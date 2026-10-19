"""Server ad analysis (podcast slice 16): Delve settings, llama-server, worker runtime.

- `delve_deploy` renders the analysis settings only when
  `delve_smart_skip_analysis` is on, keeps the env file and unit unchanged
  otherwise, and validates URLs and secrets without printing them.
- `llama_server_deploy` starts the pinned wrapper under launchd with the
  settings it reads, refuses a wrapper that pins another model, and reads the
  llama.cpp build the way /props reports it.
- `voxhelm_remote_worker_deploy` renders the `ad-analysis-v1` runtime settings
  only when switched on and requires Parakeet for it.
"""

import json
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_voxhelm_prune_and_service_knobs import (
    ROLES,
    VOXHELM_WORKER,
    _defaults,
    _env_lines,
    _render,
    _task,
    _tasks,
)

DELVE = ROLES / "delve_deploy"
LLAMA = ROLES / "llama_server_deploy"

SHA = "3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597"  # pragma: allowlist secret
TOKEN = "t" * 40
KEY = "k" * 40
PLACEHOLDER = "CHANGEME"  # pragma: allowlist secret

ANALYSIS_KEYS = (
    "DELVE_SMART_SKIP_ANALYSIS",
    "DELVE_SMART_SKIP_ANALYSIS_PROFILE",
    "DELVE_ANALYSIS_MEDIA_DIR",
    "DELVE_ANALYSIS_MEDIA_DISK_CAP_BYTES",
    "DELVE_FFPROBE_PATH",
    "DELVE_FFMPEG_PATH",
    "DELVE_VOXHELM_URL",
    "DELVE_VOXHELM_TOKEN_FILE",
    "DELVE_VOXHELM_TIMEOUT_SECONDS",
    "DELVE_VOXHELM_UPLOAD_TIMEOUT_SECONDS",
    "DELVE_VOXHELM_POLL_SECONDS",
    "DELVE_DETECTOR_URL",
    "DELVE_DETECTOR_API_KEY_FILE",
    "DELVE_DETECTOR_TIMEOUT_SECONDS",
)
WORKER_KEYS = (
    "VOXHELM_WINDOW_MODEL",
    "VOXHELM_WINDOW_TIMEOUT_SECONDS",
    "VOXHELM_FFPROBE_BIN",
)


def _resolve(defaults: dict, overrides: dict) -> dict:
    """Defaults with the `{{ var }}` references the templates rely on resolved."""
    context = {**defaults, **overrides}
    for _ in range(4):
        for key, value in list(context.items()):
            if isinstance(value, str) and "{{" in value:
                context[key] = _render_string(value, context)
    return context


def _render_string(text: str, context: dict) -> str:
    from tests.test_voxhelm_prune_and_service_knobs import _env

    return _env().from_string(text).render(context)


def _run_playbook(play: dict, extra_vars: dict) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as directory:
        playbook = Path(directory) / "playbook.json"
        playbook.write_text(json.dumps([play]))
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
            timeout=180,
        )


