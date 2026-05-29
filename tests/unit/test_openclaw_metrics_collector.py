from __future__ import annotations

import json
import re
import subprocess
import sys
import types
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
