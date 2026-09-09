import { requireChromeExecutable } from "./platform-runtime.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { EventEmitter } from "node:events";
import { chromium } from "playwright-core";
import { waitForSearchSemanticState, collectPpubsRenderedResults } from "./cdp-cli.mjs";
import { recordRetrievalDiagnostics } from "./retrieval-diagnostics.mjs";

async function fixture(t) {
  const browser = await chromium.launch({ executablePath: requireChromeExecutable(), headless: true });
  const page = await browser.newPage();
  await page.route("**/*", route => route.abort());
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "ipr-api-first-"));
  await fs.mkdir(path.join(dir, "screenshots"));
  t.after(async () => { await browser.close(); await fs.rm(dir, { recursive: true, force: true }); });
  return { page, dir };
}

test("PPS stale zero is not bound before this submission changes results", async t => {
  const {page, dir} = await fixture(t);
  await page.setContent(`<trix-editor class="trix" aria-label="Enter query text">toy</trix-editor>
    <button id="searchHistory-tab">History</button><button id="searchResults-tab">Results</button>
    <div id="searchResults-content"><div class="resultInfo"><span class="lQuery">L1:</span><span class="resultNumber">0</span> results found.</div>
    <div id="search-results-table"><div class="slick-viewport"></div></div></div>
    <div id="searchHistory-content"><div class="slick-viewport"><div class="slick-row"><span aria-describedby="grid_pNumber">L1</span><span data-field="queryName">toy</span><span aria-describedby="grid_numResults">0</span></div></div></div>`);
  await page.evaluate(() => { window.clicks = 0; document.querySelector("#searchHistory-tab").onclick = () => window.clicks++; });
  const config = {ppubs_query_binding:{strict:true,renderedQuery:"toy",previousResultSetId:"L1",historyScreenshotPath:path.join(dir,"history.png")},cdp:{semantic_poll_ms:15,semantic_stable_samples:2}};
  const stale = await waitForSearchSemanticState(page,"uspto_patent_browser",120,config);
  assert.equal(stale.timed_out,true); assert.equal(stale.history_binding_attempts.length,0);
  assert.equal(await page.evaluate(() => window.clicks),0);
  await page.evaluate(() => { document.querySelector(".lQuery").textContent="L2:"; document.querySelector("[aria-describedby=grid_pNumber]").textContent="L2"; });
  const fresh = await waitForSearchSemanticState(page,"uspto_patent_browser",1200,config);
  assert.equal(fresh.query_bound,true); assert.equal(fresh.history_binding.result_set_id,"L2");
});

test("PPS stops at the sample boundary and retains explicit omitted rows", async t => {
  const {page, dir} = await fixture(t);
  const rows = Array.from({length:4},(_,i)=>`<div class="slick-row"><span class="slick-cell" aria-describedby="slickgrid_1documentId">US 1140108${i} B2</span><span class="slick-cell" aria-describedby="slickgrid_1inventionTitle">Toy ${i}</span></div>`).join("");
  await page.setContent(`<trix-editor class="trix" aria-label="Enter query text">toy</trix-editor><div id="searchResults-content"><div class="resultInfo"><span class="lQuery">L1:</span><span class="resultNumber">1000</span> results found.</div><div id="search-results-table"><div class="slick-viewport" style="height:200px;overflow:auto">${rows}</div></div></div>`);
  const result=await collectPpubsRenderedResults(page,{result_set_id:"L1",rendered_query:"toy"},dir,"sample",{maxCandidates:2});
  assert.equal(result.candidates.length,2); assert.equal(result.result_coverage.stop_reason,"bounded_sample_limit");
  assert.equal(result.result_coverage.truncated,true); assert.equal(result.result_coverage.total_hits,1000);
  assert.equal(result.result_pages[0].viewports[0].omitted_visible_row_count,2);
  assert.equal(result.result_pages[0].viewports[0].rows.length,2);
});

test("bounded diagnostics never retain query tokens, response bodies or arbitrary errors",()=>{
  const page=new EventEmitter(); const trace=recordRetrievalDiagnostics(page,{limit:2});
  page.emit("requestfailed",{url:()=>"https://ppubs.uspto.gov/path?token=secret",failure:()=>({errorText:"net::ERR_ABORTED secret"})});
  page.emit("response",{url:()=>"https://ppubs.uspto.gov/path?key=secret",status:()=>429});
  page.emit("pageerror",new Error("secret"));
  const result=trace.stop(); assert.equal(result.length,2); assert.ok(!JSON.stringify(result).includes("secret"));
  assert.equal(page.listenerCount("requestfailed"),0);
});
