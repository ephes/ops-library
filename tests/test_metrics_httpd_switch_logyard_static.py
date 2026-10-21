"""The metrics-httpd switch in logyard_deploy and static_site_deploy.

rust/metrics-httpd/PLAN.md 7.2/7.3 (slice S5c). The switch itself
(``roles/metrics_httpd_switch``) is tested in ``test_metrics_httpd_switch.py``;
this module checks that the two roles feed it the right inputs:

- static checks: ``<role>_impl`` follows the fleet variable, select sits
  between the unit and the start, verify after a flush, the notified handlers
  exist, task names carry the file prefix;
- one ``ansible-playbook`` run rendering each role's switch inputs, drop-in
  and base unit from its defaults: the argv of PLAN.md 7.3 (and of the Rust
  fixtures), the ``--check-config`` sandbox equal to the unit's own
  ``[Service]`` lines (logyard: its ``Environment=`` lines, so
  ``metrics-httpd logyard-health`` reads what the unit gives it), the drop-in
  and the unchanged base unit equal to the goldens in
  ``tests/fixtures/metrics_httpd_switch/<role>/``;
- ``ansible-playbook`` runs of each role's inputs through select, flush and
  verify on localhost with the fakes of ``test_metrics_httpd_switch.py``:
  Python, the switch to Rust (exact ``systemd-run`` properties and
  ``--check-config`` argv, the ``logyard-health`` and ``static`` probes, the
  pin) and back;
- with ``METRICS_HTTPD_BIN`` set to a built ``metrics-httpd``: the binary's
  own ``--check-config`` accepts each role's rendered inputs.

Regenerate the goldens with ``METRICS_HTTPD_SWITCH_WRITE_GOLDENS=1``.
"""

from __future__ import annotations

import base64
import http.server
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Helpers of the switch's own tests (no test case is imported from there).
BASE = _load("metrics_httpd_switch_base_tests", ROOT / "tests/test_metrics_httpd_switch.py")
FILTERS = BASE.FILTERS
FQCN = BASE.FQCN
GOLDENS = BASE.GOLDENS
TEMPLATE = BASE.TEMPLATE
WRITE_GOLDENS = BASE.WRITE_GOLDENS
BINARY = "/opt/metrics-httpd/0.1.0/metrics-httpd"

FIXTURES = ROOT / "rust/metrics-httpd/fixtures"

# Per role: the task file holding the block with the switch inputs, the
# block's name, the file holding select, the unit template, the handlers.
ROLES = {
    "logyard_deploy": {
        "block_file": "health_endpoint.yml",
        "block": "health_endpoint | Deploy the Logyard health endpoint",
        "select_file": "health_endpoint.yml",
        "unit": "logyard-health-endpoint.service.j2",
        "impl": "logyard_health_impl",
        "notify": ["reload systemd", "restart logyard health endpoint"],
        "expect": "logyard-health",
        "prepare": "health_endpoint | Read the unit's environment for the implementation check",
    },
    "static_site_deploy": {
        "block_file": "main.yml",
        "block": "main | Serve, route and verify the static site",
        "select_file": "service.yml",
        "unit": "static-site.service.j2",
        "impl": "static_site_impl",
        "notify": ["static site | Reload systemd", "static site | Restart static site"],
        "expect": "static",
        "prepare": None,
    },
}

# Unit lines that are not sandbox: identity, the command and the restart
# policy (User=/Group= reach systemd-run as validate_user/validate_group).
NOT_SANDBOX = ("Type", "User", "Group", "ExecStart", "Restart", "RestartSec")

# Inputs that make the logyard render exercise the quoting of the unit:
# a selector with double quotes, a non-empty unit list.
LOGYARD_RENDER_VARS = {
    "logyard_health_selector": '{host="macmini",source_type="journald"}',
    "logyard_health_units": [{"id": "vector", "unit": "vector.service"}],
}


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def role_defaults(role: str) -> dict:
    return load_yaml(ROOT / "roles" / role / "defaults/main.yml")


def switch_block(role: str) -> dict:
    spec = ROLES[role]
    tasks = load_yaml(ROOT / "roles" / role / "tasks" / spec["block_file"])
    blocks = [t for t in tasks if t.get("name") == spec["block"]]
    assert len(blocks) == 1, role
    return blocks[0]


def prepare_tasks(role: str) -> list[dict]:
    """The role's own tasks that compute switch inputs before select (run
    unchanged in the test plays; their template lookups resolve against a
    ``templates`` link next to the test playbook)."""

    name = ROLES[role]["prepare"]
    if name is None:
        return []
    tasks = [t for t in switch_block(role)["block"] if t.get("name") == name]
    assert len(tasks) == 1, role
    return tasks


def link_templates(directory: Path) -> None:
    """Template lookups of a play resolve in ``<playbook dir>/templates``."""

    link = directory / "templates"
    if not link.exists():
        link.symlink_to(ROOT / "roles/logyard_deploy/templates")


