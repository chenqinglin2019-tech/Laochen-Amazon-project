#!/usr/bin/env python3
"""Turn the user's own reference image sets into user template families (schema v2).

prepare  -> validates/hashes images, dedupes against the library, detects shape,
            extracts a palette with role guesses, writes ONE numbered contact sheet
            per set and a packet skeleton (deterministic fields filled, observations null)
(agent)  -> looks at the sheet (and single previews where needed) and fills English
            observations: slot role, product/text/logo boxes, text-group skeleton,
            generation parameters, family profile and tokens
submit   -> validates, builds neutralized style plates + thumbnails, compiles family +
            templates, imports atomically under the library lock, returns IDs and
            (with --manifest) prefers/pins the family for the current project
revise   -> one post-production revision (new revision number) per project
Code never interprets images semantically and never calls a model.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import re
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from lc_template_library import Library, LibraryError, merge_documents  # noqa: E402

PACKET_SCHEMA = "lc-template-intake/1"
ACCEPTED = {".png", ".jpg", ".jpeg", ".webp"}
FONT = SCRIPT_DIR.parent / "assets/fonts/NotoSans-Regular.ttf"
GENERATION_FIELDS = ("background", "props", "surface", "lighting", "color_grade", "camera", "depth_of_field",
                     "product_placement", "product_scale", "shadow", "negative_space", "mood")


class IntakeError(RuntimeError):
    pass


def _font(size):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(str(FONT), size)
    except OSError:
        return ImageFont.load_default()


def _open_normalized(path: Path):
    """EXIF-orient and convert embedded ICC profiles to sRGB."""
    from PIL import Image, ImageOps
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source)
        icc = source.info.get("icc_profile")
        image = image.convert("RGB") if image.mode != "RGB" else image.copy()
    if icc:
        try:
            from PIL import ImageCms
            image = ImageCms.profileToProfile(image, ImageCms.ImageCmsProfile(io.BytesIO(icc)),
                                              ImageCms.createProfile("sRGB"), outputMode="RGB")
        except Exception:  # noqa: BLE001 - keep the pixels; colour conversion is best effort
            pass
    return image


def _shape(size):
    ratio = size[0] / size[1]
    return "square" if 0.95 <= ratio <= 1.05 else "wide" if ratio > 1 else "portrait"


def _dhash(image) -> str:
    small = image.convert("L").resize((9, 8))
    pixels = list(small.getdata()) if not hasattr(small, "get_flattened_data") else list(small.get_flattened_data())
    bits = "".join("1" if pixels[row * 9 + col] > pixels[row * 9 + col + 1] else "0" for row in range(8) for col in range(8))
    return f"{int(bits, 2):016x}"


def _hamming(first, second) -> int:
    return bin(int(first, 16) ^ int(second, 16)).count("1")


def _luminance(hex_color):
    rgb = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    rgb = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in rgb]
    return .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2]


def contrast(first, second):
    a, b = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (a + .05) / (b + .05)


def _palette(image, colors=8):
    small = image.copy()
    small.thumbnail((128, 128))
    quantized = small.quantize(colors=colors, method=0, dither=0)
    palette = quantized.getpalette()
    counts = sorted(quantized.getcolors(), reverse=True)
    total = sum(count for count, _ in counts)
    rows = []
    for count, index in counts:
        r, g, b = palette[index * 3:index * 3 + 3]
        rows.append({"hex": f"#{r:02X}{g:02X}{b:02X}", "share": round(count / total, 4)})
    return rows


def _border_color(image):
    from PIL import ImageStat
    width, height = image.size
    band = max(2, min(width, height) // 40)
    strips = [image.crop((0, 0, width, band)), image.crop((0, height - band, width, height)),
              image.crop((0, 0, band, height)), image.crop((width - band, 0, width, height))]
    means = [ImageStat.Stat(strip).median for strip in strips]
    channels = [sorted(values[i] for values in means)[len(means) // 2] for i in range(3)]
    return "#%02X%02X%02X" % tuple(int(c) for c in channels)


def _role_guesses(image, palette):
    background = _border_color(image)
    ink = max((row["hex"] for row in palette), key=lambda value: contrast(value, background))
    def saturation(value):
        r, g, b = (int(value[i:i + 2], 16) for i in (1, 3, 5))
        return (max(r, g, b) - min(r, g, b)) / 255
    accents = [row["hex"] for row in palette if row["share"] >= 0.02 and row["hex"] not in {background, ink}]
    accent = max(accents, key=saturation) if accents else ink
    return {"background": background, "ink": ink, "accent": accent}


def _white_corner_score(image):
    from PIL import ImageStat
    width, height = image.size
    size = max(4, min(width, height) // 20)
    corners = [image.crop((0, 0, size, size)), image.crop((width - size, 0, width, size)),
               image.crop((0, height - size, size, height)), image.crop((width - size, height - size, width, height))]
    return min(min(ImageStat.Stat(corner).mean) for corner in corners) / 255


def _contact_sheet(images, out_path):
    from PIL import Image, ImageDraw
    tile, columns = 512, 4
    rows = (len(images) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * (tile + 24) + 24, rows * (tile + 70) + 24), "white")
    draw = ImageDraw.Draw(sheet)
    font = _font(24)
    for position, (index, image, shape) in enumerate(images):
        thumb = image.copy()
        thumb.thumbnail((tile, tile))
        x = 24 + (position % columns) * (tile + 24)
        y = 24 + (position // columns) * (tile + 70)
        ox, oy = x + (tile - thumb.width) // 2, y + (tile - thumb.height) // 2
        sheet.paste(thumb, (ox, oy))
        for step in range(1, 10):  # 10% ticks as a coordinate aid
            tx = ox + round(thumb.width * step / 10)
            ty = oy + round(thumb.height * step / 10)
            draw.line([(tx, oy - 6), (tx, oy)], fill="#e0007a", width=2)
            draw.line([(ox - 6, ty), (ox, ty)], fill="#e0007a", width=2)
        draw.text((x, y + tile + 12), f"#{index}  {shape}  {image.width}x{image.height}", fill="#111111", font=font)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, format="JPEG", quality=88)
    return out_path


def _expand(paths):
    files = []
    for value in paths:
        path = Path(value).expanduser()
        if path.is_symlink():
            raise IntakeError(f"Symbolic links are not accepted: {path}")
        if path.is_dir():
            files.extend(sorted(p for p in path.iterdir() if p.suffix.lower() in ACCEPTED and p.is_file() and not p.is_symlink()))
        elif path.is_file():
            files.append(path)
        else:
            raise IntakeError(f"Not found: {path}")
    return files


def prepare(images, *, set_name=None, set_id=None, library=None):
    from PIL import UnidentifiedImageError
    library = library or Library()
    library.root.mkdir(parents=True, exist_ok=True)
    files = _expand(images)
    if not files:
        raise IntakeError("No PNG/JPEG/WebP reference images given")
    for path in files:
        if path.suffix.lower() not in ACCEPTED:
            raise IntakeError(f"{path.name}: only PNG/JPEG/WebP are accepted (convert HEIC/other formats first)")
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    digest = hashlib.sha256("".join(sorted(p.name for p in files)).encode("utf-8")).hexdigest()[:6]
    packet_id = f"{stamp}-{digest}"
    folder = library.root / "intake" / packet_id
    (folder / "images").mkdir(parents=True, exist_ok=True)
    index = library.asset_index()
    known = {sha: meta for sha, meta in index.items() if meta.get("kind") == "reference"}
    entries, sheet_items = [], []
    for number, path in enumerate(files, 1):
        payload = path.read_bytes()
        sha = hashlib.sha256(payload).hexdigest()
        try:
            image = _open_normalized(path)
        except (UnidentifiedImageError, OSError) as exc:
            raise IntakeError(f"{path.name}: unreadable image ({exc})") from exc
        dhash = _dhash(image)
        similar = next((other for other, meta in known.items() if meta.get("dhash") and other != sha
                        and _hamming(meta["dhash"], dhash) <= 6), None)
        copy_path = folder / "images" / f"{number:02d}{path.suffix.lower()}"
        copy_path.write_bytes(payload)
        palette = _palette(image)
        entries.append({
            "index": number, "sha256": sha, "filename": path.name, "file": copy_path.relative_to(library.root).as_posix(),
            "size": list(image.size), "observed_shape": _shape(image.size), "dhash": dhash, "palette": palette,
            "role_guesses": _role_guesses(image, palette),
            "suggested_slot_role": "main" if _white_corner_score(image) > 0.95 else None,
            "duplicate_of": sha if sha in known else None, "similar_to": similar, "include": sha not in known,
            "slot_role": None, "recipe": None, "observation": None,
            "product_bbox_norm": None, "text_boxes_norm": [], "logo_boxes_norm": [],
            "layout": {"product_region_norm": None, "text_groups": [], "graphics": []},
            "generation": {key: None for key in GENERATION_FIELDS}})
        sheet_items.append((number, image, entries[-1]["observed_shape"]))
    sheet = _contact_sheet(sheet_items, folder / "contact_sheet.jpg")
    first = entries[0]["role_guesses"]
    from lc_template_schema import taxonomy
    tax = taxonomy()
    packet = {
        "schema": PACKET_SCHEMA, "packet_id": packet_id, "created_at": time.time(),
        "set": {"name": set_name, "set_id": set_id or digest}, "contact_sheet": sheet.relative_to(library.root).as_posix(),
        "images": entries,
        "family": {"name": set_name, "description": None,
                   "product_profile": {"categories": [], "attributes": {}},
                   "tokens": {"palette": {"background": first["background"], "ink": first["ink"], "accent": first["accent"]},
                              "palette_names": {},
                              "fonts": {"display": {"face": None, "weight": None}, "text": {"face": None, "weight": 400},
                                        "label": {"face": None, "weight": 600}},
                              "photography": {"look": None, "light": None, "grade": None}},
                   "avoid": []},
        "review": {"visual_reviewed": False, "notes": ""},
        "vocabulary": {"slot_roles": tax["slot_roles"], "recipes": tax["recipes"], "text_roles": tax["text_roles"],
                       "palette_roles": tax["palette_roles"], "font_faces": tax["font_faces"],
                       "categories": sorted(tax["categories"]), "attributes": tax["attributes"],
                       "shadow_types": tax["shadow_types"]},
        "how": ("Look at contact_sheet (numbers match images[].index; ticks mark 10% steps). For each included image set "
                "slot_role, recipe (main -> none), English observation, product_bbox_norm, text_boxes_norm + logo_boxes_norm "
                "(ALL visible text/logos, used to neutralize the plate), layout.text_groups (roles, boxes, align, font_role, "
                "size = 360px token, color_role, case, letter_spacing_em, line_height, surface{kind,color_role,radius_em,"
                "border_color_role,border_width_px,shadow}, pill{color_role,text_color_role} for tag/pill labels, "
                "divider{color_role,width_px,length_em} for a rule under the text; never the sample words), layout.product_region_norm "
                "and generation fields. Then fill family (name, description, product_profile, tokens) and set "
                "review.visual_reviewed=true with notes. Use sample-colors for exact hex values. Only borrow design, never "
                "the sample product, brand, logos or claims.")}
    (folder / "packet.json").write_text(json.dumps(packet, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"packet": str(folder / "packet.json"), "contact_sheet": str(sheet), "images": len(entries),
            "duplicates": [e["index"] for e in entries if e["duplicate_of"]],
            "similar": [e["index"] for e in entries if e["similar_to"]]}


def sample_colors(packet_path, image_index, box, library=None):
    library = library or Library()
    packet = json.loads(Path(packet_path).read_text(encoding="utf-8"))
    entry = next((e for e in packet["images"] if e["index"] == image_index), None)
    if entry is None:
        raise IntakeError(f"No image #{image_index} in the packet")
    image = _open_normalized(library.root / entry["file"])
    width, height = image.size
    x, y, w, h = box
    crop = image.crop((int(x * width), int(y * height), int((x + w) * width), int((y + h) * height)))
    palette = _palette(crop, colors=4)
    background = palette[0]["hex"]
    text = max((row["hex"] for row in palette), key=lambda value: contrast(value, background))
    return {"image": image_index, "box": box, "colors": palette, "likely_background": background,
            "likely_text": text, "contrast": round(contrast(text, background), 2)}


def _slug(value):
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "reference set").casefold()).strip("-")
    return (slug or "reference-set")[:40].strip("-")


def _english(value, where, errors):
    from lc_template_schema import CJK
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{where}: English text required")
    elif CJK.search(value):
        errors.append(f"{where}: write observations in English")


def _validate_packet(packet):
    from lc_template_schema import taxonomy, _box, validate_profile, HEX
    tax, errors = taxonomy(), []
    if packet.get("schema") != PACKET_SCHEMA:
        return ["Not an intake packet"]
    if (packet.get("review") or {}).get("visual_reviewed") is not True:
        errors.append("review.visual_reviewed must be true after actually viewing every included image")
    included = [e for e in packet.get("images", []) if e.get("include")]
    if not included:
        errors.append("No included images")
    for entry in included:
        where = f"image #{entry.get('index')}"
        if entry.get("slot_role") not in tax["slot_roles"]:
            errors.append(f"{where}.slot_role must be one of {tax['slot_roles']}")
        if entry.get("recipe") not in tax["recipes"]:
            errors.append(f"{where}.recipe must be one of {tax['recipes']}")
        _english(entry.get("observation"), f"{where}.observation", errors)
        box = entry.get("product_bbox_norm")
        if not _box(box) or not 0.01 <= box[2] * box[3] <= 0.98:
            errors.append(f"{where}.product_bbox_norm must be a normalized box covering 1-98% of the image")
        for key in ("text_boxes_norm", "logo_boxes_norm"):
            for item in entry.get(key, []):
                if not _box(item) or item[2] * item[3] > 0.5:
                    errors.append(f"{where}.{key} boxes must be normalized and at most half the image")
        generation = entry.get("generation") or {}
        if not any(generation.get(key) for key in GENERATION_FIELDS):
            errors.append(f"{where}.generation needs the observed photographic parameters")
        for key, value in generation.items():
            if value not in (None, "", []):
                if isinstance(value, list):
                    for item in value:
                        _english(item, f"{where}.generation.{key}", errors)
                else:
                    _english(value, f"{where}.generation.{key}", errors)
    family = packet.get("family") or {}
    _english(family.get("name"), "family.name", errors)
    errors.extend(validate_profile(family.get("product_profile"), "family.product_profile"))
    palette = (family.get("tokens") or {}).get("palette") or {}
    if not palette or any(role not in tax["palette_roles"] or not isinstance(value, str) or not HEX.fullmatch(value)
                          for role, value in palette.items()):
        errors.append("family.tokens.palette must map palette roles to #RRGGBB")
    for role, face in ((family.get("tokens") or {}).get("fonts") or {}).items():
        if face.get("face") not in tax["font_faces"]:
            errors.append(f"family.tokens.fonts.{role}.face must be one of {tax['font_faces']}")
    return errors


def _template_record(entry, family_id, template_id, assets):
    layout = copy.deepcopy(entry.get("layout") or {})
    layout = {key: value for key, value in layout.items() if value not in (None, [], {})}
    if entry["slot_role"] == "main":
        layout = {k: v for k, v in layout.items() if k == "product_region_norm"}
    generation = {key: value for key, value in (entry.get("generation") or {}).items() if value not in (None, "", [])}
    record = {"id": template_id, "revision": 1, "schema": 2, "family_id": family_id, "slot_role": entry["slot_role"],
              "observed_shape": entry["observed_shape"], "recipe": entry["recipe"] if entry["slot_role"] != "main" else "none",
              "layout": layout, "generation": generation, "assets": assets, "observation": entry["observation"].strip(),
              "source_ids": [f"src-{entry['sha256'][:16]}"],
              "review": {"visual_reviewed": True, "notes": "Observed in the user's reference set during intake."}}
    return record


def submit(packet_path, *, library=None, manifest_path=None, dry_run=False, product_mode="flatten"):
    from lc_style_plate import make_plate, make_thumb
    from lc_template_schema import empty_document, validate_document, semantic_hash
    library = library or Library()
    packet_path = Path(packet_path)
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    if packet.get("images") and not any(e.get("include") for e in packet["images"]) \
            and all(e.get("duplicate_of") for e in packet["images"]):
        from lc_template_schema import latest
        document = library.load_v2()
        shas = {e["sha256"] for e in packet["images"]}
        sources = {s["id"] for s in document["sources"] if s["sha256"] in shas}
        family = next((f for f in latest(document["families"]) if sources & set(f.get("source_ids", []))), None)
        result = {"family": family["id"] if family else None, "templates": [], "reused": "all images are already in the library",
                  "slots": sorted({t["slot_role"] for t in latest(document["templates"]) if family and t["family_id"] == family["id"]})}
        if manifest_path and family:
            result["project"] = _prefer_family(Path(manifest_path), family["id"])
        return result
    errors = _validate_packet(packet)
    if errors:
        raise IntakeError("Intake packet rejected:\n- " + "\n- ".join(errors[:40]))
    included = [e for e in packet["images"] if e.get("include")]
    family_hash = hashlib.sha256("".join(sorted(e["sha256"] for e in included)).encode()).hexdigest()[:6]
    family_id = f"{_slug(packet['family']['name'])}-{family_hash}"
    plates, stored, templates, sources, slot_counts = [], [], [], [], {}
    for entry in included:
        image = _open_normalized(library.root / entry["file"])
        text_boxes = entry.get("text_boxes_norm") or [g["box"] for g in (entry.get("layout") or {}).get("text_groups", []) if g.get("box")]
        try:
            plate, metrics = make_plate(image, entry["product_bbox_norm"], text_boxes, entry.get("logo_boxes_norm", []),
                                        mode=product_mode)
        except ValueError as exc:
            raise IntakeError(f"image #{entry['index']}: {exc}") from exc
        thumb = make_thumb(image)
        assets = {}
        if not dry_run:
            original = (library.root / entry["file"]).read_bytes()
            ext = Path(entry["file"]).suffix[1:].lower().replace("jpeg", "jpg")
            assets["reference_sha256"] = library.add_asset(original, "reference", ext, size=image.size)
            index = library.asset_index()
            index[assets["reference_sha256"]]["dhash"] = entry["dhash"]
            library._write(library.index_path, index)
            buffer = io.BytesIO()
            plate.save(buffer, format="JPEG", quality=90)
            assets["plate_sha256"] = library.add_asset(buffer.getvalue(), "plate", "jpg",
                                                       derived_from=assets["reference_sha256"], size=plate.size)
            buffer = io.BytesIO()
            thumb.save(buffer, format="JPEG", quality=88)
            assets["thumb_sha256"] = library.add_asset(buffer.getvalue(), "thumb", "jpg",
                                                       derived_from=assets["reference_sha256"], size=thumb.size)
        role = entry["slot_role"]
        slot_counts[role] = slot_counts.get(role, 0) + 1
        suffix = role.replace("_", "-") + (f"-{slot_counts[role]}" if slot_counts[role] > 1 else "")
        template = _template_record(entry, family_id, f"{family_id}-{suffix}", assets)
        templates.append(template)
        sources.append({"id": f"src-{entry['sha256'][:16]}", "filename": entry["filename"], "sha256": entry["sha256"],
                        "set_id": packet["set"].get("set_id"), "observation": entry["observation"].strip()})
        plates.append({"image": entry["index"], "metrics": metrics, "template": template["id"]})
    family_source = packet["family"]
    tokens = copy.deepcopy(family_source["tokens"])
    tokens["fonts"] = {role: {k: v for k, v in face.items() if v is not None} for role, face in tokens.get("fonts", {}).items()
                       if face.get("face")}
    tokens["photography"] = {k: v for k, v in tokens.get("photography", {}).items() if v}
    family = {"id": family_id, "revision": 1, "schema": 2, "name": family_source["name"].strip(),
              "description": (family_source.get("description") or "").strip(),
              "origin": {"kind": "user_intake", "set_id": packet["set"].get("set_id"), "source_count": len(included)},
              "product_profile": family_source["product_profile"], "tokens": tokens,
              "avoid": list(family_source.get("avoid", [])), "source_ids": [s["id"] for s in sources],
              "review": {"visual_reviewed": True, "notes": packet["review"].get("notes") or "Visually reviewed during intake."}}
    incoming = empty_document()
    incoming.update(sources=sources, families=[family], templates=templates)
    errors = validate_document(incoming)
    if errors:
        raise IntakeError("Compiled records are invalid:\n- " + "\n- ".join(errors[:40]))
    if dry_run:
        return {"dry_run": True, "family": family_id, "templates": [t["id"] for t in templates], "plates": plates}
    with library.lock():
        current = library.load_v2()
        existing = {semantic_hash(t) for t in current["templates"]}
        reused = [t["id"] for t in templates if semantic_hash(t) in existing]
        known_families = {(f["id"], f["revision"]) for f in current["families"]}
        if (family["id"], family["revision"]) in known_families:
            incoming["families"] = []  # identical set re-submitted: keep the stored record
        incoming["templates"] = [t for t in templates if semantic_hash(t) not in existing]
        merged = merge_documents(current, incoming)
        library._write(library.v2_path, merged)
    result = {"family": family_id, "templates": [t["id"] for t in templates], "reused": reused,
              "slots": sorted(slot_counts), "plates": plates}
    if manifest_path:
        result["project"] = _prefer_family(Path(manifest_path), family_id)
    (packet_path.parent / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for entry in included:  # originals now live content-addressed in the library
        (library.root / entry["file"]).unlink(missing_ok=True)
    return result


def _prefer_family(manifest_path, family_id):
    import lc_image_pipeline as p
    from lc_workflow import manifest_lock
    with manifest_lock(manifest_path):
        manifest = p.read_json(manifest_path)
        policy = manifest.get("design_template_policy") or {}
        if policy.get("version") != 2:
            return {"pinned": False, "reason": "project does not use template policy v2"}
        preferred = list(dict.fromkeys(policy.get("prefer_family_ids", []) + [family_id]))
        policy["prefer_family_ids"] = preferred
        manifest["design_template_policy"] = policy
        started = any(job.get("generation_attempts") for job in manifest.get("jobs", []))
        pinned = False
        if not started and len(preferred) == 1:
            manifest["design_template_set_id"] = family_id
            manifest.pop("design_template_set_revision", None)
            pinned = True
        p.write_json(manifest_path, manifest)
    return {"pinned": pinned, "preferred": preferred,
            "reason": None if pinned else "generation already started or several preferred families; set design_template_set_id explicitly"}


def revise(manifest_path, template_id, patch, *, library=None):
    """One post-production revision per project: generation/layout/tokens only."""
    import lc_image_pipeline as p
    from lc_template_schema import latest, validate_document
    from lc_workflow import manifest_lock
    library = library or Library()
    allowed = {"generation", "layout", "tokens"}
    if not isinstance(patch, dict) or not patch or set(patch) - allowed:
        raise IntakeError(f"A revision may only change {sorted(allowed)}")
    manifest_path = Path(manifest_path)
    with manifest_lock(manifest_path):
        manifest = p.read_json(manifest_path)
        log = manifest.setdefault("design_template_revision_log", [])
        if log:
            raise IntakeError("This project already used its one template revision")
        with library.lock():
            document = library.load_v2()
            template = next((t for t in latest(document["templates"]) if t["id"] == template_id), None)
            if template is None:
                raise IntakeError(f"Unknown user template {template_id}")
            revised = copy.deepcopy(template)
            revised["revision"] += 1
            for key in ("generation", "layout"):
                if key in patch:
                    revised[key] = {**revised[key], **patch[key]}
            document["templates"].append(revised)
            if "tokens" in patch:
                family = next(f for f in latest(document["families"]) if f["id"] == template["family_id"])
                new_family = copy.deepcopy(family)
                new_family["revision"] += 1
                new_family["tokens"] = {**new_family["tokens"], **patch["tokens"]}
                document["families"].append(new_family)
            errors = validate_document(document)
            if errors:
                raise IntakeError("Revision is invalid:\n- " + "\n- ".join(errors[:20]))
            library._write(library.v2_path, document)
        log.append({"template": template_id, "revision": revised["revision"], "at": time.time()})
        p.write_json(manifest_path, manifest)
    return {"template": template_id, "revision": revised["revision"],
            "note": "Jobs that should adopt it need design_template_revision or a fresh selection; this regenerates them."}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--library-dir")
    subs = parser.add_subparsers(dest="command", required=True)
    prep = subs.add_parser("prepare")
    prep.add_argument("--images", nargs="+", required=True, help="Image files and/or folders (one set per call)")
    prep.add_argument("--set-name")
    prep.add_argument("--set-id")
    colors = subs.add_parser("sample-colors")
    colors.add_argument("--packet", required=True)
    colors.add_argument("--image", type=int, required=True)
    colors.add_argument("--box", required=True, help="x,y,w,h normalized")
    sub = subs.add_parser("submit")
    sub.add_argument("--packet", required=True)
    sub.add_argument("--manifest")
    sub.add_argument("--dry-run", action="store_true")
    sub.add_argument("--product-mode", choices=("flatten", "blur"), default="flatten")
    rev = subs.add_parser("revise")
    rev.add_argument("--manifest", required=True)
    rev.add_argument("--template", required=True)
    rev.add_argument("--patch", required=True, help="JSON file with generation/layout/tokens changes")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    library = Library(args.library_dir)
    try:
        if args.command == "prepare":
            result = prepare(args.images, set_name=args.set_name, set_id=args.set_id, library=library)
        elif args.command == "sample-colors":
            box = [float(v) for v in args.box.split(",")]
            result = sample_colors(args.packet, args.image, box, library=library)
        elif args.command == "submit":
            result = submit(args.packet, library=library, manifest_path=args.manifest, dry_run=args.dry_run,
                            product_mode=args.product_mode)
        else:
            result = revise(args.manifest, args.template, json.loads(Path(args.patch).read_text(encoding="utf-8")),
                            library=library)
        print(json.dumps({"ok": True, "command": args.command, **result}, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (IntakeError, LibraryError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "command": args.command, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
