"""The Echoport UniFi runner works only on the external encrypted disk.

The runner's per-run temp dirs (MongoDB dumps, staging copies, archives) live
below ``unifi_echoport_backup_work_dir`` on ``unifi_echoport_backup_work_mount``
(macmini: ``/mnt/cryptdata``). A missing or wrong mount fails the run before any
work; there is no fallback to ``/tmp`` or ``/``. Leftover run dirs are pruned
after ``unifi_echoport_backup_work_retention_hours`` without following
symlinks.
"""

import os
import stat
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from jinja2 import ChainableUndefined, Environment

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "roles/echoport_backup/templates/unifi_backup.py.j2"


def render(**variables) -> str:
    return Environment(undefined=ChainableUndefined).from_string(TEMPLATE.read_text()).render(**variables)


def load_runner(**variables) -> types.ModuleType:
    module = types.ModuleType("unifi_backup_workdir_test")
    module.__file__ = str(TEMPLATE)
    exec(compile(render(**variables), module.__file__, "exec"), module.__dict__)
    return module


class FakeOs:
    """Delegates to os; reports `/` on the mount's device and the mount as mounted."""

    def __init__(self, mounted: set[str], root_device: int | None = None, devices: dict | None = None):
        self._mounted = mounted
        self._root_device = root_device
        self._devices = devices or {}
        outer = self

        class FakePath:
            def __getattr__(self, name):
                return getattr(os.path, name)

            @staticmethod
            def ismount(path):
                return path in outer._mounted

        self.path = FakePath()

    def __getattr__(self, name):
        return getattr(os, name)

    def lstat(self, path, *args, **kwargs):
        info = os.lstat(path, *args, **kwargs)
        path = str(path)
        device = self._devices.get(path)
        if path == os.sep:
            device = self._root_device if self._root_device is not None else info.st_dev ^ 0xFFFF
        if device is None:
            return info
        fields = list(info)
        fields[stat.ST_DEV] = device
        return os.stat_result(fields)


class WorkDirTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(os.path.realpath(self._tmp.name))
        self.mount = base / "mnt/cryptdata"
        self.mount.mkdir(parents=True)
        self.work = self.mount / "backups/tmp/unifi-backup"
        self.runner = load_runner()
        self.runner.WORK_MOUNT = str(self.mount)
        self.runner.WORK_DIR = str(self.work)
        self.runner.WORK_OWNER_UID = os.getuid()
        self.events: list[dict] = []
        self.runner._emit = self.events.append
        self.commands: list[list[str]] = []
        self.runner.run_cmd = lambda args, check=True: self.commands.append(args)
        self.mounted()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def mounted(self, **kwargs) -> None:
        self.runner.os = FakeOs({str(self.mount)}, **kwargs)

    def unmounted(self) -> None:
        self.runner.os = FakeOs(set())


class RenderedDefaultsTest(unittest.TestCase):
    def test_defaults_point_at_the_external_disk(self):
        runner = load_runner()
        self.assertEqual(runner.WORK_DIR, "/mnt/cryptdata/backups/tmp/unifi-backup")
        self.assertEqual(runner.WORK_MOUNT, "/mnt/cryptdata")
        self.assertEqual(runner.WORK_RETENTION_HOURS, 24)
        self.assertEqual(runner.WORK_OWNER_UID, 0)

    def test_shared_temp_dir_is_ignored(self):
        legacy = {"echoport_backup_temp_dir": "/tmp/unifi-backup", "unifi_echoport_backup_temp_dir": "/tmp/unifi-backup"}
        source = render(**legacy)
        self.assertNotIn('"/tmp/unifi-backup"', source)
        self.assertNotIn("TEMP_DIR", source)
        self.assertEqual(load_runner(**legacy).WORK_DIR, "/mnt/cryptdata/backups/tmp/unifi-backup")

    def test_role_variables_override_defaults(self):
        runner = load_runner(
            unifi_echoport_backup_work_dir="/srv/ext/work/unifi",
            unifi_echoport_backup_work_mount="/srv/ext",
            unifi_echoport_backup_work_retention_hours=6,
        )
        self.assertEqual((runner.WORK_DIR, runner.WORK_MOUNT, runner.WORK_RETENTION_HOURS), ("/srv/ext/work/unifi", "/srv/ext", 6))

    def test_nothing_is_created_before_main(self):
        main_block = TEMPLATE.read_text().split('if __name__ == "__main__":', 1)[1]
        self.assertNotIn("mkdir", main_block)


