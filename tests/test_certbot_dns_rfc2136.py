import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined

ROLE = Path(__file__).resolve().parents[1] / "roles" / "certbot_dns_deploy"


def render_credentials(**variables):
    environment = Environment(
        undefined=StrictUndefined,
        trim_blocks=True,
        keep_trailing_newline=True,
    )
    template = (ROLE / "templates" / "dns-credentials.ini.j2").read_text()
    return environment.from_string(template).render(**variables)


class CertbotDnsRfc2136Tests(unittest.TestCase):
    def test_rfc2136_credentials(self):
        text = render_credentials(
            certbot_dns_provider="rfc2136",
            certbot_dns_rfc2136_server="192.0.2.53",
            certbot_dns_rfc2136_port=53,
            certbot_dns_rfc2136_key_name="acme-home",
            certbot_dns_rfc2136_key_secret="FAKEKEYFORTESTSONLYNOTREALAAAAAAAAAAAAAAAAA=",
            certbot_dns_rfc2136_key_algorithm="hmac-sha256",
        )
        self.assertIn("dns_rfc2136_server = 192.0.2.53\n", text)
        self.assertIn("dns_rfc2136_port = 53\n", text)
        self.assertIn("dns_rfc2136_name = acme-home\n", text)
        self.assertIn("dns_rfc2136_secret = FAKEKEYFORTESTSONLYNOTREALAAAAAAAAAAAAAAAAA=\n", text)
        self.assertIn("dns_rfc2136_algorithm = HMAC-SHA256\n", text)
        self.assertNotIn("dns_gandi", text)

    def test_gandi_credentials_unchanged(self):
        text = render_credentials(
            certbot_dns_provider="gandi", certbot_dns_gandi_api_token="token"
        )
        self.assertIn("dns_gandi_api_key = token\n", text)
        self.assertNotIn("rfc2136", text)

    def test_defaults_keep_gandi_and_placeholders(self):
        defaults = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
        self.assertEqual(defaults["certbot_dns_provider"], "gandi")
        self.assertEqual(defaults["certbot_dns_rfc2136_key_secret"], "CHANGEME")
        self.assertTrue(defaults["certbot_dns_reconfigure_on_provider_change"])

    def test_secret_tasks_are_no_log(self):
        credentials = yaml.safe_load((ROLE / "tasks" / "credentials.yml").read_text())
        render = [t for t in credentials if t["name"] == "Render DNS credentials file"][0]
        self.assertTrue(render["no_log"])
        validate = yaml.safe_load((ROLE / "tasks" / "validate.yml").read_text())
        rfc = [t for t in validate if t["name"] == "Validate RFC 2136 settings"][0]
        self.assertTrue(rfc["no_log"])

    def test_providers_use_separate_credentials_files(self):
        defaults = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
        self.assertNotEqual(
            defaults["certbot_dns_credentials_file"],
            defaults["certbot_dns_rfc2136_credentials_file"],
        )
        credentials = yaml.safe_load((ROLE / "tasks" / "credentials.yml").read_text())
        render = [t for t in credentials if t["name"] == "Render DNS credentials file"][0]
        self.assertEqual(
            render["ansible.builtin.template"]["dest"],
            "{{ certbot_dns_active_credentials_file }}",
        )
        certificate = (ROLE / "tasks" / "certificate.yml").read_text()
        self.assertNotIn("certbot_dns_credentials_file", certificate)
        self.assertEqual(certificate.count("certbot_dns_active_credentials_file"), 2)

    def test_reconfigure_only_on_authenticator_change(self):
        tasks = yaml.safe_load((ROLE / "tasks" / "certificate.yml").read_text())
        switch = [t for t in tasks if t["name"] == "Switch the lineage to the configured DNS provider"][0]
        argv = switch["ansible.builtin.command"]["argv"]
        self.assertEqual(argv[:2], ["certbot", "reconfigure"])
        self.assertIn("certbot_dns_current_authenticator != 'dns-' ~ certbot_dns_provider", switch["when"])
        self.assertIn("not ansible_check_mode", switch["when"])

    def test_cleanup_runs_after_the_switch(self):
        main = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
        order = [t["ansible.builtin.import_tasks"] for t in main]
        self.assertLess(order.index("certificate.yml"), order.index("cleanup.yml"))
        defaults = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
        self.assertTrue(defaults["certbot_dns_remove_unused_credentials"])


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not on PATH")
class CertbotDnsCredentialsCleanupTests(unittest.TestCase):
    """Run cleanup.yml on localhost against a temporary /etc/letsencrypt."""

    def run_cleanup(self, provider, renewal_confs, enabled=True, check=False, prepare=None):
        tasks = yaml.safe_load((ROLE / "tasks" / "cleanup.yml").read_text())
        for task in tasks:
            task.pop("become", None)
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir)
            (config / "renewal").mkdir()
            gandi = config / "dns-credentials.ini"
            rfc2136 = config / "dns-rfc2136-credentials.ini"
            gandi.write_text("dns_gandi_api_key = old\n")
            rfc2136.write_text("dns_rfc2136_name = acme-home\n")
            for name, authenticator, credentials in renewal_confs:
                plugin = authenticator.removeprefix("dns-")
                (config / "renewal" / name).write_text(
                    "[renewalparams]\n"
                    f"authenticator = {authenticator}\n"
                    f"{authenticator.replace('-', '_')}_credentials = {config / credentials}\n"
                    f"dns_{plugin}_propagation_seconds = 120\n"
                )
            if prepare:
                prepare(config)
            active = rfc2136 if provider == "rfc2136" else gandi
            variables = {
                "certbot_dns_config_dir": str(config),
                "certbot_dns_credentials_file": str(gandi),
                "certbot_dns_rfc2136_credentials_file": str(rfc2136),
                "certbot_dns_active_credentials_file": str(active),
                "certbot_dns_remove_unused_credentials": enabled,
                "certbot_dns_provider": provider,
                "certbot_dns_domain": "home.example",
            }
            playbook = config / "play.yml"
            playbook.write_text(
                yaml.safe_dump(
                    [{"hosts": "localhost", "gather_facts": False, "vars": variables, "tasks": tasks}]
                )
            )
            command = ["ansible-playbook", "-i", "localhost,", "-c", "local", str(playbook)]
            if check:
                command.append("--check")
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.managed_conf = (config / "renewal" / "home.example.conf").read_text() if (
                config / "renewal" / "home.example.conf"
            ).exists() else ""
            return gandi.exists(), rfc2136.exists()

    def test_removes_the_old_provider_file_after_the_switch(self):
        gandi, rfc2136 = self.run_cleanup(
            "rfc2136", [("home.example.conf", "dns-rfc2136", "dns-rfc2136-credentials.ini")]
        )
        self.assertFalse(gandi)
        self.assertTrue(rfc2136)

    def test_drops_the_previous_plugin_settings_after_reconfigure(self):
        # certbot reconfigure leaves dns_gandi_* in the switched lineage.
        def add_stale_gandi(config):
            conf = config / "renewal" / "home.example.conf"
            conf.write_text(
                conf.read_text()
                + f"dns_gandi_credentials = {config / 'dns-credentials.ini'}\n"
                + "dns_gandi_propagation_seconds = 120\n"
            )

        gandi, rfc2136 = self.run_cleanup(
            "rfc2136",
            [("home.example.conf", "dns-rfc2136", "dns-rfc2136-credentials.ini")],
            prepare=add_stale_gandi,
        )
        self.assertFalse(gandi)
        self.assertTrue(rfc2136)
        self.assertNotIn("dns_gandi", self.managed_conf)
        self.assertIn("authenticator = dns-rfc2136\n", self.managed_conf)
        self.assertIn("dns_rfc2136_credentials = ", self.managed_conf)
        self.assertIn("dns_rfc2136_propagation_seconds = 120\n", self.managed_conf)

    def test_keeps_settings_of_a_lineage_not_yet_switched(self):
        # The lineage still authenticates with gandi (failed or skipped switch).
        def add_rfc2136(config):
            conf = config / "renewal" / "home.example.conf"
            conf.write_text(conf.read_text() + "dns_rfc2136_propagation_seconds = 120\n")

        gandi, _ = self.run_cleanup(
            "rfc2136",
            [("home.example.conf", "dns-gandi", "dns-credentials.ini")],
            prepare=add_rfc2136,
        )
        self.assertTrue(gandi)
        self.assertIn("dns_gandi_credentials = ", self.managed_conf)

    def test_keeps_a_file_a_lineage_still_uses(self):
        # A failed or check-mode switch leaves the lineage on the old provider.
        gandi, rfc2136 = self.run_cleanup(
            "rfc2136", [("home.example.conf", "dns-gandi", "dns-credentials.ini")]
        )
        self.assertTrue(gandi)
        self.assertTrue(rfc2136)

    def test_keeps_a_file_another_lineage_uses(self):
        gandi, _ = self.run_cleanup(
            "rfc2136",
            [
                ("home.example.conf", "dns-rfc2136", "dns-rfc2136-credentials.ini"),
                ("other.example.conf", "dns-gandi", "dns-credentials.ini"),
            ],
        )
        self.assertTrue(gandi)

    def test_never_removes_the_active_file(self):
        gandi, rfc2136 = self.run_cleanup(
            "gandi", [("home.example.conf", "dns-gandi", "dns-credentials.ini")]
        )
        self.assertTrue(gandi)
        self.assertFalse(rfc2136)

    def test_keeps_the_file_when_the_scan_is_incomplete(self):
        # An unreadable configuration must not count as "no lineage uses it".
        def make_unreadable(config):
            bad = config / "renewal" / "aaa-unreadable.conf"
            bad.write_text(f"dns_gandi_credentials = {config / 'dns-credentials.ini'}\n")
            bad.chmod(0)

        gandi, _ = self.run_cleanup(
            "rfc2136",
            [("home.example.conf", "dns-rfc2136", "dns-rfc2136-credentials.ini")],
            prepare=make_unreadable,
        )
        self.assertTrue(gandi)

    def test_follows_symlinked_renewal_configurations(self):
        def link_gandi_lineage(config):
            target = config / "elsewhere.conf"
            target.write_text(f"dns_gandi_credentials = {config / 'dns-credentials.ini'}\n")
            (config / "renewal" / "other.example.conf").symlink_to(target)

        gandi, _ = self.run_cleanup(
            "rfc2136",
            [("home.example.conf", "dns-rfc2136", "dns-rfc2136-credentials.ini")],
            prepare=link_gandi_lineage,
        )
        self.assertTrue(gandi)

    def test_opt_out_and_check_mode_keep_files(self):
        confs = [("home.example.conf", "dns-rfc2136", "dns-rfc2136-credentials.ini")]
        self.assertEqual(self.run_cleanup("rfc2136", confs, enabled=False), (True, True))
        self.assertEqual(self.run_cleanup("rfc2136", confs, check=True), (True, True))


if __name__ == "__main__":
    unittest.main()
