"""The Traefik metrics entrypoint must never be created implicitly.

Prometheus metrics default to the ``traefik`` entrypoint. When the dashboard is
disabled nothing defined that entrypoint, so Traefik created it on ``:8080`` on
every interface - and a host without a firewall served ``/metrics`` to the
internet on its first restart under the role.
"""

from __future__ import annotations

import json
import shlex
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/traefik_deploy"


def _render(**overrides: object) -> str:
    context = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    context.setdefault("traefik_letsencrypt_email", "ops@example.test")
    context.update(overrides)
    environment = Environment(
        loader=FileSystemLoader(ROLE / "templates"),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    environment.filters["bool"] = bool
    environment.filters["quote"] = shlex.quote
    environment.filters["to_json"] = json.dumps
    return environment.get_template("traefik.toml.j2").render(**context)


class TraefikMetricsEntrypointTests(unittest.TestCase):
    def test_acme_directory_is_never_temporarily_world_traversable(self) -> None:
        tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
        create_directories = next(
            task
            for task in tasks
            if task.get("name") == "Create Traefik directories"
        )
        directory_modes = {
            item["path"]: item["mode"] for item in create_directories["loop"]
        }
        self.assertEqual(directory_modes["{{ traefik_acme_dir }}"], "0700")
        acme_directory_tasks = []
        for task in tasks:
            file_args = task.get("ansible.builtin.file", {})
            if file_args.get("state") != "directory":
                continue
            direct_target = file_args.get("path") == "{{ traefik_acme_dir }}"
            loop_target = any(
                isinstance(item, dict)
                and item.get("path") == "{{ traefik_acme_dir }}"
                for item in task.get("loop", [])
            )
            if direct_target or loop_target:
                acme_directory_tasks.append(task.get("name"))
        self.assertEqual(acme_directory_tasks, ["Create Traefik directories"])

    def test_dashboard_disabled_binds_metrics_to_loopback(self) -> None:
        toml = _render(traefik_dashboard_enabled=False, traefik_metrics_enabled=True)
        self.assertIn("[entryPoints.traefik]", toml)
        self.assertIn('address = "127.0.0.1:8080"', toml)
        self.assertIn('entryPoint = "traefik"', toml)

    def test_bind_address_and_port_are_configurable(self) -> None:
        toml = _render(
            traefik_dashboard_enabled=False,
            traefik_metrics_enabled=True,
            traefik_metrics_bind_address="100.64.0.9",
            traefik_metrics_port=9180,
        )
        self.assertIn('address = "100.64.0.9:9180"', toml)

    def test_dashboard_enabled_keeps_metrics_on_the_dashboard_port(self) -> None:
        toml = _render(traefik_dashboard_enabled=True, traefik_metrics_enabled=True)
        self.assertEqual(toml.count("[entryPoints.traefik]"), 1)
        self.assertIn('address = ":8090"', toml)
        self.assertNotIn("127.0.0.1:8080", toml)

    def test_metrics_disabled_defines_no_metrics_entrypoint(self) -> None:
        toml = _render(traefik_dashboard_enabled=False, traefik_metrics_enabled=False)
        self.assertNotIn("[entryPoints.traefik]", toml)
        self.assertNotIn("[metrics]", toml)


if __name__ == "__main__":
    unittest.main()
