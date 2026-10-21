"""echoport_remote_command_guard: the impl selector and confirm_live.yml.

rust/echoport-command-guard/PLAN.md 6.2 (S6). Static checks of the task files,
unit tests of the live-state filter (``plugins/filter/echoport_guard.py``)
and ``ansible-playbook`` runs against localhost: the forced command per impl
(python byte for byte as before the port) and ``confirm_live.yml`` on a
temporary ``authorized_keys`` and install root (stub binaries, the pin and
prune of ``rust_release_binary``). The role's molecule scenarios run the same
against a real sshd.
"""

from __future__ import annotations

import grp
import importlib.util
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/echoport_remote_command_guard"
TASKS = ROLE / "tasks"
FQCN = "local.ops_library.echoport_remote_command_guard"
BINARY = "echoport-command-guard"
INSTALL_ROOT = "/usr/local/lib/echoport-command-guard"
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDeployKeyForTestsOnly0000000000000000000"
OTHER_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOperatorKeyForTestsOnly00000000000000000"
PYTHON_COMMAND = (
    "/usr/bin/python3 -I /usr/local/sbin/echoport-remote-command-guard /etc/echoport/remote-command-guard.json"
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FILTERS = _load("echoport_guard_filters", ROOT / "plugins/filter/echoport_guard.py")
RUST_RELEASE = _load("rust_release_filters_for_guard", ROOT / "plugins/filter/rust_release.py")


def walk(tasks):
    for task in tasks or []:
        yield task
        for section in ("block", "rescue", "always"):
            yield from walk(task.get(section, []))


def task_file(name: str) -> list[dict]:
    return yaml.safe_load((TASKS / name).read_text(encoding="utf-8"))


def names(name: str) -> list[str]:
    return [str(task.get("name", "")) for task in walk(task_file(name))]


def line(command: str | None, key: str = KEY, comment: str = "deploy@macmini backup automation") -> str:
    options = 'from="192.0.2.10,2001:db8::10",restrict'
    if command is not None:
        options += f',command="{command}"'
    return f"{options} {key} {comment}"


def rust_command(version: str, root: str = INSTALL_ROOT) -> str:
    return f"{root}/{version}/{BINARY} /etc/echoport/remote-command-guard.json"


def shadow_command(version: str, root: str = INSTALL_ROOT) -> str:
    return f"{root}/{version}/{BINARY} --shadow /etc/echoport/remote-command-guard.json {PYTHON_COMMAND}"


# --------------------------------------------------------------------------
# Static checks
# --------------------------------------------------------------------------


class StaticTaskTests(unittest.TestCase):
    FILES = ("main.yml", "rust.yml", "forced_command.yml", "confirm_live.yml")

    def test_molecule_installs_the_crate_version(self):
        # The shadow and rust scenarios install the guard built from the
        # checkout, whose `--version` the install step checks against the
        # version the scenario names: it must follow every crate release.
        import tomllib

        cargo = tomllib.loads((ROOT / "rust/echoport-command-guard/Cargo.toml").read_text())
        version = cargo["package"]["version"]
        shared = ROLE / "molecule/shared"
        converge = (shared / "converge.yml").read_text()
        verify = (shared / "verify.yml").read_text()
        self.assertIn(f"else '{version}' }}}}", converge)
        self.assertIn(f"{INSTALL_ROOT}/{version}/{BINARY}\n", verify)
        self.assertIn(f"== '{version}\\n')", verify)
        stale = {v for v in re.findall(r"(?<![\d.])\d+\.\d+\.\d+(?![\d.])", converge + verify) if v != version}
        self.assertEqual(stale, set())

    def test_task_names_carry_their_file_prefix(self):
        # ansible-lint name[prefix] outside main.yml.
        for name in self.FILES[1:]:
            prefix = name[: -len(".yml")] + " | "
            for task_name in names(name):
                self.assertTrue(task_name.startswith(prefix), f"{name}: {task_name}")

    def test_no_task_environment_and_no_shell(self):
        for name in self.FILES:
            for task in walk(task_file(name)):
                self.assertNotIn("environment", task, f"{name}: {task.get('name')}")
                for module in ("shell", "ansible.builtin.shell", "raw", "ansible.builtin.raw"):
                    self.assertNotIn(module, task, f"{name}: {task.get('name')}")

    def test_main_tasks_never_pin_or_prune(self):
        # The authorized_keys line is not written yet when main.yml runs.
        for name in ("main.yml", "rust.yml", "forced_command.yml"):
            for task in walk(task_file(name)):
                include = task.get("ansible.builtin.include_role") or {}
                self.assertNotIn(include.get("tasks_from"), ("pin", "prune"), f"{name}: {task.get('name')}")
        install = [
            t for t in walk(task_file("rust.yml"))
            if (t.get("ansible.builtin.include_role") or {}).get("tasks_from") == "install"
        ]
        self.assertEqual(len(install), 1)
        self.assertEqual(install[0]["vars"]["rust_release_binary_fail_hard"], "{{ _echoport_guard_rust_fatal | bool }}")

    def test_rust_steps_run_before_the_policy_and_the_fact(self):
        order = names("main.yml")
        rust = order.index("Install and check the Rust guard")
        self.assertLess(rust, order.index("Install the guard policy"))
        self.assertLess(order.index("Install the guard policy"), order.index("Publish the forced command for authorized_keys"))
        # Python always validates the policy, as before the port.
        policy = next(t for t in task_file("main.yml") if t.get("name") == "Install the guard policy")
        self.assertIn("--check-policy %s", policy["ansible.builtin.copy"]["validate"])
        self.assertIn("echoport_remote_command_guard_python", policy["ansible.builtin.copy"]["validate"])

    def test_rust_failures_are_fatal_only_for_shadow_and_rust(self):
        block = task_file("rust.yml")[0]
        stop, warn = block["rescue"]
        self.assertEqual(stop["when"], "_echoport_guard_rust_fatal | bool")
        self.assertTrue(warn["ignore_errors"])
        self.assertNotIn("when", warn)
        main = {t.get("name"): t for t in task_file("main.yml")}
        self.assertEqual(
            main["Set the Rust guard state"]["ansible.builtin.set_fact"]["_echoport_guard_rust_fatal"],
            "{{ echoport_remote_command_guard_impl != 'python' }}",
        )

    def test_every_component_is_checked_up_to_the_root(self):
        stat = next(t for t in walk(task_file("rust.yml")) if t.get("name", "").endswith("Stat every component of the binary's path"))
        self.assertIn("echoport_guard_path_chain", stat["loop"])
        self.assertFalse(stat["ansible.builtin.stat"]["follow"])
        owner = next(t for t in walk(task_file("rust.yml")) if "nobody else can write it" in t.get("name", ""))
        that = owner["ansible.builtin.assert"]["that"]
        for check in ("not item.stat.islnk", "item.stat.uid == 0", "not item.stat.wgrp", "not item.stat.woth"):
            self.assertIn(check, that)

    def test_confirm_live_verifies_before_it_pins_and_pins_before_it_prunes(self):
        order = names("confirm_live.yml")
        verify = order.index("confirm_live | Assert the pinned key's line carries the published forced command")
        version = order.index("confirm_live | Assert the live Rust guard is the target version")
        pin = order.index("confirm_live | Pin the live Rust version")
        prune = order.index("confirm_live | Prune old Rust versions")
        self.assertLess(verify, version)
        self.assertLess(version, pin)
        self.assertLess(pin, prune)
        block = next(t for t in walk(task_file("confirm_live.yml")) if t.get("name") == "confirm_live | Move the pins and prune old Rust versions")
        self.assertIn("_echoport_guard_live_line_ok | bool", block["when"])
        prune_task = next(t for t in block["block"] if t.get("name") == "confirm_live | Prune old Rust versions")
        self.assertEqual(
            prune_task["vars"]["rust_release_binary_live_state_unknown"], "{{ _echoport_guard_live_unknown | length > 0 }}"
        )

    def test_defaults_are_documented(self):
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
        readme = (ROLE / "README.md").read_text(encoding="utf-8")
        for name in defaults:
            if name.startswith("echoport_remote_command_guard_"):
                self.assertTrue(f"`{name}`" in readme, f"{name} is not in README.md")
        self.assertEqual(defaults["echoport_remote_command_guard_impl"], "python")


# --------------------------------------------------------------------------
# The live-state filter
# --------------------------------------------------------------------------


class LiveStateFilterTests(unittest.TestCase):
    def state(self, *lines, roots=(INSTALL_ROOT,), key=KEY):
        return FILTERS.echoport_guard_live_state("\n".join(lines) + "\n", key, list(roots))

    def test_version_grammar_matches_rust_release_binary(self):
        self.assertEqual(FILTERS.VERSION_RE.pattern, RUST_RELEASE.VERSION_RE.pattern)

    def test_python_line(self):
        state = self.state(line(PYTHON_COMMAND), line(None, OTHER_KEY, "operator"))
        self.assertEqual(state, {"commands": [[PYTHON_COMMAND]], "versions": [], "unknown": []})

    def test_rust_and_shadow_lines(self):
        self.assertEqual(self.state(line(rust_command("0.1.0")))["versions"], ["0.1.0"])
        state = self.state(line(shadow_command("0.2.0-rc.1")))
        self.assertEqual(state["commands"], [[shadow_command("0.2.0-rc.1")]])
        self.assertEqual(state["versions"], ["0.2.0-rc.1"])
        self.assertEqual(state["unknown"], [])

    def test_several_lines_with_different_versions(self):
        state = self.state(
            line(rust_command("0.3.0")),
            line(shadow_command("0.1.0"), OTHER_KEY, "manual"),
            "# " + rust_command("0.0.9"),
            line(f"{INSTALL_ROOT}/1.0.0/{BINARY} --decide x", OTHER_KEY, "other"),
        )
        self.assertEqual(state["versions"], ["0.0.9", "0.1.0", "0.3.0", "1.0.0"])
        self.assertEqual(state["commands"], [[rust_command("0.3.0")]])
        self.assertEqual(state["unknown"], [])

    def test_resolved_root_spelling(self):
        state = self.state(line(rust_command("0.1.0", "/srv/real/guard")), roots=(INSTALL_ROOT, "/srv/real/guard"))
        self.assertEqual(state["versions"], ["0.1.0"])
        self.assertEqual(state["unknown"], [])

    def test_other_mentions_of_the_root_make_the_state_unknown(self):
        for command in (
            f"{INSTALL_ROOT}/0.1.0/LICENSE",
            f"{INSTALL_ROOT}/current/{BINARY} /p",
            f"{INSTALL_ROOT}/v0.1.0/{BINARY} /p",
            f"{INSTALL_ROOT}/0.1.0/{BINARY}-old /p",
            f"{INSTALL_ROOT}/.pins/echoport_remote_command_guard",
            f"{INSTALL_ROOT}-old/0.1.0/{BINARY} /p",
            f"/x{INSTALL_ROOT}/0.1.0/{BINARY} /p",
            f"{INSTALL_ROOT}//0.1.0/{BINARY} /p",
            f"{INSTALL_ROOT} /p",
        ):
            with self.subTest(command=command):
                state = self.state(line(command, OTHER_KEY, "manual"))
                self.assertNotEqual(state["unknown"], [], command)

    def test_unreadable_file(self):
        state = FILTERS.echoport_guard_live_state(None, KEY, [INSTALL_ROOT])
        self.assertEqual(state["commands"], [])
        self.assertEqual(state["unknown"], ["cannot read authorized_keys"])

    def test_commands_of_the_pinned_key_only(self):
        # Two lines with the key, a line without command=, a malformed line.
        state = self.state(line(PYTHON_COMMAND), line(rust_command("0.1.0")), line(None))
        self.assertEqual(state["commands"], [[PYTHON_COMMAND], [rust_command("0.1.0")], []])
        state = self.state(f'command="{PYTHON_COMMAND} {KEY}')  # unterminated quote: sshd skips it
        self.assertEqual(state["commands"], [])
        state = self.state(f'restrict,command="a",command="b" {KEY}')
        self.assertEqual(state["commands"], [["a", "b"]])
        state = self.state(f"{KEY} no options")
        self.assertEqual(state["commands"], [[]])

    def test_option_parsing(self):
        state = self.state(f'Command="echo \\"x,y\\" z",no-pty {KEY} c\r')
        self.assertEqual(state["commands"], [['echo "x,y" z']])

    def test_bad_inputs_raise(self):
        with self.assertRaises(ValueError):
            FILTERS.echoport_guard_live_state("", "not-a-key", [INSTALL_ROOT])
        with self.assertRaises(ValueError):
            FILTERS.echoport_guard_live_state("", KEY, ["relative"])
        with self.assertRaises(ValueError):
            FILTERS.echoport_guard_live_state("", KEY, "/x")
        # No roots (unusable Rust inputs): only the key's commands are read.
        state = FILTERS.echoport_guard_live_state(line(rust_command("0.1.0")) + "\n", KEY, [])
        self.assertEqual(state["versions"], [])
        self.assertEqual(state["commands"], [[rust_command("0.1.0")]])

    def test_path_chain(self):
        self.assertEqual(
            FILTERS.echoport_guard_path_chain(f"{INSTALL_ROOT}/0.1.0/{BINARY}"),
            [
                f"{INSTALL_ROOT}/0.1.0/{BINARY}",
                f"{INSTALL_ROOT}/0.1.0",
                INSTALL_ROOT,
                "/usr/local/lib",
                "/usr/local",
                "/usr",
                "/",
            ],
        )
        for bad in ("relative", "/a/../b", "/a/", ""):
            with self.assertRaises(ValueError):
                FILTERS.echoport_guard_path_chain(bad)


# --------------------------------------------------------------------------
# ansible-playbook against localhost
# --------------------------------------------------------------------------

RECAP = re.compile(
    r"^localhost\s+:\s+ok=(\d+)\s+changed=(\d+)\s+unreachable=(\d+)\s+failed=(\d+)\s+"
    r"skipped=(\d+)\s+rescued=(\d+)\s+ignored=(\d+)",
    re.M,
)


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not on PATH")
@unittest.skipUnless(shutil.which("realpath"), "realpath not on PATH")
class PlaybookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name).resolve()
        collections = cls.base / "collections/ansible_collections/local"
        collections.mkdir(parents=True)
        (collections / "ops_library").symlink_to(ROOT)
        cls.env = {
            **os.environ,
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
        self.root = self.work / "lib" / BINARY
        self.keys = self.work / "authorized_keys"
        self.runs = 0

    # -- helpers -----------------------------------------------------------

    def stub(self, version: str, says: str | None = None, mtime: int | None = None) -> None:
        directory = self.root / version
        directory.mkdir(parents=True, exist_ok=True)
        binary = directory / BINARY
        binary.write_text(f"#!/bin/sh\necho '{BINARY} {says or version} (stub)'\n")
        binary.chmod(0o755)
        if mtime is not None:
            os.utime(directory, (mtime, mtime))

    def write_keys(self, *lines: str) -> None:
        self.keys.write_text("\n".join(lines) + "\n")

    def pins(self) -> dict[str, str]:
        pins = self.root / ".pins"
        return {p.name: p.read_text() for p in sorted(pins.iterdir())} if pins.exists() else {}

    def versions(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir() if not p.name.startswith(".")) if self.root.exists() else []

    def role_vars(self, impl: str, version: str = "", **extra) -> dict:
        return {
            "echoport_remote_command_guard_impl": impl,
            "echoport_remote_command_guard_rust_version": version,
            "echoport_remote_command_guard_rust_install_root": str(self.root),
            "echoport_remote_command_guard_authorized_keys_path": str(self.keys),
            "echoport_remote_command_guard_confirm_public_key": KEY,
            **extra,
        }

    def include(self, tasks_from: str, impl: str, version: str = "", **extra) -> dict:
        return {
            "name": f"guard {tasks_from}",
            "ansible.builtin.include_role": {"name": FQCN, "tasks_from": tasks_from},
            "vars": self.role_vars(impl, version, **extra),
        }

    def play(self, *tasks: dict, check: bool = False, fact_vars: dict | None = None) -> dict:
        self.runs += 1
        facts = self.work / f"facts-{self.runs}.json"
        dump = {
            "name": "dump facts",
            "ansible.builtin.copy": {
                "dest": str(facts),
                "mode": "0644",
                "content": "{{ {'command': echoport_remote_command_guard_forced_command | default(None)} | to_json }}",
            },
            "check_mode": False,
            "changed_when": False,
        }
        play = {
            "hosts": "localhost",
            "gather_facts": False,
            "vars": {
                "rust_release_binary_owner": self.owner,
                "rust_release_binary_group": self.group,
                **(fact_vars or {}),
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

    def ok(self, *tasks: dict, **kwargs) -> dict:
        result = self.play(*tasks, **kwargs)
        self.assertEqual(result["rc"], 0, result["out"])
        return result

    def confirm(self, impl: str, version: str = "", command: str | None = None, **kwargs) -> dict:
        """confirm_live.yml with the forced command main.yml would publish."""

        if command is None:
            command = {
                "python": PYTHON_COMMAND,
                "rust": rust_command(version, str(self.root)),
                "shadow": shadow_command(version, str(self.root)),
            }[impl]
        return self.play(
            self.include("confirm_live.yml", impl, version),
            fact_vars={"echoport_remote_command_guard_forced_command": command},
            **kwargs,
        )

    # -- the forced command ------------------------------------------------

    def test_forced_command_per_impl(self):
        cases = {
            "python": PYTHON_COMMAND,
            "shadow": shadow_command("0.1.0", str(self.root)),
            "rust": rust_command("0.1.0", str(self.root)),
        }
        for impl, expected in cases.items():
            with self.subTest(impl=impl):
                result = self.ok(
                    self.include("forced_command.yml", impl, "0.1.0"),
                    fact_vars={"_echoport_guard_rust_ok": True},
                )
                self.assertEqual(result["facts"]["command"], expected)

    def test_python_forced_command_is_unchanged_without_rust(self):
        # Byte for byte the pre-port fact, so ssh_authorized_keys_manage
        # reports no change with impl python.
        result = self.ok(self.include("forced_command.yml", "python"))
        self.assertEqual(result["facts"]["command"], PYTHON_COMMAND)

    def test_rust_forced_command_needs_a_checked_binary(self):
        for impl in ("shadow", "rust"):
            with self.subTest(impl=impl):
                result = self.play(self.include("forced_command.yml", impl, "0.1.0"))
                self.assertNotEqual(result["rc"], 0)
                self.assertIn("needs an installed and checked Rust guard", result["out"])

    # -- confirm_live.yml --------------------------------------------------

    def test_confirmed_rust_line_pins_and_prunes_with_the_live_versions(self):
        for index, version in enumerate(("0.1.0", "0.2.0", "0.3.0", "0.4.0", "0.5.0")):
            self.stub(version, mtime=1_600_000_000 + index * 1000)
        self.write_keys(
            line(rust_command("0.5.0", str(self.root))),
            line(shadow_command("0.1.0", str(self.root)), OTHER_KEY, "manual edit"),
        )
        result = self.play(
            self.include("confirm_live.yml", "rust", "0.5.0", echoport_remote_command_guard_rust_keep_versions=2),
            fact_vars={"echoport_remote_command_guard_forced_command": rust_command("0.5.0", str(self.root))},
        )
        self.assertEqual(result["rc"], 0, result["out"])
        self.assertEqual(self.pins(), {"echoport_remote_command_guard": "0.5.0\n"})
        # Newest two (0.5.0, 0.4.0) plus 0.1.0, which the manual line names.
        self.assertEqual(self.versions(), ["0.1.0", "0.4.0", "0.5.0"])

        # The next confirmed version moves 0.5.0 to the previous pin.
        self.stub("0.6.0", mtime=1_700_000_000)
        self.write_keys(line(rust_command("0.6.0", str(self.root))))
        self.ok(
            self.include("confirm_live.yml", "rust", "0.6.0", echoport_remote_command_guard_rust_keep_versions=1),
            fact_vars={"echoport_remote_command_guard_forced_command": rust_command("0.6.0", str(self.root))},
        )
        self.assertEqual(
            self.pins(), {"echoport_remote_command_guard": "0.6.0\n", "echoport_remote_command_guard.previous": "0.5.0\n"}
        )
        self.assertEqual(self.versions(), ["0.5.0", "0.6.0"])

    def test_stale_line_moves_no_pin_and_prunes_nothing(self):
        for version in ("0.1.0", "0.2.0", "0.3.0", "0.4.0", "0.5.0"):
            self.stub(version)
        self.write_keys(line(rust_command("0.1.0", str(self.root))))
        (self.root / ".pins").mkdir()
        (self.root / ".pins/echoport_remote_command_guard").write_text("0.1.0\n")
        for impl in ("rust", "shadow", "python"):
            with self.subTest(impl=impl):
                result = self.confirm(impl, "0.5.0")
                self.assertNotEqual(result["rc"], 0)
                self.assertIn("No pin moves and nothing is pruned", result["out"])
                self.assertEqual(self.pins(), {"echoport_remote_command_guard": "0.1.0\n"})
                self.assertEqual(len(self.versions()), 5)

    def test_wrong_version_of_the_live_binary_moves_no_pin(self):
        self.stub("0.2.0", says="0.1.9")
        self.write_keys(line(rust_command("0.2.0", str(self.root))))
        result = self.confirm("rust", "0.2.0")
        self.assertNotEqual(result["rc"], 0)
        self.assertIn("expected echoport-command-guard 0.2.0", result["out"])
        self.assertEqual(self.pins(), {})

    def test_missing_or_ambiguous_key_line_fails(self):
        self.stub("0.2.0")
        for lines in (
            [],
            [line(rust_command("0.2.0", str(self.root)), OTHER_KEY)],
            [line(rust_command("0.2.0", str(self.root))), line(PYTHON_COMMAND)],
        ):
            with self.subTest(lines=lines):
                self.write_keys(*lines)
                result = self.confirm("rust", "0.2.0")
                self.assertNotEqual(result["rc"], 0)
                self.assertEqual(self.pins(), {})
        self.keys.unlink()
        result = self.confirm("rust", "0.2.0")
        self.assertNotEqual(result["rc"], 0)
        self.assertIn("the file cannot be read", result["out"])

    def test_other_mention_of_the_root_skips_prune(self):
        for index, version in enumerate(("0.1.0", "0.2.0", "0.3.0")):
            self.stub(version, mtime=1_600_000_000 + index * 1000)
        self.write_keys(
            line(rust_command("0.3.0", str(self.root))),
            line(f"{self.root}/current/{BINARY} /p", OTHER_KEY, "manual"),
        )
        result = self.play(
            self.include("confirm_live.yml", "rust", "0.3.0", echoport_remote_command_guard_rust_keep_versions=1),
            fact_vars={"echoport_remote_command_guard_forced_command": rust_command("0.3.0", str(self.root))},
        )
        self.assertEqual(result["rc"], 0, result["out"])
        self.assertEqual(result["recap"]["ignored"], 1, result["out"])
        self.assertIn("not pruning", result["out"])
        self.assertEqual(self.pins(), {"echoport_remote_command_guard": "0.3.0\n"})
        self.assertEqual(self.versions(), ["0.1.0", "0.2.0", "0.3.0"])

    def test_switch_to_python_keeps_the_last_rust_version(self):
        for index, version in enumerate(("0.1.0", "0.2.0", "0.3.0", "0.4.0")):
            self.stub(version, mtime=1_600_000_000 + index * 1000)
        (self.root / ".pins").mkdir()
        (self.root / ".pins/echoport_remote_command_guard").write_text("0.1.0\n")
        self.write_keys(line(PYTHON_COMMAND))
        result = self.play(
            self.include("confirm_live.yml", "python", "", echoport_remote_command_guard_rust_keep_versions=1),
            fact_vars={"echoport_remote_command_guard_forced_command": PYTHON_COMMAND},
        )
        self.assertEqual(result["rc"], 0, result["out"])
        self.assertEqual(self.pins(), {"echoport_remote_command_guard.previous": "0.1.0\n"})
        self.assertEqual(self.versions(), ["0.1.0", "0.4.0"])

    def test_python_without_an_install_root_changes_nothing(self):
        self.write_keys(line(PYTHON_COMMAND))
        result = self.confirm("python")
        self.assertEqual(result["rc"], 0, result["out"])
        self.assertFalse(self.root.exists())
        self.assertEqual(result["recap"]["changed"], 0, result["out"])

    def test_python_pin_failure_only_warns(self):
        self.stub("0.1.0")
        (self.root / ".pins").mkdir()
        (self.root / ".pins/echoport_remote_command_guard").write_text("garbage\n")
        self.write_keys(line(PYTHON_COMMAND))
        result = self.confirm("python")
        self.assertEqual(result["rc"], 0, result["out"])
        self.assertIn("WARNING: moving the pins", result["out"])
        self.assertEqual(self.versions(), ["0.1.0"])
        # The same broken pin stops a Rust deployment.
        self.write_keys(line(rust_command("0.1.0", str(self.root))))
        result = self.confirm("rust", "0.1.0")
        self.assertNotEqual(result["rc"], 0)
        self.assertIn("no pin moved and nothing was pruned", result["out"])

    def test_invalid_rust_inputs_only_warn_with_python(self):
        # Rollback independence: a Rust mistake never blocks the switch back.
        self.stub("0.1.0")
        (self.root / ".pins").mkdir()
        (self.root / ".pins/echoport_remote_command_guard").write_text("0.1.0\n")
        self.write_keys(line(PYTHON_COMMAND))
        for extra in (
            {"echoport_remote_command_guard_rust_version": "not-a-version"},
            {"echoport_remote_command_guard_rust_install_root": "relative/root"},
            {"echoport_remote_command_guard_rust_install_root": "/a/../b"},
            {"echoport_remote_command_guard_rust_keep_versions": 0},
        ):
            with self.subTest(extra=extra):
                task = self.include("confirm_live.yml", "python")
                task["vars"].update(extra)
                result = self.play(task, fact_vars={"echoport_remote_command_guard_forced_command": PYTHON_COMMAND})
                self.assertEqual(result["rc"], 0, result["out"])
                self.assertIn("WARNING: the Rust inputs are invalid", result["out"])
                self.assertEqual(self.pins(), {"echoport_remote_command_guard": "0.1.0\n"})
                self.assertEqual(self.versions(), ["0.1.0"])
        # The line is still verified with impl python.
        self.write_keys(line(rust_command("0.1.0", str(self.root))))
        task = self.include("confirm_live.yml", "python", echoport_remote_command_guard_rust_version="bad")
        result = self.play(task, fact_vars={"echoport_remote_command_guard_forced_command": PYTHON_COMMAND})
        self.assertNotEqual(result["rc"], 0)
        # shadow and rust stop.
        task = self.include("confirm_live.yml", "rust", "not-a-version")
        result = self.play(task, fact_vars={"echoport_remote_command_guard_forced_command": rust_command("0.1.0", str(self.root))})
        self.assertNotEqual(result["rc"], 0)
        self.assertIn("needs a valid", result["out"])
        self.assertEqual(self.pins(), {"echoport_remote_command_guard": "0.1.0\n"})

    def test_idempotent(self):
        self.stub("0.1.0")
        self.write_keys(line(shadow_command("0.1.0", str(self.root))))
        self.assertEqual(self.confirm("shadow", "0.1.0")["rc"], 0)
        again = self.confirm("shadow", "0.1.0")
        self.assertEqual(again["rc"], 0, again["out"])
        self.assertEqual(again["recap"]["changed"], 0, again["out"])

    def test_check_mode_moves_no_pin_and_prunes_nothing(self):
        for index, version in enumerate(("0.1.0", "0.2.0", "0.3.0")):
            self.stub(version, mtime=1_600_000_000 + index * 1000)
        # Written already (a re-run) and not yet written (a switch preview).
        for command in (rust_command("0.3.0", str(self.root)), PYTHON_COMMAND):
            with self.subTest(command=command):
                self.write_keys(line(command))
                result = self.play(
                    self.include("confirm_live.yml", "rust", "0.3.0", echoport_remote_command_guard_rust_keep_versions=1),
                    fact_vars={"echoport_remote_command_guard_forced_command": rust_command("0.3.0", str(self.root))},
                    check=True,
                )
                self.assertEqual(result["rc"], 0, result["out"])
                self.assertEqual(self.pins(), {})
                self.assertEqual(self.versions(), ["0.1.0", "0.2.0", "0.3.0"])


if __name__ == "__main__":
    unittest.main()
