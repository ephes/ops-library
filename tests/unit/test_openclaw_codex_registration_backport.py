import json
import os
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
ROLE = ROOT / "roles" / "openclaw_deploy"
PATCHER = ROLE / "files" / "openclaw-codex-v2026.9.1-registration-backport.mjs"
TASKS = ROLE / "tasks" / "plugins.yml"
VALIDATION = ROLE / "tasks" / "validate.yml"
VARIABLE = "openclaw_codex_v2026_9_1_registration_backport_enabled"
MANAGED_VARIABLE = "openclaw_codex_v2026_9_1_registration_backport_managed"


def _tasks(path: Path) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _task(path: Path, name: str) -> dict:
    return next(task for task in _tasks(path) if task.get("name") == name)


def _nested_tasks(tasks: list[dict]) -> list[dict]:
    result: list[dict] = []
    for task in tasks:
        result.append(task)
        result.extend(_nested_tasks(task.get("block", [])))
        result.extend(_nested_tasks(task.get("always", [])))
    return result


def test_compiled_backport_matches_upstream_registration_change() -> None:
    source = r"""
const {
  applyBackport,
  revertBackport,
  validatePatched,
  validatePristine,
} = await import(process.env.PATCHER_URL);
const source = [
  "const MAX_PROCESS_CONTAINMENT_MS$1 = 2e3;",
  "//#region extensions/codex/src/app-server/transport-process-registration.ts\n" +
    "const processIdentity = z.object({",
  "async function reapRegisteredCodexAppServerOrphans(requestedDeadline) {\n" +
    "\tconst store = await openProcessRegistrationStore();\n" +
    "\tconst deadline = requestedDeadline ?? Date.now() + 1e4;",
  "\t\tconst snapshot = await readCodexAppServerProcessSnapshot(void 0, " +
    "[registration.parent.pid, registration.child.pid]);",
  "\t\tif (!child.pid) throw new ProcessInspectionError(\"unavailable\");\n" +
    "\t\tconst snapshot = await readCodexAppServerProcessSnapshot(void 0, [child.pid]);",
  "\t\tconst command = await readCodexAppServerProcessCommand(spawned, Date.now() + 2e3);",
].join("\n// unrelated compiled code\n");
const patched = applyBackport(source);
validatePatched(patched);
const reverted = revertBackport(patched);
validatePristine(reverted);
console.log(JSON.stringify({
  registrationBudget: patched.includes(
    "const PROCESS_REGISTRATION_INSPECTION_MS = 1e4;",
  ),
  sharedSnapshotDeadline: patched.includes(
    "readCodexAppServerProcessSnapshot(deadline, [child.pid])",
  ),
  sharedCommandDeadline: patched.includes(
    "readCodexAppServerProcessCommand(spawned, deadline)",
  ),
  containmentBudgetPreserved: patched.includes(
    "const MAX_PROCESS_CONTAINMENT_MS$1 = 2e3;",
  ),
  reversible: reverted === source,
}));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", source],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PATCHER_URL": PATCHER.as_uri()},
    )
    result = json.loads(completed.stdout)

    assert result == {
        "registrationBudget": True,
        "sharedSnapshotDeadline": True,
        "sharedCommandDeadline": True,
        "containmentBudgetPreserved": True,
        "reversible": True,
    }


def test_backport_plan_uses_verified_install_path_without_a_shell() -> None:
    task = _task(
        TASKS,
        "plugins | Plan Codex v2026.9.1 process-registration backport",
    )
    argv = task["ansible.builtin.command"]["argv"]

    assert task["when"] == f"{MANAGED_VARIABLE} | bool"
    assert argv[:4] == ["docker", "run", "--rm", "--user"]
    assert "{{ openclaw_data_dir }}:/home/node/.openclaw" in argv
    assert any(value.endswith(":/tmp/openclaw-codex-registration-backport.mjs:ro") for value in argv)
    assert argv[-2] == (
        "{{\n  'apply'\n  if (openclaw_codex_v2026_9_1_registration_backport_enabled | bool)\n"
        "  else 'revert'\n}}"
    )
    assert argv[-3] == (
        "{{ _openclaw_codex_plugin_verified.get('install', {}).get('installPath', '') }}"
    )
    assert VARIABLE in argv[-2]
    assert argv[-1] == "--check"
    assert task["changed_when"] is False


def test_backport_quiesces_and_restores_a_running_gateway() -> None:
    tasks = _nested_tasks(_tasks(TASKS))
    names = [task.get("name") for task in tasks]
    check_index = names.index(
        "plugins | Check whether OpenClaw is running before backport reconciliation"
    )
    stop_index = names.index("plugins | Stop OpenClaw before backport reconciliation")
    apply_index = names.index("plugins | Apply planned Codex v2026.9.1 backport state")
    restore_index = names.index("plugins | Restore a previously running OpenClaw service")

    assert check_index < stop_index < apply_index < restore_index
    restore = tasks[restore_index]
    assert restore["ansible.builtin.systemd"]["state"] == "started"
    assert "openclaw_codex_gateway_active.rc == 0" in restore["when"]
    assert _task(
        TASKS,
        "plugins | Reconcile Codex backport while gateway is quiescent",
    )["always"][0] == restore


def test_backport_is_fail_closed_to_official_v2026_9_1_plugin() -> None:
    task = _task(
        VALIDATION,
        "validate | Codex v2026.9.1 process-registration backport settings",
    )
    assertions = task["ansible.builtin.assert"]["that"]

    assert task["when"] == f"{MANAGED_VARIABLE} | bool"
    assert "openclaw_codex_plugin_enabled | bool" in assertions
    assert "openclaw_version == 'v2026.9.1'" in assertions
    assert "openclaw_codex_plugin_package == '@openclaw/codex'" in assertions
    assert "openclaw_codex_plugin_version == '2026.9.1'" in assertions


def test_backport_runs_after_plugin_identity_verification() -> None:
    names = [task.get("name") for task in _tasks(TASKS)]
    assert names.index("plugins | Verify installed Codex plugin identity and version") < names.index(
        "plugins | Plan Codex v2026.9.1 process-registration backport"
    )


def test_backport_rejects_symlinks_ambiguous_bundles_and_unknown_digests() -> None:
    source = r"""
