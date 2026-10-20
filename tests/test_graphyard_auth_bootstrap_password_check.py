"""The Grafana admin password check treats MISMATCH as a mismatch.

Runs the embedded check script of both password tasks against a temporary
Grafana-style SQLite database and evaluates the tasks' own ``when``,
``until`` and ``failed_when`` expressions on the real output. A substring test
(``'MATCH' in stdout``) also matched ``MISMATCH``, so the final verification
passed with a wrong admin password.
"""

import hashlib
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "roles/graphyard_auth_bootstrap_deploy/tasks/main.yml"
CHECK_TASK = "Check whether Grafana admin password hash already matches desired secret"
RESET_TASK = "Reset Grafana admin password when mismatch is detected"
VERIFY_TASK = "Verify Grafana admin password hash matches desired secret"
CHECK_REGISTER = "graphyard_auth_bootstrap_grafana_password_check"
VERIFY_REGISTER = "graphyard_auth_bootstrap_grafana_verify"
USER = "admin"
SALT = "testsalt01"


def load_tasks():
    return yaml.safe_load(TASKS.read_text(encoding="utf-8"))


def task_named(tasks, name):
    matches = [task for task in tasks if task.get("name") == name]
    assert len(matches) == 1, matches
    return matches[0]


def evaluate(expression, register, stdout, rc=0):
    template = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(
        "{{ (" + expression.strip() + ") }}"
    )
    result = {"stdout": stdout, "stdout_lines": stdout.splitlines(), "rc": rc}
    rendered = template.render({register: result})
    assert rendered in {"True", "False"}, rendered
    return rendered == "True"


def grafana_hash(password):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), SALT.encode(), 10000, dklen=50).hex()


class GrafanaPasswordCheckTest(unittest.TestCase):
    def setUp(self):
        tasks = load_tasks()
        self.check = task_named(tasks, CHECK_TASK)
        self.reset = task_named(tasks, RESET_TASK)
        self.verify = task_named(tasks, VERIFY_TASK)
        self.assertEqual(self.check["register"], CHECK_REGISTER)
        self.assertEqual(self.verify["register"], VERIFY_REGISTER)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db_path = Path(tmp.name) / "grafana.db"
        conn = sqlite3.connect(self.db_path)
        conn.execute("create table user (login text, password text, salt text)")
        conn.execute("insert into user values (?, ?, ?)", (USER, grafana_hash("stored-secret"), SALT))
        conn.commit()
        conn.close()

    def run_script(self, task, password):
        argv = task["ansible.builtin.command"]["argv"]
        self.assertEqual(argv[:2], ["python3", "-c"])
        env = dict(
            os.environ,
            GRAFANA_DB_PATH=str(self.db_path),
            GRAFANA_ADMIN_USER=USER,
            GRAFANA_ADMIN_PASSWORD=password,
        )
        proc = subprocess.run(["python3", "-c", argv[2]], env=env, capture_output=True, text=True)
        return proc.stdout, proc.returncode

    def verify_passes(self, stdout, rc):
        until = evaluate(self.verify["until"], VERIFY_REGISTER, stdout, rc)
        failed = evaluate(self.verify["failed_when"], VERIFY_REGISTER, stdout, rc)
        return until and not failed

    def test_wrong_password_is_a_mismatch(self):
        for task in (self.check, self.verify):
            stdout, rc = self.run_script(task, "wrong-secret")
            self.assertEqual((stdout.strip(), rc), ("MISMATCH", 0))
        self.assertTrue(evaluate(self.reset["when"], CHECK_REGISTER, stdout, rc))
        self.assertFalse(self.verify_passes(stdout, rc))

    def test_desired_password_is_a_match(self):
        for task in (self.check, self.verify):
            stdout, rc = self.run_script(task, "stored-secret")
            self.assertEqual((stdout.strip(), rc), ("MATCH", 0))
        self.assertFalse(evaluate(self.reset["when"], CHECK_REGISTER, stdout, rc))
        self.assertTrue(self.verify_passes(stdout, rc))

    def test_status_tokens(self):
        self.assertTrue(self.verify_passes("MATCH\n", 0))
        self.assertFalse(self.verify_passes("MISMATCH\n", 0))
        self.assertFalse(self.verify_passes("MISSING_USER\n", 2))
        self.assertFalse(self.verify_passes("", 0))
        self.assertTrue(evaluate(self.reset["when"], CHECK_REGISTER, "MISMATCH\n"))
        self.assertFalse(evaluate(self.reset["when"], CHECK_REGISTER, "MATCH\n"))


if __name__ == "__main__":
    unittest.main()
