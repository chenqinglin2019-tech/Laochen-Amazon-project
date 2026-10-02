"""Versioned product entry and frozen target identity (01A).

The agent judges source sufficiency; this module validates its recorded basis
and the actual files. It never infers a country, product or internal structure.
"""
from __future__ import annotations

from copy import deepcopy
import ipaddress
from pathlib import Path
import re
from urllib.parse import urlsplit

from common import image_info, load_json, now_iso, resolve_retained_path, sha256_file, sha256_json

REVISION = "dual-entry-v1"
ENTRY_TYPES = {"amazon_url", "user_materials"}
COUNTRIES = {"US", "GB", "FR", "DE", "IT", "ES", "JP"}
PRODUCT_FIELDS = {"title", "purpose", "brand", "manufacturer", "category", "bullets",
                  "specifications", "structure", "variant", "visible_ip_claims"}


def enabled(task: dict) -> bool:
    revision = task.get("product_entry_revision")
    if revision is None:
        return False
    if revision != REVISION or task.get("request", {}).get("entry_type") not in ENTRY_TYPES:
        raise ValueError("PRODUCT_ENTRY_CONTRACT_INVALID")
    return True


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def public_image_url_valid(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or '').casefold()
        if (parsed.scheme != 'https' or not host or parsed.username or parsed.password or parsed.fragment
                or parsed.port not in {None,443} or '.' not in host
                or host.endswith(('.localhost','.local','.internal','.test','.invalid','.example'))):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True
    except (TypeError, ValueError):
        return False


def load_materials(path: Path) -> dict:
    path = path.expanduser().resolve()
    data = load_json(path)
    if (not isinstance(data, dict) or data.get("schema_version") not in {"product-input-v1", "product-input-v2"}
            or set(data) - {"schema_version", "product", "identity_review", "readiness", "sources", "image_selection"}):
        raise ValueError("PRODUCT_INPUT_SCHEMA_REQUIRED")
    product = data.get("product")
    if not isinstance(product, dict) or set(product) - PRODUCT_FIELDS:
        raise ValueError("PRODUCT_INPUT_SINGLE_PRODUCT_FIELDS_REQUIRED")
    if not _text(product.get("title")) or not _text(product.get("purpose")):
        raise ValueError("PRODUCT_INPUT_TITLE_AND_PURPOSE_REQUIRED")
    for field in ("variant", "specifications"):
        if field in product and not isinstance(product[field], dict):
            raise ValueError("PRODUCT_INPUT_INVALID_" + field.upper())
    for field in ("structure", "bullets", "visible_ip_claims"):
        if field in product and not isinstance(product[field], list):
            raise ValueError("PRODUCT_INPUT_INVALID_" + field.upper())
    for field in ("brand", "manufacturer", "category"):
        if field in product and not isinstance(product[field], str):
            raise ValueError("PRODUCT_INPUT_INVALID_" + field.upper())
    review = data.get("identity_review")
    if (not isinstance(review, dict) or review.get("single_product") is not True
            or review.get("status") != "confirmed" or not _text(review.get("reviewer"))
            or not _text(review.get("reasoning")) or review.get("conflicts") != []):
        raise ValueError("PRODUCT_IDENTITY_REVIEW_REQUIRED: resolve product/variant conflicts first")
    readiness = data.get("readiness")
    if (not isinstance(readiness, dict) or readiness.get("status") not in ({"ready", "partial", "needs_info"} if readiness.get("revision") == "directional-readiness-v1" else {"ready"})
            or not _text(readiness.get("reasoning"))):
        raise ValueError("PRODUCT_INPUT_NEEDS_INFORMATION: record the minimum missing information")
    missing = readiness.get("nonblocking_gaps", [])
    if not isinstance(missing, list) or any(not _text(v) for v in missing):
        raise ValueError("PRODUCT_INPUT_GAPS_INVALID")
    sources = data.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("PRODUCT_INPUT_SOURCES_REQUIRED")
    normalized, ids = [], set()
    for item in sources:
        if not isinstance(item, dict):
            raise ValueError("PRODUCT_INPUT_SOURCE_INVALID")
        sid = item.get("source_id")
        if not _text(sid) or sid in ids:
            raise ValueError("PRODUCT_INPUT_SOURCE_ID_INVALID")
        ids.add(sid)
        kind = item.get("kind")
        if kind not in {"image", "specification", "description"}:
            raise ValueError("PRODUCT_INPUT_SOURCE_KIND_INVALID")
        row = {"source_id": sid, "kind": kind}
        if bool(item.get("path")) == bool(item.get("text")):
            raise ValueError("PRODUCT_INPUT_SOURCE_PATH_OR_TEXT_REQUIRED")
        if item.get("path"):
            file = Path(item["path"]).expanduser()
            file = (path.parent / file).resolve() if not file.is_absolute() else file.resolve()
            if not file.is_file():
                raise ValueError("PRODUCT_INPUT_SOURCE_MISSING: " + sid)
            row.update(path=str(file), sha256=sha256_file(file), bytes=file.stat().st_size)
            if kind == "image":
                mime, width, height = image_info(file)
                if not mime.startswith("image/") or min(width, height) <= 0:
                    raise ValueError("PRODUCT_INPUT_IMAGE_INVALID: " + sid)
                row.update(mime_type=mime, width=width, height=height)
        elif kind == "image" or not _text(item.get("text")):
            raise ValueError("PRODUCT_INPUT_SOURCE_TEXT_INVALID")
        else:
            row.update(text=item["text"], sha256=sha256_json(item["text"]))
        public_url = item.get("source_url")
        if public_url is not None:
            if data["schema_version"] != "product-input-v2" or kind != "image" or not isinstance(public_url,str):
                raise ValueError("PRODUCT_IMAGE_PUBLIC_URL_UNSUPPORTED")
            url_review = item.get("public_url_review")
            if (not public_image_url_valid(public_url)
                    or not isinstance(url_review,dict) or url_review.get("status") != "confirmed"
                    or not _text(url_review.get("reviewer")) or not _text(url_review.get("reason"))):
                raise ValueError("PRODUCT_IMAGE_PUBLIC_URL_REVIEW_REQUIRED")
            row.update(source_url=public_url,public_url_review=deepcopy(url_review))
        elif item.get("public_url_review"):
            raise ValueError("PRODUCT_IMAGE_PUBLIC_URL_REVIEW_WITHOUT_URL")
        normalized.append(row)
    refs = review.get("source_ids")
    if not isinstance(refs, list) or not refs or any(not isinstance(s, str) or s not in ids for s in refs):
        raise ValueError("PRODUCT_IDENTITY_REVIEW_SOURCE_INVALID")
    selection = data.get("image_selection")
    if data["schema_version"] == "product-input-v2":
        image_ids = {row["source_id"] for row in normalized if row["kind"] == "image"}
        if (not isinstance(selection, dict) or selection.get("status") not in {"selected", "needs_clarification", "unavailable"}
                or not _text(selection.get("reason"))):
            raise ValueError("QUERY_IMAGE_SELECTION_REQUIRED")
        if selection["status"] == "selected":
            if (selection.get("source_id") not in image_ids or selection.get("selected_by") not in {"user", "agent"}
                    or selection.get("question")):
                raise ValueError("QUERY_IMAGE_SELECTION_INVALID")
            if selection["selected_by"] == "user" and not any(
                    row["source_id"] == selection.get("statement_source_id") and row["kind"] == "description"
                    for row in normalized):
                raise ValueError("QUERY_IMAGE_USER_SELECTION_SOURCE_REQUIRED")
        elif selection.get("source_id") or selection["status"] == "needs_clarification" and not _text(selection.get("question")):
            raise ValueError("QUERY_IMAGE_CLARIFICATION_REQUIRED")
    elif selection is not None:
        raise ValueError("QUERY_IMAGE_SELECTION_REQUIRES_V2")
    fingerprint = sha256_json({"input_sha256": sha256_file(path), "sources": normalized})
    return {"data": data, "product": deepcopy(product), "sources": normalized,
            "selection": deepcopy(selection), "fingerprint": fingerprint, "input_sha256": sha256_file(path)}


