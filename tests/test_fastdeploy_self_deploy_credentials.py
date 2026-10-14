import unittest

from tests.credential_helpers import assert_env_source


class CredentialTests(unittest.TestCase):
    def test_source_env_file(self):
        assert_env_source(
            self,
            "fastdeploy_self_deploy",
            "deploy_staging.yml",
            "env.j2",
            "secret_key",
            "SECRET_KEY",
            1,
        )
