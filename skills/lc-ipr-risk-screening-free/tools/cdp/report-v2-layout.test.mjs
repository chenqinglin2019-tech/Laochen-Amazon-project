import { chromeCandidates as detectedChromeCandidates } from "./platform-runtime.mjs";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { chromium } from "playwright-core";




test("report v2 has responsive viewports and printable excluded candidates", async (t) => {
  const required = process.env.LC_IPR_RELEASE_CHECK === "1";
  const reportPath = process.env.REPORT_V2_HTML;
  if (!reportPath) {
    assert.ok(!required, "release requires a generated legacy report");
    t.skip("REPORT_V2_HTML is not set; generated-report browser acceptance was not requested");
    return;
  }
  assert.ok(fs.existsSync(reportPath), `missing generated report: ${reportPath}`);
  const executablePath = detectedChromeCandidates().filter(candidate => fs.existsSync(candidate))[0];
  if (!executablePath) {
    assert.ok(!required, "release requires a supported system browser");
    t.skip(`no supported system Chrome executable on ${os.platform()}`);
    return;
  }

  let browser;
  try {
    browser = await chromium.launch({ executablePath, headless: true });
  } catch (error) {
    if (required) throw error;
    t.diagnostic(`system Chrome could not launch safely: ${error.message}`);
    t.skip("system Chrome unavailable");
    return;
  }

  try {
    const reportUrl = pathToFileURL(path.resolve(reportPath)).href;
    for (const width of [390, 768, 1440]) {
      const page = await browser.newPage({ viewport: { width, height: 1000 } });
      await page.goto(reportUrl, { waitUntil: "load" });
      const layout = await page.evaluate(() => ({
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
        sectionCount: document.querySelectorAll("main section.panel").length,
      }));
      assert.equal(layout.sectionCount, 8, `${width}px must render all eight report sections`);
      assert.ok(
        layout.scrollWidth <= layout.clientWidth,
        `${width}px page overflow: ${layout.scrollWidth} > ${layout.clientWidth}`,
      );
      await page.close();
    }

    const printPage = await browser.newPage({ viewport: { width: 794, height: 1123 } });
    await printPage.goto(reportUrl, { waitUntil: "load" });
    const printCopy = printPage.locator("[data-print-excluded-count]");
    assert.equal(await printCopy.isVisible(), false, "print-only candidates must stay hidden on screen");
    await printPage.emulateMedia({ media: "print" });
    assert.equal(await printPage.locator("details.fold").isVisible(), false, "screen details must be hidden in print");
    assert.equal(await printCopy.isVisible(), true, "excluded candidates must be visible in print");
    assert.ok(
      await printCopy.locator("tbody tr").count() > 0,
      "print-only excluded-candidate table must be complete",
    );
    await printPage.close();
  } finally {
    await browser.close();
  }
});
