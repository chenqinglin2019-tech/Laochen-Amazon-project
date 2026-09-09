import { resolvePythonExecutable } from "./platform-runtime.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { registryPageBindingDigest } from "./cdp-cli.mjs";

const TOOL_DIR = path.dirname(fileURLToPath(import.meta.url));
const RECORDER = path.resolve(TOOL_DIR, "..", "..", "scripts", "record_registry_browser.py");
const SCRIPTS_DIR = path.dirname(RECORDER);
const PYTHON_ENV = {
  ...process.env, PYTHONPATH: SCRIPTS_DIR,
  LC_IPR_OFFLINE_TESTS: "1", PYTHONDONTWRITEBYTECODE: "1",
};

test("registry recorder rejects missing or non-official terms review", () => {
  const script = `
import json, sys
from record_registry_browser import _terms_review
try:
    print(json.dumps(_terms_review(json.loads(sys.argv[1]), {"register.dpma.de"})))
except ValueError as exc:
    print(str(exc))
    raise SystemExit(3)
`;
  const missing = spawnSync(resolvePythonExecutable(), ["-c", script, JSON.stringify({})], {
    encoding: "utf8", env: PYTHON_ENV,
  });
  assert.equal(missing.status, 3);
  assert.match(missing.stdout, /REGISTRY_TERMS_REVIEW_REQUIRED/);
  const invalid = spawnSync(resolvePythonExecutable(), ["-c", script, JSON.stringify({
    terms_review: {
      schema_version: "1.0", operator_confirmed: true,
      decision: "cdp_assisted_single_action_confirmed",
      terms_url: "https://example.com/terms", checked_at: new Date().toISOString(),
    },
  })], { encoding: "utf8", env: PYTHON_ENV });
  assert.equal(invalid.status, 3);
  assert.match(invalid.stdout, /allowlisted official HTTPS host/);
});

