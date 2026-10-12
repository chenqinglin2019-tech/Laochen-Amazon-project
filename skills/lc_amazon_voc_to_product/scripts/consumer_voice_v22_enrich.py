#!/usr/bin/env python3
"""Derive a PRD v2.3 analysis snapshot from a completed opportunity review.

The source analysis and coding remain byte-for-byte untouched.  This bridge
only produces a new analysis snapshot whose opportunity tracks are counted
from the full, reviewed accepted-voice set.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from voc_prd_pipeline import unified_need_registry


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(path.name + " 必须是对象")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".v22-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _opportunity_tracks(
    records: list[Mapping[str, Any]],
    denominator: int,
    established_need_improvements: list[Mapping[str, Any]],
) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.get("decision") != "specific_need":
            continue
        for raw in record.get("needs", []):
            if not isinstance(raw, Mapping):
                continue
            need_id = str(raw.get("need_id") or "").strip()
            label = str(raw.get("label") or "").strip()
            if not need_id or not label:
                continue
            row = grouped.setdefault(need_id, {"need_id": need_id, "label": label, "voice_ids": set(), "kind": str(raw.get("kind") or "specific_new_need"), "design_hypothesis": bool(raw.get("design_hypothesis", False))})
            row["voice_ids"].add(str(record["voice_id"]))
    formal, hypotheses = [], []
    for item in grouped.values():
        count = len(item["voice_ids"])
        row = {key: value for key, value in item.items() if key != "voice_ids"}
        row.update({"count": count, "share": count / denominator if denominator else 0.0, "support_voice_count": count, "threshold": 0.005})
        if count * 200 >= denominator and not item["design_hypothesis"]:
            formal.append(row)
        else:
            row["evidence_scope"] = "设计假设或低于0.5%；不作为正式机会展示。"
            hypotheses.append(row)
    sort = lambda rows: sorted(rows, key=lambda item: (-item["count"], item["need_id"]))
    return {
        "schema_version": "consumer-opportunity-tracks-2.3",
        "denominator": denominator,
        "specific_new_needs": sort(formal),
        # The existing-demand track has already been counted over the same
        # accepted-voice denominator.  v2.2 must retain it rather than make
        # valid improvement opportunities disappear merely because the new
        # semantic review focuses on concrete new needs/workarounds.
        "established_need_improvements": copy.deepcopy(established_need_improvements),
        "design_hypotheses": sort(hypotheses),
        "audit": {"review_scope": "全部有效 VOC 的逐条机会语义复核", "specific_threshold": 0.005, "all_records_processed": True, "semantic_deduplication_applied": False, "specific_candidate_count": len(formal), "design_hypothesis_count": len(hypotheses)},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", required=True, type=Path)
    parser.add_argument("--coding", required=True, type=Path)
    parser.add_argument("--opportunity-review", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("输出快照已存在；请使用新运行目录，禁止覆盖历史分析")
    analysis, coding, review = _read(args.analysis), _read(args.coding), _read(args.opportunity_review)
    voices = coding.get("voices")
    records = review.get("records")
    if not isinstance(voices, list) or not isinstance(records, list):
        raise ValueError("coding/review 缺少 voices 或 records")
    denominator = int(analysis.get("funnel", {}).get("qualified_consumer_voices", 0))
    if denominator != len(voices) or review.get("reviewed_count") != denominator:
        raise ValueError("机会复核必须覆盖全部有效 VOC")
    if review.get("coding_sha256") != _sha(args.coding):
        raise ValueError("机会复核与 Coding 快照不一致")
    if review.get("status") != "completed":
        raise ValueError("机会复核尚未完成")
    output = copy.deepcopy(analysis)
    prior_tracks = analysis.get("opportunity_tracks")
    prior_established = (
        prior_tracks.get("established_need_improvements", [])
        if isinstance(prior_tracks, Mapping) else []
    )
    output["opportunity_tracks"] = _opportunity_tracks(
        [row for row in records if isinstance(row, Mapping)],
        denominator,
        [row for row in prior_established if isinstance(row, Mapping)],
    )
    registry = unified_need_registry(
        [row for row in voices if isinstance(row, dict)],
        [row for row in records if isinstance(row, dict)],
        denominator,
    )
    readiness = output.setdefault("evidence_readiness", {})
    if not isinstance(readiness, dict):
        raise ValueError("analysis.evidence_readiness 必须是对象")
    readiness["needs"] = registry
    readiness["need_registry"] = {
        "schema_version": "consumer-unified-need-registry-2.3",
        "denominator": denominator,
        "registry_sha256": hashlib.sha256(json.dumps(registry, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest(),
        "source": "base_coding_and_full_opportunity_review",
    }
    output["new_needs"] = output["opportunity_tracks"]["specific_new_needs"]
    output["business_rules_version"] = "voc-prd-v2.3"
    output.setdefault("methodology", {}).update({
        "prd_version": "2.3",
        "opportunity_method": "Codex 逐条机会语义复核；具体需求独立计数，0.5% 才为正式机会，低频仅列设计假设。",
        "kano_method": "消费者声音推断；KANO 类型用于设计策略，不替代正式配对问卷或 Better/Worse 计算。",
    })
    output["v23_derivation"] = {"status": "completed", "source_analysis_sha256": _sha(args.analysis), "coding_sha256": _sha(args.coding), "opportunity_review_path": str(args.opportunity_review.resolve()), "opportunity_review_sha256": _sha(args.opportunity_review), "raw_or_coding_mutated": False, "reviewed_count": denominator}
    _write(args.output, output)


if __name__ == "__main__":
    main()
