"""A timer whose work moved to the Daybook operations supervisor can be retired
without taking the configuration that work still runs from.

The operations supervisor runs session shipping and the archive quote classifier
as sources, from the same `sessions.env` and `archive-quotes.env` this role
writes. Retiring their launchd timers must therefore remove only the schedule --
and must remove it for good, because a timer and a source for the same work must
never both be able to run it.
"""
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/daybook_sessions_deploy"


def tasks(name="main.yml"):
    return yaml.safe_load((ROLE / "tasks" / name).read_text())


def named(prefix, name="main.yml"):
    return next(t for t in tasks(name) if t.get("name", "").endswith(prefix))


def conditions(task):
    when = task.get("when", [])
    return [when] if isinstance(when, str) else when


class RetireTimerTests(unittest.TestCase):
    def test_both_switches_default_to_scheduling_as_before(self):
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        self.assertIs(defaults["daybook_sessions_launchd_enabled"], True)
        self.assertIs(defaults["daybook_archive_quote_classifier_launchd_enabled"], True)

    def test_the_configuration_is_written_whether_or_not_launchd_schedules_it(self):
        for task in ("Render Daybook sessions environment file",
                     "Render archive quote classifier environment file",
                     "Render Daybook sessions launchd launcher",
                     "Render archive quote classifier launchd launcher"):
            found = [t for t in tasks() if t.get("name", "").endswith(task)]
            self.assertTrue(found, task)
            joined = " ".join(conditions(found[0]))
            self.assertNotIn("launchd_enabled", joined, task)

    def test_a_retired_timer_is_never_rendered_loaded_or_started(self):
        for task in ("Render Daybook sessions plist", "Bootstrap Daybook sessions unit",
                     "Enable Daybook sessions unit",
                     "Kickstart Daybook sessions unit after deploy changes",
                     "Unload existing Daybook sessions unit before bootstrap"):
            self.assertIn("daybook_sessions_launchd_enabled | bool", conditions(named(task)), task)
        for task in ("Render archive quote classifier plist", "Bootstrap archive quote classifier unit",
                     "Enable archive quote classifier unit",
                     "Kickstart archive quote classifier unit after deploy changes",
                     "Unload existing archive quote classifier unit before bootstrap"):
            self.assertIn("daybook_archive_quote_classifier_launchd_enabled | bool",
                          conditions(named(task)), task)

    def test_disabling_the_classifier_itself_still_removes_everything(self):
        removal = named("Remove disabled archive quote classifier files")
        self.assertIn("{{ daybook_archive_quote_classifier_env_file }}", removal["loop"])
        self.assertNotIn("launchd_enabled", " ".join(conditions(removal)))

    def test_retiring_unloads_disables_removes_and_proves_it(self):
        steps = tasks("retire_timer.yml")
        names = [t["name"] for t in steps]
        self.assertEqual(names, [
            "retire_timer | Inspect the timer being retired",
            "retire_timer | Refuse to retire a timer while its run is in flight",
            "retire_timer | Unload the timer",
            "retire_timer | Disable the timer's label persistently",
            "retire_timer | Remove the timer's plist",
            "retire_timer | Prove the timer is gone",
        ])
        refuse = steps[1]["ansible.builtin.assert"]["that"][0]
        self.assertIn("running|spawning", refuse)
        self.assertEqual(steps[5]["failed_when"], "daybook_sessions_retired_status.rc != 113")
        self.assertEqual(steps[4]["ansible.builtin.file"]["state"], "absent")

    def test_the_retire_loop_covers_both_timers(self):
        include = named("Retire timers whose work now runs under the operations supervisor")
        labels = [item["label"] for item in include["loop"]]
        self.assertEqual(labels, ["{{ daybook_sessions_launchd_label }}",
                                  "{{ daybook_archive_quote_classifier_launchd_label }}"])
        self.assertIn("daybook_sessions_launchd_manage_state | bool", conditions(include))


if __name__ == "__main__":
    unittest.main()
