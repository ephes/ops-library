"""Safety contracts for the file-based restore roles.

jellyfin_restore, navidrome_restore and metube_restore stopped the service
with `failed_when: false` (MeTube excepted) and ran `rsync --delete` over the
live data; minecraft_java_restore deleted the world before copying the new
one; snappymail_restore deleted the data directory before unpacking the
archive. None took a copy or had a rescue. These tests pin the safer shape:
check the archive in staging, stop (fail closed), copy config files aside,
rename the live directory aside instead of deleting it, restore into a fresh
directory, and move everything back in `rescue`. The shared shell snippets
run here against temp directories, so nothing touches a host.
"""

from __future__ import annotations

import os
import pwd
import grp
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

# role -> (rollback block, stop guard block or None, data restore task, service start task or None)
ROLES = {
    "jellyfin_restore": (
        "Restore Jellyfin with rollback",
        "Stop Jellyfin and copy config files",
        "Restore Jellyfin data directory",
        "Start Jellyfin service after restore",
    ),
    "navidrome_restore": (
        "Restore Navidrome with rollback",
        "Stop Navidrome and copy config files",
        "Restore Navidrome data directory",
        "Start Navidrome service after restore",
    ),
    "metube_restore": (
        "Restore MeTube with rollback",
        "Stop MeTube and copy config files",
        "Restore state directory",
        "Start/restart metube service",
    ),
    "minecraft_java_restore": (
        "Restore Minecraft with rollback",
        "Stop Minecraft and copy config files",
        "Restore world directory",
        "Start minecraft service",
    ),
    "snappymail_restore": (
        "Restore SnappyMail with rollback",
        None,
        "Copy restored data into place",
        None,
    ),
}

SHARED = ("Move live data aside", "Roll back data and config files", "Prune older pre-restore copies")


def load_tasks(role: str) -> list[dict]:
    return yaml.safe_load((ROOT / "roles" / role / "tasks" / "main.yml").read_text(encoding="utf-8"))


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


def module_args(task: dict) -> str:
    for key in ("ansible.builtin.command", "ansible.builtin.shell", "ansible.builtin.file", "ansible.builtin.copy"):
        if key in task:
            return str(task[key])
    return ""