test("registry recorder skips before reading capture when JPO already completed verification", async () => {
  const taskDir = await fs.mkdtemp(path.join(os.tmpdir(), "registry-recorder-skip-"));
  try {
    const checkedAt = new Date().toISOString();
    const coverageResult = spawnSync(resolvePythonExecutable(), [
      "-c",
      "import json; from common import build_coverage_requirements; print(json.dumps(build_coverage_requirements(['JP'])))",
    ], {
      encoding: "utf8",
      env: PYTHON_ENV,
    });
    assert.equal(coverageResult.status, 0, coverageResult.stderr);
    const coverageRequirements = JSON.parse(coverageResult.stdout);
    const jpoPlanEntry = {
      query_id: "QRY-JPO-API-SKIP",
      q: "2020008423",
      number: "2020008423",
      number_kind: "application",
      candidate_id: "CAND-SKIP",
      operation: "candidate_verification",
      jurisdiction: "JP",
      right_type: "patent",
      requirement_ids: ["COV-JP-PATENT-VERIFY"],
    };
    const digestResult = spawnSync(resolvePythonExecutable(), [
      "-c",
      "import json,sys; from common import sha256_json; print(sha256_json(json.loads(sys.argv[1])))",
      JSON.stringify(jpoPlanEntry),
    ], {
      encoding: "utf8",
      env: PYTHON_ENV,
    });
    assert.equal(digestResult.status, 0, digestResult.stderr);
    const jpoPlanDigest = digestResult.stdout.trim();
    await fs.writeFile(path.join(taskDir, "task.json"), JSON.stringify({
      schema_version: "2.3-free",
      task_id: "TASK-SKIP",
      target_jurisdictions: ["JP"],
      free_policy: {
        mode: "official_free_only", allow_registration: true,
        allow_commercial_freemium: true,
        commercial_freemium_mode: "explicit_opt_in",
        commercial_freemium_allowlist: ["serper", "serpapi"],
        allow_paid: false, allow_overage: false,
        on_quota_exhausted: "stop_and_report",
      },
      coverage_requirements: coverageRequirements,
    }));
    await fs.writeFile(path.join(taskDir, "search-plan.json"), JSON.stringify({
      schema_version: "2.3-free",
      task_id: "TASK-SKIP",
      queries: {
        jpo_api: [jpoPlanEntry],
        jplatpat_browser: [{
          query_id: "QRY-JP-SKIP",
          q: "2020008423",
          record_number: "2020008423",
          candidate_id: "CAND-SKIP",
          operation: "candidate_verification",
          jurisdiction: "JP",
          right_type: "patent",
          mode: "user_assisted",
          requirement_ids: ["COV-JP-PATENT-VERIFY"],
        }],
      },
    }));
    await fs.writeFile(path.join(taskDir, "normalized-candidates.json"), JSON.stringify({
      patents: [{
        candidate_id: "CAND-SKIP",
        right_type: "patent",
        application_number: "2020008423",
        verification_refs: ["EV-JPO-SKIP"],
        official_verification: {
          status: "verified",
          authority: "Japan Patent Office (JPO)",
          method: "official_free_api",
          identity_match: true,
          owner: ["権利者"],
          legal_status: "registered",
          classes: [],
          updated_date: "2026-09-03",
          url: "https://www.j-platpat.inpit.go.jp/c1801/PU/JP-2020008423/15/ja",
          checked_at: checkedAt,
          media: [],
        },
      }],
      trademarks: [],
    }));
    await fs.writeFile(path.join(taskDir, "evidence.json"), JSON.stringify({
      source_runs: [{
        run_id: "RUN-JPO-SKIP", provider: "jpo_api", operation: "candidate_verification",
        query_id: "QRY-JPO-API-SKIP",
        query: "2020008423",
        jurisdiction: "JP", right_type: "patent", status: "success",
        requirement_ids: ["COV-JP-PATENT-VERIFY"],
        request_params: {
          number: "2020008423", number_kind: "application", right_type: "patent",
          candidate_id: "CAND-SKIP",
        },
        source_environment: "production", authoritative_for_final_rating: true,
        plan_entry_sha256: jpoPlanDigest,
      }],
      collections: { official_verifications: [{
        evidence_id: "EV-JPO-SKIP", source_run_id: "RUN-JPO-SKIP",
        query_id: "QRY-JPO-API-SKIP",
        provider: "jpo_api", operation: "candidate_verification", jurisdiction: "JP",
        right_type: "patent", requirement_ids: ["COV-JP-PATENT-VERIFY"],
        plan_entry_sha256: jpoPlanDigest,
        payload: {
          candidate_id: "CAND-SKIP", right_type: "patent", application_number: "2020008423",
          official_verification: {
            status: "verified", authority: "Japan Patent Office (JPO)",
            method: "official_free_api", identity_match: true,
            owner: ["権利者"], legal_status: "registered", classes: [],
            updated_date: "2026-09-03",
            url: "https://www.j-platpat.inpit.go.jp/c1801/PU/JP-2020008423/15/ja",
            checked_at: checkedAt, media: [],
          },
        },
      }] },
    }));
    const missingCapture = path.join(taskDir, "must-not-be-read.json");
    const result = spawnSync(resolvePythonExecutable(), [
      RECORDER,
      "--task-dir", taskDir,
      "--provider", "jplatpat_browser",
      "--capture", missingCapture,
      "--operation", "candidate_verification",
      "--right-type", "patent",
      "--jurisdiction", "JP",
      "--record", "2020008423",
      "--candidate-id", "CAND-SKIP",
      "--query-id", "QRY-JP-SKIP",
    ], { encoding: "utf8", env: PYTHON_ENV });
    assert.equal(result.status, 0, result.stderr);
    const output = JSON.parse(result.stdout);
    assert.equal(output.status, "not_applicable");
    assert.equal(output.skipped, true);
    await assert.rejects(fs.access(missingCapture));
  } finally {
    await fs.rm(taskDir, { recursive: true, force: true });
  }
});

