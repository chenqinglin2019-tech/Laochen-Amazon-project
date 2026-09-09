/** Read visible Serper account evidence. This collector never grants entitlement. */
import { createHash, randomUUID } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";

const ORIGIN = "https://serper.dev";
const sha256 = value => createHash("sha256").update(value, "utf8").digest("hex");
const EMAIL = /[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9.-]*[A-Z0-9])?\.[A-Z]{2,}/gi;
const TOKENS = /[A-Za-z0-9_+/=-]{16,512}/g;
const ACCOUNT_LINK = /(?:account|dashboard|credits|billing|api[-_\s]?keys?)/i;
const MUTATION_LINK = /(?:log[-_\s]?out|sign[-_\s]?out|delete|purchase|buy|checkout|upgrade|recharge|top[-_\s]?up|subscribe|create|generate|reveal|revoke|rotate|activate|reset|cancel)/i;

function officialUrl(value) {
  try {
    const url = new URL(value);
    return url.origin === ORIGIN && !url.username && !url.password ? url : null;
  } catch { return null; }
}

function safePageUrl(value) {
  const url = officialUrl(value);
  if (!url) return "";
  // Query strings and fragments can carry credentials or login tokens.
  return `${url.origin}${url.pathname.replace(EMAIL, email => `[account-sha256:${sha256(email.toLowerCase())}]`)
    .replace(TOKENS, token => `[redacted-sha256:${sha256(token)}]`)}`;
}

function observedAccountLink(link, base) {
  if (typeof link?.href !== "string" || typeof link?.text !== "string") return null;
  let url;
  try { url = officialUrl(new URL(link.href, base).href); } catch { return null; }
  if (!url || url.search || MUTATION_LINK.test(`${url.pathname} ${link.text}`)
      || !ACCOUNT_LINK.test(`${url.pathname} ${link.text}`)) return null;
  url.hash = "";
  return url.href;
}

async function visiblePage(page) {
  return page.evaluate(() => {
    const body = document.body;
    if (!body) return { text: "", links: [], passwordVisible: false };
    const visible = element => {
      if (!element.getClientRects().length || element.closest('[hidden], [aria-hidden="true"]')) return false;
      for (let current = element; current; current = current.parentElement) {
        const style = getComputedStyle(current);
        if (style.visibility === "hidden" || style.display === "none" || style.opacity === "0"
            || style.fontSize === "0px") return false;
      }
      return true;
    };
    // Traverse rendered body content without reading hidden/password values or
    // script payloads. Do not manufacture label/value punctuation for the parser.
    const renderedText = element => {
      if (!visible(element) || /^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE)$/.test(element.tagName)) return "";
      if (element.tagName === "INPUT") {
        if (/password|passwd|(?:^|\W)pwd(?:$|\W)/i.test(`${element.name} ${element.id} ${element.autocomplete}`)) return "";
        return ["text", "email", "url", "search"].includes(element.type) ? element.value : "";
      }
      if (element.tagName === "TEXTAREA") return element.value;
      if (element.tagName === "BR") return "\n";
      const style = getComputedStyle(element);
      if (style.fontSize === "0px") return "";
      let value = "";
      for (const child of element.childNodes) {
        if (child.nodeType === Node.TEXT_NODE) {
          value += /^(?:pre|break-spaces)/.test(style.whiteSpace)
            ? child.nodeValue : child.nodeValue.replace(/[\t\r\n ]+/g, " ");
        } else if (child.nodeType === Node.ELEMENT_NODE) value += renderedText(child);
      }
      return /^(?:block|flex|grid|table|list-item)/.test(style.display) ? `\n${value}\n` : value;
    };
    return {
      text: renderedText(body).trim(),
      links: Array.from(body.querySelectorAll("a[href]")).filter(visible)
        .map(element => ({ href: element.href, text: element.innerText })),
      passwordVisible: Array.from(body.querySelectorAll('input[type="password"]')).some(visible),
    };
  });
}

