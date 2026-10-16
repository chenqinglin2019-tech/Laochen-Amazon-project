"""The shipped institution table: every entry cites an official page; task creation copies the task's countries into
evidence; module packets route the statements by right; the finalizer binds to them."""
import json
import tempfile
import unittest
from pathlib import Path

from common import load_json
import jurisdiction_rights as jr
import test_product_entry as fixture_module


class TableTests(unittest.TestCase):
    def test_table_is_valid_and_covers_every_target_country_for_both_rights(self):
        table = jr.load_table()
        pairs = {(e["jurisdiction"], e["right_type"]) for e in table["entries"]}
        for country in ("US", "GB", "FR", "DE", "IT", "ES", "JP", "EU"):
            for right in ("utility_model", "unregistered_design"):
                self.assertIn((country, right), pairs)
        for entry in table["entries"]:
            self.assertTrue(entry["source_url"].startswith("https://"))
            self.assertIn(entry["verification"], table["verification_levels"])
            self.assertRegex(entry["retrieved"], r"^\d{4}-\d{2}-\d{2}$")
        absent = {(e["jurisdiction"], e["right_type"]) for e in table["entries"] if e["applicable"] is False}
        self.assertEqual(absent, {("US", "utility_model"), ("US", "unregistered_design"), ("EU", "utility_model"),
                                  ("GB", "utility_model")})

    def test_entries_are_statements_not_originals(self):
        rows = jr.institution_entries(["US", "DE"], "2026-10-11T00:00:00+00:00")
        self.assertEqual([r["evidence_id"] for r in rows], ["EV-INST-DE-UNREGISTERED_DESIGN", "EV-INST-DE-UTILITY_MODEL",
                                                            "EV-INST-US-UNREGISTERED_DESIGN", "EV-INST-US-UTILITY_MODEL"])
        for row in rows:
            for key in ("path", "sha256", "source_url"):
                self.assertNotIn(key, row)              # nothing to attach, nothing "unsent"
            self.assertEqual(row["kind"], "institution_reference")
            self.assertTrue(row["payload"]["source_url"].startswith("https://"))
            self.assertEqual(len(row["reference_sha256"]), 64)
        self.assertEqual(jr.not_applicable_scopes(rows), {("US", "utility_model"), ("US", "unregistered_design")})

    def test_invalid_tables_are_refused(self):
        with tempfile.TemporaryDirectory() as parent:
            path = Path(parent) / "t.json"
            good = load_json(jr.TABLE)
            for bad in ({**good, "revision": "x"}, {**good, "entries": good["entries"] + [good["entries"][0]]},
                        {**good, "entries": [{**good["entries"][0], "source_url": "http://insecure"}]},
                        {**good, "entries": [{**good["entries"][0], "applicable": "no"}]}):
                path.write_text(json.dumps(bad), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "JURISDICTION_RIGHTS"):
                    jr.load_table(path)


class CreateTaskInjectionTests(fixture_module.ProductEntryTests):
    def test_new_task_carries_the_marker_and_its_countries_institution_statements(self):
        self.cli('create_task.py', '--product-input', self.input, '--jurisdictions', 'US', '--output-dir', self.run)
        task = load_json(self.run / 'task.json')
        self.assertEqual(task['best_estimate_revision'], 'best-estimate-risk-v2')
        self.assertEqual(task['assessment_revision'], 'known-findings-risk-v1')
        rows = load_json(self.run / 'evidence.json')['collections']['institution_references']
        self.assertEqual({r['evidence_id'] for r in rows}, {'EV-INST-US-UTILITY_MODEL', 'EV-INST-US-UNREGISTERED_DESIGN'})
        self.assertTrue(all(r['payload']['applicable'] is False for r in rows))

    def test_eu_country_task_includes_the_eu_layer(self):
        self.cli('create_task.py', '--product-input', self.input, '--jurisdictions', 'DE', '--output-dir', self.run)
        rows = load_json(self.run / 'evidence.json')['collections']['institution_references']
        self.assertEqual({r['jurisdiction'] for r in rows}, {'EU', 'DE'})


class ModulePacketRoutingTests(unittest.TestCase):
    def test_statements_reach_only_the_module_of_their_right_and_are_never_attached(self):
        from module_review import module_packet, attach_originals
        rows = jr.institution_entries(["US"], "2026-10-11T00:00:00+00:00")
        task = {'task_id': 'T', 'target_jurisdictions': ['US'], 'images': [],
                'assessment_scenarios': [{'scenario_id': 'product_entry', 'type': 'product_entry'}]}
        frozen = {'task': task, 'candidates': {}, 'evidence': {'collections': {'institution_references': rows}},
                  'evidence_digest': 'd' * 64, 'materiality_ledger': {}, 'search_plan': {}}
        by_group = {group: [r['evidence_id'] for r in module_packet(frozen, group)['evidence']['collections']
                            .get('institution_references', [])] for group in ('technical', 'appearance', 'expression')}
        self.assertEqual(by_group['technical'], ['EV-INST-US-UTILITY_MODEL'])
        self.assertEqual(by_group['appearance'], ['EV-INST-US-UNREGISTERED_DESIGN'])
        self.assertEqual(by_group['expression'], [])
        with tempfile.TemporaryDirectory() as parent:
            self.assertEqual(attach_originals(module_packet(frozen, 'technical'), parent), {})


# the inherited product-entry cases are run by their own module
for _name in [n for n in dir(fixture_module.ProductEntryTests) if n.startswith('test_') and n not in vars(CreateTaskInjectionTests)]:
    setattr(CreateTaskInjectionTests, _name, None)

if __name__ == '__main__':
    unittest.main()
