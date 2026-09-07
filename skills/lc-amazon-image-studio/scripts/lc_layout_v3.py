"""Bounded V3 composition recipes; no arbitrary HTML, nested groups, or remote assets."""
from __future__ import annotations

import copy
import re


RECIPES = {
    "photo_overlay": {"groups": [[.06, .06, .88, .27]], "panels": [[0, 0, 1, 1]], "product": [.10, .35, .80, .60]},
    "header_footer": {"groups": [[.06, .07, .88, .16], [.06, .80, .88, .15]], "panels": [[0, .25, 1, .50]], "product": [.10, .28, .80, .44]},
    "photo_sidebar": {"groups": [[.64, .10, .30, .80]], "panels": [[0, 0, .59, 1]], "product": [.07, .08, .46, .84]},
    "scene_grid": {"groups": [[.06, .07, .88, .16]], "panels": [[.03, .25, .455, .335], [.515, .25, .455, .335], [.03, .615, .455, .335], [.515, .615, .455, .335]], "product": [.03, .25, .94, .70]},
    "detail_callouts": {"groups": [[.06, .07, .88, .16]], "panels": [[.05, .27, .53, .66]], "product": [.05, .27, .53, .66]},
    "steps": {"groups": [[.06, .07, .88, .16]], "panels": [[.03, .27, .293, .58], [.353, .27, .294, .58], [.677, .27, .293, .58]], "product": [.03, .27, .94, .58]},
}


def _core():
    import lc_layout
    return lc_layout


def recipe_geometry(name, width, height):
    recipe = copy.deepcopy(RECIPES[name])
    if width / height > 1.35:
        # Wide A+ is composed, not a squeezed square: text gets a readable
        # column while the photographs retain useful panel aspect ratios.
        if name == "photo_overlay":
            recipe.update(groups=[[.06, .12, .42, .76]], product=[.54, .08, .40, .84])
        elif name == "scene_grid":
            recipe.update(groups=[[.045, .12, .285, .76]],
                          panels=[[.375, .05, .28, .425], [.68, .05, .28, .425], [.375, .525, .28, .425], [.68, .525, .28, .425]],
                          product=[.375, .05, .585, .90])
        elif name == "steps":
            recipe.update(groups=[[.045, .12, .26, .76]],
                          panels=[[.34, .15, .19, .70], [.555, .15, .19, .70], [.77, .15, .19, .70]],
                          product=[.34, .15, .62, .70])
    return recipe


def text_groups(layout):
    """A legacy-shaped top-level text group is a fallback, never a duplicate source."""
    if "text_groups" in layout:
        return layout["text_groups"]
    if any(layout.get(key) for key in ("headline", "body", "label")):
        return [{"id": "main", **{key: layout[key] for key in
                ("headline", "body", "label", "headline_family", "headline_weight", "mobile_sizes", "text_color") if key in layout}}]
    return []


def resolve_layout_defaults(job):
    """Resolve V3 render instructions once; descriptive mood words are not code.

    Explicit group/layout fields override design_brief.layout, which overrides
    the recipe. The input job and its single copy source are never mutated.
    """
    core = _core()
    layout = copy.deepcopy(job.get("layout") or {})
    if not isinstance(layout, dict):
        raise core.LayoutError("layout must be an object")
    if layout.get("version", 1) != 3:
        return layout
    design = job.get("design_brief") or {}
    if not isinstance(design, dict) or not isinstance(design.get("layout", {}), dict):
        raise core.LayoutError("design_brief.layout must be an object")
    brief = design.get("layout", {})
    for key in ("recipe", "headline_family", "headline_weight", "text_color", "product_region_norm"):
        if key in brief:
            layout.setdefault(key, copy.deepcopy(brief[key]))
    # New template-first scaffolds deliberately leave the recipe unpinned.
    # The old template supplies only a provisional default until a brief exists.
    if "recipe" not in layout:
        provisional = layout.get("template", "scene")
        if not isinstance(provisional, str):
            raise core.LayoutError("layout.template must be a string")
        layout["recipe"] = {"dimensions": "detail_callouts", "detail": "detail_callouts",
                            "components": "photo_sidebar", "benefits": "header_footer"}.get(provisional, "photo_overlay")
    groups = copy.deepcopy(text_groups(layout))
    if not isinstance(groups, list):
        raise core.LayoutError("text_groups must be a list")
    surface = layout.get("text_surface", brief.get("text_surface"))
    if isinstance(surface, str):
        surface = {"kind": surface}
    align = layout.get("align", brief.get("align"))
    legacy_group = layout.get("text_group") or {}
    if not isinstance(legacy_group, dict):
        raise core.LayoutError("text_group must be an object")
    box = layout.get("text_group_box", legacy_group.get("box", brief.get("text_group_box")))
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            raise core.LayoutError("Every text group must be an object")
        for key in ("headline_family", "headline_weight", "text_color"):
            if key in layout:
                group.setdefault(key, layout[key])
        if align is not None:
            group.setdefault("align", align)
        if surface is not None:
            group.setdefault("surface", copy.deepcopy(surface))
        if index == 0 and box is not None:
            group.setdefault("box", copy.deepcopy(box))
    # Use one resolved representation without persisting a second copy source.
    if "text_groups" not in layout:
        for key in ("headline", "body", "label"):
            layout.pop(key, None)
    layout["text_groups"] = groups
    if isinstance(layout.get("text_surface"), dict):
        layout.pop("text_surface")
    from lc_project_contracts import apply_style_to_layout
    return apply_style_to_layout(job, layout)


