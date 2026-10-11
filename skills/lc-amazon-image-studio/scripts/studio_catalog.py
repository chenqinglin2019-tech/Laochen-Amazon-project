"""Template catalog for the agent (V8): built-in + the user's own templates, compact.

The agent reads one compact JSON (families, one line per template, per-slot frame and
copy budget) and, when the user has reference-set templates, looks once at a contact
sheet of their thumbnails. It then picks one family for the set and a template per
slot, or `custom`. Thumbnails are never sent to the image model.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

TEXT_CAPACITY = {"photo_overlay": "headline+subline", "header_footer": "headline+subline+2 labels",
                 "photo_sidebar": "headline+subline+3 labels", "scene_grid": "headline+4 captions",
                 "detail_callouts": "headline+4 callouts", "steps": "headline+3-4 steps", "none": "no text"}
HOW_TO_CHOOSE = ("Pick ONE family for the whole set (consistent look); prefer preferred:true families (the user's own "
                 "reference sets) when they suit this product. For each slot pick the template whose fits/layout match that "
                 "image's message, or 'custom' with your own design when nothing fits. Respect each slot's copy budget. "
                 "Scenes are always your own: user templates lend layout, typography and - only if you set tone_ref after "
                 "judging them suitable - colour tone and light; never their people, objects or setting.")


def _first_sentence(text, limit):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    sentence = re.split(r"(?<=[.;])\s", text, maxsplit=1)[0]
    return (sentence[:limit - 1] + "…") if len(sentence) > limit else sentence


def _position(box):
    x, y, w, h = box
    cx, cy = x + w / 2, y + h / 2
    vertical = "top" if cy < 0.38 else "bottom" if cy > 0.62 else "middle"
    horizontal = "left" if cx < 0.38 else "right" if cx > 0.62 else "centre"
    if w >= 0.7:
        return f"{vertical} band"
    if h >= 0.6:
        return f"{horizontal} column"
    return f"{vertical}-{horizontal}"


def load(library_dir=None):
    """{'builtin': {...families, templates} (respecting the enable switch), 'user': V2 document}."""
    import lc_design_templates as builtin_lib
    from lc_template_library import Library
    from lc_template_schema import latest
    library = Library(library_dir)
    builtin = {"families": [], "templates": []}
    if library.builtin_enabled():
        try:
            document = builtin_lib.load_library()
            builtin = {"families": builtin_lib._latest(document["families"]),
                       "templates": builtin_lib._latest(document["templates"])}
        except Exception as exc:  # noqa: BLE001 - a broken built-in file must not block the user's own templates
            builtin = {"families": [], "templates": [], "error": str(exc)[:200]}
    try:
        user = library.load_v2()
        user = {"families": latest(user["families"]), "templates": latest(user["templates"]), "sources": user.get("sources", [])}
    except Exception as exc:  # noqa: BLE001
        user = {"families": [], "templates": [], "error": str(exc)[:200]}
    return {"library_dir": str(library.root), "builtin": builtin, "user": user, "library": library}


def resolve(catalog, template_id):
    """(source, family, template) for a template id, or None."""
    for source in ("user", "builtin"):
        templates = catalog[source]["templates"]
        template = next((item for item in templates if item["id"] == template_id), None)
        if template:
            family = next((item for item in catalog[source]["families"] if item["id"] == template["family_id"]), None)
            return source, copy.deepcopy(family), copy.deepcopy(template)
    return None


def family_ids(catalog):
    return {family["id"]: source for source in ("builtin", "user") for family in catalog[source]["families"]}


def _builtin_family(family, templates):
    style = family.get("style") or {}
    return {"id": family["id"], "source": "builtin", "name": family.get("name"),
            "for": family.get("categories", [])[:8],
            "look": _first_sentence(style.get("photography"), 140) + " " + _first_sentence(style.get("palette"), 110),
            "type": _first_sentence(style.get("typography"), 120),
            "templates": [{"id": item["id"], "fits": item.get("intents", [])[:4], "recipe": item.get("recipe"),
                           "layout": _first_sentence((item.get("generation") or {}).get("composition"), 110)
                           + ((" Text: " + _first_sentence((item.get("generation") or {}).get("reserved_space"), 70))
                              if (item.get("generation") or {}).get("reserved_space") else ""),
                           "text": TEXT_CAPACITY.get(item.get("recipe"), "headline+subline")}
                          for item in templates if item.get("family_id") == family["id"]]}


def _user_family(family, templates, code, preferred, tiles):
    tokens = family.get("tokens") or {}
    fonts = {role: " ".join(str(part) for part in (spec.get("face"), spec.get("weight"), spec.get("case")) if part)
             for role, spec in (tokens.get("fonts") or {}).items()}
    rows = []
    for item in templates:
        if item.get("family_id") != family["id"]:
            continue
        groups = (item.get("layout") or {}).get("text_groups", [])
        roles = "+".join(dict.fromkeys(group.get("role", "text") for group in groups)) or "no text"
        where = ", ".join(f"{group.get('role')} {_position(group['box'])}" for group in groups[:3] if group.get("box"))
        product = (item.get("layout") or {}).get("product_region_norm")
        layout = (where + (f"; product {_position(product)}" if product else "")).strip("; ")
        rows.append({"id": item["id"], "slot": item.get("slot_role"), "shape": item.get("observed_shape"),
                     "recipe": item.get("recipe"), "tile": tiles.get(item["id"]), "text": roles, "layout": layout,
                     "tone": bool((item.get("assets") or {}).get("plate_sha256"))})
    return {"id": family["id"], "source": "user", "code": code, "preferred": preferred, "name": family.get("name"),
            "for": (family.get("product_profile") or {}).get("categories", []),
            "palette": (tokens.get("palette") or {}), "fonts": fonts,
            "photography": " / ".join(str(v) for v in (tokens.get("photography") or {}).values())[:160],
            "templates": rows}


def slot_rows(project):
    import studio_plan
    from lc_frame_fit import plan as frame_plan
    rows = []
    for slot in project["slots"]:
        frame = frame_plan(slot["canvas"])
        band = frame["band"]
        keep = None if frame["exact"] else (f"y {band[1] * 100:.1f}-{(band[1] + band[3]) * 100:.1f}%" if band[3] < 1
                                            else f"x {band[0] * 100:.1f}-{(band[0] + band[2]) * 100:.1f}%")
        rows.append({"id": slot["id"], "role": slot["role"], "purpose": slot.get("purpose"), "canvas": slot["canvas"],
                     "frame": frame["frame"], **({"keep_band": keep} if keep else {}),
                     "budget": "none (no text)" if slot["kind"] == "main" else studio_plan.tier_for(slot["canvas"])})
    return rows


def compact(catalog, project, project_dir=None):
    import studio_plan
    preferred = set(project.get("preferred_families") or [])
    user_families = catalog["user"]["families"]
    tiles, sheet = {}, None
    codes = {family["id"]: f"U{index + 1}" for index, family in enumerate(user_families)}
    if user_families and project_dir is not None:
        sheet, tiles = contact_sheet(catalog, Path(project_dir) / "catalog" / "user_templates.jpg", codes)
    families = [_user_family(family, catalog["user"]["templates"], codes[family["id"]], family["id"] in preferred, tiles)
                for family in user_families]
    families.sort(key=lambda family: not family["preferred"])
    families += [_builtin_family(family, catalog["builtin"]["templates"]) for family in catalog["builtin"]["families"]]
    result = {"how_to_choose": HOW_TO_CHOOSE, "families": families, "slots": slot_rows(project),
              "copy_rules": studio_plan.RULES_SUMMARY}
    if sheet:
        result["contact_sheet"] = str(sheet)
    if project.get("refs"):
        import studio_refs
        result["refs"] = [ref["id"] for ref in project["refs"]]
        refs_sheet = studio_refs.contact_sheet(project, project_dir) if project_dir is not None else None
        if refs_sheet:
            result["refs_sheet"] = str(refs_sheet)
    if not families:
        result["note"] = "The template library is empty (built-ins disabled, no user templates): use 'custom' for every slot."
    return result


def family_detail(catalog, family_id):
    for source in ("user", "builtin"):
        family = next((item for item in catalog[source]["families"] if item["id"] == family_id), None)
        if family:
            import copy
            templates = [copy.deepcopy(item) for item in catalog[source]["templates"] if item.get("family_id") == family_id]
            for item in templates:
                item.pop("observation", None)  # may describe the sample product; never needed
                if source == "user":           # the user's references show someone else's scene: never reuse it
                    for key in ("background", "props", "surface"):
                        (item.get("generation") or {}).pop(key, None)
            return {"source": source, "family": family, "templates": templates}
    return None


def contact_sheet(catalog, out_path, codes):
    """Tile the user's template thumbnails (agent-only). Returns (path|None, {template_id: tile label})."""
    from PIL import Image, ImageDraw, ImageFont
    library = catalog["library"]
    entries = []
    for family in catalog["user"]["families"]:
        number = 0
        for template in catalog["user"]["templates"]:
            if template.get("family_id") != family["id"]:
                continue
            sha = (template.get("assets") or {}).get("thumb_sha256")
            if not sha:
                continue
            path = library.asset_path(sha)
            if not path.is_file():
                continue
            number += 1
            entries.append((f"{codes[family['id']]}-{number}", template, path))
    if not entries:
        return None, {}
    digest = hashlib.sha256(json.dumps([(label, t["id"], str(p)) for label, t, p in entries]).encode()).hexdigest()[:12]
    out_path = Path(out_path)
    stamp = out_path.with_suffix(".json")
    tiles = {template["id"]: label for label, template, _ in entries}
    try:
        if out_path.is_file() and json.loads(stamp.read_text(encoding="utf-8")).get("digest") == digest:
            return out_path, tiles
    except (OSError, ValueError):
        pass
    tile, label_h, columns = 320, 34, 4
    rows = (len(entries) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * tile, rows * (tile + label_h)), "white")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default(size=20)
    except TypeError:  # Pillow < 10.1
        font = ImageFont.load_default()
    for index, (label, template, path) in enumerate(entries):
        with Image.open(path) as thumb:
            thumb = thumb.convert("RGB")
            thumb.thumbnail((tile - 8, tile - 8))
        x, y = (index % columns) * tile, (index // columns) * (tile + label_h)
        sheet.paste(thumb, (x + (tile - thumb.width) // 2, y + label_h + (tile - thumb.height) // 2))
        draw.text((x + 6, y + 6), f"{label} {template.get('slot_role', '')}", fill="#111111", font=font)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, format="JPEG", quality=85)
    stamp.write_text(json.dumps({"digest": digest}), encoding="utf-8")
    return out_path, tiles
