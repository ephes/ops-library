"""Safety contracts for the legacy Vaultwarden restore role.

Echoport is the preferred Vaultwarden restore path. The legacy role still runs
via `just restore vaultwarden`, so it must not be able to overwrite the vault
without a safety copy, copy over a live database, replay a stale WAL, or report
a partial restore as success.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "vaultwarden_restore"


def load_tasks() -> list[dict]:
    return yaml.safe_load((ROLE / "tasks" / "main.yml").read_text(encoding="utf-8"))


def flatten(tasks: list[dict], section_filter: tuple[str, ...] = ("block", "rescue", "always")) -> list[dict]:
    flat: list[dict] = []
    for task in tasks:
        nested = False
        for section in ("block", "rescue", "always"):
            if section in task:
                nested = True
                if section in section_filter:
                    flat.extend(flatten(task[section], section_filter))
        if not nested:
            flat.append(task)
    return flat


def find_block(tasks: list[dict], name: str) -> dict:
    for task in tasks:
        if task.get("name") == name:
            return task
        for section in ("block", "rescue", "always"):
            if section in task:
                try:
                    return find_block(task[section], name)
                except KeyError:
                    pass
    raise KeyError(name)


def index_of(tasks: list[dict], name: str) -> int:
    for index, task in enumerate(tasks):
        if task.get("name") == name:
            return index
    raise AssertionError(f"task {name!r} not found")


class VaultwardenRestoreSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tasks = load_tasks()
        # Main path only: the order a successful run takes.
        cls.main_path = flatten(cls.tasks, ("block",))

    def test_integrity_check_precedes_stop(self) -> None:
        check = index_of(self.main_path, "Check staged database integrity before stopping anything")
        stop = index_of(self.main_path, "Stop Vaultwarden before restore")
        self.assertLess(check, stop)
        task = self.main_path[check]
        self.assertIn("PRAGMA integrity_check;", task["ansible.builtin.command"]["argv"])
        self.assertIn("!= 'ok'", task["failed_when"])

    def test_stop_fails_closed(self) -> None:
        for name in ("Stop Vaultwarden before restore", "Confirm Vaultwarden is stopped"):
            task = self.main_path[index_of(self.main_path, name)]
            self.assertNotEqual(task.get("failed_when"), False, name)
            self.assertNotIn("ignore_errors", task, name)
        confirm = self.main_path[index_of(self.main_path, "Confirm Vaultwarden is stopped")]
        self.assertIn("not in ['inactive', 'failed']", confirm["failed_when"])

    def test_safety_copy_is_taken_after_stop_and_before_any_overwrite(self) -> None:
        stop = index_of(self.main_path, "Confirm Vaultwarden is stopped")
        safety = index_of(self.main_path, "Take safety copy of live Vaultwarden data and config")
        sidecars = index_of(self.main_path, "Remove stale SQLite sidecar files before the database copy")
        db_copy = index_of(self.main_path, "Restore SQLite database")
        self.assertLess(stop, safety)
        self.assertLess(safety, sidecars)
        self.assertLess(sidecars, db_copy)
        script = self.main_path[safety]["ansible.builtin.shell"]["cmd"]
        self.assertIn("set -euo pipefail", script)
        self.assertIn('cp -a "$DATA_DIR/." "$safety/data/"', script)
        for name in ("config", "override", "traefik"):
            self.assertIn(name, script)

    def test_every_overwrite_task_comes_after_the_safety_copy(self) -> None:
        safety = index_of(self.main_path, "Take safety copy of live Vaultwarden data and config")
        for name in (
            "Restore SQLite database",
            "Restore attachments directory",
            "Restore sends directory",
            "Restore RSA key files",
            "Restore Vaultwarden config file",
            "Restore systemd override when present",
            "Restore Traefik configuration when present",
        ):
            self.assertGreater(index_of(self.main_path, name), safety, name)

    def test_symlinked_live_paths_are_refused_before_stop(self) -> None:
        check = index_of(self.main_path, "Check live data paths for symlinks")
        refuse = index_of(self.main_path, "Refuse to restore through symlinked data paths")
        stop = index_of(self.main_path, "Stop Vaultwarden before restore")
        self.assertLess(check, refuse)
        self.assertLess(refuse, stop)
        task = self.main_path[check]
        self.assertFalse(task["ansible.builtin.stat"]["follow"])
        for name in ("attachments", "sends", "db.sqlite3", "rsa_key.pem"):
            self.assertIn(name, task["loop"])

    def test_stale_wal_and_shm_are_removed(self) -> None:
        task = self.main_path[index_of(self.main_path, "Remove stale SQLite sidecar files before the database copy")]
        self.assertEqual(task["ansible.builtin.file"]["state"], "absent")
        self.assertIn("-wal", task["loop"])
        self.assertIn("-shm", task["loop"])

    def test_restore_steps_do_not_swallow_failures(self) -> None:
        restore = find_block(self.tasks, "Restore Vaultwarden data with rollback")
        for task in flatten(restore["block"]):
            self.assertNotEqual(task.get("failed_when"), False, task.get("name"))
            self.assertNotIn("ignore_errors", task, task.get("name"))

    def test_rescue_rolls_back_and_leaves_service_stopped(self) -> None:
        restore = find_block(self.tasks, "Restore Vaultwarden data with rollback")
        rescue = restore["rescue"]
        names = [task.get("name") for task in rescue]
        self.assertIn("Put the safety copy back", names)
        rollback = rescue[names.index("Put the safety copy back")]
        self.assertIn('rsync -a --delete --checksum "$safety/data/" "$DATA_DIR/"', rollback["ansible.builtin.shell"]["cmd"])
        for task in rescue:
            systemd = task.get("ansible.builtin.systemd")
            if systemd and "state" in systemd:
                self.assertEqual(systemd["state"], "stopped")
        self.assertIn("ansible.builtin.fail", rescue[-1])
        self.assertIn("left stopped", rescue[-1]["ansible.builtin.fail"]["msg"])

    def test_stop_or_safety_failure_aborts_before_overwrite(self) -> None:
        guard = find_block(self.tasks, "Stop Vaultwarden and take a safety copy")
        self.assertEqual(len(guard["rescue"]), 1)
        self.assertIn("ansible.builtin.fail", guard["rescue"][0])

    def test_plaintext_is_removed_in_always(self) -> None:
        outer = find_block(self.tasks, "Restore with plaintext cleanup")
        always = {task["name"]: task for task in outer["always"]}
        local = always["Remove decrypted archive from controller"]
        self.assertEqual(local["delegate_to"], "localhost")
        self.assertEqual(local["ansible.builtin.file"]["state"], "absent")
        self.assertIn("Cleanup Vaultwarden restore staging directory", always)

    def test_safety_root_default_is_set(self) -> None:
        defaults = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text(encoding="utf-8"))
        self.assertTrue(defaults["vaultwarden_restore_safety_root"].startswith("/"))


if __name__ == "__main__":
    unittest.main()
