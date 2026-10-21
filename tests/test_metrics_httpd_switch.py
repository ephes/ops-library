"""metrics_httpd_switch and the five *_metrics_endpoint consumer roles.

rust/metrics-httpd/PLAN.md 7.2/7.3 (slice S5a):

- unit tests of the checks in ``plugins/filter/metrics_httpd.py``;
- the drop-in template rendered as ops-deploy renders vendored templates
  (plain Jinja2, ``trim_blocks``), parsed back with systemd's word splitting;
- static checks of the consumer roles (where select and verify are included,
  handler names, sandbox and IP allow list mirroring the unit template);
- one ``ansible-playbook`` run rendering every consumer's argv, drop-in and
  base unit from its defaults: the argv equals the fixture argv of the
  json-file variant (``rust/metrics-httpd/fixtures/json_file.json``), the
  drop-in and the unchanged base unit equal the goldens in
  ``tests/fixtures/metrics_httpd_switch/`` (``impl: python`` renders exactly
  what the role rendered before the switch existed);
- ``ansible-playbook`` runs of select and verify against localhost with a
  fake release archive, fake ``systemd-run``/``systemctl``, a fake ``/proc``
  and a probe server: both directions of the switch, idempotence, pin moves
  and prune, refusals and the warn-and-continue paths, check mode.

Regenerate the goldens with ``METRICS_HTTPD_SWITCH_WRITE_GOLDENS=1``.
"""

from __future__ import annotations

import grp
import hashlib
import http.server
import importlib.util
import io
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path

import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/metrics_httpd_switch"
TEMPLATE = ROLE / "templates/metrics-httpd-impl.conf.j2"
GOLDENS = ROOT / "tests/fixtures/metrics_httpd_switch"
JSON_FILE_FIXTURE = ROOT / "rust/metrics-httpd/fixtures/json_file.json"
FQCN = "local.ops_library.metrics_httpd_switch"
WRITE_GOLDENS = os.environ.get("METRICS_HTTPD_SWITCH_WRITE_GOLDENS") == "1"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FILTERS = _load("metrics_httpd_filters", ROOT / "plugins/filter/metrics_httpd.py")

# Variant name in json_file.json for each consumer role.
CONSUMERS = {
    "backup_metrics_endpoint": "backup",
    "storage_metrics_endpoint": "storage",
    "thermal_metrics_endpoint": "thermal",
    "tailscale_metrics_endpoint": "tailscale",
    "dns_metrics_endpoint": "dns",
}


def walk(tasks):
    for task in tasks or []:
        yield task
        for section in ("block", "rescue", "always"):
            yield from walk(task.get(section, []))


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def systemd_split(line: str) -> list[str]:
    """Split an ExecStart= value like systemd's extract_first_word with
    EXTRACT_UNQUOTE|EXTRACT_CUNESCAPE for the characters the role allows (no
    backslash, no '%', no '$'): whitespace separates words, double and
    single quotes group them."""

    words, word, quote, started = [], [], None, False
    for char in line:
        if quote:
            if char == quote:
                quote = None
            else:
                word.append(char)
            continue
        if char in "\"'":
            quote, started = char, True
        elif char in " \t":
            if started:
                words.append("".join(word))
                word, started = [], False
        else:
            word.append(char)
            started = True
    assert quote is None, f"unterminated quote in {line!r}"
    if started:
        words.append("".join(word))
    return words


def render_vendored(binary: str, argv: list[str]) -> str:
    """The drop-in as ops-deploy renders vendored role templates (PLAN.md 7.4)."""

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATE.parent),
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        keep_trailing_newline=True,
    )
    return env.get_template(TEMPLATE.name).render(metrics_httpd_impl_binary=binary, metrics_httpd_impl_argv=argv)


def exec_start(dropin: str) -> list[str]:
    lines = [line for line in dropin.splitlines() if line.startswith("ExecStart=")]
    assert lines[0] == "ExecStart=", lines
    assert len(lines) == 2, lines
    return systemd_split(lines[1][len("ExecStart="):])


# --------------------------------------------------------------------------
# Filters
# --------------------------------------------------------------------------


class FilterTests(unittest.TestCase):
    def test_argv_accepts_a_role_command_line(self):
        argv = ["json-file", "--bind", "100.64.0.1", "--port", 9103, "--missing-message", "Status file not found - updater may not have run yet"]
        self.assertEqual(FILTERS.metrics_httpd_argv_problems(argv), [])
        self.assertEqual(FILTERS.metrics_httpd_argv_problems(["logyard-health"]), [])
        self.assertEqual(FILTERS.metrics_httpd_argv_problems(["static", "--root", "/srv/it's"]), [])

    def test_argv_refuses_what_systemd_would_interpret(self):
        for bad in ("50%", "$HOME", "${X}", 'a"b', "a\\b", "a\nb", "a\tb", "a\rb", "\x7f", ""):
            problems = FILTERS.metrics_httpd_argv_problems(["json-file", "--realm", bad])
            self.assertEqual(len(problems), 1, (bad, problems))
            self.assertIn("argv[2]", problems[0])

    def test_argv_refuses_wrong_shapes(self):
        self.assertTrue(FILTERS.metrics_httpd_argv_problems([]))
        self.assertTrue(FILTERS.metrics_httpd_argv_problems("json-file --bind x"))
        self.assertTrue(FILTERS.metrics_httpd_argv_problems(None))
        self.assertTrue(FILTERS.metrics_httpd_argv_problems(["serve"]))
        self.assertTrue(FILTERS.metrics_httpd_argv_problems(["json-file", True]))
        self.assertTrue(FILTERS.metrics_httpd_argv_problems(["json-file", None]))
        self.assertTrue(FILTERS.metrics_httpd_argv_problems(["json-file", ["x"]]))
        self.assertTrue(FILTERS.metrics_httpd_argv_problems(["json-file", "--check-config"]))

    def test_sandbox_properties(self):
        good = ["NoNewPrivileges=yes", "ProtectSystem=strict", "ReadOnlyPaths=/var/lib/x", "Environment=A=b c"]
        self.assertEqual(FILTERS.metrics_httpd_sandbox_problems(good), [])
        for bad in (["noNewPrivileges=yes"], ["ProtectSystem"], ["A=b\nc"], ["User=root"], ["Group=root"], [1], "X=y"):
            self.assertTrue(FILTERS.metrics_httpd_sandbox_problems(bad), bad)

    def test_probe_host(self):
        self.assertEqual(FILTERS.metrics_httpd_probe_host("100.64.0.1"), "100.64.0.1")
        self.assertEqual(FILTERS.metrics_httpd_probe_host("fd7a:115c:a1e0::1"), "[fd7a:115c:a1e0::1]")
        self.assertEqual(FILTERS.metrics_httpd_probe_host("0.0.0.0"), "127.0.0.1")
        self.assertEqual(FILTERS.metrics_httpd_probe_host("::"), "[::1]")
        with self.assertRaises(ValueError):
            FILTERS.metrics_httpd_probe_host("localhost")

    def test_probe_coverage_follows_ipaddressallow(self):
        covered = FILTERS.metrics_httpd_probe_covered
        units = ["localhost", "100.64.0.0/10"]
        self.assertTrue(covered("100.101.102.103", units))
        self.assertTrue(covered("127.0.0.1", units))
        self.assertTrue(covered("0.0.0.0", units))  # probed on 127.0.0.1
        self.assertFalse(covered("192.168.178.20", units))
        self.assertFalse(covered("fd7a:115c:a1e0::1", units))
        self.assertTrue(covered("fd7a:115c:a1e0::1", units + ["fd7a:115c:a1e0::/48"]))
        self.assertTrue(covered("::1", ["localhost"]))
        self.assertTrue(covered("192.168.178.20", ["any"]))
        self.assertTrue(covered("192.168.178.20", ["10.0.0.0/8 192.168.178.0/24"]))
        self.assertTrue(covered("169.254.1.1", ["link-local"]))
        self.assertTrue(covered("192.168.178.20", ["192.168.178.20"]))
        self.assertFalse(covered("192.168.178.20", []))
        self.assertFalse(covered("192.168.178.20", ["bogus", "10.0.0.0/8"]))
        self.assertTrue(covered("10.1.2.3", ["bogus", "10.0.0.0/8"]))
        self.assertFalse(covered("not-an-ip", ["any"]))
        self.assertFalse(covered("10.1.2.3", "10.0.0.0/8"))


