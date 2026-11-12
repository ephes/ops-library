#!/usr/bin/env python3
"""Remove credentials that a MinIO metadata backup does not need.

``mc admin cluster bucket export`` writes every bucket's remote targets
(``<bucket>/bucket-targets.json``, XML despite the name) with the target's
access key *and secret key*. For a replication target set up with the source's
root credentials that is the root password in clear text. The env file copy
(``/etc/default/minio``) holds the root password as well. Neither is needed to
restore: the root credentials live in the deployment secrets, and remote
targets are re-created by the replication setup.

The targets files are dropped from the export instead of emptied: an import of
a target without credentials could replace a working target on a running
MinIO, while an import without the file leaves existing targets alone.

Usage:
    redact_backup_secrets.py bucket-zip ZIP     drop remote targets from ZIP (in place)
    redact_backup_secrets.py env SRC DEST        copy SRC to DEST, values redacted
    redact_backup_secrets.py verify-absent PATH... < SECRET
        fail when SECRET (all of stdin, as is) appears in any file below PATH
        or in any member of a ZIP there (names only are printed)

The env mode handles one assignment per line. A backslash continuation or a
quoted value that does not close on its line is refused rather than guessed
at, so a multi-line secret cannot slip through.

Nothing here prints a value. Each mode verifies its own result and exits
non-zero when a credential would survive, so a backup never succeeds with one.
"""

from __future__ import annotations

import html
import io
import json
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

REDACTED = "REDACTED-BY-MINIO-BACKUP"
TARGETS_NAME = "bucket-targets.json"
ENV_SECRET_KEY = re.compile(r"(PASSWORD|SECRET|TOKEN)", re.IGNORECASE)
ENV_LINE = re.compile(r"^(\s*(?:export\s+)?)([A-Za-z_][A-Za-z0-9_]*)(\s*=\s*)(.*)$")


class RedactError(Exception):
    pass


def is_targets_entry(name: str) -> bool:
    return PurePosixPath(name).name == TARGETS_NAME