import { mkdtemp, mkdir, realpath, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
const { reconcile, resolveTarget } = await import(process.env.PATCHER_URL);

async function createPlugin(root, name) {
  const plugin = path.join(root, name);
  await mkdir(path.join(plugin, "dist"), { recursive: true });
  await writeFile(
    path.join(plugin, "package.json"),
    JSON.stringify({ name: "@openclaw/codex", version: "2026.9.1" }),
  );
  await writeFile(path.join(plugin, "dist", "transport-stdio-fixture.js"), "unknown");
  return plugin;
}

async function rejection(operation, pattern) {
  try {
    await operation();
    return false;
  } catch (error) {
    return pattern.test(String(error));
  }
}

const root = await realpath(await mkdtemp(path.join(os.tmpdir(), "openclaw-backport-test-")));
const unknown = await createPlugin(root, "unknown");
const ambiguous = await createPlugin(root, "ambiguous");
await writeFile(path.join(ambiguous, "dist", "transport-stdio-second.js"), "unknown");
const realDist = path.join(root, "real-dist");
await mkdir(realDist);
await writeFile(path.join(realDist, "transport-stdio-linked.js"), "unknown");
const linked = path.join(root, "linked");
await mkdir(linked);
await writeFile(
  path.join(linked, "package.json"),
  JSON.stringify({ name: "@openclaw/codex", version: "2026.9.1" }),
);
await symlink(realDist, path.join(linked, "dist"));

console.log(JSON.stringify({
  unknownDigest: await rejection(
    () => reconcile(unknown, "apply", false, root),
    /unknown Codex transport bundle/,
  ),
  ambiguousBundle: await rejection(
    () => resolveTarget(ambiguous, root),
    /expected one .* transport bundle, found 2/,
  ),
  symlinkedDist: await rejection(
    () => resolveTarget(linked, root),
    /symlinked path component|real directory, not a symlink/,
  ),
}));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", source],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PATCHER_URL": PATCHER.as_uri()},
    )

    assert json.loads(completed.stdout) == {
        "unknownDigest": True,
        "ambiguousBundle": True,
        "symlinkedDist": True,
    }
