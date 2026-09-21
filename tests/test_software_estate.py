"""Software collector reads metadata without importing application code."""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "estate_collect",
    Path(__file__).resolve().parents[1] / "roles/software_estate/files/collect.py",
)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


class CollectorTests(unittest.TestCase):
    def test_missing_venv_is_not_empty_success(self):
        with self.assertRaises(FileNotFoundError):
            collector.python_packages("/does-not-exist/estate")

    def test_metadata_with_environment_markers_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "lib/python3.14/site-packages/example-1.dist-info/METADATA"
            p.parent.mkdir(parents=True)
            p.write_text(
                'Name: example\nVersion: 1.0\nRequires-Dist: dep; extra == "test"\n'
            )
            found = collector.python_packages(tmp)
        self.assertEqual(found[0]["requires"], ['dep; extra == "test"'])
        self.assertIsNone(found[0]["license"])

    def test_dependency_package_is_not_application_version(self):
        with patch.object(collector, "command", return_value=""):
            result = collector.application(
                {"id": "example", "packages": ["ffmpeg"]},
                [{"name": "ffmpeg", "version": "7"}],
            )
        self.assertNotIn("installed_version", result)

    def test_secret_errors_are_not_returned(self):
        def bad():
            raise RuntimeError("password=very-secret")

        self.assertEqual(
            collector.category(bad),
            {"status": "error", "error": "RuntimeError", "items": []},
        )

    def test_command_failure_not_empty_success(self):
        with self.assertRaises(RuntimeError):
            collector.command(["/usr/bin/false"])

    def test_path_injection_rejected(self):
        with self.assertRaises(ValueError):
            collector.application({"id": "x", "unit": "x; cat /etc/passwd.service"}, [])