def drop_bucket_targets(path: Path) -> int:
    """Rewrite the bucket export ZIP without remote targets; return the count."""
    dropped = 0
    fd, tmp_name = tempfile.mkstemp(prefix=".redact-", dir=path.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with zipfile.ZipFile(path) as src, zipfile.ZipFile(
            tmp, "w", compression=zipfile.ZIP_DEFLATED
        ) as dst:
            for info in src.infolist():
                if not info.is_dir() and is_targets_entry(info.filename):
                    dropped += 1
                    continue
                dst.writestr(info, src.read(info))
        os.chmod(tmp, 0o600)
        with zipfile.ZipFile(tmp) as check:
            if check.testzip() is not None:
                raise RedactError("rewritten bucket export is corrupt")
            if any(is_targets_entry(name) for name in check.namelist()):
                raise RedactError(f"{TARGETS_NAME} survived the rewrite")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return dropped


def _single_line_value(value: str) -> bool:
    """True when ``value`` is complete on its line: no continuation, and a
    quoted value closes (honouring backslash escapes inside double quotes)
    with nothing but whitespace after it."""
    value = value.rstrip()
    if value.endswith("\\"):
        return False
    quote = value[:1]
    if quote not in ("'", '"'):
        return '"' not in value and "'" not in value
    index = 1
    while index < len(value):
        char = value[index]
        if char == "\\" and quote == '"':
            index += 2
            continue
        if char == quote:
            return value[index + 1 :].strip() == ""
        index += 1
    return False


def redact_env(text: str) -> tuple[str, int]:
    lines = []
    count = 0
    for number, line in enumerate(text.splitlines(keepends=True), start=1):
        body = line.rstrip("\r\n")
        ending = line[len(body) :]
        if body.rstrip().endswith("\\"):
            raise RedactError(
                f"env file line {number} continues on the next line; refusing to guess"
            )
        match = ENV_LINE.match(body)
        if match and not _single_line_value(match.group(4)):
            raise RedactError(
                f"env file line {number} has a multi-line value; refusing to guess"
            )
        if match and ENV_SECRET_KEY.search(match.group(2)) and match.group(4):
            body = f"{match.group(1)}{match.group(2)}{match.group(3)}{REDACTED}"
            count += 1
        lines.append(body + ending)
    return "".join(lines), count


def write_env(src: Path, dest: Path) -> int:
    text, count = redact_env(src.read_text(encoding="utf-8"))
    dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(dest, 0o600)
    return count


def _go_xml_escape(text: str) -> str:
    """encoding/xml EscapeText, which MinIO's XML exports use."""
    table = {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&#34;",
        "'": "&#39;",
        "\t": "&#x9;",
        "\n": "&#xA;",
        "\r": "&#xD;",
    }
    return "".join(table.get(char, char) for char in text)


def _go_json_escape(text: str) -> str:
    """encoding/json string escaping (HTML-safe, the json.Marshal default)."""
    out = []
    for char in text:
        code = ord(char)
        if char in ('"', "\\"):
            out.append("\\" + char)
        elif char in "\n\r\t":
            out.append({"\n": "\\n", "\r": "\\r", "\t": "\\t"}[char])
        elif code < 0x20 or char in "<>&" or code in (0x2028, 0x2029):
            out.append(f"\\u{code:04x}")
        else:
            out.append(char)
    return "".join(out)


def secret_forms(secret: str) -> list[bytes]:
    """The secret raw and as XML or JSON encoders (Go's and Python's) write it."""
    forms = {
        secret,
        _go_xml_escape(secret),
        _go_json_escape(secret),
        html.escape(secret, quote=True),
        html.escape(secret, quote=False),
        json.dumps(secret)[1:-1],
        json.dumps(secret, ensure_ascii=False)[1:-1],
    }
    return sorted(form.encode() for form in forms if form)


def _contains(data: bytes, needles: list[bytes], depth: int = 0) -> bool:
    if any(needle in data for needle in needles):
        return True
    if depth < 2 and data[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                return any(
                    _contains(zf.read(info), needles, depth + 1)
                    for info in zf.infolist()
                    if not info.is_dir()
                )
        except zipfile.BadZipFile:
            return False
    return False


def verify_absent(paths: list[Path], secret: str) -> list[str]:
    """Paths of files (or ZIPs) below ``paths`` that contain ``secret``."""
    if not secret:
        raise RedactError("no secret on stdin")
    needles = secret_forms(secret)
    leaking = []
    for root in paths:
        files = (
            [root]
            if root.is_file()
            else sorted(p for p in root.rglob("*") if p.is_file())
        )
        for path in files:
            if not path.is_symlink() and _contains(path.read_bytes(), needles):
                leaking.append(str(path))
    return leaking


def main(argv: list[str]) -> int:
    try:
        if len(argv) == 2 and argv[0] == "bucket-zip":
            count = drop_bucket_targets(Path(argv[1]))
            print(f"dropped {count} {TARGETS_NAME} file(s) (remote target credentials)")
        elif len(argv) == 3 and argv[0] == "env":
            count = write_env(Path(argv[1]), Path(argv[2]))
            print(f"redacted {count} secret value(s) in the env file copy")
        elif len(argv) >= 2 and argv[0] == "verify-absent":
            leaking = verify_absent(
                [Path(a) for a in argv[1:]],
                sys.stdin.read(),
            )
            if leaking:
                print(
                    "the root password would end up in the backup: "
                    + ", ".join(leaking),
                    file=sys.stderr,
                )
                return 1
            print("the root password appears in no snapshot file")
        else:
            print(__doc__, file=sys.stderr)
            return 2
    except (RedactError, OSError, zipfile.BadZipFile, UnicodeDecodeError) as exc:
        print(f"redact_backup_secrets: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
