import os as _fixture_os
from pathlib import Path as _FixturePath
import json
import subprocess
from pathlib import Path

_fixture_name = _fixture_os.environ.get("CONTAINER_CA_OWNER_FIXTURE", "")
assert _fixture_name.startswith("container-ca-owner-systemd-")
assert _FixturePath("/run/container-ca-owner-fixture").read_text() == _fixture_name

projects = json.loads(Path("/fixture/projects.json").read_text())
units = [p["owner"]["unit"] for p in projects]
for unit in units:
    subprocess.run(["systemctl", "stop", unit], check=True)
receipts = Path("/var/lib/managed-container-ca/owner-activation")
prior = next(
    p for p in sorted(receipts.iterdir()) if (p / "original-managed.json").exists()
)
for name, data in json.loads((prior / "original-managed.json").read_text()).items():
    p = Path(name)
    assert str(p).startswith(
        ("/var/lib/managed-container-ca/owners/", "/etc/systemd/system/owner-c-")
    )
    if data is None:
        p.unlink(missing_ok=True)
    else:
        p.write_bytes(bytes.fromhex(data))
subprocess.run(["systemctl", "daemon-reload"], check=True)
for unit in units:
    subprocess.run(["systemctl", "reset-failed", unit], check=True)
    subprocess.run(["systemctl", "start", unit], check=True)
