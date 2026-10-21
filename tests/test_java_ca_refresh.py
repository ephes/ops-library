"""Regression contracts for the incident recovery sequence."""
import unittest
from pathlib import Path
import yaml

TASKS = yaml.safe_load((Path(__file__).resolve().parents[1] / "roles/java_ca_refresh/tasks/main.yml").read_text())

class JavaRefreshTests(unittest.TestCase):
    def task(self, name):
        return next(t for t in TASKS if t["name"] == name)

    def test_interrupted_refresh_still_restarts_on_resume(self):
        restart = self.task("Restart explicitly selected JVM services after trust refresh")
        # After a successful refresh the alias predicate is false; pending state
        # must independently permit restarting JVMs with their old SSL contexts.
        self.assertIn("or java_ca_refresh_pending.stat.exists", restart["when"])
        names = [t["name"] for t in TASKS]
        self.assertLess(names.index("Persist pending restart before changing trust"), names.index("Refresh Java trust through the supported distribution hook"))
        self.assertEqual(names[-1], "Clear pending marker only after successful verification and readiness")

    def test_refresh_is_guarded_by_patched_os_and_stale_java(self):
        names = [t["name"] for t in TASKS]
        self.assertLess(names.index("Refuse refresh while affected roots remain enabled in OS trust"), names.index("Refresh Java trust through the supported distribution hook"))
        self.assertEqual(self.task("Refresh Java trust through the supported distribution hook")["when"], "java_ca_refresh_needed")
        verify = self.task("Require both affected roots absent")["ansible.builtin.assert"]["that"]
        self.assertEqual(len(verify), 2)
