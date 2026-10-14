"""`stop` and `verify` of daybook_operations_runtime_deploy, run by real Ansible.

launchctl, pgrep, kill, tmux and the Daybook interpreter are stubs that keep
their state in files under a temporary directory and log every call, so the
tests prove what the role would do to a machine without touching one.
"""

import getpass
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = "daybook_operations_runtime_deploy"

LAUNCHCTL = textwrap.dedent(
    """\
    #!/bin/sh
    echo "launchctl $*" >> "$STATE/calls"
    case "$1" in
      print)
        case "$2" in
          */*/*)
            [ -e "$STATE/loaded" ] || exit 113
            printf 'state = running\\n\\targuments = {\\n\\t\\toperations\\n\\t\\t%s\\n\\t}\\n' "${STUB_LABEL_COMMAND:-host-keep}"
            exit 0 ;;
          *) exit "${STUB_DOMAIN_RC:-0}" ;;
        esac ;;
      bootout)
        [ -e "$STATE/loaded" ] || exit 113
        rm -f "$STATE/loaded"; exit 0 ;;
      bootstrap)
        [ -n "$STUB_BOOTSTRAP_FAILS" ] && exit 5
        touch "$STATE/loaded"
        # The keeper starts the supervisor inside the host.
        [ -n "$STUB_KEEPER_STARTS" ] && touch "$STATE/serve" "$STATE/session"
        exit 0 ;;
      enable) exit 0 ;;
    esac
    exit 64
    """
)
PGREP = textwrap.dedent(
    """\
    #!/bin/sh
    echo "pgrep $*" >> "$STATE/calls"
    [ -e "$STATE/serve" ] || exit 1
    echo 4242
    """
)
KILL = textwrap.dedent(
    """\
    #!/bin/sh
    echo "kill $*" >> "$STATE/calls"
    [ -n "$STUB_IGNORES_TERM" ] && exit 0
    rm -f "$STATE/serve" "$STATE/session"
    # A supervisor that leaves a record behind when it exits.
    [ -n "$STUB_LEAVES_RECORD" ] && touch "$STATE/journal/deliveries/left.json"
    exit 0
    """
)
TMUX = textwrap.dedent(
    """\
    #!/bin/sh
    echo "tmux $* TMUX_TMPDIR=$TMUX_TMPDIR" >> "$STATE/calls"
    case "$*" in
      *"-t =supervisor") [ -e "$STATE/session" ] && exit 0; exit 1 ;;
      *"-t =host") [ -e "$STATE/host" ] && exit 0; exit 1 ;;
    esac
    exit 64
    """
)
# The machine's clock: each call answers the next line of $STATE/clock (the last
# one repeats), so a test can let time pass between two looks.
DATE = textwrap.dedent(
    """\
    #!/bin/sh
    echo "date $* TZ=$TZ" >> "$STATE/calls"
    n=$(grep -c '^date ' "$STATE/calls")
    lines=$(wc -l < "$STATE/clock")
    [ "$n" -gt "$lines" ] && n=$lines
    sed -n "${n}p" "$STATE/clock"
    """
)
# The Daybook interpreter: `python -I -c ... operations status --policy P
# --policy-owner O --binding NAME`. STUB_SOURCES maps each known source to its
# server active_state ("-" for none); an unknown source answers like the CLI does.
PYTHON = textwrap.dedent(
    f"""\
    #!{sys.executable}
    import json, os, sys
    with open(os.environ["STATE"] + "/calls", "a") as calls:
        calls.write("python " + " ".join(sys.argv[3:]) + "\\n")
    name = sys.argv[sys.argv.index("--binding") + 1]
    sources = dict(item.split("=") for item in os.environ.get("STUB_SOURCES", "").split(",") if item)
    if name not in sources:
        print(json.dumps({{"status": "api_unavailable"}}))
        raise SystemExit(75)
    active = None if sources[name] == "-" else sources[name]
    print(json.dumps({{"status": os.environ.get("STUB_LOCAL", "idle"), "enabled": True,
                      "binding": name, "deliveries": [],
                      "server": {{"enabled": True, "active_state": active,
                                 "disposition": "scanned", "stale": False}}}}))
    """
)


