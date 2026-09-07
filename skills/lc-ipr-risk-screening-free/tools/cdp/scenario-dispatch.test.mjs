import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { assertScenarioActionDispatch } from "./cdp-cli.mjs";

test("legacy dispatch does not require the new Python authority", async () => {
  const before = process.env.LC_IPR_PYTHON;
  process.env.LC_IPR_PYTHON = "/not-present/synthetic-python";
  try {
    await assertScenarioActionDispatch("/not-used", {}, "test", { query_id: "Q1" });
    await assert.rejects(assertScenarioActionDispatch("/not-used",
      { decision_workflow_revision: "scenario-triage-v1" }, "test", { query_id: "Q1" }),
    /SCENARIO_DISPATCH_RUNTIME_UNAVAILABLE/);
  } finally {
    if (before === undefined) delete process.env.LC_IPR_PYTHON;
    else process.env.LC_IPR_PYTHON = before;
  }
});

test("direct browser entry fails closed on an unsupported explicit revision", async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "ipr-scenario-dispatch-"));
  try {
    for (const revision of ["future", "", null]) {
      const task = { decision_workflow_revision: revision };
      await fs.writeFile(path.join(directory, "task.json"), JSON.stringify(task));
      await assert.rejects(assertScenarioActionDispatch(directory, task, "test", { query_id: "Q1" }),
        /DECISION_WORKFLOW_REVISION_UNSUPPORTED/);
    }
  } finally {
    await fs.rm(directory, { recursive: true });
  }
});
