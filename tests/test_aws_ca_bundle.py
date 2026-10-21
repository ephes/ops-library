"""Exercise refusal of existing custom SDK trust and effective environment checks."""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "aws_trust", ROOT / "roles/aws_ca_bundle/files/check_aws_trust.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
BUNDLE = "/etc/ssl/certs/ca-certificates.crt"


class AwsTrustTests(unittest.TestCase):
    def run_check(
        self, runtime=b"", configured="", envfile="", shared_config="", mode="preflight"
    ):
        context = Mock()
        context.get_ca_certs.return_value = []
        values = {
            "MainPID": "123",
            "Environment": configured,
            "EnvironmentFiles": "/etc/test.env (ignore_errors=no)",
        }
        with (
            patch.object(module.ssl, "SSLContext", return_value=context),
            patch.object(
                module.subprocess,
                "check_output",
                side_effect=lambda args, **kwargs: values[args[-2]],
            ),
            patch.object(
                module.Path,
                "read_bytes",
                return_value=runtime + b"\0HOME=/home/example",
            ),
            patch.object(module.Path, "exists", return_value=True),
            patch.object(
                module.Path,
                "read_text",
                autospec=True,
                side_effect=lambda path: (
                    envfile if str(path) == "/etc/test.env" else shared_config
                ),
            ),
        ):
            return module.check("example.service", BUNDLE, mode)

    def test_omitted_setting_requests_restart(self):
        self.assertEqual(self.run_check(), {"uses_system_bundle": False})

    def test_verified_runtime(self):
        self.assertTrue(
            self.run_check(runtime=("AWS_CA_BUNDLE=" + BUNDLE).encode(), mode="verify")[
                "uses_system_bundle"
            ]
        )

    def test_custom_runtime_is_preserved_by_refusal(self):
        with self.assertRaisesRegex(RuntimeError, "Existing runtime"):
            self.run_check(runtime=b"AWS_CA_BUNDLE=/private/custom.pem")

    def test_custom_unit_or_environmentfile_is_refused(self):
        for kwargs in (
            {"configured": "AWS_CA_BUNDLE=/custom.pem"},
            {"envfile": 'AWS_CA_BUNDLE="/custom.pem"'},
        ):
            with self.assertRaisesRegex(RuntimeError, "Existing"):
                self.run_check(**kwargs)

    def test_verify_catches_override_not_inherited(self):
        with self.assertRaisesRegex(RuntimeError, "did not inherit"):
            self.run_check(mode="verify")

    def test_custom_shared_config_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, "shared-config"):
            self.run_check(shared_config="[default]\nca_bundle = /custom.pem\n")
