"""Every migrated Echoport runner works only on the external encrypted disk.

The runners below keep their per-run dirs (dumps, staging copies, archives,
rclone configs) below ``<prefix>_work_dir`` on ``<prefix>_work_mount``
(macmini: ``/mnt/cryptdata``) through the shared ``_work_dir.py.j2`` include.
For each runner this module checks:

- the rendered defaults and overrides, and that the old temp dir variables
  (``echoport_backup_temp_dir``, ``*_temp_dir``) are ignored;
- a missing mount refuses backup and restore before any command runs and
  before ``mkdtemp`` (no fallback to ``/tmp`` or the system temp dir);
- a symlinked work dir is refused without writing to its target;
- a failing backup or restore removes its run dir, and restore creates its
  run dir in ``WORK_DIR``.

The include itself (device checks, owner, retention) is covered in depth by
``test_unifi_echoport_backup_workdir`` and ``test_homepage_echoport_backup_workdir``.
"""

import contextlib
import io
import os
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
BASE_VARS = {
    "echoport_backup_mc_install_path": "/usr/local/bin/mc",
    "echoport_backup_minio_alias": "minio",
    "echoport_backup_default_bucket": "backups",
    "echoport_backup_minio_prefix_aliases": {},
    "echoport_backup_allowed_roots": ["/var/lib/"],
}
# Called before the run dir exists; stubbed so the work dir check is reached.
PRECHECKS = (
    "validate_config_paths",
    "ensure_binaries",
    "detect_php_service",
    "read_db_credentials",
    "require_commands",
    "validate_ssh_identifiers",
    "validate_identifiers",
)


@dataclass(frozen=True)
class Runner:
    template: str
    prefix: str  # <prefix>_work_dir, <prefix>_work_mount, <prefix>_work_retention_hours
    service: str
    root: bool
    backup: str  # entry point name, called with (cenv) or via call_backup
    restore: str
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
                for marker in ("TEMP_DIR", "get_temp_parent_dir", "dir=None", "dir=parent"):
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
                setattr(runner, name, lambda *a, **kw: {})
        return runner, work, events, commands

    def call(self, runner, entry: str, env: dict):
        """Run an entry point; return (rc or exception, stdout)."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
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
                with self.subTest(template=spec.template, entry=entry):
                    runner, work, events, commands = self.runner(spec, mounted=False)
                    with mock.patch.object(tempfile, "mkdtemp") as mkdtemp:
                        result, _ = self.call(runner, entry, env)
                    mkdtemp.assert_not_called()
                    self.assertEqual(commands, [])
                    self.assert_failed(result, events, "not mounted")
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
                with self.subTest(template=spec.template, entry=entry):
                    runner, work, events, commands = self.runner(spec)
                    with mock.patch.object(tempfile, "mkdtemp", wraps=tempfile.mkdtemp) as mkdtemp:
                        result, _ = self.call(runner, entry, env)
                    self.assertNotEqual(result, 0)
                    self.assertEqual(mkdtemp.call_count, 1)
                    kwargs = mkdtemp.call_args.kwargs
                    self.assertEqual(kwargs["dir"], str(work))
                    self.assertIn(kwargs["prefix"], spec.run_dir_prefixes)
                    self.assertEqual(sorted(p.name for p in work.iterdir()), [])
                    self.assertEqual(sorted(p.name for p in self.base.iterdir()), ["mnt"] + sorted(
                        p.name for p in self.base.iterdir() if p.name.startswith("elsewhere-")
                    ))


if __name__ == "__main__":
    unittest.main()
