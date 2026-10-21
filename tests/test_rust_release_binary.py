"""rust_release_binary: install, pin and prune pinned Rust release binaries.

Static checks on the task files, unit tests of the decision filters
(``plugins/filter/rust_release.py``) and ``ansible-playbook`` runs against
localhost with locally built fake release archives (a shell script named like
the crate that prints its version) in a temporary install root
(rust/PLAN-foundation.md 6.2, F3).

The role targets Linux (GNU coreutils). On macOS the playbook runs need GNU
``mv`` (Homebrew coreutils' ``gmv``); the test puts it first on PATH as
``mv`` and skips the playbook runs when it is missing.
"""

from __future__ import annotations

import base64
import grp
import hashlib
import importlib.util
import io
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/rust_release_binary"
TASKS = ROLE / "tasks"
FQCN = "local.ops_library.rust_release_binary"
NAME = "demo-tool"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FILTERS = _load("rust_release_filters", ROOT / "plugins/filter/rust_release.py")
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


# --------------------------------------------------------------------------
# Static checks
# --------------------------------------------------------------------------


class StaticTaskTests(unittest.TestCase):
    FILES = ("main.yml", "common.yml", "install.yml", "pin.yml", "prune.yml")

    def test_every_task_is_named_with_its_file_prefix(self):
        # ansible-lint name[prefix]: "<task file stem> | " outside main.yml.
        for name in self.FILES:
            prefix = "rust_release_binary | " if name == "main.yml" else name[: -len(".yml")] + " | "
            for task in walk(task_file(name)):
                self.assertTrue(str(task.get("name", "")).startswith(prefix), f"{name}: {task}")

    def test_no_task_environment_and_no_shell(self):
        # The helper handles no secrets; nothing goes through environment:
        # (tests/test_become_environment_secrets.py) or a shell.
        for name in self.FILES:
            for task in walk(task_file(name)):
                self.assertNotIn("environment", task, f"{name}: {task.get('name')}")
                for module in ("shell", "ansible.builtin.shell", "raw", "ansible.builtin.raw"):
                    self.assertNotIn(module, task, f"{name}: {task.get('name')}")

    def test_only_the_version_check_becomes_another_user(self):
        for name in self.FILES:
            for task in walk(task_file(name)):
                if "become_user" in task:
                    self.assertTrue(task["name"].endswith("Read the version of the installed binary"), task["name"])

    def test_downloads_are_checksum_verified(self):
        for name in self.FILES:
            self.assertEqual(list(DOWNLOADS.findings(task_file(name), "rust_release_binary", name)), [], name)
        download = by_name(task_file("install.yml"), "Download the release archive")
        self.assertEqual(download["ansible.builtin.get_url"]["checksum"], "sha256:{{ rust_release_binary_sha256 }}")

    def test_archive_members_are_checked_before_extraction(self):
        tasks = list(walk(task_file("install.yml")))
        names = [t.get("name", "") for t in tasks]
        check = next(i for i, n in enumerate(names) if n.endswith("as regular files"))
        unpack = next(i for i, n in enumerate(names) if n.endswith("Unpack the release archive"))
        self.assertLess(check, unpack)
        that = "\n".join(tasks[check]["ansible.builtin.assert"]["that"])
        self.assertIn("reject('match', '-')", that)
        self.assertIn("| sort ==", that)
        argv = tasks[unpack]["ansible.builtin.command"]["argv"]
        self.assertIn("--no-same-owner", argv)

    def test_install_moves_into_place_atomically_and_never_prunes(self):
        tasks = task_file("install.yml")
        move = by_name(tasks, "Move the staged version into place")
        self.assertEqual(move["ansible.builtin.command"]["argv"][:2], ["mv", "--no-target-directory"])
        text = (TASKS / "install.yml").read_text(encoding="utf-8")
        self.assertNotIn("prune", "\n".join(t.get("name", "") for t in walk(tasks)).lower())
        self.assertNotIn(".pins/", text)

    def test_rescue_removes_only_a_fresh_install_of_this_include(self):
        install = by_name(task_file("install.yml"), "Install and validate the pinned release")
        remove = by_name(install["rescue"], "Remove the rejected fresh install")
        self.assertEqual(
            remove["when"], ["_rust_release_binary_paths_ok | bool", "_rust_release_binary_fresh | bool"]
        )
        reset = task_file("install.yml")[0]
        self.assertTrue(reset["name"].endswith("Reset the install state"))
        self.assertIs(reset["ansible.builtin.set_fact"]["_rust_release_binary_fresh"], False)
        self.assertIs(reset["ansible.builtin.set_fact"]["_rust_release_binary_paths_ok"], False)

    def test_prune_honours_pins_protect_and_unknown_state(self):
        text = (TASKS / "prune.yml").read_text(encoding="utf-8")
        for needle in (
            "rust_release_prune_plan",
            "_rust_release_binary_pin_files.skipped_paths",
            "_rust_release_binary_version_dirs.skipped_paths",
            "rust_release_binary_protect",
            "rust_release_binary_live_state_unknown",
            "rust_release_binary_failed_names",
            "/.pins",
        ):
            self.assertIn(needle, text)
        remove = by_name(task_file("prune.yml"), "Remove the versions no one keeps")
        self.assertEqual(remove["when"], "_rust_release_binary_prune_blocked | length == 0")

    def test_pin_writes_previous_before_current(self):
        names = [t.get("name", "") for t in walk(task_file("pin.yml"))]
        self.assertLess(
            names.index("pin | Write the previous pin"),
            names.index("pin | Write the current pin"),
        )
        self.assertLess(
            names.index("pin | Write the previous pin"),
            names.index("pin | Remove the current pin"),
        )

    def test_defaults_document_every_input(self):
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
        readme = (ROLE / "README.md").read_text(encoding="utf-8")
        for key in defaults:
            self.assertIn(key, readme, key)
        self.assertEqual(defaults["rust_release_binary_owner"], "root")
        self.assertEqual(defaults["rust_release_binary_group"], "root")
        self.assertTrue(defaults["rust_release_binary_fail_hard"])
        self.assertEqual(defaults["rust_release_binary_keep_versions"], 3)


