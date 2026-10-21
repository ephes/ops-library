"""Opt-in exact vendor updater proof in disposable homes, never an installed SDK."""

import argparse
import importlib.util
import json
import os
import platform
import pwd
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
HELPER = ROOT / "roles/rustup_security/files/rustup_security.py"


def fixture(helper, updater, base, native_sandbox=False):
    spec = importlib.util.spec_from_file_location("rustup_security", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    triple = module.TRIPLES[(platform.system(), platform.machine())]
    assert module.digest(updater) == module.PINNED[triple]
    cargo = base / "cargo"
    rustup = base / "rustup"
    (cargo / "bin").mkdir(parents=True)
    (rustup / "toolchains/sentinel/lib/rustlib").mkdir(parents=True)
    (rustup / "settings.toml").write_text("[deliberately invalid SDK sentinel\n")
    (rustup / "toolchains/sentinel/lib/rustlib/components").write_text(
        "unchanged SDK sentinel\n"
    )
    (cargo / "env").write_text("unchanged shell environment sentinel\n")
    manager = cargo / "bin/rustup"
    manager.write_bytes(b"old manager fixture; never execute")
    manager.chmod(0o750)
    os.link(manager, cargo / "bin/cargo")
    (cargo / "bin/rustc").symlink_to("rustup")
    (cargo / "bin/independent-tool").write_text("unrelated binary sentinel\n")
    before = module.protected_state(cargo, rustup)
    account = pwd.getpwuid(os.getuid())
    original_sha = module.digest(manager)
    command = [
        sys.executable,
        str(helper),
        "--home",
        account.pw_dir,
        "--user",
        account.pw_name,
        "--cargo-home",
        str(cargo),
        "--rustup-home",
        str(rustup),
        "--triple",
        triple,
        "--old-sha256",
        original_sha,
    ]
    if native_sandbox:
        # No HOME override: deny writes outside the disposable fixture and ALL
        # networking, including accidental old/default updater/SDK paths.
        assert platform.system() == "Darwin"
        sandbox = "/usr/bin/sandbox-exec"
        assert Path(sandbox).is_file(), "Native sandbox is required; no unsafe fallback"
        profile = (
            "(version 1)(allow default)(deny network*)(deny file-write*)(allow file-write* (subpath "
            + json.dumps(str(base.resolve()))
            + "))"
        )

    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "RUSTUP_FORCE_ARG0": "cargo",
        "RUSTUP_TRACE_DIR": str(base / "forbidden-trace"),
        "RUST_RECURSION_COUNT": "999",
    }
    outputs = []
    for extra, expected in [
        (["--check"], "CHANGED"),
        (["--candidate", str(updater)], "CHANGED"),
        (["--check"], "UNCHANGED"),
    ]:
        if native_sandbox and "--candidate" in extra:
            original_run = subprocess.run

            def isolated_run(argv, _original_run=original_run, **kwargs):
                if argv == [str(updater), "--self-replace"]:
                    return _original_run([sandbox, "-p", profile, *argv], **kwargs)
                assert argv[0] == "/bin/ps", "Unexpected SDK/downloader subprocess"
                return _original_run(argv, **kwargs)

            with (
                patch.dict(os.environ, env),
                patch.object(module.subprocess, "run", side_effect=isolated_run),
            ):
                changed, _ = module.patch(
                    Path(account.pw_dir),
                    account.pw_name,
                    original_sha,
                    cargo,
                    rustup,
                    triple,
                    str(updater),
                )
            assert changed
        else:
            result = subprocess.run(
                command + extra,
                capture_output=True,
                text=True,
                env=env,
                cwd="/",
                check=False,
                timeout=90,
            )
            if result.returncode:
                for proof in (cargo / ".managed-rustup-security").glob("*/result.json"):
                    print(proof.read_text(), file=sys.stderr)
                    diagnostic = proof.parent / "updater.stderr"
                    if diagnostic.exists():
                        print(diagnostic.read_text(errors="replace"), file=sys.stderr)
            assert result.returncode == 0, result.stderr
            assert result.stdout.splitlines()[0] == expected, result.stdout
        outputs.append(expected)
    assert module.digest(manager) == module.PINNED[triple]
    assert manager.stat().st_mode & 0o777 == 0o750
    assert all((cargo / "bin" / name).samefile(manager) for name in module.PROXIES)
    assert module.protected_state(cargo, rustup) == before
    assert (cargo / "bin/independent-tool").read_text() == "unrelated binary sentinel\n"
    result = json.loads(
        next((cargo / ".managed-rustup-security").glob("*/result.json")).read_text()
    )
    assert result["status"] == "updated"
    print(
        json.dumps(
            {
                "triple": triple,
                "updater_sha256": module.digest(updater),
                "check_apply_repeat": outputs,
                "manager_and_all13_proxies_fixed": True,
                "original_mode_owner_preserved": True,
                "settings_env_toolchain_metadata_unchanged": True,
                "unrelated_tool_unchanged": True,
                "network_disabled": True,
                "macos_updater_seatbelt_write_confinement": native_sandbox,
                "isolation": "native-macOS-seatbelt"
                if native_sandbox
                else "local-disposable-Docker",
                "receipt_status": result["status"],
            },
            indent=2,
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inside", action="store_true")
    parser.add_argument("--docker", action="store_true")
    args = parser.parse_args()
    if args.inside:
        assert (
            platform.system() == "Linux"
            and Path("/.dockerenv").exists()
            and os.path.ismount("/fixture")
        ), "Isolated Docker tmpfs required"
        fixture(Path("/helper.py"), Path("/rustup-init"), Path("/fixture"))
        return
    raw = os.environ.get("RUSTUP_SECURITY_FIXTURE_UPDATER")
    if not raw:
        raise SystemExit(
            "Set RUSTUP_SECURITY_FIXTURE_UPDATER to the exact official native updater"
        )
    updater = Path(raw).resolve()
    if platform.system() == "Darwin" and not args.docker:
        with tempfile.TemporaryDirectory(prefix="rustup-security-native-") as directory:
            fixture(HELPER, updater, Path(directory).resolve(), native_sandbox=True)
        print("Native fixture cleanup: complete")
        return
    context = subprocess.check_output(["docker", "context", "show"], text=True).strip()
    assert context in ("colima", "desktop-linux"), "Local Docker context required"
    endpoint = json.loads(
        subprocess.check_output(["docker", "context", "inspect", context], text=True)
    )[0]["Endpoints"]["docker"]["Host"]
    assert endpoint.startswith("unix://"), "A local Unix Docker endpoint is required"
    docker = ["docker", "--context", context]
    with tempfile.TemporaryDirectory(
        prefix="rustup-fixture-artifact-", dir=ROOT.parent
    ) as directory:
        shared_updater = Path(directory) / "rustup-init"
        shutil.copy2(updater, shared_updater)
        name = "rustup-security-" + uuid.uuid4().hex[:12]
        try:
            subprocess.run(
                [
                    *docker,
                    "run",
                    "--rm",
                    "--pull",
                    "never",
                    "--network",
                    "none",
                    "--name",
                    name,
                    "--tmpfs",
                    "/fixture:rw,size=128m",
                    "--mount",
                    f"type=bind,src={HELPER},dst=/helper.py,readonly",
                    "--mount",
                    f"type=bind,src={Path(__file__).resolve()},dst=/fixture-test.py,readonly",
                    "--mount",
                    f"type=bind,src={shared_updater},dst=/rustup-init,readonly",
                    "python:3.11-slim",
                    "python3",
                    "/fixture-test.py",
                    "--inside",
                ],
                check=True,
            )
        finally:
            subprocess.run(
                [*docker, "rm", "-f", name], capture_output=True, check=False
            )
            # --rm removes a successfully completed container; the fallback handles failures.
            remaining = subprocess.check_output(
                [*docker, "ps", "-aq", "--filter", "name=^/" + name + "$"], text=True
            ).strip()
            assert not remaining, "Disposable fixture cleanup failed"
            print("Docker fixture cleanup: complete")


if __name__ == "__main__":
    main()
