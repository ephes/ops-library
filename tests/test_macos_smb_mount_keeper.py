"""The SMB mount keeper mounts only into a free, exact mount point, and never unmounts."""

import contextlib
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "mount_keeper", ROOT / "roles/macos_smb_mount_keeper/files/mount_keeper.py"
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

SHARE = {
    "server": "fractal.example.ts.net",
    "share": "photos",
    "account": "owner",
    "mount_point": "/Volumes/photos",
}
MOUNTED = "//owner@fractal.example.ts.net/photos on /Volumes/photos (smbfs, nodev, nosuid, mounted by owner)\n"
ELSEWHERE = "//owner@fractal.example.ts.net/photos on /Volumes/photos-1 (smbfs, nodev, nosuid, mounted by owner)\n"
OTHER = (
    "/dev/disk3s1s1 on / (apfs, sealed, local, read-only, journaled)\n"
    "//owner@fractal.example.ts.net/timemachine on /Volumes/.timemachine/x/timemachine (smbfs, nobrowse)\n"
    "/dev/disk13s1 on /Volumes/Photos (apfs, local, nodev, nosuid, journaled)\n"
)


class ClassifyTests(unittest.TestCase):
    def state(self, text, exists=False):
        return module.classify(SHARE, module.mounts(text), exists)

    def test_the_share_at_its_exact_point_is_mounted(self):
        self.assertEqual(self.state(OTHER + MOUNTED, exists=True), "mounted")
        # Server names compare without case, as macOS resolves them.
        self.assertEqual(self.state(MOUNTED.replace("fractal", "FRACTAL"), exists=True), "mounted")

    def test_the_share_at_another_point_is_elsewhere(self):
        self.assertEqual(self.state(ELSEWHERE), "elsewhere")

    def test_anything_else_at_the_point_occupies_it(self):
        # A local volume whose name differs only in case sits on the same path on
        # a case-insensitive /Volumes; so does another share of the same name.
        self.assertEqual(self.state(OTHER, exists=True), "occupied")
        other_server = MOUNTED.replace("fractal.example", "elsewhere.example")
        self.assertEqual(self.state(other_server, exists=True), "occupied")

    def test_a_free_point_without_the_share_is_absent(self):
        self.assertEqual(self.state(OTHER), "absent")


class KeepTests(unittest.TestCase):
    def keep(self, before, after, *, returncode=0, exists=(False, True), raises=None):
        reads = iter([module.mounts(before), module.mounts(after)])
        present = iter(exists)
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            if raises:
                raise raises
            return SimpleNamespace(returncode=returncode)

        outcome = module.keep(SHARE, run=run, read=lambda: next(reads), exists=lambda _p: next(present))
        return outcome, calls

    def test_an_absent_share_is_mounted_through_finder_with_the_keychain(self):
        outcome, calls = self.keep(OTHER, OTHER + MOUNTED)
        self.assertEqual(outcome, "remounted")
        self.assertEqual(calls, [["/usr/bin/osascript", "-e",
                                  'mount volume "smb://owner@fractal.example.ts.net/photos"']])

    def test_nothing_is_run_unless_the_point_is_free(self):
        for before, exists in ((MOUNTED, True), (ELSEWHERE, False), (OTHER, True)):
            with self.subTest(before=before):
                outcome, calls = self.keep(before, before, exists=(exists, exists))
                self.assertNotEqual(outcome, "remounted")
                self.assertEqual(calls, [])

    def test_a_mount_that_lands_elsewhere_or_fails_is_reported(self):
        self.assertEqual(self.keep(OTHER, OTHER + ELSEWHERE, exists=(False, False))[0], "mount_elsewhere")
        self.assertEqual(self.keep(OTHER, OTHER, returncode=1)[0], "mount_failed")
        timeout = subprocess.TimeoutExpired(["osascript"], 90)
        self.assertEqual(self.keep(OTHER, OTHER, raises=timeout)[0], "mount_timeout")

    def test_the_keeper_never_unmounts(self):
        source = (ROOT / "roles/macos_smb_mount_keeper/files/mount_keeper.py").read_text()
        # Commands and calls that could unmount, eject or delete anything.
        for word in ("umount", "unmount volume", "eject", "diskutil", "rmdir", "unlink", "rmtree", "os.remove"):
            self.assertNotIn(word, source)


class MainTests(unittest.TestCase):
    def test_only_a_change_of_outcome_is_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "shares.json"
            state = Path(tmp) / "state" / "state.json"
            config.write_text(json.dumps({"shares": [SHARE]}))
            outcomes = iter(["remounted", "mounted", "mounted", "occupied"])
            logs = []
            with patch.object(module, "keep", side_effect=lambda _share: next(outcomes)):
                for _ in range(4):
                    out = io.StringIO()
                    with contextlib.redirect_stdout(out):
                        self.assertEqual(module.main(str(config), str(state)), 0)
                    logs.append(out.getvalue())
            self.assertIn("remounted", logs[0])
            self.assertEqual(logs[1:3], ["", ""])
            self.assertIn("occupied", logs[3])
            self.assertEqual(json.loads(state.read_text()), {"fractal.example.ts.net/photos": "occupied"})


if __name__ == "__main__":
    unittest.main()
