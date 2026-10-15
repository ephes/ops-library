"""A FastDeploy restore must not bring back what stage 1 retired.

Stage 1 of the FastDeploy privilege reduction unregistered `fastdeploy-self`
and `apt_upgrade_*` and removed their sudoers rules (`deploy ALL=(root) ALL`
among them). Archives taken before that still contain them; the Echoport
restore runner skips them.
"""

from __future__ import annotations

import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_fastdeploy_backup_key import render_runner

ROOT = Path(__file__).resolve().parents[1]
CHECK_SCRIPT = ROOT / "roles" / "fastdeploy_restore" / "files" / "sudoers_blanket_check.py"

# text -> restorable
SUDOERS_CASES = {
    "deploy ALL=(root) NOPASSWD: ALL\n": False,
    "deploy ALL=(root) NOPASSWD: ALL # legacy access\n": False,
    "deploy ALL=(root) NOPASSWD: ALL #included for legacy access\n": False,
    "deploy ALL=(root) NOPASSWD: \\\n    ALL\n": False,
    "deploy ALL=(root) NOPASSWD: /bin/true, ALL\n": False,
    "deploy ALL=(root) NOPASSWD: ALL : ALL=(root) /bin/true\n": False,
    "Defaultsdeploy ALL=(root) NOPASSWD: ALL\n": False,
    "Cmnd_Alias EVERYTHING = ALL\ndeploy ALL=(root) NOPASSWD: EVERYTHING\n": False,
    "#include /etc/sudoers.d/other\n": False,
    "#includedir /etc/sudoers.d\n": False,
    "#1001 ALL=(root) NOPASSWD: ALL\n": False,
    "#comment-without-space\n": False,
    "#\n# Managed by Ansible\n": True,
    "deploy ALL=(root) /x/backup.py *\n": False,
    "deploy ALL=(root) NOPASSWD: /usr/bin/\n": False,
    "deploy ALL=(root) NOPASSWD: /usr/bin/ *\n": False,
    "deploy ALL=(root) NOPASSWD: /usr/bin/.\n": False,
    "deploy ALL=(root) NOPASSWD: /usr/bin/bash *\n": False,
    "deploy ALL=(root) NOPASSWD: /home/deploy/runners/../../../usr/bin/bash\n": False,
    "deploy ALL=(root) NOPASSWD: /home/deploy/runners/x/../y\n": False,
    "deploy ALL=(root) NOPASSWD: /home/deploy/runners/x/\n": False,
    "fastdeploy ALL=(deploy) NOPASSWD: /home/deploy/runners/nyxmon/deploy.py\n": True,
    "# Stage 1\nfastdeploy ALL=(deploy) NOPASSWD:NOSETENV: /home/fastdeploy/site/services/x/backup.py *\n"
    "deploy ALL=(root) NOPASSWD:NOSETENV: /home/fastdeploy/site/services/x/backup.py *\n": True,
    "deploy ALL=(root) NOPASSWD:NOSETENV: /usr/local/libexec/daybook-operations-backup --config *\n": True,
    "fastdeploy ALL=(ALL) NOPASSWD: /usr/bin/systemctl\n": False,
    "# deploy ALL=(root) ALL\n\n": True,
}


class RetiredEntriesAreNotRestored(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = render_runner()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_defaults_name_the_retired_services_and_rules(self) -> None:
        self.assertEqual(
            set(self.runner.RETIRED_ENTRIES),
            {"fastdeploy-self", "fastdeploy-self-playbook.yml", "apt_upgrade_local", "apt_upgrade_staging"},
        )
        self.assertEqual(
            set(self.runner.RETIRED_SUDOERS),
            {"fastdeploy", "fastdeploy_fastdeploy-self", "fastdeploy_self_deploy_users"},
        )

    def test_restorable_check_matches_the_role_script(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location("sudoers_blanket_check", CHECK_SCRIPT)
        assert spec and spec.loader
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        for text, expected in SUDOERS_CASES.items():
            with self.subTest(text=text):
                self.assertIs(self.runner.sudoers_restorable(text), expected)
                self.assertIs(script.restorable(text), expected)

    def test_retired_sudoers_files_are_skipped(self) -> None:
        stage = self.tmp / "sudoers"
        stage.mkdir()
        for name in ("fastdeploy_fastdeploy-self", "fastdeploy_self_deploy_users", "fastdeploy_backup"):
            (stage / f"{name}.rule").write_text(
                "fastdeploy ALL=(deploy) NOPASSWD:NOSETENV: /home/fastdeploy/site/services/b/backup.py *\n"
            )
        # Older fastdeploy_register_service output: a narrow rule plus a blanket one.
        (stage / "fastdeploy_nyxmon.rule").write_text(
            "fastdeploy ALL=(deploy) NOPASSWD: /home/deploy/runners/nyxmon/deploy.py\n"
            "deploy ALL=(root) NOPASSWD: ALL\n"
        )
        (stage / "fastdeploy_echoport.rule").write_text(
            "fastdeploy ALL=(deploy) NOPASSWD:NOSETENV: /home/fastdeploy/site/services/e/backup.py *\n"
            "deploy ALL=(root) NOPASSWD:NOSETENV: /home/fastdeploy/site/services/e/backup.py *\n"
        )
        copied: list[str] = []
        with (
            mock.patch.object(self.runner.shutil, "copy2", side_effect=lambda src, dst: copied.append(str(dst))),
            mock.patch.object(self.runner, "run_cmd"),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.runner.restore_sudoers_from_stage(stage)
        self.assertEqual(copied, ["/etc/sudoers.d/fastdeploy_backup", "/etc/sudoers.d/fastdeploy_echoport"])

    def test_services_and_runners_are_synced_without_retired_entries(self) -> None:
        stage = self.tmp / "stage"
        for sub in ("services", "deploy_runners"):
            (stage / sub).mkdir(parents=True)
        calls: list[list[str]] = []
        with (
            mock.patch.object(self.runner, "run_cmd", side_effect=lambda args, **kw: calls.append(args)),
            mock.patch.object(self.runner, "SERVICES_PATH", str(self.tmp / "live-services")),
            mock.patch.object(self.runner, "RUNNER_ROOT", str(self.tmp / "live-runners")),
        ):
            self.runner.restore_files_from_stage(stage)
        rsyncs = [args for args in calls if args[0] == "rsync"]
        self.assertEqual(len(rsyncs), 2)
        for args in rsyncs:
            for name in self.runner.RETIRED_ENTRIES:
                self.assertIn(f"--exclude=/{name}", args)
            self.assertIn("--delete", args)


if __name__ == "__main__":
    unittest.main()
