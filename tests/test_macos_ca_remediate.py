"""Exercise the actual Apple bundle format and reject incomplete filtering."""
import importlib.util
import pathlib
import unittest
import ssl
import sys
import tempfile

SCRIPT = pathlib.Path(__file__).parents[1] / "roles/macos_ca_remediate/files/filter_bundle.py"
spec = importlib.util.spec_from_file_location("filter_bundle", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TestMacosBundle(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "darwin", "Apple bundle unavailable")
    def test_filter_is_valid_and_idempotent(self):
        text = pathlib.Path("/etc/ssl/cert.pem").read_text()
        result = module.filter_bundle(text)
        self.assertEqual(module.filter_bundle(result), result)
        self.assertNotIn("=== /C=IN/OU=emSign PKI/O=eMudhra Technologies Limited/CN=emSign ECC Root CA - G3\n", result)

    def test_invalid_bundle_fails_closed(self):
        with self.assertRaises(ssl.SSLError):
            module.filter_bundle("not a CA bundle")

    @unittest.skipUnless(sys.platform == "darwin", "Apple bundle unavailable")
    def test_apply_check_and_idempotency(self):
        original = pathlib.Path("/etc/ssl/cert.pem").read_text()
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "cert.pem"
            path.write_text(original)
            expected = module.filter_bundle(original)
            self.assertEqual(module.apply_bundle(path, check=True), original != expected)
            self.assertEqual(path.read_text(), original)
            module.apply_bundle(path)
            self.assertEqual(path.read_text(), expected)
            self.assertFalse(module.apply_bundle(path))
