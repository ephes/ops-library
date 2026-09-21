"""Exercise the shipped extension at the OpenClaw hook boundary, without network calls."""

import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ROLE = ROOT / "roles/openclaw_deploy"


def test_recovery_hooks() -> None:
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "--eval",
            r"""
import assert from 'node:assert/strict';
const { default: plugin } = await import(process.env.PLUGIN_URL);
const hooks = {};
const logs = [];
const warnings = [];
plugin.register({on: (name, fn) => { hooks[name] = fn; }, logger: {info: x => logs.push(x), warn: x => warnings.push(x)}});
const empty = 'The previous attempt did not produce a user-visible answer. Continue from the current state and produce the visible answer now. Do not restart from scratch.';
const reasoning = 'The previous assistant turn recorded reasoning but did not produce a user-visible answer. Continue from that partial turn and produce the visible answer now. Do not restate the reasoning or restart from scratch.';
for (const trigger of ['user', 'manual', 'cron', undefined]) {
  assert.equal(hooks.before_prompt_build({prompt: empty}, {trigger, runId: 'chat'}), undefined);
}
const ctx = {trigger: 'heartbeat', runId: 'beat', sessionKey: 'agent:main:main'};
for (const prompt of [undefined, null, [], {}]) {
  assert.equal(hooks.before_prompt_build({prompt}, ctx), undefined);
}
assert.equal(hooks.before_prompt_build({prompt: 'Normal heartbeat', messages: [{text: empty}]}, ctx), undefined);
const withoutRunId = hooks.before_prompt_build({prompt: empty}, {trigger: 'heartbeat'});
assert.deepEqual(withoutRunId.toolsAllow, ['heartbeat_respond']);
assert.match(withoutRunId.appendSystemContext, /heartbeat_respond/);
assert.equal(hooks.before_tool_call({toolName: 'message'}, {}), undefined);
for (const prompt of [empty, reasoning]) {
  const result = hooks.before_prompt_build({prompt}, ctx);
  assert.deepEqual(result.toolsAllow, ['heartbeat_respond']);
  assert.match(result.appendSystemContext, /notify=false/);
  assert.match(result.appendSystemContext, /notify=true with notificationText/);
  assert.match(result.appendSystemContext, /do not claim checks ran/);
  for (const target of ['telegram', '@telegram', '12345']) {
    assert.equal(hooks.before_tool_call({toolName: 'message', params: {action: 'send', target}}, ctx).block, true);
  }
  assert.equal(hooks.before_tool_call({toolName: 'heartbeat_respond', params: {notify: true}}, ctx), undefined);
  assert.equal(hooks.before_tool_call({toolName: 'message'}, {...ctx, runId: 'chat'}), undefined);
  hooks.agent_end({}, {...ctx, runId: 'chat'});
  assert.equal(hooks.before_tool_call({toolName: 'message'}, ctx).block, true);
  hooks.agent_end({}, ctx);
  assert.equal(hooks.before_tool_call({toolName: 'message'}, ctx), undefined);
}
assert.equal(logs.length, 3);
assert.equal(warnings.length, 1);
assert.match(warnings[0], /host run ID/);
// Abandoned runs expire; another session is never poisoned by a stale run.
hooks.before_prompt_build({prompt: empty}, ctx);
const originalNow = Date.now;
const future = Date.now() + 3600001;
Date.now = () => future;
assert.equal(hooks.before_tool_call({toolName: 'message'}, ctx), undefined);
hooks.before_prompt_build({prompt: 'Normal heartbeat'}, ctx);
Date.now = originalNow;
assert.equal(hooks.before_tool_call({toolName: 'message'}, ctx), undefined);
""",
        ],
        env={
            **os.environ,
            "PLUGIN_URL": (ROLE / "files/heartbeat-recovery/index.js").as_uri(),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_deploys_before_config_and_supports_disable() -> None:
    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
    names = [t.get("ansible.builtin.import_tasks") for t in tasks]
    assert names.index("heartbeat_recovery.yml") < names.index("config.yml")
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    assert defaults["openclaw_heartbeat_recovery_managed"] is False


def test_managed_config_renders_enabled_disabled_and_unmanaged() -> None:
    from ansible.parsing.dataloader import DataLoader
    from ansible.template import Templar, trust_as_template

    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    tasks = yaml.safe_load((ROLE / "tasks/config.yml").read_text())
    inputs = next(
        t["ansible.builtin.set_fact"]
        for t in tasks
        if t["name"] == "config | Build managed plugin patch inputs"
    )
    for managed, enabled in [(True, True), (True, False), (False, True)]:
        variables = {
            **defaults,
            "openclaw_heartbeat_recovery_managed": managed,
            "openclaw_heartbeat_recovery_enabled": enabled,
        }
        templar = Templar(loader=DataLoader(), variables=variables)
        rendered = {
            k: templar.template(trust_as_template(v)) for k, v in inputs.items()
        }
        entries = rendered["_openclaw_managed_plugin_entries"]
        assert ("heartbeat-recovery" in entries) == managed
        assert (
            "heartbeat-recovery" in rendered["_openclaw_managed_plugin_allow"]
        ) == managed
        assert (
            "/home/node/.openclaw/extensions/heartbeat-recovery"
            in rendered["_openclaw_managed_plugin_load_paths"]
        ) == managed
        if managed:
            assert entries["heartbeat-recovery"]["enabled"] is enabled
            assert entries["heartbeat-recovery"]["hooks"] == {
                "allowConversationAccess": True,
                "allowPromptInjection": True,
            }


def test_container_mapping_matches_extension_paths() -> None:
    compose = (ROLE / "templates/openclaw-compose.yml.j2").read_text()
    assert "{{ openclaw_data_dir }}:/home/node/.openclaw" in compose
    tasks = yaml.safe_load((ROLE / "tasks/heartbeat_recovery.yml").read_text())
    copy = next(t["ansible.builtin.copy"] for t in tasks if "ansible.builtin.copy" in t)
    assert copy["dest"].startswith(
        "{{ openclaw_data_dir }}/extensions/heartbeat-recovery/"
    )
    assert copy["owner"] == "1000"


def test_health_rejects_loaded_plugin_with_blocked_hooks() -> None:
    import json
    from ansible.parsing.dataloader import DataLoader
    from ansible.template import Templar, trust_as_template

    tasks = yaml.safe_load((ROLE / "tasks/health.yml").read_text())
    checks = next(
        t["ansible.builtin.assert"]["that"]
        for t in tasks
        if t["name"]
        == "health | Verify heartbeat recovery enabled state and hook registration"
    )
    for enabled, loaded_hooks, expected in [
        (True, ["before_prompt_build", "before_tool_call", "agent_end"], True),
        (True, ["before_tool_call"], False),
        (False, [], True),
    ]:
        inspection = {
            "plugin": {
                "enabled": enabled,
                "status": "loaded" if enabled else "disabled",
                "imported": enabled,
            },
            "typedHooks": [{"name": name} for name in loaded_hooks],
        }
        variables = {
            "openclaw_heartbeat_recovery_enabled": enabled,
            "_openclaw_heartbeat_recovery_inspect": {"stdout": json.dumps(inspection)},
        }
        templar = Templar(loader=DataLoader(), variables=variables)
        assert (
            all(
                templar.template(trust_as_template("{{ " + check + " }}"))
                for check in checks
            )
            is expected
        )


def test_version_guard_rejects_unsupported_managed_release() -> None:
    from ansible.parsing.dataloader import DataLoader
    from ansible.template import Templar, trust_as_template

    tasks = yaml.safe_load((ROLE / "tasks/validate.yml").read_text())
    task = next(
        t
        for t in tasks
        if t["name"] == "validate | Validate supported upstream version"
    )
    assert task["when"] == "openclaw_heartbeat_recovery_managed | bool"
    condition = task["ansible.builtin.assert"]["that"][0]
    for version, expected in [
        ("v2026.9.1", True),
        ("2026.9.1", True),
        ("v2026.9.2", False),
        ("main", False),
    ]:
        templar = Templar(loader=DataLoader(), variables={"openclaw_version": version})
        assert (
            templar.template(trust_as_template("{{ " + condition + " }}")) is expected
        )
