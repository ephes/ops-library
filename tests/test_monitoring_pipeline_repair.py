"""Regression tests for the two monitoring pipelines that failed silently.

Both defects hid a real problem behind a broken collector rather than behind a
wrong threshold, so both fixes are about keeping the pipeline honest:

* ``os_apt_maintenance`` wrote its state file 0600 root:root and relied on
  ``ExecStartPost=`` to widen it.  systemd skips ``ExecStartPost=`` when
  ``ExecStart=`` fails, so every failed apt run left the monitoring endpoint
  answering ``503`` - erasing the failure it had just recorded.
* ``tailscale_metrics_endpoint`` armed its collector with monotonic-only timer
  triggers.  A timer started after its ``OnBootSec=`` anchor has passed parks as
  ``active (elapsed)`` with no next elapse, freezing the payload while every
  ``summary`` assertion built on it keeps reporting green.
"""

from __future__ import annotations

import ast
import json
import shlex
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]


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


APT_ROLE = ROOT / "roles/os_apt_maintenance"
TAILSCALE_ROLE = ROOT / "roles/tailscale_metrics_endpoint"


class OsAptMaintenanceStateFilePermissionTests(unittest.TestCase):
    """A failed apt run must still leave a readable state file."""

    def _render_script(self, *, endpoint_enabled: bool) -> str:
        return (
            template_environment(APT_ROLE / "templates")
            .get_template("os_apt_maintenance.py.j2")
            .render(
                os_apt_maintenance_host_id="fractal",
                os_apt_maintenance_state_dir="/var/lib/os-apt-maintenance",
                os_apt_maintenance_state_file="/var/lib/os-apt-maintenance/state.json",
                os_apt_maintenance_lock_file="/var/lock/os-apt-maintenance.lock",
                os_apt_maintenance_apt_get_path="/usr/bin/apt-get",
                os_apt_maintenance_systemctl_path="/usr/bin/systemctl",
                os_apt_maintenance_command_timeout=1800,
                os_apt_maintenance_freshness_max_age_seconds=1209600,
                os_apt_maintenance_auto_reboot=False,
                os_apt_maintenance_update_cache=True,
                os_apt_maintenance_dist_upgrade=True,
                os_apt_maintenance_autoremove=True,
                os_apt_maintenance_autoclean=True,
                os_apt_maintenance_endpoint_enabled=endpoint_enabled,
                os_apt_maintenance_endpoint_group="metrics",
            )
        )

    def test_writer_stamps_group_and_mode_on_every_write(self) -> None:
        script = self._render_script(endpoint_enabled=True)

        # The rendered script must stay valid Python.
        ast.parse(script)

        self.assertIn('STATE_FILE_GROUP = "metrics"', script)
        self.assertIn("STATE_FILE_MODE = 0o640", script)
        self.assertIn("def apply_state_file_permissions(fileno: int) -> None:", script)
        self.assertIn("os.fchmod(fileno, STATE_FILE_MODE)", script)
        self.assertIn("os.fchown(fileno, -1, gid)", script)
        self.assertIn("grp.getgrnam(STATE_FILE_GROUP)", script)
        # Applied on the temp fd, before os.replace, so the durable file is
        # already correct no matter how the run ends.
        write_body = script.split("def atomic_write_json(", 1)[1]
        permission_call = write_body.index(
            "apply_state_file_permissions(handle.fileno())"
        )
        replace_call = write_body.index("os.replace(tmp_name, path)")
        self.assertLess(permission_call, replace_call)

    def test_endpoint_disabled_keeps_root_owned_world_readable_state(self) -> None:
        script = self._render_script(endpoint_enabled=False)

        ast.parse(script)
        self.assertIn('STATE_FILE_GROUP = "root"', script)
        self.assertIn("STATE_FILE_MODE = 0o644", script)

    def test_unit_repairs_permissions_after_a_failed_run(self) -> None:
        unit = (
            template_environment(APT_ROLE / "templates")
            .get_template("os-apt-maintenance.service.j2")
            .render(
                os_apt_maintenance_script_path="/usr/local/sbin/os-apt-maintenance",
                os_apt_maintenance_state_dir="/var/lib/os-apt-maintenance",
                os_apt_maintenance_state_file="/var/lib/os-apt-maintenance/state.json",
                os_apt_maintenance_endpoint_enabled=True,
                os_apt_maintenance_endpoint_group="metrics",
                os_apt_maintenance_command_timeout=1800,
            )
        )

        # ExecStartPost= is skipped when ExecStart= exits non-zero; ExecStopPost=
        # is not.  The state-file fix-up must never sit on the skipped hook.
        self.assertNotIn(
            "ExecStartPost=/bin/chown root:metrics "
            "/var/lib/os-apt-maintenance/state.json",
            unit,
        )
        self.assertNotIn(
            "ExecStartPost=/bin/chmod 0640 /var/lib/os-apt-maintenance/state.json",
            unit,
        )
        self.assertIn(
            "ExecStopPost=-/bin/chown root:metrics "
            "/var/lib/os-apt-maintenance/state.json",
            unit,
        )
        self.assertIn(
            "ExecStopPost=-/bin/chmod 0640 /var/lib/os-apt-maintenance/state.json",
            unit,
        )
        # The directory hooks stay on ExecStartPre= - they must exist before the
        # script writes anything.
        self.assertIn("ExecStartPre=/bin/mkdir -p /var/lib/os-apt-maintenance", unit)


