import unittest

from tests.credential_helpers import assert_pgpass


class CredentialTests(unittest.TestCase):
    def test_private_passfiles(self):
        assert_pgpass(self, "takahe_backup", 1)


class DumpWriterTests(unittest.TestCase):
    def test_dump_runs_as_backup_directory_owner(self):
        # pg_dump writes into the 0700 backup directory owned by
        # takahe_backup_owner; running it as `postgres` cannot write there.
        from pathlib import Path

        import yaml

        defaults = yaml.safe_load(
            (Path(__file__).resolve().parents[1] / "roles/takahe_shared/defaults/main.yml").read_text()
        )
        self.assertEqual(defaults["takahe_backup_dir_mode"], "0700")
        self.assertEqual(
            defaults["takahe_backup_postgres_become_user"], "{{ takahe_backup_owner }}"
        )
