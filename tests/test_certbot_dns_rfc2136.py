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


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not on PATH")
class CertbotDnsStrayConfigDirTests(unittest.TestCase):
    """Run stray.yml on localhost against temporary certbot trees."""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name).resolve()
        self.live = self.root / "live-config"
        (self.live / "renewal").mkdir(parents=True)
        (self.live / "renewal" / "home.example.conf").write_text(
            "[renewalparams]\n"
            f"cert = {self.live}/live/home.example/cert.pem\n"
            f"config_dir = {self.live}\n"
        )

    def tearDown(self):
        self._temp.cleanup()

    def make_tree(self, path, renewal=True):
        path.mkdir(parents=True)
        if renewal:
            (path / "renewal").mkdir()
            (path / "renewal" / "home.example.conf").write_text("authenticator = dns-gandi\n")
        (path / "dns-credentials.ini").write_text("dns_gandi_api_key = old\n")
        return path

    def run_stray(self, stray, check=False):
        tasks = yaml.safe_load((ROLE / "tasks" / "stray.yml").read_text())
        for task in tasks:
            task.pop("become", None)
        variables = {
            "certbot_dns_config_dir": str(self.live),
            "certbot_dns_stray_config_dirs": [str(p) for p in stray],
            "role_path": str(ROLE),
        }
        playbook = self.root / "play.yml"
        playbook.write_text(
            yaml.safe_dump([{"hosts": "localhost", "gather_facts": False, "vars": variables, "tasks": tasks}])
        )
        command = ["ansible-playbook", "-i", "localhost,", "-c", "local", str(playbook)]
        if check:
            command.append("--check")
        return subprocess.run(command, capture_output=True, text=True)

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def assert_refused(self, result):
        # A refusal must come from a guard, not from an unrelated error.
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Refusing stray certbot dir", result.stdout + result.stderr)

    def test_removes_a_listed_stray_tree(self):
        stray = self.make_tree(self.root / "letsencrypt")
        self.assert_ok(self.run_stray([stray]))
        self.assertFalse(stray.exists())
        self.assertTrue((self.live / "renewal" / "home.example.conf").exists())

    def test_check_mode_and_empty_list_keep_everything(self):
        stray = self.make_tree(self.root / "letsencrypt")
        self.assert_ok(self.run_stray([stray], check=True))
        self.assertTrue(stray.exists())
        self.assert_ok(self.run_stray([]))
        self.assertTrue(stray.exists())

    def test_skips_a_missing_path(self):
        self.assert_ok(self.run_stray([self.root / "gone"]))

    def test_refuses_the_live_dir_its_parent_and_its_children(self):
        child = self.make_tree(self.live / "nested")
        for path in (self.live, self.root, child):
            self.assert_refused(self.run_stray([path]))
        self.assertTrue(child.exists())
        self.assertTrue(self.live.exists())

    def test_refuses_certbot_default_dirs_and_unnormalized_paths(self):
        for path in ("/etc/letsencrypt", "/etc", "/", "/var/lib/letsencrypt/x",
                     f"{self.root}/a/../live-config", f"{self.root}/le*", f"{self.root}/x/", "relative"):
            self.assert_refused(self.run_stray([path]))
        self.assertTrue(self.live.exists())

    def test_refuses_a_path_that_reaches_the_live_dir_through_a_symlink(self):
        (self.root / "link").symlink_to(self.live)
        target = self.make_tree(self.live / "sub")
        self.assert_refused(self.run_stray([self.root / "link" / "sub"]))
        self.assertTrue(target.exists())

    def test_refuses_a_symlink_and_a_non_certbot_dir(self):
        real = self.make_tree(self.root / "real")
        link = self.root / "letsencrypt"
        link.symlink_to(real)
        self.assert_refused(self.run_stray([link]))
        plain = self.make_tree(self.root / "plain", renewal=False)
        self.assert_refused(self.run_stray([plain]))
        self.assertTrue(real.exists())
        self.assertTrue(plain.exists())

    def test_refuses_a_tree_a_live_renewal_configuration_uses(self):
        stray = self.make_tree(self.root / "le.old")
        conf = self.live / "renewal" / "home.example.conf"
        conf.write_text(conf.read_text() + f"dns_gandi_credentials = {stray}/dns-credentials.ini\n")
        self.assert_refused(self.run_stray([stray]))
        self.assertTrue(stray.exists())
        conf.write_text(conf.read_text() + f"archive_dir = {stray}\n")
        self.assert_refused(self.run_stray([stray]))

    def test_refuses_when_the_live_scan_fails(self):
        stray = self.make_tree(self.root / "letsencrypt")
        (self.live / "renewal" / "home.example.conf").unlink()
        self.assert_refused(self.run_stray([stray]))
        self.assertTrue(stray.exists())

    def test_a_self_contained_live_tree_allows_removal(self):
        # URLs are not paths; certbot's relative live -> archive links stay inside.
        stray = self.make_tree(self.root / "le.old")
        (self.live / "archive" / "home.example").mkdir(parents=True)
        (self.live / "archive" / "home.example" / "cert1.pem").write_text("x")
        (self.live / "live" / "home.example").mkdir(parents=True)
        (self.live / "live" / "home.example" / "cert.pem").symlink_to("../../archive/home.example/cert1.pem")
        conf = self.live / "renewal" / "home.example.conf"
        conf.write_text(
            conf.read_text()
            + "server = https://acme-v02.api.letsencrypt.org/directory\n"
            + f"archive_dir = {self.live}/archive/home.example\n"
        )
        self.assert_ok(self.run_stray([stray]))
        self.assertFalse(stray.exists())

    def test_refuses_when_a_live_tree_reaches_outside(self):
        stray = self.make_tree(self.root / "stray")
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        conf = self.live / "renewal" / "home.example.conf"
        original = conf.read_text()
        conf.write_text(original + f"x = {elsewhere}/file\n")
        self.assert_refused(self.run_stray([stray]))
        conf.write_text(original)
        (self.live / "link").symlink_to(elsewhere)
        self.assert_refused(self.run_stray([stray]))
        self.assertTrue(stray.exists())

    def test_refuses_a_symlink_chain_through_the_candidate(self):
        # live/renewal-hooks -> stray/bridge -> live/hooks: ends inside, passes through.
        stray = self.make_tree(self.root / "stray")
        (self.live / "hooks").mkdir()
        (stray / "bridge").symlink_to(self.live / "hooks")
        (self.live / "renewal-hooks").symlink_to(stray / "bridge")
        self.assert_refused(self.run_stray([stray]))
        self.assertTrue(stray.exists())

    def test_refuses_a_path_ending_in_a_newline(self):
        stray = self.make_tree(self.root / "stray\n")
        self.assert_refused(self.run_stray([stray]))
        self.assertTrue(stray.exists())

    def test_refuses_a_tree_a_live_symlink_points_into(self):
        # The live archive is a symlink into the candidate; the renewal
        # configuration names only the live path.
        stray = self.make_tree(self.root / "stray")
        (stray / "archive").mkdir()
        (self.live / "archive").symlink_to(stray / "archive")
        self.assert_refused(self.run_stray([stray]))
        self.assertTrue(stray.exists())

    def test_refuses_a_tree_reached_through_a_symlinked_parent(self):
        # Listed as /alias/stray, referenced as /storage/stray.
        storage = self.root / "storage"
        stray = self.make_tree(storage / "stray")
        (self.root / "alias").symlink_to(storage)
        conf = self.live / "renewal" / "home.example.conf"
        conf.write_text(conf.read_text() + f"dns_gandi_credentials = {stray}/dns-credentials.ini\n")
        self.assert_refused(self.run_stray([self.root / "alias" / "stray"]))
        self.assertTrue(stray.exists())

    def test_refuses_quoted_references(self):
        stray = self.make_tree(self.root / "stray")
        conf = self.live / "renewal" / "home.example.conf"
        original = conf.read_text()
        for quote in ('"', "'"):
            conf.write_text(original + f"dns_gandi_credentials = {quote}{stray}/dns-credentials.ini{quote}\n")
            self.assert_refused(self.run_stray([stray]))
            self.assertTrue(stray.exists())

    def test_refuses_paths_with_spaces_or_quotes(self):
        for name in ("stray copy", "stray'x", 'stray"x'):
            stray = self.make_tree(self.root / name)
            self.assert_refused(self.run_stray([stray]))
            self.assertTrue(stray.exists())

    def test_a_reference_continuing_past_a_space_still_refuses(self):
        stray = self.make_tree(self.root / "stray")
        conf = self.live / "renewal" / "home.example.conf"
        conf.write_text(conf.read_text() + f'x = "{stray} copy/dns.ini"\n')
        self.assert_refused(self.run_stray([stray]))
        self.assertTrue(stray.exists())

    def test_walks_a_symlinked_live_root_and_linked_directories(self):
        # The live config dir is itself a symlink, and a directory symlink in it
        # leads to another directory whose symlink points into the candidate.
        stray = self.make_tree(self.root / "stray")
        (stray / "hooks").mkdir()
        real_live = self.root / "real-live"
        self.live.rename(real_live)
        self.live.symlink_to(real_live)
        (real_live / "renewal-hooks").symlink_to(stray / "hooks")
        self.assert_refused(self.run_stray([stray]))
        (real_live / "renewal-hooks").unlink()
        other = self.root / "other"
        other.mkdir()
        (other / "deploy").symlink_to(stray / "hooks")
        (real_live / "renewal-hooks").symlink_to(other)
        self.assert_refused(self.run_stray([stray]))
        self.assertTrue(stray.exists())

    def test_resolves_dotdot_references_like_the_filesystem(self):
        # /alias -> /storage/sub, so /alias/../stray is /storage/stray.
        storage = self.root / "storage"
        (storage / "sub").mkdir(parents=True)
        stray = self.make_tree(storage / "stray")
        (self.root / "alias").symlink_to(storage / "sub")
        conf = self.live / "renewal" / "home.example.conf"
        conf.write_text(conf.read_text() + f"x = {self.root}/alias/../stray/dns.ini\n")
        self.assert_refused(self.run_stray([stray]))
        self.assertTrue(stray.exists())

    def test_refuses_dotdot_or_quoted_values_even_inside_the_live_tree(self):
        stray = self.make_tree(self.root / "stray")
        conf = self.live / "renewal" / "home.example.conf"
        original = conf.read_text()
        for value in (f"{self.live}/../stray/x", f'"{self.live}/a b/x"', f"{self.live}/"):
            conf.write_text(original + f"x = {value}\n")
            self.assert_refused(self.run_stray([stray]))
        self.assertTrue(stray.exists())

    def test_reads_renewal_configurations_of_every_protected_tree(self):
        # A second protected tree (here: the live dir given with another config
        # dir) whose renewal configuration points into the candidate.
        stray = self.make_tree(self.root / "stray")
        other = self.root / "other-config"
        (other / "renewal").mkdir(parents=True)
        (other / "renewal" / "x.conf").write_text(f"x = {stray}/dns.ini\n")
        tasks = yaml.safe_load((ROLE / "tasks" / "stray.yml").read_text())
        for task in tasks:
            task.pop("become", None)
        protected_fact = tasks[0]["ansible.builtin.set_fact"]
        protected_fact["certbot_dns_stray_protected"] = [str(self.live), str(other)]
        playbook = self.root / "play.yml"
        variables = {
            "certbot_dns_config_dir": str(self.live),
            "certbot_dns_stray_config_dirs": [str(stray)],
            "role_path": str(ROLE),
        }
        playbook.write_text(
            yaml.safe_dump([{"hosts": "localhost", "gather_facts": False, "vars": variables, "tasks": tasks}])
        )
        result = subprocess.run(
            ["ansible-playbook", "-i", "localhost,", "-c", "local", str(playbook)],
            capture_output=True,
            text=True,
        )
        self.assert_refused(result)
        self.assertTrue(stray.exists())

    def test_runs_after_cleanup(self):
        main = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
        order = [t["ansible.builtin.import_tasks"] for t in main]
        self.assertLess(order.index("cleanup.yml"), order.index("stray.yml"))
        defaults = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
        self.assertEqual(defaults["certbot_dns_stray_config_dirs"], [])


if __name__ == "__main__":
    unittest.main()
