"""Fail-closed contracts of the Echoport PostfixAdmin runner.

The runner is rendered from its Jinja template and exercised against a
temporary directory tree with psql, mc and systemctl faked out; nothing
touches a real host, database or bucket.
"""

from __future__ import annotations

import json
import subprocess
import tarfile
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from jinja2 import Environment, FileSystemLoader, StrictUndefined


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "roles" / "echoport_backup" / "templates"
TEMPLATE = "postfixadmin_backup.py.j2"

ADMIN_COLUMNS = {
    "username", "password", "superadmin", "created", "modified", "active",
    "phone", "email_other", "token", "token_validity", "totp_secret",
}
ADMIN_ROW = {
    "username": "admin@example.test",
    "password": "{SHA512-CRYPT}hash",
    "superadmin": True,
    "active": True,
    "created": "2026-01-01T00:00:00+00:00",
    "modified": "2026-01-02T00:00:00+00:00",
    "phone": "+49 30 000000",
    "email_other": "other@example.test",
    "token": "",
    "token_validity": "2000-01-01T00:00:00+00:00",
    "totp_secret": "TOTPSECRET",
}


def render_runner(root: Path) -> types.ModuleType:
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), undefined=StrictUndefined, autoescape=False)
    variables: dict[str, Any] = {
        "echoport_backup_mc_install_path": "/usr/local/bin/mc",
        "echoport_backup_minio_alias": "minio",
        "echoport_backup_default_bucket": "backups",
        "echoport_backup_temp_dir": str(root / "tmp"),
        "postfixadmin_echoport_backup_install_path": str(root / "opt/postfixadmin"),
        "postfixadmin_echoport_backup_config_file": str(root / "opt/postfixadmin/config.local.php"),
        "postfixadmin_echoport_backup_nginx_site": str(root / "etc/nginx/postfixadmin"),
        "postfixadmin_echoport_backup_traefik_config": str(root / "etc/traefik/postfixadmin.yml"),
        "postfixadmin_echoport_backup_php_root": str(root / "etc/php"),
        "postfixadmin_echoport_backup_db_credentials_file": str(root / "etc/creds.json"),
        "postfixadmin_echoport_backup_config_owner": "root:www-data",
        "postfixadmin_echoport_backup_system_owner": "root:root",
        "postfixadmin_echoport_backup_health_url": "http://127.0.0.1:8082/",
        "postfixadmin_echoport_backup_health_retries": 1,
        "postfixadmin_echoport_backup_health_delay": 1,
        "postfixadmin_echoport_backup_start_timeout": 20,
        "postfixadmin_echoport_backup_create_safety_snapshot": False,
        "postfixadmin_echoport_backup_rollback_on_failure": False,
        "postfixadmin_echoport_backup_allowed_roots": [str(root) + "/"],
    }
    source = env.get_template(TEMPLATE).render(**variables)
    module = types.ModuleType("postfixadmin_echoport_backup_test")
    module.__file__ = str(TEMPLATE_DIR / TEMPLATE)
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


class FakeDb:
    """Answers the runner's psql calls."""

    def __init__(self, admin_rows=None, log_fails=False, schema="1851"):
        self.admin_rows = [ADMIN_ROW] if admin_rows is None else admin_rows
        self.log_fails = log_fails
        self.schema = schema
        self.statements: list[str] = []

    def run_psql(self, sql: str, creds: Any, check: bool = True) -> subprocess.CompletedProcess:
        self.statements.append(sql)
        if "FROM log" in sql and self.log_fails:
            raise subprocess.CalledProcessError(1, ["psql"], "", 'relation "log" does not exist')
        if "row_to_json" in sql:
            if "FROM admin" in sql:
                rows = self.admin_rows
            elif "FROM domain_admins" in sql:
                rows = [{"username": "admin@example.test", "domain": "ALL", "active": True}]
            else:
                rows = [{"id": 1, "action": "create_domain"}]
            out = "\n".join(json.dumps(r) for r in rows)
        elif "FROM config" in sql:
            out = self.schema
        elif "information_schema.columns" in sql:
            out = "\n".join(sorted(ADMIN_COLUMNS))
        else:
            out = ""
        return subprocess.CompletedProcess(["psql"], 0, out + "\n", "")


class PostfixAdminRunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.runner = render_runner(self.root)
        for rel in (
            "opt/postfixadmin/config.local.php",
            "etc/nginx/postfixadmin",
            "etc/traefik/postfixadmin.yml",
            "etc/php/8.3/fpm/pool.d/postfixadmin.conf",
        ):
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# {rel}\n")
        (self.root / "tmp").mkdir()
        (self.root / "etc/creds.json").write_text(json.dumps(
            {"host": "127.0.0.1", "port": 5432, "database": "mail", "username": "mail", "password": "x"}
        ))
        self.uploaded: Path | None = None

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def fake_run_cmd(self, args, check=True, env=None):
        if args[0].endswith("mc") and args[1] == "cp":
            self.uploaded = self.root / "uploaded.tar.gz"
            self.uploaded.write_bytes(Path(args[2]).read_bytes())
        return subprocess.CompletedProcess(args, 0, "", "")

    def run_backup(self, db: FakeDb) -> tuple[int, list[dict]]:
        events: list[dict] = []
        with mock.patch.object(self.runner, "run_psql", db.run_psql), \
                mock.patch.object(self.runner, "run_cmd", self.fake_run_cmd), \
                mock.patch.object(self.runner, "ensure_binaries", lambda: None), \
                mock.patch.object(self.runner, "_emit", events.append):
            rc = self.runner.backup_flow({"ECHOPORT_KEY_PREFIX": "postfixadmin/test"})
        return rc, events

    def extract_upload(self) -> Path:
        assert self.uploaded is not None
        out = self.root / "extract"
        with tarfile.open(self.uploaded) as tar:
            tar.extractall(out, filter="data")
        return out

    def test_backup_lists_exactly_what_it_wrote(self) -> None:
        rc, _ = self.run_backup(FakeDb())
        self.assertEqual(rc, 0)
        extract = self.extract_upload()
        manifest = json.loads((extract / "manifest.json").read_text())
        self.assertEqual(manifest["format_version"], 2)
        self.assertEqual(manifest["db"]["tables"], ["admin", "domain_admins", "log"])
        self.assertEqual(manifest["db"]["schema_version"], 1851)
        self.assertEqual(
            sorted(manifest["config_files"]),
            ["config.local.php", "nginx-postfixadmin.conf", "php-postfixadmin.conf", "traefik-postfixadmin.yml"],
        )
        admin = json.loads((extract / "db/admin.json").read_text())
        self.assertEqual(admin[0]["totp_secret"], "TOTPSECRET")

    def test_optional_parts_are_left_out_with_a_warning(self) -> None:
        (self.root / "etc/traefik/postfixadmin.yml").unlink()
        rc, events = self.run_backup(FakeDb(log_fails=True))
        self.assertEqual(rc, 0)
        manifest = json.loads((self.extract_upload() / "manifest.json").read_text())
        self.assertEqual(manifest["db"]["tables"], ["admin", "domain_admins"])
        self.assertNotIn("traefik-postfixadmin.yml", manifest["config_files"])
        self.assertEqual(len(manifest["warnings"]), 2)
        self.assertFalse((self.extract_upload() / "db/log.json").exists())
        self.assertTrue(any("WARNING" in e.get("message", "") for e in events))

    def test_unreadable_optional_config_is_a_warning(self) -> None:
        real_copy = self.runner.copy_file_optional

        def copy(src, dst):
            if src.name == "postfixadmin.yml":
                raise PermissionError(f"Permission denied: {src}")
            return real_copy(src, dst)

        with mock.patch.object(self.runner, "copy_file_optional", copy):
            rc, _ = self.run_backup(FakeDb())
        self.assertEqual(rc, 0)
        manifest = json.loads((self.extract_upload() / "manifest.json").read_text())
        self.assertNotIn("traefik-postfixadmin.yml", manifest["config_files"])
        self.assertIn("Permission denied", manifest["warnings"][0])

    def test_missing_required_config_fails_without_upload(self) -> None:
        (self.root / "opt/postfixadmin/config.local.php").unlink()
        rc, events = self.run_backup(FakeDb())
        self.assertEqual(rc, 1)
        self.assertIsNone(self.uploaded)
        self.assertTrue(any("config.local.php" in e.get("message", "") for e in events))

    def test_missing_php_pool_fails(self) -> None:
        (self.root / "etc/php/8.3/fpm/pool.d/postfixadmin.conf").unlink()
        rc, _ = self.run_backup(FakeDb())
        self.assertEqual(rc, 1)
        self.assertIsNone(self.uploaded)

    def test_empty_admin_table_fails(self) -> None:
        rc, _ = self.run_backup(FakeDb(admin_rows=[]))
        self.assertEqual(rc, 1)
        self.assertIsNone(self.uploaded)

    def test_missing_schema_version_fails(self) -> None:
        rc, _ = self.run_backup(FakeDb(schema=""))
        self.assertEqual(rc, 1)
        self.assertIsNone(self.uploaded)

    def test_admin_upsert_restores_every_column(self) -> None:
        sql = self.runner.admin_upsert_sql(ADMIN_ROW, ADMIN_COLUMNS)
        for column in ("totp_secret", "phone", "email_other", "token", "token_validity"):
            self.assertIn(f"{column} = EXCLUDED.{column}", sql)
        self.assertIn("'TOTPSECRET'", sql)

    def test_admin_upsert_of_a_legacy_row(self) -> None:
        legacy = {"username": "a@example.test", "password": "p", "superadmin": True, "active": True}
        sql = self.runner.admin_upsert_sql(legacy, ADMIN_COLUMNS)
        self.assertIn("created, modified) VALUES", sql)
        self.assertIn("modified = EXCLUDED.modified", sql)
        self.assertNotIn("created = EXCLUDED.created", sql)

    def test_admin_upsert_refuses_unknown_columns(self) -> None:
        row = dict(ADMIN_ROW, **{"evil); DROP TABLE admin; --": "x"})
        with self.assertRaises(ValueError):
            self.runner.admin_upsert_sql(row, ADMIN_COLUMNS)
        with self.assertRaises(ValueError):
            self.runner.admin_upsert_sql({"username": "a"}, ADMIN_COLUMNS)

    def validate(self, extract: Path, db: FakeDb | None = None):
        db = db or FakeDb()
        with mock.patch.object(self.runner, "run_psql", db.run_psql):
            return self.runner.validate_archive(extract, {})

    def test_restore_accepts_a_complete_archive(self) -> None:
        self.run_backup(FakeDb())
        tables, config_files = self.validate(self.extract_upload())
        self.assertEqual(tables, ["admin", "domain_admins", "log"])
        self.assertIn("config.local.php", config_files)

    def test_restore_refuses_a_missing_listed_part(self) -> None:
        self.run_backup(FakeDb())
        extract = self.extract_upload()
        (extract / "config/traefik-postfixadmin.yml").unlink()
        with self.assertRaisesRegex(RuntimeError, "traefik-postfixadmin.yml"):
            self.validate(extract)

    def test_restore_refuses_a_missing_required_part(self) -> None:
        self.run_backup(FakeDb())
        extract = self.extract_upload()
        manifest = json.loads((extract / "manifest.json").read_text())
        manifest["db"]["tables"] = ["admin"]
        (extract / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(RuntimeError, "table domain_admins"):
            self.validate(extract)

    def test_restore_refuses_a_newer_schema(self) -> None:
        self.run_backup(FakeDb())
        with self.assertRaisesRegex(RuntimeError, "schema version"):
            self.validate(self.extract_upload(), FakeDb(schema="1800"))

    def test_restore_accepts_a_legacy_archive(self) -> None:
        extract = self.root / "legacy"
        (extract / "db").mkdir(parents=True)
        (extract / "config").mkdir()
        legacy_admin = [{"username": "a@example.test", "password": "p", "superadmin": True, "active": True}]
        (extract / "db/admin.json").write_text(json.dumps(legacy_admin))
        (extract / "db/domain_admins.json").write_text("[]")
        (extract / "db/log.json").write_text("[]")
        for name in ("config.local.php", "nginx-postfixadmin.conf", "php-postfixadmin.conf"):
            (extract / "config" / name).write_text("x")
        (extract / "manifest.json").write_text(json.dumps({"db": {"tables": ["admin", "domain_admins", "log"]}}))
        tables, config_files = self.validate(extract)
        self.assertEqual(tables, ["admin", "domain_admins", "log"])
        self.assertEqual(config_files, ["config.local.php", "nginx-postfixadmin.conf", "php-postfixadmin.conf"])
        (extract / "config/php-postfixadmin.conf").unlink()
        with self.assertRaisesRegex(RuntimeError, "php-postfixadmin.conf"):
            self.validate(extract)


if __name__ == "__main__":
    unittest.main()
