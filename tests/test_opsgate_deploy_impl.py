"""opsgate_deploy: the Python/Rust switch per launchd unit.

The contract is section 10.1 of ``rust/PLAN.md`` in the opsgate repository
(slice S10): ``opsgate_api_impl`` and ``opsgate_runner_impl`` select each
unit's implementation; with ``opsgate_rust_version`` set the release archive is
installed into ``<root>/<version>/`` and validated by its versioned path
(``--version``, ``check-config api|runner``, ``check-db``) before a plist
points at it; each plist renders the venv command or the versioned binary in
the same ``bash -lc`` wrapper; the Python variant of each plist is rendered to
``/etc/opsgate/launchd-python/`` for the emergency rollback; the live units
are verified; old versions are pruned, never the pinned, a running or a
previous one.

Static checks on the task files, renders of both plists for each
implementation (compared with fixtures in ``tests/fixtures/opsgate_deploy``;
the Python renders are the plists the role rendered before the switch), and
``ansible-playbook`` runs against localhost of the role's own install,
previous-version and prune tasks with locally built fake release archives, a
fake ``sudo`` that logs its command line, and a temporary install root.
"""

from __future__ import annotations

import copy
import grp
import hashlib
import importlib.util
import io
import json
import os
import plistlib
import pwd
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/opsgate_deploy"
TASKS = ROLE / "tasks"
FIXTURES = ROOT / "tests/fixtures/opsgate_deploy"
VERSION = "0.3.0"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
NEW_FILES = ("rust_binary.yml", "launchd.yml", "verify.yml", "prune.yml")
SECRET_WORDS = re.compile(r"token|secret|password|bcrypt|private_key", re.I)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DOWNLOADS = _load("check_root_downloads", ROOT / "scripts/check_root_downloads.py")


def walk(tasks):
    for task in tasks or []:
        yield task
        for section in ("block", "rescue", "always"):
            yield from walk(task.get(section, []))


def task_file(name: str) -> list[dict]:
    return yaml.safe_load((TASKS / name).read_text(encoding="utf-8"))


def by_name(tasks: list[dict], suffix: str) -> dict:
    for task in walk(tasks):
        if str(task.get("name", "")).endswith(suffix):
            return task
    raise AssertionError(f"no task named ...{suffix}")


def role_defaults() -> dict:
    return yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Static checks
# --------------------------------------------------------------------------


