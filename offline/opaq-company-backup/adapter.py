"""Offline fixed synthetic package adapter; no network or enrollment capability."""

import argparse
import io
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import uuid
import zipfile

REVISION = "8f99443f910105153180255b26f26768a0f80bec"  # pragma: allowlist secret (public code pin)
VALIDATOR = "experiments/2026-10-03-bound-journal-recovery/recovery.py"
SOURCE_SHA256 = "0718397eadc8cfa8c96a04ba61f7c29bc686fb58159222c76a38ed371d0ae047"  # pragma: allowlist secret (validator archive pin)
TARGET = "opaq-company-synthetic"
BUCKET = "synthetic-backups"
FORMAT = "synthetic-bound-journal-recovery-v1"
MAX_PACKAGE = 325 * 1024 * 1024 + 4096
MEMBERS = {"bridge.zip", "bound.sqlite", "current-enrichment.json", "manifest.json"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def private_root(path):
    path = Path(path).absolute()
    require(
        not path.is_symlink() and path.is_dir(), "explicit scratch directory required"
    )
    require(
        stat.S_IMODE(path.stat().st_mode) & 0o077 == 0, "private directory required"
    )
    return path


def regular(path):
    path = Path(path)
    info = path.lstat()
    require(
        stat.S_ISREG(info.st_mode) and info.st_size <= MAX_PACKAGE,
        "bounded regular package required",
    )
    return path


def copy_private(source, destination):
    # Inputs and parents must be controlled by the offline caller; no hostile
    # concurrent filesystem-writer containment is claimed.
    source = regular(source)
    with source.open("rb") as src, Path(destination).open("xb") as dst:
        os.chmod(destination, 0o600)
        total = 0
        while block := src.read(1024 * 1024):
            total += len(block)
            require(total <= MAX_PACKAGE, "growing package refused")
            dst.write(block)
    return Path(destination)


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key refused")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("nonfinite JSON refused")

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except RecursionError as exc:
        raise ValueError("bounded JSON depth required") from exc


def scope(package):
    with zipfile.ZipFile(regular(package)) as archive:
        rows = archive.infolist()
        require(
            len(rows) == 4 and {r.filename for r in rows} == MEMBERS,
            "exact four members required",
        )
        row = archive.getinfo("manifest.json")
        require(row.file_size <= 4 * 1024 * 1024, "bounded manifest required")
        require(
            row.compress_type == zipfile.ZIP_STORED, "uncompressed manifest required"
        )
        doc = decode(archive.read(row))
    require(isinstance(doc, dict), "manifest object required")
    require(
        doc.get("format") == FORMAT and doc.get("synthetic") is True,
        "synthetic schema required",
    )
    require(
        doc.get("company") == "synthetic-opaq"
        and doc.get("account") == "synthetic-company-bank",
        "company identity mismatch",
    )
    return doc


class Validator:
    """Execute only P's digest-pinned private dependency closure in new scratch."""

    def __init__(self, source_archive, python):
        archive = regular(source_archive)
        require(archive.stat().st_size == 942080, "exact source archive size required")
        self.source = archive.read_bytes()
        require(
            len(self.source) == 942080
            and hashlib.sha256(self.source).hexdigest() == SOURCE_SHA256,
            "validator source checksum mismatch",
        )
        self.python = str(Path(python).absolute())

    def restore(self, package, scratch):
        scope(package)
        scratch = private_root(scratch)
        with tempfile.TemporaryDirectory(prefix="validator-", dir=scratch) as temporary:
            export = Path(temporary) / "source"
            export.mkdir(mode=0o700)
            staging = Path(temporary) / "restore"
            staging.mkdir(mode=0o700)
            with tarfile.open(fileobj=io.BytesIO(self.source), mode="r:") as archive:
                files = 0
                for row in archive.getmembers():
                    name = Path(row.name)
                    require(
                        not name.is_absolute() and ".." not in name.parts,
                        "relative source path required",
                    )
                    destination = export / name
                    if row.isdir():
                        destination.mkdir(parents=True, exist_ok=True, mode=0o700)
                        continue
                    require(
                        row.isfile() and row.size <= 1024 * 1024,
                        "bounded regular source member required",
                    )
                    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    with archive.extractfile(row) as src, destination.open("xb") as dst:
                        destination.chmod(0o600)
                        dst.write(src.read())
                    files += 1
                require(files == 108, "exact validator closure required")
            environment = {"PATH": os.defpath, "HOME": str(export)}
            bootstrap = "import sys,runpy;assert sys.version_info >= (3,14);sys.path.insert(0,sys.argv.pop(1));entry=sys.argv.pop(1);sys.argv[0]=entry;runpy.run_path(entry,run_name='__main__')"
            try:
                result = subprocess.run(
                    [
                        self.python,
                        "-I",
                        "-S",
                        "-B",
                        "-c",
                        bootstrap,
                        str(export / "src"),
                        str(export / VALIDATOR),
                        "restore",
                        "--package",
                        str(Path(package).absolute()),
                        "--scratch-root",
                        str(staging),
                    ],
                    cwd=export,
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=60,
                )
                require(result.returncode == 0, "pinned validator refused package")
                restored = Path(result.stdout.decode().strip())
                require(
                    restored.parent == staging
                    and restored.name.startswith("opaq-bound-recovered-"),
                    "invalid validator restore output",
                )
                marker = decode((restored / "RECOVERY.json").read_bytes())
                require(
                    marker.get("state") == "inactive-scratch"
                    and all(
                        marker.get(k) == "disabled"
                        for k in ("import", "register", "decide")
                    ),
                    "inactive restore required",
                )
                destination = scratch / restored.name
                require(not destination.exists(), "fresh restore output required")
                restored.rename(destination)
                return destination
            except BaseException:
                # TemporaryDirectory removes only this invocation-owned staging,
                # including interrupted validator output, never active state.
                raise


class LocalFake:
    """Explicit disposable object root; never uses network/credentials."""

    def __init__(self, root):
        self.root = private_root(root)

    def path(self, key):
        require(
            isinstance(key, str)
            and re.fullmatch(r"opaq-company-synthetic/[0-9a-f]{32}\.zip", key)
            is not None,
            "fixed object key required",
        )
        return self.root / key.split("/")[1]

    def upload(self, source, key):
        return copy_private(source, self.path(key))

    def download(self, key, destination):
        return copy_private(self.path(key), destination)


def backup(package, expected_sha256, validator, transport, scratch):
    require(
        isinstance(expected_sha256, str)
        and re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is not None,
        "explicit SHA256 required",
    )
    scratch = private_root(scratch)
    with tempfile.TemporaryDirectory(prefix="opaq-adapter-", dir=scratch) as temporary:
        work = Path(temporary)
        admitted = copy_private(package, work / "input.zip")
        require(digest(admitted) == expected_sha256, "input checksum mismatch")
        validator.restore(admitted, work)
        key = f"{TARGET}/{uuid.uuid4().hex}.zip"
        transport.upload(admitted, key)
        fetched = transport.download(key, work / "readback.zip")
        require(
            digest(fetched) == expected_sha256
            and fetched.stat().st_size == admitted.stat().st_size,
            "full readback mismatch",
        )
        validator.restore(fetched, work)
        return {
            "success": True,
            "bucket": BUCKET,
            "key": key,
            "size_bytes": fetched.stat().st_size,
            "checksum_sha256": expected_sha256,
            "file_count": 4,
            "manifest": {
                "format": FORMAT,
                "validator_revision": REVISION,
                "synthetic": True,
            },
        }


def restore(result, validator, transport, scratch):
    require(
        isinstance(result, dict) and result.get("file_count") == 4,
        "fixed result object required",
    )
    require(
        result.get("success") is True and result.get("bucket") == BUCKET,
        "fixed successful object identity required",
    )
    require(
        result.get("manifest")
        == {"format": FORMAT, "validator_revision": REVISION, "synthetic": True},
        "pinned result schema required",
    )
    require(isinstance(result.get("key"), str), "explicit object key required")
    require(
        isinstance(result.get("size_bytes"), int)
        and not isinstance(result.get("size_bytes"), bool)
        and 0 < result["size_bytes"] <= MAX_PACKAGE,
        "bounded object size required",
    )
    checksum = result.get("checksum_sha256")
    require(
        isinstance(checksum, str) and re.fullmatch(r"[0-9a-f]{64}", checksum),
        "result checksum required",
    )
    scratch = private_root(scratch)
    with tempfile.TemporaryDirectory(prefix="opaq-download-", dir=scratch) as temporary:
        fetched = transport.download(result["key"], Path(temporary) / "package.zip")
        require(
            digest(fetched) == checksum
            and fetched.stat().st_size == result.get("size_bytes"),
            "restore checksum/size mismatch",
        )
        return validator.restore(fetched, scratch)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("--validator-source", required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--objects", required=True)
    parser.add_argument("--scratch", required=True)
    parser.add_argument("--package")
    parser.add_argument("--sha256")
    parser.add_argument("--result")
    args = parser.parse_args()
    try:
        validator = Validator(args.validator_source, args.python)
        transport = LocalFake(args.objects)
        if args.action == "backup":
            result = backup(
                args.package, args.sha256, validator, transport, args.scratch
            )
        else:
            require(args.result is not None, "explicit result file required")
            result_file = regular(args.result)
            require(result_file.stat().st_size <= 65536, "bounded result file required")
            directory = restore(
                decode(result_file.read_bytes()),
                validator,
                transport,
                args.scratch,
            )
            result = {
                "success": True,
                "state": "inactive-scratch",
                "directory": str(directory),
            }
        print("ECHOPORT_RESULT:" + json.dumps(result, sort_keys=True))
    except (
        OSError,
        ValueError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
        zipfile.BadZipFile,
    ):
        print('ECHOPORT_RESULT:{"success":false,"error":"offline adapter refused"}')
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
