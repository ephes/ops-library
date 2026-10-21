"""ca_trust_consumers: NODE_OPTIONS merging, forbidden-root scan, gate order."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import os
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
    DROPIN = "/etc/systemd/system/app.service.d/50-ca-trust-node.conf"

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
        later = [task.get("ansible.builtin.import_tasks") or task.get("ansible.builtin.include_tasks") for task in main[2:]]
        self.assertEqual(
            later, ["node_cli.yml", "node_unit.yml", "restart_unit.yml", "restart_unit.yml", "verify_node_unit.yml"]
        )
        node_restart, other_restart = main[4], main[5]
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
        for needle in ('*" (deleted)")', "NeedDaemonReload", "FragmentPath", "DropInPaths", "guard_paths", 'stat -c %Y "$path"'):
            self.assertIn(needle, cmd)
        self.assertNotIn("stat -L", cmd)  # a retargeted symlink must count
        self.assertIn("_own_dropin", cmd)
        guard = tasks[refuse]
        self.assertEqual(guard["ansible.builtin.assert"]["that"], "_ca_trust_consumers_staged.stdout | trim | length == 0")
        self.assertIn("not (ca_trust_consumers_unit.allow_staged_changes | default(false) | bool)", guard["when"])

    def test_node_unit_refuses_environment_file_override(self):
        tasks = _tasks("node_unit.yml")
        refuse = next(t for t in tasks if t["name"].endswith("Refuse to override NODE_OPTIONS from an environment file"))
        self.assertIn("stdout | trim | length == 0", refuse["ansible.builtin.assert"]["that"])
        look = next(t for t in tasks if t["name"].endswith("Look for NODE_OPTIONS in the unit's environment files"))
        self.assertIn("grep -l", look["ansible.builtin.shell"]["cmd"])  # file names only, never values

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


if __name__ == "__main__":
    unittest.main()
