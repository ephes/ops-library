#!/usr/bin/env python3
"""Render an isolated Vector pipeline; does not launch or install anything."""

from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path
from urllib.parse import urlsplit


def secret_directory(data_dir):
    """Keep credentials separate from buffers that may need diagnostic copying."""
    path = Path(data_dir)
    return path.with_name(path.name + "-secrets")


def check_existing_secret_paths(directory):
    # Configs may be generated before enrollment. Check existing paths only;
    # operators must also protect any credential provisioned later.
    for path, is_directory in ((directory, True), (directory / "writer", False)):
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ValueError("cannot inspect existing secret path") from exc
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("secret paths must not be symlinks")
        expected_type = stat.S_ISDIR if is_directory else stat.S_ISREG
        if not expected_type(info.st_mode):
            raise ValueError("unexpected secret path type")
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError(
                "existing secret paths must be owner-only and caller-owned"
            )


def configuration(spool, data_dir, endpoint):
    url = urlsplit(endpoint)
    if url.username or url.password or url.fragment or url.query or not url.hostname:
        raise ValueError("endpoint must not contain credentials, query or fragment")
    if url.scheme != "https" and not (
        url.scheme == "http" and url.hostname in ("127.0.0.1", "localhost", "::1")
    ):
        raise ValueError("HTTPS required except for local loopback tests")
    for path in (spool, data_dir):
        if not Path(path).is_absolute():
            raise ValueError("absolute private spool/data paths required")
        if any(char in str(path) for char in "*?[]${}"):
            raise ValueError("literal paths required")
    spool_path, data_path = Path(spool).resolve(), Path(data_dir).resolve()
    if (
        spool_path == data_path
        or spool_path in data_path.parents
        or data_path in spool_path.parents
    ):
        raise ValueError("spool and data directories must not overlap")
    secrets = secret_directory(data_path)
    if (
        secrets == spool_path
        or secrets in spool_path.parents
        or spool_path in secrets.parents
    ):
        raise ValueError("secret directory and spool must not overlap")
    check_existing_secret_paths(secrets)
    return {
        "data_dir": str(data_dir),
        "secret": {
            "inventory_writer": {
                "type": "directory",
                "path": str(secrets),
                "remove_trailing_whitespace": True,
            }
        },
        "sources": {
            "inventory_files": {
                "type": "file",
                "include": [str(Path(spool) / "*.ndjson")],
                "read_from": "beginning",
                "max_line_bytes": 8388608,
                "glob_minimum_cooldown_ms": 1000,
                "fingerprint": {"strategy": "checksum", "lines": 1},
            }
        },
        "transforms": {
            "inventory_decode": {
                "type": "remap",
                "inputs": ["inventory_files"],
                "source": ". = parse_json!(.message)",
                "drop_on_error": True,
                "reroute_dropped": True,
            }
        },
        "sinks": {
            "inventory_http": {
                "type": "http",
                "inputs": ["inventory_decode"],
                "uri": endpoint,
                "method": "post",
                "encoding": {"codec": "json"},
                "auth": {
                    "strategy": "bearer",
                    "token": "SECRET[inventory_writer.writer]",
                },
                "healthcheck": {"enabled": False},
                "acknowledgements": {"enabled": True},
                "batch": {"max_events": 1, "max_bytes": 12000000, "timeout_secs": 1},
                "buffer": {"type": "disk", "max_size": 268435488, "when_full": "block"},
                "request": {"concurrency": 1, "timeout_secs": 30},
            },
            "inventory_invalid": {
                "type": "file",
                "inputs": ["inventory_decode.dropped"],
                "path": str(Path(data_dir) / "invalid.ndjson"),
                "encoding": {"codec": "json"},
            },
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spool", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = configuration(args.spool, args.data_dir, args.endpoint)
    # Exclusive create protects existing and live Vector configurations.
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(data, output, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
