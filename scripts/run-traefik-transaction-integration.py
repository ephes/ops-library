"""Run the disposable ARM64/systemd transaction fixture with local release archives."""

import argparse
import shutil
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "artifacts",
    type=Path,
    help="directory containing 3.5.3/ and 3.7.12/ ARM64 archives",
)
args = parser.parse_args()
if not shutil.which("docker"):
    raise SystemExit("Docker is required for the disposable transaction fixture")
for release in ("3.5.3", "3.7.12"):
    archive = args.artifacts / release / f"traefik_v{release}_linux_arm64.tar.gz"
    if not archive.is_file():
        raise SystemExit(f"Missing integration artifact: {archive}")
root = Path(__file__).resolve().parents[1]
container = subprocess.check_output(
    [
        "docker",
        "run",
        "-d",
        "--network",
        "none",
        "--privileged",
        "--cgroupns=host",
        "-v",
        "/sys/fs/cgroup:/sys/fs/cgroup:rw",
        "--tmpfs",
        "/run",
        "--tmpfs",
        "/tmp",
        "-v",
        f"{root}:/source:ro",
        "-v",
        f"{args.artifacts.resolve()}:/artifacts:ro",
        "geerlingguy/docker-ubuntu2404-ansible",
        "/sbin/init",
    ],
    text=True,
).strip()
try:
    subprocess.run(
        [
            "docker",
            "exec",
            "-e",
            "TRAEFIK_DISPOSABLE_TEST=1",
            container,
            "/usr/bin/python3",
            "/source/tests/integration/traefik_transaction_linux.py",
        ],
        check=True,
    )
finally:
    subprocess.run(
        ["docker", "rm", "-f", container], check=True, stdout=subprocess.DEVNULL
    )
