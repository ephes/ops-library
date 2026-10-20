"""Backup archives on the host must be owner-only.

The backup roles wrote their archives with the default umask (0644), e.g.
``/opt/backups/traefik/*.tar.gz`` with ``acme.json`` inside; only
``minecraft_java_backup`` set 0600. Now:

- every ``archive`` task in ``roles/*_backup`` sets ``mode: "0600"``;
- every ``tar`` that writes an archive either runs under ``umask 077`` or is
  followed by a ``file`` task that sets the archive to 0600;
- every role that writes an archive into a backup root first tightens the
  archives already there (``find`` + ``file``, no ``chmod -R``), so archives
  from earlier runs are fixed by the next backup run;
- backup roots the roles create default to 0700, except where the PostgreSQL
  dump user has to traverse them (documented below).

The engine test runs ``traefik_backup`` on localhost against a backup root
that an earlier version left world-readable.
"""

from __future__ import annotations

import grp
import os
import pwd
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLES = ROOT / "roles"

ARCHIVE_MODULES = ("ansible.builtin.archive", "community.general.archive")
FILE = "ansible.builtin.file"
FIND = "ansible.builtin.find"
COMMANDS = ("ansible.builtin.command", "ansible.builtin.shell")
TAR_WRITE = re.compile(r"\btar\b[^\n]*?(-c[a-z]*f|-[a-z]*c[a-z]*f|--zstd -cf)")
SIMPLE_VAR = re.compile(r"\{\{ (\w+) \}\}")
ARCHIVE_PATTERNS = ["*.tar", "*.tar.*", "*.tgz"]

# role -> variable naming the directory its archives are written to
TIGHTENED_ROOTS = {
    "certbot_dns_backup": "certbot_dns_backup_root",
    "fastdeploy_backup": "fastdeploy_backup_root",
    "homeassistant_backup": "homeassistant_backup_root",
    "homelab_backup": "homelab_backup_root",
    "jellyfin_backup": "jellyfin_backup_root",
    "mail_backup": "mail_backup_destination",
    "mastodon_backup": "mastodon_backup_root",
    "metube_backup": "metube_backup_root",
    "minecraft_java_backup": "minecraft_java_backup_root",
    "minio_backup": "minio_backup_root",
    "navidrome_backup": "navidrome_backup_root",
    "nyxmon_backup": "nyxmon_backup_root",
    "paperless_backup": "paperless_backup_root",
    "snappymail_backup": "snappymail_backup_root",
    "tailscale_backup": "tailscale_backup_root",
    "takahe_backup": "takahe_backup_root",
    "traefik_backup": "traefik_backup_root",
    "unifi_backup": "unifi_backup_root",
    "vaultwarden_backup": "vaultwarden_backup_root",
    "wagtail_backup": "wagtail_backup_root",
    "work_app_backup": "work_app_backup_root",
}

# Roles that write archives only inside a private per-run directory, never
# into the backup root itself.
NO_ROOT_ARCHIVES = {
    # templates_c.tar.gz inside the 0700 per-run directory (set to 0600)
    "postfixadmin_backup",
}

# Roles whose backup root stays group-traversable: pg_dump runs as the
# postgres user and writes into the per-run directory below the root.
GROUP_TRAVERSABLE_ROOTS = {"fastdeploy_backup", "mail_backup", "paperless_backup"}


