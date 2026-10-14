import unittest

from tests.credential_helpers import assert_pgpass


class CredentialTests(unittest.TestCase):
    def test_private_passfiles(self):
        assert_pgpass(self, "paperless_restore", 3)

    def test_importer_passphrase_is_stdin(self):
        from tests.credential_helpers import assert_passphrase_stdin

        assert_passphrase_stdin(
            self,
            "paperless_restore",
            "restore.yml",
            "Run Paperless document_importer",
            "paperless_restore_importer_passphrase",
        )

    def test_empty_passphrase_does_not_read_stdin(self):
        from tests.credential_helpers import assert_empty_passphrase_does_not_read

        assert_empty_passphrase_does_not_read(
            self,
            "paperless_restore",
            "restore.yml",
            "Run Paperless document_importer",
            "paperless_restore_importer_passphrase",
        )

    def test_password_validation_precedes_destructive_restore(self):
        from tests.credential_helpers import tasks

        validate = tasks("paperless_restore", "validate.yml")
        assertion = next(
            t
            for t in validate
            if t.get("name")
            == "validate | Validate PostgreSQL passfile passwords before restore"
        )
        self.assertEqual(len(assertion["ansible.builtin.assert"]["that"]), 4)
        main = tasks("paperless_restore", "main.yml")
        includes = [
            t["ansible.builtin.include_tasks"]
            for t in main
            if "ansible.builtin.include_tasks" in t
        ]
        self.assertLess(includes.index("validate.yml"), includes.index("restore.yml"))
