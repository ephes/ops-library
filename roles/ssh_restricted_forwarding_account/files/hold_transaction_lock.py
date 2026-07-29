#!/usr/bin/env python3
"""Hold a server transaction with durable crash exclusion and fencing."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import hmac
import importlib.util
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

_FENCE_PATH = Path(__file__).with_name("manage_fence.py")
_FENCE_SPEC = importlib.util.spec_from_file_location(
    "server_transaction_fence", _FENCE_PATH
)
if _FENCE_SPEC is None or _FENCE_SPEC.loader is None:  # pragma: no cover
    raise RuntimeError("cannot load server fencing helper")
manage_fence = importlib.util.module_from_spec(_FENCE_SPEC)
_FENCE_SPEC.loader.exec_module(manage_fence)


class LockError(RuntimeError):
    """The transaction lock could not be safely acquired or attested."""


def _released(path: Path, token: str) -> bool:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return False
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            return False
        payload = os.read(descriptor, 4096)
        return payload == f"{token}\n".encode()
    finally:
        os.close(descriptor)


def _process_start_token(pid: int) -> str | None:
    try:
        value = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except FileNotFoundError:
        value = ""
    except OSError as exc:
        raise LockError("cannot attest transaction holder") from exc
    if value:
        closing = value.rfind(")")
        fields = value[closing + 2 :].split()
        if len(fields) >= 20:
            return f"proc:{fields[19]}"
    completed = subprocess.run(
        ["/bin/ps", "-o", "lstart=", "-p", str(pid)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    token = " ".join(completed.stdout.split())
    return f"ps:{token}" if completed.returncode == 0 and token else None


def _read_marker(path: Path) -> dict[str, object] | None:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise LockError(
                "durable transaction marker is not canonical owner-only state"
            )
        with os.fdopen(descriptor, encoding="utf-8") as source:
            descriptor = -1
            payload = json.load(source)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    required = {
        "version",
        "state",
        "holder_host",
        "holder_pid",
        "holder_start_token",
        "generation",
        "fencing_token",
        "recovery_token_sha256",
    }
    if (
        not isinstance(payload, dict)
        or set(payload) != required
        or payload.get("version") != 1
        or payload.get("state") != "unreleased"
        or not isinstance(payload.get("holder_host"), str)
        or not payload["holder_host"]
        or type(payload.get("holder_pid")) is not int
        or int(payload["holder_pid"]) < 1
        or not isinstance(payload.get("holder_start_token"), str)
        or not payload["holder_start_token"]
        or type(payload.get("generation")) is not int
        or int(payload["generation"]) < 1
        or not isinstance(payload.get("fencing_token"), str)
        or not payload["fencing_token"]
        or not isinstance(payload.get("recovery_token_sha256"), str)
        or len(str(payload["recovery_token_sha256"])) != 64
    ):
        raise LockError("durable transaction marker payload is invalid")
    return payload


def _require_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent = path.lstat()
    if (
        not stat.S_ISDIR(parent.st_mode)
        or stat.S_ISLNK(parent.st_mode)
        or parent.st_uid != os.geteuid()
        or stat.S_IMODE(parent.st_mode) != 0o700
    ):
        raise LockError("transaction state directory is not canonical owner-only state")


def _write_marker(path: Path, payload: dict[str, object]) -> None:
    _require_private_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_credential(path: Path) -> list[str] | None:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise LockError("recovery credential is not canonical owner-only state") from exc
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise LockError("recovery credential is not canonical owner-only state")
        with os.fdopen(descriptor, encoding="utf-8") as source:
            descriptor = -1
            payload = json.load(source)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if (
        not isinstance(payload, dict)
        or set(payload) != {"version", "tokens"}
        or payload.get("version") != 1
        or not isinstance(payload.get("tokens"), list)
        or not payload["tokens"]
        or any(not isinstance(token, str) or not token for token in payload["tokens"])
        or len(set(payload["tokens"])) != len(payload["tokens"])
    ):
        raise LockError("recovery credential payload is invalid")
    return payload["tokens"]


def _write_credential(path: Path, tokens: list[str]) -> None:
    _require_private_directory(path.parent)
    # Never replace an unsafe entry, even though rename itself would not follow it.
    _read_credential(path)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump({"version": 1, "tokens": list(dict.fromkeys(tokens))}, output)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _remove_credential(path: Path, expected_token: str | None = None) -> None:
    tokens = _read_credential(path)
    if tokens is None:
        if expected_token is not None:
            raise LockError("durable recovery credential is missing")
        return
    if expected_token is not None and expected_token not in tokens:
        raise LockError("durable recovery credential ownership changed")
    path.unlink()
    _fsync_directory(path.parent)


def _publish_ready(path: Path, release_token: str) -> None:
    _require_private_directory(path.parent)
    descriptor = os.open(
        path,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.write(descriptor, f"{release_token}\n".encode())
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)


def _attest_stale(
    existing: dict[str, object], recovery_token: str, credential_path: Path
) -> None:
    if not recovery_token:
        raise LockError("stale transaction recovery requires an authenticated token")
    supplied = hashlib.sha256(recovery_token.encode()).hexdigest()
    expected = str(existing["recovery_token_sha256"])
    if not hmac.compare_digest(supplied, expected):
        raise LockError("stale transaction recovery token is invalid")
    credentials = _read_credential(credential_path)
    if credentials is None or not any(
        hmac.compare_digest(recovery_token, token) for token in credentials
    ):
        raise LockError("stable recovery credential does not authenticate the marker")
    if existing["holder_host"] != socket.gethostname():
        raise LockError("cannot attest a transaction holder from another server")
    current = _process_start_token(int(existing["holder_pid"]))
    if current == existing["holder_start_token"]:
        raise LockError("prior server transaction holder is still active")


def _expected_marker(
    generation: int, fencing_token: str, release_token: str
) -> dict[str, object]:
    start_token = _process_start_token(os.getpid())
    if start_token is None:
        raise LockError("cannot attest current transaction holder")
    return {
        "version": 1,
        "state": "unreleased",
        "holder_host": socket.gethostname(),
        "holder_pid": os.getpid(),
        "holder_start_token": start_token,
        "generation": generation,
        "fencing_token": fencing_token,
        "recovery_token_sha256": hashlib.sha256(release_token.encode()).hexdigest(),
    }


def attest(
    marker_path: Path,
    fence_path: Path,
    generation: int,
    fencing_token: str,
) -> None:
    marker = _read_marker(marker_path)
    if marker is None:
        raise LockError("durable unreleased transaction marker is missing")
    if marker["generation"] != generation or marker["fencing_token"] != fencing_token:
        raise LockError("server transaction marker ownership changed")
    if (
        marker["holder_host"] != socket.gethostname()
        or _process_start_token(int(marker["holder_pid"]))
        != marker["holder_start_token"]
    ):
        raise LockError("server transaction holder is no longer active")
    manage_fence.manage(fence_path, generation, fencing_token, "check")


def hold(
    lock_path: Path,
    ready_path: Path,
    release_path: Path,
    timeout: int,
    release_token: str,
    *,
    marker_path: Path | None = None,
    fence_path: Path | None = None,
    generation: int = 1,
    fencing_token: str = "legacy-test-token",
    recover: bool = False,
    recovery_token: str = "",
    credential_path: Path | None = None,
) -> None:
    if not release_token:
        raise LockError("an authenticated release token is required")
    descriptor = os.open(
        lock_path,
        os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    deadline = time.monotonic() + timeout
    marker = marker_path or lock_path.with_suffix(".transaction.json")
    credential = credential_path or marker.with_suffix(".recovery.json")
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise LockError("server transaction lock is not canonical owner-only state")
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise LockError(
                        "server forwarding transaction lock did not become available"
                    )
                time.sleep(0.2)
        existing = _read_marker(marker)
        if existing is not None:
            if not recover:
                raise LockError(
                    "an unreleased server transaction marker exists; authenticated "
                    "stale-holder recovery is required"
                )
            _attest_stale(existing, recovery_token, credential)
            if generation <= int(existing["generation"]):
                raise LockError("recovery must advance the server fencing generation")
        elif recover:
            raise LockError("stale transaction recovery requested without a marker")
        else:
            # A crash after credential fsync but before marker publication leaves a
            # harmless orphan. Remove it durably while the stable lock is held.
            _remove_credential(credential)
        if fence_path is not None:
            manage_fence.manage(fence_path, generation, fencing_token, "claim")
        expected = _expected_marker(generation, fencing_token, release_token)
        if existing is None:
            # The durable plaintext credential must always precede its hashed marker.
            _write_credential(credential, [release_token])
            _write_marker(marker, expected)
        else:
            # During takeover retain both credentials across the marker switch. At
            # every crash boundary, the still-durable marker has a matching token.
            _write_credential(credential, [recovery_token, release_token])
            _write_marker(marker, expected)
            _write_credential(credential, [release_token])
        # Readiness is intentionally ephemeral and comes last. Its directory entry
        # is fsynced so a reported ready state attests both durable files above.
        _publish_ready(ready_path, release_token)
        while True:
            if _read_marker(marker) != expected:
                raise LockError("durable transaction marker ownership changed")
            if _released(release_path, release_token):
                if release_token not in (_read_credential(credential) or []):
                    raise LockError("durable recovery credential ownership changed")
                # Marker-first removal never leaves an unrecoverable marker. Each
                # directory update is separately durable; an orphan credential after
                # power loss is safely reclaimed by the next lock owner.
                marker.unlink()
                _fsync_directory(marker.parent)
                _remove_credential(credential, release_token)
                break
            time.sleep(0.1)
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=("hold", "check"), default="hold")
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--ready", type=Path)
    parser.add_argument("--release", type=Path)
    parser.add_argument("--timeout", type=int)
    parser.add_argument("--release-token")
    parser.add_argument("--marker", type=Path, required=True)
    parser.add_argument("--credential", type=Path)
    parser.add_argument("--fence", type=Path, required=True)
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument("--fencing-token", required=True)
    parser.add_argument("--recover-mode", choices=("true", "false"), default="false")
    parser.add_argument("--recovery-token", default="")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.action == "check":
            attest(args.marker, args.fence, args.generation, args.fencing_token)
        else:
            if None in (
                args.lock,
                args.ready,
                args.release,
                args.timeout,
                args.release_token,
                args.credential,
            ):
                raise LockError("hold action is missing lock control arguments")
            hold(
                args.lock,
                args.ready,
                args.release,
                args.timeout,
                args.release_token,
                marker_path=args.marker,
                fence_path=args.fence,
                generation=args.generation,
                fencing_token=args.fencing_token,
                recover=args.recover_mode == "true",
                recovery_token=args.recovery_token,
                credential_path=args.credential,
            )
    except (
        LockError,
        manage_fence.FenceError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
