"""Stub release archives of echoport-command-guard for the pins scenario.

    python3 -I make_stub_archives.py <dest-dir>

Writes <dest-dir>/<version>.tar.gz in the release layout (the binary and
LICENSE at the archive root) and <dest-dir>/sha256.json. Each binary is a
shell script that answers --version and --check-policy and, called as
`--shadow <policy> <python> -I <guard> <policy>`, execs the given Python guard
command, so every guarded SSH command still goes through the real Python
guard (rust/echoport-command-guard/PLAN.md 6.2). Kinds:

  ok       as above
  refuse   --shadow refuses everything (a post-probe through it fails)
  broken   every call exits 1 (rollback independence)
  corrupt  the archive is not a gzip file
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path

VERSIONS = {
    "0.0.1": "ok",  # X: named only by a manual authorized_keys line
    "0.1.0": "ok",  # A
    "0.2.0": "ok",  # B
    "0.3.0": "ok",  # C
    "0.4.0": "ok",  # D
    "0.5.0": "ok",  # E
    "0.6.0": "refuse",  # F
    "0.9.0": "broken",
    "0.9.1": "corrupt",
}

SCRIPT = """#!/bin/sh
# Stub echoport-command-guard {version} ({kind}) of the pins scenario.
case "$1" in
    --version)
        [ {kind} = broken ] && exit 1
        echo "echoport-command-guard {version} (stub)"
        exit 0 ;;
    --check-policy)
        [ {kind} = broken ] && exit 1
        [ $# -eq 2 ] && [ -f "$2" ] && exit 0
        exit 1 ;;
    --shadow)
        [ {kind} = broken ] && exit 1
        if [ {kind} = refuse ]; then
            echo "echoport-remote-command-guard: command not allowed" >&2
            exit 1
        fi
        [ $# -eq 6 ] && [ "$4" = -I ] && [ "$2" = "$6" ] || exit 2
        shift 2
        exec "$@" ;;
esac
exit 2
"""


def archive(version: str, kind: str) -> bytes:
    if kind == "corrupt":
        return b"not a gzip archive\n"
    members = {
        "echoport-command-guard": (SCRIPT.format(version=version, kind=kind).encode(), 0o755),
        "LICENSE": (b"MIT License (stub)\n", 0o644),
    }
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz", format=tarfile.GNU_FORMAT) as tar:
        for name, (data, mode) in members.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), mode, 0
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def main() -> None:
    dest = Path(sys.argv[1])
    dest.mkdir(parents=True, exist_ok=True)
    sums = {}
    for version, kind in VERSIONS.items():
        data = archive(version, kind)
        (dest / f"{version}.tar.gz").write_bytes(data)
        sums[version] = hashlib.sha256(data).hexdigest()
    (dest / "sha256.json").write_text(json.dumps(sums, indent=2) + "\n")


if __name__ == "__main__":
    main()
