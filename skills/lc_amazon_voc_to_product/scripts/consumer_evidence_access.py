#!/usr/bin/env python3
"""Bounded, read-only access to consumer-coding queues and workshop evidence.

This command intentionally separates local JSON/SQLite reading from Agent context:
queue pages are immutable snapshots, oversized records must be read in full through
the record command, and every source database is opened read-only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit


DEFAULT_LIMIT = 20
MAX_LOOKUP_LIMIT = 50
DEFAULT_MAX_CHARS = 12_000


class EvidenceAccessError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceAccessError(f"无法读取 JSON：{path}") from exc
    if not isinstance(value, Mapping):
        raise EvidenceAccessError(f"JSON 顶层必须为对象：{path}")
    return value


@lru_cache(maxsize=16)
def _cached_coding(path_text: str, snapshot_sha256: str) -> tuple[Mapping[str, Any], tuple[Mapping[str, Any], ...]]:
    """Parse an immutable Coding snapshot once per verified content hash."""
    coding = _load_json(Path(path_text))
    voices = coding.get("voices")
    if not isinstance(voices, list) or any(not isinstance(row, Mapping) for row in voices):
        raise EvidenceAccessError("Coding.voices 必须为对象数组")
    return coding, tuple(voices)


@lru_cache(maxsize=16)
def _cached_need_index(path_text: str, snapshot_sha256: str) -> Mapping[str, tuple[Mapping[str, Any], ...]]:
    _coding, voices = _cached_coding(path_text, snapshot_sha256)
    index: dict[str, list[Mapping[str, Any]]] = {}
    for voice in voices:
        for need in voice.get("needs", []) if isinstance(voice.get("needs"), list) else []:
            if not isinstance(need, Mapping):
                continue
            code = str(need.get("need_id") or need.get("code") or "").strip()
            if not code:
                continue
            index.setdefault(code, []).append({"voice": voice, "need": need})
    return {key: tuple(value) for key, value in index.items()}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise EvidenceAccessError(f"无法读取 JSONL：{path}") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvidenceAccessError(f"JSONL 第 {line_number} 行无效：{path}") from exc
        if not isinstance(row, dict):
            raise EvidenceAccessError(f"JSONL 第 {line_number} 行必须为对象：{path}")
        rows.append(row)
    return rows


def _cursor(value: str | None, queue_hash: str, row_count: int) -> int:
    if not value:
        return 0
    try:
        cursor = json.loads(value)
    except json.JSONDecodeError as exc:
        raise EvidenceAccessError("cursor 必须是上一页返回的 JSON 对象") from exc
    if not isinstance(cursor, Mapping) or cursor.get("queue_sha256") != queue_hash:
        raise EvidenceAccessError("cursor 与当前队列快照不匹配；请从新队列的第一页重新开始")
    offset = cursor.get("offset")
    if not isinstance(offset, int) or not 0 <= offset <= row_count:
        raise EvidenceAccessError("cursor.offset 无效")
    return offset


def _public_record(row: Mapping[str, Any], index: int) -> dict[str, Any]:
    return {
        "index": index,
        "record_id": row.get("record_id"),
        "cache_key": row.get("cache_key"),
        "hard_identity": row.get("hard_identity"),
        "platform": row.get("platform"),
        "source_kind": row.get("source_kind"),
    }


def page_queue(
    queue_path: Path,
    *,
    cursor: str | None,
    limit: int,
    max_chars: int,
    acknowledge_cache_key: str | None = None,
) -> dict[str, Any]:
    if not 1 <= limit <= MAX_LOOKUP_LIMIT:
        raise EvidenceAccessError(f"limit 必须在 1 到 {MAX_LOOKUP_LIMIT} 之间")
    if max_chars < 1:
        raise EvidenceAccessError("max-chars 必须大于 0")
    queue_path = queue_path.expanduser().resolve()
    queue_hash = _sha256(queue_path)
    rows = _load_jsonl(queue_path)
    offset = _cursor(cursor, queue_hash, len(rows))
    if acknowledge_cache_key:
        if offset >= len(rows) or rows[offset].get("cache_key") != acknowledge_cache_key:
            raise EvidenceAccessError("acknowledge-cache-key 必须匹配当前 cursor 指向的超长记录")
        offset += 1
    page: list[dict[str, Any]] = []
    serialized_chars = 0
    oversized: dict[str, Any] | None = None
    index = offset
    while index < len(rows) and len(page) < limit:
        row = rows[index]
        row_chars = len(_canonical(row))
        if row_chars > max_chars:
            oversized = {
                **_public_record(row, index),
                "serialized_chars": row_chars,
                "status": "oversized",
                "instruction": "请先使用 read-record 完整分段读取该记录，再以 acknowledge-cache-key 确认继续。",
            }
            break
        if page and serialized_chars + row_chars > max_chars:
            break
        page.append(row)
        serialized_chars += row_chars
        index += 1
    next_offset = index
    return {
        "schema_version": "consumer-evidence-page-1.0",
        "queue": str(queue_path),
        "queue_sha256": queue_hash,
        "row_count": len(rows),
        "records": page,
        "serialized_chars": serialized_chars,
        "oversized": oversized,
        "next_cursor": {"queue_sha256": queue_hash, "offset": next_offset},
        "has_more": next_offset < len(rows),
    }


def _find_row(rows: Iterable[Mapping[str, Any]], key: str, *, fields: Sequence[str]) -> Mapping[str, Any]:
    matches = [row for row in rows if any(str(row.get(field) or "") == key for field in fields)]
    if len(matches) != 1:
        raise EvidenceAccessError("未找到唯一记录，或记录标识重复")
    return matches[0]


def _segment(value: Mapping[str, Any], *, start: int, length: int) -> dict[str, Any]:
    serialized = _canonical(value)
    if start < 0 or not 1 <= length <= DEFAULT_MAX_CHARS or start > len(serialized):
        raise EvidenceAccessError("start 或 length 无效")
    end = min(len(serialized), start + length)
    return {
        "record_id": value.get("record_id") or value.get("voice_id"),
        "cache_key": value.get("cache_key"),
        "sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        "serialized_chars": len(serialized),
        "start": start,
        "end": end,
        "complete": end == len(serialized),
        "json_fragment": serialized[start:end],
    }


def read_queue_record(queue_path: Path, key: str, *, start: int, length: int) -> dict[str, Any]:
    row = _find_row(_load_jsonl(queue_path.expanduser().resolve()), key, fields=("cache_key", "record_id", "hard_identity"))
    return _segment(row, start=start, length=length)


def _need_summary(analysis: Mapping[str, Any]) -> list[dict[str, Any]]:
    readiness = analysis.get("evidence_readiness")
    needs = readiness.get("needs", []) if isinstance(readiness, Mapping) else []
    result = []
    for item in needs if isinstance(needs, list) else []:
        if not isinstance(item, Mapping):
            continue
        result.append({
            "code": item.get("code"), "label": item.get("label"), "count": item.get("count"),
            "eligible": item.get("eligible"), "known_authors": item.get("known_authors"),
            "contexts": item.get("contexts"), "channels": item.get("channels"),
            "segment_ids": item.get("segment_ids"), "gaps": item.get("gaps"),
            "support_count": len(item.get("support_refs", [])) if isinstance(item.get("support_refs"), list) else 0,
            "counter_count": len(item.get("counter_refs", [])) if isinstance(item.get("counter_refs"), list) else 0,
        })
    return result


def build_workshop_index(coding_path: Path, analysis_path: Path, output_path: Path) -> dict[str, Any]:
    coding_path, analysis_path, output_path = (path.expanduser().resolve() for path in (coding_path, analysis_path, output_path))
    coding = _load_json(coding_path)
    analysis = _load_json(analysis_path)
    voices = coding.get("voices")
    if not isinstance(voices, list):
        raise EvidenceAccessError("Coding.voices 必须为数组")
    voice_index: list[dict[str, Any]] = []
    for row in voices:
        if not isinstance(row, Mapping) or not row.get("voice_id"):
            raise EvidenceAccessError("Coding.voices 缺少 voice_id")
        needs = row.get("needs") if isinstance(row.get("needs"), list) else []
        voice_index.append({
            "voice_id": row.get("voice_id"), "cache_key": row.get("cache_key"),
            "platform": row.get("platform"), "source_kind": row.get("source_kind"),
            "segment_ids": row.get("segment_memberships", []),
            "needs": [{"code": need.get("code"), "stance": need.get("stance"), "applicability": need.get("applicability")} for need in needs if isinstance(need, Mapping)],
        })
    document = {
        "schema_version": "consumer-workshop-evidence-index-1.0",
        "coding_path": str(coding_path), "coding_sha256": _sha256(coding_path),
        "analysis_path": str(analysis_path), "analysis_sha256": _sha256(analysis_path),
        "needs": _need_summary(analysis), "voices": voice_index,
        "instruction": "索引只用于定位。读取原声、反证和保存语境时，必须通过 consumer_evidence_access.py 查询固定的 Coding 或只读源数据库。",
    }
    _atomic_json(output_path, document)
    return {"status": "ok", "index_path": str(output_path), "index_sha256": _sha256(output_path), "voice_count": len(voice_index)}


def _coding_voices(coding_path: Path) -> tuple[Mapping[str, Any], list[Mapping[str, Any]]]:
    path = coding_path.expanduser().resolve()
    snapshot_sha256 = _sha256(path)
    coding, voices = _cached_coding(str(path), snapshot_sha256)
    return coding, list(voices)


def read_voice(coding_path: Path, voice_id: str, *, start: int, length: int) -> dict[str, Any]:
    _coding, voices = _coding_voices(coding_path)
    return _segment(_find_row(voices, voice_id, fields=("voice_id",)), start=start, length=length)


def read_voices(coding_path: Path, voice_ids: Sequence[str], *, start: int, length: int) -> dict[str, Any]:
    """Read a bounded batch from one verified snapshot without reparsing it."""
    if not 1 <= len(voice_ids) <= MAX_LOOKUP_LIMIT or len(set(voice_ids)) != len(voice_ids):
        raise EvidenceAccessError(f"voice_ids 必须是 1 到 {MAX_LOOKUP_LIMIT} 个不重复 ID")
    _coding, voices = _coding_voices(coding_path)
    by_id = {str(row.get("voice_id")): row for row in voices}
    if set(voice_ids) - set(by_id):
        raise EvidenceAccessError("存在未找到的 voice_id")
    return {"coding_sha256": _sha256(coding_path.expanduser().resolve()),
            "records": [_segment(by_id[voice_id], start=start, length=length) for voice_id in voice_ids]}


def query_need(coding_path: Path, need_code: str, *, stance: str, segment_id: str | None, limit: int,
               cursor: str | None = None) -> dict[str, Any]:
    if stance not in {"all", "support", "counter", "mixed"}:
        raise EvidenceAccessError("stance 只能是 all、support、counter 或 mixed")
    if not 1 <= limit <= DEFAULT_LIMIT:
        raise EvidenceAccessError(f"limit 必须在 1 到 {DEFAULT_LIMIT} 之间")
    path = coding_path.expanduser().resolve()
    snapshot_sha256 = _sha256(path)
    index = _cached_need_index(str(path), snapshot_sha256)
    rows = []
    for item in index.get(need_code, ()):
        voice, need = item["voice"], item["need"]
        if segment_id and segment_id not in voice.get("segment_memberships", []):
            continue
        need_stance = need.get("stance")
        if stance != "all" and need_stance != stance and not (stance in {"support", "counter"} and need_stance == "mixed"):
            continue
        rows.append({
            "voice_id": voice.get("voice_id"), "platform": voice.get("platform"),
            "source_kind": voice.get("source_kind"), "segment_ids": voice.get("segment_memberships", []),
            "need": {key: need.get(key) for key in ("need_id", "code", "label", "stance", "applicability", "quote", "alternative_explanations")},
        })
    rows.sort(key=lambda row: str(row["voice_id"]))
    offset = 0
    if cursor:
        try:
            value = json.loads(cursor)
        except json.JSONDecodeError as exc:
            raise EvidenceAccessError("cursor 必须是上一页返回的 JSON 对象") from exc
        expected = {"coding_sha256": snapshot_sha256, "need_code": need_code, "stance": stance, "segment_id": segment_id}
        if not isinstance(value, Mapping) or any(value.get(key) != expected[key] for key in expected):
            raise EvidenceAccessError("cursor 与当前 Coding 快照或查询条件不匹配")
        offset = value.get("offset")
        if not isinstance(offset, int) or not 0 <= offset <= len(rows):
            raise EvidenceAccessError("cursor.offset 无效")
    end = min(offset + limit, len(rows))
    next_cursor = {"coding_sha256": snapshot_sha256, "need_code": need_code, "stance": stance,
                   "segment_id": segment_id, "offset": end}
    return {"need_code": need_code, "stance": stance, "segment_id": segment_id, "coding_sha256": snapshot_sha256,
            "total": len(rows), "records": rows[offset:end], "next_cursor": next_cursor,
            "has_more": end < len(rows), "truncated": end < len(rows)}


def _readonly_context(coding_path: Path, voice_id: str, source_db: Path, *, start: int, length: int) -> dict[str, Any]:
    coding, voices = _coding_voices(coding_path)
    voice = _find_row(voices, voice_id, fields=("voice_id",))
    expected_hash = str(coding.get("metadata", {}).get("source_db_sha256") or "")
    source_db = source_db.expanduser().resolve()
    if not expected_hash:
        raise EvidenceAccessError("Coding 缺少 source_db_sha256，不能读取外部保存语境")
    if _sha256(source_db) != expected_hash:
        raise EvidenceAccessError("source-db 哈希与 Coding 快照不一致")
    connection = sqlite3.connect(f"{source_db.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        source_row = connection.execute("SELECT * FROM comments WHERE record_id=?", (voice_id,)).fetchone()
        if source_row is None:
            raise EvidenceAccessError("source-db 中不存在该 voice_id")
        row = dict(source_row)
        source = str(row.get("source") or "unknown")
        saved: list[dict[str, str]] = []
        parent_id = str(row.get("parent_content_id") or "")
        seen: set[str] = set()
        for _ in range(8):
            if not parent_id or parent_id in seen:
                break
            seen.add(parent_id)
            matches = connection.execute("SELECT * FROM comments WHERE source=? AND content_id=?", (source, parent_id)).fetchall()
            if source.casefold() in {"web", "blog", "forum"}:
                host = urlsplit(str(row.get("canonical_url") or "")).netloc.casefold()
                matches = [candidate for candidate in matches if host and urlsplit(str(dict(candidate).get("canonical_url") or "")).netloc.casefold() == host]
            parent = matches[0] if len(matches) == 1 else None
            if parent is None:
                break
            parent_row = dict(parent)
            saved.append({"record_id": str(parent_row.get("record_id")), "text": str(parent_row.get("text") or "")})
            parent_id = str(parent_row.get("parent_content_id") or "")
        try:
            raw = json.loads(str(row.get("raw_json") or "{}"))
        except json.JSONDecodeError:
            raw = {}
        if isinstance(raw, Mapping):
            for key in ("product_title", "thread_title", "video_title", "parent_text"):
                text = str(raw.get(key) or "").strip()
                if text:
                    saved.append({"record_id": f"{voice_id}:{key}", "text": text})
        document = {"voice_id": voice_id, "full_text": voice.get("full_text"), "saved_context": saved}
        return {"source_db": str(source_db), "source_db_sha256": expected_hash, **_segment(document, start=start, length=length)}
    finally:
        connection.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="消费者编码队列与工作坊证据的只读分页工具")
    commands = parser.add_subparsers(dest="command", required=True)
    page = commands.add_parser("page-queue", help="按固定快照分页读取 JSONL 队列")
    page.add_argument("--queue", required=True, type=Path)
    page.add_argument("--cursor")
    page.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    page.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    page.add_argument("--acknowledge-cache-key")
    record = commands.add_parser("read-record", help="分段读取超长队列记录")
    record.add_argument("--queue", required=True, type=Path)
    record.add_argument("--key", required=True)
    record.add_argument("--start", type=int, default=0)
    record.add_argument("--length", type=int, default=DEFAULT_MAX_CHARS)
    index = commands.add_parser("build-workshop-index", help="生成不含全文的工作坊外置证据索引")
    index.add_argument("--coding", required=True, type=Path)
    index.add_argument("--analysis", required=True, type=Path)
    index.add_argument("--output", required=True, type=Path)
    voice = commands.add_parser("read-voice", help="分段读取 Coding 中的单条原声")
    voice.add_argument("--coding", required=True, type=Path)
    voice.add_argument("--voice-id", required=True)
    voice.add_argument("--start", type=int, default=0)
    voice.add_argument("--length", type=int, default=DEFAULT_MAX_CHARS)
    voices = commands.add_parser("read-voices", help="从同一 Coding 快照分段读取多条原声")
    voices.add_argument("--coding", required=True, type=Path)
    voices.add_argument("--voice-id", action="append", dest="voice_ids", required=True)
    voices.add_argument("--start", type=int, default=0)
    voices.add_argument("--length", type=int, default=DEFAULT_MAX_CHARS)
    need = commands.add_parser("query-need", help="按需求查询最小证据定位信息")
    need.add_argument("--coding", required=True, type=Path)
    need.add_argument("--need-code", required=True)
    need.add_argument("--stance", choices=("all", "support", "counter", "mixed"), default="all")
    need.add_argument("--segment-id")
    need.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    need.add_argument("--cursor")
    context = commands.add_parser("read-source-context", help="从匹配快照的只读源数据库读取保存语境")
    context.add_argument("--coding", required=True, type=Path)
    context.add_argument("--voice-id", required=True)
    context.add_argument("--source-db", required=True, type=Path)
    context.add_argument("--start", type=int, default=0)
    context.add_argument("--length", type=int, default=DEFAULT_MAX_CHARS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "page-queue":
            result = page_queue(args.queue, cursor=args.cursor, limit=args.limit, max_chars=args.max_chars, acknowledge_cache_key=args.acknowledge_cache_key)
        elif args.command == "read-record":
            result = read_queue_record(args.queue, args.key, start=args.start, length=args.length)
        elif args.command == "build-workshop-index":
            result = build_workshop_index(args.coding, args.analysis, args.output)
        elif args.command == "read-voice":
            result = read_voice(args.coding, args.voice_id, start=args.start, length=args.length)
        elif args.command == "read-voices":
            result = read_voices(args.coding, args.voice_ids, start=args.start, length=args.length)
        elif args.command == "query-need":
            result = query_need(args.coding, args.need_code, stance=args.stance, segment_id=args.segment_id, limit=args.limit, cursor=args.cursor)
        else:
            result = _readonly_context(args.coding, args.voice_id, args.source_db, start=args.start, length=args.length)
    except EvidenceAccessError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "ok", **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
