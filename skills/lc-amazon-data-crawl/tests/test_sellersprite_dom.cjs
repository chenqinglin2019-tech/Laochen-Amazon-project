/* Public DOM fixture tests; no browser process or new dependencies. */
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../scripts/sellersprite_panel.js'), 'utf8');
function node(text = '', cls = '', attrs = {}) {
  return {innerText: text, textContent: text, disabled: false, checked: false, value: '',
    classList: {contains: name => cls.split(' ').includes(name)},
    attributes: Object.keys(attrs).map(name => ({name})),
    getAttribute: name => attrs[name] || null, hasAttribute: name => name in attrs,
    getClientRects: () => [1], closest: () => null,
    querySelector: () => null, querySelectorAll: () => [], contains: () => true,
    click() { this.clicked = (this.clicked || 0) + 1; }, dispatchEvent() {}};
}
function fixture() {
  const root = node(), product = node(), footer = node(), document = node();
  const loading = [], more = [], exports = [], options = [];
  const chooser = node('', '', {'data-v-own': ''});
  root.querySelector = s => ({'.product-list-box': product, '.footer-nex': footer}[s] || null);
  product.querySelector = s => ({'.footer-nex': footer, '.choose-type': chooser}[s] || null);
  footer.querySelector = s => s === '.layout-center' ? node('加载数据 48 条') : null;
  footer.querySelectorAll = s => ({'.layout-center button': more, '[data-button-key="btn-export"] button': exports}[s] || []);
  product.querySelectorAll = s => s === '.vxe-table--loading,.el-loading-mask' ? loading : [];
  document.documentElement = {dataset: {lcPluginDocument: 'doc'}};
  document.querySelectorAll = s => ({'#seller-sprite-extension-app': [root], '.ext-popover-custom .el-select-dropdown__item': options}[s] || []);
  const context = {document, location: {href: 'https://www.amazon.com/s?k=test', pathname: '/s'},
    getComputedStyle: () => ({visibility: 'visible'}), MouseEvent: class {}};
  vm.createContext(context); vm.runInContext(source, context);
  return {root, product, footer, document, more, exports, options,
    run: args => context.sellerSpritePanel({action: 'snapshot', ...args})};
}
{
  const f = fixture(); const b = node('加载更多'); f.more.push(b);
  assert.equal(f.run().count, 48); assert.equal(f.run().more, true);
  assert.ok(f.run({action: 'load', expectedUrl: 'https://www.amazon.com/s?k=other'}).error);
  assert.ok(f.run({action: 'load', documentId: 'wrong'}).error); assert.equal(b.clicked, undefined);
  b.disabled = true; assert.equal(f.run().busy, true); assert.ok(f.run({action: 'load'}).error);
  b.disabled = false; f.run({action: 'load'}); assert.equal(b.clicked, 1);
}
{
  const f = fixture(); f.exports.push(node('导出'), node('导出'));
  assert.ok(f.run({action: 'export'}).error); assert.equal(f.exports[0].clicked, undefined);
}
{
  const f = fixture();
  // A transitioning closed product menu still has layout rectangles. It must not
  // be clicked while selecting all badges in the teleported open menu.
  const hidden = node('品牌', '', {'data-v-own': ''});
  hidden.closest = s => s === '.el-popper[aria-hidden="true"]' ? node() : null;
  const chosen = node('AC', 'selected', {'data-v-own': ''});
  const missing = node('A+', '', {'data-v-own': ''});
  f.options.push(hidden, chosen, missing); f.run({action: 'badges_all'});
  assert.equal(hidden.clicked, undefined); assert.equal(chosen.clicked, undefined); assert.equal(missing.clicked, 1);
}
{
  const f = fixture(); f.document.querySelectorAll = s => s === '#seller-sprite-extension-app' ? [f.root, node()] : [];
  assert.ok(f.run().error.includes('不唯一'));
}
{
  const f = fixture(); const logo = node('卖家精灵'); f.product.getClientRects = () => [];
  f.root.querySelectorAll = s => s === '.logo-btn-container .logo-btn' ? [logo] : [];
  f.run({action: 'open'}); assert.equal(logo.clicked, 1);
}
{
  const f = fixture(); f.footer.querySelector = () => null;
  f.product.querySelectorAll = s => s === '.vxe-table--empty-block' ? [node('暂无数据')] : [];
  assert.equal(f.run().count, 0); assert.equal(f.run().empty, true);
}
{
  const f = fixture(); const message = node('No results for your search query.');
  const results = [];
  const original = f.document.querySelectorAll;
  f.document.querySelectorAll = s => {
    if (s === '#search [data-csa-c-content-id="messaging-messages-no-results"]') return [message];
    if (s === '#search [data-component-type="s-search-result"][data-asin]') return results;
    return original(s);
  };
  assert.equal(f.run().amazon_no_results, true);
  results.push(node('Product', '', {'data-asin': 'B000000001'}));
  assert.equal(f.run().amazon_no_results, false);
  results.length = 0; message.getClientRects = () => [];
  assert.equal(f.run().amazon_no_results, false);
  // A plugin-only empty table must never imply a disappeared store.
  f.product.querySelectorAll = s => s === '.vxe-table--empty-block' ? [node('暂无数据')] : [];
  assert.equal(f.run().amazon_no_results, false);
}
{
  const f = fixture(), b = node('加载中'); f.more.push(b);
  assert.equal(f.run().busy, false); // Original storefront contract unchanged.
  assert.equal(f.run().keyword_busy, undefined);
  assert.equal(f.run({keyword: true}).keyword_busy, true);
  assert.equal(f.run({action: 'load', keyword: true, expectedCount: 48}).not_clicked, true);
  assert.equal(b.clicked, undefined);
}
{
  const f = fixture(), b = node('加载更多'); f.more.push(b);
  assert.equal(f.run({action: 'load', keyword: true, expectedCount: 40}).not_clicked, true);
  assert.equal(b.clicked, undefined);
  f.run({action: 'load', keyword: true, expectedCount: 48, loadAttempt: 'attempt-1'});
  assert.equal(b.clicked, 1);
  assert.equal(f.run({keyword: true}).keyword_load_attempt, 'attempt-1');
  f.more.push(node('加载更多'));
  assert.equal(f.run({action: 'load', keyword: true, expectedCount: 48}).not_clicked, true);
  assert.equal(b.clicked, 1);
}
{
  const f = fixture(), original = f.product.querySelectorAll;
  const errors = [node('网络繁忙'), node('加载失败，请重试')];
  f.product.querySelectorAll = s => s === '.error-box,.el-alert' ? errors : original(s);
  assert.equal(f.run().keyword_load_error, undefined);
  assert.equal(f.run({keyword: true}).keyword_load_error, '加载失败，请重试');
  errors.pop();
  assert.equal(f.run({keyword: true}).keyword_load_error, '');
}
console.log('DOM fixtures: 10 groups passed');
