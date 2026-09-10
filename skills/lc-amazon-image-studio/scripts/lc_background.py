"""Opt-in, evidence-bound normalization of a reviewed near-white background.

The caller supplies the aspect-safe RGB image, before marketing layout/export.
This module never rewrites model output, creates a mask, or changes approvals.
"""
from __future__ import annotations

import copy
import re
from collections import deque
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from lc_assets import box_pixels, file_hash, pixel_hash

ALGORITHM_VERSION = 1
_SHA256 = re.compile(r"[0-9a-f]{64}")


class BackgroundError(ValueError):
    pass


def _config(job):
    value = job.get("background_normalization")
    if value is None:
        return None
    if (not isinstance(value, dict) or type(value.get("version")) is not int
            or value["version"] != 1 or value.get("reviewed") is not True):
        raise BackgroundError("Background normalization requires version 1 and an explicit reviewed mask decision")
    if job.get("kind") != "main":
        raise BackgroundError("Background normalization is limited to the white-background main image")
    threshold = value.get("near_white_min", 250)
    if type(threshold) is not int or not 250 <= threshold <= 254:
        raise BackgroundError("near_white_min must be an integer from 250 to 254")
    if not isinstance(value.get("source_pixel_sha256"), str) or not _SHA256.fullmatch(value["source_pixel_sha256"]):
        raise BackgroundError("The mask decision must bind the aspect-safe source pixels")
    for key in ("background_mask", "protection_mask"):
        record = value.get(key)
        if (not isinstance(record, dict) or not isinstance(record.get("path"), str) or not record["path"]
                or not isinstance(record.get("sha256"), str) or not _SHA256.fullmatch(record["sha256"])):
            raise BackgroundError(f"{key} requires a path and SHA-256 binding")
    if value.get("protection_covers_product_and_shadow") is not True:
        raise BackgroundError("The reviewed protection mask must cover both product and shadow")
    return {**copy.deepcopy(value), "near_white_min": threshold}


def _mask_path(base, record):
    base = Path(base).resolve()
    path = Path(record["path"])
    if path.is_absolute() or ".." in path.parts:
        raise BackgroundError("Background masks must use project-relative paths")
    path = base / path
    if any(parent.is_symlink() for parent in (path, *path.parents) if parent != base and parent.is_relative_to(base)):
        raise BackgroundError("Background masks cannot use symlinks")
    if not path.is_file() or file_hash(path) != record["sha256"]:
        raise BackgroundError("Background mask is missing or changed after review")
    return path


def dependencies(job, base):
    """Local image/layout dependency only; do not add to generation fingerprints."""
    config = _config(job)
    if config is None:
        return {}
    for key in ("background_mask", "protection_mask"):
        _mask_path(base, config[key])
    return {"config": config, "algorithm_version": ALGORITHM_VERSION,
            "algorithm_sha256": file_hash(Path(__file__))}


def _mask(base, record, size):
    path = _mask_path(base, record)
    with Image.open(path) as opened:
        if opened.size != size or opened.mode not in {"1", "L"}:
            raise BackgroundError("Background masks must be grayscale at the exact aspect-safe canvas size")
        mask = opened.convert("L")
    _mask_path(base, record)  # Detect replacement during decoding, not just before it.
    if any(mask.histogram()[1:255]):
        raise BackgroundError("Background masks must be binary; masks are never stretched or threshold-guessed")
    if mask.getbbox() is None:
        raise BackgroundError("Background and product/shadow protection masks must both be nonempty")
    return mask


def _edge_connected(mask):
    """Scanline flood fill: only candidate runs connected to a canvas edge."""
    width, height = mask.size
    remaining = bytearray(mask.tobytes())
    accepted = bytearray(len(remaining))
    seeds = deque([*range(width), *range((height - 1) * width, height * width)])
    seeds.extend(y * width for y in range(1, height - 1))
    seeds.extend(y * width + width - 1 for y in range(1, height - 1))
    while seeds:
        index = seeds.popleft()
        if not remaining[index]:
            continue
        row_start = index // width * width
        row_end = row_start + width
        left = remaining.rfind(b"\0", row_start, index) + 1
        left = max(left, row_start)
        right = remaining.find(b"\0", index, row_end)
        right = row_end if right < 0 else right
        remaining[left:right] = b"\0" * (right - left)
        accepted[left:right] = b"\xff" * (right - left)
        for shift in (-width, width):
            start, stop = left + shift, right + shift
            if start < 0 or stop > len(remaining):
                continue
            while start < stop:
                start = remaining.find(b"\xff", start, stop)
                if start < 0:
                    break
                seeds.append(start)
                run_end = remaining.find(b"\0", start, stop)
                start = stop if run_end < 0 else run_end + 1
    return Image.frombytes("L", mask.size, bytes(accepted))


def apply(image, job, base):
    """Return (new RGB image, evidence); fail closed before modifying any pixels."""
    binding = dependencies(job, base)
    if not binding:
        return image, {"applied": False, "reason": "not_configured"}
    config = binding["config"]
    if image.mode != "RGB" or pixel_hash(image) != config["source_pixel_sha256"]:
        raise BackgroundError("Background masks are not bound to these aspect-safe RGB pixels")
    allowed = _mask(base, config["background_mask"], image.size)
    protected = _mask(base, config["protection_mask"], image.size)
    if ImageChops.multiply(allowed, protected).getbbox() is not None:
        raise BackgroundError("Reviewed background mask overlaps product/shadow protection")
    # Keep the whole known product container untouched, including white highlights.
    # This intentionally gives up cleaning gaps within the product's bounding box.
    if job.get("output_product_bbox_norm") is not None:
        bounds = box_pixels(job["output_product_bbox_norm"], image.size)
        ImageDraw.Draw(protected).rectangle((bounds[0], bounds[1], bounds[2] - 1, bounds[3] - 1), fill=255)
    candidate = ImageChops.multiply(allowed, ImageChops.invert(protected))
    for channel in image.split():
        candidate = ImageChops.multiply(candidate, channel.point(lambda v: 255 if v >= config["near_white_min"] else 0))
    adopted = _edge_connected(candidate)
    output = Image.composite(Image.new("RGB", image.size, "white"), image, adopted)
    difference = ImageChops.difference(output, image)
    red, green, blue = difference.split()
    changed = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    changed_count = sum(changed.histogram()[1:])
    return output, {"applied": bool(changed_count), "reason": "normalized" if changed_count else "no_eligible_pixels",
                    "changed_pixels": changed_count, "source_pixel_sha256": pixel_hash(image),
                    "output_pixel_sha256": pixel_hash(output), "protected_pixels_unchanged": True,
                    "dependencies": binding}
