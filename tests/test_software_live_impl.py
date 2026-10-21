"""The software_live switch between Python and Rust (rust/software-live/PLAN.md 7.3, 8.1).

Slice S6:

- unit tests of the decisions in ``plugins/filter/software_live_impl.py`` (release
  variant, live state of step 0, verification of step 6, APT status);
- the drop-ins and shadow units rendered for both implementations and both
  variants, and the base units unchanged (they keep running Python);
- static checks of the role: task order (inputs before any change, Python
  rollback before any Rust task, pins and prune only after the
  verification), ``nyxmon_checks.py`` installed in every mode, no task
  ``environment:``, ``software_live_remove`` covering drop-ins and shadow
  units;
- the variable validation, run with ``ansible-playbook``;
- ``ansible-playbook`` runs against localhost of the real tail of
  ``tasks/main.yml`` (from the implementation selection to pins and prune)
  with fake release archives in a temporary install directory, a fake
  ``systemctl`` (``tests/fixtures/software_live_impl/fake_systemctl.py``), a
  fake ``/proc`` and cgroup tree: both directions of the switch, the
  rollback that a broken release never blocks, the rollback pin sequence
  v1 -> v2 -> v1 -> v3 -> v4 with ``keep_versions: 2``, protection of
  versions only the live state names (a drop-in left by a failed play, a
  collector run still executing an older release and its APT child), the
  fail-closed prune, the shadow units and idempotence.
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

import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/software_live"
REMOVE_ROLE = ROOT / "roles/software_live_remove"
FAKE_SYSTEMCTL = ROOT / "tests/fixtures/software_live_impl/fake_systemctl.py"
FQCN = "local.ops_library.software_live"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FILTERS = _load("software_live_filters", ROOT / "plugins/filter/software_live_impl.py")
RUST_RELEASE = _load("rust_release_filters", ROOT / "plugins/filter/rust_release.py")

ENDPOINT = "software-live-endpoint.service"
COLLECTOR = "software-live-collector.service"
SHADOW_ENDPOINT = "software-live-shadow-endpoint.service"
SHADOW_COLLECTOR = "software-live-shadow-collector.service"
UNITS = (ENDPOINT, COLLECTOR, SHADOW_ENDPOINT, SHADOW_COLLECTOR)
RELEASES = "/usr/local/lib/software-live/releases"
PATHS = {
    "dropins": [
        "/s/software-live-endpoint.service.d/impl.conf",
        "/s/software-live-collector.service.d/impl.conf",
    ],
    "units": [
        "/s/software-live-shadow-collector.service",
        "/s/software-live-shadow-endpoint.service",
    ],
    "pin": f"{RELEASES}/.pins/software-live",
    "shadow_pin": f"{RELEASES}/.pins/software-live-shadow",
}


def walk(tasks):
    for task in tasks or []:
        yield task
        for section in ("block", "rescue", "always"):
            yield from walk(task.get(section, []))


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def task_names(path: Path) -> list[str]:
    return [t.get("name", "") for t in walk(load_yaml(path))]


# --------------------------------------------------------------------------
# Filters
# --------------------------------------------------------------------------


def probe(
    *lines: str, rc: int = 0, units: tuple[str, ...] = UNITS, done: bool = True
) -> dict:
    """A process probe result: the given lines, then an idle line per unit."""

    out = list(lines)
    reported = {line.split("\t")[1] for line in lines if line.startswith("unit\t")}
    out += [f"unit\t{u}\tinactive\t0\t0\t" for u in units if u not in reported]
    if done:
        out.append("done")
    return {"rc": rc, "stdout_lines": out}


def files(**contents) -> list[dict]:
    """File records: every switch file absent unless given (path key -> text)."""

    records = []
    for path in PATHS["dropins"] + PATHS["units"] + [PATHS["pin"], PATHS["shadow_pin"]]:
        if path in contents:
            value = contents[path]
            if value is None:  # exists, unreadable
                records.append(
                    {"path": path, "exists": True, "isreg": True, "content": None}
                )
            else:
                records.append(
                    {"path": path, "exists": True, "isreg": True, "content": value}
                )
        else:
            records.append(
                {"path": path, "exists": False, "isreg": False, "content": None}
            )
    return records


def live(probe_result: dict | None = None, file_records: list | None = None) -> dict:
    return FILTERS.software_live_live_state(
        probe_result if probe_result is not None else probe(),
        file_records if file_records is not None else files(),
        [RELEASES],
        PATHS,
    )


DROPIN = "[Service]\nExecStart=\nExecStart={bin} serve --config /etc/software-live/endpoint.json\n"


class VariantTests(unittest.TestCase):
    def test_released_variants(self):
        self.assertEqual(
            FILTERS.software_live_variant('ID=ubuntu\nVERSION_ID="24.04"\n'),
            "ubuntu24.04",
        )
        self.assertEqual(
            FILTERS.software_live_variant("ID=debian\nVERSION_ID='13'\nID=debian\n"),
            "debian13",
        )
        text = 'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nNAME="Debian GNU/Linux"\nVERSION_ID="13"\nID=debian\n'
        self.assertEqual(FILTERS.software_live_variant(text), "debian13")

    def test_anything_else_has_no_variant(self):
        for text in (
            'ID=ubuntu\nVERSION_ID="22.04"\n',
            'ID=debian\nVERSION_ID="12"\n',
            "ID=fedora\nVERSION_ID=40\n",
            'ID=Ubuntu\nVERSION_ID="24.04"\n',
            'ID=ubuntu\nVERSION_ID="24.04.1"\n',
            "",
            None,
            3,
        ):
            self.assertEqual(FILTERS.software_live_variant(text), "", text)


class LiveStateTests(unittest.TestCase):
    def test_nothing_running_is_known_and_empty(self):
        state = live()
        self.assertEqual(
            state,
            {
                "versions": [],
                "unknown": [],
                "pin": "",
                "shadow_pin": "",
                "endpoint_version": "",
                "last_live": "",
            },
        )

    def test_python_processes_and_commands_name_nothing(self):
        state = live(
            probe(
                f"unit\t{ENDPOINT}\tactive\t100\t0\t/system.slice/{ENDPOINT}",
                f"prop\t{ENDPOINT}\tExecStart={{ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 /usr/local/lib/software-live/software_live.py serve ; }}",
                f"exe\t{ENDPOINT}\t100\t/usr/bin/python3.12",
            )
        )
        self.assertEqual(state["versions"], [])
        self.assertEqual(state["unknown"], [])
        self.assertEqual(state["last_live"], "")

    def test_dropins_and_shadow_units_name_their_versions(self):
        state = live(
            file_records=files(
                **{
                    PATHS["dropins"][0]: DROPIN.format(
                        bin=f"{RELEASES}/1.0.0/software-live"
                    ),
                    PATHS["dropins"][1]: (
                        "[Service]\nExecStart=\nExecStart = "
                        + RELEASES
                        + "/1.1.0/software-live collect --config x\n"
                        "ExecStartPost=\nExecStartPost=-"
                        + RELEASES
                        + "/1.2.0-rc.1/software-live export-inventory\n"
                    ),
                    PATHS["units"][
                        0
                    ]: f'[Service]\nExecStart="{RELEASES}/2.0.0/software-live" collect\n',
                }
            )
        )
        self.assertEqual(state["versions"], ["1.0.0", "1.1.0", "1.2.0-rc.1", "2.0.0"])
        self.assertEqual(state["unknown"], [])
        self.assertEqual(state["last_live"], "")

    def test_continuations_and_every_directive_count(self):
        """systemd joins a line ending in a backslash with the next one; a
        release path in any directive (ExecStartPre=, ExecReload=, an
        --opt=value) names its version."""

        state = live(
            file_records=files(
                **{
                    PATHS["dropins"][1]: (
                        "[Service]\nExecStart=\nExecStart=\\\n"
                        "  # a comment inside the continuation\n"
                        f"  {RELEASES}/1.0.0/software-live collect \\\n  --config /etc/software-live/policy.json\n"
                    ),
                    PATHS["dropins"][0]: (
                        f"[Service]\nExecStartPre=+{RELEASES}/1.1.0/software-live-apt observe\n"
                        f"ExecReload=/bin/sh -c 'exec {RELEASES}/1.2.0/software-live --version'\n"
                        f"Environment=HELPER=--helper={RELEASES}/1.3.0/software-live-apt\n"
                        f"# ExecStart={RELEASES}/9.9.9/software-live (a comment names nothing)\n"
                    ),
                }
            )
        )
        self.assertEqual(state["unknown"], [])
        self.assertEqual(state["versions"], ["1.0.0", "1.1.0", "1.2.0", "1.3.0"])
        bad = live(
            file_records=files(
                **{PATHS["dropins"][0]: f"ReadOnlyPaths={RELEASES}/1.0.0\n"}
            )
        )
        self.assertNotEqual(bad["unknown"], [])

    def test_unreadable_or_unparseable_files_make_the_state_unknown(self):
        for records in (
            files(**{PATHS["dropins"][0]: None}),
            files(**{PATHS["units"][1]: None}),
            files(
                **{
                    PATHS["dropins"][
                        1
                    ]: f"ExecStart={RELEASES}/latest/software-live collect\n"
                }
            ),
            files(
                **{
                    PATHS["dropins"][
                        0
                    ]: f"ExecStart={RELEASES}/1.0.0/sub/software-live serve\n"
                }
            ),
            files(
                **{
                    PATHS["units"][
                        0
                    ]: "ExecStart=/opt/elsewhere/software-live collect\n"
                }
            ),
            files(**{PATHS["pin"]: "1.0.0\n2.0.0\n"}),
            files(**{PATHS["shadow_pin"]: None}),
        ):
            with self.subTest(records=[r for r in records if r["exists"]]):
                self.assertNotEqual(live(file_records=records)["unknown"], [])

    def test_loaded_commands_count(self):
        state = live(
            probe(
                f"prop\t{COLLECTOR}\tExecStart={{ path={RELEASES}/0.9.0/software-live ; argv[]={RELEASES}/0.9.0/software-live collect ; }}",
            )
        )
        self.assertEqual(state["versions"], ["0.9.0"])

    def test_running_collector_and_its_apt_child_are_protected(self):
        state = live(
            probe(
                f"unit\t{COLLECTOR}\tactivating\t200\t0\t/system.slice/{COLLECTOR}",
                f"exe\t{COLLECTOR}\t200\t{RELEASES}/1.0.0/software-live",
                f"exe\t{COLLECTOR}\t201\t{RELEASES}/1.0.0/software-live-apt (deleted)",
                f"exe\t{SHADOW_COLLECTOR}\t300\t/private{RELEASES}/0.8.0/software-live-apt",
                f"root\t/private{RELEASES}",
            )
        )
        self.assertEqual(state["unknown"], [])
        self.assertEqual(state["versions"], ["0.8.0", "1.0.0"])

    def test_unresolvable_running_processes_make_the_state_unknown(self):
        cases = {
            "noexe": probe(
                f"unit\t{COLLECTOR}\tactive\t200\t0\t/x", f"noexe\t{COLLECTOR}\t200"
            ),
            "nocgroup": probe(
                f"unit\t{SHADOW_COLLECTOR}\tactivating\t0\t0\t",
                f"nocgroup\t{SHADOW_COLLECTOR}",
            ),
            "systemctl": probe(
                f"error\t{ENDPOINT}",
                units=(COLLECTOR, SHADOW_ENDPOINT, SHADOW_COLLECTOR),
            ),
            "alias": probe(f"exe\t{COLLECTOR}\t5\t/tmp/software-live-apt"),
            "outside version dir": probe(
                f"exe\t{ENDPOINT}\t5\t{RELEASES}/software-live"
            ),
            "probe failed": probe(rc=1),
            "truncated": probe(done=False),
            "unit missing": probe(units=(ENDPOINT,)),
            "garbage": probe("what"),
        }
        for label, result in cases.items():
            with self.subTest(label):
                self.assertNotEqual(live(result)["unknown"], [])

    def test_last_live_is_the_pin_else_the_endpoint_release(self):
        endpoint = probe(
            f"unit\t{ENDPOINT}\tactive\t100\t0\t/system.slice/{ENDPOINT}",
            f"exe\t{ENDPOINT}\t100\t{RELEASES}/1.0.0/software-live",
        )
        self.assertEqual(live(endpoint)["last_live"], "1.0.0")
        self.assertEqual(live(endpoint)["endpoint_version"], "1.0.0")
        state = live(
            endpoint, files(**{PATHS["pin"]: "0.9.0\n", PATHS["shadow_pin"]: "1.1.0\n"})
        )
        self.assertEqual(
            (state["last_live"], state["pin"], state["shadow_pin"]),
            ("0.9.0", "0.9.0", "1.1.0"),
        )
        # Another PID of the unit is not its MainPID.
        other = probe(
            f"unit\t{ENDPOINT}\tactive\t100\t0\t/system.slice/{ENDPOINT}",
            f"exe\t{ENDPOINT}\t101\t{RELEASES}/1.0.0/software-live",
        )
        self.assertEqual(live(other)["last_live"], "")

    def test_files_from_ansible_results(self):
        content = base64.b64encode(b"ExecStart=/x\n").decode()
        stats = [
            {"item": "/a", "stat": {"exists": True, "isreg": True, "islnk": False}},
            {"item": "/b", "stat": {"exists": False}},
            {"item": "/c", "stat": {"exists": True, "isreg": True}},
            {"item": "/d", "failed": True, "msg": "permission denied"},
        ]
        reads = [
            {"item": stats[0], "content": content},
            {"item": stats[1], "skipped": True},
            {"item": stats[2], "failed": True, "msg": "denied"},
            {"item": stats[3], "failed": True},
        ]
        self.assertEqual(
            FILTERS.software_live_files(stats, reads),
            [
                {
                    "path": "/a",
                    "exists": True,
                    "isreg": True,
                    "content": "ExecStart=/x\n",
                },
                {"path": "/b", "exists": False, "isreg": False, "content": None},
                {"path": "/c", "exists": True, "isreg": True, "content": None},
                {"path": "/d", "exists": True, "isreg": False, "content": None},
            ],
        )

    def test_version_grammar_matches_rust_release_binary(self):
        for value in (
            "1.0.0",
            "0.1.0-rc.1",
            "01.0.0",
            "1.0",
            "1.0.0+b",
            "1.0.0-",
            "v1.0.0",
            "10.20.30-alpha.1.x",
        ):
            self.assertEqual(
                FILTERS._version_ok(value),
                RUST_RELEASE.rust_release_version_ok(value),
                value,
            )


def verify_probe(*lines: str, rc: int = 0) -> dict:
    return {"rc": rc, "stdout_lines": list(lines) + ["done"]}


SCRIPT = "/usr/local/lib/software-live/software_live.py"
BIN = f"{RELEASES}/1.0.0/software-live"


class VerifyTests(unittest.TestCase):
    def python_ok(self) -> list[str]:
        return [
            f"unit\t{ENDPOINT}\tactive\t10\t0",
            f"exe\t{ENDPOINT}\t/usr/bin/python3.12",
            f"arg\t{ENDPOINT}\t/usr/bin/python3",
            f"arg\t{ENDPOINT}\t{SCRIPT}",
            f"arg\t{ENDPOINT}\tserve",
            f"arg\t{ENDPOINT}\t--config",
            f"arg\t{ENDPOINT}\t/etc/software-live/endpoint.json",
            f"unit\t{COLLECTOR}\tinactive\t0\t0",
            f"prop\t{COLLECTOR}\tExecStart={{ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 {SCRIPT} collect --config x ; }}",
        ]

    def rust_ok(self) -> list[str]:
        return [
            f"real\t/private{BIN}",
            f"unit\t{ENDPOINT}\tactive\t10\t0",
            f"exe\t{ENDPOINT}\t/private{BIN}",
            f"unit\t{COLLECTOR}\tinactive\t0\t0",
            f"prop\t{COLLECTOR}\tExecStart={{ path={BIN} ; argv[]={BIN} collect --config x ; }}",
        ]

    def check(self, lines, impl, shadow=False):
        return FILTERS.software_live_verify(
            verify_probe(*lines),
            {"impl": impl, "binary": BIN, "script": SCRIPT, "shadow": shadow},
        )

    def test_python(self):
        self.assertEqual(self.check(self.python_ok(), "python"), [])
        self.assertNotEqual(self.check(self.rust_ok(), "python"), [])

    def test_rust(self):
        self.assertEqual(self.check(self.rust_ok(), "rust"), [])
        self.assertNotEqual(self.check(self.python_ok(), "rust"), [])

    def test_failures(self):
        rust = self.rust_ok()
        cases = {
            "endpoint inactive": [
                line.replace("\tactive\t10", "\tfailed\t0") for line in rust
            ],
            "other release": [
                line.replace(
                    f"exe\t{ENDPOINT}\t/private{BIN}",
                    f"exe\t{ENDPOINT}\t{RELEASES}/0.9.0/software-live",
                )
                for line in rust
            ],
            "collector failed": [
                line.replace(
                    f"{COLLECTOR}\tinactive\t0\t0", f"{COLLECTOR}\tfailed\t0\t1"
                )
                for line in rust
            ],
            "collector still python": rust[:-1] + [self.python_ok()[-1]],
            "collector missing": rust[:3],
        }
        for label, lines in cases.items():
            with self.subTest(label):
                self.assertNotEqual(self.check(lines, "rust"), [])
        self.assertNotEqual(
            FILTERS.software_live_verify(
                {"rc": 1, "stdout_lines": []}, {"impl": "rust"}
            ),
            [],
        )
        truncated = {"rc": 0, "stdout_lines": rust}
        self.assertNotEqual(
            FILTERS.software_live_verify(truncated, {"impl": "rust", "binary": BIN}), []
        )

    def test_shadow_endpoint(self):
        shadow = [
            f"unit\t{SHADOW_ENDPOINT}\tactive\t20\t0",
            f"exe\t{SHADOW_ENDPOINT}\t{BIN}",
        ]
        self.assertEqual(
            self.check(self.python_ok() + shadow, "python", shadow=True), []
        )
        self.assertNotEqual(self.check(self.python_ok(), "python", shadow=True), [])
        self.assertNotEqual(
            self.check(self.python_ok() + shadow[:1], "python", shadow="True"), []
        )
        self.assertEqual(self.check(self.python_ok(), "python", shadow="False"), [])


class AptStatusTests(unittest.TestCase):
    def test_status(self):
        self.assertEqual(
            FILTERS.software_live_apt_status(
                '{"status": "ok", "pending_security_count": 0}'
            ),
            "ok",
        )
        self.assertEqual(
            FILTERS.software_live_apt_status('{"status": "unknown"}'), "unknown"
        )
        for text in ("", "[]", '{"status": 1}', "not json", None):
            self.assertEqual(FILTERS.software_live_apt_status(text), "")


# --------------------------------------------------------------------------
# Templates
# --------------------------------------------------------------------------

TEMPLATE_VARS = {
    "software_live_install_dir": "/usr/local/lib/software-live",
    "software_live_config_dir": "/etc/software-live",
    "software_live_data_dir": "/var/lib/software-live",
    "software_live_group": "metrics",
    "software_live_user": "metrics",
    "software_live_inventory_group": "software-estate-publisher",
    "software_live_on_calendar": "*:0/15",
    "software_live_shadow_on_calendar": "*:7/15",
    "_software_live_rust_binary": "/usr/local/lib/software-live/releases/0.1.0/software-live",
}


def render(name: str, **overrides) -> str:
    # Ansible's template module: trim_blocks on, no lstrip_blocks.
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(ROLE / "templates"),
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        keep_trailing_newline=True,
    )
    return env.get_template(name).render({**TEMPLATE_VARS, **overrides})


def directives(text: str, key: str) -> list[str]:
    return [
        line.split("=", 1)[1]
        for line in text.splitlines()
        if line.startswith(key + "=")
    ]


class TemplateTests(unittest.TestCase):
    BIN = "/usr/local/lib/software-live/releases/0.1.0/software-live"

    def test_endpoint_dropin(self):
        text = render("impl-endpoint.conf.j2", software_live_inventory_export=True)
        self.assertEqual(
            directives(text, "ExecStart"),
            ["", f"{self.BIN} serve --config /etc/software-live/endpoint.json"],
        )
        self.assertIn("[Service]", text)

    def test_collector_dropin_with_and_without_export(self):
        base_args = (
            "collect --config /etc/software-live/policy.json --output /var/lib/software-live/state.json"
            " --cache /var/lib/software-live/upstream.json --group metrics"
        )
        on = render("impl-collector.conf.j2", software_live_inventory_export=True)
        self.assertEqual(directives(on, "ExecStart"), ["", f"{self.BIN} {base_args}"])
        self.assertEqual(
            directives(on, "ExecStartPost"),
            [
                "",
                f"-{self.BIN} export-inventory --config /var/lib/software-live/state.json --output "
                "/var/lib/software-estate-observations/software-health.json --group software-estate-publisher",
            ],
        )
        off = render("impl-collector.conf.j2", software_live_inventory_export=False)
        self.assertEqual(directives(off, "ExecStartPost"), [""])

    def test_dropin_arguments_match_the_python_units(self):
        """Same arguments as the base units, only the program differs."""

        for export in (True, False):
            for base, dropin in (
                ("endpoint.service.j2", "impl-endpoint.conf.j2"),
                ("collector.service.j2", "impl-collector.conf.j2"),
            ):
                python = render(base, software_live_inventory_export=export)
                rust = render(dropin, software_live_inventory_export=export)
                for key in ("ExecStart", "ExecStartPost"):
                    want = [
                        v.replace(
                            f"/usr/bin/python3 {TEMPLATE_VARS['software_live_install_dir']}/software_live.py",
                            self.BIN,
                        )
                        for v in directives(python, key)
                    ]
                    got = [v for v in directives(rust, key) if v]
                    self.assertEqual(got, want, (base, key, export))

    def test_base_units_still_run_python(self):
        for name in ("endpoint.service.j2", "collector.service.j2"):
            for export in (True, False):
                for line in directives(
                    render(name, software_live_inventory_export=export), "ExecStart"
                ):
                    self.assertTrue(
                        line.startswith(
                            "/usr/bin/python3 /usr/local/lib/software-live/software_live.py "
                        )
                    )

    def test_shadow_units(self):
        collector = render(
            "shadow-collector.service.j2", software_live_inventory_export=True
        )
        self.assertEqual(
            directives(collector, "ExecStart"),
            [
                f"{self.BIN} collect --report-usage --config /etc/software-live/policy.json --output "
                "/var/lib/software-live/shadow/state.json --cache /var/lib/software-live/shadow/upstream.json --group metrics"
            ],
        )
        self.assertEqual(
            directives(collector, "ExecStartPost"),
            [
                f"-{self.BIN} export-inventory --config /var/lib/software-live/shadow/state.json --output "
                "/var/lib/software-live/shadow/software-health.json --group software-estate-publisher"
            ],
        )
        self.assertEqual(
            directives(collector, "ReadWritePaths"), ["/var/lib/software-live/shadow"]
        )
        production = render("collector.service.j2", software_live_inventory_export=True)
        for key in (
            "Type",
            "User",
            "TimeoutStartSec",
            "Nice",
            "UMask",
            "NoNewPrivileges",
            "ProtectSystem",
            "ProtectHome",
            "PrivateTmp",
            "ProtectKernelTunables",
            "ProtectKernelModules",
            "ProtectControlGroups",
        ):
            self.assertEqual(
                directives(collector, key), directives(production, key), key
            )
        self.assertEqual(
            directives(
                render(
                    "shadow-collector.service.j2", software_live_inventory_export=False
                ),
                "ExecStartPost",
            ),
            [],
        )
        timer = render("shadow-collector.timer.j2")
        self.assertEqual(directives(timer, "OnCalendar"), ["*:7/15"])
        self.assertEqual(
            directives(timer, "Unit"), ["software-live-shadow-collector.service"]
        )
        endpoint = render("shadow-endpoint.service.j2")
        self.assertEqual(
            directives(endpoint, "ExecStart"),
            [f"{self.BIN} serve --config /etc/software-live/shadow-endpoint.json"],
        )
        self.assertEqual(directives(endpoint, "IPAddressAllow"), ["localhost"])
        self.assertEqual(directives(endpoint, "IPAddressDeny"), ["any"])
        production = render("endpoint.service.j2")
        for key in (
            "Type",
            "User",
            "Group",
            "Restart",
            "NoNewPrivileges",
            "ProtectSystem",
            "CapabilityBoundingSet",
            "RestrictAddressFamilies",
            "PrivateTmp",
        ):
            self.assertEqual(
                directives(endpoint, key), directives(production, key), key
            )

    def test_release_url_per_variant(self):
        defaults = load_yaml(ROLE / "defaults/main.yml")
        env = jinja2.Environment(undefined=jinja2.StrictUndefined)
        for variant in ("ubuntu24.04", "debian13"):
            url = env.from_string(defaults["software_live_rust_release_url"]).render(
                software_live_rust_version="0.1.0", _software_live_variant=variant
            )
            self.assertEqual(
                url,
                "https://github.com/ephes/ops-library/releases/download/software-live-v0.1.0/"
                f"software-live-0.1.0-x86_64-unknown-linux-gnu-{variant}.tar.gz",
            )


# --------------------------------------------------------------------------
# Static checks of the role
# --------------------------------------------------------------------------


class RoleStaticTests(unittest.TestCase):
    def test_defaults(self):
        defaults = load_yaml(ROLE / "defaults/main.yml")
        self.assertEqual(defaults["software_live_impl"], "python")
        self.assertEqual(defaults["software_live_rust_version"], "")
        self.assertEqual(defaults["software_live_rust_sha256"], {})
        self.assertIs(defaults["software_live_rust_shadow"], False)
        self.assertEqual(defaults["software_live_rust_keep_versions"], 3)
        self.assertEqual(defaults["software_live_systemd_dir"], "/etc/systemd/system")
        self.assertEqual(defaults["software_live_proc_root"], "/proc")

    def test_main_order(self):
        names = task_names(ROLE / "tasks/main.yml")
        order = [
            "Validate the implementation selection",
            "Validate private IPv4 endpoint binding",
            "Install software observation dependencies",
            "Install software observation programs",
            "Configure software endpoint",
            "Select the software observation implementation",
            "Install software observation units",
            "Load software observation units",
            "Wait for a running software observation to finish",
            "Check the software observation before the initial collection",
            "Collect an initial software observation",
            "Enable software observation timer and endpoint",
            "Enable the shadow timer and endpoint",
            "Verify the running software observation implementation",
            "Pin and prune the software-live releases",
        ]
        self.assertEqual([n for n in names if n in order], order)
        self.assertEqual(names[-2:], order[-2:])

    def test_nyxmon_checks_installed_in_every_mode(self):
        for task in walk(load_yaml(ROLE / "tasks/main.yml")):
            if task.get("name") == "Install software observation programs":
                self.assertNotIn("when", task)
                self.assertEqual(task["loop"], ["software_live.py", "nyxmon_checks.py"])
                return
        self.fail("program install task missing")

    def test_rollback_comes_before_every_rust_task(self):
        names = task_names(ROLE / "tasks/impl.yml")
        self.assertLess(
            names.index("impl | Read the live state"),
            names.index("impl | Select the Python implementation"),
        )
        self.assertLess(
            names.index("impl | Restart the production units with Python now"),
            names.index("impl | Install and validate the Rust release"),
        )
        self.assertLess(
            names.index("impl | Install and validate the Rust release"),
            names.index("impl | Point the production units at the Rust release"),
        )
        flush = load_yaml(ROLE / "tasks/flush_handlers.yml")
        self.assertEqual(
            [t.get("ansible.builtin.meta") for t in flush], ["flush_handlers"]
        )

    def test_rust_inputs_are_checked_before_any_change_with_impl_rust(self):
        tasks = load_yaml(ROLE / "tasks/impl_inputs.yml")
        include = [
            t
            for t in tasks
            if t.get("ansible.builtin.include_tasks") == "rust_inputs.yml"
        ]
        self.assertEqual(include[0]["when"], "software_live_impl == 'rust'")
        rust = load_yaml(ROLE / "tasks/rust.yml")
        self.assertEqual(
            rust[0].get("ansible.builtin.include_tasks"), "rust_inputs.yml"
        )

    def test_install_uses_rust_release_binary(self):
        for task in walk(load_yaml(ROLE / "tasks/rust.yml")):
            if task.get("name") == "rust | Install the pinned software-live release":
                self.assertEqual(
                    task["ansible.builtin.include_role"]["tasks_from"], "install"
                )
                variables = task["vars"]
                self.assertEqual(
                    variables["rust_release_binary_members"],
                    [
                        "software-live",
                        "software-live-apt",
                        "LICENSE",
                        "LICENSE.GPL-3.0",
                    ],
                )
                self.assertEqual(
                    variables["rust_release_binary_executables"],
                    ["software-live", "software-live-apt"],
                )
                self.assertIs(variables["rust_release_binary_fail_hard"], True)
                self.assertEqual(
                    variables["rust_release_binary_install_root"],
                    "{{ _software_live_releases_dir }}",
                )
                return
        self.fail("install task missing")

    def test_no_task_environment_and_no_become_user(self):
        for path in sorted((ROLE / "tasks").glob("*.yml")):
            for task in walk(load_yaml(path)):
                self.assertNotIn("environment", task, (path.name, task.get("name")))
                self.assertNotIn(
                    "become_user", task, (path.name, task.get("name"))
                ) if path.name not in ("nyxmon.yml", "nyxmon_disable.yml") else None

    def test_pins_never_run_a_release_binary(self):
        for task in walk(load_yaml(ROLE / "tasks/rust_pins.yml")):
            modules = {k for k in task if k.startswith("ansible.")}
            self.assertEqual(
                modules, {"ansible.builtin.include_role"}, task.get("name")
            )
            self.assertIn(
                task["ansible.builtin.include_role"]["tasks_from"], ("pin", "prune")
            )

    def test_notified_handlers_exist(self):
        handlers = {h["name"] for h in load_yaml(ROLE / "handlers/main.yml")}
        for path in sorted((ROLE / "tasks").glob("*.yml")):
            for task in walk(load_yaml(path)):
                notify = task.get("notify", [])
                for name in [notify] if isinstance(notify, str) else notify:
                    self.assertIn(name, handlers, (path.name, task.get("name")))
        # The reload runs first (handlers run in definition order).
        self.assertEqual(
            load_yaml(ROLE / "handlers/main.yml")[0]["name"],
            "Reload software live systemd",
        )

    def test_remove_role_covers_dropins_and_shadow_units(self):
        text = (REMOVE_ROLE / "tasks/main.yml").read_text()
        for name in (
            "software-live-endpoint.service.d",
            "software-live-collector.service.d",
            "software-live-shadow-collector.timer",
            "software-live-shadow-collector.service",
            "software-live-shadow-endpoint.service",
            "{{ software_live_remove_data_dir }}/shadow",
        ):
            self.assertIn(name, text)
        names = task_names(REMOVE_ROLE / "tasks/main.yml")
        self.assertLess(
            names.index("Stop and disable installed software observation units"),
            names.index(
                "Remove the implementation drop-ins of the software observation units"
            ),
        )
        self.assertEqual(names[-1], "Reload systemd after software observation removal")


# --------------------------------------------------------------------------
# ansible-playbook helpers
# --------------------------------------------------------------------------

RECAP = re.compile(
    r"^localhost\s+:\s+ok=(\d+)\s+changed=(\d+)\s+unreachable=(\d+)\s+failed=(\d+)\s+"
    r"skipped=(\d+)\s+rescued=(\d+)\s+ignored=(\d+)",
    re.M,
)


def _gnu_mv_dir(base: Path) -> Path | None:
    """A PATH entry whose `mv` is GNU mv (rust_release_binary needs it)."""

    probe_mv = subprocess.run(["mv", "--version"], capture_output=True, text=True)
    if probe_mv.returncode == 0 and "GNU" in probe_mv.stdout:
        return None
    gmv = shutil.which("gmv")
    if gmv is None:
        raise unittest.SkipTest(
            "GNU mv (gmv) not found; rust_release_binary targets GNU coreutils"
        )
    shim = base / "gnu-bin"
    shim.mkdir()
    (shim / "mv").symlink_to(gmv)
    return shim


def ansible_env(base: Path, extra_path: list[Path]) -> dict[str, str]:
    collections = base / "collections/ansible_collections/local"
    collections.mkdir(parents=True)
    (collections / "ops_library").symlink_to(ROOT)
    path = os.pathsep.join([str(p) for p in extra_path] + [os.environ.get("PATH", "")])
    return {
        **os.environ,
        "PATH": path,
        "ANSIBLE_COLLECTIONS_PATH": str(base / "collections"),
        "ANSIBLE_NOCOLOR": "1",
        "ANSIBLE_LOCALHOST_WARNING": "0",
        "ANSIBLE_INVENTORY_UNPARSED_WARNING": "0",
        "ANSIBLE_STDOUT_CALLBACK": "default",
        "ANSIBLE_RETRY_FILES_ENABLED": "0",
        "ANSIBLE_LOCAL_TEMP": str(base / "ansible-local"),
        "ANSIBLE_REMOTE_TEMP": str(base / "ansible-remote"),
        "ANSIBLE_PIPELINING": "1",
        "ANSIBLE_PYTHON_INTERPRETER": sys.executable,
        "no_proxy": "*",
        "NO_PROXY": "*",
    }


def run_playbook(path: Path, env: dict[str, str], check: bool = False) -> dict:
    argv = ["ansible-playbook", "-i", "localhost,", "-c", "local", str(path)]
    if check:
        argv.append("--check")
    result = subprocess.run(
        argv,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=env,
        timeout=900,
    )
    out = result.stdout + result.stderr
    match = RECAP.search(result.stdout)
    assert match is not None, out
    keys = ("ok", "changed", "unreachable", "failed", "skipped", "rescued", "ignored")
    return {
        "rc": result.returncode,
        "out": out,
        "recap": dict(zip(keys, map(int, match.groups()))),
    }


def build_archive(path: Path, version: str, salt: str = "") -> str:
    """A fake software-live release archive (PLAN.md 7.2); returns its sha256."""

    main = (
        "#!/bin/sh\n"
        f"# {salt}\n"
        'case "$1" in\n'
        f"  --version) echo 'software-live {version} (0123456789abcdef0123456789abcdef01234567)'; exit 0 ;;\n"
        "  validate) if [ -e \"$FAKE_SYSTEMD_STATE/validate-fails\" ]; then echo 'invalid policy' >&2; exit 1; fi; exit 0 ;;\n"
        "esac\n"
        "exit 0\n"
    ).encode()
    apt = (
        "#!/bin/sh\n"
        'printf \'%s\\n\' "$@" > "$FAKE_SYSTEMD_STATE/apt.argv"\n'
        'if [ -e "$FAKE_SYSTEMD_STATE/apt-unknown" ]; then\n'
        '  echo \'{"status": "unknown", "error": "APT observation failed (CacheOpen)"}\'\n'
        "  exit 0\n"
        "fi\n"
        'echo \'{"status": "ok", "pending_security_count": 0, "pending_security_updates": []}\'\n'
    ).encode()
    members = {
        "software-live": (main, 0o755),
        "software-live-apt": (apt, 0o755),
        "LICENSE": (b"MIT License\n", 0o644),
        "LICENSE.GPL-3.0": (b"GNU GENERAL PUBLIC LICENSE\n", 0o644),
    }
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, (data, mode) in members.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), mode, 1700000000
            tar.addfile(info, io.BytesIO(data))
    path.write_bytes(buffer.getvalue())
    return hashlib.sha256(buffer.getvalue()).hexdigest()


def main_tail() -> list[dict]:
    """The tasks of tasks/main.yml from the implementation selection to the
    end (and the selection's input check), as a play outside the role runs
    them: an include of a role task file becomes include_role tasks_from, the
    unit templates get the role's template directory."""

    tasks = load_yaml(ROLE / "tasks/main.yml")
    names = [t.get("name") for t in tasks]
    selected = [tasks[names.index("Validate the implementation selection")]]
    selected += tasks[names.index("Select the software observation implementation") :]
    converted = []
    for task in selected:
        task = json.loads(json.dumps(task))
        if "ansible.builtin.include_tasks" in task:
            tasks_from = task.pop("ansible.builtin.include_tasks").removesuffix(".yml")
            task["ansible.builtin.include_role"] = {
                "name": FQCN,
                "tasks_from": tasks_from,
            }
        if "ansible.builtin.template" in task:
            # The tests run unprivileged: the role's root:root becomes the
            # test user (as the role's own *_owner knobs do elsewhere).
            task["ansible.builtin.template"].update(
                src=str(ROLE / "templates") + "/{{ item.src }}",
                owner="{{ software_live_rust_owner }}",
                group="{{ software_live_rust_group }}",
            )
        converted.append(task)
    return converted


# --------------------------------------------------------------------------
# ansible-playbook runs of the switch
# --------------------------------------------------------------------------


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not on PATH")
@unittest.skipUnless(shutil.which("realpath"), "realpath not on PATH")
class SwitchPlaybookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name)
        fakes = cls.base / "fake-bin"
        fakes.mkdir()
        systemctl = fakes / "systemctl"
        systemctl.write_text(f"#!{sys.executable}\n" + FAKE_SYSTEMCTL.read_text())
        systemctl.chmod(0o755)
        shim = _gnu_mv_dir(cls.base)
        cls.env_base = ansible_env(cls.base, [fakes] + ([shim] if shim else []))
        cls.owner = pwd.getpwuid(os.getuid()).pw_name
        cls.group = grp.getgrgid(os.getgid()).gr_name
        cls.archives: dict[str, tuple[Path, str]] = {}
        cls.tail = main_tail()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(dir=self.base))
        self.state = self.work / "state"
        self.systemd = self.work / "systemd"
        self.proc = self.work / "proc"
        self.cgroup = self.work / "cgroup"
        self.install = self.work / "usr/local/lib/software-live"
        self.config = self.work / "etc/software-live"
        self.data = self.work / "var/lib/software-live"
        for path in (
            self.state,
            self.systemd,
            self.proc,
            self.cgroup,
            self.install,
            self.config,
            self.data,
        ):
            path.mkdir(parents=True)
        (self.config / "policy.json").write_text("{}\n")
        self.os_release = self.work / "os-release"
        self.os_release.write_text(
            'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nID=debian\nVERSION_ID="13"\n'
        )
        self.env = {
            **self.env_base,
            "FAKE_SYSTEMD_STATE": str(self.state),
            "FAKE_SYSTEMD_DIR": str(self.systemd),
            "FAKE_PROC": str(self.proc),
            "FAKE_CGROUP": str(self.cgroup),
        }
        self.runs = 0

    # -- helpers ---------------------------------------------------------------

    @property
    def releases(self) -> Path:
        return self.install / "releases"

    def archive(self, version: str, salt: str = "") -> tuple[Path, str]:
        key = version + salt
        if key not in self.archives:
            path = self.base / f"software-live-{key}.tar.gz"
            self.archives[key] = (path, build_archive(path, version, salt))
        return self.archives[key]

    def play(
        self,
        impl: str,
        version: str = "",
        *,
        shadow: bool = False,
        keep: int = 2,
        check: bool = False,
        archive: str | None = None,
        sha256: str | None = None,
        **overrides,
    ) -> dict:
        self.runs += 1
        variables = {
            "software_live_impl": impl,
            "software_live_rust_shadow": shadow,
            "software_live_rust_version": version,
            "software_live_rust_keep_versions": keep,
            "software_live_install_dir": str(self.install),
            "software_live_config_dir": str(self.config),
            "software_live_data_dir": str(self.data),
            "software_live_systemd_dir": str(self.systemd),
            "software_live_proc_root": str(self.proc),
            "software_live_cgroup_root": str(self.cgroup),
            "software_live_os_release_path": str(self.os_release),
            "software_live_rust_owner": self.owner,
            "software_live_rust_group": self.group,
            "software_live_rust_version_check_user": "",
            "software_live_user": self.owner,
            "software_live_group": self.group,
            "software_live_inventory_export": True,
            "software_live_inventory_group": self.group,
            "software_live_auth_user": "monitor",
            "software_live_policy": {"host": "demo", "apt_max_age_seconds": 172800},
            "software_live_verify_retries": 2,
            "software_live_verify_delay": 0,
        }
        if version:
            path, sha = self.archive(version)
            variables["software_live_rust_local_archive"] = (
                str(path) if archive is None else archive
            )
            variables["software_live_rust_sha256"] = {
                "debian13": sha if sha256 is None else sha256
            }
        variables.update(overrides)
        facts = self.work / f"facts-{self.runs}.json"
        play = {
            "hosts": "localhost",
            "gather_facts": False,
            # The tail of main.yml runs outside the role: it gets the role's
            # defaults as play variables.
            "vars": {**load_yaml(ROLE / "defaults/main.yml"), **variables},
            "tasks": [
                {"name": "role tail", "block": self.tail},
                {
                    "name": "dump facts",
                    "ansible.builtin.copy": {
                        "dest": str(facts),
                        "mode": "0644",
                        "content": (
                            "{{ {'live': _software_live_live | default(None),"
                            " 'pins': rust_release_binary_pins | default(None),"
                            " 'prune': rust_release_binary_prune | default(None)} | to_json }}"
                        ),
                    },
                    "check_mode": False,
                    "changed_when": False,
                },
            ],
            "handlers": load_yaml(ROLE / "handlers/main.yml"),
        }
        path = self.work / f"play-{self.runs}.yml"
        path.write_text(yaml.safe_dump([play], sort_keys=False), encoding="utf-8")
        (self.state / "starts.log").write_text("")
        result = run_playbook(path, self.env, check=check)
        result["facts"] = json.loads(facts.read_text()) if facts.exists() else None
        result["starts"] = (self.state / "starts.log").read_text().splitlines()
        return result

    def ok(self, *args, **kwargs) -> dict:
        result = self.play(*args, **kwargs)
        self.assertEqual(result["rc"], 0, result["out"])
        self.assertEqual(result["recap"]["failed"], 0, result["out"])
        return result

    def failed(self, *args, **kwargs) -> dict:
        result = self.play(*args, **kwargs)
        self.assertNotEqual(result["rc"], 0, result["out"])
        self.assertEqual(result["recap"]["failed"], 1, result["out"])
        return result

    def world(self) -> dict:
        return json.loads((self.state / "world.json").read_text())

    def save_world(self, world: dict) -> None:
        (self.state / "world.json").write_text(json.dumps(world))

    def pins(self) -> dict[str, str]:
        pins = self.releases / ".pins"
        return (
            {p.name: p.read_text().strip() for p in sorted(pins.iterdir())}
            if pins.exists()
            else {}
        )

    def versions(self) -> list[str]:
        if not self.releases.exists():
            return []
        return sorted(
            p.name
            for p in self.releases.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )

    def binary(self, version: str, name: str = "software-live") -> str:
        return f"{self.releases}/{version}/{name}"

    def dropin(self, unit: str) -> Path:
        return self.systemd / f"{unit}.d/impl.conf"

    def endpoint_exe(self, unit: str = ENDPOINT) -> str:
        pid = self.world()["units"][unit]["main"]
        return os.readlink(self.proc / str(pid) / "exe")

    def endpoint_args(self, unit: str = ENDPOINT) -> list[str]:
        pid = self.world()["units"][unit]["main"]
        return (self.proc / str(pid) / "cmdline").read_bytes().decode().split("\0")[:-1]

    def assert_python(self) -> None:
        self.assertFalse(self.dropin(ENDPOINT).exists())
        self.assertFalse(self.dropin(COLLECTOR).exists())
        self.assertEqual(self.endpoint_exe(), "/usr/bin/python3.12")
        self.assertEqual(
            self.endpoint_args()[1:3], [f"{self.install}/software_live.py", "serve"]
        )

    def assert_rust(self, version: str) -> None:
        self.assertEqual(self.endpoint_exe(), os.path.realpath(self.binary(version)))
        self.assertIn(
            f"ExecStart={self.binary(version)} serve", self.dropin(ENDPOINT).read_text()
        )
        self.assertIn(
            f"ExecStart={self.binary(version)} collect",
            self.dropin(COLLECTOR).read_text(),
        )

    def plant_run(
        self,
        unit: str,
        version: str | None,
        children: tuple[str, ...] = ("software-live", "software-live-apt"),
        state: str = "activating",
        finish_after: int | None = None,
    ) -> list[int]:
        """A run of `unit` still in progress, executing release `version`
        (None: a PID whose executable cannot be resolved); with
        `finish_after` it ends after that many more `systemctl show` calls."""

        world = (
            self.world()
            if (self.state / "world.json").exists()
            else {"units": {}, "next_pid": 1000}
        )
        info = world["units"].setdefault(
            unit,
            {
                "active": "inactive",
                "main": 0,
                "control": 0,
                "cgroup": "",
                "status": 0,
                "enabled": False,
                "loaded": None,
                "pids": [],
            },
        )
        pids = []
        for name in children:
            pid = world["next_pid"]
            world["next_pid"] += 1
            directory = self.proc / str(pid)
            directory.mkdir(parents=True)
            if version is not None:
                (directory / "exe").symlink_to(
                    os.path.realpath(self.binary(version, name))
                )
            pids.append(pid)
        info.update(
            active=state,
            main=pids[0],
            cgroup=f"/system.slice/{unit}",
            pids=pids,
            finish_after=finish_after,
        )
        procs = self.cgroup / "system.slice" / unit / "cgroup.procs"
        procs.parent.mkdir(parents=True, exist_ok=True)
        procs.write_text("".join(f"{pid}\n" for pid in pids))
        self.save_world(world)
        return pids

    # -- Python --------------------------------------------------------------

    def test_python_first_deploy_and_rerun(self):
        first = self.ok("python")
        self.assert_python()
        self.assertFalse(self.releases.exists())
        self.assertEqual(first["recap"]["ignored"], 0, first["out"])
        second = self.ok("python")
        self.assertEqual(second["recap"]["changed"], 0, second["out"])
        self.assertEqual(second["starts"], [COLLECTOR])  # only the initial collection
        self.assertFalse(self.releases.exists())

    # -- both directions -------------------------------------------------------

    def test_switch_to_rust_and_back_to_python(self):
        self.ok("python")
        first = self.ok("rust", "1.0.0")
        self.assert_rust("1.0.0")
        self.assertEqual(self.pins(), {"software-live": "1.0.0"})
        self.assertEqual(
            sorted(os.listdir(self.releases / "1.0.0")),
            [
                ".archive-sha256",
                "LICENSE",
                "LICENSE.GPL-3.0",
                "software-live",
                "software-live-apt",
            ],
        )
        self.assertIn(
            f"{COLLECTOR} {self.binary('1.0.0')}",
            (self.state / "collector-runs.log").read_text(),
        )
        # The APT check of the candidate got the policy's age budget.
        self.assertEqual(
            (self.state / "apt.argv").read_text().splitlines()[:3],
            ["observe", "--max-age", "172800"],
        )
        self.assertIn(ENDPOINT, first["starts"])

        rerun = self.ok("rust", "1.0.0")
        self.assertEqual(rerun["recap"]["changed"], 0, rerun["out"])
        self.assertEqual(rerun["starts"], [COLLECTOR])

        back = self.ok("python", "1.0.0")
        self.assert_python()
        # The production pin is gone, the last Rust version is the rollback pin and stays installed.
        self.assertEqual(self.pins(), {"software-live.previous": "1.0.0"})
        self.assertEqual(self.versions(), ["1.0.0"])
        self.assertIn(ENDPOINT, back["starts"])
        again = self.ok("python", "1.0.0")
        self.assertEqual(again["recap"]["changed"], 0, again["out"])

    def test_rollback_pin_sequence_with_keep_versions_2(self):
        """PLAN.md 7.3: v1 -> v2 -> v1 -> v3 keeps v1 (previous) next to v3 and
        v2; v4 then keeps v3 as previous and prunes v1 and v2."""

        self.ok("rust", "1.0.0")
        self.ok("rust", "2.0.0")
        self.assertEqual(
            self.pins(), {"software-live": "2.0.0", "software-live.previous": "1.0.0"}
        )
        self.ok("rust", "1.0.0")
        self.assertEqual(
            self.pins(), {"software-live": "1.0.0", "software-live.previous": "2.0.0"}
        )
        self.ok("rust", "3.0.0")
        self.assert_rust("3.0.0")
        self.assertEqual(
            self.pins(), {"software-live": "3.0.0", "software-live.previous": "1.0.0"}
        )
        self.assertEqual(self.versions(), ["1.0.0", "2.0.0", "3.0.0"])
        result = self.ok("rust", "4.0.0")
        self.assertEqual(
            self.pins(), {"software-live": "4.0.0", "software-live.previous": "3.0.0"}
        )
        self.assertEqual(self.versions(), ["3.0.0", "4.0.0"])
        self.assertEqual(
            sorted(result["facts"]["prune"]["removed"]), ["1.0.0", "2.0.0"]
        )

    def test_previous_without_a_pin_comes_from_the_running_endpoint(self):
        self.ok("rust", "1.0.0")
        (self.releases / ".pins/software-live").unlink()
        self.ok("rust", "2.0.0")
        self.assertEqual(
            self.pins(), {"software-live": "2.0.0", "software-live.previous": "1.0.0"}
        )

    # -- protection by the live state ------------------------------------------

    def test_running_collector_keeps_its_release(self):
        """Mandatory (owner decision 2026-10-21): a collector run still
        executing v1 (and its software-live-apt child) after its unit, the
        endpoint and both pins moved on keeps v1 installed."""

        self.ok("rust", "1.0.0")
        # The run outlives step 0 and ends while the play waits before the
        # initial collection (the third `show` after step 0's).
        self.plant_run(COLLECTOR, "1.0.0", finish_after=4)
        first = self.ok("rust", "2.0.0")
        self.assertIn(
            "FAILED - RETRYING: [localhost]: Wait for a running software observation to finish",
            first["out"],
        )
        # The initial collection ran v2, not the merged v1 run.
        self.assertTrue(
            (self.state / "collector-runs.log")
            .read_text()
            .splitlines()[-1]
            .endswith(self.binary("2.0.0"))
        )
        self.assertEqual(
            self.pins(), {"software-live": "2.0.0", "software-live.previous": "1.0.0"}
        )
        # v1 still runs while v3 is deployed: no pin names it any more.
        self.plant_run(COLLECTOR, "1.0.0", finish_after=4)
        result = self.ok("rust", "3.0.0")
        self.assertEqual(
            self.pins(), {"software-live": "3.0.0", "software-live.previous": "2.0.0"}
        )
        self.assertEqual(self.versions(), ["1.0.0", "2.0.0", "3.0.0"])
        self.assertIn("1.0.0", result["facts"]["live"]["versions"])
        self.assertEqual(result["facts"]["prune"]["removed"], [])
        # Once the run is over, a later deploy prunes it.
        self.ok("rust", "3.0.0")
        self.assertEqual(self.versions(), ["2.0.0", "3.0.0"])

    def test_running_shadow_collector_keeps_its_release(self):
        """The same for a shadow collector run (its timer is not started by
        the play, so the run is still in progress at prune time)."""

        self.ok("python", "1.0.0", shadow=True)
        self.assertEqual(self.pins(), {"software-live-shadow": "1.0.0"})
        self.plant_run(SHADOW_COLLECTOR, "1.0.0", children=("software-live-apt",))
        self.ok("python", "2.0.0", shadow=True)
        self.plant_run(SHADOW_COLLECTOR, "1.0.0", children=("software-live-apt",))
        self.ok("python", "3.0.0", shadow=True)
        self.assertEqual(self.pins(), {"software-live-shadow": "3.0.0"})
        self.assertEqual(self.versions(), ["1.0.0", "2.0.0", "3.0.0"])

    def test_unresolvable_running_collector_skips_the_prune(self):
        self.ok("rust", "1.0.0")
        self.ok("rust", "2.0.0")
        self.plant_run(SHADOW_COLLECTOR, None, children=("software-live",))
        result = self.ok("rust", "3.0.0", keep=2)
        self.assertEqual(self.versions(), ["1.0.0", "2.0.0", "3.0.0"])
        self.assertTrue(result["facts"]["prune"]["skipped"], result["out"])
        self.assertEqual(result["recap"]["ignored"], 1, result["out"])
        self.assertEqual(
            self.pins(), {"software-live": "3.0.0", "software-live.previous": "2.0.0"}
        )

    def test_running_unit_without_listable_cgroup_skips_the_prune(self):
        self.ok("rust", "1.0.0")
        self.ok("rust", "2.0.0")
        world = self.world()
        world["units"].setdefault(
            SHADOW_COLLECTOR,
            {
                "main": 0,
                "control": 0,
                "status": 0,
                "enabled": False,
                "loaded": None,
                "pids": [],
            },
        )
        world["units"][SHADOW_COLLECTOR].update(
            active="activating", cgroup="/system.slice/gone.service"
        )
        self.save_world(world)
        result = self.ok("rust", "3.0.0")
        self.assertEqual(self.versions(), ["1.0.0", "2.0.0", "3.0.0"])
        self.assertTrue(result["facts"]["prune"]["skipped"])

    def test_dropin_of_a_failed_play_protects_its_release(self):
        self.ok("rust", "1.0.0")
        # v2's units do not come up: the endpoint keeps running v1's image.
        (self.state / f"exe-override-{ENDPOINT}").write_text(self.binary("1.0.0"))
        failed = self.failed("rust", "2.0.0")
        self.assertIn("do not run the selected implementation", failed["out"])
        # Neither pin moved, nothing was pruned.
        self.assertEqual(self.pins(), {"software-live": "1.0.0"})
        self.assertEqual(self.versions(), ["1.0.0", "2.0.0"])
        (self.state / f"exe-override-{ENDPOINT}").unlink()
        # v3 is fine; v2 is named only by the drop-in v3 replaces.
        self.ok("rust", "3.0.0", keep=2)
        self.assertEqual(
            self.pins(), {"software-live": "3.0.0", "software-live.previous": "1.0.0"}
        )
        self.assertEqual(self.versions(), ["1.0.0", "2.0.0", "3.0.0"])

    def test_unreadable_or_unparseable_dropin_skips_the_prune(self):
        self.ok("rust", "1.0.0")
        self.ok("rust", "2.0.0")
        self.dropin(COLLECTOR).write_text(
            f"[Service]\nExecStart=\nExecStart={self.releases}/current/software-live collect\n"
        )
        result = self.ok("rust", "3.0.0")
        self.assertEqual(self.versions(), ["1.0.0", "2.0.0", "3.0.0"])
        self.assertTrue(result["facts"]["prune"]["skipped"])
        self.ok("rust", "3.0.0")
        self.assertEqual(self.versions(), ["2.0.0", "3.0.0"])
        # A shadow unit that exists but cannot be read (a dangling link).
        (self.systemd / SHADOW_COLLECTOR).symlink_to(self.work / "nowhere")
        result = self.ok("rust", "4.0.0", shadow=True)
        self.assertEqual(self.versions(), ["2.0.0", "3.0.0", "4.0.0"])
        self.assertIn("cannot be read", json.dumps(result["facts"]["live"]["unknown"]))

    # -- rollback is never blocked --------------------------------------------

    def test_python_rollback_with_a_missing_archive_shadow_off(self):
        self.ok("rust", "1.0.0")
        result = self.ok("python", "2.0.0", archive=str(self.base / "missing.tar.gz"))
        self.assert_python()
        self.assertEqual(self.pins(), {"software-live.previous": "1.0.0"})
        self.assertEqual(self.versions(), ["1.0.0"])
        # No Rust task ran: impl python without the shadow needs no release.
        self.assertNotIn("rust | ", result["out"])

    def test_python_rollback_with_a_broken_candidate_shadow_off(self):
        self.ok("rust", "1.0.0")
        (self.state / "validate-fails").write_text("")
        (self.state / "apt-unknown").write_text("")
        self.ok("python", "2.0.0")
        self.assert_python()
        self.assertEqual(self.versions(), ["1.0.0"])

    def test_python_rollback_with_a_missing_archive_shadow_on(self):
        self.ok("rust", "1.0.0")
        result = self.failed(
            "python", "2.0.0", shadow=True, archive=str(self.base / "missing.tar.gz")
        )
        self.assertIn("Install the pinned software-live release", result["out"])
        # The production units run Python although the shadow failed.
        self.assert_python()
        self.assertEqual(self.pins(), {"software-live": "1.0.0"})  # step 7 not reached
        self.assertEqual(self.versions(), ["1.0.0"])

    def test_python_rollback_with_a_broken_candidate_shadow_on(self):
        self.ok("rust", "1.0.0")
        (self.state / "apt-unknown").write_text("")
        result = self.failed("python", "2.0.0", shadow=True)
        self.assertIn(
            "software-live-apt observe exited 0 with status unknown", result["out"]
        )
        self.assert_python()
        self.assertFalse((self.systemd / SHADOW_ENDPOINT).exists())
        self.assertEqual(self.versions(), ["1.0.0", "2.0.0"])

    def test_python_rollback_with_an_unknown_variant_shadow_on(self):
        self.ok("rust", "1.0.0")
        self.os_release.write_text('ID=ubuntu\nVERSION_ID="22.04"\n')
        result = self.failed("python", "1.0.0", shadow=True)
        self.assertIn("released variant", result["out"])
        self.assert_python()

    # -- impl rust refusals ----------------------------------------------------

    def test_rust_refusals_change_nothing(self):
        self.ok("python")
        for label, kwargs, flag in (
            ("validate", {}, "validate-fails"),
            ("apt", {}, "apt-unknown"),
            ("checksum", {"sha256": "0" * 64}, None),
        ):
            with self.subTest(label):
                if flag:
                    (self.state / flag).write_text("")
                result = self.failed("rust", "1.0.0", **kwargs)
                if flag:
                    (self.state / flag).unlink()
                self.assert_python()
                self.assertEqual(self.pins(), {})
                self.assertNotIn(ENDPOINT, result["starts"])
        self.os_release.write_text('ID=ubuntu\nVERSION_ID="22.04"\n')
        result = self.failed("rust", "1.0.0")
        self.assertIn("released variant", result["out"])
        self.assert_python()

    def test_variable_validation(self):
        for overrides in (
            {"software_live_impl": "shadow"},
            {"software_live_rust_shadow": "yes"},
            {"software_live_rust_keep_versions": 1},
            {"software_live_shadow_port": 9110},
        ):
            with self.subTest(overrides):
                result = self.play("python", **overrides)
                self.assertNotEqual(result["rc"], 0, result["out"])
                self.assertFalse(self.dropin(ENDPOINT).exists())
        result = self.play("rust", "")
        self.assertNotEqual(result["rc"], 0)
        self.assertIn("software_live_rust_version", result["out"])
        self.assertFalse((self.systemd / ENDPOINT).exists())

    # -- shadow ----------------------------------------------------------------

    def test_shadow_on_and_off(self):
        self.ok("python")
        on = self.ok("python", "1.0.0", shadow=True)
        self.assert_python()
        self.assertEqual(
            self.endpoint_exe(SHADOW_ENDPOINT), os.path.realpath(self.binary("1.0.0"))
        )
        self.assertEqual(
            self.endpoint_args(SHADOW_ENDPOINT)[1:],
            ["serve", "--config", f"{self.config}/shadow-endpoint.json"],
        )
        config = json.loads((self.config / "shadow-endpoint.json").read_text())
        self.assertEqual(
            (config["bind"], config["port"], config["state"]),
            ("127.0.0.1", 9119, f"{self.data}/state.json"),
        )
        self.assertTrue((self.data / "shadow").is_dir())
        self.assertEqual(self.pins(), {"software-live-shadow": "1.0.0"})
        self.assertTrue(
            self.world()["units"]["software-live-shadow-collector.timer"]["enabled"]
        )
        self.assertIn(SHADOW_ENDPOINT, on["starts"])
        rerun = self.ok("python", "1.0.0", shadow=True)
        self.assertEqual(rerun["recap"]["changed"], 0, rerun["out"])
        # The shadow moves to 2.0.0 without a rollback pin.
        self.ok("python", "2.0.0", shadow=True)
        self.assertEqual(self.pins(), {"software-live-shadow": "2.0.0"})
        off = self.ok("python", "2.0.0", shadow=False)
        for name in (
            "software-live-shadow-collector.timer",
            SHADOW_COLLECTOR,
            SHADOW_ENDPOINT,
        ):
            self.assertFalse((self.systemd / name).exists(), name)
        self.assertFalse((self.data / "shadow").exists())
        self.assertFalse((self.config / "shadow-endpoint.json").exists())
        self.assertEqual(self.pins(), {})
        self.assertEqual(self.world()["units"][SHADOW_ENDPOINT]["active"], "inactive")
        self.assertEqual(off["recap"]["failed"], 0)
        # Nothing pins 1.0.0 and 2.0.0 any more; with keep 2 both stay (newest two).
        self.assertEqual(self.versions(), ["1.0.0", "2.0.0"])

    def test_rust_with_shadow_pins_both(self):
        self.ok("rust", "1.0.0", shadow=True)
        self.assert_rust("1.0.0")
        self.assertEqual(
            self.pins(), {"software-live": "1.0.0", "software-live-shadow": "1.0.0"}
        )

    # -- check mode ------------------------------------------------------------

    def test_check_mode_changes_nothing(self):
        self.ok("python")

        def tree() -> list[str]:
            # Everything the role could touch (not the fake world or the plays).
            return sorted(
                str(p)
                for p in self.work.rglob("*")
                if "state" not in p.parts
                and not re.match(r"(play|facts)-\d+\.", p.name)
            )

        before = tree()
        result = self.play("rust", "1.0.0", check=True)
        self.assertEqual(result["rc"], 0, result["out"])
        self.assertEqual(tree(), before)
        self.assert_python()


if __name__ == "__main__":
    unittest.main()
