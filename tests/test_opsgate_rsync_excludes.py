"""opsgate_deploy keeps the Rust port workspace out of the Python app dirs.

The opsgate repository carries the Rust port in `rust/` (sources, plans and,
after a local `cargo build`, gigabytes of `rust/target/`). The role rsyncs the
whole checkout into the API and runner app directories, so `rust/` must be
excluded there. This test runs the role's own source-sync tasks from
`tasks/app_source.yml` with the role defaults through real Ansible in check
mode (`synchronize` then runs `rsync --dry-run`) against a temporary
opsgate-shaped checkout, and reads the paths rsync reports.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/opsgate_deploy"
SYNC_TASKS = (
    "app_source | Build rsync exclude options",
    "app_source | Sync local OpsGate source to target",
    "app_source | Sync local OpsGate source to runner target",
)
SOURCE_FILES = (
    "pyproject.toml",
    "uv.lock",
    "src/opsgate/__init__.py",
    "src/opsgate/templates/index.html",
    # Only the top-level `rust/` is excluded; a nested directory of that name
    # still ships.
    "docs/rust/notes.md",
    "rust/Cargo.toml",
    "rust/PLAN.md",
    "rust/crates/opsgate-core/src/lib.rs",
    "rust/target/release/opsgate",
)

# Itemized change line: update type, file type, attribute flags, a space.
ITEMIZED = re.compile(r"^[<>ch.][fdLDS][^ ]* ")


def app_source_tasks() -> list[dict]:
    tasks = yaml.safe_load((ROLE / "tasks/app_source.yml").read_text())
    by_name = {task["name"]: task for task in tasks}
    return [copy.deepcopy(by_name[name]) for name in SYNC_TASKS]


def changed_paths(result: dict) -> set[str]:
    """Paths from synchronize's itemized (`%i %n%L`) rsync output.

    The module strips its `<<CHANGED>>` marker; deletions read
    `*deleting   <path>` and come back as `deleted:<path>`. The itemize code
    is matched by its update and file-type characters, not a fixed width:
    rsync 3 prints 11 characters, macOS openrsync 9.
    """
    paths = set()
    for line in result["stdout_lines"]:
        if line.startswith("*deleting"):
            paths.add("deleted:" + line.split(None, 1)[1].rstrip("/"))
        elif ITEMIZED.match(line):
            paths.add(line.split(" ", 1)[1].rstrip("/"))
    return paths


@unittest.skipIf(shutil.which("rsync") is None, "rsync is not installed")
@unittest.skipIf(shutil.which("ansible-playbook") is None, "ansible-playbook is not installed")
class OpsgateRsyncExcludeTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.source = self.tmp / "opsgate"
        for path in SOURCE_FILES:
            file = self.source / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("x")
        # A git worktree checkout: `.git` is a file.
        (self.source / ".git").write_text("gitdir: /elsewhere/.git/worktrees/x\n")

    def run_check_mode(self, app_dir: Path, runner_app_dir: Path) -> dict[str, dict]:
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        play = {
            "name": "opsgate app source sync",
            "hosts": "localhost",
            "gather_facts": False,
            "vars": {
                "opsgate_rsync_excludes": defaults["opsgate_rsync_excludes"],
                "opsgate_source_path": str(self.source),
                "opsgate_app_dir": str(app_dir),
                "opsgate_runner_app_dir": str(runner_app_dir),
            },
            "tasks": app_source_tasks(),
        }
        playbook = self.tmp / "play.yml"
        playbook.write_text(yaml.safe_dump([play]))
        completed = subprocess.run(
            ["ansible-playbook", "--check", "-i", "localhost,", "-c", "local", str(playbook)],
            cwd=ROOT,
            env=os.environ
            | {"ANSIBLE_NOCOLOR": "1", "ANSIBLE_STDOUT_CALLBACK": "ansible.posix.json"},
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        results = {
            task["task"]["name"]: task["hosts"]["localhost"]
            for task in report["plays"][0]["tasks"]
        }
        self.assertEqual(set(results), set(SYNC_TASKS))
        return results

    def test_check_mode_sync_excludes_rust_workspace(self) -> None:
        app_dir = self.tmp / "api-app"
        runner_app_dir = self.tmp / "runner-app"
        results = self.run_check_mode(app_dir, runner_app_dir)
        for name in SYNC_TASKS[1:]:
            with self.subTest(task=name):
                result = results[name]
                synced = changed_paths(result)
                # The Python app still ships, so the check cannot pass vacuously.
                for path in (
                    "pyproject.toml",
                    "uv.lock",
                    "src/opsgate/__init__.py",
                    "src/opsgate/templates/index.html",
                    "docs/rust/notes.md",
                ):
                    self.assertIn(path, synced)
                self.assertEqual({p for p in synced if p.split("/")[0] == "rust"}, set())
                self.assertEqual({p for p in synced if ".git" in p.split("/")}, set())
        # Check mode changed nothing on disk.
        self.assertFalse(app_dir.exists())
        self.assertFalse(runner_app_dir.exists())

    def test_existing_rust_dir_in_app_dir_is_left_alone(self) -> None:
        # rsync --delete never deletes excluded paths on the receiver: a
        # `rust/` synced by a role version without the exclude stays in place
        # (documented in the role README); other stale files are removed.
        app_dir = self.tmp / "api-app"
        runner_app_dir = self.tmp / "runner-app"
        for app in (app_dir, runner_app_dir):
            (app / "rust").mkdir(parents=True)
            (app / "rust/PLAN.md").write_text("old")
            (app / "stale.py").write_text("old")
        results = self.run_check_mode(app_dir, runner_app_dir)
        for name in SYNC_TASKS[1:]:
            with self.subTest(task=name):
                synced = changed_paths(results[name])
                self.assertIn("deleted:stale.py", synced)
                touched = {p.removeprefix("deleted:") for p in synced}
                self.assertEqual({p for p in touched if p.split("/")[0] == "rust"}, set())


if __name__ == "__main__":
    unittest.main()
