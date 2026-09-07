import json
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
from ansible.plugins.filter.core import FilterModule
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/voxhelm_deploy"


class VoxhelmCsrfEnvironmentTests(unittest.TestCase):
    def test_ansible_rejects_malformed_origins_before_deployment(self):
        tasks = yaml.safe_load((ROLE / "tasks/validate.yml").read_text())
        tasks = [
            task
            for task in tasks
            if task.get("name", "").startswith("validate | Validate CSRF")
        ]
        self.assertEqual(len(tasks), 2)
        cases = [
            ([], True),
            (["https://voxhelm.example.com"], True),
            ("https://voxhelm.example.com", False),
            (["voxhelm.example.com"], False),
            (["https://voxhelm.example.com/path"], False),
            (["https://voxhelm.example.com\n"], False),
        ]
        with tempfile.TemporaryDirectory() as directory:
            playbook = Path(directory) / "validate.json"
            playbook.write_text(
                json.dumps(
                    [{"hosts": "localhost", "gather_facts": False, "tasks": tasks}]
                )
            )
            for origins, valid in cases:
                with self.subTest(origins=origins):
                    result = subprocess.run(
                        [
                            "ansible-playbook",
                            "-i",
                            "localhost,",
                            "-c",
                            "local",
                            str(playbook),
                            "-e",
                            json.dumps({"voxhelm_csrf_trusted_origins": origins}),
                        ],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    self.assertEqual(
                        result.returncode,
                        0 if valid else 2,
                        result.stdout + result.stderr,
                    )

    def test_rendered_origins_round_trip_through_shell_environment(self):
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        self.assertEqual(defaults["voxhelm_csrf_trusted_origins"], [])
        env = Environment(undefined=StrictUndefined)
        env.filters.update(FilterModule().filters())
        template = env.from_string((ROLE / "templates/voxhelm.env.j2").read_text())
        for origins in (
            [],
            ["https://voxhelm.example.com"],
            ["https://voxhelm.example.com", "https://alternate.example.com:8443"],
        ):
            with self.subTest(origins=origins):
                rendered = template.render(
                    {**defaults, "voxhelm_csrf_trusted_origins": origins}
                )
                lines = [
                    line
                    for line in rendered.splitlines()
                    if line.startswith("VOXHELM_CSRF_TRUSTED_ORIGINS=")
                ]
                self.assertEqual(len(lines), 1)
                words = shlex.split(lines[0])
                self.assertEqual(len(words), 1)
                value = words[0].partition("=")[2]
                self.assertEqual(value, ",".join(origins))


if __name__ == "__main__":
    unittest.main()
