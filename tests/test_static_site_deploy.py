import json
import runpy
import unittest
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import yaml
from jinja2 import Environment, Template

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/static_site_deploy"


class StaticSiteDeployContractTests(unittest.TestCase):
    def test_rendered_server_serves_files_without_listing_or_writes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "site"
            root.mkdir()
            (root / "index.html").write_text("benchmark snapshot")
            (root / "empty").mkdir()
            rendered = Template(
                (ROLE / "templates/static-site-httpd.py.j2").read_text()
            ).render(
                static_site_path=str(root),
                static_site_bind_host="127.0.0.1",
                static_site_port=10061,
            )
            module = Path(directory) / "static-site-httpd.py"
            module.write_text(rendered)
            namespace = runpy.run_path(str(module))
            handler = partial(namespace["StaticHandler"], directory=str(root))
            server = namespace["ThreadingHTTPServer"](("127.0.0.1", 0), handler)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}"
                with urlopen(url, timeout=3) as response:
                    self.assertEqual(response.read(), b"benchmark snapshot")
                    self.assertEqual(
                        response.headers["X-Content-Type-Options"], "nosniff"
                    )
                with self.assertRaises(HTTPError) as listing:
                    urlopen(url + "/empty/", timeout=3)
                self.assertEqual(listing.exception.code, 404)
                listing.exception.close()
                with self.assertRaises(HTTPError) as write:
                    urlopen(Request(url + "/new", data=b"no", method="PUT"), timeout=3)
                self.assertEqual(write.exception.code, 501)
                write.exception.close()
                self.assertFalse((root / "new").exists())
                self.assertEqual(namespace["StaticHandler"].timeout, 10)
            finally:
                server.shutdown()
                thread.join(timeout=3)
                server.server_close()

    def test_server_binds_loopback_and_disables_directory_listing(self) -> None:
        defaults = (ROLE / "defaults/main.yml").read_text()
        server = (ROLE / "templates/static-site-httpd.py.j2").read_text()

        self.assertIn("static_site_bind_host: 127.0.0.1", defaults)
        self.assertIn("def list_directory", server)
        self.assertIn('self.send_error(404, "Directory listing is disabled")', server)

    def test_systemd_unit_is_read_only_and_unprivileged(self) -> None:
        unit = (ROLE / "templates/static-site.service.j2").read_text()

        self.assertIn("User={{ static_site_user }}", unit)
        self.assertIn("NoNewPrivileges=true", unit)
        self.assertIn("ProtectSystem=strict", unit)
        self.assertIn("ReadOnlyPaths={{ static_site_path }}", unit)
        self.assertIn("\nCapabilityBoundingSet=\n", unit)

    def test_traefik_route_requires_https_and_redirects_http(self) -> None:
        route = (ROLE / "templates/static-site.traefik.yml.j2").read_text()

        self.assertIn("tls: {}", route)
        self.assertIn("redirectScheme:", route)
        self.assertIn("- {{ static_site_traefik_http_entrypoint }}", route)
        self.assertIn(
            'url: "http://{{ static_site_bind_host }}:{{ static_site_port }}"', route
        )

    def test_strict_mode_rejects_extra_publication_content(self) -> None:
        validation = (ROLE / "tasks/validate.yml").read_text()

        self.assertIn("static_site_restrict_to_required_files", validation)
        self.assertIn("Enforce exact compact publication allowlist", validation)
        self.assertIn(
            "static_site_source_regular_files.matched == (static_site_required_files | length)",
            validation,
        )
        self.assertIn("static_site_source_directories.matched == 0", validation)
        self.assertRegex(
            validation,
            r"Find symbolic links in source[\s\S]+?hidden: true[\s\S]+?file_type: link",
        )

    def test_sync_uses_explicit_transfer_flags_and_mode_normalization(self) -> None:
        content = (ROLE / "tasks/content.yml").read_text()
        start = content.index("- name: content | Synchronize generated static site")
        end = content.index("- name: content | Keep published content root-owned")
        sync_task = content[start:end]

        self.assertIn("archive: false", sync_task)
        self.assertIn("recursive: true", sync_task)
        self.assertIn("links: false", sync_task)
        self.assertIn("times: true", sync_task)
        self.assertIn("perms: true", sync_task)
        self.assertIn("owner: false", sync_task)
        self.assertIn("group: false", sync_task)
        self.assertIn('delete: "{{ static_site_rsync_delete | bool }}"', sync_task)
        self.assertIn('rsync_path: "sudo -n rsync"', sync_task)
        self.assertIn(
            "\"--chmod={{ 'D0750,F0640' if static_site_private | bool else 'D0755,F0644' }}\"",
            sync_task,
        )

    def test_content_ownership_task_declares_directory_state(self) -> None:
        content = (ROLE / "tasks/content.yml").read_text()
        start = content.index("- name: content | Keep published content root-owned")
        ownership_task = content[start:]

        self.assertIn("state: directory", ownership_task)
        self.assertIn("recurse: true", ownership_task)

    def test_health_checks_skip_check_mode(self) -> None:
        verification = (ROLE / "tasks/verify.yml").read_text()

        task_names = (
            "Wait for loopback static service",
            "Require expected index content",
            "Wait for public HTTPS route",
            "Require expected public index content",
        )
        for index, task_name in enumerate(task_names):
            start = verification.index(f"- name: verify | {task_name}")
            if index + 1 < len(task_names):
                end = verification.index(f"- name: verify | {task_names[index + 1]}")
            else:
                end = len(verification)
            self.assertIn("not ansible_check_mode", verification[start:end])

    def test_role_supports_only_validated_ipv4_loopback(self) -> None:
        validation = (ROLE / "tasks/validate.yml").read_text()

        self.assertIn("static_site_bind_host == '127.0.0.1'", validation)
        self.assertNotIn("'::1'", validation)

    def test_source_rejects_special_entries(self) -> None:
        validation = (ROLE / "tasks/validate.yml").read_text()

        self.assertIn("file_type: any", validation)
        self.assertIn("Reject special publication source entries", validation)
        self.assertIn("static_site_source_entries.matched", validation)

    def test_http_and_https_entrypoints_must_differ(self) -> None:
        validation = (ROLE / "tasks/validate.yml").read_text()

        self.assertIn("static_site_traefik_entrypoints is sequence", validation)
        self.assertIn("static_site_traefik_entrypoints is not string", validation)
        self.assertIn("Validate HTTPS entrypoint names", validation)
        self.assertIn(
            "static_site_traefik_http_entrypoint not in static_site_traefik_entrypoints",
            validation,
        )


