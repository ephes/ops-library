"""Real Linux uv patch/venv boundary; isolated disposable prefix, no pip seeding."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    uv = sys.argv[1] if len(sys.argv) > 1 else "uv"
    with tempfile.TemporaryDirectory(prefix="wagtail-real-runtime-") as td:
        root = Path(td)
        env = {k: v for k, v in os.environ.items() if not k.startswith("UV_")}
        env.update(
            HOME=str(root),
            UV_PYTHON_INSTALL_DIR=str(root / "python"),
            UV_CACHE_DIR=str(root / "cache"),
            UV_PROJECT_ENVIRONMENT=str(root / "venv"),
        )

        def run(*args):
            return subprocess.check_output(
                [uv, "--no-config", *args], cwd=root, env=env, text=True
            ).strip()

        def version():
            return subprocess.check_output(
                [
                    str(root / "venv/bin/python"),
                    "-I",
                    "-c",
                    "import platform;print(platform.python_version())",
                ],
                text=True,
            ).strip()

        assert run("--version").split()[1] == "0.13.5"
        run("python", "install", "--no-bin", "3.15.0")
        old = Path(run("python", "find", "--no-python-downloads", "3.15.0")).resolve()
        run("venv", "--python", "3.15.0", str(root / "venv"))
        assert version() == "3.15.0"
        # Reproduce the deployed legacy minor-link venv layout in this fixture.
        # This is disposable test setup, never a production repair operation.
        runtime_root = old.parent.parent
        minor = runtime_root.parent / runtime_root.name.replace("3.15.0", "3.15")
        if not minor.exists():
            minor.symlink_to(runtime_root, target_is_directory=True)
        interpreter = root / "venv/bin/python"
        interpreter.unlink()
        interpreter.symlink_to(minor / "bin/python3.15")
        assert version() == "3.15.0"
        run("python", "install", "--no-bin", "3.15.1")
        after_install = version()
        assert after_install == "3.15.1", "uv did not retarget the legacy minor alias"
        assert minor.resolve() != runtime_root, "minor link was not moved by uv"
        assert old.exists(), "old exact-patch interpreter removed"
        env["UV_PYTHON_DOWNLOADS"] = "never"
        (root / "pyproject.toml").write_text(
            '[project]\nname="runtime-boundary"\nversion="0.0.0"\nrequires-python=">=3.15"\ndependencies=[]\n'
        )
        run("lock", "--offline")
        run("sync", "--frozen", "--no-default-groups", "--python", "3.15.1")
        assert version() == "3.15.1"
        # Normal controller rollback: exact old source/lock and interpreter pin,
        # through uv sync; no rm/ln/manual venv repair or seed invocation.
        run("sync", "--frozen", "--no-default-groups", "--python", "3.15.0")
        assert version() == "3.15.0"
        assert old.exists()
        new = Path(run("python", "find", "--no-python-downloads", "3.15.1")).resolve()
        assert new.exists(), "new patch unexpectedly removed by rollback"
        print(
            json.dumps(
                {
                    "uv": "0.13.5",
                    "before": "3.15.0",
                    "existing_venv_after_install": after_install,
                    "legacy_minor_link_fixture": True,
                    "managed_sync": "3.15.1",
                    "managed_rollback_sync": "3.15.0",
                    "both_exact_runtimes_retained": True,
                    "pip_seed_invoked": False,
                }
            )
        )


if __name__ == "__main__":
    main()
