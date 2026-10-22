"""Wiring of python_security_floor into the roles that install Python packages.

Checks the order (preflight before the first change, constraints before the
installs, verify after them), that every install command carries the
constraint file when the guard is on and nothing when it is off, and, for
MeTube, that the lock checked is the lock of exactly the commit source.yml
then checks out.
"""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLES = ROOT / "roles"
FIXTURES = ROOT / "tests/fixtures/python_security"

spec = importlib.util.spec_from_file_location("python_security", ROOT / "plugins/filter/python_security.py")
flt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flt)
FLOORS = yaml.safe_load((ROLES / "python_security_floor/defaults/main.yml").read_text())["python_security_floor_packages"]

ENV = jinja2.Environment(undefined=jinja2.StrictUndefined)
ENV.filters["quote"] = lambda value: __import__("shlex").quote(str(value))
ENV.filters["bool"] = lambda value: value if isinstance(value, bool) else str(value).lower() in ("true", "yes", "1")


def load(path):
    return yaml.safe_load((ROLES / path).read_text())


def names(tasks):
    return [t["name"] for t in tasks]


def render(template, **variables):
    return ENV.from_string(template).render(**variables)


def default(role, var, **variables):
    """One default of ``role``, templated by Ansible with ``variables`` and the role's defaults in scope."""

    from ansible.parsing.dataloader import DataLoader
    from ansible.template import Templar, trust_as_template

    # Role defaults are trusted templates in a play; mark them so here too.
    defaults = load(f"{role}/defaults/main.yml")
    scope = {k: trust_as_template(v) if isinstance(v, str) else v for k, v in defaults.items()} | variables
    value = Templar(loader=DataLoader(), variables=scope).template(scope[var])
    return value.strip() if isinstance(value, str) else value


def index(tasks, name):
    return names(tasks).index(name)


class OrderTests(unittest.TestCase):
    def assert_order(self, role, first, *later):
        tasks = load(f"{role}/tasks/main.yml")
        positions = [index(tasks, name) for name in (first, *later)]
        self.assertEqual(positions, sorted(positions), f"{role}: {first!r} must precede {later!r}")
        return tasks

    def test_metube(self):
        tasks = self.assert_order(
            "metube_deploy",
            "Validate required variables",
            "Check the existing environment's certifi/pip floors",
            "Ensure uv is installed",
        )
        self.assert_order(
            "metube_deploy",
            "Build frontend assets in the staging checkout",
            "Check the dependency lock of the revision to deploy",
            "Fetch MeTube sources",
            "Create Python environment and install dependencies",
            "Verify the environment's certifi/pip floors",
        )
        preflight = tasks[index(tasks, "Check the existing environment's certifi/pip floors")]
        self.assertIn("not (metube_sync_dependencies | bool)", preflight["when"])

    def test_homeassistant(self):
        self.assert_order(
            "homeassistant_deploy",
            "Run Home Assistant validation tasks",
            "Check existing environments' certifi/pip floors",
            "Install required packages",
        )
        self.assert_order(
            "homeassistant_deploy",
            "Write the certifi/pip install constraints",
            "Provision Python environment",
            "Manage Matter server",
            "Verify the environments' certifi/pip floors",
        )

    def test_open_webui(self):
        self.assert_order(
            "open_webui_venv_deploy",
            "main | Validate required variables",
            "main | Check the existing environment's certifi/pip floors",
            "main | Ensure uv is installed",
            "main | Write the certifi/pip install constraints",
            "main | Provision Open WebUI Python environment",
            "main | Verify the environment's certifi/pip floors",
        )

    def test_paperless(self):
        self.assert_order(
            "paperless_deploy",
            "Install system packages",
            "Write the certifi/pip install constraints",
            "Install Paperless application",
            "Verify the environment's certifi/pip floors",
        )

    def test_takahe(self):
        self.assert_order(
            "takahe_deploy",
            "Install Takahe dependencies",
            "Write the certifi/pip install constraints",
            "Configure Python environment",
            "Verify the environment's certifi/pip floors",
        )


