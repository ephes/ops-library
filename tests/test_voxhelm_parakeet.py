"""Parakeet for Voxhelm: worker install/model tasks, env rendering and routing switch.

The worker role installs the parakeet-mlx CLI and a pinned model only when
`voxhelm_remote_worker_parakeet_enabled` is set; the control plane routes
known-speaker jobs to it only when `voxhelm_known_speaker_stt_backend` is
`parakeet`. Both are off by default.
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_voxhelm_prune_and_service_knobs import (
    VOXHELM,
    VOXHELM_WORKER,
    _defaults,
    _env_lines,
    _render,
    _task,
    _tasks,
)

PARAKEET_KEYS = (
    "VOXHELM_PARAKEET_BIN",
    "VOXHELM_PARAKEET_MODEL_DIR",
    "VOXHELM_PARAKEET_MODEL_NAME",
    "VOXHELM_PARAKEET_CHUNK_SECONDS",
    "VOXHELM_PARAKEET_OVERLAP_SECONDS",
    "VOXHELM_PARAKEET_MAX_SENTENCE_SECONDS",
    "VOXHELM_PARAKEET_TIMEOUT_SECONDS",
)
VALID_PARAKEET_VARS = {
    "voxhelm_remote_worker_parakeet_package_version": "0.5.3",
    "voxhelm_remote_worker_parakeet_python_version": "3.13",
    "voxhelm_remote_worker_parakeet_bin": "/Users/jochen/.local/bin/parakeet-mlx",
    "voxhelm_remote_worker_parakeet_model_repo": "mlx-community/parakeet-tdt-0.6b-v3",
    "voxhelm_remote_worker_parakeet_model_revision": "ed2b7e8c15f9aaa0b5772e2efb986255eaef7e15",
    "voxhelm_remote_worker_parakeet_model_sha256": (
        "05e01c7f396c298cf7d23f61da7b504adeab698f0aaeafd9c82d198625464592"
    ),
    "voxhelm_remote_worker_parakeet_model_dir": "/Users/jochen/models/parakeet/ed2b7e8c",
    "voxhelm_remote_worker_parakeet_model_name": "parakeet-tdt-0.6b-v3",
    "voxhelm_remote_worker_parakeet_chunk_seconds": 600,
    "voxhelm_remote_worker_parakeet_overlap_seconds": 30,
    "voxhelm_remote_worker_parakeet_max_sentence_seconds": "",
    "voxhelm_remote_worker_parakeet_timeout_seconds": 1800,
}


def run_tasks(tasks: list, extra_vars: dict) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as directory:
        playbook = Path(directory) / "playbook.json"
        playbook.write_text(
            json.dumps([{"hosts": "localhost", "gather_facts": False, "tasks": tasks}])
        )
        return subprocess.run(
            [
                "ansible-playbook",
                "-i",
                "localhost,",
                "-c",
                "local",
                str(playbook),
                "-e",
                json.dumps(extra_vars),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )


def without_become(task: dict) -> dict:
    return {key: value for key, value in task.items() if not key.startswith("become")}


class WorkerParakeetEnvTests(unittest.TestCase):
    def setUp(self):
        self.defaults = _defaults(VOXHELM_WORKER)

    def test_parakeet_is_off_and_not_rendered_by_default(self):
        self.assertIs(self.defaults["voxhelm_remote_worker_parakeet_enabled"], False)
        values = _env_lines(_render(VOXHELM_WORKER / "templates/worker.env.j2", self.defaults))
        for key in PARAKEET_KEYS:
            self.assertNotIn(key, values)

    def test_parakeet_settings_are_rendered_when_enabled(self):
        context = {
            **self.defaults,
            **VALID_PARAKEET_VARS,
            "voxhelm_remote_worker_parakeet_enabled": True,
        }
        values = _env_lines(_render(VOXHELM_WORKER / "templates/worker.env.j2", context))
        self.assertEqual(values["VOXHELM_PARAKEET_BIN"], "/Users/jochen/.local/bin/parakeet-mlx")
        self.assertEqual(
            values["VOXHELM_PARAKEET_MODEL_DIR"], "/Users/jochen/models/parakeet/ed2b7e8c"
        )
        self.assertEqual(values["VOXHELM_PARAKEET_MODEL_NAME"], "parakeet-tdt-0.6b-v3")
        self.assertEqual(values["VOXHELM_PARAKEET_CHUNK_SECONDS"], "600")
        self.assertEqual(values["VOXHELM_PARAKEET_OVERLAP_SECONDS"], "30")
        self.assertEqual(values["VOXHELM_PARAKEET_TIMEOUT_SECONDS"], "1800")
        self.assertNotIn("VOXHELM_PARAKEET_MAX_SENTENCE_SECONDS", values)

        context["voxhelm_remote_worker_parakeet_max_sentence_seconds"] = "12.5"
        values = _env_lines(_render(VOXHELM_WORKER / "templates/worker.env.j2", context))
        self.assertEqual(values["VOXHELM_PARAKEET_MAX_SENTENCE_SECONDS"], "12.5")

    def test_default_model_directory_is_named_after_the_pinned_commit(self):
        self.assertTrue(
            self.defaults["voxhelm_remote_worker_parakeet_model_dir"].endswith(
                "/{{ voxhelm_remote_worker_parakeet_model_revision }}"
            )
        )


class WorkerParakeetTaskTests(unittest.TestCase):
    TASKS = VOXHELM_WORKER / "tasks/parakeet.yml"

    def test_main_includes_parakeet_tasks_only_when_enabled(self):
        task = _task(
            _tasks(VOXHELM_WORKER / "tasks/main.yml"),
            "runtime | Install the Parakeet CLI and pinned model",
        )
        self.assertEqual(task["ansible.builtin.include_tasks"], "parakeet.yml")
        self.assertIn("voxhelm_remote_worker_parakeet_enabled | bool", task["when"])

    def test_worker_restarts_after_a_parakeet_install(self):
        task = _task(
            _tasks(VOXHELM_WORKER / "tasks/main.yml"),
            "launchd | Start or restart remote worker unit",
        )
        self.assertIn("voxhelm_remote_worker_parakeet_install.changed", str(task["when"]))

    def test_validation_accepts_defaults_and_rejects_malformed_values(self):
        task = _task(_tasks(self.TASKS), "parakeet | Validate Parakeet settings")
        cases = [
            ({}, True),
            ({"voxhelm_remote_worker_parakeet_max_sentence_seconds": "20"}, True),
            ({"voxhelm_remote_worker_parakeet_model_revision": "main"}, False),
            ({"voxhelm_remote_worker_parakeet_model_sha256": "abc"}, False),
            ({"voxhelm_remote_worker_parakeet_model_dir": "models/parakeet"}, False),
            ({"voxhelm_remote_worker_parakeet_bin": "parakeet-mlx"}, False),
            ({"voxhelm_remote_worker_parakeet_overlap_seconds": 600}, False),
            ({"voxhelm_remote_worker_parakeet_overlap_seconds": -1}, False),
            ({"voxhelm_remote_worker_parakeet_timeout_seconds": 0}, False),
            ({"voxhelm_remote_worker_parakeet_max_sentence_seconds": "-3"}, False),
            ({"voxhelm_remote_worker_parakeet_package_version": ""}, False),
        ]
        for overrides, valid in cases:
            with self.subTest(overrides=overrides):
                result = run_tasks([task], {**VALID_PARAKEET_VARS, **overrides})
                self.assertEqual(
                    result.returncode, 0 if valid else 2, result.stdout + result.stderr
                )

    def test_cli_is_installed_only_when_the_pinned_version_is_missing(self):
        task = without_become(
            _task(_tasks(self.TASKS), "parakeet | Install the parakeet-mlx CLI as a uv tool")
        )
        argv = task["ansible.builtin.command"]["argv"]
        self.assertIn("parakeet-mlx=={{ voxhelm_remote_worker_parakeet_package_version }}", argv)
        self.assertIn("--python", argv)
        with tempfile.TemporaryDirectory() as directory:
            record = Path(directory) / "calls"
            fake_uv = Path(directory) / "uv"
            fake_uv.write_text(f'#!/bin/sh\necho "$@" >> {record}\n')
            fake_uv.chmod(0o755)
            cases = [
                ("parakeet-mlx v0.5.3 [required:  ==0.5.3]\n- parakeet-mlx\n", False),
                ("voxhelm v0.1.8\nparakeet-mlx v0.5.3\n", False),
                ("voxhelm v0.1.8\n", True),
                ("parakeet-mlx v0.5.2\n", True),
                ("parakeet-mlx v0.5.31\n", True),
            ]
            for listing, installs in cases:
                with self.subTest(listing=listing):
                    record.unlink(missing_ok=True)
                    result = run_tasks(
                        [task],
                        {
                            **VALID_PARAKEET_VARS,
                            "voxhelm_remote_worker_uv_bin": str(fake_uv),
                            "voxhelm_remote_worker_launchd_path": os.environ["PATH"],
                            "voxhelm_remote_worker_public_index_url": "https://pypi.org/simple",
                            "voxhelm_remote_worker_tool_list": {"stdout": listing},
                        },
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(record.exists(), installs)
                    if installs:
                        self.assertIn(
                            "tool install --python 3.13 --default-index "
                            "https://pypi.org/simple parakeet-mlx==0.5.3",
                            record.read_text(),
                        )

    def test_model_is_downloaded_again_when_files_or_marker_do_not_match(self):
        names = (
            "parakeet | Describe the pinned model",
            "parakeet | Check the pinned model directory",
            "parakeet | Read the recorded model commit",
            "parakeet | Decide whether the pinned model must be downloaded",
        )
        tasks = [_task(_tasks(self.TASKS), name) for name in names]
        marker = (
            "repo=mlx-community/parakeet-tdt-0.6b-v3\n"
            "revision=ed2b7e8c15f9aaa0b5772e2efb986255eaef7e15\n"
            "model.safetensors sha256="
            "05e01c7f396c298cf7d23f61da7b504adeab698f0aaeafd9c82d198625464592\n"
        )
        cases = [
            ({"config.json", "model.safetensors"}, marker, False),
            ({"config.json", "model.safetensors"}, marker.replace("ed2b7e8c", "0000000c"), True),
            ({"config.json", "model.safetensors"}, None, True),
            ({"config.json"}, marker, True),
        ]
        for files, recorded, needed in cases:
            with self.subTest(files=sorted(files), recorded=recorded, needed=needed):
                with tempfile.TemporaryDirectory() as directory:
                    for name in files:
                        (Path(directory) / name).write_text("x")
                    if recorded is not None:
                        (Path(directory) / "VOXHELM_MODEL_REVISION").write_text(recorded)
                    check = {
                        "name": "check",
                        "ansible.builtin.assert": {
                            "that": [
                                "voxhelm_remote_worker_parakeet_download_needed | bool"
                                + ("" if needed else " == false")
                            ]
                        },
                    }
                    result = run_tasks(
                        [*tasks, check],
                        {
                            **VALID_PARAKEET_VARS,
                            "voxhelm_remote_worker_parakeet_model_dir": directory,
                        },
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_model_is_downloaded_at_the_pinned_commit_and_verified_before_use(self):
        block = _task(_tasks(self.TASKS), "parakeet | Download and verify the pinned model")
        names = [task["name"] for task in block["block"]]
        self.assertLess(
            names.index("parakeet | Verify the weights' sha256"),
            names.index("parakeet | Move the verified model into place"),
        )
        download = _task(
            block["block"],
            "parakeet | Download config.json and model.safetensors at the pinned commit",
        )
        argv = download["ansible.builtin.command"]["argv"]
        self.assertEqual(
            argv[argv.index("--revision") + 1],
            "{{ voxhelm_remote_worker_parakeet_model_revision }}",
        )
        self.assertEqual(
            argv[argv.index("--local-dir") + 1],
            "{{ voxhelm_remote_worker_parakeet_partial_dir }}",
        )
        self.assertEqual(block["become_user"], "{{ voxhelm_remote_worker_service_user }}")

    def test_tasks_run_as_the_service_user_use_a_login_shell(self):
        def walk(tasks, user=None, flags=None):
            for task in tasks:
                task_user = task.get("become_user", user)
                task_flags = task.get("become_flags", flags)
                if "block" in task:
                    yield from walk(task["block"], task_user, task_flags)
                else:
                    yield task, task_user, task_flags

        checked = 0
        for task, user, flags in walk(_tasks(self.TASKS)):
            if user:
                checked += 1
                with self.subTest(task=task["name"]):
                    self.assertEqual(flags, "-i")
        # The install, the CLI check and the nine tasks of the download block.
        self.assertEqual(checked, 11)


class ControlPlaneRoutingSwitchTests(unittest.TestCase):
    def setUp(self):
        self.defaults = _defaults(VOXHELM)

    def test_switch_is_off_by_default_and_rendered(self):
        self.assertEqual(self.defaults["voxhelm_known_speaker_stt_backend"], "")
        values = _env_lines(_render(VOXHELM / "templates/voxhelm.env.j2", self.defaults))
        self.assertEqual(values["VOXHELM_KNOWN_SPEAKER_STT_BACKEND"], "")
        values = _env_lines(
            _render(
                VOXHELM / "templates/voxhelm.env.j2",
                {**self.defaults, "voxhelm_known_speaker_stt_backend": "parakeet"},
            )
        )
        self.assertEqual(values["VOXHELM_KNOWN_SPEAKER_STT_BACKEND"], "parakeet")

    def test_validation_accepts_only_empty_or_parakeet(self):
        task = _task(
            _tasks(VOXHELM / "tasks/validate.yml"), "validate | Validate known-speaker STT routing"
        )
        for value, valid in (("", True), ("parakeet", True), ("whispercpp", False)):
            with self.subTest(value=value):
                result = run_tasks([task], {"voxhelm_known_speaker_stt_backend": value})
                self.assertEqual(
                    result.returncode, 0 if valid else 2, result.stdout + result.stderr
                )


if __name__ == "__main__":
    unittest.main()
