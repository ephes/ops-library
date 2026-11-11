"""The restore scratch destination: the guard's --restore-scratch mode and the
runners' restore-scratch action (roles/echoport_backup/templates/_restore_scratch.py.j2).

- check_scratch() allows exactly the commands a scratch restore sends, only
  inside a scratch dir, and refuses every live path, systemctl and --delete;
  the live key's check() is unchanged for them;
- rmtree removes a scratch dir on descriptors without following a symlink;
- main() --restore-scratch answers the mode probe and logs the mode;
- the marina runner restores a real archive through the guard (each command
  decided by check_scratch and carried out on a temporary root), verifies it,
  removes it, and leaves the live files byte for byte as they were;
- a scratch request's poisoned live fields stop the backup path before any
  service stop (what an older runner would run for the unknown action).
"""

from __future__ import annotations

import contextlib
import grp
import hashlib
import io
import json
import os
import pwd
import shlex
import shutil
import sqlite3
import stat
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from tests.test_echoport_remote_command_guard import GUARD, STAGING_POLICY, identity, policy, render_runner

ROOT = "/home/marina/site"
SCRATCH = f"{ROOT}/.restore-scratch-20261111T120000Z-42"
POISON_DB = "/nonexistent/echoport-restore-scratch-needs-a-scratch-runner/db.sqlite3"
POISON_UNIT = "echoport-restore-scratch-needs-a-scratch-runner!"


def absent(path: str) -> os.stat_result:
    raise FileNotFoundError(path)


