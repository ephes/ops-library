"""homeassistant_deploy: the managed UV_SYSTEM_CERTS=1 drop-in and its checks.

files/uv_system_certs_check.py runs against a fake ``systemctl`` (on PATH)
and a fake ``/proc``; the wiring tests check task order; the collection
loader runs python_security_floor's system_store.yml against real CA files.
"""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/homeassistant_deploy"
CHECK = ROLE / "files/uv_system_certs_check.py"
TEMPLATE = ROLE / "templates/uv-system-certs.conf.j2"
FIXTURES = ROOT / "tests/fixtures/python_security"
SECRET = "s3cr3t-value-never-printed"

FAKE_SYSTEMCTL = textwrap.dedent(
    """\
    #!{python}
    import json, os, sys
    scenario = json.load(open(os.environ["FAKE_SYSTEMD"]))
    if sys.argv[1] == "show-environment":
        print(scenario["manager"], end="")
    elif sys.argv[1] == "show":
        for arg in sys.argv[3:]:
            name = arg.split("=", 1)[1]
            print(name + "=" + scenario["unit"].get(name, ""))
    else:
        sys.exit(2)
    """
)


class CheckScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ops-library-ha-uv-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "systemctl"
        fake.write_text(FAKE_SYSTEMCTL.format(python=sys.executable))
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        self.path = f"{bin_dir}:{os.environ['PATH']}"
        self.dropin = self.tmp / "homeassistant.service.d/50-uv-system-certs.conf"
        self.proc = self.tmp / "proc"
        self.managed_sha = hashlib.sha256(TEMPLATE.read_bytes()).hexdigest()

    def install_dropin(self, content=None):
        self.dropin.parent.mkdir(parents=True, exist_ok=True)
        self.dropin.write_bytes(TEMPLATE.read_bytes() if content is None else content)

    def run_check(self, mode, *, unit=None, manager="LANG=C.UTF-8\nPATH=/usr/bin\n", environ=None, extra=()):
        dropin_live = self.dropin.exists()
        props = {
            "LoadState": "loaded",
            "ActiveState": "active",
            "NeedDaemonReload": "no",
            "DropInPaths": str(self.dropin) if dropin_live else "",
            "EnvironmentFiles": "",
            "Environment": "PATH=/srv/venv/bin:/usr/bin HOME=/home/ha" + (" UV_SYSTEM_CERTS=1" if dropin_live else ""),
            "PassEnvironment": "",
            "MainPID": "4242" if environ is not None else "0",
        }
        props.update(unit or {})
        if environ is not None:
            (self.proc / "4242").mkdir(parents=True, exist_ok=True)
            (self.proc / "4242/environ").write_bytes("\0".join(environ).encode() + b"\0")
        scenario = self.tmp / "scenario.json"
        scenario.write_text(json.dumps({"unit": props, "manager": manager}))
        result = subprocess.run(
            [sys.executable, "-I", str(CHECK), "--unit", "homeassistant.service", "--dropin", str(self.dropin),
             "--dropin-sha256", self.managed_sha, "--mode", mode, "--proc", str(self.proc), *extra],
            env={"PATH": self.path, "FAKE_SYSTEMD": str(scenario)},
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertNotIn(SECRET, result.stdout)
        return json.loads(result.stdout)

    PLAIN = ["PATH=/srv/venv/bin:/usr/bin", "HOME=/home/ha", f"API_TOKEN={SECRET}"]

    def test_clean_unit_passes_preflight(self):
        report = self.run_check("preflight", environ=self.PLAIN)
        self.assertEqual(report["problems"], [])
        self.assertFalse(report["managed_dropin"])

    def test_missing_unit_only_allowed_when_asked_in_preflight(self):
        unit = {"LoadState": "not-found", "MainPID": "0"}
        self.assertEqual(self.run_check("preflight", unit=unit, extra=["--allow-missing-unit"])["problems"], [])
        self.assertEqual(self.run_check("preflight", unit=unit)["problems"], ["homeassistant.service is not-found"])
        self.assertEqual(
            self.run_check("verify", unit=unit, extra=["--allow-missing-unit"])["problems"],
            ["homeassistant.service is not-found"],
        )

    def test_repeat_with_own_managed_setting_passes_and_verifies(self):
        self.install_dropin()
        environ = [*self.PLAIN, "UV_SYSTEM_CERTS=1"]
        self.assertEqual(self.run_check("preflight", environ=environ)["problems"], [])
        report = self.run_check("verify", environ=environ)
        self.assertEqual(report["problems"], [])
        self.assertTrue(report["managed_dropin"] and report["running_managed_value"])

    def test_unreadable_running_environment_fails_closed(self):
        report = self.run_check("preflight", unit={"MainPID": "4243"})
        self.assertEqual(report["problems"], ["the running service's environment could not be read (FileNotFoundError)"])

    def test_verify_needs_the_running_value(self):
        self.install_dropin()
        report = self.run_check("verify", environ=self.PLAIN)
        self.assertEqual(report["problems"], ["the running service does not have the managed UV_SYSTEM_CERTS=1"])

    def test_custom_trust_in_the_running_service_is_refused(self):
        for key in ("SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "UV_NATIVE_TLS", "UV_INSECURE_HOST"):
            report = self.run_check("preflight", environ=[*self.PLAIN, f"{key}={SECRET}"])
            self.assertEqual(report["problems"], [f"the running service has {key}"], key)

    def test_uv_system_certs_without_the_managed_dropin_is_refused(self):
        report = self.run_check("preflight", environ=[*self.PLAIN, "UV_SYSTEM_CERTS=1"])
        self.assertEqual(report["problems"], ["the running service has UV_SYSTEM_CERTS without the managed drop-in"])
        self.install_dropin()
        report = self.run_check("preflight", environ=[*self.PLAIN, "UV_SYSTEM_CERTS=0"])
        self.assertEqual(report["problems"], ["the running service has UV_SYSTEM_CERTS without the managed drop-in"])

    def test_modified_dropin_is_refused(self):
        self.install_dropin(b"[Service]\nEnvironment=SSL_CERT_FILE=/opt/custom.pem\n")
        unit = {"Environment": "PATH=/usr/bin SSL_CERT_FILE=/opt/custom.pem"}
        report = self.run_check("preflight", unit=unit, environ=self.PLAIN)
        self.assertEqual(
            report["problems"],
            [f"{self.dropin} differs from the managed drop-in", "homeassistant.service sets SSL_CERT_FILE"],
        )

    def test_environment_files_and_other_dropins_are_refused(self):
        report = self.run_check("preflight", unit={"EnvironmentFiles": "/etc/ha.env (ignore_errors=no)"})
        self.assertEqual(report["problems"], ["homeassistant.service reads an EnvironmentFile; trust precedence is uncertain"])
        other = "/usr/lib/systemd/system/service.d/10-timeout-abort.conf"
        report = self.run_check("preflight", unit={"DropInPaths": other})
        self.assertEqual(report["problems"], [f"homeassistant.service has other drop-ins: {other}"])
        allowed = self.run_check("preflight", unit={"DropInPaths": other}, extra=[f"--allow-dropin={other}"])
        self.assertEqual(allowed["problems"], [])

    def test_trust_in_the_parsed_unit_environment_is_refused(self):
        # systemd's own parse covers spacing, quoting, continuation lines and drop-ins.
        quoted = f'PATH=/usr/bin "SSL_CERT_FILE=/opt/my ca/{SECRET}.pem" HOME=/home/ha'
        report = self.run_check("preflight", unit={"Environment": quoted})
        self.assertEqual(report["problems"], ["homeassistant.service sets SSL_CERT_FILE"])
        report = self.run_check("preflight", unit={"PassEnvironment": "LANG SSL_CERT_DIR"})
        self.assertEqual(report["problems"], ["homeassistant.service sets SSL_CERT_DIR"])

    def test_managed_value_in_the_parsed_environment_is_accepted_only_as_managed(self):
        self.install_dropin()
        self.assertEqual(self.run_check("preflight")["problems"], [])
        report = self.run_check("preflight", unit={"Environment": "UV_SYSTEM_CERTS=1 UV_SYSTEM_CERTS=0"})
        self.assertEqual(report["problems"], ["homeassistant.service sets UV_SYSTEM_CERTS"])

    def test_unreloaded_unit_is_refused(self):
        report = self.run_check("preflight", unit={"NeedDaemonReload": "yes"})
        self.assertEqual(report["problems"], ["homeassistant.service changed on disk since systemd loaded it; reload first"])

    def test_manager_environment_is_refused(self):
        report = self.run_check("preflight", manager=f"PATH=/usr/bin\nSSL_CERT_DIR={SECRET}\n")
        self.assertEqual(report["problems"], ["the service manager environment sets SSL_CERT_DIR"])

    def test_first_deploy_still_checks_the_manager_and_the_managed_path(self):
        unit = {"LoadState": "not-found", "MainPID": "0"}
        report = self.run_check("preflight", unit=unit, manager=f"SSL_CERT_FILE={SECRET}\n", extra=["--allow-missing-unit"])
        self.assertEqual(report["problems"], ["the service manager environment sets SSL_CERT_FILE"])
        self.install_dropin(b"[Service]\nEnvironment=SSL_CERT_FILE=/opt/custom.pem\n")
        report = self.run_check("preflight", unit=unit, extra=["--allow-missing-unit"])
        self.assertEqual(report["problems"], [f"{self.dropin} differs from the managed drop-in"])


class TemplateAndWiringTests(unittest.TestCase):
    def test_template_is_the_one_line_setting_and_static(self):
        text = TEMPLATE.read_text()
        self.assertNotIn("{{", text)
        self.assertNotIn("{%", text)
        body = [line for line in text.splitlines() if line and not line.startswith("#")]
        self.assertEqual(body, ["[Service]", "Environment=UV_SYSTEM_CERTS=1"])

    def names(self, path):
        return [t["name"] for t in yaml.safe_load((ROLE / path).read_text())]

    def test_deploy_order(self):
        names = self.names("tasks/main.yml")
        order = [
            "Run Home Assistant validation tasks",
            "Check the unit's trust settings before the UV_SYSTEM_CERTS drop-in",
            "Check the system CA store for the UV_SYSTEM_CERTS drop-in",
            "Install required packages",
            "Install systemd service",
            "Install the managed UV_SYSTEM_CERTS drop-in",
            "Reload and restart for a changed UV_SYSTEM_CERTS drop-in",
            "Apply pending handlers before verifying UV_SYSTEM_CERTS",
            "Verify the running service has the managed UV_SYSTEM_CERTS",
        ]
        positions = [names.index(n) for n in order]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(names[-1], order[-1])
        tasks = {t["name"]: t for t in yaml.safe_load((ROLE / "tasks/main.yml").read_text())}
        self.assertEqual(tasks[order[1]]["vars"], {"_ha_uv_certs_mode": "preflight", "_ha_uv_certs_allow_missing": True})
        self.assertEqual(tasks[order[6]]["notify"], ["reload systemd", "restart homeassistant"])

    def test_maintenance_entry_point_order_and_scope(self):
        tasks = yaml.safe_load((ROLE / "tasks/uv_system_certs.yml").read_text())
        names = [t["name"].split(" | ", 1)[1] for t in tasks]
        self.assertEqual(
            names,
            [
                "Require the feature to be enabled",
                "Check the existing unit before any change",
                "Check the system CA store the drop-in points uv at",
                "Install the managed drop-in",
                "Restart Home Assistant for the new drop-in",
                "Wait for Home Assistant",
                "Verify the running service",
            ],
        )
        self.assertNotIn("_ha_uv_certs_allow_missing", json.dumps(tasks))
        self.assertEqual(tasks[4]["when"], "_ha_uv_certs_dropin is changed")
        # Only the drop-in: no package, source or unit file tasks are reachable.
        text = (ROLE / "tasks/uv_system_certs.yml").read_text() + (ROLE / "tasks/uv_system_certs_dropin.yml").read_text()
        for forbidden in ("pip", "python.yml", "systemd.yml", "homeassistant.service.j2", "configuration"):
            self.assertNotIn(forbidden, text)

    def test_inspection_task_is_no_log(self):
        (inspect, _) = yaml.safe_load((ROLE / "tasks/uv_system_certs_check.yml").read_text())
        self.assertTrue(inspect["no_log"])


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook is required")
class ManagedHashTests(unittest.TestCase):
    """The hash the check expects equals the bytes the template module writes."""

    def test_lookup_hash_matches_the_written_dropin(self):
        with tempfile.TemporaryDirectory(prefix="ops-library-ha-hash-") as tmp:
            (Path(tmp) / "templates").mkdir()
            shutil.copy(TEMPLATE, Path(tmp) / "templates" / TEMPLATE.name)
            out = Path(tmp) / "written.conf"
            (Path(tmp) / "play.yml").write_text(
                textwrap.dedent(
                    f"""\
                    - hosts: localhost
                      gather_facts: false
                      tasks:
                        - ansible.builtin.template:
                            src: {TEMPLATE.name}
                            dest: {out}
                            mode: "0644"
                        - ansible.builtin.copy:
                            content: "{{{{ lookup('ansible.builtin.template', '{TEMPLATE.name}') | hash('sha256') }}}}"
                            dest: {tmp}/lookup.sha
                            mode: "0644"
                    """
                )
            )
            subprocess.run(
                ["ansible-playbook", "-i", "localhost,", "-c", "local", "play.yml"], cwd=tmp, check=True, capture_output=True
            )
            written = hashlib.sha256(out.read_bytes()).hexdigest()
            self.assertEqual(written, hashlib.sha256(TEMPLATE.read_bytes()).hexdigest())
            self.assertEqual((Path(tmp) / "lookup.sha").read_text().strip(), written)


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook is required")
class SystemStoreTests(unittest.TestCase):
    """python_security_floor system_store.yml through the collection loader."""

    def play(self, ca_file, dirs=()):
        collections = subprocess.run(
            [str(ROOT / "scripts/checkout-collections-path.sh")], check=True, capture_output=True, text=True
        ).stdout.strip()
        with tempfile.TemporaryDirectory(prefix="ops-library-store-") as tmp:
            play = Path(tmp) / "play.yml"
            play.write_text(
                textwrap.dedent(
                    f"""\
                    - hosts: localhost
                      gather_facts: false
                      tasks:
                        - ansible.builtin.include_role:
                            name: local.ops_library.python_security_floor
                            tasks_from: system_store.yml
                          vars:
                            python_security_floor_become: false
                            python_security_floor_system_python: {sys.executable}
                            python_security_floor_system_store: {ca_file}
                            python_security_floor_system_store_dirs: {json.dumps([str(d) for d in dirs])}
                    """
                )
            )
            return subprocess.run(
                ["ansible-playbook", "-i", "localhost,", "-c", "local", str(play)],
                capture_output=True,
                text=True,
                env={**os.environ, "ANSIBLE_COLLECTIONS_PATH": collections},
            )

    def test_distrusted_root_in_a_certificate_directory_is_refused(self):
        import certifi

        with tempfile.TemporaryDirectory(prefix="ops-library-ca-") as tmp:
            good = Path(tmp) / "good.pem"
            good.write_bytes(Path(certifi.where()).read_bytes())
            certs = Path(tmp) / "certs"
            certs.mkdir()
            (certs / "README").write_text("not a certificate\n")
            (certs / "ok.pem").write_bytes(Path(certifi.where()).read_bytes())
            self.assertEqual(self.play(good, [certs]).returncode, 0)
            (certs / "emsign.pem").write_text((FIXTURES / "emsign-ecc-g3-trusted.txt").read_text())
            (certs / "0123abcd.0").symlink_to("emsign.pem")
            result = self.play(good, [certs, Path(tmp) / "missing"])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("still trusts emSign ECC Root CA - G3", result.stdout)

    def test_mixed_valid_and_malformed_pem_fails_closed(self):
        import certifi

        with tempfile.TemporaryDirectory(prefix="ops-library-ca-") as tmp:
            good = Path(tmp) / "good.pem"
            good.write_bytes(Path(certifi.where()).read_bytes())
            certs = Path(tmp) / "certs"
            certs.mkdir()
            (certs / "mixed.pem").write_text(
                (FIXTURES / "emsign-ecc-g3-trusted.txt").read_text()
                + "-----BEGIN CERTIFICATE-----\nnot base64 at all\n-----END CERTIFICATE-----\n"
            )
            result = self.play(good, [certs])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("PEM content OpenSSL cannot load", result.stdout)

    def test_store_with_a_distrusted_root_is_refused_and_a_clean_one_passes(self):
        with tempfile.TemporaryDirectory(prefix="ops-library-ca-") as tmp:
            bad = Path(tmp) / "bad.pem"
            bad.write_text((FIXTURES / "emsign-ecc-g3-trusted-noncanonical.txt").read_text())
            result = self.play(bad)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("still trusts emSign ECC Root CA - G3", result.stdout)
            import certifi

            good = Path(tmp) / "good.pem"
            good.write_bytes(Path(certifi.where()).read_bytes())
            result = self.play(good)
            self.assertEqual(result.returncode, 0, result.stdout[-3000:])


if __name__ == "__main__":
    unittest.main()
