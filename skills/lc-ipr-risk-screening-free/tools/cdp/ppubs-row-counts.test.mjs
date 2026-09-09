import { requireChromeExecutable } from "./platform-runtime.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright-core";
import { ppubsRowCoverage, collectPpubsRenderedResults } from "./cdp-cli.mjs";

const fixture = JSON.parse(await fs.readFile(new URL("../../tests/fixtures/ppubs-duplicate-rows.json", import.meta.url), "utf8"));

test("retained PPS fixture has all 37 ordinals and 20 exact publications, not 17 missing patents", () => {
  const proof = ppubsRowCoverage(fixture.pages, 37);
  assert.equal(proof.complete, true); assert.equal(proof.retrieved_rows, 37); assert.equal(proof.unique_publications, 20);
  assert.deepEqual(proof.ordinal_records.map(row => row[0]), Array.from({ length: 37 }, (_, i) => i + 1));
  for (const kind of ["missing", "conflict", "family", "bottom", "loading"]) {
    const pages = structuredClone(fixture.pages), views = pages[0].viewports;
    if (kind === "missing") for (const view of views) view.rows = view.rows.filter(row => row.rowNumber !== "2");
    if (kind === "conflict") views.at(-1).rows.push({ rowNumber: "1", documentId: "US D999999 S" });
    if (kind === "family") views.at(-1).rows[0].familyGroup = "+1";
    if (kind === "bottom") views.at(-1).viewport.top = 0;
    if (kind === "loading") views.at(-1).loading = true;
    assert.equal(ppubsRowCoverage(pages, 37).complete, false, kind);
  }
});

test("PPS duplicate display rows finish only after complete ordinal evidence", async t => {
  const browser = await chromium.launch({ executablePath: requireChromeExecutable(), headless: true });
  t.after(() => browser.close());
  const page = await browser.newPage();
  await page.route("**/*", route => route.abort());
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "ipr-row-counts-"));
  t.after(() => fs.rm(dir, { recursive: true, force: true }));
  for (const missing of [false, true]) {
    const rows = [1, 2, 3].filter(n => !missing || n !== 2).map((n, i) => `<div class="slick-row" style="position:absolute;top:${i * 25}px;height:25px">
      <span class="slick-cell" aria-describedby="slickgrid_1rowNumber">${n}</span>
      <span class="slick-cell" aria-describedby="slickgrid_1documentId">US D${n === 2 ? "251929" : "238291"} S</span>
      <span class="slick-cell" aria-describedby="slickgrid_1inventionTitle">Toy</span></div>`).join("");
    await page.setContent(`<trix-editor class="trix" aria-label="Enter query text">toy</trix-editor>
      <div id="searchResults-content"><div class="resultInfo"><span class="lQuery">L1:</span><span class="resultNumber">3</span> results found. Currently displaying all results.</div>
      <div id="search-results-table"><div class="slick-viewport" style="position:relative;height:${missing ? 50 : 75}px;overflow:auto">${rows}</div></div></div>`);
    const result = await collectPpubsRenderedResults(page, { result_set_id: "L1", rendered_query: "toy" }, dir,
      missing ? "missing" : "complete", { incrementalTimeoutMs: 80 });
    assert.equal(result.result_coverage.coverage_counting_revision, "ppubs-result-rows-v1");
    assert.equal(result.result_coverage.truncated, missing);
    assert.equal(result.result_coverage.total_hits, 3);
    assert.equal(result.result_coverage.retrieved_hits, missing ? 1 : 2);
    assert.equal(result.result_coverage.unretrieved_result_row_count, missing ? 1 : 0);
    assert.equal(result.result_coverage.stop_reason, missing ? "incremental_load_not_confirmed" : "browser_results_exhausted");
  }
});
