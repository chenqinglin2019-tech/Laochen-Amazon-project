"""Actual PPS literal rewrite regression; old plan compilation stays frozen."""
import unittest
from record_browser_execution import compile_ppubs_query


class PpubsQuotedRecordTests(unittest.TestCase):
    def test_explicit_new_compiler_uses_exact_literal_and_legacy_stays_frozen(self):
        for value, digits in [('US20260233895A1', '20260233895'), ('US11401089B2', '11401089'), ('USD1111090S', 'D1111090')]:
            row = {'q': value, 'strategy': 'record_number'}
            self.assertEqual(compile_ppubs_query(row, 'record_number')['rendered_query'], digits+'.PN.')
            self.assertEqual(compile_ppubs_query({**row, 'query_compiler_revision':'ppubs-quoted-record-v1'}, 'record_number')['rendered_query'], '"'+digits+'".PN.')
        with self.assertRaises(ValueError):
            compile_ppubs_query({'q':'US11401089B2 OR 1', 'strategy':'record_number', 'query_compiler_revision':'ppubs-quoted-record-v1'}, 'record_number')


if __name__ == '__main__':
    unittest.main()
