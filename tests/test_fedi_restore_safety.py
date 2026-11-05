"""Safety contracts for the Mastodon and Takahe restore roles.

Both roles used to stop services with `failed_when: false`, drop the live
database, restore an unchecked dump without `--single-transaction` and
`rsync --delete` the media with no copy. These tests pin the safer order:
validate the dump, stop (fail closed), take safety copies, restore in one
transaction, and roll back with services left stopped. The shell snippets
that take and restore the safety copies run here against temp directories,
with stub binaries, so nothing touches a host or a database.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLES = ("mastodon", "takahe")


def load_tasks(svc: str) -> list[dict]:
    path = ROOT / "roles" / f"{svc}_restore" / "tasks" / "main.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def flatten(tasks: list[dict], sections: tuple[str, ...] = ("block", "rescue", "always")) -> list[dict]:
    flat: list[dict] = []
    for task in tasks:
        nested = False
        for section in ("block", "rescue", "always"):
            if section in task:
                nested = True
                if section in sections:
                    flat.extend(flatten(task[section], sections))
        if not nested:
            flat.append(task)
    return flat


def find(tasks: list[dict], name: str) -> dict:
    for task in tasks:
        if task.get("name") == name:
            return task
        for section in ("block", "rescue", "always"):
            for child in task.get(section, []):
                try:
                    return find([child], name)
                except KeyError:
                    pass
    raise KeyError(name)


def index_of(tasks: list[dict], name: str) -> int:
    for index, task in enumerate(tasks):
        if task.get("name") == name:
            return index
    raise AssertionError(f"task {name!r} not found")


def shell_cmd(task: dict) -> str:
    shell = task["ansible.builtin.shell"]
    return shell["cmd"] if isinstance(shell, dict) else shell


def write_stub(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text("#!/bin/bash\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class FediRestoreOrderTests(unittest.TestCase):
    def test_both_roles(self) -> None:
        for svc in ROLES:
            with self.subTest(role=svc):
                self.check_role(svc)

    def check_role(self, svc: str) -> None:
        tasks = load_tasks(svc)
        main = flatten(tasks, ("block",))
        Svc = svc.capitalize()

        validate = index_of(main, "Validate the database dump table of contents")
        stop = index_of(main, f"Stop {Svc} services before restore")
        confirm = index_of(main, f"Confirm {Svc} services are stopped")
        safety_dump = index_of(main, "Take safety dump of the live database")
        snapshot = index_of(main, "Snapshot media and config files")
        dropdb = index_of(main, f"Drop {Svc} database")
        restore = index_of(main, "Restore PostgreSQL dump")
        media = index_of(main, "Restore media directory")
        start = index_of(main, f"Start {Svc} services after restore")

        # Validation precedes the stop, the stop precedes the safety copies,
        # and every safety copy precedes the first destructive step.
        self.assertLess(validate, stop)
        self.assertLess(stop, confirm)
        self.assertLess(confirm, safety_dump)
        self.assertLess(safety_dump, dropdb)
        self.assertLess(snapshot, dropdb)
        self.assertLess(snapshot, media)
        self.assertLess(dropdb, restore)
        self.assertLess(restore, start)

        validation = shell_cmd(main[validate])
        self.assertIn("--list", validation)
        self.assertIn("TABLE DATA", validation)
        self.assertIn("--file=/dev/null", validation)

        # The media rsync must write new inodes so the hard-link snapshot
        # cannot be changed through a metadata-only update.
        self.assertIn("--ignore-times", main[media]["ansible.builtin.command"]["argv"])

        dump_argv = main[safety_dump]["ansible.builtin.command"]["argv"]
        self.assertIn("--format=custom", dump_argv)

        restore_argv = main[restore]["ansible.builtin.command"]["argv"]
        self.assertIn("'--single-transaction'", restore_argv)

        # No failure is swallowed on the way to and through the restore.
        for task in main:
            self.assertNotEqual(task.get("failed_when"), False, task.get("name"))
            self.assertNotIn("ignore_errors", task, task.get("name"))
        confirm_task = main[confirm]
        self.assertIn("not in ['inactive', 'failed']", confirm_task["failed_when"])

        # Rescue rolls back and never starts a service.
        block = find(tasks, f"Restore {Svc} with rollback")
        rescue_tasks = flatten(block["rescue"], ("block",))
        rescue_names = [task["name"] for task in rescue_tasks]
        self.assertIn("Roll back the database from the safety dump", rescue_names)
        self.assertIn("Roll back media and config files", rescue_names)
        for task in block["rescue"]:
            systemd = task.get("ansible.builtin.systemd")
            if systemd and "state" in systemd:
                self.assertEqual(systemd["state"], "stopped")
        db_rollback = shell_cmd(rescue_tasks[rescue_names.index("Roll back the database from the safety dump")])
        self.assertIn("--single-transaction", db_rollback)
        final = block["rescue"][-1]["ansible.builtin.fail"]["msg"]
        self.assertIn("Safety dump:", final)
        self.assertIn("Media snapshot:", final)
        self.assertIn("left stopped", final)

        guard = find(tasks, "Stop services and take safety copies")
        self.assertEqual(len(guard["rescue"]), 1)
        self.assertIn("ansible.builtin.fail", guard["rescue"][0])

        outer = find(tasks, "Restore with staging cleanup")
        self.assertEqual(
            [task["name"] for task in outer["always"]],
            ["Cleanup restore staging directory"],
        )

        defaults = yaml.safe_load(
            (ROOT / "roles" / f"{svc}_restore" / "defaults" / "main.yml").read_text(encoding="utf-8")
        )
        self.assertTrue(defaults[f"{svc}_restore_safety_root"].startswith("/"))
        self.assertIn(f"{svc}_restore_media_safety_root", defaults)

    def test_roles_share_the_safety_scripts(self) -> None:
        names = (
            "Validate the database dump table of contents",
            "Snapshot media and config files",
            "Roll back the database from the safety dump",
            "Roll back media and config files",
        )
        for name in names:
            with self.subTest(task=name):
                scripts = {
                    svc: shell_cmd(find(load_tasks(svc), name)).replace(svc, "SVC")
                    for svc in ROLES
                }
                self.assertEqual(scripts["mastodon"], scripts["takahe"])


GUARD_TASKS = (
    "Look for the archive's manifest",
    "Refuse a manifest that is no regular file",
    "Read the archive's manifest",
    "Find the media excludes line in the archive's manifest",
    "Refuse more than one media excludes line",
    "Record the media excludes from the archive's manifest",
    "Check the media excludes",
    "Count the archive's media files outside the excludes",
    "Look for the live media",
    "Count the live media files outside the excludes",
    "Refuse an archive whose media directory is empty",
)
MANIFEST = (
    'version: "4.3.0"\n'
    'timestamp: "20261104T120000"\n'
    'archive: "manual-20261104T120000.tar.gz"\n'
    'database_dump: "mastodon.dump"\n'
    'media_root: "/home/mastodon/live/public/system"\n'
    "{excludes}"
    'env_file: "/home/mastodon/live/.env.production"\n'
)
DEFAULT_EXCLUDES = 'media_rsync_excludes: ["/cache/***"]\n'


class MastodonEmptyMediaGuardTests(unittest.TestCase):
    """Media excludes from the manifest; an archive without media files is refused before anything stops."""

    def setUp(self) -> None:
        self.tasks = load_tasks("mastodon")
        self.main = flatten(self.tasks, ("block",))

    def test_guard_runs_after_validation_and_before_any_change(self) -> None:
        validate = index_of(self.main, "Validate the database dump table of contents")
        first_change = index_of(self.main, "Ensure media directory exists")
        stop = index_of(self.main, "Stop Mastodon services before restore")
        indexes = [index_of(self.main, name) for name in GUARD_TASKS]
        self.assertEqual(indexes, sorted(indexes))
        self.assertLess(validate, indexes[0])
        self.assertLess(indexes[-1], first_change)
        self.assertLess(indexes[-1], stop)
        for name in GUARD_TASKS:
            task = find(self.tasks, name)
            when = task["when"] if isinstance(task["when"], list) else [task["when"]]
            self.assertEqual(when[0], "mastodon_restore_media_enabled | bool", name)
            if "ansible.builtin.command" in task:
                self.assertIs(task["changed_when"], False, name)

    def test_override_and_default(self) -> None:
        refuse = find(self.tasks, "Refuse an archive whose media directory is empty")
        self.assertEqual(refuse["when"][-1], "not (mastodon_restore_empty_media_confirmed | bool)")
        message = refuse["ansible.builtin.fail"]["msg"]
        self.assertIn("mastodon_restore_empty_media_confirmed=true", message)
        self.assertIn("MASTODON_RESTORE_EMPTY_MEDIA_CONFIRMED=true", message)
        defaults = yaml.safe_load((ROOT / "roles/mastodon_restore/defaults/main.yml").read_text(encoding="utf-8"))
        self.assertIs(defaults["mastodon_restore_empty_media_confirmed"], False)

    def test_the_media_restore_uses_the_excludes(self) -> None:
        argv = find(self.tasks, "Restore media directory")["ansible.builtin.command"]["argv"]
        self.assertIn("mastodon_restore_media_excludes | map('regex_replace', '^', '--exclude=')", argv)


@unittest.skipUnless(shutil.which("ansible-playbook") and shutil.which("rsync"), "needs ansible-playbook and rsync")
class MastodonMediaExcludesEngineTests(unittest.TestCase):
    """The guard tasks and the media restore run by ansible-playbook (local connection) on temp trees."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.payload = self.base / "staging" / "manual-20261104T120000"
        (self.payload / "media").mkdir(parents=True)
        self.media = self.base / "live" / "public" / "system"
        (self.media / "cache" / "remote").mkdir(parents=True)
        (self.media / "cache" / "remote" / "x.png").write_text("cache\n", encoding="utf-8")
        self.manifest(DEFAULT_EXCLUDES)

    def manifest(self, excludes: str | None) -> None:
        path = self.payload / "manifest.yml"
        if excludes is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(MANIFEST.format(excludes=excludes), encoding="utf-8")

    def run_guard(
        self, *, restore: bool = False, confirmed: bool = False, enabled: bool = True, check: bool = False
    ) -> subprocess.CompletedProcess[str]:
        tasks = [find(load_tasks("mastodon"), name) for name in GUARD_TASKS]
        if restore:
            tasks.append(find(load_tasks("mastodon"), "Restore media directory"))
        play = [
            {
                "hosts": "localhost",
                "gather_facts": False,
                "vars_files": [str(ROOT / "roles/mastodon_restore/vars/main.yml")],
                "vars": {
                    "mastodon_restore_media_enabled": enabled,
                    "mastodon_restore_payload_dir": str(self.payload),
                    "mastodon_media_path": str(self.media),
                    "mastodon_restore_empty_media_confirmed": confirmed,
                },
                "tasks": tasks,
            }
        ]
        playbook = self.base / "play.yml"
        playbook.write_text(yaml.safe_dump(play), encoding="utf-8")
        env = {**os.environ, "ANSIBLE_NOCOLOR": "1", "ANSIBLE_LOCALHOST_WARNING": "0"}
        return subprocess.run(
            ["ansible-playbook", "-i", "localhost,", "-c", "local", *(["--check"] if check else []), str(playbook)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
            check=False,
        )

    def live(self) -> dict[str, str]:
        return {
            path.relative_to(self.media).as_posix(): path.read_text(encoding="utf-8")
            for path in self.media.rglob("*")
            if path.is_file()
        }

    def test_cache_only_live_media_needs_no_confirmation_and_keeps_the_cache(self) -> None:
        done = self.run_guard(restore=True)

        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.live(), {"cache/remote/x.png": "cache\n"})

    def test_live_files_outside_the_excludes_are_refused(self) -> None:
        (self.media / "accounts").mkdir()
        (self.media / "accounts" / "me.png").write_text("me\n", encoding="utf-8")
        (self.media / "accounts" / "link.png").symlink_to("me.png")

        done = self.run_guard(restore=True)

        self.assertNotEqual(done.returncode, 0)
        self.assertIn("deletes the 2 file(s) outside them in the live media", done.stdout)
        self.assertEqual(set(self.live()), {"cache/remote/x.png", "accounts/me.png", "accounts/link.png"})

    def test_confirmed_restore_keeps_only_the_excluded_paths(self) -> None:
        (self.media / "accounts").mkdir()
        (self.media / "accounts" / "me.png").write_text("me\n", encoding="utf-8")

        done = self.run_guard(restore=True, confirmed=True)

        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.live(), {"cache/remote/x.png": "cache\n"})

    def test_archive_media_is_restored_beside_the_kept_cache(self) -> None:
        (self.payload / "media" / "accounts").mkdir()
        (self.payload / "media" / "accounts" / "me.png").write_text("archived\n", encoding="utf-8")
        (self.media / "accounts").mkdir()
        (self.media / "accounts" / "new.png").write_text("new\n", encoding="utf-8")

        done = self.run_guard(restore=True)

        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.live(), {"cache/remote/x.png": "cache\n", "accounts/me.png": "archived\n"})

    def test_without_excludes_the_cache_counts(self) -> None:
        for case, excludes in (("no manifest", None), ("no line", ""), ("empty list", "media_rsync_excludes: []\n")):
            with self.subTest(case=case):
                self.manifest(excludes)

                done = self.run_guard(restore=True)

                self.assertNotEqual(done.returncode, 0)
                self.assertIn("deletes the 1 file(s) outside them", done.stdout)
                self.assertEqual(self.live(), {"cache/remote/x.png": "cache\n"})

    def test_without_excludes_rsync_deletes_the_cache_as_before(self) -> None:
        self.manifest(None)
        (self.payload / "media" / "accounts").mkdir()
        (self.payload / "media" / "accounts" / "me.png").write_text("archived\n", encoding="utf-8")

        done = self.run_guard(restore=True)

        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.live(), {"accounts/me.png": "archived\n"})

    def test_unreadable_excludes_stop_before_anything_changes(self) -> None:
        for excludes in (
            'media_rsync_excludes: "/cache/***"\n',
            "media_rsync_excludes: [/cache/***]\n",
            'media_rsync_excludes: [""]\n',
            "media_rsync_excludes: [1]\n",
            "media_rsync_excludes: null\n",
            'media_rsync_excludes: ["/cache/***"]\nmedia_rsync_excludes: []\n',
        ):
            with self.subTest(excludes=excludes):
                self.manifest(excludes)

                done = self.run_guard(restore=True, confirmed=True)

                self.assertNotEqual(done.returncode, 0)
                self.assertNotIn("Restore media directory", done.stdout)
                # Stopped by one of the excludes tasks (a value that is no JSON fails from_json).
                failed = [line for line in done.stdout.splitlines() if line.startswith("TASK [")][-1]
                self.assertIn(
                    failed.rstrip("* "),
                    {
                        "TASK [Refuse more than one media excludes line]",
                        "TASK [Record the media excludes from the archive's manifest]",
                        "TASK [Check the media excludes]",
                    },
                )
                self.assertEqual(self.live(), {"cache/remote/x.png": "cache\n"})

    def test_without_media_every_task_skips(self) -> None:
        (self.media / "accounts").mkdir()
        (self.media / "accounts" / "me.png").write_text("me\n", encoding="utf-8")
        self.manifest('media_rsync_excludes: "not a list"\n')

        done = self.run_guard(restore=True, enabled=False)

        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("skipped=12", done.stdout)
        self.assertEqual(set(self.live()), {"cache/remote/x.png", "accounts/me.png"})

    def test_without_live_media_nothing_is_refused(self) -> None:
        shutil.rmtree(self.media)

        done = self.run_guard()

        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    @unittest.skipIf(os.geteuid() == 0, "root reads a mode-0 directory")
    def test_an_unreadable_live_media_stops(self) -> None:
        locked = self.media / "accounts"
        locked.mkdir()
        (locked / "me.png").write_text("me\n", encoding="utf-8")
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o755)

        done = self.run_guard(restore=True, confirmed=True)

        self.assertNotEqual(done.returncode, 0)
        self.assertIn("TASK [Count the live media files outside the excludes]", done.stdout)
        self.assertNotIn("TASK [Restore media directory]", done.stdout)

    def test_check_mode_counts_and_refuses(self) -> None:
        (self.media / "accounts").mkdir()
        (self.media / "accounts" / "me.png").write_text("me\n", encoding="utf-8")

        done = self.run_guard(check=True)

        self.assertNotEqual(done.returncode, 0)
        self.assertIn("deletes the 1 file(s) outside them in the live media", done.stdout)

    def test_a_manifest_that_is_no_file_stops(self) -> None:
        (self.payload / "manifest.yml").unlink()
        (self.payload / "manifest.yml").symlink_to(self.base / "elsewhere.yml")
        (self.base / "elsewhere.yml").write_text(MANIFEST.format(excludes="media_rsync_excludes: []\n"))

        done = self.run_guard(restore=True, confirmed=True)

        self.assertNotEqual(done.returncode, 0)
        self.assertIn("is not a regular file", done.stdout)
        self.assertEqual(self.live(), {"cache/remote/x.png": "cache\n"})


