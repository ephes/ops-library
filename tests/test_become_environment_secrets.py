"""No secrets in task environments or command lines of tasks that become another user.

With ``become_user`` set to an unprivileged account, Ansible runs the module through
``sudo -u <user> /bin/sh -c '... VAR=value ... python ...'``: every task environment
value is part of the command handed to sudo, and sudo logs that command to the
journal and ``/var/log/auth.log``. ``no_log`` does not change this. Values
interpolated into a command line are visible in the process list while the command
runs. Roles must pass secrets through a 0600 file owned by the service user (for
example a sourced shell companion of the service environment), on stdin, or as a
module parameter instead.
"""

from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]

# Environment variable names that hold secrets.
SECRET_ENV_NAME = re.compile(
    r"(SECRET|SECRET_KEY|PASSWORD|PASSWD|TOKEN|API_KEY|SIGNING_KEYS?|PRIVATE_KEY"
    r"|DATABASE_URL|DSN|CREDENTIALS?)$"
)
# Ansible variable names (last identifier of a dotted path) that hold secrets.
SECRET_VARIABLE = re.compile(
    r"(secret|secret_key|password|passwd|token|api_key|signing_keys?|private_key"
    r"|database_url|dsn|credentials?)$"
)
JINJA = re.compile(r"\{\{(.*?)\}\}", re.S)
STRING_LITERAL = re.compile(r"'[^']*'|\"[^\"]*\"")
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
COMMAND_MODULES = (
    "ansible.builtin.command",
    "command",
    "ansible.builtin.shell",
    "shell",
    "ansible.builtin.raw",
    "raw",
)

# (role-relative task file, task name) -> why the finding is not fixed here.
ALLOWED = {
    (
        "roles/heis_deploy/tasks/django.yml",
        "Ensure admin user exists",
    ): "heis is maintained by its owner outside this collection's change scope; "
    "ADMIN_PASSWORD still travels in the task environment (tracked as an open item).",
    (
        "roles/metube_deploy/tasks/ui.yml",
        "Install frontend dependencies ({{ metube_ui_package_manager }})",
    ): "expression combines the fixed metube_ui_build_env (HOME, CI, corepack and "
    "analytics switches) with NODE_ENV; no secrets.",
    (
        "roles/metube_deploy/tasks/ui.yml",
        "Build frontend assets ({{ metube_ui_package_manager }})",
    ): "same fixed metube_ui_build_env plus NODE_ENV; no secrets.",
    (
        "roles/wagtail_deploy/tasks/django.yml",
        "django | Build frontend assets",
    ): "operator-supplied wagtail_asset_build_env for asset builds; the README forbids "
    "secrets there because sudo logs the values.",
}


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_multi_constructor("!", lambda loader, suffix, node: None)


def secret_references(text: str) -> list[str]:
    """Secret-looking variables referenced inside Jinja expressions of ``text``."""
    found = []
    for expression in JINJA.findall(str(text)):
        expression = STRING_LITERAL.sub("", expression)
        for identifier in IDENTIFIER.findall(expression):
            if SECRET_VARIABLE.search(identifier):
                found.append(identifier)
    return found


def becomes_unprivileged(task: dict, inherited: str | None) -> tuple[bool, str | None]:
    user = task.get("become_user", inherited)
    if user is None or str(user).strip() == "root":
        return False, user
    if task.get("become") in (False, "false", "no", "False"):
        return False, user
    return True, user


