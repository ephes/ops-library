"""Ensure application changes reach every existing restart handler."""
from pathlib import Path
import unittest

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]


class RestartNotifications(unittest.TestCase):
    def test_source_and_dependency_notifications(self):
        for role, sources in (
            ('homelab', ['source.yml']),
            ('nyxmon', ['source_rsync.yml', 'source_git.yml']),
        ):
            handlers = yaml.safe_load((ROOT / f'roles/{role}_deploy/handlers/main.yml').read_text())
            expected = {f'restart {role}'}
            if role == 'nyxmon':
                expected.add('restart nyxmon-monitor')
            self.assertTrue(expected <= {h['name'] for h in handlers})
            for file in sources + ['python.yml']:
                tasks = yaml.safe_load((ROOT / f'roles/{role}_deploy/tasks/{file}').read_text())
                for task in tasks:
                    source = file in sources and any(k in task for k in ('ansible.posix.synchronize', 'copy', 'git'))
                    dependency = file == 'python.yml' and any(s in task['name'] for s in ('Install dependencies', 'Create virtual environment', 'Create pyproject.toml'))
                    if (source and 'Sync media' not in task['name']) or dependency:
                        with self.subTest(role=role, task=task['name']):
                            self.assertTrue(expected <= set(task.get('notify', [])))
                            if 'ansible.posix.synchronize' in task:
                                self.assertIs(task['ansible.posix.synchronize']['owner'], False)
                                self.assertIs(task['ansible.posix.synchronize']['group'], False)
                    if 'register' in task and task['register'] in ('uv_sync', 'uv_sync_result'):
                        expression = Environment().compile_expression(task['changed_when'])
                        for output, changed in [('Audited 12 packages', False), ('Installed 1 package', True), ('Uninstalled 1 package', True), ('Updated 1 package', True)]:
                            for stream in ('stdout', 'stderr'):
                                result = {'stdout': '', 'stderr': ''}
                                result[stream] = output
                                self.assertEqual(expression(**{task['register']: result}), changed)
