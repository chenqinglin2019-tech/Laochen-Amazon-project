import { requireChromeExecutable, resolvePythonExecutable } from "./platform-runtime.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { chromium } from "playwright-core";
import { captureSerperAccount } from "./serper-account-capture.mjs";

const KEY = "fixture_serper_key_1234567890_abcdef1234567890";
const OTHER = "different_serper_key_1234567890_abcdef12345678";
const EMAIL = "fixture.user@example.test";
const hash = value => createHash("sha256").update(value).digest("hex");
const fingerprint = hash(KEY);
const CHROME = requireChromeExecutable();
const credits = `<pre>Free credits remaining: 100
Paid credit balance: 0
Automatic recharge: Disabled
Patents credits per request: 2
Search credits per request: 1
Images credits per request: 2</pre>`;
const identity = `<p>Account email: ${EMAIL}</p><p>API key: ${KEY}</p>`;

async function fixture(t, pages, initial = "https://serper.dev/dashboard") {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  t.after(() => browser.close());
  const context = await browser.newContext();
  const requests = [];
  await context.route("**/*", async route => {
    requests.push({ url: route.request().url(), method: route.request().method() });
    const body = pages[new URL(route.request().url()).pathname];
    if (body === undefined) return route.abort();
    return route.fulfill({ contentType: "text/html", body });
  });
  const page = await context.newPage();
  if (initial) await page.goto(initial);
  return { context, page, requests };
}

test("missing or malformed fingerprint blocks before touching the browser", async () => {
  const context = new Proxy({}, { get() { throw new Error("browser must remain unread"); } });
  for (const credentialFingerprint of [undefined, "", "raw-credential", "0".repeat(63)]) {
    const result = await captureSerperAccount({ context, credentialFingerprint });
    assert.equal(result.status, "blocked");
    assert.equal(result.error_code, "CREDENTIAL_FINGERPRINT_REQUIRED");
    assert.deepEqual(result.pages, []);
    assert.equal(result.credential_fingerprint, null);
  }
});

test("visible account text is bound and redacted before persistence and Python validation", async t => {
  const { context, requests } = await fixture(t, { "/dashboard": identity + credits });
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "serper-capture-"));
  t.after(() => fs.rm(dir, { recursive: true, force: true }));
  const outputPath = path.join(dir, "capture.json");
  const result = await captureSerperAccount({ context, credentialFingerprint: fingerprint, outputPath });
  assert.equal(result.status, "success");
  assert.equal(result.schema, "SERPER-ACCOUNT-CAPTURE/1.0");
  assert.equal(result.account_fingerprint, hash(EMAIL));
  assert.equal(result.pages[0].sha256, hash(result.pages[0].text));
  assert.ok(Date.parse(result.pages[0].captured_at) <= Date.parse(result.captured_at));
  const saved = await fs.readFile(outputPath, "utf8");
  if (process.platform !== "win32") assert.equal((await fs.stat(outputPath)).mode & 0o777, 0o600);
  assert.ok(!saved.includes(KEY) && !saved.includes(EMAIL));
  assert.match(result.pages[0].text, /Free credits remaining: 100/);
  assert.deepEqual(requests.map(value => value.method), ["GET"]);
  const scripts = path.resolve(import.meta.dirname, "../../scripts");
  const checked = spawnSync(resolvePythonExecutable(), ["-c", "import json,sys; from serper_entitlement import validate_capture; value=json.load(sys.stdin); result=validate_capture(value['capture'],value['key']); assert result['free_credit_units']==100; assert result['operation_credit_units']['patents']==2; print('verified')"], {
    input: JSON.stringify({ capture: { ...result, source_environment: "test_fixture" }, key: KEY }),
    encoding: "utf8", env: { ...process.env, PYTHONPATH: scripts, PYTHONDONTWRITEBYTECODE: "1", LC_IPR_TEST_MODE: "1" },
  });
  assert.equal(checked.status, 0, checked.stderr);
  assert.equal(checked.stdout.trim(), "verified");
});

test("hidden, password, script and transparent keys cannot establish visible proof", async t => {
  const { context } = await fixture(t, { "/dashboard": `<p>Account email: ${EMAIL}</p>${credits}
    <div hidden>${KEY}</div><div style="display:none">${KEY}</div><div style="opacity:0">${KEY}</div>
    <div style="font-size:0">${KEY}</div><div aria-hidden="true">${KEY}</div>
    <input type="password" value="${KEY}"><input type="text" name="password" value="${KEY}">
    <script>window.fixtureSecret = "${KEY}";</script>` });
  const result = await captureSerperAccount({ context, credentialFingerprint: fingerprint });
  assert.equal(result.status, "needs_user_action");
  assert.equal(result.error_code, "ACCOUNT_ACCESS_REQUIRED");
  assert.ok(!JSON.stringify(result).includes(KEY));
  assert.ok(!result.pages[0].text.includes(`[credential-sha256:${fingerprint}]`));
});

test("plain visible key input is accepted without reading protected browser state", async t => {
  const { context, page } = await fixture(t, { "/dashboard": `<p>Email: ${EMAIL}</p><label>API key <input type="text" value="${KEY}"></label>${credits}` });
  await page.evaluate(() => {
    Object.defineProperty(document, "cookie", { get() { throw new Error("cookies forbidden"); } });
    Object.defineProperty(window, "localStorage", { get() { throw new Error("storage forbidden"); } });
  });
  const result = await captureSerperAccount({ context, credentialFingerprint: fingerprint });
  assert.equal(result.status, "success");
  assert.ok(result.pages[0].text.includes(`[credential-sha256:${fingerprint}]`));
});

