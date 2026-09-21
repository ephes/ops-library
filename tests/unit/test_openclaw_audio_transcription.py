import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROLE_ROOT = Path(__file__).resolve().parents[2] / "roles" / "openclaw_deploy"


def _yaml(relative_path: str):
    return yaml.safe_load((ROLE_ROOT / relative_path).read_text(encoding="utf-8"))


def _task(tasks: list[dict], name: str) -> dict:
    for task in tasks:
        if task.get("name") == name:
            return task
        for section in ("block", "rescue", "always"):
            try:
                return _task(task.get(section, []), name)
            except LookupError:
                pass
    raise LookupError(name)


def _render(value: str, variables: dict):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(trust_as_template(value), fail_on_undefined=True)


class OpenClawAudioTranscriptionTests(unittest.TestCase):
    def test_v2026_9_1_config_migration_is_lossless_and_idempotent(self) -> None:
        config_tasks = _yaml("tasks/config.yml")
        migration = _task(
            config_tasks,
            "config | Migrate legacy settings removed in OpenClaw 2026.9.1",
        )
        script = migration["ansible.builtin.command"]["argv"][2]

        original = {
            "agents": {
                "defaults": {
                    "memorySearch": {"provider": "local", "fallback": "none"},
                    "model": {"primary": "openai/gpt-5.6-sol"},
                }
            },
            "memory": {"unrelated": True},
            "meta": {
                "lastTouchedAt": "2026-08-17T12:17:29.741Z",
                "lastTouchedVersion": "2026.7.1",
            },
            "unmanaged": {"preserved": True},
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "openclaw.json"
            config_path.write_text(json.dumps(original), encoding="utf-8")
            config_path.chmod(0o640)

            first = subprocess.run(
                [sys.executable, "-c", script, str(config_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            migrated = json.loads(config_path.read_text(encoding="utf-8"))
            second = subprocess.run(
                [sys.executable, "-c", script, str(config_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            migrated_mode = stat.S_IMODE(config_path.stat().st_mode)

            existing_search = {"provider": "existing", "fallback": "remote"}
            config_path.write_text(
                json.dumps(
                    {
                        "agents": {
                            "defaults": {
                                "memorySearch": {
                                    "provider": "legacy",
                                    "fallback": "none",
                                }
                            }
                        },
                        "memory": {"search": existing_search},
                    }
                ),
                encoding="utf-8",
            )
            subprocess.run(
                [sys.executable, "-c", script, str(config_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            migrated_with_existing_search = json.loads(
                config_path.read_text(encoding="utf-8")
            )

        self.assertEqual(first.stdout.strip(), "changed")
        self.assertEqual(second.stdout.strip(), "unchanged")
        self.assertEqual(migrated_mode, 0o640)
        self.assertNotIn("memorySearch", migrated["agents"]["defaults"])
        self.assertEqual(
            migrated["memory"]["search"],
            {"provider": "local", "fallback": "none"},
        )
        self.assertTrue(migrated["memory"]["unrelated"])
        self.assertNotIn("lastTouchedAt", migrated["meta"])
        self.assertEqual(migrated["meta"]["lastTouchedVersion"], "2026.7.1")
        self.assertTrue(migrated["unmanaged"]["preserved"])
        self.assertEqual(
            migrated_with_existing_search["memory"]["search"], existing_search
        )
        self.assertNotIn(
            "memorySearch",
            migrated_with_existing_search["agents"]["defaults"],
        )

        main_tasks = _yaml("tasks/main.yml")
        names = [task.get("name") for task in main_tasks]
        self.assertLess(
            names.index("main | Render gateway config"),
            names.index("main | Install the official Codex runtime plugin"),
        )

    def test_audio_is_opt_in_with_safe_profile_defaults(self) -> None:
        defaults = _yaml("defaults/main.yml")

        self.assertFalse(defaults["openclaw_audio_transcription_managed"])
        self.assertFalse(defaults["openclaw_audio_transcription_enabled"])
        self.assertFalse(
            defaults["openclaw_audio_transcription_allow_private_network"]
        )
        self.assertEqual(
            defaults["openclaw_audio_transcription_provider"], "senseaudio"
        )
        self.assertEqual(
            defaults["openclaw_audio_transcription_profile_id"], "senseaudio:audio"
        )
        self.assertEqual(defaults["openclaw_audio_transcription_api_key"], "")
        self.assertEqual(
            defaults["openclaw_audio_transcription_api_key_env"],
            "OPENCLAW_AUDIO_TRANSCRIPTION_API_KEY",
        )

    def test_config_pins_audio_to_dedicated_profile_and_capability(self) -> None:
        tasks = _yaml("tasks/config.yml")
        task = _task(tasks, "config | Build optional audio transcription patch")
        patch = task["ansible.builtin.set_fact"]["_openclaw_audio_config_patch"]

        self.assertIn("openclaw_audio_transcription_provider", patch)
        self.assertIn("openclaw_audio_transcription_profile_id", patch)
        self.assertIn('"capabilities": ["audio"]', patch)
        self.assertIn('"models"', patch)
        self.assertIn('"allowPrivateNetwork"', patch)
        self.assertIn('"preferredModel": (openclaw_audio_transcription_provider', patch)
        self.assertIn("openclaw_audio_transcription_timeout_seconds", patch)

        rendered = _render(
            patch,
            {
                "openclaw_audio_transcription_enabled": True,
                "openclaw_audio_transcription_provider": "senseaudio",
                "openclaw_audio_transcription_model": "gpt-4o-mini-transcribe",
                "openclaw_audio_transcription_profile_id": "senseaudio:voxhelm",
                "openclaw_audio_transcription_base_url": "http://studio:8787/v1",
                "openclaw_audio_transcription_allow_private_network": True,
                "openclaw_audio_transcription_timeout_seconds": 120,
            },
        )
        media = rendered["tools"]["media"]
        self.assertEqual(
            media["models"],
            [
                {
                    "provider": "senseaudio",
                    "model": "gpt-4o-mini-transcribe",
                    "profile": "senseaudio:voxhelm",
                    "baseUrl": "http://studio:8787/v1",
                    "capabilities": ["audio"],
                }
            ],
        )
        self.assertEqual(
            media["audio"],
            {
                "enabled": True,
                "preferredModel": "senseaudio/gpt-4o-mini-transcribe",
                "timeoutSeconds": 120,
            },
        )
        self.assertTrue(
            rendered["models"]["providers"]["senseaudio"]["request"][
                "allowPrivateNetwork"
            ]
        )
        self.assertEqual(
            rendered["models"]["providers"]["senseaudio"]["baseUrl"],
            "http://studio:8787/v1",
        )
        self.assertEqual(
            rendered["models"]["providers"]["senseaudio"]["models"],
            [
                {
                    "id": "gpt-4o-mini-transcribe",
                    "name": "gpt-4o-mini-transcribe",
                }
            ],
        )

    def test_managed_disable_renders_an_inactive_empty_audio_config(self) -> None:
        tasks = _yaml("tasks/config.yml")
        task = _task(tasks, "config | Build optional audio transcription patch")
        patch = task["ansible.builtin.set_fact"]["_openclaw_audio_config_patch"]
        rendered = _render(
            patch,
            {
                "openclaw_audio_transcription_enabled": False,
                "openclaw_audio_transcription_provider": "senseaudio",
            },
        )

        self.assertEqual(
            rendered,
            {
                "tools": {
                    "media": {"models": [], "audio": {"enabled": False}}
                }
            },
        )

        runtime_task = _task(
            tasks, "config | Build existing-config audio transcription patch"
        )
        runtime_patch = runtime_task["ansible.builtin.set_fact"][
            "_openclaw_audio_runtime_patch"
        ]
        image_model = {
            "provider": "senseaudio",
            "model": "gpt-image-1",
            "capabilities": ["image"],
        }
        rendered_runtime = _render(
            runtime_patch,
            {
                "_openclaw_audio_config_patch": rendered,
                "_openclaw_audio_model_entry": {
                    "provider": "senseaudio",
                    "model": "gpt-4o-mini-transcribe",
                    "profile": "senseaudio:voxhelm",
                    "capabilities": ["audio"],
                },
                "_openclaw_preserved_media_models": [image_model],
                "openclaw_audio_transcription_enabled": False,
                "openclaw_audio_transcription_provider": "senseaudio",
                "_openclaw_existing_config": {
                    "models": {
                        "providers": {
                            "senseaudio": {
                                "baseUrl": "http://studio:8787/v1",
                                "models": [
                                    {
                                        "id": "gpt-4o-mini-transcribe",
                                        "name": "gpt-4o-mini-transcribe",
                                    }
                                ],
                                "request": {"allowPrivateNetwork": True},
                            }
                        }
                    }
                },
            },
        )
        self.assertFalse(rendered_runtime["tools"]["media"]["audio"]["enabled"])
        self.assertEqual(rendered_runtime["tools"]["media"]["models"], [image_model])
        self.assertFalse(
            rendered_runtime["models"]["providers"]["senseaudio"]["request"][
                "allowPrivateNetwork"
            ]
        )

    def test_runtime_patch_preserves_explicit_non_audio_models(self) -> None:
        tasks = _yaml("tasks/config.yml")
        preserve = _task(tasks, "config | Preserve unmanaged media models")
        runtime = _task(tasks, "config | Build existing-config audio transcription patch")

        conditions = "\n".join(str(condition) for condition in preserve["when"])
        self.assertIn("'audio' not in item.capabilities", conditions)
        self.assertIn("item.profile", conditions)
        self.assertIn("not (openclaw_audio_transcription_enabled | bool)", conditions)
        expression = runtime["ansible.builtin.set_fact"][
            "_openclaw_audio_runtime_patch"
        ]
        self.assertIn("_openclaw_preserved_media_models", expression)

    def test_auth_profile_uses_secret_ref_and_idempotent_preflight(self) -> None:
        plan = (ROLE_ROOT / "templates/openclaw-audio-secrets-plan.json.j2").read_text(
            encoding="utf-8"
        )
        tasks = _yaml("tasks/audio_transcription.yml")
        preflight = _task(tasks, "audio_transcription | Preflight dedicated auth profile")
        apply = _task(tasks, "audio_transcription | Apply dedicated auth profile")

        self.assertIn('"type": "auth-profiles.api_key.key"', plan)
        self.assertIn('"source": "env"', plan)
        self.assertIn('"scrubEnv": false', plan)
        self.assertNotIn("openclaw_audio_transcription_api_key | to_json", plan)
        self.assertTrue(preflight["no_log"])
        self.assertIn("--dry-run", preflight["ansible.builtin.command"]["argv"])
        self.assertTrue(apply["no_log"])
        self.assertEqual(apply["when"], "_openclaw_audio_secrets_preflight.changed | bool")
        self.assertNotIn("openclaw_audio_transcription_api_key", str(apply))

        rendered_plan = _render(
            plan,
            {
                "openclaw_audio_transcription_provider": "senseaudio",
                "openclaw_audio_transcription_profile_id": "senseaudio:voxhelm",
                "openclaw_audio_transcription_api_key_env": (
                    "OPENCLAW_AUDIO_TRANSCRIPTION_API_KEY"
                ),
            },
        )
        parsed_plan = yaml.safe_load(rendered_plan)
        target = parsed_plan["targets"][0]
        self.assertEqual(target["path"], "profiles.senseaudio:voxhelm.key")
        self.assertEqual(
            target["pathSegments"], ["profiles", "senseaudio:voxhelm", "key"]
        )
        self.assertEqual(target["authProfileProvider"], "senseaudio")
        self.assertEqual(
            target["ref"],
            {
                "source": "env",
                "provider": "default",
                "id": "OPENCLAW_AUDIO_TRANSCRIPTION_API_KEY",
            },
        )

    def test_validation_enforces_isolation_version_and_safe_token_formats(self) -> None:
        tasks = _yaml("tasks/validate.yml")
        managed_validation = _task(tasks, "validate | Audio transcription settings")
        validation = _task(tasks, "validate | Enabled audio transcription settings")
        managed_conditions = "\n".join(
            managed_validation["ansible.builtin.assert"]["that"]
        )
        conditions = "\n".join(validation["ansible.builtin.assert"]["that"])

        self.assertIn("version_type='semver'", managed_conditions)
        self.assertIn("^[A-Za-z0-9._~+/=-]{20,512}\\Z", conditions)
        self.assertIn("openclaw_audio_transcription_api_key_env not in", conditions)
        self.assertIn("openclaw_openai_auth_order | length > 0", managed_conditions)
        self.assertIn(
            "openclaw_openai_auth_order | map('trim') | list",
            managed_conditions,
        )

        version_condition = managed_validation["ansible.builtin.assert"]["that"][1]
        for version, expected in (
            ("v2026.9.1-rc.1", False),
            ("v2026.9.1", True),
            ("v2026.10.0", True),
        ):
            with self.subTest(version=version):
                self.assertEqual(
                    _render(
                        "{{ " + version_condition + " }}",
                        {"openclaw_version": version},
                    ),
                    expected,
                )

        isolation_condition = managed_validation["ansible.builtin.assert"]["that"][6]
        self.assertFalse(
            _render(
                "{{ " + isolation_condition + " }}",
                {
                    "openclaw_audio_transcription_profile_id": "senseaudio:voxhelm",
                    "openclaw_openai_auth_order": [" senseaudio:voxhelm "],
                },
            )
        )

        token_condition = validation["ansible.builtin.assert"]["that"][4]
        self.assertTrue(
            _render(
                "{{ " + token_condition + " }}",
                {"openclaw_audio_transcription_api_key": "a" * 64},
            )
        )
        for suffix in ("\n", "\r\n"):
            with self.subTest(suffix=repr(suffix)):
                self.assertFalse(
                    _render(
                        "{{ " + token_condition + " }}",
                        {"openclaw_audio_transcription_api_key": "a" * 64 + suffix},
                    )
                )

    def test_upgrade_migrations_are_guarded_and_verified_before_restart(self) -> None:
        defaults = _yaml("defaults/main.yml")
        directory_tasks = _yaml("tasks/directories.yml")
        main_tasks = _yaml("tasks/main.yml")
        migration_tasks = _yaml("tasks/upgrade_migrations.yml")

        self.assertTrue(defaults["openclaw_upgrade_migrations_enabled"])

        bind_directories = _task(
            directory_tasks,
            "directories | Ensure OpenClaw bind-mount directories exist (container uid 1000)",
        )
        self.assertIn(
            "{{ openclaw_data_dir }}/backups",
            bind_directories["loop"],
        )
        self.assertEqual(bind_directories["ansible.builtin.file"]["owner"], "1000")
        self.assertEqual(bind_directories["ansible.builtin.file"]["group"], "1000")

        migration_import = _task(
            main_tasks, "main | Run guarded upstream upgrade migrations"
        )
        import_conditions = "\n".join(str(item) for item in migration_import["when"])
        self.assertIn("openclaw_upgrade_migrations_enabled", import_conditions)
        self.assertIn("version_type='semver'", import_conditions)

        doctor = _task(
            migration_tasks,
            "upgrade_migrations | Run supported non-interactive Doctor repair",
        )
        argv = doctor["ansible.builtin.command"]["argv"]
        self.assertEqual(argv[-4:], ["doctor", "--fix", "--non-interactive", "--yes"])
        self.assertEqual(doctor["when"], "_openclaw_upgrade_migrations_ran | bool")

        stop = _task(
            migration_tasks,
            "upgrade_migrations | Stop gateway before exclusive state migration",
        )
        self.assertIn("ansible_facts.services", "\n".join(stop["when"]))

        required = _task(
            migration_tasks,
            "upgrade_migrations | Require removal of runtime-blocking legacy state",
        )
        requirements = "\n".join(required["ansible.builtin.assert"]["that"])
        self.assertIn("_openclaw_remaining_workspace_setup_paths", requirements)
        self.assertIn("_openclaw_remaining_workspace_attestations", requirements)

        names = [task.get("name") for task in main_tasks]
        self.assertLess(
            names.index("main | Install the official Codex runtime plugin"),
            names.index("main | Run guarded upstream upgrade migrations"),
        )
        self.assertLess(
            names.index("main | Run guarded upstream upgrade migrations"),
            names.index("main | Configure audio transcription credentials"),
        )

    def test_health_check_requires_gateway_and_telegram_readiness(self) -> None:
        health_tasks = _yaml("tasks/health.yml")
        gateway = _task(
            health_tasks, "health | Wait for gateway and configured channel readiness"
        )
        telegram = _task(
            health_tasks, "health | Require configured Telegram channel readiness"
        )

        argv = gateway["ansible.builtin.command"]["argv"]
        self.assertEqual(argv[:2], ["python3", "-c"])
        helper = argv[2]
        self.assertIn('json.loads(result.stdout)', helper)
        self.assertIn('telegram.get("configured") is True', helper)
        self.assertIn('telegram.get("running") is True', helper)
        self.assertIn('telegram.get("connected") is True', helper)
        self.assertIn('telegram.get("lastError") is None', helper)
        self.assertEqual(gateway["until"], "_openclaw_gateway_health.rc == 0")

        names = [task.get("name") for task in health_tasks]
        self.assertLess(
            names.index("health | Determine whether Telegram readiness is required"),
            names.index("health | Wait for gateway and configured channel readiness"),
        )

        with tempfile.TemporaryDirectory() as directory:
            fake_docker = Path(directory) / "docker"
            fake_docker.write_text(
                "#!/bin/sh\nprintf '%s' \"$OPENCLAW_TEST_HEALTH\"\n",
                encoding="utf-8",
            )
            fake_docker.chmod(fake_docker.stat().st_mode | stat.S_IXUSR)

            def run_health(payload: str, telegram_expected: bool = True):
                env = os.environ.copy()
                env["PATH"] = f"{directory}:{env['PATH']}"
                env["OPENCLAW_TEST_HEALTH"] = payload
                return subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        helper,
                        "openclaw-gateway",
                        "true" if telegram_expected else "false",
                    ],
                    capture_output=True,
                    text=True,
                    env=env,
                    check=False,
                )

            ready = json.dumps(
                {
                    "ok": True,
                    "channels": {
                        "telegram": {
                            "configured": True,
                            "running": True,
                            "connected": True,
                            "lastError": None,
                        }
                    },
                }
            )
            starting = json.dumps(
                {
                    "ok": True,
                    "channels": {
                        "telegram": {
                            "configured": True,
                            "running": True,
                            "connected": False,
                            "lastError": None,
                        }
                    },
                }
            )
            errored = json.dumps(
                {
                    "ok": True,
                    "channels": {
                        "telegram": {
                            "configured": True,
                            "running": True,
                            "connected": True,
                            "lastError": "login failed",
                        }
                    },
                }
            )
            self.assertEqual(run_health(ready).returncode, 0)
            self.assertNotEqual(run_health(starting).returncode, 0)
            self.assertNotEqual(run_health(errored).returncode, 0)
            self.assertNotEqual(run_health("").returncode, 0)
            self.assertNotEqual(run_health("{not json").returncode, 0)
            self.assertEqual(run_health(starting, telegram_expected=False).returncode, 0)

        requirements = "\n".join(telegram["ansible.builtin.assert"]["that"])
        self.assertIn(".configured", requirements)
        self.assertIn(".running", requirements)
        self.assertIn(".connected", requirements)
        self.assertEqual(
            telegram["when"], "_openclaw_telegram_expected_enabled | bool"
        )

        expectation = _task(
            health_tasks,
            "health | Determine whether Telegram readiness is required",
        )
        expected = expectation["ansible.builtin.set_fact"][
            "_openclaw_telegram_expected_enabled"
        ]
        self.assertTrue(
            _render(
                expected,
                {
                    "openclaw_gateway_config": {
                        "channels": {"telegram": {"enabled": True}}
                    },
                    "openclaw_telegram_enabled": False,
                },
            )
        )
        self.assertFalse(
            _render(
                expected,
                {
                    "openclaw_gateway_config": {
                        "channels": {"telegram": {"enabled": False}}
                    },
                    "openclaw_telegram_enabled": True,
                },
            )
        )
        self.assertTrue(
            _render(
                expected,
                {
                    "openclaw_gateway_config": {},
                    "openclaw_telegram_enabled": True,
                },
            )
        )


if __name__ == "__main__":
    unittest.main()