class DelveAnalysisRenderTests(unittest.TestCase):
    def setUp(self):
        secret = "0123456789abcdef0123456789abcdef"  # pragma: allowlist secret
        self.base = {"delve_session_secret": secret}
        self.on = {
            **self.base,
            "delve_smart_skip_analysis": True,
            "delve_smart_skip_analysis_profile_src": "/tmp/profile.json",
            "delve_analysis_media_dir": "/var/lib/delve-smart-skip-media",
            "delve_analysis_media_disk_cap_bytes": 20000000000,
            "delve_ffprobe_path": "/usr/bin/ffprobe",
            "delve_ffmpeg_path": "/usr/bin/ffmpeg",
            "delve_voxhelm_url": "http://studio.example.ts.net:8787",
            "delve_voxhelm_token": TOKEN,
            "delve_detector_url": "http://studio.example.ts.net:8177",
            "delve_detector_api_key": KEY,
        }

    def _env(self, overrides: dict) -> dict:
        context = _resolve(_defaults(DELVE), overrides)
        return _env_lines(_render(DELVE / "templates/delve.env.j2", context))

    def _unit(self, overrides: dict) -> str:
        context = _resolve(_defaults(DELVE), overrides)
        return _render(DELVE / "templates/delve.service.j2", context)

    def test_analysis_is_off_by_default_and_renders_nothing(self):
        self.assertIs(_defaults(DELVE)["delve_smart_skip_analysis"], False)
        env = self._env(self.base)
        for key in ANALYSIS_KEYS:
            self.assertNotIn(key, env)
        # Settings without the switch stay out of the env file too.
        env = self._env({**self.on, "delve_smart_skip_analysis": False})
        for key in ANALYSIS_KEYS:
            self.assertNotIn(key, env)

    def test_unit_is_unchanged_while_analysis_is_off(self):
        self.assertEqual(
            self._unit(self.base),
            self._unit({**self.on, "delve_smart_skip_analysis": False}),
        )
        read_write = [
            line
            for line in self._unit(self.base).splitlines()
            if line.startswith("ReadWritePaths=")
        ]
        self.assertEqual(read_write, ["ReadWritePaths=/var/lib/delve"])

    def test_analysis_settings_are_rendered_with_files_for_the_secrets(self):
        env = self._env(self.on)
        self.assertEqual(env["DELVE_SMART_SKIP_ANALYSIS"], "true")
        self.assertEqual(
            env["DELVE_SMART_SKIP_ANALYSIS_PROFILE"],
            "/etc/delve/smart-skip-analysis-profile.json",
        )
        self.assertEqual(
            env["DELVE_ANALYSIS_MEDIA_DIR"], "/var/lib/delve-smart-skip-media"
        )
        self.assertEqual(env["DELVE_ANALYSIS_MEDIA_DISK_CAP_BYTES"], "20000000000")
        self.assertEqual(env["DELVE_FFPROBE_PATH"], "/usr/bin/ffprobe")
        self.assertEqual(env["DELVE_FFMPEG_PATH"], "/usr/bin/ffmpeg")
        self.assertEqual(env["DELVE_VOXHELM_URL"], "http://studio.example.ts.net:8787")
        self.assertEqual(env["DELVE_VOXHELM_TOKEN_FILE"], "/etc/delve/voxhelm-token")
        self.assertEqual(env["DELVE_DETECTOR_URL"], "http://studio.example.ts.net:8177")
        self.assertEqual(
            env["DELVE_DETECTOR_API_KEY_FILE"], "/etc/delve/detector-api-key"
        )
        rendered = _render(
            DELVE / "templates/delve.env.j2", _resolve(_defaults(DELVE), self.on)
        )
        self.assertNotIn(TOKEN, rendered)
        self.assertNotIn(KEY, rendered)
        for key in (
            "DELVE_VOXHELM_TIMEOUT_SECONDS",
            "DELVE_VOXHELM_UPLOAD_TIMEOUT_SECONDS",
            "DELVE_VOXHELM_POLL_SECONDS",
            "DELVE_DETECTOR_TIMEOUT_SECONDS",
        ):
            self.assertNotIn(key, env)

    def test_optional_values_fall_back_to_delves_defaults(self):
        env = self._env(
            {
                **self.on,
                "delve_analysis_media_dir": "",
                "delve_analysis_media_disk_cap_bytes": "",
                "delve_ffprobe_path": "",
                "delve_ffmpeg_path": "",
                "delve_voxhelm_url": "",
                "delve_detector_url": "",
                "delve_voxhelm_poll_seconds": 15,
            }
        )
        self.assertEqual(env["DELVE_SMART_SKIP_ANALYSIS"], "true")
        for key in (
            "DELVE_ANALYSIS_MEDIA_DIR",
            "DELVE_ANALYSIS_MEDIA_DISK_CAP_BYTES",
            "DELVE_FFPROBE_PATH",
            "DELVE_FFMPEG_PATH",
            "DELVE_VOXHELM_URL",
            "DELVE_VOXHELM_TOKEN_FILE",
            "DELVE_DETECTOR_URL",
            "DELVE_DETECTOR_API_KEY_FILE",
        ):
            self.assertNotIn(key, env)
        self.assertEqual(env["DELVE_VOXHELM_POLL_SECONDS"], "15")

    def test_media_dir_outside_the_data_dir_is_writable_for_the_unit(self):
        lines = [
            line
            for line in self._unit(self.on).splitlines()
            if line.startswith("ReadWritePaths=")
        ]
        self.assertEqual(
            lines,
            [
                "ReadWritePaths=/var/lib/delve",
                "ReadWritePaths=/var/lib/delve-smart-skip-media",
            ],
        )
        inside = {
            **self.on,
            "delve_analysis_media_dir": "/var/lib/delve/smart-skip-media",
        }
        lines = [
            line
            for line in self._unit(inside).splitlines()
            if line.startswith("ReadWritePaths=")
        ]
        self.assertEqual(lines, ["ReadWritePaths=/var/lib/delve"])

    def test_ffmpeg_is_installed_only_with_the_analysis(self):
        packages = _task(
            _tasks(DELVE / "tasks/packages.yml"),
            "packages | Ensure delve runtime packages are present",
        )
        self.assertIn(
            "delve_smart_skip_packages if delve_smart_skip_analysis",
            packages["ansible.builtin.apt"]["name"],
        )
        self.assertEqual(_defaults(DELVE)["delve_smart_skip_packages"], ["ffmpeg"])

    def test_secret_files_are_no_log_and_group_readable_only(self):
        tasks = _tasks(DELVE / "tasks/config.yml")
        for name in (
            "config | Write the voxhelm producer token file",
            "config | Write the detector API key file",
        ):
            task = _task(tasks, name)
            self.assertIs(task["no_log"], True)
            self.assertEqual(task["ansible.builtin.copy"]["mode"], "0640")
            self.assertEqual(task["ansible.builtin.copy"]["owner"], "root")


class DelveAnalysisValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        directory = Path(self.tmp.name)
        (directory / "delved").write_text("placeholder\n")
        (directory / "profile.json").write_text('{"taxonomy": "server-taxonomy-v1"}\n')
        (directory / "not-json.json").write_text("nope\n")
        self.directory = directory
        self.valid = {
            "delve_binary_src": str(directory / "delved"),
            "delve_session_secret": "0123456789abcdef0123456789abcdef",  # pragma: allowlist secret
            "delve_smart_skip_analysis": True,
            "delve_smart_skip_analysis_profile_src": str(directory / "profile.json"),
            "delve_analysis_media_dir": "/var/lib/delve-smart-skip-media",
            "delve_analysis_media_disk_cap_bytes": 20000000000,
            "delve_voxhelm_url": "http://studio.example.ts.net:8787",
            "delve_voxhelm_token": TOKEN,
            "delve_detector_url": "http://studio.example.ts.net:8177",
            "delve_detector_api_key": KEY,
        }

    def _validate(self, overrides: dict) -> subprocess.CompletedProcess:
        play = {
            "hosts": "localhost",
            "gather_facts": False,
            "vars_files": [str(DELVE / "defaults/main.yml")],
            "tasks": [
                {"ansible.builtin.include_tasks": str(DELVE / "tasks/validate.yml")}
            ],
        }
        return _run_playbook(play, {**self.valid, **overrides})

    def test_valid_settings_pass(self):
        result = self._validate({})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_bad_settings_fail(self):
        cases = {
            "url with a path": {
                "delve_voxhelm_url": "http://studio.example.ts.net:8787/v1"
            },
            "url with credentials": {
                "delve_detector_url": "http://user:pw@studio:8177"  # pragma: allowlist secret
            },
            "no profile": {"delve_smart_skip_analysis_profile_src": ""},
            "profile not JSON": {
                "delve_smart_skip_analysis_profile_src": str(
                    self.directory / "not-json.json"
                )
            },
            "relative media dir": {"delve_analysis_media_dir": "smart-skip-media"},
            "media dir with a space": {
                "delve_analysis_media_dir": "/var/lib/delve media"
            },
            "token path with a dollar": {
                "delve_voxhelm_token_path": "/etc/delve/$token"
            },
            "relative ffprobe": {"delve_ffprobe_path": "ffprobe"},
            "media dir is the data dir": {
                "delve_analysis_media_dir": "/var/lib/delve/"
            },
            "zero disk cap": {"delve_analysis_media_disk_cap_bytes": 0},
            "bad timeout": {"delve_detector_timeout_seconds": "soon"},
            "typo switch": {"delve_smart_skip_analysis": "ture"},
        }
        for label, overrides in cases.items():
            with self.subTest(label):
                result = self._validate(overrides)
                self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_placeholder_or_short_secrets_fail_without_printing_them(self):
        for overrides in (
            {"delve_voxhelm_token": "CHANGEME"},
            {"delve_detector_api_key": "short-key"},  # pragma: allowlist secret
        ):
            with self.subTest(overrides=list(overrides)):
                result = self._validate(overrides)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("The values are not printed", result.stdout)
                self.assertNotIn(TOKEN, result.stdout)
                self.assertNotIn(KEY, result.stdout)

    def test_secrets_are_not_needed_without_their_url(self):
        result = self._validate(
            {
                "delve_voxhelm_url": "",
                "delve_voxhelm_token": "",
                "delve_detector_url": "",
                "delve_detector_api_key": "",
            }
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class LlamaServerRoleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.wrapper = Path(self.tmp.name) / "detector-server.sh"
        self.wrapper.write_text(
            f'readonly GGUF_SHA256="{SHA}"\n'
            'exec "$llama" --api-key-file "$key_file" --no-ui --no-slots --cache-ram 0\n'
        )
        self.valid = {
            "llama_server_service_user": "jochen",
            "llama_server_wrapper_src": str(self.wrapper),
            "llama_server_api_key": KEY,
            "llama_server_bind_host": "127.0.0.1",
        }

    def _validate(self, overrides: dict) -> subprocess.CompletedProcess:
        play = {
            "hosts": "localhost",
            "gather_facts": False,
            "vars_files": [str(LLAMA / "defaults/main.yml")],
            "tasks": [
                # The role runs after fact gathering on a macOS host.
                {
                    "ansible.builtin.set_fact": {
                        "ansible_facts": {
                            "os_family": "Darwin",
                            "all_ipv4_addresses": ["192.168.1.5", "100.101.102.103"],
                        }
                    }
                },
                {"ansible.builtin.include_tasks": str(LLAMA / "tasks/validate.yml")},
                {
                    "ansible.builtin.debug": {
                        "msg": "BIND={{ llama_server_bind_address }}"
                    }
                },
            ],
        }
        return _run_playbook(play, {**self.valid, **overrides})

    def test_defaults_pin_the_research_detector(self):
        defaults = _defaults(LLAMA)
        self.assertEqual(defaults["llama_server_gguf_sha256"], SHA)
        self.assertEqual(
            defaults["llama_server_alias"], "qwen3-4b-instruct-2507-q4km-3605803b"
        )
        self.assertEqual(defaults["llama_server_build"], "b11669-620d2225c")
        self.assertIn(
            "/resolve/a06e946bb6b655725eafa393f4a9745d460374c9/",
            defaults["llama_server_gguf_url"],
        )
        self.assertEqual(defaults["llama_server_bind_host"], "tailnet")
        self.assertEqual(defaults["llama_server_api_key"], "CHANGEME")

    def test_plist_starts_the_wrapper_with_its_settings(self):
        context = _resolve(
            _defaults(LLAMA),
            {**self.valid, "llama_server_bind_address": "100.101.102.103"},
        )
        plist = plistlib.loads(
            _render(LLAMA / "templates/llama-server.launchd.plist.j2", context).encode()
        )
        self.assertEqual(plist["Label"], "de.wersdoerfer.llama-server")
        self.assertEqual(
            plist["ProgramArguments"],
            ["/bin/bash", "/opt/llama-server/detector-server.sh"],
        )
        self.assertEqual(plist["UserName"], "jochen")
        self.assertIs(plist["KeepAlive"], True)
        env = plist["EnvironmentVariables"]
        self.assertEqual(
            env["DELVE_DETECTOR_GGUF"],
            "/opt/llama-server/models/Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
        )
        self.assertEqual(env["DELVE_DETECTOR_HOST"], "100.101.102.103")
        self.assertEqual(env["DELVE_DETECTOR_PORT"], "8177")
        self.assertEqual(
            env["DELVE_DETECTOR_API_KEY_FILE"], "/etc/llama-server/api-key"
        )
        self.assertEqual(env["DELVE_DETECTOR_BUILD"], "b11669-620d2225c")
        self.assertEqual(env["DELVE_LLAMA_SERVER"], "/opt/homebrew/bin/llama-server")
        rendered = json.dumps(plist)
        self.assertNotIn(KEY, rendered)
        self.assertNotIn("--verbose", rendered)

    def test_valid_settings_pass_and_tailnet_picks_the_tailscale_address(self):
        result = self._validate({})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("BIND=127.0.0.1", result.stdout)
        result = self._validate({"llama_server_bind_host": "tailnet"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("BIND=100.101.102.103", result.stdout)

    def test_bad_settings_fail(self):
        other = Path(self.tmp.name) / "other.sh"
        other.write_text(self.wrapper.read_text().replace(SHA, "0" * 64))
        cases = {
            "wildcard bind": {"llama_server_bind_host": "0.0.0.0"},
            "lan bind": {"llama_server_bind_host": "192.168.1.5"},
            "placeholder user": {"llama_server_service_user": "CHANGEME"},
            "placeholder key": {"llama_server_api_key": PLACEHOLDER},
            "wrapper pins another model": {"llama_server_wrapper_src": str(other)},
            "missing wrapper": {
                "llama_server_wrapper_src": str(Path(self.tmp.name) / "missing.sh")
            },
            "alias of another model": {
                "llama_server_alias": "qwen3-4b-instruct-2507-q4km-deadbeef"
            },
            "bad build": {"llama_server_build": "0.7.0"},
        }
        for label, overrides in cases.items():
            with self.subTest(label):
                result = self._validate(overrides)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertNotIn(KEY, result.stdout)

    def test_installed_build_is_read_like_props_build_info(self):
        task = _task(
            _tasks(LLAMA / "tasks/install.yml"), "install | Resolve the installed build"
        )
        for output, expected in (
            (
                "version: 0.7.0 (build 11669, commit 620d2225c)\nbuilt with AppleClang",
                "b11669-620d2225c",
            ),
            ("something else", ""),
        ):
            with self.subTest(output=output):
                play = {
                    "hosts": "localhost",
                    "gather_facts": False,
                    "tasks": [
                        task,
                        {
                            "ansible.builtin.debug": {
                                "msg": "BUILD=[{{ llama_server_installed_build }}]"
                            }
                        },
                    ],
                }
                result = _run_playbook(
                    play, {"llama_server_version": {"stdout": "", "stderr": output}}
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(f"BUILD=[{expected}]", result.stdout)

    def test_health_requests_carrying_the_key_are_no_log(self):
        tasks = _tasks(LLAMA / "tasks/health.yml")
        for name in ("health | Read /v1/models", "health | Read /props"):
            self.assertIs(_task(tasks, name)["no_log"], True)
        self.assertIs(
            _task(
                _tasks(LLAMA / "tasks/install.yml"), "install | Write the API key file"
            )["no_log"],
            True,
        )


class WorkerAdAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.context = _resolve(
            _defaults(VOXHELM_WORKER),
            {
                "inventory_hostname": "atlas",
                "voxhelm_remote_worker_service_user": "jochen",
                "voxhelm_remote_worker_token": "worker-token",
                "voxhelm_remote_worker_parakeet_enabled": True,
            },
        )

    def _env(self, overrides: dict) -> dict:
        return _env_lines(
            _render(
                VOXHELM_WORKER / "templates/worker.env.j2",
                {**self.context, **overrides},
            )
        )

    def test_profile_runtime_is_off_by_default(self):
        self.assertIs(
            _defaults(VOXHELM_WORKER)["voxhelm_remote_worker_ad_analysis_enabled"],
            False,
        )
        env = self._env({})
        for key in WORKER_KEYS:
            self.assertNotIn(key, env)

    def test_profile_runtime_settings_are_rendered_when_on(self):
        env = self._env({"voxhelm_remote_worker_ad_analysis_enabled": True})
        self.assertEqual(env["VOXHELM_WINDOW_MODEL"], "ggml-large-v3-turbo.bin")
        self.assertEqual(env["VOXHELM_WINDOW_TIMEOUT_SECONDS"], "120")
        self.assertEqual(env["VOXHELM_FFPROBE_BIN"], "/opt/homebrew/bin/ffprobe")

    def test_turbo_model_pin_is_voxhelms(self):
        defaults = _defaults(VOXHELM_WORKER)
        self.assertEqual(
            defaults["voxhelm_remote_worker_window_model_sha256"],
            "1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69",  # pragma: allowlist secret
        )
        self.assertIn(
            "/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-large-v3-turbo.bin",
            defaults["voxhelm_remote_worker_window_model_url"],
        )
        download = _task(
            _tasks(VOXHELM_WORKER / "tasks/ad_analysis.yml"),
            "ad_analysis | Download and verify the pinned turbo window model",
        )
        self.assertEqual(
            download["ansible.builtin.get_url"]["checksum"],
            "sha256:{{ voxhelm_remote_worker_window_model_sha256 }}",
        )

    def test_profile_runtime_requires_parakeet(self):
        task = _task(
            _tasks(VOXHELM_WORKER / "tasks/ad_analysis.yml"),
            "ad_analysis | Validate the profile runtime settings",
        )
        play = {
            "hosts": "localhost",
            "gather_facts": False,
            "vars_files": [str(VOXHELM_WORKER / "defaults/main.yml")],
            "tasks": [task],
        }
        ok = _run_playbook(
            play,
            {
                "voxhelm_remote_worker_service_user": "jochen",
                "voxhelm_remote_worker_parakeet_enabled": True,
            },
        )
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        refused = _run_playbook(
            play,
            {
                "voxhelm_remote_worker_service_user": "jochen",
                "voxhelm_remote_worker_parakeet_enabled": False,
            },
        )
        self.assertNotEqual(refused.returncode, 0, refused.stdout)

    def test_worker_restarts_when_the_model_changes(self):
        tasks = _tasks(VOXHELM_WORKER / "tasks/main.yml")
        start = _task(tasks, "launchd | Start or restart remote worker unit")
        conditions = " ".join(str(item) for item in start["when"])
        self.assertIn("voxhelm_remote_worker_window_model_changed", conditions)


if __name__ == "__main__":
    unittest.main()
