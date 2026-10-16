"""r5d7: US design drawings from the official USPTO grant PDF when Google Patents has none (B0GLNPC6K8 real run).

14 of 16 design candidates were granted in 2026. Google Patents had no page for some (HTTP 404) and refuses the
drawing files of the others (HTTP 403 for everyone), so the program selected all of them unseen and the Agent read
the official PDFs by hand. The PDF is one scanned sheet per page; pypdf and Pillow take each page out as a PNG.
"""
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common import atomic_write_json, load_json, sha256_json
import core_dossier
import image_convert
import pipeline_robust


def scanned_pdf(pages=3, size=(2560, 3300)):
    """A PDF like the USPTO grant file: each page one full-page bilevel image."""
    from PIL import Image, ImageDraw
    sheets = []
    for number in range(pages):
        sheet = Image.new('1', size, 1)
        ImageDraw.Draw(sheet).rectangle([200 + number * 40, 400, 1200, 2000], outline=0, width=12)
        sheets.append(sheet)
    buffer = io.BytesIO()
    sheets[0].save(buffer, 'PDF', save_all=True, append_images=sheets[1:], resolution=300)
    return buffer.getvalue()


class PdfPageTests(unittest.TestCase):
    def test_each_page_becomes_one_bounded_grayscale_png(self):
        from PIL import Image
        pages = image_convert.pdf_page_pngs(scanned_pdf(3))
        self.assertEqual([number for number, _ in pages], [1, 2, 3])
        for _, data in pages:
            with Image.open(io.BytesIO(data)) as image:
                self.assertEqual((image.format, image.mode), ('PNG', 'L'))
                self.assertEqual(max(image.size), image_convert.PDF_PAGE_MAX_SIDE)
        self.assertEqual(len(image_convert.pdf_page_pngs(scanned_pdf(3), max_pages=2)), 2)
        # deterministic: the same PDF gives the same PNG bytes
        self.assertEqual(image_convert.pdf_page_pngs(scanned_pdf(1)), image_convert.pdf_page_pngs(scanned_pdf(1)))

    def test_unreadable_pdf_is_a_clear_error(self):
        with self.assertRaisesRegex(ValueError, 'PDF_PAGES_UNREADABLE'):
            image_convert.pdf_page_pngs(b'%PDF-1.4 not really')

    def test_official_address_of_a_design_number(self):
        self.assertEqual(pipeline_robust.uspto_pdf_url('USD1146173S1'),
                         'https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/D1146173')
        self.assertEqual(pipeline_robust.uspto_pdf_url('USD645643S'),
                         'https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/D645643')
        self.assertIsNone(pipeline_robust.uspto_pdf_url('US11401089B2'))
        self.assertIsNone(pipeline_robust.uspto_pdf_url(''))


class DesignPictureFallbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.candidates = [{'candidate_id': 'CAND-NEW', 'right_type': 'design', 'publication_number': 'USD1146173S',
                            'jurisdiction': 'US'},
                           {'candidate_id': 'CAND-OLD', 'right_type': 'design', 'publication_number': 'USD645643S',
                            'jurisdiction': 'US'}]
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
        self.pdf_calls = []

    def fetch_pdf(self, url):
        self.pdf_calls.append(url)
        if url.endswith('D645643'):
            raise ValueError('DOCUMENT_HTTP_404')
        return scanned_pdf(2), url

    def run_once(self, fetch_page):
        entries = [{'candidate_id': row['candidate_id']} for row in self.candidates]
        return pipeline_robust.retain_design_pictures(self.root, entries, fetch_page=fetch_page,
                                                      fetch_image=lambda url: self.fail('no Google image expected'),
                                                      fetch_pdf=self.fetch_pdf)

    def test_google_404_then_official_pdf_pages_become_the_drawings(self):
        def no_page(url):
            raise ValueError('DOCUMENT_HTTP_404')
        summary = self.run_once(no_page)
        retained = {row['candidate_id']: row for row in summary['retained']}
        self.assertEqual((retained['CAND-NEW']['source'], retained['CAND-NEW']['drawings']), ('uspto_pdf', 2))
        evidence = load_json(self.root / 'evidence.json')
        self.assertTrue(pipeline_robust.has_picture(evidence, 'CAND-NEW'))
        page = self.registered[0]
        self.assertEqual((page['kind'], page['visual_role'], page['figure_label'], page['candidate_id']),
                         ('patent_drawing_image', 'patent_drawings', 'USPTO-P01', 'CAND-NEW'))
        self.assertEqual(page['source_url'], 'https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/D1146173')
        self.assertEqual(page['derived_from']['page_number'], 1)
        self.assertTrue((self.root / page['derived_from']['original_file']).is_file())
        self.assertTrue(Path(page['path']).is_file())
        # both sources refused the old number for good: it is listed once and never asked again
        failed = {row['candidate_id']: row for row in summary['failed']}
        self.assertIn('DOCUMENT_HTTP_404', failed['CAND-OLD']['uspto'])
        calls = len(self.pdf_calls)
        again = self.run_once(no_page)
        self.assertEqual((again['requested'], len(self.pdf_calls)), (0, calls))

    def test_google_page_whose_drawings_are_refused_falls_back_to_the_pdf(self):
        page = ('<html><dd itemprop="publicationNumber">%s</dd><span itemprop="title">Cat toy</span>'
                '<meta itemprop="full" content="https://patentimages.storage.googleapis.com/%s/x-D00000.png"></html>')

        def fetch_page(url):
            number = url.split('/patent/')[1].split('/')[0]
            return (page % (number, number)).encode(), url

        def refused(url):
            raise ValueError('MEDIA_HTTP_403')
        entries = [{'candidate_id': 'CAND-NEW'}]
        summary = pipeline_robust.retain_design_pictures(self.root, entries, fetch_page=fetch_page,
                                                         fetch_image=refused, fetch_pdf=self.fetch_pdf)
        self.assertEqual([row['source'] for row in summary['retained']], ['uspto_pdf'])
        self.assertTrue(pipeline_robust.has_picture(load_json(self.root / 'evidence.json'), 'CAND-NEW'))

    def test_a_transient_pdf_failure_is_retried_next_time(self):
        def no_page(url):
            raise ValueError('DOCUMENT_HTTP_404')
        flaky = iter([OSError('timed out')])

        def fetch_pdf(url):
            error = next(flaky, None)
            if error:
                raise error
            return scanned_pdf(1), url
        entries = [{'candidate_id': 'CAND-NEW'}]
        first = pipeline_robust.retain_design_pictures(self.root, entries, fetch_page=no_page, fetch_pdf=fetch_pdf)
        self.assertEqual(first['retained'], [])
        second = pipeline_robust.retain_design_pictures(self.root, entries, fetch_page=no_page, fetch_pdf=fetch_pdf)
        self.assertEqual([row['source'] for row in second['retained']], ['uspto_pdf'])


class RefusedMediaTests(unittest.TestCase):
    setUp = DesignPictureFallbackTests.setUp     # the same task folder, without running those tests again

    def test_an_image_refused_for_good_is_not_asked_again(self):
        from PIL import Image
        buffer = io.BytesIO()
        Image.new('L', (40, 30), 255).save(buffer, 'PNG')
        calls = []

        def fetch_image(url):
            calls.append(url)
            if url.endswith('D00000.png'):
                raise ValueError('MEDIA_HTTP_403')
            if url.endswith('D00001.png'):
                raise ValueError('MEDIA_PUBLIC_ADDRESS_REQUIRED:benchmarking_198.18.0.0/15')
            return buffer.getvalue(), '.png', url
        detail = {'evidence_id': 'API-E', 'payload': {'publication_number': 'US12507671B1', 'images': [
            'https://patentimages.storage.googleapis.com/US12507671B1/US12507671-20251230-D00000.png',
            'https://patentimages.storage.googleapis.com/US12507671B1/US12507671-20251230-D00001.png',
            'https://patentimages.storage.googleapis.com/aa/US12507671-20251230-D00002.png']}}
        candidate = {'candidate_id': 'CAND-NEW', 'right_type': 'patent', 'jurisdiction': 'US'}
        first = core_dossier.retain_files(self.root, candidate, detail, fetch_image=fetch_image)
        self.assertEqual(len(first['drawings']), 1)
        self.assertEqual(len(calls), 3)
        second = core_dossier.retain_files(self.root, candidate, detail, fetch_image=fetch_image)
        # the 403 is remembered; the proxy refusal (a local cause) is tried again; the retained one is reused
        self.assertEqual([url.rsplit('-', 1)[1] for url in calls[3:]], ['D00001.png'])
        refused = [row for row in second['failures'] if row.get('earlier_attempt')]
        self.assertEqual([row['reason'] for row in refused], ['ValueError:MEDIA_HTTP_403'])


if __name__ == '__main__':
    unittest.main()
