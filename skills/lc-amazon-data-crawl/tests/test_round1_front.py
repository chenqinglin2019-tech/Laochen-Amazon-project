"""Round-1 front crawler fixes: D1 storefront gate, G2, D2 quarantine/deferral,
entry-point contract, D3 bsr defaults, W2 sorted landing, sellersprite-check,
G6 sponsored carousels and the next-page guard."""

from __future__ import annotations

import io
import json
import queue
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import amazon_front_crawler as front
import run_outcome
from safety_control import SafetyPausedError

NODE = shutil.which("node")


# ---------------------------------------------------------------------------
# helpers


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def capture_storefront_script() -> str:
    """Return the exact JS that inspect_storefront_plugin_page sends."""

    class CaptureDriver:
        script = ""

        def execute_script(self, script, *_args):
            CaptureDriver.script = script
            return {"at_bottom": True, "results": {}}

    runtime = SimpleNamespace(include_sponsored=False, page_scroll_step_ratio=0.85)
    with patch.object(front, "extract_front_product_cards", return_value=[{"asin": "B000000001", "is_sponsored": "no"}]):
        front.inspect_storefront_plugin_page(CaptureDriver(), runtime, scroll=False)
    return CaptureDriver.script


BOX_HARNESS = r"""
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = {};
global.window = {};
global.location = {href: 'https://www.amazon.com/s?me=fixture'};
for (const [asin, text] of Object.entries(input.boxes)) {
  const box = { innerText: text, querySelectorAll: () => [], getAttribute: () => null,
                nodeType: 1, parentElement: null, getClientRects: () => [1], matches: () => false };
  global.document = {
    hidden: false, visibilityState: 'visible', hasFocus: () => true,
    querySelector: (sel) => (sel.includes(asin) ? box : null),
    querySelectorAll: (sel) => (sel.includes(asin) ? [box] : []),
    scrollingElement: {scrollTop: 0, scrollHeight: 100, scrollBy() {}},
  };
  global.innerHeight = 100;
  global.getComputedStyle = () => ({display: 'block', visibility: 'visible'});
  const fn = new Function(input.script);
  const result = fn([asin], false, 0.85, input.labels).results[asin];
  out[asin] = result.reason + (result.fields ? ':' + result.fields.join('|') : '');
}
console.log(JSON.stringify(out));
"""

