import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";

import {
  ACTIVE_FREE_POLICY,
  FREE_POLICY_REVISION,
  assertCandidateInvocationMatches,
  assertActiveTaskPayload,
  assertCdpProviderAllowed,
  assertPlanMatchesTask,
  assertRegistrySearchAttestation,
  assertTaskRoute,
  browserRouteGate,
  browserPlannedQuery,
  browserResultCoverage,
  acceptedBrowserRoute,
  classifyBrowserAccess,
  executionReceipt,
  rejectManualBusinessCapture,
  submitSearch,
  observeAfterSubmission,
  operationTimeout,
  withOperationDeadline,
  releaseOwnedPage,
  candidateCdpCommand,
  candidatePlanInputs,
  currentRegistryTermsReview,
  detectChallenge,
  explicitNoResult,
  extractPatentClassifications,
  extractTsdrClassifications,
  extractTsdrDesignCodes,
  formatTmQuery,
  jpoVerificationAlreadyComplete,
  patentBasicSearchTerm,
  parsePatentRows,
  parseRegistryRows,
  parseTrademarkRows,
  plannedQueryCapturePaths,
  registryFilterAttestation,
  registryCaptureCommand,
  registryRecordCaptureCommand,
  registryPlannedFilters,
  renderedPatentPdfScreenshot,
  resolveExactPlanEntry,
  waitForStableSemanticState,
} from "./cdp-cli.mjs";
import { getRegistryAdapter, getAutomationCapability } from "./registry-adapters.mjs";

test("recall-integrity PPS compiler conforms to the shared Python/JS contract", async () => {
  const contract = JSON.parse(await fs.readFile(new URL("../../fixtures/ppubs-query-contract.json", import.meta.url), "utf8"));
  const task = { schema_version: "2.4-free", screening_revision: "recall-integrity-v1" };
  for (const item of contract.cases) {
    const entry = { q: item.q, strategy: item.strategy, right_type: item.right_type,
      operation: `${item.right_type}_recall`, jurisdiction: "US", filters: { field: item.field, language: "en" } };
    if (item.error) assert.throws(() => browserPlannedQuery("uspto_patent_browser", entry, task), /UNSUPPORTED_QUERY_SEMANTICS/, item.q);
    else assert.equal(browserPlannedQuery("uspto_patent_browser", entry, task).rendered_query, item.rendered, item.q);
  }
});

test("wrong US design operation is an internal pre-submit failure, not a website access failure", () => {
  const task = { schema_version: "2.4-free", screening_revision: "recall-integrity-v1" };
  const bad = { jurisdiction: "US", right_type: "design", operation: "patent_recall", q: "lid", strategy: "boolean" };
  const result = browserRouteGate(task, "uspto_patent_browser", bad, true);
  assert.equal(result.error_code, "INTERNAL_ROUTE_CONTRACT_ERROR");
  assert.equal(result.status, "failed");
  assert.equal(result.submission_state, "not_submitted");
  assert.equal(browserRouteGate(task, "uspto_patent_browser", { ...bad, operation: "design_recall" }, true), null);
});

test("title query preflight requires the existing task revision and retains strict field and language gates", () => {
  const task = { schema_version: "2.4-free", screening_revision: "recall-integrity-v1" };
  const entry = { query_id: "Q-TITLE", jurisdiction: "US", right_type: "patent", operation: "patent_recall",
    q: "lid AND strap", strategy: "boolean", filters: { field: "title", language: "en" } };
  assert.equal(browserRouteGate(task, "uspto_patent_browser", entry, true), null);
  assert.equal(browserPlannedQuery("uspto_patent_browser", entry, task).rendered_query, "(lid AND strap).TI.");
  // A pure compilation/preflight does not grant source-wide execution acceptance.
  assert.equal(browserRouteGate(task, "uspto_patent_browser", entry).status, "access_limited");
  assert.throws(() => browserPlannedQuery("uspto_patent_browser", entry), /UNSUPPORTED_QUERY_SEMANTICS/);
  const legacy = browserRouteGate({ schema_version: "2.4-free" }, "uspto_patent_browser", entry, true);
  assert.equal(legacy.error_code, "UNSUPPORTED_QUERY_SEMANTICS");
  assert.equal(legacy.submission_state, "not_submitted");
  for (const invalid of [
    { ...entry, q: "锅盖固定带" }, { ...entry, strategy: undefined },
    ...[{ field: "title", language: "ja" }, { field: "TI", language: "en" },
      { field: "locarno", language: "en" }, { field: "abstract", language: "en" },
      { field: "title", language: "en", unexpected: true }].map(filters => ({ ...entry, filters })),
  ]) {
    const result = browserRouteGate(task, "uspto_patent_browser", invalid, true);
    assert.equal(result.error_code, "UNSUPPORTED_QUERY_SEMANTICS");
    assert.equal(result.status, "failed");
    assert.equal(result.phase, "validate_plan");
    assert.equal(result.submission_state, "not_submitted");
  }
});

test("2.4 cannot convert manual registry attestation into completed business work", () => {
  assert.throws(() => rejectManualBusinessCapture({ schema_version: "2.4-free" }), /MANUAL_BUSINESS_ACTION_FORBIDDEN/);
  assert.doesNotThrow(() => rejectManualBusinessCapture({ schema_version: "2.3-free" }));
});

