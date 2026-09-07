"""Executable contracts for read-only software observations and their consumers."""

import ast
import base64
import copy
import importlib.util
import json
import sqlite3
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "roles/software_live/files" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


live = load("software_live")
checks = load("nyxmon_checks")
POLICY = {
    "host": "example",
    "traefik": {
        "expected": True,
        "unit": "traefik.service",
        "binary_path": "/usr/local/bin/traefik",
        "desired_version": "3.7.9",
    },
}
BINARY = {"version": "3.7.9", "sha256": "same-bytes"}
LATEST = {"status": "ok", "version": "3.7.9"}


class CollectorTests(unittest.TestCase):
    def proxy(
        self,
        binaries=None,
        pids=None,
        target="/usr/local/bin/traefik",
        latest=None,
        policy=None,
    ):
        with (
            patch.object(live, "main_pid", side_effect=pids or [11, 11]),
            patch.object(live, "binary_info", side_effect=binaries or [BINARY, BINARY]),
            patch.object(live.os, "readlink", return_value=target),
            patch.object(
                live.os.path, "realpath", return_value=POLICY["traefik"]["binary_path"]
            ),
            patch.object(live.Path, "exists", return_value=True),
        ):
            return live.observe_traefik(policy or POLICY["traefik"], latest or LATEST)

    def test_deployed_programs_support_python_311(self):
        for program in (live, checks):
            ast.parse(Path(program.__file__).read_text(), feature_version=(3, 11))

    def test_numeric_release_comparison(self):
        self.assertLess(live.version("v3.7.9"), live.version("3.7.12"))
        for invalid in ["3.7", "3.7.12-rc1", "development", "3.7.12 junk"]:
            with self.assertRaises(ValueError):
                live.version(invalid)

    def test_matching_process_and_binary(self):
        self.assertEqual(self.proxy()["status"], "ok")

    def test_replaced_disk_binary_is_not_a_completed_update(self):
        new = {"version": "3.7.12", "sha256": "new-bytes"}
        result = self.proxy([new, BINARY])
        self.assertIn("installed_running_drift", result["issues"])
        self.assertEqual(result["running"]["version"], "3.7.9")

    def test_same_version_different_bytes_is_drift(self):
        result = self.proxy([BINARY, {**BINARY, "sha256": "different"}])
        self.assertIn("installed_running_drift", result["issues"])

    def test_unknown_upstream_never_passes(self):
        self.assertEqual(self.proxy(latest={"status": "unknown"})["status"], "unknown")

    def test_new_upstream_and_unassigned_desired_are_visible(self):
        policy = {**POLICY["traefik"], "desired_version": None}
        result = self.proxy(policy=policy, latest={"status": "ok", "version": "3.7.12"})
        self.assertIn("desired_version_unassigned", result["issues"])
        self.assertIn("outdated_running_version", result["issues"])

    def test_deleted_and_wrong_paths_are_visible(self):
        result = self.proxy(target="/usr/bin/traefik (deleted)")
        self.assertIn("deleted_running_executable", result["issues"])
        self.assertIn("running_path_mismatch", result["issues"])

    def test_unexpected_process_image_is_never_executed(self):
        running = {"version": None, "sha256": "different-bytes"}
        for target in (
            "/memfd:payload (deleted)",
            "/tmp/other",
            "/usr/local/bin/traefik (deleted)",
        ):
            with (
                patch.object(live, "main_pid", return_value=11),
                patch.object(live.Path, "exists", return_value=True),
                patch.object(live.os, "readlink", return_value=target),
                patch.object(
                    live.os.path,
                    "realpath",
                    return_value=POLICY["traefik"]["binary_path"],
                ),
                patch.object(
                    live, "binary_info", side_effect=[BINARY, running]
                ) as probe,
            ):
                result = live.observe_traefik(POLICY["traefik"], LATEST)
                self.assertEqual(result["status"], "warning")
                self.assertTrue(result["observed"])
                self.assertEqual(result["installed"], BINARY)
                self.assertEqual(result["running"], running)
                self.assertIn("installed_running_drift", result["issues"])
                probe.assert_any_call("/proc/11/exe", probe_version=False)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proxy"
            path.write_text("unexpected bytes")
            with patch.object(live, "command") as execute:
                info = live.binary_info(str(path), probe_version=False)
                self.assertIsNone(info["version"])
                self.assertEqual(
                    info["sha256"], live.hashlib.sha256(b"unexpected bytes").hexdigest()
                )
                execute.assert_not_called()
            # Re-exec after the first link check is caught on the pinned descriptor.
            with (
                patch.object(
                    live.os, "readlink", return_value="/memfd:payload (deleted)"
                ),
                patch.object(
                    live.os.path, "realpath", return_value="/usr/local/bin/traefik"
                ),
                patch.object(live, "command") as execute,
                self.assertRaises(ValueError),
            ):
                live.binary_info(str(path), expected_target="/usr/local/bin/traefik")
            execute.assert_not_called()

    def test_upstream_failure_warns_without_claiming_local_collection_failed(self):
        observed = self.proxy(latest={"status": "unknown"})
        with (
            patch.object(live, "upstream", return_value={"status": "unknown"}),
            patch.object(live, "observe_traefik", return_value=observed),
            patch.object(
                live,
                "observe_apt",
                return_value={
                    "status": "ok",
                    "pending_security_count": 0,
                    "indexes_fresh": True,
                },
            ),
        ):
            summary = live.collect(POLICY)["summary"]
        self.assertTrue(summary["observation_ok"])
        self.assertFalse(summary["traefik_ok"])

    def test_bounded_pid_retry(self):
        self.assertEqual(self.proxy([BINARY] * 4, [11, 12, 12, 12])["main_pid"], 12)
        self.assertEqual(
            self.proxy([BINARY] * 4, [11, 12, 13, 14])["status"], "unknown"
        )

    def test_stopped_service_and_probe_errors_are_unknown(self):
        self.assertEqual(self.proxy(pids=[0])["status"], "unknown")
        with patch.object(live, "main_pid", side_effect=OSError("gone")):
            self.assertEqual(
                live.observe_traefik(POLICY["traefik"], LATEST)["status"], "unknown"
            )

    def test_expected_absence_and_unexpected_other_path(self):
        policy = {**POLICY["traefik"], "expected": False}
        with (
            patch.object(live, "main_pid", return_value=0),
            patch.object(live.Path, "exists", return_value=False),
        ):
            self.assertEqual(live.observe_traefik(policy, LATEST)["status"], "ok")
        with (
            patch.object(live, "main_pid", return_value=0),
            patch.object(live.Path, "exists", side_effect=lambda: True),
        ):
            self.assertEqual(live.observe_traefik(policy, LATEST)["status"], "warning")

    def test_binary_identity_and_in_place_change(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proxy"
            path.write_text('#!/bin/sh\nprintf "Version: 3.7.9\\n"\n')
            path.chmod(0o755)
            self.assertEqual(live.binary_info(str(path))["version"], "3.7.9")

            def replace(_, **_kwargs):
                path.write_text("different bytes")
                return "Version: 3.7.9"

            with (
                patch.object(live, "command", side_effect=replace),
                self.assertRaises(ValueError),
            ):
                live.binary_info(str(path))

    def test_failed_upstream_refresh_retains_old_timestamp_only_as_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            old = {"version": "3.7.9", "checked_at_epoch": 1}
            path.write_text(json.dumps(old))
            with patch.object(
                live.urllib.request, "urlopen", side_effect=OSError("offline")
            ):
                result = live.upstream(path, 100000)
            self.assertEqual(result["status"], "unknown")
            self.assertEqual(result["last_success"], old)
            self.assertEqual(json.loads(path.read_text()), old)

    def test_upstream_daily_cache_and_unparseable_release(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            response = Mock()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            response.read.return_value = b'{"tag_name":"v3.7.12"}'
            with patch.object(
                live.urllib.request, "urlopen", return_value=response
            ) as fetch:
                self.assertEqual(live.upstream(path, 100)["version"], "3.7.12")
                self.assertTrue(live.upstream(path, 101)["cached"])
                self.assertEqual(fetch.call_count, 1)
                response.read.return_value = b'{"tag_name":"garbage"}'
                self.assertEqual(live.upstream(path, 100000)["status"], "unknown")

    def test_atomic_state_permissions_and_failure_preserves_previous(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            live.atomic_json(path, {"healthy": False})
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            with self.assertRaises(TypeError):
                live.atomic_json(path, {"bad": object()})
            self.assertEqual(json.loads(path.read_text()), {"healthy": False})
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_cached_timestamp_is_used_not_file_touch(self):
        state = {
            "schema_version": 1,
            "generated_at_epoch": 1,
            "summary": {
                "observation_ok": True,
                "traefik_ok": True,
                "security_updates_ok": True,
                "apt_indexes_fresh": True,
            },
        }
        self.assertFalse(
            live.with_freshness(copy.deepcopy(state), now=2000)["summary"]["fresh"]
        )
        self.assertFalse(
            live.with_freshness(copy.deepcopy(state), now=0)["summary"]["fresh"]
        )
        self.assertTrue(
            live.with_freshness(copy.deepcopy(state), now=2)["summary"]["fresh"]
        )
        for bad in [
            {},
            {**state, "generated_at_epoch": "now"},
            {**state, "generated_at_epoch": float("nan")},
            {**state, "summary": {}},
        ]:
            with self.assertRaises((ValueError, KeyError)):
                live.with_freshness(bad)

    def test_security_packages_include_held_and_pinned_versions(self):
        origin = SimpleNamespace(
            trusted=True,
            origin="Debian",
            archive="bookworm-security",
            label="Debian-Security",
        )
        good = SimpleNamespace(version="2", origins=[origin])
        current = SimpleNamespace(version="1")
        package = SimpleNamespace(
            name="codec",
            fullname="codec:amd64",
            installed=current,
            candidate=current,
            versions=[good, current],
        )
        result = live.security_packages(
            [package], lambda a, b: int(a) - int(b), {"codec"}
        )
        self.assertTrue(result[0]["held"])
        self.assertEqual(result[0]["candidate"], "1")
        self.assertEqual(result[0]["security_version"], "2")
        origin.trusted = False
        self.assertEqual(
            live.security_packages([package], lambda a, b: int(a) - int(b), set()), []
        )

    def test_invalid_policy_and_public_bind_fail(self):
        for path in ["/bin/sh", "/tmp/proxy"]:
            with self.assertRaises(ValueError):
                live.validate_policy(
                    {**POLICY, "traefik": {**POLICY["traefik"], "binary_path": path}}
                )
        with (
            patch(
                "sys.argv",
                ["software_live", "serve", "--config-json", '{"bind":"0.0.0.0"}'],
            ),
            self.assertRaises(ValueError),
        ):
            live.main()


class EndpointTests(unittest.TestCase):
    def test_http_auth_freshness_and_malformed_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            state.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "generated_at_epoch": 1,
                        "summary": {
                            "observation_ok": True,
                            "traefik_ok": True,
                            "security_updates_ok": True,
                            "apt_indexes_fresh": True,
                        },
                    }
                )
            )
            server = live.http.server.HTTPServer(("127.0.0.1", 0), live.Handler)
            server.config = {
                "path": "/health",
                "state": str(state),
                "htpasswd": "/unused",
                "auth_user": "monitor",
            }
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f"http://127.0.0.1:{server.server_port}/health"
            try:
                with self.assertRaises(urllib.error.HTTPError) as missing:
                    urllib.request.urlopen(url)
                self.assertEqual(missing.exception.code, 401)
                missing.exception.close()
                authorization = (
                    "Basic " + base64.b64encode(b"monitor:fixture-value").decode()
                )
                request = urllib.request.Request(
                    url, headers={"Authorization": authorization}
                )
                with patch.object(live.subprocess, "run"):
                    with urllib.request.urlopen(request) as response:
                        self.assertFalse(json.load(response)["summary"]["fresh"])
                    state.write_text("{broken")
                    with self.assertRaises(urllib.error.HTTPError) as broken:
                        urllib.request.urlopen(request)
                    self.assertEqual(broken.exception.code, 503)
                    broken.exception.close()
                with patch.object(
                    live.subprocess,
                    "run",
                    side_effect=subprocess.CalledProcessError(1, "htpasswd"),
                ):
                    with self.assertRaises(urllib.error.HTTPError) as denied:
                        urllib.request.urlopen(request)
                    self.assertEqual(denied.exception.code, 401)
                    denied.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


