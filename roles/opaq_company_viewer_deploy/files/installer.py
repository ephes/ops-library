"""Fixed synthetic viewer lifecycle. No credential reads or global proxy changes."""

import argparse
import base64
import fcntl
import grp
import hashlib
import http.client
import json
import os
from pathlib import Path
import pwd
import socket
import ssl
import stat
import subprocess
import time
import types

POLICY_HASH = "bc843b06346f87d8b0dbd32d1043113b54cbf630e1e9046d4e6276ecd511bb14"  # pragma: allowlist secret
VIEWER_HASH = "80502449d00ed8c5a92777b87559af83d908588af030aa9a7a2bf371c434b455"  # pragma: allowlist secret
IDENTITY = "opaq-company-viewer"
UNIT = IDENTITY + ".service"
STATE = "/var/lib/opaq-company-viewer-installer"
AUTH = "/etc/opaq-company/viewer.htpasswd"
TARGETS = {
    "view/index.html": ("/srv/opaq-company/view/index.html", 0o640),
    "view/retained-last-good.html": (
        "/srv/opaq-company/view/retained-last-good.html",
        0o640,
    ),
    "view/no-accepted.html": ("/srv/opaq-company/view/no-accepted.html", 0o640),
    "opaq-company-httpd.py": ("/usr/local/libexec/opaq-company-httpd.py", 0o755),
    "opaq-company-viewer.service": ("/etc/systemd/system/" + UNIT, 0o644),
    "opaq-company.traefik.yml": ("/etc/traefik/dynamic/opaq-company.yml", 0o644),
}
PROXY = "opaq-company.traefik.yml"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def regular(path, limit=2 * 1024 * 1024):
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError("symlink refused")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("bounded regular file required")
        raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("file grew beyond limit")
        return raw


def policy(path):
    raw = regular(Path(path))
    if digest(raw) != POLICY_HASH:
        raise ValueError("package policy mismatch")
    module = types.ModuleType("trusted_package_policy")
    module.__file__ = str(path)
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def admit(bundle, rules):
    bundle = Path(bundle)
    allowed = set(TARGETS) | {"manifest.json", "fastdeploy-registration.draft.json"}
    entries = {str(p.relative_to(bundle)) for p in bundle.rglob("*")}
    if entries != allowed | {"view"} or bundle.is_symlink():
        raise ValueError("exact synthetic bundle required")
    content = {name: regular(bundle / name) for name in allowed}
    manifest = json.loads(content.pop("manifest.json"), object_pairs_hook=rules.unique)
    if set(manifest) != {
        "format",
        "synthetic_only",
        "company",
        "source_candidate",
        "hostname",
        "domain_assigned",
        "deployment_authorized",
        "content",
    } or any(
        (
            manifest["format"] != "opaq.synthetic.offline-viewer.v1",
            manifest["synthetic_only"] is not True,
            manifest["company"] != "synthetic-opaq",
            manifest["source_candidate"] != rules.CANDIDATE,
            manifest["domain_assigned"] is not False,
            manifest["deployment_authorized"] is not False,
        )
    ):
        raise ValueError("synthetic manifest required")
    if manifest["content"] != {name: digest(raw) for name, raw in content.items()}:
        raise ValueError("manifest integrity mismatch")
    config = json.loads(content[PROXY], object_pairs_hook=rules.unique)
    url = config["http"]["services"]["opaq-company"]["loadBalancer"]["servers"][0][
        "url"
    ]
    port = int(url.removeprefix("http://127.0.0.1:"))
    scope = rules.configuration(
        json.dumps(
            dict(
                synthetic_only=True,
                company="synthetic-opaq",
                hostname=manifest["hostname"],
                domain_assigned=False,
                port=port,
            )
        )
    )
    if (
        content[PROXY] != json.dumps(rules.traefik(scope), indent=2).encode() + b"\n"
        or content["opaq-company-viewer.service"] != rules.unit(scope).encode()
    ):
        raise ValueError("exact hardened service and authenticated ingress required")
    if digest(content["opaq-company-httpd.py"]) != VIEWER_HASH:
        raise ValueError("viewer code mismatch")
    for name, expected in rules.SOURCES.items():
        member = "view/" + ("index.html" if name == "accepted.html" else name)
        if digest(content[member]) != expected:
            raise ValueError("synthetic page mismatch")
    draft = json.loads(content["fastdeploy-registration.draft.json"])
    if (
        draft.get("status") != "disabled-draft-not-registered"
        or draft.get("vars", {}).get("fd_sync_services") is not False
    ):
        raise ValueError("disabled registration required")
    return {name: content[name] for name in TARGETS}, scope


