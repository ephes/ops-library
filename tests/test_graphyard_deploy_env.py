"""The graphyard deploy role's environment file and the bound-token switch.

`graphyard_require_bound_ingest_tokens` (default false) adds
`GRAPHYARD_REQUIRE_BOUND_INGEST_TOKENS=true` to graphyard.env. While it is
false the rendered file must stay byte-identical to the file the role wrote
before the switch existed, so a deploy with the default changes nothing and
restarts nothing.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml
from ansible.plugins.filter.core import to_bool
from jinja2 import Environment, FileSystemLoader, StrictUndefined


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "graphyard_deploy"
LINE = "GRAPHYARD_REQUIRE_BOUND_INGEST_TOKENS=true"
LAST_LINE_BEFORE = "GRAPHYARD_SQLITE_SYNCHRONOUS=FULL\n"


def render_env(**overrides: object) -> str:
    defaults = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
    context = {
        name: defaults[name]
        for name in ("graphyard_require_bound_ingest_tokens",)
    }
    context.update(
        {
            "graphyard_django_allowed_hosts": ["127.0.0.1", "localhost"],
            "graphyard_django_csrf_trusted_origins": [],
            "graphyard_django_settings_module": "config.settings.production",
            "graphyard_django_secret_key": "test-secret",  # pragma: allowlist secret
            "graphyard_django_admin_url": "hidden_admin/",
            "graphyard_django_login_url": "/login/",
            "graphyard_django_login_redirect_url": "/",
            "graphyard_django_session_cookie_age_seconds": 1209600,
            "graphyard_inventory_monitor_token": "",
            "graphyard_influx_url": "http://127.0.0.1:8086",
            "graphyard_influx_token": "test-token",  # pragma: allowlist secret
            "graphyard_influx_org": "graphyard",
            "graphyard_influx_bucket": "graphyard",
            "graphyard_influx_measurement": "graphyard_metrics",
            "graphyard_influx_timeout_ms": 5000,
            "graphyard_influx_api_mode": "v2",
            "graphyard_grafana_base_url": "https://grafana.example",
            "graphyard_metric_collection_interval_seconds": 60,
            "graphyard_condition_eval_interval_seconds": 60,
            "graphyard_ingest_heartbeat_min_interval_seconds": 15,
            "graphyard_heartbeat_warning_seconds": 900,
            "graphyard_heartbeat_critical_seconds": 3600,
            "graphyard_condition_data_stale_warning_seconds": 600,
            "graphyard_sqlite_timeout_seconds": 30,
            "graphyard_sqlite_busy_timeout_ms": 30000,
            "graphyard_sqlite_journal_mode": "WAL",
            "graphyard_sqlite_synchronous": "FULL",
        }
    )
    context.update(overrides)
    # Like ansible.builtin.template (trim_blocks defaults to true).
    environment = Environment(
        loader=FileSystemLoader(ROLE / "templates"),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
    )
    environment.filters["bool"] = to_bool
    return environment.get_template("graphyard.env.j2").render(**context)


class GraphyardEnvBoundTokensTest(unittest.TestCase):
    def test_default_is_false(self) -> None:
        defaults = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
        self.assertIs(defaults["graphyard_require_bound_ingest_tokens"], False)

    def test_false_leaves_the_file_unchanged(self) -> None:
        for value in (False, "false", "no", 0):
            with self.subTest(value=value):
                rendered = render_env(graphyard_require_bound_ingest_tokens=value)
                self.assertNotIn("REQUIRE_BOUND", rendered)
                # The file still ends with the line that ended it before.
                self.assertTrue(rendered.endswith(LAST_LINE_BEFORE), rendered[-120:])

    def test_default_renders_without_the_line(self) -> None:
        self.assertEqual(
            render_env(),
            render_env(graphyard_require_bound_ingest_tokens=False),
        )

    def test_true_appends_exactly_one_line(self) -> None:
        for value in (True, "true", "yes"):
            with self.subTest(value=value):
                rendered = render_env(graphyard_require_bound_ingest_tokens=value)
                off = render_env(graphyard_require_bound_ingest_tokens=False)
                self.assertEqual(rendered, off + "\n" + LINE + "\n")
                self.assertEqual(rendered.count("REQUIRE_BOUND"), 1)


if __name__ == "__main__":
    unittest.main()
