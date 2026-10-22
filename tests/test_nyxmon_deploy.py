"""Contracts for the Nyxmon deploy role's SQLite isolation and alert policy.

These tests pin the behaviour that keeps a live SQLite database out of the
blast radius of source synchronisation, and the elapsed-time notification
settings rendered into the worker environment.
"""

from __future__ import annotations

import base64
import grp
import json
import os
import pwd
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

import yaml
from ansible.plugins.filter.core import to_bool
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
        "nyxmon_require_login": defaults["nyxmon_require_login"],
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
    environment.filters["bool"] = to_bool
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

    def test_ownership_fix_never_walks_the_site_root_recursively(self) -> None:
        # The live database sits in the site root, and the writers create and
        # delete its sidecars at any moment. A recursive walk over the root
        # lists them and fails when one is gone before the chown.
        tasks = yaml.safe_load((ROLE / "tasks" / "source_rsync.yml").read_text())
        recursive = [
            task
            for task in tasks
            if "recurse" in (task.get("file") or {})
        ]
        listing = next(
            task
            for task in tasks
            if task.get("name") == "source_rsync | List site entries for the ownership fix"
        )
        root = next(
            task
            for task in tasks
            if task.get("name") == "source_rsync | Set ownership for the site root"
        )

        self.assertEqual(len(recursive), 1)
        sweep = recursive[0]
        self.assertEqual(sweep["name"], "source_rsync | Set ownership for synced files")
        self.assertEqual(sweep["file"]["recurse"], "{{ item.isdir }}")
        self.assertEqual(sweep["file"]["follow"], "{{ not item.islnk }}")
        self.assertEqual(sweep["file"]["path"], "{{ item.path }}")
        self.assertIn("nyxmon_site_entries.files", sweep["loop"])
        self.assertNotIn("mode", sweep["file"])
        self.assertEqual(
            listing["find"],
            {
                "paths": "{{ nyxmon_site_path }}",
                "file_type": "any",
                "hidden": True,
                "recurse": False,
                "excludes": ["db.sqlite3-*"],
            },
        )
        self.assertNotIn("recurse", root["file"])
        self.assertEqual(root["file"]["state"], "directory")
        names = [task["name"] for task in tasks]
        self.assertLess(names.index(listing["name"]), names.index(sweep["name"]))
        self.assertEqual(names[-1], sweep["name"])

    def test_rsync_deploys_require_the_database_in_the_site_root(self) -> None:
        validate = next(
            task
            for task in yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
            if task.get("name") == "Validate rsync-specific requirements"
        )
        base = {
            "nyxmon_deploy_method": "rsync",
            "nyxmon_source_path": "/src/nyxmon",
            "nyxmon_site_path": "/home/nyxmon/site",
        }

        self.assertEqual(
            run_cases(
                validate,
                {
                    "site_root": {**base, "nyxmon_django_path": "/home/nyxmon/site"},
                    "trailing_slash": {**base, "nyxmon_django_path": "/home/nyxmon/site/"},
                    "subdirectory": {**base, "nyxmon_django_path": "/home/nyxmon/site/src/django"},
                    "git_ignores_it": {
                        **base,
                        "nyxmon_deploy_method": "git",
                        "nyxmon_django_path": "/home/nyxmon/site/src/django",
                    },
                },
                "None",
            ),
            {
                "site_root": None,
                "trailing_slash": None,
                "subdirectory": "failed",
                "git_ignores_it": None,
            },
        )


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


class RequireLoginTests(unittest.TestCase):
    def test_login_is_off_by_default(self) -> None:
        self.assertIs(role_defaults()["nyxmon_require_login"], False)
        self.assertIn("\nNYXBOARD_REQUIRE_LOGIN=false\n", render("nyxmon.env.j2"))

    def test_login_switch_renders_a_django_boolean(self) -> None:
        for value, expected in (
            (True, "true"),
            ("true", "true"),
            ("yes", "true"),
            (False, "false"),
            ("false", "false"),
            ("no", "false"),
        ):
            with self.subTest(value=value):
                env_file = render("nyxmon.env.j2", nyxmon_require_login=value)
                self.assertEqual(
                    re.findall(r"(?m)^NYXBOARD_REQUIRE_LOGIN=(.*)$", env_file),
                    [expected],
                )

    def test_the_readme_documents_the_switch(self) -> None:
        readme = (ROLE / "README.md").read_text()

        self.assertIn("`nyxmon_require_login`", readme)
        self.assertIn("`NYXBOARD_REQUIRE_LOGIN`", readme)



