#!/usr/bin/env python3
"""Repair historical fulfillment values without modifying the source job.

This tool reuses the crawler's explicit-value parser. A non-empty raw value
whose text starts with ``FBA``, ``FBM``, or ``AMZ`` is normalized to that
prefix regardless of its suffix. A non-prefix value such as ``non-FBA`` or
``SFP`` remains evidence and is reported without being inferred.
The repaired comparison output follows the requested rule: keep every product
with a child-category rank unless its canonical method is FBA.

Example:

    python3 scripts/repair_fulfillment_outputs.py \
      outputs/competitor-stores-new-arrivals-all-20260817 \
      --output-dir outputs/competitor-stores-new-arrivals-all-20260817-repaired \
      --expected-record-count 2203 \
      --expected-unique-asin-count 2200

The source job is opened read-only. Five artifacts are staged in a sibling
directory and published together only after every validation succeeds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from amazon_category_rank_crawler import (  # noqa: E402
    normalize_fulfillment_method,
    normalize_subcategory_bsr_ranks,
    parse_fulfillment_evidence,
)
from amazon_front_crawler import (  # noqa: E402
    build_front_dedup_rows,
    write_front_workbook,
    write_jsonl_atomic,
)


REPAIR_SEMANTICS = "fulfillment-explicit-prefix-repair-v3"
REPORT_SCHEMA_VERSION = 1
REPAIRED_RECORDS_NAME = "records_repaired.jsonl"
FULL_WORKBOOK_NAME = "竞品店铺_全量数据_配送修复版.xlsx"
FILTERED_RECORDS_NAME = (
    "records_filtered_non_fba_with_subcategory_rank_repaired.jsonl"
)
FILTERED_WORKBOOK_NAME = (
    "竞品店铺_筛选版_非FBA且有子类目节点排名_配送修复版.xlsx"
)
REPORT_NAME = "repair_report.json"
ARTIFACT_NAMES: Tuple[str, ...] = (
    REPAIRED_RECORDS_NAME,
    FULL_WORKBOOK_NAME,
    FILTERED_RECORDS_NAME,
    FILTERED_WORKBOOK_NAME,
    REPORT_NAME,
)


class RepairError(RuntimeError):
    """A safe, user-facing historical repair error."""


def _text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_jsonl_strict(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RepairError(
                    f"源 records.jsonl 第 {line_number} 行不是有效 JSON：{exc.msg}"
                ) from exc
            if not isinstance(value, dict):
                raise RepairError(
                    f"源 records.jsonl 第 {line_number} 行必须是 JSON 对象。"
                )
            records.append(value)
    if not records:
        raise RepairError("源 records.jsonl 没有可修复的商品记录。")
    return records


def _unique_asin_count(records: Iterable[Mapping[str, Any]]) -> int:
    return len(
        {
            _text(record.get("asin"))
            for record in records
            if _text(record.get("asin"))
        }
    )


def _canonical_distribution(records: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    counter: Counter[str] = Counter()
    for record in records:
        value = normalize_fulfillment_method(record.get("fulfillment_method"))
        counter[value if value else "missing"] += 1
    return {
        "FBM": counter["FBM"],
        "FBA": counter["FBA"],
        "AMZ": counter["AMZ"],
        "missing": counter["missing"],
    }


def _raw_distribution(records: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    counter = Counter(
        _text(record.get("fulfillment_method_raw")) or "missing" for record in records
    )
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def repair_records(
    records: Sequence[Mapping[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Return repaired copies plus an audit summary.

    Existing valid canonical values win. Otherwise the shared explicit-value
    parser recognizes any raw value beginning with FBA/FBM/AMZ. Unknown
    evidence is never inferred. If an old record placed unknown evidence in
    the canonical field but omitted ``fulfillment_method_raw``, the evidence
    is moved to the raw field so the repaired output remains auditable.
    """

    repaired: List[Dict[str, Any]] = []
    repair_counts: Counter[str] = Counter()
    unknown_raw_values: Counter[str] = Counter()
    unknown_original_methods: Counter[str] = Counter()
    canonical_raw_conflicts: Counter[str] = Counter()

    for source_record in records:
        record = dict(source_record)
        original_method_text = _text(record.get("fulfillment_method"))
        original_method = normalize_fulfillment_method(original_method_text)
        raw_text = _text(record.get("fulfillment_method_raw"))

        if original_method_text and not original_method:
            unknown_original_methods[original_method_text] += 1
            if not raw_text:
                raw_text = original_method_text
                repair_counts["raw_backfilled_from_unknown_canonical"] += 1

        parsed_raw_method, parsed_raw_text = parse_fulfillment_evidence(
            raw_text, explicit_value=True
        )
        if parsed_raw_text:
            raw_text = parsed_raw_text
        if raw_text and not parsed_raw_method:
            unknown_raw_values[raw_text] += 1

        if original_method:
            repaired_method = original_method
            repair_counts["preserved_valid_canonical"] += 1
            if parsed_raw_method and parsed_raw_method != original_method:
                canonical_raw_conflicts[f"{original_method}|{raw_text}"] += 1
        elif parsed_raw_method:
            repaired_method = parsed_raw_method
            if normalize_fulfillment_method(raw_text):
                repair_counts["repaired_from_exact_raw"] += 1
            else:
                repair_counts[f"repaired_{parsed_raw_method}_prefix"] += 1
        else:
            repaired_method = ""
            if raw_text:
                repair_counts["unknown_raw_left_unconverted"] += 1
            else:
                repair_counts["genuinely_missing"] += 1

        record["fulfillment_method"] = repaired_method
        record["fulfillment_method_raw"] = raw_text
        repaired.append(record)

    unresolved_count = sum(
        1
        for record in repaired
        if _text(record.get("fulfillment_method_raw"))
        and not normalize_fulfillment_method(record.get("fulfillment_method"))
    )
    audit = {
        "repair_counts": dict(sorted(repair_counts.items())),
        "unknown_nonempty_raw_values": [
            {"value": value, "count": count}
            for value, count in sorted(
                unknown_raw_values.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        "unknown_original_canonical_values": [
            {"value": value, "count": count}
            for value, count in sorted(
                unknown_original_methods.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        "canonical_raw_conflicts": [
            {"canonical_and_raw": value, "count": count}
            for value, count in sorted(
                canonical_raw_conflicts.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        "raw_nonempty_canonical_empty_records": unresolved_count,
    }
    return repaired, audit


def _validate_expected_count(label: str, actual: int, expected: Optional[int]) -> None:
    if expected is not None and actual != expected:
        raise RepairError(f"{label}不符合预期：实际 {actual}，预期 {expected}。")


def filter_non_fba_with_subcategory_rank(
    records: Sequence[Mapping[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Keep ranked records unless their canonical fulfillment is FBA.

    This intentionally accepts FBM, missing, AMZ, and unknown non-empty raw
    evidence. Unknown evidence remains canonical-empty and visible in the
    repair report; only a canonical FBA value is excluded.
    """

    accepted: List[Dict[str, Any]] = []
    rejection_counts: Counter[str] = Counter()
    for source_record in records:
        reasons: List[str] = []
        method = normalize_fulfillment_method(
            source_record.get("fulfillment_method")
        )
        if method == "FBA":
            reasons.append("fulfillment_method_excluded_fba")
        if not normalize_subcategory_bsr_ranks(
            source_record.get("subcategory_bsr_ranks")
        ):
            reasons.append("subcategory_bsr_rank_missing")
        if reasons:
            rejection_counts.update(reasons)
            continue
        accepted.append(dict(source_record))
    return accepted, dict(sorted(rejection_counts.items()))


def _ensure_separate_output(source_job_dir: Path, output_dir: Path) -> None:
    if output_dir == source_job_dir or source_job_dir in output_dir.parents:
        raise RepairError("输出目录必须位于旧 job 目录之外，旧 job 只允许读取。")
    if output_dir.exists():
        raise RepairError(f"输出目录已存在，为避免覆盖已拒绝执行：{output_dir}")


def _artifact_integrity(stage_dir: Path) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    for name in ARTIFACT_NAMES[:-1]:
        path = stage_dir / name
        output.append(
            {
                "name": name,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return output


def _write_report(path: Path, report: Mapping[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def repair_job_outputs(
    source_job_dir: Path,
    output_dir: Optional[Path] = None,
    *,
    expected_record_count: Optional[int] = None,
    expected_unique_asin_count: Optional[int] = None,
    expected_filtered_asin_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Repair one historical front-crawler job into a new sibling directory."""

    source_job_dir = source_job_dir.expanduser().resolve()
    if not source_job_dir.is_dir():
        raise RepairError(f"源 job 目录不存在：{source_job_dir}")
    records_path = source_job_dir / "records.jsonl"
    if not records_path.is_file():
        raise RepairError(f"源 job 缺少 records.jsonl：{records_path}")

    if output_dir is None:
        output_dir = source_job_dir.parent / f"{source_job_dir.name}-repaired"
    output_dir = output_dir.expanduser().resolve()
    _ensure_separate_output(source_job_dir, output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)

    source_sha256_before = _sha256(records_path)
    source_records = _read_jsonl_strict(records_path)
    source_unique_asins = _unique_asin_count(source_records)
    _validate_expected_count(
        "源记录数", len(source_records), expected_record_count
    )
    _validate_expected_count(
        "源去重 ASIN 数", source_unique_asins, expected_unique_asin_count
    )

    repaired_records, repair_audit = repair_records(source_records)
    filtered_records, rejection_counts = filter_non_fba_with_subcategory_rank(
        repaired_records
    )
    filtered_unique_asins = _unique_asin_count(filtered_records)
    _validate_expected_count(
        "筛选后去重 ASIN 数",
        filtered_unique_asins,
        expected_filtered_asin_count,
    )

    repaired_dedup_rows = build_front_dedup_rows(repaired_records)
    repaired_unique_asins = _unique_asin_count(repaired_dedup_rows)
    if repaired_unique_asins != source_unique_asins:
        raise RepairError(
            "回填前后去重 ASIN 数发生变化："
            f"源 {source_unique_asins}，修复后 {repaired_unique_asins}。"
        )

    stage_dir = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.stage-", dir=str(output_dir.parent))
    )
    try:
        repaired_records_path = stage_dir / REPAIRED_RECORDS_NAME
        filtered_records_path = stage_dir / FILTERED_RECORDS_NAME
        write_jsonl_atomic(repaired_records_path, repaired_records)
        write_jsonl_atomic(filtered_records_path, filtered_records)

        failures_path = source_job_dir / "failures.jsonl"
        write_front_workbook(
            repaired_records_path,
            failures_path,
            stage_dir / FULL_WORKBOOK_NAME,
        )
        write_front_workbook(
            filtered_records_path,
            failures_path,
            stage_dir / FILTERED_WORKBOOK_NAME,
        )

        source_sha256_after = _sha256(records_path)
        if source_sha256_after != source_sha256_before:
            raise RepairError("源 records.jsonl 在回填过程中发生变化，已停止发布结果。")

        report: Dict[str, Any] = {
            "report_schema_version": REPORT_SCHEMA_VERSION,
            "repair_semantics": REPAIR_SEMANTICS,
            "fulfillment_repair_rule": {
                "shared_parser": "parse_fulfillment_evidence(explicit_value=True)",
                "recognized_prefixes": ["FBA", "FBM", "AMZ"],
                "suffix_policy": "any_suffix_after_recognized_prefix",
                "non_prefix_policy": "preserve_raw_and_leave_canonical_empty",
            },
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": {
                "job_dir": str(source_job_dir),
                "records_file": str(records_path),
                "records_sha256_before": source_sha256_before,
                "records_sha256_after": source_sha256_after,
                "source_integrity_verified": True,
            },
            "output": {
                "output_dir": str(output_dir),
                "artifact_names": list(ARTIFACT_NAMES),
                "artifact_integrity": _artifact_integrity(stage_dir),
            },
            "counts": {
                "source_records": len(source_records),
                "source_unique_asins": source_unique_asins,
                "repaired_records": len(repaired_records),
                "repaired_unique_asins": repaired_unique_asins,
                "filtered_records": len(filtered_records),
                "filtered_unique_asins": filtered_unique_asins,
            },
            "fulfillment_distribution": {
                "source_canonical_records": _canonical_distribution(source_records),
                "source_raw_records": _raw_distribution(source_records),
                "repaired_canonical_records": _canonical_distribution(repaired_records),
                "repaired_canonical_unique_asins": _canonical_distribution(
                    repaired_dedup_rows
                ),
                "raw_nonempty_canonical_empty_records": repair_audit[
                    "raw_nonempty_canonical_empty_records"
                ],
            },
            "repair_counts": repair_audit["repair_counts"],
            "unknown_nonempty_raw_values": repair_audit[
                "unknown_nonempty_raw_values"
            ],
            "unknown_original_canonical_values": repair_audit[
                "unknown_original_canonical_values"
            ],
            "canonical_raw_conflicts": repair_audit["canonical_raw_conflicts"],
            "filter": {
                "exclude_fulfillment_methods": ["FBA"],
                "require_subcategory_rank": True,
                "accepted_fulfillment_semantics": [
                    "FBM",
                    "missing",
                    "AMZ",
                    "unknown_nonempty",
                ],
                "rejection_counts": rejection_counts,
            },
        }
        _write_report(stage_dir / REPORT_NAME, report)
        os.replace(stage_dir, output_dir)
        return report
    except BaseException:
        if stage_dir.exists():
            shutil.rmtree(stage_dir)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "只读旧 job 的 records.jsonl，保守修复 SellerSprite 配送方式并旁路生成新结果。"
        )
    )
    parser.add_argument("source_job_dir", type=Path, help="旧 front-crawler job 目录")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="新输出目录；默认是旧 job 的同级 <job>-repaired",
    )
    parser.add_argument("--expected-record-count", type=int)
    parser.add_argument("--expected-unique-asin-count", type=int)
    parser.add_argument("--expected-filtered-asin-count", type=int)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = repair_job_outputs(
            args.source_job_dir,
            args.output_dir,
            expected_record_count=args.expected_record_count,
            expected_unique_asin_count=args.expected_unique_asin_count,
            expected_filtered_asin_count=args.expected_filtered_asin_count,
        )
    except RepairError as exc:
        print(f"历史配送回填失败：{exc}", file=sys.stderr)
        return 2
    counts = report["counts"]
    print(
        "历史配送回填完成："
        f"记录 {counts['repaired_records']}，"
        f"去重 ASIN {counts['repaired_unique_asins']}，"
        f"筛选 ASIN {counts['filtered_unique_asins']}。"
    )
    print(f"输出目录：{report['output']['output_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
