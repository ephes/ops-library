#!/usr/bin/env python3
"""Emit the Apple curl bundle with the two affected root sections removed."""
import re
import ssl
import sys
import os
import shutil
import tempfile
import time

AFFECTED = {"AAA Certificate Services", "emSign ECC Root CA - G3"}


def filter_bundle(text):
    output = []
    skip = False
    for line in text.splitlines(keepends=True):
        if line.startswith(("### ", "=== ")):
            skip = False
        if re.match(r"^=== .*/CN=(AAA Certificate Services|emSign ECC Root CA - G3)$", line.rstrip("\r\n")):
            skip = True
        if not skip:
            output.append(line)
    result = "".join(output)
    before = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    before.load_verify_locations(cadata=text)
    after = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    after.load_verify_locations(cadata=result)
    def subjects(context):
        return {tuple(tuple(pair) for rdn in cert["subject"] for pair in rdn) for cert in context.get_ca_certs()}
    old, new = subjects(before), subjects(after)
    removed = {subject for subject in old if any(key == "commonName" and value in AFFECTED for key, value in subject)}
    if not new or new != old - removed:
        raise ValueError("Bundle validation failed: unexpected certificate removal or affected root remains")
    return result


def apply_bundle(path, check=False):
    with open(path, encoding="utf-8") as bundle:
        original = bundle.read()
    result = filter_bundle(original)
    if result == original:
        return False
    if check:
        return True
    backup = str(path) + ".emudhra-" + str(time.time_ns()) + ".bak"
    shutil.copy2(path, backup)
    descriptor, temporary = tempfile.mkstemp(prefix=".cert-emudhra-", dir=os.path.dirname(path))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(result)
            output.flush()
            os.fsync(output.fileno())
        # Validate the exact bytes that will replace the bundle.
        with open(temporary, encoding="utf-8") as candidate:
            if filter_bundle(candidate.read()) != result:
                raise ValueError("Temporary bundle validation failed")
        shutil.copystat(path, temporary)
        stat = os.stat(path)
        os.chown(temporary, stat.st_uid, stat.st_gid)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print("Backup: " + backup)
    return True


if __name__ == "__main__":
    if sys.platform != "darwin":
        sys.exit("macOS only")
    print("CHANGED" if apply_bundle("/etc/ssl/cert.pem", check="--check" in sys.argv) else "UNCHANGED")
