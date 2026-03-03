from __future__ import annotations

import json
import types
from pathlib import Path
from urllib.error import HTTPError

import pytest


HANDLER_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "roles"
    / "openclaw_deploy"
    / "templates"
    / "paperless-handler.py.j2"
)


def _load_handler_module():
    source = HANDLER_TEMPLATE_PATH.read_text(encoding="utf-8")
    source = source.replace(
        "{{ openclaw_paperless_container_credentials_path | to_json }}",
        json.dumps("/tmp/paperless.json"),
    )
    source = source.replace(
        "{{ openclaw_paperless_command_skill_name | to_json }}",
        json.dumps("paperless"),
    )
    if "{{" in source:
        start = source.index("{{")
        end = source.index("}}", start) + 2 if "}}" in source[start:] else start + 2
        snippet = source[start:end]
        raise AssertionError(f"Unreplaced Jinja2 variable in template: {snippet}")

    module = types.ModuleType("openclaw_paperless_handler")
    module.__dict__["__name__"] = "openclaw_paperless_handler"
    exec(compile(source, str(HANDLER_TEMPLATE_PATH), "exec"), module.__dict__)
    return module


handler = _load_handler_module()


TARGET_CONTEXT_ENV_KEYS = [
    "OPENCLAW_TOOL_CONTEXT",
    "OPENCLAW_CONTEXT",
    "TOOL_CONTEXT_JSON",
    "OPENCLAW_CHANNEL",
    "OPENCLAW_REQUEST_CHANNEL",
    "OPENCLAW_MESSAGE_CHANNEL",
]
TARGET_ID_ENV_KEYS = [
    "OPENCLAW_CHAT_ID",
    "TELEGRAM_CHAT_ID",
    "CHAT_ID",
    "ChatId",
    "OPENCLAW_REQUESTER_SENDER_ID",
    "OPENCLAW_SENDER_ID",
    "REQUESTER_SENDER_ID",
    "SENDER_ID",
    "SenderId",
]


def _base_config(tmp_path: Path) -> dict:
    return {
        "base_url": "https://paperless.example.test",
        "token": "test-token",
        "delivery_channel": "telegram",
        "search_timeout_seconds": 10,
        "download_timeout_seconds": 60,
        "delivery_timeout_seconds": 20,
        "default_limit": 5,
        "max_limit": 10,
        "latest_default_days": 7,
        "latest_max_days": 365,
        "title_max_chars": 120,
        "correspondent_max_chars": 80,
        "max_download_bytes": 1024,
        "download_chunk_bytes": 128,
        "downloads_dir": str(tmp_path / "downloads"),
        "session_state_path": str(tmp_path / "sessions.json"),
        "session_target_max_age_seconds": 180,
        "health_state_path": str(tmp_path / "paperless_health_state.json"),
        "auth_failure_window_seconds": 3600,
        "auth_failure_threshold": 3,
    }


@pytest.mark.parametrize(
    ("raw_limit", "expected"),
    [
        (None, 5),
        (0, 1),
        (-3, 1),
        (7, 7),
        (999, 10),
    ],
)
def test_bounded_limit_edges(raw_limit, expected):
    assert handler._bounded_limit(raw_limit, 5, 10) == expected


def test_parser_parses_search_arguments():
    parser = handler._build_parser()
    args = parser.parse_args(
        ["search", "aok", "letter", "--from", "2026-03-01", "--to", "2026-03-31", "--limit", "8"]
    )
    assert args.command == "search"
    assert args.query == ["aok", "letter"]
    assert args.from_date == "2026-03-01"
    assert args.to_date == "2026-03-31"
    assert args.limit == 8


def test_parser_parses_latest_arguments():
    parser = handler._build_parser()
    args = parser.parse_args(["latest", "--query", "invoice", "--days", "14", "--limit", "4"])
    assert args.command == "latest"
    assert args.query == "invoice"
    assert args.days == 14
    assert args.limit == 4


def test_parser_get_defaults_to_original_document():
    parser = handler._build_parser()
    args = parser.parse_args(["get", "42"])
    assert args.command == "get"
    assert args.document_id == "42"
    assert args.original is True


def test_parser_get_archived_overrides_original_default():
    parser = handler._build_parser()
    args = parser.parse_args(["get", "42", "--archived"])
    assert args.command == "get"
    assert args.document_id == "42"
    assert args.original is False


