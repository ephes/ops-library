"""Once every scheduled Daybook job runs under the operations supervisor, launchd
keeps nothing of them to load.

A retired job is not merely disabled: its plist is deleted, and only after the
label is proven unloaded, while the configuration the supervisor's sources still
run from stays. The runtime role's `closeout` ends a machine's rollback path: the
saved original command goes, and `rollback` refuses from then on.
"""
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def tasks(role, name="main.yml"):
    return yaml.safe_load((ROOT / "roles" / role / "tasks" / name).read_text())


def defaults(role):
    return yaml.safe_load((ROOT / "roles" / role / "defaults/main.yml").read_text())


def names(items):
    return [t.get("name", "") for t in items]


def conditions(task):
    when = task.get("when", [])
    return [when] if isinstance(when, str) else when


def asserted(task):
    return task["ansible.builtin.assert"]["that"]


class VoiceMemoWorkRetiredTests(unittest.TestCase):
    ROLE = "daybook_voice_memo_work_deploy"

    def test_off_by_default_and_never_with_the_job_enabled(self):
        self.assertIs(defaults(self.ROLE)["daybook_voice_memo_work_retired"], False)
        that = asserted(tasks(self.ROLE)[0])
        self.assertIn("not (daybook_voice_memo_work_retired | bool and daybook_voice_memo_work_enabled | bool)", that)

    def test_the_plist_goes_only_after_the_label_is_proven_unloaded(self):
        items = tasks(self.ROLE)
        order = names(items)
        delete = order.index("Delete the retired Voice Memo work plist")
        self.assertLess(order.index("Verify disabled Voice Memo work LaunchAgent is unloaded"), delete)
        self.assertLess(delete, order.index("Stop after applying disabled Voice Memo work state"))
        task = items[delete]
        self.assertEqual(task["ansible.builtin.file"],
                         {"path": "{{ daybook_voice_memo_work_plist_path }}", "state": "absent"})
        self.assertIn("daybook_voice_memo_work_retired | bool", conditions(task))
        self.assertIn("not daybook_voice_memo_work_enabled | bool", conditions(task))


class MailWorkRetiredTests(unittest.TestCase):
    ROLE = "daybook_mail_work_deploy"

    def test_off_by_default_and_only_with_both_controls_off(self):
        self.assertIs(defaults(self.ROLE)["daybook_mail_work_retired"], False)
        that = asserted(tasks(self.ROLE)[0])
        self.assertIn(
            "not (daybook_mail_work_retired | bool and (daybook_mail_work_host_enabled | bool"
            " or daybook_mail_work_worker_enabled | bool))", that)

    def test_each_label_carries_its_own_plist(self):
        loop = next(t for t in tasks(self.ROLE) if t.get("name") == "Apply disabled Daybook mail work state per label")["loop"]
        self.assertEqual([item["plist"] for item in loop],
                         ["{{ daybook_mail_work_plist_path }}", "{{ daybook_mail_work_host_plist_path }}"])

    def test_the_plist_goes_only_after_the_label_is_proven_unloaded(self):
        items = tasks(self.ROLE, "disable.yml")
        order = names(items)
        delete = order.index("disable | Delete the retired Daybook mail work plist")
        self.assertEqual(delete, len(items) - 1)
        self.assertLess(order.index("disable | Verify disabled Daybook mail work LaunchAgent is unloaded"), delete)
        self.assertEqual(items[delete]["ansible.builtin.file"],
                         {"path": "{{ daybook_mail_work_agent.plist }}", "state": "absent"})
        self.assertIn("daybook_mail_work_retired | bool", conditions(items[delete]))