def service_lines(unit: str) -> list[str]:
    """The [Service] lines of a rendered unit (no comments, no blanks)."""

    lines, section = [], None
    for line in unit.splitlines():
        if line.startswith("[") and line.endswith("]"):
            section = line
            continue
        if section == "[Service]" and line and not line.startswith("#"):
            lines.append(line)
    return lines


def systemd_unquote(value: str) -> list[str]:
    """systemd's extract_first_word(EXTRACT_UNQUOTE|EXTRACT_CUNESCAPE) for the
    subset the units use: words split on white space, double quotes group,
    a backslash escapes the next character. Environment= in a unit file and
    systemd-run --property=Environment= both parse the value this way."""

    words, word, quoted, started, escaped = [], [], False, False, False
    for char in value:
        if escaped:
            word.append(char)
            escaped = False
        elif char == "\\":
            escaped, started = True, True
        elif char == '"':
            quoted, started = not quoted, True
        elif char in " \t" and not quoted:
            if started:
                words.append("".join(word))
                word, started = [], False
        else:
            word.append(char)
            started = True
    assert not quoted and not escaped, value
    if started:
        words.append("".join(word))
    return words


def environment(sandbox: list[str]) -> dict[str, str]:
    """The process environment the Environment= properties give."""

    env = {}
    for entry in sandbox:
        if entry.startswith("Environment="):
            for word in systemd_unquote(entry[len("Environment="):]):
                key, _, value = word.partition("=")
                env[key] = value
    return env


# --------------------------------------------------------------------------
# Static checks
# --------------------------------------------------------------------------


