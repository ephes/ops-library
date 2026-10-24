"""Real Linux uv patch/venv boundary; isolated disposable prefix, no pip seeding."""

import getpass
import importlib.util
import json
import shutil
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main():
    uv = sys.argv[1] if len(sys.argv) > 1 else "uv"
    with tempfile.TemporaryDirectory(prefix="wagtail-real-runtime-") as td:
        root = Path(td)
        env = {
            k: v for k, v in os.environ.items() if not k.startswith(("UV_", "ANSIBLE_"))
        }
        env.pop("VIRTUAL_ENV", None)
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
        # The actual production include_role boundary, including metadata,
        # uv_install and the real managed-base verifier. This MUST fail against
        # the pre-repair source, whose venv checker rejects base pip.
        collections = root / "collections/ansible_collections/local"
        library = collections / "ops_library"
        for role in ("wagtail_deploy", "uv_install", "python_security_floor"):
            shutil.copytree(ROOT / "roles" / role, library / "roles" / role)
        shutil.copytree(ROOT / "plugins", library / "plugins")
        pg = library / "roles/postgres_install/tasks"
        pg.mkdir(parents=True)
        (pg / "main.yml").write_text(
            yaml.safe_dump(
                [
                    {
                        "name": "PostgreSQL must not execute",
                        "ansible.builtin.fail": {
                            "msg": "Unexpected PostgreSQL dependency"
                        },
                    }
                ]
            )
        )
        # Use a regular binary so uv_install follows its real no-update path.
        binary = root / "bin/uv"
        binary.parent.mkdir()
        shutil.copy2(shutil.which(uv) or uv, binary)
        play = [
            {
                "hosts": "localhost",
                "connection": "local",
                "gather_facts": False,
                "vars": {"ansible_become": False},
                "tasks": [
                    {
                        "ansible.builtin.include_role": {
                            "name": "local.ops_library.wagtail_deploy",
                            "tasks_from": "runtime.yml",
                        },
                        "vars": {
                            "wagtail_runtime_only": True,
                            "wagtail_user": getpass.getuser(),
                            "wagtail_home": str(root),
                            "wagtail_uv_path": str(binary),
                            "wagtail_python_version": "3.15.1",
                            "wagtail_runtime_expected_version": "3.15.1",
                            "wagtail_runtime_verify_trust": True,
                        },
                    }
                ],
            }
        ]
        play_path = root / "runtime.yml"
        play_path.write_text(yaml.safe_dump(play))
        (root / "ansible.cfg").write_text(
            "[defaults]\ninterpreter_python=auto_silent\n"
        )
        env.update(
            ANSIBLE_COLLECTIONS_PATH=str(root / "collections"),
            ANSIBLE_CONFIG=str(root / "ansible.cfg"),
        )
        subprocess.run(
            ["ansible-playbook", "-i", "localhost,", str(play_path)],
            cwd=root,
            env=env,
            check=True,
        )
        new = run("python", "find", "--no-python-downloads", "3.15.1")
        inspector = (
            ROOT / "roles/python_security_floor/files/inspect_python_security.py"
        ).read_text()
        # Default application policy must still reject pip in a BASE runtime.
        default = json.loads(
            subprocess.check_output([new, "-I", "-c", inspector], text=True)
        )
        assert default["packages"]["pip"]["installed"]
        assert not default["packages"]["pip"]["in_environment"]
        assert set(default) == {"python_version", "prefix", "packages"}
        assert "module_origins" not in default["packages"]["pip"]
        spec = importlib.util.spec_from_file_location(
            "security_filter", ROOT / "plugins/filter/python_security.py"
        )
        filters = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(filters)
        defaults = yaml.safe_load(
            (ROOT / "roles/python_security_floor/defaults/main.yml").read_text()
        )
        prefix = str(Path(new).resolve().parent.parent)
        # A valid exact interpreter on PATH outside the selected uv managed
        # store is discoverable by the old probe, refused by managed-only find.
        external_bin = root / "unmanaged/bin"
        external_bin.mkdir(parents=True)
        (external_bin / "python3.15").symlink_to(new)
        external_env = {
            **env,
            "UV_PYTHON_INSTALL_DIR": str(root / "empty-managed"),
            "PATH": str(external_bin) + os.pathsep + os.environ["PATH"],
        }
        found = subprocess.check_output(
            [uv, "--no-config", "python", "find", "--no-python-downloads", "3.15.1"],
            env=external_env,
            cwd=root,
            text=True,
        ).strip()
        assert Path(found).resolve() == Path(new).resolve()
        refused = subprocess.run(
            [
                uv,
                "--no-config",
                "python",
                "find",
                "--managed-python",
                "--no-python-downloads",
                "3.15.1",
            ],
            env=external_env,
            cwd=root,
            capture_output=True,
        )
        assert refused.returncode != 0, "unmanaged exact interpreter was admitted"

        def inspect_base(python=new, expected=prefix, patch="3.15.1", probe_env=None):
            report = json.loads(
                subprocess.check_output(
                    [python, "-I", "-c", inspector, "--managed-base-prefix", expected],
                    text=True,
                    cwd=root,
                    env=probe_env,
                )
            )
            return filters.python_security_report_violations(
                report,
                defaults["python_security_floor_packages"],
                defaults["python_security_floor_distrusted_roots"],
                defaults["python_security_floor_requires_python"],
                [],
                {"python_version": patch},
            )

        assert not inspect_base()
        assert inspect_base(expected=prefix + "-other"), "wrong base was accepted"
        assert inspect_base(patch="3.15.0"), "wrong patch was accepted"
        assert inspect_base(
            python=str(root / "venv/bin/python")
        ), "venv accepted as base"
        # Isolated mode ignores user/current-directory shadows.
        shadow = root / "pip"
        shadow.mkdir()
        (shadow / "__init__.py").write_text("raise RuntimeError('shadow pip imported')")
        assert not inspect_base(probe_env={**os.environ, "PYTHONPATH": str(root)})
        # Filesystem escapes in the actual installed base must still fail.
        # These are disposable fixture mutations, restored before normal sync.
        pip = Path(default["packages"]["pip"]["module_file"]).parent
        outside = root / "external-pip"
        pip.rename(outside)
        pip.symlink_to(outside, target_is_directory=True)
        try:
            assert inspect_base(), "external pip was accepted"
        finally:
            pip.unlink()
            outside.rename(pip)
        bundle = Path(default["packages"]["pip"]["bundle"])
        outside_bundle = root / "external-ca.pem"
        bundle.rename(outside_bundle)
        bundle.symlink_to(outside_bundle)
        try:
            assert inspect_base(), "external trust bundle was accepted"
        finally:
            bundle.unlink()
            outside_bundle.rename(bundle)
        print(
            "ACTUAL-INCLUDE-ROLE-BASE-VERIFIED; DEFAULT-VENV-POLICY-STRICT; ORIGIN-ESCAPES-REJECTED"
        )
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
                    "actual_include_role_managed_base_verified": True,
                    "postgres_dependency_suppressed": True,
                    "default_venv_policy_still_strict": True,
                    "unmanaged_exact_interpreter_refused": True,
                }
            )
        )


if __name__ == "__main__":
    main()
