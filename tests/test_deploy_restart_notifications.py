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


UV_OUTPUTS = [
    ('Resolved 12 packages in 3ms\nAudited 12 packages in 1ms', False),
    ('Installed 1 package in 2ms', True),
    ('Uninstalled 1 package in 2ms', True),
    ('Updated 1 package', True),
]

# role -> (restart handlers, {task file: [task names that must notify]}, uv register names)
ROLES = {
    'echoport': (
        ['restart echoport'],
        {
            'source_rsync.yml': ['Sync Django source code to target', 'Sync additional Echoport source directories',
                                 'Copy pyproject.toml from source', 'Copy extra files from source'],
            'python.yml': ['Create virtual environment using uv', 'Create virtual environment using venv',
                           'Install dependencies using uv', 'Install dependencies using pip'],
        },
        ['uv_sync'],
    ),
    'takahe': (
        ['restart takahe-gunicorn', 'restart takahe-stator'],
        {
            'source_rsync.yml': ['source_rsync | Sync Takahe source code'],
            'source_git.yml': ['source_git | Clone or update Takahe repository'],
            'python.yml': ['python | Create Python virtual environment', 'python | Install Takahe requirements'],
        },
        [],
    ),
    'otbr': (
        ['restart otbr-agent', 'restart otbr-web'],
        {'build.yml': ['Build and install OTBR']},
        [],
    ),
    'graphyard': (
        ['restart graphyard web', 'restart graphyard agent'],
        {
            'source_rsync.yml': ['source_rsync | Sync Graphyard project to target (controller push)'],
            'source_git.yml': ['source_git | Clone or update Graphyard repository'],
            'python.yml': ['python | Create virtual environment', 'python | Sync runtime dependencies with uv'],
        },
        ['graphyard_uv_sync_result'],
    ),
    'mailgun_relay': (
        ['restart mailgun-relay'],
        {
            'source_rsync.yml': ['source_rsync | Sync mailgun-relay project to target (controller push)'],
            'source_git.yml': ['source_git | Clone or update mailgun-relay repository'],
            'python.yml': ['python | Create virtual environment', 'python | Sync runtime dependencies with uv'],
        },
        ['mailgun_relay_uv_sync_result'],
    ),
    'wagtail': (
        ['restart wagtail', 'restart wagtail db worker'],
        {
            'source_rsync.yml': ['source_rsync | Sync Wagtail source code to target'],
            'source_git.yml': ['source_git | Clone or update repository'],
            'python.yml': ['python | Create virtual environment using uv', 'python | Install dependencies with uv'],
        },
        ['wagtail_uv_sync'],
    ),
    'weeknotes_home': (
        ['restart weeknotes home'],
        {
            'source_rsync.yml': ['source_rsync | Sync daybook repository'],
            'source_git.yml': ['source_git | Checkout daybook repository'],
            'python.yml': ['python | Create virtual environment', 'python | Install weeknotes.home dependencies'],
        },
        ['weeknotes_home_uv_sync'],
    ),
    'archive': (
        ['restart archive', 'restart archive metadata worker'],
        {
            'source_rsync.yml': ['source_rsync | Sync archive repository contents'],
            'source_git.yml': ['source_git | Checkout archive repository'],
            'python.yml': ['python | Ensure archive virtual environment exists', 'python | Install archive dependencies'],
        },
        ['archive_uv_sync_result'],
    ),
    'chesslab': (
        ['restart chesslab'],
        {
            'source_rsync.yml': ['source_rsync | Sync chesslab repository contents'],
            'python.yml': ['python | Ensure chesslab virtual environment exists', 'python | Install chesslab dependencies'],
        },
        ['chesslab_uv_sync_result'],
    ),
    'heis': (
        ['restart heis'],
        {
            'source_rsync.yml': ['Sync Heis source code to target'],
            'python.yml': ['Create virtual environment using uv', 'Create virtual environment using venv',
                           'Install dependencies using uv', 'Install dependencies using pip'],
        },
        ['heis_uv_sync'],
    ),
    'marina': (
        ['restart marina'],
        {
            'source_rsync.yml': ['Sync Marina source code to target'],
            'python.yml': ['Create virtual environment using uv', 'Create virtual environment using venv',
                           'Install dependencies using uv', 'Install dependencies using pip'],
        },
        ['marina_uv_sync'],
    ),
    'open_webui_venv': (
        ['restart open webui'],
        {'python.yml': ['python | Create virtual environment using uv', 'python | Install Open WebUI via uv pip']},
        ['open_webui_uv_install'],
    ),
}