class ProductionSettingsContractTests(unittest.TestCase):
    """config.settings.production redirects plain HTTP and checks the host."""

    def test_default_settings_module_is_production(self) -> None:
        self.assertEqual(
            role_defaults()["nyxmon_django_settings_module"],
            "config.settings.production",
        )

    def test_env_file_provides_what_production_settings_require(self) -> None:
        rendered = render("nyxmon.env.j2", nyxmon_django_allowed_hosts="127.0.0.1,x.test")

        for line in (
            "DJANGO_SETTINGS_MODULE=config.settings.production",
            "DJANGO_SECRET_KEY=test-secret-key",
            "DJANGO_ALLOWED_HOSTS=127.0.0.1,x.test",
            "DJANGO_CACHE_LOCATION=/home/nyxmon/site/cache",
            "DJANGO_ADMIN_URL=admin/",
        ):
            self.assertIn(line + "\n", rendered)

    def test_web_service_starts_the_proxy_aware_entrypoint_on_loopback(self) -> None:
        unit = render("nyxmon.service.j2")

        self.assertIn("--host 127.0.0.1", unit)
        self.assertIn("config.wsgi_proxy:application", unit)

    def test_restore_probe_presents_itself_as_https_from_loopback(self) -> None:
        restore = ROOT / "roles" / "nyxmon_restore"
        defaults = yaml.safe_load((restore / "defaults" / "main.yml").read_text())
        (probe,) = [
            task
            for task in yaml.safe_load((restore / "tasks" / "verify.yml").read_text())
            if task["name"] == "HTTP health probe"
        ]

        self.assertTrue(
            defaults["nyxmon_restore_health_url"].startswith("http://127.0.0.1:")
        )
        self.assertIn("127.0.0.1", role_defaults()["nyxmon_django_allowed_hosts"])
        self.assertEqual(
            defaults["nyxmon_restore_health_headers"], {"X-Forwarded-Proto": "https"}
        )
        self.assertEqual(defaults["nyxmon_restore_health_expected_status"], 200)
        self.assertEqual(
            probe["ansible.builtin.uri"]["headers"],
            "{{ nyxmon_restore_health_headers }}",
        )


def task_list(name: str) -> list[dict]:
    return yaml.safe_load((ROLE / "tasks" / name).read_text())


def walk_tasks(tasks: list[dict]):
    for task in tasks or []:
        yield task
        for key in ("block", "rescue", "always"):
            yield from walk_tasks(task.get(key, []))


def find_task(tasks: list[dict], name: str) -> dict:
    return next(task for task in walk_tasks(tasks) if task.get("name") == name)


