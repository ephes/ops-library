"""GPS Timeline integration and Location Timeline Card in homeassistant_deploy,
and GPS Timeline's database in homeassistant_backup.

Static checks pin the artifacts and the wiring. The engine tests run the real
tasks on localhost: the deploy tasks twice against synthetic ``file://``
artifacts (the second run changes nothing and notifies no restart; needs GNU
tar for ``unarchive``), and the backup role against a live WAL database.
"""

from __future__ import annotations

import contextlib
import grp
import hashlib
import io
import json
import os
import pwd
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "roles" / "homeassistant_deploy"
BACKUP = ROOT / "roles" / "homeassistant_backup"
GPS_SHA = "feb29bc1705181aab9146cacf2c7552a70d969042825734af0435000db1ee34e"  # pragma: allowlist secret
CARD_SHA = "d81404bc66ef2affcbd701af08a04fcfee199dadfb6b82674576291db50987a5"  # pragma: allowlist secret
VERSION = "0.1.0-beta.3"
ANSIBLE = shutil.which("ansible-playbook")
HANDLER = "RUNNING HANDLER [homeassistant_deploy : restart homeassistant]"


def gnu_tar() -> bool:
    for name in ("gtar", "tar"):
        path = shutil.which(name)
        if (
            path
            and "GNU tar"
            in subprocess.run(
                [path, "--version"], capture_output=True, text=True
            ).stdout
        ):
            return True
    return False


