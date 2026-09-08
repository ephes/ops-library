"""Transactions fail closed and recover real files on restart/probe failures."""

import base64
import copy
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "roles/traefik_deploy/files" / (name + ".py")
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


tx = module("traefik_transaction")
ctl = module("traefik_control")
health = module("traefik_health_probe")


class HealthProbeTests(unittest.TestCase):
    def test_timeout_is_an_observation(self):
        with patch.object(
            health.subprocess,
            "run",
            side_effect=health.subprocess.TimeoutExpired("curl", 12),
        ):
            self.assertEqual(
                health.observe(
                    {
                        "host": "example.invalid",
                        "port": 443,
                        "scheme": "https",
                        "address": "127.0.0.1",
                    }
                ),
                {"status": "", "exit": 28},
            )

    def test_backend_recovery_is_allowed_but_auth_and_redirect_changes_fail(self):
        def result(code):
            return {"status": code, "exit": 0}

        self.assertTrue(health.acceptable(result("502"), result("200")))
        for before, after in (
            ("401", "200"),
            ("403", "200"),
            ("301", "302"),
            ("200", "502"),
        ):
            self.assertFalse(health.acceptable(result(before), result(after)))

    def test_cleanup_reports_verified_tree_and_refuses_routing_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "checks.json"
            config.write_text(
                json.dumps(
                    {
                        "probes": [{"host": "example.invalid"}],
                        "dynamic": {"route.yml": "before"},
                    }
                )
            )
            with patch("sys.argv", ["probe", "cleanup", str(config)]):
                output = io.StringIO()
                with patch.object(
                    health, "tree", return_value={"route.yml": "before"}
                ), patch("sys.stdout", output):
                    health.main()
                self.assertEqual(
                    json.loads(output.getvalue()),
                    {"cleanup": "no temporary resources", "dynamic_verified": True},
                )
                with patch.object(
                    health, "tree", return_value={"route.yml": "changed"}
                ), self.assertRaisesRegex(RuntimeError, "Permanent routing changed"):
                    health.main()

    def test_empty_capture_and_acceptance_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "checks.json"
            config.write_text(
                json.dumps({"probes": [], "observations": [], "dynamic": {}})
            )
            for mode in ("capture", "health", "alias"):
                with patch(
                    "sys.argv", ["probe", mode, str(config)]
                ), self.assertRaisesRegex(ValueError, "At least one"):
                    health.main()


class RecoveryEvidenceTests(unittest.TestCase):
    def test_verified_ssh_or_legacy_console_reference_is_required(self):
        proof = {
            "baseline": {},
            "verified_at": tx.time.time(),
            "owner": "operator",
            "review_reference": "approved proxy-only update",
            "independent_observer": "controller",
            "observer_delivery_test": "live HTTP observation",
            "observer_watch_active": True,
        }
        for key in ("recovery_access", "console_recovery"):
            tx.evidence({"evidence": {**proof, key: "verified access"}}, {})
        with self.assertRaises(tx.Refused):
            tx.evidence({"evidence": proof}, {})
        for key in ("recovery_access", "console_recovery"):
            for value in (None, "", "CHANGEME"):
                with self.assertRaises(tx.Refused):
                    tx.evidence({"evidence": {**proof, key: value}}, {})
        # An explicitly invalid new field must not be hidden by a legacy value.
        with self.assertRaises(tx.Refused):
            tx.evidence(
                {
                    "evidence": {
                        **proof,
                        "recovery_access": None,
                        "console_recovery": "verified legacy access",
                    }
                },
                {},
            )


class StartupArgumentTests(unittest.TestCase):
    def test_flag_case_is_equivalent_but_path_and_extra_arguments_are_strict(self):
        binary, config = (
            Path("/usr/local/bin/traefik"),
            Path("/etc/traefik/traefik.toml"),
        )
        for flag in (b"--configfile=", b"--configFile="):
            tx.validate_arguments([bytes(binary), flag + bytes(config)], binary, config)
        for args in (
            [bytes(binary), b"--configFile=/etc/traefik/OTHER.toml"],
            [bytes(binary), b"--configFile=" + bytes(config), b"--api.insecure=true"],
            [b"/different/traefik", b"--configfile=" + bytes(config)],
        ):
            with self.assertRaises(tx.Refused):
                tx.validate_arguments(args, binary, config)


