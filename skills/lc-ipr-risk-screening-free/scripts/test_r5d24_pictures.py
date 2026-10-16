"""r5d24: the design screen's pictures and the final review's image bundle (B0GLNPC6K8 real run, r5d23).

103 US designs waited for the picture screen. The program fetched and registered every drawing of every design (958
images, 17 minutes; 65 Google pages first, though Google refuses the drawings of every grant since 2025-07) before a
52-second screen that looks at two pictures per design. The final review then put all 958 images into one integrated
bundle, which is over its 64 MB limit, and failed instead of taking the module route.
"""
import datetime
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common import atomic_write_json, load_json, sha256_json
import core_dossier
import image_convert
import pipeline_robust
from test_r5d7_design_pdf import scanned_pdf

TODAY = datetime.date(2026, 10, 15)
PAGE = ('<html><dd itemprop="publicationNumber">%s</dd><span itemprop="title">Cat toy</span>%s</html>')
FIGURE = '<meta itemprop="full" content="https://patentimages.storage.googleapis.com/%s/x-D%05d.png">'


def google_page(url):
    number = url.split('/patent/')[1].split('/')[0]
    return (PAGE % (number, ''.join(FIGURE % (number, index) for index in range(5)))).encode(), url


class ScreenPictureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.candidates = [
            {'candidate_id': 'CAND-NEW', 'right_type': 'design', 'publication_number': 'USD1146173S1',
             'jurisdiction': 'US', 'publication_date': '2026-06-02'},
            {'candidate_id': 'CAND-OLD', 'right_type': 'design', 'publication_number': 'USD1012345S1',
             'jurisdiction': 'US', 'publication_date': '2024-11-05'}]
        atomic_write_json(self.root / 'normalized-candidates.json', {'patents': self.candidates})
        atomic_write_json(self.root / 'evidence.json', {'collections': {}, 'source_runs': []})
        self.registered = []

        def register(task_dir, payload):
            evidence = load_json(Path(task_dir) / 'evidence.json')
            evidence['collections'].setdefault('sources', []).append(
                {'evidence_id': 'EV-' + sha256_json(payload)[:12], 'kind': payload['kind'], 'payload': payload})
            atomic_write_json(Path(task_dir) / 'evidence.json', evidence)
            self.registered.append(payload)
        patcher = mock.patch.object(core_dossier, '_register', side_effect=register)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.pages, self.images, self.pdfs = [], [], []

    def fetch_page(self, url):
        self.pages.append(url)
        return google_page(url)

    def fetch_image(self, url):
        from io import BytesIO
        from PIL import Image
        self.images.append(url)
        buffer = BytesIO()
        Image.new('L', (40, 30 + len(self.images)), 255).save(buffer, 'PNG')
        return buffer.getvalue(), '.png', url

    def fetch_pdf(self, url):
        self.pdfs.append(url)
        return scanned_pdf(5), url

    def run_screen(self, ids, **kwargs):
        options = {'fetch_page': self.fetch_page, 'fetch_image': self.fetch_image, 'fetch_pdf': self.fetch_pdf,
                   'drawings': 2, 'today': TODAY, **kwargs}
        return pipeline_robust.retain_design_pictures(self.root, [{'candidate_id': cid} for cid in ids], **options)

    def drawings_of(self, cid):
        return [row for row in self.registered if row['candidate_id'] == cid and row['kind'] == 'patent_drawing_image']

    def test_a_recent_grant_goes_straight_to_two_uspto_pages(self):
        summary = self.run_screen(['CAND-NEW'])
        self.assertEqual(self.pages, [])                       # no Google page for a 2026 grant
        self.assertEqual([(row['source'], row['drawings']) for row in summary['retained']], [('uspto_pdf', 2)])
        self.assertEqual([row['figure_label'] for row in self.drawings_of('CAND-NEW')], ['USPTO-P01', 'USPTO-P02'])

    def test_an_older_design_takes_its_first_two_google_drawings(self):
        summary = self.run_screen(['CAND-OLD'])
        self.assertEqual(self.pdfs, [])
        self.assertEqual([url.rsplit('-', 1)[1] for url in self.images], ['D00000.png', 'D00001.png'])
        self.assertEqual([(row['source'], row['drawings']) for row in summary['retained']], [('google_patents', 2)])

    def test_a_recent_grant_whose_pdf_fails_tries_its_google_page(self):
        def no_pdf(url):
            self.pdfs.append(url)
            raise ValueError('DOCUMENT_HTTP_404')
        summary = self.run_screen(['CAND-NEW', 'CAND-OLD'], fetch_pdf=no_pdf)
        retained = {row['candidate_id']: row['source'] for row in summary['retained']}
        self.assertEqual(retained, {'CAND-NEW': 'google_patents', 'CAND-OLD': 'google_patents'})
        self.assertEqual(summary['failed'], [])
        self.assertEqual(len(self.drawings_of('CAND-NEW')), 2)

    def test_both_routes_failing_is_listed_once(self):
        def no_pdf(url):
            raise ValueError('DOCUMENT_HTTP_404')

        def no_page(url):
            raise ValueError('DOCUMENT_HTTP_404')
        summary = self.run_screen(['CAND-NEW'], fetch_pdf=no_pdf, fetch_page=no_page)
        self.assertEqual([(row['candidate_id'], 'DOCUMENT_HTTP_404' in row['uspto'], 'DOCUMENT_HTTP_404' in row['reason'])
                          for row in summary['failed']], [('CAND-NEW', True, True)])
        self.assertEqual(summary['retained'], [])

    def test_without_the_screen_limit_the_earlier_route_is_unchanged(self):
        def refused(url):
            raise ValueError('MEDIA_HTTP_403')
        summary = pipeline_robust.retain_design_pictures(
            self.root, [{'candidate_id': 'CAND-NEW'}], fetch_page=self.fetch_page, fetch_image=refused,
            fetch_pdf=self.fetch_pdf)
        self.assertEqual(len(self.pages), 1)                   # Google first, as before
        self.assertEqual([(row['source'], row['drawings']) for row in summary['retained']], [('uspto_pdf', 5)])

    def test_the_deep_check_completes_the_retained_pdf_without_a_new_request(self):
        self.run_screen(['CAND-NEW'])
        calls = len(self.pdfs)
        self.assertEqual(pipeline_robust.complete_uspto_pages(self.root, 'CAND-NEW'), 3)
        self.assertEqual([row['figure_label'] for row in self.drawings_of('CAND-NEW')],
                         ['USPTO-P01', 'USPTO-P02', 'USPTO-P03', 'USPTO-P04', 'USPTO-P05'])
        self.assertEqual(len(self.pdfs), calls)
        self.assertEqual(pipeline_robust.complete_uspto_pages(self.root, 'CAND-NEW'), 0)
        self.assertEqual(core_dossier.uspto_grant(load_json(self.root / 'evidence.json'), 'CAND-NEW')['pages'],
                         [1, 2, 3, 4, 5])

    def test_recent_means_granted_within_about_sixteen_months(self):
        self.assertTrue(pipeline_robust.recent_design({'publication_date': '2025-07-15'}, TODAY))
        self.assertFalse(pipeline_robust.recent_design({'publication_date': '2025-05-20'}, TODAY))
        self.assertFalse(pipeline_robust.recent_design({}, TODAY))

    def test_page_images_stop_after_the_requested_count(self):
        self.assertEqual([number for number, _ in image_convert.pdf_page_pngs(scanned_pdf(4), max_images=2)], [1, 2])


