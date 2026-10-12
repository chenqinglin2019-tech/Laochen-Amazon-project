#!/usr/bin/env python3
"""Prepare and import the v2.3 full opportunity-semantic review.

This program intentionally has no model, network, authentication or API-key
logic.  Python freezes records, batches them at most twenty at a time, and
validates coverage/counting.  Codex (or another registered reviewer) supplies
the semantic decision in a separate JSONL file; no old topic tag is treated as
a replacement for that decision.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from typing import Any, Mapping


SCHEMA = "consumer-opportunity-semantic-review-2.3"
DECISIONS = {"specific_need", "design_hypothesis", "no_specific_opportunity", "insufficient_evidence"}


class ReviewError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".opportunity-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ReviewError(path.name + " 必须是 JSON 对象")
    return value


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _record_source_sha256(record: Mapping[str, Any]) -> str:
    """Bind a semantic decision to the complete reviewer input, not its ID."""
    return hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _record(voice: Mapping[str, Any]) -> dict[str, Any]:
    voice_id = str(voice.get("voice_id") or "")
    if not voice_id:
        raise ReviewError("coding.voice_id 缺失")
    # These fields are intentionally complete enough for semantic review, but
    # exclude opaque raw response payloads and never duplicate credentials.
    record = {
        "voice_id": voice_id,
        "platform": voice.get("platform"),
        "source_kind": voice.get("source_kind"),
        "segment_memberships": voice.get("segment_memberships", []),
        "author_id": voice.get("author_id"),
        # `coding_source.json` stores the preserved consumer body as
        # `full_text`/`excerpt`; raw collector adapters use the other aliases.
        # Never silently send a blank body to the semantic reviewer.
        "text": (
            voice.get("full_text")
            or voice.get("raw_excerpt")
            or voice.get("excerpt")
            or voice.get("text")
            or voice.get("content")
            or ""
        ),
        "context": voice.get("context") or voice.get("title") or voice.get("source_url") or "",
        "existing_needs": voice.get("needs", []),
    }
    record["record_source_sha256"] = _record_source_sha256(record)
    return record


def prepare(coding_path: Path, output_dir: Path, batch_size: int) -> dict[str, Any]:
    if not 1 <= batch_size <= 20:
        raise ReviewError("batch-size 必须为 1–20")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ReviewError("输出目录必须为空，避免覆盖既有复核")
    coding = _read(coding_path)
    voices = coding.get("voices")
    if not isinstance(voices, list):
        raise ReviewError("coding.voices 必须是数组")
    rows = [_record(v) for v in voices if isinstance(v, Mapping)]
    ids = [row["voice_id"] for row in rows]
    if len(ids) != len(voices) or len(ids) != len(set(ids)):
        raise ReviewError("有效 VOC 必须都有唯一 voice_id")
    if any(not _nonempty(row.get("text")) for row in rows):
        raise ReviewError("有效 VOC 缺少可供语义复核的正文；必须先补齐原始文本")
    batches: list[dict[str, Any]] = []
    for number, start in enumerate(range(0, len(rows), batch_size), start=1):
        payload = {
            "schema_version": SCHEMA + "-batch",
            "batch_id": "opportunity-%04d" % number,
            "review_instruction": "逐条审结：从消费者表达识别希望实现的结果、障碍、后果、现有绕行方式和候选机制。不得只复用旧标签；没有具体机会亦须写明 no_specific_opportunity。每项只能根据本条及必要上下文判断。",
            "records": rows[start:start + batch_size],
        }
        filename = "batches/%s.json" % payload["batch_id"]
        _write(output_dir / filename, payload)
        batches.append({"batch_id": payload["batch_id"], "path": filename, "sha256": _digest(output_dir / filename), "record_count": len(payload["records"])})
    manifest = {
        "schema_version": SCHEMA + "-manifest",
        "coding_path": str(coding_path.resolve()),
        "coding_sha256": _digest(coding_path),
        "voice_count": len(rows),
        "batch_size": batch_size,
        "batches": batches,
        "created_at": _now(),
        "status": "prepared",
    }
    _write(output_dir / "review_manifest.json", manifest)
    return {"status": "prepared", "voice_count": len(rows), "batch_count": len(batches), "manifest": str((output_dir / "review_manifest.json").resolve())}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ReviewError("第 %d 行不是对象" % number)
        rows.append(value)
    return rows


def _validate_decision(row: Mapping[str, Any], expected_records: Mapping[str, Mapping[str, Any]]) -> None:
    if not _nonempty(row.get("voice_id")) or str(row["voice_id"]) not in expected_records:
        raise ReviewError("复核输出引用了未知 voice_id")
    if row.get("decision") not in DECISIONS:
        raise ReviewError("机会复核 decision 无效")
    for key in ("desired_outcomes", "barriers", "consequences", "workarounds", "candidate_mechanism_hints", "needs"):
        if not isinstance(row.get(key), list):
            raise ReviewError("%s 必须是数组" % key)
    if not _nonempty(row.get("rationale")) or not _nonempty(row.get("reviewer_id")):
        raise ReviewError("每条机会复核必须有 rationale 和实际 reviewer_id")
    if not _nonempty(row.get("evidence_quote")):
        raise ReviewError("每条机会复核必须保留来自该条原文的 evidence_quote")
    source_text = str(expected_records[str(row["voice_id"])].get("text") or "")
    if row.get("record_source_sha256") != expected_records[str(row["voice_id"])].get("record_source_sha256"):
        raise ReviewError("机会复核未绑定当前原文、上下文和既有需求快照")
    if str(row["evidence_quote"]).strip().casefold() not in source_text.casefold():
        raise ReviewError("evidence_quote 必须是对应消费者原文的连续片段")
    if row["decision"] == "specific_need":
        if not row["needs"]:
            raise ReviewError("具体机会必须列出至少一个具体需求")
        for need in row["needs"]:
            if not isinstance(need, Mapping) or not _nonempty(need.get("need_id")) or not _nonempty(need.get("label")):
                raise ReviewError("具体需求必须有稳定 need_id 与 label")
            if need.get("stance", "support") not in {"support", "counter", "mixed"}:
                raise ReviewError("具体需求 stance 必须是 support/counter/mixed")
            if need.get("applicability", "unknown") not in {"current", "future", "unknown"}:
                raise ReviewError("具体需求 applicability 必须是 current/future/unknown")
    if row["decision"] == "no_specific_opportunity" and row["needs"]:
        raise ReviewError("无具体机会不能暗中写入具体需求")


def import_results(output_dir: Path, results_path: Path) -> dict[str, Any]:
    manifest = _read(output_dir / "review_manifest.json")
    if manifest.get("schema_version") != SCHEMA + "-manifest":
        raise ReviewError("不是 v2.3 机会复核目录")
    output_path = output_dir / "opportunity_semantic_review.json"
    if output_path.exists():
        raise ReviewError("机会复核结果已存在；请新建修订目录，禁止覆盖已验收结果")
    coding_path = Path(str(manifest.get("coding_path") or ""))
    if not coding_path.is_file() or _digest(coding_path) != manifest.get("coding_sha256"):
        raise ReviewError("源 coding 已变化，必须重新准备复核")
    expected_records = {
        item["voice_id"]: item
        for item in [_record(v) for v in _read(coding_path).get("voices", []) if isinstance(v, Mapping)]
    }
    expected = set(expected_records)
    rows = _read_jsonl(results_path)
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        _validate_decision(row, expected_records)
        voice_id = str(row["voice_id"])
        if voice_id in by_id:
            raise ReviewError("同一 voice_id 不能重复审结")
        by_id[voice_id] = dict(row)
    if set(by_id) != expected:
        raise ReviewError("机会语义复核覆盖不完整：已审 %d / 应审 %d" % (len(by_id), len(expected)))
    normalized = [by_id[voice_id] for voice_id in sorted(by_id)]
    counts = {key: sum(1 for item in normalized if item["decision"] == key) for key in sorted(DECISIONS)}
    output = {
        "schema_version": SCHEMA + "-results",
        "manifest_sha256": _digest(output_dir / "review_manifest.json"),
        "results_source_path": str(results_path.resolve()),
        "results_source_sha256": _digest(results_path),
        "coding_sha256": manifest["coding_sha256"],
        "reviewed_count": len(normalized),
        "decision_counts": counts,
        "records": normalized,
        "completed_at": _now(),
        "status": "completed",
    }
    _write(output_path, output)
    return {"status": "completed", "reviewed_count": len(normalized), "decision_counts": counts, "output": str(output_path.resolve())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--coding", type=Path, required=True)
    prep.add_argument("--output-dir", type=Path, required=True)
    prep.add_argument("--batch-size", type=int, default=20)
    ingest = commands.add_parser("import-results")
    ingest.add_argument("--output-dir", type=Path, required=True)
    ingest.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.coding, args.output_dir, args.batch_size) if args.command == "prepare" else import_results(args.output_dir, args.results)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, ReviewError, json.JSONDecodeError) as error:
        parser.exit(2, "机会复核失败：%s\n" % error)


if __name__ == "__main__":
    raise SystemExit(main())
