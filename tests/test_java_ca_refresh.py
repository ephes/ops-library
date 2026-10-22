"""Regression contracts for the incident recovery sequence."""
import unittest
from pathlib import Path
import yaml

TASKS = yaml.safe_load((Path(__file__).resolve().parents[1] / "roles/java_ca_refresh/tasks/main.yml").read_text())

class JavaRefreshTests(unittest.TestCase):
    def task(self, name):
        return next(t for t in TASKS if t["name"] == name)

    def test_interrupted_refresh_still_restarts_on_resume(self):
        restart = self.task("Restart explicitly selected JVM services after trust refresh")
        # After a successful refresh the alias predicate is false; pending state
        # must independently permit restarting JVMs with their old SSL contexts.
        self.assertIn("or java_ca_refresh_pending.stat.exists", restart["when"])
        names = [t["name"] for t in TASKS]
        self.assertLess(names.index("Persist pending restart before changing trust"), names.index("Refresh Java trust through the supported distribution hook"))
        self.assertEqual(names[-1], "Clear pending marker only after successful verification and readiness")

    def test_refresh_is_guarded_by_patched_os_and_stale_java(self):
        names = [t["name"] for t in TASKS]
        self.assertLess(names.index("Refuse refresh while affected roots remain enabled in OS trust"), names.index("Refresh Java trust through the supported distribution hook"))
        self.assertEqual(self.task("Refresh Java trust through the supported distribution hook")["when"], "java_ca_refresh_needed")
        verify = self.task("Require both affected roots absent")["ansible.builtin.assert"]["that"]
        self.assertEqual(len(verify), 2)

    def test_explicit_java_fresh_trigger_after_os_refresh_before_verification(self):
        names = [t["name"] for t in TASKS]
        schedule = self.task("Schedule the distribution Java fresh rebuild trigger")
        process = self.task("Process only the distribution Java certificate triggers")
        self.assertEqual(schedule["ansible.builtin.command"]["argv"], ["dpkg-trigger", "--no-await", "update-ca-certificates-java-fresh"])
        self.assertEqual(process["ansible.builtin.command"]["argv"], ["dpkg", "--triggers-only", "ca-certificates-java"])
        self.assertEqual(schedule["when"], "java_ca_refresh_needed")
        self.assertEqual(process["when"], "java_ca_refresh_needed")
        self.assertLess(names.index("Refresh Java trust through the supported distribution hook"), names.index(schedule["name"]))
        self.assertLess(names.index(schedule["name"]), names.index(process["name"]))
        self.assertLess(names.index(process["name"]), names.index("Verify refreshed Java trust"))

    def test_backup_and_custom_identity_gate_precede_refresh_and_restart(self):
        names = [t["name"] for t in TASKS]
        self.assertLess(names.index("Preserve a checksum-addressed pre-refresh Java trust backup"), names.index("Refresh Java trust through the supported distribution hook"))
        self.assertLess(names.index("Require every non-distribution certificate identity preserved"), names.index("Restart explicitly selected JVM services after trust refresh"))
        self.assertFalse(self.task("Preserve a checksum-addressed pre-refresh Java trust backup")["ansible.builtin.copy"]["force"])
        self.assertIn("not ansible_check_mode", self.task("Preserve a checksum-addressed pre-refresh Java trust backup")["when"])
        import re
        pattern = self.task("Require every non-distribution certificate identity preserved")["vars"]["java_ca_refresh_custom_pattern"]
        listing = "Alias name: debian:root.pem\nEntry type: trustedCertEntry\n-----BEGIN CERTIFICATE-----\nDISTRO\n-----END CERTIFICATE-----\nAlias name: local-root\nEntry type: trustedCertEntry\n-----BEGIN CERTIFICATE-----\nCUSTOM\n-----END CERTIFICATE-----\n"
        self.assertEqual(re.findall(pattern, listing), [("local-root", "CUSTOM\n")])
        self.assertNotEqual(re.findall(pattern, listing), re.findall(pattern, listing.replace("CUSTOM", "CHANGED")))

    def test_retry_uses_saved_identity_baseline_before_restart(self):
        names = [t["name"] for t in TASKS]
        anchor = self.task("Anchor pre-refresh identities before recording pending mutation")
        self.assertIn("not java_ca_refresh_pending.stat.exists or not java_ca_refresh_baseline_file.stat.exists", anchor["when"])
        self.assertLess(names.index(anchor["name"]), names.index("Persist pending restart before changing trust"))
        self.assertLess(names.index("Read the persistent identity baseline on initial and resumed recovery"), names.index("Require every non-distribution certificate identity preserved"))
        gate = self.task("Require every non-distribution certificate identity preserved")
        self.assertIn("java_ca_refresh_saved_baseline.content", gate["vars"]["java_ca_refresh_expected_rfc"])
        self.assertIn("java_ca_refresh_pending.stat.exists", gate["vars"]["java_ca_refresh_expected_rfc"])
        self.assertIn("| sort", gate["ansible.builtin.assert"]["that"][0])
        self.assertIn("java_ca_refresh_baseline_file.stat.exists", self.task("Refuse unanchored recovery after stale aliases have disappeared")["ansible.builtin.assert"]["that"][0])