def run_playbook(base: Path, play: dict) -> subprocess.CompletedProcess[str]:
    playbook = base / "play.yml"
    playbook.write_text(yaml.safe_dump([play]), encoding="utf-8")
    env = {
        **os.environ,
        "ANSIBLE_ROLES_PATH": str(ROOT / "roles"),
        "ANSIBLE_NOCOLOR": "1",
        "ANSIBLE_LOCALHOST_WARNING": "0",
        "ANSIBLE_INVENTORY_UNPARSED_WARNING": "0",
    }
    assert ANSIBLE is not None
    return subprocess.run(
        [ANSIBLE, "-i", "localhost,", "-c", "local", str(playbook)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )


def account() -> dict[str, str]:
    return {
        "user": pwd.getpwuid(os.getuid()).pw_name,
        "group": grp.getgrgid(os.getgid()).gr_name,
    }


class StaticTests(unittest.TestCase):
    def test_defaults_pin_the_artifacts_and_stay_off(self) -> None:
        defaults = yaml.safe_load((DEPLOY / "defaults/main.yml").read_text())
        self.assertIs(defaults["homeassistant_gps_timeline_enabled"], False)
        self.assertIs(defaults["homeassistant_timeline_card_enabled"], False)
        self.assertEqual(defaults["homeassistant_gps_timeline_version"], VERSION)
        self.assertEqual(defaults["homeassistant_gps_timeline_sha256"], GPS_SHA)
        self.assertEqual(defaults["homeassistant_timeline_card_version"], "1.9.3")
        self.assertEqual(defaults["homeassistant_timeline_card_sha256"], CARD_SHA)
        self.assertEqual(
            defaults["homeassistant_gps_timeline_download_url"].strip(),
            "https://github.com/iamyacin/gps-timeline/archive/refs/tags/"
            "{{ homeassistant_gps_timeline_version }}.tar.gz",
        )
        self.assertEqual(
            defaults["homeassistant_timeline_card_download_url"].strip(),
            "https://github.com/iamyacin/timeline_card/releases/download/"
            "v{{ homeassistant_timeline_card_version }}/timeline_card.js",
        )

    def test_main_imports_both_only_when_enabled(self) -> None:
        tasks = yaml.safe_load((DEPLOY / "tasks/main.yml").read_text())
        by_file = {
            task.get("ansible.builtin.import_tasks"): task.get("when") for task in tasks
        }
        self.assertEqual(
            by_file["gps_timeline.yml"], "homeassistant_gps_timeline_enabled | bool"
        )
        self.assertEqual(
            by_file["timeline_card.yml"], "homeassistant_timeline_card_enabled | bool"
        )

    def test_tasks_leave_user_yaml_and_the_data_directory_alone(self) -> None:
        for name in ("gps_timeline.yml", "timeline_card.yml"):
            text = (DEPLOY / "tasks" / name).read_text()
            for untouched in (
                "configuration.yaml",
                "automations.yaml",
                "scripts.yaml",
                "overwrite",
            ):
                self.assertNotIn(untouched, text)
            for task in yaml.safe_load(text):
                for body in [task, *task.get("block", [])]:
                    module = body.get("ansible.builtin.file", {})
                    if module.get("state") == "absent":
                        self.assertEqual(module["path"], "{{ _ha_gps_component_dir }}")
        facts = yaml.safe_load((DEPLOY / "tasks/gps_timeline.yml").read_text())[1][
            "ansible.builtin.set_fact"
        ]
        self.assertTrue(
            facts["_ha_gps_component_dir"].endswith("/custom_components/gps_timeline")
        )

    def test_backup_role_covers_the_gps_database_by_default(self) -> None:
        defaults = yaml.safe_load((BACKUP / "defaults/main.yml").read_text())
        self.assertEqual(
            defaults["homeassistant_backup_config_sqlite_databases"],
            ["gps_timeline/gps_timeline.db"],
        )


@unittest.skipUnless(
    ANSIBLE and gnu_tar(), "needs ansible-playbook and GNU tar, as on the Linux targets"
)
class DeployEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.site = self.base / "site"
        (self.site / "config/gps_timeline").mkdir(parents=True)
        (self.site / "config/gps_timeline/gps_timeline.db").write_bytes(b"history")
        self.archive = self.base / "release.tar.gz"
        top = f"gps-timeline-{VERSION}"
        with tarfile.open(self.archive, "w:gz") as tar:
            for name, data in {
                f"{top}/README.md": b"readme",
                f"{top}/custom_components/gps_timeline/__init__.py": b"# synthetic",
                f"{top}/custom_components/gps_timeline/manifest.json": b"{}",
            }.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o664
                tar.addfile(info, io.BytesIO(data))
        self.card = self.base / "timeline_card.js"
        self.card.write_bytes(b"// synthetic card\n")
        self.card_sha = hashlib.sha256(self.card.read_bytes()).hexdigest()

    def run_tasks(self) -> subprocess.CompletedProcess[str]:
        ids = account()
        return run_playbook(
            self.base,
            {
                "hosts": "localhost",
                "gather_facts": False,
                "vars": {
                    "homeassistant_user": ids["user"],
                    "homeassistant_group": ids["group"],
                    "homeassistant_site_path": str(self.site),
                    "homeassistant_config_path": str(self.site / "config"),
                    "homeassistant_restart_on_change": False,
                    "homeassistant_gps_timeline_sha256": hashlib.sha256(
                        self.archive.read_bytes()
                    ).hexdigest(),
                    "homeassistant_gps_timeline_download_url": self.archive.as_uri(),
                    "homeassistant_timeline_card_sha256": self.card_sha,
                    "homeassistant_timeline_card_download_url": self.card.as_uri(),
                },
                "tasks": [
                    {
                        "ansible.builtin.include_role": {
                            "name": "homeassistant_deploy",
                            "tasks_from": name,
                        }
                    }
                    for name in ("gps_timeline.yml", "timeline_card.yml")
                ],
            },
        )

    def test_first_run_installs_and_notifies_repeat_changes_nothing(self) -> None:
        first = self.run_tasks()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertIn(HANDLER, first.stdout)
        component = self.site / "config/custom_components/gps_timeline"
        self.assertEqual(
            sorted(p.name for p in component.iterdir()),
            [".ops-pinned-version", "__init__.py", "manifest.json"],
        )
        sha = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.assertEqual(
            (component / ".ops-pinned-version").read_text(), f"{VERSION} {sha}\n"
        )
        self.assertEqual((component / "manifest.json").stat().st_mode & 0o777, 0o644)
        self.assertEqual(component.stat().st_mode & 0o777, 0o755)
        self.assertEqual(
            (self.site / "config/www/timeline_card.js").read_bytes(),
            self.card.read_bytes(),
        )
        self.assertEqual((self.site / "config/www").stat().st_mode & 0o777, 0o755)

        second = self.run_tasks()
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertNotIn(HANDLER, second.stdout)
        self.assertRegex(second.stdout, r"changed=0\b")
        self.assertEqual(
            (self.site / "config/gps_timeline/gps_timeline.db").read_bytes(), b"history"
        )

    def test_checksum_mismatch_fails_without_replacing_the_card(self) -> None:
        self.assertEqual(self.run_tasks().returncode, 0)
        # A changed upstream file at the same pin, with an install to repair.
        self.card.write_bytes(b"// tampered\n")
        (self.site / "config/www/timeline_card.js").write_bytes(b"// drifted\n")
        result = self.run_tasks()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            (self.site / "config/www/timeline_card.js").read_bytes(), b"// drifted\n"
        )


