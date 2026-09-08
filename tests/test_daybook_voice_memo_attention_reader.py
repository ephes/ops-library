"""Fail-closed MinIO identity provisioning with realistic sanitized mc schemas."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('attention_reader', ROOT / 'roles' /
    'daybook_voice_memo_attention_reader_deploy' / 'files' / 'provision_reader.py')
reader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reader)


class FakeMC:
    def __init__(self):
        self.policy = None
        self.user = None
        self.policies = []
        self.calls = []
        self.failed_command = None

    def call(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if command == self.failed_command:
            raise reader.Refused('synthetic_inspection_failure')
        if command == 'policy info':
            return None if self.policy is None else {'status': 'success', 'policyInfo': {'Policy': copy.deepcopy(self.policy)}}
        if command == 'user info':
            return copy.deepcopy(self.user)
        if command == 'policy entities':
            return {'status': 'success', 'result': {'timestamp': 'synthetic',
                'userMappings': [{'user': self.user['accessKey'], 'policies': self.policies}]}}
        if command == 'policy create':
            self.policy = json.loads(kwargs['path'].read_text())
        elif command == 'user add':
            access, secret = kwargs['stdin'].splitlines()
            assert len(secret) >= 32
            self.user = {'status': 'success', 'accessKey': access, 'userStatus': 'enabled', 'policyName': ''}
        elif command == 'policy attach':
            self.user['policyName'] = reader.POLICY_NAME
            self.policies = [reader.POLICY_NAME]
        else:
            raise AssertionError(command)
        return {'status': 'success'}

    def mutations(self):
        return [c for c, _ in self.calls if c in ('policy create', 'user add', 'policy attach')]


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name).resolve()
        self.path.chmod(0o700)
        self.request = dict(access_key='daybook-attention-' + 'a' * 16,
                            secret_key='synthetic-secret-' + 'b' * 32,
                            mc_bin='/usr/local/bin/mc', alias='local', state_dir=str(self.path))
        self.mc = FakeMC()

    def test_real_ansible_validates_reader_inputs_before_any_mutation(self):
        role = ROOT / 'roles/daybook_voice_memo_attention_reader_deploy'
        validation = yaml.safe_load((role / 'tasks/main.yml').read_text())[0]
        validation.pop('no_log', None)
        prefix = 'daybook_voice_memo_attention_reader_'
        base = yaml.safe_load((role / 'defaults/main.yml').read_text())
        base.update({prefix + 'access_key': self.request['access_key'],
                     prefix + 'secret_key': self.request['secret_key']})
        cases = [({}, True), ({prefix + 'access_key': 'CHANGEME'}, False),
                 ({prefix + 'secret_key': 'CHANGEME'}, False),
                 ({prefix + 'secret_key': 'x' * 257}, False),
                 ({prefix + 'secret_key': 'x' * 40 + '\r'}, False),
                 ({prefix + 'secret_key': 'x' * 40 + '\n'}, False),
                 ({prefix + 'access_key': '-' + 'a' * 20}, False),
                 ({prefix + 'access_key': 'a' * 16}, True),
                 ({prefix + 'access_key': 'a' * 15}, False),
                 ({prefix + 'access_key': 'a' * 16 + '\r'}, False),
                 ({prefix + 'access_key': 'a' * 16 + '\n'}, False),
                 ({prefix + 'alias': 'invalid alias'}, False),
                 ({prefix + 'mc_bin': 'relative-mc'}, False),
                 ({prefix + 'python': 'relative-python'}, False),
                 ({prefix + 'state_dir': '/var/lib/../../root'}, False),
                 ({prefix + 'state_dir': '/tmp/shared'}, False)]
        plays = []
        for overrides, success in cases:
            plays.append({'hosts': 'localhost', 'gather_facts': False, 'vars': base | overrides,
                'tasks': [
                    {'ansible.builtin.set_fact': {'reader_passed': False}},
                    {'block': [validation, {'ansible.builtin.set_fact': {'reader_passed': True}}],
                     'rescue': [{'ansible.builtin.debug': {'msg': 'expected reader validation rejection'}}]},
                    {'ansible.builtin.assert': {'that': [f'reader_passed == {str(success).lower()}']}},
                ]})
        path = self.path / 'reader-validation.yml'
        path.write_text(yaml.safe_dump(plays))
        result = subprocess.run(['ansible-playbook', '-i', 'localhost,', '-c', 'local', str(path)],
                                cwd=ROOT, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_leading_hyphen_access_key_is_rejected_before_cli(self):
        with self.assertRaises(reader.Refused):
            reader.provision(dict(self.request, access_key='-' + 'a' * 20), self.mc)
        self.assertEqual(self.mc.calls, [])

    def test_fresh_creation_then_read_only_idempotency(self):
        self.assertTrue(reader.provision(self.request, self.mc)['changed'])
        self.assertEqual(self.mc.mutations(), ['policy create', 'user add', 'policy attach'])
        marker = self.path / 'identity.json'
        self.assertEqual(marker.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(self.request['secret_key'], marker.read_text())
        self.assertNotIn(self.request['access_key'], marker.read_text())
        self.mc.calls.clear()
        self.assertFalse(reader.provision(self.request, self.mc)['changed'])
        self.assertEqual(self.mc.mutations(), [])

    def test_existing_unowned_identity_is_never_adopted_or_upserted(self):
        self.mc.user = {'status': 'success', 'accessKey': self.request['access_key'],
                        'userStatus': 'enabled', 'policyName': reader.POLICY_NAME}
        with self.assertRaisesRegex(reader.Refused, 'not_owned'):
            reader.provision(self.request, self.mc)
        self.assertEqual(self.mc.mutations(), [])

    def test_changed_secret_or_lost_owned_user_requires_recovery(self):
        reader.provision(self.request, self.mc)
        self.mc.calls.clear()
        with self.assertRaisesRegex(reader.Refused, 'credentials_changed'):
            reader.provision(dict(self.request, secret_key='c' * 48), self.mc)
        self.assertEqual(self.mc.calls, [])
        self.mc.user = None
        with self.assertRaisesRegex(reader.Refused, 'owned_identity_missing'):
            reader.provision(self.request, self.mc)
        self.assertEqual(self.mc.mutations(), [])

    def test_broader_policy_rejected_before_any_mutation(self):
        self.mc.policy = copy.deepcopy(reader.POLICY)
        self.mc.policy['Statement'][1]['Action'].append('s3:PutObject')
        with self.assertRaisesRegex(reader.Refused, 'existing_policy_differs'):
            reader.provision(self.request, self.mc)
        self.assertEqual(self.mc.mutations(), [])

    def test_altered_list_prefix_condition_is_rejected(self):
        self.mc.policy = copy.deepcopy(reader.POLICY)
        self.mc.policy['Statement'][0]['Condition'] = {'StringLike': {'s3:prefix': ['Inbox/*']}}
        with self.assertRaises(reader.Refused):
            reader.provision(self.request, self.mc)
        self.assertEqual(self.mc.mutations(), [])

    def test_policy_order_and_scalar_normalization(self):
        self.mc.policy = copy.deepcopy(reader.POLICY)
        self.mc.policy['Statement'].reverse()
        for statement in self.mc.policy['Statement']:
            statement['Action'] = statement['Action'][0]
            statement['Resource'] = statement['Resource'][0]
            statement['Sid'] = 'HarmlessLabel'
        self.mc.policy['Statement'][1]['Condition']['StringEquals']['s3:prefix'] = 'Inbox/Voice Memos/'
        self.assertTrue(reader.provision(self.request, self.mc)['changed'])
        self.assertNotIn('policy create', self.mc.mutations())

    def test_groups_and_extra_attachments_rejected(self):
        reader.provision(self.request, self.mc)
        self.mc.calls.clear()
        self.mc.user['memberOf'] = ['administrators']
        with self.assertRaisesRegex(reader.Refused, 'existing_identity_differs'):
            reader.provision(self.request, self.mc)
        self.mc.user.pop('memberOf')
        self.mc.policies.append('readwrite')
        with self.assertRaisesRegex(reader.Refused, 'unexpected_policy_attachments'):
            reader.provision(self.request, self.mc)
        self.assertEqual(self.mc.mutations(), [])

    def test_failed_inspection_never_becomes_assumed_absence(self):
        self.mc.failed_command = 'user info'
        with self.assertRaises(reader.Refused):
            reader.provision(self.request, self.mc)
        self.assertEqual(self.mc.mutations(), [])

    def test_partial_creation_requires_explicit_recovery(self):
        self.mc.failed_command = 'policy attach'
        with self.assertRaises(reader.Refused):
            reader.provision(self.request, self.mc)
        self.assertFalse((self.path / 'identity.json').exists())
        self.mc.failed_command = None
        with self.assertRaisesRegex(reader.Refused, 'not_owned'):
            reader.provision(self.request, self.mc)

    def test_secret_control_characters_rejected_before_cli(self):
        with self.assertRaises(reader.Refused):
            reader.provision(dict(self.request, secret_key='a' * 40 + '\nnew-key'), self.mc)
        self.assertEqual(self.mc.calls, [])

    def test_symlink_marker_rejected(self):
        elsewhere = self.path / 'other'
        elsewhere.write_text('{}')
        (self.path / 'identity.json').symlink_to(elsewhere)
        with self.assertRaisesRegex(reader.Refused, 'unsafe_ownership_marker'):
            reader.provision(self.request, self.mc)
        self.assertEqual(self.mc.calls, [])

    @patch.object(reader.subprocess, 'run')
    def test_mc_missing_code_and_failed_transport_are_distinct(self, run):
        mc = reader.MC('/usr/local/bin/mc', 'local')
        missing = {'status': 'error', 'error': {'cause': {'error': {'Code': 'XMinioAdminNoSuchUser'}}}}
        run.return_value = subprocess.CompletedProcess([], 1, stdout=json.dumps(missing))
        self.assertIsNone(mc.call('user info', identity='synthetic', missing='XMinioAdminNoSuchUser'))
        missing['error']['cause']['error']['Code'] = 'AccessDenied'
        run.return_value.stdout = json.dumps(missing)
        with self.assertRaises(reader.Refused):
            mc.call('user info', identity='synthetic', missing='XMinioAdminNoSuchUser')

    @patch.object(reader.subprocess, 'run')
    def test_user_secret_is_stdin_only_and_prompt_output_is_not_parsed(self, run):
        mc = reader.MC('/usr/local/bin/mc', 'local')
        run.return_value = subprocess.CompletedProcess([], 0, stdout='Enter Access Key: user created')
        mc.call('user add', stdin=self.request['access_key'] + '\n' + self.request['secret_key'] + '\n')
        argv = run.call_args.args[0]
        self.assertNotIn(self.request['secret_key'], repr(argv))
        self.assertNotIn(self.request['access_key'], repr(argv))
        self.assertIn(self.request['secret_key'], run.call_args.kwargs['input'])


if __name__ == '__main__':
    unittest.main()
