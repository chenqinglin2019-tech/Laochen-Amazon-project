from __future__ import annotations

import copy
import importlib.util
import json
import struct
import tempfile
import time
import unittest
import zlib
from pathlib import Path
from unittest import mock


SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "scripts" / "consumer_product_report.py"
SPEC = importlib.util.spec_from_file_location("consumer_product_report", MODULE_PATH)
assert SPEC and SPEC.loader
cpr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cpr)


def _zero_stage() -> dict[str, int]:
    return {field: 0 for field in cpr.FUNNEL_STAGE_FIELDS}


def _png_bytes(red: int, green: int, blue: int) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes((0, red, green, blue))))
        + chunk(b"IEND", b"")
    )


def _coding_v2() -> dict:
    start_30 = "2026-07-06T00:00:00Z"
    start_90 = "2026-05-07T00:00:00Z"
    end_at = "2026-08-05T00:00:00Z"
    scopes = (cpr.CATEGORY_SCOPE, *cpr.SEGMENT_SCOPES)
    return {
        "schema_version": "2.0.0",
        "project": {
            "project_root": "/tmp/project",
            "marketplace": "US",
            "listing_language": "en",
            "category_keyword": "test product",
            "opportunity_analysis": {
                "path": "07_opportunity_analysis.json",
                "sha256": "0" * 64,
                "snapshot_at": end_at,
            },
            "opportunity_dashboard": {
                "path": "机会看板.html",
                "sha256": "1" * 64,
                "snapshot_at": end_at,
            },
        },
        "generated_at": end_at,
        "end_at": end_at,
        "windows": {
            "interval_semantics": "[start_at,end_at)",
            "category_30d": {
                "scope_id": "category_30d",
                "days": 30,
                "start_at": start_30,
                "end_at": end_at,
            },
            "segment_90d": {"days": 90, "start_at": start_90, "end_at": end_at},
        },
        "top3_selection": {
            "source_field": "07_opportunity_analysis.json.feature_distribution",
            "dimension_status_source_field": "07_opportunity_analysis.json.dimension_statuses",
            "listing_share_min": 0.03,
            "listing_share_max": 0.2,
            "boundaries_inclusive": True,
            "required_dimension_valid": True,
            "required_effective_feature": True,
            "excluded_feature_values": [],
            "sort_order": [
                "supply_demand_index:desc",
                "listing_count:desc",
                "sales_share:desc",
                "dimension_rank:asc",
                "dimension_feature_name:asc",
            ],
            "candidate_count_before_filter": 0,
            "candidate_count_after_filter": 0,
            "normalization_decisions": [],
            "ranked_candidates": [],
            "selected_segment_ids": [],
            "unavailable_ranks": [1, 2, 3],
        },
        "segments": [],
        "query_plan": {
            "query_language": "en",
            "primary_lanes": [
                {
                    "query_id": "query_category",
                    "scope_id": "category_30d",
                    "primary_tool": "last30days",
                    "days": 30,
                    "as_of_utc_date": "2026-08-05",
                    "start_at": start_30,
                    "end_at": end_at,
                    "queries": ["test product"],
                    "intents": [
                        "purchase_selection",
                        "usage_scenario",
                        "satisfaction_recommendation",
                        "failure_complaint_return",
                        "alternative_replacement",
                        "diy_workaround",
                        "feature_request",
                        "reverse_need",
                    ],
                    "target_platforms": ["reddit", "youtube", "x"],
                }
            ],
            "gap_fill_queries": [],
        },
        "source_runs": [],
        "agent_reach_health": {
            "doctor": {
                "ran_at": end_at,
                "status": "not_run",
                "active_backends": [],
                "raw_artifact": None,
            },
            "check_update": {
                "ran_at": None,
                "status": "not_run",
                "current_version": None,
                "latest_version": None,
                "message": None,
            },
        },
        "need_dictionary": [],
        "voices": [],
        "dedup_groups": [],
        "excluded_records": [],
        "llm_calls": [],
        "research_plan": cpr._default_research_plan("quick"),
        "collection_funnel": {
            **_zero_stage(),
            "excluded_records": 0,
            "per_scope": [
                {"scope_id": scope, **_zero_stage()} for scope in scopes
            ],
            "per_platform": [],
            "exclusion_reasons": [],
        },
        "stop_reason": "queues_exhausted",
    }


def _runtime_collection_receipt(
    run_dir: Path,
    *,
    research_level: str = "quick",
    collection: float = 12.5,
    total: float = 18.75,
    deadline_exceeded: bool = False,
    finalization_only: bool = False,
    action: str = "continue",
    quota_and_cost: dict | None = None,
) -> dict:
    return {
        "task_id": "task-test-consumer-voice",
        "run_dir": str(run_dir.resolve()),
        "research_plan": cpr._default_research_plan(research_level),
        "time_usage_minutes": {
            "collection": collection,
            "total": total,
            "unmetered_human_setup_wait": {
                "status": "not_recorded",
                "minutes": None,
                "included_in_collection_or_total": False,
            },
        },
        "budget_gate": {
            "deadline_exceeded": deadline_exceeded,
            "finalization_only": finalization_only,
            "action": action,
        },
        "quota_and_cost": quota_and_cost or {"ledger": []},
    }


def _voice(
    voice_id: str,
    *,
    content_id: str | None,
    author: str = "author-a",
    url: str = "https://example.com/thread/1",
    parent_id: str = "parent-1",
    published_at: str = "2026-08-01T00:00:00Z",
    quote: str = "exact message",
) -> dict:
    return {
        "voice_id": voice_id,
        "platform": "reddit",
        "content_type": "comment",
        "content_id": content_id,
        "author_hash": author,
        "normalized_url": url,
        "parent_id": parent_id,
        "published_at": published_at,
        "excerpt": quote,
    }


def _synthetic_coding(level: str, per_scope: dict[str, int]) -> dict:
    """Build a schema-valid large corpus whose messages share one meaning but not one identity."""
    document = _coding_v2()
    document["research_plan"] = cpr._default_research_plan(level)
    document["stop_reason"] = "upper_bound_reached"
    segment_rows = []
    ranked_candidates = []
    for rank, scope_id in enumerate(cpr.SEGMENT_SCOPES, start=1):
        segment = {
            "segment_id": scope_id,
            "rank": rank,
            "dimension": "测试维度",
            "feature": f"测试细分{rank}",
            "canonical_key": f"test:segment-{rank}",
            "listing_count": 20 - rank,
            "listing_share": 0.05,
            "sales_share": 0.1,
            "supply_demand_index": 3.0 - rank / 10,
            "dimension_rank": rank,
            "synonyms": [],
        }
        segment_rows.append(segment)
        ranked_candidates.append(
            {
                "dimension": segment["dimension"],
                "feature": segment["feature"],
                "canonical_key": segment["canonical_key"],
                "dimension_valid": True,
                "is_effective_feature": True,
                "listing_count": segment["listing_count"],
                "listing_share": segment["listing_share"],
                "sales_share": segment["sales_share"],
                "supply_demand_index": segment["supply_demand_index"],
                "dimension_rank": segment["dimension_rank"],
                "eligible": True,
                "selected": True,
                "exclusion_reasons": [],
            }
        )
    document["segments"] = segment_rows
    selection = document["top3_selection"]
    selection.update(
        {
            "candidate_count_before_filter": 3,
            "candidate_count_after_filter": 3,
            "ranked_candidates": ranked_candidates,
            "selected_segment_ids": list(cpr.SEGMENT_SCOPES),
            "unavailable_ranks": [],
        }
    )
    scopes = (cpr.CATEGORY_SCOPE, *cpr.SEGMENT_SCOPES)
    document["query_plan"]["primary_lanes"] = []
    document["source_runs"] = []
    for scope_id in scopes:
        days = 30 if scope_id == cpr.CATEGORY_SCOPE else 90
        start_at = (
            document["windows"]["category_30d"]["start_at"]
            if days == 30
            else document["windows"]["segment_90d"]["start_at"]
        )
        query_id = f"query_{scope_id}"
        run_id = f"run_{scope_id}"
        document["query_plan"]["primary_lanes"].append(
            {
                "query_id": query_id,
                "scope_id": scope_id,
                "primary_tool": "last30days",
                "days": days,
                "as_of_utc_date": "2026-08-05",
                "start_at": start_at,
                "end_at": document["end_at"],
                "queries": ["test product consumer voice"],
                "intents": [
                    "purchase_selection",
                    "usage_scenario",
                    "satisfaction_recommendation",
                    "failure_complaint_return",
                    "alternative_replacement",
                    "diy_workaround",
                    "feature_request",
                    "reverse_need",
                ],
                "target_platforms": ["reddit", "youtube", "x"],
            }
        )
        document["source_runs"].append(
            {
                "run_id": run_id,
                "tool": "last30days",
                "role": "broad_primary_collection",
                "scope_ids": [scope_id],
                "query_ids": [query_id],
                "started_at": "2026-08-04T00:00:00Z",
                "finished_at": "2026-08-04T01:00:00Z",
                "status": "ok",
                "platform_statuses": [],
                "raw_artifact": None,
                "error_summary": None,
            }
        )
    document["need_dictionary"] = [
        {
            "need_code": "secure_hold",
            "name_zh": "需要更强的加固",
            "definition": "在颠簸场景保持稳定",
            "inclusions": ["固定", "加固"],
            "exclusions": [],
            "synonyms": [],
        }
    ]
    platforms = ("reddit", "youtube", "x")
    platform_counts = {platform: 0 for platform in platforms}
    voices = []
    for scope_id in scopes:
        query_id = f"query_{scope_id}"
        run_id = f"run_{scope_id}"
        for index in range(per_scope[scope_id]):
            platform = platforms[len(voices) % len(platforms)]
            platform_counts[platform] += 1
            identity = f"{scope_id}_{index}"
            memberships = []
            if scope_id in cpr.SEGMENT_SCOPES:
                memberships.append(
                    {
                        "segment_id": scope_id,
                        "is_member": True,
                        "evidence": "正文明确属于该测试细分",
                        "confidence": "high",
                        "method": "explicit_text",
                    }
                )
            voices.append(
                {
                    "voice_id": f"voice_{identity}",
                    "platform": platform,
                    "backend": "synthetic-test",
                    "content_type": "comment",
                    "content_id": f"comment_{identity}",
                    "thread_id": f"thread_{identity}",
                    "parent_id": f"post_{identity}",
                    "community": "synthetic",
                    "author_hash": f"author_{identity}",
                    "author_label": f"user_{identity}",
                    "author_identity_status": "pseudonymous",
                    "published_at": "2026-08-01T00:00:00Z",
                    "collected_at": "2026-08-04T01:00:00Z",
                    "language": "en",
                    "region_hint": "US",
                    "excerpt": "The mount needs stronger reinforcement.",
                    "summary_zh": "消费者要求更强的加固。",
                    "normalized_url": f"https://example.test/{platform}/comments/{identity}",
                    "engagement": {
                        "likes": 0,
                        "replies": 0,
                        "shares": 0,
                        "views": 0,
                        "score": 0,
                        "captured_at": "2026-08-04T01:00:00Z",
                    },
                    "actor_type": "consumer",
                    "eligible_for_quantitation": True,
                    "exclusion_reasons": [],
                    "collection_scopes": [scope_id],
                    "query_ids": [query_id],
                    "segment_memberships": memberships,
                    "discoveries": [
                        {
                            "discovery_id": f"discovery_{identity}",
                            "source_run_id": run_id,
                            "query_id": query_id,
                            "scope_id": scope_id,
                            "platform": platform,
                            "backend": "synthetic-test",
                            "source_content_id": f"comment_{identity}",
                            "source_url": f"https://example.test/{platform}/comments/{identity}",
                            "retrieved_at": "2026-08-04T01:00:00Z",
                        }
                    ],
                    "coding": {
                        "sentiment": "negative",
                        "use_scenes": ["rough_road"],
                        "persona_tags": ["driver"],
                        "need_codes": ["secure_hold"],
                        "satisfaction_codes": [],
                        "dissatisfaction_codes": ["secure_hold"],
                        "innovation_signals": [],
                        "kano_evidence": [
                            {
                                "need_code": "secure_hold",
                                "evidence_type": "absence_complaint",
                                "evidence_excerpt": "needs stronger reinforcement",
                            }
                        ],
                        "evidence_confidence": "high",
                        "coding_notes": None,
                    },
                }
            )
    document["voices"] = voices
    total = len(voices)
    document["collection_funnel"] = {
        **{field: total for field in cpr.FUNNEL_STAGE_FIELDS},
        "excluded_records": 0,
        "per_scope": [
            {
                "scope_id": scope_id,
                **{field: per_scope[scope_id] for field in cpr.FUNNEL_STAGE_FIELDS},
            }
            for scope_id in scopes
        ],
        "per_platform": [
            {
                "platform": platform,
                "fetched_records": count,
                "valid_voices": count,
            }
            for platform, count in platform_counts.items()
        ],
        "exclusion_reasons": [],
    }
    return document