test("2.4 maps workflow text filters without inventing structured/phonetic coverage", () => {
  const tm = { q: "TEST", right_type: "trademark_word", operation: "trademark_recall", jurisdiction: "US", filters: { field: "brand", language: "en" } };
  assert.deepEqual(browserPlannedQuery("uspto_tmsearch_browser", tm), {
    rendered_query: '\"TEST\"', strategy: "phrase", semantics: "lexical_phrase", requested_field: "brand", language_filter_applied: false,
  });
  for (const field of ["phonetic", "nice", "owner", "figurative_classification", "unexpected"]) {
    assert.equal(browserRouteGate({ schema_version: "2.4-free" }, "uspto_tmsearch_browser", { ...tm, filters: { field } }, true).error_code, "UNSUPPORTED_QUERY_SEMANTICS");
  }
  const patent = { ...tm, right_type: "patent", operation: "patent_recall", filters: { field: "structural_feature", language: "en" } };
  assert.deepEqual(browserPlannedQuery("uspto_patent_browser", patent), {
    rendered_query: '"TEST"', strategy: "advanced_literal_phrase", semantics: "advanced_literal_phrase",
    requested_field: "structural_feature", language_filter_applied: false,
  });
  assert.throws(
    () => browserPlannedQuery("uspto_patent_browser", { ...patent, q: "硅胶锅盖固定带" }),
    /English USPTO query contains CJK text/,
  );
  for (const field of ["ipc", "cpc", "owner", "applicant", "locarno"]) {
    assert.throws(() => browserPlannedQuery("uspto_patent_browser", { ...patent, filters: { field } }), /UNSUPPORTED_QUERY_SEMANTICS/);
  }
});

test("planned-query retries retain distinct screenshot and capture artifacts", () => {
  const first = plannedQueryCapturePaths("/tmp/run", "uspto_patent_browser", "QRY-1", "attempt-a");
  const second = plannedQueryCapturePaths("/tmp/run", "uspto_patent_browser", "QRY-1", "attempt-b");
  assert.match(first.screenshotPath, /uspto_patent_browser-QRY-1-attempt-a\.png$/);
  assert.match(first.capturePath, /uspto_patent_browser-QRY-1-attempt-a-capture\.json$/);
  assert.notEqual(first.screenshotPath, second.screenshotPath);
  assert.notEqual(first.capturePath, second.capturePath);
});

test("2.4 browser capability is route-scoped and an acceptance probe cannot override prohibited or absent adapters", () => {
  const task = { schema_version: "2.4-free" };
  const entry = { jurisdiction: "US", right_type: "patent", operation: "patent_recall", query_id: "Q1", q: "holder" };
  assert.equal(browserRouteGate(task, "uspto_patent_browser", entry).status, "access_limited");
  assert.equal(browserRouteGate(task, "uspto_patent_browser", entry, true), null);
  assert.equal(browserRouteGate(task, "uspto_patent_browser", { ...entry, jurisdiction: "JP" }, true).status, "access_limited");
  for (const provider of ["epo_register_browser", "wipo_branddb", "euipo_esearch_browser", "tmview_browser", "designview_browser"]) {
    assert.equal(browserRouteGate(task, provider, entry, true).error_code, "AUTOMATION_PROHIBITED");
  }
  assert.equal(browserRouteGate(task, "jplatpat_browser", { ...entry, jurisdiction: "JP" }, true).error_code, "AUTOMATION_NOT_VALIDATED");
  assert.equal(getAutomationCapability({ provider: "official_registry_browser", jurisdiction: "DE", rightType: "design", operation: "candidate_verification" }).status, "unvalidated");
  assert.equal(browserRouteGate({ schema_version: "2.3-free" }, "jplatpat_browser", entry), null);
});

test("automatic submission receipt is emitted only after verified input and actual submission", async () => {
  let filled = "", clicks = 0;
  const input = { isVisible: async () => true, fill: async (v) => { filled = v; }, inputValue: async () => filled };
  const button = { isVisible: async () => true, click: async () => { clicks++; } };
  const page = { url: () => "https://tmsearch.uspto.gov/", locator: (selector) => ({
    count: async () => 1, nth: () => selector.startsWith("input") ? input : button,
  }) };
  const result = await submitSearch(page, '"TEST"');
  assert.equal(clicks, 1);
  assert.equal(result.input_value, '"TEST"');
  assert.equal(result.action, "submit_query");
  input.inputValue = async () => "stale query";
  await assert.rejects(() => submitSearch(page, "OTHER"), /AUTOMATIC_QUERY_INPUT_MISMATCH/);
  assert.equal(clicks, 1);
});

