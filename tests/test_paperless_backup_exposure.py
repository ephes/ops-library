"""Paperless backups and the Paperless listener must not be wider than needed.

The backup archive holds every document, the database dump and the service
configuration with its secrets. ``paperless_backup`` used to set it to mode
0644 "for the fetch" inside a 0755 directory, so every account on the host
could read it. tar now writes a private temporary file that is renamed into
place, the role applies
``paperless_backup_archive_mode`` (default 0600) whether or not the archive is
fetched, and the local copy is set to 0600.

``paperless_deploy`` hard-coded ``0.0.0.0`` for gunicorn although its Traefik
route and health check use 127.0.0.1. ``paperless_bind_address`` makes that a
setting; the default is unchanged.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / "roles/paperless_backup"
DEPLOY = ROOT / "roles/paperless_deploy"


def backup_tasks() -> list[dict]:
    return yaml.safe_load((BACKUP / "tasks/main.yml").read_text())


def task_named(name: str) -> dict:
    matches = [task for task in backup_tasks() if task.get("name") == name]
    if len(matches) != 1:
        raise AssertionError(f"expected one task named {name!r}, found {len(matches)}")
    return matches[0]


def conditions(task: dict) -> list[str]:
    when = task.get("when", [])
    return [when] if isinstance(when, str) else list(when)


class PaperlessBackupArchiveModeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.defaults = yaml.safe_load((BACKUP / "defaults/main.yml").read_text())

    def test_default_archive_mode_is_owner_only(self) -> None:
        self.assertEqual(self.defaults["paperless_backup_archive_mode"], "0600")

    def test_tar_creates_the_archive_owner_only(self) -> None:
        """tar writes a fresh 0600 mktemp file that is renamed into place.

        Creating the destination first with the file module is not enough (it
        is opened with the process umask and only then restricted), and umask
        alone does not help when a file of that name already exists.
        """
        for name in ("Create tar.gz archive", "Create tar.zst archive"):
            with self.subTest(task=name):
                task = task_named(name)
                script = task["ansible.builtin.shell"]
                lines = [line.strip() for line in script.splitlines() if line.strip()]
                self.assertEqual(lines[0], "set -euo pipefail")
                self.assertEqual(lines[1], "umask 077")
                self.assertEqual(
                    lines[2],
                    "archive={{ paperless_backup_archive_path | basename | quote }}",
                )
                self.assertEqual(lines[3], 'partial="$(mktemp ".${archive}.XXXXXXXX")"')
                self.assertEqual(lines[4], """trap 'rm -f -- "$partial"' EXIT""")
                self.assertTrue(lines[5].startswith("tar -C "), lines[5])
                self.assertIn(' "$partial" ', lines[5])
                self.assertEqual(lines[6], 'mv -f -- "$partial" "$archive"')
                self.assertEqual(len(lines), 7)
                self.assertEqual(task["args"]["executable"], "/bin/bash")
                self.assertEqual(task["args"]["chdir"], "{{ paperless_backup_root }}")

    def test_shell_tasks_quote_every_templated_value(self) -> None:
        for name in ("Create tar.gz archive", "Create tar.zst archive"):
            with self.subTest(task=name):
                script = task_named(name)["ansible.builtin.shell"]
                expressions = re.findall(r"\{\{(.*?)\}\}", script)
                self.assertEqual(len(expressions), 3)
                for expression in expressions:
                    self.assertTrue(expression.strip().endswith("| quote"), expression)

    def test_nothing_creates_the_archive_before_tar(self) -> None:
        names = [task.get("name") for task in backup_tasks()]
        first_tar = names.index("Create tar.gz archive")
        for task in backup_tasks()[:first_tar]:
            for module in ("ansible.builtin.file", "ansible.builtin.copy"):
                arguments = task.get(module)
                if isinstance(arguments, dict):
                    target = str(arguments.get("path", arguments.get("dest")))
                    self.assertNotIn("paperless_backup_archive_path", target)

    def test_archive_mode_is_enforced_whether_or_not_it_is_fetched(self) -> None:
        task = task_named("Ensure archive permissions")
        module = task["ansible.builtin.file"]
        self.assertEqual(module["mode"], "{{ paperless_backup_archive_mode }}")
        self.assertEqual(module["owner"], "{{ paperless_backup_owner }}")
        self.assertEqual(conditions(task), ["paperless_backup_create_archive"])
        names = [task.get("name") for task in backup_tasks()]
        self.assertLess(
            names.index("Create tar.zst archive"),
            names.index("Ensure archive permissions"),
        )
        self.assertLess(
            names.index("Ensure archive permissions"),
            names.index("Fetch archive to control machine via synchronize"),
        )

    def test_no_task_opens_the_archive_to_other_accounts(self) -> None:
        text = (BACKUP / "tasks/main.yml").read_text()
        self.assertNotIn("Ensure archive is readable for fetch", text)
        for task in backup_tasks():
            for module in ("ansible.builtin.file", "ansible.builtin.copy"):
                arguments = task.get(module)
                if not isinstance(arguments, dict):
                    continue
                target = arguments.get("path", arguments.get("dest"))
                if target != "{{ paperless_backup_archive_path }}":
                    continue
                with self.subTest(task=task.get("name")):
                    self.assertEqual(
                        arguments.get("mode"), "{{ paperless_backup_archive_mode }}"
                    )

    def test_local_copy_has_no_group_or_other_access(self) -> None:
        task = task_named("Fetch archive to control machine via synchronize")
        options = task["ansible.posix.synchronize"]["rsync_opts"]
        # --chmod only takes effect together with --perms (archive is off).
        self.assertEqual(options, ["--perms", "--chmod=u=rw,go="])
        self.assertEqual(self.defaults["paperless_backup_local_dir_mode"], "0700")

    def test_local_copy_mode_is_set_after_either_fetch_method(self) -> None:
        names = [task.get("name") for task in backup_tasks()]
        restrict = names.index("Restrict local archive copy permissions")
        self.assertGreater(
            restrict, names.index("Fetch archive to control machine via synchronize")
        )
        self.assertGreater(restrict, names.index("Fetch archive to control machine via fetch"))
        task = task_named("Restrict local archive copy permissions")
        self.assertEqual(
            task["ansible.builtin.file"],
            {
                "path": "{{ paperless_backup_local_dir }}/"
                "{{ paperless_backup_archive_path | basename }}",
                "mode": "0600",
            },
        )
        self.assertEqual(task["delegate_to"], "localhost")
        self.assertIs(task["become"], False)
        self.assertEqual(
            conditions(task),
            ["paperless_backup_fetch_local", "paperless_backup_create_archive"],
        )


class PaperlessBindAddressTest(unittest.TestCase):
    def setUp(self) -> None:
        self.defaults = yaml.safe_load((DEPLOY / "defaults/main.yml").read_text())
        self.environment = Environment(
            loader=FileSystemLoader(DEPLOY / "templates"),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
        )

    def variables(self, **overrides: object) -> dict:
        values = {
            "paperless_virtualenv": "/home/paperless/site/.venv",
            "paperless_site_root": "/home/paperless/site",
            "paperless_manage_dir": "/home/paperless/site/paperless-ngx/src",
            "paperless_env_file": "/home/paperless/site/.env",
            "paperless_username": "paperless",
            "paperless_group": "paperless",
            "paperless_python_version": "3.12",
            "paperless_nltk_data_path": "/home/paperless/nltk",
            "paperless_external_storage_root": "/mnt/cryptdata/paperless",
            "paperless_task_workers": 2,
            "paperless_threads_per_worker": 2,
            "paperless_logs_dir": "/home/paperless/site/logs",
            "paperless_app_port": self.defaults["paperless_app_port"],
            "paperless_bind_address": self.defaults["paperless_bind_address"],
        }
        values.update(overrides)
        return values

    def binds(self, **overrides: object) -> tuple[str, str]:
        variables = self.variables(**overrides)
        unit = self.environment.get_template("paperless.service.j2").render(**variables)
        config = self.environment.get_template("gunicorn.conf.py.j2").render(**variables)
        (unit_bind,) = re.findall(r"--bind (\S+)", unit)
        (config_bind,) = re.findall(r'(?m)^bind = "([^"]+)"', config)
        return unit_bind, config_bind

    def test_default_keeps_the_previous_listener(self) -> None:
        self.assertEqual(self.defaults["paperless_bind_address"], "0.0.0.0")
        self.assertEqual(self.binds(), ("0.0.0.0:10030", "0.0.0.0:10030"))

    def test_loopback_setting_reaches_unit_and_gunicorn_config(self) -> None:
        self.assertEqual(
            self.binds(paperless_bind_address="127.0.0.1"),
            ("127.0.0.1:10030", "127.0.0.1:10030"),
        )

    def test_no_template_hard_codes_a_wildcard_listener(self) -> None:
        for template in ("paperless.service.j2", "gunicorn.conf.py.j2"):
            with self.subTest(template=template):
                self.assertNotIn("0.0.0.0", (DEPLOY / "templates" / template).read_text())

    def test_role_reaches_the_application_on_loopback(self) -> None:
        """Proxy upstream and health check stay valid with a loopback listener."""
        traefik = (DEPLOY / "templates/paperless.traefik.yml.j2").read_text()
        self.assertIn('url: "http://127.0.0.1:{{ paperless_app_port }}"', traefik)
        service = (DEPLOY / "tasks/service.yml").read_text()
        self.assertIn('url: "http://127.0.0.1:{{ paperless_app_port }}/api/"', service)


if __name__ == "__main__":
    unittest.main()
