import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, mkdtempSync, mkdirSync, readFileSync, writeFileSync, unlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";

const testsDir = dirname(fileURLToPath(import.meta.url));
const skillDir = resolve(testsDir, "..");
const cli = join(skillDir, "tools", "ipr-risk-v2.mjs");
const fixtureDir = join(testsDir, "fixtures", "rating-v2");
const manifest = JSON.parse(readFileSync(join(fixtureDir, "manifest.json"), "utf8"));

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonicalize(value[key])]));
  }
  return value;
}

function stableDigest(value) {
  return createHash("sha256").update(JSON.stringify(canonicalize(value))).digest("hex");
}

function rawDigest(value) {
  return createHash("sha256").update(value).digest("hex");
}

function finalizeImmutableArtifact(value) {
  const artifact = { ...value };
  delete artifact.digest;
  return { ...artifact, digest: stableDigest(artifact) };
}

function writeTestSourceManifest(taskDir) {
  const product = JSON.parse(readFileSync(join(taskDir, "02_product_facts.json"), "utf8"));
  const ledger = JSON.parse(readFileSync(join(taskDir, "05_evidence_ledger.json"), "utf8"));
  const paths = new Set(["02_product_facts.json", "04_query_plan.json", "05_evidence_ledger.json", "checkpoints/coverage.json"]);
  if (existsSync(join(taskDir, "01_task.json"))) paths.add("01_task.json");
  const add = (value) => {
    if (typeof value === "string" && value.length > 0) paths.add(value);
  };
  for (const image of product.images ?? []) add(image.path);
  for (const declaration of product.provenance_declarations ?? []) {
    if ((product.images ?? []).some((image) => image.path === declaration.asset_ref)
      || /^(?:input-images|raw|screenshots)\//.test(declaration.asset_ref ?? "")) add(declaration.asset_ref);
    for (const ref of declaration.evidence_refs ?? []) if (/^(?:raw|screenshots)\//.test(ref)) add(ref);
  }
  for (const run of ledger.provider_runs ?? []) {
    add(run.result_path);
    const result = JSON.parse(readFileSync(join(taskDir, run.result_path), "utf8"));
    add(result.raw_path);
  }
  for (const evidence of ledger.evidence_items ?? []) for (const ref of evidence.raw_refs ?? []) add(ref);
  for (const entry of [...(ledger.official_verifications ?? []), ...(ledger.copyright_provenance_verifications ?? [])]) {
    add(entry.event_path);
    const event = JSON.parse(readFileSync(join(taskDir, entry.event_path), "utf8"));
    add(event.asset_ref);
    for (const proof of event.proof_refs ?? []) add(proof.path);
  }
  const previousPath = join(taskDir, "v2", "source-manifest.json");
  const previous = existsSync(previousPath) ? JSON.parse(readFileSync(previousPath, "utf8")) : null;
  const manifest = {
    schema_version: "2.0",
    ruleset_version: "2.0",
    task_id: product.task_id,
    revision: previous ? previous.revision + 1 : 1,
    parent_digest: previous?.digest ?? null,
    sealed_at: new Date().toISOString(),
    artifacts: [...paths].sort().map((relativePath) => {
      const content = readFileSync(join(taskDir, relativePath));
      return { path: relativePath, sha256: rawDigest(content), bytes: content.length };
    }),
  };
  mkdirSync(dirname(previousPath), { recursive: true });
  writeFileSync(previousPath, JSON.stringify(finalizeImmutableArtifact(manifest)));
}

function run(args, { expectStatus = 0 } = {}) {
  const result = spawnSync(process.execPath, [cli, ...args], {
    cwd: skillDir,
    encoding: "utf8",
  });
  assert.equal(result.status, expectStatus, `command failed: ${args.join(" ")}\n${result.stderr}`);
  const text = expectStatus === 0 ? result.stdout : result.stderr;
  return JSON.parse(text);
}

function assertSubset(actual, expected, path = "result") {
  if (Array.isArray(expected)) {
    assert.ok(Array.isArray(actual), `${path} must be an array`);
    for (const expectedItem of expected) {
      if (expectedItem && typeof expectedItem === "object" && expectedItem.module) {
        const actualItem = actual.find((item) => item.module === expectedItem.module);
        assert.ok(actualItem, `${path} missing module ${expectedItem.module}`);
        assertSubset(actualItem, expectedItem, `${path}.${expectedItem.module}`);
      } else {
        assert.ok(actual.some((item) => JSON.stringify(item) === JSON.stringify(expectedItem)), `${path} missing expected item`);
      }
    }
    return;
  }
  if (expected && typeof expected === "object") {
    assert.ok(actual && typeof actual === "object", `${path} must be an object`);
    for (const [key, value] of Object.entries(expected)) {
      assertSubset(actual[key], value, `${path}.${key}`);
    }
    return;
  }
  assert.equal(actual, expected, path);
}

function traceCodes(result) {
  return new Set([
    ...(result.decision_trace?.reason_codes ?? []),
    ...result.modules.flatMap((module) => module.basis_codes ?? []),
    ...(result.decision_trace?.candidate_evaluations ?? []).flatMap((item) => item.basis_codes ?? []),
  ]);
}

function readFixture(name) {
  return JSON.parse(readFileSync(join(fixtureDir, `${name}.input.json`), "utf8"));
}

function evaluateObject(input, { expectStatus = 0 } = {}) {
  const directory = mkdtempSync(join(tmpdir(), "lc-ipr-v2-input-"));
  const path = join(directory, "input.json");
  writeFileSync(path, JSON.stringify(input));
  return run(["rules", "evaluate", "--input", path, "--dry-run"], { expectStatus });
}

function writeFrozenEvidence(taskDir, input) {
  const evidenceItems = [];
  const ledgerCandidates = [];
  const officialVerifications = [];
  const copyrightVerifications = [];
  const seenEvidence = new Set();
  const seenVerifications = new Set();
  const discoveryModules = [
    "appearance_design", "utility_patent", "pending_patent", "word_mark",
    "figurative_trade_dress", "copyright_creative_ip", "enforcement_public_signals",
  ];
  const discoveryModule = (module) => ["figurative_mark", "trade_dress"].includes(module) ? "figurative_trade_dress" : module;
  const existingProduct = existsSync(join(taskDir, "02_product_facts.json"))
    ? JSON.parse(readFileSync(join(taskDir, "02_product_facts.json"), "utf8"))
    : {};
  const productTitle = existingProduct?.facts?.title?.value ?? existingProduct?.product?.title ?? "Fixture product";
  const collectedAt = "2026-09-02T00:00:00Z";
  const source = { source_type: "agent_derived", source_ref: "fixture", collected_at: collectedAt };
  const productImagePath = "input-images/fixture-product.png";
  const productImageContent = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "base64");
  const provenanceProofPath = "raw/copyright-provenance/product-provenance.json";
  const provenanceProofContent = JSON.stringify({
    schema_version: "2.0",
    task_id: input.task_id,
    asset_ref: productImagePath,
    asset_sha256: rawDigest(productImageContent),
    creator: "fixture creator",
    rights_owner: "fixture creator",
    rights_basis: "original",
    commercial_use_allowed: true,
    amazon_use_allowed: true,
    territory_includes_us: true,
    term_valid: true,
  });
  mkdirSync(dirname(join(taskDir, productImagePath)), { recursive: true });
  mkdirSync(dirname(join(taskDir, provenanceProofPath)), { recursive: true });
  writeFileSync(join(taskDir, productImagePath), productImageContent);
  writeFileSync(join(taskDir, provenanceProofPath), provenanceProofContent);
  const fact = (value) => ({ state: "provided", value, sources: [source] });
  const productFacts = finalizeImmutableArtifact({
    schema_version: "0.1",
    task_id: input.task_id,
    product_id: `fixture-${input.task_id}`,
    marketplace: "US",
    asin: null,
    input_mode: "manual_detail",
    facts: {
      title: fact(productTitle),
      brand: fact("Fixture Brand"),
      category: fact("Fixture Category"),
      bullet_points: fact([]),
      description: fact("Fixture product used for source-chain tests."),
      materials: fact([]),
      technical_functions: fact([]),
    },
    images: [{
      image_id: "IMG-fixture-main",
      role: "main",
      path: productImagePath,
      sha256: rawDigest(productImageContent),
      original_name: "fixture-product.png",
      source_rank: 0,
      public_url: null,
      source,
    }],
    feature_inventory: [{
      feature_id: "feature-fixture-product",
      kind: "other",
      state: "provided",
      description: "Fixture product feature inventory.",
      source_refs: ["product.fixture"],
      sources: [source],
    }],
    provenance_declarations: [{
      asset_ref: productImagePath,
      asset_sha256: rawDigest(productImageContent),
      state: "provided",
      details: "Fixture-owned creative asset.",
      creator: "fixture creator",
      rights_owner: "fixture creator",
      rights_basis: "original",
      license_scope: "Owned for commercial and Amazon use.",
      territory: "US",
      term: "perpetual",
      evidence_refs: [provenanceProofPath],
      sources: [source],
    }],
    frozen_at: collectedAt,
  });
  writeFileSync(join(taskDir, "02_product_facts.json"), JSON.stringify(productFacts));
  const providerRuns = [];
  const runByModule = new Map();
  const rawContentByModule = new Map();
  for (const module of discoveryModules) {
    const runId = `RUN-fixture_${module}`;
    const queryId = `Q-fixture_${module}`;
    const resultRelativePath = `normalized/provider-results/${runId}.json`;
    const rawRelativePath = `raw/${runId}.json`;
    const moduleCandidates = input.candidates.filter((candidate) => discoveryModule(candidate.module) === module);
    const rawItems = moduleCandidates.flatMap((candidate) => candidate.evidence_refs.map((evidenceRef) => ({ candidate, evidence_ref: evidenceRef })));
    const rawResult = JSON.stringify({ task_id: input.task_id, run_id: runId, raw_results: rawItems });
    const providerResult = JSON.stringify({
      schema_version: "0.1",
      task_id: input.task_id,
      run_id: runId,
      operation_id: `OP-${module}`,
      query_id: queryId,
      provider: "fixture-provider",
      capability: "fixture-search",
      query: `fixture query for ${module}`,
      jurisdiction: "US",
      right_type: module,
      evidence_type: "fixture_evidence",
      coverage_modules: [module],
      status: rawItems.length > 0 ? "success" : "no_result",
      started_at: "2026-09-02T00:00:00Z",
      finished_at: "2026-09-02T00:00:01Z",
      http_status: 200,
      raw_path: rawRelativePath,
      raw_sha256: rawDigest(rawResult),
      parser: { name: "fixture-parser", version: "1.0", schema_valid: true, warnings: [] },
      counts: { items: rawItems.length, total: rawItems.length },
      cost: { billable: false, units: 0, unit_name: "request" },
      safe_error: null,
    });
    mkdirSync(dirname(join(taskDir, resultRelativePath)), { recursive: true });
    mkdirSync(dirname(join(taskDir, rawRelativePath)), { recursive: true });
    writeFileSync(join(taskDir, resultRelativePath), providerResult);
    writeFileSync(join(taskDir, rawRelativePath), rawResult);
    providerRuns.push({ run_id: runId, query_id: queryId, result_path: resultRelativePath, result_sha256: rawDigest(providerResult) });
    runByModule.set(module, { runId, queryId, rawRelativePath });
    rawContentByModule.set(module, rawResult);
  }
  const sourceIndexByRun = new Map();
  const formalCandidates = input.candidates;
  for (const candidate of formalCandidates) {
    const source = runByModule.get(discoveryModule(candidate.module));
    let sourceIndex = sourceIndexByRun.get(source.runId) ?? 0;
    const candidateSourceRefs = [];
    for (const evidenceId of candidate.evidence_refs) {
      if (seenEvidence.has(evidenceId)) continue;
      seenEvidence.add(evidenceId);
      evidenceItems.push({
        evidence_id: evidenceId,
        run_id: source.runId,
        source_index: sourceIndex,
        module: candidate.module,
        jurisdiction: "US",
        right_type: candidate.module,
        record_number: candidate.record_number ?? null,
        title: candidate.title ?? null,
        owner: candidate.owner ?? null,
        source_locator: candidate.source_locator ?? `fixture://${candidate.candidate_id}`,
        summary: `Authoritative fixture evidence for ${candidate.candidate_id}`,
        raw_refs: [source.rawRelativePath],
      });
      candidateSourceRefs.push({ run_id: source.runId, source_index: sourceIndex });
      sourceIndex += 1;
      sourceIndexByRun.set(source.runId, sourceIndex);
    }
    ledgerCandidates.push({
      candidate_id: candidate.candidate_id,
      candidate_key: `US:${candidate.module}:${candidate.candidate_id}`,
      evidence_refs: [...candidate.evidence_refs],
      source_refs: candidateSourceRefs,
      module: candidate.module,
      jurisdiction: "US",
      right_type: candidate.module,
      record_number: candidate.record_number ?? null,
      title: candidate.title ?? null,
      owner: candidate.owner ?? null,
      disposition: null,
    });
    for (const verificationId of candidate.verification_refs) {
      if (seenVerifications.has(verificationId) || !/^(?:V-|CPV-)/.test(verificationId)) continue;
      seenVerifications.add(verificationId);
      const copyright = verificationId.startsWith("CPV-");
      const relativePath = copyright
        ? `normalized/copyright-provenance-verifications/${verificationId}.json`
        : `normalized/official-verifications/${verificationId}.json`;
      const copyrightProofPath = "raw/copyright-provenance/fixture-proof.json";
      const copyrightProof = JSON.stringify({ task_id: input.task_id, candidate_id: candidate.candidate_id, proof: "unlicensed" });
      if (copyright) {
        mkdirSync(dirname(join(taskDir, copyrightProofPath)), { recursive: true });
        writeFileSync(join(taskDir, copyrightProofPath), copyrightProof);
      }
      const event = copyright
        ? finalizeImmutableArtifact({
          schema_version: "0.1",
          verification_id: verificationId,
          task_id: input.task_id,
          candidate_id: candidate.candidate_id,
          candidate_key: `US:${candidate.module}:${candidate.candidate_id}`,
          evidence_revision: 1,
          asset_ref: source.rawRelativePath,
          asset_sha256: rawDigest(rawContentByModule.get(discoveryModule(candidate.module))),
          resolution: "unlicensed",
          creator: "fixture creator",
          rights_owner: "fixture rights owner",
          rights_basis: "original",
          license_scope: "No commercial license",
          territory: "US",
          term: "active",
          commercial_use_allowed: false,
          amazon_use_allowed: false,
          proof_refs: [{ role: "conflict_evidence", path: copyrightProofPath, sha256: rawDigest(copyrightProof) }],
          verified_by: { type: "reviewer", id: "fixture-reviewer", session_id: "fixture-session" },
          verified_at: "2026-09-02T00:00:00Z",
          notes: "Test-only provenance verification",
        })
        : finalizeImmutableArtifact({
          schema_version: "2.0",
          verification_id: verificationId,
          task_id: input.task_id,
          candidate_id: candidate.candidate_id,
          authority_tier: "official",
          official_record_verified: true,
          official_status: ["active", "pending", "expired", "cancelled", "abandoned", "rejected", "disputed", "not_found"]
            .includes(candidate.factors.right_status) ? candidate.factors.right_status : "active",
          authorization_status: verificationId.includes("authorization")
            ? candidate.factors.authorization_status
            : "unknown",
          right_identity: {
            module: candidate.module,
            jurisdiction: "US",
            record_number: candidate.record_number ?? null,
          },
          ...(candidate.module === "enforcement_public_signals" ? {
            enforcement_identity: {
              claimant: candidate.factors.claimant,
              case_or_complaint_id: candidate.factors.case_or_complaint_id,
              procedure_status: candidate.factors.procedure_status,
              target_product_digest: productFacts.digest,
              underlying_candidate_ids: [...candidate.factors.underlying_risk_driver_ids],
            },
          } : {}),
          evidence_refs: [...candidate.evidence_refs],
          source_locator: `official://fixture/${candidate.candidate_id}`,
          verified_by: { type: "reviewer", id: "fixture-reviewer", session_id: "fixture-session" },
          verified_at: "2026-09-02T00:00:00Z",
        });
      const content = JSON.stringify(event);
      mkdirSync(dirname(join(taskDir, relativePath)), { recursive: true });
      writeFileSync(join(taskDir, relativePath), content);
      const entry = {
        verification_id: verificationId,
        candidate_id: candidate.candidate_id,
        event_path: relativePath,
        event_sha256: rawDigest(content),
      };
      (copyright ? copyrightVerifications : officialVerifications).push(entry);
    }
  }
  const queryPlan = finalizeImmutableArtifact({
    schema_version: "0.1",
    task_id: input.task_id,
    product_facts_digest: productFacts.digest,
    plan_version: 1,
    items: discoveryModules.map((module) => ({
      query_id: runByModule.get(module).queryId,
      module,
      target_jurisdiction: "US",
      provider_jurisdiction: "US",
      right_type: module,
      evidence_type: "fixture_evidence",
      query_family: "fixture-complete-coverage",
      query: `fixture query for ${module}`,
      strategy: "Test-only complete discovery coverage.",
      required: true,
      allowed_providers: ["fixture-provider"],
      preferred_provider: "fixture-provider",
      capability: "fixture-search",
      execution_state: "ready",
      completion_rule: { accepted_statuses: ["success", "no_result"], schema_validator: "provider-result.schema.json#0.1" },
      input_refs: ["product.fixture"],
    })),
    frozen_at: "2026-09-02T00:00:00Z",
  });
  writeFileSync(join(taskDir, "04_query_plan.json"), JSON.stringify(queryPlan));
  const ledger = {
    schema_version: "0.1",
    task_id: input.task_id,
    revision: 1,
    parent_digest: null,
    query_plan_digest: queryPlan.digest,
    provider_runs: providerRuns,
    evidence_items: evidenceItems,
    candidates: ledgerCandidates,
    official_verifications: officialVerifications,
    copyright_provenance_verifications: copyrightVerifications,
    updated_at: "2026-09-02T00:00:00Z",
    digest: "0".repeat(64),
    frozen: true,
    frozen_at: "2026-09-02T00:00:00Z",
  };
  ledger.digest = stableDigest(ledger);
  writeFileSync(join(taskDir, "05_evidence_ledger.json"), JSON.stringify(ledger));
  const coverage = finalizeImmutableArtifact({
    schema_version: "0.1",
    task_id: input.task_id,
    query_plan_digest: queryPlan.digest,
    evidence_digest: ledger.digest,
    status: "complete",
    assessment_ready: true,
    required_total: discoveryModules.length,
    completed_total: discoveryModules.length,
    rows: discoveryModules.map((module) => ({
      query_id: runByModule.get(module).queryId,
      module,
      target_jurisdiction: "US",
      provider_jurisdiction: "US",
      required: true,
      coverage_status: "complete",
      reason_code: "QUERY_COMPLETED",
      matching_run_ids: [runByModule.get(module).runId],
    })),
    gap_query_ids: [],
    evaluated_at: "2026-09-02T00:00:02Z",
  });
  mkdirSync(join(taskDir, "checkpoints"), { recursive: true });
  writeFileSync(join(taskDir, "checkpoints", "coverage.json"), JSON.stringify(coverage));
  writeTestSourceManifest(taskDir);
}

function writeReleaseFixtureInput(taskDir, suffix, { withEvidence = true } = {}) {
  const input = readFixture("active-design-strong-overlap");
  input.task_id = `ipr_fixture_${suffix}`;
  const inputPath = join(taskDir, "assessment-input.json");
  writeFileSync(inputPath, JSON.stringify(input));
  if (withEvidence) writeFrozenEvidence(taskDir, input);
  return { input, inputPath };
}

function moveOnlyCandidateToModule(input, module) {
  const candidate = input.candidates[0];
  const originalModule = candidate.module;
  candidate.module = module;
  input.modules.find((item) => item.module === originalModule).candidate_ids = [];
  input.modules.find((item) => item.module === module).candidate_ids = [candidate.candidate_id];
  return candidate;
}

for (const fixture of manifest.cases) {
  test(`rating fixture: ${fixture.id}`, () => {
    const input = join(fixtureDir, fixture.input);
    const inputData = JSON.parse(readFileSync(input, "utf8"));
    const expected = JSON.parse(readFileSync(join(fixtureDir, fixture.expected), "utf8"));
    const result = run(["rules", "evaluate", "--input", input, "--dry-run"]);
    assert.equal(result.task_id, expected.task_id);
    assertSubset(result.overall, expected.expected.overall, "overall");
    if (expected.expected.modules) assertSubset(result.modules, expected.expected.modules, "modules");
    if (expected.expected.constraints) assertSubset(result.constraints, expected.expected.constraints, "constraints");
    if (expected.expected.evidence_summary) assertSubset(result.discovery_summary, expected.expected.evidence_summary, "evidence_summary");
    if (expected.expected.resolution_path) {
      const resolutionPath = result.constraints.human_resolution_required ? "human_resolution_required" : "not_required";
      assert.equal(resolutionPath, expected.expected.resolution_path, "resolution_path");
    }
    if (expected.assertions?.counts) {
      assertSubset({
        input_candidates: inputData.candidates.length,
        unique_evidence_clusters: result.discovery_summary.unique_evidence_cluster_count,
        independent_evidence_groups: result.discovery_summary.independent_evidence_group_count,
        eligible_risk_drivers: inputData.candidates.filter((candidate) => candidate.risk_driver_eligible === true).length,
      }, expected.assertions.counts, "counts");
    }
    if (expected.expected.report) {
      const taskDir = mkdtempSync(join(tmpdir(), `lc-ipr-v2-${fixture.id}-report-`));
      mkdirSync(join(taskDir, "v2"), { recursive: true });
      writeFileSync(join(taskDir, "02_product_facts.json"), JSON.stringify({ product: { title: fixture.id, marketplace: "US" } }));
      run(["finalize-assessment", "--task-dir", taskDir, "--input", input]);
      run(["render-report", "--task-dir", taskDir]);
      const report = JSON.parse(readFileSync(join(taskDir, "report-v2", "report_data.json"), "utf8"));
      const html = readFileSync(join(taskDir, "report-v2", "ipr-risk-screening-report.html"), "utf8");
      assertSubset({
        report_mode: report.report_mode,
        legal_risk_label: report.overview.legal_risk_label,
        legacy_risk_seal_visible: report.overview.legacy_risk_seal_visible
          || /class="risk risk-(?:very_low|low|medium|high|critical)"/.test(html),
      }, expected.expected.report, "report");
    }
    const codes = traceCodes(result);
    for (const code of expected.assertions?.must_include_trace_codes ?? []) {
      assert.ok(codes.has(code), `${fixture.id} missing trace code ${code}`);
    }
    for (const code of expected.assertions?.must_not_include_trace_codes ?? []) {
      assert.ok(!codes.has(code), `${fixture.id} unexpectedly contains trace code ${code}`);
    }
  });
}

test("rules audit fingerprint binds the descriptor and executable evaluator", () => {
  const described = run(["rules", "describe", "--json"]);
  assert.match(described.audit.descriptor_digest, /^[a-f0-9]{64}$/);
  assert.match(described.audit.executable_rules_digest, /^[a-f0-9]{64}$/);
  assert.match(described.audit.rules_fingerprint, /^[a-f0-9]{64}$/);
  assert.notEqual(described.audit.rules_fingerprint, described.audit.descriptor_digest);
  assert.equal(run(["version"]).rules_fingerprint, described.audit.rules_fingerprint);
});

test("draft rendering never exposes a formal high/low risk seal", () => {
  const taskDir = mkdtempSync(join(tmpdir(), "lc-ipr-v2-draft-"));
  mkdirSync(join(taskDir, "v2"), { recursive: true });
  writeFileSync(join(taskDir, "02_product_facts.json"), JSON.stringify({ product: { title: "Draft fixture", marketplace: "US" } }));
  const input = join(fixtureDir, "draft-assessment-not-finalized.input.json");
  run(["finalize-assessment", "--task-dir", taskDir, "--input", input]);
  run(["render-report", "--task-dir", taskDir]);
  const report = JSON.parse(readFileSync(join(taskDir, "report-v2", "report_data.json"), "utf8"));
  const html = readFileSync(join(taskDir, "report-v2", "ipr-risk-screening-report.html"), "utf8");
  assert.equal(report.report_mode, "draft");
  assert.equal(report.overview.legal_risk, "not_assessable");
  assert.match(html, /评估尚未完成/);
  assert.doesNotMatch(html, /class="risk risk-(?:high|critical|medium|low|very_low)"/);
  const release = run(["validate-release", "--task-dir", taskDir], { expectStatus: 2 });
  assert.equal(release.reason_code, "FORMAL_CONCLUSION_BLOCKED");
});

test("formal assessment renders and passes the v2 manifest release gate", () => {
  const taskDir = mkdtempSync(join(tmpdir(), "lc-ipr-v2-formal-"));
  mkdirSync(join(taskDir, "v2"), { recursive: true });
  writeFileSync(join(taskDir, "02_product_facts.json"), JSON.stringify({ product: { title: "Formal fixture", marketplace: "US" } }));
  const { inputPath } = writeReleaseFixtureInput(taskDir, "formal_release");
  const finalized = run(["finalize-assessment", "--task-dir", taskDir, "--input", inputPath]);
  assert.equal(finalized.legal_risk, "high");
  const rendered = run(["render-report", "--task-dir", taskDir]);
  assert.equal(rendered.report_mode, "formal");
  const report = JSON.parse(readFileSync(join(taskDir, "report-v2", "report_data.json"), "utf8"));
  assert.equal(report.product.title, "Formal fixture");
  assert.equal(report.product.brand, "Fixture Brand");
  const release = run(["validate-release", "--task-dir", taskDir]);
  assert.equal(release.reason_code, "V2_RELEASE_VALIDATED");
});

test("official verification can be ingested through the supported v2 command chain", () => {
  const taskDir = mkdtempSync(join(tmpdir(), "lc-ipr-v2-verification-ingestion-"));
  mkdirSync(join(taskDir, "v2"), { recursive: true });
  const input = readFixture("active-design-strong-overlap");
  input.task_id = "ipr_fixture_verification_ingestion";
  input.candidates[0].verification_refs = ["V-design-authorization-unlicensed"];
  const inputPath = join(taskDir, "assessment-input.json");
  writeFileSync(inputPath, JSON.stringify(input));
  writeFrozenEvidence(taskDir, input);

  const ledgerPath = join(taskDir, "05_evidence_ledger.json");
  const coveragePath = join(taskDir, "checkpoints", "coverage.json");
  const ledger = JSON.parse(readFileSync(ledgerPath, "utf8"));
  const entry = ledger.official_verifications[0];
  const eventPath = join(taskDir, entry.event_path);
  const event = JSON.parse(readFileSync(eventPath, "utf8"));
  const eventInputPath = join(taskDir, "official-verification-input.json");
  writeFileSync(eventInputPath, JSON.stringify(event));
  ledger.official_verifications = [];
  ledger.digest = finalizeImmutableArtifact(ledger).digest;
  writeFileSync(ledgerPath, JSON.stringify(ledger));
  const coverage = JSON.parse(readFileSync(coveragePath, "utf8"));
  coverage.evidence_digest = ledger.digest;
  coverage.digest = finalizeImmutableArtifact(coverage).digest;
  writeFileSync(coveragePath, JSON.stringify(coverage));
  unlinkSync(eventPath);
  writeTestSourceManifest(taskDir);

  const recorded = run(["record-verification", "--kind", "official", "--task-dir", taskDir, "--input", eventInputPath]);
  assert.equal(recorded.reason_code, "VERIFICATION_RECORDED");
  assert.equal(recorded.assessment_rebuild_required, true);
  assert.equal(recorded.evidence_revision, 2);
  assert.equal(existsSync(join(taskDir, recorded.event_path)), true);
  assert.equal(run(["finalize-assessment", "--task-dir", taskDir, "--input", inputPath]).legal_risk, "high");
  run(["render-report", "--task-dir", taskDir]);
  assert.equal(run(["validate-release", "--task-dir", taskDir]).reason_code, "V2_RELEASE_VALIDATED");
});

test("formal very-low conclusions require real discovery and frozen zero-result evidence", () => {
  const buildNoLead = (taskId) => {
    const input = readFixture("active-design-strong-overlap");
    input.task_id = taskId;
    input.candidates = [];
    input.modules = input.modules.map((module) => ({
      ...module,
      assessability: "assessable",
      confidence: "high",
      candidate_ids: [],
      provenance_complete: true,
      unresolved_material_facts: [],
      recommended_actions: [],
    }));
    return input;
  };
  const missingDir = mkdtempSync(join(tmpdir(), "lc-ipr-v2-no-source-very-low-"));
  mkdirSync(join(missingDir, "v2"), { recursive: true });
  writeFileSync(join(missingDir, "02_product_facts.json"), JSON.stringify({ product: { title: "No source", marketplace: "US" } }));
  const missingInput = buildNoLead("ipr_fixture_no_source_very_low");
  const missingInputPath = join(missingDir, "assessment-input.json");
  writeFileSync(missingInputPath, JSON.stringify(missingInput));
  assert.equal(evaluateObject(missingInput).overall.legal_risk, "very_low");
  assert.equal(run(["finalize-assessment", "--task-dir", missingDir, "--input", missingInputPath], { expectStatus: 2 }).reason_code, "FORMAL_SOURCE_LEDGER_REQUIRED");

  const provenDir = mkdtempSync(join(tmpdir(), "lc-ipr-v2-proven-zero-result-"));
  mkdirSync(join(provenDir, "v2"), { recursive: true });
  writeFileSync(join(provenDir, "02_product_facts.json"), JSON.stringify({ product: { title: "Proven zero result", marketplace: "US" } }));
  const provenInput = buildNoLead("ipr_fixture_proven_zero_result");
  const provenInputPath = join(provenDir, "assessment-input.json");
  writeFileSync(provenInputPath, JSON.stringify(provenInput));
  writeFrozenEvidence(provenDir, provenInput);
  assert.equal(run(["finalize-assessment", "--task-dir", provenDir, "--input", provenInputPath]).legal_risk, "very_low");
  run(["render-report", "--task-dir", provenDir]);
  assert.equal(run(["validate-release", "--task-dir", provenDir]).reason_code, "V2_RELEASE_VALIDATED");

  const incompleteDir = mkdtempSync(join(tmpdir(), "lc-ipr-v2-incomplete-discovery-"));
  mkdirSync(join(incompleteDir, "v2"), { recursive: true });
  const incompleteInput = buildNoLead("ipr_fixture_incomplete_discovery");
  const incompleteInputPath = join(incompleteDir, "assessment-input.json");
  writeFileSync(incompleteInputPath, JSON.stringify(incompleteInput));
  writeFrozenEvidence(incompleteDir, incompleteInput);
  const coveragePath = join(incompleteDir, "checkpoints", "coverage.json");
  const coverage = JSON.parse(readFileSync(coveragePath, "utf8"));
  coverage.rows.pop();
  coverage.required_total -= 1;
  coverage.completed_total -= 1;
  writeFileSync(coveragePath, JSON.stringify(coverage));
  assert.equal(
    run(["finalize-assessment", "--task-dir", incompleteDir, "--input", incompleteInputPath], { expectStatus: 2 }).reason_code,
    "FORMAL_COVERAGE_CHECKPOINT_INVALID",
  );

  const deniedDir = mkdtempSync(join(tmpdir(), "lc-ipr-v2-denied-provenance-"));
  mkdirSync(join(deniedDir, "v2"), { recursive: true });
  const deniedInput = buildNoLead("ipr_fixture_denied_provenance");
  const deniedInputPath = join(deniedDir, "assessment-input.json");
  writeFileSync(deniedInputPath, JSON.stringify(deniedInput));
  writeFrozenEvidence(deniedDir, deniedInput);
  const deniedProductPath = join(deniedDir, "02_product_facts.json");
  const deniedProduct = JSON.parse(readFileSync(deniedProductPath, "utf8"));
  deniedProduct.provenance_declarations[0].license_scope = "No commercial use; not for Amazon";
  deniedProduct.provenance_declarations[0].territory = "NOT US";
  deniedProduct.provenance_declarations[0].term = "expired";
  writeFileSync(deniedProductPath, JSON.stringify(deniedProduct));
  writeTestSourceManifest(deniedDir);
  assert.equal(
    run(["finalize-assessment", "--task-dir", deniedDir, "--input", deniedInputPath], { expectStatus: 2 }).reason_code,
    "FORMAL_PROVENANCE_INCOMPLETE",
  );

  const missingAssetDir = mkdtempSync(join(tmpdir(), "lc-ipr-v2-missing-asset-provenance-"));
  mkdirSync(join(missingAssetDir, "v2"), { recursive: true });
  const missingAssetInput = buildNoLead("ipr_fixture_missing_asset_provenance");
  const missingAssetInputPath = join(missingAssetDir, "assessment-input.json");
  writeFileSync(missingAssetInputPath, JSON.stringify(missingAssetInput));
  writeFrozenEvidence(missingAssetDir, missingAssetInput);
  const secondImagePath = "input-images/fixture-second.png";
  const secondImageContent = Buffer.from("second creative asset");
  writeFileSync(join(missingAssetDir, secondImagePath), secondImageContent);
  const missingAssetProductPath = join(missingAssetDir, "02_product_facts.json");
  const missingAssetProduct = JSON.parse(readFileSync(missingAssetProductPath, "utf8"));
  missingAssetProduct.images.push({
    ...missingAssetProduct.images[0],
    image_id: "IMG-fixture-second",
    path: secondImagePath,
    sha256: rawDigest(secondImageContent),
    original_name: "fixture-second.png",
    source_rank: 1,
  });
  writeFileSync(missingAssetProductPath, JSON.stringify(missingAssetProduct));
  writeTestSourceManifest(missingAssetDir);
  assert.equal(
    run(["finalize-assessment", "--task-dir", missingAssetDir, "--input", missingAssetInputPath], { expectStatus: 2 }).reason_code,
    "FORMAL_PROVENANCE_INCOMPLETE",
  );
});

test("formal medium conclusions cannot cite dangling assessment-only evidence", () => {
  const taskDir = mkdtempSync(join(tmpdir(), "lc-ipr-v2-medium-no-ledger-"));
  mkdirSync(join(taskDir, "v2"), { recursive: true });
  writeFileSync(join(taskDir, "02_product_facts.json"), JSON.stringify({ product: { title: "Medium without ledger", marketplace: "US" } }));
  const input = readFixture("htwo-ballerina-planter");
  input.task_id = "ipr_fixture_medium_without_ledger";
  const inputPath = join(taskDir, "assessment-input.json");
  writeFileSync(inputPath, JSON.stringify(input));
  assert.equal(evaluateObject(input).overall.legal_risk, "medium");
  assert.equal(run(["finalize-assessment", "--task-dir", taskDir, "--input", inputPath], { expectStatus: 2 }).reason_code, "FORMAL_SOURCE_LEDGER_REQUIRED");
});

test("high release requires frozen, non-dangling source and verification evidence", () => {
  const prepare = (prefix) => {
    const taskDir = mkdtempSync(join(tmpdir(), prefix));
    mkdirSync(join(taskDir, "v2"), { recursive: true });
    writeFileSync(join(taskDir, "02_product_facts.json"), JSON.stringify({ product: { title: prefix, marketplace: "US" } }));
    return taskDir;
  };

  const missingLedger = prepare("lc-ipr-v2-no-ledger-");
  const missing = writeReleaseFixtureInput(missingLedger, "missing_ledger", { withEvidence: false });
  assert.equal(run(["finalize-assessment", "--task-dir", missingLedger, "--input", missing.inputPath], { expectStatus: 2 }).reason_code, "HIGH_SOURCE_LEDGER_REQUIRED");
  assert.equal(existsSync(join(missingLedger, "v2", "assessment.json")), false);
  assert.equal(existsSync(join(missingLedger, "report-v2", "ipr-risk-screening-report.html")), false);

  const dangling = prepare("lc-ipr-v2-dangling-evidence-");
  const danglingInput = writeReleaseFixtureInput(dangling, "dangling_evidence");
  const danglingLedgerPath = join(dangling, "05_evidence_ledger.json");
  const danglingLedger = JSON.parse(readFileSync(danglingLedgerPath, "utf8"));
  danglingLedger.evidence_items = [];
  writeFileSync(danglingLedgerPath, JSON.stringify(danglingLedger));
  assert.equal(run(["finalize-assessment", "--task-dir", dangling, "--input", danglingInput.inputPath], { expectStatus: 2 }).reason_code, "HIGH_SOURCE_LEDGER_INVALID");

  const tampered = prepare("lc-ipr-v2-tampered-verification-");
  const tamperedInput = writeReleaseFixtureInput(tampered, "tampered_verification");
  run(["finalize-assessment", "--task-dir", tampered, "--input", tamperedInput.inputPath]);
  run(["render-report", "--task-dir", tampered]);
  const ledger = JSON.parse(readFileSync(join(tampered, "05_evidence_ledger.json"), "utf8"));
  writeFileSync(join(tampered, ledger.official_verifications[0].event_path), JSON.stringify({ tampered: true }));
  assert.equal(run(["validate-release", "--task-dir", tampered], { expectStatus: 2 }).reason_code, "VERIFICATION_ARTIFACT_INVALID");

  const fake = prepare("lc-ipr-v2-fake-verification-");
  const fakeInput = writeReleaseFixtureInput(fake, "fake_verification");
  const fakeLedgerPath = join(fake, "05_evidence_ledger.json");
  const fakeLedger = JSON.parse(readFileSync(fakeLedgerPath, "utf8"));
  const fakeEntry = fakeLedger.official_verifications[0];
  const fakeContent = JSON.stringify({ verification_id: fakeEntry.verification_id, candidate_id: fakeEntry.candidate_id, task_id: fakeInput.input.task_id, verified: true });
  writeFileSync(join(fake, fakeEntry.event_path), fakeContent);
  fakeEntry.event_sha256 = rawDigest(fakeContent);
  writeFileSync(fakeLedgerPath, JSON.stringify(fakeLedger));
  assert.equal(run(["finalize-assessment", "--task-dir", fake, "--input", fakeInput.inputPath], { expectStatus: 2 }).reason_code, "VERIFICATION_ARTIFACT_INVALID");

  const crossRight = prepare("lc-ipr-v2-cross-right-");
  const crossRightInput = writeReleaseFixtureInput(crossRight, "cross_right");
  const crossLedgerPath = join(crossRight, "05_evidence_ledger.json");
  const crossLedger = JSON.parse(readFileSync(crossLedgerPath, "utf8"));
  const crossEntry = crossLedger.official_verifications[0];
  const crossEventPath = join(crossRight, crossEntry.event_path);
  const crossEvent = JSON.parse(readFileSync(crossEventPath, "utf8"));
  delete crossEvent.digest;
  crossEvent.right_identity.module = "word_mark";
  const reboundCrossEvent = finalizeImmutableArtifact(crossEvent);
  const reboundCrossContent = JSON.stringify(reboundCrossEvent);
  writeFileSync(crossEventPath, reboundCrossContent);
  crossEntry.event_sha256 = rawDigest(reboundCrossContent);
  writeFileSync(crossLedgerPath, JSON.stringify(crossLedger));
  writeTestSourceManifest(crossRight);
  assert.equal(run(["finalize-assessment", "--task-dir", crossRight, "--input", crossRightInput.inputPath], { expectStatus: 2 }).reason_code, "HIGH_VERIFICATION_REFERENCE_INVALID");

  const omittedCandidate = prepare("lc-ipr-v2-omitted-ledger-candidate-");
  const omittedInput = writeReleaseFixtureInput(omittedCandidate, "omitted_ledger_candidate");
  const omittedLedgerPath = join(omittedCandidate, "05_evidence_ledger.json");
  const omittedLedger = JSON.parse(readFileSync(omittedLedgerPath, "utf8"));
  omittedLedger.candidates.push({
    ...omittedLedger.candidates[0],
    candidate_id: "C-frozen_candidate_omitted_from_assessment",
    candidate_key: "US:appearance_design:omitted-frozen-candidate",
  });
  writeFileSync(omittedLedgerPath, JSON.stringify(omittedLedger));
  writeTestSourceManifest(omittedCandidate);
  assert.equal(
    run(["finalize-assessment", "--task-dir", omittedCandidate, "--input", omittedInput.inputPath], { expectStatus: 2 }).reason_code,
    "CANDIDATE_COVERAGE_MISMATCH",
  );

  const noResultSource = prepare("lc-ipr-v2-no-result-source-");
  const noResultInput = writeReleaseFixtureInput(noResultSource, "no_result_source");
  const noResultLedgerPath = join(noResultSource, "05_evidence_ledger.json");
  const noResultLedger = JSON.parse(readFileSync(noResultLedgerPath, "utf8"));
  const producingRun = noResultLedger.provider_runs.find((run) => run.run_id === noResultLedger.evidence_items[0].run_id);
  const providerResultPath = join(noResultSource, producingRun.result_path);
  const providerResult = JSON.parse(readFileSync(providerResultPath, "utf8"));
  providerResult.status = "no_result";
  providerResult.counts = { items: 0, total: 0 };
  const noResultContent = JSON.stringify(providerResult);
  writeFileSync(providerResultPath, noResultContent);
  producingRun.result_sha256 = rawDigest(noResultContent);
  writeFileSync(noResultLedgerPath, JSON.stringify(noResultLedger));
  assert.equal(
    run(["finalize-assessment", "--task-dir", noResultSource, "--input", noResultInput.inputPath], { expectStatus: 2 }).reason_code,
    "HIGH_SOURCE_LEDGER_INVALID",
  );

  const crossProduct = prepare("lc-ipr-v2-cross-product-");
  const crossProductInput = writeReleaseFixtureInput(crossProduct, "cross_product");
  const crossProductPath = join(crossProduct, "02_product_facts.json");
  const otherProduct = JSON.parse(readFileSync(crossProductPath, "utf8"));
  delete otherProduct.digest;
  otherProduct.product_id = "different-product";
  otherProduct.facts.title.value = "Different product inserted before finalization";
  writeFileSync(crossProductPath, JSON.stringify(finalizeImmutableArtifact(otherProduct)));
  assert.equal(
    run(["finalize-assessment", "--task-dir", crossProduct, "--input", crossProductInput.inputPath], { expectStatus: 2 }).reason_code,
    "HIGH_SOURCE_LEDGER_INVALID",
  );

  const silentlyTamperedProduct = prepare("lc-ipr-v2-product-byte-tamper-");
  const silentlyTamperedInput = writeReleaseFixtureInput(silentlyTamperedProduct, "product_byte_tamper");
  const silentlyTamperedPath = join(silentlyTamperedProduct, "02_product_facts.json");
  const silentlyTamperedFacts = JSON.parse(readFileSync(silentlyTamperedPath, "utf8"));
  silentlyTamperedFacts.facts.title.value = "Changed while retaining the declared legacy digest";
  writeFileSync(silentlyTamperedPath, JSON.stringify(silentlyTamperedFacts));
  assert.equal(
    run(["finalize-assessment", "--task-dir", silentlyTamperedProduct, "--input", silentlyTamperedInput.inputPath], { expectStatus: 2 }).reason_code,
    "SOURCE_MANIFEST_MISMATCH",
  );

  const mutableScreenshot = prepare("lc-ipr-v2-mutable-screenshot-");
  const mutableScreenshotInput = writeReleaseFixtureInput(mutableScreenshot, "mutable_screenshot");
  const mutableScreenshotPath = "screenshots/official-design.png";
  mkdirSync(dirname(join(mutableScreenshot, mutableScreenshotPath)), { recursive: true });
  writeFileSync(join(mutableScreenshot, mutableScreenshotPath), Buffer.from("official screenshot"));
  const mutableLedgerPath = join(mutableScreenshot, "05_evidence_ledger.json");
  const mutableLedger = JSON.parse(readFileSync(mutableLedgerPath, "utf8"));
  mutableLedger.evidence_items[0].raw_refs.push(mutableScreenshotPath);
  writeFileSync(mutableLedgerPath, JSON.stringify(mutableLedger));
  writeTestSourceManifest(mutableScreenshot);
  run(["finalize-assessment", "--task-dir", mutableScreenshot, "--input", mutableScreenshotInput.inputPath]);
  run(["render-report", "--task-dir", mutableScreenshot]);
  assert.equal(run(["validate-release", "--task-dir", mutableScreenshot]).reason_code, "V2_RELEASE_VALIDATED");
  writeFileSync(join(mutableScreenshot, mutableScreenshotPath), Buffer.from("replaced screenshot"));
  assert.equal(
    run(["validate-release", "--task-dir", mutableScreenshot], { expectStatus: 2 }).reason_code,
    "SOURCE_MANIFEST_MISMATCH",
  );

  const unsupportedAuthorization = prepare("lc-ipr-v2-unverified-authorization-");
  const authorizationInput = readFixture("active-design-strong-overlap");
  authorizationInput.task_id = "ipr_fixture_unverified_authorization";
  authorizationInput.candidates[0].factors.authorization_status = "authorized";
  authorizationInput.candidates[0].verification_refs = [];
  const authorizationInputPath = join(unsupportedAuthorization, "assessment-input.json");
  writeFileSync(authorizationInputPath, JSON.stringify(authorizationInput));
  writeFrozenEvidence(unsupportedAuthorization, authorizationInput);
  assert.equal(evaluateObject(authorizationInput).overall.legal_risk, "low");
  assert.equal(
    run(["finalize-assessment", "--task-dir", unsupportedAuthorization, "--input", authorizationInputPath], { expectStatus: 2 }).reason_code,
    "HIGH_VERIFICATION_REFERENCE_INVALID",
  );

  const omittedAdverse = prepare("lc-ipr-v2-omitted-adverse-verification-");
  const omittedAdverseInput = writeReleaseFixtureInput(omittedAdverse, "omitted_adverse_verification");
  omittedAdverseInput.input.candidates[0].verification_refs = [];
  omittedAdverseInput.input.candidates[0].factors.official_record_verified = false;
  omittedAdverseInput.input.candidates[0].factors.authorization_status = "unknown";
  writeFileSync(omittedAdverseInput.inputPath, JSON.stringify(omittedAdverseInput.input));
  assert.equal(
    run(["finalize-assessment", "--task-dir", omittedAdverse, "--input", omittedAdverseInput.inputPath], { expectStatus: 2 }).reason_code,
    "HIGH_VERIFICATION_REFERENCE_INVALID",
  );
});

test("high copyright release binds the asset, creator, owner and unlicensed provenance event", () => {
  const buildInput = (taskId) => {
    const input = readFixture("active-design-strong-overlap");
    input.task_id = taskId;
    const candidate = moveOnlyCandidateToModule(input, "copyright_creative_ip");
    candidate.candidate_id = "C-copyright_exact_unlicensed";
    candidate.record_kind = "creative_source";
    candidate.record_number = null;
    candidate.owner = "fixture rights owner";
    candidate.evidence_refs = ["E-copyright-exact-unlicensed"];
    candidate.verification_refs = [`CPV-${"a".repeat(24)}`];
    candidate.evidence_cluster_id = "copyright_exact_unlicensed";
    candidate.independence_group = "copyright_exact_unlicensed";
    candidate.factors = {
      asset_scope: "product_sculpture",
      protectable_expression: "established",
      asset_match: "exact",
      expression_similarity: "exact",
      creator_or_earliest_source: "fixture creator",
      ownership_reliability: "high",
      authorization_status: "unlicensed",
      commercial_use_covered: false,
    };
    input.modules.find((module) => module.module === "copyright_creative_ip").candidate_ids = [candidate.candidate_id];
    return input;
  };
  const prepare = (suffix) => {
    const taskDir = mkdtempSync(join(tmpdir(), `lc-ipr-v2-copyright-${suffix}-`));
    mkdirSync(join(taskDir, "v2"), { recursive: true });
    writeFileSync(join(taskDir, "02_product_facts.json"), JSON.stringify({ product: { title: "Copyright fixture", marketplace: "US" } }));
    const input = buildInput(`ipr_fixture_copyright_${suffix}`);
    const inputPath = join(taskDir, "assessment-input.json");
    writeFileSync(inputPath, JSON.stringify(input));
    writeFrozenEvidence(taskDir, input);
    return { taskDir, inputPath };
  };

  const valid = prepare("valid");
  const validLedgerPath = join(valid.taskDir, "05_evidence_ledger.json");
  const validCoveragePath = join(valid.taskDir, "checkpoints", "coverage.json");
  const validLedger = JSON.parse(readFileSync(validLedgerPath, "utf8"));
  const validEntry = validLedger.copyright_provenance_verifications[0];
  const validEventPath = join(valid.taskDir, validEntry.event_path);
  const validEventInputPath = join(valid.taskDir, "copyright-verification-input.json");
  writeFileSync(validEventInputPath, readFileSync(validEventPath));
  validLedger.copyright_provenance_verifications = [];
  validLedger.digest = finalizeImmutableArtifact(validLedger).digest;
  writeFileSync(validLedgerPath, JSON.stringify(validLedger));
  const validCoverage = JSON.parse(readFileSync(validCoveragePath, "utf8"));
  validCoverage.evidence_digest = validLedger.digest;
  validCoverage.digest = finalizeImmutableArtifact(validCoverage).digest;
  writeFileSync(validCoveragePath, JSON.stringify(validCoverage));
  unlinkSync(validEventPath);
  writeTestSourceManifest(valid.taskDir);
  assert.equal(
    run(["record-verification", "--kind", "copyright", "--task-dir", valid.taskDir, "--input", validEventInputPath]).reason_code,
    "VERIFICATION_RECORDED",
  );
  assert.equal(run(["finalize-assessment", "--task-dir", valid.taskDir, "--input", valid.inputPath]).legal_risk, "high");
  run(["render-report", "--task-dir", valid.taskDir]);
  assert.equal(run(["validate-release", "--task-dir", valid.taskDir]).reason_code, "V2_RELEASE_VALIDATED");

  const mismatched = prepare("creator_mismatch");
  const ledgerPath = join(mismatched.taskDir, "05_evidence_ledger.json");
  const ledger = JSON.parse(readFileSync(ledgerPath, "utf8"));
  const entry = ledger.copyright_provenance_verifications[0];
  const eventPath = join(mismatched.taskDir, entry.event_path);
  const event = JSON.parse(readFileSync(eventPath, "utf8"));
  delete event.digest;
  event.creator = "different creator";
  const rebound = finalizeImmutableArtifact(event);
  const content = JSON.stringify(rebound);
  writeFileSync(eventPath, content);
  entry.event_sha256 = rawDigest(content);
  writeFileSync(ledgerPath, JSON.stringify(ledger));
  writeTestSourceManifest(mismatched.taskDir);
  assert.equal(run(["finalize-assessment", "--task-dir", mismatched.taskDir, "--input", mismatched.inputPath], { expectStatus: 2 }).reason_code, "HIGH_VERIFICATION_REFERENCE_INVALID");

  const ownerMismatched = prepare("owner_mismatch");
  const ownerLedgerPath = join(ownerMismatched.taskDir, "05_evidence_ledger.json");
  const ownerLedger = JSON.parse(readFileSync(ownerLedgerPath, "utf8"));
  const ownerEntry = ownerLedger.copyright_provenance_verifications[0];
  const ownerEventPath = join(ownerMismatched.taskDir, ownerEntry.event_path);
  const ownerEvent = JSON.parse(readFileSync(ownerEventPath, "utf8"));
  delete ownerEvent.digest;
  ownerEvent.rights_owner = "different rights owner";
  const reboundOwner = finalizeImmutableArtifact(ownerEvent);
  const ownerContent = JSON.stringify(reboundOwner);
  writeFileSync(ownerEventPath, ownerContent);
  ownerEntry.event_sha256 = rawDigest(ownerContent);
  writeFileSync(ownerLedgerPath, JSON.stringify(ownerLedger));
  writeTestSourceManifest(ownerMismatched.taskDir);
  assert.equal(
    run(["finalize-assessment", "--task-dir", ownerMismatched.taskDir, "--input", ownerMismatched.inputPath], { expectStatus: 2 }).reason_code,
    "HIGH_VERIFICATION_REFERENCE_INVALID",
  );
});

test("legacy material migrates to unresolved and cannot become a risk driver", () => {
  const taskDir = mkdtempSync(join(tmpdir(), "lc-ipr-v2-migration-"));
  mkdirSync(join(taskDir, "report-draft"), { recursive: true });
  writeFileSync(join(taskDir, "report-draft", "ipr-risk-screening-report.html"), "<html><body>legacy high</body></html>");
  writeFileSync(join(taskDir, "05_evidence_ledger.json"), JSON.stringify({
    schema_version: "0.1",
    task_id: "fixture_legacy_migration",
    digest: "a".repeat(64),
    candidates: [{
      candidate_id: "legacy-material-1",
      candidate_key: "US:design_right:record:D000001",
      module: "appearance_design",
      jurisdiction: "US",
      right_type: "design_right",
      record_number: "D000001",
      title: "Legacy result",
      evidence_refs: ["evidence://legacy/1"],
      disposition: { value: "material", deterministic_triggers: ["visual_similarity"], exclusion_codes: [] },
    }],
  }));
  const migrated = run(["migrate-candidates", "--task-dir", taskDir]);
  assert.equal(migrated.unresolved_total, 1);
  const workspace = JSON.parse(readFileSync(join(taskDir, "v2", "candidate-review-workspace.json"), "utf8"));
  const candidate = workspace.candidate_review_template.decisions[0].candidate;
  assert.equal(candidate.legal_materiality, "unresolved");
  assert.equal(candidate.risk_driver_eligible, false);
  assert.equal(candidate.legacy_reassessed, false);
  const legacyMetadata = JSON.parse(readFileSync(migrated.legacy_report_metadata_path, "utf8"));
  assert.equal(legacyMetadata.report_mode, "legacy");
  assert.equal(legacyMetadata.legal_risk, "not_assessable");
  assert.equal(legacyMetadata.formal_conclusion_allowed, false);
  const legacyWrapper = readFileSync(migrated.legacy_report_wrapper_path, "utf8");
  assert.match(legacyWrapper, /legacy discovery report/);
  assert.match(legacyWrapper, /评估尚未完成/);
  assert.match(legacyWrapper, /旧报告中的高低风险字样.*不是 v2 法律风险结论/);
  assert.doesNotMatch(legacyWrapper, /risk-(?:high|critical|medium|low|very_low)/);

  const reclassified = structuredClone(candidate);
  reclassified.legal_materiality = "risk_bearing";
  reclassified.evidence_role = "risk_driver";
  reclassified.authority_tier = "official";
  reclassified.risk_driver_eligible = true;
  reclassified.right_jurisdiction = "US";
  reclassified.factors = {
    right_status: "active",
    official_record_verified: true,
    same_product_category: true,
    complete_official_images: true,
    claimed_portions: ["whole article"],
    dominant_shared_features: ["same overall silhouette"],
    dominant_differences: [],
    difference_effect: "none",
    overall_visual_impression: "high",
    authorization_status: "unlicensed",
  };
  delete reclassified.legacy_disposition;
  delete reclassified.legacy_reassessed;
  const reviewPath = join(taskDir, "v2", "candidate-review.json");
  writeFileSync(reviewPath, JSON.stringify({ items: [reclassified] }));
  assert.equal(
    run(["validate-candidates", "--input", reviewPath], { expectStatus: 2 }).reason_code,
    "LEGACY_REASSESSMENT_REQUIRED",
  );
  reclassified.legacy_disposition = "material";
  reclassified.legacy_reassessed = true;
  writeFileSync(reviewPath, JSON.stringify({ items: [reclassified] }));
  assert.equal(run(["validate-candidates", "--input", reviewPath]).reason_code, "V2_CANDIDATES_VALID");
});

test("candidate migration seals the complete frozen source graph", () => {
  const taskDir = mkdtempSync(join(tmpdir(), "lc-ipr-v2-migration-seal-"));
  mkdirSync(join(taskDir, "v2"), { recursive: true });
  const input = readFixture("active-design-strong-overlap");
  input.task_id = "ipr_fixture_migration_seal";
  writeFrozenEvidence(taskDir, input);
  unlinkSync(join(taskDir, "v2", "source-manifest.json"));
  const migrated = run(["migrate-candidates", "--task-dir", taskDir]);
  assert.equal(migrated.source_manifest_path, join(taskDir, "v2", "source-manifest.json"));
  const sourceManifest = JSON.parse(readFileSync(migrated.source_manifest_path, "utf8"));
  assert.equal(sourceManifest.task_id, input.task_id);
  assert.ok(sourceManifest.artifacts.some((artifact) => artifact.path === "02_product_facts.json"));
  assert.ok(sourceManifest.artifacts.some((artifact) => artifact.path === "raw/copyright-provenance/product-provenance.json"));
  assert.equal(sourceManifest.digest, stableDigest(Object.fromEntries(Object.entries(sourceManifest).filter(([key]) => key !== "digest"))));
});

test("critical requires a separate substantiated high-risk right", () => {
  const fixture = JSON.parse(readFileSync(join(fixtureDir, "verified-tro-target-match.input.json"), "utf8"));
  fixture.task_id = "fixture_tro_without_high_base";
  fixture.candidates = fixture.candidates.filter((candidate) => candidate.module === "enforcement_public_signals");
  const appearance = fixture.modules.find((module) => module.module === "appearance_design");
  appearance.candidate_ids = [];
  appearance.reasoning = "未发现具有结构化高风险事实支持的实体权利候选。";
  const path = join(mkdtempSync(join(tmpdir(), "lc-ipr-v2-critical-gate-")), "input.json");
  writeFileSync(path, JSON.stringify(fixture));
  const result = run(["rules", "evaluate", "--input", path, "--dry-run"]);
  assert.equal(result.modules.find((module) => module.module === "enforcement_public_signals").legal_risk, "medium");
  assert.equal(result.overall.legal_risk, "medium");
  assert.equal(result.overall.operational_action, "escalate_legal");
  assert.ok(result.decision_trace.reason_codes.includes("CRITICAL_HIGH_BASE_NOT_MET"));
});

test("a formal critical release binds the active case to the same independently high-risk product", () => {
  const taskDir = mkdtempSync(join(tmpdir(), "lc-ipr-v2-formal-critical-"));
  mkdirSync(join(taskDir, "v2"), { recursive: true });
  const input = readFixture("active-design-strong-overlap");
  input.task_id = "ipr_fixture_formal_critical";
  const design = input.candidates[0];
  design.independence_group = "IG-formal-critical-product";
  const enforcement = {
    candidate_id: "C-enforcement-active-tro",
    module: "enforcement_public_signals",
    record_kind: "enforcement_event",
    legal_materiality: "risk_bearing",
    evidence_role: "risk_driver",
    authority_tier: "official",
    target_jurisdiction: "US",
    source_jurisdiction: "US",
    right_jurisdiction: "US",
    record_number: "TRO-001",
    title: "Active TRO targeting fixture product",
    owner: "Verified Rights Owner LLC",
    source_locator: "court://fixture/TRO-001",
    published_at: "2026-09-02T00:00:00Z",
    first_seen_at: "2026-09-02T00:00:00Z",
    evidence_cluster_id: "CL-formal-critical-event",
    independence_group: "IG-formal-critical-product",
    duplicate_of: null,
    risk_driver_eligible: true,
    evidence_refs: ["E-enforcement-active-tro"],
    verification_refs: ["V-enforcement-active-tro"],
    factors: {
      event_verified: true,
      claimant: "Verified Rights Owner LLC",
      case_or_complaint_id: "TRO-001",
      subject_match: "exact",
      procedure_status: "active_tro",
      underlying_risk_driver_ids: [design.candidate_id],
    },
  };
  input.candidates.push(enforcement);
  input.modules.find((module) => module.module === "enforcement_public_signals").candidate_ids = [enforcement.candidate_id];
  const inputPath = join(taskDir, "assessment-input.json");
  writeFileSync(inputPath, JSON.stringify(input));
  writeFrozenEvidence(taskDir, input);
  const finalized = run(["finalize-assessment", "--task-dir", taskDir, "--input", inputPath]);
  assert.equal(finalized.legal_risk, "critical");
  run(["render-report", "--task-dir", taskDir]);
  assert.equal(run(["validate-release", "--task-dir", taskDir]).reason_code, "V2_RELEASE_VALIDATED");

  const wrongIdentity = JSON.parse(JSON.stringify(input));
  wrongIdentity.candidates.find((candidate) => candidate.module === "enforcement_public_signals").factors.case_or_complaint_id = "TRO-OTHER";
  const wrongPath = join(taskDir, "assessment-input-wrong-case.json");
  writeFileSync(wrongPath, JSON.stringify(wrongIdentity));
  assert.equal(
    run(["finalize-assessment", "--task-dir", taskDir, "--input", wrongPath], { expectStatus: 2 }).reason_code,
    "MODULE_FACTOR_INVALID",
  );

  const ledgerPath = join(taskDir, "05_evidence_ledger.json");
  const ledger = JSON.parse(readFileSync(ledgerPath, "utf8"));
  const enforcementEntry = ledger.official_verifications.find((entry) => entry.candidate_id === enforcement.candidate_id);
  const enforcementEventPath = join(taskDir, enforcementEntry.event_path);
  const enforcementEvent = JSON.parse(readFileSync(enforcementEventPath, "utf8"));
  delete enforcementEvent.digest;
  enforcementEvent.enforcement_identity.target_product_digest = "f".repeat(64);
  const reboundEvent = finalizeImmutableArtifact(enforcementEvent);
  const reboundContent = JSON.stringify(reboundEvent);
  writeFileSync(enforcementEventPath, reboundContent);
  enforcementEntry.event_sha256 = rawDigest(reboundContent);
  writeFileSync(ledgerPath, JSON.stringify(ledger));
  writeTestSourceManifest(taskDir);
  assert.equal(
    run(["finalize-assessment", "--task-dir", taskDir, "--input", inputPath], { expectStatus: 2 }).reason_code,
    "HIGH_VERIFICATION_REFERENCE_INVALID",
  );
});

test("an incomplete final input is rendered without any module risk seal", () => {
  const taskDir = mkdtempSync(join(tmpdir(), "lc-ipr-v2-incomplete-"));
  mkdirSync(join(taskDir, "v2"), { recursive: true });
  writeFileSync(join(taskDir, "02_product_facts.json"), JSON.stringify({ product: { title: "Incomplete fixture", marketplace: "US" } }));
  const input = join(fixtureDir, "evidence-gap-does-not-raise-risk.input.json");
  run(["finalize-assessment", "--task-dir", taskDir, "--input", input]);
  run(["render-report", "--task-dir", taskDir]);
  const report = JSON.parse(readFileSync(join(taskDir, "report-v2", "report_data.json"), "utf8"));
  const html = readFileSync(join(taskDir, "report-v2", "ipr-risk-screening-report.html"), "utf8");
  assert.equal(report.report_mode, "draft");
  assert.ok(report.modules.every((module) => module.legal_risk === "not_assessable"));
  assert.doesNotMatch(html, /class="risk risk-(?:high|critical|medium|low|very_low)"/);
});

test("risk-bearing candidates require complete module factors and module references", () => {
  const missingFactor = readFixture("active-design-strong-overlap");
  delete missingFactor.candidates[0].factors.claimed_portions;
  assert.equal(evaluateObject(missingFactor, { expectStatus: 2 }).reason_code, "MODULE_FACTORS_INCOMPLETE");

  const missingReference = readFixture("active-design-strong-overlap");
  missingReference.modules.find((module) => module.module === "appearance_design").candidate_ids = [];
  assert.equal(evaluateObject(missingReference, { expectStatus: 2 }).reason_code, "CANDIDATE_MODULE_COVERAGE_MISMATCH");

  const wrongJurisdiction = readFixture("active-design-strong-overlap");
  wrongJurisdiction.candidates[0].right_jurisdiction = "CN";
  assert.equal(evaluateObject(wrongJurisdiction, { expectStatus: 2 }).reason_code, "RISK_DRIVER_JURISDICTION_MISMATCH");

  const invalidEnum = readFixture("active-design-strong-overlap");
  invalidEnum.candidates[0].factors.overall_visual_impression = "hgh";
  assert.equal(evaluateObject(invalidEnum, { expectStatus: 2 }).reason_code, "MODULE_FACTOR_INVALID");

  const blankEvidence = readFixture("active-design-strong-overlap");
  blankEvidence.candidates[0].evidence_refs = [""];
  assert.equal(evaluateObject(blankEvidence, { expectStatus: 2 }).reason_code, "CANDIDATE_EVIDENCE_REFS_INVALID");

  const wrongRecordKind = readFixture("active-design-strong-overlap");
  wrongRecordKind.candidates[0].record_kind = "application";
  assert.equal(evaluateObject(wrongRecordKind, { expectStatus: 2 }).reason_code, "RISK_DRIVER_RECORD_KIND_MISMATCH");

  const disguisedWrongRecordKind = readFixture("active-design-strong-overlap");
  disguisedWrongRecordKind.candidates[0].record_kind = "application";
  disguisedWrongRecordKind.candidates[0].legal_materiality = "not_material";
  disguisedWrongRecordKind.candidates[0].risk_driver_eligible = false;
  disguisedWrongRecordKind.candidates[0].evidence_role = "context";
  assert.equal(evaluateObject(disguisedWrongRecordKind, { expectStatus: 2 }).reason_code, "LEGAL_RECORD_KIND_MISMATCH");

  const decisiveDifference = readFixture("active-design-strong-overlap");
  decisiveDifference.candidates[0].factors.dominant_differences = ["被主张的核心轮廓完全缺失"];
  decisiveDifference.candidates[0].factors.difference_effect = "decisive";
  const decisiveResult = evaluateObject(decisiveDifference);
  assert.equal(decisiveResult.modules.find((module) => module.module === "appearance_design").legal_risk, "low");
  assert.ok(decisiveResult.decision_trace.reason_codes.includes("DECISIVE_DESIGN_DIFFERENCES"));

  const disguisedDriver = readFixture("active-design-strong-overlap");
  disguisedDriver.candidates[0].legal_materiality = "comparison_only";
  disguisedDriver.candidates[0].risk_driver_eligible = false;
  disguisedDriver.candidates[0].evidence_role = "context";
  assert.equal(evaluateObject(disguisedDriver, { expectStatus: 2 }).reason_code, "COMPARISON_CLASSIFICATION_UNSUPPORTED");
  disguisedDriver.candidates[0].legal_materiality = "not_material";
  assert.equal(evaluateObject(disguisedDriver, { expectStatus: 2 }).reason_code, "COMPARISON_CLASSIFICATION_UNSUPPORTED");

  const verifiedExclusion = readFixture("active-design-strong-overlap");
  verifiedExclusion.candidates[0].legal_materiality = "not_material";
  verifiedExclusion.candidates[0].risk_driver_eligible = false;
  verifiedExclusion.candidates[0].evidence_role = "context";
  verifiedExclusion.candidates[0].authority_tier = "unknown";
  verifiedExclusion.candidates[0].verification_refs = [];
  verifiedExclusion.candidates[0].factors.right_status = "expired";
  verifiedExclusion.candidates[0].factors.official_record_verified = false;
  assert.equal(
    evaluateObject(verifiedExclusion, { expectStatus: 2 }).reason_code,
    "COMPARISON_CLASSIFICATION_UNSUPPORTED",
  );

  verifiedExclusion.candidates[0].authority_tier = "official";
  verifiedExclusion.candidates[0].verification_refs = ["V-expired-design"];
  verifiedExclusion.candidates[0].factors.official_record_verified = true;
  const exclusionResult = evaluateObject(verifiedExclusion);
  assert.equal(exclusionResult.modules.find((module) => module.module === "appearance_design").legal_risk, "low");
  assert.equal(exclusionResult.modules.find((module) => module.module === "appearance_design").risk_confidence, "high");
  assert.equal(exclusionResult.overall.legal_risk, "low");
  assert.equal(exclusionResult.overall.discovery_status, "leads_found");
  assert.equal(exclusionResult.overall.operational_action, "proceed_with_conditions");
});

test("non-blocking evidence gaps cap confidence without raising legal risk", () => {
  const input = readFixture("active-design-strong-overlap");
  input.coverage.gaps = [{ code: "OPTIONAL_SOURCE_GAP", module: "appearance_design", detail: "辅助来源未返回。", blocking: false }];
  const result = evaluateObject(input);
  assert.equal(result.overall.legal_risk, "high");
  assert.equal(result.overall.risk_confidence, "medium");
  assert.equal(result.overall.coverage_confidence, "medium");
  assert.ok(result.modules.find((module) => module.module === "appearance_design").basis_codes.includes("CONFIDENCE_CAPPED"));

  const malformed = readFixture("active-design-strong-overlap");
  malformed.coverage.gaps = [{ code: "IMAGE_COVERAGE_LIMITED", module: "appearance_design", detail: "缺图" }];
  assert.equal(evaluateObject(malformed, { expectStatus: 2 }).reason_code, "COVERAGE_GAP_INVALID");
});

test("unknown facts block a legal conclusion while inactive rights remain low", () => {
  const unknown = readFixture("active-design-strong-overlap");
  unknown.candidates[0].factors.right_status = "unknown";
  unknown.candidates[0].factors.official_record_verified = false;
  unknown.candidates[0].factors.complete_official_images = false;
  unknown.candidates[0].factors.overall_visual_impression = "unknown";
  unknown.candidates[0].factors.authorization_status = "unknown";
  const unknownResult = evaluateObject(unknown);
  assert.equal(unknownResult.modules.find((module) => module.module === "appearance_design").legal_risk, "not_assessable");
  assert.equal(unknownResult.overall.legal_risk, "not_assessable");
  assert.equal(unknownResult.overall.operational_action, "hold_for_evidence");

  const expired = readFixture("active-design-strong-overlap");
  expired.candidates[0].factors.right_status = "expired";
  const expiredResult = evaluateObject(expired);
  assert.equal(expiredResult.modules.find((module) => module.module === "appearance_design").legal_risk, "low");
});

test("partially assessable modules never produce a proceed action", () => {
  const input = readFixture("active-design-strong-overlap");
  input.candidates[0].factors.overall_visual_impression = "different";
  const module = input.modules.find((item) => item.module === "appearance_design");
  module.assessability = "partially_assessable";
  module.confidence = "low";
  const result = evaluateObject(input);
  assert.equal(result.overall.legal_risk, "low");
  assert.equal(result.overall.operational_action, "hold_for_evidence");
});

test("coverage confidence and risk confidence use their own evidence scopes", () => {
  const draft = readFixture("draft-assessment-not-finalized");
  draft.coverage.confidence = "high";
  draft.coverage.complete = false;
  draft.coverage.gaps = [{ code: "BLOCKING_IMAGE_GAP", module: "appearance_design", detail: "关键图组缺失", blocking: true }];
  assert.equal(evaluateObject(draft).overall.coverage_confidence, "low");

  const lowDriver = readFixture("visual-search-90-overall-different");
  lowDriver.modules.find((module) => module.module === "word_mark").confidence = "low";
  const lowDriverResult = evaluateObject(lowDriver);
  assert.equal(lowDriverResult.overall.legal_risk, "low");
  assert.equal(lowDriverResult.modules.find((module) => module.module === "appearance_design").risk_confidence, "high");
  assert.equal(lowDriverResult.overall.risk_confidence, "high");

  const weakComparison = readFixture("visual-search-90-overall-different");
  weakComparison.candidates[0].legal_materiality = "comparison_only";
  weakComparison.candidates[0].risk_driver_eligible = false;
  weakComparison.candidates[0].evidence_role = "context";
  weakComparison.candidates[0].authority_tier = "commercial";
  weakComparison.candidates[0].verification_refs = [];
  const weakComparisonResult = evaluateObject(weakComparison);
  assert.equal(weakComparisonResult.modules.find((module) => module.module === "appearance_design").risk_confidence, "low");
});

test("unresolved material facts and draft conflicts cannot be hidden by module labels", () => {
  const unresolvedFact = readFixture("visual-search-90-overall-different");
  const module = unresolvedFact.modules.find((item) => item.module === "appearance_design");
  module.unresolved_material_facts = ["完整官方图组的主张部分尚未确认"];
  const unresolvedResult = evaluateObject(unresolvedFact);
  assert.equal(unresolvedResult.modules.find((item) => item.module === "appearance_design").legal_risk, "not_assessable");
  assert.equal(unresolvedResult.overall.legal_risk, "not_assessable");
  assert.equal(unresolvedResult.overall.operational_action, "hold_for_evidence");

  const malformedFact = readFixture("visual-search-90-overall-different");
  malformedFact.modules.find((item) => item.module === "appearance_design").unresolved_material_facts = "未决事实";
  assert.equal(evaluateObject(malformedFact, { expectStatus: 2 }).reason_code, "MODULE_INPUT_INVALID");

  const draftConflict = readFixture("second-review-fact-conflict");
  draftConflict.assessment_status = "draft";
  const draftResult = evaluateObject(draftConflict);
  assert.equal(draftResult.constraints.human_resolution_required, true);
  assert.equal(draftResult.overall.discovery_status, "blocked");
  assert.equal(draftResult.overall.legal_risk, "not_assessable");
  assert.equal(draftResult.overall.operational_action, "escalate_legal");
  assert.ok(traceCodes(draftResult).has("HUMAN_RESOLUTION_REQUIRED"));
});

test("resolved conflicts require evidence and must match the resolved candidate fact", () => {
  const falseMaterial = readFixture("second-review-fact-conflict");
  falseMaterial.review.fact_conflicts[0].rating_material = false;
  assert.equal(evaluateObject(falseMaterial, { expectStatus: 2 }).reason_code, "CONFLICT_INPUT_INVALID");

  const missingEvidence = readFixture("second-review-fact-conflict");
  const conflict = missingEvidence.review.fact_conflicts[0];
  conflict.status = "resolved_by_human";
  conflict.resolution_value = "high";
  assert.equal(evaluateObject(missingEvidence, { expectStatus: 2 }).reason_code, "CONFLICT_RESOLUTION_EVIDENCE_REQUIRED");

  const wrongValue = readFixture("second-review-fact-conflict");
  const wrongConflict = wrongValue.review.fact_conflicts[0];
  wrongConflict.status = "resolved_by_evidence";
  wrongConflict.resolution_value = "low";
  wrongConflict.resolution_evidence_refs = ["evidence://resolution/visual-comparison"];
  assert.equal(evaluateObject(wrongValue, { expectStatus: 2 }).reason_code, "CONFLICT_RESOLUTION_VALUE_MISMATCH");

  const missingArtifact = readFixture("second-review-fact-conflict");
  const artifactConflict = missingArtifact.review.fact_conflicts[0];
  artifactConflict.status = "resolved_by_human";
  artifactConflict.resolution_value = "unknown";
  artifactConflict.resolution_evidence_refs = ["evidence://resolution/visual-comparison"];
  assert.equal(evaluateObject(missingArtifact, { expectStatus: 2 }).reason_code, "CONFLICT_RESOLUTION_ARTIFACT_REQUIRED");
});

test("authorized weak marks cannot become high risk", () => {
  const input = readFixture("exact-mark-unrelated-goods");
  const candidate = input.candidates[0];
  candidate.legal_materiality = "risk_bearing";
  candidate.risk_driver_eligible = true;
  candidate.evidence_role = "risk_driver";
  candidate.target_jurisdiction = "US";
  candidate.right_jurisdiction = "US";
  candidate.factors.goods_services_relatedness = "high";
  candidate.factors.channels_overlap = true;
  candidate.factors.consumer_overlap = true;
  candidate.factors.mark_strength = "weak";
  candidate.factors.confusion_likelihood = "high";
  candidate.factors.authorization_status = "authorized";
  const result = evaluateObject(input);
  assert.equal(result.modules.find((module) => module.module === "word_mark").legal_risk, "low");

  const notApplicable = readFixture("active-design-strong-overlap");
  notApplicable.candidates[0].factors.authorization_status = "not_applicable";
  const notApplicableResult = evaluateObject(notApplicable);
  assert.equal(notApplicableResult.modules.find((module) => module.module === "appearance_design").legal_risk, "medium");
});

test("near-exact word and figurative marks run the full confusion test", () => {
  for (const module of ["word_mark", "figurative_mark"]) {
    const input = readFixture("exact-mark-unrelated-goods");
    const candidate = input.candidates[0];
    if (module === "figurative_mark") {
      moveOnlyCandidateToModule(input, module);
      candidate.module = module;
      candidate.factors.figurative_similarity = "near_exact";
      delete candidate.factors.mark_similarity;
    } else candidate.factors.mark_similarity = "near_exact";
    candidate.factors.goods_services_relatedness = "high";
    candidate.factors.channels_overlap = true;
    candidate.factors.consumer_overlap = true;
    candidate.factors.mark_strength = "strong";
    candidate.factors.confusion_likelihood = "high";
    candidate.factors.authorization_status = "unlicensed";
    assert.equal(evaluateObject(input).modules.find((item) => item.module === module).legal_risk, "high");
  }
});

test("trade dress high requires the complete protectability and confusion test", () => {
  const input = readFixture("active-design-strong-overlap");
  input.task_id = "fixture_trade_dress_complete";
  const candidate = moveOnlyCandidateToModule(input, "trade_dress");
  candidate.candidate_id = "trade_dress_complete_driver";
  input.modules.find((module) => module.module === "trade_dress").candidate_ids = [candidate.candidate_id];
  candidate.factors = {
    identified_trade_dress_claim: "波浪盆沿、人物裙摆与悬挂结构的特定组合",
    nonfunctionality: "established",
    distinctiveness: "established",
    source_identification: "supported",
    confusion_likelihood: "high",
    authorization_status: "unlicensed",
  };
  const result = evaluateObject(input);
  assert.equal(result.modules.find((module) => module.module === "trade_dress").legal_risk, "high");
});

test("utility patent high requires actual element-by-element coverage", () => {
  const input = readFixture("active-design-strong-overlap");
  input.task_id = "fixture_utility_claim_mapping";
  const candidate = moveOnlyCandidateToModule(input, "utility_patent");
  candidate.candidate_id = "utility_claim_mapping_driver";
  input.modules.find((module) => module.module === "utility_patent").candidate_ids = [candidate.candidate_id];
  candidate.factors = {
    right_status: "active",
    official_record_verified: true,
    independent_claim_mappings: [{
      claim_id: "1",
      required_elements: ["A", "B"],
      mapped_elements: ["A", "B"],
      missing_elements: [],
      mapping_status: "complete",
    }],
    claim_scope_conclusion: "all_elements_mapped",
    authorization_status: "unlicensed",
  };
  assert.equal(evaluateObject(input).modules.find((module) => module.module === "utility_patent").legal_risk, "high");
  candidate.factors.independent_claim_mappings[0].mapped_elements = ["A"];
  candidate.factors.independent_claim_mappings[0].missing_elements = ["B"];
  candidate.factors.independent_claim_mappings[0].mapping_status = "partial";
  candidate.factors.claim_scope_conclusion = "uncertain";
  assert.equal(evaluateObject(input).modules.find((module) => module.module === "utility_patent").legal_risk, "medium");

  const contradictoryComplete = JSON.parse(JSON.stringify(input));
  contradictoryComplete.candidates[0].factors.independent_claim_mappings[0] = {
    claim_id: "1", required_elements: ["A", "B"], mapped_elements: ["A", "B"], missing_elements: [], mapping_status: "complete",
  };
  contradictoryComplete.candidates[0].factors.claim_scope_conclusion = "missing_elements";
  assert.equal(evaluateObject(contradictoryComplete, { expectStatus: 2 }).reason_code, "MODULE_FACTOR_INVALID");

  const contradictoryMissing = JSON.parse(JSON.stringify(input));
  contradictoryMissing.candidates[0].factors.claim_scope_conclusion = "all_elements_mapped";
  assert.equal(evaluateObject(contradictoryMissing, { expectStatus: 2 }).reason_code, "MODULE_FACTOR_INVALID");
});

test("a fully reviewed pending claim overlap can proceed with monitoring conditions", () => {
  const input = readFixture("active-design-strong-overlap");
  input.task_id = "fixture_pending_claim_conditions";
  const candidate = moveOnlyCandidateToModule(input, "pending_patent");
  candidate.candidate_id = "pending_claim_overlap_driver";
  candidate.record_kind = "application";
  input.modules.find((module) => module.module === "pending_patent").candidate_ids = [candidate.candidate_id];
  candidate.factors = {
    right_status: "pending",
    official_record_verified: true,
    independent_claim_mappings: [{
      claim_id: "1",
      required_elements: ["A", "B"],
      mapped_elements: ["A", "B"],
      missing_elements: [],
      mapping_status: "complete",
    }],
    claim_scope_conclusion: "all_elements_mapped",
    claim_change_uncertainty: "medium",
    monitoring_trigger: "Monitor publication and allowance events",
    authorization_status: "unlicensed",
  };
  const result = evaluateObject(input);
  assert.equal(result.modules.find((module) => module.module === "pending_patent").legal_risk, "medium");
  assert.equal(result.overall.operational_action, "proceed_with_conditions");

  candidate.factors.claim_change_uncertainty = "unknown";
  candidate.factors.monitoring_trigger = null;
  const unresolvedMonitoring = evaluateObject(input);
  assert.equal(unresolvedMonitoring.modules.find((module) => module.module === "pending_patent").risk_confidence, "low");
  assert.equal(unresolvedMonitoring.overall.operational_action, "hold_for_evidence");
  assert.ok(unresolvedMonitoring.decision_trace.reason_codes.includes("PENDING_CLAIM_MONITORING_UNRESOLVED"));
});

test("duplicate references are acyclic and deduplication is order independent", () => {
  const cycle = readFixture("duplicate-marketplace-pages-100");
  cycle.candidates[0].duplicate_of = cycle.candidates[1].candidate_id;
  cycle.candidates[1].duplicate_of = cycle.candidates[0].candidate_id;
  assert.equal(evaluateObject(cycle, { expectStatus: 2 }).reason_code, "DUPLICATE_REFERENCE_CYCLE");

  const ordered = readFixture("active-design-strong-overlap");
  ordered.task_id = "fixture_cluster_tie_order";
  ordered.candidates[0].factors.overall_visual_impression = "different";
  const weaker = JSON.parse(JSON.stringify(ordered.candidates[0]));
  weaker.candidate_id = "active_design_weaker_source";
  weaker.authority_tier = "commercial";
  weaker.verification_refs = [];
  ordered.candidates.push(weaker);
  ordered.modules.find((module) => module.module === "appearance_design").candidate_ids.push(weaker.candidate_id);
  const forward = evaluateObject(ordered);
  const reversed = JSON.parse(JSON.stringify(ordered));
  reversed.candidates.reverse();
  reversed.modules.find((module) => module.module === "appearance_design").candidate_ids.reverse();
  const backward = evaluateObject(reversed);
  const forwardModule = forward.modules.find((module) => module.module === "appearance_design");
  const backwardModule = backward.modules.find((module) => module.module === "appearance_design");
  assert.deepEqual(forwardModule, backwardModule);
  assert.deepEqual(forward.overall, backward.overall);
  assert.deepEqual(forwardModule.risk_driver_candidate_ids, ["C-active_design_strong_overlap"]);

  const conflicting = readFixture("active-design-strong-overlap");
  conflicting.task_id = "fixture_duplicate_fact_conflict";
  const conflictingAlias = JSON.parse(JSON.stringify(conflicting.candidates[0]));
  conflictingAlias.candidate_id = "active_design_conflicting_alias";
  conflictingAlias.duplicate_of = conflicting.candidates[0].candidate_id;
  conflictingAlias.factors.overall_visual_impression = "low";
  conflicting.candidates.push(conflictingAlias);
  conflicting.modules.find((module) => module.module === "appearance_design").candidate_ids.push(conflictingAlias.candidate_id);
  const conflictResult = evaluateObject(conflicting);
  assert.equal(conflictResult.modules.find((module) => module.module === "appearance_design").legal_risk, "not_assessable");
  assert.equal(conflictResult.overall.legal_risk, "not_assessable");
  assert.equal(conflictResult.constraints.human_resolution_required, true);
  assert.equal(conflictResult.discovery_summary.risk_driver_count, 1);

  const groupMismatch = readFixture("active-design-strong-overlap");
  const unrelatedAlias = JSON.parse(JSON.stringify(groupMismatch.candidates[0]));
  unrelatedAlias.candidate_id = "active_design_group_mismatch";
  unrelatedAlias.independence_group = "different_independence_group";
  groupMismatch.candidates.push(unrelatedAlias);
  groupMismatch.modules.find((module) => module.module === "appearance_design").candidate_ids.push(unrelatedAlias.candidate_id);
  assert.equal(evaluateObject(groupMismatch, { expectStatus: 2 }).reason_code, "EVIDENCE_CLUSTER_INDEPENDENCE_MISMATCH");
});

test("unresolved candidates hold operations and cannot be hidden by a low candidate", () => {
  const unresolved = readFixture("active-design-strong-overlap");
  unresolved.candidates[0].legal_materiality = "unresolved";
  unresolved.candidates[0].risk_driver_eligible = false;
  unresolved.candidates[0].evidence_role = "provenance";
  const unresolvedResult = evaluateObject(unresolved);
  assert.equal(unresolvedResult.overall.legal_risk, "not_assessable");
  assert.equal(unresolvedResult.overall.operational_action, "hold_for_evidence");

  const mixed = readFixture("active-design-strong-overlap");
  mixed.task_id = "fixture_mixed_claim_assessment";
  const candidate = moveOnlyCandidateToModule(mixed, "utility_patent");
  candidate.candidate_id = "utility_claim_not_reviewed";
  candidate.evidence_cluster_id = "claim_not_reviewed";
  candidate.independence_group = "claim_not_reviewed";
  candidate.factors = {
    right_status: "active",
    official_record_verified: true,
    independent_claim_mappings: [{
      claim_id: "1",
      required_elements: ["A"],
      mapped_elements: [],
      missing_elements: [],
      mapping_status: "unknown",
    }],
    claim_scope_conclusion: "not_reviewed",
    authorization_status: "unknown",
  };
  const lowCandidate = JSON.parse(JSON.stringify(candidate));
  lowCandidate.candidate_id = "utility_claim_missing_element";
  lowCandidate.evidence_cluster_id = "claim_missing_element";
  lowCandidate.independence_group = "claim_missing_element";
  lowCandidate.factors.claim_scope_conclusion = "missing_elements";
  mixed.candidates.push(lowCandidate);
  mixed.modules.find((module) => module.module === "utility_patent").candidate_ids = [candidate.candidate_id, lowCandidate.candidate_id];
  const mixedResult = evaluateObject(mixed);
  assert.equal(mixedResult.modules.find((module) => module.module === "utility_patent").legal_risk, "not_assessable");
  assert.equal(mixedResult.overall.legal_risk, "not_assessable");
});

test("critical requires a valid linked underlying high-risk candidate id", () => {
  const input = readFixture("verified-tro-target-match");
  input.candidates.find((candidate) => candidate.module === "enforcement_public_signals").factors.underlying_risk_driver_ids = ["nonexistent_high_driver"];
  const result = evaluateObject(input);
  assert.equal(result.modules.find((module) => module.module === "enforcement_public_signals").legal_risk, "medium");
  assert.equal(result.overall.legal_risk, "high");
  assert.equal(result.overall.operational_action, "escalate_legal");
  assert.ok(result.decision_trace.reason_codes.includes("ENFORCEMENT_UNDERLYING_DRIVER_LINK_INVALID"));

  const duplicateLink = readFixture("verified-tro-target-match");
  const design = duplicateLink.candidates.find((candidate) => candidate.module === "appearance_design");
  const alias = JSON.parse(JSON.stringify(design));
  alias.candidate_id = "underlying_design_duplicate_alias";
  alias.duplicate_of = design.candidate_id;
  alias.authority_tier = "commercial";
  duplicateLink.candidates.push(alias);
  duplicateLink.modules.find((module) => module.module === "appearance_design").candidate_ids.push(alias.candidate_id);
  duplicateLink.candidates.find((candidate) => candidate.module === "enforcement_public_signals").factors.underlying_risk_driver_ids = [alias.candidate_id];
  const duplicateResult = evaluateObject(duplicateLink);
  assert.equal(duplicateResult.modules.find((module) => module.module === "enforcement_public_signals").legal_risk, "critical");
  assert.equal(duplicateResult.overall.legal_risk, "critical");
});

test("release rejects a stale report after assessment changes", () => {
  const taskDir = mkdtempSync(join(tmpdir(), "lc-ipr-v2-stale-release-"));
  mkdirSync(join(taskDir, "v2"), { recursive: true });
  writeFileSync(join(taskDir, "02_product_facts.json"), JSON.stringify({ product: { title: "Stale release fixture", marketplace: "US" } }));
  const original = readFixture("active-design-strong-overlap");
  original.task_id = "ipr_fixture_stale_release";
  writeFrozenEvidence(taskDir, original);
  const originalPath = join(taskDir, "original.json");
  writeFileSync(originalPath, JSON.stringify(original));
  run(["finalize-assessment", "--task-dir", taskDir, "--input", originalPath]);
  run(["render-report", "--task-dir", taskDir]);
  const changed = JSON.parse(JSON.stringify(original));
  changed.candidates[0].factors.overall_visual_impression = "medium";
  const changedPath = join(taskDir, "changed.json");
  writeFileSync(changedPath, JSON.stringify(changed));
  run(["finalize-assessment", "--task-dir", taskDir, "--input", changedPath]);
  assert.equal(run(["validate-release", "--task-dir", taskDir], { expectStatus: 2 }).reason_code, "ASSESSMENT_BINDING_MISMATCH");
});

test("render refuses a hand-edited assessment instead of emitting a formal risk seal", () => {
  const taskDir = mkdtempSync(join(tmpdir(), "lc-ipr-v2-tampered-render-"));
  mkdirSync(join(taskDir, "v2"), { recursive: true });
  const fixture = writeReleaseFixtureInput(taskDir, "tampered_render");
  run(["finalize-assessment", "--task-dir", taskDir, "--input", fixture.inputPath]);
  const assessmentPath = join(taskDir, "v2", "assessment.json");
  const assessment = JSON.parse(readFileSync(assessmentPath, "utf8"));
  delete assessment.digest;
  assessment.overall.legal_risk = "low";
  assessment.overall.working_legal_risk = "low";
  const tampered = { ...assessment, digest: rawDigest(JSON.stringify(assessment)) };
  writeFileSync(assessmentPath, JSON.stringify(tampered));
  assert.equal(
    run(["render-report", "--task-dir", taskDir], { expectStatus: 2 }).reason_code,
    "ASSESSMENT_RECALCULATION_MISMATCH",
  );
  assert.equal(existsSync(join(taskDir, "report-v2", "ipr-risk-screening-report.html")), false);
});

test("release rejects coverage or source artifacts changed after finalization", () => {
  const taskDir = mkdtempSync(join(tmpdir(), "lc-ipr-v2-bound-release-"));
  mkdirSync(join(taskDir, "v2"), { recursive: true });
  const productPath = join(taskDir, "02_product_facts.json");
  writeFileSync(productPath, JSON.stringify({ product: { title: "Bound release fixture", marketplace: "US" } }));
  const releaseFixture = writeReleaseFixtureInput(taskDir, "bound_release");
  run(["finalize-assessment", "--task-dir", taskDir, "--input", releaseFixture.inputPath]);
  run(["render-report", "--task-dir", taskDir]);
  const coveragePath = join(taskDir, "v2", "coverage.json");
  const coverage = JSON.parse(readFileSync(coveragePath, "utf8"));
  coverage.gaps = [{ code: "LATE_GAP", module: "appearance_design", detail: "Late gap", blocking: true }];
  writeFileSync(coveragePath, JSON.stringify(coverage));
  assert.equal(run(["validate-release", "--task-dir", taskDir], { expectStatus: 2 }).reason_code, "COVERAGE_BINDING_MISMATCH");

  run(["finalize-assessment", "--task-dir", taskDir, "--input", releaseFixture.inputPath]);
  run(["render-report", "--task-dir", taskDir]);
  writeFileSync(productPath, JSON.stringify({ product: { title: "Changed product", marketplace: "US" } }));
  assert.equal(run(["validate-release", "--task-dir", taskDir], { expectStatus: 2 }).reason_code, "FORMAL_PRODUCT_FACTS_INVALID");
});

test("second review merges facts and recalculates instead of merging labels", () => {
  const directory = mkdtempSync(join(tmpdir(), "lc-ipr-v2-review-merge-"));
  const input = readFixture("active-design-strong-overlap");
  input.task_id = "ipr_fixture_review_fact_merge";
  const inputPath = join(directory, "assessment-input.json");
  writeFileSync(inputPath, JSON.stringify(input));
  writeFrozenEvidence(directory, input);
  const makeReview = (round, reviewerId, sessionId, value, { includeObservation = true, base = input } = {}) => finalizeImmutableArtifact({
    schema_version: "2.0",
    ruleset_version: "2.0",
    review_id: `REV-${(round === "first" ? "1" : "2").repeat(24)}`,
    task_id: base.task_id,
    round,
    reviewer: { type: "reviewer", id: reviewerId, session_id: sessionId },
    context_digest: stableDigest(base),
    evidence_digest: stableDigest(base.candidates),
    declared_input_refs: ["evidence://review/context"],
    isolation: { mode: "declared_only", prior_review_read: false, proof_id: null },
    modules: base.modules.map((module) => ({
      module: module.module,
      assessability: module.assessability,
      confidence: module.confidence,
      candidate_ids: module.candidate_ids,
      fact_observations: module.module === "appearance_design" && includeObservation
        ? Object.entries(base.candidates[0].factors).map(([factorName, factorValue]) => ({
          candidate_id: base.candidates[0].candidate_id,
          fact_path: `factors.${factorName}`,
          value: factorName === "overall_visual_impression" ? value : factorValue,
          status: "verified",
          evidence_refs: [...base.candidates[0].evidence_refs],
          verification_refs: [...base.candidates[0].verification_refs],
        }))
        : [],
      reasoning: "结构化事实复核完成。",
      recommended_actions: [],
    })),
    fact_conflicts: [],
    submitted_at: "2026-09-02T00:00:00Z",
  });
  const firstPath = join(directory, "first.json");
  const secondPath = join(directory, "second.json");
  const outputPath = join(directory, "merged.json");
  writeFileSync(firstPath, JSON.stringify(makeReview("first", "reviewer-a", "session-a", "low")));
  writeFileSync(secondPath, JSON.stringify(makeReview("second", "reviewer-b", "session-b", "low")));
  const mergedResult = run(["merge-reviews", "--assessment-input", inputPath, "--first-review", firstPath, "--second-review", secondPath, "--output", outputPath]);
  assert.equal(mergedResult.unresolved_conflict_total, 0);
  assert.equal(mergedResult.legal_risk, "low");
  const merged = JSON.parse(readFileSync(outputPath, "utf8"));
  assert.equal(merged.candidates[0].factors.overall_visual_impression, "low");
  const tamperedMergedPath = join(directory, "merged-tampered.json");
  const tamperedMerged = JSON.parse(JSON.stringify(merged));
  tamperedMerged.candidates[0].factors.overall_visual_impression = "high";
  writeFileSync(tamperedMergedPath, JSON.stringify(tamperedMerged));
  assert.equal(
    run(["finalize-assessment", "--task-dir", directory, "--input", tamperedMergedPath], { expectStatus: 2 }).reason_code,
    "REVIEW_MERGE_BINDING_MISMATCH",
  );

  writeFileSync(secondPath, JSON.stringify(makeReview("second", "reviewer-b", "session-b", "high")));
  const conflicted = run(["merge-reviews", "--assessment-input", inputPath, "--first-review", firstPath, "--second-review", secondPath, "--output", outputPath]);
  assert.equal(conflicted.unresolved_conflict_total, 1);
  assert.equal(conflicted.legal_risk, "not_assessable");
  assert.equal(conflicted.operational_action, "escalate_legal");

  const conflictId = JSON.parse(readFileSync(outputPath, "utf8")).review.fact_conflicts[0].conflict_id;
  const resolutionPath = join(directory, "resolution.json");
  const resolution = finalizeImmutableArtifact({
    schema_version: "2.0",
    ruleset_version: "2.0",
    resolution_id: `RES-${"3".repeat(24)}`,
    task_id: input.task_id,
    context_digest: stableDigest(input),
    evidence_digest: stableDigest(input.candidates),
    resolver: { type: "human", id: "resolver-a", session_id: "resolver-session-a" },
    resolved_facts: [{
      conflict_id: conflictId,
      module: "appearance_design",
      candidate_id: input.candidates[0].candidate_id,
      fact_path: "factors.overall_visual_impression",
      resolved_value: "low",
      evidence_refs: [...input.candidates[0].evidence_refs],
    }],
    reason: "依据完整图组裁决整体视觉印象为低。",
    lawyer_override: false,
    resolved_at: "2026-09-02T00:10:00Z",
  });
  writeFileSync(resolutionPath, JSON.stringify(resolution));
  const resolved = run(["merge-reviews", "--assessment-input", inputPath, "--first-review", firstPath, "--second-review", secondPath, "--resolution", resolutionPath, "--output", outputPath]);
  assert.equal(resolved.unresolved_conflict_total, 0);
  assert.equal(resolved.legal_risk, "low");
  run(["finalize-assessment", "--task-dir", directory, "--input", outputPath]);
  run(["render-report", "--task-dir", directory]);
  assert.equal(run(["validate-release", "--task-dir", directory]).reason_code, "V2_RELEASE_VALIDATED");

  for (const mutate of [
    (artifact) => { delete artifact.reason; },
    (artifact) => { artifact.lawyer_override = "yes"; },
    (artifact) => { artifact.lawyer_override = true; },
    (artifact) => { artifact.resolved_at = "not-a-date"; },
  ]) {
    const invalidResolution = JSON.parse(JSON.stringify(resolution));
    delete invalidResolution.digest;
    mutate(invalidResolution);
    writeFileSync(resolutionPath, JSON.stringify(finalizeImmutableArtifact(invalidResolution)));
    assert.equal(run(["merge-reviews", "--assessment-input", inputPath, "--first-review", firstPath, "--second-review", secondPath, "--resolution", resolutionPath], { expectStatus: 2 }).reason_code, "RESOLUTION_INPUT_INVALID");
  }

  writeFileSync(firstPath, JSON.stringify(makeReview("first", "reviewer-a", "session-a", "low")));
  writeFileSync(secondPath, JSON.stringify(makeReview("second", "reviewer-b", "session-b", "low", { includeObservation: false })));
  assert.equal(run(["merge-reviews", "--assessment-input", inputPath, "--first-review", firstPath, "--second-review", secondPath, "--output", outputPath], { expectStatus: 2 }).reason_code, "REVIEW_FACT_COVERAGE_MISMATCH");

  const existingConflictInput = JSON.parse(JSON.stringify(input));
  existingConflictInput.review.fact_conflicts = [{
    conflict_id: "existing_visual_conflict",
    module: "appearance_design",
    candidate_id: input.candidates[0].candidate_id,
    fact_path: "factors.overall_visual_impression",
    first_review_value: "high",
    second_review_value: "low",
    rating_material: true,
    status: "unresolved",
  }];
  const existingInputPath = join(directory, "assessment-input-existing-conflict.json");
  writeFileSync(existingInputPath, JSON.stringify(existingConflictInput));
  writeFileSync(firstPath, JSON.stringify(makeReview("first", "reviewer-a", "session-a", "unknown", { base: existingConflictInput })));
  writeFileSync(secondPath, JSON.stringify(makeReview("second", "reviewer-b", "session-b", "unknown", { base: existingConflictInput })));
  const preserved = run(["merge-reviews", "--assessment-input", existingInputPath, "--first-review", firstPath, "--second-review", secondPath, "--output", outputPath]);
  assert.equal(preserved.unresolved_conflict_total, 1);
  assert.equal(preserved.legal_risk, "not_assessable");

  let unsafeReview = makeReview("first", "reviewer-a", "session-a", "low");
  unsafeReview.modules.find((module) => module.module === "appearance_design").fact_observations[0].fact_path = "factors.__proto__.polluted";
  unsafeReview = finalizeImmutableArtifact(unsafeReview);
  writeFileSync(firstPath, JSON.stringify(unsafeReview));
  writeFileSync(secondPath, JSON.stringify(makeReview("second", "reviewer-b", "session-b", "low")));
  assert.equal(run(["merge-reviews", "--assessment-input", inputPath, "--first-review", firstPath, "--second-review", secondPath], { expectStatus: 2 }).reason_code, "REVIEW_FACT_PATH_INVALID");

  let selfResolvedReview = makeReview("first", "reviewer-a", "session-a", "low");
  selfResolvedReview.fact_conflicts = [{
    conflict_id: "reviewer_self_resolution",
    module: "appearance_design",
    candidate_id: input.candidates[0].candidate_id,
    fact_path: "factors.overall_visual_impression",
    first_review_value: "high",
    second_review_value: "low",
    rating_material: true,
    status: "resolved_by_human",
    resolution_value: "low",
    resolution_evidence_refs: ["evidence://review/self-resolution"],
  }];
  selfResolvedReview = finalizeImmutableArtifact(selfResolvedReview);
  writeFileSync(firstPath, JSON.stringify(selfResolvedReview));
  assert.equal(run(["merge-reviews", "--assessment-input", inputPath, "--first-review", firstPath, "--second-review", secondPath], { expectStatus: 2 }).reason_code, "REVIEW_CONFLICT_INVALID");
});