class FileRestoreOrderTests(unittest.TestCase):
    def test_every_role(self) -> None:
        for role, names in ROLES.items():
            with self.subTest(role=role):
                self.check_role(role, *names)

    def check_role(self, role: str, rollback_name: str, guard_name: str | None, data_name: str, start_name: str | None) -> None:
        tasks = load_tasks(role)
        main = flatten(tasks, ("block",))
        names = [task.get("name") for task in main]

        aside = index_of(main, "Move live data aside")
        data = index_of(main, data_name)
        prune = index_of(main, "Prune older pre-restore copies")
        self.assertLess(aside, data)
        self.assertLess(data, prune)
        if start_name:
            start = index_of(main, start_name)
            self.assertLess(data, start)
            self.assertLess(start, prune)

        # Nothing deletes or overwrites live data before the aside move.
        for task in main[:aside]:
            args = module_args(task)
            self.assertNotIn("--delete", args, task.get("name"))
            file_args = task.get("ansible.builtin.file") or {}
            if file_args.get("state") == "absent":
                self.assertRegex(str(file_args.get("path")), r"staging", task.get("name"))
        # No rsync --delete and no removal of the live directory anywhere.
        for task in main:
            self.assertNotIn("'--delete'", module_args(task), task.get("name"))

        # The archive is unpacked and checked before the stop and the move.
        unpack = next(i for i, n in enumerate(names) if n and ("Unpack" in n or n.startswith("Extract")))
        self.assertLess(unpack, aside)

        if guard_name:
            guard = find(tasks, guard_name)
            guard_names = [t["name"] for t in guard["block"]]
            stop = next(n for n in guard_names if n.lower().startswith("stop"))
            confirm = next(n for n in guard_names if n.startswith("Confirm"))
            self.assertLess(guard_names.index(stop), guard_names.index(confirm))
            self.assertLess(unpack, index_of(main, stop))
            self.assertLess(index_of(main, confirm), aside)
            self.assertLess(index_of(main, "Copy config files aside"), aside)
            confirm_task = find(tasks, confirm)
            self.assertIn("not in ['inactive', 'failed']", confirm_task["failed_when"])
            self.assertNotIn("when", confirm_task)
            for task in guard["block"]:
                self.assertNotIn("failed_when", {k: v for k, v in task.items() if v is False}, task["name"])
                self.assertNotIn("ignore_errors", task, task["name"])
            self.assertEqual(len(guard["rescue"]), 1)
            self.assertIn("ansible.builtin.fail", guard["rescue"][0])

        block = find(tasks, rollback_name)
        self.assertEqual(block["block"][0]["name"], "Move live data aside")
        for task in block["block"]:
            self.assertNotEqual(task.get("failed_when"), False, task["name"])
            self.assertNotIn("ignore_errors", task, task["name"])
        rescue_names = [t["name"] for t in block["rescue"]]
        self.assertIn("Roll back data and config files", rescue_names)
        self.assertIn("ansible.builtin.fail", block["rescue"][-1])
        if start_name:
            # The old data is started again only after a successful rollback.
            restart = next(t for t in block["rescue"] if t["name"].startswith("Start"))
            self.assertLess(rescue_names.index("Roll back data and config files"), rescue_names.index(restart["name"]))
            self.assertIn("rollback.rc", str(restart["when"]))
            rollback = find(tasks, "Roll back data and config files")
            self.assertIn("['inactive', 'failed']", str(rollback["when"]))

        always = [t for t in tasks if "always" in t]
        self.assertEqual(len(always), 1)
        self.assertTrue(all("staging" in t["name"].lower() or "temporary" in t["name"].lower() for t in always[0]["always"]))

        defaults = yaml.safe_load((ROOT / "roles" / role / "defaults" / "main.yml").read_text(encoding="utf-8"))
        safety_root = next(v for k, v in defaults.items() if k.endswith("_restore_safety_root"))
        self.assertTrue(safety_root.startswith("/var/backups/"))

    def test_roles_share_the_safety_scripts(self) -> None:
        names = SHARED + ("Copy config files aside",)
        for name in names:
            with self.subTest(task=name):
                scripts = {}
                for role in ROLES:
                    try:
                        scripts[role] = shell_cmd(find(load_tasks(role), name))
                    except KeyError:
                        self.assertEqual((role, name), ("snappymail_restore", "Copy config files aside"))
                self.assertEqual(len(set(scripts.values())), 1, sorted(scripts))

    def test_config_copy_matches_the_fedi_snapshot(self) -> None:
        # The file copy is the config part of the Mastodon/Takahe snapshot.
        ours = shell_cmd(find(load_tasks("jellyfin_restore"), "Copy config files aside"))
        theirs = shell_cmd(find(load_tasks("takahe_restore"), "Snapshot media and config files"))
        body = ours.split("set -euo pipefail\n", 1)[1]
        self.assertIn(body.strip().splitlines()[0], theirs)
        self.assertIn('done <<< "$CONFIG_FILES"', theirs)


