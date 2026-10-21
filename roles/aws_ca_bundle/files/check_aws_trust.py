"""Read only selected TLS environment settings, never print service secrets."""

import pwd
import re
import shlex
import ssl
import subprocess
import sys
from pathlib import Path


def check(unit, bundle, mode):
    if not re.fullmatch("[a-zA-Z0-9_.@-]+\\.service", unit):
        raise RuntimeError("Invalid service name")
    if bundle != "/etc/ssl/certs/ca-certificates.crt":
        raise RuntimeError("Only distro trust bundle is supported")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(bundle)
    names = {
        v
        for c in context.get_ca_certs()
        for r in c["subject"]
        for k, v in r
        if k == "commonName"
    }
    if names & {"AAA Certificate Services", "emSign ECC Root CA - G3"}:
        raise RuntimeError("OS trust is not remediated")

    def show(prop):
        return subprocess.check_output(
            ["systemctl", "show", unit, "-p", prop, "--value"], text=True
        ).strip()

    pid = show("MainPID")
    if not (pid.isdigit() and int(pid) > 0):
        raise RuntimeError("Service must be running before/after remediation")
    environment = dict(
        p.partition(b"=")[::2]
        for p in Path("/proc", pid, "environ").read_bytes().split(b"\x00")
        if b"=" in p
    )
    actual = environment.get(b"AWS_CA_BUNDLE", b"").decode()
    if actual not in ("", bundle):
        raise RuntimeError("Existing runtime AWS_CA_BUNDLE needs operator review")
    for entry in shlex.split(show("Environment")):
        if entry.startswith("AWS_CA_BUNDLE="):
            if entry.partition("=")[2] != bundle:
                raise RuntimeError("Existing unit AWS_CA_BUNDLE needs operator review")
    home = environment.get(b"HOME", b"").decode()
    if not home:
        home = pwd.getpwuid(Path("/proc", pid).stat().st_uid).pw_dir
    config = Path(
        environment.get(b"AWS_CONFIG_FILE", (home + "/.aws/config").encode()).decode()
    )
    if not config.is_absolute():
        raise RuntimeError("Relative AWS_CONFIG_FILE needs operator review")
    if config.exists():
        for line in config.read_text().splitlines():
            match = re.match("^\\s*ca_bundle\\s*=\\s*(.*?)\\s*$", line)
            if match:
                if match.group(1) != bundle:
                    raise RuntimeError(
                        "Existing shared-config ca_bundle needs operator review"
                    )
    raw = show("EnvironmentFiles")
    entries = re.findall("(/[^ ]+) \\(ignore_errors=(?:yes|no)\\)", raw)
    if re.sub("(/[^ ]+) \\(ignore_errors=(?:yes|no)\\)", "", raw).strip():
        raise RuntimeError("Cannot safely inspect every EnvironmentFiles entry")
    for value in entries:
        path = Path(value)
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            if re.match("^\\s*(?:export\\s+)?AWS_CA_BUNDLE\\s*=", line):
                values = shlex.split(line.partition("=")[2], comments=True)
                if values != [bundle]:
                    raise RuntimeError(
                        "Existing EnvironmentFile AWS_CA_BUNDLE needs operator review"
                    )
    if mode == "verify":
        if actual != bundle:
            raise RuntimeError(
                "Restarted service did not inherit the supported bundle override"
            )
    return {"uses_system_bundle": actual == bundle}


if __name__ == "__main__":
    import json

    print(json.dumps(check(*sys.argv[1:])))
