import { requireChromeExecutable } from "./platform-runtime.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright-core";
import { compilePpubsBoolean, compilePpubsQuery, extractAmazonProduct, freshState, browserRateLimited,
  submitSearch, waitForSearchSemanticState, collectPpubsRenderedResults, existingProviderRateLimit, rateLimitPageRef, ensureSession } from "./cdp-cli.mjs";

const CHROME = requireChromeExecutable();
const TM = { tmsearch_query_binding: { tmsearchQuery: 'CM:"FUNANYWHERE"' }, cdp: { semantic_poll_ms: 15, semantic_stable_samples: 2 } };
async function localPage(t) {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  t.after(() => browser.close());
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.route("**/*", route => route.abort());
  return page;
}

test("PPS v2 shares its accepted and rejected expressions with Python, without changing legacy rows", async () => {
  const fixture = JSON.parse(await fs.readFile(new URL("../../tests/fixtures/ppubs-boolean-v2.json", import.meta.url), "utf8"));
  for (const item of fixture) {
    if (item.error) assert.throws(() => compilePpubsBoolean(item.q, "ppubs-boolean-v2"), new RegExp(item.error), item.q);
    else assert.equal(compilePpubsBoolean(item.q, "ppubs-boolean-v2"), item.expected, item.q);
  }
  const old = { q: "layered ring with rectangular openings", strategy: "boolean", right_type: "patent" };
  assert.equal(compilePpubsQuery(old).rendered_query, "layered AND ring AND with AND rectangular AND openings");
  assert.throws(() => compilePpubsQuery({ ...old, query_compiler_revision: "ppubs-boolean-v2" }), /UNSUPPORTED_QUERY_SEMANTICS/);
});

test("PPS reports its visible query error rather than waiting for a result or matching document prose", async t => {
  const page = await localPage(t);
  const config = { ppubs_query_binding: { strict: true, renderedQuery: "ring AND WITH AND toy" }, cdp: { semantic_poll_ms: 10, semantic_stable_samples: 2 } };
  for (const error of ['Query Error : Cannot have consecutive operators: AND, WITH', '<b>Query Error</b><span>Cannot have consecutive operators: AND, WITH</span>', 'AND at position 9 is missing term(s)']) {
    await page.setContent(`<div id="searchResults-content"><p>${error}</p><div id="search-results-table"><div class="slick-row"><div class="slick-cell" aria-describedby="slickgrid_1documentId">US 11401089 B2</div><div class="slick-cell" aria-describedby="slickgrid_1inventionTitle">Old result</div></div></div></div>`);
    // Release runs launch several Chrome fixtures concurrently; allow two
    // semantic samples without making CPU scheduling the assertion.
    const rejected = await waitForSearchSemanticState(page, "uspto_patent_browser", 2000, config);
    assert.equal(rejected.stable, true); assert.equal(rejected.queryError, true); assert.equal(rejected.noResult, false);
    assert.equal(rejected.candidates.length, 0); assert.ok(rejected.query_error_text);
  }
  await page.setContent('<div id="searchResults-content"></div><article>Query Error : an example inside a patent</article>');
  const prose = await waitForSearchSemanticState(page, "uspto_patent_browser", 60, config);
  assert.equal(prose.queryError, false); assert.equal(prose.stable, false);
  await page.setContent(`<trix-editor class="trix" aria-label="Enter query text">toy</trix-editor>
    <div id="searchResults-content"><div class="resultInfo"><span class="lQuery">L1:</span><span class="resultNumber">1</span> results found.</div>
    <div id="search-results-table"><div class="slick-row"><span class="slick-cell" aria-describedby="slickgrid_1documentId">US 11401089 B2</span>
    <span class="slick-cell" aria-describedby="slickgrid_1inventionTitle">Electronic toy</span></div></div></div>
    <article>The control system reports an error status when the toy battery is low.</article>`);
  const valid = await waitForSearchSemanticState(page, "uspto_patent_browser", 2000,
    { ...config, ppubs_query_binding: { strict: true, renderedQuery: "toy", historyBinding: { result_set_id: "L1", query: "toy", total_hits: 1 } } });
  assert.equal(valid.queryError, false); assert.equal(valid.query_bound, true); assert.equal(valid.candidates.length, 1);
});

