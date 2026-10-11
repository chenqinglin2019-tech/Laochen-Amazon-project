"""Reference neutralization: style plates, tone boards and hidden regions.

- make_plate (intake): the reference without its product, text, logos and people.
  Text/logo boxes (expanded 12%) are filled with the surrounding colour and blurred;
  the product box (6%) and person boxes (8%) are flattened by interpolating their
  surroundings; an edge-energy gate rejects plates where letters or silhouettes
  survive. Plates stay in the user library and never reach the image model as they are.
- make_tone_board (V8.1): the only form in which a reference reaches the image model.
  A robust low-order fit of the image's colour and light field: local patches that
  differ from their surroundings (people, products, props, text) are dropped as
  outliers and refitted away, so only the overall tone, brightness and light direction
  remain - even for older plates or raw references that still show a person.
- main_colours: the dominant colours as hex, given to the model as words.
- hide_regions: blur out people or unrelated items in a product photo.
Deterministic (no randomness); Pillow + NumPy.
"""
from __future__ import annotations

PLATE_LONG_EDGE = 1536
THUMB_LONG_EDGE = 768
TONE_GRID = 48            # analysis cells on the long edge
TONE_LONG_EDGE = 512
TONE_KEEP = 0.6           # share of best-fitting cells kept per refit (the rest are objects/people/text)
TONE_VERSION = 2


def _pixels(box, size, expand):
    width, height = size
    x, y, w, h = box
    grow_w, grow_h = w * expand, h * expand
    left = max(0, int((x - grow_w / 2) * width))
    top = max(0, int((y - grow_h / 2) * height))
    right = min(width, int((x + w + grow_w / 2) * width + 0.999))
    bottom = min(height, int((y + h + grow_h / 2) * height + 0.999))
    return left, top, right, bottom


def _ring(array, box, width):
    import numpy as np
    left, top, right, bottom = box
    h, w = array.shape[:2]
    outer = (max(0, left - width), max(0, top - width), min(w, right + width), min(h, bottom + width))
    region = array[outer[1]:outer[3], outer[0]:outer[2]].reshape(-1, array.shape[2]).astype("float32")
    mask = np.ones((outer[3] - outer[1], outer[2] - outer[0]), dtype=bool)
    mask[top - outer[1]:bottom - outer[1], left - outer[0]:right - outer[0]] = False
    ring = region[mask.ravel()]
    return ring if ring.size else region


def _edge_energy(image, box):
    import numpy as np
    from PIL import ImageFilter
    left, top, right, bottom = box
    crop = image.crop((left, top, right, bottom)).convert("L").filter(ImageFilter.FIND_EDGES)
    values = np.asarray(crop, dtype="float32")
    return float(values[1:-1, 1:-1].mean()) if values.shape[0] > 2 and values.shape[1] > 2 else float(values.mean())


def _flatten(array, box):
    """Fill the box by blending its left/right and top/bottom edge colours (no silhouette)."""
    import numpy as np
    left, top, right, bottom = box
    h, w = bottom - top, right - left
    if h < 2 or w < 2:
        return
    pad = 3
    left_col = array[top:bottom, max(0, left - pad):max(1, left)].astype("float32").mean(axis=1)
    right_col = array[top:bottom, right:min(array.shape[1], right + pad)].astype("float32")
    right_col = right_col.mean(axis=1) if right_col.size else left_col
    top_row = array[max(0, top - pad):max(1, top), left:right].astype("float32").mean(axis=0)
    bottom_row = array[bottom:min(array.shape[0], bottom + pad), left:right].astype("float32")
    bottom_row = bottom_row.mean(axis=0) if bottom_row.size else top_row
    fx = np.linspace(0, 1, w, dtype="float32")[None, :, None]
    fy = np.linspace(0, 1, h, dtype="float32")[:, None, None]
    horizontal = left_col[:, None, :] * (1 - fx) + right_col[:, None, :] * fx
    vertical = top_row[None, :, :] * (1 - fy) + bottom_row[None, :, :] * fy
    # Trust the direction whose opposite edges agree: a tabletop/horizon keeps
    # left and right matched row by row, so it carries straight across the box.
    disagree_h = float(np.abs(left_col - right_col).mean())
    disagree_v = float(np.abs(top_row - bottom_row).mean())
    weight_h = 0.5 if disagree_h + disagree_v < 1e-6 else disagree_v / (disagree_h + disagree_v)
    array[top:bottom, left:right] = (horizontal * weight_h + vertical * (1 - weight_h)).clip(0, 255).astype(array.dtype)