def _render_route(**overrides) -> dict:
    environment = Environment()
    environment.filters["to_json"] = json.dumps
    template = environment.from_string(
        (ROLE / "templates/static-site.traefik.yml.j2").read_text()
    )
    values = {
        "static_site_service_name": "opaq",
        "static_site_host": "opaq.home.example.test",
        "static_site_traefik_entrypoints": ["web-secure"],
        "static_site_traefik_http_entrypoint": "web",
        "static_site_traefik_cert_resolver": "",
        "static_site_bind_host": "127.0.0.1",
        "static_site_port": 10064,
        "static_site_traefik_allowed_networks": [],
    }
    values.update(overrides)
    return yaml.safe_load(template.render(**values))


class StaticSitePrivateAccessTests(unittest.TestCase):
    NETWORKS = ["100.64.0.0/10", "fd7a:115c:a1e0::/48"]

    def test_default_route_has_no_allowlist(self) -> None:
        http = _render_route()["http"]

        self.assertNotIn("opaq-allowlist", http["middlewares"])
        self.assertEqual(
            http["routers"]["opaq-secure"]["middlewares"],
            ["opaq-headers", "opaq-compress"],
        )
        self.assertEqual(http["routers"]["opaq-http"]["middlewares"], ["opaq-redirect"])

    def test_allowlist_guards_both_routers_first(self) -> None:
        http = _render_route(static_site_traefik_allowed_networks=self.NETWORKS)["http"]

        self.assertEqual(
            http["middlewares"]["opaq-allowlist"],
            {"ipAllowList": {"sourceRange": self.NETWORKS}},
        )
        self.assertEqual(
            http["routers"]["opaq-secure"]["middlewares"][0], "opaq-allowlist"
        )
        # A refused source must get 403, not a redirect to the HTTPS router.
        self.assertEqual(
            http["routers"]["opaq-http"]["middlewares"], ["opaq-allowlist", "opaq-redirect"]
        )

    def test_private_defaults_keep_existing_behaviour(self) -> None:
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())

        self.assertIs(defaults["static_site_private"], False)
        self.assertEqual(defaults["static_site_traefik_allowed_networks"], [])

    def test_private_document_root_and_verification(self) -> None:
        user = (ROLE / "tasks/user.yml").read_text()
        verification = (ROLE / "tasks/verify.yml").read_text()

        self.assertIn("mode: \"{{ '0750' if static_site_private | bool else '0755' }}\"", user)
        start = verification.index("- name: verify | Find published entries readable by others")
        private_checks = verification[start:]
        self.assertIn("argv: [find, \"{{ static_site_path }}\", -perm, /o=rwx]", private_checks)
        self.assertEqual(private_checks.count("static_site_private | bool"), 2)
        self.assertEqual(private_checks.count("not ansible_check_mode"), 2)
        self.assertIn("stdout_lines | length == 0", private_checks)

    def test_allowed_networks_are_validated_as_cidr_list(self) -> None:
        validation = (ROLE / "tasks/validate.yml").read_text()

        self.assertIn("static_site_traefik_allowed_networks is sequence", validation)
        self.assertIn("static_site_traefik_allowed_networks is not string", validation)
        self.assertIn("static_site_private is boolean", validation)
        self.assertIn("Validate allowed source networks", validation)

    def test_allowed_networks_are_parsed_as_real_networks(self) -> None:
        tasks = yaml.safe_load((ROLE / "tasks/validate.yml").read_text())
        task = next(t for t in tasks if t["name"] == "validate | Validate allowed source networks")
        self.assertIn("item | local.ops_library.is_cidr", task["ansible.builtin.assert"]["that"])

        namespace = runpy.run_path(str(ROOT / "plugins/filter/network.py"))
        is_cidr = namespace["FilterModule"]().filters()["is_cidr"]
        for good in ("100.64.0.0/10", "fd7a:115c:a1e0::/48", "192.168.178.94/32", "::1/128"):
            self.assertTrue(is_cidr(good), good)
        for bad in (
            "999.999.999.999/99",
            "100.64.0.0/33",
            "fd7a:115c:a1e0::/129",
            "abcd/48",
            "100.64.0.1/10",  # host bits under the prefix
            "10.0.0.0/255.0.0.0",  # netmask: Go's ParseCIDR refuses it
            "fe80::%eth0/64",  # scoped IPv6: Go's ParseCIDR refuses it
            "10.0.0.0/٨",  # non-ASCII digit
            "100.64.0.0",
            " 100.64.0.0/10",
            "fd7a::/48\n10.0.0.0/8",
            "",
            None,
            ["100.64.0.0/10"],
        ):
            self.assertFalse(is_cidr(bad), repr(bad))


if __name__ == "__main__":
    unittest.main()
