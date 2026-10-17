import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined

ROLES = Path(__file__).resolve().parents[1] / "roles"
DEFAULTS = yaml.safe_load((ROLES / "mastodon_shared" / "defaults" / "main.yml").read_text())

BASE = {
    "mastodon_traefik_host": "fedi.example.com",
    "mastodon_local_domain": "example.com",
    "mastodon_traefik_entrypoints": ["web-secure"],
    "mastodon_traefik_service_web": "mastodon-web",
    "mastodon_traefik_service_streaming": "mastodon-streaming",
    "mastodon_traefik_cert_resolver": "",
    "mastodon_traefik_middlewares": [],
    "mastodon_nginx_enabled": True,
    "mastodon_nginx_port": 10044,
    "mastodon_web_port": 10042,
    "mastodon_streaming_port": 10043,
    "mastodon_traefik_local_domain_wellknown": DEFAULTS["mastodon_traefik_local_domain_wellknown"],
    "mastodon_traefik_local_domain_cert_resolver": DEFAULTS["mastodon_traefik_local_domain_cert_resolver"],
    "mastodon_traefik_local_domain_priority": DEFAULTS["mastodon_traefik_local_domain_priority"],
}


def to_bool(value):
    return value if isinstance(value, bool) else str(value).strip().lower() in ("1", "true", "yes", "on")


def render(**overrides):
    environment = Environment(undefined=StrictUndefined, trim_blocks=True, keep_trailing_newline=True)
    environment.filters["bool"] = to_bool
    template = (ROLES / "mastodon_deploy" / "templates" / "traefik.yml.j2").read_text()
    return yaml.safe_load(environment.from_string(template).render(**{**BASE, **overrides}))


class MastodonLocalDomainRouteTests(unittest.TestCase):
    def test_default_renders_no_local_route(self):
        self.assertFalse(DEFAULTS["mastodon_traefik_local_domain_wellknown"])
        config = render()
        self.assertEqual(set(config["http"]["routers"]), {"mastodon-web", "mastodon-streaming"})

    def test_local_route_matches_exact_discovery_paths_on_local_domain(self):
        config = render(
            mastodon_traefik_local_domain_wellknown=True, mastodon_traefik_local_domain_cert_resolver="letsencrypt"
        )
        router = config["http"]["routers"]["mastodon-local-wellknown"]
        self.assertEqual(
            router["rule"],
            "Host(`example.com`) && (Path(`/.well-known/webfinger`) || Path(`/.well-known/host-meta`)"
            " || Path(`/.well-known/nodeinfo`))",
        )
        self.assertNotIn("PathPrefix", router["rule"])
        self.assertEqual(router["service"], "mastodon-web")
        self.assertEqual(router["entryPoints"], ["web-secure"])
        self.assertEqual(router["tls"], {"certResolver": "letsencrypt"})
        # Must beat a site router on the same host, whose default priority is its rule length.
        site_rule = "Host(`example.com`) || Host(`www.example.com`) || Host(`design.example.com`)"
        self.assertGreater(router["priority"], len(site_rule))
        # The web host routers are unchanged.
        self.assertEqual(config["http"]["routers"]["mastodon-web"]["rule"], "Host(`fedi.example.com`)")

    def test_local_route_without_resolver_uses_existing_certificates(self):
        config = render(mastodon_traefik_local_domain_wellknown=True)
        self.assertEqual(config["http"]["routers"]["mastodon-local-wellknown"]["tls"], {})


if __name__ == "__main__":
    unittest.main()
