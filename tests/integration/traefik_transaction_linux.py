"""Disposable ARM64/systemd integration fixture; never run on an inventory host."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import subprocess
import tarfile
import time
from pathlib import Path

if not __debug__:
    raise SystemExit("This verification fixture requires assertions enabled")

if os.environ.get("TRAEFIK_DISPOSABLE_TEST") != "1" or not Path("/.dockerenv").exists():
    raise SystemExit(
        "This fixture requires the explicitly marked disposable Docker container"
    )
if os.uname().machine != "aarch64":
    raise SystemExit("This fixture uses checksum-pinned ARM64 release artifacts")

spec = importlib.util.spec_from_file_location(
    "tx", "/source/roles/traefik_deploy/files/traefik_transaction.py"
)
assert spec and spec.loader
tx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tx)
os.umask(0o077)
versions = {
    "3.5.3": "7087deeed64b405fa520aecaf80390213092603dace1e2a3482ffc7980ff3392",  # pragma: allowlist secret (public release digest)
    "3.7.12": "c8d942f80be27c76a55ff483927b36e3be5b0b88299a177ec0882a1fa1c24374",  # pragma: allowlist secret (public release digest)
}
for release, checksum in versions.items():
    archive = Path(f"/artifacts/{release}/traefik_v{release}_linux_arm64.tar.gz")
    tx.require(tx.digest(archive) == checksum, "integration archive checksum mismatch")
    with tarfile.open(archive) as stream:
        member = stream.getmember("traefik")
        assert member.isfile()
        data = stream.extractfile(member).read()
        path = Path(f"/opt/traefik-{release}")
        path.write_bytes(data)
        path.chmod(0o755)

binary = Path("/usr/local/bin/traefik")
binary.write_bytes(Path("/opt/traefik-3.5.3").read_bytes())
binary.chmod(0o755)
dynamic = Path("/etc/traefik/dynamic")
dynamic.mkdir(parents=True)
acme = Path("/etc/traefik/acme.json")
acme.write_text('{"fixture":"preserve"}')
config = Path("/etc/traefik/traefik.toml")
before = b"""[global]
checkNewVersion=false
sendAnonymousUsage=false
[providers.file]
directory="/etc/traefik/dynamic"
watch=true
[entryPoints.web]
address="127.0.0.1:18080"
[entryPoints.secure]
address="127.0.0.1:18443"
"""
config.write_bytes(before)
config.chmod(0o644)
unit = Path("/etc/systemd/system/traefik.service")
unit.write_text(
    "[Unit]\nDescription=Disposable Traefik fixture\n[Service]\nExecStart=/usr/local/bin/traefik --configFile=/etc/traefik/traefik.toml\nRestart=no\n[Install]\nWantedBy=multi-user.target\n"
)
unit.chmod(0o644)
subprocess.run(["systemctl", "daemon-reload"], check=True)
subprocess.run(["systemctl", "start", "traefik"], check=True)
time.sleep(2)

probe = Path("/usr/local/bin/traefik-fixture-probe")
probe.write_text(
    """#!/usr/bin/python3
import urllib.request,urllib.error
try:
    urllib.request.urlopen('http://127.0.0.1:18080/', timeout=2)
except urllib.error.HTTPError as error:
    assert error.code == 404
else:
    raise SystemExit('expected empty fixture router 404')
