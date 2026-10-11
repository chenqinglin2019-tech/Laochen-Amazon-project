"""Conservative, versioned main-image processing; originals are never rewritten."""
from __future__ import annotations

import io
import math
from collections import deque

from PIL import Image, ImageFilter

from lc_one_pass_io import StudioError, digest, inside, sha256, write_bytes

PROCESSING_VERSION = 1
PARAMETERS = {"weak_alpha_max": 16, "protection_short_edge_fraction": 0.005,
              "protection_min_pixels": 2, "component_area_fraction": 0.00002,
              "total_cleanup_fraction": 0.0005, "canvas_fill": 0.9,
              "component_connectivity": 8, "exterior_connectivity": 4,
              "resampling": "premultiplied_lanczos"}
BACKGROUND_ERRORS = {"MAIN_ALPHA_REQUIRED", "MAIN_FOREGROUND_AND_BACKGROUND_REQUIRED",
                     "MAIN_FOREGROUND_TOUCHES_CANVAS_EDGE", "MAIN_FOREGROUND_UNCERTAIN"}


def processing_settings(job):
    version = job.get("main_processing_version", PROCESSING_VERSION)
    if version != PROCESSING_VERSION:
        raise StudioError("UNKNOWN_MAIN_PROCESSING_VERSION")
    foreground = job.get("main_foreground_type", "unknown")
    if foreground not in {"opaque", "translucent", "unknown"}:
        raise StudioError("INVALID_MAIN_FOREGROUND_TYPE")
    return {"version": version, "canvas": list(job["canvas"]), "foreground_type": foreground,
            "parameters": dict(PARAMETERS)}


def boundary_max(alpha):
    w, h = alpha.size
    edges = ((0, 0, w, 1), (0, h - 1, w, h), (0, 0, 1, h), (w - 1, 0, w, h))
    return max(alpha.crop(box).getextrema()[1] for box in edges)


def exterior_zero(alpha):
    """Four-connected fully transparent background reached from the canvas boundary."""
    w, h = alpha.size
    values = alpha.tobytes()
    reached = bytearray(w * h)
    queue = deque()

    def push(p):
        if not values[p] and not reached[p]:
            reached[p] = 1
            queue.append(p)

    for x in range(w):
        push(x)
        push((h - 1) * w + x)
    for y in range(h):
        push(y * w)
        push(y * w + w - 1)
    while queue:
        p = queue.popleft()
        x, y = p % w, p // w
        if x:
            push(p - 1)
        if x + 1 < w:
            push(p + 1)
        if y:
            push(p - w)
        if y + 1 < h:
            push(p + w)
    return reached


def clean_detached_residue(alpha):
    w, h = alpha.size
    size = w * h
    radius = max(PARAMETERS["protection_min_pixels"],
                 math.ceil(min(w, h) * PARAMETERS["protection_short_edge_fraction"]))
    protected = alpha.point(lambda v: 255 if v > PARAMETERS["weak_alpha_max"] else 0)
    protected = protected.filter(ImageFilter.MaxFilter(2 * radius + 1)).tobytes()
    exterior = exterior_zero(alpha)
    values = alpha.tobytes()
    visited = bytearray(size)
    limit = max(1, math.floor(size * PARAMETERS["component_area_fraction"]))
    total_limit = max(1, math.floor(size * PARAMETERS["total_cleanup_fraction"]))
    removable = []
    for start, value in enumerate(values):
        if not value or visited[start]:
            continue
        queue = deque([start])
        visited[start] = 1
        pixels, count, safe, adjacent = [], 0, True, False
        while queue:
            p = queue.popleft()
            x, y = p % w, p // w
            count += 1
            if count <= limit:
                pixels.append(p)
            safe = safe and values[p] <= PARAMETERS["weak_alpha_max"] and not protected[p]
            for dy in (-1, 0, 1):
                ny = y + dy
                if not 0 <= ny < h:
                    continue
                for dx in (-1, 0, 1):
                    nx = x + dx
                    if not 0 <= nx < w or (dx == 0 and dy == 0):
                        continue
                    q = ny * w + nx
                    if abs(dx) + abs(dy) == 1 and exterior[q]:
                        adjacent = True
                    if values[q] and not visited[q]:
                        visited[q] = 1
                        queue.append(q)
        if safe and adjacent and count <= limit:
            removable.extend(pixels)
    if len(removable) > total_limit:
        return alpha.copy(), 0, True
    cleaned = bytearray(values)
    for p in removable:
        cleaned[p] = 0
    return Image.frombytes("L", alpha.size, bytes(cleaned)), len(removable), False


