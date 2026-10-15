"""Contracts that rsync deploys keep git metadata off the host.

A deploy role that rsyncs a whole source checkout excludes `.git`. In a git
worktree `.git` is a file pointing at the main repository, not a directory, so
an exclude written as `.git/` misses it and the file lands on the host. These
tests run every role default exclude list that mentions `.git` through a real
`rsync --dry-run`, against a clone-shaped and a worktree-shaped tree, so the
rsync pattern semantics are checked rather than the list contents.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]

# Roles known to rsync a whole checkout with a `.git` exclude. Discovery below
# finds every such list; this set only guards against the discovery silently
# matching nothing.
REQUIRED_ROLES = {"graphyard_deploy", "logyard_deploy", "mailgun_relay_deploy"}


def git_exclude_lists() -> dict[str, list[str]]:
    """Return `role/variable` -> patterns for default exclude lists naming `.git`."""
    found: dict[str, list[str]] = {}
    for defaults_file in sorted(ROOT.glob("roles/*/defaults/main.yml")):
        defaults = yaml.safe_load(defaults_file.read_text()) or {}
        role = defaults_file.parents[1].name
        for name, value in defaults.items():
            if not name.endswith("_excludes") or not isinstance(value, list):
                continue
            if any(str(pattern).strip("/") == ".git" for pattern in value):
                found[f"{role}/{name}"] = [str(pattern) for pattern in value]
    return found


def synced_paths(source: Path, excludes: list[str]) -> set[str]:
    """Return the paths `rsync -a` would copy from source with the given excludes."""
    with tempfile.TemporaryDirectory() as dest:
        result = subprocess.run(
            [
                "rsync",
                "-a",
                "--dry-run",
                "--out-format=%n",
                *(f"--exclude={pattern}" for pattern in excludes),
                f"{source}/",
                f"{dest}/",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    return {line.rstrip("/") for line in result.stdout.splitlines() if line}


@unittest.skipIf(shutil.which("rsync") is None, "rsync is not installed")
class RsyncGitExcludeTests(unittest.TestCase):
    def make_tree(self, *, worktree: bool) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        source = Path(tmp.name)
        for path in ("README.md", "src/app/__init__.py", "vendor/.git/HEAD"):
            file = source / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("x")
        if worktree:
            # A git worktree checkout: `.git` is a file pointing at the main repo.
            (source / ".git").write_text("gitdir: /elsewhere/.git/worktrees/x\n")
        else:
            (source / ".git").mkdir()
            (source / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
        return source

    def test_required_roles_are_discovered(self) -> None:
        roles = {key.split("/")[0] for key in git_exclude_lists()}
        self.assertLessEqual(REQUIRED_ROLES, roles)

    def test_git_metadata_is_not_synced_as_file_or_directory(self) -> None:
        trees = {
            "clone": self.make_tree(worktree=False),
            "worktree": self.make_tree(worktree=True),
        }
        for key, excludes in git_exclude_lists().items():
            for shape, source in trees.items():
                with self.subTest(excludes=key, tree=shape):
                    synced = synced_paths(source, excludes)
                    # Sources still ship, so an empty sync cannot pass vacuously.
                    self.assertIn("src/app/__init__.py", synced)
                    self.assertEqual(
                        {p for p in synced if ".git" in p.split("/")}, set()
                    )


if __name__ == "__main__":
    unittest.main()
