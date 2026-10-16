"""The receipt-parsing memo is keyed by exact bytes: it speeds the progress view up and can never go stale."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import source_result_processing as srp


def epo_search(*numbers):
    docs = ''.join('<ops:publication-reference><document-id document-id-type="docdb"><country>EP</country>'
                   '<doc-number>%s</doc-number><kind>A1</kind></document-id></ops:publication-reference>' % n
                   for n in numbers)
    return ('<?xml version="1.0"?><ops:world-patent-data xmlns:ops="http://ops.epo.org">'
            '<ops:biblio-search total-result-count="%d">%s</ops:biblio-search></ops:world-patent-data>'
            % (len(numbers), docs)).encode()


class ReceiptParseMemoTests(unittest.TestCase):
    def setUp(self):
        srp._PURE_MEMO.clear()

    def test_same_bytes_parse_once_and_a_caller_edit_never_leaks_into_the_next_answer(self):
        body = epo_search('1', '2', '3')
        calls = []
        real = srp._raw_rows_uncached
        def counted(*args):
            calls.append(1)
            return real(*args)
        with patch.object(srp, '_raw_rows_uncached', counted):
            first = srp._raw_rows(body, 'xml', 'epo_ops')
            first[0]['raw_sha256'] = 'tampered by a caller'
            first.append({'position': 99})
            second = srp._raw_rows(body, 'xml', 'epo_ops')
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(second), 3)
        self.assertNotEqual(second[0]['raw_sha256'], 'tampered by a caller')

    def test_changed_bytes_never_reuse_an_answer(self):
        before = srp._raw_rows(epo_search('1', '2'), 'xml', 'epo_ops')
        after = srp._raw_rows(epo_search('1', '2', '3'), 'xml', 'epo_ops')
        self.assertEqual((len(before), len(after)), (2, 3))

    def test_provider_and_suffix_are_part_of_the_key(self):
        body = json.dumps({'organic': [{'link': 'https://example.org/a'}]}).encode()
        as_serper = srp._raw_rows(body, 'json', 'serper_web')
        as_other = srp._raw_rows(body, 'xml', 'epo_ops')
        self.assertTrue(as_serper)
        self.assertIsNone(as_other)

    def test_task_field_follows_the_file_content(self):
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent)
            (root / 'task.json').write_text(json.dumps({'retrieval_workflow_revision': 'api-first-v3'}))
            self.assertEqual(srp._task_field(root, 'retrieval_workflow_revision'), 'api-first-v3')
            (root / 'task.json').write_text(json.dumps({'retrieval_workflow_revision': 'api-first-v2'}))
            self.assertEqual(srp._task_field(root, 'retrieval_workflow_revision'), 'api-first-v2')
            (root / 'task.json').write_text(json.dumps({}))
            self.assertIsNone(srp._task_field(root, 'retrieval_workflow_revision'))

    def test_memo_is_bounded(self):
        for index in range(srp._PURE_MEMO_LIMIT + 40):
            srp._raw_rows(epo_search(str(index)), 'xml', 'epo_ops')
        self.assertLessEqual(len(srp._PURE_MEMO), srp._PURE_MEMO_LIMIT)


if __name__ == '__main__':
    unittest.main()
