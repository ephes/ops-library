"""Run ca_trust_consumers task files through ansible-playbook and the collection loader.

The role's own expressions (FQCN filters, the readiness gate, the restart
decision) run for real in check mode on localhost. systemctl, dpkg-query and
dpkg are stubs on PATH; the CA store and /etc/environment are temp files.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOOD = b"\x30\x03\x02\x01\x02"
BAD = b"\x30\x03\x02\x01\x01"


def _pem(der: bytes) -> str:
    return "-----BEGIN CERTIFICATE-----\n" + base64.encodebytes(der).decode() + "-----END CERTIFICATE-----\n"


SYSTEMCTL = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json, os, sys
    units = json.load(open(os.environ["CA_TRUST_TEST_UNITS"]))
    args = sys.argv[1:]
    if args[:1] == ["show"]:
        unit = units.get(args[1], {"LoadState": "not-found", "ActiveState": "inactive", "MainPID": "0"})
        props = [args[i + 1] for i, a in enumerate(args) if a == "-p"]
        value_only = "--value" in args
        for prop in props:
            value = unit.get(prop, "")
            print(value if value_only else f"{prop}={value}")
        sys.exit(0)
    sys.exit(1)
    """
)


def _ansible_playbook() -> str | None:
    candidate = Path(sys.executable).with_name("ansible-playbook")
    return str(candidate) if candidate.exists() else shutil.which("ansible-playbook")


@unittest.skipUnless(_ansible_playbook(), "ansible-playbook not installed")
@unittest.skipUnless(Path("/usr/bin/python3").exists(), "role runs its checker with /usr/bin/python3")
class RoleRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        collections = self.tmp / "collections/ansible_collections/local"
        collections.mkdir(parents=True)
        (collections / "ops_library").symlink_to(ROOT)
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        stubs = {
            "systemctl": SYSTEMCTL,
            "dpkg-query": "#!/bin/sh\necho 'install ok installed 20260816ubuntu0.24.04.1'\n",
            # dpkg --compare-versions A ge B: CA_TRUST_TEST_GE decides.
            "dpkg": "#!/bin/sh\nexit \"${CA_TRUST_TEST_GE:-0}\"\n",
        }
        for name, body in stubs.items():
            path = bin_dir / name
            path.write_text(body)
            path.chmod(0o755)
        self.certs = self.tmp / "certs"
        self.certs.mkdir()
        (self.certs / "good.pem").write_text(_pem(GOOD))
        self.bundle = self.tmp / "ca-certificates.crt"
        self.bundle.write_text(_pem(GOOD))
        self.bundle_mtime = int(time.time()) - 600
        os.utime(self.bundle, (self.bundle_mtime, self.bundle_mtime))
        self.envfile = self.tmp / "environment"
        self.envfile.write_text('PATH="/usr/bin"\nNODE_OPTIONS="--max-old-space-size=1536"\n')
        self.units = self.tmp / "units.json"
        self.units.write_text(json.dumps({
            "old.service": {"LoadState": "loaded", "ActiveState": "active", "MainPID": "4242",
                            "ExecMainStartTimestamp": f"@{self.bundle_mtime - 3600}", "NRestarts": "0",
                            "NeedDaemonReload": "no"},
            "fresh.service": {"LoadState": "loaded", "ActiveState": "active", "MainPID": "4343",
                              "ExecMainStartTimestamp": f"@{self.bundle_mtime + 60}", "NRestarts": "0"},
            "stopped.service": {"LoadState": "loaded", "ActiveState": "inactive", "MainPID": "0",
                                "ExecMainStartTimestamp": "", "NRestarts": "0"},
        }))
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}",
            "ANSIBLE_COLLECTIONS_PATH": str(self.tmp / "collections"),
            "ANSIBLE_NOCOLOR": "1",
            "ANSIBLE_STDOUT_CALLBACK": "default",
            "ANSIBLE_LOCALHOST_WARNING": "0",
            "ANSIBLE_INVENTORY_UNPARSED_WARNING": "0",
            "CA_TRUST_TEST_UNITS": str(self.units),
        }

    def _run(self, *, ge: int = 0) -> subprocess.CompletedProcess:
        fingerprint = hashlib.sha256(BAD).hexdigest().upper()
        playbook = self.tmp / "play.yml"
        playbook.write_text(textwrap.dedent(f"""\
            - hosts: localhost
              connection: local
              gather_facts: true
              vars:
                ca_trust_consumers_ca_min_version: "20260816ubuntu0.24.04.1"
                ca_trust_consumers_forbidden_root_sha256: ["{fingerprint}"]
                ca_trust_consumers_root_paths: ["{self.bundle}", "{self.certs}"]
                ca_trust_consumers_ca_bundle: "{self.bundle}"
                ca_trust_consumers_environment_file: "{self.envfile}"
                ca_trust_consumers_node_dropin_name: 50-ca-trust-node.conf
              tasks:
                - ansible.builtin.include_role:
                    name: local.ops_library.ca_trust_consumers
                    tasks_from: "{{{{ item }}}}"
                  loop: [preflight.yml, node_cli.yml]
                - ansible.builtin.include_role:
                    name: local.ops_library.ca_trust_consumers
                    tasks_from: restart_unit.yml
                  loop: [{{name: old.service}}, {{name: fresh.service}}, {{name: stopped.service}}]
                  loop_control: {{loop_var: ca_trust_consumers_unit}}
                  vars:
                    ca_trust_consumers_unit_is_node: false
            """))
        return subprocess.run(
            [_ansible_playbook(), "-i", "localhost,", str(playbook), "--check", "--diff",
             "-e", f"ansible_python_interpreter={sys.executable}"],
            env={**self.env, "CA_TRUST_TEST_GE": str(ge)}, capture_output=True, text=True, check=False,
            cwd=self.tmp,
        )

    def test_ready_host_merges_node_options_and_plans_only_stale_running_units(self) -> None:
        result = self._run()
        out = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, out[-4000:])
        self.assertIn("No forbidden root among 2 certificates", out)
        self.assertIn('+NODE_OPTIONS="--max-old-space-size=1536 --use-openssl-ca"', out)
        self.assertIn('-NODE_OPTIONS="--max-old-space-size=1536"', out)
        self.assertIn("old.service: WOULD RESTART (check mode)", out)
        self.assertIn("fresh.service: started after the CA bundle changed, no restart needed", out)
        self.assertIn("stopped.service: inactive, not started by this role", out)
        self.assertIn('NODE_OPTIONS="--max-old-space-size=1536"', self.envfile.read_text())

    def test_restart_that_would_activate_staged_unit_change_is_refused(self) -> None:
        units = json.loads(self.units.read_text())
        units["old.service"]["NeedDaemonReload"] = "yes"
        self.units.write_text(json.dumps(units))
        result = self._run()
        out = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("old.service was not restarted: staged: unit needs daemon-reload", out)

    def test_forbidden_root_stops_before_any_change(self) -> None:
        (self.certs / "14bc7599.0").write_text(_pem(BAD))
        result = self._run()
        out = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Forbidden roots are still visible", out)
        self.assertNotIn("+NODE_OPTIONS", out)
        self.assertNotIn("WOULD RESTART", out)

    def test_old_ca_package_stops_before_any_change(self) -> None:
        result = self._run(ge=1)
        out = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is older than 20260816ubuntu0.24.04.1", out)
        self.assertNotIn("+NODE_OPTIONS", out)


if __name__ == "__main__":
    unittest.main()
