"""`delve_deploy`: the operator dashboard (/admin) only answers allowlisted sources.

The Traefik file keeps the public app router and adds a priority-200
`delve-admin` router with an `ipAllowList` middleware while
`delve_traefik_admin_ip_allowlist` is non-empty; an empty list renders the
previous single-router file.
"""

import json
import subprocess
import sys
import unittest

import yaml

from tests.test_voxhelm_prune_and_service_knobs import ROLES, _defaults, _render, _task, _tasks

DELVE = ROLES / "delve_deploy"
TEMPLATE = DELVE / "templates/delve-traefik.yml.j2"


def _route(**overrides) -> dict:
    context = _defaults(DELVE) | overrides
    return yaml.safe_load(_render(TEMPLATE, context))["http"]


class DelveAdminAllowlistTest(unittest.TestCase):
    def test_default_restricts_admin_to_homelab_ranges(self) -> None:
        defaults = _defaults(DELVE)
        self.assertIn("100.64.0.0/10", defaults["delve_traefik_admin_ip_allowlist"])
        self.assertIn("fd7a:115c:a1e0::/48", defaults["delve_traefik_admin_ip_allowlist"])

        http = _route()
        admin = http["routers"]["delve-admin"]
        host = defaults["delve_traefik_host"]
        self.assertEqual(admin["rule"], f"Host(`{host}`) && (Path(`/admin`) || PathPrefix(`/admin/`))")
        self.assertEqual(admin["priority"], 200)
        self.assertEqual(admin["service"], "delve")
        self.assertEqual(admin["middlewares"], ["delve-admin-allowlist", "delve-headers"])
        self.assertEqual(admin["entryPoints"], defaults["delve_traefik_entrypoints"])
        self.assertEqual(
            http["middlewares"]["delve-admin-allowlist"]["ipAllowList"]["sourceRange"],
            defaults["delve_traefik_admin_ip_allowlist"],
        )

    def test_public_app_router_never_serves_admin(self) -> None:
        # Fail closed: if Traefik drops the admin router, /admin is a 404.
        defaults = _defaults(DELVE)
        router = _route()["routers"]["delve"]
        host = defaults["delve_traefik_host"]
        self.assertEqual(router["rule"], f"Host(`{host}`) && !(Path(`/admin`) || PathPrefix(`/admin/`))")
        self.assertNotIn("priority", router)
        self.assertEqual(router["middlewares"], ["delve-headers"])

    def test_admin_router_uses_the_cert_resolver(self) -> None:
        admin = _route(delve_traefik_cert_resolver="letsencrypt")["routers"]["delve-admin"]
        self.assertEqual(admin["tls"], {"certResolver": "letsencrypt"})

    def test_empty_allowlist_renders_single_router(self) -> None:
        http = _route(delve_traefik_admin_ip_allowlist=[])
        host = _defaults(DELVE)["delve_traefik_host"]
        self.assertEqual(list(http["routers"]), ["delve"])
        self.assertEqual(http["routers"]["delve"]["rule"], f"Host(`{host}`)")
        self.assertEqual(list(http["middlewares"]), ["delve-headers"])


class DelveAdminAllowlistValidationTest(unittest.TestCase):
    """The validate task's network parser, run the way the role runs it."""

    def _parse(self, entries: list) -> subprocess.CompletedProcess:
        task = _task(_tasks(DELVE / "tasks/validate.yml"), "validate | Verify the /admin allowlist entries parse as networks")
        script = task["ansible.builtin.command"]["argv"][2]
        return subprocess.run([sys.executable, "-c", script, json.dumps(entries)], capture_output=True, text=True)

    def test_parses_every_hosts_list(self) -> None:
        task = _task(_tasks(DELVE / "tasks/validate.yml"), "validate | Verify the /admin allowlist entries parse as networks")
        self.assertNotIn("run_once", task)

    def test_defaults_parse(self) -> None:
        self.assertEqual(self._parse(_defaults(DELVE)["delve_traefik_admin_ip_allowlist"]).returncode, 0)

    def test_rejects_networks_traefik_cannot_build(self) -> None:
        for entry in ("192.168.1.0/33", "999.999.999.999/24", "fd7a::/129", "100.64.0.0", "10.0.0.0/08", "010.0.0.0/8", "evil/8"):
            with self.subTest(entry=entry):
                result = self._parse([entry])
                self.assertEqual(result.returncode, 1)
                self.assertIn(repr(entry), result.stdout)


if __name__ == "__main__":
    unittest.main()
