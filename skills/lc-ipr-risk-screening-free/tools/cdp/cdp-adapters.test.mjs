import test from "node:test";
import assert from "node:assert/strict";
import { chromium } from "playwright-core";

import {
  extractAfterLabel,
  extractAmazonProduct,
  parsePatentRows,
  parseTrademarkRows,
  tableRows,
} from "./cdp-cli.mjs";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

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
  } finally {
    await browser.close();
  }
});
