"""Private media contracts for the python-podcast production DB backup runner.

The runner is rendered from its Jinja template and exercised with SSH, SCP and
subprocess calls faked out; nothing touches a real host or bucket.
"""

from __future__ import annotations

import contextlib
import grp
import hashlib
import io
import json
import os
import pwd
import shutil
import subprocess
import tarfile
import tempfile
import types
import unittest
import warnings
from pathlib import Path
from typing import Any
from unittest import mock

from ansible.plugins.filter.core import FilterModule
from jinja2 import Environment, FileSystemLoader, StrictUndefined


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "roles" / "echoport_backup" / "templates"
TEMPLATE = "python_podcast_production_db_backup.py.j2"
DEFAULT_PATH = "/home/python-podcast/site/private_media"


def render_runner(**overrides: Any) -> types.ModuleType:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        undefined=StrictUndefined,
        autoescape=False,
    )
    # Ansible's own filters (to_json, bool, regex_replace), as at deploy time.
    ansible_filters = FilterModule().filters()
    for name in ("to_json", "bool", "regex_replace"):
        env.filters[name] = ansible_filters[name]
    variables: dict[str, Any] = {
        "echoport_backup_mc_install_path": "/usr/local/bin/mc",
        "echoport_backup_minio_alias": "minio",
        "echoport_backup_default_bucket": "backups",
        "echoport_backup_temp_dir": "/tmp/pp-prod-db-backup-test",
    }
    variables.update(overrides)
    source = env.get_template(TEMPLATE).render(**variables)
    module = types.ModuleType("python_podcast_production_db_backup_test")
    module.__file__ = str(TEMPLATE_DIR / TEMPLATE)
    with warnings.catch_warnings():
        # The runner's pre-existing `return` inside `finally` is intentional.
        warnings.simplefilter("ignore", SyntaxWarning)
        code = compile(source, module.__file__, "exec")
    exec(code, module.__dict__)
    return module


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_private_media_tar(path: Path, root: str = "private_media") -> None:
    """Build a tarball shaped like `tar -C <site> -czf ... private_media`."""
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / root / "cast_voice_references"
        tree.mkdir(parents=True)
        (tree / "speaker-1.wav").write_bytes(b"RIFF voice one")
        (tree / "known_speakers.json").write_text('{"speakers": []}')
        with tarfile.open(path, "w:gz") as tar:
            tar.add(Path(tmp) / root, arcname=root)


def add_member(tar: tarfile.TarFile, name: str, **attrs: Any) -> None:
    info = tarfile.TarInfo(name)
    data = attrs.pop("data", b"")
    for key, value in attrs.items():
        setattr(info, key, value)
    if info.isfile():
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    else:
        tar.addfile(info)