test("TM headerless zero requires this submission's result transition; stale zero and loading are not enough", async t => {
  const page = await localPage(t);
  await page.unroute("**/*");
  await page.route("**/*", route => route.fulfill({ contentType: "text/html", body: `<mat-select formcontrolname="searchRefinement">Field tag and Search builder</mat-select>
    <input id="searchbar" type="search" placeholder="Search using field tags"><button type="submit">Search</button><div id="result"></div>` }));
  await page.goto("https://tmsearch.uspto.gov/");
  await page.evaluate(() => document.querySelector("button").onclick = () => {
    history.pushState({}, "", "/search/search-results"); document.querySelector("#result").textContent = "No results found";
  });
  const event = await submitSearch(page, TM.tmsearch_query_binding.tmsearchQuery, "uspto_tmsearch_browser", { tmsearchFieldTags: true });
  const zero = await waitForSearchSemanticState(page, "uspto_tmsearch_browser", 500, TM);
  assert.equal(zero.noResult, true); assert.equal(zero.query_bound, true); assert.equal(zero.tmsearch_binding.total_hits, 0);
  assert.equal(zero.tmsearch_binding.result_query, "");
  assert.equal(zero.tmsearch_binding.zero_result_transition.submission_id, event.submission_id);
  assert.deepEqual(zero.tmsearch_binding.zero_result_transition.baseline, event.result_baseline);
  assert.equal(zero.tmsearch_binding.zero_result_transition.method, "result_route");
  const next = { ...TM, tmsearch_query_binding: { tmsearchQuery: 'CM:"DIFFERENT"' } };
  await submitSearch(page, next.tmsearch_query_binding.tmsearchQuery, "uspto_tmsearch_browser", { tmsearchFieldTags: true });
  const stale = await waitForSearchSemanticState(page, "uspto_tmsearch_browser", 90, next);
  assert.equal(stale.stable, false); assert.equal(stale.noResult, false);
  await page.evaluate(() => {
    document.body.insertAdjacentHTML("beforeend", '<footer id="widget"></footer>');
    document.querySelector("button").onclick = () => {
      document.querySelector("#widget").innerHTML = '<div role="progressbar">Independent chat widget refreshing</div>';
      setTimeout(() => document.querySelector("#widget").replaceChildren(), 160);
    };
  });
  await submitSearch(page, next.tmsearch_query_binding.tmsearchQuery, "uspto_tmsearch_browser", { tmsearchFieldTags: true });
  const footer = await waitForSearchSemanticState(page, "uspto_tmsearch_browser", 400, next);
  assert.equal(footer.stable, false); assert.equal(footer.noResult, false); assert.equal(footer.query_bound, false);
  await page.evaluate(() => document.querySelector("button").onclick = () => {
    document.querySelector("#result").innerHTML = '<div role="progressbar">Loading...</div>';
    setTimeout(() => document.querySelector("#result").textContent = "No results found", 160);
  });
  await submitSearch(page, next.tmsearch_query_binding.tmsearchQuery, "uspto_tmsearch_browser", { tmsearchFieldTags: true });
  const refreshed = await waitForSearchSemanticState(page, "uspto_tmsearch_browser", 600, next);
  assert.equal(refreshed.noResult, true); assert.equal(refreshed.tmsearch_binding.zero_result_transition.method, "loading_cycle");
  assert.deepEqual(refreshed.tmsearch_binding.zero_result_transition.result_container_transition,
    { prior_zero_disappeared: true, result_loading_observed: true, result_zero_reappeared: true });
});

test("visible rate-limit dialog after a long patent stops preparation without dismissal", async t => {
  const page = await localPage(t);
  await page.setContent(`<article>${"long patent text ".repeat(15000)}</article><div role="dialog"><h2>Too Many Requests</h2><button>OK</button></div>`);
  await page.evaluate(() => { window.clicks = 0; document.querySelector("button").onclick = () => window.clicks++; });
  const state = await freshState(page);
  assert.match(state.ui_alert_text, /Too Many Requests/); assert.equal(browserRateLimited(state.bodyText), true);
  await assert.rejects(() => submitSearch(page, "toy", "uspto_patent_browser", { strict: true }), error => error.code === "BROWSER_RATE_LIMITED" && error.submission_state === "not_submitted");
  assert.equal(await page.evaluate(() => window.clicks), 0);
});

test("a rate limit during family expansion preserves already captured patent rows", async t => {
  const page = await localPage(t), dir = await fs.mkdtemp(path.join(os.tmpdir(), "ipr-family-rate-"));
  t.after(() => fs.rm(dir, { recursive: true, force: true }));
  await page.setContent(`<trix-editor class="trix" aria-label="Enter query text">toy</trix-editor>
    <div id="searchResults-content"><div class="resultInfo"><span class="lQuery">L1:</span><span class="resultNumber">2</span> results found.</div>
    <div id="search-results-table"><div class="slick-viewport" style="position:relative;height:30px;overflow:auto"><div class="slick-row" style="position:relative;top:0;height:30px">
    <span class="slick-cell" aria-describedby="slickgrid_1documentId">US 11401089 B2</span><span class="slick-cell" aria-describedby="slickgrid_1inventionTitle">Toy</span>
    <span class="slick-cell" aria-describedby="slickgrid_1familyGroup"><button>+1</button></span></div></div></div></div>`);
  await page.evaluate(() => document.querySelector("button").onclick = () => {
    document.body.insertAdjacentHTML("beforeend", '<div role="dialog" style="position:fixed;inset:0;background:white">Too Many Requests</div>');
  });
  const result = await collectPpubsRenderedResults(page, { result_set_id: "L1", rendered_query: "toy" }, dir, "partial", { familyTimeoutMs: 80 });
  assert.equal(result.candidates.length, 1); assert.equal(result.result_coverage.stop_reason, "BROWSER_RATE_LIMITED");
  assert.equal(result.result_coverage.truncated, true); assert.equal(result.result_coverage.schema_valid, true);
});