@unittest.skipUnless(shutil.which("ansible-playbook"), "needs ansible-playbook")
class RuntimeStopTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="test-runtime-stop-")
        self.base = Path(self._tmp.name)
        self.state = self.base / "state"
        (self.state / "journal" / "deliveries").mkdir(parents=True)
        (self.state / "journal" / "halts").mkdir()
        self.bin = self.base / "bin"
        self.bin.mkdir()
        for name, body in (("launchctl", LAUNCHCTL), ("pgrep", PGREP), ("kill", KILL),
                           ("tmux", TMUX), ("python", PYTHON), ("date", DATE)):
            path = self.bin / name
            path.write_text(body)
            path.chmod(0o755)
        (self.state / "clock").write_text("12:00\n")
        self.plist = self.base / "keeper.plist"
        self.plist.write_text("<plist><string>operations</string><string>host-keep</string></plist>")
        self.install = self.base / "install"
        (self.install / "daybook").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(self.install / "daybook")], check=True)
        subprocess.run(
            ["git", "-C", str(self.install / "daybook"), "-c", "user.name=t", "-c", "user.email=t@t",
             "commit", "-q", "--allow-empty", "-m", "x"],
            check=True,
        )
        self.revision = subprocess.run(
            ["git", "-C", str(self.install / "daybook"), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

    def tearDown(self):
        self._tmp.cleanup()

    def running(self):
        """A supervisor at work: keeper loaded, serve running in its session, host up."""
        for name in ("loaded", "serve", "session", "host"):
            (self.state / name).touch()

    def run_role(self, action="stop", sources="regular=-,weeknotes=-", **variables):
        values = {
            "ansible_connection": "local",
            "ansible_python_interpreter": sys.executable,
            "daybook_operations_runtime_action": action,
            "daybook_operations_runtime_confirmed": True,
            "daybook_operations_runtime_user": getpass.getuser(),
            "daybook_operations_runtime_owner": "user",
            "daybook_operations_runtime_mode": "host",
            "daybook_operations_runtime_install_root": str(self.install),
            "daybook_operations_runtime_python": str(self.bin / "python"),
            "daybook_operations_runtime_plist": str(self.plist),
            "daybook_operations_runtime_journal": str(self.state / "journal"),
            "daybook_operations_runtime_launchctl": str(self.bin / "launchctl"),
            "daybook_operations_runtime_pgrep": str(self.bin / "pgrep"),
            "daybook_operations_runtime_kill": str(self.bin / "kill"),
            "daybook_operations_runtime_host_tmux": str(self.bin / "tmux"),
            "daybook_operations_runtime_date": str(self.bin / "date"),
            "daybook_operations_runtime_stop_windows": [
                {"start": "07:15", "end": "08:45"}, {"start": "19:15", "end": "20:45"},
            ],
            "daybook_operations_runtime_stop_window_lead_minutes": 20,
            "daybook_operations_runtime_status_sources": ["regular", "weeknotes"],
            "daybook_operations_runtime_revision": self.revision,
            "daybook_operations_runtime_quiet_retries": 2,
            "daybook_operations_runtime_quiet_delay": 1,
            "daybook_operations_runtime_poll_delay": 1,
            "daybook_operations_runtime_stop_timeout": 2,
            "daybook_operations_runtime_verify_retries": 2,
            **variables,
        }
        play = [{
            "hosts": "localhost",
            "gather_facts": False,
            "vars": values,
            "tasks": [{
                "name": "Run the role's action",
                "ansible.builtin.include_role": {"name": ROLE, "tasks_from": action},
            }, {
                "name": "Reached the end",
                "ansible.builtin.debug": {"msg": "ROLE_FINISHED"},
            }],
        }]
        playbook = self.base / "play.yml"
        playbook.write_text(yaml.safe_dump(play, sort_keys=False))
        env = {k: v for k, v in os.environ.items() if not k.startswith(("ANSIBLE_", "STUB_"))}
        env.update(
            STATE=str(self.state),
            STUB_SOURCES=sources,
            ANSIBLE_ROLES_PATH=str(ROOT / "roles"),
            ANSIBLE_NOCOLOR="1",
            ANSIBLE_LOCAL_TEMP=str(self.base / "ansible-tmp"),
            ANSIBLE_HOME=str(self.base / "ansible-home"),
        )
        env.update(self.stub_env)
        result = subprocess.run(
            ["ansible-playbook", "-i", "localhost,", str(playbook)],
            env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180,
            cwd=self.base,
        )
        return result, result.stdout + result.stderr

    stub_env: dict = {}

    def calls(self):
        path = self.state / "calls"
        return path.read_text().splitlines() if path.exists() else []

    def mutations(self):
        return [c for c in self.calls()
                if c.startswith("kill") or any(v in c for v in (" bootout ", " bootstrap ", " enable ",
                                                                  " disable "))]

    def assertFinished(self, result, output):
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("ROLE_FINISHED", output)

    def assertRefusedUntouched(self, result, output, reason):
        self.assertNotEqual(result.returncode, 0, output)
        self.assertNotIn("ROLE_FINISHED", output)
        self.assertIn(reason, output)
        self.assertEqual(self.mutations(), [])
        self.assertTrue((self.state / "loaded").exists())
        self.assertTrue((self.state / "serve").exists())

    # -- stop ---------------------------------------------------------------

    def test_a_quiet_supervisor_is_booted_out_then_sent_sigterm(self):
        self.running()
        result, output = self.run_role()
        self.assertFinished(result, output)
        mutations = self.mutations()
        self.assertEqual(len(mutations), 2, mutations)
        self.assertRegex(mutations[0], r"^launchctl bootout gui/\d+/de\.wersdoerfer\.daybook\.voice-memo-inbox$")
        self.assertEqual(mutations[1], "kill -TERM 4242")
        for name in ("loaded", "serve", "session"):
            self.assertFalse((self.state / name).exists(), name)
        # Never the host, never SIGKILL, never a tmux kill.
        self.assertTrue((self.state / "host").exists())
        for call in self.calls():
            tokens = call.split()
            self.assertFalse({"kill-session", "kill-server", "-KILL", "-9", "-SIGKILL"} & set(tokens), call)
        # The host is looked up under the user's socket directory.
        self.assertIn(
            f"tmux -L daybook-host has-session -t =host TMUX_TMPDIR=/private/tmp", self.calls()
        )
        # Every named source was asked.
        asked = [c for c in self.calls() if c.startswith("python")]
        self.assertTrue(any(c.endswith("--binding regular") for c in asked))
        self.assertTrue(any(c.endswith("--binding weeknotes") for c in asked))

    def test_an_already_stopped_supervisor_is_left_alone_even_inside_a_window(self):
        (self.state / "host").touch()
        (self.state / "clock").write_text("07:30\n")
        result, output = self.run_role()
        self.assertFinished(result, output)
        self.assertEqual(self.mutations(), [])

    def test_near_or_inside_a_run_window_a_running_supervisor_is_refused(self):
        for clock, refused in (("06:54", False), ("06:55", True), ("08:44", True),
                               ("08:45", False), ("18:55", True), ("20:45", False)):
            with self.subTest(clock=clock):
                (self.state / "calls").unlink(missing_ok=True)
                self.running()
                (self.state / "clock").write_text(clock + "\n")
                result, output = self.run_role()
                if refused:
                    self.assertRefusedUntouched(result, output, f"it is {clock} Europe/Berlin")
                else:
                    self.assertFinished(result, output)
                dates = [c for c in self.calls() if c.startswith("date")]
                self.assertTrue(dates and all(c == "date +%H:%M TZ=Europe/Berlin" for c in dates), dates)

    def test_the_window_is_checked_again_right_before_the_bootout(self):
        """The quiet waits can run into a window: the second look refuses."""
        self.running()
        (self.state / "clock").write_text("06:54\n06:56\n")
        result, output = self.run_role()
        self.assertRefusedUntouched(result, output, "it is 06:56 Europe/Berlin")

    def test_without_windows_the_role_default_stops_and_reads_no_clock(self):
        self.running()
        result, output = self.run_role(daybook_operations_runtime_stop_windows=[])
        self.assertFinished(result, output)
        self.assertFalse([c for c in self.calls() if c.startswith("date")])
        self.assertIn("kill -TERM 4242", self.mutations())

    def test_a_window_across_midnight_is_refused(self):
        for windows in ([{"start": "00:10", "end": "00:45"}],
                        [{"start": "23:00", "end": "01:00"}],
                        [{"start": "7:15", "end": "08:45"}]):
            with self.subTest(windows=windows):
                self.running()
                (self.state / "clock").write_text("23:55\n")
                result, output = self.run_role(daybook_operations_runtime_stop_windows=windows)
                self.assertRefusedUntouched(result, output, "must lie within one day")

    def test_an_unreadable_clock_is_refused(self):
        self.running()
        (self.state / "clock").write_text("7:5\n")
        result, output = self.run_role()
        self.assertRefusedUntouched(result, output, "the clock did not answer HH:MM")

    def test_a_loaded_label_that_does_not_run_the_keeper_is_refused(self):
        self.running()
        self.stub_env = {"STUB_LABEL_COMMAND": "serve"}
        try:
            result, output = self.run_role()
        finally:
            self.stub_env = {}
        self.assertRefusedUntouched(result, output, "does not run `operations host-keep`")

    def test_no_gui_session_is_refused(self):
        self.running()
        self.stub_env = {"STUB_DOMAIN_RC": "113"}
        try:
            result, output = self.run_role()
        finally:
            self.stub_env = {}
        self.assertRefusedUntouched(result, output, "has no Aqua session")

    def test_a_missing_capability_host_is_refused(self):
        self.running()
        (self.state / "host").unlink()
        result, output = self.run_role()
        self.assertRefusedUntouched(result, output, "capability host")

    def test_a_stop_marker_is_refused(self):
        self.running()
        (self.state / "journal" / "halts" / "regular.json").write_text("{}")
        result, output = self.run_role()
        self.assertRefusedUntouched(result, output, "stop marker")

    def test_a_record_in_the_store_is_waited_for_then_refused(self):
        self.running()
        (self.state / "journal" / "deliveries" / "op.json").write_text("{}")
        result, output = self.run_role()
        self.assertRefusedUntouched(result, output, "Still busy: 1 delivery record")
        # Waited: the store was looked at more than once.
        self.assertIn("FAILED - RETRYING", output)

    def test_an_operation_in_flight_is_refused(self):
        self.running()
        result, output = self.run_role(sources="regular=-,weeknotes=assigned")
        self.assertRefusedUntouched(result, output, "weeknotes: operation in flight")

    def test_an_unanswered_source_is_refused(self):
        self.running()
        result, output = self.run_role(sources="regular=-")
        self.assertRefusedUntouched(result, output, "weeknotes: no status")

    def test_a_supervisor_that_does_not_exit_gets_its_keeper_back(self):
        self.running()
        self.stub_env = {"STUB_IGNORES_TERM": "1"}
        try:
            result, output = self.run_role()
        finally:
            self.stub_env = {}
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn("The keeper is loaded again on the unchanged code", output)
        mutations = self.mutations()
        self.assertTrue(mutations[0].startswith("launchctl bootout"))
        self.assertEqual(mutations[1], "kill -TERM 4242")
        self.assertTrue(mutations[-1].startswith("launchctl bootstrap"), mutations)
        self.assertTrue((self.state / "loaded").exists())

    def test_a_record_left_behind_gets_the_keeper_back(self):
        self.running()
        self.stub_env = {"STUB_LEAVES_RECORD": "1"}
        try:
            result, output = self.run_role()
        finally:
            self.stub_env = {}
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn("The keeper is loaded again", output)
        self.assertTrue((self.state / "loaded").exists())

    def test_a_label_holding_something_else_is_not_booted_back_in(self):
        self.running()
        self.plist.write_text("<plist><string>voice-memos</string></plist>")
        self.stub_env = {"STUB_IGNORES_TERM": "1"}
        try:
            result, output = self.run_role()
        finally:
            self.stub_env = {}
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn("could NOT be loaded again", output)
        self.assertFalse([c for c in self.calls() if " bootstrap " in c or " enable " in c])

    def test_preflight_reports_and_touches_nothing(self):
        self.running()
        result, output = self.run_role(daybook_operations_runtime_stop_preflight=True)
        self.assertFinished(result, output)
        self.assertIn("Supervisor running: True", output)
        self.assertEqual(self.mutations(), [])

    def test_preflight_reports_a_busy_machine_as_a_refusal_without_waiting(self):
        self.running()
        (self.state / "journal" / "deliveries" / "op.json").write_text("{}")
        result, output = self.run_role(daybook_operations_runtime_stop_preflight=True)
        self.assertRefusedUntouched(result, output, "Still busy")
        self.assertNotIn("FAILED - RETRYING", output)

    def test_serve_mode_is_refused(self):
        self.running()
        result, output = self.run_role(daybook_operations_runtime_mode="serve")
        self.assertRefusedUntouched(result, output, "mode `host`")

    # -- verify -------------------------------------------------------------

    def test_verify_passes_a_running_supervisor_on_the_expected_code(self):
        self.running()
        result, output = self.run_role(action="verify")
        self.assertFinished(result, output)
        self.assertEqual(self.mutations(), [])

    def test_verify_refuses_other_code(self):
        self.running()
        result, output = self.run_role(action="verify", daybook_operations_runtime_revision="0" * 40)
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn("not verified healthy", output)

    def test_verify_refuses_a_stopped_supervisor(self):
        (self.state / "loaded").touch()
        result, output = self.run_role(action="verify")
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn("not verified healthy", output)

    def test_verify_names_an_unanswered_source(self):
        self.running()
        result, output = self.run_role(action="verify", sources="regular=-")
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn("Unhealthy sources: ['weeknotes']", output)

    def test_verify_refuses_a_stop_marker(self):
        self.running()
        (self.state / "journal" / "halts" / "regular.json").write_text("{}")
        result, output = self.run_role(action="verify")
        self.assertNotEqual(result.returncode, 0, output)


class RuntimeStopWiringTests(unittest.TestCase):
    def tasks(self, name):
        return yaml.safe_load((ROOT / "roles" / ROLE / "tasks" / name).read_text())

    def test_stop_and_verify_end_the_role_before_any_code_or_profile_changes(self):
        names = [t["name"] for t in self.tasks("main.yml")]
        end = names.index("Stop after stopping or verifying")
        self.assertLess(names.index("Stop the hosted supervisor"), end)
        self.assertLess(names.index("Verify the running supervisor"), end)
        self.assertLess(end, names.index("Install the pinned code where no other role does"))
        self.assertLess(end, names.index("Write disabled-first local policy"))

    def test_stop_signals_only_with_sigterm(self):
        def commands(tasks):
            for task in tasks:
                yield from commands(task.get("block", []) + task.get("rescue", []))
                if "ansible.builtin.command" in task:
                    yield task["name"], str(task["ansible.builtin.command"]["argv"])

        found = dict(commands(self.tasks("stop.yml")))
        self.assertIn("'-TERM'", found["stop | Ask the supervisor to stop"])
        for name, argv in found.items():
            for forbidden in ("-KILL", "'-9'", "kill-session", "kill-server", "pkill", "disable", "kickstart"):
                self.assertNotIn(forbidden, argv, name)

    def test_verify_changes_nothing(self):
        for task in self.tasks("verify.yml"):
            argv = task.get("ansible.builtin.command", {}).get("argv", [])
            self.assertFalse({"bootout", "bootstrap", "enable", "disable", "kickstart"} & set(argv), task["name"])
            self.assertNotIn("ansible.builtin.file", task)
            self.assertNotIn("ansible.builtin.copy", task)
            self.assertNotIn("ansible.builtin.template", task)


if __name__ == "__main__":
    unittest.main()