class WeeknotesRetiredTests(unittest.TestCase):
    ROLE = "daybook_sessions_deploy"
    FILE = "weeknotes_reconcile.yml"

    def test_off_by_default_and_never_with_the_unit_enabled(self):
        self.assertIs(defaults(self.ROLE)["daybook_weeknotes_reconcile_launchd_retired"], False)
        that = asserted(tasks(self.ROLE, self.FILE)[0])
        self.assertIn(
            "not (daybook_weeknotes_reconcile_launchd_retired | bool"
            " and daybook_weeknotes_reconcile_launchd_enabled | bool)", that)

    def test_a_retired_plist_is_not_rendered_but_its_configuration_is(self):
        items = tasks(self.ROLE, self.FILE)
        by_name = dict(zip(names(items), items))
        self.assertIn("not (daybook_weeknotes_reconcile_launchd_retired | bool)",
                      conditions(by_name["weeknotes_reconcile | Render launchd plist"]))
        for kept in ("weeknotes_reconcile | Render draft-only launcher",):
            self.assertNotIn("retired", str(conditions(by_name[kept])))

    def test_the_plist_goes_only_after_the_unit_converged_unloaded(self):
        items = tasks(self.ROLE, self.FILE)
        order = names(items)
        delete = order.index("weeknotes_reconcile | Delete the retired launchd plist")
        self.assertLess(order.index("weeknotes_reconcile | Assert requested launchd state converged"), delete)
        self.assertEqual(items[delete]["ansible.builtin.file"],
                         {"path": "{{ daybook_weeknotes_reconcile_launchd_plist_path }}", "state": "absent"})
        self.assertIn("daybook_weeknotes_reconcile_launchd_retired | bool", conditions(items[delete]))

    def test_a_retired_unit_needs_the_verified_epoch_before_its_environment_is_written(self):
        # The source reads the environment on every run and refuses all work
        # without the epoch, so rendering it without would stop the reconciler.
        items = tasks(self.ROLE, self.FILE)
        order = names(items)
        guard = order.index("weeknotes_reconcile | Require verified epoch while the operations source runs the reconciler")
        self.assertLess(order.index("weeknotes_reconcile | Open identity epoch gate after exact verification"), guard)
        self.assertLess(guard, order.index("weeknotes_reconcile | Render mode-0600 managed environment"))
        self.assertEqual(asserted(items[guard]),
                         ["not (daybook_weeknotes_reconcile_launchd_retired | bool)"
                          " or daybook_weeknotes_identity_attestation_verified | bool"])


class RuntimeCloseoutTests(unittest.TestCase):
    ROLE = "daybook_operations_runtime_deploy"

    def test_closeout_is_an_attended_action_that_starts_nothing(self):
        that = asserted(tasks(self.ROLE)[0])
        self.assertIn("daybook_operations_runtime_action in ['install', 'replace', 'cutover', 'rollback', 'closeout']", that)
        self.assertIn("daybook_operations_runtime_action == 'install' or daybook_operations_runtime_confirmed | bool", that)
        self.assertIn("daybook_operations_runtime_action != 'closeout' or not daybook_operations_runtime_start | bool", that)

    def test_closeout_touches_nothing_but_the_saved_command_and_its_marker(self):
        items = tasks(self.ROLE)
        order = names(items)
        close = order.index("Close the machine out")
        stop = order.index("Stop after closing the machine out")
        self.assertEqual(stop, close + 1)
        self.assertEqual(items[stop]["ansible.builtin.meta"], "end_role")
        # Before the code, the profile and every transition.
        self.assertLess(stop, order.index("Install the pinned code where no other role does"))
        steps = tasks(self.ROLE, "closeout.yml")
        changed = [t for t in steps if "ansible.builtin.stat" not in t]
        self.assertEqual([t.get("ansible.builtin.file", t.get("ansible.builtin.copy"))["path" if "ansible.builtin.file" in t else "dest"]
                          for t in changed],
                         ["{{ daybook_operations_runtime_legacy_plist }}", "{{ daybook_operations_runtime_closeout_marker }}"])

    def test_rollback_refuses_once_closed_out(self):
        items = tasks(self.ROLE)
        order = names(items)
        refuse = order.index("Refuse a rollback on a machine that was closed out")
        self.assertLess(order.index("Inspect whether the machine was closed out"), refuse)
        self.assertLess(refuse, order.index("Perform attended supervisor-label transition"))
        self.assertEqual(asserted(items[refuse]),
                         ["daybook_operations_runtime_action != 'rollback' or not daybook_operations_runtime_closed_out.stat.exists"])

    def test_a_later_cutover_saves_nothing(self):
        save = next(t for t in tasks(self.ROLE, "transition.yml") if t["name"] == "transition | Save the label's original command once")
        self.assertIn("not daybook_operations_runtime_closed_out.stat.exists", conditions(save))


if __name__ == "__main__":
    unittest.main()
