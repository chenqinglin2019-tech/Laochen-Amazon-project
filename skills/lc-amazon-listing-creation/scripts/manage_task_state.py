#!/usr/bin/env python3
"""Persist task snapshots and retry-stable SKU reservations in the project state DB."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from manage_template_library import (
    DB_RELATIVE_PATH,
    LibraryError,
    connect_database,
    sha256_file,
    utc_now,
    validate_processing_report_evidence,
)

RESULT_STATUSES = (
    "DRAFT_NOT_FOR_UPLOAD",
    "LOCAL_VALIDATION_PASSED",
    "ACCEPTED_USER_CONFIRMED",
    "ACCEPTED_REPORT_VERIFIED",
)
SKU_STATUSES = ("reserved", "validated", "committed")
ROLES = ("Parent", "Child", "Standalone")


def ensure_task_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            scope_json TEXT NOT NULL,
            input_snapshot_json TEXT NOT NULL,
            mapping_sha256 TEXT,
            output_path TEXT,
            output_sha256 TEXT,
            acceptance_evidence_path TEXT,
            acceptance_note TEXT,
            result_status TEXT NOT NULL CHECK (
                result_status IN (
                    'DRAFT_NOT_FOR_UPLOAD',
                    'LOCAL_VALIDATION_PASSED',
                    'ACCEPTED_USER_CONFIRMED',
                    'ACCEPTED_REPORT_VERIFIED'
                )
            ),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sku_reservations (
            id INTEGER PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK (role IN ('Parent', 'Child', 'Standalone')),
            source_key TEXT NOT NULL,
            sku TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL CHECK (status IN ('reserved', 'validated', 'committed')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(task_id, role, source_key)
        );
        CREATE INDEX IF NOT EXISTS idx_sku_task ON sku_reservations(task_id, status);
        """
    )
    task_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
    }
    for column in (
        "output_path",
        "output_sha256",
        "acceptance_evidence_path",
        "acceptance_note",
    ):
        if column not in task_columns:
            connection.execute(f"ALTER TABLE tasks ADD COLUMN {column} TEXT")
    connection.commit()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_json_argument(raw: str) -> Any:
    if raw.startswith("@"):
        return json.loads(Path(raw[1:]).expanduser().read_text(encoding="utf-8"))
    return json.loads(raw)