def _surface(value):
    core = _core()
    if value is None:
        value = {"kind": "transparent"}
    if not isinstance(value, dict) or set(value) - {"kind", "color", "opacity", "padding_em", "direction"}:
        raise core.LayoutError("surface accepts kind/color/opacity/padding_em/direction only")
    result = {"kind": "transparent", "color": "#F7F1E8", "opacity": .94, "padding_em": .65, "direction": "horizontal", **value}
    if result["kind"] not in {"transparent", "solid", "gradient"}:
        raise core.LayoutError("surface.kind must be transparent/solid/gradient")
    if not isinstance(result["color"], str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", result["color"]):
        raise core.LayoutError("surface.color must be #RRGGBB")
    for key, maximum in (("opacity", 1), ("padding_em", 2)):
        number = result[key]
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not 0 <= number <= maximum:
            raise core.LayoutError(f"surface.{key} must be 0..{maximum}")
    if result["direction"] not in {"horizontal", "vertical"}:
        raise core.LayoutError("surface.direction must be horizontal/vertical")
    return result


def _headline_treatment(value):
    """Validate bounded local display treatments without introducing new fonts."""
    core = _core()
    if value is None:
        return {"kind": "plain"}
    if not isinstance(value, dict) or set(value) - {"kind", "color", "width_em", "offset_em", "blur_em", "opacity"}:
        raise core.LayoutError("headline_treatment accepts kind/color/width_em/offset_em/blur_em/opacity only")
    result = {"kind": "plain", **value}
    if result["kind"] not in {"plain", "outline", "shadow"}:
        raise core.LayoutError("headline_treatment.kind must be plain/outline/shadow")
    if result["kind"] == "plain":
        if set(value) != {"kind"}:
            raise core.LayoutError("plain headline_treatment cannot contain effect settings")
        return result
    if not isinstance(result.get("color"), str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", result["color"]):
        raise core.LayoutError("headline_treatment.color must be #RRGGBB")
    if result["kind"] == "outline":
        width = result.get("width_em", .055)
        if isinstance(width, bool) or not isinstance(width, (int, float)) or not .01 <= width <= .12:
            raise core.LayoutError("headline_treatment.width_em must be 0.01..0.12")
        result["width_em"] = width
    else:
        offset = result.get("offset_em", [.06, .08])
        blur, opacity = result.get("blur_em", .08), result.get("opacity", .55)
        if (not isinstance(offset, list) or len(offset) != 2
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not -0.3 <= v <= .3 for v in offset)):
            raise core.LayoutError("headline_treatment.offset_em must contain two values from -0.3..0.3")
        if isinstance(blur, bool) or not isinstance(blur, (int, float)) or not 0 <= blur <= .3:
            raise core.LayoutError("headline_treatment.blur_em must be 0..0.3")
        if isinstance(opacity, bool) or not isinstance(opacity, (int, float)) or not 0 <= opacity <= 1:
            raise core.LayoutError("headline_treatment.opacity must be 0..1")
        result.update(offset_em=offset, blur_em=blur, opacity=opacity)
    return result


def validate_layout_v3(layout):
    core = _core()
    if not isinstance(layout, dict) or layout.get("version") != 3:
        raise core.LayoutError("validate_layout_v3 requires layout.version=3")
    recipe = layout.get("recipe")
    if recipe not in RECIPES:
        raise core.LayoutError(f"layout.recipe must be one of {', '.join(RECIPES)}")
    if "product_region_norm" in layout:
        core._box(layout["product_region_norm"], "layout.product_region_norm")
    if "font_sizes" in layout:
        raise core.LayoutError("V3 uses 360px mobile_sizes, not font_sizes")
    if layout.get("canvas_background") is not None and (not isinstance(layout["canvas_background"], str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", layout["canvas_background"])):
        raise core.LayoutError("canvas_background must be #RRGGBB")
    if layout.get("faq"):
        raise core.LayoutError("V3 FAQ copy belongs in explicit text_groups (question headline, answer body)")
    if "text_groups" in layout and any(layout.get(key) for key in ("headline", "body", "label")):
        raise core.LayoutError("V3 text_groups replaces top-level headline/body/label; use one copy source")
    groups = text_groups(layout)
    if not isinstance(groups, list) or len(groups) > 6:
        raise core.LayoutError("V3 text_groups must contain at most six flat groups")
    ids = set()
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            raise core.LayoutError("Every text group must be an object")
        gid = group.get("id", f"group-{index}")
        if not isinstance(gid, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", gid) or gid in ids:
            raise core.LayoutError("Text group ids must be unique safe identifiers")
        ids.add(gid)
        if "box" in group:
            core._box(group["box"], f"text_groups[{index}].box")
        elif index >= len(RECIPES[recipe]["groups"]):
            raise core.LayoutError("Additional text groups require explicit normalized boxes")
        if group.get("align", "left") not in {"left", "center", "right"}:
            raise core.LayoutError("Text group align must be left/center/right")
        family = group.get("headline_family", layout.get("headline_family", "sans"))
        weight = group.get("headline_weight", layout.get("headline_weight", 600))
        if family not in {"sans", "serif"} or weight not in ({400, 600} if family == "serif" else {400, 600, 700}):
            raise core.LayoutError("V3 Sans weights are 400/600/700; Serif weights are 400/600")
        core._v2_mobile_sizes({"mobile_sizes": group.get("mobile_sizes", layout.get("mobile_sizes", {}))})
        copy_values = [core._text(group.get(key, ""), f"text_groups[{index}].{key}", 500 if key == "body" else 180) for key in ("headline", "body", "label")]
        if not any(copy_values):
            raise core.LayoutError("Every text group needs visible headline/body/label copy")
        ink = group.get("text_color", layout.get("text_color", "#29251F"))
        if not isinstance(ink, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", ink):
            raise core.LayoutError("Text group text_color must be #RRGGBB")
        gap = group.get("gap_em", .45)
        if isinstance(gap, bool) or not isinstance(gap, (int, float)) or not 0 <= gap <= 2:
            raise core.LayoutError("Text group gap_em must be 0..2")
        _surface(group.get("surface"))
        _headline_treatment(group.get("headline_treatment"))
    panels = layout.get("panels", [])
    if not isinstance(panels, list) or len(panels) > 4:
        raise core.LayoutError("V3 panels must contain at most four images")
    if layout.get("canvas_background") and not panels:
        raise core.LayoutError("canvas_background requires nonempty valid panels; otherwise it would hide the base product")
    ids = set()
    for index, panel in enumerate(panels):
        if not isinstance(panel, dict):
            raise core.LayoutError("Every panel must be an object")
        pid = panel.get("id", f"panel-{index}")
        if not isinstance(pid, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", pid) or pid in ids:
            raise core.LayoutError("Panel ids must be unique safe identifiers")
        ids.add(pid)
        if "box" in panel:
            core._box(panel["box"], f"panels[{index}].box")
        elif index >= len(RECIPES[recipe]["panels"]):
            raise core.LayoutError("Additional panels require explicit normalized boxes")
        for field in ("source_crop", "product_bbox_norm"):
            if panel.get(field) is not None:
                core._box(panel[field], f"panels[{index}].{field}")
        if panel.get("fit", "cover") not in {"cover", "contain"}:
            raise core.LayoutError("Panel fit must be cover/contain")
        if not isinstance(panel.get("image"), str) or not panel["image"]:
            raise core.LayoutError("Every panel needs a project-relative image")
        refs = panel.get("evidence_refs")
        if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or not ref.strip() for ref in refs):
            raise core.LayoutError("Every panel needs nonempty evidence_refs")
    items = layout.get("items", [])
    if not isinstance(items, list) or len(items) > 4:
        raise core.LayoutError("V3 supporting items must contain at most four items")
    # Reuse the mature coordinate, copy, icon and leader validation; four items
    # are validated individually instead of weakening the V2 three-item limit.
    legacy = copy.deepcopy(layout)
    legacy.update(version=2, headline_weight=min(layout.get("headline_weight", 600), 600), items=[])
    core.validate_layout_v2(legacy)
    for item in items:
        legacy["items"] = [item]
        core.validate_layout_v2(legacy)


def geometry(job, layout, width, height):
    core = _core()
    validate_layout_v3(layout)
    recipe = recipe_geometry(layout["recipe"], width, height)
    if "product_region_norm" in layout:
        # This is a generation container, not fabricated visible product pixels.
        recipe["product"] = copy.deepcopy(layout["product_region_norm"])
    groups = [{"id": group.get("id", f"group-{i}"), "box": group.get("box", recipe["groups"][i] if i < len(recipe["groups"]) else None)}
              for i, group in enumerate(text_groups(layout))]
    panels = [{"id": panel.get("id", f"panel-{i}"), "box": panel.get("box", recipe["panels"][i] if i < len(recipe["panels"]) else None)}
              for i, panel in enumerate(layout.get("panels", []))]
    template = layout.get("template", "detail" if layout["recipe"] == "detail_callouts" and layout.get("items") else "scene")
    variant = core._v2_variant(width, height)
    item_layout = copy.deepcopy(layout)
    if template == "detail" and len(item_layout.get("items", [])) == 4:
        # Four visible details are a 2x2 card area, not a fourth overflowing row.
        for index, item in enumerate(item_layout["items"]):
            x, y = .63 + (index % 2) * .165, .31 + (index // 2) * .32
            image_h = min(.20, .135 * width / height)
            item.setdefault("image_box", [x, y, .135, image_h])
            item.setdefault("text_box", [x - .005, y + image_h + .02, .15, .105])
            item.setdefault("box", [x - .005, y, .15, image_h + .125])
    items, lines = core._v2_item_slots(item_layout, template, variant, width, height)
    zones = [group["box"] for group in groups] + [slot["text"] for slot in items if slot.get("text")]
    return {"template": template, "version": 3, "recipe": layout["recipe"], "variant": variant, "canvas": [width, height],
            "safe_margin": .05, "product_zone": recipe["product"], "text_groups": groups, "panels": panels,
            "text_group": groups[0]["box"] if groups else [.05, .05, .9, .2], "text_zones": zones,
            "image_region_norm": recipe["product"], "product_region_norm": recipe["product"], "text_regions_norm": zones,
            "items": items, "lines": lines}


def prepare_groups(layout, geom, direction):
    core = _core()
    width, _ = geom["canvas"]
    prepared = []
    for group, slot in zip(text_groups(layout), geom["text_groups"]):
        tokens = core._v2_mobile_sizes({"mobile_sizes": group.get("mobile_sizes", layout.get("mobile_sizes", {}))})
        prepared.append({"id": slot["id"], "box": slot["box"],
                         **{key: core._text(group.get(key, ""), key, 500 if key == "body" else 180) for key in ("headline", "body", "label")},
                         "align": group.get("align", "right" if direction == "rtl" else "left"),
                         "sizes": {key: value * width / 360 for key, value in tokens.items()},
                         "headline_family": group.get("headline_family", layout.get("headline_family", "sans")),
                         "headline_weight": group.get("headline_weight", layout.get("headline_weight", 600)),
                         "body_weight": group.get("body_weight", layout.get("body_weight", 400)),
                         "label_weight": group.get("label_weight", layout.get("label_weight", 600)),
                         "ink": group.get("text_color", layout.get("text_color", "#29251F")),
                         "gap_em": group.get("gap_em", .45), "surface": _surface(group.get("surface")),
                         "headline_treatment": _headline_treatment(group.get("headline_treatment"))})
    return prepared


def panel_placement(panel, canvas):
    """The exact crop/destination used by both renderer and protection mapping."""
    width, height = canvas
    iw, ih = panel["source_size"]
    crop = panel.get("source_crop", [0, 0, 1, 1])
    sx, sy, sw, sh = crop[0] * iw, crop[1] * ih, crop[2] * iw, crop[3] * ih
    x, y, w, h = panel["box"]
    dx, dy, dw, dh = x * width, y * height, w * width, h * height
    scale = max(dw / sw, dh / sh) if panel["fit"] == "cover" else min(dw / sw, dh / sh)
    if panel["fit"] == "cover":
        used_w, used_h = dw / scale, dh / scale
        sx += (sw - used_w) / 2
        sy += (sh - used_h) / 2
        sw, sh = used_w, used_h
    else:
        used_w, used_h = sw * scale, sh * scale
        dx += (dw - used_w) / 2
        dy += (dh - used_h) / 2
        dw, dh = used_w, used_h
    return {"source": [sx, sy, sw, sh], "destination": [dx, dy, dw, dh]}


def mapped_product_box(panel, canvas):
    bbox = panel.get("product_bbox_norm")
    if not bbox:
        return None
    iw, ih = panel["source_size"]
    sx, sy, sw, sh = panel["placement"]["source"]
    dx, dy, dw, dh = panel["placement"]["destination"]
    left, top = max(sx, bbox[0] * iw), max(sy, bbox[1] * ih)
    right, bottom = min(sx + sw, (bbox[0] + bbox[2]) * iw), min(sy + sh, (bbox[1] + bbox[3]) * ih)
    if right <= left or bottom <= top:
        return None
    return [(dx + (left - sx) * dw / sw) / canvas[0], (dy + (top - sy) * dh / sh) / canvas[1],
            (right - left) * dw / sw / canvas[0], (bottom - top) * dh / sh / canvas[1]]