class WebArtifactTests(unittest.TestCase):
    def test_public_artifacts_supply_installed_not_running_versions(self):
        fixtures = {
            "snappymail/index.php": "<?php\ndefine('APP_VERSION', '2.38.2');\n",
            "snappymail/snappymail/v/2.38.2/include.php": "<?php // public entry",
            "postfixadmin/.installed_version": "4.0.5\n",
            "postfixadmin/public/index.php": "<?php // public entry",
        }
        for kind, version in (("snappymail", "2.38.2"), ("postfixadmin", "4.0.5")):
            with (
                self.subTest(kind=kind),
                patch.object(
                    collector, "artifact_metadata", side_effect=fixtures.__getitem__
                ) as read,
                patch.object(collector.platform, "system", return_value="Linux"),
                patch.object(
                    collector, "command", side_effect=AssertionError("no commands")
                ),
            ):
                value = collector.application({"id": kind, "version_probe": kind}, [])
                self.assertEqual(value["installed_version"], version)
                self.assertEqual(value["presence"], "installed")
                self.assertIsNone(value["running_version"])
                self.assertEqual(value["coverage"], [])
                self.assertEqual(value["version_source"]["kind"], "artifact-metadata")
                self.assertEqual(read.call_count, 2)

    def test_invalid_or_missing_artifact_preserves_coverage_failure(self):
        for content in (
            "",
            "<?php define('APP_VERSION', 'secret');",
            "4.0.5\nother",
            "../4.0.5",
        ):
            with (
                self.subTest(content=content),
                patch.object(collector, "artifact_metadata", return_value=content),
                patch.object(collector.platform, "system", return_value="Linux"),
            ):
                value = collector.application(
                    {"id": "p", "version_probe": "postfixadmin"}, []
                )
                self.assertNotIn("installed_version", value)
                self.assertNotIn("presence", value)
                self.assertIn("installed_version:unknown", value["coverage"])
                self.assertEqual(value["version_probe_error"], "ValueError")
        with (
            patch.object(
                collector,
                "artifact_metadata",
                side_effect=PermissionError("private detail"),
            ),
            patch.object(collector.platform, "system", return_value="Linux"),
        ):
            value = collector.application(
                {"id": "s", "version_probe": "snappymail"}, []
            )
            self.assertEqual(value["version_probe_error"], "PermissionError")
            self.assertNotIn("private detail", str(value))

    def test_ambiguous_snappymail_and_missing_selected_entry_are_rejected(self):
        statement = "define('APP_VERSION', '2.38.2');\n"
        for replies in (
            [statement * 2],
            [statement + 'define("APP_VERSION", "9.9.9");\n'],
            [statement + "DEFINE('APP_VERSION', '9.9.9');\n"],
            [statement + "const APP_VERSION = '9.9.9';\n"],
            [statement, ""],
            [statement, FileNotFoundError()],
        ):
            with (
                self.subTest(replies=replies),
                patch.object(collector, "artifact_metadata", side_effect=replies),
                patch.object(collector.platform, "system", return_value="Linux"),
            ):
                value = collector.application(
                    {"id": "s", "version_probe": "snappymail"}, []
                )
                self.assertNotIn("installed_version", value)
                self.assertIn("installed_version:unknown", value["coverage"])

    def test_reader_rejects_symlinks_special_files_writable_and_oversize(self):
        import os
        from types import SimpleNamespace

        original_fstat = os.fstat

        def root_owned(fd):
            actual = original_fstat(fd)
            return SimpleNamespace(
                st_uid=0, st_mode=actual.st_mode, st_size=actual.st_size
            )

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(collector, "ARTIFACT_ROOT", tmp),
            patch.object(collector, "artifact_stat", side_effect=root_owned),
        ):
            root = Path(tmp)
            (root / "app").mkdir()
            target = root / "app/version"
            target.write_text("1.2.3")
            self.assertEqual(collector.artifact_metadata("app/version"), "1.2.3")
            (root / "alias").symlink_to(root / "app", target_is_directory=True)
            (root / "app/link").symlink_to(target)
            os.mkfifo(root / "app/fifo")
            for bad in (
                "alias/version",
                "app/link",
                "app/fifo",
                "../escape",
                "/etc/passwd",
            ):
                with self.subTest(bad=bad), self.assertRaises((ValueError, OSError)):
                    collector.artifact_metadata(bad)
            target.chmod(0o666)
            with self.assertRaises(ValueError):
                collector.artifact_metadata("app/version")
            target.chmod(0o644)
            target.write_text("x" * 16385)
            with self.assertRaises(ValueError):
                collector.artifact_metadata("app/version")
            target.write_text("ok")
            (root / "app").chmod(0o777)
            with self.assertRaises(ValueError):
                collector.artifact_metadata("app/version")
            (root / "app").chmod(0o755)

            def wrong_owner(fd):
                actual = root_owned(fd)
                if collector.stat.S_ISREG(actual.st_mode):
                    actual.st_uid = 123
                return actual

            with patch.object(collector, "artifact_stat", side_effect=wrong_owner):
                with self.assertRaisesRegex(ValueError, "untrusted artifact file"):
                    collector.artifact_metadata("app/version")
            with patch.object(
                collector,
                "artifact_stat",
                return_value=SimpleNamespace(st_uid=123, st_mode=0o40755),
            ):
                with self.assertRaisesRegex(ValueError, "untrusted artifact directory"):
                    collector.artifact_metadata("app/version")
            target.write_text("1.2.3")
            original_read = os.read
            with patch.object(
                collector,
                "artifact_read",
                side_effect=lambda fd, n: original_read(fd, min(n, 2)),
            ):
                self.assertEqual(collector.artifact_metadata("app/version"), "1.2.3")

    def test_non_linux_web_probe_does_not_read_files(self):
        with (
            patch.object(collector.platform, "system", return_value="Darwin"),
            patch.object(
                collector,
                "artifact_metadata",
                side_effect=AssertionError("no metadata access"),
            ),
        ):
            for kind in ("snappymail", "postfixadmin"):
                value = collector.application({"id": kind, "version_probe": kind}, [])
                self.assertEqual(value["coverage"], ["installed_version:unknown"])
                self.assertEqual(value["version_probe_error"], "ValueError")

    def test_navidrome_failure_keeps_existing_shape(self):
        with patch.object(collector, "media_version", side_effect=ValueError()):
            value = collector.application({"id": "n", "version_probe": "navidrome"}, [])
            self.assertEqual(value["coverage"], ["installed_version:unknown"])
            self.assertNotIn("version_probe_error", value)


