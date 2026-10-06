"""Molecule runs from different checkouts must not share Docker resources.

Docker container names are global to the daemon. A scenario whose platform is
called ``instance`` collides with every other checkout running a scenario with
the same name: one run's destroy step kills the other run's container
("UNREACHABLE: Failed to create temporary directory", rc 137).

Static check: every platform name and every Docker network name in every
``molecule.yml`` carries the ``${MOLECULE_RUN_ID:-local}`` token, and inventory
host_vars are keyed by those run-scoped names.

Wrapper check: ``scripts/molecule-run.sh`` gives each ``test`` a fresh run ID
and its own Molecule ephemeral directory, keeps a stable per-checkout ID for
debugging commands, and destroys only its own run after a failure.
"""

from __future__ import annotations

import os
import re
import subprocess
import signal
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "molecule-run.sh"
RUN_ID_TOKEN = "${MOLECULE_RUN_ID:-local}"


def molecule_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("molecule.yml")
        if not {".venv", ".git", "node_modules"} & set(path.relative_to(ROOT).parts)
    )


class MoleculeScenarioNamesAreRunScoped(unittest.TestCase):
    def test_scenarios_exist(self) -> None:
        self.assertGreater(len(molecule_files()), 0)

    def test_no_fixed_instance_platform_name(self) -> None:
        pattern = re.compile(r"""^\s*-?\s*name:\s*["']?instance["']?\s*$""", re.MULTILINE)
        offenders = [
            str(path.relative_to(ROOT))
            for path in molecule_files()
            if pattern.search(path.read_text())
        ]
        self.assertEqual(offenders, [], "fixed `name: instance` in molecule.yml")

    def test_platform_and_network_names_carry_run_id(self) -> None:
        for path in molecule_files():
            rel = path.relative_to(ROOT)
            scenario = yaml.safe_load(path.read_text())
            platforms = scenario.get("platforms") or []
            with self.subTest(scenario=str(rel)):
                self.assertTrue(platforms, "scenario defines no platforms")
                names = [platform["name"] for platform in platforms]
                for name in names:
                    self.assertIn(RUN_ID_TOKEN, name, f"platform {name!r} is not run-scoped")
                self.assertEqual(len(names), len(set(names)), "duplicate platform names")
                for platform in platforms:
                    for network in platform.get("networks") or []:
                        network_name = network.get("name", "") if isinstance(network, dict) else network
                        self.assertIn(
                            RUN_ID_TOKEN,
                            network_name,
                            f"network {network_name!r} is not run-scoped",
                        )
                env = (scenario.get("provisioner") or {}).get("env") or {}
                if "ANSIBLE_COLLECTIONS_PATH" in env:
                    # Keep the wrapper's run-scoped collection path first.
                    self.assertTrue(
                        env["ANSIBLE_COLLECTIONS_PATH"].startswith("${ANSIBLE_COLLECTIONS_PATH:-"),
                        "provisioner ANSIBLE_COLLECTIONS_PATH must start with ${ANSIBLE_COLLECTIONS_PATH:-...}",
                    )
                host_vars = ((scenario.get("provisioner") or {}).get("inventory") or {}).get("host_vars") or {}
                stale = sorted(set(host_vars) - set(names))
                self.assertEqual(stale, [], "host_vars keys that match no platform")