test("registry evidence binds each local image to hash, bytes, and MIME type", async () => {
  const taskDir = await fs.mkdtemp(path.join(os.tmpdir(), "registry-media-binding-"));
  try {
    const screenshotsDir = path.join(taskDir, "screenshots");
    const imagePath = path.join(screenshotsDir, "record.png");
    const bytes = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
    await fs.mkdir(screenshotsDir, { recursive: true });
    await fs.writeFile(imagePath, bytes);
    const result = spawnSync(resolvePythonExecutable(), [
      "-c",
      [
        "import json,sys",
        "from pathlib import Path",
        "from record_registry_browser import _evidence_file",
        "print(json.dumps(_evidence_file(sys.argv[1], 'screenshot_path', Path(sys.argv[2]))))",
      ].join(";"),
      imagePath,
      taskDir,
    ], {
      encoding: "utf8",
      env: PYTHON_ENV,
    });
    assert.equal(result.status, 0, result.stderr);
    const [recordedPath, digest, byteCount, mimeType] = JSON.parse(result.stdout);
    assert.equal(recordedPath, await fs.realpath(imagePath));
    assert.match(digest, /^[a-f0-9]{64}$/);
    assert.equal(byteCount, bytes.length);
    assert.equal(mimeType, "image/png");
  } finally {
    await fs.rm(taskDir, { recursive: true, force: true });
  }
});

test("registry candidate recorder binds query, candidate, record, jurisdiction, right type, and page case", async () => {
  const taskDir = await fs.mkdtemp(path.join(os.tmpdir(), "registry-candidate-binding-"));
  try {
    const planned = {
      query_id: "QRY-DE-DESIGN-VERIFY",
      q: "DE402024000001",
      record_number: "DE402024000001",
      candidate_id: "CAND-DE-DESIGN",
      operation: "candidate_verification",
      jurisdiction: "DE",
      right_type: "design",
      mode: "user_assisted",
      requirement_ids: ["COV-DE-DESIGN-VERIFY"],
    };
    await fs.writeFile(path.join(taskDir, "search-plan.json"), JSON.stringify({
      queries: { official_registry_browser: [planned] },
    }));
    const script = `
import json, sys
from pathlib import Path
from record_registry_browser import _verification_plan_binding
capture = json.loads(sys.argv[2])
try:
    result = _verification_plan_binding(
        Path(sys.argv[1]), "official_registry_browser", "DE", "design",
        "DE402024000001", "CAND-DE-DESIGN", capture,
        "QRY-DE-DESIGN-VERIFY",
    )
except ValueError as exc:
    print(str(exc))
    raise SystemExit(3)
print(result[0])
`;
    const validCapture = {
      query_id: planned.query_id,
      candidate_id: planned.candidate_id,
      record_number: planned.record_number,
      page_record_number: planned.record_number,
    };
    const valid = spawnSync(resolvePythonExecutable(), ["-c", script, taskDir, JSON.stringify(validCapture)], {
      encoding: "utf8", env: PYTHON_ENV,
    });
    assert.equal(valid.status, 0, valid.stderr);
    assert.match(valid.stdout, /QRY-DE-DESIGN-VERIFY/);

    for (const mutation of [
      { candidate_id: "CAND-STALE" },
      { query_id: "QRY-STALE" },
      { page_record_number: "DE402024999999" },
      { status: "no_result", page_record_number: "", page_query_record: "" },
    ]) {
      const invalid = spawnSync(resolvePythonExecutable(), [
        "-c", script, taskDir, JSON.stringify({ ...validCapture, ...mutation }),
      ], { encoding: "utf8", env: PYTHON_ENV });
      assert.equal(invalid.status, 3, invalid.stderr);
    }
    const boundNoResult = spawnSync(resolvePythonExecutable(), [
      "-c", script, taskDir, JSON.stringify({
        ...validCapture, status: "no_result", page_record_number: "",
        page_query_record: planned.record_number,
      }),
    ], { encoding: "utf8", env: PYTHON_ENV });
    assert.equal(boundNoResult.status, 0, boundNoResult.stderr);
  } finally {
    await fs.rm(taskDir, { recursive: true, force: true });
  }
});

