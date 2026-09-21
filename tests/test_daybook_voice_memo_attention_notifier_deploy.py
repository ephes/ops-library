"""Protect forced-command scope and existing root administration keys."""
import base64
import copy
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / 'roles/daybook_voice_memo_attention_notifier_deploy'
PREFIX = 'daybook_voice_memo_attention_notifier_'
OPTIONS = 'restrict,command="/usr/bin/python3 -I /usr/local/libexec/daybook-attention-notify.py --config /etc/daybook-attention-notify.json"'
KEY = 'ssh-ed25519 ' + 'A' * 68


def benign_edits():
    exact = OPTIONS + ' ' + KEY + ' daybook-attention-notifier'
    return [
        ('# retired daybook-attention-notifier 2025-01\n' + exact, True),
        ('   # ' + KEY + ' old administrator\n' + exact, True),
        (exact + '   \t', True),
        ('  ' + OPTIONS + '\tssh-ed25519\t' + 'A' * 68 + ' changed trailing comment ', True),
        ('ssh-ed25519 ' + 'B' * 68 + ' daybook-attention-notifier-old\n' + exact, True),
        (OPTIONS.replace('restrict,', '') + ' ' + KEY + ' changed comment', False),
        (OPTIONS.replace('python3 -I', 'python3') + ' ' + KEY + ' daybook-attention-notifier', False),
        (KEY + ' admin-key with harmless trailing spaces   ', False),
    ]


