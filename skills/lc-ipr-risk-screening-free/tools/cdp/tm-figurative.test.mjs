import { requireChromeExecutable } from "./platform-runtime.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright-core";
import { browserPlannedQuery, browserRouteGate, collectTmRenderedResults, parseTrademarkCards,
  parseTrademarkDetail, waitForSearchSemanticState } from "./cdp-cli.mjs";

const ROW = { jurisdiction: "US", operation: "trademark_recall", right_type: "trademark_figurative", q: "26.17.13",
  strategy: "classification", query_compiler_revision: "tm-figurative-fields-v1", filters: { field: "design_code", language: "en" },
  derived_from: ["product.mark_inventory[0]"] };
const CARD = serial => `Check to tag for ${serial}\nWordmark\nwordmark\nTEST\nStatus\nLIVEPENDING\nGoods & services\nIC 021: Containers\nClass\n021\nSerial\n${serial}\nOwners\nExample LLC`;
const CONFIG = { tmsearch_query_binding: { tmsearchQuery: "DC:261713", allowNonverbal: true },
  cdp: { semantic_poll_ms: 10, semantic_stable_samples: 2, tm_page_timeout_ms: 100 } };

test("new DC/DE semantics require real-element provenance and never reinterpret old figurative text", () => {
  assert.equal(browserPlannedQuery("uspto_tmsearch_browser", ROW).rendered_query, "DC:261713");
  assert.equal(browserRouteGate({ schema_version: "2.4-free" }, "uspto_tmsearch_browser", ROW, true), null);
  const description = { ...ROW, q: "parallel lines", strategy: "phrase", filters: { field: "mark_description", language: "en" } };
  assert.equal(browserPlannedQuery("uspto_tmsearch_browser", description).rendered_query, 'DE:"parallel lines"');
  assert.equal(browserPlannedQuery("uspto_tmsearch_browser", { ...description, strategy: "boolean" }).rendered_query, "DE:(parallel AND lines)");
  for (const row of [{ ...ROW, derived_from: [] }, { ...ROW, derived_from: ["product.brand"] },
    { ...ROW, q: "26.17" }, { ...description, q: "line) OR CM:*", strategy: "boolean" },
    { ...ROW, query_compiler_revision: undefined, q: "Mella", strategy: "phrase", filters: { field: "brand" } }]) {
    assert.throws(() => browserPlannedQuery("uspto_tmsearch_browser", row), /UNSUPPORTED_QUERY_SEMANTICS/);
  }
});

test("nonverbal result is an identified record with an explicitly absent wordmark", () => {
  const text = CARD("99999991").replace("\nTEST\nStatus", "\n\nStatus");
  const [row] = parseTrademarkCards(text, { allowNonverbal: true });
  assert.equal(row.serial_number, "99999991");
  assert.equal(row.mark_text, "");
  assert.equal(row.mark_text_missing, true);
  assert.deepEqual(parseTrademarkCards(text), []);
  assert.deepEqual(parseTrademarkDetail("Search result details for serial number 99999991\nWordmark\n\nSerial number\n99999991\nStatus\nLIVEPENDING\nStatus date\n2026-01-01", "https://tmsearch.uspto.gov/search/search-results/99999991", { allowNonverbal: true }).map(row => row.mark_text_missing), [true]);
});

async function fixture(mode, run) {
  const browser = await chromium.launch({ executablePath: requireChromeExecutable(), headless: true });
  const taskDir = await fs.mkdtemp(path.join(os.tmpdir(), "tm-pages-test-"));
  try {
    const page = await browser.newPage();
    await page.setContent('<mat-select formcontrolname="searchRefinement">Field tag and Search builder</mat-select><input id="searchbar"><pre id="results"></pre><div class="mat-mdc-paginator-range-label">1 – 1 of 2</div><button aria-label="Next page">Next</button>');
    await page.locator("#searchbar").fill("DC:261713");
    await page.locator("#results").evaluate((node, text) => node.textContent = text, `2 results for DC:261713\n${CARD("99999991")}`);
    await page.locator("button").evaluate((button, { mode, card }) => {
      button.onclick = () => {
        document.querySelector(".mat-mdc-paginator-range-label").textContent = "2 – 2 of 2";
        document.querySelector("#results").textContent = mode === "rate_limit" ? "Too Many Requests" : `2 results for ${mode === "stale" ? "OTHER" : "DC:261713"}\n${card}`;
        button.disabled = true;
      };
    }, { mode, card: CARD(mode === "repeat" ? "99999991" : "99999992") });
    const initial = await waitForSearchSemanticState(page, "uspto_tmsearch_browser", 500, CONFIG);
    assert.equal(initial.stable, true);
    await run(page, initial, taskDir);
  } finally { await browser.close(); await fs.rm(taskDir, { recursive: true, force: true }); }
}

test("DC results collect distinct consecutive pages with independent snapshots and honest total", async () => {
  await fixture("good", async (page, initial, taskDir) => {
    // Positive browser readiness needs scheduling headroom in the parallel
    // release suite; keep negative tests' short deadline and production's 12s.
    const result = await collectTmRenderedResults(page, initial, taskDir, "DC-test",
      { ...CONFIG, cdp: { ...CONFIG.cdp, tm_page_timeout_ms: 1000 } });
    assert.equal(result.result_pages.length, 2, JSON.stringify(result.result_coverage));
    assert.deepEqual(result.candidates.map(row => row.serial_number), ["99999991", "99999992"]);
    assert.equal(result.result_coverage.truncated, false);
    assert.equal(result.result_coverage.stop_reason, "browser_results_exhausted");
    assert.notEqual(result.result_pages[0].screenshot_sha256, result.result_pages[1].screenshot_sha256);
    assert.equal(result.query_binding.parsed_count, 1);
  });
});

test("pagination cap preserves earlier page and does not label all results retrieved", async () => {
  await fixture("good", async (page, initial, taskDir) => {
    const result = await collectTmRenderedResults(page, initial, taskDir, "DC-test", CONFIG, { maxPages: 1 });
    assert.equal(result.candidates.length, 1);
    assert.equal(result.result_coverage.truncated, true);
    assert.equal(result.result_coverage.stop_reason, "browser_page_limit");
  });
});

for (const mode of ["stale", "repeat", "rate_limit"]) test(`${mode} next page cannot replace earlier evidence or count as zero`, async () => {
  await fixture(mode, async (page, initial, taskDir) => {
    const result = await collectTmRenderedResults(page, initial, taskDir, "DC-test", CONFIG);
    assert.deepEqual(result.candidates.map(row => row.serial_number), ["99999991"]);
    assert.equal(result.result_coverage.truncated, true);
    assert.equal(result.result_coverage.stop_reason, mode === "rate_limit" ? "BROWSER_RATE_LIMITED" : "browser_page_not_confirmed");
  });
});