class RoleStaticTests(unittest.TestCase):
    def test_impl_default_follows_the_fleet_variable(self):
        for role, spec in ROLES.items():
            self.assertEqual(role_defaults(role)[spec["impl"]], "{{ metrics_httpd_impl | default('python') }}", role)

    def test_switch_inputs_come_from_the_role(self):
        expected = {
            "logyard_deploy": {
                "metrics_httpd_switch_impl": "{{ logyard_health_impl }}",
                "metrics_httpd_switch_service_name": "{{ logyard_health_service_name }}",
                "metrics_httpd_switch_validate_user": "{{ logyard_user }}",
                "metrics_httpd_switch_validate_group": "{{ logyard_group }}",
                "metrics_httpd_switch_argv": ["logyard-health"],
                "metrics_httpd_switch_python_script": "{{ logyard_health_script_path }}",
                "metrics_httpd_switch_probe_bind": "{{ logyard_health_bind_host }}",
                "metrics_httpd_switch_probe_port": "{{ logyard_health_port }}",
                "metrics_httpd_switch_probe_path": "{{ logyard_health_path }}",
            },
            "static_site_deploy": {
                "metrics_httpd_switch_impl": "{{ static_site_impl }}",
                "metrics_httpd_switch_service_name": "{{ static_site_systemd_unit_name }}",
                "metrics_httpd_switch_validate_user": "{{ static_site_user }}",
                "metrics_httpd_switch_validate_group": "{{ static_site_group }}",
                "metrics_httpd_switch_python_script": "{{ static_site_server_path }}",
                "metrics_httpd_switch_probe_bind": "{{ static_site_bind_host }}",
                "metrics_httpd_switch_probe_port": "{{ static_site_port }}",
                "metrics_httpd_switch_probe_path": "/",
            },
        }
        for role, spec in ROLES.items():
            variables = switch_block(role)["vars"]
            for key, value in expected[role].items():
                self.assertEqual(variables[key], value, (role, key))
            self.assertEqual(variables["metrics_httpd_switch_notify"], spec["notify"], role)
            self.assertEqual(variables["metrics_httpd_switch_probe_expect"], spec["expect"], role)
            self.assertNotIn("metrics_httpd_switch_probe_realm", variables, role)
            if role == "logyard_deploy":
                timeout = variables["metrics_httpd_switch_probe_timeout"]
                for name in ("logyard_health_timeout_seconds", "logyard_health_systemctl_timeout_seconds",
                             "logyard_health_units"):
                    self.assertIn(name, timeout)
            else:
                self.assertNotIn("metrics_httpd_switch_probe_timeout", variables, role)
            # Neither unit has an IP filter: the probe always runs.
            self.assertEqual(variables["metrics_httpd_switch_ip_address_allow"], ["any"], role)
            unit = (ROOT / "roles" / role / "templates" / spec["unit"]).read_text(encoding="utf-8")
            self.assertNotIn("IPAddressAllow", unit, role)
            self.assertNotIn("IPAddressDeny", unit, role)
            # The release comes from the fleet variables, never from the role.
            for key in ("version", "sha256", "local_archive", "install_root"):
                self.assertNotIn(f"metrics_httpd_switch_{key}", variables, role)

    def test_notified_handlers_exist(self):
        for role, spec in ROLES.items():
            handlers = {h["name"] for h in load_yaml(ROOT / "roles" / role / "handlers/main.yml")}
            self.assertLessEqual(set(spec["notify"]), handlers, role)

    def _include(self, task: dict, tasks_from: str, role: str) -> None:
        self.assertEqual(task["ansible.builtin.include_role"], {"name": FQCN, "tasks_from": tasks_from}, role)
        self.assertNotIn("vars", task, role)
        self.assertNotIn("when", task, role)

    def test_logyard_select_and_verify_are_placed_around_the_start(self):
        tasks = switch_block("logyard_deploy")["block"]
        names = [t["name"] for t in tasks]
        self.assertEqual(
            names,
            [
                "health_endpoint | Render Logyard health endpoint script",
                "health_endpoint | Render Logyard health endpoint systemd unit",
                "health_endpoint | Read the unit's environment for the implementation check",
                "health_endpoint | Select the HTTP server implementation",
                "health_endpoint | Ensure Logyard health endpoint is enabled and started",
                "health_endpoint | Apply a pending implementation switch before verifying it",
                "health_endpoint | Verify the HTTP server implementation",
            ],
        )
        self._include(tasks[3], "select", "logyard_deploy")
        self.assertEqual(tasks[5]["ansible.builtin.meta"], "flush_handlers")
        self._include(tasks[6], "verify", "logyard_deploy")
        # The sandbox is the rendered unit's Environment= lines (set_fact on
        # the controller, also in check mode), not a hand-kept copy.
        self.assertEqual(
            switch_block("logyard_deploy")["vars"]["metrics_httpd_switch_unit_sandbox"],
            "{{ _logyard_health_unit_environment }}",
        )
        prepare = tasks[2]["ansible.builtin.set_fact"]["_logyard_health_unit_environment"]
        self.assertIn("lookup('ansible.builtin.template', 'logyard-health-endpoint.service.j2')", prepare)
        self.assertNotIn("check_mode", tasks[2])
        # The whole file is the block; main.yml imports it for an enabled endpoint.
        self.assertEqual(len(load_yaml(ROOT / "roles/logyard_deploy/tasks/health_endpoint.yml")), 1)
        main = load_yaml(ROOT / "roles/logyard_deploy/tasks/main.yml")
        imports = [t for t in main if t.get("ansible.builtin.import_tasks") == "health_endpoint.yml"]
        self.assertEqual(len(imports), 1)
        self.assertEqual(imports[0]["when"], "logyard_health_enabled | bool")

    def test_static_select_and_verify_are_placed_around_the_start(self):
        service = load_yaml(ROOT / "roles/static_site_deploy/tasks/service.yml")
        names = [t["name"] for t in service]
        self.assertEqual(
            names,
            [
                "service | Install static HTTP server",
                "service | Install static site systemd unit",
                "service | Select the HTTP server implementation",
                "service | Enable and start static site service",
            ],
        )
        self._include(service[2], "select", "static_site_deploy")
        block = switch_block("static_site_deploy")["block"]
        self.assertEqual(
            [t["name"] for t in block],
            [
                "main | Configure static content service",
                "main | Configure Traefik route",
                "main | Apply service handlers before verification",
                "main | Verify the HTTP server implementation",
                "main | Verify local and public serving paths",
            ],
        )
        self.assertEqual(block[0]["ansible.builtin.include_tasks"], "service.yml")
        self.assertEqual(block[2]["ansible.builtin.meta"], "flush_handlers")
        self._include(block[3], "verify", "static_site_deploy")
        self.assertEqual(block[4]["ansible.builtin.include_tasks"], "verify.yml")
        # --check-config needs the published document root: content comes first.
        main = [t["name"] for t in load_yaml(ROOT / "roles/static_site_deploy/tasks/main.yml")]
        self.assertLess(main.index("main | Publish generated site content"), main.index(ROLES["static_site_deploy"]["block"]))

    def test_task_names_carry_the_file_prefix(self):
        files = {
            "logyard_deploy": ["health_endpoint.yml"],
            "static_site_deploy": ["main.yml", "service.yml"],
        }
        for role, names in files.items():
            for name in names:
                for task in BASE.walk(load_yaml(ROOT / "roles" / role / "tasks" / name)):
                    prefix = name.removesuffix(".yml") + " | "
                    self.assertTrue(str(task.get("name", "")).startswith(prefix), (role, name, task.get("name")))

    def test_static_unit_name_is_a_pin_name(self):
        # The unit name is also the switch's pin consumer name: validate.yml
        # refuses what rust_release_consumer_ok would refuse later.
        validate = (ROOT / "roles/static_site_deploy/tasks/validate.yml").read_text(encoding="utf-8")
        self.assertIn("static_site_systemd_unit_name is match('^[a-z][a-z0-9_-]{1,62}\\Z')", validate)
        rust_release = _load("rust_release_filters", ROOT / "plugins/filter/rust_release.py")
        pattern = re.compile(r"^[a-z][a-z0-9_-]{1,62}\Z")
        for name in ("benchmarks-static", "static_site", "a1", "static.site", "Static", "-x"):
            if pattern.match(name):
                self.assertTrue(rust_release.rust_release_consumer_ok(name), name)
        self.assertIsNone(pattern.match("static.site"))


