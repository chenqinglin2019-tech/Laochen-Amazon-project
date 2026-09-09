import { requireChromeExecutable } from "./platform-runtime.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { chromium } from "playwright-core";

import {
  extractAfterLabel,
  extractAmazonProduct,
  collectAmazonGallery,
  collectPpubsRenderedResults,
  ppubsRenderedSnapshot,
  ppubsPublishedDocumentSnapshot,
  capturePpubsDocumentPages,
  bindPpubsResultHistory,
  waitForSearchSemanticState,
  submitSearch,
  browserRateLimited,
  parsePpubsGridRows,
  updateCandidateJournal,
  firstTsdrMarkMedia,
  parsePatentRows,
  parseTrademarkRows,
  tableRows,
} from "./cdp-cli.mjs";

const CHROME = requireChromeExecutable();

test("PPS published document captures exact pane identity and bounded rendered pages without claiming active ownership", async () => {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const fs = await import("node:fs/promises"), os = await import("node:os"), path = await import("node:path");
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "ipr-pps-doc-fixture-"));
  await fs.mkdir(path.join(dir, "screenshots"));
  try {
    const page = await browser.newPage();
    await page.setContent(`<div>Active Owner OTHER US D999999 S</div><div id="documentViewer-content">
      <div class="textViewer"><div class="realdocument"><div class="metadata meta-guid meta-inventorsInfoGroup meta-usClassCurrent"><h2 class="meta-inventionTitle">Lid strap</h2>
      <section class="meta-guid"><div>US D123456 S</div></section><section class="meta-usClassCurrent"><div>D7/391</div></section>
      <section class="meta-inventorsInfoGroup">Test; Inventor</section></div><div class="documentText">An ornamental strap.</div></div></div>
      <button data-id="switchToImage">Image</button><button data-id="switchToText">Text</button>
      <button data-id="firstPage" disabled>First</button><button data-id="nextPage">Next</button>
      <span data-id="pageNumber"><input data-id="pagetext-input" value="1"><span class="page-of">of 2</span></span>
      <div class="image-canvas-wrapper" style="width:30px;height:30px"><div class="image-holder"><img width="30" height="30"></div></div></div>`);
    await page.evaluate(() => {
      const img = document.querySelector("img"), input = document.querySelector("input");
      const pixels = color => 'data:image/svg+xml,' + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="30" height="30"><rect width="30" height="30" fill="${color}"/></svg>`);
      img.src = pixels("red");
      document.querySelector("[data-id=nextPage]").onclick = () => { input.value = "2"; img.src = pixels("blue"); };
    });
    const document = await ppubsPublishedDocumentSnapshot(page);
    assert.equal(document.page_record_number, "USD123456S");
    assert.equal(document.title, "Lid strap");
    assert.deepEqual(document.classifications, ["D7/391"]);
    assert.equal(document.legal_status, ""); assert.deepEqual(document.owners, []);
    assert.ok(!document.rendered_text.includes("OTHER"));
    const result = await capturePpubsDocumentPages(page, "USD123456S", dir, "fixture");
    assert.equal(result.media_coverage.completeness, "complete");
    assert.equal(result.document_pages.length, 2);
    assert.notEqual(result.document_pages[0].sha256, result.document_pages[1].sha256);
    assert.ok(result.evidence_images.every(item => item.role === "official_document_page"));
    assert.ok(!JSON.stringify(result).includes("data:image"));
  } finally { await browser.close(); await fs.rm(dir, { recursive: true, force: true }); }
});

test("Amazon and USPTO adapters read only rendered fixture state", async () => {
  const browser = await chromium.launch({
    executablePath: CHROME,
    headless: true,
  });
  try {
    const page = await browser.newPage();
    await page.setContent(`
      <div id="wayfinding-breadcrumbs_feature_div"><a>Office Products</a><a>Mouse Pads</a></div>
      <h1 id="productTitle">Mock Cat Paw Mouse Pad</h1>
      <a id="bylineInfo">Visit the MOCKMARK Store</a>
      <input id="ASIN" value="B0TEST1234">
      <div id="feature-bullets"><li><span class="a-list-item">Ergonomic wrist support</span></li></div>
      <button aria-checked="true">Pink</button>
      <img id="landingImage" src="https://m.media-amazon.com/images/I/mock.jpg">
      <table id="productDetails_detailBullets_sections1"><tr><th>Manufacturer</th><td>Mock Inc</td></tr></table>
    `);
    const product = await extractAmazonProduct(page);
    assert.equal(product.title, "Mock Cat Paw Mouse Pad");
    assert.equal(product.pageAsin, "B0TEST1234");
    assert.equal(product.specifications.Manufacturer, "Mock Inc");
    assert.deepEqual(product.selectedVariants, ["Pink"]);

    await page.setContent(`
      <table><tr><td>MOCKMARK</td><td>Serial Number 78787878</td><td>Mock Inc</td><td>Live / Registered</td></tr></table>
    `);
    assert.equal(parseTrademarkRows(await tableRows(page))[0].serial_number, "78787878");

    await page.setContent(`
      <table><tr><td>US-D1234567-S</td><td>Cat paw mouse pad</td><td>Issued</td><td>Mock Inc</td></tr></table>
    `);
    assert.equal(parsePatentRows(await tableRows(page))[0].record_number, "US-D1234567-S");

    assert.equal(
      extractAfterLabel("Status\nLIVE\nOwner Name\nMock Inc", ["Status"]),
      "LIVE",
    );

    await page.setContent(`
      <img id="siteLogo" width="300" height="120" alt="USPTO logo">
      <img id="markImage" width="240" height="180"
        src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='240' height='180'%3E%3Crect width='240' height='180' fill='black'/%3E%3C/svg%3E">
    `);
    const markMedia = await firstTsdrMarkMedia(page);
    assert.ok(markMedia);
    assert.equal(await markMedia.getAttribute("id"), "markImage");
  } finally {
    await browser.close();
  }
});

test("PPS 4.3 SlickGrid is parsed by named cells and bound virtual scroll evidence", async () => {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const fs = await import("node:fs/promises");
  const path = await import("node:path");
  const os = await import("node:os");
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "ipr-pps-grid-fixture-"));
  try {
    const page = await browser.newPage();
    await page.setContent(`<trix-editor class="trix" aria-label="Enter query text">(lid AND strap) AND S.KD.</trix-editor>
      <div id="searchResults-content"><div class="resultInfo"><span class="lQuery">L1:</span><span class="resultNumber">2</span> results found.</div>
      <div id="search-results-table"><div class="slick-viewport" style="height:100px;overflow:auto"><div style="height:180px">
      <div class="slick-row"><div class="slick-cell" aria-describedby="slickgrid_123select">add tag 1 to document ID: US-D123456-S</div><div class="slick-cell" aria-describedby="slickgrid_123documentId">US D123456 S</div><div class="slick-cell" aria-describedby="slickgrid_123inventionTitle">Lid strap</div><div class="slick-cell" aria-describedby="slickgrid_123rowNumber">1</div></div>
      <div class="slick-row"><div class="slick-cell" aria-describedby="slickgrid_123documentId">US D123457 S</div><div class="slick-cell" aria-describedby="slickgrid_123inventionTitle">Cover holder</div><div class="slick-cell" aria-describedby="slickgrid_123rowNumber">2</div></div>
      </div></div></div></div>`);
    const snapshot = await ppubsRenderedSnapshot(page);
    assert.equal(snapshot.total_hits, 2);
    const parsed = parsePpubsGridRows(snapshot.rows);
    assert.equal(parsed[0].title, "Lid strap");
    assert.equal(parsed[0].right_type, "design");
    await page.locator("body").evaluate(node => node.insertAdjacentHTML("beforeend", `<button id="searchHistory-tab">History</button><button id="searchResults-tab">Results</button>
      <div id="searchHistory-content"><div class="slick-viewport" style="height:20px;overflow:auto"><div style="height:200px">
      <div class="slick-row"><span aria-describedby="grid_pNumber">L1</span><span data-field="queryName">(lid AND strap) AND S.KD.</span><span aria-describedby="grid_numResults">2</span></div></div></div></div>`));
    await page.locator("#searchHistory-content .slick-viewport").evaluate(node => { node.scrollTop = 80; });
    const binding = await bindPpubsResultHistory(page, "(lid AND strap) AND S.KD.", path.join(dir, "history.png"));
    assert.equal(binding.result_set_id, "L1");
    assert.equal(await page.locator("#searchHistory-content .slick-viewport").evaluate(node => node.scrollTop), 0);
    await page.locator("#searchHistory-content .slick-viewport").evaluate(node => {
      const label = node.querySelector("[aria-describedby$=pNumber]");
      label.textContent = "L9";
      node.addEventListener("scroll", () => { label.textContent = node.scrollTop > 0 ? "L1" : "L9"; });
    });
    const reused = await bindPpubsResultHistory(page, "(lid AND strap) AND S.KD.", path.join(dir, "history-reused.png"));
    assert.equal(reused.result_set_id, "L1");
    assert.ok(await page.locator("#searchHistory-content .slick-viewport").evaluate(node => node.scrollTop) > 0);
    const result = await collectPpubsRenderedResults(page, { result_set_id: "L1", rendered_query: "(lid AND strap) AND S.KD." }, dir, "fixture");
    assert.equal(result.candidates.length, 2);
    assert.equal(result.result_coverage.truncated, false);
    assert.equal(result.result_coverage.stop_reason, "browser_results_exhausted");
    assert.equal(result.result_pages.length, 1);
    assert.ok(result.result_pages[0].viewports.length >= 2);
    await page.locator(".lQuery").evaluate(node => { node.textContent = "L2:"; });
    const changed = await collectPpubsRenderedResults(page, { result_set_id: "L1", rendered_query: "(lid AND strap) AND S.KD." }, dir, "changed");
    assert.equal(changed.result_coverage.stop_reason, "query_binding_changed");
    assert.equal(changed.candidates.length, 0);
  } finally { await browser.close(); await fs.rm(dir, { recursive: true, force: true }); }
});

test("PPS readiness retries delayed history binding without resubmitting or accepting Loading and mismatches", async () => {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const fs = await import("node:fs/promises"), os = await import("node:os"), path = await import("node:path");
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "ipr-pps-readiness-fixture-"));
  try {
    const page = await browser.newPage();
    const query = "lid AND strap AND openings";
    const config = { cdp: { semantic_poll_ms: 40, semantic_stable_samples: 2 },
      ppubs_query_binding: { strict: true, renderedQuery: query, historyTimeoutMs: 160,
        historyScreenshotPath: path.join(dir, "history.png") } };
    await page.setContent(`<trix-editor class="trix" aria-label="Enter query text">${query}</trix-editor>
      <button id="submit">Search</button><button id="searchHistory-tab">History</button><button id="searchResults-tab">Results</button>
      <div id="searchResults-content"><div class="resultInfo"><span class="lQuery">L1:</span><span class="resultNumber">1</span> results found.</div>
      <div id="loading">Loading...</div><div id="search-results-table"><div class="slick-viewport"></div></div></div>
      <div id="searchHistory-content"><div class="slick-viewport"><div class="slick-row">
      <span aria-describedby="grid_pNumber">L1</span><span data-field="queryName">${query}</span><span aria-describedby="grid_numResults">Loading...</span>
      </div></div></div>`);
    await page.evaluate(() => {
      window.submits = 0; window.earlyHistoryClicks = 0;
      document.querySelector("#submit").onclick = () => window.submits++;
      document.querySelector("#searchHistory-tab").onclick = () => {
        if (document.querySelector("#loading")) window.earlyHistoryClicks++;
      };
      setTimeout(() => {
        document.querySelector("#loading").remove();
        document.querySelector("#search-results-table .slick-viewport").innerHTML = `<div class="slick-row">
          <div class="slick-cell" aria-describedby="slickgrid_123documentId">US 11401089 B2</div>
          <div class="slick-cell" aria-describedby="slickgrid_123inventionTitle">Lid strap</div></div>`;
      }, 300);
      setTimeout(() => { document.querySelector("[aria-describedby=grid_numResults]").textContent = "1"; }, 780);
    });
    const result = await waitForSearchSemanticState(page, "uspto_patent_browser", 2200, config);
    assert.equal(result.stable, true);
    assert.equal(result.query_bound, true);
    assert.equal(result.history_binding.query, query);
    assert.ok(result.history_binding_attempts.length >= 2);
    assert.equal(result.history_binding_attempts[0].bound, false);
    assert.ok(await fs.stat(result.history_binding.screenshot_path));
    assert.deepEqual(await page.evaluate(() => [window.submits, window.earlyHistoryClicks]), [0, 0]);

    await page.locator("[aria-describedby=grid_numResults]").evaluate(node => { node.textContent = "2"; });
    const mismatch = await waitForSearchSemanticState(page, "uspto_patent_browser", 400, config);
    assert.equal(mismatch.stable, false); assert.equal(mismatch.query_bound, false);
    assert.equal(mismatch.timed_out, true);
    await page.locator("[data-field=queryName]").evaluate(node => { node.textContent = "other AND query"; });
    const wrongQuery = await waitForSearchSemanticState(page, "uspto_patent_browser", 300, config);
    assert.equal(wrongQuery.stable, false); assert.equal(wrongQuery.query_bound, false);

    await page.locator("#searchResults-content").evaluate(node => {
      node.querySelector(".resultNumber").textContent = "0";
      node.insertAdjacentHTML("beforeend", "<div>Loading...</div>");
    });
    const loading = await waitForSearchSemanticState(page, "uspto_patent_browser", 220, config);
    assert.equal(loading.timed_out, true); assert.equal(loading.stable, false);
    assert.equal(loading.history_binding_attempts.length, 0);
    assert.equal(loading.ppubs.loading, true); assert.equal(loading.noResult, false);
  } finally { await browser.close(); await fs.rm(dir, { recursive: true, force: true }); }
});

test("PPS waits for delayed bottom auto-load without a Next button and preserves bounded gaps", async () => {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const fs = await import("node:fs/promises"), os = await import("node:os"), path = await import("node:path");
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "ipr-pps-incremental-fixture-"));
  try {
    const page = await browser.newPage();
    async function fixture(total, load, delay = 700) {
      await page.setContent(`<trix-editor class="trix" aria-label="Enter query text">lid AND strap</trix-editor>
        <div id="searchResults-content"><div class="resultInfo"><span class="lQuery">L1:</span><span class="resultNumber">${total}</span> results found. <span class="range">Currently displaying results 1 - 1.</span></div>
        <div id="search-results-table"><div class="slick-viewport" style="height:40px;overflow:auto"><div style="height:70px">
        <div class="slick-row"><div class="slick-cell" aria-describedby="slickgrid_123documentId">US 11401089 B2</div><div class="slick-cell" aria-describedby="slickgrid_123inventionTitle">Lid strap</div></div>
        </div></div></div></div>`);
      if (load) await page.locator(".slick-viewport").evaluate((node, { maximum, delayMs }) => {
        let pending = false, count = 1;
        node.addEventListener("scroll", () => {
          if (pending || count >= maximum || node.scrollTop + node.clientHeight < node.scrollHeight - 1) return;
          pending = true;
          setTimeout(() => {
            count++;
            node.firstElementChild.insertAdjacentHTML("beforeend", `<div class="slick-row"><div class="slick-cell" aria-describedby="slickgrid_123documentId">US ${11401088 + count} B2</div><div class="slick-cell" aria-describedby="slickgrid_123inventionTitle">Loaded strap ${count}</div></div>`);
            node.firstElementChild.style.height = `${70 * count}px`;
            document.querySelector(".range").textContent = `Currently displaying results 1 - ${count}.`;
            pending = false;
          }, delayMs);
        });
      }, { maximum: total, delayMs: delay });
    }
    const expected = { result_set_id: "L1", rendered_query: "lid AND strap" };
    await fixture(3, true);
    const complete = await collectPpubsRenderedResults(page, expected, dir, "delayed", { incrementalTimeoutMs: 2500 });
    assert.equal(complete.candidates.length, 3);
    assert.equal(complete.result_coverage.truncated, false);
    assert.equal(complete.result_pages.length, 3);
    await fixture(3, true, 0);
    const fast = await collectPpubsRenderedResults(page, expected, dir, "fast", { incrementalTimeoutMs: 2500 });
    assert.equal(fast.candidates.length, 3);
    assert.equal(fast.result_pages.length, 3);
    assert.equal(fast.result_coverage.truncated, false);
    await fixture(3, false);
    const stalled = await collectPpubsRenderedResults(page, expected, dir, "stalled", { incrementalTimeoutMs: 500 });
    assert.equal(stalled.result_coverage.stop_reason, "incremental_load_not_confirmed");
    assert.equal(stalled.candidates.length, 1);
    await fixture(9, true);
    const bounded = await collectPpubsRenderedResults(page, expected, dir, "bounded", { maxPages: 2, incrementalTimeoutMs: 2500 });
    assert.equal(bounded.result_pages.length, 2);
    assert.equal(bounded.candidates.length, 2);
    assert.equal(bounded.result_coverage.stop_reason, "browser_page_limit_8");
    assert.equal(bounded.result_coverage.truncated, true);
  } finally { await browser.close(); await fs.rm(dir, { recursive: true, force: true }); }
});

test("PPS expands only visible named +N family controls and retains all identified publications", async () => {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const fs = await import("node:fs/promises"), os = await import("node:os"), path = await import("node:path");
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "ipr-pps-family-fixture-"));
  try {
    const page = await browser.newPage();
    await page.setContent(`<button>+2 unrelated</button><trix-editor class="trix" aria-label="Enter query text">(Armanda AND Hughes).INV.</trix-editor>
      <div id="searchResults-content"><div class="resultInfo"><span class="lQuery">L7:</span><span class="resultNumber">3</span> results found.</div>
      <div id="search-results-table"><div class="slick-viewport" style="height:150px;overflow:auto"><div>
      <div class="slick-row"><div class="slick-cell" aria-describedby="slickgrid_123familyGroup"><button>+2</button></div><div class="slick-cell" aria-describedby="slickgrid_123documentId">US 20190315539 A1</div><div class="slick-cell" aria-describedby="slickgrid_123familyIdentifierCur">68160905</div><div class="slick-cell" aria-describedby="slickgrid_123inventionTitle">Lid securing device</div></div>
      </div></div></div></div>`);
    await page.locator("[aria-describedby$='familyGroup'] button").evaluate(node => node.addEventListener("click", () => {
      node.textContent = "-2";
      for (const number of ["US 11401089 B2", "US 11800001 B2"]) node.closest(".slick-row").parentElement.insertAdjacentHTML("beforeend", `<div class="slick-row"><div class="slick-cell" aria-describedby="slickgrid_123documentId">${number}</div><div class="slick-cell" aria-describedby="slickgrid_123familyIdentifierCur">68160905</div><div class="slick-cell" aria-describedby="slickgrid_123inventionTitle">Lid securing device</div></div>`);
    }));
    const result = await collectPpubsRenderedResults(page, { result_set_id: "L7", rendered_query: "(Armanda AND Hughes).INV." }, dir, "family", { familyTimeoutMs: 1500 });
    assert.equal(result.candidates.length, 3);
    assert.equal(result.result_coverage.family_expansion.expanded, 1);
    assert.equal(result.result_coverage.truncated, false);
    assert.ok(result.candidates.every(candidate => candidate.family_members.includes("US11401089B2")));
    await page.locator("[aria-describedby$='familyGroup'] button").evaluate(node => { node.textContent = "+2"; node.replaceWith(node.cloneNode(true)); });
    await page.locator(".resultNumber").evaluate(node => { node.textContent = "5"; });
    const blocked = await collectPpubsRenderedResults(page, { result_set_id: "L7", rendered_query: "(Armanda AND Hughes).INV." }, dir, "unconfirmed", { familyTimeoutMs: 500, incrementalTimeoutMs: 500 });
    assert.equal(blocked.result_coverage.stop_reason, "family_members_unretrieved");
    assert.equal(blocked.result_coverage.family_expansion.gaps[0].reason, "family_expansion_not_confirmed");
    await page.locator(".resultNumber").evaluate(node => { node.textContent = "7"; });
    const mixed = await collectPpubsRenderedResults(page, { result_set_id: "L7", rendered_query: "(Armanda AND Hughes).INV." }, dir, "mixed-gap", { familyTimeoutMs: 350, incrementalTimeoutMs: 350 });
    assert.equal(mixed.result_coverage.stop_reason, "result_rows_and_family_members_unretrieved");
    assert.equal(mixed.result_coverage.unretrieved_document_count, 4);
    assert.equal(mixed.result_coverage.unconfirmed_family_member_count, 2);
  } finally { await browser.close(); await fs.rm(dir, { recursive: true, force: true }); }
});

test("PPS preserves pre-expansion rows and restores a delayed virtual scroll anchor without selecting documents", async () => {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const fs = await import("node:fs/promises"), os = await import("node:os"), path = await import("node:path");
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "ipr-pps-anchor-fixture-"));
  try {
    const page = await browser.newPage();
    await page.setContent(`<trix-editor class="trix" aria-label="Enter query text">lid AND strap</trix-editor>
      <div id="searchResults-content"><div class="resultInfo"><span class="lQuery">L1:</span><span class="resultNumber">11</span> results found.</div>
      <div id="search-results-table"><div class="slick-viewport" style="height:75px;width:600px;overflow:auto"><div id="canvas" style="position:relative;height:250px"></div></div></div></div>`);
    await page.evaluate(() => {
      const viewport = document.querySelector(".slick-viewport"), canvas = document.querySelector("#canvas");
      const records = Array.from({length:10}, (_, i) => 100001 + i);
      let expanded = false, pending;
      window.documentSelections = 0;
      function render() {
        const start = Math.max(0, Math.floor(viewport.scrollTop / 25) - 2), end = Math.min(records.length, start + 7);
        canvas.innerHTML = records.slice(start, end).map((number, n) => `<div class="slick-row" style="position:absolute;top:${(start+n)*25}px;height:25px;width:600px">
          <div class="slick-cell" style="display:inline-block;width:100px" aria-describedby="slickgrid_123familyGroup">${number === 100002 ? `<button>${expanded ? '-1' : '+1'}</button>` : ''}</div>
          <div class="slick-cell" style="display:inline-block;width:150px" aria-describedby="slickgrid_123documentId">US ${number} B2</div>
          <div class="slick-cell" style="display:inline-block" aria-describedby="slickgrid_123rowNumber">${start+n+1}</div>
          <div class="slick-cell" style="display:inline-block" aria-describedby="slickgrid_123inventionTitle">Lid strap ${number}</div></div>`).join('');
        canvas.querySelectorAll("[aria-describedby$=familyGroup]").forEach(cell => cell.onclick = e => {
          if (e.target === cell) window.documentSelections++;
        });
        const button = canvas.querySelector("button");
        if (button && !expanded) button.onclick = () => {
          expanded = true; records.splice(2, 0, 100011); canvas.style.height = '275px';
          viewport.scrollTop = 75; render();
        };
      }
      viewport.onscroll = () => { clearTimeout(pending); pending = setTimeout(render, 450); };
      render();
    });
    const result = await collectPpubsRenderedResults(page, { result_set_id: "L1", rendered_query: "lid AND strap" }, dir, "anchor", { familyTimeoutMs: 1500, incrementalTimeoutMs: 500 });
    assert.equal(result.candidates.length, 11);
    assert.equal(result.result_coverage.truncated, false);
    assert.ok(result.candidates.some(row => row.record_number === 'US100001B2'));
    assert.equal(result.result_pages[0].viewports[0].viewport.top, 0);
    assert.equal(result.result_pages[0].viewports[0].rows[0].rowNumber, "1");
    assert.equal(await page.evaluate(() => window.documentSelections), 0);
  } finally { await browser.close(); await fs.rm(dir, {recursive:true, force:true}); }
});

test("PPS rate-limit modal blocks preparation without dismissal or query and stops collection", async () => {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const fs = await import("node:fs/promises"), os = await import("node:os"), path = await import("node:path");
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "ipr-pps-rate-fixture-"));
  try {
    const page = await browser.newPage();
    await page.setContent(`<div role="dialog"><h2>Too Many Requests</h2><p>There are too many requests in your user session. Please try your request again later.</p><button>OK</button></div>
      <div id="search-results-table"><div class="slick-viewport"></div></div>`);
    await page.evaluate(() => { window.dialogClicks = 0; document.querySelector('button').onclick = () => window.dialogClicks++; });
    assert.equal(browserRateLimited(await page.locator('body').innerText()), true);
    assert.equal(browserRateLimited('A rate-limited actuator and rate limiting controller'), false);
    await assert.rejects(() => submitSearch(page, 'lid AND strap', 'uspto_patent_browser', {strict:true}), error => {
      assert.equal(error.code, 'BROWSER_RATE_LIMITED'); assert.equal(error.submission_state, 'not_submitted'); return true;
    });
    const result = await collectPpubsRenderedResults(page, {result_set_id:'L1', rendered_query:'lid AND strap'}, dir, 'rate');
    assert.equal(result.result_coverage.stop_reason, 'BROWSER_RATE_LIMITED');
    assert.equal(result.result_coverage.truncated, true);
    assert.equal(await page.evaluate(() => window.dialogClicks), 0);
  } finally { await browser.close(); await fs.rm(dir, {recursive:true, force:true}); }
});

test("strict patent journal keeps interrupted pending entries and published-only outcomes unresolved", async () => {
  const fs = await import("node:fs/promises"), os = await import("node:os"), path = await import("node:path");
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "ipr-pps-journal-fixture-"));
  try {
    await fs.writeFile(path.join(dir, "task.json"), JSON.stringify({ task_id: "T-fixture" }));
    const identity = { provider: "uspto_patent_browser", record_number: "US11401089B2", right_type: "patent", query_id: "Q-fixture" };
    const file = await updateCandidateJournal(dir, { ...identity, status: "pending", phase: "retrieve_published_document" });
    assert.equal(JSON.parse(await fs.readFile(file)).entries[0].status, "pending");
    await updateCandidateJournal(dir, { ...identity, status: "access_limited", authority_scope: "published_document_only", document_retrieval_status: "success", error_code: "MISSING_OFFICIAL_CURRENT_STATUS" });
    const entry = JSON.parse(await fs.readFile(file)).entries[0];
    assert.equal(entry.status, "access_limited");
    assert.equal(entry.document_retrieval_status, "success");
    const source = await fs.readFile(new URL("./cdp-cli.mjs", import.meta.url), "utf8");
    const strict = source.split("async function verifyPpubsPublishedDocument(")[1].split("async function verifyCandidate(")[0];
    assert.equal((strict.match(/await updateCandidateJournal\(/g) || []).length, 2);
  } finally { await fs.rm(dir, { recursive: true, force: true }); }
});

test("strict Amazon capture excludes unrelated controls and binds each gallery slot's visible image", async () => {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  try {
    const page = await browser.newPage();
    const pixel = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20'%3E%3Crect width='20' height='20'/%3E%3C/svg%3E";
    await page.setContent(`<input id="ASIN" value="B0TEST1234"><div id="variation_color_name"><span class="selection">Blue/Grey</span></div>
      <button aria-checked="true">Captions off</button><button class="a-button-selected">$12.99</button>
      <div id="main-image-container"><img id="landingImage" data-mb-pv-slot-index="0" data-a-image-name="landingImage" width="20" height="20" data-old-hires="https://m.media-amazon.com/images/I/first.jpg" src="${pixel}">
      <img id="second" style="display:none" data-mb-pv-slot-index="1" data-a-image-name="mbAltImage" width="20" height="20" data-old-hires="https://m.media-amazon.com/images/I/second.jpg" src="${pixel}"></div>
      <ul id="altImages"><li class="imageThumbnail" data-csa-c-posx="0"><button aria-checked="true">one</button></li><li class="imageThumbnail" data-csa-c-posx="1"><button aria-checked="false">two</button></li></ul>`);
    await page.evaluate(() => document.querySelectorAll("#altImages li").forEach((item, index) => item.addEventListener("click", () => {
      document.querySelectorAll("#altImages button").forEach((button, i) => button.setAttribute("aria-checked", String(i === index)));
      document.querySelectorAll("#main-image-container img").forEach((image, i) => { image.style.display = i === index ? "block" : "none"; });
    })));
    assert.deepEqual((await extractAmazonProduct(page, { strict: true })).selectedVariants, ["Blue/Grey"]);
    const gallery = await collectAmazonGallery(page, "B0TEST1234", 12, { strict: true });
    assert.equal(gallery.observed.length, 2);
    assert.equal(gallery.failures.length, 0);
    assert.match(gallery.observed[1].source_url, /second\.jpg$/);
    assert.match((await extractAmazonProduct(page, { strict: true })).imageUrl, /second\.jpg$/);
  } finally { await browser.close(); }
});
