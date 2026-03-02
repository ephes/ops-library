from __future__ import annotations

import json
import types
from pathlib import Path

import pytest
from jinja2 import Environment, StrictUndefined


HANDLER_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "roles"
    / "openclaw_deploy"
    / "templates"
    / "mail-imap-handler.py.j2"
)


def _load_handler_module():
    source = HANDLER_TEMPLATE_PATH.read_text(encoding="utf-8")
    env = Environment(undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)
    env.filters["to_json"] = json.dumps
    env.filters["bool"] = bool
    rendered = env.from_string(source).render(
        openclaw_imap_host="mail.example.test",
        openclaw_imap_port=993,
        openclaw_imap_tls_mode="imaps",
        openclaw_imap_default_mailbox="INBOX",
        openclaw_imap_container_credentials_path="/tmp/imap_accounts.json",
        openclaw_imap_connect_timeout_seconds=8,
        openclaw_imap_command_timeout_seconds=12,
        openclaw_imap_default_limit=10,
        openclaw_imap_max_limit=25,
        openclaw_imap_header_max_chars=240,
        openclaw_imap_subject_max_chars=180,
        openclaw_imap_read_fetch_bytes=6000,
        openclaw_imap_read_snippet_chars=300,
        openclaw_imap_search_query_max_chars=200,
        openclaw_smtp_enabled=True,
        openclaw_smtp_host="mail.example.test",
        openclaw_smtp_port=465,
        openclaw_smtp_tls_mode="smtps",
        openclaw_smtp_container_credentials_path="/tmp/smtp_accounts.json",
        openclaw_smtp_connect_timeout_seconds=8,
        openclaw_smtp_command_timeout_seconds=12,
        openclaw_smtp_max_recipients=10,
        openclaw_smtp_address_max_chars=254,
        openclaw_smtp_from_name_max_chars=80,
        openclaw_smtp_subject_max_chars=180,
        openclaw_smtp_body_max_chars=2000,
    )
    if "{{" in rendered or "{%" in rendered:
        raise AssertionError("Unrendered Jinja2 markers remain in mail handler template.")

    module = types.ModuleType("openclaw_mail_handler")
    module.__dict__["__name__"] = "openclaw_mail_handler"
    exec(compile(rendered, str(HANDLER_TEMPLATE_PATH), "exec"), module.__dict__)
    return module


handler = _load_handler_module()


def test_normalize_mail_body_decodes_literal_newlines_and_strips_leading_dollar_artifact():
    raw = "$Hi Jochen, hi Katharina,\\n\\nzweiter Zustellversuch"
    normalized = handler._normalize_mail_body(raw)
    assert normalized.startswith("Hi Jochen, hi Katharina,")
    assert "\n\nzweiter Zustellversuch" in normalized
    assert "\\n" not in normalized
    assert not normalized.startswith("$")


def test_normalize_mail_body_decodes_shell_quoted_body():
    assert handler._normalize_mail_body("$'Line 1\\n\\nLine 2'") == "Line 1\n\nLine 2"


def test_normalize_mail_body_decodes_shell_double_quoted_body():
    assert handler._normalize_mail_body('$"Line 1\\nLine 2"') == "Line 1\nLine 2"


def test_normalize_mail_body_preserves_real_newlines():
    raw = "Line 1\n\nLine 2"
    assert handler._normalize_mail_body(raw) == raw


def test_normalize_mail_body_preserves_plain_wrapping_quotes():
    raw = '"Quoted body text."'
    assert handler._normalize_mail_body(raw) == raw


def test_normalize_mail_body_does_not_strip_currency_dollar():
    raw = "$100 discount\\nDetails below"
    assert handler._normalize_mail_body(raw) == "$100 discount\nDetails below"


def test_normalize_mail_body_keeps_double_dollar_prefix():
    raw = "$$formula\\nnext line"
    assert handler._normalize_mail_body(raw) == "$$formula\nnext line"


def test_normalize_mail_body_does_not_decode_escaped_tokens_when_real_newline_exists():
    raw = "Line 1\nLiteral token: \\n"
    assert handler._normalize_mail_body(raw) == raw


def test_normalize_mail_body_decodes_mixed_shell_artifact_with_real_newline():
    raw = "$Hi\\nLine 1\\nLine 2\\\nLine 3"
    assert handler._normalize_mail_body(raw) == "Hi\nLine 1\nLine 2\nLine 3"


def test_decode_mail_body_escapes_converts_common_tokens():
    assert handler._decode_mail_body_escapes("A\\r\\nB\\tC\\nD\\rE") == "A\nB\tC\nD\nE"


def test_decode_mail_body_escapes_keeps_double_backslash_sequences():
    raw = "\\\\n and \\\\t"
    assert handler._decode_mail_body_escapes(raw) == raw


def test_normalize_mail_body_keeps_leading_dollar_without_escape_tokens():
    raw = "$just text"
    assert handler._normalize_mail_body(raw) == raw


def test_normalize_mail_body_rejects_empty_body_after_unwrapping():
    with pytest.raises(handler.MailSkillError, match="Body cannot be empty."):
        handler._normalize_mail_body("$''")