# --------------------------------------------------------------------------
# The roles' inputs rendered by Ansible from their defaults
# --------------------------------------------------------------------------


def render_play(role: str, out: Path, overrides: dict) -> dict:
    spec = ROLES[role]
    variables = {**role_defaults(role), **overrides}
    return {
        "name": role,
        "hosts": "localhost",
        "gather_facts": False,
        "vars": variables,
        "tasks": [
            {
                "name": "render",
                "vars": switch_block(role)["vars"],
                "block": [
                    *prepare_tasks(role),
                    {"ansible.builtin.file": {"path": str(out), "state": "directory", "mode": "0755"}},
                    {"ansible.builtin.set_fact": {"_argv": "{{ metrics_httpd_switch_argv | map('string') | list }}"}},
                    {
                        "ansible.builtin.copy": {
                            "dest": str(out / "switch.json"),
                            "mode": "0644",
                            "content": (
                                "{{ {'argv': _argv,"
                                " 'impl': metrics_httpd_switch_impl,"
                                " 'service': metrics_httpd_switch_service_name,"
                                " 'user': metrics_httpd_switch_validate_user,"
                                " 'group': metrics_httpd_switch_validate_group,"
                                " 'sandbox': metrics_httpd_switch_unit_sandbox,"
                                " 'notify': metrics_httpd_switch_notify,"
                                " 'python_script': metrics_httpd_switch_python_script,"
                                " 'probe': [metrics_httpd_switch_probe_bind,"
                                "           metrics_httpd_switch_probe_port | string,"
                                "           metrics_httpd_switch_probe_path,"
                                "           metrics_httpd_switch_probe_expect,"
                                "           metrics_httpd_switch_probe_timeout | default('switch default') | string],"
                                " 'allow': metrics_httpd_switch_ip_address_allow,"
                                " 'argv_problems': metrics_httpd_switch_argv"
                                "   | local.ops_library.metrics_httpd_argv_problems,"
                                " 'sandbox_problems': metrics_httpd_switch_unit_sandbox"
                                "   | local.ops_library.metrics_httpd_sandbox_problems} | to_json }}"
                            ),
                        }
                    },
                    {
                        "ansible.builtin.template": {
                            "src": str(TEMPLATE),
                            "dest": str(out / "metrics-httpd-impl.conf"),
                            "mode": "0644",
                        },
                        "vars": {"metrics_httpd_impl_binary": BINARY, "metrics_httpd_impl_argv": "{{ _argv }}"},
                    },
                    {
                        "ansible.builtin.template": {
                            "src": str(ROOT / "roles" / role / "templates" / spec["unit"]),
                            "dest": str(out / spec["unit"].removesuffix(".j2")),
                            "mode": "0644",
                        }
                    },
                ],
            }
        ],
    }


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not on PATH")
class RoleRenderTests(unittest.TestCase):
    """Goldens use the defaults (logyard: plus LOGYARD_RENDER_VARS); the
    ``*-defaults`` renders use the role defaults alone."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        base = Path(cls._tmp.name)
        cls.out = base / "out"
        env = BASE.ansible_env(base, [])
        plays = [
            render_play("logyard_deploy", cls.out / "logyard_deploy", LOGYARD_RENDER_VARS),
            render_play("logyard_deploy", cls.out / "logyard_deploy-defaults", {}),
            render_play("static_site_deploy", cls.out / "static_site_deploy", {}),
        ]
        path = base / "render.yml"
        path.write_text(yaml.safe_dump(plays, sort_keys=False), encoding="utf-8")
        link_templates(base)
        cls.result = BASE.run_playbook(path, env)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.assertEqual(self.result["rc"], 0, self.result["out"])

    def switch(self, name: str) -> dict:
        return json.loads((self.out / name / "switch.json").read_text())

    def unit(self, name: str) -> str:
        role = name.removesuffix("-defaults")
        return (self.out / name / ROLES[role]["unit"].removesuffix(".j2")).read_text()

    def test_plan_argv_per_role(self):
        # PLAN.md 7.3 with the role defaults.
        self.assertEqual(self.switch("logyard_deploy")["argv"], ["logyard-health"])
        self.assertEqual(
            self.switch("static_site_deploy")["argv"],
            ["static", "--bind", "127.0.0.1", "--port", "10061", "--root", "/srv/static-sites/static-site"],
        )
        for name in ("logyard_deploy", "logyard_deploy-defaults", "static_site_deploy"):
            switch = self.switch(name)
            self.assertEqual(switch["argv_problems"], [], name)
            self.assertEqual(switch["sandbox_problems"], [], name)
            self.assertEqual(switch["impl"], "python", name)

    def test_argv_matches_the_rust_fixtures(self):
        # The parity harness adds --bind/--port to the static fixture argv.
        static = json.loads((FIXTURES / "static.json").read_text())
        argv = self.switch("static_site_deploy")["argv"]
        self.assertEqual(argv[:5], ["static", "--bind", "127.0.0.1", "--port", "10061"])
        self.assertEqual(["static"] + [{argv[-1]: "{root}"}.get(a, a) for a in argv[5:]], static["argv"])
        # logyard-health takes no flags: everything comes from the environment,
        # with the variable names of the fixture's cases.
        logyard = json.loads((FIXTURES / "logyard_health.json").read_text())
        names = {name for case in logyard["http"]["cases"] for name in case.get("env", {})}
        self.assertEqual(set(environment(self.switch("logyard_deploy")["sandbox"])), names)

    def test_identity_and_probe(self):
        logyard = self.switch("logyard_deploy-defaults")
        self.assertEqual(logyard["service"], "logyard-health-endpoint")
        self.assertEqual((logyard["user"], logyard["group"]), ("logyard", "logyard"))
        self.assertEqual(logyard["python_script"], "/usr/local/bin/logyard_health_httpd.py")
        # Three Loki requests of 10 s, no listed unit, 5 s spare.
        self.assertEqual(logyard["probe"], ["127.0.0.1", "9105", "/.well-known/logyard", "logyard-health", "35"])
        # One listed unit adds one systemctl timeout (5 s).
        self.assertEqual(self.switch("logyard_deploy")["probe"][4], "40")
        static = self.switch("static_site_deploy")
        self.assertEqual(static["service"], "static-site")
        self.assertEqual((static["user"], static["group"]), ("static-site", "static-site"))
        self.assertEqual(static["python_script"], "/usr/local/libexec/static-site-httpd.py")
        self.assertEqual(static["probe"], ["127.0.0.1", "10061", "/", "static", "switch default"])
        self.assertEqual(load_yaml(ROOT / "roles/metrics_httpd_switch/defaults/main.yml")["metrics_httpd_switch_probe_timeout"], 5)
        for switch in (logyard, static):
            self.assertTrue(FILTERS.metrics_httpd_probe_covered(switch["probe"][0], switch["allow"]))

    def test_sandbox_is_the_units_own_service_lines(self):
        for name in ("logyard_deploy", "logyard_deploy-defaults", "static_site_deploy"):
            lines = service_lines(self.unit(name))
            identity = {line.split("=", 1)[0] for line in lines} & set(NOT_SANDBOX)
            self.assertEqual(identity, set(NOT_SANDBOX), name)
            expected = [line for line in lines if line.split("=", 1)[0] not in NOT_SANDBOX]
            self.assertEqual(self.switch(name)["sandbox"], expected, name)
        # The static unit's hardening the binary must run under (PLAN.md 4.8).
        static = self.switch("static_site_deploy")["sandbox"]
        for line in ("MemoryDenyWriteExecute=true", "RestrictAddressFamilies=AF_UNIX AF_INET", "ProtectSystem=strict",
                     "ReadOnlyPaths=/srv/static-sites/static-site"):
            self.assertIn(line, static)

    def test_logyard_environment_reaches_check_config_unchanged(self):
        sandbox = self.switch("logyard_deploy")["sandbox"]
        env = environment(sandbox)
        self.assertEqual(env["LOGYARD_HEALTH_SELECTOR"], '{host="macmini",source_type="journald"}')
        self.assertEqual(json.loads(base64.b64decode(env["LOGYARD_HEALTH_UNITS_B64"], validate=True)),
                         LOGYARD_RENDER_VARS["logyard_health_units"])
        self.assertEqual(env["LOGYARD_LOKI_URL"], "http://127.0.0.1:3101")
        self.assertEqual(env["LOGYARD_HEALTH_PORT"], "9105")
        defaults = environment(self.switch("logyard_deploy-defaults")["sandbox"])
        self.assertEqual(json.loads(base64.b64decode(defaults["LOGYARD_HEALTH_UNITS_B64"], validate=True)), [])

    def test_dropin_and_unit_goldens(self):
        for name in ("logyard_deploy", "static_site_deploy"):
            for file_name in ("metrics-httpd-impl.conf", ROLES[name]["unit"].removesuffix(".j2")):
                rendered = (self.out / name / file_name).read_text()
                golden = GOLDENS / name / file_name
                if WRITE_GOLDENS:
                    golden.parent.mkdir(parents=True, exist_ok=True)
                    golden.write_text(rendered)
                self.assertEqual(rendered, golden.read_text(), f"{name}/{file_name}")

    def test_dropin_execstart_is_the_argv(self):
        for name in ("logyard_deploy", "static_site_deploy"):
            argv = self.switch(name)["argv"]
            dropin = (self.out / name / "metrics-httpd-impl.conf").read_text()
            self.assertEqual(BASE.exec_start(dropin), [BINARY] + argv)
            # ops-deploy renders the vendored template byte-identically (PLAN.md 7.4).
            self.assertEqual(dropin, BASE.render_vendored(BINARY, argv))

    def test_python_unit_still_runs_the_script(self):
        self.assertIn("ExecStart=/usr/bin/python3 /usr/local/bin/logyard_health_httpd.py\n", self.unit("logyard_deploy"))
        self.assertIn("ExecStart=/usr/bin/python3 /usr/local/libexec/static-site-httpd.py\n", self.unit("static_site_deploy"))
        for name in ("logyard_deploy", "static_site_deploy"):
            self.assertNotIn("metrics-httpd", self.unit(name))

    @unittest.skipUnless(os.environ.get("METRICS_HTTPD_BIN"), "METRICS_HTTPD_BIN (a built metrics-httpd) not set")
    def test_binary_accepts_the_rendered_inputs(self):
        binary = os.environ["METRICS_HTTPD_BIN"]
        for name in ("logyard_deploy", "logyard_deploy-defaults"):
            env = {"PATH": os.environ.get("PATH", ""), **environment(self.switch(name)["sandbox"])}
            result = subprocess.run([binary, *self.switch(name)["argv"], "--check-config"],
                                    capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
        # A unit entry the payload would reject stops the switch to Rust.
        env = {**environment(self.switch("logyard_deploy")["sandbox"]),
               "LOGYARD_HEALTH_UNITS_B64": base64.b64encode(b'[{"id": "a.b", "unit": "x.service"}]').decode()}
        result = subprocess.run([binary, "logyard-health", "--check-config"], capture_output=True, text=True,
                                env=env, timeout=30)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("id_contains_dot", result.stderr)
        with tempfile.TemporaryDirectory() as site:
            argv = self.switch("static_site_deploy")["argv"]
            result = subprocess.run([binary, *argv[:-1], site, "--check-config"], capture_output=True, text=True,
                                    timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([binary, *argv[:-1], site + "/missing", "--check-config"], capture_output=True,
                                    text=True, timeout=30)
            self.assertEqual(result.returncode, 2, result.stdout)


# --------------------------------------------------------------------------
# The roles' inputs through select, flush and verify on localhost
# --------------------------------------------------------------------------

# Like the base fake, but one argument per line (a property may hold a space).
FAKE_SYSTEMD_RUN = """#!/bin/sh
for arg in "$@"; do printf '%s\\n' "$arg"; done > "$FAKE_SYSTEMD_DIR/systemd-run.args"
printf '%s\\n' "$*" >> "$FAKE_SYSTEMD_DIR/systemd-run.log"
while [ $# -gt 0 ]; do
  case "$1" in --*) shift ;; *) break ;; esac
