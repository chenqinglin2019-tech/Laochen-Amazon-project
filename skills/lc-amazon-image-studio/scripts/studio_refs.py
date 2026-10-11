"""References for the V8.1 pipeline: tone boards, hidden photo copies and per-project references.

A reference image never reaches the image model as it is. A user template's plate or a
per-project reference is reduced to a tone board (palette, brightness, light direction
only; see lc_style_plate.make_tone_board) and only when plan.json opts in with tone_ref.
Product photos that show a person or unrelated items get a copy with those areas hidden.
All derived files live inside the project (never in the shared template library) and are
named by content, so re-planning reuses them. Pillow + NumPy only.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

REF_TYPES = {".jpg", ".jpeg", ".png", ".webp"}
HIDDEN_LONG_EDGE = 2048


def _on_white(path):
    """Open (EXIF/ICC normalized) and composite any transparency onto white."""
    import studio_main
    from PIL import Image
    image, alpha = studio_main.open_normalized(path)
    if alpha is not None:
        canvas = Image.new("RGB", image.size, (255, 255, 255))
        canvas.paste(image.convert("RGB"), mask=alpha)
        image = canvas
    return image.convert("RGB")


def _save_jpeg(image, target, quality):
    import lc_fsretry
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.stem}.tmp.jpg")
    image.save(temporary, format="JPEG", quality=quality, subsampling=0)
    lc_fsretry.replace(temporary, target)


def tone_board(source, project_dir, key):
    """design/tones/<key>-t<v>.jpg made from `source` (plate or reference).

    Returns (project-relative path, main colours as hex words)."""
    import lc_style_plate
    import studio_project as sp
    target = Path(project_dir) / "design" / "tones" / f"{key[:16]}-t{lc_style_plate.TONE_VERSION}.jpg"
    image = _on_white(source)
    if not target.is_file():
        _save_jpeg(lc_style_plate.make_tone_board(image), target, 90)
    return sp.rel(target, project_dir), lc_style_plate.main_colours(image)


def hidden_copy(project_dir, photo, boxes):
    """design/hidden/<key>.jpg: the photo with the given normalized boxes flattened and blurred."""
    import lc_style_plate
    import studio_project as sp
    from PIL import Image
    key = hashlib.sha256((photo["sha256"] + json.dumps(boxes, sort_keys=True)).encode("utf-8")).hexdigest()[:16]
    target = Path(project_dir) / "design" / "hidden" / f"{key}.jpg"
    if not target.is_file():
        image = _on_white(Path(project_dir) / photo["path"])
        scale = min(1.0, HIDDEN_LONG_EDGE / max(image.size))
        if scale < 1:
            image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
        hidden, _ = lc_style_plate.hide_regions(image, boxes)
        _save_jpeg(hidden, target, 92)
    return sp.rel(target, project_dir)


def add_refs(project, project_dir, paths):
    """Copy reference images into refs/ (ids ref1, ref2, ...). They are never product photos."""
    import studio_project as sp
    from PIL import Image
    folder = Path(project_dir)
    refs = project.setdefault("refs", [])
    known = {ref["sha256"]: ref for ref in refs}
    photo_shas = {photo["sha256"] for photo in project.get("photos", [])}
    added, skipped = [], []
    for value in paths:
        source = Path(value).expanduser()
        if not source.is_file():
            raise sp.StudioError(f"REF_NOT_FOUND: {source}")
        suffix = source.suffix.lower()
        if suffix in {".heic", ".heif"}:
            raise sp.StudioError(f"REF_FORMAT: {source.name} is HEIC; export it as JPEG or PNG first")
        if suffix not in REF_TYPES:
            raise sp.StudioError(f"REF_FORMAT: {source.name}: use JPEG, PNG or WebP")
        digest = sp.sha256_file(source)
        if digest in photo_shas:
            raise sp.StudioError(f"REF_IS_PRODUCT_PHOTO: {source.name} is already registered as a product photo; "
                                 "a reference cannot also be a product photo")
        if digest in known:
            skipped.append({"ref": str(source), "existing": known[digest]["id"]})
            continue
        number = 1 + max([int(ref["id"][3:]) for ref in refs if ref["id"][3:].isdigit()] or [0])
        ref_id = f"ref{number}"
        target = folder / "refs" / f"{ref_id}{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        with Image.open(target) as opened:
            size = list(opened.size)
        record = {"id": ref_id, "path": sp.rel(target, folder), "sha256": digest, "size": size, "added_at": time.time()}
        refs.append(record)
        known[digest] = record
        added.append({"id": ref_id, "size": size, "source": source.name})
    sheet = contact_sheet(project, folder)
    return {"added": added, "skipped": skipped, **({"refs_sheet": str(sheet)} if sheet else {}),
            "note": ("References are for your analysis only. If one genuinely suits a slot's design, set "
                     "tone_ref: \"refN\" there: only its colour tone and light reach the image model, as a blurred board.")}


def contact_sheet(project, project_dir):
    """catalog/refs.jpg: the project's references labelled by id (agent-only). Returns the path or None."""
    from PIL import Image, ImageDraw, ImageFont
    refs = [ref for ref in project.get("refs", []) if (Path(project_dir) / ref["path"]).is_file()]
    if not refs:
        return None
    out_path = Path(project_dir) / "catalog" / "refs.jpg"
    stamp = out_path.with_suffix(".json")
    digest = hashlib.sha256(json.dumps([(ref["id"], ref["sha256"]) for ref in refs]).encode()).hexdigest()[:12]
    try:
        if out_path.is_file() and json.loads(stamp.read_text(encoding="utf-8")).get("digest") == digest:
            return out_path
    except (OSError, ValueError):
        pass
    tile, label_h, columns = 320, 34, 4
    rows = (len(refs) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * tile, rows * (tile + label_h)), "white")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default(size=20)
    except TypeError:  # Pillow < 10.1
        font = ImageFont.load_default()
    for index, ref in enumerate(refs):
        thumb = _on_white(Path(project_dir) / ref["path"])
        thumb.thumbnail((tile - 8, tile - 8))
        x, y = (index % columns) * tile, (index // columns) * (tile + label_h)
        sheet.paste(thumb, (x + (tile - thumb.width) // 2, y + label_h + (tile - thumb.height) // 2))
        draw.text((x + 6, y + 6), ref["id"], fill="#111111", font=font)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, format="JPEG", quality=85)
    stamp.write_text(json.dumps({"digest": digest}), encoding="utf-8")
    return out_path
