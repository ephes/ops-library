"""Safety-contract tests for the rendered Heis production backup runner."""

from __future__ import annotations

import contextlib
import io
import shlex
import subprocess
import types
import unittest
from pathlib import Path
from unittest import mock

from jinja2 import Environment, FileSystemLoader, StrictUndefined


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "roles" / "echoport_backup" / "templates"


def render_runner() -> tuple[types.ModuleType, str]:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        undefined=StrictUndefined,
        autoescape=False,
    )
    source = env.get_template("heis_production_backup.py.j2").render(
        echoport_backup_mc_install_path="/usr/local/bin/mc",
        echoport_backup_minio_alias="minio",
        echoport_backup_default_bucket="backups",
        echoport_backup_temp_dir="/tmp/heis-production-backup",
        heis_production_backup_allowed_roots=["/home/heis/site/"],
        heis_production_backup_default_host="152.53.158.41",
        heis_production_backup_remote_user="root",
        heis_production_backup_default_db_path="/home/heis/site/db.sqlite3",
        heis_production_backup_files=["/home/heis/site/media"],
        heis_production_backup_service_names=["heis.service"],
        heis_production_backup_restore_owner="heis:heis",
        heis_production_backup_health_url="http://127.0.0.1:10020/",
        heis_production_backup_health_host="fabian-heis.de",
    )
    module = types.ModuleType("heis_production_backup_test")
    module.__file__ = str(TEMPLATE_DIR / "heis_production_backup.py.j2")
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module, source


class HeisProductionBackupSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner, cls.source = render_runner()

    def test_echoport_context_cannot_override_locked_remote_targets(self) -> None:
        malicious_context = {
            "context": {
                "env": {
                    "ECHOPORT_ACTION": "backup",
                    "ECHOPORT_DB_PATH": "/home/heis/site/.env",
                    "ECHOPORT_BACKUP_FILES": "/home/heis/site",
                    "ECHOPORT_SERVICE_NAME": "ssh.service",
                    "ECHOPORT_RESTORE_OWNER": "root:root",
                    "ECHOPORT_KEY_PREFIX": "test/run",
                }
            }
        }
        with (
            mock.patch.object(
                self.runner, "read_config_file", return_value=malicious_context
            ),
            mock.patch.object(self.runner, "backup", return_value=0) as backup,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(self.runner.main(), 0)

        kwargs = backup.call_args.kwargs
        self.assertEqual(kwargs["db_path"], "/home/heis/site/db.sqlite3")
        self.assertEqual(kwargs["backup_files"], ["/home/heis/site/media"])
        self.assertEqual(kwargs["service_names"], ["heis.service"])

    def test_restore_owner_and_targets_are_locked(self) -> None:
        malicious_context = {
            "context": {
                "env": {
                    "ECHOPORT_ACTION": "restore",
                    "ECHOPORT_DB_PATH": "/home/heis/site/.env",
                    "ECHOPORT_BACKUP_FILES": "/home/heis/site",
                    "ECHOPORT_SERVICE_NAME": "ssh.service",
                    "ECHOPORT_RESTORE_OWNER": "root:root",
                    "ECHOPORT_KEY": "heis-production/test.tar.gz",
                    "ECHOPORT_CHECKSUM": "a" * 64,
                }
            }
        }
        with (
            mock.patch.object(
                self.runner, "read_config_file", return_value=malicious_context
            ),
            mock.patch.object(self.runner, "restore", return_value=0) as restore,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(self.runner.main(), 0)

        kwargs = restore.call_args.kwargs
        self.assertEqual(kwargs["db_path"], "/home/heis/site/db.sqlite3")
        self.assertEqual(kwargs["backup_files"], ["/home/heis/site/media"])
        self.assertEqual(kwargs["service_names"], ["heis.service"])
        self.assertEqual(kwargs["restore_owner"], "heis:heis")

    def test_ssh_subprocess_has_a_hard_timeout(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(
            self.runner.subprocess, "run", return_value=completed
        ) as run:
            self.runner.ssh("152.53.158.41", "root", "/usr/bin/true")
        self.assertEqual(
            run.call_args.kwargs["timeout"], self.runner.COMMAND_TIMEOUT_SECONDS
        )

    def test_ssh_quotes_compound_remote_command_as_one_argument(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "", "")
        remote_command = (
            "rm -rf /home/heis/backup-snapshots/test && "
            "install -d -m 0700 /home/heis/backup-snapshots/test"
        )
        with mock.patch.object(
            self.runner.subprocess, "run", return_value=completed
        ) as run:
            self.runner.ssh("152.53.158.41", "root", remote_command)

        self.assertEqual(
            run.call_args.args[0],
            f"ssh {self.runner.SSH_OPTS} root@152.53.158.41 "
            f"{shlex.quote(remote_command)}",
        )

    def test_partial_stop_failure_leaves_restart_watchdog_armed(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "", "")
        stop_timeout = subprocess.TimeoutExpired("systemctl stop", 900)
        restart_error = subprocess.CalledProcessError(1, "systemctl start")
        with (
            mock.patch.object(
                self.runner,
                "validate_db_path",
                return_value="/home/heis/site/db.sqlite3",
            ),
            mock.patch.object(
                self.runner,
                "validate_remote_directory",
                return_value="/home/heis/site/media",
            ),
            mock.patch.object(self.runner, "ssh", return_value=completed) as ssh,
            mock.patch.object(self.runner, "stop_services", side_effect=stop_timeout),
            mock.patch.object(self.runner, "start_services", side_effect=restart_error),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            result = self.runner.backup(
                remote_host="152.53.158.41",
                remote_user="root",
                db_path="/home/heis/site/db.sqlite3",
                backup_files=["/home/heis/site/media"],
                service_names=["heis.service"],
                bucket="backups",
                key_prefix="heis-production/test",
                timestamp="test",
            )

        self.assertEqual(result, 1)
        commands = [call.args[2] for call in ssh.call_args_list]
        self.assertFalse(
            any(
                "systemctl stop heis-backup-watchdog" in command for command in commands
            )
        )

    def test_runner_contains_remote_watchdogs_and_full_set_rollback(self) -> None:
        for required in (
            "heis-backup-watchdog",
            "heis-restore-watchdog",
            "remote_restore_safety",
            "rollback_restore",
            "trap - ERR",
            'exit "$failure_status"',
            'mv "$safety/db.sqlite3" "$site_db"',
            'mv "$safety/media" "$site_media"',
            "Archive media paths do not match locked targets",
            "migrate --noinput",
            "X-Forwarded-Proto: https",
            "--write-out '%{open_brace}http_code{close_brace}'",
            'test "$status" = 200',
            "verify_services_active",
            'systemctl is-active --quiet "$service"',
            "Leaving {backup_watchdog_unit} armed",
            "Leaving {restore_watchdog_unit} armed",
        ):
            self.assertIn(required, self.source)


if __name__ == "__main__":
    unittest.main()