class IntegratedBundleTests(unittest.TestCase):
    def prepare(self, error):
        import adaptive_review
        import module_review
        frozen = {'task': {'final_review_execution_revision': adaptive_review.REVISION}}
        with mock.patch.object(adaptive_review, 'policy', return_value={'review_units': 10}), \
                mock.patch.object(adaptive_review, 'required_review_unit_count', return_value=2), \
                mock.patch.object(module_review, 'attach_originals', side_effect=ValueError(error)):
            return adaptive_review.prepare(frozen, '/nonexistent', [None, None])

    def test_an_oversized_image_bundle_takes_the_module_route(self):
        self.assertIsNone(self.prepare('FINAL_REVIEW_ORIGINAL_IMAGE_BUNDLE_TOO_LARGE'))

    def test_a_changed_original_still_stops_the_review(self):
        with self.assertRaisesRegex(ValueError, 'RETAINED_PATH_HASH_MISMATCH'):
            self.prepare('RETAINED_PATH_HASH_MISMATCH')


class ResumeAfterPreparationFailureTests(unittest.TestCase):
    """The failed review left final-review/ with only frozen-input.json; --resume ran the preflight with
    --resume-existing, which found no retained runtime (FINAL_REVIEW_RETAINED_RUNTIME_UNCONFIRMED) and stopped."""

    def preflight_resume_flag(self, files):
        import sys
        import report_review_host
        import review_preflight
        seen = {}

        def preflight(task_dir, output_dir, *, resume_existing=False, **kwargs):
            seen['resume_existing'] = resume_existing
            return {'ready': True}
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'final-review'
            output.mkdir()
            for name in files:
                (output / name).write_text('{}', encoding='utf-8')
            argv = ['report_review_host.py', '--task-dir', temp, '--output-dir', str(output), '--preflight',
                    '--resume-existing']
            with mock.patch.object(sys, 'argv', argv), \
                    mock.patch.object(review_preflight, 'preflight', side_effect=preflight), \
                    mock.patch.object(review_preflight, 'render', return_value='{}'), \
                    mock.patch('builtins.print'):
                with self.assertRaises(SystemExit) as stop:
                    report_review_host.main()
        self.assertEqual(stop.exception.code, 0)
        return seen['resume_existing']

    def test_a_review_that_never_started_is_checked_as_a_fresh_one(self):
        self.assertFalse(self.preflight_resume_flag(['frozen-input.json']))

    def test_a_review_with_model_output_is_still_checked_as_a_resume(self):
        self.assertTrue(self.preflight_resume_flag(['frozen-input.json', 'review.json']))


if __name__ == '__main__':
    unittest.main()
