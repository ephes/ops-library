"""MeTube's unit renders ``RequiresMountsFor=`` from ``metube_mounts_required``.

The default (empty) list must leave the unit byte-identical; a non-empty list
adds one line to ``[Unit]``. ``validate.yml`` refuses values that are not a
list of plain absolute paths, since they are rendered into the unit unquoted.
"""

import re
import unittest
from pathlib import Path

import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/metube_deploy"
TEMPLATE = ROLE / "templates/metube.service.j2"
VALIDATE = ROLE / "tasks/validate.yml"
TASK_NAME = "Validate required mounts"

UNIT_VARS = {
    "metube_systemd_after": "network.target",
    "metube_user": "metube",
    "metube_group": "metube",
    "metube_app_dir": "/opt/metube",
    "metube_env_file": "/etc/metube/metube.env",
    "metube_venv_path": "/opt/metube/venv",
    "metube_systemd_restart": "on-failure",
    "metube_systemd_restart_sec": "5s",
    "metube_systemd_nofile": 65535,
    "metube_systemd_hardening": False,
    "metube_systemd_tasks_max": "",
    "metube_systemd_memory_max": "",
    "metube_home": "/var/lib/metube",
    "metube_download_dir": "/srv/metube/downloads",
    "metube_temp_dir": "/srv/metube/downloads",
    "metube_state_dir": "/var/lib/metube",
    "metube_audio_download_dir": "/srv/metube/downloads",
}


def environment():
    # Ansible's template module: trim_blocks, trailing newline kept.
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, trim_blocks=True, keep_trailing_newline=True)
    env.filters["bool"] = bool
    env.tests["match"] = lambda value, pattern: re.match(pattern, value) is not None
    env.tests["search"] = lambda value, pattern: re.search(pattern, value) is not None
    return env


def render(mounts=None, source=None):
    variables = dict(UNIT_VARS)
    if mounts is not None:
        variables["metube_mounts_required"] = mounts
    text = source if source is not None else TEMPLATE.read_text(encoding="utf-8")
    return environment().from_string(text).render(**variables)


def defaults():
    return yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))


def valid(mounts):
    tasks = yaml.safe_load(VALIDATE.read_text(encoding="utf-8"))
    [task] = [task for task in tasks if task.get("name") == TASK_NAME]
    env = environment()
    return all(
        env.from_string("{{ (" + expression + ") }}").render(metube_mounts_required=mounts) == "True"
        for expression in task["ansible.builtin.assert"]["that"]
    )


class MetubeMountsRequiredTest(unittest.TestCase):
    def test_default_is_empty(self):
        self.assertEqual(defaults()["metube_mounts_required"], [])

    def test_empty_list_renders_the_unit_without_the_line(self):
        without = re.sub(
            r"\{% if metube_mounts_required %\}\n.*?\{% endif %\}\n",
            "",
            TEMPLATE.read_text(encoding="utf-8"),
            flags=re.DOTALL,
        )
        unit = render([])
        self.assertNotIn("RequiresMountsFor", unit)
        self.assertEqual(unit, render(source=without))

    def test_mounts_render_one_line_in_the_unit_section(self):
        unit = render(["/mnt/cryptdata/media", "/srv/extra"])
        self.assertEqual(
            unit.split("\n\n", 1)[0].splitlines(),
            [
                "[Unit]",
                "Description=MeTube (yt-dlp web UI)",
                "After=network.target",
                "RequiresMountsFor=/mnt/cryptdata/media /srv/extra",
            ],
        )

    def test_validation_accepts_plain_absolute_paths(self):
        self.assertTrue(valid([]))
        self.assertTrue(valid(["/mnt/cryptdata/media"]))
        self.assertTrue(valid(["/mnt/cryptdata/media", "/srv/extra_1.d"]))

    def test_validation_refuses_anything_else(self):
        for value in (
            "/mnt/cryptdata/media",
            {"path": "/mnt"},
            ["relative/path"],
            ["/mnt/with space"],
            ["/mnt/a\nExecStartPre=/bin/x"],
            ["/mnt/%i"],
            ["/"],
            ["/mnt/../etc"],
            ["/mnt/."],
        ):
            with self.subTest(value=value):
                self.assertFalse(valid(value))


if __name__ == "__main__":
    unittest.main()