class TailscaleCollectorTimerArmingTests(unittest.TestCase):
    """The collector timer must always have a next elapse."""

    def _render_timer(self, **overrides: object) -> str:
        defaults = yaml.safe_load((TAILSCALE_ROLE / "defaults/main.yml").read_text())
        context = {
            "tailscale_metrics_endpoint_timer_interval": defaults[
                "tailscale_metrics_endpoint_timer_interval"
            ],
            "tailscale_metrics_endpoint_timer_on_boot_sec": defaults[
                "tailscale_metrics_endpoint_timer_on_boot_sec"
            ],
            "tailscale_metrics_endpoint_timer_on_calendar": defaults[
                "tailscale_metrics_endpoint_timer_on_calendar"
            ],
            "tailscale_metrics_endpoint_timer_accuracy_sec": defaults[
                "tailscale_metrics_endpoint_timer_accuracy_sec"
            ],
            "tailscale_metrics_endpoint_timer_randomized_delay_sec": defaults[
                "tailscale_metrics_endpoint_timer_randomized_delay_sec"
            ],
        }
        context.update(overrides)
        return (
            template_environment(TAILSCALE_ROLE / "templates")
            .get_template("tailscale-metrics-collector.timer.j2")
            .render(**context)
        )

    def test_timer_has_a_wall_clock_anchor_and_an_activation_anchor(self) -> None:
        timer = self._render_timer()

        # OnBootSec= alone is the defect: it is already in the past whenever the
        # timer unit is started later in the boot, and OnUnitActiveSec= has no
        # anchor until the service has run once.
        self.assertIn("OnBootSec=45", timer)
        self.assertIn("OnActiveSec=300", timer)
        self.assertIn("OnUnitActiveSec=300", timer)
        self.assertIn("OnCalendar=*:0/5", timer)
        # Persistent= only has an effect together with OnCalendar=.
        self.assertIn("Persistent=true", timer)
        calendar_line = timer.index("OnCalendar=")
        persistent_line = timer.index("Persistent=true")
        self.assertLess(calendar_line, persistent_line)

    def test_defaults_keep_the_wall_clock_anchor_configurable(self) -> None:
        defaults = yaml.safe_load((TAILSCALE_ROLE / "defaults/main.yml").read_text())

        self.assertEqual(
            defaults["tailscale_metrics_endpoint_timer_on_calendar"], "*:0/5"
        )
        self.assertEqual(defaults["tailscale_metrics_endpoint_timer_interval"], 300)

    def test_role_detects_and_repairs_a_parked_timer(self) -> None:
        tasks = yaml.safe_load((TAILSCALE_ROLE / "tasks/main.yml").read_text())
        names = []

        def collect(block: object) -> None:
            if isinstance(block, list):
                for entry in block:
                    collect(entry)
            elif isinstance(block, dict):
                if "name" in block and isinstance(block["name"], str):
                    names.append(block["name"])
                for key in ("block", "rescue", "always"):
                    if key in block:
                        collect(block[key])

        collect(tasks)

        for expected in (
            "Read collector timer next monotonic elapse",
            "Read collector timer next realtime elapse",
            "Determine whether the collector timer is armed",
            "Re-arm a collector timer that elapsed without a next trigger",
            "Re-read collector timer next elapse after repair",
            "Require an armed collector timer",
        ):
            with self.subTest(task=expected):
                self.assertIn(expected, names)

        raw = (TAILSCALE_ROLE / "tasks/main.yml").read_text()
        self.assertIn("--property=NextElapseUSecMonotonic", raw)
        self.assertIn("--property=NextElapseUSecRealtime", raw)
        # `state: started` cannot repair an already-active timer, so the repair
        # has to restart it.
        self.assertIn("state: restarted", raw)
        self.assertIn("not (tailscale_metrics_endpoint_timer_armed | bool)", raw)

        # Regression: the post-repair gate must apply the SAME predicate as the
        # arming check. An earlier revision armed on "realtime OR monotonic" but
        # asserted on realtime alone, so a legitimately monotonic-armed timer -
        # or one transiently in `running` state while the collector service it
        # triggers executes - failed the assert. That assert runs on every
        # production tailscale deploy, so the mismatch was a deploy-breaker.
        recheck = self._task_named(
            tasks, "Re-read collector timer next elapse after repair"
        )
        gate = self._task_named(tasks, "Require an armed collector timer")
        for label, expression in (
            ("until", recheck["until"]),
            ("assert", " ".join(gate["ansible.builtin.assert"]["that"])),
        ):
            with self.subTest(gate=label):
                self.assertIn("NextElapseUSecRealtime", expression)
                self.assertIn("NextElapseUSecMonotonic", expression)
                self.assertIn("'infinity'", expression)
        # The recheck reads both properties in one call, so it must not use
        # --value (which would strip the property names the predicate matches on).
        self.assertNotIn("--value", yaml.safe_dump(recheck))

        # Regression: every task in the arming sequence must be skipped under
        # --check. Unit rendering and startup above are check-mode no-ops, so on
        # a first deployment the timer does not exist; probes that force
        # `check_mode: false` would query a nonexistent unit and the final
        # assert would fail a otherwise-valid --check run.
        for name in (
            "Read collector timer next monotonic elapse",
            "Read collector timer next realtime elapse",
            "Determine whether the collector timer is armed",
            "Re-arm a collector timer that elapsed without a next trigger",
            "Re-read collector timer next elapse after repair",
            "Require an armed collector timer",
        ):
            with self.subTest(check_mode_guard=name):
                task = self._task_named(tasks, name)
                self.assertIsNotNone(task, f"missing task: {name}")
                cond = task.get("when")
                conds = cond if isinstance(cond, list) else [cond]
                rendered = " ".join(str(c) for c in conds)
                self.assertIn(
                    "not ansible_check_mode",
                    rendered,
                    f"{name} is not guarded against --check",
                )

    @staticmethod
    def _task_named(block: object, wanted: str) -> dict:
        if isinstance(block, list):
            for entry in block:
                found = TailscaleCollectorTimerArmingTests._task_named(entry, wanted)
                if found is not None:
                    return found
        elif isinstance(block, dict):
            if block.get("name") == wanted:
                return block
            for key in ("block", "rescue", "always"):
                if key in block:
                    found = TailscaleCollectorTimerArmingTests._task_named(
                        block[key], wanted
                    )
                    if found is not None:
                        return found
        return None


