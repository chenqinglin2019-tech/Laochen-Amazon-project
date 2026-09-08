#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs/promises";
import fsSync from "node:fs";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { spawn } from "node:child_process";
import { AsyncLocalStorage } from "node:async_hooks";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "playwright-core";
import {
  assertOfficialUrl,
  assertRegistryOperation,
  directRecordUrl,
  getRegistryAdapter,
  getAutomationCapability,
  hostAllowed,
  publicRegistryCatalog,
} from "./registry-adapters.mjs";

const TOOL_DIR = path.dirname(fileURLToPath(import.meta.url));
const SKILL_DIR = path.resolve(TOOL_DIR, "..", "..");
const SENSITIVE_SESSION_KEYS = new Set([
  "cdp_endpoint", "endpoint", "websocket", "websocket_url",
  "remote_debugging_port", "profile_dir", "user_data_dir",
  "cookies", "cookie", "set-cookie", "local_storage", "localstorage",
  "authorization", "proxy-authorization", "password", "passwd", "username",
  "api_key", "apikey", "access_token", "refresh_token", "requesttoken",
  "client_id", "client_secret", "consumer_key", "consumer_secret",
]);
const SENSITIVE_URL_KEYS = new Set([
  "requesttoken", "token", "api_key", "apikey", "key", "access_token", "refresh_token",
  "client_id", "client_secret", "consumer_key", "consumer_secret", "password", "passwd",
  "username", "code", "session", "session_id",
]);
export const ACTIVE_FREE_POLICY = Object.freeze({
  mode: "official_free_only",
  allow_registration: true,
  allow_commercial_freemium: true,
  commercial_freemium_mode: "explicit_opt_in",
  commercial_freemium_default_enabled: Object.freeze([]),
  commercial_freemium_opt_in: Object.freeze(["serper", "signa", "serpapi"]),
  commercial_freemium_allowlist: Object.freeze(["serper", "signa", "serpapi"]),
  allow_paid: false,
  allow_overage: false,
  on_quota_exhausted: "stop_and_report",
});
export const FREE_POLICY_REVISION = "optional-discovery-v1";
export const AUTOMATION_POLICY_REVISION = "automation-first-v1";
export const RECALL_INTEGRITY_REVISION = "recall-integrity-v1";
const recallIntegrityEnabled = (task) => task?.screening_revision === RECALL_INTEGRITY_REVISION;
const LEGACY_DEFAULT_DISCOVERY_REVISION = "default-discovery-v1";
const LEGACY_DEFAULT_DISCOVERY_POLICY = Object.freeze({
  mode: "official_free_only",
  allow_registration: true,
  allow_commercial_freemium: true,
  commercial_freemium_mode: "default_bounded",
  commercial_freemium_default_enabled: Object.freeze(["serper", "signa"]),
  commercial_freemium_opt_in: Object.freeze(["serpapi"]),
  commercial_freemium_allowlist: Object.freeze(["serper", "signa", "serpapi"]),
  allow_paid: false,
  allow_overage: false,
  on_quota_exhausted: "stop_and_report",
});
const LEGACY_FREE_POLICIES = Object.freeze([
  Object.freeze({
    mode: "official_free_only", allow_registration: true,
    allow_commercial_freemium: true, commercial_freemium_mode: "explicit_opt_in",
    commercial_freemium_allowlist: Object.freeze(["serper"]),
    allow_paid: false, allow_overage: false, on_quota_exhausted: "stop_and_report",
  }),
  Object.freeze({
    mode: "official_free_only", allow_registration: true,
    allow_commercial_freemium: true, commercial_freemium_mode: "explicit_opt_in",
    commercial_freemium_allowlist: Object.freeze(["serper", "serpapi"]),
    allow_paid: false, allow_overage: false, on_quota_exhausted: "stop_and_report",
  }),
]);
const REGISTRY_PLAN_PROVIDERS = new Set([
  "jplatpat_browser", "tmview_browser", "designview_browser",
  "epo_register_browser", "euipo_esearch_browser",
  "official_registry_browser", "public_web_browser",
]);
const US_CANDIDATE_PROVIDERS = new Set(["uspto_patent_browser", "uspto_tsdr"]);

function samePolicy(value, expected) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const expectedKeys = Object.keys(expected).sort();
  const actualKeys = Object.keys(value).sort();
  return actualKeys.length === expectedKeys.length
    && actualKeys.every((key, index) => key === expectedKeys[index])
    && expectedKeys.every((key) => {
      const expectedValue = expected[key];
      const actual = value[key];
      if (Array.isArray(expectedValue)) {
        return Array.isArray(actual)
          && actual.length === expectedValue.length
          && actual.every((item, index) => item === expectedValue[index]);
      }
      return actual === expectedValue;
    });
}

function recognizedFreePolicy(value, revision = "") {
  if (revision === FREE_POLICY_REVISION) return samePolicy(value, ACTIVE_FREE_POLICY);
  if (revision === LEGACY_DEFAULT_DISCOVERY_REVISION) {
    return samePolicy(value, LEGACY_DEFAULT_DISCOVERY_POLICY);
  }
  if (revision) return false;
  return LEGACY_FREE_POLICIES.some((policy) => samePolicy(value, policy));
}

export function assertActiveTaskPayload(task) {
  if (!task || !["2.3-free", "2.4-free"].includes(task.schema_version)) {
    throw new Error("LEGACY_TASK_READ_ONLY: CDP network execution requires task schema 2.3-free or 2.4-free");
  }
  const policyValid = task.schema_version === "2.4-free"
    ? task.free_policy_revision === AUTOMATION_POLICY_REVISION && samePolicy(task.free_policy, ACTIVE_FREE_POLICY)
    : recognizedFreePolicy(task.free_policy, String(task.free_policy_revision || ""));
  if (!policyValid) {
    throw new Error("FREE_POLICY_INVALID: task must use its immutable recognized free policy");
  }
  if (!Array.isArray(task.coverage_requirements) || !task.coverage_requirements.length) {
    throw new Error("COVERAGE_REQUIREMENTS_MISSING: task has no operation-level coverage plan");
  }
  return task;
}

export function rejectManualBusinessCapture(task) {
  if (task?.schema_version === "2.4-free") {
    throw new Error("MANUAL_BUSINESS_ACTION_FORBIDDEN: 2.4 accepts only automatically executed, plan-bound queries; users may only complete login, CAPTCHA, MFA, access consent, or QR verification");
  }
}

export function browserRouteGate(task, provider, entry, acceptanceProbe = false) {
  if (task?.schema_version !== "2.4-free") return null;
  const capability = getAutomationCapability({
    provider, jurisdiction: entry.jurisdiction, rightType: entry.right_type, operation: entry.operation,
  });
  if (capability.executor_available) {
    try { browserPlannedQuery(provider, entry, task); }
    catch (error) {
      return { status: recallIntegrityEnabled(task) ? "failed" : "access_limited", error_code: "UNSUPPORTED_QUERY_SEMANTICS",
        phase: "validate_plan", submission_state: "not_submitted",
        browser_capability: capability, detail: String(error.message), query_id: entry.query_id, provider };
    }
    if (acceptanceProbe === true) return null;
  }
  return { status: capability.error_code === "INTERNAL_ROUTE_CONTRACT_ERROR" ? "failed" : "access_limited", error_code: capability.error_code, browser_capability: capability,
    phase: "validate_route", submission_state: "not_submitted",
    detail: capability.detail, query_id: entry.query_id, provider };
}

