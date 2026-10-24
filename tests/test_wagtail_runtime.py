"""Exercise extracted runtime tasks locally with a recording uv, never a download."""

import getpass
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import venv
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/wagtail_deploy"
ANSIBLE = shutil.which("ansible-playbook")


@unittest.skipUnless(ANSIBLE, "ansible-playbook required")
class RuntimeTests(unittest.TestCase):
    def run_case(
        self,
        installed=False,
        fail_install=False,
        fail_trust=False,
        normal=False,
        version="3.15.1",
        expected="3.15.1",
    ):
        with tempfile.TemporaryDirectory(prefix="wagtail-runtime-") as td:
            base = Path(td)
            # Installed-runtime fixture is isolated from the test runner environment.
            # Never seed pip or inherit its externally visible packages.
            venv.EnvBuilder(with_pip=False, system_site_packages=False).create(
                base / "runtime"
            )
            runtime_python = base / "runtime/bin/python"
            marker = base / "installed"
            calls = base / "calls"
            if installed:
                marker.touch()
            uv = base / "uv"
            uv.write_text(
                "#!"
                + sys.executable
                + "\n"
                + f"""
import sys,json
from pathlib import Path
marker=Path({str(marker)!r}); calls=Path({str(calls)!r})
with calls.open('a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')
if 'install' in sys.argv:
    if {fail_install!r}: sys.exit(7)
    marker.touch(); sys.exit(0)
if not marker.exists(): sys.exit(1)
print({str(base / "bad-python") if fail_trust else str(runtime_python)!r})
"""
            )
            uv.chmod(0o700)
            bad = base / "bad-python"
            bad.write_text("#!/bin/sh\nexit 9\n")
            bad.chmod(0o700)
            tasks = yaml.safe_load((ROLE / "tasks/runtime.yml").read_text())
            # The first task is the existing independently tested uv_install role.
            self.assertEqual(
                tasks[1]["ansible.builtin.import_role"]["name"], "uv_install"
            )
            (base / "runtime.yml").write_text(yaml.safe_dump([tasks[0], *tasks[2:]]))
            defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
            defaults.update(
                wagtail_user=getpass.getuser(),
                wagtail_home=str(base),
                wagtail_uv_path=str(uv),
                wagtail_python_version=version,
                wagtail_runtime_expected_version=expected,
                wagtail_runtime_verify_trust=True,
                ansible_become=False,
                wagtail_runtime_notify_restarts=normal,
                wagtail_runtime_install_bin=normal,
            )
            play = [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "vars": defaults,
                    "tasks": [
                        {"ansible.builtin.include_tasks": str(base / "runtime.yml")},
                        {"ansible.builtin.debug": {"msg": "RUNTIME-COMPLETE"}},
                    ],
                }
            ]
            play[0]["handlers"] = [
                {"name": name, "ansible.builtin.debug": {"msg": name}}
                for name in ("restart wagtail", "restart wagtail db worker")
            ]
            (base / "play.yml").write_text(yaml.safe_dump(play))
            env = {k: v for k, v in os.environ.items() if not k.startswith("ANSIBLE_")}
            collection = base / "collections/ansible_collections/local"
            collection.mkdir(parents=True)
            (collection / "ops_library").symlink_to(ROOT, target_is_directory=True)
            env.update(
                ANSIBLE_COLLECTIONS_PATH=str(base / "collections"),
                ANSIBLE_ROLES_PATH=str(ROOT / "roles"),
                ANSIBLE_FILTER_PLUGINS=str(ROOT / "plugins/filter"),
            )
            result = subprocess.run(
                [ANSIBLE, "-i", "localhost,", str(base / "play.yml")],
                env=env,
                capture_output=True,
                text=True,
                timeout=90,
            )
            recorded = [
                json.loads(line)
                for line in (calls.read_text().splitlines() if calls.exists() else [])
            ]
            return result, recorded

    def test_missing_runtime_installs_without_bin_or_restart(self):
        result, calls = self.run_case()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(["--no-config", "python", "install", "--no-bin", "3.15.1"], calls)
        self.assertIn("RUNTIME-COMPLETE", result.stdout)
        self.assertNotIn("RUNNING HANDLER", result.stdout)

    def test_existing_runtime_does_not_install(self):
        result, calls = self.run_case(installed=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(any("install" in c for c in calls))
        self.assertTrue(all("--no-python-downloads" in c for c in calls))

    def test_failed_install_stops_before_trust_or_completion(self):
        result, _ = self.run_case(fail_install=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Install requested Python version via uv", result.stdout)
        self.assertIn('"rc": 7', result.stdout)
        self.assertIn("fatal:", result.stdout)
        self.assertNotIn("RUNTIME-COMPLETE", result.stdout)

    def test_failed_trust_stops_completion(self):
        result, _ = self.run_case(installed=True, fail_trust=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Inspect the trust bundles", result.stdout)
        self.assertIn('"rc": 9', result.stdout)
        self.assertIn("fatal:", result.stdout)
        self.assertNotIn("RUNTIME-COMPLETE", result.stdout)

    def test_normal_deploy_retains_bin_and_restart_notifications(self):
        result, calls = self.run_case(normal=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(["--no-config", "python", "install", "3.15.1"], calls)
        self.assertEqual(result.stdout.count("RUNNING HANDLER"), 2)

    def test_standalone_missing_minor_or_mismatched_patch_refused(self):
        for version, expected in [
            ("3.15.1", ""),
            ("3.15", "3.15"),
            ("", ""),
            ("3.14.8", "3.15.1"),
        ]:
            with self.subTest(version=version, expected=expected):
                result, calls = self.run_case(version=version, expected=expected)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn(
                    "Require an explicit exact standalone patch", result.stdout
                )
                self.assertFalse(calls, result.stdout + result.stderr)