class ScratchModeDecisions(unittest.TestCase):
    def setUp(self) -> None:
        self.staging = policy(STAGING_POLICY)

    def decide(self, command: str, realpath=identity) -> Any:
        return GUARD.check_scratch(command, self.staging, realpath=realpath, lstat=absent)

    def refused(self, command: str, realpath=identity) -> str:
        with self.assertRaises(GUARD.Refused, msg=command) as caught:
            self.decide(command, realpath)
        return str(caught.exception)

    def test_probe_answers_only_in_scratch_mode(self) -> None:
        decision = self.decide("echoport-guard-mode")
        self.assertEqual((decision.argv, decision.output, decision.mutation), ([], "restore-scratch", None))
        with self.assertRaises(GUARD.Refused):
            GUARD.check("echoport-guard-mode", self.staging, realpath=identity, lstat=absent)

    def test_the_scratch_restore_commands(self) -> None:
        expected = {
            f"test -e {SCRATCH}": ["test", "-e", SCRATCH],
            f"readlink -f {SCRATCH}/db.sqlite3": ["readlink", "-f", f"{SCRATCH}/db.sqlite3"],
            f"mkdir -p {SCRATCH}": ["runuser", "-u", "marina", "--", "mkdir", "-p", SCRATCH],
            f"mkdir {SCRATCH}": ["runuser", "-u", "marina", "--", "mkdir", SCRATCH],
            f"mkdir -p {SCRATCH}/media": ["runuser", "-u", "marina", "--", "mkdir", "-p", f"{SCRATCH}/media"],
            f"scp -t {SCRATCH}/db.sqlite3.tmp": ["runuser", "-u", "marina", "--", "scp", "-t", f"{SCRATCH}/db.sqlite3.tmp"],
            f"rsync --server -logtpre.iLsfxCIvu . {SCRATCH}/media/":
                ["runuser", "-u", "marina", "--", "rsync", "--server", "-logtpre.iLsfxCIvu", ".", f"{SCRATCH}/media/"],
            f"rsync --server --sender -logDtpre.iLsfxCIvu . {SCRATCH}/":
                ["runuser", "-u", "marina", "--", "rsync", "--server", "--sender", "-logDtpre.iLsfxCIvu", ".", f"{SCRATCH}/"],
        }
        for command, argv in expected.items():
            with self.subTest(command=command):
                decision = self.decide(command)
                self.assertEqual(decision.argv, argv)
                self.assertIsNone(decision.mutation)
        mutations = {
            f"chmod 0700 {SCRATCH}": ("chmod", [SCRATCH], "marina"),
            f"mv {SCRATCH}/db.sqlite3.tmp {SCRATCH}/db.sqlite3":
                ("mv", [f"{SCRATCH}/db.sqlite3.tmp", f"{SCRATCH}/db.sqlite3"], "marina"),
            f"chown marina:marina {SCRATCH}/db.sqlite3": ("chown", [f"{SCRATCH}/db.sqlite3"], None),
            f"chown -R marina:marina {SCRATCH}/media": ("chown", [f"{SCRATCH}/media"], None),
            f"rm -rf -- {SCRATCH}": ("rmtree", [SCRATCH], "marina"),
        }
        for command, (op, paths, user) in mutations.items():
            with self.subTest(command=command):
                decision = self.decide(command)
                self.assertEqual(decision.argv, [])
                self.assertEqual((decision.mutation.op, decision.mutation.paths, decision.mutation.user), (op, paths, user))
        self.assertTrue(self.decide(f"mv {SCRATCH}/db.sqlite3.tmp {SCRATCH}/db.sqlite3").mutation.replace)
        self.assertTrue(self.decide(f"chown -R marina:marina {SCRATCH}/media").mutation.recursive)

    def test_live_paths_and_live_commands_are_refused(self) -> None:
        live = [
            # The live restore's commands, for the live paths.
            "systemctl stop marina.service",
            "systemctl start marina.service",
            f"rm -f {ROOT}/db.sqlite3-wal {ROOT}/db.sqlite3-shm",
            f"scp -t {ROOT}/db.sqlite3.tmp",
            f"mv {ROOT}/db.sqlite3.tmp {ROOT}/db.sqlite3",
            f"mkdir -p {ROOT}/media",
            f"rsync --server -logtpre.iLsfxCIvu . {ROOT}/media/",
            f"rsync --server -logtpre.iLsfxCIvu --delete . {ROOT}/media/",
            f"chown marina:marina {ROOT}/db.sqlite3",
            f"chown -R marina:marina {ROOT}/media",
            f"chmod 0600 {ROOT}/db.sqlite3",
            f"readlink -f {ROOT}/db.sqlite3",
            f"test -e {ROOT}/db.sqlite3",
            f"scp -f {ROOT}/db.sqlite3",
            f"rsync --server --sender -logDtpre.iLsfxCIvu --safe-links . {ROOT}/media/",
            # The root itself, its parent, other roots, outside.
            f"rm -rf -- {ROOT}",
            f"mkdir -p {ROOT}",
            f"test -e {ROOT}",
            "rm -rf -- /home/villakunterbunt/data",
            "mkdir -p /tmp/x",
            "rm -rf -- /var/tmp/django-chat-db-restore.Ab12Cd34",
            # Scratch-looking names that are not scratch dirs.
            f"mkdir -p {ROOT}/.restore-scratch-x",
            f"mkdir {ROOT}/media",
            f"mkdir {SCRATCH}/media",
            f"mkdir {ROOT}",
            f"mkdir -p {ROOT}/.restore-scratch-20261111T120000Z-",
            f"mkdir -p {ROOT}/.restore-scratch-20261111T120000Z-1234567890123",
            f"mkdir -p {ROOT}/media/.restore-scratch-20261111T120000Z",
            f"mkdir -p {ROOT}/.restore-scratch-20261111T120000Z/../db.sqlite3",
            # Inside a scratch dir, but not a form the scratch restore uses.
            f"rsync --server -logtpre.iLsfxCIvu --delete . {SCRATCH}/media/",
            f"rsync --server --sender -logDtpre.iLsfxCIvu --safe-links . {SCRATCH}/",
            f"rsync --server --sender -logDtpre.iLsfxCIvu . {SCRATCH}/media/",
            f"scp -f {SCRATCH}/db.sqlite3",
            f"scp -t {SCRATCH}/db.sqlite3",
            f"mv {SCRATCH}/a {SCRATCH}/b",
            f"mv {SCRATCH}/db.sqlite3.tmp {ROOT}/db.sqlite3",
            f"rm -rf -- {SCRATCH}/media",
            f"rm -f {SCRATCH}/db.sqlite3-wal {SCRATCH}/db.sqlite3-shm",
            f"rm -rf {SCRATCH}",
            f"chown root:root {SCRATCH}/db.sqlite3",
            f"chown villakunterbunt:villakunterbunt {SCRATCH}/db.sqlite3",
            f"chmod 0644 {SCRATCH}/db.sqlite3",
            f"runuser -u marina -- sqlite3 {SCRATCH}/db.sqlite3 'PRAGMA integrity_check;'",
            f"sha256sum {SCRATCH}/db.sqlite3",
            f"cat {SCRATCH}/db.sqlite3",
            f"test -e {SCRATCH}; rm -rf {ROOT}",
            "echoport-guard-mode x",
            "id",
            "sh -c true",
        ]
        for command in live:
            with self.subTest(command=command):
                self.refused(command)

    def test_symlinks_out_of_a_scratch_dir_are_refused(self) -> None:
        def into_live(path: str) -> str:
            # <scratch>/media is a symlink to the live media dir.
            if path.startswith(f"{SCRATCH}/media"):
                return ROOT + path[len(SCRATCH):]
            return path

        for command in (
            f"mkdir -p {SCRATCH}/media/x",
            f"rsync --server -logtpre.iLsfxCIvu . {SCRATCH}/media/",
            f"chown -R marina:marina {SCRATCH}/media",
            f"scp -t {SCRATCH}/media/a.tmp",
        ):
            with self.subTest(command=command):
                self.assertIn("as resolved", self.refused(command, realpath=into_live))

    def test_reasons_are_specific(self) -> None:
        self.assertIn("not allowed in restore-scratch mode: 'systemctl'", self.refused("systemctl stop marina.service"))
        self.assertIn("path outside a scratch dir", self.refused(f"mkdir -p {ROOT}/media"))
        self.assertIn("rsync options not allowed", self.refused(f"rsync --server -logtpre.iLsfxCIvu --delete . {SCRATCH}/m/"))