# --------------------------------------------------------------------------
# The drop-in template
# --------------------------------------------------------------------------


class TemplateTests(unittest.TestCase):
    BINARY = "/opt/metrics-httpd/0.1.0/metrics-httpd"

    def test_layout(self):
        text = render_vendored(self.BINARY, ["json-file", "--bind", "100.64.0.1", "--port", "9103"])
        self.assertEqual(
            text,
            "# Managed by ops-library metrics_httpd_switch: selects the Rust metrics-httpd.\n"
            "# Remove this file (daemon-reload, restart) to fall back to Python.\n"
            "[Service]\n"
            "ExecStart=\n"
            "ExecStart=/opt/metrics-httpd/0.1.0/metrics-httpd json-file --bind 100.64.0.1 --port 9103\n",
        )

    def test_words_survive_systemd_splitting(self):
        argv = [
            "json-file",
            "--missing-message",
            "Status file not found - updater may not have run yet",
            "--realm",
            "it's",
            "--server-name",
            "a;b",
            ";",
            "/srv/ä",
            "x=y,z",
        ]
        self.assertEqual(FILTERS.metrics_httpd_argv_problems(argv), [])
        text = render_vendored(self.BINARY, argv)
        self.assertEqual(exec_start(text), [self.BINARY] + argv)
        self.assertIn(' "Status file not found - updater may not have run yet" ', text)
        self.assertIn(' "it\'s" ', text)
        self.assertIn(' ";"', text)


# --------------------------------------------------------------------------
# Consumer roles: static checks
# --------------------------------------------------------------------------


def deploy_block(role: str) -> dict:
    tasks = load_yaml(ROOT / "roles" / role / "tasks/main.yml")
    blocks = [t for t in tasks if "block" in t and str(t.get("name", "")).startswith("Deploy")]
    assert len(blocks) == 1, role
    return blocks[0]


def unit_template(role: str) -> Path:
    name = role.removesuffix("_metrics_endpoint")
    return ROOT / "roles" / role / f"templates/{name}-metrics-endpoint.service.j2"