# --------------------------------------------------------------------------
# Decision filters
# --------------------------------------------------------------------------


def entry(path: str, mtime: float, isdir: bool = True, islnk: bool = False) -> dict:
    return {"path": path, "mtime": mtime, "isdir": isdir, "islnk": islnk}


def pin(path: str, content, isreg: bool = True) -> dict:
    return {"path": path, "isreg": isreg, "content": content}


class PinPlanTests(unittest.TestCase):
    plan = staticmethod(FILTERS.rust_release_pin_plan)

    def test_first_pin_has_no_previous(self):
        self.assertEqual(self.plan(None, None, "present", "1.0.0"), {"current": "1.0.0", "previous": None, "error": ""})

    def test_new_version_moves_the_current_pin_to_previous(self):
        self.assertEqual(self.plan("1.0.0\n", None, "present", "2.0.0")["previous"], "1.0.0")
        self.assertEqual(self.plan("2.0.0\n", "1.0.0\n", "present", "1.0.0"), {"current": "1.0.0", "previous": "2.0.0", "error": ""})

    def test_same_version_moves_nothing(self):
        self.assertEqual(self.plan("2.0.0\n", "1.0.0\n", "present", "2.0.0"), {"current": "2.0.0", "previous": "1.0.0", "error": ""})

    def test_absent_keeps_the_removed_version_as_previous(self):
        self.assertEqual(self.plan("2.0.0\n", "1.0.0\n", "absent"), {"current": None, "previous": "2.0.0", "error": ""})
        self.assertEqual(self.plan(None, "1.0.0\n", "absent"), {"current": None, "previous": "1.0.0", "error": ""})
        self.assertEqual(self.plan("2.0.0\n", "1.0.0\n", "absent", keep_previous=False), {"current": None, "previous": None, "error": ""})

    def test_previous_override(self):
        self.assertEqual(self.plan(None, None, "present", "2.0.0", "1.0.0")["previous"], "1.0.0")
        # Equal to the new current version: ignored, the automatic move wins.
        self.assertEqual(self.plan("1.5.0\n", None, "present", "2.0.0", "2.0.0")["previous"], "1.5.0")

    def test_unreadable_pins_are_errors(self):
        for current, previous in (("garbage\n", None), ("1.0.0\n2.0.0\n", None), (None, ""), ("", None)):
            self.assertTrue(self.plan(current, previous, "present", "3.0.0")["error"], (current, previous))
        self.assertTrue(self.plan(None, None, "present", "v1")["error"])
        self.assertTrue(self.plan(None, None, "maybe", "1.0.0")["error"])
        self.assertTrue(self.plan(None, None, "present", "1.0.0", "../x")["error"])

    def test_pin_content_is_one_line(self):
        self.assertEqual(FILTERS.rust_release_pin_content("1.2.3-rc.1"), "1.2.3-rc.1\n")
        with self.assertRaises(Exception):
            FILTERS.rust_release_pin_content("1.2")


