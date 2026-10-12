from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import consumer_product_development as dev


def fixture(root):
    coding = {"metadata": {"source_db_sha256": "a" * 64}, "voices": [{"voice_id": "v1", "raw_excerpt": "I wish it was easier to open", "topic_codes": ["access"], "segment_memberships": ["segment_1_all_history"]}]}
    analysis = {
        "metadata": coding["metadata"], "funnel": {"qualified_consumer_voices": 1},
        "top_segments": [{"segment_id": "segment_1_all_history", "consumer_voice_count": 1000}],
        "evidence_readiness": {"status": "sufficient", "needs": [{"code": "access", "eligible": True, "support_refs": ["v1"], "applicability": {"current": ["v1"]}}]},
        "product_concepts": [], "kano": [],
    }
    cp, ap, wp = root / "coding.json", root / "analysis.json", root / "workshop"
    dev.write_json(cp, coding); dev.write_json(ap, analysis)
    dev.prepare(cp, ap, wp)
    agents = {role: "agent-" + role for role in dev.ROLE_SPECS_V2}
    def write(role, phase, payload):
        payload = {"role": role, "phase": phase, "agent_id": agents[role], **payload}
        dev.write_json(wp / dev._expected_v2_artifact(role, phase), payload)

    write("facilitator", "empathize_define", {"workshop_problem": "让用户安全地单手开合", "target_segment": "segment_1_all_history", "decision_criteria": "先验证开合力和夹手风险", "how_might_we": ["如何让锁扣更易打开"], "open_questions": ["夹手风险是否可控"]})
    write("consumer_insights", "empathize_define", {"need_evidence_map": [{"need_code": "access", "insight": "用户想更省力地开合", "evidence_refs": ["v1"], "counterevidence_ids": [], "hypothesis_status": "supported"}]})
    write("human_factors", "empathize_define", {"journeys": [{"scenario": "上车后放入手机", "user_action": "单手打开锁扣", "barrier": "开合力过大", "desired_outcome": "无需双手", "steps": ["触达", "开合", "放入"], "constraints": ["驾驶座空间有限"]}]})
    write("market_strategy", "empathize_define", {"market_hypotheses": [{"target_user": "需要频繁取放手机的驾驶者", "alternative": "普通夹具", "value_proposition": "更省力的单手开合", "evidence_status": "to_validate"}]})
    write("independent_challenger", "empathize_define", {"challenges": [{"claim": "开合困难是核心痛点", "alternative_explanation": "可能是个别型号磨损", "evidence_needed": "跨型号开合测试"}]})

    for role in dev.V2_IDEATORS:
        idea = {"candidate_id": role + "_1", "name": "杠杆锁扣", "target_users": "现有用户", "scenarios": "单手放入手机", "core_need_codes": ["access"], "mechanism": "改变杠杆比", "evidence_refs": ["v1"], "assumptions": ["需要原型验证"], "differentiation": "降低开合力", "tradeoffs": "可能增加体积"}
        if role == "cross_domain":
            idea.update({"analogy": "相机快拆", "transfer_reason": "同样需要单手锁定", "non_applicable_conditions": "高振动下可能需要二次锁定"})
        write(role, "ideate", {"ideas": [idea]})
    write("product_architect", "synthesize", {"candidates": [{"candidate_id": "merged_1", "source_candidate_ids": [role + "_1" for role in dev.V2_IDEATORS], "merge_rationale": "不同机制都指向单手开合", "core_value": "降低开合负担", "functional_boundary": "只改善锁扣", "not_doing": "不加入充电功能", "module_relationships": {"lock": "connects_to_arm"}, "structure_layout": "销轴锁扣", "use_flow": "按压后放入手机", "tradeoffs": "体积略增", "open_questions": ["夹手风险"]}]})
    for role in dev.V2_REVIEWERS:
        issues = []
        if role == "consumer_insights":
            issues = [{"issue_id": "issue-1", "statement": "需验证是否真能单手开合", "basis": "只有一条原声", "severity": "major", "recommended_disposition": "prototype_test"}]
        write(role, "review", {"reviews": [{"candidate_id": "merged_1", "applicable": True, "reason": "按职责检查候选", "issues": issues, "counterevidence_ids": []}]})
    write("facilitator", "resolve", {"issues": [{"issue_id": "issue-1", "candidate_id": "merged_1", "raised_by": "consumer_insights", "owner_role": "prototype_validation", "disposition": "needs_validation", "response": "制作低保真锁扣样机", "remaining_risk": "不同壳厚可能影响开合", "validation_dependency": "开合力测试"}]})
    write("product_architect", "resolve", {"candidate_revisions": [{"candidate_id": "merged_1", "version": "v2", "changes": ["增加导向斜面"], "addressed_issue_ids": ["issue-1"], "accepted_risk_issue_ids": [], "validation_dependencies": [], "remaining_gaps": ["尚未打样"]}]})
    write("prototype_validation", "resolve", {"plans": [{"candidate_id": "merged_1", "hypotheses": ["杠杆可以降低开合力"], "prototype_type": "低保真样机", "fidelity": "功能原型", "test_subjects": "10 个模拟用户", "test_environment": "车内静态场景", "test_method": "测力与观察", "pass_criteria": "开合力低于 20N", "fail_criteria": "夹手或超过 20N", "next_decision": "通过后进入工程样机", "execution_status": "planned"}]})
    for role in dev.V2_REVIEWERS:
        rows = [{"issue_id": "issue-1", "outcome": "acknowledged", "rationale": "接受用样机测试解决"}] if role == "consumer_insights" else []
        write(role, "acknowledge", {"acknowledgements": rows})
    write("facilitator", "select", {"selected_candidate_ids": ["merged_1"], "decision_basis": "证据支持且可验证", "unresolved_controversy_ids": ["issue-1"]})
    write("product_architect", "select", {"selected_candidate_ids": ["merged_1"], "decision_basis": "机制完整且可打样"})
    write("independent_challenger", "select", {"positions": [{"candidate_id": "merged_1", "position": "conditional", "rationale": "须通过夹手风险测试"}]})
    executions = []
    for phase, _label, roles in dev.V2_PHASES:
        for role in roles:
            executions.append({"role": role, "phase": phase, "agent_id": agents[role], "runtime_receipt_ref": "runtime-" + role + "-" + phase, "artifact": dev._expected_v2_artifact(role, phase)})
    registry_input = wp / "role-runtime-receipts.json"
    dev.write_json(registry_input, {"schema_version": "consumer-workshop-role-registry-input-2.0", "executions": executions})
    dev.register_roles(wp, registry_input)
    concept = {
        "candidate_id": "merged_1", "concept_id": "concept_1", "name": "开合原型", "segment_id": "segment_1_all_history", "core_need_codes": ["access"],
        "jtbd": "让用户容易打开", "target_consumers": ["现有用户"], "use_scenarios": ["开合"], "features": ["杠杆锁扣"],
        "technical_solution": "改变杠杆比", "structure": "销轴锁扣", "materials": ["铝"], "risks": ["夹手"], "dependencies": ["材料与实测"],
        "cmf": {"color": "黑色"}, "moscow": {"must": ["易开合"], "should": [], "could": [], "wont": []},
        "design_thinking": {k: {"outputs": ["原型计划"]} for k in ("empathize", "define", "ideate", "prototype", "test", "iteration")},
        "bom_estimate": {"currency": "USD", "min": 2, "max": 4, "assumptions": ["1000件小批量"], "basis": "engineering_estimate"},
        "acceptance_metrics": [{"metric": "开合力", "target": "小于20N", "test_method": "测力计", "test_subjects": "10个原型", "failure_condition": "超过20N或夹手"}],
        "image_prompt": "白底锁扣原型", "selection_rationale": "消费者抱怨开合问题，先验证机制",
        "feature_evidence": [{"feature": "杠杆锁扣", "origin": "evidence_inference", "voice_ids": ["v1"], "counterevidence_ids": [], "reasoning": "开合困难可通过杠杆改善", "validation_plan": "测开合力"}],
    }
    dp = wp / "decisions.json"
    dev.write_json(dp, {"execution_mode": "subagents", "selection_notes": ["依据原声选择可验证机制"], "product_concepts": [concept], "exploration_concepts": []})
    return cp, ap, wp, dp, concept


