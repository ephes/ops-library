"""Every migrated Echoport runner works only on the external encrypted disk.

The runners below keep their per-run dirs (dumps, staging copies, archives,
rclone configs) below ``<prefix>_work_dir`` on ``<prefix>_work_mount``
(macmini: ``/mnt/cryptdata``) through the shared ``_work_dir.py.j2`` include.
For each runner this module checks:

- the rendered defaults and overrides, and that the old temp dir variables
  (``echoport_backup_temp_dir``, ``*_temp_dir``) are ignored;
- a missing mount refuses backup and restore before ``mkdtemp`` and before
  any command after the read-only configuration checks (no fallback to
  ``/tmp`` or the system temp dir);
- a symlinked work dir is refused without writing to its target;
- a failing backup or restore removes its run dir, and restore creates its
  run dir in ``WORK_DIR``.

The include itself (device checks, owner, retention) is covered in depth by
``test_unifi_echoport_backup_workdir`` and ``test_homepage_echoport_backup_workdir``.
"""

import contextlib
import hashlib
import io
import json
import os
import stat
import subprocess
import tempfile
import types
import unittest
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from unittest import mock

from ansible.plugins.filter.core import FilterModule
from jinja2 import ChainableUndefined, Environment, FileSystemLoader

from tests.test_unifi_echoport_backup_workdir import FakeOs

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "roles/echoport_backup/templates"
MC = "/usr/local/bin/mc"
BASE_VARS = {
    "echoport_backup_mc_install_path": MC,
    "echoport_backup_minio_alias": "minio",
    "echoport_backup_default_bucket": "backups",
    "echoport_backup_minio_prefix_aliases": {},
    "echoport_backup_allowed_roots": ["/var/lib/"],
    "fastdeploy_echoport_backup_health_headers": {},
    "paperless_echoport_backup_health_headers": {},
}
# Read-only configuration checks (path validation, `which` probes, reading
# credentials files) that some runners run before the run dir exists. They
# write nothing, so the work dir check only has to come before the first
# write; they are stubbed so the test reaches it, and every command after
# them (dumps, systemctl, mc, ssh) must not run when the mount is missing.
PRECHECKS = (
    "validate_config_paths",
    "validate_settings",
    "ensure_binaries",
    "detect_php_service",
    "read_db_credentials",
    "require_commands",
    "validate_ssh_identifiers",
    "validate_identifiers",
    "mc_alias_configured",  # generic runner: `mc alias list` before the run dir
)


@dataclass(frozen=True)
class Runner:
    template: str
    prefix: str  # <prefix>_work_dir, <prefix>_work_mount, <prefix>_work_retention_hours
    service: str
    root: bool
    # Entry point: a name called with (cenv) (or (config, context, cenv) for
    # main_*), or (name, kwargs) for runners whose entry points take arguments.
    backup: object
    restore: object
    legacy: tuple = ()  # old *_temp_dir variables besides echoport_backup_temp_dir
    run_dir_prefixes: tuple = ()
    variables: dict = field(default_factory=dict)  # needed to reach the run dir


