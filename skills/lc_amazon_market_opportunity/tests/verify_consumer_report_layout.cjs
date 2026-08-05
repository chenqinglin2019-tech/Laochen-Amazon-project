#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { pathToFileURL } = require("url");
let playwright;
try {
  playwright = require("playwright");
} catch (playwrightError) {
  try {
    // playwright-core is sufficient because this verifier supplies the local
    // Chrome executable explicitly and does not need downloaded browsers.
    playwright = require("playwright-core");
  } catch (coreError) {
    const bundled = path.resolve(path.dirname(process.execPath), "../node_modules/playwright");
    if (!fs.existsSync(bundled)) {
      throw new Error(
        "playwright is unavailable; use the bundled Codex Node runtime or set " +
        `NODE_PATH (${playwrightError.message}; ${coreError.message})`
      );
    }
    playwright = require(bundled);
  }
}
const { chromium } = playwright;

async function main() {
  const reportArg = process.argv[2];
  const outputArg = process.argv[3];
  if (!reportArg) {
    throw new Error("usage: verify_consumer_report_layout.cjs REPORT.html [OUTPUT_DIR]");
  }
  const reportPath = path.resolve(reportArg);
  if (!fs.existsSync(reportPath)) {
    throw new Error(`report not found: ${reportPath}`);
  }
  const outputDir = outputArg ? path.resolve(outputArg) : null;
  if (outputDir) fs.mkdirSync(outputDir, { recursive: true });
  const executablePath = process.env.LCADMO_CHROME_EXECUTABLE ||
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
  const launchOptions = { headless: true };
  if (fs.existsSync(executablePath)) launchOptions.executablePath = executablePath;
  const browser = await chromium.launch(launchOptions);
  const results = [];
  try {
    for (const width of [1440, 768, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 1000 } });
      await page.goto(pathToFileURL(reportPath).href, { waitUntil: "load" });
      const metrics = await page.evaluate(() => {
        const interfaceRoot = document.body.cloneNode(true);
        // A consumer may literally say "after 90 days".  Window vocabulary is
        // forbidden in the report UI, not censored from quoted source material.
        interfaceRoot.querySelectorAll("blockquote").forEach((node) => node.remove());
        return {
          clientWidth: document.documentElement.clientWidth,
          scrollWidth: document.documentElement.scrollWidth,
          interfaceText: interfaceRoot.innerText,
          externalResources: Array.from(document.querySelectorAll("script[src],link[href],img[src]"))
            .map((node) => node.getAttribute("src") || node.getAttribute("href"))
            .filter((value) => value && !value.startsWith("data:") && !value.startsWith("#")),
        };
      });
      if (metrics.scrollWidth > metrics.clientWidth) {
        throw new Error(`${width}px has horizontal overflow: ${metrics.scrollWidth}>${metrics.clientWidth}`);
      }
      const interfaceTextFolded = metrics.interfaceText.toLocaleLowerCase("en-US");
      for (const forbidden of [
        "来源状态",
        "证据ID",
        "证据 ID",
        "证据类型计数",
        "evidence_insufficient",
        "置信度",
        "confidence",
        "category_30d",
        "segment_1_90d",
        "segment_2_90d",
        "segment_3_90d",
        "recent_30d",
        "union_mixed_window",
        "N_category_30d",
        "N_segment_1_90d",
        "N_segment_2_90d",
        "N_segment_3_90d",
        "混合窗口",
        "同窗口对比",
      ]) {
        if (interfaceTextFolded.includes(forbidden.toLocaleLowerCase("en-US"))) {
          throw new Error(`${width}px exposes forbidden label: ${forbidden}`);
        }
      }
      for (const [label, pattern] of [
        ["30/90 day research window", /(?:30|90)[\s\u00a0]*(?:天|days?)/i],
        ["30/90 mixed-window notation", /30\s*[/／-]\s*90/i],
      ]) {
        if (pattern.test(metrics.interfaceText)) {
          throw new Error(`${width}px exposes forbidden label: ${label}`);
        }
      }
      if (metrics.externalResources.length) {
        throw new Error(`${width}px contains external resources: ${metrics.externalResources.join(", ")}`);
      }
      if (outputDir) {
        await page.screenshot({ path: path.join(outputDir, `report-${width}.png`), fullPage: true });
      }
      results.push({ width, clientWidth: metrics.clientWidth, scrollWidth: metrics.scrollWidth });
      await page.close();
    }
    const printPage = await browser.newPage();
    await printPage.goto(pathToFileURL(reportPath).href, { waitUntil: "load" });
    const pdfPath = outputDir ? path.join(outputDir, "report-a4.pdf") : undefined;
    const pdf = await printPage.pdf({ format: "A4", printBackground: true, path: pdfPath });
    if (pdf.length < 1000) throw new Error("A4 PDF output is unexpectedly empty");
    results.push({ print: "A4", pdfBytes: pdf.length });
    await printPage.close();
  } finally {
    await browser.close();
  }
  process.stdout.write(JSON.stringify({ status: "passed", reportPath, results }, null, 2) + "\n");
}

main().catch((error) => {
  process.stderr.write(JSON.stringify({ status: "failed", error: String(error.message || error) }) + "\n");
  process.exitCode = 1;
});
