"""The collection archive never packs the Rust workspace or the GitHub workflows.

rust/PLAN-foundation.md section 5: `galaxy.yml` `build_ignore` lists `rust`
and `.github`. Without them `ansible-galaxy collection build/install` from a
developer checkout would pack `rust/target/` (hundreds of MB of build output)
into ops-control's `collections/`. When `ansible-galaxy` is available, the
real checkout is built into a temporary directory and the archive members are
checked.
"""

import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = ("rust", ".github")


def ansible_galaxy():
    beside_python = Path(sys.executable).parent / "ansible-galaxy"
    if beside_python.is_file():
        return str(beside_python)
    return shutil.which("ansible-galaxy")


class CollectionBuildIgnoreTest(unittest.TestCase):
    def test_build_ignore_lists_rust_and_github(self):
        galaxy = yaml.safe_load((ROOT / "galaxy.yml").read_text(encoding="utf-8"))
        for entry in (*EXCLUDED, "tests"):
            self.assertIn(entry, galaxy["build_ignore"])

    @unittest.skipUnless(ansible_galaxy(), "ansible-galaxy not available")
    def test_built_archive_has_no_rust_or_github_members(self):
        # The checkout has both directories, so the build really exercises
        # the ignore entries (rust/ holds at least the plans).
        for name in EXCLUDED:
            self.assertTrue((ROOT / name).is_dir(), name)
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(
                [
                    ansible_galaxy(),
                    "collection",
                    "build",
                    str(ROOT),
                    "--output-path",
                    tmp,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            archives = list(Path(tmp).glob("local-ops_library-*.tar.gz"))
            self.assertEqual(len(archives), 1, archives)
            with tarfile.open(archives[0]) as archive:
                names = archive.getnames()
        offending = [
            name
            for name in names
            if any(name == top or name.startswith(f"{top}/") for top in EXCLUDED)
        ]
        self.assertEqual(offending, [])
        self.assertTrue(any(name.startswith("roles/") for name in names))
        self.assertIn("MANIFEST.json", names)


if __name__ == "__main__":
    unittest.main()