def target_binding(task: dict, *, asin=None, variant=None) -> dict:
    product = task.get("product", {})
    return {"product_id": product.get("product_id"), "entry_type": task["request"]["entry_type"],
            "asin": str(product.get("actual_asin") if asin is None else asin or ""),
            "variant": deepcopy(product.get("variant", {}) if variant is None else variant)}


def assert_frozen(task: dict) -> None:
    if not enabled(task):
        return
    frozen = task.get("product_identity")
    if (not isinstance(frozen, dict) or frozen.get("status") != "frozen"
            or not _text(task.get("product", {}).get("product_id"))
            or not frozen.get("evidence_id") or not _text(frozen.get("frozen_at"))
            or frozen.get("binding") != target_binding(task)
            or frozen.get("sha256") != sha256_json(frozen.get("binding"))):
        raise ValueError("PRODUCT_TARGET_NOT_FROZEN_OR_CHANGED")


def check_amazon_target(task: dict, asin: str, variant: dict) -> None:
    if not enabled(task):
        return
    if task["request"]["entry_type"] != "amazon_url":
        raise ValueError("PRODUCT_ENTRY_NOT_AMAZON")
    if not re.fullmatch(r"[A-Z0-9]{10}", asin) or not isinstance(variant, dict) or variant.get("confirmed") is not True:
        raise ValueError("PRODUCT_CURRENT_VARIANT_UNCONFIRMED")
    if task.get("product_identity", {}).get("status") == "frozen":
        assert_frozen(task)
        if task["product_identity"]["binding"] != target_binding(task, asin=asin, variant=variant):
            raise ValueError("PRODUCT_FROZEN_TARGET_MISMATCH")