RUNNERS = (
    Runner("delve_backup.py.j2", "delve_echoport_backup", "delve-backup", True, "backup_flow", "restore_flow",
           ("delve_echoport_backup_temp_dir",), ("delve_backup_", "delve_restore_")),
    Runner("snappymail_backup.py.j2", "snappymail_echoport_backup", "snappymail-backup", True, "backup_flow", "restore_flow",
           ("snappymail_echoport_backup_temp_dir",), ("snappymail_backup_", "snappymail_restore_")),
    Runner("vaultwarden_backup.py.j2", "vaultwarden_echoport_backup", "vaultwarden-backup", True, "backup_flow", "restore_flow",
           ("vaultwarden_echoport_backup_temp_dir",), ("vaultwarden_backup_", "vaultwarden_restore_")),
    Runner("postfixadmin_backup.py.j2", "postfixadmin_echoport_backup", "postfixadmin-backup", True, "backup_flow", "restore_flow",
           ("postfixadmin_echoport_backup_temp_dir",), ("postfixadmin_backup_", "postfixadmin_restore_")),
    Runner("minecraft_java_backup.py.j2", "minecraft_java_echoport_backup", "minecraft-java-backup", True, "backup_flow", "restore_flow",
           ("minecraft_java_echoport_backup_temp_dir",), ("minecraft_backup_", "minecraft_restore_"),
           {"minecraft_java_echoport_backup_default_world_name": "world",
            "minecraft_java_echoport_backup_server_dir": "/nonexistent/minecraft",
            "minecraft_java_echoport_backup_allowed_roots": ["/"]}),
    Runner("homeassistant_backup.py.j2", "homeassistant_backup", "homeassistant-backup", True, "backup", "restore",
           ("homeassistant_backup_temp_dir",), ("ha-backup-", "ha-restore-")),
    Runner("graphyard_backup.py.j2", "graphyard_echoport_backup", "graphyard-backup", True, "backup_flow", "restore_flow",
           ("graphyard_echoport_backup_temp_dir",), ("graphyard-backup-", "graphyard-restore-")),
    # Batch B: root runners with postgres or the former get_temp_parent_dir() fallback.
    Runner("fastdeploy_backup.py.j2", "fastdeploy_echoport_backup", "fastdeploy-backup", True, "backup", "restore",
           ("fastdeploy_echoport_backup_temp_dir", "weeknotes_home_backup_temp_dir"), ("fd-backup-", "fd-restore-")),
    Runner("echoport_backup.py.j2", "echoport_self_backup", "echoport-self-backup", True, "backup", "restore",
           ("echoport_self_backup_temp_dir",), ("echoport-self-backup-", "echoport-self-restore-")),
    Runner("paperless_backup.py.j2", "paperless_echoport_backup", "paperless-backup", True, "backup", "restore",
           ("paperless_echoport_backup_temp_dir",), ("paperless-backup-", "paperless-restore-")),
    Runner("mail_db_backup.py.j2", "mail_db_echoport_backup", "mail-db-backup", True, "backup_flow", "restore_flow",
           ("mail_db_echoport_backup_temp_dir",), ("mail_db_backup_", "mail_db_restore_"),
           {"mail_db_echoport_backup_db_name": "mail", "mail_db_echoport_backup_restore_db_prefix": "mail_restore",
            "mail_db_echoport_backup_postgres_os_user": "postgres"}),
    # Batch C: the generic runner (17 targets), entry points take (config, context, cenv).
    Runner("backup.py.j2", "echoport_backup", "echoport-backup", True, "main_backup", "main_restore",
           (), ("echoport_", "echoport_restore_")),
    # Batch D: deploy runners (no sudo to root), remote PostgreSQL over SSH.
    Runner("django_chat_staging_db_backup.py.j2", "django_chat_staging_db_backup", "django-chat-staging-db-backup", False,
           "backup_flow", "restore_flow",
           ("django_chat_staging_db_backup_temp_dir", "ggs_lennestrasse_staging_db_backup_temp_dir",
            "mastodon_production_db_backup_temp_dir"),
           ("django_chat_db_backup_", "django_chat_db_restore_"),
           {"django_chat_staging_db_backup_db_name": "django-chat",
            "django_chat_staging_db_backup_restore_db_prefix": "django_chat_restore"}),
    # Batch E: deploy runners with the former fallback, no postgres reading local files.
    Runner("gotosocial_backup.py.j2", "gotosocial_backup", "gotosocial-backup", False,
           ("backup", dict(bucket="backups", key_prefix="gotosocial/t", timestamp="t")),
           ("restore", dict(bucket="backups", key="gotosocial/t.tar.gz", expected_checksum="0" * 64)),
           (), ("gotosocial-backup-", "gotosocial-restore-")),
    Runner("marina_staging_backup.py.j2", "marina_staging_backup", "marina-staging-backup", False,
           ("backup", dict(remote_host="staging", remote_user="root", db_path="/home/marina/site/db.sqlite3",
                           backup_files=[], service_name="marina.service", bucket="backups", key_prefix="marina/t",
                           timestamp="t")),
           ("restore", dict(remote_host="staging", remote_user="root", db_path="/home/marina/site/db.sqlite3",
                            backup_files=[], service_name="marina.service", restore_owner="marina:marina",
                            bucket="backups", key="marina/t.tar.gz", expected_checksum="0" * 64)),
           ("marina_staging_backup_temp_dir", "marina_production_backup_temp_dir"), ("marina-backup-", "marina-restore-")),
    Runner("python_podcast_media_backup.py.j2", "python_podcast_media_backup", "python-podcast-media-backup", False,
           ("backup", dict(bucket="backups", key_prefix="pp-media/t", objects_prefix="pp-media/current",
                           credentials=dict.fromkeys(("source_access_key", "source_secret_key", "dest_access_key", "dest_secret_key"), "x"))),
           ("restore", dict(bucket="backups", key_prefix="pp-media/t", expected_checksum="0" * 64,
                            credentials=dict.fromkeys(("source_access_key", "source_secret_key", "dest_access_key", "dest_secret_key"), "x"))),
           ("python_podcast_media_backup_temp_dir",), ("python-podcast-media-",)),
    # Batch F: deploy runners whose restore scp's the dump to staging for pg_restore as postgres.
    Runner("python_podcast_production_db_backup.py.j2", "pp_prod_db_backup", "python-podcast-production-db-backup", False,
           ("backup", dict(bucket="backups", key_prefix="pp/t", timestamp="t")),
           ("restore", dict(bucket="backups", key="pp/t.tar.gz", expected_checksum="0" * 64)),
           ("pp_prod_db_backup_temp_dir",), ("pp-backup-", "pp-restore-")),
    Runner("python_podcast_staging_backup.py.j2", "pp_staging_backup", "python-podcast-staging-backup", False,
           ("backup", dict(bucket="backups", key_prefix="pp/t", timestamp="t")),
           ("restore", dict(bucket="backups", key="pp/t.tar.gz", expected_checksum="0" * 64)),
           ("pp_staging_backup_temp_dir",), ("pp-backup-", "pp-restore-")),
    Runner("homepage_staging_backup.py.j2", "homepage_staging_backup", "homepage-staging-backup", False,
           ("backup", dict(bucket="backups", key_prefix="homepage/t", timestamp="t")),
           ("restore", dict(bucket="backups", key="homepage/t.tar.gz", expected_checksum="0" * 64)),
           ("homepage_staging_backup_temp_dir",), ("homepage-backup-", "homepage-restore-")),
)

