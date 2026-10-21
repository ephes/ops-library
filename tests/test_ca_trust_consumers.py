"""ca_trust_consumers: NODE_OPTIONS merging, forbidden-root scan, gate order."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import shlex
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import yaml
from ansible.errors import AnsibleFilterError
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "ca_trust_consumers"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


filters = _load("ca_trust_consumers_filters", ROOT / "plugins/filter/ca_trust_consumers.py")
roots = _load("ca_trust_roots_check", ROLE / "files/ca_trust_roots_check.py")
sudoers = _load("ca_trust_sudoers_env_file", ROLE / "files/ca_trust_sudoers_env_file.py")

FLAG = "--use-openssl-ca"


def _tasks(name: str) -> list[dict]:
    return yaml.safe_load((ROLE / "tasks" / name).read_text())


def _pem(der: bytes, trusted: bool = False) -> bytes:
    label = b"TRUSTED CERTIFICATE" if trusted else b"CERTIFICATE"
    body = base64.encodebytes(der)
    return b"-----BEGIN " + label + b"-----\n" + body + b"-----END " + label + b"-----\n"


class NodeOptionsTests(unittest.TestCase):
    def test_adds_flag_to_empty_and_keeps_existing_options(self):
        merge = filters.node_options_with_flag
        self.assertEqual(merge("", FLAG), FLAG)
        self.assertEqual(merge(None, FLAG), FLAG)
        self.assertEqual(
            merge("--max-old-space-size=1536", FLAG), f"--max-old-space-size=1536 {FLAG}"
        )

    def test_is_idempotent(self):
        once = filters.node_options_with_flag("--max-old-space-size=1536", FLAG)
        self.assertEqual(filters.node_options_with_flag(once, FLAG), once)
        self.assertEqual(
            filters.node_options_with_flag(f"{FLAG} --trace-warnings", FLAG),
            f"{FLAG} --trace-warnings",
        )

    def test_refuses_conflicting_store_selector(self):
        with self.assertRaises(AnsibleFilterError):
            filters.node_options_with_flag("--use-bundled-ca", FLAG)

    def test_refuses_values_that_need_escaping(self):
        for value in ('--title="x"', "--require=/opt/%n.js", "--require=$HOME/x", "a\\b"):
            with self.subTest(value=value), self.assertRaises(AnsibleFilterError):
                filters.node_options_with_flag(value, FLAG)

    def test_refuses_invalid_flag(self):
        for flag in ("use-openssl-ca", "--Use", "--a b", ""):
            with self.subTest(flag=flag), self.assertRaises(AnsibleFilterError):
                filters.node_options_with_flag("", flag)


class EnvironmentFileTests(unittest.TestCase):
    def test_reads_plain_quoted_and_exported_values(self):
        read = filters.environment_file_node_options
        self.assertEqual(read('PATH="/usr/bin"\n'), "")
        self.assertEqual(read("NODE_OPTIONS=--a\n"), "--a")
        self.assertEqual(read('LANG=C\nNODE_OPTIONS="--a --b"\n'), "--a --b")
        self.assertEqual(read("export NODE_OPTIONS='--a'\n"), "--a")
        self.assertEqual(read(None), "")

    def test_refuses_duplicate_lines(self):
        with self.assertRaises(AnsibleFilterError):
            filters.environment_file_node_options("NODE_OPTIONS=--a\nNODE_OPTIONS=--b\n")


class SystemdUnitTests(unittest.TestCase):
    DROPIN = "/etc/systemd/system/app.service.d/99-ca-trust-node.conf"

    def test_ignores_own_dropin_and_other_sections(self):
        cat = f"""# /etc/systemd/system/app.service
[Unit]
Environment=NODE_OPTIONS=--not-service-section
[Service]
Environment="NODE_ENV=production" "NODE_OPTIONS=--max-old-space-size=512"
ExecStart=/usr/bin/node app.js

