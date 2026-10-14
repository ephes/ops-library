import unittest

from tests.credential_helpers import assert_mongo_files


class CredentialTests(unittest.TestCase):
    def test_private_mongo_scripts(self):
        assert_mongo_files(self, "unifi_deploy", 5)

    def test_hash_inputs_are_stdin_and_existing_salt_is_reused(self):
        import json
        import os
        import subprocess
        import sys
        import tempfile
        from pathlib import Path

        from tests.credential_helpers import ROOT, tasks

        task = next(
            t
            for t in tasks("unifi_deploy", "homeassistant.yml")
            if t.get("name") == "homeassistant | Hash password for MongoDB"
        )
        self.assertNotIn("environment", task)
        self.assertIn("stdin", task["ansible.builtin.command"])
        script = ROOT / "roles/unifi_deploy/files/hash_ha_password.py"
        password = "' $() ; \\\\"
        with tempfile.TemporaryDirectory() as tmp:
            client = Path(tmp) / "mkpasswd"
            client.write_text('#!/bin/sh\nprintf "%s|" "$*"\ncat\n')
            client.chmod(0o700)
            for existing, flags in [
                ("", "-m sha-512 --stdin"),
                ("$6$salt$hash", "-m sha-512 -S salt --stdin"),
                (
                    "noise\n$6$rounds=5000$salt$hash",
                    "-m sha-512 -R 5000 -S salt --stdin",
                ),
            ]:
                result = subprocess.run(
                    [sys.executable, str(script)],
                    check=False,
                    input=json.dumps({"existing_hash": existing, "password": password}),
                    capture_output=True,
                    text=True,
                    env={**os.environ, "PATH": tmp + ":/usr/bin:/bin"},
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, flags + "|" + password)

    def test_init_and_auth_scripts_use_the_same_literal_password(self):
        import json

        from tests.credential_helpers import ENV, ROOT, tasks

        password = "' \" \\ $() ;\nsecret"
        rendered = ENV.from_string(
            (ROOT / "roles/unifi_deploy/templates/mongo-init.js.j2").read_text()
        ).render(
            unifi_mongodb_user="fixture",
            unifi_mongodb_password=password,
            unifi_mongodb_database="fixture",
        )
        self.assertIn("pwd: " + json.dumps(password), rendered)
        self.assertNotIn("use admin;", rendered)
        task = next(
            t
            for t in tasks("unifi_deploy", "mongodb.yml")
            if t.get("name") == "mongodb | Create user"
        )
        self.assertIn("--file ", task["ansible.builtin.shell"])