test("a different or masked key fails closed and the receipt contains neither key nor email", async t => {
  const { context, page } = await fixture(t, { "/dashboard": `<p>Email: ${EMAIL}</p><p>API Key: ${OTHER}</p>${credits}` });
  const mismatch = await captureSerperAccount({ context, credentialFingerprint: fingerprint });
  assert.equal(mismatch.error_code, "CREDENTIAL_BINDING_MISMATCH");
  assert.ok(!JSON.stringify(mismatch).includes(OTHER));
  assert.ok(!JSON.stringify(mismatch).includes(EMAIL));
  await page.setContent(`<p>Email: ${EMAIL}</p><p>API Key: ****************</p>${credits}`);
  assert.equal((await captureSerperAccount({ context, credentialFingerprint: fingerprint })).error_code, "CREDENTIAL_NOT_VISIBLE");
  await page.setContent(`<p>Email: ${EMAIL}</p><p>[credential-sha256:${fingerprint}]</p>${credits}`);
  assert.notEqual((await captureSerperAccount({ context, credentialFingerprint: fingerprint })).status, "success");
});

test("only observed same-origin account GET links are visited, at most five", async t => {
  const pages = { "/dashboard": identity + credits + Array.from({ length: 8 }, (_, i) => `<a href="/account/${i}">Account ${i}</a>`).join("")
    + '<a href="https://evil.test/account">Account</a><a href="/billing/checkout">Billing</a>'
    + '<a href="/account?token=secret">Account</a><a href="javascript:alert(1)">API Keys</a>'
    + '<a href="/api-keys/reveal">API Keys</a><a href="/account/logout">Account</a>'
    + '<div style="opacity:0"><a href="/account/hidden">Account</a></div>' };
  for (let i = 0; i < 8; i++) pages[`/account/${i}`] = credits;
  const { context, requests } = await fixture(t, pages);
  const result = await captureSerperAccount({ context, credentialFingerprint: fingerprint });
  assert.equal(result.status, "success");
  assert.equal(result.pages.length, 6);
  assert.equal(requests.length, 6);
  assert.ok(requests.every(value => value.method === "GET" && value.url.startsWith("https://serper.dev/")));
  assert.ok(!requests.some(value => /checkout|reveal|logout|token/.test(value.url)));
});

test("without an official tab the collector opens only the known homepage and stops at login", async t => {
  const { context, requests } = await fixture(t, { "/": '<h1>Log in</h1><a href="/account">Account</a>' }, null);
  const result = await captureSerperAccount({ context, credentialFingerprint: fingerprint });
  assert.equal(result.status, "needs_user_action");
  assert.deepEqual(requests, [{ url: "https://serper.dev/", method: "GET" }]);
});

test("a redirect to an identity provider is not read or included in the proof", async () => {
  let current = "https://serper.dev/dashboard", reads = 0;
  const page = {
    url: () => current,
    evaluate: async () => {
      reads += 1;
      assert.equal(current, "https://serper.dev/dashboard");
      return { text: "Account", links: [{ href: "https://serper.dev/account", text: "Account" }] };
    },
    goto: async url => {
      assert.equal(url, "https://serper.dev/account");
      current = "https://identity.example.test/login";
    },
  };
  const context = { pages: () => [page], newPage: async () => { throw new Error("unexpected tab"); } };
  const result = await captureSerperAccount({ context, credentialFingerprint: fingerprint });
  assert.equal(page.url(), "https://identity.example.test/login");
  assert.equal(reads, 1);
  assert.equal(result.status, "needs_user_action");
  assert.equal(result.pages.length, 1);
  assert.equal(result.pages[0].url, "https://serper.dev/dashboard");
  assert.ok(!JSON.stringify(result).includes(KEY));
});

test("unknown credit units remain original text for the strict entitlement parser", async t => {
  const { context } = await fixture(t, { "/dashboard": identity + '<p>Free queries: 1000</p><p>Paid balance unknown</p>' });
  const result = await captureSerperAccount({ context, credentialFingerprint: fingerprint });
  assert.equal(result.status, "success"); // Capture success is never entitlement acceptance.
  assert.match(result.pages[0].text, /Free queries: 1000/);
  assert.ok(!result.pages[0].text.includes("Free credits"));
  assert.ok(!("free_credit_units" in result));
});

test("ambiguous account identity and capture errors never leak raw values", async t => {
  const { context, page } = await fixture(t, { "/dashboard": identity + "<p>Account email: another@example.test</p>" });
  const ambiguous = await captureSerperAccount({ context, credentialFingerprint: fingerprint });
  assert.equal(ambiguous.error_code, "ACCOUNT_IDENTITY_AMBIGUOUS");
  assert.ok(!JSON.stringify(ambiguous).includes("another@example.test"));
  page.evaluate = async () => { throw new Error(`${KEY} ${EMAIL}`); };
  const failure = await captureSerperAccount({ context, credentialFingerprint: fingerprint });
  assert.equal(failure.error_code, "ACCOUNT_PAGE_CAPTURE_FAILED");
  assert.ok(!JSON.stringify(failure).includes(KEY) && !JSON.stringify(failure).includes(EMAIL));
});
