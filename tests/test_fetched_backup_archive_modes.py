"""Backup archives fetched to the controller must be owner-only.

The archives hold credentials (``takahe.env``, database dumps, ACME and
Tailscale keys, ...). ``ansible.builtin.fetch`` has no ``mode`` option and
writes the local copy with the controller's umask, so ``takahe_backup`` left a
0644 copy in ``~/backups``. Every backup role that fetches an archive now
follows the fetch with a task that sets the local copy to 0600, under the same
conditions as the fetch (and as the synchronize alternative, where a role has
one). Check mode fetches nothing, so the task is skipped there.

The static checks cover every fetch in ``roles/*_backup``; the engine check
runs each role's fetch and permission task with ansible-playbook on localhost
under umask 022.
"""

from __future__ import annotations

import copy
import os
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

FETCH = "ansible.builtin.fetch"
FILE = "ansible.builtin.file"
SYNCHRONIZE = "ansible.posix.synchronize"
CHECK_MODE_GUARD = "not ansible_check_mode"
SIMPLE_VAR = re.compile(r"\{\{ (\w+) \}\}")


def _conditions(task: dict) -> list[str]:
    when = task.get("when", [])
    return [when] if isinstance(when, str) else list(when)


def fetching_task_files() -> list[tuple[Path, list[dict]]]:
    found = []
    for path in sorted(ROLES.glob("*_backup/tasks/*.yml")):
        tasks = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        if any(isinstance(task, dict) and FETCH in task for task in tasks):
            found.append((path, tasks))
    return found


def local_copy_path(fetch_task: dict) -> str:
    """The controller path ``fetch`` writes (flat: true into a directory)."""
    arguments = fetch_task[FETCH]
    src = SIMPLE_VAR.fullmatch(arguments["src"])
    dest = SIMPLE_VAR.fullmatch(arguments["dest"].rstrip("/"))
    assert src and dest, arguments
    assert arguments.get("flat") is True, arguments
    assert arguments["dest"].endswith("/"), arguments
    return f"{{{{ {dest.group(1)} }}}}/{{{{ {src.group(1)} | basename }}}}"


def restrict_task(tasks: list[dict], fetch_index: int) -> dict | None:
    path = local_copy_path(tasks[fetch_index])
    for task in tasks[fetch_index + 1 :]:
        arguments = task.get(FILE) if isinstance(task, dict) else None
        if isinstance(arguments, dict) and arguments.get("path") == path:
            return task
    return None


class FetchedArchiveModeStaticTest(unittest.TestCase):
    def test_backup_roles_that_fetch_are_found(self) -> None:
        roles = {path.parts[-3] for path, _ in fetching_task_files()}
        self.assertIn("takahe_backup", roles)
        self.assertGreaterEqual(len(roles), 20)

    def test_every_fetched_archive_is_made_owner_only(self) -> None:
        for path, tasks in fetching_task_files():
            for index, task in enumerate(tasks):
                if not (isinstance(task, dict) and FETCH in task):
                    continue
                with self.subTest(file=str(path.relative_to(ROOT)), task=task["name"]):
                    restrict = restrict_task(tasks, index)
                    self.assertIsNotNone(restrict, "no later file task sets the local copy's mode")
                    self.assertEqual(restrict[FILE]["mode"], "0600")
                    self.assertNotIn("state", restrict[FILE])
                    self.assertEqual(restrict.get("delegate_to"), "localhost")
                    self.assertIs(restrict.get("become"), False)
                    self.assertEqual(restrict.get("run_once"), task.get("run_once"))
                    fetch_conditions = _conditions(task)
                    # It runs whenever the fetch runs: no condition the fetch
                    # does not have (fetch_method is left out on purpose so the
                    # synchronize path is covered as well), except that check
                    # mode, where fetch writes nothing, skips it.
                    self.assertIn(CHECK_MODE_GUARD, _conditions(restrict))
                    for condition in _conditions(restrict):
                        if condition != CHECK_MODE_GUARD:
                            self.assertIn(condition, fetch_conditions)
                    for condition in fetch_conditions:
                        if "fetch_method" not in condition:
                            self.assertIn(condition, _conditions(restrict))

    def test_synchronize_copies_are_covered_and_not_world_readable(self) -> None:
        for path, tasks in fetching_task_files():
            fetch_index = next(i for i, t in enumerate(tasks) if FETCH in t)
            restrict = restrict_task(tasks, fetch_index)
            for index, task in enumerate(tasks):
                if not (isinstance(task, dict) and SYNCHRONIZE in task):
                    continue
                if task[SYNCHRONIZE].get("mode") != "pull":
                    continue
                with self.subTest(file=str(path.relative_to(ROOT)), task=task["name"]):
                    self.assertLess(index, tasks.index(restrict))
                    for option in task[SYNCHRONIZE].get("rsync_opts", []):
                        if option.startswith("--chmod="):
                            self.assertEqual(option, "--chmod=u=rw,go=")


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not on PATH")
class FetchedArchiveModeEngineTest(unittest.TestCase):
    """Run each role's fetch and permission task against localhost."""

    def test_local_copies_end_up_0600(self) -> None:
        self._run_pairs(check_mode=False)

    def test_check_mode_still_passes(self) -> None:
        """fetch writes nothing under --check; the permission task must not fail."""
        self._run_pairs(check_mode=True)

    def _run_pairs(self, check_mode: bool) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            tasks: list[dict] = []
            variables: dict[str, str] = {}
            expected: list[Path] = []
            for path, role_tasks in fetching_task_files():
                role = path.parts[-3]
                index = next(i for i, t in enumerate(role_tasks) if FETCH in t)
                fetch = copy.deepcopy(role_tasks[index])
                restrict = copy.deepcopy(restrict_task(role_tasks, index))
                src_var = SIMPLE_VAR.fullmatch(fetch[FETCH]["src"]).group(1)
                dest_var = SIMPLE_VAR.fullmatch(fetch[FETCH]["dest"].rstrip("/")).group(1)
                source = base / "remote" / role / f"{role}-20261015.tar.gz"
                source.parent.mkdir(parents=True)
                source.write_bytes(b"secret")
                os.chmod(source, 0o644)
                variables[src_var] = str(source)
                variables[dest_var] = str(base / "local" / role)
                expected.append(base / "local" / role / source.name)
                for task in (fetch, restrict):
                    # Conditions are checked statically; here both run unless
                    # the check-mode guard applies.
                    for key in ("when", "become"):
                        task.pop(key, None)
                    tasks.append(task)
                restrict["when"] = [CHECK_MODE_GUARD]
            playbook = base / "play.yml"
            playbook.write_text(
                yaml.safe_dump(
                    [{"hosts": "localhost", "gather_facts": False, "vars": variables, "tasks": tasks}]
                ),
                encoding="utf-8",
            )
            env = {
                **os.environ,
                "ANSIBLE_NOCOLOR": "1",
                "ANSIBLE_LOCALHOST_WARNING": "0",
                "ANSIBLE_INVENTORY_UNPARSED_WARNING": "0",
            }
            result = subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    'umask 022 && exec ansible-playbook -i localhost, -c local "$@"',
                    "sh",
                    str(playbook),
                    *(["--check"] if check_mode else []),
                ],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                env=env,
                timeout=300,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for local in expected:
                with self.subTest(copy=str(local.relative_to(base))):
                    if check_mode:
                        self.assertFalse(local.exists())
                        continue
                    self.assertTrue(local.is_file())
                    self.assertEqual(stat.S_IMODE(local.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
