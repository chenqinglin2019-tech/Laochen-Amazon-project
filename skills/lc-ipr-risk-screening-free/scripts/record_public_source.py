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
    "original_patent_document",
}


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
    run = record_result(task_dir, provider="public_source", operation="retained_document",
        query=str(payload["source_url"]), jurisdiction=str(payload.get("jurisdiction") or "US"),
        evidence_type="public_source", status="success", normalized=payload,
        request_params={"q": payload["source_url"], "right_type": payload.get("right_type", "")},
        source_environment="local_agent_review", authoritative_for_final_rating=False,
        submission_state="not_submitted")
    print(run["run_id"])


if __name__ == "__main__":
    main()
