"""mail_backend_local_delivery_clients: port-25 delivery to local domains only.

Port 25 on the backend relays for ``mynetworks`` and rejects everything else.
A host that only sends its own system mail to a local mailbox should not get
``mynetworks`` (that also lets it relay to the internet through the edge).
These tests render the role's real templates and validation tasks through
Ansible and check:

- the default (no clients) renders master.cf/main.cf unchanged;
- configured clients get a cidr map and a restriction class that permits only
  hosted destinations;
- entries wider than one host, or not in canonical form, are refused;
- when Postfix tools are installed locally, ``postconf`` parses the rendered
  master.cf override and ``postmap`` resolves the map as intended.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "mail_backend_deploy"
TEMPLATES = ROLE / "templates" / "postfix"
DEFAULT_RELAY_LINE = "  -o smtpd_relay_restrictions=permit_mynetworks,reject\n"
CLIENT_RELAY_LINE = (
    "  -o { smtpd_relay_restrictions = permit_mynetworks, check_client_access "
    "cidr:/etc/postfix/local_delivery_clients.cidr, reject }\n"
)


def _validation_tasks() -> list[dict]:
    tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text(encoding="utf-8"))
    selected = [t for t in tasks if "local-delivery client" in t.get("name", "")]
    assert len(selected) == 2, [t.get("name") for t in tasks]
    for task in selected:
        # The test runs on localhost already; keep the task otherwise unchanged.
        task.pop("delegate_to", None)
    return selected


def _run(clients: object, out_dir: Path) -> subprocess.CompletedProcess[str]:
    render_tasks = [
        {
            "name": f"render {name}",
            "ansible.builtin.template": {
                "src": str(TEMPLATES / f"{name}.j2"),
                "dest": str(out_dir / name),
                "mode": "0644",
            },
        }
        for name in ("main.cf", "master.cf", "local_delivery_clients.cidr")
    ]
    playbook = [
        {
            "hosts": "localhost",
            "gather_facts": False,
            "vars_files": [str(ROLE / "defaults" / "main.yml")],
            "tasks": _validation_tasks() + render_tasks,
        }
    ]
    playbook_path = out_dir / "playbook.yml"
    playbook_path.write_text(yaml.safe_dump(playbook, sort_keys=False), encoding="utf-8")
    # Extra vars, because vars_files (the role defaults) outrank play vars.
    extra_vars = out_dir / "extra-vars.json"
    extra_vars.write_text(
        json.dumps(
            {
                "mail_backend_domains": ["example.test"],
                "mail_backend_postgres_password": "test",  # pragma: allowlist secret
                "mail_backend_relay_password": "test",  # pragma: allowlist secret
                "mail_backend_local_delivery_clients": clients,
            }
        ),
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "ANSIBLE_NOCOLOR": "1",
        "ANSIBLE_LOCALHOST_WARNING": "0",
        "ANSIBLE_INVENTORY_UNPARSED_WARNING": "0",
        "ANSIBLE_RETRY_FILES_ENABLED": "0",
    }
    return subprocess.run(
        [
            "ansible-playbook", "-i", "localhost,", "-c", "local",
            "-e", f"@{extra_vars}", str(playbook_path),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
        check=False,
    )


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not on PATH")
class LocalDeliveryClientRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _render(self, clients: object) -> tuple[str, str, str]:
        result = _run(clients, self.out)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return tuple(
            (self.out / name).read_text(encoding="utf-8")
            for name in ("main.cf", "master.cf", "local_delivery_clients.cidr")
        )

    def test_default_renders_port_25_unchanged(self) -> None:
        main_cf, master_cf, _ = self._render([])
        self.assertIn(DEFAULT_RELAY_LINE, master_cf)
        self.assertNotIn("local_delivery", master_cf)
        self.assertNotIn("smtpd_restriction_classes", main_cf)
        self.assertNotIn("local_delivery_only", main_cf)

    def test_clients_get_map_and_restriction_class(self) -> None:
        clients = ["100.64.0.10/32", "2001:db8::10/128"]
        main_cf, master_cf, cidr = self._render(clients)

        self.assertIn(CLIENT_RELAY_LINE, master_cf)
        self.assertNotIn(DEFAULT_RELAY_LINE, master_cf)
        # Only port 25 changes; submission/smtps keep SASL-only relaying.
        self.assertEqual(master_cf.count("check_client_access"), 1)
        self.assertEqual(
            master_cf.count("-o smtpd_relay_restrictions=permit_sasl_authenticated,reject"), 2
        )
        self.assertIn("smtpd_restriction_classes = local_delivery_only\n", main_cf)
        self.assertIn("local_delivery_only = permit_auth_destination, reject\n", main_cf)
        # Not added to mynetworks, so no relaying to outside domains.
        mynetworks = next(line for line in main_cf.splitlines() if line.startswith("mynetworks ="))
        for client in clients:
            self.assertNotIn(client.split("/")[0], mynetworks)

        entries = [line.split() for line in cidr.splitlines() if line and not line.startswith("#")]
        self.assertEqual(entries, [[c, "local_delivery_only"] for c in clients])

    def test_rendered_config_parses_with_local_postfix(self) -> None:
        if not (shutil.which("postconf") and shutil.which("postmap")):
            self.skipTest("postconf/postmap not on PATH")
        _, master_cf, _ = self._render(["100.64.0.10/32"])
        conf = self.out / "conf"
        conf.mkdir()
        (conf / "main.cf").write_text("compatibility_level = 2\n", encoding="utf-8")
        # Only the port-25 service: an older local Postfix may not know every
        # service type in the full file (postlog's unix-dgram needs 3.4).
        lines = master_cf.splitlines(keepends=True)
        start = next(i for i, line in enumerate(lines) if line.startswith("smtp      inet"))
        end = next(
            i for i in range(start + 1, len(lines)) if not lines[i].startswith("  ")
        )
        (conf / "master.cf").write_text("".join(lines[start:end]), encoding="utf-8")
        parsed = subprocess.run(
            ["postconf", "-c", str(conf), "-P", "smtp/inet/smtpd_relay_restrictions"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(parsed.returncode, 0, parsed.stderr)
        self.assertEqual(
            parsed.stdout.strip(),
            "smtp/inet/smtpd_relay_restrictions = permit_mynetworks, check_client_access "
            "cidr:/etc/postfix/local_delivery_clients.cidr, reject",
        )

        table = f"cidr:{self.out / 'local_delivery_clients.cidr'}"
        hit = subprocess.run(
            ["postmap", "-q", "100.64.0.10", table], capture_output=True, text=True, check=False
        )
        self.assertEqual((hit.returncode, hit.stdout.strip()), (0, "local_delivery_only"))
        miss = subprocess.run(
            ["postmap", "-q", "100.64.0.11", table], capture_output=True, text=True, check=False
        )
        self.assertEqual(miss.returncode, 1, miss.stdout + miss.stderr)


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not on PATH")
class LocalDeliveryClientValidationTests(unittest.TestCase):
    def _assert_refused(self, clients: object, message: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(clients, Path(tmp))
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn(message, result.stdout)
            self.assertFalse((Path(tmp) / "master.cf").exists())

    def test_networks_wider_than_one_host_are_refused(self) -> None:
        for entry in ("100.64.0.0/24", "192.168.0.0/16", "2001:db8::/64", "0.0.0.0/0"):
            with self.subTest(entry=entry):
                self._assert_refused([entry], "must be one host")

    def test_bare_addresses_and_non_canonical_forms_are_refused(self) -> None:
        cases = {
            "100.64.0.10": "must be one host",
            "2001:DB8::10/128": "write it as",
            "[2001:db8::10]/128": "does not appear to be",
            "100.64.0.10/24": "has host bits set",
            "not-an-ip/32": "does not appear to be",
        }
        for entry, message in cases.items():
            with self.subTest(entry=entry):
                self._assert_refused([entry], message)

    def test_non_list_values_are_refused(self) -> None:
        for value in ("100.64.0.10/32", {"host": "100.64.0.10/32"}, [32]):
            with self.subTest(value=json.dumps(value)):
                self._assert_refused(value, "must be a list of strings")


class LocalDeliveryClientStaticTests(unittest.TestCase):
    def test_default_is_empty(self) -> None:
        defaults = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text(encoding="utf-8"))
        self.assertEqual(defaults["mail_backend_local_delivery_clients"], [])

    def test_map_is_removed_when_unused_and_restarts_postfix(self) -> None:
        tasks = yaml.safe_load((ROLE / "tasks" / "postfix.yml").read_text(encoding="utf-8"))
        by_name = {t["name"]: t for t in tasks}
        create = by_name["Create local-delivery client map"]
        remove = by_name["Remove local-delivery client map when no clients are configured"]
        self.assertEqual(create["ansible.builtin.template"]["dest"],
                         "/etc/postfix/local_delivery_clients.cidr")
        self.assertEqual(remove["ansible.builtin.file"]["state"], "absent")
        self.assertEqual(create["notify"], "Restart postfix")
        self.assertEqual(remove["notify"], "Restart postfix")

    def test_readme_documents_the_variable(self) -> None:
        readme = (ROLE / "README.md").read_text(encoding="utf-8")
        self.assertIn("mail_backend_local_delivery_clients", readme)
        self.assertIn("permit_auth_destination", readme)


if __name__ == "__main__":
    unittest.main()
