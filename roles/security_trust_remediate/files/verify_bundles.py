"""Verify user-owned bundle files using distro Python without importing their code."""

import ssl
import sys
from pathlib import Path

prefix = Path(sys.argv[1]).resolve(strict=True)
for value in sys.argv[2:]:
    path = Path(value).resolve(strict=True)
    if not path.is_relative_to(prefix):
        raise RuntimeError("Bundle escapes explicit virtual environment")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(str(path))
    names = {
        v
        for cert in context.get_ca_certs()
        for rdn in cert["subject"]
        for k, v in rdn
        if k == "commonName"
    }
    if names & {"emSign ECC Root CA - G3", "AAA Certificate Services"}:
        raise RuntimeError(str(path))
print("Verified allowlisted bundle files independently of application code")
