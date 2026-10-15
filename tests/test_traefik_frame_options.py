"""Every Traefik `customFrameOptionsValue` in a role template is a recorded decision.

Traefik's headers middleware replaces the backend's `X-Frame-Options` with
`customFrameOptionsValue`. A backend that answers `DENY` behind an edge that
says `SAMEORIGIN` is therefore weakened by the edge. The table below records,
per headers middleware, the value the edge sets and why; a template that adds
or changes one fails here until the table says what the backend needs.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLES = ROOT / "roles"

# (template below roles/, middleware key as written in the template) -> (value, reason)
EXPECTED = {
    # The backend sends DENY itself (measured on the running services, and the
    # Django apps set X_FRAME_OPTIONS = "DENY" or keep Django's default); none
    # of them frames its own pages.
    ("archive_deploy/templates/archive.traefik.yml.j2", "archive-headers"): ("DENY", "Django default"),
    ("chesslab_deploy/templates/chesslab.traefik.yml.j2", "chesslab-headers"): ("DENY", "Django default"),
    ("echoport_deploy/templates/traefik-echoport.yml.j2", "echoport-headers"): ("DENY", "app setting"),
    ("graphyard_ingress_deploy/templates/traefik-graphyard.yml.j2", "graphyard-headers"): ("DENY", "app"),
    ("graphyard_ingress_deploy/templates/traefik-graphyard.yml.j2", "grafana-headers"): (
        "DENY",
        "Grafana default (allow_embedding off)",
    ),
    ("gotosocial_deploy/templates/traefik.yml.j2", "gotosocial-headers"): ("DENY", "GoToSocial default"),
    ("homelab_deploy/templates/traefik.yml.j2", "homelab-headers"): ("DENY", "app setting"),
    ("logyard_ingress_deploy/templates/traefik-logyard.yml.j2", "logyard-headers"): ("DENY", "API only"),
    ("mailgun_relay_ingress_deploy/templates/traefik-mailgun-relay.yml.j2", "mailgun-relay-headers"): (
        "DENY",
        "API only",
    ),
    ("minio_deploy/templates/traefik-minio.yml.j2", "minio-console-headers"): ("DENY", "console default"),
    ("navidrome_deploy/templates/navidrome-traefik.yml.j2", "navidrome-headers"): ("DENY", "Navidrome default"),
    ("nyxmon_deploy/templates/traefik-nyxmon.yml.j2", "nyxmon-headers"): ("DENY", "app setting"),
    ("voxhelm_ingress_deploy/templates/voxhelm-traefik.yml.j2", "voxhelm-headers"): ("DENY", "app"),
    ("weeknotes_home_deploy/templates/weeknotes-home.traefik.yml.j2", "{{ weeknotes_home_service_name }}-headers"): (
        "DENY",
        "Django default",
    ),
    ("work_app_deploy/templates/traefik.yml.j2", "work-app-headers"): ("DENY", "app setting"),
    # SAMEORIGIN is kept where the backend sends SAMEORIGIN or no header at
    # all (the edge then adds protection rather than removing it), or frames
    # its own pages.
    ("fastdeploy_deploy/templates/traefik.yml.j2", "{{ fastdeploy_service_name }}-headers"): ("SAMEORIGIN", "backend sends none"),
    ("homeassistant_deploy/templates/homeassistant.traefik.yml.j2", "homeassistant-headers"): (
        "SAMEORIGIN",
        "backend sends SAMEORIGIN; add-on panels are same-origin frames",
    ),
    ("jellyfin_deploy/templates/jellyfin-traefik.yml.j2", "jellyfin-headers"): ("SAMEORIGIN", "backend sends none"),
    ("metube_deploy/templates/metube-traefik.yml.j2", "metube-headers"): ("SAMEORIGIN", "backend sends none"),
    ("ollama_proxy_deploy/templates/ollama-proxy-traefik.yml.j2", "ollama-headers"): (
        "SAMEORIGIN",
        "backend sends none",
    ),
    ("open_webui_deploy/templates/open-webui-traefik.yml.j2", "open-webui-headers"): (
        "SAMEORIGIN",
        "backend sends none",
    ),
    ("open_webui_venv_deploy/templates/open-webui-traefik.yml.j2", "open-webui-headers"): (
        "SAMEORIGIN",
        "backend sends none",
    ),
    ("opsgate_ingress_deploy/templates/opsgate-traefik.yml.j2", "opsgate-headers"): (
        "SAMEORIGIN",
        "backend sends none",
    ),
    ("static_site_deploy/templates/static-site.traefik.yml.j2", "{{ static_site_service_name }}-headers"): (
        "SAMEORIGIN",
        "the role's own httpd sends SAMEORIGIN",
    ),
    ("takahe_deploy/templates/traefik.yml.j2", "takahe-headers"): (
        "SAMEORIGIN",
        "not measured: decide after checking what the deployed Takahe sends",
    ),
    ("vaultwarden_deploy/templates/traefik-vaultwarden.yml.j2", "vaultwarden-headers"): (
        "SAMEORIGIN",
        "backend sends SAMEORIGIN",
    ),
    ("wagtail_deploy/templates/wagtail.traefik.yml.j2", "{{ wagtail_service_name }}-headers"): (
        "SAMEORIGIN",
        "the Wagtail admin previews pages in same-origin frames",
    ),
}

MIDDLEWARE = re.compile(r"^    (\S.*):\s*$")
VALUE = re.compile(r"^\s+customFrameOptionsValue:\s*(\S+)\s*$")


def frame_options() -> dict[tuple[str, str], str]:
    """Map (template, enclosing middleware key) to the value each template sets."""
    found: dict[tuple[str, str], str] = {}
    for template in sorted(ROLES.glob("*/templates/**/*.j2")):
        middleware = None
        for line in template.read_text().splitlines():
            key = MIDDLEWARE.match(line)
            if key:
                middleware = key.group(1)
            value = VALUE.match(line)
            if value:
                if middleware is None:
                    raise AssertionError(f"{template}: frame option outside a middleware")
                entry = (str(template.relative_to(ROLES)), middleware)
                if entry in found:
                    raise AssertionError(f"{entry}: frame option set twice")
                found[entry] = value.group(1)
    return found


class TraefikFrameOptionsTest(unittest.TestCase):
    def test_every_template_value_is_a_recorded_decision(self) -> None:
        found = frame_options()
        self.assertEqual(sorted(found), sorted(EXPECTED))
        for entry, value in found.items():
            with self.subTest(template=entry[0], middleware=entry[1]):
                self.assertEqual(value, EXPECTED[entry][0], EXPECTED[entry][1])

    def test_values_are_valid_header_values(self) -> None:
        for entry, (value, reason) in EXPECTED.items():
            with self.subTest(template=entry[0]):
                self.assertIn(value, ("DENY", "SAMEORIGIN"))
                self.assertTrue(reason)

    def test_no_template_sets_frame_options_another_way(self) -> None:
        # frameDeny or a raw X-Frame-Options response header would bypass the table.
        for template in sorted(ROLES.glob("*/templates/**/*traefik*.j2")):
            settings = [
                line
                for line in template.read_text().splitlines()
                if not line.lstrip().startswith("#")
            ]
            with self.subTest(template=str(template.relative_to(ROLES))):
                offending = [
                    line
                    for line in settings
                    if "frameDeny" in line or "x-frame-options" in line.lower()
                ]
                self.assertEqual(offending, [])

    def test_backends_that_send_deny_are_not_weakened(self) -> None:
        found = frame_options()
        for role, middleware in (
            ("archive_deploy", "archive-headers"),
            ("chesslab_deploy", "chesslab-headers"),
            ("echoport_deploy", "echoport-headers"),
            ("graphyard_ingress_deploy", "grafana-headers"),
            ("homelab_deploy", "homelab-headers"),
            ("minio_deploy", "minio-console-headers"),
            ("navidrome_deploy", "navidrome-headers"),
            ("nyxmon_deploy", "nyxmon-headers"),
            ("weeknotes_home_deploy", "{{ weeknotes_home_service_name }}-headers"),
            ("work_app_deploy", "work-app-headers"),
            ("voxhelm_ingress_deploy", "voxhelm-headers"),
        ):
            values = [
                value
                for (template, name), value in found.items()
                if template.startswith(role + "/") and name == middleware
            ]
            with self.subTest(role=role):
                self.assertEqual(values, ["DENY"])


if __name__ == "__main__":
    unittest.main()
