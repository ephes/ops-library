"""UniFi's logs stay private.

UniFi 9.5 writes its MongoDB connection URI, password included, to
``server.log`` on every start. Logback has no file-mode setting, so the unit
sets ``UMask=0027``, ``directories.yml`` locks the log directory to 0750 and
``logs.yml`` tightens entries that already exist. The playbook
``tests/test_unifi_log_permissions.yml`` runs those tasks on a temporary tree.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/unifi_deploy"


def tasks(name: str) -> list[dict]:
    return yaml.safe_load((ROLE / "tasks" / name).read_text())


class UnifiLogPermissionsTest(unittest.TestCase):
    def test_unit_sets_a_private_umask(self) -> None:
        unit = (ROLE / "templates/unifi.service.j2").read_text()
        service = unit.split("[Service]\n", 1)[1].split("\n[", 1)[0]
        self.assertIn("UMask=0027", service.splitlines())

    def test_log_directory_is_0750_and_no_other_directory_task_widens_it(self) -> None:
        log_tasks = [
            task
            for task in tasks("directories.yml")
            if "{{ unifi_logs_dir }}"
            in str(task["ansible.builtin.file"].get("path", ""))
            or "{{ unifi_logs_dir }}" in task.get("loop", [])
        ]
        self.assertEqual(len(log_tasks), 1)
        self.assertNotIn("loop", log_tasks[0])
        self.assertEqual(log_tasks[0]["ansible.builtin.file"]["mode"], "0750")
        self.assertEqual(log_tasks[0]["ansible.builtin.file"]["state"], "directory")

    def test_existing_entries_are_tightened_as_their_owner_not_root(self) -> None:
        find, select, dirs, files = tasks("logs.yml")
        self.assertIs(find["ansible.builtin.find"]["follow"], False)
        self.assertIs(find["ansible.builtin.find"]["recurse"], True)
        self.assertIn(
            "rejectattr('islnk')",
            select["ansible.builtin.set_fact"]["unifi_loose_log_dirs"],
        )
        self.assertIn(
            "rejectattr('islnk')",
            select["ansible.builtin.set_fact"]["unifi_loose_log_files"],
        )
        # Only removes bits: directories at most 0750, files at most 0640.
        self.assertEqual(
            dirs["ansible.builtin.command"]["argv"],
            "{{ unifi_logs_runas + ['chmod', 'g-w,o-rwx'] + unifi_loose_log_dirs }}",
        )
        self.assertEqual(
            files["ansible.builtin.command"]["argv"],
            "{{ unifi_logs_runas + ['chmod', 'u-x,g-wx,o-rwx'] + unifi_loose_log_files }}",
        )
        for task in (dirs, files):
            self.assertNotIn("become", task)
            self.assertNotIn("become_user", task)
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        self.assertEqual(
            defaults["unifi_logs_runas"], ["runuser", "-u", "{{ unifi_user }}", "--"]
        )

    def test_logs_are_tightened_after_the_unit_is_written(self) -> None:
        imports = [
            task.get("ansible.builtin.import_tasks") for task in tasks("main.yml")
        ]
        self.assertLess(imports.index("directories.yml"), imports.index("logs.yml"))
        self.assertLess(imports.index("systemd.yml"), imports.index("logs.yml"))


if __name__ == "__main__":
    unittest.main()
