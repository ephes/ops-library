import unittest

from tests.credential_helpers import assert_env_source


class CredentialTests(unittest.TestCase):
    def test_source_env_file(self):
        assert_env_source(
            self,
            "nyxmon_deploy",
            "django.yml",
            "nyxmon.env.j2",
            "nyxmon_django_secret_key",
            "DJANGO_SECRET_KEY",
            2,
        )

    def test_django_manage_change_detection_is_preserved(self):
        from ansible.plugins.test.core import TestModule

        from tests.credential_helpers import ENV, tasks

        ENV.tests.update(TestModule().tests())
        for command, outputs in [
            (
                "migrate",
                [
                    ("No migrations to apply.\n", False),
                    ("  Applying app.0001... OK\n", True),
                    ("Installed 0 object(s)\n", False),
                    ("Installed 2 objects\n", True),
                ],
            ),
            (
                "collectstatic",
                [
                    ("", False),
                    ("0 static files copied.\n", False),
                    ("2 static files copied.\n", True),
                ],
            ),
        ]:
            task = next(
                t
                for t in tasks("nyxmon_deploy", "django.yml")
                if t.get("register") == "nyxmon_" + command + "_result"
            )
            for output, changed in outputs:
                result = {"stdout": output, "stdout_lines": output.splitlines()}
                actual = ENV.from_string(
                    "{% if " + task["changed_when"] + " %}yes{% endif %}"
                ).render(**{"nyxmon_" + command + "_result": result})
                self.assertEqual(bool(actual), changed, output)

    def test_opsgate_runtime_assertions_keep_application_format(self):
        from tests.test_nyxmon_deploy import render

        text = render(
            "nyxmon.env.j2",
            nyxmon_opsgate_submit_base_url="https://submit.example",
            nyxmon_opsgate_submit_token="fixture",
            nyxmon_opsgate_approval_base_url="https://approve.example",
            nyxmon_opsgate_ticket_expires_seconds=300,
            nyxmon_opsgate_submit_timeout_seconds=5,
            nyxmon_opsgate_submit_include_warnings=False,
        )
        self.assertIn("\nOPSGATE_SUBMIT_BASE_URL=https://submit.example\n", text)
        self.assertIn("\nOPSGATE_APPROVAL_BASE_URL=https://approve.example\n", text)
