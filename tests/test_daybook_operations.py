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
        self.assertEqual(args[4:6], ["operations", "serve"])
        self.assertNotIn(
            "LaunchAgents", values["daybook_operations_runtime_staged_plist"]
        )
        # Only a cutover enables dispatch. `replace` in particular writes the new
        # profile disabled: it changes the store's shape and starts nothing.
        for action, enabled in [
            ("install", False),
            ("replace", False),
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

    def test_the_profile_is_schema_4_and_names_no_source(self):
        """The machine's identity, the kinds of work it can run, a pool and a store.

        No source: since step 3 the source list is the server's, and a source is
        added with an insert there. What stays per kind is how it runs here and
        what that costs.
        """
        role = "daybook_operations_runtime_deploy"
        values, env = self.variables(role)
        kinds = [
            {"adapter": "voice_memos.ingest.v1", "deadline": 330, "lease": 600},
            {"adapter": "voice_memos.transcribe_long.v1", "deadline": 1200, "lease": 1500},
        ]
        values["daybook_operations_runtime_kinds"] = kinds
        plist = plistlib.loads(
            env.from_string(self.text(role, "templates/runtime.plist.j2"))
            .render(**values).encode())
        self.assertEqual(plist["ProgramArguments"][4:6], ["operations", "serve"])
        self.assertTrue(plist["KeepAlive"])
        self.assertNotIn("StartInterval", plist)

        policy = json.loads(
            env.from_string(self.text(role, "templates/policy.json.j2")).render(**values))
        self.assertEqual(policy["schema"], 4)
        self.assertEqual(policy["kinds"], kinds)
        self.assertNotIn("bindings", policy)
        self.assertEqual(policy["journal"], values["daybook_operations_runtime_journal"])
        self.assertEqual(policy["workers"], {"count": 2, "long": 1})
        for entry in policy["kinds"]:
            self.assertNotIn("name", entry)
            self.assertNotIn("cadence", entry)
            self.assertNotIn("journal", entry)
        self.assertFalse(policy["enabled"])

    def test_the_store_is_a_new_directory_not_an_old_journal(self):
        values, _ = self.variables("daybook_operations_runtime_deploy")
        store = values["daybook_operations_runtime_journal"]
        self.assertTrue(store.endswith("/.local/state/daybook/operations"), store)
        self.assertNotIn("operations-importer", store)
        self.assertNotIn("operations-long", store)

    def test_the_role_refuses_a_profile_that_would_stop_at_load(self):
        """Each of these fails on the machine anyway; failing here is cheaper."""
        role = "daybook_operations_runtime_deploy"
        tasks = yaml.safe_load(self.text(role, "tasks/main.yml"))
        entry = next(t for t in tasks if t["name"].startswith("Validate every kind of work"))
        conditions = " ".join(entry["ansible.builtin.assert"]["that"])
        self.assertIn("['adapter', 'deadline', 'lease']", conditions)
        self.assertIn("daybook_operations_runtime_adapters", conditions)
        self.assertIn("item.lease >= item.deadline + 60", conditions)
        for field in ("deadline", "lease"):
            self.assertIn(f"item.{field} is integer and item.{field} is not boolean",
                          conditions)
        self.assertNotIn("| int", conditions)
        self.assertNotIn("cadence", conditions)
        self.assertEqual(entry["loop"], "{{ daybook_operations_runtime_kinds }}")
        once = next(t for t in tasks if t["name"] == "Require each kind of work at most once")
        self.assertIn("map(attribute='adapter') | unique", str(once))

        guard = next(t for t in tasks if t["name"] == "Validate protected runtime installation")
        conditions = " ".join(guard["ansible.builtin.assert"]["that"])
        self.assertIn("daybook_operations_runtime_mode in ['tick', 'serve']", conditions)
        self.assertIn("daybook_operations_runtime_action in ['install', 'replace', 'cutover', 'rollback']",
                      conditions)
        self.assertIn("daybook_operations_runtime_workers.long < daybook_operations_runtime_workers.count",
                      conditions)
        self.assertIn("daybook_operations_runtime_workers.long >= 1", conditions)
        self.assertIn("daybook_operations_runtime_action != 'replace' or not daybook_operations_runtime_start",
                      conditions)
        self.assertNotIn("bindings", conditions)

    def test_changing_the_stores_shape_proves_every_old_journal_drained(self):
        """The installed client reads only schema 3, so it cannot be asked about a
        schema 2 profile. The proof reads the files -- and must not pass on their
        absence: a missing journal, or a used one whose slot is gone, proves
        nothing. The real behaviour is checked against Ansible itself in the
        runbook's validation; this pins the shape so it cannot silently regress."""
        role = "daybook_operations_runtime_deploy"
        tasks = yaml.safe_load(self.text(role, "tasks/main.yml"))
        names = [t["name"] for t in tasks]
        exists = tasks[names.index("Require every journal being left behind to exist")]
        self.assertIn("item.stat.exists and item.stat.isdir",
                      exists["ansible.builtin.assert"]["that"])
        inspect = tasks[names.index("Inspect every journal being left behind")]
        self.assertIn("/deliveries", inspect["loop"])
        self.assertIn("/halts", inspect["loop"])
        evidence = tasks[names.index("Inspect the evidence files of each per-source journal")]
        self.assertIn("['delivery.json', 'runtime.lock', 'halted.json']", evidence["loop"])
        proof = tasks[names.index("Prove every per-source journal being left behind is drained")]
        conditions = " ".join(proof["ansible.builtin.assert"]["that"])
        self.assertIn("not halted.stat.exists", conditions)
        # An existing slot must be idle regardless of the lock; only a journal with
        # neither counts as never opened.
        self.assertIn("(slot.stat.exists and item in daybook_operations_runtime_idle_journals)",
                      conditions)
        self.assertIn("(not slot.stat.exists and not lock.stat.exists)", conditions)
        reset = tasks[names.index("Start the idle evidence from nothing")]
        self.assertEqual(reset["ansible.builtin.set_fact"],
                         {"daybook_operations_runtime_idle_journals": []})
        self.assertLess(names.index("Start the idle evidence from nothing"),
                        names.index("Collect the per-source journals whose slot reads exactly idle"))
        collect = tasks[names.index("Collect the per-source journals whose slot reads exactly idle")]
        self.assertIn(".phase == 'idle'", str(collect))
        store = tasks[names.index("Prove a store being replaced owes nothing")]
        self.assertIn("daybook_operations_runtime_old_store.matched == 0",
                      store["ansible.builtin.assert"]["that"])
        # Every proof runs before anything is written.
        for name in ("Prove every per-source journal being left behind is drained",
                     "Prove a store being replaced owes nothing"):
            self.assertLess(names.index(name),
                            names.index("Write disabled-first root-owned local policy"))

        identity = tasks[names.index(
            "Preserve profile identity and refuse installing over an enabled runtime")]
        conditions = " ".join(identity["ansible.builtin.assert"]["that"])
        # Only `replace` may change the profile's shape -- not `install`, which
        # skips the label check.
        self.assertIn("daybook_operations_runtime_previous_schema | int == 4 "
                      "or daybook_operations_runtime_action == 'replace'", conditions)
        self.assertNotIn("['install', 'replace']", conditions)
        self.assertIn("daybook_operations_runtime_previous_journals[0] == "
                      "daybook_operations_runtime_journal", conditions)
        # Kinds of work may be added, never silently dropped -- including the ones
        # an older profile only implied through its sources' adapters.
        self.assertIn("daybook_operations_runtime_previous_kinds | difference(", conditions)
        shape = tasks[names.index("Read the previous profile's shape")]["ansible.builtin.set_fact"]
        self.assertIn("previous.bindings | map(attribute='adapter')",
                      shape["daybook_operations_runtime_previous_kinds"])
        # An unknown future schema is refused, not assumed to look like the newest.
        self.assertIn("daybook_operations_runtime_previous_schema | int in [1, 2, 3, 4]", conditions)

        label = tasks[names.index("Require the regular label already quiesced before a replace")]
        self.assertEqual(label["failed_when"], "daybook_operations_runtime_replace_label.rc != 113")
        transition = tasks[names.index("Perform attended regular-label transition")]
        self.assertEqual(transition["when"], "daybook_operations_runtime_action in ['cutover', 'rollback']")

    def test_every_cli_call_names_its_source_and_the_store_is_created_whole(self):
        role = "daybook_operations_runtime_deploy"
        tasks = yaml.safe_load(self.text(role, "tasks/main.yml"))
        seen = 0
        for name in ("tasks/main.yml", "tasks/transition.yml", "tasks/start.yml"):
            for task in yaml.safe_load(self.text(role, name)):
                argv = (task.get("ansible.builtin.command") or {}).get("argv") or []
                if "operations" not in argv:
                    continue
                verb = argv[argv.index("operations") + 1]
                if verb == "serve":
                    continue
                seen += 1
                with self.subTest(file=name, verb=verb):
                    self.assertIn("--binding", argv)
                    self.assertEqual(argv[argv.index("--binding") + 1],
                                     "{{ daybook_operations_runtime_binding }}")
        self.assertGreaterEqual(seen, 3)

        store = next(t for t in tasks if t["name"] == "Create the owner-private delivery store")
        self.assertEqual(store["loop"], [
            "{{ daybook_operations_runtime_journal }}",
            "{{ daybook_operations_runtime_journal }}/deliveries",
            "{{ daybook_operations_runtime_journal }}/halts",
        ])
        self.assertEqual(store["ansible.builtin.file"]["mode"], "0700")

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