def test_handle_search_rejects_invalid_date_range(tmp_path):
    args = types.SimpleNamespace(
        query=["letter"],
        from_date="2026-03-10",
        to_date="2026-03-01",
        limit=5,
    )
    with pytest.raises(handler.PaperlessSkillError, match="Date range is invalid"):
        handler._handle_search(args, _base_config(tmp_path))


def test_search_metadata_row_format_is_deterministic(tmp_path):
    config = _base_config(tmp_path)
    row, meta = handler._format_document_row(
        config,
        {
            "id": 42,
            "title": "AOK Letter",
            "correspondent_name": "AOK",
            "created": "2026-02-28T09:12:13Z",
        },
    )
    assert row == "#42 | AOK Letter | AOK | 2026-02-28"
    assert meta["id"] == 42


def test_record_auth_result_persists_failure_and_success(tmp_path):
    config = _base_config(tmp_path)
    handler._record_auth_result(config, 401)
    state = json.loads(Path(config["health_state_path"]).read_text(encoding="utf-8"))
    assert state["last_status_code"] == 401
    assert len(state["auth_failure_epochs"]) == 1
    assert "last_failure_at" in state

    handler._record_auth_result(config, None)
    state = json.loads(Path(config["health_state_path"]).read_text(encoding="utf-8"))
    assert "last_success_at" in state


@pytest.mark.parametrize("status_code", [401, 403])
def test_request_maps_auth_failure_and_updates_health_state(tmp_path, monkeypatch, status_code):
    config = _base_config(tmp_path)

    class _FailingOpener:
        def open(self, request, timeout):
            raise HTTPError(request.full_url, status_code, "unauthorized", {}, None)

    monkeypatch.setattr(handler, "build_opener", lambda *_args, **_kwargs: _FailingOpener())

    with pytest.raises(handler.PaperlessSkillError, match="authentication failed"):
        handler._paperless_request(
            config=config,
            method="GET",
            path="/api/documents/",
            timeout_seconds=5,
            expect_json=True,
        )

    state = json.loads(Path(config["health_state_path"]).read_text(encoding="utf-8"))
    assert state["last_status_code"] == status_code
    assert len(state["auth_failure_epochs"]) == 1


def test_resolve_active_telegram_target_from_direct_env(monkeypatch):
    for key in TARGET_CONTEXT_ENV_KEYS + TARGET_ID_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENCLAW_CHAT_ID", "304012876")
    assert handler._resolve_active_telegram_target() == "304012876"


def test_resolve_active_telegram_target_from_generic_sender_id(monkeypatch):
    for key in TARGET_CONTEXT_ENV_KEYS + TARGET_ID_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SENDER_ID", "304012876")
    assert handler._resolve_active_telegram_target() == "304012876"


def test_resolve_active_telegram_target_from_context_json(monkeypatch):
    for key in TARGET_CONTEXT_ENV_KEYS + TARGET_ID_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(
        "OPENCLAW_CONTEXT",
        json.dumps({"channel": "telegram", "chatId": "304012876"}),
    )
    assert handler._resolve_active_telegram_target() == "304012876"


def test_resolve_active_telegram_target_returns_none_for_non_telegram_context(monkeypatch):
    for key in TARGET_CONTEXT_ENV_KEYS + TARGET_ID_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENCLAW_CONTEXT", json.dumps({"channel": "discord", "chatId": "304012876"}))
    assert handler._resolve_active_telegram_target() is None


def test_resolve_active_telegram_target_non_telegram_context_blocks_direct_env(monkeypatch):
    for key in TARGET_CONTEXT_ENV_KEYS + TARGET_ID_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENCLAW_CONTEXT", json.dumps({"channel": "discord", "chatId": "555"}))
    monkeypatch.setenv("OPENCLAW_CHAT_ID", "304012876")
    assert handler._resolve_active_telegram_target() is None


def test_resolve_active_telegram_target_non_telegram_channel_env_blocks_direct_env(monkeypatch):
    for key in TARGET_CONTEXT_ENV_KEYS + TARGET_ID_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENCLAW_CHANNEL", "discord")
    monkeypatch.setenv("OPENCLAW_CHAT_ID", "304012876")
    assert handler._resolve_active_telegram_target() is None


def test_resolve_active_telegram_target_returns_none_when_missing(monkeypatch):
    for key in TARGET_CONTEXT_ENV_KEYS + TARGET_ID_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    assert handler._resolve_active_telegram_target() is None