class SbomModuleMixin:
    def setUp(self):
        import json

        self.json = json
        path = (
            Path(__file__).resolve().parents[1] / "roles/software_estate/files/sbom.py"
        )
        module_spec = importlib.util.spec_from_file_location("estate_sbom", path)
        self.scanner = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(self.scanner)


class SbomTests(SbomModuleMixin, unittest.TestCase):
    def test_container_scan_uses_immutable_local_image(self):
        image = "sha256:" + "a" * 64
        document = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "metadata": {"component": {"bom-ref": "root"}},
        }
        responses = [
            self.json.dumps({"version": "1.52.0"}).encode(),
            image.encode(),
            self.json.dumps(document).encode(),
            image.encode(),
        ]
        with patch.object(self.scanner, "run", side_effect=responses) as invoke:
            result = self.scanner.scan(
                {
                    "host": "test",
                    "service": "example",
                    "kind": "container",
                    "container": "example-1",
                }
            )
        self.assertIn("docker:" + image, invoke.call_args_list[2].args[0])
        self.assertEqual(
            result["document"]["compositions"][0]["aggregate"], "incomplete"
        )
        self.assertEqual(result["identity"]["value"], image)

    def test_replaced_image_rejected(self):
        image = "sha256:" + "a" * 64
        document = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "metadata": {"component": {"bom-ref": "root"}},
        }
        responses = [
            b'{"version":"1.52.0"}',
            image.encode(),
            self.json.dumps(document).encode(),
            ("sha256:" + "b" * 64).encode(),
        ]
        with (
            patch.object(self.scanner, "run", side_effect=responses),
            self.assertRaises(ValueError),
        ):
            self.scanner.scan(
                {
                    "host": "test",
                    "service": "example",
                    "kind": "container",
                    "container": "example-1",
                }
            )

    def test_missing_metadata_cannot_claim_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            self.scanner.fingerprint(tmp)


class ReviewRegressionTests(unittest.TestCase):
    def test_missing_docker_is_not_empty_success(self):
        with patch.object(collector.shutil, "which", return_value=None):
            result = collector.category(collector.containers)
        self.assertEqual(result["status"], "unsupported")

    def test_bad_plist_is_a_category_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Bad.app/Contents/Info.plist"
            path.parent.mkdir(parents=True)
            path.write_text('<?xml version="1.0"?><plist><broken>')
            result = collector.category(lambda: collector.mac_apps([tmp]))
        self.assertEqual(result["status"], "error")

    def test_direct_dependency_urls_are_not_exposed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = (
                Path(tmp) / "lib/python3.14/site-packages/example-1.dist-info/METADATA"
            )
            path.parent.mkdir(parents=True)
            path.write_text(
                "Name: example\nVersion: 1\nRequires-Dist: dep @ https://user:password@example.invalid/private\n"  # pragma: allowlist secret (synthetic test credentials)
            )
            result = collector.python_packages(tmp)[0]
        self.assertEqual(result["requires"], [])
        self.assertEqual(result["omitted_direct_references"], 1)


class SbomSchemaTests(SbomModuleMixin, unittest.TestCase):
    def test_broad_root_spellings_rejected_before_metadata_scan(self):
        for root in ["/opt/", "//opt", "/opt/.", "/", "relative/path"]:
            with (
                self.subTest(root=root),
                patch.object(self.scanner, "run", return_value=b'{"version":"1.52.0"}'),
                patch.object(self.scanner, "fingerprint") as fingerprint,
                self.assertRaises(ValueError),
            ):
                self.scanner.scan(
                    {
                        "host": "test",
                        "service": "example",
                        "kind": "python-venv",
                        "path": root,
                    }
                )
            fingerprint.assert_not_called()

    def test_wrong_scanner_version_rejected(self):
        with (
            patch.object(self.scanner, "run", return_value=b'{"version":"0.0.1"}'),
            self.assertRaises(ValueError),
        ):
            self.scanner.scan(
                {
                    "host": "test",
                    "service": "example",
                    "kind": "container",
                    "container": "example-1",
                }
            )

    def test_composition_document_validates_offline(self):
        import jsonschema
        from referencing import Registry, Resource

        schemas = (
            Path(__file__).resolve().parents[1] / "roles/software_estate/files/schemas"
        )
        registry = Registry().with_resources(
            (data["$id"], Resource.from_contents(data))
            for p in schemas.glob("*.json")
            for data in [self.json.loads(p.read_text())]
        )
        schema = self.json.loads((schemas / "bom-1.6.schema.json").read_text())
        document = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "version": 1,
            "metadata": {
                "component": {
                    "type": "application",
                    "name": "example",
                    "bom-ref": "root",
                }
            },
            "compositions": [{"aggregate": "incomplete", "assemblies": ["root"]}],
        }
        jsonschema.Draft7Validator(schema, registry=registry).validate(document)
        document["compositions"][0]["aggregate"] = "false-completeness"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft7Validator(schema, registry=registry).validate(document)