def run_cases(task: dict, cases: dict[str, dict], show: str) -> dict[str, object]:
    """Run one role task once per case on localhost and report each outcome.

    Returns ``{case: "failed"}`` for a failed task, else the value of the
    variable ``show`` after the task (``None`` for an assert).
    """
    plays = []
    for case, variables in cases.items():
        plays.append(
            {
                "name": case,
                "hosts": "localhost",
                "gather_facts": False,
                "vars": variables,
                "tasks": [
                    {
                        "block": [
                            dict(task),
                            {
                                "ansible.builtin.debug": {
                                    "msg": "CASE {{ "
                                    + json.dumps(case)
                                    + " }} {{ ({'value': "
                                    + show
                                    + "}) | to_json }}"
                                }
                            },
                        ],
                        "rescue": [
                            {
                                "ansible.builtin.debug": {
                                    "msg": "CASE {{ " + json.dumps(case) + " }} failed"
                                }
                            }
                        ],
                    }
                ],
            }
        )
    with tempfile.TemporaryDirectory() as tmp:
        playbook = Path(tmp) / "cases.yml"
        playbook.write_text(yaml.safe_dump(plays))
        result = subprocess.run(
            [
                str(Path(sys.executable).parent / "ansible-playbook"),
                "-i",
                "localhost,",
                "-c",
                "local",
                str(playbook),
            ],
            capture_output=True,
            text=True,
            check=False,
            env={
                **os.environ,
                "ANSIBLE_STDOUT_CALLBACK": "json",
                "ANSIBLE_LOCALHOST_WARNING": "false",
            },
        )
    if result.returncode != 0:
        raise AssertionError(result.stdout[-4000:] + result.stderr[-4000:])
    outcomes: dict[str, object] = {}
    for play in json.loads(result.stdout)["plays"]:
        for task_result in play["tasks"]:
            message = task_result["hosts"]["localhost"].get("msg", "")
            if isinstance(message, str) and message.startswith("CASE "):
                case, _, rest = message[len("CASE ") :].partition(" ")
                outcomes[case] = "failed" if rest == "failed" else json.loads(rest)["value"]
    return outcomes


