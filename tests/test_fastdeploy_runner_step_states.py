"""FastDeploy runner reports use only the API's accepted step states."""

import ast
import contextlib
import io
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "roles/fastdeploy_register_service/templates/deploy.py.j2"
ACCEPTED_STATES = {"running", "success", "failure"}
REPORTERS = {"output_step", "update_step", "emit_step", "emit"}
REPORTER_DEFINITION = re.compile(
    r"def\s+(?:" + "|".join(sorted(REPORTERS)) + r")\([^)]*\bstate\b"
)


def state_literals(source):
    # Keep every Python branch, including Jinja loop bodies, for the static
    # audit. Replace template values so the remaining Python can be parsed.
    source = re.sub(r"{{.*?}}", "template_value", source, flags=re.DOTALL)
    source = re.sub(r"{%.*?%}|{#.*?#}", "", source, flags=re.DOTALL)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        values = []
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", getattr(node.func, "attr", ""))
            if name in REPORTERS:
                if len(node.args) >= 2:
                    values.append(node.args[1])
                values.extend(k.value for k in node.keywords if k.arg == "state")
        elif isinstance(node, ast.Dict):
            values.extend(
                value
                for key, value in zip(node.keys, node.values)
                if isinstance(key, ast.Constant) and key.value == "state"
            )
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == "state" for t in targets):
                values.append(node.value)
        for value in values:
            for literal in ast.walk(value):
                if isinstance(literal, ast.Constant) and isinstance(literal.value, str):
                    yield literal.lineno, literal.value


class RunnerStepStatesTests(unittest.TestCase):
    def test_all_runner_state_literals_are_accepted(self):
        found = set()
        scanned = set()
        for directory in (ROOT / "roles", ROOT / "scripts"):
            for path in sorted(directory.rglob("*.py*")):
                if not (path.name.endswith(".py") or path.name.endswith(".py.j2")):
                    continue
                source = path.read_text()
                if not REPORTER_DEFINITION.search(source):
                    continue
                scanned.add(path.relative_to(ROOT).as_posix())
                for line, state in state_literals(source):
                    with self.subTest(path=str(path.relative_to(ROOT)), line=line):
                        self.assertIn(state, ACCEPTED_STATES)
                    found.add(state)
        self.assertEqual(found, ACCEPTED_STATES)
        self.assertIn(
            "roles/daybook_operations_api_backup/files/echoport_runner.py", scanned
        )

    def test_static_audit_covers_literal_forms(self):
        source = """
update_step("verify", "warning", "inactive")
reporter.emit_step(
    name="verify", state="pending")
output_step("result", "success" if ok else "failure")
payload = {"state": "skipped"}
state: str = "cancelled"
emit("backup", "queued")
"""
        self.assertEqual(
            {state for _, state in state_literals(source)},
            {
                "warning",
                "pending",
                "success",
                "failure",
                "skipped",
                "cancelled",
                "queued",
            },
        )

    def test_runner_discovery_excludes_unrelated_emit_helpers(self):
        self.assertTrue(
            REPORTER_DEFINITION.search('def emit(name, state, message=""):')
        )
        self.assertFalse(REPORTER_DEFINITION.search("def emit(inventory):"))

    def test_rendered_runner_verification_is_non_fatal(self):
        cases = [
            ("demo", 0, "active"),
            ("demo", 3, "inactive"),
            ("demo.service", 3, "failed"),
            ("demo", 4, "unknown"),
            ("demo", 1, ""),
            ("", 0, ""),
        ]
        for unit, returncode, unit_state in cases:
            with self.subTest(
                unit=unit, state=unit_state
            ), tempfile.TemporaryDirectory() as workspace, patch.dict(os.environ):
                variables = {
                    "fd_service_name": "demo",
                    "fd_runner_config_path": "",
                    "fd_runner_secret_config_path": "",
                    "fd_ops_control_method": "rsync",
                    "fd_ops_control_ref": "main",
                    "fd_context_defaults": {},
                    "fd_ansible_playbook_bin": "ansible-playbook",
                    "fd_ansible_galaxy_bin": "ansible-galaxy",
                    "fd_sops_age_key_path": "",
                    "fd_ansible_config": "",
                    "fd_ops_control_remote_path": workspace,
                    "fd_workspace_dir": workspace,
                }
                source = (
                    Environment(undefined=StrictUndefined)
                    .from_string(TEMPLATE.read_text())
                    .render(variables)
                )
                namespace = {"__name__": "test_runner"}
                exec(compile(source, str(TEMPLATE), "exec"), namespace)
                namespace["get_cached_config"] = lambda: {
                    "verify": {"systemd_service": unit}
                }
                process = Mock(stdout=[], wait=Mock(return_value=0))
                probe = subprocess.CompletedProcess(
                    [],
                    returncode,
                    stdout=unit_state + "\n",
                    stderr="probe diagnostic" if not unit_state else "",
                )
                output = io.StringIO()
                diagnostics = io.StringIO()
                with patch("subprocess.Popen", return_value=process), patch(
                    "subprocess.run", return_value=probe
                ) as run, contextlib.redirect_stdout(
                    output
                ), contextlib.redirect_stderr(
                    diagnostics
                ):
                    self.assertEqual(namespace["main"](), 0)
                events = [json.loads(line) for line in output.getvalue().splitlines()]
                verification = [e for e in events if e.get("name") == "verify"][-1]
                self.assertEqual(verification["state"], "success")
                if not unit:
                    run.assert_not_called()
                    self.assertEqual(verification["message"], "Verification skipped")
                else:
                    run.assert_called_once_with(
                        ["systemctl", "is-active", "demo.service"],
                        capture_output=True,
                        text=True,
                    )
                    self.assertIn("demo.service", verification["message"])
                    self.assertIn(unit_state or "unknown", verification["message"])
                    self.assertEqual(
                        verification["message"].startswith("WARNING:"), returncode != 0
                    )
                if unit and not unit_state:
                    self.assertIn("probe diagnostic", diagnostics.getvalue())
                self.assertEqual(events[-1]["status"], "success")


if __name__ == "__main__":
    unittest.main()
