#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs/promises";
import fsSync from "node:fs";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { spawn } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "playwright-core";

const TOOL_DIR = path.dirname(fileURLToPath(import.meta.url));
const SKILL_DIR = path.resolve(TOOL_DIR, "..", "..");
const SENSITIVE_SESSION_KEYS = new Set([
  "cdp_endpoint", "endpoint", "websocket", "websocket_url",
  "remote_debugging_port", "profile_dir", "user_data_dir",
  "cookies", "local_storage", "localstorage",
]);
const SENSITIVE_URL_KEYS = new Set([
  "requesttoken", "token", "api_key", "apikey", "key", "access_token", "client_secret",
]);

function parseArgs(argv) {
  const [command = "", ...rest] = argv;
  const args = { command };
  for (let index = 0; index < rest.length; index += 1) {
    const raw = rest[index];
    if (!raw.startsWith("--")) {
      throw new Error(`Unexpected argument: ${raw}`);
    }
    const key = raw.slice(2).replaceAll("-", "_");
    const next = rest[index + 1];
    if (next && !next.startsWith("--")) {
      args[key] = next;
      index += 1;
    } else {
      args[key] = true;
    }
  }
  return args;
}

function expandHome(value) {
  const text = String(value || "");
  if (text === "~") return os.homedir();
  if (text.startsWith("~/")) return path.join(os.homedir(), text.slice(2));
  return path.resolve(text);
}

async function readJson(filePath) {
  return JSON.parse(await fs.readFile(filePath, "utf8"));
}

async function writeJsonAtomic(filePath, value, mode = 0o600) {
  await fs.mkdir(path.dirname(filePath), { recursive: true, mode: 0o700 });
  const tempPath = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  await fs.writeFile(tempPath, `${JSON.stringify(value, null, 2)}\n`, { mode });
  await fs.rename(tempPath, filePath);
  await fs.chmod(filePath, mode);
}

async function updateCandidateJournal(taskDir, entry) {
  const journalPath = path.join(taskDir, "browser-candidate-journal.json");
  let journal;
  try {
    journal = await readJson(journalPath);
  } catch {
    const task = await readJson(path.join(taskDir, "task.json"));
    journal = {
      schema_version: "1.0",
      task_id: String(task.task_id || ""),
      entries: [],
    };
  }
  if (!Array.isArray(journal.entries)) journal.entries = [];
  const provider = String(entry.provider || "");
  const recordNumber = cleanNumber(entry.record_number);
  if (!provider || !recordNumber) {
    throw new Error("Candidate journal entries require provider and record_number");
  }
  const index = journal.entries.findIndex((item) =>
    String(item?.provider || "") === provider
      && cleanNumber(item?.record_number) === recordNumber
  );
  const previous = index >= 0 ? journal.entries[index] : {};
  const next = {
    ...previous,
    ...entry,
    provider,
    record_number: recordNumber,
    updated_at: nowIso(),
  };
  if (index >= 0) journal.entries[index] = next;
  else journal.entries.push(next);
  assertNoSensitiveKeys(journal, "candidate_journal");
  await writeJsonAtomic(journalPath, journal);
  return journalPath;
}

async function loadConfig() {
  return readJson(path.join(SKILL_DIR, "config.json"));
}

function sanitizedSession(version, sessionId) {
  return {
    browser: "chrome_desktop",
    capture_transport: "cdp",
    browser_version: String(version.Browser || "Chrome/unknown"),
    protocol_version: String(version["Protocol-Version"] || "unknown"),
    cdp_session_id: sessionId,
  };
}

function assertNoSensitiveKeys(value, prefix = "capture") {
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertNoSensitiveKeys(item, `${prefix}[${index}]`));
    return;
  }
  if (!value || typeof value !== "object") return;
  for (const [key, item] of Object.entries(value)) {
    if (SENSITIVE_SESSION_KEYS.has(key.toLowerCase())) {
      throw new Error(`Sensitive browser field cannot be serialized: ${prefix}.${key}`);
    }
    assertNoSensitiveKeys(item, `${prefix}.${key}`);
  }
}

async function fetchVersion(port) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 2000);
  try {
    const response = await fetch(`http://127.0.0.1:${port}/json/version`, {
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`CDP version endpoint returned ${response.status}`);
    const version = await response.json();
    const endpoint = String(version.webSocketDebuggerUrl || "");
    if (!endpoint.startsWith(`ws://127.0.0.1:${port}/`)) {
      throw new Error("CDP endpoint is not bound to the expected loopback address");
    }
    return version;
  } finally {
    clearTimeout(timeout);
  }
}

async function waitForChromeEndpoint(child, timeoutMs = 20000) {
  return new Promise((resolve, reject) => {
    let buffer = "";
    const timeout = setTimeout(() => {
      reject(new Error("Timed out waiting for Chrome CDP endpoint"));
    }, timeoutMs);
    const finish = (error, value) => {
      clearTimeout(timeout);
      child.stderr?.off("data", onData);
      child.off("exit", onExit);
      if (error) reject(error);
      else resolve(value);
    };
    const onData = (chunk) => {
      buffer += chunk.toString("utf8");
      const match = buffer.match(/DevTools listening on ws:\/\/127\.0\.0\.1:(\d+)\/devtools\/browser\/[A-Za-z0-9-]+/);
      if (match) finish(null, Number(match[1]));
    };
    const onExit = (code) => finish(new Error(`Chrome exited before CDP became ready: ${code}`));
    child.stderr?.on("data", onData);
    child.once("exit", onExit);
  });
}

