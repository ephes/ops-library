#!/usr/bin/env python3
"""Maintain a JSSE trust-store copy without changing vendor cacerts or binaries."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile

# Affected trust anchors, not a list of eMudhra-owned roots. AAA cross-signs
# compromised eMudhra intermediates. Ubuntu's incident advisory explicitly
# distrusts both: https://ubuntu.com/blog/emudhra-ca-compromise-fixes-available
BLOCKED = {
    # CN=AAA Certificate Services, O=Comodo CA Limited (Sectigo cross-sign path)
    "D7A7A0FB5D7E2731D771E9484EBCDEF71D5F0C3E0A2948782BC83EE0EA699EF4",
    # CN=emSign ECC Root CA - G3, O=eMudhra Technologies Limited
    "86A1ECBA089C4A8D3BBE2734C612BA341D813E043CF9E8A862CD5C57A36BBE6B",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def certificates(text):
    result = {}
    for section in text.split("Alias name: ")[1:]:
        alias = section.splitlines()[0].strip()
        match = re.search(
            r"-----BEGIN CERTIFICATE-----(.*?)-----END CERTIFICATE-----", section, re.S
        )
        if match:
            result[alias] = (
                hashlib.sha256(base64.b64decode(match[1])).hexdigest().upper()
            )
    if not result:
        raise ValueError("No certificates found in keytool output")
    return result


def atomic_write(path, data, mode=0o644):
    if path.exists():
        current = path.stat()
        if current.st_uid != os.getuid():
            raise ValueError(f"Refusing to change ownership of {path}")
        mode = stat.S_IMODE(current.st_mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".java-trust-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--jdk", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--options", type=Path)
    parser.add_argument("--default-options", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if bool(args.options) != bool(args.default_options):
        parser.error("--options and --default-options must be supplied together")
    if args.options and not args.options.parent.is_dir():
        raise ValueError(
            "Refusing to create an IDE configuration directory before first launch; "
            "initialize the IDE normally or use a supported per-app VM options launcher"
        )
    source = args.jdk / "lib/security/cacerts"
    output = args.output
    manifest = output.with_name(output.name + ".emudhra.json")
    for path in (source, output, manifest, args.options):
        if path and (path.is_symlink() or (path.exists() and not path.is_file())):
            raise ValueError(f"Refusing non-regular file: {path}")
        if (
            path
            and path != source
            and path.exists()
            and path.stat().st_uid != os.getuid()
        ):
            raise ValueError(f"Refusing to change ownership of {path}")
    if source.resolve() == output.resolve():
        raise ValueError("Output must not replace vendor cacerts")
    source_hash = digest(source)
    old = json.loads(manifest.read_text()) if manifest.exists() else None
    # Preserve an existing custom jssecacerts on first adoption. Refuse to
    # overwrite later manual drift; the operator must reconcile it explicitly.
    if old and (not output.exists() or digest(output) != old["output_sha256"]):
        raise ValueError(
            "Managed trust store changed outside automation; reconcile before retry"
        )
    if old and old.get("custom_adopted") and old["source_sha256"] != source_hash:
        raise ValueError(
            "Vendor CA store changed; reconcile adopted custom trust before retry"
        )
    custom_adopted = old.get("custom_adopted", False) if old else output.exists()
    base = (
        source
        if not output.exists() or (old and old["source_sha256"] != source_hash)
        else output
    )
    keytool = str(args.jdk / "bin/keytool")

    def run(*options):
        return subprocess.run(
            [keytool, "-J-Duser.language=en", "-J-Duser.country=US", *options],
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    before = certificates(
        run("-list", "-rfc", "-keystore", str(base), "-storepass", "changeit")
    )
    remove = [alias for alias, fingerprint in before.items() if fingerprint in BLOCKED]
    options_bytes = None
    if args.options:
        existing = (
            args.options.read_bytes().decode("utf-8")
            if args.options.exists()
            else args.default_options.read_bytes().decode("utf-8")
        )
        desired = "-Djavax.net.ssl.trustStore=" + str(output)
        flags = [
            line
            for line in existing.splitlines()
            if line.startswith("-Djavax.net.ssl.trustStore=")
        ]
        if flags and flags != [desired]:
            raise ValueError(
                "Existing custom trustStore option requires operator reconciliation"
            )
        updated = (
            existing
            if flags
            else existing
            + ("" if not existing or existing.endswith("\n") else "\n")
            + desired
            + "\n"
        )
        if not args.options.exists() or updated != existing:
            options_bytes = updated.encode()
    store_change = bool(remove) or not output.exists() or base == source
    changed = store_change or options_bytes is not None or old is None
    if not args.check:
        if store_change:
            with tempfile.TemporaryDirectory(prefix="java-trust-") as directory:
                candidate = Path(directory) / "cacerts"
                shutil.copyfile(base, candidate)
                for alias in remove:
                    run(
                        "-delete",
                        "-alias",
                        alias,
                        "-keystore",
                        str(candidate),
                        "-storepass",
                        "changeit",
                    )
                after = certificates(
                    run(
                        "-list",
                        "-rfc",
                        "-keystore",
                        str(candidate),
                        "-storepass",
                        "changeit",
                    )
                )
                expected = {
                    alias: fp for alias, fp in before.items() if fp not in BLOCKED
                }
                if after != expected:
                    raise ValueError(
                        "Trust-store transformation changed unrelated certificates"
                    )
                atomic_write(output, candidate.read_bytes())
        if changed:
            atomic_write(
                manifest,
                (
                    json.dumps(
                        {
                            "source_sha256": source_hash,
                            "output_sha256": digest(output),
                            "custom_adopted": custom_adopted,
                        },
                        sort_keys=True,
                    )
                    + "\n"
                ).encode(),
            )
        if options_bytes is not None:
            atomic_write(args.options, options_bytes)
    print(
        json.dumps(
            {
                "changed": changed,
                "removed_aliases": remove,
                "output": str(output),
                "restart_required": bool(store_change or options_bytes is not None),
            }
        )
    )


if __name__ == "__main__":
    main()
