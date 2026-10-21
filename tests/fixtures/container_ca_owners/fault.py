"""Inject an unavailable trust source after preflight; test real owner recovery."""
import os as _fixture_os
from pathlib import Path as _FixturePath
import json
from pathlib import Path
import subprocess
import threading
import time

_fixture_name = _fixture_os.environ.get("CONTAINER_CA_OWNER_FIXTURE", "")
assert _fixture_name.startswith("container-ca-owner-systemd-")
assert _FixturePath("/run/container-ca-owner-fixture").read_text() == _fixture_name


projects = json.loads(Path("/fixture/projects.json").read_text())
first = projects[0]
managed = Path("/etc/systemd/system") / (
    first["owner"]["unit"] + ".d/90-managed-container-ca.conf"
)
bundle = Path(first["containers"][0]["store"]) / "bundle.pem"
held = bundle.with_suffix(".held")
injected = threading.Event()
finished = threading.Event()


def inject():
    while not finished.is_set():
        if managed.exists():
            bundle.rename(held)
            injected.set()
            return
        time.sleep(0.001)


started = time.time()
thread = threading.Thread(target=inject)
thread.start()
try:
    result = subprocess.run(
        [
            "python3",
            "/root/owner-tools/persist_owners.py",
            json.dumps(projects),
            "--apply",
        ],
        text=True,
        capture_output=True,
        timeout=180,
    )
finally:
    finished.set()
    thread.join()
    if held.exists():
        held.rename(bundle)
assert injected.is_set() and result.returncode != 0
receipt = max(Path("/var/lib/managed-container-ca/owner-activation").iterdir())
outcome = json.loads((receipt / "result.json").read_text())
assert outcome["status"] == "rolled_back" and not outcome["docker_restart_attempted"]
logs = list(receipt.glob("command-error-*.txt"))
assert logs and all(p.stat().st_mode & 0o777 == 0o600 for p in logs)
assert any("bundle.pem" in p.read_text() for p in logs)
assert (
    "bundle.pem" not in result.stderr
)  # Detailed native errors stay in private files.
for project in projects:
    row = json.loads(
        subprocess.check_output(
            ["docker", "inspect", project["containers"][0]["name"]], text=True
        )
    )[0]
    assert row["State"]["Running"]
    assert not any(m["Destination"] == "/run/managed-ca" for m in row["Mounts"])
    marker = Path(project["directory"]) / "data/marker"
    assert marker.read_text() == "preserve-" + marker.parent.parent.name
second = projects[1]["owner"]["unit"]
second_container = projects[1]["containers"][0]["name"]
journal = subprocess.check_output(
    [
        "journalctl",
        "--unit",
        second,
        "--since",
        "@" + str(started),
        "-o",
        "json",
        "--no-pager",
    ],
    text=True,
)
# Containerized journald does not necessarily record PID1's host/namespace identity.
# The real Compose command's own unit journal records each distinct successful start.
start_processes = {
    row["_PID"]
    for row in map(json.loads, journal.splitlines())
    if row.get("_SYSTEMD_UNIT") == second
    and row.get("MESSAGE", "").split() == ["Container", second_container, "Started"]
}
assert (
    len(start_processes) >= 2
)  # Activation tries owner2, then recovery tries it again.
print(
    json.dumps(
        {
            "status": outcome["status"],
            "first_owner_failure_injected": True,
            "remaining_owner_started_during_activation_and_recovery": True,
            "all_original_owners_running": True,
            "original_data_preserved": True,
            "private_native_journal_diagnostics_0600": True,
            "docker_restart_attempted": False,
        },
        indent=2,
    )
)
