"""Every SQLite backup in the collection waits for a committing writer.

2026-10-17 and 2026-10-20 the generic Echoport runner failed with "database is
locked": `sqlite3 .backup` ran without a busy handler while a writer held its
exclusive lock (2.51.1 fixed that runner). The other Echoport runners now share
templates/_sqlite_backup.py.j2: `.timeout` before `.backup`, up to three
attempts, a partial copy removed, an integrity check that must print exactly
`ok`, and sqlite3's error text in the failure. The GoToSocial runner (remote
snapshot) is covered in test_gotosocial_echoport_backup.py, the generic runner
in test_echoport_sqlite_backup.py.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

import yaml
from jinja2 import ChainableUndefined, Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "roles" / "echoport_backup" / "templates"

# Runners that back up a live local database with sqlite_backup().
LOCAL_RUNNERS = (
    "echoport_backup.py.j2",
    "homeassistant_backup.py.j2",
    "graphyard_backup.py.j2",
    "delve_backup.py.j2",
    "vaultwarden_backup.py.j2",
)
# Off limits for this collection's maintenance (owned elsewhere); they keep
# their own snapshot code.
EXEMPT_RUNNERS = {"heis_production_backup.py.j2", "villakunterbunt_staging_backup.py.j2"}
ANSIBLE = shutil.which("ansible", path=str(Path(sys.executable).parent)) or shutil.which("ansible")


class _Lenient(ChainableUndefined):
    def __str__(self) -> str:
        return ""


def render_runner(template: str) -> types.ModuleType:
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), undefined=_Lenient)
    env.filters["to_json"] = lambda value: json.dumps([] if isinstance(value, ChainableUndefined) else value)
    env.filters["bool"] = lambda value: bool(value) and not isinstance(value, ChainableUndefined)
    env.filters["quote"] = lambda value: "'" + str(value) + "'"
    source = env.get_template(template).render()
    module = types.ModuleType(template.removesuffix(".py.j2"))
    with contextlib.redirect_stderr(io.StringIO()):
        exec(compile(source, template, "exec"), module.__dict__)  # noqa: S102
    module.SQLITE_BACKUP_RETRY_DELAY_SECONDS = 0
    return module


@unittest.skipUnless(shutil.which("sqlite3"), "sqlite3 CLI not installed")
class LocalRunnerSqliteBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db = self.tmp / "db.sqlite3"
        with contextlib.closing(sqlite3.connect(self.db)) as conn:
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("CREATE TABLE item (id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO item DEFAULT VALUES")
            conn.commit()
        self.out = self.tmp / "out" / "db.sqlite3"
        self.out.parent.mkdir()

    def hold_exclusive_lock(self) -> sqlite3.Connection:
        writer = sqlite3.connect(self.db, isolation_level=None, check_same_thread=False, timeout=0)
        self.addCleanup(writer.close)
        writer.execute("BEGIN EXCLUSIVE")
        writer.execute("INSERT INTO item DEFAULT VALUES")
        return writer

    def test_backup_waits_for_a_committing_writer(self) -> None:
        for template in LOCAL_RUNNERS:
            with self.subTest(runner=template):
                runner = render_runner(template)
                self.out.unlink(missing_ok=True)
                writer = self.hold_exclusive_lock()
                release = threading.Timer(0.5, lambda w=writer: w.execute("COMMIT"))
                release.start()
                self.addCleanup(release.cancel)
                with contextlib.redirect_stderr(io.StringIO()):
                    runner.sqlite_backup(str(self.db), self.out)
                release.join()
                with contextlib.closing(sqlite3.connect(self.out)) as conn:
                    count = conn.execute("SELECT count(*) FROM item").fetchone()[0]
                writer.close()
                with contextlib.closing(sqlite3.connect(self.db)) as conn:
                    expected = conn.execute("SELECT count(*) FROM item").fetchone()[0]
                self.assertEqual(count, expected)

    def test_lock_that_outlasts_every_attempt_fails_with_the_reason(self) -> None:
        for template in LOCAL_RUNNERS:
            with self.subTest(runner=template):
                runner = render_runner(template)
                writer = self.hold_exclusive_lock()
                runner.SQLITE_BUSY_TIMEOUT_MS = 100
                runner.SQLITE_BACKUP_ATTEMPTS = 2
                stderr = io.StringIO()
                try:
                    with contextlib.redirect_stderr(stderr), self.assertRaises(RuntimeError) as caught:
                        runner.sqlite_backup(str(self.db), self.out)
                finally:
                    writer.rollback()
                    writer.close()
                self.assertIn("database is locked", str(caught.exception))
                self.assertIn(str(self.db), str(caught.exception))
                self.assertIn("attempt 1/2 failed", stderr.getvalue())
                self.assertIn("attempt 2/2 failed", stderr.getvalue())
                self.assertFalse(self.out.exists(), "a partial copy was left behind")

    def test_a_failed_attempt_is_retried(self) -> None:
        for template in LOCAL_RUNNERS:
            with self.subTest(runner=template):
                runner = render_runner(template)
                self.out.unlink(missing_ok=True)
                real_attempt = runner._sqlite_backup_attempt
                calls = []

                def flaky(db_path, backup_path, real_attempt=real_attempt, calls=calls):
                    calls.append(db_path)
                    if len(calls) == 1:
                        backup_path.write_bytes(b"partial")
                        return "sqlite3 backup failed: Error: database is locked"
                    return real_attempt(db_path, backup_path)

                with mock.patch.dict(runner.__dict__, {"_sqlite_backup_attempt": flaky}):
                    with contextlib.redirect_stderr(io.StringIO()):
                        runner.sqlite_backup(str(self.db), self.out)
                self.assertEqual(len(calls), 2)
                with contextlib.closing(sqlite3.connect(self.out)) as conn:
                    self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_missing_source_is_not_created(self) -> None:
        missing = self.tmp / "missing.sqlite3"
        for template in LOCAL_RUNNERS:
            with self.subTest(runner=template):
                runner = render_runner(template)
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises((RuntimeError, FileNotFoundError)):
                    runner.sqlite_backup(str(missing), self.out)
                self.assertFalse(missing.exists())

    def test_integrity_check_must_print_exactly_ok(self) -> None:
        # "broken" contains "ok": a substring test accepted this report.
        report = "*** in database main ***\nrow 7 missing from index broken_idx\n"

        def fake_run(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, report, "")

        for template in LOCAL_RUNNERS:
            with self.subTest(runner=template):
                runner = render_runner(template)
                with mock.patch.object(runner.subprocess, "run", side_effect=fake_run):
                    if hasattr(runner, "run_cmd"):
                        with mock.patch.dict(runner.__dict__, {"run_cmd": lambda args, check=True: fake_run(args)}):
                            with self.assertRaises(RuntimeError) as caught:
                                runner.sqlite_integrity_check(str(self.db))
                    else:
                        with self.assertRaises(RuntimeError) as caught:
                            runner.sqlite_integrity_check(str(self.db))
                self.assertIn("broken_idx", str(caught.exception))


class SharedHelperIsUsedTests(unittest.TestCase):
    def test_no_runner_runs_its_own_sqlite_backup(self) -> None:
        backup_call = re.compile(r"""\.backup '|\.backup\(""")
        for template in sorted(TEMPLATE_DIR.glob("*.py.j2")):
            if template.name in EXEMPT_RUNNERS or template.name == "_sqlite_backup.py.j2":
                continue
            with self.subTest(template=template.name):
                source = template.read_text()
                self.assertIsNone(backup_call.search(source), "use templates/_sqlite_backup.py.j2")
                if "sqlite3" in source and "PRAGMA integrity_check" in source:
                    self.assertIn("{% include '_sqlite_backup.py.j2' %}", source)

    def test_helper_sets_the_busy_timeout_before_backup(self) -> None:
        runner = render_runner("marina_staging_backup.py.j2")
        argv = runner.sqlite_backup_argv("/srv/db.sqlite3", Path("/tmp/x/db.sqlite3"))
        self.assertEqual(argv, ["sqlite3", "/srv/db.sqlite3", ".timeout 30000", ".backup '/tmp/x/db.sqlite3'"])
        self.assertEqual((runner.SQLITE_BACKUP_ATTEMPTS, runner.SQLITE_BACKUP_RETRY_DELAY_SECONDS), (3, 0))

    @unittest.skipUnless(ANSIBLE, "ansible not installed")
    def test_ansible_template_module_resolves_the_include(self) -> None:
        """fastdeploy_runner renders runners from an absolute path; the include must resolve next to it."""
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "backup.py"
            defaults = ROOT / "roles" / "echoport_backup" / "defaults" / "main.yml"
            result = subprocess.run(
                [
                    ANSIBLE, "localhost", "-c", "local", "-i", "localhost,", "-m", "ansible.builtin.template",
                    "-a", f"src={TEMPLATE_DIR / 'backup.py.j2'} dest={dest}",
                    "-e", f"@{defaults}",
                ],
                capture_output=True, text=True, cwd=tmp,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            rendered = dest.read_text()
            self.assertIn('f".timeout {SQLITE_BUSY_TIMEOUT_MS}"', rendered)
            self.assertNotIn("{% include", rendered)
            compile(rendered, str(dest), "exec")


class AnsibleTaskBackupsTests(unittest.TestCase):
    """The on-host backup roles that run sqlite3 .backup hot also wait for writers."""

    ROLES = {
        "homelab_backup": "Perform SQLite hot backup",
        "work_app_backup": "Perform SQLite hot backup",
        "nyxmon_backup": "Create SQLite backup with .backup",
        "homeassistant_backup": "Create SQLite backup using .backup",
    }

    @staticmethod
    def find_task(tasks, name):
        for task in tasks:
            if task.get("name") == name:
                return task
            for key in ("block", "rescue", "always"):
                found = AnsibleTaskBackupsTests.find_task(task.get(key, []), name)
                if found:
                    return found
        return None

    def test_backup_command_sets_a_busy_timeout(self) -> None:
        for role, name in self.ROLES.items():
            with self.subTest(role=role):
                tasks = yaml.safe_load((ROOT / "roles" / role / "tasks" / "main.yml").read_text())
                task = self.find_task(tasks, name)
                self.assertIsNotNone(task, name)
                cmd = task["ansible.builtin.command"]["cmd"]
                self.assertRegex(cmd, r'"\.timeout 30000"\s+"\.backup ')
                self.assertTrue(task.get("retries") and task.get("until"), "a failed hot backup is retried")


if __name__ == "__main__":
    unittest.main()