async function ensureSession(config) {
  const cdp = config.cdp || {};
  const runtimeDir = expandHome(cdp.runtime_dir || "~/.codex/runtime/lc-ipr-free-cdp");
  const profileDir = expandHome(cdp.profile_dir || "~/.codex/browser-profiles/lc-ipr-free-cdp");
  const descriptorPath = path.join(runtimeDir, "session.json");
  await fs.mkdir(runtimeDir, { recursive: true, mode: 0o700 });
  await fs.mkdir(profileDir, { recursive: true, mode: 0o700 });
  await fs.chmod(runtimeDir, 0o700);
  await fs.chmod(profileDir, 0o700);

  let descriptor = null;
  try {
    descriptor = await readJson(descriptorPath);
    const port = Number(descriptor.port);
    if (!Number.isInteger(port) || port < 1024 || port > 65535) {
      throw new Error("Invalid runtime CDP port");
    }
    const version = await fetchVersion(port);
    return {
      version,
      sessionId: String(descriptor.session_id),
      endpoint: version.webSocketDebuggerUrl,
      launched: false,
    };
  } catch {
    // A stale descriptor is replaced only after a fresh loopback Chrome starts.
  }

  const executable = expandHome(cdp.chrome_executable || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome");
  if (!fsSync.existsSync(executable)) {
    throw new Error(`Chrome executable is missing: ${executable}`);
  }
  const chromeArgs = [
    "--remote-debugging-address=127.0.0.1",
    "--remote-debugging-port=0",
    `--user-data-dir=${profileDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-mode",
    "about:blank",
  ];
  const child = spawn(executable, chromeArgs, {
    detached: true,
    stdio: ["ignore", "ignore", "pipe"],
  });
  const port = await waitForChromeEndpoint(child);
  const version = await fetchVersion(port);
  const sessionId = crypto
    .createHash("sha256")
    .update(`${child.pid}:${port}:${Date.now()}`)
    .digest("hex")
    .slice(0, 20);
  await writeJsonAtomic(descriptorPath, {
    port,
    pid: child.pid,
    session_id: sessionId,
    created_at: new Date().toISOString(),
  });
  child.stderr?.destroy();
  child.unref();
  return {
    version,
    sessionId,
    endpoint: version.webSocketDebuggerUrl,
    launched: true,
  };
}

async function connectSession(config) {
  const session = await ensureSession(config);
  const browser = await chromium.connectOverCDP(session.endpoint);
  const context = browser.contexts()[0];
  if (!context) {
    throw new Error("CDP browser has no default context");
  }
  const timeout = Number(config.cdp?.action_timeout_ms || 15000);
  context.setDefaultTimeout(timeout);
  return { ...session, browser, context };
}

function nowIso() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

function slug(value) {
  return String(value || "capture")
    .replace(/[^A-Za-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80) || "capture";
}

function sanitizeEvidenceUrl(value) {
  try {
    const url = new URL(String(value || ""));
    for (const key of [...url.searchParams.keys()]) {
      if (SENSITIVE_URL_KEYS.has(key.toLowerCase())) url.searchParams.delete(key);
    }
    return url.toString();
  } catch {
    return "";
  }
}

function sanitizeSensitiveText(value) {
  return String(value || "").replace(
    /([?&](?:requesttoken|token|api_key|apikey|key|access_token|client_secret)=)[^&\s]+/gi,
    "$1[redacted]",
  );
}

function cleanNumber(value) {
  return String(value || "").replace(/[^A-Za-z0-9]/g, "").toUpperCase();
}

export function formatTmQuery(query, strategy) {
  const value = String(query || "").trim();
  if (strategy === "prefix") return `${value}*`;
  if (strategy === "exact" || strategy === "phrase") return `"${value.replaceAll('"', "")}"`;
  throw new Error(`Unsupported TM Search strategy: ${strategy}`);
}

export function detectChallenge(url, title, bodyText) {
  const text = `${url}\n${title}\n${bodyText}`.toLowerCase();
  return /captcha|robot check|verify you are human|security verification|access denied|challenge-platform/.test(text);
}

export function explicitNoResult(bodyText) {
  return /no (records|results|matches|cases) (were )?found|0 results|zero results/i.test(String(bodyText || ""));
}

export async function waitForStableSemanticState(readSnapshot, options = {}) {
  const timeoutMs = Number(options.timeoutMs || 45000);
  const pollMs = Number(options.pollMs || 750);
  const stableSamples = Math.max(1, Number(options.stableSamples || 3));
  const deadline = Date.now() + timeoutMs;
  let lastSignature = "";
  let stableCount = 0;
  let latest = null;
  while (Date.now() <= deadline) {
    latest = await readSnapshot();
    const signature = String(latest?.signature || "");
    if (latest?.ready && signature) {
      stableCount = signature === lastSignature ? stableCount + 1 : 1;
      lastSignature = signature;
      if (stableCount >= stableSamples) {
        return { ...latest, stable: true, timed_out: false, stable_samples: stableCount };
      }
    } else {
      stableCount = 0;
      lastSignature = "";
    }
    await new Promise((resolve) => setTimeout(resolve, pollMs));
  }
  return {
    ...(latest || {}),
    stable: false,
    timed_out: true,
    stable_samples: stableCount,
  };
}

export function renderedPatentPdfScreenshot(screenshot) {
  return Buffer.isBuffer(screenshot) && screenshot.length >= 60000;
}

export function assertCdpProviderAllowed(provider) {
  if (provider === "wipo_patentscope_browser") {
    throw new Error("PATENTSCOPE queries must be performed manually and operator-confirmed");
  }
  if (provider === "espacenet_browser") {
    throw new Error("Espacenet browser automation is disabled; use the planned EPO OPS query");
  }
  if (!["uspto_tmsearch_browser", "uspto_patent_browser"].includes(provider)) {
    throw new Error(`run-planned-query does not support provider: ${provider}`);
  }
}

export function parseTrademarkRows(rows) {
  const results = [];
  for (const cells of rows) {
    const values = cells.map((value) => String(value || "").trim()).filter(Boolean);
    const joined = values.join(" | ");
    const serial = joined.match(/(?:^|\D)(\d{8})(?:\D|$)/)?.[1] || "";
    if (!serial) continue;
    const registration = joined.match(/(?:registration|reg\.?)\s*(?:no\.?|number)?\s*[:#]?\s*(\d{7,8})/i)?.[1] || "";
    const markText = values.find((value) => !value.includes(serial) && !/serial|registration|live|dead|class/i.test(value)) || "";
    if (!markText) continue;
    results.push({
      serial_number: serial,
      registration_number: registration,
      mark_text: markText,
      owner: values.find((value) => /inc|llc|ltd|corp|company|co\./i.test(value)) || "",
      status: values.find((value) => /live|dead|registered|pending/i.test(value)) || "",
      nice_classes: values.filter((value) => /(?:international class|ic)\s*0?\d+/i.test(value)),
      goods_services: [],
    });
  }
  return results;
}

export function parsePatentRows(rows) {
  const results = [];
  for (const cells of rows) {
    const values = cells.map((value) => String(value || "").trim()).filter(Boolean);
    const joined = values.join(" | ");
    const match = joined.match(/\bUS[-\s]?(?:D|RE|PP)?\d{5,11}(?:[-\s]?[A-Z]\d?)?\b/i)
      || joined.match(/\bD\d{6,8}(?:[-\s]?S\d?)?\b/i);
    if (!match) continue;
    const record = match[0].replace(/\s+/g, "-").toUpperCase();
    const recordIndex = values.findIndex((value) => value.includes(match[0]));
    const title = values.slice(Math.max(0, recordIndex + 1)).find((value) =>
      value.length > 3
      && !/^(preview|pdf|text|display|title|pages?|result\s*#?)(?:\s|$)/i.test(value)
      && !/^\d{4}-\d{2}-\d{2}$/.test(value)
      && !/^(active|expired|issued|pending|abandon(?:ed)?)$/i.test(value)
      && !/^(?:\d+|page \d+(?: of \d+)?)$/i.test(value)
    ) || "";
    if (!title) continue;
    results.push({
      record_number: record,
      publication_number: record,
      title,
      owners: values.filter((value) => /inc|llc|ltd|corp|company|co\./i.test(value)).slice(0, 3),
      legal_status: values.find((value) => /active|expired|issued|pending|abandon/i.test(value)) || "",
      jurisdiction: "US",
      kind_code: record.match(/[A-Z]\d?$/)?.[0] || "",
      material: false,
    });
  }
  return results;
}

async function searchSemanticSnapshot(page, provider) {
  const state = await freshState(page);
  const rows = await tableRows(page);
  const candidates = provider === "uspto_tmsearch_browser"
    ? parseTrademarkRows(rows)
    : parsePatentRows(rows);
  const challenge = detectChallenge(state.url, state.title, state.bodyText);
  const noResult = explicitNoResult(state.bodyText);
  return {
    ready: challenge || noResult || candidates.length > 0,
    signature: JSON.stringify({
      url: state.url,
      challenge,
      noResult,
      candidates: candidates.map((item) => [
        item.record_number || item.serial_number,
        item.title || item.mark_text,
      ]),
    }),
    state,
    rows,
    candidates,
    challenge,
    noResult,
  };
}

async function waitForSearchSemanticState(page, provider, timeoutMs, config) {
  return waitForStableSemanticState(
    () => searchSemanticSnapshot(page, provider),
    {
      timeoutMs,
      pollMs: Number(config.cdp?.semantic_poll_ms || 750),
      stableSamples: Number(config.cdp?.semantic_stable_samples || 3),
    },
  );
}

async function freshState(page) {
  const state = { url: page.url(), title: "", bodyText: "" };
  try {
    state.title = await page.title();
  } catch {}
  try {
    state.bodyText = (await page.locator("body").innerText()).slice(0, 200000);
  } catch {}
  return state;
}

async function navigateAndRefresh(page, url, timeoutMs) {
  let navigationError = "";
  try {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: timeoutMs });
  } catch (error) {
    navigationError = String(error?.message || error);
  }
  await page.waitForTimeout(800);
  return { state: await freshState(page), navigationError };
}

async function firstVisible(page, selectors) {
  for (const selector of selectors) {
    const locator = page.locator(selector);
    const count = Math.min(await locator.count(), 20);
    for (let index = 0; index < count; index += 1) {
      const item = locator.nth(index);
      if (await item.isVisible().catch(() => false)) return item;
    }
  }
  return null;
}

export async function tableRows(page) {
  return page.locator("table tr").evaluateAll((rows) =>
    rows.map((row) =>
      Array.from(row.querySelectorAll("th,td"))
        .map((cell) => (cell.innerText || "").trim())
        .filter(Boolean)
    ).filter((cells) => cells.length)
  ).catch(() => []);
}

async function safeScreenshot(page, screenshotPath, options = {}) {
  await fs.mkdir(path.dirname(screenshotPath), { recursive: true, mode: 0o700 });
  await page.screenshot({ path: screenshotPath, animations: "disabled", ...options });
}

export async function extractAmazonProduct(page) {
  return page.evaluate(() => {
    const visibleText = (selector) => {
      const element = document.querySelector(selector);
      if (!element) return "";
      const style = getComputedStyle(element);
      return style.display === "none" || style.visibility === "hidden"
        ? ""
        : (element.innerText || element.textContent || "").trim();
    };
    const list = (selector) => Array.from(document.querySelectorAll(selector))
      .filter((element) => {
        const style = getComputedStyle(element);
        return style.display !== "none" && style.visibility !== "hidden";
      })
      .map((element) => (element.innerText || element.textContent || "").trim())
      .filter(Boolean);
    const specs = {};
    for (const row of document.querySelectorAll(
      "#productDetails_detailBullets_sections1 tr, #productDetails_techSpec_section_1 tr, #detailBullets_feature_div li"
    )) {
      const cells = Array.from(row.querySelectorAll("th,td,span"))
        .map((cell) => (cell.innerText || cell.textContent || "").trim())
        .filter(Boolean);
      if (cells.length >= 2 && !specs[cells[0]]) specs[cells[0]] = cells.slice(1).join(" ");
    }
    const image = document.querySelector("#landingImage, #imgTagWrapperId img, img[data-old-hires]");
    let imageUrl = image?.getAttribute("data-old-hires") || "";
    const dynamic = image?.getAttribute("data-a-dynamic-image");
    if (!imageUrl && dynamic) {
      try {
        const entries = Object.entries(JSON.parse(dynamic));
        entries.sort((left, right) => (right[1]?.[0] || 0) * (right[1]?.[1] || 0) - (left[1]?.[0] || 0) * (left[1]?.[1] || 0));
        imageUrl = entries[0]?.[0] || "";
      } catch {}
    }
    imageUrl ||= image?.currentSrc || image?.src || "";
    const selectedVariants = list(
      "[aria-checked='true'], .a-button-selected, .swatchSelect, .variation_selected"
    );
    return {
      title: visibleText("#productTitle"),
      brand: visibleText("#bylineInfo").replace(/^Visit the | Store$/g, "").trim(),
      category: list("#wayfinding-breadcrumbs_feature_div a").join(" > "),
      bullets: list("#feature-bullets li span.a-list-item"),
      specifications: specs,
      selectedVariants,
      imageUrl,
      imageWidth: image?.naturalWidth || 0,
      imageHeight: image?.naturalHeight || 0,
      pageAsin: document.querySelector("input#ASIN")?.value || "",
    };
  });
}

async function captureAmazon(args, config) {
  const taskDir = path.resolve(String(args.task_dir || ""));
  const task = await readJson(path.join(taskDir, "task.json"));
  if (task.schema_version !== "2.2-free") throw new Error("capture-amazon requires task schema 2.2-free");
  if (task.checkpoints?.credential_preflight?.status !== "success") {
    throw new Error("Credential preflight must pass before opening Amazon");
  }
  const requestedUrl = String(task.request?.url || "");
  const session = await connectSession(config);
  const provenance = sanitizedSession(session.version, session.sessionId);
  let page = session.context.pages().find((item) => item.url().includes(task.request?.amazon_host || ""));
  if (!page) page = await session.context.newPage();
  const timeout = Number(config.cdp?.navigation_timeout_ms || 45000);
  const { state, navigationError } = await navigateAndRefresh(page, requestedUrl, timeout);
  const capturePath = path.join(taskDir, "browser-capture.json");

  if (detectChallenge(state.url, state.title, state.bodyText)) {
    const screenshotPath = path.join(taskDir, "screenshots", "amazon-user-action.png");
    await safeScreenshot(page, screenshotPath);
    const capture = {
      ...provenance,
      status: "robot_check",
      requested_url: requestedUrl,
      final_url: state.url,
      screenshot_path: screenshotPath,
      detail: "Amazon requires user action in the visible dedicated Chrome window.",
    };
    assertNoSensitiveKeys(capture);
    await writeJsonAtomic(capturePath, capture);
    return { status: "needs_user_action", capture_path: capturePath };
  }

  const product = await extractAmazonProduct(page);
  const urlAsin = state.url.match(/\/(?:dp|gp\/product|gp\/aw\/d)\/([A-Z0-9]{10})(?:[/?]|$)/i)?.[1]?.toUpperCase() || "";
  const actualAsin = String(product.pageAsin || urlAsin).toUpperCase();
  const corePath = path.join(taskDir, "screenshots", "product-core.png");
  const detailsPath = path.join(taskDir, "screenshots", "product-details.png");
  await page.evaluate(() => scrollTo(0, 0));
  await safeScreenshot(page, corePath);
  const details = await firstVisible(page, [
    "#productDetails_detailBullets_sections1",
    "#productDetails_techSpec_section_1",
    "#detailBullets_feature_div",
  ]);
  if (details) await details.scrollIntoViewIfNeeded().catch(() => {});
  await safeScreenshot(page, detailsPath);

  const imageUrl = String(product.imageUrl || "");
  if (!/^https:\/\/[^/]*media-amazon\.com\//i.test(imageUrl)) {
    const capture = {
      ...provenance, status: "failed", requested_url: requestedUrl,
      final_url: state.url, actual_asin: actualAsin,
      detail: "A current-variant HTTPS Amazon media main image was not available.",
    };
    assertNoSensitiveKeys(capture);
    await writeJsonAtomic(capturePath, capture);
    return { status: "failed", capture_path: capturePath };
  }

  const imagePage = await session.context.newPage();
  const imageResponse = await imagePage.goto(imageUrl, { waitUntil: "load", timeout });
  if (!imageResponse?.ok()) throw new Error(`Main image request failed: ${imageResponse?.status()}`);
  const imageBytes = await imageResponse.body();
  const contentType = String(imageResponse.headers()["content-type"] || "image/jpeg").split(";")[0];
  const imageSize = await imagePage.locator("img").first().evaluate((image) => ({
    width: image.naturalWidth,
    height: image.naturalHeight,
  })).catch(() => ({ width: product.imageWidth, height: product.imageHeight }));
  await imagePage.close();
  const extension = contentType.includes("png") ? "png" : contentType.includes("webp") ? "webp" : "jpg";
  const imagePath = path.join(taskDir, "images", `main.${extension}`);
  await fs.writeFile(imagePath, imageBytes, { mode: 0o600 });
  const imageHash = crypto.createHash("sha256").update(imageBytes).digest("hex");
  const manufacturer = Object.entries(product.specifications)
    .find(([key]) => /manufacturer/i.test(key))?.[1] || "";
  const visibleIpClaims = product.bullets.filter((value) =>
    /patent|copyright|licensed|trademark|registered design/i.test(value)
  );
  const selected = product.selectedVariants.join(" | ").slice(0, 500);
  const capture = {
    ...provenance,
    status: "success",
    requested_url: requestedUrl,
    final_url: state.url,
    requested_asin: String(task.product?.requested_asin || ""),
    actual_asin: actualAsin,
    variant: {
      label: selected ? "Selected option" : "ASIN",
      value: selected || actualAsin,
      confirmed: Boolean(actualAsin && actualAsin === String(task.product?.requested_asin || "").toUpperCase()),
    },
    title: product.title,
    brand: product.brand,
    manufacturer,
    category: product.category,
    bullets: product.bullets,
    specifications: product.specifications,
    structure: [],
    visible_ip_claims: visibleIpClaims,
    ocr_text: [],
    visual_features: [],
    main_image: {
      path: imagePath,
      source_url: imageUrl,
      width: Number(imageSize.width || 0),
      height: Number(imageSize.height || 0),
      format: extension === "png" ? "PNG" : extension === "webp" ? "WEBP" : "JPEG",
      sha256: imageHash,
    },
    screenshots: {
      product_core: corePath,
      product_details: detailsPath,
    },
    collected_at: nowIso(),
  };
  if (navigationError && (!capture.title || !capture.category)) {
    capture.status = "failed";
    capture.detail = `Amazon did not render a complete product page: ${navigationError.slice(0, 300)}`;
  }
  assertNoSensitiveKeys(capture);
  await writeJsonAtomic(capturePath, capture);
  return { status: capture.status, capture_path: capturePath };
}

async function submitSearch(page, renderedQuery) {
  const input = await firstVisible(page, [
    "input[type='search']",
    "input[placeholder*='Search' i]",
    "input[aria-label*='Search' i]",
    "input[type='text']",
  ]);
  if (!input) throw new Error("No visible search input was found");
  await input.fill(renderedQuery);
  const button = await firstVisible(page, [
    "button:has-text('Search')",
    "input[type='submit']",
    "button[type='submit']",
  ]);
  if (button) await button.click();
  else await input.press("Enter");
}

async function runPlannedQuery(args, config) {
  const taskDir = path.resolve(String(args.task_dir || ""));
  const queryId = String(args.query_id || "");
  const task = await readJson(path.join(taskDir, "task.json"));
  const plan = await readJson(path.join(taskDir, "search-plan.json"));
  let provider = "";
  let query = null;
  for (const [name, entries] of Object.entries(plan.queries || {})) {
    const match = Array.isArray(entries) ? entries.find((item) => item?.query_id === queryId) : null;
    if (match) {
      provider = name;
      query = match;
      break;
    }
  }
  if (!query) throw new Error(`Unknown query_id: ${queryId}`);
  assertCdpProviderAllowed(provider);

  const session = await connectSession(config);
  const provenance = sanitizedSession(session.version, session.sessionId);
  const page = await session.context.newPage();
  const providerConfig = config.providers[provider];
  const startUrl = providerConfig.search_url || providerConfig.basic_search_url;
  const timeout = Number(config.cdp?.navigation_timeout_ms || 45000);
  await navigateAndRefresh(page, startUrl, timeout);
  const renderedQuery = provider === "uspto_tmsearch_browser"
    ? formatTmQuery(query.q, query.strategy)
    : String(query.q);
  let actionError = "";
  try {
    await submitSearch(page, renderedQuery);
    await page.waitForLoadState("domcontentloaded", { timeout }).catch(() => {});
  } catch (error) {
    actionError = String(error?.message || error);
  }
  const semantic = await waitForSearchSemanticState(page, provider, timeout, config);
  const state = semantic.state || await freshState(page);
  const screenshotPath = path.join(taskDir, "screenshots", `${slug(provider)}-${slug(queryId)}.png`);
  await safeScreenshot(page, screenshotPath, { fullPage: false });
  const candidates = semantic.candidates || [];
  const challenge = Boolean(semantic.challenge);
  let status = "access_limited";
  let resultMessage = "";
  let detail = "";
  if (challenge) {
    status = "needs_user_action";
    detail = "The official USPTO page requires user action in visible Chrome.";
  } else if (!semantic.timed_out && candidates.length) {
    status = "success";
  } else if (!semantic.timed_out && semantic.noResult) {
    status = "no_result";
    resultMessage = "The rendered official page explicitly reported zero results.";
  } else {
    detail = actionError
      ? `Search completion could not be confirmed after refreshing page state: ${actionError.slice(0, 300)}`
      : semantic.timed_out
        ? "The rendered page did not reach a stable semantic result before timeout."
        : "The rendered page did not expose validated candidates or an explicit zero-result message.";
  }
  const capture = {
    ...provenance,
    status,
    query: String(query.q),
    final_url: state.url,
    checked_at: nowIso(),
    screenshot_path: screenshotPath,
    candidates,
    ...(provider === "uspto_tmsearch_browser"
      ? { strategy: query.strategy, rendered_query: renderedQuery }
      : { mode: query.mode || "basic_search" }),
    ...(resultMessage ? { result_message: resultMessage } : {}),
    ...(detail ? { detail } : {}),
  };
  assertNoSensitiveKeys(capture);
  const capturePath = path.join(taskDir, `${slug(provider)}-${slug(queryId)}-capture.json`);
  await writeJsonAtomic(capturePath, capture);
  return { status, provider, query_id: queryId, capture_path: capturePath };
}

async function matchingPatentResultRow(page, record) {
  const recordClean = cleanNumber(record);
  const rows = page.locator("table tr");
  const count = Math.min(await rows.count(), 200);
  for (let index = 0; index < count; index += 1) {
    const row = rows.nth(index);
    const rowText = await row.innerText().catch(() => "");
    if (cleanNumber(rowText).includes(recordClean)) return row;
  }
  return null;
}

async function matchingPatentResultLink(row, labels = ["Text", "Preview", "PDF"]) {
  if (!row) return null;
  for (const label of labels) {
    const link = row.locator("a").filter({ hasText: label }).first();
    if (await link.isVisible().catch(() => false)) return link;
  }
  return null;
}

async function capturePatentPdfFigure(context, page, row, taskDir, record, timeout, config) {
  const pdfLink = await matchingPatentResultLink(row, ["PDF"]);
  if (!pdfLink) return { attempted: false, path: null };
  const href = await pdfLink.getAttribute("href").catch(() => "");
  if (!href) return { attempted: true, path: null };
  const pdfUrl = new URL(href, page.url()).toString();
  let pdfPage = context.pages().find((item) =>
    item.url().includes("/api/pdf/")
      && cleanNumber(item.url()).includes(cleanNumber(record))
  );
  const ownsPage = !pdfPage;
  pdfPage ||= await context.newPage();
  try {
    if (ownsPage) {
      await pdfPage.goto(pdfUrl, { waitUntil: "domcontentloaded", timeout }).catch(() => {});
    }
    const stable = await waitForStableSemanticState(async () => {
      const screenshot = await pdfPage.screenshot({ animations: "disabled" }).catch(() => null);
      const identityMatches = cleanNumber(pdfPage.url()).includes(cleanNumber(record));
      return {
        ready: Boolean(identityMatches && renderedPatentPdfScreenshot(screenshot)),
        signature: screenshot
          ? crypto.createHash("sha256").update(screenshot).digest("hex")
          : "",
        screenshot,
      };
    }, {
      timeoutMs: timeout,
      pollMs: Number(config.cdp?.semantic_poll_ms || 750),
      stableSamples: Number(config.cdp?.semantic_stable_samples || 3),
    });
    if (!stable.stable || !stable.screenshot) return { attempted: true, path: null };
    const figurePath = path.join(
      taskDir, "screenshots", `uspto-patent-${slug(record)}-figures.png`,
    );
    await fs.writeFile(figurePath, stable.screenshot, { mode: 0o600 });
    return { attempted: true, path: figurePath };
  } finally {
    if (ownsPage) await pdfPage.close().catch(() => {});
  }
}

function isDesignRecord(record) {
  return /^(?:US)?D\d{6,8}(?:S\d?)?$/.test(cleanNumber(record));
}

export function patentBasicSearchTerm(record) {
  const normalized = cleanNumber(record);
  const design = normalized.match(/^(?:US)?D(\d{6,8})(?:S\d?)?$/);
  if (design) return `D${design[1]}`;
  const utility = normalized.match(/^US(\d{6,11})(?:[A-Z]\d?)?$/);
  return utility?.[1] || String(record || "").trim();
}

async function firstPatentDrawing(page) {
  const elements = page.locator("img, canvas, object, embed");
  const count = Math.min(await elements.count(), 120);
  for (let index = 0; index < count; index += 1) {
    const element = elements.nth(index);
    if (!await element.isVisible().catch(() => false)) continue;
    const info = await element.evaluate((node) => {
      const rect = node.getBoundingClientRect();
      const source = node.currentSrc || node.src || node.data || "";
      const alt = node.alt || "";
      return {
        width: Math.max(Number(node.naturalWidth || 0), rect.width),
        height: Math.max(Number(node.naturalHeight || 0), rect.height),
        source: String(source),
        alt: String(alt),
      };
    }).catch(() => null);
    if (!info || info.width < 180 || info.height < 180) continue;
    if (/logo|header|icon|sprite/i.test(`${info.source} ${info.alt}`)) continue;
    return element;
  }
  return null;
}

async function patentDetailSnapshot(page, record, parsed, externalDrawingReady = false) {
  const state = await freshState(page);
  const bodyClean = cleanNumber(state.bodyText);
  const requested = cleanNumber(record);
  const identityMatches = bodyClean.includes(requested) || cleanNumber(state.url).includes(requested);
  const title = parsed?.title
    || extractAfterLabel(state.bodyText, ["Title"])
    || "";
  let legalStatus = parsed?.legal_status
    || extractAfterLabel(state.bodyText, ["Status", "Legal Status"])
    || "";
  if (!legalStatus && /date of patent|united states (?:design )?patent/i.test(state.bodyText)) {
    legalStatus = "Issued";
  }
  const owners = parsed?.owners?.length
    ? parsed.owners
    : [extractAfterLabel(state.bodyText, ["Assignee", "Applicant", "Applicant(s)"])].filter(Boolean);
  const drawing = isDesignRecord(record) && !externalDrawingReady
    ? await firstPatentDrawing(page)
    : null;
  const designDrawingReady = !isDesignRecord(record) || externalDrawingReady || Boolean(drawing);
  const ready = identityMatches
    && Boolean(title)
    && Boolean(legalStatus)
    && owners.length > 0
    && designDrawingReady;
  return {
    ready,
    signature: JSON.stringify({
      url: state.url,
      identityMatches,
      title,
      legalStatus,
      owners,
      designDrawingReady,
    }),
    state,
    page_record_number: identityMatches ? record : "",
    title,
    legal_status: legalStatus,
    owners,
    drawing_ready: designDrawingReady,
    noResult: explicitNoResult(state.bodyText),
    challenge: detectChallenge(state.url, state.title, state.bodyText),
  };
}

export function extractAfterLabel(text, labels) {
  const lines = String(text || "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  for (let index = 0; index < lines.length; index += 1) {
    for (const label of labels) {
      const pattern = new RegExp(`^${label}\\s*[:#-]?\\s*(.*)$`, "i");
      const match = lines[index].match(pattern);
      if (match?.[1]) return match[1].trim();
      if (match && lines[index + 1]) return lines[index + 1];
    }
  }
  return "";
}

async function verifyCandidate(args, config) {
  const taskDir = path.resolve(String(args.task_dir || ""));
  const provider = String(args.provider || "");
  const record = String(args.record || "").trim();
  if (!["uspto_tsdr", "uspto_patent_browser"].includes(provider) || !record) {
    throw new Error("verify-candidate requires --provider uspto_tsdr|uspto_patent_browser and --record");
  }
  const session = await connectSession(config);
  const provenance = sanitizedSession(session.version, session.sessionId);
  const page = await session.context.newPage();
  const timeout = Number(config.cdp?.navigation_timeout_ms || 45000);
  let state;
  let candidate = null;
  let actionError = "";
  let patentSemantic = null;
  let detailOpened = false;
  let figureCaptureAttempted = false;
  const evidenceImages = [];

  if (provider === "uspto_tsdr") {
    const serial = record.replace(/\D/g, "");
    if (serial.length !== 8) throw new Error("TSDR record must be an eight-digit serial number");
    ({ state } = await navigateAndRefresh(
      page,
      `https://tsdr.uspto.gov/#caseNumber=${serial}&caseSearchType=US_APPLICATION&caseType=SERIAL_NO&searchType=statusSearch`,
      timeout,
    ));
    await page.waitForTimeout(1500);
    state = await freshState(page);
    candidate = {
      serial_number: serial,
      page_case_number: extractAfterLabel(state.bodyText, ["Serial Number", "Case Number"]) || serial,
      registration_number: extractAfterLabel(state.bodyText, ["Registration Number"]),
      mark_text: extractAfterLabel(state.bodyText, ["Mark Literal Elements", "Word Mark"]),
      case_status: extractAfterLabel(state.bodyText, ["Status", "Current Status"]),
      owners: [extractAfterLabel(state.bodyText, ["Owner Name", "Current Owner"])].filter(Boolean),
      goods_services: [extractAfterLabel(state.bodyText, ["Goods and Services", "Identification"])].filter(Boolean),
    };
  } else {
    await navigateAndRefresh(page, config.providers.uspto_patent_browser.basic_search_url, timeout);
    let parsed = null;
    try {
      await submitSearch(page, patentBasicSearchTerm(record));
      await page.waitForLoadState("domcontentloaded", { timeout }).catch(() => {});
      const searchSemantic = await waitForSearchSemanticState(
        page, "uspto_patent_browser", timeout, config,
      );
      parsed = (searchSemantic.candidates || []).find((item) =>
        cleanNumber(item.record_number) === cleanNumber(record)
      ) || null;
      const resultRow = await matchingPatentResultRow(page, record);
      const figureCapture = await capturePatentPdfFigure(
        session.context, page, resultRow, taskDir, record, timeout, config,
      );
      figureCaptureAttempted = figureCapture.attempted;
      if (figureCapture.path) {
        evidenceImages.push({
          path: figureCapture.path,
          label: `USPTO patent figures ${cleanNumber(record)}`,
          role: "official_drawing",
        });
      }
      const link = await matchingPatentResultLink(resultRow, ["Text", "Preview"]);
      if (link) {
        const detailHref = await link.getAttribute("href").catch(() => "");
        if (!detailHref) throw new Error("The patent detail link had no target URL");
        await page.goto(new URL(detailHref, page.url()).toString(), {
          waitUntil: "domcontentloaded",
          timeout,
        });
        await page.waitForLoadState("domcontentloaded", { timeout }).catch(() => {});
        state = await freshState(page);
        detailOpened = cleanNumber(state.url).includes(cleanNumber(record))
          || cleanNumber(state.bodyText).includes(cleanNumber(record));
        if (detailOpened) {
          await updateCandidateJournal(taskDir, {
            provider,
            record_number: record,
            title: parsed?.title || "",
            status: "pending",
            opened_at: nowIso(),
            final_url: sanitizeEvidenceUrl(state.url),
          });
        }
        if (isDesignRecord(record)) {
          await page.evaluate(() => scrollTo(0, document.body.scrollHeight)).catch(() => {});
        }
        patentSemantic = await waitForStableSemanticState(
          () => patentDetailSnapshot(page, record, parsed, evidenceImages.length > 0),
          {
            timeoutMs: timeout,
            pollMs: Number(config.cdp?.semantic_poll_ms || 750),
            stableSamples: Number(config.cdp?.semantic_stable_samples || 3),
          },
        );
        state = patentSemantic.state || state;
      }
    } catch (error) {
      actionError = sanitizeSensitiveText(error?.message || error);
    }
    state = await freshState(page);
    const detail = patentSemantic
      || await patentDetailSnapshot(page, record, parsed, evidenceImages.length > 0);
    candidate = {
      record_number: record,
      page_record_number: detail.page_record_number
        || extractAfterLabel(state.bodyText, ["Document ID", "Patent Number"])
        || "",
      publication_number: extractAfterLabel(state.bodyText, ["Publication Number"]),
      application_number: extractAfterLabel(state.bodyText, ["Application Number"]),
      grant_number: extractAfterLabel(state.bodyText, ["Patent Number", "Grant Number"]),
      title: detail.title || "",
      legal_status: detail.legal_status || "",
      owners: detail.owners || [],
    };
  }

  const screenshotPath = path.join(taskDir, "screenshots", `${slug(provider)}-${slug(record)}.png`);
  await safeScreenshot(page, screenshotPath);
  if (provider === "uspto_patent_browser"
      && isDesignRecord(record)
      && patentSemantic?.stable
      && !evidenceImages.length) {
    const drawing = await firstPatentDrawing(page);
    if (drawing) {
      const drawingPath = path.join(taskDir, "screenshots", `uspto-design-${slug(record)}-drawing.png`);
      await drawing.screenshot({ path: drawingPath, animations: "disabled" });
      evidenceImages.push({
        path: drawingPath,
        label: `USPTO design drawing ${cleanNumber(record)}`,
        role: "official_drawing",
      });
    }
  }
  state ||= await freshState(page);
  const challenge = detectChallenge(state.url, state.title, state.bodyText);
  let status = "access_limited";
  let detail = "";
  if (challenge) {
    status = "needs_user_action";
    detail = "The official USPTO page requires user action in visible Chrome.";
  } else if (provider === "uspto_tsdr") {
    if (candidate.case_status && candidate.owners.length && candidate.goods_services.length) status = "success";
    else if (explicitNoResult(state.bodyText)) status = "no_result";
    else detail = "TSDR identity/status/owner/goods fields could not all be confirmed from rendered content.";
  } else {
    const identityMatches = cleanNumber(candidate.page_record_number) === cleanNumber(record)
      && cleanNumber(state.url).includes(cleanNumber(record));
    if (figureCaptureAttempted && !evidenceImages.length) {
      detail = "The patent PDF opened, but no non-blank stable figure frame was captured.";
    } else if (!patentSemantic?.timed_out
        && patentSemantic?.stable
        && identityMatches
        && candidate.title
        && candidate.legal_status
        && candidate.owners.length
        && (!isDesignRecord(record) || evidenceImages.length > 0)) {
      status = "success";
    }
    else if (explicitNoResult(state.bodyText)) status = "no_result";
    else if (!detail) detail = actionError
      ? `Patent verification could not be confirmed after refreshing page state: ${actionError.slice(0, 300)}`
      : patentSemantic?.timed_out
        ? "Patent detail fields did not become stable before timeout."
        : isDesignRecord(record) && !evidenceImages.length
          ? "The design record loaded, but an official drawing did not become available."
          : "Patent identity/title/status/owner fields could not all be confirmed from rendered content.";
  }
  const capture = {
    ...provenance,
    status,
    ...candidate,
    final_url: sanitizeEvidenceUrl(state.url),
    checked_at: nowIso(),
    screenshot_path: screenshotPath,
    ...(evidenceImages.length ? { evidence_images: evidenceImages, views: evidenceImages.map((item) => item.label) } : {}),
    ...(status === "no_result" ? { result_message: "The rendered official page explicitly reported no matching record." } : {}),
    ...(detail ? { detail } : {}),
  };
  assertNoSensitiveKeys(capture);
  const capturePath = path.join(taskDir, `${slug(provider)}-${slug(record)}-capture.json`);
  await writeJsonAtomic(capturePath, capture);
  if (provider === "uspto_patent_browser" && detailOpened) {
    await updateCandidateJournal(taskDir, {
      provider,
      record_number: record,
      title: candidate.title || "",
      status,
      final_url: sanitizeEvidenceUrl(state.url),
      screenshot_path: screenshotPath,
      capture_path: capturePath,
      completed_at: nowIso(),
    });
  }
  return { status, provider, record, capture_path: capturePath };
}

async function doctor(config) {
  const session = await connectSession(config);
  const result = {
    status: "success",
    ...sanitizedSession(session.version, session.sessionId),
    endpoint_scope: "loopback",
    profile_is_dedicated: true,
    headless: false,
    contexts: session.browser.contexts().length,
    pages: session.context.pages().length,
    launched: session.launched,
  };
  return result;
}

function printHelp() {
  process.stdout.write(`Usage:
  node cdp-cli.mjs doctor
  node cdp-cli.mjs capture-amazon --task-dir /absolute/run
  node cdp-cli.mjs run-planned-query --task-dir /absolute/run --query-id QRY-...
  node cdp-cli.mjs verify-candidate --task-dir /absolute/run --provider uspto_tsdr|uspto_patent_browser --record ID
`);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.command || args.command === "help" || args.command === "--help") {
    printHelp();
    return;
  }
  const config = await loadConfig();
  let result;
  if (args.command === "doctor") result = await doctor(config);
  else if (args.command === "capture-amazon") result = await captureAmazon(args, config);
  else if (args.command === "run-planned-query") result = await runPlannedQuery(args, config);
  else if (args.command === "verify-candidate") result = await verifyCandidate(args, config);
  else throw new Error(`Unknown command: ${args.command}`);
  assertNoSensitiveKeys(result, "result");
  const exitCode = ["failed", "access_limited"].includes(result.status) ? 2 : 0;
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`, () => process.exit(exitCode));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    process.stderr.write(`CDP command failed: ${error?.message || error}\n`, () => process.exit(1));
  });
}