RESTORE_ENV = {
    "ECHOPORT_ACTION": "restore",
    "ECHOPORT_TARGET": "t",
    "ECHOPORT_BUCKET": "backups",
    "ECHOPORT_KEY": "t/2026-10-23T02-00-00.tar.gz",
    "ECHOPORT_CHECKSUM": "0" * 64,
    "ECHOPORT_RESTORE_ID": "1",
}
BACKUP_ENV = {"ECHOPORT_ACTION": "backup", "ECHOPORT_TARGET": "t", "ECHOPORT_BUCKET": "backups", "ECHOPORT_RUN_ID": "1"}


def render(template: str, **variables) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES), undefined=ChainableUndefined)
    ansible_filters = FilterModule().filters()
    for name in ("to_json", "regex_replace", "bool", "b64encode", "quote"):
        if name in ansible_filters:
            env.filters[name] = ansible_filters[name]
    return env.get_template(template).render(**{**BASE_VARS, **variables})


def load_runner(template: str, **variables) -> types.ModuleType:
    module = types.ModuleType(template.replace(".py.j2", "_work_dirs_test"))
    module.__file__ = str(TEMPLATES / template)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        exec(compile(render(template, **variables), module.__file__, "exec"), module.__dict__)
    return module


class RenderedDefaultsTest(unittest.TestCase):
    def test_defaults_point_at_the_external_disk(self):
        for spec in RUNNERS:
            with self.subTest(template=spec.template):
                runner = load_runner(spec.template)
                self.assertEqual(runner.WORK_DIR, f"/mnt/cryptdata/backups/tmp/{spec.service}")
                self.assertEqual(runner.WORK_MOUNT, "/mnt/cryptdata")
                self.assertEqual(runner.WORK_RETENTION_HOURS, 24)
                self.assertEqual(runner.WORK_OWNER_UID, 0 if spec.root else os.geteuid())
                self.assertEqual(tuple(runner.RUN_DIR_PREFIXES), spec.run_dir_prefixes)

    def test_variables_override_defaults(self):
        for spec in RUNNERS:
            with self.subTest(template=spec.template):
                runner = load_runner(
                    spec.template,
                    **{
                        f"{spec.prefix}_work_dir": "/srv/ext/work/x",
                        f"{spec.prefix}_work_mount": "/srv/ext",
                        f"{spec.prefix}_work_retention_hours": 0,
                    },
                )
                self.assertEqual((runner.WORK_DIR, runner.WORK_MOUNT), ("/srv/ext/work/x", "/srv/ext"))
                self.assertEqual(runner.WORK_RETENTION_HOURS, 1)
                self.assertEqual(load_runner(spec.template, **{f"{spec.prefix}_work_retention_hours": 6}).WORK_RETENTION_HOURS, 6)

    def test_legacy_temp_dir_variables_are_ignored(self):
        for spec in RUNNERS:
            with self.subTest(template=spec.template):
                legacy = {name: f"/tmp/{spec.service}" for name in ("echoport_backup_temp_dir", *spec.legacy)}
                source = render(spec.template, **legacy)
                self.assertNotIn(f"\"/tmp/{spec.service}", source)
                # (_REMOTE_TEMP_DIR_RE in the podcast runner is a remote path pattern.)
                self.assertNotRegex(source, r"(?<![A-Z_])TEMP_DIR(?![A-Z_])")
                for marker in ("get_temp_parent_dir", "dir=None", "dir=parent"):
                    self.assertNotIn(marker, source)
                self.assertEqual(load_runner(spec.template, **legacy).WORK_DIR, f"/mnt/cryptdata/backups/tmp/{spec.service}")

    def test_runners_use_the_include_and_create_nothing_before_main(self):
        for spec in RUNNERS:
            with self.subTest(template=spec.template):
                source = (TEMPLATES / spec.template).read_text()
                self.assertEqual(source.count("{% include '_work_dir.py.j2' %}"), 1)
                self.assertNotIn("mkdtemp", source)
                main_block = source.split('if __name__ == "__main__":', 1)[1]
                self.assertNotIn("mkdir", main_block)

    def test_rendered_runners_compile_on_python_3_12_syntax(self):
        # macmini runs Python 3.12; compile() here checks the syntax of the
        # interpreter running the tests, the include adds no newer syntax.
        for spec in RUNNERS:
            with self.subTest(template=spec.template):
                compile(render(spec.template), spec.template, "exec")