done
exec "$@"
"""


class EndpointHandler(http.server.BaseHTTPRequestHandler):
    """200 with the logyard payload shape for every GET (no auth)."""

    requests: list[dict] = []
    body = b'{"status": "ok", "loki": {"ready": true}}'
    delay = 0.0

    def do_GET(self):  # noqa: N802 - http.server API
        type(self).requests.append({"path": self.path, "authorization": self.headers.get("Authorization")})
        time.sleep(type(self).delay)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(type(self).body)))
        self.end_headers()
        self.wfile.write(type(self).body)

    def log_message(self, *args):  # silence
        pass


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not on PATH")
@unittest.skipUnless(shutil.which("realpath"), "realpath not on PATH")
class RoleSwitchPlaybookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name)
        fakes = cls.base / "fake-bin"
        fakes.mkdir()
        for name, text in (("systemd-run", FAKE_SYSTEMD_RUN), ("systemctl", BASE.FAKE_SYSTEMCTL)):
            (fakes / name).write_text(text)
            (fakes / name).chmod(0o755)
        (cls.base / "fake_restart.py").write_text(BASE.FAKE_RESTART)
        shim = BASE._gnu_mv_dir(cls.base)
        cls.env_base = BASE.ansible_env(cls.base, [fakes] + ([shim] if shim else []))
        cls.owner = BASE.pwd.getpwuid(os.getuid()).pw_name
        cls.group = BASE.grp.getgrgid(os.getgid()).gr_name
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), EndpointHandler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.archive = cls.base / "metrics-httpd-0.1.0.tar.gz"
        cls.sha256 = BASE.build_archive(cls.archive, "0.1.0")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls._tmp.cleanup()

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(dir=self.base))
        self.state = self.work / "state"
        self.systemd = self.work / "systemd"
        self.proc = self.work / "proc"
        for path in (self.state, self.systemd, self.proc):
            path.mkdir()
        self.root = self.work / "opt/metrics-httpd"
        self.log = self.work / "handlers.log"
        self.env = {**self.env_base, "FAKE_SYSTEMD_DIR": str(self.state)}
        self.runs = 0
        EndpointHandler.requests, EndpointHandler.delay = [], 0.0

    def role_vars(self, role: str) -> dict:
        overrides = {
            "logyard_deploy": {**LOGYARD_RENDER_VARS, "logyard_health_port": self.port},
            "static_site_deploy": {"static_site_port": self.port, "static_site_service_name": "benchmarks-static"},
        }[role]
        return {**role_defaults(role), **overrides}

    def restart_argv(self, unit: str, script: str) -> list[str]:
        return [sys.executable, str(self.base / "fake_restart.py"), str(self.systemd), unit, str(self.proc),
                str(self.state), script, str(self.log)]

    def play(self, role: str, fleet_impl: str, version: str = "", *, expect_ok: bool = True, **overrides) -> dict:
        self.runs += 1
        spec = ROLES[role]
        variables = {**self.role_vars(role), **overrides}
        unit = {"logyard_deploy": "logyard-health-endpoint", "static_site_deploy": "benchmarks-static"}[role]
        script = {"logyard_deploy": "/usr/local/bin/logyard_health_httpd.py",
                  "static_site_deploy": "/usr/local/libexec/benchmarks-static-httpd.py"}[role]
        if self.runs == 1:
            subprocess.run(self.restart_argv(unit, script), check=True)
            self.log.write_text("")
        variables.update(
            {
                # Fleet variables (PLAN.md 7.1): the role's impl follows them.
                "metrics_httpd_impl": fleet_impl,
                "metrics_httpd_rust_version": version,
                "metrics_httpd_rust_sha256": self.sha256 if version else "",
                "metrics_httpd_rust_local_archive": str(self.archive) if version else "",
                # Test-only knobs of the switch.
                "metrics_httpd_switch_install_root": str(self.root),
                "metrics_httpd_switch_version_check_user": "",
                "metrics_httpd_switch_verify_retries": 2,
                "metrics_httpd_switch_verify_delay": 0,
                "metrics_httpd_switch_systemd_dir": str(self.systemd),
                "metrics_httpd_switch_proc_root": str(self.proc),
                "metrics_httpd_switch_owner": self.owner,
                "metrics_httpd_switch_group": self.group,
            }
        )
        facts = self.work / f"facts-{self.runs}.json"
        play = {
            "hosts": "localhost",
            "gather_facts": False,
            "vars": variables,
            "tasks": [
                {
                    "name": "switch",
                    "vars": switch_block(role)["vars"],
                    "block": [
                        *prepare_tasks(role),
                        {"name": "select", "ansible.builtin.include_role": {"name": FQCN, "tasks_from": "select"}},
                        {"name": "flush", "ansible.builtin.meta": "flush_handlers"},
                        {"name": "verify", "ansible.builtin.include_role": {"name": FQCN, "tasks_from": "verify"}},
                        {
                            "name": "dump facts",
                            "ansible.builtin.copy": {
                                "dest": str(facts),
                                "mode": "0644",
                                "content": "{{ {'selected': _metrics_httpd_switch_selected | default(None)} | to_json }}",
                            },
                            "changed_when": False,
                        },
                    ],
                }
            ],
            "handlers": [
                {
                    "name": spec["notify"][0],
                    "ansible.builtin.command": {"argv": ["sh", "-c", f"echo reload >> {self.log}"]},
                    "changed_when": True,
                },
                {
                    "name": spec["notify"][1],
                    "ansible.builtin.command": {"argv": self.restart_argv(unit, script)},
                    "changed_when": True,
                },
            ],
        }
        path = self.work / f"play-{self.runs}.yml"
        path.write_text(yaml.safe_dump([play], sort_keys=False), encoding="utf-8")
        link_templates(self.work)
        result = BASE.run_playbook(path, self.env)
        if not expect_ok:
            self.assertNotEqual(result["rc"], 0, result["out"])
            return result
        self.assertEqual(result["rc"], 0, result["out"])
        result["facts"] = json.loads(facts.read_text())
        result["handlers"] = self.log.read_text().splitlines() if self.log.exists() else []
        self.log.write_text("")
        result["unit"], result["script"] = unit, script
        return result

    def dropin(self, unit: str) -> Path:
        return self.systemd / f"{unit}.service.d/metrics-httpd-impl.conf"

    def pins(self) -> dict[str, str]:
        pins = self.root / ".pins"
        return {p.name: p.read_text() for p in sorted(pins.iterdir())} if pins.exists() else {}

    def roundtrip(self, role: str, argv: list[str], sandbox: list[str], user: str, probe_path: str) -> None:
        python = self.play(role, "python")
        unit = python["unit"]
        self.assertEqual(python["recap"]["changed"], 0, python["out"])
        self.assertEqual(python["handlers"], [])
        self.assertFalse(self.dropin(unit).exists())
        self.assertEqual(EndpointHandler.requests, [{"path": probe_path, "authorization": None}])

        rust = self.play(role, "rust", "0.1.0")
        binary = f"{self.root}/0.1.0/metrics-httpd"
        self.assertEqual(rust["handlers"], ["reload", f"restart {binary}"], rust["out"])
        self.assertEqual(BASE.exec_start(self.dropin(unit).read_text()), [binary] + argv)
        self.assertEqual(self.pins(), {unit: "0.1.0\n"})
        self.assertEqual(rust["facts"]["selected"]["impl"], "rust")
        # --check-config ran as the unit's user with exactly the unit's sandbox.
        args = (self.state / "systemd-run.args").read_text().splitlines()
        self.assertEqual(
            args,
            ["--wait", "--pipe", "--collect", "--quiet", f"--property=User={user}", f"--property=Group={user}"]
            + [f"--property={entry}" for entry in sandbox]
            + [binary] + argv + ["--check-config"],
        )
        self.assertEqual((self.state / "check-config.argv").read_text().splitlines(), argv + ["--check-config"])
        self.assertEqual(EndpointHandler.requests[-1], {"path": probe_path, "authorization": None})

        back = self.play(role, "python", "0.1.0")
        self.assertEqual(back["handlers"], ["reload", "restart /usr/bin/python3.12"], back["out"])
        self.assertFalse(self.dropin(unit).exists())
        self.assertEqual(self.pins(), {f"{unit}.previous": "0.1.0\n"})
        self.assertEqual(back["recap"]["ignored"], 0, back["out"])

    def test_logyard_health_endpoint(self):
        variables = self.role_vars("logyard_deploy")
        sandbox = [
            "Environment=LOGYARD_HEALTH_BIND=127.0.0.1",
            f"Environment=LOGYARD_HEALTH_PORT={self.port}",
            "Environment=LOGYARD_HEALTH_PATH=/.well-known/logyard",
            "Environment=LOGYARD_LOKI_URL=http://127.0.0.1:3101",
            'Environment="LOGYARD_HEALTH_SELECTOR={host=\\"macmini\\",source_type=\\"journald\\"}"',
            "Environment=LOGYARD_WARNING_WINDOW_SECONDS=900",
            "Environment=LOGYARD_CRITICAL_WINDOW_SECONDS=3600",
            "Environment=LOGYARD_REQUEST_TIMEOUT_SECONDS=10",
            "Environment=LOGYARD_HEALTH_SYSTEMCTL_TIMEOUT_SECONDS=5",
            "Environment=LOGYARD_HEALTH_UNITS_B64="
            + base64.b64encode(json.dumps(variables["logyard_health_units"]).encode()).decode(),
        ]
        self.roundtrip("logyard_deploy", ["logyard-health"], sandbox, "logyard", "/.well-known/logyard")

    def test_static_site(self):
        root = "/srv/static-sites/benchmarks-static"
        argv = ["static", "--bind", "127.0.0.1", "--port", str(self.port), "--root", root]
        unit = (ROOT / "roles/static_site_deploy/templates/static-site.service.j2").read_text(encoding="utf-8")
        sandbox = [
            line.replace("{{ static_site_path }}", root)
            for line in service_lines(unit)
            if line.split("=", 1)[0] not in NOT_SANDBOX
        ]
        self.roundtrip("static_site_deploy", argv, sandbox, "benchmarks-static", "/")

    def test_logyard_probe_waits_for_a_slow_answer(self):
        # Python answers after its Loki requests; the probe waits for them
        # (default: 3 x 10 s + 5 s), not the switch's 5 s.
        EndpointHandler.delay = 6.0
        result = self.play("logyard_deploy", "python")
        self.assertEqual(EndpointHandler.requests, [{"path": "/.well-known/logyard", "authorization": None}])
        self.assertEqual(result["recap"]["failed"], 0, result["out"])
        # A probe timeout below the answer time fails the check (the knob is
        # used): no Loki timeout and no unit leave the 5 s spare.
        failed = self.play("logyard_deploy", "python", expect_ok=False, logyard_health_timeout_seconds=0,
                           logyard_health_units=[], metrics_httpd_switch_verify_retries=1)
        self.assertIn("verify | Assert the endpoint answers as expected", failed["out"])

    def test_logyard_host_name_bind_stays_deployable_with_python(self):
        result = self.play("logyard_deploy", "python", logyard_health_bind_host="localhost")
        self.assertIn("is not an IP address, so the address to probe is unknown", result["out"])
        self.assertEqual(EndpointHandler.requests, [])
        self.assertEqual(result["recap"]["failed"], 0, result["out"])

    def test_probe_timeout_must_be_whole_seconds(self):
        failed = self.play("static_site_deploy", "python", expect_ok=False, metrics_httpd_switch_probe_timeout=0)
        self.assertIn("verify | Assert select ran for this unit", failed["out"])


if __name__ == "__main__":
    unittest.main()
