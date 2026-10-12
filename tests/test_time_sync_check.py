"""The time_sync_check role reports clock problems clearly and changes nothing."""
from pathlib import Path
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / 'roles/time_sync_check'
SPEC = importlib.util.spec_from_file_location('time_sync_status', ROLE / 'files/time_sync_status.py')
status = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(status)

CHRONY_OK = '85BB1234,ntp.example.net,2,1760000000.123456789,-0.000123456,0.000010000,0.000200000,-3.251,0.001,0.030,0.012345678,0.000987654,64.9,Normal\n'
CHRONY_UNSYNCED = '7F7F0101,,0,0.000000000,0.000000000,0.000000000,0.000000000,0.000,0.000,0.000,1.000000000,1.000000000,0.0,Not synchronised\n'
CHRONY_FAR_OFF = CHRONY_OK.replace('-0.000123456', '7199.5')
TIMESYNC_STATUS = textwrap.dedent('''\
           Server: 192.0.2.1 (ntp.example.net)
    Poll interval: 34min 8s (min: 32s; max 34min 8s)
             Leap: normal
          Stratum: 2
    Root distance: 12.345ms (max: 5s)
           Offset: {offset}
            Delay: 2.345ms
    ''')


class StatusParsing(unittest.TestCase):
    def test_systemd_time_spans(self):
        for text, seconds in (
            ('+1.234ms', 0.001234), ('-543us', -0.000543), ('+12μs', 0.000012), ('0', 0.0),
            ('+2h 3min 4.5s', 7384.5), ('-1min 30s', -90.0), ('+1.5s', 1.5), ('+1d 2h', 93600.0),
        ):
            with self.subTest(text=text):
                self.assertAlmostEqual(status.parse_timespan(text), seconds, places=9)
        for text in ('', 'n/a', '+5 parsecs', '12', '1s garbage'):
            with self.subTest(text=text):
                self.assertIsNone(status.parse_timespan(text))

    def test_timedatectl_and_timesyncd_output(self):
        self.assertIs(status.parse_timedatectl_show('NTPSynchronized=yes\n'), True)
        self.assertIs(status.parse_timedatectl_show('NTP=yes\nNTPSynchronized=no\n'), False)
        self.assertIsNone(status.parse_timedatectl_show('Failed to connect to bus\n'))
        self.assertAlmostEqual(status.parse_timesync_status(TIMESYNC_STATUS.format(offset='+1.234ms')), 0.001234)
        self.assertIsNone(status.parse_timesync_status('       Server: n/a\n'))

    def test_chrony_tracking(self):
        self.assertEqual(status.parse_chrony_tracking(CHRONY_OK), (-0.000123456, True))
        self.assertEqual(status.parse_chrony_tracking(CHRONY_UNSYNCED), (0.0, False))
        self.assertEqual(status.parse_chrony_tracking('506 Cannot talk to daemon\n'), (None, None))
        self.assertEqual(status.parse_chrony_tracking(''), (None, None))

    def evaluate(self, **facts):
        defaults = dict(kernel_synchronized=True, source='chrony', source_synchronized=True,
                        offset_seconds=0.001, max_offset_seconds=1.0)
        return status.evaluate(**{**defaults, **facts})

    def test_evaluation(self):
        self.assertEqual(self.evaluate(), ([], []))
        self.assertEqual(self.evaluate(offset_seconds=-1.0)[0], [])
        cases = (
            (dict(offset_seconds=-7200.0), 'clock offset -7200.000000s exceeds the allowed 1s'),
            (dict(kernel_synchronized=False), 'NTPSynchronized=no'),
            (dict(source=None, source_synchronized=None, offset_seconds=None), 'no time synchronization service is active'),
            (dict(source_synchronized=False), 'chrony reports that it is not synchronized'),
            (dict(kernel_synchronized=None, source_synchronized=None), 'could not confirm that chrony is synchronized'),
        )
        for facts, expected in cases:
            with self.subTest(facts=facts):
                problems, _ = self.evaluate(**facts)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(expected, problems[0])
        # timesyncd has not polled yet: synchronized, but no offset to judge.
        problems, notes = self.evaluate(source='systemd-timesyncd', source_synchronized=None, offset_seconds=None)
        self.assertEqual(problems, [])
        self.assertEqual(notes, ['systemd-timesyncd did not report an offset'])


