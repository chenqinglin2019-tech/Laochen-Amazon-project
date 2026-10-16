"""r5d13: older Google Patents pages are read, and a page without readable claims never leaves a scope unregistered.

B0GLNPC6K8 r5d12 task: the free task's ten SerpApi requests were spent, so US20040253908A1 (selected late) had only its
Google Patents page. That 2004 page numbers claims without zero padding (num="8") and lists the cancelled ones as a
range (num="1-7" "1-7. (Canceled)"); the parser read no claim, core_dossier recorded nothing for the scope
("public_page_claims_missing") and checkpoint 2 stopped on SPECIALTY_INTAKE_PENDING. On a copy of that run the page
now gives claims 8-10, the scope is registered and, after a stand-in comparison, readiness passes.
"""
import unittest

import core_focus


def page(*claims):
    body = ''.join('<div class="claim"><div num="%s" id="CLM-%s" class="claim"><div class="claim-text">%s</div></div></div>'
                   % (num, num, text) for num, text in claims)
    return '<section itemprop="claims" itemscope><h2>Claims</h2>%s</section>' % body


class PageClaimTests(unittest.TestCase):
    def test_unpadded_numbers_and_cancelled_ranges(self):
        text = page(('1-7', '<b>1</b>-<b>7</b>. (Canceled)'),
                    ('8', '<b>8</b>. An animal exerciser comprising a rod.'),
                    ('9', '<b>9</b>. The animal exerciser of claim 8, wherein the rod is wooden.'))
        self.assertEqual(core_focus.page_claims(text), [
            '8. An animal exerciser comprising a rod.', '9. The animal exerciser of claim 8, wherein the rod is wooden.'])

    def test_padded_numbers_unchanged_and_single_cancelled_claims_dropped(self):
        text = page(('00001', '1. A pet toy comprising a rod.'), ('00006', '6 . (canceled)'),
                    ('00010', '10. A pet toy comprising a line.'))
        self.assertEqual(core_focus.page_claims(text), ['1. A pet toy comprising a rod.', '10. A pet toy comprising a line.'])
        self.assertEqual(core_focus.page_claims('<html>no claims</html>'), [])


class MediaRowReadingTests(unittest.TestCase):
    """r5d14: a design's 11th drawing exists only as the SerpApi record's own media row (``url`` + ``source_field``);
    the inventory lists it as a public original, so the reader must read it (B0GLNPC6K8: USD983466S1 has 21)."""

    def test_an_api_media_row_is_read_like_a_registered_drawing(self):
        import tempfile
        from pathlib import Path
        import module_review
        from common import sha256_bytes
        from test_report_estimate import PNG
        root = Path(tempfile.mkdtemp())
        self.addCleanup(__import__('shutil').rmtree, root, True)
        image = root / 'raw' / 'serpapi_google_patents' / 'media' / 'd10.png'
        image.parent.mkdir(parents=True)
        image.write_bytes(PNG)
        row = {'path': str(image), 'sha256': sha256_bytes(PNG), 'bytes': len(PNG), 'source_field': 'images[10]',
               'url': 'https://patentimages.storage.googleapis.com/x/USD0983466-20230411-D00010.png'}
        packet = {'task': {}, 'evidence': {'collections': {'patents': [
            {'evidence_id': 'EV-REC', 'payload': {'media': [row]}}]}}}
        module_review.attach_originals(packet, root)
        names = [m['name'] for m in packet['retained_originals']['materials']]
        self.assertEqual(names, ['d10.png'])
        # a media row without its source field is not a public original and stays unread
        packet = {'task': {}, 'evidence': {'collections': {'patents': [
            {'evidence_id': 'EV-REC', 'payload': {'media': [dict(row, source_field=None)]}}]}}}
        module_review.attach_originals(packet, root)
        self.assertEqual(packet['retained_originals']['materials'], [])


if __name__ == '__main__':
    unittest.main()
