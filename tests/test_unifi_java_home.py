"""UniFi runs the Java it was configured for, not the system default.

``/usr/bin/java`` follows the Debian alternatives link. Another service on the
same host (macmini: Minecraft 26.3 with OpenJDK 25) can move that link to a
Java outside UniFi's supported range (17-24 for UniFi 9.5); UniFi then exits
with status 255 on every start. The unit and the role's Java check therefore
use ``{{ unifi_java_home }}/bin/java``.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/unifi_deploy"
JAVA = "{{ unifi_java_home }}/bin/java"


class UnifiJavaHomeTest(unittest.TestCase):
    def test_unit_execs_the_configured_java(self) -> None:
        unit = (ROLE / "templates/unifi.service.j2").read_text()
        execs = {
            key: value
            for key, _, value in (
                line.partition("=") for line in unit.splitlines()
            )
            if key.startswith("Exec")
        }
        self.assertEqual(set(execs), {"ExecStart", "ExecStop"})
        for key, value in execs.items():
            self.assertTrue(value.startswith(JAVA + " "), f"{key}={value}")
        self.assertIn('Environment="JAVA_HOME={{ unifi_java_home }}"', unit)

    def test_java_check_runs_the_configured_binary(self) -> None:
        tasks = yaml.safe_load((ROLE / "tasks/java.yml").read_text())
        (verify,) = [task for task in tasks if "ansible.builtin.command" in task]
        self.assertEqual(
            verify["ansible.builtin.command"]["argv"], [JAVA, "-version"]
        )

    def test_default_java_home_matches_the_default_package(self) -> None:
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        self.assertEqual(defaults["unifi_java_package"], "openjdk-17-jre-headless")
        self.assertEqual(
            defaults["unifi_java_home"], "/usr/lib/jvm/java-17-openjdk-amd64"
        )

    def test_no_unifi_role_hardcodes_the_system_java(self) -> None:
        offenders = [
            str(path.relative_to(ROOT))
            for role in sorted(ROOT.glob("roles/unifi_*"))
            for path in sorted(role.rglob("*"))
            if path.is_file()
            and path.suffix != ".md"
            and "/usr/bin/java" in path.read_text(errors="ignore")
        ]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
