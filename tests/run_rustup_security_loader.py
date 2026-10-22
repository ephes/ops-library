"""Actual FQCN role lifecycle against a disposable current-owner macOS install."""

import hashlib
import json
import os
import platform
import pwd
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def main():
    assert platform.system() == "Darwin", "This fixture requires genuine macOS"
    ca = Path(os.environ["RUSTUP_SECURITY_FIXTURE_CA_FILE"])
    interpreter = Path(os.environ["RUSTUP_SECURITY_FIXTURE_MODULE_PYTHON"])
    assert ca.is_file() and interpreter.is_file()
    account = pwd.getpwuid(os.geteuid())
    with tempfile.TemporaryDirectory(prefix="rustup-role-loader-") as directory:
        base = Path(directory)
        role = (
            base
            / "collections/ansible_collections/local/ops_library/roles/rustup_security"
        )
        shutil.copytree(
            ROOT / "roles/rustup_security",
            role,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        cargo = base / "cargo"
        rustup = base / "rustup"
        (cargo / "bin").mkdir(parents=True)
        (rustup / "toolchains/sentinel/lib/rustlib").mkdir(parents=True)
        manager = cargo / "bin/rustup"
        manager.write_bytes(b"old disposable manager; never execute")
        manager.chmod(0o750)
        old_sha = hashlib.sha256(manager.read_bytes()).hexdigest()
        os.link(manager, cargo / "bin/cargo")
        (cargo / "bin/rustc").symlink_to("rustup")
        (rustup / "settings.toml").write_text(
            "[deliberately invalid SDK settings sentinel\n"
        )
        (rustup / "toolchains/sentinel/lib/rustlib/components").write_text(
            "SDK preserved\n"
        )
        (cargo / "env").write_text("shell environment preserved\n")
        play = [
            {
                "hosts": "localhost",
                "gather_facts": False,
                "vars": {
                    "ansible_connection": "local",
                    "ansible_user": account.pw_name,
                    "ansible_python_interpreter": str(interpreter),
                    "ansible_remote_tmp": str(base / "remote"),
                    "rustup_security_become": False,
                    "rustup_security_owner": account.pw_name,
                    "rustup_security_home": account.pw_dir,
                    "rustup_security_cargo_home": str(cargo),
                    "rustup_security_rustup_home": str(rustup),
                    "rustup_security_old_sha256": old_sha,
                    "rustup_security_triple": "aarch64-apple-darwin"
                    if platform.machine() == "arm64"
                    else "x86_64-apple-darwin",
                    "rustup_security_ca_file": str(ca),
                    "rustup_security_python": str(interpreter),
                },
                "tasks": [
                    {
                        "name": "Actual scoped role",
                        "ansible.builtin.include_role": {
                            "name": "local.ops_library.rustup_security"
                        },
                    }
                ],
            }
        ]
        path = base / "play.yml"
        path.write_text(yaml.safe_dump(play))
        config = base / "ansible.cfg"
        config.write_text(
            "[defaults]\ngathering=explicit\nfact_caching=memory\nretry_files_enabled=False\n"
        )
        env = {
            **os.environ,
            "ANSIBLE_CONFIG": str(config),
            "ANSIBLE_COLLECTIONS_PATH": str(base / "collections/ansible_collections"),
            "ANSIBLE_LOCAL_TEMP": str(base / "local"),
            "ANSIBLE_NOCOLOR": "1",
        }
        recaps = []
        for extra, expected in [(["--check"], 1), ([], 1), (["--check"], 0)]:
            run = subprocess.run(
                ["ansible-playbook", "-i", "localhost,", str(path), *extra],
                cwd="/",
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=180,
            )
            print(run.stdout)
            assert run.returncode == 0, run.stderr
            recap = next(
                line
                for line in run.stdout.splitlines()
                if line.startswith("localhost ") and "failed=" in line
            )
            assert f"changed={expected}" in recap and "failed=0" in recap, recap
            recaps.append(recap)
        proof = json.loads(
            next((cargo / ".managed-rustup-security").glob("*/result.json")).read_text()
        )
        assert proof["status"] == "updated"
        assert (
            manager.stat().st_uid == os.geteuid()
            and manager.stat().st_mode & 0o777 == 0o750
        )
        print(
            json.dumps(
                {
                    "role": "local.ops_library.rustup_security",
                    "connection": "local-current-owner",
                    "become": False,
                    "recaps": recaps,
                    "receipt_status": proof["status"],
                    "synthetic_sdk_never_executed": True,
                },
                indent=2,
            )
        )
    print("Actual role fixture cleanup: complete")


if __name__ == "__main__":
    main()