# A deliberately small DOM: enough CSS (tag, #id, .class, [attr op "v" i],
# :not(), descendant) to run the real card-extraction script on fixture HTML.
MINI_DOM_HARNESS = r"""
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const VOID = new Set(['img', 'br', 'input', 'meta', 'link', 'hr']);
function findClose(text, start, open, close) {
  let depth = 0, quote = null;
  for (let i = start; i < text.length; i++) {
    const ch = text[i];
    if (quote) { if (ch === quote) quote = null; continue; }
    if (ch === '"' || ch === "'") { quote = ch; continue; }
    if (ch === open) depth++;
    else if (ch === close) { depth--; if (depth === 0) return i; }
  }
  throw new Error('unclosed ' + text);
}
function splitTop(str, sep) {
  const out = []; let depth = 0, quote = null, cur = '';
  for (const ch of str) {
    if (quote) { cur += ch; if (ch === quote) quote = null; continue; }
    if (ch === '"' || ch === "'") { quote = ch; cur += ch; continue; }
    if (ch === '[' || ch === '(') depth++;
    if (ch === ']' || ch === ')') depth--;
    if (depth === 0 && sep.test(ch)) { if (cur.trim()) out.push(cur.trim()); cur = ''; continue; }
    cur += ch;
  }
  if (cur.trim()) out.push(cur.trim());
  return out;
}
function parseAttr(inner) {
  const m = inner.match(/^\s*([\w:-]+)\s*(?:([*^$]?=)\s*("([^"]*)"|'([^']*)'|[^\s\]]+))?\s*(i)?\s*$/);
  if (!m) throw new Error('bad attr ' + inner);
  const v = m[4] !== undefined ? m[4] : (m[5] !== undefined ? m[5] : m[3]);
  return {type: 'attr', name: m[1], op: m[2] || null, v, ci: Boolean(m[6])};
}
function parseCompound(text) {
  const parts = []; let i = 0;
  const tag = text.match(/^(?:[a-zA-Z][a-zA-Z0-9-]*|\*)/);
  if (tag) { if (tag[0] !== '*') parts.push({type: 'tag', v: tag[0].toUpperCase()}); i = tag[0].length; }
  while (i < text.length) {
    const ch = text[i];
    if (ch === '.' || ch === '#') {
      const m = text.slice(i + 1).match(/^[\w-]+/);
      parts.push({type: ch === '.' ? 'class' : 'id', v: m[0]}); i += 1 + m[0].length;
    } else if (ch === '[') {
      const end = findClose(text, i, '[', ']');
      parts.push(parseAttr(text.slice(i + 1, end))); i = end + 1;
    } else if (text.startsWith(':not(', i)) {
      const end = findClose(text, i + 4, '(', ')');
      parts.push({type: 'not', v: parseCompound(text.slice(i + 5, end))}); i = end + 1;
    } else throw new Error('bad selector ' + text);
  }
  return parts;
}
const parseList = (sel) => splitTop(sel, /,/).map((c) => splitTop(c, /\s/).map(parseCompound));
function matchCompound(el, parts) {
  for (const p of parts) {
    if (p.type === 'tag' && el.tagName !== p.v) return false;
    if (p.type === 'id' && el.getAttribute('id') !== p.v) return false;
    if (p.type === 'class' && !(el.getAttribute('class') || '').split(/\s+/).includes(p.v)) return false;
    if (p.type === 'not' && matchCompound(el, p.v)) return false;
    if (p.type === 'attr') {
      let a = el.getAttribute(p.name);
      if (a === null) return false;
      if (!p.op) continue;
      let v = p.v;
      if (p.ci) { a = a.toLowerCase(); v = v.toLowerCase(); }
      if (p.op === '=' && a !== v) return false;
      if (p.op === '*=' && !a.includes(v)) return false;
      if (p.op === '^=' && !a.startsWith(v)) return false;
      if (p.op === '$=' && !a.endsWith(v)) return false;
    }
  }
  return true;
}
function matchComplex(el, compounds) {
  let idx = compounds.length - 1;
  if (!matchCompound(el, compounds[idx])) return false;
  let node = el.parentElement; idx--;
  while (idx >= 0) {
    if (!node) return false;
    if (matchCompound(node, compounds[idx])) idx--;
    node = node.parentElement;
  }
  return true;
}
class El {
  constructor(tag, attrs, parent) {
    this.tagName = tag.toUpperCase(); this.attrs = attrs; this.children = [];
    this.parentElement = parent; this.nodeType = 1;
  }
  getAttribute(n) { return Object.prototype.hasOwnProperty.call(this.attrs, n) ? this.attrs[n] : null; }
  get textContent() { return this.children.map((c) => (typeof c === 'string' ? c : c.textContent)).join(' '); }
  get innerText() { return this.textContent; }
  get outerHTML() { return ''; }
  get href() {
    const h = this.getAttribute('href');
    if (h === null) return '';
    try { return new URL(h, location.href).href; } catch (e) { return h; }
  }
  *descendants() {
    for (const c of this.children) { if (typeof c !== 'string') { yield c; yield* c.descendants(); } }
  }
  querySelectorAll(sel) { const list = parseList(sel); return [...this.descendants()].filter((e) => list.some((s) => matchComplex(e, s))); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  matches(sel) { return parseList(sel).some((s) => matchComplex(this, s)); }
  closest(sel) { for (let n = this; n; n = n.parentElement) if (n.matches(sel)) return n; return null; }
  contains(other) { for (let n = other; n; n = n.parentElement) if (n === this) return true; return false; }
  getClientRects() { return [1]; }
}
function parseHTML(html) {
  const root = new El('html', {}, null);
  let cur = root;
  const re = /<\/?([a-zA-Z0-9]+)([^>]*)>|([^<]+)/g; let m;
  while ((m = re.exec(html))) {
    if (m[3] !== undefined) { const t = m[3].replace(/\s+/g, ' ').trim(); if (t) cur.children.push(t); continue; }
    if (m[0].startsWith('</')) { cur = cur.parentElement || root; continue; }
    const attrs = {}; const ar = /([\w:-]+)(?:="([^"]*)")?/g; let a;
    while ((a = ar.exec(m[2]))) attrs[a[1]] = a[2] !== undefined ? a[2] : '';
    const el = new El(m[1].toLowerCase(), attrs, cur); cur.children.push(el);
    if (!VOID.has(m[1].toLowerCase())) cur = el;
  }
  return root;
}
global.location = {href: 'https://www.amazon.com/s?k=test'};
global.document = parseHTML(input.html);
global.innerHeight = 800;
global.getComputedStyle = () => ({display: 'block', visibility: 'visible', opacity: '1'});
const fn = new Function(input.script);
console.log(JSON.stringify(fn(...input.args)));
"""

SEARCH_FIXTURE = """
<div class="s-main-slot">
  <div data-component-type="s-search-result" data-asin="B0ORGANIC1" class="s-result-item">
    <h2><a href="/dp/B0ORGANIC1"><span>Organic product one title</span></a></h2></div>
  <div data-component-type="s-search-result" data-asin="B0SPONSOR1" class="s-result-item AdHolder">
    <span class="puis-sponsored-label-text">Sponsored</span>
    <h2><a href="/dp/B0SPONSOR1"><span>Sponsored product title</span></a></h2></div>
  <div class="s-result-item" data-asin="">
    <div class="a-carousel-container">
      <div class="a-carousel-header"><span>Sponsored</span><h2>Brands related to your search</h2></div>
      <ol class="a-carousel"><li><div data-asin="B0CAROUSL1"><a href="/dp/B0CAROUSL1"><span>Carousel ad card title</span></a></div></li></ol>
    </div>
  </div>
  <div class="s-result-item AdHolder" data-asin="">
    <div data-asin="B0ADHOLDR1"><a href="/dp/B0ADHOLDR1"><span>Ad holder card title</span></a></div></div>
  <div class="s-result-item" data-asin="">
    <div class="a-carousel-container">
      <div class="a-carousel-header"><h2>Customers frequently viewed</h2></div>
      <ol class="a-carousel">
        <li><div data-asin="B0WIDGETAD"><a href="/dp/B0WIDGETAD"><span>Widget ad card title</span></a>
            <span class="puis-sponsored-label-text">Sponsored</span></div></li>
        <li><div data-asin="B0WIDGET02"><a href="/dp/B0WIDGET02"><span>Widget plain card two</span></a></div></li>
      </ol>
    </div>
  </div>
  <div data-component-type="s-search-result" data-asin="B0ORGANIC2" class="s-result-item">
    <h2><a href="/dp/B0ORGANIC2"><span>Organic product two title</span></a></h2></div>
</div>
"""


