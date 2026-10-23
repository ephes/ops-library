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
import grp
import importlib.util
import io
import json
import os
import pwd
import re
import secrets
import shlex
import shutil
import stat
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
# Race regressions of the root-run mutations, shared with the Rust guard (tests/mutations.rs).
RACES_PATH = ROOT / "rust" / "echoport-command-guard" / "parity" / "races.json"
TEMPLATE_DIR = ROOT / "roles" / "echoport_backup" / "templates"

PRODUCTION_POLICY = {
    "postgres": {
        "dump_databases": ["homepage", "python-podcast"],
        "restore_databases": {},
        "temp_file_prefixes": ["homepage", "pp"],
    },
    "units": ["gotosocial"],
    "private_media_paths": ["/home/python-podcast/site/private_media"],
    "path_roots": [{"path": "/var/lib/gotosocial", "owner": "gotosocial:gotosocial"}],
    "read_files": ["/etc/gotosocial/config.yaml"],
    "sqlite_snapshots": [
        {
            "database": "/var/lib/gotosocial/sqlite.db",
            "owner": "gotosocial:gotosocial",
            "temp_dir": "/var/tmp/gotosocial-echoport.XXXXXX",
        }
    ],
    "ready_urls": ["http://127.0.0.1:10070/readyz"],
}

