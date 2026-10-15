"""Keyword fault injection and healthy-path timing, without live browser traffic."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from amazon_plugin_crawler import PluginCrawler, PanelState, fingerprint, source_task
from keyword_load_recovery import KeywordLoadRecovery
from opencli_bridge import BridgeTransientError
from opencli_read_recovery import BridgeReadRecoveryExhausted
from run_outcome import CrawlStop
import test_plugin_collection as fixtures
from test_plugin_collection import FakeBridge


class InstrumentedBridge(FakeBridge):
    def __init__(self, clock, count=16, increments=None):
        super().__init__(count, increments)
        self.url = "https://www.amazon.com/s?k=test"
        self.clock = clock
        self.reads = 0
        self.started = None
        self.clicked = 0
        self.attempt_id = ""
        self.delay = None
        self.hide_button = False
        self.lose_reply = False
        self.error = ""
        self.fail_attempts = 0
        self.extra = {}
        self.outage_until = 0

    def panel(self, action="snapshot", **kwargs):
        if action == "snapshot":
            self.reads += 1
            if self.clock.now() < self.outage_until:
                raise BridgeTransientError("cdp_timeout")
            elapsed = self.clock.now() - self.started if self.started is not None else 0
            if self.started is not None and self.delay is not None and elapsed >= self.delay:
                self.count = 26
                self.increments = []
            busy = bool(self.started is not None and self.delay is not None and elapsed < self.delay)
            error = f"加载失败，请重试（尝试 {self.clicked}）" if self.clicked and self.clicked <= self.fail_attempts else self.error
            return {**super().panel(), "more": bool(self.increments) and not self.hide_button,
                    "more_count": int(bool(self.increments) and not self.hide_button),
                    "keyword_busy": busy, "keyword_load_attempt": self.attempt_id,
                    "keyword_load_error": error, **self.extra}
        if action == "load":
            self.actions.append(action)
            if kwargs.get("keyword") and self.count != kwargs["expectedCount"]:
                return {"not_clicked": True}
            self.clicked += 1
            self.attempt_id = kwargs.get("loadAttempt", "")
            self.started = self.clock.now()
            if not self.delay and self.clicked > self.fail_attempts:
                self.count += self.increments.pop(0)
            if self.lose_reply:
                self.lose_reply = False
                raise BridgeTransientError("client_timeout")
            return {"clicked": "加载更多"}
        return super().panel(action, **kwargs)


class KeywordRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PluginCollectionTests()
        self.fixture.setUp()
        self.clock = self.fixture.clock
        self.root = self.fixture.root

    def tearDown(self):
        self.fixture.tearDown()

    def make(self, count=16, increments=None, **options):
        cfg = self.fixture.cfg(mode="keyword_search", **options)
        b = InstrumentedBridge(self.clock, count, increments)
        c = self.fixture.crawler(cfg, b)
        c.materialize = lambda: None
        c.exports = []
        c.export = lambda t, s: (c.exports.append(s["count"]) or [{}] * s["count"], {})
        return c, b, source_task(b.url)

    def pending(self, c, task, before=16):
        c.state.data["current_task"] = {**task, "load_pending": True, "plugin_count": before,
            "document_id": c.bridge.document_id, "loads_since_export": 0}
        c.state.save()

    def restart(self, c):
        # Re-read JSON, not the old in-memory dictionary.
        c.state = PanelState(c.state.path, fingerprint(c.cfg, []))
        c.read_recovery.data = c.state.data
        c.read_recovery.save = c.state.save

    def test_healthy_path_keeps_original_time_and_call_counts(self):
        cases = [(16, [], {}, 10, 6, 0), (2001, [10], {}, 10, 6, 0),
                 (16, [10], {}, 20, 14, 1), (16, [10, 10], {}, 30, 22, 2),
                 (1990, [50, 50], {}, 20, 14, 1)]
        for i, (count, increments, opts, seconds, reads, clicks) in enumerate(cases):
            with self.subTest(case=i):
                c, b, task = self.make(count, increments, job_id=f"healthy-{i}", **opts)
                start = self.clock.now()
                c.run_task(task, prepared=True)
                self.assertEqual(self.clock.now() - start, seconds)
                self.assertEqual(b.reads, reads)
                self.assertEqual(b.clicked, clicks)
                self.assertEqual(len(c.exports), 1)

    def test_storefront_keeps_original_no_growth_end_behavior(self):
        cfg = self.fixture.cfg()
        b = FakeBridge(16, [0])
        c = self.fixture.crawler(cfg, b)
        c.materialize = lambda: None
        c.export = lambda t, s: ([{}] * s["count"], {})
        task = source_task(b.url)
        c.run_task(task, prepared=True)
        self.assertTrue(c.state.data["tasks"][task["key"]]["complete"])
        self.assertEqual(b.actions, ["load"])

    def test_late_results_four_to_eight_minutes_click_once(self):
        for delay in (240, 480):
            with self.subTest(delay=delay):
                c, b, task = self.make(increments=[10], job_id=f"late-{delay}")
                b.delay = delay
                c.run_task(task, prepared=True)
                self.assertEqual(b.clicked, 1)
                self.assertEqual(c.exports, [26])

    def test_no_growth_disappeared_button_never_completes_or_exports(self):
        c, b, task = self.make(increments=[0])
        with self.assertRaises(CrawlStop) as caught:
            c.run_task(task, prepared=True)
        self.assertEqual(caught.exception.exit_code, 20)
        self.assertEqual(b.clicked, 1)
        self.assertEqual(c.exports, [])
        self.assertNotIn(task["key"], c.state.data["tasks"])
        self.assertTrue(c.state.data["current_task"]["load_pending"])
        self.assertEqual(c.state.data["current_task"]["keyword_load"]["elapsed"], 600)
        self.restart(c)
        before = b.reads
        with self.assertRaises(CrawlStop):
            c.run_task(task, prepared=True)
        self.assertEqual(b.reads - before, 1)
        self.assertEqual(b.clicked, 1)

    def test_lost_click_reply_reads_result_without_replay(self):
        c, b, task = self.make(increments=[10])
        b.lose_reply = True
        c.run_task(task, prepared=True)
        self.assertEqual(b.clicked, 1)
        self.assertEqual(c.exports, [26])

    def test_old_pending_checkpoint_waits_instead_of_clicking(self):
        c, b, task = self.make(increments=[10])
        self.pending(c, task)
        b.delay = 240
        b.started = self.clock.now()
        self.restart(c)
        c.run_task(task, prepared=True)
        self.assertEqual(b.clicked, 0)
        self.assertEqual(c.exports, [26])

    def test_expired_pending_can_accept_already_arrived_result(self):
        c, b, task = self.make(increments=[])
        self.pending(c, task)
        helper = KeywordLoadRecovery(c)
        record = helper.new_record(16)
        record["elapsed"] = 600
        c.state.data["current_task"]["keyword_load"] = record
        b.count = 26
        c.run_task(task, prepared=True)
        self.assertEqual(b.clicked, 0)
        self.assertEqual(c.exports, [26])

    def test_explicit_failure_respects_original_retry_schedule_and_budget(self):
        for mode, failures, elapsed, clicks in [("supervised", 1, 80, 2),
                                                ("unattended", 2, 440, 3)]:
            with self.subTest(mode=mode):
                c, b, task = self.make(increments=[10], operation_mode=mode, job_id=mode)
                b.fail_attempts = failures
                start = self.clock.now()
                c.run_task(task, prepared=True)
                self.assertEqual(b.clicked, clicks)
                self.assertEqual(self.clock.now() - start, elapsed)

    def test_explicit_retry_exhaustion_and_restart_do_not_reset_budget(self):
        c, b, task = self.make(increments=[10])
        # Different, fresh failure text for each retry, not a stale alert.
        original = b.panel
        def panel(action="snapshot", **kw):
            result = original(action, **kw)
            if action == "snapshot" and b.clicked:
                result["keyword_load_error"] = f"加载失败，请重试 {b.clicked}"
            return result
        b.panel = panel
        b.fail_attempts = 99
        with self.assertRaises(CrawlStop): c.run_task(task, prepared=True)
        self.assertEqual(b.clicked, 2)
        self.restart(c)
        with self.assertRaises(CrawlStop): c.run_task(task, prepared=True)
        self.assertEqual(b.clicked, 2)
        self.assertEqual(c.exports, [])

    def test_stale_failure_alert_does_not_authorize_retry(self):
        c, b, task = self.make(increments=[0, 10])
        b.error = "加载失败，请重试"
        with self.assertRaises(CrawlStop): c.run_task(task, prepared=True)
        self.assertEqual(b.clicked, 1)

    def test_cooldown_late_growth_cancels_retry_click(self):
        c, b, task = self.make(increments=[10])
        b.fail_attempts = 1
        original = b.panel
        def panel(action="snapshot", **kw):
            if b.started is not None and self.clock.now() - b.started >= 30:
                b.count, b.increments = 26, []
            return original(action, **kw)
        b.panel = panel
        c.run_task(task, prepared=True)
        self.assertEqual(b.clicked, 1)
        self.assertEqual(c.exports, [26])

    def test_bridge_outage_excluded_and_stability_restarted(self):
        c, b, task = self.make(increments=[10])
        original = b.panel
        once = [False]
        def panel(action="snapshot", **kw):
            if action == "snapshot" and b.clicked and not once[0]:
                once[0] = True
                b.outage_until = self.clock.now() + 700
            return original(action, **kw)
        b.panel = panel
        c.run_task(task, prepared=True)
        self.assertEqual(b.clicked, 1)
        self.assertGreater(c.read_recovery.blocked_seconds, 600)
        self.assertEqual(c.exports, [26])

    def test_captcha_and_identity_errors_do_not_retry_or_export(self):
        for kind in ("captcha", "identity"):
            c, b, task = self.make(increments=[10], job_id=kind)
            original = b.panel
            def panel(action="snapshot", **kw):
                if action == "snapshot" and b.clicked:
                    if kind == "identity": raise CrawlStop("identity", exit_code=30)
                    return {**original(action, **kw), "captcha": True}
                return original(action, **kw)
            b.panel = panel
            with self.assertRaises((RuntimeError, CrawlStop)): c.run_task(task, prepared=True)
            self.assertEqual(b.clicked, 1)
            self.assertEqual(c.exports, [])

    def test_count_regression_does_not_retry(self):
        c, b, task = self.make(increments=[-1, 10])
        with self.assertRaises(CrawlStop) as caught: c.run_task(task, prepared=True)
        self.assertEqual(caught.exception.exit_code, 30)
        self.assertEqual(b.clicked, 1)

    def test_interrupted_observation_resumes_remaining_budget(self):
        c, b, task = self.make(increments=[0])
        original_wait = c.wait
        def wait(seconds, *args, **kw):
            if b.clicked and c.state.data["current_task"]["keyword_load"]["elapsed"] >= 200:
                raise KeyboardInterrupt()
            return original_wait(seconds, *args, **kw)
        c.wait = wait
        with self.assertRaises(KeyboardInterrupt): c.run_task(task, prepared=True)
        elapsed = c.state.data["current_task"]["keyword_load"]["elapsed"]
        c.wait = original_wait
        self.restart(c)
        start = self.clock.now()
        with self.assertRaises(CrawlStop): c.run_task(task, prepared=True)
        self.assertEqual(self.clock.now() - start, 600 - elapsed)
        self.assertEqual(b.clicked, 1)

    def test_interrupted_retry_cooldown_keeps_original_deadline(self):
        c, b, task = self.make(increments=[10])
        b.fail_attempts = 1
        original_wait = c.wait
        def wait(seconds, phase="waiting", detail=""):
            if phase == "retry_wait":
                self.clock.sleep(20)
                raise KeyboardInterrupt()
            return original_wait(seconds, phase, detail)
        c.wait = wait
        with self.assertRaises(KeyboardInterrupt): c.run_task(task, prepared=True)
        c.wait = original_wait
        self.restart(c)
        start = self.clock.now()
        c.run_task(task, prepared=True)
        self.assertEqual(self.clock.now() - start, 50)  # Remaining 40 + stable 10.
        self.assertEqual(b.clicked, 2)

    def test_read_recovery_exhaustion_preserves_pending_and_does_not_retry(self):
        c, b, task = self.make(increments=[10])
        original = b.panel
        def panel(action="snapshot", **kw):
            if action == "snapshot" and b.clicked:
                raise BridgeTransientError("cdp_timeout")
            return original(action, **kw)
        b.panel = panel
        with self.assertRaises(BridgeReadRecoveryExhausted): c.run_task(task, prepared=True)
        self.assertEqual(b.clicked, 1)
        self.assertTrue(c.state.data["current_task"]["load_pending"])
        self.assertEqual(c.state.data["current_task"]["keyword_load"]["elapsed"], 0)
        self.assertEqual(c.exports, [])

    def test_unknown_failure_does_not_touch_pending_download_ledger(self):
        c, b, task = self.make(increments=[0])
        ledger = b'{"pending":{"job":"original","download":{"id":41}}}'
        c.export_state_path.write_bytes(ledger)
        with self.assertRaises(CrawlStop): c.run_task(task, prepared=True)
        self.assertEqual(c.export_state_path.read_bytes(), ledger)
        self.assertEqual(c.exports, [])

    def test_interrupted_preclick_rest_resumes_only_unsent_operation(self):
        c, b, task = self.make(increments=[10])
        original = c.safety.before_remote_action
        def interrupted(action):
            raise KeyboardInterrupt()
        c.safety.before_remote_action = interrupted
        with self.assertRaises(KeyboardInterrupt): c.run_task(task, prepared=True)
        self.assertEqual(b.clicked, 0)
        self.assertEqual(c.state.data["current_task"]["keyword_load"]["status"], "not_dispatched")
        self.restart(c)
        c.safety.before_remote_action = original
        c.run_task(task, prepared=True)
        self.assertEqual(b.clicked, 1)
        self.assertEqual(c.exports, [26])


if __name__ == "__main__":
    unittest.main()