class StaticTests(unittest.TestCase):
    def test_defaults_keep_python_and_install_nothing(self):
        defaults = role_defaults()
        self.assertEqual(defaults["opsgate_api_impl"], "python")
        self.assertEqual(defaults["opsgate_runner_impl"], "python")
        self.assertEqual(defaults["opsgate_rust_version"], "")
        self.assertEqual(defaults["opsgate_rust_sha256"], "")
        self.assertEqual(defaults["opsgate_rust_local_archive"], "")
        self.assertEqual(defaults["opsgate_rust_install_root"], "/usr/local/libexec/opsgate-rs")
        self.assertEqual(defaults["opsgate_rust_keep_versions"], 3)
        self.assertEqual(
            defaults["opsgate_launchd_python_plist_dir"], "{{ opsgate_config_dir }}/launchd-python"
        )

    def test_release_url_names_the_tagged_release_asset(self):
        url = (
            Environment(undefined=StrictUndefined)
            .from_string(role_defaults()["opsgate_rust_release_url"])
            .render(opsgate_rust_version=VERSION)
        )
        self.assertEqual(
            url,
            "https://github.com/ephes/opsgate/releases/download/rs-v0.3.0/"
            "opsgate-0.3.0-aarch64-apple-darwin.tar.gz",
        )

    def test_task_order(self):
        names = [task["name"] for task in task_file("main.yml")]
        order = [
            "main | Validate required variables and target",
            "main | Sync OpsGate application source into control service home",
            "main | Write control-plane and runner environment files",
            "main | Install and validate the pinned Rust release",
            "main | Render and optionally manage launchd plists",
            "main | Verify the running implementations",
            "main | Prune old Rust releases",
        ]
        self.assertEqual([n for n in names if n in order], order)
        self.assertEqual(
            by_name(task_file("main.yml"), "Install and validate the pinned Rust release")[
                "ansible.builtin.import_tasks"
            ],
            "rust_binary.yml",
        )
        for name in order[-3:]:
            self.assertNotIn("when", by_name(task_file("main.yml"), name))

    def test_switch_is_validated_before_anything_changes(self):
        tasks = task_file("validate.yml")
        that = "\n".join(by_name(tasks, "Ensure the implementation switch is coherent")["ansible.builtin.assert"]["that"])
        for needle in (
            "opsgate_api_impl in ['python', 'rust']",
            "opsgate_runner_impl in ['python', 'rust']",
            "is regex('^[0-9a-f]{64}$')",
            "(opsgate_api_impl == 'python' and opsgate_runner_impl == 'python') or opsgate_rust_version != ''",
            "opsgate_rust_keep_versions | int >= 1",
        ):
            self.assertIn(needle, that)

    def test_every_new_task_is_named_with_its_file_prefix(self):
        for name in NEW_FILES:
            prefix = name[: -len(".yml")] + " | "
            for task in walk(task_file(name)):
                self.assertTrue(str(task.get("name", "")).startswith(prefix), f"{name}: {task.get('name')}")

    def test_no_task_environment_and_no_become_user(self):
        # Validation commands run through `sudo -u` in argv like
        # app_runtime.yml; nothing goes through environment: or become_user
        # (tests/test_become_environment_secrets.py).
        for name in NEW_FILES:
            for task in walk(task_file(name)):
                self.assertNotIn("environment", task, f"{name}: {task.get('name')}")
                self.assertNotIn("become_user", task, f"{name}: {task.get('name')}")

    def test_validation_commands_pass_only_the_env_file_path(self):
        users = {
            "--version": "{{ control_service_user }}",
            "api": "{{ control_service_user }}",
            "runner": "{{ ops_user }}",
            "check-db": "{{ control_service_user }}",
        }
        seen = set()
        for task in walk(task_file("rust_binary.yml")):
            command = task.get("ansible.builtin.command")
            if not command or command["argv"][0] != "sudo":
                continue
            argv = command["argv"]
            self.assertEqual(argv[1], "-u")
            self.assertEqual(argv[3:5], ["-H", "env"])
            assignments = [a for a in argv[5:] if "=" in a.split("{{")[0]]
            self.assertEqual(
                [a.split("=", 1)[0] for a in assignments][:2], ["HOME", "PATH"], task["name"]
            )
            self.assertLessEqual({a.split("=", 1)[0] for a in assignments}, {"HOME", "PATH", "OPSGATE_ENV_FILE"})
            for assignment in assignments:
                if assignment.startswith("OPSGATE_ENV_FILE="):
                    self.assertIn(assignment, (
                        "OPSGATE_ENV_FILE={{ opsgate_api_env_file }}",
                        "OPSGATE_ENV_FILE={{ opsgate_runner_env_file }}",
                    ))
            self.assertEqual(argv[5 + len(assignments)], "{{ opsgate_rust_binary }}")
            for arg in argv:
                self.assertIsNone(SECRET_WORDS.search(arg), f"{task['name']}: {arg}")
            self.assertEqual(command["chdir"], "/")
            self.assertIs(task["check_mode"], False)
            self.assertIs(task["changed_when"], False)
            key = argv[-1] if argv[-1] in users else argv[-3]
            self.assertEqual(argv[2], users[key], task["name"])
            seen.add(key)
        self.assertEqual(seen, set(users))
        derive = by_name(task_file("rust_binary.yml"), "Derive Rust release paths")["ansible.builtin.set_fact"]
        self.assertIn("opsgate_api_environment.OPSGATE_ENV_FILE", derive["opsgate_api_env_file"])
        self.assertIn("opsgate_runner_environment.OPSGATE_ENV_FILE", derive["opsgate_runner_env_file"])

    def test_download_is_checksum_verified_and_members_checked_before_unpack(self):
        tasks = task_file("rust_binary.yml")
        self.assertEqual(list(DOWNLOADS.findings(tasks, "opsgate_deploy", "rust_binary.yml")), [])
        download = by_name(tasks, "Download the release archive")["ansible.builtin.get_url"]
        self.assertEqual(download["checksum"], "sha256:{{ opsgate_rust_sha256 }}")
        names = [t.get("name", "") for t in walk(tasks)]
        check = names.index("rust_binary | Assert the archive holds only opsgate and its license as regular files")
        unpack = names.index("rust_binary | Unpack the release archive")
        self.assertLess(names.index("rust_binary | Assert the staged archive is the pinned one"), check)
        self.assertLess(check, unpack)
        argv = by_name(tasks, "Unpack the release archive")["ansible.builtin.command"]["argv"]
        self.assertIn("--no-same-owner", argv)
        for task in walk(tasks):
            self.assertFalse({"unarchive", "ansible.builtin.unarchive"} & set(task), task.get("name"))

    def test_installed_version_is_never_replaced(self):
        tasks = task_file("rust_binary.yml")
        stage = by_name(tasks, "Stage the pinned release")
        self.assertIn("not opsgate_rust_dir_stat.stat.exists", stage["when"])
        move = by_name(tasks, "Move the staged version into place")["ansible.builtin.command"]
        self.assertEqual(move["creates"], "{{ opsgate_rust_dir }}")

    def test_rescue_stops_for_rust_and_warns_for_python(self):
        install = by_name(task_file("rust_binary.yml"), "Install and validate the pinned Rust release")
        rescue = install["rescue"]
        remove = by_name(rescue, "Remove the rejected fresh install")
        self.assertEqual(remove["when"], "not (opsgate_rust_dir_stat.stat.exists | default(true))")
        stop = by_name(rescue, "Stop on a rejected Rust release")
        self.assertEqual(stop["when"], "opsgate_api_impl == 'rust' or opsgate_runner_impl == 'rust'")
        warn = by_name(rescue, "Warn about the rejected Rust release and continue with Python")
        self.assertIs(warn["ignore_errors"], True)
        names = [t["name"] for t in rescue]
        self.assertLess(names.index(stop["name"]), names.index(warn["name"]))

    def test_plists_render_the_selected_impl_and_python_copies_always(self):
        tasks = task_file("launchd.yml")
        for unit in ("api", "runner"):
            render = by_name(tasks, f"Render {unit.replace('api', 'API')} plist")
            self.assertEqual(render["vars"], {"opsgate_launchd_render_impl": f"{{{{ opsgate_{unit}_impl }}}}"})
            self.assertEqual(render["ansible.builtin.template"]["src"], f"opsgate.{unit}.launchd.plist.j2")
            copy_task = by_name(tasks, f"Render the Python {unit.replace('api', 'API')} plist copy")
            self.assertEqual(copy_task["vars"], {"opsgate_launchd_render_impl": "python"})
            self.assertNotIn("when", copy_task)
            template = copy_task["ansible.builtin.template"]
            self.assertEqual(template["src"], f"opsgate.{unit}.launchd.plist.j2")
            self.assertEqual(
                template["dest"],
                f"{{{{ opsgate_launchd_python_plist_dir }}}}/{{{{ opsgate_{unit}_launchd_label }}}}.plist",
            )
            self.assertEqual((template["owner"], template["group"], template["mode"]), ("root", "wheel", "0644"))

    def test_python_changes_restart_only_units_that_run_python(self):
        tasks = task_file("launchd.yml")
        for unit, label in (("api", "API"), ("runner", "runner")):
            manage = by_name(tasks, f"Manage {label} launchd state when enabled")
            restart = " ".join(manage["vars"]["opsgate_launchd_force_restart"].split())
            self.assertIn(f"opsgate_{unit}_impl == 'python' and (", restart)
            self.assertTrue(restart.endswith(f"or opsgate_{unit}_env_template.changed }}}}"), restart)

    def test_verify_and_prune(self):
        verify = task_file("verify.yml")
        read = by_name(verify, "Read the live launchd units")
        defaults = role_defaults()
        # At most 30 s by default.
        self.assertEqual((defaults["opsgate_launchd_verify_retries"], defaults["opsgate_launchd_verify_delay"]), (10, 3))
        for task in (read, by_name(verify, "Check the API health endpoint")):
            self.assertEqual(task["retries"], "{{ opsgate_launchd_verify_retries | int }}")
            self.assertEqual(task["delay"], "{{ opsgate_launchd_verify_delay | int }}")
        self.assertIn('launchctl print "system/$label"', read["ansible.builtin.shell"])
        self.assertIn('ps -o comm= -p "$pid"', read["ansible.builtin.shell"])
        self.assertIn("'^args=.* -m opsgate ' ~ item.command ~ '$'", read["until"])
        health = by_name(verify, "Check the API health endpoint")
        self.assertEqual(
            health["ansible.builtin.uri"]["url"], "http://127.0.0.1:{{ opsgate_api_bind_port }}/api/v1/health"
        )
        prune = by_name(task_file("prune.yml"), "Prune old Rust releases")
        self.assertIn("not opsgate_rust_install_failed | bool", prune["when"])
        self.assertIn("not ansible_check_mode", prune["when"])


