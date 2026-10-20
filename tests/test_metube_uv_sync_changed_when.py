"""MeTube's ``uv sync`` task reports changed only when packages change.

The old ``changed_when`` ended in ``or metube_uv_sync.rc == 0``, so every
successful sync reported changed and notified a MeTube restart. uv writes its
summary to stderr; a no-op sync prints only ``Checked``/``Audited N packages``.
The samples below are real ``uv sync --frozen --no-dev`` output.
"""

import unittest
from pathlib import Path

import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "roles/metube_deploy/tasks/python.yml"
TASK_NAME = "Install MeTube Python dependencies via uv"
REGISTER = "metube_uv_sync"

FIRST_SYNC = (
    "Using CPython 3.14.0\n"
    "Creating virtual environment at: /opt/metube/venv\n"
    "Installed 2 packages in 2ms\n"
    " + six==1.17.0\n"
    " + yt-dlp==2026.10.1\n"
)
LOCK_UPGRADE = (
    "Prepared 1 package in 120ms\n"
    "Uninstalled 1 package in 1ms\n"
    "Installed 1 package in 3ms\n"
    " - yt-dlp==2026.10.1\n"
    " + yt-dlp==2026.10.14\n"
)
DEPENDENCY_REMOVED = "Uninstalled 1 package in 1ms\n - six==1.17.0\n"
NO_OP_CHECKED = "Checked 2 packages in 0.28ms\n"
NO_OP_AUDITED = "Audited 2 packages in 0.31ms\n"


def load_task():
    tasks = yaml.safe_load(TASKS.read_text(encoding="utf-8"))
    matches = [task for task in tasks if task.get("name") == TASK_NAME]
    assert len(matches) == 1, matches
    return matches[0]


def changed_when(task, stdout="", stderr="", rc=0):
    expression = task["changed_when"]
    template = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string("{{ (" + expression + ") }}")
    rendered = template.render({REGISTER: {"stdout": stdout, "stderr": stderr, "rc": rc}})
    assert rendered in {"True", "False"}, rendered
    return rendered == "True"


class MetubeUvSyncChangedWhenTest(unittest.TestCase):
    def setUp(self):
        self.task = load_task()
        self.assertEqual(self.task["register"], REGISTER)

    def test_does_not_depend_on_return_code(self):
        self.assertNotIn("rc", self.task["changed_when"])

    def test_no_op_sync_is_unchanged(self):
        self.assertFalse(changed_when(self.task, stderr=NO_OP_CHECKED))
        self.assertFalse(changed_when(self.task, stderr=NO_OP_AUDITED))
        self.assertFalse(changed_when(self.task))

    def test_installs_and_removals_are_changed(self):
        for stderr in (FIRST_SYNC, LOCK_UPGRADE, DEPENDENCY_REMOVED):
            with self.subTest(stderr=stderr.splitlines()[-1]):
                self.assertTrue(changed_when(self.task, stderr=stderr))

    def test_summary_on_stdout_is_also_seen(self):
        self.assertTrue(changed_when(self.task, stdout=FIRST_SYNC))
        self.assertFalse(changed_when(self.task, stdout=NO_OP_CHECKED))


if __name__ == "__main__":
    unittest.main()
