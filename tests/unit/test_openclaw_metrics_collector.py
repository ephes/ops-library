from __future__ import annotations

import json
import re
import subprocess
import sys
import types
from argparse import Namespace
from pathlib import Path


COLLECTOR_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "roles"
    / "openclaw_deploy"
    / "templates"
    / "openclaw-metrics-collector.py.j2"
)


def _load_collector_module():
    source = COLLECTOR_TEMPLATE_PATH.read_text(encoding="utf-8")
    rendered = re.sub(r"\{\{[^{}]+\}\}", "0", source)
    if "{{" in rendered:
        start = rendered.index("{{")
        end = rendered.index("}}", start) + 2 if "}}" in rendered[start:] else start + 2
        snippet = rendered[start:end]
        raise AssertionError(f"Unreplaced Jinja2 variable in template: {snippet}")

    module = types.ModuleType("openclaw_metrics_collector")
    module.__dict__["__name__"] = "openclaw_metrics_collector"
    exec(compile(rendered, str(COLLECTOR_TEMPLATE_PATH), "exec"), module.__dict__)
    return module


collector = _load_collector_module()


def test_run_json_command_rejects_nonzero_by_default(monkeypatch):
    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout='{"ok": false}',
            stderr="health failed",
        )

    monkeypatch.setattr(collector.subprocess, "run", fake_run)

    try:
        collector.run_json_command(["openclaw", "health", "--json"], timeout=5)
    except RuntimeError as err:
        assert "command failed rc=1" in str(err)
    else:
        raise AssertionError("nonzero command should fail without allow_nonzero_json")


def test_run_json_command_allows_nonzero_parseable_json(monkeypatch):
    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout='{"ok": false, "channels": {"telegram": {"probe": {"ok": false}}}}',
            stderr="telegram getMe timeout",
        )

    monkeypatch.setattr(collector.subprocess, "run", fake_run)

    result = collector.run_json_command(
        ["openclaw", "health", "--json"],
        timeout=5,
        allow_nonzero_json=True,
    )

    assert result["ok"] is False
    assert result["channels"]["telegram"]["probe"]["ok"] is False


def test_run_json_command_rejects_nonzero_without_json_even_when_allowed(monkeypatch):
    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="container unavailable",
        )

    monkeypatch.setattr(collector.subprocess, "run", fake_run)

    try:
        collector.run_json_command(
            ["openclaw", "health", "--json"],
            timeout=5,
            allow_nonzero_json=True,
        )
    except RuntimeError as err:
        message = str(err)
        assert "command failed rc=1" in message
        assert "JSON was unusable" in message
    else:
        raise AssertionError("nonzero command without JSON should fail")


def test_main_keeps_collector_ok_for_nonzero_health_with_telegram_probe_failure(
    monkeypatch,
    tmp_path,
):
    output_path = tmp_path / "openclaw-health.json"

    health_payload = {
        "ok": False,
        "channels": {
            "telegram": {
                "running": True,
                "connected": False,
                "probe": {"ok": False},
            },
        },
    }
    channels_payload = {
        "channels": {
            "telegram": {
                "running": True,
                "configured": True,
                "lastError": None,
            },
        },
    }

    def fake_run(command, *_args, **_kwargs):
        command_text = " ".join(command)
        if " health --json" in command_text:
            return subprocess.CompletedProcess(
                args=command,
                returncode=1,
                stdout=json.dumps(health_payload),
                stderr="fetch timeout after 10000ms: api.telegram.org getMe",
            )
        if " channels status --json" in command_text:
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout=json.dumps(channels_payload),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {command_text}")

    monkeypatch.setattr(collector.subprocess, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "openclaw-metrics-collector",
            "--container",
            "openclaw-gateway",
            "--output",
            str(output_path),
            "--command-timeout",
            "5",
        ],
    )

    assert collector.main() == 0

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    openclaw = payload["openclaw"]
    assert openclaw["collector_ok"] is True
    assert openclaw["collector_errors"] == []
    assert openclaw["health"]["ok"] is False
    assert openclaw["health"]["telegram_probe_ok"] is False
    assert openclaw["channels"]["telegram"]["running"] is True


def test_main_marks_collector_failed_when_channels_status_fails(
    monkeypatch,
    tmp_path,
):
    output_path = tmp_path / "openclaw-health.json"

    health_payload = {
        "ok": True,
        "channels": {
            "telegram": {
                "running": True,
                "connected": True,
            },
        },
    }

    def fake_run(command, *_args, **_kwargs):
        command_text = " ".join(command)
        if " health --json" in command_text:
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout=json.dumps(health_payload),
                stderr="",
            )
        if " channels status --json" in command_text:
            return subprocess.CompletedProcess(
                args=command,
                returncode=1,
                stdout='{"channels": {"telegram": {"running": true}}}',
                stderr="channels status failed",
            )
        raise AssertionError(f"unexpected command: {command_text}")

    monkeypatch.setattr(collector.subprocess, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "openclaw-metrics-collector",
            "--container",
            "openclaw-gateway",
            "--output",
            str(output_path),
            "--command-timeout",
            "5",
        ],
    )

    assert collector.main() == 0

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    openclaw = payload["openclaw"]
    assert openclaw["collector_ok"] is False
    assert openclaw["health"]["ok"] is True
    assert openclaw["health"]["telegram_probe_ok"] is True
    assert openclaw["channels"]["telegram"]["running"] is False
    assert openclaw["collector_errors"]
    assert "channels status failed" in openclaw["collector_errors"][0]


