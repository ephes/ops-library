import json
import re
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/opaq_app_deploy"
DEFAULTS = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
NETWORKS = ["100.64.0.0/10", "fd7a:115c:a1e0::/48"]


def _render(template: str, **overrides) -> str:
    environment = Environment()
    environment.filters["to_json"] = json.dumps
    environment.filters["union"] = lambda a, b: list(dict.fromkeys(list(a) + list(b)))
    values = {}
    # Resolve the defaults' own Jinja references once, as Ansible would.
    for key, value in DEFAULTS.items():
        values[key] = value
    for _ in range(4):
        for key, value in list(values.items()):
            if isinstance(value, str) and "{{" in value:
                values[key] = environment.from_string(value).render(**values)
    values.update(
        opaq_app_secret_key="k" * 50,
        opaq_app_upload_token_sha256="0" * 64,
        opaq_app_traefik_host="opaq.home.example.test",
        opaq_app_allowed_networks=NETWORKS,
    )
    values.update(overrides)
    return environment.from_string((ROLE / "templates" / template).read_text()).render(**values)


class OpaqAppDeployTests(unittest.TestCase):
    def test_route_guards_both_routers_with_the_allowlist(self) -> None:
        http = yaml.safe_load(_render("traefik.yml.j2"))["http"]
        self.assertEqual(http["middlewares"]["opaq-app-allowlist"], {"ipAllowList": {"sourceRange": NETWORKS}})
        self.assertEqual(http["routers"]["opaq-app-secure"]["middlewares"], ["opaq-app-allowlist"])
        self.assertEqual(http["routers"]["opaq-app-http"]["middlewares"], ["opaq-app-allowlist", "opaq-app-redirect"])
        self.assertEqual(http["routers"]["opaq-app-secure"]["tls"], {})
        self.assertEqual(
            http["services"]["opaq-app"]["loadBalancer"]["servers"], [{"url": "http://127.0.0.1:10065"}]
        )
        self.assertNotIn("basicAuth", json.dumps(http))

    def test_environment_carries_only_the_token_digest(self) -> None:
        env = _render("env.j2")
        self.assertIn("OPAQ_UPLOAD_TOKEN_SHA256=" + "0" * 64, env)
        self.assertNotIn("UPLOAD_TOKEN=", env.replace("UPLOAD_TOKEN_SHA256=", ""))
        self.assertIn("DJANGO_DEBUG=false", env)
        self.assertIn("DJANGO_ALLOWED_HOSTS=opaq.home.example.test,127.0.0.1", env)
        self.assertIn("DJANGO_CSRF_TRUSTED_ORIGINS=https://opaq.home.example.test", env)
        self.assertIn("OPAQ_DATABASE_PATH=/home/opaq-app/data/db.sqlite3", env)
        self.assertIn("PYTHONPATH=/home/opaq-app/site/src:/home/opaq-app/site/services/opaq_app", env)

    def test_unit_is_hardened_and_only_data_is_writable(self) -> None:
        unit = _render("opaq-app.service.j2")
        self.assertIn("User=opaq-app", unit)
        self.assertIn("ProtectSystem=strict", unit)
        self.assertIn("ReadWritePaths=/home/opaq-app/data", unit)
        self.assertIn("NoNewPrivileges=true", unit)
        self.assertIn("\nCapabilityBoundingSet=\n", unit)
        self.assertIn("UMask=0077", unit)
        self.assertIn("--bind 127.0.0.1:10065", unit)

    def test_database_lives_outside_the_synced_tree(self) -> None:
        self.assertFalse(DEFAULTS["opaq_app_data_path"].startswith(DEFAULTS["opaq_app_site_path"]))
        self.assertIn("*.sqlite3", DEFAULTS["opaq_app_rsync_excludes"])
        self.assertEqual(DEFAULTS["opaq_app_source_dirs"], ["src", "services/opaq_app"])

    def test_private_directories_and_files(self) -> None:
        user = (ROLE / "tasks/user.yml").read_text()
        self.assertIn('mode: "0700"', user)
        django = (ROLE / "tasks/django.yml").read_text()
        self.assertEqual(django.count('mode: "0600"'), 2)
        source = (ROLE / "tasks/source.yml").read_text()
        self.assertIn('mode: "u+rwX,go-rwx"', source)

    def test_only_the_app_dependency_group_is_installed(self) -> None:
        python = (ROLE / "tasks/python.yml").read_text()
        for flag in ("--frozen", "--only-group", "--no-install-project"):
            self.assertIn(f"- {flag}", python)

    def test_validation_requires_secrets_host_and_cidr_allowlist(self) -> None:
        tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
        checks = tasks[0]["ansible.builtin.assert"]["that"]
        self.assertIn("opaq_app_upload_token_sha256 is match('^[0-9a-f]{64}$')", checks)
        self.assertIn("not (opaq_app_traefik_enabled | bool) or opaq_app_allowed_networks | length > 0", checks)
        self.assertIs(tasks[0]["no_log"], True)
        self.assertIn("item | local.ops_library.is_cidr", tasks[1]["ansible.builtin.assert"]["that"])

    def test_role_creates_no_user_account(self) -> None:
        text = "".join(p.read_text() for p in (ROLE / "tasks").glob("*.yml"))
        self.assertNotRegex(text, re.compile(r"createsuperuser|create_user|ensure_superuser"))


if __name__ == "__main__":
    unittest.main()
