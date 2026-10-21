import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("repair_ca", Path(__file__).parents[1] / "roles/linuxserver_ca_remediate/files/repair_ca.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TestLinuxserverCA(unittest.TestCase):
    def test_native_store_preserves_other_roots_and_repeats(self):
        fixture = (Path(__file__).parent / "fixtures/linuxserver-ca.txt").read_bytes()
        blocks = module.PEM.findall(fixture)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = root / "source", root / "output"
            source.mkdir(); output.mkdir()
            for index, block in enumerate(blocks):
                (source / f"{index}.crt").write_bytes(block)
            def regenerate():
                for existing in output.iterdir():
                    existing.unlink()
                for path in source.glob("*.crt"):
                    (output / path.name).write_bytes(path.read_bytes())
            found = module.repair((source,), (output,), regenerate)
            self.assertEqual(len(found), 1)
            self.assertFalse(found & module.BLOCKED)
            self.assertEqual(module.repair((source,), (output,), regenerate), found)

    def test_unknown_layout_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                module.repair((Path(temporary),), (), lambda: None)

    def test_stale_generated_root_is_rejected(self):
        fixture = (Path(__file__).parent / "fixtures/linuxserver-ca.txt").read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            source, output = Path(temporary) / "source", Path(temporary) / "output"
            source.mkdir(); output.mkdir()
            (source / "mixed.crt").write_bytes(fixture)
            (output / "stale.pem").write_bytes(fixture)
            with self.assertRaises(ValueError):
                module.repair((source,), (output,), lambda: None)
            remaining = module.PEM.findall((source / "mixed.crt").read_bytes())
            self.assertEqual(len(remaining), 1)
            self.assertNotIn(module.fingerprint(remaining[0]), module.BLOCKED)

    def test_trust_annotated_native_store_fails_closed(self):
        fixture=(Path(__file__).parent/'fixtures/linuxserver-ca.txt').read_bytes()
        good=next(block for block in module.PEM.findall(fixture) if module.fingerprint(block) not in module.BLOCKED)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'sources';output=root/'output';source.mkdir();output.mkdir()
            (source/'good.crt').write_bytes(good)
            (output/'trusted.pem').write_bytes(b'-----BEGIN TRUSTED CERTIFICATE-----')
            with self.assertRaises(ValueError):module.repair((source,),(output,),lambda:None)

    def test_blocked_symlink_unlinks_without_touching_target(self):
        fixture=(Path(__file__).parent/'fixtures/linuxserver-ca.txt').read_bytes()
        blocks=module.PEM.findall(fixture)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'sources';source.mkdir()
            target=root/'external.crt';bad=next(block for block in blocks if module.fingerprint(block) in module.BLOCKED);target.write_bytes(bad)
            (source/'bad.crt').symlink_to(target)
            good=next(block for block in blocks if module.fingerprint(block) not in module.BLOCKED);(source/'good.crt').write_bytes(good)
            module.repair((source,),(source,),lambda:None)
            self.assertEqual(target.read_bytes(),bad)
            self.assertFalse((source/'bad.crt').is_symlink())
