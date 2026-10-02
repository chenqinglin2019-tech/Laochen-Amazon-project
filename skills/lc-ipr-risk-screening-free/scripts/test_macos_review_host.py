import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from macos_review_host import child_environment, completed_review, sandbox_profile, signing_context, require_chatgpt_auth


class MacosReviewHostTests(unittest.TestCase):
    def events(self):
        return [{'type': 'thread.started', 'thread_id': 'actual-thread'},
                {'type': 'item.completed', 'item': {'type': 'agent_message',
                    'text': json.dumps({'items': {}, 'coverage': {}})}},
                {'type': 'turn.completed'}]

    def test_finished_tool_free_trace_returns_actual_thread(self):
        identity, result = completed_review(self.events())
        self.assertEqual(identity, 'actual-thread')
        self.assertEqual(set(result), {'items', 'coverage'})

    def test_tool_activity_cannot_be_signed_as_an_independent_review(self):
        for activity in ('command_execution', 'mcp_tool_call', 'web_search', 'file_change'):
            with self.subTest(activity=activity), self.assertRaisesRegex(ValueError, 'TOOL_ACTIVITY'):
                completed_review(self.events() + [{'type': 'item.started', 'item': {'type': activity}}])

    def test_failed_truncated_and_multiple_turns_are_rejected(self):
        for events in (self.events()[:-1], self.events() + [{'type': 'turn.failed'}],
                       self.events() + [self.events()[0]], self.events() + [self.events()[1]],
                       self.events() + [{'type': 'turn.completed'}],
                       self.events() + [{'type': 'tool.started'}]):
            with self.assertRaises(ValueError):
                completed_review(events)

    def test_reviewer_cannot_return_a_host_receipt(self):
        events = self.events()
        events[1]['item']['text'] = json.dumps({'items': {}, 'coverage': {}, 'isolation_receipt': {}})
        with self.assertRaisesRegex(ValueError, 'OUTPUT_FIELDS'):
            completed_review(events)

    def test_child_never_gets_host_signing_key_or_offline_bypass(self):
        with patch.dict(os.environ, {'LC_IPR_REVIEW_HOST_KEY': 'test-key',
                                     'OPENAI_API_KEY': 'offline-fake', 'LC_IPR_OFFLINE_TESTS': '1'}):
            environment = child_environment()
            for key in ('LC_IPR_REVIEW_HOST_KEY', 'OPENAI_API_KEY', 'LC_IPR_OFFLINE_TESTS', 'PWD'):
                self.assertNotIn(key, environment)

    def test_host_key_context_restores_environment_on_failure(self):
        with patch.dict(os.environ, {'LC_IPR_REVIEW_HOST_KEY': 'outer'}):
            with self.assertRaises(RuntimeError), signing_context('inner'):
                self.assertEqual(os.environ['LC_IPR_REVIEW_HOST_KEY'], 'inner')
                raise RuntimeError('failure')
            self.assertEqual(os.environ['LC_IPR_REVIEW_HOST_KEY'], 'outer')

    def test_metered_or_unknown_auth_does_not_start_a_review(self):
        for status in ('Logged in using API key', 'Not logged in', ''):
            with patch('macos_review_host.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', status)):
                with self.assertRaisesRegex(ValueError, 'CHATGPT_LOGIN_REQUIRED'):
                    require_chatgpt_auth('binary', 'profile', 'workspace')
        with patch('macos_review_host.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', 'Logged in using ChatGPT')):
            require_chatgpt_auth('binary', 'profile', 'workspace')

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS kernel boundary only')
    def test_real_kernel_denies_existing_peer_file_but_reads_input(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            peer = root / '中文 审阅目录'
            peer.mkdir()
            denied = peer / 'first-review.txt'
            denied.write_text('fixture only')
            allowed = root / 'input.json'
            allowed.write_text('{}')
            profile = root / 'sandbox.sb'
            profile.write_text(sandbox_profile(Path('/bin/cat'), [peer]))
            for file, expected in ((allowed, 0), (denied, 1)):
                result = subprocess.run(['/usr/bin/sandbox-exec', '-f', str(profile), '/bin/cat', str(file)],
                                        cwd=root, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, expected)
                if expected == 1:
                    self.assertEqual(result.stdout, b'')

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS kernel boundary only')
    def test_real_kernel_denies_peer_writes(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            peer = root / '中文 审阅目录'
            peer.mkdir()
            denied = peer / 'review.txt'
            denied.write_text('fixture only')
            before = denied.stat().st_mtime_ns
            profile = root / 'sandbox.sb'
            profile.write_text(sandbox_profile(Path('/usr/bin/touch'), [peer]))
            result = subprocess.run(['/usr/bin/sandbox-exec', '-f', str(profile),
                                     '/usr/bin/touch', str(denied)], cwd=root,
                                    capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(denied.stat().st_mtime_ns, before)


if __name__ == '__main__':
    unittest.main()
