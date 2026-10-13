import unittest

from tests.credential_helpers import assert_pgpass


class CredentialTests(unittest.TestCase):
    def test_private_passfiles(self):
        assert_pgpass(self, "mastodon_backup", 1)
