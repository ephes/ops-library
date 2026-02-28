from __future__ import annotations

import json
import types
from pathlib import Path
from urllib.request import Request

import pytest


HANDLER_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "roles"
    / "openclaw_deploy"
    / "templates"
    / "homeassistant-read-handler.py.j2"
)


def _load_handler_module():
    source = HANDLER_TEMPLATE_PATH.read_text(encoding="utf-8")
    source = source.replace(
        "{{ openclaw_homeassistant_container_credentials_path | to_json }}",
        json.dumps("/tmp/homeassistant.json"),
    )
    source = source.replace(
        "{{ openclaw_homeassistant_command_skill_name | to_json }}",
        json.dumps("homeassistant"),
    )
    if "{{" in source:
        start = source.index("{{")
        end = source.index("}}", start) + 2 if "}}" in source[start:] else start + 2
        snippet = source[start:end]
        raise AssertionError(f"Unreplaced Jinja2 variable in template: {snippet}")

    module = types.ModuleType("openclaw_homeassistant_handler")
    module.__dict__["__name__"] = "openclaw_homeassistant_handler"
    exec(compile(source, str(HANDLER_TEMPLATE_PATH), "exec"), module.__dict__)
    return module


handler = _load_handler_module()


def _write_config(tmp_path: Path, *, base_url: str) -> Path:
    config_path = tmp_path / "homeassistant.json"
    config_path.write_text(
        json.dumps(
            {
                "base_url": base_url,
                "token": "test-token",
                "allow_domains": ["sun"],
                "allow_entities": [],
                "allow_write_domains": [],
                "allow_write_entities": [],
                "request_timeout_seconds": 8,
                "default_limit": 10,
                "max_limit": 25,
                "state_max_chars": 200,
                "friendly_name_max_chars": 120,
                "attribute_max_items": 8,
                "attribute_value_max_chars": 120,
            }
        ),
        encoding="utf-8",
    )
    return config_path


def test_normalize_entity_id_lowercases_and_trims():
    assert handler._normalize_entity_id(" Light.Kitchen_1 ") == "light.kitchen_1"


def test_normalize_entity_id_rejects_invalid_values():
    with pytest.raises(handler.HASkillError, match="Entity ID must match"):
        handler._normalize_entity_id("light.bad-id")


def test_normalize_entity_id_rejects_empty_input():
    with pytest.raises(handler.HASkillError, match="Entity ID must match"):
        handler._normalize_entity_id("")


def test_entity_allowed_read_and_write_sets_are_separate():
    read_allow_domains = ["light"]
    read_allow_entities = []
    write_allow_domains = []
    write_allow_entities = ["automation.weekday_07_40_esszimmer_blink"]

    assert handler._entity_allowed("light.esszimmer", read_allow_domains, read_allow_entities)
    assert not handler._entity_allowed(
        "light.esszimmer",
        write_allow_domains,
        write_allow_entities,
    )

    assert handler._entity_allowed(
        "automation.weekday_07_40_esszimmer_blink",
        write_allow_domains,
        write_allow_entities,
    )
    assert not handler._entity_allowed(
        "automation.weekday_07_40_esszimmer_blink",
        read_allow_domains,
        read_allow_entities,
    )


def test_entity_allowed_with_empty_allowlists_returns_false():
    assert not handler._entity_allowed("sun.sun", [], [])


def test_write_allowlist_happy_path_calls_expected_service(monkeypatch, capsys):
    monkeypatch.setattr(
        handler,
        "_load_config",
        lambda _path: {
            "base_url": "http://ha.local",
            "token": "test-token",
            "allow_domains": ["sun"],
            "allow_entities": [],
            "allow_write_domains": [],
            "allow_write_entities": ["automation.weekday_07_40_esszimmer_blink"],
            "request_timeout_seconds": 8,
            "default_limit": 10,
            "max_limit": 25,
            "state_max_chars": 200,
            "friendly_name_max_chars": 120,
            "attribute_max_items": 8,
            "attribute_value_max_chars": 120,
        },
    )

    calls = []

    def _fake_post(*, base_url, token, path, timeout_seconds, payload, operation):
        calls.append(
            {
                "base_url": base_url,
                "token": token,
                "path": path,
                "timeout_seconds": timeout_seconds,
                "payload": payload,
                "operation": operation,
            }
        )
        return []

    monkeypatch.setattr(handler, "_ha_post_json", _fake_post)
    monkeypatch.setattr(
        handler.sys,
        "argv",
        [
            "homeassistant-read-handler.py",
            "turn_on",
            "automation.weekday_07_40_esszimmer_blink",
        ],
    )

    result = handler.main()
    output = capsys.readouterr().out

    assert result == 0
    assert len(calls) == 1
    assert calls[0]["path"] == "/api/services/homeassistant/turn_on"
    assert calls[0]["payload"] == {"entity_id": "automation.weekday_07_40_esszimmer_blink"}
    assert "Status: accepted" in output


def test_write_allowlist_deny_path_returns_access_denied(monkeypatch, capsys):
    monkeypatch.setattr(
        handler,
        "_load_config",
        lambda _path: {
            "base_url": "http://ha.local",
            "token": "test-token",
            "allow_domains": ["sun"],
            "allow_entities": [],
            "allow_write_domains": [],
            "allow_write_entities": ["automation.weekday_07_40_esszimmer_blink"],
            "request_timeout_seconds": 8,
            "default_limit": 10,
            "max_limit": 25,
            "state_max_chars": 200,
            "friendly_name_max_chars": 120,
            "attribute_max_items": 8,
            "attribute_value_max_chars": 120,
        },
    )

    called = {"ha_post_called": False}

    def _unexpected_post(*args, **kwargs):
        called["ha_post_called"] = True
        raise AssertionError("write request should not be executed for denied entities")

    monkeypatch.setattr(handler, "_ha_post_json", _unexpected_post)
    monkeypatch.setattr(
        handler.sys,
        "argv",
        ["homeassistant-read-handler.py", "turn_on", "sun.sun"],
    )

    result = handler.main()
    output = capsys.readouterr().out

    assert result == 2
    assert "Home Assistant access denied:" in output
    assert "Write action for entity 'sun.sun' is not allowlisted." in output
    assert called["ha_post_called"] is False


def test_load_config_rejects_base_url_with_query(tmp_path):
    path = _write_config(tmp_path, base_url="https://ha.local?foo=bar")
    with pytest.raises(handler.HASkillError, match="base URL is invalid"):
        handler._load_config(str(path))


def test_load_config_rejects_base_url_with_fragment(tmp_path):
    path = _write_config(tmp_path, base_url="https://ha.local#frag")
    with pytest.raises(handler.HASkillError, match="base URL is invalid"):
        handler._load_config(str(path))


def test_load_config_rejects_non_http_scheme(tmp_path):
    path = _write_config(tmp_path, base_url="ftp://ha.local")
    with pytest.raises(handler.HASkillError, match="base URL is invalid"):
        handler._load_config(str(path))


@pytest.mark.parametrize(
    ("raw_limit", "expected"),
    [
        (None, 10),
        (0, 1),
        (-5, 1),
        (3, 3),
        (500, 25),
    ],
)
def test_bounded_limit_edges(raw_limit, expected):
    assert handler._bounded_limit(raw_limit, 10, 25) == expected


def test_no_redirect_handler_rejects_redirect_request():
    no_redirect = handler._NoRedirectHandler()
    req = Request("https://example.invalid/origin")
    assert (
        no_redirect.redirect_request(req, None, 302, "Found", {}, "https://example.invalid")
        is None
    )