class RustAgentTests(unittest.TestCase):
    """PLAN.md 8.3 of nyxmon agent-rs: versioned install, drop-in switch."""

    def test_defaults_keep_the_python_agent_and_install_nothing(self) -> None:
        defaults = role_defaults()

        self.assertEqual(defaults["nyxmon_agent_impl"], "python")
        self.assertEqual(defaults["nyxmon_agent_rust_version"], "")
        self.assertEqual(defaults["nyxmon_agent_rust_sha256"], "")
        self.assertEqual(defaults["nyxmon_agent_rust_local_archive"], "")
        self.assertEqual(defaults["nyxmon_agent_rust_install_root"], "/opt/nyxmon-agent")
        self.assertEqual(defaults["nyxmon_agent_rust_keep_versions"], 3)

    def test_release_url_names_the_tagged_release_asset(self) -> None:
        url = (
            Environment(undefined=StrictUndefined)
            .from_string(role_defaults()["nyxmon_agent_rust_release_url"])
            .render(nyxmon_agent_rust_version="0.1.0")
        )

        self.assertEqual(
            url,
            "https://github.com/ephes/nyxmon/releases/download/agent-rs-v0.1.0/"
            "nyxmon-agent-0.1.0-x86_64-unknown-linux-gnu.tar.gz",
        )

    def test_agent_tasks_run_after_migrations_and_verify_after_the_restart(self) -> None:
        names = [task.get("name") for task in task_list("main.yml")]
        install = names.index("Install the Rust agent and select the agent implementation")
        verify = names.index(
            "main | Verify the running agent implementation and prune old Rust agents"
        )

        self.assertLess(names.index("Configure Django application"), install)
        self.assertLess(install, names.index("Setup monitoring"))
        self.assertLess(
            names.index("main | Flush handlers before OpsGate smoke validation"), verify
        )
        self.assertLess(
            verify, names.index("main | Validate live nyxmon-monitor OpsGate settings")
        )
        self.assertLess(
            names.index("Validate monitoring agent implementation settings"),
            names.index("Setup user and directories"),
        )

    def test_dropin_starts_the_versioned_binary_with_the_python_arguments(self) -> None:
        dropin = render(
            "agent-impl.conf.j2",
            nyxmon_agent_rust_binary="/opt/nyxmon-agent/0.1.0/nyxmon-agent",
        )
        base = render("nyxmon-monitor.service.j2")

        self.assertIn(
            "[Service]\nExecStart=\n"
            "ExecStart=/opt/nyxmon-agent/0.1.0/nyxmon-agent "
            "--db /home/nyxmon/site/db.sqlite3 --enable-telegram\n",
            dropin,
        )
        self.assertIn(
            "ExecStart=/home/nyxmon/site/.venv/bin/start-agent "
            "--db /home/nyxmon/site/db.sqlite3 --enable-telegram\n",
            base,
        )

    def test_dropin_exists_only_for_rust_and_every_change_restarts(self) -> None:
        tasks = task_list("agent_rust.yml")
        rust = find_task(tasks, "agent_rust | Select the Rust agent for the monitoring unit")
        python = find_task(tasks, "agent_rust | Select the Python agent for the monitoring unit")

        self.assertEqual(rust["when"], "nyxmon_agent_impl == 'rust'")
        self.assertEqual(python["when"], "nyxmon_agent_impl == 'python'")
        self.assertEqual(python["ansible.builtin.file"]["state"], "absent")
        for task in (rust, python):
            self.assertEqual(task["notify"], ["reload systemd", "restart nyxmon-monitor"])

    def test_candidate_is_validated_before_the_dropin_changes(self) -> None:
        tasks = task_list("agent_rust.yml")
        names = [task.get("name") for task in walk_tasks(tasks)]
        install = find_task(tasks, "agent_rust | Install and validate the pinned Rust agent release")

        self.assertEqual(install["when"], "nyxmon_agent_rust_version | length > 0")
        for earlier, later in (
            (
                "agent_rust | Refuse a different archive for an installed version",
                "agent_rust | Download the release archive",
            ),
            (
                "agent_rust | Download the release archive",
                "agent_rust | Assert the candidate reports the pinned version",
            ),
            (
                "agent_rust | Assert the candidate reports the pinned version",
                "agent_rust | Assert the database schema satisfies the candidate",
            ),
            (
                "agent_rust | Assert the database schema satisfies the candidate",
                "agent_rust | Select the Rust agent for the monitoring unit",
            ),
        ):
            self.assertLess(names.index(earlier), names.index(later))
        version = find_task(tasks, "agent_rust | Read the version of the candidate binary")
        schema = find_task(tasks, "agent_rust | Check the database schema with the candidate binary")
        for task in (version, schema):
            self.assertEqual(task["become_user"], "{{ nyxmon_user }}")
            self.assertEqual(
                task["ansible.builtin.command"]["argv"][0], "{{ nyxmon_agent_rust_binary }}"
            )
        self.assertEqual(
            schema["ansible.builtin.command"]["argv"][1:],
            ["--check-schema", "--db", "{{ nyxmon_django_path }}/db.sqlite3"],
        )
        rescue = find_task(tasks, "agent_rust | Remove the rejected fresh install")
        self.assertEqual(rescue["when"], "not nyxmon_agent_rust_dir_stat.stat.exists")

    def test_download_is_checksum_pinned(self) -> None:
        download = find_task(task_list("agent_rust.yml"), "agent_rust | Download the release archive")

        self.assertEqual(
            download["ansible.builtin.get_url"]["checksum"],
            "sha256:{{ nyxmon_agent_rust_sha256 }}",
        )

    def test_settings_validation(self) -> None:
        task = find_task(task_list("main.yml"), "Validate monitoring agent implementation settings")
        sha = "a" * 64
        base = {
            "nyxmon_agent_impl": "python",
            "nyxmon_agent_rust_version": "",
            "nyxmon_agent_rust_sha256": "",
            "nyxmon_agent_rust_local_archive": "",
            "nyxmon_agent_rust_install_root": "/opt/nyxmon-agent",
            "nyxmon_agent_rust_keep_versions": 3,
            "nyxmon_monitoring_enabled": True,
        }
        accepted = {
            "defaults": {},
            "python_with_a_pinned_release": {"nyxmon_agent_rust_version": "0.1.0", "nyxmon_agent_rust_sha256": sha},
            "rust_release": {"nyxmon_agent_impl": "rust", "nyxmon_agent_rust_version": "0.1.0", "nyxmon_agent_rust_sha256": sha},
            "rust_local_archive": {"nyxmon_agent_impl": "rust", "nyxmon_agent_rust_version": "0.2.0-rc.1", "nyxmon_agent_rust_local_archive": "/tmp/a.tar.gz"},
            "keep_one": {"nyxmon_agent_rust_keep_versions": 1},
        }
        refused = {
            "unknown_impl": {"nyxmon_agent_impl": "go"},
            "rust_without_version": {"nyxmon_agent_impl": "rust"},
            "rust_without_monitoring": {"nyxmon_agent_impl": "rust", "nyxmon_agent_rust_version": "0.1.0", "nyxmon_agent_rust_sha256": sha, "nyxmon_monitoring_enabled": False},
            "version_without_checksum": {"nyxmon_agent_rust_version": "0.1.0"},
            "short_checksum": {"nyxmon_agent_rust_version": "0.1.0", "nyxmon_agent_rust_sha256": "a" * 63},
            "uppercase_checksum": {"nyxmon_agent_rust_version": "0.1.0", "nyxmon_agent_rust_sha256": "A" * 64},
            "checksum_without_version": {"nyxmon_agent_rust_sha256": sha},
            "archive_without_version": {"nyxmon_agent_rust_local_archive": "/tmp/a.tar.gz"},
            "version_with_a_path": {"nyxmon_agent_rust_version": "../0.1.0", "nyxmon_agent_rust_sha256": sha},
            "version_with_a_v": {"nyxmon_agent_rust_version": "v0.1.0", "nyxmon_agent_rust_sha256": sha},
            "root_install_root": {"nyxmon_agent_rust_install_root": "/"},
            "relative_install_root": {"nyxmon_agent_rust_install_root": "opt/nyxmon-agent"},
            "keep_zero": {"nyxmon_agent_rust_keep_versions": 0},
            "keep_boolean": {"nyxmon_agent_rust_keep_versions": True},
        }
        cases = {name: {**base, **overrides} for name, overrides in {**accepted, **refused}.items()}

        outcomes = run_cases(task, cases, "none")

        for name in accepted:
            with self.subTest(case=name):
                self.assertIsNone(outcomes[name])
        for name in refused:
            with self.subTest(case=name):
                self.assertEqual(outcomes[name], "failed")

    def test_previous_rust_version_is_read_from_the_dropin(self) -> None:
        task = find_task(
            task_list("agent_rust.yml"),
            "agent_rust | Derive the Rust version the drop-in selected so far",
        )
        rendered = render(
            "agent-impl.conf.j2",
            nyxmon_agent_rust_binary="/opt/nyxmon-agent/0.1.0/nyxmon-agent",
        )

        def case(content: str | None) -> dict:
            variables: dict = {"nyxmon_agent_rust_install_root": "/opt/nyxmon-agent"}
            variables["nyxmon_agent_dropin_before"] = (
                {"skipped": True}
                if content is None
                else {"content": base64.b64encode(content.encode()).decode()}
            )
            return variables

        outcomes = run_cases(
            task,
            {
                "rust_dropin": case(rendered),
                "no_dropin": case(None),
                "foreign_path": case("[Service]\nExecStart=\nExecStart=/usr/bin/x --db y\n"),
            },
            "nyxmon_agent_rust_active_before",
        )

        self.assertEqual(
            outcomes, {"rust_dropin": "0.1.0", "no_dropin": "", "foreign_path": ""}
        )

    def test_pruning_keeps_the_pinned_previous_and_newest_versions(self) -> None:
        task = find_task(
            task_list("agent_verify.yml"),
            "agent_verify | Decide which Rust agent versions to keep",
        )
        installed = [
            ("0.1.0", 10),
            ("0.2.0", 20),
            ("0.3.0", 30),
            ("0.4.0", 40),
            ("0.5.0-rc.1", 50),
            ("not-a-version", 60),
        ]

        def case(pinned: str, previous: str | None, keep: int, live: str = "") -> dict:
            return {
                "nyxmon_agent_rust_version": pinned,
                "nyxmon_agent_rust_keep_versions": keep,
                "nyxmon_agent_rust_install_root": "/opt/nyxmon-agent",
                "nyxmon_agent_live": {
                    "stdout_lines": ["state=active", "pid=42", f"exe={live}", "arg=x"]
                },
                "nyxmon_agent_rust_installed": {
                    "files": [
                        {"path": f"/opt/nyxmon-agent/{name}", "mtime": mtime}
                        for name, mtime in installed
                    ]
                },
                "nyxmon_agent_rust_previous": (
                    {"failed": True, "msg": "file not found"}
                    if previous is None
                    else {"content": base64.b64encode(f"{previous}\n".encode()).decode()}
                ),
            }

        outcomes = run_cases(
            task,
            {
                "newest_three": case("0.5.0-rc.1", None, 3),
                "old_pin_and_previous": case("0.1.0", "0.2.0", 1),
                "live_binary": case(
                    "0.1.0", "0.2.0", 1, live="/opt/nyxmon-agent/0.3.0/nyxmon-agent"
                ),
            },
            "nyxmon_agent_rust_versions_installed | difference(nyxmon_agent_rust_versions_kept) | sort",
        )

        self.assertEqual(outcomes["newest_three"], ["0.1.0", "0.2.0"])
        self.assertEqual(outcomes["old_pin_and_previous"], ["0.3.0", "0.4.0"])
        self.assertEqual(outcomes["live_binary"], ["0.4.0"])

    def test_pruning_needs_the_live_check(self) -> None:
        tasks = task_list("agent_verify.yml")
        verify = find_task(tasks, "agent_verify | Verify the running agent implementation")
        prune = find_task(tasks, "agent_verify | Prune old Rust agent versions")

        self.assertIn("nyxmon_monitoring_enabled", verify["when"])
        self.assertIn("nyxmon_monitoring_enabled", prune["when"])
        self.assertLess(tasks.index(verify), tasks.index(prune))

    def test_previous_version_is_recorded_only_when_the_selection_moves(self) -> None:
        condition = find_task(
            task_list("agent_rust.yml"),
            "agent_rust | Remember the previously selected Rust version",
        )["when"]
        # The real task's condition on a harmless task; facts set in one case
        # would leak into the next, a registered result does not.
        probe = {
            "name": "probe",
            "ansible.builtin.debug": {"msg": "recorded"},
            "when": condition,
            "register": "probe",
        }

        def case(before: str, impl: str, version: str) -> dict:
            return {
                "nyxmon_agent_rust_active_before": before,
                "nyxmon_agent_rust_active_before_stat": {"stat": {"isdir": True}},
                "nyxmon_agent_impl": impl,
                "nyxmon_agent_rust_version": version,
            }

        outcomes = run_cases(
            probe,
            {
                "same_version_rewritten": case("0.2.0", "rust", "0.2.0"),
                "rust_to_rust": case("0.1.0", "rust", "0.2.0"),
                "rust_to_python": case("0.2.0", "python", "0.2.0"),
                "no_rust_before": case("", "rust", "0.2.0"),
            },
            "probe is not skipped",
        )

        self.assertEqual(
            outcomes,
            {
                "same_version_rewritten": False,
                "rust_to_rust": True,
                "rust_to_python": True,
                "no_rust_before": False,
            },
        )

    def test_archive_members_must_be_regular_files_before_extraction(self) -> None:
        tasks = task_list("agent_rust.yml")
        names = [task.get("name") for task in walk_tasks(tasks)]
        check = find_task(
            tasks,
            "agent_rust | Assert the archive holds only the agent and its license as regular files",
        )

        self.assertLess(
            names.index(check["name"]), names.index("agent_rust | Unpack the release archive")
        )
        self.assertIn(
            "nyxmon_agent_rust_member_types.stdout_lines | reject('match', '-') | list | length == 0",
            check["ansible.builtin.assert"]["that"],
        )
        chmod = find_task(tasks, "agent_rust | Make the agent binary root-owned and executable")
        self.assertIs(chmod["ansible.builtin.file"]["follow"], False)

    def test_live_process_check_identifies_each_implementation(self) -> None:
        raw = (ROLE / "tasks" / "agent_verify.yml").read_text()

        self.assertIn("('exe=' ~ nyxmon_agent_rust_binary)", raw)
        self.assertIn("('arg=' ~ nyxmon_venv_bin ~ '/start-agent')", raw)
        self.assertIn('readlink "/proc/$pid/exe"', raw)
        self.assertIn('done < "/proc/$pid/cmdline"', raw)

    def test_readme_documents_the_switch_and_rollback(self) -> None:
        readme = (ROLE / "README.md").read_text()

        for name in role_defaults():
            if name.startswith("nyxmon_agent_"):
                with self.subTest(variable=name):
                    self.assertIn(f"`{name}`", readme)
        self.assertIn("agent-impl.conf", readme)
        self.assertIn("Rollback", readme)


