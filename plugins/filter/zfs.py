"""Filters for values accepted by ZFS size properties."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from ansible.errors import AnsibleFilterError

_ZFS_SIZE_RE = re.compile(
    r"^([0-9]+(?:[.][0-9]+)?)[ ]*([KMGTPEZ]?)(?:I?B)?$",
    re.IGNORECASE,
)
_ZFS_SIZE_POWERS = {unit: power for power, unit in enumerate(" KMGTPEZ")}
_ZFS_SIZE_POWERS[""] = 0


def zfs_size_to_bytes(value: Any) -> int:
    """Convert a positive ZFS size to the exact integer ZFS stores.

    ZFS scales decimal input by a binary unit and truncates the result. Ansible's
    built-in ``human_to_bytes`` rounds instead, which differs by one byte for
    values such as ``1.1T`` and prevents idempotent property comparisons.
    """

    text = str(value).strip()
    match = _ZFS_SIZE_RE.fullmatch(text)
    if match is None:
        raise AnsibleFilterError(f"Invalid ZFS size value: {value!r}")

    number, unit = match.groups()
    multiplier = 1024 ** _ZFS_SIZE_POWERS[unit.upper()]
    return int(Decimal(number) * multiplier)


class FilterModule:
    """Expose collection filters to Ansible."""

    def filters(self) -> dict[str, Any]:
        return {"zfs_size_to_bytes": zfs_size_to_bytes}
