import unittest
from pathlib import Path

import yaml

from tests.credential_helpers import assert_pgpass


class CredentialTests(unittest.TestCase):
    def test_private_passfiles(self):
        assert_pgpass(self, "fastdeploy_restore", 1)

    def test_password_validated_before_destructive_steps(self):
        # restore.yml drops and recreates the database before the passfile
        # wrapper; a password the passfile cannot hold must fail in validate.
        root = Path(__file__).resolve().parents[1] / "roles/fastdeploy_restore/tasks"
        first = yaml.safe_load((root / "validate.yml").read_text())[0]
        that = first["ansible.builtin.assert"]["that"]
        self.assertTrue(any('"\\n"' in c and "fastdeploy_restore_postgres_password" in c for c in that))
        self.assertTrue(any('"\\r"' in c and "fastdeploy_restore_postgres_password" in c for c in that))
