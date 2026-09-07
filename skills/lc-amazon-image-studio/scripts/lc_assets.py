"""Local product compositing and final-file disclosure; no image-model calls."""
from __future__ import annotations

import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageOps, PngImagePlugin

POLICY_VERSION = "amazon-2026-09-05-v3"
SYNTHETIC_KEYWORD = "contains-synthetic-performer"
DC = "http://purl.org/dc/elements/1.1/"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
XMP = "adobe:ns:meta/"
HUMAN_SOURCES = {"synthetic", "real", "none", "non_photorealistic", "unknown"}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode()).hexdigest()


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def pixel_hash(image: Image.Image) -> str:
    rgb = image.convert("RGB")
    h = hashlib.sha256(f"RGB:{rgb.width}:{rgb.height}:".encode())
    h.update(rgb.tobytes())
    return h.hexdigest()


def local_asset(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    if "://" in value:
        raise ValueError("Only local image assets are allowed")
    return path if path.is_absolute() else (base / path).resolve()


def box_pixels(box: list[float], size: tuple[int, int]) -> tuple[int, int, int, int]:
    if (not isinstance(box, (list, tuple)) or len(box) != 4
            or not all(isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) for n in box)):
        raise ValueError("Product box must contain four finite normalized numbers")
    x, y, w, h = box
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > 1.00000001 or y + h > 1.00000001:
        raise ValueError("Product box must stay inside the normalized image area")
    return round(x * size[0]), round(y * size[1]), round((x + w) * size[0]), round((y + h) * size[1])


