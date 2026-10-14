import unittest

from tests.credential_helpers import assert_pgpass


class CredentialTests(unittest.TestCase):
    def test_private_passfiles(self):
        assert_pgpass(self, "mastodon_restore", 6)

    def test_credential_failure_does_not_abort_remaining_rollback(self):
        from tests.credential_helpers import tasks

        block = next(
            t
            for t in tasks("mastodon_restore", "main.yml")
            if t.get("name", "").startswith("main | Run Roll back the database")
        )
        self.assertEqual(
            block["rescue"][0]["ansible.builtin.set_fact"][
                "mastodon_restore_db_rollback"
            ]["rc"],
            1,
        )
        self.assertFalse(block["always"][0]["failed_when"])
