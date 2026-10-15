"""Fixed daily-Chrome image search. No browser launch, upload, popup or focus API."""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import ipaddress
import json
import re
import random
import shutil
import socket
import sys
import time
import uuid
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit, urlunsplit

import requests
import amazon_image_competitor_crawler as core
from opencli_bridge import OpenCliBridge, BridgeTransientError, cli_command
from opencli_read_recovery import ReadRecovery
from run_outcome import config_error, needs_human, retry_later, _atomic_write_json
from safety_control import LocalSafetyController, RiskSignal, classify_amazon_risk, classify_sellersprite_risk

SCHEMA = 'image-background-v1'
METHOD = 'sellersprite_stylesnap_url'
AMAZON_IMAGE_HOSTS = {'m.media-amazon.com', 'images-na.ssl-images-amazon.com', 'images-eu.ssl-images-amazon.com', 'images-fe.ssl-images-amazon.com'}
NOTICE = '开始找同款前，请先退出卖家精灵账号登录，并保持插件启用。找同款按未登录方式运行；确认退出后才会开始查询。'
DOM = Path(__file__).with_name('image_background_dom.js').read_text(encoding='utf-8')


def wait_for_recovery(runtime, state, reason):
    """One bounded source retry; keep its deadline when the process restarts."""
    pending = state.data.get('automatic_recovery')
    if not pending:
        pending = dict(reason=reason, until=time.time() + random.uniform(20, 35))
        state.data['automatic_recovery'] = pending
        state.data.setdefault('automatic_recovery_events', []).append(dict(pending, time=core.now_iso()))
        state.flush()
    deadline = min(float(pending['until']), time.time() + 35)
    while time.time() < deadline:
        runtime.safety.heartbeat('retry_wait', detail='自动恢复：' + pending['reason'])
        time.sleep(min(2, max(0, deadline - time.time())))
    state.data.pop('automatic_recovery', None)
    state.flush()


def retry_local_write(runtime, operation):
    """Retry transient file locks without revisiting the browser or model."""
    for attempt in range(3):
        try:
            return operation()
        except OSError:
            if attempt == 2:
                raise
            runtime.safety.heartbeat('retry_wait', detail='自动重试本地结果写入')
            time.sleep(2)


def public_image_url(value: str, *, resolve: bool = False) -> str:
    try:
        p = urlsplit(value)
        host = p.hostname or ''
        if p.scheme != 'https' or not host or p.username or p.password or p.port not in (None, 443):
            raise ValueError()
        if host.lower() in {'localhost'} or host.lower().endswith(('.local', '.localhost', '.internal')):
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError()
        if resolve:
            addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            if not addresses:
                raise core.ImageResolutionError('图片域名解析未返回地址，将按普通网络故障恢复。')
            if any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
                raise ValueError()
    except OSError as exc:
        # DNS outages are recoverable; never label them as invalid user input.
        raise core.ImageResolutionError(
            f'图片域名解析失败（{type(exc).__name__}，errno={exc.errno}），将按普通网络故障恢复。'
        ) from exc
    except ValueError as exc:
        raise config_error('图片必须是可公开访问的 HTTPS 网址，不能是本地或内网地址。') from exc
    return urlunsplit((p.scheme, p.netloc, p.path, p.query, ''))


def normalize_image_url(value: str) -> str:
    value = public_image_url(value)
    p = urlsplit(value)
    if p.hostname in AMAZON_IMAGE_HOSTS:
        path = re.sub(r'\._.*\.', '.', p.path)
        return urlunsplit(('https', 'm.media-amazon.com', path, '', ''))
    return value


def amazon_system_image_proxy(url: str) -> dict:
    """Let the configured local HTTPS proxy resolve only known Amazon CDNs.

    macOS proxies may return fake local DNS addresses in TUN mode. HTTPS
    CONNECT uses the original hostname and keeps normal TLS verification.
    Arbitrary URLs still require public DNS resolution on this computer.
    """
    public_image_url(url)
    if urlsplit(url).hostname not in AMAZON_IMAGE_HOSTS:
        return {}
    get_system_proxies = getattr(urllib.request, 'getproxies_macosx_sysconf', None)
    if get_system_proxies is None:
        return {}
    try:
        proxy = get_system_proxies().get('https', '')
        parsed = urlsplit(proxy)
        if parsed.scheme not in {'http', 'https'} or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'} or not parsed.port:
            return {}
    except (OSError, ValueError):
        return {}
    return {'https': proxy}


def read_image_in_memory(url: str) -> str:
    """Bounded fallback used only after a model cannot read an image URL."""
    for _ in range(5):
        proxies = amazon_system_image_proxy(url)
        public_image_url(url, resolve=not bool(proxies))
        with requests.get(url, headers=core.request_headers(), timeout=45, stream=True, allow_redirects=False, proxies=proxies) as response:
            if 300 <= response.status_code < 400:
                from urllib.parse import urljoin
                url = urljoin(url, response.headers.get('location', ''))
                continue
            response.raise_for_status()
            mime = response.headers.get('content-type', '').split(';')[0].lower()
            if not mime.startswith('image/'):
                raise core.EmbeddingProviderError('图片网址没有返回图片，不能进行模型判定。')
            content = bytearray()
            for chunk in response.iter_content(65536):
                content.extend(chunk)
                if len(content) > 20 * 1024 * 1024:
                    raise core.EmbeddingProviderError('图片超过 20 MiB，停止内存转码。')
            if not content:
                raise core.EmbeddingProviderError('图片内容为空。')
            return f'data:{mime};base64,' + base64.b64encode(content).decode('ascii')
    raise core.EmbeddingProviderError('图片重定向次数超过限制。')


def product_asin(url: str, domain: str) -> str:
    p = urlsplit(url)
    if p.scheme != 'https' or p.hostname not in {domain, 'www.' + domain} or p.username or p.password:
        raise config_error('商品链接必须属于配置的 HTTPS Amazon 站点。')
    match = re.search(r'/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?]|$)', p.path, re.I)
    if not match:
        raise config_error('商品链接必须包含有效的 /dp/ASIN 或 /gp/product/ASIN。')
    return match[1].upper()