def test_canary_expected_match_exact():
    assert collector.canary_expected_match("OPENCLAW_CANARY_OK", "OPENCLAW_CANARY_OK")


def test_canary_expected_match_multiline_line_match():
    observed = "some preface\nOPENCLAW_CANARY_OK\nsome suffix"
    assert collector.canary_expected_match(observed, "OPENCLAW_CANARY_OK")


def test_canary_expected_match_rejects_partial_token():
    assert not collector.canary_expected_match(
        "OPENCLAW_CANARY_OK_NOT",
        "OPENCLAW_CANARY_OK",
    )


def test_canary_expected_match_rejects_empty_inputs():
    assert not collector.canary_expected_match("", "OPENCLAW_CANARY_OK")
    assert not collector.canary_expected_match("OPENCLAW_CANARY_OK", "")


def test_canary_expected_match_trims_line_whitespace():
    observed = "  OPENCLAW_CANARY_OK  \n"
    assert collector.canary_expected_match(observed, "OPENCLAW_CANARY_OK")


def test_build_payload_includes_stable_canary_metadata_keys():
    payload = collector.build_payload()
    canary = payload["openclaw"]["synthetic"]["canary"]
    assert "agent" in canary
    assert "timeout_seconds" in canary
    assert "session_id" in canary
    assert canary["agent"] is None
    assert canary["timeout_seconds"] == 0
    assert canary["session_id"] == ""
    assert canary["last_run"]["session_id"] is None


def test_build_canary_attempt_session_id_uses_epoch_and_attempt():
    assert (
        collector.build_canary_attempt_session_id("probe-openclaw-canary", 1780466312, 3)
        == "probe-openclaw-canary-1780466312-a3"
    )


def test_cleanup_synthetic_canary_sessions_removes_only_old_canary_files(tmp_path):
    old_names = [
        "probe-openclaw-canary.jsonl",
        "probe-openclaw-canary.trajectory.jsonl",
        "probe-openclaw-canary-1780466312-a1.jsonl",
        "probe-openclaw-canary-1780466312-a1.trajectory-path.json",
    ]
    for name in old_names:
        path = tmp_path / name
        path.write_text("old", encoding="utf-8")
        collector.os.utime(path, (1000, 1000))

    keep_old_other = tmp_path / "probe-openclaw-other-1780466312-a1.jsonl"
    keep_old_other.write_text("old other", encoding="utf-8")
    collector.os.utime(keep_old_other, (1000, 1000))

    keep_fresh = tmp_path / "probe-openclaw-canary-1780469999-a1.jsonl"
    keep_fresh.write_text("fresh", encoding="utf-8")
    collector.os.utime(keep_fresh, (1900, 1900))

    removed = collector.cleanup_synthetic_canary_sessions(
        str(tmp_path),
        "probe-openclaw-canary",
        retention_seconds=600,
        now_epoch=2000,
    )

    assert removed == len(old_names)
    for name in old_names:
        assert not (tmp_path / name).exists()
    assert keep_old_other.exists()
    assert keep_fresh.exists()


