#!/usr/bin/env python3
"""Synthetic success-rate benchmark for the pure-white main image (V8, maintainers only).

Simulates model outputs (1024 px) for product types x imperfections on the backdrop that
`studio_main.choose_backdrop` would request, runs the real cutout -> compose -> export ->
verify chain and reports, per case: first-try pass, safe failure (an error code that
triggers a targeted redo), and SILENT BAD (accepted but the product mask is wrong or a
background block is not 255). Silent bad must stay 0. Redo attempts are simulated with a
more compliant output (the correction the redo prompt asks for).

    python -X utf8 benchmark_main_white.py [--out result.json] [--always-white]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_main as sm  # noqa: E402

SIZE = 1024


# ---------------------------------------------------------------- products (RGB layer + GT mask)

def _layer():
    return Image.new("RGB", (SIZE, SIZE), (0, 0, 0)), Image.new("L", (SIZE, SIZE), 0)


def _gradient_fill(draw_box, mask, left_colour, right_colour, rgb):
    x0, y0, x1, y1 = draw_box
    array = np.asarray(rgb).copy()
    m = np.asarray(mask) > 0
    xs = np.linspace(0, 1, x1 - x0)[None, :, None]
    band = (np.asarray(left_colour) * (1 - xs) + np.asarray(right_colour) * xs).astype(np.uint8)
    region = np.broadcast_to(band, (y1 - y0, x1 - x0, 3))
    sub = array[y0:y1, x0:x1]
    sub[m[y0:y1, x0:x1]] = region[m[y0:y1, x0:x1]]
    return Image.fromarray(array)


def product(name, scale=1.0, offset=(0, 0)):
    rgb, mask = _layer()
    d, md = ImageDraw.Draw(rgb), ImageDraw.Draw(mask)
    cx, cy = SIZE // 2 + offset[0], SIZE // 2 + offset[1]
    half_w, half_h = int(300 * scale), int(360 * scale)
    box = (cx - half_w, cy - half_h, cx + half_w, cy + half_h)
    hole = None
    if name == "black_box":
        md.rounded_rectangle(box, 40, fill=255)
        rgb = _gradient_fill(box, mask, (25, 25, 28), (60, 60, 66), rgb)
    elif name == "white_box":
        md.rounded_rectangle(box, 40, fill=255)
        rgb = _gradient_fill(box, mask, (248, 248, 248), (222, 222, 224), rgb)
        d = ImageDraw.Draw(rgb)
        for i in range(3):
            d.ellipse((cx - 40 + i * 30, cy + 200, cx - 20 + i * 30, cy + 220), fill=(20, 20, 20))
    elif name == "light_grey_cylinder":
        md.rectangle(box, fill=255)
        md.ellipse((box[0], box[1] - 60, box[2], box[1] + 60), fill=255)
        rgb = _gradient_fill((box[0], box[1] - 60, box[2], box[3]), mask, (170, 170, 172), (232, 232, 234), rgb)
    elif name == "red_bottle":
        body = (cx - 170, cy - 150, cx + 170, cy + 360)
        md.rounded_rectangle(body, 60, fill=255)
        md.rectangle((cx - 60, cy - 330, cx + 60, cy - 150), fill=255)
        d.rounded_rectangle(body, 60, fill=(196, 32, 40))
        d.rectangle((cx - 60, cy - 330, cx + 60, cy - 150), fill=(196, 32, 40))
        md.rectangle((cx - 70, cy - 380, cx + 70, cy - 320), fill=255)
        d.rectangle((cx - 70, cy - 380, cx + 70, cy - 320), fill=(15, 15, 15))
    elif name == "metal":
        md.rounded_rectangle(box, 70, fill=255)
        rgb = _gradient_fill(box, mask, (95, 95, 100), (238, 238, 242), rgb)
        d = ImageDraw.Draw(rgb)
        d.rectangle((cx + 60, box[1] + 20, cx + 90, box[3] - 20), fill=(252, 252, 252))
    elif name in {"mug_hole", "white_mug_hole"}:
        colour = (40, 90, 180) if name == "mug_hole" else (238, 238, 238)
        body = (cx - 330, cy - 330, cx + 170, cy + 370)
        md.rounded_rectangle(body, 30, fill=255)
        d.rounded_rectangle(body, 30, fill=colour)
        ring_outer = (cx + 90, cy - 190, cx + 400, cy + 190)
        ring_inner = (cx + 170, cy - 105, cx + 320, cy + 105)
        md.ellipse(ring_outer, fill=255)
        d.ellipse(ring_outer, fill=colour)
        md.ellipse(ring_inner, fill=0)
        hole = ring_inner
        md.rounded_rectangle(body, 30, fill=255)
        d.rounded_rectangle(body, 30, fill=colour)
    elif name == "set_two":
        case = (cx - 330, cy - 120, cx + 30, cy + 260)
        md.rounded_rectangle(case, 60, fill=255)
        d.rounded_rectangle(case, 60, fill=(60, 60, 64))
        for ex in (cx + 120, cx + 260):
            md.ellipse((ex - 55, cy - 40, ex + 55, cy + 70), fill=255)
            d.ellipse((ex - 55, cy - 40, ex + 55, cy + 70), fill=(232, 232, 236))
    elif name == "cable":
        dev = (cx - 200, cy - 300, cx + 200, cy + 120)
        md.rounded_rectangle(dev, 30, fill=255)
        d.rounded_rectangle(dev, 30, fill=(45, 45, 50))
        points = [(cx, cy + 120), (cx + 60, cy + 220), (cx - 40, cy + 300), (cx + 100, cy + 380)]
        md.line(points, fill=255, width=4)
        d.line(points, fill=(30, 30, 30), width=4)
    elif name == "glass":
        body = (cx - 180, cy - 300, cx + 180, cy + 340)
        md.rounded_rectangle(body, 80, fill=255)
        d.rounded_rectangle(body, 80, fill=(205, 222, 232))
        d.rounded_rectangle(body, 80, outline=(120, 140, 150), width=6)
    return rgb, mask, hole


# ---------------------------------------------------------------- simulated model output

def render(name, backdrop_rgb, flaw, *, scale=1.0, offset=(0, 0)):
    rgb, mask, hole = product(name, scale, offset)
    base = np.full((SIZE, SIZE, 3), backdrop_rgb, np.float32)
    if flaw == "offwhite" and tuple(backdrop_rgb) == (255, 255, 255):
        base[:] = (244, 244, 244)
    if flaw == "vignette":
        yy, xx = np.mgrid[0:SIZE, 0:SIZE] / (SIZE - 1) - 0.5
        base *= (1 - 0.16 * (xx ** 2 + yy ** 2) / 0.5)[..., None]
    if flaw == "gradient":
        base -= np.linspace(0, 14, SIZE)[:, None, None]
    m = np.asarray(mask, np.float32) / 255.0
    if flaw in {"soft_shadow", "hard_shadow"}:
        bbox = mask.getbbox()
        shadow = Image.new("L", (SIZE, SIZE), 0)
        sd = ImageDraw.Draw(shadow)
        if flaw == "soft_shadow":
            sd.ellipse((bbox[0] + 20, bbox[3] - 30, bbox[2] - 20, bbox[3] + 50), fill=255)
            shadow = shadow.filter(ImageFilter.GaussianBlur(22))
            strength = 0.32
        else:
            shifted = Image.new("L", (SIZE, SIZE), 0)
            shifted.paste(mask.crop((bbox[0], bbox[3] - 120, bbox[2], bbox[3])), (bbox[0] + 30, bbox[3] - 60))
            shadow = shifted
            strength = 0.25
        s = np.asarray(shadow, np.float32)[..., None] / 255.0
        base *= (1 - strength * s)
    if flaw == "glass_alpha":
        pass
    alpha = m[..., None]
    if name == "glass":
        alpha = alpha * 0.55
        rim = np.asarray(mask.filter(ImageFilter.FIND_EDGES), np.float32)[..., None] / 255.0
        alpha = np.maximum(alpha, rim)
    out = base * (1 - alpha) + np.asarray(rgb, np.float32) * alpha
    if flaw == "noise":
        out += np.random.default_rng(7).normal(0, 2.5, out.shape)
    image = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")
    if flaw == "jpeg":
        import io
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=80)
        image = Image.open(io.BytesIO(buffer.getvalue())).convert("RGB")
    return image, np.asarray(mask) > 127, hole


def reference_photo(name):
    rgb, mask, _ = product(name)
    base = Image.new("RGB", (SIZE, SIZE), (247, 247, 247))
    base.paste(rgb, (0, 0), mask)
    return base, None


# ---------------------------------------------------------------- one case

def attempt(name, backdrop_rgb, flaw, temp, *, scale=1.0, offset=(0, 0)):
    image, truth, hole = render(name, backdrop_rgb, flaw, scale=scale, offset=offset)
    raw = Path(temp) / f"{name}-{flaw}.png"
    image.save(raw)
    started = time.monotonic()
    try:
        img, alpha = sm.open_normalized(raw)
        light = name in {"white_box", "white_mug_hole", "glass"} and tuple(backdrop_rgb) == (255, 255, 255)
        foreground, matte, info = sm.cutout(img, alpha=alpha, light_product=light, strict_outline=True)
        result, placed, placement = sm.compose(foreground, matte, (2000, 2000),
                                               max_upscale=sm.GENERATED_MAX_UPSCALE, sharpen=True)
        exported = sm.export(result, placed, Path(temp) / f"{name}-{flaw}.jpg")
    except sm.MainError as exc:
        return {"outcome": "safe_failure", "code": exc.code, "seconds": round(time.monotonic() - started, 2)}
    predicted = np.asarray(matte) > 127
    union = (predicted | truth).sum()
    iou = float((predicted & truth).sum() / union) if union else 0.0
    verified = exported["verify"]["ok"]
    # What a buyer sees: our cut-out on white vs the true product on white (raw scale).
    rgb_true, mask_true, _ = product(name, scale, offset)
    true_white = np.full((SIZE, SIZE, 3), 255.0)
    t = (np.asarray(mask_true, np.float32) / 255.0)[..., None]
    if name == "glass":
        t = t * 0.55
    true_white = true_white * (1 - t) + np.asarray(rgb_true, np.float32) * t
    a = (np.asarray(matte, np.float32) / 255.0)[..., None]
    ours = 255.0 * (1 - a) + np.asarray(foreground, np.float32) * a
    region = (predicted | truth)
    visible = (np.abs(ours - true_white).max(axis=2) > 40) & region
    visible_error = float(visible.sum() / max(1, truth.sum()))
    good = verified and visible_error <= 0.01
    return {"outcome": "pass" if good else "silent_bad", "iou": round(iou, 4), "visible_error": round(visible_error, 4),
            "verified": verified,
            "format": exported["format"], "shadow_removed": info.get("shadow_removed"),
            "holes": info.get("holes_removed"), "light_edge": info.get("light_edge"), "faint_outline": info.get("faint_outline"),
            "seconds": round(time.monotonic() - started, 2)}


REDO_FIX = {  # what the targeted redo prompt asks the model to change
    "MAIN_SHADOW_AMBIGUOUS": {"flaw": "clean"},
    "MAIN_BACKGROUND_NOT_PLAIN": {"flaw": "clean"},
    "MAIN_PRODUCT_CROPPED": {"scale": 0.9, "offset": (0, 0)},
    "MAIN_PRODUCT_TOO_SMALL": {"scale": 1.3},
    "MAIN_CUTOUT_INCOMPLETE": {"switch_backdrop": True},
    "MAIN_NO_PRODUCT": {"flaw": "clean"},
    "MAIN_VERIFY_FAILED": {"flaw": "clean"},
}

PRODUCTS = ["black_box", "white_box", "light_grey_cylinder", "red_bottle", "metal", "mug_hole", "white_mug_hole",
            "set_two", "cable", "glass"]
FLAWS = ["clean", "noise", "vignette", "gradient", "soft_shadow", "hard_shadow", "jpeg", "offwhite"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    parser.add_argument("--always-white", action="store_true", help="baseline: always request a white backdrop")
    parser.add_argument("--products", nargs="*")
    parser.add_argument("--flaws", nargs="*")
    args = parser.parse_args()
    products, flaws = args.products or PRODUCTS, args.flaws or FLAWS
    rows = []
    with tempfile.TemporaryDirectory(prefix="lc-main-white-") as temp:
        for name in products:
            choice = {"backdrop": "white"} if args.always_white else sm.choose_backdrop([reference_photo(name)])
            backdrop = sm.BACKDROPS[choice["backdrop"]]
            for flaw in flaws:
                first = attempt(name, backdrop, flaw, temp)
                tries, final, current = [first], first, {"flaw": flaw, "backdrop": backdrop, "scale": 1.0, "offset": (0, 0)}
                while final["outcome"] == "safe_failure" and len(tries) < 3:
                    fix = REDO_FIX.get(final["code"], {"flaw": "clean"})
                    if fix.get("switch_backdrop"):
                        others = [c for c in sm.BACKDROPS.values() if c != current["backdrop"]]
                        current["backdrop"] = others[0] if tuple(current["backdrop"]) == (255, 255, 255) else (255, 255, 255)
                        current["flaw"] = "clean"
                    current.update({k: v for k, v in fix.items() if k != "switch_backdrop"})
                    final = attempt(name, current["backdrop"], current["flaw"], temp,
                                    scale=current["scale"], offset=current["offset"])
                    tries.append(final)
                rows.append({"product": name, "backdrop": choice["backdrop"], "flaw": flaw, "first": first,
                             "attempts": len(tries), "final": final["outcome"],
                             "codes": [t.get("code") for t in tries if t.get("code")]})
                print(f"{name:20s} {choice['backdrop']:10s} {flaw:12s} first={first['outcome']:12s} "
                      f"{first.get('code') or first.get('iou')}  final={final['outcome']} after {len(tries)}", flush=True)
    total = len(rows)
    summary = {
        "cases": total,
        "first_try_pass": sum(r["first"]["outcome"] == "pass" for r in rows),
        "first_try_safe_failure": sum(r["first"]["outcome"] == "safe_failure" for r in rows),
        "silent_bad_first": sum(r["first"]["outcome"] == "silent_bad" for r in rows),
        "pass_within_3": sum(r["final"] == "pass" for r in rows),
        "silent_bad_final": sum(r["final"] == "silent_bad" for r in rows),
        "always_white": args.always_white,
    }
    summary["first_try_pass_rate"] = round(summary["first_try_pass"] / total, 3)
    summary["pass_within_3_rate"] = round(summary["pass_within_3"] / total, 3)
    print(json.dumps(summary, indent=1))
    if args.out:
        Path(args.out).write_text(json.dumps({"summary": summary, "rows": rows}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
