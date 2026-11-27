// 用本机 Chrome 采集 Amazon 商品页（没装 EGO 浏览器时用）。输入从标准输入读一段 JSON，结果打印成一行 IPR_RESULT。
// 依赖 playwright-core（安装脚本在 tools/ 里装）。用单独的浏览器资料目录，过了一次验证码后下次不用再过。
import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright-core";

const out = (payload) => console.log("IPR_RESULT " + JSON.stringify(payload));
let input = "";
for await (const chunk of process.stdin) input += chunk;
const INPUT = JSON.parse(input);
let context;
try {
  await fs.mkdir(INPUT.profileDir, { recursive: true });
  context = await chromium.launchPersistentContext(INPUT.profileDir, { channel: "chrome", headless: false, viewport: null });
  const page = context.pages()[0] || (await context.newPage());
  const read = () => page.evaluate("(" + INPUT.extract + ")()");
  // 打开商品页并读一遍；遇到"继续购物"的中间页点过去再读
  const open = async () => {
    await page.goto(INPUT.url, { waitUntil: "domcontentloaded", timeout: INPUT.timeout });
    let now = await read();
    for (let round = 0; round < 2 && now.interstitial; round += 1) {
      await page.evaluate(() => {
        const button = [...document.querySelectorAll("button, input[type='submit'], a.a-button-text")]
          .find((node) => /continue shopping|weiter einkaufen|weiter shoppen|continuer les achats|continua con gli acquisti|seguir comprando|ショッピングを続ける/i
            .test(node.textContent || node.value || ""));
        if (button) button.click();
      });
      await page.waitForTimeout(2500);
      now = await read();
    }
    return now;
  };
  const onProduct = () => /\/(dp|gp\/product|gp\/aw\/d)\//.test(page.url());
  let state = await open();
  // 验证码或登录：窗口开着，等用户处理一会儿；处理完自动继续，没处理就停下让用户续跑
  const wasBlocked = Boolean(state.blocked);
  const deadline = Date.now() + INPUT.waitForUserSeconds * 1000;
  while (state.blocked && Date.now() < deadline) {
    await page.waitForTimeout(3000);
    state = await read().catch(() => state);
  }
  if (wasBlocked && !state.blocked) {
    await page.waitForLoadState("domcontentloaded").catch(() => {});
    state = await read().catch(() => state);
  }
  // 过完验证或登录，Amazon 常把人带到首页而不是原来的商品页：回到商品页再读一遍
  if (!state.blocked && !state.title && (wasBlocked || !onProduct())) {
    state = await open();
  }
  if (!state.title && !state.blocked && !state.missing) {
    await page.waitForSelector("#productTitle", { timeout: 15000 }).catch(() => {});
    state = await read();
  }
  if (state.blocked) {
    out({ status: "blocked", kind: state.blocked, url: state.url });
  } else if (state.missing || !state.title) {
    out({ status: state.missing ? "missing" : "no_title", url: state.url, pageTitle: state.pageTitle });
  } else {
    const saved = [];
    const failed = [];
    await fs.mkdir(INPUT.imageDir, { recursive: true });
    for (const [index, url] of state.images.slice(0, INPUT.maxImages).entries()) {
      const extension = (url.match(/\.(jpe?g|png|webp)(?:$|\?)/i) || [, "jpg"])[1].toLowerCase().replace("jpeg", "jpg");
      const file = path.join(INPUT.imageDir, "IMG-" + String(index + 1).padStart(3, "0") + "." + extension);
      try {
        const response = await context.request.get(url, { timeout: 20000 });
        if (!response.ok()) throw new Error("status " + response.status());
        await fs.writeFile(file, await response.body());
        saved.push({ file, url });
      } catch (error) { failed.push(url); }
    }
    out({ status: "ok", product: state, images: saved, failedImages: failed });
  }
} catch (error) {
  out({ status: "error", message: String((error && error.message) || error).slice(0, 400) });
} finally {
  if (context) await context.close().catch(() => {});
}
