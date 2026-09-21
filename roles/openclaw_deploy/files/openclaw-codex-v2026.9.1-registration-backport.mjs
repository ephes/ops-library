#!/usr/bin/env node

import { createHash, randomUUID } from "node:crypto";
import {
  lstat,
  open,
  realpath,
  readdir,
  rename,
  rm,
} from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const PACKAGE_NAME = "@openclaw/codex";
const PACKAGE_VERSION = "2026.9.1";
const UPSTREAM_COMMIT = "26e5c2858a811390887f2937236dac51015f2a48";
const SOURCE_SHA256 = "513e62ddeba5545431e34fc8a189ae53ee3425752c859cc1454d3eb1ce554d2d";
const PATCHED_SHA256 = "6d3ed3f48264c0a5ff4152e16e1bc0343e6744da7b9b7a4db0e691f98be8669e";
const DATA_ROOT = "/home/node/.openclaw";

const replacements = [
  [
    "//#region extensions/codex/src/app-server/transport-process-registration.ts\n" +
      "const processIdentity = z.object({",
    "//#region extensions/codex/src/app-server/transport-process-registration.ts\n" +
      "const PROCESS_REGISTRATION_INSPECTION_MS = 1e4;\n" +
      "const processIdentity = z.object({",
  ],
  [
    "async function reapRegisteredCodexAppServerOrphans(requestedDeadline) {\n" +
      "\tconst store = await openProcessRegistrationStore();\n" +
      "\tconst deadline = requestedDeadline ?? Date.now() + 1e4;",
    "async function reapRegisteredCodexAppServerOrphans() {\n" +
      "\tconst store = await openProcessRegistrationStore();\n" +
      "\tconst deadline = Date.now() + PROCESS_REGISTRATION_INSPECTION_MS;",
  ],
  [
    "\t\tconst snapshot = await readCodexAppServerProcessSnapshot(void 0, " +
      "[registration.parent.pid, registration.child.pid]);",
    "\t\tconst snapshot = await readCodexAppServerProcessSnapshot(deadline, " +
      "[registration.parent.pid, registration.child.pid]);",
  ],
  [
    "\t\tif (!child.pid) throw new ProcessInspectionError(\"unavailable\");\n" +
      "\t\tconst snapshot = await readCodexAppServerProcessSnapshot(void 0, [child.pid]);",
    "\t\tif (!child.pid) throw new ProcessInspectionError(\"unavailable\");\n" +
      "\t\tconst deadline = Date.now() + PROCESS_REGISTRATION_INSPECTION_MS;\n" +
      "\t\tconst snapshot = await readCodexAppServerProcessSnapshot(deadline, [child.pid]);",
  ],
  [
    "\t\tconst command = await readCodexAppServerProcessCommand(spawned, Date.now() + 2e3);",
    "\t\tconst command = await readCodexAppServerProcessCommand(spawned, deadline);",
  ],
];

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function occurrences(haystack, needle) {
  return haystack.split(needle).length - 1;
}

function applyBackport(source) {
  let patched = source;
  for (const [oldFragment, newFragment] of replacements) {
    const count = occurrences(patched, oldFragment);
    if (count !== 1) {
      throw new Error(
        `expected exactly one v${PACKAGE_VERSION} patch site, found ${count}: ` +
          JSON.stringify(oldFragment.slice(0, 80)),
      );
    }
    patched = patched.replace(oldFragment, newFragment);
  }
  return patched;
}

function validatePatched(source) {
  for (const [oldFragment, newFragment] of replacements) {
    if (source.includes(oldFragment)) {
      throw new Error(`unpatched v${PACKAGE_VERSION} code remains`);
    }
    if (occurrences(source, newFragment) !== 1) {
      throw new Error("patched code is missing or ambiguous");
    }
  }
}

function validatePristine(source) {
  for (const [oldFragment, newFragment] of replacements) {
    if (occurrences(source, oldFragment) !== 1) {
      throw new Error("pristine code is missing or ambiguous");
    }
    if (source.includes(newFragment)) {
      throw new Error(`patched v${PACKAGE_VERSION} code remains`);
    }
  }
}