STAGING_POLICY = {
    "postgres": {
        "dump_databases": ["homepage", "python-podcast", "django-chat"],
        "restore_databases": {"homepage": "homepage", "python-podcast": "python-podcast"},
        "temp_file_prefixes": ["homepage", "pp"],
        "scratch_restore_prefixes": ["django_chat_restore"],
    },
    "temp_dirs": ["/var/tmp/django-chat-db-restore.XXXXXXXX"],
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

# What sshd hands the guard for each rsync client call the runners make
# (client options -> server command without the path). Derived by running
# rsync 3.2.7 (Ubuntu 24.04, macmini) and 3.5.0 (Debian 13) with a recording
# -e program; both send the same. A runner with other options fails here
# until its server command is derived and allowed in the guard.
RSYNC_CLIENT_TO_SERVER = {
    ("-a", "--safe-links"): "rsync --server --sender -logDtpre.iLsfxCIvu --safe-links .",
    ("-a", "--no-D"): "rsync --server -logtpre.iLsfxCIvu .",
    ("-a", "--no-D", "--delete"): "rsync --server -logtpre.iLsfxCIvu --delete .",
}
RSYNC_DOWNLOAD = RSYNC_CLIENT_TO_SERVER[("-a", "--safe-links")]
RSYNC_UPLOAD_DELETE = RSYNC_CLIENT_TO_SERVER[("-a", "--no-D", "--delete")]


def rsync_server_command(argv: list[str]) -> tuple[str, str, bool]:
    """(host, SSH_ORIGINAL_COMMAND, is_download) for a runner's rsync client argv."""
    e = argv.index("-e")
    options = tuple(argv[1:e])
    source, target = argv[e + 2:]
    download = ":" in source
    user_host, path = (source if download else target).split(":", 1)
    assert options in RSYNC_CLIENT_TO_SERVER, f"rsync client options {options} have no derived server command"
    return user_host.split("@", 1)[1], f"{RSYNC_CLIENT_TO_SERVER[options]} {path}", download


def fake_stat(mode: int, nlink: int = 1, uid: int | None = None) -> os.stat_result:
    """An lstat result; owned by the guard's own user (root on the hosts) by default."""
    return os.stat_result((mode, 1, 1, nlink, os.geteuid() if uid is None else uid, 0, 0, 0, 0, 0))


def lstat_absent(path: str) -> os.stat_result:
    raise FileNotFoundError(path)


def lstat_runner_view(path: str) -> os.stat_result:
    """The hosts as the runners leave them: their mktemp dirs exist, nothing else."""
    if re.fullmatch(r"/var/tmp/(gotosocial-echoport|django-chat-db-restore)\.[A-Za-z0-9]+", path) or re.fullmatch(
        r"/tmp/echoport-pp-private-media\.[A-Za-z0-9]+", path
    ):
        return fake_stat(stat.S_IFDIR | 0o700, nlink=2)
    raise FileNotFoundError(path)


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

    def test_public_schema_owner_after_createdb(self) -> None:
        for database in ("homepage", "python-podcast"):
            with self.subTest(database=database):
                command = (
                    f"sudo -u postgres psql -X -v ON_ERROR_STOP=1 -d {database} "
                    f"-c 'ALTER SCHEMA public OWNER TO \"{database}\"'"
                )
                decision = self.allowed(command, self.staging)
                self.assertEqual(
                    decision.argv,
                    ["sudo", "-n", "-u", "postgres", "--", "psql", "-X", "-v", "ON_ERROR_STOP=1",
                     "-d", database, "-c", f'ALTER SCHEMA public OWNER TO "{database}"'],
                )

    def test_tar_runs_with_umask(self) -> None:
        command = (
            "umask 077 && tar -C /home/python-podcast/site -czf "
            "/tmp/echoport-pp-private-media.Ab12Cd34/private_media.tar.gz -- private_media"
        )
        decision = GUARD.check(command, self.production, realpath=identity, lstat=lstat_runner_view)
        self.assertEqual(decision.umask, 0o077)
        self.assertEqual(decision.argv[0], "tar")
        # Not into a directory someone else made (or opened up) under that name.
        for directory in (
            fake_stat(stat.S_IFDIR | 0o700, nlink=2, uid=os.geteuid() + 1),
            fake_stat(stat.S_IFDIR | 0o777, nlink=2),
            fake_stat(stat.S_IFLNK | 0o777),
        ):
            for refused in (command, "scp -f /tmp/echoport-pp-private-media.Ab12Cd34/private_media.tar.gz"):
                with self.subTest(directory=directory, command=refused):
                    with self.assertRaises(GUARD.Refused):
                        GUARD.check(refused, self.production, realpath=identity,
                                    lstat=lambda p, st=directory: st if not p.endswith(".gz") else lstat_absent(p))
        with self.assertRaises(GUARD.Refused):
            GUARD.check(command, self.production, realpath=identity, lstat=lambda p: (
                fake_stat(stat.S_IFLNK | 0o777) if p.endswith(".gz") else lstat_runner_view(p)))

    def test_uploads_run_as_the_target_owner(self) -> None:
        for command, host, user in (
            ("scp -t /home/marina/site/db.sqlite3.tmp", self.staging, "marina"),
            ("scp -t /home/villakunterbunt/data/db.sqlite3.tmp", self.staging, "villakunterbunt"),
            ("scp -t /tmp/echoport_homepage_restore_20261015.dump", self.staging, "postgres"),
            (f"{RSYNC_UPLOAD_DELETE} /home/marina/site/media/", self.staging, "marina"),
            ("scp -t /var/lib/gotosocial/sqlite.db.restore-tmp", self.production, "gotosocial"),
            (f"{RSYNC_UPLOAD_DELETE} /var/lib/gotosocial/storage/", self.production, "gotosocial"),
            ("mkdir -p /home/marina/site/media", self.staging, "marina"),
        ):
            with self.subTest(command=command):
                decision = self.allowed(command, host)
                self.assertEqual(decision.argv, ["runuser", "-u", user, "--", *shlex.split(command)])
        for command, host in (
            ("scp -f /home/marina/site/db.sqlite3", self.staging),
            (f"{RSYNC_DOWNLOAD} /home/marina/site/media/", self.staging),
        ):
            with self.subTest(command=command):
                self.assertEqual(self.allowed(command, host).argv, shlex.split(command))

    def test_exact_rsync_commands(self) -> None:
        for server in RSYNC_CLIENT_TO_SERVER.values():
            with self.subTest(server=server):
                self.allowed(f"{server} /home/marina/site/media/", self.staging)

    def test_django_chat_shapes(self) -> None:
        tmp = "/var/tmp/django-chat-db-restore.Ab12Cd34"
        for command in (
            "runuser -u postgres -- pg_dump --format=custom --dbname=django-chat",
            "runuser -u postgres -- psql -X -v ON_ERROR_STOP=1 -qAt -d django-chat -c 'SHOW server_version;'",
            "runuser -u postgres -- psql -X -v ON_ERROR_STOP=1 -qAt -d postgres "
            "-c \"SELECT 1 FROM pg_database WHERE datname = 'django_chat_restore_42';\"",
            "runuser -u postgres -- psql -X -v ON_ERROR_STOP=1 -qAt -d django_chat_restore_42 "
            "-c 'SELECT count(*) FROM public.auth_user;'",
            "runuser -u postgres -- createdb django_chat_restore_42",
            "mktemp -d /var/tmp/django-chat-db-restore.XXXXXXXX",
            f"sha256sum {tmp}/django-chat.dump",
            f"rm -rf -- {tmp}",
        ):
            with self.subTest(command=command):
                GUARD.check(command, self.staging, realpath=identity, lstat=lstat_runner_view)
        upload = self.allowed(f"umask 077 && cat > {tmp}/django-chat.dump", self.staging)
        self.assertEqual((upload.argv, upload.umask), (["cat"], 0o077))
        self.assertEqual((upload.stdout.directory, upload.stdout.name), (tmp, "django-chat.dump"))
        restore = self.allowed(
            "runuser -u postgres -- pg_restore --no-owner --no-privileges --exit-on-error "
            f"--dbname=django_chat_restore_42 < {tmp}/django-chat.dump",
            self.staging,
        )
        self.assertEqual(restore.argv[-1], "--dbname=django_chat_restore_42")
        self.assertEqual((restore.stdin.directory, restore.stdin.name, restore.stdin.owners), (tmp, "django-chat.dump", ()))

    def test_gotosocial_shapes(self) -> None:
        tmp = "/var/tmp/gotosocial-echoport.Ab12Cd"
        for command in (
            "test -f /var/lib/gotosocial/sqlite.db",
            "mktemp -d /var/tmp/gotosocial-echoport.XXXXXX",
            f"chown gotosocial:gotosocial {tmp}",
            f"runuser -u gotosocial -- sqlite3 /var/lib/gotosocial/sqlite.db \".backup '{tmp}/sqlite.db'\"",
            # The runner waits for a committing writer and retries into a new file.
            f"runuser -u gotosocial -- sqlite3 /var/lib/gotosocial/sqlite.db '.timeout 30000' \".backup '{tmp}/sqlite.db'\"",
            f"runuser -u gotosocial -- sqlite3 /var/lib/gotosocial/sqlite.db '.timeout 30000' \".backup '{tmp}/retry2-sqlite.db'\"",
            f"runuser -u gotosocial -- sqlite3 {tmp}/sqlite.db 'PRAGMA integrity_check;'",
            f"runuser -u gotosocial -- sqlite3 {tmp}/retry2-sqlite.db 'PRAGMA integrity_check;'",
            "scp -f /etc/gotosocial/config.yaml",
            "scp -f /var/lib/gotosocial/.ops-domain-layout",
            f"{RSYNC_DOWNLOAD} /var/lib/gotosocial/storage/",
            f"rm -rf -- {tmp}",
            "systemctl stop gotosocial",
            "mv /var/lib/gotosocial/sqlite.db /var/lib/gotosocial/sqlite.db.pre-restore-20261015T020000Z",
            "scp -t /var/lib/gotosocial/sqlite.db.restore-tmp",
            "mkdir -p /var/lib/gotosocial/storage",
            f"{RSYNC_UPLOAD_DELETE} /var/lib/gotosocial/storage/",
            "chown -R gotosocial:gotosocial /var/lib/gotosocial/storage",
            "chmod 0600 /var/lib/gotosocial/sqlite.db",
            "chmod 0700 /var/lib/gotosocial/storage",
            "curl -fsS -o /dev/null http://127.0.0.1:10070/readyz",
        ):
            with self.subTest(command=command):
                GUARD.check(command, self.production, realpath=identity, lstat=lstat_runner_view)
        read = GUARD.check(f"cat {tmp}/sqlite.db", self.production, realpath=identity, lstat=lstat_runner_view)
        self.assertEqual(read.argv, ["cat"])
        self.assertEqual((read.stdin.directory, read.stdin.name, read.stdin.owners), (tmp, "sqlite.db", ("gotosocial",)))

    def test_root_changes_are_made_by_the_guard(self) -> None:
        """chmod, chown, mv and rm -f of side files run nothing: perform() makes them."""
        tmp = "/var/tmp/gotosocial-echoport.Ab12Cd"
        db = "/var/lib/gotosocial/sqlite.db"
        for command, host, mutation in (
            ("chmod 0600 /var/lib/gotosocial/sqlite.db", self.production,
             GUARD.Mutation("chmod", [db], mode=0o600, user="gotosocial")),
            ("chmod 0700 /home/marina/site/media", self.staging,
             GUARD.Mutation("chmod", ["/home/marina/site/media"], mode=0o700, user="marina")),
            ("chown marina:marina /home/marina/site/db.sqlite3", self.staging,
             GUARD.Mutation("chown", ["/home/marina/site/db.sqlite3"], owner="marina:marina")),
            ("chown -R gotosocial:gotosocial /var/lib/gotosocial/storage", self.production,
             GUARD.Mutation("chown", ["/var/lib/gotosocial/storage"], owner="gotosocial:gotosocial", recursive=True)),
            (f"chown gotosocial:gotosocial {tmp}", self.production,
             GUARD.Mutation("chown", [tmp], owner="gotosocial:gotosocial", private=True)),
            ("mv /home/marina/site/db.sqlite3.tmp /home/marina/site/db.sqlite3", self.staging,
             GUARD.Mutation("mv", ["/home/marina/site/db.sqlite3.tmp", "/home/marina/site/db.sqlite3"], replace=True,
                            user="marina")),
            (f"mv {db} {db}.pre-restore-20261015T020000Z", self.production,
             GUARD.Mutation("mv", [db, f"{db}.pre-restore-20261015T020000Z"], user="gotosocial")),
            (f"mv {db}.restore-tmp {db}", self.production,
             GUARD.Mutation("mv", [f"{db}.restore-tmp", db], user="gotosocial")),
            ("rm -f /home/marina/site/db.sqlite3-wal /home/marina/site/db.sqlite3-shm", self.staging,
             GUARD.Mutation("rm", ["/home/marina/site/db.sqlite3-wal", "/home/marina/site/db.sqlite3-shm"],
                            user="marina")),
        ):
            with self.subTest(command=command):
                decision = GUARD.check(command, host, realpath=identity, lstat=lstat_runner_view)
                self.assertEqual(decision, GUARD.Decision(argv=[], mutation=mutation))
        # Everything else still runs a tool and changes nothing itself.
        self.assertIsNone(self.allowed("rm -f /tmp/echoport_pp_dump_x.dump", self.production).mutation)
        self.assertIsNone(self.allowed("mkdir -p /home/marina/site/media", self.staging).mutation)

    def test_policy_rejects_unsafe_entries(self) -> None:
        for broken in (
            {"units": ["a b"]},
            {"path_roots": [{"path": "/", "owner": "root:root"}]},
            {"path_roots": [{"path": "/home/x/../y", "owner": "x:x"}]},
            {"path_roots": [{"path": "/home/x", "owner": "root"}]},
            {"path_roots": [{"path": "/home/x", "owner": "root:root"}]},
            {"postgres": {"dump_databases": ["db;id"]}},
            {"postgres": {"temp_file_prefixes": ["../x"]}},
            {"private_media_paths": ["/tmp"]},
            {"temp_dirs": ["/root/x.XXXXXX"]},
            {"temp_dirs": ["/var/tmp/x.XXX"]},
            {"postgres": {"scratch_restore_prefixes": ["x;y"]}},
            {"sqlite_snapshots": [{"database": "/var/lib/x/db", "owner": "root:root", "temp_dir": "/var/tmp/x.XXXXXX"}]},
            {"sqlite_snapshots": [{"database": "/var/lib/x/db", "owner": "x:x", "temp_dir": "/srv/x.XXXXXX"}]},
            {"read_files": ["/etc"]},
            {"ready_urls": ["http://example.org/readyz"]},
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

    def test_public_schema_owner_only_in_its_exact_shape(self) -> None:
        prefix = "sudo -u postgres psql -X -v ON_ERROR_STOP=1 -d"
        good_sql = 'ALTER SCHEMA public OWNER TO "homepage"'
        # The exact command is allowed on staging only (production restores nothing).
        self.assertRefused(f"{prefix} homepage -c {shlex.quote(good_sql)}", self.production)
        for sql in (
            'ALTER SCHEMA public OWNER TO "python-podcast"',  # another restore database's role
            'ALTER SCHEMA public OWNER TO "postgres"',
            "ALTER SCHEMA public OWNER TO homepage",  # unquoted role
            "ALTER SCHEMA public OWNER TO 'homepage'",
            'ALTER SCHEMA public OWNER TO "homepage";',
            'ALTER SCHEMA public OWNER TO "homepage" ',
            ' ALTER SCHEMA public OWNER TO "homepage"',
            'ALTER SCHEMA  public OWNER TO "homepage"',
            'alter schema public owner to "homepage"',
            'ALTER SCHEMA "public" OWNER TO "homepage"',
            'ALTER SCHEMA pg_catalog OWNER TO "homepage"',
            'ALTER SCHEMA other OWNER TO "homepage"',
            'ALTER DATABASE homepage OWNER TO "homepage"',
            'ALTER SCHEMA public OWNER TO "homepage"; DROP TABLE x',
            'ALTER SCHEMA public OWNER TO "homepage"; ALTER ROLE homepage SUPERUSER',
            'ALTER SCHEMA public OWNER TO "Homepage"',
            'ALTER SCHEMA public OWNER TO "homepage""',
            'ALTER SCHEMA public OWNER TO ""homepage""',
            'ALTER SCHEMA public OWNER TO "homepage"\\gexec',
            "\\! id",
            "SELECT 1",
            "",
        ):
            with self.subTest(sql=sql):
                self.assertRefused(f"{prefix} homepage -c {shlex.quote(sql)}", self.staging)
        q = shlex.quote(good_sql)
        for command in (
            # databases outside restore_databases (dump-only, scratch, system)
            f"{prefix} django-chat -c {shlex.quote(chr(39) + 'x')}",
            f"{prefix} django-chat -c {shlex.quote('ALTER SCHEMA public OWNER TO \"django-chat\"')}",
            f"{prefix} postgres -c {shlex.quote('ALTER SCHEMA public OWNER TO \"postgres\"')}",
            f"{prefix} template1 -c {shlex.quote('ALTER SCHEMA public OWNER TO \"homepage\"')}",
            f"{prefix} django_chat_restore_42 -c {q}",
            # other or extra arguments
            f"sudo -u postgres psql -v ON_ERROR_STOP=1 -X -d homepage -c {q}",
            f"sudo -u postgres psql -X -v ON_ERROR_STOP=0 -d homepage -c {q}",
            f"sudo -u postgres psql -X -v ON_ERROR_STOP=1 -qAt -d homepage -c {q}",
            f"sudo -u postgres psql -X -v ON_ERROR_STOP=1 --dbname=homepage -c {q}",
            f"sudo -u postgres psql -X -v ON_ERROR_STOP=1 -d homepage --command {q}",
            f"sudo -u postgres psql -X -v ON_ERROR_STOP=1 -d homepage -f {q}",
            f"sudo -u postgres psql -X -v ON_ERROR_STOP=1 -d homepage -c {q} -c {q}",
            f"sudo -u postgres psql -X -v ON_ERROR_STOP=1 -d homepage -c {q} -o /tmp/x",
            f"sudo -u postgres psql -X -v ON_ERROR_STOP=1 -h evil -d homepage -c {q}",
            f"sudo -u postgres psql -X -X -v ON_ERROR_STOP=1 -d homepage -c {q}",
            f"sudo -u postgres psql -v ON_ERROR_STOP=1 -d homepage -c {q}",
            f"sudo -u postgres psql -X -d homepage -c {q}",
            f"sudo -u postgres psql -d homepage -c {q}",
            f"sudo -u postgres psql -X -v ON_ERROR_STOP=1 -d homepage {q}",
            f"sudo -u postgres psql -X -v ON_ERROR_STOP=1 -d homepage -c {q}; id",
            f"sudo -u postgres psql -X -v ON_ERROR_STOP=1 -d homepage -c {q} && id",
            # not as postgres
            f"sudo -u homepage psql -X -v ON_ERROR_STOP=1 -d homepage -c {q}",
            f"sudo -u root psql -X -v ON_ERROR_STOP=1 -d homepage -c {q}",
            f"psql -X -v ON_ERROR_STOP=1 -d homepage -c {q}",
        ):
            with self.subTest(command=command):
                self.assertRefused(command, self.staging)

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
            f"{RSYNC_UPLOAD_DELETE} /home/marina/site/link/",
            "mv /home/marina/site/link/a /home/marina/site/b",
            "chmod 0600 /home/marina/site/link/a",
        ):
            with self.subTest(command=command):
                self.assertRefused(command, self.staging, realpath=escaping)


    def test_mutations_name_their_root_as_written(self) -> None:
        """perform() walks the path as written, so it must lie inside the root before resolving."""

        def into_the_root(path: str) -> str:
            # /home/marina/alias is a symlink to the root.
            return os.path.normpath(path.replace("/home/marina/alias", "/home/marina/site", 1))

        for command, path in (
            ("chmod 0600 /home/marina/alias/db.sqlite3", "/home/marina/alias/db.sqlite3"),
            ("chown marina:marina /home/marina/alias/db.sqlite3", "/home/marina/alias/db.sqlite3"),
            ("chown -R marina:marina /home/marina/alias/media", "/home/marina/alias/media"),
            ("mv /home/marina/alias/a /home/marina/site/b", "/home/marina/alias/a"),
            ("mv /home/marina/site/a.tmp /home/marina/alias/a", "/home/marina/alias/a"),
            ("rm -f /home/marina/alias/db-wal /home/marina/alias/db-shm", "/home/marina/alias/db-wal"),
            ("chmod 0600 /home/marina/site/media/", "/home/marina/site/media/"),
            ("chown -R marina:marina /home/marina/site/", "/home/marina/site/"),
        ):
            with self.subTest(command=command):
                with self.assertRaises(GUARD.Refused) as caught:
                    GUARD.check(command, self.staging, realpath=into_the_root, lstat=lstat_absent)
                self.assertEqual(str(caught.exception), f"path not inside its root as written: {path!r}")
        # Reading and uploading through such a path is unchanged.
        GUARD.check("test -e /home/marina/alias/db.sqlite3", self.staging, realpath=into_the_root)
        GUARD.check("chmod 0600 /home/marina/site/media", self.staging, realpath=into_the_root)

    def test_rsync_options_must_match_exactly(self) -> None:
        media = "/home/marina/site/media/"
        for server_args in (
            "--server --sender -logDtpLre.iLsfxCIvu --safe-links .",  # -L: follow symlinks out of the root
            "--server --sender -logDtpre.iLsfxCIvu .",  # without --safe-links
            "--server --sender -logDtpre.iLsfxCIvu --safe-links --copy-unsafe-links .",
            "--server -logDtpre.iLsfxCIvu .",  # upload with D: device files
            "--server -logDtpre.iLsfxCIvu --delete .",
            "--server -logKtpre.iLsfxCIvu --delete .",  # -K: keep dirlinks
            "--server -logtpre.iLsfxCIvu --delete --remove-source-files .",
            "--server -logtpre.iLsfxCIvu --delete-excluded .",
            "--server --sender -logtpre.iLsfxCIvu --delete .",
        ):
            with self.subTest(args=server_args):
                self.assertRefused(f"rsync {server_args} {media}", self.staging)

    def test_scp_refuses_targets_that_are_not_plain_files(self) -> None:
        kinds = {
            "symlink": fake_stat(stat.S_IFLNK | 0o777),
            "device": fake_stat(stat.S_IFCHR | 0o600),
            "block device": fake_stat(stat.S_IFBLK | 0o600),
            "fifo": fake_stat(stat.S_IFIFO | 0o600),
            "directory": fake_stat(stat.S_IFDIR | 0o700, nlink=2),
            "hard link": fake_stat(stat.S_IFREG | 0o600, nlink=2),
        }
        for kind, st in kinds.items():
            for command, host in (
                ("scp -t /home/marina/site/db.sqlite3.tmp", self.staging),
                ("scp -f /home/marina/site/db.sqlite3", self.staging),
                ("scp -t /tmp/echoport_homepage_restore_x.dump", self.staging),
                ("scp -f /tmp/echoport_homepage_dump_x.dump", self.production),
                ("scp -f /etc/gotosocial/config.yaml", self.production),
            ):
                with self.subTest(kind=kind, command=command):
                    with self.assertRaises(GUARD.Refused):
                        GUARD.check(command, host, realpath=identity, lstat=lambda _p, st=st: st)
        plain = fake_stat(stat.S_IFREG | 0o600)
        GUARD.check("scp -t /home/marina/site/db.sqlite3.tmp", self.staging, realpath=identity, lstat=lambda _p: plain)
        # Dump files must be postgres's (pg_dump writes them; pg_restore reads them).
        for command, host in (
            ("scp -f /tmp/echoport_homepage_dump_x.dump", self.production),
            ("scp -t /tmp/echoport_homepage_restore_x.dump", self.staging),
        ):
            with self.subTest(command=command):
                with self.assertRaises(GUARD.Refused):
                    GUARD.check(command, host, realpath=identity,
                                lstat=lambda _p: fake_stat(stat.S_IFREG | 0o600, uid=os.geteuid() + 12345))
        GUARD.check("scp -t /home/marina/site/db.sqlite3.tmp", self.staging, realpath=identity, lstat=lstat_absent)

    def test_scp_against_a_real_tree(self) -> None:
        tree = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, tree, ignore_errors=True)
        root = tree / "site"
        root.mkdir()
        outside = tree / "outside.txt"
        outside.write_text("x")
        (root / "plain.tmp").write_text("x")
        (root / "link.tmp").symlink_to(outside)
        (root / "dirlink").symlink_to(tree)
        os.link(outside, root / "hard.tmp")
        os.mkfifo(root / "fifo.tmp")
        host = policy({"path_roots": [{"path": str(root), "owner": "marina:marina"}]})
        GUARD.check(f"scp -t {root}/plain.tmp", host)
        GUARD.check(f"scp -t {root}/new.tmp", host)
        for name in ("link.tmp", "hard.tmp", "fifo.tmp", "dirlink/outside.tmp"):
            with self.subTest(name=name):
                with self.assertRaises(GUARD.Refused):
                    GUARD.check(f"scp -t {root}/{name}", host)

    def test_mv_only_onto_new_names_within_one_root(self) -> None:
        exists = fake_stat(stat.S_IFREG | 0o600)
        GUARD.check("mv /home/marina/site/a /home/marina/site/b", self.staging, realpath=identity, lstat=lstat_absent)
        GUARD.check("mv /home/marina/site/a.tmp /home/marina/site/a", self.staging, realpath=identity,
                    lstat=lambda _p: exists)
        for command, lstat in (
            ("mv /home/marina/site/a /home/marina/site/b", lambda _p: exists),
            ("mv /home/marina/site/a /home/villakunterbunt/data/a", lstat_absent),
            ("mv /home/marina/site/a /tmp/a", lstat_absent),
        ):
            with self.subTest(command=command):
                with self.assertRaises(GUARD.Refused):
                    GUARD.check(command, self.staging, realpath=identity, lstat=lstat)

    def test_django_chat_refusals(self) -> None:
        tmp = "/var/tmp/django-chat-db-restore.Ab12Cd34"
        psql = "runuser -u postgres -- psql -X -v ON_ERROR_STOP=1 -qAt -d"
        for command in (
            f"{psql} django-chat -c 'DROP TABLE auth_user;'",
            f"{psql} django-chat -c 'SELECT count(*) FROM public.auth_user;'",
            f"{psql} postgres -c 'SHOW server_version;'",
            f"{psql} django_chat_restore_42 -c 'SELECT count(*) FROM public.auth_user; DROP TABLE x;'",
            f"{psql} homepage -c \"SELECT 1 FROM pg_database WHERE datname = 'django_chat_restore_1';\"",
            "runuser -u postgres -- pg_dump --format=custom --dbname=postgres",
            "runuser -u postgres -- createdb django-chat",
            "runuser -u postgres -- createdb django_chat_restore_x",
            "runuser -u postgres -- pg_restore --no-owner --no-privileges --exit-on-error --dbname=django-chat "
            f"< {tmp}/django-chat.dump",
            "runuser -u postgres -- pg_restore --no-owner --no-privileges --exit-on-error "
            "--dbname=django_chat_restore_1 < /tmp/echoport_homepage_restore_x.dump",
            "runuser -u postgres -- pg_restore --no-owner --no-privileges --exit-on-error --dbname=django_chat_restore_1",
            "sudo -u postgres pg_restore --no-owner --no-privileges --exit-on-error "
            f"--dbname=django_chat_restore_1 < {tmp}/django-chat.dump",
            f"systemctl start marina.service < {tmp}/django-chat.dump",
            "runuser -u root -- id",
            "runuser -u postgres -- id",
            f"umask 077 && cat > {tmp}/notes.txt",
            "umask 077 && cat > /var/tmp/other.Ab12Cd34/django-chat.dump",
            f"umask 077 && cat > {tmp}/sub/django-chat.dump",
            f"umask 022 && cat > {tmp}/django-chat.dump",
            f"cat {tmp}/django-chat.dump",
            "cat /etc/hostname",
            "sha256sum /etc/hostname",
            "mktemp -d /var/tmp/other.XXXXXXXX",
            "rm -rf -- /var/tmp",
            "rm -rf -- /var/tmp/django-chat-db-restore.Ab12",
        ):
            with self.subTest(command=command):
                self.assertRefused(command, self.staging)
        # sha256sum only in a private directory of the guard's user.
        for directory in (
            fake_stat(stat.S_IFDIR | 0o755, nlink=2),
            fake_stat(stat.S_IFDIR | 0o700, nlink=2, uid=os.geteuid() + 1),
            fake_stat(stat.S_IFLNK | 0o777),
        ):
            with self.subTest(directory=directory):
                with self.assertRaises(GUARD.Refused):
                    GUARD.check(f"sha256sum {tmp}/django-chat.dump", self.staging, realpath=identity,
                                lstat=lambda path, st=directory: st if path == tmp else lstat_absent(path))

    def test_gotosocial_refusals(self) -> None:
        tmp = "/var/tmp/gotosocial-echoport.Ab12Cd"
        as_gts = "runuser -u gotosocial -- sqlite3"
        for command in (
            f"{as_gts} /var/lib/gotosocial/sqlite.db '.shell id'",
            f"{as_gts} /var/lib/gotosocial/sqlite.db \".backup '/tmp/x.db'\"",
            f"{as_gts} /var/lib/gotosocial/sqlite.db \".backup '{tmp}/sqlite.db' extra\"",
            f"{as_gts} /var/lib/gotosocial/sqlite.db '.timeout 0' \".backup '{tmp}/sqlite.db'\"",
            f"{as_gts} /var/lib/gotosocial/sqlite.db '.timeout 30000; .shell id' \".backup '{tmp}/sqlite.db'\"",
            f"{as_gts} /var/lib/gotosocial/sqlite.db '.shell id' \".backup '{tmp}/sqlite.db'\"",
            f"{as_gts} /var/lib/gotosocial/sqlite.db '.timeout 30000' \".backup '/tmp/x.db'\"",
            f"{as_gts} /var/lib/gotosocial/sqlite.db \".backup '{tmp}/sqlite.db'\" '.timeout 30000'",
            f"{as_gts} {tmp}/sqlite.db '.timeout 30000' 'PRAGMA integrity_check;'",
            f"{as_gts} /var/lib/gotosocial/sqlite.db '.timeout 30000' '.timeout 30000' \".backup '{tmp}/sqlite.db'\"",
            f"{as_gts} /var/lib/gotosocial/sqlite.db 'PRAGMA integrity_check;'",
            f"{as_gts} {tmp}/sqlite.db 'DELETE FROM accounts;'",
            f"runuser -u marina -- sqlite3 {tmp}/sqlite.db 'PRAGMA integrity_check;'",
            "runuser -u gotosocial -- id",
            f"chown root:root {tmp}",
            "chown gotosocial:gotosocial /var/tmp/django-chat-db-restore.Ab12Cd34",
            "chown root:root /var/lib/gotosocial/sqlite.db",
            "chmod 4755 /var/lib/gotosocial/sqlite.db",
            "chmod 0777 /var/lib/gotosocial/storage",
            "chmod 0600 /etc/hostname",
            "chmod -R 0700 /var/lib/gotosocial",
            "curl -fsS -o /dev/null http://127.0.0.1:9999/readyz",
            "curl -fsS -o /root/x http://127.0.0.1:10070/readyz",
            "curl -fsS http://127.0.0.1:10070/readyz",
            "scp -f /etc/gotosocial/other.yaml",
            "scp -t /etc/gotosocial/config.yaml",
            "scp -t /var/lib/gotosocial/sqlite.db",
            f"scp -f {tmp}/sqlite.db",
            "cat /var/lib/gotosocial/sqlite.db",
            f"cat {tmp}/sub/sqlite.db",
            "test -x /var/lib/gotosocial/sqlite.db",
            "mktemp -d /var/tmp/gotosocial-echoport.XXX",
            "systemctl restart gotosocial",
        ):
            with self.subTest(command=command):
                with self.assertRaises(GUARD.Refused, msg=command):
                    GUARD.check(command, self.production, realpath=identity, lstat=lstat_runner_view)
        # A snapshot temp dir that is not a directory is not handed over.
        with self.assertRaises(GUARD.Refused):
            GUARD.check(f"chown gotosocial:gotosocial {tmp}", self.production, realpath=identity, lstat=lstat_absent)
        # Staging has none of it.
        self.assertRefused("curl -fsS -o /dev/null http://127.0.0.1:10070/readyz", self.staging)
        self.assertRefused("mktemp -d /var/tmp/gotosocial-echoport.XXXXXX", self.staging)