class AttentionNotifierRoleTests(unittest.TestCase):
    def tasks(self):
        return yaml.safe_load((ROLE / 'tasks/main.yml').read_text())

    def test_real_ansible_rejects_admin_key_reuse(self):
        all_tasks = self.tasks()
        selected = [all_tasks[0], next(t for t in all_tasks if 'ansible.builtin.set_fact' in t),
                    next(t for t in all_tasks if t['name'] == 'Reject reuse of a differently authorized existing key')]
        plays = []
        for index, (old_keys, success) in enumerate([
            ('', True), ('ssh-ed25519 ' + 'B' * 68 + ' admin', True),
            (KEY + ' admin', False),
            (OPTIONS + ' ssh-ed25519 ' + 'B' * 68 + ' daybook-attention-notifier', False), (OPTIONS + ' ' + KEY + ' daybook-attention-notifier', True),
        ] + benign_edits()):
            tasks = copy.deepcopy(selected)
            for task in tasks:
                task.pop('no_log', None)
            plays.append({
                'name': f'key coexistence {index}', 'hosts': 'localhost', 'gather_facts': False,
                'vars': {
                    'ansible_facts': {'system': 'Linux'},
                    PREFIX + 'script_src': '/private/build/attention_notify.py',
                    PREFIX + 'public_key': KEY, PREFIX + 'native_host': 'example',
                    PREFIX + 'recipient': '123456789', PREFIX + 'container': 'openclaw-gateway',
                    PREFIX + 'existing_keys': {'content': base64.b64encode(old_keys.encode()).decode()},
                },
                'tasks': [
                    {'ansible.builtin.set_fact': {'key_passed': False}},
                    {'block': tasks + [{'ansible.builtin.set_fact': {'key_passed': True}}],
                     'rescue': [{'ansible.builtin.debug': {'msg': 'expected key rejection'}}]},
                    {'ansible.builtin.assert': {'that': [f'key_passed == {str(success).lower()}']}},
                ],
            })
        with tempfile.TemporaryDirectory() as tmp:
            playbook = Path(tmp) / 'keys.yml'
            playbook.write_text(yaml.safe_dump(plays))
            result = subprocess.run(
                ['ansible-playbook', '-i', 'localhost,', '-c', 'local', str(playbook)],
                cwd=ROOT, env=os.environ | {'ANSIBLE_NOCOLOR': '1'}, capture_output=True,
                text=True, timeout=90,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_remove_rejects_admin_and_different_notifier_keys(self):
        role = ROOT / 'roles/daybook_voice_memo_attention_notifier_remove'
        tasks = yaml.safe_load((role / 'tasks/main.yml').read_text())
        selected = [tasks[0], next(t for t in tasks if 'ansible.builtin.set_fact' in t),
                    next(t for t in tasks if t['name'].startswith('Require exact dedicated'))]
        prefix = PREFIX.replace('notifier_', 'notifier_remove_')
        plays = []
        for old_keys, success in [
            ('', True), (KEY + ' admin', False),
            (OPTIONS + ' ' + KEY + ' daybook-attention-notifier', True),
            (OPTIONS + ' ssh-ed25519 ' + 'B' * 68 + ' daybook-attention-notifier', False),
        ] + benign_edits():
            validation = copy.deepcopy(selected)
            for task in validation:
                task.pop('no_log', None)
            plays.append({
                'hosts': 'localhost', 'gather_facts': False,
                'vars': {'ansible_facts': {'system': 'Linux'}, prefix + 'confirm': True,
                         prefix + 'public_key': KEY, prefix + 'existing_keys': {
                             'content': base64.b64encode(old_keys.encode()).decode()}},
                'tasks': [
                    {'ansible.builtin.set_fact': {'remove_passed': False}},
                    {'block': validation + [{'ansible.builtin.set_fact': {'remove_passed': True}}],
                     'rescue': [{'ansible.builtin.debug': {'msg': 'expected key rejection'}}]},
                    {'ansible.builtin.assert': {'that': [f'remove_passed == {str(success).lower()}']}},
                ],
            })
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'remove.yml'
            path.write_text(yaml.safe_dump(plays))
            result = subprocess.run(
                ['ansible-playbook', '-i', 'localhost,', '-c', 'local', str(path)],
                cwd=ROOT, capture_output=True, text=True, timeout=90,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        revoke = next(t['ansible.posix.authorized_key'] for t in tasks if 'ansible.posix.authorized_key' in t)
        self.assertEqual(revoke['state'], 'absent')
        self.assertIs(revoke['exclusive'], False)
        removed = next(t for t in tasks if 'ansible.builtin.file' in t)
        self.assertEqual(removed['loop'], ['/etc/daybook-attention-notify.json',
                                          '/usr/local/libexec/daybook-attention-notify.py'])

    def test_remove_requires_confirmation_and_exact_platform_scope(self):
        role = ROOT / 'roles/daybook_voice_memo_attention_notifier_remove'
        validation = yaml.safe_load((role / 'tasks/main.yml').read_text())[0]
        validation.pop('no_log', None)
        prefix = PREFIX + 'remove_'
        base = {'ansible_facts': {'system': 'Linux'}, prefix + 'confirm': True,
                prefix + 'public_key': KEY}
        plays = []
        for overrides, success in [({}, True), ({prefix + 'confirm': False}, False),
                                   ({prefix + 'confirm': 'true'}, False),
                                   ({'ansible_facts': {'system': 'Darwin'}}, False),
                                   ({prefix + 'public_key': 'not-a-key'}, False),
                                   ({prefix + 'public_key': KEY + '\n'}, False)]:
            plays.append({'hosts': 'localhost', 'gather_facts': False, 'vars': base | overrides,
                'tasks': [
                    {'ansible.builtin.set_fact': {'remove_passed': False}},
                    {'block': [validation, {'ansible.builtin.set_fact': {'remove_passed': True}}],
                     'rescue': [{'ansible.builtin.debug': {'msg': 'expected removal rejection'}}]},
                    {'ansible.builtin.assert': {'that': [f'remove_passed == {str(success).lower()}']}},
                ]})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'confirm.yml'
            path.write_text(yaml.safe_dump(plays))
            result = subprocess.run(['ansible-playbook', '-i', 'localhost,', '-c', 'local', str(path)],
                                    cwd=ROOT, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_deploy_rejects_trailing_newlines_in_pinned_inputs(self):
        validation = copy.deepcopy(self.tasks()[0])
        validation.pop('no_log', None)
        base = {'ansible_facts': {'system': 'Linux'}, PREFIX + 'script_src': '/private/notify.py',
                PREFIX + 'public_key': KEY, PREFIX + 'native_host': 'example',
                PREFIX + 'recipient': '123456789', PREFIX + 'container': 'openclaw-gateway'}
        plays = []
        cases = [({}, True)] + [({PREFIX + field: base[PREFIX + field] + '\n'}, False)
                                for field in ('script_src', 'public_key', 'native_host', 'recipient')]
        for overrides, success in cases:
            plays.append({'hosts': 'localhost', 'gather_facts': False, 'vars': base | overrides,
                'tasks': [
                    {'ansible.builtin.set_fact': {'inputs_passed': False}},
                    {'block': [validation, {'ansible.builtin.set_fact': {'inputs_passed': True}}],
                     'rescue': [{'ansible.builtin.debug': {'msg': 'expected input rejection'}}]},
                    {'ansible.builtin.assert': {'that': [f'inputs_passed == {str(success).lower()}']}},
                ]})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'inputs.yml'
            path.write_text(yaml.safe_dump(plays))
            result = subprocess.run(['ansible-playbook', '-i', 'localhost,', '-c', 'local', str(path)],
                                    cwd=ROOT, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_authorized_key_stat_is_selected_by_exact_path(self):
        for role in (ROLE, ROOT / 'roles/daybook_voice_memo_attention_notifier_remove'):
            tasks = yaml.safe_load((role / 'tasks/main.yml').read_text())
            slurp = next(t for t in tasks if 'ansible.builtin.slurp' in t)
            self.assertIn("selectattr('item', 'equalto', '/root/.ssh/authorized_keys')", slurp['when'])
            self.assertNotIn('[-1]', slurp['when'])

    def test_single_forced_key_preserves_other_keys(self):
        tasks = self.tasks()
        facts = next(t['ansible.builtin.set_fact'] for t in tasks if 'ansible.builtin.set_fact' in t)
        self.assertEqual(facts[PREFIX + 'key_options'], OPTIONS)
        key = next(t for t in tasks if 'ansible.posix.authorized_key' in t)
        self.assertIs(key['ansible.posix.authorized_key']['exclusive'], False)
        self.assertEqual(key['ansible.posix.authorized_key']['user'], 'root')
        self.assertTrue(key['no_log'])
        self.assertNotIn('permitopen', OPTIONS)
        self.assertNotIn('environment=', OPTIONS)

    def test_root_configuration_is_private_and_no_send_occurs(self):
        tasks = self.tasks()
        config = next(t for t in tasks if t['name'] == 'Install pinned private notifier configuration')
        self.assertTrue(config['no_log'])
        self.assertEqual(config['ansible.builtin.copy']['owner'], 'root')
        self.assertEqual(config['ansible.builtin.copy']['mode'], '0600')
        self.assertFalse(any('ansible.builtin.command' in t or 'ansible.builtin.shell' in t for t in tasks))


if __name__ == '__main__':
    unittest.main()
