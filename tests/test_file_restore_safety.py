"""Static role wiring and real local filesystem preservation regressions."""

import contextlib
import gzip
import os
import re
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml
from jinja2.nativetypes import NativeEnvironment

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "roles/restore_preserve_internal/files/preserve.py"
ROLES = ("jellyfin", "navidrome", "metube", "minecraft_java", "snappymail", "wagtail")


def flatten(tasks):
    result = []
    for task in tasks:
        if not any(section in task for section in ("block", "rescue", "always")):
            result.append(task)
        for section in ("block", "rescue", "always"):
            result.extend(flatten(task.get(section, [])))
    return result


class WiringTests(unittest.TestCase):
    def test_all_six_use_one_shared_include_before_restore(self):
        for role in ROLES:
            filename = "restore_data.yml" if role == "minecraft_java" else "main.yml"
            text = (ROOT / f"roles/{role}_restore/tasks/{filename}").read_text()
            tasks = flatten(yaml.safe_load(text))
            preserve = next(
                i
                for i, t in enumerate(tasks)
                if "restore_preserve_internal/tasks/main.yml" in str(t)
            )
            replace = next(
                i
                for i, t in enumerate(tasks)
                if (
                    ("rsync" in str(t) and t.get("name", "").startswith("Restore"))
                    or t.get("name") == "Restore world directory"
                    or t.get("name") == "Drop Wagtail database"
                )
            )
            self.assertLess(preserve, replace, role)
            self.assertNotIn("rsync -a --delete", text)
            self.assertIn(
                "pre-restore", (ROOT / f"roles/{role}_restore/README.md").read_text()
            )

    def test_no_role_removes_preserved_copies(self):
        for role in ROLES + ("restore_preserve_internal",):
            dirname = role if role.endswith("_internal") else role + "_restore"
            for file in (ROOT / "roles" / dirname / "tasks").glob("*.yml"):
                for task in flatten(yaml.safe_load(file.read_text())):
                    destructive = (
                        task.get("ansible.builtin.file", {}).get("state") == "absent"
                    )
                    if destructive:
                        self.assertNotIn("preserv", str(task))
                        self.assertNotIn("pre-restore", str(task))
                        self.assertRegex(
                            str(task), r"staging|temp_dir|snappymail_restore_stage|_task_pgpass\.path"
                        )
        self.assertNotIn("rmtree", HELPER.read_text())
        self.assertNotIn("unlink", HELPER.read_text())

    def test_wagtail_validation_dump_transaction_recovery_order(self):
        text = (ROOT / "roles/wagtail_restore/tasks/main.yml").read_text()
        tasks = flatten(yaml.safe_load(text))
        names = [t.get("name", "") for t in tasks]
        self.assertLess(
            names.index("Validate compressed SQL dump before stopping services"),
            names.index("Stop Wagtail service before restore"),
        )
        self.assertLess(
            names.index("Take and verify live database safety dump"),
            names.index("Drop Wagtail database"),
        )
        restore = tasks[names.index("Restore PostgreSQL dump in one transaction")]
        self.assertIn("--single-transaction", str(restore))
        self.assertIn("ON_ERROR_STOP=1", str(restore))
        self.assertIn("Restore Wagtail safety dump in one transaction", names)
        self.assertNotIn("Restart Wagtail service after failed restore", names)

    def test_review_recovery_and_staging_regressions(self):
        wagtail = yaml.safe_load(
            (ROOT / "roles/wagtail_restore/tasks/main.yml").read_text()
        )
        scope = next(task for task in wagtail if "rescue" in task)
        recovery = next(
            task
            for task in scope["rescue"]
            if task.get("name") == "Recover verified Wagtail database"
        )
        self.assertIn(
            "not wagtail_restore_replacement_complete | bool", recovery["when"]
        )
        stop = next(
            task
            for task in scope["rescue"]
            if task.get("name")
            == "Leave Wagtail services stopped after restore failure"
        )
        self.assertIn("wagtail_restore_stop_service | bool", stop["when"])
        names = [task.get("name") for task in scope["block"]]
        self.assertLess(
            names.index("Restore PostgreSQL dump in one transaction"),
            names.index("Mark SQL replacement committed"),
        )
        self.assertLess(
            names.index("Mark SQL replacement committed"),
            names.index("Run migrations after restore"),
        )
        snappy = yaml.safe_load(
            (ROOT / "roles/snappymail_restore/tasks/main.yml").read_text()
        )
        block = next(task for task in snappy if "block" in task)
        stage = next(
            task for task in block["block"] if "ansible.builtin.tempfile" in task
        )
        self.assertEqual(
            stage["ansible.builtin.tempfile"]["path"],
            "{{ snappymail_data_dir | dirname }}",
        )
        self.assertEqual(block["always"][0]["ansible.builtin.file"]["state"], "absent")
        names = [task.get("name") for task in block["block"]]
        self.assertLess(
            names.index("Check SnappyMail preservation before stopping writers"),
            names.index("Stop SnappyMail writers before preservation"),
        )
        self.assertLess(
            names.index(
                "Require an identifiable SnappyMail PHP-FPM pool before stopping nginx"
            ),
            names.index("Stop SnappyMail writers before preservation"),
        )
        restart = next(
            task
            for task in block["rescue"]
            if task["name"]
            == "Restart SnappyMail units stopped before a preservation failure"
        )
        self.assertIn("RESTORE_PRESERVED", str(restart["when"]))
        stop_tasks = yaml.safe_load(
            (ROOT / "roles/minecraft_java_restore/tasks/stop_service.yml").read_text()
        )
        stop = next(
            task for task in stop_tasks if task["name"] == "Stop minecraft service"
        )
        self.assertEqual(
            stop["when"],
            "'LoadState=loaded' in minecraft_restore_service_load.stdout_lines",
        )
        self.assertNotIn("failed_when", stop)

    def test_minecraft_loaded_missing_masked_and_removed_running_units(self):
        tasks = yaml.safe_load(
            (ROOT / "roles/minecraft_java_restore/tasks/stop_service.yml").read_text()
        )
        query = next(
            task
            for task in tasks
            if task["name"] == "Query Minecraft service load state"
        )
        guard = next(task for task in tasks if "ansible.builtin.assert" in task)[
            "ansible.builtin.assert"
        ]["that"][0]
        stop = next(task for task in tasks if task["name"] == "Stop minecraft service")
        starts = yaml.safe_load(
            (ROOT / "roles/minecraft_java_restore/tasks/start_service.yml").read_text()
        )
        start = next(
            task for task in starts if task["name"] == "Start minecraft service"
        )
        wait = next(
            task for task in starts if task["name"] == "Wait for server to start"
        )
        self.assertEqual(start["when"], stop["when"])
        self.assertEqual(wait["when"], stop["when"])
        env = NativeEnvironment()
        cases = [
            (0, ["LoadState=loaded", "ActiveState=active"], True, True),
            (0, ["LoadState=not-found", "ActiveState=inactive"], True, False),
            (1, ["LoadState=not-found", "ActiveState=inactive"], True, False),
            (0, ["LoadState=not-found", "ActiveState=active"], False, False),
            (1, ["LoadState=not-found", "ActiveState=active"], False, False),
            (0, ["LoadState=masked", "ActiveState=inactive"], False, False),
            (1, [], False, False),
            (1, ["LoadState=loaded", "ActiveState=active"], False, False),
        ]
        for rc, lines, allowed, managed in cases:
            value = {"rc": rc, "stdout_lines": lines}

            def render(expression):
                return env.from_string("{{ " + expression + " }}").render(
                    minecraft_restore_service_load=value
                )

            accepted = not render(query["failed_when"]) and render(guard)
            self.assertEqual(accepted, allowed, (rc, lines))
            self.assertEqual(
                bool(accepted and render(stop["when"])), managed, (rc, lines)
            )

    def test_wagtail_failure_name_is_invocation_owned_and_always_reported(self):
        tasks = yaml.safe_load(
            (ROOT / "roles/wagtail_restore/tasks/main.yml").read_text()
        )
        reset = next(
            task
            for task in tasks
            if task["name"] == "Reset Wagtail recovery state for this invocation"
        )
        self.assertEqual(
            reset["ansible.builtin.set_fact"]["wagtail_restore_failed_task_name"],
            "none",
        )
        scope = next(task for task in tasks if "rescue" in task)
        self.assertIn(
            "wagtail_restore_failed_task_name",
            scope["rescue"][0]["ansible.builtin.set_fact"],
        )
        self.assertIn("wagtail_restore_failed_task_name", str(scope["always"]))
        self.assertNotIn("ansible_failed_task", str(scope["always"]))

    def test_snappymail_recovery_selects_only_units_this_run_stopped(self):
        tasks = yaml.safe_load(
            (ROOT / "roles/snappymail_restore/tasks/main.yml").read_text()
        )
        rescue = next(task["rescue"] for task in tasks if "rescue" in task)
        record = rescue[0]
        restart = rescue[1]
        self.assertIn("snappymail_restore_restart_services | bool", restart["when"])
        self.assertEqual(restart["loop"], "{{ snappymail_restore_stopped_units }}")
        env = NativeEnvironment()
        env.filters["bool"] = bool
        results = [
            {"item": "skipped", "skipped": True},
            {"item": "inactive", "changed": False, "failed": False},
            {"item": "failed", "changed": True, "failed": True},
            {"item": "stopped", "changed": True, "failed": False},
            {"item": "stopped-without-failed-key", "changed": True},
        ]
        for enabled in (False, True):
            selected = []
            for item in results:
                if all(
                    env.from_string("{{ " + condition + " }}").render(
                        item=item, snappymail_restore_restart_services=enabled
                    )
                    for condition in record["when"]
                ):
                    selected.append(item["item"])
            self.assertEqual(
                selected, ["stopped", "stopped-without-failed-key"] if enabled else []
            )

    def test_marked_report_ignores_remote_stderr_and_initializes_check_mode(self):
        tasks = yaml.safe_load(
            (ROOT / "roles/restore_preserve_internal/tasks/main.yml").read_text()
        )
        report = {"path": "/live.pre-restore-123", "size_bytes": 42, "method": "rename"}
        result = {
            "stdout_lines": [
                "cp: harmless warning",
                "RESTORE_PRESERVED " + json.dumps(report),
                "remote stderr after report",
            ]
        }
        env = NativeEnvironment()
        env.tests["match"] = lambda value, pattern: bool(re.match(pattern, value))
        env.filters["regex_replace"] = lambda value, pattern, replace: re.sub(
            pattern, replace, value
        )
        env.filters["from_json"] = json.loads
        expression = next(
            task["ansible.builtin.set_fact"]["restore_preserve_report"]
            for task in tasks
            if task["name"] == "Record retained pre-restore copy"
        )
        self.assertEqual(
            env.from_string(expression).render(restore_preserve_result=result), report
        )
        self.assertIsNone(
            tasks[0]["ansible.builtin.set_fact"]["restore_preserve_report"]["path"]
        )
        self.assertNotIn("when", tasks[0])


