import unittest
from pathlib import Path

import yaml
from jinja2 import Template


ROOT = Path(__file__).resolve().parents[1]
ROLES = ROOT / "roles"


class Debian13CompatibilityTests(unittest.TestCase):
    def test_staging_roles_declare_trixie_support(self) -> None:
        role_names = (
            "postgres_install",
            "redis_install",
            "tailscale_deploy",
            "mastodon_deploy",
            "takahe_deploy",
            "wagtail_deploy",
            "bind_authoritative_deploy",
            "vector_apt_install",
            "graphyard_vector_deploy",
            "logyard_vector_deploy",
            "ssh_guard_deploy",
            "ssh_authorized_keys_manage",
            "shell_basics_deploy",
            "static_site_deploy",
            "systemd_unit_masks",
        )

        for role_name in role_names:
            with self.subTest(role=role_name):
                metadata = yaml.safe_load(
                    (ROLES / role_name / "meta/main.yml").read_text()
                )
                platforms = metadata["galaxy_info"]["platforms"]
                debian = next(item for item in platforms if item["name"] == "Debian")
                self.assertTrue(
                    "trixie" in debian["versions"] or "all" in debian["versions"]
                )

    def test_repository_defaults_resolve_to_trixie(self) -> None:
        cases = (
            ("postgres_install", "postgres_install_repo_codename", "trixie"),
            ("redis_install", "redis_install_apt_suite", "trixie"),
            ("tailscale_shared", "tailscale_repo_release", "trixie"),
            ("tailscale_shared", "tailscale_repo_distro", "debian"),
            ("mastodon_shared", "mastodon_postgres_repo_codename", "trixie"),
            ("takahe_shared", "takahe_postgres_repo_codename", "trixie"),
            ("wagtail_deploy", "wagtail_postgres_repo_codename", "trixie"),
        )
        context = {
            "ansible_distribution": "Debian",
            "ansible_distribution_release": "trixie",
        }

        for role_name, variable, expected in cases:
            with self.subTest(role=role_name, variable=variable):
                defaults = yaml.safe_load(
                    (ROLES / role_name / "defaults/main.yml").read_text()
                )
                self.assertEqual(Template(defaults[variable]).render(**context), expected)

    def test_repository_tasks_preserve_release_contracts(self) -> None:
        postgres = (ROLES / "postgres_install/tasks/repo.yml").read_text()
        redis = (ROLES / "redis_install/tasks/install.yml").read_text()
        tailscale = (ROLES / "tailscale_deploy/tasks/repo.yml").read_text()
        vector_defaults = yaml.safe_load(
            (ROLES / "vector_apt_install/defaults/main.yml").read_text()
        )

        self.assertIn('suites: "{{ postgres_install_repo_codename }}-pgdg"', postgres)
        self.assertIn('- "{{ redis_install_apt_suite }}"', redis)
        self.assertIn("ansible.builtin.deb822_repository", tailscale)
        self.assertIn('suites: "{{ tailscale_repo_release }}"', tailscale)
        self.assertNotIn("ansible.builtin.apt_repository", tailscale)
        self.assertEqual(vector_defaults["vector_apt_install_repo_channel"], "stable")
        self.assertEqual(vector_defaults["vector_apt_install_repo_version"], "vector-0")

    def test_bind_builtin_zone_include_tracks_debian_packaging(self) -> None:
        defaults = yaml.safe_load(
            (ROLES / "bind_authoritative_deploy/defaults/main.yml").read_text()
        )
        template = Template(defaults["bind_builtin_zones_file"])

        self.assertEqual(
            template.render(
                bind_config_dir="/etc/bind",
                ansible_distribution="Debian",
                ansible_distribution_major_version="13",
            ),
            "/etc/bind/named.conf.root-hints",
        )
        self.assertEqual(
            template.render(
                bind_config_dir="/etc/bind",
                ansible_distribution="Debian",
                ansible_distribution_major_version="12",
            ),
            "/etc/bind/named.conf.default-zones",
        )

    def test_debian13_molecule_scenarios_install_real_packages(self) -> None:
        roles = (
            "postgres_install",
            "redis_install",
            "tailscale_deploy",
            "shell_basics_deploy",
        )
        for role_name in roles:
            with self.subTest(role=role_name):
                scenario = yaml.safe_load(
                    (ROLES / role_name / "molecule/default/molecule.yml").read_text()
                )
                self.assertEqual(
                    scenario["platforms"][0]["image"],
                    "geerlingguy/docker-debian13-ansible",
                )
                sequence = scenario["scenario"]["test_sequence"]
                self.assertIn("converge", sequence)
                self.assertIn("verify", sequence)

        postgres_converge = (
            ROLES / "postgres_install/molecule/default/converge.yml"
        ).read_text()
        self.assertIn('postgres_install_version: "17"', postgres_converge)

    def test_application_and_dns_package_tasks_remain_distribution_native(self) -> None:
        package_tasks = {
            "mastodon_deploy": "mastodon_system_packages",
            "takahe_deploy": "takahe_system_packages",
            "bind_authoritative_deploy": "bind_packages",
            "shell_basics_deploy": "shell_basics_packages",
        }
        for role_name, variable in package_tasks.items():
            with self.subTest(role=role_name):
                text = "\n".join(
                    path.read_text()
                    for path in (ROLES / role_name / "tasks").glob("*.yml")
                )
                self.assertIn(variable, text)
                self.assertNotIn("bookworm", text)


if __name__ == "__main__":
    unittest.main()