def test_resolve_active_telegram_target_from_recent_unique_slash_session(tmp_path, monkeypatch):
    for key in TARGET_CONTEXT_ENV_KEYS + TARGET_ID_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    config = _base_config(tmp_path)
    now_ms = int(handler.datetime.now(tz=handler.timezone.utc).timestamp() * 1000)
    sessions = {
        "telegram:slash:304012876": {
            "updatedAt": now_ms,
            "origin": {"provider": "telegram", "to": "telegram:304012876"},
        }
    }
    Path(config["session_state_path"]).write_text(json.dumps(sessions), encoding="utf-8")

    assert handler._resolve_active_telegram_target(config=config) == "304012876"


def test_resolve_active_telegram_target_returns_none_for_ambiguous_recent_slash_sessions(
    tmp_path, monkeypatch
):
    for key in TARGET_CONTEXT_ENV_KEYS + TARGET_ID_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    config = _base_config(tmp_path)
    now_ms = int(handler.datetime.now(tz=handler.timezone.utc).timestamp() * 1000)
    sessions = {
        "telegram:slash:304012876": {"updatedAt": now_ms},
        "telegram:slash:999999999": {"updatedAt": now_ms},
    }
    Path(config["session_state_path"]).write_text(json.dumps(sessions), encoding="utf-8")

    assert handler._resolve_active_telegram_target(config=config) is None


def test_resolve_active_telegram_target_ignores_stale_slash_sessions(tmp_path, monkeypatch):
    for key in TARGET_CONTEXT_ENV_KEYS + TARGET_ID_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    config = _base_config(tmp_path)
    now_ms = int(handler.datetime.now(tz=handler.timezone.utc).timestamp() * 1000)
    stale_ms = now_ms - ((config["session_target_max_age_seconds"] + 30) * 1000)
    sessions = {
        "telegram:slash:304012876": {"updatedAt": stale_ms},
    }
    Path(config["session_state_path"]).write_text(json.dumps(sessions), encoding="utf-8")

    assert handler._resolve_active_telegram_target(config=config) is None


def test_resolve_active_telegram_target_from_recent_unique_delivery_context(
    tmp_path, monkeypatch
):
    for key in TARGET_CONTEXT_ENV_KEYS + TARGET_ID_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    config = _base_config(tmp_path)
    now_ms = int(handler.datetime.now(tz=handler.timezone.utc).timestamp() * 1000)
    sessions = {
        "agent:main:telegram:direct:304012876": {
            "updatedAt": now_ms,
            "origin": {"provider": "telegram", "to": "telegram:304012876"},
            "deliveryContext": {"channel": "telegram", "to": "telegram:304012876"},
        }
    }
    Path(config["session_state_path"]).write_text(json.dumps(sessions), encoding="utf-8")

    assert handler._resolve_active_telegram_target(config=config) == "304012876"


def test_resolve_active_telegram_target_prefers_unique_slash_over_ambiguous_route_entry(
    tmp_path, monkeypatch
):
    for key in TARGET_CONTEXT_ENV_KEYS + TARGET_ID_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    config = _base_config(tmp_path)
    now_ms = int(handler.datetime.now(tz=handler.timezone.utc).timestamp() * 1000)
    sessions = {
        "telegram:slash:304012876": {
            "updatedAt": now_ms,
            "origin": {"provider": "telegram", "to": "telegram:304012876"},
        },
        "agent:main:telegram:direct:304012876": {
            "updatedAt": now_ms,
            "origin": {"provider": "telegram", "from": "telegram:111111", "to": "telegram:222222"},
            "deliveryContext": {"channel": "telegram", "to": "telegram:304012876"},
        },
    }
    Path(config["session_state_path"]).write_text(json.dumps(sessions), encoding="utf-8")

    assert handler._resolve_active_telegram_target(config=config) == "304012876"


def test_resolve_active_telegram_target_returns_none_for_ambiguous_route_entry_without_slash(
    tmp_path, monkeypatch
):
    for key in TARGET_CONTEXT_ENV_KEYS + TARGET_ID_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    config = _base_config(tmp_path)
    now_ms = int(handler.datetime.now(tz=handler.timezone.utc).timestamp() * 1000)
    sessions = {
        "agent:main:telegram:direct:304012876": {
            "updatedAt": now_ms,
            "origin": {"provider": "telegram", "from": "telegram:111111", "to": "telegram:222222"},
            "deliveryContext": {"channel": "telegram", "to": "telegram:304012876"},
        },
    }
    Path(config["session_state_path"]).write_text(json.dumps(sessions), encoding="utf-8")

    assert handler._resolve_active_telegram_target(config=config) is None


