from pathlib import Path

import yaml


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