def capture_card_script() -> str:
    class CaptureDriver:
        script = ""

        def execute_script(self, script, *_args):
            CaptureDriver.script = script
            return []

    front.extract_front_product_cards(CaptureDriver(), False)
    return CaptureDriver.script


def run_node(harness: str, payload: Dict[str, Any]) -> Any:
    completed = subprocess.run(
        [NODE, "-e", harness],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    return json.loads(completed.stdout)


# ---------------------------------------------------------------------------
# D1 / G2 storefront gate


@unittest.skipUnless(NODE, "node is required for the JS-level storefront tests")
class StorefrontBoxGrammarTests(unittest.TestCase):
    def test_rendered_values_and_optional_labels_do_not_block(self) -> None:
        base = "近30天销量(父体): 1,234\n近30天销量(子体): 300\nFBA费用: $5.12\n毛利率: 32%"
        boxes = {
            "B000000001": base + "\n上架时间:\n卖家:",
            "B000000002": "近30天销量(父体): -\n近30天销量(子体): --\nFBA费用: —\n毛利率: 暂无",
            "B000000003": "近30天销量(父体): 无\n近30天销量(子体): 300\nFBA费用: -$1.20\n毛利率: -12%",
            "B000000004": "近30天销量(父体): N/A\n近30天销量(子体): 0\nFBA费用: N/A\n毛利率:\n-3.5%",
            "B000000005": "近30天销量(父体): 1,234\n近30天销量(子体): 300\nFBA费用: $5.12\n毛利率:",
            "B000000006": "近30天销量(父体): 加载中\n近30天销量(子体): 300\nFBA费用: $5.12\n毛利率: 32%",
        }
        result = run_node(
            BOX_HARNESS,
            {
                "script": capture_storefront_script(),
                "boxes": boxes,
                "labels": list(front.STOREFRONT_REQUIRED_PLUGIN_LABELS),
            },
        )
        for asin in ("B000000001", "B000000002", "B000000003", "B000000004"):
            self.assertEqual(result[asin], "complete", asin)
        self.assertEqual(result["B000000005"], "field_missing:毛利率")
        self.assertEqual(result["B000000006"], "field_missing:近30天销量(父体)")


class StorefrontCoverageTests(unittest.TestCase):
    def runtime(self) -> SimpleNamespace:
        return SimpleNamespace(
            include_sponsored=False,
            page_scroll_step_ratio=0.85,
            storefront_plugin_stable_seconds=10.0,
        )

    def test_allowed_missing_is_floor_of_five_percent(self) -> None:
        self.assertEqual(
            [front.storefront_allowed_missing(n) for n in (0, 1, 19, 20, 39, 40, 48, 60)],
            [0, 0, 0, 1, 1, 2, 2, 3],
        )
        self.assertFalse(front.storefront_coverage_ok({"product_count": 19, "pending": {"A": "loading"}}))
        self.assertTrue(front.storefront_coverage_ok({"product_count": 20, "pending": {"A": "loading"}}))
        self.assertFalse(front.storefront_coverage_ok({"product_count": 20, "pending": {"A": "x", "B": "y"}}))
        self.assertFalse(front.storefront_coverage_ok({"product_count": 0, "pending": {}}))

    def _wait(self, snapshots: List[Dict[str, Any]]) -> str:
        clock = FakeClock()
        driver = SimpleNamespace(current_url="https://www.amazon.com/s?me=A", execute_script=lambda *_: True)
        with (
            patch.object(front, "inspect_sellersprite_block", return_value={"status": "data_loading"}),
            patch.object(front, "inspect_storefront_plugin_page", side_effect=snapshots),
            patch.object(front.time, "monotonic", side_effect=clock.monotonic),
            patch.object(front.time, "sleep", side_effect=clock.sleep),
            redirect_stdout(io.StringIO()),
        ):
            return front.wait_for_storefront_plugin_page(driver, self.runtime(), 140.0)

    def test_one_unloaded_card_of_twenty_is_ready(self) -> None:
        snap = {"at_bottom": True, "product_count": 20, "complete_count": 19,
                "pending": {"B0SLOW00001": "loading"}, "signature": "s"}
        self.assertEqual(self._wait([snap] * 30), "ok")

    def test_two_unloaded_cards_of_twenty_time_out(self) -> None:
        snap = {"at_bottom": True, "product_count": 20, "complete_count": 18,
                "pending": {"B0SLOW00001": "loading", "B0SLOW00002": "loading"}, "signature": "s"}
        self.assertEqual(self._wait([snap] * 100), "timeout")

    def test_g2_window_starts_when_signature_equals_previous_not_at_bottom(self) -> None:
        scrolling = {"at_bottom": False, "product_count": 2, "complete_count": 2, "pending": {}, "signature": "S"}
        bottom = dict(scrolling, at_bottom=True)
        self.assertEqual(self._wait([scrolling] + [bottom] * 40), "ok")


class StorefrontRecordTests(unittest.TestCase):
    def test_incomplete_cards_written_blank_with_marker_and_gate_values_kept(self) -> None:
        cards = [
            {"asin": "B000000001", "rank": "1", "is_sponsored": "no",
             "text": "近30天销量(父体): 1,234 近30天销量(子体): 300 FBA费用: -- 毛利率: -12% 配送:FBM 4.5 out of 5 1,234 ratings"},
            {"asin": "B000000002", "rank": "2", "is_sponsored": "no",
             "text": "近30天销量(父体): 99 FBA费用: $3.00 配送:FBA 4.1 out of 5"},
        ]
        runtime = SimpleNamespace(include_sponsored=False, field_selectors={})
        current = {"source_type": "storefront", "source_id": "s", "page_number": 1,
                   "page_url": "https://www.amazon.com/s?me=A"}
        driver = SimpleNamespace(current_url=current["page_url"])
        values = {"B000000001": {"近30天销量(父体)": "1,234", "近30天销量(子体)": "300",
                                 "FBA费用": "--", "毛利率": "-12%"}}
        with (
            patch.object(front, "extract_front_product_cards", return_value=cards),
            patch.object(front, "extract_table_rows", return_value=[]),
        ):
            records = front.merge_front_product_data(
                driver, runtime, current, "ok",
                plugin_incomplete_asins=["B000000002"], plugin_values=values,
            )
        complete, incomplete = records
        self.assertEqual(complete["plugin_fields_status"], "完整")
        self.assertEqual(complete["gross_margin"], "-12%")
        self.assertEqual(complete["fba_fee"], "--")
        self.assertEqual(incomplete["plugin_fields_status"], "插件字段未加载")
        self.assertEqual(incomplete["load_status"], "partial")
        for field_name in front.FRONT_PLUGIN_FIELDS:
            self.assertEqual(incomplete[field_name], "", field_name)
        self.assertEqual(incomplete["subcategory_bsr_ranks"], [])
        self.assertEqual(incomplete["rating_value"], "4.1")

    def test_keyword_records_have_no_plugin_marker(self) -> None:
        runtime = SimpleNamespace(include_sponsored=False, field_selectors={})
        current = {"source_type": "keyword_search", "source_id": "k", "page_number": 1, "page_url": "https://www.amazon.com/s?k=a"}
        with (
            patch.object(front, "extract_front_product_cards", return_value=[{"asin": "B000000001", "text": ""}]),
            patch.object(front, "extract_table_rows", return_value=[]),
        ):
            record = front.merge_front_product_data(SimpleNamespace(current_url=current["page_url"]), runtime, current, "ok")[0]
        self.assertNotIn("plugin_fields_status", record)

    def test_workbook_shows_plugin_status_column(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            records_path = Path(tmp) / "records.jsonl"
            rows = [
                {"asin": "B000000001", "plugin_fields_status": "插件字段未加载", "page_number": 1, "rank": "1"},
                {"asin": "B000000002", "plugin_fields_status": "完整", "page_number": 1, "rank": "2"},
            ]
            records_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
            output = Path(tmp) / "dedup_total.xlsx"
            front.write_front_workbook(records_path, Path(tmp) / "failures.jsonl", output)
            sheet = front.load_workbook(output).active
            headers = [cell.value for cell in sheet[1]]
            column = headers.index("插件字段状态")
            values = {row[headers.index("ASIN")]: row[column] for row in sheet.iter_rows(min_row=2, values_only=True)}
        self.assertEqual(values, {"B000000001": "插件字段未加载", "B000000002": "完整"})


# ---------------------------------------------------------------------------
# D2 quarantine / deferral in the main loop


class FakeSafeRuntimeMixin:
    def make_runtime(self, tmp: str, mode: str, keywords: List[str]) -> front.FrontRuntimeConfig:
        keywords_file = Path(tmp) / "keywords.csv"
        keywords_file.write_text("keyword\n" + "\n".join(keywords) + "\n", encoding="utf-8")
        raw = {
            "mode": "keyword_search",
            "job_id": "round1-job",
            "outputs_root": str(Path(tmp) / "outputs"),
            "keywords_file": str(keywords_file),
            "operation_mode": mode,
            "delivery_location_enabled": False,
        }
        return front.build_front_runtime_config(raw, no_resume=False)


def ok_result(worker_id: str, task: Dict[str, Any]) -> front.FrontPageResult:
    url = str(task.get("page_url") or "")
    record = {"asin": "B0" + str(abs(hash(task["keyword"])) % 10**8).zfill(8), "keyword": task["keyword"]}
    return front.FrontPageResult(
        worker_id=worker_id, task=task, page_key=front.front_page_key(task, url), page_url=url,
        raw_records=[record], accepted_records=[record], plugin_status="ok",
        next_task=None, finish_reason="no_next_page",
    )


def failing_result(worker_id: str, task: Dict[str, Any], reason: str = "plugin_data_timeout") -> front.FrontPageResult:
    return front.FrontPageResult(
        worker_id=worker_id, task=task, page_url=str(task.get("page_url") or ""),
        error_reason=reason, error_message="卖家精灵字段等待到期。", fatal=True,
    )


def make_fake_worker(behaviour: Callable[[str, Dict[str, Any]], front.FrontPageResult], seen: List[str]):
    class FakeWorker:
        def __init__(self, worker_id, runtime, results, *_args, **_kwargs) -> None:
            self.worker_id = worker_id
            self.results = results

        def start(self) -> None:
            pass

        def submit(self, task) -> None:
            seen.append(task["keyword"])
            self.results.put(behaviour(self.worker_id, task))

        def stop(self) -> None:
            pass

        def join(self, timeout=None) -> bool:
            return True

        def is_alive(self) -> bool:
            return True

    return FakeWorker


class DummyBatchPause:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def after_completed_page(self) -> None:
        pass


class QuarantineLoopTests(FakeSafeRuntimeMixin, unittest.TestCase):
    def run_loop(self, runtime, behaviour) -> tuple[Any, List[str], str]:
        seen: List[str] = []
        out = io.StringIO()
        error = None
        with (
            patch.object(front, "FrontWorker", make_fake_worker(behaviour, seen)),
            patch.object(front, "BatchPauseScheduler", DummyBatchPause),
            redirect_stdout(out),
        ):
            try:
                front._run_front_modes_unlocked({}, runtime, dry_run=False)
            except BaseException as exc:  # noqa: BLE001 - asserted by callers
                error = exc
        return error, seen, out.getvalue()

    def state(self, runtime) -> Dict[str, Any]:
        return json.loads((runtime.outputs_root / runtime.job_id / "state.json").read_text(encoding="utf-8"))

    def failures(self, runtime) -> List[Dict[str, Any]]:
        path = runtime.outputs_root / runtime.job_id / "failures.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_supervised_first_failure_stops_retry_later_second_skips(self) -> None:
        # An item-type failure (no environment cause): D2 skips on the 2nd run.
        # Environment failures (plugin_data_timeout, network) are covered in
        # test_round1b_front.py.
        def behaviour(worker_id, task):
            if task["keyword"] == "beta":
                return failing_result(worker_id, task, front.AmazonPageRetryExhausted.failure_code)
            return ok_result(worker_id, task)

        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.make_runtime(tmp, "supervised", ["alpha", "beta", "gamma"])
            error, seen, _out = self.run_loop(runtime, behaviour)
            self.assertIsInstance(error, run_outcome.CrawlStop)
            self.assertEqual(error.exit_code, run_outcome.EXIT_RETRY_LATER)
            self.assertEqual(seen, ["alpha", "beta"])
            state = self.state(runtime)
            self.assertEqual([task["keyword"] for task in state["pending"]], ["beta", "gamma"])
            self.assertEqual(list(state["item_failure_cycles"].values()), [1])

            error, seen, _out = self.run_loop(runtime, behaviour)
            self.assertIsNone(error)
            self.assertEqual(seen, ["beta", "gamma"])
            state = self.state(runtime)
            self.assertEqual(len(state["skipped_items"]), 1)
            self.assertEqual(state["skipped_items"][0]["reason"], front.AmazonPageRetryExhausted.failure_code)
            self.assertEqual(state["pending"], [])
            self.assertIn(front.QUARANTINE_REASON, [item["reason"] for item in self.failures(runtime)])
            job_dir = runtime.outputs_root / runtime.job_id
            self.assertEqual(front.skipped_count_for(job_dir), 1)
            self.assertEqual(run_outcome.exit_with(None, job_dir, skipped_count=1), run_outcome.EXIT_COMPLETED_WITH_SKIPS)

            # A third run never re-queues the skipped page.
            error, seen, _out = self.run_loop(runtime, behaviour)
            self.assertIsNone(error)
            self.assertEqual(seen, [])

    def test_success_clears_failure_count(self) -> None:
        calls = {"n": 0}

        def behaviour(worker_id, task):
            calls["n"] += 1
            return failing_result(worker_id, task) if calls["n"] == 1 else ok_result(worker_id, task)

        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.make_runtime(tmp, "supervised", ["alpha"])
            error, _seen, _out = self.run_loop(runtime, behaviour)
            self.assertEqual(error.exit_code, run_outcome.EXIT_RETRY_LATER)
            error, _seen, _out = self.run_loop(runtime, behaviour)
            self.assertIsNone(error)
            self.assertEqual(self.state(runtime).get("item_failure_cycles"), {})
            self.assertFalse(self.state(runtime).get("skipped_items"))

    def test_unattended_defers_to_end_then_retry_later_then_skips(self) -> None:
        def behaviour(worker_id, task):
            if task["keyword"] == "alpha":
                return failing_result(worker_id, task, front.AmazonPageRetryExhausted.failure_code)
            return ok_result(worker_id, task)

        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.make_runtime(tmp, "unattended", ["alpha", "beta"])
            error, seen, out = self.run_loop(runtime, behaviour)
            self.assertEqual(seen, ["alpha", "beta"])
            self.assertIsInstance(error, run_outcome.CrawlStop)
            self.assertEqual(error.exit_code, run_outcome.EXIT_RETRY_LATER)
            self.assertNotIn("队列已完成", out)
            self.assertIn("1 个页面已延期", out)
            self.assertEqual(len(self.state(runtime)["deferred_tasks"]), 1)

            error, seen, _out = self.run_loop(runtime, behaviour)
            self.assertIsNone(error)
            self.assertEqual(seen, ["alpha"])
            state = self.state(runtime)
            self.assertEqual(len(state["skipped_items"]), 1)
            self.assertFalse(state.get("deferred_tasks"))

    def test_restored_deferred_tasks_go_to_end_of_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.make_runtime(tmp, "unattended", ["alpha", "beta", "gamma"])
            queue_ = front.build_initial_queue(runtime)
            store = front.FrontStateStore(Path(tmp) / "state.json", runtime, queue_)
            store.load_or_create()
            leased = store.lease_next("tab-1")
            store.defer_task("tab-1", leased, "plugin_data_timeout")
            store.restore_deferred_tasks()
            self.assertEqual([task["keyword"] for task in store.data["pending"]], ["beta", "gamma", "alpha"])

    def test_non_fatal_failure_finishes_source_and_continues(self) -> None:
        def behaviour(worker_id, task):
            if task["keyword"] == "alpha":
                return front.FrontPageResult(worker_id=worker_id, task=task, error_reason="odd_page",
                                             error_message="x", fatal=False, finish_reason="odd_page")
            return ok_result(worker_id, task)

        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.make_runtime(tmp, "supervised", ["alpha", "beta"])
            error, seen, _out = self.run_loop(runtime, behaviour)
            self.assertIsNone(error)
            self.assertEqual(seen, ["alpha", "beta"])
            self.assertEqual(self.state(runtime)["completed_source_reasons"]["alpha|sort:Featured"], "odd_page")

    def test_categorized_stop_is_raised_and_page_kept(self) -> None:
        def behaviour(worker_id, task):
            stop = run_outcome.needs_human("login", next_action=front.NEXT_ACTION_SELLERSPRITE_LOGIN)
            return front.FrontPageResult(worker_id=worker_id, task=task, error_reason="needs_human",
                                         error_message="login", fatal=True, stop=stop)

        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.make_runtime(tmp, "supervised", ["alpha", "beta"])
            error, seen, _out = self.run_loop(runtime, behaviour)
            self.assertEqual(error.exit_code, run_outcome.EXIT_NEEDS_HUMAN)
            self.assertEqual(seen, ["alpha"])
            self.assertEqual([task["keyword"] for task in self.state(runtime)["pending"]], ["alpha", "beta"])


# ---------------------------------------------------------------------------
# Entry-point contract and classification


class EntryPointTests(FakeSafeRuntimeMixin, unittest.TestCase):
    def test_classification_of_page_stops(self) -> None:
        sign_in = front.front_stop_for(front.UserFacingError("amazon_sign_in_terminal: 检测到 Amazon 登录页"))
        self.assertEqual(sign_in.exit_code, run_outcome.EXIT_NEEDS_HUMAN)
        self.assertEqual(sign_in.next_action, front.NEXT_ACTION_AMAZON_SIGN_IN)
        captcha = front.front_stop_for(front.VerificationUnconfirmedError("amazon_robot_check_unconfirmed: 人工处理超时"))
        self.assertEqual(captcha.exit_code, run_outcome.EXIT_NEEDS_HUMAN)
        self.assertIn("人工验证", captcha.next_action)
        delivery = front.front_stop_for(front.DeliveryLocationUnconfirmedError("配送地址需要人工确认"))
        self.assertEqual(delivery.exit_code, run_outcome.EXIT_NEEDS_HUMAN)
        self.assertIn("配送地址", delivery.next_action)
        self.assertEqual(
            front.front_stop_for(front.PluginDataTimeout("x")).exit_code, run_outcome.EXIT_RETRY_LATER
        )
        with self.assertRaises(run_outcome.CrawlStop) as login:
            front.raise_for_blocked_plugin({"status": "login_required"})
        self.assertEqual(login.exception.exit_code, run_outcome.EXIT_NEEDS_HUMAN)
        self.assertEqual(login.exception.next_action, front.NEXT_ACTION_SELLERSPRITE_LOGIN)
        with self.assertRaises(front.PluginDataTimeout):
            front.raise_for_blocked_plugin({"status": "data_loading"})
        paused = SafetyPausedError("x", kind="risk_pause")
        self.assertIs(front.front_stop_for(paused), paused)

    def test_config_errors_exit_40(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = front.main(["--config", str(Path(tmp) / "missing.json")])
            self.assertEqual(code, run_outcome.EXIT_CONFIG_ERROR)
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"mode": "keyword_search", "keywords_file": str(Path(tmp) / "nope.csv")}), encoding="utf-8")
            self.assertEqual(front.main(["--config", str(bad)]), run_outcome.EXIT_CONFIG_ERROR)

    def write_config(self, tmp: str) -> Path:
        keywords_file = Path(tmp) / "keywords.csv"
        keywords_file.write_text("keyword\nalpha\n", encoding="utf-8")
        config = Path(tmp) / "config.json"
        config.write_text(json.dumps({
            "mode": "keyword_search", "job_id": "entry-job", "outputs_root": str(Path(tmp) / "outputs"),
            "keywords_file": str(keywords_file), "delivery_location_enabled": False,
        }), encoding="utf-8")
        return config

    def test_dry_run_exit_0(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            self.assertEqual(front.main(["--config", str(self.write_config(tmp)), "--dry-run"]), 0)

    def test_job_label_set_before_acquire_and_summary_written_then_finalized(self) -> None:
        acquired_labels: List[str] = []

        class FakeSafety:
            rate_probe_active = False

            def __init__(self, *args, **kwargs) -> None:
                self.job_label = ""
                self.status_path = None

            def acquire(self) -> None:
                acquired_labels.append(self.job_label)

            def begin(self, **_kwargs) -> None:
                pass

            def fail_review(self) -> None:
                pass

            def release(self) -> None:
                pass

            def heartbeat(self, *_args, **_kwargs) -> None:
                pass

        def fake_summary(job_dir, mode, _safety) -> None:
            job_dir.mkdir(parents=True, exist_ok=True)
            (job_dir / "run_summary.json").write_text(json.dumps({"operation_mode": mode}), encoding="utf-8")

        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            config = self.write_config(tmp)
            with (
                patch.object(front, "LocalSafetyController", FakeSafety),
                patch.object(front, "write_run_summary", side_effect=fake_summary),
                patch.object(front, "configure_manual_waits") as manual_waits,
                patch.object(front, "_run_front_modes_unlocked",
                             side_effect=run_outcome.needs_human("x", next_action=front.NEXT_ACTION_SELLERSPRITE_VERIFY)),
            ):
                code = front.main(["--config", str(config)])
            summary = json.loads((Path(tmp) / "outputs" / "entry-job" / "run_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(acquired_labels, ["entry-job"])
        self.assertEqual(manual_waits.call_args_list[0].kwargs["continue_file"].name, "CONTINUE")
        self.assertEqual(manual_waits.call_args_list[-1].kwargs, {})
        self.assertEqual(code, run_outcome.EXIT_NEEDS_HUMAN)

        class HeldSafety(FakeSafety):
            def acquire(self) -> None:
                raise SafetyPausedError("busy", kind="lock_held")

        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            config = self.write_config(tmp)
            with patch.object(front, "LocalSafetyController", HeldSafety):
                held_code = front.main(["--config", str(config)])
            self.assertEqual(held_code, run_outcome.EXIT_LOCK_HELD)
            # Another process may own this job: its summary/heartbeat stay untouched.
            self.assertFalse((Path(tmp) / "outputs" / "entry-job" / "run_summary.json").exists())
        self.assertEqual(summary["operation_mode"], "supervised")
        self.assertEqual(summary["status"], "needs_human")
        self.assertEqual(summary["next_action"], front.NEXT_ACTION_SELLERSPRITE_VERIFY)


# ---------------------------------------------------------------------------
# D3 bsr defaults and single workbook


class BsrModeTests(unittest.TestCase):
    def test_category_runtime_owns_bsr_defaults(self) -> None:
        raw = {"mode": "bsr_category", "start_url": "https://www.amazon.com/gp/bestsellers/x/1",
               "include_root": False, "max_depth": "", "outputs_root": tempfile.gettempdir()}
        runtime = front.build_category_runtime_config(raw, front.DEFAULT_CONFIG, False)
        self.assertTrue(runtime.include_root)
        self.assertEqual((runtime.max_depth, runtime.max_pages_per_category), (3, 2))

    def test_bsr_passes_config_through_and_keeps_only_dedup_workbook(self) -> None:
        captured: Dict[str, Any] = {}
        with tempfile.TemporaryDirectory() as tmp:
            category_runtime = SimpleNamespace(
                outputs_root=Path(tmp), job_id="bsr-job", include_root=True,
                max_depth=3, max_pages_per_category=2,
            )

            def fake_build(config, *_args):
                captured.update(config)
                return category_runtime

            def fake_crawl(_runtime, dry_run):
                job_dir = Path(tmp) / "bsr-job"
                job_dir.mkdir(parents=True, exist_ok=True)
                (job_dir / "records.jsonl").write_text(json.dumps({"asin": "B000000001"}) + "\n", encoding="utf-8")
                (job_dir / "total_bsr-job_merged.xlsx").write_bytes(b"x")
                return 0

            context: Dict[str, Any] = {}
            with (
                patch.object(front, "build_category_runtime_config", side_effect=fake_build),
                patch.object(front, "run_category_crawl", side_effect=fake_crawl),
                redirect_stdout(io.StringIO()),
            ):
                front.run_bsr_category_mode(
                    {"mode": "bsr_category", "start_url": "https://www.amazon.com/gp/bestsellers/x"},
                    SimpleNamespace(resume_after_review=False), False, False, context=context,
                )
            job_dir = Path(tmp) / "bsr-job"
            self.assertTrue((job_dir / "dedup_total.xlsx").exists())
            self.assertFalse((job_dir / "total_bsr-job_merged.xlsx").exists())
            self.assertEqual(context["job_dir"], job_dir)
        self.assertEqual(captured, {"mode": "bsr_category", "start_url": "https://www.amazon.com/gp/bestsellers/x"})


# ---------------------------------------------------------------------------
# W2 sorted landing


class SortedLandingTests(unittest.TestCase):
    def test_search_store_url_opens_sorted(self) -> None:
        task = {"source_type": "storefront", "page_url": "https://www.amazon.com/s?me=A1B2C3",
                "store_sort_order": "Newest Arrivals", "prepared_storefront": False}
        self.assertIn("s=date-desc-rank", front.storefront_landing_url(task))
        self.assertEqual(
            front.storefront_landing_url(dict(task, page_url="https://www.amazon.com/stores/X/page/1")),
            "https://www.amazon.com/stores/X/page/1",
        )
        self.assertEqual(front.storefront_landing_url(dict(task, prepared_storefront=True)), task["page_url"])
        keyword = {"source_type": "keyword_search", "page_url": "https://www.amazon.com/s?k=a&s=review-rank"}
        self.assertEqual(front.storefront_landing_url(keyword), keyword["page_url"])

    def _prepare(self, current_url: str, sort_order: str) -> List[str]:
        opened: List[str] = []
        driver = SimpleNamespace(current_url=current_url, execute_script=lambda *_a: "")
        current = {"store_sort_order": sort_order, "prepared_storefront": False}
        with patch.object(front, "wait_for_product_cards", return_value=True):
            front.prepare_storefront_page(driver, SimpleNamespace(), current, page_opener=opened.append)
        self.assertTrue(current["prepared_storefront"])
        return opened

    def test_no_second_navigation_when_sort_took_effect(self) -> None:
        self.assertEqual(self._prepare("https://www.amazon.com/s?me=A&s=date-desc-rank", "Newest Arrivals"), [])
        self.assertEqual(self._prepare("https://www.amazon.com/s?me=A&s=relevanceblender", "Featured"), [])
        self.assertEqual(self._prepare("https://www.amazon.com/s?me=A", "Featured"), [])

    def test_fallback_navigation_when_url_route_did_not_take_effect(self) -> None:
        opened = self._prepare("https://www.amazon.com/s?me=A", "Price: Low to High")
        self.assertEqual(len(opened), 1)
        self.assertIn("s=price-asc-rank", opened[0])


# ---------------------------------------------------------------------------
# sellersprite-check


class SellerSpriteCheckTests(unittest.TestCase):
    TEMPLATE = SKILL_ROOT / "assets" / "config" / "amazon_front_bsr_category.json"

    def setUp(self) -> None:
        import run_sellersprite_check as chk

        self.chk = chk

    def run_main(self, args: List[str]) -> tuple[int, Dict[str, Any]]:
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.chk.main(args)
        return code, json.loads(out.getvalue())

    def test_bundled_bsr_template_resolves_start_url(self) -> None:
        raw = json.loads(self.TEMPLATE.read_text(encoding="utf-8"))
        _runtime, url, current = self.chk.resolve_check_target(raw, self.TEMPLATE)
        self.assertEqual(url, raw["start_url"])
        self.assertEqual(current["page_url"], raw["start_url"])

    def test_lock_and_risk_pause_have_their_own_status(self) -> None:
        for kind, status, code in (
            ("lock_held", "lock_held", run_outcome.EXIT_LOCK_HELD),
            ("risk_pause", "risk_pause", run_outcome.EXIT_RISK_PAUSE),
        ):
            with patch.object(self.chk.LocalSafetyController, "acquire",
                              side_effect=SafetyPausedError("paused", kind=kind)):
                exit_code, report = self.run_main(["--config", str(self.TEMPLATE)])
            self.assertEqual((exit_code, report["status"]), (code, status))

    def test_missing_config_and_unreachable_browser(self) -> None:
        exit_code, report = self.run_main(["--config", "/nonexistent/config.json"])
        self.assertEqual((exit_code, report["status"]), (run_outcome.EXIT_CONFIG_ERROR, "config_error"))
        with (
            patch.object(self.chk.LocalSafetyController, "acquire"),
            patch.object(self.chk.LocalSafetyController, "begin"),
            patch.object(self.chk, "start_driver", side_effect=front.UserFacingError("没有找到可连接的 Chrome CDP 调试窗口。")),
        ):
            exit_code, report = self.run_main(["--config", str(self.TEMPLATE)])
        self.assertEqual((exit_code, report["status"]), (run_outcome.EXIT_NEEDS_HUMAN, "browser_unreachable"))
        self.assertEqual(self.chk.exit_code_for_status("data_loading"), run_outcome.EXIT_RETRY_LATER)
        self.assertEqual(self.chk.exit_code_for_status("ready"), 0)


# ---------------------------------------------------------------------------
# G6 sponsored carousels and next-page guard


@unittest.skipUnless(NODE, "node is required for the JS-level card tests")
class SponsoredCarouselCardTests(unittest.TestCase):
    def cards(self, include_sponsored: bool) -> List[Dict[str, Any]]:
        return run_node(
            MINI_DOM_HARNESS,
            {"script": capture_card_script(), "html": SEARCH_FIXTURE, "args": [include_sponsored, False]},
        )

    def test_cards_inside_sponsored_carousels_and_ad_holders_are_sponsored(self) -> None:
        organic = self.cards(False)
        # Selector order (search results first), as before this change.
        self.assertEqual([card["asin"] for card in organic], ["B0ORGANIC1", "B0ORGANIC2", "B0WIDGET02"])
        self.assertEqual([card["rank"] for card in organic], ["1", "2", "3"])
        everything = {card["asin"]: card["is_sponsored"] for card in self.cards(True)}
        self.assertEqual(
            everything,
            {
                "B0ORGANIC1": "no", "B0SPONSOR1": "yes", "B0CAROUSL1": "yes", "B0ADHOLDR1": "yes",
                "B0WIDGETAD": "yes", "B0WIDGET02": "no", "B0ORGANIC2": "no",
            },
        )


class NextPageGuardTests(unittest.TestCase):
    def _next(self, next_url: str):
        driver = SimpleNamespace(current_url="https://www.amazon.com/s?k=dash+cam&page=1")
        runtime = SimpleNamespace(max_pages_per_keyword=7, store_page_limit=None)
        current = {"source_type": "keyword_search", "page_number": 1, "page_url": driver.current_url}
        with patch.object(front, "find_next_page_url", return_value=next_url):
            return front.build_next_front_task(driver, runtime, current, [{"asin": "B000000001"}])

    def test_product_link_is_never_followed_as_next_page(self) -> None:
        self.assertEqual(self._next("https://www.amazon.com/Nextbase-Dash-Cam/dp/B0ABCDEFGH"), (None, "invalid_next_url"))
        self.assertEqual(self._next("https://www.amazon.com/gp/help/customer/display.html"), (None, "invalid_next_url"))
        task, reason = self._next("https://www.amazon.com/s?k=dash+cam&page=2")
        self.assertEqual(reason, "")
        self.assertEqual(task["page_number"], 2)


if __name__ == "__main__":
    unittest.main()