# --------------------------------------------------------------------------
# ansible-playbook against localhost
# --------------------------------------------------------------------------

RECAP = re.compile(
    r"^localhost\s+:\s+ok=(\d+)\s+changed=(\d+)\s+unreachable=(\d+)\s+failed=(\d+)\s+"
    r"skipped=(\d+)\s+rescued=(\d+)\s+ignored=(\d+)",
    re.M,
)

FAKE_SUDO = """#!{python}
import json, os, sys
argv = sys.argv[1:]
with open({log!r}, "a") as log:
    log.write(json.dumps(argv) + "\\n")
assert argv[0] == "-u" and argv[2] == "-H", argv
os.execvp(argv[3], argv[3:])
"""


def build_archive(path: Path, version: str = VERSION, *, says: str | None = None, check_config: int = 0,
                  check_db: int = 0, members: list[str] | None = None, symlink: str | None = None,
                  salt: str = "") -> str:
    """A fake opsgate release archive; returns its sha256."""

    script = (
        "#!/bin/sh\n"
        f"# {salt}\n"
        'case "$1" in\n'
        f"  --version) echo 'opsgate {says or version} ({COMMIT})' ;;\n"
        f'  check-config) [ {check_config} -eq 0 ] || echo "opsgate check-config $2: configuration error: X" >&2; exit {check_config} ;;\n'
        f"  check-db) exit {check_db} ;;\n"
        "  *) exit 2 ;;\n"
        "esac\n"
    ).encode()
    files = {"opsgate": (script, 0o755), "LICENSE": (b"MIT License\n", 0o644)}
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for name in members if members is not None else ["LICENSE", "opsgate"]:
            data, mode = files.get(name, (b"extra\n", 0o644))
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime, info.uname, info.gname = len(data), mode, 1700000000, "root", "root"
            tar.addfile(info, io.BytesIO(data))
        if symlink:
            info = tarfile.TarInfo(symlink)
            info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
            tar.addfile(info)
    import gzip

    data = gzip.compress(buffer.getvalue(), mtime=0)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not on PATH")
class PlaybookTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name)
        cls.owner = pwd.getpwuid(os.getuid()).pw_name
        cls.group = grp.getgrgid(os.getgid()).gr_name
        cls.env = {
            **os.environ,
            "ANSIBLE_NOCOLOR": "1",
            "ANSIBLE_LOCALHOST_WARNING": "0",
            "ANSIBLE_INVENTORY_UNPARSED_WARNING": "0",
            "ANSIBLE_STDOUT_CALLBACK": "default",
            "ANSIBLE_RETRY_FILES_ENABLED": "0",
            "ANSIBLE_LOCAL_TEMP": str(cls.base / "ansible-local"),
            "ANSIBLE_REMOTE_TEMP": str(cls.base / "ansible-remote"),
            "ANSIBLE_PIPELINING": "1",
            "ANSIBLE_PYTHON_INTERPRETER": sys.executable,
        }

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(dir=self.base))
        self.root = self.work / "libexec/opsgate-rs"
        self.runs = 0

    def base_vars(self, **overrides) -> dict:
        values = {
            "opsgate_rust_install_root": str(self.root),
            "opsgate_rust_owner": self.owner,
            "opsgate_rust_group": self.group,
            "control_service_user": self.owner,
            "ops_user": self.owner,
            "control_service_home_dir": str(self.work),
            "ops_home_dir": str(self.work),
            "opsgate_config_dir": str(self.work / "etc"),
            "opsgate_db_path": str(self.work / "opsgate.sqlite3"),
        }
        values.update(overrides)
        return values

    def play(self, tasks: list[dict], check: bool = False, path_prefix: str | None = None, **overrides) -> dict:
        self.runs += 1
        facts = self.work / f"facts-{self.runs}.json"
        dump = {
            "name": "dump facts",
            "ansible.builtin.copy": {
                "dest": str(facts),
                "mode": "0644",
                "content": (
                    "{{ {'failed': opsgate_rust_install_failed | default(None),"
                    " 'kept': opsgate_rust_versions_kept | default(None),"
                    " 'unknown': opsgate_rust_live_state_unknown | default(None),"
                    " 'api_before': opsgate_api_rust_version_before | default(None),"
                    " 'runner_before': opsgate_runner_rust_version_before | default(None)} | to_json }}"
                ),
            },
            "check_mode": False,
            "changed_when": False,
        }
        # A later vars file overrides an earlier one (play vars would lose
        # against vars_files).
        overrides_file = self.work / f"vars-{self.runs}.yml"
        overrides_file.write_text(yaml.safe_dump(self.base_vars(**overrides)), encoding="utf-8")
        play = {
            "hosts": "localhost",
            "gather_facts": False,
            "vars_files": [str(ROLE / "defaults/main.yml"), str(overrides_file)],
            "tasks": copy.deepcopy(tasks) + [dump],
        }
        path = self.work / f"play-{self.runs}.yml"
        path.write_text(yaml.safe_dump([play], sort_keys=False), encoding="utf-8")
        argv = ["ansible-playbook", "-i", "localhost,", "-c", "local", str(path)]
        if check:
            argv.append("--check")
        env = dict(self.env)
        if path_prefix:
            env["PATH"] = f"{path_prefix}{os.pathsep}{env.get('PATH', '')}"
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env,
                                cwd=ROOT, timeout=600)
        out = result.stdout + result.stderr
        match = RECAP.search(result.stdout)
        self.assertIsNotNone(match, out)
        keys = ("ok", "changed", "unreachable", "failed", "skipped", "rescued", "ignored")
        recap = dict(zip(keys, map(int, match.groups())))
        data = json.loads(facts.read_text()) if facts.exists() else None
        return {"rc": result.returncode, "out": out, "recap": recap, "facts": data}


# --------------------------------------------------------------------------
# Plist renders
# --------------------------------------------------------------------------


class PlistRenderTests(PlaybookTestCase):
    """Both plists for each implementation, rendered by Ansible with the role defaults."""

    def render_all(self) -> dict[str, str]:
        tasks = []
        for unit in ("api", "runner"):
            for impl in ("python", "rust"):
                tasks.append({
                    "name": f"render {unit} {impl}",
                    "ansible.builtin.copy": {
                        "dest": str(self.work / f"{unit}-{impl}.plist"),
                        "mode": "0644",
                        "content": (
                            "{{ lookup('ansible.builtin.template', '"
                            + str(ROLE / f"templates/opsgate.{unit}.launchd.plist.j2")
                            + f"', template_vars={{'opsgate_launchd_render_impl': '{impl}'}}) }}}}"
                        ),
                    },
                })
        defaults = role_defaults()
        result = self.play(
            tasks,
            **{
                # The production values, not the test overrides of base_vars.
                key: defaults[key]
                for key in ("control_service_user", "ops_user", "opsgate_config_dir")
            },
            control_service_home_dir="/Users/control_service_user",
            ops_home_dir="/Users/ops",
            opsgate_rust_version=VERSION,
            opsgate_rust_binary=f"/usr/local/libexec/opsgate-rs/{VERSION}/opsgate",
        )
        self.assertEqual(result["rc"], 0, result["out"])
        return {
            f"{unit}-{impl}": (self.work / f"{unit}-{impl}.plist").read_text()
            for unit in ("api", "runner")
            for impl in ("python", "rust")
        }

    def test_renders_match_the_fixtures(self):
        # The Python fixtures are the plists the role rendered before the
        # switch existed: a role update with both impls python changes no
        # plist and restarts no unit.
        renders = self.render_all()
        for name, text in renders.items():
            with self.subTest(plist=name):
                self.assertEqual(text, (FIXTURES / f"{name}.plist").read_text())

    def test_rust_differs_from_python_only_in_the_command(self):
        renders = self.render_all()
        expected = {
            "api": ("/Users/control_service_user/opsgate", "serve"),
            "runner": ("/Users/ops/opsgate", "runner"),
        }
        for unit, (directory, command) in expected.items():
            with self.subTest(unit=unit):
                python = plistlib.loads(renders[f"{unit}-python"].encode())
                rust = plistlib.loads(renders[f"{unit}-rust"].encode())
                self.assertEqual(
                    python["ProgramArguments"],
                    ["/usr/bin/env", "bash", "-lc", f"cd {directory} && .venv/bin/python -m opsgate {command}"],
                )
                self.assertEqual(
                    rust["ProgramArguments"],
                    ["/usr/bin/env", "bash", "-lc",
                     f"cd {directory} && exec /usr/local/libexec/opsgate-rs/{VERSION}/opsgate {command}"],
                )
                python.pop("ProgramArguments")
                rust.pop("ProgramArguments")
                self.assertEqual(python, rust)
                self.assertIn("OPSGATE_ENV_FILE", rust["EnvironmentVariables"])


# --------------------------------------------------------------------------
# Install and validation (tasks/rust_binary.yml)
# --------------------------------------------------------------------------


