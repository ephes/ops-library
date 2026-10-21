import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('activate', Path(__file__).parents[1] / 'roles/container_ca_activate/files/activate.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TestActivation(unittest.TestCase):
    def fixture(self, root):
        source = root / 'compose.yml'
        source.write_text('services: {}')
        store = root / 'store'
        store.mkdir()
        (store / 'bundle.pem').write_text((Path(__file__).parent / 'fixtures/activation-ca.txt').read_text())
        (store / 'empty').mkdir()
        (store / 'manifest.json').write_text(json.dumps({'image': 'sha256:pinned'}))
        projects = [{'project': 'example', 'directory': str(root), 'files': [str(source)],
                     'containers': [{'name': 'example-server', 'store': str(store), 'node': True}]}]
        state = {'Name': '/example-server', 'Image': 'sha256:pinned',
                 'Config': {'Env': ['NODE_OPTIONS=--max-old-space-size=1536'], 'Labels': {
                     'com.docker.compose.project': 'example', 'com.docker.compose.service': 'server',
                     'com.docker.compose.config-hash': 'original-hash'}}, 'State': {'Running': True}}
        return projects, state

    def runner(self, state, calls, failure=None):
        def execute(argv):
            calls.append(argv)
            if argv[:2] == ['docker', 'inspect']:
                return json.dumps([state])
            if argv[:2] == ['docker', 'ps']:
                return 'example-server\n'
            if '--hash' in argv:
                return 'server original-hash\n'
            if failure:
                failure(argv)
            return ''
        return execute

    def test_success_preserves_bits_and_restarts_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); projects, state = self.fixture(root); calls = []
            receipt = module.transaction(projects, root / 'receipt', self.runner(state, calls), lambda *a: None)
            overlay = json.loads((receipt / 'active-0.json').read_text())['services']['server']
            self.assertEqual(overlay['image'], state['Image'])
            self.assertEqual(overlay['environment']['NODE_OPTIONS'], '--max-old-space-size=1536 --use-openssl-ca')
            self.assertEqual(overlay['volumes'][0]['bind'], {'create_host_path': False})
            self.assertEqual(sum(c == ['systemctl', 'restart', 'docker.service'] for c in calls), 1)
            self.assertTrue(all('never' in c and '--no-build' in c for c in calls if 'create' in c))
            self.assertEqual(json.loads((receipt / 'result.json').read_text())['status'], 'activated')
            self.assertEqual((receipt / 'original-inspect.json').stat().st_mode & 0o777, 0o600)

    def test_configuration_drift_fails_before_receipt_or_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); projects, state = self.fixture(root); calls = []
            state['Config']['Labels']['com.docker.compose.config-hash'] = 'changed'
            with self.assertRaises(ValueError):
                module.transaction(projects, root / 'receipt', self.runner(state, calls))
            self.assertFalse((root / 'receipt').exists())
            self.assertFalse(any('stop' in c or 'create' in c or 'restart' in c for c in calls))

    def test_failed_active_create_restores_original_image_and_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); projects, state = self.fixture(root); calls = []; injected = False
            def fail(argv):
                nonlocal injected
                if 'create' in argv and any('active-0' in x for x in argv):
                    injected = True
                    raise RuntimeError('injected active create failure')
            with self.assertRaisesRegex(RuntimeError, 'injected'):
                module.transaction(projects, root / 'receipt', self.runner(state, calls, fail), lambda *a: None)
            self.assertTrue(injected)
            self.assertTrue(any('create' in c and any('rollback-0' in x for x in c) for c in calls))
            rollback = json.loads((root / 'receipt/rollback-0.json').read_text())
            self.assertEqual(rollback, {'services': {'server': {'image': 'sha256:pinned'}}})
            self.assertEqual(sum(c == ['systemctl', 'restart', 'docker.service'] for c in calls), 1)
            self.assertEqual(json.loads((root / 'receipt/result.json').read_text())['status'], 'rolled_back')

    def test_failed_health_recovers_without_second_daemon_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); projects, state = self.fixture(root); calls = []; health_calls = 0
            def health(*args):
                nonlocal health_calls
                health_calls += 1
                if health_calls == 1:
                    raise RuntimeError('injected health failure')
            with self.assertRaisesRegex(RuntimeError, 'health'):
                module.transaction(projects, root / 'receipt', self.runner(state, calls), health)
            self.assertEqual(health_calls, 2)
            self.assertEqual(sum(c == ['systemctl', 'restart', 'docker.service'] for c in calls), 1)

    def test_conflicting_node_mode_and_stale_store_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); projects, state = self.fixture(root)
            state['Config']['Env'] = ['NODE_OPTIONS=--use-system-ca']
            with self.assertRaises(ValueError):
                module.overlay_for(projects[0], {'example-server': state})
            state['Config']['Env'] = []
            state['Image'] = 'sha256:changed'
            with self.assertRaises(ValueError):
                module.overlay_for(projects[0], {'example-server': state})

    def test_shared_check_preflight_requires_entire_running_fleet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); projects, state = self.fixture(root); calls = []
            normal = self.runner(state, calls)
            def execute(argv):
                if argv[:2] == ['docker', 'ps']:
                    return 'example-server\nother-running-container\n'
                return normal(argv)
            with self.assertRaisesRegex(ValueError, 'entire running fleet'):
                module.preflight(projects, execute)
            self.assertFalse(any('stop' in c or 'create' in c for c in calls))

    def test_recovery_failure_keeps_outcome_and_restart_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); projects, state = self.fixture(root); calls = []; faults = []
            def fail(argv):
                if 'create' in argv:
                    faults.append(argv)
                    raise RuntimeError('injected create failure')
            with self.assertRaisesRegex(RuntimeError, 'injected'):
                module.transaction(projects, root / 'receipt', self.runner(state, calls, fail), lambda *a: None)
            self.assertEqual(len(faults), 2)
            result = json.loads((root / 'receipt/result.json').read_text())
            self.assertEqual(result['status'], 'recovery_failed')
            self.assertEqual(result['failed_step'], 'create-0')
            self.assertEqual(result['step'], 'recovery_create-0')
            self.assertFalse(result['docker_restart_attempted'])

    def test_status_storage_failure_does_not_block_recovery(self):
        import contextlib
        import io
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); projects, state = self.fixture(root); calls = []; health_calls = 0; writes = 0
            original_write = Path.write_text
            def write(path, *args, **kwargs):
                nonlocal writes
                if path.name == 'result.json':
                    writes += 1
                    if writes > 1:
                        raise OSError('injected full receipt filesystem')
                return original_write(path, *args, **kwargs)
            def health(*args):
                nonlocal health_calls
                health_calls += 1
                if health_calls == 1:
                    raise RuntimeError('injected health failure')
            output = io.StringIO()
            with patch.object(Path, 'write_text', write), contextlib.redirect_stdout(output):
                with self.assertRaisesRegex(RuntimeError, 'health'):
                    module.transaction(projects, root / 'receipt', self.runner(state, calls), health)
            self.assertIn("WARNING: activation receipt is unreliable", output.getvalue())
            self.assertGreater(writes, 1)
            self.assertEqual(health_calls, 2)
            self.assertTrue(any('create' in c and any('rollback-0' in x for x in c) for c in calls))
            self.assertEqual(sum(c == ['systemctl', 'restart', 'docker.service'] for c in calls), 1)
