"""fastdeploy_deploy mints its validation token and creates token users through FastDeploy itself."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/fastdeploy_deploy"

# A stand-in for the FastDeploy site: just enough of deploy.auth and
# commands.py to show what the helpers call and what they pass.
FAKE_AUTH = '''
import json

def create_access_token(payload, expires_delta=None):
    return "token:" + json.dumps({**payload, "ttl": expires_delta.total_seconds()}, sort_keys=True)

def get_password_hash(plain):
    assert len(plain) >= 48, "expected a long random password"
    return "hash-of-" + str(len(plain))
'''
FAKE_COMMANDS = '''
import json, os, sys
if __name__ == "__main__":
    print(json.dumps({
        "argv": sys.argv,
        "user": os.environ["INITIAL_USER_NAME"],
        "hash": os.environ["INITIAL_PASSWORD_HASH"],
        "columns": os.environ["COLUMNS"],
        "file": os.path.basename(__file__),
    }))
'''


def tasks(path: str) -> dict:
    return {t["name"]: t for t in yaml.safe_load((ROLE / path).read_text())}


def run_helper(name: str, stdin: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as site:
        package = Path(site) / "src/deploy"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("")
        (package / "auth.py").write_text(FAKE_AUTH)
        (Path(site) / "commands.py").write_text(FAKE_COMMANDS)
        return subprocess.run(
            [sys.executable, "-c", (ROLE / "files" / name).read_text()],
            input=stdin, capture_output=True, text=True, cwd=site,
        )


class ValidationTokenTests(unittest.TestCase):
    def test_helper_uses_fastdeploys_own_token_function(self):
        result = run_helper("mint_validation_token.py", json.dumps({"user": "admin", "ttl_seconds": 300}))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout.removeprefix("token:")),
            {"user": "admin", "type": "user", "ttl": 300.0},
        )

    def test_role_brings_no_jwt_library_and_no_secret(self):
        for path in ("files/mint_validation_token.py", "tasks/rollout.yml", "molecule/default/verify.yml"):
            with self.subTest(path=path):
                text = (ROLE / path).read_text()
                self.assertNotIn("jose", text)
                self.assertNotIn("import jwt", text)
        self.assertNotIn("secret_key", (ROLE / "tasks/rollout.yml").read_text())

    def test_mint_task_passes_only_the_script_and_reports_its_failure(self):
        rollout = tasks("tasks/rollout.yml")
        mint = rollout["rollout | Mint FastDeploy validation token"]
        command = mint["ansible.builtin.command"]
        self.assertEqual(command["argv"][0], "{{ fastdeploy_venv_bin }}/python")
        self.assertEqual(command["argv"][1], "-c")
        self.assertIn("mint_validation_token.py", command["argv"][2])
        self.assertEqual(len(command["argv"]), 3)
        self.assertIn("fastdeploy_rollout_validation_user", command["stdin"])
        self.assertEqual(command["chdir"], "{{ fastdeploy_site_path }}")
        self.assertNotIn("environment", mint)
        self.assertIs(mint["no_log"], True)
        # The no_log task must not hide its own failure.
        self.assertIs(mint["failed_when"], False)
        # In check mode the site may not exist; the command module fails on a
        # missing chdir instead of skipping.
        self.assertIn("not ansible_check_mode", mint["when"])
        names = list(rollout)
        report = rollout["rollout | Report a failed validation token mint"]
        self.assertEqual(names.index(report["name"]), names.index(mint["name"]) + 1)
        message = report["ansible.builtin.fail"]["msg"]
        self.assertIn("fastdeploy_rollout_validation_token.rc", message)
        self.assertNotIn("stdout", message)
        self.assertIn("not ansible_check_mode", report["when"])
        self.assertIs(rollout["rollout | Validate FastDeploy DB-backed auth after restart"]["no_log"], True)


class LegacyTokenUserTests(unittest.TestCase):
    def test_helper_runs_createuser_with_a_random_password_hash(self):
        result = run_helper("ensure_token_user.py", "credential-rotation\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "argv": ["commands.py", "createuser"],
                "user": "credential-rotation",
                "hash": "hash-of-64",
                "columns": "1000",
                "file": "commands.py",
            },
        )

    def test_helper_refuses_an_empty_name(self):
        result = run_helper("ensure_token_user.py", "\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_bridge_is_off_by_default(self):
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        self.assertEqual(defaults["fastdeploy_legacy_token_users"], [])

    def test_task_hides_output_and_reports_failures_without_it(self):
        initialize = tasks("tasks/initialize.yml")
        ensure = initialize["initialize | Ensure legacy service token users exist"]
        command = ensure["ansible.builtin.command"]
        self.assertEqual(len(command["argv"]), 3)
        self.assertIn("ensure_token_user.py", command["argv"][2])
        self.assertEqual(command["stdin"], "{{ item }}")
        self.assertEqual(ensure["loop"], "{{ fastdeploy_legacy_token_users }}")
        self.assertNotIn("environment", ensure)
        self.assertIs(ensure["no_log"], True)
        self.assertIs(ensure["failed_when"], False)
        self.assertEqual(ensure["when"], "not ansible_check_mode")
        report = initialize["initialize | Report a failed legacy service token user"]
        self.assertIn("not ansible_check_mode", report["when"])
        message = report["ansible.builtin.fail"]["msg"]
        self.assertNotIn("stdout", message)
        self.assertNotIn("stderr", message)
        # A failed loop item is printed in full, so the loop must not be the
        # registered results (they hold the output).
        self.assertEqual(report["loop"], "{{ fastdeploy_legacy_token_users }}")


if __name__ == "__main__":
    unittest.main()
