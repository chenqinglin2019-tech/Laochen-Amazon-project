#!/usr/bin/env python3
"""Read-only wall-clock attribution for one finished or running task directory.

Answers one question: where did the wall time go? It separates time spent
inside timed program steps (source calls, hosts, review sessions) from the
remaining time (model authoring, harness and idle), and attributes that
remaining time to the kind of ledger record written right after it.

This helper never writes into the task directory, never opens credential
files, never changes a business state and is not a gate. Timestamps come only
from run-time event fields (``*_at`` written by the program) and from
``runtime-timings.jsonl``; publication or source dates are never used.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

TIMINGS = "runtime-timings.jsonl"
SKIP_DIRS = {"raw", "images", "screenshots", "node_modules", ".git", "__pycache__"}
SKIP_FILES = {".env", "config.json", "config.local.json", TIMINGS}
MAX_FILE_BYTES = 256 * 1024 * 1024
TIME_KEY_SUFFIX = "_at"
TIME_KEYS_EXACT = {"at", "timestamp"}
# Run-time identity fields that carry no event meaning of their own.
IGNORED_KEYS = {"as_of", "assessment_at", "valid_at", "expires_at", "expiry_at", "published_at",
                "filed_at", "granted_at", "priority_at", "source_updated_at", "source_checked_at"}
DEFAULT_IDLE_CAP_SECONDS = 900
# Original source material: its timestamps are source data, never run events.
ORIGINAL_FIELDS = {"payload", "record_fields", "source_record", "raw_response", "response", "body", "data",
                   "status_history", "legal_events"}


def parse_ts(value):
    """Return an aware UTC datetime for a full ISO date-time string, else None."""
    if not isinstance(value, str) or len(value) < 16 or "T" not in value and " " not in value:
        return None
    text = value.strip().replace("Z", "+00:00").replace("z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_time_key(key):
    return isinstance(key, str) and key not in IGNORED_KEYS and (
        key in TIME_KEYS_EXACT or key.endswith(TIME_KEY_SUFFIX))


def walk_events(node, path, file_label, out, intervals):
    """Collect (timestamp, label) points and (start, end, label) intervals from nested JSON."""
    if isinstance(node, dict):
        stamps = {}
        for key, value in node.items():
            if _is_time_key(key):
                parsed = parse_ts(value)
                if parsed is not None:
                    stamps[key] = parsed
        label = file_label + (":" + path if path else "")
        started, finished = stamps.get("started_at"), stamps.get("finished_at")
        if started is not None and finished is not None and finished >= started:
            intervals.append((started, finished, label))
        for key, parsed in stamps.items():
            out.append((parsed, label, key))
        for key, value in node.items():
            if isinstance(value, (dict, list)) and key not in ORIGINAL_FIELDS:
                walk_events(value, (path + "." if path else "") + str(key), file_label, out, intervals)
    elif isinstance(node, list):
        for item in node:
            if isinstance(item, (dict, list)):
                walk_events(item, path + "[]", file_label, out, intervals)


def _iter_json_files(root):
    for path in sorted(root.iterdir()):
        if path.name in SKIP_FILES or path.name.startswith("."):
            continue
        if path.is_dir() or path.is_symlink() or path.suffix.lower() not in {".json", ".jsonl"}:
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        yield path


def _load(path):
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    if path.suffix.lower() == ".jsonl":
        rows = []
        for line in text.splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        return rows
    try:
        return json.loads(text)
    except ValueError:
        return None


def merge_intervals(intervals):
    ordered = sorted((s, e) for s, e, *_ in intervals)
    merged = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def overlap_seconds(start, end, merged):
    total = 0.0
    for left, right in merged:
        if right <= start:
            continue
        if left >= end:
            break
        total += (min(end, right) - max(start, left)).total_seconds()
    return total


def attribute(events, machine, idle_cap):
    """Attribute each gap before an event to that event's record kind."""
    ordered = sorted(events, key=lambda row: row[0])
    merged = merge_intervals(machine)
    buckets = {}
    gaps = []
    previous = None
    for stamp, label, key in ordered:
        if previous is not None and stamp > previous[0]:
            span = (stamp - previous[0]).total_seconds()
            machine_s = overlap_seconds(previous[0], stamp, merged)
            other_s = max(0.0, span - machine_s)
            idle_s = max(0.0, other_s - idle_cap)
            other_s -= idle_s
            row = buckets.setdefault(label, {"label": label, "events": 0, "agent_seconds": 0.0,
                                             "machine_seconds": 0.0, "idle_over_cap_seconds": 0.0})
            row["agent_seconds"] += other_s
            row["machine_seconds"] += machine_s
            row["idle_over_cap_seconds"] += idle_s
            gaps.append({"seconds": round(span, 1), "machine_seconds": round(machine_s, 1),
                         "from": previous[1], "to": label, "at": stamp.isoformat()})
        row = buckets.setdefault(label, {"label": label, "events": 0, "agent_seconds": 0.0,
                                         "machine_seconds": 0.0, "idle_over_cap_seconds": 0.0})
        row["events"] += 1
        previous = (stamp, label)
    gaps.sort(key=lambda g: -g["seconds"])
    return buckets, gaps


