"""Fault injection only: no browser, model, network or shared traffic state."""
import copy
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from opencli_bridge import BridgeTransientError, OpenCliBridge, TRANSIENT_CODES
from opencli_read_recovery import ReadRecovery, BridgeReadRecoveryExhausted
from run_outcome import CrawlStop, needs_human
from safety_control import SafetyPausedError
import test_plugin_collection as pc
import test_image_background as ib


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.clock = ib.Clock()
        self.bridge = SimpleNamespace(target='fixed', session='session', validate_target=Mock())
        self.data, self.saved = {}, []
        self.safety = SimpleNamespace(heartbeat=Mock(), _load_pause=lambda: None)
        self.recovery = self.make()

    def make(self, sleep=None):
        return ReadRecovery(self.bridge, self.data, lambda: self.saved.append(copy.deepcopy(self.data)),
                            self.safety, now=self.clock.now, sleep=sleep or self.clock.sleep)

    def test_exact_schedule_and_outage_deadline(self):
        times = []
        def fail():
            times.append(self.clock.t)
            raise BridgeTransientError('client_timeout')
        with self.assertRaises(BridgeReadRecoveryExhausted) as caught:
            self.recovery.read('snapshot', fail)
        self.assertEqual(caught.exception.exit_code, 20)
        self.assertEqual(times, [0, 2, 4, 34, 94, 214, 514, 814, 1114, 1414, 1714])
        self.assertEqual(self.clock.t, 1800)
        self.assertEqual(self.recovery.blocked_seconds, 1800)
        self.assertTrue(self.data[ReadRecovery.KEY])
        self.assertEqual(self.safety.heartbeat.call_args.args[0], 'bridge_retry_wait')

    def test_slow_failed_commands_count_toward_limit(self):
        def fail():
            self.clock.sleep(35)
            raise BridgeTransientError('client_timeout')
        with self.assertRaises(BridgeReadRecoveryExhausted): self.recovery.read('snapshot', fail)
        self.assertEqual(self.clock.t, 1800)
        self.assertEqual(self.data[ReadRecovery.KEY]['started_at'], 0)

    def test_restart_preserves_next_attempt_and_budget(self):
        def interrupt(n):
            self.clock.sleep(n)
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.make(interrupt).read('snapshot', Mock(side_effect=BridgeTransientError('cdp_timeout')))
        saved = copy.deepcopy(self.data[ReadRecovery.KEY])
        # Even a separately failing target listing must not steal/reset the snapshot budget.
        target = Mock(side_effect=[BridgeTransientError('cdp_timeout'), {'page': 'fixed'}])
        self.make().read('target', target)
        self.assertEqual(self.data[ReadRecovery.KEY]['deadline'], saved['deadline'])
        self.assertEqual(self.data[ReadRecovery.KEY]['operation'], 'snapshot')
        self.make().read('snapshot', lambda: {'ok': True})
        self.assertNotIn(ReadRecovery.KEY, self.data)
        self.assertEqual(self.clock.t, 4)

    def test_expired_restart_can_read_after_repair_but_cannot_retry_again(self):
        with self.assertRaises(BridgeReadRecoveryExhausted):
            self.recovery.read('snapshot', Mock(side_effect=BridgeTransientError('cdp_timeout')))
        failed = Mock(side_effect=BridgeTransientError('cdp_timeout'))
        with self.assertRaises(BridgeReadRecoveryExhausted): self.make().read('snapshot', failed)
        self.assertEqual(failed.call_count, 1)
        self.assertEqual(self.clock.t, 1800)
        resumed = self.make()
        resumed.read('target', lambda: True)
        self.assertIn(ReadRecovery.KEY, self.data)
        resumed.read('snapshot', lambda: True)
        self.assertNotIn(ReadRecovery.KEY, self.data)

    def test_risk_pause_during_wait_aborts_without_more_reads(self):
        read = Mock(side_effect=BridgeTransientError('client_timeout'))
        self.safety._load_pause = lambda: {'active': True} if self.clock.t else None
        with self.assertRaises(SafetyPausedError): self.recovery.read('snapshot', read)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(self.clock.t, 2)

    def test_changed_target_or_document_is_never_rebound(self):
        for changed in ('target', 'document'):
            self.setUp()
            def sleep(n):
                self.clock.sleep(n)
                if changed == 'target': self.bridge.target = 'other'
            read = Mock(side_effect=[BridgeTransientError('client_timeout'), needs_human('document changed')])
            with self.assertRaises(CrawlStop) as caught: self.make(sleep).read('snapshot', read)
            self.assertEqual(caught.exception.exit_code, 30)
            self.assertLessEqual(read.call_count, 2)

    def test_structured_transport_errors_classified_for_all_reads(self):
        bridge = OpenCliBridge('test', 'fixed', command=['unused'])
        for code in TRANSIENT_CODES:
            error = {'error': {'code': code}}
            process = SimpleNamespace(returncode=1, stdout=json.dumps(error))
            with self.subTest(code=code), patch('opencli_bridge.subprocess.run', return_value=process):
                for read in (bridge.validate_target, bridge.panel, lambda: bridge.wait_download('x')):
                    with self.assertRaises(BridgeTransientError): read()
        with patch.object(bridge, 'evaluate', return_value={'error': '工作页网址已变化'}):
            with self.assertRaises(CrawlStop) as caught: bridge.panel()
            self.assertNotIsInstance(caught.exception, BridgeTransientError)

    def test_normal_download_no_match_is_not_a_transport_fault(self):
        bridge = OpenCliBridge('test', 'fixed', command=['unused'])
        process = SimpleNamespace(returncode=1, stdout=json.dumps({'error': {'code': 'wait_timeout'}}))
        with patch('opencli_bridge.subprocess.run', return_value=process):
            self.assertIn('error', bridge.wait_download('x'))

    def test_inflight_cli_timeout_is_bounded_by_outage_budget(self):
        bridge = OpenCliBridge('test', 'fixed', command=['unused'])
        bridge.read_deadline = 105
        with patch('opencli_bridge.time.monotonic', return_value=100), patch('opencli_bridge.subprocess.run',
                return_value=SimpleNamespace(returncode=0, stdout='[]')) as run:
            bridge.tabs()
        self.assertEqual(run.call_args.kwargs['timeout'], 5)


class PluginRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fx = pc.PluginCollectionTests()
        self.fx.setUp()
        self.addCleanup(self.fx.tearDown)

    def crawler(self, count=4, increments=None):
        bridge = pc.FakeBridge(count, increments)
        cfg = self.fx.cfg(store_max_records='all')
        return self.fx.crawler(cfg, bridge), bridge, pc.source_task(bridge.url)

    def test_load_then_long_read_outage_does_not_click_twice(self):
        c, b, task = self.crawler(increments=[4])
        original, failures = b.panel, [0]
        def panel(action='snapshot', **kwargs):
            if action == 'snapshot' and 'load' in b.actions and failures[0] < 6:
                failures[0] += 1
                raise BridgeTransientError('client_timeout')
            return original(action, **kwargs)
        b.panel = panel
        c.export = Mock(return_value=([{}] * 8, {'plugin_count': 8}))
        c.materialize = Mock()
        c.run_task(task, prepared=True)
        self.assertEqual(b.actions, ['load'])
        self.assertEqual(c.safety.actions, ['plugin:load'])
        self.assertEqual(c.export.call_count, 1)
        self.assertEqual(c.state.data['tasks'][task['key']]['retained_count'], 8)
        self.assertGreaterEqual(c.read_recovery.blocked_seconds, 514)

    def test_read_exhaustion_never_enters_business_load_retry_or_skip(self):
        c, b, task = self.crawler(increments=[4])
        original = b.panel
        def panel(action='snapshot', **kwargs):
            if action == 'snapshot' and 'load' in b.actions:
                raise BridgeTransientError('client_timeout')
            return original(action, **kwargs)
        b.panel = panel
        c.export = Mock()
        with self.assertRaises(BridgeReadRecoveryExhausted): c.run_task(task, prepared=True)
        self.assertEqual(b.actions, ['load'])
        c.export.assert_not_called()
        self.assertTrue(c.state.data['current_task']['load_pending'])
        self.assertFalse(c.state.data['tasks'])
        self.assertFalse(c.state.data.get('skipped_items'))
        # Restart after connectivity returns: reconcile the already completed load.
        b.panel = original
        resumed = pc.PluginCrawler(c.cfg, c.state, b, c.safety, now=self.fx.clock.now, sleep=self.fx.clock.sleep)
        resumed.export = Mock(return_value=([{}] * 8, {'plugin_count': 8}))
        resumed.materialize = Mock()
        resumed.run_task(task, prepared=True)
        self.assertEqual(b.actions, ['load'])

    def test_download_outage_and_restart_reuse_single_export(self):
        for exhaust in (False, True):
            with self.subTest(exhaust=exhaust):
                # Independent task/ledger per scenario.
                self.setUp()
                c, b, task = self.crawler()
                path = self.fx.root / 'Products(4)-US.xlsx'
                pc.native_file(path, 4)
                os.utime(path, (self.fx.clock.now() + 2000,) * 2)
                complete = dict(filename=str(path), id=123, downloaded=True, state='complete',
                                url='blob:https://www.amazon.com/export')
                b.wait_download = Mock(side_effect=BridgeTransientError('client_timeout') if exhaust else
                                       [BridgeTransientError('client_timeout')] * 6 + [complete])
                if exhaust:
                    with self.assertRaises(BridgeReadRecoveryExhausted): c.export(task, b.panel())
                    self.assertTrue(c._read_export_state()['pending'])
                    b.wait_download = Mock(return_value=complete)
                else:
                    rows, report = c.export(task, b.panel())
                    self.assertEqual(len(rows), 4)
                    b.wait_download = Mock(side_effect=AssertionError('must reuse staged download'))
                resumed = pc.PluginCrawler(c.cfg, c.state, b, c.safety, now=self.fx.clock.now, sleep=self.fx.clock.sleep)
                rows, report = resumed.export(task, b.panel())
                self.assertEqual(len(rows), 4)
                self.assertEqual(b.actions.count('export'), 1)
                self.assertEqual(c.safety.actions, ['plugin:export'])
                c.state.commit(task, rows, report, None, 'source_exhausted')
                c.acknowledge_export(task, report)
                self.assertNotIn('pending', c._read_export_state())

    def test_captcha_after_read_recovery_blocks_next_action(self):
        c, b, _ = self.crawler()
        with patch.object(b, 'panel', side_effect=[BridgeTransientError('client_timeout'), {'captcha': True}]):
            with self.assertRaisesRegex(RuntimeError, 'risk'): c.remote('load')
        self.assertEqual(b.actions, [])
        self.assertEqual(c.safety.actions, [])

    def test_stability_restarts_after_disconnect(self):
        c, b, _ = self.crawler()
        original, failed = b.panel, [False]
        start = self.fx.clock.now()
        def panel(action='snapshot', **kwargs):
            if self.fx.clock.now() >= start + 8 and not failed[0]:
                failed[0] = True
                raise BridgeTransientError('client_timeout')
            return original(action, **kwargs)
        b.panel = panel
        c.stable()
        self.assertEqual(self.fx.clock.now() - start, 20)  # 8 observed + 2 outage + 10 stable

    def test_timed_out_write_is_not_replayed(self):
        for action in ('load', 'export'):
            c, b, task = self.crawler()
            original = b.panel
            def panel(kind='snapshot', **kwargs):
                if kind == action:
                    b.actions.append(kind)
                    raise BridgeTransientError('client_timeout')
                return original(kind, **kwargs)
            b.panel = panel
            with self.subTest(action=action), self.assertRaises(BridgeTransientError):
                if action == 'load': c.remote('load')
                else: c.export(task, original())
            self.assertEqual(b.actions.count(action), 1)


class ImageRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fx = ib.BackgroundTests()
        self.fx.setUp()
        self.addCleanup(self.fx.tearDown)

    def test_long_navigation_read_outage_does_not_navigate_twice(self):
        destination = dict(ib.snapshot(), url='https://www.amazon.com/dp/B000000002', asin='B000000002')
        page, bridge, state, clock = self.fx.page([ib.snapshot(), destination])
        page.attach()
        original, failures = bridge.dom, [0]
        def dom(script, args):
            if args['action'] == 'snapshot' and 'navigate' in bridge.actions and failures[0] < 6:
                failures[0] += 1
                raise BridgeTransientError('cdp_timeout')
            return original(script, args)
        bridge.dom = dom
        result = page.navigate(destination['url'])
        self.assertEqual(result['asin'], 'B000000002')
        self.assertEqual(bridge.actions.count('navigate'), 1)
        self.assertNotIn('pending_navigation', state.data)
        self.assertGreaterEqual(clock.t, 514)

    def test_target_listing_timeout_recovers_without_rebinding(self):
        page, bridge, state, clock = self.fx.page([ib.snapshot()])
        page.attach()
        writes = list(bridge.actions)
        failures = [0]
        def validate():
            if failures[0] < 6:
                failures[0] += 1
                raise BridgeTransientError('client_timeout')
        with patch.object(bridge, 'validate_target', side_effect=validate), \
                patch.object(bridge, 'bind') as bind:
            page.stable('product')
        bind.assert_not_called()
        self.assertEqual(bridge.actions.count('mark'), writes.count('mark'))
        self.assertNotIn('navigate', bridge.actions)
        self.assertGreaterEqual(clock.t, 518)
        self.assertNotIn(ReadRecovery.KEY, state.data)

    def test_image_stability_restarts_after_read_gap(self):
        page, bridge, _, clock = self.fx.page([ib.snapshot()])
        page.attach()
        original, failed = bridge.dom, [False]
        def dom(script, args):
            if clock.t >= 2 and not failed[0]:
                failed[0] = True
                raise BridgeTransientError('cdp_timeout')
            return original(script, args)
        bridge.dom = dom
        page.stable('product')
        self.assertEqual(clock.t, 8)  # 2 observed + 2 outage + 4 continuously stable


if __name__ == '__main__':
    unittest.main()
