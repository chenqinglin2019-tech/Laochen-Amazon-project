"""Generation frame for a canvas (V7.2): the photo fills the canvas, no white bars.

Image tools return a few frames (1:1, 3:2, 2:3). A canvas with another aspect
(A+ 1464x600 or 970x600, listing 1600x2080) used to be `contain`-ed into the
canvas with white padding: the product looked shrunk and every planned box in the
prompt was in the wrong frame. For new projects (`layout_first_policy.frame_fit
== "cover"`):

- the prompt asks for the nearest frame and says only the central band is used
  (`plan`), with every placement expressed in frame coordinates;
- at ingest that band is cut from the returned image (slid to keep the whole
  product when the agent gave its box) and resized to the exact canvas, so the
  frozen `contain` step is an exact full-canvas fit; the returned file is kept
  as the attempt's master.

Nothing is cropped to make room for text; the band is planned before generation.
"""
from __future__ import annotations

import math

FRAMES = {"1:1": (1, 1), "3:2": (3, 2), "2:3": (2, 3)}
SIZES = {"1:1": "1024x1024", "3:2": "1536x1024", "2:3": "1024x1536"}
TOLERANCE = 0.01  # relative aspect difference treated as identical
PRODUCT_MARGIN = 0.02


def enabled(manifest):
    policy = (manifest or {}).get("layout_first_policy")
    return isinstance(policy, dict) and policy.get("version") == 1 and policy.get("frame_fit", "cover") == "cover"


def plan(canvas):
    """Nearest tool frame and the band of it that becomes the canvas (normalized in the frame)."""
    width, height = canvas
    ratio = width / height
    name = min(FRAMES, key=lambda key: abs(math.log(ratio / (FRAMES[key][0] / FRAMES[key][1]))))
    frame_ratio = FRAMES[name][0] / FRAMES[name][1]
    if abs(ratio / frame_ratio - 1) <= TOLERANCE:
        band = [0.0, 0.0, 1.0, 1.0]
    elif ratio > frame_ratio:
        fraction = frame_ratio / ratio
        band = [0.0, round((1 - fraction) / 2, 4), 1.0, round(fraction, 4)]
    else:
        fraction = ratio / frame_ratio
        band = [round((1 - fraction) / 2, 4), 0.0, round(fraction, 4), 1.0]
    return {"frame": name, "size": SIZES[name], "band": band, "exact": band == [0.0, 0.0, 1.0, 1.0],
            "orientation": "square" if name == "1:1" else "landscape" if name == "3:2" else "portrait"}


def canvas_to_frame(box, band):
    """A canvas-normalized box expressed in the generation frame."""
    bx, by, bw, bh = band
    x, y, w, h = box
    return [round(bx + x * bw, 4), round(by + y * bh, 4), round(w * bw, 4), round(h * bh, 4)]


def same_aspect(size, canvas):
    return abs((size[0] / size[1]) / (canvas[0] / canvas[1]) - 1) <= TOLERANCE / 2


def crop_box(source_size, canvas, product=None):
    """Pixel crop (left, top, right, bottom) with the canvas aspect, plus whether the product is trimmed.

    `product` is the product box normalized to the source image (the agent's --bbox)."""
    sw, sh = source_size
    width, height = canvas
    ratio = width / height
    if sw / sh > ratio:
        cw, ch = max(1, round(sh * ratio)), sh
    else:
        cw, ch = sw, max(1, round(sw / ratio))
    left, top = (sw - cw) / 2, (sh - ch) / 2
    trimmed = False
    if product:
        x, y, w, h = product
        margin_x, margin_y = PRODUCT_MARGIN * sw, PRODUCT_MARGIN * sh
        p_left, p_right = x * sw - margin_x, (x + w) * sw + margin_x
        p_top, p_bottom = y * sh - margin_y, (y + h) * sh + margin_y
        if cw < sw:
            if p_right - p_left <= cw:
                left = min(max(left, p_right - cw), p_left)
            else:
                left = (p_left + p_right) / 2 - cw / 2
                trimmed = (x + w - x) * sw > cw
        if ch < sh:
            if p_bottom - p_top <= ch:
                top = min(max(top, p_bottom - ch), p_top)
            else:
                top = (p_top + p_bottom) / 2 - ch / 2
                trimmed = trimmed or h * sh > ch
        left, top = min(max(0, left), sw - cw), min(max(0, top), sh - ch)
        inside_x = x * sw >= left - 1 and (x + w) * sw <= left + cw + 1
        inside_y = y * sh >= top - 1 and (y + h) * sh <= top + ch + 1
        trimmed = trimmed or not (inside_x and inside_y)
    left, top = round(left), round(top)
    return [left, top, left + cw, top + ch], trimmed


def source_box_to_raw(box, crop, source_size):
    """Map a box normalized to the returned image into the cropped raw (normalized)."""
    sw, sh = source_size
    left, top, right, bottom = crop
    cw, ch = right - left, bottom - top
    x, y, w, h = box
    x0, y0 = max(0.0, (x * sw - left) / cw), max(0.0, (y * sh - top) / ch)
    x1, y1 = min(1.0, ((x + w) * sw - left) / cw), min(1.0, ((y + h) * sh - top) / ch)
    return [round(x0, 4), round(y0, 4), round(max(0.0, x1 - x0), 4), round(max(0.0, y1 - y0), 4)]


def fit(payload, canvas, product=None):
    """Return (png_bytes, record) for a returned image whose aspect differs from the canvas."""
    import hashlib
    import io
    from PIL import Image, ImageOps
    with Image.open(io.BytesIO(payload)) as opened:
        source = ImageOps.exif_transpose(opened).convert("RGB")
    crop, trimmed = crop_box(source.size, canvas, product)
    image = source.crop(tuple(crop)).resize(tuple(canvas), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    data = buffer.getvalue()
    expected = plan(canvas)
    frame_ratio = FRAMES[expected["frame"]][0] / FRAMES[expected["frame"]][1]
    return data, {"version": 1, "source_sha256": hashlib.sha256(payload).hexdigest(), "source_size": list(source.size),
                  "crop_px": crop, "canvas": list(canvas), "raw_sha256": hashlib.sha256(data).hexdigest(),
                  "frame_requested": expected["frame"],
                  "frame_matched": abs((source.size[0] / source.size[1]) / frame_ratio - 1) <= TOLERANCE,
                  "product_trimmed": bool(trimmed), "product_hint": product}
