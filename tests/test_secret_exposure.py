"""Reject exposed task credential transport regardless of no_log."""

import json
import subprocess
import unittest
from collections import Counter
from pathlib import Path

import yaml

from scripts import check_secret_no_log as check

ROOT = Path(__file__).resolve().parents[1]
AUDITED = {
    "archive_deploy",
    "nyxmon_deploy",
    "fastdeploy_deploy",
    "fastdeploy_self_deploy",
    "fastdeploy_restore",
    "minecraft_java_backup",
    "mastodon_backup",
    "mastodon_restore",
    "takahe_backup",
    "takahe_restore",
    "paperless_backup",
    "paperless_restore",
    "wagtail_backup",
    "wagtail_restore",
    "unifi_deploy",
    "unifi_remove",
    "redis_install",
    "mail_relay_deploy",
}


class ExposureTests(unittest.TestCase):
    def test_environment_and_argv_ignore_no_log(self):
        for task in [
            {"command": "true", "environment": {"PGPASSWORD": "{{ db_password }}"}},
            {"shell": "mongosh -p {{ db_password }}"},
            {"command": {"argv": ["tool", "{{ password_hash }}"]}},
            {
                "action": {
                    "module": "command",
                    "args": {"argv": ["tool", "{{ api_token }}"]},
                }
            },
            {"local_action": "shell echo {{ admin_password }}"},
            {"command": "tailscale up --authkey={{ tailscale_auth_key }}"},
            {"command": {"argv": ["tailscale", "up", "--auth-key={{ service_authkey }}"]}},
            {
                "command": "true",
                "environment": "{{ {'PAPERLESS_PASSPHRASE': passphrase} }}",
            },
        ]:
            for no_log in (True, "{{ hidden }}", False):
                with self.subTest(task=task, no_log=no_log):
                    self.assertEqual(
                        len(
                            list(
                                check.iter_exposure_findings(dict(task, no_log=no_log))
                            )
                        ),
                        1,
                    )

    def test_inherited_environment_survives_unrelated_task_environment(self):
        data = yaml.safe_load(
            """
- environment:
    SECRET_KEY: "{{ service_secret }}"
  no_log: true
  block:
    - name: nested
      command: true
      environment:
        PATH: /usr/bin
  rescue:
    - name: recover
      command: true
  always:
    - name: cleanup
      command: true
"""
        )
        self.assertEqual(
            [n for n, _ in check.iter_exposure_findings(data)],
            ["nested", "recover", "cleanup"],
        )

    def test_inherited_environment_survives_template_and_list_children(self):
        data = yaml.safe_load(
            """
- environment:
    PGPASSWORD: "{{ db_password }}"
  block:
    - name: template child
      command: true
      environment: "{{ extra_env }}"
    - name: list child
      command: true
      environment:
        - PATH: /usr/bin
    - name: overriding child
      command: true
      environment:
        PGPASSWORD: ""
"""
        )
        self.assertEqual(
            [n for n, _ in check.iter_exposure_findings(data)],
            ["template child", "list child"],
        )

    def test_stdin_and_file_paths_are_allowed(self):
        data = [
            {
                "command": {
                    "argv": ["tool", "{{ password_file }}", "{{ token_path }}"],
                    "stdin": "{{ admin_password }}",
                },
                "no_log": True,
                "environment": {"PGPASSFILE": "{{ private_dir }}/pgpass"},
            }
        ]
        self.assertEqual(list(check.iter_exposure_findings(data)), [])

    def test_repository_and_exact_baseline(self):
        findings = Counter(check.exposure_scan(check.default_paths()))
        entries = json.loads(
            (ROOT / "scripts/secret_exposure_allowlist.json").read_text()
        )
        allowed = Counter((e["file"], e["task"], e["reason"]) for e in entries)
        self.assertEqual(findings, allowed, "New exposure or stale allowlist entry")
        for entry in entries:
            self.assertNotIn(entry["file"].split("/")[1], AUDITED)
            self.assertTrue(entry["disposition"])
        result = subprocess.run(
            [
                __import__("sys").executable,
                str(ROOT / "scripts/check_secret_no_log.py"),
                "--exposure",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_environment_path_keys_are_allowed(self):
        task = {
            "command": "true",
            "environment": {
                "RESTIC_PASSWORD_FILE": "/private/password",
                "VAULT_TOKEN_PATH": "{{ token_path }}",
                "PRIVATE_KEY_DIR": "/private/keys",
            },
        }
        self.assertIsNone(check.exposure_reason(task))
        task["environment"]["RESTIC_PASSWORD_FILE"] = "{{ admin_password }}"
        self.assertIsNotNone(check.exposure_reason(task))

    def test_duplicate_and_stale_allowlist_identities_fail_cli(self):
        import tempfile
        from unittest.mock import patch

        identity = (
            "roles/fixture/tasks/main.yml",
            "duplicate",
            "puts a credential in task environment",
        )
        baseline = [{"file": identity[0], "task": identity[1], "reason": identity[2]}]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "scripts/secret_exposure_allowlist.json").write_text(
                json.dumps(baseline)
            )
            with (
                patch.object(check, "ROOT", root),
                patch.object(check, "default_paths", return_value=[]),
            ):
                for findings, expected in [
                    ([identity], 0),
                    ([identity, identity], 1),
                    ([], 1),
                ]:
                    with patch.object(check, "exposure_scan", return_value=findings):
                        self.assertEqual(check.main(["--exposure"]), expected)

    def test_documented_indirect_debt_is_current_and_does_not_suppress_checks(self):
        from tests.credential_helpers import tasks

        entries = json.loads(
            (ROOT / "scripts/secret_exposure_indirect_debt.json").read_text()
        )
        identities = [(e["file"], e["task"]) for e in entries]
        self.assertEqual(len(identities), len(set(identities)))
        for entry in entries:
            _, role, _, file = entry["file"].split("/")
            task = next(t for t in tasks(role, file) if t.get("name") == entry["task"])
            self.assertTrue(entry["reason"])
            self.assertNotIn(role, AUDITED)
            self.assertIsNone(check.exposure_reason(task))
            if entry["kind"] == "indirect":
                transport = str(task.get("environment", "")) + str(
                    task.get("ansible.builtin.command", "")
                )
                self.assertIn(entry["aggregate"], transport)
                if role in {"unifi_restore", "minio_restore"}:
                    self.assertIn(
                        "ops-secrets-in-task-environment:",
                        (ROOT / entry["file"]).read_text(),
                    )
            else:
                self.assertIn(
                    "passphrase",
                    str(task.get("args", task.get("ansible.builtin.command", {}))),
                )

    def test_deferred_unifi_verification_results_are_protected(self):
        from tests.credential_helpers import tasks

        task = next(
            t
            for t in tasks("unifi_restore", "verify.yml")
            if t.get("name") == "verify | Verify MongoDB is accessible"
        )
        self.assertEqual(
            task["no_log"],
            "{{ unifi_restore_mongodb_password | default('', true) | length > 0 }}",
        )