class ConstraintArgumentTests(unittest.TestCase):
    """Every package install a role runs carries the constraint file, and only when enabled."""

    def install_commands(self, path, marker):
        tasks = load(path)
        return [t for t in tasks if marker in str(t.get("ansible.builtin.command", ""))]

    def test_homeassistant_installs(self):
        on = default("homeassistant_deploy", "homeassistant_python_security_constraint_args", homeassistant_home="/h")
        self.assertEqual(on, "--constraint /h/site/.python-security-constraints.txt")
        off = default(
            "homeassistant_deploy",
            "homeassistant_python_security_constraint_args",
            homeassistant_home="/h",
            homeassistant_python_security_floor_enabled=False,
        )
        self.assertEqual(off, "")
        commands = self.install_commands("homeassistant_deploy/tasks/python.yml", "pip', 'install'")
        commands += self.install_commands("homeassistant_deploy/tasks/python.yml", "pip install")
        commands += self.install_commands("homeassistant_deploy/tasks/matter_server.yml", "pip install")
        self.assertEqual(len(commands), 3)
        for task in commands:
            text = str(task["ansible.builtin.command"])
            self.assertTrue(
                "homeassistant_python_security_constraint_args" in text
                or "homeassistant_python_security_constraint_argv" in text,
                task["name"],
            )

    def test_open_webui_install(self):
        (task,) = self.install_commands("open_webui_venv_deploy/tasks/python.yml", "pip install")
        self.assertIn("open_webui_python_security_constraint_args", task["ansible.builtin.command"])
        self.assertEqual(
            default("open_webui_venv_deploy", "open_webui_python_security_constraint_args"),
            "--constraint /opt/open-webui/.python-security-constraints.txt",
        )

    def test_paperless_installs(self):
        commands = self.install_commands("paperless_deploy/tasks/application.yml", "pip install")
        self.assertEqual(len(commands), 3)
        for task in commands:
            self.assertIn("paperless_python_security_constraint_args", task["ansible.builtin.command"]["cmd"])

    def test_takahe_pip_tasks(self):
        tasks = [t for t in load("takahe_deploy/tasks/python.yml") if "ansible.builtin.pip" in t]
        self.assertEqual(len(tasks), 2)
        for task in tasks:
            self.assertIn("takahe_python_security_pip_args", task["ansible.builtin.pip"]["extra_args"])
        self.assertEqual(
            default("takahe_deploy", "takahe_python_security_pip_args", takahe_home_path="/home/takahe"),
            "-c /home/takahe/.python-security-constraints.txt",
        )

    def test_preflight_deferrals(self):
        (owui,) = [t for t in load("open_webui_venv_deploy/tasks/security_preflight.yml") if "vars" in t]
        self.assertEqual(owui["vars"]["python_security_floor_deferred"], ["certifi"])
        (takahe,) = [
            d for d in load("takahe_deploy/meta/main.yml")["dependencies"] if d["role"].endswith("python_security_floor")
        ]
        expr = takahe["vars"]["python_security_floor_preflight"][0]["deferred"]
        self.assertEqual(yaml.safe_load(render(expr, takahe_pip_upgrade=True)), ["certifi", "pip"])
        self.assertEqual(yaml.safe_load(render(expr, takahe_pip_upgrade=False)), ["certifi"])
        for role in ("homeassistant_deploy", "metube_deploy"):
            text = (ROLES / role / "tasks/security_preflight.yml").read_text()
            self.assertNotIn("python_security_floor_deferred", text, role)
        (paperless,) = [
            d for d in load("paperless_deploy/meta/main.yml")["dependencies"] if d["role"].endswith("python_security_floor")
        ]
        self.assertNotIn("deferred", paperless["vars"]["python_security_floor_preflight"][0])


