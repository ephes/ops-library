"""Reject dependency conflicts before narrowly scoped package replacement."""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "trust", ROOT / "plugins/filter/security_trust.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TrustPreflightTests(unittest.TestCase):
    def report(self, requirement="certifi>=2023.5.7", python="3.14"):
        return {
            "packages": {
                "certifi": {"version": "2025.1.31", "requires": []},
                "requests": {"version": "2.0", "requires": [requirement]},
            },
            "marker_environment": {"python_version": python, "extra": ""},
        }

    def test_reject_exact_pin(self):
        self.assertTrue(
            module.trust_update_conflicts(
                self.report("certifi==2025.1.31"), {"certifi": "2026.10.19"}
            )
        )

    def test_allow_compatible_and_inactive_extra(self):
        for requirement in ("certifi>=2023.5.7", 'certifi==2025.1.31; extra == "docs"'):
            self.assertEqual(
                module.trust_update_conflicts(
                    self.report(requirement), {"certifi": "2026.10.19"}
                ),
                [],
            )

    def test_no_insertion_and_no_downgrade(self):
        self.assertEqual(
            module.trust_update_conflicts(self.report("pip==20"), {"pip": "26.2.2"}), []
        )
        self.assertEqual(
            module.trust_update_conflicts(
                self.report("certifi==2025.1.31"), {"certifi": "2024.1.1"}
            ),
            [],
        )

    def test_reject_old_python_pip(self):
        report = self.report(python="3.9")
        report["packages"]["pip"] = {"version": "21.0", "requires": []}
        self.assertEqual(
            module.trust_update_conflicts(report, {"pip": "26.2.2"}),
            ["pip target requires Python >=3.10"],
        )

    def test_remote_python_markers(self):
        self.assertTrue(
            module.trust_update_conflicts(
                self.report('certifi<2026; python_version < "3.12"', "3.11"),
                {"certifi": "2026.10.19"},
            )
        )
        self.assertEqual(
            module.trust_update_conflicts(
                self.report('certifi<2026; python_version < "3.12"', "3.14"),
                {"certifi": "2026.10.19"},
            ),
            [],
        )


class TrustLockTests(unittest.TestCase):
    def test_only_certifi_stanza_may_change(self):
        old = 'version = 1\n[[package]]\nname = "certifi"\nversion = "2025.1.31"\n[[package]]\nname = "requests"\nversion = "2.0"\n'
        fixed = old.replace("2025.1.31", "2026.10.19")
        self.assertTrue(module.trust_lock_replacement_safe(old, fixed, "2026.10.19"))
        self.assertFalse(
            module.trust_lock_replacement_safe(old, fixed, "2026.10.19", "missing")
        )
        self.assertFalse(
            module.trust_lock_replacement_safe(
                old, fixed.replace('"2.0"', '"3.0"'), "2026.10.19"
            )
        )
        self.assertFalse(
            module.trust_lock_replacement_safe(
                old, fixed + "\n[changed]\na = 1\n", "2026.10.19"
            )
        )


