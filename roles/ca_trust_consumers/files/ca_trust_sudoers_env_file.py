#!/usr/bin/env python3
"""List sudoers files that may set the env_file option (sudoers accepts only one).

Reads the given files and the top-level regular files of the given
directories (as #includedir does: names with a dot or ending in "~" are
skipped), skipping --exclude paths, and reports every file in which the whole
word env_file appears anywhere. This deliberately does not parse sudoers:
quoting, continuation lines, comments and selector lists interact in ways a
partial parser gets wrong, so a mention in a comment or a quoted value also
counts (fail closed). Only longer option names such as restricted_env_file do
not. Prints one path per line; exits 0. Read-only, standard library only.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

_ENV_FILE = re.compile(r"(?<![A-Za-z0-9_])env_file(?![A-Za-z0-9_])")


def sets_env_file(text: str) -> bool:
    """True when the file mentions env_file as a whole word anywhere."""
    return bool(_ENV_FILE.search(text))


def candidate_files(paths: list[str]) -> list[str]:
    files: list[str] = []
    for path in paths:
        if os.path.isdir(path):
            for name in sorted(os.listdir(path)):
                full = os.path.join(path, name)
                if "." in name or name.endswith("~") or not os.path.isfile(full):
                    continue
                files.append(full)
        elif os.path.isfile(path):
            files.append(path)
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args(argv)
    excluded = {os.path.realpath(path) for path in args.exclude}
    for path in candidate_files(args.paths):
        if os.path.realpath(path) in excluded:
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError:
            print(f"{path} (unreadable)")
            continue
        if sets_env_file(text):
            print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
