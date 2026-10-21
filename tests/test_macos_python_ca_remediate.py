import importlib.util
from pathlib import Path
import unittest
import tomllib

spec=importlib.util.spec_from_file_location('remediate_ca',Path(__file__).parents[1]/'roles/macos_python_ca_remediate/files/remediate_ca.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class TestMacPythonCA(unittest.TestCase):
    def test_lock_only_certifi_changes(self):
        original='version = 1\n\n'+module.STANZA.replace('2026.10.19','2026.2.25')+'[[package]]\nname = "unrelated"\nversion = "1.2.3"\n'
        result=module.patch_lock(original)
        self.assertTrue(result.endswith('[[package]]\nname = "unrelated"\nversion = "1.2.3"\n'))
        self.assertEqual(tomllib.loads(result)['package'][0]['version'],module.TARGET)
        self.assertEqual(module.patch_lock(result),result)

    def test_absent_duplicate_private_registry_rejected(self):
        for text in ('version = 1',module.STANZA+module.STANZA,module.STANZA.replace('2026.10.19','2026.2.25').replace('https://pypi.org/simple','https://example.invalid/simple')):
            with self.assertRaises(ValueError):module.patch_lock(text)

    def test_prerelease_is_not_assumed_safe(self):
        with self.assertRaises(ValueError):module.version('2026.10.19.dev1')

    def test_check_mode_and_absent_package_do_not_write(self):
        import json
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);env=root/'env';env.mkdir();(env/'pyvenv.cfg').write_text('home = /example')
            info={'prefix':str(env),'packages':{'certifi':'2026.2.25','pip':None,'sigstore':None}}
            with patch.object(module,'run',side_effect=[json.dumps(info),'uv 0.13.4']),patch.object(Path,'home',return_value=root):
                module.remediate(env,check=True)
            self.assertFalse((root/'.local').exists())
            info['packages']['certifi']=None
            with patch.object(module,'run',side_effect=[json.dumps(info),'uv 0.13.4']),patch.object(Path,'home',return_value=root):
                module.remediate(env)
            self.assertFalse((root/'.local').exists())

    def test_apply_receipts_lock_metadata_and_hashed_no_deps_install(self):
        import json
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);env=root/'env';env.mkdir();(env/'pyvenv.cfg').write_text('home = /example')
            lock=root/'uv.lock';original='version = 1\n\n'+module.STANZA.replace('2026.10.19','2026.2.25')
            lock.write_text(original);lock.chmod(0o755);before=lock.stat();installed=False
            def fake_run(*args):
                nonlocal installed
                if args==(module.UV,'--version'):return 'uv 0.13.4'
                if args[-1]==module.INSPECT:
                    return json.dumps({'prefix':str(env),'packages':{'certifi':module.TARGET if installed else '2026.2.25','pip':None,'sigstore':None}})
                if args[-1]==module.VERIFY:return '{"verified_ca_count": 100}'
                self.assertEqual(args[:3],(module.UV,'pip','install'))
                self.assertIn('--no-deps',args);self.assertIn('--require-hashes',args)
                self.assertIn(module.HASH,Path(args[-1]).read_text())
                installed=True;return ''
            with patch.object(module,'run',side_effect=fake_run),patch.object(Path,'home',return_value=root):
                module.remediate(env,lock)
            receipts=list((root/'.local/state/managed-python-ca').glob('*.json'))
            self.assertEqual(len(receipts),1)
            receipt=receipts[0];backup=receipt.with_suffix('.uv.lock')
            self.assertEqual(receipt.stat().st_mode & 0o777,0o600)
            self.assertEqual(backup.stat().st_mode & 0o777,0o600)
            self.assertEqual(backup.read_text(),original)
            self.assertEqual(lock.stat().st_mode & 0o777,0o755)
            self.assertEqual((lock.stat().st_uid,lock.stat().st_gid),(before.st_uid,before.st_gid))
            self.assertEqual(json.loads(receipt.read_text())['lock_sha256'],module.hashlib.sha256(original.encode()).hexdigest())

    def test_already_remediated_lock_preserves_resolution_policy(self):
        text = 'version = 1\n[options]\nexclude-newer = "2026-10-01T00:00:00Z"\n\n' + module.STANZA
        self.assertEqual(module.patch_lock(text), text)

    def test_outdated_lock_rejects_package_resolution_policy(self):
        text = 'version = 1\n[options]\nexclude-newer-package = {certifi = "2026-10-01T00:00:00Z"}\n\n' + module.STANZA.replace('2026.10.19', '2026.2.25')
        with self.assertRaises(ValueError):
            module.patch_lock(text)