def as_list(value):
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)


class RoleRestartNotifications(unittest.TestCase):
    def test_code_and_dependency_tasks_notify_every_unit(self):
        for role, (expected, files, registers) in ROLES.items():
            role_dir = ROOT / f'roles/{role}_deploy'
            handlers = yaml.safe_load((role_dir / 'handlers/main.yml').read_text())
            known = {h['name'] for h in handlers} | {l for h in handlers for l in as_list(h.get('listen'))}
            self.assertTrue(set(expected) <= known, (role, expected, known))
            seen_registers = set()
            for file, names in files.items():
                tasks = {t['name']: t for t in yaml.safe_load((role_dir / f'tasks/{file}').read_text())}
                for name in names:
                    with self.subTest(role=role, task=name):
                        task = tasks[name]
                        self.assertTrue(set(expected) <= set(as_list(task.get('notify'))))
                        if 'ansible.posix.synchronize' in task:
                            self.assertIs(task['ansible.posix.synchronize'].get('owner'), False)
                            self.assertIs(task['ansible.posix.synchronize'].get('group'), False)
                            # Role-side writes (uv.lock, symlinks) bump directory mtimes.
                            self.assertIn('--omit-dir-times', str(task['ansible.posix.synchronize'].get('rsync_opts')) + str(task.get('vars')))
                        register = task.get('register')
                        if register in registers:
                            seen_registers.add(register)
                            changed_when = task['changed_when']
                            self.assertIsInstance(changed_when, str)
                            expression = Environment().compile_expression(changed_when)
                            for output, changed in UV_OUTPUTS:
                                for stream in ('stdout', 'stderr'):
                                    result = {'stdout': '', 'stderr': ''}
                                    result[stream] = output
                                    self.assertEqual(bool(expression(**{register: result})), changed, (output, stream))
            self.assertEqual(seen_registers, set(registers), role)

    def test_unchanged_syncs_do_not_churn_role_managed_state(self):
        def task(role, file, name):
            tasks = yaml.safe_load((ROOT / f'roles/{role}_deploy/tasks/{file}').read_text())
            return next(t for t in tasks if t['name'] == name)

        # Takahe's directories.yml sets 0750 on the site; synced modes must not flip it back.
        takahe = task('takahe', 'source_rsync.yml', 'source_rsync | Sync Takahe source code')
        self.assertIs(takahe['ansible.posix.synchronize']['perms'], False)

        # Echoport's delete: true sync must keep files the role creates in the site root.
        echoport = task('echoport', 'source_rsync.yml', 'Sync Django source code to target')
        env = Environment()
        for use_pyproject, extra in ((True, ['config.toml']), (False, [])):
            managed = env.from_string(echoport['vars']['echoport_rsync_role_managed']).render(
                echoport_use_source_pyproject=use_pyproject, echoport_rsync_extra_files=extra)
            for path in ['.env', 'venv', 'uv.lock', 'staging-db-refresh.sh'] + extra:
                self.assertIn(repr(path), managed)
            self.assertEqual(repr('pyproject.toml') in managed, use_pyproject)
        self.assertIn('--exclude=db.sqlite3-*', echoport['vars']['echoport_rsync_django_opts'])

        # Wagtail's venv symlink lives in the synced site root.
        wagtail = task('wagtail', 'source_rsync.yml', 'source_rsync | Build rsync exclude list')
        self.assertIn("['/venv']", wagtail['ansible.builtin.set_fact']['wagtail_rsync_excludes_all'])