def run_play(tasks: list[dict], variables: dict) -> subprocess.CompletedProcess:
    """Run ``tasks`` as one play on localhost; the caller checks the outcome."""
    with tempfile.TemporaryDirectory(suffix="-journal-race") as tmp:
        playbook = Path(tmp) / "play.yml"
        playbook.write_text(
            yaml.safe_dump(
                [
                    {
                        "name": "journal race",
                        "hosts": "localhost",
                        "gather_facts": False,
                        "vars": variables,
                        "tasks": tasks,
                    }
                ]
            )
        )
        return subprocess.run(
            [
                str(Path(sys.executable).parent / "ansible-playbook"),
                "-i",
                "localhost,",
                "-c",
                "local",
                str(playbook),
            ],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "ANSIBLE_LOCALHOST_WARNING": "false"},
        )


class SidecarChurn:
    """Create and delete SQLite sidecars the way a running writer does.

    With journal_mode=delete every write transaction creates
    ``db.sqlite3-journal`` and deletes it at commit; WAL mode does the same to
    ``-wal``/``-shm`` with the connections. SQLite gives sidecars the database
    file's mode, so they are created 0600 here, as next to a restricted
    database.
    """

    NAMES = ("db.sqlite3-journal", "db.sqlite3-wal", "db.sqlite3-shm")

    def __init__(self, directory: Path) -> None:
        self.paths = [directory / name for name in self.NAMES]
        self.stop = threading.Event()
        self.cycles = 0
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self) -> None:
        while not self.stop.is_set():
            for path in self.paths:
                os.close(os.open(path, os.O_CREAT | os.O_WRONLY, 0o600))
            for path in self.paths:
                path.unlink()
            self.cycles += 1

    def __enter__(self) -> "SidecarChurn":
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop.set()
        self.thread.join()