class RunnerWorkDirTest(unittest.TestCase):
    """Behaviour of each runner's backup and restore entry points."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(os.path.realpath(self._tmp.name))
        cwd = os.getcwd()
        os.chdir(self.base)
        self.addCleanup(os.chdir, cwd)
        self.mount = self.base / "mnt/cryptdata"
        self.mount.mkdir(parents=True)

    def runner(self, spec: Runner, mounted: bool = True):
        runner = load_runner(spec.template, **spec.variables)
        work = self.mount / "backups/tmp" / spec.service
        runner.WORK_MOUNT = str(self.mount)
        runner.WORK_DIR = str(work)
        runner.WORK_OWNER_UID = os.geteuid()
        runner.os = FakeOs({str(self.mount)} if mounted else set())
        events: list[dict] = []
        runner._emit = events.append
        commands: list = []

        def record(args, *a, **kw):
            commands.append(args)
            raise subprocess.CalledProcessError(1, args, "", "refused by test")

        runner.subprocess = types.SimpleNamespace(
            run=record,
            Popen=record,
            check_output=record,
            check_call=record,
            CalledProcessError=subprocess.CalledProcessError,
            CompletedProcess=subprocess.CompletedProcess,
            TimeoutExpired=subprocess.TimeoutExpired,
            PIPE=subprocess.PIPE,
            DEVNULL=subprocess.DEVNULL,
            STDOUT=subprocess.STDOUT,
        )
        for name in PRECHECKS:
            if hasattr(runner, name):
                setattr(runner, name, lambda *a, _name=name, **kw: _name == "mc_alias_configured" or {})
        return runner, work, events, commands

    def call(self, runner, entry: str, env: dict):
        """Run an entry point; return (rc or exception, stdout)."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                if isinstance(entry, tuple):
                    return getattr(runner, entry[0])(**entry[1]), out.getvalue()
                if entry.startswith("main_"):
                    return getattr(runner, entry)(None, {"env": dict(env)}, dict(env)), out.getvalue()
                return getattr(runner, entry)(dict(env)), out.getvalue()
            except Exception as exc:  # noqa: BLE001 - the runner's __main__ reports it
                return exc, out.getvalue()

    def assert_failed(self, result, events: list, text: str) -> None:
        if isinstance(result, Exception):
            self.assertIn(text, str(result))
        else:
            self.assertEqual(result, 1)
            self.assertTrue(any(text in str(e.get("message", "")) or text in str(e.get("error", "")) for e in events), events)

    def test_backup_and_restore_refuse_before_any_work_when_unmounted(self):
        for spec in RUNNERS:
            for entry, env in ((spec.backup, BACKUP_ENV), (spec.restore, RESTORE_ENV)):
                with self.subTest(template=spec.template, entry=str(entry)[:40]):
                    runner, work, events, commands = self.runner(spec, mounted=False)
                    with mock.patch.object(tempfile, "mkdtemp") as mkdtemp:
                        result, _ = self.call(runner, entry, env)
                    mkdtemp.assert_not_called()
                    self.assertEqual(commands, [])
                    self.assert_failed(result, events, "not mounted")
                    if not isinstance(result, Exception):
                        # Reported as a failed step, not only a return code.
                        self.assertTrue(any(e.get("state") == "failure" and "not mounted" in e.get("message", "")
                                            for e in events), events)
                    self.assertFalse((self.mount / "backups").exists())

    def test_symlinked_work_dir_is_refused_without_fallback(self):
        for spec in RUNNERS:
            with self.subTest(template=spec.template):
                runner, work, events, commands = self.runner(spec)
                elsewhere = self.base / f"elsewhere-{spec.service}"
                elsewhere.mkdir()
                work.parent.mkdir(parents=True, exist_ok=True)
                work.symlink_to(elsewhere)
                with mock.patch.object(tempfile, "mkdtemp") as mkdtemp:
                    result, _ = self.call(runner, spec.backup, BACKUP_ENV)
                mkdtemp.assert_not_called()
                self.assertEqual(commands, [])
                self.assert_failed(result, events, "not a plain directory")
                self.assertEqual(list(elsewhere.iterdir()), [])

    def test_failing_runs_remove_their_run_dir_in_the_work_dir(self):
        for spec in RUNNERS:
            for entry, env in ((spec.backup, BACKUP_ENV), (spec.restore, RESTORE_ENV)):
                with self.subTest(template=spec.template, entry=str(entry)[:40]):
                    runner, work, events, commands = self.runner(spec)
                    with mock.patch.object(tempfile, "mkdtemp", wraps=tempfile.mkdtemp) as mkdtemp:
                        result, _ = self.call(runner, entry, env)
                    self.assertNotEqual(result, 0)
                    self.assertEqual(mkdtemp.call_count, 1)
                    kwargs = mkdtemp.call_args.kwargs
                    self.assertEqual(kwargs["dir"], str(work))
                    self.assertTrue(kwargs["prefix"].startswith(spec.run_dir_prefixes), kwargs["prefix"])
                    self.assertEqual(sorted(p.name for p in work.iterdir()), [])
                    self.assertEqual(sorted(p.name for p in self.base.iterdir()), ["mnt"] + sorted(
                        p.name for p in self.base.iterdir() if p.name.startswith("elsewhere-")
                    ))