class Rmtree(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.root = self.base / "root"
        self.root.mkdir()
        self.live = self.root / "media"
        self.live.mkdir()
        (self.live / "photo.jpg").write_bytes(b"live")
        self.scratch = self.root / ".restore-scratch-20261111T120000Z"

    def rmtree(self, path: Path) -> None:
        GUARD.perform(GUARD.Mutation("rmtree", [str(path)]))

    def test_removes_a_tree_and_follows_no_symlink(self) -> None:
        (self.scratch / "media" / "deep" / "deeper").mkdir(parents=True)
        (self.scratch / "media" / "deep" / "deeper" / "f").write_bytes(b"x")
        (self.scratch / "db.sqlite3").write_bytes(b"db")
        (self.scratch / "to-live").symlink_to(self.live)
        (self.scratch / "media" / "to-photo").symlink_to(self.live / "photo.jpg")
        locked = self.scratch / "media" / "locked"
        locked.mkdir()
        (locked / "f").write_bytes(b"x")
        locked.chmod(0o500)
        self.rmtree(self.scratch)
        self.assertFalse(self.scratch.exists() or self.scratch.is_symlink())
        self.assertEqual((self.live / "photo.jpg").read_bytes(), b"live")
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["media"])

    def test_missing_dir_is_fine(self) -> None:
        self.rmtree(self.scratch)
        self.rmtree(self.root / "gone" / ".restore-scratch-20261111T120000Z")

    def test_a_symlinked_scratch_dir_is_refused_and_its_target_kept(self) -> None:
        self.scratch.symlink_to(self.live)
        with self.assertRaises(GUARD.Refused):
            self.rmtree(self.scratch)
        self.assertEqual((self.live / "photo.jpg").read_bytes(), b"live")
        self.assertTrue(self.scratch.is_symlink())

    def test_a_symlink_on_the_way_is_refused(self) -> None:
        (self.base / "elsewhere" / ".restore-scratch-20261111T120000Z").mkdir(parents=True)
        (self.root / "link").symlink_to(self.base / "elsewhere")
        with self.assertRaises(GUARD.Refused):
            self.rmtree(self.root / "link" / ".restore-scratch-20261111T120000Z")
        self.assertTrue((self.base / "elsewhere" / ".restore-scratch-20261111T120000Z").is_dir())

    def test_a_file_is_refused(self) -> None:
        self.scratch.write_bytes(b"not a dir")
        with self.assertRaises(GUARD.Refused):
            self.rmtree(self.scratch)
        self.assertTrue(self.scratch.is_file())

    def test_a_swap_during_the_walk_cannot_reach_the_live_tree(self) -> None:
        (self.scratch / "a").mkdir(parents=True)
        (self.scratch / "a" / "f").write_bytes(b"x")

        def hook(event: str, path: str) -> None:
            # Right before "a" is opened, replace it with a symlink to live media.
            if event == "dir" and path == str(self.scratch):
                shutil.rmtree(self.scratch / "a")
                (self.scratch / "a").symlink_to(self.live)

        with contextlib.suppress(GUARD.Refused):
            GUARD.perform(GUARD.Mutation("rmtree", [str(self.scratch)]), hook)
        self.assertEqual((self.live / "photo.jpg").read_bytes(), b"live")


