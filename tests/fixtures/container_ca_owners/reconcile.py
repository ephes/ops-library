"""Exercise an explicitly approved next tool version without app image changes."""
import os
from pathlib import Path
import json
import subprocess


name = os.environ.get("CONTAINER_CA_OWNER_FIXTURE", "")
assert name.startswith("container-ca-owner-systemd-")
assert Path("/run/container-ca-owner-fixture").read_text() == name
projects = Path("/fixture/projects.json").read_text()
tool = Path("/root/owner-tools/persist_owners.py")
tool.write_text(
    tool.read_text() + "\n# Fixture: simulated reviewed next tool version.\n"
)


def call(mode, approval=None):
    args = ["python3", str(tool), projects, mode]
    if approval is not None:
        args.append(json.dumps(approval))
    return subprocess.run(args, text=True, capture_output=True, timeout=180)


def ids():
    rows = json.loads(
        subprocess.check_output(
            ["docker", "inspect", "owner-c-first-server", "owner-c-second-server"],
            text=True,
        )
    )
    return {row["Name"]: row["Id"] for row in rows}


before = ids()
assert call("--check").returncode != 0
approved = json.loads(
    subprocess.check_output(
        ["python3", str(tool), "--managed-sha", projects], text=True
    )
)
assert len(approved) == 8
for invalid in [
    dict(list(approved.items())[1:]),
    {**approved, next(iter(approved)): "stale-proof"},
]:
    for mode in ("--check", "--apply"):
        assert call(mode, invalid).returncode != 0
        assert ids() == before
changed = call("--check", approved)
assert changed.returncode == 0 and changed.stdout.splitlines()[0] == "CHANGED"
assert ids() == before
applied = call("--apply", approved)
assert applied.returncode == 0 and applied.stdout.splitlines()[0] == "CHANGED"
repeated = call("--check")
assert repeated.returncode == 0 and repeated.stdout.splitlines()[0] == "UNCHANGED"
assert call("--check", approved).returncode != 0  # Old approval cannot be reused.
for project in json.loads(projects):
    row = json.loads(
        subprocess.check_output(
            ["docker", "inspect", project["containers"][0]["name"]], text=True
        )
    )[0]
    assert row["State"]["Running"]
    assert any(
        m["Destination"] == "/run/managed-ca" and not m["RW"] for m in row["Mounts"]
    )
    assert (
        Path(project["directory"]) / "data/marker"
    ).read_text() == "preserve-" + Path(project["directory"]).name
print(
    json.dumps(
        {
            "approved_tool_update": True,
            "changed_check_matches_apply": True,
            "repeat_unchanged": True,
            "stale_and_incomplete_approval_before_stop": True,
            "all_native_owners_running": True,
            "data_and_trust_preserved": True,
        },
        indent=2,
    )
)