class SqliteSidecarRaceTests(unittest.TestCase):
    """The deploy keeps running writers; their sidecars come and go mid-task.

    At the 2026-10-16 cutover the deploy needed three runs: the privacy pass
    failed on a db.sqlite3-journal deleted between ``find`` and ``file``, the
    ownership fix on one deleted while its recursive walk ran. These tests run
    the role's own tasks on localhost against a directory with that churn.
    """

    def setUp(self) -> None:
        self.site = Path(tempfile.mkdtemp(suffix="-journal-race"))
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.site)], check=False)
        self.variables = {
            "nyxmon_user": pwd.getpwuid(os.getuid()).pw_name,
            "nyxmon_group": grp.getgrgid(os.getgid()).gr_name,
            "nyxmon_site_path": str(self.site),
            "nyxmon_django_path": str(self.site),
        }
        for name in ("db.sqlite3", "db.sqlite3.agent.lock", "manage.py"):
            (self.site / name).write_text(name)
            (self.site / name).chmod(0o644)
        (self.site / "config").mkdir()
        (self.site / "config" / "settings.py").write_text("")
        (self.site / ".venv" / "bin").mkdir(parents=True)
        (self.site / ".venv" / "bin" / "python").write_text("")
        (self.site / "venv").symlink_to(self.site / ".venv")

    def privacy_tasks(self) -> list[dict]:
        tasks = task_list("sqlite_privacy.yml")
        names = [task["name"] for task in tasks]
        return tasks[names.index("sqlite_privacy | Find database and sidecars") :]

    def ownership_tasks(self) -> list[dict]:
        tasks = task_list("source_rsync.yml")
        names = [task["name"] for task in tasks]
        return tasks[names.index("source_rsync | List site entries for the ownership fix") :]

    def with_after(self, tasks: list[dict], name: str, *extra: dict) -> list[dict]:
        names = [task["name"] for task in tasks]
        index = names.index(name) + 1
        return tasks[:index] + list(extra) + tasks[index:]

    def vanish(self, name: str) -> dict:
        return {
            "name": f"writer deletes {name}",
            "ansible.builtin.file": {"path": str(self.site / name), "state": "absent"},
        }

    def mode(self, name: str) -> int:
        return (self.site / name).stat().st_mode & 0o777

    def assertPlay(self, result: subprocess.CompletedProcess, ok: bool) -> None:
        output = result.stdout[-6000:] + result.stderr[-3000:]
        if ok:
            self.assertEqual(result.returncode, 0, output)
        else:
            self.assertNotEqual(result.returncode, 0, output)

    def test_privacy_pass_survives_a_journal_deleted_after_the_listing(self) -> None:
        journal = self.site / "db.sqlite3-journal"
        journal.write_text("")
        journal.chmod(0o644)
        tasks = self.with_after(
            self.privacy_tasks(),
            "sqlite_privacy | Require the main database",
            self.vanish("db.sqlite3-journal"),
        )

        self.assertPlay(run_play(tasks, self.variables), ok=True)
        self.assertEqual(self.mode("db.sqlite3"), 0o600)
        self.assertEqual(self.mode("db.sqlite3.agent.lock"), 0o600)

    def test_the_unguarded_restriction_fails_on_that_journal(self) -> None:
        # Proves the case above is the cutover failure: without the guard for
        # transient sidecars the same sequence fails.
        journal = self.site / "db.sqlite3-journal"
        journal.write_text("")
        tasks = self.with_after(
            self.privacy_tasks(),
            "sqlite_privacy | Require the main database",
            self.vanish("db.sqlite3-journal"),
        )
        for task in tasks:
            if task["name"] == "sqlite_privacy | Restrict database and sidecars":
                task.pop("failed_when")

        self.assertPlay(run_play(tasks, self.variables), ok=False)

    def test_a_vanished_database_still_fails(self) -> None:
        tasks = self.with_after(
            self.privacy_tasks(),
            "sqlite_privacy | Require the main database",
            self.vanish("db.sqlite3"),
        )

        self.assertPlay(run_play(tasks, self.variables), ok=False)

    def test_a_sidecar_that_is_not_private_at_the_end_still_fails(self) -> None:
        # The guard only skips a failed restriction; the verify pass still
        # refuses every database file present afterwards that others can read.
        tasks = self.with_after(
            self.privacy_tasks(),
            "sqlite_privacy | Restrict database and sidecars",
            {
                "name": "a readable sidecar appears",
                "ansible.builtin.copy": {
                    "content": "",
                    "dest": str(self.site / "db.sqlite3-wal"),
                    "mode": "0644",
                },
            },
        )

        self.assertPlay(run_play(tasks, self.variables), ok=False)

    def test_ownership_fix_and_privacy_pass_under_sidecar_churn(self) -> None:
        tasks = self.ownership_tasks() + self.privacy_tasks()

        with SidecarChurn(self.site) as churn:
            for attempt in range(5):
                with self.subTest(attempt=attempt):
                    self.assertPlay(run_play(tasks, self.variables), ok=True)
        self.assertGreater(churn.cycles, 1000)
        self.assertEqual(self.mode("db.sqlite3"), 0o600)
        self.assertEqual(self.mode("manage.py"), 0o644)
        self.assertTrue((self.site / "venv").is_symlink())

    def test_the_old_recursive_walk_fails_under_the_same_churn(self) -> None:
        # Proves the churn reproduces the cutover failure: one recursive walk
        # over the site root (the task this role used before) loses the race.
        old_walk = {
            "name": "the old ownership fix",
            "file": {
                "path": str(self.site),
                "owner": self.variables["nyxmon_user"],
                "group": self.variables["nyxmon_group"],
                "recurse": True,
            },
        }

        with SidecarChurn(self.site):
            results = []
            for _ in range(20):
                results.append(run_play([old_walk], self.variables).returncode)
                if results[-1] != 0:
                    break
        self.assertNotEqual(results[-1], 0, f"no failure in {len(results)} runs")


if __name__ == "__main__":
    unittest.main()
