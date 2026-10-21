#!/usr/bin/env python3
"""Persist CA-only Compose overlays in explicitly inspected native systemd owners."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time

import activate

ROOT = Path("/var/lib/managed-container-ca/owners")
UNIT_ROOT = Path("/etc/systemd/system")
# Native health checks may run only every 180 seconds after startup.
OWNER_HEALTH_TIMEOUT_SECONDS = 600


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def private_file(path, content):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("Managed path is a symlink")
    descriptor, name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".new", dir=path.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class Runner:
    def __init__(self, receipt=None):
        self.receipt = receipt
        self.sequence = 0

    def __call__(self, argv, input_text=None):
        started = time.time()
        result = subprocess.run(argv, input=input_text, text=True, capture_output=True)
        if result.returncode:
            self.sequence += 1
            folder = self.receipt or ROOT.parent / "owner-errors"
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y%m%dT%H%M%S%fZ"
            )
            path = folder / f"command-error-{stamp}-{self.sequence}.txt"
            detail = result.stdout + "\n" + result.stderr
            if (
                argv[:1] == ["systemctl"]
                and len(argv) == 3
                and argv[1] in ("start", "stop")
            ):
                journal = subprocess.run(
                    [
                        "journalctl",
                        "--unit",
                        argv[2],
                        "--since",
                        "@" + str(started),
                        "--output",
                        "short-iso",
                        "--no-pager",
                        "-n",
                        "80",
                    ],
                    text=True,
                    capture_output=True,
                )
                detail += "\nNative owner journal:\n" + journal.stdout + journal.stderr
            private_file(path, detail.encode())
            raise RuntimeError(
                "Native command failed; private diagnostics: " + str(path)
            )
        return result.stdout


def protected(path):
    stat = path.lstat()
    if path.is_symlink() or stat.st_uid != 0 or stat.st_mode & 0o022:
        raise ValueError("Managed path is not root-owned and protected")


def owner_paths(project):
    unit = project["owner"]["unit"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.service", unit):
        raise ValueError("Invalid explicit owner unit")
    folder = ROOT / unit
    return (
        folder / "owner.json",
        folder / "trust.json",
        UNIT_ROOT / (unit + ".d") / "90-managed-container-ca.conf",
    )


def command_with_overlay(argv, overlay):
    # Only the actual inspected simple Compose owner shape is supported.
    if argv[:2] != ["/usr/bin/docker", "compose"] or argv[-3:] != [
        "up",
        "-d",
        "--remove-orphans",
    ]:
        raise ValueError("Unsupported native Compose start/reload shape")
    prefix = argv[2:-3]
    if len(prefix) == 4 and prefix[0] == "-p":
        prefix = prefix[2:]
    if len(prefix) != 2 or prefix[0] != "-f" or not prefix[1].startswith("/"):
        raise ValueError("Unsupported native Compose file/project arguments")
    return argv[:-3] + ["-f", str(overlay)] + argv[-3:]


def dropin(project):
    config, overlay, _ = owner_paths(project)
    owner = project["owner"]
    prepare = [
        "/usr/bin/python3",
        str(ROOT / "persist_owners.py"),
        "--prepare",
        str(config),
    ]
    lines = [
        "[Service]",
        "ExecStartPre=" + shlex.join(prepare),
        "ExecStart=",
        "ExecStart=" + shlex.join(command_with_overlay(owner["start"], overlay)),
    ]
    if owner["reload"]:
        lines += [
            "ExecReload=",
            "ExecReload=" + shlex.join(prepare),
            "ExecReload=" + shlex.join(command_with_overlay(owner["reload"], overlay)),
        ]
    return ("\n".join(lines) + "\n").encode()


def validate_owner(project, execute, approved=None):
    approved = approved or {}
    owner = project["owner"]
    config, overlay, managed = owner_paths(project)
    fragment = UNIT_ROOT / owner["unit"]
    protected(fragment)
    if digest(fragment) != owner["fragment_sha256"]:
        raise ValueError("Original owner fragment changed; reconcile explicitly")
    text = fragment.read_text()
    if "\\\n" in text:
        raise ValueError("Multiline owner commands require explicit reconciliation")
    fields = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields.setdefault(key, []).append(value)
    if fields.get("Type") != ["oneshot"] or fields.get("RemainAfterExit") != ["yes"]:
        raise ValueError("Owner must be an inspected oneshot with RemainAfterExit")
    loaded = execute(
        ["systemctl", "show", owner["unit"], "--property=FragmentPath", "--value"]
    ).strip()
    if loaded != str(fragment):
        raise ValueError("Loaded owner fragment differs from explicit source")
    if fields.get("WorkingDirectory") != [owner["working_directory"]]:
        raise ValueError("Owner working directory changed")
    for key in (
        "User",
        "Group",
        "ExecStartPre",
        "ExecStartPost",
        "ExecStopPre",
        "ExecStopPost",
        "ExecCondition",
        "Environment",
        "EnvironmentFile",
        "PassEnvironment",
        "UnsetEnvironment",
    ):
        if fields.get(key):
            raise ValueError("Unsupported owner user, environment or pre/post command")
    for key, name in [
        ("ExecStart", "start"),
        ("ExecStop", "stop"),
        ("ExecReload", "reload"),
    ]:
        actual = [shlex.split(value) for value in fields.get(key, [])]
        expected = [owner[name]] if owner[name] else []
        if actual != expected:
            raise ValueError("Owner command changed; reconcile explicitly")
    command_with_overlay(owner["start"], overlay)
    if owner["reload"]:
        command_with_overlay(owner["reload"], overlay)
    if owner["stop"][:-1] != owner["start"][:-3] or owner["stop"][-1] not in (
        "stop",
        "down",
    ):
        raise ValueError("Unsupported owner stop semantics")
    if (
        owner["working_directory"] != project["directory"]
        or project["files"] != [owner["start"][owner["start"].index("-f") + 1]]
        or Path(project["files"][0]).parent != Path(project["directory"])
    ):
        raise ValueError("Owner and explicit project paths differ")
    if any(
        re.search(r"[^A-Za-z0-9_./:,=-]", token)
        for key in ("start", "stop", "reload")
        for token in owner[key]
    ):
        raise ValueError("Owner argv needs explicit reconciliation")
    extras = shlex.split(
        execute(
            ["systemctl", "show", owner["unit"], "--property=DropInPaths", "--value"]
        ).strip()
    )
    if extras not in ([], [str(managed)]):
        raise ValueError("Unknown owner drop-in; reconcile explicitly")
    if managed.exists():
        if extras != [str(managed)] and not approved:
            raise ValueError(
                "Managed drop-in is not loaded; explicit reconciliation required"
            )
        protected(managed)
        if managed.read_bytes() != dropin(project) and approved.get(
            str(managed)
        ) != digest(managed):
            raise ValueError("Managed owner drop-in drift")
    return config, overlay, managed


def ca_overlay(project, execute):
    base = json.loads(
        execute(activate.compose(project) + ["config", "--format", "json"])
    )
    records = project["containers"]
    if set(base["services"]) != {r["service"] for r in records}:
        raise ValueError("Base Compose service coverage changed")
    states = {}
    for record in records:
        if record.get("store"):
            source = Path(record["store"])
            for path in (
                source,
                source / "bundle.pem",
                source / "manifest.json",
                source / "empty",
            ):
                protected(path)
        if record.get("chrome_policy"):
            protected(Path(record["chrome_policy"]))
        if record.get("linuxserver_hook"):
            protected(Path(record["linuxserver_hook"]))
        service = base["services"][record["service"]]
        if service.get("build") or service.get("pull_policy") not in (
            None,
            "missing",
            "if_not_present",
            "never",
        ):
            raise ValueError("Native owner would build or force-pull an image")
        image = json.loads(execute(["docker", "image", "inspect", service["image"]]))[0]
        env = dict(pair.split("=", 1) for pair in (image["Config"].get("Env") or []))
        for key, value in (service.get("environment") or {}).items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = str(value)
        states[record["name"]] = {
            "Image": image["Id"],
            "Config": {
                "Env": [k + "=" + v for k, v in env.items()],
                "Labels": {"com.docker.compose.service": record["service"]},
            },
        }
        if record.get("linuxserver_hook"):
            proof = record["linuxserver_proof"]
            if "images" in proof and "image" in proof:
                raise ValueError("Use one explicit LinuxServer image proof format")
            images = proof.get("images", [proof.get("image")])
            if (
                not isinstance(images, list)
                or not 1 <= len(images) <= 2
                or len(set(images)) != len(images)
                or image["Id"] not in images
            ):
                raise ValueError("LinuxServer image needs a new reviewed trust proof")
            for filename in ("repair_ca.py", "10-emudhra-ca.sh"):
                path = Path(record["linuxserver_hook"]) / filename
                protected(path)
                if digest(path) != proof["sha256"][filename]:
                    raise ValueError("LinuxServer hook proof changed")
    result = activate.overlay_for(project, states)
    for service in result["services"].values():
        del service["image"]
    return (json.dumps(result, indent=2) + "\n").encode()


def configuration_bytes(project):
    return (json.dumps(project, sort_keys=True, indent=2) + "\n").encode()


def prepare(config_path, execute):
    protected(config_path)
    project = json.loads(config_path.read_text())
    for name, expected in project["tool_sha256"].items():
        path = ROOT / name
        protected(path)
        if digest(path) != expected:
            raise ValueError("Managed owner tool drift")
    config, overlay, managed = validate_owner(project, execute)
    if config != config_path or not managed.is_file():
        raise ValueError("Managed owner is not installed")
    content = ca_overlay(project, execute)
    if overlay.exists():
        protected(overlay)
    if not overlay.exists() or overlay.read_bytes() != content:
        private_file(overlay, content)


def managed_hashes(projects):
    paths = {ROOT / name for name in ("persist_owners.py", "activate.py")}
    paths.update(path for project in projects for path in owner_paths(project))
    result = {}
    for path in sorted(paths):
        if path.exists():
            protected(path)
            result[str(path)] = digest(path)
    return result


def write_outcome(receipt, data, required=False):
    try:
        private_file(receipt / "result.json", json.dumps(data).encode())
    except OSError:
        if required:
            raise
        print(
            "WARNING: private outcome receipt unavailable; verify live owner state before retry"
        )


def plan(projects, execute, approved=None):
    approved = approved or {}
    if approved and approved != managed_hashes(projects):
        raise ValueError(
            "Reconciliation requires exact hashes of every existing managed artifact"
        )
    units = [p["owner"]["unit"] for p in projects]
    if len(units) != len(set(units)) or len({p["project"] for p in projects}) != len(
        projects
    ):
        raise ValueError("Duplicate explicit owner or project")
    artifacts = {
        ROOT / name: Path(__file__).with_name(name).read_bytes()
        for name in ("persist_owners.py", "activate.py")
    }
    tool_hashes = {
        p.name: hashlib.sha256(data).hexdigest() for p, data in artifacts.items()
    }
    augmented = []
    for raw in projects:
        project = json.loads(json.dumps(raw))
        project["tool_sha256"] = tool_hashes
        config, overlay, managed = validate_owner(project, execute, approved)
        content = ca_overlay(project, execute)
        artifacts.update(
            {
                config: configuration_bytes(project),
                overlay: content,
                managed: dropin(project),
            }
        )
        current = dict(project)
        if managed.exists():
            if not config.exists() or not overlay.exists():
                raise ValueError("Managed owner configuration or override missing")
            current["files"] = project["files"] + [str(overlay)]
        augmented.append(current)
    for path, content in artifacts.items():
        if path.exists():
            protected(path)
            if path.read_bytes() != content and approved.get(str(path)) != digest(path):
                raise ValueError("Managed owner artifact drift; reconcile explicitly")
    original, _ = activate.preflight(augmented, execute)
    if any(m["Type"] != "bind" for row in original for m in row["Mounts"]):
        raise ValueError(
            "Owner stop needs explicit non-bind volume preservation review"
        )
    return artifacts, original


def apply(projects, receipt, execute=None, approved=None):
    receipt.mkdir(parents=True, exist_ok=False, mode=0o700)
    execute = execute or Runner(receipt)
    artifacts, original = plan(projects, execute, approved)
    if not approved and all(
        p.exists() and p.read_bytes() == content for p, content in artifacts.items()
    ):
        write_outcome(
            receipt,
            {
                "status": "unchanged",
                "docker_restart_attempted": False,
                "units": [p["owner"]["unit"] for p in projects],
            },
        )
        return False
    before = {str(p): p.read_bytes().hex() if p.exists() else None for p in artifacts}
    private_file(receipt / "original-managed.json", json.dumps(before).encode())
    private_file(receipt / "original-inspect.json", json.dumps(original).encode())
    units = [p["owner"]["unit"] for p in projects]
    failures = []

    def attempt_all(verb):
        errors = []
        for unit in units:
            try:
                execute(["systemctl", verb, unit])
            except Exception:
                errors.append(unit)
        if errors:
            raise RuntimeError("One or more native owners failed " + verb)

    def outcome(status, required=False):
        write_outcome(
            receipt,
            {
                "status": status,
                "docker_restart_attempted": False,
                "units": units,
                "failures": failures,
            },
            required,
        )

    outcome("prepared", required=True)
    try:
        attempt_all("stop")
        for path, content in artifacts.items():
            private_file(path, content)
        execute(["systemctl", "daemon-reload"])
        attempt_all("start")
        activate.healthy(
            [r["Name"].lstrip("/") for r in original],
            execute,
            timeout=OWNER_HEALTH_TIMEOUT_SECONDS,
        )
        outcome("activated")
        return True
    except Exception:
        failures.append("activation")
        try:
            attempt_all("stop")
        except Exception:
            failures.append("recovery-stop")
        # Restore every artifact even after an earlier restoration fails.
        for path, content in before.items():
            try:
                target = Path(path)
                if content is None:
                    target.unlink(missing_ok=True)
                else:
                    private_file(target, bytes.fromhex(content))
            except Exception:
                failures.append("restore-managed-file")
        try:
            execute(["systemctl", "daemon-reload"])
        except Exception:
            failures.append("recovery-daemon-reload")
        try:
            attempt_all("start")
        except Exception:
            failures.append("recovery-start")
        try:
            activate.healthy(
                [r["Name"].lstrip("/") for r in original],
                execute,
                timeout=OWNER_HEALTH_TIMEOUT_SECONDS,
            )
        except Exception:
            failures.append("recovery-health")
        outcome("recovery_failed" if len(failures) > 1 else "rolled_back")
        raise RuntimeError(
            "Owner activation failed; inspect private receipt " + str(receipt)
        ) from None


def main():
    os.umask(0o077)
    if os.geteuid() != 0 or sys.platform != "linux":
        raise ValueError("Owner persistence requires Linux root")
    if sys.argv[1] == "--prepare":
        prepare(Path(sys.argv[2]), Runner())
        return
    if sys.argv[1] == "--managed-sha":
        print(json.dumps(managed_hashes(json.loads(sys.argv[2])), sort_keys=True))
        return
    projects = json.loads(sys.argv[1])
    approved = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
    if sys.argv[2] == "--check":
        artifacts, _ = plan(projects, Runner(), approved)
        print(
            "CHANGED"
            if approved
            or any(
                not p.exists() or p.read_bytes() != data
                for p, data in artifacts.items()
            )
            else "UNCHANGED"
        )
        print("Owner preflight passed; no runtime changes")
    elif sys.argv[2] == "--apply":
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y%m%dT%H%M%S%fZ"
        )
        receipt = ROOT.parent / "owner-activation" / stamp
        changed = apply(projects, receipt, approved=approved)
        print("CHANGED" if changed else "UNCHANGED")
        print("Receipt: " + str(receipt))
    else:
        raise ValueError("Unknown explicit operation")


if __name__ == "__main__":
    main()
