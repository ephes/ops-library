import unittest
from tests.credential_helpers import tasks


class CredentialTests(unittest.TestCase):
    def test_mail_relay_deploy(self):
        found = [t for t in tasks('mail_relay_deploy', 'sasl.yml') if 'relay user' in t.get('name', '') and 'sasldb2' in t.get('name', '') and 'password' in str(t)]
        self.assertEqual(len(found), 2)
        for task in found:
            command = task['ansible.builtin.command']
            self.assertEqual(command['stdin'], '{{ mail_relay_sasl_password }}')
            self.assertNotIn('password', str(command['argv']))
            self.assertTrue(task['no_log'])
