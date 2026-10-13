from pathlib import Path

import pytest
import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROLE = Path(__file__).resolve().parents[2] / "roles" / "openclaw_deploy"


def _render(expression, variables):
    if isinstance(expression, list):
        return [_render(item, variables) for item in expression]
    return Templar(loader=DataLoader(), variables=variables).template(
        trust_as_template(expression)
    )


def _context(running, image="openclaw:v2026.10.2", exists=True, stdout=None):
    variables = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    variables.update(
        openclaw_container_name="test-gateway",
        openclaw_site_dir="/test/site",
        openclaw_data_dir="/test/data",
        openclaw_image_name="openclaw",
        openclaw_image_tag="v2026.10.2",
        openclaw_codex_plugin_version="2026.10.2",
        _openclaw_cli_gateway={
            "rc": 0 if exists else 1,
            "stdout": f"{'true' if running else 'false'} {image}" if exists else "",
        },
    )
    if stdout is not None:
        variables["_openclaw_cli_gateway"]["stdout"] = stdout
    tasks = yaml.safe_load((ROLE / "tasks/cli_context.yml").read_text())
    inspector = tasks[0]
    assert _render(inspector["ansible.builtin.command"]["argv"], variables) == [
        "docker",
        "inspect",
        "--format",
        "{{.State.Running}} {{.Config.Image}}",
        "test-gateway",
    ]
    assert inspector["failed_when"] is False
    for task in tasks:
        for key, expression in task.get("ansible.builtin.set_fact", {}).items():
            variables[key] = _render(expression, variables)
        for condition in task.get("ansible.builtin.assert", {}).get("that", []):
            if not _render("{{ " + condition + " }}", variables):
                raise ValueError(task["name"])
    return variables


@pytest.mark.parametrize(
    "running,exists", [(False, False), (False, True), (True, True)]
)
def test_plugin_and_audio_commands_use_safe_context(running, exists):
    variables = _context(running, exists=exists)
    prefix = variables["_openclaw_cli_argv"]
    assert prefix[:3] == ["docker", "run", "--rm"]
    assert prefix[prefix.index("--network") + 1] == "host"
    assert prefix[prefix.index("--env-file") + 1] == "/test/site/.env"
    assert prefix[prefix.index("--volume") + 1] == "/test/data:/home/node/.openclaw"
    assert prefix[-2:] == ["openclaw:v2026.10.2", "dist/index.js"]
    if running:
        assert prefix[prefix.index("--pid") + 1] == "container:test-gateway"
    else:
        assert "--pid" not in prefix
    expected = {
        "plugins | Inspect installed Codex plugin": [
            "plugins",
            "inspect",
            "codex",
            "--json",
        ],
        "plugins | Install configured official Codex plugin release": [
            "plugins",
            "install",
            "--force",
            "--pin",
            "@openclaw/codex@2026.10.2",
        ],
        "plugins | Inspect Codex plugin after reconciliation": [
            "plugins",
            "inspect",
            "codex",
            "--json",
        ],
        "audio_transcription | Preflight dedicated auth profile": [
            "secrets",
            "apply",
            "--from",
            "/home/node/.openclaw/managed-audio-secrets-plan.json",
            "--dry-run",
            "--json",
        ],
        "audio_transcription | Apply dedicated auth profile": [
            "secrets",
            "apply",
            "--from",
            "/home/node/.openclaw/managed-audio-secrets-plan.json",
            "--json",
        ],
    }
    seen = set()
    for filename in ("plugins.yml", "audio_transcription.yml"):
        tasks = yaml.safe_load((ROLE / "tasks" / filename).read_text())
        assert tasks[0]["ansible.builtin.import_tasks"] == "cli_context.yml"
        for task in tasks:
            if task["name"] not in expected:
                continue
            argv = _render(task["ansible.builtin.command"]["argv"], variables)
            assert argv == prefix + expected[task["name"]]
            if filename == "audio_transcription.yml":
                assert task["no_log"] is True
            seen.add(task["name"])
    assert seen == set(expected)


def test_live_cli_context_rejects_different_image_before_command_selection():
    with pytest.raises(ValueError, match="Require matching image"):
        _context(True, image="openclaw:v2026.9.9")


@pytest.mark.parametrize(
    "stdout", ["", "true", "true image extra", "unrecognized image"]
)
def test_cli_context_refuses_unrecognized_inspection_instead_of_offline_fallback(
    stdout,
):
    with pytest.raises(ValueError, match="Require unambiguous container state"):
        _context(True, stdout=stdout)
