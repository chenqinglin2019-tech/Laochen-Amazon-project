import { requireChromeExecutable } from "./platform-runtime.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { chromium } from "playwright-core";
import { browserPlannedQuery, parseTrademarkCards, parseTrademarkDetail, tmsearchResultBinding, waitForSearchSemanticState } from "./cdp-cli.mjs";

const CARD = `Check to tag for 88418732\nWordmark\nwordmark\nLID LATCH\nStatus\nDEADABANDONED\nGoods & services\nIC 021: A device used to secure a lid and for storage purposes.\nClass\n021\nSerial\n88418732\nOwners\n49th And Monroe (LIMITED LIABILITY COMPANY; NEW YORK, USA)`;
const ROW = { jurisdiction:"US", right_type:"trademark_word", operation:"trademark_recall", q:"Lid Latch", filters:{field:"ocr",language:"en"}, strategy:"phrase" };
const DETAIL = `Search result details for serial number 88418732\nTrademark\nWordmark\n\nLID LATCH\n\nSerial number\n\n88418732\n\nRegistration number\nN/A\nFiling date\n2019-05-07\nStatus\nDEADABANDONED\nStatus date\n2020-02-19\nClass\n021\nTM5 Status\nDEAD/APPLICATION\nGoods and services\nIC 021: A device used to secure a lid and for storage purposes.\nCurrent owner\n49th And Monroe\nOwnership transitions\nNo assignments`;

test("TM compiler binds new field-tag rows without rewriting legacy phrase rows", () => {
  assert.equal(browserPlannedQuery("uspto_tmsearch_browser", ROW).rendered_query, '"Lid Latch"');
  const compiled = browserPlannedQuery("uspto_tmsearch_browser", {...ROW, query_compiler_revision:"tm-field-tags-v1"});
  assert.equal(compiled.rendered_query, 'CM:"Lid Latch"');
  assert.equal(compiled.search_mode, "field_tag");
  assert.throws(() => browserPlannedQuery("uspto_tmsearch_browser", {...ROW,query_compiler_revision:"unknown"}));
  assert.throws(() => browserPlannedQuery("uspto_tmsearch_browser", {...ROW,q:'Lid" OR *',query_compiler_revision:"tm-field-tags-v1"}));
});

test("TM visible cards bind each mark to repeated serial and preserve labels", () => {
  const rows = parseTrademarkCards(CARD + '\n' + CARD);
  assert.equal(rows.length,1);
  assert.equal(rows[0].mark_text,"LID LATCH");
  assert.equal(rows[0].serial_number,"88418732");
  assert.deepEqual(rows[0].nice_classes,["021"]);
  assert.match(rows[0].goods_services[0],/secure a lid/);
  assert.match(rows[0].owner,/49th And Monroe/);
  assert.deepEqual(parseTrademarkCards(CARD.replace("Serial\n88418732","Serial\n99999999")),[]);
  assert.deepEqual(parseTrademarkCards("9 results for test\n88418732"),[]);
});

test("TM field-tag results reject stale query, wrong mode and unrelated zero", () => {
  const q='CM:"Lid Latch"';
  assert.equal(tmsearchResultBinding(`1 results for ${q}`,q,"Field tag and Search builder",q).query_bound,true);
  assert.equal(tmsearchResultBinding(`1 results for "${q}"`,q,"Field tag and Search builder",q).query_bound,true);
  assert.equal(tmsearchResultBinding(`1 results for ${q}`,q,"Wordmark",q).query_bound,false);
  assert.equal(tmsearchResultBinding('0 results for "other"',q,"Field tag and Search builder",q).query_bound,false);
  assert.equal(tmsearchResultBinding(`1 results for ${q}`,"changed","Field tag and Search builder",q).query_bound,false);
  assert.equal(tmsearchResultBinding(`Result 1 of 1 for ${q}`,q,"Field tag and Search builder",q).query_bound,true);
  assert.equal(tmsearchResultBinding(`Result 1 of 12 for ${q}`,q,"Field tag and Search builder",q).query_bound,false);
  assert.equal(tmsearchResultBinding('Result 1 of 1 for 88418732',q,"Field tag and Search builder",q).query_bound,false);
});

test("TM single-result detail requires route, repeated serial, rendered mark and loaded status", () => {
  const url='https://tmsearch.uspto.gov/search/search-results/88418732';
  const [row]=parseTrademarkDetail(DETAIL,url);
  assert.equal(row.serial_number,'88418732'); assert.equal(row.mark_text,'LID LATCH');
  assert.equal(row.status,'DEADABANDONED'); assert.deepEqual(row.nice_classes,['021']);
  assert.equal(row.goods_services_truncated,false); assert.match(row.goods_services[0],/secure a lid/);
  assert.deepEqual(parseTrademarkDetail(DETAIL,url.replace('88418732','99999999')),[]);
  assert.deepEqual(parseTrademarkDetail(DETAIL.replace('Serial number\n\n88418732','Serial number\n\n99999999'),url),[]);
  assert.deepEqual(parseTrademarkDetail(DETAIL.replace('DEADABANDONED',''),url),[]);
  assert.deepEqual(parseTrademarkDetail(DETAIL,'http://%'),[]);
});

