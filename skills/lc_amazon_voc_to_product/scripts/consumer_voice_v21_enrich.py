#!/usr/bin/env python3
"""Create a PRD v2.1 derived analysis without altering any source receipt.

This bridge is intentionally deterministic.  It recomputes the two opportunity
tracks from the already accepted full voice set, enriches the saved Alexa
analysis with explicit need/direction links, and records the bounded competitor
re-review as a sidecar.  It never changes auth, raw collection data, coding,
or the frozen twelve-role concept definitions.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from consumer_voice_local_reprocess import _opportunity_tracks


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} 必须为 JSON object")
    return value


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


DIMENSION_NEEDS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("收纳", "理线", "供电"), ("storage_cable_power",)),
    (("设备", "显示", "多屏", "接口"), ("work_surface_capacity",)),
    (("承重", "稳定", "材料", "耐久"), ("stability_structure", "materials_shipping_damage")),
    (("安装", "装拆", "搬家", "移动"), ("assembly_experience",)),
    (("价格", "预算", "配置"), ("value_price",)),
    (("升降", "坐姿", "人体", "椅"), ("ergonomic_height",)),
    (("空间", "小空间", "折叠", "转角"), ("small_space_fit",)),
)


def _map_dimensions(dimensions: list[Any], known_need_ids: set[str]) -> list[str]:
    result: list[str] = []
    for raw in dimensions:
        text = str(raw)
        for aliases, ids in DIMENSION_NEEDS:
            if any(alias in text for alias in aliases):
                result.extend(need_id for need_id in ids if need_id in known_need_ids)
    return list(dict.fromkeys(result))


def _direction_ids(need_ids: list[str], concepts: list[Mapping[str, Any]]) -> list[str]:
    return [str(concept.get("concept_id")) for concept in concepts
            if set(need_ids).intersection(str(code) for code in concept.get("core_need_codes", []))]


def _alexas(qa: Mapping[str, Any], needs: list[Mapping[str, Any]], concepts: list[Mapping[str, Any]], *, baseline: Mapping[str, Any] | None = None) -> dict[str, Any]:
    labels = {str(row.get("need_id") or row.get("code")): str(row.get("label") or row.get("need_label") or row.get("need_id") or row.get("code")) for row in needs}
    mapped = 0
    records: list[dict[str, Any]] = []
    for raw in qa.get("records", []):
        if not isinstance(raw, Mapping):
            continue
        row = copy.deepcopy(dict(raw))
        ids = [str(item) for item in row.get("need_ids", []) if str(item) in labels]
        if row.get("disposition", "adopted") == "adopted" and not ids:
            ids = _map_dimensions(list(row.get("buying_dimensions", [])), set(labels))
        row["need_ids"] = ids
        row["consumer_findings"] = [labels[item] for item in ids]
        row["development_direction_ids"] = _direction_ids(ids, concepts)
        if ids:
            mapped += 1
        records.append(row)
    # The import list deliberately contains only reviewed records; retain
    # count/status fields from the validated baseline receipt.
    output = copy.deepcopy(dict(baseline or {}))
    output.update({key: value for key, value in qa.items() if key != "records"})
    output["records"] = records
    output["v21_mapping"] = {
        "status": "completed",
        "mapping_rule": "仅按已保存的选购维度与显式别名映射到稳定 need_id；不新造消费者结论。",
        "adopted_records_with_need_links": mapped,
        "adopted_records": sum(row.get("disposition", "adopted") == "adopted" for row in records),
        "unmapped_adopted_records": sum(row.get("disposition", "adopted") == "adopted" and not row.get("need_ids") for row in records),
    }
    return output


def _competition_audit(rankings: Mapping[str, Any], architecture: Mapping[str, Any]) -> dict[str, Any]:
    by_concept = {str(row.get("concept_id")): row for row in architecture.get("concepts", []) if isinstance(row, Mapping)}
    all_rows = next((rows for rows in rankings.get("rankings", {}).values() if isinstance(rows, list)), [])
    sales_rank = {str(row.get("asin")): index for index, row in enumerate(sorted(all_rows, key=lambda row: (-float(row.get("sales") or 0), str(row.get("asin") or ""))), start=1) if isinstance(row, Mapping)}
    denominator = int(architecture.get("denominator") or 0)
    concepts: list[dict[str, Any]] = []
    for concept_id, rows in rankings.get("rankings", {}).items():
        if not isinstance(rows, list) or not rows:
            continue
        selected = rows[0]
        detail = selected.get("detail", {}) if isinstance(selected.get("detail"), Mapping) else {}
        review = by_concept.get(str(concept_id), {})
        comparisons = [row for row in review.get("feature_comparisons", []) if isinstance(row, Mapping)]
        upgrades = []
        for item in comparisons:
            metrics = item.get("basic_need_statistics", [])
            needs = "；".join(f"{row.get('count', 0)}/{denominator}（{row.get('percentage', 0):.2f}%）" for row in metrics if isinstance(row, Mapping))
            upgrades.append({
                "competitor_existing": item.get("competitor_existing_claim", "待核验"),
                "consumer_need": needs or "未记录对应基础需求",
                "our_upgrade": item.get("our_upgrade_frozen", "待定义"),
                "expected_improvement": item.get("expected_improvement_hypothesis", "待验证"),
                "tradeoff": item.get("tradeoffs", "待验证"),
                "validation": item.get("validation", "待定义"),
            })
        concepts.append({
            "concept_id": concept_id,
            "verdict": "verification_pending",
            "benchmark": {
                "asin": selected.get("asin"), "title": detail.get("title"), "product_url": detail.get("product_url"),
                "price": f"USD {detail.get('price'):.2f}" if isinstance(detail.get("price"), (int, float)) else "待核验",
                "sales": selected.get("sales"), "sales_rank": sales_rank.get(str(selected.get("asin"))),
                "sales_period": selected.get("sales_period"), "verified_original_sales_period": selected.get("sales_period"),
                "top_decile_cutoff": rankings.get("cutoff_sales"),
                "matched_feature_count": selected.get("overlap_count"), "core_feature_count": selected.get("overlap_denominator"),
                "overlap_share": (selected.get("overlap_count", 0) / selected.get("overlap_denominator", 1)),
                "selection_rationale": "销量前10%入围后，按冻结正向核心特征重叠、销量、ASIN排序。未体现的标签为未知，不作功能缺失结论。",
            },
            "core_feature_matches": selected.get("matched", []),
            "core_feature_unknowns": selected.get("unconfirmed", []),
            "comparison": {"benchmark_satisfies": "仅展示可从商品标题/标签确认的声明；其余能力待核验。", "remaining_gap": "具体机制、性能与尺寸包络须购样或样机验证。", "our_change": "见逐功能升级矩阵。", "expected_improvement": "均为待验证假设。", "tradeoffs": "见逐功能升级矩阵。", "validation": "见逐功能升级矩阵。"},
            "upgrade_matrix": upgrades,
        })
    return {"schema_version": "competition-audit-2.1", "status": "completed", "product_pool": {"product_count": rankings.get("pool_count"), "top_decile_count": rankings.get("eligible_count"), "top_decile_cutoff": rankings.get("cutoff_sales"), "sales_period": "近30天月销量"}, "method": "销量前10%入围，再比较冻结核心特征；未知能力不作为竞品缺失证据。", "concepts": concepts}


def _image_prompt(concept: Mapping[str, Any], role: str) -> str:
    role_instruction = {
        "overall": "Show the complete exterior only in a neutral studio, three-quarter view.",
        "structure": "Show the key structure and frozen upgrade mechanism clearly; do not add any unfrozen part.",
        "scene": "Show the defined use scenario/state; do not claim that safety or performance has been tested.",
    }[role]
    return (
        "Unverified product concept illustration. " + role_instruction
        + " JTBD: " + str(concept.get("jtbd", ""))
        + " Functional and technical solution: " + str(concept.get("technical_solution", ""))
        + " Structure: " + str(concept.get("structure", ""))
        + " Materials: " + "；".join(map(str, concept.get("materials", [])))
        + " Appearance: " + json.dumps(concept.get("cmf", {}), ensure_ascii=False)
        + " No brand, visible text, claim badge, invented feature, or engineering-performance assertion."
    )


def _concept_assets(image_dir: Path, output_dir: Path, concepts: list[Mapping[str, Any]]) -> dict[str, list[dict[str, str]]]:
    role_order = (("overall", "产品整体外观图"), ("structure", "关键结构与升级机制图"), ("scene", "使用场景图"))
    result: dict[str, list[dict[str, str]]] = {}
    for concept in concepts:
        concept_id = str(concept.get("concept_id") or "")
        rows: list[dict[str, str]] = []
        for suffix, role_label in role_order:
            path = image_dir / f"{concept_id}-{suffix}.png"
            if not path.is_file():
                raise ValueError(f"缺少概念图：{path}")
            rows.append({"role": suffix, "role_label": role_label, "path": os.path.relpath(path, output_dir), "sha256": _sha(path), "prompt": _image_prompt(concept, suffix), "prompt_basis": "JTBD + 功能与技术方案 + 结构 + 材料 + 外观（冻结工作坊产物）"})
        result[concept_id] = rows
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 PRD v2.1 的确定性派生分析")
    parser.add_argument("--analysis", required=True, type=Path)
    parser.add_argument("--coding", required=True, type=Path)
    parser.add_argument("--qa-analysis", required=True, type=Path)
    parser.add_argument("--competition-review", required=True, type=Path)
    parser.add_argument("--competitor-rankings", required=True, type=Path)
    parser.add_argument("--architecture-comparison", required=True, type=Path)
    parser.add_argument("--concept-images-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    analysis = _read(args.analysis)
    coding = _read(args.coding)
    qa = _read(args.qa_analysis)
    review = _read(args.competition_review)
    rankings = _read(args.competitor_rankings)
    architecture = _read(args.architecture_comparison)
    voices = coding.get("voices")
    if not isinstance(voices, list):
        raise ValueError("编码文件缺少 voices[]")
    denominator = int(analysis.get("funnel", {}).get("qualified_consumer_voices", 0))
    if denominator != len(voices):
        raise ValueError(f"有效 VOC 分母不一致：analysis={denominator} coding={len(voices)}")

    output = copy.deepcopy(analysis)
    taxonomy = coding.get("semantic_taxonomy") if isinstance(coding.get("semantic_taxonomy"), Mapping) else {}
    tracks = _opportunity_tracks(voices, denominator, taxonomy)
    output["opportunity_tracks"] = tracks
    output["new_needs"] = tracks["specific_new_needs"]
    needs = [row for row in output.get("evidence_readiness", {}).get("needs", []) if isinstance(row, Mapping)]
    concepts = [row for row in output.get("product_concepts", []) if isinstance(row, Mapping)]
    baseline_qa = output.get("alexa_analysis")
    output["alexa_analysis"] = _alexas(qa, needs, concepts, baseline=baseline_qa if isinstance(baseline_qa, Mapping) else {})
    output["competition_v21_review"] = {
        "status": "completed",
        "scope": "销量前10%主对标与冻结功能的有界复评；不伪称为新的完整十二角色工作坊。",
        "source_path": str(args.competition_review.resolve()),
        "source_sha256": _sha(args.competition_review),
        "review": review,
    }
    output["competition_audit"] = _competition_audit(rankings, architecture)
    output["concept_image_assets"] = _concept_assets(args.concept_images_dir.resolve(), args.output.parent.resolve(), concepts)
    output["business_rules_version"] = "voc-prd-v2.1"
    methodology = output.setdefault("methodology", {})
    methodology.update({
        "prd_version": "2.1",
        "opportunity_method": "双轨：具体新需求严格按 stable need_id 与0.5%阈值；既有需求改进不宣称市场空白。",
        "alexa_method": "选购维度、声明核验与测试约束，不计入有效VOC分母。",
    })
    output["v21_derivation"] = {
        "status": "completed",
        "source_analysis_sha256": _sha(args.analysis),
        "coding_sha256": _sha(args.coding),
        "qa_analysis_sha256": _sha(args.qa_analysis),
        "raw_or_coding_mutated": False,
        "coding_reassignment_performed": False,
        "opportunity_recount_scope": f"全部 {denominator} 条已接受有效VOC",
        "limitation": "本次派生重算不重写已验收逐条编码；具体机会仍由现有模型复核编码的 stable need_id 判定。",
    }
    _write(args.output, output)


if __name__ == "__main__":
    main()