class PrunePlanTests(unittest.TestCase):
    ROOTS = ["/opt/demo-tool", "/srv/real/demo-tool"]

    def plan(self, versions, pins=(), protect=(), keep=1):
        entries = [entry(f"/opt/demo-tool/{v}", m) for v, m in versions]
        return FILTERS.rust_release_prune_plan(entries, list(pins), list(protect), keep, self.ROOTS, NAME)

    def test_keeps_newest_by_mtime(self):
        plan = self.plan([("1.0.0", 1), ("3.0.0", 3), ("2.0.0", 2)], keep=2)
        self.assertEqual(plan["versions"], ["3.0.0", "2.0.0", "1.0.0"])
        self.assertEqual(plan["remove"], ["1.0.0"])
        # mtime, not version order, decides
        self.assertEqual(self.plan([("9.0.0", 1), ("1.0.0", 5)])["remove"], ["9.0.0"])
        # ties by version name, descending, deterministic
        self.assertEqual(self.plan([("1.0.0", 1), ("2.0.0", 1)])["remove"], ["1.0.0"])

    def test_pins_previous_and_protect_are_kept(self):
        versions = [("1.0.0", 1), ("2.0.0", 2), ("3.0.0", 3), ("4.0.0", 4), ("5.0.0", 5)]
        pins = [pin("/opt/demo-tool/.pins/a", "1.0.0\n"), pin("/opt/demo-tool/.pins/a.previous", "2.0.0\n")]
        plan = self.plan(versions, pins, ["3.0.0"])
        self.assertEqual(plan["keep"], ["5.0.0", "3.0.0", "2.0.0", "1.0.0"])
        self.assertEqual(plan["remove"], ["4.0.0"])
        self.assertEqual(plan["unknown"], [])

    def test_protect_executable_paths(self):
        versions = [("1.0.0", 1), ("2.0.0", 2), ("3.0.0", 3), ("4.0.0", 4)]
        protect = [
            "/opt/demo-tool/1.0.0/demo-tool",
            "/srv/real/demo-tool/2.0.0/demo-tool-apt (deleted)",
            "/usr/bin/python3.12",  # a Python process contributes nothing
        ]
        plan = self.plan(versions, protect=protect)
        self.assertEqual(plan["protected"], ["1.0.0", "2.0.0"])
        self.assertEqual(plan["remove"], ["3.0.0"])

    def test_uninterpretable_live_state_removes_nothing(self):
        versions = [("1.0.0", 1), ("2.0.0", 2)]
        for protect in (
            ["/opt/demo-tool/.staging-1.0.0/tree/demo-tool"],
            ["/opt/demo-tool/1.0.0/sub/demo-tool"],
            ["/opt/demo-tool/1.0/demo-tool"],
            ["/opt/demo-tool/../demo-tool/1.0.0/demo-tool"],
            ["/opt//demo-tool/1.0.0/demo-tool"],
            ["/elsewhere/1.0.0/demo-tool"],  # the binary outside every root spelling
            ["1.0.0/demo-tool"],
            [""],
            [None],
            [" 1.0.0"],
        ):
            plan = self.plan(versions, protect=protect)
            self.assertEqual(plan["remove"], [], protect)
            self.assertTrue(plan["unknown"], protect)
            self.assertEqual(plan["keep"], ["2.0.0", "1.0.0"])
        for pins in (
            [pin("/opt/demo-tool/.pins/a", "garbage")],
            [pin("/opt/demo-tool/.pins/a", None)],
            [pin("/opt/demo-tool/.pins/sub", None, isreg=False)],
            [pin("/opt/demo-tool/.pins/a", "")],
        ):
            plan = self.plan(versions, pins=pins)
            self.assertEqual(plan["remove"], [], pins)
            self.assertTrue(plan["unknown"], pins)

    def test_only_real_version_directories_are_candidates(self):
        entries = [
            entry("/opt/demo-tool/1.0.0", 1),
            entry("/opt/demo-tool/2.0.0", 2, isdir=False, islnk=True),
            entry("/opt/demo-tool/notes", 0),
            entry("/opt/demo-tool/01.0.0", 0),
            entry("/opt/demo-tool/3.0.0", 3),
        ]
        plan = FILTERS.rust_release_prune_plan(entries, [], [], 1, self.ROOTS, NAME)
        self.assertEqual(plan["versions"], ["3.0.0", "1.0.0"])
        self.assertEqual(plan["remove"], ["1.0.0"])

    def test_invalid_keep_versions(self):
        for keep in (0, -1, "2", True, None):
            with self.assertRaises(Exception):
                FILTERS.rust_release_prune_plan([], [], [], keep, self.ROOTS, NAME)

    def test_pin_records_from_slurp_results(self):
        results = [
            {"item": {"path": "/r/.pins/a", "isreg": True, "islnk": False}, "content": base64.b64encode(b"1.0.0\n").decode()},
            {"item": {"path": "/r/.pins/d", "isreg": False, "islnk": False}, "skipped": True},
            {"item": {"path": "/r/.pins/u", "isreg": True, "islnk": False}, "failed": True, "msg": "denied"},
        ]
        self.assertEqual(
            FILTERS.rust_release_pin_records(results),
            [
                {"path": "/r/.pins/a", "isreg": True, "content": "1.0.0\n"},
                {"path": "/r/.pins/d", "isreg": False, "content": None},
                {"path": "/r/.pins/u", "isreg": True, "content": None},
            ],
        )

    def test_version_and_consumer_grammar(self):
        ok = FILTERS.rust_release_version_ok
        for good in ("0.1.0", "1.20.3", "1.0.0-rc.1", "1.0.0-alpha-2"):
            self.assertTrue(ok(good), good)
        for bad in ("", "1.0", "v1.0.0", "01.0.0", "1.0.0+build", "1.0.0-", "../1.0.0", "1.0.0\n", None, 1):
            self.assertFalse(ok(bad), bad)
        self.assertTrue(FILTERS.rust_release_consumer_ok("metrics_endpoint-2"))
        for bad in ("", "a.previous", "A", "-a", "a/b", "a\n"):
            self.assertFalse(FILTERS.rust_release_consumer_ok(bad), bad)
        self.assertTrue(FILTERS.rust_release_name_ok("software-live-apt"))
        for bad in ("", "Tool", "a_b", "a\n", "../a"):
            self.assertFalse(FILTERS.rust_release_name_ok(bad), bad)
        self.assertTrue(FILTERS.rust_release_sha256_ok("a" * 64))
        for bad in ("A" * 64, "a" * 63, "a" * 64 + "\n", ""):
            self.assertFalse(FILTERS.rust_release_sha256_ok(bad), bad)
        for good in ("/opt/metrics-httpd", "/opt/software-live/releases", "/var/x@y/a+b"):
            self.assertTrue(FILTERS.rust_release_root_ok(good), good)
        for bad in ("/", "", "opt/x", "/opt/", "/opt//x", "/opt/./x", "/opt/../x", "/opt/x\n", "/opt/a b"):
            self.assertFalse(FILTERS.rust_release_root_ok(bad), bad)


# --------------------------------------------------------------------------
# ansible-playbook against localhost
# --------------------------------------------------------------------------


def _gnu_mv_dir(base: Path) -> Path | None:
    """A PATH entry whose `mv` is GNU mv, or None when the system mv is GNU."""

    probe = subprocess.run(["mv", "--version"], capture_output=True, text=True)
    if probe.returncode == 0 and "GNU" in probe.stdout:
        return None
    gmv = shutil.which("gmv")
    if gmv is None:
        raise unittest.SkipTest("GNU mv (gmv) not found; the role targets GNU coreutils")
    shim = base / "gnu-bin"
    shim.mkdir()
    (shim / "mv").symlink_to(gmv)
    return shim


