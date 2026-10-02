"""Run the fixture using a pinned local daemon and an allowlisted temporary mount."""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import time
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MOUNT_FILES = (
    "experiments/pyinfra_authorized_keys/fixture.py",
    "experiments/pyinfra_authorized_keys/deploy.py",
    "roles/ssh_authorized_keys_manage/defaults/main.yml",
    "roles/ssh_authorized_keys_manage/tasks/main.yml",
    "roles/ssh_authorized_keys_manage/templates/authorized_keys.j2",
)


def local_endpoint(environment):
    """Resolve Docker's active endpoint, rejecting non-local transports before build."""
    # Reject explicit remote overrides even if another context would shadow them.
    for key in ("DOCKER_HOST", "BUILDKIT_HOST"):
        value = environment.get(key)
        if value and not value.startswith("unix:///"):
            raise RuntimeError(f"{key} must identify a local Unix socket")
    if environment.get("DOCKER_HOST") and not environment.get("DOCKER_CONTEXT"):
        endpoint = environment["DOCKER_HOST"]
    else:
        command = [
            "docker",
            "context",
            "inspect",
            "--format",
            "{{json .Endpoints.docker.Host}}",
        ]
        if environment.get("DOCKER_CONTEXT"):
            command.append(environment["DOCKER_CONTEXT"])
        result = subprocess.run(
            command,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        endpoint = json.loads(result.stdout)
    if not isinstance(endpoint, str) or not endpoint.startswith("unix:///"):
        raise RuntimeError(
            "Docker trial requires a local Unix socket; SSH/TCP contexts are refused"
        )
    socket = Path(endpoint.removeprefix("unix://"))
    if not stat.S_ISSOCK(socket.stat().st_mode):
        raise RuntimeError("Docker endpoint is not a local Unix socket")
    return endpoint


def docker_environment(environment):
    # Legacy build stays on the pinned daemon, bypassing selected buildx builders.
    cleaned = {
        key: value
        for key, value in environment.items()
        if not key.startswith(("DOCKER_", "BUILDX_", "BUILDKIT_"))
    }
    cleaned["DOCKER_BUILDKIT"] = "0"
    return cleaned


def stage(root, destination):
    """Copy only known fixture/role files; never traverse source symlinks."""
    for relative in (*MOUNT_FILES, "experiments/pyinfra_authorized_keys/Dockerfile"):
        source = root / relative
        for part in (source, *source.parents):
            if part == root.parent:
                break
            if part.is_symlink():
                raise RuntimeError(f"Refusing symlink in trial source: {relative}")
        if not source.is_file():
            raise RuntimeError(f"Missing trial source: {relative}")
        target = (
            destination / "build" / "Dockerfile"
            if relative.endswith("Dockerfile")
            else destination / "mount" / relative
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def main():
    endpoint = local_endpoint(dict(os.environ))
    environment = docker_environment(dict(os.environ))
    docker = ["docker", "--host", endpoint]
    suffix = uuid.uuid4().hex[:12]
    tag = "ops-pyinfra-trial:" + suffix
    name = "ops-pyinfra-trial-" + suffix
    scratch = ROOT / "tmp" / "pyinfra-trial"
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stage-", dir=scratch) as directory:
        staged = Path(directory)
        stage(ROOT, staged)
        start = time.monotonic()
        subprocess.run(
            docker + ["build", "-t", tag, str(staged / "build")],
            env=environment,
            check=True,
            timeout=900,
        )
        build_seconds = time.monotonic() - start
        try:
            result = subprocess.run(
                docker
                + [
                    "run",
                    "--name",
                    name,
                    "--network",
                    "none",
                    "--mount",
                    f"type=bind,src={staged / 'mount'},dst=/repo,readonly",
                    tag,
                    "python",
                    "/repo/experiments/pyinfra_authorized_keys/fixture.py",
                ],
                env=environment,
                text=True,
                capture_output=True,
                timeout=120,
            )
            if result.returncode:
                raise RuntimeError(result.stdout + result.stderr)
            evidence = json.loads(result.stdout)
            evidence["build_seconds"] = round(build_seconds, 3)
            print(json.dumps(evidence, indent=2))
        finally:
            subprocess.run(
                docker + ["rm", "-f", name],
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )


if __name__ == "__main__":
    main()
