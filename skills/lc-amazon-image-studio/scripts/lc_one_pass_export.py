"""Technical exports only. No OCR, typography, browser or visual QA."""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps, PngImagePlugin

from lc_one_pass_io import StudioError, digest, inside, sha256, write_bytes


def open_image(path):
    with Image.open(path) as image:
        if image.format not in {"PNG", "JPEG", "WEBP"} or getattr(image, "n_frames", 1) != 1:
            raise StudioError("UNSUPPORTED_IMAGE_FORMAT")
        image.load()
        return ImageOps.exif_transpose(image).copy()


def normalize(image, canvas):
    width, height = canvas
    # One source pixel of rounding is allowed; no crop, stretch or added panels.
    if abs(image.width * height - image.height * width) > max(width, height):
        raise StudioError("ASPECT_RATIO_MISMATCH")
    if image.size != (width, height):
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    return image


def alpha_background(image):
    if "A" not in image.getbands() and "transparency" not in image.info:
        raise StudioError("MAIN_ALPHA_REQUIRED")
    alpha = image.convert("RGBA").getchannel("A")
    counts = alpha.histogram()
    if not counts[0] or counts[0] == image.width * image.height:
        raise StudioError("MAIN_FOREGROUND_AND_BACKGROUND_REQUIRED")
    # Require the canvas boundary to be background; do not infer it from brightness.
    edges = (alpha.crop((0, 0, alpha.width, 1)), alpha.crop((0, alpha.height - 1, alpha.width, alpha.height)),
             alpha.crop((0, 0, 1, alpha.height)), alpha.crop((alpha.width - 1, 0, alpha.width, alpha.height)))
    if any(edge.getbbox() is not None for edge in edges):
        raise StudioError("MAIN_FOREGROUND_TOUCHES_CANVAS_EDGE")
    return alpha.point(lambda value: 255 if value == 0 else 0)


def export_settings(job):
    settings = {"canvas": job["canvas"], "human_source": job.get("human_source", "none"),
                "keywords": job.get("export_keywords", []), "format": "PNG", "version": 1}
    if job["kind"] == "main" and job.get("main_processing_version"):
        from lc_one_pass_main import processing_settings
        settings["main_processing"] = processing_settings(job)
    return settings


def export_job(job, base):
    if job["kind"] == "main" and job.get("main_processing_version"):
        from lc_one_pass_main import verify_prepared
        image = verify_prepared(job, base)
    else:
        image = normalize(open_image(inside(base, job["raw_output"])), job["canvas"])
    background = None
    if job["kind"] == "main":
        check = job.get("main_background_check") or {}
        if check.get("raw_sha256") != job["raw_sha256"] or check.get("verdict") != "pass":
            raise StudioError("MAIN_BACKGROUND_CHECK_REQUIRED")
        if (job.get("main_processing_version") and
                check.get("processing_id") != job["main_processing"]["processing_id"]):
            raise StudioError("MAIN_PROCESSING_CHECK_REQUIRED")
        background = alpha_background(image)
        white = Image.new("RGBA", image.size, (255, 255, 255, 255))
        image = Image.alpha_composite(white, image.convert("RGBA")).convert("RGB")
    else:
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    metadata = PngImagePlugin.PngInfo()
    # Preserve disclosure intent without pretending that anyone reviewed the output.
    keywords = sorted(set(job.get("export_keywords", [])) - {"contains-synthetic-performer"})
    if job.get("human_source") == "synthetic":
        keywords.append("contains-synthetic-performer")
    if keywords:
        from lc_assets import make_xmp
        metadata.add_itxt("XML:com.adobe.xmp", make_xmp(keywords).decode("utf-8"))
    metadata.add_text("generation-source", "Codex built-in image generation")
    stream = io.BytesIO()
    image.save(stream, format="PNG", pnginfo=metadata)
    output_hash = digest({"source": job["raw_sha256"], "settings": export_settings(job),
                          "main_check": job.get("main_background_check") if background else None})
    relative = f"final/{job['id']}-{output_hash[:16]}.png"
    path = inside(base, relative)
    write_bytes(path, stream.getvalue(), immutable=True)
    with Image.open(path) as final:
        final.load()
        if final.size != tuple(job["canvas"]):
            raise StudioError("FINAL_SIZE_MISMATCH")
        if background:
            # Check every selected background pixel after final-file decoding.
            extrema = Image.composite(final.convert("RGB"), Image.new("RGB", final.size, "white"),
                                      background).getextrema()
            if extrema != ((255, 255), (255, 255), (255, 255)):
                raise StudioError("MAIN_FINAL_BACKGROUND_NOT_WHITE")
    record = {"path": relative, "sha256": sha256(path), "raw_sha256": job["raw_sha256"],
              "settings_hash": digest(export_settings(job)), "canvas": job["canvas"], "format": "PNG"}
    if job["kind"] == "main" and job.get("main_processing_version"):
        record["processing_id"] = job["main_processing"]["processing_id"]
        record["main_check_hash"] = digest(job["main_background_check"])
    if background:
        mask_path = f"source/masks/{job['id']}-{output_hash[:16]}.png"
        encoded = io.BytesIO()
        background.save(encoded, format="PNG")
        write_bytes(inside(base, mask_path), encoded.getvalue(), immutable=True)
        record["white_background"] = {"rgb": [255, 255, 255], "mask": mask_path,
                                      "mask_sha256": sha256(inside(base, mask_path)),
                                      "background_pixels": background.histogram()[255],
                                      "final_sha256": record["sha256"]}
    return record


