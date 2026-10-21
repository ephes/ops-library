"""Filters for the ca_trust_consumers role.

They merge one Node.js trust flag into an existing NODE_OPTIONS value without
dropping anything already there, and find the NODE_OPTIONS value a systemd unit
or ``/etc/environment`` already sets.
"""

from __future__ import annotations

import re
import shlex

from ansible.errors import AnsibleFilterError

# Characters allowed in a NODE_OPTIONS value written to /etc/environment or a
# unit drop-in. Excludes quotes, backslashes, "%" (systemd specifiers) and "$"
# so the value needs no escaping in either file format.
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9 _=./:,+-]*$")

# Node refuses to start when both store selectors are given.
_CONFLICTS = {"--use-openssl-ca": "--use-bundled-ca", "--use-bundled-ca": "--use-openssl-ca"}

_ENV_LINE = re.compile(r"^\s*(?:export\s+)?NODE_OPTIONS=(.*)$")


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def node_options_with_flag(existing: str | None, flag: str) -> str:
    """Return ``existing`` NODE_OPTIONS with ``flag`` added once, order kept."""
    if not isinstance(flag, str) or not re.fullmatch(r"--[a-z][a-z0-9-]*", flag):
        raise AnsibleFilterError(f"invalid Node.js flag: {flag!r}")
    existing = (existing or "").strip()
    if not _SAFE_VALUE.match(existing):
        raise AnsibleFilterError(
            "existing NODE_OPTIONS contains characters this role does not rewrite "
            "(quotes, backslashes, %, $); set it explicitly instead"
        )
    tokens = existing.split()
    conflict = _CONFLICTS.get(flag)
    if conflict and conflict in tokens:
        raise AnsibleFilterError(
            f"existing NODE_OPTIONS already selects {conflict}, which Node.js "
            f"rejects together with {flag}; resolve it at its source"
        )
    if flag not in tokens:
        tokens.append(flag)
    return " ".join(tokens)


def environment_file_node_options(text: str | None) -> str:
    """Return the NODE_OPTIONS value set in a pam_env style file, or ''."""
    values = [
        _unquote(match.group(1))
        for line in (text or "").splitlines()
        if (match := _ENV_LINE.match(line))
    ]
    if len(values) > 1:
        raise AnsibleFilterError("NODE_OPTIONS is set more than once; keep one line")
    return values[0] if values else ""


def systemd_unit_node_options(cat_text: str | None, exclude_path: str = "") -> str:
    """Return NODE_OPTIONS from ``Environment=`` in ``systemctl cat`` output.

    Fragments are separated by ``# /path`` header lines; the fragment at
    ``exclude_path`` (this role's own drop-in) is ignored, so the result is
    what the unit sets without it. The last assignment wins and an empty
    ``Environment=`` resets earlier ones, as in systemd.
    """
    value = ""
    skip = False
    section = ""
    for raw in (cat_text or "").splitlines():
        line = raw.strip()
        if line.startswith("# /"):
            skip = bool(exclude_path) and line[2:].strip() == exclude_path
            section = ""
            continue
        if skip or not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line
            continue
        if section != "[Service]":
            continue
        key, sep, rhs = line.partition("=")
        if not sep or key.strip() != "Environment":
            continue
        rhs = rhs.strip()
        if not rhs:
            value = ""
            continue
        try:
            assignments = shlex.split(rhs)
        except ValueError as exc:
            raise AnsibleFilterError(f"cannot parse Environment= line: {exc}") from exc
        for assignment in assignments:
            name, eq, assigned = assignment.partition("=")
            if eq and name == "NODE_OPTIONS":
                value = assigned
    return value


class FilterModule:
    def filters(self):
        return {
            "ca_trust_node_options_with_flag": node_options_with_flag,
            "ca_trust_environment_file_node_options": environment_file_node_options,
            "ca_trust_systemd_unit_node_options": systemd_unit_node_options,
        }
