"""mail_relay_client must not configure Postfix with an unqualified origin.

Postfix appends ``myorigin`` to unqualified senders and recipients, so
``root`` becomes ``root@<myorigin>``. The role defaulted ``myorigin`` to
``ansible_fqdn``, which is a bare host name on hosts without a DNS domain:
fractal sent as ``root@fractal`` and the smarthost answered
``450 4.1.8 Domain not found`` for every message. The role now refuses such a
value before touching Postfix.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "mail_relay_client"


def _run_validate(**role_vars: object) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as scratch:
        playbook = Path(scratch) / "validate.yml"
        playbook.write_text(
            yaml.safe_dump(
                [
                    {
                        "hosts": "localhost",
                        "gather_facts": False,
                        "tasks": [
                            {
                                "ansible.builtin.include_role": {
                                    "name": "mail_relay_client",
                                    "tasks_from": "validate",
                                },
                                "vars": role_vars,
                            }
                        ],
                    }
                ]
            ),
            encoding="utf-8",
        )
        env = {
            **os.environ,
            "ANSIBLE_ROLES_PATH": str(ROOT / "roles"),
            "ANSIBLE_NOCOLOR": "1",
            "ANSIBLE_LOCALHOST_WARNING": "0",
            "ANSIBLE_INVENTORY_UNPARSED_WARNING": "0",
            "ANSIBLE_RETRY_FILES_ENABLED": "0",
        }
        return subprocess.run(
            ["ansible-playbook", "-i", "localhost,", "-c", "local", str(playbook)],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
            check=False,
        )


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not on PATH")
class MailRelayClientValidateTests(unittest.TestCase):
    def test_qualified_origin_passes(self) -> None:
        for origin in ("example.com", "mail.example.org", "xn--wersdrfer-47a.de"):
            with self.subTest(origin=origin):
                result = _run_validate(
                    mail_relay_client_relayhost="relay.example.com",
                    mail_relay_client_myorigin=origin,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unqualified_origin_fails_before_postfix_is_touched(self) -> None:
        for origin in ("fractal", "localhost", "", ".example.com", "example.com.",
                       "-bad.example.com", "$mydomain", "example.123"):
            with self.subTest(origin=origin):
                result = _run_validate(
                    mail_relay_client_relayhost="relay.example.com",
                    mail_relay_client_myorigin=origin,
                )
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn(
                    "mail_relay_client_myorigin must be a fully qualified",
                    result.stdout,
                )

    def test_disabled_role_skips_origin_check(self) -> None:
        result = _run_validate(
            mail_relay_client_enabled=False,
            mail_relay_client_relayhost="",
            mail_relay_client_myorigin="fractal",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class MailRelayClientConfigTests(unittest.TestCase):
    def test_myorigin_is_applied_to_postfix(self) -> None:
        tasks = yaml.safe_load((ROLE / "tasks" / "config.yml").read_text())
        build = next(t for t in tasks if t["name"] == "config | Build desired postfix settings")
        expression = build["ansible.builtin.set_fact"][
            "_mail_relay_client_desired_postfix_settings"
        ]
        self.assertIn("'myorigin': mail_relay_client_myorigin", expression)

    def test_validation_runs_before_postfix_changes(self) -> None:
        main = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
        includes = [t["ansible.builtin.include_tasks"] for t in main]
        self.assertEqual(includes[0], "validate.yml")
        self.assertLess(includes.index("validate.yml"), includes.index("config.yml"))

    def test_readme_documents_qualified_origin(self) -> None:
        readme = (ROLE / "README.md").read_text()
        self.assertIn("fully qualified", readme)
        self.assertIn("450 4.1.8", readme)


if __name__ == "__main__":
    unittest.main()
