# ruff: noqa: B023

import argparse
import grp
import hashlib
import importlib.util
import json
import os
import pwd
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


LOCK_HELPER_PATH = (
    ROOT / "roles/ssh_restricted_forwarding_account/files/hold_transaction_lock.py"
)
lock_helper = load_module("hold_transaction_lock", LOCK_HELPER_PATH)
FENCE_HELPER_PATH = (
    ROOT / "roles/ssh_restricted_forwarding_account/files/manage_fence.py"
)
fence_helper = load_module("manage_fence", FENCE_HELPER_PATH)
CANDIDATE_HELPER_PATH = (
    ROOT / "roles/ssh_restricted_forwarding_account/files/manage_sshd_candidate.py"
)
candidate_helper = load_module("manage_sshd_candidate", CANDIDATE_HELPER_PATH)
ACCOUNT_HOME_HELPER_PATH = (
    ROOT / "roles/ssh_restricted_forwarding_account/files/manage_account_home.py"
)
account_home_helper = load_module("manage_account_home", ACCOUNT_HOME_HELPER_PATH)
IDENTITY_HELPER_PATH = (
    ROOT / "roles/ssh_forwarding_identity/files/manage_forwarding_identity.py"
)
identity_helper = load_module("manage_forwarding_identity", IDENTITY_HELPER_PATH)


class SSHForwardingRoleTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_identity_generation_is_descriptor_relative_and_agent_independent(self):
        tasks = self.read("roles/ssh_forwarding_identity/tasks/main.yml")
        defaults = self.read("roles/ssh_forwarding_identity/defaults/main.yml")
        helper = self.read(
            "roles/ssh_forwarding_identity/files/manage_forwarding_identity.py"
        )
        self.assertIn("pinned no-follow directory descriptors", tasks)
        self.assertNotIn("ansible.builtin.file", tasks)
        self.assertNotIn("creates:", tasks)
        self.assertIn("dir_fd=", helper)
        self.assertIn('os.open("/", _inspection_flags()', helper)
        self.assertIn("O_NOFOLLOW", helper)
        self.assertIn("O_DIRECTORY", helper)
        self.assertIn("_exchange_at", helper)
        self.assertIn("_rename_exclusive_at", helper)
        self.assertIn("os.fsync(parent_fd)", helper)
        self.assertIn('"-P"', helper)
        self.assertIn('"-N"', helper)
        self.assertNotIn("ssh-add", helper)
        self.assertNotIn("keychain", helper.lower())
        self.assertIn("CHANGEME", defaults)

    def test_identity_rejects_symlink_above_home_and_at_parent_without_target_mutation(
        self,
    ):
        uid = os.getuid()
        gid = os.getgid()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real = root / "real"
            home = real / "home"
            target = root / "target"
            home.mkdir(parents=True)
            target.mkdir()
            marker = target / "marker"
            marker.write_text("untouched", encoding="utf-8")
            (root / "alias").symlink_to(real, target_is_directory=True)
            with self.assertRaisesRegex(
                identity_helper.IdentityError, "no-follow directory"
            ):
                identity_helper.open_parent(
                    str(root / "alias" / "home"),
                    str(root / "alias" / "home" / ".ssh" / "identity"),
                    uid=uid,
                    gid=gid,
                    create=True,
                )
            (home / ".ssh").symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(
                identity_helper.IdentityError, "no-follow directory"
            ):
                identity_helper.open_parent(
                    str(home),
                    str(home / ".ssh" / "identity"),
                    uid=uid,
                    gid=gid,
                    create=True,
                )
            self.assertEqual(marker.read_text(encoding="utf-8"), "untouched")
            self.assertEqual(list(target.iterdir()), [marker])

    def test_check_mode_derives_ephemeral_key_without_creating_missing_parent(self):
        user = pwd.getpwuid(os.getuid()).pw_name
        group = grp.getgrgid(os.getgid()).gr_name
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve() / "home"
            home.mkdir()
            args = argparse.Namespace(
                state="present",
                home=str(home),
                path=str(home / ".ssh" / "identity"),
                user=user,
                group=group,
                comment="check-test",
                keygen="/usr/bin/ssh-keygen",
                check=True,
            )
            result = identity_helper.manage(args)
            self.assertEqual(result["status"], "checked")
            self.assertTrue(str(result["public_key"]).startswith("ssh-ed25519 "))
            self.assertFalse((home / ".ssh").exists())

    def test_recoverable_creation_check_mode_preserves_complete_filesystem_snapshot(
        self,
    ):
        user = pwd.getpwuid(os.getuid())
        group = grp.getgrgid(os.getgid())

        def snapshot(root: Path):
            result = {}
            for path in sorted(root.rglob("*")):
                info = path.lstat()
                metadata = (
                    info.st_dev,
                    info.st_ino,
                    info.st_mode,
                    info.st_nlink,
                    info.st_uid,
                    info.st_gid,
                    info.st_size,
                    info.st_atime_ns,
                    info.st_mtime_ns,
                    info.st_ctime_ns,
                )
                result[str(path.relative_to(root))] = (
                    metadata,
                    path.read_bytes() if path.is_file() else None,
                )
            return result

        for boundary in ("staged", "published"):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp).resolve() / "home"
                parent = home / ".ssh"
                parent.mkdir(parents=True, mode=0o700)
                parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
                payload = identity_helper._generate(
                    "/usr/bin/ssh-keygen", "recoverable-check"
                )
                staging = f".identity.creation-{'d' * 32}.tmp"
                intent = {
                    "version": 1,
                    "staging_name": staging,
                    "size": len(payload),
                    "sha256": __import__("hashlib").sha256(payload).hexdigest(),
                    "identity": None,
                }
                try:
                    intent_binding = identity_helper._write_creation_intent(
                        parent_fd,
                        "identity",
                        intent,
                        user.pw_uid,
                        group.gr_gid,
                        create=True,
                    )
                    descriptor, inode = identity_helper._create_verified_temporary(
                        parent_fd,
                        staging,
                        payload,
                        0o600,
                        user.pw_uid,
                        group.gr_gid,
                        "private identity",
                    )
                    os.close(descriptor)
                    intent["identity"] = inode
                    identity_helper._write_creation_intent(
                        parent_fd,
                        "identity",
                        intent,
                        user.pw_uid,
                        group.gr_gid,
                        create=False,
                        expected=intent_binding,
                    )
                    if boundary == "published":
                        identity_helper._rename_exclusive_at(
                            parent_fd, staging, "identity"
                        )
                        os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
                args = argparse.Namespace(
                    state="present",
                    home=str(home),
                    path=str(parent / "identity"),
                    user=user.pw_name,
                    group=group.gr_name,
                    comment="recoverable-check",
                    keygen="/usr/bin/ssh-keygen",
                    check=True,
                )
                before = snapshot(home)
                result = identity_helper.manage(args)
                after = snapshot(home)
                self.assertEqual(after, before)
                self.assertEqual(result["status"], "checked")
                expected_public, _ = identity_helper._derive(
                    "/usr/bin/ssh-keygen", payload, "recoverable-check"
                )
                self.assertEqual(result["public_key"], expected_public)

    def test_unbound_creation_restart_keeps_exact_original_intent_authority(self):
        user = pwd.getpwuid(os.getuid())
        group = grp.getgrgid(os.getgid())
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve() / "home"
            parent = home / ".ssh"
            parent.mkdir(parents=True, mode=0o700)
            staging = f".identity.creation-{'7' * 32}.tmp"
            original_intent = {
                "version": 1,
                "staging_name": staging,
                "size": 1,
                "sha256": hashlib.sha256(b"lost").hexdigest(),
                "identity": None,
            }
            parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                original_binding = identity_helper._write_creation_intent(
                    parent_fd,
                    "identity",
                    original_intent,
                    user.pw_uid,
                    group.gr_gid,
                    create=True,
                )
            finally:
                os.close(parent_fd)
            payload = identity_helper._generate(
                "/usr/bin/ssh-keygen", "unbound-authority"
            )
            original_create = identity_helper._create_verified_temporary
            observed_exact_authority = False

            def inspect_before_allocation(*args, **kwargs):
                nonlocal observed_exact_authority
                if args[1] == staging:
                    observed_exact_authority = True
                    self.assertEqual(
                        (parent / ".identity.creation.json").read_bytes(),
                        original_binding.payload,
                    )
                    self.assertFalse((parent / "identity").exists())
                    self.assertFalse((parent / staging).exists())
                return original_create(*args, **kwargs)

            args = argparse.Namespace(
                state="present",
                home=str(home),
                path=str(parent / "identity"),
                user=user.pw_name,
                group=group.gr_name,
                comment="unbound-authority",
                keygen="/usr/bin/ssh-keygen",
                check=False,
            )
            with (
                mock.patch.object(identity_helper, "_generate", return_value=payload),
                mock.patch.object(
                    identity_helper,
                    "_create_verified_temporary",
                    side_effect=inspect_before_allocation,
                ),
            ):
                result = identity_helper.manage(args)
            self.assertTrue(observed_exact_authority)
            self.assertEqual(result["status"], "present")
            self.assertEqual((parent / "identity").read_bytes(), payload)
            self.assertFalse((parent / staging).exists())
            self.assertFalse((parent / ".identity.creation.json").exists())
            self.assertTrue(
                any(
                    path.read_bytes() == original_binding.payload
                    for path in parent.glob(".identity.intent-*.tmp.remove-*.tmp")
                )
            )

    def test_unbound_creation_races_after_planning_fail_closed_in_check_and_real(self):
        user = pwd.getpwuid(os.getuid())
        group = grp.getgrgid(os.getgid())
        payload = identity_helper._generate("/usr/bin/ssh-keygen", "plan-race")
        for check in (True, False):
            for raced_name in ("canonical", "staging"):
                with (
                    self.subTest(check=check, raced_name=raced_name),
                    tempfile.TemporaryDirectory() as temporary,
                ):
                    home = Path(temporary).resolve() / "home"
                    parent = home / ".ssh"
                    parent.mkdir(parents=True, mode=0o700)
                    staging = f".identity.creation-{'8' * 32}.tmp"
                    intent = {
                        "version": 1,
                        "staging_name": staging,
                        "size": 1,
                        "sha256": hashlib.sha256(b"lost").hexdigest(),
                        "identity": None,
                    }
                    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        identity_helper._write_creation_intent(
                            parent_fd,
                            "identity",
                            intent,
                            user.pw_uid,
                            group.gr_gid,
                            create=True,
                        )
                    finally:
                        os.close(parent_fd)
                    raced = parent / (
                        "identity" if raced_name == "canonical" else staging
                    )

                    def race_after_plan(*_args):
                        raced.write_bytes(b"operator creation")
                        raced.chmod(0o600)
                        return payload

                    args = argparse.Namespace(
                        state="present",
                        home=str(home),
                        path=str(parent / "identity"),
                        user=user.pw_name,
                        group=group.gr_name,
                        comment="plan-race",
                        keygen="/usr/bin/ssh-keygen",
                        check=check,
                    )
                    with (
                        mock.patch.object(
                            identity_helper, "_generate", side_effect=race_after_plan
                        ),
                        self.assertRaisesRegex(
                            identity_helper.IdentityError, "companion state changed"
                        ),
                    ):
                        identity_helper.manage(args)
                    self.assertEqual(raced.read_bytes(), b"operator creation")
                    self.assertTrue((parent / ".identity.creation.json").exists())

    def test_creation_intent_retirement_keeps_companion_bindings_open(self):
        user = pwd.getpwuid(os.getuid())
        group = grp.getgrgid(os.getgid())
        payload = identity_helper._generate("/usr/bin/ssh-keygen", "retire-race")
        for raced_name in ("canonical", "staging"):
            with (
                self.subTest(raced_name=raced_name),
                tempfile.TemporaryDirectory() as temporary,
            ):
                parent = Path(temporary)
                parent.chmod(0o700)
                parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
                original_cleanup = identity_helper._safe_unlink_identity
                displaced = parent / ".operator-displaced-canonical"
                raced = False

                def race_retirement(directory_fd, name, expected, **kwargs):
                    nonlocal raced
                    if name == ".identity.creation.json" and not raced:
                        raced = True
                        if raced_name == "canonical":
                            (parent / "identity").rename(displaced)
                            (parent / "identity").write_bytes(b"operator replacement")
                            (parent / "identity").chmod(0o600)
                        else:
                            current_intent = json.loads(
                                (parent / ".identity.creation.json").read_text(
                                    encoding="utf-8"
                                )
                            )
                            staging_name = current_intent["staging_name"]
                            # Publication retired the real staging name; recreation
                            # at that exact companion is not cleanup authority.
                            (parent / staging_name).write_bytes(b"operator staging")
                            (parent / staging_name).chmod(0o600)
                    return original_cleanup(directory_fd, name, expected, **kwargs)

                try:
                    with (
                        mock.patch.object(
                            identity_helper,
                            "_safe_unlink_identity",
                            side_effect=race_retirement,
                        ),
                        self.assertRaisesRegex(
                            identity_helper.IdentityError,
                            "companion state changed",
                        ),
                    ):
                        identity_helper._create_private_crash_safe(
                            parent_fd,
                            "identity",
                            payload,
                            "/usr/bin/ssh-keygen",
                            "retire-race",
                            user.pw_uid,
                            group.gr_gid,
                        )
                    self.assertTrue(raced)
                    if raced_name == "canonical":
                        self.assertEqual(
                            (parent / "identity").read_bytes(),
                            b"operator replacement",
                        )
                        self.assertEqual(displaced.read_bytes(), payload)
                    else:
                        staging_entries = list(parent.glob(".identity.creation-*.tmp"))
                        self.assertEqual(len(staging_entries), 1)
                        self.assertEqual(
                            staging_entries[0].read_bytes(), b"operator staging"
                        )
                finally:
                    os.close(parent_fd)

    def test_identity_parent_swap_after_open_cannot_redirect_key_install(self):
        user = pwd.getpwuid(os.getuid()).pw_name
        group = grp.getgrgid(os.getgid()).gr_name
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            home = root / "home"
            parent = home / ".ssh"
            target = root / "target"
            parent.mkdir(parents=True)
            target.mkdir()
            marker = target / "marker"
            marker.write_text("untouched", encoding="utf-8")
            private = identity_helper._generate("/usr/bin/ssh-keygen", "race-test")

            def swap_parent(*_args):
                parent.rename(home / ".ssh-pinned")
                parent.symlink_to(target, target_is_directory=True)
                return private

            args = argparse.Namespace(
                state="present",
                home=str(home),
                path=str(parent / "identity"),
                user=user,
                group=group,
                comment="race-test",
                keygen="/usr/bin/ssh-keygen",
                check=False,
            )
            with mock.patch.object(
                identity_helper, "_generate", side_effect=swap_parent
            ):
                result = identity_helper.manage(args)
            self.assertEqual(result["status"], "present")
            self.assertEqual(marker.read_text(encoding="utf-8"), "untouched")
            self.assertFalse((target / "identity").exists())
            self.assertTrue((home / ".ssh-pinned" / "identity").is_file())

    def test_private_identity_write_failures_never_publish_partial_canonical(self):
        user = pwd.getpwuid(os.getuid())
        group = grp.getgrgid(os.getgid())
        for case in ("zero", "enospc"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                parent = Path(temporary)
                parent.chmod(0o700)
                parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
                payload = identity_helper._generate(
                    "/usr/bin/ssh-keygen", "failure-test"
                )
                original_write = identity_helper.os.write
                calls = 0

                def fail_private_write(
                    descriptor, value, selected_case=case, write=original_write
                ):
                    nonlocal calls
                    raw = bytes(value)
                    if b"OPENSSH PRIVATE KEY" in raw or calls:
                        calls += 1
                        if selected_case == "zero":
                            return 0
                        if calls == 1:
                            return write(descriptor, value[:11])
                        raise OSError(28, "simulated ENOSPC")
                    return write(descriptor, value)

                try:
                    with (
                        mock.patch.object(
                            identity_helper.os,
                            "write",
                            side_effect=fail_private_write,
                        ),
                        self.assertRaises((identity_helper.IdentityError, OSError)),
                    ):
                        identity_helper._create_private_crash_safe(
                            parent_fd,
                            "identity",
                            payload,
                            "/usr/bin/ssh-keygen",
                            "failure-test",
                            user.pw_uid,
                            group.gr_gid,
                        )
                    self.assertFalse((parent / "identity").exists())
                    self.assertFalse((parent / ".identity.creation.json").exists())
                    quarantines = list(
                        parent.glob(".identity.creation-*.tmp.remove-*.tmp")
                    )
                    self.assertEqual(len(quarantines), 1)
                    self.assertTrue(quarantines[0].is_file())
                    created = identity_helper._create_private_crash_safe(
                        parent_fd,
                        "identity",
                        payload,
                        "/usr/bin/ssh-keygen",
                        "failure-test",
                        user.pw_uid,
                        group.gr_gid,
                    )
                    self.assertEqual(created, payload)
                finally:
                    os.close(parent_fd)

    def test_private_identity_write_all_retries_partial_and_eintr(self):
        user = pwd.getpwuid(os.getuid())
        group = grp.getgrgid(os.getgid())
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            parent.chmod(0o700)
            parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
            payload = identity_helper._generate("/usr/bin/ssh-keygen", "retry-test")
            original_write = identity_helper.os.write
            interrupted = False
            partials = 0

            def retrying_write(descriptor, value):
                nonlocal interrupted, partials
                raw = bytes(value)
                if b"OPENSSH PRIVATE KEY" in raw or partials:
                    if not interrupted:
                        interrupted = True
                        raise InterruptedError()
                    partials += 1
                    return original_write(descriptor, value[:13])
                return original_write(descriptor, value)

            try:
                with mock.patch.object(
                    identity_helper.os, "write", side_effect=retrying_write
                ):
                    created = identity_helper._create_private_crash_safe(
                        parent_fd,
                        "identity",
                        payload,
                        "/usr/bin/ssh-keygen",
                        "retry-test",
                        user.pw_uid,
                        group.gr_gid,
                    )
                self.assertTrue(interrupted)
                self.assertGreater(partials, 1)
                self.assertEqual(created, payload)
            finally:
                os.close(parent_fd)

    def test_bound_private_temporary_resumes_after_restart_without_rotation(self):
        user = pwd.getpwuid(os.getuid())
        group = grp.getgrgid(os.getgid())
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            parent.chmod(0o700)
            parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
            payload = identity_helper._generate("/usr/bin/ssh-keygen", "restart-test")
            staging = f".identity.creation-{'a' * 32}.tmp"
            intent = {
                "version": 1,
                "staging_name": staging,
                "size": len(payload),
                "sha256": __import__("hashlib").sha256(payload).hexdigest(),
                "identity": None,
            }
            try:
                intent_binding = identity_helper._write_creation_intent(
                    parent_fd,
                    "identity",
                    intent,
                    user.pw_uid,
                    group.gr_gid,
                    create=True,
                )
                descriptor, inode = identity_helper._create_verified_temporary(
                    parent_fd,
                    staging,
                    payload,
                    0o600,
                    user.pw_uid,
                    group.gr_gid,
                    "private identity",
                )
                os.close(descriptor)
                intent["identity"] = inode
                identity_helper._write_creation_intent(
                    parent_fd,
                    "identity",
                    intent,
                    user.pw_uid,
                    group.gr_gid,
                    create=False,
                    expected=intent_binding,
                )
                resumed = identity_helper._reconcile_creation(
                    parent_fd,
                    "identity",
                    "/usr/bin/ssh-keygen",
                    "restart-test",
                    user.pw_uid,
                )
                self.assertEqual(resumed, payload)
                self.assertEqual((parent / "identity").read_bytes(), payload)
                self.assertFalse((parent / staging).exists())
                self.assertFalse((parent / ".identity.creation.json").exists())
            finally:
                os.close(parent_fd)

    def test_unbound_private_temporary_is_preserved_fail_closed_on_restart(self):
        user = pwd.getpwuid(os.getuid())
        group = grp.getgrgid(os.getgid())
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            parent.chmod(0o700)
            parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
            staging = f".identity.creation-{'c' * 32}.tmp"
            intent = {
                "version": 1,
                "staging_name": staging,
                "size": 1,
                "sha256": __import__("hashlib").sha256(b"x").hexdigest(),
                "identity": None,
            }
            try:
                identity_helper._write_creation_intent(
                    parent_fd,
                    "identity",
                    intent,
                    user.pw_uid,
                    group.gr_gid,
                    create=True,
                )
                (parent / staging).write_bytes(b"")
                (parent / staging).chmod(0o600)
                with self.assertRaisesRegex(
                    identity_helper.IdentityError, "ambiguous unbound"
                ):
                    identity_helper._reconcile_creation(
                        parent_fd,
                        "identity",
                        "/usr/bin/ssh-keygen",
                        "unbound-test",
                        user.pw_uid,
                    )
                self.assertTrue((parent / staging).exists())
                self.assertTrue((parent / ".identity.creation.json").exists())
                self.assertFalse((parent / "identity").exists())
            finally:
                os.close(parent_fd)

    def test_unbound_creation_intent_rejects_every_adjacent_key_snapshot_invariant(
        self,
    ):
        user = pwd.getpwuid(os.getuid())
        group = grp.getgrgid(os.getgid())
        payload_a = identity_helper._generate("/usr/bin/ssh-keygen", "unbound-a")
        payload_b = identity_helper._generate("/usr/bin/ssh-keygen", "unbound-b")
        cases = {
            "canonical-same-content": (payload_a, None),
            "canonical-different-content": (payload_b, None),
            "staging-same-content": (None, payload_a),
            "staging-different-content": (None, payload_b),
            "both-same-content": (payload_a, payload_a),
            "both-different-content": (payload_a, payload_b),
        }

        def snapshot(root: Path):
            result = {}
            for path in sorted(root.rglob("*")):
                payload = path.read_bytes() if path.is_file() else None
                info = path.lstat()
                result[str(path.relative_to(root))] = (
                    info.st_dev,
                    info.st_ino,
                    info.st_mode,
                    info.st_nlink,
                    info.st_uid,
                    info.st_gid,
                    info.st_size,
                    info.st_atime_ns,
                    info.st_mtime_ns,
                    info.st_ctime_ns,
                    payload,
                )
            return result

        for check in (True, False):
            for case, (canonical_payload, staging_payload) in cases.items():
                with (
                    self.subTest(check=check, case=case),
                    tempfile.TemporaryDirectory() as temporary,
                ):
                    home = Path(temporary).resolve() / "home"
                    parent = home / ".ssh"
                    parent.mkdir(parents=True, mode=0o700)
                    staging = f".identity.creation-{'e' * 32}.tmp"
                    intent = {
                        "version": 1,
                        "staging_name": staging,
                        "size": len(payload_a),
                        "sha256": hashlib.sha256(payload_a).hexdigest(),
                        "identity": None,
                    }
                    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        identity_helper._write_creation_intent(
                            parent_fd,
                            "identity",
                            intent,
                            user.pw_uid,
                            group.gr_gid,
                            create=True,
                        )
                    finally:
                        os.close(parent_fd)
                    if canonical_payload is not None:
                        (parent / "identity").write_bytes(canonical_payload)
                        (parent / "identity").chmod(0o600)
                    if staging_payload is not None:
                        (parent / staging).write_bytes(staging_payload)
                        (parent / staging).chmod(0o600)
                    args = argparse.Namespace(
                        state="present",
                        home=str(home),
                        path=str(parent / "identity"),
                        user=user.pw_name,
                        group=group.gr_name,
                        comment="unbound-snapshot",
                        keygen="/usr/bin/ssh-keygen",
                        check=check,
                    )
                    before = snapshot(home)
                    with (
                        mock.patch.object(identity_helper, "_derive") as derive,
                        mock.patch.object(identity_helper, "_generate") as generate,
                        self.assertRaisesRegex(
                            identity_helper.IdentityError, "ambiguous unbound"
                        ),
                    ):
                        identity_helper.manage(args)
                    self.assertEqual(snapshot(home), before)
                    derive.assert_not_called()
                    generate.assert_not_called()
                    self.assertFalse((parent / "identity.pub").exists())

    def test_restart_never_accepts_partial_replacement_canonical_key(self):
        user = pwd.getpwuid(os.getuid())
        group = grp.getgrgid(os.getgid())
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            parent.chmod(0o700)
            parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
            payload = identity_helper._generate("/usr/bin/ssh-keygen", "replace-test")
            staging = f".identity.creation-{'b' * 32}.tmp"
            intent = {
                "version": 1,
                "staging_name": staging,
                "size": len(payload),
                "sha256": __import__("hashlib").sha256(payload).hexdigest(),
                "identity": None,
            }
            try:
                intent_binding = identity_helper._write_creation_intent(
                    parent_fd,
                    "identity",
                    intent,
                    user.pw_uid,
                    group.gr_gid,
                    create=True,
                )
                descriptor, inode = identity_helper._create_verified_temporary(
                    parent_fd,
                    staging,
                    payload,
                    0o600,
                    user.pw_uid,
                    group.gr_gid,
                    "private identity",
                )
                os.close(descriptor)
                intent["identity"] = inode
                identity_helper._write_creation_intent(
                    parent_fd,
                    "identity",
                    intent,
                    user.pw_uid,
                    group.gr_gid,
                    create=False,
                    expected=intent_binding,
                )
                (parent / "identity").write_bytes(b"partial replacement")
                (parent / "identity").chmod(0o600)
                with self.assertRaisesRegex(
                    identity_helper.IdentityError,
                    "canonical forwarding identity was replaced",
                ):
                    identity_helper._reconcile_creation(
                        parent_fd,
                        "identity",
                        "/usr/bin/ssh-keygen",
                        "replace-test",
                        user.pw_uid,
                    )
                self.assertEqual(
                    (parent / "identity").read_bytes(), b"partial replacement"
                )
                self.assertTrue((parent / staging).exists())
                self.assertTrue((parent / ".identity.creation.json").exists())
            finally:
                os.close(parent_fd)

    def test_public_key_and_creation_intent_updates_reject_substitution_races(self):
        uid = os.getuid()
        gid = os.getgid()
        for target_kind in ("public-key", "creation-intent"):
            for race in ("temporary", "canonical"):
                with (
                    self.subTest(target=target_kind, race=race),
                    tempfile.TemporaryDirectory() as temporary,
                ):
                    parent = Path(temporary)
                    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        if target_kind == "public-key":
                            canonical_name = "identity.pub"
                            canonical = parent / canonical_name
                            canonical.write_bytes(b"old public key\n")
                            canonical.chmod(0o644)
                            expected = identity_helper._read_regular(
                                parent_fd, canonical_name, uid, 0o644
                            )

                            def update():
                                identity_helper._replace(
                                    parent_fd,
                                    canonical_name,
                                    b"new public key\n",
                                    0o644,
                                    uid,
                                    gid,
                                    expected,
                                )

                            replacement_mode = 0o644
                        else:
                            canonical_name = ".identity.creation.json"
                            old_intent = {
                                "version": 1,
                                "staging_name": f".identity.creation-{'a' * 32}.tmp",
                                "size": 1,
                                "sha256": "0" * 64,
                                "identity": None,
                            }
                            new_intent = {**old_intent, "sha256": "1" * 64}
                            intent_binding = identity_helper._write_creation_intent(
                                parent_fd,
                                "identity",
                                old_intent,
                                uid,
                                gid,
                                create=True,
                            )
                            canonical = parent / canonical_name

                            def update():
                                identity_helper._write_creation_intent(
                                    parent_fd,
                                    "identity",
                                    new_intent,
                                    uid,
                                    gid,
                                    create=False,
                                    expected=intent_binding,
                                )

                            replacement_mode = 0o600
                        old_payload = canonical.read_bytes()
                        displaced = parent / f".{target_kind}-{race}-displaced"
                        raced = False
                        if race == "temporary":
                            original_publish = (
                                identity_helper._publish_verified_temporary
                            )

                            def substitute_temporary(
                                directory_fd,
                                name,
                                temporary_name,
                                descriptor,
                                identity,
                                payload,
                                expected_binding,
                                label,
                            ):
                                nonlocal raced
                                raced = True
                                (parent / temporary_name).rename(displaced)
                                (parent / temporary_name).write_bytes(payload)
                                (parent / temporary_name).chmod(replacement_mode)
                                return original_publish(
                                    directory_fd,
                                    name,
                                    temporary_name,
                                    descriptor,
                                    identity,
                                    payload,
                                    expected_binding,
                                    label,
                                )

                            patcher = mock.patch.object(
                                identity_helper,
                                "_publish_verified_temporary",
                                side_effect=substitute_temporary,
                            )
                        else:
                            original_exchange = identity_helper._exchange_at

                            def substitute_canonical(directory_fd, first, second):
                                nonlocal raced
                                if not raced:
                                    raced = True
                                    canonical.rename(displaced)
                                    canonical.write_bytes(b"attacker replacement\n")
                                    canonical.chmod(replacement_mode)
                                return original_exchange(directory_fd, first, second)

                            patcher = mock.patch.object(
                                identity_helper,
                                "_exchange_at",
                                side_effect=substitute_canonical,
                            )
                        with patcher, self.assertRaises(identity_helper.IdentityError):
                            update()
                        self.assertTrue(raced)
                        self.assertTrue(displaced.exists())
                        if race == "temporary":
                            self.assertEqual(canonical.read_bytes(), old_payload)
                        else:
                            self.assertEqual(
                                canonical.read_bytes(), b"attacker replacement\n"
                            )
                            self.assertEqual(displaced.read_bytes(), old_payload)
                    finally:
                        os.close(parent_fd)

    def test_public_and_intent_publication_reattest_after_old_name_retirement(self):
        uid = os.getuid()
        gid = os.getgid()
        for target_kind in ("public-key", "creation-intent"):
            with self.subTest(target=target_kind), tempfile.TemporaryDirectory() as tmp:
                parent = Path(tmp)
                parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    if target_kind == "public-key":
                        name = "identity.pub"
                        canonical = parent / name
                        canonical.write_bytes(b"old public key\n")
                        canonical.chmod(0o644)
                        expected = identity_helper._read_regular(
                            parent_fd, name, uid, 0o644
                        )

                        def update():
                            identity_helper._replace(
                                parent_fd,
                                name,
                                b"new public key\n",
                                0o644,
                                uid,
                                gid,
                                expected,
                            )

                        replacement_mode = 0o644
                    else:
                        name = ".identity.creation.json"
                        old = {
                            "version": 1,
                            "staging_name": f".identity.creation-{'a' * 32}.tmp",
                            "size": 1,
                            "sha256": "0" * 64,
                            "identity": None,
                        }
                        expected = identity_helper._write_creation_intent(
                            parent_fd,
                            "identity",
                            old,
                            uid,
                            gid,
                            create=True,
                        )
                        new = {**old, "sha256": "1" * 64}
                        canonical = parent / name

                        def update():
                            identity_helper._write_creation_intent(
                                parent_fd,
                                "identity",
                                new,
                                uid,
                                gid,
                                create=False,
                                expected=expected,
                            )

                        replacement_mode = 0o600
                    displaced = parent / f".{target_kind}.published-displaced"
                    original_cleanup = identity_helper._safe_unlink_identity
                    raced = False

                    def substitute_after_retirement(*args, **kwargs):
                        nonlocal raced
                        result = original_cleanup(*args, **kwargs)
                        if not raced:
                            raced = True
                            canonical.rename(displaced)
                            canonical.write_bytes(b"attacker canonical substitution\n")
                            canonical.chmod(replacement_mode)
                        return result

                    with (
                        mock.patch.object(
                            identity_helper,
                            "_safe_unlink_identity",
                            side_effect=substitute_after_retirement,
                        ),
                        self.assertRaisesRegex(
                            identity_helper.IdentityError,
                            "retired-name cleanup",
                        ),
                    ):
                        update()
                    self.assertTrue(raced)
                    self.assertTrue(displaced.exists())
                    self.assertEqual(
                        canonical.read_bytes(), b"attacker canonical substitution\n"
                    )
                finally:
                    os.close(parent_fd)

    def test_creation_intent_transitions_reject_valid_substitution_at_open(self):
        uid = os.getuid()
        gid = os.getgid()
        for transition in ("update", "clear"):
            with (
                self.subTest(transition=transition),
                tempfile.TemporaryDirectory() as tmp,
            ):
                parent = Path(tmp)
                parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    original = {
                        "version": 1,
                        "staging_name": f".identity.creation-{'a' * 32}.tmp",
                        "size": 1,
                        "sha256": "0" * 64,
                        "identity": None,
                    }
                    binding = identity_helper._write_creation_intent(
                        parent_fd,
                        "identity",
                        original,
                        uid,
                        gid,
                        create=True,
                    )
                    canonical = parent / ".identity.creation.json"
                    displaced = parent / f".intent-{transition}-original"
                    substitute = {**original, "sha256": "f" * 64}
                    substitute_payload = (
                        json.dumps(substitute, sort_keys=True) + "\n"
                    ).encode()
                    original_open = identity_helper.os.open
                    raced = False

                    def substitute_before_open(path, flags, *args, **kwargs):
                        nonlocal raced
                        if path == canonical.name and not raced:
                            raced = True
                            canonical.rename(displaced)
                            canonical.write_bytes(substitute_payload)
                            canonical.chmod(0o600)
                        return original_open(path, flags, *args, **kwargs)

                    with (
                        mock.patch.object(
                            identity_helper.os,
                            "open",
                            side_effect=substitute_before_open,
                        ),
                        self.assertRaises(identity_helper.IdentityError),
                    ):
                        if transition == "update":
                            identity_helper._write_creation_intent(
                                parent_fd,
                                "identity",
                                {**original, "sha256": "1" * 64},
                                uid,
                                gid,
                                create=False,
                                expected=binding,
                            )
                        else:
                            identity_helper._clear_creation_intent(
                                parent_fd, "identity", uid, binding
                            )
                    self.assertTrue(raced)
                    self.assertEqual(canonical.read_bytes(), substitute_payload)
                    self.assertEqual(displaced.read_bytes(), binding.payload)
                finally:
                    os.close(parent_fd)

    def test_identity_inspection_special_entries_never_block_for_canonical_names(self):
        user = pwd.getpwuid(os.getuid()).pw_name
        group = grp.getgrgid(os.getgid()).gr_name
        for inspected_name in ("identity", "identity.pub", ".identity.creation.json"):
            for kind in ("fifo", "socket", "directory"):
                with (
                    self.subTest(name=inspected_name, kind=kind),
                    tempfile.TemporaryDirectory() as temporary,
                ):
                    home = Path(temporary).resolve() / "home"
                    parent = home / ".ssh"
                    parent.mkdir(parents=True, mode=0o700)
                    identity = parent / "identity"
                    if inspected_name != "identity":
                        identity.write_bytes(
                            identity_helper._generate(
                                "/usr/bin/ssh-keygen", "special-entry-test"
                            )
                        )
                        identity.chmod(0o600)
                    special = parent / inspected_name
                    listener = None
                    if kind == "fifo":
                        os.mkfifo(special, 0o600)
                    elif kind == "socket":
                        listener = socket.socket(socket.AF_UNIX)
                        listener.bind(str(special))
                    else:
                        special.mkdir(mode=0o700)
                    try:
                        started = time.monotonic()
                        completed = subprocess.run(
                            [
                                sys.executable,
                                str(IDENTITY_HELPER_PATH),
                                "--state",
                                "present",
                                "--home",
                                str(home),
                                "--path",
                                str(identity),
                                "--user",
                                user,
                                "--group",
                                group,
                                "--comment",
                                "special-entry-test",
                                "--keygen",
                                "/usr/bin/ssh-keygen",
                                "--check",
                            ],
                            stdin=subprocess.DEVNULL,
                            capture_output=True,
                            text=True,
                            check=False,
                            timeout=2,
                        )
                        self.assertNotEqual(completed.returncode, 0)
                        self.assertLess(time.monotonic() - started, 2)
                    finally:
                        if listener is not None:
                            listener.close()

        completed = subprocess.run(
            [
                sys.executable,
                str(IDENTITY_HELPER_PATH),
                "--state",
                "present",
                "--home",
                "/dev",
                "--path",
                "/dev/null",
                "--user",
                user,
                "--group",
                group,
                "--comment",
                "device-entry-test",
                "--keygen",
                "/usr/bin/ssh-keygen",
                "--check",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
        self.assertNotEqual(completed.returncode, 0)

    def test_identity_rejects_wrong_mode_and_hardlink_replacements_before_read(self):
        uid = os.getuid()
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                private = parent / "identity"
                private.write_bytes(b"replacement")
                private.chmod(0o644)
                with self.assertRaisesRegex(
                    identity_helper.IdentityError, "owner-controlled regular"
                ):
                    identity_helper._read_regular(descriptor, "identity", uid, 0o600)
                private.chmod(0o600)
                linked = parent / "replacement-link"
                os.link(private, linked)
                with self.assertRaisesRegex(
                    identity_helper.IdentityError, "owner-controlled regular"
                ):
                    identity_helper._read_regular(descriptor, "identity", uid, 0o600)
                self.assertEqual(private.read_bytes(), b"replacement")
            finally:
                os.close(descriptor)

    def test_identity_cleanup_is_exclusive_and_rejects_post_verification_swap(self):
        for case in ("precreated-target", "post-verification-swap"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                parent = Path(temporary)
                source = parent / "identity"
                source.write_bytes(b"owned")
                source.chmod(0o600)
                parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
                expected = identity_helper._inode_identity(source.stat())
                original_rename = identity_helper._rename_exclusive_at
                displaced = parent / ".identity-displaced"
                target_path = None

                def race_cleanup(
                    descriptor,
                    source_name,
                    target_name,
                    *,
                    root=parent,
                    selected_case=case,
                    source_path=source,
                    displaced_path=displaced,
                    rename=original_rename,
                ):
                    nonlocal target_path
                    target_path = root / target_name
                    if selected_case == "precreated-target":
                        target_path.write_bytes(b"concurrent")
                        target_path.chmod(0o600)
                    else:
                        source_path.rename(displaced_path)
                        source_path.write_bytes(b"replacement")
                        source_path.chmod(0o600)
                    return rename(descriptor, source_name, target_name)

                try:
                    with mock.patch.object(
                        identity_helper,
                        "_rename_exclusive_at",
                        side_effect=race_cleanup,
                    ):
                        if case == "precreated-target":
                            with self.assertRaisesRegex(
                                identity_helper.IdentityError, "quarantine exists"
                            ):
                                identity_helper._safe_unlink_identity(
                                    parent_fd, source.name, expected
                                )
                            self.assertEqual(source.read_bytes(), b"owned")
                            self.assertEqual(target_path.read_bytes(), b"concurrent")
                        else:
                            with self.assertRaisesRegex(
                                identity_helper.IdentityError, "raced during cleanup"
                            ):
                                identity_helper._safe_unlink_identity(
                                    parent_fd, source.name, expected
                                )
                            self.assertEqual(displaced.read_bytes(), b"owned")
                            self.assertEqual(target_path.read_bytes(), b"replacement")
                finally:
                    os.close(parent_fd)

    def test_cleanup_recreated_canonical_is_preserved_at_every_durability_boundary(
        self,
    ):
        for name, mode in (
            ("identity", 0o600),
            ("identity.pub", 0o644),
            (".identity.creation.json", 0o600),
        ):
            for boundary in ("rename", "first-fsync", "final-fsync"):
                with (
                    self.subTest(name=name, boundary=boundary),
                    tempfile.TemporaryDirectory() as temporary,
                ):
                    parent = Path(temporary)
                    source = parent / name
                    source.write_bytes(b"authenticated evidence")
                    source.chmod(mode)
                    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
                    expected = identity_helper._inode_identity(source.stat())
                    original_rename = identity_helper._rename_exclusive_at
                    original_fsync = identity_helper.os.fsync
                    fsync_calls = 0
                    recreated = False

                    def recreate():
                        nonlocal recreated
                        if not recreated:
                            recreated = True
                            source.write_bytes(b"concurrent canonical")
                            source.chmod(mode)

                    def rename_then_recreate(*args, **kwargs):
                        result = original_rename(*args, **kwargs)
                        if boundary == "rename":
                            recreate()
                        return result

                    def fsync_then_recreate(descriptor):
                        nonlocal fsync_calls
                        result = original_fsync(descriptor)
                        if descriptor == parent_fd:
                            fsync_calls += 1
                            selected = 1 if boundary == "first-fsync" else 2
                            if boundary != "rename" and fsync_calls == selected:
                                recreate()
                        return result

                    try:
                        with (
                            mock.patch.object(
                                identity_helper,
                                "_rename_exclusive_at",
                                side_effect=rename_then_recreate,
                            ),
                            mock.patch.object(
                                identity_helper.os,
                                "fsync",
                                side_effect=fsync_then_recreate,
                            ),
                            self.assertRaisesRegex(
                                identity_helper.IdentityError,
                                "canonical name was recreated",
                            ),
                        ):
                            identity_helper._safe_unlink_identity(
                                parent_fd, name, expected
                            )
                        self.assertTrue(recreated)
                        self.assertEqual(source.read_bytes(), b"concurrent canonical")
                        quarantines = list(
                            parent.glob(f".{name.lstrip('.')}.remove-*.tmp")
                        )
                        self.assertEqual(len(quarantines), 1)
                        self.assertEqual(
                            quarantines[0].read_bytes(), b"authenticated evidence"
                        )
                    finally:
                        os.close(parent_fd)

    def test_absent_identity_cleanup_uses_original_private_and_public_read_binding(
        self,
    ):
        uid = os.getuid()
        for name, mode in (("identity", 0o600), ("identity.pub", 0o644)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                parent = Path(temporary)
                source = parent / name
                source.write_bytes(b"validated")
                source.chmod(mode)
                parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
                displaced = parent / f".{name}.validated"
                try:
                    binding = identity_helper._read_regular(parent_fd, name, uid, mode)
                    self.assertIsNotNone(binding)
                    assert binding is not None
                    source.rename(displaced)
                    source.write_bytes(b"operator replacement")
                    source.chmod(mode)
                    with self.assertRaisesRegex(
                        identity_helper.IdentityError,
                        "controlled temporary identity changed",
                    ):
                        identity_helper._safe_unlink_identity(
                            parent_fd, name, binding.identity
                        )
                    self.assertEqual(source.read_bytes(), b"operator replacement")
                    self.assertEqual(displaced.read_bytes(), b"validated")
                finally:
                    os.close(parent_fd)

    def test_account_has_key_sshd_fencing_and_transaction_defense(self):
        main_tasks = self.read("roles/ssh_restricted_forwarding_account/tasks/main.yml")
        transaction_tasks = self.read(
            "roles/ssh_restricted_forwarding_account/tasks/account.yml"
        )
        tasks = main_tasks + "\n" + transaction_tasks
        defaults = self.read(
            "roles/ssh_restricted_forwarding_account/defaults/main.yml"
        )
        key = self.read(
            "roles/ssh_restricted_forwarding_account/templates/authorized_keys.j2"
        )
        sshd = self.read(
            "roles/ssh_restricted_forwarding_account/templates/sshd-forwarding.conf.j2"
        )
        self.assertIn("restrict,port-forwarding", key)
        self.assertIn("permitopen=", key)
        self.assertIn("command=", key)
        for directive in (
            "AuthenticationMethods publickey",
            "AllowTcpForwarding local",
            "PermitOpen",
            "PermitListen none",
            "GatewayPorts no",
            "AllowAgentForwarding no",
            "PermitTTY no",
            "MaxSessions 0",
            "ForceCommand",
            "Match all",
        ):
            self.assertIn(directive, sshd)
        self.assertIn("password_lock: false", tasks)
        self.assertIn(
            "Remove dedicated forwarding account without recursive deletion", tasks
        )
        self.assertIn("remove: false", tasks)
        self.assertNotIn("remove: true", transaction_tasks)
        self.assertIn("Attest exact account identity and no-follow home", tasks)
        self.assertIn("manage_account_home.py --action remove-home", tasks)
        self.assertIn("ssh_restricted_forwarding_account_contract_path", defaults)
        self.assertIn("Create temporary complete sshd candidate tree", tasks)
        self.assertIn("Mutate account, key, and policy as one transaction", tasks)
        self.assertIn("Restore exact prior account properties", tasks)
        self.assertIn("Attest restored sshd policy activation", tasks)
        self.assertIn(
            "Reattest holder and fencing immediately before provisioning mutation",
            tasks,
        )
        self.assertIn(
            "Reattest holder and fencing immediately before revocation mutation",
            tasks,
        )
        self.assertIn(
            "Reattest holder liveness and fencing before successful finalization",
            tasks,
        )
        self.assertIn("durable transaction marker", tasks)
        self.assertIn("async: 2147483647", main_tasks)
        self.assertIn("release-token", main_tasks)
        self.assertIn("ssh_restricted_forwarding_account_fence_path", defaults)
        self.assertIn(
            "ssh_restricted_forwarding_account_recovery_credential_path", defaults
        )
        self.assertIn("--credential", main_tasks)
        self.assertIn(
            "Remove ephemeral transaction lock control directory after holder exit",
            main_tasks,
        )
        self.assertNotIn("/root/.ssh", tasks)

    def test_bounded_account_home_removal_unlinks_symlinks_without_following(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "managed-home"
            nested = home / "nested"
            outside = root / "outside"
            nested.mkdir(parents=True)
            outside.mkdir()
            marker = outside / "marker"
            marker.write_text("untouched", encoding="utf-8")
            (home / "outside-link").symlink_to(outside, target_is_directory=True)
            (nested / "file").write_text("managed", encoding="utf-8")
            descriptor = os.open(home, os.O_RDONLY | os.O_DIRECTORY)
            try:
                with (
                    mock.patch.object(
                        account_home_helper, "_mount_id_fd", return_value=1
                    ),
                    mock.patch.object(account_home_helper, "_require_entry_mount"),
                ):
                    account_home_helper._preflight_contents(descriptor, 1)
                    account_home_helper._remove_contents(descriptor, 1)
            finally:
                os.close(descriptor)
            self.assertEqual(list(home.iterdir()), [])
            self.assertEqual(marker.read_text(encoding="utf-8"), "untouched")

    def test_account_home_preflight_rejects_same_device_nested_mount_before_deletion(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            nested = home / "nested-mount"
            ordinary = home / "ordinary"
            nested.mkdir(parents=True)
            ordinary.mkdir()
            protected = nested / "protected"
            managed = ordinary / "managed"
            protected.write_text("preserve", encoding="utf-8")
            managed.write_text("preserve", encoding="utf-8")
            nested_inode = nested.stat().st_ino

            def mount_id(descriptor):
                # Bind mounts can share st_dev; only the kernel mount ID differs.
                return 2 if os.fstat(descriptor).st_ino == nested_inode else 1

            def portable_open_entry(directory_fd, name):
                return os.open(
                    name,
                    os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW,
                    dir_fd=directory_fd,
                )

            descriptor = os.open(home, os.O_RDONLY | os.O_DIRECTORY)
            try:
                with (
                    mock.patch.object(
                        account_home_helper, "_mount_id_fd", side_effect=mount_id
                    ),
                    mock.patch.object(
                        account_home_helper,
                        "_open_entry_for_mount",
                        side_effect=portable_open_entry,
                    ),
                    self.assertRaisesRegex(
                        account_home_helper.AccountRemovalError, "nested mount"
                    ),
                ):
                    account_home_helper._preflight_contents(descriptor, 1)
            finally:
                os.close(descriptor)
            self.assertEqual(protected.read_text(encoding="utf-8"), "preserve")
            self.assertEqual(managed.read_text(encoding="utf-8"), "preserve")

    @staticmethod
    def contracted_identity_payload():
        return {
            "version": 1,
            "user": "managed_user",
            "uid": 4242,
            "group": "managed_group",
            "gid": 4242,
            "home": "/home/managed_user",
            "shell": "/usr/sbin/nologin",
        }

    def test_partial_removal_rejects_recycled_uid_when_passwd_name_is_absent(self):
        payload = self.contracted_identity_payload()
        recycled = mock.Mock(pw_name="replacement_user")
        with (
            mock.patch.object(
                account_home_helper.pwd, "getpwuid", return_value=recycled
            ),
            self.assertRaisesRegex(
                account_home_helper.AccountRemovalError, "UID was reassigned"
            ),
        ):
            account_home_helper._require_contracted_numeric_identity(payload)

    def test_partial_removal_rejects_recycled_primary_gid(self):
        payload = self.contracted_identity_payload()
        group = mock.Mock(gr_name="replacement_group")
        with (
            mock.patch.object(
                account_home_helper.pwd, "getpwuid", side_effect=KeyError
            ),
            mock.patch.object(account_home_helper.grp, "getgrgid", return_value=group),
            self.assertRaisesRegex(
                account_home_helper.AccountRemovalError, "GID was reassigned"
            ),
        ):
            account_home_helper._require_contracted_numeric_identity(payload)

    def test_process_scan_rejects_live_contracted_uid_and_unreadable_status(self):
        for error, expected in (
            (None, "running process"),
            (PermissionError("denied"), "cannot read one process owner"),
        ):
            with self.subTest(error=error):
                entry = mock.MagicMock()
                entry.name = "123"
                status = mock.Mock()
                entry.__truediv__.return_value = status
                if error is None:
                    status.read_text.return_value = (
                        "Name:\ttest\nUid:\t4242\t4242\t4242\t4242\n"
                    )
                else:
                    status.read_text.side_effect = error
                with (
                    mock.patch.object(Path, "is_dir", return_value=True),
                    mock.patch.object(Path, "iterdir", return_value=iter([entry])),
                    self.assertRaisesRegex(
                        account_home_helper.AccountRemovalError, expected
                    ),
                ):
                    account_home_helper._require_no_uid_processes(4242)

    def test_check_mode_process_gate_reports_contracted_uid_processes(self):
        payload = self.contracted_identity_payload()
        with mock.patch.object(
            account_home_helper, "_uid_processes", return_value=[123, 456]
        ):
            processes = account_home_helper._require_contracted_numeric_identity(
                payload, defer_uid_processes=True
            )
        self.assertEqual(processes, [123, 456])

    def test_passwd_absent_partial_resume_still_attests_numeric_identity_and_processes(
        self,
    ):
        payload = self.contracted_identity_payload()
        contract = Path(tempfile.gettempdir()) / "managed-contract-present"
        contract.touch()
        self.addCleanup(contract.unlink, missing_ok=True)
        with (
            mock.patch.object(
                account_home_helper, "_current_identity", return_value=(None, None)
            ),
            mock.patch.object(
                account_home_helper, "_open_home_parent", return_value=99
            ),
            mock.patch.object(
                account_home_helper.os, "stat", side_effect=FileNotFoundError
            ),
            mock.patch.object(Path, "exists", return_value=True),
            mock.patch.object(account_home_helper.os, "close"),
            mock.patch.object(
                account_home_helper,
                "_read_contract",
                return_value=(payload, mock.Mock()),
            ),
            mock.patch.object(
                account_home_helper, "_require_contracted_numeric_identity"
            ) as require_numeric,
        ):
            result = account_home_helper.attest(
                "managed_user",
                "managed_group",
                Path("/home/managed_user"),
                "/usr/sbin/nologin",
                contract,
            )
        self.assertEqual(result["status"], "absent")
        require_numeric.assert_called_once_with(payload)

    def test_fully_absent_account_is_idempotent_without_stale_uid_scan(self):
        contract = Path(tempfile.gettempdir()) / "managed-contract-absent"
        contract.unlink(missing_ok=True)
        with (
            mock.patch.object(
                account_home_helper, "_current_identity", return_value=(None, None)
            ),
            mock.patch.object(
                account_home_helper, "_open_home_parent", return_value=99
            ),
            mock.patch.object(
                account_home_helper.os, "stat", side_effect=FileNotFoundError
            ),
            mock.patch.object(Path, "exists", return_value=False),
            mock.patch.object(Path, "is_symlink", return_value=False),
            mock.patch.object(account_home_helper.os, "close"),
            mock.patch.object(
                account_home_helper, "_require_contracted_numeric_identity"
            ) as require_numeric,
        ):
            result = account_home_helper.attest(
                "managed_user",
                "managed_group",
                Path("/home/managed_user"),
                "/usr/sbin/nologin",
                contract,
            )
        self.assertEqual(result, {"status": "absent"})
        require_numeric.assert_not_called()

    def test_sshd_candidate_rejects_absolute_config_and_dropin_symlinks_without_target_mutation(
        self,
    ):
        for linked_name, target_is_directory in (
            ("sshd_config", False),
            ("sshd_config.d", True),
        ):
            with (
                self.subTest(linked_name=linked_name),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                source = root / "ssh"
                candidate = root / "candidate"
                outside = root / "outside"
                source.mkdir(mode=0o700)
                candidate.mkdir(mode=0o700)
                if target_is_directory:
                    outside.mkdir(mode=0o751)
                    marker = outside / "marker.conf"
                    marker.write_bytes(b"outside dropin bytes\n")
                    marker.chmod(0o640)
                    (source / "sshd_config").write_text(
                        "Include /etc/ssh/sshd_config.d/*.conf\n",
                        encoding="utf-8",
                    )
                else:
                    outside.write_bytes(b"outside config bytes\n")
                    outside.chmod(0o640)
                    marker = outside
                    (source / "sshd_config.d").mkdir(mode=0o755)
                (source / linked_name).symlink_to(
                    outside.resolve(), target_is_directory=target_is_directory
                )
                before_target_info = outside.stat()
                before_info = marker.stat()
                before_bytes = marker.read_bytes()
                with self.assertRaisesRegex(
                    candidate_helper.CandidateError, "contains a symlink"
                ):
                    candidate_helper.prepare(source, candidate)
                after_target_info = outside.stat()
                after_info = marker.stat()
                self.assertEqual(marker.read_bytes(), before_bytes)
                self.assertEqual(
                    (
                        after_target_info.st_mode,
                        after_target_info.st_uid,
                        after_target_info.st_gid,
                        after_target_info.st_size,
                        after_target_info.st_mtime_ns,
                    ),
                    (
                        before_target_info.st_mode,
                        before_target_info.st_uid,
                        before_target_info.st_gid,
                        before_target_info.st_size,
                        before_target_info.st_mtime_ns,
                    ),
                )
                self.assertEqual(
                    (
                        after_info.st_mode,
                        after_info.st_uid,
                        after_info.st_gid,
                        after_info.st_size,
                        after_info.st_mtime_ns,
                    ),
                    (
                        before_info.st_mode,
                        before_info.st_uid,
                        before_info.st_gid,
                        before_info.st_size,
                        before_info.st_mtime_ns,
                    ),
                )

    def test_server_lock_outlives_acquisition_timeout_until_authenticated_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock = root / "account.lock"
            first_ready = root / "first-ready"
            first_release = root / "first-release"
            token = "correct-token"
            holder = threading.Thread(
                target=lock_helper.hold,
                args=(lock, first_ready, first_release, 1, token),
            )
            holder.start()
            deadline = time.monotonic() + 2
            while not first_ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(first_ready.exists())
            time.sleep(1.1)
            with self.assertRaisesRegex(
                lock_helper.LockError, "did not become available"
            ):
                lock_helper.hold(
                    lock, root / "second-ready", root / "second-release", 0, "other"
                )
            first_release.write_text("wrong-token\n", encoding="utf-8")
            time.sleep(0.2)
            self.assertTrue(holder.is_alive())
            first_release.write_text(f"{token}\n", encoding="utf-8")
            first_release.chmod(0o600)
            holder.join(timeout=2)
            self.assertFalse(holder.is_alive())

    def test_recovery_credential_is_durable_before_marker_and_ready_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "account.transaction.json"
            credential = root / "account.recovery.json"
            with (
                mock.patch.object(
                    lock_helper,
                    "_write_marker",
                    side_effect=OSError("simulated power loss"),
                ),
                self.assertRaisesRegex(OSError, "simulated power loss"),
            ):
                lock_helper.hold(
                    root / "account.lock",
                    root / "ready",
                    root / "release",
                    1,
                    "durable-token",
                    marker_path=marker,
                    credential_path=credential,
                )
            self.assertEqual(
                lock_helper._read_credential(credential), ["durable-token"]
            )
            self.assertFalse(marker.exists())
            self.assertFalse((root / "ready").exists())

    def test_takeover_power_loss_always_leaves_marker_matching_stable_credential(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "account.transaction.json"
            credential = root / "account.recovery.json"
            old_token = "1" * 64
            stale = {
                "version": 1,
                "state": "unreleased",
                "holder_host": lock_helper.socket.gethostname(),
                "holder_pid": 999999,
                "holder_start_token": "proc:gone",
                "generation": 1,
                "fencing_token": "old-fence",
                "recovery_token_sha256": lock_helper.hashlib.sha256(
                    old_token.encode()
                ).hexdigest(),
            }
            lock_helper._write_credential(credential, [old_token])
            lock_helper._write_marker(marker, stale)
            with (
                mock.patch.object(
                    lock_helper,
                    "_write_marker",
                    side_effect=OSError("simulated takeover power loss"),
                ),
                self.assertRaisesRegex(OSError, "takeover power loss"),
            ):
                lock_helper.hold(
                    root / "account.lock",
                    root / "failed-ready",
                    root / "failed-release",
                    1,
                    "2" * 64,
                    marker_path=marker,
                    credential_path=credential,
                    generation=2,
                    fencing_token="failed-fence",
                    recover=True,
                    recovery_token=old_token,
                )
            self.assertEqual(lock_helper._read_marker(marker), stale)
            self.assertIn(old_token, lock_helper._read_credential(credential))
            self.assertFalse((root / "failed-ready").exists())

            release_token = "3" * 64
            recovered = threading.Thread(
                target=lock_helper.hold,
                args=(
                    root / "account.lock",
                    root / "ready",
                    root / "release",
                    1,
                    release_token,
                ),
                kwargs={
                    "marker_path": marker,
                    "credential_path": credential,
                    "generation": 2,
                    "fencing_token": "recovered-fence",
                    "recover": True,
                    "recovery_token": old_token,
                },
            )
            recovered.start()
            deadline = time.monotonic() + 3
            while not (root / "ready").exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue((root / "ready").exists())
            (root / "release").write_text(f"{release_token}\n", encoding="utf-8")
            (root / "release").chmod(0o600)
            recovered.join(timeout=3)
            self.assertFalse(recovered.is_alive())
            self.assertFalse(marker.exists())
            self.assertFalse(credential.exists())

    def test_stable_credential_recovers_after_ephemeral_control_directory_loss(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stable = root / "stable"
            stable.mkdir(mode=0o700)
            control = root / "control"
            control.mkdir(mode=0o700)
            lock = root / "account.lock"
            marker = stable / "account.transaction.json"
            credential = stable / "account.recovery.json"
            token = "1" * 64
            helper_dir = LOCK_HELPER_PATH.parent
            code = (
                "import sys; "
                f"sys.path.insert(0, {str(helper_dir)!r}); "
                "from pathlib import Path; import hold_transaction_lock as h; "
                f"h.hold(Path({str(lock)!r}), Path({str(control / 'ready')!r}), "
                f"Path({str(control / 'release')!r}), 1, {token!r}, "
                f"marker_path=Path({str(marker)!r}), "
                f"credential_path=Path({str(credential)!r}), "
                "generation=1, fencing_token='first-fence')"
            )
            holder = subprocess.Popen([sys.executable, "-c", code])
            self.addCleanup(lambda: holder.poll() is None and holder.kill())
            deadline = time.monotonic() + 3
            while not (control / "ready").exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue((control / "ready").exists())
            holder.kill()
            holder.wait(timeout=3)
            recovered_token = lock_helper._read_credential(credential)[0]
            for child in control.iterdir():
                child.unlink()
            control.rmdir()

            recovery_control = root / "recovery-control"
            recovery_control.mkdir(mode=0o700)
            release_token = "2" * 64
            synced_directories = []
            original_fsync_directory = lock_helper._fsync_directory

            def recording_fsync_directory(path):
                synced_directories.append(path)
                original_fsync_directory(path)

            recovered = threading.Thread(
                target=lock_helper.hold,
                args=(
                    lock,
                    recovery_control / "ready",
                    recovery_control / "release",
                    1,
                    release_token,
                ),
                kwargs={
                    "marker_path": marker,
                    "credential_path": credential,
                    "generation": 2,
                    "fencing_token": "second-fence",
                    "recover": True,
                    "recovery_token": recovered_token,
                },
            )
            with mock.patch.object(
                lock_helper,
                "_fsync_directory",
                side_effect=recording_fsync_directory,
            ):
                recovered.start()
                deadline = time.monotonic() + 3
                while (
                    not (recovery_control / "ready").exists()
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.01)
                self.assertTrue((recovery_control / "ready").exists())
                (recovery_control / "release").write_text(
                    f"{release_token}\n", encoding="utf-8"
                )
                (recovery_control / "release").chmod(0o600)
                recovered.join(timeout=3)
            self.assertFalse(recovered.is_alive())
            self.assertFalse(marker.exists())
            self.assertFalse(credential.exists())
            # Transition writes plus marker/credential cleanup are directory durable.
            self.assertGreaterEqual(synced_directories.count(stable), 5)

    def test_unsafe_stable_credential_is_rejected_without_target_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "outside"
            target.write_text("do not change\n", encoding="utf-8")
            target.chmod(0o600)
            credential = root / "account.recovery.json"
            credential.symlink_to(target)
            with self.assertRaisesRegex(lock_helper.LockError, "not canonical"):
                lock_helper.hold(
                    root / "account.lock",
                    root / "ready",
                    root / "release",
                    1,
                    "new-token",
                    marker_path=root / "account.transaction.json",
                    credential_path=credential,
                )
            self.assertEqual(target.read_text(encoding="utf-8"), "do not change\n")
            self.assertTrue(credential.is_symlink())

    def test_holder_death_leaves_durable_marker_and_requires_authenticated_recovery(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock = root / "account.lock"
            marker = root / "account.transaction.json"
            ready = root / "ready"
            release = root / "release"
            first_token = "1" * 64
            helper_dir = LOCK_HELPER_PATH.parent
            code = (
                "import sys; "
                f"sys.path.insert(0, {str(helper_dir)!r}); "
                "from pathlib import Path; "
                "import hold_transaction_lock as h; "
                f"h.hold(Path({str(lock)!r}), Path({str(ready)!r}), "
                f"Path({str(release)!r}), 1, {first_token!r}, "
                f"marker_path=Path({str(marker)!r}), generation=1, "
                "fencing_token='first-fence')"
            )
            holder = subprocess.Popen([sys.executable, "-c", code])
            self.addCleanup(lambda: holder.poll() is None and holder.kill())
            deadline = time.monotonic() + 3
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(ready.exists())
            holder.kill()
            holder.wait(timeout=3)
            self.assertTrue(marker.exists())

            with self.assertRaisesRegex(lock_helper.LockError, "unreleased"):
                lock_helper.hold(
                    lock,
                    root / "normal-ready",
                    root / "normal-release",
                    0,
                    "2" * 64,
                    marker_path=marker,
                    generation=2,
                    fencing_token="normal-fence",
                )
            with self.assertRaisesRegex(lock_helper.LockError, "token is invalid"):
                lock_helper.hold(
                    lock,
                    root / "wrong-ready",
                    root / "wrong-release",
                    0,
                    "3" * 64,
                    marker_path=marker,
                    generation=2,
                    fencing_token="recovery-fence",
                    recover=True,
                    recovery_token="wrong-token",
                )

            recovery_ready = root / "recovery-ready"
            recovery_release = root / "recovery-release"
            recovery_token = "4" * 64
            recovered = threading.Thread(
                target=lock_helper.hold,
                args=(lock, recovery_ready, recovery_release, 1, recovery_token),
                kwargs={
                    "marker_path": marker,
                    "generation": 2,
                    "fencing_token": "recovery-fence",
                    "recover": True,
                    "recovery_token": first_token,
                },
            )
            recovered.start()
            deadline = time.monotonic() + 3
            while not recovery_ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(recovery_ready.exists())
            marker_payload = lock_helper._read_marker(marker)
            self.assertEqual(marker_payload["generation"], 2)
            self.assertEqual(marker_payload["fencing_token"], "recovery-fence")
            with self.assertRaisesRegex(
                lock_helper.LockError, "marker ownership changed"
            ):
                lock_helper.attest(
                    marker,
                    root / "unused-fence",
                    1,
                    "first-fence",
                )
            recovery_release.write_text(f"{recovery_token}\n", encoding="utf-8")
            recovery_release.chmod(0o600)
            recovered.join(timeout=3)
            self.assertFalse(recovered.is_alive())
            self.assertFalse(marker.exists())

    def test_takeover_fence_rejects_obsolete_owner_mutation_and_finalization(self):
        current = {"generation": 8, "token": "new-token"}
        with (
            mock.patch.object(fence_helper.os, "geteuid", return_value=0),
            mock.patch.object(fence_helper, "_read", return_value=current),
            mock.patch.object(fence_helper, "_write") as write,
        ):
            with self.assertRaisesRegex(fence_helper.FenceError, "obsolete"):
                fence_helper.manage(Path("/fence"), 7, "old-token", "claim")
            with self.assertRaisesRegex(fence_helper.FenceError, "lost server fencing"):
                fence_helper.manage(Path("/fence"), 7, "old-token", "check")
            self.assertEqual(
                fence_helper.manage(Path("/fence"), 8, "new-token", "check")["status"],
                "attested",
            )
            write.assert_not_called()

    def test_molecule_harness_covers_real_sshd_policy_and_failure_paths(self):
        verify = self.read(
            "roles/ssh_restricted_forwarding_account/molecule/default/verify.yml"
        )
        molecule = self.read(
            "roles/ssh_restricted_forwarding_account/molecule/default/molecule.yml"
        )
        for behavior in (
            "Authenticate key and establish permitted local forwarding",
            "Reject shell or exec session",
            "Reject remote forwarding",
            "Exercise traversal rejection before root writes",
            "Require managed account, key, and policy rollback",
            "Prove prior key authenticates after recovery reload",
            "Exercise symlinked identity parent rejection before mutation",
            "Prove symlink target contents and metadata were untouched",
            "Exercise drifted passwd home rejection",
            "Exercise drifted shell rejection",
            "Exercise drifted primary group rejection",
            "Exercise drifted home ownership rejection",
            "Exercise symlinked home hierarchy rejection",
            "Exercise repurposed username rejection",
            "Prove canonical-home tmpfs preservation when capabilities permit",
            "Prove canonical-home bind preservation when capabilities permit",
            "Prove real tmpfs preservation when container capabilities permit",
            "Prove same-device bind mount preservation when capabilities permit",
            "Canonically revoke and remove managed account",
            "Rerun absent state to prove idempotence",
        ):
            self.assertIn(behavior, verify)
        self.assertIn("- idempotence", molecule)
        self.assertIn("- check", molecule)

    def test_public_documentation_and_collection_version_are_updated(self):
        readme = self.read("README.md")
        changelog = self.read("CHANGELOG.md")
        galaxy = self.read("galaxy.yml")
        for role in ("ssh_forwarding_identity", "ssh_restricted_forwarding_account"):
            self.assertIn(f"roles/{role}/README.md", readme)
            self.assertIn(role, changelog)
        # The SSH forwarding roles shipped in 2.12.0; later releases must not
        # regress below that, but pinning the exact version made every
        # unrelated collection bump fail here.
        version = next(
            line.split(":", 1)[1].strip()
            for line in galaxy.splitlines()
            if line.startswith("version:")
        )
        self.assertGreaterEqual(
            tuple(int(part) for part in version.split(".")), (2, 12, 0)
        )
        identity_readme = self.read("roles/ssh_forwarding_identity/README.md")
        self.assertIn(
            "never rotates or removes a private key implicitly", identity_readme
        )
        self.assertIn("confirmed `state: absent` removes", identity_readme)


if __name__ == "__main__":
    unittest.main()
