import re
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined

ROLES = Path(__file__).resolve().parents[1] / "roles"
TEMPLATES = ROLES / "mastodon_deploy" / "templates"
DEFAULTS = yaml.safe_load((ROLES / "mastodon_shared" / "defaults" / "main.yml").read_text())

# Concrete values for the defaults that reference other variables.
BASE = {
    "mastodon_nginx_pid_file": "/run/mastodon-nginx/nginx.pid",
    "mastodon_nginx_error_log": "/var/log/mastodon-nginx/error.log",
    "mastodon_nginx_access_log": "/var/log/mastodon-nginx/access.log",
    "mastodon_nginx_worker_connections": 4096,
    "mastodon_nginx_body_temp_path": "/var/lib/mastodon-nginx/body",
    "mastodon_web_port": 10042,
    "mastodon_streaming_port": 10043,
    "mastodon_nginx_port": 10044,
    "mastodon_nginx_server_name": "_",
    "mastodon_public_path": "/home/mastodon/live/public",
    "mastodon_nginx_client_max_body_size": "100M",
    "mastodon_nginx_cache_enabled": False,
    "mastodon_nginx_cache_path": "/var/cache/mastodon/nginx",
    "mastodon_nginx_cache_zone": "mastodon",
    "mastodon_nginx_cache_zone_size": "20m",
    "mastodon_nginx_cache_inactive": "14d",
    "mastodon_nginx_cache_size": "1g",
    "mastodon_nginx_temp_path": "/var/cache/mastodon/nginx/temp",
    "mastodon_nginx_federation_cache_enabled": DEFAULTS["mastodon_nginx_federation_cache_enabled"],
    "mastodon_nginx_federation_cache_path": DEFAULTS["mastodon_nginx_federation_cache_path"],
    "mastodon_nginx_federation_cache_zone": DEFAULTS["mastodon_nginx_federation_cache_zone"],
    "mastodon_nginx_federation_cache_zone_size": DEFAULTS["mastodon_nginx_federation_cache_zone_size"],
    "mastodon_nginx_federation_cache_size": DEFAULTS["mastodon_nginx_federation_cache_size"],
    "mastodon_nginx_federation_cache_inactive": DEFAULTS["mastodon_nginx_federation_cache_inactive"],
    "mastodon_nginx_federation_cache_locations": DEFAULTS["mastodon_nginx_federation_cache_locations"],
    "mastodon_nginx_federation_cache_lock_timeout": DEFAULTS["mastodon_nginx_federation_cache_lock_timeout"],
    "mastodon_nginx_access_log_timing": DEFAULTS["mastodon_nginx_access_log_timing"],
}


def to_bool(value):
    return value if isinstance(value, bool) else str(value).strip().lower() in ("1", "true", "yes", "on")


def render(name, **overrides):
    environment = Environment(undefined=StrictUndefined, trim_blocks=True, keep_trailing_newline=True)
    # The Ansible filters the templates use.
    environment.filters["bool"] = to_bool
    environment.filters["basename"] = lambda path: Path(path).name
    template = (TEMPLATES / name).read_text()
    return environment.from_string(template).render(**{**BASE, **overrides})


def location_block(text, path):
    match = re.search(r"location = " + re.escape(path) + r" \{(.*?)\n        \}", text, re.S)
    return match.group(1) if match else None


