import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from jinja2 import Environment, StrictUndefined

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_TEMPLATE = (
    REPO_ROOT
    / "roles"
    / "certbot_dns_deploy"
    / "templates"
    / "renewal-hooks.sh.j2"
)


class CertbotDnsRenewalHookTemplateTests(unittest.TestCase):
    def render(self, hooks):
        # Match the Ansible template module's Jinja whitespace defaults.
        environment = Environment(
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=False,
            keep_trailing_newline=True,
            autoescape=False,
        )
        return environment.from_string(HOOK_TEMPLATE.read_text()).render(
            certbot_dns_renewal_hooks=hooks
        )

    def run_script(self, hooks, failing_service=None, env_overrides=None):
        script = self.render(hooks)
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            calls_path = temp_path / "calls"
            systemctl_path = temp_path / "systemctl"
            systemctl_path.write_text(
                "#!/bin/bash\n"
                'printf \'%s\\n\' "$*" >> "$HOOK_CALLS"\n'
                'if [ -n "${FAIL_SERVICE:-}" ] && [ "${!#}" = "$FAIL_SERVICE" ]; then\n'
                "  exit 1\n"
                "fi\n"
            )
            systemctl_path.chmod(0o755)

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{temp_path}:{env['PATH']}",
                    "HOOK_CALLS": str(calls_path),
                }
            )
            if failing_service:
                env["FAIL_SERVICE"] = failing_service
            if env_overrides:
                env.update(env_overrides)

            hook_path = temp_path / "reload-services.sh"
            hook_path.write_text(script)
            hook_path.chmod(0o755)
            result = subprocess.run(
                [str(hook_path)],
                capture_output=True,
                text=True,
                cwd=temp_path,
                env=env,
                check=False,
            )
            calls = calls_path.read_text().splitlines() if calls_path.exists() else []
            return script, result, calls

    def test_empty_hook_list_is_a_successful_noop(self):
        script, result, calls = self.run_script([])

        subprocess.run(["bash", "-n"], input=script, text=True, check=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [])

    def test_rendered_multiline_hooks_are_valid_and_run_in_order(self):
        hooks = [
            "printf 'preflight\\n' >> \"$HOOK_CALLS\"\n"
            "systemctl restart traefik",
            "systemctl reload postfix",
            "systemctl reload dovecot",
        ]
        script, result, calls = self.run_script(hooks)

        subprocess.run(["bash", "-n"], input=script, text=True, check=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            calls,
            ["preflight", "restart traefik", "reload postfix", "reload dovecot"],
        )

    def test_every_item_runs_and_any_failure_is_returned(self):
        hooks = [
            "systemctl restart traefik",
            "systemctl reload postfix",
            "systemctl reload dovecot",
        ]
        expected_calls = ["restart traefik", "reload postfix", "reload dovecot"]

        for item_index, failing_service in enumerate(
            ("traefik", "postfix", "dovecot"), start=1
        ):
            with self.subTest(failing_service=failing_service):
                _, result, calls = self.run_script(hooks, failing_service)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(calls, expected_calls)
                self.assertIn(
                    f"renewal hook item {item_index} failed", result.stderr
                )
                self.assertIn("rc=1", result.stderr)

    def test_failure_diagnostic_includes_renewed_lineage(self):
        lineage = "/etc/letsencrypt/live/example.test"
        _, result, _ = self.run_script(
            ["exit 2"], env_overrides={"RENEWED_LINEAGE": lineage}
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn(f"lineage={lineage}", result.stderr)

    def test_a_multiline_item_stops_at_its_first_failure(self):
        hooks = [
            "systemctl restart traefik\n"
            "printf 'must-not-run\\n' >> \"$HOOK_CALLS\"",
            "systemctl reload postfix",
        ]
        _, result, calls = self.run_script(hooks, failing_service="traefik")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(calls, ["restart traefik", "reload postfix"])

    def test_explicit_exit_is_isolated_to_one_item(self):
        for exit_status, expected_status in ((0, 0), (1, 1)):
            with self.subTest(exit_status=exit_status):
                hooks = [
                    f"exit {exit_status}",
                    "systemctl reload postfix",
                ]
                _, result, calls = self.run_script(hooks)

                self.assertEqual(result.returncode, expected_status)
                self.assertEqual(calls, ["reload postfix"])

    def test_lineage_guard_is_isolated_and_handles_unset_lineage(self):
        lineage = "/etc/letsencrypt/live/example.test"
        hooks = [
            f'[ "${{RENEWED_LINEAGE:-}}" = "{lineage}" ] || exit 0\n'
            "systemctl restart traefik",
            "systemctl reload postfix",
        ]

        _, unset_result, unset_calls = self.run_script(hooks)
        _, matching_result, matching_calls = self.run_script(
            hooks, env_overrides={"RENEWED_LINEAGE": lineage}
        )

        self.assertEqual(unset_result.returncode, 0, unset_result.stderr)
        self.assertEqual(unset_calls, ["reload postfix"])
        self.assertEqual(matching_result.returncode, 0, matching_result.stderr)
        self.assertEqual(matching_calls, ["restart traefik", "reload postfix"])

    def test_unset_variables_fail_only_their_item(self):
        hooks = [
            'printf \'%s\\n\' "$UNSET_HOOK_VALUE"',
            "systemctl reload postfix",
        ]
        _, result, calls = self.run_script(hooks)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(calls, ["reload postfix"])
        self.assertIn("renewal hook item 1 failed", result.stderr)

    def test_shell_state_does_not_leak_between_items(self):
        hooks = [
            "export HOOK_LOCAL=value\ncd /",
            '[ -z "${HOOK_LOCAL:-}" ]\n'
            '[ "$PWD" != "/" ]\n'
            "systemctl reload postfix",
        ]
        _, result, calls = self.run_script(hooks)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ["reload postfix"])

    def test_multiple_nonstandard_failures_report_each_rc_and_exit_one(self):
        hooks = ["exit 3", "exit 4", "systemctl reload postfix"]
        _, result, calls = self.run_script(hooks)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(calls, ["reload postfix"])
        self.assertIn("renewal hook item 1 failed (rc=3)", result.stderr)
        self.assertIn("renewal hook item 2 failed (rc=4)", result.stderr)

    def test_heredoc_indentation_is_preserved(self):
        hooks = [
            "systemctl restart traefik <<'HOOK_INPUT'\n"
            "certificate data\n"
            "HOOK_INPUT",
            "systemctl reload postfix",
        ]
        script, result, calls = self.run_script(hooks)

        self.assertIn("\nHOOK_INPUT\n", script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ["restart traefik", "reload postfix"])


if __name__ == "__main__":
    unittest.main()
