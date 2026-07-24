import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DaybookPhotosOffloadDeployTests(unittest.TestCase):
    def text(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_role_is_quiesce_first_and_user_scoped(self):
        defaults = self.text(
            "roles/daybook_photos_offload_deploy/defaults/main.yml"
        )
        tasks = self.text("roles/daybook_photos_offload_deploy/tasks/main.yml")

        self.assertIn("daybook_photos_offload_launchd_enabled: false", defaults)
        self.assertIn("/Library/LaunchAgents/", defaults)
        self.assertIn('ansible_become_flags: "-H -i"', defaults)
        self.assertIn("ansible_become_flags == '-H -i'", tasks)
        self.assertIn("launchctl", tasks)
        self.assertIn("gui/{{ daybook_photos_offload_uid.stdout | trim }}", tasks)
        self.assertIn(
            "Disable Photos offload before changing deployment state",
            tasks,
        )
        self.assertLess(
            tasks.index("quiesce | Disable Photos offload"),
            tasks.index("source | Materialize exact detached Daybook Photos revision"),
        )
        self.assertLess(
            tasks.index("quiesce | Boot out the exact loaded Photos offload service"),
            tasks.index("runtime | Synchronize pinned Daybook runtime"),
        )
        self.assertIn(
            "gui/{{ daybook_photos_offload_uid.stdout | trim }}/"
            "{{ daybook_photos_offload_launchd_label }}",
            tasks,
        )
        self.assertNotIn("/Library/LaunchDaemons/", defaults)

    def test_launcher_is_pinned_clean_and_content_minimized(self):
        launcher = self.text(
            "roles/daybook_photos_offload_deploy/templates/reconcile.sh.j2"
        )

        self.assertIn("/usr/bin/git -C", launcher)
        self.assertIn("rev-parse HEAD", launcher)
        self.assertIn("status --porcelain=v1 --untracked-files=all", launcher)
        self.assertIn("--frozen", launcher)
        self.assertIn("--no-dev", launcher)
        self.assertIn("--no-config", launcher)
        self.assertNotIn("--no-sync", launcher)
        self.assertIn("/usr/bin/env -i", launcher)
        self.assertIn("UV_PROJECT_ENVIRONMENT=", launcher)
        self.assertIn("GIT_CONFIG_GLOBAL=/dev/null", launcher)
        self.assertIn("GIT_CONFIG_SYSTEM=/dev/null", launcher)
        self.assertIn("safe.directory=", launcher)
        self.assertIn("core.fsmonitor=false", launcher)
        self.assertIn("ls-files -v", launcher)
        self.assertIn(
            "diff --no-ext-diff --no-textconv --quiet HEAD --",
            launcher,
        )
        self.assertIn("ls-files --others --ignored --exclude-standard", launcher)
        self.assertLess(
            launcher.index("config --no-includes --local"),
            launcher.index("rev-parse HEAD"),
        )
        self.assertIn("generic_failure", launcher)
        self.assertIn("exec 2>/dev/null", launcher)
        self.assertIn(
            "cd -- {{ daybook_photos_offload_checkout_path | quote }}",
            launcher,
        )
        self.assertIn("photos offload-reconcile", launcher)
        self.assertIn("--summary-only", launcher)
        self.assertNotIn("offload-discover", launcher)
        self.assertNotIn("/Volumes/", launcher)

    def test_plist_is_aqua_twice_daily_and_never_run_at_load(self):
        plist = self.text(
            "roles/daybook_photos_offload_deploy/templates/photos-offload.launchd.plist.j2"
        )
        defaults = self.text(
            "roles/daybook_photos_offload_deploy/defaults/main.yml"
        )

        self.assertIn("<key>LimitLoadToSessionType</key>", plist)
        self.assertIn("<string>Aqua</string>", plist)
        self.assertIn("<key>RunAtLoad</key>\n  <false/>", plist)
        self.assertIn("<key>StartCalendarInterval</key>", plist)
        self.assertIn("- Hour: 8\n    Minute: 10", defaults)
        self.assertIn("- Hour: 20\n    Minute: 10", defaults)
        self.assertNotIn("<key>UserName</key>", plist)

    def test_paths_logs_and_managed_files_are_hardened(self):
        defaults = self.text(
            "roles/daybook_photos_offload_deploy/defaults/main.yml"
        )
        tasks = self.text("roles/daybook_photos_offload_deploy/tasks/main.yml")

        self.assertIn(
            'daybook_photos_offload_log_dir: '
            '"{{ daybook_photos_offload_runtime_dir }}/logs"',
            defaults,
        )
        self.assertIn("owner: root", tasks)
        self.assertIn(
            'daybook_photos_offload_checkout_path: "/Library/Application Support/',
            defaults,
        )
        self.assertIn(
            'daybook_photos_offload_repo_bundle_path: '
            '"{{ daybook_photos_offload_checkout_path | dirname }}/source.bundle"',
            defaults,
        )
        self.assertIn(
            'daybook_photos_offload_repo_bundle_src: "CHANGEME"',
            defaults,
        )
        validation = tasks.split(
            "validate | Ensure required Photos offload variables are safe", 1
        )[1].split("validate | Reject traversal", 1)[0]
        self.assertIn(
            "daybook_photos_offload_repo_url == "
            "daybook_photos_offload_repo_bundle_path",
            validation,
        )
        self.assertIn(
            "daybook_photos_offload_repo_bundle_src != 'CHANGEME'",
            validation,
        )
        self.assertIn(
            "Install controller-verified Photos offload source bundle",
            tasks,
        )
        self.assertNotIn("ansible.builtin.git:", tasks)
        self.assertIn("Clone protected Daybook Photos bundle without checkout", tasks)
        clone_start = tasks.index("Clone protected Daybook Photos bundle without checkout")
        clone_end = tasks.index("\n- name:", clone_start)
        self.assertIn("- --branch\n      - main", tasks[clone_start:clone_end])
        self.assertIn("Fetch exact protected Daybook Photos bundle update", tasks)
        fetch_start = tasks.index("Fetch exact protected Daybook Photos bundle update")
        fetch_end = tasks.index("\n- name:", fetch_start)
        self.assertIn("changed_when: false", tasks[fetch_start:fetch_end])
        self.assertIn("GIT_CONFIG_GLOBAL=/dev/null", tasks)
        self.assertIn("GIT_CONFIG_SYSTEM=/dev/null", tasks)
        self.assertIn("GIT_TERMINAL_PROMPT=0", tasks)
        for mutation in (
            "Clone protected Daybook Photos bundle without checkout",
            "Fetch exact protected Daybook Photos bundle update",
            "Materialize exact detached Daybook Photos revision",
        ):
            start = tasks.index(mutation)
            next_task = tasks.find("\n- name:", start)
            block = tasks[start : next_task if next_task != -1 else None]
            self.assertIn("not ansible_check_mode", block)
        bundle_install = tasks.split(
            "Install controller-verified Photos offload source bundle", 1
        )[1].split("Remove ACLs from managed Photos offload source bundle", 1)[0]
        self.assertIn("not ansible_check_mode", bundle_install)
        self.assertIn("Require exact managed Photos offload source bundle", tasks)
        self.assertLess(
            tasks.index("Require exact managed Photos offload source bundle"),
            tasks.index("Materialize exact detached Daybook Photos revision"),
        )
        self.assertIn(
            "Write root-only Photos offload checkout trust attestation",
            tasks,
        )
        self.assertIn(
            "Reject unsafe trust attestation and require it for a pre-existing checkout",
            tasks,
        )
        self.assertIn(
            "Require exact protected written Photos offload trust attestation",
            tasks,
        )
        written_attestation = tasks.split(
            "Require exact protected written Photos offload trust attestation", 1
        )[1].split("\n- name:", 1)[0]
        self.assertIn("stat.nlink", written_attestation)
        self.assertIn("stat.mode == '0600'", written_attestation)
        self.assertIn("stdout_lines | length == 1", written_attestation)
        self.assertIn(
            "daybook_photos_offload_launchd_manage_state | bool",
            tasks.split(
                "validate | Ensure required Photos offload variables are safe",
                1,
            )[1].split("validate | Reject traversal", 1)[0],
        )
        self.assertIn("Reject traversal and relative Photos offload paths", tasks)
        self.assertIn("Reject existing symlink components", tasks)
        self.assertIn("item.stat.nlink", tasks)
        self.assertIn("/bin/pwd", tasks)
        self.assertIn("-P", tasks)
        self.assertIn(
            "Inspect Photos offload environment before synchronization",
            tasks,
        )
        self.assertLess(
            tasks.index("Inspect Photos offload environment before synchronization"),
            tasks.index("Synchronize pinned Daybook runtime"),
        )
        self.assertIn(
            '- "{{ daybook_photos_offload_venv_path }}"',
            tasks.split("Reject existing symlink components", 1)[1].split(
                "Inspect pre-existing Photos offload checkout",
                1,
            )[0],
        )
        self.assertLess(
            tasks.index("Inspect pre-existing Photos offload Git identity"),
            tasks.index("Materialize exact detached Daybook Photos revision"),
        )
        self.assertLess(
            tasks.index("Recheck checkout components before runtime synchronization"),
            tasks.index("Synchronize pinned Daybook runtime"),
        )
        self.assertLess(
            tasks.index("Inspect Photos offload environment after checkout update"),
            tasks.index("Synchronize pinned Daybook runtime"),
        )
        self.assertIn("safe.directory=", tasks)
        self.assertIn("Verify every protected checkout descendant", tasks)
        self.assertNotIn("recurse: true", tasks)
        self.assertIn("Verify attested pre-existing protected checkout", tasks)
        self.assertIn("root-checkout-v1", tasks)
        self.assertNotIn("os.chown", tasks)
        self.assertNotIn("os.chmod", tasks)
        self.assertIn("if os.path.join(base, name) != excluded", tasks)
        self.assertIn("Inspect ignored pre-existing checkout content", tasks)
        self.assertIn("Inspect ignored deployed checkout content", tasks)
        self.assertLess(
            tasks.index("Inspect pre-existing repository-local Git configuration"),
            tasks.index("Inspect pre-existing Photos offload Git identity"),
        )
        self.assertLess(
            tasks.index("Ensure protected Daybook Photos checkout ancestors"),
            tasks.index("Reject existing symlink components"),
        )
        self.assertLess(
            tasks.index("Require ACL-free complete checkout ancestry"),
            tasks.index("Reject existing symlink components"),
        )
        self.assertLess(
            tasks.index("Reject existing symlink components"),
            tasks.index("Inspect pre-existing Photos offload checkout"),
        )
        self.assertIn("Require ACL-free complete checkout ancestry", tasks)
        self.assertIn(
            "Remove inherited ACLs from private Photos offload directories",
            tasks,
        )
        private_directories = tasks.split(
            "runtime | Ensure private Photos offload directories exist", 1
        )[1].split("runtime | Remove inherited ACLs", 1)[0]
        self.assertIn('- "{{ daybook_photos_offload_log_dir }}"', private_directories)
        private_logs = tasks.split(
            "runtime | Ensure private Photos offload logs exist", 1
        )[1].split("runtime | Remove ACLs from private Photos offload logs", 1)[0]
        self.assertIn(
            'become_user: "{{ daybook_photos_offload_service_user }}"',
            private_logs,
        )
        self.assertIn("Require ACL-free private Photos offload logs", tasks)
        self.assertIn("Require ACL-free user LaunchAgents directory", tasks)
        self.assertIn(
            "Require ACL-free Photos offload executable configuration",
            tasks,
        )
        self.assertLess(
            tasks.index("Require ACL-free Photos offload executable configuration"),
            tasks.index("activate | Enable and verify Photos offload"),
        )

    def test_absence_checks_require_expected_launchctl_result(self):
        tasks = self.text("roles/daybook_photos_offload_deploy/tasks/main.yml")

        self.assertGreaterEqual(tasks.count("=> disabled"), 5)
        self.assertGreaterEqual(tasks.count("=> true"), 4)
        self.assertIn("daybook_photos_offload_quiesced_print.rc == 113", tasks)
        self.assertIn("daybook_photos_offload_rescue_print.rc == 113", tasks)
        self.assertIn("daybook_photos_offload_final_print.rc == 113", tasks)
        self.assertGreaterEqual(tasks.count("Could not find service"), 3)
        self.assertIn("daybook_photos_offload_quiesced_disabled.rc == 0", tasks)
        self.assertIn("daybook_photos_offload_enabled_disabled.rc == 0", tasks)
        self.assertIn("daybook_photos_offload_rescue_disabled.rc == 0", tasks)
        self.assertIn("daybook_photos_offload_final_disabled.rc == 0", tasks)

    def test_activation_has_fail_closed_rescue(self):
        tasks = self.text("roles/daybook_photos_offload_deploy/tasks/main.yml")

        activation = tasks.split(
            "activate | Enable and verify Photos offload with fail-closed rescue",
            1,
        )[1]
        self.assertIn("rescue:", activation)
        self.assertIn(
            "activate | Disable Photos offload after activation failure",
            activation,
        )
        self.assertIn(
            "activate | Boot out Photos offload after activation failure",
            activation,
        )
        self.assertIn(
            "activate | Require fail-closed Photos offload rescue",
            activation,
        )
        rescue = activation.split("rescue:", 1)[1]
        self.assertIn("failed_when: false", rescue)
        self.assertLess(
            rescue.index("Disable Photos offload after activation failure"),
            rescue.index("Boot out Photos offload after activation failure"),
        )
        self.assertIn(
            "gui/{{ daybook_photos_offload_uid.stdout | trim }}/"
            "{{ daybook_photos_offload_launchd_label }}",
            activation,
        )

    def test_read_only_probes_run_in_check_mode_and_mutations_do_not(self):
        tasks = self.text("roles/daybook_photos_offload_deploy/tasks/main.yml")

        for probe in (
            "Resolve Photos offload service user id",
            "Probe the logged-in user's GUI domain",
            "Read current Photos offload service state",
            "Read current Photos offload disabled state",
            "Read deployed Daybook commit",
            "Read deployed Daybook worktree status",
        ):
            start = tasks.index(probe)
            next_task = tasks.find("\n- name:", start)
            block = tasks[start : next_task if next_task != -1 else None]
            self.assertIn("check_mode: false", block)

        disable_start = tasks.index(
            "quiesce | Disable Photos offload before changing deployment state"
        )
        disable_end = tasks.index("\n- name:", disable_start)
        self.assertNotIn("check_mode: false", tasks[disable_start:disable_end])
        self.assertIn("failed_when: false", tasks[disable_start:disable_end])
        for mutation in (
            "Ensure protected Daybook Photos checkout ancestors exist",
            "Protect the checkout root from service-user replacement",
            "Protect Git metadata root from service-user replacement",
            "Ensure checkout-local Photos offload environment exists",
            "Write root-only Photos offload checkout trust attestation",
            "Ensure private Photos offload directories exist",
            "Ensure user LaunchAgents directory exists",
            "Ensure private Photos offload logs exist",
            "Render Photos offload launcher",
            "Render Photos offload user LaunchAgent",
        ):
            start = tasks.index(mutation)
            next_task = tasks.find("\n- name:", start)
            block = tasks[start : next_task if next_task != -1 else None]
            self.assertIn("not ansible_check_mode", block)

    def test_role_does_not_mutate_photos_or_fractal(self):
        tasks = self.text("roles/daybook_photos_offload_deploy/tasks/main.yml")
        launcher = self.text(
            "roles/daybook_photos_offload_deploy/templates/reconcile.sh.j2"
        )
        combined = tasks + launcher

        for forbidden in (
            "rm -",
            "delete",
            "mount_smbfs",
            "osascript",
            "recovery-bundle",
        ):
            self.assertNotIn(forbidden, combined)


if __name__ == "__main__":
    unittest.main()
