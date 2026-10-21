#!/usr/bin/env python3
"""Decide whether this role may own sudoers env_file, using sudo's own parser.

Runs `cvtsudoers -c /dev/null -i sudoers -d all -f json <sudoers>` (sudo's
supported exporter, with its own configuration file disabled; it applies
the real sudoers grammar and follows @include/@includedir) and inspects only
its Defaults entries. sudoers accepts one env_file, and the JSON has no source
file, so ownership is by exact value: an unbound Defaults entry setting
env_file to the managed path is ours.

Prints one JSON object {"verdict": ..., "reasons": [...]} and exits 0:
  none     no env_file anywhere (nothing to protect)
  managed  exactly one unbound env_file equal to the managed path
  refuse   anything else: another value, a scoped (bound) or negated entry,
           a duplicate, or cvtsudoers missing, failing or printing invalid JSON
Reasons name binding types and counts only, never values or other policy.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys


# Every input pinned: /etc/cvtsudoers.conf could otherwise filter Defaults
# (e.g. "defaults = global") or match only some users, hiding a conflict.
PINNED_ARGS = ("-c", "/dev/null", "-i", "sudoers", "-d", "all", "-f", "json")


def inspect(policy: dict, managed: str) -> dict:
    ours, reasons = 0, []
    for entry in policy.get("Defaults", []) or []:
        bindings = entry.get("Binding") or []
        for option in entry.get("Options", []) or []:
            if not isinstance(option, dict) or "env_file" not in option:
                continue
            value = option["env_file"]
            if bindings:
                kinds = sorted({key for binding in bindings for key in binding})
                reasons.append(f"env_file bound to {'/'.join(kinds)}")
            elif value is False:
                reasons.append("negated env_file")
            elif value != managed:
                reasons.append("env_file with an unmanaged value")
            else:
                ours += 1
    if ours > 1:
        reasons.append(f"managed env_file set {ours} times")
    if reasons:
        return {"verdict": "refuse", "reasons": reasons}
    return {"verdict": "managed" if ours else "none", "reasons": []}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cvtsudoers", required=True)
    parser.add_argument("--sudoers", required=True)
    parser.add_argument("--managed", required=True)
    args = parser.parse_args(argv)
    try:
        result = subprocess.run(
            [args.cvtsudoers, *PINNED_ARGS, args.sudoers],
            capture_output=True, text=True, check=False, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        report = {"verdict": "refuse", "reasons": [f"cvtsudoers could not run ({type(exc).__name__})"]}
    else:
        if result.returncode != 0:
            report = {"verdict": "refuse", "reasons": [f"cvtsudoers exited {result.returncode} (invalid sudoers?)"]}
        else:
            try:
                policy = json.loads(result.stdout)
                if not isinstance(policy, dict):
                    raise ValueError("not an object")
            except ValueError:
                report = {"verdict": "refuse", "reasons": ["cvtsudoers printed no valid JSON"]}
            else:
                report = inspect(policy, args.managed)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
