"""Contracts for the index-only apt refresh added to ``os_apt_maintenance``.

The maintenance timer installs upgrades, so it runs on a slow weekly cadence.
Monitoring is stricter: ``software_live`` warns when the newest security
InRelease is older than 48 hours, because a "0 pending security updates" verdict
computed from week-old indexes is not evidence of anything. A weekly timer can
never hold a 48-hour budget, so index freshness needs its own daily unit.

These tests execute the rendered runner against a fake ``apt-get`` rather than
only grepping the template, because the two properties that matter - that a
refresh installs nothing, and that it never stamps the maintenance state file -
are behavioural. Asserting them textually would keep passing if the mode were
wired to the wrong function.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/os_apt_maintenance"

SENTINEL_STATE = {
    "host_id": "staging",
    "last_success_at": "2026-09-06T02:17:03Z",
    "last_status": "success",
}


def template_environment(directory: Path) -> Environment:
    environment = Environment(
        loader=FileSystemLoader(directory),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    environment.filters["bool"] = bool
    environment.filters["quote"] = shlex.quote
    environment.filters["to_json"] = json.dumps
    return environment


class RefreshRunnerBehaviourTests(unittest.TestCase):
    """Run the rendered script for real, with apt-get replaced by a stub."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        self.state_dir = self.tmp / "state"
        self.state_dir.mkdir()
        self.state_file = self.state_dir / "state.json"
        self.state_file.write_text(json.dumps(SENTINEL_STATE), encoding="utf-8")

        self.lock_file = self.tmp / "run" / "os-apt-maintenance.lock"
        self.apt_log = self.tmp / "apt-calls.log"

    def _write_fake_apt(self, exit_code: int = 0) -> Path:
        fake = self.tmp / "apt-get"
        fake.write_text(
            "#!/bin/sh\n"
            f'printf "%s\\n" "$*" >> {shlex.quote(str(self.apt_log))}\n'
            f"exit {exit_code}\n",
            encoding="utf-8",
        )
        fake.chmod(0o755)
        return fake

    def _render_runner(self, apt_get: Path) -> Path:
        script = (
            template_environment(ROLE / "templates")
            .get_template("os_apt_maintenance.py.j2")
            .render(
                os_apt_maintenance_host_id="staging",
                os_apt_maintenance_state_dir=str(self.state_dir),
                os_apt_maintenance_state_file=str(self.state_file),
                os_apt_maintenance_lock_file=str(self.lock_file),
                os_apt_maintenance_apt_get_path=str(apt_get),
                os_apt_maintenance_systemctl_path="/usr/bin/systemctl",
                os_apt_maintenance_command_timeout=1800,
                os_apt_maintenance_refresh_command_timeout=900,
                os_apt_maintenance_freshness_max_age_seconds=1209600,
                os_apt_maintenance_auto_reboot=False,
                os_apt_maintenance_update_cache=True,
                os_apt_maintenance_dist_upgrade=True,
                os_apt_maintenance_autoremove=True,
                os_apt_maintenance_autoclean=True,
                os_apt_maintenance_endpoint_enabled=False,
                os_apt_maintenance_endpoint_group="root",
            )
        )
        path = self.tmp / "os-apt-maintenance"
        path.write_text(script, encoding="utf-8")
        path.chmod(0o755)
        return path

    def _run_refresh(self, *, apt_exit_code: int = 0) -> subprocess.CompletedProcess:
        runner = self._render_runner(self._write_fake_apt(apt_exit_code))
        return subprocess.run(
            [sys.executable, str(runner), "--refresh-only"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def _apt_calls(self) -> list[str]:
        if not self.apt_log.exists():
            return []
        return [line for line in self.apt_log.read_text().splitlines() if line]

    def test_refresh_updates_indexes_and_installs_nothing(self) -> None:
        completed = self._run_refresh()

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(self._apt_calls(), ["update"])

    def test_refresh_never_writes_the_maintenance_state_file(self) -> None:
        before = self.state_file.stat().st_mtime_ns

        completed = self._run_refresh()

        self.assertEqual(completed.returncode, 0, completed.stderr)
        # last_success_at means "a full maintenance run succeeded" and feeds the
        # 14-day freshness check. If a refresh stamped it, that check would stay
        # green on a host whose weekly upgrade had been failing for a month.
        self.assertEqual(json.loads(self.state_file.read_text()), SENTINEL_STATE)
        self.assertEqual(self.state_file.stat().st_mtime_ns, before)

    def test_failed_refresh_fails_the_unit_and_leaves_state_alone(self) -> None:
        completed = self._run_refresh(apt_exit_code=100)

        self.assertEqual(completed.returncode, 1)
        self.assertIn("apt-get update failed", completed.stderr)
        self.assertEqual(json.loads(self.state_file.read_text()), SENTINEL_STATE)

    def test_refresh_steps_aside_while_a_maintenance_run_holds_the_lock(self) -> None:
        import fcntl

        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_file.open("w", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            completed = self._run_refresh()

        # A maintenance run refreshes the indexes itself as its first step, so
        # stepping aside is correct - and must not fail the unit, or every
        # overlap would page someone about a non-problem.
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(self._apt_calls(), [])
        self.assertIn("skipping index refresh", completed.stderr)

    def test_refresh_uses_its_own_shorter_timeout(self) -> None:
        runner = self._render_runner(self._write_fake_apt())
        script = runner.read_text()

        self.assertIn("REFRESH_COMMAND_TIMEOUT = 900", script)
        refresh_body = script.split("def run_refresh(", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("timeout=REFRESH_COMMAND_TIMEOUT", refresh_body)


class RefreshUnitTests(unittest.TestCase):
    """The units must schedule daily and must not carry upgrade verbs."""

    def _render(self, name: str, **overrides: object) -> str:
        values: dict[str, object] = {
            "os_apt_maintenance_script_path": "/usr/local/sbin/os-apt-maintenance",
            "os_apt_maintenance_refresh_command_timeout": 900,
            "os_apt_maintenance_refresh_timer_on_calendar": "*-*-* 06:00:00",
            "os_apt_maintenance_refresh_timer_accuracy_sec": "10m",
            "os_apt_maintenance_refresh_timer_randomized_delay_sec": "1h",
            "os_apt_maintenance_refresh_timer_persistent": True,
        }
        values.update(overrides)
        return (
            template_environment(ROLE / "templates").get_template(name).render(**values)
        )

    def test_service_runs_refresh_only(self) -> None:
        unit = self._render("os-apt-maintenance-refresh.service.j2")

        self.assertIn(
            "ExecStart=/usr/local/sbin/os-apt-maintenance --refresh-only", unit
        )
        self.assertEqual(unit.count("ExecStart="), 1)
        for verb in ("dist-upgrade", "autoremove", "autoclean", "reboot"):
            self.assertNotIn(verb, unit)

    def test_service_timeout_outlives_the_command_budget(self) -> None:
        unit = self._render("os-apt-maintenance-refresh.service.j2")

        # systemd must not kill the run before the runner's own timeout fires,
        # or the recorded reason for a hung mirror is lost.
        self.assertIn("TimeoutStartSec=1020", unit)

    def test_timer_is_daily_jittered_and_persistent(self) -> None:
        unit = self._render("os-apt-maintenance-refresh.timer.j2")

        self.assertIn("OnCalendar=*-*-* 06:00:00", unit)
        self.assertIn("RandomizedDelaySec=1h", unit)
        self.assertIn("Persistent=true", unit)
        self.assertIn("WantedBy=timers.target", unit)

    def test_timer_persistence_can_be_turned_off(self) -> None:
        unit = self._render(
            "os-apt-maintenance-refresh.timer.j2",
            os_apt_maintenance_refresh_timer_persistent=False,
        )

        self.assertIn("Persistent=false", unit)


class RefreshRoleWiringTests(unittest.TestCase):
    """Disabling the refresh must actually stop it, not just stop managing it."""

    def setUp(self) -> None:
        self.tasks = (ROLE / "tasks/main.yml").read_text()
        self.defaults = (ROLE / "defaults/main.yml").read_text()
        self.handlers = (ROLE / "handlers/main.yml").read_text()

    def test_refresh_is_on_by_default(self) -> None:
        self.assertIn("os_apt_maintenance_refresh_enabled: true", self.defaults)

    def test_refresh_cadence_is_daily_not_weekly(self) -> None:
        # A weekly refresh cannot hold the 48-hour apt index budget that
        # software_live enforces; that mismatch is the whole reason this exists.
        self.assertIn(
            'os_apt_maintenance_refresh_timer_on_calendar: "*-*-* 06:00:00"',
            self.defaults,
        )

    def test_disabled_refresh_is_stopped_and_removed(self) -> None:
        self.assertIn("Stop apt index refresh timer when disabled", self.tasks)
        self.assertIn("Remove apt index refresh units when disabled", self.tasks)

    def test_refresh_timer_has_a_restart_handler(self) -> None:
        self.assertIn("restart os-apt-maintenance-refresh-timer", self.handlers)
        self.assertIn("restart os-apt-maintenance-refresh-timer", self.tasks)


if __name__ == "__main__":
    unittest.main()