class InstallTests(PlaybookTestCase):
    def setUp(self):
        super().setUp()
        self.shim = self.work / "shim"
        self.shim.mkdir()
        self.sudo_log = self.work / "sudo.log"
        sudo = self.shim / "sudo"
        sudo.write_text(FAKE_SUDO.format(python=sys.executable, log=str(self.sudo_log)))
        sudo.chmod(0o755)

    def archive(self, name: str = "release", **kwargs) -> tuple[Path, str]:
        path = self.work / f"{name}.tar.gz"
        return path, build_archive(path, **kwargs)

    def install(self, archive: tuple[Path, str], check: bool = False, **overrides) -> dict:
        path, sha = archive
        values = {
            "opsgate_rust_version": VERSION,
            "opsgate_rust_local_archive": str(path),
            "opsgate_rust_sha256": sha,
        }
        values.update(overrides)
        return self.play(task_file("rust_binary.yml"), check=check, path_prefix=str(self.shim), **values)

    def sudo_calls(self) -> list[list[str]]:
        if not self.sudo_log.exists():
            return []
        return [json.loads(line) for line in self.sudo_log.read_text().splitlines()]

    def installed(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir())

    def test_fresh_install_validates_by_the_versioned_path_and_is_idempotent(self):
        (self.work / "opsgate.sqlite3").write_bytes(b"")
        archive = self.archive()
        result = self.install(archive)
        self.assertEqual(result["rc"], 0, result["out"])
        self.assertFalse(result["facts"]["failed"])
        version_dir = self.root / VERSION
        self.assertEqual(self.installed(), [VERSION])
        self.assertEqual(sorted(p.name for p in version_dir.iterdir()), [".archive-sha256", "LICENSE", "opsgate"])
        self.assertEqual((version_dir / ".archive-sha256").read_text(), archive[1] + "\n")
        self.assertEqual((version_dir / "opsgate").stat().st_mode & 0o7777, 0o755)
        self.assertEqual((version_dir / "LICENSE").stat().st_mode & 0o7777, 0o644)
        self.assertEqual(version_dir.stat().st_mode & 0o7777, 0o755)
        binary = str(version_dir / "opsgate")
        home = str(self.work)
        launchd_path = role_defaults()["opsgate_launchd_path"]
        etc = self.work / "etc"
        self.assertEqual(self.sudo_calls(), [
            ["-u", self.owner, "-H", "env", f"HOME={home}", f"PATH={launchd_path}", binary, "--version"],
            ["-u", self.owner, "-H", "env", f"HOME={home}", f"PATH={launchd_path}",
             f"OPSGATE_ENV_FILE={etc}/opsgate-api.env", binary, "check-config", "api"],
            ["-u", self.owner, "-H", "env", f"HOME={home}", f"PATH={launchd_path}",
             f"OPSGATE_ENV_FILE={etc}/opsgate-runner.env", binary, "check-config", "runner"],
            ["-u", self.owner, "-H", "env", f"HOME={home}", f"PATH={launchd_path}",
             binary, "check-db", "--db", str(self.work / "opsgate.sqlite3")],
        ])

        again = self.install(archive)
        self.assertEqual(again["rc"], 0, again["out"])
        self.assertEqual(again["recap"]["changed"], 0, again["out"])
        self.assertEqual(len(self.sudo_calls()), 8)

    def test_missing_database_is_not_checked(self):
        result = self.install(self.archive())
        self.assertEqual(result["rc"], 0, result["out"])
        self.assertEqual([call[-1] for call in self.sudo_calls()], ["--version", "api", "runner"])

    def test_check_mode_installs_nothing(self):
        result = self.install(self.archive(), check=True)
        self.assertEqual(result["rc"], 0, result["out"])
        self.assertEqual(self.installed(), [])
        self.assertEqual(self.sudo_calls(), [])

    def test_download_with_checksum(self):
        path, sha = self.archive()
        result = self.install((path, sha), opsgate_rust_local_archive="", opsgate_rust_release_url=path.as_uri())
        self.assertEqual(result["rc"], 0, result["out"])
        self.assertEqual(self.installed(), [VERSION])
        bad = self.install((path, "0" * 64), opsgate_rust_local_archive="",
                           opsgate_rust_release_url=path.as_uri(), opsgate_api_impl="rust",
                           opsgate_rust_version="0.3.1")
        self.assertNotEqual(bad["rc"], 0, bad["out"])
        self.assertEqual(self.installed(), [VERSION])

    def test_a_different_archive_for_an_installed_version_is_refused(self):
        self.assertEqual(self.install(self.archive())["rc"], 0)
        other = self.archive("other", salt="rebuilt")
        before = (self.root / VERSION / "opsgate").read_bytes()
        result = self.install(other, opsgate_api_impl="rust")
        self.assertNotEqual(result["rc"], 0, result["out"])
        self.assertIn("is never replaced in place", result["out"])
        self.assertEqual((self.root / VERSION / "opsgate").read_bytes(), before)

    def test_member_refusals_remove_the_fresh_install(self):
        cases = {
            "extra": {"members": ["LICENSE", "opsgate", "README"]},
            "missing": {"members": ["opsgate"]},
            "duplicate": {"members": ["LICENSE", "opsgate", "opsgate"]},
            "nested": {"members": ["LICENSE", "bin/opsgate"]},
            "symlink": {"symlink": "passwd"},
        }
        for name, kwargs in cases.items():
            with self.subTest(case=name):
                result = self.install(self.archive(name, **kwargs), opsgate_runner_impl="rust")
                self.assertNotEqual(result["rc"], 0, result["out"])
                self.assertIn("must hold exactly the regular files opsgate and", result["out"])
                self.assertEqual(self.installed(), [])

    def test_rejected_release_stops_a_rust_deploy(self):
        for overrides in ({"opsgate_api_impl": "rust"}, {"opsgate_runner_impl": "rust"}):
            for kwargs in ({"check_config": 1}, {"says": "0.2.9"}):
                with self.subTest(overrides=overrides, archive=kwargs):
                    result = self.install(self.archive(**kwargs), **overrides)
                    self.assertNotEqual(result["rc"], 0, result["out"])
                    self.assertIn("Nothing was switched", result["out"])
                    self.assertEqual(self.installed(), [])

    def test_rejected_release_warns_and_continues_with_python(self):
        (self.work / "opsgate.sqlite3").write_bytes(b"")
        result = self.install(self.archive(check_db=1))
        self.assertEqual(result["rc"], 0, result["out"])
        self.assertEqual(result["recap"]["ignored"], 1, result["out"])
        self.assertTrue(result["facts"]["failed"])
        self.assertIn("WARNING: opsgate 0.3.0 failed installation or validation", result["out"])
        self.assertEqual(self.installed(), [])

    def test_installed_version_is_kept_when_it_is_rejected_later(self):
        self.assertEqual(self.install(self.archive())["rc"], 0)
        (self.work / "opsgate.sqlite3").write_bytes(b"")
        # Same archive; the database now fails the check.
        path = self.work / "release.tar.gz"
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        script = (self.root / VERSION / "opsgate")
        script.write_text(script.read_text().replace("check-db) exit 0", "check-db) exit 1"))
        result = self.install((path, sha))
        self.assertEqual(result["rc"], 0, result["out"])
        self.assertTrue(result["facts"]["failed"])
        self.assertEqual(self.installed(), [VERSION])


