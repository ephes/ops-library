"""The Echoport homepage runners work only on the external encrypted disk.

``homepage_production_db_backup.py.j2`` (production pg_dump, nightly staging
restore) and ``homepage_media_backup.py.j2`` (S3 <-> MinIO via rclone) keep
their per-run dirs below ``*_work_dir`` on ``*_work_mount`` (macmini:
``/mnt/cryptdata``) through the shared ``_work_dir.py.j2`` include. A missing
or wrong mount fails the run before any work; there is no fallback to ``/tmp``
or ``/``. Both runners run as the deploy user, so the work dir must belong to
the runner's effective uid. Leftover run dirs are pruned after the retention
window.
"""

import hashlib
import json
import os
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import types
import unittest
import warnings
from pathlib import Path
from unittest import mock

from ansible.plugins.filter.core import FilterModule
from jinja2 import ChainableUndefined, Environment, FileSystemLoader

from tests.test_unifi_echoport_backup_workdir import FakeOs

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "roles/echoport_backup/templates"
DB = "homepage_production_db_backup.py.j2"
MEDIA = "homepage_media_backup.py.j2"
BASE_VARS = {
    "echoport_backup_mc_install_path": "/usr/local/bin/mc",
    "echoport_backup_minio_alias": "minio",
    "echoport_backup_default_bucket": "backups",
}


def render(template: str, **variables) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES), undefined=ChainableUndefined)
    ansible_filters = FilterModule().filters()
    for name in ("to_json", "regex_replace"):
        env.filters[name] = ansible_filters[name]
    return env.get_template(template).render(**{**BASE_VARS, **variables})


def load_runner(template: str, **variables) -> types.ModuleType:
    module = types.ModuleType(template.replace(".py.j2", "_workdir_test"))
    module.__file__ = str(TEMPLATES / template)
    with warnings.catch_warnings():
        # The DB runner's pre-existing `return` in `finally` (Python 3.14).
        warnings.simplefilter("ignore", SyntaxWarning)
        exec(compile(render(template, **variables), module.__file__, "exec"), module.__dict__)
    return module


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RenderedDefaultsTest(unittest.TestCase):
    CASES = {
        DB: ("homepage_prod_db_backup", "homepage-production-db-backup", {"echoport_backup_temp_dir": "/tmp/homepage-production-db-backup"}),
        MEDIA: ("homepage_media_backup", "homepage-media-backup", {"homepage_media_backup_temp_dir": "/tmp/homepage-media-backup"}),
    }

    def test_defaults_point_at_the_external_disk(self):
        for template, (_, name, _legacy) in self.CASES.items():
            with self.subTest(template=template):
                runner = load_runner(template)
                self.assertEqual(runner.WORK_DIR, f"/mnt/cryptdata/backups/tmp/{name}")
                self.assertEqual(runner.WORK_MOUNT, "/mnt/cryptdata")
                self.assertEqual(runner.WORK_RETENTION_HOURS, 24)
                self.assertEqual(runner.WORK_OWNER_UID, os.geteuid())

    def test_legacy_temp_dir_is_ignored(self):
        for template, (_, name, legacy) in self.CASES.items():
            with self.subTest(template=template):
                source = render(template, **legacy)
                self.assertNotIn(f'"/tmp/{name}"', source)
                self.assertNotIn("TEMP_DIR", source)
                self.assertNotIn("dir=None", source)
                self.assertEqual(load_runner(template, **legacy).WORK_DIR, f"/mnt/cryptdata/backups/tmp/{name}")

    def test_variables_override_defaults(self):
        for template, (prefix, _, _legacy) in self.CASES.items():
            with self.subTest(template=template):
                runner = load_runner(
                    template,
                    **{
                        f"{prefix}_work_dir": "/srv/ext/work/x",
                        f"{prefix}_work_mount": "/srv/ext",
                        f"{prefix}_work_retention_hours": 0,
                    },
                )
                self.assertEqual((runner.WORK_DIR, runner.WORK_MOUNT), ("/srv/ext/work/x", "/srv/ext"))
                self.assertEqual(runner.WORK_RETENTION_HOURS, 1)

    def test_runners_share_the_work_dir_include(self):
        for template in (DB, MEDIA, "unifi_backup.py.j2"):
            with self.subTest(template=template):
                self.assertIn("{% include '_work_dir.py.j2' %}", (TEMPLATES / template).read_text())

    def test_nothing_is_created_before_main(self):
        for template in (DB, MEDIA):
            with self.subTest(template=template):
                source = (TEMPLATES / template).read_text()
                main_block = source.split('if __name__ == "__main__":', 1)[1]
                self.assertNotIn("mkdir", main_block)

    def test_db_restore_keeps_the_public_schema_owner_step(self):
        source = (TEMPLATES / DB).read_text()
        self.assertIn("public_schema_owner_sql(DB_USER)", source)
        self.assertIn('ALTER SCHEMA public OWNER TO "{role}"', source)


