#!/usr/bin/env python3
"""Register a retained, hash-bound public source for an Agent investigation."""
from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlsplit

from common import ensure_object, load_json, path_within, sha256_file
from provider_utils import record_result


# Candidate leads require an original, locally retained publication. Allow
# those document kinds here so the shared source registry, rather than an
# ad-hoc candidate file, remains the provenance record.
ALLOWED_KINDS = {
    "provenance_document", "official_record", "rights_record", "license",
    "patent_document", "patent_publication", "design_document",
    "design_drawings", "official_publication", "published_document",
    "original_patent_document", "patent_drawing_image",
}
# best-estimate-risk-v2: a drawing retained from a candidate's trusted API detail record is bound to that exact
# candidate in the payload (the shared result recorder keeps the payload intact), so the report can show the
# right's own figures without page rendering. It is not a candidate document and never changes triage bindings.


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".tif", ".tiff", ".bmp", ".svg", ".heic", ".avif"}


def image_payload(payload, path):
    """r5d4: a GIF / TIFF image original is registered as its lossless PNG (first frame), the original's hash, size,
    name and format kept beside it (image_convert.py); any other image format the review cannot read is refused
    here instead of voiding a complete final review later (B0FSJBDTF2: a gazette GIF)."""
    import image_convert
    suffix = path.suffix.lower()
    if suffix not in IMAGE_SUFFIXES or suffix in image_convert.READABLE:
        return payload
    if not image_convert.format_of(suffix):
        raise ValueError("PUBLIC_SOURCE_IMAGE_FORMAT_UNSUPPORTED: " + suffix + " (register PNG, JPEG, WEBP, GIF or TIFF)")
    data = path.read_bytes()
    png = image_convert.to_png(data)
    target = path.with_name(path.name + ".png")
    if not target.exists() or target.read_bytes() != png:
        from common import atomic_write_bytes
        atomic_write_bytes(target, png)
    from common import sha256_bytes
    return {**payload, "path": str(target), "sha256": sha256_bytes(png), "bytes": len(png),
            "derived_from": {"original_sha256": payload["sha256"], "original_bytes": payload["bytes"],
                             "original_file": path.name, "original_format": image_convert.format_of(suffix),
                             "transform": image_convert.TRANSFORM}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    task_dir = args.task_dir.resolve()
    payload = ensure_object(load_json(args.input), "public source")
    if payload.get("kind") not in ALLOWED_KINDS:
        raise ValueError("PUBLIC_SOURCE_KIND_INVALID")
    parsed = urlsplit(str(payload.get("source_url") or ""))
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("PUBLIC_SOURCE_URL_INVALID")
    path = Path(str(payload.get("path") or "")).resolve()
    if not path.is_file() or not path_within(path, task_dir) or sha256_file(path) != payload.get("sha256") or path.stat().st_size != payload.get("bytes"):
        raise ValueError("PUBLIC_SOURCE_ARTIFACT_INVALID")
    if not str(payload.get("reasoning") or "").strip():
        raise ValueError("PUBLIC_SOURCE_REASONING_REQUIRED")
    payload = image_payload(payload, path)
    path = Path(payload["path"]).resolve()
    task = load_json(task_dir / "task.json")
    from assessment_estimate import best_estimate_v2
    if payload["kind"] == "patent_drawing_image":
        if (not best_estimate_v2(task) or payload.get("visual_role") != "patent_drawings"
                or not str(payload.get("candidate_id") or "").startswith("CAND-")
                or not payload.get("publication_number") or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}):
            raise ValueError("PUBLIC_SOURCE_DRAWING_BINDING_INVALID")
    run = record_result(task_dir, provider="public_source", operation="retained_document",
        query=str(payload["source_url"]), jurisdiction=str(payload.get("jurisdiction") or "US"),
        evidence_type="public_source", status="success", normalized=payload,
        request_params={"q": payload["source_url"], "right_type": payload.get("right_type", "")},
        source_environment="local_agent_review", authoritative_for_final_rating=False,
        submission_state="not_submitted")
    print(run["run_id"])


if __name__ == "__main__":
    main()
