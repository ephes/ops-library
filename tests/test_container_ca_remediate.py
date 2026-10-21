import importlib.util
from pathlib import Path
import ssl
import unittest

spec = importlib.util.spec_from_file_location("prepare_store", Path(__file__).parents[1] / "roles/container_ca_remediate/files/prepare_store.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TestContainerCA(unittest.TestCase):
    def test_only_blocked_fingerprints_removed(self):
        fixture = Path(__file__).parent / "fixtures/container-ca.txt"
        original = fixture.read_bytes()
        bundle, removed, retained = module.collect_certificates([original, original])
        self.assertEqual(set(removed), module.BLOCKED)
        self.assertEqual(len(retained), 1)
        self.assertEqual(module.collect_certificates([bundle])[0], bundle)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cadata=bundle.decode())
        self.assertEqual(len(context.get_ca_certs()), 1)

    def test_empty_store_fails(self):
        with self.assertRaises(ValueError):
            module.collect_certificates([b"not certificates"])

    def test_prepare_check_manifest_and_idempotency(self):
        import io
        import json
        import tarfile
        import tempfile
        from unittest.mock import patch
        data = (Path(__file__).parent / "fixtures/container-ca.txt").read_bytes()
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as target:
            member = tarfile.TarInfo("etc/ssl/certs/ca-certificates.crt")
            member.size = len(data)
            target.addfile(member, io.BytesIO(data))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "stores"
            with patch.object(module, "run", side_effect=[b'"sha256:test"', archive.getvalue()]):
                module.prepare("test", check=True, root_dir=root)
            self.assertFalse(root.exists())
            with patch.object(module, "run", side_effect=[b'"sha256:test"', archive.getvalue()]):
                module.prepare("test", root_dir=root)
            manifest = json.loads((root / "test/manifest.json").read_text())
            self.assertEqual(set(manifest["removed_sha256"]), module.BLOCKED)
            self.assertEqual(manifest["image"], "sha256:test")
            stamp = (root / "test/bundle.pem").stat().st_mtime_ns
            with patch.object(module, "run", side_effect=[b'"sha256:test"', archive.getvalue()]):
                module.prepare("test", root_dir=root)
            self.assertEqual((root / "test/bundle.pem").stat().st_mtime_ns, stamp)
            (root / "test/empty/unexpected.pem").write_text("unexpected")
            with patch.object(module, "run", side_effect=[b'"sha256:test"', archive.getvalue()]):
                with self.assertRaises(ValueError):
                    module.prepare("test", root_dir=root)

    def test_trust_annotated_material_fails_closed(self):
        with self.assertRaises(ValueError):
            module.collect_certificates([b"-----BEGIN TRUSTED CERTIFICATE-----"])