class AliasTests(unittest.TestCase):
    before = b'[entryPoints.web]\naddress=":80"\n[entryPoints.secure]\naddress=":443"\n'
    after = (
        before
        + b'[entryPoints.web.http]\naliasHeadersStrategy="delete"\n[entryPoints.secure.http]\naliasHeadersStrategy="delete"\n'
    )
    policy: ClassVar[dict] = {"web": "delete", "secure": "delete"}

    def test_only_alias_delta_accepted(self):
        tx.validate_alias(self.before, self.after, self.policy)

    def test_timeout_or_provider_change_rejected(self):
        for suffix in [
            b'\n[providers.file]\ndirectory="/elsewhere"\n',
            b'\n[entryPoints.web.transport.respondingTimeouts]\nreadTimeout="600s"\n',
        ]:
            with self.assertRaises(tx.Refused):
                tx.validate_alias(self.before, self.after + suffix, self.policy)

    def test_missing_entrypoint_and_legacy_policy_rejected(self):
        with self.assertRaises(tx.Refused):
            tx.validate_alias(self.before, self.after, {"web": "delete"})
        before = (
            self.before + b'[entryPoints.web.http]\nunderscoreHeadersStrategy="keep"\n'
        )
        with self.assertRaises(tx.Refused):
            tx.validate_alias(before, self.after, self.policy)


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "traefik.toml"
        self.config.write_bytes(AliasTests.before)
        self.binary = self.root / "traefik"
        self.binary.write_bytes(b"old executable")
        self.binary.chmod(0o755)
        self.state_root = self.root / "state"
        self.state_root.mkdir(mode=0o700)
        self.policy = {
            "host": "fixture",
            "config_path": str(self.config),
            "binary_path": str(self.binary),
            "alias_policy": AliasTests.policy,
        }
        self.live = {
            "version": "3.7.12",
            "binary_sha256": tx.digest(self.binary),
            "config_sha256": tx.digest(self.config),
            "dynamic_sha256": "dynamic",
            "unit_sha256": "unit",
        }
        self.state = tx.state_for(self.policy, "clear", self.live)
        self.state_path = self.state_root / "state.json"
        tx.save(self.state_path, self.state)
        self.request = {
            "policy": self.policy,
            "action": "alias",
            "controller_state": self.state,
            "evidence": {"owner": "operator"},
            "baseline_probe": {"fixture": "baseline"},
            "acceptance_probe": {"fixture": "acceptance"},
            "cleanup_probe": {"fixture": "cleanup"},
            "approved_binary_sha256": self.live["binary_sha256"],
            "candidate_config_base64": base64.b64encode(AliasTests.after).decode(),
            "compatibility": {
                "baseline": self.live,
                "architecture": os.uname().machine,
                "passed": True,
                "baseline_pair_passed": True,
                "report_reference": "fixture",
                "candidate_binary_sha256": self.live["binary_sha256"],
                "candidate_config_sha256": tx.hashlib.sha256(
                    AliasTests.after
                ).hexdigest(),
            },
        }
        patches = [
            patch.object(tx, "STATE_ROOT", self.state_root),
            patch.object(tx, "LOCK", self.root / "lock"),
            patch.object(tx, "validate_policy"),
            patch.object(tx, "trusted_file"),
            patch.object(tx.os, "geteuid", return_value=0),
            patch.object(tx, "evidence"),
            patch.object(tx, "identity", return_value=self.live),
            patch.object(tx, "check_probe"),
            patch.object(tx, "backup"),
        ]
        # State-dir ownership is a production invariant; tests retain real mode
        # checks but use the current user's owned temporary directory.
        self.real_uid = self.state_root.stat().st_uid
        self.request["test"] = True
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        # Only the root ownership check is replaced, never transaction logic.
        original_require = tx.require

        def checked(ok, message):
            if message == "unsafe state directory":
                ok = (
                    self.state_root.is_dir()
                    and self.state_root.stat().st_mode & 0o777 == 0o700
                )
            original_require(ok, message)

        p = patch.object(tx, "require", side_effect=checked)
        p.start()
        self.addCleanup(p.stop)

    def read_state(self):
        return json.loads(self.state_path.read_text())

    def test_binary_replacement_restarts_and_preserves_configuration(self):
        candidate = self.root / "new-binary"
        candidate.write_bytes(b"new executable")
        self.request.update(
            action="binary",
            release={"version": "3.7.13", "sha256": "a" * 64},
            archive_path="fixture",
        )
        expected = dict(self.live, version="3.7.13", binary_sha256=tx.digest(candidate))
        self.request["compatibility"].update(
            candidate_binary_sha256=expected["binary_sha256"],
            candidate_config_sha256=self.live["config_sha256"],
        )
        acme = self.root / "acme.json"
        acme.write_bytes(b"newer certificate state")
        with (
            patch.object(tx, "candidate_binary", return_value=candidate),
            patch.object(tx, "restart_verify", return_value=expected) as restart,
        ):
            result = tx.execute(self.request)
        self.assertTrue(result["changed"])
        restart.assert_called_once()
        self.assertEqual(self.binary.read_bytes(), b"new executable")
        self.assertEqual(self.config.read_bytes(), AliasTests.before)
        self.assertEqual(acme.read_bytes(), b"newer certificate state")

    def test_binary_rollback_recovers_original_and_no_config_or_acme_overwrite(self):
        candidate = self.root / "new-binary"
        candidate.write_bytes(b"new executable")
        self.request.update(
            action="binary",
            release={"version": "3.7.13", "sha256": "a" * 64},
            archive_path="fixture",
        )
        self.request["compatibility"].update(
            candidate_binary_sha256=tx.digest(candidate),
            candidate_config_sha256=self.live["config_sha256"],
        )
        acme = self.root / "acme.json"
        acme.write_bytes(b"newer certificate state")
        with (
            patch.object(tx, "candidate_binary", return_value=candidate),
            patch.object(
                tx,
                "restart_verify",
                side_effect=[tx.Refused("failed candidate"), self.live],
            ),
        ):
            result = tx.execute(self.request)
        self.assertEqual(result["state"]["phase"], "recovery")
        self.assertEqual(self.binary.read_bytes(), b"old executable")
        self.assertEqual(self.config.read_bytes(), AliasTests.before)
        self.assertEqual(acme.read_bytes(), b"newer certificate state")

    def test_alias_success_and_atomic_replacement(self):
        expected = dict(
            self.live, config_sha256=tx.hashlib.sha256(AliasTests.after).hexdigest()
        )
        with patch.object(tx, "restart_verify", return_value=expected) as restart:
            result = tx.execute(self.request)
        self.assertEqual(self.config.read_bytes(), AliasTests.after)
        self.assertEqual(result["state"]["phase"], "clear")
        self.assertEqual(restart.call_count, 1)
        self.assertEqual(self.read_state(), result["state"])

    def test_failed_start_restores_config_and_leaves_recovery(self):
        with patch.object(
            tx, "restart_verify", side_effect=[tx.Refused("start failed"), self.live]
        ):
            result = tx.execute(self.request)
        self.assertTrue(result["failed"])
        self.assertEqual(self.config.read_bytes(), AliasTests.before)
        self.assertEqual(self.read_state()["phase"], "recovery")

    def test_failed_recovery_is_degraded(self):
        with patch.object(
            tx, "restart_verify", side_effect=tx.Refused("still unhealthy")
        ):
            result = tx.execute(self.request)
        self.assertEqual(result["state"]["phase"], "degraded")
        self.assertIn("review_due", result["state"])

    def test_noop_never_restarts(self):
        self.config.write_bytes(AliasTests.after)
        self.live["config_sha256"] = tx.digest(self.config)
        self.state["identity"] = self.live
        self.request["compatibility"]["baseline"] = self.live
        tx.save(self.state_path, self.state)
        with patch.object(tx, "restart_verify") as restart:
            result = tx.execute(self.request)
        self.assertFalse(result["changed"])
        restart.assert_not_called()

    def test_mismatched_or_missing_records_never_write_config(self):
        for state in [
            None,
            dict(self.state, phase="recovery"),
            dict(self.state, revision="wrong"),
        ]:
            request = copy.deepcopy(self.request)
            request["controller_state"] = state
            with self.assertRaises(tx.Refused):
                tx.execute(request)
            self.assertEqual(self.config.read_bytes(), AliasTests.before)

    def test_enrollment_never_clears_existing_state(self):
        self.request["action"] = "enroll"
        with self.assertRaises(tx.Refused):
            tx.execute(self.request)
        self.assertEqual(self.read_state(), self.state)

    def test_binary_digest_and_version_guard_for_alias(self):
        for key, value in [("version", "3.7.9"), ("binary_sha256", "unapproved")]:
            saved = self.live[key]
            self.live[key] = value
            self.state["identity"] = self.live
            tx.save(self.state_path, self.state)
            with self.assertRaises(tx.Refused):
                tx.execute(self.request)
            self.live[key] = saved

    def test_native_architecture_required(self):
        self.request["compatibility"]["architecture"] = "different-platform"
        with self.assertRaises(tx.Refused):
            tx.execute(self.request)

    def test_archive_checksum_refused_before_execution(self):
        archive = self.root / "release.tar.gz"
        archive.write_bytes(b"untrusted")
        with patch.object(tx, "version") as probe, self.assertRaises(tx.Refused):
            tx.candidate_binary(archive, "0" * 64, self.root, "3.7.12")
        probe.assert_not_called()


