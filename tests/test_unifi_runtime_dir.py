"""The UniFi unit recreates /run/unifi itself.

The vendor layout links ``/usr/lib/unifi/run`` to ``/run/unifi``, a tmpfs
directory that only the vendor's own unit (``RuntimeDirectory=unifi``) or init
script creates. Our replacement unit must do the same; otherwise the directory
is missing after every reboot and the deploy admission refuses the host
(``installation_layout_missing_use_ansible``).
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/unifi_deploy"


def service_settings() -> dict[str, list[str]]:
    unit = (ROLE / "templates/unifi.service.j2").read_text()
    section = unit.split("[Service]\n", 1)[1].split("\n[", 1)[0]
    settings: dict[str, list[str]] = {}
    for line in section.splitlines():
        key, sep, value = line.partition("=")
        if sep and not line.startswith(("#", " ")):
            settings.setdefault(key, []).append(value)
    return settings


class UnifiRuntimeDirTest(unittest.TestCase):
    def test_unit_creates_and_keeps_the_runtime_directory(self) -> None:
        settings = service_settings()
        self.assertEqual(settings["RuntimeDirectory"], ["unifi"])
        self.assertEqual(settings["RuntimeDirectoryMode"], ["0750"])
        # Kept after a stop until the next reboot, so admission still sees it.
        self.assertEqual(settings["RuntimeDirectoryPreserve"], ["yes"])

    def test_role_gives_the_run_dir_the_unit_mode(self) -> None:
        tasks = yaml.safe_load((ROLE / "tasks/directories.yml").read_text())
        run_dir = [
            task["ansible.builtin.file"]
            for task in tasks
            if task["ansible.builtin.file"].get("path") == "{{ unifi_run_dir }}"
        ]
        self.assertEqual(len(run_dir), 1)
        self.assertEqual(run_dir[0]["mode"], "0750")
        for task in tasks:
            self.assertNotIn("{{ unifi_run_dir }}", task.get("loop", []))


if __name__ == "__main__":
    unittest.main()