test("PPUBS advanced search binds the Trix editor instead of the short quick-lookup field", async () => {
  let editorValue = "", quickLookupFills = 0, clicks = 0;
  const editor = {
    isVisible: async () => true, waitFor: async () => {}, click: async () => {},
    press: async () => { editorValue = ""; },
    pressSequentially: async (value) => { editorValue = value; },
    textContent: async () => editorValue,
  };
  const button = { isVisible: async () => true, isEnabled: async () => true, click: async () => { clicks++; } };
  const quickLookup = { isVisible: async () => true, fill: async () => { quickLookupFills++; } };
  const page = {
    url: () => "https://ppubs.uspto.gov/basic/",
    waitForTimeout: async () => {},
    locator: (selector) => ({
      "trix-editor.trix[aria-label='Enter query text']": editor,
      "#search-btn-search": button,
      "#quickLookupTextInput": quickLookup,
    }[selector] || { isVisible: async () => false }),
  };
  const result = await submitSearch(page, "silicone lid strap", "uspto_patent_browser");
  assert.equal(result.submit_method, "ppubs_advanced_search");
  assert.equal(editorValue, "silicone lid strap");
  assert.equal(quickLookupFills, 0);
  assert.equal(clicks, 1);
});

test("PPUBS validates the controlled advanced editor before submission", async () => {
  let clicks = 0;
  const editor = {
    isVisible: async () => true, waitFor: async () => {}, click: async () => {}, press: async () => {},
    pressSequentially: async () => {}, textContent: async () => "stale value",
  };
  const button = { isVisible: async () => true, isEnabled: async () => true, click: async () => { clicks++; } };
  const page = { url: () => "https://ppubs.uspto.gov/basic/", waitForTimeout: async () => {},
    locator: (selector) => ({ "trix-editor.trix[aria-label='Enter query text']": editor, "#search-btn-search": button }[selector]) };
  await assert.rejects(() => submitSearch(page, "expected value", "uspto_patent_browser"), /AUTOMATIC_QUERY_INPUT_MISMATCH/);
  assert.equal(clicks, 0);
});

test("execution receipt binds plan contents and observed results without asserting global acceptance", () => {
  const entry = { query_id: "Q1", q: "日本語", jurisdiction: "US", right_type: "patent", operation: "patent_recall" };
  const capture = { status: "success", checked_at: "2026-09-06T00:00:00Z", final_url: "https://ppubs.uspto.gov/", candidates: [{ record_number: "US1234567B2" }] };
  const receipt = executionReceipt({ task_id: "T1" }, "uspto_patent_browser", entry, [], capture);
  assert.equal(receipt.mode, "automatic");
  assert.equal(receipt.business_actions_by, "agent");
  assert.notEqual(receipt.plan_entry_sha256, executionReceipt({ task_id: "T1" }, "uspto_patent_browser", { ...entry, q: "changed" }, [], capture).plan_entry_sha256);
  assert.notEqual(receipt.result_sha256, executionReceipt({ task_id: "T1" }, "uspto_patent_browser", entry, [], { ...capture, candidates: [] }).result_sha256);
  assert.equal(receipt.accepted, undefined);
});

test("2.4 only asks the user for actual access verification, not generic access denial", () => {
  assert.equal(classifyBrowserAccess("https://example.test/", "Forbidden", "Access denied"), "access_limited");
  assert.equal(classifyBrowserAccess("https://example.test/", "", "Verify you are human CAPTCHA"), "needs_user_action");
  assert.equal(classifyBrowserAccess("https://example.test/login", "", ""), "needs_user_action");
  assert.equal(classifyBrowserAccess("https://example.test/", "Results", "No results found"), null);
});

test("route acceptance requires matching task, exact route, intact execution evidence, and original plan", async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "ipr-browser-acceptance-"));
  try {
    const task = { task_id: "T1", schema_version: "2.4-free" };
    const entry = { query_id: "Q1", q: "test", jurisdiction: "US", right_type: "patent", operation: "patent_recall" };
    const provider = "uspto_patent_browser";
    const screenshot = path.join(dir, "screenshots", "result.png");
    const receiptPath = path.join(dir, "raw", "browser-execution", "receipt.json");
    await fs.mkdir(path.dirname(screenshot), { recursive: true });
    await fs.mkdir(path.dirname(receiptPath), { recursive: true });
    await fs.writeFile(screenshot, "test screenshot fixture");
    const digest = (bytes) => crypto.createHash("sha256").update(bytes).digest("hex");
    const at = new Date().toISOString();
    const events = [{ action: "submit_query", actor: "agent", at, rendered_query: "test", input_value: "test" },
      { action: "observe_result", actor: "agent", stable: true, at, screenshot_sha256: digest(await fs.readFile(screenshot)) }];
    const receipt = executionReceipt(task, provider, entry, events,
      { status: "success", checked_at: at, final_url: "https://ppubs.uspto.gov/", candidates: [{ record_number: "US1234567B2" }] });
    await fs.writeFile(receiptPath, JSON.stringify(receipt));
    await fs.writeFile(path.join(dir, "search-plan.json"), JSON.stringify({ queries: { [provider]: [entry] } }));
    await fs.writeFile(path.join(dir, "browser-route-acceptance.json"), JSON.stringify({ task_id: task.task_id,
      routes: [{ provider, ...entry, screenshot_path: screenshot,
        query_execution: { path: receiptPath, sha256: digest(await fs.readFile(receiptPath)) } }] }));
    assert.equal(await acceptedBrowserRoute(dir, task, provider, entry), true);
    assert.equal(await acceptedBrowserRoute(dir, { ...task, task_id: "OTHER" }, provider, entry), false);
    assert.equal(await acceptedBrowserRoute(dir, task, provider, { ...entry, right_type: "design" }), false);
    await fs.writeFile(screenshot, "changed");
    assert.equal(await acceptedBrowserRoute(dir, task, provider, entry), false);
  } finally { await fs.rm(dir, { recursive: true, force: true }); }
});

