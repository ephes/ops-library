#!/usr/bin/env python3
"""Persist and attest a monotonic forwarding-account fencing token."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path


class FenceError(RuntimeError):
    """A stale or unsafe fencing state was supplied."""


def _read(path: Path) -> dict[str, object] | None:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise FenceError("server fence is not canonical root-only state")
        with os.fdopen(descriptor, encoding="utf-8") as source:
            descriptor = -1
            payload = json.load(source)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("generation"), int)
        or payload["generation"] < 1
        or not isinstance(payload.get("token"), str)
        or not payload["token"]
    ):
        raise FenceError("server fence payload is invalid")
    return payload


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent_info = path.parent.lstat()
    if (
        not stat.S_ISDIR(parent_info.st_mode)
        or stat.S_ISLNK(parent_info.st_mode)
        or parent_info.st_uid != 0
        or stat.S_IMODE(parent_info.st_mode) != 0o700
    ):
        raise FenceError("server fence directory is not canonical root-only state")
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=".fence-")
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        parent_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        temporary.unlink(missing_ok=True)


def manage(path: Path, generation: int, token: str, action: str) -> dict[str, object]:
    if os.geteuid() != 0:
        raise FenceError("server fence helper must run as root")
    if generation < 1 or not token:
        raise FenceError(
            "a positive generation and nonempty fencing token are required"
        )
    existing = _read(path)
    if action == "claim":
        if existing is not None:
            prior_generation = int(existing["generation"])
            prior_token = str(existing["token"])
            if generation < prior_generation:
                raise FenceError("obsolete forwarding workflow generation")
            if generation == prior_generation and token != prior_token:
                raise FenceError("fencing token conflicts at the current generation")
        if existing != {"generation": generation, "token": token}:
            _write(path, {"generation": generation, "token": token})
    elif existing != {"generation": generation, "token": token}:
        raise FenceError("forwarding workflow lost server fencing ownership")
    return {
        "status": "claimed" if action == "claim" else "attested",
        "generation": generation,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=("claim", "check"), required=True)
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument("--token", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        print(
            json.dumps(
                manage(args.path, args.generation, args.token, args.action),
                sort_keys=True,
            )
        )
    except (FenceError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