class ConsumerStaticTests(unittest.TestCase):
    def test_impl_default_follows_the_fleet_variable(self):
        for role in CONSUMERS:
            defaults = load_yaml(ROOT / "roles" / role / "defaults/main.yml")
            self.assertEqual(defaults[f"{role}_impl"], "{{ metrics_httpd_impl | default('python') }}", role)

    def test_switch_inputs_come_from_the_role(self):
        for role in CONSUMERS:
            variables = deploy_block(role)["vars"]
            self.assertEqual(variables["metrics_httpd_switch_impl"], f"{{{{ {role}_impl }}}}", role)
            self.assertEqual(variables["metrics_httpd_switch_service_name"], f"{{{{ {role}_service_name }}}}", role)
            self.assertEqual(variables["metrics_httpd_switch_validate_user"], f"{{{{ {role}_user }}}}", role)
            self.assertEqual(variables["metrics_httpd_switch_validate_group"], f"{{{{ {role}_group }}}}", role)
            self.assertEqual(variables["metrics_httpd_switch_python_script"], f"{{{{ {role}_server_path }}}}", role)
            self.assertEqual(variables["metrics_httpd_switch_probe_bind"], f"{{{{ {role}_bind }}}}", role)
            self.assertEqual(variables["metrics_httpd_switch_probe_port"], f"{{{{ {role}_port }}}}", role)
            self.assertEqual(variables["metrics_httpd_switch_probe_path"], f"{{{{ {role}_path }}}}", role)
            self.assertEqual(variables["metrics_httpd_switch_probe_realm"], f"{CONSUMERS[role]}-metrics", role)
            self.assertNotIn("metrics_httpd_switch_probe_expect", variables)  # default: unauthorized

    def test_select_and_verify_are_placed_around_the_start(self):
        for role in CONSUMERS:
            tasks = deploy_block(role)["block"]
            names = [t.get("name", "") for t in tasks]
            unit = names.index("Create HTTP server service unit")
            select = names.index("Select the HTTP server implementation")
            start = names.index("Ensure HTTP server is enabled and running")
            verify = names.index("Verify the HTTP server implementation")
            self.assertEqual(select, unit + 1, role)
            self.assertLess(select, start, role)
            self.assertLess(start, verify, role)
            flushes = [i for i, t in enumerate(tasks) if t.get("ansible.builtin.meta") == "flush_handlers"]
            self.assertTrue(any(select < i < start for i in flushes), role)
            self.assertTrue(any(start < i < verify for i in flushes), role)
            for index, tasks_from in ((select, "select"), (verify, "verify")):
                include = tasks[index]["ansible.builtin.include_role"]
                self.assertEqual(include, {"name": FQCN, "tasks_from": tasks_from}, role)
                self.assertNotIn("vars", tasks[index], role)
                self.assertNotIn("when", tasks[index], role)

    def test_notified_handlers_exist(self):
        for role in CONSUMERS:
            handlers = {h["name"] for h in load_yaml(ROOT / "roles" / role / "handlers/main.yml")}
            notify = deploy_block(role)["vars"]["metrics_httpd_switch_notify"]
            self.assertEqual(notify, ["reload systemd", f"restart {role.removesuffix('_metrics_endpoint')}-metrics-endpoint"])
            self.assertLessEqual(set(notify), handlers, role)

    def test_sandbox_and_ip_allow_mirror_the_unit(self):
        for role in CONSUMERS:
            unit = unit_template(role).read_text(encoding="utf-8")
            variables = deploy_block(role)["vars"]
            for line in ("NoNewPrivileges=true", "ProtectSystem=strict", "ProtectHome=true", "PrivateTmp=true"):
                self.assertIn(line + "\n", unit, role)
            read_only = re.findall(r"(?m)^ReadOnlyPaths=(.*)$", unit)
            sandbox = variables["metrics_httpd_switch_unit_sandbox"]
            self.assertEqual(
                sandbox[:4], ["NoNewPrivileges=yes", "ProtectSystem=strict", "ProtectHome=yes", "PrivateTmp=yes"], role
            )
            self.assertEqual([s.removeprefix("ReadOnlyPaths=") for s in sandbox[4:]], read_only, role)
            self.assertIn("IPAddressDeny=any\n", unit, role)
            allow = variables["metrics_httpd_switch_ip_address_allow"]
            literal = re.findall(r"(?m)^IPAddressAllow=(.*)$", unit)
            if role == "tailscale_metrics_endpoint":
                self.assertEqual(literal, ["{{ network }}"])
                self.assertIn("{% for network in tailscale_metrics_endpoint_ip_address_allow %}", unit)
                self.assertEqual(allow, "{{ tailscale_metrics_endpoint_ip_address_allow }}")
            else:
                self.assertEqual(allow, literal, role)

    def test_tailscale_argument_spec_knows_impl(self):
        spec = load_yaml(ROOT / "roles/tailscale_metrics_endpoint/meta/argument_specs.yml")
        option = spec["argument_specs"]["main"]["options"]["tailscale_metrics_endpoint_impl"]
        self.assertEqual(option, {"type": "str", "choices": ["python", "rust"]})


class SwitchStaticTests(unittest.TestCase):
    FILES = ("main.yml", "select.yml", "verify.yml")

    def test_task_names_carry_the_file_prefix(self):
        for name in self.FILES:
            prefix = "metrics_httpd_switch | " if name == "main.yml" else name.removesuffix(".yml") + " | "
            for task in walk(load_yaml(ROLE / "tasks" / name)):
                self.assertTrue(str(task.get("name", "")).startswith(prefix), (name, task.get("name")))

    def test_no_environment_no_become_no_credentials(self):
        # PLAN.md acceptance: no secret in environment: under become_user; the
        # switch uses no credential at all.
        for name in self.FILES:
            for task in walk(load_yaml(ROLE / "tasks" / name)):
                self.assertNotIn("environment", task, task.get("name"))
                self.assertNotIn("become_user", task, task.get("name"))
                self.assertNotIn("become", task, task.get("name"))
                uri = task.get("ansible.builtin.uri")
                if uri is not None:
                    for key in ("url_username", "url_password", "headers"):
                        self.assertNotIn(key, uri)
                    self.assertIs(uri["use_netrc"], False)
                    self.assertIs(uri["force_basic_auth"], False)

    def test_python_selection_comes_before_any_rust_step(self):
        tasks = list(walk(load_yaml(ROLE / "tasks/select.yml")))
        names = [t["name"] for t in tasks]
        python = names.index("select | Select the Python implementation")
        install = names.index("select | Install the pinned metrics-httpd release")
        check = names.index("select | Check the configuration with the installed binary")
        rust = names.index("select | Select the Rust implementation")
        self.assertLess(python, install)
        self.assertLess(install, check)
        self.assertLess(check, rust)
        self.assertEqual(tasks[install]["vars"]["rust_release_binary_fail_hard"], "{{ metrics_httpd_switch_impl == 'rust' }}")

    def test_pin_and_prune_follow_the_checks(self):
        tasks = list(walk(load_yaml(ROLE / "tasks/verify.yml")))
        names = [t["name"] for t in tasks]
        order = [
            "verify | Read the live process of the unit",
            "verify | Assert the unit runs the selected implementation",
            "verify | Probe the endpoint without credentials",
            "verify | Assert the endpoint answers as expected",
            "verify | Move the pin of this unit",
            "verify | Prune old metrics-httpd releases",
        ]
        self.assertEqual([n for n in names if n in order], order)


# --------------------------------------------------------------------------
# ansible-playbook helpers
# --------------------------------------------------------------------------

RECAP = re.compile(
    r"^localhost\s+:\s+ok=(\d+)\s+changed=(\d+)\s+unreachable=(\d+)\s+failed=(\d+)\s+"
    r"skipped=(\d+)\s+rescued=(\d+)\s+ignored=(\d+)",
    re.M,
)


def _gnu_mv_dir(base: Path) -> Path | None:
    """A PATH entry whose `mv` is GNU mv (rust_release_binary needs it)."""

    probe = subprocess.run(["mv", "--version"], capture_output=True, text=True)
    if probe.returncode == 0 and "GNU" in probe.stdout:
        return None
    gmv = shutil.which("gmv")
    if gmv is None:
        raise unittest.SkipTest("GNU mv (gmv) not found; rust_release_binary targets GNU coreutils")
    shim = base / "gnu-bin"
    shim.mkdir()
    (shim / "mv").symlink_to(gmv)
    return shim