class MastodonNginxFederationCacheTests(unittest.TestCase):
    def test_defaults_keep_the_switches_off(self):
        self.assertFalse(DEFAULTS["mastodon_nginx_federation_cache_enabled"])
        self.assertFalse(DEFAULTS["mastodon_nginx_access_log_timing"])
        self.assertEqual(
            DEFAULTS["mastodon_nginx_federation_cache_locations"],
            ["/actor", "/.well-known/webfinger", "/.well-known/host-meta", "/.well-known/nodeinfo", "/nodeinfo/2.0"],
        )

    def test_disabled_renders_no_federation_cache(self):
        text = render("nginx.conf.j2")
        self.assertNotIn("mastodon_federation", text)
        self.assertNotIn("location = ", text)
        self.assertNotIn("log_format", text)
        self.assertIn("        access_log /var/log/mastodon-nginx/access.log;\n", text)

    def test_enabled_caches_each_location_with_lock_and_stale(self):
        text = render("nginx.conf.j2", mastodon_nginx_federation_cache_enabled=True)
        self.assertIn(
            "proxy_cache_path /var/cache/mastodon/nginx-federation levels=1:2 keys_zone=mastodon_federation:10m"
            " inactive=7d max_size=100m use_temp_path=off;",
            text,
        )
        for path in DEFAULTS["mastodon_nginx_federation_cache_locations"]:
            block = location_block(text, path)
            self.assertIsNotNone(block, path)
            self.assertIn("proxy_cache mastodon_federation;", block)
            self.assertIn(
                'proxy_cache_key "$mastodon_forwarded_proto://$mastodon_forwarded_host$request_uri'
                '|$mastodon_federation_accept|$mastodon_federation_cors";',
                block,
            )
            # Vary is replaced by the normalized key parts above.
            self.assertIn("proxy_ignore_headers Vary;", block)
            self.assertIn("proxy_set_header Accept $mastodon_federation_accept;", block)
            self.assertIn('proxy_set_header Accept-Encoding "";', block)
            # A location-level proxy_set_header drops the inherited ones.
            for header in ("Host", "X-Forwarded-For", "X-Forwarded-Proto", "X-Forwarded-Host", "X-Real-IP"):
                self.assertIn(f"proxy_set_header {header} ", block)
            self.assertIn("proxy_cache_lock on;", block)
            # lock_age defaults to 5s in nginx and would let a second request through.
            self.assertIn("proxy_cache_lock_timeout 10s;", block)
            self.assertIn("proxy_cache_lock_age 10s;", block)
            self.assertIn("proxy_cache_use_stale updating error timeout", block)
            self.assertIn("proxy_cache_background_update on;", block)
            # The shared @proxy turns buffering off; caching needs it on.
            self.assertIn("proxy_buffering on;", block)
            self.assertIn("proxy_pass http://mastodon-web;", block)
            # nginx must follow Mastodon's own Cache-Control/Expires; only Vary is ignored.
            self.assertEqual(re.findall(r"proxy_ignore_headers [^;]*;", block), ["proxy_ignore_headers Vary;"])
            self.assertNotIn("proxy_cache_valid", block)

    def test_cache_key_maps_are_declared_at_http_level(self):
        text = render("nginx.conf.j2", mastodon_nginx_federation_cache_enabled=True)
        server = text.index("    server {")
        accept_map = text.index("map $http_accept $mastodon_federation_accept {")
        cors_map = text.index("map $http_origin $mastodon_federation_cors {")
        self.assertLess(accept_map, server)
        self.assertLess(cors_map, server)
        # Both ActivityStreams media types share one entry.
        self.assertIn('"~*application/(activity|ld)\\+json" "application/activity+json";', text)

    def test_prime_tasks_require_a_cache_hit(self):
        defaults = DEFAULTS
        self.assertIn({"path": "/actor", "accept": "application/activity+json"}, defaults["mastodon_nginx_federation_cache_prime"])
        self.assertEqual(defaults["mastodon_nginx_federation_cache_prime_hosts"], ["{{ mastodon_traefik_host }}"])
        tasks = yaml.safe_load((ROLES / "mastodon_deploy" / "tasks" / "federation_cache.yml").read_text())
        check = next(task for task in tasks if task["name"] == "federation_cache | Check that the federation documents are served from the cache")
        self.assertIn("x_cache_status", check["failed_when"])
        self.assertIn("'HIT'", check["failed_when"])
        main = yaml.safe_load((ROLES / "mastodon_deploy" / "tasks" / "main.yml").read_text())
        names = [task["name"] for task in main]
        self.assertLess(names.index("Run Mastodon health check"), names.index("Fill and check the nginx federation cache"))

    def test_requester_dependent_documents_are_not_cached(self):
        text = render("nginx.conf.j2", mastodon_nginx_federation_cache_enabled=True)
        locations = re.findall(r"location = (\S+) \{", text)
        self.assertEqual(locations, DEFAULTS["mastodon_nginx_federation_cache_locations"])
        self.assertNotIn("/users/", "".join(locations))

    def test_timing_log_keeps_combined_fields_first(self):
        text = render("nginx.conf.j2", mastodon_nginx_access_log_timing=True)
        self.assertIn(
            "log_format mastodon_timing '$remote_addr - $remote_user [$time_local] \"$request\" $status"
            " $body_bytes_sent \"$http_referer\" \"$http_user_agent\" rt=$request_time"
            " urt=$upstream_response_time cache=$upstream_cache_status';",
            text,
        )
        self.assertIn("        access_log /var/log/mastodon-nginx/access.log mastodon_timing;\n", text)
        # log_format is declared at http level, before the server block uses it.
        self.assertLess(text.index("log_format mastodon_timing"), text.index("    server {"))

    def test_unit_raises_the_open_file_limit(self):
        self.assertEqual(DEFAULTS["mastodon_nginx_limit_nofile"], 65536)
        self.assertGreater(DEFAULTS["mastodon_nginx_limit_nofile"], DEFAULTS["mastodon_nginx_worker_connections"])
        text = render(
            "nginx.service.j2",
            mastodon_nginx_user="mastodon",
            mastodon_nginx_group="mastodon",
            mastodon_nginx_run_dir="/run/mastodon-nginx",
            mastodon_nginx_config_path="/etc/mastodon/nginx.conf",
            mastodon_nginx_limit_nofile=65536,
        )
        self.assertIn("\nLimitNOFILE=65536\n", text)


if __name__ == "__main__":
    unittest.main()
