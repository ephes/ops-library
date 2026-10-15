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


if __name__ == "__main__":
    unittest.main()
