import importlib.util
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'roles/voxhelm_deploy/files/refresh_python_trust.py'
spec = importlib.util.spec_from_file_location('trust_refresh', SOURCE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class TrustRefreshTests(unittest.TestCase):
    def test_idle_database_is_read_only_and_active_work_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'db.sqlite3'
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE jobs_job(state TEXT, lease_expires_at TEXT)')
                db.execute('CREATE TABLE jobs_worker(running_job_ids TEXT)')
            before = path.read_bytes()
            self.assertFalse(any(m.idle(str(path)).values()))
            self.assertEqual(before, path.read_bytes())
            for sql in ["INSERT INTO jobs_job VALUES ('queued',NULL)",
                        "INSERT INTO jobs_job VALUES ('complete','2999-01-01')",
                        "INSERT INTO jobs_worker VALUES ('[1]')"]:
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute(sql)
                with self.assertRaisesRegex(ValueError, 'not idle'):
                    m.idle(str(path))
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute('DELETE FROM jobs_job')
                    db.execute('DELETE FROM jobs_worker')

    def test_missing_database_not_created(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'missing'
            with self.assertRaises(sqlite3.OperationalError):
                m.idle(str(path))
            self.assertFalse(path.exists())

    def test_unknown_unit_rejected_before_native_access(self):
        with self.assertRaises(ValueError):
            m.snapshot('manual-app', '/app/.venv')

    def run_refresh(self, uid, check=False):
        old = {'pid': 123, 'uid': uid, 'plist': b'original'}
        new = dict(old, pid=456)
        with patch.object(m, 'snapshot', side_effect=[old, old, new]), \
             patch.object(m, 'command', return_value=json.dumps({'certifi': '2026.10.19'})) as command, \
             patch.object(m.os, 'getuid', return_value=uid), \
             patch.object(m.os, 'kill') as kill:
            result = m.refresh('de.wersdoerfer.voxhelm', '/app/.venv', check)
            self.assertEqual(command.call_args_list[0].kwargs['uid'], uid)
            if check:
                kill.assert_not_called()
                self.assertEqual(command.call_count, 1)
                self.assertEqual(command.call_args_list[0].kwargs['uid'], uid)
            elif uid == 0:
                kill.assert_not_called()
                self.assertEqual(command.call_args.args[0], ['/bin/launchctl', 'kickstart', '-k', 'system/de.wersdoerfer.voxhelm'])
            else:
                kill.assert_called_once_with(123, m.signal.SIGTERM)
            return result

    def test_root_uses_launchctl_and_requires_new_pid(self):
        self.assertEqual(self.run_refresh(0)['new_pid'], 456)

    def test_owned_system_child_uses_signal(self):
        self.assertEqual(self.run_refresh(501)['new_pid'], 456)

    def test_check_mode_does_not_restart(self):
        self.assertTrue(self.run_refresh(501, True)['check'])

    def test_unit_drift_aborts_before_restart(self):
        with patch.object(m, 'snapshot', side_effect=[{'pid': 1, 'uid': 501}, {'pid': 2, 'uid': 501}]), \
             patch.object(m, 'command', return_value='{}'), patch.object(m.os, 'kill') as kill:
            with self.assertRaisesRegex(ValueError, 'changed'):
                m.refresh('de.wersdoerfer.voxhelm', '/app/.venv')
            kill.assert_not_called()

class ProvenanceTests(unittest.TestCase):
    def snapshot(self, executable, *, label='de.wersdoerfer.voxhelm', mode=0o100644,
                 owner=0, keepalive=True, process_uid=501, children=''):
        import plistlib
        from types import SimpleNamespace
        plist = plistlib.dumps({'Label': label, 'KeepAlive': keepalive,
                                'UserName': 'worker', 'WorkingDirectory': '/app'})
        outputs = ['state = running\npid = 123\n', f'{process_uid} {executable}\n']
        if children:
            outputs.append(children)
        with patch.object(m.Path, 'lstat', return_value=SimpleNamespace(st_mode=mode, st_uid=owner)), \
             patch.object(m.Path, 'read_bytes', return_value=plist), \
             patch.object(m.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=501)), \
             patch.object(m.os, 'getuid', return_value=501), \
             patch.object(m, 'command', side_effect=outputs):
            return m.snapshot(label, '/app/.venv')

    def test_direct_and_relative_python(self):
        self.assertEqual(self.snapshot('/app/.venv/bin/python')['pid'], 123)
        self.assertEqual(self.snapshot('.venv/bin/python3.14')['pid'], 123)

    def test_caffeinate_one_owned_python_child(self):
        result = self.snapshot('/usr/bin/caffeinate', label='de.wersdoerfer.voxhelm-remote-worker',
                               children='456 123 501 /app/.venv/bin/python\n')
        self.assertEqual(result['pid'], 456)

    def test_wrong_owner_mode_keepalive_prefix_and_wrapper_fail(self):
        cases = [dict(owner=501), dict(mode=0o100666), dict(mode=0o120777),
                 dict(keepalive=False), dict(process_uid=0)]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.snapshot('/app/.venv/bin/python', **kwargs)
        for executable in ['/app/.venv/bin/python-foreign', '/other/bin/python', '/usr/bin/caffeinate']:
            with self.subTest(executable=executable), self.assertRaises(ValueError):
                self.snapshot(executable)

    def test_caffeinate_multiple_children_rejected(self):
        with self.assertRaises(ValueError):
            self.snapshot('/usr/bin/caffeinate', label='de.wersdoerfer.voxhelm-remote-worker',
                          children='456 123 501 /app/.venv/bin/python\n457 123 501 /app/.venv/bin/python\n')

class ProbeIdentityTests(unittest.TestCase):
    def test_root_drops_probe_to_unit_owner_and_minimal_environment(self):
        from types import SimpleNamespace
        account = SimpleNamespace(pw_dir='/home/worker', pw_name='worker', pw_gid=20)
        with patch.object(m.pwd, 'getpwuid', return_value=account), \
             patch.object(m.os, 'getuid', return_value=0), \
             patch.object(m.os, 'getgrouplist', return_value=[20, 30]), \
             patch.object(m.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='ok')) as run:
            self.assertEqual(m.command(['/venv/bin/python', '-c', 'probe'], uid=501), 'ok')
            options = run.call_args.kwargs
            self.assertEqual((options['user'], options['group'], options['extra_groups']), (501, 20, []))
            self.assertEqual(options['env'], {'HOME': '/home/worker', 'USER': 'worker', 'LOGNAME': 'worker', 'PATH': '/usr/bin:/bin'})

    def test_probe_failure_reports_exception_class_without_stderr(self):
        from types import SimpleNamespace
        result = SimpleNamespace(returncode=1, stderr='private trace\nssl.SSLCertVerificationError: detail\n')
        with patch.object(m.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(ValueError, r'python \(SSLCertVerificationError\)') as error:
                m.command(['/venv/bin/python'])
            self.assertNotIn('private', str(error.exception))
