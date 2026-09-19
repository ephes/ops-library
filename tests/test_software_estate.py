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


if __name__ == "__main__":
    unittest.main()
