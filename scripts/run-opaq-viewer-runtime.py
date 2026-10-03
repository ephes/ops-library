"""Run pinned synthetic lifecycle in a unique offline Linux VM container, no build/pull."""

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIGEST = "c8d942f80be27c76a55ff483927b36e3be5b0b88299a177ec0882a1fa1c24374"  # pragma: allowlist secret -- public release checksum
IMAGE = "sha256:08ebfac183e237444343fff0916cc5eb5ac9b4891626251e76890615c2dcd22e"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    if platform.system() != "Darwin":
        raise SystemExit("Established privileged fixture requires macOS Linux VM")
    # Reuse existing local-endpoint checks and scrub remote/build overrides.
    spec = importlib.util.spec_from_file_location(
        "redis_runner", ROOT / "tests/redis_validation/run.py"
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    endpoint = runner.local_endpoint(dict(os.environ))
    env = runner.docker_environment(dict(os.environ))
    docker = ["docker", "--host", endpoint]
    if hashlib.sha256(args.archive.read_bytes()).hexdigest() != DIGEST:
        raise SystemExit("Archive mismatch: nothing executed")
    image = subprocess.check_output(
        docker + ["image", "inspect", IMAGE, "--format", "{{.Id}}"], env=env, text=True
    ).strip()
    if (
        subprocess.check_output(
            docker + ["info", "--format", "{{.OSType}}"], env=env, text=True
        ).strip()
        != "linux"
    ):
        raise SystemExit("Linux VM required")
    # Actual reviewed admission before any container creation.
    subprocess.run(
        [
            "python3",
            "-I",
            str(ROOT / "roles/opaq_company_viewer_deploy/files/installer.py"),
            "--action",
            "admit",
            "--policy",
            str(ROOT / "offline/opaq-company-viewer/package.py"),
            "--bundle",
            str(args.bundle),
            "--proxy-group",
            "synthetic-proxy",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    name = "opaq-runtime-" + uuid.uuid4().hex[:12]
    scratch = ROOT / "tmp" / "opaq-runtime"
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stage-", dir=scratch) as directory:
        stage = Path(directory)
        shutil.copyfile(args.archive, stage / "traefik.tar.gz")
        shutil.copytree(args.bundle, stage / "bundle")
        files = [
            "tests/integration/opaq_viewer_linux.py",
            "offline/opaq-company-viewer/package.py",
            "offline/opaq-company-viewer/viewer.py",
        ]
        files += [
            "roles/opaq_company_viewer_deploy/"
            + str(p.relative_to(ROOT / "roles/opaq_company_viewer_deploy"))
            for p in (ROOT / "roles/opaq_company_viewer_deploy").rglob("*")
            if p.is_file()
        ]
        files += [
            "tests/fixtures/opaq_company_viewer/" + name
            for name in ("accepted.html", "no-accepted.html", "retained-last-good.html")
        ]
        for relative in files:
            source = ROOT / relative
            if any(p.is_symlink() for p in (source, *source.parents)):
                raise SystemExit("Source symlink refused")
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        try:
            subprocess.run(
                docker
                + [
                    "run",
                    "--pull=never",
                    "-d",
                    "--name",
                    name,
                    "--network",
                    "none",
                    "--privileged",
                    "--cgroupns",
                    "private",
                    "--tmpfs",
                    "/run",
                    "--tmpfs",
                    "/run/lock",
                    "--tmpfs",
                    "/tmp",
                    "--mount",
                    f"type=bind,src={stage},dst=/fixture,readonly",
                    "-e",
                    "OPAQ_DISPOSABLE_TEST=1",
                    image,
                ],
                env=env,
                check=True,
                stdout=subprocess.DEVNULL,
                timeout=30,
            )
            result = subprocess.run(
                docker
                + [
                    "exec",
                    name,
                    "python",
                    "/fixture/tests/integration/opaq_viewer_linux.py",
                ],
                env=env,
                check=False,
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode:
                raise RuntimeError(result.stdout + result.stderr)
            print(json.dumps(json.loads(result.stdout), indent=2))
        finally:
            subprocess.run(
                docker + ["rm", "-f", name],
                env=env,
                check=True,
                stdout=subprocess.DEVNULL,
                timeout=30,
            )


if __name__ == "__main__":
    main()