test("public candidate recorder requires the exact planned source and record", async () => {
  const taskDir = await fs.mkdtemp(path.join(os.tmpdir(), "public-candidate-binding-"));
  try {
    const planned = {
      query_id: "QRY-US-PTAB-VERIFY",
      q: "IPR2026-00123",
      record_number: "IPR2026-00123",
      candidate_id: "CAND-US-PTAB",
      operation: "candidate_verification",
      jurisdiction: "US",
      right_type: "enforcement",
      source_key: "ptab",
      mode: "manual_capture",
      requirement_ids: ["COV-US-ENFORCEMENT-VERIFY"],
    };
    await fs.writeFile(path.join(taskDir, "search-plan.json"), JSON.stringify({
      queries: { public_web_browser: [planned] },
    }));
    const script = `
import json, sys
from pathlib import Path
from record_registry_browser import _rules, _verification_plan_binding
rules = _rules("public_web_browser", "US", {
    "providers": {"public_web_browser": {"jurisdiction_allowed_hosts": {
        "US": ["publicrecords.copyright.gov", "ttabvue.uspto.gov", "ptab.uspto.gov", "ccb.gov", "dockets.ccb.gov"]
    }}}
})
assert "candidate_verification" in rules["operations"]
try:
    result = _verification_plan_binding(
        Path(sys.argv[1]), "public_web_browser", "US", "enforcement",
        sys.argv[2], "CAND-US-PTAB", json.loads(sys.argv[3]),
        "QRY-US-PTAB-VERIFY",
    )
except ValueError as exc:
    print(str(exc))
    raise SystemExit(3)
print(result[0])
`;
    const capture = {
      query_id: planned.query_id,
      candidate_id: planned.candidate_id,
      source_key: "ptab",
      record_number: planned.record_number,
      page_record_number: planned.record_number,
    };
    const valid = spawnSync(resolvePythonExecutable(), [
      "-c", script, taskDir, planned.record_number, JSON.stringify(capture),
    ], { encoding: "utf8", env: PYTHON_ENV });
    assert.equal(valid.status, 0, valid.stderr);
    for (const [record, mutation] of [
      [planned.record_number, { source_key: "ttabvue" }],
      ["IPR202600123", {}],
    ]) {
      const invalid = spawnSync(resolvePythonExecutable(), [
        "-c", script, taskDir, record, JSON.stringify({ ...capture, ...mutation }),
      ], { encoding: "utf8", env: PYTHON_ENV });
      assert.equal(invalid.status, 3, invalid.stderr);
    }
  } finally {
    await fs.rm(taskDir, { recursive: true, force: true });
  }
});

test("USPTO candidate recorders reject stale query/candidate/record bindings", async () => {
  const taskDir = await fs.mkdtemp(path.join(os.tmpdir(), "uspto-candidate-binding-"));
  try {
    const patent = {
      query_id: "QRY-US-DESIGN", q: "USD1132316S1", record_number: "USD1132316S1",
      candidate_id: "CAND-US-DESIGN", operation: "candidate_verification",
      jurisdiction: "US", right_type: "design", requirement_ids: ["COV-US-DESIGN-VERIFY"],
    };
    const trademark = {
      query_id: "QRY-US-TSDR", q: "99123456", serial_number: "99123456",
      candidate_id: "CAND-US-TM", operation: "candidate_verification",
      jurisdiction: "US", right_type: "trademark_figurative",
      mode: "user_assisted", requirement_ids: ["COV-US-TM-FIGURATIVE-VERIFY"],
    };
    await fs.writeFile(path.join(taskDir, "search-plan.json"), JSON.stringify({
      queries: { uspto_patent_browser: [patent], uspto_tsdr: [trademark] },
    }));
    const script = `
import json, sys
from pathlib import Path
if sys.argv[1] == "patent":
    from record_uspto_patent_chrome_verification import bind_candidate_plan
    result = bind_candidate_plan(Path(sys.argv[2]), json.loads(sys.argv[3]), "USD1132316S1", "design")
else:
    from record_tsdr_browser_verification import bind_candidate_plan
    result = bind_candidate_plan(Path(sys.argv[2]), json.loads(sys.argv[3]), "99123456", "trademark_figurative")
print(result[0])
`;
    const patentCapture = { query_id: patent.query_id, candidate_id: patent.candidate_id };
    const trademarkCapture = { query_id: trademark.query_id, candidate_id: trademark.candidate_id };
    for (const [kind, capture, expected] of [
      ["patent", patentCapture, patent.query_id], ["trademark", trademarkCapture, trademark.query_id],
    ]) {
      const valid = spawnSync(resolvePythonExecutable(), ["-c", script, kind, taskDir, JSON.stringify(capture)], {
        encoding: "utf8", env: PYTHON_ENV,
      });
      assert.equal(valid.status, 0, valid.stderr);
      assert.match(valid.stdout, new RegExp(expected));
      const stale = spawnSync(resolvePythonExecutable(), [
        "-c", script, kind, taskDir, JSON.stringify({ ...capture, candidate_id: "CAND-STALE" }),
      ], { encoding: "utf8", env: PYTHON_ENV });
      assert.notEqual(stale.status, 0);
      assert.match(stale.stderr, /candidate_id.*does not match/i);
    }
  } finally {
    await fs.rm(taskDir, { recursive: true, force: true });
  }
});

