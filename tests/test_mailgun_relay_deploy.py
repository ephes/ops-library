"""Contracts for what the mailgun-relay rsync deploy ships to the host.

The relay repository also holds the Rust port under rust/ and is often
deployed from a git worktree, where `.git` is a file. These tests run the
role's exclude patterns through a real `rsync --dry-run` so the rsync
pattern semantics (anchoring, directory-only matches) are checked, not
just the list contents.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "mailgun_relay_deploy"


def rsync_excludes() -> list[str]:
    defaults = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
    return defaults["mailgun_relay_rsync_excludes"]


def synced_paths(source: Path) -> set[str]:
    """Return the paths `rsync -a` would copy from source with the role's excludes."""
    with tempfile.TemporaryDirectory() as dest:
        result = subprocess.run(
            [
                "rsync",
                "-a",
                "--dry-run",
                "--out-format=%n",
                *(f"--exclude={pattern}" for pattern in rsync_excludes()),
                f"{source}/",
                f"{dest}/",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    return {line.rstrip("/") for line in result.stdout.splitlines() if line}


@unittest.skipIf(shutil.which("rsync") is None, "rsync is not installed")
class RsyncExcludeTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.source = Path(tmp.name)
        for path in (
            "pyproject.toml",
            "uv.lock",
            "src/mailgun_relay/__init__.py",
            "src/mailgun_relay/rust/module.py",
            "rust/PLAN.md",
            "rust/target/debug/big.rlib",
            "rust/spikes/s1b/Cargo.toml",
            "rust/spikes/s1b/target/release/binary",
            "vendor/.git/HEAD",
            ".venv/bin/python",
        ):
            file = self.source / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("x")
        # A git worktree checkout: `.git` is a file pointing at the main repo.
        (self.source / ".git").write_text("gitdir: /elsewhere/.git/worktrees/x\n")

    def test_python_service_sources_are_synced(self) -> None:
        synced = synced_paths(self.source)
        for path in (
            "pyproject.toml",
            "uv.lock",
            "src/mailgun_relay/__init__.py",
            # Only the top-level rust/ is excluded, not every directory named rust.
            "src/mailgun_relay/rust/module.py",
        ):
            with self.subTest(path=path):
                self.assertIn(path, synced)

    def test_rust_port_is_not_synced(self) -> None:
        synced = synced_paths(self.source)
        self.assertEqual({p for p in synced if p.split("/")[0] == "rust"}, set())

    def test_git_metadata_is_not_synced_as_file_or_directory(self) -> None:
        synced = synced_paths(self.source)
        self.assertNotIn(".git", synced)
        self.assertEqual({p for p in synced if ".git" in p.split("/")}, set())


if __name__ == "__main__":
    unittest.main()