def validate_inputs(path: Path, domain: str) -> list[dict]:
    errors = []
    for index, row in enumerate(core.read_product_rows(path), 2):
        if not any(str(v or '').strip() for v in row.values()):
            continue
        asin = core.pick_column(row, core.INPUT_ALIASES['source_asin']).strip().upper()
        url = core.pick_column(row, core.INPUT_ALIASES['product_url'])
        image = core.pick_column(row, core.INPUT_ALIASES['image_url'])
        try:
            if asin and not re.fullmatch(r'[A-Z0-9]{10}', asin):
                raise config_error('ASIN 格式无效')
            if url:
                found = product_asin(url, domain)
                if asin and found != asin:
                    raise config_error('ASIN 与商品链接冲突')
            if image:
                public_image_url(image)
            if not (asin or url or image):
                raise config_error('请补充 ASIN、商品链接或公开图片网址；不支持仅本地图片')
        except core.run_outcome.CrawlStop as exc:
            errors.append(f'第 {index} 行：{exc}')
    if errors:
        raise config_error('\n'.join(errors))
    # Keep every input row; count-only duplicate reuse happens after a committed snapshot.
    return core.load_products(path, domain, dedupe=False)


def validate_config(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise config_error('配置文件必须为 JSON 对象。')
    if raw.get('browser_backend', 'opencli') != 'opencli' or raw.get('search_strategy', METHOD) != METHOD:
        raise config_error('找同款已迁移至 OpenCLI + 图片网址搜索。请使用新模板、新 job_id；旧任务用 --migrate-from-job 显式导入。')
    legacy = ['chrome_binary', 'chrome_user_data_dir', 'chrome_profile_directory', 'debugger_address', 'extension_path', 'lens_url_template']
    if any(raw.get(k) not in (None, '') for k in legacy):
        raise config_error('请移除旧 CDP／上传配置并使用新的找同款模板。')
    if raw.get('browser_mode') not in (None, 'reuse'):
        raise config_error('找同款只绑定日常 Chrome 的现有标签。')
    for key in ['sellersprite_required', 'sellersprite_on_lens', 'enrich_accepted_results', 'activate_plugin']:
        if raw.get(key) not in (None, False):
            raise config_error(f'{key} 与退出登录的找同款流程不兼容。')
    if raw.get('product_filters'):
        raise config_error('找同款不支持插件字段业务筛选；请先移除 product_filters，避免未知字段被当作符合条件。')
    entry = raw.get('entry_mode', 'batch')
    if entry not in {'batch', 'current_tab'}:
        raise config_error('entry_mode 必须为 batch 或 current_tab。')
    job = raw.get('job_id', '')
    if not isinstance(job, str) or not re.fullmatch(r'[\w.-]+', job) or job in {'.', '..'}:
        raise config_error('job_id 必须为不含路径分隔符的名称。')
    for key in ['max_candidates_per_source', 'max_competitors_per_source']:
        n = raw.get(key, 48)
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise config_error(f'{key} 必须为正整数。')
    if raw.get('browser_tab_concurrency', 1) != 1:
        raise config_error('找同款只支持单工作标签。')
    if not raw.get('marketplace'):
        raise config_error('请在配置中明确 marketplace。')
    cfg = dict(raw, browser_backend='opencli', browser_mode='reuse', search_strategy=METHOD,
               entry_mode=entry, result_mode=raw.get('result_mode', 'count_only'),
               match_mode=raw.get('match_mode', 'cascade'), max_candidates_per_source=raw.get('max_candidates_per_source', 48),
               max_competitors_per_source=raw.get('max_competitors_per_source', 48),
               sellersprite_required=False, sellersprite_on_lens=False, enrich_accepted_results=False, activate_plugin=False,
               lens_url_template='https://www.{domain}/stylesnap')
    if entry == 'current_tab':
        cfg['products_file'] = str(core.resolve_path(str(raw.get('outputs_root', 'outputs'))) / job / 'current_tab.csv')
    return cfg


def confirm_logout(confirmed: bool, operation_mode: str) -> str:
    print(NOTICE, flush=True)
    if not confirmed and operation_mode != 'unattended' and sys.stdin.isatty():
        confirmed = input('已退出卖家精灵登录？输入 YES 确认：').strip().upper() == 'YES'
    if not confirmed:
        raise needs_human('尚未确认退出卖家精灵登录，未发送搜索请求。', next_action='手动退出后，使用 --confirm-sellersprite-logged-out 启动本次任务。')
    return core.now_iso()


class BackgroundPage:
    def __init__(self, runtime, state, *, bridge=None, clock=time.monotonic, sleep=time.sleep, wall_clock=time.time):
        self.runtime, self.state = runtime, state
        self.clock, self.sleep = clock, sleep
        binding = state.data.get('browser') or {}
        self.bridge = bridge or OpenCliBridge(binding.get('session') or ('lc-image-' + runtime.job_id))
        self.bridge.target = binding.get('target', '')
        self.url, self.document = binding.get('url', ''), binding.get('document_id', '')
        self.attached = False
        self.read_recovery = ReadRecovery(self.bridge, state.data, state.flush, runtime.safety,
                                          now=wall_clock, sleep=sleep)

    def observation_clock(self):
        return self.clock() - self.read_recovery.blocked_seconds

    def validate_target(self):
        return self.read_recovery.read('target', self.bridge.validate_target)

    def raw(self, action='snapshot', *, guarded=True, **kwargs):
        arguments = dict(action=action, expectedUrl=self.url if guarded else '',
                         documentId=self.document if guarded else '', **kwargs)
        # Keep writes outside read recovery; unknown replies must never replay them.
        def read_once():
            result = self.bridge.dom(DOM, arguments)
            if guarded and result.get('adopted_url_rewrite'):
                if not self.document or result.get('document_id') != self.document:
                    raise needs_human('页面文档身份已变化，不能采用改写后的网址。')
                self.check_host(result['url'])
                self.health(result)
                self.url = result['url']
                self.save_binding()
                print('已核对同一文档与同一目标，采用页面规范化后的网址。', flush=True)
            self.health(result)
            return result
        try:
            if action == 'snapshot':
                return self.read_recovery.read('image_snapshot', read_once)
            return self.bridge.dom(DOM, arguments)
        except core.run_outcome.CrawlStop as exc:
            identity = getattr(exc, 'page_identity', None)
            if isinstance(identity, dict):
                self.state.data['last_page_identity_error'] = dict(
                    identity, time=core.now_iso(), action=action, target=self.bridge.target)
                self.state.flush()
                print('页面身份校验差异已保存到 state.json: last_page_identity_error。', flush=True)
            raise

    def save_binding(self):
        self.state.data['browser'] = dict(session=self.bridge.session, target=self.bridge.target, url=self.url, document_id=self.document)
        self.state.flush()

    def attach(self):
        if self.attached:
            return
        if self.state.data.get('pending_navigation') and not self.bridge.target and not self.runtime.rebind:
            raise needs_human('导航断点缺少原工作标签身份，请人工核对后 --rebind。')
        if not self.bridge.target or self.runtime.rebind:
            if self.runtime.rebind:
                self.state.data.pop(ReadRecovery.KEY, None)
            self.bridge.bind()
            self.url, self.document = '', ''
            self.runtime.rebind = False
            self.save_binding()
        self.validate_target()
        if self.state.data.get('pending_navigation'):
            self.recover_navigation()
        snap = self.raw()
        self.check_host(snap['url'])
        self.health(snap)
        if not self.document:
            mark = self.raw('mark', id=uuid.uuid4().hex)
            self.url, self.document = mark['url'], mark['document_id']
        self.save_binding()
        self.attached = True

    def destination_matches(self, requested, snap):
        self.check_host(snap.get('url', ''))
        wanted, actual = urlsplit(requested), urlsplit(snap['url'])
        if wanted.path == '/stylesnap':
            return bool(snap.get('result_page') and parse_qs(actual.query).get('q') == parse_qs(wanted.query).get('q'))
        return bool(core.parse_asin(requested) and core.parse_asin(snap['url']) == core.parse_asin(requested))

    def reload_stalled_destination(self, destination, snap):
        """One persisted reload of a positively identified, committed destination."""
        if self.state.data.get('pending_navigation_reload'):
            return False
        if snap.get('document_loading') or not self.destination_matches(destination, snap):
            return False
        if not (snap.get('source_image') or snap.get('cards') or snap.get('empty')):
            return False
        # Guard the observed document before throttling; user changes during a
        # rest must never be overwritten by the recovery operation.
        self.url, self.document = snap['url'], ''
        mark = self.raw('mark', id=uuid.uuid4().hex)
        self.document = mark['document_id']
        self.save_binding()
        self.runtime.safety.before_remote_action('已确认目标页面加载超时，重新加载一次')
        self.validate_target()
        latest = self.raw()
        self.health(latest)
        if latest.get('ready'):
            return True  # It completed during the rest; the next read adopts it.
        self.state.data['pending_navigation_reload'] = dict(url=destination, time=core.now_iso())
        self.state.flush()  # Save the budget before sending an uncertain write.
        print('预期页面已到达但文档加载超时，按原节流规则重新加载一次。', flush=True)
        try:
            self.raw('navigate', url=destination)
        except BridgeTransientError:
            # The write may have executed; only reconcile it on later reads.
            pass
        self.wait('等待原目标页面重新加载')
        return True

    def recover_navigation(self):
        """Resolve intent on the original target; reload only a known destination."""
        destination = self.state.data['pending_navigation']
        deadline = self.observation_clock() + self.runtime.page_timeout
        while True:
            self.validate_target()
            snap = self.raw(guarded=False)
            self.health(snap)
            same_origin = snap.get('url') == self.url and snap.get('document_id') == self.document
            reloading = bool(self.state.data.get('pending_navigation_reload'))
            if same_origin and not reloading:
                # Navigation never committed; the normal collector may retry it.
                self.state.data.pop('pending_navigation', None)
                self.state.flush()
                return
            root_loading = snap.get('document_loading') and (snap.get('url') == self.url or self.destination_matches(destination, snap))
            if not root_loading and not self.destination_matches(destination, snap):
                raise needs_human('未完成导航的工作标签已被改为其他页面；未接管或重新绑定。')
            if not root_loading and snap.get('ready'):
                self.url, self.document = snap['url'], ''
                mark = self.raw('mark', id=uuid.uuid4().hex)
                self.document = mark['document_id']
                self.state.data.pop('pending_navigation', None)
                self.state.data.pop('pending_navigation_reload', None)
                self.save_binding()
                return
            if self.observation_clock() >= deadline:
                if self.reload_stalled_destination(destination, snap):
                    deadline = self.observation_clock() + self.runtime.page_timeout
                    continue
                raise retry_later('原标签仍未完成导航，保留断点；仅对已确认目标允许一次重新加载，不重复未知状态操作。')
            self.wait('等待导航文档根节点' if root_loading else '自动核对未完成的导航')

    def check_host(self, url):
        p = urlsplit(url)
        if p.scheme != 'https' or p.hostname not in {self.runtime.marketplace_domain, 'www.' + self.runtime.marketplace_domain}:
            raise needs_human('工作标签必须属于配置的 Amazon 站点；未导航或接管其他页面。')

    def health(self, snap):
        safety = self.runtime.safety
        signal = classify_amazon_risk(http_status=None, title=snap.get('title', ''), body_text=snap.get('body', ''))
        if snap.get('captcha'):
            signal = RiskSignal('amazon', 'captcha', 'Amazon 出现验证码。')
        if snap.get('plugin_captcha'):
            signal = RiskSignal('sellersprite', 'captcha', '卖家精灵出现验证码。')
        signal = signal or classify_sellersprite_risk(snap.get('messages', ''))
        if signal:
            safety.trip(signal, page_url=snap.get('url', ''))
        if snap.get('signin'):
            raise needs_human('Amazon 弹出了登录页；本工具不使用也不需要 Amazon 买家账号，本条采集已停止。请稍后重试，不要登录买家账号。')
        if snap.get('logged_in'):
            raise needs_human('页面明确显示卖家精灵仍已登录。请先手动退出，再重新确认启动。')
        self.state.data['logout_observation'] = 'guest_dom' if snap.get('guest') else 'user_confirmed_only'
        if snap.get('ready') and (snap.get('source_image') or snap.get('cards') or snap.get('empty')):
            safety.note_risk_checked()

    def snapshot(self):
        self.attach()
        self.validate_target()
        snap = self.raw()
        self.health(snap)
        return snap

    def wait(self, detail):
        self.runtime.safety.heartbeat('plugin_wait', detail=detail)
        self.sleep(2)

    def navigate(self, url):
        self.attach()
        snap = self.snapshot()
        # Reuse a verified, ready document instead of reloading the same URL.
        # Same-URL reloads can invalidate the mark before the navigation reply.
        if snap.get('url') == url and snap.get('ready'):
            return snap
        self.runtime.safety.before_remote_action('找同款导航／查询')
        # Re-check after throttling: the user may have changed/closed the tab meanwhile.
        self.snapshot()
        self.state.data['pending_navigation'] = url
        self.state.flush()
        try:
            self.raw('navigate', url=url)
        except core.run_outcome.CrawlStop as exc:
            if exc.exit_code != 30:
                raise
            # A navigation can destroy the eval context before its reply arrives.
            # Reconcile the persisted intent on the original target; never resend it.
            self.recover_navigation()
            snap = self.snapshot()
            if not self.destination_matches(url, snap):
                raise exc
            return snap
        deadline = self.observation_clock() + self.runtime.page_timeout
        while self.observation_clock() < deadline:
            self.validate_target()
            snap = self.raw(guarded=False)
            self.health(snap)
            actual = snap.get('url', '')
            if actual == self.url and snap.get('document_id') == self.document:
                self.wait('等待工作标签导航')
                continue
            self.check_host(actual)
            if snap.get('document_loading') and (actual == self.url or self.destination_matches(url, snap)):
                self.wait('等待导航文档根节点')
                continue
            if not self.destination_matches(url, snap):
                raise needs_human('工作标签跳转到了非预期页面，已停止。')
            if snap.get('ready'):
                # Atomic document marking also validates the URL observed above.
                self.url, self.document = actual, ''
                mark = self.raw('mark', id=uuid.uuid4().hex)
                self.document = mark['document_id']
                self.state.data.pop('pending_navigation', None)
                self.state.data.pop('pending_navigation_reload', None)
                self.save_binding()
                return self.snapshot()
            self.wait('等待搜索页加载')
        self.attached = False
        raise core.TransientAmazonPageUnavailable('找同款导航超时，先核对原标签中的导航状态再恢复。', reason='expected_content_missing', url=url)

    def delivery(self, snap):
        if not self.runtime.delivery_location_enabled:
            return
        loc = self.runtime.delivery_locations.get(self.runtime.marketplace_domain, {})
        expected = re.sub(r'[\s-]+', '', loc.get('postal_code', '')).casefold()
        actual = snap.get('delivery', '').casefold()
        expected_pattern = r'[\s-]*'.join(re.escape(c) for c in expected)
        if not expected or not re.search(r'(?<![a-z0-9])' + expected_pattern + r'(?![a-z0-9])', actual):
            # No uncertain address mutations in a shared daily browser.
            raise needs_human('无法确认 Amazon 配送地与配置一致。请手动设置配置邮编后 --rebind；不会使用旧地址缓存。')

    def stable(self, kind):
        deadline = self.observation_clock() + self.runtime.page_timeout
        signature, since = None, self.observation_clock()
        while self.observation_clock() < deadline:
            generation = self.read_recovery.generation
            snap = self.snapshot()
            if generation != self.read_recovery.generation:
                signature, since = None, self.observation_clock()
            if snap.get('not_found'):
                return snap
            ready = snap.get('ready') and not snap.get('busy')
            if kind == 'product':
                ready = ready and bool(snap.get('source_image'))
            else:
                ready = ready and snap.get('result_page') and (bool(snap.get('cards')) or snap.get('empty'))
            # Only fields that identify the source / ordered visual candidates
            # define stability. Live plugin text and prices must not reset it.
            content = ((snap.get('asin'), snap.get('source_image')) if kind == 'product' else
                       (bool(snap.get('empty')), tuple((card.get('asin'), card.get('candidate_image_url'))
                                                     for card in snap.get('cards', []))))
            new = (bool(ready), content)
            if not ready or new != signature:
                signature, since = new, self.observation_clock()
            if ready and self.observation_clock() - since >= 4:
                self.delivery(snap)
                return snap
            self.wait('等待图片／候选稳定')
        raise core.TransientAmazonPageUnavailable('图片／相似候选未稳定或页面结构无法识别；没有写入零同款。', reason='expected_content_missing', url=self.url)

    def collect(self, current, *, on_candidates=None):
        self.attach()
        saved_image = current.get('source_image')
        image_url = saved_image or current.get('input_image_url')
        product = current.get('source_product_url')
        # Product inputs always take the actual page image; input URL is not a substitute.
        if product and not saved_image:
            snap = self.snapshot()
            if not (self.runtime.entry_mode == 'current_tab' and snap.get('asin') == current.get('source_asin')):
                self.navigate(product)
            snap = self.stable('product')
            if snap.get('not_found'):
                self.navigate(core.product_url_for_asin(self.runtime.marketplace_domain, current['source_asin']))
                snap = self.stable('product')
                if snap.get('not_found'):
                    raise core.SourceProductUnavailable(product)
            if snap.get('asin') != current.get('source_asin'):
                raise needs_human('商品页 ASIN 与当前来源不一致。')
            image_url = snap['source_image']
        if not image_url:
            raise config_error('当前来源缺少可用图片网址。')
        image_url = normalize_image_url(image_url)
        current['source_image'] = image_url
        current['source_image_identity'] = hashlib.sha256(('image-url-v1:' + image_url).encode()).hexdigest()
        result_url = f'https://www.{self.runtime.marketplace_domain}/stylesnap?q={quote(image_url, safe="")}'
        current['search_url'] = result_url
        self.state.set_current(current)
        snap = self.snapshot()
        if not snap.get('installed'):
            raise needs_human('工作页未检测到卖家精灵插件，请保持插件启用并退出账号登录。')
        if not (snap.get('result_page') and parse_qs(urlsplit(snap['url']).query).get('q') == [image_url]):
            self.navigate(result_url)
        snap = self.stable('results')
        if snap.get('not_found'):
            raise core.TransientAmazonPageUnavailable('相似搜索入口不可用，没有写入零同款。', reason='expected_content_missing', url=self.url)
        collected, seen = [], set()
        store = core.source_progress_store(self.runtime)
        partial = store.get('lens', 'partial_collection') if store is not None else None
        if partial and partial.get('source_image') == image_url:
            for row in partial.get('candidate_records', []):
                asin = str(row.get('asin') or '').upper()
                if row.get('source_id') == current['source_id'] and re.fullmatch(r'[A-Z0-9]{10}', asin) and asin not in seen:
                    seen.add(asin)
                    collected.append(row)
            collected = collected[:self.runtime.max_candidates_per_source]
        stable_rounds = 0
        stop = 'no_progress'
        for round_number in range(self.runtime.page_scroll_max_rounds + 1):
            previous = len(collected)
            for card in snap.get('cards', []):
                asin = str(card.get('asin') or '').upper()
                if not re.fullmatch(r'[A-Z0-9]{10}', asin) or asin in seen:
                    continue
                seen.add(asin)
                row = dict(card, source_type='image_search', source_id=current['source_id'],
                           source_asin=current.get('source_asin', ''), source_product_url=product or '',
                           source_image=image_url, input_row=current['input_row'], scraped_at=core.now_iso(),
                           rank=str(len(collected) + 1), note='未登录找同款：未查询卖家精灵登录指标')
                try:
                    row['candidate_image_url'] = normalize_image_url(card.get('candidate_image_url', ''))
                except core.run_outcome.CrawlStop:
                    row['candidate_image_url'] = ''
                collected.append(row)
            collected = collected[:self.runtime.max_candidates_per_source]
            if collected and (round_number == 0 or len(collected) > previous):
                if store is not None:
                    store.put('lens', 'partial_collection', dict(source_image=image_url, candidate_records=collected))
                if on_candidates is not None and on_candidates(collected):
                    stop = 'prescreen_limit_reached'
                    break
            if len(collected) >= self.runtime.max_candidates_per_source:
                stop = 'limit_reached'
                break
            if snap.get('empty'):
                stop = 'source_exhausted'
                break
            stable_rounds = stable_rounds + 1 if len(collected) == previous else 0
            if stable_rounds >= 2 or round_number == self.runtime.page_scroll_max_rounds:
                stop = 'no_progress' if stable_rounds >= 2 else 'scroll_limit'
                break
            self.runtime.safety.before_remote_action('找同款候选滚动加载')
            self.snapshot()
            self.raw('scroll')
            snap = self.stable('results')
        current['collection_stop_reason'] = stop
        self.state.set_current(current)
        return collected[:self.runtime.max_candidates_per_source]


def progress_identity(runtime, current, plan, provider):
    return dict(source_id=current['source_id'], input_row=current['input_row'],
                provider_sha256=provider['sha256'], crawl_plan_sha256=plan['sha256'])


def migration_preflight(runtime, queue):
    old_id = runtime.migrate_from_job
    if not old_id:
        return
    if not re.fullmatch(r'[\w.-]+', old_id) or old_id in {'.', '..', runtime.job_id}:
        raise config_error('迁移来源必须是另一个有效 job_id。')
    old = core.load_json(runtime.outputs_root / old_id / 'state.json')
    if runtime.entry_mode == 'current_tab':
        raise config_error('迁移请使用 batch 及旧任务的原输入文件；current_tab 请使用独立的新任务。')
    plan = core.image_crawl_plan_fingerprint(runtime, queue)
    previous = old.get('crawl_plan_fingerprint') or {}
    if old.get('vision_provider_fingerprint') != core.vision_provider_fingerprint(runtime) or any(
        previous.get(key) != plan.get(key) for key in ('marketplace_domain', 'result_mode', 'match_mode',
        'max_candidates_per_source', 'include_source_as_competitor', 'normalized_sources_sha256')):
        raise config_error('旧任务的输入、顺序、数量、配送地或模型不一致，不能迁移。')


def migrate(runtime, state, queue, plan, provider):
    old_id = runtime.migrate_from_job
    if not old_id:
        return
    if not re.fullmatch(r'[\w.-]+', old_id) or old_id in {'.', '..', runtime.job_id}:
        raise config_error('迁移来源必须是另一个有效 job_id。')
    if state.data.get('migration_complete'):
        if state.data['migration_complete'] != old_id:
            raise config_error('本任务已从其他来源迁移。')
        return
    old_dir = runtime.outputs_root / old_id
    old = core.load_json(old_dir / 'state.json')
    report = {'from_job': old_id, 'imported_results': [], 'imported_progress': [], 'not_imported': []}
    old_plan = old.get('crawl_plan_fingerprint') or {}
    compatible = old.get('vision_provider_fingerprint') == provider and all(
        old_plan.get(key) == plan.get(key) for key in
        ('marketplace_domain', 'result_mode', 'match_mode', 'max_candidates_per_source', 'include_source_as_competitor', 'normalized_sources_sha256'))
    if not compatible:
        raise config_error('旧任务的输入、顺序、候选数量、配送地或模型参数不一致，不能迁移；请保留旧结果并使用独立新任务。')
    rows = {int(row['input_row']): row for row in queue}
    for file in sorted((old_dir / 'source_results').glob('*.json')):
        payload = core.load_json(file)
        source = payload.get('source') or {}
        current = rows.get(int(source.get('input_row') or 0))
        if not current or payload.get('crawl_plan_sha256') != old_plan.get('sha256') or payload.get('provider_sha256') != provider['sha256']:
            report['not_imported'].append(file.name)
            continue
        core.validate_committed_count_identity(payload['count_row'], current)
        core.commit_source_result_shard(state.path.parent / 'source_results', current, plan, provider,
                                        payload['candidate_rows'], payload['accepted_rows'], payload['count_row'])
        report['imported_results'].append(current['input_row'])
    if runtime.is_count_only:
        for old_count in core.load_count_results(old_dir / 'counts.jsonl').values():
            rownum = int(old_count.get('input_row') or 0)
            current = rows.get(rownum)
            if not current or rownum in report['imported_results']:
                continue
            core.validate_committed_count_identity(old_count, current)
            core.commit_source_result_shard(state.path.parent / 'source_results', current, plan, provider, [], [], old_count)
            report['imported_results'].append(rownum)
    pending = old.get('current') or {}
    current = rows.get(int(pending.get('input_row') or 0))
    if current and current['source_id'] == pending.get('source_id'):
        directory = core.source_progress_dir(old_dir, pending)
        meta = core.SourceProgressStore._read(directory / 'meta.json') or {}
        expected = {str(k): str(v) for k, v in progress_identity(runtime, pending, old_plan, provider).items()}
        if meta.get('identity') == expected:
            dest = core.SourceProgressStore(core.source_progress_dir(state.path.parent, current), progress_identity(runtime, current, plan, provider))
            for file in directory.glob('*.json'):
                if file.name != 'meta.json':
                    shutil.copyfile(file, dest.directory / file.name)
            for key in ('source_image', 'source_image_identity', core.MODEL_CHECKPOINT_KEY):
                if key in pending:
                    current[key] = pending[key]
            legacy_path = Path(str(pending.get('resolved_source_image_path') or ''))
            if legacy_path.is_file() and legacy_path.resolve().is_relative_to(old_dir.resolve()):
                current['legacy_source_image_path'] = str(legacy_path.resolve())
            report['imported_progress'].append(current['input_row'])
        else:
            report['not_imported'].append('未完成来源的图片／模型检查点身份无法核对，将重采')
    state.data['queue'] = queue
    state.data['migration_complete'] = old_id
    state.flush()
    _atomic_write_json(state.path.parent / 'migration_report.json', report)


def run(runtime, *, dry_run=False):
    core.prepare_vision_provider(runtime)
    queue = validate_inputs(runtime.products_file, runtime.marketplace_domain) if runtime.entry_mode == 'batch' else []
    migration_preflight(runtime, queue)
    cli_command()  # Dependency check only; no browser command during dry-run.
    if dry_run:
        print(f'dry-run：{runtime.entry_mode}，每来源最多 {runtime.max_candidates_per_source} 个候选；未连接浏览器、搜索或调用模型。')
        return
    confirmed_at = confirm_logout(runtime.confirm_logout, runtime.operation_mode)
    job = runtime.outputs_root / runtime.job_id
    job.mkdir(parents=True, exist_ok=True)
    safety = LocalSafetyController(mode=runtime.operation_mode, traffic_profile='image',
        batch_pause_pages_min=runtime.batch_pause_pages_min, batch_pause_pages_max=runtime.batch_pause_pages_max,
        batch_pause_seconds_min=runtime.batch_pause_seconds_min, batch_pause_seconds_max=runtime.batch_pause_seconds_max)
    safety.job_label, safety.status_path = runtime.job_id, job / 'run_heartbeat.json'
    safety.acquire()
    state = None
    job_lock = core.JobRunLock(job / '.run.lock')
    lock_acquired = False
    try:
        try:
            job_lock.acquire()
            lock_acquired = True
        except core.UserFacingError as exc:
            raise core.run_outcome.CrawlStop(str(exc), exit_code=50) from exc
        safety.begin(resume_after_review=runtime.resume_after_review)
        runtime.safety = safety
        if not runtime.resume:
            for name in ('state.json', 'records.jsonl', 'candidates.jsonl', 'counts.jsonl', 'failures.jsonl', 'migration_report.json', 'image_collection_report.json',
                         runtime.products_file.stem + '_相似竞品数量.xlsx', runtime.products_file.stem + '_同款竞品结果.xlsx'):
                (job / name).unlink(missing_ok=True)
            for name in ('source_results', core.SOURCE_PROGRESS_DIRNAME):
                shutil.rmtree(job / name, ignore_errors=True)
        previous = core.load_json(job / 'state.json') if (job / 'state.json').exists() else {}
        if previous and previous.get('background_schema') != SCHEMA:
            raise config_error('旧找同款断点不能直接继续。请使用新 job_id 和 --migrate-from-job。')
        if runtime.entry_mode == 'current_tab':
            if runtime.products_file.exists() and previous:
                queue = validate_inputs(runtime.products_file, runtime.marketplace_domain)
            else:
                # Bootstrap only after explicit logout confirmation and global lock.
                bootstrap = type('Bootstrap', (), {'data': {}, 'flush': lambda self: None})()
                page = BackgroundPage(runtime, bootstrap)
                snap = page.stable('product')
                linked_asin = product_asin(snap['url'], runtime.marketplace_domain)
                asin = snap.get('asin') or linked_asin
                if not re.fullmatch(r'[A-Z0-9]{10}', asin):
                    raise needs_human('无法确认当前商品变体的 ASIN。')
                source_image = normalize_image_url(snap['source_image'])
                with runtime.products_file.open('w', encoding='utf-8-sig', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(['ASIN', '商品URL', '主图URL'])
                    writer.writerow([asin, core.product_url_for_asin(runtime.marketplace_domain, asin), source_image])
                queue = validate_inputs(runtime.products_file, runtime.marketplace_domain)
                queue[0]['source_image'] = source_image
                previous = {'browser': bootstrap.data['browser']}
        if previous.get('background_schema') == SCHEMA and (
            previous.get('crawl_plan_fingerprint') != core.image_crawl_plan_fingerprint(runtime, queue)
            or previous.get('vision_provider_fingerprint') != core.vision_provider_fingerprint(runtime)
            or previous.get('delivery_location_fingerprint') != runtime.delivery_location_fingerprint
        ):
            raise config_error('当前配置或输入与断点不一致，请使用新 job_id；未丢弃已付费的模型进度。')
        state = core.ImageCompetitorStateStore(job / 'state.json', runtime, queue)
        state.load_or_create()
        state.data.update(background_schema=SCHEMA, logout_confirmed_at=confirmed_at, search_method=METHOD)
        if previous.get('browser') and not state.data.get('browser'):
            state.data['browser'] = previous['browser']
        if runtime.rebind:
            state.data.pop('pending_navigation', None)
        state.flush()
        plan = core.image_crawl_plan_fingerprint(runtime, queue)
        provider = core.vision_provider_fingerprint(runtime)
        migrate(runtime, state, queue, plan, provider)
        page = BackgroundPage(runtime, state)
        paths = [job / n for n in ('candidates.jsonl', 'records.jsonl', 'counts.jsonl')]
        def materialize():
            return retry_local_write(runtime, lambda: core.materialize_source_result_shards(job / 'source_results', plan, provider, *paths))
        def commit(*args):
            return retry_local_write(runtime, lambda: core.commit_source_result_shard(*args))
        counts = materialize()
        duplicates = core.duplicate_original_rows(queue) if runtime.is_count_only else {}
        def fail_current(current, reason, exc):
            nonlocal counts
            key = core.image_work_key(current)
            note_reason, detail = core.item_failure_classification(reason, str(exc), exc)
            core.run_outcome.note_item_failure(state.data, key, reason=note_reason, detail=detail)
            # Legacy accounting counts different process runs, not in-process
            # recovery cycles. Keep this bounded retry budget on the source.
            cycles = int(current.get('automatic_retry_failures') or 0) + 1
            current['automatic_retry_failures'] = cycles
            state.set_current(current)
            if cycles >= 2:
                core.run_outcome.record_skipped_item(state.data, key, reason=core.QUARANTINE_REASON,
                    label=current.get('source_asin', ''), url=current.get('source_product_url', ''))
                evaluation = core.MatchEvaluation([], {}, '', 'skipped', None, '', '来源连续失败已跳过，同款数量留空。')
                count = core.build_count_result_row(runtime, current, METHOD, 'guest_no_enrichment', 0, evaluation)
                commit(job / 'source_results', current, plan, provider, [], [], count)
                counts = materialize()
                state.clear_amazon_page_retry()
                state.finish_current_source('skipped', result=count)
                if core.record_operational_outcome(state, False):
                    raise retry_later('连续多个来源无法自动恢复，已保存未完成任务；请检查失败日志。') from exc
                return
            state.clear_amazon_page_retry()
            wait_for_recovery(runtime, state, reason)

        state.restore_deferred()
        if state.data.get('automatic_recovery'):
            wait_for_recovery(runtime, state, '')
        while True:
            pause_path = job / 'pause_after_count.json'
            if pause_path.exists():
                pause = core.load_json(pause_path)
                limit = pause.get('completed_count')
                if type(limit) is not int or limit < 1:
                    raise config_error('pause_after_count.json 的 completed_count 必须是正整数。')
                if len(counts) >= limit:
                    raise needs_human(f'已按用户要求完成 {len(counts)} 个产品并暂停。',
                        next_action='等待用户明确通知继续；届时移除 pause_after_count.json，再从原断点恢复。')
            current = state.next_work()
            if current is None:
                break
            safety.set_work_key(core.image_work_key(current))
            rownum = current['input_row']
            if rownum in counts:
                core.validate_committed_count_identity(counts[rownum], current)
                state.finish_current_source(counts[rownum].get('processing_status', 'recovered'), result=counts[rownum])
                continue
            duplicate = duplicates.get(rownum)
            if duplicate and duplicate in counts:
                count = core.build_duplicate_count_row(runtime, current, counts[duplicate], duplicate)
                commit(job / 'source_results', current, plan, provider, [], [], count)
                counts = materialize()
                state.finish_current_source('duplicate', result=count)
                continue
            progress = core.SourceProgressStore(core.source_progress_dir(job, current), progress_identity(runtime, current, plan, provider))
            runtime._source_progress = progress
            try:
                checkpoint = core.load_image_model_checkpoint(current)
                if checkpoint:
                    _, _, candidates, evaluation = checkpoint
                else:
                    metrics_before = core.provider_metric_snapshot(runtime)
                    early_evaluation = None
                    def prescreen_batch(candidates):
                        nonlocal early_evaluation
                        image_url = current['source_image']
                        legacy = current.get('legacy_source_image_path')
                        ref = core.ImageReference(image_url, legacy_path=Path(legacy) if legacy else None)
                        early_evaluation = core.run_cascade_match(runtime, ref, ref.url, candidates, prescreen_only=True)
                        if early_evaluation is not None:
                            print(f"流式粗筛命中 {early_evaluation.prescreen_visual_match_count} 个，立即停止候选加载：{current.get('source_asin', '')}", flush=True)
                        return early_evaluation is not None
                    saved = core.load_saved_lens_collection(progress)
                    if saved:
                        _, _, candidates = saved
                    else:
                        def collect_attempt(attempt):
                            # A retry uses the same target, with the same persistent traffic counter.
                            if attempt.attempt_number > 1 and current.get('search_url'):
                                page.navigate(current['search_url'])
                            return page.collect(current, on_candidates=prescreen_batch if runtime.match_mode == 'cascade' else None)
                        candidates = core.run_image_page_stage_with_recovery(runtime, state, current,
                            'stylesnap_results', current.get('source_product_url') or runtime.lens_url,
                            lambda: None, collect_attempt)
                        progress.put('lens', 'collection', dict(search_method=METHOD, plugin_status='guest_no_enrichment', candidate_records=candidates))
                        progress.delete('lens', 'partial_collection')
                    image_url = current.get('source_image') or current.get('input_image_url')
                    if not image_url and candidates:
                        image_url = candidates[0].get('source_image')
                    if not image_url:
                        progress.delete('lens', 'collection')
                        raise core.TransientAmazonPageUnavailable('候选检查点缺少来源图片身份，将重采当前来源并保留可核对的模型缓存。', reason='expected_content_missing')
                    current['source_image'] = normalize_image_url(image_url)
                    state.set_current(current)
                    legacy = current.get('legacy_source_image_path')
                    ref = core.ImageReference(current['source_image'], legacy_path=Path(legacy) if legacy else None)
                    evaluation = early_evaluation or core.evaluate_competitor_matches(runtime, ref, ref.url, candidates)
                    evaluation.provider_metrics = core.provider_metric_delta(metrics_before, core.provider_metric_snapshot(runtime))
                    retry_local_write(runtime, lambda: core.save_image_model_checkpoint(state, current, search_method=METHOD, plugin_status='guest_no_enrichment', candidate_records=candidates, evaluation=evaluation))
                audit = core.build_candidate_audit_rows(candidates, evaluation.accepted_records, evaluation.decisions)
                count = core.build_count_result_row(runtime, current, METHOD, 'guest_no_enrichment', len(candidates), evaluation)
                count.update(logout_confirmed_at=confirmed_at, collection_stop_reason=current.get('collection_stop_reason', 'restored_snapshot'),
                             source_image_identity=current.get('source_image_identity', ''), evaluated_count=sum(v.get('prescreen_status') in {'matched', 'rejected'} or (not v.get('prescreen_status') and isinstance(v.get('is_competitor'), bool)) for v in evaluation.decisions.values()),
                             scope='collected_candidates_only')
                commit(job / 'source_results', current, plan, provider, audit, evaluation.accepted_records, count)
                counts = materialize()
                core.run_outcome.clear_item_failures(state.data, core.image_work_key(current))
                state.finish_current_source(evaluation.processing_status, count=len(evaluation.accepted_records), result=count)
                core.record_operational_outcome(state, True)
                safety.complete_review_success()
            except core.SourceProductUnavailable:
                evaluation = core.MatchEvaluation([], {}, '', 'source_unavailable', None, '', '商品链接失效，同款数量留空。')
                count = core.build_count_result_row(runtime, current, METHOD, 'guest_no_enrichment', 0, evaluation)
                commit(job / 'source_results', current, plan, provider, [], [], count)
                counts = materialize()
                state.finish_current_source('source_unavailable', result=count)
            except core.AmazonPageRetryExhausted as exc:
                core.log_amazon_page_retry_exhausted_once(job / 'failures.jsonl', state, current, exc)
                fail_current(current, exc.failure_code, exc)
            except core.TransientAmazonPageUnavailable as exc:
                fail_current(current, 'snapshot_incomplete', exc)
            except core.FatalEmbeddingProviderError:
                raise
            except core.EmbeddingProviderError as exc:
                core.log_failure(job / 'failures.jsonl', state, current, 'model_incomplete', core.redact_sensitive_text(str(exc))[:180])
                if isinstance(exc, core.CandidatesUnscorableError):
                    progress.delete('lens', 'collection')
                fail_current(current, 'embedding_provider_error', exc)
            finally:
                runtime._source_progress = None
        if state.deferred_count():
            raise retry_later('有未完成来源已推迟到下次运行，已保存断点。')
        return
    finally:
        active_error = sys.exc_info()[0] is not None
        try:
            if state is not None and state.data:
                def write_outputs():
                    state.flush()
                    if (job / 'counts.jsonl').exists():
                        suffix = '相似竞品数量' if runtime.is_count_only else '同款竞品结果'
                        output = job / f'{runtime.products_file.stem}_{suffix}.xlsx'
                        if runtime.is_count_only:
                            core.write_count_only_workbook(runtime.products_file, job / 'counts.jsonl', output)
                        else:
                            core.write_workbook(runtime.products_file, job / 'records.jsonl', job / 'candidates.jsonl', job / 'failures.jsonl', output)
                            wb = core.load_workbook(output)
                            ws = core.replace_sheet(wb, '来源状态')
                            mapping = {'source_asin': '来源ASIN', 'source_product_url': '商品URL', 'processing_status': '判定状态',
                                       'same_product_count': '同款数量', 'candidate_count': '候选数量', 'match_reason': '说明'}
                            core.write_sheet(ws, list(mapping.values()), core.read_jsonl(job / 'counts.jsonl'), mapping)
                            wb.save(output)
                    _atomic_write_json(job / 'image_collection_report.json', {
                        'schema': SCHEMA, 'logout_confirmed_at': confirmed_at, 'logout_observation': state.data.get('logout_observation', 'user_confirmed_only'),
                        'traffic_profile': 'image', 'automatic_recoveries': state.data.get('automatic_recovery_events', []),
                        'browser': state.data.get('browser'), 'sources': state.data.get('completed_source_results', {}),
                        'search_method': METHOD, 'http_status_coverage': 'DOM_and_bridge_errors_only', 'scope': 'collected_candidates_only'})
                retry_local_write(runtime, write_outputs)
        except Exception as output_error:
            if not active_error:
                raise needs_human('结果文件写入失败，请关闭 Excel/WPS 中的输出文件后重跑；已提交的来源不会重复付费。') from output_error
            print('部分结果文件暂未写出，原始运行错误保留。', file=sys.stderr)
        finally:
            try:
                safety.fail_review()
                if lock_acquired:
                    core.write_run_summary(job, runtime.operation_mode, safety)
            finally:
                job_lock.release()
                safety.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description='日常 Chrome 后台找同款（未登录卖家精灵）')
    parser.add_argument('--config', default=str(core.DEFAULT_CONFIG))
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--no-resume', action='store_true')
    parser.add_argument('--operation-mode', choices=['supervised', 'unattended'])
    parser.add_argument('--resume-after-review', action='store_true')
    parser.add_argument('--confirm-sellersprite-logged-out', action='store_true')
    parser.add_argument('--rebind', action='store_true')
    parser.add_argument('--migrate-from-job', default='')
    args = parser.parse_args(argv)
    job, error = None, None
    core.run_outcome.start_new_run()
    try:
        raw = core.load_json(core.resolve_path(args.config))
        if args.operation_mode:
            raw['operation_mode'] = args.operation_mode
        cfg = validate_config(raw)
        runtime = core.build_image_runtime_config(cfg, args.no_resume)
        runtime.entry_mode = cfg['entry_mode']
        runtime.confirm_logout = args.confirm_sellersprite_logged_out
        runtime.rebind, runtime.migrate_from_job = args.rebind, args.migrate_from_job
        runtime.resume_after_review = args.resume_after_review
        if not args.dry_run:
            job = runtime.outputs_root / runtime.job_id
        run(runtime, dry_run=args.dry_run)
    except KeyboardInterrupt as exc:
        error = exc
    except Exception as exc:
        error = core.classify_crawl_exception(exc, dry_run=args.dry_run)
        if isinstance(exc, (core.UserFacingError, ValueError, FileNotFoundError)):
            error = config_error(str(exc))
    if error:
        print(str(error), file=sys.stderr)
    return core.run_outcome.exit_with(error, job if job and job.exists() else None, skipped_count=core._skipped_count(job))


if __name__ == '__main__':
    raise SystemExit(main())
