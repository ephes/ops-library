"""SnappyMail 3.0.0 and the webmail/Vaultwarden Traefik allowlists.

The ``snappymail_deploy`` and ``vaultwarden_deploy`` templates match the
ops-deploy ``services.snappymail``/``services.vaultwarden`` templates, so an
Ansible rollback writes what pyinfra writes: SnappyMail 3.0.0, nginx serving
only the selected release below ``/snappymail/``, ``fastcgi_param HTTPS on``
and the ``ipAllowList`` middlewares. With ``OPS_DEPLOY_PATH`` set to an
ops-deploy checkout the templates are compared byte for byte.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
SNAPPYMAIL = ROOT / "roles/snappymail_deploy"
SNAPPYMAIL_SHARED = ROOT / "roles/snappymail_shared"
VAULTWARDEN = ROOT / "roles/vaultwarden_deploy"
TAILNET = ["100.64.0.0/10", "fd7a:115c:a1e0::/48"]
LAN = ["192.168.178.0/24", *TAILNET]


def _bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "y"}
    return bool(value)


def _environment(role: Path) -> Environment:
    environment = Environment(
        loader=FileSystemLoader(role / "templates"),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,  # as Ansible's template module renders
    )
    environment.filters["bool"] = _bool
    return environment


def _defaults(*roles: Path) -> dict:
    merged: dict = {}
    for role in roles:
        merged.update(yaml.safe_load((role / "defaults/main.yml").read_text()))
    return merged


def snappymail_vars(**overrides: object) -> dict:
    variables = _defaults(SNAPPYMAIL_SHARED, SNAPPYMAIL)
    variables.update(
        {
            "snappymail_nginx_server_name": "webmail.example.org",
            "snappymail_php_fpm_socket": "/run/php/php8.3-fpm-snappymail.sock",
            "snappymail_traefik_host": "webmail.example.org",
        }
    )
    variables.update(overrides)
    return variables


def render_snappymail(template: str, **overrides: object) -> str:
    return (
        _environment(SNAPPYMAIL)
        .get_template(template)
        .render(**snappymail_vars(**overrides))
    )


def render_vaultwarden(**overrides: object) -> dict:
    variables = _defaults(VAULTWARDEN)
    variables.update(
        {
            "vaultwarden_domain": "https://vault.example.org",
            "vaultwarden_hostname": "vault.example.org",
        }
    )
    variables.update(overrides)
    text = (
        _environment(VAULTWARDEN)
        .get_template("traefik-vaultwarden.yml.j2")
        .render(**variables)
    )
    return yaml.safe_load(text)


def validation_script(role: Path, task_name: str) -> str:
    for task in yaml.safe_load((role / "tasks/validate.yml").read_text()):
        if task["name"] == task_name:
            return task["ansible.builtin.command"]["argv"][2]
    raise AssertionError(f"{task_name} not found in {role}")


def run_validation(script: str, entries: list[str]) -> subprocess.CompletedProcess[str]:
    import json

    return subprocess.run(
        [sys.executable, "-c", script, json.dumps(entries)],
        capture_output=True,
        text=True,
        check=False,
    )


class SnappyMailReleaseTest(unittest.TestCase):
    def test_pins_3_0_0_with_the_verified_archive_checksum(self) -> None:
        defaults = _defaults(SNAPPYMAIL_SHARED)
        self.assertEqual(defaults["snappymail_version"], "3.0.0")
        self.assertEqual(
            defaults["snappymail_download_checksum"],
            "sha256:ac495fb8eb95a27c3f2bfab74db0d15b12079c35ef1c533dc70504865f21d000",  # pragma: allowlist secret
        )

    def test_nginx_serves_only_the_selected_release_below_snappymail(self) -> None:
        text = render_snappymail("nginx-snappymail.conf.j2")
        self.assertIn("location ^~ /snappymail/ {\n        deny all;", text)
        self.assertIn("location ^~ /snappymail/v/3.0.0/static/ {", text)
        self.assertIn("location ^~ /snappymail/v/3.0.0/themes/ {", text)
        self.assertNotIn("2.38.2", text)

    def test_nginx_passes_https_to_php(self) -> None:
        text = render_snappymail("nginx-snappymail.conf.j2")
        php = text[text.index("location ~ \\.php$") :]
        self.assertIn("fastcgi_param HTTPS on;", php[: php.index("}")])


class SnappyMailAllowlistTest(unittest.TestCase):
    def test_default_is_enabled_with_the_tailnet(self) -> None:
        defaults = _defaults(SNAPPYMAIL_SHARED)
        self.assertIs(defaults["snappymail_traefik_ip_whitelist_enabled"], True)
        self.assertEqual(defaults["snappymail_traefik_ip_whitelist"], TAILNET)

    def test_enabled_allowlist_is_on_the_router(self) -> None:
        route = yaml.safe_load(
            render_snappymail(
                "traefik-snappymail.yml.j2", snappymail_traefik_ip_whitelist=LAN
            )
        )["http"]
        self.assertIn(
            "snappymail-ipwhitelist",
            route["routers"]["snappymail-secure"]["middlewares"],
        )
        self.assertEqual(
            route["middlewares"]["snappymail-ipwhitelist"],
            {"ipAllowList": {"sourceRange": LAN}},
        )

    def test_disabled_allowlist_renders_no_middleware(self) -> None:
        route = yaml.safe_load(
            render_snappymail(
                "traefik-snappymail.yml.j2",
                snappymail_traefik_ip_whitelist_enabled=False,
            )
        )["http"]
        self.assertNotIn(
            "snappymail-ipwhitelist",
            route["routers"]["snappymail-secure"]["middlewares"],
        )
        self.assertNotIn("snappymail-ipwhitelist", route["middlewares"])

    def test_enabled_empty_list_is_refused(self) -> None:
        tasks = yaml.safe_load((SNAPPYMAIL / "tasks/validate.yml").read_text())
        shape = next(
            t
            for t in tasks
            if t["name"].endswith("Ensure Traefik IP allowlist is a list of networks")
        )
        self.assertIn(
            "(not snappymail_traefik_ip_whitelist_enabled | bool) or (snappymail_traefik_ip_whitelist | length > 0)",
            shape["ansible.builtin.assert"]["that"],
        )

    def test_entries_must_parse(self) -> None:
        script = validation_script(
            SNAPPYMAIL,
            "Validate | Verify Traefik IP allowlist entries parse as networks",
        )
        self.assertEqual(run_validation(script, [*LAN, "192.168.178.20"]).returncode, 0)
        for bad in (
            "lan",
            "192.168.1.0/33",
            "fd7a::/129",
            "1.2.3",
            " 10.0.0.0/8",
            "fe80::1%eth0",
        ):
            with self.subTest(bad=bad):
                self.assertEqual(run_validation(script, [bad]).returncode, 1)


class VaultwardenAllowlistTest(unittest.TestCase):
    def test_default_is_empty_and_renders_no_middleware(self) -> None:
        self.assertEqual(_defaults(VAULTWARDEN)["vaultwarden_traefik_ip_allowlist"], [])
        route = render_vaultwarden()["http"]
        self.assertEqual(
            route["routers"]["vaultwarden"]["middlewares"], ["vaultwarden-headers"]
        )
        self.assertNotIn("vaultwarden-ipallowlist", route["middlewares"])

    def test_allowlist_is_on_the_https_router(self) -> None:
        route = render_vaultwarden(vaultwarden_traefik_ip_allowlist=LAN)["http"]
        self.assertEqual(
            route["routers"]["vaultwarden"]["middlewares"],
            ["vaultwarden-ipallowlist", "vaultwarden-headers"],
        )
        self.assertEqual(
            route["middlewares"]["vaultwarden-ipallowlist"],
            {"ipAllowList": {"sourceRange": LAN}},
        )

    def test_entries_must_be_cidr_networks(self) -> None:
        script = validation_script(
            VAULTWARDEN,
            "validate | Verify Traefik IP allowlist entries parse as networks",
        )
        self.assertEqual(run_validation(script, LAN).returncode, 0)
        for bad in (
            "192.168.178.20",
            "lan",
            "192.168.1.0/33",
            "fd7a::/129",
            "10.0.0.0/x",
        ):
            with self.subTest(bad=bad):
                self.assertEqual(run_validation(script, [bad]).returncode, 1)


OPS_DEPLOY = os.environ.get("OPS_DEPLOY_PATH")


@unittest.skipUnless(OPS_DEPLOY, "OPS_DEPLOY_PATH not set")
class OpsDeployTemplatesTest(unittest.TestCase):
    def test_templates_are_ops_deploys(self) -> None:
        assert OPS_DEPLOY is not None
        services = Path(OPS_DEPLOY) / "src/ops_deploy/services"
        for role, service, name in (
            (SNAPPYMAIL, "snappymail", "nginx-snappymail.conf.j2"),
            (SNAPPYMAIL, "snappymail", "traefik-snappymail.yml.j2"),
            (VAULTWARDEN, "vaultwarden", "traefik-vaultwarden.yml.j2"),
        ):
            with self.subTest(template=name):
                self.assertEqual(
                    (role / "templates" / name).read_bytes(),
                    (services / service / "templates" / name).read_bytes(),
                )


if __name__ == "__main__":
    unittest.main()
