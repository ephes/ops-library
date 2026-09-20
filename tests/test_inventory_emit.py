import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

FILES = Path(__file__).resolve().parents[1] / "roles/software_estate/files"
sys.path.insert(0, str(FILES))
try:
    import emit
    import vector_inventory_config as config
finally:
    sys.path.pop(0)


class InventoryEmitterTests(unittest.TestCase):
    def observation(self):
        return {
            "host": "test",
            "collector": "software-estate/1",
            "observed_at": 1700000000,
            "categories": {
                name: {"status": "ok", "items": []}
                for name in ("packages", "services", "containers")
            },
            "applications": [],
            "gaps": [],
        }

    def test_adapter_maps_real_collector_schema_and_timestamp(self):
        observation = self.observation()
        observation["categories"]["application_bundles"] = {
            "status": "ok",
            "items": [{"name": "App", "version": "1"}],
        }
        result = emit.envelope(observation)
        self.assertEqual(
            set(result["categories"]),
            {"packages", "units", "containers", "applications"},
        )
        self.assertEqual(result["observed_at"], "2023-11-14T22:13:20+00:00")
        self.assertEqual(
            result["categories"]["applications"]["items"][0]["id"],
            "macos-application-bundles",
        )

    def test_failed_application_category_does_not_claim_success(self):
        observation = self.observation()
        observation["applications"] = [{"id": "app", "status": "error", "items": []}]
        self.assertEqual(
            emit.envelope(observation)["categories"]["applications"],
            {"status": "error", "items": [], "error": "application_probe_failed"},
        )

    def test_opt_in_preserves_partial_evidence_without_claiming_success(self):
        observation = self.observation()
        apps = [
            {"id": "working", "status": "ok", "items": {"installed_version": "1.2"}},
            {
                "id": "missing",
                "status": "error",
                "items": [],
                "error": "PermissionError",
            },
        ]
        observation["applications"] = apps
        legacy = emit.envelope(observation)["categories"]["applications"]
        self.assertNotIn("partial_items", legacy)
        category = emit.envelope(observation, preserve_partial=True)["categories"][
            "applications"
        ]
        self.assertEqual(category["status"], "error")
        self.assertEqual(category["items"], [])
        self.assertEqual(category["partial_items"], apps)
        observation["applications"] = apps[:1]
        self.assertNotIn(
            "partial_items",
            emit.envelope(observation, preserve_partial=True)["categories"][
                "applications"
            ],
        )
        for invalid in ["false", 1, None]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                emit.collect.validate_policy(
                    {"host": "test", "preserve_partial_applications": invalid}
                )

    def test_cli_reads_partial_evidence_opt_in(self):
        observation = self.observation()
        observation["applications"] = [{"id": "broken", "status": "error", "items": []}]
        with tempfile.TemporaryDirectory() as tmp:
            policy = Path(tmp) / "policy.json"
            policy.write_text(
                json.dumps({"host": "test", "preserve_partial_applications": True})
            )
            with (
                patch.object(
                    sys, "argv", ["emit", "--policy", str(policy), "--spool", tmp]
                ),
                patch.object(emit.collect, "collect", return_value=observation),
                patch("builtins.print"),
            ):
                emit.main()
            report = json.loads(next(Path(tmp).glob("*.ndjson")).read_text())
            self.assertEqual(
                report["categories"]["applications"]["partial_items"],
                observation["applications"],
            )

    def test_invalid_cli_policy_fails_before_scanning_or_writing(self):
        for invalid in ["false", 1, None]:
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as tmp:
                policy = Path(tmp) / "policy.json"
                policy.write_text(
                    json.dumps(
                        {"host": "test", "preserve_partial_applications": invalid}
                    )
                )
                with (
                    patch.object(
                        sys, "argv", ["emit", "--policy", str(policy), "--spool", tmp]
                    ),
                    patch.object(emit.collect, "packages") as packages,
                    self.assertRaisesRegex(ValueError, "preserve_partial_applications"),
                ):
                    emit.main()
                packages.assert_not_called()
                self.assertEqual(list(Path(tmp).rglob("*.ndjson")), [])

    def test_partial_probe_error_does_not_export_exception_message(self):
        with patch.object(
            emit.collect,
            "application",
            side_effect=RuntimeError("private-command-output"),
        ):
            observed = emit.collect.category(lambda: emit.collect.application({}, []))
        observation = self.observation()
        observation["applications"] = [{"id": "broken", **observed}]
        report = emit.envelope(observation, preserve_partial=True)
        self.assertEqual(
            report["categories"]["applications"]["partial_items"][0]["error"],
            "RuntimeError",
        )
        self.assertNotIn("private-command-output", json.dumps(report))

    def test_nested_probe_failures_reach_the_envelope(self):
        for field, probe in [
            ("path", "git_checkout"),
            ("venv", "python_packages"),
            ("version_probe", "media_version"),
        ]:
            with (
                self.subTest(field=field),
                patch.object(
                    emit.collect, probe, side_effect=RuntimeError("unavailable")
                ) as failed,
            ):
                spec = {
                    "id": "app",
                    field: "/missing" if field != "version_probe" else "jellyfin",
                }
                observed = emit.collect.category(
                    lambda: emit.collect.application(spec, [])
                )
                failed.assert_called_once()
                observation = self.observation()
                observation["applications"] = [{"id": "app", **observed}]
                self.assertEqual(
                    emit.envelope(observation)["categories"]["applications"]["status"],
                    "error",
                )

    def test_invalid_application_ids_fail_before_collection(self):
        for applications in [
            [{"id": ""}],
            [{"id": " "}],
            [{"id": "same"}, {"id": "same"}],
        ]:
            with (
                self.subTest(applications=applications),
                patch.object(
                    emit.collect, "category", return_value={"status": "ok", "items": []}
                ) as probe,
            ):
                with self.assertRaises(ValueError):
                    emit.collect.collect({"host": "test", "applications": applications})
                probe.assert_not_called()

    def test_missing_package_evidence_reaches_application_failure(self):
        for package_probe in (
            RuntimeError("timeout"),
            emit.collect.UnsupportedProbe("missing"),
        ):
            with self.subTest(probe=type(package_probe).__name__), patch.object(
                emit.collect.platform, "system", return_value="Linux"
            ), patch.object(
                emit.collect, "packages", side_effect=package_probe
            ), patch.object(
                emit.collect, "units", return_value=[]
            ), patch.object(
                emit.collect, "containers", return_value=[]
            ), patch.object(
                emit.collect, "command", return_value=""
            ):
                observed = emit.collect.collect(
                    {
                        "host": "test",
                        "applications": [
                            {
                                "id": "app",
                                "packages": ["example"],
                                "primary_package": "example",
                            }
                        ],
                    }
                )
                self.assertIn(
                    "packages:host_probe_unavailable",
                    observed["applications"][0]["items"]["coverage"],
                )
                self.assertEqual(
                    emit.envelope(observed)["categories"]["applications"]["status"],
                    "error",
                )

    def test_unresolved_primary_package_is_a_coverage_gap(self):
        for primary in (None, "missing"):
            with self.subTest(primary=primary), patch.object(
                emit.collect, "command", return_value=""
            ):
                app = emit.collect.application(
                    {
                        "id": "app",
                        "packages": ["dependency"],
                        "primary_package": primary,
                    },
                    [{"name": "dependency", "version": "1"}],
                )
                self.assertIn("installed_version:unknown", app["coverage"])

    def test_primary_package_matches_debian_architecture_suffix(self):
        with patch.object(emit.collect, "command", return_value=""):
            app = emit.collect.application(
                {"id": "app", "packages": ["example"], "primary_package": "example"},
                [{"name": "example:amd64", "version": "1.2.3"}],
            )
        self.assertEqual(app["installed_version"], "1.2.3")
        self.assertEqual(app["coverage"], [])
        observed = self.observation()
        observed["applications"] = [{"id": "app", "status": "ok", "items": app}]
        self.assertEqual(
            emit.envelope(observed)["categories"]["applications"]["status"], "ok"
        )

    def test_vector_rejects_overlapping_directories(self):
        for spool, data in [
            ("/private/out", "/private/out"),
            ("/private/out", "/private/out/data"),
            ("/private/out/data", "/private/out"),
        ]:
            with self.subTest(spool=spool, data=data), self.assertRaises(ValueError):
                config.configuration(
                    spool, data, "https://receiver.example/v1/inventory"
                )

    def test_atomic_report_is_private_and_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = str(Path(tmp).resolve())
            result = emit.envelope(self.observation())
            output = emit.write_report(result, tmp)
            self.assertEqual(json.loads(output.read_text()), result)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(emit.outbox.entries(Path(tmp)), [output])
            with self.assertRaises(ValueError):
                emit.write_report(result, tmp)

    def test_outbox_never_evicts_unconfirmed_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = str(Path(tmp).resolve())
            for i in range(32):
                (Path(tmp) / str(i)).write_text("keep")
            with self.assertRaisesRegex(ValueError, "outbox full"):
                emit.write_report(emit.envelope(self.observation()), tmp)
            self.assertEqual(len(emit.outbox.entries(Path(tmp))), 32)

    def test_byte_limit_and_nonprivate_spool(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = str(Path(tmp).resolve())
            result = emit.envelope(self.observation())
            result["gaps"] = ["x" * emit.MAX_BYTES]
            with self.assertRaises(ValueError):
                emit.write_report(result, tmp)
            Path(tmp).chmod(0o755)
            with self.assertRaises(ValueError):
                emit.write_report(emit.envelope(self.observation()), tmp)

    def test_vector_config_requires_private_remote_transport(self):
        for endpoint in [
            "http://remote.example/v1/inventory",
            "https://user:pass@remote.example/v1/inventory",  # pragma: allowlist secret (synthetic test credentials)
            "file:///tmp/data",
        ]:
            with self.assertRaises(ValueError):
                config.configuration("/tmp/reports", "/tmp/data", endpoint)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = str(Path(tmp).resolve())
            root = Path(tmp).resolve()
            result = config.configuration(
                root / "reports",
                root / "data",
                "https://inventory.example/v1/inventory",
            )
            self.assertNotIn("${", json.dumps(result))
            sink = result["sinks"]["inventory_http"]
            self.assertEqual(sink["batch"]["max_events"], 1)
            self.assertEqual(sink["buffer"]["when_full"], "block")
            self.assertEqual(sink["auth"]["token"], "SECRET[inventory_writer.writer]")
            self.assertEqual(
                result["secret"]["inventory_writer"],
                {
                    "type": "directory",
                    "path": str(root / "data-secrets"),
                    "remove_trailing_whitespace": True,
                },
            )

    def test_vector_secret_sibling_follows_resolved_data_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = str(Path(tmp).resolve())
            root = Path(tmp).resolve()
            data = root / "data"
            data.mkdir()
            alias = root / "alias"
            alias.symlink_to(data, target_is_directory=True)
            result = config.configuration(
                root / "outbox", alias, "http://127.0.0.1/v1/inventory"
            )
            self.assertEqual(
                result["secret"]["inventory_writer"]["path"], str(root / "data-secrets")
            )

    def test_vector_checks_existing_secret_permissions_and_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = str(Path(tmp).resolve())
            root = Path(tmp)
            data = root / "data"
            secrets = config.secret_directory(data)
            secrets.mkdir(mode=0o700)
            writer = secrets / "writer"
            writer.write_text("synthetic")
            writer.chmod(0o600)
            endpoint = "http://127.0.0.1/v1/inventory"
            config.configuration(root / "outbox", data, endpoint)
            for path in (secrets, writer):
                private_mode = path.stat().st_mode & 0o777
                path.chmod(0o755 if path.is_dir() else 0o644)
                with self.assertRaisesRegex(ValueError, "owner-only"):
                    config.configuration(root / "outbox", data, endpoint)
                path.chmod(private_mode)
            with self.assertRaisesRegex(ValueError, "overlap"):
                config.configuration(secrets, data, endpoint)
            writer.unlink()
            writer.symlink_to(root / "missing")
            with self.assertRaisesRegex(ValueError, "symlinks"):
                config.configuration(root / "outbox", data, endpoint)

    def test_python310_syntax(self):
        import ast

        for name in ["emit.py", "vector_inventory_config.py"]:
            ast.parse(
                (FILES / name).read_text(encoding="utf-8"), feature_version=(3, 10)
            )


if __name__ == "__main__":
    unittest.main()