function revertBackport(source) {
  let pristine = source;
  for (const [oldFragment, newFragment] of replacements) {
    const count = occurrences(pristine, newFragment);
    if (count !== 1) {
      throw new Error(
        `expected exactly one patched v${PACKAGE_VERSION} site, found ${count}: ` +
          JSON.stringify(newFragment.slice(0, 80)),
      );
    }
    pristine = pristine.replace(newFragment, oldFragment);
  }
  return pristine;
}

function sameIdentity(left, right) {
  return left.dev === right.dev && left.ino === right.ino;
}

async function inspectDirectory(directory, label) {
  const metadata = await lstat(directory);
  if (metadata.isSymbolicLink() || !metadata.isDirectory()) {
    throw new Error(`${label} must be a real directory, not a symlink`);
  }
  if ((await realpath(directory)) !== directory) {
    throw new Error(`${label} contains a symlinked path component`);
  }
  return { dev: metadata.dev, ino: metadata.ino };
}

async function revalidateDirectory(directory, expected, label) {
  const current = await inspectDirectory(directory, label);
  if (!sameIdentity(current, expected)) {
    throw new Error(`${label} changed during backport reconciliation`);
  }
}

async function inspectRegularFile(filename, label) {
  const metadata = await lstat(filename);
  if (metadata.isSymbolicLink() || !metadata.isFile()) {
    throw new Error(`${label} must be a regular file, not a symlink`);
  }
  if ((await realpath(filename)) !== filename) {
    throw new Error(`${label} contains a symlinked path component`);
  }
  return { dev: metadata.dev, ino: metadata.ino };
}

async function readPinnedFile(filename, expected, label) {
  const handle = await open(filename, "r");
  try {
    const before = await handle.stat();
    if (!sameIdentity(before, expected) || !before.isFile()) {
      throw new Error(`${label} changed before it could be read`);
    }
    const content = await handle.readFile("utf8");
    const after = await handle.stat();
    if (!sameIdentity(after, expected) || before.size !== after.size || before.mtimeMs !== after.mtimeMs) {
      throw new Error(`${label} changed while it was being read`);
    }
    return content;
  } finally {
    await handle.close();
  }
}

async function resolveTarget(pluginDirArgument, dataRoot = DATA_ROOT) {
  const pluginDir = await realpath(pluginDirArgument);
  if (pluginDir !== pluginDirArgument) {
    throw new Error("plugin directory must not contain symlinked path components");
  }
  if (pluginDir !== dataRoot && !pluginDir.startsWith(`${dataRoot}/`)) {
    throw new Error(`plugin directory must remain under ${dataRoot}`);
  }
  const pluginIdentity = await inspectDirectory(pluginDir, "plugin directory");

  const packageJsonPath = path.join(pluginDir, "package.json");
  const packageJsonIdentity = await inspectRegularFile(packageJsonPath, "package.json");
  const packageJson = JSON.parse(
    await readPinnedFile(packageJsonPath, packageJsonIdentity, "package.json"),
  );
  if (packageJson.name !== PACKAGE_NAME || packageJson.version !== PACKAGE_VERSION) {
    throw new Error(
      `backport requires exactly ${PACKAGE_NAME}@${PACKAGE_VERSION}; found ` +
        `${packageJson.name}@${packageJson.version}`,
    );
  }

  const distDir = path.join(pluginDir, "dist");
  const distIdentity = await inspectDirectory(distDir, "plugin dist directory");
  const entries = await readdir(distDir);
  const candidates = entries.filter((name) => /^transport-stdio-[A-Za-z0-9_-]+\.js$/.test(name));
  if (candidates.length !== 1) {
    throw new Error(`expected one ${PACKAGE_NAME} transport bundle, found ${candidates.length}`);
  }
  const target = path.join(distDir, candidates[0]);
  const targetIdentity = await inspectRegularFile(target, "transport bundle");
  await revalidateDirectory(pluginDir, pluginIdentity, "plugin directory");
  await revalidateDirectory(distDir, distIdentity, "plugin dist directory");
  return { distDir, distIdentity, pluginDir, pluginIdentity, target, targetIdentity };
}

