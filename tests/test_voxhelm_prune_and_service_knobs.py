"""Render checks for the Voxhelm prune job and the optional service settings.

Covers the hourly `prune_job_artifacts` launchd job in `voxhelm_deploy` (off by
default, dry-run until switched) and the optional Voxhelm, Echoport and
mailgun-relay settings that are rendered only when the owner sets them.
"""

import json
import plistlib
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
from ansible.plugins.filter.core import FilterModule
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
ROLES = ROOT / "roles"
VOXHELM = ROLES / "voxhelm_deploy"
ECHOPORT = ROLES / "echoport_deploy"
MAILGUN = ROLES / "mailgun_relay_deploy"

VOXHELM_OPTIONAL_KEYS = (
    "VOXHELM_SOURCE_ARTIFACT_RETENTION_SECONDS",
    "VOXHELM_JOB_METADATA_RETENTION_SECONDS",
    "VOXHELM_STAGED_INPUT_RETENTION_SECONDS",
    "VOXHELM_WYOMING_STT_MAX_AUDIO_SECONDS",
    "VOXHELM_PRIVATE_URL_HOSTS",
)
ECHOPORT_OPTIONAL_KEYS = (
    "ECHOPORT_STALE_RUN_GRACE_SECONDS",
    "ECHOPORT_LATE_RESULT_WINDOW_SECONDS",
    "ECHOPORT_HEALTH_OVERDUE_GRACE_MINUTES",
)


def _env() -> Environment:
    # Ansible's template module renders with trim_blocks enabled.
    env = Environment(undefined=StrictUndefined, trim_blocks=True)
    env.filters.update(FilterModule().filters())
    return env


def _render(path: Path, context: dict) -> str:
    return _env().from_string(path.read_text()).render(context)


def _defaults(role: Path) -> dict:
    return yaml.safe_load((role / "defaults/main.yml").read_text())


def _env_lines(rendered: str) -> dict:
    values = {}
    for line in rendered.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        words = shlex.split(line)
        key, _, value = words[0].partition("=")
        values[key] = value
    return values


def _tasks(path: Path) -> list:
    return yaml.safe_load(path.read_text())


def _task(tasks: list, name: str) -> dict:
    matches = [task for task in tasks if task.get("name") == name]
    if len(matches) != 1:
        raise AssertionError(f"expected one task named {name!r}, found {len(matches)}")
    return matches[0]