class RunnerTestCase(unittest.TestCase):
    template = DB
    name = "homepage-production-db-backup"

    def setUp(self) -> None:
        self._umask = os.umask(0o022)
        self.addCleanup(os.umask, self._umask)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(os.path.realpath(self._tmp.name))
        self.mount = base / "mnt/cryptdata"
        self.mount.mkdir(parents=True)
        self.work = self.mount / "backups/tmp" / self.name
        self.store = base / "store"
        self.store.mkdir()
        self.runner = load_runner(self.template)
        self.runner.WORK_MOUNT = str(self.mount)
        self.runner.WORK_DIR = str(self.work)
        self.events: list[dict] = []
        self.runner._emit = self.events.append
        self.mounted()

    def mounted(self, **kwargs) -> None:
        self.runner.os = FakeOs({str(self.mount)}, **kwargs)

    def unmounted(self) -> None:
        self.runner.os = FakeOs(set())

    def run_dirs(self) -> list[str]:
        return sorted(p.name for p in self.work.iterdir()) if self.work.exists() else []

    def step(self, name: str, state: str) -> list[dict]:
        return [e for e in self.events if e.get("name") == name and e.get("state") == state]

    def refused_before_any_work(self, calls: list) -> None:
        self.assertEqual(calls, [])
        failures = self.step("init", "failure")
        self.assertEqual(len(failures), 1)
        self.assertIn("Work directory check failed", failures[0]["message"])
        self.assertEqual(self.events[-1], {"event": "finish", "status": "failure", "message": mock.ANY})


