"""Exact retained PDF-page provenance; rendering is an explicit acquisition step.

Validation never renders again. An old image requires an actual Agent page
comparison, not a filename-based conversion of its metadata.
"""
from __future__ import annotations

import io
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from common import atomic_write_bytes, now_iso, sha256_file

PAGE_SCHEMA = "IPR-PDF-PAGE/1.0"


def _number(value):
    return re.sub(r"[\s,./-]", "", str(value or "")).upper()


def pdf_page_count(path: Path, digest: str, cache: dict | None = None) -> int:
    key = (str(path.resolve()), digest)
    if cache is not None and key in cache:
        return cache[key]
    if not path.is_file() or sha256_file(path) != digest:
        raise ValueError("PDF_PAGE_PARENT_HASH_MISMATCH")
    try:
        from pypdf import PdfReader
        count = len(PdfReader(io.BytesIO(path.read_bytes()), strict=True).pages)
    except ImportError as exc:
        raise ValueError("PDF_PAGE_READER_UNAVAILABLE: use bundled PDF runtime") from exc
    except Exception as exc:
        raise ValueError("PDF_PAGE_PARENT_UNREADABLE") from exc
    if count < 1:
        raise ValueError("PDF_PAGE_PARENT_EMPTY")
    if cache is not None:
        cache[key] = count
    return count


def validate_page_binding(record: dict, parent: dict, root: Path, *, cache=None) -> None:
    pdf = Path(parent.get("source_path") or parent.get("path", ""))
    pdf = pdf if pdf.is_absolute() else root / pdf
    digest = parent.get("sha256")
    page = record.get("page_number")
    if type(page) is not int or page < 1:
        raise ValueError("PDF_PAGE_NUMBER_INVALID")
    count = pdf_page_count(pdf, digest, cache)
    if page > count:
        raise ValueError("PDF_PAGE_OUT_OF_RANGE")
    for key in ("publication_number", "jurisdiction", "right_type"):
        if record.get(key) and _number(record[key]) != _number(parent.get(key)):
            raise ValueError("PDF_PAGE_IDENTITY_CONFLICT:" + key)
    origin = record.get("page_verification") or {}
    if (origin.get("schema") != PAGE_SCHEMA or origin.get("source_document_sha256") != digest
            or origin.get("page_count") != count or origin.get("page_number") != page
            or origin.get("image_sha256") != record.get("sha256")):
        raise ValueError("PDF_PAGE_PROVENANCE_MISSING_OR_STALE")
    method = origin.get("method")
    if method == "controlled_pdf_render":
        params = origin.get("render_parameters") or {}
        if (origin.get("renderer") != "pdftoppm" or type(params.get("dpi")) is not int
                or not 72 <= params["dpi"] <= 600 or params.get("format") != "png"):
            raise ValueError("PDF_PAGE_RENDER_PARAMETERS_INVALID")
    elif method == "agent_page_verification":
        if not all(isinstance(origin.get(k), str) and origin[k].strip()
                   for k in ("reviewer", "reviewed_at", "reasoning")):
            raise ValueError("PDF_PAGE_MANUAL_VERIFICATION_INCOMPLETE")
    else:
        raise ValueError("PDF_PAGE_PROVENANCE_METHOD_INVALID")


def render_page(pdf: Path, output: Path, page: int, expected_sha256: str, *, dpi: int = 144) -> dict:
    """Create one authentic PNG and a receipt; never replace an existing image."""
    count = pdf_page_count(pdf, expected_sha256)
    if type(page) is not int or not 1 <= page <= count:
        raise ValueError("PDF_PAGE_OUT_OF_RANGE")
    if type(dpi) is not int or not 72 <= dpi <= 600:
        raise ValueError("PDF_PAGE_RENDER_PARAMETERS_INVALID")
    if output.exists():
        raise ValueError("PDF_PAGE_OUTPUT_ALREADY_EXISTS")
    binary = shutil.which("pdftoppm")
    if not binary:
        raise ValueError("PDF_PAGE_RENDERER_UNAVAILABLE")
    with tempfile.TemporaryDirectory(prefix="ipr-pdf-page-") as directory:
        prefix = Path(directory) / "page"
        subprocess.run([binary, "-f", str(page), "-l", str(page), "-r", str(dpi),
                        "-singlefile", "-png", str(pdf), str(prefix)],
                       check=True, capture_output=True, timeout=60)
        payload = prefix.with_suffix(".png").read_bytes()
        if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("PDF_PAGE_RENDER_OUTPUT_INVALID")
        if sha256_file(pdf) != expected_sha256:
            raise ValueError("PDF_PAGE_PARENT_CHANGED_DURING_RENDER")
        output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(output, payload)
    return {"schema": PAGE_SCHEMA, "method": "controlled_pdf_render", "renderer": "pdftoppm",
            "render_parameters": {"dpi": dpi, "format": "png"}, "page_number": page,
            "page_count": count, "source_document_sha256": expected_sha256,
            "image_sha256": sha256_file(output), "rendered_at": now_iso()}
