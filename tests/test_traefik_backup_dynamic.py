"""traefik_backup must capture the file-provider route configs.

The role used to archive only ``acme.json`` (off by default) and its own
metadata, so a Traefik backup on macmini held no route config at all. The
dynamic directory (``/etc/traefik/dynamic``, one file per service) is now
copied into the backup directory and archived as ``<run>/dynamic/<file>``.
These tests run the role with ansible-playbook on localhost against a
temporary dynamic directory.
"""

from __future__ import annotations

import grp
import os
import pwd
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "traefik_backup"


class TraefikBackupDefaultsTest(unittest.TestCase):
    def test_dynamic_dir_is_backed_up_by_default(self) -> None:
        defaults = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
        self.assertIs(defaults["traefik_backup_include_dynamic"], True)
        self.assertEqual(defaults["traefik_backup_dynamic_dir"], "/etc/traefik/dynamic")


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not on PATH")
class TraefikBackupDynamicEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.dynamic = self.base / "etc" / "traefik" / "dynamic"
        self.dynamic.mkdir(parents=True)
        (self.dynamic / "homelab.yml").write_text("http: {}\n")
        (self.dynamic / "certificates.yml").write_text("tls: {}\n")
        os.chmod(self.dynamic / "homelab.yml", 0o644)
        self.root = self.base / "backups" / "traefik"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_role(self, **overrides: object) -> subprocess.CompletedProcess[str]:
        variables = {
            "traefik_backup_root": str(self.root),
            "traefik_backup_dynamic_dir": str(self.dynamic),
            "traefik_backup_owner": pwd.getpwuid(os.getuid()).pw_name,
            "traefik_backup_group": grp.getgrgid(os.getgid()).gr_name,
            "traefik_backup_fetch_local": False,
            "traefik_backup_prefix": "test",
            **overrides,
        }
        playbook = self.base / "play.yml"
        playbook.write_text(
            yaml.safe_dump(
                [
                    {
                        "hosts": "localhost",
                        "gather_facts": True,
                        "gather_subset": ["!all", "date_time"],
                        "vars": variables,
                        "roles": ["traefik_backup"],
                    }
                ]
            ),
            encoding="utf-8",
        )
        env = {
            **os.environ,
            "ANSIBLE_ROLES_PATH": str(ROOT / "roles"),
            "ANSIBLE_NOCOLOR": "1",
            "ANSIBLE_LOCALHOST_WARNING": "0",
            "ANSIBLE_INVENTORY_UNPARSED_WARNING": "0",
        }
        return subprocess.run(
            ["ansible-playbook", "-i", "localhost,", "-c", "local", str(playbook)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
        )

    def archive_members(self) -> list[str]:
        archives = sorted(self.root.glob("test-*.tar.gz"))
        self.assertEqual(len(archives), 1, archives)
        with tarfile.open(archives[0]) as archive:
            return archive.getnames()

    def test_archive_holds_the_dynamic_files(self) -> None:
        result = self.run_role()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        members = self.archive_members()
        run = members[0].split("/")[0]
        self.assertTrue(run.startswith("test-"), members)
        self.assertIn(f"{run}/dynamic/homelab.yml", members)
        self.assertIn(f"{run}/dynamic/certificates.yml", members)
        self.assertIn(f"{run}/metadata.yml", members)
        copied = self.root / run / "dynamic" / "homelab.yml"
        self.assertEqual(copied.read_text(), "http: {}\n")
        self.assertEqual(copied.stat().st_mode & 0o777, 0o644)
        metadata = yaml.safe_load((self.root / run / "metadata.yml").read_text())
        self.assertEqual(metadata["dynamic_dir"], str(self.dynamic))
        self.assertIs(metadata["include_dynamic"], True)

    def test_trailing_slash_still_lands_in_dynamic(self) -> None:
        result = self.run_role(traefik_backup_dynamic_dir=f"{self.dynamic}/")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        members = self.archive_members()
        run = members[0].split("/")[0]
        self.assertIn(f"{run}/dynamic/homelab.yml", members)
        self.assertNotIn(f"{run}/homelab.yml", members)

    def test_layout_does_not_depend_on_the_source_name(self) -> None:
        routes = self.base / "etc" / "traefik" / "routes"
        self.dynamic.rename(routes)
        result = self.run_role(traefik_backup_dynamic_dir=str(routes))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        members = self.archive_members()
        run = members[0].split("/")[0]
        self.assertIn(f"{run}/dynamic/homelab.yml", members)
        self.assertFalse([m for m in members if "/routes" in m], members)

    def test_missing_dynamic_dir_fails(self) -> None:
        shutil.rmtree(self.dynamic)
        result = self.run_role()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Traefik dynamic config directory not found", result.stdout)
        self.assertFalse(list(self.root.glob("test-*.tar.gz")))

    def test_disabled_dynamic_backup_skips_the_directory(self) -> None:
        result = self.run_role(traefik_backup_include_dynamic=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        members = self.archive_members()
        # Like acme/, the (empty) dynamic/ directory is always created.
        self.assertFalse([m for m in members if "/dynamic/" in m], members)


if __name__ == "__main__":
    unittest.main()
