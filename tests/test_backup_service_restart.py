"""Static check that backup roles cannot leave a service stopped on failure.

A backup role that stops a service for a consistent copy must restart it even
when a copy or dump step fails. Every ``systemd``/``service`` task with
``state: stopped`` in ``roles/*_backup/tasks/*.yml`` must therefore sit inside a
``block`` whose ``always`` section starts the same unit (same ``name``, or a
loop over the stop task's registered results).

Task files pulled in with a static ``import_tasks``/``include_tasks`` are
expanded at their import site, so a stop/start pair kept in a shared file (as in
``unifi_backup/tasks/services.yml``) is checked where it is used. A ``when:``
item of the form ``var == 'value'`` whose ``var`` is set by the import's
``vars`` drops the task at that site when the values differ.
"""

import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLES = ROOT / "roles"

SERVICE_MODULES = {
    "systemd",
    "systemd_service",
    "service",
    "ansible.builtin.systemd",
    "ansible.builtin.systemd_service",
    "ansible.builtin.service",
}
IMPORT_MODULES = {
    "import_tasks",
    "include_tasks",
    "ansible.builtin.import_tasks",
    "ansible.builtin.include_tasks",
}
START_STATES = {"started", "restarted"}
EQUALS_LITERAL = re.compile(r"""^\s*(\w+)\s*==\s*['"]([^'"]*)['"]\s*$""")


def disabled_by(task, import_vars):
    """True when a ``var == 'value'`` condition contradicts the import vars."""
    conditions = task.get("when", [])
    if not isinstance(conditions, list):
        conditions = [conditions]
    for condition in conditions:
        match = EQUALS_LITERAL.match(str(condition))
        if match and match.group(1) in import_vars:
            if str(import_vars[match.group(1)]) != match.group(2):
                return True
    return False


def service_call(task):
    """Return ``(name, state)`` for a systemd/service task, else ``None``."""
    for module in SERVICE_MODULES:
        args = task.get(module)
        if isinstance(args, dict):
            return str(args.get("name", args.get("unit", ""))), args.get("state")
    return None


def import_target(task):
    for module in IMPORT_MODULES:
        target = task.get(module)
        if isinstance(target, dict):
            target = target.get("file")
        if isinstance(target, str) and "{{" not in target:
            return target
    return None


class TaskExpander:
    """Expand static task-file imports inside one role's ``tasks`` dir."""

    def __init__(self, files):
        self.files = files  # {"main.yml": [tasks]}

    def expand(self, tasks, seen=(), import_vars=None):
        import_vars = import_vars or {}
        result = []
        for task in tasks or []:
            if not isinstance(task, dict) or disabled_by(task, import_vars):
                continue
            target = import_target(task)
            if target in self.files and target not in seen:
                inner_vars = {**import_vars, **(task.get("vars") or {})}
                result.extend(
                    self.expand(self.files[target], seen + (target,), inner_vars)
                )
                continue
            task = dict(task)
            for key in ("block", "rescue", "always"):
                if key in task:
                    task[key] = self.expand(task[key], seen, import_vars)
            result.append(task)
        return result

    def imported(self):
        names = set()

        def walk(tasks):
            for task in tasks or []:
                if not isinstance(task, dict):
                    continue
                target = import_target(task)
                if target:
                    names.add(target)
                for key in ("block", "rescue", "always"):
                    walk(task.get(key))

        for tasks in self.files.values():
            walk(tasks)
        return names


def flatten(tasks):
    for task in tasks or []:
        yield task
        for key in ("block", "rescue", "always"):
            yield from flatten(task.get(key))


def restarts(stop_task, always_tasks):
    stop_name, _ = service_call(stop_task)
    register = stop_task.get("register")
    for task in flatten(always_tasks):
        call = service_call(task)
        if not call or call[1] not in START_STATES:
            continue
        if call[0] == stop_name:
            return True
        loop = str(task.get("loop", task.get("with_items", "")))
        if register and register in loop:
            return True
    return False