class DependencyOrderTests(unittest.TestCase):
    """Roles whose meta dependencies change the host run the preflight dependency first."""

    def task_list(self, role):
        import os

        collections = subprocess.run(
            [str(ROOT / "scripts/checkout-collections-path.sh")], check=True, capture_output=True, text=True
        ).stdout.strip()
        with tempfile.TemporaryDirectory(prefix="ops-library-deps-") as tmp:
            play = Path(tmp) / "play.yml"
            play.write_text(f"- hosts: localhost\n  gather_facts: false\n  roles:\n    - local.ops_library.{role}\n")
            out = subprocess.run(
                ["ansible-playbook", "-i", "localhost,", "-c", "local", "--list-tasks", str(play)],
                check=True,
                capture_output=True,
                text=True,
                # Dependencies use community collections from the usual locations.
                env={
                    **os.environ,
                    "ANSIBLE_COLLECTIONS_PATH": f"{collections}:{Path.home() / '.ansible/collections'}"
                    ":/usr/share/ansible/collections",
                },
            ).stdout
        return [line.strip().split("\t")[0] for line in out.splitlines() if line.startswith("      ")]

    def assert_preflight_first(self, role, skip=()):
        tasks = [t for t in self.task_list(role) if not t.startswith(skip)]
        prefix = "local.ops_library.python_security_floor : main | "
        self.assertTrue(tasks[0].startswith(prefix + "Require"), tasks[:3])
        self.assertTrue(tasks[2].startswith(prefix + "Verify existing"), tasks[:3])
        self.assertFalse(tasks[3].startswith("local.ops_library.python_security_floor"), tasks[:4])

    def test_paperless_preflight_precedes_uv_redis_and_postgres(self):
        self.assert_preflight_first("paperless_deploy")

    def test_takahe_preflight_precedes_postgres(self):
        # takahe_shared only sets defaults.
        self.assert_preflight_first("takahe_deploy", skip=("local.ops_library.takahe_shared :",))


class MetubeExactRevisionTests(unittest.TestCase):
    """The lock checked is the lock of the commit source.yml checks out."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="ops-library-metube-rev-")
        repo = Path(cls.tmp.name) / "upstream"
        git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        subprocess.run(["git", "init", "-q", "-b", "master", str(repo)], check=True)
        for tag, fixture in (("2026.10.09", "uv-lock-stale.txt"), ("2026.10.20", "uv-lock-current.txt")):
            (repo / "uv.lock").write_text((FIXTURES / fixture).read_text())
            subprocess.run([*git, "add", "uv.lock"], check=True)
            subprocess.run([*git, "commit", "-q", "-m", tag], check=True)
            subprocess.run([*git, "tag", tag], check=True)
        cls.repo = repo
        cls.tasks = load("metube_deploy/tasks/security_source.yml")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def rev(self, ref):
        return subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", f"{ref}^{{commit}}"], check=True, capture_output=True, text=True
        ).stdout.strip()

    def check(self, ui_build, ref):
        variables = {"metube_ui_build": ui_build, "metube_ui_build_dir": str(self.repo), "metube_source_check_dir": str(self.repo)}
        if ui_build:
            variables["metube_ui_build_rev"] = self.rev(ref)
        else:
            variables["metube_source_check_checkout"] = {"after": self.rev(ref)}
        record = self.tasks[index(self.tasks, "security_source | Record the MeTube revision to deploy")]["ansible.builtin.set_fact"]
        facts = {k: render(v, **variables).strip() for k, v in record.items()}
        read = self.tasks[index(self.tasks, "security_source | Read the uv.lock of the MeTube revision to deploy")]
        argv = [render(a, **variables, **facts) for a in read["ansible.builtin.command"]["argv"]]
        lock = subprocess.run(argv, check=True, capture_output=True, text=True).stdout
        source = load("metube_deploy/tasks/source.yml")[0]["ansible.builtin.git"]["version"]
        deployed = render(source.replace("| default(metube_ui_build_rev) | default(metube_repo_version)", ""), **facts)
        return facts["metube_source_rev"], deployed, flt.uv_lock_floor_violations(lock, FLOORS)

    def test_stale_tag_is_refused_with_and_without_ui_build(self):
        for ui_build in (True, False):
            rev, deployed, problems = self.check(ui_build, "2026.10.09")
            self.assertEqual(rev, deployed)
            self.assertIn("certifi 2026.7.22 is locked; 2026.10.19 or later is required", problems)

    def test_fixed_tag_passes_and_is_the_commit_deployed(self):
        for ui_build in (True, False):
            rev, deployed, problems = self.check(ui_build, "2026.10.20")
            self.assertEqual((rev, deployed, problems), (self.rev("2026.10.20"), self.rev("2026.10.20"), []))

    def test_no_ui_build_uses_its_own_staging_checkout_before_the_source_checkout(self):
        (block,) = [t for t in self.tasks if "block" in t]
        self.assertEqual(block["when"], "not (metube_ui_build | bool)")
        git = [t for t in block["block"] if "ansible.builtin.git" in t][0]["ansible.builtin.git"]
        self.assertEqual(git["dest"], "{{ metube_source_check_dir }}")
        self.assertEqual(git["version"], "{{ metube_repo_version }}")


if __name__ == "__main__":
    unittest.main()
