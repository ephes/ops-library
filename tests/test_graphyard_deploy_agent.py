"""Contracts for the graphyard deploy role's agent implementation switch.

Section 8.3 of graphyard's agent-rs/PLAN.md: graphyard-agent.service runs the
Python agent (`manage.py start_agent`, the default) or a pinned release of the
Rust port, selected by a systemd drop-in. These tests pin the settings
validation, the versioned install, the candidate validation before the switch,
the drop-in, the live process check and the pruning, and run the role's rsync
excludes through a real `rsync --dry-run` so the Cargo build output of the
port never reaches the host. The Molecule scenario of the role runs the same
paths against systemd with fake release archives.
"""

from __future__ import annotations

import base64
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
from ansible.plugins.filter.core import to_bool
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from tests.test_nyxmon_deploy import find_task, run_cases, walk_tasks


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "graphyard_deploy"
BINARY = "/opt/graphyard-agent/0.1.0/graphyard-agent"
SHA = "a" * 64


def role_defaults() -> dict:
    return yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())


def task_list(name: str) -> list[dict]:
    return yaml.safe_load((ROLE / "tasks" / name).read_text())


def render(template_name: str, **overrides: object) -> str:
    context = {
        "graphyard_user": "graphyard",
        "graphyard_group": "graphyard",
        "graphyard_django_path": "/opt/apps/graphyard/site/src/django",
        "graphyard_env_path": "/etc/graphyard/graphyard.env",
        "graphyard_venv_bin": "/opt/apps/graphyard/site/.venv/bin",
        "graphyard_runtime_enabled": True,
        "graphyard_runtime_service_name": "graphyard-runtime",
        "graphyard_agent_restart_sec": 5,
        "graphyard_agent_rust_binary": BINARY,
        "graphyard_web_bind_host": "127.0.0.1",
        "graphyard_web_bind_port": 8051,
        "graphyard_web_workers": 1,
        "graphyard_web_restart_sec": 5,
    }
    context.update(overrides)
    # Like ansible.builtin.template (trim_blocks defaults to true).
    environment = Environment(
        loader=FileSystemLoader(ROLE / "templates"),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
    )
    environment.filters["bool"] = to_bool
    return environment.get_template(template_name).render(**context)