// Translate only the text semantics implemented by the existing US controls.
// A field label in a plan is intent; it is never evidence that a UI filter ran.
export function browserPlannedQuery(provider, entry, task = {}) {
  const value = String(entry.q || entry.query || "").trim();
  if (!value) throw new Error("UNSUPPORTED_QUERY_SEMANTICS: empty planned query");
  const filters = entry.filters || {};
  if (typeof filters !== "object" || Array.isArray(filters)
      || Object.keys(filters).some((key) => !["field", "language"].includes(key))) {
    throw new Error("UNSUPPORTED_QUERY_SEMANTICS: unimplemented browser filters");
  }
  const field = String(filters.field || "");
  const language = String(filters.language || "").toLowerCase();
  if (language && !["en", "en-us", "english"].includes(language)) {
    throw new Error("UNSUPPORTED_QUERY_SEMANTICS: US browser executor has not validated this query language");
  }
  if (["en", "en-us", "english"].includes(language) && /[\u3040-\u30ff\u3400-\u9fff]/.test(value)) {
    throw new Error("UNSUPPORTED_QUERY_SEMANTICS: an English USPTO query contains CJK text and must be replaced by an evidenced English term");
  }
  if (entry.operation === "candidate_verification") {
    if (field && !["record_number", "publication_number", "serial_number"].includes(field)) {
      throw new Error("UNSUPPORTED_QUERY_SEMANTICS: candidate verification requires a known record number");
    }
    if (recallIntegrityEnabled(task) && provider === "uspto_patent_browser"
        && !/^(?:US)?(?:D\d{6,8}(?:S\d?)?|\d{6,11}(?:[AB]\d?)?|(?:RE|PP)\d{5,8}(?:[A-Z]\d?)?)$/.test(cleanNumber(value))) {
      throw new Error("UNSUPPORTED_QUERY_SEMANTICS: malformed known US record number");
    }
    if (recallIntegrityEnabled(task) && provider === "uspto_patent_browser") {
      return compilePpubsQuery({ ...entry, strategy: "record_number" }, "record_number");
    }
    return { rendered_query: provider === "uspto_patent_browser" ? patentBasicSearchTerm(value) : value,
      strategy: "record_number", semantics: "known_record", requested_field: field, language_filter_applied: false };
  }
  if (provider === "uspto_tmsearch_browser") {
    if (entry.query_compiler_revision === "tm-figurative-fields-v1") return compileTmFigurativeQuery(entry, field);
    if (entry.right_type !== "trademark_word" || field && !["brand", "ocr", "translation"].includes(field)) {
      throw new Error("UNSUPPORTED_QUERY_SEMANTICS: figurative/classification/phonetic search has no accepted control mapping");
    }
    const strategy = entry.strategy || (field ? "phrase" : "");
    if (!["exact", "phrase", "prefix"].includes(strategy)) {
      throw new Error("UNSUPPORTED_QUERY_SEMANTICS: unsupported trademark text strategy");
    }
    const revision = entry.query_compiler_revision;
    if (revision && revision !== "tm-field-tags-v1") throw new Error("UNSUPPORTED_QUERY_SEMANTICS: unknown TM compiler revision");
    if (revision && /["\\\r\n]/.test(value)) throw new Error("UNSUPPORTED_QUERY_SEMANTICS: unsafe TM literal");
    if (revision && strategy === "prefix" && !/^[A-Za-z0-9]+$/.test(value)) throw new Error("UNSUPPORTED_QUERY_SEMANTICS: TM prefix requires one literal token");
    return { rendered_query: (revision ? "CM:" : "") + formatTmQuery(value, strategy), strategy,
      semantics: strategy === "prefix" ? "lexical_prefix" : "lexical_phrase", requested_field: field, language_filter_applied: false,
      ...(revision ? { query_compiler_revision: revision, search_mode: "field_tag", field_code: "CM" } : {}) };
  }
  if (provider === "uspto_patent_browser") {
    if (recallIntegrityEnabled(task)) return compilePpubsQuery(entry, field);
    if (field && !["structural_feature", "category", "product", "function", "translation", "synonym", "english", "design"].includes(field)) {
      throw new Error("UNSUPPORTED_QUERY_SEMANTICS: owner/classification fields have no accepted control mapping");
    }
    if (value.includes('"')) {
      throw new Error("UNSUPPORTED_QUERY_SEMANTICS: embedded quotation marks require an explicit Patent Public Search query plan");
    }
    // PPS Advanced treats AND, OR, NOT and WITH as operators.  Quoting a
    // plan's natural-language text preserves terms such as "and" as literal
    // words (per the official PPS stopword guidance), rather than silently
    // changing the plan into a Boolean/proximity statement.
    return { rendered_query: `"${value}"`, strategy: "advanced_literal_phrase", semantics: "advanced_literal_phrase",
      requested_field: field, language_filter_applied: false };
  }
  throw new Error("UNSUPPORTED_QUERY_SEMANTICS: no automatic provider mapping");
}

// Official Advanced Search indexes, verified 2026-09-06:
// https://www.uspto.gov/patents/search/patent-public-search/searchable-indexes
// ASNM is a published assignee name, not proof of today's owner. Locarno is
// deliberately absent until its input format and live result binding are tested.
export const PPUBS_FIELD_CODES = Object.freeze({ owner: "ASNM", assignee: "ASNM", applicant: "AANM",
  inventor: "INV", uspc: "CCLS", cpc: "CPC", ipc: "CIPC", title: "TI" });
const PPUBS_TEXT_FIELDS = new Set(["", "structural_feature", "category", "product", "function", "translation", "synonym", "english", "design", "brand"]);

export function compilePpubsBoolean(value) {
  const text = String(value).trim();
  const tokens = text.match(/"[^"\r\n]+"|\(|\)|[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*/g) || [];
  if (!tokens.length || tokens.join("").replaceAll(" ", "") !== text.replace(/\s/g, "") || tokens.length > 80) {
    throw new Error("UNSUPPORTED_QUERY_SEMANTICS: unsupported Boolean token or excessive query");
  }
  const isOperator = (token) => /^(AND|OR|NOT)$/i.test(token);
  for (const token of tokens) if (token.startsWith('"')) validatePpubsPhrase(token.slice(1, -1));
  if (!tokens.some(isOperator) && !tokens.includes("(") && !tokens.includes(")")) {
    if (tokens.length > 12) throw new Error("UNSUPPORTED_QUERY_SEMANTICS: decompose long product text before querying");
    return tokens.join(" AND ");
  }
  let index = 0;
  function atom() {
    if (tokens[index]?.toUpperCase() === "NOT") { index++; return `NOT ${atom()}`; }
    if (tokens[index] === "(") {
      index++;
      const result = expression();
      if (tokens[index++] !== ")") throw new Error("UNSUPPORTED_QUERY_SEMANTICS: unbalanced Boolean group");
      return `(${result})`;
    }
    const token = tokens[index++];
    if (!token || token === ")" || isOperator(token)) throw new Error("UNSUPPORTED_QUERY_SEMANTICS: missing Boolean operand");
    return token;
  }
  function expression() {
    let result = atom();
    while (tokens[index] && tokens[index] !== ")") {
      const operator = tokens[index++].toUpperCase();
      if (!["AND", "OR", "NOT"].includes(operator)) throw new Error("UNSUPPORTED_QUERY_SEMANTICS: explicit Boolean operator required");
      result += ` ${operator} ${atom()}`;
    }
    return result;
  }
  const result = expression();
  if (index !== tokens.length) throw new Error("UNSUPPORTED_QUERY_SEMANTICS: unmatched Boolean group");
  return result;
}

function validatePpubsPhrase(value) {
  if (!value || value.length > 120 || value.split(/\s+/).length > 8 || /["\r\n!?;<>]/.test(value)
      || /\b(?:PATENTED|MAKE IT EASY|YOUR FAVORITE|SATISFACTION GUARANTEED)\b/i.test(value)) {
    throw new Error("UNSUPPORTED_QUERY_SEMANTICS: phrase must be a short lexical phrase, not marketing text");
  }
}

export function compilePpubsQuery(entry, field = String(entry.filters?.field || "")) {
  const value = String(entry.q || entry.query || "").trim();
  const strategy = entry.strategy;
  if (!["boolean", "phrase", "record_number"].includes(strategy)) throw new Error("UNSUPPORTED_QUERY_SEMANTICS: explicit query strategy required");
  const code = PPUBS_FIELD_CODES[field];
  if (!code && !PPUBS_TEXT_FIELDS.has(field) && !["record_number", "publication_number"].includes(field)) throw new Error("UNSUPPORTED_QUERY_SEMANTICS: unsupported PPS field");
  let rendered;
  if (strategy === "record_number") {
    const record = cleanNumber(value).replace(/^US/, "").replace(/(?<=\d)[ABS]\d?$/, "");
    if (!/^(?:D|RE|PP)?\d{5,11}$/.test(record)) throw new Error("UNSUPPORTED_QUERY_SEMANTICS: malformed known US record number");
    rendered = entry.query_compiler_revision === "ppubs-quoted-record-v1" ? `"${record}".PN.` : `${record}.PN.`;
  } else if (["uspc", "cpc", "ipc"].includes(field)) {
    if (strategy !== "boolean" || !(field === "uspc" ? /^D?\d{1,3}\/\d+(?:\.\d+)?$/i : /^[A-HY]\d{2}[A-Z]\d+(?:\/\d+)?$/i).test(value)) {
      throw new Error("UNSUPPORTED_QUERY_SEMANTICS: expected one normalized classification code");
    }
    rendered = `${value.toUpperCase()}.${code}.`;
  } else {
    if (strategy === "phrase") { validatePpubsPhrase(value); rendered = `"${value}"`; }
    else rendered = compilePpubsBoolean(value);
    if (code) rendered = `(${rendered}).${code}.`;
  }
  // USPTO's CLM index guidance explicitly uses S.KD. for design patents.
  if (entry.right_type === "design" && strategy !== "record_number") rendered = `(${rendered}) AND S.KD.`;
  return { rendered_query: rendered, strategy, semantics: strategy === "record_number" ? "known_record" : strategy === "phrase" ? "lexical_phrase" : "boolean_terms",
    requested_field: field, language_filter_applied: false,
    field_code: strategy === "record_number" ? "PN" : code || null,
    right_type_filter: entry.right_type === "design" && strategy !== "record_number" ? "S.KD." : null };
}

export function executionReceipt(task, provider, entry, events, capture) {
  return {
    schema_version: "1.0", task_id: task.task_id, provider,
    query_id: entry.query_id, operation: entry.operation, jurisdiction: entry.jurisdiction,
    right_type: entry.right_type, query: String(entry.q || entry.query || ""),
    plan_entry_sha256: registryPageBindingDigest(entry),
    mode: "automatic", business_actions_by: "agent", events,
    completed_at: capture.checked_at, outcome: capture.status,
    final_url: sanitizeEvidenceUrl(capture.final_url),
    query_semantics: capture.query_semantics || null,
    ...(recallIntegrityEnabled(task) ? { result_pages_sha256: registryPageBindingDigest(capture.result_pages || []) } : {}),
    ...(capture.document_retrieval ? { document_retrieval_sha256: registryPageBindingDigest(capture.document_retrieval) } : {}),
    result_coverage_sha256: registryPageBindingDigest(capture.result_coverage || {}),
    media_coverage_sha256: registryPageBindingDigest(capture.media_coverage || {}),
    result_sha256: registryPageBindingDigest(capture.candidates || {
      record_number: capture.record_number || capture.serial_number || "",
      page_record_number: capture.page_record_number || capture.page_case_number || "",
    }),
  };
}

async function attachExecutionReceipt(taskDir, task, provider, entry, events, capture) {
  operationTimeout(1);
  if (task.schema_version !== "2.4-free") return;
  const receipt = executionReceipt(task, provider, entry, events, capture);
  const receiptPath = path.join(taskDir, "raw", "browser-execution", `${slug(entry.query_id)}-${crypto.randomUUID()}.json`);
  await writeJsonAtomic(receiptPath, receipt);
  capture.query_execution = { path: receiptPath, sha256: crypto.createHash("sha256").update(await fs.readFile(receiptPath)).digest("hex") };
  capture.browser_capability = {
    ...getAutomationCapability({ provider, jurisdiction: entry.jurisdiction, rightType: entry.right_type, operation: entry.operation }),
    status: capture.status === "needs_user_action" ? "access_verification_only" : "unvalidated",
    acceptance_result: capture.status,
    acceptance_evidence: capture.query_execution,
  };
  const submitted = events.some((event) => ["submit_query", "navigate_record"].includes(event.action));
  const observed = events.findLast((event) => event.action === "observe_result");
  if (["success", "no_result"].includes(capture.status) && submitted && observed?.stable === true) {
    // A single result is evidence for this query, not acceptance of all
    // positive/zero/record/pagination cases on the route.
    capture.browser_capability.status = recallIntegrityEnabled(task) ? "unvalidated" : "automatic";
    const acceptancePath = path.join(taskDir, "browser-route-acceptance.json");
    let acceptances = { task_id: task.task_id, routes: [] };
    try { acceptances = await readJson(acceptancePath); } catch {}
    if (acceptances.task_id !== task.task_id || !Array.isArray(acceptances.routes)) {
      throw new Error("BROWSER_ACCEPTANCE_TASK_MISMATCH");
    }
    acceptances.routes = acceptances.routes.filter((item) => !(item.provider === provider
      && item.jurisdiction === entry.jurisdiction && item.right_type === entry.right_type && item.operation === entry.operation));
    acceptances.routes.push({ provider, jurisdiction: entry.jurisdiction, right_type: entry.right_type,
      operation: entry.operation, query_execution: capture.query_execution,
      screenshot_path: capture.screenshot_path, checked_at: capture.checked_at });
    await writeJsonAtomic(acceptancePath, acceptances);
  }
  if (capture.status === "needs_user_action") {
    capture.required_user_actions = ["login", "captcha", "mfa", "consent", "qr"];
    capture.detail = "Complete only the login, CAPTCHA, MFA, access consent, or QR verification in visible Chrome. The agent must rerun the same plan entry and perform the query and capture automatically.";
  }
}

export async function acceptedBrowserRoute(taskDir, task, provider, entry) {
  const capability = getAutomationCapability({ provider, jurisdiction: entry.jurisdiction,
    rightType: entry.right_type, operation: entry.operation });
  if (!capability.executor_available) return false;
  let accepted;
  try { accepted = await readJson(path.join(taskDir, "browser-route-acceptance.json")); } catch { return false; }
  if (accepted.task_id !== task.task_id || !Array.isArray(accepted.routes)) return false;
  for (const item of accepted.routes) {
    if (["provider", "jurisdiction", "right_type", "operation"].some((key) => item[key] !== capability[key])) continue;
    try {
      const receiptPath = path.resolve(String(item.query_execution?.path || ""));
      if (!receiptPath.startsWith(path.resolve(taskDir, "raw", "browser-execution") + path.sep)) continue;
      const bytes = await fs.readFile(receiptPath);
      if (crypto.createHash("sha256").update(bytes).digest("hex") !== item.query_execution.sha256) continue;
      const receipt = JSON.parse(bytes);
      if (recallIntegrityEnabled(task) && (receipt.query_id !== entry.query_id
          || receipt.plan_entry_sha256 !== registryPageBindingDigest(entry))) continue;
      if (receipt.task_id !== task.task_id || receipt.mode !== "automatic" || receipt.business_actions_by !== "agent"
          || !["success", "no_result"].includes(receipt.outcome)
          || ["provider", "jurisdiction", "right_type", "operation"].some((key) => receipt[key] !== capability[key])) continue;
      const age = Date.now() - Date.parse(receipt.completed_at);
      if (!Number.isFinite(age) || age < -300000 || age > 48 * 3600000) continue;
      const plan = await readJson(path.join(taskDir, "search-plan.json"));
      const prior = resolveExactPlanEntry(plan, receipt.query_id);
      if (prior.provider !== provider || registryPageBindingDigest(prior.entry) !== receipt.plan_entry_sha256) continue;
      const events = receipt.events || [];
      const observation = events.findLast((event) => event.action === "observe_result");
      if (!events.some((event) => ["submit_query", "navigate_record"].includes(event.action) && event.actor === "agent")
          || observation?.stable !== true) continue;
      const screenshot = path.resolve(String(item.screenshot_path || ""));
      if (!screenshot.startsWith(path.resolve(taskDir, "screenshots") + path.sep)) continue;
      if (crypto.createHash("sha256").update(await fs.readFile(screenshot)).digest("hex") !== observation.screenshot_sha256) continue;
      return true;
    } catch { /* Invalid or stale acceptance is not reusable. */ }
  }
  return false;
}

export function assertTaskRoute(task, provider, operation, jurisdiction = "", rightType = "") {
  assertActiveTaskPayload(task);
  const expectedJurisdiction = jurisdiction === "EP" ? "EU" : String(jurisdiction || "").toUpperCase();
  const matched = task.coverage_requirements.some((requirement) => {
    if (!requirement || typeof requirement !== "object") return false;
    if (expectedJurisdiction && String(requirement.jurisdiction || "").toUpperCase() !== expectedJurisdiction) return false;
    if (rightType && String(requirement.right_type || "") !== String(rightType)) return false;
    return Array.isArray(requirement.routes) && requirement.routes.some((route) =>
      route && route.provider === provider && route.operation === operation
    );
  });
  if (!matched) {
    throw new Error(`PROVIDER_OPERATION_NOT_CONFIGURED: ${provider}/${operation}/${expectedJurisdiction}/${rightType}`);
  }
}

export function assertPlanMatchesTask(task, plan) {
  assertActiveTaskPayload(task);
  if (!plan || plan.schema_version !== task.schema_version || plan.task_id !== task.task_id) {
    throw new Error("SEARCH_PLAN_IDENTITY_MISMATCH: search plan does not belong to this task");
  }
  if (
    String(plan.free_policy_revision || "") !== String(task.free_policy_revision || "")
    || !samePolicy(plan.free_policy, task.free_policy)
  ) {
    throw new Error("FREE_POLICY_INVALID: search plan policy/revision must match the task");
  }
}

export function resolveExactPlanEntry(plan, queryId) {
  const expected = String(queryId || "").trim();
  if (!expected) throw new Error("QUERY_ID_REQUIRED: select one generated plan entry");
  const matches = [];
  for (const [provider, entries] of Object.entries(plan?.queries || {})) {
    if (!Array.isArray(entries)) continue;
    for (const entry of entries) {
      if (entry && typeof entry === "object" && String(entry.query_id || "") === expected) {
        matches.push({ provider, entry });
      }
    }
  }
  if (matches.length !== 1) {
    throw new Error(matches.length
      ? `QUERY_ID_AMBIGUOUS: ${expected} appears in more than one plan entry`
      : `QUERY_ID_NOT_PLANNED: ${expected}`);
  }
  return matches[0];
}

export async function assertScenarioActionDispatch(taskDir, task, provider, entry) {
  if (!Object.hasOwn(task || {}, "decision_workflow_revision")) return;
  // Reuse the Python dispatch authority rather than maintaining a weaker JS
  // copy of triage hashes, current decisions, cancellation and substitution.
  const result = await new Promise((resolve, reject) => {
    const child = spawn(process.env.LC_IPR_PYTHON || "python3", [
      path.join(SKILL_DIR, "scripts", "authorize_scenario_action.py"),
      "--task-dir", taskDir, "--provider", provider, "--query-id", String(entry.query_id || ""),
    ], { stdio: ["ignore", "pipe", "pipe"], env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" } });
    let output = "";
    const timeout = setTimeout(() => {
      child.kill();
      reject(new Error("SCENARIO_DISPATCH_TIMEOUT: current action authorization could not be verified"));
    }, operationTimeout(15000));
    child.stdout.on("data", (chunk) => {
      output += chunk.toString();
      if (output.length > 32768) child.kill();
    });
    child.stderr.resume();
    child.once("error", () => {
      clearTimeout(timeout);
      reject(new Error("SCENARIO_DISPATCH_RUNTIME_UNAVAILABLE: Python authorization is required"));
    });
    child.once("close", (code) => {
      clearTimeout(timeout);
      try {
        const parsed = JSON.parse(output);
        if (code === 0 && parsed.allowed === true) resolve(parsed);
        else reject(new Error(`${String(parsed.code || "SCENARIO_ACTION_BLOCKED")}: current scenario/triage does not authorize this action`));
      } catch (error) {
        reject(error instanceof SyntaxError
          ? new Error("SCENARIO_DISPATCH_INVALID_RESPONSE: current action authorization failed") : error);
      }
    });
  });
  return result;
}

export function candidatePlanInputs(provider, entry) {
  if (!entry || typeof entry !== "object" || entry.operation !== "candidate_verification") {
    throw new Error("CANDIDATE_PLAN_ENTRY_REQUIRED: selected entry is not candidate_verification");
  }
  const queryId = String(entry.query_id || "").trim();
  const candidateId = String(entry.candidate_id || "").trim();
  const jurisdiction = String(entry.jurisdiction || "").toUpperCase();
  const rightType = String(entry.right_type || "").trim();
  const record = String(
    entry.record_number || entry.serial_number || entry.number || entry.identifier
      || entry.q || entry.query || "",
  ).trim();
  const query = String(entry.q || entry.query || "").trim();
  const sourceKey = String(entry.source_key || "").trim();
  if (!queryId || !candidateId || !jurisdiction || !REGISTRY_RIGHT_TYPES.has(rightType) || !record) {
    throw new Error(
      "CANDIDATE_PLAN_BINDING_INCOMPLETE: query_id/candidate_id/jurisdiction/right_type/record are required",
    );
  }
  if (!query || (provider === "public_web_browser"
    ? query !== record
    : cleanNumber(query) !== cleanNumber(record))) {
    throw new Error("CANDIDATE_PLAN_RECORD_MISMATCH: q and the planned record identifier differ");
  }
  if (!Array.isArray(entry.requirement_ids) || !entry.requirement_ids.some((value) => String(value || "").trim())) {
    throw new Error("CANDIDATE_PLAN_REQUIREMENT_MISSING: candidate action has no requirement_ids");
  }
  if (provider === "uspto_tsdr") {
    if (jurisdiction !== "US" || !rightType.startsWith("trademark_")) {
      throw new Error("CANDIDATE_PLAN_ROUTE_MISMATCH: TSDR requires a US trademark action");
    }
    if (String(entry.serial_number || "").replace(/\D/g, "") !== record.replace(/\D/g, "")) {
      throw new Error("CANDIDATE_PLAN_RECORD_MISMATCH: TSDR serial_number differs from q");
    }
  } else if (provider === "uspto_patent_browser") {
    if (jurisdiction !== "US" || !["patent", "design"].includes(rightType)) {
      throw new Error("CANDIDATE_PLAN_ROUTE_MISMATCH: Patent Public Search requires a US patent/design action");
    }
    if (cleanNumber(entry.record_number) !== cleanNumber(record)) {
      throw new Error("CANDIDATE_PLAN_RECORD_MISMATCH: USPTO record_number differs from q");
    }
  } else if (provider === "public_web_browser") {
    if (!["copyright", "enforcement"].includes(rightType)) {
      throw new Error("CANDIDATE_PLAN_ROUTE_MISMATCH: public-web verification requires copyright/enforcement");
    }
    if (jurisdiction === "US" && !sourceKey) {
      throw new Error("CANDIDATE_PLAN_SOURCE_MISSING: US public-web verification requires source_key");
    }
  } else if (!REGISTRY_PLAN_PROVIDERS.has(provider)) {
    throw new Error(`CANDIDATE_PLAN_PROVIDER_UNSUPPORTED: ${provider}`);
  }
  return {
    provider,
    query_id: queryId,
    candidate_id: candidateId,
    jurisdiction,
    right_type: rightType,
    operation: "candidate_verification",
    record,
    source_key: sourceKey,
    ...(entry.workflow_correction_revision ? {
      workflow_correction_revision: entry.workflow_correction_revision,
      ...(entry.required_facts ? { required_facts: entry.required_facts } : {}),
      ...(entry.reading_scope ? { reading_scope: entry.reading_scope } : {}),
    } : {}),
  };
}

export function plannedReadingScope(entry, task) {
  if (task?.workflow_correction_revision !== "workflow-correction-v1") return null;
  const allowed = new Set(["abstract", "representative_figures", "protection_content", "current_status", "goods_services"]);
  const facts = entry?.required_facts, scope = entry?.reading_scope;
  if (entry?.workflow_correction_revision !== task.workflow_correction_revision
      || !Array.isArray(facts) || !facts.length || facts.some(value => !allowed.has(value))
      || new Set(facts).size !== facts.length || !scope || !allowed.has(scope.level)) {
    throw new Error("CANDIDATE_PLAN_READING_CONTRACT_INVALID: exact required_facts and reading_scope are required");
  }
  const pages = scope.page_numbers === undefined ? [] : scope.page_numbers;
  if (!Array.isArray(pages) || pages.some(value => !Number.isSafeInteger(value) || value < 1)
      || new Set(pages).size !== pages.length || facts.includes("representative_figures") && !pages.length) {
    throw new Error("CANDIDATE_PLAN_READING_CONTRACT_INVALID: representative pages must be explicitly identified");
  }
  return { required_facts: [...facts], reading_scope: { ...scope, page_numbers: [...pages] } };
}

export function assertCandidateInvocationMatches(args, planned) {
  const fields = [
    "provider", "query_id", "candidate_id", "jurisdiction", "right_type", "operation", "source_key",
  ];
  for (const field of fields) {
    const supplied = String(args?.[field] || "").trim();
    const expected = String(planned?.[field] || "").trim();
    if (supplied && (field === "jurisdiction" ? supplied.toUpperCase() : supplied) !== expected) {
      throw new Error(`CANDIDATE_INVOCATION_MISMATCH: ${field} differs from the selected plan entry`);
    }
  }
  if (args?.record && (planned.provider === "public_web_browser"
    ? String(args.record).trim() !== planned.record
    : cleanNumber(args.record) !== cleanNumber(planned.record))) {
    throw new Error("CANDIDATE_INVOCATION_MISMATCH: record differs from the selected plan entry");
  }
  return planned;
}

export function candidateCdpCommand(provider) {
  if (US_CANDIDATE_PROVIDERS.has(provider)) return "verify-candidate";
  if (REGISTRY_PLAN_PROVIDERS.has(provider)) return "open-registry";
  throw new Error(`CANDIDATE_PLAN_PROVIDER_UNSUPPORTED: ${provider}`);
}

async function resolvePlannedCandidateAction(taskDir, args) {
  const task = await readJson(path.join(taskDir, "task.json"));
  const plan = await readJson(path.join(taskDir, "search-plan.json"));
  assertPlanMatchesTask(task, plan);
  const resolved = resolveExactPlanEntry(plan, args.query_id);
  await assertScenarioActionDispatch(taskDir, task, resolved.provider, resolved.entry);
  const planned = candidatePlanInputs(resolved.provider, resolved.entry);
  assertCandidateInvocationMatches(args, planned);
  assertTaskRoute(task, planned.provider, planned.operation, planned.jurisdiction, planned.right_type);
  const targets = new Set((task.target_jurisdictions || []).map((value) => String(value).toUpperCase()));
  if (!targets.has(planned.jurisdiction) && !(planned.jurisdiction === "EP" && targets.has("EU"))) {
    throw new Error(`Registry jurisdiction ${planned.jurisdiction} is not in the task target jurisdictions`);
  }
  return { task, plan, entry: resolved.entry, inputs: planned };
}

function parseArgs(argv) {
  const [command = "", ...rest] = argv;
  const args = { command };
  for (let index = 0; index < rest.length; index += 1) {
    const raw = rest[index];
    if (!raw.startsWith("--")) {
      throw new Error(`Unexpected argument: ${raw}`);
    }
    const key = raw.slice(2).replaceAll("-", "_");
    const next = rest[index + 1];
    if (next && !next.startsWith("--")) {
      args[key] = next;
      index += 1;
    } else {
      args[key] = true;
    }
  }
  return args;
}

function expandHome(value) {
  const text = String(value || "");
  if (text === "~") return os.homedir();
  if (text.startsWith("~/")) return path.join(os.homedir(), text.slice(2));
  return path.resolve(text);
}

async function readJson(filePath) {
  return JSON.parse(await fs.readFile(filePath, "utf8"));
}

async function writeJsonAtomic(filePath, value, mode = 0o600) {
  operationTimeout(1);
  await fs.mkdir(path.dirname(filePath), { recursive: true, mode: 0o700 });
  const tempPath = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  await fs.writeFile(tempPath, `${JSON.stringify(value, null, 2)}\n`, { mode });
  await fs.rename(tempPath, filePath);
  await fs.chmod(filePath, mode);
}

export async function updateCandidateJournal(taskDir, entry) {
  const journalPath = path.join(taskDir, "browser-candidate-journal.json");
  let journal;
  try {
    journal = await readJson(journalPath);
  } catch {
    const task = await readJson(path.join(taskDir, "task.json"));
    journal = {
      schema_version: "1.0",
      task_id: String(task.task_id || ""),
      entries: [],
    };
  }
  if (!Array.isArray(journal.entries)) journal.entries = [];
  const provider = String(entry.provider || "");
  const recordNumber = cleanNumber(entry.record_number);
  if (!provider || !recordNumber) {
    throw new Error("Candidate journal entries require provider and record_number");
  }
  const index = journal.entries.findIndex((item) =>
    String(item?.provider || "") === provider
      && cleanNumber(item?.record_number) === recordNumber
  );
  const previous = index >= 0 ? journal.entries[index] : {};
  const next = {
    ...previous,
    ...entry,
    provider,
    record_number: recordNumber,
    updated_at: nowIso(),
  };
  if (index >= 0) journal.entries[index] = next;
  else journal.entries.push(next);
  assertNoSensitiveKeys(journal, "candidate_journal");
  await writeJsonAtomic(journalPath, journal);
  return journalPath;
}

export async function loadConfig(skillDir = SKILL_DIR) {
  // Browser routes need runtime settings only; never open local credentials.
  let config;
  try {
    config = await readJson(path.join(skillDir, "references", "runtime-config.json"));
  } catch {
    throw new Error("RUNTIME_CONFIG_INVALID: references/runtime-config.json is missing, unreadable, or invalid JSON");
  }
  if (!config || typeof config !== "object" || Array.isArray(config)) {
    throw new Error("RUNTIME_CONFIG_INVALID: references/runtime-config.json must contain an object");
  }
  return config;
}

function sanitizedSession(version, sessionId) {
  return {
    browser: "chrome_desktop",
    capture_transport: "cdp",
    browser_version: String(version.Browser || "Chrome/unknown"),
    protocol_version: String(version["Protocol-Version"] || "unknown"),
    cdp_session_id: sessionId,
  };
}

function assertNoSensitiveKeys(value, prefix = "capture") {
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertNoSensitiveKeys(item, `${prefix}[${index}]`));
    return;
  }
  if (!value || typeof value !== "object") return;
  for (const [key, item] of Object.entries(value)) {
    if (SENSITIVE_SESSION_KEYS.has(key.toLowerCase())) {
      throw new Error(`Sensitive browser field cannot be serialized: ${prefix}.${key}`);
    }
    assertNoSensitiveKeys(item, `${prefix}.${key}`);
  }
}

async function fetchVersion(port) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 2000);
  try {
    const response = await fetch(`http://127.0.0.1:${port}/json/version`, {
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`CDP version endpoint returned ${response.status}`);
    const version = await response.json();
    const endpoint = String(version.webSocketDebuggerUrl || "");
    if (!endpoint.startsWith(`ws://127.0.0.1:${port}/`)) {
      throw new Error("CDP endpoint is not bound to the expected loopback address");
    }
    return version;
  } finally {
    clearTimeout(timeout);
  }
}

async function waitForChromeEndpoint(child, timeoutMs = 20000) {
  return new Promise((resolve, reject) => {
    let buffer = "";
    const timeout = setTimeout(() => {
      reject(new Error("Timed out waiting for Chrome CDP endpoint"));
    }, timeoutMs);
    const finish = (error, value) => {
      clearTimeout(timeout);
      child.stderr?.off("data", onData);
      child.off("exit", onExit);
      if (error) reject(error);
      else resolve(value);
    };
    const onData = (chunk) => {
      buffer += chunk.toString("utf8");
      const match = buffer.match(/DevTools listening on ws:\/\/127\.0\.0\.1:(\d+)\/devtools\/browser\/[A-Za-z0-9-]+/);
      if (match) finish(null, Number(match[1]));
    };
    const onExit = (code) => finish(new Error(`Chrome exited before CDP became ready: ${code}`));
    child.stderr?.on("data", onData);
    child.once("exit", onExit);
  });
}

async function ensureSession(config) {
  const cdp = config.cdp || {};
  const runtimeDir = expandHome(cdp.runtime_dir || "~/.codex/runtime/lc-ipr-free-cdp");
  const profileDir = expandHome(cdp.profile_dir || "~/.codex/browser-profiles/lc-ipr-free-cdp");
  const descriptorPath = path.join(runtimeDir, "session.json");
  await fs.mkdir(runtimeDir, { recursive: true, mode: 0o700 });
  await fs.mkdir(profileDir, { recursive: true, mode: 0o700 });
  await fs.chmod(runtimeDir, 0o700);
  await fs.chmod(profileDir, 0o700);

  let descriptor = null;
  try {
    descriptor = await readJson(descriptorPath);
    const port = Number(descriptor.port);
    if (!Number.isInteger(port) || port < 1024 || port > 65535) {
      throw new Error("Invalid runtime CDP port");
    }
    const version = await fetchVersion(port);
    return {
      version,
      sessionId: String(descriptor.session_id),
      endpoint: version.webSocketDebuggerUrl,
      launched: false,
    };
  } catch {
    // A stale descriptor is replaced only after a fresh loopback Chrome starts.
  }

  const executable = expandHome(cdp.chrome_executable || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome");
  if (!fsSync.existsSync(executable)) {
    throw new Error(`Chrome executable is missing: ${executable}`);
  }
  const chromeArgs = [
    "--remote-debugging-address=127.0.0.1",
    "--remote-debugging-port=0",
    `--user-data-dir=${profileDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-mode",
    "about:blank",
  ];
  const child = spawn(executable, chromeArgs, {
    detached: true,
    stdio: ["ignore", "ignore", "pipe"],
  });
  const port = await waitForChromeEndpoint(child);
  const version = await fetchVersion(port);
  const sessionId = crypto
    .createHash("sha256")
    .update(`${child.pid}:${port}:${Date.now()}`)
    .digest("hex")
    .slice(0, 20);
  await writeJsonAtomic(descriptorPath, {
    port,
    pid: child.pid,
    session_id: sessionId,
    created_at: new Date().toISOString(),
  });
  child.stderr?.destroy();
  child.unref();
  return {
    version,
    sessionId,
    endpoint: version.webSocketDebuggerUrl,
    launched: true,
  };
}

async function connectSession(config) {
  const session = await ensureSession(config);
  const browser = await chromium.connectOverCDP(session.endpoint);
  const context = browser.contexts()[0];
  if (!context) {
    throw new Error("CDP browser has no default context");
  }
  const timeout = Number(config.cdp?.action_timeout_ms || 15000);
  context.setDefaultTimeout(timeout);
  return { ...session, browser, context };
}

function nowIso() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

export function currentRegistryTermsReview(args, adapter, checkedAt = nowIso()) {
  if (args?.confirm_current_terms !== true) {
    throw new Error(
      "REGISTRY_TERMS_REVIEW_REQUIRED: pass --confirm-current-terms after reviewing the adapter's current official terms/service notice",
    );
  }
  const termsUrl = assertOfficialUrl(adapter.terms_url, {
    ...adapter, browser_allowed_hosts: adapter.terms_allowed_hosts,
  }).toString();
  return {
    schema_version: "1.0",
    terms_url: sanitizeEvidenceUrl(termsUrl),
    checked_at: checkedAt,
    decision: "cdp_assisted_single_action_confirmed",
    operator_confirmed: true,
  };
}

function slug(value) {
  return String(value || "capture")
    .replace(/[^A-Za-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80) || "capture";
}

export function shellQuoteArgument(value) {
  const raw = String(value ?? "");
  if (raw.includes("\0")) throw new Error("Shell command arguments cannot contain NUL bytes");
  return `'${raw.replaceAll("'", `'"'"'`)}'`;
}

export function registryCaptureCommand({
  taskDir, provider, queryId, query, rightType, filters, cliPath = fileURLToPath(import.meta.url),
}) {
  const argv = [
    "node", cliPath, "capture-registry-search",
    "--task-dir", String(taskDir),
    "--provider", String(provider),
    "--query-id", String(queryId),
    "--attest-query", String(query),
    "--attest-right-type", String(rightType),
    "--attest-filters", canonicalJson(filters || {}),
    "--attest-current-page",
    "--confirm-current-terms",
  ];
  return { argv, shell: argv.map((value) => shellQuoteArgument(value)).join(" ") };
}

export function registryRecordCaptureCommand({
  taskDir, provider, queryId, record, candidateId, rightType, jurisdiction, sourceKey = "",
  cliPath = fileURLToPath(import.meta.url),
}) {
  const argv = [
    "node", cliPath, "capture-registry",
    "--task-dir", String(taskDir),
    "--provider", String(provider),
    "--query-id", String(queryId),
    "--record", String(record),
    "--candidate-id", String(candidateId),
    "--right-type", String(rightType),
    "--jurisdiction", String(jurisdiction),
  ];
  if (sourceKey) argv.push("--source-key", String(sourceKey));
  argv.push("--confirm-current-terms");
  return { argv, shell: argv.map((value) => shellQuoteArgument(value)).join(" ") };
}

function sanitizeEvidenceUrl(value) {
  try {
    const url = new URL(String(value || ""));
    url.username = "";
    url.password = "";
    for (const key of [...url.searchParams.keys()]) {
      if (SENSITIVE_URL_KEYS.has(key.toLowerCase())) url.searchParams.delete(key);
    }
    if (url.hash.includes("?")) {
      const [route, rawQuery] = url.hash.slice(1).split("?", 2);
      const params = new URLSearchParams(rawQuery);
      for (const key of [...params.keys()]) {
        if (SENSITIVE_URL_KEYS.has(key.toLowerCase())) params.delete(key);
      }
      url.hash = `${route}${params.size ? `?${params.toString()}` : ""}`;
    }
    return url.toString();
  } catch {
    return "";
  }
}

function sanitizeSensitiveText(value) {
  return String(value || "")
    .replace(/\b(authorization|proxy-authorization)\s*:\s*(?:bearer|basic)?\s*[^\s,;]+/gi, "$1: [redacted]")
    .replace(
      /([?&](?:requesttoken|token|api_key|apikey|key|access_token|refresh_token|client_id|client_secret|consumer_key|consumer_secret|password|passwd|username|code|session|session_id)=)[^&#\s]+/gi,
      "$1[redacted]",
    )
    .replace(
      /(["'](?:requesttoken|token|api_key|apikey|access_token|refresh_token|authorization|client_id|client_secret|consumer_key|consumer_secret|password|passwd|username)["']\s*:\s*)(["'])[^"']*\2/gi,
      "$1$2[redacted]$2",
    );
}

function cleanNumber(value) {
  return String(value || "").replace(/[^A-Za-z0-9]/g, "").toUpperCase();
}

export function formatTmQuery(query, strategy) {
  const value = String(query || "").trim();
  if (strategy === "prefix") return `${value}*`;
  if (strategy === "exact" || strategy === "phrase") return `"${value.replaceAll('"', "")}"`;
  if (strategy === "design_code") return value;
  throw new Error(`Unsupported TM Search strategy: ${strategy}`);
}

export function compileTmFigurativeQuery(entry, field) {
  if (entry.query_compiler_revision !== "tm-figurative-fields-v1" || entry.right_type !== "trademark_figurative") {
    throw new Error("UNSUPPORTED_QUERY_SEMANTICS: figurative fields require an explicit new compiler revision");
  }
  const refs = typeof entry.derived_from === "string" ? [entry.derived_from] : entry.derived_from || [];
  if (!Array.isArray(refs) || !refs.some(ref => typeof ref === "string" && /^(?:product\.mark_inventory\[\d+\]|evidence:EV[-A-Za-z0-9]+)/.test(ref))) {
    throw new Error("UNSUPPORTED_QUERY_SEMANTICS: figurative element provenance required");
  }
  const value = String(entry.q || "").trim(), strategy = entry.strategy;
  let code, rendered, semantics, dimension;
  if (field === "design_code" && strategy === "classification" && /^(?:\d{6}|\d{2}\.\d{2}\.\d{2})$/.test(value)) {
    [code, rendered, semantics, dimension] = ["DC", "DC:" + value.replaceAll(".", ""), "design_classification", "classification"];
  } else if (field === "mark_description" && ["boolean", "phrase"].includes(strategy)) {
    if (strategy === "phrase") {
      validatePpubsPhrase(value);
      if (!/^[A-Za-z0-9][A-Za-z0-9 '\-]*$/.test(value)) throw new Error("UNSUPPORTED_QUERY_SEMANTICS: unsafe design description phrase");
      rendered = `DE:"${value}"`;
    } else rendered = `DE:(${compilePpubsBoolean(value)})`;
    [code, semantics, dimension] = ["DE", "design_description", "description"];
  } else throw new Error("UNSUPPORTED_QUERY_SEMANTICS: expected one US design code or an English design description");
  return { rendered_query: rendered, strategy, semantics, requested_field: field, language_filter_applied: false,
    query_compiler_revision: "tm-figurative-fields-v1", search_mode: "field_tag", field_code: code, search_dimension: dimension };
}

export function detectChallenge(url, title, bodyText) {
  const text = `${url}\n${title}\n${bodyText}`.toLowerCase();
  return /captcha|robot check|verify you are human|security verification|access denied|challenge-platform/.test(text);
}

export function classifyBrowserAccess(url, title, bodyText) {
  const text = `${url}\n${title}\n${bodyText}`.toLowerCase();
  if (browserRateLimited(text)) return "access_limited";
  if (/captcha|robot check|verify you are human|security verification|scan.{0,20}qr|multi.?factor authentication|two.?factor authentication|enter (?:the )?(?:verification|security) code|access consent required|sign in to continue|log in to continue|login required|\/signin(?:[/?\s]|$)|\/login(?:[/?\s]|$)/.test(text)) {
    return "needs_user_action";
  }
  if (/access denied|forbidden|automated access.{0,30}(prohibited|blocked)|unusual traffic|temporarily blocked/.test(text)) return "access_limited";
  return null;
}

export function browserRateLimited(bodyText) {
  return /too many requests|(?:rate|request)[ -]?limit (?:has been )?exceeded/i.test(String(bodyText || ""));
}

export function explicitNoResult(bodyText) {
  return /no (records|results|matches|cases) (were )?found|0 results|zero results/i.test(String(bodyText || ""));
}

export function browserResultCoverage(bodyText, retrievedCount, completed = true) {
  const text = String(bodyText || "");
  const match = text.match(/\b(?:results?|records?)\s+\d[\d,]*\s*[-–]\s*\d[\d,]*\s+of\s+([\d,]+)\b/i)
    || text.match(/\b([\d,]+)\s+(?:results|records)\s+(?:found|returned)\b/i)
    || text.match(/\btotal\s+(?:results|records)\s*:\s*([\d,]+)\b/i);
  const reportedTotal = explicitNoResult(text) ? 0 : match ? Number(match[1].replaceAll(",", "")) : null;
  return { total_hits: reportedTotal, retrieved_hits: retrievedCount, reviewed_hits: null,
    schema_valid: completed, source_updated_at: null,
    stop_reason: reportedTotal === 0 && completed ? "zero_results" : "browser_current_page_only",
    retrieved_count: retrievedCount, reported_total: reportedTotal,
    pages_retrieved: completed ? 1 : 0,
    truncated: reportedTotal === null ? null : reportedTotal > retrievedCount ? true : reportedTotal === 0 ? false : null,
    completeness: "unknown",
    reason: "Only the rendered result page was inspected; pagination, provider coverage, and recall completeness were not validated." };
}

const operationContext = new AsyncLocalStorage();
const currentOperationDeadline = () => operationContext.getStore() ?? Infinity;
const ownedAutomaticPages = new Map();

export function operationTimeout(requestedMs, deadline = currentOperationDeadline(), now = Date.now()) {
  const remaining = deadline - now;
  if (remaining <= 0) throw Object.assign(new Error("OPERATION_DEADLINE_EXCEEDED"), { code: "OPERATION_DEADLINE_EXCEEDED" });
  return Math.max(1, Math.min(Number(requestedMs), remaining));
}

export async function withOperationDeadline(action, deadline = Infinity) {
  if (deadline !== Infinity && (!Number.isFinite(deadline) || deadline <= Date.now())) {
    throw Object.assign(new Error("OPERATION_DEADLINE_EXCEEDED"), { code: "OPERATION_DEADLINE_EXCEEDED" });
  }
  return operationContext.run(Math.min(currentOperationDeadline(), deadline), async () => {
    let timer;
    try {
      if (currentOperationDeadline() === Infinity) return await action();
      return await Promise.race([Promise.resolve().then(action), new Promise((_, reject) => {
        timer = setTimeout(() => reject(Object.assign(new Error("OPERATION_DEADLINE_EXCEEDED"), { code: "OPERATION_DEADLINE_EXCEEDED" })), operationTimeout(2147483647));
      })]);
    } finally { clearTimeout(timer); }
  });
}

async function newAutomaticPage(context, policy = "inspect") {
  const page = await context.newPage();
  ownedAutomaticPages.set(page, policy);
  return page;
}

export async function releaseOwnedPage(page, owned, accessStatus) {
  if (!owned || accessStatus === "needs_user_action") return false;
  let timer;
  try { await Promise.race([page.close().catch(() => {}), new Promise(resolve => { timer = setTimeout(resolve, 2000); })]); }
  finally { clearTimeout(timer); }
  return true;
}

async function releaseAutomaticPages() {
  for (const [page, policy] of ownedAutomaticPages) {
    if (policy === "preserve") continue;
    if (policy === "close") { await releaseOwnedPage(page, true, null); continue; }
    // These pages were created by this command. User pages are never registered.
    let timer;
    let state;
    try { state = await Promise.race([freshState(page), new Promise((resolve) => { timer = setTimeout(() => resolve(null), 1500); })]); }
    finally { clearTimeout(timer); }
    if (state) await releaseOwnedPage(page, true, classifyBrowserAccess(state.url, state.title, state.bodyText));
  }
  ownedAutomaticPages.clear();
}

export async function waitForStableSemanticState(readSnapshot, options = {}) {
  const timeoutMs = Number(options.timeoutMs || 45000);
  const pollMs = Number(options.pollMs || 750);
  const stableSamples = Math.max(1, Number(options.stableSamples || 3));
  const deadline = Date.now() + operationTimeout(timeoutMs);
  let lastSignature = "";
  let stableCount = 0;
  let latest = null;
  while (Date.now() <= deadline) {
    latest = await readSnapshot();
    if (Date.now() > deadline) break;
    const signature = String(latest?.signature || "");
    if (latest?.ready && signature) {
      stableCount = signature === lastSignature ? stableCount + 1 : 1;
      lastSignature = signature;
      if (stableCount >= stableSamples) {
        return { ...latest, stable: true, timed_out: false, stable_samples: stableCount };
      }
    } else {
      stableCount = 0;
      lastSignature = "";
    }
    const remaining = deadline - Date.now();
    if (remaining <= 0) break;
    await new Promise((resolve) => setTimeout(resolve, Math.min(pollMs, remaining)));
  }
  return {
    ...(latest || {}),
    stable: false,
    timed_out: true,
    stable_samples: stableCount,
  };
}

export function renderedPatentPdfScreenshot(screenshot) {
  return Buffer.isBuffer(screenshot) && screenshot.length >= 60000;
}

export function assertCdpProviderAllowed(provider) {
  if (/wipo|patentscope/i.test(String(provider || ""))) {
    throw new Error("WIPO/PATENTSCOPE is disabled; legacy WIPO evidence is read-only");
  }
  if (provider === "espacenet_browser") {
    throw new Error("Espacenet browser automation is disabled; use the planned EPO OPS query");
  }
  if (!["uspto_tmsearch_browser", "uspto_patent_browser"].includes(provider)) {
    throw new Error(`run-planned-query does not support provider: ${provider}`);
  }
}

export function parseTrademarkRows(rows) {
  const results = [];
  for (const cells of rows) {
    const values = cells.map((value) => String(value || "").trim()).filter(Boolean);
    const joined = values.join(" | ");
    const serial = joined.match(/(?:^|\D)(\d{8})(?:\D|$)/)?.[1] || "";
    if (!serial) continue;
    const registration = joined.match(/(?:registration|reg\.?)\s*(?:no\.?|number)?\s*[:#]?\s*(\d{7,8})/i)?.[1] || "";
    const markText = values.find((value) => !value.includes(serial) && !/serial|registration|live|dead|class/i.test(value)) || "";
    if (!markText) continue;
    results.push({
      serial_number: serial,
      registration_number: registration,
      mark_text: markText,
      owner: values.find((value) => /inc|llc|ltd|corp|company|co\./i.test(value)) || "",
      status: values.find((value) => /live|dead|registered|pending/i.test(value)) || "",
      nice_classes: values.filter((value) => /(?:international class|ic)\s*0?\d+/i.test(value)),
      goods_services: [],
    });
  }
  return results;
}

export function parseTrademarkCards(bodyText, { allowNonverbal = false } = {}) {
  const results = new Map();
  for (const block of String(bodyText || "").split(/(?=Check to tag for\s+\d{8}\b)/i)) {
    const tagged = block.match(/^Check to tag for\s+(\d{8})\b/i)?.[1];
    const serial = block.match(/\nSerial\s*\n(\d{8})\b/i)?.[1];
    const mark = block.match(/\nWordmark\s*\n(?:wordmark\s*\n)?([\s\S]*?)\nStatus\s*\n/i)?.[1]?.trim();
    if (!tagged || serial !== tagged || mark === undefined || !mark && !allowNonverbal || results.has(serial)) continue;
    const status = block.match(/\nStatus\s*\n([\s\S]*?)\nGoods\s*&\s*services/i)?.[1]?.trim() || "";
    const goods = block.match(/\nGoods\s*&\s*services\s*\n([\s\S]*?)\nClass\s*\n/i)?.[1]?.trim() || "";
    const classes = block.match(/\nClass\s*\n([\s\S]*?)\nSerial\s*\n/i)?.[1] || "";
    const owner = block.match(/\nOwners\s*\n([^\n]+)/i)?.[1]?.trim() || "";
    results.set(serial, { serial_number: serial, registration_number: "", mark_text: mark,
      ...(!mark ? { mark_text_missing: true } : {}),
      owner, status, nice_classes: [...classes.matchAll(/\b\d{3}\b/g)].map(m => m[0]),
      goods_services: goods ? [goods.replace(/\noutbound\b/g, "")] : [], goods_services_truncated: /\.\.\.|…/.test(goods) });
  }
  return [...results.values()];
}

export function parseTrademarkDetail(bodyText, url, { allowNonverbal = false } = {}) {
  const text = String(bodyText || "");
  const marker = text.match(/Search result details for serial number\s+(\d{8})\b/i);
  let routeSerial;
  try { routeSerial = new URL(url, "https://invalid.test").pathname.match(/^\/search\/search-results\/(\d{8})\/?$/)?.[1]; }
  catch { return []; }
  if (!marker || marker[1] !== routeSerial) return [];
  const block = text.slice(marker.index + marker[0].length);
  const serial = block.match(/\nSerial number\s*\n(\d{8})\b/i)?.[1];
  const mark = block.match(/\nWordmark\s*\n([\s\S]*?)\nSerial number\s*\n/i)?.[1]?.trim();
  const status = block.match(/\nStatus\s*\n([\s\S]*?)\nStatus date\s*\n/i)?.[1]?.trim();
  // The detail skeleton exposes serial/wordmark before async fields finish.
  // Require a rendered LIVE/DEAD status as well; no current-status verification
  // is inferred from this recall result (that remains the TSDR stage).
  if (serial !== marker[1] || mark === undefined || !mark && !allowNonverbal || !/^(?:LIVE|DEAD)/i.test(status || "")) return [];
  const registration = block.match(/\nRegistration number\s*\n(\d{7,8})\b/i)?.[1] || "";
  const classes = block.match(/\nClass\s*\n([\s\S]*?)\nTM5 Status\s*\n/i)?.[1] || "";
  const goods = block.match(/\nGoods and services\s*\n([\s\S]*?)\nCurrent owner\s*\n/i)?.[1]?.trim() || "";
  const owner = block.match(/\nCurrent owner\s*\n([\s\S]*?)\nOwnership transitions\s*\n/i)?.[1]?.trim() || "";
  return [{ serial_number: serial, registration_number: registration, mark_text: mark, status,
    ...(!mark ? { mark_text_missing: true } : {}),
    owner, nice_classes: [...classes.matchAll(/\b\d{3}\b/g)].map(m => m[0]),
    goods_services: goods ? [goods] : [], goods_services_truncated: !goods || /\.\.\.|…/.test(goods) }];
}

export function tmsearchResultBinding(bodyText, inputValue, mode, renderedQuery) {
  const text = String(bodyText || "");
  const detail = text.match(/\bResult\s+(\d+)\s+of\s+([\d,]+)\s+for\s+([^\r\n]+)/i);
  const header = detail ? [detail[0], detail[2], detail[3]] : text.match(/\b([\d,]+)\s+results?\s+for\s+([^\r\n]+)/i);
  const normalize = value => String(value || "").replace(/[“”]/g, '"').replace(/\s+/g, " ").trim();
  const query = normalize(renderedQuery);
  const resultQuery = normalize(header?.[2]);
  // The count header quotes the whole field-tag statement on current TM Search.
  const headerMatches = resultQuery === query || resultQuery === `"${query}"`;
  const total = header ? Number(header[1].replaceAll(",", "")) : null;
  return { total_hits: total, result_view: detail ? "detail" : "list", result_index: detail ? Number(detail[1]) : null,
    query_bound: Boolean(query && headerMatches && normalize(inputValue) === query
      && mode === "Field tag and Search builder" && (!detail || total === 1 && Number(detail[1]) === 1)),
    input_value: inputValue, rendered_query: renderedQuery, search_mode: mode, result_query: resultQuery };
}

export async function collectTmRenderedResults(page, initial, taskDir, stem, config, { maxPages = 8 } = {}) {
  // Each page retains its own query binding and pixels. Unvisited pages are
  // never treated as an empty search, and no new query is submitted here.
  const pages = [], found = new Map();
  let current = initial, stop = "browser_current_page_only", failure = null;
  const total = initial.tmsearch_binding?.total_hits;
  const range = async () => {
    const label = await page.locator(".mat-mdc-paginator-range-label, .mat-paginator-range-label").first().innerText().catch(() => "");
    const match = label.match(/([\d,]+)\s*[–—-]\s*([\d,]+)\s+(?:of|\/)\s*([\d,]+)/i);
    return match ? { start: Number(match[1].replaceAll(",", "")), end: Number(match[2].replaceAll(",", "")), total: Number(match[3].replaceAll(",", "")) } : null;
  };
  let observedRange = await range();
  const limit = Math.min(8, Math.max(1, Number(maxPages) || 8));
  for (let index = 1; index <= limit; index++) {
    if (!current.stable || !current.query_bound || current.tmsearch_binding?.total_hits !== total || !current.candidates?.length) break;
    const serials = current.candidates.map(row => row.serial_number);
    if (serials.some(serial => found.has(serial)) || new Set(serials).size !== serials.length) { stop = "browser_repeated_page"; break; }
    const screenshotPath = path.join(taskDir, "screenshots", `${stem}-tm-page-${index}.png`);
    await safeScreenshot(page, screenshotPath, { fullPage: true });
    pages.push({ page_index: index, query_binding: current.tmsearch_binding, final_url: current.state.url,
      range: observedRange, candidates: current.candidates, screenshot_path: screenshotPath,
      screenshot_sha256: crypto.createHash("sha256").update(await fs.readFile(screenshotPath)).digest("hex") });
    current.candidates.forEach(row => found.set(row.serial_number, row));
    if (found.size === total) { stop = "browser_results_exhausted"; break; }
    if (index === limit) { stop = "browser_page_limit"; break; }
    if (!observedRange || observedRange.total !== total || observedRange.end - observedRange.start + 1 !== serials.length
        || index === 1 && observedRange.start !== 1) { stop = "browser_pagination_range_unavailable"; break; }
    const next = page.getByRole("button", { name: /^Next page$/i });
    if (await next.count() !== 1 || !await next.isVisible() || !await next.isEnabled()) { stop = "browser_next_page_unavailable"; break; }
    const previousEnd = observedRange.end;
    try {
      await next.click({ timeout: operationTimeout(10000) });
      const ready = await waitForStableSemanticState(async () => {
        const snapshot = await searchSemanticSnapshot(page, "uspto_tmsearch_browser", config.tmsearch_query_binding);
        const nextRange = await range();
        return { ...snapshot, range: nextRange, ready: snapshot.ready && snapshot.query_bound && snapshot.tmsearch_binding?.total_hits === total
          && nextRange?.start === previousEnd + 1 && nextRange.total === total
          && nextRange.end - nextRange.start + 1 === snapshot.candidates.length
          && snapshot.candidates.every(row => !found.has(row.serial_number)), signature: snapshot.signature + JSON.stringify(nextRange) };
      }, { timeoutMs: Number(config.cdp?.tm_page_timeout_ms || 12000), pollMs: Number(config.cdp?.semantic_poll_ms || 750), stableSamples: Number(config.cdp?.semantic_stable_samples || 3) });
      if (!ready.stable) {
        stop = ready.rateLimited ? "BROWSER_RATE_LIMITED" : "browser_page_not_confirmed";
        failure = { attempted_page: index + 1, error_code: stop, final_url: sanitizeEvidenceUrl(ready.state?.url || page.url()),
          access_status: classifyBrowserAccess(ready.state?.url || page.url(), ready.state?.title || "", ready.state?.bodyText || ""),
          observed_query_binding: ready.tmsearch_binding || null,
          error_excerpt: sanitizeSensitiveText(String(ready.state?.bodyText || "").split("\n").filter(line => /too many requests|rate limit|loading|searching/i.test(line)).join("\n").slice(0, 1200)) };
        const failurePath = path.join(taskDir, "screenshots", `${stem}-tm-page-${index + 1}-incomplete.png`);
        try {
          await safeScreenshot(page, failurePath, { fullPage: true });
          Object.assign(failure, { screenshot_path: failurePath, screenshot_sha256: crypto.createHash("sha256").update(await fs.readFile(failurePath)).digest("hex") });
        } catch { /* The operation deadline never authorizes a new screenshot budget. */ }
        break;
      }
      current = ready;
      observedRange = ready.range;
    } catch { stop = "browser_pagination_interrupted"; break; }
  }
  const last = pages.at(-1), complete = found.size === total && pages.length > 0;
  return { candidates: [...found.values()], result_pages: pages, query_binding: last?.query_binding || initial.tmsearch_binding,
    last_screenshot_path: last?.screenshot_path, last_state: current.state,
    result_coverage: { total_hits: total, retrieved_hits: found.size, reviewed_hits: null, schema_valid: pages.length > 0,
      source_updated_at: null, reported_total: total, retrieved_count: found.size, pages_retrieved: pages.length,
      truncated: !complete, completeness: complete ? "result_set_complete" : "partial", stop_reason: stop,
      ...(failure ? { pagination_failure: failure } : {}),
      reason: "Only distinct query-bound rendered pages are counted; failed or unvisited pages remain a retrieval gap." } };
}

export function parsePatentRows(rows) {
  const results = [];
  for (const cells of rows) {
    const values = cells.map((value) => String(value || "").trim()).filter(Boolean);
    const joined = values.join(" | ");
    const match = joined.match(/\bUS[-\s]?(?:D|RE|PP)?\d{5,11}(?:[-\s]?[A-Z]\d?)?\b/i)
      || joined.match(/\bD\d{6,8}(?:[-\s]?S\d?)?\b/i);
    if (!match) continue;
    const record = match[0].replace(/\s+/g, "-").toUpperCase();
    const recordIndex = values.findIndex((value) => value.includes(match[0]));
    const title = values.slice(Math.max(0, recordIndex + 1)).find((value) =>
      value.length > 3
      && !/^(preview|pdf|text|display|title|pages?|result\s*#?)(?:\s|$)/i.test(value)
      && !/^\d{4}-\d{2}-\d{2}$/.test(value)
      && !/^(active|expired|issued|pending|abandon(?:ed)?)$/i.test(value)
      && !/^(?:\d+|page \d+(?: of \d+)?)$/i.test(value)
    ) || "";
    if (!title) continue;
    results.push({
      record_number: record,
      publication_number: record,
      title,
      owners: values.filter((value) => /inc|llc|ltd|corp|company|co\./i.test(value)).slice(0, 3),
      legal_status: values.find((value) => /active|expired|issued|pending|abandon/i.test(value)) || "",
      jurisdiction: "US",
      kind_code: record.match(/[A-Z]\d?$/)?.[0] || "",
      material: false,
    });
  }
  return results;
}

export async function ppubsRenderedSnapshot(page) {
  return page.evaluate(() => {
    const root = document.querySelector("#searchResults-content");
    const viewport = root?.querySelector("#search-results-table .slick-viewport");
    const text = (selector) => (root?.querySelector(selector)?.textContent || "").trim();
    const visible = (node) => Boolean(node && node.getBoundingClientRect().width && node.getBoundingClientRect().height);
    const rows = [...(root?.querySelectorAll("#search-results-table .slick-row") || [])].map((row) => {
      const fields = {};
      for (const cell of row.querySelectorAll(".slick-cell[aria-describedby]")) {
        const key = cell.getAttribute("aria-describedby").replace(/^slickgrid_\d+/, "");
        fields[key] = (cell.innerText || "").trim();
      }
      return fields;
    });
    const next = root?.querySelector(".page-number .btn-next");
    const count = text(".resultNumber").replaceAll(",", "");
    const resultText = text(".resultInfo");
    const range = resultText.match(/displaying results\s+([\d,]+)\s*-\s*([\d,]+)/i);
    const families = text(".srFilterSection").match(/([\d,]+)\s+families/i);
    const positionedRows = [...(viewport?.querySelectorAll(".slick-row") || [])].filter(row => row.style.top);
    const intervals = positionedRows.map(row => ({ top: row.offsetTop, bottom: row.offsetTop + row.offsetHeight }))
      .sort((a, b) => a.top - b.top);
    const contiguous = intervals.length === rows.length && intervals.every((row, index) => row.bottom > row.top
      && (index === 0 || Math.abs(row.top - intervals[index - 1].bottom) <= 1));
    return { rows, result_set_id: text(".lQuery").replace(/[:\s]/g, ""),
      total_hits: /^\d+$/.test(count) ? Number(count) : null,
      loading: [...(root?.querySelectorAll("*") || [])].some(node => !node.children.length && visible(node)
        && /^loading(?:\.{3}|…)?$/i.test((node.textContent || "").trim())),
      result_text: resultText, filter_text: text(".srFilterSection"),
      displayed_start: range ? Number(range[1].replaceAll(",", "")) : null,
      displayed_end: range ? Number(range[2].replaceAll(",", "")) : /currently displaying all results/i.test(resultText)
        ? Number(families?.[1].replaceAll(",", "") || count) || null : null,
      reported_families: families ? Number(families[1].replaceAll(",", "")) : null,
      current_page: Number(text(".current-page")) || 1,
      all_pages: Number(text(".all-pages")) || null,
      next_visible: visible(next), next_enabled: visible(next) && !next.disabled && !next.classList.contains("disabled"),
      editor_value: (document.querySelector("trix-editor.trix[aria-label='Enter query text']")?.textContent || "").trim(),
      viewport: viewport ? { top: viewport.scrollTop, height: viewport.clientHeight, scroll_height: viewport.scrollHeight,
        positioned_row_count: positionedRows.length, rows_contiguous: contiguous,
        ...(positionedRows.length ? { rendered_top: Math.min(...positionedRows.map(row => row.offsetTop)),
          rendered_bottom: Math.max(...positionedRows.map(row => row.offsetTop + row.offsetHeight)) } : {}) } : null };
  });
}

export function ppubsViewportAligned(value) {
  const position = value.viewport;
  if (!position || position.rendered_top === undefined) return true;
  if (position.rendered_top <= position.top + 1
      && position.rendered_bottom >= Math.min(position.scroll_height, position.top + position.height) - 1) return true;
  // SlickGrid pads its canvas to the viewport even when a small loaded set
  // contains just two collapsed families. Official loaded-row count and real
  // contiguous positioned rows authorize reading this window, not declaring
  // the result set complete: hidden family members must still be expanded.
  return position.top <= 1 && position.height > 0 && position.scroll_height <= position.height + 1
    && position.rendered_top <= 1 && position.rows_contiguous === true
    && position.positioned_row_count === value.rows.length
    && Number.isInteger(value.displayed_end) && value.displayed_end > 0
    && value.rows.length >= value.displayed_end
    && (value.displayed_start === 1 || /currently displaying all results/i.test(value.result_text));
}

export function parsePpubsGridRows(rows) {
  const results = [];
  for (const row of rows) {
    const record = cleanNumber(row.documentId);
    if (!/^US(?:(?:D|RE|PP)?\d{5,11})(?:[A-Z]\d?)?$/.test(record) || !row.inventionTitle) continue;
    const kind = record.match(/\d([A-Z]\d?)$/)?.[1] || "";
    results.push({ record_number: record, publication_number: record, title: row.inventionTitle,
      owners: row.assigneeName ? [row.assigneeName] : [], inventors: row.inventorsShort ? [row.inventorsShort] : [],
      application_number: row.applicationNumber || "", family_id: row.familyIdentifierCur || "",
      family_member_count: Number(String(row.familyGroup || "").match(/[+-]\s*(\d+)/)?.[1] || 0),
      publication_date: row.datePublished || "", legal_status: "", jurisdiction: "US", kind_code: kind,
      right_type: record.startsWith("USD") || kind.startsWith("S") ? "design" : "patent", material: false,
      result_ordinal: Number(row.rowNumber) || null });
  }
  return results;
}

async function searchSemanticSnapshot(page, provider, options = {}) {
  const state = await freshState(page);
  const ppubs = provider === "uspto_patent_browser" && options.strict ? await ppubsRenderedSnapshot(page) : null;
  const rows = ppubs?.rows || await tableRows(page);
  const tmCards = provider === "uspto_tmsearch_browser" && options.tmsearchQuery ? parseTrademarkCards(state.bodyText, options) : [];
  const tmBinding = provider === "uspto_tmsearch_browser" && options.tmsearchQuery
    ? tmsearchResultBinding(state.bodyText,
      await page.locator("#searchbar").inputValue().catch(() => ""),
      (await page.locator("mat-select[formcontrolname='searchRefinement']").innerText().catch(() => "")).trim(), options.tmsearchQuery) : null;
  const tmLoading = tmBinding ? await page.evaluate(() => {
    const visible = node => { const r = node.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(node).visibility !== "hidden"; };
    return /(?:^|\n)\s*(?:loading|searching)(?:\.{3}|…)\s*(?:\n|$)/i.test(document.body.innerText)
      || [...document.querySelectorAll('[aria-busy="true"],mat-spinner,mat-progress-spinner,mat-progress-bar,[role="progressbar"]')].some(visible)
      || [...document.querySelectorAll("body *")].some(node => !node.children.length && visible(node)
        && /^(?:loading|searching)(?:\.{3}|…)?$/i.test((node.textContent || "").trim()));
  }) : false;
  const candidates = provider === "uspto_tmsearch_browser"
    ? tmBinding ? tmBinding.result_view === "detail" ? parseTrademarkDetail(state.bodyText, state.url, options) : tmCards
      : parseTrademarkRows(rows)
    : ppubs ? parsePpubsGridRows(rows) : parsePatentRows(rows);
  if (tmBinding) Object.assign(tmBinding, { loading: tmLoading, parsed_count: candidates.length });
  const challenge = detectChallenge(state.url, state.title, state.bodyText);
  const rateLimited = browserRateLimited(state.bodyText);
  const binding = tmBinding ? tmBinding.query_bound : !ppubs || Boolean(ppubs.result_set_id && options.historyBinding?.result_set_id === ppubs.result_set_id
    && options.historyBinding?.query === options.renderedQuery && options.historyBinding?.total_hits === ppubs.total_hits
    && ppubs.editor_value === options.renderedQuery);
  const noResult = tmBinding ? binding && !tmLoading && tmBinding.total_hits === 0 && !candidates.length : ppubs ? binding && ppubs.total_hits === 0 && /results found/i.test(ppubs.result_text) : explicitNoResult(state.bodyText);
  const queryError = /(?:error status|please enter only one word per text box|invalid search query)/i.test(state.bodyText);
  return {
    ready: challenge || rateLimited || queryError || binding && !ppubs?.loading && !tmLoading
      && (noResult || candidates.length > 0 && (!tmBinding || tmBinding.total_hits >= candidates.length)),
    signature: JSON.stringify({
      url: state.url,
      challenge,
      rateLimited,
      noResult,
      queryError,
      ...(ppubs ? { result_set_id: ppubs.result_set_id, total_hits: ppubs.total_hits, loading: ppubs.loading, binding } : {}),
      ...(tmBinding ? { tmBinding } : {}),
      candidates: candidates.map((item) => [
        item.record_number || item.serial_number,
        item.title || item.mark_text, ...(tmBinding ? [item.status, item.owner, item.goods_services, item.nice_classes] : []),
      ]),
    }),
    state,
    rows,
    candidates,
    challenge,
    rateLimited,
    noResult,
    queryError,
    ...(ppubs ? { ppubs, query_bound: binding } : {}),
    ...(tmBinding ? { tmsearch_binding: tmBinding, query_bound: binding } : {}),
  };
}

export async function waitForSearchSemanticState(page, provider, timeoutMs, config) {
  const options = { ...(config.ppubs_query_binding || {}), ...(config.tmsearch_query_binding || {}) };
  const deadline = Date.now() + operationTimeout(timeoutMs);
  const bindingAttempts = [];
  return waitForStableSemanticState(
    async () => {
      let snapshot = await searchSemanticSnapshot(page, provider, options);
      // PPS can publish the L-number/count long before its grid and history
      // become ready. Do not freeze a one-time null binding into every later
      // poll, or switch away while the result grid is still Loading.
      if (options.strict && options.historyScreenshotPath && !snapshot.query_bound
          && !snapshot.challenge && !snapshot.rateLimited && !snapshot.queryError && !snapshot.ppubs?.loading
          && snapshot.ppubs?.result_set_id && snapshot.ppubs.total_hits !== null
          && (snapshot.ppubs.total_hits === 0 || snapshot.candidates.length)) {
        const remaining = deadline - Date.now();
        if (remaining > 0) {
          let errorCode = "";
          try {
            options.historyBinding = await bindPpubsResultHistory(page, options.renderedQuery,
              options.historyScreenshotPath, { timeoutMs: Math.min(Number(options.historyTimeoutMs || 12000), remaining) });
          } catch (error) {
            options.historyBinding = null;
            errorCode = sanitizeSensitiveText(error.code || error.message).slice(0, 150);
          }
          bindingAttempts.push({ at: nowIso(), result_set_id: snapshot.ppubs.result_set_id,
            bound: Boolean(options.historyBinding), ...(errorCode ? { error_code: errorCode } : {}) });
          snapshot = await searchSemanticSnapshot(page, provider, options);
        }
      }
      return { ...snapshot, ...(options.strict ? { history_binding: options.historyBinding || null,
        history_binding_attempts: bindingAttempts } : {}) };
    },
    {
      timeoutMs,
      pollMs: Number(config.cdp?.semantic_poll_ms || 750),
      stableSamples: Number(config.cdp?.semantic_stable_samples || 3),
    },
  );
}

async function freshState(page) {
  const state = { url: page.url(), title: "", bodyText: "" };
  try {
    state.title = await page.title();
  } catch {}
  try {
    state.bodyText = (await page.locator("body").innerText()).slice(0, 200000);
  } catch {}
  return state;
}

async function navigateAndRefresh(page, url, timeoutMs) {
  let navigationError = "";
  try {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: operationTimeout(timeoutMs) });
  } catch (error) {
    navigationError = String(error?.message || error);
  }
  if (currentOperationDeadline() === Infinity) await page.waitForTimeout(800);
  return { state: await freshState(page), navigationError };
}

async function firstVisible(page, selectors) {
  for (const selector of selectors) {
    const locator = page.locator(selector);
    const count = Math.min(await locator.count(), 20);
    for (let index = 0; index < count; index += 1) {
      const item = locator.nth(index);
      if (await item.isVisible().catch(() => false)) return item;
    }
  }
  return null;
}

export async function tableRows(page) {
  return page.locator("table tr").evaluateAll((rows) =>
    rows.map((row) =>
      Array.from(row.querySelectorAll("th,td"))
        .map((cell) => (cell.innerText || "").trim())
        .filter(Boolean)
    ).filter((cells) => cells.length)
  ).catch(() => []);
}

async function safeScreenshot(page, screenshotPath, options = {}) {
  operationTimeout(1);
  await fs.mkdir(path.dirname(screenshotPath), { recursive: true, mode: 0o700 });
  await page.screenshot({ path: screenshotPath, animations: "disabled", ...options, timeout: operationTimeout(15000) });
}

export function plannedQueryCapturePaths(taskDir, provider, queryId, executionId = crypto.randomUUID()) {
  const stem = `${slug(provider)}-${slug(queryId)}-${slug(executionId)}`;
  return {
    screenshotPath: path.join(taskDir, "screenshots", `${stem}.png`),
    capturePath: path.join(taskDir, `${stem}-capture.json`),
  };
}

export function candidateCapturePaths(taskDir, provider, record, queryId, task = {}) {
  const paths = provider === "uspto_tsdr" && recallIntegrityEnabled(task)
    ? plannedQueryCapturePaths(taskDir, provider, queryId)
    : { screenshotPath: path.join(taskDir, "screenshots", `${slug(provider)}-${slug(record)}.png`),
      capturePath: path.join(taskDir, `${slug(provider)}-${slug(record)}-capture.json`) };
  return { ...paths, markImagePath: path.join(taskDir, "images", provider === "uspto_tsdr" && recallIntegrityEnabled(task)
    ? `${path.basename(paths.screenshotPath, ".png")}-official-mark.png` : `uspto-tsdr-${slug(record)}-official-mark.png`) };
}

export async function extractAmazonProduct(page, { strict = false } = {}) {
  return page.evaluate(({ strict }) => {
    const visibleText = (selector) => {
      const element = document.querySelector(selector);
      if (!element) return "";
      const style = getComputedStyle(element);
      return style.display === "none" || style.visibility === "hidden"
        ? ""
        : (element.innerText || element.textContent || "").trim();
    };
    const list = (selector) => Array.from(document.querySelectorAll(selector))
      .filter((element) => {
        const style = getComputedStyle(element);
        return style.display !== "none" && style.visibility !== "hidden";
      })
      .map((element) => (element.innerText || element.textContent || "").trim())
      .filter(Boolean);
    const specs = {};
    for (const row of document.querySelectorAll(
      "#productDetails_detailBullets_sections1 tr, #productDetails_techSpec_section_1 tr, #detailBullets_feature_div li"
    )) {
      const cells = Array.from(row.querySelectorAll("th,td,span"))
        .map((cell) => (cell.innerText || cell.textContent || "").trim())
        .filter(Boolean);
      if (cells.length >= 2 && !specs[cells[0]]) specs[cells[0]] = cells.slice(1).join(" ");
    }
    const isVisible = (element) => {
      const box = element.getBoundingClientRect();
      return box.width > 0 && box.height > 0 && getComputedStyle(element).visibility !== "hidden";
    };
    const image = strict
      ? [...document.querySelectorAll("#main-image-container img[data-a-image-name], #landingImage, #imgTagWrapperId img")].find(isVisible)
      : document.querySelector("#landingImage, #imgTagWrapperId img, img[data-old-hires]");
    let imageUrl = image?.getAttribute("data-old-hires") || "";
    const dynamic = image?.getAttribute("data-a-dynamic-image");
    if (!imageUrl && dynamic) {
      try {
        const entries = Object.entries(JSON.parse(dynamic));
        entries.sort((left, right) => (right[1]?.[0] || 0) * (right[1]?.[1] || 0) - (left[1]?.[0] || 0) * (left[1]?.[1] || 0));
        imageUrl = entries[0]?.[0] || "";
      } catch {}
    }
    imageUrl ||= image?.currentSrc || image?.src || "";
    // A global aria-checked selector includes the video player's subtitles and
    // buy-box price. Those are not ASIN variation identity.
    const selectedVariants = strict ? [...new Set(list(
      "[id^='variation_'] .selection, #twister .selection, [id^='variation_'] .swatchSelect, #twister .swatchSelect, [id^='variation_'] .variation_selected, #twister .variation_selected"
    ))] : list("[aria-checked='true'], .a-button-selected, .swatchSelect, .variation_selected");
    return {
      title: visibleText("#productTitle"),
      brand: visibleText("#bylineInfo").replace(/^Visit the | Store$/g, "").trim(),
      category: list("#wayfinding-breadcrumbs_feature_div a").join(" > "),
      bullets: list("#feature-bullets li span.a-list-item"),
      specifications: specs,
      selectedVariants,
      imageUrl,
      imageWidth: image?.naturalWidth || 0,
      imageHeight: image?.naturalHeight || 0,
      ...(strict ? { imageSlot: image?.getAttribute("data-mb-pv-slot-index") ?? null } : {}),
      pageAsin: document.querySelector("input#ASIN")?.value || "",
    };
  }, { strict });
}

export async function collectAmazonGallery(page, expectedAsin, maxViews = 12, { strict = false } = {}) {
  const thumbnails = page.locator("#altImages li.imageThumbnail");
  const available = await thumbnails.count();
  const observed = [];
  const failures = [];
  for (let index = 0; index < Math.min(available, maxViews); index += 1) {
    try {
      const thumbnail = thumbnails.nth(index);
      if (!await thumbnail.isVisible()) continue;
      const previous = strict ? await extractAmazonProduct(page, { strict }) : null;
      const wasSelected = strict && await thumbnail.locator("[aria-checked='true'], .a-button-selected").count() > 0;
      const slot = strict ? await thumbnail.getAttribute("data-csa-c-posx") : null;
      await thumbnail.click();
      const result = await waitForStableSemanticState(async () => {
        const value = await extractAmazonProduct(page, { strict });
        const selected = !strict || await thumbnail.locator("[aria-checked='true'], .a-button-selected").count() > 0;
        const imageBound = !strict || (slot !== null && value.imageSlot !== null
          ? value.imageSlot === slot : selected && (wasSelected || value.imageUrl !== previous?.imageUrl));
        return { ready: Boolean(value.imageUrl && value.imageWidth > 0 && selected && imageBound),
          signature: `${value.pageAsin}|${value.imageUrl}`, product: value };
      }, { timeoutMs: 4000, pollMs: 200, stableSamples: 2 });
      const value = result.product || {};
      if (String(value.pageAsin || "").toUpperCase() !== expectedAsin) {
        throw new Error("AMAZON_VARIANT_CHANGED");
      }
      if (!result.stable) throw new Error(strict ? "GALLERY_SELECTED_IMAGE_NOT_BOUND" : "GALLERY_IMAGE_NOT_STABLE");
      if (!observed.some((item) => item.source_url === value.imageUrl)) {
        observed.push({ source_url: value.imageUrl, asin: expectedAsin,
          observed_at: nowIso(), gallery_index: index,
          width: value.imageWidth, height: value.imageHeight });
      }
    } catch (error) {
      if (String(error.message).includes("AMAZON_VARIANT_CHANGED")) throw error;
      failures.push({ gallery_index: index, reason: sanitizeSensitiveText(error.message).slice(0, 150) });
    }
  }
  return { observed, available_thumbnail_count: available,
    attempted_count: Math.min(available, maxViews), truncated: available > maxViews,
    failures, completeness: "unknown",
    reason: "Gallery images are observed product views; internal structure, hidden faces, and packaging completeness require product evidence review." };
}

async function captureAmazon(args, config) {
  const taskDir = path.resolve(String(args.task_dir || ""));
  const task = await readJson(path.join(taskDir, "task.json"));
  const capturePrefix = recallIntegrityEnabled(task) ? `amazon-${crypto.randomUUID()}-` : "";
  assertActiveTaskPayload(task);
  if (task.checkpoints?.credential_preflight?.status !== "success") {
    throw new Error("Credential preflight must pass before opening Amazon");
  }
  const requestedUrl = String(task.request?.url || "");
  const session = await connectSession(config);
  const provenance = sanitizedSession(session.version, session.sessionId);
  let page = session.context.pages().find((item) => item.url().includes(task.request?.amazon_host || ""));
  if (!page) page = await session.context.newPage();
  const timeout = Number(config.cdp?.navigation_timeout_ms || 45000);
  const { state, navigationError } = await navigateAndRefresh(page, requestedUrl, timeout);
  const capturePath = path.join(taskDir, `${capturePrefix}browser-capture.json`);

  const accessStatus = task.schema_version === "2.4-free"
    ? classifyBrowserAccess(state.url, state.title, state.bodyText)
    : detectChallenge(state.url, state.title, state.bodyText) ? "needs_user_action" : null;
  if (accessStatus) {
    const screenshotPath = path.join(taskDir, "screenshots", `${capturePrefix}amazon-user-action.png`);
    await safeScreenshot(page, screenshotPath);
    const capture = {
      ...provenance,
      status: accessStatus === "needs_user_action" ? "robot_check" : "access_limited",
      requested_url: requestedUrl,
      final_url: state.url,
      screenshot_path: screenshotPath,
      detail: accessStatus === "needs_user_action"
        ? "Complete only login, CAPTCHA, MFA, access consent, or QR verification in visible Chrome; the agent resumes capture."
        : "Amazon access is blocked; no permitted access verification action was identified.",
    };
    assertNoSensitiveKeys(capture);
    await writeJsonAtomic(capturePath, capture);
    return { status: accessStatus, capture_path: capturePath };
  }

  const product = await extractAmazonProduct(page, { strict: recallIntegrityEnabled(task) });
  const urlAsin = state.url.match(/\/(?:dp|gp\/product|gp\/aw\/d)\/([A-Z0-9]{10})(?:[/?]|$)/i)?.[1]?.toUpperCase() || "";
  const actualAsin = String(product.pageAsin || urlAsin).toUpperCase();
  const corePath = path.join(taskDir, "screenshots", `${capturePrefix}product-core.png`);
  const detailsPath = path.join(taskDir, "screenshots", `${capturePrefix}product-details.png`);
  await page.evaluate(() => scrollTo(0, 0));
  await safeScreenshot(page, corePath);
  const details = await firstVisible(page, [
    "#productDetails_detailBullets_sections1",
    "#productDetails_techSpec_section_1",
    "#detailBullets_feature_div",
  ]);
  if (details) await details.scrollIntoViewIfNeeded().catch(() => {});
  await safeScreenshot(page, detailsPath);

  const imageUrl = String(product.imageUrl || "");
  if (!/^https:\/\/[^/]*media-amazon\.com\//i.test(imageUrl)) {
    const capture = {
      ...provenance, status: "failed", requested_url: requestedUrl,
      final_url: state.url, actual_asin: actualAsin,
      detail: "A current-variant HTTPS Amazon media main image was not available.",
    };
    assertNoSensitiveKeys(capture);
    await writeJsonAtomic(capturePath, capture);
    return { status: "failed", capture_path: capturePath };
  }

  const imagePage = await session.context.newPage();
  const imageResponse = await imagePage.goto(imageUrl, { waitUntil: "load", timeout });
  if (!imageResponse?.ok()) throw new Error(`Main image request failed: ${imageResponse?.status()}`);
  const imageBytes = await imageResponse.body();
  const contentType = String(imageResponse.headers()["content-type"] || "image/jpeg").split(";")[0];
  const imageSize = await imagePage.locator("img").first().evaluate((image) => ({
    width: image.naturalWidth,
    height: image.naturalHeight,
  })).catch(() => ({ width: product.imageWidth, height: product.imageHeight }));
  await imagePage.close();
  const extension = contentType.includes("png") ? "png" : contentType.includes("webp") ? "webp" : "jpg";
  const imagePath = path.join(taskDir, "images", `${capturePrefix}main.${extension}`);
  await fs.writeFile(imagePath, imageBytes, { mode: 0o600 });
  const imageHash = crypto.createHash("sha256").update(imageBytes).digest("hex");
  const productImages = [];
  let galleryCoverage = null;
  if (task.schema_version === "2.4-free") {
    galleryCoverage = await collectAmazonGallery(page, actualAsin, 12, { strict: recallIntegrityEnabled(task) });
    const hashes = new Set([imageHash]);
    for (const view of galleryCoverage.observed) {
      if (view.source_url === imageUrl || !/^https:\/\/[^/]*media-amazon\.com\//i.test(view.source_url)) continue;
      const mediaPage = await session.context.newPage();
      try {
        const response = await mediaPage.goto(view.source_url, { waitUntil: "load", timeout });
        if (!response?.ok()) throw new Error("GALLERY_MEDIA_FETCH_FAILED");
        const bytes = await response.body();
        const digest = crypto.createHash("sha256").update(bytes).digest("hex");
        if (hashes.has(digest)) continue;
        const type = String(response.headers()["content-type"] || "");
        const ext = type.includes("png") ? "png" : type.includes("webp") ? "webp" : "jpg";
        const size = await mediaPage.locator("img").first().evaluate((img) => ({ width: img.naturalWidth, height: img.naturalHeight }));
        if (!size.width || !size.height) throw new Error("GALLERY_MEDIA_DIMENSIONS_UNKNOWN");
        const filePath = path.join(taskDir, "images", `${capturePrefix}gallery-${productImages.length + 1}.${ext}`);
        await fs.writeFile(filePath, bytes, { mode: 0o600 });
        hashes.add(digest);
        productImages.push({ ...view, ...size, path: filePath, sha256: digest,
          role: "product_view", format: ext === "jpg" ? "JPEG" : ext.toUpperCase() });
      } catch (error) {
        galleryCoverage.failures.push({ gallery_index: view.gallery_index, reason: sanitizeSensitiveText(error.message).slice(0, 150) });
      } finally { await mediaPage.close(); }
    }
    galleryCoverage.retrieved_count = 1 + productImages.length;
    delete galleryCoverage.observed;
  }
  const manufacturer = Object.entries(product.specifications)
    .find(([key]) => /manufacturer/i.test(key))?.[1] || "";
  const visibleIpClaims = product.bullets.filter((value) =>
    /patent|copyright|licensed|trademark|registered design/i.test(value)
  );
  const selected = product.selectedVariants.join(" | ").slice(0, 500);
  const capture = {
    ...provenance,
    status: "success",
    requested_url: requestedUrl,
    final_url: state.url,
    requested_asin: String(task.product?.requested_asin || ""),
    actual_asin: actualAsin,
    variant: {
      label: selected ? "Selected option" : "ASIN",
      value: selected || actualAsin,
      confirmed: Boolean(actualAsin && actualAsin === String(task.product?.requested_asin || "").toUpperCase()),
    },
    title: product.title,
    brand: product.brand,
    manufacturer,
    category: product.category,
    bullets: product.bullets,
    specifications: product.specifications,
    structure: [],
    visible_ip_claims: visibleIpClaims,
    ocr_text: [],
    visual_features: [],
    main_image: {
      path: imagePath,
      source_url: imageUrl,
      width: Number(imageSize.width || 0),
      height: Number(imageSize.height || 0),
      format: extension === "png" ? "PNG" : extension === "webp" ? "WEBP" : "JPEG",
      sha256: imageHash,
    },
    ...(task.schema_version === "2.4-free" ? { product_images: productImages, image_coverage: galleryCoverage } : {}),
    screenshots: {
      product_core: corePath,
      product_details: detailsPath,
    },
    collected_at: nowIso(),
  };
  if (navigationError && (!capture.title || !capture.category)) {
    capture.status = "failed";
    capture.detail = `Amazon did not render a complete product page: ${navigationError.slice(0, 300)}`;
  }
  assertNoSensitiveKeys(capture);
  await writeJsonAtomic(capturePath, capture);
  return { status: capture.status, capture_path: capturePath };
}

function automaticQueryError(code) {
  const error = new Error(code);
  error.code = code;
  return error;
}

async function submitPpubsAdvancedSearch(page, renderedQuery, { strict = false } = {}) {
  const editor = page.locator("trix-editor.trix[aria-label='Enter query text']");
  const button = page.locator("#search-btn-search");
  await editor.waitFor({ state: "visible", timeout: operationTimeout(15000) }).catch(() => {});
  if (!await editor.isVisible().catch(() => false)
      || !await button.isVisible().catch(() => false)) {
    throw automaticQueryError("PPUBS_ADVANCED_SEARCH_CONTROLS_UNAVAILABLE");
  }
  // PPS Basic routes its first generic input to Quick Lookup, which accepts
  // only patent numbers and truncates text. The advanced Trix editor accepts
  // the plan-bound statement; keyboard events update its controlled state.
  if (strict) {
    // PPS 4.3.0 intercepts Select All after a prior search. Its own Clear
    // control resets the controlled Trix model; never append to stale input.
    const clear = page.locator("button.buttonReset[title='Clear search query and reset search options']");
    if (!await clear.isVisible().catch(() => false)) throw automaticQueryError("PPUBS_CLEAR_CONTROL_UNAVAILABLE");
    await clear.click({ timeout: operationTimeout(15000) });
    const empty = await waitForStableSemanticState(async () => {
      const value = (await editor.textContent()).trim();
      return { ready: value === "", signature: value === "" ? "empty" : value };
    }, { timeoutMs: 3000, pollMs: 100, stableSamples: 2 });
    if (!empty.stable) throw automaticQueryError("PPUBS_CLEAR_INPUT_MISMATCH");
    await editor.click({ timeout: operationTimeout(15000) });
  } else {
    await editor.click({ timeout: operationTimeout(15000) });
    const selectAll = process.platform === "darwin" ? "Meta+A" : "Control+A";
    await editor.press(selectAll, { timeout: operationTimeout(15000) });
    await editor.press("Backspace", { timeout: operationTimeout(15000) });
  }
  await editor.pressSequentially(renderedQuery, { timeout: operationTimeout(15000) });
  await page.waitForTimeout(100);
  // innerText deliberately uppercases recognized PPS operators for display.
  // textContent retains the entered statement and is therefore the correct
  // controlled-value check for a quoted literal phrase.
  const actualValue = (await page.locator("trix-editor.trix[aria-label='Enter query text']").textContent()).trim();
  if (actualValue !== renderedQuery) {
    throw automaticQueryError("AUTOMATIC_QUERY_INPUT_MISMATCH");
  }
  if (!await button.isEnabled().catch(() => false)) {
    throw automaticQueryError("PPUBS_ADVANCED_SEARCH_BUTTON_DISABLED");
  }
  const previousResultSet = strict ? (await page.locator("#searchResults-content .lQuery").textContent().catch(() => "") || "").replace(/[:\s]/g, "") : "";
  try {
    // A timeout during click can still have reached the official service, so
    // callers must observe the page instead of retrying a possible submission.
    await button.click({ timeout: operationTimeout(15000) });
  } catch (error) {
    error.submission_state = "uncertain";
    error.phase = "submit";
    throw error;
  }
  return {
    action: "submit_query", actor: "agent", at: nowIso(), rendered_query: renderedQuery,
    input_value: actualValue, submit_method: "ppubs_advanced_search",
    previous_result_set_id: previousResultSet,
    url: sanitizeEvidenceUrl(page.url()),
  };
}

async function resolvePpubsAdvancedWorkspace(context, fallbackPage) {
  if (await fallbackPage.locator("trix-editor.trix[aria-label='Enter query text']").isVisible().catch(() => false)) {
    return fallbackPage;
  }
  // PPS permits one Advanced Search console per browser session.  A previous
  // automatic attempt may leave that console open after a recoverable UI
  // error; reuse its visible, official workspace instead of treating the
  // "Console is already open" landing page as a failed locator lookup.
  for (const page of context.pages().slice().reverse()) {
    if (page === fallbackPage || !page.url().startsWith("https://ppubs.uspto.gov/pubwebapp/")) continue;
    if (await page.locator("trix-editor.trix[aria-label='Enter query text']").isVisible().catch(() => false)) return page;
  }
  return fallbackPage;
}

async function openPpubsAdvancedWorkspace(session, page, startUrl, timeout) {
  // Closing one completed PPS query releases its server-side single-console
  // lock asynchronously. Retry only the explicit lock landing page; a normal
  // workspace is allowed to finish its own editor-ready wait below.
  for (let attempt = 0; attempt < 3; attempt += 1) {
    await navigateAndRefresh(page, startUrl, timeout);
    const workspace = await resolvePpubsAdvancedWorkspace(session.context, page);
    if (workspace !== page) {
      if (ownedAutomaticPages.has(page)) {
        await releaseOwnedPage(page, true, null);
        ownedAutomaticPages.delete(page);
      }
      return workspace;
    }
    const state = await freshState(page);
    if (!/patent public search console is already open/i.test(state.bodyText)) return page;
    if (attempt < 2) await page.waitForTimeout(1500 * (attempt + 1));
  }
  return page;
}

export async function submitSearch(page, renderedQuery, provider = "", options = {}) {
  let submitting = false;
  try {
    if (options.strict && browserRateLimited((await freshState(page)).bodyText)) {
      throw automaticQueryError("BROWSER_RATE_LIMITED");
    }
    if (provider === "uspto_patent_browser") {
      const result = await submitPpubsAdvancedSearch(page, renderedQuery, options);
      submitting = true;
      return result;
    }
    if (provider === "uspto_tmsearch_browser" && options.tmsearchFieldTags) {
      const mode = page.locator("mat-select[formcontrolname='searchRefinement']");
      if ((await mode.innerText()).trim() !== "Field tag and Search builder") {
        await mode.click({ timeout: operationTimeout(15000) });
        await page.getByRole("option", { name: "Field tag and Search builder", exact: true }).click({ timeout: operationTimeout(15000) });
      }
      const selected = await waitForStableSemanticState(async () => {
        const text = (await mode.innerText()).trim();
        const placeholder = await page.locator("#searchbar").getAttribute("placeholder");
        return { ready: text === "Field tag and Search builder" && placeholder === "Search using field tags", signature: text + placeholder };
      }, { timeoutMs: 5000, pollMs: 100, stableSamples: 2 });
      if (!selected.stable) throw automaticQueryError("TMSEARCH_FIELD_TAG_MODE_UNCONFIRMED");
    }
    const input = await firstVisible(page, ["input[type='search']", "input[placeholder*='Search' i]",
      "input[aria-label*='Search' i]", "input[type='text']"]);
    if (!input) throw new Error("AUTOMATIC_QUERY_INPUT_MISSING");
    await input.fill(renderedQuery, { timeout: operationTimeout(15000) });
    const actualValue = await input.inputValue();
    if (actualValue !== renderedQuery) throw new Error("AUTOMATIC_QUERY_INPUT_MISMATCH");
    const button = await firstVisible(page, ["button:has-text('Search')", "input[type='submit']", "button[type='submit']"]);
    submitting = true; // A timed-out click/Enter can already have reached the server.
    if (button) await button.click({ timeout: operationTimeout(15000) });
    else await input.press("Enter", { timeout: operationTimeout(15000) });
    return { action: "submit_query", actor: "agent", at: nowIso(), rendered_query: renderedQuery,
      input_value: actualValue, submit_method: button ? "click" : "enter", url: sanitizeEvidenceUrl(page.url()),
      ...(options.tmsearchFieldTags ? { search_mode: "Field tag and Search builder" } : {}) };
  } catch (error) {
    error.submission_state ||= submitting ? "uncertain" : "not_submitted";
    error.phase ||= submitting ? "submit" : "prepare_input";
    error.code ||= submitting ? "AUTOMATIC_QUERY_SUBMISSION_UNCERTAIN" : "AUTOMATIC_QUERY_PRE_SUBMIT_FAILED";
    throw error;
  }
}

export async function observeAfterSubmission(page, provider, timeout, config, submitError, observe = waitForSearchSemanticState) {
  if (submitError?.submission_state === "not_submitted") {
    return { state: await freshState(page), stable: false, timed_out: false, candidates: [], skipped: "not_submitted" };
  }
  return observe(page, provider, operationTimeout(timeout), config);
}

// Only use the visible, named family column; never guess a control from other
// "+" buttons in the PPS workspace. Unsupported markup remains an explicit gap.
export async function expandPpubsVisibleFamily(page, expected, attempted, { timeoutMs = 8000 } = {}) {
  const target = await page.locator("#search-results-table .slick-viewport").evaluate((viewport, already) => {
    const bounds = viewport.getBoundingClientRect();
    for (const row of viewport.querySelectorAll(".slick-row")) {
      const cell = row.querySelector(".slick-cell[aria-describedby$='familyGroup']");
      const label = (cell?.innerText || "").trim(), rect = cell?.getBoundingClientRect();
      const record = (row.querySelector(".slick-cell[aria-describedby$='documentId']")?.innerText || "").replace(/[^A-Za-z0-9]/g, "").toUpperCase();
      if (/^\+\s*\d+$/.test(label) && record && !already.includes(record) && rect?.width > 0
          && rect.bottom > bounds.top && rect.top < bounds.bottom && rect.right > bounds.left && rect.left < bounds.right) {
        return { record, documentText: row.querySelector(".slick-cell[aria-describedby$='documentId']").innerText.trim(),
          label, id: cell.getAttribute("aria-describedby") };
      }
    }
    return null;
  }, [...attempted]);
  if (!target) return null;
  attempted.add(target.record);
  const row = page.locator("#search-results-table .slick-row").filter({ has: page.locator(".slick-cell[aria-describedby$='documentId']").filter({ hasText: target.documentText }) });
  const control = row.locator(".slick-cell[aria-describedby$='familyGroup'] button").filter({ hasText: new RegExp(`^\\s*\\+\\s*${Number(target.label.replace(/\D/g, ""))}\\s*$`) });
  // The cell background selects a document in PPS; only its explicit family
  // button expands a family. A re-resolving record-bound locator also avoids
  // clicking a different row after SlickGrid recycles a numeric row index.
  if (await control.count() !== 1 || !await control.isVisible()) return { ...target, expanded: false, reason: "family_expansion_control_unavailable" };
  await control.click({ timeout: operationTimeout(timeoutMs) });
  const expanded = await waitForStableSemanticState(async () => {
    const snapshot = await ppubsRenderedSnapshot(page);
    const bound = snapshot.result_set_id === expected.result_set_id && snapshot.editor_value === expected.rendered_query;
    const row = snapshot.rows.find(item => cleanNumber(item.documentId) === target.record);
    return { ready: !bound || Boolean(row && /^[\u2212-]\s*\d*$/.test(String(row.familyGroup || "").trim())),
      signature: JSON.stringify([bound, row?.familyGroup, snapshot.rows.map(item => item.documentId), snapshot.viewport?.scroll_height]),
      value: { bound, snapshot } };
  }, { timeoutMs: operationTimeout(timeoutMs), pollMs: 250, stableSamples: 2 });
  if (expanded.value?.bound === false) throw new Error("query_binding_changed");
  return { ...target, expanded: Boolean(expanded.stable), reason: expanded.stable ? "family_control_expanded" : "family_expansion_not_confirmed" };
}

export async function collectPpubsRenderedResults(page, expected, taskDir, stem, { maxPages = 8, maxViewports = 128, incrementalTimeoutMs = 10000, familyTimeoutMs = 8000 } = {}) {
  const candidates = new Map();
  const pages = [];
  const familyAttempts = new Set(), familyActions = [], familyGaps = [];
  let latest = null, stopReason = "browser_result_unconfirmed", exhausted = false;
  const pageLimit = Math.max(1, Math.min(8, maxPages));
  const unsettledGaps = [];
  async function settledSnapshot() {
    const result = await waitForStableSemanticState(async () => {
      const value = await ppubsRenderedSnapshot(page), position = value.viewport;
      const bound = value.result_set_id === expected.result_set_id && value.editor_value === expected.rendered_query;
      const aligned = ppubsViewportAligned(value);
      return { ready: !bound || !value.loading && value.rows.length > 0 && aligned,
        signature: JSON.stringify([bound, value.rows, position, value.displayed_end]), value };
    }, { timeoutMs: operationTimeout(2500), pollMs: 100, stableSamples: 3 });
    if (!result.stable) throw new Error("virtual_render_not_stable");
    return result.value;
  }
  async function recordViewport(pageEvidence, value) {
    if (value.result_set_id !== expected.result_set_id || value.editor_value !== expected.rendered_query) throw new Error("query_binding_changed");
    const parsed = parsePpubsGridRows(value.rows);
    if (value.rows.length && parsed.length !== value.rows.length) throw new Error("result_grid_parse_incomplete");
    const screenshot = path.join(taskDir, "screenshots", `${stem}-page-${pageEvidence.page_index}-view-${pageEvidence.viewports.length + 1}.png`);
    await safeScreenshot(page, screenshot);
    pageEvidence.viewports.push({ ...value, screenshot_path: screenshot,
      screenshot_sha256: crypto.createHash("sha256").update(await fs.readFile(screenshot)).digest("hex"), observed_at: nowIso() });
    for (const candidate of parsed) candidates.set(candidate.record_number, { ...candidates.get(candidate.record_number), ...candidate });
  }
  try {
    const viewport = page.locator("#search-results-table .slick-viewport");
    await viewport.evaluate((node) => { node.scrollTop = 0; });
    for (let pageIndex = 1; pageIndex <= pageLimit; pageIndex++) {
      const pageEvidence = { page_index: pageIndex, current_page: pageIndex, result_set_id: expected.result_set_id, viewports: [] };
      pages.push(pageEvidence);
      let lastTop = -1, incrementDetected = false;
      for (let viewIndex = 1; viewIndex <= maxViewports; viewIndex++) {
        if (currentOperationDeadline() - Date.now() < 15000) { stopReason = "operation_deadline_truncated"; return finish(); }
        if (browserRateLimited((await freshState(page)).bodyText)) { stopReason = "browser_rate_limited"; return finish(); }
        latest = await settledSnapshot();
        if (latest.result_set_id !== expected.result_set_id || latest.editor_value !== expected.rendered_query) {
          stopReason = "query_binding_changed"; return finish();
        }
        if (pageEvidence.viewports.length && latest.displayed_end > (pageEvidence.loaded_range_end || Infinity)) {
          // A fast response may arrive during scrolling, before the explicit
          // bottom wait. Start a new bounded batch without skipping its rows.
          incrementDetected = true; break;
        }
        pageEvidence.loaded_range_end ??= latest.displayed_end;
        // Preserve the current window BEFORE clicking anything that may
        // scroll/recycle it. Restore that anchor after each expansion so the
        // subsequent forward sweep cannot silently skip leading/middle rows.
        await recordViewport(pageEvidence, latest);
        const anchorTop = latest.viewport?.top || 0;
        for (let group = 0; group < 32; group++) {
          if (browserRateLimited((await freshState(page)).bodyText)) { stopReason = "browser_rate_limited"; return finish(); }
          const action = await expandPpubsVisibleFamily(page, expected, familyAttempts, { timeoutMs: familyTimeoutMs });
          if (!action) break;
          familyActions.push(action);
          if (!action.expanded) familyGaps.push(action);
          latest = await settledSnapshot();
          await recordViewport(pageEvidence, latest);
          // Family expansion grows the displayed row count without fetching a
          // new 500-document batch. Keep this batch's baseline in sync.
          pageEvidence.loaded_range_end = Math.max(pageEvidence.loaded_range_end || 0, latest.displayed_end || 0);
          await viewport.evaluate((node, top) => { node.scrollTop = top; }, anchorTop);
          latest = await settledSnapshot();
          await recordViewport(pageEvidence, latest);
          if (latest.result_set_id !== expected.result_set_id || latest.editor_value !== expected.rendered_query) {
            stopReason = "query_binding_changed"; return finish();
          }
        }
        // This is an evidence batch, not a nonexistent PPS Next-page control.
        const position = latest.viewport;
        if (!position || position.height <= 0) { stopReason = "virtual_viewport_unavailable"; return finish(); }
        if (position.top + position.height >= position.scroll_height - 1) break;
        if (position.top === lastTop) { stopReason = "virtual_scroll_stalled"; return finish(); }
        lastTop = position.top;
        if (viewIndex === maxViewports) { stopReason = "virtual_viewport_limit"; return finish(); }
        await viewport.evaluate((node) => { node.scrollTop += Math.max(1, Math.floor(node.clientHeight * 0.8)); });
      }
      if (latest.total_hits !== null && candidates.size === latest.total_hits && !familyGaps.length) { exhausted = true; stopReason = "browser_results_exhausted"; return finish(); }
      if (pageIndex === pageLimit) { stopReason = "browser_page_limit_8"; return finish(); }
      if (incrementDetected) continue;
      const before = latest;
      // PPS auto-loads its next 500 documents at the last row. A momentary
      // bottom is not exhaustion: wait for a stable larger range/height/row set.
      await viewport.evaluate((node) => { node.scrollTop = node.scrollHeight; });
      const changed = await waitForStableSemanticState(async () => {
        const value = await ppubsRenderedSnapshot(page);
        const bound = value.result_set_id === expected.result_set_id && value.editor_value === expected.rendered_query;
        const grew = (value.displayed_end || 0) > (before.displayed_end || 0)
          || (value.viewport?.scroll_height || 0) > (before.viewport?.scroll_height || 0)
          || value.rows.some(row => !candidates.has(cleanNumber(row.documentId)));
        return { ready: !bound || grew, signature: JSON.stringify([bound, value.displayed_end, value.viewport?.scroll_height, value.rows]), value: { bound, snapshot: value } };
      }, { timeoutMs: operationTimeout(incrementalTimeoutMs), pollMs: 250, stableSamples: 2 });
      if (changed.value?.bound === false) { stopReason = "query_binding_changed"; return finish(); }
      if (!changed.stable) { stopReason = familyGaps.length ? "family_members_unretrieved" : "incremental_load_not_confirmed"; return finish(); }
    }
  } catch (error) {
    stopReason = ["query_binding_changed", "virtual_render_not_stable", "result_grid_parse_incomplete"].includes(error.message)
      ? error.message : `pagination_failed:${String(error.code || error.message).slice(0,100)}`;
    if (stopReason === "virtual_render_not_stable") unsettledGaps.push({ reason: stopReason, viewport: latest?.viewport || null });
  }
  return finish();
  function finish() {
    const missingCount = latest?.total_hits === null || latest?.total_hits === undefined ? null : Math.max(0, latest.total_hits - candidates.size);
    const unconfirmedFamilyCount = familyGaps.reduce((count, gap) => count + Number(String(gap.label || "").replace(/\D/g, "")), 0);
    if (stopReason === "family_members_unretrieved" && missingCount > unconfirmedFamilyCount) {
      stopReason = "result_rows_and_family_members_unretrieved";
    }
    const families = new Map();
    for (const candidate of candidates.values()) if (candidate.family_id) {
      const members = families.get(candidate.family_id) || [];
      members.push(candidate.record_number); families.set(candidate.family_id, members);
    }
    for (const candidate of candidates.values()) if (candidate.family_id) candidate.family_members = families.get(candidate.family_id);
    return { candidates: [...candidates.values()], result_pages: pages.filter(p => p.viewports.length),
      result_coverage: { total_hits: latest?.total_hits ?? null, retrieved_hits: candidates.size, reviewed_hits: null,
        retrieved_count: candidates.size, reported_total: latest?.total_hits ?? null, pages_retrieved: pages.filter(p => p.viewports.length).length,
        schema_valid: Boolean(candidates.size && !["query_binding_changed", "page_binding_changed", "result_grid_parse_incomplete"].includes(stopReason)),
        source_updated_at: null, truncated: !exhausted, completeness: exhausted ? "result_set_complete" : "partial",
        stop_reason: stopReason, reason: "Coverage refers only to this bound query's displayed result set, not exhaustive IP recall.",
        result_set_id: expected.result_set_id, max_pages: pageLimit, pagination_mode: "incremental_scroll",
        viewport_gaps: unsettledGaps,
        unretrieved_document_count: missingCount, unconfirmed_family_member_count: unconfirmedFamilyCount,
        family_expansion: { attempted: familyActions.length, expanded: familyActions.filter(item => item.expanded).length, gaps: familyGaps } } };
  }
}

export async function bindPpubsResultHistory(page, renderedQuery, screenshotPath, { timeoutMs = 12000 } = {}) {
  // Repeating an identical query can reuse its L-number. An L-number change
  // alone is not the query identity; bind the displayed results to the exact
  // query text and count in the official Search History UI.
  await page.locator("#searchHistory-tab").click({ timeout: operationTimeout(15000) });
  try {
    // New searches are inserted above the currently selected history row.
    // Virtualized history can retain its old scroll offset and omit the new
    // L-number from the rendered DOM until the official viewport is scrolled.
    await page.locator("#searchHistory-content .slick-viewport").evaluateAll(nodes => nodes.forEach(node => { node.scrollTop = 0; }));
    let historyViewports = 0;
    const result = await waitForStableSemanticState(async () => {
      const binding = await page.evaluate(() => {
        const resultSet = (document.querySelector("#searchResults-content .lQuery")?.textContent || "").replace(/[:\s]/g, "");
        for (const row of document.querySelectorAll("#searchHistory-content .slick-row")) {
          const label = (row.querySelector("[aria-describedby$='pNumber']")?.textContent || "").trim();
          if (label !== resultSet) continue;
          const query = (row.querySelector("[data-field='queryName']")?.textContent || "").trim();
          const count = (row.querySelector("[aria-describedby$='numResults']")?.textContent || "").trim().replaceAll(",", "");
          return { result_set_id: resultSet, query, total_hits: /^\d+$/.test(count) ? Number(count) : null };
        }
        return null;
      });
      // Identical queries can reuse an older L-number rather than insert a
      // new history row. Search only rendered viewports, with a hard bound;
      // never read SlickGrid's hidden backing data or accept an unbound set.
      if (!binding && historyViewports < 20) {
        await page.locator("#searchHistory-content .slick-viewport").evaluateAll(nodes => nodes.forEach(node => {
          node.scrollTop = node.scrollTop + node.clientHeight >= node.scrollHeight - 1 ? 0
            : node.scrollTop + Math.max(1, Math.floor(node.clientHeight * 0.8));
        }));
        historyViewports++;
      }
      return { ready: binding?.query === renderedQuery && binding?.total_hits !== null, signature: JSON.stringify(binding), binding };
    }, { timeoutMs: operationTimeout(timeoutMs), pollMs: Math.min(300, timeoutMs / 4), stableSamples: 2 });
    if (!result.stable) return null;
    await safeScreenshot(page, screenshotPath);
    return { ...result.binding, screenshot_path: screenshotPath,
      screenshot_sha256: crypto.createHash("sha256").update(await fs.readFile(screenshotPath)).digest("hex") };
  } finally { await page.locator("#searchResults-tab").click({ timeout: operationTimeout(15000) }); }
}

async function runPlannedQuery(args, config) {
  const taskDir = path.resolve(String(args.task_dir || ""));
  const queryId = String(args.query_id || "");
  const task = await readJson(path.join(taskDir, "task.json"));
  const plan = await readJson(path.join(taskDir, "search-plan.json"));
  assertPlanMatchesTask(task, plan);
  const resolved = resolveExactPlanEntry(plan, queryId);
  const { provider, entry: query } = resolved;
  await assertScenarioActionDispatch(taskDir, task, provider, query);
  assertTaskRoute(
    task, provider, String(query.operation || ""),
    String(query.jurisdiction || ""), String(query.right_type || ""),
  );
  const gate = browserRouteGate(task, provider, query, args.acceptance_probe === true
    || await acceptedBrowserRoute(taskDir, task, provider, query));
  if (gate) return gate;

  if (query.operation === "candidate_verification") {
    const candidateInputs = candidatePlanInputs(provider, query);
    const command = candidateCdpCommand(provider);
    if (command === "verify-candidate") {
      return verifyCandidate({ ...args, ...candidateInputs }, config);
    }
    if (command === "open-registry") {
      return openRegistryRecord({ ...args, ...candidateInputs }, config);
    }
  }

  if (REGISTRY_PLAN_PROVIDERS.has(provider)) {
    return openRegistrySearch({
      ...args,
      provider,
      query: String(query.q || query.query || ""),
      operation: String(query.operation || ""),
      jurisdiction: String(query.jurisdiction || ""),
      right_type: String(query.right_type || ""),
      source_key: String(query.source_key || ""),
      query_id: queryId,
    }, config);
  }
  assertCdpProviderAllowed(provider);

  const session = await connectSession(config);
  const provenance = sanitizedSession(session.version, session.sessionId);
  // PPS keeps a single Advanced Search console per browser session. Preserve
  // the official workspace across planned queries so that closing a completed
  // query does not race the service's short-lived "Console is already open"
  // session lock.
  let page;
  if (provider === "uspto_patent_browser" && recallIntegrityEnabled(task)) {
    for (const existing of session.context.pages().slice().reverse()) {
      if (existing.url().startsWith("https://ppubs.uspto.gov/pubwebapp/")
          && await existing.locator("trix-editor.trix[aria-label='Enter query text']").isVisible().catch(() => false)) { page = existing; break; }
    }
  }
  page ||= await newAutomaticPage(session.context, provider === "uspto_patent_browser" ? "preserve" : "inspect");
  const providerConfig = config.providers[provider];
  const startUrl = providerConfig.search_url || providerConfig.basic_search_url;
  const timeout = Number(config.cdp?.navigation_timeout_ms || 45000);
  if (provider === "uspto_patent_browser") {
    if (!recallIntegrityEnabled(task) || !await page.locator("trix-editor.trix[aria-label='Enter query text']").isVisible().catch(() => false)) {
      page = await openPpubsAdvancedWorkspace(session, page, startUrl, timeout);
    }
  }
  else await navigateAndRefresh(page, startUrl, timeout);
  const plannedExecution = task.schema_version === "2.4-free" ? browserPlannedQuery(provider, query, task) : null;
  const renderedQuery = plannedExecution?.rendered_query || (provider === "uspto_tmsearch_browser"
    ? formatTmQuery(query.q, query.strategy) : String(query.q));
  let actionError = "";
  let submitError = null;
  const executionEvents = [];
  const { screenshotPath, capturePath } = plannedQueryCapturePaths(taskDir, provider, queryId);
  try {
    executionEvents.push(await submitSearch(page, renderedQuery, provider, { strict: recallIntegrityEnabled(task),
      tmsearchFieldTags: plannedExecution?.search_mode === "field_tag" }));
    await page.waitForLoadState("domcontentloaded", { timeout: operationTimeout(timeout) }).catch(() => {});
  } catch (error) {
    actionError = String(error?.message || error);
    submitError = error;
  }
  const strictPpubs = recallIntegrityEnabled(task) && provider === "uspto_patent_browser";
  const semanticConfig = strictPpubs ? { ...config, ppubs_query_binding: { strict: true, renderedQuery,
    historyScreenshotPath: screenshotPath.replace(/\.png$/, "-history.png") } } : plannedExecution?.search_mode === "field_tag"
      ? { ...config, tmsearch_query_binding: { tmsearchQuery: renderedQuery,
        allowNonverbal: plannedExecution?.query_compiler_revision === "tm-figurative-fields-v1" } } : config;
  // Keep the former 12s binding + navigation-readiness budget, now shared by
  // one recoverable state machine; the operation/scheduler deadline is unchanged.
  const semantic = await observeAfterSubmission(page, provider, timeout + (strictPpubs ? 12000 : 0), semanticConfig, submitError);
  const historyBinding = semantic.history_binding || null;
  if (historyBinding) executionEvents.push({ action: "observe_query_binding", actor: "agent", at: nowIso(), ...historyBinding });
  let state = semantic.state || await freshState(page);
  // A query can be rerun after a transient official-site failure. Its prior
  // evidence must remain immutable because earlier evidence records bind the
  // screenshot hash, rather than being silently overwritten by the retry.
  let collection = null;
  if (strictPpubs && !actionError && semantic.stable && semantic.query_bound && semantic.candidates?.length) {
    collection = await collectPpubsRenderedResults(page, { result_set_id: semantic.ppubs.result_set_id, rendered_query: renderedQuery },
      taskDir, path.basename(screenshotPath, ".png"));
    state = await freshState(page);
  }
  const figurativeTm = plannedExecution?.query_compiler_revision === "tm-figurative-fields-v1";
  if (figurativeTm && !actionError && semantic.stable && semantic.query_bound && semantic.candidates?.length) {
    collection = await collectTmRenderedResults(page, semantic, taskDir, path.basename(screenshotPath, ".png"), semanticConfig);
    state = collection.last_state;
  }
  if (figurativeTm && collection?.last_screenshot_path) await fs.copyFile(collection.last_screenshot_path, screenshotPath);
  else await safeScreenshot(page, screenshotPath, { fullPage: false });
  const candidates = collection?.candidates || semantic.candidates || [];
  const challenge = Boolean(semantic.challenge);
  const accessStatus = task.schema_version === "2.4-free"
    ? classifyBrowserAccess(state.url, state.title, state.bodyText) : challenge ? "needs_user_action" : null;
  let status = "access_limited";
  let resultMessage = "";
  let detail = "";
  const paginationAccess = collection?.result_coverage.pagination_failure?.access_status;
  if (paginationAccess === "needs_user_action" || accessStatus) {
    status = paginationAccess === "needs_user_action" ? paginationAccess : accessStatus;
    detail = status === "needs_user_action" ? "The official USPTO page requires access verification in visible Chrome."
      : "The official page denied access without a supported login or CAPTCHA recovery step.";
  } else if (!actionError && !semantic.timed_out && candidates.length && (!collection || collection.result_coverage.schema_valid)) {
    status = "success";
  } else if (!actionError && !semantic.timed_out && semantic.noResult) {
    status = "no_result";
    resultMessage = "The rendered official page explicitly reported zero results.";
  } else if (!actionError && !semantic.timed_out && semantic.queryError) {
    detail = "The official USPTO page rejected the submitted query; it was not treated as a zero-result search.";
  } else {
    detail = actionError
      ? `Search completion could not be confirmed after refreshing page state: ${actionError.slice(0, 300)}`
      : semantic.timed_out
        ? "The rendered page did not reach a stable semantic result before timeout."
        : "The rendered page did not expose validated candidates or an explicit zero-result message.";
  }
  if (strictPpubs && !["success", "no_result", "needs_user_action"].includes(status) && !accessStatus) status = "failed";
  if (semantic.tmsearch_binding && !["success", "no_result", "needs_user_action"].includes(status) && !accessStatus) status = "failed";
  const tmCoverage = semantic.tmsearch_binding ? {
    total_hits: semantic.tmsearch_binding.total_hits, retrieved_hits: candidates.length, reviewed_hits: null,
    schema_valid: semantic.tmsearch_binding.query_bound && ["success", "no_result"].includes(status), source_updated_at: null,
    retrieved_count: candidates.length, reported_total: semantic.tmsearch_binding.total_hits,
    pages_retrieved: ["success", "no_result"].includes(status) ? 1 : 0,
    truncated: semantic.tmsearch_binding.total_hits === null ? true : semantic.tmsearch_binding.total_hits !== candidates.length,
    completeness: semantic.tmsearch_binding.total_hits === candidates.length ? "result_set_complete" : "partial",
    stop_reason: semantic.tmsearch_binding.total_hits === candidates.length ? "browser_results_exhausted" : "browser_current_page_only",
    reason: "Only the field-tag query's current rendered cards were captured; no unvisited pages are claimed." } : null;
  const capture = {
    ...provenance,
    status,
    ...(submitError ? { error_code: submitError.code || "AUTOMATIC_QUERY_FAILED", phase: submitError.phase || "observe_result", submission_state: submitError.submission_state || "uncertain" } :
      ["access_limited", "failed"].includes(status) ? { error_code: semantic.queryError ? "USPTO_QUERY_REJECTED" : semantic.timed_out ? "BROWSER_SEMANTIC_TIMEOUT" : "BROWSER_RESULT_UNCONFIRMED", phase: "observe_result", submission_state: "submitted" } :
        strictPpubs ? { phase: "observe_result", submission_state: "submitted" } : {}),
    query_id: queryId,
    query: String(query.q),
    right_type: String(query.right_type || ""),
    final_url: state.url,
    checked_at: nowIso(),
    screenshot_path: screenshotPath,
    candidates,
    ...(task.schema_version === "2.4-free" ? {
      result_coverage: collection?.result_coverage || tmCoverage || browserResultCoverage(strictPpubs && semantic.ppubs ? semantic.ppubs.result_text : state.bodyText, candidates.length, ["success", "no_result"].includes(status)),
    } : {}),
    ...(strictPpubs ? { result_pages: collection?.result_pages || [], result_set_id: semantic.ppubs?.result_set_id || "",
      history_binding: historyBinding,
      history_binding_attempts: semantic.history_binding_attempts || [],
      source_result_reused: executionEvents.find(e => e.action === "submit_query")?.previous_result_set_id === semantic.ppubs?.result_set_id } : {}),
    ...(figurativeTm ? { result_pages: collection?.result_pages || [] } : {}),
    ...(provider === "uspto_tmsearch_browser"
      ? { strategy: plannedExecution?.strategy || query.strategy, rendered_query: renderedQuery,
        ...(semantic.tmsearch_binding ? { query_binding: collection?.query_binding || semantic.tmsearch_binding } : {}) }
      : {
        mode: query.mode || "basic_search",
        search_focus: query.search_focus || query.right_type || "patent",
      }),
    ...(plannedExecution ? { query_semantics: plannedExecution } : {}),
    ...(resultMessage ? { result_message: resultMessage } : {}),
    ...(detail ? { detail } : {}),
    ...(browserRateLimited(state.bodyText) ? { error_code: "BROWSER_RATE_LIMITED",
      detail: "The official page reports Too Many Requests. This provider is paused; the dialog is not dismissed and no automatic resubmission is attempted." } : {}),
    ...(status === "failed" && !submitError && semantic.tmsearch_binding ? {
      error_code: semantic.tmsearch_binding.query_bound ? "BROWSER_RESULT_PARSE_FAILED" : "BROWSER_QUERY_BINDING_FAILED",
      detail: "TM Search result cards or field-tag query binding were not validated; no zero result or website-access denial is claimed." } : {}),
  };
  if (collection?.result_coverage.stop_reason === "BROWSER_RATE_LIMITED") Object.assign(capture, {
    error_code: "BROWSER_RATE_LIMITED", detail: "Earlier pages were retained; pagination reached a rate limit and no further pages were submitted." });
  executionEvents.push({ action: "observe_result", actor: "agent", at: nowIso(),
    stable: Boolean(semantic.stable), observed_count: candidates.length,
    ...(strictPpubs ? { result_set_id: semantic.ppubs?.result_set_id || "", query_bound: semantic.query_bound === true } : {}),
    ...(semantic.tmsearch_binding ? { query_binding: collection?.query_binding || semantic.tmsearch_binding } : {}),
    final_url: sanitizeEvidenceUrl(state.url), screenshot_sha256: crypto.createHash("sha256").update(await fs.readFile(screenshotPath)).digest("hex") });
  await attachExecutionReceipt(taskDir, task, provider, query, executionEvents, capture);
  assertNoSensitiveKeys(capture);
  await writeJsonAtomic(capturePath, capture);
  if (ownedAutomaticPages.has(page)) ownedAutomaticPages.set(page,
    status === "needs_user_action" || capture.error_code === "BROWSER_RATE_LIMITED" || provider === "uspto_patent_browser" && recallIntegrityEnabled(task) ? "preserve" : "close");
  return { status, provider, query_id: queryId, capture_path: capturePath,
    ...Object.fromEntries(["detail", "error_code", "phase", "submission_state"].filter(key => capture[key]).map(key => [key, capture[key]])) };
}

async function matchingPatentResultRow(page, record) {
  const recordClean = cleanNumber(record);
  const rows = page.locator("table tr");
  const count = Math.min(await rows.count(), 200);
  for (let index = 0; index < count; index += 1) {
    const row = rows.nth(index);
    const rowText = await row.innerText().catch(() => "");
    if (cleanNumber(rowText).includes(recordClean)) return row;
  }
  return null;
}

async function matchingPatentResultLink(row, labels = ["Text", "Preview", "PDF"]) {
  if (!row) return null;
  for (const label of labels) {
    const link = row.locator("a").filter({ hasText: label }).first();
    if (await link.isVisible().catch(() => false)) return link;
  }
  return null;
}

async function capturePatentPdfFigure(context, page, row, taskDir, record, timeout, config) {
  const pdfLink = await matchingPatentResultLink(row, ["PDF"]);
  if (!pdfLink) return { attempted: false, path: null };
  const href = await pdfLink.getAttribute("href").catch(() => "");
  if (!href) return { attempted: true, path: null };
  const pdfUrl = new URL(href, page.url()).toString();
  let pdfPage = context.pages().find((item) =>
    item.url().includes("/api/pdf/")
      && cleanNumber(item.url()).includes(cleanNumber(record))
  );
  const ownsPage = !pdfPage;
  pdfPage ||= await newAutomaticPage(context, "close");
  try {
    if (ownsPage) {
      await pdfPage.goto(pdfUrl, { waitUntil: "domcontentloaded", timeout: operationTimeout(timeout) }).catch(() => {});
    }
    const stable = await waitForStableSemanticState(async () => {
      const screenshot = await pdfPage.screenshot({ animations: "disabled" }).catch(() => null);
      const identityMatches = cleanNumber(pdfPage.url()).includes(cleanNumber(record));
      return {
        ready: Boolean(identityMatches && renderedPatentPdfScreenshot(screenshot)),
        signature: screenshot
          ? crypto.createHash("sha256").update(screenshot).digest("hex")
          : "",
        screenshot,
      };
    }, {
      timeoutMs: timeout,
      pollMs: Number(config.cdp?.semantic_poll_ms || 750),
      stableSamples: Number(config.cdp?.semantic_stable_samples || 3),
    });
    if (!stable.stable || !stable.screenshot) return { attempted: true, path: null };
    const figurePath = path.join(
      taskDir, "screenshots", `uspto-patent-${slug(record)}-figures.png`,
    );
    await fs.writeFile(figurePath, stable.screenshot, { mode: 0o600 });
    return { attempted: true, path: figurePath };
  } finally {
    if (ownsPage) {
      await releaseOwnedPage(pdfPage, true, null);
      ownedAutomaticPages.delete(pdfPage);
    }
  }
}

function isDesignRecord(record) {
  return /^(?:US)?D\d{6,8}(?:S\d?)?$/.test(cleanNumber(record));
}

export function patentBasicSearchTerm(record) {
  const normalized = cleanNumber(record);
  const design = normalized.match(/^(?:US)?D(\d{6,8})(?:S\d?)?$/);
  if (design) return `D${design[1]}`;
  const utility = normalized.match(/^US(\d{6,11})(?:[A-Z]\d?)?$/);
  return utility?.[1] || String(record || "").trim();
}

async function firstPatentDrawing(page) {
  const elements = page.locator("img, canvas, object, embed");
  const count = Math.min(await elements.count(), 120);
  for (let index = 0; index < count; index += 1) {
    const element = elements.nth(index);
    if (!await element.isVisible().catch(() => false)) continue;
    const info = await element.evaluate((node) => {
      const rect = node.getBoundingClientRect();
      const source = node.currentSrc || node.src || node.data || "";
      const alt = node.alt || "";
      return {
        width: Math.max(Number(node.naturalWidth || 0), rect.width),
        height: Math.max(Number(node.naturalHeight || 0), rect.height),
        source: String(source),
        alt: String(alt),
      };
    }).catch(() => null);
    if (!info || info.width < 180 || info.height < 180) continue;
    if (/logo|header|icon|sprite/i.test(`${info.source} ${info.alt}`)) continue;
    return element;
  }
  return null;
}

async function patentDetailSnapshot(page, record, parsed, externalDrawingReady = false) {
  const state = await freshState(page);
  const bodyClean = cleanNumber(state.bodyText);
  const requested = cleanNumber(record);
  const identityMatches = bodyClean.includes(requested) || cleanNumber(state.url).includes(requested);
  const title = parsed?.title
    || extractAfterLabel(state.bodyText, ["Title"])
    || "";
  let legalStatus = parsed?.legal_status
    || extractAfterLabel(state.bodyText, ["Status", "Legal Status"])
    || "";
  if (!legalStatus && /date of patent|united states (?:design )?patent/i.test(state.bodyText)) {
    legalStatus = "Issued";
  }
  const owners = parsed?.owners?.length
    ? parsed.owners
    : [extractAfterLabel(state.bodyText, ["Assignee", "Applicant", "Applicant(s)"])].filter(Boolean);
  const classifications = extractPatentClassifications(state.bodyText);
  const drawing = isDesignRecord(record) && !externalDrawingReady
    ? await firstPatentDrawing(page)
    : null;
  const designDrawingReady = !isDesignRecord(record) || externalDrawingReady || Boolean(drawing);
  const ready = identityMatches
    && Boolean(title)
    && Boolean(legalStatus)
    && owners.length > 0
    && designDrawingReady
    && (!isDesignRecord(record) || classifications.length > 0);
  return {
    ready,
    signature: JSON.stringify({
      url: state.url,
      identityMatches,
      title,
      legalStatus,
      owners,
      classifications,
      designDrawingReady,
    }),
    state,
    page_record_number: identityMatches ? record : "",
    title,
    legal_status: legalStatus,
    owners,
    classifications,
    drawing_ready: designDrawingReady,
    noResult: explicitNoResult(state.bodyText),
    challenge: detectChallenge(state.url, state.title, state.bodyText),
  };
}

export function extractAfterLabel(text, labels) {
  const lines = String(text || "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  for (let index = 0; index < lines.length; index += 1) {
    for (const label of labels) {
      const escaped = String(label).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const pattern = new RegExp(`^${escaped}(?![\\p{L}\\p{N}_])\\s*[:#-]?\\s*(.*)$`, "iu");
      const match = lines[index].match(pattern);
      if (match?.[1]) return match[1].trim();
      if (match && lines[index + 1]) return lines[index + 1];
    }
  }
  return "";
}

function uniqueLabeledValues(text, labels) {
  return [...new Set(labels.map((label) => extractAfterLabel(text, [label])).filter(Boolean))];
}

export function extractPatentClassifications(text) {
  return uniqueLabeledValues(text, [
    "Locarno Classification", "Locarno Class", "U.S. Classification", "US Classification",
    "Current U.S. Class", "International Classification", "IPC", "CPC", "Classification",
  ]);
}

export function extractTsdrClassifications(text) {
  return uniqueLabeledValues(text, [
    "International Class", "International Classes", "Nice Class", "Nice Classes", "Class",
  ]);
}

export function extractTsdrDesignCodes(text) {
  return uniqueLabeledValues(text, [
    "Design Search Code", "Design Search Codes", "Design Code", "Design Codes",
  ]);
}

export async function firstTsdrMarkMedia(page) {
  const selectors = [
    "#markImage", "img[id*='markImage' i]", "img[src*='getMarkImage' i]",
    "[data-testid*='mark' i] img", "img[alt*='mark image' i]", ".mark-image img",
  ];
  for (const selector of selectors) {
    const candidates = page.locator(selector);
    const count = Math.min(await candidates.count(), 20);
    for (let index = 0; index < count; index += 1) {
      const element = candidates.nth(index);
      if (!await element.isVisible().catch(() => false)) continue;
      const usable = await element.evaluate((node) => {
        const rect = node.getBoundingClientRect();
        const width = Math.max(Number(node.naturalWidth || 0), rect.width);
        const height = Math.max(Number(node.naturalHeight || 0), rect.height);
        return width >= 80 && height >= 80;
      }).catch(() => false);
      if (usable) return element;
    }
  }
  return null;
}

export function ppubsTextEvidenceMetadata(renderedText) {
  if (typeof renderedText !== "string" || !renderedText.trim()) throw new Error("PPS_TEXT_EVIDENCE_EMPTY");
  const digest = crypto.createHash("sha256").update(canonicalJson(renderedText)).digest("hex");
  return { text_evidence_revision: "retained-text-v1", text_hash_algorithm: "sha256-canonical-json-utf8",
    rendered_text_stage: "source", rendered_text_sha256: digest,
    source_rendered_text_stage: "source", source_rendered_text_sha256: digest };
}

export function extractPpubsAbstract(value) {
  if (typeof value !== "string") return "";
  const text = value.replace(/\r\n?/g, "\n");
  const heading = /(?:^|\n)[\t ]*(?:\(57\)[\t ]*)?ABSTRACT(?:[\t ]+OF[\t ]+THE[\t ]+DISCLOSURE)?[\t ]*:?[\t ]*(?:\n|$)/i.exec(text);
  if (!heading) return "";
  const following = text.slice(heading.index + heading[0].length);
  // PPS 4.3 inserts Background/Summary before description/claims. Stop at
  // actual section headings, never at these words inside an abstract sentence.
  const boundary = /^[\t ]*(?:BACKGROUND(?:[\t ]*\/[\t ]*SUMMARY)?(?: OF (?:THE )?INVENTION)?|SUMMARY(?: OF (?:THE )?INVENTION)?|DESCRIPTION|(?:BRIEF|DETAILED) DESCRIPTION(?: OF (?:THE )?(?:DRAWINGS|INVENTION|PREFERRED EMBODIMENTS))?|CLAIMS|WHAT IS CLAIMED(?: IS)?)[\t ]*:?[\t ]*$/im.exec(following);
  return (boundary ? following.slice(0, boundary.index) : following).trim();
}

export async function ppubsPublishedDocumentSnapshot(page) {
  return page.locator("#documentViewer-content").evaluate((viewer) => {
    const doc = viewer.querySelector(".textViewer .realdocument");
    const text = (selector) => {
      const node = doc?.querySelector(selector), rect = node?.getBoundingClientRect();
      return rect?.width > 0 && rect?.height > 0 ? (node.innerText || "").trim() : "";
    };
    return {
      page_record_number: text(".meta-guid:not(.metadata) > div").replace(/[^A-Za-z0-9]/g, "").toUpperCase(),
      title: text("h2.meta-inventionTitle"),
      application_number: text(".meta-applicationNumber:not(.metadata) > div"),
      published_at: text(".meta-datePublished:not(.metadata) > div"),
      filed_at: text(".meta-applicationFilingDate:not(.metadata) > div"),
      inventor_information: text(".meta-inventorsInfoGroup:not(.metadata)"),
      classifications: text(".meta-usClassCurrent:not(.metadata) > div").replace(/^US\s+CLASS\s+CURRENT:\s*/i, "").split(",").map(x => x.trim()).filter(Boolean),
      rendered_text: (doc?.innerText || "").trim().slice(0, 200000),
      legal_status: "", owners: [],
    };
  });
}

export async function capturePpubsDocumentPages(page, record, taskDir, stem, { maxPages = 20, pageNumbers = null } = {}) {
  const images = [], pages = [];
  let total = null, stopReason = "image_view_unavailable", lastHash = "";
  try {
    await page.locator("#documentViewer-content [data-id='switchToImage']").click({ timeout: operationTimeout(10000) });
    const first = page.locator("#documentViewer-content [data-id='firstPage']");
    if (await first.isEnabled()) await first.click({ timeout: operationTimeout(10000) });
    const requested = pageNumbers === null ? null : [...pageNumbers];
    if (requested && (!requested.length || requested.some(value => !Number.isSafeInteger(value) || value < 1) || new Set(requested).size !== requested.length)) {
      throw new Error("requested_document_pages_invalid");
    }
    const ordinals = requested || Array.from({ length: Math.min(20, maxPages) }, (_, index) => index + 1);
    for (const ordinal of ordinals) {
      if (currentOperationDeadline() - Date.now() < 15000) { stopReason = "operation_deadline_truncated"; break; }
      if (requested) {
        const pageInput = page.locator("#documentViewer-content input[data-id='pagetext-input']");
        await pageInput.fill(String(ordinal), { timeout: operationTimeout(10000) });
        await pageInput.press("Enter", { timeout: operationTimeout(10000) });
      }
      const ready = await waitForStableSemanticState(async () => {
        const value = await page.locator("#documentViewer-content").evaluate((viewer) => {
          const input = viewer.querySelector("input[data-id='pagetext-input']");
          const image = viewer.querySelector(".image-canvas-wrapper .image-holder img");
          const total = (viewer.querySelector("[data-id='pageNumber'] .page-of")?.textContent || "").match(/of\s+(\d+)/i);
          const rect = image?.getBoundingClientRect();
          return { page: Number(input?.value || 0), total: total ? Number(total[1]) : null,
            image_ready: Boolean(image?.complete && image?.naturalWidth > 0 && rect?.width > 0 && rect?.height > 0) };
        });
        return { ready: value.page === ordinal && value.total > 0 && value.image_ready,
          signature: JSON.stringify(value), value };
      }, { timeoutMs: operationTimeout(12000), pollMs: 400, stableSamples: 3 });
      if (!ready.stable) { stopReason = "image_page_not_confirmed"; break; }
      total = ready.value.total;
      const wrapper = page.locator("#documentViewer-content .image-canvas-wrapper");
      // Capture only pixels rendered by the official UI. Image request URLs
      // contain short-lived request tokens and are never read or serialized.
      // PPS updates the page counter before replacing the displayed bitmap.
      // Require stable changed pixels, not merely an incremented page number.
      const changed = await waitForStableSemanticState(async () => {
        const pixels = await wrapper.screenshot({ animations: "disabled", timeout: operationTimeout(10000) });
        const digest = crypto.createHash("sha256").update(pixels).digest("hex");
        return { ready: digest !== lastHash, signature: digest, pixels, digest };
      }, { timeoutMs: operationTimeout(15000), pollMs: 400, stableSamples: 3 });
      if (!changed.stable) { stopReason = "image_page_pixels_reused"; break; }
      const { pixels, digest } = changed;
      lastHash = digest;
      const imagePath = path.join(taskDir, "screenshots", `${stem}-document-page-${ordinal}.png`);
      await fs.writeFile(imagePath, pixels, { mode: 0o600 });
      pages.push({ record_number: record, page: ordinal, total_pages: total, path: imagePath, sha256: digest });
      images.push({ path: imagePath, label: `USPTO ${record} published document page ${ordinal}/${total}`,
        role: "official_document_page" });
      if (requested) { stopReason = "requested_document_pages_exhausted"; continue; }
      if (ordinal === total) { stopReason = "published_document_pages_exhausted"; break; }
      if (ordinal === Math.min(20, maxPages)) { stopReason = "document_page_limit_20"; break; }
      const next = page.locator("#documentViewer-content [data-id='nextPage']");
      if (!await next.isEnabled()) { stopReason = "document_next_page_unavailable"; break; }
      await next.click({ timeout: operationTimeout(10000) });
    }
  } catch (error) { stopReason = `document_image_failed:${sanitizeSensitiveText(error.code || error.message).slice(0, 100)}`; }
  finally {
    const textButton = page.locator("#documentViewer-content [data-id='switchToText']");
    if (await textButton.isVisible().catch(() => false)) await textButton.click({ timeout: operationTimeout(10000) }).catch(() => {});
  }
  return { evidence_images: images, document_pages: pages, media_coverage: {
    expected_count: total, retrieved_count: pages.length,
    completeness: stopReason === "published_document_pages_exhausted" ? "complete" : pages.length ? "partial" : "unknown",
    ...(pageNumbers !== null ? { requested_pages: pageNumbers, requested_pages_complete:
      pageNumbers.every(number => pages.some(value => value.page === number)) } : {}),
    stop_reason: stopReason, reason: "Coverage concerns this published document's image pages only, not current legal status or ownership." } };
}

async function verifyPpubsPublishedDocument(args, config, resolved) {
  const taskDir = path.resolve(String(args.task_dir)), provider = "uspto_patent_browser";
  const record = cleanNumber(args.record), queryId = args.query_id;
  const reading = plannedReadingScope(resolved.entry, resolved.task);
  if (reading?.required_facts.includes("current_status")) {
    return { status: "access_limited", provider, record, error_code: "CURRENT_STATUS_ROUTE_UNAVAILABLE",
      phase: "validate_capability", submission_state: "not_submitted",
      detail: "Patent Public Search provides published content, not current legal status. No duplicate document request was submitted." };
  }
  const session = await connectSession(config);
  let page;
  for (const existing of session.context.pages().slice().reverse()) {
    if (existing.url().startsWith("https://ppubs.uspto.gov/pubwebapp/")
        && await existing.locator("trix-editor.trix[aria-label='Enter query text']").isVisible().catch(() => false)) { page = existing; break; }
  }
  if (!page) {
    page = await newAutomaticPage(session.context, "preserve");
    page = await openPpubsAdvancedWorkspace(session, page, config.providers[provider].search_url, Number(config.cdp?.navigation_timeout_ms || 45000));
  }
  const { screenshotPath, capturePath } = plannedQueryCapturePaths(taskDir, provider, queryId);
  const semantics = browserPlannedQuery(provider, resolved.entry, resolved.task);
  const events = [];
  let document = null, historyBinding = null, bindingAttempts = [], media = {}, issue = null, status = "failed", noResult = false;
  const journalIdentity = { provider, right_type: args.right_type, record_number: record,
    candidate_id: args.candidate_id, query_id: queryId };
  await updateCandidateJournal(taskDir, { ...journalIdentity, status: "pending", phase: "retrieve_published_document",
    opened_at: nowIso(), final_url: sanitizeEvidenceUrl(page.url()) });
  try {
    events.push(await submitSearch(page, semantics.rendered_query, provider, { strict: true }));
    const result = await waitForSearchSemanticState(page, provider, operationTimeout(32000), {
      ...config, ppubs_query_binding: { strict: true, renderedQuery: semantics.rendered_query,
        historyScreenshotPath: screenshotPath.replace(/\.png$/, "-history.png") } });
    historyBinding = result.history_binding;
    bindingAttempts = result.history_binding_attempts || [];
    if (historyBinding) events.push({ action: "observe_query_binding", actor: "agent", at: nowIso(), ...historyBinding });
    if (!historyBinding) throw new Error("PUBLISHED_DOCUMENT_QUERY_BINDING_MISSING");
    noResult = Boolean(result.stable && result.query_bound && result.noResult);
    if (noResult) status = "no_result";
    else {
      if (!result.stable || !result.query_bound || !result.candidates?.some(row => cleanNumber(row.record_number) === record)) {
        throw new Error("PUBLISHED_DOCUMENT_EXACT_RESULT_MISSING");
      }
      const cells = page.locator("#search-results-table .slick-cell[aria-describedby$='documentId'] button");
      let match = null;
      for (let i = 0; i < await cells.count(); i++) {
        const cell = cells.nth(i);
        if (cleanNumber(await cell.textContent()) === record) { match = cell; break; }
      }
      if (!match) throw new Error("PUBLISHED_DOCUMENT_EXACT_CONTROL_MISSING");
      await match.click({ timeout: operationTimeout(15000) });
      const toText = page.locator("#documentViewer-content [data-id='switchToText']");
      if (await toText.isVisible().catch(() => false)) await toText.click({ timeout: operationTimeout(10000) });
      const loaded = await waitForStableSemanticState(async () => {
        const value = await ppubsPublishedDocumentSnapshot(page);
        return { ready: value.page_record_number === record && Boolean(value.title && value.rendered_text),
          signature: JSON.stringify(value), value };
      }, { timeoutMs: operationTimeout(reading ? Math.min(45000, Number(config.cdp?.navigation_timeout_ms || 45000)) : 20000),
        pollMs: 400, stableSamples: 3 });
      if (!loaded.stable) throw new Error("PUBLISHED_DOCUMENT_IDENTITY_UNCONFIRMED");
      document = loaded.value;
      if (!reading || reading.required_facts.some(fact => ["representative_figures", "protection_content"].includes(fact))) {
        media = await capturePpubsDocumentPages(page, record, taskDir, path.basename(screenshotPath, ".png"),
          reading?.reading_scope.page_numbers.length ? { pageNumbers: reading.reading_scope.page_numbers } : {});
      }
      if (reading) {
        const abstract = extractPpubsAbstract(document.rendered_text);
        document.abstract = abstract;
        const obtained = [];
        if (abstract) obtained.push("abstract");
        if (reading.required_facts.includes("representative_figures") && media.media_coverage?.requested_pages_complete) obtained.push("representative_figures");
        if (reading.required_facts.includes("protection_content") && document.rendered_text && document.rendered_text.length < 200000 && media.media_coverage?.completeness === "complete") obtained.push("protection_content");
        document.satisfied_facts = obtained;
      }
      const after = await ppubsPublishedDocumentSnapshot(page);
      if (after.page_record_number !== record || after.title !== document.title) {
        document = null; media = {}; throw new Error("PUBLISHED_DOCUMENT_IDENTITY_CHANGED");
      }
      status = reading && reading.required_facts.every(fact => document.satisfied_facts.includes(fact))
        ? "success" : "access_limited";
    }
  } catch (error) { issue = error; }
  const state = await freshState(page);
  const access = classifyBrowserAccess(state.url, state.title, state.bodyText);
  if (access && (!document || browserRateLimited(state.bodyText))) status = access;
  await safeScreenshot(page, screenshotPath);
  const capture = {
    ...sanitizedSession(session.version, session.sessionId), status, provider,
    task_id: resolved.task.task_id, operation: "candidate_verification", query_id: queryId,
    candidate_id: args.candidate_id, record_number: record, right_type: args.right_type,
    page_record_number: document?.page_record_number || "", publication_number: document ? record : "",
    ...(document || {}), ...media, final_url: sanitizeEvidenceUrl(state.url), checked_at: nowIso(), screenshot_path: screenshotPath,
    ...(reading ? { workflow_correction_revision: resolved.task.workflow_correction_revision, ...reading,
      content_retrieval_status: status === "success" ? "completed" : "incomplete" } : {}),
    query_semantics: semantics, history_binding: historyBinding, history_binding_attempts: bindingAttempts,
    submission_state: events.some(e => e.action === "submit_query") ? "submitted" : issue?.submission_state || "not_submitted",
    phase: document ? reading ? "retrieve_requested_content" : "verify_current_status" : issue?.phase || "retrieve_published_document",
    error_code: document ? reading ? status === "success" ? "" : "REQUESTED_CONTENT_INCOMPLETE" : "MISSING_OFFICIAL_CURRENT_STATUS" : noResult ? "" : issue?.code || "PUBLISHED_DOCUMENT_RETRIEVAL_FAILED",
    detail: document ? reading ? "Requested published-content scope was inspected. Read the satisfied_facts and requested page coverage; current legal status and ownership remain unknown." : "Published document and available image pages were retrieved with exact identity. Current legal status and current ownership are not established by the publication; this is incomplete verification, not a website access denial."
      : noResult ? "The bound official known-number query reported zero results." : sanitizeSensitiveText(issue?.message || "Official document retrieval did not complete"),
    ...(noResult ? { result_message: "The bound official known-number query reported zero results." } : {}),
    ...(document ? { text_evidence_revision: "retained-text-v1",
      document_retrieval: { status: "success", authority_scope: "published_document_only", identity_match: true,
      record_number: record, title: document.title, ...ppubsTextEvidenceMetadata(document.rendered_text),
      missing_official_current_status: true, missing_official_current_owner: true, document_pages: media.document_pages || [] } } : {}),
    ...(browserRateLimited(state.bodyText) ? { error_code: "BROWSER_RATE_LIMITED",
      detail: "The official page reports Too Many Requests. This provider is paused; available publication evidence does not establish current legal status." } : {}),
  };
  events.push({ action: "observe_result", actor: "agent", at: nowIso(), stable: Boolean(document || noResult),
    identity: document?.page_record_number || "", final_url: capture.final_url,
    screenshot_sha256: crypto.createHash("sha256").update(await fs.readFile(screenshotPath)).digest("hex") });
  await attachExecutionReceipt(taskDir, resolved.task, provider, resolved.entry, events, capture);
  assertNoSensitiveKeys(capture);
  await writeJsonAtomic(capturePath, capture);
  await updateCandidateJournal(taskDir, { ...journalIdentity, status, title: document?.title || "",
    phase: capture.phase, error_code: capture.error_code, detail: capture.detail,
    authority_scope: document ? "published_document_only" : "", document_retrieval_status: document ? "success" : "failed",
    final_url: capture.final_url, screenshot_path: screenshotPath, capture_path: capturePath, completed_at: nowIso() });
  return { status, provider, record, capture_path: capturePath, error_code: capture.error_code, phase: capture.phase, detail: capture.detail };
}

// TSDR's displayed heading and DOM section key are not always identical.
const TSDR_SECTION_KEYS = Object.freeze({ "Mark Information": "markInformation" });

export async function tsdrRenderedSnapshot(page) {
  return page.evaluate(sectionKeys => {
    const visible = node => { const r = node?.getBoundingClientRect(); return Boolean(r?.width && r?.height && getComputedStyle(node).visibility !== "hidden"); };
    const fields = root => {
      const output = {};
      for (const key of root?.querySelectorAll(".key") || []) {
        const value = key.nextElementSibling;
        if (!visible(key) || !value?.classList.contains("value") || !visible(value)) continue;
        const label = key.textContent.trim().replace(/:$/, ""), text = value.innerText.trim();
        if (text) (output[label] ||= []).push(text);
      }
      return output;
    };
    const section = label => [...document.querySelectorAll("span[data-sectiontitle]")]
      .find(node => node.getAttribute("data-sectiontitle") === (sectionKeys[label] || label))?.closest(".expand_wrapper");
    const summary = fields(document.querySelector("#summary"));
    const goods = fields(section("Goods and Services")), owner = fields(section("Current Owner(s) Information"));
    const mark = fields(section("Mark Information"));
    const rendered = fields(document);
    return { page_case_number: summary["US Serial Number"]?.[0] || "",
      registration_number: summary["US Registration Number"]?.[0] || "", mark_text: summary.Mark?.[0] || "",
      case_status: summary.Status?.[0] || "", owners: owner["Owner Name"] || [], goods_services: goods.For || [],
      classes: [...new Set((goods["International Class(es)"] || []).flatMap(value => [...value.matchAll(/\b\d{3}\b/g)].map(m => m[0])))],
      design_codes: ["Design Search Code(s)", "Design Search Code", "Design Search Codes", "Design Code", "Design Codes"].flatMap(label => rendered[label] || []),
      ...(Object.keys(mark).length ? { mark_description: mark["Mark Description"]?.[0] || mark["Description of Mark"]?.[0] || "",
        mark_drawing_type: mark["Mark Drawing Type"]?.[0] || "",
        mark_information: { section_observed: true, rendered_fields: Object.keys(mark), literal_elements: mark["Mark Literal Elements"]?.[0] || "" } } : {}),
      status_date: summary["Status Date"]?.[0] || "", generated_on: summary["Generated on"]?.[0] || "" };
  }, TSDR_SECTION_KEYS);
}

export async function expandTsdrVerificationSections(page, expectedSerial, { markInformation = false } = {}) {
  const serial = cleanNumber(expectedSerial);
  if (serial.length !== 8 || cleanNumber((await tsdrRenderedSnapshot(page)).page_case_number) !== serial) throw new Error("TSDR_RECORD_IDENTITY_MISMATCH");
  const expanded = [];
  for (const label of ["Goods and Services", "Current Owner(s) Information", ...(markInformation ? ["Mark Information"] : [])]) {
    const heading = page.locator(`span[data-sectiontitle="${TSDR_SECTION_KEYS[label] || label}"]`);
    const wrapper = page.locator(".expand_wrapper").filter({ has: heading });
    if (await wrapper.count() !== 1) throw new Error("TSDR_SECTION_CONTROL_UNAVAILABLE");
    const content = wrapper.locator(".toggle_container").first();
    if (!await content.isVisible()) {
      await heading.locator("a.sectionLink").click({ timeout: operationTimeout(10000) });
      await content.waitFor({ state: "visible", timeout: operationTimeout(10000) });
      expanded.push(label);
    }
    if (cleanNumber((await tsdrRenderedSnapshot(page)).page_case_number) !== serial) throw new Error("TSDR_RECORD_IDENTITY_CHANGED");
  }
  return expanded;
}

async function verifyCandidate(args, config) {
  const taskDir = path.resolve(String(args.task_dir || ""));
  const resolved = await resolvePlannedCandidateAction(taskDir, args);
  const gate = browserRouteGate(resolved.task, resolved.inputs.provider, resolved.entry, args.acceptance_probe === true
    || await acceptedBrowserRoute(taskDir, resolved.task, resolved.inputs.provider, resolved.entry));
  if (gate) return gate;
  args = { ...args, ...resolved.inputs };
  const provider = args.provider;
  const record = args.record;
  const rightType = args.right_type;
  const candidateId = args.candidate_id;
  const queryId = args.query_id;
  if (!["uspto_tsdr", "uspto_patent_browser"].includes(provider) || !record) {
    throw new Error("verify-candidate requires a planned US patent or TSDR candidate action");
  }
  if (!REGISTRY_RIGHT_TYPES.has(rightType)) {
    throw new Error("verify-candidate requires an explicit supported --right-type");
  }
  if (provider === "uspto_patent_browser" && recallIntegrityEnabled(resolved.task)) {
    return verifyPpubsPublishedDocument(args, config, resolved);
  }
  const session = await connectSession(config);
  const provenance = sanitizedSession(session.version, session.sessionId);
  const page = await newAutomaticPage(session.context);
  const timeout = Number(config.cdp?.navigation_timeout_ms || 45000);
  let state;
  let candidate = null;
  let actionError = "";
  let patentSemantic = null;
  let detailOpened = false;
  let figureCaptureAttempted = false;
  let recordStable = false;
  const evidenceImages = [];
  const executionEvents = [];
  const strictTsdr = provider === "uspto_tsdr" && recallIntegrityEnabled(resolved.task);
  const candidatePaths = candidateCapturePaths(taskDir, provider, record, queryId, resolved.task);

  if (provider === "uspto_tsdr") {
    const serial = record.replace(/\D/g, "");
    if (serial.length !== 8) throw new Error("TSDR record must be an eight-digit serial number");
    ({ state } = await navigateAndRefresh(
      page,
      `https://tsdr.uspto.gov/#caseNumber=${serial}&caseSearchType=US_APPLICATION&caseType=SERIAL_NO&searchType=statusSearch`,
      timeout,
    ));
    executionEvents.push({ action: "navigate_record", actor: "agent", at: nowIso(),
      record_number: record, url: sanitizeEvidenceUrl(page.url()) });
    if (resolved.task.schema_version !== "2.4-free") await page.waitForTimeout(1500);
    state = await freshState(page);
    if (resolved.task.schema_version === "2.4-free") {
      const semantic = await waitForStableSemanticState(async () => {
        const snapshot = await freshState(page);
        const identity = strictTsdr ? (await tsdrRenderedSnapshot(page)).page_case_number
          : extractAfterLabel(snapshot.bodyText, ["Serial Number", "Case Number"]);
        return { ready: cleanNumber(identity) === cleanNumber(record)
            || explicitNoResult(snapshot.bodyText) || classifyBrowserAccess(snapshot.url, snapshot.title, snapshot.bodyText),
          signature: registryPageBindingDigest({ url: snapshot.url, body: snapshot.bodyText }), state: snapshot };
      }, { timeoutMs: timeout, stableSamples: Number(config.cdp?.semantic_stable_samples || 3),
        pollMs: Number(config.cdp?.semantic_poll_ms || 750) });
      state = semantic.state || state;
      recordStable = Boolean(semantic.stable);
    }
    if (strictTsdr && recordStable && cleanNumber((await tsdrRenderedSnapshot(page)).page_case_number) === cleanNumber(record)
        && !classifyBrowserAccess(state.url, state.title, state.bodyText)) {
      try {
        const expanded = await expandTsdrVerificationSections(page, serial, { markInformation: rightType === "trademark_figurative" });
        executionEvents.push({ action: "expand_record_sections", actor: "agent", at: nowIso(), record_number: serial, sections: expanded });
        const loaded = await waitForStableSemanticState(async () => {
          const fields = await tsdrRenderedSnapshot(page);
          return { ready: cleanNumber(fields.page_case_number) === serial && Boolean((fields.mark_text || rightType === "trademark_figurative" && fields.mark_information?.section_observed) && fields.case_status
              && fields.owners.length && fields.goods_services.length && fields.classes.length),
            signature: JSON.stringify(fields), fields };
        }, { timeoutMs: operationTimeout(15000), pollMs: 400, stableSamples: 3 });
        recordStable = Boolean(loaded.stable);
      } catch (error) { actionError = sanitizeSensitiveText(error.code || error.message); recordStable = false; }
      state = await freshState(page);
    }
    candidate = strictTsdr ? { candidate_id: candidateId, serial_number: serial, ...(await tsdrRenderedSnapshot(page)) } : {
      candidate_id: candidateId,
      serial_number: serial,
      page_case_number: extractAfterLabel(state.bodyText, ["Serial Number", "Case Number"]),
      registration_number: extractAfterLabel(state.bodyText, ["Registration Number"]),
      mark_text: extractAfterLabel(state.bodyText, ["Mark Literal Elements", "Word Mark"]),
      case_status: extractAfterLabel(state.bodyText, ["Status", "Current Status"]),
      owners: [extractAfterLabel(state.bodyText, ["Owner Name", "Current Owner"])].filter(Boolean),
      goods_services: [extractAfterLabel(state.bodyText, ["Goods and Services", "Identification"])].filter(Boolean),
      classes: extractTsdrClassifications(state.bodyText),
      design_codes: extractTsdrDesignCodes(state.bodyText),
    };
  } else {
    await navigateAndRefresh(page, config.providers.uspto_patent_browser.search_url || config.providers.uspto_patent_browser.basic_search_url, timeout);
    let parsed = null;
    try {
      let submitError = null;
      try { executionEvents.push(await submitSearch(page, patentBasicSearchTerm(record), provider)); }
      catch (error) {
        if (error.submission_state === "not_submitted") throw error;
        submitError = error;
        actionError = sanitizeSensitiveText(error?.message || error);
      }
      await page.waitForLoadState("domcontentloaded", { timeout: operationTimeout(timeout) }).catch(() => {});
      const searchSemantic = await observeAfterSubmission(
        page, "uspto_patent_browser", timeout, config, submitError,
      );
      recordStable = Boolean(searchSemantic.stable && searchSemantic.noResult);
      parsed = (searchSemantic.candidates || []).find((item) =>
        cleanNumber(item.record_number) === cleanNumber(record)
      ) || null;
      const resultRow = await matchingPatentResultRow(page, record);
      const figureCapture = await capturePatentPdfFigure(
        session.context, page, resultRow, taskDir, record, timeout, config,
      );
      figureCaptureAttempted = figureCapture.attempted;
      if (figureCapture.path) {
        evidenceImages.push({
          path: figureCapture.path,
          label: `USPTO patent figures ${cleanNumber(record)}`,
          role: "official_drawing",
        });
      }
      const link = await matchingPatentResultLink(resultRow, ["Text", "Preview"]);
      if (link) {
        const detailHref = await link.getAttribute("href").catch(() => "");
        if (!detailHref) throw new Error("The patent detail link had no target URL");
        await page.goto(new URL(detailHref, page.url()).toString(), {
          waitUntil: "domcontentloaded",
          timeout: operationTimeout(timeout),
        });
        await page.waitForLoadState("domcontentloaded", { timeout: operationTimeout(timeout) }).catch(() => {});
        state = await freshState(page);
        detailOpened = cleanNumber(state.url).includes(cleanNumber(record))
          || cleanNumber(state.bodyText).includes(cleanNumber(record));
        if (detailOpened) {
          await updateCandidateJournal(taskDir, {
            provider,
            right_type: rightType,
            record_number: record,
            title: parsed?.title || "",
            status: "pending",
            opened_at: nowIso(),
            final_url: sanitizeEvidenceUrl(state.url),
          });
        }
        if (isDesignRecord(record)) {
          await page.evaluate(() => scrollTo(0, document.body.scrollHeight)).catch(() => {});
        }
        patentSemantic = await waitForStableSemanticState(
          () => patentDetailSnapshot(page, record, parsed, evidenceImages.length > 0),
          {
            timeoutMs: timeout,
            pollMs: Number(config.cdp?.semantic_poll_ms || 750),
            stableSamples: Number(config.cdp?.semantic_stable_samples || 3),
          },
        );
        state = patentSemantic.state || state;
      }
    } catch (error) {
      actionError = sanitizeSensitiveText(error?.message || error);
    }
    state = await freshState(page);
    const detail = patentSemantic
      || await patentDetailSnapshot(page, record, parsed, evidenceImages.length > 0);
    candidate = {
      candidate_id: candidateId,
      record_number: record,
      page_record_number: detail.page_record_number
        || extractAfterLabel(state.bodyText, ["Document ID", "Patent Number"])
        || "",
      publication_number: extractAfterLabel(state.bodyText, ["Publication Number"]),
      application_number: extractAfterLabel(state.bodyText, ["Application Number"]),
      grant_number: extractAfterLabel(state.bodyText, ["Patent Number", "Grant Number"]),
      title: detail.title || "",
      legal_status: detail.legal_status || "",
      owners: detail.owners || [],
      classifications: detail.classifications || [],
    };
  }

  if (provider === "uspto_tsdr" && rightType === "trademark_figurative") {
    const mark = await firstTsdrMarkMedia(page);
    if (mark) {
      const markPath = candidatePaths.markImagePath;
      await fs.mkdir(path.dirname(markPath), { recursive: true, mode: 0o700 });
      await mark.screenshot({ path: markPath, animations: "disabled" }).catch(() => {});
      if (fsSync.existsSync(markPath)) candidate.mark_image_path = markPath;
    }
  }
  const screenshotPath = candidatePaths.screenshotPath;
  await safeScreenshot(page, screenshotPath, strictTsdr ? { fullPage: true } : {});
  if (provider === "uspto_patent_browser"
      && isDesignRecord(record)
      && patentSemantic?.stable
      && !evidenceImages.length) {
    const drawing = await firstPatentDrawing(page);
    if (drawing) {
      const drawingPath = path.join(taskDir, "screenshots", `uspto-design-${slug(record)}-drawing.png`);
      await drawing.screenshot({ path: drawingPath, animations: "disabled" });
      evidenceImages.push({
        path: drawingPath,
        label: `USPTO design drawing ${cleanNumber(record)}`,
        role: "official_drawing",
      });
    }
  }
  state ||= await freshState(page);
  const challenge = detectChallenge(state.url, state.title, state.bodyText);
  let status = "access_limited";
  let detail = "";
  const accessStatus = resolved.task.schema_version === "2.4-free"
    ? classifyBrowserAccess(state.url, state.title, state.bodyText) : challenge ? "needs_user_action" : null;
  if (accessStatus) {
    status = accessStatus;
    detail = accessStatus === "needs_user_action" ? "The official USPTO page requires access verification in visible Chrome."
      : "The official page denied access without a supported login or CAPTCHA recovery step.";
  } else if (provider === "uspto_tsdr") {
    const identityMatches = cleanNumber(candidate.page_case_number) === cleanNumber(record)
      && cleanNumber(state.url).includes(cleanNumber(record));
    const figurativeMediaReady = rightType !== "trademark_figurative" || Boolean(candidate.mark_image_path);
    if ((resolved.task.schema_version !== "2.4-free" || recordStable)
        && identityMatches && candidate.case_status && candidate.owners.length
        && candidate.goods_services.length && figurativeMediaReady) status = "success";
    else if (explicitNoResult(state.bodyText) && (resolved.task.schema_version !== "2.4-free" || recordStable)) status = "no_result";
    else if (rightType === "trademark_figurative" && !candidate.mark_image_path) {
      detail = "TSDR record loaded, but the required official mark image was not captured.";
    } else {
      detail = actionError ? `TSDR rendered record sections could not be read: ${actionError}`
        : "TSDR page case number, URL, status, owner, and goods/services could not all be bound to the plan.";
    }
  } else {
    const identityMatches = cleanNumber(candidate.page_record_number) === cleanNumber(record)
      && cleanNumber(state.url).includes(cleanNumber(record));
    if (figureCaptureAttempted && !evidenceImages.length) {
      detail = "The patent PDF opened, but no non-blank stable figure frame was captured.";
    } else if (!patentSemantic?.timed_out
        && patentSemantic?.stable
        && identityMatches
        && candidate.title
        && candidate.legal_status
        && candidate.owners.length
        && (!isDesignRecord(record) || candidate.classifications.length > 0)
        && (!isDesignRecord(record) || evidenceImages.length > 0)) {
      status = "success";
    }
    else if (explicitNoResult(state.bodyText) && (resolved.task.schema_version !== "2.4-free" || recordStable || patentSemantic?.stable)) status = "no_result";
    else if (!detail) detail = actionError
      ? `Patent verification could not be confirmed after refreshing page state: ${actionError.slice(0, 300)}`
      : patentSemantic?.timed_out
        ? "Patent detail fields did not become stable before timeout."
        : isDesignRecord(record) && !evidenceImages.length
          ? "The design record loaded, but an official drawing did not become available."
          : isDesignRecord(record) && !candidate.classifications.length
            ? "The design record loaded, but an official classification was not captured."
          : "Patent identity/title/status/owner fields could not all be confirmed from rendered content.";
  }
  if (strictTsdr && status === "access_limited" && !accessStatus) status = "failed";
  const capture = {
    ...provenance,
    status,
    query_id: queryId,
    ...candidate,
    jurisdiction: "US",
    right_type: rightType,
    final_url: sanitizeEvidenceUrl(state.url),
    checked_at: nowIso(),
    screenshot_path: screenshotPath,
    ...(evidenceImages.length ? { evidence_images: evidenceImages, views: evidenceImages.map((item) => item.label) } : {}),
    ...(status === "no_result" ? { result_message: "The rendered official page explicitly reported no matching record." } : {}),
    ...(detail ? { detail } : {}),
    ...(strictTsdr && status === "failed" ? { error_code: "TSDR_EVIDENCE_INCOMPLETE", phase: "verify_record", submission_state: "submitted" } : {}),
    ...(strictTsdr && browserRateLimited(state.bodyText) ? { error_code: "BROWSER_RATE_LIMITED", phase: "verify_record", submission_state: "submitted" } : {}),
  };
  if (resolved.task.schema_version === "2.4-free") {
    capture.media_coverage = { retrieved_count: evidenceImages.length + Number(Boolean(candidate.mark_image_path)),
      expected_count: null, completeness: rightType === "design" ? "unknown" : "not_assessed",
      reason: "Captured media does not prove that every official drawing or product view was retrieved." };
    executionEvents.push({ action: "observe_result", actor: "agent", at: nowIso(),
      stable: provider === "uspto_tsdr" ? recordStable : Boolean(patentSemantic?.stable || recordStable),
      final_url: sanitizeEvidenceUrl(state.url), identity: candidate.page_record_number || candidate.page_case_number || "",
      screenshot_sha256: crypto.createHash("sha256").update(await fs.readFile(screenshotPath)).digest("hex") });
    await attachExecutionReceipt(taskDir, resolved.task, provider, resolved.entry, executionEvents, capture);
  }
  assertNoSensitiveKeys(capture);
  const capturePath = candidatePaths.capturePath;
  await writeJsonAtomic(capturePath, capture);
  ownedAutomaticPages.set(page, status === "needs_user_action" ? "preserve" : "close");
  if (provider === "uspto_patent_browser" && detailOpened) {
    await updateCandidateJournal(taskDir, {
      provider,
      right_type: rightType,
      record_number: record,
      title: candidate.title || "",
      status,
      final_url: sanitizeEvidenceUrl(state.url),
      screenshot_path: screenshotPath,
      capture_path: capturePath,
      completed_at: nowIso(),
    });
  }
  return { status, provider, record, capture_path: capturePath,
    ...(capture.detail ? { detail: capture.detail, error_code: capture.error_code || (actionError ? "CANDIDATE_ACTION_FAILED" : "CANDIDATE_EVIDENCE_INCOMPLETE"), phase: capture.phase || "candidate_verification" } : {}) };
}

const REGISTRY_RIGHT_TYPES = new Set([
  "patent", "utility_model", "design", "trademark_word", "trademark_figurative",
  "copyright", "enforcement",
]);
const REGISTRY_PLAN_META_FIELDS = new Set([
  "query_id", "operation", "jurisdiction", "right_type", "required", "required_for",
  "requirement_id", "requirement_ids", "wave", "derived_from", "execute_by_default",
  "execute_when", "fallback_provider", "mode",
  "decision_workflow_revision", "scenario_id", "scenario_sha256", "scenario_bindings",
  "triage_decision_id", "triage_decision_sha256", "triage_jurisdiction", "triage_candidate_id",
  "action_purpose", "evidence_obligation_id", "triage_action_id",
  "workflow_correction_revision", "required_facts", "reading_scope",
]);

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) =>
      `${JSON.stringify(key)}:${canonicalJson(value[key])}`
    ).join(",")}}`;
  }
  return JSON.stringify(value);
}

function normalizedRegistryBindingValue(value) {
  return String(value ?? "").normalize("NFKC").replace(/\s+/g, " ").trim().toLowerCase();
}

function equivalentRegistryBindingValue(expected, actual) {
  const left = normalizedRegistryBindingValue(expected);
  const right = normalizedRegistryBindingValue(actual);
  if (left === right) return true;
  const classificationAliases = {
    vienna_classification: ["vienna", "vienna classification"],
    locarno_classification: ["locarno", "locarno classification"],
    nice_classification: ["nice", "nice classification"],
    jpo_figurative_classification: ["jpo figurative", "figurative classification", "図形分類"],
  };
  return (classificationAliases[left] || []).some((value) => right === value);
}

export function registryPlannedFilters(entry) {
  const filters = {};
  for (const key of Object.keys(entry || {}).sort()) {
    if (REGISTRY_PLAN_META_FIELDS.has(key) || key === "q" || key === "query") continue;
    const value = entry[key];
    if (value === undefined || value === null || value === "") continue;
    filters[key] = value;
  }
  return filters;
}

export function registryFilterAttestation(entry) {
  return canonicalJson(registryPlannedFilters(entry));
}

export function assertRegistrySearchAttestation(attestation, entry, renderedSearch = null) {
  if (!attestation || typeof attestation !== "object" || Array.isArray(attestation)) {
    throw new Error("REGISTRY_OPERATOR_ATTESTATION_REQUIRED: pass the explicit attestation flags");
  }
  const plannedQuery = String(entry?.q || entry?.query || "").trim();
  const plannedRightType = String(entry?.right_type || "").trim();
  if (attestation.confirmed_current_page !== true) {
    throw new Error("REGISTRY_OPERATOR_ATTESTATION_REQUIRED: --attest-current-page is required");
  }
  if (String(attestation.query || "") !== plannedQuery) {
    throw new Error("REGISTRY_ATTESTED_QUERY_MISMATCH: attested query does not match the plan");
  }
  if (String(attestation.right_type || "") !== plannedRightType) {
    throw new Error("REGISTRY_ATTESTED_RIGHT_TYPE_MISMATCH: attested right type does not match the plan");
  }
  if (canonicalJson(attestation.filters || {}) !== registryFilterAttestation(entry)) {
    throw new Error("REGISTRY_ATTESTED_FILTER_MISMATCH: attested filters do not match the plan");
  }
  if (renderedSearch !== null) {
    if (!renderedSearch || renderedSearch.extraction_attempted !== true) {
      throw new Error("REGISTRY_RENDERED_BINDING_MISSING: DOM/URL extraction was not attempted");
    }
    const queryValues = Array.isArray(renderedSearch.query_values)
      ? renderedSearch.query_values.filter((value) => String(value || "").trim())
      : [];
    if (queryValues.length && !queryValues.some((value) =>
      equivalentRegistryBindingValue(plannedQuery, value)
    )) {
      throw new Error("REGISTRY_RENDERED_QUERY_MISMATCH: visible page belongs to another query");
    }
    const plannedFilters = registryPlannedFilters(entry);
    const renderedFilters = renderedSearch.filters && typeof renderedSearch.filters === "object"
      ? renderedSearch.filters
      : {};
    for (const [key, values] of Object.entries(renderedFilters)) {
      const observed = Array.isArray(values) ? values.filter((value) => String(value || "").trim()) : [];
      if (!observed.length) continue;
      if (!(key in plannedFilters) || !observed.some((value) =>
        equivalentRegistryBindingValue(plannedFilters[key], value)
      )) {
        throw new Error(`REGISTRY_RENDERED_FILTER_MISMATCH: visible ${key} does not match the plan`);
      }
    }
  }
  return {
    query: plannedQuery,
    right_type: plannedRightType,
    filters: registryPlannedFilters(entry),
    confirmed_current_page: true,
  };
}

function registryAttestationFromArgs(args, entry) {
  let filters;
  try {
    filters = JSON.parse(typeof args.attest_filters === "string" ? args.attest_filters : "");
  } catch {
    throw new Error("REGISTRY_OPERATOR_ATTESTATION_REQUIRED: --attest-filters must be a JSON object");
  }
  if (!filters || typeof filters !== "object" || Array.isArray(filters)) {
    throw new Error("REGISTRY_OPERATOR_ATTESTATION_REQUIRED: --attest-filters must be a JSON object");
  }
  return assertRegistrySearchAttestation({
    query: typeof args.attest_query === "string" ? args.attest_query : "",
    right_type: typeof args.attest_right_type === "string" ? args.attest_right_type : "",
    filters,
    confirmed_current_page: args.attest_current_page === true,
  }, entry);
}

function registryRecallOperation(rightType) {
  if (rightType === "design") return "design_recall";
  if (String(rightType).startsWith("trademark")) return "trademark_recall";
  if (rightType === "utility_model") return "utility_model_recall";
  if (rightType === "copyright") return "copyright_recall";
  if (rightType === "enforcement") return "enforcement_recall";
  return "patent_recall";
}

function registryInputs(args, config, { search = false } = {}) {
  const provider = String(args.provider || "").trim();
  const rightType = String(args.right_type || "").trim();
  const jurisdiction = String(args.jurisdiction || (provider === "jplatpat_browser" ? "JP" : "")).toUpperCase();
  if (!provider || !REGISTRY_RIGHT_TYPES.has(rightType) || !jurisdiction) {
    throw new Error("Registry commands require --provider, --right-type, and --jurisdiction");
  }
  const operation = String(args.operation || (search ? registryRecallOperation(rightType) : "candidate_verification"));
  const sourceKey = String(args.source_key || "").trim();
  const adapter = getRegistryAdapter(provider, jurisdiction, rightType, config, sourceKey);
  assertRegistryOperation(adapter, operation);
  return { provider, rightType, jurisdiction, operation, sourceKey, adapter };
}

async function resolvePlannedRegistryQuery(taskDir, args) {
  const task = await readJson(path.join(taskDir, "task.json"));
  const plan = await readJson(path.join(taskDir, "search-plan.json"));
  assertPlanMatchesTask(task, plan);
  const provider = String(args.provider || "").trim();
  const queryId = String(args.query_id || "").trim();
  const queryText = String(args.query || "").trim();
  const operation = String(args.operation || "").trim();
  const jurisdiction = String(args.jurisdiction || "").toUpperCase();
  const rightType = String(args.right_type || "").trim();
  const sourceKey = String(args.source_key || "").trim();
  const entries = Array.isArray(plan.queries?.[provider]) ? plan.queries[provider] : [];
  const matches = entries.filter((entry) => {
    if (!entry || typeof entry !== "object") return false;
    if (queryId && String(entry.query_id || "") !== queryId) return false;
    if (queryText && String(entry.q || entry.query || "") !== queryText) return false;
    if (operation && String(entry.operation || "") !== operation) return false;
    if (jurisdiction && String(entry.jurisdiction || "").toUpperCase() !== jurisdiction) return false;
    if (rightType && String(entry.right_type || "") !== rightType) return false;
    if (sourceKey && String(entry.source_key || "") !== sourceKey) return false;
    return true;
  });
  if (matches.length !== 1) {
    throw new Error(
      matches.length
        ? "REGISTRY_QUERY_AMBIGUOUS: pass the generated --query-id and --source-key"
        : "REGISTRY_QUERY_NOT_PLANNED: the assisted lookup must match one generated query",
    );
  }
  const entry = matches[0];
  await assertScenarioActionDispatch(taskDir, task, provider, entry);
  return {
    task,
    plan,
    entry,
    args: {
      ...args,
      provider,
      query_id: String(entry.query_id || ""),
      query: String(entry.q || entry.query || ""),
      operation: String(entry.operation || ""),
      jurisdiction: String(entry.jurisdiction || ""),
      right_type: String(entry.right_type || ""),
      source_key: String(entry.source_key || ""),
    },
  };
}

async function assertRegistryTask(taskDir, inputs) {
  const task = await readJson(path.join(taskDir, "task.json"));
  assertActiveTaskPayload(task);
  const jurisdiction = inputs.jurisdiction;
  const targets = new Set((task.target_jurisdictions || []).map((item) => String(item).toUpperCase()));
  if (!targets.has(jurisdiction) && !(jurisdiction === "EP" && targets.has("EU"))) {
    throw new Error(`Registry jurisdiction ${jurisdiction} is not in the task target jurisdictions`);
  }
  assertTaskRoute(task, inputs.provider, inputs.operation, jurisdiction, inputs.rightType);
  return task;
}

function assertNoSensitiveUrlInput(value, adapter) {
  const parsed = assertOfficialUrl(value, adapter);
  if (parsed.username || parsed.password) throw new Error("Registry URL cannot contain credentials");
  for (const key of parsed.searchParams.keys()) {
    if (SENSITIVE_URL_KEYS.has(key.toLowerCase())) {
      throw new Error(`Registry URL cannot contain sensitive query parameter: ${key}`);
    }
  }
  return parsed.toString();
}

async function registryPage(context, adapter) {
  const pages = [...context.pages()].reverse();
  for (const page of pages) {
    try {
      const parsed = new URL(page.url());
      if (parsed.protocol === "https:" && hostAllowed(parsed.hostname, adapter.browser_allowed_hosts)) {
        return page;
      }
    } catch {}
  }
  return null;
}

function registryNoResult(bodyText) {
  return explicitNoResult(bodyText)
    || /該当(?:する)?(?:情報|案件|結果).{0,20}(?:ありません|なし)|検索結果\s*[：:]?\s*0\s*件/i.test(String(bodyText || ""))
    || /keine (?:treffer|ergebnisse)|aucun r[ée]sultat|nessun risultato|no se (?:han )?encontraron resultados/i.test(String(bodyText || ""))
    || /inga (?:träffar|resultat)|brak wynik[oó]w|geen resultaten/i.test(String(bodyText || ""));
}

function registryChallenge(url, title, bodyText) {
  const text = `${url}\n${title}\n${bodyText}`;
  return detectChallenge(url, title, bodyText)
    || /(?:login|sign in|authentication) (?:is )?required|ログインが必要|認証が必要/i.test(text);
}

function recordFromText(text, rightType, jurisdiction) {
  const value = String(text || "");
  const prefixed = value.match(
    /\b(?:JP|EP|DE|FR|GB|UK|IT|ES|NL|BE|SE|PL)[\s./-]?(?:[A-Z]{0,3}[\s./-]?)?\d[A-Z0-9./-]{5,20}\b/i,
  )?.[0];
  if (prefixed) return prefixed.trim();
  if (jurisdiction === "JP") {
    const jpApplication = value.match(/\b(?:19|20)\d{8}\b/)?.[0];
    if (jpApplication) return jpApplication;
  }
  if (/application|registration|trade\s*mark|trademark|design|patent|出願|登録|意匠|商標/i.test(value)) {
    const number = value.match(/\b(?!19\d{6}\b|20\d{6}\b)\d{7,12}\b/)?.[0];
    if (number) return number;
  }
  return "";
}

export function parseRegistryRows(rows, options = {}) {
  const rightType = String(options.rightType || "patent");
  const jurisdiction = String(options.jurisdiction || "").toUpperCase();
  const candidates = [];
  const seen = new Set();
  for (const rawCells of rows || []) {
    const cells = (Array.isArray(rawCells) ? rawCells : [rawCells])
      .map((item) => String(item || "").replace(/\s+/g, " ").trim())
      .filter(Boolean);
    if (!cells.length) continue;
    const joined = cells.join(" | ");
    const recordNumber = recordFromText(joined, rightType, jurisdiction);
    const key = cleanNumber(recordNumber);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    const title = cells.find((item) =>
      item.length > 3
      && !cleanNumber(item).includes(key)
      && !/^(?:application|registration|owner|applicant|status|class|date|result|record|details?)\b/i.test(item)
      && !/^(?:live|dead|registered|pending|expired|active|inactive)$/i.test(item)
    ) || "";
    const owner = cells.find((item) =>
      /(?:inc\.?|llc|ltd\.?|corp\.?|company|gmbh|s\.?a\.?|株式会社|有限会社|法人|大学|研究所|庁長官|sp\.\s*z\s*o\.o\.|\bab\b)/i.test(item)
    ) || "";
    const legalStatus = cells.find((item) =>
      /live|dead|registered|pending|expired|active|inactive|granted|refused|withdrawn|係属|登録|消滅|満了/i.test(item)
    ) || "";
    const classes = cells.filter((item) =>
      /(?:ipc|cpc|locarno|nice|class|classification|分類|類似群)\s*[:#-]?\s*[A-Z0-9]/i.test(item)
    );
    candidates.push({
      record_number: recordNumber,
      application_number: jurisdiction === "JP" && /^\d{10}$/.test(recordNumber) ? recordNumber : "",
      title,
      owner,
      legal_status: legalStatus,
      classes,
      jurisdiction,
      right_type: rightType,
      material: false,
    });
  }
  return candidates;
}

async function renderedRegistryRows(page) {
  const rows = await tableRows(page);
  const blocks = await page.locator("[role='row'], article, main li").evaluateAll((nodes) =>
    nodes.slice(0, 300).map((node) => (node.innerText || node.textContent || "").trim())
      .filter((value) => value && value.length <= 3000)
      .map((value) => value.split(/\r?\n/).map((part) => part.trim()).filter(Boolean))
  ).catch(() => []);
  return [...rows, ...blocks];
}

function registrySearchFieldRelevant(key) {
  const value = normalizedRegistryBindingValue(key);
  return [
    "query", "search", "keyword", "verbal", "denomination", "trademark", "patent",
    "design", "classification", "vienna", "locarno", "niceclass",
  ].some((item) => value.includes(item))
    || /(?:^|[^a-z])(q|term|text|mark|class)(?:[^a-z]|$)/i.test(value)
    || /検索|キーワード|商標|標章|意匠|特許|分類|類似群/.test(value);
}

function registryFilterFieldRelevant(key, filterKey) {
  const descriptor = normalizedRegistryBindingValue(key);
  const name = normalizedRegistryBindingValue(filterKey).replaceAll("_", " ");
  if (descriptor.includes(name)) return true;
  const aliases = {
    classification_scheme: /classification|class|vienna|locarno|nice|分類|類似群/i,
    query_mode: /query.?mode|search.?type|classification|検索種別|検索方法/i,
    strategy: /strategy|match.?type|search.?type|検索方法/i,
    search_focus: /right.?type|record.?type|patent|design|trademark|権利|種別/i,
    source_key: /source|database|registry|record.?set|情報源|データベース/i,
  };
  return aliases[filterKey]?.test(descriptor) || false;
}

function urlRegistrySearchFields(rawUrl) {
  const fields = [];
  try {
    const parsed = new URL(String(rawUrl || ""));
    for (const [key, value] of parsed.searchParams.entries()) {
      if (!SENSITIVE_URL_KEYS.has(key.toLowerCase()) && String(value || "").trim()) {
        fields.push({ key, value: String(value).slice(0, 1000), source: `url:${key}` });
      }
    }
    const hash = parsed.hash.startsWith("#") ? parsed.hash.slice(1) : parsed.hash;
    const queryIndex = hash.indexOf("?");
    if (queryIndex >= 0) {
      for (const [key, value] of new URLSearchParams(hash.slice(queryIndex + 1)).entries()) {
        if (!SENSITIVE_URL_KEYS.has(key.toLowerCase()) && String(value || "").trim()) {
          fields.push({ key, value: String(value).slice(0, 1000), source: `hash:${key}` });
        }
      }
    }
  } catch {}
  return fields;
}

async function domRegistrySearchFields(page) {
  return page.locator("input, textarea, select").evaluateAll((nodes) => {
    const result = [];
    for (const node of nodes.slice(0, 300)) {
      const style = window.getComputedStyle(node);
      const type = String(node.getAttribute("type") || "").toLowerCase();
      if (style.display === "none" || style.visibility === "hidden"
          || ["hidden", "password", "email"].includes(type)) continue;
      if (["checkbox", "radio"].includes(type) && !node.checked) continue;
      const labels = node.labels ? Array.from(node.labels).map((label) => label.textContent || "") : [];
      const descriptor = [
        node.getAttribute("name"), node.id, node.getAttribute("aria-label"),
        node.getAttribute("placeholder"), ...labels,
      ].filter(Boolean).join(" ").replace(/\s+/g, " ").trim().slice(0, 500);
      if (!descriptor || /password|secret|token|login|account|username|email/i.test(descriptor)) continue;
      const values = node.tagName === "SELECT"
        ? Array.from(node.selectedOptions || []).map((option) => option.value || option.textContent || "")
        : [node.value || ""];
      for (const rawValue of values) {
        const value = String(rawValue || "").replace(/\s+/g, " ").trim().slice(0, 1000);
        if (value) result.push({ key: descriptor, value, source: `dom:${node.tagName.toLowerCase()}` });
      }
    }
    return result;
  }).catch(() => []);
}

async function renderedRegistrySearchBinding(page, state, plannedFilters) {
  const fields = [
    ...urlRegistrySearchFields(state.url),
    ...await domRegistrySearchFields(page),
  ];
  const queryFields = fields.filter((field) => registrySearchFieldRelevant(field.key));
  const filters = {};
  const filterSources = {};
  for (const key of Object.keys(plannedFilters || {}).sort()) {
    const matches = fields.filter((field) => registryFilterFieldRelevant(field.key, key));
    if (!matches.length) continue;
    filters[key] = [...new Set(matches.map((field) => field.value))];
    filterSources[key] = [...new Set(matches.map((field) => field.source))];
  }
  return {
    schema_version: "1.0",
    extraction_attempted: true,
    query_values: [...new Set(queryFields.map((field) => field.value))],
    query_sources: [...new Set(queryFields.map((field) => field.source))],
    filters,
    filter_sources: filterSources,
  };
}

async function registrySemanticSnapshot(page, inputs) {
  const state = await freshState(page);
  const rows = await renderedRegistryRows(page);
  const candidates = parseRegistryRows(rows, {
    rightType: inputs.rightType,
    jurisdiction: inputs.jurisdiction,
  });
  const challenge = registryChallenge(state.url, state.title, state.bodyText);
  const noResult = registryNoResult(state.bodyText);
  return {
    ready: challenge || noResult || candidates.length > 0,
    signature: JSON.stringify({
      url: state.url,
      title: state.title,
      challenge,
      noResult,
      candidates: candidates.map((item) => cleanNumber(item.record_number)),
    }),
    state,
    candidates,
    challenge,
    noResult,
  };
}

export function registryPageBindingDigest(value) {
  return crypto.createHash("sha256").update(canonicalJson(value), "utf8").digest("hex");
}

async function openRegistrySearch(args, config) {
  const taskDir = path.resolve(String(args.task_dir || ""));
  const resolved = await resolvePlannedRegistryQuery(taskDir, args);
  const gate = browserRouteGate(resolved.task, resolved.args.provider, resolved.entry);
  if (gate) return gate;
  args = resolved.args;
  const query = String(args.query || "").trim();
  if (!query) throw new Error("open-registry-search requires one non-empty --query");
  const inputs = registryInputs(args, config, { search: true });
  const termsReview = currentRegistryTermsReview(args, inputs.adapter);
  await assertRegistryTask(taskDir, inputs);
  const session = await connectSession(config);
  const page = await session.context.newPage();
  const timeout = Number(config.cdp?.navigation_timeout_ms || 45000);
  const requestedUrl = args.url
    ? assertNoSensitiveUrlInput(args.url, inputs.adapter)
    : inputs.adapter.search_url;
  const { state } = await navigateAndRefresh(page, requestedUrl, timeout);
  const finalUrl = assertNoSensitiveUrlInput(state.url, inputs.adapter);
  const captureSlug = slug(args.query_id || `${inputs.sourceKey}-${query}`);
  const screenshotPath = path.join(
    taskDir, "screenshots", `${slug(inputs.provider)}-${captureSlug}-search-open.png`,
  );
  await safeScreenshot(page, screenshotPath);
  const plannedFilters = registryPlannedFilters(resolved.entry);
  const captureCommand = registryCaptureCommand({
    taskDir,
    provider: inputs.provider,
    queryId: String(args.query_id || ""),
    query,
    rightType: inputs.rightType,
    filters: plannedFilters,
  });
  const capture = {
    ...sanitizedSession(session.version, session.sessionId),
    status: "needs_user_action",
    provider: inputs.provider,
    operation: inputs.operation,
    query_id: String(args.query_id || ""),
    query,
    ...(inputs.sourceKey ? { source_key: inputs.sourceKey } : {}),
    right_type: inputs.rightType,
    jurisdiction: inputs.jurisdiction,
    final_url: sanitizeEvidenceUrl(finalUrl),
    checked_at: nowIso(),
    screenshot_path: screenshotPath,
    candidates: [],
    terms_review: termsReview,
    required_operator_attestation: {
      query,
      right_type: inputs.rightType,
      filters: plannedFilters,
      filters_json: canonicalJson(plannedFilters),
      flags: ["--attest-query", "--attest-right-type", "--attest-filters", "--attest-current-page"],
    },
    capture_command_argv: captureCommand.argv,
    capture_command: captureCommand.shell,
    detail: "Submit this one planned query in the visible official page. Then capture it with the exact attestation values shown here; no query was submitted automatically.",
  };
  assertNoSensitiveKeys(capture);
  const capturePath = path.join(taskDir, `${slug(inputs.provider)}-${captureSlug}-search-open.json`);
  await writeJsonAtomic(capturePath, capture);
  return {
    status: capture.status,
    provider: inputs.provider,
    operation: inputs.operation,
    capture_path: capturePath,
    capture_command_argv: captureCommand.argv,
    capture_command: captureCommand.shell,
  };
}

async function captureRegistrySearch(args, config) {
  const taskDir = path.resolve(String(args.task_dir || ""));
  const resolved = await resolvePlannedRegistryQuery(taskDir, args);
  rejectManualBusinessCapture(resolved.task);
  args = resolved.args;
  const query = String(args.query || "").trim();
  if (!query) throw new Error("capture-registry-search requires a non-empty planned query");
  const attestedPlan = registryAttestationFromArgs(args, resolved.entry);
  const attestationInvokedAt = nowIso();
  const inputs = registryInputs(args, config, { search: true });
  const termsReview = currentRegistryTermsReview(args, inputs.adapter);
  await assertRegistryTask(taskDir, inputs);
  const session = await connectSession(config);
  const page = await registryPage(session.context, inputs.adapter);
  if (!page) throw new Error(`No visible ${inputs.provider} page is open on an allowlisted official host`);
  const timeout = Number(config.cdp?.navigation_timeout_ms || 45000);
  const semantic = await waitForStableSemanticState(() => registrySemanticSnapshot(page, inputs), {
    timeoutMs: timeout,
    pollMs: Number(config.cdp?.semantic_poll_ms || 750),
    stableSamples: Number(config.cdp?.semantic_stable_samples || 3),
  });
  const bound = await registrySemanticSnapshot(page, inputs);
  if (!semantic.timed_out && semantic.signature !== bound.signature) {
    throw new Error("REGISTRY_PAGE_CHANGED_DURING_CAPTURE: rendered results changed after stabilization");
  }
  const finalUrl = sanitizeEvidenceUrl(assertNoSensitiveUrlInput(bound.state.url, inputs.adapter));
  const pageTitle = String(bound.state.title || "").replace(/\s+/g, " ").trim();
  if (!pageTitle) throw new Error("REGISTRY_PAGE_TITLE_MISSING: current official page has no auditable title");
  const renderedSearch = await renderedRegistrySearchBinding(
    page, bound.state, registryPlannedFilters(resolved.entry),
  );
  assertRegistrySearchAttestation(attestedPlan, resolved.entry, renderedSearch);
  const captureSlug = slug(args.query_id || `${inputs.sourceKey}-${query}`);
  const screenshotPath = path.join(
    taskDir, "screenshots", `${slug(inputs.provider)}-${captureSlug}-search-result.png`,
  );
  await safeScreenshot(page, screenshotPath);
  const postCaptureState = await freshState(page);
  if (postCaptureState.url !== bound.state.url || postCaptureState.title !== bound.state.title) {
    throw new Error("REGISTRY_PAGE_CHANGED_DURING_CAPTURE: URL or title changed while taking the screenshot");
  }
  const screenshotBytes = await fs.readFile(screenshotPath);
  const screenshotSha256 = crypto.createHash("sha256").update(screenshotBytes).digest("hex");
  const checkedAt = nowIso();
  const pageBinding = {
    query_id: String(args.query_id || ""),
    final_url: finalUrl,
    page_title: pageTitle,
    screenshot_sha256: screenshotSha256,
    checked_at: checkedAt,
    rendered_search: renderedSearch,
    capture_provenance: sanitizedSession(session.version, session.sessionId),
  };
  const pageBindingSha256 = registryPageBindingDigest(pageBinding);
  let status = "access_limited";
  let detail = "The visible page did not expose stable candidate identifiers or an explicit zero-result message.";
  if (bound.challenge) {
    status = "needs_user_action";
    detail = "The official registry requires login, CAPTCHA, or other user action.";
  } else if (!semantic.timed_out && bound.candidates?.length) {
    status = "success";
    detail = "";
  } else if (!semantic.timed_out && bound.noResult) {
    status = "no_result";
    detail = "The rendered official page explicitly reported zero results.";
  }
  const capture = {
    ...sanitizedSession(session.version, session.sessionId),
    status,
    provider: inputs.provider,
    operation: inputs.operation,
    query_id: String(args.query_id || ""),
    query,
    ...(inputs.sourceKey ? { source_key: inputs.sourceKey } : {}),
    right_type: inputs.rightType,
    jurisdiction: inputs.jurisdiction,
    final_url: finalUrl,
    page_title: pageTitle,
    checked_at: checkedAt,
    screenshot_path: screenshotPath,
    screenshot_sha256: screenshotSha256,
    rendered_search: renderedSearch,
    operator_attestation: {
      schema_version: "1.0",
      operator_confirmed: true,
      confirmed_current_page: true,
      query: attestedPlan.query,
      right_type: attestedPlan.right_type,
      filters: attestedPlan.filters,
      invoked_at: attestationInvokedAt,
      attested_at: checkedAt,
      page_binding_sha256: pageBindingSha256,
    },
    terms_review: termsReview,
    candidates: bound.candidates || [],
    ...(status === "no_result" ? { result_message: detail } : {}),
    ...(status !== "success" ? { detail } : {}),
  };
  assertNoSensitiveKeys(capture);
  const capturePath = path.join(taskDir, `${slug(inputs.provider)}-${captureSlug}-search-capture.json`);
  await writeJsonAtomic(capturePath, capture);
  return { status, provider: inputs.provider, operation: inputs.operation, capture_path: capturePath };
}

export async function jpoVerificationAlreadyComplete(taskDir, rightType, candidateId, record) {
  let payload;
  let evidence;
  let task;
  try {
    payload = await readJson(path.join(taskDir, "normalized-candidates.json"));
    evidence = await readJson(path.join(taskDir, "evidence.json"));
    task = await readJson(path.join(taskDir, "task.json"));
  } catch {
    return false;
  }
  const requirementIds = new Set((task.coverage_requirements || [])
    .filter((requirement) => requirement?.phase === "candidate_verification"
      && String(requirement?.jurisdiction || "").toUpperCase() === "JP"
      && String(requirement?.right_type || "") === rightType
      && (requirement.routes || []).some((route) => route?.provider === "jpo_api"
        && route?.operation === "candidate_verification"))
    .map((requirement) => String(requirement.requirement_id || ""))
    .filter(Boolean));
  if (!requirementIds.size) return false;
  const sourceRuns = new Map((evidence.source_runs || []).map((run) => [String(run?.run_id || ""), run]));
  const evidenceBindings = new Map();
  for (const entry of evidence.collections?.official_verifications || []) {
    if (!entry || entry.provider !== "jpo_api" || entry.operation !== "candidate_verification"
        || entry.right_type !== rightType) continue;
    const run = sourceRuns.get(String(entry.source_run_id || ""));
    const runRequirements = new Set(run?.requirement_ids || []);
    const entryRequirements = new Set(entry.requirement_ids || []);
    const requirementBound = [...requirementIds].some((value) =>
      runRequirements.has(value) && entryRequirements.has(value));
    if (!run || run.status !== "success" || run.provider !== "jpo_api"
        || run.operation !== "candidate_verification" || run.right_type !== rightType
        || !requirementBound) continue;
    const rows = Array.isArray(entry.payload?.candidates) ? entry.payload.candidates : [entry.payload];
    const validRows = rows.filter((row) => row?.official_verification?.status === "verified");
    if (validRows.length) evidenceBindings.set(String(entry.evidence_id || ""), validRows);
  }
  const expectedId = String(candidateId || "").trim();
  const expectedRecord = cleanNumber(record);
  const rows = [...(payload.patents || []), ...(payload.trademarks || [])];
  for (const item of rows) {
    if (!item || typeof item !== "object" || String(item.right_type || "") !== rightType) continue;
    const identifiers = new Set([
      "record_number", "application_number", "publication_number", "registration_number",
      "grant_number", "serial_number",
    ].map((field) => cleanNumber(item[field])).filter(Boolean));
    const matches = (expectedId && String(item.candidate_id || "") === expectedId)
      || (expectedRecord && identifiers.has(expectedRecord));
    if (!matches) continue;
    const boundRows = (item.verification_refs || []).flatMap((ref) => evidenceBindings.get(String(ref)) || []);
    const verification = item.official_verification;
    const comparableFields = [
      "status", "authority", "method", "identity_match", "legal_status",
      "owner", "classes", "media", "url", "checked_at",
    ];
    const canonical = (value) => {
      if (Array.isArray(value)) return JSON.stringify(value.map(canonical).sort());
      if (value && typeof value === "object") return JSON.stringify(Object.keys(value).sort()
        .map((key) => [key, canonical(value[key])]));
      return JSON.stringify(value ?? null);
    };
    const boundToSameRecord = boundRows.some((row) => {
      const idMatches = Boolean(expectedId && String(row.candidate_id || "") === expectedId);
      const rowIds = new Set([
        "record_number", "application_number", "publication_number", "registration_number",
        "grant_number", "serial_number", "page_application_number",
      ].map((field) => cleanNumber(row[field])).filter(Boolean));
      const recordMatches = [...identifiers].some((value) => rowIds.has(value));
      if (!idMatches && !recordMatches) return false;
      const official = row?.official_verification;
      return official && comparableFields.every((field) =>
        canonical(verification?.[field]) === canonical(official?.[field]));
    });
    if (!boundToSameRecord) continue;
    if (!verification || typeof verification !== "object" || verification.status !== "verified") continue;
    const authority = `${verification.authority || ""} ${verification.source || ""}`.toLowerCase();
    const owners = verification.owner || verification.owners;
    const classes = verification.classes || item.classes || item.classifications;
    const classPresent = Array.isArray(classes) ? classes.length > 0 : Boolean(String(classes || "").trim());
    const checkedAt = Date.parse(String(verification.checked_at || ""));
    const ageHours = Number.isFinite(checkedAt) ? (Date.now() - checkedAt) / 3600000 : Infinity;
    let officialHost = "";
    let officialProtocol = "";
    try {
      const parsedOfficialUrl = new URL(String(verification.url || ""));
      officialHost = parsedOfficialUrl.hostname.toLowerCase();
      officialProtocol = parsedOfficialUrl.protocol;
    } catch {}
    const updatedDate = String(verification.updated_date || item.updated_date || "").trim();
    const media = verification.media || item.media || item.views;
    const mediaRequired = ["design", "trademark_figurative"].includes(rightType);
    // The JPO verification API contract treats identity, owner, legal status,
    // update date and the fixed J-PlatPat address as complete for patents.
    // Classification/media are additional completeness gates only for rights
    // whose identity depends on them. Utility models never use this API path.
    const classRequired = [
      "design", "trademark_word", "trademark_figurative",
    ].includes(rightType);
    if ((authority.includes("jpo") || authority.includes("japan patent office"))
        && verification.identity_match === true
        && (Array.isArray(owners) ? owners.length > 0 : Boolean(String(owners || "").trim()))
        && Boolean(String(verification.legal_status || "").trim())
        && Boolean(updatedDate)
        && officialProtocol === "https:"
        && officialHost === "www.j-platpat.inpit.go.jp"
        && ageHours >= -0.1 && ageHours <= 48
        && (!classRequired || classPresent)
        && (!mediaRequired || (Array.isArray(media) ? media.length > 0 : Boolean(media)))) {
      return true;
    }
  }
  return false;
}

async function openRegistryRecord(args, config) {
  const taskDir = path.resolve(String(args.task_dir || ""));
  const resolved = await resolvePlannedCandidateAction(taskDir, args);
  const gate = browserRouteGate(resolved.task, resolved.inputs.provider, resolved.entry);
  if (gate) return gate;
  args = { ...args, ...resolved.inputs };
  const record = args.record;
  if (!record) throw new Error("open-registry requires one non-empty --record");
  const inputs = registryInputs(args, config);
  await assertRegistryTask(taskDir, inputs);
  if (inputs.provider === "jplatpat_browser" && await jpoVerificationAlreadyComplete(
    taskDir, inputs.rightType, args.candidate_id, record,
  )) {
    return {
      status: "not_applicable",
      skipped: true,
      provider: inputs.provider,
      operation: inputs.operation,
      reason: "complete_jpo_api_verification_already_present",
    };
  }
  const termsReview = currentRegistryTermsReview(args, inputs.adapter);
  const requestedUrl = args.url
    ? assertNoSensitiveUrlInput(args.url, inputs.adapter)
    : directRecordUrl(inputs.adapter, record);
  assertNoSensitiveUrlInput(requestedUrl, inputs.adapter);
  const session = await connectSession(config);
  const page = await session.context.newPage();
  const timeout = Number(config.cdp?.navigation_timeout_ms || 45000);
  const { state } = await navigateAndRefresh(page, requestedUrl, timeout);
  assertNoSensitiveUrlInput(state.url, inputs.adapter);
  const screenshotPath = path.join(
    taskDir, "screenshots", `${slug(inputs.provider)}-${slug(record)}-record-open.png`,
  );
  await safeScreenshot(page, screenshotPath);
  const captureCommand = registryRecordCaptureCommand({
    taskDir,
    provider: inputs.provider,
    queryId: args.query_id,
    record,
    candidateId: args.candidate_id,
    rightType: inputs.rightType,
    jurisdiction: inputs.jurisdiction,
    sourceKey: inputs.sourceKey,
  });
  const capture = {
    ...sanitizedSession(session.version, session.sessionId),
    status: "needs_user_action",
    provider: inputs.provider,
    operation: inputs.operation,
    query_id: args.query_id,
    record_number: record,
    candidate_id: String(args.candidate_id || ""),
    ...(inputs.sourceKey ? { source_key: inputs.sourceKey } : {}),
    right_type: inputs.rightType,
    jurisdiction: inputs.jurisdiction,
    final_url: sanitizeEvidenceUrl(state.url),
    checked_at: nowIso(),
    screenshot_path: screenshotPath,
    terms_review: termsReview,
    capture_command_argv: captureCommand.argv,
    capture_command: captureCommand.shell,
    detail: "Confirm the single official record in visible Chrome, then run capture-registry. No search form or pagination was automated.",
  };
  assertNoSensitiveKeys(capture);
  const capturePath = path.join(taskDir, `${slug(inputs.provider)}-${slug(record)}-record-open.json`);
  await writeJsonAtomic(capturePath, capture);
  await updateCandidateJournal(taskDir, {
    provider: inputs.provider,
    query_id: args.query_id,
    record_number: record,
    candidate_id: String(args.candidate_id || ""),
    ...(inputs.sourceKey ? { source_key: inputs.sourceKey } : {}),
    status: "pending",
    opened_at: nowIso(),
    final_url: sanitizeEvidenceUrl(state.url),
  });
  return {
    status: capture.status,
    provider: inputs.provider,
    operation: inputs.operation,
    capture_path: capturePath,
    capture_command_argv: captureCommand.argv,
    capture_command: captureCommand.shell,
  };
}

function registryField(text, labels) {
  const lines = String(text || "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  for (let index = 0; index < lines.length; index += 1) {
    for (const label of [...labels].sort((left, right) => right.length - left.length)) {
      const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const match = lines[index].match(
        new RegExp(`^${escaped}(?![\\p{L}\\p{N}_])\\s*[:#-]?\\s*(.*)$`, "iu"),
      );
      if (match?.[1]) return match[1].trim();
      if (match && lines[index + 1]) return lines[index + 1];
    }
  }
  return "";
}

async function firstRegistryMedia(page) {
  const preferred = await firstVisible(page, [
    "[data-testid*='design' i] img", "[data-testid*='mark' i] img",
    "img[class*='design' i]", "img[class*='trademark' i]", "img[class*='mark' i]",
    ".image-viewer img", ".drawing img", ".representation img",
  ]);
  if (preferred) return preferred;
  return firstPatentDrawing(page);
}

async function registryRecordSnapshot(page, record, rightType) {
  const state = await freshState(page);
  const requested = cleanNumber(record);
  const bindingFields = [
    ...urlRegistrySearchFields(state.url),
    ...await domRegistrySearchFields(page),
  ];
  const requestEchoMatches = Boolean(requested) && bindingFields.some((field) =>
    cleanNumber(field.value) === requested
  );
  const pageRecordText = registryField(state.bodyText, [
    "Application number", "Publication number", "Registration number", "Patent number",
    "Design number", "Trademark number", "Record number", "Case number", "Docket number",
    "Proceeding number", "Claim number", "Serial number",
    "Anmeldenummer", "Registernummer", "Numéro de dépôt", "Numéro d'enregistrement",
    "Numero domanda", "Numero registrazione", "Número de solicitud", "Número de registro",
    "出願番号", "公開番号", "登録番号", "案件番号",
  ]);
  const pageRecordNumber = cleanNumber(pageRecordText);
  const identityMatches = Boolean(requested) && pageRecordNumber === requested;
  const title = registryField(state.bodyText, [
    "Title", "Work title", "Case name", "Proceeding", "Mark", "Word mark", "Design product", "Article", "Titre", "Bezeichnung",
    "Titolo", "Título", "発明の名称", "意匠に係る物品", "商標", "名称",
  ]);
  const owner = registryField(state.bodyText, [
    "Owner", "Claimant", "Copyright claimant", "Party", "Petitioner", "Respondent",
    "Proprietor", "Applicant", "Holder", "Titulaire", "Inhaber", "Anmelder",
    "Titolare", "Solicitante", "Rättsinnehavare", "Właściciel", "権利者", "出願人",
  ]);
  const legalStatus = registryField(state.bodyText, [
    "Legal status", "Status", "Current status", "Statut", "Rechtsstand", "Stato", "Estado",
    "Status prawny", "Rättslig status", "法的状態", "ステータス", "経過情報",
  ]);
  const classes = [registryField(state.bodyText, [
    "Classification", "Class", "IPC", "CPC", "Locarno", "Nice class", "分類", "区分", "類似群コード",
  ])].filter(Boolean);
  const media = rightType === "design" || rightType === "trademark_figurative"
    ? await firstRegistryMedia(page)
    : null;
  const classRequired = [
    "patent", "utility_model", "design", "trademark_word", "trademark_figurative",
  ].includes(rightType);
  const challenge = registryChallenge(state.url, state.title, state.bodyText);
  const noResult = registryNoResult(state.bodyText);
  const ready = challenge || (noResult && requestEchoMatches) || (
    identityMatches && Boolean(title) && Boolean(owner) && Boolean(legalStatus) && Boolean(
      rightType !== "design" && rightType !== "trademark_figurative" || media,
    ) && (!classRequired || classes.length > 0)
  );
  return {
    ready,
    signature: JSON.stringify({
      url: state.url, pageRecordNumber, identityMatches, title, owner, legalStatus, classes,
      requestEchoMatches, media: Boolean(media), challenge, noResult,
    }),
    state,
    pageRecordNumber,
    identityMatches,
    requestEchoMatches,
    title,
    owner,
    legalStatus,
    classes,
    media,
    challenge,
    noResult,
  };
}

async function captureRegistryRecord(args, config) {
  const taskDir = path.resolve(String(args.task_dir || ""));
  const resolved = await resolvePlannedCandidateAction(taskDir, args);
  rejectManualBusinessCapture(resolved.task);
  args = { ...args, ...resolved.inputs };
  const record = args.record;
  if (!record) throw new Error("capture-registry requires the operator-confirmed --record");
  const inputs = registryInputs(args, config);
  await assertRegistryTask(taskDir, inputs);
  if (inputs.provider === "jplatpat_browser" && await jpoVerificationAlreadyComplete(
    taskDir, inputs.rightType, args.candidate_id, record,
  )) {
    return {
      status: "not_applicable",
      skipped: true,
      provider: inputs.provider,
      operation: inputs.operation,
      reason: "complete_jpo_api_verification_already_present",
    };
  }
  const termsReview = currentRegistryTermsReview(args, inputs.adapter);
  const session = await connectSession(config);
  const page = await registryPage(session.context, inputs.adapter);
  if (!page) throw new Error(`No visible ${inputs.provider} page is open on an allowlisted official host`);
  const timeout = Number(config.cdp?.navigation_timeout_ms || 45000);
  const semantic = await waitForStableSemanticState(
    () => registryRecordSnapshot(page, record, inputs.rightType),
    {
      timeoutMs: timeout,
      pollMs: Number(config.cdp?.semantic_poll_ms || 750),
      stableSamples: Number(config.cdp?.semantic_stable_samples || 3),
    },
  );
  const state = semantic.state || await freshState(page);
  assertNoSensitiveUrlInput(state.url, inputs.adapter);
  const screenshotPath = path.join(
    taskDir, "screenshots", `${slug(inputs.provider)}-${slug(record)}-record.png`,
  );
  await safeScreenshot(page, screenshotPath);
  const evidenceImages = [];
  if (semantic.media && (inputs.rightType === "design" || inputs.rightType === "trademark_figurative")) {
    const mediaPath = path.join(
      taskDir, "screenshots", `${slug(inputs.provider)}-${slug(record)}-official-media.png`,
    );
    await semantic.media.screenshot({ path: mediaPath, animations: "disabled" }).catch(() => {});
    if (fsSync.existsSync(mediaPath)) {
      evidenceImages.push({
        path: mediaPath,
        label: `${inputs.adapter.authority} official ${inputs.rightType} media ${record}`,
        role: inputs.rightType === "design" ? "official_drawing" : "official_mark_image",
      });
    }
  }
  let status = "access_limited";
  let detail = "Official identity, title, legal status, and owner fields did not all stabilize.";
  if (semantic.challenge) {
    status = "needs_user_action";
    detail = "The official registry requires login, CAPTCHA, or other user action.";
  } else if (semantic.noResult && semantic.requestEchoMatches) {
    status = "no_result";
    detail = "The rendered official page explicitly reported no matching record.";
  } else if (semantic.noResult) {
    detail = "The page reported no result, but the requested record was not visible in the URL or rendered form.";
  } else if (
    semantic.stable && semantic.identityMatches && semantic.title && semantic.owner && semantic.legalStatus
    && (!["patent", "utility_model", "design", "trademark_word", "trademark_figurative"].includes(inputs.rightType)
      || semantic.classes?.length)
    && (!["design", "trademark_figurative"].includes(inputs.rightType) || evidenceImages.length)
  ) {
    status = "success";
    detail = "";
  } else if (["design", "trademark_figurative"].includes(inputs.rightType) && !evidenceImages.length) {
    detail = "The official record loaded, but required official visual media was not captured.";
  } else if (["patent", "utility_model", "design", "trademark_word", "trademark_figurative"].includes(inputs.rightType)
      && !semantic.classes?.length) {
    detail = "The official record loaded, but the required official classification was not captured.";
  }
  const capture = {
    ...sanitizedSession(session.version, session.sessionId),
    status,
    provider: inputs.provider,
    operation: inputs.operation,
    query_id: args.query_id,
    record_number: record,
    page_record_number: semantic.pageRecordNumber || "",
    page_query_record: semantic.requestEchoMatches ? record : "",
    candidate_id: String(args.candidate_id || ""),
    ...(inputs.sourceKey ? { source_key: inputs.sourceKey } : {}),
    right_type: inputs.rightType,
    jurisdiction: inputs.jurisdiction,
    title: semantic.title || "",
    legal_status: semantic.legalStatus || "",
    owners: semantic.owner ? [semantic.owner] : [],
    classes: semantic.classes || [],
    final_url: sanitizeEvidenceUrl(state.url),
    checked_at: nowIso(),
    screenshot_path: screenshotPath,
    terms_review: termsReview,
    ...(evidenceImages.length ? { evidence_images: evidenceImages } : {}),
    ...(status === "no_result" ? { result_message: detail } : {}),
    ...(status !== "success" ? { detail } : {}),
  };
  assertNoSensitiveKeys(capture);
  const capturePath = path.join(taskDir, `${slug(inputs.provider)}-${slug(record)}-capture.json`);
  await writeJsonAtomic(capturePath, capture);
  await updateCandidateJournal(taskDir, {
    provider: inputs.provider,
    query_id: args.query_id,
    right_type: inputs.rightType,
    record_number: record,
    candidate_id: String(args.candidate_id || ""),
    ...(inputs.sourceKey ? { source_key: inputs.sourceKey } : {}),
    title: semantic.title || "",
    status,
    final_url: sanitizeEvidenceUrl(state.url),
    screenshot_path: screenshotPath,
    capture_path: capturePath,
    completed_at: nowIso(),
  });
  return { status, provider: inputs.provider, operation: inputs.operation, record, capture_path: capturePath };
}

async function doctor(config) {
  const session = await connectSession(config);
  const result = {
    status: "success",
    ...sanitizedSession(session.version, session.sessionId),
    endpoint_scope: "loopback",
    profile_is_dedicated: true,
    headless: false,
    contexts: session.browser.contexts().length,
    pages: session.context.pages().length,
    launched: session.launched,
  };
  return result;
}

function printHelp() {
  process.stdout.write(`Usage:
  node cdp-cli.mjs doctor
  node cdp-cli.mjs capture-amazon --task-dir /absolute/run
  node cdp-cli.mjs run-planned-query --task-dir /absolute/run --query-id QRY-... [--acceptance-probe]
  node cdp-cli.mjs automation-capability --provider PROVIDER --jurisdiction CC --right-type TYPE --operation OP
  node cdp-cli.mjs verify-candidate --task-dir /absolute/run --query-id QRY-... --provider uspto_tsdr|uspto_patent_browser --record ID --candidate-id CAND-...
  node cdp-cli.mjs registry-catalog
  node cdp-cli.mjs open-registry-search --task-dir DIR --provider PROVIDER --query-id QRY-ID --confirm-current-terms
  node cdp-cli.mjs capture-registry-search --task-dir DIR --provider PROVIDER --query-id QRY-ID --attest-query QUERY --attest-right-type TYPE --attest-filters '{}' --attest-current-page --confirm-current-terms
  node cdp-cli.mjs open-registry --task-dir DIR --query-id QRY-... --provider PROVIDER --record ID --candidate-id CAND-... --right-type TYPE --jurisdiction CC [--source-key KEY] --confirm-current-terms [--url OFFICIAL_URL]
  node cdp-cli.mjs capture-registry --task-dir DIR --query-id QRY-... --provider PROVIDER --record ID --candidate-id CAND-... --right-type TYPE --jurisdiction CC [--source-key KEY] --confirm-current-terms

2.4: --acceptance-probe permits a real automatic attempt only for an existing US executor.
Successful plan-bound acceptance is reused in this task for the same route for 48 hours.
Users may only complete login/CAPTCHA/QR; rerun the same planned query afterwards.
Manual open/capture-registry workflows and --confirm-current-terms apply only to historical 2.3 tasks.
`);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.command || args.command === "help" || args.command === "--help") {
    printHelp();
    return;
  }
  let result;
  if (args.command === "automation-capability") {
    result = getAutomationCapability({ provider: args.provider, jurisdiction: args.jurisdiction,
      rightType: args.right_type, operation: args.operation });
  } else if (args.command === "registry-catalog") {
    result = { status: "success", ...publicRegistryCatalog() };
  } else {
    const config = await loadConfig();
    const automatic = ["run-planned-query", "verify-candidate"].includes(args.command);
    const deadline = args.deadline_epoch_ms === undefined
      ? automatic ? Date.now() + Number(config.cdp?.operation_timeout_ms || 165000) : Infinity
      : Number(args.deadline_epoch_ms);
    try {
      result = await withOperationDeadline(async () => {
        let result;
        if (args.command === "doctor") result = await doctor(config);
        else if (args.command === "capture-amazon") result = await captureAmazon(args, config);
        else if (args.command === "run-planned-query") result = await runPlannedQuery(args, config);
        else if (args.command === "verify-candidate") result = await verifyCandidate(args, config);
        else if (args.command === "open-registry-search") result = await openRegistrySearch(args, config);
        else if (args.command === "capture-registry-search") result = await captureRegistrySearch(args, config);
        else if (args.command === "open-registry") result = await openRegistryRecord(args, config);
        else if (args.command === "capture-registry") result = await captureRegistryRecord(args, config);
        else throw new Error(`Unknown command: ${args.command}`);
        return result;
      }, deadline);
    } finally { await releaseAutomaticPages(); }
  }
  assertNoSensitiveKeys(result, "result");
  const exitCode = ["failed", "access_limited"].includes(result.status) ? 2 : 0;
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`, () => process.exit(exitCode));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    process.stdout.write(`${JSON.stringify({ status: "access_limited", error_code: error.code || "BROWSER_EXECUTION_FAILED", detail: sanitizeSensitiveText(error?.message || error) })}\n`, () => process.exit(1));
  });
}