class FediRestoreScriptTests(unittest.TestCase):
    """Run the snapshot and rollback snippets against temp directories."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        write_stub(self.bin, "systemctl", "exit 0\n")
        tasks = load_tasks("mastodon")
        self.snapshot = shell_cmd(find(tasks, "Snapshot media and config files"))
        self.rollback = shell_cmd(find(tasks, "Roll back media and config files"))
        self.validate = shell_cmd(find(tasks, "Validate the database dump table of contents"))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_script(self, script: str, env: dict[str, str]) -> subprocess.CompletedProcess:
        full_env = {"PATH": f"{self.bin}:{os.environ['PATH']}", **env}
        return subprocess.run(
            ["bash", "-c", script], env=full_env, capture_output=True, text=True, check=False
        )

    def test_snapshot_and_rollback_restore_media_and_config(self) -> None:
        media = self.root / "media"
        (media / "a").mkdir(parents=True)
        (media / "a" / "old.jpg").write_text("old")
        (media / "newer-than-backup.jpg").write_text("uploaded after the backup")
        env_file = self.root / "site" / ".env.production"
        env_file.parent.mkdir()
        env_file.write_text("OLD_SECRET=1")
        unit = self.root / "units" / "web.service"
        absent_unit = self.root / "units" / "extra.service"
        unit.parent.mkdir()
        unit.write_text("[Service]\nold")
        safety = self.root / "safety" / "ts"
        safety.mkdir(parents=True)
        media_safety = self.root / "media-safety" / "ts"
        media_safety.parent.mkdir()
        env = {
            "SAFETY_DIR": str(safety),
            "MEDIA_SAFETY": str(media_safety),
            "MEDIA_DIR": str(media),
            "MEDIA_ENABLED": "true",
            "CONFIG_FILES": "\n".join([str(env_file), str(unit), str(absent_unit)]),
        }
        result = self.run_script(self.snapshot, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((media_safety / "newer-than-backup.jpg").read_text(), "uploaded after the backup")
        self.assertEqual(Path(f"{safety}/files{env_file}").read_text(), "OLD_SECRET=1")

        # A second run must not reuse an existing snapshot directory.
        again = self.run_script(self.snapshot, env)
        self.assertNotEqual(again.returncode, 0)

        # Simulate the restore: rsync --delete drops the newer upload and the
        # config files are replaced, one new unit appears.
        # Replace rather than rewrite in place: rsync writes new inodes, which
        # is what keeps a hard-link snapshot intact.
        (media / "newer-than-backup.jpg").unlink()
        (media / "a" / "old.jpg").unlink()
        (media / "a" / "old.jpg").write_text("from archive")
        env_file.write_text("RESTORED=1")
        unit.write_text("[Service]\nrestored")
        absent_unit.write_text("[Service]\nnew")

        rollback_env = {k: env[k] for k in ("SAFETY_DIR", "MEDIA_SAFETY", "MEDIA_DIR", "MEDIA_ENABLED")}
        result = self.run_script(self.rollback, rollback_env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((media / "newer-than-backup.jpg").read_text(), "uploaded after the backup")
        self.assertEqual((media / "a" / "old.jpg").read_text(), "old")
        self.assertEqual(env_file.read_text(), "OLD_SECRET=1")
        self.assertEqual(unit.read_text(), "[Service]\nold")
        self.assertFalse(absent_unit.exists())

    def test_symlinked_media_root_is_copied_not_linked(self) -> None:
        real = self.root / "real-media"
        real.mkdir()
        (real / "upload.jpg").write_text("keep me")
        media = self.root / "media"
        media.symlink_to(real)
        safety = self.root / "safety"
        safety.mkdir()
        media_safety = self.root / "media-safety"
        result = self.run_script(
            self.snapshot,
            {
                "SAFETY_DIR": str(safety),
                "MEDIA_SAFETY": str(media_safety),
                "MEDIA_DIR": str(media),
                "MEDIA_ENABLED": "true",
                "CONFIG_FILES": "",
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(media_safety.is_symlink())
        (real / "upload.jpg").unlink()
        self.assertEqual((media_safety / "upload.jpg").read_text(), "keep me")

    def test_relative_config_symlink_survives_rollback(self) -> None:
        site = self.root / "site"
        site.mkdir()
        (site / "secrets").write_text("SECRET=1")
        link = site / ".env.production"
        link.symlink_to("secrets")
        safety = self.root / "safety"
        safety.mkdir()
        env = {
            "SAFETY_DIR": str(safety),
            "MEDIA_SAFETY": str(self.root / "media-safety"),
            "MEDIA_DIR": str(self.root / "no-media"),
            "MEDIA_ENABLED": "false",
            "CONFIG_FILES": str(link),
        }
        self.assertEqual(self.run_script(self.snapshot, env).returncode, 0)
        link.unlink()
        link.write_text("RESTORED=1")
        env.pop("CONFIG_FILES")
        result = self.run_script(self.rollback, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), "secrets")

    def test_rollback_restores_same_size_same_mtime_media(self) -> None:
        media = self.root / "media"
        media.mkdir()
        target = media / "f.bin"
        target.write_text("AAAA")
        safety = self.root / "safety"
        safety.mkdir()
        media_safety = self.root / "media-safety"
        env = {
            "SAFETY_DIR": str(safety),
            "MEDIA_SAFETY": str(media_safety),
            "MEDIA_DIR": str(media),
            "MEDIA_ENABLED": "true",
            "CONFIG_FILES": "",
        }
        self.assertEqual(self.run_script(self.snapshot, env).returncode, 0)
        stamp = target.stat()
        target.unlink()
        target.write_text("BBBB")
        os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        env.pop("CONFIG_FILES")
        result = self.run_script(self.rollback, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(target.read_text(), "AAAA")

    def test_snapshot_skips_media_when_disabled(self) -> None:
        media = self.root / "media"
        media.mkdir()
        (media / "x").write_text("x")
        safety = self.root / "safety"
        safety.mkdir()
        media_safety = self.root / "media-safety"
        result = self.run_script(
            self.snapshot,
            {
                "SAFETY_DIR": str(safety),
                "MEDIA_SAFETY": str(media_safety),
                "MEDIA_DIR": str(media),
                "MEDIA_ENABLED": "false",
                "CONFIG_FILES": "",
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(media_safety.exists())

    def render_validation(self, list_output: str, full_read_rc: int) -> subprocess.CompletedProcess:
        write_stub(
            self.bin,
            "fake_pg_restore",
            "if [ \"$1\" = --list ]; then\n"
            f"  cat <<'TOC'\n{list_output}\nTOC\n"
            "  exit 0\n"
            "fi\n"
            f"exit {full_read_rc}\n",
        )
        script = self.validate.replace("{{ mastodon_restore_postgres_restore_binary }}", "fake_pg_restore")
        self.assertNotIn("{{", script)
        return self.run_script(script, {"DUMP": str(self.root / "x.dump")})

    def test_validation_requires_table_data_and_a_full_read(self) -> None:
        good_toc = ";\n; Archive created\n3456; 0 16390 TABLE DATA public accounts mastodon"
        self.assertEqual(self.render_validation(good_toc, 0).returncode, 0)
        self.assertNotEqual(self.render_validation("; empty archive", 0).returncode, 0)
        self.assertNotEqual(self.render_validation(good_toc, 1).returncode, 0)


if __name__ == "__main__":
    unittest.main()