def make_plate(image, product_box=None, text_boxes=(), logo_boxes=(), *, person_boxes=(), mode="flatten"):
    """Return (plate, metrics). Raises ValueError when neutralization is insufficient."""
    from PIL import Image
    rgb = image.convert("RGB")
    scale = min(1.0, PLATE_LONG_EDGE / max(rgb.size))
    if scale < 1:
        rgb = rgb.resize((round(rgb.width * scale), round(rgb.height * scale)), Image.Resampling.LANCZOS)
    targets = []
    for kind, boxes, expand in (("text", text_boxes, 0.12), ("logo", logo_boxes, 0.12)):
        for box in boxes or ():
            targets.append((kind, _pixels(box, rgb.size, expand)))
    if product_box:
        targets.append(("product", _pixels(product_box, rgb.size, 0.06)))
    # People are flattened before the product so the product fill never picks up their colours.
    people = [("person", _pixels(box, rgb.size, 0.08)) for box in person_boxes or ()]
    product = [item for item in targets if item[0] == "product"]
    targets = [item for item in targets if item[0] != "product"] + people + product
    return _neutralize(rgb, targets, mode)


def _neutralize(rgb, targets, mode):
    import numpy as np
    from PIL import Image, ImageFilter
    array = np.asarray(rgb).copy()
    before = {index: _edge_energy(rgb, box) for index, (_, box) in enumerate(targets)}
    mask = Image.new("L", rgb.size, 0)
    for kind, box in targets:
        left, top, right, bottom = box
        if right - left < 2 or bottom - top < 2:
            continue
        ring = _ring(array, box, max(4, int(0.06 * max(right - left, bottom - top))))
        fill = np.median(ring, axis=0)
        if kind == "person" or (kind == "product" and mode == "flatten"):
            _flatten(array, box)
        else:
            region = array[top:bottom, left:right].astype("float32")
            array[top:bottom, left:right] = (region * 0.4 + fill * 0.6).clip(0, 255).astype(array.dtype) \
                if kind == "product" else np.broadcast_to(fill, region.shape).astype(array.dtype)
        mask.paste(255, box)
    softened = Image.fromarray(array).filter(ImageFilter.GaussianBlur(max(6, max(rgb.size) // 90)))
    feather = mask.filter(ImageFilter.GaussianBlur(max(3, max(rgb.size) // 200)))
    plate = Image.composite(softened, Image.fromarray(array), feather)
    metrics = []
    for index, (kind, box) in enumerate(targets):
        after = _edge_energy(plate, box)
        ratio = after / before[index] if before[index] > 1e-6 else 0.0
        limit = 0.25 if kind in {"product", "person"} else 0.2
        metrics.append({"kind": kind, "box_px": list(box), "edge_energy_ratio": round(ratio, 4), "limit": limit})
        if ratio > limit:
            raise ValueError(f"{kind} region still shows structure (edge ratio {ratio:.2f} > {limit}); enlarge its box")
    return plate, metrics


def make_thumb(image, long_edge=THUMB_LONG_EDGE):
    from PIL import Image
    thumb = image.convert("RGB")
    scale = min(1.0, long_edge / max(thumb.size))
    if scale < 1:
        thumb = thumb.resize((round(thumb.width * scale), round(thumb.height * scale)), Image.Resampling.LANCZOS)
    return thumb


def _design(u, v):
    import numpy as np
    return np.stack([np.ones_like(u), u, v, u * u, u * v, v * v], axis=-1)


def make_tone_board(image):
    """Overall tone, brightness and light direction of an image, nothing else (see the module doc)."""
    import numpy as np
    from PIL import Image
    rgb = image.convert("RGB")
    width, height = rgb.size
    long_edge = max(width, height)
    cells = (max(4, round(TONE_GRID * width / long_edge)), max(4, round(TONE_GRID * height / long_edge)))
    grid = np.asarray(rgb.resize(cells, Image.Resampling.BOX), dtype=np.float64).reshape(-1, 3)   # area averages
    v, u = np.mgrid[0:cells[1], 0:cells[0]]
    design = _design((u.ravel() + 0.5) / cells[0] * 2 - 1, (v.ravel() + 0.5) / cells[1] * 2 - 1)
    keep = np.ones(len(grid), bool)
    for _ in range(4):                       # robust refit: drop the cells that stand out (objects, people, text)
        coef, *_ = np.linalg.lstsq(design[keep], grid[keep], rcond=None)
        residual = np.linalg.norm(grid - design @ coef, axis=1)
        keep = residual <= np.quantile(residual, TONE_KEEP)
    coef, *_ = np.linalg.lstsq(design[keep], grid[keep], rcond=None)
    size = (max(2, round(TONE_LONG_EDGE * width / long_edge)), max(2, round(TONE_LONG_EDGE * height / long_edge)))
    yy, xx = np.mgrid[0:size[1], 0:size[0]]
    field = _design((xx + 0.5) / size[0] * 2 - 1, (yy + 0.5) / size[1] * 2 - 1) @ coef
    return Image.fromarray(np.clip(np.rint(field), 0, 255).astype(np.uint8), "RGB")


def main_colours(image, count=5, min_share=0.03):
    """Dominant colours as #RRGGBB, largest share first (words for the prompt, no spatial layout)."""
    from PIL import Image
    small = image.convert("RGB").copy()
    small.thumbnail((160, 160))
    quantized = small.quantize(colors=8, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    palette = quantized.getpalette()
    counts = sorted(quantized.getcolors() or [], reverse=True)
    total = float(sum(count_ for count_, _ in counts)) or 1.0
    colours = []
    for share, index in counts:
        if share / total < min_share:
            continue
        rgb = tuple(palette[index * 3:index * 3 + 3])
        if all(sum(abs(a - b) for a, b in zip(rgb, other)) > 36 for other in colours):
            colours.append(rgb)
        if len(colours) == count:
            break
    return ["#%02X%02X%02X" % colour for colour in colours]


def hide_regions(image, boxes, *, expand=0.06):
    """Flatten and blur inside each normalized box; pixels outside the boxes stay unchanged.

    Returns (image, metrics) with the edge-energy ratio left inside each box."""
    from PIL import Image, ImageFilter
    import numpy as np
    rgb = image.convert("RGB")
    array = np.asarray(rgb).copy()
    mask = Image.new("L", rgb.size, 0)
    targets = []
    for box in boxes or ():
        left, top, right, bottom = _pixels(box, rgb.size, expand)
        if right - left < 2 or bottom - top < 2:
            continue
        targets.append((left, top, right, bottom))
        _flatten(array, (left, top, right, bottom))
        mask.paste(255, (left, top, right, bottom))
    softened = Image.fromarray(array).filter(ImageFilter.GaussianBlur(max(4, max(rgb.size) // 120)))
    result = Image.composite(softened, rgb, mask)
    metrics = []
    for box in targets:
        before = _edge_energy(rgb, box)
        metrics.append({"box_px": list(box),
                        "edge_energy_ratio": round(_edge_energy(result, box) / before, 4) if before > 1e-6 else 0.0})
    return result, metrics
