"""Contracts for the mailgun-relay deploy role.

The relay repository also holds the Rust port under rust/ and is often
deployed from a git worktree, where `.git` is a file. The rsync tests run the
role's exclude patterns through a real `rsync --dry-run` so the rsync
pattern semantics (anchoring, directory-only matches) are checked, not
just the list contents.

The implementation tests pin the Python/Rust switch (mailgun-relay
rust/PLAN.md 9.1): versioned install, candidate validation, the drop-in,
the live check and pruning. The Molecule scenario runs the same paths
against systemd.
"""

from __future__ import annotations

import base64
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from tests.test_nyxmon_deploy import find_task, run_cases, walk_tasks


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "mailgun_relay_deploy"


def role_defaults() -> dict:
    return yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())


def rsync_excludes() -> list[str]:
    return role_defaults()["mailgun_relay_rsync_excludes"]


def task_list(name: str) -> list[dict]:
    return yaml.safe_load((ROLE / "tasks" / name).read_text())


def render(template_name: str, **context: object) -> str:
    environment = Environment(
        loader=FileSystemLoader(ROLE / "templates"),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    return environment.get_template(template_name).render(**context)


def synced_paths(source: Path) -> set[str]:
    """Return the paths `rsync -a` would copy from source with the role's excludes."""
    with tempfile.TemporaryDirectory() as dest:
        result = subprocess.run(
            [
                "rsync",
                "-a",
                "--dry-run",
                "--out-format=%n",
                *(f"--exclude={pattern}" for pattern in rsync_excludes()),
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
            "src/mailgun_relay/__init__.py",
            "src/mailgun_relay/rust/module.py",
            "rust/PLAN.md",
            "rust/target/debug/big.rlib",
            "rust/spikes/s1b/Cargo.toml",
            "rust/spikes/s1b/target/release/binary",
            "vendor/.git/HEAD",
            ".venv/bin/python",
        ):
            file = self.source / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("x")
        # A git worktree checkout: `.git` is a file pointing at the main repo.
        (self.source / ".git").write_text("gitdir: /elsewhere/.git/worktrees/x\n")

    def test_python_service_sources_are_synced(self) -> None:
        synced = synced_paths(self.source)
        for path in (
            "pyproject.toml",
            "uv.lock",
            "src/mailgun_relay/__init__.py",
            # Only the top-level rust/ is excluded, not every directory named rust.
            "src/mailgun_relay/rust/module.py",
        ):
            with self.subTest(path=path):
                self.assertIn(path, synced)

    def test_rust_port_is_not_synced(self) -> None:
        synced = synced_paths(self.source)
        self.assertEqual({p for p in synced if p.split("/")[0] == "rust"}, set())

    def test_git_metadata_is_not_synced_as_file_or_directory(self) -> None:
        synced = synced_paths(self.source)
        self.assertNotIn(".git", synced)
        self.assertEqual({p for p in synced if ".git" in p.split("/")}, set())


class ImplementationSwitchTests(unittest.TestCase):
    """mailgun-relay rust/PLAN.md 9.1: versioned install, drop-in switch."""

    def test_defaults_keep_python_and_install_nothing(self) -> None:
        defaults = role_defaults()

        self.assertEqual(defaults["mailgun_relay_impl"], "python")
        self.assertEqual(defaults["mailgun_relay_rust_version"], "")
        self.assertEqual(defaults["mailgun_relay_rust_sha256"], "")
        self.assertEqual(defaults["mailgun_relay_rust_local_archive"], "")
        self.assertEqual(defaults["mailgun_relay_rust_install_root"], "/opt/mailgun-relay")
        self.assertEqual(defaults["mailgun_relay_rust_keep_versions"], 3)

    def test_release_url_names_the_tagged_release_asset(self) -> None:
        url = (
            Environment(undefined=StrictUndefined)
            .from_string(role_defaults()["mailgun_relay_rust_release_url"])
            .render(mailgun_relay_rust_version="0.2.0")
        )

        self.assertEqual(
            url,
            "https://github.com/ephes/mailgun-relay/releases/download/rs-v0.2.0/"
            "mailgun-relay-0.2.0-x86_64-unknown-linux-gnu.tar.gz",
        )

    def test_task_order(self) -> None:
        names = [task.get("name") for task in task_list("main.yml")]

        for earlier, later in (
            ("main | Validate implementation settings", "main | Ensure service user and directories"),
            ("main | Render env and secrets files", "main | Install the pinned Rust release and select the implementation"),
            ("main | Install the pinned Rust release and select the implementation", "main | Configure and start systemd service"),
            ("main | Apply handlers before health verification", "main | Verify health endpoint"),
            ("main | Verify health endpoint", "main | Verify the running implementation and prune old Rust releases"),
        ):
            with self.subTest(earlier=earlier, later=later):
                self.assertLess(names.index(earlier), names.index(later))
        verify = find_task(
            task_list("main.yml"),
            "main | Verify the running implementation and prune old Rust releases",
        )
        # The live check does not depend on the optional health check.
        self.assertNotIn("when", verify)

    def test_python_dropin_is_removed_before_any_rust_step(self) -> None:
        tasks = task_list("impl.yml")
        names = [task.get("name") for task in tasks]
        python = find_task(tasks, "impl | Select the Python implementation")
        rust_steps = find_task(tasks, "impl | Install and validate the pinned Rust release")

        self.assertLess(names.index(python["name"]), names.index(rust_steps["name"]))
        self.assertEqual(python["when"], "mailgun_relay_impl == 'python'")
        self.assertEqual(python["ansible.builtin.file"]["state"], "absent")
        self.assertEqual(rust_steps["ansible.builtin.import_tasks"], "rust.yml")
        self.assertEqual(rust_steps["when"], "mailgun_relay_rust_version | length > 0")
        self.assertLess(
            names.index(rust_steps["name"]), names.index("impl | Select the Rust implementation")
        )

    def test_dropin_exists_only_for_rust_and_every_change_restarts(self) -> None:
        tasks = task_list("impl.yml")
        rust = find_task(tasks, "impl | Select the Rust implementation")
        python = find_task(tasks, "impl | Select the Python implementation")

        self.assertEqual(rust["when"], "mailgun_relay_impl == 'rust'")
        self.assertEqual(rust["ansible.builtin.template"]["src"], "impl.conf.j2")
        for task in (rust, python):
            self.assertEqual(task["notify"], ["reload systemd", "restart mailgun-relay"])

    def test_dropin_starts_the_versioned_binary_with_a_fixed_mmap_threshold(self) -> None:
        dropin = render(
            "impl.conf.j2",
            mailgun_relay_rust_binary="/opt/mailgun-relay/0.2.0/mailgun-relay",
        )
        base = render(
            "mailgun-relay.service.j2",
            mailgun_relay_user="mailgun-relay",
            mailgun_relay_group="mailgun-relay",
            mailgun_relay_site_path="/opt/apps/mailgun-relay/site",
            mailgun_relay_env_path="/etc/mailgun-relay/mailgun-relay.env",
            mailgun_relay_venv_bin="/opt/apps/mailgun-relay/site/.venv/bin",
        )
        directives = [
            line for line in dropin.splitlines() if line and not line.startswith("#")
        ]

        self.assertEqual(
            directives,
            [
                "[Service]",
                "ExecStart=",
                "ExecStart=/opt/mailgun-relay/0.2.0/mailgun-relay",
                "Environment=MALLOC_MMAP_THRESHOLD_=131072",
            ],
        )
        # The reason for the setting stays next to it.
        self.assertIn("mmap threshold", dropin)
        self.assertIn(
            "ExecStart=/opt/apps/mailgun-relay/site/.venv/bin/python -m mailgun_relay\n", base
        )

    def test_rust_failures_are_fatal_only_for_rust(self) -> None:
        tasks = task_list("rust.yml")
        (outer,) = tasks
        rescue = {task["name"]: task for task in outer["rescue"]}

        stop = rescue["rust | Stop on a rejected Rust release"]
        self.assertEqual(stop["when"], "mailgun_relay_impl == 'rust'")
        self.assertIn("ansible.builtin.fail", stop)
        warn = rescue["rust | Warn about the rejected Rust release and continue with Python"]
        self.assertIs(warn["ignore_errors"], True)
        self.assertNotIn("when", warn)
        self.assertEqual(
            rescue["rust | Remove the rejected fresh install"]["when"],
            "not (mailgun_relay_rust_dir_stat.stat.exists | default(true))",
        )
        self.assertEqual(
            rescue["rust | Record the rejected Rust release"]["ansible.builtin.set_fact"],
            {"mailgun_relay_rust_install_failed": True},
        )
        names = list(rescue)
        self.assertLess(
            names.index("rust | Stop on a rejected Rust release"),
            names.index("rust | Warn about the rejected Rust release and continue with Python"),
        )
        # Every install and validation step sits inside the rescued block.
        inside = [task.get("name") for task in walk_tasks(outer["block"])]
        for name in (
            "rust | Download the release archive",
            "rust | Refuse a different archive for an installed version",
            "rust | Assert the archive holds only the relay and its license as regular files",
            "rust | Assert the candidate reports the pinned version",
            "rust | Assert the candidate accepts the configuration",
        ):
            with self.subTest(task=name):
                self.assertIn(name, inside)

    def test_candidate_is_validated_before_the_dropin_changes(self) -> None:
        tasks = task_list("rust.yml")
        names = [task.get("name") for task in walk_tasks(tasks)]
        for earlier, later in (
            (
                "rust | Refuse a different archive for an installed version",
                "rust | Download the release archive",
            ),
            (
                "rust | Assert the archive holds only the relay and its license as regular files",
                "rust | Unpack the release archive",
            ),
            (
                "rust | Download the release archive",
                "rust | Assert the candidate reports the pinned version",
            ),
            (
                "rust | Assert the candidate reports the pinned version",
                "rust | Assert the candidate accepts the configuration",
            ),
        ):
            with self.subTest(earlier=earlier, later=later):
                self.assertLess(names.index(earlier), names.index(later))

        version = find_task(tasks, "rust | Read the version of the candidate binary")
        self.assertEqual(version["become_user"], "{{ mailgun_relay_user }}")
        self.assertEqual(
            version["ansible.builtin.command"]["argv"],
            ["{{ mailgun_relay_rust_binary }}", "--version"],
        )
        check = find_task(tasks, "rust | Check the configuration with the candidate binary")
        argv = check["ansible.builtin.command"]["argv"]
        self.assertEqual(argv[:4], ["systemd-run", "--wait", "--pipe", "--collect"])
        self.assertEqual(argv[-2:], ["{{ mailgun_relay_rust_binary }}", "--check-config"])
        for prop in (
            "--property=User={{ mailgun_relay_user }}",
            "--property=Group={{ mailgun_relay_group }}",
            "--property=EnvironmentFile={{ mailgun_relay_env_path }}",
        ):
            with self.subTest(prop=prop):
                self.assertIn(prop, argv)
        self.assertIs(check["check_mode"], False)
        self.assertIs(check["failed_when"], False)

    def test_check_config_runs_with_the_hardening_of_the_unit(self) -> None:
        argv = find_task(
            task_list("rust.yml"), "rust | Check the configuration with the candidate binary"
        )["ansible.builtin.command"]["argv"]
        unit = (ROLE / "templates" / "mailgun-relay.service.j2").read_text()
        properties = {
            arg.split("=", 1)[1].split("=", 1)[0]
            for arg in argv
            if arg.startswith("--property=")
        }

        for line in unit.splitlines():
            key, _, value = line.partition("=")
            if key in {"NoNewPrivileges", "ProtectSystem", "ProtectHome", "PrivateTmp", "PrivateDevices"}:
                with self.subTest(setting=key):
                    self.assertIn(key, properties)
                    self.assertTrue(value)

    def test_download_is_checksum_pinned(self) -> None:
        download = find_task(task_list("rust.yml"), "rust | Download the release archive")

        self.assertEqual(
            download["ansible.builtin.get_url"]["checksum"],
            "sha256:{{ mailgun_relay_rust_sha256 }}",
        )

    def test_archive_members_must_be_regular_files_before_extraction(self) -> None:
        tasks = task_list("rust.yml")
        check = find_task(
            tasks,
            "rust | Assert the archive holds only the relay and its license as regular files",
        )

        self.assertIn(
            "mailgun_relay_rust_member_types.stdout_lines | reject('match', '-') | list | length == 0",
            check["ansible.builtin.assert"]["that"],
        )
        chmod = find_task(tasks, "rust | Make the relay binary root-owned and executable")
        self.assertIs(chmod["ansible.builtin.file"]["follow"], False)

    def test_archive_must_hold_exactly_the_relay_and_its_license(self) -> None:
        task = find_task(
            task_list("rust.yml"),
            "rust | Assert the archive holds only the relay and its license as regular files",
        )
        regular = "-rwxr-xr-x root/root 100 2026-10-15 12:00 {}"

        def case(names: list[str], types: list[str] | None = None) -> dict:
            return {
                "mailgun_relay_rust_member_names": {"stdout_lines": names},
                "mailgun_relay_rust_member_types": {
                    "stdout_lines": types
                    if types is not None
                    else [regular.format(name) for name in names]
                },
            }

        outcomes = run_cases(
            task,
            {
                "release_layout": case(["mailgun-relay", "LICENSE"]),
                "dot_prefixed": case(["./mailgun-relay", "./LICENSE"]),
                "missing_license": case(["mailgun-relay"]),
                "missing_binary": case(["LICENSE"]),
                "extra_file": case(["mailgun-relay", "LICENSE", "README"]),
                "duplicate": case(["mailgun-relay", "LICENSE", "mailgun-relay"]),
                "in_a_directory": case(["dist/mailgun-relay", "LICENSE"]),
                "symlink": case(
                    ["mailgun-relay", "LICENSE"],
                    [
                        "lrwxrwxrwx root/root 0 2026-10-15 12:00 mailgun-relay -> /etc/shadow",
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
        task = find_task(task_list("main.yml"), "main | Validate implementation settings")
        sha = "a" * 64
        base = {
            "mailgun_relay_impl": "python",
            "mailgun_relay_rust_version": "",
            "mailgun_relay_rust_sha256": "",
            "mailgun_relay_rust_local_archive": "",
            "mailgun_relay_rust_install_root": "/opt/mailgun-relay",
            "mailgun_relay_rust_keep_versions": 3,
            "mailgun_relay_site_path": "/opt/apps/mailgun-relay/site",
        }
        accepted = {
            "defaults": {},
            "python_with_a_pinned_release": {"mailgun_relay_rust_version": "0.2.0", "mailgun_relay_rust_sha256": sha},
            "rust_release": {"mailgun_relay_impl": "rust", "mailgun_relay_rust_version": "0.2.0", "mailgun_relay_rust_sha256": sha},
            "rust_local_archive": {"mailgun_relay_impl": "rust", "mailgun_relay_rust_version": "0.3.0-rc.1", "mailgun_relay_rust_local_archive": "/tmp/a.tar.gz"},
            "keep_one": {"mailgun_relay_rust_keep_versions": 1},
            "root_next_to_the_site": {"mailgun_relay_rust_install_root": "/opt/apps/mailgun-relay/site-rust"},
            "dotted_name": {"mailgun_relay_rust_install_root": "/opt/.mailgun-relay"},
        }
        refused = {
            "unknown_impl": {"mailgun_relay_impl": "go"},
            "rust_without_version": {"mailgun_relay_impl": "rust"},
            "version_without_checksum": {"mailgun_relay_rust_version": "0.2.0"},
            "short_checksum": {"mailgun_relay_rust_version": "0.2.0", "mailgun_relay_rust_sha256": "a" * 63},
            "uppercase_checksum": {"mailgun_relay_rust_version": "0.2.0", "mailgun_relay_rust_sha256": "A" * 64},
            "checksum_without_version": {"mailgun_relay_rust_sha256": sha},
            "archive_without_version": {"mailgun_relay_rust_local_archive": "/tmp/a.tar.gz"},
            "version_with_a_path": {"mailgun_relay_rust_version": "../0.2.0", "mailgun_relay_rust_sha256": sha},
            "version_with_a_v": {"mailgun_relay_rust_version": "v0.2.0", "mailgun_relay_rust_sha256": sha},
            "version_as_number": {"mailgun_relay_rust_version": 0.2, "mailgun_relay_rust_sha256": sha},
            "root_install_root": {"mailgun_relay_rust_install_root": "/"},
            "relative_install_root": {"mailgun_relay_rust_install_root": "opt/mailgun-relay"},
            "install_root_in_the_site": {"mailgun_relay_rust_install_root": "/opt/apps/mailgun-relay/site/rust"},
            "install_root_is_the_site": {"mailgun_relay_rust_install_root": "/opt/apps/mailgun-relay/site"},
            "install_root_dotdot_is_root": {"mailgun_relay_rust_install_root": "/opt/.."},
            "install_root_dot_into_the_site": {"mailgun_relay_rust_install_root": "/opt/apps/mailgun-relay/./site/rust"},
            "install_root_dotdot_into_the_site": {"mailgun_relay_rust_install_root": "/opt/x/../apps/mailgun-relay/site/rust"},
            "install_root_double_slash": {"mailgun_relay_rust_install_root": "/opt//mailgun-relay"},
            "install_root_in_a_site_with_a_trailing_slash": {
                "mailgun_relay_rust_install_root": "/srv/site/rust",
                "mailgun_relay_site_path": "/srv/site/",
            },
            "keep_zero": {"mailgun_relay_rust_keep_versions": 0},
            "keep_boolean": {"mailgun_relay_rust_keep_versions": True},
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
            task_list("impl.yml"), "impl | Derive the Rust version the drop-in selected so far"
        )
        rendered = render(
            "impl.conf.j2", mailgun_relay_rust_binary="/opt/mailgun-relay/0.2.0/mailgun-relay"
        )

        def case(content: str | None) -> dict:
            variables: dict = {"mailgun_relay_rust_install_root": "/opt/mailgun-relay"}
            variables["mailgun_relay_dropin_before"] = (
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
                "foreign_path": case("[Service]\nExecStart=\nExecStart=/usr/bin/x\n"),
                "python_home": case(
                    "[Service]\nExecStart=\n"
                    "ExecStart=/opt/apps/mailgun-relay/0.1.0/mailgun-relay\n"
                ),
            },
            "mailgun_relay_rust_active_before",
        )

        self.assertEqual(
            outcomes,
            {"rust_dropin": "0.2.0", "no_dropin": "", "foreign_path": "", "python_home": ""},
        )

    def test_previous_version_is_recorded_only_when_the_selection_moves(self) -> None:
        condition = find_task(
            task_list("impl.yml"), "impl | Remember the previously selected Rust version"
        )["when"]
        probe = {
            "name": "probe",
            "ansible.builtin.debug": {"msg": "recorded"},
            "when": condition,
            "register": "probe",
        }

        def case(before: str, impl: str, version: str) -> dict:
            return {
                "mailgun_relay_rust_active_before": before,
                "mailgun_relay_rust_active_before_stat": {"stat": {"isdir": True}},
                "mailgun_relay_impl": impl,
                "mailgun_relay_rust_version": version,
            }

        outcomes = run_cases(
            probe,
            {
                "same_version_rewritten": case("0.2.0", "rust", "0.2.0"),
                "rust_to_rust": case("0.2.0", "rust", "0.2.1"),
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
        tasks = task_list("verify_impl.yml")
        read = find_task(tasks, "verify_impl | Read the live mailgun-relay process")
        expected = read["vars"]["mailgun_relay_expected_lines"]

        def lines(impl: str) -> list[str]:
            return yaml.safe_load(
                Environment()
                .from_string(expected)
                .render(
                    mailgun_relay_impl=impl,
                    mailgun_relay_rust_binary="/opt/mailgun-relay/0.2.0/mailgun-relay",
                    mailgun_relay_venv_bin="/opt/apps/mailgun-relay/site/.venv/bin",
                )
            )

        self.assertEqual(lines("rust"), ["exe=/opt/mailgun-relay/0.2.0/mailgun-relay"])
        self.assertEqual(
            lines("python"),
            ["arg=/opt/apps/mailgun-relay/site/.venv/bin/python", "arg=-m", "arg=mailgun_relay"],
        )
        self.assertIn('readlink "/proc/$pid/exe"', read["ansible.builtin.shell"])
        self.assertIn('done < "/proc/$pid/cmdline"', read["ansible.builtin.shell"])
        self.assertEqual(read["retries"], 10)

    def test_pruning_follows_the_live_check_and_skips_a_rejected_release(self) -> None:
        tasks = task_list("verify_impl.yml")
        verify = find_task(tasks, "verify_impl | Verify the running implementation")
        prune = find_task(tasks, "verify_impl | Prune old Rust releases")

        self.assertLess(tasks.index(verify), tasks.index(prune))
        self.assertIn("not mailgun_relay_rust_install_failed | bool", prune["when"])
        self.assertIn("mailgun_relay_rust_version | length > 0", prune["when"])

    def test_pruning_keeps_the_pinned_previous_live_and_newest_versions(self) -> None:
        task = find_task(
            task_list("verify_impl.yml"), "verify_impl | Decide which Rust releases to keep"
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
                "mailgun_relay_rust_version": pinned,
                "mailgun_relay_rust_keep_versions": keep,
                "mailgun_relay_rust_install_root": "/opt/mailgun-relay",
                "mailgun_relay_live": {
                    "stdout_lines": ["state=active", "pid=42", f"exe={live}", "arg=x"]
                },
                "mailgun_relay_rust_installed": {
                    "files": [
                        {"path": f"/opt/mailgun-relay/{name}", "mtime": mtime}
                        for name, mtime in installed
                    ]
                },
                "mailgun_relay_rust_previous": (
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
                    "0.1.0", "0.2.0", 1, live="/opt/mailgun-relay/0.3.0/mailgun-relay"
                ),
            },
            "mailgun_relay_rust_versions_installed | difference(mailgun_relay_rust_versions_kept) | sort",
        )

        self.assertEqual(outcomes["newest_three"], ["0.1.0", "0.2.0"])
        self.assertEqual(outcomes["old_pin_and_previous"], ["0.3.0", "0.4.0"])
        self.assertEqual(outcomes["live_binary"], ["0.4.0"])

    def test_existing_task_and_handler_names_stay(self) -> None:
        handlers = [h["name"] for h in yaml.safe_load((ROLE / "handlers" / "main.yml").read_text())]

        self.assertEqual(handlers, ["reload systemd", "restart mailgun-relay"])

    def test_readme_documents_the_switch_and_rollback(self) -> None:
        readme = (ROLE / "README.md").read_text()

        for name in role_defaults():
            if name.startswith(("mailgun_relay_impl", "mailgun_relay_rust_")):
                with self.subTest(variable=name):
                    self.assertIn(f"`{name}`", readme)
        for text in ("impl.conf", "MALLOC_MMAP_THRESHOLD_=131072", "--check-config", "### Rollback"):
            with self.subTest(text=text):
                self.assertIn(text, readme)


if __name__ == "__main__":
    unittest.main()
