import test from "node:test";
import assert from "node:assert/strict";

import {
  assertCdpProviderAllowed,
  detectChallenge,
  explicitNoResult,
  formatTmQuery,
  patentBasicSearchTerm,
  parsePatentRows,
  parseTrademarkRows,
  renderedPatentPdfScreenshot,
  waitForStableSemanticState,
} from "./cdp-cli.mjs";

test("blocks CDP automation for WIPO and Espacenet", () => {
  assert.throws(
    () => assertCdpProviderAllowed("wipo_patentscope_browser"),
    /manually and operator-confirmed/,
  );
  assert.throws(
    () => assertCdpProviderAllowed("espacenet_browser"),
    /use the planned EPO OPS query/,
  );
  assert.doesNotThrow(() => assertCdpProviderAllowed("uspto_tmsearch_browser"));
  assert.doesNotThrow(() => assertCdpProviderAllowed("uspto_patent_browser"));
});

test("formats only the supported USPTO TM Search strategies", () => {
  assert.equal(formatTmQuery("MOCK MARK", "exact"), '"MOCK MARK"');
  assert.equal(formatTmQuery("MOCK MARK", "phrase"), '"MOCK MARK"');
  assert.equal(formatTmQuery("MOCK", "prefix"), "MOCK*");
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
