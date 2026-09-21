// Run inside the pinned OpenClaw image. No model calls, outbound sends, or state writes.
import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

const dist = process.env.OPENCLAW_DIST ?? '/app/dist';
assert.ok(process.env.HEARTBEAT_PLUGIN, 'Set HEARTBEAT_PLUGIN to the installed extension index.js path');
async function bundledExport(name) {
  for (const file of await readdir(dist)) {
    if (!file.endsWith('.js')) continue;
    const source = await readFile(`${dist}/${file}`, 'utf8');
    const match = source.match(new RegExp(`export \\{[^}]*\\b${name} as ([A-Za-z_$][\\w$]*)[ ,}]`));
    if (match) return (await import(pathToFileURL(`${dist}/${file}`)))[match[1]];
  }
  throw new Error(`Missing installed runtime export: ${name}`);
}
const createHookRunner = await bundledExport('createHookRunner');
const createPolicy = await bundledExport('createAgentHarnessPromptToolPolicy');
const { default: plugin } = await import(pathToFileURL(process.env.HEARTBEAT_PLUGIN));
const registry = { typedHooks: [] };
plugin.register({
  on(hookName, handler) { registry.typedHooks.push({ pluginId: plugin.id, hookName, handler }); },
  logger: { info() {} },
});
const runner = createHookRunner(registry, {catchErrors: false});
const ctx = {runId: 'integration-heartbeat', trigger: 'heartbeat', sessionKey: 'agent:main:main'};
const event = {prompt: 'The previous attempt did not produce a user-visible answer. Continue from the current state and produce the visible answer now. Do not restart from scratch.', messages: []};
const recovery = await runner.runBeforePromptBuild(event, ctx);
assert.match(recovery.appendSystemContext, /heartbeat_respond/);
const tools = [{name: 'message'}, {name: 'exec'}, {name: 'heartbeat_respond'}];
const policy = createPolicy({tools, codeModeControlsEnabled: false});
assert.deepEqual(policy.apply({toolsAllow: recovery.toolsAllow}).callableToolNames, ['heartbeat_respond']);
// OpenClaw may force-add message after filtering; the dispatch hook must still block it.
assert.ok(policy.apply({toolsAllow: recovery.toolsAllow, forceToolNames: ['message']}).callableToolNames.includes('message'));
const message = {toolName: 'message', params: {action: 'send', target: 'telegram'}};
const blocked = await runner.runBeforeToolCall(message, {...ctx, toolName: 'message'});
assert.equal(blocked.block, true);
const permitted = await runner.runBeforeToolCall({toolName: 'heartbeat_respond', params: {notify: true}}, {...ctx, toolName: 'heartbeat_respond'});
assert.notEqual(permitted?.block, true);
const chatCtx = {...ctx, trigger: 'user', runId: 'integration-chat'};
assert.equal(await runner.runBeforePromptBuild(event, chatCtx), undefined);
assert.notEqual((await runner.runBeforeToolCall(message, {...chatCtx, toolName: 'message'}))?.block, true);
await runner.runAgentEnd({messages: [], success: true}, ctx);
assert.notEqual((await runner.runBeforeToolCall(message, {...ctx, toolName: 'message'}))?.block, true);
console.log('PASS: installed hook runner, tool policy, forced-message guard, chat isolation, cleanup');
