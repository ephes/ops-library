"""The encrypted volume's fstab entry must not flip on every run.

``encrypted_volume_prepare`` used to write the fstab entry twice: ``lineinfile``
with a line ending in ``0 2``, then ``ansible.posix.mount`` (``state:
mounted``, no ``dump``/``passno``, so ``0 0``). Every run rewrote the line
twice, and because the mount module saw a changed entry on a mounted path, it
remounted the volume (macmini ``/mnt/cryptdata`` under a running MinIO on every
``deploy-one minio``).

Now the mount task is the only writer of the entry and takes
``encrypted_volume_fstab_dump``/``encrypted_volume_fstab_passno``. The engine
test runs the role's own mount task against a temporary fstab (``state:
present`` instead of ``mounted``: the same fstab comparison that decides the
remount, without mounting) and checks that the live line is left alone, that a
real change (old passno, new options) is reported as a change, and that it
converges in one run. The validate-only fstab assert is run against fstab
contents too.
"""

from __future__ import annotations

import copy
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "encrypted_volume_prepare"
TASKS = ROLE / "tasks" / "main.yml"
DEFAULTS = ROLE / "defaults" / "main.yml"

MOUNT_TASK = "Mount encrypted filesystem"
VALIDATE_TASK = "Assert fstab entry exists"
UUID = "169c4190-32ea-4ef1-b564-03da7eb18fea"
ROOT_LINE = "/dev/root / ext4 defaults 0 1"
# The /mnt/cryptdata line on macmini on 2026-10-20 (what the mount task left).
LIVE_LINE = f"UUID={UUID} /mnt/cryptdata ext4 defaults,noatime 0 0"


def _tasks() -> list[dict]:
    return yaml.safe_load(TASKS.read_text(encoding="utf-8"))


def _defaults() -> dict:
    return yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))


def _walk(tasks: list[dict]):
    for task in tasks:
        yield task
        for key in ("block", "rescue", "always"):
            if key in task:
                yield from _walk(task[key])


def _find(name: str) -> dict:
    for task in _walk(_tasks()):
        if task.get("name") == name:
            return copy.deepcopy(task)
    raise KeyError(name)


def _mount_args(task: dict) -> dict:
    for key in ("ansible.posix.mount", "mount"):
        if key in task:
            return task[key]
    raise AssertionError(f"not a mount task: {task}")


class FstabTaskContractTest(unittest.TestCase):
    def test_mount_task_is_the_only_fstab_writer(self) -> None:
        writers = []
        for task in _walk(_tasks()):
            for module in ("lineinfile", "ansible.builtin.lineinfile", "replace",
                           "ansible.builtin.replace", "blockinfile", "ansible.builtin.blockinfile",
                           "copy", "ansible.builtin.copy", "template", "ansible.builtin.template"):
                args = task.get(module)
                if isinstance(args, dict) and "fstab" in str(args.get("path", args.get("dest", ""))):
                    writers.append(task["name"])
        self.assertEqual(writers, [])

    def test_mount_task_sets_dump_and_passno(self) -> None:
        mount = _mount_args(_find(MOUNT_TASK))
        self.assertEqual(mount["state"], "mounted")
        self.assertEqual(mount["dump"], "{{ encrypted_volume_fstab_dump }}")
        self.assertEqual(mount["passno"], "{{ encrypted_volume_fstab_passno }}")

    def test_no_remount_state_or_handlers(self) -> None:
        self.assertNotRegex(TASKS.read_text(encoding="utf-8"), r"state:\s*remounted")
        self.assertFalse((ROLE / "handlers").exists())

    def test_defaults_match_the_live_line(self) -> None:
        defaults = _defaults()
        rendered = " ".join(
            [
                f"UUID={UUID}",
                defaults["encrypted_volume_mount_point"],
                defaults["encrypted_volume_fs_type"],
                defaults["encrypted_volume_mount_opts"],
                str(defaults["encrypted_volume_fstab_dump"]),
                str(defaults["encrypted_volume_fstab_passno"]),
            ]
        )
        self.assertEqual(rendered, LIVE_LINE)