class CollectionLoadTests(unittest.TestCase):
    def test_collection_filter_is_loadable_by_ansible(self):
        import os
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            namespace = base / "ansible_collections/local"
            namespace.mkdir(parents=True)
            (namespace / "ops_library").symlink_to(ROOT)
            play = base / "probe.yml"
            import yaml

            tasks = yaml.safe_load(
                (
                    ROOT / "roles/security_trust_remediate/tasks/environment.yml"
                ).read_text()
            )
            real_assert = next(
                t["ansible.builtin.assert"]
                for t in tasks
                if t["name"].endswith(
                    "Reject system Python and incompatible installed dependency requirements"
                )
            )
            play.write_text(
                """- hosts: localhost
  gather_facts: false
  tasks:
    - ansible.builtin.assert:
        that:
          - ({'packages':{},'marker_environment':{}} | local.ops_library.trust_update_conflicts({})) == []
"""
            )
            data = yaml.safe_load(play.read_text())
            data[0]["vars"] = {
                "security_trust_before": {
                    "prefix": "/opt/test",
                    "base_prefix": "/usr",
                    "packages": {},
                    "marker_environment": {},
                },
                "security_trust_targets": {},
                "trust_env": {"path": "/opt/test"},
            }
            data[0]["tasks"].append({"ansible.builtin.assert": real_assert})
            main = yaml.safe_load(
                (ROOT / "roles/security_trust_remediate/tasks/main.yml").read_text()
            )
            selected = [
                t
                for t in main
                if t["name"]
                in (
                    "Check completed restart evidence for every allowlisted environment",
                    "Preserve all restart requirements before OS trust can change",
                )
            ]
            evidence = base / "evidence"
            evidence.mkdir()
            data[0]["vars"].update(
                {
                    "security_trust_backup_dir": str(evidence),
                    "security_trust_ca_version": "fixed",
                    "security_trust_certifi_version": "2026.10.19",
                    "security_trust_pip_version": "26.2.2",
                    "security_trust_prior_ca": {"stdout": "old"},
                    "security_trust_environments": [
                        {"path": "/opt/first", "services": ["first"]},
                        {"path": "/opt/second", "services": ["second"]},
                    ],
                }
            )
            data[0]["tasks"].extend(selected)
            import base64

            before = (
                'version = 1\n[[package]]\nname = "certifi"\nversion = "2025.1.31"\n'
            )
            replacement = base / "uv.lock"
            replacement.write_text(
                before.replace("2025.1.31", "2026.10.19")
                + 'wheels = [{ hash = "sha256:fixed" }]\n'
            )
            lock_tasks = yaml.safe_load(
                (ROOT / "roles/security_trust_remediate/tasks/lockfile.yml").read_text()
            )
            lock_assert = next(
                t["ansible.builtin.assert"]
                for t in lock_tasks
                if t["name"].endswith("Prove only the certifi package stanza changes")
            )
            data[0]["vars"].update(
                {
                    "security_trust_lock_original": {
                        "content": base64.b64encode(before.encode()).decode()
                    },
                    "trust_lock": {"src": str(replacement)},
                    "security_trust_certifi_version": "2026.10.19",
                    "security_trust_wheels": [
                        {"package": "certifi", "sha256": "fixed"}
                    ],
                }
            )
            data[0]["tasks"].append({"ansible.builtin.assert": lock_assert})
            play.write_text(yaml.safe_dump(data))
            result = subprocess.run(
                ["ansible-playbook", "-i", "localhost,", "-c", "local", str(play)],
                check=False,
                env={**os.environ, "ANSIBLE_COLLECTIONS_PATH": directory},
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            # A fresh-host check run must not need or create the evidence directory.
            import shutil

            shutil.rmtree(evidence)
            import copy

            check_data = copy.deepcopy(data)
            check_data[0]["tasks"].append(
                next(
                    t
                    for t in main
                    if t["name"] == "Stage verified offline update wheels"
                )
            )
            check_data[0]["vars"]["security_trust_wheel_dir"] = str(
                base / "fresh-wheel-cache"
            )
            check_data[0]["vars"]["security_trust_wheels"][0].update(
                {"name": "test.whl", "src": str(replacement)}
            )
            play.write_text(yaml.safe_dump(check_data))
            checked = subprocess.run(
                [
                    "ansible-playbook",
                    "--check",
                    "-i",
                    "localhost,",
                    "-c",
                    "local",
                    str(play),
                ],
                check=False,
                env={**os.environ, "ANSIBLE_COLLECTIONS_PATH": directory},
                capture_output=True,
                text=True,
            )
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            self.assertFalse(evidence.exists())
            self.assertFalse((base / "fresh-wheel-cache").exists())
            play.write_text(yaml.safe_dump(data))
            # Matching target completion evidence suppresses a redundant OS restart.
            evidence.mkdir()
            import hashlib

            signature = hashlib.sha256(b"fixed:2026.10.19:26.2.2").hexdigest()
            for path in ("/opt/first", "/opt/second"):
                (
                    evidence
                    / (
                        hashlib.sha256(path.encode()).hexdigest()
                        + "."
                        + signature
                        + ".restart-complete"
                    )
                ).write_text("completed")
            data[0]["vars"]["security_trust_prior_ca"] = {"stdout": "fixed"}
            play.write_text(yaml.safe_dump(data))
            completed = subprocess.run(
                ["ansible-playbook", "-i", "localhost,", "-c", "local", str(play)],
                check=False,
                env={**os.environ, "ANSIBLE_COLLECTIONS_PATH": directory},
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                completed.returncode, 0, completed.stdout + completed.stderr
            )
            self.assertFalse(list(evidence.glob("*.restart-required")))
            # Restore the changed-CA case and require all restart markers.
            data[0]["vars"]["security_trust_prior_ca"] = {"stdout": "old"}
            play.write_text(yaml.safe_dump(data))
            changed = subprocess.run(
                ["ansible-playbook", "-i", "localhost,", "-c", "local", str(play)],
                check=False,
                env={**os.environ, "ANSIBLE_COLLECTIONS_PATH": directory},
                capture_output=True,
                text=True,
            )
            self.assertEqual(changed.returncode, 0, changed.stdout + changed.stderr)

            for path in ("/opt/first", "/opt/second"):
                self.assertTrue(
                    (
                        evidence
                        / (
                            hashlib.sha256(path.encode()).hexdigest()
                            + ".restart-required"
                        )
                    ).exists()
                )


class OptimizedInterpreterTests(unittest.TestCase):
    def test_system_site_packages_rejected_under_optimization(self):
        import subprocess
        import sys
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "pyvenv.cfg").write_text(
                "include-system-site-packages = true\n"
            )
            script = (
                ROOT / "roles/security_trust_remediate/files/inspect_environment.py"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-O",
                    "-c",
                    'import sys,runpy;sys.prefix=sys.argv[1];runpy.run_path(sys.argv[2],run_name="__main__")',
                    directory,
                    str(script),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("System site-packages", result.stderr)


class FreshHostCheckModeTests(unittest.TestCase):
    def test_real_role_check_mode_os_staging_and_documented_skip_boundaries(self):
        import hashlib
        import json
        import os
        import shutil
        import subprocess
        import tempfile
        import uuid

        import yaml

        if not shutil.which("docker"):
            self.skipTest("Docker is unavailable for the Linux lifecycle fixture")
        connection = subprocess.run(
            ["ansible-doc", "-t", "connection", "--json", "community.docker.docker"],
            check=False,
            capture_output=True,
            text=True,
        )
        if connection.returncode or not json.loads(connection.stdout or "{}"):
            self.skipTest(
                "community.docker is unavailable for the Linux lifecycle fixture"
            )
        image = "geerlingguy/docker-debian13-ansible:latest"
        inspected = subprocess.run(
            ["docker", "image", "inspect", image], check=False, capture_output=True
        )
        if inspected.returncode:
            self.skipTest("The Debian 13 lifecycle fixture image is not cached")
        name = "emudhra-linux-check-" + uuid.uuid4().hex[:12]
        subprocess.run(
            [
                "docker",
                "run",
                "--pull=never",
                "--rm",
                "-d",
                "--name",
                name,
                image,
                "sleep",
                "infinity",
            ],
            check=True,
            capture_output=True,
        )
        try:
            with tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                collection = base / "collections/ansible_collections/local/ops_library"
                collection.parent.mkdir(parents=True)
                collection.symlink_to(ROOT, target_is_directory=True)
                backup = "/var/backups/" + name
                cache = "/var/cache/" + name
                paths = [
                    backup,
                    cache,
                    "/usr/local/bin/uv",
                    "/usr/local/bin/uvx",
                    "/opt/security-check/venv",
                    "/opt/security-check/uv.lock",
                ]
                snapshot_code = (
                    "import hashlib,json,pathlib,subprocess; "
                    "print(json.dumps({'packages':subprocess.check_output(['dpkg-query','-W']).decode(),"
                    "'apt_lists':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() "
                    "for p in pathlib.Path('/var/lib/apt/lists').rglob('*') if p.is_file()},"
                    "'paths':{p:pathlib.Path(p).exists() for p in "
                    + repr(paths)
                    + "}}))"
                )

                def snapshot():
                    result = subprocess.run(
                        [
                            "docker",
                            "exec",
                            name,
                            "/usr/bin/python3",
                            "-c",
                            snapshot_code,
                        ],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    return json.loads(result.stdout)

                before = snapshot()
                self.assertFalse(any(before["paths"].values()), before["paths"])
                ca = subprocess.run(
                    [
                        "docker",
                        "exec",
                        name,
                        "dpkg-query",
                        "--show",
                        "--showformat=${Version}",
                        "ca-certificates",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout
                wheels = []
                for package in ("certifi", "pip"):
                    wheel = base / (package + ".whl")
                    wheel.write_bytes(b"check-mode fixture; must never be installed")
                    wheels.append(
                        {
                            "package": package,
                            "name": wheel.name,
                            "src": str(wheel),
                            "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                        }
                    )
                play = base / "check.yml"
                play.write_text(
                    yaml.safe_dump(
                        [
                            {
                                "hosts": "fixture",
                                "gather_facts": True,
                                "vars": {
                                    "security_trust_ca_version": ca,
                                    "security_trust_backup_dir": backup,
                                    "security_trust_wheel_dir": cache,
                                    "security_trust_wheels": wheels,
                                    "security_trust_environments": [
                                        {
                                            "path": paths[4],
                                            "services": ["fixture.service"],
                                            "health_urls": [
                                                {"url": "http://127.0.0.1:1/"}
                                            ],
                                        }
                                    ],
                                    "security_trust_lockfiles": [{"path": paths[5]}],
                                },
                                "roles": ["local.ops_library.security_trust_remediate"],
                            }
                        ]
                    )
                )
                inventory = base / "inventory.yml"
                inventory.write_text(
                    yaml.safe_dump(
                        {
                            "all": {
                                "hosts": {
                                    "fixture": {
                                        "ansible_host": name,
                                        "ansible_connection": "community.docker.docker",
                                        "ansible_python_interpreter": "/usr/bin/python3",
                                    }
                                }
                            }
                        }
                    )
                )
                callbacks = base / "callbacks"
                callbacks.mkdir()
                (callbacks / "trust_lifecycle.py").write_text(
                    "import json\nfrom ansible.plugins.callback import CallbackBase\n"
                    "class CallbackModule(CallbackBase):\n"
                    " CALLBACK_VERSION=2.0\n CALLBACK_TYPE='stdout'\n CALLBACK_NAME='trust_lifecycle'\n"
                    " def emit(self,result,status):\n"
                    "  self._display.display(json.dumps({'task':result._task.get_name(),'status':status,"
                    "'changed':result._result.get('changed',False),'msg':result._result.get('msg','')}))\n"
                    " def v2_runner_on_ok(self,result): self.emit(result,'ok')\n"
                    " def v2_runner_on_skipped(self,result): self.emit(result,'skipped')\n"
                    " def v2_runner_on_failed(self,result,ignore_errors=False): self.emit(result,'failed')\n"
                )

                def run_check():
                    return subprocess.run(
                        [
                            "ansible-playbook",
                            "--check",
                            "-i",
                            str(inventory),
                            str(play),
                        ],
                        check=False,
                        env={
                            **os.environ,
                            "ANSIBLE_COLLECTIONS_PATH": str(base / "collections"),
                            "ANSIBLE_CALLBACK_PLUGINS": str(callbacks),
                            "ANSIBLE_STDOUT_CALLBACK": "trust_lifecycle",
                        },
                        capture_output=True,
                        text=True,
                    )

                checked = run_check()
                print(checked.stdout)
                self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
                results = {
                    event["task"].split(" : ")[-1]: event
                    for event in (
                        json.loads(line)
                        for line in checked.stdout.splitlines()
                        if line.startswith('{"task":')
                    )
                }
                for task in (
                    "Validate explicit incident scope",
                    "Validate every environment before OS mutation or restart evidence",
                    "Read installed distribution CA revision before any update",
                    "Refresh indexes and install only the pinned CA package",
                ):
                    self.assertEqual(results[task]["status"], "ok", results)
                for task in (
                    "Preserve all restart requirements before OS trust can change",
                    "Stage verified offline update wheels",
                    "Repair explicitly guarded deployed trust lockfiles",
                    "Remediate only explicit environment allowlist",
                ):
                    self.assertEqual(results[task]["status"], "skipped", results)
                # An unavailable changed CA pin must fail closed without changing the snapshot.
                changed_play = yaml.safe_load(play.read_text())
                changed_play[0]["vars"][
                    "security_trust_ca_version"
                ] = "0.0.0-unavailable-fixture"
                play.write_text(yaml.safe_dump(changed_play))
                rejected = run_check()
                print(rejected.stdout)
                self.assertNotEqual(
                    rejected.returncode, 0, rejected.stdout + rejected.stderr
                )
                rejected_results = {
                    event["task"].split(" : ")[-1]: event
                    for event in (
                        json.loads(line)
                        for line in rejected.stdout.splitlines()
                        if line.startswith('{"task":')
                    )
                }
                self.assertEqual(
                    rejected_results[
                        "Refresh indexes and install only the pinned CA package"
                    ]["status"],
                    "failed",
                    rejected_results,
                )
                self.assertEqual(
                    snapshot(),
                    before,
                    checked.stdout + checked.stderr + rejected.stdout + rejected.stderr,
                )
                print(
                    "Fresh-host lifecycle unchanged:",
                    json.dumps(
                        {
                            "package_metadata_sha256": hashlib.sha256(
                                before["packages"].encode()
                            ).hexdigest(),
                            "apt_index_files": len(before["apt_lists"]),
                            "paths": before["paths"],
                        },
                        sort_keys=True,
                    ),
                )
        finally:
            subprocess.run(
                ["docker", "rm", "-f", name], check=False, capture_output=True
            )