class GuardRedirects(unittest.TestCase):
    """The files the guard opens itself for `< file`, `> file` and `cat`."""

    def setUp(self) -> None:
        # Like the runners' mktemp -d: a 0700 directory of the guard's user.
        self.dir = Path(f"/tmp/echoport-guard-test.{secrets.token_hex(4)}")
        self.dir.mkdir(mode=0o700)
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def redirect(self, name: str, owners: tuple[str, ...] = ()) -> Any:
        return GUARD.Redirect(str(self.dir), name, owners)

    def test_create_is_exclusive_and_private(self) -> None:
        fd = GUARD.open_redirect(self.redirect("a.dump"), create=True)
        os.write(fd, b"dump")
        os.close(fd)
        self.assertEqual(stat.S_IMODE((self.dir / "a.dump").stat().st_mode), 0o600)
        with self.assertRaises(OSError):
            GUARD.open_redirect(self.redirect("a.dump"), create=True)

    def test_read_plain_file(self) -> None:
        (self.dir / "a.dump").write_bytes(b"dump")
        fd = GUARD.open_redirect(self.redirect("a.dump"), create=False)
        self.assertEqual(os.read(fd, 10), b"dump")
        os.close(fd)

    def test_refuses_links_and_special_files(self) -> None:
        outside = self.dir.parent / f"{self.dir.name}-outside"
        outside.write_text("x")
        self.addCleanup(outside.unlink)
        (self.dir / "link").symlink_to(outside)
        os.link(outside, self.dir / "hard")
        os.mkfifo(self.dir / "fifo")
        (self.dir / "sub").mkdir()
        for name, create in (("link", False), ("link", True), ("hard", False), ("fifo", False), ("sub", False)):
            with self.subTest(name=name, create=create):
                with self.assertRaises((GUARD.Refused, OSError)):
                    fd = GUARD.open_redirect(self.redirect(name), create=create)
                    os.close(fd)
        self.assertEqual(outside.read_text(), "x")

    def test_refuses_a_shared_or_foreign_directory(self) -> None:
        (self.dir / "a.dump").write_bytes(b"dump")
        self.dir.chmod(0o755)
        with self.assertRaises(GUARD.Refused):
            GUARD.open_redirect(self.redirect("a.dump"), create=False)
        self.dir.chmod(0o700)
        with mock.patch.object(GUARD.os, "geteuid", return_value=os.geteuid() + 1):
            with self.assertRaises(GUARD.Refused):
                GUARD.open_redirect(self.redirect("a.dump"), create=False)

    def test_refuses_a_symlinked_directory(self) -> None:
        link = self.dir.parent / f"{self.dir.name}-link"
        link.symlink_to(self.dir)
        self.addCleanup(link.unlink)
        (self.dir / "a.dump").write_bytes(b"dump")
        with self.assertRaises(OSError):
            GUARD.open_redirect(GUARD.Redirect(str(link), "a.dump"), create=False)


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
            mock.patch.object(GUARD, "_log") as self.log,
            contextlib.redirect_stderr(io.StringIO()) as self.stderr,
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

    def test_allowed_mutation_is_made_without_exec(self) -> None:
        base = Path(os.path.realpath(self.tmp))
        root = base / "root"
        root.mkdir()
        (root / "db").write_text("db")
        (root / "db").chmod(0o644)
        outside = base / "secret"
        outside.write_text("secret")
        outside.chmod(0o644)
        me = pwd.getpwuid(os.geteuid()).pw_name
        group = grp.getgrgid(os.getegid()).gr_name
        self.policy_file.write_text(json.dumps({"path_roots": [{"path": str(root), "owner": f"{me}:{group}"}]}))
        command = f"chmod 0600 {root}/db"
        rc, execvp = self.run_main(command)
        self.assertEqual(rc, 0)
        execvp.assert_not_called()
        self.assertEqual(stat.S_IMODE((root / "db").stat().st_mode), 0o600)
        self.assertEqual(self.log.call_args.args[1], f"allowed from 100.93.155.101: {command!r}")
        self.assertEqual(self.stderr.getvalue(), "")
        # A symlink put there after check(): refused and logged, nothing changed outside.
        (root / "db").unlink()
        (root / "db").symlink_to(outside)
        checked = GUARD.Decision(argv=[], mutation=GUARD.Mutation("chmod", [f"{root}/db"], mode=0o600))
        with mock.patch.object(GUARD, "check", return_value=checked):
            rc, execvp = self.run_main(command)
        self.assertEqual(rc, 1)
        execvp.assert_not_called()
        self.assertEqual(self.stderr.getvalue(), "echoport-remote-command-guard: command not allowed\n")
        self.assertEqual(self.log.call_args.args[1],
                         f"refused from 100.93.155.101: chmod target is a symbolic link: '{root}/db': {command!r}")
        self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0o644)

    def test_mutations_drop_to_the_roots_owner_except_chown(self) -> None:
        """As root, chmod, mv and rm run as the root's owner; chown keeps root."""
        me = pwd.getpwuid(os.geteuid())
        state = {"uid": 0, "calls": []}

        def setuid(uid: int) -> None:
            state["calls"].append(("setuid", uid))
            state["uid"] = uid

        def performed(mutation: Any, hook: Any = None) -> None:
            state["calls"].append(("perform", mutation.op, state["uid"]))

        for mutation, dropped in (
            (GUARD.Mutation("chmod", ["/x/db"], mode=0o600, user=me.pw_name), True),
            (GUARD.Mutation("mv", ["/x/a", "/x/b"], user=me.pw_name), True),
            (GUARD.Mutation("rm", ["/x/a-wal", "/x/a-shm"], user=me.pw_name), True),
            (GUARD.Mutation("chown", ["/x/db"], owner=f"{me.pw_name}:x"), False),
        ):
            with self.subTest(op=mutation.op):
                state.update(uid=0, calls=[])
                with (
                    mock.patch.object(GUARD, "check", return_value=GUARD.Decision(argv=[], mutation=mutation)),
                    mock.patch.object(GUARD, "perform", side_effect=performed),
                    mock.patch.object(GUARD.os, "geteuid", side_effect=lambda: state["uid"]),
                    mock.patch.object(GUARD.os, "getuid", side_effect=lambda: state["uid"]),
                    mock.patch.object(GUARD.os, "setgroups", side_effect=lambda g: state["calls"].append(("setgroups", g))),
                    mock.patch.object(GUARD.os, "setgid", side_effect=lambda g: state["calls"].append(("setgid", g))),
                    mock.patch.object(GUARD.os, "setuid", side_effect=setuid),
                ):
                    rc, execvp = self.run_main("x")
                self.assertEqual(rc, 0)
                execvp.assert_not_called()
                expected = [("perform", mutation.op, me.pw_uid if dropped else 0)]
                if dropped:
                    expected = [("setgroups", [me.pw_gid]), ("setgid", me.pw_gid), ("setuid", me.pw_uid), *expected]
                self.assertEqual(state["calls"], expected)
        # An unknown owner, or root as the owner, refuses before anything is changed.
        for user, reason in (("no-such-user-h1", "unknown user: 'no-such-user-h1'"),
                             ("root", "will not run as root: 'root'")):
            with self.subTest(user=user):
                state.update(uid=0, calls=[])
                bad = GUARD.Mutation("chmod", ["/x/db"], mode=0o600, user=user)
                with (
                    mock.patch.object(GUARD, "check", return_value=GUARD.Decision(argv=[], mutation=bad)),
                    mock.patch.object(GUARD, "perform", side_effect=performed),
                    mock.patch.object(GUARD.os, "geteuid", side_effect=lambda: state["uid"]),
                    mock.patch.object(GUARD.os, "setuid", side_effect=setuid),
                ):
                    rc, _execvp = self.run_main("x")
                self.assertEqual(rc, 1)
                self.assertEqual(state["calls"], [])
                self.assertIn(reason, self.log.call_args.args[1])

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


