#!/usr/bin/env python3
"""Opt-in real systemd + nested Docker/Compose owner lifecycle regression."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid

REPO = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ansible-playbook", default=shutil.which("ansible-playbook"))
    args = parser.parse_args()
    if not args.ansible_playbook:
        raise SystemExit("Requires ansible-playbook and community.docker collection")
    endpoint = os.environ.get("DOCKER_HOST")
    if not endpoint:
        context = json.loads(
            subprocess.check_output(["docker", "context", "inspect"], text=True)
        )[0]
        endpoint = context["Endpoints"]["docker"]["Host"]
    if not endpoint.startswith("unix://"):
        raise SystemExit("Fixture requires a local Unix Docker endpoint")
    scratch = Path(tempfile.mkdtemp(prefix="container-ca-owner-systemd-"))
    name = "container-ca-owner-systemd-" + uuid.uuid4().hex[:12]
    fixture_image = "geerlingguy/docker-ubuntu2404-ansible:latest"
    workload_image = "python:3.14.8-slim"
    result = {"fixture": name, "scratch": str(scratch), "cases": []}

    def run(argv, label, timeout=300):
        command = subprocess.run(argv, text=True, capture_output=True, timeout=timeout)
        (scratch / (label + ".log")).write_text(command.stdout + command.stderr)
        if command.returncode:
            raise RuntimeError(label + " failed; see " + str(scratch))
        return command.stdout

    def inside(argv, label, timeout=300):
        return run(["docker", "exec", name, *argv], label, timeout)

    def copy(source, target):
        run(
            ["docker", "cp", str(source), name + ":" + target],
            "copy-" + Path(target).name,
        )

    try:
        for key, image in [
            ("fixture_image", fixture_image),
            ("workload_image", workload_image),
        ]:
            result[key] = run(
                ["docker", "image", "inspect", image, "--format", "{{.Id}}"], key
            ).strip()
        run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "--pull",
                "never",
                "--privileged",
                "--cgroupns",
                "host",
                "--tmpfs",
                "/run",
                "--tmpfs",
                "/tmp",
                "-v",
                "/sys/fs/cgroup:/sys/fs/cgroup:rw",
                "-e",
                "container=docker",
                "-e",
                "CONTAINER_CA_OWNER_FIXTURE=" + name,
                "-e",
                "SYSTEMD_LOG_TARGET=console",
                "--entrypoint",
                "/sbin/init",
                fixture_image,
            ],
            "boot",
        )
        deadline = time.monotonic() + 60
        while True:
            ready = subprocess.run(
                ["docker", "exec", name, "systemctl", "is-system-running"],
                capture_output=True,
                text=True,
            )
            if ready.stdout.strip() in ("running", "degraded"):
                break
            if time.monotonic() > deadline:
                raise RuntimeError("Actual systemd did not boot")
            time.sleep(0.2)
        inside(
            [
                "python3",
                "-c",
                "import os;from pathlib import Path;Path('/run/container-ca-owner-fixture').write_text(os.environ['CONTAINER_CA_OWNER_FIXTURE'])",
            ],
            "fixture-marker",
        )
        inside(
            [
                "bash",
                "-c",
                "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends docker.io docker-compose-v2",
            ],
            "fixture-packages",
        )
        docker_unit = "[Unit]\nDescription=Isolated nested test Docker\n[Service]\nType=notify\nExecStart=/usr/bin/dockerd --host=unix:///var/run/docker.sock --storage-driver=vfs --iptables=false --bridge=none --ip-forward=false --ip-masq=false\nTimeoutStartSec=90\n[Install]\nWantedBy=multi-user.target\n"
        unit_source = scratch / "docker.service"
        unit_source.write_text(docker_unit)
        copy(unit_source, "/etc/systemd/system/docker.service")
        inside(["systemctl", "daemon-reload"], "nested-daemon-reload")
        inside(["systemctl", "start", "docker.service"], "nested-daemon-start")
        save = subprocess.Popen(
            ["docker", "save", workload_image],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            loaded = subprocess.run(
                ["docker", "exec", "-i", name, "docker", "load"],
                stdin=save.stdout,
                capture_output=True,
                timeout=180,
            )
            save.stdout.close()
            save.wait(timeout=30)
            if save.returncode or loaded.returncode:
                raise RuntimeError("Existing local workload image transfer failed")
        finally:
            if save.poll() is None:
                save.kill()
                save.wait()
        inside(["mkdir", "-p", "/root/owner-tools"], "tools-directory")
        for source in [
            REPO / "roles/container_ca_activate/files/activate.py",
            REPO / "roles/container_ca_activate/files/persist_owners.py",
            REPO / "tests/fixtures/activation-ca.txt",
        ]:
            copy(source, "/root/owner-tools/" + source.name)
        for source in (REPO / "tests/fixtures/container_ca_owners").glob("*.py"):
            copy(source, "/root/owner-tools/" + source.name)
        inside(["python3", "/root/owner-tools/setup.py"], "setup")
        projects = json.loads(
            inside(["cat", "/fixture/projects.json"], "project-specification")
        )
        collection = scratch / "collections/ansible_collections/local"
        collection.mkdir(parents=True)
        (collection / "ops_library").symlink_to(REPO, target_is_directory=True)
        inventory = scratch / "inventory"
        inventory.write_text(
            "[fixture]\n"
            + name
            + " ansible_connection=community.docker.docker ansible_python_interpreter=/usr/bin/python3\n"
        )
        play = scratch / "play.json"
        play.write_text(
            json.dumps(
                [
                    {
                        "hosts": "fixture",
                        "gather_facts": False,
                        "vars": {"container_ca_activate_projects": projects},
                        "tasks": [
                            {
                                "name": "Exercise owner entrypoint",
                                "ansible.builtin.include_role": {
                                    "name": "local.ops_library.container_ca_activate",
                                    "tasks_from": "persist_owners",
                                },
                            }
                        ],
                    }
                ]
            )
        )
        config = scratch / "ansible.cfg"
        config.write_text("[defaults]\n")
        env = dict(
            os.environ,
            ANSIBLE_CONFIG=str(config),
            ANSIBLE_COLLECTIONS_PATH=str(scratch / "collections")
            + ":"
            + str(Path.home() / ".ansible/collections"),
        )
        for label, flags in [
            ("loader-check", ["--check"]),
            ("loader-apply", []),
            ("loader-repeat", []),
        ]:
            call = subprocess.run(
                [args.ansible_playbook, "-i", str(inventory), str(play), *flags],
                env=env,
                text=True,
                capture_output=True,
                timeout=300,
            )
            (scratch / (label + ".log")).write_text(call.stdout + call.stderr)
            if call.returncode:
                raise RuntimeError(label + " failed; see " + str(scratch))
            result["cases"].append(label)
        result["lifecycle"] = json.loads(
            inside(["python3", "/root/owner-tools/lifecycle.py"], "lifecycle")
        )
        result["reconcile"] = json.loads(
            inside(["python3", "/root/owner-tools/reconcile.py"], "explicit-reconcile")
        )
        inside(["python3", "/root/owner-tools/reset.py"], "reset-originals")
        result["recovery"] = json.loads(
            inside(["python3", "/root/owner-tools/fault.py"], "fault-recovery")
        )
    finally:
        cleanup = subprocess.run(
            ["docker", "rm", "-f", "--volumes", name], capture_output=True, text=True
        )
        result["cleanup_exit"] = cleanup.returncode
        result["remaining_fixture"] = (
            subprocess.run(["docker", "inspect", name], capture_output=True).returncode
            == 0
        )
        (scratch / "result.json").write_text(json.dumps(result, indent=2))
        print(scratch / "result.json")


if __name__ == "__main__":
    main()
