"""One review sheet image and one compact todo per prepared review packet.

The sheet stacks what the reviewer must see (downscaled final layout, the 360 px
preview at true size, every P0/P1 detail comparison and, for template jobs, the
adopted reference thumbnail) so a routine review needs one image view. The todo
holds only the judgments to fill; review-submit merges it back into the bound
packet, so every existing validation still applies. Original-size files remain
available for anything the sheet cannot settle.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

TODO_SCHEMA = "lc-review-todo/1"
FONT = Path(__file__).resolve().parents[1] / "assets/fonts/NotoSans-Regular.ttf"


def _font(size):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(str(FONT), size)
    except OSError:
        return ImageFont.load_default()


def _open(path, max_width):
    from PIL import Image
    with Image.open(path) as image:
        image = image.convert("RGB")
        if image.width > max_width:
            image = image.resize((max_width, round(image.height * max_width / image.width)), Image.Resampling.LANCZOS)
        return image


def build_sheet(base, packet, out_path, reference=None):
    from PIL import Image, ImageDraw
    base = Path(base)
    panels = []
    if packet.get("preview") and (base / packet["preview"]).is_file():
        panels.append(("final layout (downscaled)", _open(base / packet["preview"], 1000), 0))
    right = []
    if packet.get("mobile_preview") and (base / packet["mobile_preview"]).is_file():
        right.append(("360 px preview (true size)", _open(base / packet["mobile_preview"], 360)))
    for item in packet.get("comparisons", []):
        path = base / item["path"]
        if path.is_file():
            right.append((f"detail {item['id']}: evidence | output", _open(path, 840)))
    if reference and Path(reference).is_file():
        right.append(("adopted template reference", _open(reference, 480)))
    if not panels and not right:
        return None
    label_height, gap = 34, 16
    left_width = panels[0][1].width if panels else 0
    right_width = max((image.width for _, image in right), default=0)
    left_height = (panels[0][1].height + label_height) if panels else 0
    right_height = sum(image.height + label_height + gap for _, image in right)
    sheet = Image.new("RGB", (left_width + right_width + gap * 3, max(left_height, right_height) + gap * 2), "white")
    draw = ImageDraw.Draw(sheet)
    font = _font(22)
    if panels:
        title, image, _ = panels[0]
        draw.text((gap, gap), title, fill="#111111", font=font)
        sheet.paste(image, (gap, gap + label_height))
    y, x = gap, left_width + gap * 2
    for title, image in right:
        draw.text((x, y), title, fill="#111111", font=font)
        sheet.paste(image, (x, y + label_height))
        y += image.height + label_height + gap
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, format="JPEG", quality=88)
    return out_path


def write_sheet_and_todo(base, packet_path, reference=None):
    base = Path(base).resolve()
    packet = json.loads(Path(packet_path).read_text(encoding="utf-8"))
    job = packet["job"]
    sheet = build_sheet(base, packet, base / "review" / "sheets" / f"{job}.jpg", reference=reference)
    guidance = {key: packet[key] for key in packet if key.endswith("_guidance") or key in {"reuse_guidance", "title_effect_fallback"}}
    if reference:
        guidance["design_fidelity"] = ("The sheet shows the adopted template's reference thumbnail. In visual_design notes, "
                                       "compare layout, palette, typography and lighting with it (close/partial/off for each); "
                                       "the product itself must follow the product evidence, never the reference.")
    todo = {"schema": TODO_SCHEMA, "job": job, "review_id": packet["review_id"],
            "packet": Path(packet_path).relative_to(base).as_posix(),
            "look_at": {"sheet": sheet.relative_to(base).as_posix() if sheet else None,
                        "original": packet.get("preview"), "mobile": packet.get("mobile_preview"),
                        "comparisons": [item["path"] for item in packet.get("comparisons", [])]},
            "missing_annotations": packet.get("missing_annotations", []),
            "approved_copy": packet.get("approved_copy"), "guidance": guidance,
            "reviews": copy.deepcopy(packet.get("reviews", {})),
            "how": ("Look at the sheet (open the original only if something is unclear), fill every verdict "
                    "(pass/fail/not_applicable) with specific notes, then review-submit --packet <this todo>.")}
    out = base / "review" / "packets" / f"{job}.todo.json"
    out.write_text(json.dumps(todo, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"sheet": todo["look_at"]["sheet"], "todo": out.relative_to(base).as_posix()}


def expand_todos(base, payload):
    """Turn compact todos (single, list or map) back into full bound packets."""
    base = Path(base).resolve()

    def expand(item):
        if not (isinstance(item, dict) and item.get("schema") == TODO_SCHEMA):
            return item
        path = (base / item["packet"]).resolve()
        if not path.is_relative_to(base) or not path.is_file():
            raise ValueError(f"Review todo points to a missing packet: {item.get('packet')}")
        packet = json.loads(path.read_text(encoding="utf-8"))
        if packet.get("job") != item.get("job") or packet.get("review_id") != item.get("review_id"):
            raise ValueError("STALE_REVIEW_PACKET: the todo belongs to an older review packet; use the latest todo")
        packet["reviews"] = copy.deepcopy(item.get("reviews", {}))
        return packet

    if isinstance(payload, list):
        return [expand(item) for item in payload]
    if isinstance(payload, dict) and payload.get("schema") == TODO_SCHEMA:
        return expand(payload)
    if isinstance(payload, dict) and payload and all(isinstance(value, dict) and value.get("schema") == TODO_SCHEMA
                                                     for value in payload.values()):
        return {key: expand(value) for key, value in payload.items()}
    return payload