def findings_for(tasks, inherited: str | None = None) -> list[tuple[str, str]]:
    """(task name, problem) for every offending task in a task list."""
    problems: list[tuple[str, str]] = []
    if not isinstance(tasks, list):
        return problems
    for task in tasks:
        if not isinstance(task, dict):
            continue
        unprivileged, user = becomes_unprivileged(task, inherited)
        for section in ("block", "rescue", "always"):
            problems += findings_for(task.get(section), task.get("become_user", inherited))
        if not unprivileged:
            continue
        name = str(task.get("name", "<unnamed>"))
        environment = task.get("environment")
        if isinstance(environment, str):
            problems.append((name, "environment is an expression; use a literal mapping"))
        elif isinstance(environment, dict):
            for key, value in environment.items():
                if SECRET_ENV_NAME.search(str(key)) or secret_references(value):
                    problems.append((name, f"secret in task environment: {key}"))
        for module in COMMAND_MODULES:
            if module not in task:
                continue
            body = task[module]
            parts: list[str] = []
            if isinstance(body, str):
                parts = [body]
            elif isinstance(body, dict):
                parts = [str(item) for item in body.get("argv", [])]
                for key in ("cmd", "_raw_params"):
                    if key in body:
                        parts.append(str(body[key]))
            for part in parts:
                for identifier in secret_references(part):
                    problems.append((name, f"secret on the command line: {identifier}"))
    return problems


def task_files():
    for pattern in ("roles/*/tasks/**/*.yml", "roles/*/handlers/**/*.yml"):
        for path in sorted(ROOT.glob(pattern)):
            if "molecule" not in path.parts:
                yield path


class BecomeEnvironmentSecretsGuard(unittest.TestCase):
    def test_no_role_task_sends_secrets_through_sudo_or_argv(self):
        offending = []
        seen_allowed = set()
        for path in task_files():
            relative = str(path.relative_to(ROOT))
            tasks = yaml.load(path.read_text(), Loader=_Loader)
            for name, problem in findings_for(tasks):
                if (relative, name) in ALLOWED:
                    seen_allowed.add((relative, name))
                    continue
                offending.append(f"{relative}: {name}: {problem}")
        self.assertEqual(offending, [], "\n".join(offending))
        self.assertEqual(
            set(ALLOWED) - seen_allowed,
            set(),
            "stale allowlist entries: remove them",
        )

    def test_guard_catches_each_leak_shape(self):
        leaking = yaml.safe_load(
            """
            - name: env key
              ansible.builtin.command: {argv: [manage.py]}
              become_user: app
              environment: {ADMIN_PASSWORD: "{{ x }}"}
            - name: env value
              ansible.builtin.command: {argv: [manage.py]}
              become: true
              become_user: "{{ app_user }}"
              environment: {DJANGO_SETTINGS: "{{ app_django_secret_key }}"}
            - name: env expression
              ansible.builtin.command: {argv: [manage.py]}
              become_user: postgres
              environment: "{{ admin_env }}"
            - name: argv
              ansible.builtin.command:
                argv: [htpasswd, -b, file, user, "{{ item.password }}"]
              become_user: app
            - name: shell text
              ansible.builtin.shell: "mc alias set x {{ minio_root_password }}"
              become_user: app
            - name: inherited from block
              become_user: app
              block:
                - name: inner
                  ansible.builtin.command: {argv: [x]}
                  environment: {HA_TOKEN: "{{ t }}"}
            """
        )
        names = {name for name, _ in findings_for(leaking)}
        self.assertEqual(
            names, {"env key", "env value", "env expression", "argv", "shell text", "inner"}
        )

    def test_guard_accepts_safe_shapes(self):
        safe = yaml.safe_load(
            """
            - name: root keeps the environment out of sudo
              ansible.builtin.command: {argv: [x]}
              become: true
              environment: {PGPASSWORD: "{{ db_password }}"}
            - name: become disabled
              ansible.builtin.command: {argv: [x]}
              become: false
              become_user: app
              environment: {PGPASSWORD: "{{ db_password }}"}
            - name: stdin and non-secret names
              ansible.builtin.shell:
                cmd: |
                  . {{ env_path | quote }}.shell
                  IFS= read -r ADMIN_PASSWORD
                stdin: "{{ admin_password }}"
              become_user: app
              environment:
                SERVICE_TOKEN_STATUS_TARGETS: "{{ targets | to_json }}"
                TOKEN_USER: "{{ backup_token_user }}"
                SCRIPT: "{{ lookup('ansible.builtin.file', 'mint_token.py') }}"
            """
        )
        self.assertEqual(findings_for(safe), [])