def unguarded_stops(tasks, enclosing_always=()):
    """Yield stop tasks with no enclosing ``always`` that restarts the unit."""
    for task in tasks:
        call = service_call(task)
        if call and call[1] == "stopped":
            if not any(restarts(task, always) for always in enclosing_always):
                yield task
        if "block" in task:
            yield from unguarded_stops(
                task["block"], enclosing_always + (task.get("always") or [],)
            )
        # A stop in rescue/always is not protected by its own block's always.
        for key in ("rescue", "always"):
            if key in task:
                yield from unguarded_stops(task[key], enclosing_always)


def role_violations(role_dir):
    tasks_dir = role_dir / "tasks"
    files = {
        path.name: yaml.safe_load(path.read_text()) or []
        for path in sorted(tasks_dir.glob("*.yml"))
    }
    expander = TaskExpander(files)
    imported = expander.imported()
    for name, tasks in files.items():
        if name in imported:
            continue
        for task in unguarded_stops(expander.expand(tasks, (name,))):
            yield f"{role_dir.name}/tasks/{name}: {task.get('name', '<unnamed>')}"


class CheckerSelfTest(unittest.TestCase):
    STOP = {
        "name": "Stop app",
        "ansible.builtin.systemd": {"name": "{{ app }}", "state": "stopped"},
        "register": "app_stop_result",
    }
    COPY = {"name": "Copy", "ansible.builtin.command": "rsync -a a b"}
    START = {
        "name": "Start app",
        "ansible.builtin.systemd": {"name": "{{ app }}", "state": "started"},
    }

    def check(self, tasks, extra=None):
        files = {"main.yml": tasks, **(extra or {})}
        expander = TaskExpander(files)
        return list(unguarded_stops(expander.expand(tasks, ("main.yml",))))

    def test_plain_stop_then_start_is_flagged(self):
        self.assertEqual(len(self.check([self.STOP, self.COPY, self.START])), 1)

    def test_block_with_always_restart_passes(self):
        tasks = [{"block": [self.STOP, self.COPY], "always": [self.START]}]
        self.assertEqual(self.check(tasks), [])

    def test_restart_of_other_unit_is_flagged(self):
        other = {
            "name": "Start other",
            "ansible.builtin.systemd": {"name": "other", "state": "started"},
        }
        tasks = [{"block": [self.STOP, self.COPY], "always": [other]}]
        self.assertEqual(len(self.check(tasks)), 1)

    def test_restart_in_rescue_only_is_flagged(self):
        tasks = [{"block": [self.STOP, self.COPY], "rescue": [self.START]}]
        self.assertEqual(len(self.check(tasks)), 1)

    def test_loop_over_registered_stop_results_passes(self):
        stop = {
            "name": "Stop units",
            "ansible.builtin.systemd": {"name": "{{ item }}", "state": "stopped"},
            "loop": "{{ units }}",
            "register": "units_stop_result",
        }
        start = {
            "name": "Start units",
            "ansible.builtin.systemd": {"name": "{{ item.item }}", "state": "started"},
            "loop": "{{ units_stop_result.results | default([]) }}",
        }
        tasks = [{"block": [stop, self.COPY], "always": [start]}]
        self.assertEqual(self.check(tasks), [])

    def test_imported_stop_and_start_are_checked_at_import_site(self):
        services = [
            {**self.STOP, "when": ["service_action == 'stop'"]},
            {**self.START, "when": "service_action == 'start'"},
        ]
        guarded = [
            {
                "block": [
                    {
                        "ansible.builtin.import_tasks": "services.yml",
                        "vars": {"service_action": "stop"},
                    }
                ],
                "always": [
                    {
                        "ansible.builtin.import_tasks": "services.yml",
                        "vars": {"service_action": "start"},
                    }
                ],
            }
        ]
        self.assertEqual(self.check(guarded, {"services.yml": services}), [])
        bare = [{"ansible.builtin.import_tasks": "services.yml"}, self.COPY]
        self.assertEqual(
            len(self.check(bare, {"services.yml": [self.STOP]})), 1
        )


class BackupServiceRestartTest(unittest.TestCase):
    def test_backup_roles_restart_stopped_services_in_always(self):
        violations = []
        for role_dir in sorted(ROLES.glob("*_backup")):
            if (role_dir / "tasks").is_dir():
                violations.extend(role_violations(role_dir))
        self.assertEqual(
            violations,
            [],
            "Backup tasks stop a service outside a block whose `always` "
            "restarts it; a failed copy would leave the service down:\n"
            + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
