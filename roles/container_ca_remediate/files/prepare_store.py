#!/usr/bin/env python3
"""Create a replacement store from each container's own existing trust material."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import tempfile
import tarfile
import io

BLOCKED = {
    "d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4",
    "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b",
}
PEM = re.compile(rb"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", re.S)


def collect_certificates(blobs):
    certificates = {}
    removed = set()
    for data in blobs:
        if b"-----BEGIN TRUSTED CERTIFICATE-----" in data:
            raise ValueError("OpenSSL trust-annotated certificate needs explicit review")
        for raw in PEM.findall(data):
            pem = raw.decode("ascii")
            der = ssl.PEM_cert_to_DER_cert(pem)
            digest = hashlib.sha256(der).hexdigest()
            # Reject malformed material before it can replace a working store.
            probe = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            probe.load_verify_locations(cadata=pem)
            if digest in BLOCKED:
                removed.add(digest)
            else:
                certificates[digest] = pem + "\n"
    if not certificates:
        raise ValueError("No usable certificates found in container store")
    bundle = "".join(certificates[key] for key in sorted(certificates)).encode("ascii")
    return bundle, sorted(removed), sorted(certificates)


def run(*args):
    return subprocess.check_output(args)


def atomic_write(path, content):
    descriptor, temporary = tempfile.mkstemp(prefix=".ca-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def prepare(name, check=False, image=None, root_dir=Path("/var/lib/managed-container-ca")):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", name):
        raise ValueError("Invalid container name")
    if image is None:
        image_id = json.loads(run("docker", "inspect", "--format", "{{json .Image}}", name))
    else:
        image_id = json.loads(run("docker", "image", "inspect", "--format", "{{json .Id}}", image))
    # Read a dereferenced archive without extracting paths onto the host.
    # This preserves custom CA symlinks outside the bundle too.
    archive = (run("docker", "exec", name, "tar", "-chf", "-", "/etc/ssl/certs") if image is None else
               run("docker", "run", "--rm", "--pull", "never", "--network", "none", "--read-only",
                   "--entrypoint", "tar", image, "-chf", "-", "/etc/ssl/certs"))
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as source:
        blobs = []
        for member in source:
            if member.isfile() or member.islnk():
                content = source.extractfile(member)
                blobs.append(content.read())
        bundle, removed, certificates = collect_certificates(blobs)
    root = root_dir / name
    target = root / "bundle.pem"
    manifest = json.dumps({"container": name, "image": image_id, "removed_sha256": removed,
                           "retained_sha256": certificates}, indent=2).encode() + b"\n"
    manifest_path = root / "manifest.json"
    changed = (not target.exists() or target.read_bytes() != bundle or
               not manifest_path.exists() or manifest_path.read_bytes() != manifest)
    if not check:
        root.mkdir(parents=True, exist_ok=True, mode=0o755)
        (root / "empty").mkdir(exist_ok=True, mode=0o755)
        if any((root / "empty").iterdir()):
            raise ValueError("Replacement empty trust directory must remain empty")
        if changed:
            atomic_write(target, bundle)
        if not (root / "manifest.json").exists() or (root / "manifest.json").read_bytes() != manifest:
            atomic_write(root / "manifest.json", manifest)
    print("CHANGED" if changed else "UNCHANGED")
    print(json.dumps({"container": name, "image": image_id, "removed": removed, "retained_count": len(certificates)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--image")
    args = parser.parse_args()
    prepare(args.name, check=args.check, image=args.image)
