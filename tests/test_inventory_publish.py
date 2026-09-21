"""Cadence, durable retries, failure isolation and launchd contract."""

import contextlib
import io
import json
import plistlib
import socket
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from jinja2 import Environment

FILES = Path(__file__).resolve().parents[1] / "roles/software_estate/files"
sys.path.insert(0, str(FILES))
try:
    import publish
finally:
    sys.path.pop(0)


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        (self.root / "outbox").mkdir(mode=0o700)
        self.writer = self.root / "writer"
        self.writer.write_text("1.synthetic-credential-for-tests-only")
        self.writer.chmod(0o600)
        self.config = {
            "policy": {"host": "test", "applications": []},
            "hostnames": [socket.gethostname().split(".")[0].lower(), "test"],
            "directory": self.root,
            "endpoint": "https://receiver.example/v1/inventory",
            "credential_file": str(self.writer),
        }
        self.observation = {
            "host": "test",
            "collector": "test",
            "observed_at": 1700000000,
            "categories": {
                name: {"status": "ok", "items": []}
                for name in ("packages", "services", "containers")
            },
            "applications": [],
            "gaps": [],
        }
        self.now = 1700000000

    def tearDown(self):
        self.temp.cleanup()

    def tick(self, outcome=("stored", "created", 0), **kwargs):
        with (
            patch.object(publish.time, "time", return_value=self.now),
            patch.object(
                publish.collect, "collect", return_value=self.observation
            ) as scan,
            patch.object(publish.send, "post", return_value=outcome) as post,
        ):
            result = publish.tick(self.config, **kwargs)
            return result, scan.call_count, post.call_count

    def test_partial_evidence_policy_reaches_durable_report(self):
        self.config["policy"]["preserve_partial_applications"] = True
        self.observation["applications"] = [
            {"id": "working", "status": "ok", "items": {"installed_version": "1.2"}},
            {"id": "missing", "status": "error", "items": []},
        ]
        result, scans, posts = self.tick(("retry", "network_error", 3600))
        self.assertEqual((result["scan"], scans, posts), ("published", 1, 1))
        report = json.loads(next((self.root / "outbox").glob("*.ndjson")).read_text())
        category = report["categories"]["applications"]
        self.assertEqual(category["status"], "error")
        self.assertEqual(category["items"], [])
        self.assertEqual(category["partial_items"], self.observation["applications"])
        self.now += 3601
        self.assertEqual(self.tick()[1:], (0, 1))

    def test_legacy_receiver_rejection_preserves_partial_report_for_explicit_retry(
        self,
    ):
        self.config["policy"]["preserve_partial_applications"] = True
        self.observation["applications"] = [
            {"id": "broken", "status": "error", "items": []}
        ]
        result, _, _ = self.tick(("blocked", "http_400", 0))
        self.assertEqual(result["reports"][0]["status"], "blocked")
        path = next((self.root / "outbox").glob("*.ndjson"))
        original = path.read_bytes()
        self.assertEqual(
            json.loads(original)["categories"]["applications"]["partial_items"],
            self.observation["applications"],
        )
        self.now += 3600
        self.assertEqual(self.tick()[1:], (0, 0))
        self.assertEqual(path.read_bytes(), original)
        # After the receiver upgrade, explicitly retry the same immutable report.
        self.assertEqual(
            self.tick(send_only=True, retry_blocked=True, retry_now=True)[1:], (0, 1)
        )
        self.assertFalse(path.exists())

    def test_weekly_cadence_hourly_retry_and_restart(self):
        result, scans, posts = self.tick(("retry", "network_error", 3600))
        self.assertEqual((result["scan"], scans, posts), ("published", 1, 1))
        report = next((self.root / "outbox").glob("*.ndjson"))
        original = report.read_bytes()
        self.now += 1800
        result, scans, posts = self.tick()
        self.assertEqual((scans, posts), (0, 0))
        self.assertEqual(report.read_bytes(), original)
        self.now += 1801
        # A fresh invocation reads both persisted files; no in-memory schedule cache.
        result, scans, posts = self.tick()
        self.assertEqual((scans, posts), (0, 1))
        self.assertFalse(report.exists())
        self.now = 1700000000 + publish.WEEK - 1
        self.assertEqual(self.tick()[1], 0)
        self.now += 1
        self.assertEqual(self.tick()[1:], (1, 1))
        self.now += 10 * publish.WEEK
        self.assertEqual(self.tick()[1:], (1, 1))  # One catch-up, no backlog of scans.

    def test_manual_collection_updates_cadence_and_uses_same_lock(self):
        self.tick()
        self.now += 60
        self.assertEqual(self.tick(collect_now=True)[1], 1)
        with (
            publish.outbox.locked(self.root),
            patch.object(publish.collect, "collect") as scan,
        ):
            with self.assertRaisesRegex(ValueError, "busy"):
                publish.tick(self.config, collect_now=True)
            scan.assert_not_called()

    def test_scan_failure_still_sends_pending_and_retries_scan_next_tick(self):
        self.tick(("retry", "network_error", 3600))
        self.now += publish.WEEK
        with (
            patch.object(publish.collect, "collect", side_effect=ValueError("failed")),
            patch.object(publish.time, "time", return_value=self.now),
            patch.object(publish.send, "post", return_value=("stored", "created", 0)),
        ):
            result = publish.tick(self.config)
        self.assertEqual(result["scan"], "failed")
        self.assertEqual(result["reports"][0]["status"], "stored")
        self.now += 3600
        self.assertEqual(self.tick()[1], 1)

    def test_category_errors_are_published_and_finish_weekly_attempt(self):
        self.observation["categories"]["packages"] = {
            "status": "error",
            "items": [],
            "error": "unreadable",
        }
        self.assertEqual(self.tick()[0]["scan"], "published")
        self.now += 3600
        self.assertEqual(self.tick()[1], 0)

    def test_full_outbox_is_preserved_and_delivery_runs_without_scan(self):
        for _ in range(publish.outbox.MAX_REPORTS):
            publish.emit.write_report(
                publish.emit.envelope(self.observation), self.root / "outbox"
            )
        result, scans, posts = self.tick(("retry", "network_error", 3600))
        self.assertEqual((result["scan"], scans, posts), ("failed", 0, 32))
        self.assertEqual(len(list((self.root / "outbox").glob("*.ndjson"))), 32)

    def test_corrupt_state_backward_clock_and_wrong_host_fail_closed(self):
        self.tick()
        path = self.root / publish.STATE
        original = path.read_text()
        for payload in ["{}", "not json", original.replace('"test"', '"other"')]:
            path.write_text(payload)
            with self.assertRaises(ValueError):
                self.tick()
        path.write_text(original)
        self.now -= 301
        with self.assertRaises(ValueError):
            self.tick()

    def test_send_only_without_schedule_never_scans(self):
        self.assertEqual(self.tick(send_only=True)[1:], (0, 0))
        self.assertIsNone(
            json.loads((self.root / publish.STATE).read_text())["last_scan"]
        )

    def test_deadline_retains_published_report(self):
        with (
            patch.object(publish.collect, "collect", return_value=self.observation),
            patch.object(publish.send, "post", side_effect=publish.send.RunDeadline),
        ):
            result = publish.tick(self.config)
        self.assertIn("delivery_error", result)
        self.assertEqual(len(list((self.root / "outbox").glob("*.ndjson"))), 1)

    def test_configuration_rejects_other_host_symlinks_and_insecure_paths(self):
        path = self.root / "config.json"
        raw = {**self.config, "directory": str(self.root)}
        path.write_text(json.dumps(raw))
        path.chmod(0o600)
        self.assertEqual(publish.configuration(path)["directory"], self.root)
        raw["hostnames"] = ["a-different-host"]
        path.write_text(json.dumps(raw))
        with self.assertRaises(ValueError):
            publish.configuration(path)
        raw["hostnames"] = self.config["hostnames"]
        path.write_text(json.dumps(raw))
        path.chmod(0o644)
        with self.assertRaises(ValueError):
            publish.configuration(path)
        path.chmod(0o600)
        (self.root / publish.STATE).symlink_to(self.writer)
        with self.assertRaises(OSError):
            self.tick()

    def test_stopped_scan_unwinds_without_sending_or_committing_cadence(self):
        with (
            patch.object(publish.collect, "collect", side_effect=publish.Stopped),
            patch.object(publish.send, "send_reports") as sender,
        ):
            with self.assertRaises(publish.Stopped):
                publish.tick(self.config)
            sender.assert_not_called()
        with publish.outbox.locked(self.root):
            pass
        self.assertIsNone(
            json.loads((self.root / publish.STATE).read_text())["last_scan"]
        )

    def test_launchd_has_calendar_and_login_triggers_but_no_keepalive(self):
        template = (
            FILES.parent.parent
            / "software_estate_publisher/templates/publisher.plist.j2"
        )
        config = plistlib.loads(
            Environment()
            .from_string(template.read_text())
            .render(
                software_estate_publisher_label="test.publisher",
                software_estate_publisher_python="/path with spaces/python",
                software_estate_publisher_release="/private/release&one",
                software_estate_publisher_config="/private/config.json",
                software_estate_publisher_minute=17,
            )
            .encode()
        )
        self.assertEqual(config["StartCalendarInterval"], {"Minute": 17})
        self.assertTrue(config["RunAtLoad"])
        self.assertNotIn("KeepAlive", config)
        self.assertNotIn("StartInterval", config)
        self.assertEqual(
            config["ProgramArguments"][1], "/private/release&one/publish.py"
        )
        self.assertEqual(config["Umask"], 0o077)

    def test_main_modes_exit_status_and_single_json_result(self):
        args = ["--config", str(self.root / "unused.json")]
        cases = [
            ({"scan": "not_due", "reports": []}, 0),
            ({"scan": "failed", "reports": []}, 1),
            ({"scan": "not_due", "reports": [{"status": "waiting"}]}, 1),
            ({"scan": "not_due", "reports": [{}]}, 1),
        ]
        for result, status in cases:
            with (
                patch.object(publish, "configuration", return_value=self.config),
                patch.object(publish, "tick", return_value=result),
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                self.assertEqual(publish.main(args), status)
                json.loads(output.getvalue())
        for error, status, marker in [
            (publish.outbox.Busy("different message"), 75, "busy"),
            (publish.Stopped(), 143, "stopped"),
            (ValueError("bad config"), 1, "local_configuration_or_state_error"),
        ]:
            with (
                patch.object(publish, "configuration", return_value=self.config),
                patch.object(publish, "tick", side_effect=error),
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                self.assertEqual(publish.main(args), status)
                self.assertEqual(json.loads(output.getvalue()), {"error": marker})
        with (
            patch.object(publish, "configuration", return_value=self.config),
            patch.object(publish, "tick") as tick,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(publish.main([*args, "--check"]), 0)
            tick.assert_not_called()
            with publish.outbox.locked(self.root):
                self.assertEqual(publish.main([*args, "--check"]), 75)
        for flags in [["--retry-now"], ["--check", "--collect-now"]]:
            with (
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                publish.main([*args, *flags])

    def test_path_guard_remains_active_under_python_optimization(self):
        tasks = yaml.safe_load(
            (
                FILES.parent.parent / "software_estate_publisher/tasks/main.yml"
            ).read_text()
        )
        guard = next(t for t in tasks if t["name"].startswith("Check publisher paths"))
        code = guard["ansible.builtin.command"]["argv"][2]
        safe = self.root / "private"
        safe.mkdir(mode=0o700)
        unsafe = self.root / "symlink"
        unsafe.symlink_to(safe)
        for path, status in [(safe, 0), (unsafe, 1), (self.root.parent, 1)]:
            result = subprocess.run(
                [sys.executable, "-O", "-c", code, str(self.root), str(path)],
                capture_output=True,
            )
            self.assertEqual(result.returncode, status)

    @unittest.skipUnless(shutil.which("ansible-playbook"), "Ansible unavailable")
    def test_initial_writer_provision_preserves_existing_and_rejects_symlink(self):
        role = FILES.parent.parent / "software_estate_publisher"
        tasks = yaml.safe_load((role / "tasks/main.yml").read_text())
        guard = next(t for t in tasks if t["name"].startswith("Check publisher paths"))
        install = next(t for t in tasks if t["name"] == "Install publisher files")
        provision = [
            t
            for t in install["block"]
            if t["name"].startswith(
                ("Create the private writer", "Provision a missing host-bound writer")
            )
        ]
        marker = self.root / "target-python-used"
        target_python = self.root / "target-python"
        target_python.write_text(
            f"#!{sys.executable}\n"
            "import os,sys\nfrom pathlib import Path\n"
            f"Path({str(marker)!r}).touch()\n"
            f"os.execv({sys.executable!r}, [{sys.executable!r}, *sys.argv[1:]])\n"
        )
        target_python.chmod(0o700)
        variables = yaml.safe_load((role / "defaults/main.yml").read_text())
        variables.update(
            software_estate_publisher_home=str(self.root),
            software_estate_publisher_release=str(self.root / "release"),
            software_estate_publisher_credential_file=str(
                self.root / "credentials/writer"
            ),
            software_estate_publisher_writer="synthetic-initial-writer",
            ansible_facts={"python": {"executable": str(target_python)}},
            ansible_python_interpreter=sys.executable,
        )
        play = self.root / "provision.yml"
        writer = self.root / "credentials/writer"
        for supplied, succeeds in [
            ("  \n", True),
            ("synthetic-initial-writer", True),
            ("synthetic-replacement-writer", True),
            ("synthetic-symlink-writer", False),
        ]:
            if not succeeds:
                writer.unlink()
                writer.symlink_to(self.writer)
            marker.unlink(missing_ok=True)
            variables["software_estate_publisher_writer"] = supplied
            play.write_text(
                yaml.safe_dump(
                    [
                        {
                            "hosts": "localhost",
                            "connection": "local",
                            "gather_facts": False,
                            "vars": variables,
                            "tasks": [guard, *provision],
                        }
                    ]
                )
            )
            result = subprocess.run(
                ["ansible-playbook", "-i", "localhost,", str(play)],
                capture_output=True,
                text=True,
                timeout=45,
            )
            self.assertEqual(result.returncode == 0, succeeds, result.stdout)
            self.assertTrue(
                marker.exists(), "Guard did not invoke the target interpreter"
            )
            if supplied.strip():
                self.assertNotIn(supplied, result.stdout + result.stderr)
            else:
                self.assertFalse(
                    writer.exists(), "Whitespace must not create an unusable writer"
                )
                continue
            if succeeds:
                self.assertEqual(writer.read_text(), "synthetic-initial-writer\n")
                self.assertEqual(writer.stat().st_mode & 0o777, 0o600)
                self.assertEqual(writer.parent.stat().st_mode & 0o777, 0o700)
            else:
                self.assertIn("symlink", result.stdout)
                self.assertEqual(
                    self.writer.read_text(), "1.synthetic-credential-for-tests-only"
                )

    def test_python310_syntax(self):
        import ast

        ast.parse((FILES / "publish.py").read_text(), feature_version=(3, 10))


if __name__ == "__main__":
    unittest.main()
