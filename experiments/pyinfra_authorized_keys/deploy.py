"""Bounded trial equivalent; loaded only by Pyinfra in the disposable container."""
import io
import json
import os
from pathlib import Path

from pyinfra.operations import files

if os.environ.get("PYINFRA_TRIAL_CONTAINER") != "1" or not Path("/.dockerenv").exists():
    raise RuntimeError("This trial only runs inside its disposable Docker container")
config = json.loads(Path("/tmp/trial-config.json").read_text())
if config["enabled"]:
    for field in ("user", "group", "home"):
        if not config[field].strip():
            raise ValueError(f"{field} must be set")
    if not config["entries"]:
        raise ValueError("entries cannot be empty")
    for entry in config["entries"]:
        if not str(entry.get("key", "")).strip():
            raise ValueError("entry must define a non-empty key")
    lines = ["# Managed by Ansible - local.ops_library.ssh_authorized_keys_manage"]
    for entry in config["entries"]:
        parts = [
            str(entry.get(field, "")).strip()
            for field in ("key_options", "key", "comment")
        ]
        lines.append(" ".join(part for part in parts if part))
    directory = config["home"] + "/.ssh"
    files.directory(
        path=directory, user=config["user"], group=config["group"], mode="700"
    )
    # Public keys only: generic uploads MUST NOT be reused for plaintext secrets.
    files.put(
        src=io.StringIO("\n".join(lines) + "\n"),
        dest=directory + "/authorized_keys",
        user=config["user"],
        group=config["group"],
        mode="600",
    )
