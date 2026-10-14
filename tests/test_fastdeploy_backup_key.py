"""Object key tests for the rendered FastDeploy backup runner.

From 2026-02-11 to 2026-10-14 the runner deployed on macmini read the Echoport
context from the top level of the FastDeploy config file, while FastDeploy
nests it under ``context.env``. Every backup therefore got an empty key prefix
and was uploaded to the shared key ``.tar.gz``, which nightly retention then
deleted. These tests pin the context lookup and the key fallback.
"""

from __future__ import annotations

import contextlib
import io
import json
import types
import unittest
from pathlib import Path
from unittest import mock

from jinja2 import Environment, FileSystemLoader, StrictUndefined


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "roles" / "echoport_backup" / "templates"
TEMPLATE = "fastdeploy_backup.py.j2"


def render_runner() -> types.ModuleType:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        undefined=StrictUndefined,
        autoescape=False,
    )
    env.filters["to_json"] = json.dumps
    source = env.get_template(TEMPLATE).render(
        echoport_backup_mc_install_path="/usr/local/bin/mc",
        echoport_backup_minio_alias="backup-fastdeploy",
        echoport_backup_default_bucket="backups",
        echoport_backup_temp_dir="/tmp/fastdeploy-backup",
        fastdeploy_echoport_backup_allowed_roots=["/home/fastdeploy/", "/tmp/"],
        fastdeploy_echoport_backup_check_disk_space=True,
        fastdeploy_echoport_backup_cleanup_safety_snapshot=True,
        fastdeploy_echoport_backup_create_safety_snapshot=True,
        fastdeploy_echoport_backup_db_name="fastdeploy",
        fastdeploy_echoport_backup_db_user="fastdeploy",
        fastdeploy_echoport_backup_disk_space_multiplier=2.0,
        fastdeploy_echoport_backup_enforce_host_match=True,
        fastdeploy_echoport_backup_env_file="/home/fastdeploy/site/.env",
        fastdeploy_echoport_backup_health_delay=5,
        fastdeploy_echoport_backup_health_expected_status=200,
        fastdeploy_echoport_backup_health_forwarded_for="",
        fastdeploy_echoport_backup_health_forwarded_proto="",
        fastdeploy_echoport_backup_health_headers={},
        fastdeploy_echoport_backup_health_retries=20,
        fastdeploy_echoport_backup_health_url="http://127.0.0.1:9999/docs",
        fastdeploy_echoport_backup_include_logs=False,
        fastdeploy_echoport_backup_include_workspace=False,
        fastdeploy_echoport_backup_postgres_become_user="postgres",
        fastdeploy_echoport_backup_restore_owner_deploy="deploy:deploy",
        fastdeploy_echoport_backup_restore_owner_fastdeploy="fastdeploy:fastdeploy",
        fastdeploy_echoport_backup_rollback_on_failure=True,
        fastdeploy_echoport_backup_runner_root="/home/deploy/runners",
        fastdeploy_echoport_backup_service_name="fastdeploy",
        fastdeploy_echoport_backup_services_path="/home/fastdeploy/site/services",
        fastdeploy_echoport_backup_site_root="/home/fastdeploy/site",
        fastdeploy_echoport_backup_sudoers_glob="/etc/sudoers.d/fastdeploy_*",
        fastdeploy_echoport_backup_systemd_unit_path="/etc/systemd/system/fastdeploy.service",
        fastdeploy_echoport_backup_traefik_config_path="/etc/traefik/dynamic/fastdeploy.yml",
        fastdeploy_echoport_backup_workspace_path="/home/deploy/_workspace",
        fastdeploy_echoport_backup_writer_services=["fastdeploy"],
    )
    module = types.ModuleType("fastdeploy_backup_test")
    module.__file__ = str(TEMPLATE_DIR / TEMPLATE)
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


ECHOPORT_ENV = {
    "ECHOPORT_ACTION": "backup",
    "ECHOPORT_TARGET": "fastdeploy",
    "ECHOPORT_RUN_ID": "4415",
    "ECHOPORT_BUCKET": "backups",
    "ECHOPORT_KEY_PREFIX": "fastdeploy/2026-10-14T04-54-13",
    "ECHOPORT_TIMESTAMP": "2026-10-14T04-54-13",
}


class FastDeployBackupKeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = render_runner()

    def run_main(self, config: dict) -> dict:
        with (
            mock.patch.object(self.runner, "read_config_file", return_value=config),
            mock.patch.dict(self.runner.os.environ, {}, clear=True),
            mock.patch.object(self.runner, "backup", return_value=0) as backup,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(self.runner.main(), 0)
        return backup.call_args.args[0]

    def test_reads_echoport_context_nested_under_env(self) -> None:
        # Echoport posts {"env": context}; FastDeploy writes it as config["context"].
        cenv = self.run_main({"context": {"env": dict(ECHOPORT_ENV)}})
        self.assertEqual(cenv["ECHOPORT_KEY_PREFIX"], "fastdeploy/2026-10-14T04-54-13")
        self.assertEqual(cenv["ECHOPORT_TIMESTAMP"], "2026-10-14T04-54-13")
        self.assertEqual(
            self.runner.resolve_backup_key(cenv, "fastdeploy", cenv["ECHOPORT_TIMESTAMP"]),
            "fastdeploy/2026-10-14T04-54-13.tar.gz",
        )

    def test_still_accepts_a_flat_context(self) -> None:
        cenv = self.run_main({"context": dict(ECHOPORT_ENV)})
        self.assertEqual(cenv["ECHOPORT_KEY_PREFIX"], "fastdeploy/2026-10-14T04-54-13")

    def test_empty_prefix_falls_back_to_target_and_timestamp(self) -> None:
        cenv = self.run_main({"context": {"env": {"ECHOPORT_ACTION": "backup"}}})
        self.assertEqual(cenv["ECHOPORT_KEY_PREFIX"], "")
        key = self.runner.resolve_backup_key(cenv, "fastdeploy", "2026-10-15T03-40-01")
        self.assertEqual(key, "fastdeploy/2026-10-15T03-40-01.tar.gz")

    def test_never_returns_the_shared_dot_tar_gz_key(self) -> None:
        for prefix in ("", "/", "//"):
            with self.subTest(prefix=prefix):
                key = self.runner.resolve_backup_key(
                    {"ECHOPORT_KEY_PREFIX": prefix}, "fastdeploy", "2026-10-15T03-40-01"
                )
                self.assertEqual(key, "fastdeploy/2026-10-15T03-40-01.tar.gz")

    def test_refuses_a_key_without_any_prefix(self) -> None:
        with self.assertRaises(ValueError):
            self.runner.resolve_backup_key({"ECHOPORT_KEY_PREFIX": ""}, "", "")

    def test_backup_fails_before_upload_when_no_prefix_can_be_built(self) -> None:
        with (
            mock.patch.object(self.runner, "resolve_backup_key", side_effect=ValueError("no prefix")),
            mock.patch.object(self.runner, "run_cmd") as run_cmd,
            mock.patch.object(self.runner, "read_config_file", return_value={"context": {"env": {}}}),
            contextlib.redirect_stdout(io.StringIO()) as out,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(self.runner.main(), 1)
        run_cmd.assert_not_called()
        self.assertIn('{"name": "result", "state": "failure"', out.getvalue())


if __name__ == "__main__":
    unittest.main()