# --------------------------------------------------------------------------
# Live verification (tasks/verify.yml)
# --------------------------------------------------------------------------

FAKE_LAUNCHCTL = """#!{python}
import pathlib, sys
state = pathlib.Path({state!r})
assert sys.argv[1] == "print", sys.argv
label = sys.argv[2].removeprefix("system/")
unit = state / label
failure = state / (label + ".rc")
if failure.exists():
    sys.stderr.write("launchctl failed\\n")
    sys.exit(int(failure.read_text()))
if not unit.exists():
    sys.stderr.write("Could not find service\\n")
    sys.exit(113)
print("system/" + label + " = {{")
print("\\tactive count = 1")
print(unit.read_text(), end="")
print("\\tendpoints = {{")
print("\\t\\tstate = active")
print("\\t}}")
print("}}")
"""

FAKE_PS = """#!{python}
import pathlib, sys
state = pathlib.Path({state!r})
args = sys.argv[1:]
assert args[0] == "-o" and args[2] == "-p", args
field = args[1].rstrip("=")
path = state / ("pid-" + args[3] + "." + field)
if not path.exists():
    sys.exit(1)
print(path.read_text())
"""


class HealthHandler(BaseHTTPRequestHandler):
    body = b'{"status": "ok", "db": "ok"}'

    def do_GET(self):  # noqa: N802 (http.server API)
        if self.path != "/api/v1/health":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):
        pass