class CommandTimeoutTests(SbomModuleMixin, unittest.TestCase):
    def test_scanner_timeout_is_reaped(self):
        import subprocess
        import sys

        with self.assertRaises(subprocess.TimeoutExpired):
            self.scanner.run(
                [sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.02
            )

    def test_collector_timeout_is_reaped(self):
        import subprocess
        import sys

        with self.assertRaises(subprocess.TimeoutExpired):
            collector.command(
                [sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.02
            )


class SecondReviewTests(SbomModuleMixin, unittest.TestCase):
    def test_remote_scripts_parse_on_python_310(self):
        import ast

        for module in (collector, self.scanner):
            with self.subTest(module=module.__file__):
                ast.parse(Path(module.__file__).read_text(), feature_version=(3, 10))

    def test_missing_os_release_keeps_other_categories(self):
        def missing_release(path, *args, **kwargs):
            self.assertEqual(path, Path("/etc/os-release"))
            raise FileNotFoundError(path)

        with (
            patch.object(collector.platform, "system", return_value="Linux"),
            patch.object(collector, "packages", return_value=[]),
            patch.object(collector, "units", return_value=[]),
            patch.object(collector, "containers", return_value=[]),
            patch.object(
                collector.Path, "read_text", autospec=True, side_effect=missing_release
            ),
        ):
            result = collector.collect({"host": "test"})
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["categories"]["packages"]["status"], "ok")
        self.assertIsNone(result["os_version"])
        self.assertIn("os_release:unreadable_or_missing", result["gaps"])

    def test_invalid_policy_shapes_return_json_error(self):
        import json
        import subprocess
        import sys

        script = Path(collector.__file__)
        for data in [
            [],
            1,
            {"host": "test", "applications": "bad"},
            {"host": "test", "applications": ["bad"]},
            {"host": "test", "applications": [{"id": ""}]},
            {"host": "test", "applications": [{"id": "same"}, {"id": "same"}]},
        ]:
            with self.subTest(data=data):
                result = subprocess.run(
                    [sys.executable, str(script), "--policy-json", json.dumps(data)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 1)
                self.assertIn("error", json.loads(result.stdout))
                self.assertNotIn("Traceback", result.stderr)

    def test_venv_scan_records_normalized_source_and_selection(self):
        document = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "metadata": {"component": {"bom-ref": "root"}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "pyvenv.cfg").write_text("home = /example\n")
            with (
                patch.object(
                    self.scanner,
                    "run",
                    side_effect=[
                        b'{"version":"1.52.0"}',
                        self.json.dumps(document).encode(),
                    ],
                ) as run,
                patch.object(
                    self.scanner, "fingerprint", return_value="fingerprint"
                ) as fingerprint,
            ):
                result = self.scanner.scan(
                    {
                        "host": "test",
                        "service": "example",
                        "kind": "python-venv",
                        "path": tmp + "/.",
                    }
                )
            argv = run.call_args_list[1].args[0]
            self.assertIn("dir:" + str(Path(tmp).resolve()), argv)
            selection_index = argv.index("--override-default-catalogers")
            self.assertEqual(
                argv[selection_index + 1], "python-installed-package-cataloger"
            )
            self.assertEqual(result["source"], "dir:" + str(Path(tmp).resolve()))
            self.assertIn(
                "python-installed-package-cataloger", result["cataloger_selection"]
            )
            self.assertEqual(
                [c.args[0] for c in fingerprint.call_args_list],
                [str(Path(tmp).resolve())] * 2,
            )

    def test_vendored_schema_checksums_match_provenance(self):
        import hashlib
        import re

        root = (
            Path(__file__).resolve().parents[1] / "roles/software_estate/files/schemas"
        )
        readme = (root / "README.md").read_text()
        paths = list(root.glob("*.json"))
        self.assertTrue(paths)
        expected = set(re.findall(r"- `([^`]+\.json)`: `", readme))
        self.assertEqual({path.name for path in paths}, expected)
        for path in paths:
            self.assertIn(
                f"`{path.name}`: `{hashlib.sha256(path.read_bytes()).hexdigest()}`",
                readme,
            )


class RelatedUnitTests(unittest.TestCase):
    def test_binding_reuses_unit_inventory_without_commands(self):
        observation = {
            "status": "ok",
            "items": [
                {"name": "worker.service", "state": "failed"},
                {"name": "idle.service", "state": "not-loaded"},
                {"name": "unrelated.service", "state": "active"},
            ],
        }
        with patch.object(
            collector, "command", side_effect=AssertionError("extra probe")
        ):
            result = collector.application(
                {
                    "id": "app",
                    "related_units": [
                        "worker.service",
                        "idle.service",
                        "missing.service",
                    ],
                },
                [],
                unit_observation=observation,
            )
        self.assertEqual(
            result["related_units"]["items"],
            [
                {"name": "worker.service", "state": "failed"},
                {"name": "idle.service", "state": "not-loaded"},
                {"name": "missing.service", "state": "not-observed"},
            ],
        )
        self.assertEqual(
            result["coverage"], ["related_units:missing.service:not_observed"]
        )
        self.assertNotIn("installed_version", result)
        self.assertNotIn("runtime", result)

    def test_unavailable_inventory_cannot_reuse_supplied_states(self):
        for status in ["error", "unsupported"]:
            result = collector.application(
                {"id": "app", "related_units": ["worker.service"]},
                [],
                unit_observation={
                    "status": status,
                    "error": "sensitive detail",
                    "items": [{"name": "worker.service", "state": "active"}],
                },
            )
            self.assertEqual(result["related_units"]["status"], status)
            self.assertEqual(result["related_units"]["items"][0]["state"], "unknown")
            self.assertEqual(
                result["coverage"], ["related_units:host_probe_unavailable"]
            )
            self.assertNotIn("sensitive detail", str(result))

    def test_invalid_bindings_fail_before_collection(self):
        invalid = [
            None,
            "worker.service",
            [None],
            [{}],
            ["worker.service"] * 2,
            ["app.service"],
            ["bad;name.service"],
            ["a" * 201 + ".service"],
            [f"worker-{i}.service" for i in range(33)],
        ]
        for names in invalid:
            with (
                self.subTest(names=names),
                patch.object(collector, "packages") as packages,
            ):
                with self.assertRaises(ValueError):
                    collector.collect(
                        {
                            "host": "test",
                            "applications": [
                                {
                                    "id": "app",
                                    "unit": "app.service",
                                    "related_units": names,
                                }
                            ],
                        }
                    )
                packages.assert_not_called()

    def test_maximum_bindings_and_old_policy_are_supported(self):
        longest = "a" * (200 - len(".service")) + ".service"
        names = [longest] + [f"worker-{i}.service" for i in range(31)]
        result = collector.application(
            {"id": "app", "related_units": names},
            [],
            unit_observation={
                "status": "ok",
                "items": [{"name": name, "state": "inactive"} for name in names],
            },
        )
        self.assertEqual(len(result["related_units"]["items"]), 32)
        self.assertEqual(result["related_units"]["items"][0]["name"], longest)
        self.assertEqual(result["coverage"], [])
        for spec in [{"id": "app"}, {"id": "app", "related_units": []}]:
            with self.subTest(spec=spec):
                result = collector.application(
                    spec, [], unit_observation={"status": "error", "items": []}
                )
                self.assertNotIn("related_units", result)
                self.assertEqual(result["coverage"], [])


if __name__ == "__main__":
    unittest.main()
