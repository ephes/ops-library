"""Apply the pinned upstream Rustup self-replacement stage without SDK updates."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import platform
import pwd
import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

PINNED = {
    triple: checksum.removeprefix("sha256:")
    for triple, checksum in {
        "x86_64-unknown-linux-gnu": "sha256:5be191e8c70a5007074254cb74d78dbfdd25cd5a61c27de7b8e5410122ec24f4",
        "aarch64-unknown-linux-gnu": "sha256:a9c168dbea81a84671c6b7a5c1795cb0eb699020110d107ddfca427bd797e697",
        "aarch64-apple-darwin": "sha256:f7c7e11eb2e07f006e532a8aaac77b32f4527d305ac386c0c633ca6133d35ca9",
        "x86_64-apple-darwin": "sha256:b9610730ddeef52765723847866fd1e3540b2bf7d5ab0c324aa143a5edf25ba0",
    }.items()
}
TRIPLES = {
    ("Linux", "x86_64"): "x86_64-unknown-linux-gnu",
    ("Linux", "aarch64"): "aarch64-unknown-linux-gnu",
    ("Darwin", "arm64"): "aarch64-apple-darwin",
    ("Darwin", "x86_64"): "x86_64-apple-darwin",
}
# rust-lang/rustup 1.29.2 src/lib.rs TOOLS and DUP_TOOLS.
PROXIES = (
    "rustc",
    "rustdoc",
    "cargo",
    "rust-lldb",
    "rust-gdb",
    "rust-gdbgui",
    "rls",
    "cargo-clippy",
    "clippy-driver",
    "cargo-miri",
    "rust-analyzer",
    "rustfmt",
    "cargo-fmt",
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protected_state(cargo, rustup):
    """Bounded SDK metadata and settings proof; never traverse projects/toolchains."""
    result: dict[str, Any] = {}
    for name, path in [
        ("settings", rustup / "settings.toml"),
        *[("cargo_" + p, cargo / p) for p in ("env", "env.fish", "env.nu")],
    ]:
        result[name] = digest(path) if path.is_file() else None
    toolchains = rustup / "toolchains"
    result["toolchains"] = {}
    if toolchains.exists():
        for path in sorted(toolchains.iterdir()):
            stat = path.lstat()
            entry = {
                "inode": stat.st_ino,
                "mtime_ns": stat.st_mtime_ns,
                "mode": stat.st_mode,
            }
            if path.is_symlink():
                entry["link"] = os.readlink(path)
            elif path.is_dir():
                for name in (
                    "components",
                    "multirust-channel-manifest.toml",
                    "rust-installer-version",
                ):
                    manifest = path / "lib/rustlib" / name
                    entry[name] = digest(manifest) if manifest.is_file() else None
            result["toolchains"][path.name] = entry
    return result


def active_tools():
    if platform.system() == "Linux":
        names = []
        for path in Path("/proc").glob("[0-9]*/status"):
            try:
                fields = dict(
                    line.split(":", 1)
                    for line in path.read_text().splitlines()
                    if ":" in line
                )
                if int(fields["Uid"].split()[0]) == os.geteuid():
                    names.append(fields["Name"].strip())
            except (FileNotFoundError, ProcessLookupError):
                continue  # A process may disappear while reading kernel metadata.
            except (PermissionError, KeyError, ValueError) as error:
                raise ValueError("Cannot prove owner process state") from error
        return names
    return subprocess.check_output(
        ["/bin/ps", "-u", str(os.geteuid()), "-o", "comm="], text=True, timeout=10
    ).splitlines()


def inspect(home, user, old_sha, cargo, rustup, triple):
    account = pwd.getpwuid(os.geteuid())
    if (
        TRIPLES.get((platform.system(), platform.machine())) != triple
        or account.pw_name != user
        or account.pw_dir != str(home)
    ):
        raise ValueError(
            "Expected exact existing account/home and supported platform/triple"
        )
    for path in (home, cargo, cargo / "bin", rustup):
        if (
            not path.is_absolute()
            or path.is_symlink()
            or not path.is_dir()
            or path.stat().st_uid != os.geteuid()
        ):
            raise ValueError(
                "Existing owner-controlled nonsymlink directories required"
            )
    manager = cargo / "bin/rustup"
    if (
        manager.is_symlink()
        or not manager.is_file()
        or manager.stat().st_uid != os.geteuid()
    ):
        raise ValueError("Existing owner-controlled Rustup executable required")
    target = PINNED[triple]
    current = digest(manager)
    if (
        current not in (old_sha, target)
        or re.fullmatch(r"[0-9a-f]{64}", old_sha) is None
    ):
        raise ValueError("Rustup identity differs from explicit old/fixed checksum")
    proxies: dict[str, dict[str, Any] | None] = {}
    for name in PROXIES:
        path = manager.parent / name
        if not path.exists() and not path.is_symlink():
            proxies[name] = None
        elif path.stat().st_uid != os.geteuid() or not path.samefile(manager):
            raise ValueError("Unknown/custom proxy requires separate review")
        elif path.is_symlink():
            proxies[name] = {"link": os.readlink(path)}
        else:
            proxies[name] = {"hardlink": True}
    running = active_tools()
    if any(
        Path(p.strip()).name in {"rustup", *PROXIES}
        or Path(p.strip()).name.startswith("rustup-init")
        for p in running
    ):
        raise ValueError("Active Rust tools must finish before manager replacement")
    return manager, current, target, proxies, protected_state(cargo, rustup)


def patch(home, user, old_sha, cargo, rustup, triple, candidate=None, check=False):
    manager, current, target, proxies, state = inspect(
        home, user, old_sha, cargo, rustup, triple
    )
    if current == target:
        if any(value is None for value in proxies.values()):
            raise ValueError(
                "Fixed manager has incomplete proxies; review before repair"
            )
        return False, None
    if check:
        return True, None
    if not candidate:
        raise ValueError("Pinned updater path is required for apply")
    candidate = Path(candidate)
    if not candidate.name.startswith("rustup-init"):
        raise ValueError("Only exact official Rustup updater basename accepted")
    if (
        not candidate.is_absolute()
        or candidate.is_symlink()
        or not candidate.is_file()
        or digest(candidate) != target
    ):
        raise ValueError("Only exact official Rustup 1.29.2 updater bytes accepted")
    for directory in (cargo / ".managed-rustup-security",):
        if directory.exists() and (
            directory.is_symlink()
            or not directory.is_dir()
            or directory.stat().st_uid != os.geteuid()
        ):
            raise ValueError("Receipt directory identity is unsafe")
    old_mode = stat.S_IMODE(manager.stat().st_mode)
    old_gid = manager.stat().st_gid
    receipt = (
        cargo
        / ".managed-rustup-security"
        / datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S%fZ")
    )
    receipt.mkdir(parents=True, mode=0o700)
    receipt.chmod(0o700)
    backup = receipt / "rustup.before"
    shutil.copy2(manager, backup)
    backup.chmod(0o600)
    record = {
        "status": "prepared",
        "old_sha256": current,
        "fixed_sha256": target,
        "proxies_before": proxies,
        "protected_before": state,
        "old_mode": old_mode,
        "old_gid": old_gid,
        "triple": triple,
    }

    def write():
        path = receipt / "result.json"
        path.write_text(json.dumps(record, indent=2) + "\n")
        path.chmod(0o600)

    write()
    # Refuse drift before the vendor can mutate anything. In particular, never
    # replace a concurrent legitimate update with our earlier backup.
    if digest(backup) != current:
        raise ValueError("Rustup backup differs from preflight identity")
    if digest(manager) != current or protected_state(cargo, rustup) != state:
        raise ValueError("Rustup state changed after preflight")
    # Upstream Process::name honors RUSTUP_FORCE_ARG0 before dispatch. Keep the
    # self-replacement stage independent of ambient Rustup mode/trace settings.
    vendor_env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("RUSTUP_", "RUST_"))
    }
    vendor_env.update(CARGO_HOME=str(cargo), RUSTUP_HOME=str(rustup))
    try:
        # Exact stage used by upstream Unix self-update; no downloader, installer
        # profile/environment stage, toolchain selection, or SDK commands.
        result = subprocess.run(
            [str(candidate), "--self-replace"],
            cwd="/",
            env=vendor_env,
            capture_output=True,
            check=False,
            timeout=60,
        )
        (receipt / "updater.stdout").write_bytes(result.stdout)
        (receipt / "updater.stdout").chmod(0o600)
        (receipt / "updater.stderr").write_bytes(result.stderr)
        (receipt / "updater.stderr").chmod(0o600)
        if result.returncode != 0 or digest(manager) != target:
            raise RuntimeError("Pinned updater failed; inspect private receipt")
        manager.chmod(old_mode)
        if manager.stat().st_gid != old_gid:
            os.chown(manager, -1, old_gid)
        if (
            protected_state(cargo, rustup) != state
            or manager.stat().st_uid != os.geteuid()
        ):
            raise RuntimeError("Settings/toolchain metadata/owner changed unexpectedly")
        if any(not (manager.parent / name).samefile(manager) for name in PROXIES):
            raise RuntimeError("Rustup proxy replacement did not converge")
        record["status"] = "updated"
    except Exception as error:  # noqa: BLE001
        # Every failed mutation must attempt rollback.
        # Attempt every manager/proxy restoration even if an earlier one fails.
        failures = []
        try:
            temporary = manager.with_name(".rustup-security-restore")
            shutil.copy2(backup, temporary)
            temporary.chmod(old_mode)
            if temporary.stat().st_gid != old_gid:
                os.chown(temporary, -1, old_gid)
            os.replace(temporary, manager)
        except OSError:
            failures.append("manager")
        for name, before in proxies.items():
            try:
                path = manager.parent / name
                path.unlink(missing_ok=True)
                if before is not None:
                    if "link" in before:
                        path.symlink_to(before["link"])
                    else:
                        os.link(manager, path)
            except OSError:
                failures.append(name)
        record["status"] = "recovery_failed" if failures else "rolled_back"
        record["restore_failures"] = failures
        record["error_class"] = type(error).__name__
        try:
            record["protected_unchanged"] = protected_state(cargo, rustup) == state
        except OSError:
            record["protected_unchanged"] = False
        write()
        raise RuntimeError(
            "Manager patch failed; inspect private receipt " + str(receipt)
        ) from None
    write()
    return True, receipt


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--old-sha256", required=True)
    parser.add_argument("--cargo-home", required=True)
    parser.add_argument("--rustup-home", required=True)
    parser.add_argument("--triple", required=True)
    parser.add_argument("--candidate")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    changed, receipt = patch(
        Path(args.home),
        args.user,
        args.old_sha256,
        Path(args.cargo_home),
        Path(args.rustup_home),
        args.triple,
        args.candidate,
        args.check,
    )
    print("CHANGED" if changed else "UNCHANGED")
    if receipt:
        print("Private receipt: " + str(receipt))


if __name__ == "__main__":
    main()
