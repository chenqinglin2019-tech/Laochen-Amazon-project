/* SellerSprite 5.0.6 public DOM contract. No Vue state, provider APIs or OS input. */
function sellerSpritePanel(args) {
  const text = e => (e?.innerText || e?.textContent || "").replace(/\s+/g, " ").trim();
  const visible = e => !!e && !e.closest('.el-popper[aria-hidden="true"]') && e.getClientRects().length > 0 && getComputedStyle(e).visibility !== "hidden";
  const all = (scope, selector) => [...scope.querySelectorAll(selector)];
  const unique = (nodes, name) => {
    if (nodes.length !== 1) throw Error(`${name}需要唯一匹配，实际 ${nodes.length}`);
    return nodes[0];
  };
  const click = (e, name) => {
    if (!visible(e) || e.disabled || e.getAttribute("aria-disabled") === "true" || e.classList.contains("is-loading"))
      throw Error(`${name}不可操作`);
    e.click();
    return {clicked: name};
  };
  try {
    const href = location.href.split("#")[0];
    if (args.expectedUrl && href !== args.expectedUrl) throw Error("工作页网址已变化，停止操作");
    if (args.documentId && document.documentElement.dataset.lcPluginDocument !== args.documentId)
      throw Error("工作页被重新加载，必须重新核对采集状态");
    if (args.action === "navigate") {
      location.assign(args.url);
      return {navigating: true};
    }
    if (args.action === "mark") {
      document.documentElement.dataset.lcPluginDocument = args.id;
      return {url: href, document_id: args.id};
    }
    // Only Amazon's main search message counts; recommendations and plugin empty states do not.
    const noResults = all(document, '#search [data-csa-c-content-id="messaging-messages-no-results"]').some(visible) &&
      !all(document, '#search [data-component-type="s-search-result"][data-asin]').some(e => visible(e) && e.getAttribute("data-asin"));
    const roots = all(document, "#seller-sprite-extension-app");
    if (roots.length > 1) throw Error("卖家精灵容器不唯一");
    const root = roots[0];
    const product = root?.querySelector(".product-list-box");
    const footer = product?.querySelector(".footer-nex") || root?.querySelector(".footer-nex");
    const countText = text(footer?.querySelector(".layout-center"));
    const countMatch = countText.match(/加载数据\s*([\d,]+)\s*条|(?:Loaded|Loading data)\s*([\d,]+)/i);
    const more = footer ? all(footer, ".layout-center button").filter(e => /^(加载更多|Load more)$/i.test(text(e))) : [];
    const exportButtons = footer ? all(footer, '[data-button-key="btn-export"] button').filter(visible) : [];
    const busy = more.some(e => e.disabled || e.getAttribute("aria-disabled") === "true" || e.classList.contains("is-loading")) ||
      (product && all(product, ".vxe-table--loading,.el-loading-mask").some(visible));
    const empty = !!product && all(product, '.vxe-table--empty-block').some(e => visible(e) && /暂无数据|No data/i.test(text(e)));
    const messages = root ? [...all(root, ".el-message,.el-alert,.el-message-box,.error-box,.guest-span-btn"),
      ...all(document, '.el-message[class*="ext-"],.el-message-box__wrapper[class*="ext-"]')].filter(visible).map(text).join("\n") : "";
    const selected = text(product?.querySelector(".had-check")).match(/(?:已勾选|Selected)\s*(\d+)/i);
    const rows = product ? all(product, ".vxe-table--body .vxe-body--row").filter(visible).map(row => ({
      row_id: row.getAttribute("rowid"),
      index: text(row.querySelector(".close-icon .cp")),
      title: text(row.querySelector(".fcs .flex-column > span")),
      asins: [...new Set(all(row, 'a[href]').map(a => a.href.match(/\/(?:dp|gp\/product)\/([A-Z0-9]{10})(?:[/?]|$)/i)?.[1]).filter(Boolean))],
      text: text(row).slice(0, 1600)
    })) : [];
    if (args.action === "snapshot") return {
      url: href, title: document.title, document_id: document.documentElement.dataset.lcPluginDocument || "",
      installed: !!root, panel: visible(product), count: countMatch ? Number((countMatch[1] || countMatch[2]).replace(/,/g, "")) : (empty && !busy ? 0 : null),
      more: more.filter(visible).length === 1, more_count: more.filter(visible).length,
      busy: !!busy, exporting: exportButtons.some(e => e.disabled || e.classList.contains("is-loading")),
      selected: selected ? Number(selected[1]) : 0, messages,
      guest: /游客|未登录|guest|sign in/i.test(text(root?.querySelector(".guest-span-btn"))),
      captcha: !!root && all(root, '.robot-card-container').some(visible),
      empty, amazon_no_results: noResults,
      amazon_error: document.querySelector('#captchacharacters,form[action*="validateCaptcha"]') ? "captcha" :
        (/robot check|sorry! something went wrong!|access denied/i.test(document.title) ? text(document.body).slice(0, 2000) : ""),
      signin: location.pathname.startsWith("/ap/signin"), rows,
      headers: product ? all(product, ".vxe-header--column").map(text).filter(Boolean) : [],
      dropdowns: product ? all(product, ".choose-type .el-select input").map(e => e.value) : []
    };
    if (!root) throw Error("未检测到卖家精灵，请在当前工作页打开插件");
    const icon = (scope, href, name) => unique(all(scope, "use").filter(e => e.getAttribute("xlink:href") === href && visible(e)), name);
    if (args.action === "open") {
      if (visible(product)) return {ready: true};
      const tabs = all(root, '.nav-item-ext .nav-web').filter(e => visible(e) && /^(产品查询|Product Research)$/i.test(text(e)));
      if (tabs.length) return click(unique(tabs, "产品查询"), "产品查询");
      return click(unique(all(root, '.logo-btn-container .logo-btn').filter(visible), "卖家精灵入口"), "卖家精灵入口");
    }
    if (!visible(product)) throw Error("产品查询面板未打开");
    const ownedOptions = () => {
      // Element Plus teleports badge options to body. Require the scoped Vue DOM
      // attribute shared with THIS panel's chooser, not arbitrary page options.
      const chooser = product.querySelector(".choose-type");
      const scopes = [...(chooser?.attributes || [])].map(a => a.name).filter(n => n.startsWith("data-v-"));
      return all(document, ".ext-popover-custom .el-select-dropdown__item")
        .filter(e => visible(e) && (root.contains(e) || scopes.some(n => e.hasAttribute(n))));
    };
    if (args.action === "load") {
      if (busy) throw Error("上一轮仍在加载");
      return click(unique(more.filter(visible), "加载更多"), "加载更多");
    }
    if (args.action === "export") {
      if (busy || (selected && Number(selected[1]) > 0)) throw Error("加载中或存在勾选，禁止导出");
      return click(unique(exportButtons, "普通导出"), "普通导出");
    }
    if (args.action === "filter_open") return click(icon(root, "#iconfiltrate", "过滤设置").closest(".sign-in-btn"), "过滤设置");
    if (args.action === "filter_reset") return click(unique(all(product, ".filter-div .reset-btn").filter(visible), "重置条件"), "重置条件");
    if (args.action === "filter_close") return click(unique(all(product, ".filter-div .filter-div-header-right").filter(visible), "关闭过滤设置"), "关闭过滤设置");
    if (args.action === "dedup_off") {
      const label = unique(all(product, ".choose-type label").filter(e => /列表ASIN去重|Remove duplicate ASIN/i.test(text(e))), "列表ASIN去重");
      const input = label.querySelector("input");
      return input.checked ? click(label, "关闭列表ASIN去重") : {ready: true};
    }
    if (args.action === "clear_selection") {
      const input = unique(all(product, ".vxe-table--header .custom-checkbox input[type=checkbox]").filter(visible), "表头选择框");
      if (input.checked || input.indeterminate || Number(selected?.[1] || 0) > 0) return click(input, "取消选择");
      return {ready: true};
    }
    if (args.action === "select_open" || args.action === "select_close") {
      const selects = all(product, ".choose-type .el-select").filter(visible);
      let candidates;
      if (args.kind === "badges") candidates = selects.filter(e => e.classList.contains("product-list-select"));
      else if (args.kind === "product") candidates = selects.filter(e => /^(产品|品牌|卖家|Products?|Brands?|Sellers?)$/i.test(e.querySelector("input")?.value || ""));
      else candidates = selects.filter(e => /展示|自然|广告|Show|Organic|Sponsored/i.test(e.querySelector("input")?.value || ""));
      if (args.kind === "show" && !candidates.length) return {absent: true}; // Seller storefront has no show-type selector.
      const candidate = unique(candidates, args.kind);
      const opened = !!candidate.querySelector(".el-select__caret.is-reverse");
      if (opened === (args.action === "select_open")) return {ready: true};
      return click(candidate.querySelector(".select-trigger"), args.kind);
    }
    if (args.action === "select_option") {
      const options = ownedOptions();
      const desired = args.kind === "product" ? /^(产品|Products?)$/i : /^(展示全部|Show all|All)$/i;
      return click(unique(options.filter(e => desired.test(text(e))), args.kind), args.kind);
    }
    if (args.action === "badges_all") {
      const options = ownedOptions();
      if (!options.length) throw Error("未识别商品标识选项");
      const missing = options.filter(e => !e.classList.contains("selected") && !e.classList.contains("is-disabled"));
      if (missing.length) return click(missing[0], "选择商品标识");
      return {ready: true};
    }
    if (args.action === "columns_open") return click(icon(footer, "#icona-Icon-Customize", "自定义设置").closest("button"), "自定义设置");
    if (args.action === "columns_all") {
      const container = unique(all(root, ".filter-column-content").filter(visible), "数据列设置");
      const boxes = all(container, 'input[type="checkbox"]');
      if (!boxes.length) throw Error("没有可识别的数据列");
      const missing = boxes.filter(e => !e.checked && !e.disabled);
      for (const input of missing) input.click();
      return {changed: missing.length};
    }
    if (args.action === "columns_save") {
      const container = unique(all(root, ".filter-column-content").filter(visible), "数据列设置").closest(".el-tab-pane");
      return click(unique(all(container, "button").filter(e => /^(保存|Save)$/i.test(text(e))), "保存数据列"), "保存数据列");
    }
    if (args.action === "export_options_open" || args.action === "export_options_close") {
      const wrapper = unique(all(footer, '[data-button-key="btn-export"] .footer-light-overlay-wrapper'), "导出选项");
      wrapper.dispatchEvent(new MouseEvent(args.action.endsWith("open") ? "mouseenter" : "mouseleave", {bubbles: false}));
      return {ready: true};
    }
    if (args.action === "export_options_off") {
      const options = unique(all(footer, '[data-button-key="btn-export"] .export-popover').filter(visible), "导出选项");
      // Translation and high-res image downloads add unrelated requests. Keep original text/images.
      for (const box of all(options, 'input[type="checkbox"]')) if (box.checked) box.click();
      return {ready: true};
    }
    if (args.action === "reset_order") {
      // Refresh the plugin's export sort cache through the public list-order header.
      const header = unique(all(product, ".vxe-table--header .table-title").filter(e => text(e) === "#" && visible(e)), "原始序号表头");
      return click(header, "原始序号表头");
    }
    throw Error(`不支持的面板操作 ${args.action}`);
  } catch (error) {
    return {error: String(error.message || error)};
  }
}
