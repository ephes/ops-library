import os as _fixture_os
from pathlib import Path as _FixturePath
import hashlib
import json
import subprocess
import shutil
from pathlib import Path

_fixture_name = _fixture_os.environ.get("CONTAINER_CA_OWNER_FIXTURE", "")
assert _fixture_name.startswith("container-ca-owner-systemd-")
assert _FixturePath("/run/container-ca-owner-fixture").read_text() == _fixture_name

image = json.loads(
    subprocess.check_output(
        ["docker", "image", "inspect", "python:3.14.8-slim"], text=True
    )
)[0]["Id"]
projects = []
if Path("/fixture").exists():
    shutil.rmtree("/fixture")
for name in ["first", "second"]:
    root = Path("/fixture") / name
    root.mkdir(parents=True)
    (root / "data").mkdir()
    (root / "data/marker").write_text("preserve-" + name)
    store = root / "store"
    store.mkdir()
    (store / "empty").mkdir()
    (store / "bundle.pem").write_bytes(
        Path("/root/owner-tools/activation-ca.txt").read_bytes()
    )
    (store / "manifest.json").write_text(json.dumps({"image": image}))
    source = root / "compose.yml"
    project = "owner-c-" + name
    container = project + "-server"
    source.write_text(
        json.dumps(
            {
                "services": {
                    "server": {
                        "image": "python:3.14.8-slim",
                        "container_name": container,
                        "command": ["python3", "-c", "import time;time.sleep(3600)"],
                        "network_mode": "none",
                        "environment": {
                            "NODE_OPTIONS": "--max-old-space-size=1536",
                            "APP_VALUE": "fixture-value-only",
                        },
                        "volumes": [str(root / "data") + ":/data"],
                    }
                }
            }
        )
    )
    argv = ["/usr/bin/docker", "compose", "-p", project, "-f", str(source)]
    owner = {
        "unit": project + ".service",
        "working_directory": str(root),
        "start": argv + ["up", "-d", "--remove-orphans"],
        "stop": argv + [("down" if name == "first" else "stop")],
        "reload": argv + ["up", "-d", "--remove-orphans"] if name == "first" else [],
    }
    unit = Path("/etc/systemd/system") / owner["unit"]
    unit.write_text(
        "[Unit]\nDescription=Isolated owner test\nRequires=docker.service\nAfter=docker.service\n[Service]\nType=oneshot\nRemainAfterExit=yes\nWorkingDirectory="
        + str(root)
        + "\n"
        + "\n".join(
            key + "=" + " ".join(owner[k])
            for key, k in [
                ("ExecStart", "start"),
                ("ExecStop", "stop"),
                ("ExecReload", "reload"),
            ]
            if owner[k]
        )
        + "\n[Install]\nWantedBy=docker.service\n"
    )
    owner["fragment_sha256"] = hashlib.sha256(unit.read_bytes()).hexdigest()
    projects.append(
        {
            "project": project,
            "directory": str(root),
            "files": [str(source)],
            "owner": owner,
            "containers": [
                {
                    "name": container,
                    "service": "server",
                    "store": str(store),
                    "node": name == "first",
                }
            ],
        }
    )
Path("/fixture/projects.json").write_text(json.dumps(projects))
subprocess.run(["systemctl", "daemon-reload"], check=True)
for p in projects:
    subprocess.run(["systemctl", "enable", "--now", p["owner"]["unit"]], check=True)
