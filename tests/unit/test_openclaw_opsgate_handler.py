from __future__ import annotations

import json
import types
from pathlib import Path

import pytest


HANDLER_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "roles"
    / "openclaw_deploy"
    / "templates"
    / "opsgate-submit-handler.py.j2"
)


def _load_handler_module():
    source = HANDLER_TEMPLATE_PATH.read_text(encoding="utf-8")
    source = source.replace(
        "{{ openclaw_opsgate_container_credentials_path | to_json }}",
        json.dumps("/tmp/opsgate_submit.json"),
    )
    source = source.replace(
        "{{ openclaw_opsgate_command_skill_name | to_json }}",
        json.dumps("opsgate"),
    )
    if "{{" in source:
        start = source.index("{{")
        end = source.index("}}", start) + 2 if "}}" in source[start:] else start + 2
        snippet = source[start:end]
        raise AssertionError(f"Unreplaced Jinja2 variable in template: {snippet}")

    module = types.ModuleType("openclaw_opsgate_handler")
    module.__dict__["__name__"] = "openclaw_opsgate_handler"
    exec(compile(source, str(HANDLER_TEMPLATE_PATH), "exec"), module.__dict__)
    return module


handler = _load_handler_module()


def _base_config() -> dict:
    return {
        "submit_base_url": "http://opsgate.internal:8711",
        "approval_base_url": "https://opsgate.example.test",
        "submit_token": "t" * 32,
        "submit_timeout_seconds": 10,
        "ticket_expires_seconds": 0,
        "title_max_chars": 120,
        "summary_max_chars": 240,
        "request_max_chars": 4000,
        "task_ref_max_chars": 120,
    }


def test_normalize_argv_splits_single_shell_style_argument():
    assert handler._normalize_argv(['create --title "Hello world" issue text']) == [
        "create",
        "--title",
        "Hello world",
        "issue",
        "text",
    ]


def test_normalize_argv_preserves_unbalanced_input():
    raw = ['create --title "unterminated']
    assert handler._normalize_argv(raw) == raw


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("  Hello   world  ", "Hello world"),
        ("abcdef", "abc"),
    ],
)
def test_sanitize_text_normalizes_and_truncates(raw_value, expected):
    max_chars = 20 if expected == "Hello world" else 3
    assert handler._sanitize_text(raw_value, max_chars) == expected


def test_sanitize_multiline_text_collapses_blank_lines_and_truncates():
    assert handler._sanitize_multiline_text("one\n\n\n\n two \n", 80) == "one\n\n two"
    assert handler._sanitize_multiline_text("abcdef", 3) == "abc"


def test_derive_title_uses_first_non_empty_line():
    issue_text = "\n\nFirst line title\nSecond line details"
    assert handler._derive_title(issue_text, 120) == "First line title"


def test_derive_title_rejects_empty_issue():
    with pytest.raises(handler.OpsGateSkillError, match="Issue description cannot be empty"):
        handler._derive_title("   \n\t", 120)


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("INC-123", "INC-123"),
        ("task/ref:42", "task/ref:42"),
        ("", ""),
    ],
)
def test_validate_task_ref_accepts_expected_values(raw_value, expected):
    assert handler._validate_task_ref(raw_value, 120) == expected


def test_validate_task_ref_rejects_invalid_characters():
    with pytest.raises(handler.OpsGateSkillError, match="task_ref may contain only"):
        handler._validate_task_ref("bad task ref", 120)


def test_validate_task_ref_rejects_overlong_value():
    with pytest.raises(handler.OpsGateSkillError, match="task_ref must be at most 4 characters"):
        handler._validate_task_ref("ABCDE", 4)


@pytest.mark.parametrize(
    "raw_value",
    [
        "ftp://opsgate.example.test",
        "https://opsgate.example.test?foo=bar",
        "https://opsgate.example.test#frag",
        "",
    ],
)
def test_normalize_url_rejects_invalid_values(raw_value):
    with pytest.raises(handler.OpsGateSkillError, match="OpsGate URL is invalid"):
        handler._normalize_url(raw_value)


def test_build_parser_parses_create_arguments():
    parser = handler._build_parser()
    args = parser.parse_args(
        ["create", "--title", "Investigate", "--task-ref", "INC-123", "queue", "stuck"]
    )
    assert args.command == "create"
    assert args.title == "Investigate"
    assert args.task_ref == "INC-123"
    assert args.issue == ["queue", "stuck"]


def test_build_prompt_keeps_constraints_after_issue_description():
    prompt = handler._build_prompt("Service is timing out")
    assert "## Issue Description\nService is timing out\n\n## Constraints" in prompt
    assert "- Treat this as an investigator-only ticket." in prompt


def test_main_create_submits_fixed_single_step_ticket(monkeypatch, capsys):
    monkeypatch.setattr(handler, "_load_config", _base_config)
    captured: dict[str, object] = {}

    def _fake_post_ticket(config, payload):
        captured["config"] = config
        captured["payload"] = payload
        return 201, {"id": "ticket-123"}

    monkeypatch.setattr(handler, "_post_ticket", _fake_post_ticket)
    monkeypatch.setattr(
        handler.sys,
        "argv",
        [
            "opsgate-submit-handler.py",
            "create",
            "--title",
            "Queue incident",
            "--task-ref",
            "INC-123",
            "Queue",
            "is",
            "stuck",
        ],
    )

    result = handler.main()
    output = capsys.readouterr().out
    payload = captured["payload"]

    assert result == 0
    assert "Ticket ID: ticket-123" in output
    assert payload["title"] == "Queue incident"
    assert payload["task_ref"] == "INC-123"
    assert payload["execution_plan"] == [
        {
            "role": "investigator",
            "agent": "codex",
            "prompt_markdown": handler._build_prompt("Queue is stuck"),
        }
    ]
    assert payload["context"] == {
        "producer": "openclaw",
        "integration": "opsgate-submit-v1",
        "workflow": "single-step-investigator",
        "request": "Queue is stuck",
    }
    assert "expires_at" not in payload


def test_main_duplicate_ticket_returns_clear_error(monkeypatch, capsys):
    monkeypatch.setattr(handler, "_load_config", _base_config)
    monkeypatch.setattr(
        handler,
        "_post_ticket",
        lambda _config, _payload: (409, {"error": "duplicate_open_ticket"}),
    )
    monkeypatch.setattr(
        handler.sys,
        "argv",
        [
            "opsgate-submit-handler.py",
            "create",
            "--task-ref",
            "INC-123",
            "Queue",
            "is",
            "stuck",
        ],
    )

    with pytest.raises(handler.OpsGateSkillError, match="OpsGate already has an open ticket for INC-123."):
        handler.main()

    assert capsys.readouterr().out == ""