class ProductionDbRunnerTest(RunnerTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.remote: list[str] = []
        self.local: list[list[str]] = []
        self.sent: list[tuple[str, int]] = []
        self.fail_pg_dump = False
        self.runner.ssh = self.ssh
        self.runner.scp_from_remote = self.scp_from_remote
        self.runner.scp_to_remote = self.scp_to_remote
        self.runner.subprocess = types.SimpleNamespace(
            run=self.fake_run, CalledProcessError=subprocess.CalledProcessError, CompletedProcess=subprocess.CompletedProcess
        )

    def ssh(self, host, user, cmd, check=True):
        self.remote.append(cmd)
        if self.fail_pg_dump and "pg_dump" in cmd:
            raise subprocess.CalledProcessError(1, cmd, "", "boom")
        stdout = "loaded\n" if cmd.startswith("systemctl show") else ""
        return subprocess.CompletedProcess(cmd, 0, stdout, "")

    def scp_from_remote(self, host, user, remote, local):
        self.remote.append(f"scp -f {remote}")
        Path(local).write_bytes(b"PGDMP fake dump")

    def scp_to_remote(self, host, user, local, remote):
        self.remote.append(f"scp -t {remote}")
        self.sent.append((local, stat.S_IMODE(os.stat(local).st_mode)))

    def fake_run(self, args, **kwargs):
        self.local.append(list(args))
        if args[0] == "pg_restore":
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[1] == "cp" and args[2].startswith("minio/"):
            stored = self.store / args[2].replace("/", "_")
            Path(args[3]).write_bytes(stored.read_bytes())
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[1] == "cp":
            self.archive_mode = stat.S_IMODE(os.stat(args[2]).st_mode)
            with tarfile.open(args[2]) as tar:
                self.member_modes = {m.name: m.mode for m in tar.getmembers()}
            (self.store / args[3].replace("/", "_")).write_bytes(Path(args[2]).read_bytes())
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 0, "", "")  # mc stat

    def backup(self) -> int:
        return self.runner.backup(bucket="backups", key_prefix="homepage-production-db/t", timestamp="2026-10-23T02-00-00")

    def test_backup_refuses_before_any_work_when_unmounted(self):
        self.unmounted()
        with mock.patch.object(self.runner.tempfile, "mkdtemp") as mkdtemp:
            self.assertEqual(self.backup(), 1)
        mkdtemp.assert_not_called()
        self.refused_before_any_work(self.remote + self.local)
        self.assertFalse(self.work.exists())

    def test_backup_refuses_mount_on_the_root_device(self):
        root_device = os.lstat(self.mount).st_dev
        self.mounted(root_device=root_device)
        self.assertEqual(self.backup(), 1)
        self.refused_before_any_work(self.remote + self.local)
        self.assertIn("root filesystem device", self.step("init", "failure")[0]["message"])

    def test_backup_refuses_component_on_another_device(self):
        (self.mount / "backups").mkdir()
        self.mounted(devices={str(self.mount / "backups"): os.lstat(self.mount).st_dev + 1})
        self.assertEqual(self.backup(), 1)
        self.refused_before_any_work(self.remote + self.local)
        self.assertFalse((self.mount / "backups/tmp").exists())

    def test_backup_refuses_foreign_owned_work_dir(self):
        self.runner.WORK_OWNER_UID = os.geteuid() + 1
        self.assertEqual(self.backup(), 1)
        self.refused_before_any_work(self.remote + self.local)
        self.assertIn("not owned by the runner user", self.step("init", "failure")[0]["message"])

    def test_backup_refuses_symlinked_work_dir_without_fallback(self):
        elsewhere = Path(self._tmp.name) / "elsewhere"
        elsewhere.mkdir()
        (self.mount / "backups/tmp").mkdir(parents=True)
        self.work.symlink_to(elsewhere)
        self.assertEqual(self.backup(), 1)
        self.refused_before_any_work(self.remote + self.local)
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_backup_success_is_private_and_cleans_up(self):
        self.assertEqual(self.backup(), 0)
        self.assertEqual(self.archive_mode, 0o600)
        self.assertEqual(self.member_modes["database/homepage.dump"] & 0o777, 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.work).st_mode), 0o700)
        self.assertEqual(self.run_dirs(), [])
        self.assertTrue(any(c.startswith("rm -f /tmp/echoport_homepage_dump_") for c in self.remote))
        self.assertEqual(self.events[-1]["status"], "success")

    def test_backup_removes_run_dir_on_failure(self):
        self.fail_pg_dump = True
        self.assertEqual(self.backup(), 1)
        self.assertEqual(self.run_dirs(), [])
        self.assertEqual(self.work.parent.stat().st_dev, self.mount.stat().st_dev)

    def test_restore_uses_the_work_dir_and_cleans_up(self):
        self.assertEqual(self.backup(), 0)
        archive = self.store / "minio_backups_homepage-production-db_t.tar.gz"
        self.events.clear()
        self.remote.clear()
        with mock.patch.object(self.runner.tempfile, "mkdtemp", wraps=tempfile.mkdtemp) as mkdtemp:
            rc = self.runner.restore(bucket="backups", key="homepage-production-db/t.tar.gz", expected_checksum=sha256(archive))
        self.assertEqual(rc, 0)
        self.assertEqual(mkdtemp.call_args.kwargs, {"prefix": "homepage-restore-", "dir": str(self.work)})
        [(local, mode)] = self.sent
        self.assertTrue(local.startswith(str(self.work) + os.sep), local)
        # pg_restore reads the scp'd file as postgres on staging.
        self.assertEqual(mode, 0o644)
        self.assertEqual(self.run_dirs(), [])
        commands = self.remote
        alter = next(i for i, c in enumerate(commands) if "ALTER SCHEMA public OWNER" in c)
        pg_restore = next(i for i, c in enumerate(commands) if "pg_restore" in c)
        self.assertLess(alter, pg_restore)

    def test_restore_refuses_before_download_when_unmounted(self):
        self.unmounted()
        rc = self.runner.restore(bucket="backups", key="homepage-production-db/t.tar.gz", expected_checksum="0" * 64)
        self.assertEqual(rc, 1)
        self.refused_before_any_work(self.remote + self.local)

    def test_restore_removes_run_dir_on_checksum_mismatch(self):
        self.assertEqual(self.backup(), 0)
        rc = self.runner.restore(bucket="backups", key="homepage-production-db/t.tar.gz", expected_checksum="0" * 64)
        self.assertEqual(rc, 1)
        self.assertEqual(self.run_dirs(), [])
        self.assertFalse(any("dropdb" in c for c in self.remote))