class PaperlessDatabaseRestoreTest(unittest.TestCase):
    """psql (as postgres) reads the dump on stdin, never from a path.

    postgres cannot traverse the root-only run dir on the work mount, so the
    old staging copy in TEMP_DIR/restore-db (outside the run dir, chmod 0644)
    and ``psql --file <path>`` are gone.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.run_dir = Path(self._tmp.name) / "paperless-restore-x"
        self.run_dir.mkdir(mode=0o700)
        self.dump = self.run_dir / "paperless.sql"
        self.dump.write_text("CREATE TABLE t (id int);\n")
        self.runner = load_runner(
            "paperless_backup.py.j2",
            paperless_echoport_backup_db_name="paperless",
            paperless_echoport_backup_db_owner="paperless",
            paperless_echoport_backup_postgres_become_user="postgres",
        )
        self.calls: list[tuple[list, bytes | None]] = []

        def run(args, stdin=None, **kwargs):
            self.calls.append((list(args), stdin.read() if stdin is not None else None))
            return subprocess.CompletedProcess(args, 0, "", "")

        self.runner.subprocess = types.SimpleNamespace(
            run=run, CalledProcessError=subprocess.CalledProcessError, PIPE=subprocess.PIPE
        )
        self.runner.build_postgres_command = lambda args: ["runuser", "-u", "postgres", "--", *args]

    def test_psql_reads_the_dump_on_stdin(self):
        self.runner.restore_database_from_dump(self.dump)
        commands = [args[4] for args, _ in self.calls]
        self.assertEqual(commands, ["dropdb", "createdb", "psql"])
        psql_args, stdin = self.calls[-1]
        self.assertEqual(psql_args[-2:], ["--file", "-"])
        self.assertEqual(stdin, b"CREATE TABLE t (id int);\n")
        for args, _ in self.calls:
            self.assertFalse(any(str(self.run_dir) in a for a in args), args)
        # Nothing staged next to (or outside) the run dir, no mode change.
        self.assertEqual(sorted(p.name for p in Path(self._tmp.name).iterdir()), ["paperless-restore-x"])
        self.assertEqual(sorted(p.name for p in self.run_dir.iterdir()), ["paperless.sql"])

    def test_unreadable_dump_fails_before_the_database_is_dropped(self):
        self.dump.chmod(0o000)
        self.addCleanup(self.dump.chmod, 0o600)
        if os.access(self.dump, os.R_OK):
            self.skipTest("running as a user that can read mode 000 files")
        with self.assertRaises(PermissionError):
            self.runner.restore_database_from_dump(self.dump)
        self.assertEqual(self.calls, [])

    def test_failed_psql_is_reported(self):
        def run(args, stdin=None, **kwargs):
            rc = 3 if args[4] == "psql" else 0
            return subprocess.CompletedProcess(args, rc, "", "ERROR: boom")

        self.runner.subprocess.run = run
        with self.assertRaisesRegex(RuntimeError, "psql restore failed: ERROR: boom"):
            self.runner.restore_database_from_dump(self.dump)

    def test_template_has_no_staging_dir(self):
        source = (TEMPLATES / "paperless_backup.py.j2").read_text()
        self.assertNotIn("restore-db", source)
        self.assertNotIn("staged_dump", source)


class StagingDumpModeTest(unittest.TestCase):
    """Runners whose restore scp's the dump to staging, where pg_restore reads it as postgres.

    Classic scp keeps the local mode, so the dump is chmodded 0644 right
    before the upload (it stays private locally inside the 0700 run dir).
    """

    TEMPLATES = (
        ("python_podcast_production_db_backup.py.j2", "pp/t", "pp-restore-"),
        ("python_podcast_staging_backup.py.j2", "pp/t", "pp-restore-"),
        ("homepage_staging_backup.py.j2", "homepage/t", "homepage-restore-"),
    )

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(os.path.realpath(self._tmp.name))
        self.mount = self.base / "mnt/cryptdata"
        self.mount.mkdir(parents=True)
        self.store = self.base / "store"
        self.store.mkdir()

    def runner(self, template: str):
        # pp_prod_db: no private media archive (its own tests cover it).
        runner = load_runner(template, pp_prod_db_backup_private_media_path="")
        self.work = self.mount / "backups/tmp" / template.replace("_backup.py.j2", "")
        runner.WORK_MOUNT = str(self.mount)
        runner.WORK_DIR = str(self.work)
        runner.os = FakeOs({str(self.mount)})
        runner._emit = lambda event: None
        self.sent: list[tuple[str, int]] = []

        def ssh(host, user, cmd, check=True):
            return subprocess.CompletedProcess(cmd, 0, "loaded\n" if cmd.startswith("systemctl show") else "", "")

        def scp_from_remote(host, user, remote, local):
            Path(local).write_bytes(b"PGDMP fake dump")

        def scp_to_remote(host, user, local, remote):
            self.sent.append((local, stat.S_IMODE(os.stat(local).st_mode)))

        def run(args, **kwargs):
            if args[0] != MC:
                return subprocess.CompletedProcess(args, 0, "", "")
            if args[1] == "cp" and args[2].startswith("minio/"):
                Path(args[3]).write_bytes((self.store / "archive").read_bytes())
            elif args[1] == "cp":
                (self.store / "archive").write_bytes(Path(args[2]).read_bytes())
            elif args[1] == "stat":
                return subprocess.CompletedProcess(args, 0, json.dumps({"size": (self.store / "archive").stat().st_size}), "")
            return subprocess.CompletedProcess(args, 0, "", "")

        runner.ssh, runner.scp_from_remote, runner.scp_to_remote = ssh, scp_from_remote, scp_to_remote
        runner.resolve_restore_units = lambda host, user: ["svc.service"]
        runner.subprocess = types.SimpleNamespace(
            run=run, CalledProcessError=subprocess.CalledProcessError, CompletedProcess=subprocess.CompletedProcess,
            PIPE=subprocess.PIPE, DEVNULL=subprocess.DEVNULL,
        )
        return runner

    def test_dump_is_world_readable_only_for_the_upload(self):
        for template, key, prefix in self.TEMPLATES:
            with self.subTest(template=template):
                old = os.umask(0o077)  # archives made under umask 077 carry a 0600 dump
                try:
                    runner = self.runner(template)
                    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                        self.assertEqual(runner.backup(bucket="backups", key_prefix=key, timestamp="t"), 0)
                        checksum = hashlib.sha256((self.store / "archive").read_bytes()).hexdigest()
                        with mock.patch.object(tempfile, "mkdtemp", wraps=tempfile.mkdtemp) as mkdtemp:
                            rc = runner.restore(bucket="backups", key=f"{key}.tar.gz", expected_checksum=checksum)
                finally:
                    os.umask(old)
                self.assertEqual(rc, 0)
                self.assertEqual(mkdtemp.call_args.kwargs, {"prefix": prefix, "dir": str(self.work)})
                [(local, mode)] = self.sent
                self.assertTrue(local.startswith(str(self.work) + os.sep), local)
                self.assertEqual(mode, 0o644)
                self.assertEqual(list(self.work.iterdir()), [])


class PodcastMediaCredentialsTest(unittest.TestCase):
    """The rclone config (S3 and MinIO credentials) is created 0600 in the run dir."""

    def test_rclone_config_is_created_private_whatever_the_umask(self):
        runner = load_runner("python_podcast_media_backup.py.j2")
        with tempfile.TemporaryDirectory() as tmp:
            old = os.umask(0o022)
            try:
                config = Path(tmp) / "rclone.conf"
                runner.write_rclone_config(config, dict.fromkeys(
                    ("source_access_key", "source_secret_key", "dest_access_key", "dest_secret_key"), "x"))
            finally:
                os.umask(old)
            self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)
            self.assertIn("secret_access_key = x", config.read_text())
            with self.assertRaises(FileExistsError):  # O_EXCL: never reuses an existing file
                runner.write_rclone_config(config, dict.fromkeys(
                    ("source_access_key", "source_secret_key", "dest_access_key", "dest_secret_key"), "y"))

    def test_main_sets_a_private_umask(self):
        runner = load_runner("python_podcast_media_backup.py.j2")
        runner._emit = lambda event: None
        runner.read_config_file = lambda: None
        runner.load_credentials = lambda: (_ for _ in ()).throw(RuntimeError("stop here"))
        old = os.umask(0o022)
        try:
            with mock.patch.dict(os.environ, {"CONTEXT": "{}"}), contextlib.redirect_stderr(io.StringIO()):
                with contextlib.suppress(Exception):
                    runner.main()
            self.assertEqual(os.umask(0o022), 0o077)
        finally:
            os.umask(old)


if __name__ == "__main__":
    unittest.main()
