"""Contract between the existing privileged observation and unprivileged inventory."""

import copy
import grp
import importlib.util
import json
import math
import os
import stat
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


live = load("bridge_live", "roles/software_live/files/software_live.py")
collector = load("bridge_collect", "roles/software_estate/files/collect.py")


def source():
    check = {"status": "ok", "observed": True, "expected": True, "issues": []}
    return {
        "schema_version": 2,
        "host": "example",
        "generated_at_epoch": time.time(),
        "os": {**check, "cycle": "24.04"},
        "postgresql": {**check, "server_version": "17.7"},
        "traefik": {
            **check,
            "installed": {"version": "3.7.9"},
            "running": {"version": "3.7.8"},
            "upstream": {"version": "3.7.9"},
        },
        "apt": {"status": "ok", "indexes_fresh": True, "pending_security_count": 2},
    }


def root_stat(value):
    fields = list(value)
    fields[4] = 0
    return os.stat_result(fields)


class HealthBridgeTests(unittest.TestCase):
    def read_fixture(self, data):
        # Ownership is emulated; file descriptors, permissions, JSON and bounds are real.
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            folder.chmod(0o750)
            target = folder / "software-health.json"
            target.write_text(json.dumps(data))
            target.chmod(0o640)
            lstat, fstat = Path.lstat, os.fstat
            with (
                patch.object(collector, "HEALTH_EXPORT", target),
                patch.object(Path, "lstat", lambda p: root_stat(lstat(p))),
                patch.object(os, "fstat", lambda fd: root_stat(fstat(fd))),
            ):
                return collector.software_health("example")

    def test_allowlisted_projection_roundtrip_preserves_time_and_unknowns(self):
        original = source()
        original["private_config"] = {
            "opaque_fixture": "synthetic-never-export",
        }
        original["traefik"]["binary_path"] = "/private/path"
        original["traefik"]["upstream"]["request_headers"] = "synthetic-never-export"
        before = copy.deepcopy(original)
        projected = live.inventory_projection(original)
        self.assertEqual(self.read_fixture(projected), projected)
        self.assertEqual(projected["observed_at_epoch"], original["generated_at_epoch"])
        self.assertEqual(projected["apt"]["pending_security_count"], 2)
        self.assertEqual(projected["max_age_seconds"], 1800)
        self.assertEqual(projected["source"], "software-live/2")
        self.assertIsNone(projected["checks"]["postgresql"]["installed_version"])
        self.assertEqual(projected["checks"]["postgresql"]["running_version"], "17.7")
        self.assertNotIn("synthetic-never-export", json.dumps(projected))
        self.assertNotIn("/private/path", json.dumps(projected))
        self.assertEqual(original, before)
        original["apt"] = {
            "status": "unknown",
            "indexes_fresh": False,
            "pending_security_count": None,
        }
        original["postgresql"].update(expected=False, observed=True)
        projected = live.inventory_projection(original)
        self.assertEqual(self.read_fixture(projected), projected)
        self.assertIsNone(projected["apt"]["pending_security_count"])
        self.assertFalse(projected["checks"]["postgresql"]["expected"])

    def test_projection_rejects_invalid_source_not_manufacture_success(self):
        for key, value in [
            ("generated_at_epoch", math.nan),
            ("generated_at_epoch", True),
            ("host", ""),
            ("schema_version", 99),
            ("schema_version", 2.0),
        ]:
            with self.subTest(key=key, value=value):
                raw = source()
                raw[key] = value
                with self.assertRaises(ValueError):
                    live.inventory_projection(raw)
        raw = source()
        raw["apt"]["pending_security_count"] = True
        with self.assertRaises(ValueError):
            live.inventory_projection(raw)
        raw = source()
        raw["os"]["observed"] = "yes"
        with self.assertRaises(ValueError):
            live.inventory_projection(raw)

    def test_reader_rejects_stale_future_cross_host_and_extra_fields(self):
        changes = [
            ("observed_at_epoch", time.time() - 1801),
            ("observed_at_epoch", time.time() + 60),
            ("observed_at_epoch", math.nan),
            ("observed_at_epoch", True),
            ("max_age_seconds", 86400),
            ("host", "another-host"),
            ("private_config", "never-forward"),
            ("schema_version", True),
        ]
        for key, value in changes:
            with self.subTest(key=key):
                data = live.inventory_projection(source())
                data[key] = value
                with self.assertRaises(ValueError):
                    self.read_fixture(data)
        data = live.inventory_projection(source())
        data["apt"]["pending_security_count"] = True
        with self.assertRaises(ValueError):
            self.read_fixture(data)
        data = live.inventory_projection(source())
        data["checks"]["os"]["issues"] = ["x"] * 21
        with self.assertRaises(ValueError):
            self.read_fixture(data)

    def test_reader_refuses_nonroot_writable_or_linked_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            folder.chmod(0o750)
            target = folder / "software-health.json"
            target.write_text(json.dumps(live.inventory_projection(source())))
            target.chmod(0o640)
            lstat, fstat = Path.lstat, os.fstat
            with patch.object(collector, "HEALTH_EXPORT", target):
                with patch.object(
                    Path,
                    "lstat",
                    return_value=os.stat_result(
                        (stat.S_IFDIR | 0o777, 1, 1, 1, 0, 0, 0, 0, 0, 0)
                    ),
                ):
                    with self.assertRaises(ValueError):
                        collector.software_health("example")
                with patch.object(Path, "lstat", lambda p: root_stat(lstat(p))):
                    with patch.object(
                        os,
                        "fstat",
                        return_value=os.stat_result(
                            (stat.S_IFREG | 0o640, 1, 1, 1, 99, 0, 0, 0, 0, 0)
                        ),
                    ):
                        with self.assertRaises(ValueError):
                            collector.software_health("example")
                    with patch.object(os, "fstat", lambda fd: root_stat(fstat(fd))):
                        target.chmod(0o660)
                        with self.assertRaises(ValueError):
                            collector.software_health("example")
                        target.chmod(0o640)
                        linked = folder / "alias"
                        os.link(target, linked)
                        with self.assertRaises(ValueError):
                            collector.software_health("example")
                        linked.unlink()
                        target.unlink()
                        target.symlink_to("missing")
                        with self.assertRaises(OSError):
                            collector.software_health("example")

    def test_unavailable_health_is_explicit_partial_failure_and_opt_in(self):
        with patch.object(
            collector, "software_health", side_effect=ValueError("stale")
        ) as reader:
            app = collector.application(
                {"id": "health", "software_health": True}, [], host="example"
            )
            reader.assert_called_once_with("example")
            self.assertEqual(app["software_health"]["status"], "error")
            self.assertIn("software_health:unavailable", app["coverage"])
            reader.reset_mock()
            collector.application({"id": "health"}, [])
            reader.assert_not_called()
        with self.assertRaises(ValueError):
            collector.application({"id": "health", "software_health": "true"}, [])

    def test_export_atomic_permissions_and_failure_preserves_prior_file(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            folder.chmod(0o750)
            raw = folder / "state.json"
            raw.write_text(json.dumps(source()))
            raw.chmod(0o640)
            target = folder / "software-health.json"
            target.write_text("prior")
            target.chmod(0o600)
            original_inode = target.stat().st_ino
            lstat, fstat = Path.lstat, os.fstat
            group = grp.getgrgid(os.getgid()).gr_name
            with (
                patch.object(Path, "lstat", lambda p: root_stat(lstat(p))),
                patch.object(os, "fstat", lambda fd: root_stat(fstat(fd))),
            ):
                with patch.object(os, "fchown", wraps=os.fchown) as chown:
                    live.export_inventory(raw, target, group)
                    self.assertEqual(chown.call_args.args[1:], (-1, os.getgid()))
                result = json.loads(target.read_text())
                self.assertEqual(result["host"], "example")
                st = target.stat()
                self.assertEqual(stat.S_IMODE(st.st_mode), 0o640)
                self.assertEqual(st.st_uid, os.getuid())  # root in the production unit
                self.assertEqual(st.st_gid, os.getgid())
                self.assertNotEqual(st.st_ino, original_inode)
                prior = target.read_bytes()
                with patch.object(grp, "getgrnam", side_effect=KeyError("missing")):
                    with self.assertRaises(KeyError):
                        live.export_inventory(raw, target, group)
                self.assertEqual(target.read_bytes(), prior)
                for content, mode in [
                    (json.dumps(source()), 0o660),
                    ("x" * (1024 * 1024 + 1), 0o640),
                ]:
                    raw.write_text(content)
                    raw.chmod(mode)
                    with self.assertRaisesRegex(
                        ValueError,
                        "unsafe source file" if mode == 0o660 else "source too large",
                    ):
                        live.export_inventory(raw, target, group)
                    self.assertEqual(target.read_bytes(), prior)
                raw.chmod(0o640)
                folder.chmod(0o770)
                with self.assertRaises(ValueError):
                    live.export_inventory(raw, target, group)
                folder.chmod(0o750)
                raw.unlink()
                raw.symlink_to("missing")
                with self.assertRaises(OSError):
                    live.export_inventory(raw, target, group)
                self.assertEqual(target.read_bytes(), prior)
                self.assertEqual(
                    {p.name for p in folder.iterdir()},
                    {"state.json", "software-health.json"},
                )

    def test_export_mode_never_collects_or_connects(self):
        with (
            patch.object(
                live.sys,
                "argv",
                [
                    "software_live.py",
                    "export-inventory",
                    "--config",
                    "/state.json",
                    "--output",
                    "/output.json",
                    "--group",
                    "reader",
                ],
            ),
            patch.object(live, "export_inventory") as export,
            patch.object(live, "collect") as collect,
        ):
            live.main()
            export.assert_called_once_with(
                Path("/state.json"), Path("/output.json"), "reader"
            )
            collect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