class MediaRunnerTest(RunnerTestCase):
    template = MEDIA
    name = "homepage-media-backup"
    CREDENTIALS = {"source_access_key": "a", "source_secret_key": "b", "dest_access_key": "c", "dest_secret_key": "d"}

    def setUp(self) -> None:
        super().setUp()
        self.runner.RCLONE_PATH = sys.executable
        self.commands: list[list[str]] = []
        self.config_modes: list[int] = []
        self.fail_copy = False
        self.runner.run_cmd = self.run_cmd

    def run_cmd(self, args, check=True):
        self.commands.append(list(args))
        config = Path(args[args.index("--config") + 1])
        self.assertTrue(str(config).startswith(str(self.work) + os.sep))
        self.config_modes.append(stat.S_IMODE(config.stat().st_mode))
        if args[1] == "copy" and self.fail_copy:
            raise subprocess.CalledProcessError(1, args, "", "boom")
        if args[1] == "size":
            return subprocess.CompletedProcess(args, 0, json.dumps({"bytes": 10, "count": 2}), "")
        if args[1] == "copyto" and args[2].startswith("dst:"):
            Path(args[3]).write_text(self.manifest)
        if args[1] == "copyto" and not args[2].startswith("dst:"):
            self.manifest_mode = stat.S_IMODE(os.stat(args[2]).st_mode)
            self.manifest = Path(args[2]).read_text()
        return subprocess.CompletedProcess(args, 0, "", "")

    def backup(self) -> int:
        return self.runner.backup(bucket="backups", key_prefix="homepage-media/t", objects_prefix="homepage-media/current", credentials=self.CREDENTIALS)

    def test_backup_refuses_before_any_work_when_unmounted(self):
        self.unmounted()
        with mock.patch.object(self.runner, "write_rclone_config") as write_config:
            self.assertEqual(self.backup(), 1)
        write_config.assert_not_called()
        self.refused_before_any_work(self.commands)
        self.assertFalse(self.work.exists())

    def test_backup_success_is_private_and_cleans_up(self):
        os.umask(0o077)  # main() sets it before dispatching
        self.assertEqual(self.backup(), 0)
        self.assertEqual(set(self.config_modes), {0o600})
        self.assertEqual(self.manifest_mode, 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.work).st_mode), 0o700)
        self.assertEqual(self.run_dirs(), [])

    def test_backup_removes_run_dir_on_failure(self):
        self.fail_copy = True
        self.assertEqual(self.backup(), 1)
        self.assertEqual(self.run_dirs(), [])

    def test_restore_uses_the_work_dir_and_cleans_up(self):
        self.assertEqual(self.backup(), 0)
        checksum = hashlib.sha256(self.manifest.encode()).hexdigest()
        self.commands.clear()
        rc = self.runner.restore(bucket="backups", key_prefix="homepage-media/t", expected_checksum=checksum, credentials=self.CREDENTIALS)
        self.assertEqual(rc, 0)
        self.assertIn("restore_media", [e.get("name") for e in self.events])
        self.assertEqual(self.run_dirs(), [])

    def test_restore_refuses_before_download_when_unmounted(self):
        self.unmounted()
        rc = self.runner.restore(bucket="backups", key_prefix="homepage-media/t", expected_checksum="0" * 64, credentials=self.CREDENTIALS)
        self.assertEqual(rc, 1)
        self.refused_before_any_work(self.commands)

    def test_main_sets_a_private_umask(self):
        self.runner.load_credentials = lambda: self.CREDENTIALS
        self.unmounted()
        with mock.patch.dict(os.environ, {"CONTEXT": "{}"}), mock.patch.object(self.runner, "read_config_file", return_value=None):
            with mock.patch("sys.stderr"):
                self.assertEqual(self.runner.main(), 1)
        self.assertEqual(os.umask(0o022), 0o077)


class RetentionTest(RunnerTestCase):
    def test_prunes_only_stale_run_dirs_of_each_runner(self):
        for template, name, prefixes in (
            (DB, "homepage-production-db-backup", ("homepage-backup-x", "homepage-restore-x")),
            (MEDIA, "homepage-media-backup", ("homepage-media-x", "homepage-media-restore-x")),
        ):
            with self.subTest(template=template):
                runner = load_runner(template)
                runner._emit = self.events.append
                runner.WORK_MOUNT = str(self.mount)
                runner.WORK_DIR = str(self.mount / "backups/tmp" / name)
                runner.os = FakeOs({str(self.mount)})
                device = runner.prepare_work_dir()
                work = Path(runner.WORK_DIR)
                old = time.time() - 25 * 3600
                for entry in (*prefixes, "other-x"):
                    (work / entry).mkdir()
                    os.utime(work / entry, (old, old))
                (work / f"{prefixes[0]}-fresh").mkdir()
                removed, failed = runner.prune_stale_run_dirs(device)
                self.assertEqual(sorted(removed), sorted(prefixes))
                self.assertEqual(failed, [])
                self.assertEqual(sorted(p.name for p in work.iterdir()), sorted(["other-x", f"{prefixes[0]}-fresh"]))

    def test_create_run_dir_prunes_before_creating(self):
        self.runner.prepare_work_dir()
        stale = self.work / "homepage-backup-stale"
        stale.mkdir()
        old = time.time() - 25 * 3600
        os.utime(stale, (old, old))
        run_dir = self.runner.create_run_dir("homepage-backup-")
        self.assertFalse(stale.exists())
        self.assertEqual(stat.S_IMODE(run_dir.stat().st_mode), 0o700)
        self.assertEqual(run_dir.parent, self.work)
        self.assertTrue(any("stale work dir" in e.get("message", "") for e in self.events))


if __name__ == "__main__":
    unittest.main()