# {self.DROPIN}
[Service]
Environment="NODE_OPTIONS=--max-old-space-size=512 {FLAG}"
"""
        self.assertEqual(
            filters.systemd_unit_node_options(cat, self.DROPIN), "--max-old-space-size=512"
        )
        self.assertEqual(
            filters.systemd_unit_node_options(cat, ""), f"--max-old-space-size=512 {FLAG}"
        )

    def test_last_assignment_wins_and_empty_resets(self):
        cat = """# /lib/systemd/system/app.service
[Service]
Environment=NODE_OPTIONS=--a
# /etc/systemd/system/app.service.d/10-local.conf
[Service]
Environment=
"""
        self.assertEqual(filters.systemd_unit_node_options(cat, self.DROPIN), "")
        cat += "Environment=NODE_OPTIONS=--b\n"
        self.assertEqual(filters.systemd_unit_node_options(cat, self.DROPIN), "--b")

    def test_unit_without_node_options(self):
        cat = "# /etc/systemd/system/x.service\n[Service]\nEnvironment=PORT=1\n"
        self.assertEqual(filters.systemd_unit_node_options(cat, self.DROPIN), "")

    def test_filters_are_registered(self):
        self.assertEqual(
            set(filters.FilterModule().filters()),
            {
                "ca_trust_node_options_with_flag",
                "ca_trust_environment_file_node_options",
                "ca_trust_systemd_unit_node_options",
            },
        )


class RootsCheckTests(unittest.TestCase):
    BAD = b"\x30\x03\x02\x01\x01"
    GOOD = b"\x30\x03\x02\x01\x02"

    def _sha(self, der: bytes) -> str:
        return hashlib.sha256(der).hexdigest().upper()

    def test_finds_forbidden_root_in_bundle_directory_and_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "share").mkdir()
            (base / "certs").mkdir()
            (base / "share" / "bad.crt").write_bytes(_pem(self.BAD))
            (base / "certs" / "good.pem").write_bytes(_pem(self.GOOD))
            os.symlink(base / "share" / "bad.crt", base / "certs" / "14bc7599.0")
            (base / "certs" / "subdir").mkdir()
            (base / "bundle.crt").write_bytes(_pem(self.GOOD) + _pem(self.BAD))
            report = roots.scan(
                [str(base / "bundle.crt"), str(base / "missing.pem"), str(base / "certs")],
                {self._sha(self.BAD)},
            )
        self.assertEqual(report["files_scanned"], 3)
        self.assertEqual(report["certificates"], 4)
        self.assertEqual(
            sorted(Path(item["path"]).name for item in report["found"]),
            ["14bc7599.0", "bundle.crt"],
        )

    def test_trusted_certificate_aux_data_is_ignored_for_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trusted.pem"
            path.write_bytes(_pem(self.BAD + b"\x30\x00", trusted=True))
            report = roots.scan([str(path)], {self._sha(self.BAD)})
        self.assertEqual(len(report["found"]), 1)

    def test_clean_store_and_garbage_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bundle.crt"
            path.write_bytes(
                _pem(self.GOOD)
                + b"-----BEGIN CERTIFICATE-----\n!!!\n-----END CERTIFICATE-----\n"
            )
            report = roots.scan([str(path)], {self._sha(self.BAD)})
        self.assertEqual(report["found"], [])
        self.assertEqual(report["certificates"], 1)

    def test_cli_validates_fingerprints_and_prints_json(self):
        with self.assertRaises(SystemExit):
            roots.main(["--forbid", "abc", "/nonexistent"])
        with self.assertRaises(SystemExit):
            roots.main(["/nonexistent"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bundle.crt"
            path.write_bytes(_pem(self.BAD))
            out = io.StringIO()
            sha = self._sha(self.BAD)
            colon = ":".join(sha[i : i + 2] for i in range(0, 64, 2)).lower()
            with redirect_stdout(out):
                self.assertEqual(roots.main(["--forbid", colon, str(path)]), 0)
        self.assertEqual(json.loads(out.getvalue())["found"][0]["sha256"], sha)


class SudoersEnvFileTests(unittest.TestCase):
    def test_any_whole_word_mention_counts(self):
        sets = sudoers.sets_env_file
        for text in (
            'Defaults env_file="/etc/proxy.env"\n',
            "Defaults\tenv_reset, env_file=/etc/x\n",
            "Defaults:root, daemon env_file=/etc/proxy.env\n",  # selector list with a blank
            "Defaults env_reset, \\\n    env_file=\"/etc/proxy.env\"\n",  # continued line
            '# comment ending in a backslash \\\nDefaults env_file=/etc/proxy.env\n',
            'Defaults env_keep += "FOO \\\n#BAR", env_file="/etc/proxy.env"\n',  # quote across lines
            "Defaults !env_file\n",
            "# Defaults env_file=/commented\n",  # fail closed: a comment counts too
        ):
            with self.subTest(text=text):
                self.assertTrue(sets(text))

    def test_longer_names_and_absent_option_do_not_count(self):
        sets = sudoers.sets_env_file
        for text in (
            'Defaults restricted_env_file="/etc/proxy.env"\n',
            'Defaults secure_path="/usr/bin:/bin"\n',
            'Defaults env_keep += "LANG env_file_hint"\n',
            "root ALL=(ALL) ALL\n#includedir /etc/sudoers.d\n",
        ):
            with self.subTest(text=text):
                self.assertFalse(sets(text))

    def test_cli_scans_like_includedir_and_excludes_own_dropin(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "sudoers").write_text("#includedir /etc/sudoers.d\n")
            d = base / "sudoers.d"
            d.mkdir()
            (d / "ca-trust-consumers").write_text('Defaults env_file="/etc/ca-trust-consumers/sudo.env"\n')
            (d / "proxy").write_text("Defaults env_reset,\\\n env_file=/etc/proxy.env\n")
            (d / "ignored.bak").write_text("Defaults env_file=/x\n")  # sudo skips names with a dot
            (d / "README~").write_text("Defaults env_file=/x\n")
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(sudoers.main(["--exclude", str(d / "ca-trust-consumers"), str(base / "sudoers"), str(d)]), 0)
        self.assertEqual(out.getvalue().splitlines(), [str(d / "proxy")])


class RoleStructureTests(unittest.TestCase):
    def test_all_role_yaml_parses(self):
        for path in ROLE.rglob("*.yml"):
            with self.subTest(path=path):
                self.assertIsNotNone(yaml.safe_load(path.read_text()))

    def test_defaults_forbid_the_four_incident_roots(self):
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        # emudhra.we-have-a-problem.com/roots.json (2026-10-20)
        self.assertEqual(
            set(defaults["ca_trust_consumers_forbidden_root_sha256"]),
            {
                "86A1ECBA089C4A8D3BBE2734C612BA341D813E043CF9E8A862CD5C57A36BBE6B",  # emSign ECC Root CA - G3
                "D7A7A0FB5D7E2731D771E9484EBCDEF71D5F0C3E0A2948782BC83EE0EA699EF4",  # AAA Certificate Services
                "7DD78D5F4F13459A83DFF9ABBBA62EDBAF6F2D102BF257FD712F4D9F2746ED8D",  # emSign Root TLS CA - G3
                "F2EDAAFF3D9B701FB4D14C9F285F8C0BAD90FC3BCC1FA07D47F4718EDABA34A5",  # emSign Root CS CA - G3
            },
        )
        self.assertEqual(defaults["ca_trust_consumers_node_flag"], FLAG)
        self.assertEqual(defaults["ca_trust_consumers_ca_min_version"], "")
        self.assertFalse(defaults["ca_trust_consumers_node_cli"])
        self.assertEqual(defaults["ops_library_documentation_category"], "operations")

    def test_readiness_gate_runs_before_any_change(self):
        main = _tasks("main.yml")
        names = [task["name"] for task in main]
        self.assertEqual(names[0], "Validate ca_trust_consumers settings")
        self.assertEqual(main[1]["ansible.builtin.import_tasks"], "preflight.yml")
        self.assertEqual(main[2]["ansible.builtin.import_tasks"], "pending_units.yml")
        later = [task.get("ansible.builtin.import_tasks") or task.get("ansible.builtin.include_tasks") for task in main[3:]]
        self.assertEqual(
            later, ["node_cli.yml", "node_unit.yml", "restart_unit.yml", "restart_unit.yml", "verify_node_unit.yml"]
        )
        node_restart, other_restart = main[5], main[6]
        self.assertEqual(node_restart["loop"], "{{ ca_trust_consumers_node_units }}")
        self.assertTrue(node_restart["vars"]["ca_trust_consumers_unit_is_node"])
        self.assertEqual(other_restart["loop"], "{{ ca_trust_consumers_restart_units }}")
        self.assertFalse(other_restart["vars"]["ca_trust_consumers_unit_is_node"])
        preflight = _tasks("preflight.yml")
        modules = {key for task in preflight for key in task if key.startswith("ansible.builtin.")}
        self.assertLessEqual(
            modules,
            {"ansible.builtin.command", "ansible.builtin.assert", "ansible.builtin.script", "ansible.builtin.stat"},
        )
        asserts = [task for task in preflight if "ansible.builtin.assert" in task]
        self.assertTrue(any("_ca_trust_consumers_ca_compare.rc == 0" in str(t) for t in asserts))
        self.assertTrue(any("_report.found | length == 0" in str(t) for t in asserts))

    def test_restarts_only_running_stale_units_when_enabled(self):
        tasks = _tasks("restart_unit.yml")
        decide = next(t for t in tasks if t["name"].endswith("Decide whether the unit holds pre-update roots"))
        expr = decide["ansible.builtin.set_fact"]["_ca_trust_consumers_needs_restart"]
        self.assertIn("_before.ActiveState == 'active'", expr)
        self.assertIn("< (_ca_trust_consumers_bundle.stat.mtime | int)", expr)
        block = next(t for t in tasks if "block" in t)
        self.assertEqual(
            block["when"],
            ["_ca_trust_consumers_needs_restart | bool", "ca_trust_consumers_restart | bool", "not ansible_check_mode"],
        )
        inner = {t["name"]: t for t in block["block"]}
        self.assertEqual(inner["restart_unit | Restart in place"]["ansible.builtin.systemd_service"]["state"], "restarted")
        detached = inner["restart_unit | Restart through a transient unit"]["ansible.builtin.command"]["argv"]
        self.assertEqual(detached[:3], ["systemd-run", "--no-block", "--collect"])
        self.assertEqual(detached[-3:], ["/bin/systemctl", "restart", "{{ ca_trust_consumers_unit.name }}"])
        self.assertIn("ansible.builtin.wait_for_connection", inner["restart_unit | Wait for the controller connection"])
        wait = inner["restart_unit | Wait for a new active main process"]
        self.assertIn("_after.ActiveState == 'active'", wait["until"])
        # No task in the role starts or enables a unit.
        for path in (ROLE / "tasks").glob("*.yml"):
            text = path.read_text()
            self.assertNotIn("state: started", text, path)
            self.assertNotIn("enabled: true", text, path)

    def test_node_restart_decision_is_stateless(self):
        # A run interrupted after writing a drop-in must still restart the unit
        # next time: the decision reads the running processes, not run state.
        tasks = _tasks("restart_unit.yml")
        check = tasks[1]
        self.assertEqual(check["ansible.builtin.include_tasks"], "node_runtime.yml")
        self.assertEqual(check["when"], "ca_trust_consumers_unit_is_node | default(false) | bool")
        decide = tasks[2]["ansible.builtin.set_fact"]["_ca_trust_consumers_needs_restart"]
        self.assertIn("'flag=no' in _ca_trust_consumers_node_runtime.stdout", decide)
        for path in (ROLE / "tasks").glob("*.yml"):
            self.assertNotIn("force_restart", path.read_text(), path)
        verify = _tasks("verify_node_unit.yml")
        self.assertEqual(verify[0]["ansible.builtin.include_tasks"], "node_runtime.yml")

    def test_restart_refuses_staged_changes_before_restarting(self):
        tasks = _tasks("restart_unit.yml")
        names = [t["name"] for t in tasks]
        look = names.index("restart_unit | Look for changes a restart would activate")
        refuse = names.index("restart_unit | Refuse to activate staged changes")
        block = next(i for i, t in enumerate(tasks) if "block" in t)
        self.assertLess(look, refuse)
        self.assertLess(refuse, block)
        cmd = tasks[look]["ansible.builtin.shell"]["cmd"]
        for needle in ('*" (deleted)")', "NeedDaemonReload", "FragmentPath", "DropInPaths", "EnvironmentFiles",
                       "guard_paths", 'stat -c %Y "$path"', "set -o pipefail"):
            self.assertIn(needle, cmd)
        self.assertIn('stat -L -c %Y "$path"', cmd)  # the link target must count too
        self.assertIn("_own_dropin", cmd)
        guard = tasks[refuse]
        self.assertEqual(guard["ansible.builtin.assert"]["that"], "_ca_trust_consumers_staged.stdout | trim | length == 0")
        self.assertIn("not (ca_trust_consumers_unit.allow_staged_changes | default(false) | bool)", guard["when"])

    def test_no_secret_bearing_content_is_logged_or_diffed(self):
        cli = {t["name"]: t for t in _tasks("node_cli.yml")}
        self.assertTrue(cli["node_cli | Read environment file"]["no_log"])
        line = cli["node_cli | Set NODE_OPTIONS in environment file"]
        self.assertTrue(line["no_log"])
        self.assertFalse(line["diff"])
        unit = _tasks("node_unit.yml")
        cat = next(t for t in unit if t["name"] == "node_unit | Read unit definition")
        self.assertTrue(cat["no_log"])
        block = next(t for t in unit if "block" in t)
        template = next(t for t in block["block"] if "ansible.builtin.template" in t)
        self.assertFalse(template["diff"])

    def test_effective_value_and_pending_reload_are_checked(self):
        unit = {t["name"]: t for t in _tasks("node_unit.yml")}
        effective = unit["node_unit | Check the effective NODE_OPTIONS of the unit"]["ansible.builtin.shell"]["cmd"]
        self.assertIn("-p Environment --value", effective)
        self.assertIn("echo effective=yes", effective)
        self.assertIn("-p UnsetEnvironment --value", effective)
        self.assertEqual(
            unit["node_unit | Require the flag in the unit's effective environment"]["ansible.builtin.assert"]["that"],
            "_ca_trust_consumers_node_effective.stdout | trim == 'effective=yes'",
        )
        pending = _tasks("pending_units.yml")
        self.assertIn("NeedDaemonReload", pending[0]["ansible.builtin.shell"]["cmd"])
        self.assertEqual(pending[1]["ansible.builtin.assert"]["that"], "_ca_trust_consumers_pending.stdout | trim | length == 0")
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        self.assertTrue(defaults["ca_trust_consumers_node_dropin_name"].startswith("99-"))

    def test_sudo_sessions_get_the_flag_from_a_root_owned_env_file(self):
        cli = _tasks("node_cli.yml")
        block = next(t for t in cli if t.get("name") == "node_cli | Configure sudo sessions")
        inner = {t["name"]: t for t in block["block"]}
        dropin = inner["node_cli | Point sudo at the environment file"]["ansible.builtin.copy"]
        self.assertIn('Defaults env_file="{{ ca_trust_consumers_sudo_env_file }}"', dropin["content"])
        self.assertEqual(dropin["mode"], "0440")
        self.assertEqual(dropin["validate"], "{{ ca_trust_consumers_visudo }} -cf %s")
        env = inner["node_cli | Write sudo environment file"]
        self.assertIn('NODE_OPTIONS="{{ _ca_trust_consumers_cli_node_options }}"', env["ansible.builtin.copy"]["content"])
        self.assertTrue(env["no_log"])
        self.assertFalse(env["diff"])
        line = next(t for t in cli if t.get("name") == "node_cli | Set NODE_OPTIONS in environment file")
        self.assertEqual(line["ansible.builtin.lineinfile"]["line"], 'NODE_OPTIONS="{{ _ca_trust_consumers_cli_node_options }}"')
        for text in (str(block), (ROLE / "defaults/main.yml").read_text()):
            self.assertNotIn("env_keep", text.replace("unlike env_keep", ""))
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        self.assertTrue(defaults["ca_trust_consumers_node_cli_sudo"])
        self.assertNotIn(".", Path(defaults["ca_trust_consumers_sudoers_dropin"]).name)

    def test_report_mode_does_not_fail_on_unrestarted_processes(self):
        verify = _tasks("verify_node_unit.yml")[-1]
        self.assertEqual(verify["when"], ["not ansible_check_mode", "ca_trust_consumers_restart | bool"])

    def test_node_unit_refuses_environment_file_override(self):
        tasks = _tasks("node_unit.yml")
        refuse = next(t for t in tasks if t["name"].endswith("Refuse to override NODE_OPTIONS from an environment file"))
        self.assertIn("stdout | trim | length == 0", refuse["ansible.builtin.assert"]["that"])
        look = next(t for t in tasks if t["name"].endswith("Look for NODE_OPTIONS in the unit's environment files"))
        cmd = look["ansible.builtin.shell"]["cmd"]
        self.assertIn("grep -q -F NODE_OPTIONS", cmd)  # any mention; file names only, never values
        self.assertIn("(wildcard pattern)", cmd)
        self.assertIn("(unreadable)", cmd)

    def test_dropin_template_renders_single_environment_line(self):
        template = Environment(undefined=StrictUndefined).from_string(
            (ROLE / "templates/node-trust.conf.j2").read_text()
        )
        rendered = template.render(
            ansible_managed="Ansible managed",
            ca_trust_consumers_node_flag=FLAG,
            ca_trust_consumers_node_options=f"--max-old-space-size=512 {FLAG}",
        )
        lines = [line for line in rendered.splitlines() if line and not line.startswith("#")]
        self.assertEqual(lines, ["[Service]", f'Environment="NODE_OPTIONS=--max-old-space-size=512 {FLAG}"'])

    def test_runtime_verification_prints_no_environment_values(self):
        cmd = _tasks("node_runtime.yml")[0]["ansible.builtin.shell"]["cmd"]
        self.assertIn('echo "pid=$pid flag=yes"', cmd)
        self.assertNotIn("cat /proc", cmd)
        self.assertIn(">/dev/null", cmd)



STUB_SYSTEMCTL = """#!/usr/bin/env python3
import json, os, sys
units = json.load(open(os.environ["CA_TRUST_TEST_UNITS"]))
args = sys.argv[1:]
if args[:1] == ["show"]:
    unit = units.get(args[1], {})
    for i, a in enumerate(args):
        if a == "-p":
            print(unit.get(args[i + 1], ""))
    sys.exit(0)
