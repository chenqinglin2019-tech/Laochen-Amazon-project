import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const TOOL_DIR = path.dirname(fileURLToPath(import.meta.url));
const SCRIPTS_DIR = path.resolve(TOOL_DIR, "..", "..", "scripts");
const PYTHON_ENV = {
  ...process.env, PYTHONPATH: SCRIPTS_DIR,
  LC_IPR_OFFLINE_TESTS: "1", PYTHONDONTWRITEBYTECODE: "1",
};

function check(taskDir, values) {
  const script = `
import json, sys
from pathlib import Path
from common import load_json
from provider_utils import ProviderError, authorize_exact_plan_execution
args = json.loads(sys.argv[2])
try:
    row = authorize_exact_plan_execution(
        Path(sys.argv[1]), load_json(Path(sys.argv[1]) / "task.json"),
        args["provider"], args["operation"], args.get("query_id", ""),
        jurisdiction=args["jurisdiction"], right_type=args["right_type"],
        query=args["query"], request_params=args["request_params"],
    )
except ProviderError as exc:
    print(exc.code)
    raise SystemExit(3)
print(row["query_id"])
`;
  return spawnSync("python3", ["-c", script, taskDir, JSON.stringify(values)], {
    encoding: "utf8", env: PYTHON_ENV,
  });
}

test("official API execution requires one exact immutable plan row", async () => {
  const taskDir = await fs.mkdtemp(path.join(os.tmpdir(), "ipr-api-plan-binding-"));
  try {
    const freePolicy = {
      mode: "official_free_only", allow_registration: true,
      allow_commercial_freemium: true,
      commercial_freemium_mode: "explicit_opt_in",
      commercial_freemium_allowlist: ["serper"],
      allow_paid: false, allow_overage: false,
      on_quota_exhausted: "stop_and_report",
    };
    await fs.writeFile(path.join(taskDir, "task.json"), JSON.stringify({
      schema_version: "2.3-free", task_id: "TASK-API-BIND", free_policy: freePolicy,
    }));
    const row = {
      query_id: "QRY-EPO-EXACT", q: "pn=US* and ta=mouse", range: "1-25",
      operation: "search", jurisdiction: "US", right_type: "patent",
      required: true, required_for: "low_risk",
      requirement_ids: ["COV-US-PATENT-RECALL"], wave: 1,
      derived_from: ["fixture"],
    };
    await fs.writeFile(path.join(taskDir, "search-plan.json"), JSON.stringify({
      schema_version: "2.3-free", task_id: "TASK-API-BIND", free_policy: freePolicy,
      queries: { epo_ops: [row] },
    }));
    const valid = {
      provider: "epo_ops", operation: "search", query_id: row.query_id,
      jurisdiction: "US", right_type: "patent", query: row.q,
      request_params: { q: row.q, range: "1-25", right_type: "patent" },
    };
    const accepted = check(taskDir, valid);
    assert.equal(accepted.status, 0, accepted.stderr);
    assert.match(accepted.stdout, /QRY-EPO-EXACT/);
    for (const [mutation, code] of [
      [{ query_id: "" }, "QUERY_ID_REQUIRED"],
      [{ request_params: { ...valid.request_params, range: "26-50" } }, "QUERY_PLAN_PARAMETERS_MISMATCH"],
      [{ jurisdiction: "JP" }, "QUERY_PLAN_SCOPE_MISMATCH"],
      [{ provider: "jpo_api" }, "QUERY_ID_PROVIDER_MISMATCH"],
    ]) {
      const rejected = check(taskDir, { ...valid, ...mutation });
      assert.equal(rejected.status, 3, rejected.stderr);
      assert.match(rejected.stdout, new RegExp(code));
    }
  } finally {
    await fs.rm(taskDir, { recursive: true, force: true });
  }
});
