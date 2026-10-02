import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from macos_review_host import completed_review
from review_material_bundle import retained_bundle


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')


class MaterialBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = self.root / 'image.png'
        self.image.write_bytes(PNG)
        self.row = {'provider': 'public_source', 'source_url': 'https://example.invalid/image.png', 'path': str(self.image),
                    'sha256': hashlib.sha256(PNG).hexdigest()}
        self.frozen = {'items': {'J1': {'evidence_refs': ['E1']}},
                       'source_facts': {'E1': {'row': self.row}}}

    def test_exact_retained_bytes_and_source_identity_are_used(self):
        bundle, images = retained_bundle(self.frozen, self.root)
        self.assertEqual(images['M1.png'], PNG)
        self.assertEqual(bundle['materials'][0]['source_refs'], ['E1'])

    def test_changed_material_is_rejected_before_review(self):
        self.image.write_bytes(PNG + b'changed')
        with self.assertRaisesRegex(ValueError, 'HASH_CHANGED'):
            retained_bundle(self.frozen, self.root)

    def test_external_path_even_with_correct_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as other:
            image = Path(other) / 'image.png'
            image.write_bytes(PNG)
            self.row['path'] = str(image)
            with self.assertRaisesRegex(ValueError, 'OUTSIDE_TASK'):
                retained_bundle(self.frozen, self.root)

    def test_user_files_and_unused_evidence_are_not_automatically_exposed(self):
        self.row['provider'] = 'user_file'
        with self.assertRaisesRegex(ValueError, 'NO_FROZEN_PUBLIC_IMAGE'):
            retained_bundle(self.frozen, self.root)
        self.row['provider'] = 'public_source'
        self.frozen['items']['J1']['evidence_refs'] = []
        with self.assertRaisesRegex(ValueError, 'NO_FROZEN_PUBLIC_IMAGE'):
            retained_bundle(self.frozen, self.root)

    def test_public_provider_label_alone_does_not_expose_an_unattributed_file(self):
        self.row.pop('source_url')
        with self.assertRaisesRegex(ValueError, 'NO_FROZEN_PUBLIC_IMAGE'):
            retained_bundle(self.frozen, self.root)

    def test_duplicate_nested_artifact_is_attached_once(self):
        self.row['payload'] = dict(self.row)
        bundle, images = retained_bundle(self.frozen, self.root)
        self.assertEqual(len(images), 1)
        self.assertEqual(len(bundle['materials']), 1)

    def test_html_body_is_frozen_as_text_without_active_script(self):
        path = self.root / 'page.html'
        data = b'<style>hidden</style><p>Visible original fact</p><script>bad()</script>'
        path.write_bytes(data)
        self.frozen['items']['J1']['evidence_refs'].append('E2')
        self.frozen['source_facts']['E2'] = {'row': {'provider': 'public_source',
            'path': str(path), 'source_url': 'https://example.invalid/page.html', 'sha256': hashlib.sha256(data).hexdigest()}}
        bundle, _ = retained_bundle(self.frozen, self.root)
        self.assertEqual(bundle['materials'][1]['text'], 'Visible original fact')

    def test_image_extension_does_not_turn_arbitrary_bytes_into_an_image(self):
        self.image.write_bytes(b'not an image')
        self.row['sha256'] = hashlib.sha256(self.image.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'IMAGE_INVALID'):
            retained_bundle(self.frozen, self.root)

    def test_material_observation_coverage_is_required_in_real_trace(self):
        output = {'items': {}, 'coverage': {}, 'material_observations': {'M1': 'A visible red triangle'}}
        events = [{'type': 'thread.started', 'thread_id': 'session'},
                  {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(output)}},
                  {'type': 'turn.completed'}]
        self.assertEqual(completed_review(events, ['M1'])[0], 'session')
        with self.assertRaisesRegex(ValueError, 'READING_INCOMPLETE'):
            completed_review(events, ['M1', 'M2'])


if __name__ == '__main__':
    unittest.main()