sys.exit(1)
"""


def _gnu_stat() -> str | None:
    import shutil

    for name in ("gstat", "stat"):
        path = shutil.which(name)
        if path and subprocess.run([path, "-c", "%Y", "/"], capture_output=True).returncode == 0:
            return path
    return None


@unittest.skipUnless(_gnu_stat(), "GNU stat needed")
class ShellBehaviourTests(unittest.TestCase):
    """Run the role's rendered shell snippets against a stub systemctl."""

    def setUp(self):
        import shutil

        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "systemctl").write_text(STUB_SYSTEMCTL)
        (bin_dir / "stat").write_text(f'#!/bin/sh\nexec {_gnu_stat()} "$@"\n')
        for stub in bin_dir.iterdir():
            stub.chmod(0o755)
        self.units = self.tmp / "units.json"
        self.env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                    "CA_TRUST_TEST_UNITS": str(self.units)}
        self.jinja = Environment(undefined=StrictUndefined)
        self.jinja.filters["quote"] = shlex.quote

    def _run(self, task_file, task_name, unit, **context):
        self.units.write_text(json.dumps({"app.service": unit}))
        task = next(t for t in _tasks(task_file) if t["name"] == task_name)
        variables = {"ca_trust_consumers_unit": {"name": "app.service"}, "ca_trust_consumers_node_flag": FLAG,
                     **context}
        for key, value in (task.get("vars") or {}).items():
            variables[key] = self.jinja.from_string(value).render(**variables)
        cmd = self.jinja.from_string(task["ansible.builtin.shell"]["cmd"]).render(**variables)
        import shutil

        result = subprocess.run([shutil.which("bash"), "-c", cmd], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_environment_files_with_blanks_unparsed_and_wildcards_are_refused(self):
        spaced = self.tmp / "app config.env"
        spaced.write_text("NODE_OPTIONS=--use-bundled-ca\n")
        clean = self.tmp / "clean.env"
        clean.write_text("PORT=1\n")
        name = "node_unit | Look for NODE_OPTIONS in the unit's environment files"
        out = self._run("node_unit.yml", name, {"EnvironmentFiles": f"{spaced} (ignore_errors=no)\n{clean} (ignore_errors=yes)"})
        self.assertEqual(out.splitlines(), [str(spaced)])
        out = self._run("node_unit.yml", name, {"EnvironmentFiles": "something odd"})
        self.assertIn("(unparsed entry)", out)
        out = self._run("node_unit.yml", name, {"EnvironmentFiles": f"{self.tmp}/*.env (ignore_errors=no)"})
        self.assertIn("(wildcard pattern)", out)
        out = self._run("node_unit.yml", name, {"EnvironmentFiles": f"{clean} (ignore_errors=no)"})
        self.assertEqual(out, "")

    def test_effective_value_handles_quoting_and_unset(self):
        name = "node_unit | Check the effective NODE_OPTIONS of the unit"
        quoted = f'"NODE_OPTIONS=--max-old-space-size=512 {FLAG}" PORT=1'
        self.assertEqual(self._run("node_unit.yml", name, {"Environment": quoted}).strip(), "effective=yes")
        self.assertEqual(self._run("node_unit.yml", name, {"Environment": "NODE_OPTIONS=--other"}).strip(),
                         "effective=no")
        unset = {"Environment": quoted, "UnsetEnvironment": f'"NODE_OPTIONS=--max-old-space-size=512 {FLAG}"'}
        self.assertEqual(self._run("node_unit.yml", name, unset).strip(), "effective=unset")

    def test_staged_check_sees_link_targets_blank_paths_and_unparsable_dropins(self):
        import time

        started = int(time.time()) - 1000
        old = started - 1000
        target = self.tmp / "real.env"
        target.write_text("A=1\n")
        link = self.tmp / "linked.env"
        link.symlink_to(target)
        os.utime(link, (old, old), follow_symlinks=False)
        spaced = self.tmp / "app config.env"
        spaced.write_text("A=1\n")
        quiet = self.tmp / "quiet.env"
        quiet.write_text("A=1\n")
        os.utime(quiet, (old, old))
        name = "restart_unit | Look for changes a restart would activate"
        context = {"_ca_trust_consumers_before": {"MainPID": "0"}, "_ca_trust_consumers_started": started,
                   "ca_trust_consumers_systemd_dir": "/etc/systemd/system",
                   "ca_trust_consumers_node_dropin_name": "99-ca-trust-node.conf"}
        unit = {"NeedDaemonReload": "no", "FragmentPath": "", "DropInPaths": "",
                "EnvironmentFiles": f"{link} (ignore_errors=no)\n{spaced} (ignore_errors=yes)\n{quiet} (ignore_errors=no)"}
        out = self._run("restart_unit.yml", name, unit, **context)
        self.assertIn(f"staged: {link} changed after the process started", out)
        self.assertIn(f"staged: {spaced} changed after the process started", out)
        self.assertNotIn(str(quiet), out)
        unit = {"NeedDaemonReload": "no", "FragmentPath": "", "DropInPaths": f"{self.tmp}/a b.conf",
                "EnvironmentFiles": "odd entry"}
        out = self._run("restart_unit.yml", name, unit, **context)
        self.assertIn("staged: cannot parse DropInPaths of app.service", out)
        self.assertIn("staged: cannot parse EnvironmentFiles entry of app.service", out)
        unit = {"NeedDaemonReload": "no", "FragmentPath": "", "DropInPaths": "", "EnvironmentFiles": ""}
        self.assertEqual(self._run("restart_unit.yml", name, unit, **context), "")

if __name__ == "__main__":
    unittest.main()
