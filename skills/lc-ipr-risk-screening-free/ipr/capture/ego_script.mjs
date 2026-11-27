// 交给 `ego-browser nodejs` 运行的采集脚本。下面两个常量的值由 ego.py 填入。
// 这段脚本跑在 EGO 自带的 Node.js 里：不继承终端的工作目录和环境变量，所有路径都是绝对路径。
const INPUT = __INPUT__;
const EXTRACT = __EXTRACT__;
let printed = false;
const out = (payload) => { printed = true; console.log("IPR_RESULT " + JSON.stringify(payload)); };
// 结果已经打印出去之后，收尾出错不能把结果改判成失败
const finish = async (task) => { try { await task.finish({ keep: [] }); } catch (error) { /* 收尾失败不影响结果 */ } };
const fs = await import("node:fs/promises");
const nodePath = await import("node:path");

let task;
let page;
try {
  const entry = INPUT.spaceId === null ? undefined : (await listTaskSpaces()).find((item) => item.id === INPUT.spaceId);
  if (!entry) {
    task = await taskSpace("侵权排查 采集商品 " + INPUT.label);
  } else if (entry.ownership === "user") {
    task = await claimTaskSpace(INPUT.spaceId);
  } else if (entry.ownership === "agentDelegatedToUser") {
    task = await takeOverTaskSpace(INPUT.spaceId);
  } else {
    task = await taskSpace(INPUT.spaceId);
  }
  page = (await task.pages())[0];
  if (!page) {
    const tabs = await task.tabs();
    page = tabs.length ? await task.adopt(tabs[0].page) : await task.newPage();
  }

  const read = async () => page.evaluate("(" + EXTRACT + ")()");
  // 续跑时页面还停在同一个商品上才接着用，否则重新打开
  const current = entry ? String(await page.url()) : "";
  const onProduct = /\/(dp|gp\/product|gp\/aw\/d)\//.test(current) && (!INPUT.asin || current.toUpperCase().includes("/" + INPUT.asin));
  if (!onProduct) await page.goto(INPUT.url, { timeout: INPUT.timeout });
  await page.waitForLoadState().catch(() => {});
  let state = await read();
  for (let round = 0; round < 2 && state.interstitial; round += 1) {
    // "继续购物"的中间页：点一下再读
    await page.evaluate(() => {
      const button = [...document.querySelectorAll("button, input[type='submit'], a.a-button-text")]
        .find((node) => /continue shopping|weiter einkaufen|weiter shoppen|continuer les achats|continua con gli acquisti|seguir comprando|ショッピングを続ける/i
          .test(node.textContent || node.value || ""));
      if (button) button.click();
    });
    await page.waitForTimeout(2500);
    await page.waitForLoadState().catch(() => {});
    state = await read();
  }
  if (!state.title && !state.blocked && !state.missing) {
    // 页面还没渲染完：再等一下标题
    await page.waitForSelector("#productTitle", { timeout: 15000 }).catch(() => {});
    state = await read();
  }

  if (state.blocked) {
    // 验证码或登录：交给用户在浏览器里处理，不结束这个工作区，续跑时接着用
    await task.handOff().catch(() => {});
    out({ status: "blocked", kind: state.blocked, spaceId: task.spaceId, url: state.url });
  } else if (state.missing || !state.title) {
    out({ status: state.missing ? "missing" : "no_title", url: state.url, pageTitle: state.pageTitle, spaceId: task.spaceId });
    await finish(task);
  } else {
    const saved = [];
    const failed = [];
    await fs.mkdir(INPUT.imageDir, { recursive: true });
    for (const [index, url] of state.images.slice(0, INPUT.maxImages).entries()) {
      const extension = (url.match(/\.(jpe?g|png|webp)(?:$|\?)/i) || [, "jpg"])[1].toLowerCase().replace("jpeg", "jpg");
      const file = nodePath.join(INPUT.imageDir, "IMG-" + String(index + 1).padStart(3, "0") + "." + extension);
      let ok = false;
      try {
        const response = await page.fetch(url, { saveAs: file, timeout: 20000 });
        ok = !!(response && response.ok);
      } catch (error) { ok = false; }
      if (!ok) {
        try {
          const response = await fetch(url, { signal: AbortSignal.timeout(20000) });
          if (response.ok) {
            await fs.writeFile(file, Buffer.from(await response.arrayBuffer()));
            ok = true;
          }
        } catch (error) { ok = false; }
      }
      if (ok) saved.push({ file, url }); else failed.push(url);
    }
    out({ status: "ok", product: state, images: saved, failedImages: failed, spaceId: task.spaceId });
    await finish(task);
  }
} catch (error) {
  if (!printed) {
    out({ status: "error", message: String((error && error.message) || error).slice(0, 400), spaceId: task ? task.spaceId : null });
    if (task) await finish(task);
  }
}