class WagtailShellTests(unittest.TestCase):
    def setUp(self):
        tasks = flatten(
            yaml.safe_load((ROOT / "roles/wagtail_restore/tasks/main.yml").read_text())
        )
        self.shells = {
            task["name"]: task["ansible.builtin.shell"]
            for task in tasks
            if "ansible.builtin.shell" in task
        }
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env = dict(
            os.environ,
            PATH=str(self.bin) + ":" + os.environ["PATH"],
            SAFETY_DIR=str(self.root),
        )

    def stub(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\n" + body)
        path.chmod(0o755)

    def run_shell(self, name):
        return subprocess.run(
            ["bash", "-c", self.shells[name]],
            env=self.env,
            capture_output=True,
            text=True,
        )

    def test_validation_rejects_truncated_or_incomplete_sql(self):
        dump = self.root / "incoming.sql.gz"
        self.env["DUMP"] = str(dump)
        dump.write_bytes(
            gzip.compress(b"SELECT 1;\n-- PostgreSQL database dump complete\n")
        )
        self.assertEqual(
            self.run_shell(
                "Validate compressed SQL dump before stopping services"
            ).returncode,
            0,
        )
        dump.write_bytes(dump.read_bytes()[:-5])
        self.assertNotEqual(
            self.run_shell(
                "Validate compressed SQL dump before stopping services"
            ).returncode,
            0,
        )
        dump.write_bytes(gzip.compress(b"SELECT 1;\n"))
        self.assertNotEqual(
            self.run_shell(
                "Validate compressed SQL dump before stopping services"
            ).returncode,
            0,
        )

    def test_psql_error_is_a_restore_failure(self):
        dump = self.root / "incoming.sql.gz"
        dump.write_bytes(gzip.compress(b"SELECT broken;\n"))
        self.env["DUMP"] = str(dump)
        self.stub(
            "psql",
            'printf "%s\n" "$@" > "$SAFETY_DIR/args"\ncat > "$SAFETY_DIR/sql"\nexit 13\n',
        )
        result = self.run_shell("Restore PostgreSQL dump in one transaction")
        self.assertEqual(result.returncode, 13)
        self.assertIn("--single-transaction", (self.root / "args").read_text())
        self.assertIn("ON_ERROR_STOP=1", (self.root / "args").read_text())
        self.assertIn("SELECT broken", (self.root / "sql").read_text())

    def test_database_space_failure_and_dump_collision_fail_before_dump(self):
        self.stub("psql", "echo 1024\n")
        self.stub(
            "df",
            'printf "Filesystem 1B-blocks Used Available Use%% Mounted\nroot 1024 1024 0 100%% /\n"\n',
        )
        self.stub("pg_dump", 'touch "$SAFETY_DIR/dump-executed"\n')
        result = self.run_shell("Take and verify live database safety dump")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "dump-executed").exists())
        self.stub(
            "df",
            'printf "Filesystem 1B-blocks Used Available Use%% Mounted\nroot 999999999 0 999999999 0%% /\n"\n',
        )
        collision = self.root / "database.pre-restore.dump"
        collision.write_text("existing site content")
        result = self.run_shell("Take and verify live database safety dump")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "dump-executed").exists())
        self.assertEqual(collision.read_text(), "existing site content")


class PreserveTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("restore_preserve", HELPER)
        self.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.helper)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.live = Path(self.temp.name).resolve() / "live"
        self.live.mkdir()
        (self.live / "data").write_text("current state")
        (self.live / "nested").mkdir()
        (self.live / "nested" / "data").write_text("nested state")
        (self.live / "link").symlink_to("data")
        self.mount_patch = patch.object(self.helper, "mounts", return_value=set())
        self.mount_patch.start()
        self.addCleanup(self.mount_patch.stop)

    def preserve(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.helper.preserve(str(self.live), **kwargs)

    def test_rename_retains_original_and_second_restore_retains_both(self):
        first = self.preserve()
        self.assertEqual(first["method"], "rename")
        self.assertGreater(first["size_bytes"], 0)
        self.assertEqual(list(self.live.iterdir()), [])
        (self.live / "data").write_text("second state")
        second = self.preserve()
        self.assertNotEqual(first["path"], second["path"])
        self.assertEqual((Path(first["path"]) / "data").read_text(), "current state")
        self.assertEqual((Path(second["path"]) / "data").read_text(), "second state")
        self.assertTrue((Path(first["path"]) / "link").is_symlink())

    def test_no_fallible_size_walk_after_rename_and_report_precedes_recreate(self):
        original_size = self.helper.size
        original_replace = self.helper.os.replace
        moved = False

        def move(*args):
            nonlocal moved
            original_replace(*args)
            moved = True

        def measure(*args, **kwargs):
            if moved:
                raise OSError("post-rename traversal would fail")
            return original_size(*args, **kwargs)

        output = io.StringIO()
        with (
            patch.object(self.helper.os, "replace", side_effect=move),
            patch.object(self.helper, "size", side_effect=measure),
            patch.object(Path, "mkdir", side_effect=OSError("recreate failed")),
            contextlib.redirect_stdout(output),
        ):
            with self.assertRaisesRegex(OSError, "recreate failed"):
                self.helper.preserve(str(self.live))
        report = json.loads(
            output.getvalue().strip().removeprefix("RESTORE_PRESERVED ")
        )
        self.assertEqual(report["method"], "rename")
        self.assertEqual((Path(report["path"]) / "data").read_text(), "current state")
        self.assertFalse(self.live.exists())

    def test_mount_copy_exists_and_verified_before_emptying(self):
        self.helper.mounts.return_value = {str(self.live)}
        run = subprocess.run
        observed = []

        def spy(argv, **kwargs):
            if argv[0] == "rsync" and "-a" in argv:
                copies = list(self.live.parent.glob("live.pre-restore-*"))
                self.assertEqual(len(copies), 1)
                self.assertEqual((copies[0] / "data").read_text(), "current state")
                self.assertIn("verified", observed)
                observed.append("empty")
            result = run(argv, **kwargs)
            if argv[0] == "rsync" and "-aHAXnc" in argv:
                observed.append("verified")
            return result

        with patch.object(self.helper.subprocess, "run", side_effect=spy):
            report = self.preserve()
        self.assertEqual(report["method"], "copy")
        self.assertEqual(observed, ["verified", "empty"])
        self.assertEqual(list(self.live.iterdir()), [])
        self.assertTrue(Path(report["path"]).exists())

    def test_insufficient_space_leaves_live_and_siblings_untouched(self):
        self.helper.mounts.return_value = {str(self.live)}
        with patch.object(
            self.helper.shutil,
            "disk_usage",
            return_value=shutil._ntuple_diskusage(1, 1, 0),
        ):
            with self.assertRaisesRegex(ValueError, "insufficient"):
                self.preserve()
        self.assertEqual((self.live / "data").read_text(), "current state")
        self.assertEqual(list(self.live.parent.iterdir()), [self.live])

    def test_failed_verification_keeps_live_and_incomplete_copy(self):
        self.helper.mounts.return_value = {str(self.live)}
        run = subprocess.run

        def fail_verify(argv, **kwargs):
            if argv[0] == "rsync":
                return subprocess.CompletedProcess(
                    argv, 0, stdout="changed data", stderr=""
                )
            return run(argv, **kwargs)

        with patch.object(self.helper.subprocess, "run", side_effect=fail_verify):
            with self.assertRaisesRegex(ValueError, "verification failed"):
                self.preserve()
        self.assertEqual((self.live / "data").read_text(), "current state")
        self.assertEqual(len(list(self.live.parent.glob("live.pre-restore-*"))), 1)

    def test_nested_mount_fails_before_changes(self):
        self.helper.mounts.return_value = {str(self.live / "nested")}
        with self.assertRaisesRegex(ValueError, "nested mounts"):
            self.preserve()
        self.assertEqual(list(self.live.parent.iterdir()), [self.live])

    def test_preflight_never_creates_copies_or_clears_data(self):
        self.helper.mounts.return_value = {str(self.live)}
        self.helper.preflight(str(self.live))
        self.assertEqual(list(self.live.parent.iterdir()), [self.live])
        self.assertEqual((self.live / "data").read_text(), "current state")
        with patch.object(
            self.helper.shutil,
            "disk_usage",
            return_value=shutil._ntuple_diskusage(1, 1, 0),
        ):
            with self.assertRaisesRegex(ValueError, "insufficient"):
                self.helper.preflight(str(self.live))
        self.assertEqual(list(self.live.parent.iterdir()), [self.live])

    def test_keep_live_copies_without_emptying(self):
        report = self.preserve(empty=False)
        self.assertEqual(report["method"], "copy")
        self.assertEqual((self.live / "data").read_text(), "current state")
        self.assertEqual((Path(report["path"]) / "data").read_text(), "current state")

    def test_cross_filesystem_uses_copy_without_attempting_rename(self):
        real_stat = Path.stat

        def different_device(path, *args, **kwargs):
            info = real_stat(path, *args, **kwargs)
            if path == self.live.parent:
                values = list(info)
                values[2] = info.st_dev + 1
                return type(info)(values)
            return info

        with (
            patch.object(Path, "stat", different_device),
            patch.object(
                self.helper.os,
                "replace",
                side_effect=AssertionError("rename attempted"),
            ),
        ):
            report = self.preserve()
        self.assertEqual(report["method"], "copy")
        self.assertEqual((Path(report["path"]) / "data").read_text(), "current state")

    def test_layout_refuses_overlap_symlink_and_preservation_paths(self):
        for staging in (self.live, self.live / "stage", self.live.parent):
            with self.assertRaisesRegex(ValueError, "disjoint"):
                self.helper.check_layout([str(self.live), str(staging)], [])
        alias = self.live.parent / "alias"
        alias.symlink_to(self.live, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.helper.check_layout([str(alias)], [])
        with self.assertRaisesRegex(ValueError, "pre-restore"):
            self.helper.check_layout(
                [str(self.live.parent / "live.pre-restore-old")], []
            )
        with self.assertRaisesRegex(ValueError, "disjoint"):
            self.helper.check_layout(
                [str(self.live)], [str(self.live / "archive.tar.gz")]
            )
        self.assertEqual((self.live / "data").read_text(), "current state")

    def test_findmnt_includes_bind_and_nested_mounts(self):
        self.mount_patch.stop()
        with patch.object(
            self.helper.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                [],
                0,
                json.dumps(
                    {
                        "filesystems": [
                            {"target": "/", "children": [{"target": str(self.live)}]}
                        ]
                    }
                ),
            ),
        ):
            self.assertIn(str(self.live), self.helper.mounts())


if __name__ == "__main__":
    unittest.main()