test("rate-limit recovery inspects an existing official page without navigation or dismissing unlabelled modal", async t => {
  const page = await localPage(t);
  await page.unroute("**/*");
  await page.route("**/*", route => route.fulfill({ contentType: "text/html", body: '<div><h2>Too Many Requests</h2><p>There are too many requests in your user session. Please try your request again later.</p><button>OK</button></div>' }));
  await page.goto("https://ppubs.uspto.gov/pubwebapp/");
  await page.evaluate(() => { window.clicks = 0; document.querySelector("button").onclick = () => window.clicks++; });
  let navigations = 0;
  page.on("framenavigated", () => navigations++);
  const pageRef = await rateLimitPageRef(page);
  assert.match(pageRef.target_id, /^[a-f0-9]{32}$/i);
  const result = await existingProviderRateLimit(page.context(), "uspto_patent_browser", pageRef);
  assert.equal(result.error_code, "BROWSER_RATE_LIMITED"); assert.equal(result.submission_state, "not_submitted");
  assert.equal(navigations, 0); assert.equal(await page.evaluate(() => window.clicks), 0);
  await page.locator("div").evaluate(node => node.textContent = "Patent Public Search");
  assert.equal(await existingProviderRateLimit(page.context(), "uspto_patent_browser", pageRef), null);
  await page.locator("div").evaluate(node => node.remove());
  assert.equal((await existingProviderRateLimit(page.context(), "uspto_patent_browser", pageRef)).error_code, "BROWSER_RATE_LIMIT_RECOVERY_UNVERIFIED");
  assert.equal((await existingProviderRateLimit({ pages: () => [] }, "uspto_patent_browser", pageRef)).submission_state, "not_submitted");
  assert.equal(navigations, 0);
  const help = await page.context().newPage();
  await help.route("**/*", route => route.fulfill({ contentType: "text/html", body: "Patent Public Search Help" }));
  await help.goto("https://ppubs.uspto.gov/help");
  assert.equal((await existingProviderRateLimit(page.context(), "uspto_patent_browser", pageRef)).error_code, "BROWSER_RATE_LIMIT_RECOVERY_UNVERIFIED");
  await help.goto(pageRef.url); // Even a replacement tab on the identical URL has a different identity.
  assert.equal((await existingProviderRateLimit(page.context(), "uspto_patent_browser", pageRef)).error_code, "BROWSER_RATE_LIMIT_RECOVERY_UNVERIFIED");
  await page.close();
  assert.equal((await existingProviderRateLimit(help.context(), "uspto_patent_browser", pageRef)).error_code, "BROWSER_RATE_LIMIT_RECOVERY_UNVERIFIED");
  assert.equal((await existingProviderRateLimit(help.context(), "uspto_patent_browser")).error_code, "BROWSER_RATE_LIMIT_RECOVERY_UNVERIFIED");
});

test("rate-limit recovery cannot create a profile or launch a replacement browser when the old session is absent", async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "ipr-recovery-absent-"));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const runtime = path.join(root, "runtime"), profile = path.join(root, "profile");
  await assert.rejects(() => ensureSession({ cdp: { runtime_dir: runtime, profile_dir: profile } }, { existingOnly: true }),
    error => error.code === "BROWSER_RATE_LIMIT_RECOVERY_UNVERIFIED");
  assert.deepEqual(await fs.readdir(root), []);
});

test("Amazon byline normalization retains source and distinguishes placeholders from actual brand text", async t => {
  const page = await localPage(t);
  for (const [raw, brand, placeholder] of [["Brand: Generic", "Generic", true], ["Brand: Unbranded", "Unbranded", true], ["Visit the ACME Store", "ACME", false], ["Brand: The Store", "The Store", false], ["Brand: GENERIC TOYS", "GENERIC TOYS", false], ["", "", false]]) {
    await page.setContent('<a id="bylineInfo"></a>');
    await page.locator("#bylineInfo").evaluate((node, value) => node.textContent = value, raw);
    const actual = await extractAmazonProduct(page, { strict: true });
    assert.equal(actual.brand, brand); assert.equal(actual.brand_byline_raw, raw); assert.equal(actual.brand_placeholder, placeholder);
  }
});
