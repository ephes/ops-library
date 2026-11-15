"""`just test` runs every target of its two lists exactly once.

The `test` recipe runs the targets of `test_serial_targets` one after another
(as one job) beside the targets of `test_parallel_targets`, a few at a time
(scripts/run-parallel.sh). This keeps the two lists consistent: every entry
is a recipe of the justfile, none is listed twice, and the targets that use
Docker or Molecule stay in the serial list.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Docker-backed targets: they must not run beside each other.
DOCKER_TARGETS = {
    "test-container-ca-activate",
    "test-security-trust-remediate",
    "test-openclaw-compose-lifecycle",
    "test-os-apt-maintenance-failed-run",
    "test-tailscale-metrics-timer",
    "test-ssh-forwarding-integration",
}


def justfile_list(text, name):
    match = re.search(rf'^{name} := "([^"]*)"$', text, re.MULTILINE)
    if match is None:
        raise AssertionError(f"{name} not found in the justfile")
    return match.group(1).split()


class JustTestTargetsTest(unittest.TestCase):
    def setUp(self):
        self.justfile = (ROOT / "justfile").read_text(encoding="utf-8")
        self.serial = justfile_list(self.justfile, "test_serial_targets")
        self.parallel = justfile_list(self.justfile, "test_parallel_targets")
        self.recipes = set(
            re.findall(
                r"^([A-Za-z_][\w-]*)(?: [^:\n]*)?:(?!=)", self.justfile, re.MULTILINE
            )
        )

    def test_every_target_is_a_recipe(self):
        missing = [t for t in self.serial + self.parallel if t not in self.recipes]
        self.assertEqual(missing, [])

    def test_no_target_is_listed_twice(self):
        targets = self.serial + self.parallel
        self.assertEqual(len(targets), len(set(targets)))

    def test_docker_targets_run_serially(self):
        self.assertEqual(DOCKER_TARGETS - set(self.serial), set())

    def test_docs_lint_runs_after_docs_build(self):
        self.assertLess(self.serial.index("docs-build"), self.serial.index("docs-lint"))

    def test_molecule_targets_run_serially(self):
        # A target whose recipe runs Molecule or Docker belongs in the serial list.
        for target in self.parallel:
            body = re.search(
                rf"^{re.escape(target)}(?: [^:\n]*)?:.*\n((?:(?:    .*)?\n)*)",
                self.justfile,
                re.MULTILINE,
            ).group(1)
            self.assertNotRegex(
                body,
                r"just molecule-|molecule-run\.sh|_export-docker-host|docker (build|run|compose)",
                target,
            )


if __name__ == "__main__":
    unittest.main()
