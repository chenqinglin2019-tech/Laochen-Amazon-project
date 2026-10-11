"""Main image (V8): an exact RGB(255,255,255) packshot, white by construction.

Whatever background the source has (a real photo or a model result), the product is
cut out locally and placed on a canvas that starts as pure 255 white; pixels outside
the product are never written, so the background is exactly 255 whenever the cutout
succeeds. Everything here therefore aims at a cutout that cannot silently fail:

- the source backdrop is modelled as a smooth surface (vignettes/gradients allowed),
  background = backdrop-coloured pixels connected to the border (plus enclosed holes);
- soft shadows are removed only when guards prove they are shadows (never the product);
- edge pixels are de-contaminated (backdrop colour removed) so no grey/colour halo;
- for generated mains the backdrop colour is chosen to contrast with the product
  (`choose_backdrop`): white/light products are shot on grey, dark ones on white;
- failures return a code that maps to a targeted automatic redo (`REDO_HINTS`).

`verify_jpeg` proves the result on the decoded file: every 8x8 JPEG block that does
not touch the product must be exactly (255, 255, 255). Pillow + NumPy only.
"""
from __future__ import annotations

import math
from pathlib import Path

FILL = 0.85                 # product longer side / canvas side (Amazon: >= 85%)
WORK_MAX = 1400             # analysis resolution (long side)
PLAIN_SPREAD = 14.0         # p90 backdrop residual allowed (0..255 RGB distance)
PHOTO_MAX_UPSCALE = 1.75
GENERATED_MAX_UPSCALE = 2.8
EDGE_MARGIN = 2             # px at work resolution: product touching the frame
ALPHA_FLOOR = 0.06
LOW_CONTRAST_OUTLINE = 0.25  # generated mains: share of the outline allowed to be faint

# Backdrops a generated main may be shot on (all neutral: coloured backdrops tint glossy products).
BACKDROPS = {"white": (255, 255, 255), "light_grey": (200, 200, 200), "mid_grey": (140, 140, 140)}
BACKDROP_HEX = {"white": "#FFFFFF", "light_grey": "#C8C8C8", "mid_grey": "#8C8C8C"}

REDO_HINTS = {
    "MAIN_BACKGROUND_NOT_PLAIN": "the backdrop was not one flat colour: make it perfectly flat and uniform edge to edge "
                                 "(no gradient, vignette, floor line, horizon, texture or props)",
    "MAIN_SHADOW_AMBIGUOUS": "there was a shadow or reflection under/around the product: use shadowless light-tent "
                             "lighting; no contact shadow, drop shadow or reflection at all; the product floats",
    "MAIN_PRODUCT_CROPPED": "the product touched or crossed the frame edge: show the whole product with clear space "
                            "on every side, filling about 75-80% of the frame",
    "MAIN_PRODUCT_TOO_SMALL": "the product was too small in the frame: make it fill about 75-80% of the frame",
    "MAIN_CUTOUT_INCOMPLETE": "parts of the product blended into the backdrop: use the stated contrasting backdrop "
                              "colour and keep every part of the product clearly distinct from it",
    "MAIN_NO_PRODUCT": "no product was found: show exactly one complete product in the centre",
}


class MainError(ValueError):
    def __init__(self, code, message, **info):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.info = info


# ---------------------------------------------------------------- image input

def open_normalized(path):
    """RGB in sRGB (EXIF orientation applied) plus the alpha channel when it is meaningful."""
    from PIL import Image, ImageOps
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened)
        image.load()
    icc = image.info.get("icc_profile")
    if icc:
        try:
            import io
            from PIL import ImageCms
            source = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            target = ImageCms.createProfile("sRGB")
            mode = "RGBA" if image.mode in {"RGBA", "LA", "PA"} else "RGB"
            image = ImageCms.profileToProfile(image.convert(mode), source, target, outputMode=mode)
        except Exception:  # noqa: BLE001 - an unreadable profile: treat as sRGB
            pass
    alpha = None
    if image.mode in {"RGBA", "LA", "PA"} or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        channel = rgba.getchannel("A")
        low, high = channel.getextrema()
        if low < 250 and high > 5:
            alpha = channel
        image = rgba
    return image.convert("RGB"), alpha


# ---------------------------------------------------------------- mask helpers (no SciPy)