def verify_export(job, base):
    record = job.get("delivery") or {}
    if not record or job.get("status") != "ready_to_deliver":
        raise StudioError("IMAGE_NOT_READY")
    path = inside(base, record["path"])
    if sha256(path) != record["sha256"] or digest(export_settings(job)) != record["settings_hash"]:
        raise StudioError("FINAL_FILE_OR_EXPORT_SETTINGS_CHANGED")
    if sha256(inside(base, job["raw_output"])) != record["raw_sha256"]:
        raise StudioError("RAW_FILE_CHANGED")
    image = open_image(path)
    if image.size != tuple(job["canvas"]):
        raise StudioError("FINAL_SIZE_MISMATCH")
    if job["kind"] == "main":
        expected_mask = None
        if job.get("main_processing_version"):
            from lc_one_pass_main import verify_prepared
            prepared = verify_prepared(job, base)
            check = job.get("main_background_check", {})
            if (record.get("processing_id") != job["main_processing"]["processing_id"] or
                    check.get("processing_id") != record["processing_id"] or
                    record.get("main_check_hash") != digest(check) or
                    check.get("raw_sha256") != job["raw_sha256"] or check.get("verdict") != "pass"):
                raise StudioError("MAIN_PROCESSING_CHECK_REQUIRED")
            expected_mask = alpha_background(prepared)
        white = record.get("white_background") or {}
        if white.get("final_sha256") != record["sha256"]:
            raise StudioError("WHITE_BACKGROUND_BINDING_CHANGED")
        mask_path = inside(base, white["mask"])
        if sha256(mask_path) != white["mask_sha256"]:
            raise StudioError("WHITE_BACKGROUND_MASK_CHANGED")
        with Image.open(mask_path) as mask:
            if mask.size != image.size or mask.mode != "L":
                raise StudioError("WHITE_BACKGROUND_MASK_INVALID")
            if expected_mask is not None and mask.tobytes() != expected_mask.tobytes():
                raise StudioError("WHITE_BACKGROUND_MASK_SOURCE_MISMATCH")
            if Image.composite(image.convert("RGB"), Image.new("RGB", image.size, "white"), mask).getextrema() != ((255, 255),) * 3:
                raise StudioError("MAIN_FINAL_BACKGROUND_NOT_WHITE")
    return path
