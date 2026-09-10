"""Rendered contract tests for the Daybook mail work scheduler.

The properties asserted here are the ones that would be expensive to discover on
a live Mac: that no scheduled invocation carries a window start, that the worker
routes through the capability host rather than trying to act itself, and that the
two agents stay independently controllable.
"""
import plistlib
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/daybook_mail_work_deploy"


class MailWorkRoleTests(unittest.TestCase):
    def variables(self, **overrides):
        values = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        values.update(
            daybook_mail_work_service_user="example",
            daybook_mail_work_assignment_path="/Users/example/daybook/docs/mail-worker-assignment.md",
            daybook_mail_work_cwd="/Users/example/daybook",
        )
        values.update(overrides)
        env = Environment()
        for _ in range(8):
            for name, value in values.items():
                if isinstance(value, str):
                    values[name] = env.from_string(value).render(**values)
        return values

    def render(self, template: str, **overrides):
        values = self.variables(**overrides)
        body = Environment().from_string(
            (ROLE / "templates" / template).read_text()
        ).render(**values)
        return plistlib.loads(body.encode()), body

    # -- the worker -------------------------------------------------------

    def test_a_scheduled_run_never_carries_a_window_start(self):
        """--since overrides the watermark, so a pinned one reprocesses history."""
        plist, body = self.render("mail-work.launchd.plist.j2")
        self.assertNotIn("--since", plist["ProgramArguments"])
        self.assertNotIn("--reseed", plist["ProgramArguments"])
        self.assertNotIn("--since", body)

    def test_the_worker_routes_through_the_capability_host(self):
        plist, _ = self.render("mail-work.launchd.plist.j2")
        argv = plist["ProgramArguments"]
        self.assertIn("--via-host", argv)
        self.assertEqual(argv[argv.index("--via-host") + 1], "daybook-host")
        self.assertEqual(argv[argv.index("--provider") + 1], "claude")

    def test_the_worker_pins_the_socket_directory_it_resolves_against(self):
        """-L resolves against TMUX_TMPDIR, which launchd and the GUI need not share."""
        plist, _ = self.render("mail-work.launchd.plist.j2")
        self.assertEqual(plist["EnvironmentVariables"]["TMUX_TMPDIR"], "/private/tmp")
        self.assertIn("--host-tmpdir", plist["ProgramArguments"])

    def test_the_worker_names_the_executables_its_session_will_use(self):
        """A session in the host inherits the GUI environment, not the agent's."""
        plist, _ = self.render("mail-work.launchd.plist.j2")
        argv = plist["ProgramArguments"]
        for flag in ("--session-tmux", "--claude"):
            self.assertTrue(argv[argv.index(flag) + 1].startswith("/"), flag)

    def test_the_worker_runs_on_an_interval_in_a_gui_session(self):
        plist, _ = self.render("mail-work.launchd.plist.j2")
        self.assertEqual(plist["StartInterval"], 300)
        self.assertEqual(plist["LimitLoadToSessionType"], "Aqua")
        self.assertNotIn("KeepAlive", plist)

    # -- the host ---------------------------------------------------------

    def test_the_host_agent_goes_through_ensure_not_straight_at_open(self):
        """`open -na` always launches a new instance; ensure gates before it."""
        plist, _ = self.render("mail-work-host.launchd.plist.j2")
        argv = plist["ProgramArguments"]
        self.assertEqual(argv[1:4], ["work", "host", "ensure"])
        self.assertNotIn("/usr/bin/open", argv[0])
        self.assertIn("--lock", argv)

    def test_the_host_is_re_ensured_far_less_often_than_the_worker_runs(self):
        host, _ = self.render("mail-work-host.launchd.plist.j2")
        worker, _ = self.render("mail-work.launchd.plist.j2")
        self.assertTrue(host["RunAtLoad"])
        self.assertGreaterEqual(host["StartInterval"], 3600)
        self.assertGreater(host["StartInterval"], worker["StartInterval"] * 10)
        self.assertEqual(host["LimitLoadToSessionType"], "Aqua")

    # -- the role ---------------------------------------------------------

    def test_the_worker_cannot_be_enabled_without_a_host(self):
        tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
        guard = next(t for t in tasks if t["name"].startswith("Require a capability host"))
        self.assertEqual(guard["when"], "daybook_mail_work_worker_enabled | bool")
        self.assertIn("daybook_mail_work_host_enabled | bool",
                      guard["ansible.builtin.assert"]["that"])

    def test_the_notify_config_must_exist_before_anything_is_installed(self):
        tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
        inspect = next(t for t in tasks if t["name"].startswith("Inspect existing"))
        self.assertIn("{{ daybook_mail_work_notify_config_path }}", inspect["loop"])

    def test_state_may_be_shared_with_manual_runs(self):
        """Pinning state under the runtime dir forced a second watermark."""
        body = (ROLE / "tasks/main.yml").read_text()
        self.assertNotIn("daybook_mail_work_state_path == daybook_mail_work_runtime_dir", body)
        self.assertNotIn("daybook_mail_work_mail_state_path == daybook_mail_work_runtime_dir", body)

    def test_both_agents_default_to_off(self):
        values = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        self.assertFalse(values["daybook_mail_work_host_enabled"])
        self.assertFalse(values["daybook_mail_work_worker_enabled"])
        self.assertEqual(values["daybook_mail_work_provider"], "claude")

    def test_each_label_is_disabled_and_reloaded_on_its_own(self):
        for name in ("disable.yml", "enable.yml"):
            body = (ROLE / "tasks" / name).read_text()
            self.assertIn("daybook_mail_work_agent.label", body)
            self.assertNotIn("daybook_mail_work_launchd_label }}\"]\n", body)

    def test_the_role_refuses_a_rendered_plist_that_carries_since(self):
        tasks = yaml.safe_load((ROLE / "tasks/enable.yml").read_text())
        guard = next(t for t in tasks if t["name"].endswith("Refuse a scheduled window start"))
        self.assertIn("'--since' not in (daybook_mail_work_installed.content | b64decode)",
                      guard["ansible.builtin.assert"]["that"])
        # It must read the file back from the managed host: a controller-side
        # lookup would inspect a filesystem where no plist was ever written.
        self.assertTrue(any(t.get("ansible.builtin.slurp") for t in tasks))


if __name__ == "__main__":
    unittest.main()