def prepare_pixels(image, canvas, foreground_type="unknown"):
    """Analyse source pixels before any resampling; keep every retained component."""
    if "A" not in image.getbands() and "transparency" not in image.info:
        raise StudioError("MAIN_ALPHA_REQUIRED")
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    counts = alpha.histogram()
    if not counts[0] or counts[0] == rgba.width * rgba.height:
        raise StudioError("MAIN_FOREGROUND_AND_BACKGROUND_REQUIRED")
    edge_alpha = boundary_max(alpha)
    if edge_alpha > PARAMETERS["weak_alpha_max"]:
        raise StudioError("MAIN_FOREGROUND_TOUCHES_CANVAS_EDGE")
    if alpha.getextrema()[1] <= PARAMETERS["weak_alpha_max"]:
        raise StudioError("MAIN_FOREGROUND_UNCERTAIN")
    removed, limited = 0, False
    if foreground_type == "opaque":
        alpha, removed, limited = clean_detached_residue(alpha)
        rgba.putalpha(alpha)
    elif foreground_type not in {"translucent", "unknown"}:
        raise StudioError("INVALID_MAIN_FOREGROUND_TYPE")
    bbox = alpha.getbbox()
    width, height = canvas
    source_width, source_height = bbox[2] - bbox[0], bbox[3] - bbox[1]
    scale = min(width * PARAMETERS["canvas_fill"] / source_width,
                height * PARAMETERS["canvas_fill"] / source_height)
    fitted = (max(1, math.floor(source_width * scale)), max(1, math.floor(source_height * scale)))
    offset = ((width - fitted[0]) // 2, (height - fitted[1]) // 2)
    # Premultiplied alpha prevents hidden RGB in transparent pixels bleeding into edges.
    subject = rgba.crop(bbox).convert("RGBa").resize(fitted, Image.Resampling.LANCZOS).convert("RGBA")
    prepared = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    prepared.paste(subject, offset)
    return prepared, {"source_size": list(rgba.size), "source_bbox": list(bbox), "scale": scale,
                      "fitted_size": list(fitted), "offset": list(offset),
                      "removed_pixels": removed, "cleanup_limit_exceeded": limited,
                      "source_boundary_max_alpha": edge_alpha,
                      "requires_endpoint_check": edge_alpha > 0}


def verify_prepared(job, base):
    from lc_one_pass_export import open_image
    record = job.get("main_processing")
    if not isinstance(record, dict) or record.get("processing_id") != digest(
            {key: value for key, value in record.items() if key != "processing_id"}):
        raise StudioError("MAIN_PROCESSING_RECORD_CHANGED")
    if record["settings"] != processing_settings(job):
        raise StudioError("MAIN_PROCESSING_SETTINGS_CHANGED")
    if record["raw_sha256"] != job.get("raw_sha256") or record["raw_output"] != job.get("raw_output"):
        raise StudioError("MAIN_PROCESSING_SOURCE_CHANGED")
    if sha256(inside(base, record["raw_output"])) != record["raw_sha256"]:
        raise StudioError("RAW_FILE_CHANGED")
    path = inside(base, record["path"])
    if sha256(path) != record["sha256"]:
        raise StudioError("MAIN_PROCESSED_FILE_CHANGED")
    image = open_image(path)
    if image.mode != "RGBA" or image.size != tuple(job["canvas"]):
        raise StudioError("MAIN_PROCESSED_SPEC_CHANGED")
    return image


def prepare_artifact(job, base):
    from lc_one_pass_export import open_image
    settings = processing_settings(job)
    raw = inside(base, job["raw_output"])
    if sha256(raw) != job["raw_sha256"]:
        raise StudioError("RAW_FILE_CHANGED")
    previous = job.get("main_processing")
    if previous:
        if previous.get("processing_id") != digest({k: v for k, v in previous.items() if k != "processing_id"}):
            raise StudioError("MAIN_PROCESSING_RECORD_CHANGED")
        if previous["settings"] == settings and previous["raw_sha256"] == job["raw_sha256"]:
            verify_prepared(job, base)
            return previous
    image, transform = prepare_pixels(open_image(raw), job["canvas"], settings["foreground_type"])
    key = digest({"raw_sha256": job["raw_sha256"], "settings": settings})
    relative = f"processed/{job['id']}-{key[:16]}.png"
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    write_bytes(inside(base, relative), stream.getvalue(), immutable=True)
    record = {"raw_output": job["raw_output"], "raw_sha256": job["raw_sha256"],
              "settings": settings, "transform": transform, "path": relative,
              "sha256": sha256(inside(base, relative))}
    record["processing_id"] = digest(record)
    return record
