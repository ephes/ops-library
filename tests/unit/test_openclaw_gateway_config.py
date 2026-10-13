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


@pytest.mark.parametrize("network_mode", ["bridge", "host"])
@pytest.mark.parametrize("traefik_enabled", [False, True])
def test_network_mode_keeps_gateway_bind_and_port_consistent(
    network_mode, traefik_enabled
):
    variables = yaml.safe_load((ROLE_ROOT / "defaults/main.yml").read_text())
    variables.update(
        openclaw_network_mode=network_mode,
        openclaw_traefik_enabled=traefik_enabled,
        openclaw_host_port=18890,
        openclaw_container_port=18789,
    )
    task = _task_by_name("config | Build gateway access patch")
    templar = Templar(loader=DataLoader(), variables=variables)
    patch = templar.template(
        trust_as_template(
            task["ansible.builtin.set_fact"]["_openclaw_gateway_access_patch"]
        )
    )["gateway"]
    assert patch["bind"] == (
        "lan" if network_mode == "bridge" and traefik_enabled else "loopback"
    )
    assert patch["port"] == (18890 if network_mode == "host" else 18789)
    variables["_openclaw_existing_config"] = {"gateway": {"bind": "lan", "port": 9999}}
    for name in (
        "config | Build managed plugin patch inputs",
        "config | Build gateway access patch",
    ):
        for key, expression in _task_by_name(name)["ansible.builtin.set_fact"].items():
            variables[key] = Templar(loader=DataLoader(), variables=variables).template(
                trust_as_template(expression)
            )
    runtime = Templar(loader=DataLoader(), variables=variables).template(
        trust_as_template(
            _task_by_name("config | Build runtime config patch")[
                "ansible.builtin.set_fact"
            ]["_openclaw_runtime_patch"]
        )
    )["gateway"]
    assert runtime["bind"] == patch["bind"]
    assert runtime["port"] == patch["port"]
    compose_template = (ROLE_ROOT / "templates/openclaw-compose.yml.j2").read_text()
    rendered = templar.template(trust_as_template(compose_template))
    services = yaml.safe_load(rendered)["services"]
    service = services[variables["openclaw_container_name"]]
    assert services["openclaw-cli"]["network_mode"] == (
        "host"
        if network_mode == "host"
        else "service:" + variables["openclaw_container_name"]
    )
    if network_mode == "host":
        assert service["network_mode"] == "host"
        assert "ports" not in service
    else:
        assert "network_mode" not in service
        assert service["ports"] == ["127.0.0.1:18890:18789"]


@pytest.mark.parametrize("configured_timeout", [123, 500])
def test_port_startup_budget_is_independent_of_readiness_retries(configured_timeout):
    defaults = yaml.safe_load((ROLE_ROOT / "defaults/main.yml").read_text())
    defaults["openclaw_startup_timeout"] = configured_timeout
    tasks = yaml.safe_load((ROLE_ROOT / "tasks/health.yml").read_text())
    templar = Templar(loader=DataLoader(), variables=defaults)
    timeout = templar.template(
        trust_as_template(tasks[0]["ansible.builtin.wait_for"]["timeout"])
    )
    assert timeout == configured_timeout
    assert (
        timeout
        > defaults["openclaw_healthcheck_delay"]
        * defaults["openclaw_healthcheck_retries"]
    )


@pytest.mark.parametrize("invalid_timeout", [0, -1, "not-a-number"])
def test_invalid_startup_budget_fails_with_its_variable_named(invalid_timeout):
    variables = yaml.safe_load((ROLE_ROOT / "defaults/main.yml").read_text())
    variables["openclaw_startup_timeout"] = invalid_timeout
    task = next(
        task
        for task in yaml.safe_load((ROLE_ROOT / "tasks/validate.yml").read_text())
        if task["name"] == "validate | Gateway network mode"
    )
    conditions = task["ansible.builtin.assert"]["that"]
    templar = Templar(loader=DataLoader(), variables=variables)
    results = [
        templar.template(trust_as_template("{{ " + expression + " }}"))
        for expression in conditions
    ]
    assert not all(results)
    assert "openclaw_startup_timeout" in task["ansible.builtin.assert"]["fail_msg"]
