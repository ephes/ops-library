"""Drift guard for the fixtures of the Rust port of software_live.

rust/software-live/fixtures/ holds what the Python program
(roles/software_live/files/software_live.py) returns for a fixed corpus,
written by rust/software-live/fixtures/generate.py (rust/software-live/PLAN.md
6.1). The Rust tests compare the Rust code with them, so they must always
describe the Python program of this checkout. The Rust CI job only runs for
changes under rust/; this test (part of `just test`) catches a change of the
Python program that changes a fixture.

After such a change: `just rs-software-live-fixtures`, then update the Rust
code in the same change. TESTMAP.md must name every Python test of the
program, so a new Python test gets a Rust counterpart or a reason.
"""

from __future__ import annotations

import ast
import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
CRATE = ROOT / "rust" / "software-live"
GENERATOR_PATH = CRATE / "fixtures" / "generate.py"
TESTMAP = CRATE / "TESTMAP.md"
PYTHON_TESTS = (
    ROOT / "tests" / "test_software_live.py",
    ROOT / "tests" / "test_software_health_bridge.py",
)
REGENERATE = "run `just rs-software-live-fixtures` and update the Rust code in the same change"


def load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("software_live_rust_fixtures", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FixturesMatchThePythonProgram(unittest.TestCase):
    generator: ModuleType

    @classmethod
    def setUpClass(cls) -> None:
        cls.generator = load_generator()

    def test_committed_fixtures_match_a_regeneration(self) -> None:
        stale = self.generator.check_fixtures()
        self.assertEqual(stale, [], f"stale software-live Rust fixtures {stale}: {REGENERATE}")

    def test_drift_check_detects_an_edited_or_missing_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory)
            for name in self.generator.GENERATORS:
                shutil.copy(self.generator.FIXTURES_DIR / name, copy / name)
            self.assertEqual(self.generator.check_fixtures(copy), [])

            policy = copy / "policy.json"
            text = policy.read_text(encoding="utf-8")
            self.assertIn('"host is required"', text)
            policy.write_text(text.replace('"host is required"', '"host is needed"', 1), encoding="utf-8")
            self.assertEqual(self.generator.check_fixtures(copy), ["policy.json"])

            (copy / "report.json").unlink()
            self.assertEqual(self.generator.check_fixtures(copy), ["policy.json", "report.json"])

    def test_p3_cases_are_inputs_python_accepts(self) -> None:
        import json

        for name in ("policy.json", "version.json", "traefik.json"):
            data = json.loads((self.generator.FIXTURES_DIR / name).read_text(encoding="utf-8"))
            if isinstance(data, list):
                cases = data
            elif name == "traefik.json":
                cases = data["binary_info"] + data["observe"]
            else:
                cases = data["cases"]
            tagged = [case for case in cases if "p3" in case]
            self.assertTrue(tagged, name)
            for case in tagged:
                self.assertNotIn("error", {k for k, v in case.items() if v is not None}, case)


class PythonReadsRustWrittenCaches(unittest.TestCase):
    """Cache files are shared state across the implementations (PLAN.md 3.3):
    the Python program must use a cache the Rust code wrote exactly as one it
    wrote itself, so a rollback neither repeats the upstream request nor
    loses the ``last_success`` evidence. ``fixtures/rust-caches.json`` holds
    what the Rust code writes (the Rust test
    ``upstream::tests::rust_written_caches_are_committed`` keeps it current).
    """

    live: ModuleType

    @classmethod
    def setUpClass(cls) -> None:
        cls.live = load_generator().live

    def lookup(self, cache: dict, directory: Path, now: float) -> dict:
        path = directory / cache["cache"]
        if cache["function"] == "upstream":
            return self.live.upstream(path, now)
        return self.live.lifecycle_upstream(cache["product"], path, now)

    def test_rust_written_caches_are_fresh_hits_and_kept_evidence(self) -> None:
        import json
        from unittest import mock

        caches = json.loads((CRATE / "fixtures" / "rust-caches.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(caches["caches"]), 3)
        for cache in caches["caches"]:
            with self.subTest(cache["id"]), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                file = directory / cache["file"]
                file.write_text(cache["text"], encoding="ascii")
                written = json.loads(cache["text"])
                with mock.patch.object(
                    self.live.urllib.request, "urlopen", side_effect=AssertionError("no request")
                ):
                    hit = self.lookup(cache, directory, cache["now"] + 86399)
                self.assertEqual(hit, {**written, "status": "ok", "cached": True})
                with mock.patch.object(
                    self.live.urllib.request, "urlopen", side_effect=OSError("offline")
                ):
                    stale = self.lookup(cache, directory, cache["now"] + 86400)
                self.assertEqual(
                    stale, {"status": "unknown", "error": "OSError", "last_success": written}
                )
                self.assertEqual(file.read_text(encoding="ascii"), cache["text"])


class TestmapNamesEveryPythonTest(unittest.TestCase):
    def test_every_python_test_has_a_row(self) -> None:
        testmap = TESTMAP.read_text(encoding="utf-8")
        names = []
        for path in PYTHON_TESTS:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                    names.append(node.name)
        self.assertGreater(len(names), 30)
        missing = [name for name in names if f"`{name}`" not in testmap]
        self.assertEqual(missing, [], "add these Python tests to rust/software-live/TESTMAP.md")


if __name__ == "__main__":
    unittest.main()