class NyxmonTests(unittest.TestCase):
    def test_idempotent_targeted_upsert_and_reenable(self):
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / "db.sqlite3")
            with closing(sqlite3.connect(db)) as connection:
                connection.executescript(
                    "CREATE TABLE service(id INTEGER PRIMARY KEY,name TEXT); CREATE TABLE health_check(id INTEGER PRIMARY KEY,name TEXT,service_id INTEGER,check_type TEXT,url TEXT,check_interval INTEGER,data TEXT,status TEXT,next_check_time INTEGER,processing_started_at INTEGER,disabled INTEGER);"
                )
            item = {
                "service": "Live software health",
                "name": "Example",
                "url": "http://127.0.0.1/health",
                "interval": 3600,
                "data": {"checks": []},
            }
            self.assertTrue(checks.upsert(db, [item]))
            self.assertFalse(checks.upsert(db, [item]))
            with closing(sqlite3.connect(db)) as connection:
                connection.execute("UPDATE health_check SET disabled=1")
                connection.commit()
            self.assertTrue(checks.upsert(db, [item]))
            with closing(sqlite3.connect(db)) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM health_check").fetchone()[
                        0
                    ],
                    1,
                )
            other = {**item, "name": "Unrelated"}
            checks.upsert(db, [other])
            self.assertTrue(checks.disable(db, ["Example"]))
            self.assertFalse(checks.disable(db, ["Example"]))
            with closing(sqlite3.connect(db)) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT name, disabled FROM health_check ORDER BY name"
                    ).fetchall(),
                    [("Example", 1), ("Unrelated", 0)],
                )
            with self.assertRaises(sqlite3.OperationalError):
                checks.upsert(str(Path(directory) / "missing.sqlite3"), [item])


if __name__ == "__main__":
    unittest.main()
