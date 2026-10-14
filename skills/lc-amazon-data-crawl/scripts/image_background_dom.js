/* Public DOM only. Every action checks ownership before touching the page. */
function imageBackgroundDom(args) {
  const norm = value => (value || '').replace(/\s+/g, ' ').trim();
  const text = el => norm(el?.innerText || el?.textContent);
  const visible = el => !!el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
  const href = location.href.split('#')[0];
  // Only same-document canonical URL rewrites may be adopted on a read.
  const sameResource = (left, right) => {
    try {
      const a = new URL(left), b = new URL(right);
      if (a.protocol !== 'https:' || a.origin !== b.origin || a.username || a.password || b.username || b.password) return false;
      const key = u => {
        const product = u.pathname.match(/\/(?:dp|gp\/product)\/([A-Z0-9]{10})(?:\/ref=[^/?]*)?\/?$/i);
        const styles = /^\/stylesnap\/?$/.test(u.pathname) ||
          (/^\/products\/?$/.test(u.pathname) && u.searchParams.get('modes') === 'stylesnap');
        if (!product && !styles) return null;
        if (styles && (!u.searchParams.get('q') || u.searchParams.getAll('q').length !== 1)) return null;
        const domAsin = document.querySelector('input#ASIN')?.value;
        if (product && domAsin && domAsin.toUpperCase() !== product[1].toUpperCase()) return null;
        // th=1 is accepted only on a product whose DOM ASIN independently agrees.
        const allowTh = product && domAsin && domAsin.toUpperCase() === product[1].toUpperCase() &&
          u.searchParams.getAll('th').length === 1 && u.searchParams.get('th') === '1';
        const params = [...u.searchParams].filter(([k]) => !/^(psc|ref|ref_|_encoding|tag|pf_rd_.*|pd_rd_.*)$/.test(k) && !(styles && k === 'modes') && !(allowTh && k === 'th'));
        params.sort((x,y) => JSON.stringify(x).localeCompare(JSON.stringify(y)));
        return JSON.stringify([product ? 'product:' + product[1].toUpperCase() : 'stylesnap', params]);
      };
      const ka = key(a);
      return ka !== null && ka === key(b);
    } catch (_) { return false; }
  };
  let adoptedUrlRewrite = false;
  try {
    if (args.expectedUrl && args.expectedUrl !== href) {
      adoptedUrlRewrite = args.action === 'snapshot' && !!args.documentId &&
        document.documentElement?.dataset.lcImageDocument === args.documentId && sameResource(args.expectedUrl, href);
      if (!adoptedUrlRewrite) throw Error('工作页网址已变化');
    }
    if (args.documentId && document.documentElement?.dataset.lcImageDocument !== args.documentId)
      throw Error('工作页已刷新或被替换');
    // CDP can observe a navigation before the new document has a root node.
    // Only an unguarded read of a pending navigation may report this loading state.
    if (!document.documentElement && args.action === 'snapshot' && !args.documentId) {
      return {url: href, document_id: '', ready: false, document_loading: true,
        result_page: /^\/stylesnap(?:\/|$)/.test(location.pathname) ||
          (/^\/products(?:\/|$)/.test(location.pathname) && new URL(href).searchParams.get('modes') === 'stylesnap'), cards: []};
    }
    if (args.action === 'mark') {
      document.documentElement.dataset.lcImageDocument = args.id;
      return {url: href, document_id: args.id};
    }
    if (args.action === 'navigate') {
      // Return the acknowledgement before navigation destroys this JS context.
      setTimeout(() => location.assign(args.url), 100);
      return {navigating: true};
    }
    if (args.action === 'scroll') {
      const grid = document.querySelector('#product_grid_container');
      const target = grid && grid.scrollHeight > grid.clientHeight && /auto|scroll/.test(getComputedStyle(grid).overflowY)
        ? grid : document.scrollingElement;
      if (!target) throw Error('找不到滚动容器');
      target.scrollBy(0, Math.max(600, innerHeight * 0.85));
      return {scrolled: true};
    }
    const roots = [...document.querySelectorAll('#seller-sprite-extension-app')];
    if (roots.length > 1) throw Error('卖家精灵容器不唯一');
    const root = roots[0];
    // Only explicit, visible public account controls prove a logged-in state.
    const loggedIn = !!root && [...root.querySelectorAll('button,a,.el-dropdown-menu__item')]
      .some(el => visible(el) && /^(退出登录|退出账户|Sign out|Log out)$/i.test(text(el)));
    const guest = !!root && [...root.querySelectorAll('.guest-span-btn')]
      .some(el => visible(el) && /游客|未登录|guest|sign in/i.test(text(el)));
    const messages = root ? [...root.querySelectorAll('.el-message,.el-alert,.el-message-box,.error-box')]
      .filter(visible).map(text).join('\n') : '';
    const img = document.querySelector('#landingImage,#imgTagWrapperId img,#main-image');
    const selected = document.querySelector('ul.maintain-height .selected img');
    const sourceImage = selected?.src || img?.getAttribute('data-old-hires') || img?.currentSrc || img?.src || '';
    const asin = document.querySelector('input#ASIN')?.value || href.match(/\/(?:dp|gp\/product)\/([A-Z0-9]{10})(?:[/?]|$)/i)?.[1] || '';
    const body = text(document.body);
    const resultPage = /^\/stylesnap(?:\/|$)/.test(location.pathname) ||
      (/^\/products(?:\/|$)/.test(location.pathname) && new URL(href).searchParams.get('modes') === 'stylesnap');
    const grid = document.querySelector('#product_grid_container,[data-testid="product-grid"],[class*="ProductGrid"]');
    const noResults = resultPage && /no styles found|no matching (?:styles|products)|未找到相似商品|没有找到相似商品/i.test(body);
    const busy = [...document.querySelectorAll('[aria-busy="true"],.a-spinner-wrapper')].some(visible);
    const cards = resultPage ? (() => {

const includeText = true;
const asinRe = /\b([A-Z0-9]{10})\b/;
const asinUrlRe = /\/(?:dp|gp\/product)\/([A-Z0-9]{10})(?:[/?#]|$)/i;
const norm = (text) => (text || '').replace(/\s+/g, ' ').trim();
const absUrl = (href) => {
  try { return new URL(href, location.href).href; } catch (err) { return href || ''; }
};
const imageFromSrcset = (value) => {
  if (!value) return '';
  const parts = value.split(',').map(part => part.trim()).filter(Boolean);
  let best = '';
  let bestWidth = 0;
  for (const part of parts) {
    const items = part.split(/\s+/);
    const url = items[0] || '';
    const width = Number((items[1] || '').replace(/[^\d.]/g, '')) || 0;
    if (url && width >= bestWidth) {
      best = url;
      bestWidth = width;
    }
  }
  return best;
};
const usableImageUrl = (value) => {
  if (!value) return false;
  if (/^data:image\//i.test(value)) return true;
  try {
    const parsed = new URL(value, location.href);
    if (!/^https?:$/i.test(parsed.protocol)) return false;
    if (parsed.href.split('#')[0] === location.href.split('#')[0]) return false;
    if (/\/(?:dp|gp\/product)\//i.test(parsed.pathname)) return false;
    return /\/images\//i.test(parsed.pathname)
      || /\.(?:jpe?g|png|webp|gif|avif)$/i.test(parsed.pathname);
  } catch (err) {
    return false;
  }
};
const getAsin = (el) => {
  for (const attr of ['data-asin', 'asin', 'data-csa-c-asin', 'data-csa-c-item-id']) {
    const value = el.getAttribute(attr);
    if (!value) continue;
    const cleaned = value.trim();
    if (/^[A-Z0-9]{10}$/i.test(cleaned)) return cleaned.toUpperCase();
    const attrMatch = cleaned.match(/(?:^|[.:_-])([A-Z0-9]{10})(?:$|[.:_-])/i) || cleaned.match(/\basin\.([A-Z0-9]{10})\b/i);
    if (attrMatch) return attrMatch[1].toUpperCase();
  }
  for (const a of el.querySelectorAll('a[href]')) {
    const match = a.href.match(asinUrlRe);
    if (match) return match[1].toUpperCase();
  }
  const textMatch = norm(el.innerText || el.textContent || '').match(asinRe);
  return textMatch ? textMatch[1].toUpperCase() : '';
};
const getUrl = (el, asin) => {
  const links = [...el.querySelectorAll('a[href]')];
  for (const a of links) {
    if (asin && a.href.includes(asin)) return absUrl(a.href);
  }
  for (const a of links) {
    if (/\/(?:dp|gp\/product)\//i.test(a.href)) return absUrl(a.href);
  }
  return '';
};
const getTitle = (el) => {
  const selectors = ['h2 a span', 'h2 span', 'a.a-link-normal span', 'img[alt]', '.p13n-sc-truncate'];
  for (const selector of selectors) {
    const item = el.querySelector(selector);
    if (!item) continue;
    const text = norm(item.getAttribute('alt') || item.innerText || item.textContent || '');
    if (text && text.length > 5) return text;
  }
  return '';
};
const getImageUrl = (el) => {
  const imgs = [...el.querySelectorAll('img')];
  let best = '';
  let bestArea = 0;
  for (const img of imgs) {
    const src = [
      img.getAttribute('data-old-hires'),
      img.currentSrc,
      img.getAttribute('src'),
      img.getAttribute('data-src'),
      imageFromSrcset(img.getAttribute('srcset') || '')
    ].find(usableImageUrl) || '';
    if (!src) continue;
    const area = (img.naturalWidth || img.width || 0) * (img.naturalHeight || img.height || 0);
    if (!best || area >= bestArea) {
      best = src;
      bestArea = area;
    }
  }
  return best ? absUrl(best) : '';
};
const getSellerCountryFlagCode = (el) => {
  const flagElements = [...el.querySelectorAll('[class*="flag-icon-"], [class*="icp-nav-flag-"]')];
  for (const flag of flagElements) {
    const classText = String(flag.getAttribute('class') || '');
    const match = classText.match(/(?:flag-icon|icp-nav-flag)-([a-z]{2})\b/i);
    if (match) return match[1].toLowerCase();
    const hint = norm(flag.getAttribute('title') || flag.getAttribute('aria-label') || '');
    if (hint) return hint;
  }
  return '';
};
const isExcludedContainer = (el) => {
  if (el.closest('[id^="seller-sprite"],[id^="sellersprite"]')) return true;
  for (let cur = el; cur && cur !== document.body; cur = cur.parentElement) {
    const id = String(cur.id || '').toLowerCase();
    const cls = String(cur.className || '').toLowerCase();
    if (['nav-belt', 'navbar', 'nav-main', 'navfooter', 'ewc-content', 'nav-flyout-ewc'].includes(id)) return true;
    if (id.includes('ewc') || cls.includes('ewc') || cls.includes('cart')) return true;
  }
  const hrefs = [...el.querySelectorAll('a[href]')].map(a => a.href).join(' ');
  if (/ewc_|\/cart|\/gp\/cart|ref=ewc/i.test(hrefs)) return true;
  return false;
};
const selectors = [
  'article.cellContainer[data-csa-c-item-type="asin"]',
  'article[data-csa-c-item-id*=".asin."]',
  '[data-csa-c-item-id*=".asin."]',
  '#product_grid_container article',
  '.s-result-item[data-asin]:not([data-asin=""])',
  '[data-component-type="s-search-result"][data-asin]:not([data-asin=""])',
  '#gridItemRoot',
  '.zg-grid-general-faceout',
  '.p13n-grid-content',
  '[data-asin]:not([data-asin=""])'
];
// A single selector-list query preserves document order across all card shapes.
// Running one query per selector would group cards by selector priority and can
// change which product becomes the 11th cascade prescreen match.
const elements = [...document.querySelectorAll(selectors.join(','))]
  .filter(el => !isExcludedContainer(el));
const seenAsins = new Set();
const cards = [];
for (const el of elements) {
  const asin = getAsin(el);
  if (!asin || seenAsins.has(asin)) continue;
  const productUrl = getUrl(el, asin);
  if (/ewc_|\/cart|\/gp\/cart|ref=ewc/i.test(productUrl)) continue;
  const imageUrl = getImageUrl(el);
  seenAsins.add(asin);
  cards.push({
    asin,
    title: getTitle(el),
    product_url: productUrl,
    candidate_image_url: imageUrl,
    rank: String(cards.length + 1),
    price: norm(el.querySelector('.a-price .a-offscreen')?.textContent),
    rating_value: norm(el.querySelector('.a-icon-alt')?.textContent),
    review_count: norm(el.querySelector('a[href*="customerReviews"] .a-size-base')?.textContent),
    seller_country_flag_code: getSellerCountryFlagCode(el),
    text: includeText ? norm(el.innerText || el.textContent || '') : ''
  });
}
return cards;
    })() : [];
    return {url: href, document_id: document.documentElement.dataset.lcImageDocument || '',
      adopted_url_rewrite: adoptedUrlRewrite,
      title: document.title, ready: document.readyState === 'complete', asin: asin.toUpperCase(), source_image: sourceImage,
      installed: !!root || !!document.querySelector('#seller-sprite-extension-find-similar-listing'),
      logged_in: loggedIn, guest, messages, body: body.slice(0, 12000),
      signin: location.pathname.startsWith('/ap/signin'),
      captcha: !!document.querySelector('#captchacharacters,form[action*="validateCaptcha"]'),
      plugin_captcha: !!root && [...root.querySelectorAll('.robot-card-container')].some(visible),
      not_found: /page not found/i.test(document.title),
      delivery: text(document.querySelector('#glow-ingress-line2')),
      result_page: resultPage, grid: !!grid, empty: noResults, busy, cards};
  } catch (err) {
    const error = String(err.message || err);
    if (!['工作页网址已变化', '工作页已刷新或被替换'].includes(error)) return {error};
    // Preserve identity evidence without saving arbitrary query values or page text.
    const safeUrl = value => {
      try {
        const u = new URL(value); u.username = ''; u.password = ''; u.hash = '';
        for (const key of [...new Set(u.searchParams.keys())])
          if (!['psc', 'th', 'modes'].includes(key)) u.searchParams.set(key, '[redacted]');
        return u.href.slice(0, 2048);
      } catch (_) { return ''; }
    };
    return {error, page_identity: {
      expected_url: safeUrl(args.expectedUrl), actual_url: safeUrl(href),
      expected_document: String(args.documentId || '').slice(0, 128),
      actual_document: String(document.documentElement?.dataset.lcImageDocument || '').slice(0, 128),
      dom_asin: String(document.querySelector('input#ASIN')?.value || '').slice(0, 10)
    }};
  }
}
