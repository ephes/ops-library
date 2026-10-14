import unittest

from tests.credential_helpers import assert_mongo_files


class CredentialTests(unittest.TestCase):
    def test_private_mongo_scripts(self):
        assert_mongo_files(self, "unifi_remove", 2)