class RoleIsReadOnly(unittest.TestCase):
    def test_only_reads(self):
        tasks = yaml.safe_load((ROLE / 'tasks/main.yml').read_text())
        allowed = {'ansible.builtin.assert', 'ansible.builtin.set_fact', 'ansible.builtin.script',
                   'ansible.builtin.debug', 'ansible.builtin.fail'}
        keywords = {'name', 'vars', 'when', 'register', 'changed_when', 'check_mode'}
        for task in tasks:
            self.assertEqual(len(set(task) - keywords), 1, task['name'])
            self.assertLessEqual(set(task) - keywords, allowed, task['name'])
        script = next(t for t in tasks if 'ansible.builtin.script' in t)
        self.assertIs(script['changed_when'], False)
        self.assertIs(script['check_mode'], False)
        self.assertFalse((ROLE / 'handlers').exists())
        source = (ROLE / 'files/time_sync_status.py').read_text()
        commands = [line for line in source.splitlines() if 'run([' in line]
        self.assertEqual(len(commands), 4, commands)
        for line in commands:
            self.assertRegex(line, r'"timedatectl", "(show|timesync-status)"|"systemctl", "is-active"|"chronyc", "-c", "tracking"')
        for word in ('set-ntp', 'set-time', 'makestep', 'restart', 'enable', 'settimeofday', 'clock_settime'):
            self.assertNotIn(word, source)


PLAYBOOK = '''
- hosts: localhost
  connection: local
  gather_facts: false
  environment:
    PATH: "{{ stub_path }}"
  tasks:
    - name: Run the check
      ansible.builtin.include_role:
        name: time_sync_check
    - name: Write the result
      ansible.builtin.copy:
        content: "{{ time_sync_check_result | to_json }}"
        dest: "{{ result_file }}"
        mode: "0600"
'''