def write_stub(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text("#!/bin/bash\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class FileRestoreScriptTests(unittest.TestCase):
    """Run the shared snippets against temp directories."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        write_stub(self.bin, "systemctl", f'echo "$*" >> "{self.root}/systemctl.log"\n')
        tasks = load_tasks("jellyfin_restore")
        self.copy_files = shell_cmd(find(tasks, "Copy config files aside"))
        self.aside = shell_cmd(find(tasks, "Move live data aside"))
        self.rollback = shell_cmd(find(tasks, "Roll back data and config files"))
        self.prune = shell_cmd(find(tasks, "Prune older pre-restore copies"))
        self.owner = pwd.getpwuid(os.getuid()).pw_name
        self.group = grp.getgrgid(os.getgid()).gr_name
        self.safety_root = self.root / "safety"
        self.safety = self.safety_root / "20261006T120000Z"
        self.safety.mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_script(self, script: str, env: dict[str, str]) -> subprocess.CompletedProcess:
        full_env = {"PATH": f"{self.bin}:{os.environ['PATH']}", "SAFETY_DIR": str(self.safety), **env}
        return subprocess.run(["bash", "-c", script], env=full_env, capture_output=True, text=True, check=False)

    def dirs(self, *paths: Path, mode: str = "0750") -> str:
        return "\n".join(f"{p}\t{self.owner}\t{self.group}\t{mode}" for p in paths)

    def aside_env(self, *paths: Path, keep_live: bool = False) -> dict[str, str]:
        return {"STAMP": "20261006T120000Z", "KEEP_LIVE": "true" if keep_live else "false", "DIRS": self.dirs(*paths)}

    def test_move_aside_then_rollback_restores_the_old_tree(self) -> None:
        data = self.root / "var" / "lib" / "jellyfin"
        (data / "metadata").mkdir(parents=True)
        (data / "metadata" / "old.nfo").write_text("old")
        (data / "added-after-backup.db").write_text("keep me")
        config = self.root / "etc" / "jellyfin"
        config.mkdir(parents=True)
        (config / "system.xml").write_text("old config")
        unit = self.root / "units" / "jellyfin.service"
        unit.parent.mkdir()
        unit.write_text("[Service]\nold")
        traefik = self.root / "traefik" / "jellyfin.yml"

        result = self.run_script(self.copy_files, {"CONFIG_FILES": f"{unit}\n{traefik}"})
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_script(self.aside, self.aside_env(data, config))
        self.assertEqual(result.returncode, 0, result.stderr)

        aside = Path(f"{data}.pre-restore-20261006T120000Z")
        self.assertEqual((aside / "added-after-backup.db").read_text(), "keep me")
        self.assertTrue(data.is_dir())
        self.assertEqual(list(data.iterdir()), [])
        self.assertEqual(stat.S_IMODE(data.stat().st_mode), 0o750)
        self.assertIn(f"kept {data} as {aside}", result.stdout)

        # Simulate a half-finished restore.
        (data / "partial.db").write_text("from archive")
        (config / "system.xml").write_text("restored")
        unit.write_text("[Service]\nrestored")
        traefik.parent.mkdir()
        traefik.write_text("new")

        result = self.run_script(self.rollback, {})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((data / "added-after-backup.db").read_text(), "keep me")
        self.assertFalse((data / "partial.db").exists())
        self.assertEqual((config / "system.xml").read_text(), "old config")
        self.assertFalse(aside.exists())
        self.assertEqual(unit.read_text(), "[Service]\nold")
        self.assertFalse(traefik.exists())
        self.assertIn("daemon-reload", (self.root / "systemctl.log").read_text())

    def test_move_aside_refuses_an_existing_safety_path_before_moving_anything(self) -> None:
        first = self.root / "a"
        second = self.root / "b"
        first.mkdir()
        second.mkdir()
        (first / "x").write_text("x")
        Path(f"{second}.pre-restore-20261006T120000Z").mkdir()
        result = self.run_script(self.aside, self.aside_env(first, second))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((first / "x").read_text(), "x")
        self.assertFalse(Path(f"{first}.pre-restore-20261006T120000Z").exists())
        # Rollback after the refusal must not touch the live directories.
        self.assertEqual(self.run_script(self.rollback, {}).returncode, 0)
        self.assertEqual((first / "x").read_text(), "x")

    def test_bind_mount_on_the_same_device_is_refused_in_both_modes(self) -> None:
        # A bind mount shares its parent's device number; only the mount
        # table (mountpoint -q) tells it apart. Nothing may move or copy.
        first = self.root / "plain"
        first.mkdir()
        (first / "f").write_text("plain")
        bound = self.root / "bound"
        bound.mkdir()
        (bound / "f").write_text("bound")
        write_stub(self.bin, "mountpoint", f'[ "${{@: -1}}" = "{bound}" ]\n')
        for keep_live in (False, True):
            with self.subTest(keep_live=keep_live):
                result = self.run_script(self.aside, self.aside_env(first, bound, keep_live=keep_live))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("mount point", result.stderr)
                self.assertEqual((first / "f").read_text(), "plain")
                self.assertEqual((bound / "f").read_text(), "bound")
                self.assertFalse(Path(f"{first}.pre-restore-20261006T120000Z").exists())
                self.assertFalse(Path(f"{bound}.pre-restore-20261006T120000Z").exists())

    def test_safety_directory_inside_a_live_directory_is_refused(self) -> None:
        data = self.root / "data"
        data.mkdir()
        (data / "f").write_text("live")
        self.safety = data / "safety" / "20261006T120000Z"
        self.safety.mkdir(parents=True)
        result = self.run_script(self.aside, self.aside_env(data))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("lies inside", result.stderr)
        self.assertEqual((data / "f").read_text(), "live")
        self.assertFalse(Path(f"{data}.pre-restore-20261006T120000Z").exists())

    def test_nested_directories_are_refused_before_anything_moves(self) -> None:
        data = self.root / "data"
        config = data / "config"
        config.mkdir(parents=True)
        (config / "system.xml").write_text("live config")
        for order in ((config, data), (data, config), (data, data)):
            with self.subTest(order=[p.name for p in order]):
                result = self.run_script(self.aside, self.aside_env(*order))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("list only one", result.stderr)
                self.assertEqual((config / "system.xml").read_text(), "live config")
                self.assertEqual(list(self.root.glob("**/*.pre-restore-*")), [])

    def test_rollback_without_manifest_fails(self) -> None:
        result = self.run_script(self.rollback, {})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("manifest", result.stderr)

    def test_nested_mount_is_refused_before_anything_moves(self) -> None:
        data = self.root / "snappymail"
        (data / "attachments").mkdir(parents=True)
        (data / "attachments" / "a.bin").write_text("on the mount")
        mountinfo = self.root / "mountinfo"
        mountinfo.write_text(f"36 22 8:1 / {data / 'attachments'} rw - ext4 /dev/sdb1 rw\n")
        for keep_live in (False, True):
            with self.subTest(keep_live=keep_live):
                env = {**self.aside_env(data, keep_live=keep_live), "MOUNTINFO": str(mountinfo)}
                result = self.run_script(self.aside, env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("contains a mount point", result.stderr)
                self.assertEqual((data / "attachments" / "a.bin").read_text(), "on the mount")
                self.assertFalse(Path(f"{data}.pre-restore-20261006T120000Z").exists())

    def test_rollback_never_deletes_through_a_mount(self) -> None:
        data = self.root / "data"
        data.mkdir()
        (data / "f").write_text("old")
        self.assertEqual(self.run_script(self.aside, self.aside_env(data)).returncode, 0)
        (data / "mnt").mkdir()
        (data / "mnt" / "x").write_text("mounted later")
        mountinfo = self.root / "mountinfo"
        mountinfo.write_text(f"36 22 8:1 / {data / 'mnt'} rw - ext4 /dev/sdb1 rw\n")
        result = self.run_script(self.rollback, {"MOUNTINFO": str(mountinfo)})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not replaced", result.stderr)
        self.assertEqual((data / "mnt" / "x").read_text(), "mounted later")
        self.assertEqual(Path(f"{data}.pre-restore-20261006T120000Z/f").read_text(), "old")

    def test_symlinked_directory_moves_its_target(self) -> None:
        real = self.root / "disk" / "world"
        real.mkdir(parents=True)
        (real / "level.dat").write_text("old world")
        link = self.root / "server" / "world"
        link.parent.mkdir()
        link.symlink_to(real)
        result = self.run_script(self.aside, self.aside_env(link))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(link.is_symlink())
        self.assertTrue(real.is_dir())
        self.assertEqual(list(real.iterdir()), [])
        self.assertEqual(Path(f"{real}.pre-restore-20261006T120000Z/level.dat").read_text(), "old world")
        (real / "level.dat").write_text("broken")
        self.assertEqual(self.run_script(self.rollback, {}).returncode, 0)
        self.assertEqual((link / "level.dat").read_text(), "old world")

    def test_missing_directory_is_skipped(self) -> None:
        missing = self.root / "nope"
        result = self.run_script(self.aside, self.aside_env(missing))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(missing.exists())
        self.assertEqual(self.run_script(self.rollback, {}).returncode, 0)

    def test_rollback_removes_a_partial_restore_of_a_new_directory(self) -> None:
        world = self.root / "server" / "world"
        world.parent.mkdir()
        self.assertEqual(self.run_script(self.aside, self.aside_env(world)).returncode, 0)
        world.mkdir()
        (world / "partial.mca").write_text("half")
        self.assertEqual(self.run_script(self.rollback, {}).returncode, 0)
        self.assertFalse(world.exists())

    def test_prune_sees_mounts_through_a_symlinked_safety_root(self) -> None:
        real_root = self.root / "real-safety"
        real_root.mkdir()
        old = real_root / "20250101T000000Z"
        old.mkdir()
        (old / "f").write_text("on the mount")
        alias = self.root / "alias-safety"
        alias.symlink_to(real_root)
        mountinfo = self.root / "mountinfo"
        mountinfo.write_text(f"36 22 8:1 / {old} rw - ext4 /dev/sdb1 rw\n")
        data = self.root / "data"
        data.mkdir()
        self.assertEqual(self.run_script(self.aside, self.aside_env(data)).returncode, 0)
        result = self.run_script(self.prune, {"SAFETY_ROOT": str(alias), "MOUNTINFO": str(mountinfo)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((old / "f").read_text(), "on the mount")
        self.assertIn("keeping", result.stderr)

    def test_keep_live_copies_and_rolls_back_a_merge(self) -> None:
        data = self.root / "snappymail"
        data.mkdir()
        (data / "user.json").write_text("old")
        result = self.run_script(self.aside, self.aside_env(data, keep_live=True))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((data / "user.json").read_text(), "old")
        self.assertEqual(Path(f"{data}.pre-restore-20261006T120000Z/user.json").read_text(), "old")
        (data / "user.json").write_text("merged")
        (data / "new.json").write_text("new")
        self.assertEqual(self.run_script(self.rollback, {}).returncode, 0)
        self.assertEqual((data / "user.json").read_text(), "old")
        self.assertFalse((data / "new.json").exists())

    def test_rollback_moves_back_when_the_fresh_directory_is_missing(self) -> None:
        data = self.root / "state"
        data.mkdir()
        (data / "queue.json").write_text("old")
        self.assertEqual(self.run_script(self.aside, self.aside_env(data)).returncode, 0)
        data.rmdir()
        self.assertEqual(self.run_script(self.rollback, {}).returncode, 0)
        self.assertEqual((data / "queue.json").read_text(), "old")

    def test_rollback_drops_an_unfinished_copy_and_keeps_live_data(self) -> None:
        data = self.root / "live"
        data.mkdir()
        (data / "f").write_text("live")
        partial = Path(f"{data}.pre-restore-20261006T120000Z")
        partial.mkdir()
        (self.safety / "dirs.manifest").write_text(f"{data}\t{partial}\n")
        (self.safety / "dirs.done").write_text("")
        self.assertEqual(self.run_script(self.rollback, {}).returncode, 0)
        self.assertEqual((data / "f").read_text(), "live")
        self.assertFalse(partial.exists())

    def test_prune_keeps_an_old_copy_with_a_mount_inside(self) -> None:
        data = self.root / "my data"
        data.mkdir()
        mounted = Path(f"{data}.pre-restore-20250101T000000Z")
        (mounted / "transcodes").mkdir(parents=True)
        (mounted / "transcodes" / "on-other-disk.mkv").write_text("keep")
        plain = Path(f"{data}.pre-restore-20250201T000000Z")
        plain.mkdir()
        escaped = str(mounted / "transcodes").replace(" ", "\\040")
        mountinfo = self.root / "mountinfo"
        mountinfo.write_text(
            "22 1 8:1 / / rw,relatime shared:1 - ext4 /dev/sda1 rw\n"
            f"36 22 8:1 /srv/cache {escaped} rw,relatime shared:2 - ext4 /dev/sda1 rw\n"
        )
        self.assertEqual(self.run_script(self.aside, self.aside_env(data)).returncode, 0)
        result = self.run_script(self.prune, {"SAFETY_ROOT": str(self.safety_root), "MOUNTINFO": str(mountinfo)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"keeping {mounted}: a mount point lies inside it", result.stderr)
        self.assertEqual((mounted / "transcodes" / "on-other-disk.mkv").read_text(), "keep")
        self.assertFalse(plain.exists())
        self.assertTrue(Path(f"{data}.pre-restore-20261006T120000Z").is_dir())

    def test_prune_keeps_an_old_copy_that_is_itself_a_mount(self) -> None:
        data = self.root / "data"
        data.mkdir()
        mounted = Path(f"{data}.pre-restore-20250101T000000Z")
        mounted.mkdir()
        (mounted / "f").write_text("on the mount")
        old_safety = self.safety_root / "20250101T000000Z"
        old_safety.mkdir()
        mountinfo = self.root / "mountinfo"
        mountinfo.write_text(
            f"36 22 8:1 / {mounted} rw - ext4 /dev/sdb1 rw\n"
            f"37 22 8:1 / {old_safety} rw - ext4 /dev/sdc1 rw\n"
        )
        self.assertEqual(self.run_script(self.aside, self.aside_env(data)).returncode, 0)
        result = self.run_script(self.prune, {"SAFETY_ROOT": str(self.safety_root), "MOUNTINFO": str(mountinfo)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((mounted / "f").read_text(), "on the mount")
        self.assertTrue(old_safety.is_dir())
        self.assertIn(f"keeping {old_safety}", result.stderr)

    def test_prune_ignores_a_mount_next_to_the_copy(self) -> None:
        data = self.root / "data"
        data.mkdir()
        older = Path(f"{data}.pre-restore-20250101T000000Z")
        older.mkdir()
        mountinfo = self.root / "mountinfo"
        # Shares the prefix but is not inside the copy.
        mountinfo.write_text(f"36 22 8:1 / {older}x rw - ext4 /dev/sda1 rw\n")
        self.assertEqual(self.run_script(self.aside, self.aside_env(data)).returncode, 0)
        result = self.run_script(self.prune, {"SAFETY_ROOT": str(self.safety_root), "MOUNTINFO": str(mountinfo)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(older.exists())

    def test_rollback_keeps_an_unfinished_copy_with_a_mount_inside(self) -> None:
        data = self.root / "live"
        data.mkdir()
        partial = Path(f"{data}.pre-restore-20261006T120000Z")
        (partial / "mnt").mkdir(parents=True)
        (partial / "mnt" / "x").write_text("mounted")
        (self.safety / "dirs.manifest").write_text(f"{data}\t{partial}\n")
        (self.safety / "dirs.done").write_text("")
        mountinfo = self.root / "mountinfo"
        mountinfo.write_text(f"36 22 8:1 / {partial / 'mnt'} rw - ext4 /dev/sdb1 rw\n")
        result = self.run_script(self.rollback, {"MOUNTINFO": str(mountinfo)})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((partial / "mnt" / "x").read_text(), "mounted")

    def test_prune_keeps_only_this_runs_copies(self) -> None:
        data = self.root / "data"
        data.mkdir()
        older = Path(f"{data}.pre-restore-20250101T000000Z")
        older.mkdir()
        unrelated = Path(f"{data}.pre-restore-notes")
        unrelated.mkdir()
        old_safety = self.safety_root / "20250101T000000Z"
        old_safety.mkdir()
        self.assertEqual(self.run_script(self.aside, self.aside_env(data)).returncode, 0)
        result = self.run_script(self.prune, {"SAFETY_ROOT": str(self.safety_root)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(older.exists())
        self.assertFalse(old_safety.exists())
        self.assertTrue(unrelated.exists())
        self.assertTrue(Path(f"{data}.pre-restore-20261006T120000Z").is_dir())
        self.assertTrue(self.safety.is_dir())
        self.assertTrue(data.is_dir())


if __name__ == "__main__":
    unittest.main()
