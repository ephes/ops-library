"""Disabled pilot deployment input and rendered launchd contract checks."""
import copy
import hashlib
import os
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / 'roles/daybook_voice_memo_attention_deploy'
REMOVE = ROOT / 'roles/daybook_voice_memo_attention_remove'
PREFIX = 'daybook_voice_memo_attention_'


class AttentionRoleTests(unittest.TestCase):
    def variables(self):
        variables = yaml.safe_load((ROLE / 'defaults/main.yml').read_text())
        variables.update({
            PREFIX + 'service_user': 'example',
            PREFIX + 'wheel_src': '/private/build/daybook-0.0.0-py3-none-any.whl',
            PREFIX + 'config': {
                'version': 1, 'enabled': False, 'profile': 'synthetic',
                'state_path': '/Users/example/.local/state/daybook/voice-memo-attention/state.sqlite3',
                'source': {'kind': 'synthetic'},
            },
        })
        env = Environment()
        for _ in range(8):
            for name, value in variables.items():
                if isinstance(value, str):
                    variables[name] = env.from_string(value).render(**variables)
        return variables

    def test_real_ansible_rejects_activation_and_bad_scope_before_mutation(self):
        validation = yaml.safe_load((ROLE / 'tasks/main.yml').read_text())[:2]
        cases = [({}, True), ({PREFIX + 'enabled': True}, False),
                 ({PREFIX + 'enabled': 'false'}, False),
                 ({PREFIX + 'service_user': 'root'}, False),
                 ({PREFIX + 'service_user': 'example\n'}, False),
                 ({PREFIX + 'wheel_src': '/private/daybook-valid.whl\n'}, False),
                 ({PREFIX + 'runtime_dir': '/tmp/shared'}, False),
                 ({PREFIX + 'wheel_src': '/private/build/other-1.0-py3-none-any.whl'}, False)]
        bad_config = self.variables()[PREFIX + 'config'] | {'enabled': True}
        cases.append(({PREFIX + 'config': bad_config}, False))
        plays = []
        for index, (overrides, success) in enumerate(cases):
            variables = self.variables() | overrides
            tasks = copy.deepcopy(validation)
            # Suppress only private-config values in normal role output; synthetic
            # test data may be shown by Ansible on failure for diagnostics.
            for task in tasks:
                task.pop('no_log', None)
            plays.append({
                'name': f'validation case {index}', 'hosts': 'localhost',
                'gather_facts': False,
                'vars': variables | {'ansible_facts': {'os_family': 'Darwin'}},
                'tasks': [
                    {'ansible.builtin.set_fact': {'validation_passed': False}},
                    {'block': tasks + [{'ansible.builtin.set_fact': {'validation_passed': True}}],
                     'rescue': [{'ansible.builtin.debug': {'msg': 'expected validation rejection'}}]},
                    {'ansible.builtin.assert': {'that': [f'validation_passed == {str(success).lower()}']}},
                ],
            })
        with tempfile.TemporaryDirectory() as tmp:
            playbook = Path(tmp) / 'validation.yml'
            playbook.write_text(yaml.safe_dump(plays))
            env = os.environ | {'ANSIBLE_NOCOLOR': '1'}
            result = subprocess.run(
                ['ansible-playbook', '-i', 'localhost,', '-c', 'local', str(playbook)],
                cwd=ROOT, env=env, text=True, capture_output=True, timeout=90,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_ansible_remove_rejects_unconfirmed_root_and_wrong_scope(self):
        validation = yaml.safe_load((REMOVE / 'tasks/main.yml').read_text())[0]
        prefix = PREFIX + 'remove_'
        base = {'ansible_facts': {'os_family': 'Darwin'}, prefix + 'confirm': True,
                prefix + 'service_user': 'example', prefix + 'service_home': '/Users/example',
                prefix + 'launchd_label': 'de.wersdoerfer.daybook.voice-memo-attention'}
        plays = []
        cases = [({}, True), ({prefix + 'confirm': False}, False),
                 ({prefix + 'confirm': 'true'}, False), ({prefix + 'service_user': 'root'}, False),
                 ({prefix + 'service_home': '/Users/other'}, False),
                 ({prefix + 'launchd_label': 'de.wersdoerfer.daybook.voice-memo-inbox'}, False)]
        for overrides, success in cases:
            plays.append({'hosts': 'localhost', 'gather_facts': False, 'vars': base | overrides,
                'tasks': [
                    {'ansible.builtin.set_fact': {'remove_passed': False}},
                    {'block': [validation, {'ansible.builtin.set_fact': {'remove_passed': True}}],
                     'rescue': [{'ansible.builtin.debug': {'msg': 'expected removal rejection'}}]},
                    {'ansible.builtin.assert': {'that': [f'remove_passed == {str(success).lower()}']}},
                ]})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'remove.yml'
            path.write_text(yaml.safe_dump(plays))
            result = subprocess.run(['ansible-playbook', '-i', 'localhost,', '-c', 'local', str(path)],
                                    cwd=ROOT, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_ansible_destination_receipt_is_idempotent_without_copy_checksum(self):
        all_tasks = yaml.safe_load((ROLE / 'tasks/main.yml').read_text())
        names = ['Copy provided Daybook wheel', 'Read installed wheel destination checksum',
                 'Require a readable installed wheel checksum', 'Inspect successful wheel installation receipt',
                 'Read successful wheel installation receipt', 'Determine whether attention wheel needs installation',
                 'Record successful attention wheel installation']
        selected = {name: copy.deepcopy(next(t for t in all_tasks if t['name'] == name)) for name in names}
        for task in selected.values():
            module = task.get('ansible.builtin.copy')
            if module:
                # The integration sandbox owns these temp files; exercise the
                # role's real copy/stat/receipt templates without root ownership.
                module.pop('owner', None)
                module.pop('group', None)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source = directory / 'daybook-0.0.0-py3-none-any.whl'
            source.write_text('synthetic wheel bytes one')
            target = directory / 'installation'
            target.mkdir()
            plays = []
            for number, changed in enumerate((True, False, True)):
                expected_bytes = 'synthetic wheel bytes two' if number == 2 else 'synthetic wheel bytes one'
                digest = hashlib.sha1(expected_bytes.encode()).hexdigest()
                tasks = []
                if number == 2:
                    tasks.append({'ansible.builtin.copy': {'content': expected_bytes, 'dest': str(source)}})
                tasks += [selected[names[0]],
                    {'ansible.builtin.assert': {'that': [PREFIX + 'wheel.changed == ' + str(changed).lower()]}},
                    {'ansible.builtin.debug': {'msg': 'copy_checksum_present={{ ' + PREFIX + 'wheel.checksum is defined }}'}},
                    # Simulate a copy result without checksum on every converge.
                    # Both comparison and receipt must use the destination stat.
                    {'ansible.builtin.set_fact': {PREFIX + 'wheel': {'changed': changed}}},
                    selected[names[1]], selected[names[2]],
                    {'ansible.builtin.set_fact': {PREFIX + 'venv_created': {'changed': False}}},
                    selected[names[3]], selected[names[4]], selected[names[5]],
                    {'ansible.builtin.assert': {'that': [PREFIX + 'install_needed == ' + str(changed).lower()]}},
                    {'name': 'Simulate successful wheel install without executing uv or Python',
                     'ansible.builtin.set_fact': {'install_calls': '{{ (install_calls | default(0) | int) + 1 }}'},
                     'when': PREFIX + 'install_needed'},
                    selected[names[6]],
                    {'ansible.builtin.slurp': {'src': str(target / 'installed-wheel.sha1')}, 'register': 'actual_receipt'},
                    {'ansible.builtin.assert': {'that': [
                        "(actual_receipt.content | b64decode | trim) == '" + digest + "'",
                        'install_calls | int == ' + str(2 if number == 2 else 1)]}},
                ]
                plays.append({'name': f'wheel converge {number}', 'hosts': 'localhost', 'gather_facts': False,
                              'vars': {PREFIX + 'install_root': str(target), PREFIX + 'wheel_src': str(source)},
                              'tasks': tasks})
            path = directory / 'receipt.yml'
            path.write_text(yaml.safe_dump(plays))
            result = subprocess.run(['ansible-playbook', '-i', 'localhost,', '-c', 'local', str(path)],
                                    cwd=ROOT, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # The installed copy plugin supplies this field even on its unchanged
        # path; the stripped-result exercise above proves we no longer need it.
        self.assertEqual(result.stdout.count('copy_checksum_present='), 3)

    def test_import_verification_precedes_success_receipt(self):
        tasks = yaml.safe_load((ROLE / 'tasks/main.yml').read_text())
        verify = next(t for t in tasks if t['name'].startswith('Verify installed attention module'))
        self.assertEqual(verify['ansible.builtin.command']['argv'],
                         ['/usr/bin/sudo', '-n', '-H', '-u', '{{ daybook_voice_memo_attention_service_user }}', '--',
                          '{{ daybook_voice_memo_attention_venv }}/bin/python', '-I', '-c', 'import daybook.attention'])
        self.assertFalse(verify['changed_when'])
        self.assertTrue(verify['become'])
        self.assertEqual(verify['become_user'], 'root')
        self.assertEqual(verify['ansible.builtin.command']['chdir'], '{{ daybook_voice_memo_attention_service_home }}')
        self.assertEqual(verify['when'], 'not ansible_check_mode')
        names = [t['name'] for t in tasks]
        self.assertLess(names.index(verify['name']), names.index('Record successful attention wheel installation'))

    def test_plist_is_disabled_isolated_and_has_exact_cli(self):
        variables = self.variables()
        rendered = Environment().from_string(
            (ROLE / 'templates/attention.launchd.plist.j2').read_text()
        ).render(**variables)
        plist = plistlib.loads(rendered.encode())
        self.assertIs(plist['Disabled'], True)
        self.assertIs(plist['RunAtLoad'], True)
        self.assertEqual(plist['KeepAlive'], {'SuccessfulExit': False})
        self.assertEqual(plist['ThrottleInterval'], 900)
        self.assertEqual(plist['Umask'], 0o077)
        self.assertEqual(plist['ProgramArguments'], [
            variables[PREFIX + 'venv'] + '/bin/python', '-I', '-m', 'daybook.attention',
            '--config', variables[PREFIX + 'config_path'], 'serve',
        ])
        self.assertNotIn('StartInterval', plist)
        self.assertEqual(plist['WorkingDirectory'], variables[PREFIX + 'runtime_dir'])

    def test_deploy_never_starts_app_or_initializes_state(self):
        tasks = yaml.safe_load((ROLE / 'tasks/main.yml').read_text())
        command_arguments = [t['ansible.builtin.command']['argv'] for t in tasks
                             if 'ansible.builtin.command' in t]
        for argv in command_arguments:
            self.assertFalse(set(argv) & {'bootstrap', 'enable', 'kickstart', 'tick', 'initialize', 'baseline'})
        names = [t['name'] for t in tasks]
        self.assertLess(names.index('Verify attention label is unloaded'), names.index('Copy provided Daybook wheel'))
        private = next(t for t in tasks if t['name'] == 'Install disabled private attention configuration')
        self.assertTrue(private['no_log'])
        self.assertEqual(private['ansible.builtin.copy']['mode'], '0600')
        self.assertNotIn('state: absent', (ROLE / 'tasks/main.yml').read_text())

    def test_launchctl_probes_do_not_log_private_environment(self):
        for role in (ROLE, REMOVE):
            for task in yaml.safe_load((role / 'tasks/main.yml').read_text()):
                argv = task.get('ansible.builtin.command', {}).get('argv', [])
                if argv[:2] == ['/bin/launchctl', 'print']:
                    self.assertTrue(task.get('no_log'), task['name'])

    def test_removal_only_removes_attention_plist(self):
        tasks = yaml.safe_load((REMOVE / 'tasks/main.yml').read_text())
        removals = [t['ansible.builtin.file'] for t in tasks if 'ansible.builtin.file' in t]
        self.assertEqual(len(removals), 1)
        self.assertEqual(removals[0]['state'], 'absent')
        self.assertTrue(removals[0]['path'].endswith('.plist'))
        self.assertNotIn('voice-memo-inbox', (REMOVE / 'tasks/main.yml').read_text())
        self.assertEqual(tasks[-2]['name'], 'Verify attention label is unloaded before removal')


if __name__ == '__main__':
    unittest.main()
