"""Contracts of the Echoport mail database runner (target `mail-db`).

The runner is rendered from its Jinja template and run with pg_dump, psql,
pg_restore and mc faked out; nothing touches a real database or bucket.
"""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from jinja2 import Environment, FileSystemLoader, StrictUndefined


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "roles" / "echoport_backup" / "templates"
TEMPLATE = "mail_db_backup.py.j2"
REQUIRED = ["domain", "mailbox", "alias", "alias_domain", "admin", "domain_admins", "config"]
COUNTED = ["domain", "mailbox", "alias", "alias_domain", "admin", "domain_admins"]


def render_runner(temp_dir: Path, **overrides: Any) -> types.ModuleType:
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), undefined=StrictUndefined, autoescape=False)
    variables: dict[str, Any] = {
        "echoport_backup_mc_install_path": "/usr/local/bin/mc",
        "echoport_backup_minio_alias": "backup-mail-db",
        "echoport_backup_default_bucket": "backups",
        "mail_db_echoport_backup_db_name": "mail",
        "mail_db_echoport_backup_postgres_os_user": "postgres",
        "mail_db_echoport_backup_restore_db_prefix": "mail_restore",
        "mail_db_echoport_backup_required_tables": REQUIRED,
        "mail_db_echoport_backup_counted_tables": COUNTED,
    }
    variables.update(overrides)
    source = env.get_template(TEMPLATE).render(**variables)
    module = types.ModuleType("mail_db_backup_test")
    module.__file__ = str(TEMPLATE_DIR / TEMPLATE)
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    # The external work dir check (_work_dir.py.j2) is covered by
    # test_echoport_runner_work_dirs; here run dirs go to temp_dir.
    def create_run_dir(prefix: str) -> Path:
        temp_dir.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=prefix, dir=temp_dir))

    module.create_run_dir = create_run_dir
    return module


class FakeHost:
    """Plays PostgreSQL and MinIO for the runner's run_cmd calls."""

    def __init__(self, root: Path, tables: list[str] | None = None, dump_bytes: bytes = b"PGDMP fake",
                 counts: dict[str, int] | None = None, existing_dbs: tuple[str, ...] = ()) -> None:
        self.root = root
        self.tables = REQUIRED + ["log", "vacation"] if tables is None else tables
        self.dump_bytes = dump_bytes
        self.counts = counts or {t: i + 1 for i, t in enumerate(COUNTED)}
        self.dumped_counts: dict[str, int] = {}
        self.restored_counts: dict[str, int] | None = None
        self.write_during_dump = False
        self.existing_dbs = existing_dbs
        self.calls: list[list[str]] = []
        self.stored: dict[str, bytes] = {}
        self.stat_size_delta = 0

    def run_cmd(self, args, check=True, stdin_path=None, stdout_path=None):
        self.calls.append(list(args))
        cmd = args[4:] if args[:1] == ["runuser"] else args
        out = ""
        if cmd[0] == "pg_dump":
            Path(stdout_path).write_bytes(self.dump_bytes)
            self.dumped_counts = dict(self.counts)
            if self.write_during_dump:
                # A mailbox is created after pg_dump took its snapshot.
                self.counts["mailbox"] += 1
        elif cmd[0] == "pg_restore" and "--data-only" in cmd:
            table = next(a for a in cmd if a.startswith("--table=")).split("=", 1)[1]
            rows = [f"{i}\tBob\u2028Smith\x85\u2029x" for i in range(self.dumped_counts[table])]
            out = "\n".join([f"COPY public.{table} (id, value) FROM stdin;", *rows, "\\.", ""])
        elif cmd[0] == "pg_restore" and "--list" in cmd:
            out = "\n".join(
                f"{i}; 0 1 TABLE DATA public {t} mail" for i, t in enumerate(self.tables, start=3000)
            )
        elif cmd[0] == "psql":
            sql = cmd[-1]
            database = cmd[cmd.index("-d") + 1]
            if "pg_database" in sql:
                out = "1" if any(f"'{db}'" in sql for db in self.existing_dbs) else ""
            elif "server_version" in sql:
                out = "17.11"
            elif sql.startswith("SELECT count(*) FROM public."):
                table = sql.split("public.")[1].rstrip(";")
                if database == "mail":
                    counts = self.counts
                else:
                    counts = self.restored_counts if self.restored_counts is not None else self.dumped_counts
                out = str(counts[table])
        elif cmd[0].endswith("mc") and cmd[1] == "cp":
            src, dest = cmd[-2], cmd[-1]
            if dest.startswith("backup-mail-db/"):
                self.stored[dest] = Path(src).read_bytes()
            else:
                Path(dest).write_bytes(self.stored[src])
        elif cmd[0].endswith("mc") and cmd[1] == "stat":
            out = json.dumps({"status": "success", "size": len(self.stored[cmd[-1]]) + self.stat_size_delta})
        result = subprocess.CompletedProcess(args, 0, out, "")
        return result


class MailDbRunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.runner = render_runner(self.root / "work")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_flow(self, host: FakeHost, flow: str, cenv: dict) -> tuple[int, list[dict]]:
        events: list[dict] = []
        with mock.patch.object(self.runner, "run_cmd", host.run_cmd), \
                mock.patch.object(self.runner, "ensure_binaries", lambda: None), \
                mock.patch.object(self.runner, "_emit", events.append):
            rc = getattr(self.runner, flow)(cenv)
        return rc, events

    def backup(self, host: FakeHost) -> tuple[int, list[dict]]:
        return self.run_flow(host, "backup_flow", {"ECHOPORT_TARGET": "mail-db", "ECHOPORT_KEY_PREFIX": "mail-db/t1"})

    @staticmethod
    def result(events: list[dict]) -> dict:
        message = next(e["message"] for e in events if e.get("name") == "result")
        return json.loads(message.split("ECHOPORT_RESULT:", 1)[1])

    def test_backup_uploads_dump_and_manifest(self) -> None:
        host = FakeHost(self.root)
        rc, events = self.backup(host)
        self.assertEqual(rc, 0)
        result = self.result(events)
        self.assertTrue(result["success"])
        self.assertEqual(result["key"], "mail-db/t1.tar.gz")
        archive = host.stored["backup-mail-db/backups/mail-db/t1.tar.gz"]
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            names = sorted(tar.getnames())
            manifest = json.load(tar.extractfile("manifest.json"))
        self.assertEqual(names, ["mail.dump", "manifest.json", "manifest.sha256"])
        self.assertEqual(manifest["database"], "mail")
        self.assertEqual(manifest["row_counts"]["mailbox"], 2)
        self.assertIn("mailbox", manifest["tables"])
        dump = next(c for c in host.calls if "pg_dump" in c)
        self.assertEqual(dump[:4], ["runuser", "-u", "postgres", "--"])
        self.assertIn("--format=custom", dump)
        self.assertFalse(any((self.root / "work").iterdir()))

    def test_dump_without_a_required_table_fails(self) -> None:
        host = FakeHost(self.root, tables=[t for t in REQUIRED if t != "mailbox"])
        rc, events = self.backup(host)
        self.assertEqual(rc, 1)
        self.assertFalse(self.result(events)["success"])
        self.assertEqual(host.stored, {})

    def test_empty_dump_fails(self) -> None:
        host = FakeHost(self.root, dump_bytes=b"")
        rc, _ = self.backup(host)
        self.assertEqual(rc, 1)
        self.assertEqual(host.stored, {})

    def test_upload_size_mismatch_fails(self) -> None:
        host = FakeHost(self.root)
        host.stat_size_delta = 1
        rc, events = self.backup(host)
        self.assertEqual(rc, 1)
        self.assertFalse(self.result(events)["success"])

    def restore_env(self, host: FakeHost, restore_id: str = "42", checksum: str | None = None) -> dict:
        self.backup(host)
        key = "mail-db/t1.tar.gz"
        archive = host.stored[f"backup-mail-db/backups/{key}"]
        host.calls.clear()
        return {
            "ECHOPORT_ACTION": "restore",
            "ECHOPORT_RESTORE_ID": restore_id,
            "ECHOPORT_KEY": key,
            "ECHOPORT_CHECKSUM": checksum or hashlib.sha256(archive).hexdigest(),
        }

    def test_restore_goes_into_a_scratch_database(self) -> None:
        host = FakeHost(self.root)
        cenv = self.restore_env(host)
        rc, events = self.run_flow(host, "restore_flow", cenv)
        self.assertEqual(rc, 0, events)
        restore = next(c for c in host.calls if c[4:5] == ["pg_restore"] and "--list" not in c)
        self.assertIn("--dbname=mail_restore_42", restore)
        self.assertIn(["runuser", "-u", "postgres", "--", "createdb", "mail_restore_42"], host.calls)
        self.assertFalse(any("--dbname=mail" == arg for call in host.calls for arg in call))
        self.assertFalse(any("--clean" in call for call in host.calls))

    def test_writes_during_the_dump_do_not_break_the_restore_check(self) -> None:
        host = FakeHost(self.root)
        host.write_during_dump = True
        cenv = self.restore_env(host)
        archive = host.stored["backup-mail-db/backups/mail-db/t1.tar.gz"]
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            manifest = json.load(tar.extractfile("manifest.json"))
        self.assertEqual(manifest["row_counts"]["mailbox"], 2)
        self.assertEqual(host.counts["mailbox"], 3)
        rc, events = self.run_flow(host, "restore_flow", cenv)
        self.assertEqual(rc, 0, events)

    def test_restore_refuses_an_existing_scratch_database(self) -> None:
        host = FakeHost(self.root, existing_dbs=("mail_restore_42",))
        rc, _ = self.run_flow(host, "restore_flow", self.restore_env(host))
        self.assertEqual(rc, 1)
        self.assertFalse(any("createdb" in call for call in host.calls))

    def test_restore_refuses_a_bad_checksum_or_restore_id(self) -> None:
        host = FakeHost(self.root)
        rc, _ = self.run_flow(host, "restore_flow", self.restore_env(host, checksum="0" * 64))
        self.assertEqual(rc, 1)
        host = FakeHost(self.root)
        rc, _ = self.run_flow(host, "restore_flow", self.restore_env(host, restore_id="1; DROP"))
        self.assertEqual(rc, 1)
        self.assertFalse(any("createdb" in call for call in host.calls))

    def test_restore_fails_on_row_count_mismatch(self) -> None:
        host = FakeHost(self.root)
        cenv = self.restore_env(host)
        host.restored_counts = dict(host.dumped_counts, mailbox=0)
        rc, events = self.run_flow(host, "restore_flow", cenv)
        self.assertEqual(rc, 1)
        self.assertIn("Row counts differ", self.result(events)["error"])

    def test_restore_refuses_unsafe_archive_members(self) -> None:
        bad = self.root / "bad.tar.gz"
        with tarfile.open(bad, "w:gz") as tar:
            info = tarfile.TarInfo("../escape")
            info.size = 1
            tar.addfile(info, io.BytesIO(b"x"))
        (self.root / "x").mkdir()
        with self.assertRaises(ValueError):
            self.runner.safe_extract_tarball(bad, self.root / "x")

    def test_invalid_settings_are_refused(self) -> None:
        runner = render_runner(self.root / "work", mail_db_echoport_backup_db_name="mail; DROP")
        with self.assertRaises(ValueError):
            runner.validate_settings()


if __name__ == "__main__":
    unittest.main()
