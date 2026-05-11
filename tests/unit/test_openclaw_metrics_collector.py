from __future__ import annotations

import re
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