async function writeAtomically(resolved, content) {
  // The role stops the managed gateway before calling this mutation path. The
  // identity checks fail closed on accidental replacement, but Node does not
  // expose descriptor-relative renameat2: this is not a security boundary
  // against an uncoordinated process intentionally writing as container uid 1000.
  const { distDir, distIdentity, pluginDir, pluginIdentity, target, targetIdentity } = resolved;
  const temporary = path.join(
    distDir,
    `.${path.basename(target)}.openclaw-backport-${process.pid}-${randomUUID()}`,
  );
  let handle;
  try {
    handle = await open(temporary, "wx", 0o600);
    await handle.writeFile(content, "utf8");
    await handle.sync();
    await handle.chmod(0o644);
    await handle.close();
    handle = undefined;
    await revalidateDirectory(pluginDir, pluginIdentity, "plugin directory");
    await revalidateDirectory(distDir, distIdentity, "plugin dist directory");
    const currentTarget = await inspectRegularFile(target, "transport bundle");
    if (!sameIdentity(currentTarget, targetIdentity)) {
      throw new Error("transport bundle changed before atomic replacement");
    }
    await rename(temporary, target);
    await revalidateDirectory(pluginDir, pluginIdentity, "plugin directory");
    await revalidateDirectory(distDir, distIdentity, "plugin dist directory");
    const publishedIdentity = await inspectRegularFile(target, "published transport bundle");
    const published = await readPinnedFile(target, publishedIdentity, "published transport bundle");
    if (published !== content) {
      throw new Error("published transport bundle does not match the requested content");
    }
    const directory = await open(distDir, "r");
    try {
      await directory.sync();
    } finally {
      await directory.close();
    }
  } finally {
    await handle?.close();
    await rm(temporary, { force: true });
  }
}

async function reconcile(pluginDir, action, checkOnly = false, dataRoot = DATA_ROOT) {
  const resolved = await resolveTarget(pluginDir, dataRoot);
  const source = await readPinnedFile(
    resolved.target,
    resolved.targetIdentity,
    "transport bundle",
  );
  const sourceSha256 = sha256(source);

  if (![SOURCE_SHA256, PATCHED_SHA256].includes(sourceSha256)) {
    throw new Error(`refusing to patch an unknown Codex transport bundle: sha256=${sourceSha256}`);
  }

  if (action === "apply") {
    if (sourceSha256 === PATCHED_SHA256) {
      validatePatched(source);
      return { action, changed: false, path: resolved.target, sha256: sourceSha256 };
    }
    validatePristine(source);
    const patched = applyBackport(source);
    validatePatched(patched);
    const patchedSha256 = sha256(patched);
    if (patchedSha256 !== PATCHED_SHA256) {
      throw new Error(`generated backport does not match its pinned digest: sha256=${patchedSha256}`);
    }
    if (!checkOnly) {
      await writeAtomically(resolved, patched);
    }
    return { action, changed: true, path: resolved.target, sha256: patchedSha256 };
  }

  if (sourceSha256 === SOURCE_SHA256) {
    validatePristine(source);
    return { action, changed: false, path: resolved.target, sha256: sourceSha256 };
  }
  validatePatched(source);
  const pristine = revertBackport(source);
  validatePristine(pristine);
  const pristineSha256 = sha256(pristine);
  if (pristineSha256 !== SOURCE_SHA256) {
    throw new Error(`reverted bundle does not match its pinned digest: sha256=${pristineSha256}`);
  }
  if (!checkOnly) {
    await writeAtomically(resolved, pristine);
  }
  return { action, changed: true, path: resolved.target, sha256: pristineSha256 };
}

async function main() {
  if (
    ![4, 5].includes(process.argv.length) ||
    !["apply", "revert"].includes(process.argv[3]) ||
    (process.argv.length === 5 && process.argv[4] !== "--check")
  ) {
    throw new Error(
      "usage: openclaw-codex-v2026.9.1-registration-backport.mjs " +
        "PLUGIN_DIR apply|revert [--check]",
    );
  }
  const result = await reconcile(process.argv[2], process.argv[3], process.argv[4] === "--check");
  console.log(JSON.stringify({ ...result, upstreamCommit: UPSTREAM_COMMIT }));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}

export {
  applyBackport,
  inspectDirectory,
  inspectRegularFile,
  reconcile,
  replacements,
  resolveTarget,
  revertBackport,
  validatePatched,
  validatePristine,
};
