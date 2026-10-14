"""Preserve audited task behavior while changing credential delivery."""

import json
import unittest

from tests.credential_helpers import ROOT, tasks


class CredentialContracts(unittest.TestCase):
    def test_original_attributes_and_postgresql_commands_are_preserved(self):
        entries = json.loads(
            (ROOT / "tests/task_credential_contracts.json").read_text()
        )
        for entry in entries:
            _, role, _, file = entry["file"].split("/")
            task = next(t for t in tasks(role, file) if t.get("name") == entry["task"])
            with self.subTest(file=entry["file"], task=entry["task"]):
                for key, value in entry["attributes"].items():
                    self.assertEqual(task.get(key), value, key)
                if "module" in entry:
                    self.assertEqual(task[entry["module"]], entry["arguments"])
                    self.assertEqual(task.get("args"), entry["args"])