@unittest.skipUnless(
    ANSIBLE and shutil.which("rsync") and shutil.which("sqlite3"),
    "needs ansible-playbook, rsync and sqlite3",
)
class BackupEngineTest(unittest.TestCase):
    def test_gps_database_is_a_consistent_copy_without_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config = base / "site/config"
            (config / "gps_timeline").mkdir(parents=True)
            live = sqlite3.connect(config / "gps_timeline/gps_timeline.db")
            live.execute("PRAGMA journal_mode=WAL")
            live.execute("PRAGMA wal_autocheckpoint=0")
            live.executescript("CREATE TABLE p(v TEXT); INSERT INTO p VALUES ('kept');")
            live.commit()
            self.assertGreater(
                (config / "gps_timeline/gps_timeline.db-wal").stat().st_size, 0
            )
            (config / "configuration.yaml").write_text("{}\n")
            ids = account()
            root = base / "backups"
            try:
                result = run_playbook(
                    base,
                    {
                        "hosts": "localhost",
                        "gather_facts": True,
                        "gather_subset": ["!all", "date_time"],
                        "vars": {
                            "homeassistant_backup_root": str(root),
                            "homeassistant_config_path": str(config),
                            "homeassistant_data_path": str(base / "site/data"),
                            "homeassistant_logs_path": str(base / "site/logs"),
                            "homeassistant_service_unit_path": str(
                                base / "absent.service"
                            ),
                            "homeassistant_traefik_config_path": str(
                                base / "absent.yml"
                            ),
                            "homeassistant_backup_otbr_state_path": str(
                                base / "absent-thread"
                            ),
                            "homeassistant_backup_owner": ids["user"],
                            "homeassistant_backup_group": ids["group"],
                            "homeassistant_backup_fetch_local": False,
                            "homeassistant_backup_create_archive": False,
                            "homeassistant_backup_generate_checksums": False,
                        },
                        "roles": ["homeassistant_backup"],
                    },
                )
            finally:
                live.close()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            (snapshot,) = root.glob("manual-*")
            gps = snapshot / "config/gps_timeline"
            self.assertEqual(sorted(p.name for p in gps.iterdir()), ["gps_timeline.db"])
            copy = sqlite3.connect(gps / "gps_timeline.db")
            self.assertEqual(copy.execute("SELECT v FROM p").fetchall(), [("kept",)])
            copy.close()
            self.assertEqual(
                (snapshot / "config/configuration.yaml").read_text(), "{}\n"
            )


@unittest.skipUnless(
    shutil.which("rsync") and shutil.which("sqlite3"), "needs rsync and sqlite3"
)
class EchoportRunnerTest(unittest.TestCase):
    """The FastDeploy/Echoport runner snapshots the GPS database and restores it cleanly."""

    def test_backup_snapshots_and_excludes_the_live_files(self) -> None:
        from tests.test_sqlite_backup_runners import render_runner

        runner = render_runner("homeassistant_backup.py.j2")
        self.assertEqual(
            runner.CONFIG_SQLITE_DATABASES, ["gps_timeline/gps_timeline.db"]
        )
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            site = base / "site"
            config = site / "config"
            (config / "gps_timeline").mkdir(parents=True)
            (site / "data").mkdir()
            with contextlib.closing(
                sqlite3.connect(config / "home-assistant_v2.db")
            ) as main:
                main.execute("CREATE TABLE t(v)")
                main.commit()
            live = sqlite3.connect(config / "gps_timeline/gps_timeline.db")
            live.execute("PRAGMA journal_mode=WAL")
            live.execute("PRAGMA wal_autocheckpoint=0")
            live.executescript("CREATE TABLE p(v TEXT); INSERT INTO p VALUES ('kept');")
            live.commit()
            work = base / "work"
            work.mkdir()
            staged = base / "staged"
            runner.SITE_ROOT, runner.CONFIG_PATH, runner.DATA_PATH = (
                str(site),
                str(config),
                str(site / "data"),
            )
            runner.MAIN_DB_PATH = str(config / "home-assistant_v2.db")
            runner.ZIGBEE_DB_PATH = str(config / "zigbee.db")
            runner.LOGS_PATH = runner.THREAD_STATE_PATH = str(base / "absent")
            runner.SYSTEMD_UNIT_PATH = runner.TRAEFIK_CONFIG_PATH = str(
                base / "absent-file"
            )
            runner.MATTER_CHIP_FACTORY_PATH = ""
            runner.ALLOWED_ROOTS = [str(base)]
            runner.create_run_dir = lambda prefix: work
            runner.create_tarball = lambda source, tarball: (
                shutil.copytree(source, staged),
                tarball.write_bytes(b"x"),
            )
            real_run_cmd = runner.run_cmd
            runner.run_cmd = lambda args, check=True: (
                subprocess.CompletedProcess(args, 0, "", "")
                if args[0] == runner.MC_PATH
                else real_run_cmd(args, check)
            )
            try:
                with contextlib.redirect_stdout(
                    io.StringIO()
                ), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(
                        runner.backup({"ECHOPORT_TARGET": "homeassistant"}), 0
                    )
            finally:
                live.close()
            gps = staged / "config/gps_timeline"
            self.assertEqual(sorted(p.name for p in gps.iterdir()), ["gps_timeline.db"])
            with contextlib.closing(sqlite3.connect(gps / "gps_timeline.db")) as copy:
                self.assertEqual(
                    copy.execute("SELECT v FROM p").fetchall(), [("kept",)]
                )
            manifest = json.loads((staged / "manifest.json").read_text())
            self.assertEqual(manifest["target"], "homeassistant")

    def test_unsafe_database_paths_are_refused(self) -> None:
        from tests.test_sqlite_backup_runners import render_runner

        runner = render_runner("homeassistant_backup.py.j2")
        runner.ALLOWED_ROOTS = ["/"]
        runner.SITE_ROOT = (
            runner.CONFIG_PATH
        ) = runner.DATA_PATH = runner.MAIN_DB_PATH = "/"
        for bad in ("../x.db", "/abs.db", ".hidden/x.db", "a//b.db"):
            runner.CONFIG_SQLITE_DATABASES = [bad]
            with self.subTest(path=bad), self.assertRaises(ValueError):
                runner.validate_config_paths()


if __name__ == "__main__":
    unittest.main()