class FakeRemote:
    """Records SSH/SCP traffic and plays the production/staging hosts."""

    def __init__(self, work: Path, probe: str = "present", du_bytes: int = 4096) -> None:
        self.work = work
        self.probe = probe
        self.du_bytes = du_bytes
        self.ssh_commands: list[str] = []
        self.scp_from: list[tuple[str, str]] = []
        self.scp_to: list[tuple[str, str]] = []
        self.uploaded: Path | None = None
        self.download_source: Path | None = None

    def ssh(self, host: str, user: str, cmd: str, check: bool = True) -> subprocess.CompletedProcess:
        self.ssh_commands.append(cmd)
        stdout = ""
        if cmd.startswith("mktemp -d /tmp/echoport-pp-private-media."):
            stdout = "/tmp/echoport-pp-private-media.Ab12Cd34\n"
        elif cmd.startswith("if test -L"):
            stdout = f"{self.probe}\n"
        elif cmd.startswith("du -sb"):
            stdout = f"{self.du_bytes}\t{DEFAULT_PATH}\n"
        elif cmd.startswith("systemctl show"):
            stdout = "loaded\n"
        return subprocess.CompletedProcess(cmd, 0, stdout, "")

    def scp_from_remote(self, host: str, user: str, remote: str, local: str) -> None:
        self.scp_from.append((remote, local))
        if remote.endswith(".dump"):
            Path(local).write_bytes(b"PGDMP fake dump")
        else:
            make_private_media_tar(Path(local))

    def scp_to_remote(self, host: str, user: str, local: str, remote: str) -> None:
        self.scp_to.append((local, remote))

    def run(self, args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        if args[0] == "pg_restore":
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[1] == "cp" and args[2].startswith("minio/"):
            assert self.download_source is not None
            shutil.copy(self.download_source, args[3])
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[1] == "cp":
            self.uploaded = self.work / "uploaded.tar.gz"
            shutil.copy(args[2], self.uploaded)
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 0, "", "")  # mc stat

    @contextlib.contextmanager
    def installed(self, runner: types.ModuleType):
        with (
            mock.patch.object(runner, "ssh", side_effect=self.ssh),
            mock.patch.object(runner, "scp_from_remote", side_effect=self.scp_from_remote),
            mock.patch.object(runner, "scp_to_remote", side_effect=self.scp_to_remote),
            mock.patch.object(runner.subprocess, "run", side_effect=self.run),
            mock.patch.object(runner, "TEMP_DIR", str(self.work)),
            contextlib.redirect_stdout(io.StringIO()) as out,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            yield out


def emitted_steps(output: str) -> list[dict]:
    return [json.loads(line) for line in output.splitlines() if line.startswith("{")]


class RenderDefaultsTests(unittest.TestCase):
    def test_defaults_enable_backup_and_keep_restore_opt_in(self) -> None:
        runner = render_runner()
        self.assertEqual(runner.PRIVATE_MEDIA_PATH, DEFAULT_PATH)
        self.assertEqual(runner.RESTORE_PRIVATE_MEDIA_PATH, DEFAULT_PATH)
        self.assertEqual(runner.RESTORE_PRIVATE_MEDIA_OWNER, "python-podcast:python-podcast")
        self.assertIs(runner.RESTORE_PRIVATE_MEDIA_DEFAULT, False)
        self.assertEqual(runner.PRIVATE_MEDIA_MAX_BYTES, 2 * 1024**3)

    def test_role_vars_override_defaults(self) -> None:
        runner = render_runner(
            pp_prod_db_backup_private_media_path="/srv/pp/private",
            pp_prod_db_backup_private_media_max_bytes=1024,
            pp_prod_db_backup_restore_private_media=True,
            pp_prod_db_backup_restore_private_media_path="/srv/staging/private",
            pp_prod_db_backup_restore_private_media_owner="pp:pp",
        )
        self.assertEqual(runner.PRIVATE_MEDIA_PATH, "/srv/pp/private")
        self.assertEqual(runner.PRIVATE_MEDIA_MAX_BYTES, 1024)
        self.assertIs(runner.RESTORE_PRIVATE_MEDIA_DEFAULT, True)
        self.assertEqual(runner.RESTORE_PRIVATE_MEDIA_PATH, "/srv/staging/private")
        self.assertEqual(runner.RESTORE_PRIVATE_MEDIA_OWNER, "pp:pp")


class PrivateMediaBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = render_runner()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def run_backup(self, runner: types.ModuleType, remote: FakeRemote) -> tuple[int, list[dict]]:
        with remote.installed(runner) as out:
            rc = runner.backup(bucket="backups", key_prefix="pp/run", timestamp="2026-10-06T02-00-00")
        return rc, emitted_steps(out.getvalue())

    def test_backup_runs_only_when_path_is_set(self) -> None:
        runner = render_runner(pp_prod_db_backup_private_media_path="")
        remote = FakeRemote(self.tmp)
        rc, _ = self.run_backup(runner, remote)
        self.assertEqual(rc, 0)
        self.assertFalse(any("tar " in cmd or "du -sb" in cmd for cmd in remote.ssh_commands))
        assert remote.uploaded is not None
        with tarfile.open(remote.uploaded) as tar:
            self.assertNotIn("private_media/private_media.tar.gz", tar.getnames())
            manifest = json.load(tar.extractfile("manifest.json"))  # type: ignore[arg-type]
        self.assertNotIn("private_media", manifest)

    def test_backup_ships_private_media_with_its_own_checksum(self) -> None:
        remote = FakeRemote(self.tmp)
        rc, steps = self.run_backup(self.runner, remote)
        self.assertEqual(rc, 0)

        tar_cmds = [cmd for cmd in remote.ssh_commands if " tar " in f" {cmd}"]
        self.assertEqual(len(tar_cmds), 1)
        self.assertTrue(tar_cmds[0].startswith("umask 077 && tar -C /home/python-podcast/site -czf "))
        self.assertTrue(tar_cmds[0].endswith("-- private_media"))
        remote_dir = "/tmp/echoport-pp-private-media.Ab12Cd34"
        self.assertIn(f"-czf {remote_dir}/private_media.tar.gz ", tar_cmds[0])
        mktemp = next(i for i, cmd in enumerate(remote.ssh_commands) if cmd.startswith("mktemp -d"))
        self.assertLess(mktemp, remote.ssh_commands.index(tar_cmds[0]))
        self.assertIn(f"rm -rf -- {remote_dir}", remote.ssh_commands)

        assert remote.uploaded is not None
        extract = self.tmp / "check"
        with tarfile.open(remote.uploaded) as tar:
            tar.extractall(extract)
        manifest = json.loads((extract / "manifest.json").read_text())
        entry = manifest["private_media"]
        nested = extract / "private_media" / "private_media.tar.gz"
        self.assertTrue(entry["included"])
        self.assertEqual(entry["source"], DEFAULT_PATH)
        self.assertEqual(entry["root"], "private_media")
        self.assertEqual(entry["checksum_sha256"], sha256(nested))
        self.assertEqual(entry["file_count"], 2)
        result = next(s for s in steps if s.get("name") == "result")
        self.assertEqual(json.loads(result["message"].split(":", 1)[1])["file_count"], 2)

    def test_missing_directory_is_a_warning_not_a_failure(self) -> None:
        remote = FakeRemote(self.tmp, probe="missing")
        rc, steps = self.run_backup(self.runner, remote)
        self.assertEqual(rc, 0)
        self.assertFalse(any(cmd.startswith("du -sb") for cmd in remote.ssh_commands))
        step = [s for s in steps if s.get("name") == "backup_private_media"][-1]
        self.assertEqual(step["state"], "success")
        self.assertIn("WARNING", step["message"])
        assert remote.uploaded is not None
        with tarfile.open(remote.uploaded) as tar:
            self.assertNotIn("private_media/private_media.tar.gz", tar.getnames())
            manifest = json.load(tar.extractfile("manifest.json"))  # type: ignore[arg-type]
        self.assertEqual(manifest["private_media"], {"included": False, "source": DEFAULT_PATH, "reason": "missing"})

    def test_symlinked_directory_fails_the_backup(self) -> None:
        remote = FakeRemote(self.tmp, probe="symlink")
        rc, _ = self.run_backup(self.runner, remote)
        self.assertEqual(rc, 1)
        self.assertIsNone(remote.uploaded)

    def test_failed_probe_fails_instead_of_skipping(self) -> None:
        def broken(host, user, cmd, check=True):
            if cmd.startswith("if test -L"):
                return subprocess.CompletedProcess(cmd, 255, "", "ssh: connection refused")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with (
            mock.patch.object(self.runner, "ssh", side_effect=broken),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            with self.assertRaisesRegex(RuntimeError, "connection refused"):
                self.runner.backup_private_media(self.tmp, "/tmp/x.tar.gz")

    def test_size_guard_fails_before_archiving(self) -> None:
        runner = render_runner(pp_prod_db_backup_private_media_max_bytes=1000)
        remote = FakeRemote(self.tmp, du_bytes=1001)
        rc, steps = self.run_backup(runner, remote)
        self.assertEqual(rc, 1)
        self.assertFalse(any(" tar " in f" {cmd}" for cmd in remote.ssh_commands))
        failure = [s for s in steps if s.get("name") == "backup_private_media"][-1]
        self.assertEqual(failure["state"], "failure")
        self.assertIn("byte guard", failure["message"])
        self.assertIsNone(remote.uploaded)

    def test_path_validation(self) -> None:
        validate = self.runner.validate_private_media_path
        self.assertEqual(validate("/home/pp/site/private_media/", "p"), "/home/pp/site/private_media")
        for bad in ["relative/path", "/", "/top", "/home/../etc", "/home/pp/./x", "/home/pp/$(id)", "/home/pp x"]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate(bad, "p")


class PrivateMediaArchiveSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = render_runner(pp_prod_db_backup_private_media_max_bytes=100)
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def archive(self, *members: tuple[str, dict]) -> Path:
        path = self.tmp / "pm.tar.gz"
        with tarfile.open(path, "w:gz") as tar:
            add_member(tar, "private_media", type=tarfile.DIRTYPE)
            for name, attrs in members:
                add_member(tar, name, **attrs)
        return path

    def test_accepts_regular_tree(self) -> None:
        path = self.archive(
            ("private_media/cast_voice_references", {"type": tarfile.DIRTYPE}),
            ("private_media/cast_voice_references/a.wav", {"data": b"abc"}),
        )
        self.assertEqual(self.runner.verify_private_media_archive(path, "private_media"), (1, 3))

    def test_rejects_unsafe_members(self) -> None:
        cases = {
            "traversal": ("private_media/../escape", {"data": b"x"}),
            "absolute": ("/etc/passwd", {"data": b"x"}),
            "outside root": ("other/file", {"data": b"x"}),
            "symlink": ("private_media/link", {"type": tarfile.SYMTYPE, "linkname": "a"}),
            "hardlink": ("private_media/hard", {"type": tarfile.LNKTYPE, "linkname": "private_media/a"}),
            "fifo": ("private_media/fifo", {"type": tarfile.FIFOTYPE}),
            "oversize": ("private_media/big.wav", {"data": b"x" * 101}),
        }
        for label, member in cases.items():
            with self.subTest(label), self.assertRaises(ValueError):
                self.runner.verify_private_media_archive(self.archive(member), "private_media")

    def test_rejects_invalid_root_name(self) -> None:
        path = self.archive()
        for root in ["..", ".", "a/b", "$(id)"]:
            with self.subTest(root=root), self.assertRaises(ValueError):
                self.runner.verify_private_media_archive(path, root)


class PrivateMediaRestoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = render_runner()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def backup_archive(self, checksum: str | None = None, include: bool = True) -> tuple[Path, str]:
        """Build an outer archive shaped like the runner's backup output."""
        build = self.tmp / "build"
        (build / "database").mkdir(parents=True)
        (build / "database" / "python-podcast.dump").write_bytes(b"PGDMP")
        manifest: dict[str, Any] = {"target": "python-podcast-production-db"}
        if include:
            (build / "private_media").mkdir()
            nested = build / "private_media" / "private_media.tar.gz"
            make_private_media_tar(nested)
            manifest["private_media"] = {
                "included": True,
                "root": "private_media",
                "checksum_sha256": checksum or sha256(nested),
            }
        (build / "manifest.json").write_text(json.dumps(manifest))
        outer = self.tmp / "backup.tar.gz"
        with tarfile.open(outer, "w:gz") as tar:
            for item in sorted(build.iterdir()):
                tar.add(item, arcname=item.name)
        return outer, sha256(outer)

    def run_restore(self, opt_in: bool, **archive: Any) -> tuple[int, FakeRemote, list[dict]]:
        outer, checksum = self.backup_archive(**archive)
        remote = FakeRemote(self.tmp)
        remote.download_source = outer
        with remote.installed(self.runner) as out:
            rc = self.runner.restore(
                bucket="backups", key="pp/run.tar.gz", expected_checksum=checksum,
                include_private_media=opt_in,
            )
        return rc, remote, emitted_steps(out.getvalue())

    def test_default_restore_does_not_extract_or_ship_private_media(self) -> None:
        extracted: list[str] = []
        real_extract = self.runner.safe_extract_tarball

        def spy(tarball, dest, include_private_media=False):
            real_extract(tarball, dest, include_private_media=include_private_media)
            extracted.extend(str(p.relative_to(dest)) for p in Path(dest).rglob("*"))

        with mock.patch.object(self.runner, "safe_extract_tarball", side_effect=spy):
            rc, remote, steps = self.run_restore(opt_in=False)
        self.assertEqual(rc, 0)
        self.assertFalse(any(p.startswith("private_media") for p in extracted))
        self.assertEqual([remote_path for _, remote_path in remote.scp_to], [remote.scp_to[0][1]])
        self.assertTrue(remote.scp_to[0][1].endswith(".dump"))
        self.assertFalse(any(cmd.startswith("sh -c") for cmd in remote.ssh_commands))
        skipped = [s for s in steps if s.get("name") == "restore_private_media"]
        self.assertIn("--include-private-media", skipped[-1]["message"])

    def test_opted_in_restore_installs_private_media_while_stopped(self) -> None:
        rc, remote, _ = self.run_restore(opt_in=True)
        self.assertEqual(rc, 0)
        shipped = [remote_path for _, remote_path in remote.scp_to]
        self.assertEqual(len(shipped), 2)
        self.assertTrue(shipped[1].endswith(".tar.gz"))
        commands = remote.ssh_commands
        install = next(i for i, cmd in enumerate(commands) if cmd.startswith("sh -c"))
        restore_db = next(i for i, cmd in enumerate(commands) if "pg_restore" in cmd)
        start = next(i for i, cmd in enumerate(commands) if cmd.startswith("systemctl start"))
        self.assertLess(restore_db, install)
        self.assertLess(install, start)
        self.assertIn(DEFAULT_PATH, commands[install])
        self.assertIn("python-podcast:python-podcast", commands[install])
        self.assertEqual(shipped[1], "/tmp/echoport-pp-private-media.Ab12Cd34/private_media.tar.gz")
        self.assertIn("rm -rf -- /tmp/echoport-pp-private-media.Ab12Cd34", commands)

    def test_checksum_mismatch_fails_before_anything_destructive(self) -> None:
        rc, remote, _ = self.run_restore(opt_in=True, checksum="0" * 64)
        self.assertEqual(rc, 1)
        self.assertEqual(remote.scp_to, [])
        self.assertFalse(any(cmd.startswith("systemctl stop") for cmd in remote.ssh_commands))
        self.assertFalse(any("dropdb" in cmd for cmd in remote.ssh_commands))

    def test_opted_in_restore_of_backup_without_private_media_warns(self) -> None:
        rc, remote, steps = self.run_restore(opt_in=True, include=False)
        self.assertEqual(rc, 0)
        self.assertFalse(any(cmd.startswith("sh -c") for cmd in remote.ssh_commands))
        warning = [s for s in steps if s.get("name") == "restore_private_media"][-1]
        self.assertIn("WARNING", warning["message"])

    def test_unsafe_private_member_is_rejected_even_when_not_extracted(self) -> None:
        outer = self.tmp / "evil.tar.gz"
        with tarfile.open(outer, "w:gz") as tar:
            add_member(tar, "private_media/../../escape", data=b"x")
        dest = self.tmp / "dest"
        dest.mkdir()
        with self.assertRaises(ValueError):
            self.runner.safe_extract_tarball(outer, dest, include_private_media=False)

    def test_unnormalized_private_member_is_not_extracted(self) -> None:
        outer = self.tmp / "dot.tar.gz"
        with tarfile.open(outer, "w:gz") as tar:
            add_member(tar, "./private_media/private_media.tar.gz", data=b"secret")
            add_member(tar, "manifest.json", data=b"{}")
        dest = self.tmp / "dest"
        dest.mkdir()
        self.runner.safe_extract_tarball(outer, dest, include_private_media=False)
        self.assertEqual(sorted(p.name for p in dest.rglob("*")), ["manifest.json"])

    def test_outer_archive_links_are_rejected(self) -> None:
        cases = {
            "hardlink": [
                ("private_media/private_media.tar.gz", {"data": b"secret"}),
                ("database/leak", {"type": tarfile.LNKTYPE, "linkname": "private_media/private_media.tar.gz"}),
            ],
            "symlink": [
                ("private_media/private_media.tar.gz", {"data": b"secret"}),
                ("database/leak", {"type": tarfile.SYMTYPE, "linkname": "../private_media/private_media.tar.gz"}),
            ],
            "symlinked ancestor": [
                ("alias", {"type": tarfile.SYMTYPE, "linkname": "."}),
                ("alias/private_media/private_media.tar.gz", {"data": b"secret"}),
            ],
        }
        for label, members in cases.items():
            outer = self.tmp / f"{label}.tar.gz"
            with tarfile.open(outer, "w:gz") as tar:
                for name, attrs in members:
                    add_member(tar, name, **attrs)
            for include in (False, True):
                dest = self.tmp / f"dest-{label}-{include}"
                dest.mkdir()
                with self.subTest(label, include=include), self.assertRaisesRegex(ValueError, "link"):
                    self.runner.safe_extract_tarball(outer, dest, include_private_media=include)
                self.assertEqual(list(dest.iterdir()), [])

    def test_install_script_handles_root_named_like_its_parking_dirs(self) -> None:
        for root in ["previous", "old", "new", "tree"]:
            with self.subTest(root=root):
                base = self.tmp / f"case-{root}"
                target = base / "site" / root
                (target / "stale").mkdir(parents=True)
                archive = base / "pm.tar.gz"
                make_private_media_tar(archive, root=root)
                owner = f"{pwd.getpwuid(os.getuid()).pw_name}:{grp.getgrgid(os.getgid()).gr_name}"
                script = self.runner.install_private_media_script(str(archive), root, str(target), owner)
                subprocess.run(["sh", "-c", script], check=True, capture_output=True)
                self.assertEqual(sorted(p.name for p in target.iterdir()), ["cast_voice_references"])
                self.assertEqual(sorted(p.name for p in target.parent.iterdir()), [root])

    def test_install_script_swaps_tree_in_place(self) -> None:
        site = self.tmp / "site"
        target = site / "private_media"
        (target / "stale").mkdir(parents=True)
        (target / "stale" / "old.wav").write_bytes(b"old")
        archive = self.tmp / "pm.tar.gz"
        make_private_media_tar(archive)
        owner = f"{pwd.getpwuid(os.getuid()).pw_name}:{grp.getgrgid(os.getgid()).gr_name}"
        script = self.runner.install_private_media_script(str(archive), "private_media", str(target), owner)
        subprocess.run(["sh", "-c", script], check=True, capture_output=True)
        self.assertTrue((target / "cast_voice_references" / "speaker-1.wav").is_file())
        self.assertFalse((target / "stale").exists())
        self.assertEqual(sorted(p.name for p in site.iterdir()), ["private_media"])


class RestoreOptInTests(unittest.TestCase):
    def call_main(self, runner: types.ModuleType, argv: list[str]) -> dict:
        context = {
            "context": {
                "env": {
                    "ECHOPORT_ACTION": "restore",
                    "ECHOPORT_KEY": "pp/run.tar.gz",
                    "ECHOPORT_CHECKSUM": "a" * 64,
                    "ECHOPORT_INCLUDE_PRIVATE_MEDIA": "true",
                    "ECHOPORT_BACKUP_FILES": "/home/python-podcast/site/private_media",
                }
            }
        }
        with (
            mock.patch.object(runner, "read_config_file", return_value=context),
            mock.patch.object(runner, "restore", return_value=0) as restore,
            mock.patch.object(runner.sys, "argv", ["backup.py", "--config", "/x", *argv]),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(runner.main(), 0)
        return restore.call_args.kwargs

    def test_echoport_context_cannot_opt_in(self) -> None:
        self.assertIs(self.call_main(render_runner(), [])["include_private_media"], False)

    def test_cli_flag_opts_in(self) -> None:
        kwargs = self.call_main(render_runner(), ["--include-private-media"])
        self.assertIs(kwargs["include_private_media"], True)

    def test_locked_role_var_opts_in(self) -> None:
        runner = render_runner(pp_prod_db_backup_restore_private_media=True)
        self.assertIs(self.call_main(runner, [])["include_private_media"], True)


if __name__ == "__main__":
    unittest.main()