class ScratchMain(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.policy_file = self.tmp / "policy.json"
        self.policy_file.write_text(json.dumps(STAGING_POLICY))

    def run_main(self, argv: list[str], command: str) -> tuple[int, Any, str]:
        env = {"SSH_CLIENT": "100.93.155.101 50000 22", "SSH_ORIGINAL_COMMAND": command}
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(GUARD.os, "execvp") as execvp,
            mock.patch.object(GUARD, "_log") as log,
            contextlib.redirect_stdout(io.StringIO()) as out,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            rc = GUARD.main(argv)
        self.log = log
        return rc, execvp, out.getvalue()

    def test_probe(self) -> None:
        rc, execvp, out = self.run_main(["guard", "--restore-scratch", str(self.policy_file)], "echoport-guard-mode")
        self.assertEqual((rc, out), (0, "restore-scratch\n"))
        execvp.assert_not_called()
        self.assertEqual(self.log.call_args.args[1],
                         "allowed from 100.93.155.101 in restore-scratch mode: 'echoport-guard-mode'")
        rc, execvp, out = self.run_main(["guard", str(self.policy_file)], "echoport-guard-mode")
        self.assertEqual((rc, out), (1, ""))
        self.assertTrue(self.log.call_args.args[1].startswith("refused from 100.93.155.101: command not allowed"))

    def test_scratch_mode_refuses_live_commands_and_says_so(self) -> None:
        rc, execvp, _out = self.run_main(["guard", "--restore-scratch", str(self.policy_file)],
                                         "systemctl stop marina.service")
        self.assertEqual(rc, 1)
        execvp.assert_not_called()
        self.assertEqual(
            self.log.call_args.args[1],
            "refused from 100.93.155.101 in restore-scratch mode: command not allowed in restore-scratch mode: "
            "'systemctl': 'systemctl stop marina.service'",
        )
        # The live key's guard still runs it, with its log line unchanged.
        rc, execvp, _out = self.run_main(["guard", str(self.policy_file)], "systemctl stop marina.service")
        self.assertEqual(rc, 0)
        execvp.assert_called_once_with("systemctl", ["systemctl", "stop", "marina.service"])
        self.assertEqual(self.log.call_args.args[1], "allowed from 100.93.155.101: 'systemctl stop marina.service'")

    def test_scratch_command_runs_as_owner(self) -> None:
        root = os.path.realpath(self.tmp) + "/site"
        os.mkdir(root)
        self.policy_file.write_text(json.dumps({"path_roots": [{"path": root, "owner": "marina:marina"}]}))
        scratch = f"{root}/.restore-scratch-20261111T120000Z-42"
        rc, execvp, _out = self.run_main(["guard", "--restore-scratch", str(self.policy_file)], f"mkdir -p {scratch}")
        self.assertEqual(rc, 0)
        execvp.assert_called_once_with("runuser", ["runuser", "-u", "marina", "--", "mkdir", "-p", scratch])

    def test_usage(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(GUARD.main(["guard", "--other", str(self.policy_file)]), 2)


# --- The marina runner end to end --------------------------------------------


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(root: Path) -> dict:
    """Everything below root except scratch dirs: type, content hash, link target, mode."""
    result = {}
    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".restore-scratch-")]
        for name in dirnames + filenames:
            path = Path(directory) / name
            st = os.lstat(path)
            if stat.S_ISLNK(st.st_mode):
                value = ("link", os.readlink(path))
            elif stat.S_ISDIR(st.st_mode):
                value = ("dir", stat.S_IMODE(st.st_mode))
            else:
                value = ("file", sha(path), stat.S_IMODE(st.st_mode), st.st_mtime_ns)
            result[str(path.relative_to(root))] = value
    return result


class ScratchHost:
    """Staging as the scratch key sees it: each command is decided by the guard
    in --restore-scratch mode and carried out on a temporary root."""

    def __init__(self, test: unittest.TestCase, root: Path, policy_data: dict, archive: Path) -> None:
        self.test = test
        self.root = root
        self.policy = policy(policy_data)
        self.archive = archive
        self.commands: list[str] = []
        self.refusals: list[tuple[str, str]] = []
        self.ssh_argv: list[list[str]] = []
        self.extra_g: list[str] = []  # more ssh -G lines (a config naming another key)

    def decide(self, command: str) -> Any:
        self.commands.append(command)
        try:
            return GUARD.check_scratch(command, self.policy)
        except GUARD.Refused as exc:
            self.refusals.append((command, str(exc)))
            return None

    def execute(self, decision: Any) -> subprocess.CompletedProcess:
        if decision.output is not None:
            return subprocess.CompletedProcess([], 0, decision.output + "\n", "")
        if decision.mutation is not None:
            GUARD.perform(decision.mutation)
            return subprocess.CompletedProcess([], 0, "", "")
        argv = decision.argv
        if argv[0] == "runuser":
            argv = argv[4:]
        if argv[0] == "mkdir" and len(argv) == 2:
            try:
                os.mkdir(argv[1])
            except FileExistsError:
                return subprocess.CompletedProcess(argv, 1, "", "File exists")
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[0] == "mkdir":
            os.makedirs(argv[2], exist_ok=True)
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[0] == "test":
            return subprocess.CompletedProcess(argv, 0 if os.path.lexists(argv[2]) else 1, "", "")
        raise AssertionError(f"unexpected executed command {argv}")

    def run(self, args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        assert isinstance(args, list), args
        if args[1] == "cp":  # mc cp minio/<bucket>/<key> <local>
            shutil.copy(self.archive, args[3])
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[0] == "ssh" and "-G" in args:
            # What ssh -G prints for these options and the scratch config.
            options = dict(args[i + 1].split("=", 1) for i, a in enumerate(args) if a == "-o")
            lines = [f"identityfile {options['IdentityFile']}", *self.extra_g, "identitiesonly yes",
                     "identityagent none", "controlmaster false"]
            return subprocess.CompletedProcess(args, 0, "\n".join(lines) + "\n", "")
        if args[0] == "ssh":
            self.ssh_argv.append(args)
            decision = self.decide(args[-1])
            return subprocess.CompletedProcess(args, 1, "", "refused") if decision is None else self.execute(decision)
        if args[0] == "scp":
            self.ssh_argv.append(args)
            remote = args[-1].split(":", 1)[1]
            decision = self.decide(f"scp -t {remote}")
            if decision is None:
                return subprocess.CompletedProcess(args, 1, "", "refused")
            shutil.copy(args[-2], remote)
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[0] == "rsync":
            e = args.index("-e")
            self.ssh_argv.append(shlex.split(args[e + 1]))
            options, source, target = tuple(args[1:e]), args[e + 2], args[e + 3]
            if options == ("-a", "--no-D"):
                remote = target.split(":", 1)[1]
                decision = self.decide(f"rsync --server -logtpre.iLsfxCIvu . {remote}")
                src, dst = source, remote
            else:
                self.test.assertEqual(options, ("-a",))
                remote = source.split(":", 1)[1]
                decision = self.decide(f"rsync --server --sender -logDtpre.iLsfxCIvu . {remote}")
                src, dst = remote, target
            if decision is None:
                return subprocess.CompletedProcess(args, 1, "", "refused")
            shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True)
            return subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(f"unexpected local command: {args}")


