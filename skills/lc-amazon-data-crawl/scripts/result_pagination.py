"""Result-list Show more controls, scoped away from products and carousels."""
from __future__ import annotations

import time

from selenium.common.exceptions import WebDriverException

CONTROL_JS = r"""
const root = document.querySelector('#search') || document.querySelector('main');
if (!root) return null;
const visible = el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
const excluded = '.s-result-item[data-asin]:not([data-asin=""]), [data-component-type="s-search-result"][data-asin]:not([data-asin=""]), [data-component-type*="carousel"], .a-carousel-container, aside, [id*="seller-sprite"], [class*="seller-sprite"], [class*="quick-view-ext"]';
const names = /^(show more results|see more results|load more results|show more products|load more products|加载更多(?:商品|结果)?|查看更多(?:商品|结果)?)$/i;
const candidates = [...root.querySelectorAll('button, a, [role="button"], input[type="button"], input[type="submit"]')].filter(el => {
  const labelled = (el.getAttribute('aria-labelledby') || '').split(/\s+/).map(id => document.getElementById(id)?.innerText || '').join(' ');
  const label = (el.getAttribute('aria-label') || labelled.trim() || el.innerText || el.value || '').replace(/\s+/g, ' ').trim();
  const knownPending = el.getAttribute('data-lc-result-more') === 'owned' &&
    (el.disabled || el.getAttribute('aria-disabled') === 'true' || el.getAttribute('aria-busy') === 'true');
  return visible(el) && (names.test(label) || knownPending) && !el.closest(excluded);
});
const controls = candidates.filter(el => !candidates.some(other => other !== el && el.contains(other)));
if (!controls.length) return null;
if (controls.length !== 1) return {ambiguous:true, count:controls.length};
const el = controls[0];
for (const old of root.querySelectorAll('[data-lc-result-more]')) if (old !== el) old.removeAttribute('data-lc-result-more');
if (el.getAttribute('data-lc-result-more') !== 'owned') el.setAttribute('data-lc-result-more', 'owned');
return {selector:'[data-lc-result-more="owned"]', disabled:Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true'), busy:el.getAttribute('aria-busy') === 'true'};
"""

ASINS_JS = r"""
const root = document.querySelector('.s-main-slot') || document.querySelector('#search');
if (!root) return [];
return [...new Set([...root.querySelectorAll('.s-result-item[data-asin], [data-component-type="s-search-result"][data-asin]')]
 .filter(el => !el.closest('.a-carousel-container, aside'))
 .map(el => el.getAttribute('data-asin')).filter(asin => /^[A-Z0-9]{10}$/.test(asin || '')))];
"""


def find_load_more_control(driver):
    if not callable(getattr(driver, "execute_script", None)):
        return None
    value = driver.execute_script(CONTROL_JS)
    if isinstance(value, dict) and value.get("ambiguous"):
        raise WebDriverException("load_more_ambiguous: 主结果区存在多个加载控件，无法确认后续范围。")
    return value if isinstance(value, dict) and value.get("selector") else None


def result_asins(driver):
    value = driver.execute_script(ASINS_JS)
    return set(value) if isinstance(value, list) else set()


def click_and_wait_more(driver, runtime, stop_event=None):
    from amazon_category_rank_crawler import safety_before_remote_action, prepare_navigation, inspect_sellersprite_block
    before = result_asins(driver)
    safety_before_remote_action(runtime, "点击加载更多 Amazon 商品", stop_event)
    prepare_navigation(driver, runtime, stop_event)
    control = find_load_more_control(driver)
    if not control or control.get("disabled") or control.get("busy"):
        raise WebDriverException("load_more_unavailable: 加载更多控件尚不可用，保留批次断点。")
    click = getattr(driver, "click_result_control", None)
    if callable(click):
        click(control["selector"])
    else:
        from selenium.webdriver.common.by import By
        driver.find_element(By.CSS_SELECTOR, control["selector"]).click()
    deadline = time.monotonic() + runtime.page_timeout
    previous = None
    stable = None
    last_desktop_check = -float("inf")
    while time.monotonic() < deadline:
        if stop_event is not None and stop_event.is_set():
            from desktop_runtime import DesktopUnavailable
            raise DesktopUnavailable("load_more_cancelled")
        if time.monotonic() - last_desktop_check >= 2:
            from desktop_runtime import ensure_page_desktop
            paused = ensure_page_desktop(driver, runtime, stop_event)
            deadline += paused
            if paused:
                stable = None
            last_desktop_check = time.monotonic()
        block = inspect_sellersprite_block(driver, runtime)
        if block.get("status") == "blocked":
            from amazon_front_crawler import raise_for_blocked_plugin
            raise_for_blocked_plugin(block)
        after = result_asins(driver)
        control = find_load_more_control(driver)
        if after - before and not (control and control.get("busy")):
            if after != previous:
                stable = time.monotonic()
            elif stable is not None and time.monotonic() - stable >= 2:
                return after
        else:
            stable = None
        previous = after
        safety = getattr(runtime, "safety", None)
        if safety:
            safety.heartbeat("page", detail="等待加载更多商品")
        if stop_event is None:
            time.sleep(0.5)
        elif stop_event.wait(0.5):
            break
    raise WebDriverException("load_more_timeout: 点击后未确认新增商品，不能当作自然末页。")