class ExecutableCoverageTests(unittest.TestCase):
    """Both repairs are driven against real systemd, not only string-matched.

    A rendered-template assertion cannot tell whether systemd actually keeps a
    failed unit's state file readable, or whether a parked timer is really
    detected - which is the exact class of bug both repairs address.
    """

    def setUp(self) -> None:
        self.justfile = (ROOT / "justfile").read_text()
        self.default_recipe = next(
            line for line in self.justfile.splitlines() if line.startswith("test:")
        )

    def test_a_failing_apt_run_is_exercised_in_molecule(self) -> None:
        verify = (
            ROOT
            / "roles/os_apt_maintenance/molecule/default/verify.yml"
        ).read_text()

        self.assertIn("Install an apt-get stub that always fails", verify)
        self.assertIn("Reset the state file to the unreadable pre-fix permissions", verify)
        self.assertIn("Assert the failed run left a readable state file", verify)
        self.assertIn("Assert the writer stamps the permissions itself", verify)
        self.assertIn("Assert the failure is reported, not hidden behind a 503", verify)

        self.assertIn("test-os-apt-maintenance-failed-run:", self.justfile)
        self.assertIn("test-os-apt-maintenance-failed-run", self.default_recipe)

    def test_a_parked_collector_timer_is_exercised_in_molecule(self) -> None:
        verify = (
            ROOT
            / "roles/tailscale_metrics_endpoint/molecule/default/verify.yml"
        ).read_text()

        self.assertIn("Assert the deployed timer is armed", verify)
        self.assertIn("Assert the collector really runs again", verify)
        self.assertIn("Park the collector timer", verify)
        self.assertIn("Assert the parking reproduction actually parked the timer", verify)
        self.assertIn("Assert a permanently parked timer fails the deployment", verify)
        self.assertIn("Assert the role left the timer armed", verify)

        self.assertIn("test-tailscale-metrics-timer:", self.justfile)
        self.assertIn("test-tailscale-metrics-timer", self.default_recipe)


if __name__ == "__main__":  # pragma: no cover - convenience entry point
    unittest.main()
