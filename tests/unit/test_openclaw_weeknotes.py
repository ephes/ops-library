from pathlib import Path

import yaml


ROLE_PATH = (
    Path(__file__).resolve().parents[2]
    / "roles"
    / "openclaw_deploy"
)


def test_weeknotes_default_payload_limit_supports_long_voice_notes() -> None:
    defaults = yaml.safe_load(
        (ROLE_PATH / "defaults" / "main.yml").read_text(encoding="utf-8")
    )

    assert defaults["openclaw_weeknotes_max_payload_length"] == 4000


def test_weeknotes_handler_applies_configured_limit_to_write_commands() -> None:
    handler = (
        ROLE_PATH / "templates" / "weeknotes-md-handler.sh.j2"
    ).read_text(encoding="utf-8")

    assert "MAX_PAYLOAD={{ openclaw_weeknotes_max_payload_length }}" in handler
    assert handler.count("ERROR: Text exceeds %d characters") == 2
