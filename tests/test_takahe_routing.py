"""Execute routing tasks in a local sandbox, without root ownership or reloads.

Only owner/group arguments are omitted from the copied tasks for portability.
Task ordering, guards, templates, and file removal use the production definitions.
"""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class TakaheRoutingTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory(prefix="takahe-routing-")
        self.addCleanup(self.sandbox.cleanup)
        self.root = Path(self.sandbox.name)
        self.dynamic = self.root / "dynamic"
        self.managed = self.dynamic / "takahe.yml"
        self.legacy = self.dynamic / "old.yml"
        tasks = yaml.safe_load(
            (ROOT / "roles/takahe_deploy/tasks/traefik.yml").read_text()
        )
        for task in tasks:
            for module in ("ansible.builtin.file", "ansible.builtin.template"):
                if module in task:
                    task[module].pop("owner", None)
                    task[module].pop("group", None)
        (self.root / "routing.yml").write_text(yaml.safe_dump(tasks, sort_keys=False))
        (self.root / "templates").mkdir()
        self.template = self.root / "templates/traefik.yml.j2"
        shutil.copyfile(
            ROOT / "roles/takahe_deploy/templates/traefik.yml.j2", self.template
        )

    def run_tasks(self, paths=None):
        variables = yaml.safe_load(
            (ROOT / "roles/takahe_shared/defaults/main.yml").read_text()
        )
        variables.update(
            takahe_traefik_config_path=str(self.managed),
            takahe_domain="fedi.example.test",
            takahe_nginx_port=10025,
        )
        if paths is not None:
            variables["takahe_traefik_legacy_config_paths"] = paths
        play = [
            {
                "name": "Exercise routing cleanup",
                "hosts": "localhost",
                "gather_facts": False,
                "vars": variables,
                "tasks": [{"ansible.builtin.import_tasks": "routing.yml"}],
                "handlers": [
                    {
                        "name": "reload traefik",
                        "ansible.builtin.debug": {"msg": "Sandbox reload notification"},
                    }
                ],
            }
        ]
        playbook = self.root / "play.yml"
        playbook.write_text(yaml.safe_dump(play, sort_keys=False))
        env = dict(os.environ, ANSIBLE_NOCOLOR="1", ANSIBLE_STDOUT_CALLBACK="default")
        return subprocess.run(
            ["ansible-playbook", "-i", "localhost,", "-c", "local", str(playbook)],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
            check=False,
        )

    def test_render_remove_and_idempotence(self):
        self.dynamic.mkdir()
        self.legacy.write_text("legacy route\n")
        unrelated = self.dynamic / "other.yml"
        unrelated.write_text("other service\n")
        result = self.run_tasks([str(self.legacy)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.legacy.exists())
        self.assertEqual(unrelated.read_text(), "other service\n")
        config = yaml.safe_load(self.managed.read_text())
        servers = config["http"]["services"]["takahe"]["loadBalancer"]["servers"]
        self.assertEqual(servers, [{"url": "http://127.0.0.1:10025"}])
        again = self.run_tasks([str(self.legacy)])
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertRegex(again.stdout, r"changed=0\b")

    def test_default_empty_list_preserves_existing_files(self):
        self.dynamic.mkdir()
        self.legacy.write_text("legacy route\n")
        result = self.run_tasks()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.managed.exists())
        self.assertEqual(self.legacy.read_text(), "legacy route\n")

    def test_render_failure_preserves_legacy(self):
        self.dynamic.mkdir()
        self.legacy.write_text("legacy route\n")
        self.template.unlink()
        result = self.run_tasks([str(self.legacy)])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.legacy.read_text(), "legacy route\n")
        self.assertFalse(self.managed.exists())

    def test_invalid_paths_fail_before_creating_directory(self):
        for invalid in (
            str(self.managed),
            str(self.root / "outside.yml"),
            str(self.dynamic / "old.txt"),
            123,
            str(self.dynamic / "../escape.yml"),
        ):
            with self.subTest(path=invalid):
                result = self.run_tasks([invalid])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Invalid legacy path", result.stdout)
                self.assertFalse(self.dynamic.exists())


if __name__ == "__main__":
    unittest.main()