"""
)
probe.chmod(0o755)
cleanup = Path("/usr/local/bin/traefik-fixture-cleanup")
cleanup.write_text(
    '#!/usr/bin/python3\nfrom pathlib import Path\nassert not list(Path("/etc/traefik/dynamic").iterdir())\n'
)
cleanup.chmod(0o755)
failed = Path("/usr/local/bin/traefik-fixture-fail")
failed.write_text("#!/usr/bin/python3\nraise SystemExit(1)\n")
failed.chmod(0o755)
policy = {
    "host": "fixture",
    "binary_path": str(binary),
    "config_path": str(config),
    "dynamic_path": str(dynamic),
    "alias_policy": {"web": "delete", "secure": "delete"},
    "backup_paths": [str(binary), "/etc/traefik", str(unit), str(acme)],
    "acme_paths": [str(acme)],
}


def command(path):
    return {"argv": [str(path)], "sha256": tx.digest(path)}


def request(action, state):
    live = tx.identity(policy)
    return {
        "action": action,
        "policy": policy,
        "controller_state": state,
        "evidence": {
            "baseline": live,
            "verified_at": int(time.time()),
            "owner": "disposable test",
            "review_reference": "integration fixture",
            "console_recovery": "container discard",
            "independent_observer": "test controller",
            "observer_delivery_test": "fixture assertions",
            "observer_watch_active": True,
        },
        "baseline_probe": command(probe),
        "acceptance_probe": command(probe),
        "cleanup_probe": command(cleanup),
        "compatibility": {
            "baseline": live,
            "architecture": os.uname().machine,
            "passed": True,
            "baseline_pair_passed": True,
            "report_reference": "disposable fixture",
            "candidate_binary_sha256": tx.digest(Path("/opt/traefik-3.7.12")),
            "candidate_config_sha256": tx.digest(config),
        },
        "release": {"version": "3.7.12", "sha256": versions["3.7.12"]},
        "archive_path": "/artifacts/3.7.12/traefik_v3.7.12_linux_arm64.tar.gz",
    }


# Exercise real prerequisite repairs before enrolling the disposable proxy.
prepare_engine = "/source/roles/traefik_deploy/files/traefik_prepare.py"


def preparation(payload, success=True):
    payload.update(
        machine_id=Path("/etc/machine-id").read_text().strip(),
        review_reference="disposable fixture",
    )
    request_path = Path("/tmp/preparation.json")
    request_path.write_text(json.dumps(payload))
    outcome = subprocess.run(
        ["/usr/bin/python3", prepare_engine, "--request", str(request_path)],
        capture_output=True,
        text=True,
    )
    assert (outcome.returncode == 0) == success, outcome.stderr
    return outcome


initial_pid = subprocess.check_output(
    ["systemctl", "show", "traefik", "-p", "MainPID", "--value"]
)
os.chown(binary, 1001, 115)
preparation(
    {
        "action": "ownership",
        "binary_path": str(binary),
        "binary_sha256": tx.digest(binary),
        "previous_owner": [1001, 115],
    }
)
assert binary.stat().st_uid == 0 and binary.stat().st_gid == 0
assert (
    subprocess.check_output(
        ["systemctl", "show", "traefik", "-p", "MainPID", "--value"]
    )
    == initial_pid
)
retired_home = Path("/home/retired/site")
retired_home.mkdir(parents=True)
retired_source = retired_home / "retired.service"
retired_source.write_text(
    "[Service]\nExecStart=/bin/sleep infinity\n[Install]\nWantedBy=multi-user.target\n"
)
retired_unit = Path("/etc/systemd/system/retired.service")
retired_unit.symlink_to(retired_source)
subprocess.run(["systemctl", "daemon-reload"], check=True)
retired_route = dynamic / "retired.traefik.yml"
retired_route.write_text("http: {}\n")
retired_route.chmod(0o644)
retired_candidate = {
    "http": {
        "middlewares": {
            "retained": {"headers": {"customResponseHeaders": {"X-Fixture": "kept"}}}
        }
    }
}
retired_original = json.dumps(
    {"http": {"middlewares": retired_candidate["http"]["middlewares"], "routers": {}}}
)
retired_route.write_text(retired_original)
# Refused preconditions must preserve both route bytes and the source unit.
refusal_request = {
    "action": "retire",
    "service": "retired",
    "unit_target": str(retired_source),
    "route_sha256": tx.digest(retired_route),
    "verified_middlewares": retired_candidate["http"]["middlewares"],
    "candidate_base64": base64.b64encode(
        json.dumps(retired_candidate).encode()
    ).decode(),
}
for fault in ("active", "route-drift", "candidate-shape", "middleware-change"):
    rejected = dict(refusal_request)
    if fault == "active":
        subprocess.run(["systemctl", "start", "retired"], check=True)
    elif fault == "route-drift":
        rejected["route_sha256"] = "0" * 64
    elif fault == "candidate-shape":
        rejected["candidate_base64"] = base64.b64encode(
            b'{"http":{"routers":{}}}'
        ).decode()
    else:
        rejected["verified_middlewares"] = {}
    preparation(rejected, success=False)
    assert retired_route.read_text() == retired_original and retired_source.is_file()
    assert os.readlink(retired_unit) == str(retired_source)
    if fault == "active":
        subprocess.run(["systemctl", "stop", "retired"], check=True)
    # Unresolved journal refuses even a now-valid request.
    refused = preparation(refusal_request, success=False)
    assert "unresolved preparation" in refused.stderr
    # Disposable test reconciliation after the assertions above; retain evidence.
    for pending in Path("/var/lib/traefik-preparation").glob("*/pending.json"):
        assert not pending.with_name("fixture-reconciled.json").exists()
        pending.rename(pending.with_name("fixture-reconciled.json"))

preparation(
    {
        "action": "retire",
        "service": "retired",
        "unit_target": str(retired_source),
        "route_sha256": tx.digest(retired_route),
        "verified_middlewares": retired_candidate["http"]["middlewares"],
        "candidate_base64": base64.b64encode(
            json.dumps(retired_candidate).encode()
        ).decode(),
    }
)
assert json.loads(retired_route.read_text()) == retired_candidate
assert retired_source.is_file() and os.readlink(retired_unit) == "/dev/null"
assert (
    subprocess.check_output(
        ["systemctl", "show", "traefik", "-p", "MainPID", "--value"]
    )
    == initial_pid
)
# The test's empty-router cleanup contract owns this disposable fixture route.
retired_route.unlink()

state = tx.execute(request("enroll", None))["state"]
preparation(
    {
        "action": "ownership",
        "binary_path": str(binary),
        "binary_sha256": tx.digest(binary),
        "previous_owner": [0, 0],
    },
    success=False,
)
bad = request("binary", state)
bad["acceptance_probe"] = command(failed)
result = tx.execute(bad)
assert result["failed"] and result["state"]["phase"] == "recovery"
assert tx.identity(policy)["version"] == "3.5.3" and config.read_bytes() == before
assert acme.read_text() == '{"fixture":"preserve"}'
resume = request("resume", result["state"])
resume["recovery_review_reference"] = "fixture verified rollback"
state = tx.execute(resume)["state"]
result = tx.execute(request("binary", state))
assert not result.get("failed")
state = result["state"]
assert tx.identity(policy)["version"] == "3.7.12"
alias = request("alias", state)
after = (
    before
    + b'[entryPoints.web.http]\naliasHeadersStrategy="delete"\n[entryPoints.secure.http]\naliasHeadersStrategy="delete"\n'
)
alias.update(
    candidate_config_base64=base64.b64encode(after).decode(),
    approved_binary_sha256=tx.digest(binary),
)
alias["compatibility"]["candidate_config_sha256"] = hashlib.sha256(after).hexdigest()
result = tx.execute(alias)
assert not result.get("failed")
assert config.read_bytes() == after and acme.read_text() == '{"fixture":"preserve"}'
pid = subprocess.check_output(
    ["systemctl", "show", "traefik", "-p", "MainPID", "--value"]
)
noop = request("alias", result["state"])
noop.update(
    candidate_config_base64=base64.b64encode(after).decode(),
    approved_binary_sha256=tx.digest(binary),
)
result = tx.execute(noop)
assert result["changed"] is False
assert (
    subprocess.check_output(
        ["systemctl", "show", "traefik", "-p", "MainPID", "--value"]
    )
    == pid
)
print(
    json.dumps(
        {
            "native_arch": os.uname().machine,
            "preparation_ownership_and_retirement": "verified",
            "binary_rollback": "verified",
            "binary_update": "3.7.12",
            "alias_update": "verified",
            "noop_pid_preserved": True,
            "acme_preserved": True,
        }
    )
)
