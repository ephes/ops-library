"""Regression checks for migration rejection, dependency recovery and deletion gates."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'roles/host_storage_migrate/files/migrate.py'
spec = importlib.util.spec_from_file_location('host_storage_migrate', SCRIPT)
assert spec is not None and spec.loader is not None
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)

CONFIG = {'mount': '/mnt/data', 'uuid': 'test-uuid', 'root': '/mnt/data/host',
          'sources': ['/opt/backups', '/var/lib/docker', '/var/lib/containerd'],
          'cache_bytes': 10000000000}


class StorageMigrationTests(unittest.TestCase):
    def test_unsupported_split_nested_and_duplicate_paths_are_rejected(self):
        for values in [
            {'sources': ['/var/lib/docker']}, {'sources': ['/etc', '/var/lib/docker', '/var/lib/containerd']},
            {'sources': CONFIG['sources'] + ['/opt/backups']},
            {'root': '/mnt/data'}, {'root': '/mnt/other'}, {'root': '/mnt/data/../bad'},
            {'root': '/mnt/data/a b'}, {'cache_bytes': True}, {'cache_bytes': 0},
        ]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                migration.validate({**CONFIG, **values})

    def test_missing_or_wrong_disk_never_passes_mount_validation(self):
        for rows in [[], [{'target': '/mnt/data', 'uuid': 'other', 'options': 'rw'}],
                     [{'target': '/', 'uuid': 'test-uuid', 'options': 'rw'}],
                     [{'target': '/mnt/data', 'uuid': 'test-uuid', 'options': 'ro'}]]:
            with self.subTest(rows=rows), patch.object(migration, 'run', return_value=json.dumps({'filesystems': rows})):
                with self.assertRaises(RuntimeError):
                    migration.external(CONFIG)

    def test_transitive_service_stop_closure_does_not_include_unrelated_services(self):
        units = {
            'docker.service': {}, 'docker.socket': {}, 'containerd.service': {},
            'runtime.service': {'Requires': ['docker.service']},
            'web.service': {'BindsTo': ['runtime.service']},
            'agent.service': {'PartOf': ['web.service']},
            'wants.service': {'Wants': ['docker.service']},
            'ordered.service': {'After': ['docker.service']},
            'unrelated.service': {'After': ['network.target']},
        }
        self.assertEqual(migration.closure(units, set(migration.ENGINES)),
                         ['agent.service', 'containerd.service', 'docker.service',
                          'docker.socket', 'ordered.service', 'runtime.service', 'wants.service', 'web.service'])

    def test_daemon_merge_keeps_unrelated_settings_and_removes_default_gc_floor(self):
        original = {'log-driver': 'local', 'features': {'containerd-snapshotter': True},
                    'builder': {'other': 'keep', 'gc': {'defaultKeepStorage': '20GB'}}}
        before = copy.deepcopy(original)
        result = migration.daemon_config(original, 10000000000)
        self.assertEqual(original, before)
        self.assertEqual(result['log-driver'], 'local')
        self.assertEqual(result['features'], before['features'])
        self.assertEqual(result['builder']['other'], 'keep')
        self.assertEqual(result['builder']['gc'], {'enabled': True, 'policy': [
            {'all': True, 'reservedSpace': '0B', 'maxUsedSpace': '10000000000'}]})

    def test_container_recreation_allowed_but_missing_changed_or_unhealthy_rejected(self):
        baseline = {'app': {'image': 'sha256:old', 'health': 'healthy'}}
        migration.check_containers(baseline, baseline)
        for current in [{}, {'app': {'image': 'sha256:new', 'health': 'healthy'}},
                        {'app': {'image': 'sha256:old', 'health': 'starting'}}]:
            with self.subTest(current=current), self.assertRaises(RuntimeError):
                migration.check_containers(baseline, current)

    def test_consumers_fully_stop_before_docker_then_containerd_and_start_in_reverse(self):
        units = ['containerd.service', 'app.service', 'docker.service', 'docker.socket']
        self.assertEqual(migration.service_groups(units, starting=False),
                         [['app.service'], ['docker.socket', 'docker.service'], ['containerd.service']])
        self.assertEqual(migration.service_groups(units, starting=True),
                         [['containerd.service'], ['docker.socket', 'docker.service'], ['app.service']])
        self.assertEqual(migration.service_groups([], starting=False), [])

    def make_tool(self, directory):
        with patch.object(migration, 'STATE_DIR', Path(directory).resolve()):
            tool = migration.Migration(CONFIG)
        tool.save = lambda: None
        tool.state = {'config': CONFIG, 'phase': 'prepared', 'files': {},
                      'sources': {}, 'renamed': [], 'installed': [], 'enabled': [],
                      'daemon': None, 'daemon_metadata': None, 'units': migration.ENGINES,
                      'containers': {}}
        return tool

    def test_failed_checksum_rolls_back_without_renaming_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            tool = self.make_tool(directory)
            source = Path(directory).resolve() / 'source'
            source.mkdir()
            (source / 'important').write_text('retained')
            tool.sources = [source]
            tool.state['sources'] = {str(source): migration.identity(source)}
            candidate = Path(directory) / 'daemon.candidate.json'
            candidate.write_text(json.dumps(migration.daemon_config({}, CONFIG['cache_bytes'])))
            tool.copy = lambda **kw: (_ for _ in ()).throw(RuntimeError('checksum mismatch')) if kw.get('verify') else None
            with (patch.object(migration, 'external'),
                  patch.object(migration, 'STATE_DIR', Path(directory)),
                  patch.object(migration, 'active_units', side_effect=[{'docker.service': {}}, {}]),
                  patch.object(migration, 'containers', return_value={}),
                  patch.object(migration, 'mounted_below', return_value=False),
                  patch.object(migration, 'run', return_value=''),
                  patch.object(tool, 'rollback') as rollback):
                with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                    tool.cutover()
                rollback.assert_called_once()
            self.assertEqual((source / 'important').read_text(), 'retained')
            self.assertFalse(tool.previous(source).exists())

    def test_early_rollback_does_not_stop_uninstalled_mount_units(self):
        with tempfile.TemporaryDirectory() as directory:
            tool = self.make_tool(directory)
            tool.state['files'] = {'/etc/systemd/system/var-lib-docker.mount': 'unused'}
            with (patch.object(migration, 'run', return_value='') as run,
                  patch.object(tool, 'restore_services') as restore,
                  patch.object(Path, 'unlink')):
                tool.rollback()
            commands = [call.args[0] for call in run.call_args_list]
            self.assertNotIn(['systemctl', 'stop', 'var-lib-docker.mount'], commands)
            restore.assert_called_once()
            self.assertEqual(tool.state['phase'], 'rolled_back')

    def test_rollback_continues_after_reload_failure_and_handles_empty_units(self):
        for units in [[], ['docker.service']]:
            with self.subTest(units=units), tempfile.TemporaryDirectory() as directory:
                tool = self.make_tool(directory)
                tool.state['units'] = units
                def command(args, **kwargs):
                    if units and args == ['systemctl', 'daemon-reload']:
                        raise RuntimeError('reload failed')
                    return ''
                with (patch.object(migration, 'run', side_effect=command) as run,
                      patch.object(tool, 'restore_services') as restore,
                      patch.object(Path, 'unlink')):
                    if units:
                        with self.assertRaisesRegex(RuntimeError, 'reload failed'):
                            tool.rollback()
                    else:
                        tool.rollback()
                    if units:
                        restore.assert_not_called()
                    else:
                        restore.assert_called_once()
                stops = [x.args[0] for x in run.call_args_list
                         if x.args[0][:2] == ['systemctl', 'stop']]
                self.assertEqual(stops, [])

    def test_recovery_timeout_can_change_without_allowing_storage_identity_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'state.json').write_text(json.dumps({'config': CONFIG, 'phase': 'needs_attention'}))
            with patch.object(migration, 'STATE_DIR', base):
                tool = migration.Migration({**CONFIG, 'health_timeout': 600})
                self.assertEqual(tool.state['config']['health_timeout'], 600)
                with self.assertRaisesRegex(RuntimeError, 'configuration differs'):
                    migration.Migration({**CONFIG, 'uuid': 'changed-uuid'})

    def test_exposed_external_storage_can_never_roll_back_to_stale_data(self):
        with tempfile.TemporaryDirectory() as directory:
            tool = self.make_tool(directory)
            tool.state['external_exposed'] = True
            with patch.object(migration, 'run') as run:
                with self.assertRaisesRegex(RuntimeError, 'new writes'):
                    tool.rollback()
                run.assert_not_called()

    def test_health_failure_after_exposure_keeps_external_data_for_forward_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            tool = self.make_tool(directory)
            source = base / 'source'
            source.mkdir()
            (source / 'important').write_text('old data')
            tool.sources = [source]
            tool.state['sources'] = {str(source): migration.identity(source)}
            (base / 'daemon.candidate.json').write_text(json.dumps(migration.daemon_config({}, CONFIG['cache_bytes'])))
            def activate():
                tool.state['external_exposed'] = True
                raise RuntimeError('health not ready')
            with (patch.object(migration, 'STATE_DIR', base),
                  patch.object(migration, 'external'),
                  patch.object(migration, 'active_units', side_effect=[{'docker.service': {}}, {}]),
                  patch.object(migration, 'containers', return_value={}),
                  patch.object(migration, 'mounted_below', return_value=False),
                  patch.object(migration, 'run', return_value=''),
                  patch.object(tool, 'copy'), patch.object(tool, 'activate', side_effect=activate),
                  patch.object(tool, 'rollback') as rollback):
                with self.assertRaisesRegex(RuntimeError, 'health not ready'):
                    tool.cutover()
                rollback.assert_not_called()
            self.assertEqual(tool.state['phase'], 'needs_attention')
            self.assertEqual((tool.previous(source) / 'important').read_text(), 'old data')

    def test_successful_cutover_checks_units_not_dropins_and_starts_automount_first(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            tool = self.make_tool(directory)
            source = base / 'source'
            source.mkdir()
            (source / 'important').write_text('keep')
            tool.sources = [source]
            tool.root = base / 'external'
            tool.root.mkdir()
            tool.state['sources'] = {str(source): migration.identity(source)}
            systemd = base / 'units'
            tool.state['files'] = {
                str(systemd / 'opt-backups.mount'): 'test',
                str(systemd / 'opt-backups.automount'): 'test',
                str(systemd / 'docker.service.d/90-host-storage.conf'): 'test',
            }
            (base / 'daemon.candidate.json').write_text(json.dumps(migration.daemon_config({}, CONFIG['cache_bytes'])))
            commands = []
            verify_environments = []
            def command(args, **kwargs):
                commands.append(args)
                if args == ['systemd-analyze', 'unit-paths']:
                    return '/run/systemd/generator\n/usr/lib/systemd/system\n'
                if args[:2] == ['systemd-analyze', 'verify']:
                    verify_environments.append(kwargs['env'])
                return ''
            with (patch.object(migration, 'STATE_DIR', base),
                  patch.object(migration, 'SYSTEMD', systemd),
                  patch.object(migration, 'DAEMON', base / 'etc/docker/daemon.json'),
                  patch.object(migration, 'external'),
                  patch.object(migration, 'active_units', side_effect=[{'docker.service': {}}, {}]),
                  patch.object(migration, 'containers', return_value={}),
                  patch.object(migration, 'mounted_below', return_value=False),
                  patch.object(migration, 'run', side_effect=command),
                  patch.object(tool, 'copy'), patch.object(tool, 'mount_checks'),
                  patch.object(tool, 'restore_services')):
                tool.cutover()
            verify = next(x for x in commands if x[:2] == ['systemd-analyze', 'verify'])
            self.assertTrue(all(not x.endswith('.conf') for x in verify[2:]))
            self.assertIn('docker.service', verify)
            first_stop = next(i for i, x in enumerate(commands) if x[:2] == ['systemctl', 'stop'])
            self.assertLess(commands.index(verify), first_stop)
            self.assertIn('/run/systemd/generator', verify_environments[0]['SYSTEMD_UNIT_PATH'].split(':'))
            self.assertLess(commands.index(['systemctl', 'start', 'opt-backups.automount']),
                            commands.index(['systemctl', 'start', 'opt-backups.mount']))
            self.assertIn(['systemctl', 'enable', 'opt-backups.automount'], commands)
            self.assertNotIn(['systemctl', 'enable', 'opt-backups.mount'], commands)
            self.assertEqual(tool.state['phase'], 'verified')
            self.assertEqual((tool.previous(source) / 'important').read_text(), 'keep')

    def test_finalize_refuses_replaced_old_directory_and_nested_mount(self):
        for changed_inode, nested_mount in [(True, False), (False, True)]:
            with self.subTest(changed_inode=changed_inode), tempfile.TemporaryDirectory() as directory:
                tool = self.make_tool(directory)
                source = Path(directory).resolve() / 'source'
                old = tool.previous(source)
                old.mkdir()
                (old / 'important').write_text('keep')
                tool.sources = [source]
                original_identity = migration.identity(old)
                tool.state.update(phase='verified', sources={str(source):
                                  [0, 0] if changed_inode else original_identity})
                with (patch.object(tool, 'verify'),
                      patch.object(migration, 'mounted_below', return_value=nested_mount),
                      patch.object(migration.shutil, 'rmtree') as remove):
                    with self.assertRaises(RuntimeError):
                        tool.finalize()
                    remove.assert_not_called()
                self.assertEqual((old / 'important').read_text(), 'keep')

    def test_atomic_write_preserves_existing_file_on_collision(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config'
            path.write_text('original')
            path.with_name('config.host-storage-new').write_text('someone else')
            with self.assertRaises(FileExistsError):
                migration.write(path, 'replacement')
            self.assertEqual(path.read_text(), 'original')

    def rollback_fixture(self, directory):
        base = Path(directory).resolve()
        tool = self.make_tool(directory)
        tool.root = base / 'external'
        tool.root.mkdir()
        source = base / 'source'
        source.mkdir()
        tool.sources = [source]
        tool.state.update(phase='rolled_back', root_identity=migration.identity(tool.root),
                          sources={str(source): migration.identity(source)},
                          files={str(base / 'source.mount'): 'unit'},
                          installed=[str(base / 'source.mount')], renamed=[str(source)],
                          enabled=['source.mount'])
        return base, tool, source

    def test_verified_rollback_can_reprepare_and_preserves_each_prior_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            base, tool, source = self.rollback_fixture(directory)
            with (patch.object(migration, 'STATE_DIR', base),
                  patch.object(migration, 'DAEMON', base / 'daemon.json'),
                  patch.object(migration, 'external'), patch.object(tool, 'verify_units'),
                  patch.object(tool, 'copy') as copy):
                tool.prepare()
                self.assertEqual(tool.state['phase'], 'prepared')
                self.assertEqual(tool.state['installed'], [])
                self.assertEqual(tool.state['renamed'], [])
                self.assertEqual(tool.state['enabled'], [])
                receipts = list(base.glob('state-before-reprepare-*.json'))
                self.assertEqual(len(receipts), 1)
                self.assertEqual(json.loads(receipts[0].read_text())['phase'], 'rolled_back')
                tool.state['phase'] = 'rolled_back'
                tool.prepare()
                self.assertEqual(len(list(base.glob('state-before-reprepare-*.json'))), 2)
                self.assertEqual(copy.call_count, 2)

    def test_reprepare_rejects_every_dirty_or_ambiguous_rollback_boundary(self):
        for condition in ['exposed', 'unit', 'daemon', 'source', 'previous', 'root', 'phase']:
            with self.subTest(condition=condition), tempfile.TemporaryDirectory() as directory:
                base, tool, source = self.rollback_fixture(directory)
                if condition == 'exposed': tool.state['external_exposed'] = True
                if condition == 'unit': (base / 'source.mount').write_text('leftover')
                if condition == 'daemon': (base / 'daemon.json').write_text('{}')
                if condition == 'source': tool.state['sources'][str(source)] = [0, 0]
                if condition == 'previous': tool.previous(source).mkdir()
                if condition == 'root': tool.state['root_identity'] = [0, 0]
                if condition == 'phase': tool.state['phase'] = 'rollback_failed'
                with (patch.object(migration, 'STATE_DIR', base),
                      patch.object(migration, 'DAEMON', base / 'daemon.json'),
                      patch.object(migration, 'external'), patch.object(tool, 'copy') as copy):
                    with self.assertRaises(RuntimeError): tool.prepare()
                    copy.assert_not_called()
                self.assertEqual(list(base.glob('state-before-reprepare-*.json')), [])

    def test_unit_preflight_failure_never_stops_services(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            tool = self.make_tool(directory)
            source = base / 'source'
            source.mkdir()
            tool.sources = [source]
            tool.state['sources'] = {str(source): migration.identity(source)}
            (base / 'daemon.candidate.json').write_text(json.dumps(migration.daemon_config({}, CONFIG['cache_bytes'])))
            with (patch.object(migration, 'STATE_DIR', base),
                  patch.object(migration, 'DAEMON', base / 'daemon.json'),
                  patch.object(migration, 'external'), patch.object(migration, 'run', return_value='') as run,
                  patch.object(tool, 'verify_units', side_effect=RuntimeError('invalid unit dependency')),
                  patch.object(migration, 'active_units') as active):
                with self.assertRaisesRegex(RuntimeError, 'invalid unit dependency'):
                    tool.cutover()
                active.assert_not_called()
                self.assertFalse(any(c.args[0][:2] == ['systemctl', 'stop'] for c in run.call_args_list))
            self.assertEqual(tool.state['phase'], 'prepared')

    def test_failed_command_keeps_diagnostic_private(self):
        import sys
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            with patch.object(migration, 'STATE_DIR', base):
                with self.assertRaises(RuntimeError) as caught:
                    migration.run([sys.executable, '-c', 'import sys; print("private diagnostic"); sys.exit(2)'])
            files = list(base.glob('command-failure-*.log'))
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].read_text(), 'private diagnostic\n')
            self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
            self.assertNotIn('private diagnostic', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
