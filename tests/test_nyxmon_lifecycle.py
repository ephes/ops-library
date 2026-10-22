"""Contracts for the Nyxmon roles' account, removal and restore lifecycle.

The deploy role's account creation and repeat runs are exercised for real by
the nyxmon_deploy Molecule scenario; these tests pin the task structure that
makes them work, plus the removal and restore behaviour that has no Molecule
scenario.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def tasks(role: str, name: str = "main.yml") -> list[dict]:
    return yaml.safe_load((ROOT / "roles" / role / "tasks" / name).read_text())


def flatten(items: list[dict]) -> list[dict]:
    out: list[dict] = []
    for item in items:
        out.append(item)
        for key in ("block", "rescue", "always"):
            out.extend(flatten(item.get(key, [])))
    return out


def by_name(items: list[dict], name: str) -> dict:
    [task] = [t for t in flatten(items) if t.get("name") == name]
    return task


def conditions(task: dict) -> list[str]:
    when = task.get("when", [])
    return [when] if isinstance(when, str) else list(when)


class DeployAccountTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = tasks("nyxmon_deploy", "user.yml")

    def test_existence_comes_from_the_getent_fact_not_failed(self) -> None:
        # failed_when: false means `.failed` is never true, so testing it
        # skipped account creation on a fresh host.
        check = by_name(self.user, "user | Check if nyxmon user exists")
        self.assertIs(check["failed_when"], False)
        record = by_name(self.user, "user | Record whether the nyxmon user exists")
        expr = record["ansible.builtin.set_fact"]["nyxmon_user_exists"]
        self.assertIn("getent_passwd", expr)
        for task in flatten(self.user):
            for condition in conditions(task):
                self.assertNotIn("nyxmon_user_check.failed", condition)

    def test_create_sets_group_and_shell_only_for_a_missing_account(self) -> None:
        create = by_name(self.user, "user | Ensure nyxmon user exists")
        self.assertEqual(create["user"]["group"], "{{ nyxmon_group }}")
        self.assertEqual(create["user"]["shell"], "/bin/bash")
        self.assertEqual(conditions(create), ["not (nyxmon_user_exists | bool)"])

    def test_supplementary_group_only_when_primary_group_differs(self) -> None:
        append = by_name(self.user, "user | Ensure nyxmon user is in correct group")
        when = conditions(append)
        self.assertIn("nyxmon_user_exists | bool", when)
        self.assertTrue(any("getent_group" in c and "!=" in c for c in when))


class RemoveDropInTests(unittest.TestCase):
    def setUp(self) -> None:
        self.main = tasks("nyxmon_remove")

    def test_sqlite_privacy_drop_ins_are_removed_for_both_units(self) -> None:
        deploy = tasks("nyxmon_deploy", "sqlite_privacy.yml")
        installed = by_name(deploy, "sqlite_privacy | Install writer umask drop-ins")
        self.assertTrue(installed["ansible.builtin.copy"]["dest"].endswith(".service.d/sqlite-privacy.conf"))

        remove = by_name(self.main, "Remove SQLite privacy drop-ins")
        self.assertEqual(remove["file"]["state"], "absent")
        self.assertEqual(
            remove["file"]["path"],
            "/etc/systemd/system/{{ item }}.service.d/sqlite-privacy.conf",
        )
        self.assertEqual(
            remove["loop"],
            ["{{ nyxmon_service_name }}", "{{ nyxmon_monitor_service_name }}"],
        )
        self.assertEqual(remove["notify"], "reload systemd")

    def test_drop_in_directories_are_removed_only_when_empty(self) -> None:
        listing = by_name(self.main, "Find what is left in the service drop-in directories")
        self.assertIs(listing["find"]["hidden"], True)
        self.assertEqual(listing["find"]["file_type"], "any")
        rmdir = by_name(self.main, "Remove empty service drop-in directories")
        self.assertEqual(conditions(rmdir), ["item.matched | default(0) == 0"])

    def test_drop_ins_go_before_the_final_daemon_reload(self) -> None:
        names = [t.get("name") for t in self.main]
        self.assertLess(
            names.index("Remove empty service drop-in directories"),
            names.index("Reload systemd daemon"),
        )


class RestoreModeTests(unittest.TestCase):
    def test_directory_modes_are_set_after_the_rsync(self) -> None:
        # rsync -a src/ dest/ copies the archive directory's 0700 onto dest;
        # the mode task must run afterwards to keep nyxmon_deploy's 0755.
        restore = flatten(tasks("nyxmon_restore", "restore.yml"))
        names = [t.get("name") for t in restore]
        create = names.index("Ensure destination directories exist")
        rsync = names.index("Restore Nyxmon directories")
        mode = names.index("Reset destination directory modes after the rsync")
        # Created before the rsync (rsync cannot create missing parents) and
        # reset afterwards.
        self.assertLess(create, rsync)
        self.assertLess(rsync, mode)
        for index in (create, mode):
            task = restore[index]["ansible.builtin.file"]
            self.assertEqual(task["mode"], "0755")
            self.assertEqual(task["state"], "directory")
            self.assertEqual(task["path"], "{{ item.dest }}")


if __name__ == "__main__":
    unittest.main()