function validateRecallAttestation(capture, planned, browserEvidence) {
  const script = `
import json, sys
from record_registry_browser import _validate_recall_attestation
capture = json.loads(sys.argv[1])
planned = json.loads(sys.argv[2])
browser_evidence = json.loads(sys.argv[3])
query_id = planned["query_id"]
try:
    _validate_recall_attestation(capture, planned, browser_evidence, query_id)
except ValueError as exc:
    print(str(exc))
    raise SystemExit(3)
print("accepted")
`;
  return spawnSync(resolvePythonExecutable(), [
    "-c", script,
    JSON.stringify(capture),
    JSON.stringify(planned),
    JSON.stringify(browserEvidence),
  ], {
    encoding: "utf8",
    env: PYTHON_ENV,
  });
}

function bindRecallAttestation(capture, planned, browserEvidence) {
  const bound = structuredClone(capture);
  bound.operator_attestation.page_binding_sha256 = registryPageBindingDigest({
    query_id: planned.query_id,
    final_url: bound.final_url,
    page_title: bound.page_title,
    screenshot_sha256: bound.screenshot_sha256,
    checked_at: bound.checked_at,
    rendered_search: bound.rendered_search,
    capture_provenance: browserEvidence.capture_provenance,
  });
  return bound;
}

test("registry recorder rejects missing attestation and a stale rendered query", () => {
  const checkedAt = new Date().toISOString();
  const planned = {
    query_id: "QRY-JP-RECALL-1",
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
  const browserEvidence = {
    screenshot_sha256: "a".repeat(64),
    capture_provenance: {
      browser: "chrome_desktop",
      capture_transport: "cdp",
      browser_version: "Chrome/140",
      protocol_version: "1.3",
      cdp_session_id: "session_12345678",
    },
  };
  const baseCapture = {
    query_id: planned.query_id,
    query: planned.q,
    right_type: planned.right_type,
    final_url: "https://www.j-platpat.inpit.go.jp/results",
    page_title: "J-PlatPat search results",
    screenshot_sha256: browserEvidence.screenshot_sha256,
    checked_at: checkedAt,
    rendered_search: {
      schema_version: "1.0",
      extraction_attempted: true,
      query_values: [],
      query_sources: [],
      filters: {},
      filter_sources: {},
    },
  };

  const missing = validateRecallAttestation(baseCapture, planned, browserEvidence);
  assert.equal(missing.status, 3, missing.stderr);
  assert.match(missing.stdout, /REGISTRY_OPERATOR_ATTESTATION_REQUIRED/);

  const staleCapture = structuredClone(baseCapture);
  staleCapture.rendered_search.query_values = ["OLD QUERY"];
  staleCapture.rendered_search.query_sources = ["dom:input"];
  staleCapture.operator_attestation = {
    schema_version: "1.0",
    operator_confirmed: true,
    confirmed_current_page: true,
    query: planned.q,
    right_type: planned.right_type,
    filters: {
      classification_scheme: "jpo_figurative_classification",
      query_mode: "figurative_classification",
    },
    invoked_at: checkedAt,
    attested_at: checkedAt,
    page_binding_sha256: "",
  };
  const stale = validateRecallAttestation(
    bindRecallAttestation(staleCapture, planned, browserEvidence), planned, browserEvidence,
  );
  assert.equal(stale.status, 3, stale.stderr);
  assert.match(stale.stdout, /REGISTRY_RENDERED_QUERY_MISMATCH/);

  const attestedFallback = structuredClone(baseCapture);
  attestedFallback.operator_attestation = structuredClone(staleCapture.operator_attestation);
  const accepted = validateRecallAttestation(
    bindRecallAttestation(attestedFallback, planned, browserEvidence), planned, browserEvidence,
  );
  assert.equal(accepted.status, 0, accepted.stderr);
  assert.match(accepted.stdout, /accepted/);
});