def legacy_fixture(root):
    cp, ap, _wp, _dp, concept = fixture(root)
    wp = root / "legacy-workshop"
    wp.mkdir()
    dev.write_json(wp / "evidence_pack.json", {"legacy": True})
    dev.write_json(wp / "evidence_index.json", {"legacy": True})
    dev.write_json(wp / "workshop.json", {
        "version": 1, "coding_path": str(cp), "coding_sha256": dev.digest(cp),
        "analysis_path": str(ap), "analysis_sha256": dev.digest(ap),
        "evidence_pack_sha256": dev.digest(wp / "evidence_pack.json"),
        "evidence_index_sha256": dev.digest(wp / "evidence_index.json"),
    })
    for role in dev.IDEATORS:
        ideas = [{"candidate_id": role + "_" + str(index), "name": "开合机制", "segment_id": "segment_1_all_history", "core_need_codes": ["access"], "mechanism": "杠杆锁扣", "evidence_refs": ["v1"], "assumptions": ["待验证"]} for index in range(6)]
        dev.write_json(wp / ("ideate-" + role + ".json"), {"role": role, "agent_id": role, "ideas": ideas})
        dev.write_json(wp / ("revise-" + role + ".json"), {"role": role, "agent_id": role, "responses": [{"candidate_id": "merged_1", "changes": ["补充测试"], "addressed_reviews": list(dev.REVIEWERS), "remaining_gaps": []}]})
    dev.write_json(wp / "merged_candidates.json", {"candidates": [{"candidate_id": "merged_1", "source_candidate_ids": [role + "_0" for role in dev.IDEATORS], "merge_rationale": "共同解决单手开合"}]})
    for role in dev.REVIEWERS:
        dev.write_json(wp / ("review-" + role + ".json"), {"role": role, "agent_id": role, "reviews": [{"candidate_id": "merged_1", "decision": "revise", "reason": "需要样机验证", "issues": [], "counterevidence_ids": []}]})
    decision = wp / "decisions.json"
    dev.write_json(decision, {"execution_mode": "subagents", "selection_notes": ["旧工作坊兼容回归"], "product_concepts": [copy.deepcopy(concept)], "exploration_concepts": []})
    return cp, ap, wp, decision


