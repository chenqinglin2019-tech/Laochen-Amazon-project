"""CUA provenance is opt-in; automatic execution proofs remain mandatory."""
import unittest
from common import capture_provenance

class CuaRecallProvenanceTests(unittest.TestCase):
    def capture(self):
        return {"browser":"codex_iab", "capture_transport":"cua", "mode":"basic_search",
                "cua_browser_id":"2", "cua_tab_id":"5"}
    def test_explicit_current_consumer_can_record_real_iab_identity(self):
        result=capture_provenance(self.capture(), {"schema_version":"2.4-free"}, allowed_transports={"cdp","cua"})
        self.assertEqual(result["browser"],"codex_iab")
        self.assertEqual(result["cua_tab_id"],"5")
    def test_other_consumers_and_legacy_tasks_remain_closed(self):
        for schema, transports in [("2.4-free",{"cdp"}),("2.3-free",{"cdp","cua"})]:
            with self.assertRaises(ValueError):
                capture_provenance(self.capture(), {"schema_version":schema}, allowed_transports=transports)
    def test_missing_tab_operator_assertion_and_session_fields_are_rejected(self):
        for update in [{"cua_tab_id":""},{"operator_confirmed":True},{"cookies":[]},{"mode":"verification"}]:
            with self.assertRaises(ValueError):
                capture_provenance({**self.capture(),**update},{"schema_version":"2.4-free"},allowed_transports={"cua"})

class PpubsQuerySpacingTests(unittest.TestCase):
    def test_parenthesis_spacing_is_equal_but_phrase_or_operator_changes_are_not(self):
        from record_browser_execution import ppubs_query_text_equal
        self.assertTrue(ppubs_query_text_equal('( ball OR sphere ) AND ( motorized )', '(ball OR sphere) AND (motorized)'))
        self.assertFalse(ppubs_query_text_equal('(ball OR sphere) OR (motorized)', '(ball OR sphere) AND (motorized)'))
        self.assertFalse(ppubs_query_text_equal('"self  propelled" AND ball', '"self propelled" AND ball'))
        self.assertFalse(ppubs_query_text_equal('sphere AND motorized', 'ball AND motorized'))

    def test_shared_history_query_equality_contract(self):
        import json
        from pathlib import Path
        from record_browser_execution import ppubs_query_text_equal
        cases = json.loads((Path(__file__).resolve().parents[1] / "fixtures/ppubs-query-equality.json").read_text())
        for actual, expected, equal in cases:
            with self.subTest(actual=actual, expected=expected):
                self.assertEqual(ppubs_query_text_equal(actual, expected), equal)