class AcceptanceTests(unittest.TestCase):
    def test_failed_acceptance_runs_cleanup_once_without_retrying_traffic(self):
        with (
            patch.object(tx, "run"),
            patch.object(tx, "identity", return_value={}),
            patch.object(
                tx, "check_probe", side_effect=[tx.Refused("bad ingress"), None]
            ) as probe,
            self.assertRaises(tx.Refused),
        ):
            tx.restart_verify({}, {}, {"kind": "acceptance"}, {"kind": "cleanup"})
        self.assertEqual(
            [call.args[0]["kind"] for call in probe.call_args_list],
            ["acceptance", "cleanup"],
        )

    def test_identity_is_checked_after_probe_cleanup(self):
        with (
            patch.object(tx, "run"),
            patch.object(tx, "identity", side_effect=[{}, {"drift": True}]),
            patch.object(tx, "check_probe"),
            self.assertRaises(tx.Refused),
        ):
            tx.restart_verify({}, {}, {}, {})


class ControllerTests(unittest.TestCase):
    registry: ClassVar[dict] = {
        "schema": 1,
        "hosts": {"fixture": {"desired_release": "3.7.12"}},
        "releases": {
            "3.7.12": {
                "approval_reference": "approved",
                "linux_amd64": {"sha256": "a" * 64},
            }
        },
    }

    def test_unknown_host_and_request_policy_override(self):
        with self.assertRaises(ValueError):
            ctl.make_request(self.registry, "all", "binary", {})
        request = ctl.make_request(
            self.registry,
            "fixture",
            "binary",
            {"policy": {"host": "other"}, "release": {"version": "old"}},
        )
        self.assertEqual(request["policy"]["host"], "fixture")
        self.assertEqual(request["release"]["version"], "3.7.12")

    def test_incomplete_request_never_sets_pending(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            journal = root / "journal"
            journal.mkdir(mode=0o700)
            initial = {"schema": 1, "host": "fixture", "phase": "clear"}
            ctl.write_json(journal / "fixture.json", initial)
            with patch.object(ctl, "invoke") as invoke, self.assertRaises(ValueError):
                ctl.control(root, self.registry, "fixture", "binary", {}, journal)
            invoke.assert_not_called()
            self.assertEqual(
                json.loads((journal / "fixture.json").read_text()), initial
            )

    def test_alias_request_requires_candidate_before_pending(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            journal = root / "journal"
            journal.mkdir(mode=0o700)
            initial = {"schema": 1, "host": "fixture", "phase": "clear"}
            ctl.write_json(journal / "fixture.json", initial)
            supplied = {
                "evidence": {},
                "compatibility": {},
                "baseline_probe": {},
                "acceptance_probe": {},
                "cleanup_probe": {},
            }
            with patch.object(ctl, "invoke") as invoke, self.assertRaises(ValueError):
                ctl.control(root, self.registry, "fixture", "alias", supplied, journal)
            invoke.assert_not_called()
            self.assertEqual(
                json.loads((journal / "fixture.json").read_text()), initial
            )

    def test_bad_fresh_observation_never_sets_pending(self):
        for observed in (
            {},
            {"identity": {}, "state": {"phase": "recovery"}},
            {
                "identity": {"changed": True},
                "state": {"schema": 1, "host": "fixture", "phase": "clear"},
            },
        ):
            with (
                self.subTest(observed=observed),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                journal = root / "journal"
                journal.mkdir(mode=0o700)
                initial = {"schema": 1, "host": "fixture", "phase": "clear"}
                ctl.write_json(journal / "fixture.json", initial)
                supplied = {
                    "evidence": {"baseline": {}},
                    "compatibility": {},
                    "baseline_probe": {},
                    "acceptance_probe": {},
                    "cleanup_probe": {},
                }
                with (
                    patch.object(ctl, "invoke", return_value=(0, observed)),
                    self.assertRaises(ValueError),
                ):
                    ctl.control(
                        root, self.registry, "fixture", "binary", supplied, journal
                    )
                self.assertEqual(
                    json.loads((journal / "fixture.json").read_text()), initial
                )

    def test_readonly_preflight_failure_preserves_clear_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            journal = root / "journal"
            journal.mkdir(mode=0o700)
            initial = {"schema": 1, "host": "fixture", "phase": "clear"}
            ctl.write_json(journal / "fixture.json", initial)
            supplied = {
                "evidence": {"baseline": {}},
                "compatibility": {},
                "baseline_probe": {},
                "acceptance_probe": {},
                "cleanup_probe": {},
            }
            with (
                patch.object(ctl, "invoke", return_value=(1, {})),
                self.assertRaises(ValueError),
            ):
                ctl.control(root, self.registry, "fixture", "binary", supplied, journal)
            self.assertEqual(
                json.loads((journal / "fixture.json").read_text()), initial
            )

    def test_transport_failure_preserves_pending_and_refuses_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            journal = root / "journal"
            journal.mkdir(mode=0o700)
            initial = {"schema": 1, "host": "fixture", "phase": "clear"}
            ctl.write_json(journal / "fixture.json", initial)
            with patch.object(
                ctl,
                "invoke",
                side_effect=[(0, {"identity": {}, "state": initial}), (255, {})],
            ):
                result = ctl.control(
                    root,
                    self.registry,
                    "fixture",
                    "binary",
                    {
                        "evidence": {"baseline": {}},
                        "compatibility": {},
                        "baseline_probe": {},
                        "acceptance_probe": {},
                        "cleanup_probe": {},
                    },
                    journal,
                )
            self.assertEqual(result, 255)
            self.assertEqual(
                json.loads((journal / "fixture.json").read_text())["phase"], "pending"
            )
            with patch.object(ctl, "invoke") as invoke, self.assertRaises(ValueError):
                ctl.control(root, self.registry, "fixture", "binary", {}, journal)
            invoke.assert_not_called()


if __name__ == "__main__":
    unittest.main()