def label(mask):
    """4-connected component labels (int32, 0 = background) and the count.

    Run-length union-find: horizontal runs are found with NumPy, runs overlapping in
    neighbouring rows are united (pure Python over runs, not pixels), and labels are
    painted back with a cumulative sum. Exact, no SciPy; Pillow's flood fill is Python
    per pixel and far too slow for 4000 px photos."""
    import numpy as np
    mask = np.ascontiguousarray(mask, dtype=bool)
    height, width = mask.shape
    padded = np.zeros((height, width + 2), np.int8)
    padded[:, 1:-1] = mask
    delta = np.diff(padded, axis=1)
    start_rows, start_cols = np.nonzero(delta == 1)
    end_rows, end_cols = np.nonzero(delta == -1)
    count = len(start_rows)
    if count == 0:
        return np.zeros((height, width), np.int32), 0
    starts, ends = start_cols.tolist(), end_cols.tolist()
    parent = list(range(count))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    first = np.searchsorted(start_rows, np.arange(height + 1)).tolist()
    for y in range(height - 1):
        i, i_end, j, j_end = first[y], first[y + 1], first[y + 1], first[y + 2]
        while i < i_end and j < j_end:
            if starts[i] < ends[j] and starts[j] < ends[i]:
                a, b = find(i), find(j)
                if a != b:
                    if a < b:
                        parent[b] = a
                    else:
                        parent[a] = b
            if ends[i] <= ends[j]:
                i += 1
            else:
                j += 1
    roots = np.fromiter((find(i) for i in range(count)), dtype=np.int64, count=count)
    _, ids = np.unique(roots, return_inverse=True)
    ids = ids.astype(np.int64) + 1
    paint = np.zeros((height, width + 1), np.int64)
    np.add.at(paint, (start_rows, start_cols), ids)
    np.add.at(paint, (end_rows, end_cols), -ids)
    labels = np.cumsum(paint, axis=1)[:, :width].astype(np.int32)
    return labels, int(ids.max())


def connected_to_border(candidate):
    """Pixels of `candidate` 4-connected to the image border."""
    import numpy as np
    labels, count = label(candidate)
    if not count:
        return np.zeros_like(candidate, dtype=bool)
    edge = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    edge = edge[edge > 0]
    return np.isin(labels, edge)


def components(mask, min_area=1, limit=200):
    """Connected components (4-connectivity) largest first: [(area, region_bool, bbox)]."""
    import numpy as np
    labels, count = label(mask)
    if not count:
        return []
    areas = np.bincount(labels.ravel(), minlength=count + 1)
    areas[0] = 0
    found = []
    for value in np.argsort(-areas)[:limit]:
        area = int(areas[value])
        if area < min_area or value == 0:
            break
        region = labels == value
        ys, xs = np.nonzero(region)
        found.append((area, region, (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)))
    return found


def keep_parts(mask, min_area, relative):
    """Union of components with area >= min_area and >= relative x largest; (mask, count, largest)."""
    import numpy as np
    labels, count = label(mask)
    if not count:
        return np.zeros_like(mask, dtype=bool), 0, 0
    areas = np.bincount(labels.ravel(), minlength=count + 1)
    areas[0] = 0
    largest = int(areas.max())
    keep = np.nonzero((areas >= max(min_area, relative * largest)) & (areas > 0))[0]
    return np.isin(labels, keep), int(len(keep)), largest


def _morph(mask, size, op):
    import numpy as np
    from PIL import Image, ImageFilter
    image = Image.fromarray(mask.astype(np.uint8) * 255, "L")
    image = image.filter(ImageFilter.MinFilter(size) if op == "erode" else ImageFilter.MaxFilter(size))
    return np.asarray(image) > 127


def _open(mask, size=3):
    return _morph(_morph(mask, size, "erode"), size, "dilate")


def _despeckle(mask):
    """Drop pixels with fewer than 2 of 8 neighbours set (keeps 1 px lines, removes specks)."""
    import numpy as np
    padded = np.pad(mask, 1).astype(np.uint8)
    neighbours = sum(padded[1 + dy:padded.shape[0] - 1 + dy, 1 + dx:padded.shape[1] - 1 + dx]
                     for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx)
    return mask & (neighbours >= 2)


def _bbox(mask):
    import numpy as np
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


# ---------------------------------------------------------------- backdrop model

def _grid(height, width):
    import numpy as np
    u = (np.arange(width, dtype=np.float32) / max(1, width - 1) - 0.5)[None, :]
    v = (np.arange(height, dtype=np.float32) / max(1, height - 1) - 0.5)[:, None]
    return u, v