function activeTask() {
  return {
    schema_version: "2.3-free",
    task_id: "TASK-CDP",
    free_policy: { ...ACTIVE_FREE_POLICY },
    free_policy_revision: FREE_POLICY_REVISION,
    coverage_requirements: [{
      requirement_id: "COV-US-PATENT-RECALL",
      jurisdiction: "US",
      right_type: "patent",
      routes: [{ provider: "uspto_patent_browser", operation: "patent_recall" }],
    }],
  };
}

test("rejects legacy tasks, mutated free policy, mismatched plans, and unplanned routes before CDP", () => {
  assert.throws(() => assertActiveTaskPayload({ schema_version: "2.2-free" }), /LEGACY_TASK_READ_ONLY/);
  assert.doesNotThrow(() => assertActiveTaskPayload({
    ...activeTask(),
    free_policy: JSON.parse(JSON.stringify(ACTIVE_FREE_POLICY)),
  }));
  for (const [key, value] of Object.entries(ACTIVE_FREE_POLICY)) {
    const mutated = JSON.parse(JSON.stringify(ACTIVE_FREE_POLICY));
    mutated[key] = Array.isArray(value)
      ? [...value, "not-authorized"]
      : typeof value === "boolean"
        ? !value
        : `${value}-mutated`;
    assert.throws(
      () => assertActiveTaskPayload({ ...activeTask(), free_policy: mutated }),
      /FREE_POLICY_INVALID/,
      `mutated policy field should fail: ${key}`,
    );
  }
  assert.throws(
    () => assertPlanMatchesTask(activeTask(), {
      schema_version: "2.3-free", task_id: "OTHER", free_policy: { ...ACTIVE_FREE_POLICY },
      free_policy_revision: FREE_POLICY_REVISION,
    }),
    /SEARCH_PLAN_IDENTITY_MISMATCH/,
  );
  assert.doesNotThrow(() => assertTaskRoute(
    activeTask(), "uspto_patent_browser", "patent_recall", "US", "patent",
  ));
  assert.throws(() => assertTaskRoute(
    activeTask(), "uspto_patent_browser", "candidate_verification", "US", "patent",
  ), /PROVIDER_OPERATION_NOT_CONFIGURED/);
});

test("accepts the frozen default-discovery revision without migrating it", () => {
  const frozenPolicy = {
    mode: "official_free_only",
    allow_registration: true,
    allow_commercial_freemium: true,
    commercial_freemium_mode: "default_bounded",
    commercial_freemium_default_enabled: ["serper", "signa"],
    commercial_freemium_opt_in: ["serpapi"],
    commercial_freemium_allowlist: ["serper", "signa", "serpapi"],
    allow_paid: false,
    allow_overage: false,
    on_quota_exhausted: "stop_and_report",
  };
  const task = {
    ...activeTask(),
    free_policy: frozenPolicy,
    free_policy_revision: "default-discovery-v1",
  };
  assert.doesNotThrow(() => assertActiveTaskPayload(task));
  assert.doesNotThrow(() => assertPlanMatchesTask(task, {
    schema_version: task.schema_version,
    task_id: task.task_id,
    free_policy: JSON.parse(JSON.stringify(frozenPolicy)),
    free_policy_revision: "default-discovery-v1",
  }));
});

test("resolves one exact candidate action and routes every official CDP verifier", () => {
  const base = {
    operation: "candidate_verification",
    candidate_id: "CAND-1",
    requirement_ids: ["COV-VERIFY"],
  };
  const cases = [
    ["uspto_patent_browser", "US", "design", "USD1132316S1", "record_number", "verify-candidate"],
    ["uspto_tsdr", "US", "trademark_figurative", "99123456", "serial_number", "verify-candidate"],
    ["official_registry_browser", "DE", "design", "DE402024000001", "record_number", "open-registry"],
    ["jplatpat_browser", "JP", "utility_model", "2024000123", "record_number", "open-registry"],
    ["epo_register_browser", "EU", "patent", "EP4123456A1", "record_number", "open-registry"],
  ];
  const queries = {};
  for (const [provider, jurisdiction, rightType, record, recordField, command] of cases) {
    const entry = {
      ...base,
      query_id: `QRY-${provider}`,
      q: record,
      [recordField]: record,
      jurisdiction,
      right_type: rightType,
    };
    queries[provider] = [entry];
    const inputs = candidatePlanInputs(provider, entry);
    assert.equal(inputs.record, record);
    assert.equal(inputs.candidate_id, "CAND-1");
    assert.equal(candidateCdpCommand(provider), command);
    assert.doesNotThrow(() => assertCandidateInvocationMatches({
      ...inputs, record,
    }, inputs));
  }
  const resolved = resolveExactPlanEntry({ queries }, "QRY-uspto_tsdr");
  assert.equal(resolved.provider, "uspto_tsdr");
  assert.throws(() => assertCandidateInvocationMatches({
    ...candidatePlanInputs("uspto_tsdr", resolved.entry), candidate_id: "CAND-STALE",
  }, candidatePlanInputs("uspto_tsdr", resolved.entry)), /candidate_id differs/);
});