def plan_duplicates(plan):
    """Physical duplicates in a search plan: same provider/operation/request parameters."""
    queries = plan.get("queries") if isinstance(plan, dict) else None
    if not isinstance(queries, dict):
        return None
    meta_keys = {"query_id", "purpose_id", "derived_from", "requirement_ids", "right_type", "jurisdiction",
                 "scenario_id", "scenario_sha256", "discovery_scope", "execute_by_default", "required",
                 "required_for", "wave", "execution_phase", "search_dimension", "search_language",
                 "reason", "operation", "provider", "api_gap_revision", "gap_reason", "judgment_impact",
                 "product_dependencies", "object_ids", "term_ref", "dimension", "request_class", "route_role"}
    country_keys = {"country", "gl", "hl", "jurisdiction", "office", "offices"}
    exact, languageless = {}, {}
    total = 0
    lens = {"rows": 0, "countries": set(), "images": set()}
    for provider, rows in queries.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            total += 1
            params = row.get("params") if isinstance(row.get("params"), dict) else {
                k: v for k, v in row.items() if k not in meta_keys}
            canon = json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)
            operation = row.get("operation") or ""
            exact.setdefault((provider, operation, canon), []).append(row.get("jurisdiction") or params.get("country"))
            stripped = {k: v for k, v in params.items() if k not in country_keys}
            languageless.setdefault((provider, operation, json.dumps(stripped, sort_keys=True, ensure_ascii=False, default=str)),
                                    []).append(row.get("jurisdiction") or params.get("country"))
            if provider == "serpapi_google_lens":
                lens["rows"] += 1
                lens["countries"].add(str(params.get("country") or row.get("jurisdiction") or ""))
                lens["images"].add(str(params.get("image_url") or params.get("q") or ""))
    def groups(table):
        return sorted(({"provider": k[0], "operation": k[1], "rows": len(v), "jurisdictions": sorted({str(x) for x in v if x}),
                        "request": k[2][:160]} for k, v in table.items() if len(v) > 1), key=lambda g: -g["rows"])
    exact_groups, loose_groups = groups(exact), groups(languageless)
    return {"plan_rows": total, "distinct_physical_requests": len(exact),
            "exact_duplicate_rows": sum(g["rows"] - 1 for g in exact_groups),
            "same_request_other_country_rows": sum(g["rows"] - 1 for g in loose_groups),
            "lens": {"rows": lens["rows"], "countries": sorted(c for c in lens["countries"] if c),
                     "distinct_images": len([i for i in lens["images"] if i])},
            "exact_duplicate_groups": exact_groups[:10], "country_variant_groups": loose_groups[:10]}


def analyse(run_dir, idle_cap=DEFAULT_IDLE_CAP_SECONDS):
    root = Path(run_dir).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit("RUN_DIR_NOT_FOUND")
    events, intervals, timing_rows = [], [], []
    created = None
    plan = None
    notes = []
    for path in _iter_json_files(root):
        data = _load(path)
        if data is None:
            notes.append("UNREADABLE:" + path.name)
            continue
        if path.name == "task.json" and isinstance(data, dict):
            created = parse_ts(data.get("created_at")) or created
        if path.name == "search-plan.json":
            plan = data
        walk_events(data, "", path.name, events, intervals)
    timings_path = root / TIMINGS
    if timings_path.is_file() and not timings_path.is_symlink():
        for row in _load(timings_path) or []:
            if not isinstance(row, dict):
                continue
            started, finished = parse_ts(row.get("started_at")), parse_ts(row.get("finished_at"))
            if started is not None and finished is not None and finished >= started:
                timing_rows.append((started, finished, str(row.get("stage") or "unknown"), row))
    if created is not None:
        low, high = created - timedelta(hours=1), datetime.now(timezone.utc) + timedelta(days=1)
        events = [e for e in events if low <= e[0] <= high]
        intervals = [i for i in intervals if low <= i[0] <= high]
        timing_rows = [t for t in timing_rows if low <= t[0] <= high]
    machine = [(s, e, label) for s, e, label in intervals if label.startswith("evidence.json:source_runs")]
    machine += [(s, e, "timing:" + stage) for s, e, stage, _ in timing_rows]
    points = list(events) + [(f, "timing:" + st + ":end", "finished_at") for _, f, st, _ in timing_rows]
    if not points:
        return {"schema": "IPR-TIMING-ATTRIBUTION/1.0", "error": "NO_TIMESTAMPS_FOUND", "notes": notes}
    first = min(p[0] for p in points)
    last = max(p[0] for p in points)
    wall = (last - first).total_seconds()
    merged = merge_intervals(machine)
    machine_union = sum((e - s).total_seconds() for s, e in merged)
    buckets, gaps = attribute(points, machine, idle_cap)
    by_stage = {}
    for _, _, stage, row in timing_rows:
        item = by_stage.setdefault(stage, {"stage": stage, "runs": 0, "seconds": 0.0})
        item["runs"] += 1
        item["seconds"] += float(row.get("elapsed_ms") or 0) / 1000.0
    rows = sorted(buckets.values(), key=lambda r: -(r["agent_seconds"] + r["machine_seconds"]))
    agent_total = sum(r["agent_seconds"] for r in rows)
    idle_total = sum(r["idle_over_cap_seconds"] for r in rows)
    active = max(0.0, wall - idle_total)
    budget = None
    budget_path = root / "execution-budget.json"
    if budget_path.is_file():
        data = _load(budget_path)
        if isinstance(data, dict):
            budget = {k: data.get(k) for k in ("used_seconds", "review_used_seconds", "invocations")}
    result = {
        "schema": "IPR-TIMING-ATTRIBUTION/1.0", "auxiliary_only": True,
        "first_event": first.isoformat(), "last_event": last.isoformat(),
        "wall_seconds": round(wall, 1), "active_seconds": round(active, 1),
        "machine_seconds_union": round(machine_union, 1),
        "agent_or_harness_seconds": round(agent_total, 1),
        "idle_over_cap_seconds": round(idle_total, 1), "idle_cap_seconds": idle_cap,
        "machine_share": round(machine_union / active, 3) if active > 0 else None,
        "budget_journal": budget,
        "timed_steps_by_stage": sorted(({**v, "seconds": round(v["seconds"], 1)} for v in by_stage.values()),
                                       key=lambda v: -v["seconds"]),
        "by_record_kind": [{**r, "agent_seconds": round(r["agent_seconds"], 1),
                            "machine_seconds": round(r["machine_seconds"], 1),
                            "idle_over_cap_seconds": round(r["idle_over_cap_seconds"], 1)} for r in rows[:30]],
        "largest_gaps": gaps[:10],
        "plan_duplicates": plan_duplicates(plan) if plan is not None else None,
        "notes": notes,
        "meaning": ("Auxiliary diagnostics only. Gaps are attributed to the record kind written right after them; "
                    "batch writes put the preceding gap on the first record. Not a gate and not a business fact."),
    }
    return result


