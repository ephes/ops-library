import unittest

from tests.credential_helpers import assert_pgpass


class CredentialTests(unittest.TestCase):
    def test_private_passfiles(self):
        assert_pgpass(self, "paperless_backup", 1)

    def test_exporter_passphrase_is_stdin(self):
        from tests.credential_helpers import assert_passphrase_stdin

        assert_passphrase_stdin(
            self,
            "paperless_backup",
            "main.yml",
            "Run Paperless document_exporter",
            "paperless_backup_exporter_passphrase",
        )

    def test_empty_passphrase_does_not_read_stdin(self):
        from tests.credential_helpers import assert_empty_passphrase_does_not_read

        assert_empty_passphrase_does_not_read(
            self,
            "paperless_backup",
            "main.yml",
            "Run Paperless document_exporter",
            "paperless_backup_exporter_passphrase",
        )
