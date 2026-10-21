#!/usr/bin/env python3
"""Report forbidden root certificates visible to Go and OpenSSL clients.

Scans the given files, and every entry (symlinks followed) of the given
directories, the way Go's crypto/x509 builds its Linux system pool and OpenSSL
resolves its default CA directory. Prints one JSON object; exits 0 unless the
arguments are invalid. Read-only, standard library only.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import sys

_PEM = re.compile(
    rb"-----BEGIN (TRUSTED )?CERTIFICATE-----\s*(.+?)\s*-----END (?:TRUSTED )?CERTIFICATE-----",
    re.DOTALL,
)
_SHA256 = re.compile(r"^[0-9A-F]{64}$")


def first_der_element(data: bytes) -> bytes:
    """Return the first DER TLV (an OpenSSL TRUSTED CERTIFICATE has aux data after it)."""
    if len(data) < 2:
        raise ValueError("short DER")
    length = data[1]
    offset = 2
    if length & 0x80:
        count = length & 0x7F
        if count == 0 or count > 4 or len(data) < 2 + count:
            raise ValueError("bad DER length")
        length = int.from_bytes(data[2 : 2 + count], "big")
        offset = 2 + count
    end = offset + length
    if end > len(data):
        raise ValueError("truncated DER")
    return data[:end]


def certificate_fingerprints(blob: bytes) -> list[str]:
    fingerprints = []
    for match in _PEM.finditer(blob):
        try:
            der = base64.b64decode(b"".join(match.group(2).split()), validate=True)
            if match.group(1):
                der = first_der_element(der)
        except (binascii.Error, ValueError):
            continue
        fingerprints.append(hashlib.sha256(der).hexdigest().upper())
    return fingerprints


def scan(paths: list[str], forbidden: set[str]) -> dict:
    files: list[str] = []
    for path in paths:
        if os.path.isdir(path):
            files.extend(os.path.join(path, name) for name in sorted(os.listdir(path)))
        elif os.path.exists(path):
            files.append(path)
    report: dict = {"files_scanned": 0, "certificates": 0, "unreadable": 0, "found": []}
    for path in files:
        if not os.path.isfile(path):  # follows symlinks; skips directories
            continue
        try:
            with open(path, "rb") as handle:
                blob = handle.read()
        except OSError:
            report["unreadable"] += 1
            continue
        report["files_scanned"] += 1
        for fingerprint in certificate_fingerprints(blob):
            report["certificates"] += 1
            if fingerprint in forbidden:
                report["found"].append({"path": path, "sha256": fingerprint})
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forbid", action="append", default=[], help="SHA-256 fingerprint (hex)")
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args(argv)
    forbidden = {value.replace(":", "").upper() for value in args.forbid}
    bad = sorted(value for value in forbidden if not _SHA256.match(value))
    if not forbidden or bad:
        parser.error(f"need valid --forbid SHA-256 fingerprints, got {bad or 'none'}")
    print(json.dumps(scan(args.paths, forbidden), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