def synced_paths(source: Path) -> set[str]:
    """Return the paths the role's rsync excludes let `rsync -a` copy from source."""
    with tempfile.TemporaryDirectory() as dest:
        result = subprocess.run(
            [
                "rsync",
                "-a",
                "--dry-run",
                "--out-format=%n",
                *(
                    f"--exclude={pattern}"
                    for pattern in role_defaults()["graphyard_rsync_excludes"]
                ),
                f"{source}/",
                f"{dest}/",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    return {line.rstrip("/") for line in result.stdout.splitlines() if line}


@unittest.skipIf(shutil.which("rsync") is None, "rsync is not installed")
class RsyncExcludeTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.source = Path(tmp.name)
        for path in (
            "pyproject.toml",
            "uv.lock",
            "src/django/manage.py",
            "src/graphyard/services.py",
            "agent-rs/PLAN.md",
            "agent-rs/Cargo.toml",
            "agent-rs/crates/graphyard-agent/src/main.rs",
            "agent-rs/target/release/graphyard-agent",
            "agent-rs/target/debug/deps/big.rlib",
        ):
            file = self.source / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("x")

    def test_cargo_target_directory_is_not_synced(self) -> None:
        synced = synced_paths(self.source)

        self.assertIn("agent-rs", synced)
        self.assertEqual({p for p in synced if p.startswith("agent-rs/target")}, set())

    def test_application_and_port_sources_are_synced(self) -> None:
        synced = synced_paths(self.source)

        for path in (
            "pyproject.toml",
            "uv.lock",
            "src/django/manage.py",
            "src/graphyard/services.py",
            "agent-rs/PLAN.md",
            "agent-rs/crates/graphyard-agent/src/main.rs",
        ):
            with self.subTest(path=path):
                self.assertIn(path, synced)


class AgentImplementationTests(unittest.TestCase):
    """graphyard agent-rs/PLAN.md 8.3: versioned install, drop-in switch."""

    def test_defaults_keep_the_python_agent_and_install_nothing(self) -> None:
        defaults = role_defaults()

        self.assertEqual(defaults["graphyard_agent_impl"], "python")
        self.assertEqual(defaults["graphyard_agent_rust_version"], "")
        self.assertEqual(defaults["graphyard_agent_rust_sha256"], "")
        self.assertEqual(defaults["graphyard_agent_rust_local_archive"], "")
        self.assertEqual(
            defaults["graphyard_agent_rust_install_root"], "/opt/graphyard-agent"
        )
        self.assertEqual(defaults["graphyard_agent_rust_keep_versions"], 3)
        self.assertIn("agent-rs/target/", defaults["graphyard_rsync_excludes"])

    def test_release_url_names_the_tagged_release_asset(self) -> None:
        url = (
            Environment(undefined=StrictUndefined)
            .from_string(role_defaults()["graphyard_agent_rust_release_url"])
            .render(graphyard_agent_rust_version="0.1.0")
        )

        self.assertEqual(
            url,
            "https://github.com/ephes/graphyard/releases/download/agent-rs-v0.1.0/"
            "graphyard-agent-0.1.0-x86_64-unknown-linux-gnu.tar.gz",
        )

    def test_agent_tasks_run_after_migrations_and_verify_after_the_restart(
        self,
    ) -> None:
        tasks = task_list("main.yml")
        names = [task.get("name") for task in tasks]
        install = names.index(
            "main | Install the Rust agent and select the agent implementation"
        )
        verify = names.index(
            "main | Verify the running agent implementation and prune old Rust agents"
        )

        self.assertLess(
            names.index("main | Validate agent implementation settings"),
            names.index("main | Ensure graphyard user and directories"),
        )
        self.assertLess(
            names.index("main | Apply Django environment and management tasks"), install
        )
        self.assertLess(
            install, names.index("main | Configure and start systemd services")
        )
        self.assertLess(
            names.index("main | Apply handlers before health verification"), verify
        )
        self.assertLess(
            verify, names.index("main | Verify Graphyard health endpoint and services")
        )
        self.assertEqual(
            tasks[install]["ansible.builtin.import_tasks"], "agent_rust.yml"
        )
        self.assertEqual(
            tasks[verify]["ansible.builtin.import_tasks"], "agent_verify.yml"
        )
        for index in (install, verify):
            self.assertNotIn("when", tasks[index])

    def test_dropin_starts_the_versioned_binary_on_the_django_database(self) -> None:
        dropin = render("agent-impl.conf.j2")
        base = render("graphyard-agent.service.j2")

        self.assertTrue(
            dropin.endswith(
                "[Service]\nExecStart=\n"
                "ExecStart=/opt/graphyard-agent/0.1.0/graphyard-agent "
                "--db /opt/apps/graphyard/site/src/django/db.sqlite3\n"
            ),
            dropin,
        )
        # Everything but ExecStart comes from the unchanged base unit.
        self.assertEqual(
            [line for line in dropin.splitlines() if line and not line.startswith("#")],
            [
                "[Service]",
                "ExecStart=",
                f"ExecStart={BINARY} --db /opt/apps/graphyard/site/src/django/db.sqlite3",
            ],
        )
        for line in (
            "WorkingDirectory=/opt/apps/graphyard/site/src/django\n",
            "EnvironmentFile=/etc/graphyard/graphyard.env\n",
            "ExecStart=/opt/apps/graphyard/site/.venv/bin/python manage.py start_agent\n",
            "Wants=graphyard-runtime.service\n",
            "User=graphyard\n",
        ):
            with self.subTest(line=line):
                self.assertIn(line, base)

    def test_dropin_exists_only_for_rust_and_every_change_restarts(self) -> None:
        tasks = task_list("agent_rust.yml")
        rust = find_task(
            tasks, "agent_rust | Select the Rust agent for graphyard-agent"
        )
        python = find_task(
            tasks, "agent_rust | Select the Python agent for graphyard-agent"
        )
        path = find_task(tasks, "agent_rust | Derive the drop-in path")

        self.assertEqual(rust["when"], "graphyard_agent_impl == 'rust'")
        self.assertEqual(python["when"], "graphyard_agent_impl == 'python'")
        self.assertEqual(rust["ansible.builtin.template"]["src"], "agent-impl.conf.j2")
        self.assertEqual(python["ansible.builtin.file"]["state"], "absent")
        for task in (rust, python):
            self.assertEqual(
                task["notify"], ["reload systemd", "restart graphyard agent"]
            )
        self.assertEqual(
            path["ansible.builtin.set_fact"]["graphyard_agent_dropin"],
            "/etc/systemd/system/{{ graphyard_agent_unit }}.service.d/agent-impl.conf",
        )

    def test_handlers_reload_before_the_restart(self) -> None:
        handlers = [
            h["name"]
            for h in yaml.safe_load((ROLE / "handlers" / "main.yml").read_text())
        ]

        self.assertEqual(
            handlers,
            ["reload systemd", "restart graphyard web", "restart graphyard agent"],
        )

    def test_candidate_is_validated_before_the_dropin_changes(self) -> None:
        tasks = task_list("agent_rust.yml")
        names = [task.get("name") for task in walk_tasks(tasks)]
        install = find_task(
            tasks, "agent_rust | Install and validate the pinned Rust agent release"
        )

        self.assertEqual(install["when"], "graphyard_agent_rust_version | length > 0")
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
                "agent_rust | Select the Rust agent for graphyard-agent",
            ),
        ):
            self.assertLess(names.index(earlier), names.index(later))
        version = find_task(
            tasks, "agent_rust | Read the version of the candidate binary"
        )
        schema = find_task(
            tasks, "agent_rust | Check the database schema with the candidate binary"
        )
        for task in (version, schema):
            self.assertEqual(task["become_user"], "{{ graphyard_user }}")
            # Validation needs no secrets: no EnvironmentFile, no environment.
            self.assertNotIn("environment", task)
            self.assertEqual(
                task["ansible.builtin.command"]["argv"][0],
                "{{ graphyard_agent_rust_binary }}",
            )
        self.assertEqual(version["ansible.builtin.command"]["argv"][1:], ["--version"])
        self.assertEqual(
            schema["ansible.builtin.command"]["argv"][1:],
            ["--check-schema", "--db", "{{ graphyard_django_path }}/db.sqlite3"],
        )
        rescue = find_task(tasks, "agent_rust | Remove the rejected fresh install")
        self.assertEqual(
            rescue["when"], "not graphyard_agent_rust_dir_stat.stat.exists"
        )

    def test_candidate_must_report_the_pinned_version(self) -> None:
        task = find_task(
            task_list("agent_rust.yml"),
            "agent_rust | Assert the candidate reports the pinned version",
        )

        def case(rc: int, stdout: str) -> dict:
            return {
                "graphyard_agent_rust_version": "0.1.0",
                "graphyard_agent_rust_binary": BINARY,
                "graphyard_agent_rust_version_check": {
                    "rc": rc,
                    "stdout": stdout,
                    "stderr": "",
                },
            }

        outcomes = run_cases(
            task,
            {
                "pinned": case(0, f"graphyard-agent 0.1.0 ({'0' * 40})\n"),
                "other_version": case(0, f"graphyard-agent 0.1.1 ({'0' * 40})\n"),
                "other_binary": case(0, f"nyxmon-agent 0.1.0 ({'0' * 40})\n"),
                "nonzero_exit": case(1, f"graphyard-agent 0.1.0 ({'0' * 40})\n"),
                "empty": case(0, ""),
            },
            "none",
        )

        self.assertEqual(
            outcomes,
            {
                "pinned": None,
                "other_version": "failed",
                "other_binary": "failed",
                "nonzero_exit": "failed",
                "empty": "failed",
            },
        )

    def test_download_is_checksum_pinned(self) -> None:
        download = find_task(
            task_list("agent_rust.yml"), "agent_rust | Download the release archive"
        )

        self.assertEqual(
            download["ansible.builtin.get_url"]["checksum"],
            "sha256:{{ graphyard_agent_rust_sha256 }}",
        )
        self.assertEqual(
            download["ansible.builtin.get_url"]["url"],
            "{{ graphyard_agent_rust_release_url }}",
        )

    def test_archive_members_must_be_regular_files_before_extraction(self) -> None:
        tasks = task_list("agent_rust.yml")
        names = [task.get("name") for task in walk_tasks(tasks)]
        check = find_task(
            tasks,
            "agent_rust | Assert the archive holds only the agent and its license as regular files",
        )

        self.assertLess(
            names.index(check["name"]),
            names.index("agent_rust | Unpack the release archive"),
        )
        chmod = find_task(
            tasks, "agent_rust | Make the agent binary root-owned and executable"
        )
        self.assertIs(chmod["ansible.builtin.file"]["follow"], False)

    def test_archive_must_hold_exactly_the_agent_and_its_license(self) -> None:
        task = find_task(
            task_list("agent_rust.yml"),
            "agent_rust | Assert the archive holds only the agent and its license as regular files",
        )
        regular = "-rwxr-xr-x root/root 100 2026-10-21 12:00 {}"

        def case(names: list[str], types: list[str] | None = None) -> dict:
            return {
                "graphyard_agent_rust_member_names": {"stdout_lines": names},
                "graphyard_agent_rust_member_types": {
                    "stdout_lines": types
                    if types is not None
                    else [regular.format(name) for name in names]
                },
            }

        outcomes = run_cases(
            task,
            {
                "release_layout": case(["graphyard-agent", "LICENSE"]),
                "dot_prefixed": case(["./graphyard-agent", "./LICENSE"]),
                "missing_license": case(["graphyard-agent"]),
                "missing_binary": case(["LICENSE"]),
                "extra_file": case(["graphyard-agent", "LICENSE", "README"]),
                "duplicate": case(["graphyard-agent", "LICENSE", "graphyard-agent"]),
                "in_a_directory": case(["dist/graphyard-agent", "LICENSE"]),
                "symlink": case(
                    ["graphyard-agent", "LICENSE"],
                    [
                        "lrwxrwxrwx root/root 0 2026-10-21 12:00 graphyard-agent -> /etc/shadow",
                        regular.format("LICENSE"),
                    ],
                ),
            },
            "none",
        )

        self.assertEqual(
            outcomes,
            {
                "release_layout": None,
                "dot_prefixed": None,
                "missing_license": "failed",
                "missing_binary": "failed",
                "extra_file": "failed",
                "duplicate": "failed",
                "in_a_directory": "failed",
                "symlink": "failed",
            },
        )

    def test_settings_validation(self) -> None:
        task = find_task(
            task_list("main.yml"), "main | Validate agent implementation settings"
        )
        base = {
            "graphyard_agent_impl": "python",
            "graphyard_agent_rust_version": "",
            "graphyard_agent_rust_sha256": "",
            "graphyard_agent_rust_local_archive": "",
            "graphyard_agent_rust_install_root": "/opt/graphyard-agent",
            "graphyard_agent_rust_keep_versions": 3,
        }
        accepted = {
            "defaults": {},
            "python_with_a_pinned_release": {
                "graphyard_agent_rust_version": "0.1.0",
                "graphyard_agent_rust_sha256": SHA,
            },
            "rust_release": {
                "graphyard_agent_impl": "rust",
                "graphyard_agent_rust_version": "0.1.0",
                "graphyard_agent_rust_sha256": SHA,
            },
            "rust_local_archive": {
                "graphyard_agent_impl": "rust",
                "graphyard_agent_rust_version": "0.2.0-rc.1",
                "graphyard_agent_rust_local_archive": "/tmp/a.tar.gz",
            },
            "keep_one": {"graphyard_agent_rust_keep_versions": 1},
            "keep_as_string": {"graphyard_agent_rust_keep_versions": "2"},
        }
        refused = {
            "unknown_impl": {"graphyard_agent_impl": "go"},
            "rust_without_version": {"graphyard_agent_impl": "rust"},
            "version_without_checksum": {"graphyard_agent_rust_version": "0.1.0"},
            "short_checksum": {
                "graphyard_agent_rust_version": "0.1.0",
                "graphyard_agent_rust_sha256": "a" * 63,
            },
            "uppercase_checksum": {
                "graphyard_agent_rust_version": "0.1.0",
                "graphyard_agent_rust_sha256": "A" * 64,
            },
            "checksum_without_version": {"graphyard_agent_rust_sha256": SHA},
            "archive_without_version": {
                "graphyard_agent_rust_local_archive": "/tmp/a.tar.gz"
            },
            "version_with_a_path": {
                "graphyard_agent_rust_version": "../0.1.0",
                "graphyard_agent_rust_sha256": SHA,
            },
            "version_with_a_v": {
                "graphyard_agent_rust_version": "v0.1.0",
                "graphyard_agent_rust_sha256": SHA,
            },
            "version_as_a_number": {
                "graphyard_agent_rust_version": 0.1,
                "graphyard_agent_rust_sha256": SHA,
            },
            "root_install_root": {"graphyard_agent_rust_install_root": "/"},
            "relative_install_root": {
                "graphyard_agent_rust_install_root": "opt/graphyard-agent"
            },
            "install_root_with_a_space": {
                "graphyard_agent_rust_install_root": "/opt/graphyard agent"
            },
            "keep_zero": {"graphyard_agent_rust_keep_versions": 0},
            "keep_negative": {"graphyard_agent_rust_keep_versions": -1},
            "keep_boolean": {"graphyard_agent_rust_keep_versions": True},
        }
        cases = {
            name: {**base, **overrides}
            for name, overrides in {**accepted, **refused}.items()
        }

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

        def case(content: str | None) -> dict:
            variables: dict = {
                "graphyard_agent_rust_install_root": "/opt/graphyard-agent"
            }
            variables["graphyard_agent_dropin_before"] = (
                {"skipped": True}
                if content is None
                else {"content": base64.b64encode(content.encode()).decode()}
            )
            return variables

        outcomes = run_cases(
            task,
            {
                "rust_dropin": case(render("agent-impl.conf.j2")),
                "no_dropin": case(None),
                "foreign_path": case(
                    "[Service]\nExecStart=\nExecStart=/usr/bin/x --db y\n"
                ),
            },
            "graphyard_agent_rust_active_before",
        )

        self.assertEqual(
            outcomes, {"rust_dropin": "0.1.0", "no_dropin": "", "foreign_path": ""}
        )

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
                "graphyard_agent_rust_active_before": before,
                "graphyard_agent_rust_active_before_stat": {"stat": {"isdir": True}},
                "graphyard_agent_impl": impl,
                "graphyard_agent_rust_version": version,
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

    def test_live_check_identifies_each_implementation(self) -> None:
        tasks = task_list("agent_verify.yml")
        read = find_task(tasks, "agent_verify | Read the live graphyard-agent process")
        expected = read["vars"]["graphyard_agent_expected_lines"]

        def lines(impl: str) -> list[str]:
            return yaml.safe_load(
                Environment()
                .from_string(expected)
                .render(
                    graphyard_agent_impl=impl,
                    graphyard_agent_rust_binary=BINARY,
                    graphyard_venv_bin="/opt/apps/graphyard/site/.venv/bin",
                )
            )

        self.assertEqual(lines("rust"), [f"exe={BINARY}"])
        self.assertEqual(
            lines("python"),
            [
                "arg=/opt/apps/graphyard/site/.venv/bin/python",
                "arg=manage.py",
                "arg=start_agent",
            ],
        )
        assert_task = find_task(
            tasks, "agent_verify | Assert graphyard-agent runs the selected agent"
        )
        self.assertEqual(assert_task["vars"], read["vars"])
        self.assertIn('readlink "/proc/$pid/exe"', read["ansible.builtin.shell"])
        self.assertIn('done < "/proc/$pid/cmdline"', read["ansible.builtin.shell"])
        # 10 x 3 s: the plan's 30 s retry window after the restart.
        self.assertEqual((read["retries"], read["delay"]), (10, 3))

    def test_live_check_accepts_only_the_selected_agent(self) -> None:
        tasks = task_list("agent_verify.yml")
        check = find_task(
            tasks, "agent_verify | Assert graphyard-agent runs the selected agent"
        )
        venv = "/opt/apps/graphyard/site/.venv/bin"
        python_argv = [f"arg={venv}/python", "arg=manage.py", "arg=start_agent"]

        def case(impl: str, *lines: str) -> dict:
            return {
                "graphyard_agent_impl": impl,
                "graphyard_agent_unit": "graphyard-agent",
                "graphyard_agent_rust_binary": BINARY,
                "graphyard_agent_rust_install_root": "/opt/graphyard-agent",
                "graphyard_venv_bin": venv,
                "graphyard_agent_live": {"stdout_lines": list(lines)},
            }

        rust_argv = [
            f"arg={BINARY}",
            "arg=--db",
            "arg=/opt/apps/graphyard/site/src/django/db.sqlite3",
        ]
        uv_python = (
            "exe=/opt/apps/graphyard/.local/share/uv/python/cpython-3.12/bin/python3.12"
        )
        outcomes = run_cases(
            {**check, "vars": {**check["vars"]}},
            {
                "rust_running": case(
                    "rust", "state=active", "pid=7", f"exe={BINARY}", *rust_argv
                ),
                "rust_other_version": case(
                    "rust",
                    "state=active",
                    "pid=7",
                    "exe=/opt/graphyard-agent/0.0.9/graphyard-agent",
                    *rust_argv,
                ),
                "rust_still_python": case(
                    "rust", "state=active", "pid=7", uv_python, *python_argv
                ),
                "rust_inactive": case("rust", "state=activating", "pid=0"),
                "python_running": case(
                    "python", "state=active", "pid=7", uv_python, *python_argv
                ),
                "python_still_rust": case(
                    "python", "state=active", "pid=7", f"exe={BINARY}", *rust_argv
                ),
                "python_argv_from_a_rust_binary": case(
                    "python", "state=active", "pid=7", f"exe={BINARY}", *python_argv
                ),
                "python_other_command": case(
                    "python",
                    "state=active",
                    "pid=7",
                    uv_python,
                    f"arg={venv}/python",
                    "arg=manage.py",
                    "arg=runserver",
                ),
                "python_failed": case("python", "state=failed", "pid=0"),
            },
            "none",
        )

        self.assertEqual(
            outcomes,
            {
                "rust_running": None,
                "rust_other_version": "failed",
                "rust_still_python": "failed",
                "rust_inactive": "failed",
                "python_running": None,
                "python_still_rust": "failed",
                "python_argv_from_a_rust_binary": "failed",
                "python_other_command": "failed",
                "python_failed": "failed",
            },
        )

    def test_pruning_follows_the_live_check(self) -> None:
        tasks = task_list("agent_verify.yml")
        verify = find_task(
            tasks, "agent_verify | Verify the running agent implementation"
        )
        prune = find_task(tasks, "agent_verify | Prune old Rust agent versions")

        self.assertLess(tasks.index(verify), tasks.index(prune))
        self.assertEqual(verify["when"], "not ansible_check_mode")
        self.assertIn("graphyard_agent_rust_version | length > 0", prune["when"])
        self.assertIn("not ansible_check_mode", prune["when"])

    def test_pruning_keeps_the_pinned_previous_live_and_newest_versions(self) -> None:
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
                "graphyard_agent_rust_version": pinned,
                "graphyard_agent_rust_keep_versions": keep,
                "graphyard_agent_rust_install_root": "/opt/graphyard-agent",
                "graphyard_agent_live": {
                    "stdout_lines": ["state=active", "pid=42", f"exe={live}", "arg=x"]
                },
                "graphyard_agent_rust_installed": {
                    "files": [
                        {"path": f"/opt/graphyard-agent/{name}", "mtime": mtime}
                        for name, mtime in installed
                    ]
                },
                "graphyard_agent_rust_previous": (
                    {"failed": True, "msg": "file not found"}
                    if previous is None
                    else {
                        "content": base64.b64encode(f"{previous}\n".encode()).decode()
                    }
                ),
            }

        outcomes = run_cases(
            task,
            {
                "newest_three": case("0.5.0-rc.1", None, 3),
                "old_pin_and_previous": case("0.1.0", "0.2.0", 1),
                "live_binary": case(
                    "0.1.0",
                    "0.2.0",
                    1,
                    live="/opt/graphyard-agent/0.3.0/graphyard-agent",
                ),
            },
            "graphyard_agent_rust_versions_installed | difference(graphyard_agent_rust_versions_kept) | sort",
        )

        self.assertEqual(outcomes["newest_three"], ["0.1.0", "0.2.0"])
        self.assertEqual(outcomes["old_pin_and_previous"], ["0.3.0", "0.4.0"])
        self.assertEqual(outcomes["live_binary"], ["0.4.0"])

    def test_readme_documents_the_switch_and_rollback(self) -> None:
        readme = (ROLE / "README.md").read_text()

        for name in role_defaults():
            if name.startswith("graphyard_agent_impl") or name.startswith(
                "graphyard_agent_rust_"
            ):
                with self.subTest(variable=name):
                    self.assertIn(f"`{name}`", readme)
        for text in (
            "agent-impl.conf",
            "--check-schema",
            "### Rollback",
            "agent-rs/target/",
        ):
            with self.subTest(text=text):
                self.assertIn(text, readme)


