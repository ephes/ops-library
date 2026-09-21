"""Contracts for the Nyxmon deploy role's SQLite isolation and alert policy.

These tests pin the behaviour that keeps a live SQLite database out of the
blast radius of source synchronisation, and the elapsed-time notification
settings rendered into the worker environment.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "nyxmon_deploy"


def role_defaults() -> dict:
    return yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())





def render(template_name: str, **overrides: object) -> str:
    defaults = role_defaults()
    context = {
        "nyxmon_user": "nyxmon",
        "nyxmon_group": "nyxmon",
        "nyxmon_home": "/home/nyxmon",
        "nyxmon_site_path": "/home/nyxmon/site",
        "nyxmon_venv_bin": "/home/nyxmon/site/.venv/bin",
        "nyxmon_cache_dir": "/home/nyxmon/site/cache",
        "nyxmon_django_path": "/home/nyxmon/site",
        "nyxmon_django_settings_module": "config.settings.production",
        "nyxmon_django_secret_key": "test-secret-key",
        "nyxmon_django_allowed_hosts": "127.0.0.1",
        "nyxmon_django_admin_url": "admin/",
        "nyxmon_django_debug": False,
        "nyxmon_telegram_bot_token": "test-token",
        "nyxmon_telegram_chat_id": "1",
        "nyxmon_notify_consecutive_failures": defaults[
            "nyxmon_notify_consecutive_failures"
        ],
        "nyxmon_notify_repeat_interval_seconds": defaults[
            "nyxmon_notify_repeat_interval_seconds"
        ],
        "nyxmon_notify_warning_repeat_interval_seconds": defaults[
            "nyxmon_notify_warning_repeat_interval_seconds"
        ],
        "nyxmon_processing_lease_seconds": defaults["nyxmon_processing_lease_seconds"],
        "nyxmon_check_batch_size": defaults["nyxmon_check_batch_size"],
        "nyxmon_opsgate_submit_base_url": "",
        "nyxmon_opsgate_submit_token": "",
        "nyxmon_app_host": "127.0.0.1",
        "nyxmon_app_port": 10017,
        "nyxmon_workers": 4,
    }
    context.update(overrides)
    environment = Environment(
        loader=FileSystemLoader(ROLE / "templates"),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    environment.filters["lower"] = lambda value: str(value).lower()
    return environment.get_template(template_name).render(**context)


class SourceSyncSafetyTests(unittest.TestCase):
    def test_sync_never_deletes_a_live_database_or_its_sidecars(self) -> None:
        excludes = role_defaults()["nyxmon_rsync_excludes"]

        for required in (
            "db.sqlite3",
            "db.sqlite3-wal",
            "db.sqlite3-shm",
            "db.sqlite3-journal",
            "db.sqlite3*",
            "*.sqlite3",
            ".env",
        ):
            with self.subTest(exclude=required):
                self.assertIn(required, excludes)

    def test_sync_does_not_re_own_the_destination_directory(self) -> None:
        tasks = yaml.safe_load((ROLE / "tasks" / "source_rsync.yml").read_text())
        syncs = [
            task
            for task in tasks
            if task.get("ansible.posix.synchronize") is not None
        ]

        self.assertEqual(len(syncs), 2)
        for task in syncs:
            module = task["ansible.posix.synchronize"]
            with self.subTest(task=task["name"]):
                self.assertIs(module["owner"], False)
                self.assertIs(module["group"], False)
                self.assertIn("nyxmon_rsync_excludes", module["rsync_opts"])

    def test_database_and_sidecars_stay_private_to_nyxmon(self) -> None:
        main_tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
        tasks = yaml.safe_load((ROLE / "tasks" / "sqlite_privacy.yml").read_text())
        include = next(
            task
            for task in main_tasks
            if task.get("name") == "Enforce SQLite credential privacy"
        )
        find_task = next(
            task
            for task in tasks
            if task.get("name") == "sqlite_privacy | Find database and sidecars"
        )
        mode_task = next(
            task
            for task in tasks
            if task.get("name") == "sqlite_privacy | Restrict database and sidecars"
        )
        flush_index = next(
            index
            for index, task in enumerate(tasks)
            if task.get("name") == "sqlite_privacy | Activate writer umask drop-ins"
        )
        find_index = tasks.index(find_task)

        self.assertEqual(include["include_tasks"], "sqlite_privacy.yml")
        include_index = main_tasks.index(include)
        for predecessor in (
            "Deploy source code",
            "Configure Django application",
            "Setup systemd service",
            "Setup monitoring",
        ):
            predecessor_index = next(
                index
                for index, task in enumerate(main_tasks)
                if task.get("name") == predecessor
            )
            self.assertLess(predecessor_index, include_index)
        self.assertLess(flush_index, find_index)
        self.assertEqual(find_task["ansible.builtin.find"]["patterns"], "db.sqlite3*")
        self.assertIs(find_task["ansible.builtin.find"]["recurse"], False)
        self.assertEqual(mode_task["ansible.builtin.file"]["mode"], "0600")
        raw = (ROLE / "tasks" / "sqlite_privacy.yml").read_text()
        self.assertEqual(raw.count("UMask=0077"), 1)
        self.assertIn("restart nyxmon for SQLite privacy", raw)
        self.assertIn("restart nyxmon-monitor for SQLite privacy", raw)
        self.assertIn("item.mode == '0600'", raw)

        ordered_names = [task["name"] for task in tasks]
        for earlier, later in zip(
            (
                "sqlite_privacy | Install writer umask drop-ins",
                "sqlite_privacy | Activate writer umask drop-ins",
                "sqlite_privacy | Find database and sidecars",
                "sqlite_privacy | Restrict database and sidecars",
                "sqlite_privacy | Re-read database and sidecar metadata",
            ),
            (
                "sqlite_privacy | Activate writer umask drop-ins",
                "sqlite_privacy | Find database and sidecars",
                "sqlite_privacy | Restrict database and sidecars",
                "sqlite_privacy | Re-read database and sidecar metadata",
                "sqlite_privacy | Verify database and sidecars are private",
            ),
        ):
            self.assertLess(ordered_names.index(earlier), ordered_names.index(later))

    def test_exactly_one_recursive_ownership_fix_scoped_to_the_site_tree(self) -> None:
        tasks = yaml.safe_load((ROLE / "tasks" / "source_rsync.yml").read_text())
        recursive = [
            task
            for task in tasks
            if (task.get("file") or {}).get("recurse") is True
        ]

        self.assertEqual(len(recursive), 1)
        self.assertEqual(recursive[0]["file"]["path"], "{{ nyxmon_site_path }}")


class NotificationPolicyTests(unittest.TestCase):
    def test_defaults_do_not_page_on_the_first_sample(self) -> None:
        defaults = role_defaults()

        self.assertEqual(defaults["nyxmon_notify_consecutive_failures"], 2)
        self.assertNotIn("nyxmon_notify_repeat_failures", defaults)

    def test_reminder_cadence_is_elapsed_time_not_sample_count(self) -> None:
        defaults = role_defaults()

        self.assertEqual(defaults["nyxmon_notify_repeat_interval_seconds"], 21600)
        self.assertEqual(
            defaults["nyxmon_notify_warning_repeat_interval_seconds"], 86400
        )

        env_file = render("nyxmon.env.j2")
        self.assertIn("NYXMON_NOTIFY_CONSECUTIVE_FAILURES=2", env_file)
        self.assertIn("NYXMON_NOTIFY_REPEAT_INTERVAL_SECONDS=21600", env_file)
        self.assertIn("NYXMON_NOTIFY_WARNING_REPEAT_INTERVAL_SECONDS=86400", env_file)
        self.assertNotIn("NYXMON_NOTIFY_REPEAT_FAILURES", env_file)

    def test_the_removed_sample_count_variable_warns_instead_of_failing(self) -> None:
        main_tasks = (ROLE / "tasks" / "main.yml").read_text()

        self.assertIn("Warn about the removed sample-count reminder variable", main_tasks)
        self.assertIn("when: nyxmon_notify_repeat_failures is defined", main_tasks)

    def test_settings_are_range_checked(self) -> None:
        main_tasks = (ROLE / "tasks" / "main.yml").read_text()

        self.assertIn("Validate Nyxmon reliability settings are whole numbers", main_tasks)
        self.assertIn("(item.value | string) is match('^[0-9]+$')", main_tasks)
        self.assertIn("nyxmon_notify_repeat_interval_seconds | int >= 60", main_tasks)
        self.assertIn(
            "nyxmon_notify_warning_repeat_interval_seconds | int <= 2592000",
            main_tasks,
        )
        self.assertIn("nyxmon_notify_consecutive_failures | int <= 100", main_tasks)


if __name__ == "__main__":
    unittest.main()
