"""Actual original tasks and authenticated WS against owned stale disk fixtures."""

import asyncio
import base64
import getpass
import importlib.util
import json
import os
from pathlib import Path
import ssl
import sys
import tempfile
import unittest

from aiohttp import web
import yaml

from tests.test_homeassistant_assist_autodetection import selected_tasks, variables

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/homeassistant_deploy"
SPEC = importlib.util.spec_from_file_location(
    "owned_registry", ROLE / "files/assist_registry.py"
)
HELPER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HELPER)
OWNED_AUTH_VALUE = "owned-registry-test-only"


class LiveRegistry(unittest.IsolatedAsyncioTestCase):
    def test_check_mode_missing_or_null_data_keeps_original_empty_selection(self):
        from ansible.parsing.dataloader import DataLoader
        from ansible.template import Templar, trust_as_template

        tasks = yaml.safe_load((ROLE / "tasks/assist_registry.yml").read_text())
        task = next(
            task
            for task in tasks
            if task["name"].endswith(
                "Retain saved engine identifiers for check mode only"
            )
        )
        expression = task["ansible.builtin.set_fact"]["_ha_assist_registry_entities"]
        for document in ({}, {"data": None}, {"data": {}}):
            loader = DataLoader()
            templar = Templar(
                loader=loader,
                variables={
                    "_ha_assist_registry_saved_raw": {
                        "content": base64.b64encode(
                            json.dumps(document).encode()
                        ).decode()
                    }
                },
            )
            self.assertEqual(templar.template(trust_as_template(expression)), [])

    async def asyncSetUp(self):
        self.calls = []
        self.fault = ""
        self.empty_queries = 0
        self.ready_calls = 0
        self.entities = [
            {
                "entity_id": kind + suffix,
                "platform": platform,
                "config_entry_id": entry,
                "disabled_by": disabled,
                "options": {"private": "must-not-return"},
            }
            for kind in ("stt", "tts")
            for suffix, platform, entry, disabled in (
                (".disabled", "wyoming", "owned-entry", "user"),
                (".other_platform", "other", "owned-entry", None),
                (".other_entry", "wyoming", "other-entry", None),
                (".owned", "wyoming", "owned-entry", None),
            )
        ]

        async def ws(request):
            connection = web.WebSocketResponse()
            await connection.prepare(request)
            await connection.send_json({"type": "auth_required"})
            auth = await connection.receive_json()
            self.assertEqual(auth, {"type": "auth", "access_token": OWNED_AUTH_VALUE})
            await connection.send_json(
                {"type": "auth_invalid" if self.fault == "auth" else "auth_ok"}
            )
            if self.fault == "auth":
                await connection.close()
                return connection
            body = await connection.receive_json()
            self.calls.append(body)
            self.assertEqual(body, {"id": 1, "type": "config/entity_registry/list"})
            if self.fault == "stall":
                await asyncio.sleep(0.1)
                await connection.close()
                return connection
            entities = self.entities
            if self.empty_queries:
                entities = []
                self.empty_queries -= 1
            await connection.send_json(
                {
                    "id": 1,
                    "success": self.fault != "query",
                    "result": {} if self.fault == "malformed" else entities,
                }
            )
            await connection.close()
            return connection

        async def ready(request):
            self.assertEqual(
                request.headers["Authorization"], "Bearer " + OWNED_AUTH_VALUE
            )
            self.ready_calls += 1
            return web.Response(text="{}", content_type="application/json")

        app = web.Application()
        app.router.add_get("/api/", ready)
        app.router.add_get("/api/websocket", ws)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.url = "http://127.0.0.1:" + str(site._server.sockets[0].getsockname()[1])

    async def asyncTearDown(self):
        await self.runner.cleanup()

    def payload(self):
        return {"url": self.url, "token": OWNED_AUTH_VALUE, "timeout": 2}

    async def test_live_projection_and_failure_controls(self):
        report = await HELPER.query(self.payload())
        encoded = json.dumps(report)
        self.assertNotIn("must-not-return", encoded)
        self.assertNotIn("disabled", encoded)
        self.assertNotIn(OWNED_AUTH_VALUE, encoded)
        self.assertTrue(
            (await HELPER.query({**self.payload(), "entity_id": "stt.owned"}))["ready"]
        )
        self.assertFalse(
            (await HELPER.query({**self.payload(), "entity_id": "stt.disabled"}))[
                "ready"
            ]
        )
        for fault in ("auth", "query", "malformed"):
            self.fault = fault
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                await HELPER.query(self.payload())

    async def test_command_failure_is_bounded_and_does_not_expose_response_or_auth(
        self,
    ):
        for fault in ("auth", "query", "malformed", "stall"):
            self.fault = fault
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                "-B",
                str(ROLE / "files/assist_registry.py"),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                out, err = await asyncio.wait_for(
                    proc.communicate(
                        json.dumps({**self.payload(), "timeout": 0.03}).encode()
                    ),
                    5,
                )
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.communicate()
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(json.loads(out), {"success": False})
            self.assertEqual(err, b"")
            self.assertNotIn(OWNED_AUTH_VALUE.encode(), out)

    async def test_matching_engine_readiness_uses_existing_retry_bound(self):
        self.empty_queries = 1
        result = await HELPER.query(
            {
                **self.payload(),
                "entry_id": "owned-entry",
                "kinds": ["stt", "tts"],
                "retries": 1,
                "delay": 0,
            }
        )
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(
            HELPER.selection_ready(
                result["entities"], {"entry_id": "owned-entry", "kinds": ["stt", "tts"]}
            )
        )
        self.calls.clear()
        result = await HELPER.query(
            {
                **self.payload(),
                "entry_id": "absent",
                "kinds": ["stt"],
                "retries": 2,
                "delay": 0,
            }
        )
        self.assertEqual(len(self.calls), 3)
        self.assertFalse(
            HELPER.selection_ready(
                result["entities"], {"entry_id": "absent", "kinds": ["stt"]}
            )
        )

    async def test_actual_tls_validation_policy(self):
        with tempfile.TemporaryDirectory(prefix="ha-registry-tls-") as directory:
            root = Path(directory)
            key, certificate = root / "owned.key", root / "owned.crt"
            proc = await asyncio.create_subprocess_exec(
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-subj",
                "/CN=owned-registry.invalid",
                "-keyout",
                str(key),
                "-out",
                str(certificate),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                await asyncio.wait_for(proc.communicate(), 20)
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.communicate()
            self.assertEqual(proc.returncode, 0)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certificate, key)
            site = web.TCPSite(self.runner, "127.0.0.1", 0, ssl_context=context)
            await site.start()
            url = "https://127.0.0.1:" + str(site._server.sockets[0].getsockname()[1])
            from aiohttp import ClientConnectorCertificateError

            with self.assertRaises(ClientConnectorCertificateError):
                await HELPER.query(
                    {**self.payload(), "url": url, "validate_certs": True}
                )
            result = await HELPER.query(
                {**self.payload(), "url": url, "validate_certs": False}
            )
            self.assertTrue(result["success"])

    async def test_actual_original_both_paths_ignore_stale_disk_and_preserve_explicit(
        self,
    ):
        with tempfile.TemporaryDirectory(prefix="ha-live-registry-") as directory:
            root = Path(directory)
            saved = root / ".storage/core.entity_registry"
            saved.parent.mkdir()
            saved.write_text('{"data":{"entities":[]}}')
            before = (saved.read_bytes(), saved.stat().st_mtime_ns)
            plays = []
            for filename in ("assist_pipelines.yml", "assist_pipeline_stt.yml"):
                for explicit in (False, True):
                    values = variables([])
                    values.update(
                        homeassistant_user=getpass.getuser(),
                        role_path=str(ROLE),
                        homeassistant_virtualenv_path=sys.prefix,
                        homeassistant_api_url=self.url,
                        homeassistant_api_token=OWNED_AUTH_VALUE,
                        homeassistant_api_timeout=2,
                        homeassistant_api_validate_certs=True,
                        homeassistant_api_retries=1,
                        homeassistant_api_retry_delay=0,
                        homeassistant_api_forwarded_proto="http",
                        _ha_api_ready_once=False,
                        homeassistant_app_port=8123,
                        homeassistant_config_path=str(root),
                        ansible_become=False,
                        ansible_python_interpreter=sys.executable,
                    )
                    tasks = selected_tasks(filename)
                    keys = [
                        next(iter(task["ansible.builtin.set_fact"])) for task in tasks
                    ]
                    if explicit:
                        values["homeassistant_assist_pipelines"][0].update(
                            stt_engine_id="stt.explicit", tts_engine_id="tts.explicit"
                        )
                        values.update(dict(zip(keys, ("stt.explicit", "tts.explicit"))))
                    original = yaml.safe_load(
                        (
                            ROOT
                            / "tests/fixtures/homeassistant_assist_registry_original.yml"
                        ).read_text()
                    )[filename]["tasks"]
                    negative = (
                        []
                        if explicit
                        else [
                            *original,
                            {
                                "name": "Assert original stale disk cannot resolve engines",
                                "ansible.builtin.assert": {
                                    "that": [key + " == ''" for key in keys]
                                },
                            },
                        ]
                    )
                    plays.append(
                        {
                            "name": filename + str(explicit),
                            "hosts": "localhost",
                            "gather_facts": False,
                            "vars": values,
                            "tasks": [
                                {"ansible.builtin.set_fact": values, "no_log": True},
                                *negative,
                                {
                                    "ansible.builtin.include_tasks": str(
                                        ROLE / "tasks/assist_registry.yml"
                                    ),
                                    "when": not explicit,
                                },
                                *tasks,
                                {
                                    "name": "Assert live engines without persisted entities",
                                    "ansible.builtin.assert": {
                                        "that": [
                                            key
                                            + " == "
                                            + repr(
                                                kind
                                                + (
                                                    ".explicit"
                                                    if explicit
                                                    else ".owned"
                                                )
                                            )
                                            for key, kind in zip(keys, ("stt", "tts"))
                                        ]
                                    },
                                },
                            ],
                        }
                    )
            play = root / "owned.yml"
            play.write_text(yaml.safe_dump(plays, sort_keys=False))
            config = root / "ansible.cfg"
            config.write_text(
                "[defaults]\nretry_files_enabled=False\nlog_path=/dev/null\nfact_caching=memory\n"
            )
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "ansible.cli.playbook",
                "-i",
                "localhost,",
                "-c",
                "local",
                str(play),
                cwd=root,
                env={
                    **os.environ,
                    "ANSIBLE_CONFIG": str(config),
                    "ANSIBLE_LOCAL_TEMP": str(root / "local"),
                },
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await asyncio.wait_for(proc.communicate(), 40)
            self.assertEqual(proc.returncode, 0, (out + err).decode())
            self.assertIn(b"Assert live engines without persisted entities", out)
            self.assertIn(b"failed=0", out)
            self.assertNotIn(OWNED_AUTH_VALUE.encode(), out + err)
            self.assertEqual(len(self.calls), 2)  # Explicit settings never query.
            self.assertEqual((saved.read_bytes(), saved.stat().st_mtime_ns), before)

    async def test_actual_role_identity_precedence_and_unresolved_failure(self):
        with tempfile.TemporaryDirectory(prefix="ha-registry-identity-") as directory:
            root = Path(directory)
            plays = []
            for filename in ("assist_pipelines.yml", "assist_pipeline_stt.yml"):
                source = yaml.safe_load((ROLE / "tasks" / filename).read_text())
                prefix = []
                for task in source:
                    if (
                        task.get("ansible.builtin.include_tasks")
                        == "assist_registry.yml"
                    ):
                        task["ansible.builtin.include_tasks"] = str(
                            ROLE / "tasks/assist_registry.yml"
                        )
                    prefix.append(task)
                    if task["name"].startswith("Validate "):
                        break
                for identity in ("known", "saved", "missing"):
                    config = root / (filename + identity)
                    storage = config / ".storage"
                    storage.mkdir(parents=True)
                    (storage / "core.entity_registry").write_text(
                        '{"data":{"entities":[]}}'
                    )
                    (storage / "core.config_entries").write_text(
                        json.dumps(
                            {
                                "data": {
                                    "entries": [
                                        {
                                            "domain": "wyoming",
                                            "entry_id": entry,
                                            "data": {"host": host, "port": port},
                                        }
                                        for host, port, entry in (
                                            ("other", 10300, "wrong-host"),
                                            ("owned", "10300", "wrong-type"),
                                            ("owned", 10300, "owned-entry"),
                                            ("owned", 10300, "later"),
                                        )
                                    ]
                                    if identity == "saved"
                                    else []
                                }
                            }
                        )
                    )
                    (storage / "assist_pipeline.pipelines").write_text(
                        json.dumps(
                            {
                                "data": {
                                    "preferred_item": "owned-pipeline",
                                    "items": [
                                        {"id": "owned-pipeline", "language": "en"}
                                    ],
                                }
                            }
                        )
                    )
                    values = {
                        "_owned_failed": False,
                        "_ha_wyoming_entry_id": "owned-entry"
                        if identity == "known"
                        else "",
                        "role_path": str(ROLE),
                        "homeassistant_virtualenv_path": sys.prefix,
                        "homeassistant_user": getpass.getuser(),
                        "ansible_become": False,
                        "ansible_python_interpreter": sys.executable,
                        "ansible_date_time": {"epoch": "owned"},
                        "homeassistant_api_url": self.url,
                        "homeassistant_api_token": OWNED_AUTH_VALUE,
                        "homeassistant_api_timeout": 2,
                        "homeassistant_api_validate_certs": True,
                        "homeassistant_api_retries": 1,
                        "homeassistant_api_retry_delay": 0,
                        "homeassistant_api_forwarded_proto": "http",
                        "_ha_api_ready_once": False,
                        "homeassistant_app_port": 8123,
                        "homeassistant_config_path": str(config),
                        "homeassistant_wyoming_host": "owned",
                        "homeassistant_wyoming_port": 10300,
                        "homeassistant_llama_cpp_enabled": False,
                        "homeassistant_assist_pipelines": [
                            {"name": "Owned", "language": "en"}
                        ],
                        "homeassistant_manage_assist_pipeline_stt_engine": True,
                        "homeassistant_manage_assist_pipeline_tts_engine": True,
                    }
                    keys = [
                        next(iter(task["ansible.builtin.set_fact"]))
                        for task in selected_tasks(filename)
                    ]
                    plays.append(
                        {
                            "name": filename + identity,
                            "hosts": "localhost",
                            "gather_facts": False,
                            "vars": values,
                            "tasks": [
                                {"ansible.builtin.set_fact": values, "no_log": True},
                                {
                                    "block": prefix,
                                    "rescue": [
                                        {
                                            "ansible.builtin.set_fact": {
                                                "_owned_failed": True
                                            }
                                        }
                                    ],
                                },
                                {
                                    "name": "Assert exact identity outcome",
                                    "ansible.builtin.assert": {
                                        "that": [
                                            "_owned_failed == "
                                            + str(identity == "missing"),
                                            *[
                                                key
                                                + " == "
                                                + repr(
                                                    ""
                                                    if identity == "missing"
                                                    else kind + ".owned"
                                                )
                                                for key, kind in zip(
                                                    keys, ("stt", "tts")
                                                )
                                            ],
                                        ]
                                    },
                                },
                            ],
                        }
                    )
            snapshots = {
                p: (p.read_bytes(), p.stat().st_mtime_ns)
                for p in root.rglob(".storage/*")
            }
            play = root / "owned.yml"
            play.write_text(yaml.safe_dump(plays, sort_keys=False))
            config = root / "ansible.cfg"
            config.write_text(
                "[defaults]\nretry_files_enabled=False\nlog_path=/dev/null\nfact_caching=memory\n"
            )
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "ansible.cli.playbook",
                "-i",
                "localhost,",
                "-c",
                "local",
                str(play),
                cwd=root,
                env={
                    **os.environ,
                    "ANSIBLE_CONFIG": str(config),
                    "ANSIBLE_LOCAL_TEMP": str(root / "local"),
                },
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                out, err = await asyncio.wait_for(proc.communicate(), 40)
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.communicate()
            self.assertEqual(proc.returncode, 0, (out + err).decode())
            self.assertIn(b"Assert exact identity outcome", out)
            self.assertEqual(len(self.calls), 6)
            self.assertNotIn(OWNED_AUTH_VALUE.encode(), out + err)
            self.assertEqual(
                {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in snapshots},
                snapshots,
            )


if __name__ == "__main__":
    unittest.main()
