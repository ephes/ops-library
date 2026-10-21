"""A fake ``systemctl`` for the software_live switch tests.

It keeps a small world in ``$FAKE_SYSTEMD_STATE/world.json`` and behaves like
systemd for the calls the role and ``ansible.builtin.systemd_service`` make:

- unit files and drop-ins live in ``$FAKE_SYSTEMD_DIR``; ``daemon-reload``
  loads their ``ExecStart=``/``ExecStartPost=`` (an empty assignment resets
  the list, as in systemd); a unit is loaded on first use otherwise;
- ``start``/``restart`` of an endpoint "executes" its loaded ``ExecStart=``:
  a new PID in ``$FAKE_PROC`` (``exe`` link to the resolved executable,
  ``cmdline``) and in the unit's ``cgroup.procs`` under ``$FAKE_CGROUP``;
- ``start`` of a collector runs it to completion: it rewrites the file named
  by ``--output`` and records ``ExecMainStatus``. A collector that a test left
  ``activating`` (a run still in progress) finishes instead, as systemd merges
  the start job into the running one;
- ``show`` prints the requested properties (``--property=A,B``/``-p A``,
  ``--value``), ``ExecStart=`` in systemd's ``{ path=... ; argv[]=... }`` form.

A run a test planted may carry ``finish_after``: it ends after that many
more ``show`` calls of its unit (a run that finishes while the play waits).

Flag files in ``$FAKE_SYSTEMD_STATE``: ``exe-override-<unit>`` (the next start
of that unit runs the executable named in the file instead) and
``collector-fails`` (a collector run exits 1).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
import time
from pathlib import Path

STATE = Path(os.environ["FAKE_SYSTEMD_STATE"])
UNITS = Path(os.environ["FAKE_SYSTEMD_DIR"])
PROC = Path(os.environ["FAKE_PROC"])
CGROUP = Path(os.environ["FAKE_CGROUP"])
WORLD = STATE / "world.json"
RUNNING = ("activating", "active", "deactivating", "reloading", "refreshing")


def load() -> dict:
    if WORLD.exists():
        return json.loads(WORLD.read_text())
    return {"units": {}, "next_pid": 1000}


world = load()


def save() -> None:
    WORLD.write_text(json.dumps(world, indent=1, sort_keys=True))


def unit(name: str) -> dict:
    return world["units"].setdefault(
        name,
        {
            "active": "inactive",
            "main": 0,
            "control": 0,
            "cgroup": "",
            "status": 0,
            "enabled": False,
            "loaded": None,
            "pids": [],
        },
    )


def read_config(name: str) -> dict | None:
    base = UNITS / name
    if not base.exists():
        return None
    files = [base] + sorted((UNITS / f"{name}.d").glob("*.conf"))
    config = {"ExecStart": [], "ExecStartPost": []}
    for path in files:
        for line in path.read_text().splitlines():
            match = re.match(r"^(ExecStart|ExecStartPost)=(.*)$", line)
            if match:
                if match.group(2) == "":
                    config[match.group(1)] = []
                else:
                    config[match.group(1)].append(match.group(2))
    return config


def loaded(name: str) -> dict | None:
    info = unit(name)
    if info["loaded"] is None:
        info["loaded"] = read_config(name)
    return info["loaded"]


def words(command: str) -> list[str]:
    return shlex.split(command.lstrip("-@:+!"))


def exec_value(command: str) -> str:
    argv = words(command)
    ignore = "yes" if command.startswith("-") else "no"
    return (
        f"{{ path={argv[0]} ; argv[]={' '.join(argv)} ; ignore_errors={ignore} ; "
        "start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }"
    )


def kill(name: str) -> None:
    info = unit(name)
    for pid in info["pids"]:
        target = PROC / str(pid)
        if target.is_symlink() or target.exists():
            for child in target.iterdir() if target.is_dir() else []:
                child.unlink()
            target.rmdir()
    info["pids"], info["main"], info["control"] = [], 0, 0
    if info["cgroup"]:
        procs = CGROUP / info["cgroup"].lstrip("/") / "cgroup.procs"
        if procs.exists():
            procs.write_text("")


def spawn(name: str, argv: list[str]) -> int:
    info = unit(name)
    pid = world["next_pid"]
    world["next_pid"] += 1
    exe = argv[0]
    override = STATE / f"exe-override-{name}"
    if override.exists():
        exe = override.read_text().strip()
    if exe == "/usr/bin/python3":
        exe = "/usr/bin/python3.12"
    elif os.path.exists(exe):
        exe = os.path.realpath(exe)  # /proc shows the resolved path
    directory = PROC / str(pid)
    directory.mkdir(parents=True)
    (directory / "exe").symlink_to(exe)
    (directory / "cmdline").write_bytes(b"".join(a.encode() + b"\0" for a in argv))
    info["cgroup"] = f"/system.slice/{name}"
    procs = CGROUP / "system.slice" / name / "cgroup.procs"
    procs.parent.mkdir(parents=True, exist_ok=True)
    info["pids"] = [pid]
    procs.write_text(f"{pid}\n")
    return pid


def start(name: str) -> int:
    config = loaded(name)
    if config is None:
        print(f"Failed to start {name}: Unit {name} not found.", file=sys.stderr)
        return 5
    info = unit(name)
    with (STATE / "starts.log").open("a") as log:
        log.write(f"{name}\n")
    if name.endswith(".timer"):
        info["active"] = "active"
        return 0
    if name.endswith("endpoint.service"):
        if info["active"] == "active":
            return 0
        info["main"] = spawn(name, words(config["ExecStart"][-1]))
        info["active"] = "active"
        return 0
    # A collector (oneshot).
    argv = words(config["ExecStart"][-1])
    output = argv[argv.index("--output") + 1] if "--output" in argv else None
    if info["active"] in RUNNING:
        # A run in progress: systemd merges the start job and waits for it.
        kill(name)
        info["active"], info["status"] = "inactive", 0
    else:
        with (STATE / "collector-runs.log").open("a") as log:
            log.write(f"{name} {argv[0]}\n")
        if (STATE / "collector-fails").exists():
            info["status"] = 1
            print(f"Job for {name} failed.", file=sys.stderr)
            return 1
        info["status"] = 0
    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(json.dumps({"generated_at_epoch": time.time()}) + "\n")
    return 0


def stop(name: str) -> int:
    info = unit(name)
    kill(name)
    info["active"] = "inactive"
    return 0


def show(names: list[str], props: list[str], value_only: bool) -> int:
    for name in names:
        info = unit(name)
        if info.get("finish_after") is not None:
            # A planted run that ends after this many more `show` calls.
            info["finish_after"] -= 1
            if info["finish_after"] <= 0:
                kill(name)
                info.update(active="inactive", status=0, finish_after=None)
        config = loaded(name)
        values = {
            "LoadState": "loaded" if config is not None else "not-found",
            "ActiveState": info["active"],
            "SubState": "running" if info["active"] == "active" else "dead",
            "MainPID": str(info["main"]),
            "ControlPID": str(info["control"]),
            "ControlGroup": info["cgroup"] if info["active"] in RUNNING else "",
            "ExecMainStatus": str(info["status"]),
            "UnitFileState": "enabled" if info["enabled"] else "disabled",
        }
        lines: list[tuple[str, str]] = []
        for prop in props or list(values) + ["ExecStart", "ExecStartPost"]:
            if prop in ("ExecStart", "ExecStartPost"):
                for command in (config or {}).get(prop, []):
                    lines.append((prop, exec_value(command)))
            elif prop in values:
                lines.append((prop, values[prop]))
        for prop, value in lines:
            print(value if value_only else f"{prop}={value}")
    return 0


def main(args: list[str]) -> int:
    with (STATE / "systemctl.log").open("a") as log:
        log.write(" ".join(args) + "\n")
    if not args:
        return 0
    command, rest = args[0], args[1:]
    props: list[str] = []
    value_only = False
    names: list[str] = []
    it = iter(rest)
    for arg in it:
        if arg.startswith("--property="):
            props += arg[len("--property=") :].split(",")
        elif arg == "-p":
            props += next(it).split(",")
        elif arg == "--value":
            value_only = True
        elif arg == "--":
            continue
        elif arg.startswith("-"):
            continue
        else:
            names.append(arg)
    if command == "daemon-reload":
        for name in list(world["units"]):
            world["units"][name]["loaded"] = read_config(name)
        for path in UNITS.iterdir():
            if path.is_file():
                unit(path.name)["loaded"] = read_config(path.name)
        return 0
    if command == "show":
        return show(names, props, value_only)
    rc = 0
    for name in names:
        info = unit(name)
        if command == "is-enabled":
            print("enabled" if info["enabled"] else "disabled")
            rc = rc or (0 if info["enabled"] else 1)
        elif command == "is-active":
            print(info["active"])
            rc = rc or (0 if info["active"] == "active" else 3)
        elif command in ("enable", "disable"):
            info["enabled"] = command == "enable"
        elif command == "start":
            rc = rc or start(name)
        elif command == "restart":
            if loaded(name) is None:
                rc = rc or 5
                continue
            stop(name)
            rc = rc or start(name)
        elif command == "stop":
            rc = rc or stop(name)
        else:
            print(f"fake systemctl: unsupported {command}", file=sys.stderr)
            return 1
    return rc


if __name__ == "__main__":
    try:
        code = main(sys.argv[1:])
    finally:
        save()
    sys.exit(code)