def ansible_env(base: Path, extra_path: list[Path]) -> dict[str, str]:
    collections = base / "collections/ansible_collections/local"
    collections.mkdir(parents=True)
    (collections / "ops_library").symlink_to(ROOT)
    path = os.pathsep.join([str(p) for p in extra_path] + [os.environ.get("PATH", "")])
    return {
        **os.environ,
        "PATH": path,
        "ANSIBLE_COLLECTIONS_PATH": str(base / "collections"),
        "ANSIBLE_NOCOLOR": "1",
        "ANSIBLE_LOCALHOST_WARNING": "0",
        "ANSIBLE_INVENTORY_UNPARSED_WARNING": "0",
        "ANSIBLE_STDOUT_CALLBACK": "default",
        "ANSIBLE_RETRY_FILES_ENABLED": "0",
        "ANSIBLE_LOCAL_TEMP": str(base / "ansible-local"),
        "ANSIBLE_REMOTE_TEMP": str(base / "ansible-remote"),
        "ANSIBLE_PIPELINING": "1",
        "ANSIBLE_PYTHON_INTERPRETER": sys.executable,
        "no_proxy": "*",
        "NO_PROXY": "*",
    }


def run_playbook(path: Path, env: dict[str, str], check: bool = False) -> dict:
    argv = ["ansible-playbook", "-i", "localhost,", "-c", "local", str(path)]
    if check:
        argv.append("--check")
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=900)
    out = result.stdout + result.stderr
    match = RECAP.search(result.stdout)
    assert match is not None, out
    keys = ("ok", "changed", "unreachable", "failed", "skipped", "rescued", "ignored")
    return {"rc": result.returncode, "out": out, "recap": dict(zip(keys, map(int, match.groups())))}


# --------------------------------------------------------------------------
# Consumer roles rendered by Ansible from their defaults
# --------------------------------------------------------------------------

RENDER_VARS = {
    "tailscale_ip": "100.64.0.10",
}


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not on PATH")
class ConsumerRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        base = Path(cls._tmp.name)
        cls.out = base / "out"
        cls.out.mkdir()
        env = ansible_env(base, [])
        plays = []
        for role in CONSUMERS:
            block_vars = deploy_block(role)["vars"]
            out = cls.out / role
            plays.append(
                {
                    "name": role,
                    "hosts": "localhost",
                    "gather_facts": False,
                    "vars_files": [str(ROOT / "roles" / role / "defaults/main.yml")],
                    "vars": dict(RENDER_VARS),
                    "tasks": [
                        {
                            "name": "render",
                            "vars": block_vars,
                            "block": [
                                {"ansible.builtin.file": {"path": str(out), "state": "directory", "mode": "0755"}},
                                {
                                    "ansible.builtin.set_fact": {
                                        "_argv": "{{ metrics_httpd_switch_argv | map('string') | list }}",
                                    }
                                },
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
                                            "           metrics_httpd_switch_probe_realm],"
                                            " 'allow': metrics_httpd_switch_ip_address_allow,"
                                            " 'argv_problems': metrics_httpd_switch_argv"
                                            "   | local.ops_library.metrics_httpd_argv_problems} | to_json }}"
                                        ),
                                    }
                                },
                                {
                                    "ansible.builtin.template": {
                                        "src": str(TEMPLATE),
                                        "dest": str(out / "metrics-httpd-impl.conf"),
                                        "mode": "0644",
                                    },
                                    "vars": {
                                        "metrics_httpd_impl_binary": "/opt/metrics-httpd/0.1.0/metrics-httpd",
                                        "metrics_httpd_impl_argv": "{{ _argv }}",
                                    },
                                },
                                {
                                    "ansible.builtin.template": {
                                        "src": str(unit_template(role)),
                                        "dest": str(out / unit_template(role).name.removesuffix(".j2")),
                                        "mode": "0644",
                                    }
                                },
                            ],
                        }
                    ],
                }
            )
        path = base / "render.yml"
        path.write_text(yaml.safe_dump(plays, sort_keys=False), encoding="utf-8")
        cls.result = run_playbook(path, env)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.assertEqual(self.result["rc"], 0, self.result["out"])

    def switch(self, role: str) -> dict:
        return json.loads((self.out / role / "switch.json").read_text())

    def test_argv_matches_the_json_file_fixture(self):
        variants = {v["variant"]: v for v in json.loads(JSON_FILE_FIXTURE.read_text())["variants"]}
        defaults = {role: load_yaml(ROOT / "roles" / role / "defaults/main.yml") for role in CONSUMERS}
        for role, variant in CONSUMERS.items():
            argv = self.switch(role)["argv"]
            self.assertEqual(argv[:5], ["json-file", "--bind", "100.64.0.10", "--port", str(defaults[role][f"{role}_port"])])
            rest = ["json-file"] + argv[5:]
            json_path = rest[rest.index("--json-path") + 1]
            htpasswd = rest[rest.index("--htpasswd-file") + 1]
            self.assertTrue(json_path.startswith("/var/lib/"), json_path)
            self.assertTrue(htpasswd.startswith(f"/etc/{variant}-metrics-endpoint/"), htpasswd)
            placeholders = [{json_path: "{json}", htpasswd: "{htpasswd}"}.get(a, a) for a in rest]
            self.assertEqual(placeholders, variants[variant]["argv"], role)

    def test_plan_argv_per_role(self):
        # PLAN.md 7.3 with the role defaults.
        expected_extra = {
            "backup_metrics_endpoint": [],
            "storage_metrics_endpoint": [],
            "thermal_metrics_endpoint": [],
            "tailscale_metrics_endpoint": ["--path-match", "path-only"],
            "dns_metrics_endpoint": ["--meta", "merge", "--request-timeout", "15"],
        }
        for role, variant in CONSUMERS.items():
            switch = self.switch(role)
            self.assertEqual(switch["argv_problems"], [], role)
            argv = switch["argv"]
            self.assertEqual(argv[argv.index("--realm") + 1], f"{variant}-metrics")
            self.assertEqual(argv[argv.index("--server-name") + 1], f"{variant}-metrics-httpd/0.1")
            self.assertEqual(argv[15:], expected_extra[role], role)
            self.assertEqual(switch["impl"], "python")
            self.assertEqual(switch["service"], f"{variant}-metrics-endpoint")
            self.assertEqual((switch["user"], switch["group"]), ("metrics", "metrics"))
            self.assertEqual(switch["probe"][:3], ["100.64.0.10", argv[4], argv[6]])
            self.assertTrue(FILTERS.metrics_httpd_probe_covered("100.64.0.10", switch["allow"]), role)

    def test_dropin_and_unit_goldens(self):
        for role in CONSUMERS:
            for name in ("metrics-httpd-impl.conf", unit_template(role).name.removesuffix(".j2")):
                rendered = (self.out / role / name).read_text()
                golden = GOLDENS / role / name
                if WRITE_GOLDENS:
                    golden.parent.mkdir(parents=True, exist_ok=True)
                    golden.write_text(rendered)
                self.assertEqual(rendered, golden.read_text(), f"{role}/{name}")

    def test_dropin_execstart_is_the_argv(self):
        for role in CONSUMERS:
            switch = self.switch(role)
            dropin = (self.out / role / "metrics-httpd-impl.conf").read_text()
            self.assertEqual(exec_start(dropin), ["/opt/metrics-httpd/0.1.0/metrics-httpd"] + switch["argv"])
            # ops-deploy renders the vendored template byte-identically (PLAN.md 7.4).
            self.assertEqual(dropin, render_vendored("/opt/metrics-httpd/0.1.0/metrics-httpd", switch["argv"]))

    def test_python_unit_still_runs_the_script(self):
        for role in CONSUMERS:
            unit = (self.out / role / unit_template(role).name.removesuffix(".j2")).read_text()
            script = self.switch(role)["python_script"]
            self.assertIn(f"ExecStart=/usr/bin/python3 {script} \\\n", unit, role)
            self.assertNotIn("metrics-httpd-impl", unit)