test("rejects duplicate query ids and candidate q/record drift", () => {
  const entry = {
    query_id: "QRY-DUP", q: "99123456", serial_number: "99123456",
    candidate_id: "CAND-1", operation: "candidate_verification", jurisdiction: "US",
    right_type: "trademark_word", requirement_ids: ["COV-US-TM"],
  };
  assert.throws(() => resolveExactPlanEntry({
    queries: { uspto_tsdr: [entry], jplatpat_browser: [{ ...entry }] },
  }, "QRY-DUP"), /QUERY_ID_AMBIGUOUS/);
  assert.throws(() => candidatePlanInputs("uspto_tsdr", {
    ...entry, serial_number: "99876543",
  }), /CANDIDATE_PLAN_RECORD_MISMATCH/);
});

test("binds public candidate verification to its exact record and official source", () => {
  const entry = {
    query_id: "QRY-US-PTAB-VERIFY",
    q: "IPR2026-00123",
    record_number: "IPR2026-00123",
    candidate_id: "CAND-US-PTAB",
    operation: "candidate_verification",
    jurisdiction: "US",
    right_type: "enforcement",
    source_key: "ptab",
    requirement_ids: ["COV-US-ENFORCEMENT-VERIFY"],
  };
  const inputs = candidatePlanInputs("public_web_browser", entry);
  assert.equal(inputs.record, "IPR2026-00123");
  assert.equal(inputs.source_key, "ptab");
  assert.equal(candidateCdpCommand("public_web_browser"), "open-registry");
  assert.throws(
    () => assertCandidateInvocationMatches({ ...inputs, source_key: "ttabvue" }, inputs),
    /source_key differs/,
  );
  assert.throws(
    () => assertCandidateInvocationMatches({ ...inputs, record: "IPR202600123" }, inputs),
    /record differs/,
  );
  assert.throws(
    () => candidatePlanInputs("public_web_browser", { ...entry, source_key: "" }),
    /CANDIDATE_PLAN_SOURCE_MISSING/,
  );
  assert.throws(
    () => candidatePlanInputs("public_web_browser", {
      ...entry, q: "IPR202600123", record_number: "IPR2026-00123",
    }),
    /CANDIDATE_PLAN_RECORD_MISMATCH/,
  );
});

test("extracts official design and figurative-mark classifications without guessing", () => {
  assert.deepEqual(extractPatentClassifications([
    "Locarno Classification", "06-06", "U.S. Classification", "D06/552",
  ].join("\n")), ["06-06", "D06/552"]);
  assert.deepEqual(extractTsdrClassifications("International Class\n020"), ["020"]);
  assert.deepEqual(extractTsdrDesignCodes("Design Search Codes\n03.01.08"), ["03.01.08"]);
});

test("blocks CDP automation for WIPO, Espacenet, and optional API-only discovery providers", () => {
  assert.throws(
    () => assertCdpProviderAllowed("wipo_patentscope_browser"),
    /disabled.*legacy WIPO evidence is read-only/,
  );
  assert.throws(
    () => assertCdpProviderAllowed("espacenet_browser"),
    /use the planned EPO OPS query/,
  );
  assert.throws(
    () => assertCdpProviderAllowed("serper_patents"),
    /does not support provider/,
  );
  assert.throws(
    () => assertCdpProviderAllowed("serpapi_google_patents"),
    /does not support provider/,
  );
  assert.doesNotThrow(() => assertCdpProviderAllowed("uspto_tmsearch_browser"));
  assert.doesNotThrow(() => assertCdpProviderAllowed("uspto_patent_browser"));
});

test("formats only the supported USPTO TM Search strategies", () => {
  assert.equal(formatTmQuery("MOCK MARK", "exact"), '"MOCK MARK"');
  assert.equal(formatTmQuery("MOCK MARK", "phrase"), '"MOCK MARK"');
  assert.equal(formatTmQuery("MOCK", "prefix"), "MOCK*");
  assert.equal(formatTmQuery("03.01.08", "design_code"), "03.01.08");
  assert.throws(() => formatTmQuery("MOCK", "fuzzy"), /Unsupported/);
});

test("formats USPTO Basic Search patent numbers without country/kind wrappers", () => {
  assert.equal(patentBasicSearchTerm("US-11401089-B2"), "11401089");
  assert.equal(patentBasicSearchTerm("USD1132316S1"), "D1132316");
});

test("detects user-action challenges without treating ordinary results as challenges", () => {
  assert.equal(detectChallenge("https://example.test/captcha", "", ""), true);
  assert.equal(detectChallenge("https://example.test/results", "Search", "No records found"), false);
});

test("requires explicit zero-result wording", () => {
  assert.equal(explicitNoResult("No records found"), true);
  assert.equal(explicitNoResult("The page is still loading"), false);
});

