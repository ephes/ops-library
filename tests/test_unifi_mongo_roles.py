"""The MongoDB user unifi_deploy creates can use all three controller databases.

UniFi 9.5 derives ``<db>_stat`` and ``<db>_audit`` from ``unifi.db.name`` and
ensures indexes in all three on every start; without a grant on ``_audit`` it
logs ``Failure while ensuring index`` (Unauthorized on
``unifi_audit.traffic_flow``). The audit grant stays a narrow ``readWrite``.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import jinja2

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "roles/unifi_deploy/templates/mongo-init.js.j2"


def render() -> str:
    environment = jinja2.Environment(undefined=jinja2.StrictUndefined)
    environment.filters["to_json"] = lambda value: '"' + value + '"'
    return environment.from_string(TEMPLATE.read_text()).render(
        unifi_mongodb_user="unifi",
        unifi_mongodb_password="placeholder",
        unifi_mongodb_database="unifi",
    )


class UnifiMongoRolesTest(unittest.TestCase):
    def test_new_user_gets_the_audit_database(self) -> None:
        script = render()
        self.assertIn('{ role: "readWrite", db: "unifi_audit" }', script)
        self.assertNotIn('{ role: "dbOwner", db: "unifi_audit" }', script)
        for database in ("unifi", "unifi_stat"):
            self.assertIn(f'{{ role: "readWrite", db: "{database}" }}', script)
            self.assertIn(f'{{ role: "dbOwner", db: "{database}" }}', script)
        self.assertIn('{ role: "clusterMonitor", db: "admin" }', script)
        self.assertNotIn("AnyDatabase", script)


if __name__ == "__main__":
    unittest.main()
