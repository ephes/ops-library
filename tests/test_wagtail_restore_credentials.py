import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "roles/wagtail_restore/tasks/main.yml"


def walk(nodes):
    for node in nodes or []:
        yield node
        for key in ("block", "rescue", "always"):
            yield from walk(node.get(key))


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.nodes = yaml.safe_load(TASKS.read_text())
        self.tasks = list(walk(self.nodes))

    def test_postgres_clients_read_a_private_passfile(self):
        self.assertNotIn("PGPASSWORD", TASKS.read_text())
        users = [t for t in self.tasks if "PGPASSFILE" in (t.get("environment") or {})]
        self.assertEqual(
            [t["name"] for t in users],
            [
                "Take and verify live database safety dump",
                "Restore PostgreSQL dump in one transaction",
                "Restore Wagtail safety dump in one transaction",
            ],
        )
        for task in users:
            self.assertIn("wagtail_restore_task_pgpass.path", task["environment"]["PGPASSFILE"])
            self.assertTrue(task.get("no_log"))

    def test_passfile_lifecycle(self):
        restore = next(n for n in self.nodes if "block" in n and "rescue" in n)
        names = [t.get("name") for t in restore["block"]]
        self.assertEqual(names[:2], ["Allocate private PostgreSQL passfile directory", "Render PostgreSQL passfile"])
        render = restore["block"][1]
        self.assertEqual(render["ansible.builtin.template"]["mode"], "0600")
        self.assertTrue(render["no_log"])
        self.assertEqual(restore["always"][0]["name"], "Remove private PostgreSQL passfile directory")
        top = [t.get("name") for t in self.nodes]
        validate = top.index("Validate PostgreSQL passfile password before restore")
        self.assertLess(validate, self.nodes.index(restore))

    def test_passfile_escapes_colon_and_backslash(self):
        template = (ROOT / "roles/wagtail_restore/templates/task-pgpass.j2").read_text()
        self.assertTrue(template.startswith("*:*:*:*:"))
        self.assertIn("replace(':', '\\\\:')", template)
        self.assertIn("replace('\\\\', '\\\\\\\\')", template)