test("extracts conservative trademark candidates from rendered rows", () => {
  const rows = [
    ["MOCKMARK", "Serial Number 78787878", "Registration Number 7654321", "Mock Inc", "Live / Registered"],
    ["Header", "Status"],
  ];
  assert.deepEqual(parseTrademarkRows(rows), [{
    serial_number: "78787878",
    registration_number: "7654321",
    mark_text: "MOCKMARK",
    owner: "Mock Inc",
    status: "Live / Registered",
    nice_classes: [],
    goods_services: [],
  }]);
});

test("extracts patent identifiers but ignores rows without an official-looking US number", () => {
  const rows = [
    ["US-D1234567-S", "Cat paw mouse pad", "Issued", "Mock Inc"],
    ["No identifier", "Other row"],
  ];
  assert.deepEqual(parsePatentRows(rows), [{
    record_number: "US-D1234567-S",
    publication_number: "US-D1234567-S",
    title: "Cat paw mouse pad",
    owners: ["Mock Inc"],
    legal_status: "Issued",
    jurisdiction: "US",
    kind_code: "S",
    material: false,
  }]);
});

test("extracts compact US design numbers and skips display-action cells", () => {
  const rows = [[
    "1", "D1132316", "Preview PDF Text", "Flexible lid-securing strap",
    "Mock Inventor", "2026-01-01", "8",
  ]];
  assert.deepEqual(parsePatentRows(rows), [{
    record_number: "D1132316",
    publication_number: "D1132316",
    title: "Flexible lid-securing strap",
    owners: [],
    legal_status: "",
    jurisdiction: "US",
    kind_code: "",
    material: false,
  }]);
});

test("waits for multiple stable semantic samples instead of a fixed delay", async () => {
  let reads = 0;
  const result = await waitForStableSemanticState(async () => {
    reads += 1;
    if (reads < 3) return { ready: false, signature: "" };
    return { ready: true, signature: "US11401089B2", value: "loaded" };
  }, { timeoutMs: 1000, pollMs: 5, stableSamples: 3 });
  assert.equal(result.stable, true);
  assert.equal(result.value, "loaded");
  assert.ok(reads >= 5);
});

test("rejects a stable but visually blank patent PDF frame", () => {
  assert.equal(renderedPatentPdfScreenshot(Buffer.alloc(24691)), false);
  assert.equal(renderedPatentPdfScreenshot(Buffer.alloc(120000)), true);
});

test("extracts one conservative Japanese registry candidate without translating its text", () => {
  const rows = [[
    "出願番号 2020008423", "管理システム及び管理方法", "特許庁長官", "登録",
  ]];
  assert.deepEqual(parseRegistryRows(rows, { rightType: "patent", jurisdiction: "JP" }), [{
    record_number: "2020008423",
    application_number: "2020008423",
    title: "管理システム及び管理方法",
    owner: "特許庁長官",
    legal_status: "登録",
    classes: [],
    jurisdiction: "JP",
    right_type: "patent",
    material: false,
  }]);
});

test("does not turn ordinary dates into registry candidate identifiers", () => {
  const rows = [["Filing date", "2024-01-23", "Updated 2026-09-03"]];
  assert.deepEqual(parseRegistryRows(rows, { rightType: "design", jurisdiction: "DE" }), []);
});

test("requires explicit registry operator attestation and rejects a stale rendered query", () => {
  const planned = {
    query_id: "QRY-REGISTRY-1",
    q: "猫工房",
    operation: "trademark_recall",
    jurisdiction: "JP",
    right_type: "trademark_figurative",
    mode: "user_assisted",
    query_mode: "figurative_classification",
    classification_scheme: "jpo_figurative_classification",
    required: true,
    requirement_ids: ["COV-JP-TM-FIG"],
  };
  const filters = {
    classification_scheme: "jpo_figurative_classification",
    query_mode: "figurative_classification",
  };
  assert.deepEqual(registryPlannedFilters(planned), filters);
  assert.equal(registryFilterAttestation(planned), JSON.stringify(filters));
  assert.throws(
    () => assertRegistrySearchAttestation(null, planned),
    /REGISTRY_OPERATOR_ATTESTATION_REQUIRED/,
  );
  const attestation = {
    query: "猫工房",
    right_type: "trademark_figurative",
    filters,
    confirmed_current_page: true,
  };
  assert.throws(
    () => assertRegistrySearchAttestation(attestation, planned, {
      extraction_attempted: true,
      query_values: ["OLD QUERY"],
      filters: {},
    }),
    /REGISTRY_RENDERED_QUERY_MISMATCH/,
  );
  assert.doesNotThrow(() => assertRegistrySearchAttestation(attestation, planned, {
    extraction_attempted: true,
    query_values: ["猫工房"],
    filters: { classification_scheme: ["JPO figurative"] },
  }));
});