class ContractV2Tests(unittest.TestCase):
    def test_fixed_research_levels(self) -> None:
        expected = {
            "quick": (500, 1000, 35, 60),
            "standard": (1000, 3000, 55, 90),
            "deep": (3000, 5000, 75, 120),
        }
        for level, values in expected.items():
            plan = cpr._default_research_plan(level)
            self.assertEqual(values[:2], (plan["sample_target"]["total_valid_min"], plan["sample_target"]["total_valid_max"]))
            self.assertEqual(values[2:], (plan["time_budget_minutes"]["collection"], plan["time_budget_minutes"]["total"]))
            self.assertEqual(3, plan["sample_target"]["min_platforms"])
            self.assertEqual(1.0, sum(item["share"] for item in plan["sample_target"]["per_scope"].values()))

    def test_selected_segment_keeps_known_normalized_synonyms(self) -> None:
        opportunity = {
            "feature_distribution": [
                {
                    "dimension": "夹持方式",
                    "feature": "机械夹持",
                    "is_effective_feature": True,
                    "listing_share": 0.1,
                    "sales_share": 0.2,
                    "listing_count": 12,
                    "supply_demand_index": 2.0,
                }
            ],
            "dimension_statuses": [{"dimension": "夹持方式", "valid": True}],
            "agent_trace": {
                "normalization_dictionary": [
                    {
                        "dimension": "夹持方式",
                        "raw_value": "mechanical clamp",
                        "standard_value": "mechanical clamping",
                        "upper_group": "mechanical clamping",
                        "display_value": "机械夹持",
                    },
                    {
                        "dimension": "夹持方式",
                        "raw_value": "clamp mount",
                        "standard_value": "mechanical clamping",
                        "upper_group": "mechanical clamping",
                        "display_value": "机械夹持",
                    },
                ]
            },
        }
        result = cpr.select_segments(opportunity)
        self.assertEqual(
            ["clamp mount", "mechanical clamp", "mechanical clamping"],
            result["selected_segments"][0]["synonyms"],
        )

    def test_v2_validates_and_v1_still_reads(self) -> None:
        v2 = _coding_v2()
        normalized, _ = cpr.validate_coding_document(v2)
        self.assertEqual("2.0.0", normalized["schema_version"])

        v1 = copy.deepcopy(v2)
        v1["schema_version"] = "1.0.0"
        for field in ("research_plan", "collection_funnel", "stop_reason"):
            v1.pop(field)
        v1["windows"]["segment_90d"]["recent_30d_start_at"] = "2026-07-06T00:00:00Z"
        normalized_v1, _ = cpr.validate_coding_document(v1)
        self.assertEqual("1.0.0", normalized_v1["schema_version"])

    def test_deduplicated_stage_may_exceed_final_valid_voices(self) -> None:
        document = _coding_v2()
        for field in cpr.FUNNEL_STAGE_FIELDS[:-1]:
            document["collection_funnel"][field] = 1
        document["collection_funnel"]["valid_voices"] = 0
        normalized, _ = cpr.validate_coding_document(document)
        self.assertEqual(1, normalized["collection_funnel"]["deduplicated_records"])
        self.assertEqual(0, normalized["collection_funnel"]["valid_voices"])

    def test_v2_rejects_removed_recent_fields(self) -> None:
        document = _coding_v2()
        document["windows"]["segment_90d"]["recent_30d_start_at"] = "2026-07-06T00:00:00Z"
        with self.assertRaises(cpr.ContractError) as caught:
            cpr.validate_coding_document(document)
        self.assertTrue(any("recent_30d_start_at" in item for item in caught.exception.details))

        analysis = {"schema_version": "2.0.0", "same_window_comparison": {}}
        self.assertTrue(cpr._v2_removed_analysis_field_errors(analysis))

    def test_v1_object_memberships_are_parsed(self) -> None:
        voice = {
            "collection_scopes": ["category_30d"],
            "segment_memberships": [
                {"segment_id": "segment_1_90d", "is_member": True},
                {"segment_id": "segment_2_90d", "is_member": False},
            ],
        }
        self.assertEqual(
            {"category_30d", "segment_1_90d"}, cpr._voice_scope_ids(voice)
        )

    def test_segment_query_hit_does_not_become_segment_membership(self) -> None:
        voice = {
            "collection_scopes": ["segment_1_90d"],
            "segment_memberships": [
                {
                    "segment_id": "segment_1_90d",
                    "is_member": False,
                    "evidence": "正文不属于该细分",
                }
            ],
        }
        self.assertEqual(set(), cpr._voice_scope_ids(voice))

    def test_analyze_writes_v2_without_recent_subsets(self) -> None:
        result = cpr.analyze_coding(_coding_v2())
        self.assertEqual("2.0.0", result["schema_version"])
        self.assertNotIn("same_window_comparison", result)
        self.assertFalse(any("recent_30d" in key for key in result["denominators"]))
        receipt = result["collection_receipt"]
        self.assertFalse(receipt["available"])
        self.assertEqual(
            [0.4, 0.2, 0.2, 0.2],
            [item["share"] for item in receipt["target_attainment"]["routes"]],
        )
        self.assertIsNone(receipt["time_usage_minutes"]["collection"])
        self.assertEqual(
            "not_recorded",
            receipt["youtube_quota_and_cost"]["cost_classification"],
        )
        cpr._validate_against_schema(
            result,
            SKILL_ROOT / "references" / "social_voice_analysis.schema.json",
            "v2 analysis",
        )

    def test_analysis_imports_collection_receipt_business_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            coding_path = root / "social_voice_coding.json"
            coding = _coding_v2()
            coding_path.write_text(json.dumps(coding), encoding="utf-8")
            (root / "collection_receipt.json").write_text(
                json.dumps(
                    _runtime_collection_receipt(
                        root,
                        deadline_exceeded=True,
                        finalization_only=True,
                        action="finalize_over_budget",
                        quota_and_cost={
                            "daily_quota_limit": 10000,
                            "quota_units": 320,
                            "request_entries": 6,
                            "ledger": [
                                {
                                    "source": "youtube",
                                    "operation": "commentThreads.list",
                                    "request_entries": 6,
                                    "units": 320,
                                    "cost_status": "quota_only",
                                    "amount": None,
                                }
                            ],
                        },
                    )
                ),
                encoding="utf-8",
            )

            result = cpr.analyze_coding(coding, coding_path=coding_path)
            receipt = result["collection_receipt"]
            self.assertTrue(receipt["available"])
            self.assertEqual(12.5, receipt["time_usage_minutes"]["collection"])
            self.assertEqual(18.75, receipt["time_usage_minutes"]["total"])
            self.assertTrue(receipt["deadline_status"]["recorded"])
            self.assertTrue(receipt["deadline_status"]["deadline_exceeded"])
            self.assertFalse(
                receipt["time_usage_minutes"]["unmetered_api_setup_wait"][
                    "included_in_collection_or_total"
                ]
            )
            youtube = receipt["youtube_quota_and_cost"]
            self.assertEqual(320, youtube["quota_units"])
            self.assertEqual(6, youtube["request_entries"])
            self.assertEqual("quota_only", youtube["cost_classification"])
            self.assertIn("配额单位不是美元", youtube["interpretation_zh"])
            self.assertIsNone(youtube["provider_confirmed_actual_cost_usd"])
            self.assertIsNone(youtube["estimated_direct_cost_usd"])
            cpr._validate_against_schema(
                result,
                SKILL_ROOT / "references" / "social_voice_analysis.schema.json",
                "v2 analysis with receipt",
            )

    def test_collection_receipt_requires_exact_task_directory_and_plan_binding(self) -> None:
        cases = (
            (
                "task_id",
                lambda receipt, root: receipt.update({"task_id": ""}),
                "task_id",
            ),
            (
                "run_dir",
                lambda receipt, root: receipt.update(
                    {"run_dir": str((root / "other-run").resolve())}
                ),
                "run_dir",
            ),
            (
                "research_plan",
                lambda receipt, root: receipt.update(
                    {"research_plan": cpr._default_research_plan("standard")}
                ),
                "research_plan",
            ),
        )
        for label, mutate, expected in cases:
            with self.subTest(field=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                coding_path = root / "social_voice_coding.json"
                coding = _coding_v2()
                coding_path.write_text(json.dumps(coding), encoding="utf-8")
                receipt = _runtime_collection_receipt(root)
                mutate(receipt, root)
                (root / "collection_receipt.json").write_text(
                    json.dumps(receipt), encoding="utf-8"
                )
                with self.assertRaises(cpr.ContractError) as caught:
                    cpr.analyze_coding(coding, coding_path=coding_path)
                self.assertIn(
                    expected,
                    "\n".join(caught.exception.details),
                )

    def test_collection_receipt_deadline_is_recorded_only_when_fields_are_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            coding_path = root / "social_voice_coding.json"
            coding = _coding_v2()
            coding_path.write_text(json.dumps(coding), encoding="utf-8")
            receipt = _runtime_collection_receipt(root)
            receipt["budget_gate"].pop("deadline_exceeded")
            (root / "collection_receipt.json").write_text(
                json.dumps(receipt), encoding="utf-8"
            )

            result = cpr.analyze_coding(coding, coding_path=coding_path)
            deadline = result["collection_receipt"]["deadline_status"]
            self.assertFalse(deadline["recorded"])
            self.assertIsNone(deadline["deadline_exceeded"])
            self.assertIsNone(deadline["finalization_only"])
            self.assertIsNone(deadline["action"])

    def test_ready_schema_requires_real_receipt_and_explicit_safe_deadline(self) -> None:
        analysis = cpr.analyze_coding(_coding_v2())
        artifacts = analysis["report_artifacts"]
        artifacts.update(
            {
                "status": "ready",
                "image_paths": ["concept-1.png", "concept-2.png", "concept-3.png"],
                "embedded_image_count": 3,
                "all_product_images_ready": True,
                "standalone_html": True,
            }
        )
        artifacts["analysis_json"]["status"] = "validated"
        artifacts["html_report"]["status"] = "validated"
        receipt = analysis["collection_receipt"]
        receipt["time_usage_minutes"].update({"collection": 20, "total": 40})
        receipt["deadline_status"].update(
            {
                "recorded": True,
                "deadline_exceeded": False,
                "finalization_only": False,
                "action": "continue",
            }
        )

        schema_path = SKILL_ROOT / "references" / "social_voice_analysis.schema.json"
        invalid = copy.deepcopy(analysis)
        invalid["collection_receipt"]["available"] = False
        invalid["collection_receipt"]["deadline_status"]["recorded"] = False
        with self.assertRaises(cpr.ContractError) as caught:
            cpr._validate_against_schema(invalid, schema_path, "ready analysis")
        details = "\n".join(caught.exception.details)
        self.assertIn("collection_receipt.available", details)
        self.assertIn("collection_receipt.deadline_status.recorded", details)

        missing_fields = copy.deepcopy(analysis)
        missing_fields["collection_receipt"]["time_usage_minutes"].pop("total")
        missing_fields["collection_receipt"]["deadline_status"].pop(
            "deadline_exceeded"
        )
        with self.assertRaises(cpr.ContractError) as missing_caught:
            cpr._validate_against_schema(
                missing_fields, schema_path, "ready analysis missing receipt fields"
            )
        missing_details = "\n".join(missing_caught.exception.details)
        self.assertIn("time_usage_minutes: 缺少必填字段 total", missing_details)
        self.assertIn(
            "deadline_status: 缺少必填字段 deadline_exceeded", missing_details
        )

        analysis["collection_receipt"]["available"] = True
        cpr._validate_against_schema(analysis, schema_path, "ready analysis")

    def test_ready_gate_requires_real_recorded_receipt_and_rechecks_total_time(self) -> None:
        base = cpr.analyze_coding(_coding_v2())

        missing = copy.deepcopy(base)
        missing.pop("collection_receipt")
        self.assertTrue(
            any("真实采集回执" in item for item in cpr._ready_gate_errors(missing))
        )

        unrecorded = copy.deepcopy(base)
        unrecorded["collection_receipt"]["available"] = True
        unrecorded["collection_receipt"]["time_usage_minutes"].update(
            {"collection": 20, "total": 40}
        )
        self.assertTrue(
            any("完整且有效" in item for item in cpr._ready_gate_errors(unrecorded))
        )

        ambiguous = copy.deepcopy(unrecorded)
        ambiguous["collection_receipt"]["deadline_status"]["recorded"] = True
        self.assertTrue(
            any(
                "deadline_exceeded=false" in item
                for item in cpr._ready_gate_errors(ambiguous)
            )
        )

        understated = copy.deepcopy(unrecorded)
        understated["collection_receipt"]["time_usage_minutes"]["total"] = 60
        understated["collection_receipt"]["deadline_status"].update(
            {
                "recorded": True,
                "deadline_exceeded": False,
                "finalization_only": True,
                "action": "finalize_now",
            }
        )
        self.assertTrue(
            any(
                "实际总耗时已达到" in item
                for item in cpr._ready_gate_errors(understated)
            )
        )

    def test_v2_analysis_schema_rejects_every_removed_field_family(self) -> None:
        base = cpr.analyze_coding(_coding_v2())
        variants = []
        same_window = copy.deepcopy(base)
        same_window["same_window_comparison"] = {}
        variants.append((same_window, "same_window_comparison"))
        recent_window = copy.deepcopy(base)
        recent_window["windows"]["segment_90d"]["recent_30d_start_at"] = "2026-07-06T00:00:00Z"
        variants.append((recent_window, "recent_30d_start_at"))
        recent_method = copy.deepcopy(base)
        recent_method["methodology"]["segment_recent_slice_days"] = 30
        variants.append((recent_method, "segment_recent_slice_days"))
        recent_denominator = copy.deepcopy(base)
        recent_denominator["denominators"]["N_segment_1_recent_30d"] = 0
        variants.append((recent_denominator, "N_segment_1_recent_30d"))
        invalid_receipt_share = copy.deepcopy(base)
        invalid_receipt_share["collection_receipt"]["target_attainment"]["routes"][0][
            "share"
        ] = 0.3
        variants.append((invalid_receipt_share, "0.4"))
        for document, field in variants:
            with self.subTest(field=field), self.assertRaises(cpr.ContractError) as caught:
                cpr._validate_against_schema(
                    document,
                    SKILL_ROOT / "references" / "social_voice_analysis.schema.json",
                    "v2 analysis",
                )
            self.assertTrue(any(field in item for item in caught.exception.details))

        for field in ("is_recent_30d", "period_bucket", "temporal_buckets"):
            errors = cpr._v2_removed_coding_field_errors(
                {"schema_version": "2.0.0", "voices": [{field: True}]}
            )
            self.assertTrue(any(field in item for item in errors))

    def test_1000_3000_5000_same_semantic_voices_reconcile_and_scale(self) -> None:
        cases = {
            "quick": {
                "category_30d": 400,
                "segment_1_90d": 200,
                "segment_2_90d": 200,
                "segment_3_90d": 200,
            },
            "standard": {
                "category_30d": 1200,
                "segment_1_90d": 600,
                "segment_2_90d": 600,
                "segment_3_90d": 600,
            },
            "deep": {
                "category_30d": 2000,
                "segment_1_90d": 1000,
                "segment_2_90d": 1000,
                "segment_3_90d": 1000,
            },
        }
        analyses = {}
        documents = {}
        for level, per_scope in cases.items():
            document = _synthetic_coding(level, per_scope)
            started = time.monotonic()
            analysis = cpr.analyze_coding(document)
            elapsed = time.monotonic() - started
            total = sum(per_scope.values())
            self.assertLess(elapsed, 30, f"{level} analysis unexpectedly slow")
            self.assertEqual(total, analysis["denominators"]["N_union_mixed_window"])
            self.assertEqual(
                per_scope["category_30d"], analysis["denominators"]["N_category_30d"]
            )
            for rank in range(1, 4):
                self.assertEqual(
                    per_scope[f"segment_{rank}_90d"],
                    analysis["denominators"][f"N_segment_{rank}_90d"],
                )
            need = next(
                item
                for item in analysis["union_analysis"]["need_stats"]
                if item["need_code"] == "secure_hold"
            )
            self.assertEqual(total, need["voice_count"])
            self.assertEqual(1.0, need["voice_share"])
            analyses[level] = analysis
            documents[level] = document

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            coding_path = root / "social_voice_coding.json"
            analysis_path = root / "social_voice_analysis.json"
            output = root / "report.html"
            coding_path.write_text(
                json.dumps(documents["deep"], ensure_ascii=False), encoding="utf-8"
            )
            analysis = cpr.analyze_coding(
                documents["deep"],
                coding_path=coding_path,
                output_path=analysis_path,
                report_path=output,
            )
            analysis_path.write_text(
                json.dumps(analysis, ensure_ascii=False), encoding="utf-8"
            )
            result = cpr.render_report(
                analysis,
                SKILL_ROOT / "assets" / "consumer_product_report.template.html",
                output,
                [],
                "消费者声音与产品创意开发报告",
                analysis_path=analysis_path,
            )
            html = output.read_text(encoding="utf-8")
            self.assertEqual("passed", result["offline_dependency_check"])
            self.assertIn("5,000", html)
            self.assertIn("需要更强的加固", html)
            self.assertNotIn("同窗口对比", html)
            self.assertIn("四路样本目标与实际完成度", html)
            self.assertIn("实际采集耗时", html)
            self.assertIn("YouTube配额", html)
            for forbidden in ("来源状态", "证据ID", "证据类型计数", "source_statuses"):
                self.assertNotIn(forbidden, html)

    def test_offline_validator_rejects_active_or_embedded_html_and_requires_csp(self) -> None:
        strict_csp = (
            '<meta http-equiv="Content-Security-Policy" content="'
            + cpr.REQUIRED_REPORT_CSP
            + '">'
        )
        unsafe = {
            "script": "<script>document.body.textContent='x'</script>",
            "iframe": '<iframe srcdoc="<p>x</p>"></iframe>',
            "form": '<form action="#"><input></form>',
            "base": '<base href="https://example.com/">',
            "event": '<div onload="alert(1)">x</div>',
        }
        for label, fragment in unsafe.items():
            with self.subTest(label=label):
                self.assertTrue(cpr._offline_dependency_errors(strict_csp + fragment))
        self.assertIn(
            "HTML必须包含固定严格Content-Security-Policy",
            cpr._offline_dependency_errors("<html><head></head><body>safe</body></html>"),
        )
        self.assertEqual([], cpr._offline_dependency_errors(strict_csp + "<p>safe</p>"))


class HardDedupeTests(unittest.TestCase):
    def test_same_message_id_merges_and_schema_allows_trace(self) -> None:
        unique, report = cpr._deduplicate_voices(
            [_voice("voice-1", content_id="comment-1"), _voice("voice-2", content_id="comment-1")]
        )
        self.assertEqual(1, len(unique))
        self.assertEqual(["voice-2"], unique[0]["merged_voice_ids"])
        self.assertEqual(1, report["duplicate_count"])
        schema = json.loads((SKILL_ROOT / "references" / "social_voice_coding.schema.json").read_text())
        self.assertIn("merged_voice_ids", schema["$defs"]["voice"]["properties"])

    def test_same_text_different_ids_or_authors_stays_separate(self) -> None:
        unique, report = cpr._deduplicate_voices(
            [
                _voice("voice-1", content_id="comment-1", author="author-a", quote="same"),
                _voice("voice-2", content_id="comment-2", author="author-b", quote="same"),
            ]
        )
        self.assertEqual(2, len(unique))
        self.assertEqual(0, report["duplicate_count"])

    def test_only_comment_permalink_can_dedupe_by_url(self) -> None:
        comment_url = "https://reddit.com/r/test/comments/post/slug/comment-1"
        unique, _ = cpr._deduplicate_voices(
            [_voice("voice-1", content_id=None, url=comment_url), _voice("voice-2", content_id=None, url=comment_url)]
        )
        self.assertEqual(1, len(unique))
        unique, _ = cpr._deduplicate_voices(
            [_voice("voice-1", content_id="comment-1", url=comment_url), _voice("voice-2", content_id=None, url=comment_url)]
        )
        self.assertEqual(1, len(unique))
        unique, _ = cpr._deduplicate_voices(
            [_voice("voice-1", content_id="comment-1", url=comment_url), _voice("voice-2", content_id="comment-2", url=comment_url)]
        )
        self.assertEqual(2, len(unique))

        parent_url = "https://reddit.com/r/test/comments/post/slug/"
        unique, _ = cpr._deduplicate_voices(
            [
                _voice("voice-3", content_id=None, url=parent_url, author="a", published_at="2026-08-01T01:00:00Z"),
                _voice("voice-4", content_id=None, url=parent_url, author="b", published_at="2026-08-01T02:00:00Z"),
            ]
        )
        self.assertEqual(2, len(unique))

    def test_fallback_requires_full_exact_composite(self) -> None:
        first = _voice("voice-1", content_id=None)
        same = _voice("voice-2", content_id=None)
        different_author = _voice("voice-3", content_id=None, author="author-b")
        unique, _ = cpr._deduplicate_voices([first, same, different_author])
        self.assertEqual(2, len(unique))


class PresentationTests(unittest.TestCase):
    def _timed_finalize_fixture(
        self, root: Path, *, total_elapsed_seconds: float = 0.0
    ) -> tuple[object, Path, Path, dict, bytes]:
        collector = cpr._load_consumer_voice_collector()
        run_dir = root / "consumer_voice_test"
        run_dir.mkdir(parents=True)
        (root / "market_opportunity").mkdir(parents=True)
        db_path = run_dir / "collector.sqlite3"
        with collector.CollectorStore(db_path) as store:
            store.create_task(
                "timed-finalize-test",
                "car phone holder",
                "quick",
                "2026-08-05T00:00:00Z",
                [],
                project_dir=root,
                run_dir=run_dir,
                task_id="task-1",
            )
            store.update_task(
                "task-1",
                status="collection_completed",
                total_elapsed_seconds=total_elapsed_seconds,
                updated_at=collector.iso_utc(),
            )
            phase = store.begin_timing_phase(
                "task-1",
                "manifest_finalize",
                "workflow-finalize",
                phase_run_id="manifest-phase-1",
                boot_id="boot-a",
                monotonic_ns=0,
            )
            collector.write_json(
                run_dir / "collection_receipt.json",
                collector.build_receipt(store, "task-1"),
            )
        manifest_path = root / "project_manifest.json"
        cpr._atomic_write_json(
            manifest_path,
            {
                "project_id": "preserve-me",
                "artifacts": {"market_dashboard": "market_opportunity/dashboard.html"},
                "status": {"market_research": "ready"},
            },
        )
        return collector, run_dir, manifest_path, phase, manifest_path.read_bytes()

    @staticmethod
    def _fake_manifest_finalize(
        manifest_path: Path,
        coding_path: Path,
        analysis_path: Path,
        report_path: Path,
        status: str,
    ) -> dict:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        document.setdefault("artifacts", {}).update(
            {
                "consumer_voice_coding": str(coding_path),
                "consumer_voice_analysis": str(analysis_path),
                "consumer_product_report_html": str(report_path),
            }
        )
        document.setdefault("status", {})["consumer_product_discovery"] = status
        cpr._atomic_write_json(manifest_path, document)
        return {
            "status": "updated",
            "manifest": str(manifest_path),
            "consumer_product_discovery": status,
            "artifact_keys": [
                "consumer_voice_coding",
                "consumer_voice_analysis",
                "consumer_product_report_html",
            ],
        }

    @staticmethod
    def _sequence_clock(*values: int):
        remaining = iter(values)
        return lambda: next(remaining)

    def test_timed_manifest_finalize_commits_after_phase_end_and_replays_idempotently(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            collector, run_dir, manifest_path, phase, _ = self._timed_finalize_fixture(root)
            kwargs = {
                "manifest_path": manifest_path,
                "coding_path": run_dir / "social_voice_coding.json",
                "analysis_path": run_dir / "social_voice_analysis.json",
                "report_path": root / "market_opportunity" / "report.html",
                "status": "ready",
                "collector_run_dir": run_dir,
                "phase_run_id": phase["phase_run_id"],
                "event_id": "manifest-event-1",
                "_collector_module": collector,
                "_boot_id": "boot-a",
            }
            with mock.patch.object(
                cpr, "finalize_manifest", side_effect=self._fake_manifest_finalize
            ):
                result = cpr.finalize_manifest_timed(
                    **kwargs, _monotonic_ns=self._sequence_clock(0, 2_000_000_000)
                )
                replay = cpr.finalize_manifest_timed(
                    **kwargs,
                    _monotonic_ns=lambda: self.fail(
                        "幂等重放不应再次读取计时钟或重写manifest"
                    ),
                )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual("ready", manifest["status"]["consumer_product_discovery"])
            self.assertEqual(str(manifest_path.resolve()), result["manifest"])
            self.assertFalse(result["replayed"])
            self.assertTrue(replay["replayed"])
            with collector.CollectorStore(run_dir / "collector.sqlite3") as store:
                task = store.task_row("task-1")
                self.assertEqual("completed", task["status"])
                self.assertIsNotNone(task["finished_at"])
                intent = store.manifest_finalize_intent("task-1", phase["phase_run_id"])
                self.assertEqual("committed", intent["state"])
                self.assertEqual(
                    1,
                    store.connection.execute(
                        "SELECT COUNT(*) FROM timing_events WHERE event_id='manifest-event-1'"
                    ).fetchone()[0],
                )

    def test_timed_manifest_finalize_rejects_cross_run_lineage_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            collector, run_dir, manifest_path, phase, previous = self._timed_finalize_fixture(root)
            with mock.patch.object(
                cpr, "finalize_manifest", side_effect=self._fake_manifest_finalize
            ) as finalize:
                with self.assertRaises(cpr.ContractError) as caught:
                    cpr.finalize_manifest_timed(
                        manifest_path,
                        root / "other-run" / "social_voice_coding.json",
                        run_dir / "social_voice_analysis.json",
                        root / "market_opportunity" / "report.html",
                        "ready",
                        run_dir,
                        phase["phase_run_id"],
                        "manifest-event-cross-run",
                        _collector_module=collector,
                        _boot_id="boot-a",
                        _monotonic_ns=lambda: 0,
                    )
            finalize.assert_not_called()
            self.assertIn("血缘不一致", str(caught.exception))
            self.assertEqual(previous, manifest_path.read_bytes())
            with collector.CollectorStore(run_dir / "collector.sqlite3") as store:
                self.assertIsNone(
                    store.manifest_finalize_intent("task-1", phase["phase_run_id"])
                )

    def test_timed_manifest_finalize_rejects_receipt_from_another_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            collector, run_dir, manifest_path, phase, previous = self._timed_finalize_fixture(root)
            receipt_path = run_dir / "collection_receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["task_id"] = "wrong-task"
            collector.write_json(receipt_path, receipt)
            with mock.patch.object(
                cpr, "finalize_manifest", side_effect=self._fake_manifest_finalize
            ) as finalize:
                with self.assertRaises(cpr.ContractError) as caught:
                    cpr.finalize_manifest_timed(
                        manifest_path,
                        run_dir / "social_voice_coding.json",
                        run_dir / "social_voice_analysis.json",
                        root / "market_opportunity" / "report.html",
                        "ready",
                        run_dir,
                        phase["phase_run_id"],
                        "manifest-event-wrong-receipt",
                        _collector_module=collector,
                        _boot_id="boot-a",
                        _monotonic_ns=lambda: 0,
                    )
            finalize.assert_not_called()
            self.assertIn("task_id", " ".join(caught.exception.details))
            self.assertEqual(previous, manifest_path.read_bytes())

    def test_post_commit_receipt_failure_is_recoverable_without_manifest_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            collector, run_dir, manifest_path, phase, _ = self._timed_finalize_fixture(root)
            kwargs = {
                "manifest_path": manifest_path,
                "coding_path": run_dir / "social_voice_coding.json",
                "analysis_path": run_dir / "social_voice_analysis.json",
                "report_path": root / "market_opportunity" / "report.html",
                "status": "ready",
                "collector_run_dir": run_dir,
                "phase_run_id": phase["phase_run_id"],
                "event_id": "manifest-event-receipt-recovery",
                "_collector_module": collector,
                "_boot_id": "boot-a",
            }
            with mock.patch.object(
                cpr, "finalize_manifest", side_effect=self._fake_manifest_finalize
            ), mock.patch.object(
                collector, "write_json", side_effect=OSError("simulated receipt disk failure")
            ):
                with self.assertRaises(cpr.ContractError) as caught:
                    cpr.finalize_manifest_timed(
                        **kwargs, _monotonic_ns=self._sequence_clock(0, 1_000_000_000)
                    )
            self.assertIn("manifest已经提交", str(caught.exception))
            self.assertEqual(
                "ready",
                json.loads(manifest_path.read_text(encoding="utf-8"))["status"][
                    "consumer_product_discovery"
                ],
            )
            with collector.CollectorStore(run_dir / "collector.sqlite3") as store:
                self.assertEqual("completed", store.task_row("task-1")["status"])
                self.assertEqual(
                    "committed",
                    store.manifest_finalize_intent("task-1", phase["phase_run_id"])["state"],
                )

            # The same committed phase/event is a repair operation: it does not
            # rewrite the manifest or consume another timing event, but replaces
            # the stale pre-commit receipt with the authoritative final receipt.
            with mock.patch.object(
                cpr, "finalize_manifest", side_effect=self._fake_manifest_finalize
            ):
                replay = cpr.finalize_manifest_timed(
                    **kwargs,
                    _monotonic_ns=lambda: self.fail("committed replay must not read the clock"),
                )
            self.assertTrue(replay["replayed"])
            healed = json.loads(
                (run_dir / "collection_receipt.json").read_text(encoding="utf-8")
            )
            self.assertEqual("completed", healed["status"])

    def test_timed_manifest_finalize_deadline_restores_old_manifest_and_does_not_complete(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            collector, run_dir, manifest_path, phase, previous = self._timed_finalize_fixture(
                root, total_elapsed_seconds=3_599.0
            )
            with mock.patch.object(
                cpr, "finalize_manifest", side_effect=self._fake_manifest_finalize
            ):
                with self.assertRaises(cpr.ContractError) as caught:
                    cpr.finalize_manifest_timed(
                        manifest_path,
                        run_dir / "social_voice_coding.json",
                        run_dir / "social_voice_analysis.json",
                        root / "market_opportunity" / "report.html",
                        "ready",
                        run_dir,
                        phase["phase_run_id"],
                        "manifest-event-deadline",
                        _collector_module=collector,
                        _boot_id="boot-a",
                        _monotonic_ns=self._sequence_clock(0, 2_000_000_000),
                    )
            self.assertIn("恢复旧manifest", str(caught.exception))
            self.assertEqual(previous, manifest_path.read_bytes())
            with collector.CollectorStore(run_dir / "collector.sqlite3") as store:
                task = store.task_row("task-1")
                self.assertEqual("collection_completed", task["status"])
                self.assertIsNone(task["finished_at"])
                self.assertEqual("total_deadline", task["stop_reason"])
                intent = store.manifest_finalize_intent("task-1", phase["phase_run_id"])
                self.assertEqual("rolled_back", intent["state"])

    def test_timed_manifest_finalize_crash_is_recovered_by_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            collector, run_dir, manifest_path, phase, previous = self._timed_finalize_fixture(root)
            with mock.patch.object(
                cpr, "finalize_manifest", side_effect=self._fake_manifest_finalize
            ):
                with self.assertRaises(SystemExit):
                    cpr.finalize_manifest_timed(
                        manifest_path,
                        run_dir / "social_voice_coding.json",
                        run_dir / "social_voice_analysis.json",
                        root / "market_opportunity" / "report.html",
                        "ready",
                        run_dir,
                        phase["phase_run_id"],
                        "manifest-event-crash",
                        _collector_module=collector,
                        _boot_id="boot-a",
                        _monotonic_ns=self._sequence_clock(0),
                        _after_candidate_write=lambda: (_ for _ in ()).throw(SystemExit(9)),
                    )
            self.assertEqual(
                "ready",
                json.loads(manifest_path.read_text(encoding="utf-8"))["status"][
                    "consumer_product_discovery"
                ],
            )
            receipt_args = collector.build_parser().parse_args(
                ["receipt", "--run-dir", str(run_dir)]
            )
            receipt = collector.execute(receipt_args)
            self.assertEqual(1, receipt["manifest_finalize_recovery"]["recovered_count"])
            self.assertEqual(previous, manifest_path.read_bytes())
            with collector.CollectorStore(run_dir / "collector.sqlite3") as store:
                task = store.task_row("task-1")
                self.assertEqual("collection_completed", task["status"])
                self.assertIsNone(task["finished_at"])
                intent = store.manifest_finalize_intent("task-1", phase["phase_run_id"])
                self.assertEqual("rolled_back", intent["state"])

    def test_next_timed_finalize_recovers_crash_intent_before_requiring_new_phase(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            collector, run_dir, manifest_path, phase, previous = self._timed_finalize_fixture(root)
            arguments = (
                manifest_path,
                run_dir / "social_voice_coding.json",
                run_dir / "social_voice_analysis.json",
                root / "market_opportunity" / "report.html",
                "ready",
                run_dir,
                phase["phase_run_id"],
                "manifest-event-crash-next",
            )
            with mock.patch.object(
                cpr, "finalize_manifest", side_effect=self._fake_manifest_finalize
            ):
                with self.assertRaises(SystemExit):
                    cpr.finalize_manifest_timed(
                        *arguments,
                        _collector_module=collector,
                        _boot_id="boot-a",
                        _monotonic_ns=self._sequence_clock(0),
                        _after_candidate_write=lambda: (_ for _ in ()).throw(SystemExit(9)),
                    )
                with self.assertRaises(cpr.ContractError):
                    cpr.finalize_manifest_timed(
                        *arguments,
                        _collector_module=collector,
                        _boot_id="boot-a",
                        _monotonic_ns=lambda: 0,
                    )
            self.assertEqual(previous, manifest_path.read_bytes())
            with collector.CollectorStore(run_dir / "collector.sqlite3") as store:
                intent = store.manifest_finalize_intent("task-1", phase["phase_run_id"])
                self.assertEqual("rolled_back", intent["state"])
                self.assertEqual(
                    "abandoned",
                    store.connection.execute(
                        "SELECT status FROM timing_sessions WHERE phase_run_id=?",
                        (phase["phase_run_id"],),
                    ).fetchone()[0],
                )

    def test_timed_manifest_finalize_exception_rolls_back_before_returning_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            collector, run_dir, manifest_path, phase, previous = self._timed_finalize_fixture(root)
            with mock.patch.object(
                cpr, "finalize_manifest", side_effect=self._fake_manifest_finalize
            ):
                with self.assertRaises(cpr.ContractError):
                    cpr.finalize_manifest_timed(
                        manifest_path,
                        run_dir / "social_voice_coding.json",
                        run_dir / "social_voice_analysis.json",
                        root / "market_opportunity" / "report.html",
                        "ready",
                        run_dir,
                        phase["phase_run_id"],
                        "manifest-event-error",
                        _collector_module=collector,
                        _boot_id="boot-a",
                        _monotonic_ns=self._sequence_clock(0, 1_000_000_000),
                        _after_candidate_write=lambda: (_ for _ in ()).throw(
                            RuntimeError("simulated finalize failure")
                        ),
                    )
            self.assertEqual(previous, manifest_path.read_bytes())
            with collector.CollectorStore(run_dir / "collector.sqlite3") as store:
                task = store.task_row("task-1")
                self.assertEqual("collection_completed", task["status"])
                self.assertIsNone(task["finished_at"])
                intent = store.manifest_finalize_intent("task-1", phase["phase_run_id"])
                self.assertEqual("rolled_back", intent["state"])

    def test_timed_manifest_finalize_zero_time_preflight_makes_no_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            collector, run_dir, manifest_path, phase, previous = self._timed_finalize_fixture(root)
            with collector.CollectorStore(run_dir / "collector.sqlite3") as store:
                store.update_task(
                    "task-1",
                    total_elapsed_seconds=3_600.0,
                    updated_at=collector.iso_utc(),
                )
            with mock.patch.object(
                cpr, "finalize_manifest", side_effect=self._fake_manifest_finalize
            ) as finalize:
                with self.assertRaises(cpr.ContractError):
                    cpr.finalize_manifest_timed(
                        manifest_path,
                        run_dir / "social_voice_coding.json",
                        run_dir / "social_voice_analysis.json",
                        root / "market_opportunity" / "report.html",
                        "ready",
                        run_dir,
                        phase["phase_run_id"],
                        "manifest-event-zero",
                        _collector_module=collector,
                        _boot_id="boot-a",
                        _monotonic_ns=lambda: 0,
                    )
            finalize.assert_not_called()
            self.assertEqual(previous, manifest_path.read_bytes())
            with collector.CollectorStore(run_dir / "collector.sqlite3") as store:
                self.assertEqual(
                    0,
                    store.connection.execute(
                        "SELECT COUNT(*) FROM manifest_finalize_intents WHERE task_id='task-1'"
                    ).fetchone()[0],
                )

    def test_final_receipt_time_can_only_advance_from_rendered_analysis_snapshot(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            analysis_path = Path(temporary) / "social_voice_analysis.json"
            analysis_path.write_text(
                json.dumps(
                    {
                        "collection_receipt": {
                            "time_usage_minutes": {"collection": 20.0, "total": 35.0}
                        }
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                [],
                cpr._final_receipt_snapshot_errors(
                    analysis_path,
                    {"time_usage_minutes": {"collection": 20.0, "total": 35.5}},
                ),
            )
            errors = cpr._final_receipt_snapshot_errors(
                analysis_path,
                {"time_usage_minutes": {"collection": 19.9, "total": 34.9}},
            )
            self.assertEqual(2, len(errors))
            self.assertTrue(all("小于HTML快照" in error for error in errors))

    def test_html_hides_internal_keys_and_caps_representative_evidence(self) -> None:
        voices = [
            {
                "voice_id": f"voice-{index}",
                "platform": "reddit",
                "published_at": "2026-08-01T00:00:00Z",
                "normalized_url": f"https://example.com/comment/{index}",
                "excerpt": f"quote {index}",
                "summary_zh": f"摘要 {index}",
                "community": "test",
            }
            for index in range(6)
        ]
        rendered = cpr._render_evidence_appendix({"limitations": []}, {"voices": voices})
        self.assertEqual(3, rendered.count('class="evidence-item"'))
        self.assertNotIn("voice-", rendered)
        self.assertIn("完整证据保留在JSON", rendered)

        structured = cpr._structured_html({"prompt_text": "secret", "description": "业务说明"})
        self.assertNotIn("prompt_text", structured)
        self.assertNotIn("secret", structured)
        self.assertIn("业务说明", structured)

    def test_kano_labels_are_chinese(self) -> None:
        for code in ("M", "O", "A", "I", "R"):
            label = cpr._kano_label(code)
            self.assertNotIn(code + " ·", label)
            self.assertTrue(label.endswith("型"))

    def test_unknown_scene_and_persona_codes_use_chinese_safe_fallback(self) -> None:
        item = {
            "code": "unmapped_internal_code",
            "label": "unmapped_internal_code",
            "voice_count": 3,
            "voice_share": 0.3,
            "author_count": 3,
            "thread_count": 2,
            "platform_count": 1,
            "confidence": "low",
        }
        scene_html = cpr._render_ranked_items(
            "场景", [item], presentation_kind="scene"
        )
        persona_html = cpr._render_ranked_items(
            "人群", [item], presentation_kind="persona"
        )
        self.assertIn("未归类使用场景", scene_html)
        self.assertIn("未归类消费者类型", persona_html)
        self.assertNotIn("unmapped_internal_code", scene_html + persona_html)

    def test_free_text_cannot_leak_hidden_internal_labels(self) -> None:
        rendered = cpr._structured_html(
            {
                "description": (
                    "证据ID、Evidence IDs、来源状态、source_statuses 和证据类型计数"
                    "均不能作为面向业务人员的字段展示。"
                )
            }
        )
        for forbidden in (
            "证据ID",
            "证据 ID",
            "Evidence IDs",
            "来源状态",
            "source_statuses",
            "证据类型计数",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_executive_summary_uses_real_sample_gates(self) -> None:
        base = {
            "schema_version": "2.0.0",
            "research_plan": cpr._default_research_plan("quick"),
            "denominators": {
                "N_category_30d": 200,
                "N_segment_1_90d": 100,
                "N_segment_2_90d": 100,
                "N_segment_3_90d": 100,
                "N_union_mixed_window": 500,
            },
            "scope_quality": [{"scope_id": "union_mixed_window", "platform_count": 3, "confidence": "high", "valid_voice_count": 500}],
            "segments": [],
            "segment_analyses": [],
            "category_30d": {},
            "product_concepts": [],
            "report_artifacts": {"status": "ready"},
        }
        ready_html = cpr._render_executive_summary(base)
        self.assertIn("均达到门槛", ready_html)
        self.assertNotIn("平台覆盖和样本强度仍不足", ready_html)
        self.assertIn("<strong>高</strong>", ready_html)

        partial = copy.deepcopy(base)
        partial["denominators"]["N_union_mixed_window"] = 499
        partial_html = cpr._render_executive_summary(partial)
        self.assertIn("当前仍未达到", partial_html)
        self.assertIn("总有效留言（499/500，缺1条）", partial_html)
        self.assertIn("<strong>低</strong>", partial_html)

    def test_partial_reasons_and_receipt_are_visible_without_internal_fields(self) -> None:
        coding = _synthetic_coding(
            "quick",
            {
                "category_30d": 199,
                "segment_1_90d": 100,
                "segment_2_90d": 100,
                "segment_3_90d": 100,
            },
        )
        analysis = cpr.analyze_coding(coding)
        analysis["collection_receipt"]["time_usage_minutes"].update(
            {"collection": 34.2, "total": 51.8}
        )
        analysis["collection_receipt"]["youtube_quota_and_cost"].update(
            {
                "usage_recorded": True,
                "daily_quota_limit": 10000,
                "quota_units": 640,
                "request_entries": 12,
                "cost_classification": "quota_only",
                "interpretation_zh": "YouTube Data API只记录配额用量，没有按请求计美元费用；配额单位不是美元。",
            }
        )
        analysis["report_artifacts"]["status"] = "partial"

        executive = cpr._render_executive_summary(analysis)
        methodology = cpr._render_windows_and_sources(analysis)
        combined = executive + methodology
        self.assertIn("全品类30天（199/200，缺1条）", executive)
        self.assertIn("本轮未达标", executive)
        for expected in (
            "本轮执行回执",
            "快速研究",
            "499 / 500–1,000 条有效留言",
            "199<small> / 200–400 条",
            "平台门槛",
            "采集耗时",
            "任务耗时",
            "停止原因",
            "达到档位上限",
        ):
            self.assertIn(expected, executive)
        for expected in (
            "四路样本目标与实际完成度",
            "40.0%",
            "20.0%",
            "34.2",
            "51.8",
            "首次API准备等待",
            "640 / 10,000",
            "配额单位不是美元",
            "全品类30天（199/200，缺1条）",
            "预计完成时间",
            "35–55",
            "任务硬上限",
            "逐平台样本覆盖",
            "抓取候选",
            "抓取有效率",
            "有效样本贡献",
            "Reddit",
            "YouTube",
            "X",
            "YouTube通道直接费用",
            "不代表全任务总成本",
            "只合并同一底层公开留言",
            "报告内耗时为生成时快照",
            "collection_receipt.json",
        ):
            self.assertIn(expected, methodology)
        for forbidden in ("来源状态", "证据ID", "证据类型计数", "source_statuses"):
            self.assertNotIn(forbidden, combined)

    def test_concept_cards_show_complete_image_prompt_in_chinese(self) -> None:
        analysis = cpr.analyze_coding(_coding_v2())
        prompt = analysis["product_concepts"][0]["image_prompt"]
        prompt.update(
            {
                "prompt_text": "FULL_PROMPT_SENTINEL：重型卡车驾驶舱内的加固手机支架。",
                "target_product": "重型卡车手机支架",
                "target_consumer": "长途货车司机",
                "use_scenario": "连续颠簸道路导航",
                "key_structure": "双点机械夹持与减振底座",
                "technical_constraints": ["不遮挡驾驶视线", "单手装卸"],
                "scale_and_proportion": "真实车载产品比例",
                "materials": ["铝合金", "玻纤增强尼龙"],
                "cmf": "哑光黑与安全橙点缀",
                "camera": "驾驶员侧45度视角",
                "lighting": "自然驾驶舱光线",
                "background": "重型卡车驾驶舱",
                "must_show": ["夹持结构", "减振底座"],
                "forbidden": ["虚构认证标识", "不可读文字"],
            }
        )
        rendered = cpr._render_concepts(analysis, {})
        for expected in (
            "查看完整概念图提示词",
            "FULL_PROMPT_SENTINEL",
            "目标产品",
            "目标消费者",
            "使用场景",
            "关键结构",
            "技术约束",
            "尺寸与比例",
            "材质",
            "颜色与表面",
            "镜头角度",
            "光线",
            "背景",
            "必须展示",
            "禁止出现",
            "驾驶员侧45度视角",
            "虚构认证标识",
        ):
            self.assertIn(expected, rendered)

    def test_print_css_expands_closed_concept_prompt_details(self) -> None:
        template = (
            SKILL_ROOT / "assets" / "consumer_product_report.template.html"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "details:not([open])::details-content",
            template,
        )
        self.assertIn("content-visibility: visible !important", template)

    def test_total_deadline_is_visible_and_blocks_ready(self) -> None:
        analysis = cpr.analyze_coding(_coding_v2())
        analysis["collection_receipt"]["available"] = True
        analysis["collection_receipt"]["deadline_status"].update(
            {
                "recorded": True,
                "deadline_exceeded": True,
                "finalization_only": True,
                "action": "finalize_over_budget",
            }
        )
        analysis["collection_receipt"]["time_usage_minutes"]["total"] = 60.2
        analysis["report_artifacts"]["status"] = "partial"
        executive = cpr._render_executive_summary(analysis)
        methodology = cpr._render_windows_and_sources(analysis)
        self.assertIn("完整任务已达到总时间上限", executive)
        self.assertIn("已达到总时间上限", methodology)
        self.assertTrue(
            any("总时间上限" in error for error in cpr._ready_gate_errors(analysis))
        )

    def test_finalization_reserve_stops_expansion_but_does_not_force_partial(self) -> None:
        analysis = cpr.analyze_coding(_coding_v2())
        analysis["collection_receipt"]["available"] = True
        analysis["collection_receipt"]["time_usage_minutes"].update(
            {"collection": 35, "total": 55}
        )
        analysis["collection_receipt"]["deadline_status"].update(
            {
                "recorded": True,
                "deadline_exceeded": False,
                "finalization_only": True,
                "action": "finalize_now",
            }
        )
        analysis["report_artifacts"]["status"] = "ready"
        self.assertFalse(
            any("时间" in error or "收尾" in error for error in cpr._ready_gate_errors(analysis))
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            coding_path = root / "social_voice_coding.json"
            coding_path.write_text(json.dumps(_coding_v2()), encoding="utf-8")
            analysis["project"]["coding_artifact"] = str(coding_path)
            (root / "collection_receipt.json").write_text(
                json.dumps(
                    _runtime_collection_receipt(
                        root,
                        collection=35,
                        total=55,
                        finalization_only=True,
                        action="finalize_now",
                    )
                ),
                encoding="utf-8",
            )
            refreshed, changed = cpr._refresh_analysis_runtime_receipt(analysis)
            self.assertTrue(changed)
            self.assertEqual("ready", refreshed["report_artifacts"]["status"])

    def test_business_copy_explains_hard_identity_counting_without_semantic_merge(self) -> None:
        analysis = cpr.analyze_coding(_coding_v2())
        combined = (
            cpr._render_executive_summary(analysis)
            + cpr._render_scope_summary(analysis)
            + cpr._render_windows_and_sources(analysis)
        )
        for expected in (
            "计数口径",
            "不同评论即使语义相同，也分别计数",
            "联合硬身份唯一语料",
            "仅合并同一底层留言",
            "初步硬身份唯一记录",
            "跨查询同一留言合并后",
        ):
            self.assertIn(expected, combined)
        for ambiguous in ("联合去重语料", "条有效去重留言", "技术去重后记录"):
            self.assertNotIn(ambiguous, combined)

    def test_final_render_refreshes_latest_runtime_receipt_and_downgrades_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            coding_path = root / "social_voice_coding.json"
            coding = _coding_v2()
            coding_path.write_text(json.dumps(coding), encoding="utf-8")
            analysis = cpr.analyze_coding(coding, coding_path=coding_path)
            analysis["report_artifacts"]["status"] = "ready"
            (root / "collection_receipt.json").write_text(
                json.dumps(
                    _runtime_collection_receipt(
                        root,
                        collection=35,
                        total=60.1,
                        deadline_exceeded=True,
                        finalization_only=True,
                        action="finalize_over_budget",
                    )
                ),
                encoding="utf-8",
            )
            refreshed, changed = cpr._refresh_analysis_runtime_receipt(analysis)
            self.assertTrue(changed)
            self.assertEqual("total_deadline", refreshed["stop_reason"])
            self.assertEqual("partial", refreshed["report_artifacts"]["status"])
            self.assertEqual(60.1, refreshed["collection_receipt"]["time_usage_minutes"]["total"])

    def test_ready_gate_enforces_total_routes_and_platforms(self) -> None:
        analysis = {
            "schema_version": "2.0.0",
            "research_plan": cpr._default_research_plan("quick"),
            "denominators": {
                "N_category_30d": 0,
                "N_segment_1_90d": 0,
                "N_segment_2_90d": 0,
                "N_segment_3_90d": 0,
                "N_union_mixed_window": 0,
            },
            "scope_quality": [{"scope_id": "union_mixed_window", "platform_count": 1}],
            "product_concepts": [],
            "segments": [],
            "supply_validation": [],
            "union_analysis": {},
            "report_artifacts": {},
        }
        errors = cpr._ready_gate_errors(analysis)
        self.assertTrue(any("有效留言总量不足" in item for item in errors))
        self.assertEqual(4, sum("有效留言不足" in item for item in errors))
        self.assertTrue(any("有效平台不足" in item for item in errors))

    def test_manifest_update_preserves_existing_keys_and_dashboard_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "project_manifest.json"
            dashboard = root / "market_opportunity" / "市场机会深挖看板.html"
            dashboard.parent.mkdir(parents=True)
            dashboard.write_bytes(b"<html>immutable dashboard</html>")
            before_sha = cpr.hashlib.sha256(dashboard.read_bytes()).hexdigest()
            original = {
                "project_id": "keep-me",
                "artifacts": {"market_dashboard": "market_opportunity/市场机会深挖看板.html"},
                "status": {"market_research": "ready"},
                "custom": {"nested": [1, 2, 3]},
            }
            manifest_path.write_text(
                json.dumps(original, ensure_ascii=False), encoding="utf-8"
            )
            result = cpr.finalize_manifest(
                manifest_path,
                root / "coding.json",
                root / "analysis.json",
                root / "report.html",
                "failed",
            )
            updated = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual("updated", result["status"])
            self.assertEqual("keep-me", updated["project_id"])
            self.assertEqual(original["custom"], updated["custom"])
            self.assertEqual("ready", updated["status"]["market_research"])
            self.assertEqual("failed", updated["status"]["consumer_product_discovery"])
            self.assertEqual(
                "market_opportunity/市场机会深挖看板.html",
                updated["artifacts"]["market_dashboard"],
            )
            self.assertEqual(
                before_sha,
                cpr.hashlib.sha256(dashboard.read_bytes()).hexdigest(),
            )
            self.assertEqual(before_sha, result["original_dashboard_sha256_verified"])

    def test_failed_finalize_still_rejects_dashboard_sha_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dashboard = root / "market_opportunity" / "市场机会深挖看板.html"
            dashboard.parent.mkdir(parents=True)
            dashboard.write_text("immutable", encoding="utf-8")
            manifest_path = root / "project_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "artifacts": {
                            "market_opportunity_html": {
                                "path": "market_opportunity/市场机会深挖看板.html",
                                "sha256": "0" * 64,
                            }
                        },
                        "status": {},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(cpr.ContractError) as caught:
                cpr.finalize_manifest(
                    manifest_path,
                    root / "coding.json",
                    root / "analysis.json",
                    root / "report.html",
                    "failed",
                )
            self.assertIn("SHA-256", str(caught.exception))


class ReportHardeningTests(unittest.TestCase):
    def test_v2_recursively_rejects_segment_subwindows_in_every_analysis_layer(self) -> None:
        base = cpr.analyze_coding(_coding_v2())
        variants: list[tuple[str, dict]] = []

        union_classification = copy.deepcopy(base)
        union_classification["union_analysis"]["kano_differences"] = [
            {
                "need_code": "secure_hold",
                "classifications": [
                    {"scope_id": "category_30d", "classification": "M"},
                    {
                        "scope_id": "segment_1_recent_30d",
                        "classification": "A",
                    },
                ],
                "rationale": "测试深层分类范围",
                "evidence_origins": [],
                "confidence": "low",
            }
        ]
        variants.append(("union kano classification", union_classification))

        concept_origin = copy.deepcopy(base)
        concept_origin["product_concepts"][0]["evidence_origins"][0][
            "origin_type"
        ] = "segment_days_31_90"
        variants.append(("concept evidence origin", concept_origin))

        concept_kano = copy.deepcopy(base)
        concept_kano["product_concepts"][0]["kano_mapping"] = [
            {
                "need_code": "secure_hold",
                "classification": "M",
                "scope_id": "segment_2_recent_30d",
                "design_response": "测试",
            }
        ]
        variants.append(("concept kano scope", concept_kano))

        moscow_origin = copy.deepcopy(base)
        moscow_origin["product_concepts"][0]["moscow"]["must"][0][
            "evidence_origins"
        ][0]["origin_type"] = "segment_recent_30d"
        variants.append(("moscow evidence origin", moscow_origin))

        persistence_field = copy.deepcopy(base)
        persistence_field["segment_analyses"] = [
            {
                "segment_id": "segment_1_90d",
                "denominator_90d": 0,
                "need_stats_90d": [],
                "kano_90d": [],
                "satisfaction_90d": [],
                "dissatisfaction_90d": [],
                "use_scenes": [],
                "personas": [],
                "diy_workarounds": [],
                "new_needs": [],
                "need_persistence": [],
            }
        ]
        variants.append(("legacy persistence field", persistence_field))

        schema_path = SKILL_ROOT / "references" / "social_voice_analysis.schema.json"
        for label, document in variants:
            with self.subTest(layer=label):
                removed = cpr._v2_removed_analysis_field_errors(document)
                self.assertTrue(removed, label)
                with self.assertRaises(cpr.ContractError) as caught:
                    cpr._validate_against_schema(document, schema_path, "v2 analysis")
                self.assertTrue(
                    any("细分子窗口" in detail for detail in caught.exception.details),
                    caught.exception.details,
                )

        legacy = copy.deepcopy(concept_origin)
        legacy["schema_version"] = "1.0.0"
        cpr._validate_against_schema(legacy, schema_path, "v1 analysis")

    def test_ready_images_require_real_unique_files_and_concept_id_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = []
            for index, color in enumerate(((255, 0, 0), (0, 255, 0), (0, 0, 255)), start=1):
                path = root / f"concept_{index}.png"
                path.write_bytes(_png_bytes(*color))
                paths.append(path)
            images = cpr._parse_images(
                [f"concept_{index}={path}" for index, path in enumerate(paths, start=1)]
            )
            concepts = []
            for index, path in enumerate(paths, start=1):
                info = cpr._image_file_info(path)
                concepts.append(
                    {
                        "concept_id": f"concept_{index}",
                        "image_artifact": {
                            "status": "ok",
                            "path": str(path),
                            "mime_type": info["mime_type"],
                            "sha256": info["sha256"],
                            "embedded_as_data_uri": True,
                        },
                    }
                )
            analysis = {
                "project": {"project_root": str(root)},
                "product_concepts": concepts,
                "report_artifacts": {"image_paths": [str(path) for path in paths]},
            }
            html = "".join(
                f'<img data-concept-id="concept_{index}" src="{images[f"concept_{index}"]["data_uri"]}">'
                for index in range(1, 4)
            )
            self.assertEqual(
                [],
                cpr._ready_image_artifact_errors(
                    analysis,
                    images=images,
                    analysis_path=root / "analysis.json",
                    html_text=html,
                ),
            )

            swapped = dict(images)
            swapped["concept_1"], swapped["concept_2"] = (
                swapped["concept_2"],
                swapped["concept_1"],
            )
            self.assertTrue(
                any(
                    "传入的concept_1图片与其声明产物不一致" in error
                    for error in cpr._ready_image_artifact_errors(
                        analysis, images=swapped, analysis_path=root / "analysis.json"
                    )
                )
            )

            wrong_sha = copy.deepcopy(analysis)
            wrong_sha["product_concepts"][0]["image_artifact"]["sha256"] = "0" * 64
            self.assertTrue(
                any(
                    "SHA-256与真实图片文件不一致" in error
                    for error in cpr._ready_image_artifact_errors(
                        wrong_sha, analysis_path=root / "analysis.json"
                    )
                )
            )

            duplicate = copy.deepcopy(analysis)
            duplicate["product_concepts"][2]["image_artifact"] = copy.deepcopy(
                duplicate["product_concepts"][1]["image_artifact"]
            )
            duplicate["report_artifacts"]["image_paths"][2] = str(paths[1])
            duplicate_errors = cpr._ready_image_artifact_errors(
                duplicate, analysis_path=root / "analysis.json"
            )
            self.assertTrue(any("复用同一图片文件" in error for error in duplicate_errors))
            self.assertTrue(any("复用相同图片内容" in error for error in duplicate_errors))

            swapped_html = (
                f'<img data-concept-id="concept_1" src="{images["concept_2"]["data_uri"]}">'
                f'<img data-concept-id="concept_2" src="{images["concept_1"]["data_uri"]}">'
                f'<img data-concept-id="concept_3" src="{images["concept_3"]["data_uri"]}">'
            )
            self.assertTrue(
                any(
                    "HTML内嵌的concept_1图片SHA-256不一致" in error
                    for error in cpr._ready_image_artifact_errors(
                        analysis,
                        analysis_path=root / "analysis.json",
                        html_text=swapped_html,
                    )
                )
            )

            mismatched_extension = root / "not_really_jpeg.jpg"
            mismatched_extension.write_bytes(_png_bytes(1, 2, 3))
            with self.assertRaises(cpr.ContractError):
                cpr._parse_images([f"concept_1={mismatched_extension}"])

    def test_category_satisfaction_and_dissatisfaction_render_full_top10(self) -> None:
        def items(prefix: str) -> list[dict]:
            return [
                {
                    "label": f"{prefix}{index}",
                    "voice_count": 20 - index,
                    "voice_share": (20 - index) / 100,
                    "author_count": 10,
                    "thread_count": 5,
                    "platform_count": 3,
                    "confidence": "medium",
                }
                for index in range(1, 11)
            ]

        rendered = cpr._render_category(
            {
                "category_30d": {
                    "need_stats": [],
                    "dissatisfaction_top10": items("不满点"),
                    "satisfaction_top10": items("满意点"),
                    "kano": [],
                    "use_scenes": [],
                    "significant_recent_topics": [],
                    "current_new_needs": [],
                    "reverse_needs": [],
                }
            }
        )
        self.assertEqual(20, rendered.count('class="insight-row"'))
        self.assertIn("不满点10", rendered)
        self.assertIn("满意点10", rendered)

    def test_all_user_facing_enum_values_have_chinese_labels(self) -> None:
        expected = {
            "in_progress": "进行中",
            "completed": "已完成",
            "blocked": "受阻",
            "user_and_scenario_test": "用户与场景测试",
            "few_listings": "仅发现少量供给",
            "verified_rare_supply": "已验证为稀缺供给",
            "no_verified_supply": "当前覆盖范围内未验证到供给",
            "supply_gap_hypothesis": "供给缺口假设",
            "validated_new_need": "已验证的新需求",
            "agent_design_concept": "Agent设计创意",
            "top_30_by_sales": "销量前30款",
            "cumulative_80_percent_sales": "累计覆盖80%销量",
            "pending": "待处理",
            "written": "已生成",
            "validated": "已校验",
        }
        for raw, translated in expected.items():
            with self.subTest(raw=raw):
                self.assertEqual(translated, cpr._display_text(raw))

        future_html = cpr._render_future_validation(
            {
                "future_validation_checklist": [
                    {
                        "validation_type": "user_and_scenario_test",
                        "status": status,
                        "objective": "目标",
                        "trigger": "触发",
                        "method": "方法",
                        "acceptance_criteria": "标准",
                        "owner_role": "负责人",
                    }
                    for status in ("planned", "in_progress", "completed", "blocked")
                ]
            }
        )
        self.assertIn("用户与场景测试", future_html)
        for raw in ("user_and_scenario_test", "in_progress", "completed", "blocked"):
            self.assertNotIn(raw, future_html)

        supply_html = cpr._render_union_and_supply(
            {
                "segments": [{"segment_id": "segment_1_90d", "feature": "测试细分"}],
                "union_analysis": {
                    "need_stats": [],
                    "kano_differences": [],
                    "shared_needs": [],
                    "extreme_scenarios": [],
                    "new_needs": [],
                    "development_priorities": [],
                },
                "supply_validation": [
                    {
                        "segment_id": "segment_1_90d",
                        "confidence": "medium",
                        "products_checked": 30,
                        "cumulative_sales_share": 0.8,
                        "snapshot_at": "2026-08-05T00:00:00Z",
                        "finding": "no_verified_supply",
                        "findings": [
                            {"description": "少量供给", "finding": "few_listings"},
                            {
                                "description": "稀缺供给",
                                "finding": "verified_rare_supply",
                            },
                        ],
                        "claim_boundary": "仅限已检查样本",
                        "checked_layers": {},
                        "supply_evidence": [],
                        "limitations": [],
                    }
                ],
            }
        )
        for raw in ("few_listings", "verified_rare_supply", "no_verified_supply"):
            self.assertNotIn(raw, supply_html)
        self.assertIn("仅发现少量供给", supply_html)
        self.assertIn("已验证为稀缺供给", supply_html)
        self.assertIn("当前覆盖范围内未验证到供给", supply_html)


if __name__ == "__main__":
    unittest.main()
