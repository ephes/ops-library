import contextlib
import importlib.util
import io
import fcntl
import stat
from types import SimpleNamespace
import os
import pwd
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "operations_bridge",
    ROOT / "roles/daybook_operations_api_backup/files/echoport_runner.py",
)
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


class BackupBridgeTests(unittest.TestCase):
    def test_restore_and_cross_target_storage_are_refused_before_commands(self):
        policy = {"target": "operations", "bucket": "backups"}
        for values in (
            {"ECHOPORT_ACTION": "restore"},
            {"ECHOPORT_TARGET": "other"},
            {"ECHOPORT_BUCKET": "public"},
        ):
            with self.subTest(values=values), patch.object(bridge, "command") as call:
                with self.assertRaises(ValueError):
                    bridge.validate_context(
                        {
                            "context": {
                                "env": {
                                    "ECHOPORT_ACTION": "backup",
                                    "ECHOPORT_TARGET": "operations",
                                    "ECHOPORT_BUCKET": "backups",
                                    **values,
                                }
                            }
                        },
                        policy,
                    )
                call.assert_not_called()
        bridge.validate_context(
            {
                "context": {
                    "env": {
                        "ECHOPORT_ACTION": "backup",
                        "ECHOPORT_TARGET": "operations",
                        "ECHOPORT_BUCKET": "backups",
                        "ECHOPORT_KEY": "/etc/shadow",
                        "ECHOPORT_COMMAND": "sh",
                    }
                }
            },
            policy,
        )

    def test_missing_context_fields_never_start_a_backup(self):
        for config in (
            {},
            {"env": {"ECHOPORT_ACTION": "restore"}},
            {"context": {}},
            {"context": {"env": {"ECHOPORT_ACTION": "backup"}}},
        ):
            with (
                self.subTest(config=config),
                self.assertRaisesRegex(ValueError, "invalid_context"),
            ):
                bridge.validate_context(
                    config, {"target": "operations", "bucket": "backups"}
                )

    def test_root_policy_rejects_other_owner_and_writable_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy"
            path.write_text("{}")
            for uid, mode in ((501, 0o600), (0, 0o620), (0, 0o602)):
                info = SimpleNamespace(
                    st_mode=stat.S_IFREG | mode, st_uid=uid, st_size=2
                )
                with (
                    patch.object(bridge.os, "fstat", return_value=info),
                    self.assertRaisesRegex(ValueError, "invalid_configuration"),
                ):
                    bridge.read_json(path, root_owned=True)

    def test_held_bridge_lock_prevents_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "lock"
            policy = {
                "target": "operations",
                "bucket": "backups",
                "lock": str(lock_path),
            }
            context = {
                "context": {
                    "ECHOPORT_ACTION": "backup",
                    "ECHOPORT_TARGET": "operations",
                    "ECHOPORT_BUCKET": "backups",
                }
            }
            with lock_path.open("w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                output = io.StringIO()
                with (
                    patch.object(bridge.os, "geteuid", return_value=0),
                    patch.object(bridge.os, "umask"),
                    patch.object(bridge.signal, "signal"),
                    patch.object(bridge, "read_json", side_effect=[policy, context]),
                    patch.object(bridge, "backup") as call,
                    patch("sys.argv", ["bridge", "--config", "ignored"]),
                    contextlib.redirect_stdout(output),
                ):
                    self.assertEqual(bridge.main(), 1)
                call.assert_not_called()
                self.assertIn("backup_already_running", output.getvalue())

    def test_command_timeout_and_interrupt_reap_owned_children(self):
        for error in (
            bridge.subprocess.TimeoutExpired("backup", 240),
            ValueError("backup_interrupted"),
        ):
            with (
                self.subTest(error=type(error).__name__),
                patch.object(bridge.subprocess, "Popen") as popen,
                patch.object(bridge.os, "killpg") as kill,
            ):
                child = popen.return_value.__enter__.return_value
                child.pid = 123
                child.communicate.side_effect = [error, (b"", b"")]
                with self.assertRaises(ValueError):
                    bridge.command(["/fixed/backup"])
                self.assertEqual(
                    child.communicate.call_args_list[0].kwargs, {"timeout": 240}
                )
                kill.assert_called_once_with(123, bridge.signal.SIGKILL)
                self.assertEqual(child.communicate.call_count, 2)

    def test_configuration_symlinks_and_fifos_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").write_text("{}")
            (root / "link").symlink_to(root / "config")
            os.mkfifo(root / "fifo")
            for name in ("link", "fifo"):
                with self.subTest(name=name), self.assertRaises((OSError, ValueError)):
                    bridge.read_json(root / name)
            self.assertEqual(bridge.read_json(root / "config"), {})

    def test_roundtrip_verification_and_cleanup_with_service_account_boundary(self):
        account = pwd.getpwuid(os.geteuid())
        for corrupt, oversized in ((False, False), (True, False), (False, True)):
            with (
                self.subTest(corrupt=corrupt, oversized=oversized),
                tempfile.TemporaryDirectory() as tmp,
            ):
                root = Path(tmp)
                for name in ("backup", "stage"):
                    (root / name).mkdir()
                policy = {
                    "user": account.pw_name,
                    "backup_root": str(root / "backup"),
                    "staging_root": str(root / "stage"),
                    "python": "/protected/python",
                    "lifecycle": "/protected/lifecycle.py",
                    "config": "/protected/config.json",
                    "target": "operations",
                    "bucket": "backups",
                    "alias": "minio",
                    "mc": "/usr/local/bin/mc",
                }
                uploaded = {}
                calls = []

                def command(
                    args,
                    *,
                    account=None,
                    output=None,
                    timeout=bridge.COMMAND_TIMEOUT,
                    calls=calls,
                    policy=policy,
                    uploaded=uploaded,
                    corrupt=corrupt,
                ):
                    calls.append(args)
                    if args[0] == policy["python"]:
                        self.assertIsNotNone(account)
                        self.assertEqual(timeout, bridge.COMMAND_TIMEOUT)
                        source = Path(args[args.index("--archive") + 1])
                        if args[3] == "backup":
                            source.write_bytes(b"private-db-and-keyring")
                        else:
                            self.assertEqual(args[3], "validate")
                            self.assertEqual(
                                source.read_bytes(), b"private-db-and-keyring"
                            )
                    elif args[0] == "/usr/bin/head":
                        self.assertIsNotNone(account)
                        output.write(Path(args[-1]).read_bytes())
                    else:
                        self.assertIsNone(account)
                        self.assertEqual(args[:3], [policy["mc"], "cp", "--quiet"])
                        self.assertLessEqual(timeout, bridge.TRANSFER_TIMEOUT)
                        self.assertGreater(timeout, bridge.COMMAND_TIMEOUT)
                        src, dest = args[3:]
                        if Path(src).is_file():
                            self.assertTrue(
                                dest.startswith("minio/backups/operations/")
                            )
                            uploaded[dest] = Path(src).read_bytes()
                        else:
                            Path(dest).write_bytes(
                                b"changed" if corrupt else uploaded[src]
                            )

                with (
                    patch.object(bridge, "command", side_effect=command),
                    patch.object(bridge, "LIMIT", 5 if oversized else 1024),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    if oversized:
                        with self.assertRaisesRegex(ValueError, "archive_capacity"):
                            bridge.backup(policy)
                    elif corrupt:
                        with self.assertRaisesRegex(
                            ValueError, "upload_verification_failed"
                        ):
                            bridge.backup(policy)
                    else:
                        result = bridge.backup(policy)
                        self.assertTrue(result["success"])
                        self.assertEqual(
                            result["size_bytes"], len(b"private-db-and-keyring")
                        )
                self.assertEqual(len(uploaded), 0 if oversized else 1)
                self.assertEqual(len(calls), 3 if oversized else 5)
                self.assertEqual(list((root / "backup").iterdir()), [])
                self.assertEqual(list((root / "stage").iterdir()), [])

    def test_child_diagnostics_are_not_emitted_on_failure(self):
        output = io.StringIO()
        with (
            patch.object(bridge.os, "geteuid", return_value=0),
            patch.object(bridge.os, "umask"),
            patch.object(bridge.signal, "signal"),
            patch.object(
                bridge, "read_json", side_effect=RuntimeError("PRIVATE-CREDENTIAL")
            ),
            patch("sys.argv", ["bridge", "--config", "/unknown"]),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(bridge.main(), 1)
        self.assertNotIn("PRIVATE", output.getvalue())
        self.assertIn("backup_failed", output.getvalue())


class FakeClock:
    """time.monotonic/time.sleep for the transfer budget; commands may advance it."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class TransferRetryTests(unittest.TestCase):
    ARGS = ["/usr/local/bin/mc", "cp", "--quiet", "/stage/snapshot.tar", "a/b/k.tar"]

    def run_transfer(self, outcomes, *, budget=None, step="upload"):
        """Run transfer() against a scripted command; each outcome is
        (seconds the attempt takes, exception or None)."""
        clock = FakeClock()
        timeouts = []
        scripted = list(outcomes)

        def command(args, *, timeout):
            self.assertEqual(args, self.ARGS)
            timeouts.append(timeout)
            seconds, error = scripted.pop(0)
            clock.now += min(seconds, timeout)
            if error is not None:
                raise error
            return b""

        output = io.StringIO()
        deadline = clock.now + (bridge.TRANSFER_BUDGET if budget is None else budget)
        with (
            patch.object(bridge, "command", side_effect=command),
            patch.object(bridge.time, "monotonic", clock.monotonic),
            patch.object(bridge.time, "sleep", clock.sleep),
            contextlib.redirect_stdout(output),
        ):
            try:
                bridge.transfer(self.ARGS, deadline, step)
                error = None
            except ValueError as exc:
                error = str(exc)
        return error, timeouts, clock, output.getvalue()

    def test_a_stalled_upload_is_retried_and_succeeds(self):
        error, timeouts, clock, output = self.run_transfer(
            [(300, ValueError("backup_command_timeout")), (5, None)]
        )
        self.assertIsNone(error)
        self.assertEqual(timeouts, [bridge.TRANSFER_TIMEOUT, bridge.TRANSFER_TIMEOUT])
        self.assertEqual(clock.sleeps, [bridge.TRANSFER_RETRY_DELAY])
        self.assertIn('"name": "upload", "state": "running", "message": "attempt 2 of 3"', output)

    def test_the_per_attempt_limit_outlasts_two_unreachable_replica_dials(self):
        # 2026-11-05: one dial to the unreachable replica took about 135 s.
        self.assertGreater(bridge.TRANSFER_TIMEOUT, 2 * 135)
        self.assertGreater(bridge.TRANSFER_TIMEOUT, bridge.COMMAND_TIMEOUT)

    def test_failed_exits_are_retried_too(self):
        error, timeouts, _, _ = self.run_transfer(
            [(1, ValueError("backup_command_failed")), (1, None)], step="verify"
        )
        self.assertIsNone(error)
        self.assertEqual(len(timeouts), 2)

    def test_retries_are_bounded_and_report_the_last_category(self):
        for failure, category in (
            ("backup_command_timeout", "upload_timeout"),
            ("backup_command_failed", "upload_failed"),
        ):
            with self.subTest(failure=failure):
                error, timeouts, clock, _ = self.run_transfer(
                    [(10, ValueError(failure))] * bridge.TRANSFER_ATTEMPTS
                )
                self.assertEqual(error, category)
                self.assertEqual(len(timeouts), bridge.TRANSFER_ATTEMPTS)
                self.assertEqual(len(clock.sleeps), bridge.TRANSFER_ATTEMPTS - 1)

    def test_attempts_never_outlast_the_shared_budget(self):
        # Two full timeouts (2 x 300 s) and a delay leave 270 s: the third
        # attempt gets 270 s, not 300 s.
        error, timeouts, clock, _ = self.run_transfer(
            [(10_000, ValueError("backup_command_timeout"))] * 3
        )
        self.assertEqual(error, "upload_timeout")
        self.assertEqual(timeouts, [300, 300, 900 - 600 - 2 * 30])
        self.assertEqual(clock.sleeps, [30, 30])
        self.assertLessEqual(clock.now, 1000 + bridge.TRANSFER_BUDGET)

    def test_an_exhausted_budget_starts_no_attempt(self):
        error, timeouts, _, _ = self.run_transfer(
            [], budget=bridge.TRANSFER_MIN_ATTEMPT - 1, step="verify"
        )
        self.assertEqual(error, "transfer_budget_exhausted")
        self.assertEqual(timeouts, [])

    def test_a_too_short_remainder_ends_retries(self):
        # 150 s budget: the first attempt times out at 150 s and nothing is left.
        error, timeouts, clock, output = self.run_transfer(
            [(10_000, ValueError("backup_command_timeout"))], budget=150
        )
        self.assertEqual(error, "upload_timeout")
        self.assertEqual(timeouts, [150])
        self.assertEqual(clock.sleeps, [])
        self.assertNotIn("attempt 2", output)

    def test_no_retry_is_announced_when_too_little_budget_would_remain(self):
        # 70 s left after the first attempt: minus the 30 s delay that is
        # below the 60 s minimum, so no second attempt is announced or slept for.
        error, timeouts, clock, output = self.run_transfer(
            [(230, ValueError("backup_command_failed"))], budget=300
        )
        self.assertEqual(error, "upload_failed")
        self.assertEqual(timeouts, [300])
        self.assertEqual(clock.sleeps, [])
        self.assertNotIn("attempt 2", output)

    def test_interrupts_are_never_retried(self):
        error, timeouts, clock, _ = self.run_transfer(
            [(1, ValueError("backup_interrupted"))]
        )
        self.assertEqual(error, "backup_interrupted")
        self.assertEqual(len(timeouts), 1)
        self.assertEqual(clock.sleeps, [])

    def test_worst_case_run_stays_below_the_echoport_limit(self):
        # backup, validate and the source copy, then both transfers' budget.
        self.assertLess(3 * bridge.COMMAND_TIMEOUT + bridge.TRANSFER_BUDGET, 1800)

    def test_transfer_categories_are_public_results(self):
        for category in (
            "upload_timeout",
            "upload_failed",
            "verify_timeout",
            "verify_failed",
            "transfer_budget_exhausted",
        ):
            output = io.StringIO()
            with (
                self.subTest(category=category),
                patch.object(bridge.os, "geteuid", return_value=0),
                patch.object(bridge.os, "umask"),
                patch.object(bridge.signal, "signal"),
                patch.object(
                    bridge,
                    "read_json",
                    side_effect=[
                        {"target": "t", "bucket": "b", "lock": os.devnull},
                        {
                            "context": {
                                "ECHOPORT_ACTION": "backup",
                                "ECHOPORT_TARGET": "t",
                                "ECHOPORT_BUCKET": "b",
                            }
                        },
                    ],
                ),
                patch.object(bridge.fcntl, "flock"),
                patch.object(bridge, "backup", side_effect=ValueError(category)),
                patch("sys.argv", ["bridge", "--config", "ignored"]),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(bridge.main(), 1)
            self.assertIn(f'\\"error\\": \\"{category}\\"', output.getvalue())