def role_defaults(role: str) -> dict:
    """The role's defaults merged over its ``*_shared`` role's defaults."""
    merged: dict = {}
    shared = ROLES / role.replace("_backup", "_shared") / "defaults" / "main.yml"
    for path in (shared, ROLES / role / "defaults" / "main.yml"):
        if path.exists():
            merged.update(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    return merged


def resolve(role: str, value: object) -> object:
    match = SIMPLE_VAR.fullmatch(str(value))
    if match is None:
        return value
    return role_defaults(role).get(match.group(1), value)


def task_lists(path: Path):
    """Yield every task list in a task file (top level and block bodies)."""

    def walk(tasks):
        yield tasks
        for task in tasks:
            if isinstance(task, dict):
                for key in ("block", "rescue", "always"):
                    if key in task:
                        yield from walk(task[key])

    tasks = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    yield from walk(tasks)


def backup_task_files():
    for path in sorted(ROLES.glob("*_backup/tasks/*.yml")):
        yield path.parts[-3], path


def writes_tar(task: dict) -> str | None:
    for module in COMMANDS:
        if module in task:
            arguments = task[module]
            text = arguments.get("cmd", "") if isinstance(arguments, dict) else arguments
            text = str(text).replace("\\\n", " ")
            if TAR_WRITE.search(text):
                return text
    return None


class ArchiveTaskModeTest(unittest.TestCase):
    def test_archive_modules_set_0600(self) -> None:
        seen = 0
        for role, path in backup_task_files():
            for tasks in task_lists(path):
                for task in tasks:
                    if not isinstance(task, dict):
                        continue
                    for module in ARCHIVE_MODULES:
                        if module in task:
                            seen += 1
                            with self.subTest(role=role, task=task.get("name")):
                                self.assertEqual(task[module].get("mode"), "0600")
        self.assertGreaterEqual(seen, 12)

    def test_tar_archives_are_made_owner_only(self) -> None:
        seen = 0
        for role, path in backup_task_files():
            for tasks in task_lists(path):
                for index, task in enumerate(tasks):
                    if not isinstance(task, dict):
                        continue
                    script = writes_tar(task)
                    if script is None:
                        continue
                    seen += 1
                    with self.subTest(role=role, task=task.get("name")):
                        if "umask 077" in script:
                            continue
                        restrict = [
                            later
                            for later in tasks[index + 1 :]
                            if isinstance(later, dict)
                            and isinstance(later.get(FILE), dict)
                            and "state" not in later[FILE]
                            and resolve(role, later[FILE].get("mode")) == "0600"
                        ]
                        self.assertTrue(restrict, f"{path}: no 0600 file task after tar")
        self.assertGreaterEqual(seen, 12)


class ExistingArchivesTightenedTest(unittest.TestCase):
    def test_every_role_writing_archives_is_covered(self) -> None:
        writing = set()
        for role, path in backup_task_files():
            for tasks in task_lists(path):
                for task in tasks:
                    if isinstance(task, dict) and (
                        any(module in task for module in ARCHIVE_MODULES) or writes_tar(task)
                    ):
                        writing.add(role)
        self.assertEqual(writing - NO_ROOT_ARCHIVES, set(TIGHTENED_ROOTS))

    def test_existing_archives_are_tightened_with_the_file_module(self) -> None:
        for role, root_var in TIGHTENED_ROOTS.items():
            with self.subTest(role=role):
                pairs = []
                for path in sorted((ROLES / role / "tasks").glob("*.yml")):
                    for tasks in task_lists(path):
                        for index, task in enumerate(tasks):
                            if not (isinstance(task, dict) and FIND in task):
                                continue
                            find = task[FIND]
                            if find.get("paths") != f"{{{{ {root_var} }}}}":
                                continue
                            if find.get("patterns") != ARCHIVE_PATTERNS:
                                continue
                            follower = tasks[index + 1]
                            pairs.append((task, follower))
                self.assertEqual(len(pairs), 1, pairs)
                find_task, file_task = pairs[0]
                self.assertEqual(find_task[FIND]["file_type"], "file")
                self.assertNotIn("recurse", find_task[FIND])
                register = find_task["register"]
                self.assertIn(FILE, file_task)
                self.assertEqual(file_task[FILE]["path"], "{{ item.path }}")
                self.assertEqual(resolve(role, file_task[FILE]["mode"]), "0600")
                self.assertIn(f"{register}.files", file_task["loop"])
                self.assertIn("rejectattr('mode', 'equalto'", file_task["loop"])

    def test_no_recursive_chmod(self) -> None:
        for role, path in backup_task_files():
            with self.subTest(path=str(path)):
                self.assertNotRegex(path.read_text(encoding="utf-8"), r"chmod\s+-R")


class BackupRootModeTest(unittest.TestCase):
    def test_backup_roots_default_to_0700(self) -> None:
        for role, root_var in TIGHTENED_ROOTS.items():
            if role in GROUP_TRAVERSABLE_ROOTS:
                continue
            with self.subTest(role=role):
                modes = []
                for path in sorted((ROLES / role / "tasks").glob("*.yml")):
                    for tasks in task_lists(path):
                        for task in tasks:
                            arguments = task.get(FILE) if isinstance(task, dict) else None
                            if not isinstance(arguments, dict):
                                continue
                            if arguments.get("state") != "directory":
                                continue
                            targets = [arguments.get("path")]
                            if arguments.get("path") == "{{ item }}":
                                targets = task.get("loop", [])
                            if f"{{{{ {root_var} }}}}" in targets:
                                modes.append(resolve(role, arguments.get("mode")))
                self.assertTrue(modes, f"{role} does not create {root_var}")
                self.assertEqual(set(modes), {"0700"})


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not on PATH")
class TraefikBackupArchiveModeEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.dynamic = self.base / "dynamic"
        self.dynamic.mkdir()
        (self.dynamic / "whoami.yml").write_text("http: {}\n")
        self.root = self.base / "backups" / "traefik"
        self.root.mkdir(parents=True)
        os.chmod(self.root, 0o755)
        self.old = self.root / "manual-20260101T000000.tar.gz"
        self.old.write_text("old archive")
        os.chmod(self.old, 0o644)
        self.other = self.root / "README.txt"
        self.other.write_text("not an archive")
        os.chmod(self.other, 0o644)

    def run_role(self, *extra: str) -> subprocess.CompletedProcess[str]:
        playbook = self.base / "play.yml"
        playbook.write_text(
            yaml.safe_dump(
                [
                    {
                        "hosts": "localhost",
                        "gather_facts": True,
                        "gather_subset": ["!all", "date_time"],
                        "vars": {
                            "traefik_backup_root": str(self.root),
                            "traefik_backup_dynamic_dir": str(self.dynamic),
                            "traefik_backup_owner": pwd.getpwuid(os.getuid()).pw_name,
                            "traefik_backup_group": grp.getgrgid(os.getgid()).gr_name,
                            "traefik_backup_fetch_local": False,
                            "traefik_backup_prefix": "test",
                        },
                        "roles": ["traefik_backup"],
                    }
                ]
            ),
            encoding="utf-8",
        )
        env = {
            **os.environ,
            "ANSIBLE_ROLES_PATH": str(ROOT / "roles"),
            "ANSIBLE_NOCOLOR": "1",
            "ANSIBLE_LOCALHOST_WARNING": "0",
            "ANSIBLE_INVENTORY_UNPARSED_WARNING": "0",
        }
        return subprocess.run(
            [
                "/bin/sh",
                "-c",
                'umask 022 && exec ansible-playbook -i localhost, -c local "$@"',
                "ansible-playbook",
                str(playbook),
                *extra,
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
        )

    @staticmethod
    def mode(path: Path) -> int:
        return stat.S_IMODE(path.stat().st_mode)

    def test_new_and_old_archives_end_up_0600(self) -> None:
        result = self.run_role()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        new = list(self.root.glob("test-*.tar.gz"))
        self.assertEqual(len(new), 1, new)
        self.assertEqual(self.mode(new[0]), 0o600)
        self.assertEqual(self.mode(self.old), 0o600)
        self.assertEqual(self.mode(self.other), 0o644)
        self.assertEqual(self.mode(self.root), 0o700)

    def test_tightening_is_idempotent(self) -> None:
        os.chmod(self.old, 0o600)
        result = self.run_role()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        header = "TASK [traefik_backup : Restrict backup archives to owner-only]"
        block = result.stdout.split(header, 1)[1].split("TASK [", 1)[0]
        self.assertNotIn("changed:", block)
        self.assertEqual(self.mode(self.old), 0o600)

    def test_check_mode_changes_nothing(self) -> None:
        result = self.run_role("--check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.mode(self.old), 0o644)
        self.assertFalse(list(self.root.glob("test-*.tar.gz")))


if __name__ == "__main__":
    unittest.main()