function sanitizeText(text, fingerprint) {
  const credentials = new Set((text.match(TOKENS) || []).filter(token => sha256(token) === fingerprint));
  // A mismatched displayed API key is sensitive too; do not put it in a failure receipt.
  const labelled = /(?:api[\s_-]*key|x-api-key|authorization|bearer)\s*[=:：]?\s*["']?([A-Za-z0-9_+/=-]{16,512})/gi;
  for (const match of text.matchAll(labelled)) credentials.add(match[1]);
  for (const token of text.match(TOKENS) || []) {
    if (/^[a-f0-9]{32,128}$/i.test(token)) credentials.add(token);
  }
  let safe = text;
  for (const token of [...credentials].sort((a, b) => b.length - a.length)) {
    safe = safe.split(token).join(`[credential-sha256:${sha256(token)}]`);
  }
  safe = safe.replace(EMAIL, email => `[account-sha256:${sha256(email.toLowerCase())}]`);
  return { text: safe, credentialMatched: [...credentials].some(token => sha256(token) === fingerprint),
    credentialSeen: credentials.size > 0 };
}

function accountEmails(text, credentialMatched) {
  const labelled = /(?:^|\n)\s*(?:account(?:\s+(?:email|id))?|email(?:\s+address)?|signed\s+in\s+as|logged\s+in\s+as|账户|邮箱)\s*[:：]?\s*([^\s<>]+@[^\s<>]+)/gi;
  const results = [];
  for (const match of text.matchAll(labelled)) {
    const found = match[1].match(EMAIL);
    if (found?.length === 1) results.push(found[0].toLowerCase());
  }
  // An unlabelled header email is usable only beside the actual matching key,
  // and only when it is the sole non-support address on that rendered page.
  if (!results.length && credentialMatched) {
    const emails = [...new Set((text.match(EMAIL) || []).map(value => value.toLowerCase()))]
      .filter(value => !/^(?:support|hello|contact|info)@serper\.dev$/.test(value));
    if (emails.length === 1) results.push(emails[0]);
  }
  return results;
}

async function persist(outputPath, result) {
  if (!outputPath) return result;
  const target = path.resolve(outputPath);
  await fs.mkdir(path.dirname(target), { recursive: true, mode: 0o700 });
  const temp = `${target}.${randomUUID()}.tmp`;
  try {
    await fs.writeFile(temp, `${JSON.stringify(result, null, 2)}\n`, { mode: 0o600, flag: "wx" });
    await fs.rename(temp, target);
  } catch {
    await fs.rm(temp, { force: true }).catch(() => {});
    throw new Error("SERPER_ACCOUNT_CAPTURE_WRITE_FAILED");
  }
  return result;
}

export async function captureSerperAccount({ context, credentialFingerprint, outputPath } = {}) {
  const result = { schema: "SERPER-ACCOUNT-CAPTURE/1.0", collector: "cdp-serper-account-v1",
    source_environment: "production", captured_at: new Date().toISOString(),
    credential_fingerprint: null, account_fingerprint: null, pages: [], status: "blocked" };
  const finish = (status, errorCode, message) => persist(outputPath,
    { ...result, captured_at: new Date().toISOString(), status, ...(errorCode ? { error_code: errorCode } : {}), message });
  if (typeof credentialFingerprint !== "string" || !/^[a-f0-9]{64}$/.test(credentialFingerprint)) {
    return finish("blocked", "CREDENTIAL_FINGERPRINT_REQUIRED", "需要现有凭据读取入口提供 SHA-256；尚未读取账户页面。");
  }
  result.credential_fingerprint = credentialFingerprint;
  if (!context || typeof context.pages !== "function" || typeof context.newPage !== "function") {
    return finish("blocked", "BROWSER_CONTEXT_REQUIRED", "需要已连接的浏览器上下文。");
  }
  let page;
  let matched = false, credentialSeen = false, loginRequired = false;
  const accounts = new Set(), visited = new Set(), pending = [];
  try {
    page = context.pages().find(candidate => officialUrl(candidate.url()));
    if (!page) {
      page = await context.newPage();
      await page.goto(ORIGIN, { waitUntil: "domcontentloaded", timeout: 15000 });
    }
    for (let navigations = 0; ; ) {
      const current = page.url();
      if (!officialUrl(current)) {
        loginRequired = true;
        break; // Never read an identity-provider page after a redirect.
      }
      const snapshot = await visiblePage(page);
      const text = typeof snapshot.text === "string" ? snapshot.text : "";
      const sanitized = sanitizeText(text, credentialFingerprint);
      matched ||= sanitized.credentialMatched;
      credentialSeen ||= sanitized.credentialSeen;
      for (const email of accountEmails(text, sanitized.credentialMatched)) accounts.add(sha256(email));
      result.pages.push({ url: safePageUrl(current), captured_at: new Date().toISOString(),
        text: sanitized.text, sha256: sha256(sanitized.text) });
      visited.add(new URL(current).href.split("#")[0]);
      loginRequired ||= snapshot.passwordVisible === true || /(?:^|\n)\s*(?:sign\s*in|log\s*in|verify (?:you are human|your (?:email|identity))|captcha)\s*(?:$|\n)/i.test(text)
        || /\/(?:login|sign[-_]?in)(?:\/|$)/i.test(new URL(current).pathname);
      if (loginRequired || navigations >= 5) break;
      for (const link of Array.isArray(snapshot.links) ? snapshot.links : []) {
        const next = observedAccountLink(link, current);
        if (next && !visited.has(next) && !pending.includes(next)) pending.push(next);
      }
      const next = pending.find(value => !visited.has(value));
      if (!next) break;
      pending.splice(pending.indexOf(next), 1);
      navigations += 1;
      await page.goto(next, { waitUntil: "domcontentloaded", timeout: 15000 });
    }
  } catch {
    return finish("blocked", "ACCOUNT_PAGE_CAPTURE_FAILED", "账户页面读取未完成；未执行登录、显示密钥或账户更改。");
  }
  if (loginRequired) return finish("needs_user_action", "ACCOUNT_ACCESS_REQUIRED", "请在官方页面完成登录或访问验证后重试；采集器不会自动登录或显示密钥。");
  if (!matched) return finish("blocked", credentialSeen ? "CREDENTIAL_BINDING_MISMATCH" : "CREDENTIAL_NOT_VISIBLE",
    "未在可见账户文字中取得与当前凭据匹配的密钥；不能据本地指纹建立账户证明。");
  if (accounts.size !== 1) return finish("blocked", accounts.size ? "ACCOUNT_IDENTITY_AMBIGUOUS" : "ACCOUNT_IDENTITY_NOT_VISIBLE",
    "未取得唯一的可见账户邮箱标识，不能建立账户证明。");
  result.account_fingerprint = [...accounts][0];
  return finish("success", "", "已采集并脱敏可见账户原文；免费余额、计量单位、付费余额和自动充值仍由证明验收器检查。");
}