def test_download_precheck_content_length_over_limit(tmp_path, monkeypatch):
    config = _base_config(tmp_path)
    config["max_download_bytes"] = 100

    class _Resp:
        status = 200
        headers = {"Content-Length": "200"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _size):
            raise AssertionError("read should not be called when Content-Length is over cap")

        def getcode(self):
            return 200

    class _Opener:
        def open(self, _request, timeout):
            return _Resp()

    monkeypatch.setattr(handler, "build_opener", lambda *_args, **_kwargs: _Opener())

    with pytest.raises(handler.DocumentTooLargeError) as err:
        handler._download_document_with_cap(config=config, document_id=7, original=False)
    assert err.value.streamed is False


def test_download_stream_without_content_length_hard_caps(tmp_path, monkeypatch):
    config = _base_config(tmp_path)
    config["max_download_bytes"] = 100
    config["download_chunk_bytes"] = 64

    class _Resp:
        status = 200
        headers = {}

        def __init__(self):
            self._chunks = [b"a" * 70, b"b" * 70, b""]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _size):
            return self._chunks.pop(0)

        def getcode(self):
            return 200

    class _Opener:
        def open(self, _request, timeout):
            return _Resp()

    monkeypatch.setattr(handler, "build_opener", lambda *_args, **_kwargs: _Opener())

    with pytest.raises(handler.DocumentTooLargeError) as err:
        handler._download_document_with_cap(config=config, document_id=8, original=False)
    assert err.value.streamed is True


def test_download_http_error_during_stream_cleans_partial_file(tmp_path, monkeypatch):
    config = _base_config(tmp_path)
    config["max_download_bytes"] = 1024
    config["download_chunk_bytes"] = 64

    class _Resp:
        status = 200
        headers = {}

        def __init__(self):
            self._calls = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _size):
            self._calls += 1
            if self._calls == 1:
                return b"a" * 32
            raise HTTPError("https://paperless.example.test/download", 500, "error", {}, None)

        def getcode(self):
            return 200

    class _Opener:
        def open(self, _request, timeout):
            return _Resp()

    monkeypatch.setattr(handler, "build_opener", lambda *_args, **_kwargs: _Opener())

    with pytest.raises(handler.PaperlessSkillError, match="download failed \\(HTTP 500\\)"):
        handler._download_document_with_cap(config=config, document_id=9, original=False)

    leftovers = list(Path(config["downloads_dir"]).glob("paperless-9-*.bin"))
    assert leftovers == []


def test_download_extension_prefers_content_disposition_filename():
    ext = handler._download_extension_from_headers(
        {
            "Content-Disposition": 'attachment; filename="scan.pdf"',
            "Content-Type": "image/tiff",
        }
    )
    assert ext == ".pdf"


def test_download_extension_falls_back_to_content_type():
    ext = handler._download_extension_from_headers({"Content-Type": "image/png; charset=utf-8"})
    assert ext == ".png"


@pytest.mark.parametrize("status_code", [401, 403])
def test_download_auth_failure_during_stream_records_state_and_cleans_partial_file(
    tmp_path, monkeypatch, status_code
):
    config = _base_config(tmp_path)
    config["max_download_bytes"] = 1024
    config["download_chunk_bytes"] = 64

    class _Resp:
        status = 200
        headers = {}

        def __init__(self):
            self._calls = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _size):
            self._calls += 1
            if self._calls == 1:
                return b"a" * 32
            raise HTTPError("https://paperless.example.test/download", status_code, "auth", {}, None)

        def getcode(self):
            return 200

    class _Opener:
        def open(self, _request, timeout):
            return _Resp()

    monkeypatch.setattr(handler, "build_opener", lambda *_args, **_kwargs: _Opener())

    with pytest.raises(handler.PaperlessSkillError, match="Paperless authentication failed."):
        handler._download_document_with_cap(config=config, document_id=99, original=False)

    leftovers = list(Path(config["downloads_dir"]).glob("paperless-99-*.bin"))
    assert leftovers == []
    state = json.loads(Path(config["health_state_path"]).read_text(encoding="utf-8"))
    assert state["last_status_code"] == status_code
    assert len(state["auth_failure_epochs"]) == 1


