#!/usr/bin/python3
"""Keep SMB shares mounted at their exact /Volumes path in the user's session.

Run by a LaunchAgent every few minutes. For each configured share it does one of:

- nothing, when the share is mounted from its server at exactly its mount point;
- nothing but a log line, when the mount point is taken by anything else, or the
  share is mounted somewhere else -- it never unmounts, renames or deletes;
- otherwise asks Finder's `mount volume` to mount it, with the credential the
  user's login keychain holds, and checks where it landed.

Only a change of a share's outcome is logged, so a healthy mount writes nothing.
Consumers of the share verify its identity themselves; this only restores it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

MOUNT_LINE = re.compile(
    r"^//(?:[^@/]+@)?(?P<server>[^/]+)/(?P<share>\S+) on (?P<point>.+) \((?P<fs>[^,)]+)"
)
MOUNT_TIMEOUT_SECONDS = 90


def mounts(text: str) -> list[dict[str, str]]:
    """The SMB-style entries of `/sbin/mount` output."""
    found = []
    for line in text.splitlines():
        match = MOUNT_LINE.match(line)
        if match:
            found.append(match.groupdict())
    return found


def classify(share: dict, entries: list[dict[str, str]], point_exists: bool) -> str:
    """What is true of one configured share right now.

    `mounted`: from its server at exactly its mount point. `elsewhere`: from its
    server, but at another point (typically `<point>-1`), which consumers refuse.
    `occupied`: the mount point exists and is not this share. `absent`: nothing
    there, so it may be mounted.
    """
    server, name, point = share["server"].casefold(), share["share"], share["mount_point"]
    ours = [
        entry for entry in entries
        if entry["fs"] == "smbfs" and entry["server"].casefold() == server and entry["share"] == name
    ]
    if any(entry["point"] == point for entry in ours):
        return "mounted"
    if ours:
        return "elsewhere"
    if point_exists:
        return "occupied"
    return "absent"


def mount_command(share: dict) -> list[str]:
    url = f"smb://{share['account']}@{share['server']}/{share['share']}"
    return ["/usr/bin/osascript", "-e", f'mount volume "{url}"']


def read_mounts() -> list[dict[str, str]]:
    result = subprocess.run(["/sbin/mount"], capture_output=True, text=True, check=True)
    return mounts(result.stdout)


def keep(share: dict, *, run=subprocess.run, read=read_mounts, exists=os.path.lexists) -> str:
    """Bring one share to `mounted` if that is safe; return its outcome."""
    state = classify(share, read(), exists(share["mount_point"]))
    if state != "absent":
        return state
    try:
        result = run(mount_command(share), capture_output=True, text=True, timeout=MOUNT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return "mount_timeout"
    if result.returncode != 0:
        return "mount_failed"
    after = classify(share, read(), exists(share["mount_point"]))
    return "remounted" if after == "mounted" else f"mount_{after}"


def main(config_path: str, state_path: str) -> int:
    config = json.loads(Path(config_path).read_text())
    state_file = Path(state_path)
    try:
        previous = json.loads(state_file.read_text())
    except (OSError, ValueError):
        previous = {}
    current = {}
    for share in config["shares"]:
        key = f"{share['server']}/{share['share']}"
        outcome = keep(share)
        # `remounted` is an event; as a state it is `mounted`.
        current[key] = "mounted" if outcome == "remounted" else outcome
        if outcome == "remounted" or previous.get(key) != current[key]:
            stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            print(f"{stamp} {key} at {share['mount_point']}: {outcome}", flush=True)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_file.with_suffix(".tmp")
    temporary.write_text(json.dumps(current, sort_keys=True))
    os.replace(temporary, state_file)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
