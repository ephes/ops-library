#!/usr/bin/python3
"""Read-only ingress and static-policy acceptance for a proxy-only update."""

import argparse
import concurrent.futures
import hashlib
import json
import subprocess
import time
import tomllib
from pathlib import Path


def observe(probe):
    args = [
        "curl",
        "--silent",
        "--show-error",
        "--output",
        "/dev/null",
        "--write-out",
        "%{http_code}",
        "--max-time",
        "10",
        "--resolve",
        f"{probe['host']}:{probe['port']}:{probe['address']}",
        f"{probe['scheme']}://{probe['host']}:{probe['port']}{probe.get('path', '/')}",
    ]
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=12, check=False
        )
    except subprocess.TimeoutExpired:
        return {"status": "", "exit": 28}
    return {"status": result.stdout, "exit": result.returncode}


def acceptable(before, after):
    if before == after:
        return True
    # A formerly unavailable backend recovering is not an ingress regression.
    # Authentication failures and redirects retain their exact expected status.
    return (
        before["exit"] == after["exit"] == 0
        and before["status"].startswith("5")
        and after["status"].startswith("2")
    )


def tree(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["capture", "health", "alias", "cleanup"])
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if not isinstance(config.get("probes"), list) or not config["probes"]:
        raise ValueError("At least one explicit ingress probe is required")
    dynamic = Path("/etc/traefik/dynamic")
    if args.mode == "capture":
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            observed = list(pool.map(observe, config["probes"]))
        print(json.dumps({"observations": observed, "dynamic": tree(dynamic)}))
        return
    if tree(dynamic) != config["dynamic"]:
        raise RuntimeError("Permanent routing changed during the update")
    if args.mode == "cleanup":
        # This probe creates no live route, backend, unit or timer to remove.
        print(
            json.dumps({"cleanup": "no temporary resources", "dynamic_verified": True})
        )
        return
    if args.mode == "alias":
        static = tomllib.loads(Path("/etc/traefik/traefik.toml").read_text())
        entries = static["entryPoints"]
        if set(entries) != set(config["entrypoints"]) or any(
            e.get("http", {}).get("aliasHeadersStrategy") != "delete"
            for e in entries.values()
        ):
            raise RuntimeError("Incomplete header-alias policy")
    for attempt in range(5):
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            actual = list(pool.map(observe, config["probes"]))
        failures = [
            p["host"]
            for p, before, after in zip(
                config["probes"], config["observations"], actual, strict=True
            )
            if not acceptable(before, after)
        ]
        if not failures:
            print(
                json.dumps({"ingress_checks": len(actual), "baseline_preserved": True})
            )
            return
        if attempt < 4:
            time.sleep(2)
    raise RuntimeError("Ingress changed for: " + ", ".join(failures))


if __name__ == "__main__":
    main()
