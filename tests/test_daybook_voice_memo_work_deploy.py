"""Rendered contract tests for the separate Voice Memo work scheduler."""
import plistlib
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/daybook_voice_memo_work_deploy"


class VoiceMemoWorkRoleTests(unittest.TestCase):
    def variables(self):
        values = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        values.update(daybook_voice_memo_work_service_user="example",
                      daybook_voice_memo_work_imported_since="2026-09-08T19:58:34+02:00",
                      daybook_voice_memo_work_codex_socket="/Users/example/runtime/codex.sock",
                      daybook_voice_memo_work_aws_access_key_id="key",
                      daybook_voice_memo_work_aws_secret_access_key="secret",
                      daybook_voice_memo_work_s3_endpoint_url="https://objects.example.test",
                      daybook_voice_memo_work_effective_cutoff="2026-09-08T19:58:34+02:00")
        env = Environment()
        for _ in range(8):
            for name, value in values.items():
                if isinstance(value, str):
                    values[name] = env.from_string(value).render(**values)
        return values

    def test_plist_runs_only_new_import_bridge_every_five_minutes(self):
        values = self.variables()
        rendered = Environment().from_string((ROLE / "templates/voice-memo-work.launchd.plist.j2").read_text()).render(**values)
        plist = plistlib.loads(rendered.encode())
        argv = plist["ProgramArguments"]
        self.assertEqual(plist["StartInterval"], 300)
        self.assertEqual(argv[:5], [values["daybook_voice_memo_work_cli"], "work", "--state", values["daybook_voice_memo_work_state_path"], "memos"])
        self.assertEqual(argv[argv.index("--imported-since") + 1], values["daybook_voice_memo_work_effective_cutoff"])
        self.assertIn("--socket", argv)
        self.assertNotIn("serve", argv)
        environment = plist["EnvironmentVariables"]
        self.assertEqual(environment["AWS_PROFILE"], "daybook-work")
        self.assertEqual(environment["AWS_DEFAULT_PROFILE"], "daybook-work")
        self.assertEqual(environment["AWS_CONFIG_FILE"], "/dev/null")
        for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                     "AWS_SECURITY_TOKEN", "AWS_WEB_IDENTITY_TOKEN_FILE", "AWS_ROLE_ARN",
                     "AWS_ROLE_SESSION_NAME"):
            self.assertEqual(environment[name], "")
        self.assertTrue(argv[argv.index("--state") + 1].endswith("/memos/work.sqlite3"))

    def test_role_preserves_cutoff_and_changes_only_own_label(self):
        text = (ROLE / "tasks/main.yml").read_text()
        self.assertIn("force: false", text)
        self.assertNotIn("de.wersdoerfer.daybook.voice-memo-inbox", text)
        self.assertNotIn("acceptance/work.sqlite3", text)
        self.assertIn("--imported-since", text)
        self.assertIn("disabled_domain.rc not in [0, 112]", text)
        self.assertIn("disabled_loaded.rc not in [0, 113]", text)
        self.assertIn("disabled_verified.rc != 113", text)
        self.assertGreaterEqual(text.count("Could not find service"), 2)
        disable = next(task for task in yaml.safe_load(text)
                       if task["name"] == "Disable Voice Memo work LaunchAgent")
        self.assertEqual(disable["when"], "not daybook_voice_memo_work_enabled | bool")

    def test_credentials_are_separate_and_private(self):
        tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
        install = next(task for task in tasks if task["name"] == "Install owner-private Voice Memo source credentials")
        self.assertTrue(install["no_log"])
        self.assertEqual(install["ansible.builtin.template"]["mode"], "0600")

    def test_cli_capability_check_starts_from_accessible_owner_home(self):
        tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
        check = next(task for task in tasks
                     if task["name"] == "Verify installed Daybook supports recurring import cutoff")
        self.assertEqual(check["become_user"], "root")
        command = check["ansible.builtin.command"]
        self.assertEqual(command["chdir"], "{{ daybook_voice_memo_work_service_home }}")
        self.assertEqual(command["argv"][:6], ["/usr/bin/sudo", "-n", "-H", "-u",
                                                "{{ daybook_voice_memo_work_service_user }}", "--"])


if __name__ == "__main__":
    unittest.main()
