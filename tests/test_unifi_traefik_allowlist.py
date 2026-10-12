"""The UniFi controller route can be limited to trusted networks.

``unifi_deploy`` publishes the controller admin UI as ``unifi.<domain>`` with a
``Host()`` rule only: no Basic Auth, no source restriction. With
``unifi_traefik_ip_allowlist`` set, the router gets an ``ipAllowList``
middleware. The default (empty list) renders exactly the file the role wrote
before, so nothing changes until the variable is set.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/unifi_deploy"
TRUSTED = ["192.168.0.0/16", "100.64.0.0/10", "fd7a:115c:a1e0::/48"]

# The template as it was before the allowlist existed.
PREVIOUS_OUTPUT = """\
http:
  routers:
    unifi:
      rule: "Host(`unifi.home.xn--wersdrfer-47a.de`)"
      entryPoints:
        - "web-secure"
      service: unifi
      tls:
        certResolver: "letsencrypt"

  services:
    unifi:
      loadBalancer:
        servers:
          - url: "https://127.0.0.1:8443"
        serversTransport: unifi-transport

  serversTransports:
    unifi-transport:
      insecureSkipVerify: true
"""


def render_text(**overrides: object) -> str:
    environment = Environment(
        loader=FileSystemLoader(ROLE / "templates"),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,  # as Ansible's template module renders
    )
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    variables = {
        "unifi_external_hostname": "unifi.home.xn--wersdrfer-47a.de",
        "unifi_traefik_entrypoints": defaults["unifi_traefik_entrypoints"],
        "unifi_traefik_certresolver": defaults["unifi_traefik_certresolver"],
        "unifi_traefik_ip_allowlist": defaults["unifi_traefik_ip_allowlist"],
        "unifi_controller_bind_address": "127.0.0.1",
        "unifi_port_https": 8443,
    }
    variables.update(overrides)
    return environment.get_template("unifi.traefik.yml.j2").render(**variables)


def render(**overrides: object) -> dict:
    return yaml.safe_load(render_text(**overrides))


class UnifiTraefikAllowlistTest(unittest.TestCase):
    def test_default_is_an_empty_list(self) -> None:
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        self.assertEqual(defaults["unifi_traefik_ip_allowlist"], [])

    def test_default_renders_the_previous_file_unchanged(self) -> None:
        self.assertEqual(render_text(), PREVIOUS_OUTPUT)
        config = render()
        self.assertNotIn("middlewares", config["http"])
        self.assertNotIn("middlewares", config["http"]["routers"]["unifi"])

    def test_allowlist_restricts_the_only_router(self) -> None:
        config = render(unifi_traefik_ip_allowlist=TRUSTED)["http"]
        self.assertEqual(list(config["routers"]), ["unifi"])
        self.assertEqual(config["routers"]["unifi"]["middlewares"], ["unifi-ipallow"])
        self.assertEqual(
            config["middlewares"],
            {"unifi-ipallow": {"ipAllowList": {"sourceRange": TRUSTED}}},
        )

    def test_allowlist_leaves_rule_service_and_tls_alone(self) -> None:
        plain = render()["http"]
        limited = render(unifi_traefik_ip_allowlist=TRUSTED)["http"]
        for key in ("rule", "entryPoints", "service", "tls"):
            with self.subTest(key=key):
                self.assertEqual(
                    limited["routers"]["unifi"][key], plain["routers"]["unifi"][key]
                )
        self.assertEqual(limited["services"], plain["services"])
        self.assertEqual(limited["serversTransports"], plain["serversTransports"])

    def test_allowlist_without_certresolver(self) -> None:
        config = render(
            unifi_traefik_ip_allowlist=TRUSTED, unifi_traefik_certresolver=""
        )["http"]
        self.assertEqual(config["routers"]["unifi"]["tls"], {})
        self.assertEqual(config["routers"]["unifi"]["middlewares"], ["unifi-ipallow"])

    def test_role_validates_the_allowlist_before_it_changes_anything(self) -> None:
        """A bare string would render one "network" per character.

        ``tests/test_unifi_traefik_allowlist.yml`` runs these checks under
        Ansible; this pins where they sit and what they cover.
        """
        validate = (ROLE / "tasks/validate.yml").read_text()
        self.assertIn("import_tasks: validate_traefik.yml", validate)
        main = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
        self.assertEqual(main[0]["ansible.builtin.import_tasks"], "validate.yml")

        shape, parse = yaml.safe_load((ROLE / "tasks/validate_traefik.yml").read_text())
        conditions = [" ".join(c.split()) for c in shape["ansible.builtin.assert"]["that"]]
        self.assertIn("unifi_traefik_ip_allowlist is not string", conditions)
        self.assertIn("unifi_traefik_ip_allowlist is not mapping", conditions)
        self.assertIn(
            "unifi_traefik_ip_allowlist | reject('string') | list | length == 0",
            conditions,
        )
        self.assertEqual(shape["when"], "unifi_traefik_enabled | bool")

        argv = parse["ansible.builtin.command"]["argv"]
        self.assertEqual(argv[:2], ["python3", "-c"])
        self.assertIn("ipaddress.ip_network(entry, strict=False)", argv[2])
        self.assertIn("ipaddress.ip_address(entry)", argv[2])
        self.assertEqual(argv[3], "{{ unifi_traefik_ip_allowlist | to_json }}")
        # Runs on the controller, also in check mode, and never reports a change.
        self.assertEqual(parse["delegate_to"], "localhost")
        self.assertIs(parse["become"], False)
        self.assertIs(parse["check_mode"], False)
        self.assertIs(parse["changed_when"], False)
        self.assertIn("unifi_traefik_enabled | bool", parse["when"])


if __name__ == "__main__":
    unittest.main()
