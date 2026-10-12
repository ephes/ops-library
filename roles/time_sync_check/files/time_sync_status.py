#!/usr/bin/env python3
"""Report whether this host's clock is NTP-synchronized. Read-only.

Prints one JSON object describing the kernel sync flag, the active time
service (chrony or systemd-timesyncd), its measured offset and the problems
found. Nothing is started, stopped or adjusted. Standard library only.

Exit status is 0 unless ``--strict`` is given and problems were found (1).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time

SERVICES = (
    ("chrony", ("chrony.service", "chronyd.service")),
    ("systemd-timesyncd", ("systemd-timesyncd.service",)),
)
# systemd format_timespan() units, in seconds.
TIMESPAN_UNITS = {
    "y": 31557600.0,
    "month": 2629800.0,
    "w": 604800.0,
    "d": 86400.0,
    "h": 3600.0,
    "min": 60.0,
    "m": 60.0,
    "s": 1.0,
    "ms": 1e-3,
    "us": 1e-6,
    "µs": 1e-6,
    "μs": 1e-6,
}
TIMESPAN_PART = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*([a-zµμ]+)")


def run(argv: list[str], timeout: float = 10.0) -> tuple[int, str]:
    """Run a command; return (rc, stdout). A missing command gives rc 127."""
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False
        )
    except FileNotFoundError:
        return 127, ""
    except (OSError, subprocess.SubprocessError):
        return 126, ""
    return result.returncode, result.stdout


def parse_timespan(text: str) -> float | None:
    """Parse a systemd time span such as ``+1.234ms`` or ``-2h 3min 4s``."""
    text = text.strip()
    if not text:
        return None
    sign = -1.0 if text.startswith("-") else 1.0
    body = text.lstrip("+-").strip()
    if body == "0":
        return 0.0
    total = 0.0
    position = 0
    matched = False
    for match in TIMESPAN_PART.finditer(body):
        if body[position : match.start()].strip():
            return None
        unit = TIMESPAN_UNITS.get(match.group(2))
        if unit is None:
            return None
        total += float(match.group(1)) * unit
        position = match.end()
        matched = True
    if not matched or body[position:].strip():
        return None
    return sign * total


def parse_timedatectl_show(text: str) -> bool | None:
    """Return the kernel sync flag from ``timedatectl show`` output."""
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "NTPSynchronized":
            value = value.strip().lower()
            if value in ("yes", "no"):
                return value == "yes"
    return None


def parse_timesync_status(text: str) -> float | None:
    """Return the offset in seconds from ``timedatectl timesync-status``."""
    for line in text.splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "Offset":
            return parse_timespan(value)
    return None


def parse_chrony_tracking(text: str) -> tuple[float | None, bool | None]:
    """Return (offset seconds, synchronized) from ``chronyc -c tracking``.

    CSV fields: reference id, name, stratum, reference time, system time
    offset, last offset, RMS offset, frequency, residual frequency, skew,
    root delay, root dispersion, update interval, leap status.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return None, None
    fields = lines[-1].split(",")
    if len(fields) < 14:
        return None, None
    try:
        offset = float(fields[4])
        stratum = int(fields[2])
    except ValueError:
        return None, None
    leap = fields[13].strip().lower()
    synchronized = leap != "not synchronised" and stratum > 0
    return offset, synchronized


def evaluate(
    *,
    kernel_synchronized: bool | None,
    source: str | None,
    source_synchronized: bool | None,
    offset_seconds: float | None,
    max_offset_seconds: float,
) -> tuple[list[str], list[str]]:
    """Return (problems, notes) for the collected facts."""
    problems: list[str] = []
    notes: list[str] = []
    if source is None:
        problems.append(
            "no time synchronization service is active "
            "(looked for chrony and systemd-timesyncd)"
        )
    if kernel_synchronized is False:
        problems.append("the system clock is not synchronized (NTPSynchronized=no)")
    elif kernel_synchronized is None:
        notes.append("timedatectl did not report NTPSynchronized")
    if source_synchronized is False:
        problems.append(f"{source} reports that it is not synchronized")
    if (
        source is not None
        and kernel_synchronized is None
        and source_synchronized is None
    ):
        problems.append(f"could not confirm that {source} is synchronized")
    if offset_seconds is None:
        if source is not None:
            notes.append(f"{source} did not report an offset")
    elif abs(offset_seconds) > max_offset_seconds:
        problems.append(
            f"clock offset {offset_seconds:+.6f}s exceeds the allowed "
            f"{max_offset_seconds:g}s"
        )
    return problems, notes


def collect(max_offset_seconds: float) -> dict:
    rc, shown = run(["timedatectl", "show", "-p", "NTPSynchronized"])
    kernel_synchronized = parse_timedatectl_show(shown) if rc == 0 else None

    source = None
    for name, units in SERVICES:
        if any(run(["systemctl", "is-active", "--quiet", unit])[0] == 0 for unit in units):
            source = name
            break

    offset = None
    source_synchronized = None
    if source == "chrony":
        rc, tracking = run(["chronyc", "-c", "tracking"])
        if rc == 0:
            offset, source_synchronized = parse_chrony_tracking(tracking)
    elif source == "systemd-timesyncd":
        rc, status = run(["timedatectl", "timesync-status"])
        if rc == 0:
            offset = parse_timesync_status(status)

    problems, notes = evaluate(
        kernel_synchronized=kernel_synchronized,
        source=source,
        source_synchronized=source_synchronized,
        offset_seconds=offset,
        max_offset_seconds=max_offset_seconds,
    )
    return {
        "ok": not problems,
        "problems": problems,
        "notes": notes,
        "source": source,
        "kernel_synchronized": kernel_synchronized,
        "source_synchronized": source_synchronized,
        "offset_seconds": offset,
        "max_offset_seconds": max_offset_seconds,
        "epoch": time.time(),
    }


def positive_seconds(value: str) -> float:
    number = float(value)
    if not number > 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return number


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max-offset", type=positive_seconds, default=1.0,
                        help="largest acceptable absolute offset in seconds")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 when a problem is found")
    args = parser.parse_args(argv)
    report = collect(args.max_offset)
    print(json.dumps(report, sort_keys=True))
    return 1 if args.strict and not report["ok"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
