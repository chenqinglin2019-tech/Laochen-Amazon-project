"""Media collection respects user control before dispatch and evidence registration."""
from contextlib import redirect_stdout
from io import StringIO
import unittest
from unittest.mock import patch

from common import atomic_write_json, load_json
from candidate_media import collect
from continuation_stage_c import REVISION, record_event
import test_visual_triage_host


class CandidateMediaPauseTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_visual_triage_host.VisualHostTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        task = load_json(self.root / 'task.json')
        task['continuous_continuation_revision'] = REVISION
        atomic_write_json(self.root / 'task.json', task)
        evidence = load_json(self.root / 'evidence.json')
        evidence['task_id'] = task['task_id']
        atomic_write_json(self.root / 'evidence.json', evidence)

    def pause(self):
        with redirect_stdout(StringIO()):
            record_event(self.root, {'kind':'pause', 'actor':'user', 'intent':'pause',
                'reasoning':'Explicit user pause', 'scope':{'level':'task'}, 'reason':'Stop requested'})

    def test_direct_collection_already_paused_never_downloads_or_creates_media(self):
        self.pause()
        with patch('candidate_media.download') as download, self.assertRaisesRegex(ValueError, 'USER_ACTIVE_PAUSE'):
            collect(self.root, self.fixture.media.ids)
        download.assert_not_called()
        self.assertFalse((self.root / 'candidate-media.json').exists())
        self.assertFalse((self.root / 'raw/candidate-media').exists())

    def test_pause_during_download_does_not_write_or_cache_failure(self):
        def download(*args, **kwargs):
            self.pause()
            return self.fixture.download(*args, **kwargs)
        with patch('candidate_media.download', side_effect=download), self.assertRaisesRegex(ValueError, 'USER_ACTIVE_PAUSE'):
            collect(self.root, self.fixture.media.ids)
        self.assertFalse((self.root / 'candidate-media.json').exists())
        self.assertFalse((self.root / 'raw/candidate-media').exists())

    def test_pause_before_final_registration_preserves_existing_receipts(self):
        with patch('candidate_media.download', side_effect=self.fixture.download):
            collect(self.root, self.fixture.media.ids)
        before = {name:(self.root / name).read_bytes() for name in ('candidate-media.json', 'supplemental-evidence.json')}
        import candidate_media
        original = candidate_media._assert_media_active
        calls = []
        def check(root, candidates):
            calls.append(True)
            # Pause after the cached-fetch guard, before the final locked write.
            result = original(root, candidates)
            if len(calls) == 2:
                self.pause()
            return result
        with patch('candidate_media._assert_media_active', side_effect=check), \
             patch('candidate_media.download') as download, self.assertRaisesRegex(ValueError, 'USER_ACTIVE_PAUSE'):
            collect(self.root, self.fixture.media.ids)
        download.assert_not_called()
        for name, data in before.items():
            self.assertEqual((self.root / name).read_bytes(), data)

    def test_pause_between_visual_snapshot_and_media_entry_stops_host(self):
        from visual_triage_host import run
        from workflow_v24 import work_view_from_dir
        def paused_view(root):
            view = work_view_from_dir(root)
            self.pause()
            return view
        with patch('workflow_v24.work_view_from_dir', side_effect=paused_view), \
             patch('candidate_media.download') as download, \
             patch('report_review_host.run_native_logged') as model, self.assertRaisesRegex(ValueError, 'USER_ACTIVE_PAUSE'):
            run(self.root, binary=self.fixture.binary, isolation='macos-sandbox')
        download.assert_not_called(); model.assert_not_called()


if __name__ == '__main__':
    unittest.main()
