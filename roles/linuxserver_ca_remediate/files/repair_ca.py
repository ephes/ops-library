"""Repair image CA sources before Qt starts; never fetch packages at startup."""
import hashlib
from pathlib import Path
import re
import ssl
import subprocess

BLOCKED = {
    "d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4",
    "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b",
}
PEM = re.compile(rb"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", re.S)
SOURCES = (Path("/usr/share/ca-certificates"), Path("/usr/local/share/ca-certificates"))
# Qt's Linux backend uses fixed directories, bypassing SSL_CERT_FILE/DIR.
VERIFY = tuple(Path(path) for path in (
    "/etc/ssl/certs", "/usr/lib/ssl/certs", "/usr/share/ssl",
    "/etc/pki/ca-trust/extracted/pem/directory-hash", "/usr/local/ssl",
    "/var/ssl/certs", "/usr/local/ssl/certs", "/etc/openssl/certs",
    "/opt/openssl/certs", "/etc/ssl", "/etc/security/certificates"))


def fingerprint(pem):
    der = ssl.PEM_cert_to_DER_cert(pem.decode("ascii"))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cadata=pem.decode("ascii"))
    return hashlib.sha256(der).hexdigest()


def repair(sources=SOURCES, verify=VERIFY, update=None):
    retained = set()
    for root in sources:
        if not root.exists():
            continue
        for path in root.rglob("*.crt"):
            data = path.read_bytes()
            if b"-----BEGIN TRUSTED CERTIFICATE-----" in data:
                raise ValueError("Trust-annotated CA source needs explicit review")
            blocks = PEM.findall(data)
            affected = [block for block in blocks if fingerprint(block) in BLOCKED]
            retained.update(fingerprint(block) for block in blocks if block not in affected)
            if not affected:
                continue
            if len(affected) == len(blocks):
                # Unlink a symlink itself; do not modify its external target.
                path.unlink()
            else:
                if path.is_symlink():
                    raise ValueError("Mixed CA symlink source needs explicit review")
                for block in affected:
                    data = data.replace(block, b"")
                path.write_bytes(data)
    if not retained:
        raise ValueError("No unaffected CA sources; refusing unknown trust layout")
    if update is None:
        subprocess.run(["/usr/sbin/update-ca-certificates"], check=True)
    else:
        update()
    found = set()
    for root in verify:
        if not root.is_dir():
            continue
        for path in root.iterdir():
            if path.is_file():
                data = path.read_bytes()
                if b"-----BEGIN TRUSTED CERTIFICATE-----" in data:
                    raise ValueError("Trust-annotated native store needs explicit review")
                found.update(fingerprint(block) for block in PEM.findall(data))
    if found & BLOCKED or not retained.issubset(found):
        raise ValueError("Generated native trust failed blocked/retained certificate checks")
    return found


if __name__ == "__main__":
    repair()