def ansible_like_environment() -> Environment:
    """Jinja settings Ansible's template module uses, with the filters these files need."""
    env = Environment(trim_blocks=True, keep_trailing_newline=True)
    env.filters["to_json"] = json.dumps
    return env


def source(shell_text: str, names: list[str]) -> dict[str, str]:
    result = subprocess.run(
        [
            "/bin/sh",
            "-c",
            'set -a; . /dev/stdin; set +a; for v in "$@"; do printf "%s\\0" "$(printenv "$v")"; done',
            "sh",
            *names,
        ],
        input=shell_text,
        capture_output=True,
        text=True,
        check=True,
    )
    return dict(zip(names, result.stdout.split("\0")))


AWKWARD = "a$b`c\\d\"e'f g#h&(i)$(id)"


class ShellCompanionTemplates(unittest.TestCase):
    """The service file keeps its format; the companion sources back to exact values."""

    def check(self, role: str, template: str, values: dict, expected_service: dict):
        text = (ROOT / "roles" / role / "templates" / template).read_text()
        env = ansible_like_environment()
        service = env.from_string(text).render(**values)
        for key, line in expected_service.items():
            self.assertIn(f"{key}={line}\n", service)
        shell = env.from_string(text).render(task_shell_environment=True, **values)
        names = [line.split("=", 1)[0] for line in shell.splitlines() if "=" in line and not line.startswith("#")]
        return source(shell, names)

    def test_chesslab(self):
        values = {
            "chesslab_django_settings_module": "chesslab.djangoapp.settings",
            "chesslab_django_secret_key": AWKWARD,
            "chesslab_django_debug": False,
            "chesslab_db_path": "/home/chesslab/data/chess.db",
            "chesslab_django_allowed_hosts": ["chess.example", "127.0.0.1"],
            "chesslab_django_csrf_trusted_origins": ["https://chess.example"],
            "chesslab_secure_cookies": True,
            "chesslab_limit": "20",
        }
        escaped = AWKWARD.replace("\\", "\\\\").replace('"', '\\"')
        sourced = self.check(
            "chesslab_deploy",
            "chesslab.env.j2",
            values,
            {"CHESSLAB_SECRET_KEY": f'"{escaped}"', "CHESSLAB_DEBUG": '"false"'},
        )
        self.assertEqual(sourced["CHESSLAB_SECRET_KEY"], AWKWARD)
        self.assertEqual(sourced["CHESSLAB_ALLOWED_HOSTS"], "chess.example,127.0.0.1")
        self.assertEqual(sourced["CHESSLAB_TRAINER_LIMIT"], "20")

    def test_weeknotes_home(self):
        values = {
            "weeknotes_home_django_settings_module": "weeknotes_home.settings",
            "weeknotes_home_django_secret_key": AWKWARD,
            "weeknotes_home_django_debug": False,
            "weeknotes_home_django_allowed_hosts": ["weeknotes.example"],
            "weeknotes_home_django_csrf_trusted_origins": ["https://weeknotes.example"],
            "weeknotes_home_static_root": "/srv/static",
            "weeknotes_home_django_db_conn_max_age": 60,
            "weeknotes_home_cast_base_url": "https://cast.example",
            "weeknotes_home_api_token": "tok$en",
            "weeknotes_home_database_url": "postgresql://u:p$w@localhost/db",
        }
        escaped = AWKWARD.replace("\\", "\\\\").replace('"', '\\"')
        sourced = self.check(
            "weeknotes_home_deploy",
            "weeknotes-home.env.j2",
            values,
            {"DJANGO_SECRET_KEY": f'"{escaped}"', "DATABASE_URL": '"postgresql://u:p$w@localhost/db"'},
        )
        self.assertEqual(sourced["DJANGO_SECRET_KEY"], AWKWARD)
        self.assertEqual(sourced["DATABASE_URL"], "postgresql://u:p$w@localhost/db")
        self.assertEqual(sourced["WEEKNOTES_HOME_API_TOKEN"], "tok$en")
        self.assertEqual(sourced["DJANGO_DB_CONN_MAX_AGE"], "60")

    def test_daybook_operations_api(self):
        keys = {"v1": "k" * 40}
        values = {
            "daybook_operations_api_secret_key": AWKWARD,
            "daybook_operations_api_database_url": "postgresql://u:p$w@127.0.0.1:5432/db",
            "daybook_operations_api_signing_keys": keys,
            "daybook_operations_api_signing_key_id": "v1",
            "daybook_operations_api_domain": "ops.example",
            "daybook_operations_api_record_limit": 300000,
            "daybook_operations_api_storage_path": "/var/lib/ops",
            "daybook_operations_api_storage_sample_interval": 300,
            "daybook_operations_api_storage_sample_max_age": 900,
            "daybook_operations_api_nominal_records_per_day": 2600,
            "daybook_operations_api_capacity_warn_utilization": 0.7,
            "daybook_operations_api_capacity_critical_utilization": 0.8,
            "daybook_operations_api_capacity_warn_days": 30,
            "daybook_operations_api_capacity_critical_days": 14,
        }
        sourced = self.check(
            "daybook_operations_api_deploy",
            "environment.j2",
            values,
            {
                "OPERATIONS_SECRET_KEY": AWKWARD,
                "OPERATIONS_SIGNING_KEYS": "'" + json.dumps(keys) + "'",
                "OPERATIONS_SIGNING_KEY_ID": "v1",
                "OPERATIONS_ALLOWED_HOSTS": "localhost,127.0.0.1,ops.example",
            },
        )
        self.assertEqual(sourced["OPERATIONS_SECRET_KEY"], AWKWARD)
        self.assertEqual(json.loads(sourced["OPERATIONS_SIGNING_KEYS"]), keys)
        self.assertEqual(sourced["OPERATIONS_SIGNING_KEY_ID"], "v1")
        self.assertEqual(sourced["OPERATIONS_CAPACITY_CRITICAL_DAYS"], "14")


