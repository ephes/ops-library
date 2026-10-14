"""Grafana datasource provisioning rewrite reports changed only on a real change.

Runs the task's embedded script against a temporary provisioning file and
evaluates the task's own ``changed_when`` expression on the real output. A
substring test (``'CHANGED' in stdout``) also matched ``UNCHANGED``, so every
deploy restarted the Grafana container.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "roles/graphyard_auth_bootstrap_deploy/tasks/main.yml"
TASK_NAME = "Update Grafana datasource provisioning URL when it does not match target"
REGISTER = "graphyard_auth_bootstrap_grafana_datasource_provisioning_url_update"
TARGET_URL = "http://graphyard-influxdb:8086"


def load_task():
    tasks = yaml.safe_load(TASKS.read_text(encoding="utf-8"))
    matches = [task for task in tasks if task.get("name") == TASK_NAME]
    assert len(matches) == 1, matches
    return matches[0]


def changed_when(task, stdout):
    expression = task["changed_when"]
    template = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string("{{ (" + expression + ") }}")
    result = {"stdout": stdout, "stdout_lines": stdout.splitlines()}
    rendered = template.render({REGISTER: result})
    assert rendered in {"True", "False"}, rendered
    return rendered == "True"


class GrafanaDatasourceProvisioningChangedWhenTest(unittest.TestCase):
    def setUp(self):
        self.task = load_task()
        self.assertEqual(self.task["register"], REGISTER)
        argv = self.task["ansible.builtin.command"]["argv"]
        self.assertEqual(argv[:2], ["python3", "-c"])
        self.script = argv[2]
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "graphyard.yaml"

    def run_script(self):
        env = dict(
            os.environ,
            GRAFANA_DATASOURCE_PROVISIONING_PATH=str(self.path),
            GRAFANA_DATASOURCE_TARGET_URL=TARGET_URL,
        )
        proc = subprocess.run(
            ["python3", "-c", self.script], env=env, capture_output=True, text=True, check=True
        )
        return proc.stdout

    def write(self, url):
        self.path.write_text(
            "apiVersion: 1\ndatasources:\n  - name: Graphyard\n    access: proxy\n" f"    url: {url}\n",
            encoding="utf-8",
        )

    def test_matching_url_reports_unchanged(self):
        self.write(TARGET_URL)
        stdout = self.run_script()
        self.assertEqual(stdout.strip(), "UNCHANGED")
        self.assertFalse(changed_when(self.task, stdout))

    def test_rewritten_url_reports_changed_then_unchanged(self):
        self.write("http://172.18.0.5:8086")
        stdout = self.run_script()
        self.assertEqual(stdout.strip(), "CHANGED")
        self.assertTrue(changed_when(self.task, stdout))
        self.assertIn(f"    url: {TARGET_URL}\n", self.path.read_text(encoding="utf-8"))

        stdout = self.run_script()
        self.assertEqual(stdout.strip(), "UNCHANGED")
        self.assertFalse(changed_when(self.task, stdout))

    def test_status_tokens(self):
        self.assertTrue(changed_when(self.task, "CHANGED\n"))
        self.assertFalse(changed_when(self.task, "UNCHANGED\n"))
        self.assertFalse(changed_when(self.task, ""))


if __name__ == "__main__":
    unittest.main()
