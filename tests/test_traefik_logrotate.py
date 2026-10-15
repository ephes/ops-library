"""Traefik log rotation must keep the running Traefik writing to fresh files.

The postrotate script used to run ``systemctl reload traefik || true``. The
role's unit has no ExecReload, so the reload failed, ``|| true`` hid it, and
Traefik kept writing to the renamed ``access.log.1`` (465 MB on macmini) while
the fresh ``access.log`` stayed empty and ``notifempty`` never rotated it
again. Traefik reopens its access log on SIGUSR1, so the script signals the
main PID directly. It never reopens its own ``traefik.log``
(``RotateAccessLogs`` is the only SIGUSR1 action), so that file is rotated with
``copytruncate``. The script runs here against a stub ``systemctl``; the
Molecule scenario rotates for real.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "traefik_deploy"


def render_logrotate(**overrides: object) -> str:
    defaults = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
    context = {**defaults, **overrides}
    env = Environment(loader=FileSystemLoader(ROLE / "templates"), undefined=StrictUndefined)
    return env.get_template("traefik.logrotate.j2").render(**context)


def stanzas(config: str) -> dict[str, list[str]]:
    """Map each log path to the directives of its block (comments dropped)."""
    lines = [line.strip() for line in config.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    blocks: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in lines:
        if line.endswith("{"):
            current = blocks.setdefault(line[:-1].strip(), [])
        elif line == "}":
            current = None
        else:
            assert current is not None, f"directive outside a block: {line}"
            current.append(line)
    return blocks


def postrotate_script(config: str) -> str:
    match = re.search(r"^\s*postrotate\n(.*?)^\s*endscript$", config, re.S | re.M)
    assert match, "postrotate block missing"
    return textwrap.dedent(match.group(1))


ACCESS = "/var/log/traefik/access.log"
GENERAL = "/var/log/traefik/traefik.log"


class TraefikLogrotateConfigTest(unittest.TestCase):
    def test_rotation_policy(self) -> None:
        blocks = stanzas(render_logrotate())
        # Order matters: the SIGUSR1 log line must land in the fresh traefik.log.
        self.assertEqual(list(blocks), [GENERAL, ACCESS])
        for path, block in blocks.items():
            for directive in ("daily", "rotate 7", "compress", "delaycompress", "missingok", "notifempty"):
                self.assertIn(directive, block, path)
        for block in stanzas(render_logrotate(traefik_logrotate_days=14)).values():
            self.assertIn("rotate 14", block)

    def test_access_log_is_renamed_and_reopened(self) -> None:
        block = stanzas(render_logrotate())[ACCESS]
        self.assertIn("create 0644 root root", block)
        self.assertIn("postrotate", block)
        self.assertNotIn("copytruncate", block)

    def test_general_log_is_copied_and_truncated(self) -> None:
        # Traefik never reopens traefik.log; a rename would strand it on .1.
        block = stanzas(render_logrotate())[GENERAL]
        self.assertIn("copytruncate", block)
        self.assertNotIn("postrotate", block)
        self.assertFalse([line for line in block if line.startswith("create")])

    def test_postrotate_does_not_rely_on_reload(self) -> None:
        unit = (ROLE / "templates" / "traefik.service.j2").read_text()
        script = postrotate_script(render_logrotate())
        if "ExecReload" not in unit:
            self.assertNotIn("reload", script)
        self.assertNotIn("|| true", script, "a failed signal must reach logrotate's exit status")
        self.assertNotIn("/dev/null", script)


class TraefikPostrotateScriptTest(unittest.TestCase):
    """Run the rendered postrotate script under /bin/sh with a stub systemctl."""

    def run_script(self, *, active: bool, kill_rc: int = 0) -> tuple[int, list[str]]:
        script = postrotate_script(render_logrotate())
        with tempfile.TemporaryDirectory() as tmp:
            calls = Path(tmp) / "calls"
            stub = Path(tmp) / "systemctl"
            stub.write_text(textwrap.dedent(f"""\
                #!/bin/sh
                echo "$*" >> {calls}
                case "$1" in
                  is-active) exit {0 if active else 3} ;;
                  kill) exit {kill_rc} ;;
                esac
                exit 99
                """))
            stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
            env = {**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}"}
            result = subprocess.run(["/bin/sh", "-c", script], env=env, check=False)
            recorded = calls.read_text().splitlines() if calls.exists() else []
        return result.returncode, recorded

    def test_signals_main_process_with_usr1(self) -> None:
        rc, calls = self.run_script(active=True)
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [
            "is-active --quiet traefik.service",
            "kill --signal=USR1 --kill-whom=main traefik.service",
        ])

    def test_stopped_traefik_is_not_signalled(self) -> None:
        rc, calls = self.run_script(active=False)
        self.assertEqual(rc, 0)
        self.assertEqual(calls, ["is-active --quiet traefik.service"])

    def test_failed_signal_fails_the_script(self) -> None:
        rc, _ = self.run_script(active=True, kill_rc=1)
        self.assertNotEqual(rc, 0)


class TraefikLogrotateTasksTest(unittest.TestCase):
    def test_full_deploy_imports_the_standalone_entry(self) -> None:
        tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
        imports = [task.get("ansible.builtin.import_tasks") for task in tasks]
        self.assertIn("logrotate.yml", imports)
        self.assertNotIn("/etc/logrotate.d/traefik", (ROLE / "tasks" / "main.yml").read_text())

    def test_standalone_entry_only_writes_the_logrotate_file(self) -> None:
        tasks = yaml.safe_load((ROLE / "tasks" / "logrotate.yml").read_text())
        self.assertEqual(len(tasks), 1)
        task = tasks[0]
        self.assertEqual(task["ansible.builtin.template"]["src"], "traefik.logrotate.j2")
        self.assertEqual(task["ansible.builtin.template"]["dest"], "/etc/logrotate.d/traefik")
        self.assertEqual(task["ansible.builtin.template"]["mode"], "0644")
        # Usable on transaction-managed hosts: no handler may restart Traefik.
        self.assertNotIn("notify", task)


if __name__ == "__main__":
    unittest.main()