FAKE_UV = textwrap.dedent(
    """\
    #!/usr/bin/env bash
    [[ "$1" == run ]] && shift
    printf '%s|%s|%s|%s|%s|%s\\n' "$*" "$MOLECULE_RUN_ID" "$MOLECULE_EPHEMERAL_DIRECTORY" "$PWD" "$ANSIBLE_HOME" "$ANSIBLE_COLLECTIONS_PATH" >> "$FAKE_UV_LOG"
    if [[ "$2" == test ]]; then
        if [[ -n "${FAKE_UV_DETACHED_JOB:-}" ]]; then
            # Like Ansible's async_wrapper: setsid() leaves the process group,
            # and the argv names this run's ansible-tmp-<epoch> directory.
            job_dir="$FAKE_UV_LOG.d/ansible-tmp-$(date +%s).5-$$-1"
            mkdir -p "$job_dir"
            cat > "$job_dir/AnsiballZ_docker_container.py" <<'PY'
    import os, sys, time
    os.setsid()
    time.sleep(2)
    with open(os.environ["FAKE_UV_LOG"], "a") as log:
        print("detached job finished", file=log)
    PY
            python3 "$job_dir/AnsiballZ_docker_container.py" >/dev/null 2>&1 &
            echo "$!" > "$FAKE_UV_LOG.sleeper"
            sleep 0.2
            exit 3
        fi
        if [[ -n "${FAKE_UV_TEST_BLOCK:-}" ]]; then
            # A descendant that ignores the parent's exit, like ansible-playbook
            # under Molecule; the wrapper must stop the whole process group.
            # FAKE_UV_IGNORE_TERM: the whole tree ignores TERM (inherited).
            if [[ -n "${FAKE_UV_IGNORE_TERM:-}" ]]; then
                trap '' TERM
            else
                trap 'echo terminated >> "$FAKE_UV_LOG"; exit 143' TERM
            fi
            sleep 60 >/dev/null 2>&1 &
            echo "$!" > "$FAKE_UV_LOG.sleeper"
            wait
        fi
        exit "${FAKE_UV_TEST_RC:-0}"
    fi
    exit 0
    """
)


