import os as _fixture_os
from pathlib import Path as _FixturePath
import json
import subprocess
import time
from pathlib import Path

_fixture_name = _fixture_os.environ.get("CONTAINER_CA_OWNER_FIXTURE", "")
assert _fixture_name.startswith("container-ca-owner-systemd-")
assert _FixturePath("/run/container-ca-owner-fixture").read_text() == _fixture_name

projects = json.loads(Path("/fixture/projects.json").read_text())
names = [p["containers"][0]["name"] for p in projects]
results = []
image = json.loads(
    subprocess.check_output(
        ["docker", "image", "inspect", "python:3.14.8-slim"], text=True
    )
)[0]["Id"]


def verify(case, memory="1536"):
    deadline = time.monotonic() + 90
    while True:
        p = subprocess.run(
            ["docker", "inspect", *names], text=True, capture_output=True
        )
        if p.returncode == 0:
            rows = json.loads(p.stdout)
            if all(r["State"]["Running"] for r in rows):
                break
        if time.monotonic() > deadline:
            raise RuntimeError("fixture readiness timeout")
        time.sleep(0.3)
    for r in rows:
        assert r["Image"] == image
        env = dict(x.split("=", 1) for x in r["Config"]["Env"])
        assert env["SSL_CERT_FILE"] == "/run/managed-ca/bundle.pem"
        assert env["APP_VALUE"] == "fixture-value-only"
        assert any(
            m["Destination"] == "/run/managed-ca" and not m["RW"] for m in r["Mounts"]
        )
        if "first" in r["Name"]:
            assert (
                env["NODE_OPTIONS"]
                == "--max-old-space-size=" + memory + " --use-openssl-ca"
            )
        else:
            assert env["NODE_OPTIONS"] == "--max-old-space-size=1536"
    for p in projects:
        marker = Path(p["directory"]) / "data/marker"
        assert marker.read_text() == "preserve-" + marker.parent.parent.name
        overlay = json.loads(
            (
                Path("/var/lib/managed-container-ca/owners")
                / p["owner"]["unit"]
                / "trust.json"
            ).read_text()
        )
        assert set(overlay["services"]["server"]) == {"environment", "volumes"}
        assert "APP_VALUE" not in overlay["services"]["server"]["environment"]
    results.append(
        {
            "case": case,
            "running": len(rows),
            "same_image": image,
            "data_preserved": True,
            "readonly_trust_mounts": True,
            "ca_only_no_image_or_app_snapshot": True,
        }
    )


verify("initial")
subprocess.run(["systemctl", "restart", "owner-c-first.service"], check=True)
verify("owner_restart")
source = Path("/fixture/first/compose.yml")
cfg = json.loads(source.read_text())
cfg["services"]["server"]["environment"]["NODE_OPTIONS"] = "--max-old-space-size=2048"
source.write_text(json.dumps(cfg))
subprocess.run(["systemctl", "reload", "owner-c-first.service"], check=True)
verify("owner_reload_dynamic_base", "2048")
before = subprocess.check_output(
    ["systemctl", "show", "docker", "--property=InvocationID", "--value"], text=True
).strip()
subprocess.run(["systemctl", "restart", "docker.service"], check=True)
verify("actual_nested_daemon_dependency_cycle", "2048")
after = subprocess.check_output(
    ["systemctl", "show", "docker", "--property=InvocationID", "--value"], text=True
).strip()
assert before != after
# Missing trust source must reject reload before native Compose can mutate either container.
ids = json.loads(subprocess.check_output(["docker", "inspect", *names], text=True))
ids = {r["Name"]: r["Id"] for r in ids}
bundle = Path("/fixture/first/store/bundle.pem")
bundle.rename(bundle.with_suffix(".held"))
try:
    result = subprocess.run(
        ["systemctl", "reload", "owner-c-first.service"], text=True, capture_output=True
    )
    assert result.returncode != 0
    now = json.loads(subprocess.check_output(["docker", "inspect", *names], text=True))
    assert {r["Name"]: r["Id"] for r in now} == ids
    results.append(
        {
            "case": "missing_store_reload",
            "failed_before_recreation": True,
            "both_container_ids_unchanged": True,
        }
    )
finally:
    bundle.with_suffix(".held").rename(bundle)
subprocess.run(["systemctl", "reset-failed", "owner-c-first.service"], check=True)
subprocess.run(["systemctl", "reload", "owner-c-first.service"], check=True)
verify("restored_store", "2048")
print(
    json.dumps(
        {"results": results, "fixture_only_docker_invocation_changed": True}, indent=2
    )
)
