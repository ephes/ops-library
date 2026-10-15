"""wagtail_deploy installs a site's runtime dependencies only.

Runs the role's own ``tasks/uv_sync.yml`` with the role defaults through
``ansible-playbook`` and a real ``uv`` against a throwaway project.  The
project's packages are local wheels, so the test needs no network.

The cases mirror a deploy: an existing venv that still holds the dev group
(as every venv synced before this option did) loses it, a second run changes
nothing, and the two switches bring back the default groups or add a named
group.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/wagtail_deploy"
UV = shutil.which("uv")
ANSIBLE_PLAYBOOK = shutil.which("ansible-playbook", path=str(Path(sys.executable).parent)) or shutil.which(
    "ansible-playbook"
)

PACKAGES = ("runtimepkg", "devpkg", "workerpkg")

PLAYBOOK = """\
- name: Run the wagtail_deploy dependency sync
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    # Variables beat the task's become keyword: the test runs as the
    # current user, without sudo.
    ansible_become: false
  tasks:
    - name: Load role defaults
      ansible.builtin.include_vars:
        file: "{role}/defaults/main.yml"

    - name: Sync dependencies like the role does
      ansible.builtin.include_tasks: "{role}/tasks/uv_sync.yml"

  handlers:
    - name: restart wagtail
      ansible.builtin.debug:
        msg: restart wagtail

    - name: restart wagtail db worker
      ansible.builtin.debug:
        msg: restart wagtail db worker
"""


def build_wheel(directory, name):
    """Write a minimal pure-Python wheel for ``name`` 0.1."""
    dist_info = f"{name}-0.1.dist-info"
    files = {
        f"{name}/__init__.py": "",
        f"{dist_info}/METADATA": f"Metadata-Version: 2.1\nName: {name}\nVersion: 0.1\n",
        f"{dist_info}/WHEEL": "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    record = "".join(f"{path},,\n" for path in files) + f"{dist_info}/RECORD,,\n"
    files[f"{dist_info}/RECORD"] = record
    path = directory / f"{name}-0.1-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as wheel:
        for member, content in files.items():
            wheel.writestr(member, content)
    return path


@unittest.skipUnless(UV and ANSIBLE_PLAYBOOK, "needs uv and ansible-playbook")
class WagtailUvSyncTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ops-library-wagtail-uv-sync-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.site = self.tmp / "site"
        self.venv = self.site / ".venv"
        wheels = self.tmp / "wheels"
        wheels.mkdir()
        self.site.mkdir()
        sources = "\n".join(
            f'{name} = {{ path = "{build_wheel(wheels, name)}" }}' for name in PACKAGES
        )
        (self.site / "pyproject.toml").write_text(
            textwrap.dedent(
                """\
                [project]
                name = "site"
                version = "0.1"
                requires-python = ">=3.9"
                dependencies = ["runtimepkg"]

                [dependency-groups]
                dev = ["devpkg"]
                worker = ["workerpkg"]

                [tool.uv]
                package = false

                [tool.uv.sources]
                """
            )
            + sources
            + "\n",
            encoding="utf-8",
        )
        self.env = dict(
            os.environ,
            UV_OFFLINE="1",
            UV_PYTHON_DOWNLOADS="never",
            UV_NO_CONFIG="1",
            UV_CACHE_DIR=str(self.tmp / "uv-cache"),
            ANSIBLE_STDOUT_CALLBACK="ansible.builtin.json",
            ANSIBLE_LOCALHOST_WARNING="false",
            ANSIBLE_INVENTORY_UNPARSED_WARNING="false",
        )
        for name in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"):
            self.env.pop(name, None)
        self.uv("lock")
        self.uv("venv", "--python", sys.executable, str(self.venv))
        (self.tmp / "playbook.yml").write_text(PLAYBOOK.format(role=ROLE), encoding="utf-8")

    def uv(self, *args):
        subprocess.run(
            [UV, *args], cwd=self.site, env=self.env, check=True, capture_output=True, text=True
        )

    def installed(self):
        found = set()
        for site_packages in self.venv.glob("lib/python*/site-packages"):
            found.update(name for name in PACKAGES if (site_packages / name / "__init__.py").exists())
        return found

    def run_role(self, **overrides):
        extra_vars = {
            "wagtail_uv_path": UV,
            "wagtail_user": os.environ.get("USER", "root"),
            "wagtail_site_path": str(self.site),
            "wagtail_venv_path": str(self.venv),
            **overrides,
        }
        proc = subprocess.run(
            [
                ANSIBLE_PLAYBOOK,
                "-i",
                "localhost,",
                "-e",
                json.dumps(extra_vars),
                str(self.tmp / "playbook.yml"),
            ],
            cwd=self.tmp,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        sync = [
            host_result
            for play in result["plays"]
            for task in play["tasks"]
            if task["task"]["name"] == "python | Install dependencies with uv"
            for host_result in task["hosts"].values()
        ]
        self.assertEqual(len(sync), 1, proc.stdout)
        return sync[0]

    def test_default_removes_dev_group_from_an_existing_venv(self):
        # A venv as the role left it before: synced with the default groups.
        subprocess.run(
            [UV, "sync", "--frozen"],
            cwd=self.site,
            env=dict(self.env, UV_PROJECT_ENVIRONMENT=str(self.venv)),
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(self.installed(), {"runtimepkg", "devpkg"})

        first = self.run_role()
        self.assertIn("--no-default-groups", first["cmd"])
        self.assertTrue(first["changed"], first)
        self.assertEqual(self.installed(), {"runtimepkg"})

        second = self.run_role()
        self.assertFalse(second["changed"], second)
        self.assertEqual(self.installed(), {"runtimepkg"})

    def test_default_groups_switch_installs_dev_group(self):
        result = self.run_role(wagtail_uv_install_default_groups=True)
        self.assertNotIn("--no-default-groups", result["cmd"])
        self.assertTrue(result["changed"], result)
        self.assertEqual(self.installed(), {"runtimepkg", "devpkg"})

    def test_named_group_is_installed_without_dev_group(self):
        result = self.run_role(wagtail_uv_sync_groups=["worker"])
        self.assertIn("--group=worker", result["cmd"])
        self.assertEqual(self.installed(), {"runtimepkg", "workerpkg"})


if __name__ == "__main__":
    unittest.main()