class RuntimeDependencyTests(unittest.TestCase):
    """graphyard-web and graphyard-agent survive graphyard-runtime transitions.

    Requires=, PartOf= and BindsTo= all stop the units with the runtime, and
    a later start of the runtime does not start them again (the container CA
    activation stops and starts its owner units; 2026-10-21 outage). Wants=
    plus After= keeps the boot order and pulls the runtime in without tying
    their lifetime to it. The runtime_deps Molecule scenario runs this
    against systemd.
    """

    UNITS = ("graphyard-web.service.j2", "graphyard-agent.service.j2")

    @staticmethod
    def unit_lines(template: str, **overrides: object) -> list[str]:
        unit = render(template, **overrides)
        section = unit.split("[Service]", 1)[0]
        return [
            line
            for line in section.splitlines()
            if line and not line.startswith("#")
        ]

    def test_units_want_and_follow_the_runtime_without_stop_propagation(
        self,
    ) -> None:
        for template in self.UNITS:
            with self.subTest(template=template):
                lines = self.unit_lines(
                    template, graphyard_runtime_service_name="gy-runtime"
                )
                self.assertIn("Wants=gy-runtime.service", lines)
                after = next(line for line in lines if line.startswith("After="))
                self.assertIn("gy-runtime.service", after.split("=", 1)[1].split())
                for directive in ("Requires=", "Requisite=", "BindsTo=", "PartOf="):
                    self.assertFalse(
                        [line for line in lines if line.startswith(directive)],
                        f"{template}: {directive} ties the unit to the runtime",
                    )

    def test_units_without_a_runtime_do_not_name_it(self) -> None:
        for template in self.UNITS:
            with self.subTest(template=template):
                unit = render(template, graphyard_runtime_enabled=False)
                self.assertNotIn("graphyard-runtime", unit)
                self.assertNotIn("\n\n\n", unit)

    def test_runtime_unit_is_a_oneshot_that_stays_active(self) -> None:
        unit = render(
            "graphyard-runtime.service.j2",
            graphyard_home="/opt/apps/graphyard",
            graphyard_compose_project_name="graphyard-runtime",
            graphyard_compose_path="/opt/apps/graphyard/docker-compose.yml",
        )

        for line in ("Type=oneshot\n", "RemainAfterExit=yes\n"):
            with self.subTest(line=line):
                self.assertIn(line, unit)
        # The runtime does not pull the app units in; they pull it in.
        self.assertNotIn("graphyard-web", unit)
        self.assertNotIn("graphyard-agent", unit)

    def test_molecule_scenario_covers_the_runtime_transitions(self) -> None:
        scenario = ROLE / "molecule" / "runtime_deps"
        cases = (scenario / "cases.yml").read_text()
        converge = (scenario / "converge.yml").read_text()

        self.assertIn("tasks_from: service.yml", converge)
        self.assertIn("templates/graphyard-runtime.service.j2", converge)
        self.assertIn("templates/agent-impl.conf.j2", cases)
        for case in ("restart", "stop/start", "failed start", "cold start"):
            with self.subTest(case=case):
                self.assertIn(f"| Case {case}:", cases)

    def test_readme_explains_the_dependency_choice(self) -> None:
        readme = (ROLE / "README.md").read_text()

        for text in ("### Unit dependencies", "`Wants=`", "`PartOf=`", "`BindsTo=`", "runtime_deps"):
            with self.subTest(text=text):
                self.assertIn(text, readme)

if __name__ == "__main__":
    unittest.main()
