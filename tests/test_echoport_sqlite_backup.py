"""The generic Echoport runner backs up a SQLite database that is being written.

2026-10-17 and 2026-10-20: the nyxmon backup failed with "Failed to backup
database" because `sqlite3 .backup` ran without a busy handler while the
nyxmon agent (rollback journal, a commit every few seconds) held its exclusive
lock. The runner now passes `.timeout` before `.backup` and retries a failed
attempt.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sqlite3
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

import yaml
from ansible.plugins.filter.core import to_bool
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]
BACKUP_ROLE = ROOT / "roles" / "echoport_backup"


def load_runner(tmp: Path) -> types.ModuleType:
    env = Environment(loader=FileSystemLoader(BACKUP_ROLE / "templates"))
    env.filters["to_json"] = json.dumps
    env.filters["bool"] = to_bool
    defaults = yaml.safe_load((BACKUP_ROLE / "defaults" / "main.yml").read_text())
    defaults["echoport_backup_allowed_roots"] = [str(tmp)]
    defaults["echoport_backup_temp_dir"] = str(tmp / "work")
    source = env.get_template("backup.py.j2").render(**defaults)
    module = types.ModuleType("echoport_generic_runner")
    exec(compile(source, "backup.py", "exec"), module.__dict__)  # noqa: S102
    return module


@unittest.skipUnless(shutil.which("sqlite3"), "sqlite3 CLI not installed")
class SqliteBackupUnderWriteLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db = self.tmp / "db.sqlite3"
        with contextlib.closing(sqlite3.connect(self.db)) as conn:
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("CREATE TABLE check_result (id INTEGER PRIMARY KEY, status TEXT)")
            conn.execute("INSERT INTO check_result (status) VALUES ('ok')")
            conn.commit()
        self.runner = load_runner(self.tmp)
        self.runner.SQLITE_BACKUP_RETRY_DELAY_SECONDS = 0
        self.backup_path = self.tmp / "out.sqlite3"

    def hold_exclusive_lock(self) -> sqlite3.Connection:
        writer = sqlite3.connect(self.db, isolation_level=None, check_same_thread=False)
        self.addCleanup(writer.close)
        writer.execute("BEGIN EXCLUSIVE")
        writer.execute("INSERT INTO check_result (status) VALUES ('ok')")
        return writer

    def run_backup(self) -> tuple[str | None, str]:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            error = self.runner.backup_sqlite(str(self.db), self.backup_path)
        return error, stderr.getvalue()

    def test_backup_waits_for_a_committing_writer(self):
        writer = self.hold_exclusive_lock()
        release = threading.Timer(0.5, lambda: writer.execute("COMMIT"))
        release.start()
        self.addCleanup(release.cancel)

        error, _ = self.run_backup()

        self.assertIsNone(error)
        with contextlib.closing(sqlite3.connect(self.backup_path)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM check_result").fetchone()[0], 2)

    def test_lock_that_outlasts_every_attempt_fails_with_the_reason(self):
        self.hold_exclusive_lock()
        self.runner.SQLITE_BUSY_TIMEOUT_MS = 100
        self.runner.SQLITE_BACKUP_ATTEMPTS = 2

        error, stderr = self.run_backup()

        self.assertIn("database is locked", error)
        self.assertIn("attempt 1/2 failed", stderr)
        self.assertIn("attempt 2/2 failed", stderr)
        self.assertFalse(self.backup_path.exists())

    def test_a_failed_attempt_is_retried(self):
        real_attempt = self.runner._sqlite_backup_attempt
        calls = []

        def flaky(db_path, backup_path):
            calls.append(db_path)
            if len(calls) == 1:
                backup_path.write_bytes(b"partial")
                return "sqlite3 backup failed: Error: database is locked"
            return real_attempt(db_path, backup_path)

        with mock.patch.dict(self.runner.__dict__, {"_sqlite_backup_attempt": flaky}):
            error, stderr = self.run_backup()

        self.assertIsNone(error)
        self.assertEqual(len(calls), 2)
        self.assertIn("attempt 1/3 failed", stderr)
        with contextlib.closing(sqlite3.connect(self.backup_path)) as conn:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_missing_database_is_not_created(self):
        self.db.unlink()
        error, _ = self.run_backup()
        self.assertEqual(error, "database file not found")
        self.assertFalse(self.db.exists())


class BackupStepMessageTests(unittest.TestCase):
    def test_failure_step_carries_the_sqlite_error(self):
        source = (BACKUP_ROLE / "templates" / "backup.py.j2").read_text()
        self.assertIn('f".timeout {SQLITE_BUSY_TIMEOUT_MS}", f".backup \'{backup_path}\'"', source)
        self.assertIn('f"Failed to backup database: {db_path} ({db_error})"', source)


if __name__ == "__main__":
    unittest.main()
