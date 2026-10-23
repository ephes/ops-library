"""Contracts of the Echoport Django Chat staging database runner.

The runner is rendered from its Jinja template and run with ssh, pg_restore
and mc faked out; nothing touches a real host, database or bucket.
"""

from __future__ import annotations

import hashlib
import io
import json
import shlex
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
TEMPLATE = "django_chat_staging_db_backup.py.j2"
REQUIRED = ["wagtailcore_page", "cast_episode", "cast_audio", "auth_user", "django_migrations"]
COUNTED = ["wagtailcore_page", "cast_episode", "cast_audio", "auth_user"]
ALIAS = "backup-django-chat-staging-db"
HOST = "staging.example.org"


def render_runner(temp_dir: Path, **overrides: Any) -> types.ModuleType:
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), undefined=StrictUndefined, autoescape=False)
    variables: dict[str, Any] = {
        "echoport_backup_mc_install_path": "/usr/local/bin/mc",
        "echoport_backup_minio_alias": ALIAS,
        "echoport_backup_default_bucket": "backups",
        "django_chat_staging_db_backup_host": HOST,
        "django_chat_staging_db_backup_remote_user": "root",
        "django_chat_staging_db_backup_db_name": "django-chat",
        "django_chat_staging_db_backup_postgres_os_user": "postgres",
        "django_chat_staging_db_backup_restore_db_prefix": "django_chat_restore",
        "django_chat_staging_db_backup_required_tables": REQUIRED,
        "django_chat_staging_db_backup_counted_tables": COUNTED,
    }
    variables.update(overrides)
    source = env.get_template(TEMPLATE).render(**variables)
    module = types.ModuleType("django_chat_staging_db_backup_test")
    module.__file__ = str(TEMPLATE_DIR / TEMPLATE)
    exec(compile(source, module.__file__, "exec"), module.__dict__)

    # The external work dir check (_work_dir.py.j2) is covered by
    # test_echoport_runner_work_dirs; here run dirs go to temp_dir.
    def create_run_dir(prefix: str) -> Path:
        temp_dir.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=prefix, dir=temp_dir))

    module.create_run_dir = create_run_dir
    return module