class DevelopmentTests(unittest.TestCase):
    def test_v23_selects_the_new_workshop_protocol_without_reinterpreting_v22(self):
        self.assertEqual(dev.WORKSHOP_PROTOCOL_V31, dev._workshop_protocol({"business_rules_version": "voc-prd-v2.3"}))
        self.assertEqual(dev.WORKSHOP_PROTOCOL_V3, dev._workshop_protocol({"business_rules_version": "voc-prd-v2.2"}))

    def test_prd_v2_exactly_three_directions(self):
        analysis = {"business_rules_version": "voc-prd-v2"}
        for count in (0, 1, 2, 4):
            with self.assertRaises(dev.DevelopmentError):
                dev.validate_recommendation_count(analysis, [{}] * count)
        dev.validate_recommendation_count(analysis, [{}, {}, {}])

    def test_prd_v2_empty_workshop_is_not_complete(self):
        with self.assertRaises(dev.DevelopmentError):
            dev.validate_development_receipt({"business_rules_version": "voc-prd-v2", "product_concepts": [], "development": {}})
        with self.assertRaises(dev.DevelopmentError):
            dev.validate_development_receipt({"business_rules_version": "voc-prd-v2", "product_concepts": [{}, {}, {}], "development": {}})

    def test_prd_v2_low_volume_keeps_real_need_evidence_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp, ap, _wp, _dp, concept = fixture(Path(tmp))
            analysis = dev.read_json(ap)
            analysis["business_rules_version"] = "voc-prd-v2"
            analysis["evidence_readiness"]["status"] = "insufficient"
            analysis["top_segments"][0]["consumer_voice_count"] = 1
            voices = {v["voice_id"]: v for v in dev.read_json(cp)["voices"]}
            dev.validate_concept(concept, voices, analysis, formal=True)
            analysis["evidence_readiness"]["needs"][0]["eligible"] = False
            with self.assertRaises(dev.DevelopmentError):
                dev.validate_concept(concept, voices, analysis, formal=True)

    def test_historical_v1_workshop_still_finalizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); _cp, _ap, wp, decision = legacy_fixture(root)
            output = root / "legacy-development.json"
            dev.finalize(wp, decision, output)
            self.assertNotIn("protocol_version", dev.read_json(output)["development"])

    def test_complete_workshop_preserves_source_statistics_and_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); cp, ap, wp, dp, _ = fixture(root)
            before = (dev.digest(cp), dev.digest(ap))
            out = root / "development.json"
            dev.finalize(wp, dp, out)
            result = dev.read_json(out)
            self.assertEqual(result["funnel"], dev.read_json(ap)["funnel"])
            self.assertEqual(result["development"]["recommended_count"], 1)
            self.assertEqual(before, (dev.digest(cp), dev.digest(ap)))

    def test_stale_evidence_and_pack_are_rejected(self):
        for filename in ("coding", "pack"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); cp, ap, wp, dp, _ = fixture(root)
                path = cp if filename == "coding" else wp / "evidence_pack.json"
                path.write_text(path.read_text() + " ")
                with self.assertRaises(dev.DevelopmentError):
                    dev.finalize(wp, dp, root / "out.json")

    def test_missing_review_or_revision_cannot_finalize(self):
        for file in ("review-independent-challenger.json", "revise-product-architect.json"):
            with self.subTest(file=file), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); cp, ap, wp, dp, _ = fixture(root)
                (wp / file).unlink()
                with self.assertRaises((OSError, dev.DevelopmentError)):
                    dev.finalize(wp, dp, root / "out.json")

    def test_fake_evidence_bad_cost_and_incomplete_acceptance_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); cp, ap, wp, dp, concept = fixture(root)
            voices = {v["voice_id"]: v for v in dev.read_json(cp)["voices"]}
            dev.validate_concept(concept, voices, dev.read_json(ap), formal=True)
            for change in ("fake", "cost", "failure", "feature", "need", "duplicate", "wrong_need"):
                item = copy.deepcopy(concept)
                if change == "fake": item["feature_evidence"][0]["voice_ids"] = ["invented"]
                if change == "cost": item["bom_estimate"]["min"] = -1
                if change == "failure": del item["acceptance_metrics"][0]["failure_condition"]
                if change == "feature": item["features"].append("没有依据的功能")
                if change == "need": item["core_need_codes"] = ["unverified"]
                if change == "duplicate":
                    item["features"] *= 2; item["feature_evidence"] *= 2
                if change == "wrong_need": item["feature_evidence"][0]["need_codes"] = ["appearance"]
                with self.subTest(change=change), self.assertRaises(dev.DevelopmentError):
                    dev.validate_concept(item, voices, dev.read_json(ap), formal=True)

    def test_other_segment_or_historical_support_cannot_validate_current_feature(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); cp, ap, wp, dp, concept = fixture(root)
            voices = {v["voice_id"]: v for v in dev.read_json(cp)["voices"]}
            analysis = dev.read_json(ap)
            dev.validate_concept(concept, voices, analysis, formal=True)
            voices["v1"]["segment_memberships"] = ["segment_3_all_history"]
            with self.assertRaisesRegex(dev.DevelopmentError, "当前细分"):
                dev.validate_concept(concept, voices, analysis, formal=True)
            voices["v1"]["segment_memberships"] = ["segment_1_all_history"]
            analysis["evidence_readiness"]["needs"][0]["applicability"]["current"] = []
            with self.assertRaisesRegex(dev.DevelopmentError, "当前细分"):
                dev.validate_concept(concept, voices, analysis, formal=True)

    def test_partial_evidence_only_allows_exploration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); cp, ap, wp, dp, concept = fixture(root)
            analysis = dev.read_json(ap); analysis["evidence_readiness"]["status"] = "partial"
            with self.assertRaises(dev.DevelopmentError):
                dev.validate_concept(concept, {"v1": {}}, analysis, formal=True)
            dev.validate_concept(concept, {"v1": {}}, analysis, formal=False)

    def test_v2_rejects_role_simulation_and_allows_exploration_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); cp, ap, wp, dp, concept = fixture(root)
            decision = dev.read_json(dp); decision["execution_mode"] = "role_simulation"
            dev.write_json(dp, decision)
            with self.assertRaises(dev.DevelopmentError): dev.finalize(wp, dp, root / "out.json")
            decision["execution_mode"] = "subagents"
            decision["product_concepts"] = []
            decision["exploration_concepts"] = [concept]
            dev.write_json(dp, decision)
            dev.finalize(wp, dp, root / "out.json")
            self.assertEqual(dev.read_json(root / "out.json")["product_concepts"], [])

    def test_v2_stage_receipt_binds_roles_and_final_concepts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); _cp, _ap, wp, dp, _concept = fixture(root)
            staged = dev.validate_v2_stage(wp, "select")
            self.assertEqual("stage_validated", staged["status"])
            output = root / "development.json"
            dev.finalize(wp, dp, output)
            result = dev.read_json(output)
            dev.validate_development_receipt(result)
            result["product_concepts"][0]["name"] = "被篡改的终稿"
            with self.assertRaisesRegex(dev.DevelopmentError, "完成回执失效"):
                dev.validate_development_receipt(result)

    def test_v2_registry_rejects_one_agent_in_two_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); _cp, _ap, wp, _dp, _concept = fixture(root)
            (wp / "role_registry.json").unlink()
            payload = dev.read_json(wp / "role-runtime-receipts.json")
            duplicate_role, source_role = "human_factors", "facilitator"
            duplicate_agent = "agent-" + source_role
            for execution in payload["executions"]:
                if execution["role"] == duplicate_role:
                    execution["agent_id"] = duplicate_agent
                    artifact = wp / execution["artifact"]
                    document = dev.read_json(artifact)
                    document["agent_id"] = duplicate_agent
                    dev.write_json(artifact, document)
            dev.write_json(wp / "role-runtime-receipts.json", payload)
            with self.assertRaisesRegex(dev.DevelopmentError, "两个十二角色"):
                dev.register_roles(wp, wp / "role-runtime-receipts.json")

    def test_report_finalization_recomputes_protocol_even_for_partial_delivery(self):
        import test_consumer_voice_local_reprocess as data
        import consumer_all_history_report as report
        sample = data.LocalReprocessTestCase()
        sample.setUp()
        try:
            data.cvlr.reprocess(sample.db, sample.output, selection_file=sample.selection, dashboard=sample.dashboard)
            cp = sample.output / "social_voice_all_history_coding.json"
            ap = sample.output / "social_voice_all_history_analysis.json"
            hp, mp = sample.root / "report.html", sample.root / "manifest.json"
            dev.write_json(mp, {"artifacts": {}, "status": {"market_opportunity": "ready"}})
            original = dev.read_json(ap)
            args = dict(manifest_path=mp, coding_path=cp, analysis_path=ap, report_path=hp,
                        source_db_path=sample.db, dashboard_path=sample.dashboard, status="partial",
                        source_snapshot_path=sample.output / "source_snapshot.json")
            def render():
                report.render_report(dev.read_json(ap), analysis_path=ap, template_path=report._default_template(), output_path=hp)
            render()
            report.finalize_manifest(**args)
            manifest_hash = dev.digest(mp)
            tampered = copy.deepcopy(original)
            tampered["evidence_readiness"]["status"] = "sufficient"
            for check in tampered["evidence_readiness"]["checks"]:
                check["passed"] = True
            dev.write_json(ap, tampered)
            render()  # A matching HTML hash must not bypass evidence validation.
            with self.assertRaisesRegex(report.ReportError, "证据.*校验失败"):
                report.finalize_manifest(**args)
            self.assertEqual(manifest_hash, dev.digest(mp))
        finally:
            sample.tearDown()


if __name__ == "__main__":
    unittest.main()