class MoleculeRunWrapper(unittest.TestCase):
    role = "test_dummy"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "uv"
        fake.write_text(FAKE_UV)
        fake.chmod(0o755)
        self.log = tmp / "uv.log"
        self.state_root = tmp / "state"
        self.env = {
            key: value for key, value in os.environ.items() if key != "MOLECULE_RUN_ID"
        }
        self.env.update(
            PATH=f"{bin_dir}{os.pathsep}{self.env['PATH']}",
            FAKE_UV_LOG=str(self.log),
            OPS_LIBRARY_MOLECULE_STATE_DIR=str(self.state_root),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_wrapper(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(WRAPPER), *args],
            env={**self.env, **env},
            capture_output=True,
            text=True,
            check=False,
        )

    def calls(self) -> list[list[str]]:
        return [line.split("|") for line in self.log.read_text().splitlines()]

    def test_each_test_run_gets_a_fresh_id_and_state_dir(self) -> None:
        for _ in range(2):
            result = self.run_wrapper(self.role, "default", "test")
            self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertEqual([call[0] for call in calls], ["molecule test -s default"] * 2)
        run_ids = [call[1] for call in calls]
        self.assertNotEqual(run_ids[0], run_ids[1])
        for run_id, call in zip(run_ids, calls):
            self.assertRegex(run_id, r"^t[0-9a-f]{10}$")
            self.assertEqual(
                call[2], str(self.state_root / run_id / self.role / "default" / "molecule")
            )
            self.assertEqual(Path(call[3]).resolve(), (ROOT / "roles" / self.role).resolve())
            run_home = self.state_root / run_id / self.role / "default" / "ansible"
            self.assertEqual(call[4], str(run_home))
            self.assertTrue(call[5].startswith(f"{run_home}/collections:"), call[5])
        self.assertEqual(list(self.state_root.iterdir()), [], "state dir left behind")

    def test_failed_test_destroys_only_its_own_run(self) -> None:
        result = self.run_wrapper(self.role, "default", "test", FAKE_UV_TEST_RC="3")
        self.assertEqual(result.returncode, 3)
        calls = self.calls()
        self.assertEqual(
            [call[0] for call in calls],
            ["molecule test -s default", "molecule destroy -s default"],
        )
        self.assertEqual(calls[0][1], calls[1][1])
        self.assertEqual(calls[0][2], calls[1][2])
        self.assertEqual(list(self.state_root.iterdir()), [])

    def start_blocking_test(self, **env: str) -> subprocess.Popen[str]:
        proc = subprocess.Popen(
            [str(WRAPPER), self.role, "default", "test"],
            env={**self.env, "FAKE_UV_TEST_BLOCK": "1", **env},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 10
        while not Path(f"{self.log}.sleeper").exists():
            if time.monotonic() > deadline:
                proc.kill()
                proc.communicate()
                self.fail("test never started")
            time.sleep(0.05)
        return proc

    def test_test_that_ignores_term_is_killed_and_destroyed(self) -> None:
        proc = self.start_blocking_test(
            FAKE_UV_IGNORE_TERM="1", OPS_LIBRARY_MOLECULE_STOP_TIMEOUT="1"
        )
        try:
            proc.send_signal(signal.SIGTERM)
            _, stderr = proc.communicate(timeout=15)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
        self.assertEqual(proc.returncode, 143)
        self.assertIn("sending KILL", stderr)
        sleeper = int(Path(f"{self.log}.sleeper").read_text())
        with self.assertRaises(ProcessLookupError, msg="descendant survived"):
            os.kill(sleeper, 0)
        commands = [line.split("|")[0] for line in self.log.read_text().splitlines()]
        self.assertEqual(
            commands, ["molecule test -s default", "molecule destroy -s default"]
        )
        self.assertEqual(list(self.state_root.iterdir()), [])

    def test_interrupted_test_stops_the_run_and_destroys_it(self) -> None:
        proc = self.start_blocking_test()
        try:
            proc.send_signal(signal.SIGTERM)
            proc.communicate(timeout=10)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
        self.assertEqual(proc.returncode, 143)
        sleeper = int(Path(f"{self.log}.sleeper").read_text())
        with self.assertRaises(ProcessLookupError, msg="descendant survived"):
            os.kill(sleeper, 0)
        lines = self.log.read_text().splitlines()
        self.assertEqual(lines[1], "terminated")
        self.assertEqual(
            [line.split("|")[0] for line in (lines[0], lines[2])],
            ["molecule test -s default", "molecule destroy -s default"],
        )
        self.assertEqual(lines[0].split("|")[1], lines[2].split("|")[1])
        self.assertEqual(list(self.state_root.iterdir()), [])

    def test_debug_ids_differ_between_roles_and_scenarios(self) -> None:
        for role, scenario in (
            ("test_dummy", "default"),
            ("redis_install", "default"),
            ("mail_monitoring", "default"),
            ("mail_monitoring", "legacy"),
        ):
            result = self.run_wrapper(role, scenario, "converge")
            self.assertEqual(result.returncode, 0, result.stderr)
        run_ids = [call[1] for call in self.calls()]
        self.assertEqual(len(set(run_ids)), 4, run_ids)

    def test_failed_test_waits_for_detached_async_jobs_before_destroy(self) -> None:
        result = self.run_wrapper(self.role, "default", "test", FAKE_UV_DETACHED_JOB="1")
        self.assertEqual(result.returncode, 3, result.stderr)
        lines = self.log.read_text().splitlines()
        self.assertEqual(
            [line.split("|")[0] for line in lines],
            [
                "molecule test -s default",
                "detached job finished",
                "molecule destroy -s default",
            ],
        )

    def test_debug_commands_share_a_stable_checkout_id(self) -> None:
        for command in ("converge", "verify", "destroy"):
            result = self.run_wrapper(self.role, "default", command)
            self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertEqual(
            [call[0] for call in calls],
            [
                "molecule converge -s default",
                "molecule verify -s default",
                "molecule destroy -s default",
            ],
        )
        self.assertEqual(len({call[1] for call in calls}), 1)
        self.assertRegex(calls[0][1], r"^wt[0-9a-f]{10}$")
        self.assertFalse((self.state_root / calls[0][1]).exists())

    def test_explicit_run_id_is_used_and_validated(self) -> None:
        result = self.run_wrapper(self.role, "default", "test", MOLECULE_RUN_ID="ci-42")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls()[0][1], "ci-42")
        bad = self.run_wrapper(self.role, "default", "test", MOLECULE_RUN_ID="Bad/ID")
        self.assertEqual(bad.returncode, 2)
        self.assertIn("MOLECULE_RUN_ID", bad.stderr)

    def test_unknown_scenario_is_rejected(self) -> None:
        result = self.run_wrapper(self.role, "nope", "test")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
