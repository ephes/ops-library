#!/usr/bin/env python3
"""Narrow, journaled repairs before first Traefik transaction enrollment."""

import argparse
import base64
import fcntl
import json
import os
import re
import stat
import uuid
from pathlib import Path

from traefik_transaction import (
    LOCK,
    STATE_ROOT,
    atomic,
    digest,
    require,
    run,
    save,
    trusted_file,
)


def pid():
    return int(
        run(
            ["systemctl", "show", "traefik.service", "-p", "MainPID", "--value"]
        ).strip()
    )


def repair_ownership(request, journal):
    binary = Path(request["binary_path"])
    require(
        str(binary) in {"/usr/bin/traefik", "/usr/local/bin/traefik"},
        "unsupported binary path",
    )
    for parent in binary.parents:
        info = parent.lstat()
        require(
            stat.S_ISDIR(info.st_mode)
            and info.st_uid == 0
            and not info.st_mode & 0o022,
            "unsafe binary parent",
        )
    descriptor = os.open(binary, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        require(
            stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o755,
            "unexpected binary metadata",
        )
        require(
            [info.st_uid, info.st_gid] == request["previous_owner"], "ownership drift"
        )
        require(
            digest(Path(f"/proc/self/fd/{descriptor}")) == request["binary_sha256"],
            "binary hash drift",
        )
        main_pid = pid()
        require(
            main_pid > 1 and os.readlink(f"/proc/{main_pid}/exe") == str(binary),
            "unexpected runtime",
        )
        require(
            digest(Path(f"/proc/{main_pid}/exe")) == request["binary_sha256"],
            "running hash drift",
        )
        save(
            journal / "before.json",
            {
                "binary": str(binary),
                "sha256": request["binary_sha256"],
                "uid": info.st_uid,
                "gid": info.st_gid,
                "mode": "0755",
                "pid": main_pid,
            },
        )
        os.fchown(descriptor, 0, 0)
        os.fsync(descriptor)
        after = binary.lstat()
        require(
            (after.st_dev, after.st_ino) == (info.st_dev, info.st_ino),
            "binary replaced during ownership repair",
        )
        trusted_file(binary)
        require(
            pid() == main_pid
            and digest(binary) == request["binary_sha256"]
            and digest(Path(f"/proc/{main_pid}/exe")) == request["binary_sha256"],
            "runtime changed during repair",
        )
    finally:
        os.close(descriptor)


def retire_route(request, journal):
    name = request["service"]
    require(re.fullmatch(r"[a-z][a-z0-9_-]*", name), "invalid service name")
    require(name != "traefik", "cannot retire the proxy")
    route = Path("/etc/traefik/dynamic") / (name + ".traefik.yml")
    unit = Path("/etc/systemd/system") / (name + ".service")
    target = Path(request["unit_target"])
    require(
        target == Path("/home") / name / "site" / (name + ".service"),
        "unexpected linked unit target",
    )
    trusted_file(route)
    require(digest(route) == request["route_sha256"], "route drift")
    require(unit.is_symlink() and os.readlink(unit) == str(target), "unit link drift")
    require(target.is_file(), "unit source absent")
    state = run(
        ["systemctl", "show", name + ".service", "-p", "ActiveState", "--value"]
    ).strip()
    require(state == "inactive", "retirement requires an already inactive service")
    candidate = base64.b64decode(request["candidate_base64"], validate=True)
    parsed = json.loads(candidate)
    require(
        set(parsed) == {"http"} and set(parsed["http"]) == {"middlewares"},
        "retirement candidate must contain only retained middleware",
    )
    require(isinstance(parsed["http"]["middlewares"], dict), "invalid middleware map")
    require(
        parsed["http"]["middlewares"] == request.get("verified_middlewares"),
        "candidate changes retained middleware",
    )
    candidate = (json.dumps(parsed, indent=2) + "\n").encode()
    original = route.read_bytes()
    original_mode = stat.S_IMODE(route.stat().st_mode)
    main_pid = pid()
    require(main_pid > 1, "proxy not running")
    atomic(journal / "route.before.yml", original)
    atomic(journal / "unit.before", target.read_bytes())
    save(
        journal / "before.json",
        {
            "route": str(route),
            "route_sha256": digest(route),
            "mode": original_mode,
            "unit": str(unit),
            "unit_target": str(target),
            "pid": main_pid,
        },
    )
    # Disable removes install links, but preserves the application's source unit.
    run(["systemctl", "disable", name + ".service"])
    if unit.is_symlink():
        require(os.readlink(unit) == str(target), "unit link changed")
        unit.unlink()
    require(
        not unit.exists() and not unit.is_symlink(), "unexpected unit after disable"
    )
    unit.symlink_to("/dev/null")
    run(["systemctl", "daemon-reload"])
    require(
        run(
            ["systemctl", "show", name + ".service", "-p", "LoadState", "--value"]
        ).strip()
        == "masked",
        "unit mask failed",
    )
    require(
        digest(route) == request["route_sha256"], "route changed before replacement"
    )
    atomic(route, candidate, original_mode)
    require(pid() == main_pid, "proxy restarted during retirement")
    require(
        run(
            ["systemctl", "show", name + ".service", "-p", "ActiveState", "--value"]
        ).strip()
        == "inactive",
        "retired service is active",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    args = parser.parse_args()
    request = json.loads(Path(args.request).read_text())
    require(os.geteuid() == 0, "root required")
    require(
        Path("/etc/machine-id").read_text().strip() == request["machine_id"],
        "wrong machine",
    )
    require(request.get("review_reference"), "review reference required")
    with LOCK.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(
            not STATE_ROOT.exists() and not STATE_ROOT.is_symlink(),
            "preparation prohibited after enrollment",
        )
        root = Path("/var/lib/traefik-preparation")
        root.mkdir(mode=0o700, exist_ok=True)
        info = root.lstat()
        require(
            stat.S_ISDIR(info.st_mode)
            and info.st_uid == 0
            and info.st_gid == 0
            and stat.S_IMODE(info.st_mode) == 0o700,
            "unsafe preparation journal",
        )
        require(
            not any(root.glob("*/pending.json")),
            "unresolved preparation; inspect prior journal",
        )
        journal = root / str(uuid.uuid4())
        journal.mkdir(mode=0o700)
        save(journal / "pending.json", request)
        if request["action"] == "ownership":
            repair_ownership(request, journal)
        elif request["action"] == "retire":
            retire_route(request, journal)
        else:
            raise ValueError("unsupported preparation action")
        save(
            journal / "complete.json",
            {
                "action": request["action"],
                "review_reference": request["review_reference"],
            },
        )
        (journal / "pending.json").unlink()
        print(
            json.dumps(
                {"changed": True, "journal": str(journal), "action": request["action"]}
            )
        )


if __name__ == "__main__":
    main()