test("builds a complete shell-safe registry capture command", () => {
  const command = registryCaptureCommand({
    taskDir: "/tmp/run with spaces",
    provider: "jplatpat_browser",
    queryId: "QRY-1",
    query: "O'Brien 猫",
    rightType: "trademark_word",
    filters: { query_mode: "owner's phrase" },
    cliPath: "/tmp/cdp-cli.mjs",
  });
  assert.deepEqual(command.argv.slice(-8), [
    "--attest-query", "O'Brien 猫",
    "--attest-right-type", "trademark_word",
    "--attest-filters", '{"query_mode":"owner\'s phrase"}',
    "--attest-current-page",
    "--confirm-current-terms",
  ]);
  assert.match(command.shell, /O'"'"'Brien 猫/);
  assert.match(command.shell, /owner'"'"'s phrase/);
});

test("builds a record capture command with every candidate binding", () => {
  const command = registryRecordCaptureCommand({
    taskDir: "/tmp/run with spaces",
    provider: "official_registry_browser",
    queryId: "QRY-DE-1",
    record: "DE40'2024",
    candidateId: "CAND-DE-1",
    rightType: "design",
    jurisdiction: "DE",
    cliPath: "/tmp/cdp-cli.mjs",
  });
  assert.deepEqual(command.argv.slice(-13), [
    "--provider", "official_registry_browser",
    "--query-id", "QRY-DE-1",
    "--record", "DE40'2024",
    "--candidate-id", "CAND-DE-1",
    "--right-type", "design",
    "--jurisdiction", "DE",
    "--confirm-current-terms",
  ]);
  assert.match(command.shell, /DE40'"'"'2024/);
});

test("record capture command preserves a public candidate source key", () => {
  const command = registryRecordCaptureCommand({
    taskDir: "/tmp/public-run",
    provider: "public_web_browser",
    queryId: "QRY-US-PTAB-VERIFY",
    record: "IPR2026-00123",
    candidateId: "CAND-US-PTAB",
    rightType: "enforcement",
    jurisdiction: "US",
    sourceKey: "ptab",
    cliPath: "/tmp/cdp-cli.mjs",
  });
  assert.deepEqual(command.argv.slice(-3), [
    "--source-key", "ptab", "--confirm-current-terms",
  ]);
});

test("registry live use requires and records a current operator terms confirmation", () => {
  const adapter = getRegistryAdapter("official_registry_browser", "DE", "design");
  assert.throws(
    () => currentRegistryTermsReview({}, adapter, "2026-09-04T00:00:00Z"),
    /REGISTRY_TERMS_REVIEW_REQUIRED/,
  );
  assert.deepEqual(
    currentRegistryTermsReview(
      { confirm_current_terms: true }, adapter, "2026-09-04T00:00:00Z",
    ),
    {
      schema_version: "1.0",
      terms_url: adapter.terms_url,
      checked_at: "2026-09-04T00:00:00Z",
      decision: "cdp_assisted_single_action_confirmed",
      operator_confirmed: true,
    },
  );
});

test("skips J-PlatPat only when a recent JPO verification is complete for the right type", async () => {
  const taskDir = await fs.mkdtemp(path.join(os.tmpdir(), "jpo-skip-test-"));
  try {
    const checkedAt = new Date().toISOString();
    await fs.writeFile(path.join(taskDir, "task.json"), JSON.stringify({
      schema_version: "2.3-free",
      task_id: "TASK-JPO-SKIP",
      free_policy: { ...ACTIVE_FREE_POLICY },
      free_policy_revision: FREE_POLICY_REVISION,
      coverage_requirements: [{
        requirement_id: "COV-JP-PATENT-VERIFY", jurisdiction: "JP",
        right_type: "patent", phase: "candidate_verification",
        routes: [{ provider: "jpo_api", operation: "candidate_verification" }],
      }],
    }));
    await fs.writeFile(path.join(taskDir, "normalized-candidates.json"), JSON.stringify({
      patents: [{
        candidate_id: "CAND-PATENT",
        right_type: "patent",
        application_number: "2020008423",
        verification_refs: ["EV-JPO-PATENT"],
        official_verification: {
          status: "verified",
          authority: "Japan Patent Office (JPO)",
          identity_match: true,
          owner: ["権利者"],
          legal_status: "registered",
          classes: [],
          updated_date: "2026-09-03",
          url: "https://www.j-platpat.inpit.go.jp/c1801/PU/JP-2020008423/15/ja",
          checked_at: checkedAt,
          media: [],
        },
      }, {
        candidate_id: "CAND-DESIGN",
        right_type: "design",
        application_number: "2020008424",
        official_verification: {
          status: "verified",
          source: "JPO Patent Information Retrieval API",
          identity_match: true,
          owner: ["権利者"],
          legal_status: "registered",
          classes: ["design:C3-123"],
          updated_date: "2026-09-03",
          url: "https://www.j-platpat.inpit.go.jp/c1801/DE/JP-2020008424/15/ja",
          checked_at: checkedAt,
          media: [],
        },
      }],
      trademarks: [],
    }));
    await fs.writeFile(path.join(taskDir, "evidence.json"), JSON.stringify({
      source_runs: [{
        run_id: "RUN-JPO-PATENT", provider: "jpo_api",
        operation: "candidate_verification", status: "success", jurisdiction: "JP",
        right_type: "patent", requirement_ids: ["COV-JP-PATENT-VERIFY"],
      }],
      collections: { official_verifications: [{
        evidence_id: "EV-JPO-PATENT", source_run_id: "RUN-JPO-PATENT",
        provider: "jpo_api", operation: "candidate_verification", jurisdiction: "JP",
        right_type: "patent", requirement_ids: ["COV-JP-PATENT-VERIFY"],
        payload: {
          candidate_id: "CAND-PATENT", right_type: "patent",
          application_number: "2020008423",
          official_verification: {
            status: "verified", authority: "Japan Patent Office (JPO)",
            identity_match: true, owner: ["権利者"], legal_status: "registered",
            classes: [], updated_date: "2026-09-03",
            url: "https://www.j-platpat.inpit.go.jp/c1801/PU/JP-2020008423/15/ja",
            checked_at: checkedAt, media: [],
          },
        },
      }] },
    }));
    assert.equal(await jpoVerificationAlreadyComplete(
      taskDir, "patent", "CAND-PATENT", "2020008423",
    ), true);
    assert.equal(await jpoVerificationAlreadyComplete(
      taskDir, "design", "CAND-DESIGN", "2020008424",
    ), false);
  } finally {
    await fs.rm(taskDir, { recursive: true, force: true });
  }
});

test("rendered result coverage records totals and truncation without claiming exhaustive recall", () => {
  assert.equal(browserResultCoverage("Results 1-25 of 1,203", 25).reported_total, 1203);
  assert.equal(browserResultCoverage("Results 1-25 of 1,203", 25).total_hits, 1203);
  assert.equal(browserResultCoverage("Results 1-25 of 1,203", 25).retrieved_hits, 25);
  assert.equal(browserResultCoverage("No results found", 0).schema_valid, true);
  assert.equal(browserResultCoverage("No results found", 0).stop_reason, "zero_results");
  assert.equal(browserResultCoverage("Results 1-25 of 1,203", 25).truncated, true);
  assert.equal(browserResultCoverage("No results found", 0).truncated, false);
  assert.equal(browserResultCoverage("25 results found", 25).completeness, "unknown");
  assert.equal(browserResultCoverage("Some results", 25).truncated, null);
});

test("MFA and access consent are recoverable access actions", () => {
  assert.equal(classifyBrowserAccess("https://example.test/", "", "Enter the verification code"), "needs_user_action");
  assert.equal(classifyBrowserAccess("https://example.test/", "", "Access consent required"), "needs_user_action");
});


test("known pre-submit failure skips semantic waiting but uncertain submission is observed", async () => {
  let observations = 0;
  const page = { url: () => "https://example.test/search", title: async () => "Search",
    locator: () => ({ innerText: async () => "Search page" }) };
  const observe = async () => { observations += 1; return { stable: true }; };
  const start = Date.now();
  const skipped = await observeAfterSubmission(page, "uspto_patent_browser", 45000, {},
    { submission_state: "not_submitted" }, observe);
  assert.equal(skipped.skipped, "not_submitted");
  assert.equal(observations, 0);
  assert.ok(Date.now() - start < 1000);
  await observeAfterSubmission(page, "uspto_patent_browser", 45000, {},
    { submission_state: "uncertain" }, observe);
  assert.equal(observations, 1);
});

test("one operation deadline shrinks stage budgets and terminates an unresolved stage", async () => {
  assert.equal(operationTimeout(45000, 5000, 4900), 100);
  assert.throws(() => operationTimeout(45000, 5000, 5000), /OPERATION_DEADLINE_EXCEEDED/);
  await assert.rejects(() => withOperationDeadline(async () => new Promise(() => {}), Date.now() + 25), /OPERATION_DEADLINE_EXCEEDED/);
  await assert.rejects(() => withOperationDeadline(async () => "unused", NaN), /OPERATION_DEADLINE_EXCEEDED/);
});

test("automatic page cleanup never closes unowned pages or access verification pages", async () => {
  let closes = 0;
  const page = { close: async () => { closes += 1; } };
  assert.equal(await releaseOwnedPage(page, false, null), false);
  assert.equal(await releaseOwnedPage(page, true, "needs_user_action"), false);
  assert.equal(closes, 0);
  assert.equal(await releaseOwnedPage(page, true, "access_limited"), true);
  assert.equal(closes, 1);
});


test("operation deadline interrupts a blocked semantic snapshot and prevents later capture stage", async () => {
  let captured = false;
  const start = Date.now();
  await assert.rejects(() => withOperationDeadline(async () => {
    await waitForStableSemanticState(async () => new Promise(() => {}), { timeoutMs: 45000 });
    captured = true;
  }, Date.now() + 25), /OPERATION_DEADLINE_EXCEEDED/);
  assert.equal(captured, false);
  assert.ok(Date.now() - start < 1000);
});


test("expired async work cannot regain a new budget after the outer deadline returns", async () => {
  let captured = false;
  await assert.rejects(() => withOperationDeadline(async () => {
    await waitForStableSemanticState(async () => {
      await new Promise(resolve => setTimeout(resolve, 50));
      return { ready: true, signature: "late" };
    }, { timeoutMs: 45000, stableSamples: 1 });
    operationTimeout(1); // The same guard used before capture/receipt/journal writes.
    captured = true;
  }, Date.now() + 15), /OPERATION_DEADLINE_EXCEEDED/);
  await new Promise(resolve => setTimeout(resolve, 70));
  assert.equal(captured, false);
  assert.equal(await withOperationDeadline(async () => "next operation", Date.now() + 100), "next operation");
});
