from tests.credential_helpers import ENV, tasks
import subprocess
import tempfile
import unittest
from pathlib import Path


class CredentialTests(unittest.TestCase):
    def test_minecraft_java_backup(self):
        found = [t for t in tasks('minecraft_java_backup', 'main.yml') if t.get('name') in ('Disable auto-save', 'Flush world to disk', 'Re-enable auto-save')]
        self.assertEqual(len(found), 3)
        password = "space ' $() ` ; \\\\ : password"
        with tempfile.TemporaryDirectory() as tmp:
            client = Path(tmp) / 'mcrcon'
            client.write_text('#!/bin/sh\nprintf "%s" "$MCRCON_PASS"\n')
            client.chmod(0o700)
            for task in found:
                self.assertNotIn('environment', task)
                self.assertTrue(task['no_log'])
                self.assertEqual(task['args']['stdin'], '{{ minecraft_java_rcon_password }}')
                command = ENV.from_string(task['ansible.builtin.shell']).render(minecraft_java_rcon_port=25575)
                self.assertNotIn(password, command)
                command = command.replace('/usr/local/bin/mcrcon', str(client))
                result = subprocess.run(['/bin/sh', '-c', command], input=password+'\n', text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, password)

    def test_failure_reporting_preserves_abort_and_always(self):
        all_tasks = tasks('minecraft_java_backup', 'main.yml')
        for label in ('save-off', 'save-all'):
            block = next(t for t in all_tasks if t.get('name') == 'main | Coordinate '+label)
            self.assertIn('ansible.builtin.fail', block['rescue'][-1])
        backup = next(t for t in all_tasks if t.get('name') == 'Perform backup with save coordination')
        self.assertIn('Re-enable auto-save', [t['name'] for t in backup['always']])
