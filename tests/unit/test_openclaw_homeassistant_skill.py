"""Contract tests for the /homeassistant command skill instructions.

The handler's allowlist stops the wrong *write*. It cannot stop the wrong
*target*: an agent asked to switch a device outside the write allowlist can
discover the writable domain, act on the closest-sounding entity there, and
report success under the name the user said. That happened in production on
2026-07-30 - "Mach bitte das Amaran-Licht an." turned on light.strahler_tripod
and answered "Das Amaran-Licht ist an.", while the real target
(switch.wintergarten_amaran_60x_s_power) stayed off.

The only thing standing between that behaviour and the house is prose in the
skill template, so these tests pin the rules that prose has to keep carrying.
They deliberately assert on the *substance* of each rule rather than exact
wording, so the text can be reworded but not quietly dropped.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


SKILL_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "roles"
    / "openclaw_deploy"
    / "templates"
    / "homeassistant-skill.md.j2"
)

TEMPLATE_VARS = {
    "openclaw_homeassistant_command_skill_name": "homeassistant",
    "openclaw_homeassistant_skill_name": "homeassistant-read",
    "openclaw_homeassistant_container_skills_dir": "/home/node/.openclaw/skills",
}


def _render_skill() -> str:
    source = SKILL_TEMPLATE_PATH.read_text(encoding="utf-8")
    for name, value in TEMPLATE_VARS.items():
        source = source.replace("{{ " + name + " }}", value)
    if "{{" in source:
        start = source.index("{{")
        end = source.index("}}", start) + 2 if "}}" in source[start:] else start + 2
        raise AssertionError(f"Unreplaced Jinja2 variable in template: {source[start:end]}")
    return source


@pytest.fixture(scope="module")
def skill() -> str:
    return _render_skill()


def test_renders_with_the_role_defaults(skill: str) -> None:
    assert skill.startswith("---\nname: homeassistant\n")
    assert "/home/node/.openclaw/skills/homeassistant-read/handler.py" in skill


def test_has_a_truthfulness_section(skill: str) -> None:
    assert re.search(r"^##\s+Truthfulness Rules\s*$", skill, re.MULTILINE)


def test_forbids_substituting_a_different_entity(skill: str) -> None:
    """The Strahler Tripod bug: acting on the nearest writable lookalike."""
    assert "Never substitute." in skill
    # The specific trap - reaching for another domain because it is writable.
    assert re.search(
        r"do not\s+fall back to a different domain because that domain happens to be writable",
        skill,
    )


def test_requires_naming_the_entity_actually_acted_on(skill: str) -> None:
    assert "Never report an action you did not perform." in skill
    assert "State the entity you actually acted" in skill


def test_requires_reporting_a_write_refusal_verbatim(skill: str) -> None:
    """A denial must be relayed, not worked around against another entity."""
    assert "A refusal is a result." in skill
    assert "is not allowlisted" in skill
    assert "Do not\n  retry the request against a different entity." in skill


def test_forbids_treating_a_no_op_as_a_confirmation(skill: str) -> None:
    assert "`Changed states reported: 0` is not a confirmation." in skill


def test_forbids_claiming_absence_from_a_filtered_list(skill: str) -> None:
    """A --domain filter only proves absence from that domain.

    A German speaker calls a smart plug driving a lamp a "Licht" regardless of
    its HA domain, so words in the request are not domain hints.
    """
    assert 'Never conclude "does not exist" from a filtered list.' in skill
    assert "run `list --limit 200` with no\n  `--domain` filter" in skill


def test_forbids_claiming_absence_from_a_truncated_list(skill: str) -> None:
    """`showing X of Y` with X < Y is a partial view of the house."""
    assert "Allowed entities: showing X of Y" in skill
    assert "until `X == Y`" in skill
    assert "Never report a\n  device as absent based on a truncated listing." in skill


def test_discovery_is_not_hardcoded_to_the_light_domain(skill: str) -> None:
    """Steering discovery at lights is what surfaced the writable lookalike."""
    assert "Do not assume the target is a light" in skill
    assert "- `list --limit 200` for an unqualified request" in skill
    assert "list --domain light --limit 200" not in skill
