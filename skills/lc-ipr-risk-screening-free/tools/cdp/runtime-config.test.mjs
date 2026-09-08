import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { loadConfig } from "./cdp-cli.mjs";

async function fixture(t) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "ipr-browser-config-"));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  await fs.mkdir(path.join(root, "references"));
  return root;
}

test("browser loads runtime settings without opening credential files", async (t) => {
  const root = await fixture(t);
  const runtime = { cdp: { operation_timeout_ms: 1000 }, providers: { fixture: {} } };
  await fs.writeFile(path.join(root, "references", "runtime-config.json"), JSON.stringify(runtime));
  // Directories make accidental credential reads fail, even in privileged tests.
  await fs.mkdir(path.join(root, "config.json"));
  await fs.mkdir(path.join(root, ".env"));
  await fs.mkdir(path.join(root, "config.local.json"));
  assert.deepEqual(await loadConfig(root), runtime);
});

test("missing runtime settings never fall back to credential or legacy config", async (t) => {
  const root = await fixture(t);
  await fs.writeFile(path.join(root, "config.json"), JSON.stringify({ cdp: {}, backend_token: "fixture-only" }));
  await fs.writeFile(path.join(root, "config.local.json"), JSON.stringify({ cdp: {} }));
  await assert.rejects(loadConfig(root), /RUNTIME_CONFIG_INVALID/);
});

test("invalid runtime settings report no file contents", async (t) => {
  const root = await fixture(t);
  for (const contents of ["fixture-secret malformed json", "null", "[]", "\"fixture-secret\""]) {
    await fs.writeFile(path.join(root, "references", "runtime-config.json"), contents);
    await assert.rejects(loadConfig(root), (error) => {
      assert.match(error.message, /RUNTIME_CONFIG_INVALID/);
      assert.doesNotMatch(error.message, /fixture-secret/);
      return true;
    });
  }
});
