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
                    calls=calls,
                    policy=policy,
                    uploaded=uploaded,
                    corrupt=corrupt,
                ):
                    calls.append(args)
                    if args[0] == policy["python"]:
                        self.assertIsNotNone(account)
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
