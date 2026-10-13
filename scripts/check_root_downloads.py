#!/usr/bin/env python3
"""Reject unverified downloads in the roles covered by audit finding L4."""
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLES = ("echoport_backup",)
# No vendor-published checksum was found for this repository signing key. Keep only this
# exact existing download exempt; it is reported as an unresolved L4 item.
EXCEPTION = (
    "vibe_coding_deploy",
    "nodejs.yml",
    "https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key",
)


def walk(nodes):
    for node in nodes or []:
        yield node
        for key in ("block", "rescue", "always"):
            yield from walk(node.get(key, []))


def findings(nodes, role="", filename=""):
    verified_paths = set()
    for task in walk(nodes):
        for module, args in task.items():
            short = module.rsplit(".", 1)[-1]
            if short in ("get_url", "unarchive", "uri") and not isinstance(args, dict):
                yield f"{task.get('name')}: download module requires mapping arguments"
                continue
            if short == "get_url":
                url = args.get("url", "")
                if args.get("checksum"):
                    verified_paths.add(args.get("dest"))
                if (role, filename, url) != EXCEPTION and not args.get("checksum"):
                    yield f"{task.get('name')}: missing checksum"
                if "latest" in url:
                    yield f"{task.get('name')}: unpinned URL"
            if short in ("unarchive", "uri") and isinstance(args, dict):
                url = args.get("src", args.get("url", ""))
                if short == "unarchive" and (
                    str(url).startswith(("https://", "http://"))
                    or (args.get("remote_src") and url not in verified_paths)
                ):
                    yield f"{task.get('name')}: archive source has no preceding verified download"
                if short == "uri" and args.get("dest"):
                    yield f"{task.get('name')}: uri download bypasses checksum"
                if "latest" in str(url):
                    yield f"{task.get('name')}: unpinned URL"
            if short in ("shell", "command"):
                command = args if isinstance(args, str) else str(args)
                if re.search(r"\b(curl|wget)\b", command):
                    yield f"{task.get('name')}: shell download bypasses checksum"


def task_files(role):
    return (
        path
        for path in (ROOT / "roles" / role / "tasks").rglob("*")
        if path.suffix in (".yml", ".yaml")
    )


def main():
    errors = []
    for role in ROLES:
        for path in task_files(role):
            errors.extend(
                f"{path.relative_to(ROOT)}: {msg}"
                for msg in findings(yaml.safe_load(path.read_text()), role, path.name)
            )
    for error in errors:
        print(error)
    return bool(errors)


if __name__ == "__main__":
    sys.exit(main())
