import { resolveChromeExecutable } from "./platform-runtime.mjs";
import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "playwright-core";

test("five-level report keeps eight sections, seven modules, original images and offline responsive layout", async (t) => {
  const required = process.env.LC_IPR_RELEASE_CHECK === "1";
  const reportPath = process.env.REPORT_ESTIMATE_HTML;
  if (!reportPath) {
    assert.ok(!required, "release requires a generated five-level report");
    t.skip("REPORT_ESTIMATE_HTML is not set");
    return;
  }
  assert.ok(fs.existsSync(reportPath), "generated five-level report is missing");
  const executablePath = resolveChromeExecutable();
  if (!executablePath) {
    assert.ok(!required, "release requires a supported system browser");
    t.skip("system browser unavailable");
    return;
  }
  const directory = path.dirname(path.resolve(reportPath));
  const data = JSON.parse(fs.readFileSync(path.join(directory, "report-data.json"), "utf8"));
  if (required) assert.equal(data.visual_policy_revision, "core-risk-evidence-v2", "release must exercise the new default visual policy");
  const figures = (blocks) => blocks.flatMap((block) => block.type === "figures"
    ? block.items : block.type === "details" ? figures(block.blocks || []) : []);
  const coreFigures = data.sections.flatMap((section) => figures(section.blocks || []));
  if (["core-risk-evidence-v1", "core-risk-evidence-v2"].includes(data.visual_policy_revision)) {
    const key = (row) => [row.scenario_id || "", row.jurisdiction, row.right_type, row.candidate_id].join("|");
    for (const section of data.sections.filter((item) => item.candidate_id)) {
      const row = data.assessments.find((item) => key(item) === key(section));
      assert.ok(row, "core section must bind an assessed candidate in its own scenario");
      assert.ok(["中", "高", "极高"].includes(row.risk), "low/pending candidates cannot enter the core gallery");
      assert.ok(row.aggregation_included !== false && !row.future_signal && !row.signal_only && !row.out_of_scope);
      for (const image of figures(section.blocks || [])) {
        assert.equal(key(image), key(section), "image must retain candidate/scenario/country/right binding");
        assert.equal(image.risk, row.risk);
      }
    }
    const fixture = data.presentation_source.release_visual_fixture;
    if (fixture) {
      assert.deepEqual([...new Set(coreFigures.map((image) => image.evidence_id))].sort(), fixture.expected_core_refs);
      assert.ok(coreFigures.length > 0, "release must show substantive candidate evidence, not only a product thumbnail");
      for (const ref of fixture.excluded_refs) assert.ok(!coreFigures.some((image) => image.evidence_id === ref));
      assert.deepEqual(data.visual_gaps, [], "qualified fixture rights images must satisfy the core roles");
      if (fixture.scenario_isolation) {
        assert.deepEqual(coreFigures.map((image) => [image.scenario_id, image.risk]).sort(),
          [["brand_reuse", "极高"], ["product_entry", "中"]]);
        assert.equal(data.overall.risk, "中", "conditional risk must not overwrite the primary scenario");
      }
    }
  }
  const screenshotDir = process.env.REPORT_SCREENSHOTS_DIR;
  if (screenshotDir) fs.mkdirSync(screenshotDir, { recursive: true });
  const browser = await chromium.launch({ executablePath, headless: true });
  try {
    for (const width of [390, 768, 1440]) {
      const page = await browser.newPage({ viewport: { width, height: 1000 } });
      const network = [];
      await page.route(/^https?:\/\//, async (route) => {
        network.push(route.request().url());
        await route.abort();
      });
      await page.context().setOffline(true);
      await page.goto(pathToFileURL(path.resolve(reportPath)).href, { waitUntil: "load" });
      const observed = await page.evaluate(() => ({
        width: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
        sections: [...document.querySelectorAll("main section.panel")].map((item) => item.id),
        modules: document.querySelectorAll("#modules .module").length,
        scripts: document.scripts.length,
        images: [...document.images].map((item) => ({ src: item.src,
          hash: item.dataset.sha256, complete: item.complete && item.naturalWidth > 0 })),
        coreImages: [...document.querySelectorAll("#visual img")].map((item) => item.dataset.sha256),
        links: [...document.querySelectorAll("a[href]")].map((item) => item.href),
      }));
      assert.deepEqual(observed.sections, ["product", "decision", "coverage", "gaps", "modules", "visual", "candidates", "trace"]);
      assert.equal(observed.modules, 7);
      assert.ok(observed.scrollWidth <= observed.width, `${width}px horizontal overflow`);
      assert.equal(observed.scripts, 0);
      assert.deepEqual(network, []);
      assert.equal(observed.images.length, data.visual_evidence.length);
      assert.deepEqual(observed.coreImages, coreFigures.map((image) => image.sha256));
      for (const image of observed.images) {
        assert.ok(image.complete, "broken image");
        assert.ok(image.src.startsWith("data:image/"), "image must be embedded");
        assert.equal(crypto.createHash("sha256").update(Buffer.from(image.src.split(",")[1], "base64")).digest("hex"), image.hash);
      }
      for (const href of observed.links) {
        if (href.startsWith("file:")) assert.ok(fs.existsSync(fileURLToPath(href)), "broken local evidence link");
      }
      if (screenshotDir) {
        await page.screenshot({ path: path.join(screenshotDir, `estimate-${width}.png`) });
        await page.locator("#visual").screenshot({ path: path.join(screenshotDir, `core-evidence-${width}.png`) });
      }
      await page.emulateMedia({ media: "print" });
      assert.equal(await page.locator("main section.panel").count(), 8);
      await page.close();
    }
  } finally {
    await browser.close();
  }
});