def _have_posix_mount() -> bool:
    if not shutil.which("ansible-doc"):
        return False
    result = subprocess.run(
        ["ansible-doc", "-t", "module", "-j", "ansible.posix.mount"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result.returncode == 0


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not on PATH")
@unittest.skipUnless(_have_posix_mount(), "ansible.posix collection not installed")
class FstabEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.fstab = self.base / "fstab"

    def playbook(self, name: str, play_vars: dict, tasks: list[dict]) -> subprocess.CompletedProcess[str]:
        play = {
            "hosts": "localhost",
            "gather_facts": False,
            "vars": {**_defaults(), **play_vars},
            "tasks": tasks,
        }
        path = self.base / name
        path.write_text(yaml.safe_dump([play], sort_keys=False), encoding="utf-8")
        env = {
            **os.environ,
            "ANSIBLE_NOCOLOR": "1",
            "ANSIBLE_LOCALHOST_WARNING": "0",
            "ANSIBLE_INVENTORY_UNPARSED_WARNING": "0",
            "ANSIBLE_STDOUT_CALLBACK": "default",
        }
        return subprocess.run(
            ["ansible-playbook", "-i", "localhost,", "-c", "local", str(path)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
        )

    def run_mount(self, **overrides: str) -> bool:
        mount = _find(MOUNT_TASK)
        args = _mount_args(mount)
        args["fstab"] = str(self.fstab)
        args["state"] = "present"
        mount["register"] = "fstab_mount"
        report = {"name": "Report", "debug": {"msg": "RESULT mount={{ fstab_mount.changed }}"}}
        result = self.playbook(
            "mount.yml", {"encrypted_volume_fstab_src": f"UUID={UUID}", **overrides}, [mount, report]
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for line in result.stdout.splitlines():
            if "RESULT mount=" in line:
                return line.split("RESULT mount=", 1)[1].strip().strip('"') == "True"
        self.fail("no RESULT line:\n" + result.stdout)

    def entries(self) -> list[str]:
        return [line for line in self.fstab.read_text(encoding="utf-8").splitlines() if "/mnt/cryptdata" in line]

    def test_live_line_is_left_alone(self) -> None:
        self.fstab.write_text(f"{ROOT_LINE}\n{LIVE_LINE}\n", encoding="utf-8")
        before = self.fstab.read_text(encoding="utf-8")
        self.assertFalse(self.run_mount())
        self.assertEqual(self.fstab.read_text(encoding="utf-8"), before)

    def test_old_passno_line_converges_in_one_run(self) -> None:
        # What the removed lineinfile task wrote before the mount task flipped it.
        self.fstab.write_text(f"{ROOT_LINE}\nUUID={UUID} /mnt/cryptdata ext4 defaults,noatime 0 2\n", encoding="utf-8")
        self.assertTrue(self.run_mount())
        self.assertEqual(self.entries(), [LIVE_LINE])
        self.assertFalse(self.run_mount())

    def test_option_change_is_a_change(self) -> None:
        # With state: mounted a changed entry on a mounted path is remounted,
        # so new options take effect; nothing else may pre-write the line.
        self.fstab.write_text(f"{ROOT_LINE}\n{LIVE_LINE}\n", encoding="utf-8")
        self.assertTrue(self.run_mount(encrypted_volume_mount_opts="defaults,noatime,nofail"))
        self.assertEqual(self.entries(), [f"UUID={UUID} /mnt/cryptdata ext4 defaults,noatime,nofail 0 0"])
        self.assertFalse(self.run_mount(encrypted_volume_mount_opts="defaults,noatime,nofail"))

    def test_missing_entry_is_added_once(self) -> None:
        self.fstab.write_text(f"{ROOT_LINE}\n", encoding="utf-8")
        self.assertTrue(self.run_mount())
        self.assertEqual(self.entries(), [LIVE_LINE])
        self.assertFalse(self.run_mount())

    def run_validate(self, content: str, *, mapper_active: bool = True) -> subprocess.CompletedProcess[str]:
        return self.playbook(
            "validate.yml",
            {
                "encrypted_volume_mapper_path": "/dev/mapper/cryptdata",
                "encrypted_volume_expected_mapper_active": mapper_active,
                "encrypted_volume_validate_fs_uuid": {"stdout": f"{UUID}\n"},
                "encrypted_volume_fstab_stat": {"stat": {"exists": True}},
                "encrypted_volume_fstab_file": {"content": "{{ fstab_text | b64encode }}"},
                "fstab_text": content,
            },
            [_find(VALIDATE_TASK)],
        )

    def test_validate_only_accepts_mapper_or_the_mappers_uuid(self) -> None:
        for line in (LIVE_LINE, "/dev/mapper/cryptdata\t/mnt/cryptdata  ext4 defaults,noatime 0 0"):
            result = self.run_validate(f"{ROOT_LINE}\n{line}\n")
            self.assertEqual(result.returncode, 0, line + "\n" + result.stdout + result.stderr)

    def test_validate_only_rejects_other_entries(self) -> None:
        for line in (
            f"UUID={UUID} /mnt/cryptdata ext4 defaults,noatime 0 2",
            f"UUID={UUID} /mnt/cryptdata ext4 defaults 0 0",
            f"UUID={UUID} /mnt/cryptdata2 ext4 defaults,noatime 0 0",
            "UUID=00000000-0000-0000-0000-000000000000 /mnt/cryptdata ext4 defaults,noatime 0 0",
            "UUID=- /mnt/cryptdata ext4 defaults,noatime 0 0",
            "/dev/sdb1 /mnt/cryptdata ext4 defaults,noatime 0 0",
        ):
            result = self.run_validate(f"{ROOT_LINE}\n{line}\n")
            self.assertNotEqual(result.returncode, 0, line)
            self.assertIn("missing the expected entry", result.stdout, line)

    def test_validate_only_needs_the_open_mapper_for_a_uuid_source(self) -> None:
        result = self.run_validate(f"{ROOT_LINE}\n{LIVE_LINE}\n", mapper_active=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing the expected entry", result.stdout)


if __name__ == "__main__":
    unittest.main()
