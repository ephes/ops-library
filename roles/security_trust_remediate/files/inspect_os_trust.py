"""Verify eager PEM trust and hashed-directory contents after distro CA updates."""

import ssl
from pathlib import Path

BAD = {"emSign ECC Root CA - G3", "AAA Certificate Services"}


def subjects(context):
    return {
        v
        for cert in context.get_ca_certs()
        for rdn in cert["subject"]
        for k, v in rdn
        if k == "commonName"
    }


context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
context.load_verify_locations("/etc/ssl/certs/ca-certificates.crt")
if subjects(context) & BAD:
    raise RuntimeError(subjects(context) & BAD)
for path in Path("/etc/ssl/certs").iterdir():
    if not path.is_file():
        continue
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(str(path))
    except ssl.SSLError:
        continue
    if subjects(context) & BAD:
        raise RuntimeError(str(path))
for line in Path("/etc/ca-certificates.conf").read_text().splitlines():
    if line.startswith(("!", "#")):
        continue
    if any(
        name in line for name in ("AAA_Certificate_Services", "emSign_ECC_Root_CA_-_G3")
    ):
        raise RuntimeError(line)
print(
    "Verified eager OS bundle, hashed certificate directory and selected distro roots"
)
