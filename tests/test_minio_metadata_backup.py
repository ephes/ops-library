"""Contracts for metadata-only MinIO backups and their restore.

A metadata-only backup must never stop MinIO or touch its data directories,
and restoring such a snapshot must never rsync data (the snapshot has none:
an rsync --delete from an empty tree would wipe the bucket data). Molecule
(`just molecule-test minio_backup`) runs the real thing against a MinIO
server; these checks pin the gating so a refactor cannot drop it silently.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / "roles" / "minio_backup"
RESTORE = ROOT / "roles" / "minio_restore"


def load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def task(tasks: list[dict], name: str) -> dict:
    for item in tasks:
        if item.get("name") == name:
            return item
    raise AssertionError(f"task {name!r} not found")


def conditions(item: dict) -> list[str]:
    when = item.get("when", [])
    return [when] if isinstance(when, str) else list(when)


class MetadataBackupTests(unittest.TestCase):
    def test_defaults_keep_the_full_backup_and_all_snapshots(self) -> None:
        defaults = load(BACKUP / "defaults" / "main.yml")
        self.assertIs(defaults["minio_backup_include_data"], True)
        self.assertEqual(defaults["minio_backup_keep_count"], 0)
        self.assertGreater(defaults["minio_backup_metadata_min_free_bytes"], 0)

    def test_service_stop_and_data_copy_only_in_full_scope(self) -> None:
        main = load(BACKUP / "tasks" / "main.yml")
        cold = task(main, "Perform cold backup of data and configuration")
        self.assertEqual(cold["ansible.builtin.import_tasks"], "cold_backup.yml")
        self.assertIn("minio_backup_include_data | bool", conditions(cold))
        config = task(main, "Copy MinIO configuration files (metadata-only backup)")
        self.assertEqual(config["ansible.builtin.import_tasks"], "config.yml")
        self.assertIn("not (minio_backup_include_data | bool)", conditions(config))
        # config.yml itself must not stop or start anything.
        config_tasks = load(BACKUP / "tasks" / "config.yml")
        self.assertFalse(any("ansible.builtin.systemd" in t for t in config_tasks))

    def test_data_directories_are_not_touched_in_metadata_scope(self) -> None:
        validate = load(BACKUP / "tasks" / "validate.yml")
        for name in ("Verify MinIO data directories exist", "Ensure all data directories are present"):
            self.assertIn("minio_backup_include_data | bool", conditions(task(validate, name)))
        disk = load(BACKUP / "tasks" / "disk_check.yml")
        self.assertIn("minio_backup_include_data | bool", conditions(task(disk, "Measure MinIO data directories")))

    def test_metadata_records_scope_and_no_data_dirs(self) -> None:
        finalize = load(BACKUP / "tasks" / "finalize.yml")
        metadata = task(finalize, "Build backup metadata structure")["ansible.builtin.set_fact"]["minio_backup_metadata"]
        self.assertIn("'metadata'", metadata["scope"])
        self.assertIn("else []", metadata["data_dirs"])

    def test_retention_is_opt_in_and_prefix_bound(self) -> None:
        main = load(BACKUP / "tasks" / "main.yml")
        retention = task(main, "Apply backup retention")
        self.assertIn("(minio_backup_keep_count | int) > 0", conditions(retention))
        tasks = load(BACKUP / "tasks" / "retention.yml")
        find = task(tasks, "retention | Find backups of this prefix")["ansible.builtin.find"]
        self.assertFalse(find["recurse"])
        select = task(tasks, "retention | Select backups beyond the retention count")["ansible.builtin.set_fact"]
        self.assertIn("regex_escape", select["minio_backup_retention_expired"])
        self.assertIn("[0-9]{8}T[0-9]{6}$", select["minio_backup_retention_expired"])


class MetadataRestoreTests(unittest.TestCase):
    def test_defaults(self) -> None:
        defaults = load(RESTORE / "defaults" / "main.yml")
        self.assertIs(defaults["minio_restore_allow_metadata_only"], True)
        self.assertIs(defaults["minio_restore_metadata_restore_system_files"], False)

    def test_metadata_scope_has_no_data_directories(self) -> None:
        validate = load(RESTORE / "tasks" / "validate.yml")
        scope = task(validate, "Record snapshot scope")["ansible.builtin.set_fact"]
        self.assertEqual(scope["minio_restore_scope"], "{{ minio_restore_metadata.scope | default('full') }}")
        targets = task(validate, "Determine target data directories for restore")["ansible.builtin.set_fact"]
        self.assertIn("if minio_restore_scope == 'metadata'", targets["minio_restore_target_data_dirs"])
        task(validate, "Validate snapshot scope")

    def test_service_stop_and_rsync_are_gated(self) -> None:
        restore = load(RESTORE / "tasks" / "restore.yml")[0]
        system = task(restore["block"], "Restore MinIO service and data")
        self.assertIn("minio_restore_scope == 'full'", system["when"])
        self.assertIn("minio_restore_metadata_restore_system_files", system["when"])
        system_tasks = load(RESTORE / "tasks" / "restore_system.yml")
        guard = system_tasks[0]
        self.assertEqual(guard["name"], "Refuse a full restore without data directories")
        prepare = load(RESTORE / "tasks" / "prepare.yml")
        for name in ("Check snapshot data directory exists", "Fail if snapshot data directory is missing"):
            self.assertIn("minio_restore_scope == 'full'", conditions(task(prepare, name)))


if __name__ == "__main__":
    unittest.main()
