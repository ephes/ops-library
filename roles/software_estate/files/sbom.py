#!/usr/bin/env python3
"""Bounded local-only Syft scans. Returns a CycloneDX document plus provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import tempfile
import time
from pathlib import Path

SYFT = "/usr/local/lib/software-estate/syft"
VERSION = "1.52.0"


def run(argv, timeout=30, env=None):
    """Spool stdout to disk; enforce timeout and cap before reading into memory."""
    limit = 64 * 1024 * 1024
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(
            argv,
            stdout=output,
            stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                if output.tell() > limit:
                    raise ValueError("output_limit")
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(argv[0], timeout)
                time.sleep(0.02)
            if process.returncode:
                raise RuntimeError("command_failed")
            if output.tell() > limit:
                raise ValueError("output_limit")
            output.seek(0)
            data = output.read(limit + 1)
            if len(data) > limit:
                raise ValueError("output_limit")
            return data
        finally:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait()


def fingerprint(root):
    """Fingerprint metadata, not installed file contents; label this limitation."""
    digest = hashlib.sha256()
    count = 0
    for path in sorted(
        Path(root).glob("lib/python*/site-packages/*.dist-info/METADATA")
    ):
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("metadata_limit")
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
        count += 1
    if not count:
        raise ValueError("no_installed_metadata")
    return digest.hexdigest()


def scan(policy):
    started = time.time()
    environment = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "SYFT_CHECK_FOR_APP_UPDATE": "false",
        "SYFT_ENRICH": "",
    }
    version = json.loads(run([SYFT, "version", "-o", "json"], env=environment))
    if version["version"] != VERSION:
        raise ValueError("wrong_scanner_version")
    if policy["kind"] == "python-venv":
        if not Path(policy["path"]).is_absolute():
            raise ValueError("invalid_scan_root")
        root = str(Path(policy["path"]).resolve())
        if (
            not Path(root).is_absolute()
            or ".." in Path(root).parts
            or len(Path(root).parts) < 3
            or not (Path(root) / "pyvenv.cfg").is_file()
        ):
            raise ValueError("invalid_scan_root")
        before = fingerprint(root)
        source = "dir:" + root
        selection = [
            "--override-default-catalogers",
            "python-installed-package-cataloger",
        ]
        identity = {
            "type": "python-distribution-metadata-sha256",
            "value": before,
            "artifact_identity_complete": False,
        }
    elif policy["kind"] == "container":
        container = policy["container"]
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+", container):
            raise ValueError("invalid_container")
        before = (
            run(["docker", "inspect", "--format", "{{.Image}}", container])
            .decode()
            .strip()
        )
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", before):
            raise ValueError("invalid_image_id")
        source = "docker:" + before
        selection = []
        identity = {
            "type": "docker-image-id",
            "value": before,
            "artifact_identity_complete": True,
        }
    else:
        raise ValueError("unsupported_scan_kind")
    with tempfile.TemporaryDirectory(prefix="software-estate-sbom-") as temp:
        config = Path(temp) / "config.yml"
        config.write_text("check-for-app-update: false\nenrich: []\n")
        document = json.loads(
            run(
                [
                    SYFT,
                    "scan",
                    source,
                    "--config",
                    str(config),
                    "-o",
                    "cyclonedx-json@1.6",
                    *selection,
                ],
                timeout=900,
                env=environment,
            )
        )
    if policy["kind"] == "python-venv":
        if fingerprint(root) != before:
            raise ValueError("metadata_changed_during_scan")
    else:
        after = (
            run(["docker", "inspect", "--format", "{{.Image}}", policy["container"]])
            .decode()
            .strip()
        )
        if after != before:
            raise ValueError("container_image_changed_during_scan")
    if document.get("bomFormat") != "CycloneDX" or document.get("specVersion") != "1.6":
        raise ValueError("unexpected_sbom_schema")
    # Unknown dependency/constituent coverage must not become complete by omission.
    document["compositions"] = [
        {
            "aggregate": "incomplete",
            "assemblies": [document["metadata"]["component"]["bom-ref"]],
        }
    ]
    return {
        "observed_at": started,
        "host": policy["host"],
        "service": policy["service"],
        "scanner": {"name": "syft", "version": VERSION},
        "source": source,
        "cataloger_selection": selection,
        "identity": identity,
        "limitations": ["no_runtime_mutable_files", "dependency_coverage_incomplete"],
        "document": document,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy-json", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(scan(json.loads(args.policy_json))))
    except (
        OSError,
        ValueError,
        KeyError,
        RuntimeError,
        subprocess.TimeoutExpired,
    ) as exc:
        print(json.dumps({"error": type(exc).__name__}))
        raise SystemExit(1) from None
