import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DaybookVoiceMemoInboxRoleTests(unittest.TestCase):
    def text(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_defaults_are_disabled_and_secret_free(self):
        defaults = self.text(
            "roles/daybook_voice_memo_inbox_deploy/defaults/main.yml"
        )
        self.assertIn("daybook_voice_memo_inbox_enabled: false", defaults)
        self.assertIn("daybook_voice_memo_inbox_launchd_enabled: false", defaults)
        self.assertIn('daybook_voice_memo_inbox_voxhelm_token: "CHANGEME"', defaults)
        self.assertIn(
            'daybook_voice_memo_inbox_s3_secret_access_key: "CHANGEME"',
            defaults,
        )
        self.assertNotIn("Bearer ", defaults)

    def test_schedule_and_program_arguments_are_fixed(self):
        defaults = self.text(
            "roles/daybook_voice_memo_inbox_deploy/defaults/main.yml"
        )
        plist = self.text(
            "roles/daybook_voice_memo_inbox_deploy/templates/voice-memo-inbox.launchd.plist.j2"
        )
        self.assertIn("daybook_voice_memo_inbox_interval_seconds: 300", defaults)
        self.assertIn("daybook_voice_memo_inbox_activation_status_retries: 72", defaults)
        self.assertIn("daybook_voice_memo_inbox_activation_status_delay_seconds: 5", defaults)
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
        self.assertIn("failed_when: daybook_voice_memo_inbox_quiesced.rc == 0", tasks)
        self.assertIn("until: daybook_voice_memo_inbox_quiesced.rc != 0", tasks)
        self.assertIn("until: daybook_voice_memo_inbox_rescue_probe.rc != 0", tasks)
        rescue_probe = tasks[tasks.index("Probe Voice Memo inbox label after rescue"):tasks.index(
            "Require proven disabled/unloaded state after activation failure"
        )]
        self.assertIn("ignore_errors: true", rescue_probe)
        protect = tasks[tasks.index("- name: Protect Voice Memo inbox interpreter\n") + 1:]
        protect = protect[: protect.index("\n- name:")]
        self.assertIn("follow: false", protect)
        self.assertIn("Require active Voice Memo owner Aqua domain for deployment", tasks)
        self.assertIn("Prove Voice Memo inbox label is disabled", tasks)
        self.assertIn("print-disabled", tasks)
        self.assertIn(
            "daybook_voice_memo_inbox_activation_confirmation == "
            "daybook_voice_memo_inbox_activation_phrase",
            tasks,
        )
        self.assertIn("Initialize Voice Memo historical baseline in Aqua context", tasks)
        self.assertIn("Install root-owned Voice Memo activation marker", tasks)
        self.assertIn("Capture Voice Memo ledger generation before bootstrap", tasks)
        self.assertIn("generation | int > daybook_voice_memo_inbox_prebootstrap_report.generation | int", tasks)
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
        proof_start = tasks.index("Install root-owned proven first Voice Memo scan marker")
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
        self.assertIn("Copy pinned Voice Memo inbox interpreter into protected checkout", tasks)
        self.assertIn("- -L", tasks)
        self.assertNotIn("- -pL", tasks)
        copy = tasks.index("Copy pinned Voice Memo inbox interpreter into protected checkout")
        protect_staged = tasks.index("Protect staged Voice Memo inbox interpreter before it becomes live")
        install = tasks.index("Install regular Voice Memo inbox interpreter atomically")
        self.assertLess(copy, protect_staged)
        self.assertLess(protect_staged, install)
        staged = tasks[protect_staged:install]
        self.assertIn("owner: root", staged)
        self.assertIn('mode: "0755"', staged)
        self.assertIn("daybook_voice_memo_inbox_python_needs_copy | bool", tasks[copy:install])
        self.assertIn(
            "daybook_voice_memo_inbox_protected_python.stat.checksum == daybook_voice_memo_inbox_python_source_checksum",
            tasks,
        )
        self.assertNotIn("stat.checksum | length == 40", tasks)
        self.assertIn("selectattr('item', 'eq', daybook_voice_memo_inbox_python_source)", tasks)
        self.assertIn("Require protected Voice Memo inbox interpreter boundary", tasks)
        self.assertIn("not daybook_voice_memo_inbox_protected_python.stat.islnk", tasks)
        self.assertIn("daybook_voice_memo_inbox_protected_python.stat.nlink == 1", tasks)
        self.assertIn("daybook_voice_memo_inbox_protected_python.stat.pw_name == 'root'", tasks)
        self.assertIn("daybook_voice_memo_inbox_protected_python.stat.mode == '0755'", tasks)
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
            4,
        )
        activation = tasks.split(
            "- name: Initialize Voice Memo historical baseline in Aqua context", 1
        )[1]
        self.assertGreaterEqual(
            activation.count(
                'chdir: "{{ daybook_voice_memo_inbox_checkout_path }}"'
            ),
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
        self.assertIn("does not disable, unload, or remove an existing installation", readme)

    def test_activation_rescue_proves_disabled_and_unloaded(self):
        tasks = self.text("roles/daybook_voice_memo_inbox_deploy/tasks/main.yml")
        rescue = tasks[tasks.index("  rescue:"):]
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
        proof = rescue[positions[4]:positions[5]]
        self.assertIn("daybook_voice_memo_inbox_rescue_disabled_labels.rc == 0", proof)
        self.assertIn("regex_search(", proof)
        self.assertIn("(?:true|disabled)", proof)
        self.assertIn("daybook_voice_memo_inbox_rescue_probe.rc != 0", proof)
        self.assertIn("COULD NOT PROVE", proof)
        self.assertIn("emergency disable", proof)
        final = rescue[positions[5]:]
        self.assertIn("proven", final)
        self.assertIn("disable rc={{ daybook_voice_memo_inbox_rescue_disable.rc }}", final)

    def test_checkout_replacement_fails_closed_when_git_cannot_read_revision(self):
        tasks = self.text("roles/daybook_voice_memo_inbox_deploy/tasks/main.yml")
        executables = tasks[tasks.index("Inspect required Voice Memo inbox executables"):tasks.index(
            "Require executable Voice Memo inbox prerequisites"
        )]
        self.assertIn("    - /usr/bin/git\n", executables)
        bundle_install = tasks.index("Install exact Daybook source bundle")
        verify = tasks.index("Verify installed Daybook source bundle against the existing checkout")
        heads = tasks.index("List installed Daybook source bundle heads")
        require_bundle = tasks.index("Require a valid Daybook bundle containing the pinned commit")
        inspect = tasks.index("Inspect existing managed Daybook checkout")
        refuse = tasks.index("Refuse to replace an existing checkout whose revision cannot be read")
        replace = tasks.index("Replace drifted managed Daybook checkout")
        self.assertLess(bundle_install, inspect)
        self.assertLess(inspect, verify)
        verify_block = tasks[verify:heads]
        self.assertIn('chdir: "{{ daybook_voice_memo_inbox_checkout_path }}"', verify_block)
        self.assertIn("- daybook_voice_memo_inbox_checkout_dir.stat.exists", verify_block)
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
        replace_block = tasks[replace:tasks.index("Clone exact Daybook bundle")]
        self.assertIn("- daybook_voice_memo_inbox_checkout_dir.stat.exists", replace_block)
        self.assertNotIn("installed_ref.rc != 0", replace_block)
        self.assertIn(
            "- daybook_voice_memo_inbox_installed_ref.stdout | trim != daybook_voice_memo_inbox_repo_ref\n",
            replace_block,
        )
        self.assertNotIn("daybook_voice_memo_inbox_bundle.changed", replace_block)

    def test_fresh_host_check_mode_guards_are_keyed_by_path(self):
        tasks = self.text("roles/daybook_voice_memo_inbox_deploy/tasks/main.yml")
        self.assertNotIn("managed_parents.results[", tasks)
        index = tasks[tasks.index("Index Voice Memo inbox managed parent directories by path"):]
        index = index[: index.index("- name: Create protected Voice Memo inbox directories")]
        self.assertIn("map(attribute='item')", index)
        self.assertIn("map(attribute='stat.exists')", index)
        for task_name, key in (
            ("Create owner-only Voice Memo inbox logs", "daybook_voice_memo_inbox_log_dir"),
            ("Install exact Daybook source bundle", "daybook_voice_memo_inbox_install_root"),
            ("Render protected Voice Memo inbox policy", "daybook_voice_memo_inbox_install_root"),
            ("Render owner-only Voice Memo inbox credentials", "daybook_voice_memo_inbox_credential_dir"),
            (
                "Render disabled-first Voice Memo inbox LaunchAgent",
                "daybook_voice_memo_inbox_service_home ~ '/Library/LaunchAgents'",
            ),
        ):
            body = tasks[tasks.index(f"- name: {task_name}") + 1:]
            body = body[: body.index("\n- name:")]
            self.assertIn(
                f"not ansible_check_mode or daybook_voice_memo_inbox_parent_exists[{key}]",
                body,
                task_name,
            )
        protect = tasks[tasks.index("- name: Protect Voice Memo inbox interpreter") + 1:]
        protect = protect[: protect.index("\n- name:")]
        self.assertIn(
            "not ansible_check_mode or daybook_voice_memo_inbox_python_stat.stat.exists",
            protect,
        )
        loop = tasks[tasks.index("Inspect Voice Memo inbox managed parent directories"):tasks.index(
            "Index Voice Memo inbox managed parent directories by path"
        )]
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
        sync_task = tasks.split(
            "- name: Synchronize locked Daybook runtime", 1
        )[1].split("- name: Inspect Voice Memo inbox virtualenv interpreter", 1)[0]
        self.assertIn("not ansible_check_mode", sync_task)
        self.assertIn("daybook_voice_memo_inbox_installed_ref.rc == 0", sync_task)
        self.assertIn(
            "daybook_voice_memo_inbox_installed_ref.stdout | trim == "
            "daybook_voice_memo_inbox_repo_ref",
            sync_task,
        )

    def test_launch_agent_is_scoped_to_voice_memos_owner(self):
        defaults = self.text(
            "roles/daybook_voice_memo_inbox_deploy/defaults/main.yml"
        )
        tasks = self.text("roles/daybook_voice_memo_inbox_deploy/tasks/main.yml")
        self.assertIn(
            'daybook_voice_memo_inbox_service_home }}/Library/LaunchAgents/',
            defaults,
        )
        self.assertNotIn('daybook_voice_memo_inbox_plist_path: "/Library/LaunchAgents/', defaults)
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
        defaults = self.text(
            "roles/daybook_voice_memo_inbox_deploy/defaults/main.yml"
        )
        self.assertIn('daybook_voice_memo_inbox_prefix: "Inbox/Voice Memos"', defaults)
        self.assertIn("min_stable_seconds", policy)
        self.assertIn("duration_tolerance_seconds", policy)
        self.assertIn("max_audio_bytes", policy)
        self.assertIn("max_duration_seconds", policy)
        self.assertIn("ffprobe_path", policy)
        self.assertIn("ffmpeg_path", policy)


if __name__ == "__main__":
    unittest.main()
