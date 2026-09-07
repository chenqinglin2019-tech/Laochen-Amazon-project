import test from "node:test";
import assert from "node:assert/strict";
import { plannedReadingScope, capturePpubsDocumentPages } from "./cdp-cli.mjs";

const task = { workflow_correction_revision: "workflow-correction-v1" };
test("minimal reading contract is exact and legacy remains unchanged", () => {
  assert.equal(plannedReadingScope({}, {}), null);
  const entry = { ...task, required_facts: ["abstract"], reading_scope: { level: "abstract" } };
  assert.deepEqual(plannedReadingScope(entry, task), { required_facts: ["abstract"], reading_scope: { level: "abstract", page_numbers: [] } });
  assert.throws(() => plannedReadingScope({ ...entry, required_facts: ["representative_figures"] }, task));
  assert.throws(() => plannedReadingScope({ ...entry, required_facts: ["abstract", "abstract"] }, task));
  assert.throws(() => plannedReadingScope({ ...entry, workflow_correction_revision: undefined }, task));
  assert.deepEqual(plannedReadingScope({ ...entry, required_facts: ["representative_figures"], reading_scope: { level: "representative_figures", page_numbers: [3, 5] } }, task).reading_scope.page_numbers, [3, 5]);
});

test("representative page scope captures only requested page and does not claim full PDF", async () => {
  const { chromium } = await import("playwright-core");
  const fs = await import("node:fs/promises"), os = await import("node:os"), path = await import("node:path");
  const browser = await chromium.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "ipr-reading-fixture-"));
  try {
    await fs.mkdir(path.join(dir, "screenshots"));
    const page = await browser.newPage();
    await page.route("**/*", route => route.abort());
    await page.setContent(`<div id="documentViewer-content"><button data-id="switchToImage">Image</button><button data-id="switchToText">Text</button>
      <button data-id="firstPage" disabled>First</button><button data-id="nextPage">Next</button>
      <span data-id="pageNumber"><input data-id="pagetext-input" value="1"><span class="page-of">of 7</span></span>
      <div class="image-canvas-wrapper" style="width:30px;height:30px"><div class="image-holder"><img width="30" height="30"></div></div></div>`);
    await page.evaluate(() => {
      const img = document.querySelector("img"), input = document.querySelector("input");
      const pixels = color => "data:image/svg+xml," + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="30" height="30"><rect width="30" height="30" fill="${color}"/></svg>`);
      img.src = pixels("red");
      input.addEventListener("keydown", event => { if (event.key === "Enter") img.src = pixels(input.value === "3" ? "blue" : "green"); });
      document.querySelector("[data-id=nextPage]").onclick = () => { throw new Error("must not traverse unrequested pages"); };
    });
    const result = await capturePpubsDocumentPages(page, "US11401089B2", dir, "fixture", { pageNumbers: [3] });
    assert.deepEqual(result.document_pages.map(item => item.page), [3]);
    assert.equal(result.media_coverage.requested_pages_complete, true);
    assert.equal(result.media_coverage.completeness, "partial");
    assert.equal(result.evidence_images.length, 1);
  } finally { await browser.close(); await fs.rm(dir, { recursive: true, force: true }); }
});