def freeze(task: dict, evidence_id: str) -> None:
    if task.get("product_identity", {}).get("status") == "frozen":
        assert_frozen(task)
        return
    binding = target_binding(task)
    task["product_identity"] = {"status": "frozen", "binding": binding,
        "sha256": sha256_json(binding), "evidence_id": evidence_id, "frozen_at": now_iso()}
    assert_frozen(task)


def evidence_errors(task: dict, evidence: dict, task_dir: Path) -> list[str]:
    try:
        assert_frozen(task)
    except ValueError as exc:
        return [str(exc)]
    identity = task["product_identity"]
    entries = evidence.get("collections", {}).get("product", [])
    record = next((v for v in entries if v.get("evidence_id") == identity["evidence_id"]), None)
    if not record or record.get("product", {}).get("product_id") != task["product"]["product_id"]:
        return ["PRODUCT_IDENTITY_EVIDENCE_MISSING"]
    if target_binding({**task, "product": record["product"]}) != identity["binding"]:
        return ["PRODUCT_IDENTITY_EVIDENCE_MISMATCH"]
    source = "amazon_browser" if task["request"]["entry_type"] == "amazon_url" else "user_materials"
    runs = [v for v in evidence.get("source_runs", []) if v.get("provider") == source
            and v.get("status") == "success" and identity["evidence_id"] in v.get("evidence_ids", [])]
    if not runs:
        return ["PRODUCT_SOURCE_RECEIPT_MISSING"]
    for run in runs:
        raw_paths = run.get("raw_paths")
        if not isinstance(raw_paths, list) or len(raw_paths) != 1:
            return ["PRODUCT_SOURCE_RECEIPT_INVALID"]
        try:
            raw = resolve_retained_path(task_dir, raw_paths[0], expected_sha256=run.get("payload_digest", ""))
            if not run.get("payload_digest"):
                raise ValueError("Missing receipt digest")
        except (ValueError, OSError):
            return ["PRODUCT_SOURCE_RECEIPT_CHANGED"]
        if source == "user_materials" and sha256_json(load_json(raw)) != sha256_json(record):
            return ["PRODUCT_SOURCE_RECORD_CHANGED"]
    active = record
    if source == "amazon_browser":
        current_id = task.get("checkpoints", {}).get("browser_product", {}).get("evidence_id")
        active = next((v for v in entries if v.get("evidence_id") == current_id), None)
        if (not active or target_binding({**task, "product": active.get("product", {})}) != identity["binding"]):
            return ["PRODUCT_CURRENT_CAPTURE_MISMATCH"]
    def image_binding(images):
        return sorted((v.get("image_id", ""), str(resolve_retained_path(task_dir, v.get("path", ""),
                       expected_sha256=v.get("sha256", ""), expected_bytes=v.get("bytes"))),
                       v.get("sha256", ""), v.get("role", ""), v.get("width", 0), v.get("height", 0))
                      for v in images)
    try:
        base_ids={v.get('image_id') for v in active.get('images',[])}
        current_base=[v for v in task.get('images',[]) if v.get('image_id') in base_ids]
        extras=[v for v in task.get('images',[]) if v.get('image_id') not in base_ids]
        retained_extras={v.get('image_id'):v for v in evidence.get('collections',{}).get('product_images',[])}
        for image in extras:
            saved=retained_extras.get(image.get('image_id'),{})
            resolve_retained_path(task_dir,image.get('path',''),expected_sha256=image.get('sha256',''),
                                  expected_bytes=image.get('bytes'))
            if saved.get('target_sha256')!=identity['sha256'] or saved.get('product_id')!=task['product']['product_id']:
                return ["PRODUCT_CURRENT_MEDIA_BINDING_MISMATCH"]
        if (image_binding(current_base) != image_binding(active.get("images", []))
                or len(current_base)+len(extras)!=len(task.get('images',[]))
                or any(v.get('image_id') not in retained_extras or v.get('sha256')!=retained_extras[v['image_id']].get('sha256')
                       or v.get('path')!=retained_extras[v['image_id']].get('path') for v in extras)
                or sorted(task["product"].get("media_identity", [])) != sorted({v.get("sha256") for v in task.get('images', [])})):
            return ["PRODUCT_CURRENT_MEDIA_BINDING_MISMATCH"]
    except (ValueError, OSError):
        return ["PRODUCT_CURRENT_MEDIA_BINDING_MISMATCH"]
    if source == "amazon_browser":
        return []  # Existing Amazon recorder owns screenshot/media validation.
    errors = []
    for item in record.get("sources", []):
        if "path" in item:
            try:
                resolve_retained_path(task_dir, item["path"], expected_sha256=item.get("sha256", ""),
                                      expected_bytes=item.get("bytes"))
            except (ValueError, OSError):
                errors.append("PRODUCT_SOURCE_FILE_CHANGED")
        elif sha256_json(item.get("text")) != item.get("sha256"):
            errors.append("PRODUCT_SOURCE_TEXT_CHANGED")
    if not record.get("sources"):
        errors.append("PRODUCT_SOURCES_MISSING")
    return errors
