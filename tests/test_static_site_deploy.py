import runpy
import unittest
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from jinja2 import Template

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
        self.assertIn('"--chmod=D0755,F0644"', sync_task)

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


if __name__ == "__main__":
    unittest.main()
