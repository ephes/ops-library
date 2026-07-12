#!/usr/bin/env python3
"""Persist durable USB replication attempt state for monitoring."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any


PRESENT_RESULTS = {"success", "failed"}
ALL_RESULTS = PRESENT_RESULTS | {"skipped_absent"}


def _load_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def record_state(
    path: Path,
    *,
    result: str,
    exit_code: int,
    device_path: str,
    pool: str,
    occurred_at: str | None = None,
    size_bytes: int | None = None,
    alloc_bytes: int | None = None,
    free_bytes: int | None = None,
) -> dict[str, Any]:
    if result not in ALL_RESULTS:
        raise ValueError(f"unsupported result: {result}")

    timestamp = occurred_at or datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    state = _load_state(path)
    state.update(
        {
            "version": 1,
            "device_path": device_path,
            "pool": pool,
            "last_attempt_at": timestamp,
            "last_attempt_result": result,
            "last_attempt_exit_code": exit_code,
        }
    )

    if result in PRESENT_RESULTS:
        state.update(
            {
                "last_present_attempt_at": timestamp,
                "last_present_attempt_result": result,
                "last_present_attempt_exit_code": exit_code,
            }
        )
        if result == "success":
            state["last_success_at"] = timestamp

        if size_bytes is not None and alloc_bytes is not None and free_bytes is not None:
            state.update(
                {
                    "last_known_size_bytes": size_bytes,
                    "last_known_alloc_bytes": alloc_bytes,
                    "last_known_free_bytes": free_bytes,
                    "last_known_used_ratio": alloc_bytes / size_bytes if size_bytes > 0 else None,
                    "last_known_observed_epoch": int(
                        datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
                    ),
                    "last_known_observed_iso": timestamp,
                }
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o644)
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
    return state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-path", required=True, type=Path)
    parser.add_argument("--result", required=True, choices=sorted(ALL_RESULTS))
    parser.add_argument("--exit-code", required=True, type=int)
    parser.add_argument("--device-path", required=True)
    parser.add_argument("--pool", required=True)
    parser.add_argument("--size-bytes", type=int)
    parser.add_argument("--alloc-bytes", type=int)
    parser.add_argument("--free-bytes", type=int)
    args = parser.parse_args()
    record_state(
        args.state_path,
        result=args.result,
        exit_code=args.exit_code,
        device_path=args.device_path,
        pool=args.pool,
        size_bytes=args.size_bytes,
        alloc_bytes=args.alloc_bytes,
        free_bytes=args.free_bytes,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