class FakeHosts:
    """Plays the staging host (over ssh), local pg_restore and MinIO."""

    def __init__(self, root: Path, tables: list[str] | None = None, dump_bytes: bytes = b"PGDMP fake",
                 counts: dict[str, int] | None = None, existing_dbs: tuple[str, ...] = ()) -> None:
        self.root = root
        self.tables = REQUIRED + ["cast_post", "wagtailcore_site"] if tables is None else tables
        self.dump_bytes = dump_bytes
        self.counts = counts or {t: i + 1 for i, t in enumerate(COUNTED)}
        self.dumped_counts: dict[str, int] = {}
        self.restored_counts: dict[str, int] | None = None
        self.write_during_dump = False
        self.existing_dbs = existing_dbs
        self.calls: list[list[str]] = []
        self.remote_calls: list[str] = []
        self.remote_files: dict[str, bytes] = {}
        self.remote_dirs: set[str] = set()
        self.removed_dirs: list[str] = []
        self.corrupt_remote_copy = False
        self.stored: dict[str, bytes] = {}
        self.stat_size_delta = 0

    def run_cmd(self, args, check=True, stdin_path=None, stdout_path=None):
        self.calls.append(list(args))
        if args[0] == "ssh":
            self.assert_ssh(args)
            out = self.remote(args[-1], stdin_path, stdout_path)
        else:
            out = self.local(args)
        return subprocess.CompletedProcess(args, 0, out, "")

    @staticmethod
    def assert_ssh(args: list[str]) -> None:
        assert args[-2] == f"root@{HOST}", args
        assert "StrictHostKeyChecking=yes" in args and "BatchMode=yes" in args, args

    def remote(self, line: str, stdin_path, stdout_path) -> str:
        self.remote_calls.append(line)
        if line.startswith("umask 077 && cat > "):
            path = shlex.split(line.split(" > ", 1)[1])[0]
            data = Path(stdin_path).read_bytes()
            self.remote_files[path] = data + (b"x" if self.corrupt_remote_copy else b"")
            return ""
        stdin_to = None
        if " < " in line:
            line, stdin_to = line.split(" < ", 1)
            stdin_to = shlex.split(stdin_to)[0]
        argv = shlex.split(line)
        cmd = argv[4:] if argv[:1] == ["runuser"] else argv
        if cmd[0] == "pg_dump":
            Path(stdout_path).write_bytes(self.dump_bytes)
            self.dumped_counts = dict(self.counts)
            if self.write_during_dump:
                self.counts["auth_user"] += 1
            return ""
        if cmd[0] == "psql":
            sql = cmd[-1]
            database = cmd[cmd.index("-d") + 1]
            if "pg_database" in sql:
                return "1" if any(f"'{db}'" in sql for db in self.existing_dbs) else ""
            if "server_version" in sql:
                return "17.11"
            if sql.startswith("SELECT count(*) FROM public."):
                table = sql.split("public.")[1].rstrip(";")
                if database == "django-chat":
                    return str(self.counts[table])
                counts = self.restored_counts if self.restored_counts is not None else self.dumped_counts
                return str(counts[table])
        if cmd[0] == "mktemp":
            path = cmd[-1].replace("XXXXXXXX", "Ab12Cd34")
            self.remote_dirs.add(path)
            return path + "\n"
        if cmd[0] == "sha256sum":
            return hashlib.sha256(self.remote_files[cmd[1]]).hexdigest() + "  " + cmd[1] + "\n"
        if cmd[0] == "rm":
            self.removed_dirs.append(cmd[-1])
            return ""
        if cmd[0] in ("createdb", "pg_restore"):
            if cmd[0] == "pg_restore":
                assert stdin_to in self.remote_files, stdin_to
            return ""
        raise AssertionError(f"unexpected remote command: {line}")

    def local(self, args: list[str]) -> str:
        if args[0] == "pg_restore" and "--data-only" in args:
            table = next(a for a in args if a.startswith("--table=")).split("=", 1)[1]
            rows = [f"{i}\tBob Smith\x85 x" for i in range(self.dumped_counts[table])]
            return "\n".join([f"COPY public.{table} (id, value) FROM stdin;", *rows, "\\.", ""])
        if args[0] == "pg_restore" and "--list" in args:
            return "\n".join(
                f"{i}; 0 1 TABLE DATA public {t} django-chat" for i, t in enumerate(self.tables, start=3000)
            )
        if args[0].endswith("mc") and args[1] == "cp":
            src, dest = args[-2], args[-1]
            if dest.startswith(f"{ALIAS}/"):
                self.stored[dest] = Path(src).read_bytes()
            else:
                Path(dest).write_bytes(self.stored[src])
            return ""
        if args[0].endswith("mc") and args[1] == "stat":
            return json.dumps({"status": "success", "size": len(self.stored[args[-1]]) + self.stat_size_delta})
        raise AssertionError(f"unexpected local command: {args}")


class DjangoChatStagingDbRunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.runner = render_runner(self.root / "work")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_flow(self, host: FakeHosts, flow: str, cenv: dict) -> tuple[int, list[dict]]:
        events: list[dict] = []
        with mock.patch.object(self.runner, "run_cmd", host.run_cmd), \
                mock.patch.object(self.runner, "ensure_binaries", lambda: None), \
                mock.patch.object(self.runner, "_emit", events.append):
            rc = getattr(self.runner, flow)(cenv)
        return rc, events

    def backup(self, host: FakeHosts) -> tuple[int, list[dict]]:
        return self.run_flow(
            host, "backup_flow",
            {"ECHOPORT_TARGET": "django-chat-staging-db", "ECHOPORT_KEY_PREFIX": "django-chat-staging-db/t1"},
        )

    @staticmethod
    def result(events: list[dict]) -> dict:
        message = next(e["message"] for e in events if e.get("name") == "result")
        return json.loads(message.split("ECHOPORT_RESULT:", 1)[1])

    def test_backup_uploads_dump_and_manifest(self) -> None:
        host = FakeHosts(self.root)
        rc, events = self.backup(host)
        self.assertEqual(rc, 0, events)
        result = self.result(events)
        self.assertTrue(result["success"])
        self.assertEqual(result["key"], "django-chat-staging-db/t1.tar.gz")
        archive = host.stored[f"{ALIAS}/backups/django-chat-staging-db/t1.tar.gz"]
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            names = sorted(tar.getnames())
            manifest = json.load(tar.extractfile("manifest.json"))
        self.assertEqual(names, ["django-chat.dump", "manifest.json", "manifest.sha256"])
        self.assertEqual(manifest["database"], "django-chat")
        self.assertEqual(manifest["host"], HOST)
        self.assertEqual(manifest["row_counts"]["cast_episode"], 2)
        self.assertIn("cast_audio", manifest["tables"])
        dump = next(c for c in host.remote_calls if "pg_dump" in c)
        self.assertEqual(
            shlex.split(dump), ["runuser", "-u", "postgres", "--", "pg_dump", "--format=custom", "--dbname=django-chat"]
        )
        self.assertFalse(any((self.root / "work").iterdir()))

    def test_dump_without_a_required_table_fails(self) -> None:
        host = FakeHosts(self.root, tables=[t for t in REQUIRED if t != "cast_episode"])
        rc, events = self.backup(host)
        self.assertEqual(rc, 1)
        self.assertFalse(self.result(events)["success"])
        self.assertEqual(host.stored, {})

    def test_empty_dump_fails(self) -> None:
        host = FakeHosts(self.root, dump_bytes=b"")
        rc, _ = self.backup(host)
        self.assertEqual(rc, 1)
        self.assertEqual(host.stored, {})

    def test_upload_size_mismatch_fails(self) -> None:
        host = FakeHosts(self.root)
        host.stat_size_delta = 1
        rc, events = self.backup(host)
        self.assertEqual(rc, 1)
        self.assertFalse(self.result(events)["success"])

    def restore_env(self, host: FakeHosts, restore_id: str = "42", checksum: str | None = None) -> dict:
        self.backup(host)
        key = "django-chat-staging-db/t1.tar.gz"
        archive = host.stored[f"{ALIAS}/backups/{key}"]
        host.calls.clear()
        host.remote_calls.clear()
        return {
            "ECHOPORT_ACTION": "restore",
            "ECHOPORT_RESTORE_ID": restore_id,
            "ECHOPORT_KEY": key,
            "ECHOPORT_CHECKSUM": checksum or hashlib.sha256(archive).hexdigest(),
        }

    def test_restore_goes_into_a_scratch_database_on_the_host(self) -> None:
        host = FakeHosts(self.root)
        cenv = self.restore_env(host)
        rc, events = self.run_flow(host, "restore_flow", cenv)
        self.assertEqual(rc, 0, events)
        remote_dir = "/var/tmp/django-chat-db-restore.Ab12Cd34"
        self.assertIn(
            "runuser -u postgres -- pg_restore --no-owner --no-privileges --exit-on-error "
            f"--dbname=django_chat_restore_42 < {remote_dir}/django-chat.dump",
            host.remote_calls,
        )
        self.assertIn("runuser -u postgres -- createdb django_chat_restore_42", host.remote_calls)
        self.assertFalse(any("--dbname=django-chat" in c.split() for c in host.remote_calls))
        self.assertFalse(any("--clean" in c or "dropdb" in c for c in host.remote_calls))
        self.assertEqual(host.removed_dirs, [remote_dir])
        self.assertFalse(any((self.root / "work").iterdir()))

    def test_writes_during_the_dump_do_not_break_the_restore_check(self) -> None:
        host = FakeHosts(self.root)
        host.write_during_dump = True
        cenv = self.restore_env(host)
        rc, events = self.run_flow(host, "restore_flow", cenv)
        self.assertEqual(rc, 0, events)

    def test_restore_refuses_an_existing_scratch_database(self) -> None:
        host = FakeHosts(self.root, existing_dbs=("django_chat_restore_42",))
        rc, _ = self.run_flow(host, "restore_flow", self.restore_env(host))
        self.assertEqual(rc, 1)
        self.assertFalse(any("createdb" in c for c in host.remote_calls))

    def test_restore_refuses_a_corrupt_copy_on_the_host(self) -> None:
        host = FakeHosts(self.root)
        cenv = self.restore_env(host)
        host.corrupt_remote_copy = True
        rc, events = self.run_flow(host, "restore_flow", cenv)
        self.assertEqual(rc, 1)
        self.assertIn("differs from the archive", self.result(events)["error"])
        self.assertFalse(any("createdb" in c for c in host.remote_calls))
        self.assertEqual(host.removed_dirs, ["/var/tmp/django-chat-db-restore.Ab12Cd34"])

    def test_restore_refuses_a_bad_checksum_or_restore_id(self) -> None:
        host = FakeHosts(self.root)
        rc, _ = self.run_flow(host, "restore_flow", self.restore_env(host, checksum="0" * 64))
        self.assertEqual(rc, 1)
        host = FakeHosts(self.root)
        rc, _ = self.run_flow(host, "restore_flow", self.restore_env(host, restore_id="1; DROP"))
        self.assertEqual(rc, 1)
        self.assertFalse(any("createdb" in c for c in host.remote_calls))

    def test_restore_fails_on_row_count_mismatch(self) -> None:
        host = FakeHosts(self.root)
        cenv = self.restore_env(host)
        host.restored_counts = dict(host.dumped_counts, cast_episode=0)
        rc, events = self.run_flow(host, "restore_flow", cenv)
        self.assertEqual(rc, 1)
        self.assertIn("Row counts differ", self.result(events)["error"])

    def test_restore_fails_when_the_manifest_lacks_a_counted_table(self) -> None:
        for counted in ([], COUNTED[:2]):
            with self.subTest(recorded=counted):
                host = FakeHosts(self.root)
                cenv = self.restore_env(host)
                runner = render_runner(self.root / "work", django_chat_staging_db_backup_counted_tables=counted)
                self.runner, original = runner, self.runner
                try:
                    host.calls.clear()
                    host.remote_calls.clear()
                    rc, _ = self.run_flow(host, "backup_flow", {"ECHOPORT_KEY_PREFIX": "django-chat-staging-db/t2"})
                    self.assertEqual(rc, 0)
                finally:
                    self.runner = original
                archive = host.stored[f"{ALIAS}/backups/django-chat-staging-db/t2.tar.gz"]
                cenv = dict(cenv, ECHOPORT_KEY="django-chat-staging-db/t2.tar.gz",
                            ECHOPORT_CHECKSUM=hashlib.sha256(archive).hexdigest())
                host.restored_counts = {t: 999 for t in COUNTED}
                rc, events = self.run_flow(host, "restore_flow", cenv)
                self.assertEqual(rc, 1)
                self.assertIn("no row count for", self.result(events)["error"])
                self.assertIn("cast_audio", self.result(events)["error"])

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
        for override in (
            {"django_chat_staging_db_backup_db_name": "django-chat; DROP"},
            {"django_chat_staging_db_backup_host": "staging;rm"},
            {"django_chat_staging_db_backup_restore_db_prefix": "django-chat"},
            {"django_chat_staging_db_backup_counted_tables": ["auth_user; x"]},
        ):
            runner = render_runner(self.root / "work", **override)
            with self.assertRaises(ValueError, msg=override):
                runner.validate_settings()

    def test_unexpected_remote_temp_dir_is_refused_and_not_removed(self) -> None:
        host = FakeHosts(self.root)
        with mock.patch.object(self.runner, "run_cmd", host.run_cmd), \
                mock.patch.object(host, "remote", lambda line, *a: "/tmp\n"):
            with self.assertRaises(RuntimeError):
                self.runner.make_remote_temp_dir()
            self.runner.remove_remote_temp_dir("/tmp")
        self.assertEqual(len(host.calls), 1)


if __name__ == "__main__":
    unittest.main()
