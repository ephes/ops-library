"""Read-only metadata and TLS bundle inventory; run with the target interpreter."""

import hashlib
import importlib.metadata
import json
import os
import platform
import ssl
import sys
from pathlib import Path


def inspect():
    config = Path(sys.prefix, "pyvenv.cfg").read_text().lower()
    if any(
        line.replace(" ", "") == "include-system-site-packages=true"
        for line in config.splitlines()
    ):
        raise RuntimeError("System site-packages venv is distribution-managed")
    packages = {
        d.metadata["Name"]: {"version": d.version, "requires": d.requires or []}
        for d in importlib.metadata.distributions()
        if d.metadata["Name"]
    }
    bundles = {}
    for name in ("certifi", "pip._vendor.certifi"):
        try:
            module = __import__(name, fromlist=["where"])
        except ImportError:
            continue
        path = module.where()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(path)
        bundles[name] = {
            "path": path,
            "sha256": hashlib.sha256(
                __import__("pathlib").Path(path).read_bytes()
            ).hexdigest(),
            "subjects": [c["subject"] for c in context.get_ca_certs()],
        }
    return {
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
        "packages": packages,
        "bundles": bundles,
        "marker_environment": {
            "implementation_name": sys.implementation.name,
            "implementation_version": platform.python_version(),
            "os_name": os.name,
            "platform_machine": platform.machine(),
            "platform_release": platform.release(),
            "platform_system": platform.system(),
            "platform_version": platform.version(),
            "python_full_version": platform.python_version(),
            "python_version": ".".join(map(str, sys.version_info[:2])),
            "platform_python_implementation": platform.python_implementation(),
            "sys_platform": sys.platform,
            "extra": "",
        },
    }


if __name__ == "__main__":
    print(json.dumps(inspect()))
