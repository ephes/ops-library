"""Tasks that pass credentials in their arguments must set no_log: true."""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_secret_no_log", ROOT / "scripts/check_secret_no_log.py"
)
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)


def findings(text: str) -> list[tuple[str, str]]:
    return list(check.iter_findings(yaml.safe_load(text)))


class SecretNoLogCheckTests(unittest.TestCase):
    def test_repository_has_no_unprotected_credential_tasks(self):
        self.assertEqual(check.scan(check.default_paths()), [])

    def test_bearer_header_without_no_log_is_flagged(self):
        result = findings(
            """
- name: Sync
  ansible.builtin.uri:
    url: "{{ base }}/sync"
    headers:
      Authorization: "Bearer {{ api_token }}"
  failed_when: false
"""
        )
        self.assertEqual(result, [("Sync", "sends header 'Authorization'")])

    def test_short_module_name_and_other_credential_headers_are_flagged(self):
        for header in ("authorization", "X-API-Key", "X-Auth-Token", "Cookie"):
            with self.subTest(header=header):
                result = findings(
                    f"""
- name: Call
  uri:
    url: https://example.invalid/
    headers:
      {header}: "{{{{ value }}}}"
"""
                )
                self.assertEqual(len(result), 1)

    def test_header_value_with_secret_variable_is_flagged(self):
        result = findings(
            """
- name: Call
  uri:
    url: https://example.invalid/
    headers:
      X-Custom: "{{ service_secret }}"
"""
        )
        self.assertEqual(len(result), 1)

    def test_url_password_and_secret_body_are_flagged(self):
        self.assertEqual(
            len(
                findings(
                    """
- uri:
    url: https://example.invalid/
    url_username: admin
    url_password: "{{ admin_password }}"
- uri:
    url: https://example.invalid/login
    method: POST
    body_format: json
    body:
      user: admin
      password: "{{ admin_password }}"
"""
                )
            ),
            2,
        )

    def test_curl_bearer_in_command_or_shell_is_flagged(self):
        result = findings(
            """
- name: Curl shell
  ansible.builtin.shell: >
    curl -fsS -H "Authorization: Bearer {{ token }}" https://example.invalid/
- name: Curl argv
  ansible.builtin.command:
    argv: [curl, -H, "Authorization: Bearer {{ token }}", https://example.invalid/]
- name: Curl oauth2 bearer option
  ansible.builtin.command:
    argv: [curl, --oauth2-bearer, "{{ api_token }}", https://example.invalid/]
- name: Split Bearer argument
  ansible.builtin.command:
    argv: [httpie, "Authorization:", Bearer, "{{ api_token }}"]
"""
        )
        self.assertEqual(len(result), 4)

    def test_secret_variable_on_a_command_line_is_flagged(self):
        result = findings(
            """
- name: Argv password
  ansible.builtin.command:
    argv: [python, manage.py, ensure_admin_user, --password, "{{ archive_admin_password }}"]
- name: Shell password
  ansible.builtin.shell: |
    mcrcon -H 127.0.0.1 -p "{{ minecraft_java_rcon_password }}" "list"
- name: Cmd secret
  command:
    cmd: "tool --secret={{ service_secret | quote }}"
- name: Free-form with args
  ansible.builtin.command: "doveadm pw -p {{ mail_admin_password }}"
  args:
    chdir: /tmp
- name: Raw token
  ansible.builtin.raw: "login {{ api_token }}"
- name: Stdin password
  ansible.builtin.command: htpasswd -niB user
  args:
    stdin: "{{ metrics_endpoint_auth_password }}"
- name: Action form
  action: ansible.builtin.shell echo {{ db_password }} | psql
"""
        )
        self.assertEqual(
            result,
            [
                ("Argv password", "renders a secret-named variable into the command line"),
                ("Shell password", "renders a secret-named variable into the command line"),
                ("Cmd secret", "renders a secret-named variable into the command line"),
                ("Free-form with args", "renders a secret-named variable into the command line"),
                ("Raw token", "renders a secret-named variable into the command line"),
                ("Stdin password", "renders a secret-named variable into stdin"),
                ("Action form", "renders a secret-named variable into the command line"),
            ],
        )

    def test_secret_off_the_command_line_or_with_no_log_is_not_flagged(self):
        result = findings(
            """
- name: Environment carries the secret
  ansible.builtin.command:
    argv: [mcrcon, -H, 127.0.0.1, list]
  environment:
    MCRCON_PASS: "{{ minecraft_java_rcon_password }}"
- name: Protected stdin
  ansible.builtin.command: htpasswd -niB user
  args:
    stdin: "{{ auth_password }}"
  no_log: true
- name: Secret pointers and literals
  ansible.builtin.command:
    argv:
      - tool
      - --password-file
      - "{{ admin_password_file }}"
      - "{{ token_path }}"
      - "{{ password_hash }}"
    stdin: "{{ lookup('ansible.builtin.file', 'service_token_status.py') }}"
- name: Plain variables
  ansible.builtin.shell: "systemctl restart {{ service_name }} && echo token"
"""
        )
        self.assertEqual(result, [])

    def assertRcon_wrapper(self, argv):
        """Run the wrapper with a fake mcrcon: password from stdin, not argv."""
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "mcrcon"
            fake.write_text('#!/bin/sh\nprintf "%s|%s\\n" "$MCRCON_PASS" "$*"\n')
            fake.chmod(0o700)
            rendered = [str(item).replace("{{ minecraft_java_rcon_port }}", "25575") for item in argv]
            result = subprocess.run(
                rendered, input="p4ss w0rd$'\"\n", capture_output=True, text=True, check=True,
                env={"PATH": f"{directory}:/usr/bin:/bin"},
            )
        self.assertEqual(result.stdout, "p4ss w0rd$'\"|-H 127.0.0.1 -P 25575 list\n")

    def test_role_commands_keep_secrets_off_the_command_line(self):
        def tasks(path):
            return {t["name"]: t for t in yaml.safe_load((ROOT / "roles" / path).read_text())}

        admin = tasks("archive_deploy/tasks/django.yml")["django | Ensure archive admin user exists"]
        command = admin["ansible.builtin.shell"]
        self.assertNotIn("archive_admin_password", command["cmd"])
        self.assertIn("--password-stdin", command["cmd"])
        self.assertEqual(command["stdin"], "{{ archive_admin_password }}")
        self.assertNotIn("environment", admin)
        self.assertIs(admin["no_log"], True)
        # The no_log task must not hide its own failure.
        self.assertIs(admin["failed_when"], False)
        report = tasks("archive_deploy/tasks/django.yml")["django | Report a failed archive admin user update"]
        self.assertIn("ansible.builtin.fail", report)
        self.assertIn("archive_ensure_admin_user.rc", report["when"])
        self.assertIn("archive_ensure_admin_user.stderr", report["ansible.builtin.fail"]["msg"])
        self.assertNotIn("archive_admin_password", yaml.safe_dump(report))

        verify = tasks("minecraft_java_deploy/tasks/verify.yml")
        rcon = verify["Test RCON connection"]
        command = rcon["ansible.builtin.command"]
        self.assertNotIn("-p", command["argv"])
        self.assertNotIn("password", yaml.safe_dump(command["argv"]))
        self.assertEqual(command["stdin"], "{{ minecraft_java_rcon_password }}")
        # Task environment ends up on the remote shell's command line.
        self.assertNotIn("environment", rcon)
        self.assertIs(rcon["no_log"], True)
        self.assertRcon_wrapper(command["argv"])
        self.assertIn("rcon_test.stdout", verify["Display RCON test result"]["ansible.builtin.debug"]["msg"])

        metrics = tasks("metrics_endpoint/tasks/main.yml")
        block = next(t for t in metrics.values() if any(
            inner.get("name") == "Generate htpasswd entry" for inner in t.get("block", [])))
        for name in ("Verify existing htpasswd credentials", "Generate htpasswd entry"):
            task = next(t for t in block["block"] if t["name"] == name)
            self.assertIs(task["no_log"], True)

    def test_failure_reports_never_print_the_uri_msg(self):
        """uri's msg can quote request headers (e.g. an invalid header value)."""
        for role, register in (
            ("fastdeploy_register_service", "sync_result"),
            ("echoport_backup", "echoport_backup_sync_result"),
        ):
            with self.subTest(role=role):
                tasks = yaml.safe_load((ROOT / "roles" / role / "tasks/main.yml").read_text())
                report = next(t for t in tasks if t.get("name") == "Report failed service sync")
                text = yaml.safe_dump(report)
                self.assertIn(f"{register}.status", text)
                self.assertNotIn(f"{register}.msg", text)
                sync = next(t for t in tasks if t.get("register") == register)
                self.assertIs(sync.get("no_log"), True)

    def test_no_log_on_task_or_enclosing_block_protects(self):
        result = findings(
            """
- name: Task level
  uri:
    url: https://example.invalid/
    headers:
      Authorization: "Bearer {{ api_token }}"
  no_log: true
- name: Block level
  no_log: true
  block:
    - name: Inner
      uri:
        url: https://example.invalid/
        headers:
          Authorization: "Bearer {{ api_token }}"
"""
        )
        self.assertEqual(result, [])

    def test_templated_or_false_no_log_does_not_protect(self):
        result = findings(
            """
- name: Templated
  uri:
    url: https://example.invalid/
    headers:
      Authorization: "Bearer {{ api_token }}"
  no_log: "{{ hide_secrets }}"
- name: Block overridden
  no_log: true
  block:
    - name: Inner false
      uri:
        url: https://example.invalid/
        headers:
          Authorization: "Bearer {{ api_token }}"
      no_log: false
"""
        )
        self.assertEqual([name for name, _ in result], ["Templated", "Inner false"])

    def test_task_level_args_and_action_forms_are_flagged(self):
        result = findings(
            """
- name: Args headers
  ansible.builtin.uri:
  args:
    url: https://example.invalid/
    headers:
      Authorization: "Bearer {{ api_token }}"
- name: Action dict
  action:
    module: ansible.builtin.uri
    url: https://example.invalid/
    headers:
      Authorization: "Bearer {{ api_token }}"
- name: Local action dict
  local_action:
    module: uri
    url: https://example.invalid/
    url_password: "{{ admin_password }}"
- name: Action string
  action: uri url=https://example.invalid/ url_password={{ admin_password }}
- name: Action shell
  action: >-
    ansible.builtin.shell curl -H "Authorization: Bearer {{ token }}" https://example.invalid/
- name: Free-form uri with args
  uri: url=https://example.invalid/
  args:
    headers:
      Authorization: "Bearer {{ api_token }}"
- name: Action nested args
  action:
    module: uri
    args:
      headers:
        Authorization: "Bearer plaintext"
- name: Action module with free-form args
  action:
    module: uri url=https://example.invalid/ url_password=plaintext
- name: Free-form API key header
  action: uri url=https://example.invalid/ headers="X-API-Key=plaintext"
- name: Free-form cookie header
  uri: url=https://example.invalid/ headers="Cookie=session=plaintext"
- name: Templated task args
  uri:
    url: https://example.invalid/
  args: "{{ request_args }}"
"""
        )
        self.assertEqual(
            [name for name, _ in result],
            [
                "Args headers",
                "Action dict",
                "Local action dict",
                "Action string",
                "Action shell",
                "Free-form uri with args",
                "Action nested args",
                "Action module with free-form args",
                "Free-form API key header",
                "Free-form cookie header",
                "Templated task args",
            ],
        )

    def test_vault_tagged_files_are_checked_and_parse_errors_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            vaulted = Path(directory) / "vaulted.yml"
            vaulted.write_text(
                """
- name: Uses vault inline
  ansible.builtin.set_fact:
    other: !vault |
      $ANSIBLE_VAULT;1.1;AES256
      3132
    raw_value: !unsafe "{{ not_templated }}"
- name: Leaky
  ansible.builtin.uri:
    url: https://example.invalid/
    headers:
      Authorization: "Bearer {{ api_token }}"
"""
            )
            broken = Path(directory) / "broken.yml"
            broken.write_text("- name: [unclosed\n")
            problems = check.scan([vaulted, broken])
        self.assertEqual(len(problems), 2)
        self.assertIn("'Leaky'", problems[0])
        self.assertIn("cannot be parsed", problems[1])

    def test_plain_requests_and_secret_pointers_are_not_flagged(self):
        result = findings(
            """
- uri:
    url: "{{ base }}/health"
    headers:
      Accept: application/json
- uri:
    url: https://example.invalid/
    src: "{{ token_file }}"
- command: curl -fsS http://127.0.0.1/health
"""
        )
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