def build_archive(path: Path, version: str, *, says: str | None = None, exit_code: int = 0,
                  members: list[str] | None = None, symlink: str | None = None,
                  directory: str | None = None, salt: str = "") -> str:
    """A fake release archive; returns its sha256."""

    script = (
        "#!/bin/sh\n"
        f"# {salt}\n"
        f"echo '{NAME} {says or version} (0123456789abcdef0123456789abcdef01234567)'\n"
        f"exit {exit_code}\n"
    ).encode()
    files = {NAME: (script, 0o755), "LICENSE": (b"MIT License\n", 0o644)}
    names = members if members is not None else [NAME, "LICENSE"]
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name in names:
            data, mode = files.get(name, (b"extra\n", 0o644))
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), mode, 1700000000
            tar.addfile(info, io.BytesIO(data))
        if symlink:
            info = tarfile.TarInfo(symlink)
            info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
            tar.addfile(info)
        if directory:
            info = tarfile.TarInfo(directory)
            info.type, info.mode = tarfile.DIRTYPE, 0o755
            tar.addfile(info)
    path.write_bytes(buffer.getvalue())
    return hashlib.sha256(buffer.getvalue()).hexdigest()


RECAP = re.compile(
    r"^localhost\s+:\s+ok=(\d+)\s+changed=(\d+)\s+unreachable=(\d+)\s+failed=(\d+)\s+"
    r"skipped=(\d+)\s+rescued=(\d+)\s+ignored=(\d+)",
    re.M,
)


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not on PATH")
class PlaybookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name)
        collections = cls.base / "collections/ansible_collections/local"
        collections.mkdir(parents=True)
        (collections / "ops_library").symlink_to(ROOT)
        path = os.environ.get("PATH", "")
        shim = _gnu_mv_dir(cls.base)
        if shim is not None:
            path = f"{shim}{os.pathsep}{path}"
        cls.env = {
            **os.environ,
            "PATH": path,
            "ANSIBLE_COLLECTIONS_PATH": str(cls.base / "collections"),
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
        cls.owner = pwd.getpwuid(os.getuid()).pw_name
        cls.group = grp.getgrgid(os.getgid()).gr_name

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(dir=self.base))
        self.root = self.work / "opt" / NAME
        self.archives: dict[str, tuple[Path, str]] = {}
        self.runs = 0

    # -- helpers -----------------------------------------------------------

    def archive(self, version: str, key: str | None = None, **kwargs) -> tuple[Path, str]:
        key = key or version
        path = self.work / f"{key}.tar.gz"
        sha = build_archive(path, version, **kwargs)
        self.archives[key] = (path, sha)
        return path, sha

    def include(self, tasks_from: str, **params) -> dict:
        return {
            "name": f"rust_release_binary {tasks_from}",
            "ansible.builtin.include_role": {"name": FQCN, "tasks_from": tasks_from},
            "vars": {f"rust_release_binary_{k}": v for k, v in params.items()},
        }

    def install(self, version: str, key: str | None = None, **params) -> dict:
        path, sha = self.archives.get(key or version) or self.archive(version, key)
        args = {"version": version, "local_archive": str(path), "sha256": sha}
        args.update(params)
        return self.include("install", **args)

    def pin(self, consumer: str, version: str = "", **params) -> dict:
        return self.include("pin", consumer=consumer, version=version, **params)

    def prune(self, **params) -> dict:
        return self.include("prune", **params)

    def play(self, *tasks: dict, check: bool = False) -> dict:
        """Run tasks; returns rc, output, recap counters and the role's facts."""

        self.runs += 1
        facts = self.work / f"facts-{self.runs}.json"
        dump = {
            "name": "dump facts",
            "ansible.builtin.copy": {
                "dest": str(facts),
                "mode": "0644",
                "content": (
                    "{{ {'path': rust_release_binary_path | default(None),"
                    " 'failed': rust_release_binary_failed | default(None),"
                    " 'failed_names': rust_release_binary_failed_names | default([]),"
                    " 'pins': rust_release_binary_pins | default(None),"
                    " 'prune': rust_release_binary_prune | default(None)} | to_json }}"
                ),
            },
            "check_mode": False,
            "changed_when": False,
        }
        play = {
            "hosts": "localhost",
            "gather_facts": False,
            "vars": {
                "rust_release_binary_name": NAME,
                "rust_release_binary_install_root": str(self.root),
                "rust_release_binary_owner": self.owner,
                "rust_release_binary_group": self.group,
                "rust_release_binary_validate_user": "",
            },
            "tasks": list(tasks) + [dump],
        }
        path = self.work / f"play-{self.runs}.yml"
        path.write_text(yaml.safe_dump([play], sort_keys=False), encoding="utf-8")
        argv = ["ansible-playbook", "-i", "localhost,", "-c", "local", str(path)]
        if check:
            argv.append("--check")
        result = subprocess.run(
            argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, env=self.env, timeout=600
        )
        out = result.stdout + result.stderr
        match = RECAP.search(result.stdout)
        self.assertIsNotNone(match, out)
        keys = ("ok", "changed", "unreachable", "failed", "skipped", "rescued", "ignored")
        recap = dict(zip(keys, map(int, match.groups())))
        data = json.loads(facts.read_text()) if facts.exists() else None
        return {"rc": result.returncode, "out": out, "recap": recap, "facts": data}

    def ok(self, *tasks: dict, check: bool = False) -> dict:
        result = self.play(*tasks, check=check)
        self.assertEqual(result["rc"], 0, result["out"])
        return result

    def versions(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and not p.is_symlink() and not p.name.startswith("."))

    def pins(self) -> dict[str, str]:
        pins = self.root / ".pins"
        return {p.name: p.read_text() for p in sorted(pins.iterdir())} if pins.exists() else {}

    def age(self, *versions: str) -> None:
        """Give the version directories increasing mtimes in this order."""

        for index, version in enumerate(versions):
            stamp = 1_600_000_000 + index * 1000
            os.utime(self.root / version, (stamp, stamp))

    def staging_left(self) -> list[str]:
        return [p.name for p in self.root.iterdir() if p.name.startswith(".staging")] if self.root.exists() else []

    # -- install -----------------------------------------------------------

    def test_install_layout_and_idempotent_rerun(self):
        _, sha = self.archive("1.0.0")
        first = self.ok(self.install("1.0.0"))
        version_dir = self.root / "1.0.0"
        self.assertEqual(sorted(p.name for p in version_dir.iterdir()), [".archive-sha256", "LICENSE", NAME])
        self.assertEqual((version_dir / NAME).stat().st_mode & 0o7777, 0o755)
        self.assertEqual((version_dir / "LICENSE").stat().st_mode & 0o7777, 0o644)
        self.assertEqual((version_dir / ".archive-sha256").read_text(), sha + "\n")
        self.assertEqual(version_dir.stat().st_mode & 0o7777, 0o755)
        self.assertEqual(self.staging_left(), [])
        self.assertEqual(first["facts"]["path"], str(version_dir / NAME))
        self.assertFalse(first["facts"]["failed"])
        self.assertGreater(first["recap"]["changed"], 0)

        self.ok(self.pin("svc", "1.0.0"))
        again = self.ok(self.install("1.0.0"), self.pin("svc", "1.0.0"), self.prune())
        self.assertEqual(again["recap"]["changed"], 0, again["out"])
        self.assertEqual(again["recap"]["ignored"], 0, again["out"])
        self.assertEqual(self.pins(), {"svc": "1.0.0\n"})

    def test_install_extra_members(self):
        self.archive("1.0.0", members=[NAME, "LICENSE", "helper", "LICENSE.GPL-3.0"])
        self.ok(self.install("1.0.0", members=[NAME, "helper", "LICENSE", "LICENSE.GPL-3.0"], executables=[NAME, "helper"]))
        version_dir = self.root / "1.0.0"
        self.assertEqual((version_dir / "helper").stat().st_mode & 0o7777, 0o755)
        self.assertEqual((version_dir / "LICENSE.GPL-3.0").stat().st_mode & 0o7777, 0o644)
        # The default member list refuses the same archive.
        self.archive("2.0.0", members=[NAME, "LICENSE", "helper"])
        refused = self.play(self.install("2.0.0"))
        self.assertNotEqual(refused["rc"], 0)
        self.assertEqual(self.versions(), ["1.0.0"])

    def test_install_by_download_with_checksum(self):
        path, sha = self.archive("1.0.0")
        self.ok(self.include("install", version="1.0.0", sha256=sha, release_url=path.as_uri()))
        self.assertEqual((self.root / "1.0.0/.archive-sha256").read_text(), sha + "\n")
        path2, _ = self.archive("2.0.0")
        wrong = self.play(self.include("install", version="2.0.0", sha256="0" * 64, release_url=path2.as_uri()))
        self.assertNotEqual(wrong["rc"], 0)
        self.assertEqual(self.versions(), ["1.0.0"])
        self.assertEqual(self.staging_left(), [])

    def test_refuses_a_different_archive_for_an_installed_version(self):
        self.archive("1.0.0", key="a", salt="a")
        _, sha_b = self.archive("1.0.0", key="b", salt="b")
        self.ok(self.install("1.0.0", key="a"))
        before = (self.root / "1.0.0" / NAME).read_bytes()
        hard = self.play(self.install("1.0.0", key="b"))
        self.assertNotEqual(hard["rc"], 0)
        self.assertIn("is never replaced in place", hard["out"])
        self.assertEqual((self.root / "1.0.0" / NAME).read_bytes(), before)
        soft = self.ok(self.install("1.0.0", key="b", fail_hard=False))
        self.assertTrue(soft["facts"]["failed"])
        self.assertEqual(soft["facts"]["path"], "")
        self.assertEqual(soft["recap"]["ignored"], 1)
        self.assertEqual(self.versions(), ["1.0.0"])
        self.assertNotEqual((self.root / "1.0.0/.archive-sha256").read_text().strip(), sha_b)

    def test_refuses_archives_with_other_members(self):
        cases = {
            "extra": {"members": [NAME, "LICENSE", "README"]},
            "missing": {"members": [NAME]},
            "duplicate": {"members": [NAME, "LICENSE", NAME]},
            "nested": {"members": [f"bin/{NAME}", "LICENSE"]},
            "symlink": {"symlink": "evil"},
            "directory": {"directory": "sub"},
            "dotdot": {"members": [NAME, "LICENSE", "../escape"]},
        }
        installs = []
        for index, kwargs in enumerate(cases.values()):
            self.archive(f"1.0.{index}", **kwargs)
            installs.append(self.install(f"1.0.{index}", fail_hard=False))
        result = self.ok(*installs)
        self.assertEqual(result["recap"]["ignored"], len(cases), result["out"])
        self.assertGreaterEqual(result["out"].count("must hold exactly the regular files"), len(cases))
        self.assertEqual(self.versions(), [])
        self.assertEqual(self.staging_left(), [])
        hard = self.play(self.install("1.0.0"))
        self.assertNotEqual(hard["rc"], 0)
        self.assertEqual(self.versions(), [])
        self.assertFalse((self.work / "escape").exists())
        self.assertFalse((self.work / "opt/escape").exists())

    def test_rejected_binary_is_removed_and_blocks_prune_in_the_same_run(self):
        self.ok(*[self.install(v) for v in ("1.0.0", "1.1.0", "1.2.0")])
        self.age("1.0.0", "1.1.0", "1.2.0")
        self.archive("2.0.0", says="2.0.1")
        self.archive("3.0.0", exit_code=1)
        for version in ("2.0.0", "3.0.0"):
            result = self.ok(self.install(version, fail_hard=False), self.prune(keep_versions=1))
            self.assertTrue(result["facts"]["failed"], version)
            self.assertEqual(result["facts"]["failed_names"], [NAME])
            self.assertEqual(result["recap"]["ignored"], 2, result["out"])  # install warning + prune warning
            self.assertIn("failed earlier in this run", result["out"])
            self.assertEqual(result["facts"]["prune"]["removed"], [])
            self.assertEqual(self.versions(), ["1.0.0", "1.1.0", "1.2.0"], version)
        # A failure in one run does not block the next one.
        self.ok(self.prune(keep_versions=1))
        self.assertEqual(self.versions(), ["1.2.0"])

    def test_rejected_binary_stops_the_play_with_fail_hard(self):
        self.archive("2.0.0", says="9.9.9")
        result = self.play(self.install("2.0.0"), {"name": "after", "ansible.builtin.debug": {"msg": "REACHED"}})
        self.assertNotEqual(result["rc"], 0)
        self.assertNotIn("REACHED", result["out"])
        self.assertIn("expected 'demo-tool 2.0.0 (<commit>)'", result["out"])
        self.assertEqual(self.versions(), [])

    def test_invalid_inputs_only_warn_without_fail_hard(self):
        path, sha = self.archive("1.0.0")
        bad = {"local_archive": str(path), "sha256": sha}
        result = self.ok(self.include("install", version="../../etc", fail_hard=False, **bad))
        self.assertTrue(result["facts"]["failed"])
        self.assertEqual(result["recap"]["ignored"], 1)
        self.assertEqual(self.versions(), [])
        for params in ({"version": "1.0"}, {"version": "1.0.0", "members": [NAME, "LICENSE\n"]}):
            result = self.play(self.include("install", **{**bad, **params}))
            self.assertNotEqual(result["rc"], 0, params)
        self.assertEqual(self.versions(), [])

    def test_check_mode(self):
        self.ok(self.install("1.0.0"))
        fresh = self.ok(self.install("2.0.0"), check=True)
        self.assertEqual(self.versions(), ["1.0.0"])
        self.assertEqual(self.staging_left(), [])
        self.assertEqual(fresh["facts"]["path"], str(self.root / "2.0.0" / NAME))
        # An installed version is still validated in check mode.
        self.ok(self.install("1.0.0"), check=True)
        binary = self.root / "1.0.0" / NAME
        binary.write_text("#!/bin/sh\nexit 3\n")
        broken = self.play(self.install("1.0.0"), check=True)
        self.assertNotEqual(broken["rc"], 0)
        self.assertIn("--version exited", broken["out"])
        # pin and prune change nothing in check mode
        self.ok(self.install("3.0.0"))
        self.age("1.0.0", "3.0.0")
        self.ok(self.pin("svc", "1.0.0"), self.prune(keep_versions=1), check=True)
        self.assertEqual(self.pins(), {})
        self.assertEqual(self.versions(), ["1.0.0", "3.0.0"])

    def test_include_without_tasks_from_fails(self):
        result = self.play({"name": "main", "ansible.builtin.include_role": {"name": FQCN}})
        self.assertNotEqual(result["rc"], 0)
        self.assertIn("tasks_from", result["out"])

    # -- pin ---------------------------------------------------------------

    def test_pin_moves_and_absent(self):
        self.ok(*[self.install(v) for v in ("1.0.0", "2.0.0")])
        first = self.ok(self.pin("svc", "1.0.0"))
        self.assertEqual(first["facts"]["pins"], {"current": "1.0.0", "previous": None})
        self.assertEqual((self.root / ".pins/svc").stat().st_mode & 0o7777, 0o644)
        self.ok(self.pin("svc", "2.0.0"))
        self.assertEqual(self.pins(), {"svc": "2.0.0\n", "svc.previous": "1.0.0\n"})
        same = self.ok(self.pin("svc", "2.0.0"))
        self.assertEqual(same["recap"]["changed"], 0)
        self.ok(self.pin("svc", state="absent"))
        self.assertEqual(self.pins(), {"svc.previous": "2.0.0\n"})
        self.ok(self.pin("svc", state="absent"))
        self.assertEqual(self.pins(), {"svc.previous": "2.0.0\n"})
        self.ok(self.pin("svc", "1.0.0"))
        self.assertEqual(self.pins(), {"svc": "1.0.0\n", "svc.previous": "2.0.0\n"})
        self.ok(self.pin("svc", state="absent", keep_previous=False))
        self.assertEqual(self.pins(), {})
        # explicit previous for a consumer that knows the live version without a pin
        self.ok(self.pin("other", "2.0.0", previous="1.0.0"))
        self.assertEqual(self.pins(), {"other": "2.0.0\n", "other.previous": "1.0.0\n"})

    def test_pin_refusals_change_nothing(self):
        self.ok(self.install("1.0.0"))
        self.ok(self.pin("svc", "1.0.0"))
        missing = self.play(self.pin("svc", "2.0.0"))
        self.assertNotEqual(missing["rc"], 0)
        self.assertIn("is not installed", missing["out"])
        self.assertEqual(self.pins(), {"svc": "1.0.0\n"})
        bad_name = self.play(self.pin("svc.previous", "1.0.0"))
        self.assertNotEqual(bad_name["rc"], 0)
        (self.root / ".pins/svc").write_text("garbage\n")
        self.ok(self.install("2.0.0"))
        corrupt = self.play(self.pin("svc", "2.0.0"))
        self.assertNotEqual(corrupt["rc"], 0)
        self.assertIn("not one version", corrupt["out"])
        self.assertEqual(self.pins(), {"svc": "garbage\n"})

    def test_absent_pin_without_install_root_creates_nothing(self):
        self.ok(self.pin("svc", state="absent"), self.prune())
        self.assertFalse(self.root.exists())

    # -- prune -------------------------------------------------------------

    def test_prune_keeps_newest_pins_previous_protected_and_other_consumers(self):
        self.ok(*[self.install(v) for v in ("1.0.0", "2.0.0", "3.0.0", "4.0.0", "5.0.0", "6.0.0")])
        self.ok(self.pin("a", "1.0.0"), self.pin("a", "2.0.0"), self.pin("b", "3.0.0"))
        self.assertEqual(self.pins(), {"a": "2.0.0\n", "a.previous": "1.0.0\n", "b": "3.0.0\n"})
        (self.root / "notes").mkdir()
        (self.root / ".staging-9.0.0").mkdir()
        (self.root / "9.9.9").symlink_to(self.root / "1.0.0")
        self.age("1.0.0", "2.0.0", "3.0.0", "4.0.0", "5.0.0", "6.0.0")
        result = self.ok(self.prune(keep_versions=1, protect=["4.0.0"]))
        self.assertEqual(self.versions(), ["1.0.0", "2.0.0", "3.0.0", "4.0.0", "6.0.0", "notes"])
        self.assertEqual(result["facts"]["prune"]["removed"], ["5.0.0"])
        self.assertTrue((self.root / ".staging-9.0.0").is_dir())
        self.assertTrue((self.root / "9.9.9").is_symlink())
        again = self.ok(self.prune(keep_versions=1, protect=["4.0.0"]))
        self.assertEqual(again["recap"]["changed"], 0)

    def test_rollback_sequence_keeps_the_previous_pin(self):
        """Owner decision 2026-10-21: v1 live; v2; roll back to v1; v3; v4."""

        self.ok(self.install("1.0.0"), self.pin("svc", "1.0.0"))

        def deploy(version: str, protect: list[str] | None = None) -> None:
            # A consumer's successful deploy: install, (verify live), pin, prune.
            # Install order is mtime order; a reinstall does not touch the mtime.
            self.ok(
                self.install(version),
                self.pin("svc", version),
                self.prune(keep_versions=1, protect=protect or []),
            )

        deploy("2.0.0")
        self.assertEqual(self.pins(), {"svc": "2.0.0\n", "svc.previous": "1.0.0\n"})
        self.assertEqual(self.versions(), ["1.0.0", "2.0.0"])
        deploy("1.0.0")  # roll back
        self.assertEqual(self.pins(), {"svc": "1.0.0\n", "svc.previous": "2.0.0\n"})
        self.assertEqual(self.versions(), ["1.0.0", "2.0.0"])
        deploy("3.0.0")
        self.assertEqual(self.pins(), {"svc": "3.0.0\n", "svc.previous": "1.0.0\n"})
        self.assertEqual(self.versions(), ["1.0.0", "3.0.0"])  # v1 stays: it is the previous pin
        deploy("4.0.0", protect=["1.0.0"])
        self.assertEqual(self.pins(), {"svc": "4.0.0\n", "svc.previous": "3.0.0\n"})
        self.assertEqual(self.versions(), ["1.0.0", "3.0.0", "4.0.0"])  # v1 stays: protected
        deploy("4.0.0")
        self.assertEqual(self.versions(), ["3.0.0", "4.0.0"])  # neither pinned nor protected any more

    def test_switch_to_python_keeps_the_last_rust_version(self):
        self.ok(self.install("1.0.0"), self.pin("svc", "1.0.0"))
        self.ok(self.install("2.0.0"), self.pin("svc", "2.0.0"))
        self.ok(*[self.install(v) for v in ("3.0.0", "4.0.0")])
        self.age("1.0.0", "2.0.0", "3.0.0", "4.0.0")
        self.ok(self.pin("svc", state="absent"), self.prune(keep_versions=1))
        self.assertEqual(self.pins(), {"svc.previous": "2.0.0\n"})
        self.assertEqual(self.versions(), ["2.0.0", "4.0.0"])

    def test_repeated_failed_deploys_never_prune_the_live_version(self):
        """Owner decision 2026-10-21: failed deploys with different targets."""

        self.ok(self.install("1.0.0"), self.pin("svc", "1.0.0"))
        live = str(self.root / "1.0.0" / NAME)
        verify_fails = {"name": "consumer verification", "ansible.builtin.fail": {"msg": "not live"}}

        # 1. installed, verification fails: the play stops before pin and prune.
        result = self.play(self.install("2.0.0"), verify_fails, self.pin("svc", "2.0.0"), self.prune(keep_versions=1))
        self.assertNotEqual(result["rc"], 0)
        # 2. broken release without fail_hard: prune of this run deletes nothing.
        self.archive("3.0.0", says="3.0.1")
        result = self.ok(self.install("3.0.0", fail_hard=False), self.prune(keep_versions=1))
        self.assertIn("failed earlier in this run", result["out"])
        # 3. installed, the consumer cannot read its live state: nothing deleted.
        self.ok(self.install("4.0.0"))
        self.age("1.0.0", "2.0.0", "4.0.0")
        result = self.ok(self.prune(keep_versions=1, live_state_unknown=True))
        self.assertIn("live state as unknown", result["out"])
        self.assertEqual(self.versions(), ["1.0.0", "2.0.0", "4.0.0"])
        # 4. pins lost; the consumer protects what its unit runs (live state alone).
        shutil.rmtree(self.root / ".pins")
        self.ok(self.install("5.0.0"))
        self.age("1.0.0", "2.0.0", "4.0.0", "5.0.0")
        self.ok(self.prune(keep_versions=1, protect=[live]))
        self.assertEqual(self.versions(), ["1.0.0", "5.0.0"])
        # 5. a target whose verification failed is not pinned; v1 is still live.
        self.ok(self.install("6.0.0"))
        self.age("1.0.0", "5.0.0", "6.0.0")
        self.ok(self.prune(keep_versions=1, protect=[live, "1.0.0"]))
        self.assertEqual(self.versions(), ["1.0.0", "6.0.0"])
        self.assertTrue((self.root / "1.0.0" / NAME).is_file())

    def test_protect_running_oneshot_executables(self):
        """A collector run still executes v1 after its unit and pins moved on."""

        real = self.work / "real"
        real.mkdir()
        alias_root = self.work / "alias"
        alias_root.symlink_to(real)
        self.root = alias_root / NAME  # configured through a symlinked parent
        self.ok(*[self.install(v) for v in ("1.0.0", "2.0.0", "3.0.0", "4.0.0")])
        self.ok(self.pin("svc", "3.0.0"))
        self.age("1.0.0", "2.0.0", "3.0.0", "4.0.0")
        resolved = Path(os.path.realpath(self.root))
        # /proc/<pid>/exe of the run: the resolved path, deleted or not.
        running = [f"{resolved}/1.0.0/{NAME} (deleted)", f"{resolved}/2.0.0/{NAME}-apt", "/usr/bin/python3"]
        result = self.ok(self.prune(keep_versions=1, protect=running))
        self.assertEqual(self.versions(), ["1.0.0", "2.0.0", "3.0.0", "4.0.0"])
        self.assertEqual(result["facts"]["prune"]["removed"], [])
        self.age("1.0.0", "2.0.0", "3.0.0", "4.0.0")
        result = self.ok(self.prune(keep_versions=1, protect=running[:1]))
        self.assertEqual(result["facts"]["prune"]["removed"], ["2.0.0"])
        self.assertEqual(self.versions(), ["1.0.0", "3.0.0", "4.0.0"])

    def test_uninterpretable_live_state_prunes_nothing(self):
        self.ok(*[self.install(v) for v in ("1.0.0", "2.0.0", "3.0.0")])
        self.age("1.0.0", "2.0.0", "3.0.0")
        cases = (
            [f"{self.root}/.staging-1.0.0/tree/{NAME}"],
            [f"{self.root}/1.0/{NAME}"],
            [f"/somewhere/else/{NAME}"],
            ["latest"],
        )
        result = self.ok(*[self.prune(keep_versions=1, protect=protect) for protect in cases])
        self.assertEqual(result["recap"]["ignored"], len(cases), result["out"])
        self.assertEqual(self.versions(), ["1.0.0", "2.0.0", "3.0.0"])
        (self.root / ".pins").mkdir()
        (self.root / ".pins/svc").write_text("not a version\n")
        result = self.ok(self.prune(keep_versions=1))
        self.assertIn("does not hold exactly one version", result["out"])
        (self.root / ".pins/svc").unlink()
        (self.root / ".pins/odd").mkdir()
        result = self.ok(self.prune(keep_versions=1))
        self.assertIn("is not a regular file", result["out"])
        self.assertEqual(self.versions(), ["1.0.0", "2.0.0", "3.0.0"])
        (self.root / ".pins/odd").rmdir()
        self.ok(self.prune(keep_versions=1))
        self.assertEqual(self.versions(), ["3.0.0"])

    @unittest.skipIf(os.geteuid() == 0, "root reads a directory with mode 000")
    def test_unlistable_pins_prune_nothing(self):
        # find reports an unreadable directory in skipped_paths and succeeds;
        # an incomplete pin listing must not count as "no pins".
        self.ok(*[self.install(v) for v in ("1.0.0", "2.0.0")])
        self.ok(self.pin("svc", "1.0.0"), self.pin("svc", "2.0.0"), self.pin("svc", state="absent"))
        self.assertEqual(self.pins(), {"svc.previous": "2.0.0\n"})
        self.ok(self.install("3.0.0"))
        self.age("1.0.0", "2.0.0", "3.0.0")
        pins = self.root / ".pins"
        pins.chmod(0o000)
        self.addCleanup(pins.chmod, 0o755)
        result = self.ok(self.prune(keep_versions=1))
        self.assertIn("cannot list every pin", result["out"])
        self.assertEqual(result["recap"]["ignored"], 1)
        self.assertEqual(result["facts"]["prune"]["removed"], [])
        pins.chmod(0o755)
        self.assertEqual(self.versions(), ["1.0.0", "2.0.0", "3.0.0"])
        self.ok(self.prune(keep_versions=1))
        self.assertEqual(self.versions(), ["2.0.0", "3.0.0"])

    def test_prune_input_validation(self):
        for params in ({"keep_versions": 0}, {"protect": "1.0.0"}, {"live_state_unknown": "maybe"}):
            result = self.play(self.prune(**params))
            self.assertNotEqual(result["rc"], 0, params)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(unittest.main())