class GuardMutationRaces(unittest.TestCase):
    """The race regressions of rust/echoport-command-guard/parity/races.json.

    The table is run by parity/races.py here and, as root on the hosts'
    distributions, in the Layer-2 containers; the Rust guard runs it too
    (tests/mutations.rs). A change between check() and perform(), or during
    perform()'s walk (its test hook), must never make the guard change, move
    or remove anything outside the root.
    """

    def test_scenarios(self) -> None:
        races = load_races_module()
        failures, skipped = races.run_all(GUARD, RACES_PATH)
        self.assertEqual(failures, [])
        if skipped:
            # Checked above: every scenario that ran passed.
            self.skipTest(f"skipped here: {', '.join(skipped)} (a chown needs a second group of the test user "
                          "or root; non-UTF-8 names need Linux)")


def load_races_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("echoport_guard_races", RACES_PATH.with_suffix(".py"))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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

    def rsync(self, argv: list[str]) -> None:
        """The runner's own rsync client call, as the server side sees it."""
        host, command, download = rsync_server_command(argv)
        self.record(host, command)
        if download:
            local = Path(argv[-1])
            local.mkdir(parents=True, exist_ok=True)
            (local / "file.txt").write_text("data")

    def run(self, args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        if isinstance(args, str) and args.startswith("rsync "):
            self.rsync(shlex.split(args))
            return subprocess.CompletedProcess(args, 0, "", "")
        if isinstance(args, str):
            raise AssertionError(f"unexpected shell command in runner: {args}")
        if args[0] == "sqlite3":
            if args[-1].startswith(".backup"):
                clean = args[-1].split("'")[1]
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

    def assert_all_allowed(self, hosts: Any, expected_hosts: set[str]) -> None:
        self.assertTrue(hosts.commands, "runner sent no remote commands")
        self.assertEqual({host for host, _ in hosts.commands}, expected_hosts)
        for host, command in hosts.commands:
            with self.subTest(host=host, command=command):
                GUARD.check(command, self.policies[host], realpath=identity, lstat=lstat_runner_view)

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
                # The fresh database's public schema goes to the app role
                # between createdb and pg_restore.
                db = runner.DB_NAME
                commands = [command for _, command in restore_hosts.commands]
                createdb = commands.index(f"sudo -u postgres createdb --owner={db} {db}")
                alter = commands.index(
                    f"sudo -u postgres psql -X -v ON_ERROR_STOP=1 -d {db} "
                    f"-c 'ALTER SCHEMA public OWNER TO \"{db}\"'"
                )
                pg_restore = next(i for i, c in enumerate(commands) if c.startswith("sudo -u postgres pg_restore"))
                self.assertEqual(alter, createdb + 1)
                self.assertLess(alter, pg_restore)

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
        self.assertIn(f"{RSYNC_DOWNLOAD} /home/marina/site/media/", [c for _, c in backup_hosts.commands])
        sent = [command for _, command in restore_hosts.commands]
        self.assertIn("rsync --server -logtpre.iLsfxCIvu . /home/marina/site/media/", sent)
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
        sent = [command for _, command in restore_hosts.commands]
        self.assertIn(f"{RSYNC_UPLOAD_DELETE} /home/villakunterbunt/data/media/", sent)

    def test_django_chat_runner(self) -> None:
        tests_dir = Path(__file__).resolve().parent
        loader_spec = importlib.util.spec_from_file_location(
            "django_chat_runner_contract", tests_dir / "test_django_chat_staging_db_backup.py"
        )
        assert loader_spec and loader_spec.loader
        contract = importlib.util.module_from_spec(loader_spec)
        loader_spec.loader.exec_module(contract)
        runner = contract.render_runner(self.tmp / "work")
        host = contract.FakeHosts(self.tmp)
        events: list[dict] = []
        with (
            mock.patch.object(runner, "run_cmd", host.run_cmd),
            mock.patch.object(runner, "ensure_binaries", lambda: None),
            mock.patch.object(runner, "_emit", events.append),
        ):
            self.assertEqual(runner.backup_flow({"ECHOPORT_KEY_PREFIX": "django-chat-staging-db/t1"}), 0, events)
            backup_calls = list(host.remote_calls)
            archive = host.stored[f"{contract.ALIAS}/backups/django-chat-staging-db/t1.tar.gz"]
            host.remote_calls.clear()
            cenv = {
                "ECHOPORT_RESTORE_ID": "42",
                "ECHOPORT_KEY": "django-chat-staging-db/t1.tar.gz",
                "ECHOPORT_CHECKSUM": sha256_bytes(archive),
            }
            self.assertEqual(runner.restore_flow(cenv), 0, events)
        self.policies[contract.HOST] = self.policies["staging.wersdoerfer.de"]
        for calls in (backup_calls, host.remote_calls):
            recorded = types.SimpleNamespace(commands=[(contract.HOST, c) for c in calls])
            self.assert_all_allowed(recorded, {contract.HOST})

    def test_gotosocial_runner(self) -> None:
        runner = render_runner(
            "gotosocial_backup.py.j2",
            gotosocial_backup_remote_host="wersdoerfer.de",
            gotosocial_backup_ready_url="http://127.0.0.1:10070/readyz",
            gotosocial_backup_target_name="gotosocial",
        )
        host = GoToSocialHost(self.tmp)
        with host.installed(runner):
            self.assertEqual(runner.backup("backups", "gotosocial/t1", "2026-10-15T01-25-00"), 0)
            backup = list(host.commands)
            host.commands.clear()
            archive = host.store["gotosocial/t1.tar.gz"]
            self.assertEqual(runner.restore("backups", "gotosocial/t1.tar.gz", sha256(archive)), 0)
        for recorded in (backup, host.commands):
            self.assert_all_allowed(types.SimpleNamespace(commands=recorded), {"wersdoerfer.de"})
        sent = [c for _, c in backup + host.commands]
        self.assertIn(f"{RSYNC_DOWNLOAD} /var/lib/gotosocial/storage/", sent)
        self.assertIn(f"{RSYNC_UPLOAD_DELETE} /var/lib/gotosocial/storage/", sent)
        self.assertTrue(any(c.startswith("cat /var/tmp/gotosocial-echoport.") for c in sent))
        self.assertTrue(any(c.startswith("mv /var/lib/gotosocial/storage ") for c in sent))


class GoToSocialHost:
    """Plays production for gotosocial_backup.py.j2 at the subprocess boundary."""

    TMP = "/var/tmp/gotosocial-echoport.Ab12Cd"
    LAYOUT = "fedi.example.org example.org\n"

    def __init__(self, work: Path) -> None:
        self.work = work
        self.commands: list[tuple[str, str]] = []
        self.store: dict[str, Path] = {}

    def ssh_line(self, line: str, kwargs: dict) -> subprocess.CompletedProcess:
        self.commands.append(("wersdoerfer.de", line))
        argv = shlex.split(line)
        stdout, rc = "", 0
        if argv[0] == "mktemp":
            stdout = self.TMP + "\n"
        elif argv[-1] == "PRAGMA integrity_check;":
            stdout = "ok\n"
        elif argv[0] == "cat":
            kwargs["stdout"].write(b"SQLite format 3\0")
        elif argv[:2] == ["test", "-e"] and argv[2].endswith(("-wal", "-shm")):
            rc = 1
        return subprocess.CompletedProcess(argv, rc, stdout if "stdout" not in kwargs else b"", "" if "stdout" not in kwargs else b"")

    def run(self, args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        assert isinstance(args, list), args
        if args[0] == "ssh":
            assert args[-2] == "root@wersdoerfer.de", args
            return self.ssh_line(args[-1], kwargs)
        if args[0] == "scp":
            assert args[1] == "-O", args
            source, target = args[-2], args[-1]
            if ":" in source:
                path = source.split(":", 1)[1]
                self.commands.append(("wersdoerfer.de", f"scp -f {path}"))
                Path(target).write_text(self.LAYOUT if path.endswith("domain-layout") else "host: x\n")
            else:
                self.commands.append(("wersdoerfer.de", f"scp -t {target.split(':', 1)[1]}"))
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[0] == "rsync":
            host, command, download = rsync_server_command(args)
            self.commands.append((host, command))
            if download:
                local = Path(args[-1])
                local.mkdir(parents=True, exist_ok=True)
                (local / "a.png").write_bytes(b"png")
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[0] == "sqlite3":
            return subprocess.CompletedProcess(args, 0, "ok\n" if "PRAGMA" in args[-1] else "1\n", "")
        if args[1] == "cp":
            source, target = args[-2], args[-1]
            if source.startswith("minio/"):
                shutil.copy(self.store[source.split("/", 2)[2]], target)
            else:
                stored = self.work / f"gts-{len(self.store)}.tar.gz"
                shutil.copy(source, stored)
                self.store[target.split("/", 2)[2]] = stored
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[1] == "stat":
            size = self.store[args[-1].split("/", 2)[2]].stat().st_size
            return subprocess.CompletedProcess(args, 0, json.dumps({"size": size}), "")
        raise AssertionError(f"unexpected local command: {args}")

    @contextlib.contextmanager
    def installed(self, runner: types.ModuleType):
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(runner.subprocess, "run", side_effect=self.run))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            yield


def sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


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
