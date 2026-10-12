import copy
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import voc_prd_pipeline as pipeline
import consumer_voice_evidence as evidence


class PrdTests(unittest.TestCase):
    def test_unified_registry_keeps_one_voice_need_count_and_preserves_judgments(self):
        voices = [{"voice_id": "v1", "needs": [{"need_id": "stable", "label": "稳定性", "stance": "support", "applicability": "current"}]},
                  {"voice_id": "v2", "needs": []}]
        reviews = [
            {"voice_id": "v1", "decision": "specific_need", "needs": [{"need_id": "stable", "label": "稳定性", "stance": "counter", "applicability": "current"}]},
            {"voice_id": "v2", "decision": "specific_need", "needs": [{"need_id": "new", "label": "可折叠托盘", "stance": "support", "applicability": "future"}]},
        ]
        registry = pipeline.unified_need_registry(voices, reviews, 2)
        stable = next(row for row in registry if row["need_id"] == "stable")
        self.assertEqual(1, stable["count"])
        self.assertEqual(["v1"], stable["mixed_refs"])
        self.assertTrue(stable["eligible"])
        new = next(row for row in registry if row["need_id"] == "new")
        self.assertFalse(new["eligible"])
        self.assertEqual("opportunity_review", new["origin"][0])

    def test_document_validator_respects_soft_v2_checks(self):
        import test_consumer_voice_local_reprocess as fixtures
        fixture = fixtures.LocalReprocessTestCase(); fixture.setUp()
        try:
            fixtures.cvlr.reprocess(fixture.db, fixture.output, selection_file=fixture.selection)
            coding, analysis = fixture._load_outputs()
            # Exercise the document consistency layer independently of the
            # later per-record evidence recalculation (covered by integration).
            coding["metadata"].pop("evidence_protocol", None)
            analysis["metadata"].pop("evidence_protocol", None)
            analysis["business_rules_version"] = "voc-prd-v2"
            analysis["evidence_readiness"]["checks"] = [{"passed":False,"blocking":False,"id":"volume"},{"passed":True,"blocking":True,"id":"quality"}]
            analysis["evidence_readiness"]["status"] = "sufficient"
            fixtures.cvlr.validate_v3_documents(coding, analysis)
            analysis.pop("business_rules_version")
            with self.assertRaises(fixtures.cvlr.LocalReprocessError):
                fixtures.cvlr.validate_v3_documents(coding, analysis)
        finally:
            fixture.tearDown()

    def test_input_coding_cache_stays_readonly(self):
        import test_consumer_voice_local_reprocess as fixtures
        fixture = fixtures.LocalReprocessTestCase(); fixture.setUp()
        try:
            cache = fixture.root / "historical-cache.json"
            original = b'{"schema_version":"1.0.0","entries":[]}\n'
            cache.write_bytes(original)
            fixtures.cvlr.reprocess(fixture.db, fixture.output, selection_file=fixture.selection, coding_cache=cache)
            self.assertEqual(original, cache.read_bytes())
            self.assertTrue((fixture.output / "coding_cache.json").is_file())
            with self.assertRaises(fixtures.cvlr.LocalReprocessError):
                fixtures.cvlr.reprocess(fixture.db, fixture.output, selection_file=fixture.selection, coding_cache=fixture.output / "coding_cache.json")
        finally:
            fixture.tearDown()

    def test_kano_exact_boundary_and_evidence_bound_reuse(self):
        voices = [{"voice_id": str(i), "excerpt": "original"} for i in range(100)]
        def need(count):
            return {"need_id": "n", "code": "n", "label": "需求", "count": count,
                    "all_refs": [str(i) for i in range(count)], "support_refs": ["0"], "counter_refs": []}
        below, queue = pipeline.holistic_kano([need(2)], voices, "tax")
        self.assertEqual("below_threshold", below[0]["status"])
        self.assertFalse(queue)
        rows, queue = pipeline.holistic_kano([need(3)], voices, "tax")
        self.assertEqual(1, len(queue))
        rows[0].update(status="classified", classification="M", rationale="明确缺失造成任务失败")
        reused, queue = pipeline.holistic_kano([need(3)], voices, "tax", rows)
        self.assertEqual("classified", reused[0]["status"])
        self.assertFalse(queue)
        voices[0]["excerpt"] = "changed"
        changed, queue = pipeline.holistic_kano([need(3)], voices, "tax", rows)
        self.assertEqual("pending", changed[0]["status"])
        self.assertEqual(1, len(queue))

    def test_opportunities_count_whole_set_without_label_merge(self):
        import consumer_voice_local_reprocess as local
        voices = self.voices(0, 200)
        for i, v in enumerate(voices):
            v.update(semantic_codes=["diy_modification_workaround"] if i == 0 else [], topic_codes=["n"],
                     needs=[{"need_id": "n", "code": "n", "label": "same", "stance": "support", "applicability": "current", "novel": i == 0}] if i < 5 else [])
        result = local._new_needs(voices, 200)
        self.assertEqual(5, result[0]["count"])
        self.assertEqual(.025, result[0]["share"])
        voices[0]["needs"][0].update(need_id="rare", code="rare")
        # Same display label does not borrow five mentions from another ID.
        result = local._new_needs(voices, 201)
        self.assertEqual([], result)

    def test_specific_opportunity_does_not_borrow_cooccurring_broad_need(self):
        import consumer_voice_local_reprocess as local
        voices = self.voices(0, 1000)
        for i, voice in enumerate(voices):
            voice.update(semantic_codes=["diy_modification_workaround"] if i == 0 else [], topic_codes=["broad"],
                         needs=[{"need_id":"broad", "code":"broad", "label":"稳定", "stance":"support", "applicability":"current", "novel":False}] if i < 100 else [])
        voices[0]["needs"].append({"need_id":"specific", "code":"specific", "label":"折叠托盘", "stance":"support", "applicability":"current", "novel":True})
        self.assertEqual([], local._new_needs(voices, 1000))
        for voice in voices[:100]:
            voice["needs"][0]["novel"] = True
        self.assertEqual([], local._new_needs(voices, 1000, {"topic_regex":{"broad":()}}))

    def test_single_segment_reprocess_integrates_rules_and_pending_kano(self):
        import test_consumer_voice_local_reprocess as fixtures
        fixture = fixtures.LocalReprocessTestCase(); fixture.setUp()
        try:
            selection = json.loads(fixture.selection.read_text())
            selection["workflow_mode"] = "single_segment"
            selection["selected_segments"] = selection["selected_segments"][:1]
            fixture.selection.write_text(json.dumps(selection))
            config = {"version":"1", "rules":[{"id":"explicit_purchase", "product_phrases":["car phone holder"],
                "phrases":["Where can I buy"], "semantic_codes":["purchase_selection_recommendation"]}]}
            rules_path = fixture.root / "rules.json"; rules_path.write_text(json.dumps(config))
            fixtures.cvlr.reprocess(fixture.db, fixture.output, selection_file=fixture.selection, rule_config=rules_path)
            coding, analysis = fixture._load_outputs()
            self.assertEqual(1, len(coding["voices"]))
            self.assertEqual("rule_classified", coding["voices"][0]["coding_method"])
            self.assertEqual("need_holistic_inference", analysis["methodology"]["kano_mode"])
            self.assertTrue((fixture.output / "review_batches.json").exists())
            self.assertEqual(11, coding["coding_review"]["unreviewed_records"])
            sample = json.loads((fixture.output / "quality_review_queue.json").read_text())
            receipt = fixture.root / "quality.json"
            receipt.write_text(json.dumps({"taxonomy_sha256":sample["taxonomy_sha256"],
                "results_sha256":sample["results_sha256"], "reviewer":"independent-reviewer",
                "reviewed_cache_keys":[r["cache_key"] for r in sample["entries"]], "open_issues":0}))
            fixtures.cvlr.reprocess(fixture.db, fixture.output, selection_file=fixture.selection,
                rule_config=rules_path, quality_review=receipt)
            self.assertEqual("passed", fixture._load_outputs()[1]["quality_audit"]["status"])
            changed = next(r for r in sample["entries"] if r["decision"] == "include")
            changed.update(decision="exclude", coding_method="model_reviewed", reason="人工重新核对后排除")
            imported = fixture.root / "changed.json"; imported.write_text(json.dumps({"entries":[changed]}))
            fixtures.cvlr.reprocess(fixture.db, fixture.output, selection_file=fixture.selection,
                rule_config=rules_path, quality_review=receipt, agent_coding=[imported])
            self.assertEqual("pending", fixture._load_outputs()[1]["quality_audit"]["status"])
        finally:
            fixture.tearDown()

    def record(self, text="My small desk wobbles", rid="r1"):
        return evidence.review_input({"record_id": rid, "hard_key": rid, "source": "reddit"}, text, [], "taxonomy")

    def rules(self):
        return {"version": "1", "rules": [{"id": "wobble", "product_phrases": ["small desk"],
            "phrases": ["wobbles"], "reject_phrases": ["never wobbles", "not wobbles"],
            "semantic_codes": ["complaint"], "need": {"need_id": "stability", "label": "稳定",
            "stance": "support", "applicability": "unknown"}}]}

    def test_rules_and_negation(self):
        r = self.record()
        decision = pipeline.classify(r, self.rules(), {"s1"})
        result = evidence.validate_entry(decision, r, ["complaint"], {"s1"})
        self.assertEqual("rule_classified", result["coding_method"])
        self.assertEqual("stability", result["needs"][0]["need_id"])
        self.assertIsNone(pipeline.classify(self.record("My small desk never wobbles"), self.rules(), {"s1"}))
        self.assertIsNone(pipeline.classify(self.record("unexpected expression"), self.rules(), {"s1"}))
        unicode_record = self.record("Straße. My small desk wobbles")
        unicode_decision = pipeline.classify(unicode_record, self.rules(), {"s1"})
        self.assertEqual("wobbles", unicode_decision["needs"][0]["quote"])
        evidence.validate_entry(unicode_decision, unicode_record, ["complaint"], {"s1"})

    def test_conflict_and_general_voice(self):
        rules = self.rules()
        other = copy.deepcopy(rules["rules"][0]); other.update(id="opposite", decision="exclude")
        rules["rules"].append(other)
        self.assertIsNone(pipeline.classify(self.record(), rules, {"s1"}))
        r = self.record()
        d = pipeline.classify(r, self.rules(), {"s1"}); d["needs"] = []
        self.assertEqual([], evidence.validate_entry(d, r, ["complaint"], {"s1"})["needs"])

    def test_batch_bound_and_complete_segments(self):
        rows = [self.record("文"*3000, "r"+str(i)) for i in range(21)]
        batches = pipeline.review_batches(rows)
        self.assertTrue(all(b.get("segment_count") for b in batches))
        chunks = [b for b in batches if b["record_id"] == "r0"]
        merged = "".join(b["json_fragment"] for b in chunks)
        self.assertEqual(rows[0], json.loads(merged))
        pipeline.validate_segments(len(chunks), [b["segment_index"] for b in chunks])
        with self.assertRaises(ValueError): pipeline.validate_segments(len(chunks), [0])
        with self.assertRaises(ValueError): pipeline.validate_batch_ids(rows, rows[:-1])
        with self.assertRaises(ValueError): pipeline.validate_batch_ids(rows, rows + rows[:1])

    def voices(self, amazon, social):
        result = []
        for kind, count in (("review", amazon), ("social", social)):
            for i in range(count):
                result.append({"voice_id": kind+str(i), "source_kind": kind, "platform": "amazon" if kind=="review" else "web",
                    "coding_method": "rule_classified", "author_key": "same-author", "thread_key": "same-thread",
                    "segment_memberships": ["s1"], "needs": [], "scenarios": []})
        return result

    def test_independent_minima_no_saturation_or_author_gate(self):
        for a, s, passed in ((4000,2000,True), (5000,1000,True), (3000,3000,True), (4000,1900,True)):
            result = evidence.evaluate_single_segment(self.voices(a,s), {"segment_id": "s1"}, [],
                {"unreviewed_records":0, "quality_review_complete":True}, social_policy={},
                data_exhaustion={"status":"completed", "rounds":[{"result":"checked"}]})
            self.assertEqual(passed, result["status"] == "sufficient")
            self.assertFalse(any("saturation" in c["code"] for c in result["checks"]))

    def test_same_words_two_ids_no_semantic_dedup_and_known_author(self):
        v = self.voices(0,2)
        for row in v:
            row.update(excerpt="same words", needs=[{"code":"stability", "label":"稳定", "stance":"support", "applicability":"current"}])
        need = evidence.need_metrics(v, evidence.DEFAULT_THRESHOLDS)[0]
        self.assertEqual(2, need["count"])
        self.assertEqual(1, need["known_authors"])
        self.assertTrue(need["eligible"])

    def test_undetermined_is_completed_and_not_include(self):
        r = self.record()
        d = pipeline.classify(r, self.rules(), {"s1"})
        d.update(decision="undetermined", coding_method="model_reviewed")
        clean = evidence.validate_entry(d, r, ["complaint"], {"s1"})
        self.assertEqual("undetermined", clean["decision"])
        self.assertEqual("completed", clean["processing_status"])

    def test_alias_mapping_and_long_review_receipts(self):
        decision = {"needs":[{"code":"a", "label":"稳定", "stance":"support"},
                             {"code":"b", "label":"稳定", "stance":"counter"}]}
        canonical = pipeline.canonicalize_decision(decision, {"need_aliases":{"a":"stability", "b":"stability"}})
        self.assertEqual(1, len(canonical["needs"]))
        self.assertEqual("mixed", canonical["needs"][0]["stance"])
        record = self.record("中"*5000)
        plan = pipeline.review_batches([record])
        with self.assertRaises(ValueError): pipeline.validate_long_review(record, {})
        pipeline.validate_long_review(record, {"review_payload_sha256":plan[0]["review_payload_sha256"],
            "reviewed_segment_indices":list(range(plan[0]["segment_count"]))})
        exported = pipeline.review_batches([{**record, "rule_suggestions":{}, "audit_sample":False, "decision":None}])
        self.assertEqual(plan[0]["review_payload_sha256"], exported[0]["review_payload_sha256"])

    def test_identity_and_research_material_cannot_inflate_voc(self):
        r = self.record(); r["identity_verified"] = False
        self.assertIsNone(pipeline.classify(r, self.rules(), {"s1"}))
        r["source_kind"] = "research_signal"
        self.assertEqual("exclude", pipeline.classify(r, {}, {"s1"})["decision"])
        for marker in ("research_signal", "model_summary"):
            self.assertEqual("research_signal", evidence.source_kind({"source":"web", "source_kind":"social",
                "raw_json":json.dumps({"original":{"evidence_kind":marker}})}))

    def test_web_site_local_identity_and_result_hash(self):
        import consumer_voice_local_reprocess as reprocess
        a = {"source":"web", "canonical_url":"https://one.example/post/1", "author_id":"1", "thread_id":"1"}
        b = {**a, "canonical_url":"https://two.example/post/1"}
        self.assertNotEqual(reprocess._source_namespace(a), reprocess._source_namespace(b))
        self.assertNotEqual(reprocess._author_key(a), reprocess._author_key(b))
        self.assertNotEqual(reprocess._thread_key(a), reprocess._thread_key(b))
        original = [{"record_id":"1", "cache_key":"same-text", "decision":"include"}]
        changed = [{**original[0], "decision":"exclude"}]
        self.assertNotEqual(pipeline.results_sha256(original), pipeline.results_sha256(changed))
        import sqlite3
        import test_consumer_voice_local_reprocess as fixtures
        fixture = fixtures.LocalReprocessTestCase(); fixture.setUp()
        try:
            with sqlite3.connect(fixture.db) as connection:
                for rid, host in (("same-a","one.example"),("same-b","two.example")):
                    connection.execute("UPDATE comments SET source='web', content_id='same-id', author_id='same-author', canonical_url=? WHERE record_id=?",
                        ("https://"+host+"/post/1", rid))
            fixtures.cvlr.reprocess(fixture.db, fixture.output, selection_file=fixture.selection)
            coding, _ = fixture._load_outputs()
            selected = [v for v in coding["voices"] if v["voice_id"] in {"same-a","same-b"}]
            self.assertEqual(2, len(selected))
            self.assertEqual(2, len({v["hard_identity"] for v in selected}))
            self.assertEqual(2, len({v["author_key"] for v in selected}))
        finally:
            fixture.tearDown()

    def test_new_method_source_breakdown_uses_stable_code_even_without_needs(self):
        voices = [{"voice_id":"1", "source_kind":"social", "platform":"web", "author_key":None,
            "thread_key":None, "coding_method":"rule_classified", "topic_codes":["aaa","bbb"],
            "topic_labels":["同名", "同名"]}]
        social = evidence.source_breakdown(voices)[0]
        self.assertEqual(2, len(social["top_topics"]))


if __name__ == "__main__":
    unittest.main()
