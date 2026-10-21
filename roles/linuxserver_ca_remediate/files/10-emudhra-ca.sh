#!/bin/bash
# LinuxServer custom init ignores failed scripts, so never return on failure.
set -u
if /usr/bin/python3 /run/managed-ca-init/repair_ca.py; then
    echo "[managed-ca] affected roots absent; native trust verified"
else
    echo "[managed-ca] trust repair failed; halting before application startup" >&2
    /run/s6/basedir/bin/halt || true
    # Keep init-custom-files blocked even if shutdown cannot be requested.
    while :; do sleep 3600; done
fi
