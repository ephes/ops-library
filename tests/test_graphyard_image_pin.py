"""Keep the rollback role's Grafana default immutable."""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class GraphyardImagePinTests(unittest.TestCase):
    def test_grafana_default_is_pinned(self):
        defaults = yaml.safe_load(
            (ROOT / "roles/graphyard_deploy/defaults/main.yml").read_text()
        )
        self.assertRegex(
            defaults["graphyard_grafana_image"],
            r"^grafana/grafana-oss:[0-9]+\.[0-9]+\.[0-9]+@sha256:[0-9a-f]{64}$",
        )