def compose_product_layers(manifest: dict, job: dict, base: Path) -> tuple[Image.Image, list[dict]]:
    """Composite verified cutouts using uniform scaling. Never guesses a mask."""
    size = tuple(job["canvas"])
    color = job.get("padding_color", "#ffffff")
    color = tuple(color) if isinstance(color, list) else color
    canvas = Image.new("RGBA", size, color)
    if job.get("background_asset"):
        with Image.open(local_asset(job["background_asset"], base)) as src:
            bg = ImageOps.exif_transpose(src).convert("RGBA")
            # Background cropping is permissible; product layers are always contained.
            canvas.alpha_composite(ImageOps.fit(bg, size, method=Image.Resampling.LANCZOS))
    refs = {r["id"]: r for r in manifest["references"]}
    provenance = []
    layers = job.get("product_layers", [])
    if not layers:
        raise ValueError("pixel_composite requires product_layers with a reviewed cutout or mask")
    for index, layer in enumerate(layers):
        ref = refs.get(layer.get("reference_id"))
        if not ref:
            raise ValueError(f"Product layer {index}: reference_id is unknown")
        asset_path = local_asset(layer.get("asset_path") or ref["path"], base)
        with Image.open(asset_path) as src:
            product = ImageOps.exif_transpose(src).convert("RGBA")
        if layer.get("mask_path"):
            with Image.open(local_asset(layer["mask_path"], base)) as src:
                mask = ImageOps.exif_transpose(src).convert("L")
            if mask.size != product.size:
                raise ValueError("Product mask size must match the asset; masks are never stretched")
            product.putalpha(mask)
        if layer.get("crop_bbox_norm"):
            product = product.crop(box_pixels(layer["crop_bbox_norm"], product.size))
        if product.width < 1 or product.height < 1 or product.getchannel("A").getbbox() is None:
            raise ValueError("Product layer is empty or fully transparent")
        if not layer.get("opaque_rectangle", False) and product.getchannel("A").getextrema() == (255, 255):
            raise ValueError("Opaque product asset requires a reviewed mask, or explicit opaque_rectangle=true")
        bbox = layer.get("bbox_norm", job["target_product_bbox_norm"])
        left, top, right, bottom = box_pixels(bbox, size)
        if right <= left or bottom <= top:
            raise ValueError("Product layer has an empty target box")
        scale = min((right-left)/product.width, (bottom-top)/product.height)
        target_size = (max(1, round(product.width*scale)), max(1, round(product.height*scale)))
        fitted = product.resize(target_size, Image.Resampling.LANCZOS)
        pos = (left+(right-left-fitted.width)//2, top+(bottom-top-fitted.height)//2)
        shadow = layer.get("shadow", {})
        if shadow.get("enabled"):
            alpha = fitted.getchannel("A")
            opacity = float(shadow.get("opacity", 0.15))
            blur = float(shadow.get("blur", 18)) * min(size)/2000
            alpha = alpha.point(lambda p: round(p*opacity))
            mask_canvas = Image.new("L", size, 0)
            offset = shadow.get("offset", [0, 12])
            mask_canvas.paste(alpha, (pos[0]+round(offset[0]*min(size)/2000),
                                      pos[1]+round(offset[1]*min(size)/2000)))
            shadow_color = shadow.get("color", "#000000")
            shade = Image.new("RGBA", size, tuple(shadow_color) if isinstance(shadow_color, list) else shadow_color)
            shade.putalpha(mask_canvas.filter(ImageFilter.GaussianBlur(blur)))
            canvas.alpha_composite(shade)
        canvas.alpha_composite(fitted, pos)
        alpha_box = fitted.getchannel("A").getbbox() or (0, 0, *fitted.size)
        actual = [(pos[0]+alpha_box[0])/size[0], (pos[1]+alpha_box[1])/size[1],
                  (alpha_box[2]-alpha_box[0])/size[0], (alpha_box[3]-alpha_box[1])/size[1]]
        reference_provenance = ref.get("provenance", {})
        reference_origin = reference_provenance.get("kind", "real_photo")
        inherited_origin = "original" if reference_origin == "real_photo" else reference_origin
        asset_origin = layer.get("asset_origin", inherited_origin)
        if asset_origin != inherited_origin:
            raise ValueError("Product layer asset_origin contradicts the reference provenance")
        evidence_ids = list(dict.fromkeys([ref["id"]] + layer.get("source_reference_ids", [])
                                         + reference_provenance.get("source_reference_ids", [])
                                         + list(layer.get("source_binding", {}).get("source_reference_hashes", {}))))
        provenance.append({"reference_id": ref["id"], "asset_path": str(asset_path),
                           "asset_sha256": file_hash(asset_path), "bbox_norm": actual,
                           "scale": scale, "asset_origin": asset_origin,
                           "source_reference_ids": evidence_ids,
                           "mask_sha256": file_hash(local_asset(layer["mask_path"], base)) if layer.get("mask_path") else None})
    return canvas.convert("RGB"), provenance


def xmp_keywords(image: Image.Image) -> list[str]:
    payload = image.info.get("xmp") or image.info.get("XML:com.adobe.xmp")
    if not payload:
        return []
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        raise ValueError("External declarations are forbidden in XMP")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError("Malformed XMP metadata") from exc
    return [item.text or "" for subject in root.iter(f"{{{DC}}}subject")
            for item in subject.iter(f"{{{RDF}}}li")]


def make_xmp(keywords: list[str]) -> bytes:
    ET.register_namespace("x", XMP)
    ET.register_namespace("rdf", RDF)
    ET.register_namespace("dc", DC)
    root = ET.Element(f"{{{XMP}}}xmpmeta")
    rdf = ET.SubElement(root, f"{{{RDF}}}RDF")
    desc = ET.SubElement(rdf, f"{{{RDF}}}Description", {f"{{{RDF}}}about": ""})
    bag = ET.SubElement(ET.SubElement(desc, f"{{{DC}}}subject"), f"{{{RDF}}}Bag")
    for value in sorted(set(keywords)):
        ET.SubElement(bag, f"{{{RDF}}}li").text = value
    return ET.tostring(root, encoding="utf-8")


def disclosure_issues(job: dict) -> list[str]:
    data = job.get("ai_disclosure") or {}
    issues = []
    if not isinstance(data, dict):
        return ["AI_DISCLOSURE_MUST_BE_OBJECT"]
    source = data.get("human_source", "unknown")
    if not isinstance(source, str) or source not in HUMAN_SOURCES or source == "unknown":
        issues.append("AI_HUMAN_SOURCE_REVIEW_REQUIRED")
    if not job.get("image_sha256") or data.get("reviewed_image_sha256") != job.get("image_sha256"):
        issues.append("AI_DISCLOSURE_NOT_BOUND_TO_IMAGE")
    if job.get("disclosure_extra_images") and (not job.get("disclosure_visual_fingerprint")
            or data.get("reviewed_visual_fingerprint") != job.get("disclosure_visual_fingerprint")):
        issues.append("AI_DISCLOSURE_INSET_REVIEW_REQUIRED")
    if job.get("kind") == "ad" and not data.get("channel_reviewed"):
        issues.append("AD_CHANNEL_DISCLOSURE_REVIEW_REQUIRED")
    return issues


def export_image(image: Image.Image, job: dict, path: Path) -> dict:
    issues = disclosure_issues(job)
    if issues:
        raise ValueError(", ".join(issues))
    if image.size != tuple(job.get("canvas", [])):
        raise ValueError("EXPORT_SIZE_MISMATCH: rendered image must match the requested canvas")
    keywords = [str(v) for v in job.get("export", {}).get("keywords", []) if v != SYNTHETIC_KEYWORD]
    if job["ai_disclosure"]["human_source"] == "synthetic":
        keywords.append(SYNTHETIC_KEYWORD)
    packet = make_xmp(keywords)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    rgb = image.convert("RGB")
    try:
        if path.suffix.lower() in {".jpg", ".jpeg"}:
            quality = job.get("export", {}).get("quality", 95)
            if type(quality) is not int or not 1 <= quality <= 100:
                raise ValueError("JPEG quality must be an integer from 1 to 100")
            rgb.save(temp, format="JPEG", quality=quality,
                     subsampling=0, xmp=packet)
        elif path.suffix.lower() == ".png":
            info = PngImagePlugin.PngInfo()
            info.add_itxt("XML:com.adobe.xmp", packet.decode("utf-8"))
            rgb.save(temp, format="PNG", pnginfo=info, optimize=True)
        else:
            raise ValueError("Final output must be PNG or JPEG")
        with Image.open(temp) as check:
            actual = xmp_keywords(check)
            if set(actual) != set(keywords) or check.size != rgb.size:
                raise ValueError("Final file metadata/size round-trip verification failed")
            result = {"policy_version": POLICY_VERSION, "human_source": job["ai_disclosure"]["human_source"],
                      "embedded_keywords": actual, "verified": True,
                      "pixel_sha256": pixel_hash(check), "c2pa": "not_reissued; source originals retained"}
            if path.suffix.lower() in {".jpg", ".jpeg"}:
                result["encoding"] = {"format": "JPEG", "quality": quality, "chroma_subsampling": "4:4:4"}
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    result["file_sha256"] = file_hash(path)
    return result


def check_export(job: dict, path: Path) -> list[str]:
    issues = disclosure_issues(job)
    try:
        with Image.open(path) as image:
            keywords = xmp_keywords(image)
            data = job.get("ai_disclosure") or {}
            expected = isinstance(data, dict) and data.get("human_source") == "synthetic"
            if (SYNTHETIC_KEYWORD in keywords) != expected:
                issues.append("SYNTHETIC_PERFORMER_METADATA_MISMATCH")
            if image.mode != "RGB":
                issues.append("EXPORT_NOT_RGB")
            if image.size != tuple(job["canvas"]):
                issues.append("EXPORT_SIZE_MISMATCH")
    except (OSError, ValueError) as exc:
        issues.append(f"EXPORT_UNREADABLE:{exc}")
    return issues
