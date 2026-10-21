"""Validate narrow prior-install evidence without importing application packages."""

import base64
import email
import hashlib
import json
import os
import pwd
import re
import stat
import sys
from pathlib import Path


def file_digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def unchanged_path(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError("Recovery path must be absolute without symlinks")
    return path


def inspect(entry, wheel, wheel_hash, target_version="2026.10.19", apply=False):
    prefix = unchanged_path(entry["path"])
    owner = pwd.getpwnam(entry["owner"])
    if not re.fullmatch(r"/home/[a-zA-Z0-9_-]+/(site/)?\.?venv", str(prefix)):
        raise ValueError("Unsupported recovery environment")
    if prefix.stat().st_uid != owner.pw_uid or owner.pw_uid == 0:
        raise ValueError("Environment owner mismatch")
    # An already maintained package requires no restoration authority or mutation.
    # Later ordinary remediation may legitimately update pip or replace a snapshot.
    installed = []
    for metadata in prefix.glob(
        "lib/python*/site-packages/certifi-*.dist-info/METADATA"
    ):
        unchanged_path(metadata)
        headers = email.message_from_bytes(metadata.read_bytes())
        if re.sub(r"[-_.]+", "-", headers.get("Name", "")).lower() != "certifi":
            raise ValueError("Unexpected certifi distribution identity")
        installed.append(headers.get("Version"))
    if installed == [target_version]:
        return {"already_fixed": True, "cache_paths": []}
    if len(installed) > 1:
        raise ValueError("Duplicate installed certifi distribution")
    evidence = unchanged_path(entry["before"])
    if not re.fullmatch(
        r"/var/backups/security-trust-remediation/environment-[a-zA-Z0-9_]+/before.json",
        str(evidence),
    ):
        raise ValueError("Unexpected evidence path")
    for path in (evidence.parent, evidence):
        info = path.lstat()
        if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("Evidence must remain root-only")
    archive = unchanged_path(evidence.parent / "environment.tar")
    if (
        archive.stat().st_uid != 0
        or not archive.is_file()
        or archive.stat().st_size == 0
    ):
        raise ValueError("Missing original environment archive")
    if file_digest(archive) != entry["archive_sha256"]:
        raise ValueError("Original archive digest mismatch")
    raw = evidence.read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry["before_sha256"]:
        raise ValueError("Prior evidence digest mismatch")
    before = json.loads(raw)
    if before["prefix"] != str(prefix) or "certifi" not in before["packages"]:
        raise ValueError("No proven previous certifi installation")
    wheel = unchanged_path(wheel)
    if file_digest(wheel) != wheel_hash:
        raise ValueError("Wheel digest mismatch")
    if (
        wheel.stat().st_uid != 0
        or wheel.stat().st_mode & 0o022
        or wheel.parent.stat().st_uid != 0
        or wheel.parent.stat().st_mode & 0o022
    ):
        raise ValueError("Wheel and staging directory must be root-controlled")

    def canonical(name):
        return re.sub(r"[-_.]+", "-", name).lower()

    expected = {
        canonical(k): v["version"]
        for k, v in before["packages"].items()
        if canonical(k) != "certifi"
    }
    current = {}
    for metadata in prefix.glob("lib/python*/site-packages/*.dist-info/METADATA"):
        unchanged_path(metadata)
        headers = email.message_from_bytes(metadata.read_bytes())
        name = canonical(headers["Name"])
        if name != "certifi":
            if name in current:
                raise ValueError("Duplicate installed distribution")
            current[name] = headers["Version"]
    for metadata in prefix.glob("lib/python*/site-packages/*.egg-info/PKG-INFO"):
        unchanged_path(metadata)
        headers = email.message_from_bytes(metadata.read_bytes())
        name = canonical(headers["Name"])
        if name != "certifi":
            if name in current:
                raise ValueError("Duplicate installed distribution")
            current[name] = headers["Version"]
    if expected != current:
        raise ValueError("Installed distributions changed since interrupted update")
    if not list(prefix.glob("lib/python*/site-packages/certifi")):
        raise ValueError("Missing interrupted certifi package directory")
    # Reject an unexpectedly newer installed distribution instead of downgrading it.
    installed_certifi = []
    for metadata in prefix.glob(
        "lib/python*/site-packages/certifi-*.dist-info/METADATA"
    ):
        headers = email.message_from_bytes(metadata.read_bytes())
        installed_certifi.append(headers.get("Version"))
        if headers.get("Version") not in (
            before["packages"]["certifi"]["version"],
            target_version,
        ):
            raise ValueError("Unexpected currently installed certifi version")
    if len(installed_certifi) > 1:
        raise ValueError("Duplicate installed certifi distribution")
    already_fixed = installed_certifi == [target_version]
    cache_paths = []
    for name in ([] if already_fixed else entry["cache_paths"]):
        path = unchanged_path(name)
        relative = path.relative_to(prefix)
        if not re.fullmatch(
            r"lib/python3\.[0-9]+/site-packages/certifi/__pycache__(/[a-zA-Z0-9_.-]+\.pyc)?",
            str(relative),
        ):
            raise ValueError(
                "Only exact generated certifi cache entries are recoverable"
            )
        info = path.lstat()
        if info.st_uid not in (0, owner.pw_uid) or info.st_nlink > (
            2 if path.is_dir() else 1
        ):
            raise ValueError("Unexpected cache ownership or hard links")
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise ValueError("Unexpected cache type")
        cache_paths.append(str(path))
    if apply:
        for name in cache_paths:
            # Never follow an owner-controlled intermediate path during root chown.
            descriptors = []
            try:
                descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
                descriptors.append(descriptor)
                components = Path(name).parts[1:]
                for index, component in enumerate(components):
                    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                    if index < len(components) - 1:
                        flags |= os.O_DIRECTORY
                    descriptor = os.open(component, flags, dir_fd=descriptor)
                    descriptors.append(descriptor)
                info = os.fstat(descriptor)
                if (
                    info.st_uid not in (0, owner.pw_uid)
                    or info.st_nlink > (2 if stat.S_ISDIR(info.st_mode) else 1)
                    or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
                ):
                    raise ValueError("Cache identity changed during recovery")
                os.fchown(descriptor, owner.pw_uid, owner.pw_gid)
            finally:
                for descriptor in reversed(descriptors):
                    os.close(descriptor)
    import grp

    return {
        "before": before,
        "group": grp.getgrgid(owner.pw_gid).gr_name,
        "cache_paths": cache_paths,
        "already_fixed": already_fixed,
    }


if __name__ == "__main__":
    print(
        json.dumps(
            inspect(
                json.loads(base64.b64decode(sys.argv[1])),
                sys.argv[2],
                sys.argv[3],
                target_version=sys.argv[4],
                apply="--apply" in sys.argv[5:],
            )
        )
    )
