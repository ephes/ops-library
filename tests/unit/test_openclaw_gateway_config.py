from pathlib import Path

import pytest
import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template


ROLE_ROOT = Path(__file__).resolve().parents[2] / "roles" / "openclaw_deploy"


def _walk_tasks(tasks: list[dict]):
    for task in tasks:
        yield task
        for section in ("block", "rescue", "always"):
            yield from _walk_tasks(task.get(section, []))


def _task_by_name(name: str) -> dict:
    tasks = yaml.safe_load(
        (ROLE_ROOT / "tasks" / "config.yml").read_text(encoding="utf-8")
    )
    return next(task for task in _walk_tasks(tasks) if task.get("name") == name)


def test_seeded_gateway_config_sets_required_local_mode() -> None:
    task = _task_by_name("config | Build gateway access patch")
    expression = task["ansible.builtin.set_fact"]["_openclaw_gateway_access_patch"]

    assert '"mode": "local"' in expression


def test_existing_gateway_config_patch_sets_required_local_mode() -> None:
    task = _task_by_name("config | Build runtime config patch")
    expression = task["ansible.builtin.set_fact"]["_openclaw_runtime_patch"]

    assert '"mode": "local"' in expression


def test_seeded_gateway_config_manages_telegram_streaming_policy() -> None:
    task = _task_by_name("config | Build gateway config from individual variables")
    expression = task["ansible.builtin.set_fact"]["_openclaw_built_config"]

    assert '"streaming": {' in expression
    assert "openclaw_telegram_streaming_preview_tool_progress" in expression
    assert "openclaw_telegram_streaming_preview_command_text" in expression


def test_existing_gateway_config_patch_manages_telegram_streaming_policy() -> None:
    task = _task_by_name("config | Build runtime config patch")
    expression = task["ansible.builtin.set_fact"]["_openclaw_runtime_patch"]

    assert '"streaming": {' in expression
    assert "openclaw_telegram_streaming_preview_tool_progress" in expression
    assert "openclaw_telegram_streaming_preview_command_text" in expression


def test_seeded_gateway_config_manages_direct_message_session_scope() -> None:
    task = _task_by_name("config | Build gateway config from individual variables")
    expression = task["ansible.builtin.set_fact"]["_openclaw_built_config"]

    assert '"dmScope": openclaw_session_dm_scope' in expression


def test_existing_gateway_config_patch_manages_direct_message_session_scope() -> None:
    task = _task_by_name("config | Build runtime config patch")
    expression = task["ansible.builtin.set_fact"]["_openclaw_runtime_patch"]

    assert '"dmScope": openclaw_session_dm_scope' in expression


def test_workspace_guidance_is_written_to_active_workspace() -> None:
    soul_task = _task_by_name("config | Render SOUL.md (system prompt)")
    user_task = _task_by_name("config | Render USER.md (shared user profile)")

    assert (
        soul_task["ansible.builtin.copy"]["dest"]
        == "{{ openclaw_agent_workspace_dir }}/SOUL.md"
    )
    assert (
        user_task["ansible.builtin.copy"]["dest"]
        == "{{ openclaw_agent_workspace_dir }}/USER.md"
    )


@pytest.mark.parametrize("primary_configured", [False, True])
def test_model_switch_preserves_parameters_and_sets_low_reasoning(
    primary_configured: bool,
) -> None:
    variables = yaml.safe_load((ROLE_ROOT / "defaults/main.yml").read_text())
    variables.update(
        openclaw_agent_model_primary="openai/gpt-6.1-sol",
        openclaw_agent_thinking_default="low",
        _openclaw_existing_config={
            "agents": {
                "defaults": {
                    "model": {"primary": "openai/gpt-5.6-sol"},
                    "thinkingDefault": "high",
                    "models": {
                        "openai/gpt-5.6-sol": {"alias": "previous"},
                        "openai/gpt-6.1-sol": {"params": {"temperature": 0.5}},
                    },
                }
            },
            "unmanaged": {"keep": True},
        },
    )
    if not primary_configured:
        del variables["_openclaw_existing_config"]["agents"]["defaults"]["models"][
            "openai/gpt-6.1-sol"
        ]
    for name in (
        "config | Build managed plugin patch inputs",
        "config | Build gateway access patch",
        "config | Build optional model policy patch",
        "config | Build optional reasoning policy patch",
        "config | Add primary to an existing model allowlist",
    ):
        templar = Templar(loader=DataLoader(), variables=variables)
        for key, expression in _task_by_name(name)["ansible.builtin.set_fact"].items():
            variables[key] = templar.template(trust_as_template(expression))
    for name, key in (
        (
            "config | Build gateway config from individual variables",
            "_openclaw_built_config",
        ),
        ("config | Build runtime config patch", "_openclaw_runtime_patch"),
    ):
        templar = Templar(loader=DataLoader(), variables=variables)
        expression = _task_by_name(name)["ansible.builtin.set_fact"][key]
        patch = templar.template(trust_as_template(expression))
        assert patch["agents"]["defaults"]["model"]["primary"] == "openai/gpt-6.1-sol"
        assert patch["agents"]["defaults"]["thinkingDefault"] == "low"
        variables["_openclaw_runtime_patch"] = patch
    merge = _task_by_name("config | Merge runtime config patch")
    templar = Templar(loader=DataLoader(), variables=variables)
    merged = templar.template(
        trust_as_template(merge["ansible.builtin.set_fact"]["_openclaw_patched_config"])
    )
    assert merged["unmanaged"] == {"keep": True}
    assert merged["agents"]["defaults"]["models"] == {
        "openai/gpt-5.6-sol": {"alias": "previous"},
        "openai/gpt-6.1-sol": {"params": {"temperature": 0.5}}
        if primary_configured
        else {},
    }


@pytest.mark.parametrize("model_allowlist", [None, {}])
def test_model_switch_keeps_unrestricted_configs_unrestricted(model_allowlist) -> None:
    defaults = {} if model_allowlist is None else {"models": model_allowlist}
    task = _task_by_name("config | Add primary to an existing model allowlist")
    templar = Templar(
        loader=DataLoader(),
        variables={
            "openclaw_gateway_config": {},
            "openclaw_agent_model_primary": "openai/gpt-6.1-sol",
            "_openclaw_existing_config": {"agents": {"defaults": defaults}},
        },
    )
    expression = task["ansible.builtin.set_fact"]["_openclaw_model_allowlist_patch"]
    assert templar.template(trust_as_template(expression)) == {}