class VoxhelmPruneJobTests(unittest.TestCase):
    def setUp(self):
        self.defaults = _defaults(VOXHELM)
        self.context = {
            **self.defaults,
            "voxhelm_app_dir": "/opt/apps/voxhelm/site",
            "voxhelm_config_dir": "/etc/voxhelm",
            "voxhelm_prune_script_path": "/opt/apps/voxhelm/site/prune.sh",
            "voxhelm_prune_stdout_log": "/var/log/voxhelm/voxhelm-prune.log",
            "voxhelm_prune_stderr_log": "/var/log/voxhelm/voxhelm-prune.err.log",
        }

    def test_prune_job_is_off_and_dry_run_by_default(self):
        self.assertIs(self.defaults["voxhelm_prune_enabled"], False)
        self.assertIs(self.defaults["voxhelm_prune_dry_run"], True)
        self.assertEqual(self.defaults["voxhelm_prune_interval_seconds"], 3600)

    def test_prune_script_sources_env_and_defaults_to_dry_run(self):
        script = _render(VOXHELM / "templates/prune.sh.j2", self.context)
        self.assertIn("set -euo pipefail", script)
        self.assertIn("source /etc/voxhelm/voxhelm.env", script)
        self.assertIn("cd /opt/apps/voxhelm/site", script)
        exec_lines = [line for line in script.splitlines() if line.startswith("exec ")]
        self.assertEqual(
            exec_lines,
            ["exec .venv/bin/python manage.py prune_job_artifacts --dry-run"],
        )
        subprocess.run(["bash", "-n"], input=script, text=True, check=True)

    def test_prune_script_deletes_only_when_dry_run_is_off(self):
        script = _render(
            VOXHELM / "templates/prune.sh.j2",
            {**self.context, "voxhelm_prune_dry_run": False},
        )
        self.assertNotIn("--dry-run", script)
        exec_lines = [line for line in script.splitlines() if line.startswith("exec ")]
        self.assertEqual(exec_lines, ["exec .venv/bin/python manage.py prune_job_artifacts"])

    def test_prune_plist_is_periodic_and_never_kept_alive(self):
        rendered = _render(
            VOXHELM / "templates/voxhelm-prune.launchd.plist.j2", self.context
        )
        plist = plistlib.loads(rendered.encode())
        self.assertEqual(plist["Label"], "de.wersdoerfer.voxhelm-prune")
        self.assertEqual(plist["StartInterval"], 3600)
        self.assertIs(plist["RunAtLoad"], False)
        self.assertIs(plist["KeepAlive"], False)
        self.assertEqual(
            plist["ProgramArguments"][-1], "/opt/apps/voxhelm/site/prune.sh"
        )
        self.assertEqual(
            plist["StandardOutPath"], "/var/log/voxhelm/voxhelm-prune.log"
        )

        custom = plistlib.loads(
            _render(
                VOXHELM / "templates/voxhelm-prune.launchd.plist.j2",
                {**self.context, "voxhelm_prune_interval_seconds": "7200"},
            ).encode()
        )
        self.assertEqual(custom["StartInterval"], 7200)

    def test_launchd_tasks_gate_the_prune_job_and_never_kickstart_it(self):
        config = _tasks(VOXHELM / "tasks/config.yml")
        script = _task(config, "config | Render Voxhelm prune script")
        self.assertEqual(script["when"], "voxhelm_prune_enabled | bool")

        launchd = _tasks(VOXHELM / "tasks/launchd.yml")
        render = _task(launchd, "launchd | Render Voxhelm prune plist")
        self.assertEqual(render["when"], "voxhelm_prune_enabled | bool")
        self.assertEqual(render["ansible.builtin.template"]["src"], "voxhelm-prune.launchd.plist.j2")

        manage = _task(launchd, "launchd | Manage Voxhelm prune launchd state")
        self.assertIn("voxhelm_prune_enabled | bool", manage["when"])
        self.assertIs(manage["vars"]["voxhelm_launchd_start_service"], False)
        self.assertIs(manage["vars"]["voxhelm_launchd_force_restart"], False)
        self.assertEqual(manage["vars"]["voxhelm_launchd_label"], "{{ voxhelm_prune_label }}")

        disabled = "not (voxhelm_prune_enabled | bool)"
        status = _task(
            launchd, "launchd | Check whether the disabled Voxhelm prune job is loaded"
        )
        self.assertIn(disabled, status["when"])
        bootout = _task(launchd, "launchd | Unload the disabled Voxhelm prune job")
        self.assertIn(disabled, bootout["when"])
        self.assertIn("voxhelm_prune_status.rc == 0", bootout["when"])
        self.assertIn("launchctl bootout system/", bootout["ansible.builtin.command"])
        # A refused unload must fail the play, not be ignored.
        self.assertNotIn("failed_when", bootout)
        confirm = _task(
            launchd, "launchd | Confirm the disabled Voxhelm prune job is unloaded"
        )
        self.assertEqual(confirm["failed_when"], "voxhelm_prune_status_after.rc == 0")
        remove = _task(launchd, "launchd | Remove the disabled Voxhelm prune plist and script")
        self.assertIn(disabled, remove["when"])
        self.assertIn("voxhelm_launchd_manage_state | bool", remove["when"])
        self.assertEqual(remove["ansible.builtin.file"]["state"], "absent")
        names = [task.get("name") for task in launchd]
        self.assertLess(
            names.index("launchd | Confirm the disabled Voxhelm prune job is unloaded"),
            names.index("launchd | Remove the disabled Voxhelm prune plist and script"),
        )

    def test_source_sync_keeps_the_generated_prune_script(self):
        tasks = [
            task
            for task in _tasks(VOXHELM / "tasks/source.yml")
            if task.get("name") == "source | Build rsync exclude options"
        ]
        self.assertEqual(len(tasks), 1)
        cases = [
            ({}, True),
            ({"voxhelm_app_dir": "/opt/apps/voxhelm/site/"}, True),
            ({"voxhelm_prune_script_path": "/usr/local/libexec/voxhelm-prune.sh"}, False),
        ]
        with tempfile.TemporaryDirectory() as directory:
            playbook = Path(directory) / "source.json"
            tasks.append(
                {
                    "ansible.builtin.copy": {
                        "content": "{{ voxhelm_rsync_exclude_opts | to_json }}",
                        "dest": str(Path(directory) / "opts.json"),
                    }
                }
            )
            playbook.write_text(
                json.dumps([{"hosts": "localhost", "gather_facts": False, "tasks": tasks}])
            )
            for overrides, protected in cases:
                with self.subTest(overrides=overrides):
                    app_dir = overrides.get("voxhelm_app_dir", "/opt/apps/voxhelm/site")
                    extra = {
                        "voxhelm_sync_excludes": self.defaults["voxhelm_sync_excludes"],
                        "voxhelm_app_dir": app_dir,
                        "voxhelm_prune_script_path": overrides.get(
                            "voxhelm_prune_script_path",
                            "/opt/apps/voxhelm/site/prune.sh",
                        ),
                    }
                    result = subprocess.run(
                        [
                            "ansible-playbook",
                            "-i",
                            "localhost,",
                            "-c",
                            "local",
                            str(playbook),
                            "-e",
                            json.dumps(extra),
                        ],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    opts = json.loads((Path(directory) / "opts.json").read_text())
                    self.assertIn("--exclude=var", opts)
                    anchored = [opt for opt in opts if opt.startswith("--exclude=/")]
                    self.assertEqual(anchored, ["--exclude=/prune.sh"] if protected else [])

    def test_remote_worker_role_never_schedules_pruning(self):
        for path in (ROLES / "voxhelm_remote_worker_deploy").rglob("*"):
            if path.is_file():
                self.assertNotIn("prune", path.read_text(), str(path))


class VoxhelmOptionalSettingsTests(unittest.TestCase):
    def setUp(self):
        self.defaults = _defaults(VOXHELM)

    def test_new_settings_are_not_rendered_by_default(self):
        values = _env_lines(_render(VOXHELM / "templates/voxhelm.env.j2", self.defaults))
        for key in VOXHELM_OPTIONAL_KEYS:
            self.assertNotIn(key, values)

    def test_new_settings_are_rendered_when_set(self):
        values = _env_lines(
            _render(
                VOXHELM / "templates/voxhelm.env.j2",
                {
                    **self.defaults,
                    "voxhelm_source_artifact_retention_seconds": 172800,
                    "voxhelm_job_metadata_retention_seconds": "0",
                    "voxhelm_staged_input_retention_seconds": 3600,
                    "voxhelm_wyoming_stt_max_audio_seconds": 60,
                    "voxhelm_private_url_hosts": ["nas.local", "minio.tailnet.ts.net"],
                },
            )
        )
        self.assertEqual(values["VOXHELM_SOURCE_ARTIFACT_RETENTION_SECONDS"], "172800")
        self.assertEqual(values["VOXHELM_JOB_METADATA_RETENTION_SECONDS"], "0")
        self.assertEqual(values["VOXHELM_STAGED_INPUT_RETENTION_SECONDS"], "3600")
        self.assertEqual(values["VOXHELM_WYOMING_STT_MAX_AUDIO_SECONDS"], "60")
        self.assertEqual(
            values["VOXHELM_PRIVATE_URL_HOSTS"], "nas.local,minio.tailnet.ts.net"
        )

    def test_validation_rejects_malformed_values(self):
        tasks = [
            task
            for task in _tasks(VOXHELM / "tasks/validate.yml")
            if task.get("name")
            in (
                "validate | Validate optional Voxhelm retention and Wyoming limits",
                "validate | Validate the prune schedule and private URL hosts",
            )
        ]
        self.assertEqual(len(tasks), 2)
        base = {
            key: self.defaults[key]
            for key in (
                "voxhelm_source_artifact_retention_seconds",
                "voxhelm_job_metadata_retention_seconds",
                "voxhelm_staged_input_retention_seconds",
                "voxhelm_wyoming_stt_max_audio_seconds",
                "voxhelm_prune_interval_seconds",
                "voxhelm_private_url_hosts",
            )
        }
        cases = [
            ({}, True),
            ({"voxhelm_job_metadata_retention_seconds": 0}, True),
            ({"voxhelm_source_artifact_retention_seconds": "86400"}, True),
            ({"voxhelm_private_url_hosts": ["nas.local"]}, True),
            ({"voxhelm_wyoming_stt_max_audio_seconds": "-1"}, False),
            ({"voxhelm_job_metadata_retention_seconds": "90d"}, False),
            ({"voxhelm_prune_interval_seconds": 10}, False),
            ({"voxhelm_private_url_hosts": "nas.local"}, False),
            ({"voxhelm_private_url_hosts": {"nas.local": False}}, False),
            ({"voxhelm_private_url_hosts": [1]}, False),
            ({"voxhelm_private_url_hosts": ["nas.local,evil.example"]}, False),
            ({"voxhelm_private_url_hosts": ["nas local"]}, False),
            ({"voxhelm_private_url_hosts": ["nas.local\n"]}, False),
            ({"voxhelm_wyoming_stt_max_audio_seconds": "60\n"}, False),
        ]
        with tempfile.TemporaryDirectory() as directory:
            playbook = Path(directory) / "validate.json"
            playbook.write_text(
                json.dumps([{"hosts": "localhost", "gather_facts": False, "tasks": tasks}])
            )
            for overrides, valid in cases:
                with self.subTest(overrides=overrides):
                    result = subprocess.run(
                        [
                            "ansible-playbook",
                            "-i",
                            "localhost,",
                            "-c",
                            "local",
                            str(playbook),
                            "-e",
                            json.dumps({**base, **overrides}),
                        ],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    self.assertEqual(
                        result.returncode, 0 if valid else 2, result.stdout + result.stderr
                    )


class EchoportOptionalSettingsTests(unittest.TestCase):
    def setUp(self):
        self.context = {
            **_defaults(ECHOPORT),
            "echoport_django_secret_key": "test-secret",
            "echoport_fastdeploy_service_token": "test-token",
        }

    def test_timing_settings_are_not_rendered_by_default(self):
        values = _env_lines(_render(ECHOPORT / "templates/echoport.env.j2", self.context))
        for key in ECHOPORT_OPTIONAL_KEYS:
            self.assertNotIn(key, values)

    def test_timing_settings_are_rendered_when_set(self):
        values = _env_lines(
            _render(
                ECHOPORT / "templates/echoport.env.j2",
                {
                    **self.context,
                    "echoport_stale_run_grace_seconds": 1800,
                    "echoport_late_result_window_seconds": "43200",
                    "echoport_health_overdue_grace_minutes": 90,
                },
            )
        )
        self.assertEqual(values["ECHOPORT_STALE_RUN_GRACE_SECONDS"], "1800")
        self.assertEqual(values["ECHOPORT_LATE_RESULT_WINDOW_SECONDS"], "43200")
        self.assertEqual(values["ECHOPORT_HEALTH_OVERDUE_GRACE_MINUTES"], "90")


class MailgunRelayOptionalSettingsTests(unittest.TestCase):
    def setUp(self):
        self.context = {
            **_defaults(MAILGUN),
            "mailgun_relay_envelope_sender": "relay@example.com",
        }

    def test_concurrency_cap_is_not_rendered_by_default(self):
        values = _env_lines(
            _render(MAILGUN / "templates/mailgun-relay.env.j2", self.context)
        )
        self.assertNotIn("MAILGUN_RELAY_SMTP_MAX_CONCURRENCY", values)
        self.assertEqual(values["MAILGUN_RELAY_SMTP_TIMEOUT_S"], "30")

    def test_concurrency_cap_is_rendered_when_set(self):
        values = _env_lines(
            _render(
                MAILGUN / "templates/mailgun-relay.env.j2",
                {**self.context, "mailgun_relay_smtp_max_concurrency": 4},
            )
        )
        self.assertEqual(values["MAILGUN_RELAY_SMTP_MAX_CONCURRENCY"], "4")


if __name__ == "__main__":
    unittest.main()
