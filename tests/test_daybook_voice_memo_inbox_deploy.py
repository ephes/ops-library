import copy
import os
import plistlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment


ROOT = Path(__file__).resolve().parents[1]
ROLE = "roles/daybook_voice_memo_inbox_deploy"
SHORT_LABEL = "de.wersdoerfer.daybook.voice-memo-inbox"
LONG_LABEL = "de.wersdoerfer.daybook.voice-memo-inbox-long"
ACTIVATION_BLOCK = "Activate Voice Memo inbox after explicit historical baseline"


class DaybookVoiceMemoInboxRoleTests(unittest.TestCase):
    def text(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def role_variables(self) -> dict:
        """Resolve the role defaults far enough to render its plists."""
        variables = yaml.safe_load(self.text(f"{ROLE}/defaults/main.yml"))
        variables["daybook_voice_memo_inbox_service_user"] = "example"
        env = Environment()
        for _ in range(8):
            for key, value in list(variables.items()):
                if isinstance(value, str) and "{{" in value:
                    variables[key] = env.from_string(value).render(**variables)
        return variables

    def render_plist(self, template: str) -> dict:
        rendered = (
            Environment(keep_trailing_newline=True)
            .from_string(self.text(f"{ROLE}/templates/{template}"))
            .render(**self.role_variables())
        )
        return plistlib.loads(rendered.encode("utf-8"))

    def test_defaults_are_disabled_and_secret_free(self):
        defaults = self.text("roles/daybook_voice_memo_inbox_deploy/defaults/main.yml")
        self.assertIn("daybook_voice_memo_inbox_enabled: false", defaults)
        self.assertIn("daybook_voice_memo_inbox_launchd_enabled: false", defaults)
        self.assertIn('daybook_voice_memo_inbox_voxhelm_token: "CHANGEME"', defaults)
        self.assertIn(
            'daybook_voice_memo_inbox_s3_secret_access_key: "CHANGEME"',
            defaults,
        )
        self.assertNotIn("Bearer ", defaults)

    def test_schedule_and_program_arguments_are_fixed(self):
        defaults = self.text("roles/daybook_voice_memo_inbox_deploy/defaults/main.yml")
        plist = self.text(
            "roles/daybook_voice_memo_inbox_deploy/templates/voice-memo-inbox.launchd.plist.j2"
        )
        self.assertIn("daybook_voice_memo_inbox_interval_seconds: 300", defaults)
        self.assertIn(
            "daybook_voice_memo_inbox_activation_status_retries: 72", defaults
        )
        self.assertIn(
            "daybook_voice_memo_inbox_activation_status_delay_seconds: 5", defaults
        )
        self.assertIn("<key>RunAtLoad</key>\n  <true/>", plist)
        self.assertIn("<key>StartInterval</key>", plist)
        self.assertIn("voice-memos", plist)
        self.assertIn("ingest", plist)
        self.assertIn("--summary-only", plist)
        self.assertIn("<string>-I</string>", plist)
        self.assertIn("<string>-c</string>", plist)
        self.assertIn(
            "<string>from daybook.cli import main; raise SystemExit(main())</string>",
            plist,
        )
        self.assertNotIn("<string>-m</string>", plist)
        self.assertIn("<key>WorkingDirectory</key>", plist)
        for forbidden in ("token", "secret", "access_key"):
            self.assertNotIn(forbidden, plist.lower())

    def test_role_quiesces_before_install_and_activation_is_gated(self):
        tasks = self.text("roles/daybook_voice_memo_inbox_deploy/tasks/main.yml")
        disable = tasks.index("Disable Voice Memo inbox before deployment")
        quiesced = tasks.index(
            "Verify Voice Memo inbox is quiesced before managed changes"
        )
        bundle = tasks.index("Install exact Daybook source bundle")
        self.assertLess(disable, bundle)
        self.assertLess(quiesced, bundle)
        self.assertIn(
            "Prove Voice Memo inbox is quiesced before managed changes", tasks
        )
        self.assertIn("daybook_voice_memo_inbox_quiesced.rc | int != 0", tasks)
        self.assertIn("until: daybook_voice_memo_inbox_quiesced.rc != 0", tasks)
        self.assertIn("until: daybook_voice_memo_inbox_rescue_probe.rc != 0", tasks)
        rescue_probe = tasks[
            tasks.index("Probe Voice Memo inbox label after rescue") : tasks.index(
                "Require proven disabled/unloaded state after activation failure"
            )
        ]
        self.assertIn("ignore_errors: true", rescue_probe)
        protect = tasks[
            tasks.index("- name: Protect Voice Memo inbox interpreter\n") + 1 :
        ]
        protect = protect[: protect.index("\n- name:")]
        self.assertIn("follow: false", protect)
        self.assertIn(
            "Require active Voice Memo owner Aqua domain for deployment", tasks
        )
        self.assertIn("Prove Voice Memo inbox label is disabled", tasks)
        self.assertIn("print-disabled", tasks)
        self.assertIn(
            "daybook_voice_memo_inbox_activation_confirmation == "
            "daybook_voice_memo_inbox_activation_phrase",
            tasks,
        )
        self.assertIn(
            "Initialize Voice Memo historical baseline in Aqua context", tasks
        )
        self.assertIn("Install root-owned Voice Memo activation marker", tasks)
        self.assertIn("Capture Voice Memo ledger generation before bootstrap", tasks)
        self.assertIn(
            "generation | int > daybook_voice_memo_inbox_prebootstrap_report.generation | int",
            tasks,
        )
        self.assertLess(
            tasks.index("Install root-owned Voice Memo activation marker"),
            tasks.index("Capture Voice Memo ledger generation before bootstrap"),
        )
        self.assertLess(
            tasks.index("Capture Voice Memo ledger generation before bootstrap"),
            tasks.index("Bootstrap Voice Memo inbox LaunchAgent"),
        )
        self.assertIn("Rescue-disable Voice Memo inbox label", tasks)
        self.assertIn("Rescue-bootout Voice Memo inbox label", tasks)
        self.assertIn(
            "historical_count | int == "
            "daybook_voice_memo_inbox_prebootstrap_report.historical_count | int",
            tasks,
        )
        self.assertIn(
            "daybook_voice_memo_inbox_activation_phrase == "
            "'BASELINE ALL CURRENT VOICE MEMOS AS HISTORICAL'",
            tasks,
        )
        self.assertIn("Install root-owned proven first Voice Memo scan marker", tasks)
        self.assertIn("Reject inconsistent Voice Memo activation markers", tasks)
        self.assertLess(
            tasks.index("Wait for privacy-safe first Voice Memo scan"),
            tasks.index("Install root-owned proven first Voice Memo scan marker"),
        )
        proof_start = tasks.index(
            "Install root-owned proven first Voice Memo scan marker"
        )
        proof_end = tasks.index("Rescue-disable Voice Memo inbox label")
        proof_block = tasks[proof_start:proof_end]
        self.assertIn("owner: root", proof_block)
        self.assertIn('mode: "0644"', proof_block)
        self.assertIn(
            "when: not daybook_voice_memo_inbox_activation_proof.stat.exists",
            proof_block,
        )

    def test_scheduled_interpreter_is_regular_and_protected(self):
        tasks = self.text("roles/daybook_voice_memo_inbox_deploy/tasks/main.yml")
        self.assertIn(
            "Copy pinned Voice Memo inbox interpreter into protected checkout", tasks
        )
        self.assertIn("- -L", tasks)
        self.assertNotIn("- -pL", tasks)
        copy = tasks.index(
            "Copy pinned Voice Memo inbox interpreter into protected checkout"
        )
        protect_staged = tasks.index(
            "Protect staged Voice Memo inbox interpreter before it becomes live"
        )
        install = tasks.index("Install regular Voice Memo inbox interpreter atomically")
        self.assertLess(copy, protect_staged)
        self.assertLess(protect_staged, install)
        staged = tasks[protect_staged:install]
        self.assertIn("owner: root", staged)
        self.assertIn('mode: "0755"', staged)
        self.assertIn(
            "daybook_voice_memo_inbox_python_needs_copy | bool", tasks[copy:install]
        )
        self.assertIn(
            "daybook_voice_memo_inbox_protected_python.stat.checksum == daybook_voice_memo_inbox_python_source_checksum",
            tasks,
        )
        self.assertNotIn("stat.checksum | length == 40", tasks)
        self.assertIn(
            "selectattr('item', 'eq', daybook_voice_memo_inbox_python_source)", tasks
        )
        self.assertIn("Require protected Voice Memo inbox interpreter boundary", tasks)
        self.assertIn("not daybook_voice_memo_inbox_protected_python.stat.islnk", tasks)
        self.assertIn(
            "daybook_voice_memo_inbox_protected_python.stat.nlink == 1", tasks
        )
        self.assertIn(
            "daybook_voice_memo_inbox_protected_python.stat.pw_name == 'root'", tasks
        )
        self.assertIn(
            "daybook_voice_memo_inbox_protected_python.stat.mode == '0755'", tasks
        )
        self.assertIn(
            "Smoke-test protected Voice Memo inbox interpreter as service user", tasks
        )
        self.assertIn(
            "Smoke-test protected Voice Memo inbox CLI entrypoint as service user",
            tasks,
        )
        self.assertIn("- --help", tasks)
        self.assertIn("daybook_voice_memo_inbox_python_source", tasks)
        self.assertEqual(
            tasks.count("- from daybook.cli import main; raise SystemExit(main())"),
            6,
        )
        activation = tasks.split(
            "- name: Initialize Voice Memo historical baseline in Aqua context", 1
        )[1]
        self.assertGreaterEqual(
            activation.count('chdir: "{{ daybook_voice_memo_inbox_checkout_path }}"'),
            3,
        )

    def test_protected_checkout_must_be_clean_before_runtime_sync(self):
        tasks = self.text("roles/daybook_voice_memo_inbox_deploy/tasks/main.yml")
        checkout = tasks.index("Check out exact reviewed Daybook commit")
        inspect = tasks.index("Inspect protected Daybook checkout cleanliness")
        require = tasks.index("Require an unmodified protected Daybook checkout")
        sync = tasks.index("Synchronize locked Daybook runtime")
        self.assertLess(checkout, inspect)
        self.assertLess(inspect, require)
        self.assertLess(require, sync)
        inspect_block = tasks[inspect:require]
        self.assertIn("- --porcelain", inspect_block)
        self.assertIn("- --untracked-files=all", inspect_block)
        self.assertIn("GIT_CONFIG_GLOBAL: /dev/null", inspect_block)
        require_block = tasks[require:sync]
        self.assertIn(
            "daybook_voice_memo_inbox_checkout_status.stdout | trim | length == 0",
            require_block,
        )
        self.assertIn("paths withheld", require_block)
        readme = self.text("roles/daybook_voice_memo_inbox_deploy/README.md")
        self.assertIn(
            "does not disable, unload, or remove an existing installation", readme
        )

    def test_activation_rescue_proves_disabled_and_unloaded(self):
        tasks = self.text("roles/daybook_voice_memo_inbox_deploy/tasks/main.yml")
        rescue = tasks[tasks.index("  rescue:") :]
        order = [
            "Rescue-disable Voice Memo inbox label",
            "Rescue-bootout Voice Memo inbox label",
            "Re-read disabled Voice Memo inbox labels after rescue",
            "Probe Voice Memo inbox label after rescue",
            "Require proven disabled/unloaded state after activation failure",
            "Fail closed after Voice Memo inbox activation error",
        ]
        positions = [rescue.index(name) for name in order]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("register: daybook_voice_memo_inbox_rescue_disable", rescue)
        self.assertIn("register: daybook_voice_memo_inbox_rescue_bootout", rescue)
        proof = rescue[positions[4] : positions[5]]
        self.assertIn("daybook_voice_memo_inbox_rescue_disabled_labels.rc == 0", proof)
        self.assertIn("regex_search(", proof)
        self.assertIn("(?:true|disabled)", proof)
        self.assertIn("daybook_voice_memo_inbox_rescue_probe.rc != 0", proof)
        self.assertIn("COULD NOT PROVE", proof)
        self.assertIn("emergency disable", proof)
        final = rescue[positions[5] :]
        self.assertIn("proven", final)
        self.assertIn(
            "disable rc={{ daybook_voice_memo_inbox_rescue_disable.rc }}", final
        )

    def test_checkout_replacement_fails_closed_when_git_cannot_read_revision(self):
        tasks = self.text("roles/daybook_voice_memo_inbox_deploy/tasks/main.yml")
        executables = tasks[
            tasks.index("Inspect required Voice Memo inbox executables") : tasks.index(
                "Require executable Voice Memo inbox prerequisites"
            )
        ]
        self.assertIn("    - /usr/bin/git\n", executables)
        bundle_install = tasks.index("Install exact Daybook source bundle")
        verify = tasks.index(
            "Verify installed Daybook source bundle against the existing checkout"
        )
        heads = tasks.index("List installed Daybook source bundle heads")
        require_bundle = tasks.index(
            "Require a valid Daybook bundle containing the pinned commit"
        )
        inspect = tasks.index("Inspect existing managed Daybook checkout")
        refuse = tasks.index(
            "Refuse to replace an existing checkout whose revision cannot be read"
        )
        replace = tasks.index("Replace drifted managed Daybook checkout")
        self.assertLess(bundle_install, inspect)
        self.assertLess(inspect, verify)
        verify_block = tasks[verify:heads]
        self.assertIn(
            'chdir: "{{ daybook_voice_memo_inbox_checkout_path }}"', verify_block
        )
        self.assertIn(
            "- daybook_voice_memo_inbox_checkout_dir.stat.exists", verify_block
        )
        self.assertLess(verify, heads)
        self.assertLess(heads, require_bundle)
        self.assertLess(require_bundle, replace)
        bundle_block = tasks[require_bundle:refuse]
        self.assertIn(
            "not daybook_voice_memo_inbox_checkout_dir.stat.exists or daybook_voice_memo_inbox_bundle_verify.rc == 0",
            bundle_block,
        )
        self.assertIn("daybook_voice_memo_inbox_bundle_heads.rc == 0", bundle_block)
        self.assertIn("daybook_voice_memo_inbox_repo_ref ~ ' '", bundle_block)
        self.assertIn("checkout is left untouched", bundle_block)
        self.assertLess(require_bundle, refuse)
        self.assertLess(refuse, replace)
        refuse_block = tasks[refuse:replace]
        self.assertIn(
            "not daybook_voice_memo_inbox_checkout_dir.stat.exists or daybook_voice_memo_inbox_installed_ref.rc == 0",
            refuse_block,
        )
        replace_block = tasks[replace : tasks.index("Clone exact Daybook bundle")]
        self.assertIn(
            "- daybook_voice_memo_inbox_checkout_dir.stat.exists", replace_block
        )
        self.assertNotIn("installed_ref.rc != 0", replace_block)
        self.assertIn(
            "- daybook_voice_memo_inbox_installed_ref.stdout | trim != daybook_voice_memo_inbox_repo_ref\n",
            replace_block,
        )
        self.assertNotIn("daybook_voice_memo_inbox_bundle.changed", replace_block)

    def test_fresh_host_check_mode_guards_are_keyed_by_path(self):
        tasks = self.text("roles/daybook_voice_memo_inbox_deploy/tasks/main.yml")
        self.assertNotIn("managed_parents.results[", tasks)
        index = tasks[
            tasks.index("Index Voice Memo inbox managed parent directories by path") :
        ]
        index = index[
            : index.index("- name: Create protected Voice Memo inbox directories")
        ]
        self.assertIn("map(attribute='item')", index)
        self.assertIn("map(attribute='stat.exists')", index)
        for task_name, key in (
            (
                "Create owner-only Voice Memo inbox logs",
                "daybook_voice_memo_inbox_log_dir",
            ),
            (
                "Install exact Daybook source bundle",
                "daybook_voice_memo_inbox_install_root",
            ),
            (
                "Render protected Voice Memo inbox policy",
                "daybook_voice_memo_inbox_install_root",
            ),
            (
                "Render owner-only Voice Memo inbox credentials",
                "daybook_voice_memo_inbox_credential_dir",
            ),
            (
                "Render disabled-first Voice Memo inbox LaunchAgent",
                "daybook_voice_memo_inbox_service_home ~ '/Library/LaunchAgents'",
            ),
        ):
            body = tasks[tasks.index(f"- name: {task_name}") + 1 :]
            body = body[: body.index("\n- name:")]
            self.assertIn(
                f"not ansible_check_mode or daybook_voice_memo_inbox_parent_exists[{key}]",
                body,
                task_name,
            )
        protect = tasks[
            tasks.index("- name: Protect Voice Memo inbox interpreter") + 1 :
        ]
        protect = protect[: protect.index("\n- name:")]
        self.assertIn(
            "not ansible_check_mode or daybook_voice_memo_inbox_python_stat.stat.exists",
            protect,
        )
        loop = tasks[
            tasks.index(
                "Inspect Voice Memo inbox managed parent directories"
            ) : tasks.index("Index Voice Memo inbox managed parent directories by path")
        ]
        for path in (
            "daybook_voice_memo_inbox_install_root",
            "daybook_voice_memo_inbox_log_dir",
            "daybook_voice_memo_inbox_credential_dir",
            "daybook_voice_memo_inbox_service_home }}/Library/LaunchAgents",
        ):
            self.assertIn(path, loop)

    def test_required_values_reject_empty_strings(self):
        tasks = self.text("roles/daybook_voice_memo_inbox_deploy/tasks/main.yml")
        validation = tasks[: tasks.index("Resolve Voice Memo inbox service uid")]
        for variable in (
            "daybook_voice_memo_inbox_bucket",
            "daybook_voice_memo_inbox_s3_access_key_id",
            "daybook_voice_memo_inbox_s3_secret_access_key",
            "daybook_voice_memo_inbox_voxhelm_token",
        ):
            self.assertIn(f"- {variable} != 'CHANGEME'", validation, variable)
            self.assertIn(f"- {variable} | string | length > 0", validation, variable)
        self.assertIn(
            "daybook_voice_memo_inbox_s3_endpoint_url | string is match('^https?://",
            validation,
        )

    def test_fresh_check_mode_does_not_enter_an_uncreated_checkout(self):
        tasks = self.text("roles/daybook_voice_memo_inbox_deploy/tasks/main.yml")
        sync_task = tasks.split("- name: Synchronize locked Daybook runtime", 1)[
            1
        ].split("- name: Inspect Voice Memo inbox virtualenv interpreter", 1)[0]
        self.assertIn("not ansible_check_mode", sync_task)
        self.assertIn("daybook_voice_memo_inbox_installed_ref.rc == 0", sync_task)
        self.assertIn(
            "daybook_voice_memo_inbox_installed_ref.stdout | trim == "
            "daybook_voice_memo_inbox_repo_ref",
            sync_task,
        )

    def test_launch_agent_is_scoped_to_voice_memos_owner(self):
        defaults = self.text("roles/daybook_voice_memo_inbox_deploy/defaults/main.yml")
        tasks = self.text("roles/daybook_voice_memo_inbox_deploy/tasks/main.yml")
        self.assertIn(
            "daybook_voice_memo_inbox_service_home }}/Library/LaunchAgents/",
            defaults,
        )
        self.assertNotIn(
            'daybook_voice_memo_inbox_plist_path: "/Library/LaunchAgents/', defaults
        )
        self.assertIn("daybook_voice_memo_inbox_plist_path ==", tasks)

    def test_credentials_are_owner_only_and_hidden(self):
        tasks = self.text("roles/daybook_voice_memo_inbox_deploy/tasks/main.yml")
        start = tasks.index("Render owner-only Voice Memo inbox credentials")
        end = tasks.index("Render disabled-first Voice Memo inbox LaunchAgent")
        block = tasks[start:end]
        self.assertIn('mode: "0600"', block)
        self.assertIn("no_log: true", block)
        policy = self.text(
            "roles/daybook_voice_memo_inbox_deploy/templates/policy.json.j2"
        )
        self.assertNotIn("voxhelm_token", policy)
        self.assertNotIn("secret_access_key", policy)

    def test_policy_pins_readiness_and_inbox_prefix(self):
        policy = self.text(
            "roles/daybook_voice_memo_inbox_deploy/templates/policy.json.j2"
        )
        defaults = self.text("roles/daybook_voice_memo_inbox_deploy/defaults/main.yml")
        self.assertIn('daybook_voice_memo_inbox_prefix: "Inbox/Voice Memos"', defaults)
        self.assertIn("min_stable_seconds", policy)
        self.assertIn("duration_tolerance_seconds", policy)
        self.assertIn("max_audio_bytes", policy)
        self.assertIn("max_duration_seconds", policy)
        self.assertIn("ffprobe_path", policy)
        self.assertIn("ffmpeg_path", policy)

    def test_long_lane_defaults_are_disabled_and_pinned(self):
        defaults = self.text(f"{ROLE}/defaults/main.yml")
        self.assertIn("daybook_voice_memo_inbox_long_lane_enabled: false", defaults)
        self.assertIn(
            f"daybook_voice_memo_inbox_long_launchd_label: {LONG_LABEL}", defaults
        )
        self.assertIn("daybook_voice_memo_inbox_long_interval_seconds: 600", defaults)
        for line in (
            "daybook_voice_memo_inbox_long_max_duration_seconds: 2400",
            "daybook_voice_memo_inbox_long_max_audio_bytes: 25165824",
            "daybook_voice_memo_inbox_long_realtime_factor: 0.08",
            "daybook_voice_memo_inbox_long_queue_slack_seconds: 600",
            "daybook_voice_memo_inbox_long_validation_timeout_seconds: 60",
            "daybook_voice_memo_inbox_long_max_attempts: 5",
            "daybook_voice_memo_inbox_long_queue_per_run: 2",
            "daybook_voice_memo_inbox_long_min_gap_seconds: 480",
        ):
            self.assertIn(line, defaults, line)
        variables = self.role_variables()
        self.assertEqual(
            variables["daybook_voice_memo_inbox_long_plist_path"],
            f"/Users/example/Library/LaunchAgents/{LONG_LABEL}.plist",
        )
        self.assertTrue(
            variables["daybook_voice_memo_inbox_long_stdout_log"].endswith(
                "/logs/ingest-long.log"
            )
        )
        self.assertTrue(
            variables["daybook_voice_memo_inbox_long_stderr_log"].endswith(
                "/logs/ingest-long.err.log"
            )
        )
        # 24 MiB stays below Voxhelm's 25 MiB sync upload limit and above the
        # short lane's ceiling.
        self.assertLess(
            variables["daybook_voice_memo_inbox_long_max_audio_bytes"], 25 * 1024 * 1024
        )
        self.assertGreaterEqual(
            variables["daybook_voice_memo_inbox_long_max_audio_bytes"],
            variables["daybook_voice_memo_inbox_max_audio_bytes"],
        )

    def test_both_launch_agents_render_exactly_one_lane_each(self):
        short = self.render_plist("voice-memo-inbox.launchd.plist.j2")
        long_lane = self.render_plist("voice-memo-inbox-long.launchd.plist.j2")
        self.assertEqual(short["Label"], SHORT_LABEL)
        self.assertEqual(long_lane["Label"], LONG_LABEL)
        self.assertEqual(
            short["ProgramArguments"][:5], long_lane["ProgramArguments"][:5]
        )
        self.assertEqual(short["ProgramArguments"][5:], ["ingest", "--summary-only"])
        self.assertEqual(
            long_lane["ProgramArguments"][5:], ["transcribe-long", "--summary-only"]
        )
        self.assertEqual(short["StartInterval"], 300)
        self.assertEqual(long_lane["StartInterval"], 600)
        self.assertIs(short["RunAtLoad"], True)
        self.assertIs(long_lane["RunAtLoad"], False)
        self.assertEqual(
            short["EnvironmentVariables"], long_lane["EnvironmentVariables"]
        )
        self.assertEqual(short["WorkingDirectory"], long_lane["WorkingDirectory"])
        self.assertTrue(long_lane["StandardOutPath"].endswith("/logs/ingest-long.log"))
        self.assertTrue(
            long_lane["StandardErrorPath"].endswith("/logs/ingest-long.err.log")
        )
        differing = {
            key
            for key in set(short) | set(long_lane)
            if short.get(key) != long_lane.get(key)
        }
        self.assertEqual(
            differing,
            {
                "Label",
                "ProgramArguments",
                "StartInterval",
                "RunAtLoad",
                "StandardOutPath",
                "StandardErrorPath",
            },
        )
        template = self.text(f"{ROLE}/templates/voice-memo-inbox-long.launchd.plist.j2")
        for forbidden in ("token", "secret", "access_key"):
            self.assertNotIn(forbidden, template.lower())

    def test_quiesce_and_prove_cover_both_labels(self):
        tasks = self.text(f"{ROLE}/tasks/main.yml")
        order = [
            "Disable Voice Memo inbox before deployment",
            "Disable Voice Memo inbox long lane before deployment",
            "Read disabled Voice Memo inbox labels",
            "Boot out Voice Memo inbox before deployment",
            "Boot out Voice Memo inbox long lane before deployment",
            "Prove Voice Memo inbox label is disabled",
            "Prove Voice Memo inbox long lane label is disabled",
            "Verify Voice Memo inbox is quiesced before managed changes",
            "Prove Voice Memo inbox is quiesced before managed changes",
            "Verify Voice Memo inbox long lane is quiesced before managed changes",
            "Prove Voice Memo inbox long lane is quiesced before managed changes",
            "Install exact Daybook source bundle",
        ]
        positions = [tasks.index(name) for name in order]
        self.assertEqual(positions, sorted(positions))
        prove_long = tasks[
            tasks.index(
                "Prove Voice Memo inbox long lane label is disabled"
            ) : tasks.index(
                "Verify Voice Memo inbox is quiesced before managed changes"
            )
        ]
        self.assertIn(
            "daybook_voice_memo_inbox_long_launchd_label | regex_escape", prove_long
        )
        self.assertIn("(?:true|disabled)", prove_long)
        bootout_long = tasks[
            tasks.index(
                "Boot out Voice Memo inbox long lane before deployment"
            ) : tasks.index("Prove Voice Memo inbox label is disabled")
        ]
        self.assertIn("failed_when: false", bootout_long)
        quiesced_long = tasks[
            tasks.index(
                "Verify Voice Memo inbox long lane is quiesced before managed changes"
            ) : tasks.index("Inspect Voice Memo inbox managed parent directories")
        ]
        self.assertIn(
            "until: daybook_voice_memo_inbox_long_quiesced.rc != 0", quiesced_long
        )
        # The raw launchctl print output of a still-loaded job is never shown;
        # the proof is a sanitized assertion on the exit status instead.
        self.assertIn("no_log: true", quiesced_long)
        self.assertIn(
            "daybook_voice_memo_inbox_long_quiesced.rc | int != 0", quiesced_long
        )
        for lane in ("", " long lane"):
            probe = tasks[
                tasks.index(f"Probe Voice Memo inbox{lane} label after rescue") :
            ]
            probe = probe[: probe.index("\n    - name:")]
            self.assertIn("no_log: true", probe)

    def test_pre_quiesce_in_flight_log_never_waits_for_a_running_item(self):
        tasks = self.text(f"{ROLE}/tasks/main.yml")
        read_start = tasks.index(
            "Read Voice Memo inbox long lane in-flight count before quiesce"
        )
        extract_start = tasks.index(
            "Extract Voice Memo inbox long lane in-flight count before quiesce"
        )
        report_start = tasks.index(
            "Report Voice Memo inbox long lane in-flight count before quiesce"
        )
        disable = tasks.index("Disable Voice Memo inbox before deployment")
        self.assertLess(read_start, extract_start)
        self.assertLess(extract_start, report_start)
        self.assertLess(report_start, disable)
        read_block = tasks[read_start:extract_start]
        # Never blocks on the in-flight item: no retry loop, no wait condition,
        # and a failed read cannot fail the deployment.
        self.assertNotIn("retries:", read_block)
        self.assertNotIn("until:", read_block)
        self.assertIn("failed_when: false", read_block)
        self.assertIn("changed_when: false", read_block)
        self.assertIn("no_log: true", read_block)
        self.assertIn("- status", read_block)
        self.assertIn("- --summary-only", read_block)
        self.assertNotIn("transcribe-long", read_block)
        # Skipped on a fresh host where interpreter or policy do not exist yet.
        self.assertIn("daybook_voice_memo_inbox_prequiesce_runtime.results", read_block)
        self.assertIn("stat.exists", read_block)
        extract_block = tasks[extract_start:report_start]
        # The count is extracted best-effort with a regular expression: a
        # malformed status document must never abort the quiesce that follows.
        self.assertIn("ansible.builtin.set_fact", extract_block)
        self.assertNotIn("from_json", extract_block)
        self.assertIn("regex_search", extract_block)
        self.assertIn("ignore_errors: true", extract_block)
        report_block = tasks[
            report_start : tasks.index("Disable Voice Memo inbox before deployment")
        ]
        self.assertIn("items in flight before quiesce", report_block)
        self.assertIn("daybook_voice_memo_inbox_prequiesce_in_flight", report_block)
        self.assertIn("ansible.builtin.debug", report_block)
        self.assertNotIn("from_json", report_block)
        # Only a validated non-negative integer is ever reported.
        self.assertIn("is match('[0-9]+$')", report_block)
        for forbidden in ("source_id", "object_key", "signature", "path"):
            self.assertNotIn(forbidden, report_block)

    def test_long_lane_liveness_proof_accepts_only_specified_outcomes(self):
        tasks = self.text(f"{ROLE}/tasks/main.yml")
        order = [
            "Enable Voice Memo inbox exact label",
            "Bootstrap Voice Memo inbox LaunchAgent",
            "Enable Voice Memo inbox long lane exact label",
            "Bootstrap Voice Memo inbox long lane LaunchAgent",
            "Prove Voice Memo inbox long lane liveness without work",
            "Parse Voice Memo inbox long lane liveness proof",
            "Require a proven live Voice Memo inbox long lane",
            "Verify Voice Memo inbox long lane label is loaded",
            "Require a loaded Voice Memo inbox long lane label",
            "Report loaded Voice Memo inbox long lane label",
            "Wait for privacy-safe first Voice Memo scan",
            "Install root-owned proven first Voice Memo scan marker",
        ]
        positions = [tasks.index(name) for name in order]
        self.assertEqual(positions, sorted(positions))
        proof = tasks[
            tasks.index(
                "Prove Voice Memo inbox long lane liveness without work"
            ) : tasks.index("Verify Voice Memo inbox long lane label is loaded")
        ]
        self.assertIn("- transcribe-long", proof)
        self.assertIn("- --no-work", proof)
        self.assertIn("- --summary-only", proof)
        self.assertIn("launchctl", proof)
        self.assertIn("asuser", proof)
        self.assertIn("/usr/bin/sudo", proof)
        self.assertIn(
            "daybook_voice_memo_inbox_long_liveness.stdout | default('{}', true) | from_json",
            proof,
        )
        self.assertIn("daybook_voice_memo_inbox_long_liveness.rc == 0", proof)
        self.assertIn(
            "daybook_voice_memo_inbox_long_liveness_report.category == 'proof_only'",
            proof,
        )
        self.assertIn("daybook_voice_memo_inbox_long_liveness.rc == 75", proof)
        self.assertIn(
            "daybook_voice_memo_inbox_long_liveness_report.category in "
            "['lock_contended', 'ledger_busy']",
            proof,
        )
        loaded = tasks[
            tasks.index(
                "Verify Voice Memo inbox long lane label is loaded"
            ) : tasks.index("Require a loaded Voice Memo inbox long lane label")
        ]
        self.assertIn("- print", loaded)
        self.assertIn("daybook_voice_memo_inbox_long_launchd_label", loaded)
        # launchctl print dumps the loaded job's HOME, private log paths, and
        # environment: the raw output is hidden and only the exit status is used.
        self.assertIn("no_log: true", loaded)
        self.assertIn("register: daybook_voice_memo_inbox_long_loaded", loaded)
        self.assertIn("failed_when: false", loaded)
        report = tasks[
            tasks.index(
                "Require a loaded Voice Memo inbox long lane label"
            ) : tasks.index("Wait for privacy-safe first Voice Memo scan")
        ]
        # A non-zero launchctl print must still fail the activation block, and
        # only the sanitized rc and label may be reported.
        self.assertIn("daybook_voice_memo_inbox_long_loaded.rc | int == 0", report)
        self.assertNotIn("stdout", report)
        self.assertNotIn("stderr", report)
        # The first-scan proof marker stays bound to the short lane.
        marker = tasks[
            tasks.index(
                "Install root-owned proven first Voice Memo scan marker"
            ) : tasks.index("Rescue-disable Voice Memo inbox label")
        ]
        self.assertNotIn("long", marker)

    # ------------------------------------------------------------------
    # Executable coverage of the extracted proof tasks
    # ------------------------------------------------------------------

    def ansible_playbook_binary(self) -> str:
        """Locate ansible-playbook, skipping cleanly when it is unavailable."""
        bundled = ROOT / ".venv" / "bin" / "ansible-playbook"
        if bundled.exists():
            return str(bundled)
        found = shutil.which("ansible-playbook")
        if not found:
            self.skipTest(
                "ansible-playbook is not available (no .venv and none on PATH); "
                "run 'just venv' to execute the proof-task cases"
            )
        return found

    def test_every_daybook_cli_and_launchctl_print_task_hides_raw_output(self):
        """Verbose Ansible output must never carry the service home, user, or a traceback.

        Every task whose argv runs the Daybook CLI under `launchctl asuser`
        (its argv names the service home and user, and stderr can carry a
        traceback with private paths) and every label-scoped `launchctl print`
        (which dumps the job's environment) must set `no_log: true`, and the
        facts parsed from their stdout must be hidden as well.
        """

        def walk(tasks):
            for task in tasks:
                yield task
                for key in ("block", "rescue", "always"):
                    if key in task:
                        yield from walk(task[key])

        offenders = []
        for task in walk(self.role_task_list()):
            command = task.get("ansible.builtin.command") or {}
            argv = command.get("argv") if isinstance(command, dict) else None
            if not argv:
                continue
            runs_cli = (
                "asuser" in argv
                and "from daybook.cli import main; raise SystemExit(main())" in argv
            )
            prints_job = argv[:2] == ["/bin/launchctl", "print"]
            if (runs_cli or prints_job) and task.get("no_log") is not True:
                offenders.append(task.get("name"))
        self.assertEqual(offenders, [])
        for task in walk(self.role_task_list()):
            fact = task.get("ansible.builtin.set_fact") or {}
            if any("from_json" in str(value) for value in fact.values()):
                self.assertIs(task.get("no_log"), True, task.get("name"))

    def role_task_list(self) -> list:
        return yaml.safe_load(self.text(f"{ROLE}/tasks/main.yml"))

    def activation_block(self) -> dict:
        for task in self.role_task_list():
            if task.get("name") == ACTIVATION_BLOCK:
                return task
        self.fail(f"activation block not found: {ACTIVATION_BLOCK}")

    def extract_tasks(self, tasks: list, names: list) -> list:
        by_name = {task.get("name"): task for task in tasks}
        missing = [name for name in names if name not in by_name]
        self.assertEqual(missing, [], f"tasks missing from the role: {missing}")
        return [copy.deepcopy(by_name[name]) for name in names]

    def run_extracted_play(self, plays: list) -> subprocess.CompletedProcess:
        """Run role tasks verbatim against synthetic facts on localhost."""
        binary = self.ansible_playbook_binary()
        with tempfile.TemporaryDirectory() as workdir:
            playbook = Path(workdir) / "extracted.yml"
            playbook.write_text(
                yaml.safe_dump(plays, sort_keys=False), encoding="utf-8"
            )
            config = Path(workdir) / "ansible.cfg"
            config.write_text(
                "[defaults]\nstdout_callback = default\n", encoding="utf-8"
            )
            env = dict(
                os.environ,
                ANSIBLE_CONFIG=str(config),
                ANSIBLE_NOCOLOR="1",
                ANSIBLE_LOCALHOST_WARNING="False",
                ANSIBLE_INVENTORY_UNPARSED_WARNING="False",
                ANSIBLE_RETRY_FILES_ENABLED="False",
            )
            return subprocess.run(
                [binary, "-i", "localhost,", "-c", "local", str(playbook)],
                cwd=workdir,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
            )

    def liveness_case_block(self, case: dict, tasks: list) -> dict:
        """Wrap the extracted proof tasks in a per-case block and rescue."""
        return {
            "name": f"Liveness case {case['id']}",
            "vars": {
                "daybook_voice_memo_inbox_long_liveness": {
                    "rc": case["rc"],
                    "stdout": case["stdout"],
                },
                "daybook_voice_memo_inbox_long_loaded": {"rc": case["loaded_rc"]},
                "daybook_voice_memo_inbox_long_launchd_label": LONG_LABEL,
            },
            "block": copy.deepcopy(tasks)
            + [
                {
                    "name": f"Record proven case {case['id']}",
                    "ansible.builtin.debug": {"msg": f"CASE {case['id']} PROVEN"},
                }
            ],
            "rescue": [
                {
                    "name": f"Record failed case {case['id']}",
                    "ansible.builtin.debug": {"msg": f"CASE {case['id']} FAILED"},
                }
            ],
        }

    LIVENESS_CASES = [
        {
            "id": "proof-only-0",
            "rc": 0,
            "stdout": '{"category": "proof_only", "long_in_flight_count": 0}',
            "loaded_rc": 0,
            "expected": "PROVEN",
        },
        {
            "id": "lock-contended-75",
            "rc": 75,
            "stdout": '{"category": "lock_contended"}',
            "loaded_rc": 0,
            "expected": "PROVEN",
        },
        {
            "id": "ledger-busy-75",
            "rc": 75,
            "stdout": '{"category": "ledger_busy"}',
            "loaded_rc": 0,
            "expected": "PROVEN",
        },
        {
            "id": "proof-only-75",
            "rc": 75,
            "stdout": '{"category": "proof_only"}',
            "loaded_rc": 0,
            "expected": "FAILED",
        },
        {
            "id": "lock-contended-0",
            "rc": 0,
            "stdout": '{"category": "lock_contended"}',
            "loaded_rc": 0,
            "expected": "FAILED",
        },
        {
            "id": "other-category-0",
            "rc": 0,
            "stdout": '{"category": "long_lane_disabled"}',
            "loaded_rc": 0,
            "expected": "FAILED",
        },
        {
            "id": "malformed-json",
            "rc": 0,
            "stdout": 'Traceback (most recent call last): {"category": ',
            "loaded_rc": 0,
            "expected": "FAILED",
        },
        {
            "id": "unloaded-label",
            "rc": 0,
            "stdout": '{"category": "proof_only"}',
            "loaded_rc": 1,
            "expected": "FAILED",
        },
    ]

    def test_long_lane_liveness_proof_outcomes_are_executed(self):
        """Run the role's own proof tasks against synthetic lane outcomes."""
        proof_tasks = self.extract_tasks(
            self.activation_block()["block"],
            [
                # The two launchctl commands cannot run in a test; their
                # registered results are supplied as synthetic facts instead.
                "Parse Voice Memo inbox long lane liveness proof",
                "Require a proven live Voice Memo inbox long lane",
                "Require a loaded Voice Memo inbox long lane label",
            ],
        )
        play = {
            "hosts": "localhost",
            "connection": "local",
            "gather_facts": False,
            "tasks": [
                self.liveness_case_block(case, proof_tasks)
                for case in self.LIVENESS_CASES
            ],
        }
        completed = self.run_extracted_play([play])
        self.assertEqual(
            completed.returncode,
            0,
            f"harness play did not complete:\n{completed.stdout}\n{completed.stderr}",
        )
        for case in self.LIVENESS_CASES:
            expected = f"CASE {case['id']} {case['expected']}"
            unexpected = "CASE {} {}".format(
                case["id"], "FAILED" if case["expected"] == "PROVEN" else "PROVEN"
            )
            self.assertIn(expected, completed.stdout, completed.stdout)
            self.assertNotIn(unexpected, completed.stdout, completed.stdout)

    def test_long_lane_liveness_failure_is_fail_closed(self):
        """A rejected outcome leaves the block through its failure path."""
        proof_tasks = self.extract_tasks(
            self.activation_block()["block"],
            [
                "Parse Voice Memo inbox long lane liveness proof",
                "Require a proven live Voice Memo inbox long lane",
                "Require a loaded Voice Memo inbox long lane label",
            ],
        )
        rejected = [
            case for case in self.LIVENESS_CASES if case["expected"] == "FAILED"
        ]
        for case in (
            rejected[0],
            next(c for c in rejected if c["id"] == "malformed-json"),
        ):
            with self.subTest(case=case["id"]):
                play = {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "tasks": [
                        {
                            "name": f"Fail-closed case {case['id']}",
                            "vars": {
                                "daybook_voice_memo_inbox_long_liveness": {
                                    "rc": case["rc"],
                                    "stdout": case["stdout"],
                                },
                                "daybook_voice_memo_inbox_long_loaded": {
                                    "rc": case["loaded_rc"]
                                },
                                "daybook_voice_memo_inbox_long_launchd_label": LONG_LABEL,
                            },
                            "block": copy.deepcopy(proof_tasks),
                            # Stands in for the role's rescue, which can only
                            # run launchctl on a real Aqua session.
                            "rescue": [
                                {
                                    "name": "Fail closed like the role rescue",
                                    "ansible.builtin.fail": {
                                        "msg": "LONG LANE PROOF RESCUED"
                                    },
                                }
                            ],
                        }
                    ],
                }
                completed = self.run_extracted_play([play])
                self.assertNotEqual(completed.returncode, 0, completed.stdout)
                self.assertIn("LONG LANE PROOF RESCUED", completed.stdout)

    def test_long_lane_liveness_failure_path_is_the_two_label_rescue(self):
        """The block those proof tasks live in rescues both labels."""
        activation = self.activation_block()
        block_names = [task.get("name") for task in activation["block"]]
        for name in (
            "Parse Voice Memo inbox long lane liveness proof",
            "Require a proven live Voice Memo inbox long lane",
            "Require a loaded Voice Memo inbox long lane label",
        ):
            self.assertIn(name, block_names)
        rescue = activation["rescue"]
        rescue_names = [task.get("name") for task in rescue]
        self.assertEqual(
            rescue_names[:4],
            [
                "Rescue-disable Voice Memo inbox label",
                "Rescue-disable Voice Memo inbox long lane label",
                "Rescue-bootout Voice Memo inbox label",
                "Rescue-bootout Voice Memo inbox long lane label",
            ],
        )
        commands = {
            task["name"]: task["ansible.builtin.command"]["argv"]
            for task in rescue
            if "ansible.builtin.command" in task
        }
        for name, action, label in (
            ("Rescue-disable Voice Memo inbox label", "disable", SHORT_LABEL),
            ("Rescue-disable Voice Memo inbox long lane label", "disable", LONG_LABEL),
            ("Rescue-bootout Voice Memo inbox label", "bootout", SHORT_LABEL),
            ("Rescue-bootout Voice Memo inbox long lane label", "bootout", LONG_LABEL),
        ):
            argv = commands[name]
            self.assertEqual(argv[0], "/bin/launchctl")
            self.assertEqual(argv[1], action)
            self.assertTrue(argv[2].endswith("}}"), argv[2])
            self.assertIn(
                "long_launchd_label" if label == LONG_LABEL else "inbox_launchd_label",
                argv[2],
            )
        self.assertEqual(
            rescue_names[-1], "Fail closed after Voice Memo inbox activation error"
        )
        self.assertIn("ansible.builtin.fail", rescue[-1])

    def test_quiesce_proofs_fail_when_a_label_is_still_loaded(self):
        """The sanitized quiesce proofs keep failing on a loaded label."""
        proofs = {
            "short": (
                "Prove Voice Memo inbox is quiesced before managed changes",
                "daybook_voice_memo_inbox_quiesced",
                "daybook_voice_memo_inbox_launchd_label",
                SHORT_LABEL,
            ),
            "long": (
                "Prove Voice Memo inbox long lane is quiesced before managed changes",
                "daybook_voice_memo_inbox_long_quiesced",
                "daybook_voice_memo_inbox_long_launchd_label",
                LONG_LABEL,
            ),
        }
        blocks = []
        expectations = []
        for lane, (name, register, label_var, label) in proofs.items():
            task = self.extract_tasks(self.role_task_list(), [name])
            for rc, outcome in ((1, "QUIESCED"), (0, "LOADED")):
                case = f"{lane}-rc{rc}"
                expectations.append((case, outcome))
                blocks.append(
                    {
                        "name": f"Quiesce case {case}",
                        "vars": {
                            "daybook_voice_memo_inbox_enabled": True,
                            register: {"rc": rc},
                            label_var: label,
                        },
                        "block": copy.deepcopy(task)
                        + [
                            {
                                "name": f"Record quiesced case {case}",
                                "ansible.builtin.debug": {
                                    "msg": f"QUIESCE {case} QUIESCED"
                                },
                            }
                        ],
                        "rescue": [
                            {
                                "name": f"Record loaded case {case}",
                                "ansible.builtin.debug": {
                                    "msg": f"QUIESCE {case} LOADED"
                                },
                            }
                        ],
                    }
                )
        play = {
            "hosts": "localhost",
            "connection": "local",
            "gather_facts": False,
            "tasks": blocks,
        }
        completed = self.run_extracted_play([play])
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        for case, outcome in expectations:
            with self.subTest(case=case):
                self.assertIn(
                    f"QUIESCE {case} {outcome}", completed.stdout, completed.stdout
                )

    PREQUIESCE_CASES = [
        {"id": "count-three", "stdout": '{"long_in_flight_count": 3}', "value": "3"},
        {"id": "count-zero", "stdout": '{"long_in_flight_count": 0}', "value": "0"},
        {
            "id": "truncated-json",
            "stdout": '{"category": "healthy", "long_in_flight_count": 2, "queued',
            "value": "2",
        },
        {"id": "null-count", "stdout": '{"long_in_flight_count": null}', "value": ""},
        {
            # A null count must not borrow the next field's number.
            "id": "null-count-then-number",
            "stdout": '{"long_in_flight_count": null, "queued_count": 4}',
            "value": "",
        },
        {
            # Nothing negative is ever reported as a count.
            "id": "negative-count",
            "stdout": '{"long_in_flight_count": -1}',
            "value": "",
        },
        {"id": "not-json", "stdout": "Traceback (most recent call last):", "value": ""},
        {"id": "empty", "stdout": "", "value": ""},
    ]

    def test_pre_quiesce_count_extraction_never_stops_the_quiesce(self):
        """Malformed status output yields no count and no failure."""
        extraction_tasks = self.extract_tasks(
            self.role_task_list(),
            [
                "Extract Voice Memo inbox long lane in-flight count before quiesce",
                "Report Voice Memo inbox long lane in-flight count before quiesce",
            ],
        )
        blocks = []
        for case in self.PREQUIESCE_CASES:
            blocks.append(
                {
                    "name": f"Reset in-flight fact for {case['id']}",
                    "ansible.builtin.set_fact": {
                        "daybook_voice_memo_inbox_prequiesce_in_flight": ""
                    },
                }
            )
            blocks.append(
                {
                    "name": f"Pre-quiesce case {case['id']}",
                    "vars": {
                        "daybook_voice_memo_inbox_enabled": True,
                        "daybook_voice_memo_inbox_prequiesce_status": {
                            "rc": 0,
                            "stdout": case["stdout"],
                        },
                    },
                    "block": copy.deepcopy(extraction_tasks)
                    + [
                        {
                            "name": f"Record extracted count for {case['id']}",
                            "ansible.builtin.debug": {
                                "msg": (
                                    f"PREQUIESCE {case['id']} VALUE=["
                                    "{{ daybook_voice_memo_inbox_prequiesce_in_flight"
                                    " | default('') }}]"
                                )
                            },
                        }
                    ],
                    "rescue": [
                        {
                            "name": f"Record aborted case {case['id']}",
                            "ansible.builtin.debug": {
                                "msg": f"PREQUIESCE {case['id']} ABORTED"
                            },
                        }
                    ],
                }
            )
        play = {
            "hosts": "localhost",
            "connection": "local",
            "gather_facts": False,
            "tasks": blocks,
        }
        completed = self.run_extracted_play([play])
        self.assertEqual(
            completed.returncode,
            0,
            f"extraction must never fail the play:\n{completed.stdout}\n{completed.stderr}",
        )
        for case in self.PREQUIESCE_CASES:
            with self.subTest(case=case["id"]):
                self.assertNotIn(
                    f"PREQUIESCE {case['id']} ABORTED",
                    completed.stdout,
                    completed.stdout,
                )
                self.assertIn(
                    f"PREQUIESCE {case['id']} VALUE=[{case['value']}]",
                    completed.stdout,
                    completed.stdout,
                )
        # The operator line is emitted only for validated non-negative integers.
        reported = [
            line
            for line in completed.stdout.splitlines()
            if "items in flight before quiesce" in line
        ]
        expected_counts = [
            case["value"] for case in self.PREQUIESCE_CASES if case["value"]
        ]
        self.assertEqual(len(reported), len(expected_counts), completed.stdout)
        for line, count in zip(reported, expected_counts):
            self.assertIn(f"before quiesce: {count} ", line)

    def test_rescue_proves_both_labels_and_keeps_the_deployed_revision(self):
        tasks = self.text(f"{ROLE}/tasks/main.yml")
        rescue = tasks[tasks.index("  rescue:") :]
        order = [
            "Rescue-disable Voice Memo inbox label",
            "Rescue-disable Voice Memo inbox long lane label",
            "Rescue-bootout Voice Memo inbox label",
            "Rescue-bootout Voice Memo inbox long lane label",
            "Re-read disabled Voice Memo inbox labels after rescue",
            "Probe Voice Memo inbox label after rescue",
            "Probe Voice Memo inbox long lane label after rescue",
            "Require proven disabled/unloaded state after activation failure",
            "Fail closed after Voice Memo inbox activation error",
        ]
        positions = [rescue.index(name) for name in order]
        self.assertEqual(positions, sorted(positions))
        proof = rescue[positions[7] : positions[8]]
        self.assertIn(
            "daybook_voice_memo_inbox_long_launchd_label | regex_escape", proof
        )
        self.assertIn("daybook_voice_memo_inbox_rescue_probe.rc != 0", proof)
        self.assertIn("daybook_voice_memo_inbox_rescue_long_probe.rc != 0", proof)
        self.assertIn("COULD NOT PROVE", proof)
        long_probe = rescue[positions[6] : positions[7]]
        self.assertIn(
            "until: daybook_voice_memo_inbox_rescue_long_probe.rc != 0", long_probe
        )
        self.assertIn("ignore_errors: true", long_probe)
        # The rescue only touches launchd; it never re-clones, re-syncs, or
        # otherwise changes the deployed Daybook revision.
        for forbidden in (
            "/usr/bin/git",
            "ansible.builtin.template",
            "ansible.builtin.copy",
            "ansible.builtin.file",
            "daybook_voice_memo_inbox_repo_ref",
            "daybook_voice_memo_inbox_uv_bin",
            "daybook_voice_memo_inbox_checkout_path",
        ):
            self.assertNotIn(forbidden, rescue, forbidden)
        self.assertIn("The deployed Daybook revision is unchanged.", rescue)

    def test_policy_renders_long_lane_fields_and_validates_their_ranges(self):
        policy = self.text(f"{ROLE}/templates/policy.json.j2")
        for field in (
            "long_lane_enabled",
            "long_max_duration_seconds",
            "long_max_audio_bytes",
            "long_realtime_factor",
            "long_queue_slack_seconds",
            "long_validation_timeout_seconds",
            "long_max_attempts",
            "long_queue_per_run",
            "long_min_gap_seconds",
            "long_interval_seconds",
        ):
            self.assertIn(f'"{field}"', policy, field)
        tasks = self.text(f"{ROLE}/tasks/main.yml")
        validation = tasks[: tasks.index("Resolve Voice Memo inbox service uid")]
        self.assertIn(
            "daybook_voice_memo_inbox_long_lane_enabled is boolean", validation
        )
        self.assertIn(
            "daybook_voice_memo_inbox_long_interval_seconds | int == 600", validation
        )
        for bound in (
            "long_max_duration_seconds | float > 180",
            "long_max_duration_seconds | float <= 3600",
            "long_max_audio_bytes | int >= 16777216",
            "long_max_audio_bytes | int < 26214400",
            "long_realtime_factor | float >= 0.02",
            "long_realtime_factor | float <= 4.0",
            "long_queue_slack_seconds | int >= 120",
            "long_queue_slack_seconds | int <= 900",
            "long_validation_timeout_seconds | int >= 30",
            "long_validation_timeout_seconds | int <= 120",
            "long_max_attempts | int >= 1",
            "long_max_attempts | int <= 10",
            "long_queue_per_run | int >= 1",
            "long_queue_per_run | int <= 5",
            "long_min_gap_seconds | int > 430",
            "long_min_gap_seconds | int <= 900",
        ):
            self.assertIn(bound, validation, bound)
            # Bounded values are validated unconditionally: they are rendered
            # into the shared policy whether or not the lane may do work.
            line = [
                candidate for candidate in validation.splitlines() if bound in candidate
            ][0]
            self.assertNotIn(
                "not daybook_voice_memo_inbox_long_lane_enabled | bool or", line, bound
            )
        self.assertIn("round(0, 'ceil') | int", validation)
        self.assertIn(
            "daybook_voice_memo_inbox_long_queue_slack_seconds | int\n", validation
        )
        self.assertIn(") <= 2700", validation)
        defaults = self.role_variables()
        deadline = (
            -(
                -int(
                    defaults["daybook_voice_memo_inbox_long_max_duration_seconds"]
                    * defaults["daybook_voice_memo_inbox_long_realtime_factor"]
                    * 1000
                )
                // 1000
            )
            + defaults["daybook_voice_memo_inbox_long_queue_slack_seconds"]
        )
        self.assertLessEqual(deadline, 2700)

    def test_second_log_pair_is_owner_only_and_check_mode_guarded(self):
        tasks = self.text(f"{ROLE}/tasks/main.yml")
        logs = tasks[
            tasks.index("- name: Create owner-only Voice Memo inbox logs") + 1 :
        ]
        logs = logs[: logs.index("\n- name:")]
        for variable in (
            "daybook_voice_memo_inbox_stdout_log",
            "daybook_voice_memo_inbox_stderr_log",
            "daybook_voice_memo_inbox_long_stdout_log",
            "daybook_voice_memo_inbox_long_stderr_log",
        ):
            self.assertIn(f'"{{{{ {variable} }}}}"', logs, variable)
        self.assertIn('mode: "0600"', logs)
        self.assertIn(
            "not ansible_check_mode or daybook_voice_memo_inbox_parent_exists"
            "[daybook_voice_memo_inbox_log_dir]",
            logs,
        )
        validation = tasks[: tasks.index("Resolve Voice Memo inbox service uid")]
        self.assertIn(
            "daybook_voice_memo_inbox_long_stdout_log == "
            "daybook_voice_memo_inbox_log_dir ~ '/ingest-long.log'",
            validation,
        )
        self.assertIn(
            "daybook_voice_memo_inbox_long_stderr_log == "
            "daybook_voice_memo_inbox_log_dir ~ '/ingest-long.err.log'",
            validation,
        )
        plist_render = tasks[
            tasks.index(
                "- name: Render disabled-first Voice Memo inbox long lane LaunchAgent"
            )
            + 1 :
        ]
        plist_render = plist_render[: plist_render.index("\n- name:")]
        self.assertIn(
            "not ansible_check_mode or daybook_voice_memo_inbox_parent_exists"
            "[daybook_voice_memo_inbox_service_home ~ '/Library/LaunchAgents']",
            plist_render,
        )
        self.assertIn("src: voice-memo-inbox-long.launchd.plist.j2", plist_render)
        self.assertIn('mode: "0644"', plist_render)
        self.assertIn("owner: root", plist_render)


if __name__ == "__main__":
    unittest.main()
