"""Guard real mutation boundaries of the manager-only Rustup transaction."""

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "rustup_security", ROOT / "roles/rustup_security/files/rustup_security.py"
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
OFFICIAL_PINS = dict(module.PINNED)


class RustupSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.cargo = self.home / ".cargo"
        self.rustup = self.home / ".rustup"
        (self.cargo / "bin").mkdir(parents=True)
        self.rustup.mkdir()
        (self.rustup / "settings.toml").write_text(
            'default_toolchain = "preserve-me"\n'
        )
        self.manager = self.cargo / "bin/rustup"
        self.manager.write_bytes(b"old Rustup fixture")
        self.manager.chmod(0o755)
        os.link(self.manager, self.cargo / "bin/cargo")
        (self.cargo / "bin/rustc").symlink_to("rustup")
        self.old = module.digest(self.manager)
        self.candidate = self.home / "rustup-init"
        self.candidate.write_bytes(b"new fixture")
        self.fixed = module.digest(self.candidate)
        self.account = type(
            "Account", (), {"pw_name": "fixture", "pw_dir": str(self.home)}
        )()
        self.mocks = [
            patch.object(module.pwd, "getpwuid", return_value=self.account),
            patch.object(module.platform, "system", return_value="Linux"),
            patch.object(module.platform, "machine", return_value="aarch64"),
            patch.dict(module.PINNED, {"aarch64-unknown-linux-gnu": self.fixed}),
            patch.object(module, "active_tools", return_value=["python3"]),
        ]
        for mock in self.mocks:
            mock.start()
            self.addCleanup(mock.stop)

    def call(self, **kwargs):
        return module.patch(
            self.home,
            "fixture",
            self.old,
            self.cargo,
            self.rustup,
            "aarch64-unknown-linux-gnu",
            **kwargs,
        )

    def test_check_predicts_change_without_creating_receipts_or_touching_files(self):
        before = module.protected_state(self.cargo, self.rustup)
        self.assertEqual(self.call(check=True), (True, None))
        self.assertEqual(module.digest(self.manager), self.old)
        self.assertEqual(module.protected_state(self.cargo, self.rustup), before)
        self.assertFalse((self.cargo / ".managed-rustup-security").exists())

    def test_unknown_proxy_fails_before_updater_or_backup(self):
        (self.cargo / "bin/cargo").unlink()
        (self.cargo / "bin/cargo").write_bytes(b"independent custom cargo")
        with patch.object(module.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "Unknown/custom proxy"):
                self.call(candidate=str(self.candidate))
            run.assert_not_called()
        self.assertFalse((self.cargo / ".managed-rustup-security").exists())

    def test_wrong_candidate_and_busy_owner_fail_before_mutation(self):
        with self.assertRaisesRegex(ValueError, "official Rustup"):
            self.call(candidate=str(self.manager))
        with (
            patch.object(
                module,
                "active_tools",
                return_value=["/some/toolchain/bin/rustc"],
            ),
            self.assertRaisesRegex(ValueError, "Active Rust tools"),
        ):
            self.call(check=True)
        self.assertFalse((self.cargo / ".managed-rustup-security").exists())

    def test_wrong_bytes_with_correct_updater_basename_fail(self):
        self.candidate.write_bytes(b"untrusted updater")
        with patch.object(module.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "updater bytes"):
                self.call(candidate=str(self.candidate))
            run.assert_not_called()
        self.assertFalse((self.cargo / ".managed-rustup-security").exists())

    def test_success_sanitizes_dispatch_env_and_converges_idempotently(self):
        before = module.protected_state(self.cargo, self.rustup)

        def succeed(argv, **kwargs):
            self.assertEqual(argv, [str(self.candidate), "--self-replace"])
            env = kwargs["env"]
            self.assertNotIn("RUSTUP_FORCE_ARG0", env)
            self.assertNotIn("RUSTUP_TRACE_DIR", env)
            self.assertNotIn("RUST_RECURSION_COUNT", env)
            self.assertEqual(env["CARGO_HOME"], str(self.cargo))
            self.assertEqual(env["RUSTUP_HOME"], str(self.rustup))
            self.manager.unlink()
            self.manager.write_bytes(self.candidate.read_bytes())
            for name in module.PROXIES:
                path = self.manager.parent / name
                path.unlink(missing_ok=True)
                os.link(self.manager, path)
            return subprocess.CompletedProcess(argv, 0, b"", b"")

        with (
            patch.dict(
                os.environ,
                {
                    "RUSTUP_FORCE_ARG0": "cargo",
                    "RUSTUP_TRACE_DIR": "/unwanted",
                    "RUST_RECURSION_COUNT": "999",
                },
            ),
            patch.object(module.subprocess, "run", side_effect=succeed) as run,
        ):
            changed, receipt = self.call(candidate=str(self.candidate))
            self.assertTrue(changed)
            run.assert_called_once()
            self.assertEqual(self.call(), (False, None))
        self.assertEqual(self.manager.stat().st_mode & 0o777, 0o755)
        self.assertEqual(module.protected_state(self.cargo, self.rustup), before)
        self.assertEqual(
            json.loads((receipt / "result.json").read_text())["status"], "updated"
        )
        (self.manager.parent / "rustdoc").unlink()
        with self.assertRaisesRegex(ValueError, "incomplete proxies"):
            self.call(check=True)

    def test_corrupt_backup_or_concurrent_drift_never_rolls_back(self):
        original_copy = module.shutil.copy2
        for corrupt_backup in (True, False):
            with self.subTest(corrupt_backup=corrupt_backup):
                inode = self.manager.stat().st_ino

                def copy_then_drift(source, destination):
                    result = original_copy(source, destination)
                    if corrupt_backup:
                        destination.write_bytes(b"bad backup")
                    else:
                        self.manager.write_bytes(b"legitimate concurrent manager")
                    return result

                with (
                    patch.object(module.shutil, "copy2", side_effect=copy_then_drift),
                    patch.object(module.subprocess, "run") as run,
                    self.assertRaisesRegex(
                        ValueError, "backup differs|changed after preflight"
                    ),
                ):
                    self.call(candidate=str(self.candidate))
                run.assert_not_called()
                self.assertEqual(self.manager.stat().st_ino, inode)
                self.assertTrue((self.cargo / "bin/cargo").samefile(self.manager))
                self.assertEqual(os.readlink(self.cargo / "bin/rustc"), "rustup")
                expected = (
                    b"old Rustup fixture"
                    if corrupt_backup
                    else b"legitimate concurrent manager"
                )
                self.assertEqual(self.manager.read_bytes(), expected)

    def test_updater_failure_restores_original_hardlinks_and_symlinks(self):
        def fail(*args, **kwargs):
            self.manager.unlink()
            self.manager.write_bytes(b"partially replaced")
            (self.cargo / "bin/rustdoc").symlink_to("rustup")
            return subprocess.CompletedProcess(
                args, 1, b"", b"deliberate fixture failure"
            )

        with (
            patch.object(module.subprocess, "run", side_effect=fail),
            self.assertRaisesRegex(RuntimeError, "private receipt"),
        ):
            self.call(candidate=str(self.candidate))
        self.assertEqual(module.digest(self.manager), self.old)
        self.assertTrue((self.cargo / "bin/cargo").samefile(self.manager))
        self.assertEqual(os.readlink(self.cargo / "bin/rustc"), "rustup")
        self.assertFalse((self.cargo / "bin/rustdoc").exists())
        receipts = list((self.cargo / ".managed-rustup-security").glob("*/result.json"))
        result = json.loads(receipts[0].read_text())
        self.assertEqual(result["status"], "rolled_back")
        self.assertTrue(result["protected_unchanged"])
        self.assertEqual(receipts[0].stat().st_mode & 0o777, 0o600)

    def test_runtime_pins_and_role_only_use_vendor_replace_stage(self):
        defaults = yaml.safe_load(
            (ROOT / "roles/rustup_security/defaults/main.yml").read_text()
        )
        for triple, checksum in OFFICIAL_PINS.items():
            self.assertEqual(
                defaults["rustup_security_checksums"][triple], "sha256:" + checksum
            )
        tasks = (ROOT / "roles/rustup_security/tasks/main.yml").read_text()
        self.assertIn("validate_certs: true", tasks)
        self.assertIn("ca_path:", tasks)
        self.assertNotIn("component add", tasks)
        self.assertNotIn("rustup update", tasks)
        self.assertNotIn(
            "--version",
            (ROOT / "roles/rustup_security/files/rustup_security.py").read_text(),
        )


if __name__ == "__main__":
    unittest.main()