class MarinaScratchRestore(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.root = self.base / "site"
        self.root.mkdir()
        me = pwd.getpwuid(os.geteuid()).pw_name
        group = grp.getgrgid(os.getegid()).gr_name
        self.owner = f"{me}:{group}"
        # Live data: a database with -wal/-shm and media.
        self.live_db = self.root / "db.sqlite3"
        self.live_db.write_bytes(b"live database")
        (self.root / "db.sqlite3-wal").write_bytes(b"wal")
        (self.root / "db.sqlite3-shm").write_bytes(b"shm")
        (self.root / "media" / "img").mkdir(parents=True)
        (self.root / "media" / "img" / "live.jpg").write_bytes(b"live photo")
        (self.root / "media" / "only-live.txt").write_text("not in the backup")
        self.policy_data = {"path_roots": [{"path": str(self.root), "owner": self.owner}], "units": ["marina.service"]}
        self.archive = self.make_archive()
        self.ssh_dir = self.base / "ssh"
        self.ssh_dir.mkdir(mode=0o700)
        for name, content in (("restore-scratch.config", "Host *\n"), ("id_scratch", "scratch key"), ("id_live", "live key")):
            (self.ssh_dir / name).write_text(content)
            (self.ssh_dir / name).chmod(0o600)
        self.runner = render_runner(
            "marina_staging_backup.py.j2",
            marina_staging_backup_default_host="staging.wersdoerfer.de",
            marina_staging_backup_remote_user="root",
            marina_staging_backup_allowed_roots=[f"{self.root}/"],
            marina_staging_backup_restore_owner=self.owner,
            marina_staging_backup_scratch_ssh_config=str(self.ssh_dir / "restore-scratch.config"),
            marina_staging_backup_scratch_ssh_key=str(self.ssh_dir / "id_scratch"),
            marina_staging_backup_live_ssh_key=str(self.ssh_dir / "id_live"),
        )

    def make_archive(self) -> Path:
        stage = self.base / "stage"
        (stage / "media" / "img").mkdir(parents=True)
        (stage / "media" / "img" / "a.jpg").write_bytes(b"backup photo")
        (stage / "media" / "img" / "empty").mkdir()
        (stage / "media" / "rel-link").symlink_to("img/a.jpg")
        db = stage / "db_backup.sqlite3"
        with contextlib.closing(sqlite3.connect(db)) as connection:
            connection.execute("CREATE TABLE t (x)")
            connection.execute("INSERT INTO t VALUES (1)")
            connection.commit()
        manifest = {"database": {"filename": "db_backup.sqlite3"}, "files": [f"{self.root}/media"]}
        (stage / "manifest.json").write_text(json.dumps(manifest))
        archive = self.base / "backup.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for name in ("manifest.json", "db_backup.sqlite3", "media"):
                tar.add(stage / name, arcname=name)
        self.backup_db_sha = sha(db)
        return archive

    def context(self, **overrides: str) -> dict:
        env = {
            "ECHOPORT_ACTION": "restore-scratch",
            "ECHOPORT_RESTORE_DESTINATION": "scratch",
            "ECHOPORT_RESTORE_KEEP_SCRATCH": "0",
            "ECHOPORT_RESTORE_SCRATCH_DB_PATH": str(self.live_db),
            "ECHOPORT_RESTORE_ID": "42",
            "ECHOPORT_KEY": "marina-staging/2026-11-11T03-00-00.tar.gz",
            "ECHOPORT_CHECKSUM": sha(self.archive),
            "ECHOPORT_BUCKET": "backups",
            "ECHOPORT_RESTORE_OWNER": self.owner,
            "ECHOPORT_DB_PATH": POISON_DB,
            "ECHOPORT_SERVICE_NAME": POISON_UNIT,
        }
        env.update(overrides)
        return {"context": {"env": env}}

    def run_runner(self, host: ScratchHost, config: dict) -> tuple[int, dict]:
        work = self.base / "work"
        work.mkdir(exist_ok=True)
        with (
            mock.patch.object(self.runner, "read_config_file", return_value=config),
            mock.patch.object(self.runner.subprocess, "run", side_effect=host.run),
            mock.patch.object(self.runner, "ssh", side_effect=AssertionError("live ssh helper used")),
            mock.patch.object(self.runner, "scp_to_remote", side_effect=AssertionError("live scp helper used")),
            mock.patch.object(self.runner, "rsync_to_remote", side_effect=AssertionError("live rsync helper used")),
            mock.patch.object(self.runner, "create_run_dir",
                              side_effect=lambda prefix: Path(tempfile.mkdtemp(prefix=prefix, dir=work))),
            contextlib.redirect_stdout(io.StringIO()) as out,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            rc = self.runner.main()
        results = [line for line in out.getvalue().splitlines() if "ECHOPORT_RESULT:" in line]
        self.assertEqual(len(results), 1, out.getvalue())
        message = json.loads(results[0])["message"]
        return rc, json.loads(message.split("ECHOPORT_RESULT:", 1)[1])

    def test_restore_verify_cleanup_and_live_untouched(self) -> None:
        before = fingerprint(self.root)
        host = ScratchHost(self, self.root, self.policy_data, self.archive)
        rc, result = self.run_runner(host, self.context())
        self.assertEqual(rc, 0, result)
        self.assertEqual(host.refusals, [])
        scratch = f"{self.root}/.restore-scratch-"
        self.assertTrue(result["scratch_path"].startswith(scratch) and result["scratch_path"].endswith("-42"))
        self.assertEqual((result["destination"], result["kept"], result["cleaned"]), ("scratch", False, True))
        verification = result["verification"]
        self.assertTrue(verification["ok"], verification)
        self.assertEqual((verification["integrity"], verification["tables"]), ("ok", 1))
        self.assertEqual(verification["db_sha256"], self.backup_db_sha)
        self.assertEqual(verification["archive_sha256"], sha(self.archive))
        self.assertEqual(verification["differences"], [])
        self.assertEqual(result["file_count"], 2)
        # Gone again, live byte for byte as before.
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),
                         ["db.sqlite3", "db.sqlite3-shm", "db.sqlite3-wal", "media"])
        self.assertEqual(fingerprint(self.root), before)
        # The first command is the mode probe, every other one names the scratch dir only.
        self.assertEqual(host.commands[0], "echoport-guard-mode")
        for command in host.commands[1:]:
            self.assertIn(result["scratch_path"], command)
            self.assertNotIn("systemctl", command)
            self.assertNotIn("--delete", command)
        self.assertEqual(host.commands[-2:], [f"rm -rf -- {result['scratch_path']}", f"test -e {result['scratch_path']}"])
        self.assertEqual(host.commands[1], f"mkdir {result['scratch_path']}")
        # Every connection uses the scratch config and key only.
        for argv in host.ssh_argv:
            self.assertIn(str(self.ssh_dir / "restore-scratch.config"), argv)
            self.assertIn(f"IdentityFile={self.ssh_dir / 'id_scratch'}", argv)
            for option in ("IdentitiesOnly=yes", "IdentityAgent=none", "ControlMaster=no", "ControlPath=none"):
                self.assertIn(option, argv)

    def test_an_empty_db_path_uses_the_runners_default(self) -> None:
        runner = render_runner(
            "marina_staging_backup.py.j2",
            marina_staging_backup_default_host="staging.wersdoerfer.de",
            marina_staging_backup_allowed_roots=[f"{self.root}/"],
            marina_staging_backup_default_db_path=str(self.live_db),
            marina_staging_backup_restore_owner=self.owner,
            marina_staging_backup_scratch_ssh_config=str(self.ssh_dir / "restore-scratch.config"),
            marina_staging_backup_scratch_ssh_key=str(self.ssh_dir / "id_scratch"),
            marina_staging_backup_live_ssh_key=str(self.ssh_dir / "id_live"),
        )
        self.runner = runner
        host = ScratchHost(self, self.root, self.policy_data, self.archive)
        rc, result = self.run_runner(host, self.context(ECHOPORT_RESTORE_SCRATCH_DB_PATH=""))
        self.assertEqual(rc, 0, result)
        self.assertTrue(result["verification"]["ok"])

    def test_keep_scratch_leaves_the_verified_copy(self) -> None:
        host = ScratchHost(self, self.root, self.policy_data, self.archive)
        rc, result = self.run_runner(host, self.context(ECHOPORT_RESTORE_KEEP_SCRATCH="1"))
        self.assertEqual(rc, 0, result)
        scratch = Path(result["scratch_path"])
        self.assertEqual((result["kept"], result["cleaned"]), (True, False))
        self.assertEqual(sha(scratch / "db.sqlite3"), self.backup_db_sha)
        self.assertEqual((scratch / "media" / "img" / "a.jpg").read_bytes(), b"backup photo")
        self.assertEqual(os.readlink(scratch / "media" / "rel-link"), "img/a.jpg")
        self.assertFalse((scratch / "media" / "only-live.txt").exists())
        self.assertEqual(stat.S_IMODE(scratch.stat().st_mode), 0o700)
        self.assertEqual((self.root / "media" / "only-live.txt").read_text(), "not in the backup")

    def test_a_tampered_copy_fails_verification_and_is_removed(self) -> None:
        host = ScratchHost(self, self.root, self.policy_data, self.archive)
        original = host.execute

        def tamper(decision: Any) -> subprocess.CompletedProcess:
            done = original(decision)
            mutation = decision.mutation
            if mutation is not None and mutation.op == "chown" and mutation.recursive:
                Path(mutation.paths[0], "extra.txt").write_text("not in the archive")
            return done

        host.execute = tamper
        rc, result = self.run_runner(host, self.context())
        self.assertEqual(rc, 1)
        self.assertFalse(result["success"])
        self.assertFalse(result["verification"]["ok"])
        self.assertIn("media/extra.txt", result["verification"]["differences"])
        self.assertTrue(result["cleaned"])
        self.assertFalse(any(p.name.startswith(".restore-scratch-") for p in self.root.iterdir()))

    def test_the_live_guard_stops_it_before_any_write(self) -> None:
        host = ScratchHost(self, self.root, self.policy_data, self.archive)
        live_policy = policy(self.policy_data)
        host.decide = lambda command: (host.commands.append(command), self._live(command, live_policy))[1]
        rc, result = self.run_runner(host, self.context())
        self.assertEqual(rc, 1)
        self.assertIn("echoport-guard-mode", result["error"])
        self.assertEqual(host.commands, ["echoport-guard-mode"])

    @staticmethod
    def _live(command: str, live_policy: Any) -> Any:
        try:
            return GUARD.check(command, live_policy)
        except GUARD.Refused:
            return None

    def test_missing_or_live_key_refuses_before_any_connection(self) -> None:
        for change in ("missing", "live", "mode"):
            with self.subTest(change=change):
                key = self.ssh_dir / "id_scratch"
                key.write_text("scratch key")
                key.chmod(0o600)
                if change == "missing":
                    key.unlink()
                elif change == "live":
                    key.write_text("live key")
                else:
                    key.chmod(0o644)
                host = ScratchHost(self, self.root, self.policy_data, self.archive)
                rc, result = self.run_runner(host, self.context())
                self.assertEqual(rc, 1)
                self.assertEqual(host.commands, [])
                self.assertIn("scratch SSH key", result["error"])

    def test_a_config_with_another_identity_refuses_before_connecting(self) -> None:
        for extra in (["identityfile /home/deploy/.ssh/id_ed25519"], ["certificatefile /x-cert.pub"]):
            with self.subTest(extra=extra):
                host = ScratchHost(self, self.root, self.policy_data, self.archive)
                host.extra_g = extra
                rc, result = self.run_runner(host, self.context())
                self.assertEqual(rc, 1)
                self.assertEqual(host.commands, [])
                self.assertIn("does not use the scratch key alone", result["error"])

    def test_an_existing_scratch_dir_is_neither_used_nor_removed(self) -> None:
        host = ScratchHost(self, self.root, self.policy_data, self.archive)
        fixed = self.runner.datetime(2026, 11, 11, 12, 0, 0, tzinfo=self.runner.timezone.utc)
        taken = self.root / ".restore-scratch-20261111T120000Z-42"
        taken.mkdir()
        (taken / "other-run.txt").write_text("someone else's")

        class Frozen(self.runner.datetime):  # type: ignore[name-defined, misc]
            @classmethod
            def now(cls, tz=None):  # noqa: ANN001, ANN206
                return fixed

        with mock.patch.object(self.runner, "datetime", Frozen):
            rc, result = self.run_runner(host, self.context())
        self.assertEqual(rc, 1)
        self.assertFalse(result["cleaned"])
        self.assertEqual((taken / "other-run.txt").read_text(), "someone else's")

    def test_a_malformed_manifest_still_reports(self) -> None:
        stage = self.base / "bad"
        stage.mkdir()
        (stage / "manifest.json").write_text(json.dumps({"database": "x", "files": [1]}))
        bad = self.base / "bad.tar.gz"
        with tarfile.open(bad, "w:gz") as tar:
            tar.add(stage / "manifest.json", arcname="manifest.json")
        host = ScratchHost(self, self.root, self.policy_data, bad)
        rc, result = self.run_runner(host, self.context(ECHOPORT_CHECKSUM=sha(bad)))
        self.assertEqual(rc, 1)
        self.assertIn("unexpected error: AttributeError", result["error"])

    def test_a_refused_work_dir_reports_a_scratch_result(self) -> None:
        host = ScratchHost(self, self.root, self.policy_data, self.archive)
        with (
            mock.patch.object(self.runner, "read_config_file", return_value=self.context()),
            mock.patch.object(self.runner.subprocess, "run", side_effect=host.run),
            mock.patch.object(self.runner, "create_run_dir", side_effect=RuntimeError("not on the work mount")),
            contextlib.redirect_stdout(io.StringIO()) as out,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(self.runner.main(), 1)
        results = [line for line in out.getvalue().splitlines() if "ECHOPORT_RESULT:" in line]
        self.assertEqual(len(results), 1)
        result = json.loads(json.loads(results[0])["message"].split("ECHOPORT_RESULT:", 1)[1])
        self.assertEqual(result["destination"], "scratch")
        self.assertIn("cannot create the work directory: not on the work mount", result["error"])
        self.assertEqual(host.commands, [])

    def test_context_refusals(self) -> None:
        for overrides, reason in (
            ({"ECHOPORT_RESTORE_DESTINATION": "live"}, "ECHOPORT_RESTORE_DESTINATION=scratch"),
            ({"ECHOPORT_RESTORE_KEEP_SCRATCH": "yes"}, "must be 0 or 1"),
            ({"ECHOPORT_KEY": ""}, "needs ECHOPORT_RESTORE_SCRATCH_DB_PATH"),
            ({"ECHOPORT_RESTORE_SCRATCH_DB_PATH": "/home/other/db.sqlite3"}, "not below an allowed root"),
            ({"ECHOPORT_RESTORE_SCRATCH_DB_PATH": f"{self.root}/../x/db.sqlite3"}, "not a plain absolute path"),
            ({"ECHOPORT_CHECKSUM": "0" * 64}, "Checksum mismatch"),
            ({"ECHOPORT_RESTORE_ID": ""}, "numeric ECHOPORT_RESTORE_ID"),
            ({"ECHOPORT_RESTORE_ID": "4x"}, "numeric ECHOPORT_RESTORE_ID"),
        ):
            with self.subTest(overrides=overrides):
                host = ScratchHost(self, self.root, self.policy_data, self.archive)
                rc, result = self.run_runner(host, self.context(**overrides))
                self.assertEqual(rc, 1)
                self.assertIn(reason, result["error"])
                self.assertFalse(any(p.name.startswith(".restore-scratch-") for p in self.root.iterdir()))

    def test_layout(self) -> None:
        layout = self.runner.scratch_layout(
            f"{self.root}/data/db.sqlite3", [f"{self.root}/media", f"{self.root}/private/files"], "7",
            now=self.runner.datetime(2026, 11, 11, 12, 0, 0, tzinfo=self.runner.timezone.utc),
        )
        self.assertEqual(layout["scratch"], f"{self.root}/.restore-scratch-20261111T120000Z-7")
        self.assertEqual(layout["db_rel"], "data/db.sqlite3")
        self.assertEqual(layout["files"], [(f"{self.root}/media", "media"), (f"{self.root}/private/files", "private/files")])
        for db, files in (
            (f"{self.root}/db.sqlite3", [f"{self.root}/db.sqlite3"]),
            (f"{self.root}/media/db.sqlite3", [f"{self.root}/media"]),
            (f"{self.root}/.restore-scratch-20261111T120000Z/db.sqlite3", []),
            (f"{self.root}/db.sqlite3", ["/elsewhere/media"]),
        ):
            with self.subTest(db=db, files=files), self.assertRaises(self.runner.ScratchError):
                self.runner.scratch_layout(db, files, "1")


class PoisonedLiveFields(unittest.TestCase):
    """A scratch request reaching a runner's backup path (what an older runner
    runs for an action it does not know) fails before any service stop."""

    def test_marina_backup_with_poisoned_fields_stops_nothing(self) -> None:
        runner = render_runner(
            "marina_staging_backup.py.j2",
            marina_staging_backup_default_host="staging.wersdoerfer.de",
            marina_staging_backup_allowed_roots=["/home/marina/site/"],
        )
        staging = policy(STAGING_POLICY)
        sent: list[str] = []

        def ssh(host: str, user: str, cmd: str, check: bool = True) -> subprocess.CompletedProcess:
            sent.append(cmd)
            try:
                GUARD.check(cmd, staging, realpath=identity, lstat=absent)
            except GUARD.Refused:
                if check:
                    raise subprocess.CalledProcessError(1, cmd, "", "refused") from None
                return subprocess.CompletedProcess(cmd, 1, "", "refused")
            return subprocess.CompletedProcess(cmd, 0, cmd.split()[-1] + "\n", "")

        config = {"context": {"env": {
            "ECHOPORT_ACTION": "backup", "ECHOPORT_DB_PATH": POISON_DB, "ECHOPORT_SERVICE_NAME": POISON_UNIT,
            "ECHOPORT_BACKUP_FILES": "", "ECHOPORT_KEY_PREFIX": "marina-staging/x",
        }}}
        work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        with (
            mock.patch.object(runner, "read_config_file", return_value=config),
            mock.patch.object(runner, "ssh", side_effect=ssh),
            mock.patch.object(runner, "create_run_dir", side_effect=lambda prefix: Path(tempfile.mkdtemp(dir=work))),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(runner.main(), 1)
        self.assertEqual(sent, [f"readlink -f {POISON_DB}"])


if __name__ == "__main__":
    unittest.main()
