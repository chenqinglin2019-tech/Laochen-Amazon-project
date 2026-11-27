() => {
  // 在 Amazon 商品页里运行，取商品资料。EGO 和 Chrome 两种采集方式共用这一段。
  const clean = (value) => (value || "").replace(/\s+/g, " ").trim();
  const text = (selector) => clean((document.querySelector(selector) || {}).textContent);
  const visible = (node) => node && !node.closest(".aok-hidden, [hidden], [aria-hidden='true']");
  const bodyText = clean((document.body && document.body.innerText) || "").slice(0, 6000);
  const pageTitle = document.title || "";
  const path = location.pathname;

  // 要用户处理的情况：验证码、登录页。页面上已经有商品标题就不算（导航栏里也有登录表单，不能误判）
  const hasProduct = !!document.querySelector("#productTitle");
  let blocked = "";
  if (hasProduct) {
    blocked = "";
  } else if (document.querySelector("form[action*='validateCaptcha'], #captchacharacters, iframe[src*='captcha'], #aacb-captcha-header")
      || /robot check|bot check/i.test(pageTitle)
      || /enter the characters you see|type the characters you see|geben sie die zeichen|saisissez les caractères|inserisci i caratteri|introduce los caracteres|画像に表示されている文字/i.test(bodyText)) {
    blocked = "captcha";
  } else if (/\/ap\/(signin|mfa|cvf|challenge)/.test(path)) {
    blocked = "login";
  }
  // "点一下继续购物"的中间页：脚本可以自己点
  const continueButton = [...document.querySelectorAll("button, input[type='submit'], a.a-button-text")]
    .find((node) => /continue shopping|weiter einkaufen|weiter shoppen|continuer les achats|continua con gli acquisti|seguir comprando|ショッピングを続ける/i
      .test(node.textContent || node.value || ""));
  const interstitial = !document.querySelector("#productTitle") && !!continueButton && !blocked;

  const title = text("#productTitle") || text("#title");
  const missing = !title && !blocked && !interstitial
    && (/page not found|couldn't find that page|seite wurde nicht gefunden|page introuvable|pagina non trovata|no se ha encontrado|ページが見つかりません/i.test(pageTitle + " " + bodyText.slice(0, 800))
      || !!document.querySelector("img[alt*='Dogs of Amazon'], a[href*='/dogsofamazon']"));

  const bullets = [...document.querySelectorAll("#feature-bullets ul li span.a-list-item, #productFactsDesktopExpander ul li span.a-list-item")]
    .filter(visible).map((node) => clean(node.textContent)).filter((value) => value && value.length > 3);
  const category = [...document.querySelectorAll("#wayfinding-breadcrumbs_feature_div ul li a")].map((node) => clean(node.textContent)).filter(Boolean).join(" > ");
  const brandRaw = text("#bylineInfo");
  const brand = clean(brandRaw.replace(/^(brand:|marke:|marque\s*:|marca:|ブランド:)/i, "").replace(/^visit the (.+) store$/i, "$1")
    .replace(/^besuche den (.+)-store$/i, "$1").replace(/^visiter la boutique (.+)$/i, "$1").replace(/^visita lo store di (.+)$/i, "$1")
    .replace(/^visita la tienda de (.+)$/i, "$1"));
  const description = text("#productDescription").slice(0, 2000);
  const asinInput = document.querySelector("input#ASIN, input[name='ASIN']");
  const asin = ((asinInput && asinInput.value) || (path.match(/\/(?:dp|gp\/product|gp\/aw\/d)\/([A-Za-z0-9]{10})/) || [])[1] || "").toUpperCase();

  // 图片：先取页面脚本里当前款式的大图，再用页面上的主图和缩略图兜底
  const urls = [];
  const add = (url) => {
    // 地址里常带一段 /images/W/…/ 的中间路径，统一成 https://m.media-amazon.com/images/I/文件名
    const match = (url || "").match(/^https:\/\/[^/]*media-amazon\.com\/(?:.*\/)?images\/I\/([^/?#]+)/i);
    if (!match || /play-icon|PKdp-|\.gif$/i.test(match[1])) return;
    const key = match[1].split(".")[0];
    if (!key || urls.some((item) => item.key === key)) return;
    urls.push({ key, url: "https://m.media-amazon.com/images/I/" + match[1] });
  };
  for (const script of document.querySelectorAll("script:not([src])")) {
    const source = script.textContent || "";
    if (!source.includes("colorImages") && !source.includes("ImageBlockATF")) continue;
    const start = source.indexOf("'initial'") >= 0 ? source.indexOf("'initial'") : source.indexOf('"initial"');
    const block = start >= 0 ? source.slice(start, start + 60000) : source;
    for (const match of block.matchAll(/"hiRes":"(https:[^"]+)"/g)) add(match[1]);
    if (!urls.length) for (const match of block.matchAll(/"large":"(https:[^"]+)"/g)) add(match[1]);
    if (urls.length) break;
  }
  const landing = document.querySelector("#landingImage, #imgBlkFront, #main-image");
  if (landing) add(landing.getAttribute("data-old-hires") || landing.src);
  for (const thumb of document.querySelectorAll("#altImages li.imageThumbnail img, #altImages li.item img")) {
    add((thumb.src || "").replace(/\.[^./]*_\.(jpe?g|png|webp)$/i, "._AC_SL1500_.$1"));
  }

  const claimText = [title, ...bullets, description].join("\n");
  const marking = [...new Set((claimText.match(/[^.\n]{0,40}(patent(?:ed| pending)?|pat\. ?(?:no|pending)|US ?D?\d{1,2},?\d{3},?\d{3}|特許|意匠登録|gebrauchsmuster|brevet)[^.\n]{0,40}/gi) || []).map(clean))].slice(0, 5);

  return {
    url: location.href, pageTitle, blocked, interstitial, missing,
    title, brand, brandRaw, category, bullets: bullets.slice(0, 10), description, asin,
    images: urls.map((item) => item.url), marking,
    unavailable: /currently unavailable|derzeit nicht verfügbar|actuellement indisponible|non disponibile|no disponible|現在在庫切れ|現在お取り扱いできません/i.test(text("#availability")),
  };
}
