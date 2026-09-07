import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  assertOfficialUrl,
  assertRegistryOperation,
  getRegistryAdapter,
  hostAllowed,
  publicRegistryCatalog,
} from "./registry-adapters.mjs";

const REAL_CONFIG = JSON.parse(readFileSync(new URL("../../config.json", import.meta.url), "utf8"));

test("all registry adapters are assisted, user-triggered, and single-action", () => {
  for (const [provider, jurisdiction, rightType, operation] of [
    ["jplatpat_browser", "JP", "utility_model", "utility_model_recall"],
    ["tmview_browser", "DE", "trademark_word", "trademark_recall"],
    ["designview_browser", "FR", "design", "design_recall"],
    ["epo_register_browser", "EU", "patent", "candidate_verification"],
    ["euipo_esearch_browser", "EU", "trademark_figurative", "trademark_recall"],
    ["official_registry_browser", "PL", "patent", "patent_recall"],
    ["public_web_browser", "US", "copyright", "copyright_recall"],
    ["public_web_browser", "US", "enforcement", "candidate_verification"],
  ]) {
    const adapter = getRegistryAdapter(provider, jurisdiction, rightType);
    assert.equal(adapter.interaction_mode, "cdp_assisted");
    assert.equal(adapter.user_triggered_only, true);
    assert.equal(adapter.bulk_automation, false);
    assert.equal(adapter.max_records_per_command, 1);
    assert.match(adapter.terms_url, /^https:\/\//);
    assert.doesNotThrow(() => assertRegistryOperation(adapter, operation));
  }
});

test("every resolved adapter has an explicit terms binding and never falls back to its search URL", () => {
  const catalog = publicRegistryCatalog();
  const adapters = [];

  for (const [provider, metadata] of Object.entries(catalog.providers)) {
    adapters.push(getRegistryAdapter(provider, metadata.jurisdictions[0], metadata.right_types[0]));
  }
  for (const [country, metadata] of Object.entries(catalog.official_registry_browser)) {
    for (const rightType of metadata.right_types) {
      adapters.push(getRegistryAdapter("official_registry_browser", country, rightType));
    }
  }
  for (const country of Object.keys(catalog.public_web_browser)) {
    for (const rightType of ["copyright", "enforcement"]) {
      adapters.push(getRegistryAdapter("public_web_browser", country, rightType));
    }
  }
  for (const [sourceKey, rightType] of [
    ["copyright_records", "copyright"],
    ["ttabvue", "enforcement"],
    ["ptab", "enforcement"],
    ["copyright_claims_board", "enforcement"],
  ]) {
    adapters.push(getRegistryAdapter("public_web_browser", "US", rightType, {}, sourceKey));
  }

  for (const adapter of adapters) {
    assert.notEqual(adapter.terms_url, adapter.search_url);
    assert.ok(adapter.terms_allowed_hosts.length > 0);
    assert.equal(
      hostAllowed(new URL(adapter.terms_url).hostname, adapter.terms_allowed_hosts),
      true,
    );
    assert.equal(adapter.interaction_mode, "cdp_assisted");
    assert.equal(adapter.user_triggered_only, true);
  }
});

test("terms bindings use the audited authority-specific legal notices", () => {
  const expected = [
    ["jplatpat_browser", "JP", "patent", "www.inpit.go.jp", /j-platpat_notice\.html$/],
    ["tmview_browser", "DE", "trademark_word", "www.euipo.europa.eu", /legal-notices$/],
    ["designview_browser", "FR", "design", "www.euipo.europa.eu", /legal-notices$/],
    ["epo_register_browser", "EU", "patent", "www.epo.org", /terms-and-conditions-use-website-european-patent-office$/],
    ["euipo_esearch_browser", "EU", "trademark_figurative", "www.euipo.europa.eu", /legal-notices$/],
    ["official_registry_browser", "DE", "patent", "register.dpma.de", /nutzungsbedingungenpage$/],
    ["official_registry_browser", "FR", "patent", "data.inpi.fr", /content\/editorial\/cgu$/],
    ["official_registry_browser", "GB", "patent", "www.gov.uk", /help\/terms-conditions$/],
    ["official_registry_browser", "NL", "patent", "mijnoctrooi.rvo.nl", /disclaimer\/home\.action$/],
    ["official_registry_browser", "NL", "trademark_word", "www.boip.int", /general-terms-and-conditions-governing-boip-online-services$/],
    ["official_registry_browser", "BE", "patent", "bpp.economie.fgov.be", /disclaimer\/home\.action$/],
    ["official_registry_browser", "BE", "design", "www.boip.int", /general-terms-and-conditions-governing-boip-online-services$/],
    ["official_registry_browser", "SE", "patent", "www.prv.se", /about-our-website\/$/],
    ["official_registry_browser", "PL", "patent", "uprp.gov.pl", /node\/1000610$/],
  ];
  for (const [provider, jurisdiction, rightType, host, path] of expected) {
    const adapter = getRegistryAdapter(provider, jurisdiction, rightType);
    const terms = new URL(adapter.terms_url);
    assert.equal(terms.hostname, host);
    assert.match(terms.pathname, path);
  }

  assert.equal(
    getRegistryAdapter("public_web_browser", "US", "enforcement", {}, "ptab").terms_url,
    "https://www.uspto.gov/terms-use-uspto-websites",
  );
  assert.equal(
    getRegistryAdapter("public_web_browser", "US", "enforcement", {}, "copyright_claims_board").terms_url,
    "https://ccb.gov/about/legal.html",
  );
  assert.equal(
    getRegistryAdapter("public_web_browser", "GB", "enforcement").terms_url,
    "https://caselaw.nationalarchives.gov.uk/terms-of-use",
  );
});

test("full config cannot override right-specific BOIP and UKIPO register surfaces", () => {
  for (const country of ["NL", "BE"]) {
    assert.match(
      getRegistryAdapter("official_registry_browser", country, "design", REAL_CONFIG).search_url,
      /boip\.int\/en\/designs-register/,
    );
    for (const rightType of ["trademark_word", "trademark_figurative"]) {
      assert.match(
        getRegistryAdapter("official_registry_browser", country, rightType, REAL_CONFIG).search_url,
        /boip\.int\/en\/trademarks-register/,
      );
    }
  }
  assert.match(
    getRegistryAdapter("official_registry_browser", "GB", "design", REAL_CONFIG).search_url,
    /registered-design\.service\.gov\.uk/,
  );
  for (const rightType of ["trademark_word", "trademark_figurative"]) {
    assert.match(
      getRegistryAdapter("official_registry_browser", "GB", rightType, REAL_CONFIG).search_url,
      /trademarks\.ipo\.gov\.uk/,
    );
  }
  assert.match(
    getRegistryAdapter("official_registry_browser", "GB", "patent", REAL_CONFIG).search_url,
    /gov\.uk\/search-for-patent/,
  );
  assert.match(
    getRegistryAdapter("official_registry_browser", "NL", "patent", REAL_CONFIG).search_url,
    /mijnoctrooi\.rvo\.nl/,
  );
  assert.match(
    getRegistryAdapter("official_registry_browser", "BE", "patent", REAL_CONFIG).search_url,
    /bpp\.economie\.fgov\.be/,
  );
});

test("full config exposes utility-model routes and current IT/SE entry points", () => {
  for (const country of ["DE", "FR", "IT", "ES", "PL"]) {
    assert.ok(
      REAL_CONFIG.providers.official_registry_browser.registries[country].right_types.includes("utility_model"),
    );
    const adapter = getRegistryAdapter("official_registry_browser", country, "utility_model", REAL_CONFIG);
    assert.ok(adapter.right_types.includes("utility_model"));
    assert.doesNotThrow(() => assertRegistryOperation(adapter, "utility_model_recall"));
  }
  assert.ok(REAL_CONFIG.providers.inpi_api.supported_right_types.includes("utility_model"));
  assert.equal(
    getRegistryAdapter("official_registry_browser", "IT", "patent", REAL_CONFIG).search_url,
    "https://www.uibm.gov.it/bancadati/home/index/",
  );
  assert.equal(
    getRegistryAdapter("official_registry_browser", "SE", "patent", REAL_CONFIG).search_url,
    "https://search.prv.se/",
  );
});

test("TMview and DesignView allow EU27 discovery without inventing a national verifier", () => {
  const trademark = getRegistryAdapter("tmview_browser", "AT", "trademark_word");
  const design = getRegistryAdapter("designview_browser", "RO", "design");
  assert.doesNotThrow(() => assertRegistryOperation(trademark, "trademark_recall"));
  assert.doesNotThrow(() => assertRegistryOperation(design, "design_recall"));
  assert.throws(
    () => getRegistryAdapter("official_registry_browser", "AT", "trademark_word"),
    /Unsupported national official registry jurisdiction/,
  );
});

test("official URL validation rejects lookalike and configured non-official hosts", () => {
  const adapter = getRegistryAdapter("jplatpat_browser", "JP", "patent");
  assert.equal(hostAllowed("www.j-platpat.inpit.go.jp", adapter.browser_allowed_hosts), true);
  assert.equal(hostAllowed("j-platpat.inpit.go.jp.evil.example", adapter.browser_allowed_hosts), false);
  assert.doesNotThrow(() => assertOfficialUrl("https://www.j-platpat.inpit.go.jp/", adapter));
  assert.throws(() => assertOfficialUrl("https://j-platpat.inpit.go.jp.evil.example/", adapter), /allowlisted/);
  assert.throws(
    () => getRegistryAdapter("jplatpat_browser", "JP", "patent", {
      providers: { jplatpat_browser: { search_url: "https://evil.example/" } },
    }),
    /built-in official HTTPS host/,
  );
});

test("catalog exposes all national and public-web metadata without enabling bulk automation", () => {
  const catalog = publicRegistryCatalog();
  assert.deepEqual(Object.keys(catalog.official_registry_browser).sort(), [
    "BE", "DE", "ES", "FR", "GB", "IT", "NL", "PL", "SE",
  ]);
  assert.equal(catalog.public_web_browser.US.bulk_automation, false);
  assert.ok(catalog.public_web_browser.US.browser_allowed_hosts.includes("ptab.uspto.gov"));
});

test("public-web adapter uses the jurisdiction-specific configured official allowlist", () => {
  const adapter = getRegistryAdapter("public_web_browser", "US", "enforcement", {
    providers: {
      public_web_browser: {
        jurisdiction_allowed_hosts: {
          US: ["ttabvue.uspto.gov", "ptab.uspto.gov", "dockets.ccb.gov"],
        },
      },
    },
  });
  assert.deepEqual(adapter.browser_allowed_hosts, [
    "ttabvue.uspto.gov", "ptab.uspto.gov", "dockets.ccb.gov",
  ]);
  assert.throws(
    () => getRegistryAdapter("public_web_browser", "US", "copyright", {
      providers: { public_web_browser: { jurisdiction_allowed_hosts: { US: ["example.com"] } } },
    }),
    /outside the built-in official allowlist/,
  );
});

test("US public-web source keys bind each planned lookup to its own official host", () => {
  const expected = {
    copyright_records: "publicrecords.copyright.gov",
    ttabvue: "ttabvue.uspto.gov",
    ptab: "ptab.uspto.gov",
    copyright_claims_board: "ccb.gov",
  };
  for (const [sourceKey, host] of Object.entries(expected)) {
    const rightType = sourceKey === "copyright_records" ? "copyright" : "enforcement";
    const adapter = getRegistryAdapter(
      "public_web_browser", "US", rightType, REAL_CONFIG, sourceKey,
    );
    assert.equal(adapter.source_key, sourceKey);
    assert.equal(new URL(adapter.search_url).hostname, host);
    assert.ok(adapter.browser_allowed_hosts.includes(host));
    assert.ok(adapter.browser_allowed_hosts.every((item) =>
      sourceKey === "copyright_claims_board" ? item.endsWith("ccb.gov") : item === host
    ));
    assert.doesNotThrow(() => assertRegistryOperation(adapter, "candidate_verification"));
  }
  assert.throws(
    () => getRegistryAdapter("public_web_browser", "US", "enforcement", REAL_CONFIG, "pacer"),
    /Unsupported public-web source key/,
  );
});
