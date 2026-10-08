"""Exercise the literal subject boundary emitted into rspamd's UCL settings."""

import json
import re
from pathlib import Path

import jinja2
import pytest


TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "roles/mail_spam_deploy/templates/local.d/settings.conf.j2"
)


def render(probe):
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["to_json"] = json.dumps
    env.filters["regex_escape"] = re.escape
    return env.from_string(TEMPLATE.read_text()).render(
        mail_spam_monitoring_probe=probe
    )


def test_empty_configuration_removes_exemption():
    assert "nyxmon_local_delivery_probe" not in render({})


@pytest.mark.parametrize("prefix", ["[nyxmon-local-inbound]", "[probe].*"])
def test_subject_is_literal_and_anchored(prefix):
    result = render(
        dict(
            source_ip="100.64.0.10",
            sender="probe@example.com",
            recipient="monitor@example.com",
            subject_prefix=prefix,
        )
    )
    encoded = re.search(r'"Subject" = (.+);', result).group(1)
    pattern = json.loads(encoded)[1:-1]
    assert re.search(pattern, prefix + " 2026-10-08T12:00:00Z abc123")
    assert re.search(pattern, prefix)
    assert not re.search(pattern, "forged " + prefix)
    assert not re.search(pattern, prefix + "-forged")
    assert not re.search(pattern, prefix.replace("[", "").replace("]", ""))


@pytest.mark.parametrize(
    "source, allowed",
    [
        ("100.64.0.10", True),
        ("100.64.0.20", False),
        ("192.168.1.20", False),
        ("127.0.1.1", False),
    ],
)
def test_role_rejects_trusted_relay_and_local_sources(source, allowed):
    import subprocess
    import sys
    import yaml

    tasks = yaml.safe_load((TEMPLATE.parents[2] / "tasks/main.yml").read_text())
    task = next(
        t
        for t in tasks
        if t["name"] == "Validate probe source is not a local or relay network"
    )
    script = task["ansible.builtin.command"]["argv"][2]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            source,
            json.dumps(["100.64.0.20/32", "192.168.0.0/16", "127.0.0.0/8", "::1/128"]),
        ],
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) == allowed