# --------------------------------------------------------------------------
# select and verify against localhost
# --------------------------------------------------------------------------

FAKE_SYSTEMD_RUN = """#!/bin/sh
# Records the call, drops the systemd-run options and runs the command.
printf '%s\\n' "$*" >> "$FAKE_SYSTEMD_DIR/systemd-run.log"
while [ $# -gt 0 ]; do
  case "$1" in --*) shift ;; *) break ;; esac
done
exec "$@"
"""

FAKE_SYSTEMCTL = """#!/bin/sh
# systemctl is-active UNIT | systemctl show --property=MainPID --value UNIT
case "$1" in
  is-active) cat "$FAKE_SYSTEMD_DIR/$2.state" 2>/dev/null || echo inactive ;;
  show) cat "$FAKE_SYSTEMD_DIR/$4.pid" 2>/dev/null || echo 0 ;;
  *) echo "fake systemctl: unsupported $*" >&2; exit 1 ;;
esac
"""

# The consumer's restart handler: "starts" the unit as systemd would, from
# the drop-in (Rust) or the base ExecStart (Python), into the fake /proc.
FAKE_RESTART = r'''
import os, re, sys
from pathlib import Path
systemd_dir, unit, proc, state, script, log = sys.argv[1:7]
pid = str(int((Path(state) / f"{unit}.pid").read_text() or "100") + 1) if (Path(state) / f"{unit}.pid").exists() else "100"
dropin = Path(systemd_dir) / f"{unit}.service.d" / "metrics-httpd-impl.conf"
if dropin.exists():
    line = [l for l in dropin.read_text().splitlines() if re.match(r"^ExecStart=\S", l)][-1]
    argv = line[len("ExecStart="):].split()
    exe = argv[0]
else:
    exe = "/usr/bin/python3.12"
    argv = ["/usr/bin/python3", script, "--bind", "127.0.0.1"]
(Path(proc) / pid).mkdir(parents=True, exist_ok=True)
link = Path(proc) / pid / "exe"
if link.is_symlink():
    link.unlink()
link.symlink_to(exe)
(Path(proc) / pid / "cmdline").write_bytes(b"".join(a.encode() + b"\0" for a in argv))
(Path(state) / f"{unit}.pid").write_text(pid + "\n")
(Path(state) / f"{unit}.state").write_text("active\n")
with open(log, "a") as handle:
    handle.write(f"restart {exe}\n")
'''

UNIT = "demo-metrics-endpoint"
SCRIPT = "/usr/local/bin/demo_metrics_httpd.py"
REALM = "demo-metrics"


def build_archive(path: Path, version: str, salt: str = "") -> str:
    """A fake metrics-httpd release archive; returns its sha256."""

    script = (
        "#!/bin/sh\n"
        f"# {salt}\n"
        'if [ "$1" = "--version" ]; then\n'
        f"  echo 'metrics-httpd {version} (0123456789abcdef0123456789abcdef01234567)'\n"
        "  exit 0\n"
        "fi\n"
        'for arg in "$@"; do printf \'%s\\n\' "$arg"; done > "$FAKE_SYSTEMD_DIR/check-config.argv"\n'
        'if [ -e "$FAKE_SYSTEMD_DIR/check-fails" ]; then\n'
        "  echo 'metrics-httpd: htpasswd file /x: Permission denied' >&2\n"
        "  exit 2\n"
        "fi\n"
        "echo 'bind 127.0.0.1:9 path /x (bcrypt entries: 1)'\n"
    ).encode()
    files = {"metrics-httpd": (script, 0o755), "LICENSE": (b"MIT License\n", 0o644)}
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, (data, mode) in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), mode, 1700000000
            tar.addfile(info, io.BytesIO(data))
    path.write_bytes(buffer.getvalue())
    return hashlib.sha256(buffer.getvalue()).hexdigest()


