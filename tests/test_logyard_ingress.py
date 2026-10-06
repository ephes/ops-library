"""The Logyard ingress must route only the Loki push path and readiness probe.

Loki runs with ``auth_enabled: false``. The Traefik route used to forward every
path on the host, so any allowed client IP (LAN, tailnet and two VPS hosts)
could query, tail or delete every host's logs. Producers only need
``POST /loki/api/v1/push`` (Vector's loki sink) and ``GET /ready`` (Vector's
healthcheck and the documented validation curl). Grafana reads Loki over the
docker network, so it never goes through this route.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/logyard_ingress_deploy"
HOST = "logyard.home.xn--wersdrfer-47a.de"


def render(**overrides: object) -> dict:
    environment = Environment(
        loader=FileSystemLoader(ROLE / "templates"),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    environment.filters["bool"] = bool
    environment.filters["to_json"] = json.dumps
    variables = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    variables.update(
        logyard_ingress_host=HOST,
        logyard_ingress_traefik_cert_resolver="letsencrypt",
        logyard_ingress_internal_ip_ranges=["192.168.0.0/16", "100.64.0.0/10"],
    )
    variables.update(overrides)
    text = environment.get_template("traefik-logyard.yml.j2").render(**variables)
    return yaml.safe_load(text)


class LogyardIngressRouteTest(unittest.TestCase):
    def test_internal_router_matches_only_push_and_ready(self) -> None:
        rule = render()["http"]["routers"]["logyard-int"]["rule"]
        self.assertEqual(
            rule,
            f"Host(`{HOST}`) && (ClientIP(`192.168.0.0/16`) || ClientIP(`100.64.0.0/10`))"
            " && (((Method(`POST`)) && Path(`/loki/api/v1/push`))"
            " || ((Method(`GET`) || Method(`HEAD`)) && Path(`/ready`)))",
        )
        self.assertNotIn("PathPrefix", rule)

    def test_no_web_secure_router_forwards_host_only_to_loki(self) -> None:
        routers = render()["http"]["routers"]
        for name, router in routers.items():
            if router["service"] != "logyard" or "web-secure" not in router["entryPoints"]:
                continue
            with self.subTest(router=name):
                self.assertIn("Path(`", router["rule"])
                self.assertIn("Method(`", router["rule"])

    def test_plain_http_router_only_redirects(self) -> None:
        rendered = render()
        router = rendered["http"]["routers"]["logyard-http"]
        self.assertEqual(router["entryPoints"], ["web"])
        self.assertEqual(router["middlewares"], ["logyard-redirect-to-https"])
        self.assertIn(
            "redirectScheme", rendered["http"]["middlewares"]["logyard-redirect-to-https"]
        )

    def test_root_redirect_is_unchanged(self) -> None:
        rendered = render()
        router = rendered["http"]["routers"]["logyard-root"]
        self.assertEqual(router["rule"], f"Host(`{HOST}`) && Path(`/`)")
        self.assertEqual(router["service"], "noop@internal")
        self.assertEqual(router["priority"], 140)
        redirect = rendered["http"]["middlewares"]["logyard-root-redirect"]["redirectRegex"]
        self.assertEqual(redirect["regex"], "^https?://[^/]+/$")
        self.assertEqual(
            redirect["replacement"],
            "https://grafana.home.xn--wersdrfer-47a.de/d/logyard-home/logyard-overview",
        )

    def test_allowed_paths_override(self) -> None:
        rule = render(
            logyard_ingress_allowed_paths=[{"path": "/loki/api/v1/push", "methods": ["POST"]}]
        )["http"]["routers"]["logyard-int"]["rule"]
        self.assertTrue(rule.endswith("&& (((Method(`POST`)) && Path(`/loki/api/v1/push`)))"))
        self.assertNotIn("/ready", rule)

    def test_grafana_datasource_does_not_use_the_ingress(self) -> None:
        datasource = (
            ROOT / "roles/logyard_deploy/templates/grafana-logyard-datasource.yml.j2"
        ).read_text()
        self.assertIn(
            "url: http://{{ logyard_loki_container_name }}:{{ logyard_loki_http_port }}",
            datasource,
        )


if __name__ == "__main__":
    unittest.main()