def test_run_synthetic_canary_uses_fresh_session_per_attempt(monkeypatch, tmp_path):
    commands = []

    def fake_run_json_command(command, *_args, **_kwargs):
        commands.append(command)
        return {
            "status": "ok",
            "result": {
                "payloads": [{"text": "OPENCLAW_CANARY_OK"}],
                "meta": {
                    "durationMs": 123,
                    "agentMeta": {"provider": "test-provider", "model": "test-model"},
                },
            },
        }

    times = iter([1000, 1000])
    monkeypatch.setattr(collector.time, "time", lambda: next(times, 1000))
    monkeypatch.setattr(collector.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(collector, "run_json_command", fake_run_json_command)

    payload = collector.build_payload()
    args = Namespace(
        synthetic_canary_enabled=1,
        synthetic_canary_interval=300,
        synthetic_canary_timeout=45,
        synthetic_canary_agent="",
        synthetic_canary_session_id="probe-openclaw-canary",
        synthetic_canary_message="Reply exactly: OPENCLAW_CANARY_OK",
        synthetic_canary_expected_text="OPENCLAW_CANARY_OK",
        synthetic_canary_state_path=str(tmp_path / "state.json"),
        synthetic_canary_force_run=True,
        synthetic_canary_max_attempts=3,
        synthetic_canary_retry_delay=0,
        synthetic_canary_output_max_chars=256,
        synthetic_canary_sessions_dir=str(tmp_path),
        synthetic_canary_session_retention_seconds=86400,
        container="openclaw-gateway",
    )

    collector.run_synthetic_canary(args, payload)

    assert commands
    command = commands[0]
    assert command[command.index("--session-id") + 1] == "probe-openclaw-canary-1000-a1"
    last_run = payload["openclaw"]["synthetic"]["canary"]["last_run"]
    assert last_run["ok"] is True
    assert last_run["session_id"] == "probe-openclaw-canary-1000-a1"
    assert payload["openclaw"]["synthetic"]["canary"]["due"] is False


def test_run_synthetic_canary_retries_with_distinct_session_ids(monkeypatch, tmp_path):
    commands = []

    def fake_run_json_command(command, *_args, **_kwargs):
        commands.append(command)
        if len(commands) == 1:
            return {
                "status": "ok",
                "result": {
                    "payloads": [{"text": "WRONG_MARKER"}],
                    "meta": {
                        "durationMs": 111,
                        "agentMeta": {"provider": "test-provider", "model": "test-model"},
                    },
                },
            }
        return {
            "status": "ok",
            "result": {
                "payloads": [{"text": "OPENCLAW_CANARY_OK"}],
                "meta": {
                    "durationMs": 222,
                    "agentMeta": {"provider": "test-provider", "model": "test-model"},
                },
            },
        }

    times = iter([1000, 1001, 1002])
    monkeypatch.setattr(collector.time, "time", lambda: next(times, 1002))
    monkeypatch.setattr(collector.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(collector, "run_json_command", fake_run_json_command)

    payload = collector.build_payload()
    args = Namespace(
        synthetic_canary_enabled=1,
        synthetic_canary_interval=300,
        synthetic_canary_timeout=45,
        synthetic_canary_agent="",
        synthetic_canary_session_id="probe-openclaw-canary",
        synthetic_canary_message="Reply exactly: OPENCLAW_CANARY_OK",
        synthetic_canary_expected_text="OPENCLAW_CANARY_OK",
        synthetic_canary_state_path=str(tmp_path / "state.json"),
        synthetic_canary_force_run=True,
        synthetic_canary_max_attempts=3,
        synthetic_canary_retry_delay=0,
        synthetic_canary_output_max_chars=256,
        synthetic_canary_sessions_dir=str(tmp_path),
        synthetic_canary_session_retention_seconds=86400,
        container="openclaw-gateway",
    )

    collector.run_synthetic_canary(args, payload)

    assert len(commands) == 2
    first_session_id = commands[0][commands[0].index("--session-id") + 1]
    second_session_id = commands[1][commands[1].index("--session-id") + 1]
    assert first_session_id == "probe-openclaw-canary-1001-a1"
    assert second_session_id == "probe-openclaw-canary-1002-a2"
    assert first_session_id != second_session_id
    last_run = payload["openclaw"]["synthetic"]["canary"]["last_run"]
    assert last_run["ok"] is True
    assert last_run["attempts"] == 2
    assert last_run["session_id"] == second_session_id


def test_resolve_telegram_probe_ok_legacy_probe_shape():
    assert collector.resolve_telegram_probe_ok(
        {"channels": {"telegram": {"probe": {"ok": True}}}},
    )


def test_resolve_telegram_probe_ok_current_connected_shape():
    assert collector.resolve_telegram_probe_ok(
        {"channels": {"telegram": {"running": True, "connected": True}}},
    )


def test_resolve_telegram_probe_ok_current_account_connected_shape():
    assert collector.resolve_telegram_probe_ok(
        {
            "channels": {
                "telegram": {
                    "running": True,
                    "accounts": {
                        "default": {"running": True, "connected": True},
                    },
                },
            },
        },
    )


def test_resolve_telegram_probe_ok_prefers_current_shape_over_stale_probe():
    assert collector.resolve_telegram_probe_ok(
        {
            "channels": {
                "telegram": {
                    "running": True,
                    "connected": True,
                    "probe": {"ok": False},
                },
            },
        },
    )


def test_resolve_telegram_probe_ok_rejects_disconnected_channel():
    assert not collector.resolve_telegram_probe_ok(
        {"channels": {"telegram": {"running": True, "connected": False}}},
    )


def test_resolve_telegram_probe_ok_rejects_disconnected_accounts():
    assert not collector.resolve_telegram_probe_ok(
        {
            "channels": {
                "telegram": {
                    "running": True,
                    "accounts": {
                        "default": {"running": True, "connected": False},
                    },
                },
            },
        },
    )


def test_resolve_telegram_probe_ok_rejects_missing_channels():
    assert not collector.resolve_telegram_probe_ok({})
