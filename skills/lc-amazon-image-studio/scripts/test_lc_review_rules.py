import ast
import unittest
from unittest.mock import patch

import lc_review_rules as rules
from lc_assets import file_hash


class ReviewRuleTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {"review_rule_profile": "scoped_v1", "review_dependency_version": 2,
                         "style_contract": {"version": 3}}
        self.job = {"kind": "main", "text_mode": "none"}

    def changed_hashes(self, name, before, after):
        reader = rules._read_source
        source = reader(name)
        self.assertIn(before, source)
        with patch.object(rules, "_read_source", side_effect=lambda filename: source.replace(before, after, 1) if filename == name else reader(filename)):
            return rules.rule_hashes("qa", self.manifest, self.job)

    def test_legacy_exact_field_names_and_full_byte_hashes(self):
        manifest = {"review_dependency_version": 2, "style_contract": {"version": 3}}
        qa = rules.rule_hashes("qa", manifest, self.job)
        self.assertEqual(set(qa), {"rule_hashes", "dependency_rule_hashes", "contract_rule_hashes"})
        self.assertEqual(qa["rule_hashes"], {name: file_hash(rules.SCRIPT_DIR / name) for name in ("lc_image_pipeline.py", "lc_quality.py", "lc_assets.py")})
        self.assertEqual(rules.rule_hashes("qa", {**manifest, "review_rule_profile": "legacy"}, self.job), qa)
        review = rules.rule_hashes("review", manifest, self.job)
        self.assertEqual(set(review), {"rules", "dependency_rules"})
        self.assertEqual(set(rules.rule_hashes("product", manifest, self.job)), {"rules"})

    def test_real_qa_threshold_and_new_helper_changes_invalidate(self):
        baseline = rules.rule_hashes("qa", self.manifest, self.job)
        self.assertNotEqual(baseline, self.changed_hashes("lc_image_pipeline.py", "white >= 254.5", "white >= 254.6"))
        reader = rules._read_source
        with patch.object(rules, "_read_source", side_effect=lambda name: reader(name) + "\ndef future_visual_helper():\n    return 7\n" if name == "lc_image_pipeline.py" else reader(name)):
            self.assertNotEqual(baseline, rules.rule_hashes("qa", self.manifest, self.job))

    def test_logging_and_cleanup_workers_do_not_invalidate_scoped_rules(self):
        baseline = rules.rule_hashes("qa", self.manifest, self.job)
        reader = rules._read_source
        originals = {name: reader(name) for name in ("lc_image_pipeline.py", "lc_delivery.py")}
        modified = {}
        for name, target in (("lc_image_pipeline.py", "record_timing"), ("lc_delivery.py", "compact_project")):
            text = originals[name]
            node = next(value for value in ast.parse(text).body if isinstance(value, ast.FunctionDef) and value.name == target)
            lines = text.splitlines(keepends=True)
            lines[node.lineno - 1:node.end_lineno] = [f"def {target}(*args, **kwargs):\n    raise RuntimeError('changed infrastructure only')\n"]
            modified[name] = "".join(lines)
        with patch.object(rules, "_read_source", side_effect=lambda name: modified.get(name, reader(name))):
            self.assertEqual(baseline, rules.rule_hashes("qa", self.manifest, self.job))

    def test_visual_module_and_review_validator_changes_invalidate(self):
        baseline = rules.rule_hashes("qa", self.manifest, self.job)
        self.assertNotEqual(baseline, self.changed_hashes("lc_assets.py", 'POLICY_VERSION = ', 'VISUAL_CHANGE = True\nPOLICY_VERSION = '))
        self.assertNotEqual(baseline, self.changed_hashes("lc_workflow.py", 'Explicit verdict and notes required:', 'Actual verdict and notes required:'))

    def test_job_profile_can_keep_legacy_and_invalid_profile_is_rejected(self):
        self.assertNotIn("review_rule_profile", rules.rule_hashes("qa", self.manifest, {**self.job, "review_rule_profile": "legacy"}))
        with self.assertRaises(ValueError):
            rules.rule_hashes("qa", {"review_rule_profile": "unknown"}, self.job)


if __name__ == "__main__":
    unittest.main()
