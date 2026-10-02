"""Regression checks for remote endpoint and accidental private-file exposure."""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import run


class SafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (run.ROOT / "tmp").mkdir(parents=True, exist_ok=True)

    def test_remote_overrides_rejected_before_docker(self):
        for key in ("DOCKER_HOST", "BUILDKIT_HOST"):
            for endpoint in ("ssh://host", "tcp://127.0.0.1:2375", "tcp://remote:2376"):
                with self.subTest(key=key, endpoint=endpoint):
                    with patch.object(run.subprocess, "run") as command:
                        with self.assertRaises(RuntimeError):
                            run.local_endpoint({key: endpoint})
                        command.assert_not_called()

    def test_remote_context_rejected_before_build(self):
        inspected = subprocess.CompletedProcess([], 0, json.dumps("ssh://remote"), "")
        with patch.object(run.os, "environ", {"DOCKER_CONTEXT": "remote"}):
            with patch.object(run.subprocess, "run", return_value=inspected) as command:
                with self.assertRaises(RuntimeError):
                    run.main()
                self.assertEqual(command.call_count, 1)
                self.assertEqual(command.call_args.args[0][1:3], ["context", "inspect"])

    def test_local_socket_and_environment_pinning(self):
        with tempfile.TemporaryDirectory(dir=run.ROOT / "tmp") as directory:
            with socket.socket(socket.AF_UNIX) as daemon:
                endpoint = "unix://" + directory + "/docker.sock"
                # bind(2) limits the supplied path length, even for deep checkouts.
                previous_directory = Path.cwd()
                try:
                    os.chdir(directory)
                    daemon.bind("docker.sock")
                finally:
                    os.chdir(previous_directory)
                self.assertEqual(
                    run.local_endpoint({"DOCKER_HOST": endpoint}), endpoint
                )
        environment = run.docker_environment(
            {
                "PATH": "/bin",
                "DOCKER_HOST": "remote",
                "DOCKER_CONTEXT": "other",
                "BUILDX_BUILDER": "remote",
                "BUILDKIT_HOST": "remote",
            }
        )
        self.assertEqual(environment, {"PATH": "/bin", "DOCKER_BUILDKIT": "0"})

    def test_allowlist_excludes_ignored_canaries_and_rejects_symlinks(self):
        with tempfile.TemporaryDirectory(dir=run.ROOT / "tmp") as directory:
            root = Path(directory) / "source"
            staged = Path(directory) / "staged"
            for relative in (
                *run.MOUNT_FILES,
                "experiments/pyinfra_authorized_keys/Dockerfile",
            ):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("fixture")
            for relative in (
                "secrets/prod/canary.yml",
                ".envrc",
                "inventories/prod/hosts.yml",
                "experiments/pyinfra_authorized_keys/private.key",
            ):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("PRIVATE-CANARY")
            run.stage(root, staged)
            copied = {
                str(path.relative_to(staged / "mount"))
                for path in (staged / "mount").rglob("*")
                if path.is_file()
            }
            self.assertEqual(copied, set(run.MOUNT_FILES))
            self.assertEqual(
                list((staged / "build").iterdir()), [staged / "build/Dockerfile"]
            )
            source = root / run.MOUNT_FILES[0]
            source.unlink()
            source.symlink_to(root / "secrets/prod/canary.yml")
            with self.assertRaises(RuntimeError):
                run.stage(root, Path(directory) / "refused")


if __name__ == "__main__":
    unittest.main()
