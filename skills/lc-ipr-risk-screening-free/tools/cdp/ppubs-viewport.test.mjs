import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright-core";
import { ppubsViewportAligned, collectPpubsRenderedResults } from "./cdp-cli.mjs";

test("short padded PPS canvas is readable only with contiguous complete loaded rows", () => {
  const value = { rows: [{}, {}], displayed_start: null, displayed_end: 2,
    result_text: "6 results found. Currently displaying all results.",
    viewport: { top: 0, height: 179, scroll_height: 179, rendered_top: 0, rendered_bottom: 50,
      positioned_row_count: 2, rows_contiguous: true } };
  assert.equal(ppubsViewportAligned(value), true);
  for (const mutation of [{ rows_contiguous: false }, { positioned_row_count: 1 },
    { rendered_top: 25 }, { top: 25 }, { scroll_height: 500 }]) {
    assert.equal(ppubsViewportAligned({ ...value, viewport: { ...value.viewport, ...mutation } }), false);
  }
  assert.equal(ppubsViewportAligned({ ...value, displayed_end: 6 }), false);
  assert.equal(ppubsViewportAligned({ ...value, displayed_end: null }), false);
});

test("small folded PPS results retain six publications without counting family expansion as pages", async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "ipr-small-pps-"));
  const browser = await chromium.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`<trix-editor class="trix" aria-label="Enter query text">test AND strap</trix-editor>
      <div id="searchResults-content"><div class="resultInfo"><span class="lQuery">L3:</span>
      <span class="resultNumber">6</span> results found. <span class="range">Currently displaying results 1 - 2.</span></div>
      <div class="srFilterSection">2 families</div><div id="search-results-table">
      <div class="slick-viewport" style="height:179px;overflow:auto;position:relative">
      <div class="grid-canvas" style="height:179px;position:relative"></div></div></div></div>`);
    await page.locator(".grid-canvas").evaluate(canvas => {
      function append(number, expanded = false) {
        const row = document.createElement("div");
        row.className = "slick-row";
        row.style.cssText = `position:absolute;height:25px;top:${canvas.children.length * 25}px`;
        row.innerHTML = `<div class="slick-cell" aria-describedby="slickgrid_123familyGroup" style="display:inline-block">${expanded ? "" : "<button>+2</button>"}</div>
          <div class="slick-cell" aria-describedby="slickgrid_123documentId" style="display:inline-block">US ${number} B2</div>
          <div class="slick-cell" aria-describedby="slickgrid_123inventionTitle" style="display:inline-block">Synthetic strap</div>`;
        canvas.append(row);
        const button = row.querySelector("button");
        button?.addEventListener("click", () => {
          if (button.textContent !== "+2") return;
          button.textContent = "-2";
          append(number + 1, true); append(number + 2, true);
          document.querySelector(".range").textContent = `Currently displaying results 1 - ${canvas.children.length}.`;
        });
      }
      append(11100000); append(11100100);
    });
    const result = await collectPpubsRenderedResults(page, { result_set_id: "L3", rendered_query: "test AND strap" },
      directory, "synthetic-small", { maxPages: 1, familyTimeoutMs: 1500 });
    assert.equal(result.candidates.length, 6);
    assert.equal(result.result_coverage.family_expansion.expanded, 2);
    assert.equal(result.result_coverage.truncated, false);
    assert.equal(result.result_pages.length, 1);
    assert.equal(result.result_pages[0].loaded_range_end, 6);
  } finally {
    await browser.close();
    await fs.rm(directory, { recursive: true });
  }
});