class VerifyTests(PlaybookTestCase):
    API = "de.wersdoerfer.opsgate.api"
    RUNNER = "de.wersdoerfer.opsgate.runner"

    def setUp(self):
        super().setUp()
        self.state = self.work / "launchd"
        self.state.mkdir()
        self.shim = self.work / "shim"
        self.shim.mkdir()
        for name, template in (("launchctl", FAKE_LAUNCHCTL), ("ps", FAKE_PS)):
            script = self.shim / name
            script.write_text(template.format(python=sys.executable, state=str(self.state)))
            script.chmod(0o755)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), HealthHandler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.binary = f"{self.root}/{VERSION}/opsgate"

    def unit(self, label: str, pid: int | None, comm: str = "", args: str = "", state: str = "running") -> None:
        lines = [f"\tstate = {state}"]
        if pid is not None:
            lines.append(f"\tpid = {pid}")
            (self.state / f"pid-{pid}.comm").write_text(comm)
            (self.state / f"pid-{pid}.args").write_text(args)
        (self.state / label).write_text("\n".join(lines) + "\n")

    def python_unit(self, label: str, pid: int, command: str) -> None:
        self.unit(label, pid, "bash", f"bash -lc cd /Users/x/opsgate && .venv/bin/python -m opsgate {command}")

    def rust_unit(self, label: str, pid: int, command: str, binary: str | None = None) -> None:
        binary = binary or self.binary
        self.unit(label, pid, binary, f"{binary} {command}")

    def verify(self, **overrides) -> dict:
        tasks = [by_name(task_file("rust_binary.yml"), "Derive Rust release paths")] + task_file("verify.yml")
        values = {
            "opsgate_rust_version": VERSION,
            "opsgate_api_bind_port": self.server.server_address[1],
            "opsgate_launchd_manage_state": True,
            "opsgate_launchd_start_services": True,
            "opsgate_launchd_verify_retries": 2,
            "opsgate_launchd_verify_delay": 0,
        }
        values.update(overrides)
        return self.play(tasks, path_prefix=str(self.shim), **values)

    def test_selected_implementations_pass(self):
        self.rust_unit(self.API, 101, "serve")
        self.python_unit(self.RUNNER, 102, "runner")
        result = self.verify(opsgate_api_impl="rust")
        self.assertEqual(result["rc"], 0, result["out"])
        self.python_unit(self.API, 103, "serve")
        self.rust_unit(self.RUNNER, 104, "runner")
        result = self.verify(opsgate_runner_impl="rust")
        self.assertEqual(result["rc"], 0, result["out"])

    def test_wrong_or_stopped_units_fail(self):
        cases = {
            "python runs, rust selected": (lambda: self.python_unit(self.API, 101, "serve"), {"opsgate_api_impl": "rust"}),
            "other version runs": (
                lambda: self.rust_unit(self.API, 101, "serve", f"{self.root}/0.2.9/opsgate"),
                {"opsgate_api_impl": "rust"},
            ),
            "rust runs, python selected": (lambda: self.rust_unit(self.API, 101, "serve"), {}),
            "wrong command": (lambda: self.rust_unit(self.API, 101, "runner"), {"opsgate_api_impl": "rust"}),
            "not running": (lambda: self.unit(self.API, None, state="not running"), {}),
            "not loaded": (lambda: (self.state / self.API).unlink(missing_ok=True), {}),
        }
        for name, (arrange, overrides) in cases.items():
            with self.subTest(case=name):
                self.python_unit(self.API, 100, "serve")
                self.python_unit(self.RUNNER, 102, "runner")
                arrange()
                result = self.verify(**overrides)
                self.assertNotEqual(result["rc"], 0, result["out"])
                self.assertIn("does not run the selected implementation", result["out"])

    def test_unhealthy_api_fails(self):
        self.python_unit(self.API, 101, "serve")
        self.python_unit(self.RUNNER, 102, "runner")
        HealthHandler.body = b'{"status": "degraded"}'
        self.addCleanup(setattr, HealthHandler, "body", b'{"status": "ok", "db": "ok"}')
        result = self.verify()
        self.assertNotEqual(result["rc"], 0, result["out"])
        self.assertIn("Check the API health endpoint", result["out"])

    def test_incomplete_readings_fail_a_managed_unit_and_block_prune(self):
        def ps_fails():
            self.rust_unit(self.API, 101, "serve")
            (self.state / "pid-101.comm").unlink()

        def launchctl_fails():
            self.rust_unit(self.API, 101, "serve")
            (self.state / f"{self.API}.rc").write_text("5")

        def running_without_pid():
            self.unit(self.API, None)

        cases = {"ps fails": ps_fails, "launchctl fails": launchctl_fails, "running without pid": running_without_pid}
        for name, arrange in cases.items():
            with self.subTest(case=name):
                for path in self.state.iterdir():
                    path.unlink()
                self.python_unit(self.RUNNER, 102, "runner")
                arrange()
                managed = self.verify(opsgate_api_impl="rust")
                self.assertNotEqual(managed["rc"], 0, managed["out"])
                self.assertIn("does not run the selected implementation", managed["out"])

                # Not managed: only read, and the unknown reading keeps every
                # release, including the one the API may still run.
                if self.root.exists():
                    shutil.rmtree(self.root)
                for index, version in enumerate(("0.1.0", "0.2.0", VERSION, "0.3.1")):
                    (self.root / version).mkdir(parents=True)
                    os.utime(self.root / version, (1_600_000_000 + index, 1_600_000_000 + index))
                result = self.play(
                    [by_name(task_file("rust_binary.yml"), "Derive Rust release paths")]
                    + task_file("verify.yml") + task_file("prune.yml"),
                    path_prefix=str(self.shim),
                    opsgate_rust_version="0.3.1",
                    opsgate_rust_keep_versions=1,
                    opsgate_api_bind_port=self.server.server_address[1],
                    opsgate_launchd_verify_retries=1,
                    opsgate_launchd_verify_delay=0,
                )
                self.assertEqual(result["rc"], 0, result["out"])
                self.assertTrue(result["facts"]["unknown"])
                self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["0.1.0", "0.2.0", VERSION, "0.3.1"])

    def test_units_that_are_not_managed_are_only_read(self):
        self.rust_unit(self.API, 101, "serve", f"{self.root}/0.2.9/opsgate")
        result = self.verify(opsgate_launchd_manage_state=False)
        self.assertEqual(result["rc"], 0, result["out"])
        self.assertNotIn("Check the API health endpoint] ***\nok", result["out"])


# --------------------------------------------------------------------------
# Previous versions (tasks/launchd.yml) and prune (tasks/prune.yml)
# --------------------------------------------------------------------------

PREVIOUS_TASKS = (
    "launchd | Read the plists as they are before this run",
    "launchd | Derive the Rust versions the plists selected so far",
    "launchd | Check the Rust versions the plists selected so far",
    "launchd | Remember the Rust version a unit moves away from",
)


def plist(root: Path, version: str | None, command: str) -> str:
    if version is None:
        line = f"cd /Users/ops/opsgate &amp;&amp; .venv/bin/python -m opsgate {command}"
    else:
        line = f"cd /Users/ops/opsgate &amp;&amp; exec {root}/{version}/opsgate {command}"
    return f"<plist><dict><key>ProgramArguments</key><array><string>{line}</string></array></dict></plist>\n"


def live(*units: tuple[str, str | None], rc: int = 0) -> dict:
    results = []
    for name, comm in units:
        lines = ["loaded=yes", "state=running", "pid=42"]
        if comm is not None:
            lines.append(f"comm={comm}")
        results.append({"rc": rc, "stdout_lines": lines, "item": {"unit": name}})
    return {"results": results}