class MountCheckTest(WorkDirTestCase):
    def test_prepares_root_only_work_dir_on_the_mount(self):
        self.runner.prepare_work_dir()
        self.assertTrue(self.work.is_dir())
        for path in (self.mount / "backups", self.mount / "backups/tmp", self.work):
            self.assertEqual(stat.S_IMODE(path.lstat().st_mode), 0o700, path)

    def test_existing_work_dir_mode_is_tightened(self):
        self.work.mkdir(parents=True)
        self.work.chmod(0o755)
        self.runner.prepare_work_dir()
        self.assertEqual(stat.S_IMODE(self.work.lstat().st_mode), 0o700)

    def test_refuses_when_mount_is_not_mounted(self):
        self.unmounted()
        with self.assertRaisesRegex(RuntimeError, "not mounted"):
            self.runner.prepare_work_dir()
        self.assertFalse((self.mount / "backups").exists())

    def test_refuses_mount_on_the_root_device(self):
        self.mounted(root_device=os.lstat(self.mount).st_dev)
        with self.assertRaisesRegex(RuntimeError, "root filesystem device"):
            self.runner.prepare_work_dir()

    def test_refuses_root_as_mount(self):
        self.runner.WORK_MOUNT = "/"
        self.runner.os = FakeOs({"/"})
        with self.assertRaisesRegex(RuntimeError, "root filesystem"):
            self.runner.prepare_work_dir()

    def test_refuses_missing_mount(self):
        self.runner.WORK_MOUNT = str(self.mount.parent / "absent")
        with self.assertRaisesRegex(RuntimeError, "missing"):
            self.runner.prepare_work_dir()

    def test_refuses_work_dir_outside_or_equal_to_mount(self):
        for work in ("/tmp/unifi-backup", str(self.mount), str(self.mount) + "-other/unifi"):
            self.runner.WORK_DIR = work
            with self.subTest(work=work), self.assertRaisesRegex(RuntimeError, "not below work mount"):
                self.runner.prepare_work_dir()

    def test_refuses_relative_or_unnormalized_paths(self):
        for work in ("backups/unifi", str(self.mount) + "/backups/../../escape"):
            self.runner.WORK_DIR = work
            with self.subTest(work=work), self.assertRaisesRegex(ValueError, "normalized absolute"):
                self.runner.prepare_work_dir()

    def test_refuses_component_on_another_device(self):
        (self.mount / "backups").mkdir()
        self.mounted(devices={str(self.mount / "backups"): os.lstat(self.mount).st_dev + 1})
        with self.assertRaisesRegex(RuntimeError, "not on"):
            self.runner.prepare_work_dir()
        self.assertFalse((self.mount / "backups/tmp").exists())

    def test_refuses_symlinked_component_without_following_it(self):
        outside = self.mount.parent / "outside"
        outside.mkdir()
        (self.mount / "backups").symlink_to(outside)
        with self.assertRaisesRegex(RuntimeError, "not a plain directory"):
            self.runner.prepare_work_dir()
        self.assertEqual(list(outside.iterdir()), [])

    def test_refuses_symlinked_mount(self):
        link = self.mount.parent / "link"
        link.symlink_to(self.mount)
        self.runner.WORK_MOUNT = str(link)
        self.runner.WORK_DIR = str(link / "work")
        self.runner.os = FakeOs({str(link)})
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            self.runner.prepare_work_dir()

    def test_refuses_foreign_owned_work_dir(self):
        self.runner.WORK_OWNER_UID = os.getuid() + 1
        with self.assertRaisesRegex(RuntimeError, "not owned by root"):
            self.runner.prepare_work_dir()

    def test_no_fallback_temp_dir_when_the_check_fails(self):
        self.unmounted()
        with mock.patch.object(tempfile, "mkdtemp", side_effect=AssertionError("mkdtemp called")):
            with self.assertRaisesRegex(RuntimeError, "not mounted"):
                self.runner.create_run_dir("unifi_backup_")