def save_task(
    project_root: Path,
    task_id: str,
    scope: dict[str, Any],
    snapshot: dict[str, Any],
    result_status: str,
    mapping_sha256: str | None = None,
) -> dict[str, Any]:
    if not task_id.strip():
        raise LibraryError("task_id must not be empty")
    required_scope = (
        "marketplace",
        "content_language",
        "product_type",
        "browse_node",
        "fill_mode",
    )
    missing = [key for key in required_scope if not str(scope.get(key, "")).strip()]
    if missing:
        raise LibraryError("Task scope is incomplete: " + ", ".join(missing))
    if result_status != "DRAFT_NOT_FOR_UPLOAD":
        raise LibraryError("A new task must start as DRAFT_NOT_FOR_UPLOAD")
    product_snapshot = snapshot.get("product") if isinstance(snapshot, dict) else None
    if not isinstance(product_snapshot, dict):
        raise LibraryError("Task snapshot must contain product.path and product.sha256")
    product_path_raw = product_snapshot.get("path")
    product_hash = product_snapshot.get("sha256")
    if not isinstance(product_path_raw, str) or not Path(product_path_raw).expanduser().is_absolute():
        raise LibraryError("Task snapshot product.path must be an absolute path")
    product_path = Path(product_path_raw).expanduser().resolve()
    if any(
        parent.name in {"空白模板库", "样板模板库"}
        for parent in (product_path, *product_path.parents)
    ):
        raise LibraryError("Task product input cannot come from either template library")
    if (
        not product_path.is_file()
        or product_path.suffix.casefold() not in {".xlsx", ".xlsm"}
        or not isinstance(product_hash, str)
        or sha256_file(product_path) != product_hash
    ):
        raise LibraryError("Task snapshot product file is missing or its SHA-256 does not match")
    template_snapshot = snapshot.get("templates") if isinstance(snapshot, dict) else None
    if not isinstance(template_snapshot, dict):
        raise LibraryError("Task snapshot must contain the selected templates metadata")
    blank_entry_id = template_snapshot.get("blank_entry_id")
    if isinstance(blank_entry_id, bool) or not isinstance(blank_entry_id, int):
        raise LibraryError("Task template snapshot must contain integer blank_entry_id")
    for key in ("blank_sha256", "blank_schema_fingerprint"):
        if not isinstance(template_snapshot.get(key), str) or not template_snapshot[key].strip():
            raise LibraryError(f"Task template snapshot must contain {key}")
    if scope.get("fill_mode") == "SAMPLE_GUIDED":
        sample_entry_id = template_snapshot.get("sample_entry_id")
        if isinstance(sample_entry_id, bool) or not isinstance(sample_entry_id, int):
            raise LibraryError("SAMPLE_GUIDED task snapshot must contain integer sample_entry_id")
        for key in ("sample_sha256", "sample_verification", "sample_schema_compatibility"):
            if not isinstance(template_snapshot.get(key), str) or not template_snapshot[key].strip():
                raise LibraryError(f"SAMPLE_GUIDED task snapshot must contain {key}")
    connection = connect_database(project_root)
    try:
        ensure_task_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        scope_json = canonical_json(scope)
        snapshot_json = canonical_json(snapshot)
        existing = connection.execute(
            "SELECT scope_json, input_snapshot_json, result_status FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if existing is not None:
            if existing["scope_json"] != scope_json:
                raise LibraryError("Retry cannot change the scope of an existing task_id")
            if existing["input_snapshot_json"] != snapshot_json:
                raise LibraryError("Retry cannot change the input snapshot of an existing task_id")
            if mapping_sha256:
                connection.execute(
                    "UPDATE tasks SET mapping_sha256 = ?, updated_at = ? WHERE task_id = ?",
                    (mapping_sha256, utc_now(), task_id),
                )
            connection.commit()
            return {
                "task_id": task_id,
                "scope": scope,
                "snapshot_sha256": sha256_json(snapshot),
                "result_status": existing["result_status"],
                "database": str(project_root / DB_RELATIVE_PATH),
                "retry": True,
            }
        now = utc_now()
        connection.execute(
            """
            INSERT INTO tasks(task_id, scope_json, input_snapshot_json, mapping_sha256,
                              result_status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                scope_json,
                snapshot_json,
                mapping_sha256,
                result_status,
                now,
                now,
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {
        "task_id": task_id,
        "scope": scope,
        "snapshot_sha256": sha256_json(snapshot),
        "result_status": result_status,
        "database": str(project_root / DB_RELATIVE_PATH),
        "retry": False,
    }


def reserve_sku(project_root: Path, task_id: str, role: str, source_key: str, sku: str) -> dict[str, Any]:
    source_key = source_key.strip()
    sku = sku.strip()
    if not source_key or not sku:
        raise LibraryError("source_key and sku must not be empty")
    connection = connect_database(project_root)
    try:
        ensure_task_schema(connection)
        task = connection.execute("SELECT task_id FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if task is None:
            raise LibraryError(f"Task does not exist; save it before reserving SKUs: {task_id}")
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT * FROM sku_reservations WHERE task_id = ? AND role = ? AND source_key = ?",
            (task_id, role, source_key),
        ).fetchone()
        if existing is not None:
            if existing["sku"] != sku:
                raise LibraryError(
                    f"Retry must reuse reserved SKU {existing['sku']} for {role}/{source_key}; received {sku}"
                )
            connection.commit()
            return dict(existing)
        collision = connection.execute(
            "SELECT task_id, role, source_key FROM sku_reservations WHERE sku = ?", (sku,)
        ).fetchone()
        if collision is not None:
            raise LibraryError(
                f"SKU already reserved by task {collision['task_id']} "
                f"for {collision['role']}/{collision['source_key']}: {sku}"
            )
        now = utc_now()
        cursor = connection.execute(
            "INSERT INTO sku_reservations(task_id, role, source_key, sku, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'reserved', ?, ?)",
            (task_id, role, source_key, sku, now, now),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM sku_reservations WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return dict(row)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def set_task_skus_status(project_root: Path, task_id: str, status: str) -> dict[str, Any]:
    connection = connect_database(project_root)
    try:
        ensure_task_schema(connection)
        current = connection.execute(
            "SELECT status, COUNT(*) AS count FROM sku_reservations WHERE task_id = ? GROUP BY status",
            (task_id,),
        ).fetchall()
        if not current:
            raise LibraryError(f"Task has no SKU reservations: {task_id}")
        rank = {value: index for index, value in enumerate(SKU_STATUSES)}
        if any(rank[row["status"]] > rank[status] for row in current):
            if not (status == "validated" and all(row["status"] == "committed" for row in current)):
                raise LibraryError("SKU reservation status cannot move backwards")
            rows = connection.execute(
                "SELECT role, source_key, sku, status FROM sku_reservations WHERE task_id = ? ORDER BY id",
                (task_id,),
            ).fetchall()
            return {"task_id": task_id, "updated": 0, "reservations": [dict(row) for row in rows]}
        if status == "committed" and any(row["status"] == "reserved" for row in current):
            raise LibraryError("SKUs must be marked validated before they can be committed")
        if status == "committed":
            task = connection.execute(
                "SELECT result_status FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if task is None or task["result_status"] == "DRAFT_NOT_FOR_UPLOAD":
                raise LibraryError("Draft tasks cannot commit SKU reservations")
        now = utc_now()
        cursor = connection.execute(
            "UPDATE sku_reservations SET status = ?, updated_at = ? WHERE task_id = ?",
            (status, now, task_id),
        )
        connection.commit()
        rows = connection.execute(
            "SELECT role, source_key, sku, status FROM sku_reservations WHERE task_id = ? ORDER BY id",
            (task_id,),
        ).fetchall()
    finally:
        connection.close()
    return {"task_id": task_id, "updated": cursor.rowcount, "reservations": [dict(row) for row in rows]}


def get_task(project_root: Path, task_id: str) -> dict[str, Any]:
    connection = connect_database(project_root)
    try:
        ensure_task_schema(connection)
        task = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if task is None:
            raise LibraryError(f"Task not found: {task_id}")
        reservations = connection.execute(
            "SELECT role, source_key, sku, status, created_at, updated_at "
            "FROM sku_reservations WHERE task_id = ? ORDER BY id",
            (task_id,),
        ).fetchall()
    finally:
        connection.close()
    return {
        "task_id": task["task_id"],
        "scope": json.loads(task["scope_json"]),
        "input_snapshot": json.loads(task["input_snapshot_json"]),
        "mapping_sha256": task["mapping_sha256"],
        "output_path": task["output_path"],
        "output_sha256": task["output_sha256"],
        "acceptance_evidence_path": task["acceptance_evidence_path"],
        "acceptance_note": task["acceptance_note"],
        "result_status": task["result_status"],
        "created_at": task["created_at"],
        "updated_at": task["updated_at"],
        "sku_reservations": [dict(row) for row in reservations],
    }


def verify_mapping_reservations(
    project_root: Path, task_id: str, mapping: dict[str, Any]
) -> dict[str, Any]:
    expected: dict[tuple[str, str], str] = {}
    errors: list[dict[str, Any]] = []
    for index, row in enumerate(mapping.get("rows", []), start=1):
        if not isinstance(row, dict):
            continue
        role = row.get("role")
        source_key = str(row.get("source_key") or "").strip()
        fields = row.get("fields") if isinstance(row.get("fields"), dict) else {}
        sku_values = []
        for field, record in fields.items():
            if str(field).split("[", 1)[0].split("#", 1)[0] != "contribution_sku":
                continue
            value = record.get("value") if isinstance(record, dict) else None
            if value is not None and str(value).strip():
                sku_values.append(str(value).strip())
        if role not in ROLES or not source_key or len(set(sku_values)) != 1:
            errors.append({
                "code": "mapping_sku_identity_invalid",
                "row_index": index,
                "role": role,
                "source_key": source_key,
                "sku_values": sku_values,
            })
            continue
        expected[(role, source_key)] = sku_values[0]

    connection = connect_database(project_root)
    try:
        ensure_task_schema(connection)
        task = connection.execute(
            "SELECT input_snapshot_json FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if task is None:
            errors.append({"code": "task_not_found", "task_id": task_id})
            snapshot_product = None
            snapshot_templates = None
        else:
            snapshot = json.loads(task["input_snapshot_json"])
            snapshot_product = snapshot.get("product") if isinstance(snapshot, dict) else None
            snapshot_templates = snapshot.get("templates") if isinstance(snapshot, dict) else None
        rows = connection.execute(
            "SELECT role, source_key, sku, status FROM sku_reservations WHERE task_id = ?",
            (task_id,),
        ).fetchall()
    finally:
        connection.close()
    actual = {(row["role"], row["source_key"]): row["sku"] for row in rows}
    mapping_inputs = mapping.get("inputs") if isinstance(mapping.get("inputs"), dict) else {}
    mapping_product = mapping_inputs.get("product")
    if mapping_product != snapshot_product:
        errors.append({
            "code": "product_snapshot_mismatch",
            "mapping_product": mapping_product,
            "task_product": snapshot_product,
        })
    mapping_templates = mapping.get("templates")
    if mapping_templates != snapshot_templates:
        errors.append({
            "code": "template_snapshot_mismatch",
            "mapping_templates": mapping_templates,
            "task_templates": snapshot_templates,
        })
    if expected != actual:
        errors.append({
            "code": "sku_reservations_mismatch",
            "expected_from_mapping": [
                {"role": role, "source_key": source_key, "sku": sku}
                for (role, source_key), sku in sorted(expected.items())
            ],
            "actual_reservations": [dict(row) for row in rows],
        })
    return {
        "ok": not errors,
        "task_id": task_id,
        "checked_rows": len(expected),
        "errors": errors,
    }


def update_task_result(
    project_root: Path,
    task_id: str,
    result_status: str,
    mapping_sha256: str | None,
    *,
    report_path: Path | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    evidence_path: str | None = None
    if report_path is not None and result_status != "ACCEPTED_REPORT_VERIFIED":
        raise LibraryError(
            "--report 仅用于 ACCEPTED_REPORT_VERIFIED 的 Amazon 处理报告；"
            "本地 Mapping/工作簿校验报告由 Writer 单独保存。"
        )
    if report_path is not None:
        report = validate_processing_report_evidence(report_path)
        evidence_path = str(report)
    if result_status == "ACCEPTED_REPORT_VERIFIED" and evidence_path is None:
        raise LibraryError("ACCEPTED_REPORT_VERIFIED requires an attached processing report")
    connection = connect_database(project_root)
    try:
        ensure_task_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        task = connection.execute(
            "SELECT result_status, output_path, output_sha256 FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if task is None:
            raise LibraryError(f"Task not found: {task_id}")
        current = task["result_status"]
        allowed = {
            "DRAFT_NOT_FOR_UPLOAD": {"DRAFT_NOT_FOR_UPLOAD", "LOCAL_VALIDATION_PASSED"},
            "LOCAL_VALIDATION_PASSED": {
                "DRAFT_NOT_FOR_UPLOAD",
                "LOCAL_VALIDATION_PASSED",
                "ACCEPTED_USER_CONFIRMED",
                "ACCEPTED_REPORT_VERIFIED",
            },
            "ACCEPTED_USER_CONFIRMED": {
                "DRAFT_NOT_FOR_UPLOAD",
                "ACCEPTED_USER_CONFIRMED",
                "ACCEPTED_REPORT_VERIFIED",
            },
            "ACCEPTED_REPORT_VERIFIED": {
                "DRAFT_NOT_FOR_UPLOAD",
                "ACCEPTED_REPORT_VERIFIED",
            },
        }
        if result_status not in allowed[current]:
            raise LibraryError(f"Invalid task status transition: {current} -> {result_status}")
        if result_status.startswith("ACCEPTED_") and not (task["output_path"] and task["output_sha256"]):
            raise LibraryError("Accepted status requires a locally validated output snapshot")
        now = utc_now()
        cursor = connection.execute(
            "UPDATE tasks SET result_status = ?, mapping_sha256 = COALESCE(?, mapping_sha256), "
            "acceptance_evidence_path = ?, acceptance_note = ?, updated_at = ? WHERE task_id = ?",
            (result_status, mapping_sha256, evidence_path, note, now, task_id),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {
        "task_id": task_id,
        "result_status": result_status,
        "mapping_sha256": mapping_sha256,
        "acceptance_evidence_path": evidence_path,
        "acceptance_note": note,
    }


def finalize_task_output(
    project_root: Path,
    task_id: str,
    result_status: str,
    mapping_sha256: str,
    output_path: Path,
    output_sha256: str,
) -> dict[str, Any]:
    connection = connect_database(project_root)
    try:
        ensure_task_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        task = connection.execute("SELECT result_status FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if task is None:
            raise LibraryError(f"Task not found: {task_id}")
        allowed_output_transitions = {
            "DRAFT_NOT_FOR_UPLOAD": {"DRAFT_NOT_FOR_UPLOAD", "LOCAL_VALIDATION_PASSED"},
            "LOCAL_VALIDATION_PASSED": {"LOCAL_VALIDATION_PASSED"},
            "ACCEPTED_USER_CONFIRMED": set(),
            "ACCEPTED_REPORT_VERIFIED": set(),
        }
        if result_status not in allowed_output_transitions[task["result_status"]]:
            raise LibraryError(
                f"Output finalization cannot change task status: "
                f"{task['result_status']} -> {result_status}"
            )
        reservations = connection.execute(
            "SELECT id, status FROM sku_reservations WHERE task_id = ?", (task_id,)
        ).fetchall()
        if not reservations:
            raise LibraryError(f"Task has no SKU reservations: {task_id}")
        if result_status == "LOCAL_VALIDATION_PASSED":
            if any(row["status"] not in {"validated", "committed"} for row in reservations):
                raise LibraryError("All SKU reservations must be validated before final output commit")
            connection.execute(
                "UPDATE sku_reservations SET status = 'committed', updated_at = ? WHERE task_id = ?",
                (utc_now(), task_id),
            )
        now = utc_now()
        connection.execute(
            "UPDATE tasks SET result_status = ?, mapping_sha256 = ?, output_path = ?, "
            "output_sha256 = ?, updated_at = ? WHERE task_id = ?",
            (result_status, mapping_sha256, str(output_path), output_sha256, now, task_id),
        )
        final_reservations = connection.execute(
            "SELECT DISTINCT status FROM sku_reservations WHERE task_id = ?",
            (task_id,),
        ).fetchall()
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    final_statuses = {row["status"] for row in final_reservations}
    if result_status == "LOCAL_VALIDATION_PASSED":
        sku_status = "committed"
    elif final_statuses == {"committed"}:
        sku_status = "committed_reused"
    elif len(final_statuses) == 1:
        sku_status = next(iter(final_statuses))
    else:
        sku_status = "mixed"
    return {
        "task_id": task_id,
        "result_status": result_status,
        "mapping_sha256": mapping_sha256,
        "output_path": str(output_path),
        "output_sha256": output_sha256,
        "sku_status": sku_status,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)

    save = commands.add_parser("save-task")
    save.add_argument("--task-id", required=True)
    save.add_argument("--scope-json", required=True, help="Inline JSON or @path")
    save.add_argument("--snapshot-json", required=True, help="Inline JSON or @path")
    save.add_argument("--result-status", choices=RESULT_STATUSES, default="DRAFT_NOT_FOR_UPLOAD")
    save.add_argument("--mapping-sha256")

    reserve = commands.add_parser("reserve-sku")
    reserve.add_argument("--task-id", required=True)
    reserve.add_argument("--role", choices=ROLES, required=True)
    reserve.add_argument("--source-key", required=True)
    reserve.add_argument("--sku", required=True)

    sku_status = commands.add_parser("set-skus-status")
    sku_status.add_argument("--task-id", required=True)
    sku_status.add_argument("--status", choices=SKU_STATUSES, required=True)

    show = commands.add_parser("show-task")
    show.add_argument("--task-id", required=True)

    verify = commands.add_parser("verify-mapping-skus")
    verify.add_argument("--task-id", required=True)
    verify.add_argument("--mapping", type=Path, required=True)

    result = commands.add_parser("set-task-result")
    result.add_argument("--task-id", required=True)
    result.add_argument("--result-status", choices=RESULT_STATUSES, required=True)
    result.add_argument("--mapping-sha256")
    result.add_argument(
        "--report",
        type=Path,
        help="Amazon processing report; only valid for ACCEPTED_REPORT_VERIFIED",
    )
    result.add_argument("--note")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    project_root = args.project_root.expanduser().resolve()
    try:
        if args.command == "save-task":
            result = save_task(
                project_root,
                args.task_id,
                load_json_argument(args.scope_json),
                load_json_argument(args.snapshot_json),
                args.result_status,
                args.mapping_sha256,
            )
        elif args.command == "reserve-sku":
            result = reserve_sku(project_root, args.task_id, args.role, args.source_key, args.sku)
        elif args.command == "set-skus-status":
            result = set_task_skus_status(project_root, args.task_id, args.status)
        elif args.command == "show-task":
            result = get_task(project_root, args.task_id)
        elif args.command == "verify-mapping-skus":
            mapping = json.loads(args.mapping.read_text(encoding="utf-8"))
            result = verify_mapping_reservations(project_root, args.task_id, mapping)
            if not result["ok"]:
                print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
                return 1
        else:
            result = update_task_result(
                project_root,
                args.task_id,
                args.result_status,
                args.mapping_sha256,
                report_path=args.report,
                note=args.note,
            )
    except (LibraryError, OSError, sqlite3.Error, json.JSONDecodeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
