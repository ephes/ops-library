"""minio_deploy: the S3 API routers' optional LAN/Tailscale restriction."""

from __future__ import annotations

import unittest
from pathlib import Path

import jinja2
import yaml

ROLE = Path(__file__).resolve().parent.parent / "roles/minio_deploy"
TASK_NAME = "Validate the internal-only S3 API switch"


def validation_passes(**values: object) -> bool:
    """Evaluate the validate task's ``that`` list like Ansible's assert."""
    tasks = yaml.safe_load((ROLE / "tasks/validate.yml").read_text())
    (task,) = [task for task in tasks if task.get("name") == TASK_NAME]
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.tests["boolean"] = lambda value: isinstance(value, bool)
    return all(
        env.compile_expression(expression)(**values)
        for expression in task["assert"]["that"]
    )


def render(**overrides: object) -> dict:
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    values = {
        **defaults,
        "minio_traefik_host": "minio.example.test",
        "minio_traefik_api_host": "objects.example.test",
        "minio_console_basic_auth_password_hash": "fixture-hash",
        **overrides,
    }
    env = jinja2.Environment(
        undefined=jinja2.StrictUndefined, trim_blocks=True, keep_trailing_newline=True
    )
    text = env.from_string(
        (ROLE / "templates/traefik-minio.yml.j2").read_text()
    ).render(**values)
    return yaml.safe_load(text)["http"]["routers"]


class ApiInternalOnlyTest(unittest.TestCase):
    def test_default_keeps_the_api_public(self) -> None:
        routers = render()
        self.assertEqual(
            routers["minio-api-secure"]["rule"], "Host(`objects.example.test`)"
        )
        self.assertEqual(
            routers["minio-api-http"]["rule"], "Host(`objects.example.test`)"
        )

    def test_internal_only_restricts_both_api_routers(self) -> None:
        routers = render(
            minio_traefik_api_internal_only=True,
            minio_internal_ip_ranges=["10.0.0.0/8", "100.64.0.0/10"],
        )
        expected = "Host(`objects.example.test`) && (ClientIP(`10.0.0.0/8`) || ClientIP(`100.64.0.0/10`))"
        self.assertEqual(routers["minio-api-secure"]["rule"], expected)
        self.assertEqual(routers["minio-api-http"]["rule"], expected)
        # The console routers are unchanged by the switch.
        self.assertEqual(
            routers["minio-console-ext"]["rule"], "Host(`minio.example.test`)"
        )

    def test_default_is_off(self) -> None:
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        self.assertIs(defaults["minio_traefik_api_internal_only"], False)

    def test_validation(self) -> None:
        ranges = ["10.0.0.0/8"]
        self.assertTrue(
            validation_passes(
                minio_traefik_api_internal_only=True, minio_internal_ip_ranges=ranges
            )
        )
        self.assertTrue(
            validation_passes(
                minio_traefik_api_internal_only=False, minio_internal_ip_ranges=[]
            )
        )
        self.assertFalse(
            validation_passes(
                minio_traefik_api_internal_only=True, minio_internal_ip_ranges=[]
            )
        )
        for value in ("true", "yes", 1):
            self.assertFalse(
                validation_passes(
                    minio_traefik_api_internal_only=value,
                    minio_internal_ip_ranges=ranges,
                ),
                value,
            )


if __name__ == "__main__":
    unittest.main()