def render_text(result):
    if result.get("error"):
        return "没有找到可用时间戳：" + str(result["error"])
    lines = []
    active = result["active_seconds"]
    lines.append("活动窗口：%.0f 秒（%.1f 分钟）；其中程序计时步骤并集 %.0f 秒（%s），其余（模型书写/宿主）%.0f 秒"
                 % (active, active / 60.0, result["machine_seconds_union"],
                    "%.0f%%" % (result["machine_share"] * 100) if result["machine_share"] is not None else "-",
                    result["agent_or_harness_seconds"]))
    if result["idle_over_cap_seconds"]:
        lines.append("首尾墙钟 %.0f 秒；另有 %.0f 秒是超过 %d 秒的单段空闲，未计入活动窗口"
                     % (result["wall_seconds"], result["idle_over_cap_seconds"], result["idle_cap_seconds"]))
    if result.get("budget_journal"):
        lines.append("预算日志：%s" % json.dumps(result["budget_journal"], ensure_ascii=False))
    lines.append("")
    lines.append("按账本记录类型归因（其后紧邻的间隔）：")
    lines.append("%-62s %6s %9s %9s" % ("记录类型", "条数", "书写秒", "程序秒"))
    for row in result["by_record_kind"][:20]:
        lines.append("%-62s %6d %9.0f %9.0f" % (row["label"][:62], row["events"], row["agent_seconds"], row["machine_seconds"]))
    if result["timed_steps_by_stage"]:
        lines.append("")
        lines.append("程序计时步骤（runtime-timings.jsonl）：")
        for row in result["timed_steps_by_stage"][:12]:
            lines.append("  %-34s %4d 次  %8.0f 秒" % (row["stage"], row["runs"], row["seconds"]))
    if result["largest_gaps"]:
        lines.append("")
        lines.append("最长的 5 段间隔：")
        for gap in result["largest_gaps"][:5]:
            lines.append("  %8.0f 秒（程序 %.0f）  %s → %s" % (gap["seconds"], gap["machine_seconds"], gap["from"][:40], gap["to"][:40]))
    dup = result.get("plan_duplicates")
    if dup:
        lines.append("")
        lines.append("取数计划：%d 行，%d 个不同物理请求；完全相同重复 %d 行；仅国家参数不同 %d 行；Lens %d 行/%d 国/%d 张图"
                     % (dup["plan_rows"], dup["distinct_physical_requests"], dup["exact_duplicate_rows"],
                        dup["same_request_other_country_rows"], dup["lens"]["rows"], len(dup["lens"]["countries"]),
                        dup["lens"]["distinct_images"]))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only wall-clock attribution for a task directory")
    parser.add_argument("--run-dir", "--task-dir", dest="run_dir", required=True)
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--idle-cap", type=int, default=DEFAULT_IDLE_CAP_SECONDS,
                        help="single gaps longer than this many seconds are reported as idle, not authoring")
    args = parser.parse_args(argv)
    if args.idle_cap <= 0:
        parser.error("--idle-cap must be positive")
    result = analyse(args.run_dir, args.idle_cap)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else render_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