def test_handle_get_falls_back_when_active_chat_target_missing(tmp_path, monkeypatch):
    config = _base_config(tmp_path)
    downloaded = tmp_path / "downloaded.bin"
    downloaded.write_bytes(b"hello")

    monkeypatch.setattr(
        handler,
        "_paperless_request",
        lambda **_kwargs: (
            {
                "id": 10,
                "title": "Notice",
                "correspondent_name": "AOK",
                "created": "2026-03-01T08:00:00Z",
            },
            {},
        ),
    )
    monkeypatch.setattr(
        handler,
        "_download_document_with_cap",
        lambda **_kwargs: (downloaded, 5),
    )
    monkeypatch.setattr(handler, "_resolve_active_telegram_target", lambda **_kwargs: None)

    args = types.SimpleNamespace(document_id="10", original=False)
    output = handler._handle_get(args, config)

    assert "Delivery: unavailable (active Telegram chat context missing)." in output
    assert "Paperless URL: https://paperless.example.test/documents/10/details" in output
    assert not downloaded.exists()


def test_handle_get_falls_back_when_send_fails(tmp_path, monkeypatch):
    config = _base_config(tmp_path)
    downloaded = tmp_path / "downloaded.bin"
    downloaded.write_bytes(b"hello")

    monkeypatch.setattr(
        handler,
        "_paperless_request",
        lambda **_kwargs: (
            {
                "id": 11,
                "title": "Invoice",
                "correspondent_name": "Utility",
                "created": "2026-03-01T08:00:00Z",
            },
            {},
        ),
    )
    monkeypatch.setattr(
        handler,
        "_download_document_with_cap",
        lambda **_kwargs: (downloaded, 5),
    )
    monkeypatch.setattr(handler, "_resolve_active_telegram_target", lambda **_kwargs: "304012876")
    monkeypatch.setattr(
        handler,
        "_send_telegram_media",
        lambda **_kwargs: (_ for _ in ()).throw(handler.PaperlessSkillError("boom")),
    )

    args = types.SimpleNamespace(document_id="11", original=False)
    output = handler._handle_get(args, config)

    assert "Delivery: unavailable (Telegram send failed)." in output
    assert "Paperless URL: https://paperless.example.test/documents/11/details" in output
    assert not downloaded.exists()


def test_handle_get_large_file_deterministic_fallback(tmp_path, monkeypatch):
    config = _base_config(tmp_path)
    config["max_download_bytes"] = 52428800

    monkeypatch.setattr(
        handler,
        "_paperless_request",
        lambda **_kwargs: (
            {
                "id": 12,
                "title": "Huge Scan",
                "correspondent_name": "Archive",
                "created": "2026-03-01T08:00:00Z",
            },
            {},
        ),
    )
    monkeypatch.setattr(
        handler,
        "_download_document_with_cap",
        lambda **_kwargs: (_ for _ in ()).throw(
            handler.DocumentTooLargeError(
                limit_bytes=52428800, content_length=60000000, streamed=False
            )
        ),
    )

    args = types.SimpleNamespace(document_id="12", original=False)
    output = handler._handle_get(args, config)
    assert "Delivery: skipped (file exceeds Telegram upload limit of 50 MB)." in output


def test_handle_get_success_output_is_deterministic(tmp_path, monkeypatch):
    config = _base_config(tmp_path)
    downloaded = tmp_path / "downloaded.bin"
    downloaded.write_bytes(b"hello")

    monkeypatch.setattr(
        handler,
        "_paperless_request",
        lambda **_kwargs: (
            {
                "id": 13,
                "title": "Letter",
                "correspondent_name": "AOK",
                "created": "2026-03-01T08:00:00Z",
            },
            {},
        ),
    )
    monkeypatch.setattr(
        handler,
        "_download_document_with_cap",
        lambda **_kwargs: (downloaded, 5),
    )
    monkeypatch.setattr(handler, "_resolve_active_telegram_target", lambda **_kwargs: "304012876")
    monkeypatch.setattr(handler, "_send_telegram_media", lambda **_kwargs: "777")

    args = types.SimpleNamespace(document_id="13", original=True)
    output = handler._handle_get(args, config)

    assert "Document: #13 | Letter | AOK | 2026-03-01" in output
    assert "Delivery: sent to Telegram chat 304012876 (message_id=777)." in output
    assert "Paperless URL: https://paperless.example.test/documents/13/details" in output
    assert not downloaded.exists()
