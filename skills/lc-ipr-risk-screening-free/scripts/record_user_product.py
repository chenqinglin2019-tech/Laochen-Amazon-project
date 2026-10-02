#!/usr/bin/env python3
"""Retain user-supplied materials after credentials preflight; never browse."""
from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
import shutil
import tempfile

from common import atomic_write_json, load_json, now_iso, sha256_file, sha256_json, stable_id
from product_entry import enabled, load_materials, freeze, evidence_errors


def record(task_dir: Path, *, product_input: Path | None = None, change_review_path: Path | None = None) -> str:
    from execution_lock import execution_lock
    with execution_lock(task_dir.resolve(), "product"):
        return _record(task_dir,product_input=product_input,change_review_path=change_review_path)


def _finish_change(task_dir, task, evidence, old_task, change_review):
    from product_change import append_target_change, retain_event
    if change_review['kind']=='target_change':
        statement=change_review['user_statement'].strip()
        statement_eid=stable_id('EV','target_change_statement',task['task_id'],sha256_json(statement))
        source={'evidence_id':statement_eid,'kind':'user_statement','text':statement,'sha256':sha256_json(statement)}
        retained=evidence['collections'].setdefault('scope_sources',[])
        if not any(row.get('evidence_id')==statement_eid for row in retained): retained.append(source)
        source_refs=[statement_eid]
    else:
        source_refs=change_review.get('source_refs',[])
        known={row.get('evidence_id') for values in evidence['collections'].values() if isinstance(values,list)
               for row in values if isinstance(row,dict)}
        if not isinstance(source_refs,list) or not source_refs or not set(source_refs)<=known:
            raise ValueError('PRODUCT_IDENTITY_CORRECTION_SOURCE_REQUIRED')
    plan=load_json(task_dir/'search-plan.json') if (task_dir/'search-plan.json').is_file() else {}
    event=append_target_change(task_dir,task,evidence,old_task,plan,change_review,source_refs)
    retain_event(task_dir,task,evidence,event)
    for key in ('product_scope','product_scope_revision','product_delivery','product_delivery_revision','query_terms'):
        task.pop(key,None)
    task['product_scope_required']=True