STDIN_TASKS = {
    "roles/chesslab_deploy/tasks/django.yml": ("django | Ensure Django app users exist", "CHESSLAB_ADMIN_PASSWORD"),
    "roles/echoport_deploy/tasks/django.yml": ("Ensure admin user exists", "ADMIN_PASSWORD"),
    "roles/marina_deploy/tasks/django.yml": ("Ensure admin user exists", "ADMIN_PASSWORD"),
    "roles/fastdeploy_backup/tasks/main.yml": ("Dump PostgreSQL database", "PGPASSWORD"),
}


class LosslessStdinPasswords(unittest.TestCase):
    """Passwords on stdin arrive verbatim: no added newline, never an empty stdin."""

    def test_tasks_use_the_sentinel_protocol_and_it_round_trips(self):
        for file, (name, var) in STDIN_TASKS.items():
            with self.subTest(file=file):
                tasks = yaml.load((ROOT / file).read_text(), Loader=_Loader)
                task = next(t for t in tasks if t.get("name") == name)
                module = task.get("ansible.builtin.shell") or task.get("shell")
                self.assertIs(module["stdin_add_newline"], False)
                self.assertTrue(module["stdin"].startswith("x{{ "))
                self.assertTrue(task["no_log"] is True)
                lines = [line.strip() for line in module["cmd"].splitlines()]
                start = lines.index(f"{var}=$(cat; printf x)")
                snippet = "\n".join(lines[start:start + 3]) + f'\nprintf "%s" "${var}"'
                for value in ["", "plain", "trailing\n\n", "x-lead\nmid$`\\"]:
                    out = subprocess.run(["/bin/sh", "-c", snippet], input="x" + value,
                                         capture_output=True, text=True, check=True).stdout
                    self.assertEqual(out, value)


if __name__ == "__main__":
    unittest.main()
