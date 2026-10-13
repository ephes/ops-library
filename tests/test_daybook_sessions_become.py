import unittest
from pathlib import Path

import yaml


TASKS = Path(__file__).resolve().parents[1] / "roles/daybook_sessions_deploy/tasks"


def leaf_tasks(tasks, inherited=None):
    for task in tasks or []:
        flags = task.get("become_flags", inherited)
        nested = [task[key] for key in ("block", "rescue", "always") if key in task]
        if nested:
            for children in nested:
                yield from leaf_tasks(children, flags)
        else:
            yield task, flags


class DaybookSessionsBecomeTests(unittest.TestCase):
    def test_every_switch_to_the_service_user_uses_a_login_shell(self):
        # Studio is reached as root, whose working directory the service user
        # cannot read: without -i a module dies in getcwd, and the environment
        # probe then reads that crash as an interpreter that cannot start.
        switched = 0
        for path in sorted(TASKS.glob("*.yml")):
            for task, flags in leaf_tasks(yaml.safe_load(path.read_text(encoding="utf-8"))):
                if task.get("become_user") != "{{ daybook_sessions_service_user }}":
                    continue
                switched += 1
                self.assertEqual(flags, "-i", f"{path.name}: {task.get('name')}")
        self.assertGreaterEqual(switched, 13)


if __name__ == "__main__":
    unittest.main()
