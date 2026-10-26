"""The Python endpoint verifies Basic Auth without putting the password in argv."""

import base64
import shutil
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import jinja2

ROOT = Path(__file__).resolve().parents[1]


class EndpointCredentialTests(unittest.TestCase):
    def test_password_is_given_only_on_stdin(self):
        template = ROOT / "roles/metrics_endpoint/templates/metrics_httpd.py.j2"
        text = (
            jinja2.Environment(undefined=jinja2.StrictUndefined)
            .from_string(template.read_text())
            .render(
                metrics_endpoint_script_path="/usr/local/bin/mail-metrics.sh",
                metrics_endpoint_htpasswd_path="/etc/metrics-endpoint/htpasswd",
                metrics_endpoint_script_timeout=10,
            )
        )
        scope = {"__name__": "endpoint_fixture"}
        # Execute only the trusted role template under test.
        exec(compile(text, str(template), "exec"), scope)  # noqa: S102
        handler_type = scope["MetricsHandler"]
        handler = object.__new__(handler_type)
        value = "fixture-endpoint-stdin-value"
        header = "Basic " + base64.b64encode(("nyxmon:" + value).encode()).decode()
        with mock.patch.object(
            scope["subprocess"],
            "run",
            return_value=SimpleNamespace(returncode=0, stderr=""),
        ) as run:
            self.assertTrue(
                handler._check_auth(header, {"htpasswd_file": "/fixture/auth"})[0]
            )
        argv = run.call_args.args[0]
        self.assertNotIn(value, argv)
        self.assertEqual(argv, ["htpasswd", "-vi", "/fixture/auth", "nyxmon"])
        self.assertEqual(run.call_args.kwargs["input"], value)
        self.assertTrue(run.call_args.kwargs["capture_output"])
        self.assertTrue(run.call_args.kwargs["text"])


@unittest.skipUnless(
    shutil.which("htpasswd"), "htpasswd is required for password semantics"
)
class EndpointPasswordSemanticsTests(unittest.TestCase):
    def setUp(self):
        template = ROOT / "roles/metrics_endpoint/templates/metrics_httpd.py.j2"
        text = (
            jinja2.Environment(undefined=jinja2.StrictUndefined)
            .from_string(template.read_text())
            .render(
                metrics_endpoint_script_path="/fixture/script",
                metrics_endpoint_htpasswd_path="/fixture/htpasswd",
                metrics_endpoint_script_timeout=10,
            )
        )
        scope = {"__name__": "endpoint_fixture"}
        exec(compile(text, str(template), "exec"), scope)  # noqa: S102
        self.handler = object.__new__(scope["MetricsHandler"])

    def check(self, path, password, user="nyxmon"):
        header = "Basic " + base64.b64encode((user + ":" + password).encode()).decode()
        return self.handler._check_auth(header, {"htpasswd_file": str(path)})[0]

    def entry(self, algorithm, password, user="nyxmon"):
        import subprocess

        result = subprocess.run(
            ["htpasswd", "-ni" + algorithm, user],
            input=password,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    def test_bcrypt_suffix_preserves_the_old_72_and_255_byte_bounds(self):
        import tempfile

        value = "L" * 72
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "htpasswd"
            path.write_text(self.entry("B", value))
            for password in (
                value,
                value + "\n",
                value + "\r\n",
                value + "x" * 181 + "\r\n",
            ):
                with self.subTest(password_bytes=len(password.encode())):
                    self.assertTrue(self.check(path, password))
            for password in (
                value[:71] + "\n",
                value + "\0tail",
                value + "x" * 182 + "\r\n",
            ):
                with self.subTest(password_bytes=len(password.encode())):
                    self.assertFalse(self.check(path, password))

    def test_long_sha_password_cannot_be_authenticated_by_truncating_a_suffix(self):
        import tempfile

        value = "S" * 80
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "htpasswd"
            path.write_text(self.entry("s", value))
            self.assertTrue(self.check(path, value))
            for suffix in ("\n", "\r\n", "\r", "\0tail"):
                with self.subTest(suffix=repr(suffix)):
                    self.assertFalse(self.check(path, value + suffix))

    def test_every_matching_record_must_be_bcrypt_for_the_suffix_exception(self):
        import tempfile

        value = "L" * 72
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "htpasswd"
            path.write_text(self.entry("B", value) + self.entry("s", value))
            self.assertTrue(self.check(path, value))
            self.assertFalse(self.check(path, value + "\n"))
            path.write_text(
                self.entry("B", value) + self.entry("s", value, "someone-else")
            )
            self.assertTrue(self.check(path, value + "\n"))


if __name__ == "__main__":
    unittest.main()
