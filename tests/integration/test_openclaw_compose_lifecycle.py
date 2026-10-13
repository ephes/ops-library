"""Exercise the rendered service commands against an isolated real Compose stack."""

import json
import os
import shlex
import shutil
import subprocess
import sys
import uuid
import warnings
from pathlib import Path

import jinja2
import yaml

ROLE = Path(__file__).resolve().parents[2] / "roles" / "openclaw_deploy"


def test_service_restart_retains_proxy_bridge_identity(tmp_path: Path) -> None:
    docker = shutil.which("docker")
    assert docker, "The lifecycle integration check requires Docker"
    project = f"openclaw-lifecycle-{uuid.uuid4().hex[:12]}"
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text(
        yaml.safe_dump(
            {
                "name": project,
                "services": {
                    "probe": {
                        "image": os.environ.get(
                            "OPENCLAW_LIFECYCLE_TEST_IMAGE", "alpine:3.22"
                        ),
                        "command": ["sleep", "300"],
                    }
                },
            }
        )
    )
    template = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(
        (ROLE / "templates/openclaw.service.j2").read_text()
    )
    unit = template.render(openclaw_site_dir=str(tmp_path))
    commands = {}
    for line in unit.splitlines():
        if line.startswith(("ExecStart=", "ExecStop=")):
            name, command = line.split("=", 1)
            commands[name] = [docker, *shlex.split(command)[1:]]

    def run(argv: list[str]) -> str:
        result = subprocess.run(
            argv, check=False, capture_output=True, text=True, timeout=180
        )
        if result.returncode:
            error = subprocess.CalledProcessError(result.returncode, argv)
            error.add_note(result.stderr)
            raise error
        return result.stdout

    def bridge_identity() -> tuple[str, str]:
        network = json.loads(run([docker, "network", "inspect", f"{project}_default"]))[
            0
        ]
        return network["Id"], network["IPAM"]["Config"][0]["Gateway"]

    try:
        run(commands["ExecStart"])
        original = bridge_identity()
        for cycle in range(2):
            prior_container = run(
                [docker, "compose", "-f", str(compose_file), "ps", "-q", "probe"]
            ).strip()
            run(commands["ExecStop"])
            assert bridge_identity() == original
            assert not run(
                [
                    docker,
                    "compose",
                    "-f",
                    str(compose_file),
                    "ps",
                    "-q",
                    "--status",
                    "running",
                ]
            ).strip()
            if cycle == 1:
                config = yaml.safe_load(compose_file.read_text())
                config["services"]["probe"]["environment"] = {"RECREATE": "yes"}
                compose_file.write_text(yaml.safe_dump(config))
            run(commands["ExecStart"])
            if cycle == 1:
                assert (
                    run(
                        [
                            docker,
                            "compose",
                            "-f",
                            str(compose_file),
                            "ps",
                            "-q",
                            "probe",
                        ]
                    ).strip()
                    != prior_container
                )
            assert bridge_identity() == original
            assert run(
                [
                    docker,
                    "compose",
                    "-f",
                    str(compose_file),
                    "ps",
                    "-q",
                    "--status",
                    "running",
                ]
            ).strip()
    finally:
        primary_failure = sys.exc_info()[0] is not None
        result = subprocess.run(
            [docker, "compose", "-f", str(compose_file), "down", "--remove-orphans"],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode:
            if primary_failure:
                warnings.warn(
                    f"Compose cleanup also failed: {result.stderr}", stacklevel=2
                )
            else:
                raise AssertionError(f"Compose cleanup failed: {result.stderr}")
