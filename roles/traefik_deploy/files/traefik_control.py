#!/usr/bin/env python3
"""Controller journal for the guarded Traefik Ansible entry."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import yaml


def write_json(path: Path, value: Any) -> None:
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def canonical(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def make_request(
    registry: dict[str, Any], host: str, action: str, supplied: dict[str, Any]
) -> dict[str, Any]:
    if registry.get("schema") != 1 or host not in registry["hosts"]:
        raise ValueError(
            "select exactly one canonical host from the transaction registry"
        )
    policy = dict(registry["hosts"][host])
    selected = policy.pop("desired_release")
    policy["host"] = host
    release = dict(registry["releases"][selected]["linux_amd64"])
    release.update(version=selected, arch="amd64")
    if action == "binary" and not registry["releases"][selected].get(
        "approval_reference"
    ):
        raise ValueError("selected release has no approval reference")
    result = dict(supplied)
    result.update(policy=policy, release=release, action=action)
    return result


def invoke(
    root: Path, request: dict[str, Any], directory: Path
) -> tuple[int, dict[str, Any]]:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    response = directory / "result.json"
    variables = directory / "vars.json"
    write_json(
        variables,
        {
            "target_host": request["policy"]["host"],
            "traefik_transaction_request": request,
            "traefik_transaction_result_path": str(response),
        },
    )
    result = subprocess.run(
        [
            "ansible-playbook",
            "-i",
            "inventories/prod/hosts.yml",
            "playbooks/traefik/transaction.yml",
            "-e",
            "@" + str(variables),
        ],
        cwd=root,
        check=False,
    )
    return (
        result.returncode,
        json.loads(response.read_text()) if response.exists() else {},
    )


def control(
    root: Path,
    registry: dict[str, Any],
    host: str,
    action: str,
    supplied: dict[str, Any],
    journal: Path,
) -> int:
    request = make_request(registry, host, action, supplied)
    journal.mkdir(parents=True, mode=0o700, exist_ok=True)
    if (
        journal.is_symlink()
        or journal.stat().st_uid != os.geteuid()
        or journal.stat().st_mode & 0o077
    ):
        raise ValueError("controller journal must be an owner-only directory")
    local = journal / f"{host}.json"
    with (journal / f"{host}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if local.is_symlink():
            raise ValueError("controller state cannot be a symlink")
        previous = json.loads(local.read_text()) if local.exists() else None
        request["controller_state"] = previous
        directory = journal / (host + "-" + str(uuid.uuid4()))
        directory.mkdir(mode=0o700)
        if action == "inspect":
            code, result = invoke(root, request, directory)
            result["controller_state"] = previous
            result["records_match"] = (
                "state" in result
                and not result.get("failed")
                and previous == result["state"]
            )
            result["host_state_digest"] = (
                canonical(result["state"]) if "state" in result else None
            )
            result["controller_record_digest"] = canonical(previous)
            write_json(directory / "inspection.json", result)
            print(json.dumps(result, indent=2, sort_keys=True))
            print("Inspection retained:", directory / "inspection.json")
            return code
        if action == "enroll" and previous is not None:
            raise ValueError("enrollment cannot overwrite a controller record")
        if action in ["binary", "alias"] and (
            not previous or previous.get("phase") != "clear"
        ):
            raise ValueError(
                "missing/pending/recovery controller record; inspect and reconcile first"
            )
        if action == "resume":
            # Only a reviewed resume can reconcile transport ambiguity. The caller
            # must bind the exact observed host state and local journal revision.
            if not previous or supplied.get("controller_record_digest") != canonical(
                previous
            ):
                raise ValueError(
                    "resume must bind the current controller record digest"
                )
            code, inspected = invoke(
                root, make_request(registry, host, "inspect", {}), directory / "inspect"
            )
            if code or supplied.get("host_state_digest") != canonical(
                inspected.get("state")
            ):
                raise ValueError(
                    "resume must bind the freshly observed host state digest"
                )
            request["controller_state"] = inspected["state"]
        required = ["evidence"]
        if action in ["binary", "alias"]:
            required += [
                "compatibility",
                "baseline_probe",
                "acceptance_probe",
                "cleanup_probe",
            ]
        if action == "alias":
            required += ["candidate_config_base64", "approved_binary_sha256"]
        if action == "resume":
            required += ["baseline_probe", "recovery_review_reference"]
        if any(key not in request for key in required):
            raise ValueError("incomplete window request; no pending record was created")
        if action != "resume":
            code, inspected = invoke(
                root,
                make_request(registry, host, "inspect", {}),
                directory / "preflight",
            )
            if code or "identity" not in inspected:
                raise ValueError(
                    "read-only host preflight failed; no pending record was created"
                )
            if inspected.get("state") != previous:
                raise ValueError("controller and host recovery records disagree")
            if request["evidence"].get("baseline") != inspected["identity"]:
                raise ValueError("window baseline does not match fresh observation")
        write_json(directory / "previous-controller.json", previous)
        write_json(
            local,
            {
                "schema": 1,
                "host": host,
                "phase": "pending",
                "revision": str(uuid.uuid4()),
                "updated_at": int(time.time()),
                "operation": action,
                "journal": str(directory),
            },
        )
        code, result = invoke(root, request, directory)
        returned = result.get("state")
        if (
            returned is not None
            and returned.get("host") == host
            and returned.get("schema") == 1
        ):
            write_json(local, returned)
        # No usable response intentionally leaves the controller pending. Do not
        # restore the previous clear record when the remote outcome is unknown.
        print("Transaction evidence:", directory)
        if result.get("error"):
            print("Refused:", result["error"])
        return code or (1 if result.get("failed") or returned is None else 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument(
        "--journal", type=Path, default=Path.home() / ".local/state/ops-control/traefik"
    )
    parser.add_argument(
        "action", choices=["inspect", "enroll", "binary", "alias", "resume"]
    )
    parser.add_argument("host")
    parser.add_argument("request", type=Path, nargs="?")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        supplied = json.loads(args.request.read_text()) if args.request else {}
        return control(
            args.root.resolve(),
            yaml.safe_load(args.registry.read_text()),
            args.host,
            args.action,
            supplied,
            args.journal,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("Refused:", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