class PreviousAndPruneTests(PlaybookTestCase):
    def setUp(self):
        super().setUp()
        self.api_plist = self.work / "api.plist"
        self.runner_plist = self.work / "runner.plist"

    def previous(self, api: str | None, runner: str | None, **overrides) -> dict:
        self.api_plist.write_text(plist(self.root, api, "serve"))
        self.runner_plist.write_text(plist(self.root, runner, "runner"))
        tasks = [by_name(task_file("launchd.yml"), name.split(" | ", 1)[1]) for name in PREVIOUS_TASKS]
        tasks.insert(0, by_name(task_file("rust_binary.yml"), "Derive Rust release paths"))
        result = self.play(
            tasks,
            opsgate_api_launchd_plist_path=str(self.api_plist),
            opsgate_runner_launchd_plist_path=str(self.runner_plist),
            **overrides,
        )
        self.assertEqual(result["rc"], 0, result["out"])
        return result

    def make_versions(self, *versions: str) -> None:
        for index, version in enumerate(versions):
            directory = self.root / version
            directory.mkdir(parents=True)
            (directory / "opsgate").write_text("x")
            stamp = 1_600_000_000 + index * 1000
            os.utime(directory, (stamp, stamp))

    def previous_files(self) -> dict[str, str]:
        return {p.name: p.read_text() for p in sorted(self.root.glob(".previous-*"))}

    def test_versions_before_are_read_from_the_plists(self):
        self.make_versions("0.3.0", "0.3.1")
        result = self.previous("0.3.0", None, opsgate_rust_version="0.3.0", opsgate_api_impl="rust")
        self.assertEqual((result["facts"]["api_before"], result["facts"]["runner_before"]), ("0.3.0", ""))
        self.assertEqual(self.previous_files(), {})  # unchanged selection

    def test_moving_away_records_the_previous_version_per_unit(self):
        self.make_versions("0.3.0", "0.3.1")
        # API to a new version, runner to Python.
        self.previous("0.3.0", "0.3.0", opsgate_rust_version="0.3.1", opsgate_api_impl="rust")
        self.assertEqual(self.previous_files(), {".previous-api": "0.3.0\n", ".previous-runner": "0.3.0\n"})

    def test_missing_plists_and_removed_versions_record_nothing(self):
        self.make_versions("0.3.1")
        self.previous("0.2.0", None, opsgate_rust_version="0.3.1", opsgate_api_impl="rust")
        self.assertEqual(self.previous_files(), {})
        self.api_plist.unlink()
        tasks = [by_name(task_file("launchd.yml"), name.split(" | ", 1)[1]) for name in PREVIOUS_TASKS]
        tasks.insert(0, by_name(task_file("rust_binary.yml"), "Derive Rust release paths"))
        result = self.play(tasks, opsgate_api_launchd_plist_path=str(self.work / "absent.plist"),
                           opsgate_runner_launchd_plist_path=str(self.work / "absent2.plist"))
        self.assertEqual(result["rc"], 0, result["out"])
        self.assertEqual((result["facts"]["api_before"], result["facts"]["runner_before"]), ("", ""))

    def prune(self, opsgate_live: dict | None, failed: bool = False, **overrides) -> dict:
        tasks = [by_name(task_file("rust_binary.yml"), "Derive Rust release paths")]
        if failed:
            tasks.append({"name": "reject the release", "ansible.builtin.set_fact": {"opsgate_rust_install_failed": True}})
        tasks += task_file("prune.yml")
        values = {"opsgate_rust_version": "0.3.4", "opsgate_rust_keep_versions": 2}
        if opsgate_live is not None:
            values["opsgate_live"] = opsgate_live
        values.update(overrides)
        result = self.play(tasks, **values)
        self.assertEqual(result["rc"], 0, result["out"])
        return result

    def remaining(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir() if not p.name.startswith("."))

    def test_prune_keeps_pinned_live_previous_and_newest(self):
        self.make_versions("0.1.0", "0.2.0", "0.3.0", "0.3.1", "0.3.2", "0.3.3", "0.3.4")
        (self.root / "notes").mkdir()
        (self.root / ".staging").mkdir()
        (self.root / "link").symlink_to(self.root / "0.1.0")
        (self.root / ".previous-api").write_text("0.2.0\n")
        (self.root / ".previous-runner").write_text("0.3.0\n")
        self.prune(live(("api", str(self.root / "0.3.4/opsgate")), ("runner", str(self.root / "0.3.1/opsgate"))))
        # pinned 0.3.4 (also live), runner live 0.3.1, previous 0.2.0 and
        # 0.3.0, newest two 0.3.4 and 0.3.3; 0.1.0 and 0.3.2 go. Hidden
        # entries, links and directories not named like a version stay.
        self.assertEqual(self.remaining(), ["0.2.0", "0.3.0", "0.3.1", "0.3.3", "0.3.4", "link", "notes"])
        self.assertTrue((self.root / ".staging").is_dir())

    def test_prune_keeps_everything_on_unknown_live_state(self):
        versions = ("0.1.0", "0.2.0", "0.3.3", "0.3.4")
        cases = {
            "not read": None,
            "one unit": live(("api", None)),
            "read failed": live(("api", None), ("runner", None), rc=1),
            "unversioned executable": live(("api", str(self.root / "current/opsgate")), ("runner", None)),
        }
        for name, state in cases.items():
            with self.subTest(case=name):
                if self.root.exists():
                    shutil.rmtree(self.root)
                self.make_versions(*versions)
                result = self.prune(state)
                self.assertTrue(result["facts"]["unknown"])
                self.assertEqual(result["recap"]["ignored"], 1, result["out"])
                self.assertEqual(self.remaining(), list(versions))

    def test_python_units_and_a_rejected_release_prune_nothing_beyond_the_rules(self):
        self.make_versions("0.1.0", "0.2.0", "0.3.3", "0.3.4")
        self.prune(live(("api", None), ("runner", None)), failed=True)
        self.assertEqual(self.remaining(), ["0.1.0", "0.2.0", "0.3.3", "0.3.4"])
        # Both units on Python: only the pinned and the newest versions stay.
        result = self.prune(live(("api", "/usr/bin/bash"), ("runner", None)))
        self.assertFalse(result["facts"]["unknown"])
        self.assertEqual(self.remaining(), ["0.3.3", "0.3.4"])


if __name__ == "__main__":
    unittest.main()
