from __future__ import annotations

import json
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


HANDLER_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "roles"
    / "openclaw_deploy"
    / "templates"
    / "calendar-handler.py.j2"
)


def _load_handler_module():
    source = HANDLER_TEMPLATE_PATH.read_text(encoding="utf-8")
    source = source.replace(
        "{{ openclaw_calendar_container_credentials_path | to_json }}",
        json.dumps("/tmp/calendar_accounts.json"),
    )
    source = source.replace(
        "{{ openclaw_calendar_command_skill_name | to_json }}",
        json.dumps("calendar"),
    )
    if "{{" in source:
        start = source.index("{{")
        end = source.index("}}", start) + 2 if "}}" in source[start:] else start + 2
        snippet = source[start:end]
        raise AssertionError(f"Unreplaced Jinja2 variable in template: {snippet}")

    module = types.ModuleType("openclaw_calendar_handler")
    module.__dict__["__name__"] = "openclaw_calendar_handler"
    exec(compile(source, str(HANDLER_TEMPLATE_PATH), "exec"), module.__dict__)
    return module


handler = _load_handler_module()


def _write_config(tmp_path: Path, *, calendar_id: str = "family", writable: bool = True) -> Path:
    path = tmp_path / "calendar_accounts.json"
    path.write_text(
        json.dumps(
            {
                "timezone": "Europe/Berlin",
                "default_duration_minutes": 60,
                "request_timeout_seconds": 10,
                "default_limit": 10,
                "max_limit": 25,
                "title_max_chars": 180,
                "location_max_chars": 140,
                "calendars": {
                    calendar_id: {
                        "display_name": "Family",
                        "url": "https://caldav.example.test/family",
                        "username": "family@example.com",
                        "password": "secret",
                        "read": True,
                        "write": writable,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _base_config():
    return {
        "timezone": "Europe/Berlin",
        "default_duration_minutes": 60,
        "request_timeout_seconds": 10,
        "default_limit": 10,
        "max_limit": 25,
        "title_max_chars": 180,
        "location_max_chars": 140,
        "calendars": {
            "family": {
                "id": "family",
                "display_name": "Family",
                "url": "https://caldav.example.test/family",
                "username": "family@example.com",
                "password": "secret",
                "read": True,
                "write": True,
            }
        },
    }


def test_parse_user_datetime_accepts_iso_without_timezone():
    parsed = handler._parse_user_datetime("2026-03-02T14:30", "Europe/Berlin")
    assert parsed.tzinfo is not None
    assert parsed.year == 2026
    assert parsed.month == 3
    assert parsed.day == 2
    assert parsed.hour == 14
    assert parsed.minute == 30


def test_parse_user_datetime_rejects_invalid_text():
    with pytest.raises(handler.CalendarSkillError, match="Datetime must be ISO-like"):
        handler._parse_user_datetime("tomorrow afternoon", "Europe/Berlin")


def test_parse_user_datetime_dst_spring_forward_is_stable():
    parsed = handler._parse_user_datetime("2026-03-29T02:30", "Europe/Berlin")
    assert parsed.tzinfo is not None
    assert parsed.year == 2026
    assert parsed.month == 3
    assert parsed.day == 29
    assert parsed.hour == 2
    assert parsed.minute == 30


def test_parse_ical_datetime_value_date_branch():
    parsed, all_day = handler._parse_ical_datetime(
        "20260302",
        {"VALUE": "DATE"},
        "Europe/Berlin",
    )
    assert all_day is True
    assert parsed.year == 2026
    assert parsed.month == 3
    assert parsed.day == 2
    assert parsed.hour == 0
    assert parsed.minute == 0


def test_parse_ical_datetime_utc_z_branch():
    parsed, all_day = handler._parse_ical_datetime("20260302T130000Z", {}, "Europe/Berlin")
    assert all_day is False
    assert parsed.tzinfo is not None
    assert parsed.hour == 14  # UTC+1 in March before DST switch


def test_parse_ical_datetime_invalid_tzid_falls_back_to_default():
    parsed, all_day = handler._parse_ical_datetime(
        "20260302T130000",
        {"TZID": "Invalid/Timezone"},
        "Europe/Berlin",
    )
    assert all_day is False
    assert parsed.tzinfo is not None
    assert parsed.hour == 13


@pytest.mark.parametrize(
    ("raw_limit", "expected"),
    [
        (None, 10),
        (0, 1),
        (-4, 1),
        (12, 12),
        (999, 25),
    ],
)
def test_bounded_limit_edges(raw_limit, expected):
    assert handler._bounded_limit(raw_limit, 10, 25) == expected


def test_build_rrule_with_count():
    rrule = handler._build_rrule(
        repeat="weekly",
        count=5,
        until=None,
        timezone_name="Europe/Berlin",
    )
    assert rrule == "FREQ=WEEKLY;COUNT=5"


def test_build_rrule_rejects_count_and_until_together():
    with pytest.raises(handler.CalendarSkillError, match="either --count or --until"):
        handler._build_rrule(
            repeat="daily",
            count=2,
            until="2026-03-10",
            timezone_name="Europe/Berlin",
        )


def test_parse_ical_duration_supported_and_invalid_values():
    assert handler._parse_ical_duration("PT90M") == timedelta(minutes=90)
    assert handler._parse_ical_duration("P2DT3H") == timedelta(days=2, hours=3)
    assert handler._parse_ical_duration("-PT15M") is None
    assert handler._parse_ical_duration("NOT_A_DURATION") is None


def test_build_calendar_query_xml_uses_calendar_data_expand():
    start = datetime(2026, 3, 2, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 3, 9, 0, 0, tzinfo=timezone.utc)
    xml = handler._build_calendar_query_xml(start, end).decode("utf-8")
    assert "<c:calendar-data><c:expand " in xml
    assert "<c:calendar-data/>" not in xml
    assert 'time-range start="' in xml
    assert ' end="' in xml


def test_load_config_rejects_invalid_calendar_id(tmp_path):
    path = _write_config(tmp_path, calendar_id="Family!")
    with pytest.raises(handler.CalendarSkillError, match="Calendar IDs must match"):
        handler._load_config(str(path))


def test_normalize_url_rejects_query_and_fragment():
    with pytest.raises(handler.CalendarSkillError, match="URL is invalid"):
        handler._normalize_url("https://caldav.example.test/path?token=x")
    with pytest.raises(handler.CalendarSkillError, match="URL is invalid"):
        handler._normalize_url("https://caldav.example.test/path#frag")


def test_sanitize_text_truncates_and_normalizes_whitespace():
    assert handler._sanitize_text("  hello   world  ", 20) == "hello world"
    assert handler._sanitize_text("x" * 20, 10).endswith("...")


def test_escape_ical_text_escapes_special_characters():
    text = "Hello, world; line1\nline2 \\ test"
    escaped = handler._escape_ical_text(text)
    assert r"\," in escaped
    assert r"\;" in escaped
    assert r"\n" in escaped
    assert r"\\" in escaped


def test_fold_ical_line_wraps_at_octet_limit():
    folded = handler._fold_ical_line("SUMMARY:" + ("x" * 220), max_octets=75)
    parts = folded.split("\r\n")
    assert len(parts) >= 3
    assert all(len(part.encode("utf-8")) <= 75 for part in parts)
    assert all(part.startswith(" ") for part in parts[1:])


def test_fold_ical_line_wraps_utf8_multibyte_at_octet_limit():
    folded = handler._fold_ical_line("SUMMARY:" + ("ä" * 120), max_octets=75)
    parts = folded.split("\r\n")
    assert len(parts) >= 3
    assert all(len(part.encode("utf-8")) <= 75 for part in parts)
    assert all(part.startswith(" ") for part in parts[1:])


def test_events_overlap_boundary_conditions():
    start = datetime(2026, 3, 2, 14, 0, tzinfo=timezone.utc)
    end = datetime(2026, 3, 2, 15, 0, tzinfo=timezone.utc)
    assert handler._events_overlap(start, end, start, end)
    assert not handler._events_overlap(start, end, end, end + timedelta(minutes=30))
    assert not handler._events_overlap(start, end, start - timedelta(minutes=30), start)


def test_extract_events_from_ical_happy_path_with_duration_and_all_day():
    ical = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:event-1\r\n"
        "DTSTART:20260302T140000Z\r\n"
        "DURATION:PT45M\r\n"
        "SUMMARY:Call\r\n"
        "LOCATION:Office\r\n"
        "END:VEVENT\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:event-2\r\n"
        "DTSTART;VALUE=DATE:20260303\r\n"
        "DTEND;VALUE=DATE:20260305\r\n"
        "SUMMARY:Trip\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    events = handler._extract_events_from_ical(
        ical_text=ical,
        calendar_id="family",
        display_name="Family",
        resource_href="/dav/cal/family/event-1.ics",
        timezone_name="Europe/Berlin",
        title_max_chars=180,
        location_max_chars=140,
    )
    assert len(events) == 2
    timed = [event for event in events if event["uid"] == "event-1"][0]
    all_day = [event for event in events if event["uid"] == "event-2"][0]
    assert timed["summary"] == "Call"
    assert timed["location"] == "Office"
    assert timed["end"] - timed["start"] == timedelta(minutes=45)
    assert all_day["all_day"] is True
    assert (all_day["end"] - all_day["start"]).days == 2


def test_extract_events_from_ical_skips_event_without_dtstart():
    ical = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:event-1\r\n"
        "SUMMARY:No start\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    events = handler._extract_events_from_ical(
        ical_text=ical,
        calendar_id="family",
        display_name="Family",
        resource_href="/dav/cal/family/event-1.ics",
        timezone_name="Europe/Berlin",
        title_max_chars=180,
        location_max_chars=140,
    )
    assert events == []


def test_fetch_calendar_events_rejects_invalid_xml(monkeypatch):
    calendar = {
        "id": "family",
        "display_name": "Family",
        "url": "https://caldav.example.test/family",
        "username": "family@example.com",
        "password": "secret",
        "read": True,
        "write": False,
    }

    monkeypatch.setattr(
        handler,
        "_caldav_request",
        lambda **kwargs: (207, b"<d:multistatus>broken"),
    )

    with pytest.raises(handler.CalendarSkillError, match="not valid XML"):
        handler._fetch_calendar_events(
            calendar=calendar,
            range_start=datetime(2026, 3, 2, 0, 0, tzinfo=timezone.utc),
            range_end=datetime(2026, 3, 3, 0, 0, tzinfo=timezone.utc),
            timeout_seconds=10,
            timezone_name="Europe/Berlin",
            title_max_chars=180,
            location_max_chars=140,
        )


def test_collect_events_returns_partial_results_with_warning(monkeypatch):
    config = _base_config()
    config["calendars"]["jochen"] = {
        "id": "jochen",
        "display_name": "Jochen",
        "url": "https://caldav.example.test/jochen",
        "username": "jochen@example.com",
        "password": "secret",
        "read": True,
        "write": False,
    }

    start = datetime(2026, 3, 2, 14, 0, tzinfo=timezone.utc)
    end = datetime(2026, 3, 2, 15, 0, tzinfo=timezone.utc)

    def _fake_fetch(**kwargs):
        calendar = kwargs["calendar"]
        if calendar["id"] == "jochen":
            raise handler.CalendarSkillError("boom")
        return [
            {
                "uid": "event-1",
                "summary": "Family time",
                "location": "",
                "start": start,
                "end": end,
                "all_day": False,
                "calendar_id": "family",
                "calendar_display_name": "Family",
            }
        ]

    monkeypatch.setattr(handler, "_fetch_calendar_events", _fake_fetch)
    events, warnings = handler._collect_events(
        config=config,
        range_start=start,
        range_end=end,
    )
    assert len(events) == 1
    assert len(warnings) == 1
    assert "Jochen" in warnings[0]


def test_create_event_denies_non_writable_calendar(tmp_path):
    config_path = _write_config(tmp_path, writable=False)
    config = handler._load_config(str(config_path))
    with pytest.raises(handler.CalendarAccessDenied, match="Write access denied"):
        handler._create_event(
            config=config,
            calendar_id="family",
            title="Test",
            start="2026-03-02T16:00",
            duration=60,
            repeat=None,
            count=None,
            until=None,
        )


def test_create_event_happy_path(monkeypatch, tmp_path):
    config_path = _write_config(tmp_path, writable=True)
    config = handler._load_config(str(config_path))

    calls = []

    def _fake_request(**kwargs):
        calls.append(kwargs)
        return 201, b""

    monkeypatch.setattr(handler, "_caldav_request", _fake_request)
    monkeypatch.setattr(handler.uuid, "uuid4", lambda: "00000000-0000-0000-0000-000000000001")

    output = handler._create_event(
        config=config,
        calendar_id="family",
        title="Family planning",
        start="2026-03-02T16:00",
        duration=60,
        repeat="monthly",
        count=3,
        until=None,
    )

    assert len(calls) == 1
    assert calls[0]["method"] == "PUT"
    assert calls[0]["operation"] == "create for calendar 'family'"
    assert b"DTSTART:" in calls[0]["body"]
    assert b"DTSTART;TZID=" not in calls[0]["body"]
    assert "Status: created" in output
    assert "Calendar: Family (family)" in output
    assert "Event ID: family:" in output
    assert "Recurrence: FREQ=MONTHLY;COUNT=3" in output


def test_main_today_command_renders_listing(monkeypatch, capsys):
    config = _base_config()
    event = {
        "uid": "event-1",
        "summary": "Family",
        "location": "",
        "start": datetime(2026, 3, 2, 14, 0, tzinfo=timezone.utc),
        "end": datetime(2026, 3, 2, 15, 0, tzinfo=timezone.utc),
        "all_day": False,
        "calendar_id": "family",
        "calendar_display_name": "Family",
    }
    monkeypatch.setattr(handler, "_load_config", lambda _path: config)
    monkeypatch.setattr(handler, "_collect_events", lambda **kwargs: ([event], ["Warning: demo"]))
    monkeypatch.setattr(handler.sys, "argv", ["calendar-handler.py", "today"])

    result = handler.main()
    output = capsys.readouterr().out
    assert result == 0
    assert "Calendar for" in output
    assert "Warning: demo" in output


def test_main_on_command_works(monkeypatch, capsys):
    config = _base_config()
    monkeypatch.setattr(handler, "_load_config", lambda _path: config)
    monkeypatch.setattr(handler, "_collect_events", lambda **kwargs: ([], []))
    monkeypatch.setattr(handler.sys, "argv", ["calendar-handler.py", "on", "2026-03-02"])

    result = handler.main()
    output = capsys.readouterr().out
    assert result == 0
    assert "Calendar for 2026-03-02" in output


def test_main_tomorrow_command_works(monkeypatch, capsys):
    config = _base_config()

    class _FakeDateTime:
        @staticmethod
        def now(tz=None):
            return datetime(2026, 3, 1, 12, 0, tzinfo=tz)

    monkeypatch.setattr(handler, "_load_config", lambda _path: config)
    monkeypatch.setattr(
        handler,
        "_render_day_listing",
        lambda **kwargs: f"Calendar for {kwargs['selected_day'].isoformat()}",
    )
    monkeypatch.setattr(handler, "datetime", _FakeDateTime)
    monkeypatch.setattr(handler.sys, "argv", ["calendar-handler.py", "tomorrow"])

    result = handler.main()
    output = capsys.readouterr().out
    assert result == 0
    assert "Calendar for 2026-03-02" in output


def test_main_week_command_with_explicit_start_works(monkeypatch, capsys):
    config = _base_config()
    monkeypatch.setattr(handler, "_load_config", lambda _path: config)
    monkeypatch.setattr(handler, "_collect_events", lambda **kwargs: ([], []))
    monkeypatch.setattr(
        handler.sys,
        "argv",
        ["calendar-handler.py", "week", "--start", "2026-03-02"],
    )

    result = handler.main()
    output = capsys.readouterr().out
    assert result == 0
    assert "Calendar week 2026-03-02 -> 2026-03-08" in output


def test_main_week_command_defaults_to_current_week_monday(monkeypatch, capsys):
    config = _base_config()

    class _FakeDateTime:
        @staticmethod
        def now(tz=None):
            return datetime(2026, 3, 4, 12, 0, tzinfo=tz)

        @staticmethod
        def combine(day_value, time_value, tzinfo=None):
            return datetime.combine(day_value, time_value, tzinfo=tzinfo)

    monkeypatch.setattr(handler, "_load_config", lambda _path: config)
    monkeypatch.setattr(handler, "_collect_events", lambda **kwargs: ([], []))
    monkeypatch.setattr(handler, "datetime", _FakeDateTime)
    monkeypatch.setattr(handler.sys, "argv", ["calendar-handler.py", "week"])

    result = handler.main()
    output = capsys.readouterr().out
    assert result == 0
    assert "Calendar week 2026-03-02 -> 2026-03-08" in output


def test_main_free_command_busy(monkeypatch, capsys):
    config = _base_config()
    start = datetime(2026, 3, 2, 14, 0, tzinfo=timezone.utc)
    event = {
        "uid": "event-1",
        "summary": "Conflict",
        "location": "",
        "start": start,
        "end": start + timedelta(minutes=90),
        "all_day": False,
        "calendar_id": "family",
        "calendar_display_name": "Family",
    }

    monkeypatch.setattr(handler, "_load_config", lambda _path: config)
    monkeypatch.setattr(handler, "_collect_events", lambda **kwargs: ([event], []))
    monkeypatch.setattr(
        handler.sys,
        "argv",
        ["calendar-handler.py", "free", "--at", "2026-03-02T15:00", "--duration", "60"],
    )

    result = handler.main()
    output = capsys.readouterr().out
    assert result == 0
    assert "Status: busy" in output
    assert "Conflicts: 1" in output


def test_main_free_command_free(monkeypatch, capsys):
    config = _base_config()
    monkeypatch.setattr(handler, "_load_config", lambda _path: config)
    monkeypatch.setattr(handler, "_collect_events", lambda **kwargs: ([], []))
    monkeypatch.setattr(
        handler.sys,
        "argv",
        ["calendar-handler.py", "free", "--at", "2026-03-02T15:00", "--duration", "60"],
    )

    result = handler.main()
    output = capsys.readouterr().out
    assert result == 0
    assert "Status: free" in output


def test_main_create_command_calls_create(monkeypatch, capsys):
    config = _base_config()
    monkeypatch.setattr(handler, "_load_config", lambda _path: config)
    monkeypatch.setattr(handler, "_create_event", lambda **kwargs: "Status: created")
    monkeypatch.setattr(
        handler.sys,
        "argv",
        [
            "calendar-handler.py",
            "create",
            "--calendar",
            "family",
            "--title",
            "Test",
            "--start",
            "2026-03-02T16:00",
        ],
    )

    result = handler.main()
    output = capsys.readouterr().out
    assert result == 0
    assert "Status: created" in output


def test_event_id_round_trip():
    event_id = handler._build_event_id("family", "/dav/cal/family/event-1.ics")
    calendar_id, href = handler._parse_event_id(event_id)
    assert calendar_id == "family"
    assert href == "/dav/cal/family/event-1.ics"


def test_parse_event_id_rejects_malformed():
    with pytest.raises(handler.CalendarSkillError, match="Event ID must match"):
        handler._parse_event_id("missing-delimiter")


def test_decode_event_token_rejects_invalid_base64():
    with pytest.raises(handler.CalendarSkillError, match="Event ID is invalid"):
        handler._decode_event_token("%%%")


def test_build_event_id_rejects_null_byte_href():
    with pytest.raises(handler.CalendarSkillError, match="Event ID is invalid"):
        handler._build_event_id("family", "/family/event-\x00.ics")


def test_normalize_event_href_extracts_path_from_absolute_url():
    assert (
        handler._normalize_event_href("https://caldav.example.test/family/event-1.ics")
        == "/family/event-1.ics"
    )


def test_resolve_event_url_rejects_path_escape():
    with pytest.raises(handler.CalendarAccessDenied, match="does not belong"):
        handler._resolve_event_url(
            "https://caldav.example.test/family",
            "/other/cal/event-1.ics",
        )


def test_resolve_event_url_rejects_path_traversal():
    with pytest.raises(handler.CalendarAccessDenied, match="does not belong"):
        handler._resolve_event_url(
            "https://caldav.example.test/family",
            "/family/../other/event-1.ics",
        )


def test_resolve_event_url_rejects_scheme_netloc_in_event_href():
    with pytest.raises(handler.CalendarSkillError, match="Event ID is invalid"):
        handler._resolve_event_url(
            "https://caldav.example.test/family",
            "https://evil.example.test/family/event-1.ics",
        )


def test_delete_event_requires_confirm(tmp_path):
    config_path = _write_config(tmp_path, writable=True)
    config = handler._load_config(str(config_path))
    event_id = handler._build_event_id("family", "/family/event-1.ics")
    with pytest.raises(handler.CalendarSkillError, match="Delete requires --confirm"):
        handler._delete_event(config=config, event_id=event_id, confirm=False)


def test_delete_event_denies_non_writable_calendar_without_request(monkeypatch, tmp_path):
    config_path = _write_config(tmp_path, writable=False)
    config = handler._load_config(str(config_path))
    event_id = handler._build_event_id("family", "/family/event-1.ics")

    called = []

    def _fake_request(**kwargs):
        called.append(kwargs)
        return 204, b""

    monkeypatch.setattr(handler, "_caldav_request", _fake_request)
    with pytest.raises(handler.CalendarAccessDenied, match="Write access denied"):
        handler._delete_event(config=config, event_id=event_id, confirm=True)
    assert called == []


def test_delete_event_happy_path(monkeypatch, tmp_path):
    config_path = _write_config(tmp_path, writable=True)
    config = handler._load_config(str(config_path))
    event_id = handler._build_event_id("family", "/family/event-1.ics")

    calls = []

    def _fake_request(**kwargs):
        calls.append(kwargs)
        return 204, b""

    monkeypatch.setattr(handler, "_caldav_request", _fake_request)
    output = handler._delete_event(config=config, event_id=event_id, confirm=True)
    assert len(calls) == 1
    assert calls[0]["method"] == "DELETE"
    assert "Status: deleted" in output
    assert "Event ID: family:" in output


def test_delete_event_missing_event(monkeypatch, tmp_path):
    config_path = _write_config(tmp_path, writable=True)
    config = handler._load_config(str(config_path))
    event_id = handler._build_event_id("family", "/family/missing.ics")

    def _fake_request(**kwargs):
        raise handler.CalendarNotFound("Calendar endpoint not found for delete.")

    monkeypatch.setattr(handler, "_caldav_request", _fake_request)
    with pytest.raises(handler.CalendarNotFound):
        handler._delete_event(config=config, event_id=event_id, confirm=True)


def test_edit_event_requires_changes(tmp_path):
    config_path = _write_config(tmp_path, writable=True)
    config = handler._load_config(str(config_path))
    event_id = handler._build_event_id("family", "/family/event-1.ics")
    with pytest.raises(handler.CalendarSkillError, match="Edit requires at least one"):
        handler._edit_event(
            config=config,
            event_id=event_id,
            title=None,
            start=None,
            duration=None,
        )


def test_edit_event_denies_non_writable_calendar_without_request(monkeypatch, tmp_path):
    config_path = _write_config(tmp_path, writable=False)
    config = handler._load_config(str(config_path))
    event_id = handler._build_event_id("family", "/family/event-1.ics")

    called = []

    def _fake_request(**kwargs):
        called.append(kwargs)
        return 200, b""

    monkeypatch.setattr(handler, "_caldav_request", _fake_request)
    with pytest.raises(handler.CalendarAccessDenied, match="Write access denied"):
        handler._edit_event(
            config=config,
            event_id=event_id,
            title="Updated title",
            start=None,
            duration=None,
        )
    assert called == []


def test_edit_event_missing_event(monkeypatch, tmp_path):
    config_path = _write_config(tmp_path, writable=True)
    config = handler._load_config(str(config_path))
    event_id = handler._build_event_id("family", "/family/missing.ics")

    def _fake_request(**kwargs):
        raise handler.CalendarNotFound("Calendar endpoint not found for edit.")

    monkeypatch.setattr(handler, "_caldav_request_with_headers", _fake_request)
    with pytest.raises(handler.CalendarNotFound):
        handler._edit_event(
            config=config,
            event_id=event_id,
            title="Updated title",
            start=None,
            duration=None,
        )


def test_edit_event_happy_path(monkeypatch, tmp_path):
    config_path = _write_config(tmp_path, writable=True)
    config = handler._load_config(str(config_path))
    event_id = handler._build_event_id("family", "/family/event-1.ics")

    existing_ical = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:event-1\r\n"
        "DTSTART:20260302T160000Z\r\n"
        "DTEND:20260302T170000Z\r\n"
        "SUMMARY:Old title\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    get_calls = []
    put_calls = []

    def _fake_get_request(**kwargs):
        get_calls.append(kwargs)
        return 200, existing_ical.encode("utf-8"), {"etag": '"v1"'}

    def _fake_put_request(**kwargs):
        put_calls.append(kwargs)
        return 204, b""

    monkeypatch.setattr(handler, "_caldav_request_with_headers", _fake_get_request)
    monkeypatch.setattr(handler, "_caldav_request", _fake_put_request)
    output = handler._edit_event(
        config=config,
        event_id=event_id,
        title="Updated title",
        start="2026-03-02T18:30",
        duration=45,
    )

    assert len(get_calls) == 1
    assert len(put_calls) == 1
    assert get_calls[0]["method"] == "GET"
    assert put_calls[0]["method"] == "PUT"
    assert put_calls[0]["headers"]["If-Match"] == '"v1"'
    assert b"SUMMARY:Updated title" in put_calls[0]["body"]
    assert b"DTSTART:" in put_calls[0]["body"]
    assert b"DTEND:" in put_calls[0]["body"]
    assert "Status: updated" in output
    assert "Event ID: family:" in output


def test_edit_event_title_only_keeps_existing_time_window(monkeypatch, tmp_path):
    config_path = _write_config(tmp_path, writable=True)
    config = handler._load_config(str(config_path))
    event_id = handler._build_event_id("family", "/family/event-1.ics")

    existing_ical = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:event-1\r\n"
        "DTSTART:20260302T160000Z\r\n"
        "DTEND:20260302T170000Z\r\n"
        "SUMMARY:Old title\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    def _fake_get_request(**kwargs):
        return 200, existing_ical.encode("utf-8"), {}

    put_calls = []

    def _fake_put_request(**kwargs):
        put_calls.append(kwargs)
        return 204, b""

    monkeypatch.setattr(handler, "_caldav_request_with_headers", _fake_get_request)
    monkeypatch.setattr(handler, "_caldav_request", _fake_put_request)
    output = handler._edit_event(
        config=config,
        event_id=event_id,
        title="Title only update",
        start=None,
        duration=None,
    )

    assert len(put_calls) == 1
    assert "If-Match" not in put_calls[0]["headers"]
    assert "Start: 2026-03-02" in output
    assert "End: 2026-03-02" in output
    assert "Title: Title only update" in output


def test_edit_event_rejects_unknown_calendar(tmp_path):
    config_path = _write_config(tmp_path, writable=True)
    config = handler._load_config(str(config_path))
    event_id = handler._build_event_id("unknown", "/unknown/event-1.ics")
    with pytest.raises(handler.CalendarSkillError, match="Unknown calendar"):
        handler._edit_event(
            config=config,
            event_id=event_id,
            title="Updated title",
            start=None,
            duration=None,
        )


def test_extract_event_duration_minutes_clamps_negative_delta():
    dtstart = datetime(2026, 3, 2, 16, 0, tzinfo=timezone.utc)
    minutes = handler._extract_event_duration_minutes(
        dtstart=dtstart,
        dtend_params={},
        dtend_raw="20260302T150000Z",
        duration_raw=None,
        timezone_name="Europe/Berlin",
        fallback_minutes=60,
    )
    assert minutes == 1


def test_main_edit_command_calls_edit(monkeypatch, capsys):
    config = _base_config()
    monkeypatch.setattr(handler, "_load_config", lambda _path: config)
    monkeypatch.setattr(handler, "_edit_event", lambda **kwargs: "Status: updated")
    monkeypatch.setattr(
        handler.sys,
        "argv",
        [
            "calendar-handler.py",
            "edit",
            "family:ZXZlbnQ",
            "--title",
            "New title",
        ],
    )

    result = handler.main()
    output = capsys.readouterr().out
    assert result == 0
    assert "Status: updated" in output


def test_main_delete_command_calls_delete(monkeypatch, capsys):
    config = _base_config()
    monkeypatch.setattr(handler, "_load_config", lambda _path: config)
    monkeypatch.setattr(handler, "_delete_event", lambda **kwargs: "Status: deleted")
    monkeypatch.setattr(
        handler.sys,
        "argv",
        ["calendar-handler.py", "delete", "family:ZXZlbnQ", "--confirm"],
    )

    result = handler.main()
    output = capsys.readouterr().out
    assert result == 0
    assert "Status: deleted" in output


def test_main_delete_requires_confirm(monkeypatch, capsys):
    config = _base_config()
    monkeypatch.setattr(handler, "_load_config", lambda _path: config)
    monkeypatch.setattr(
        handler.sys,
        "argv",
        ["calendar-handler.py", "delete", "family:ZXZlbnQ"],
    )

    result = handler.main()
    output = capsys.readouterr().out
    assert result == 1
    assert "Delete requires --confirm" in output
