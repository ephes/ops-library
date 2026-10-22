import importlib.util
import json
from pathlib import Path
import subprocess
import stat
from types import SimpleNamespace
import contextlib
import io
import sys
import tempfile
import unittest
from unittest.mock import patch

FILES = Path(__file__).parents[1] / "roles/container_ca_activate/files"
sys.path.insert(0, str(FILES))
spec = importlib.util.spec_from_file_location(
    "persist_owners", FILES / "persist_owners.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
sys.path.pop(0)
PROTECTED = module.protected


class TestOwners(unittest.TestCase):
    def setUp(self):
        # Portable file fixtures run as the developer; actual-systemd tests run as root.
        guard = patch.object(module, "protected")
        guard.start()
        self.addCleanup(guard.stop)

    def test_protection_rejects_each_unsafe_metadata_condition(self):
        for uid, mode in [(501, 0o100644), (0, 0o100666), (0, 0o120644)]:
            with self.subTest(uid=uid, mode=mode), patch.object(
                Path, "lstat", return_value=SimpleNamespace(st_uid=uid, st_mode=mode)
            ), patch.object(Path, "is_symlink", return_value=stat.S_ISLNK(mode)):
                with self.assertRaisesRegex(ValueError, "protected"):
                    PROTECTED(Path("/metadata-only-test"))

    def fixture(self, root):
        store = root / "store"
        store.mkdir()
        (store / "bundle.pem").write_bytes(
            (Path(__file__).parent / "fixtures/activation-ca.txt").read_bytes()
        )
        (store / "empty").mkdir()
        (store / "manifest.json").write_text('{"image":"sha256:known"}')
        source = root / "compose.yml"
        source.write_text("services: {}")
        argv = ["/usr/bin/docker", "compose", "-p", "example", "-f", str(source)]
        owner = {
            "unit": "example.service",
            "working_directory": str(root),
            "start": argv + ["up", "-d", "--remove-orphans"],
            "stop": argv + ["down"],
            "reload": argv + ["up", "-d", "--remove-orphans"],
        }
        fragment = root / "units/example.service"
        fragment.parent.mkdir()
        fragment.write_text(
            "[Service]\nType=oneshot\nRemainAfterExit=yes\nWorkingDirectory="
            + str(root)
            + "\n"
            + "\n".join(
                key + "=" + " ".join(owner[name])
                for key, name in [
                    ("ExecStart", "start"),
                    ("ExecStop", "stop"),
                    ("ExecReload", "reload"),
                ]
            )
            + "\n"
        )
        owner["fragment_sha256"] = module.digest(fragment)
        project = {
            "project": "example",
            "directory": str(root),
            "files": [str(source)],
            "owner": owner,
            "containers": [
                {
                    "name": "example-server",
                    "service": "server",
                    "store": str(store),
                    "node": True,
                }
            ],
        }
        return project, fragment

    def runtime(self, project, node="--max-old-space-size=1536", image="sha256:known"):
        calls = []

        def execute(argv, input_text=None):
            calls.append(argv)
            if argv[:3] == ["systemctl", "show", "example.service"]:
                if "--property=FragmentPath" in argv:
                    return str(module.UNIT_ROOT / "example.service")
                managed = module.owner_paths(project)[2]
                return str(managed) if managed.exists() else ""
            if argv[:3] == ["docker", "image", "inspect"]:
                return json.dumps(
                    [
                        {
                            "Id": image,
                            "Config": {"Env": ["NODE_OPTIONS=--old-image-option"]},
                        }
                    ]
                )
            if argv[-3:] == ["config", "--format", "json"]:
                return json.dumps(
                    {
                        "services": {
                            "server": {
                                "image": "example:pinned",
                                "environment": {
                                    "NODE_OPTIONS": node,
                                    "APP_VALUE": "keep-value",
                                },
                            }
                        }
                    }
                )
            raise AssertionError(argv)

        return execute, calls

    def test_ca_only_overlay_derives_current_base_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, _ = self.fixture(Path(tmp))
            for option in ["--max-old-space-size=1536", "--max-old-space-size=2048"]:
                execute, _ = self.runtime(project, option)
                overlay = json.loads(module.ca_overlay(project, execute))["services"][
                    "server"
                ]
                self.assertNotIn("image", overlay)
                self.assertEqual(set(overlay), {"environment", "volumes"})
                self.assertEqual(
                    overlay["environment"]["NODE_OPTIONS"], option + " --use-openssl-ca"
                )
                self.assertNotIn("APP_VALUE", overlay["environment"])
                self.assertNotIn("keep-value", json.dumps(overlay))

    def test_changed_image_fails_before_any_native_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, _ = self.fixture(Path(tmp))
            execute, calls = self.runtime(project, image="sha256:changed")
            with self.assertRaisesRegex(ValueError, "image changed"):
                module.ca_overlay(project, execute)
            self.assertFalse(
                any(c[:1] == ["systemctl"] or "up" in c or "start" in c for c in calls)
            )

    def test_linuxserver_proof_binds_exact_image_and_hook_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, _ = self.fixture(root)
            record = project["containers"][0]
            record.pop("store")
            record.pop("node")
            hook = root / "hook"
            hook.mkdir()
            for name in ("repair_ca.py", "10-emudhra-ca.sh"):
                (hook / name).write_text("reviewed-" + name)
            record["linuxserver_hook"] = str(hook)
            record["linuxserver_proof"] = {
                "image": "sha256:known",
                "sha256": {
                    name: module.digest(hook / name)
                    for name in ("repair_ca.py", "10-emudhra-ca.sh")
                },
            }
            execute, _ = self.runtime(project)
            with patch.object(module, "protected"):
                self.assertNotIn(
                    "image",
                    json.loads(module.ca_overlay(project, execute))["services"][
                        "server"
                    ],
                )
                record["linuxserver_proof"].pop("image")
                record["linuxserver_proof"]["images"] = [
                    "sha256:known",
                    "sha256:candidate",
                ]
                module.ca_overlay(project, execute)
                record["linuxserver_proof"]["images"].append("sha256:third")
                with self.assertRaisesRegex(ValueError, "new reviewed trust proof"):
                    module.ca_overlay(project, execute)
                record["linuxserver_proof"]["images"] = [
                    "sha256:known",
                    "sha256:candidate",
                ]
                (hook / "repair_ca.py").write_text("unreviewed change")
                with self.assertRaisesRegex(ValueError, "hook proof changed"):
                    module.ca_overlay(project, execute)
                record["linuxserver_proof"]["images"] = ["sha256:other"]
                with self.assertRaisesRegex(ValueError, "new reviewed trust proof"):
                    module.ca_overlay(project, execute)

    def test_exact_owner_dropin_retains_flags_and_stop(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            module, "ROOT", Path(tmp) / "managed"
        ), patch.object(module, "UNIT_ROOT", Path(tmp) / "units"):
            project, _ = self.fixture(Path(tmp))
            execute, _ = self.runtime(project)
            with patch.object(module, "protected"):
                module.validate_owner(project, execute)
            content = module.dropin(project).decode()
            self.assertIn("up -d --remove-orphans", content)
            self.assertIn("ExecStartPre=", content)
            self.assertEqual(content.count("ExecReload="), 3)
            self.assertNotIn("ExecStop=", content)
            self.assertNotIn("image", content)

    def test_unknown_dropin_and_changed_fragment_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            module, "ROOT", Path(tmp) / "managed"
        ), patch.object(module, "UNIT_ROOT", Path(tmp) / "units"):
            project, fragment = self.fixture(Path(tmp))
            execute, _ = self.runtime(project)

            def overridden(argv, input_text=None):
                return (
                    "/etc/systemd/system/example.service.d/other.conf"
                    if "--property=DropInPaths" in argv
                    else execute(argv)
                )

            with patch.object(module, "protected"):
                with self.assertRaisesRegex(ValueError, "Unknown owner drop-in"):
                    module.validate_owner(project, overridden)
                fragment.write_text(
                    fragment.read_text() + "\n# changed by future deployment\n"
                )
                with self.assertRaisesRegex(ValueError, "fragment changed"):
                    module.validate_owner(project, execute)

    def test_missing_store_rejects_runtime_prepare_before_overlay_write(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            module, "ROOT", Path(tmp) / "managed"
        ), patch.object(module, "UNIT_ROOT", Path(tmp) / "units"):
            root = Path(tmp)
            project, _ = self.fixture(root)
            project["tool_sha256"] = {}
            config, overlay, managed = module.owner_paths(project)
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps(project))
            managed.parent.mkdir(parents=True)
            managed.write_bytes(module.dropin(project))
            execute, _ = self.runtime(project)
            (root / "store/bundle.pem").unlink()
            with patch.object(module, "protected"), patch.object(
                module, "validate_owner", return_value=(config, overlay, managed)
            ):
                with self.assertRaisesRegex(ValueError, "not prepared"):
                    module.prepare(config, execute)
            self.assertFalse(overlay.exists())

    def test_private_native_error_is_recoverable_and_not_echoed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner = module.Runner(root)
            response = subprocess.CompletedProcess(
                ["example"], 1, "private-token", "precise native failure"
            )
            with patch.object(module.subprocess, "run", return_value=response):
                with self.assertRaisesRegex(
                    RuntimeError, "private diagnostics"
                ) as error:
                    runner(["example"])
            self.assertNotIn("private-token", str(error.exception))
            logs = list(root.glob("command-error-*.txt"))
            self.assertEqual(len(logs), 1)
            self.assertIn("precise native failure", logs[0].read_text())
            self.assertEqual(logs[0].stat().st_mode & 0o777, 0o600)

    def test_unique_atomic_temporary_ignores_stale_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "trust.json"
            stale = target.with_name("trust.json.new")
            stale.write_text("interrupted")
            module.private_file(target, b"fresh")
            self.assertEqual(target.read_bytes(), b"fresh")
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(stale.read_text(), "interrupted")

    def test_environment_and_project_resolution_are_explicit(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            module, "ROOT", Path(tmp) / "managed"
        ), patch.object(module, "UNIT_ROOT", Path(tmp) / "units"):
            project, fragment = self.fixture(Path(tmp))
            execute, _ = self.runtime(project)
            fragment.write_text(fragment.read_text() + "Environment=EXAMPLE=value\n")
            project["owner"]["fragment_sha256"] = module.digest(fragment)
            with self.assertRaisesRegex(ValueError, "environment"):
                module.validate_owner(project, execute)
            fragment.write_text(
                fragment.read_text()
                .replace("Environment=EXAMPLE=value\n", "")
                .replace(str(tmp), str(Path(tmp) / "other"), 1)
            )
            project["owner"]["fragment_sha256"] = module.digest(fragment)
            project["owner"]["working_directory"] = project["directory"] = str(
                Path(tmp) / "other"
            )
            with self.assertRaisesRegex(ValueError, "paths differ"):
                module.validate_owner(project, execute)

    def test_runtime_tool_drift_fails_before_composition(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            module, "ROOT", Path(tmp) / "managed"
        ):
            module.ROOT.mkdir()
            config = module.ROOT / "owner.json"
            (module.ROOT / "persist_owners.py").write_text("unexpected")
            config.write_text(
                json.dumps({"tool_sha256": {"persist_owners.py": "expected"}})
            )
            calls = []
            with self.assertRaisesRegex(ValueError, "tool drift"):
                module.prepare(config, lambda *args: calls.append(args))
            self.assertEqual(calls, [])

    def plan_fixture(self, root):
        project, _ = self.fixture(root)
        execute, _ = self.runtime(project)
        state = {"Name": "/example-server", "Mounts": [{"Type": "bind"}]}
        return project, execute, state

    def test_managed_reconciliation_is_exact_and_check_reports_changed_bytes(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            module, "ROOT", Path(tmp) / "managed"
        ), patch.object(module, "UNIT_ROOT", Path(tmp) / "units"):
            root = Path(tmp)
            project, execute, state = self.plan_fixture(root)
            with patch.object(module.activate, "preflight", return_value=([state], [])):
                artifacts, _ = module.plan([project], execute)
                for path, data in artifacts.items():
                    module.private_file(path, data)
                self.assertEqual(module.plan([project], execute)[0], artifacts)
                policy = root / "policy.json"
                policy.write_text("{}")
                project["containers"][0]["chrome_policy"] = str(policy)
                with self.assertRaisesRegex(ValueError, "artifact drift"):
                    module.plan([project], execute)
                approved = module.managed_hashes([project])
                changed, _ = module.plan([project], execute, approved)
                self.assertTrue(
                    any(path.read_bytes() != data for path, data in changed.items())
                )
                with patch.object(
                    module, "plan", return_value=(changed, [state])
                ), patch.object(module, "Runner", return_value=execute), patch.object(
                    module.os, "geteuid", return_value=0
                ), patch.object(
                    module.sys, "platform", "linux"
                ), patch.object(
                    module.sys,
                    "argv",
                    [
                        "persist_owners.py",
                        json.dumps([project]),
                        "--check",
                        json.dumps(approved),
                    ],
                ), contextlib.redirect_stdout(
                    io.StringIO()
                ) as out:
                    module.main()
                self.assertEqual(out.getvalue().splitlines()[0], "CHANGED")
                stale = dict(approved)
                stale[next(iter(stale))] = "wrong"
                with self.assertRaisesRegex(ValueError, "exact hashes"):
                    module.plan([project], execute, stale)
                incomplete = dict(approved)
                incomplete.pop(next(iter(incomplete)))
                with self.assertRaisesRegex(ValueError, "exact hashes"):
                    module.plan([project], execute, incomplete)

    def test_non_bind_data_volume_requires_explicit_review(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            module, "ROOT", Path(tmp) / "managed"
        ), patch.object(module, "UNIT_ROOT", Path(tmp) / "units"):
            project, execute, state = self.plan_fixture(Path(tmp))
            state["Mounts"] = [{"Type": "volume"}]
            with patch.object(module.activate, "preflight", return_value=([state], [])):
                with self.assertRaisesRegex(ValueError, "non-bind volume"):
                    module.plan([project], execute)

    def test_success_receipt_failure_does_not_restart_healthy_owners_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "artifact"
            calls = []
            original_write = module.private_file

            def write(path, data):
                if (
                    path.name == "result.json"
                    and json.loads(data)["status"] == "activated"
                ):
                    raise OSError("injected full receipt volume")
                original_write(path, data)

            with patch.object(
                module,
                "plan",
                return_value=({artifact: b"new"}, [{"Name": "/example"}]),
            ), patch.object(module.activate, "healthy"), patch.object(
                module, "private_file", side_effect=write
            ), contextlib.redirect_stdout(
                io.StringIO()
            ) as out:
                self.assertTrue(
                    module.apply(
                        [{"owner": {"unit": "example.service"}}],
                        root / "receipt",
                        lambda argv, **kw: calls.append(argv),
                    )
                )
            self.assertEqual(
                calls,
                [
                    ["systemctl", "stop", "example.service"],
                    ["systemctl", "daemon-reload"],
                    ["systemctl", "start", "example.service"],
                ],
            )
            self.assertIn("WARNING", out.getvalue())

    def test_unchanged_apply_never_stops_an_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "artifact"
            artifact.write_bytes(b"known")
            calls = []
            with patch.object(module, "plan", return_value=({artifact: b"known"}, [])):
                self.assertFalse(
                    module.apply(
                        [{"owner": {"unit": "example.service"}}],
                        root / "receipt",
                        lambda *args: calls.append(args),
                    )
                )
            self.assertEqual(calls, [])
            self.assertEqual(
                json.loads((root / "receipt/result.json").read_text())["status"],
                "unchanged",
            )

    def owner_health_case(self, activation_ready, recovery_ready=None):
        # Exercise the actual health polling loop through the production caller.
        # A 194-second native check models startup grace plus a 180-second interval.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "managed.conf"
            artifact.write_bytes(b"original")
            projects = [
                {"owner": {"unit": n + ".service"}} for n in ("first", "second")
            ]
            original = [{"Name": "/first"}, {"Name": "/second"}]
            calls = []
            clock = [0.0]
            starts = [0]
            phase_started = [0.0]

            def execute(argv, input_text=None):
                calls.append(argv)
                if argv == ["systemctl", "start", "first.service"]:
                    starts[0] += 1
                    phase_started[0] = clock[0]
                return ""

            def states(names, execute):
                ready = activation_ready if starts[0] == 1 else recovery_ready
                healthy = ready is not None and clock[0] - phase_started[0] >= ready
                return [
                    {
                        "State": {
                            "Running": True,
                            "Health": {"Status": "healthy" if healthy else "starting"},
                        }
                    }
                    for _ in names
                ]

            def sleep(seconds):
                clock[0] += seconds

            real_healthy = module.activate.healthy
            with (
                patch.object(
                    module, "plan", return_value=({artifact: b"new"}, original)
                ),
                patch.object(module.activate, "inspect", side_effect=states),
                patch.object(
                    module.activate.time, "monotonic", side_effect=lambda: clock[0]
                ),
                patch.object(module.activate.time, "sleep", side_effect=sleep),
                patch.object(module.activate, "healthy", wraps=real_healthy) as health,
            ):
                if activation_ready is None:
                    with self.assertRaisesRegex(
                        RuntimeError, "Owner activation failed"
                    ):
                        module.apply(projects, root / "receipt", execute)
                else:
                    self.assertTrue(module.apply(projects, root / "receipt", execute))
            expected_calls = 2 if activation_ready is None else 1
            self.assertEqual(health.call_count, expected_calls)
            for call in health.call_args_list:
                self.assertEqual(call.args, (["first", "second"], execute))
                self.assertEqual(call.kwargs, {"timeout": 600})
            self.assertFalse(
                any("restart" in c or "docker.service" in c for c in calls)
            )
            outcome = json.loads((root / "receipt/result.json").read_text())
            self.assertFalse(outcome["docker_restart_attempted"])
            if activation_ready is None:
                self.assertEqual(artifact.read_bytes(), b"original")
                for name in ("first", "second"):
                    self.assertEqual(
                        calls.count(["systemctl", "start", name + ".service"]), 2
                    )
            return outcome, clock[0]

    def test_native_owner_activation_waits_for_delayed_native_health(self):
        outcome, elapsed = self.owner_health_case(194)
        self.assertEqual(outcome["status"], "activated")
        self.assertEqual(elapsed, 194)

    def test_native_owner_recovery_has_its_own_extended_health_budget(self):
        outcome, elapsed = self.owner_health_case(None, 194)
        self.assertEqual(outcome["status"], "rolled_back")
        self.assertEqual(elapsed, 600 + 194)

    def test_native_owner_health_budgets_exhaust_and_fail_closed(self):
        outcome, elapsed = self.owner_health_case(None, None)
        self.assertEqual(outcome["status"], "recovery_failed")
        self.assertEqual(elapsed, 600 + 600)
        self.assertIn("recovery-health", outcome["failures"])

    def recovery_case(self, root, fail_recovery):
        artifact = root / "managed.conf"
        artifact.write_bytes(b"original")
        projects = [
            {"owner": {"unit": name + ".service"}} for name in ["first", "second"]
        ]
        original = [{"Name": "/first"}, {"Name": "/second"}]
        calls = []
        first_starts = 0

        def execute(argv, input_text=None):
            nonlocal first_starts
            calls.append(argv)
            if argv == ["systemctl", "start", "first.service"]:
                first_starts += 1
                if first_starts == 1 or fail_recovery:
                    raise RuntimeError("injected first-owner failure")
            return ""

        with patch.object(
            module, "plan", return_value=({artifact: b"new"}, original)
        ), patch.object(module.activate, "healthy"):
            with self.assertRaisesRegex(RuntimeError, "Owner activation failed"):
                module.apply(projects, root / "receipt", execute)
        self.assertEqual(artifact.read_bytes(), b"original")
        self.assertEqual(calls.count(["systemctl", "start", "second.service"]), 2)
        self.assertFalse(any("restart" in c or "docker.service" in c for c in calls))
        outcome = json.loads((root / "receipt/result.json").read_text())
        self.assertEqual(
            outcome["status"], "recovery_failed" if fail_recovery else "rolled_back"
        )
        self.assertFalse(outcome["docker_restart_attempted"])

    def test_first_activation_failure_does_not_skip_other_owner_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.recovery_case(Path(tmp), False)

    def test_first_recovery_failure_still_attempts_remaining_owners(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.recovery_case(Path(tmp), True)


if __name__ == "__main__":
    unittest.main()
