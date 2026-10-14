import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.credential_helpers import ENV, tasks


class CredentialTests(unittest.TestCase):
    def test_redis_install(self):
        task = next(
            t
            for t in tasks("redis_install", "service.yml")
            if t["name"] == "Check if Redis accepts configured password"
        )
        self.assertNotIn(
            "redis_install_password", str(task["ansible.builtin.command"]["argv"])
        )
        self.assertIn("REDISCLI_AUTH", str(task["ansible.builtin.command"]["argv"]))
        self.assertTrue(task["no_log"])
        self.assertEqual(
            task["ansible.builtin.command"]["stdin"], "{{ redis_install_password }}"
        )
        self.assertFalse(task["changed_when"])
        self.assertFalse(task["failed_when"])

        self.assertNotIn("environment", task)
        command = task["ansible.builtin.command"]
        argv = [
            ENV.from_string(v).render(redis_install_port=6379) for v in command["argv"]
        ]
        self.assertNotIn("--askpass", str(argv))
        self.assertNotIn(" -a ", str(argv))
        password = "space ' \" $() \\\\"
        with tempfile.TemporaryDirectory() as tmp:
            client = Path(tmp) / "redis-cli"
            client.write_text('#!/bin/sh\nprintf "%s|%s" "$REDISCLI_AUTH" "$*"\n')
            client.chmod(0o700)
            result = subprocess.run(
                argv,
                check=False,
                input=password + "\n",
                text=True,
                capture_output=True,
                env={"PATH": tmp + ":/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, password + "|-p 6379 PING")
