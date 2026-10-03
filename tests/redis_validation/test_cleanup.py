"""Run the rendered validator locally against an owned slow-terminating process."""
import os
from pathlib import Path
import shlex
import signal
import subprocess
import tempfile
import time
import unittest

from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[2]
STAND_IN = """#!/usr/bin/env python3
import os, pathlib, signal, socket, subprocess, sys, time
args = sys.argv[1:]
pidfile = pathlib.Path(args[args.index("--pidfile") + 1])
socket_path = args[args.index("--unixsocket") + 1]
marker = pathlib.Path(os.environ["REDIS_CLEANUP_MARKER"])
if "--child" in args:
    signal.signal(signal.SIGTERM, lambda *_: marker.write_text("cleanup started"))
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    listener = socket.socket(socket.AF_UNIX)
    os.chdir(pidfile.parent)
    listener.bind(pathlib.Path(socket_path).name)
    pidfile.write_text(str(os.getpid()))
    while True:
        time.sleep(0.05)
else:
    subprocess.Popen([sys.executable, __file__, "--child", *args],
                     start_new_session=True, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
    for _ in range(200):
        if pidfile.exists() and pathlib.Path(socket_path).is_socket():
            break
        time.sleep(0.01)
    else:
        sys.exit(1)
    if os.environ.get("REDIS_CLEANUP_STARTUP_FAIL") == "1":
        sys.exit(1)
"""


class CleanupTests(unittest.TestCase):
    def test_repeated_signals_during_success_cleanup_fail_and_remove_artifacts(self):
        self.run_cleanup_case(startup_failure=False)

    def test_repeated_signals_during_failed_cleanup_preserve_failure_and_remove_artifacts(
        self,
    ):
        self.run_cleanup_case(startup_failure=True)

    def test_process_group_signals_during_success_cleanup_fail_and_remove_artifacts(
        self,
    ):
        self.run_cleanup_case(startup_failure=False, process_group=True)

    def test_process_group_signals_during_failed_cleanup_preserve_failure_and_remove_artifacts(
        self,
    ):
        self.run_cleanup_case(startup_failure=True, process_group=True)

    def test_process_group_signal_during_pid_read_preserves_cleanup(self):
        self.run_cleanup_case(
            startup_failure=True, process_group=True, pause_command="cat"
        )

    def test_process_group_signal_during_removal_preserves_cleanup(self):
        self.run_cleanup_case(
            startup_failure=True, process_group=True, pause_command="rm"
        )

    def test_permanent_removal_failure_is_bounded_and_fails_validation(self):
        self.run_cleanup_case(startup_failure=False, removal_failure=True)

    def run_cleanup_case(
        self,
        *,
        startup_failure,
        process_group=False,
        pause_command=None,
        removal_failure=False,
    ):
        scratch = ROOT / "tmp"
        scratch.mkdir(exist_ok=True)
        # The stand-in binds a relative socket name, avoiding address length limits
        # even when the review checkout has a deep path. All files remain owned here.
        with tempfile.TemporaryDirectory(prefix="redis-cln-", dir=scratch) as directory:
            root = Path(directory)
            marker = root / "cleanup-started"
            validator_root = root / "validation"
            script = root / "validate.sh"
            env = Environment()
            env.filters["quote"] = shlex.quote
            script.write_text(
                env.from_string(
                    (
                        ROOT / "roles/redis_install/templates/validate-config.sh.j2"
                    ).read_text()
                ).render(redis_install_validate_dir=str(validator_root))
            )
            stand_in = root / "redis-server"
            stand_in.write_text(STAND_IN)
            stand_in.chmod(0o700)
            command_marker = root / "command-started"
            release = root / "command-release"
            if pause_command:
                wrapper = root / pause_command
                wrapper.write_text(
                    "#!/usr/bin/env python3\n"
                    "import os, pathlib, signal, sys, time\n"
                    "pathlib.Path(os.environ['REDIS_COMMAND_MARKER']).write_text(str(signal.getsignal(signal.SIGTERM)))\n"
                    "while not pathlib.Path(os.environ['REDIS_COMMAND_RELEASE']).exists(): time.sleep(0.01)\n"
                    f"os.execv('/bin/{pause_command}', ['{pause_command}', *sys.argv[1:]])\n"
                )
                wrapper.chmod(0o700)
            if removal_failure:
                wrapper = root / "rm"
                wrapper.write_text(
                    "#!/usr/bin/env python3\n"
                    "import os, pathlib, sys\n"
                    "count = pathlib.Path(os.environ['REDIS_COMMAND_MARKER'])\n"
                    "count.write_text(str(int(count.read_text()) + 1) if count.exists() else '1')\n"
                    "sys.exit(1)\n"
                )
                wrapper.chmod(0o700)
            process = subprocess.Popen(
                ["/bin/bash", str(script), str(root / "synthetic.conf")],
                env=dict(
                    os.environ,
                    PATH=f"{root}:{os.environ['PATH']}",
                    REDIS_CLEANUP_MARKER=str(marker),
                    REDIS_CLEANUP_STARTUP_FAIL="1" if startup_failure else "0",
                    REDIS_COMMAND_MARKER=str(command_marker),
                    REDIS_COMMAND_RELEASE=str(release),
                ),
                start_new_session=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            child_pid = None
            try:
                deadline = time.monotonic() + 10

                def reached_boundary():
                    if pause_command == "cat":
                        return command_marker.exists() or marker.exists()
                    return command_marker.exists() if pause_command else marker.exists()

                while not reached_boundary():
                    if process.poll() is not None or time.monotonic() > deadline:
                        self.fail(
                            f"Validator did not reach cleanup: {process.communicate(timeout=2)}"
                        )
                    time.sleep(0.01)
                [pidfile] = validator_root.glob("redis-config.*/redis-config-test.pid")
                child_pid = int(pidfile.read_text())
                # Redis is still alive after its first TERM: the EXIT trap is polling.
                if pause_command != "rm":
                    os.kill(child_pid, 0)
                for signum in (
                    ()
                    if removal_failure
                    else (
                        signal.SIGTERM,
                        signal.SIGINT,
                        signal.SIGTERM,
                        signal.SIGINT,
                    )
                ):
                    if process.poll() is None:
                        if process_group:
                            os.killpg(process.pid, signum)
                        else:
                            os.kill(process.pid, signum)
                    time.sleep(0.05)
                release.touch()
                stdout, stderr = process.communicate(timeout=10)
                if removal_failure:
                    self.assertEqual(len(list(validator_root.iterdir())), 1)
                    self.assertEqual(command_marker.read_text(), "3")
                    self.assertIn(b"Redis validation cleanup failed.", stderr)
                else:
                    self.assertEqual(list(validator_root.iterdir()), [])
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    try:
                        os.kill(child_pid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(0.02)
                else:
                    self.fail("Owned slow validator process survived cleanup")
                self.assertEqual(process.returncode, 1, (stdout, stderr))
                if pause_command == "cat":
                    self.assertFalse(
                        command_marker.exists(),
                        "Cleanup unexpectedly executed external cat",
                    )
                elif pause_command == "rm":
                    self.assertEqual(command_marker.read_text(), str(signal.SIG_IGN))
            finally:
                release.touch()
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=2)
                if child_pid is None:
                    pidfiles = list(
                        validator_root.glob("redis-config.*/redis-config-test.pid")
                    )
                    if pidfiles:
                        child_pid = int(pidfiles[0].read_text())
                if child_pid is not None:
                    try:
                        os.kill(child_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass


if __name__ == "__main__":
    unittest.main()
