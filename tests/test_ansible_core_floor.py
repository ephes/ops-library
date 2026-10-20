"""The collection and its own test environment require ansible-core >= 2.20.3.

ansible-core 2.20.0-2.20.2 write a stray ``Install-Python-Debian: no`` line into
deb822 repository files, which later controllers remove again, so the same
deploy flips between changed and unchanged depending on the controller version.
"""

import tomllib
import unittest
from pathlib import Path

import yaml
from packaging.specifiers import SpecifierSet
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
AFFECTED = [Version(v) for v in ("2.20.0", "2.20.1", "2.20.2")]


class AnsibleCoreFloorTest(unittest.TestCase):
    def assert_floor(self, spec):
        specifier = SpecifierSet(spec)
        for version in AFFECTED:
            self.assertNotIn(version, specifier, spec)
        self.assertIn(Version("2.20.3"), specifier, spec)

    def test_runtime_requires_ansible(self):
        runtime = yaml.safe_load((ROOT / "meta/runtime.yml").read_text(encoding="utf-8"))
        self.assert_floor(runtime["requires_ansible"])

    def test_pyproject_dependency(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        specs = [d.removeprefix("ansible-core") for d in project["dependencies"] if d.startswith("ansible-core")]
        self.assertEqual(len(specs), 1, specs)
        self.assert_floor(specs[0])

    def test_locked_version(self):
        lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
        versions = [p["version"] for p in lock["package"] if p["name"] == "ansible-core"]
        self.assertEqual(len(versions), 1, versions)
        self.assertGreaterEqual(Version(versions[0]), Version("2.20.3"))


if __name__ == "__main__":
    unittest.main()
