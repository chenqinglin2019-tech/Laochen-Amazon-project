import test from "node:test";
import assert from "node:assert/strict";
import { browserDiscoveryBudget, registryPageBindingDigest } from "./cdp-cli.mjs";

test("browser acquisition shares pages and unique cards with the same purpose version", () => {
  const task = { discovery_budget_revision: "discovery-purpose-budget-v1" };
  const base = { action_purpose: "discovery", discovery_intent_id: "INT-lock",
    refinement_round: 0, operation: "patent_recall", discovery_role: "browser_fallback" };
  const api = { ...base, query_id: "Q-A", discovery_role: "primary" };
  const browser = { ...base, query_id: "Q-B" };
  const nextVersion = { ...base, query_id: "Q-C", refinement_round: 1 };
  const plan = { queries: { serper_patents: [api], uspto_patent_browser: [browser, nextVersion] } };
  const run = (provider, row, id, pages, status = "success") => ({ run_id: id, provider,
    query_id: row.query_id, plan_entry_sha256: registryPageBindingDigest(row),
    status, metadata: { search_coverage: { pages_retrieved: pages } } });
  const cards = Array.from({ length: 57 }, (_, i) => ({ source_record_sha256: String(i).padStart(64, "0") }));
  const evidence = { source_runs: [run("serper_patents", api, "RUN-A", 5),
    run("uspto_patent_browser", browser, "RUN-B", 2),
    run("uspto_patent_browser", nextVersion, "RUN-C", 1),
    run("uspto_patent_browser", browser, "RUN-UNKNOWN", 0, "failed")],
  collections: { patents: [{ source_run_id: "RUN-B", payload: { candidates: cards } }] } };
  const remaining = browserDiscoveryBudget(task, plan, evidence, browser);
  assert.equal(remaining.pagesAcquired, 7);
  assert.equal(remaining.remainingPages, 1);
  assert.equal(remaining.browserCandidatesAcquired, 57);
  assert.equal(remaining.remainingCandidates, 0);
  assert.equal(browserDiscoveryBudget(task, plan, evidence, nextVersion).remainingPages, 7);
});