def fit_backdrop(array):
    """Quadratic colour surface fitted to the outer ring (robust). Returns (surface, stats)."""
    import numpy as np
    height, width, _ = array.shape
    ring = max(4, int(round(0.03 * min(height, width))))
    mask = np.zeros((height, width), bool)
    mask[:ring, :] = mask[-ring:, :] = True
    mask[:, :ring] = mask[:, -ring:] = True
    ys, xs = np.nonzero(mask)
    step = max(1, len(xs) // 24000)
    ys, xs = ys[::step], xs[::step]
    u = xs / max(1, width - 1) - 0.5
    v = ys / max(1, height - 1) - 0.5
    design = np.stack([np.ones_like(u), u, v, u * u, u * v, v * v], axis=1).astype(np.float64)
    values = array[ys, xs].astype(np.float64)
    # Robust start: distance to the ring's median colour drops product parts that reach the
    # border before any surface is fitted (they would otherwise bend the fit).
    first = np.linalg.norm(values - np.median(values, axis=0), axis=1)
    keep = first <= max(30.0, 3.0 * float(np.median(first)))
    if keep.sum() < 50:
        keep = np.ones(len(u), bool)
    for _ in range(4):
        solution = np.linalg.lstsq(design[keep], values[keep], rcond=None)[0]
        residual = np.linalg.norm(values - design @ solution, axis=1)
        mad = float(np.median(residual[keep])) + 1e-6
        keep = residual <= max(4.0, 3.5 * 1.4826 * mad)
    spread = float(np.percentile(residual[keep], 90)) if keep.any() else 255.0
    gu, gv = _grid(height, width)
    surface = np.empty((height, width, 3), np.float32)
    for channel in range(3):
        a = solution[:, channel]
        surface[..., channel] = a[0] + a[1] * gu + a[2] * gv + a[3] * gu * gu + a[4] * gu * gv + a[5] * gv * gv
    np.clip(surface, 0, 255, out=surface)
    mean = values[keep].mean(axis=0) if keep.any() else values.mean(axis=0)
    luminance = float(0.2126 * mean[0] + 0.7152 * mean[1] + 0.0722 * mean[2])
    chroma = float(mean.max() - mean.min())
    return surface, {"spread": round(spread, 2), "outliers": round(float(1 - keep.mean()), 3),
                     "color": [round(float(c), 1) for c in mean], "luminance": round(luminance, 1),
                     "chroma": round(chroma, 1), "solution": solution}


def _surface_at(solution, height, width):
    import numpy as np
    gu, gv = _grid(height, width)
    surface = np.empty((height, width, 3), np.float32)
    for channel in range(3):
        a = solution[:, channel]
        surface[..., channel] = a[0] + a[1] * gu + a[2] * gv + a[3] * gu * gu + a[4] * gu * gv + a[5] * gv * gv
    return np.clip(surface, 0, 255)


# ---------------------------------------------------------------- cutout

def cutout(image, *, alpha=None, light_product=False, strict_outline=False, analysis_only=False):
    """Product alpha matte at full resolution plus diagnostics, or MainError.

    `alpha`: an existing transparency channel (already cut-out PNG) is trusted as is."""
    import numpy as np
    from PIL import Image, ImageFilter
    width, height = image.size
    if alpha is not None:
        matte = np.asarray(alpha, dtype=np.float32) / 255.0
        info = {"method": "embedded_alpha", "shadow_removed": 0.0, "holes_removed": 0}
        return _finish_matte(image, matte, None, info)
    scale = min(1.0, WORK_MAX / max(width, height))
    work = image if scale == 1.0 else image.resize((max(1, round(width * scale)), max(1, round(height * scale))),
                                                   Image.Resampling.BOX)
    array = np.asarray(work, dtype=np.float32)
    h, w, _ = array.shape
    surface, stats = fit_backdrop(array)
    if stats["spread"] > PLAIN_SPREAD:
        raise MainError("MAIN_BACKGROUND_NOT_PLAIN", f"backdrop varies too much (p90 residual {stats['spread']})",
                        backdrop=_public(stats))
    distance = np.linalg.norm(array - surface, axis=2)
    # Many separate non-backdrop runs along the outer edge = a busy scene, not a product that
    # happens to reach one edge (that gives one or two runs).
    border = np.concatenate([distance[0, :], distance[:, -1], distance[-1, ::-1], distance[::-1, 0]]) >= 30.0
    runs = int(np.count_nonzero(border[1:] & ~border[:-1])) + int(border[0] and not border[-1])
    if runs > 6:
        raise MainError("MAIN_BACKGROUND_NOT_PLAIN", f"the frame edge crosses {runs} separate objects or textures",
                        backdrop=_public(stats))
    tolerance = float(min(28.0, max(10.0, 3.0 * stats["spread"] + 8.0)))
    candidate = distance < tolerance
    background = connected_to_border(candidate)
    foreground = ~background
    if foreground.sum() < 0.002 * h * w:
        raise MainError("MAIN_NO_PRODUCT", "no product separated from the backdrop", backdrop=_public(stats))
    info = {"method": "backdrop_surface", "backdrop": _public(stats), "tolerance": round(tolerance, 1)}
    # Guarded shadow removal: neutral, smooth, darker-than-backdrop regions grown from the backdrop.
    luminance = 0.2126 * array[..., 0] + 0.7152 * array[..., 1] + 0.0722 * array[..., 2]
    chroma = array.max(axis=2) - array.min(axis=2)
    backdrop_luminance = 0.2126 * surface[..., 0] + 0.7152 * surface[..., 1] + 0.0722 * surface[..., 2]
    blurred = np.asarray(Image.fromarray(np.clip(luminance, 0, 255).astype(np.uint8), "L")
                         .filter(ImageFilter.GaussianBlur(1.5)), dtype=np.float32)
    gy, gx = np.gradient(blurred)
    gradient = np.hypot(gx, gy)
    neutral_backdrop = stats["chroma"] <= 18
    shadowish = ((chroma <= 16) & (luminance >= np.maximum(45.0, 0.40 * backdrop_luminance))
                 & (luminance < backdrop_luminance - 2.0))
    removed = np.zeros_like(foreground)
    info.update(shadow_removed=0.0)
    before = _bbox(foreground)
    fg_area = float(foreground.sum())
    if neutral_backdrop and (shadowish & foreground).any():
        strong = connected_to_border(background | (shadowish & foreground & (gradient <= 3.0)))
        grown = connected_to_border(strong | (shadowish & foreground & (gradient <= 6.0)))
        candidate_removed = grown & ~background
        product = ~grown
        after = _bbox(product)
        if candidate_removed.any() and after is not None:
            top, bottom = before[1], before[3]
            cut = top + 0.55 * (bottom - top)
            ys = np.nonzero(candidate_removed)[0]
            g1 = candidate_removed.sum() <= 0.30 * fg_area
            g2 = float((ys >= cut).mean()) >= 0.85 or after[3] <= cut
            g3 = (after[3] - after[1]) >= 0.6 * (bottom - top)
            if g1 and g2 and g3:
                background, foreground, removed = grown, product, candidate_removed
                info["shadow_removed"] = round(float(removed.sum()) / fg_area, 4)
            else:
                # The growth leaked into a neutral product: keep everything; a real shadow left
                # under the product is caught by the attached-shadow check below.
                info["shadow_guard"] = "kept_product"
    # A hard-edged shadow cannot be grown into; detect what is left attached under the product.
    if neutral_backdrop:
        box = _bbox(foreground)
        if box is not None:
            residual = foreground & shadowish & (gradient <= 6.0) & (luminance <= 0.92 * backdrop_luminance)
            area = float(residual.sum())
            if area > 0.03 * float(foreground.sum()):
                cut = box[1] + 0.55 * (box[3] - box[1])
                ys = np.nonzero(residual)[0]
                low = float((ys >= cut).mean())
                if low >= 0.85:
                    raise MainError("MAIN_SHADOW_AMBIGUOUS", "a hard shadow remains attached under the product",
                                    residual=round(area / float(foreground.sum()), 3), **info)
    # A flat, uniform shadow region sitting at the bottom of the silhouette (hard shadow on a
    # neutral product, where colour alone cannot tell product from shadow).
    if neutral_backdrop:
        hard = _uniform_bottom_shadow(work, array, foreground, background, luminance, backdrop_luminance,
                                      shadowish & (gradient <= 6.0))
        if hard:
            raise MainError("MAIN_SHADOW_AMBIGUOUS", "a flat shadow sits under the product", shadow=hard, **info)
    # Background visible through holes (handles, rings): enclosed, strongly backdrop-like, uniform.
    holes_removed = 0
    if not light_product:
        enclosed = _despeckle(candidate & foreground & (distance < 0.6 * tolerance))
        minimum = max(40, int(0.0004 * h * w))
        for area, region, _ in components(enclosed, min_area=minimum, limit=120):
            if float(distance[region].mean()) <= 0.5 * tolerance and float(distance[region].std()) <= 0.35 * tolerance:
                background |= region
                foreground &= ~region
                holes_removed += 1
    info["holes_removed"] = holes_removed
    # Isolated noise goes; every real product part (also small separate pieces) stays.
    foreground = _despeckle(foreground)
    foreground, part_count, largest = keep_parts(foreground, max(12, int(0.0002 * h * w)), 0.004)
    if not part_count:
        raise MainError("MAIN_NO_PRODUCT", "no product separated from the backdrop", **info)
    info["parts"] = part_count
    box = _bbox(foreground)
    if box[0] <= EDGE_MARGIN or box[1] <= EDGE_MARGIN or box[2] >= w - EDGE_MARGIN or box[3] >= h - EDGE_MARGIN:
        raise MainError("MAIN_PRODUCT_CROPPED", "the product touches the frame edge", bbox_norm=_norm(box, w, h), **info)
    # Completeness: faint non-backdrop pixels reaching beyond the cut-out (sides/top) mean
    # product parts were taken for backdrop (shadows only extend below and are excluded).
    strict = (distance >= max(6.0, 2.5 * stats["spread"])) & ~removed & ~(shadowish & (gradient <= 6.0))
    pad_x, pad_y = int(0.15 * w), int(0.15 * h)
    window = np.zeros_like(strict)
    window[max(0, box[1] - pad_y):min(h, box[3] + pad_y), max(0, box[0] - pad_x):min(w, box[2] + pad_x)] = True
    strict = _open(strict & window, 3)
    reach = None
    for area, region, part_box in components(strict, min_area=max(60, int(0.0003 * h * w)), limit=120):
        reach = part_box if reach is None else (min(reach[0], part_box[0]), min(reach[1], part_box[1]),
                                                max(reach[2], part_box[2]), max(reach[3], part_box[3]))
    gap = 0.0
    if reach is not None:
        gap = max((box[0] - reach[0]) / w, (reach[2] - box[2]) / w, (box[1] - reach[1]) / h, 0.0)
    info["extent_gap"] = round(float(gap), 4)
    if gap > 0.04:
        raise MainError("MAIN_CUTOUT_INCOMPLETE", "parts of the product look like the backdrop", **info)
    # How much of the outline runs through low-contrast pixels: product parts taken for backdrop
    # (or a soft shadow left behind) leave a faint outline; a clean cut-out has a crisp one.
    outline = foreground & ~_morph(foreground, 3, "erode")
    info["light_edge"] = round(float((distance[outline] < 2.0 * tolerance).mean()) if outline.any() else 0.0, 3)
    inner = _morph(foreground, 3, "erode") & ~_morph(foreground, 7, "erode")   # 1-3 px inside (no JPEG ringing)
    info["faint_outline"] = round(float((distance[inner] < 2.0 * tolerance).mean()) if inner.any() else 0.0, 3)
    if strict_outline and info["faint_outline"] > LOW_CONTRAST_OUTLINE:
        raise MainError("MAIN_CUTOUT_INCOMPLETE", "the product outline fades into the backdrop", **info)
    if analysis_only:
        # Eligibility checks need only the product box (in full-resolution pixels).
        box = _bbox(foreground)
        info["bbox"] = [round(box[0] / scale), round(box[1] / scale), round(box[2] / scale), round(box[3] / scale)]
        return None, None, info
    # Soft matte at work resolution: hard mask -> slight feather -> upsample.
    hard = Image.fromarray(foreground.astype(np.uint8) * 255, "L").filter(ImageFilter.GaussianBlur(0.7))
    if scale != 1.0:
        hard = hard.resize((width, height), Image.Resampling.BILINEAR)
    matte = np.asarray(hard, dtype=np.float32) / 255.0
    full_surface = _surface_at(stats["solution"], height, width) if scale != 1.0 else surface
    return _finish_matte(image, matte, full_surface, info)


def _uniform_bottom_shadow(work, array, foreground, background, luminance, backdrop_luminance, smooth_shadowish):
    """Find a uniform, shadow-toned region in the lowest part of the silhouette touching the backdrop."""
    import numpy as np
    box = _bbox(foreground)
    if box is None:
        return None
    height = box[3] - box[1]
    fg_area = float(foreground.sum())
    ratio = luminance / np.maximum(backdrop_luminance, 1.0)
    seeds = smooth_shadowish & foreground & (ratio >= 0.5) & (ratio <= 0.92)
    seeds[:box[1] + int(0.72 * height), :] = False
    ys, xs = np.nonzero(seeds)
    if not len(xs):
        return None
    edge = _morph(background, 3, "dilate") & foreground          # silhouette pixels next to the backdrop
    order = np.argsort(xs)
    picks = order[np.linspace(0, len(order) - 1, num=min(9, len(order))).astype(int)]
    covered = np.zeros_like(foreground)
    for index in picks:
        x, y = int(xs[index]), int(ys[index])
        if covered[y, x]:
            continue
        similar = (np.abs(array - array[y, x]).max(axis=2) <= 8.0) & foreground
        labels, _ = label(similar)
        region = labels == labels[y, x]
        covered |= region
        area = float(region.sum())
        if area < 0.01 * fg_area:
            continue
        rys = np.nonzero(region)[0]
        below = float((rys >= box[1] + 0.6 * height).mean())
        uniform = float(luminance[region].std())
        touching = float((region & edge).sum()) / max(1.0, float(region.sum()) ** 0.5)
        if below >= 0.9 and uniform <= 6.0 and touching >= 2.0:
            return {"area": round(area / fg_area, 3), "below": round(below, 3), "std": round(uniform, 2)}
    return None


def _finish_matte(image, matte, surface, info):
    """De-contaminate edge colours (remove backdrop spill) and clean the matte."""
    import numpy as np
    from PIL import Image
    rgb = np.asarray(image, dtype=np.float32)
    matte = np.where(matte < ALPHA_FLOOR, 0.0, matte)
    matte = np.where(matte > 0.985, 1.0, matte)
    if surface is not None:
        edge = (matte > 0) & (matte < 1)
        if edge.any():
            a = matte[edge][:, None]
            rgb[edge] = np.clip((rgb[edge] - (1.0 - a) * surface[edge]) / a, 0, 255)
    foreground = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")
    alpha = Image.fromarray(np.clip(matte * 255.0 + 0.5, 0, 255).astype(np.uint8), "L")
    box = alpha.point(lambda value: 255 if value > 10 else 0).getbbox()
    if box is None:
        raise MainError("MAIN_NO_PRODUCT", "empty product matte", **info)
    info["bbox"] = list(box)
    return foreground, alpha, info


def _public(stats):
    return {key: value for key, value in stats.items() if key != "solution"}


def _norm(box, width, height):
    return [round(box[0] / width, 4), round(box[1] / height, 4), round((box[2] - box[0]) / width, 4),
            round((box[3] - box[1]) / height, 4)]


# ---------------------------------------------------------------- composite + verification

def compose(foreground, alpha, canvas=(2000, 2000), *, fill=FILL, max_upscale=None, sharpen=False):
    """Product centred on an exact-255 canvas; pixels outside the matte are never written."""
    import numpy as np
    from PIL import Image, ImageFilter
    box = alpha.point(lambda value: 255 if value > 10 else 0).getbbox()
    width, height = canvas
    crop_w, crop_h = box[2] - box[0], box[3] - box[1]
    scale = min(fill * width / crop_w, fill * height / crop_h)
    if max_upscale is not None and scale > max_upscale:
        raise MainError("MAIN_PRODUCT_TOO_SMALL", f"the product would need {scale:.2f}x upscaling (max {max_upscale})",
                        upscale=round(scale, 3))
    size = (max(1, round(crop_w * scale)), max(1, round(crop_h * scale)))
    product = foreground.crop(box).resize(size, Image.Resampling.LANCZOS)
    if sharpen and scale > 1.3:
        product = product.filter(ImageFilter.UnsharpMask(radius=1.2, percent=45, threshold=2))
    matte = alpha.crop(box).resize(size, Image.Resampling.LANCZOS)
    left, top = (width - size[0]) // 2, (height - size[1]) // 2
    out = np.full((height, width, 3), 255.0, np.float32)
    a = np.asarray(matte, dtype=np.float32)[..., None] / 255.0
    a = np.where(a < ALPHA_FLOOR, 0.0, a)
    region = out[top:top + size[1], left:left + size[0]]
    out[top:top + size[1], left:left + size[0]] = np.asarray(product, dtype=np.float32) * a + region * (1.0 - a)
    placed = np.zeros((height, width), bool)
    placed[top:top + size[1], left:left + size[0]] = a[..., 0] > 0
    result = Image.fromarray(np.clip(out + 0.5, 0, 255).astype(np.uint8), "RGB")
    info = {"scale": round(scale, 4), "placed_bbox": [left, top, left + size[0], top + size[1]],
            "fill": round(max(size[0] / width, size[1] / height), 4)}
    return result, placed, info


def verify_jpeg(path, placed, *, fill=FILL):
    """Every 8x8 block without product pixels must decode to exactly (255,255,255)."""
    import numpy as np
    from PIL import Image, ImageFilter
    with Image.open(path) as image:
        array = np.asarray(image.convert("RGB"))
    height, width = placed.shape
    reasons = []
    if array.shape[:2] != (height, width):
        return {"ok": False, "reasons": ["size mismatch"]}
    grown = np.asarray(Image.fromarray(placed.astype(np.uint8) * 255, "L").filter(ImageFilter.MaxFilter(3))) > 0
    bh, bw = math.ceil(height / 8), math.ceil(width / 8)
    pad_fg = np.zeros((bh * 8, bw * 8), bool)
    pad_fg[:height, :width] = grown
    pad_white = np.ones((bh * 8, bw * 8), bool)
    pad_white[:height, :width] = (array == 255).all(axis=2)
    block_fg = pad_fg.reshape(bh, 8, bw, 8).any(axis=(1, 3))
    block_white = pad_white.reshape(bh, 8, bw, 8).all(axis=(1, 3))
    bad = int((~block_fg & ~block_white).sum())
    if bad:
        reasons.append(f"{bad} background blocks are not exactly 255")
    border = np.concatenate([array[0], array[-1], array[:, 0], array[:, -1]])
    if not (border == 255).all():
        reasons.append("border pixels are not exactly 255")
    box = _bbox(placed)
    product_fill = max((box[2] - box[0]) / width, (box[3] - box[1]) / height) if box else 0.0
    if box is None or abs(product_fill - fill) > 0.012:
        reasons.append(f"product fill {product_fill:.3f} is not {fill:.2f}")
    if box is not None:
        cx, cy = (box[0] + box[2]) / 2 / width, (box[1] + box[3]) / 2 / height
        if abs(cx - 0.5) > 0.01 or abs(cy - 0.5) > 0.01:
            reasons.append("product is not centred")
    edge_values = array[pad_fg[:height, :width] & ~placed]
    return {"ok": not reasons, "reasons": reasons, "background_blocks_bad": bad,
            "white_fraction": round(float((array == 255).all(axis=2).mean()), 4),
            "fill": round(product_fill, 4), "edge_min": int(edge_values.min()) if edge_values.size else 255}


def export(image, placed, path, *, quality=95):
    """JPEG q95 4:4:4, proven on the decoded file; q100, then lossless PNG as fallbacks."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    attempts = []
    for q in (quality, 100):
        temporary = path.with_name(f".{path.stem}.tmp.jpg")
        image.save(temporary, format="JPEG", quality=q, subsampling=0, optimize=True)
        report = verify_jpeg(temporary, placed)
        attempts.append({"format": "jpeg", "quality": q, "ok": report["ok"]})
        if report["ok"]:
            import lc_fsretry
            lc_fsretry.replace(temporary, path)
            return {"path": str(path), "format": "jpeg", "quality": q, "verify": report, "attempts": attempts}
        temporary.unlink(missing_ok=True)
    png = path.with_suffix(".png")
    image.save(png, format="PNG", optimize=True)
    report = verify_jpeg(png, placed)
    attempts.append({"format": "png", "ok": report["ok"]})
    if not report["ok"]:
        raise MainError("MAIN_VERIFY_FAILED", "; ".join(report["reasons"]), verify=report)
    return {"path": str(png), "format": "png", "verify": report, "attempts": attempts}


# ---------------------------------------------------------------- routes

def product_colours(image, alpha=None, sample=60000):
    """Product pixel colours from a photo (cut out when the background is plain, else its centre)."""
    import numpy as np
    try:
        foreground, matte, _ = cutout(image, alpha=alpha)
        rgb = np.asarray(foreground, dtype=np.float32).reshape(-1, 3)
        weights = np.asarray(matte, dtype=np.float32).reshape(-1)
        pixels = rgb[weights > 200]
        source = "cutout"
    except MainError:
        width, height = image.size
        centre = image.crop((width // 4, height // 4, width * 3 // 4, height * 3 // 4))
        pixels = np.asarray(centre, dtype=np.float32).reshape(-1, 3)
        source = "centre"
    if len(pixels) > sample:
        pixels = pixels[:: max(1, len(pixels) // sample)]
    return pixels, source


def _confusable(values, colour):
    """Fraction of product colours that would look like a shadow on this backdrop."""
    import numpy as np
    luminance = values @ np.asarray([0.2126, 0.7152, 0.0722], np.float32)
    chroma = values.max(axis=1) - values.min(axis=1)
    backdrop = 0.2126 * colour[0] + 0.7152 * colour[1] + 0.0722 * colour[2]
    return float(((chroma <= 16) & (luminance >= max(45.0, 0.40 * backdrop)) & (luminance < backdrop - 2.0)).mean())


def choose_backdrop(photos, *, transparent=False):
    """Neutral backdrop that keeps the product separable and never shadow-like.

    For each candidate: separation = 5th percentile colour distance product<->backdrop,
    confusable = share of product colours that look like a shadow on it. White wins
    unless another backdrop is clearly safer. Transparent products always use white
    (whatever shows through must already be white)."""
    import numpy as np
    if transparent:
        return {"backdrop": "white", "hex": BACKDROP_HEX["white"], "reason": "transparent product"}
    pixels, sources = [], []
    for image, alpha in photos:
        values, source = product_colours(image, alpha)
        if len(values):
            pixels.append(values)
            sources.append(source)
    if not pixels:
        return {"backdrop": "white", "hex": BACKDROP_HEX["white"], "reason": "no product colours measured"}
    values = np.concatenate(pixels)
    rows = {}
    for name, colour in BACKDROPS.items():
        distance = np.linalg.norm(values - np.asarray(colour, np.float32), axis=1)
        rows[name] = {"separation": round(float(np.percentile(distance, 5)), 1),
                      "confusable": round(_confusable(values, colour), 3)}

    def risk(name):
        # Poor separation breaks the cut-out itself; shadow-like product colours only matter
        # when a shadow is present (guarded), so separation weighs more.
        row = rows[name]
        return (0.6 * row["confusable"] + (0.8 if row["separation"] < 25 else 0.0) + (0.2 if row["separation"] < 45 else 0.0))
    choice = "white"
    best = min(rows, key=lambda name: (round(risk(name), 3), -rows[name]["separation"]))
    if risk(best) + 0.10 < risk("white"):
        choice = best
    luminance = values @ np.asarray([0.2126, 0.7152, 0.0722], np.float32)
    return {"backdrop": choice, "hex": BACKDROP_HEX[choice], "candidates": rows,
            "light_fraction": round(float((luminance >= 200).mean()), 3), "measured_from": sources}


def photo_candidate(path, canvas=(2000, 2000)):
    """Can this real photo become the main image locally? (any plain backdrop or embedded alpha)."""
    try:
        image, alpha = open_normalized(path)
        if alpha is not None:
            foreground, matte, info = cutout(image, alpha=alpha)
        else:
            foreground, matte, info = cutout(image, analysis_only=True)
    except MainError as exc:
        return {"eligible": False, "reasons": [exc.code], "detail": str(exc)}
    except OSError as exc:
        return {"eligible": False, "reasons": ["UNREADABLE"], "detail": str(exc)}
    box = info["bbox"]
    crop_w, crop_h = box[2] - box[0], box[3] - box[1]
    upscale = min(FILL * canvas[0] / crop_w, FILL * canvas[1] / crop_h)
    reasons = []
    if upscale > PHOTO_MAX_UPSCALE:
        reasons.append("MAIN_PHOTO_RESOLUTION")
    return {"eligible": not reasons, "reasons": reasons, "upscale": round(upscale, 3), "method": info.get("method"),
            "shadow_removed": info.get("shadow_removed", 0.0), "light_edge": info.get("light_edge", 0.0),
            "product_px": [crop_w, crop_h]}


def build_from_photo(path, out_path, canvas=(2000, 2000)):
    image, alpha = open_normalized(path)
    foreground, matte, info = cutout(image, alpha=alpha)
    result, placed, placement = compose(foreground, matte, canvas, max_upscale=PHOTO_MAX_UPSCALE)
    exported = export(result, placed, out_path)
    check = bool(info.get("shadow_removed", 0) > 0.03 or info.get("light_edge", 0) > 0.35)
    return {"route": "photo", "cutout": info, "placement": placement, "check_suggested": check, **exported}


def build_from_generated(path, out_path, canvas=(2000, 2000), *, light_product=False):
    image, alpha = open_normalized(path)
    foreground, matte, info = cutout(image, alpha=alpha, light_product=light_product, strict_outline=True)
    result, placed, placement = compose(foreground, matte, canvas, max_upscale=GENERATED_MAX_UPSCALE, sharpen=True)
    exported = export(result, placed, out_path)
    check = bool(info.get("shadow_removed", 0) > 0.03 or info.get("light_edge", 0) > 0.35 or info.get("holes_removed"))
    return {"route": "generated", "cutout": info, "placement": placement, "check_suggested": check, **exported}