class Runtime:
    def identity(self):
        account = pwd.getpwnam(IDENTITY)
        group = grp.getgrnam(IDENTITY)
        if (
            account.pw_shell not in ("/usr/sbin/nologin", "/sbin/nologin", "/bin/false")
            or account.pw_dir != "/nonexistent"
            or account.pw_gid != group.gr_gid
            or account.pw_uid == 0
        ):
            raise ValueError("dedicated nonlogin identity required")
        return group.gr_gid

    def root_gid(self):
        return 0

    def proxy_gid(self, name):
        return grp.getgrnam(name).gr_gid

    def state(self):
        def query(prop):
            result = subprocess.run(
                ["systemctl", "show", UNIT, "--property=" + prop, "--value"],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()

        if query("LoadState") == "not-found":
            return {"active": False, "enabled": False}
        active, enabled = query("ActiveState"), query("UnitFileState")
        if active not in {"active", "inactive", "failed"} or enabled not in {
            "enabled",
            "disabled",
        }:
            raise ValueError("unsupported service state")
        return {"active": active == "active", "enabled": enabled == "enabled"}

    def restore_service(self, previous):
        self.command("daemon-reload")
        self.command("enable" if previous["enabled"] else "disable", UNIT)
        self.command("restart" if previous["active"] else "stop", UNIT)

    def command(self, *args):
        subprocess.run(
            ["systemctl", *args],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop_owned(self):
        result = subprocess.run(
            ["systemctl", "stop", UNIT],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode not in (0, 5):
            raise ValueError("owned service stop failed")

    def occupied(self, port):
        with socket.socket() as connection:
            connection.settimeout(1)
            return connection.connect_ex(("127.0.0.1", port)) == 0

    def verify(self, scope, content, ingress):
        for name in ("index.html", "retained-last-good.html", "no-accepted.html"):
            connection = (
                http.client.HTTPSConnection(
                    scope["hostname"], timeout=5, context=ssl.create_default_context()
                )
                if ingress
                else http.client.HTTPConnection("127.0.0.1", scope["port"], timeout=5)
            )
            try:
                connection.request("GET", "/" + name)
                response = connection.getresponse()
                raw = response.read(2 * 1024 * 1024 + 1)
                if (
                    response.status != (401 if ingress else 200)
                    or response.getheader("Cache-Control") != "private, no-store"
                ):
                    raise ValueError("private response verification failed")
                if not ingress and raw != content["view/" + name]:
                    raise ValueError("served synthetic page mismatch")
            finally:
                connection.close()

    def retry_verify(self, scope, content, ingress):
        for attempt in range(10):
            try:
                self.verify(scope, content, ingress)
                return
            except (OSError, ValueError, http.client.HTTPException):
                if attempt == 9:
                    raise
                time.sleep(1)


class Installer:
    def __init__(self, runtime, root=Path("/"), owner_uid=0, rules=None):
        self.runtime, self.root = runtime, Path(root)
        self.owner_uid = owner_uid
        self.rules = rules

    def path(self, absolute):
        return self.root / absolute.lstrip("/")

    def atomic(self, path, raw, mode, uid=None, gid=None):
        uid = self.owner_uid if uid is None else uid
        gid = self.runtime.root_gid() if gid is None else gid
        # No recursive removal; only fixed artifact parents may be created.
        for parent in (path, *path.parents):
            if parent.is_symlink():
                raise ValueError("symlink destination refused")
        temporary = path.with_name("." + path.name + ".opaq-pending")
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, mode)
            os.chown(temporary, uid, gid)
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def cleanup_pending(self, path, approved):
        temporary = path.with_name("." + path.name + ".opaq-pending")
        if not temporary.exists() and not temporary.is_symlink():
            return
        raw = regular(temporary)
        info = temporary.stat()
        if (
            info.st_uid != self.owner_uid
            or stat.S_IMODE(info.st_mode) not in {0o600, 0o640, 0o644, 0o755}
            or not any(body.startswith(raw) for body in approved)
        ):
            raise ValueError("foreign pending artifact; recovery refused")
        temporary.unlink()

    def journal(self, record):
        self.cleanup_pending(
            self.path(STATE + "/record.json"),
            [
                json.dumps(dict(record, phase=phase)).encode()
                for phase in ("prepared", "complete", "recovering")
            ],
        )
        self.atomic(
            self.path(STATE + "/record.json"), json.dumps(record).encode(), 0o600
        )

    def check_content(self, content, scope):
        if self.rules is None or set(content) != set(TARGETS):
            raise ValueError("independent publication policy required")
        normalized = self.rules.configuration(json.dumps(scope))
        if normalized != scope:
            raise ValueError("noncanonical scope")
        if digest(content["opaq-company-httpd.py"]) != VIEWER_HASH:
            raise ValueError("recorded program mismatch")
        for name, expected in self.rules.SOURCES.items():
            member = "view/" + ("index.html" if name == "accepted.html" else name)
            if digest(content[member]) != expected:
                raise ValueError("recorded synthetic content mismatch")
        if (
            content["opaq-company-viewer.service"] != self.rules.unit(scope).encode()
            or content[PROXY]
            != json.dumps(self.rules.traefik(scope), indent=2).encode() + b"\n"
        ):
            raise ValueError("recorded service or ingress mismatch")

    def read_record(self):
        path = self.path(STATE + "/record.json")
        if not path.exists():
            return None
        info = path.lstat()
        if info.st_uid != self.owner_uid or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError("private ownership record required")
        record = json.loads(regular(path), object_pairs_hook=self.rules.unique)
        if (
            set(record)
            != {
                "format",
                "phase",
                "desired",
                "previous",
                "scope",
                "previous_scope",
                "service",
            }
            or record["format"] != "opaq.synthetic.installer.v1"
            or record["phase"] not in {"prepared", "complete", "recovering"}
            or set(record["service"]) != {"active", "enabled"}
            or any(not isinstance(value, bool) for value in record["service"].values())
        ):
            raise ValueError("invalid ownership record")
        for section, scope in (
            ("desired", record["scope"]),
            ("previous", record["previous_scope"]),
        ):
            entries = record[section]
            if set(entries) != set(TARGETS):
                raise ValueError("exact rollback set required")
            if all(value is None for value in entries.values()):
                if section != "previous" or scope is not None:
                    raise ValueError("invalid absent history")
                continue
            content = {}
            for name, value in entries.items():
                if (
                    not isinstance(value, dict)
                    or set(value) != {"body", "mode", "uid", "gid"}
                    or any(
                        not isinstance(value[key], int)
                        or isinstance(value[key], bool)
                        or value[key] < 0
                        for key in ("mode", "uid", "gid")
                    )
                    or value["mode"] != TARGETS[name][1]
                    or value["uid"] != self.owner_uid
                ):
                    raise ValueError("invalid artifact metadata")
                raw = base64.b64decode(value["body"], validate=True)
                if len(raw) > 2 * 1024 * 1024:
                    raise ValueError("bounded recorded artifact required")
                content[name] = raw
            self.check_content(content, scope)
        return record

    def auth(self, proxy_group):
        path = self.path(AUTH)
        for parent in (path, *path.parents):
            if parent.is_symlink():
                raise ValueError("auth symlink refused")
        info = path.stat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size == 0
            or info.st_uid != self.owner_uid
            or stat.S_IMODE(info.st_mode) != 0o640
            or info.st_gid != self.runtime.proxy_gid(proxy_group)
        ):
            raise ValueError("dedicated root-owned private auth file required")

    def capture(self):
        result = {}
        for name, (absolute, _) in TARGETS.items():
            path = self.path(absolute)
            if path.exists() or path.is_symlink():
                raw = regular(path)
                info = path.stat()
                result[name] = dict(
                    body=base64.b64encode(raw).decode(),
                    mode=stat.S_IMODE(info.st_mode),
                    uid=info.st_uid,
                    gid=info.st_gid,
                )
            else:
                result[name] = None
        return result

    def expected(self, content, gid):
        return {
            name: dict(
                body=base64.b64encode(raw).decode(),
                mode=TARGETS[name][1],
                uid=self.owner_uid,
                gid=gid if name.startswith("view/") else self.runtime.root_gid(),
            )
            for name, raw in content.items()
        }

    def validate(self, content, scope, proxy_group):
        self.check_content(content, scope)
        self.auth(proxy_group)
        # Shared parent directories must already exist; no proxy provisioning.
        for absolute in (
            "/etc/traefik/dynamic",
            "/etc/systemd/system",
            "/usr/local/libexec",
            "/srv",
        ):
            path = self.path(absolute)
            if not path.is_dir() or any(p.is_symlink() for p in (path, *path.parents)):
                raise ValueError("safe existing shared directories required")
        record = self.read_record()
        current = self.capture()
        if record is None:
            if (
                any(current.values())
                or self.path("/srv/opaq-company").exists()
                or self.runtime.occupied(scope["port"])
                or self.runtime.state() != {"active": False, "enabled": False}
            ):
                raise ValueError("unowned first-install collision")
        elif record["phase"] != "complete" or current != record["desired"]:
            raise ValueError(
                "interrupted or externally changed installation; inspect and rollback"
            )
        return record, current

    def rollback(self, record):
        for name, (absolute, _) in TARGETS.items():
            approved = [
                base64.b64decode(value["body"], validate=True)
                for value in (record["desired"][name], record["previous"][name])
                if value is not None
            ]
            self.cleanup_pending(self.path(absolute), approved)
        current = self.capture()
        # A crash between a write and phase update can leave either recorded side.
        for name in TARGETS:
            if current[name] not in (record["desired"][name], record["previous"][name]):
                raise ValueError("externally changed owned artifact; recovery refused")
        record["phase"] = "recovering"
        self.journal(record)
        # Stop only this owned unit, including recovery after its file was removed.
        if record["previous"]["opaq-company-viewer.service"] is None:
            if self.path(TARGETS["opaq-company-viewer.service"][0]).exists():
                self.runtime.command("disable", UNIT)
            self.runtime.stop_owned()
        else:
            self.runtime.command("stop", UNIT)
        # Withdraw/restore only this route first; no global proxy restart.
        for name in (PROXY, *(n for n in TARGETS if n != PROXY)):
            path = self.path(TARGETS[name][0])
            before = record["previous"][name]
            if before is None:
                path.unlink(missing_ok=True)
            else:
                self.atomic(
                    path,
                    base64.b64decode(before["body"], validate=True),
                    before["mode"],
                    before["uid"],
                    before["gid"],
                )
        if record["previous"]["opaq-company-viewer.service"] is None:
            self.runtime.command("daemon-reload")
        else:
            self.runtime.restore_service(record["service"])
        if all(value is None for value in record["previous"].values()):
            for absolute in ("/srv/opaq-company/view", "/srv/opaq-company"):
                path = self.path(absolute)
                if path.exists():
                    path.rmdir()  # Never delete foreign files.
            self.path(STATE + "/record.json").unlink()
        else:
            record["desired"] = record["previous"]
            record["scope"] = record["previous_scope"]
            record["phase"] = "complete"
            record["previous"] = record["desired"]
            record["service"] = self.runtime.state()
            self.journal(record)

    def execute(self, action, proxy_group, content=None, scope=None):
        state = self.path(STATE)
        if any(p.is_symlink() for p in (state, *state.parents)):
            raise ValueError("unsafe state directory")
        state.mkdir(mode=0o700, exist_ok=True)
        info = state.stat()
        if info.st_uid != self.owner_uid or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError("root-only state required")
        with os.fdopen(
            os.open(
                state / "lock",
                os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o600,
            ),
            "a",
        ) as lock:
            lock_info = os.fstat(lock.fileno())
            if (
                not stat.S_ISREG(lock_info.st_mode)
                or lock_info.st_uid != self.owner_uid
                or stat.S_IMODE(lock_info.st_mode) != 0o600
            ):
                raise ValueError("private regular lock required")
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if action == "rollback":
                record = self.read_record()
                if record is None:
                    raise ValueError("no owned rollback record")
                self.rollback(record)
                return True
            if action == "validate":
                self.validate(content, scope, proxy_group)
                return False
            gid = self.runtime.identity()
            if action == "verify":
                record = self.read_record()
                if record is None or record["phase"] != "complete":
                    raise ValueError("no complete installation")
                content = {
                    name: base64.b64decode(value["body"], validate=True)
                    for name, value in record["desired"].items()
                }
                scope = record["scope"]
            old, before = self.validate(content, scope, proxy_group)
            desired = self.expected(content, gid)
            if action == "verify" or before == desired:
                self.runtime.retry_verify(scope, content, False)
                self.runtime.retry_verify(scope, content, True)
                if self.runtime.state() != {"active": True, "enabled": True}:
                    raise ValueError("viewer service not active and enabled")
                return False
            record = dict(
                format="opaq.synthetic.installer.v1",
                phase="prepared",
                previous=before,
                desired=desired,
                scope=scope,
                previous_scope=old["scope"] if old else None,
                service=self.runtime.state(),
            )
            self.journal(record)
            try:
                if old is not None:
                    self.runtime.command("stop", UNIT)
                if old is None:
                    for absolute in ("/srv/opaq-company", "/srv/opaq-company/view"):
                        path = self.path(absolute)
                        path.mkdir(mode=0o750)
                        os.chown(path, self.owner_uid, gid)
                for name, value in desired.items():
                    if name != PROXY:
                        self.atomic(
                            self.path(TARGETS[name][0]),
                            content[name],
                            value["mode"],
                            value["uid"],
                            value["gid"],
                        )
                self.runtime.command("daemon-reload")
                self.runtime.command("enable", UNIT)
                self.runtime.command("restart", UNIT)
                self.runtime.retry_verify(scope, content, False)
                self.atomic(
                    self.path(TARGETS[PROXY][0]),
                    content[PROXY],
                    0o644,
                    self.owner_uid,
                    self.runtime.root_gid(),
                )
                self.runtime.retry_verify(scope, content, True)
                self.runtime.retry_verify(scope, content, False)
                if self.runtime.state() != {"active": True, "enabled": True}:
                    raise ValueError("viewer service did not remain active and enabled")
                record["phase"] = "complete"
                self.journal(record)
            except BaseException:
                self.rollback(record)
                raise
            return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action",
        choices=("admit", "validate", "install", "verify", "rollback"),
        required=True,
    )
    parser.add_argument("--bundle")
    parser.add_argument("--policy", required=True)
    parser.add_argument("--proxy-group", required=True)
    args = parser.parse_args(argv)
    try:
        if (
            args.action != "admit" and os.geteuid() != 0
        ) or args.proxy_group == "CHANGEME":
            raise ValueError("root and explicit proxy group required")
        rules = policy(args.policy)
        content, scope = (
            admit(args.bundle, rules)
            if args.action in ("admit", "validate", "install")
            else (None, None)
        )
        changed = False
        if args.action != "admit":
            changed = Installer(Runtime(), rules=rules).execute(
                args.action, args.proxy_group, content, scope
            )
        print(json.dumps({"changed": changed, "action": args.action}))
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as exc:
        parser.exit(1, f"Synthetic viewer operation refused: {type(exc).__name__}\n")


if __name__ == "__main__":
    main()
