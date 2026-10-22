"""Run ssh_authorized_keys_manage against a temporary home with real Ansible.

The non-exclusive mode must add or update only the declared keys and leave
every other line of authorized_keys alone (another role's forced-command key
on the same account must survive). The default mode still renders the whole
file.
"""

from __future__ import annotations

import grp
import os
import pwd
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

KEY_A = "ssh-ed25519 " + "A" * 68
KEY_B = "ssh-ed25519 " + "B" * 68
KEY_FOREIGN = "ssh-ed25519 " + "F" * 68
FOREIGN_OPTIONS = 'restrict,command="/usr/local/libexec/notify.py --config /etc/notify.json"'
FOREIGN_LINE = f"{FOREIGN_OPTIONS} {KEY_FOREIGN} other-role-notifier\n"


class SshAuthorizedKeysManageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        (self.home / ".ssh").mkdir(parents=True)
        self.keys = self.home / ".ssh" / "authorized_keys"
        self.user = pwd.getpwuid(os.getuid()).pw_name
        self.group = grp.getgrgid(os.getgid()).gr_name

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_role(self, entries: list[dict], exclusive: bool | None = None) -> tuple[int, int, str]:
        role_vars = {
            "ssh_authorized_keys_manage_user": self.user,
            "ssh_authorized_keys_manage_group": self.group,
            "ssh_authorized_keys_manage_home": str(self.home),
            "ssh_authorized_keys_manage_entries": entries,
        }
        if exclusive is not None:
            role_vars["ssh_authorized_keys_manage_exclusive"] = exclusive
        play = [{
            "hosts": "localhost",
            "gather_facts": False,
            "roles": [{"role": "ssh_authorized_keys_manage", "vars": role_vars}],
        }]
        playbook = Path(self.tmp.name) / "play.yml"
        playbook.write_text(yaml.safe_dump(play))
        result = subprocess.run(
            ["ansible-playbook", "-i", "localhost,", "-c", "local", str(playbook)],
            cwd=ROOT,
            env=os.environ | {"ANSIBLE_NOCOLOR": "1", "ANSIBLE_ROLES_PATH": str(ROOT / "roles")},
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout + result.stderr
        match = re.search(r"localhost\s*:\s*ok=\d+\s+changed=(\d+)", output)
        changed = int(match.group(1)) if match else -1
        return result.returncode, changed, output

    def test_non_exclusive_keeps_foreign_lines_and_is_idempotent(self) -> None:
        original = (
            "# notes kept by hand\n"
            + FOREIGN_LINE
            + f"{KEY_A} old-comment\n"
        )
        self.keys.write_text(original)
        entries = [
            {"key": KEY_A, "comment": "opsgate-ops"},
            {"key": KEY_B, "comment": "operator", "key_options": 'from="100.64.0.0/10"'},
        ]
        rc, changed, output = self.run_role(entries, exclusive=False)
        self.assertEqual(rc, 0, output)
        self.assertGreater(changed, 0, output)
        self.assertEqual(
            self.keys.read_text(),
            "# notes kept by hand\n"
            + FOREIGN_LINE
            + f"{KEY_A} opsgate-ops\n"
            + f'from="100.64.0.0/10" {KEY_B} operator\n',
        )
        self.assertEqual(self.keys.stat().st_mode & 0o777, 0o600)

        rc, changed, output = self.run_role(entries, exclusive=False)
        self.assertEqual(rc, 0, output)
        self.assertEqual(changed, 0, output)

    def test_non_exclusive_is_a_no_op_on_a_file_the_default_mode_rendered(self) -> None:
        entries = [
            {"key": KEY_A + " opsgate@runner", "comment": "opsgate-ops"},
            {"key": KEY_B, "key_options": 'command="/usr/local/sbin/allow.sh",no-pty', "comment": "replication"},
        ]
        rc, _, output = self.run_role(entries)
        self.assertEqual(rc, 0, output)
        with self.keys.open("a") as handle:
            handle.write(FOREIGN_LINE)
        rendered = self.keys.read_bytes()

        rc, changed, output = self.run_role(entries, exclusive=False)
        self.assertEqual(rc, 0, output)
        self.assertEqual(changed, 0, output)
        self.assertEqual(self.keys.read_bytes(), rendered)

    def test_default_mode_still_renders_the_whole_file(self) -> None:
        self.keys.write_text(FOREIGN_LINE)
        rc, _, output = self.run_role([{"key": KEY_A, "comment": "opsgate-ops"}])
        self.assertEqual(rc, 0, output)
        self.assertEqual(
            self.keys.read_text(),
            "# Managed by Ansible - local.ops_library.ssh_authorized_keys_manage\n"
            f"{KEY_A} opsgate-ops\n",
        )

    def test_rejects_line_breaks_and_non_boolean_mode(self) -> None:
        self.keys.write_text(FOREIGN_LINE)
        rc, _, output = self.run_role([{"key": KEY_A + "\n" + KEY_B}], exclusive=False)
        self.assertNotEqual(rc, 0, output)
        self.assertIn("line break", output)

        rc, _, output = self.run_role([{"key": KEY_A}], exclusive="false")  # type: ignore[arg-type]
        self.assertNotEqual(rc, 0, output)
        self.assertEqual(self.keys.read_text(), FOREIGN_LINE)

    def test_non_exclusive_refuses_repeated_keys(self) -> None:
        original = (
            f'from="10.0.0.1" {KEY_FOREIGN} first\n'
            f'from="10.0.0.2" {KEY_FOREIGN} second\n'
        )
        self.keys.write_text(original)
        rc, _, output = self.run_role([{"key": KEY_A, "comment": "operator"}], exclusive=False)
        self.assertNotEqual(rc, 0, output)
        self.assertIn("would rewrite lines", output)
        self.assertEqual(self.keys.read_text(), original)

        self.keys.write_text(FOREIGN_LINE)
        rc, _, output = self.run_role(
            [{"key": KEY_A, "comment": "one"}, {"key": KEY_A, "key_options": "no-pty", "comment": "two"}],
            exclusive=False,
        )
        self.assertNotEqual(rc, 0, output)
        self.assertEqual(self.keys.read_text(), FOREIGN_LINE)

    def test_identity_follows_the_module_parser(self) -> None:
        # Forced commands mentioning other words must not hide a shared key.
        original = (
            f'command="exec ssh-agent bash -c true" {KEY_FOREIGN} first\n'
            f'command="exec ssh-agent sh -c true" {KEY_FOREIGN} second\n'
        )
        self.keys.write_text(original)
        rc, _, output = self.run_role([{"key": KEY_A}], exclusive=False)
        self.assertNotEqual(rc, 0, output)
        self.assertEqual(self.keys.read_text(), original)

        # Whatever the module would collapse or rewrite is refused unchanged.
        for original in (
            f'command="echo\u00a0ssh-rsa\u00a0first" {KEY_FOREIGN} a\n'
            f'command="echo\u00a0ssh-rsa\u00a0second" {KEY_FOREIGN} b\n',
            "# note\r\n# note\n" + FOREIGN_LINE,
            "\\# note\n# note\n" + FOREIGN_LINE,
            FOREIGN_LINE + "\n\n",
            f"{KEY_FOREIGN}\n",
        ):
            with self.subTest(original=original):
                self.keys.write_bytes(original.encode())
                rc, _, output = self.run_role([{"key": KEY_A}], exclusive=False)
                self.assertNotEqual(rc, 0, output)
                self.assertEqual(self.keys.read_bytes(), original.encode())

        # Options embedded in one entry's key and the bare key in another.
        self.keys.write_text(FOREIGN_LINE)
        rc, _, output = self.run_role(
            [{"key": f'from="10.0.0.1" {KEY_A}'}, {"key": KEY_A, "comment": "bare"}],
            exclusive=False,
        )
        self.assertNotEqual(rc, 0, output)
        self.assertEqual(self.keys.read_text(), FOREIGN_LINE)

        # Blobs that differ only in letter case are different keys.
        lower = "ssh-ed25519 " + "f" * 68
        original = FOREIGN_LINE + f"{lower} lower\n"
        self.keys.write_text(original)
        rc, _, output = self.run_role([{"key": KEY_A, "comment": "operator"}], exclusive=False)
        self.assertEqual(rc, 0, output)
        self.assertEqual(self.keys.read_text(), original + f"{KEY_A} operator\n")

    def test_non_exclusive_accepts_entries_without_comment(self) -> None:
        rc, changed, output = self.run_role([{"key": KEY_A}], exclusive=False)
        self.assertEqual(rc, 0, output)
        self.assertEqual(self.keys.read_text(), f"{KEY_A} \n")
        rc, changed, output = self.run_role([{"key": KEY_A}], exclusive=False)
        self.assertEqual(rc, 0, output)
        self.assertEqual(changed, 0, output)

        self.keys.write_text(FOREIGN_LINE)
        rc, _, output = self.run_role([{"key": KEY_B}], exclusive=False)
        self.assertEqual(rc, 0, output)
        self.assertEqual(self.keys.read_text(), FOREIGN_LINE + f"{KEY_B} \n")

    def test_loop_never_uses_exclusive(self) -> None:
        tasks = yaml.safe_load((ROOT / "roles/ssh_authorized_keys_manage/tasks/main.yml").read_text())
        modules = [task["ansible.posix.authorized_key"] for task in tasks if "ansible.posix.authorized_key" in task]
        self.assertEqual(len(modules), 1)
        self.assertIs(modules[0]["exclusive"], False)
        self.assertEqual(modules[0]["state"], "present")


if __name__ == "__main__":
    unittest.main()