def _record(task_dir: Path, *, product_input: Path | None = None, change_review_path: Path | None = None) -> str:
    task_dir = task_dir.resolve()
    task = load_json(task_dir / "task.json")
    evidence = load_json(task_dir / "evidence.json")
    if not enabled(task) or task["request"]["entry_type"] != "user_materials":
        raise ValueError("USER_MATERIALS_ENTRY_REQUIRED")
    if task.get("checkpoints", {}).get("credential_preflight", {}).get("status") != "success":
        raise ValueError("CREDENTIAL_PREFLIGHT_REQUIRED")
    changing=change_review_path is not None
    old_task=deepcopy(task) if changing else None
    change_review=load_json(change_review_path.resolve()) if changing else None
    if changing:
        if product_input is None or not isinstance(change_review,dict):
            raise ValueError('PRODUCT_TARGET_CHANGE_INPUT_REQUIRED')
        old_errors=evidence_errors(task,evidence,task_dir)
        if old_errors: raise ValueError('; '.join(old_errors))
        from product_entry import assert_frozen
        assert_frozen(task)
        if (change_review.get('kind') not in {'target_change','identity_correction'}
                or change_review.get('expected_target_sha256')!=task['product_identity']['sha256']
                or not str(change_review.get('reason','')).strip()
                or change_review['kind']=='target_change' and not str(change_review.get('user_statement','')).strip()):
            raise ValueError('PRODUCT_TARGET_CHANGE_REVIEW_INVALID')
        prepared=load_materials(product_input)
        if prepared['data']['schema_version']!='product-input-v2' or prepared['fingerprint']==task['request']['input_fingerprint']:
            raise ValueError('PRODUCT_TARGET_CHANGE_MATERIALS_INVALID')
        task['request']['input_path']=str(product_input.resolve())
        task['request']['input_fingerprint']=prepared['fingerprint']
        task['product']={'product_id':stable_id('PRODUCT',task['task_id'],prepared['fingerprint']),
            'input_role':old_task['product']['input_role'],
            'input_role_source':old_task['product']['input_role_source'],
            'intended_use':'','assets':[],'image_coverage':{'status':'unknown','missing_views':[]}}
        task['product_identity']={'status':'pending'}
    elif product_input is not None:
        raise ValueError('PRODUCT_INPUT_CHANGE_REVIEW_REQUIRED')
    if not changing and task.get("product_identity", {}).get("status") == "frozen":
        errors = evidence_errors(task, evidence, task_dir)
        if errors:
            raise ValueError("; ".join(errors))
        return "success"  # Idempotent even after planning, without external input access.
    expected_id = stable_id("EV", "user_materials", task["task_id"], task["request"]["input_fingerprint"])
    retained = [v for v in evidence.get("collections", {}).get("product", []) if v.get("evidence_id") == expected_id]
    if retained:
        if len(retained) != 1 or retained[0].get("input_fingerprint") != task["request"]["input_fingerprint"]:
            raise ValueError("PRODUCT_RECOVERY_RECORD_CONFLICT")
        saved = retained[0]
        for key in ("product_id", "requested_asin", "actual_asin", "input_role", "input_role_source"):
            if saved.get("product", {}).get(key) != task.get("product", {}).get(key):
                raise ValueError("PRODUCT_RECOVERY_IDENTITY_CONFLICT")
        task["product"] = deepcopy(saved["product"])
        task["images"] = deepcopy(saved["images"])
        task["product_readiness"] = deepcopy(saved["readiness"])
        freeze(task, expected_id)
        errors = evidence_errors(task, evidence, task_dir)
        if errors:
            raise ValueError("; ".join(errors))
        task["request"]["input_path"] = str(task_dir / "raw" / "user_materials" / task["request"]["input_fingerprint"] / "input.json")
        task["checkpoints"]["user_product"] = {"status": "success", "evidence_id": expected_id, "at": saved["collected_at"]}
        if changing:
            _finish_change(task_dir,task,evidence,old_task,change_review)
            atomic_write_json(task_dir/'evidence.json',evidence)
        task["updated_at"] = now_iso()
        atomic_write_json(task_dir / "task.json", task)
        return "success"
    input_path = Path(task["request"]["input_path"])
    prepared = prepared if changing else load_materials(input_path)
    if prepared["fingerprint"] != task["request"]["input_fingerprint"]:
        raise ValueError("PRODUCT_INPUT_CHANGED_BEFORE_INGESTION")
    stamp = now_iso()
    evidence_id = stable_id("EV", "user_materials", task["task_id"], prepared["fingerprint"])
    destination = task_dir / "raw" / "user_materials" / prepared["fingerprint"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".product-input-", dir=destination.parent) as temp:
        staged = Path(temp)
        sources, images = [], []
        selection = prepared.get("selection")
        for index, source in enumerate(prepared["sources"]):
            source = deepcopy(source)
            if "path" in source:
                original = Path(source["path"])
                name = f"source-{index}{original.suffix}"
                shutil.copyfile(original, staged / name)
                if sha256_file(staged / name) != source["sha256"]:
                    raise ValueError("PRODUCT_INPUT_CHANGED_DURING_INGESTION")
                source["path"] = str(destination / name)
                if source["kind"] == "image":
                    is_main = (source["source_id"] == selection.get("source_id") if selection
                               else not images)
                    images.append({**source, "image_id": f"IMG-{len(images)+1:03d}",
                                   "role": "main" if is_main else "product_view", "collected_at": stamp})
            sources.append(source)
        shutil.copyfile(input_path, staged / "input.json")
        if sha256_file(staged / "input.json") != prepared["input_sha256"]:
            raise ValueError("PRODUCT_INPUT_CHANGED_DURING_INGESTION")
        # Reuse byte-identical remnants of an interrupted write; never overwrite.
        if destination.exists():
            if any(not (destination / p.name).is_file() or sha256_file(destination / p.name) != sha256_file(p)
                   for p in staged.iterdir()):
                raise ValueError("PRODUCT_RETAINED_INPUT_CONFLICT")
        else:
            shutil.copytree(staged, destination)
    task["product"].update(prepared["product"])
    if selection:
        from product_delivery import image_identity
        chosen = next((image for image in images if image["role"] == "main"), None)
        task["product"]["query_image"] = {
            "status": selection["status"], "image_id": chosen["image_id"] if chosen else "",
            "sha256": chosen["sha256"] if chosen else "",
            "source_id": selection.get("source_id", ""), "source_url": chosen.get("source_url", "") if chosen else "",
            "source_kind": "other_public_url" if chosen and chosen.get("source_url") else "user_file",
            "selected_by": selection.get("selected_by", ""),
            "reason": selection["reason"], "question": selection.get("question", ""),
            "target_sha256": image_identity(task), "selected_at": stamp,
        }
    task["product"]["media_identity"] = sorted({image["sha256"] for image in images})
    task["product"]["analysis"] = {"status": "pending"}
    task["images"] = images
    task["product_readiness"] = prepared["data"]["readiness"]
    freeze(task, evidence_id)
    payload = {"evidence_id": evidence_id, "source": "user_materials", "product": deepcopy(task["product"]),
               "sources": sources, "images": images, "identity_review": prepared["data"]["identity_review"],
               "input_fingerprint": prepared["fingerprint"], "readiness": prepared["data"]["readiness"], "collected_at": stamp}
    evidence["collections"]["product"].append(payload)
    raw = destination / "record.json"
    atomic_write_json(raw, payload)
    evidence["source_runs"].append({"run_id": stable_id("SRC", evidence_id), "provider": "user_materials",
        "operation": "product_capture", "evidence_ids": [evidence_id], "query_id": stable_id("QRY", task["task_id"], "user_materials"),
        "query": task["product"]["product_id"], "status": "success", "evidence_type": "product",
        "raw_paths": [str(raw)], "payload_digest": sha256_file(raw), "started_at": stamp,
        "finished_at": stamp, "detail": "User materials retained; not an Amazon or registry response."})
    task["request"]["input_path"] = str(destination / "input.json")
    task["checkpoints"]["user_product"] = {"status": "success", "evidence_id": evidence_id, "at": stamp}
    if changing:
        _finish_change(task_dir,task,evidence,old_task,change_review)
    task["updated_at"] = evidence["updated_at"] = stamp
    atomic_write_json(task_dir / "evidence.json", evidence)
    atomic_write_json(task_dir / "task.json", task)
    return "success"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--product-input", type=Path)
    parser.add_argument("--change-review", type=Path)
    args = parser.parse_args()
    print(record(args.task_dir,product_input=args.product_input,change_review_path=args.change_review))


if __name__ == "__main__":
    main()