test("TM semantic readiness reads cards in verified field-tag mode", async () => {
  const browser=await chromium.launch({executablePath:requireChromeExecutable(),headless:true});
  try {
    const page=await browser.newPage();
    await page.setContent(`<mat-select formcontrolname="searchRefinement">Field tag and Search builder</mat-select><input id="searchbar"><pre id="results"></pre>`);
    const q='CM:"Lid Latch"';
    await page.locator("#searchbar").fill(q);
    await page.locator("#results").evaluate((e,text)=>{e.textContent=text;},`1 results for ${q}\n${CARD}`);
    const found=await waitForSearchSemanticState(page,"uspto_tmsearch_browser",1000,{tmsearch_query_binding:{tmsearchQuery:q},cdp:{semantic_poll_ms:10,semantic_stable_samples:2}});
    assert.equal(found.stable,true);assert.equal(found.candidates.length,1);assert.equal(found.query_bound,true);
    assert.equal(found.tmsearch_binding.loading,false);assert.equal(found.tmsearch_binding.parsed_count,1);
    await page.locator('#results').evaluate((e,text)=>{e.textContent=text;},`0 results for ${q}\n${CARD}`);
    const conflicting=await waitForSearchSemanticState(page,"uspto_tmsearch_browser",80,{tmsearch_query_binding:{tmsearchQuery:q},cdp:{semantic_poll_ms:10,semantic_stable_samples:2}});
    assert.equal(conflicting.stable,false);assert.equal(conflicting.noResult,false);
    await page.locator('#results').evaluate((e,text)=>{e.textContent=text;},`1 results for ${q}\n${CARD}`);
    await page.locator('body').evaluate(e=>e.insertAdjacentHTML('beforeend','<div role="progressbar">Loading...</div>'));
    const loading=await waitForSearchSemanticState(page,"uspto_tmsearch_browser",80,{tmsearch_query_binding:{tmsearchQuery:q},cdp:{semantic_poll_ms:10,semantic_stable_samples:2}});
    assert.equal(loading.stable,false);assert.equal(loading.tmsearch_binding.loading,true);
    await page.locator('[role=progressbar]').evaluate(e=>e.remove());
    const legacy=await waitForSearchSemanticState(page,"uspto_tmsearch_browser",80,{cdp:{semantic_poll_ms:10,semantic_stable_samples:2}});
    assert.equal(legacy.stable,false);assert.equal(legacy.candidates.length,0);
    await page.locator('#results').evaluate((e,text)=>{e.textContent=text;},`0 results for ${q}`);
    const zero=await waitForSearchSemanticState(page,"uspto_tmsearch_browser",1000,{tmsearch_query_binding:{tmsearchQuery:q},cdp:{semantic_poll_ms:10,semantic_stable_samples:2}});
    assert.equal(zero.stable,true);assert.equal(zero.noResult,true);assert.equal(zero.candidates.length,0);
    await page.locator("mat-select").evaluate(e=>{e.textContent="Wordmark";});
    const wrong=await waitForSearchSemanticState(page,"uspto_tmsearch_browser",80,{tmsearch_query_binding:{tmsearchQuery:q},cdp:{semantic_poll_ms:10,semantic_stable_samples:2}});
    assert.equal(wrong.stable,false);
  } finally {await browser.close();}
});

test("TM single-result auto-navigation binds the field-tag query, not a direct serial lookup", async () => {
  const browser=await chromium.launch({executablePath:requireChromeExecutable(),headless:true});
  try {
    const page=await browser.newPage(), q='CM:"Lid Latch"';
    // Local interception only: this fixture does not reach USPTO.
    await page.route('https://tmsearch.uspto.gov/**', route=>route.fulfill({contentType:'text/html',body:'<mat-select formcontrolname="searchRefinement">Field tag and Search builder</mat-select><input id="searchbar"><pre id="result"></pre>'}));
    await page.goto('https://tmsearch.uspto.gov/search/search-results/88418732');
    await page.locator('#searchbar').fill(q);
    await page.locator('#result').evaluate((e,text)=>e.textContent=text,`Result 1 of 1 for ${q}\n${DETAIL}`);
    const config={tmsearch_query_binding:{tmsearchQuery:q},cdp:{semantic_poll_ms:10,semantic_stable_samples:2}};
    // A positive result needs two samples even under release-suite contention.
    const result=await waitForSearchSemanticState(page,'uspto_tmsearch_browser',2000,config);
    assert.equal(result.stable,true);assert.equal(result.candidates[0].serial_number,'88418732');
    assert.equal(result.tmsearch_binding.result_view,'detail');assert.equal(result.tmsearch_binding.result_index,1);
    await page.locator('#result').evaluate((e,text)=>e.textContent=text,`Result 1 of 1 for 88418732\n${DETAIL}`);
    const direct=await waitForSearchSemanticState(page,'uspto_tmsearch_browser',80,config);
    assert.equal(direct.stable,false);assert.equal(direct.query_bound,false);
  }finally{await browser.close();}
});