class RetentionTest(WorkDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.device = self.runner.prepare_work_dir()
        self.old = time.time() - 48 * 3600

    def make_dir(self, name: str, old: bool) -> Path:
        path = self.work / name
        path.mkdir()
        (path / "payload.bin").write_bytes(b"x")
        if old:
            os.utime(path, (self.old, self.old))
        return path

    def test_prunes_only_stale_run_dirs(self):
        stale_backup = self.make_dir("unifi_backup_old", old=True)
        stale_restore = self.make_dir("unifi_restore_old", old=True)
        fresh = self.make_dir("unifi_backup_fresh", old=False)
        foreign = self.make_dir("keep_me", old=True)
        removed, failed = self.runner.prune_stale_run_dirs(self.device)
        self.assertEqual(sorted(removed), ["unifi_backup_old", "unifi_restore_old"])
        self.assertEqual(failed, [])
        self.assertFalse(stale_backup.exists() or stale_restore.exists())
        self.assertTrue(fresh.is_dir() and foreign.is_dir())

    def test_does_not_follow_symlinks(self):
        outside = self.mount.parent / "outside"
        outside.mkdir()
        (outside / "precious").write_text("keep")
        link = self.work / "unifi_backup_link"
        link.symlink_to(outside, target_is_directory=True)
        os.utime(link, (self.old, self.old), follow_symlinks=False)
        stale = self.make_dir("unifi_backup_old", old=False)
        (stale / "escape").symlink_to(outside, target_is_directory=True)
        os.utime(stale, (self.old, self.old))
        removed, _ = self.runner.prune_stale_run_dirs(self.device)
        self.assertEqual(removed, ["unifi_backup_old"])
        self.assertTrue(link.is_symlink())
        self.assertEqual((outside / "precious").read_text(), "keep")

    def test_skips_run_dirs_on_another_device(self):
        stale = self.make_dir("unifi_backup_old", old=True)
        removed, _ = self.runner.prune_stale_run_dirs(self.device + 1)
        self.assertEqual(removed, [])
        self.assertTrue(stale.is_dir())

    def test_create_run_dir_prunes_and_creates_private_dir(self):
        stale = self.make_dir("unifi_backup_old", old=True)
        run_dir = self.runner.create_run_dir("unifi_backup_")
        self.assertFalse(stale.exists())
        self.assertEqual(run_dir.parent, self.work)
        self.assertEqual(stat.S_IMODE(run_dir.lstat().st_mode), 0o700)
        self.assertTrue(any("stale work dir" in e.get("message", "") for e in self.events))


class FlowTest(WorkDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.umask = os.umask(0o022)
        creds = {"host": "127.0.0.1", "port": 27017, "database": "unifi", "username": "u", "password": "p", "auth_db": "admin"}
        self.runner.validate_config_paths = lambda: None
        self.runner.ensure_binaries = lambda: None
        self.runner.read_mongo_credentials = lambda: dict(creds)
        self.runner.service_is_active = lambda: False
        self.runner.rsync_dir = lambda *args, **kwargs: None

    def tearDown(self) -> None:
        os.umask(self.umask)
        super().tearDown()

    def run_dirs(self) -> list[Path]:
        return sorted(self.work.iterdir()) if self.work.exists() else []

    def test_backup_refuses_before_any_work_when_unmounted(self):
        self.unmounted()
        dumps = []
        self.runner.mongo_dump = lambda creds, out: dumps.append(out)
        with self.assertRaisesRegex(RuntimeError, "not mounted"):
            self.runner.backup_flow({})
        self.assertEqual((dumps, self.commands), ([], []))

    def test_restore_refuses_before_download_when_unmounted(self):
        self.unmounted()
        downloads = []
        self.runner.download_from_minio = lambda *args: downloads.append(args)
        with self.assertRaisesRegex(RuntimeError, "not mounted"):
            self.runner.restore_flow({"ECHOPORT_KEY": "unifi/x.tar.gz", "ECHOPORT_CHECKSUM": "0" * 64})
        self.assertEqual((downloads, self.commands), ([], []))

    def test_backup_removes_run_dir_on_failure(self):
        def failing_dump(creds, out):
            out.mkdir(parents=True, exist_ok=True)
            (out / "partial.bson").write_bytes(b"x")
            raise RuntimeError("mongodump failed")

        self.runner.mongo_dump = failing_dump
        self.assertEqual(self.runner.backup_flow({}), 1)
        self.assertEqual(self.run_dirs(), [])

    def test_backup_removes_run_dir_when_config_validation_fails(self):
        def invalid():
            raise ValueError("bad config")

        self.runner.validate_config_paths = invalid
        with self.assertRaisesRegex(ValueError, "bad config"):
            self.runner.backup_flow({})
        self.assertEqual(self.run_dirs(), [])

    def test_backup_archive_is_private_and_run_dir_removed(self):
        modes = {}

        def dump(creds, out):
            (out / creds["database"]).mkdir(parents=True)
            (out / creds["database"] / "c.bson").write_bytes(b"x")

        def upload(tarball, bucket, key):
            modes["run_dir"] = stat.S_IMODE(tarball.parent.lstat().st_mode)
            modes["parent"] = tarball.parent.parent
            modes["tarball"] = stat.S_IMODE(tarball.lstat().st_mode)
            modes["dump"] = stat.S_IMODE((tarball.parent / "payload/database/unifi/c.bson").lstat().st_mode)

        self.runner.mongo_dump = dump
        self.runner.upload_to_minio = upload
        self.runner.copy_file_optional = lambda src, dst: False
        self.assertEqual(self.runner.backup_flow({"ECHOPORT_KEY_PREFIX": "unifi/test"}), 0)
        self.assertEqual(modes, {"run_dir": 0o700, "parent": self.work, "tarball": 0o600, "dump": 0o600})
        self.assertEqual(self.run_dirs(), [])

    def test_restore_uses_the_work_dir_and_cleans_up(self):
        seen = {}

        def download(bucket, key, dest):
            seen["parent"] = dest.parent.parent
            seen["prefix"] = dest.parent.name.split("_")[1]
            dest.write_bytes(b"not a tarball")
            dest.chmod(0o644)

        self.runner.download_from_minio = download
        self.runner.calculate_sha256 = lambda path: seen.setdefault("mode", stat.S_IMODE(path.lstat().st_mode)) and "0" * 64
        self.runner.disk_space_precheck = mock.Mock(side_effect=RuntimeError("stop here"))
        result = self.runner.restore_flow({"ECHOPORT_KEY": "unifi/x.tar.gz", "ECHOPORT_CHECKSUM": "0" * 64})
        self.assertEqual(result, 1)
        self.assertEqual(seen, {"parent": self.work, "prefix": "restore", "mode": 0o600})
        self.assertEqual(self.run_dirs(), [])


if __name__ == "__main__":
    unittest.main()
