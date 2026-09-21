import json
import plistlib
import re
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]


class OperationsRoleTests(unittest.TestCase):
    def text(self, role, name):
        return (ROOT / "roles" / role / name).read_text()

    def variables(self, role):
        result = yaml.safe_load(self.text(role, "defaults/main.yml"))
        env = Environment()
        env.filters.update(
            bool=bool,
            to_json=json.dumps,
            to_nice_json=json.dumps,
            dirname=lambda p: str(Path(p).parent),
        )
        for _ in range(8):
            for key, value in list(result.items()):
                if isinstance(value, str) and "{{" in value:
                    result[key] = env.from_string(value).render(**result)
        return result, env

    def test_staged_runtime_keeps_fda_interpreter_and_fixed_adapter(self):
        role = "daybook_operations_runtime_deploy"
        values, env = self.variables(role)
        self.assertEqual(values["daybook_operations_runtime_action"], "install")
        self.assertFalse(values["daybook_operations_runtime_start"])
        plist = plistlib.loads(
            env.from_string(self.text(role, "templates/runtime.plist.j2"))
            .render(**values)
            .encode()
        )
        args = plist["ProgramArguments"]
        self.assertEqual(
            args[0],
            "/Library/Application Support/Daybook/voice-memo-inbox/daybook/.venv/bin/python",
        )
        self.assertEqual(args[1], "-I")
        self.assertEqual(args[4:6], ["operations", "tick"])
        self.assertEqual(plist["StartInterval"], 300)
        self.assertNotIn(
            "LaunchAgents", values["daybook_operations_runtime_staged_plist"]
        )
        for action, enabled in [
            ("install", False),
            ("cutover", True),
            ("rollback", False),
        ]:
            values["daybook_operations_runtime_action"] = action
            policy = json.loads(
                env.from_string(self.text(role, "templates/policy.json.j2")).render(
                    **values
                )
            )
            self.assertEqual(policy["enabled"], enabled)

    def test_the_supervisor_mode_renders_a_kept_alive_profile_of_several_bindings(self):
        """`serve` is one long-lived process, so launchd keeps it rather than
        waking it. That is only safe because a binding stopped for an operator
        records the stop beside its journal; without that, KeepAlive would be a
        retry loop straight back into the uncertain state."""
        role = "daybook_operations_runtime_deploy"
        values, env = self.variables(role)
        bindings = [
            {"name": "regular", "adapter": "voice_memos.ingest.v1",
             "journal": "/Users/x/.local/state/daybook/operations-importer",
             "cadence": 300, "deadline": 330, "lease": 600},
            {"name": "long", "adapter": "voice_memos.transcribe_long.v1",
             "journal": "/Users/x/.local/state/daybook/operations-long",
             "cadence": 600, "deadline": 1200, "lease": 1500},
        ]
        values["daybook_operations_runtime_mode"] = "serve"
        values["daybook_operations_runtime_bindings"] = bindings
        plist = plistlib.loads(
            env.from_string(self.text(role, "templates/runtime.plist.j2"))
            .render(**values).encode())
        self.assertEqual(plist["ProgramArguments"][4:6], ["operations", "serve"])
        self.assertTrue(plist["KeepAlive"])
        # A supervisor that owns its own due times must not also be woken.
        self.assertNotIn("StartInterval", plist)

        policy = json.loads(
            env.from_string(self.text(role, "templates/policy.json.j2")).render(**values))
        self.assertEqual(policy["schema"], 2)
        self.assertEqual(policy["bindings"], bindings)
        self.assertNotIn("binding", policy)
        self.assertNotIn("journal", policy)
        # Staging stays disabled; only an attended cutover enables dispatch.
        self.assertFalse(policy["enabled"])

    def test_the_single_binding_profile_is_untouched_by_the_supervisor_option(self):
        """Studio runs this today. Adding the option must not rewrite it."""
        role = "daybook_operations_runtime_deploy"
        values, env = self.variables(role)
        self.assertEqual(values["daybook_operations_runtime_mode"], "tick")
        self.assertEqual(values["daybook_operations_runtime_bindings"], [])
        policy = json.loads(
            env.from_string(self.text(role, "templates/policy.json.j2")).render(**values))
        self.assertEqual(policy["schema"], 1)
        self.assertEqual(policy["binding"], "regular")
        self.assertIn("journal", policy)
        plist = plistlib.loads(
            env.from_string(self.text(role, "templates/runtime.plist.j2"))
            .render(**values).encode())
        self.assertEqual(plist["ProgramArguments"][4:6], ["operations", "tick"])
        self.assertEqual(plist["StartInterval"], 300)
        self.assertNotIn("KeepAlive", plist)

    def test_the_role_refuses_a_profile_that_would_stop_at_load(self):
        """Each of these fails on the machine anyway; failing here is cheaper."""
        role = "daybook_operations_runtime_deploy"
        tasks = yaml.safe_load(self.text(role, "tasks/main.yml"))
        entry = next(t for t in tasks if t["name"].startswith("Validate every binding"))
        conditions = " ".join(entry["ansible.builtin.assert"]["that"])
        self.assertIn("['adapter', 'cadence', 'deadline', 'journal', 'lease', 'name']",
                      conditions)
        self.assertIn("daybook_operations_runtime_adapters", conditions)
        # The lease must outlast the child plus termination and delivery.
        self.assertIn("item.lease >= item.deadline + 60", conditions)
        # Whole numbers, not things `| int` would coerce: the profile is emitted
        # verbatim and the client requires real integers, so a quoted "300" would
        # pass a coercing check here and stop the whole profile at load.
        for field in ("cadence", "deadline", "lease"):
            self.assertIn(f"item.{field} is integer and item.{field} is not boolean",
                          conditions)
        self.assertNotIn("| int", conditions)
        self.assertEqual(entry["loop"], "{{ daybook_operations_runtime_bindings }}")

        guard = next(t for t in tasks if t["name"] == "Validate protected runtime installation")
        conditions = guard["ansible.builtin.assert"]["that"]
        self.assertIn("daybook_operations_runtime_mode in ['tick', 'serve']", conditions)
        # A binding list and the supervisor go together in both directions.
        # `operations tick` with no `--binding` cannot choose between several
        # bindings, and launchd's fixed wake-up could not honour their separate
        # cadences either; `serve` with no list would supervise the schema 1
        # binding by accident rather than by decision.
        self.assertIn(
            "(daybook_operations_runtime_mode == 'serve') "
            "== (daybook_operations_runtime_bindings | length > 0)",
            " ".join(conditions))

        unique = next(t for t in tasks if t["name"].startswith("Require distinct"))
        self.assertIn("map(attribute='journal') | unique", str(unique))

        values, _ = self.variables(role)
        self.assertEqual(values["daybook_operations_runtime_adapters"],
                         ["voice_memos.ingest.v1", "voice_memos.transcribe_long.v1"])

    def test_transition_waits_before_bootout_and_never_touches_long_label(self):
        text = self.text("daybook_operations_runtime_deploy", "tasks/transition.yml")
        self.assertLess(text.index("Wait for current"), text.index("bootout"))
        self.assertLess(text.index("Prove runtime"), text.index("Install selected"))
        self.assertNotIn("voice-memo-inbox-long", text)
        self.assertNotIn("activation.json", text)
        self.assertIn("force: false", text)

    def test_server_binds_loopback_and_disabled_handler_cannot_start(self):
        role = "daybook_operations_api_deploy"
        values, env = self.variables(role)
        self.assertFalse(values["daybook_operations_api_enabled"])
        values["item"] = "api"
        service = env.from_string(self.text(role, "templates/service.j2")).render(
            **values
        )
        self.assertIn("--bind 127.0.0.1:10063", service)
        self.assertIn("NoNewPrivileges=true", service)
        self.assertIn(
            "when: daybook_operations_api_enabled | bool",
            self.text(role, "handlers/main.yml"),
        )
        router = yaml.safe_load(
            env.from_string(self.text(role, "templates/traefik.yml.j2")).render(
                **values
            )
        )
        self.assertIn(
            "daybook-operations-networks",
            router["http"]["routers"]["daybook-operations"]["middlewares"],
        )
        self.assertEqual(
            router["http"]["middlewares"]["daybook-operations-limit"]["buffering"][
                "maxRequestBodyBytes"
            ],
            16384,
        )

    def test_capacity_monitoring_environment_is_rendered_and_bounded(self):
        role = "daybook_operations_api_deploy"
        values, env = self.variables(role)
        environment = env.from_string(self.text(role, "templates/environment.j2")).render(
            **values
        )
        settings = dict(
            line.split("=", 1) for line in environment.splitlines() if "=" in line
        )
        # The sampled location is operator-configured and absolute; no client selects it.
        self.assertTrue(settings["OPERATIONS_STORAGE_PATH"].startswith("/"))
        self.assertEqual(settings["OPERATIONS_RECORD_LIMIT"], "100000")
        self.assertEqual(settings["OPERATIONS_NOMINAL_RECORDS_PER_DAY"], "1152")
        self.assertEqual(settings["OPERATIONS_CAPACITY_WARN_UTILIZATION"], "0.7")
        self.assertEqual(settings["OPERATIONS_CAPACITY_CRITICAL_UTILIZATION"], "0.8")
        self.assertEqual(settings["OPERATIONS_CAPACITY_WARN_DAYS"], "30")
        self.assertEqual(settings["OPERATIONS_CAPACITY_CRITICAL_DAYS"], "14")
        # A missing sample must become stale well inside the documented alerting window.
        self.assertLessEqual(
            int(settings["OPERATIONS_STORAGE_SAMPLE_INTERVAL"]),
            int(settings["OPERATIONS_STORAGE_SAMPLE_MAX_AGE"]),
        )
        self.assertEqual(settings["OPERATIONS_STORAGE_SAMPLE_MAX_AGE"], "900")

    def test_role_validates_capacity_bounds_and_separated_profile_purposes(self):
        tasks = yaml.safe_load(self.text("daybook_operations_api_deploy", "tasks/main.yml"))
        asserts = [
            task
            for task in tasks
            if task.get("ansible.builtin.assert") and task["name"].startswith("Validate")
        ]
        conditions = " ".join(
            " ".join(task["ansible.builtin.assert"]["that"]) for task in asserts
        )
        for expected in (
            "daybook_operations_api_storage_path is match('^/')",
            "daybook_operations_api_nominal_records_per_day | int >= 1",
            "daybook_operations_api_capacity_critical_utilization | float <= 1",
        ):
            self.assertIn(expected, conditions)
        purposes = next(
            task for task in asserts if task["name"] == "Validate profile purposes"
        )
        self.assertTrue(purposes["no_log"])
        # A monitor token may never also be listed as an executor token.
        self.assertIn(
            "item.monitor_tokens | default([]) | select('in', item.tokens) | list | length == 0",
            purposes["ansible.builtin.assert"]["that"],
        )
        self.assertIn(
            "item.monitor_tokens is not defined or item.schema is defined",
            purposes["ansible.builtin.assert"]["that"],
        )

    def test_the_server_role_accepts_a_schema_three_profile_and_checks_its_bindings(self):
        """The provisioner learned schema 3; this role had to as well.

        A dry run caught it refusing the very profile ops-control now writes.
        Validating here names the offending field, where the provisioner can only
        report that the whole file was invalid.
        """
        role = "daybook_operations_api_deploy"
        tasks = yaml.safe_load(self.text(role, "tasks/main.yml"))
        purposes = next(t for t in tasks if t["name"] == "Validate profile purposes")
        conditions = purposes["ansible.builtin.assert"]["that"]
        self.assertIn("item.schema is not defined or item.schema in [2, 3]", conditions)
        # Schema 3 replaces the single-binding keys rather than ignoring them,
        # and the earlier schemas must not carry a binding list.
        joined = " ".join(conditions)
        self.assertIn("'binding' not in item and 'binding_enabled' not in item", joined)
        self.assertIn("('bindings' not in item)", joined)
        # A schema 3 entry with no list at all would otherwise slip past both
        # binding checks, which skip profiles that have none.
        self.assertIn("item.schema | default(2) != 3 or item.bindings is defined", conditions)

        entry = next(t for t in tasks if t["name"].startswith("Validate every binding"))
        checks = " ".join(entry["ansible.builtin.assert"]["that"])
        self.assertIn("['adapter', 'cadence', 'enabled', 'lease_seconds', 'name']", checks)
        self.assertIn("daybook_operations_api_adapters", checks)
        # Whole numbers, not values `| int` would coerce: the profile is written
        # out as given and the provisioner requires real integers.
        for field in ("cadence", "lease_seconds"):
            self.assertIn(f"item.1.{field} is integer and item.1.{field} is not boolean",
                          checks)
        self.assertNotIn("| int", checks)
        # A quoted "false" is not false.
        self.assertIn("item.1.enabled is boolean", checks)
        # subelements with skip_missing leaves schema 1 and 2 profiles alone.
        self.assertIn("subelements('bindings', skip_missing=True)", entry["loop"])

        unique = next(t for t in tasks if t["name"].startswith("Require distinct binding"))
        self.assertIn("map(attribute='name') | unique", str(unique))

        values, _ = self.variables(role)
        self.assertEqual(values["daybook_operations_api_adapters"],
                         ["voice_memos.ingest.v1", "voice_memos.transcribe_long.v1"])

    def test_restore_account_can_atomically_replace_private_configuration(self):
        role = "daybook_operations_api_deploy"
        values, env = self.variables(role)
        tasks = yaml.safe_load(self.text(role, "tasks/main.yml"))
        directories = next(
            t for t in tasks if t["name"] == "Create service directories"
        )
        values["item"] = values["daybook_operations_api_config_dir"]
        config = directories["ansible.builtin.file"]
        owner = env.from_string(config["owner"]).render(**values)
        self.assertEqual(owner, values["daybook_operations_api_user"])
        mode = int(config["mode"], 8)
        self.assertEqual(mode & 0o300, 0o300)
        self.assertEqual(mode & 0o027, 0)

    def test_macos_user_commands_enter_an_accessible_login_directory(self):
        role = "daybook_operations_runtime_deploy"

        def walk(tasks):
            for task in tasks or []:
                yield task
                for branch in ("block", "rescue", "always"):
                    yield from walk(task.get(branch, []))

        checked = 0
        for path in (ROOT / "roles" / role / "tasks").glob("*.yml"):
            for task in walk(yaml.safe_load(path.read_text())):
                if "become_user" in task:
                    checked += 1
                    with self.subTest(task=task["name"]):
                        flags = task.get("become_flags", "").split()
                        for expected in ("-i", "-H", "-S", "-n"):
                            self.assertIn(expected, flags)
        self.assertGreater(checked, 0)

    def test_lifecycle_never_executes_service_owned_python_as_root(self):
        for action in ("backup", "restore"):
            role = "daybook_operations_api_" + action
            tasks = yaml.safe_load(self.text(role, "tasks/main.yml"))
            for task in tasks:
                if "ansible.builtin.command" in task:
                    self.assertIn("become_user", task)
                    self.assertNotEqual(task["become_user"], "root")
        tasks = self.text("daybook_operations_api_restore", "tasks/main.yml")
        self.assertLess(tasks.index("Validate before"), tasks.index("Stop both units"))
        self.assertLess(
            tasks.index("Stop both units"), tasks.index("Restore with safety")
        )
        self.assertNotIn("state: started", tasks)
        remove = self.text("daybook_operations_api_remove", "tasks/main.yml")
        self.assertNotIn("postgresql_db", remove)
        self.assertNotIn("user:", remove)

    def test_management_failure_exposes_only_known_categories(self):
        tasks = yaml.safe_load(
            self.text("daybook_operations_api_deploy", "tasks/management.yml")
        )
        task = tasks[0]["rescue"][0]
        env = Environment()
        env.filters["regex_findall"] = lambda value, pattern: re.findall(pattern, value)
        for error, expected in [
            (
                "PRIVATE-DIAGNOSTIC CommandError: operations_configuration_invalid",
                "operations_configuration_invalid",
            ),
            ("PRIVATE-UNRECOGNIZED", "management_command_failed"),
        ]:
            rendered = env.from_string(task["ansible.builtin.fail"]["msg"]).render(
                daybook_operations_api_management={"rc": 1, "stderr": error}
            )
            self.assertIn(expected, rendered)
            self.assertNotIn("PRIVATE", rendered)

    def test_management_uses_native_failures_and_orders_migration_first(self):
        tasks = yaml.safe_load(
            self.text("daybook_operations_api_deploy", "tasks/management.yml")
        )
        command = tasks[0]["block"][0]
        self.assertNotIn("failed_when", command)
        self.assertTrue(command["no_log"])
        self.assertIn("ansible.builtin.fail", tasks[0]["rescue"][0])
        main = yaml.safe_load(
            self.text("daybook_operations_api_deploy", "tasks/main.yml")
        )
        inclusion = next(
            t
            for t in main
            if t.get("ansible.builtin.include_tasks") == "management.yml"
        )
        self.assertEqual(inclusion["loop"][0], ["migrate", "--noinput"])
        self.assertEqual(inclusion["loop"][1][0], "provision_operations")

    def test_real_ansible_stops_after_command_signal_or_zero_rc_module_failure(self):
        import getpass
        import os
        import shutil
        import subprocess
        import sys
        import tempfile

        runner = shutil.which("ansible-playbook")
        self.assertIsNotNone(runner)
        helper = ROOT / "roles/daybook_operations_api_deploy/tasks/management.yml"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for mode in ("success", "command_failure", "signal", "module_failure"):
                with self.subTest(mode=mode):
                    marker = root / "calls.txt"
                    marker.unlink(missing_ok=True)
                    executable = root / "python"
                    executable.write_text(
                        f"#!{sys.executable}\n"
                        + "import os, signal, sys\n"
                        + f"with open({str(marker)!r}, 'a') as stream: stream.write(sys.argv[2] + '\\n')\n"
                        + "print('PRIVATE-CHILD-DIAGNOSTIC', file=sys.stderr)\n"
                        + (
                            "os.kill(os.getpid(), signal.SIGTERM)\n"
                            if mode == "signal"
                            else "raise SystemExit(2)\n"
                            if mode == "command_failure"
                            else ""
                        )
                    )
                    executable.chmod(0o700)
                    # management.yml expects venv/bin/python.
                    (root / "bin").mkdir(exist_ok=True)
                    link = root / "bin/python"
                    link.unlink(missing_ok=True)
                    link.symlink_to(executable)
                    variables = {
                        "ansible_connection": "local",
                        "ansible_become": False,
                        "ansible_python_interpreter": "/usr/bin/true"
                        if mode == "module_failure"
                        else sys.executable,
                        "daybook_operations_api_venv": str(root),
                        "daybook_operations_api_site": str(root),
                        "daybook_operations_api_user": getpass.getuser(),
                        "daybook_operations_api_secret_key": "CHANGE_ME",
                        "daybook_operations_api_database_url": "unused",
                        "daybook_operations_api_signing_keys": {},
                        "daybook_operations_api_signing_key_id": "test",
                        "daybook_operations_api_domain": "localhost",
                    }
                    play = [
                        {
                            "name": "Isolated management failure fixture",
                            "hosts": "localhost",
                            "gather_facts": False,
                            "vars": variables,
                            "tasks": [
                                {
                                    "name": "Exercise real included helper",
                                    "ansible.builtin.include_tasks": str(helper),
                                    "loop": [["migrate"], ["provision_operations"]],
                                    "loop_control": {
                                        "loop_var": "daybook_operations_api_management_argv"
                                    },
                                },
                                {
                                    "name": "After management",
                                    "ansible.builtin.debug": {
                                        "msg": "SERVICE_START_REACHED"
                                    },
                                },
                            ],
                        }
                    ]
                    playbook = root / "fixture.yml"
                    playbook.write_text(yaml.safe_dump(play, sort_keys=False))
                    environment = dict(
                        os.environ,
                        ANSIBLE_NOCOLOR="1",
                        ANSIBLE_STDOUT_CALLBACK="default",
                    )
                    result = subprocess.run(
                        [runner, "-i", "localhost,", str(playbook)],
                        env=environment,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    output = result.stdout + result.stderr
                    calls = marker.read_text().splitlines() if marker.exists() else []
                    self.assertNotIn("PRIVATE-CHILD-DIAGNOSTIC", output)
                    if mode == "success":
                        self.assertEqual(result.returncode, 0, output)
                        self.assertEqual(calls, ["migrate", "provision_operations"])
                        self.assertIn("SERVICE_START_REACHED", output)
                    else:
                        self.assertNotEqual(result.returncode, 0, output)
                        self.assertNotIn("provision_operations", calls)
                        self.assertNotIn("SERVICE_START_REACHED", output)
                        self.assertIn("management_command_failed", output)