@unittest.skipUnless(os.name == 'posix', 'needs a POSIX shell for the command stubs')
class RoleRun(unittest.TestCase):
    """Run the role on localhost against stubbed timedatectl/systemctl/chronyc."""

    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp(prefix='time-sync-check-'))
        self.addCleanup(shutil.rmtree, self.scratch)
        self.stubs = self.scratch / 'bin'
        self.stubs.mkdir()
        (self.scratch / 'play.yml').write_text(PLAYBOOK)

    def stub(self, name, body):
        path = self.stubs / name
        path.write_text('#!/bin/sh\n' + textwrap.dedent(body))
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def host(self, *, synchronized='yes', active='chrony.service', chrony=CHRONY_OK, timesync=''):
        (self.scratch / 'timesync-status').write_text(timesync)
        self.stub('timedatectl', f'''\
            case "$1" in
              show) echo "NTPSynchronized={synchronized}" ;;
              timesync-status) cat "{self.scratch}/timesync-status" ;;
              *) echo "unexpected: $*" >&2; exit 64 ;;
            esac
            ''')
        self.stub('systemctl', f'''\
            [ "$1" = is-active ] || {{ echo "unexpected: $*" >&2; exit 64; }}
            for unit in "$@"; do [ "$unit" = "{active}" ] && exit 0; done
            exit 3
            ''')
        self.stub('chronyc', f'''\
            [ "$*" = "-c tracking" ] || {{ echo "unexpected: $*" >&2; exit 64; }}
            printf '%s' '{chrony}'
            ''')

    def play(self, **extra):
        result_file = self.scratch / 'result.json'
        variables = {
            'stub_path': f'{self.stubs}:{os.environ.get("PATH", "/usr/bin:/bin")}',
            'result_file': str(result_file),
            'time_sync_check_python': sys.executable,
            **extra,
        }
        env = {**os.environ, 'ANSIBLE_ROLES_PATH': str(ROOT / 'roles'), 'ANSIBLE_NOCOLOR': '1',
               'ANSIBLE_LOCALHOST_WARNING': 'false', 'ANSIBLE_INVENTORY_UNPARSED_WARNING': 'false'}
        run = subprocess.run(
            [sys.executable, '-m', 'ansible', 'playbook', '-i', 'localhost,', str(self.scratch / 'play.yml'),
             '-e', json.dumps(variables)],
            capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL, cwd=self.scratch)
        result = json.loads(result_file.read_text()) if result_file.exists() else None
        return run, result

    def test_synchronized_chrony_host_passes(self):
        self.host()
        run, result = self.play()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertTrue(result['ok'])
        self.assertEqual(result['source'], 'chrony')
        self.assertEqual(result['problems'], [])
        self.assertAlmostEqual(result['offset_seconds'], -0.000123456)
        self.assertEqual(result['controller_skew_seconds'], 0)
        self.assertIn('changed=1 ', run.stdout)  # only this test's own result file

    def test_synchronized_timesyncd_host_passes(self):
        self.host(active='systemd-timesyncd.service', timesync=TIMESYNC_STATUS.format(offset='-250.5ms'))
        run, result = self.play()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(result['source'], 'systemd-timesyncd')
        self.assertAlmostEqual(result['offset_seconds'], -0.2505)

    def test_offset_above_threshold_fails_clearly(self):
        self.host(active='systemd-timesyncd.service', timesync=TIMESYNC_STATUS.format(offset='+2h 12.5s'))
        run, result = self.play()
        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
        self.assertIsNone(result)
        self.assertIn('Time synchronization check FAILED on localhost', run.stdout)
        self.assertIn('clock offset +7212.500000s exceeds the allowed 1s', run.stdout)
        self.assertIn('it changed nothing', run.stdout)

        run, result = self.play(time_sync_check_max_offset_seconds=7300)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertTrue(result['ok'])

    def test_unsynchronized_host_fails_or_warns(self):
        self.host(synchronized='no', chrony=CHRONY_UNSYNCED)
        run, _ = self.play()
        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
        self.assertIn('NTPSynchronized=no', run.stdout)
        self.assertIn('chrony reports that it is not synchronized', run.stdout)

        run, result = self.play(time_sync_check_fail=False)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertFalse(result['ok'])
        self.assertEqual(len(result['problems']), 2)
        self.assertIn('WARNING: time synchronization problem on localhost', run.stdout)
        self.assertIn('Continuing because time_sync_check_fail is false', run.stdout)

    def test_host_without_a_time_service_fails(self):
        self.host(active='none.service')
        run, _ = self.play()
        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
        self.assertIn('no time synchronization service is active', run.stdout)

    def test_clock_far_from_the_controller_fails_even_when_it_claims_sync(self):
        """A host two hours off that still reports NTPSynchronized=yes."""
        self.host()
        fake = self.scratch / 'python-two-hours-ahead'
        fake.write_text(textwrap.dedent(f'''\
            #!/bin/sh
            exec "{sys.executable}" - "$@" <<'PY'
            import json, runpy, sys, time
            real = time.time
            time.time = lambda: real() + 7200
            sys.argv = sys.argv[1:]
            runpy.run_path(sys.argv[0], run_name='__main__')
            PY
            '''))
        fake.chmod(0o700)
        run, _ = self.play(time_sync_check_python=str(fake))
        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
        self.assertIn('the host clock differs from the controller clock by about 7', run.stdout)
        self.assertIn('(allowed: 30s)', run.stdout)

        run, result = self.play(time_sync_check_python=str(fake), time_sync_check_controller_max_skew_seconds=0)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertTrue(result['ok'])
        self.assertGreater(result['controller_skew_seconds'], 7000)

    def test_invalid_settings_are_rejected(self):
        self.host()
        for extra in ({'time_sync_check_max_offset_seconds': 0}, {'time_sync_check_max_offset_seconds': 'soon'},
                      {'time_sync_check_controller_max_skew_seconds': -1}, {'time_sync_check_fail': 'maybe'}):
            with self.subTest(extra=extra):
                run, _ = self.play(**extra)
                self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
                self.assertIn('time_sync_check_max_offset_seconds must be a number above 0', run.stdout)

    def test_script_strict_mode_exit_status(self):
        self.host(synchronized='no')
        env = {**os.environ, 'PATH': f'{self.stubs}:{os.environ.get("PATH", "")}'}
        script = str(ROLE / 'files/time_sync_status.py')
        relaxed = subprocess.run([sys.executable, script], capture_output=True, text=True, env=env)
        strict = subprocess.run([sys.executable, script, '--strict'], capture_output=True, text=True, env=env)
        self.assertEqual((relaxed.returncode, strict.returncode), (0, 1))
        report = json.loads(strict.stdout)
        self.assertFalse(report['ok'])
        self.assertLess(abs(report['epoch'] - time.time()), 60)


if __name__ == '__main__':
    unittest.main()