class ProbeHandler(http.server.BaseHTTPRequestHandler):
    status = 401
    realm = REALM
    requests: list[dict] = []

    def do_GET(self):  # noqa: N802 - http.server API
        type(self).requests.append({"path": self.path, "authorization": self.headers.get("Authorization")})
        body = b"{}"
        self.send_response(type(self).status)
        if type(self).status == 401:
            self.send_header("WWW-Authenticate", f'Basic realm="{type(self).realm}"')
            body = b""
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence
        pass


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not on PATH")
@unittest.skipUnless(shutil.which("realpath"), "realpath not on PATH")
class SwitchPlaybookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name)
        fakes = cls.base / "fake-bin"
        fakes.mkdir()
        for name, text in (("systemd-run", FAKE_SYSTEMD_RUN), ("systemctl", FAKE_SYSTEMCTL)):
            (fakes / name).write_text(text)
            (fakes / name).chmod(0o755)
        (cls.base / "fake_restart.py").write_text(FAKE_RESTART)
        shim = _gnu_mv_dir(cls.base)
        cls.env_base = ansible_env(cls.base, [fakes] + ([shim] if shim else []))
        cls.owner = pwd.getpwuid(os.getuid()).pw_name
        cls.group = grp.getgrgid(os.getgid()).gr_name
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ProbeHandler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls._tmp.cleanup()

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(dir=self.base))
        self.state = self.work / "state"
        self.state.mkdir()
        self.systemd = self.work / "systemd"
        self.systemd.mkdir()
        self.proc = self.work / "proc"
        self.proc.mkdir()
        self.root = self.work / "opt/metrics-httpd"
        self.log = self.work / "handlers.log"
        self.env = {**self.env_base, "FAKE_SYSTEMD_DIR": str(self.state)}
        self.archives: dict[str, tuple[Path, str]] = {}
        self.runs = 0
        ProbeHandler.status, ProbeHandler.realm, ProbeHandler.requests = 401, REALM, []
        # The unit runs the Python script before the first switch.
        self.restart()

    # -- helpers -------------------------------------------------------------

    def restart(self) -> None:
        subprocess.run(
            [sys.executable, str(self.base / "fake_restart.py"), str(self.systemd), UNIT, str(self.proc),
             str(self.state), SCRIPT, str(self.log)],
            check=True,
        )
        self.log.write_text("")

    def archive(self, version: str, salt: str = "") -> tuple[Path, str]:
        key = version + salt
        if key not in self.archives:
            path = self.work / f"metrics-httpd-{key}.tar.gz"
            self.archives[key] = (path, build_archive(path, version, salt))
        return self.archives[key]

    def play(self, impl: str, version: str = "", *, check: bool = False, sha256: str | None = None,
             restart_follows: bool = True, **overrides) -> dict:
        self.runs += 1
        variables = {
            "metrics_httpd_switch_impl": impl,
            "metrics_httpd_switch_service_name": UNIT,
            "metrics_httpd_switch_validate_user": "metrics",
            "metrics_httpd_switch_validate_group": "metrics",
            "metrics_httpd_switch_version_check_user": "",
            "metrics_httpd_switch_argv": [
                "json-file", "--bind", "127.0.0.1", "--port", self.port, "--path", "/.well-known/demo",
                "--json-path", "/var/lib/demo/demo.json", "--htpasswd-file", "/etc/demo/htpasswd",
                "--realm", REALM, "--server-name", "demo-metrics-httpd/0.1",
                "--missing-message", "Metrics file not found - timer may not have run yet",
            ],
            "metrics_httpd_switch_unit_sandbox": [
                "NoNewPrivileges=yes", "ProtectSystem=strict", "ProtectHome=yes", "PrivateTmp=yes",
                "ReadOnlyPaths=/var/lib/demo",
            ],
            "metrics_httpd_switch_notify": ["reload systemd", f"restart {UNIT}"],
            "metrics_httpd_switch_version": version,
            "metrics_httpd_switch_install_root": str(self.root),
            "metrics_httpd_switch_python_script": SCRIPT,
            "metrics_httpd_switch_probe_bind": "127.0.0.1",
            "metrics_httpd_switch_probe_port": self.port,
            "metrics_httpd_switch_probe_path": "/.well-known/demo",
            "metrics_httpd_switch_probe_realm": REALM,
            "metrics_httpd_switch_ip_address_allow": ["localhost", "100.64.0.0/10"],
            "metrics_httpd_switch_verify_retries": 2,
            "metrics_httpd_switch_verify_delay": 0,
            "metrics_httpd_switch_systemd_dir": str(self.systemd),
            "metrics_httpd_switch_proc_root": str(self.proc),
            "metrics_httpd_switch_owner": self.owner,
            "metrics_httpd_switch_group": self.group,
        }
        if version:
            path, sha = self.archive(version)
            variables["metrics_httpd_switch_local_archive"] = str(path)
            variables["metrics_httpd_switch_sha256"] = sha if sha256 is None else sha256
        variables.update(overrides)
        restart = (
            [sys.executable, str(self.base / "fake_restart.py"), str(self.systemd), UNIT, str(self.proc),
             str(self.state), SCRIPT, str(self.log)]
            if restart_follows
            else ["sh", "-c", f"echo 'restart ignored' >> {self.log}"]
        )
        facts = self.work / f"facts-{self.runs}.json"
        play = {
            "hosts": "localhost",
            "gather_facts": False,
            "vars": variables,
            "tasks": [
                {"name": "select", "ansible.builtin.include_role": {"name": FQCN, "tasks_from": "select"}},
                {"name": "flush", "ansible.builtin.meta": "flush_handlers"},
                {"name": "verify", "ansible.builtin.include_role": {"name": FQCN, "tasks_from": "verify"}},
                {
                    "name": "dump facts",
                    "ansible.builtin.copy": {
                        "dest": str(facts),
                        "mode": "0644",
                        "content": (
                            "{{ {'pins': rust_release_binary_pins | default(None),"
                            " 'prune': rust_release_binary_prune | default(None),"
                            " 'selected': _metrics_httpd_switch_selected | default(None)} | to_json }}"
                        ),
                    },
                    "check_mode": False,
                    "changed_when": False,
                },
            ],
            "handlers": [
                {
                    "name": "reload systemd",
                    "ansible.builtin.command": {"argv": ["sh", "-c", f"echo reload >> {self.log}"]},
                    "changed_when": True,
                },
                {
                    "name": f"restart {UNIT}",
                    "ansible.builtin.command": {"argv": restart},
                    "changed_when": True,
                },
            ],
        }
        path = self.work / f"play-{self.runs}.yml"
        path.write_text(yaml.safe_dump([play], sort_keys=False), encoding="utf-8")
        result = run_playbook(path, self.env, check=check)
        result["facts"] = json.loads(facts.read_text()) if facts.exists() else None
        result["handlers"] = self.log.read_text().splitlines() if self.log.exists() else []
        self.log.write_text("")
        return result

    def ok(self, *args, **kwargs) -> dict:
        result = self.play(*args, **kwargs)
        self.assertEqual(result["rc"], 0, result["out"])
        return result

    def failed(self, *args, **kwargs) -> dict:
        result = self.play(*args, **kwargs)
        self.assertNotEqual(result["rc"], 0, result["out"])
        self.assertEqual(result["recap"]["failed"], 1, result["out"])
        return result

    @property
    def dropin(self) -> Path:
        return self.systemd / f"{UNIT}.service.d/metrics-httpd-impl.conf"

    def binary(self, version: str) -> str:
        return f"{self.root}/{version}/metrics-httpd"

    def pins(self) -> dict[str, str]:
        pins = self.root / ".pins"
        return {p.name: p.read_text() for p in sorted(pins.iterdir())} if pins.exists() else {}

    def versions(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and not p.name.startswith("."))

    def systemd_run_calls(self) -> list[str]:
        log = self.state / "systemd-run.log"
        return log.read_text().splitlines() if log.exists() else []

    def live_exe(self) -> str:
        pid = (self.state / f"{UNIT}.pid").read_text().strip()
        return os.readlink(self.proc / pid / "exe")

    # -- python ----------------------------------------------------------------

    def test_python_without_a_release_changes_nothing(self):
        result = self.ok("python")
        self.assertEqual(result["recap"]["changed"], 0, result["out"])
        self.assertEqual(result["recap"]["ignored"], 0, result["out"])
        self.assertEqual(result["handlers"], [])
        self.assertFalse(self.dropin.parent.exists())
        self.assertFalse(self.root.exists())
        self.assertEqual(self.systemd_run_calls(), [])
        self.assertEqual(ProbeHandler.requests, [{"path": "/.well-known/demo", "authorization": None}])

    # -- rust, both directions -------------------------------------------------

    def test_switch_to_rust_upgrade_and_back_to_python(self):
        first = self.ok("rust", "0.1.0")
        self.assertEqual(first["handlers"], ["reload", f"restart {self.binary('0.1.0')}"])
        self.assertEqual(
            self.dropin.read_text(),
            "# Managed by ops-library metrics_httpd_switch: selects the Rust metrics-httpd.\n"
            "# Remove this file (daemon-reload, restart) to fall back to Python.\n"
            "[Service]\n"
            "ExecStart=\n"
            f"ExecStart={self.binary('0.1.0')} json-file --bind 127.0.0.1 --port {self.port}"
            " --path /.well-known/demo --json-path /var/lib/demo/demo.json --htpasswd-file /etc/demo/htpasswd"
            f" --realm {REALM} --server-name demo-metrics-httpd/0.1"
            ' --missing-message "Metrics file not found - timer may not have run yet"\n',
        )
        self.assertEqual(self.dropin.stat().st_mode & 0o7777, 0o644)
        self.assertEqual(self.live_exe(), self.binary("0.1.0"))
        self.assertEqual(self.pins(), {UNIT: "0.1.0\n"})
        # --check-config ran in the unit's sandbox with the exact argv.
        calls = self.systemd_run_calls()
        self.assertEqual(len(calls), 1)
        self.assertTrue(
            calls[0].startswith(
                "--wait --pipe --collect --quiet --property=User=metrics --property=Group=metrics"
                " --property=NoNewPrivileges=yes --property=ProtectSystem=strict --property=ProtectHome=yes"
                " --property=PrivateTmp=yes --property=ReadOnlyPaths=/var/lib/demo "
                f"{self.binary('0.1.0')} json-file --bind 127.0.0.1"
            ),
            calls[0],
        )
        argv = (self.state / "check-config.argv").read_text().splitlines()
        self.assertEqual(argv[-3:], ["--missing-message", "Metrics file not found - timer may not have run yet", "--check-config"])
        self.assertIsNone(ProbeHandler.requests[-1]["authorization"])

        again = self.ok("rust", "0.1.0")
        self.assertEqual(again["recap"]["changed"], 0, again["out"])
        self.assertEqual(again["handlers"], [])

        upgrade = self.ok("rust", "0.2.0")
        self.assertEqual(upgrade["handlers"], ["reload", f"restart {self.binary('0.2.0')}"])
        self.assertIn(f"ExecStart={self.binary('0.2.0')} json-file", self.dropin.read_text())
        self.assertEqual(self.pins(), {UNIT: "0.2.0\n", f"{UNIT}.previous": "0.1.0\n"})
        self.assertEqual(self.versions(), ["0.1.0", "0.2.0"])

        back = self.ok("python", "0.2.0")
        self.assertEqual(back["handlers"], ["reload", "restart /usr/bin/python3.12"])
        self.assertFalse(self.dropin.exists())
        self.assertEqual(self.pins(), {f"{UNIT}.previous": "0.2.0\n"})
        self.assertEqual(back["recap"]["ignored"], 0, back["out"])
        # The installed release is still checked with impl python.
        self.assertEqual(len(self.systemd_run_calls()), 4)

    def test_prune_keeps_pins_of_other_units_and_the_rollback_pin(self):
        (self.root / ".pins").mkdir(parents=True)
        self.ok("rust", "0.1.0", metrics_httpd_switch_keep_versions=1)
        (self.root / ".pins/other-metrics-endpoint").write_text("0.1.0\n")
        for version in ("0.2.0", "0.3.0", "0.4.0"):
            self.ok("rust", version, metrics_httpd_switch_keep_versions=1)
        # 0.4.0 current, 0.3.0 the rollback pin, 0.1.0 another unit's pin.
        self.assertEqual(self.versions(), ["0.1.0", "0.3.0", "0.4.0"])

    def test_prune_protects_the_version_the_old_dropin_named(self):
        self.ok("rust", "0.1.0")
        # Pins lost (hand edit): the drop-in still names 0.1.0 when 0.2.0 is selected.
        shutil.rmtree(self.root / ".pins")
        result = self.ok("rust", "0.2.0", metrics_httpd_switch_keep_versions=1)
        self.assertIn("0.1.0", self.versions(), result["out"])
        self.assertEqual(self.pins(), {UNIT: "0.2.0\n"})

    def test_quoted_words_reach_the_binary_as_one_argument(self):
        self.ok("rust", "0.1.0", metrics_httpd_switch_argv=[
            "json-file", "--bind", "127.0.0.1", "--port", self.port, "--path", "/.well-known/demo",
            "--json-path", "/var/lib/demo/demo.json", "--htpasswd-file", "/etc/demo/htpasswd",
            "--realm", REALM, "--server-name", "demo-metrics-httpd/0.1",
            "--missing-message", "it's; gone",
        ])
        line = [l for l in self.dropin.read_text().splitlines() if l.startswith("ExecStart=/")][0]
        self.assertTrue(line.endswith(' --missing-message "it\'s; gone"'), line)
        argv = (self.state / "check-config.argv").read_text().splitlines()
        self.assertEqual(argv[-2:], ["it's; gone", "--check-config"])

    # -- refusals ----------------------------------------------------------------

    def test_rust_check_config_failure_stops_before_the_switch(self):
        (self.state / "check-fails").write_text("")
        result = self.failed("rust", "0.1.0")
        self.assertIn("Permission denied", result["out"])
        self.assertIn("Nothing was switched", result["out"])
        self.assertFalse(self.dropin.exists())
        self.assertEqual(result["handlers"], [])
        self.assertEqual(self.pins(), {})

    def test_rust_check_config_failure_keeps_the_running_release(self):
        self.ok("rust", "0.1.0")
        (self.state / "check-fails").write_text("")
        self.failed("rust", "0.2.0")
        self.assertIn(self.binary("0.1.0"), self.dropin.read_text())
        self.assertEqual(self.pins(), {UNIT: "0.1.0\n"})

    def test_python_check_config_failure_warns_and_continues(self):
        (self.state / "check-fails").write_text("")
        result = self.ok("python", "0.1.0")
        self.assertEqual(result["recap"]["ignored"], 1, result["out"])
        self.assertIn("WARNING:", result["out"])
        self.assertFalse(self.dropin.exists())
        self.assertEqual(self.versions(), ["0.1.0"])

    def test_rust_install_failure_stops_the_play(self):
        self.ok("rust", "0.1.0")
        result = self.failed("rust", "0.2.0", sha256="0" * 64)
        self.assertIn(self.binary("0.1.0"), self.dropin.read_text())
        self.assertEqual(self.versions(), ["0.1.0"])
        self.assertEqual(result["handlers"], [])

    def test_python_install_failure_warns_and_never_prunes(self):
        self.ok("rust", "0.1.0")
        result = self.ok("python", "0.2.0", sha256="0" * 64, metrics_httpd_switch_keep_versions=1)
        self.assertFalse(self.dropin.exists())
        # install warned (ignored) and prune refused to run after it (ignored).
        self.assertEqual(result["recap"]["ignored"], 2, result["out"])
        self.assertEqual(self.versions(), ["0.1.0"])
        self.assertEqual(self.pins(), {f"{UNIT}.previous": "0.1.0\n"})

    def test_python_rollback_is_not_blocked_by_an_invalid_version(self):
        self.ok("rust", "0.1.0")
        result = self.ok("python", "not-a-version")
        self.assertFalse(self.dropin.exists())
        self.assertEqual(result["handlers"], ["reload", "restart /usr/bin/python3.12"])
        # install warned, prune refused after the failed install.
        self.assertEqual(result["recap"]["ignored"], 2, result["out"])
        self.assertEqual(self.pins(), {f"{UNIT}.previous": "0.1.0\n"})

    def test_probe_ignores_netrc_credentials(self):
        netrc = self.work / "netrc"
        netrc.write_text("default login someone password secret\n")
        netrc.chmod(0o600)
        self.env["NETRC"] = str(netrc)
        self.ok("python")
        self.assertEqual(ProbeHandler.requests, [{"path": "/.well-known/demo", "authorization": None}])

    def test_unsafe_argv_and_missing_release_are_refused(self):
        for overrides in (
            {"metrics_httpd_switch_argv": ["json-file", "--realm", "100%"]},
            {"metrics_httpd_switch_argv": ["json-file", "--realm", "$USER"]},
            {"metrics_httpd_switch_impl": "go"},
            {"metrics_httpd_switch_service_name": "Demo.service"},
        ):
            result = self.failed("python", **overrides)
            self.assertIn("select | Assert the switch inputs", result["out"])
        result = self.failed("rust")  # no version
        self.assertIn("select | Assert the switch inputs", result["out"])
        result = self.failed("rust", "0.1.0", sha256="", metrics_httpd_switch_local_archive="")
        self.assertIn("select | Assert the switch inputs", result["out"])
        self.assertFalse(self.root.exists())
        self.assertFalse(self.dropin.parent.exists())

    # -- verify ------------------------------------------------------------------

    def test_verify_fails_when_the_unit_runs_the_other_implementation(self):
        result = self.failed("rust", "0.1.0", restart_follows=False)
        self.assertIn("does not run the selected", result["out"])
        self.assertEqual(self.pins(), {})
        self.assertEqual(ProbeHandler.requests, [])

    def test_verify_fails_on_a_wrong_realm(self):
        ProbeHandler.realm = "other"
        result = self.failed("rust", "0.1.0")
        self.assertIn('expected 401 with WWW-Authenticate: Basic realm="demo-metrics"', result["out"])
        self.assertEqual(self.pins(), {})

    def test_verify_fails_on_an_open_endpoint(self):
        ProbeHandler.status = 200
        self.failed("python")

    def test_probe_skipped_when_the_ip_filter_would_drop_it(self):
        result = self.ok("rust", "0.1.0", metrics_httpd_switch_ip_address_allow=["100.64.0.0/10"])
        self.assertIn("Skipping the HTTP probe", result["out"])
        self.assertEqual(ProbeHandler.requests, [])
        self.assertEqual(self.pins(), {UNIT: "0.1.0\n"})

    def test_static_and_logyard_expectations(self):
        ProbeHandler.status = 200
        self.ok("python", metrics_httpd_switch_probe_expect="static", metrics_httpd_switch_probe_realm="")
        self.failed("python", metrics_httpd_switch_probe_expect="logyard-health")  # "{}" has no status

    # -- check mode ----------------------------------------------------------------

    def test_check_mode_changes_nothing(self):
        result = self.ok("rust", "0.1.0", check=True)
        self.assertFalse(self.root.exists())
        self.assertFalse(self.dropin.exists())
        self.assertEqual(result["handlers"], [])
        self.ok("rust", "0.1.0")
        before = self.dropin.read_text()
        result = self.ok("python", "0.1.0", check=True)
        self.assertEqual(self.dropin.read_text(), before)
        self.assertEqual(self.pins(), {UNIT: "0.1.0\n"})


if __name__ == "__main__":
    unittest.main()
