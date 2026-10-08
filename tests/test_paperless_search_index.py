"""Regression coverage for empty indexes with already-current schema markers."""
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined

ROLE = Path(__file__).resolve().parents[1] / "roles" / "paperless_deploy"


class PaperlessSearchIndexTests(unittest.TestCase):
    def setUp(self):
        tasks = yaml.safe_load((ROLE / "tasks/search_index.yml").read_text())
        self.maintenance = tasks[0]
        self.pause = self.maintenance["block"][2]
        self.reindex = self.pause["block"][1]

    def test_rebuild_runs_after_configuration_before_service_health(self):
        tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
        imports = [task.get("ansible.builtin.import_tasks") for task in tasks]
        for prerequisite in ("configuration.yml", "systemd.yml"):
            self.assertLess(
                imports.index(prerequisite), imports.index("search_index.yml")
            )
        self.assertLess(imports.index("search_index.yml"), imports.index("service.yml"))
        self.assertEqual(self.maintenance["when"], "not ansible_check_mode")
        self.assertNotIn("when", self.reindex)
        self.assertNotIn("creates", self.reindex["args"])

    def test_all_configured_units_are_paused_and_running_units_resume_on_failure(self):
        env = Environment(undefined=StrictUndefined)
        env.filters["regex_replace"] = lambda value, pattern, replacement: re.sub(
            pattern, replacement, value
        )
        expression = self.maintenance["block"][1]["ansible.builtin.set_fact"][
            "paperless_deploy_reindex_running_units"
        ]
        result = env.from_string(expression).render(
            ansible_facts={
                "services": {
                    "paperless.service": {
                        "name": "paperless.service",
                        "state": "running",
                    },
                    "paperless-worker.service": {
                        "name": "paperless-worker.service",
                        "state": "stopped",
                    },
                    "postgresql.service": {
                        "name": "postgresql.service",
                        "state": "running",
                    },
                }
            },
            paperless_service_units=[
                "paperless",
                "paperless-worker",
                "paperless-consumer",
            ],
        )
        self.assertEqual(yaml.safe_load(result), ["paperless.service"])
        stop = self.pause["block"][0]
        resume = self.pause["always"][0]
        self.assertEqual(stop["loop"], "{{ paperless_service_units }}")
        self.assertEqual(resume["loop"], "{{ paperless_deploy_reindex_running_units }}")
        for task in (stop, resume):
            self.assertEqual(task["ansible.builtin.systemd"]["name"], "{{ item }}")
        self.assertEqual(stop["ansible.builtin.systemd"]["state"], "stopped")
        self.assertEqual(resume["ansible.builtin.systemd"]["state"], "started")

    def test_reindex_uses_environment_and_never_skips_current_schema(self):
        with tempfile.TemporaryDirectory(prefix="paperless search ") as directory:
            root = Path(directory)
            env_file = root / "app.env"
            env_file.write_text("PAPERLESS_TEST_ENV=loaded\n")
            (root / "manage.py").write_text(
                "import os, sys\n"
                "assert os.environ['PAPERLESS_TEST_ENV'] == 'loaded'\n"
                "assert sys.argv[1:] == ['document_index', 'reindex']\n"
                "print('indexed existing documents despite current schema')\n"
            )
            env = Environment(undefined=StrictUndefined)
            env.filters["quote"] = shlex.quote
            script = env.from_string(self.reindex["ansible.builtin.shell"]).render(
                paperless_env_file=str(env_file),
                paperless_python_bin=sys.executable,
            )
            run = subprocess.run(
                ["/bin/bash", "-c", script], cwd=root, capture_output=True, text=True
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("indexed existing documents", run.stdout)
            env_file.unlink()
            failure = subprocess.run(
                ["/bin/bash", "-c", script], cwd=root, capture_output=True, text=True
            )
            self.assertNotEqual(failure.returncode, 0)
            self.assertNotIn("indexed existing documents", failure.stdout)


if __name__ == "__main__":
    unittest.main()
