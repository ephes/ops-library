"""Contracts for the echoport_remote_command_guard forced-command allowlist.

Two layers:

- the guard itself: allowed command shapes, refusals, the exec hand-off;
- the remote runners: every Echoport runner that SSHes to production or
  staging is rendered from its template and driven through a full backup and
  a restore from that backup with the network faked out. Every command it
  would send is converted to what sshd hands the guard (SSH_ORIGINAL_COMMAND)
  and must be allowed by the policy for that host. A runner change that sends
  a new command therefore fails here before it fails on the pinned hosts.

The policies mirror ops-control's inventory (host_vars production/staging,
`echoport_remote_command_guard_policy`); ops-control checks its copy against
its register playbooks.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
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
GUARD_PATH = ROOT / "roles" / "echoport_remote_command_guard" / "files" / "echoport-remote-command-guard.py"
TEMPLATE_DIR = ROOT / "roles" / "echoport_backup" / "templates"

PRODUCTION_POLICY = {
    "postgres": {
        "dump_databases": ["homepage", "python-podcast"],
        "restore_databases": {},
        "temp_file_prefixes": ["homepage", "pp"],
    },
    "units": [],
    "private_media_paths": ["/home/python-podcast/site/private_media"],
    "path_roots": [],
}

STAGING_POLICY = {
    "postgres": {
        "dump_databases": ["homepage", "python-podcast"],
        "restore_databases": {"homepage": "homepage", "python-podcast": "python-podcast"},
        "temp_file_prefixes": ["homepage", "pp"],
    },
    "units": [
        "homepage",
        "homepage.service",
        "homepage-db-worker",
        "python-podcast",
        "python-podcast.service",
        "python-podcast-db-worker",
        "marina.service",
        "villakunterbunt-next.service",
        "villakunterbunt-django.service",
    ],
    "private_media_paths": [],
    "path_roots": [
        {"path": "/home/marina/site", "owner": "marina:marina"},
        {"path": "/home/villakunterbunt/data", "owner": "villakunterbunt:villakunterbunt"},
    ],
}

RSYNC_FLAGS = "-logDtpre.iLsfxCIvu"


def load_guard() -> types.ModuleType:
    loader_spec = importlib.util.spec_from_file_location("echoport_remote_command_guard", GUARD_PATH)
    assert loader_spec and loader_spec.loader
    module = importlib.util.module_from_spec(loader_spec)
    sys.modules[loader_spec.name] = module  # dataclasses look the module up
    loader_spec.loader.exec_module(module)
    return module


GUARD = load_guard()


def policy(data: dict) -> Any:
    return GUARD.Policy.from_dict(json.loads(json.dumps(data)))


def identity(path: str) -> str:
    return os.path.normpath(path)


class GuardAllowsRunnerShapes(unittest.TestCase):
    def setUp(self) -> None:
        self.production = policy(PRODUCTION_POLICY)
        self.staging = policy(STAGING_POLICY)

    def allowed(self, command: str, host: Any) -> Any:
        return GUARD.check(command, host, realpath=identity)

    def test_postgres_dump_and_restore(self) -> None:
        decision = self.allowed(
            "sudo -u postgres pg_dump --format=custom --file=/tmp/echoport_pp_dump_2026-10-15T02-00-00.dump "
            "--dbname=python-podcast",
            self.production,
        )
        self.assertEqual(decision.argv[:5], ["sudo", "-n", "-u", "postgres", "--"])
        self.assertEqual(decision.argv[5], "pg_dump")
        self.allowed("sudo -u postgres dropdb --if-exists --force homepage", self.staging)
        self.allowed("sudo -u postgres createdb --owner=homepage homepage", self.staging)
        self.allowed(
            "sudo -u postgres pg_restore --exit-on-error --dbname=homepage --no-owner --role=homepage "
            "/tmp/echoport_homepage_restore_20261015020000.dump",
            self.staging,
        )
        self.allowed("sudo -u postgres psql -d homepage -c 'SELECT 1'", self.staging)

    def test_tar_runs_with_umask(self) -> None:
        decision = self.allowed(
            "umask 077 && tar -C /home/python-podcast/site -czf "
            "/tmp/echoport-pp-private-media.Ab12Cd34/private_media.tar.gz -- private_media",
            self.production,
        )
        self.assertEqual(decision.umask, 0o077)
        self.assertEqual(decision.argv[0], "tar")

    def test_policy_rejects_unsafe_entries(self) -> None:
        for broken in (
            {"units": ["a b"]},
            {"path_roots": [{"path": "/", "owner": "root:root"}]},
            {"path_roots": [{"path": "/home/x/../y", "owner": "x:x"}]},
            {"path_roots": [{"path": "/home/x", "owner": "root"}]},
            {"postgres": {"dump_databases": ["db;id"]}},
            {"postgres": {"temp_file_prefixes": ["../x"]}},
            {"private_media_paths": ["/tmp"]},
        ):
            with self.subTest(policy=broken):
                with self.assertRaises(GUARD.Refused):
                    GUARD.Policy.from_dict(broken)


class GuardRefusals(unittest.TestCase):
    def setUp(self) -> None:
        self.production = policy(PRODUCTION_POLICY)
        self.staging = policy(STAGING_POLICY)

    def assertRefused(self, command: str, host: Any, realpath=identity) -> None:
        with self.assertRaises(GUARD.Refused, msg=command):
            GUARD.check(command, host, realpath=realpath)

    def test_arbitrary_commands(self) -> None:
        for command in (
            "id",
            "true",
            "bash",
            "/bin/sh",
            "sftp",
            "/usr/lib/openssh/sftp-server",
            "internal-sftp",
            "cat /etc/hostname",
            "sh -c id",
            "sudo -u root id",
            "sudo -u postgres psql -d homepage -c 'SELECT 2'",
            "sudo -u postgres psql -c 'SELECT 1'",
            "sudo -u postgres pg_dump --format=custom --file=/root/x.dump --dbname=homepage",
            "sudo -u postgres pg_dump --format=custom --file=/tmp/echoport_pp_dump_x.dump --dbname=postgres",
            "sudo -u postgres dropdb --if-exists --force postgres",
            "sudo -u postgres createdb --owner=postgres homepage",
            "systemctl stop ssh.service",
            "systemctl restart homepage.service",
            "rm -rf /srv",
            "rm -f /etc/hostname",
            "mktemp -d /tmp/x.XXXX",
            "test -e /home/marina/site; id",
            "test -e /home/marina/site && id",
            "readlink -f /etc",
            "scp -f /etc/hostname",
            "scp -t /root/notes.txt",
            "scp -t /home/marina/site/db.sqlite3",
            "scp -r -t /home/marina/site/",
            "rsync --server -logDtpre.iLsfxCIvu --delete . /etc/",
            "rsync --server --sender -logDtpre.iLsfxCIvu --safe-links . /root/",
            "rsync --server -logDtpre.iLsfxCIvu --delete --remove-source-files . /home/marina/site/media/",
            "rsync --server -logDtpre.iLsfxCIvu --delete . /home/marina/site/media",
            "chown root:root /home/marina/site/db.sqlite3",
            "chown -R villakunterbunt:villakunterbunt /home/marina/site/media",
            "mv /home/marina/site/x /etc/hostname",
            "mkdir -p /home/marina/siteevil",
            "mkdir -p /home/marina/site/../../../etc/x",
            "umask 077 && tar -C /etc -czf /tmp/echoport-pp-private-media.Ab12/private_media.tar.gz -- hostname",
            "umask 077 && tar -C /home/python-podcast/site -czf /tmp/x.tar.gz -- private_media",
            "test -e '/home/marina/site/a\nb'",
            "",
        ):
            with self.subTest(command=command):
                self.assertRefused(command, self.staging)
                self.assertRefused(command, self.production)

    def test_host_specific_rules(self) -> None:
        # production only dumps; staging has no private media.
        self.assertRefused("sudo -u postgres dropdb --if-exists --force homepage", self.production)
        self.assertRefused("systemctl stop homepage.service", self.production)
        self.assertRefused("mktemp -d /tmp/echoport-pp-private-media.XXXXXXXX", self.staging)
        self.assertRefused("du -sb -- /home/python-podcast/site/private_media", self.staging)
        self.assertRefused("scp -t /tmp/echoport_homepage_dump_x.dump", self.staging)
        self.assertRefused("scp -f /tmp/echoport_homepage_restore_x.dump", self.production)

    def test_symlink_escape_is_refused(self) -> None:
        def escaping(path: str) -> str:
            return "/etc/hostname" if path.startswith("/home/marina/site/link") else os.path.normpath(path)

        for command in (
            "scp -f /home/marina/site/link",
            "scp -t /home/marina/site/link/x.tmp",
            "chown -R marina:marina /home/marina/site/link",
            "rsync --server -logDtpre.iLsfxCIvu --delete . /home/marina/site/link/",
        ):
            with self.subTest(command=command):
                self.assertRefused(command, self.staging, realpath=escaping)


class GuardMain(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.policy_file = self.tmp / "policy.json"
        self.policy_file.write_text(json.dumps(STAGING_POLICY))

    def run_main(self, command: str | None) -> tuple[int, mock.Mock]:
        env = {"SSH_CLIENT": "100.93.155.101 50000 22", "PATH": "/evil"}
        if command is not None:
            env["SSH_ORIGINAL_COMMAND"] = command
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(GUARD.os, "execvp") as execvp,
            mock.patch.object(GUARD, "_log"),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            rc = GUARD.main(["guard", str(self.policy_file)])
            self.path_at_exec = os.environ.get("PATH")
        return rc, execvp

    def test_interactive_session_is_refused(self) -> None:
        rc, execvp = self.run_main(None)
        self.assertEqual(rc, 1)
        execvp.assert_not_called()

    def test_refused_command_is_not_executed(self) -> None:
        rc, execvp = self.run_main("id")
        self.assertEqual(rc, 1)
        execvp.assert_not_called()

    def test_allowed_command_is_executed_without_shell(self) -> None:
        rc, execvp = self.run_main("systemctl start marina.service")
        execvp.assert_called_once_with("systemctl", ["systemctl", "start", "marina.service"])
        self.assertEqual(self.path_at_exec, GUARD.SAFE_PATH)
        self.assertEqual(rc, 0)

    def test_broken_policy_refuses_everything(self) -> None:
        for broken in ("{not json", "[]", json.dumps({"units": ["a b"]})):
            with self.subTest(policy=broken):
                self.policy_file.write_text(broken)
                rc, execvp = self.run_main("systemctl start marina.service")
                self.assertEqual(rc, 1)
                execvp.assert_not_called()

    def test_check_policy_mode(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            for data in (PRODUCTION_POLICY, STAGING_POLICY):
                self.policy_file.write_text(json.dumps(data))
                self.assertEqual(GUARD.main(["guard", "--check-policy", str(self.policy_file)]), 0)
            for broken in ("{not json", "[]", json.dumps({"path_roots": [{"path": "/"}]})):
                self.policy_file.write_text(broken)
                self.assertEqual(GUARD.main(["guard", "--check-policy", str(self.policy_file)]), 1)


# --- Runner templates -------------------------------------------------------

def render_runner(template: str, **variables: Any) -> types.ModuleType:
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), undefined=StrictUndefined, autoescape=False)
    ansible_filters = FilterModule().filters()
    for name in ("to_json", "bool", "regex_replace"):
        env.filters[name] = ansible_filters[name]
    base: dict[str, Any] = {
        "echoport_backup_mc_install_path": "/usr/local/bin/mc",
        "echoport_backup_minio_alias": "minio",
        "echoport_backup_default_bucket": "backups",
        "echoport_backup_temp_dir": "/tmp/echoport-guard-test",
    }
    base.update(variables)
    source = env.get_template(template).render(**base)
    module = types.ModuleType(template.replace(".py.j2", "_guard_test"))
    module.__file__ = str(TEMPLATE_DIR / template)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


class RecordingHosts:
    """Plays production/staging and MinIO; records what sshd would see per host."""

    def __init__(self, work: Path) -> None:
        self.work = work
        self.commands: list[tuple[str, str]] = []
        self.store: dict[str, Path] = {}
        self.last_key: str | None = None

    def record(self, host: str, command: str) -> None:
        self.commands.append((host, command))

    def ssh(self, host: str, user: str, cmd: str, check: bool = True) -> subprocess.CompletedProcess:
        self.assert_root(user)
        self.record(host, cmd)
        args = shlex.split(cmd) if not cmd.startswith("umask ") else []
        stdout = ""
        if cmd.startswith("readlink -f "):
            stdout = args[2] + "\n"
        elif cmd.startswith("systemctl show"):
            stdout = "loaded\n"
        elif cmd.startswith("mktemp -d "):
            stdout = "/tmp/echoport-pp-private-media.Ab12Cd34\n"
        elif cmd.startswith("sh -c 'if test -L"):
            stdout = "present\n"
        elif cmd.startswith("du -sb"):
            stdout = "4096\t/home/python-podcast/site/private_media\n"
        return subprocess.CompletedProcess(cmd, 0, stdout, "")

    @staticmethod
    def assert_root(user: str) -> None:
        assert user == "root", user

    def scp_from_remote(self, host: str, user: str, remote: str, local: str) -> None:
        self.record(host, f"scp -f {remote}")
        target = Path(local)
        if remote.endswith(".dump"):
            target.write_bytes(b"PGDMP fake dump")
        elif remote.endswith(".tar.gz"):
            with tempfile.TemporaryDirectory() as tmp:
                tree = Path(tmp) / "private_media"
                tree.mkdir()
                (tree / "voice.wav").write_bytes(b"RIFF")
                with tarfile.open(target, "w:gz") as tar:
                    tar.add(tree, arcname="private_media")
        else:
            target.write_bytes(b"SQLite format 3\0")

    def scp_to_remote(self, host: str, user: str, local: str, remote: str) -> None:
        self.record(host, f"scp -t {remote}")

    def rsync_from_remote(self, host: str, user: str, remote: str, local: str) -> None:
        self.record(host, f"rsync --server --sender {RSYNC_FLAGS} --safe-links . {remote}/")
        Path(local).mkdir(parents=True, exist_ok=True)
        (Path(local) / "file.txt").write_text("data")

    def rsync_to_remote(self, host: str, user: str, local: str, remote: str) -> None:
        self.record(host, f"rsync --server {RSYNC_FLAGS} --delete . {remote}/")

    def run(self, args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        if isinstance(args, str):
            raise AssertionError(f"unexpected shell command in runner: {args}")
        if args[0] == "sqlite3":
            if args[2].startswith(".backup"):
                clean = args[2].split("'")[1]
                shutil.copy(args[1], clean)
                return subprocess.CompletedProcess(args, 0, "", "")
            return subprocess.CompletedProcess(args, 0, "ok\n", "")
        if args[0] == "pg_restore":
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[1] == "cp" and args[2].startswith("minio/"):
            shutil.copy(self.store[args[2]], args[3])
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[1] == "cp":
            stored = self.work / f"upload-{len(self.store)}.tar.gz"
            shutil.copy(args[2], stored)
            self.store[args[3]] = stored
            self.last_key = args[3]
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[1] == "stat":
            return subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(f"unexpected local command: {args}")

    @contextlib.contextmanager
    def installed(self, runner: types.ModuleType):
        patches = [
            mock.patch.object(runner, "ssh", side_effect=self.ssh),
            mock.patch.object(runner, "scp_from_remote", side_effect=self.scp_from_remote),
            mock.patch.object(runner, "scp_to_remote", side_effect=self.scp_to_remote),
            mock.patch.object(runner.subprocess, "run", side_effect=self.run),
            mock.patch.object(runner, "TEMP_DIR", str(self.work)),
        ]
        for name in ("rsync_from_remote", "rsync_to_remote"):
            if hasattr(runner, name):
                patches.append(mock.patch.object(runner, name, side_effect=getattr(self, name)))
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            out = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            yield out


def sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


class RunnerCommandsAreAllowlisted(unittest.TestCase):
    POLICIES = {"wersdoerfer.de": PRODUCTION_POLICY, "staging.wersdoerfer.de": STAGING_POLICY}

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.policies = {host: policy(data) for host, data in self.POLICIES.items()}

    def assert_all_allowed(self, hosts: RecordingHosts, expected_hosts: set[str]) -> None:
        self.assertTrue(hosts.commands, "runner sent no remote commands")
        self.assertEqual({host for host, _ in hosts.commands}, expected_hosts)
        for host, command in hosts.commands:
            with self.subTest(host=host, command=command):
                GUARD.check(command, self.policies[host], realpath=identity)

    def backup_then_restore(self, runner, backup, restore) -> tuple[RecordingHosts, RecordingHosts]:
        backup_hosts = RecordingHosts(self.tmp)
        with backup_hosts.installed(runner):
            self.assertEqual(backup(), 0)
        assert backup_hosts.last_key is not None
        archive = backup_hosts.store[backup_hosts.last_key]
        key = backup_hosts.last_key.split("/", 2)[2]
        restore_hosts = RecordingHosts(self.tmp)
        restore_hosts.store = backup_hosts.store
        with restore_hosts.installed(runner):
            self.assertEqual(restore(key, sha256(archive)), 0)
        return backup_hosts, restore_hosts

    def test_production_db_runners(self) -> None:
        cases = [
            ("homepage_production_db_backup.py.j2", {
                "homepage_prod_db_backup_db_name": "homepage",
                "homepage_prod_db_backup_db_user": "homepage",
                "homepage_prod_db_backup_service_name": "homepage.service",
            }),
            ("python_podcast_production_db_backup.py.j2", {
                "pp_prod_db_backup_db_name": "python-podcast",
                "pp_prod_db_backup_db_user": "python-podcast",
                "pp_prod_db_backup_service_name": "python-podcast.service",
            }),
        ]
        for template, variables in cases:
            with self.subTest(template=template):
                runner = render_runner(template, **variables)
                backup_hosts, restore_hosts = self.backup_then_restore(
                    runner,
                    lambda: runner.backup(bucket="backups", key_prefix="t/run", timestamp="2026-10-15T02-00-00"),
                    lambda key, checksum: runner.restore(bucket="backups", key=key, expected_checksum=checksum),
                )
                self.assert_all_allowed(backup_hosts, {"wersdoerfer.de"})
                self.assert_all_allowed(restore_hosts, {"staging.wersdoerfer.de"})

    def test_staging_db_runners(self) -> None:
        cases = [
            ("homepage_staging_backup.py.j2", {
                "homepage_staging_backup_default_host": "staging.wersdoerfer.de",
                "homepage_staging_backup_db_name": "homepage",
                "homepage_staging_backup_db_user": "homepage",
                "homepage_staging_backup_service_name": "homepage",
            }),
            ("python_podcast_staging_backup.py.j2", {
                "pp_staging_backup_default_host": "staging.wersdoerfer.de",
                "pp_staging_backup_db_name": "python-podcast",
                "pp_staging_backup_db_user": "python-podcast",
                "pp_staging_backup_service_name": "python-podcast",
            }),
        ]
        for template, variables in cases:
            with self.subTest(template=template):
                runner = render_runner(template, **variables)
                backup_hosts, restore_hosts = self.backup_then_restore(
                    runner,
                    lambda: runner.backup(bucket="backups", key_prefix="t/run", timestamp="2026-10-15T02-00-00"),
                    lambda key, checksum: runner.restore(bucket="backups", key=key, expected_checksum=checksum),
                )
                self.assert_all_allowed(backup_hosts, {"staging.wersdoerfer.de"})
                self.assert_all_allowed(restore_hosts, {"staging.wersdoerfer.de"})

    def test_marina_runner(self) -> None:
        runner = render_runner(
            "marina_staging_backup.py.j2",
            marina_staging_backup_default_host="staging.wersdoerfer.de",
            marina_staging_backup_remote_user="root",
            marina_staging_backup_default_db_path="/home/marina/site/db.sqlite3",
            marina_staging_backup_service_name="marina.service",
            marina_staging_backup_restore_owner="marina:marina",
            marina_staging_backup_allowed_roots=["/home/marina/site/"],
        )
        common = dict(
            remote_host="staging.wersdoerfer.de", remote_user="root",
            db_path="/home/marina/site/db.sqlite3", backup_files=["/home/marina/site/media"],
            service_name="marina.service",
        )
        backup_hosts, restore_hosts = self.backup_then_restore(
            runner,
            lambda: runner.backup(**common, bucket="backups", key_prefix="t/run", timestamp="2026-10-15T02-00-00"),
            lambda key, checksum: runner.restore(
                **common, restore_owner="marina:marina", bucket="backups", key=key, expected_checksum=checksum,
            ),
        )
        self.assert_all_allowed(backup_hosts, {"staging.wersdoerfer.de"})
        self.assert_all_allowed(restore_hosts, {"staging.wersdoerfer.de"})
        sent = [command for _, command in restore_hosts.commands]
        self.assertTrue(any(command.startswith("rsync --server") for command in sent))
        self.assertTrue(any(command.startswith("chown -R marina:marina") for command in sent))

    def test_villakunterbunt_runner(self) -> None:
        runner = render_runner(
            "villakunterbunt_staging_backup.py.j2",
            villakunterbunt_staging_backup_default_host="staging.wersdoerfer.de",
            villakunterbunt_staging_backup_remote_user="root",
            villakunterbunt_staging_backup_default_db_path="/home/villakunterbunt/data/db.sqlite3",
            villakunterbunt_staging_backup_service_names=[
                "villakunterbunt-next.service", "villakunterbunt-django.service",
            ],
            villakunterbunt_staging_backup_restore_owner="villakunterbunt:villakunterbunt",
            villakunterbunt_staging_backup_files=[
                "/home/villakunterbunt/data/media", "/home/villakunterbunt/data/private_media",
            ],
            villakunterbunt_staging_backup_allowed_roots=["/home/villakunterbunt/data/"],
        )
        common = dict(
            remote_host="staging.wersdoerfer.de", remote_user="root",
            db_path="/home/villakunterbunt/data/db.sqlite3",
            backup_files=["/home/villakunterbunt/data/media", "/home/villakunterbunt/data/private_media"],
            service_names=["villakunterbunt-next.service", "villakunterbunt-django.service"],
        )
        backup_hosts, restore_hosts = self.backup_then_restore(
            runner,
            lambda: runner.backup(**common, bucket="backups", key_prefix="t/run", timestamp="2026-10-15T02-00-00"),
            lambda key, checksum: runner.restore(
                **common, restore_owner="villakunterbunt:villakunterbunt", bucket="backups", key=key,
                expected_checksum=checksum,
            ),
        )
        self.assert_all_allowed(backup_hosts, {"staging.wersdoerfer.de"})
        self.assert_all_allowed(restore_hosts, {"staging.wersdoerfer.de"})


class RunnersUseClassicScp(unittest.TestCase):
    """The guard can only check scp paths with the classic protocol (-O)."""

    TEMPLATES = (
        "homepage_production_db_backup.py.j2",
        "python_podcast_production_db_backup.py.j2",
        "homepage_staging_backup.py.j2",
        "python_podcast_staging_backup.py.j2",
        "marina_staging_backup.py.j2",
        "villakunterbunt_staging_backup.py.j2",
    )

    def test_scp_helpers_pass_dash_O(self) -> None:
        for template in self.TEMPLATES:
            with self.subTest(template=template):
                runner = render_runner(template)
                seen: list[str] = []

                def fake_run(cmd, **kwargs):
                    seen.append(cmd)
                    return subprocess.CompletedProcess(cmd, 0, "", "")

                with (
                    mock.patch.object(runner.subprocess, "run", side_effect=fake_run),
                    contextlib.redirect_stderr(io.StringIO()),
                ):
                    runner.scp_from_remote("staging.wersdoerfer.de", "root", "/tmp/a.dump", "/tmp/b")
                    runner.scp_to_remote("staging.wersdoerfer.de", "root", "/tmp/b", "/tmp/a.dump")
                self.assertEqual(len(seen), 2)
                for cmd in seen:
                    self.assertTrue(cmd.startswith("scp -O "), cmd)


if __name__ == "__main__":
    unittest.main()
