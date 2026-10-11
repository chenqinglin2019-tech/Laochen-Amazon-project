"""One-shot prompt compiler (V8): template + the agent's plan -> a finished-image prompt.

The image model draws the complete designed image (photo + text) in one call, so the
prompt states: the product identity (attached photos first), the layout in plain words,
the look and typography from the chosen template (or the agent's custom design), the
exact copy (numbered, quoted, nothing else), and the guardrails. The main image gets
its own prompt: one product on a flat backdrop chosen for an easy, exact cut-out
(replaced with pure white locally), no shadow, no text.

V8.1 no-copy rules: product photos count only for the product (never their person or
setting); a reference reaches the model only as an opted-in, blurred colour-and-light
board; people are a newly cast model (plan.json cast), and later images of the set get
the set's first model image as an identity reference, added at reservation time.
"""
from __future__ import annotations

import re

from lc_frame_fit import canvas_to_frame, plan as frame_plan

TYPE_WORDS = {"noto_sans": "clean sans-serif", "noto_serif": "classic serif", "montserrat": "geometric sans-serif",
              "poppins": "rounded geometric sans-serif", "oswald": "condensed bold sans-serif",
              "bebas_neue": "tall condensed capitals", "nunito": "soft rounded sans-serif",
              "libre_baskerville": "elegant book serif", "pacifico": "brush script", "sans": "clean sans-serif",
              "serif": "classic serif"}
WEIGHT_WORDS = {300: "light", 400: "regular", 500: "medium", 600: "semibold", 700: "bold", 800: "extra bold", 900: "black"}
RECIPE_WORDS = {"photo_overlay": "one photograph fills the frame; the text block sits on a calm area of it",
                "header_footer": "a title band at the top, the photograph in the middle, short labels along the bottom",
                "photo_sidebar": "the photograph on one side, a clean text column on the other",
                "scene_grid": "a small grid of related scenes with short captions under one title",
                "detail_callouts": "the product large, with small labels joined by thin leader lines to the parts they name",
                "steps": "numbered steps side by side under one title, each with a short caption",
                "none": "a clean photograph without text"}
CALLOUT_WORDS = {"detail_callouts": "small labels with thin leader lines pointing to the parts they name",
                 "header_footer": "short labels in a neat row along the bottom",
                 "photo_sidebar": "a short list in the text column, each item with a small simple icon",
                 "scene_grid": "one short caption under each scene", "steps": "numbered step captions in order",
                 "photo_overlay": "a short list under the subline"}
INTERNAL = re.compile(r"[^.]*\b(container|containers|target|measured|mask|approved copy|360[- ]?(pixel|px)|module|"
                      r"text_mode|local (overlay|text)|deterministic|rendered locally|base photograph)\b[^.]*\.?", re.I)
PEOPLE_LINES = {False: "People: none - no people, faces, hands or body parts.",
                "hands": "People: only realistic adult hands where the action needs them; no faces."}
PERSON_LINE = ("People: {cast}. An original adult model created for this set: never a person from the product photos{tone}, "
               "nor any real or famous person; natural poses; the product stays the hero.")
PERSON_FALLBACK = "a realistic adult model whose face, hair and styling are your own invention"
HANDS_CAST_LINE = ("People: only realistic adult hands where the action needs them, consistent with this set's model "
                   "({cast}); no faces.")
PRODUCT_ONLY = ("Use the product photos only for the product itself: ignore their background, setting, props and any "
                "person in them.")
HIDDEN_NOTE = " Blurred patches in it hide a person or unrelated items; leave them out."
TONE_LINE = ("Image {n} - colour and light reference only (a smooth colour field, not a scene): take just its overall "
             "colour tone, brightness and light direction; invent your own setting, objects and people. The photograph "
             "itself must be sharp and fully detailed.")
TONE_COLOURS = " Main colours of that reference, to use as accents: {colours}."
IDENTITY_LINE = ("Image {n} - this set's model, from an earlier image of the set: show exactly this same person (face, "
                 "hairstyle, hair colour, skin tone, build); pose, expression and framing follow this scene. Take only "
                 "the person from it - not its background, product placement, layout or text.")
# User templates lend only tone, light and photography feel; their background, props and surface
# describe someone else's scene and are never used.
USER_LOOK_KEYS = ("lighting", "color_grade", "camera", "depth_of_field", "mood", "negative_space",
                  "product_placement", "product_scale")
PEOPLE_WORDS = re.compile(
    r"\b(person|persons|people|model|models|woman|women|man|men|girl|girls|boy|boys|lady|ladies|guy|guys|child|children|"
    r"kid|kids|baby|babies|toddler\w*|teen\w*|adult|adults|mother|father|mom|mum|dad|parent\w*|family|couple|friends?|"
    r"bride|groom|someone|somebody|customer|user|she|he|her|his|him|face|faces|hands?|arms?|fingers?|"
    r"skin(?![ -]?care)|hair(?![ -]?(dryer|drier|brush|comb|clip|tie|band|care|oil|spray|straightener|curler|iron))|"
    r"portrait|selfie|smil\w*|pos(e|es|ed|ing)|wear(s|ing)?|worn)\b", re.I)


# ---------------------------------------------------------------- words for boxes and frames

def pct(box):
    x, y, w, h = box
    return f"x {x * 100:.0f}-{(x + w) * 100:.0f}%, y {y * 100:.0f}-{(y + h) * 100:.0f}%"


def where(box):
    x, y, w, h = box
    cx, cy = x + w / 2, y + h / 2
    vertical = "top" if cy < 0.4 else "bottom" if cy > 0.6 else "middle"
    horizontal = "left" if cx < 0.4 else "right" if cx > 0.6 else "centre"
    if w >= 0.7:
        return f"full-width {vertical} band"
    if h >= 0.6:
        return f"tall {horizontal} column"
    if vertical == "middle" and horizontal == "centre":
        return "central area"
    return f"{'upper' if vertical == 'top' else 'lower' if vertical == 'bottom' else 'middle'}-{horizontal} area"


def shape_of(canvas):
    width, height = canvas
    return "portrait" if height / width > 1.12 else "wide" if width / height > 1.05 else "square"


def frame_lines(canvas):
    frame = frame_plan(canvas)
    width, height = canvas
    if frame["exact"]:
        return frame, [f"Frame: {frame['orientation']} {frame['frame']} ({frame['size']} if the tool takes a size); the whole "
                       f"frame is the final {width} x {height} image."]
    band = frame["band"]
    if band[3] < 1:
        cut = band[1] * 100
        where_text = (f"only the middle strip from {band[1] * 100:.0f}% to {(band[1] + band[3]) * 100:.0f}% of the height "
                      f"becomes the final {width} x {height} image; the top and bottom {cut:.0f}% are cut off")
    else:
        cut = band[0] * 100
        where_text = (f"only the middle strip from {band[0] * 100:.0f}% to {(band[0] + band[2]) * 100:.0f}% of the width "
                      f"becomes the final {width} x {height} image; the left and right {cut:.0f}% are cut off")
    return frame, [f"Frame: {frame['orientation']} {frame['frame']} ({frame['size']} if the tool takes a size). Important: "
                   f"{where_text}. Put the product, every word of text and any graphics inside that strip, at least 3% "
                   "from its edges; fill the cut areas only with plain continuing background."]


def _clean(text, limit=260):
    text = INTERNAL.sub("", re.sub(r"\s+", " ", str(text or ""))).strip()
    return (text[:limit - 1] + "…") if len(text) > limit else text


def _first(text, limit=200):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return _clean(re.split(r"(?<=[.;])\s", text, maxsplit=1)[0], limit).rstrip(" ;,.")


def _typeface(face, weight=None, case=None, spacing=None):
    words = [WEIGHT_WORDS.get(int(weight), "") if weight else "", TYPE_WORDS.get(str(face), str(face or "sans-serif"))]
    if case == "uppercase":
        words.append("in capitals")
    if spacing and float(spacing) >= 0.1:
        words.append("with wide letter-spacing")
    return " ".join(word for word in words if word)


# ---------------------------------------------------------------- template snapshots -> design

def design_from_template(source, family, template, slot):
    """A neutral design dict used by the compiler (layout/look/typography/scene/avoid/plate)."""
    canvas = slot["canvas"]
    shape = shape_of(canvas)
    frame = frame_plan(canvas)
    band = frame["band"]
    design = {"source": source, "template": template["id"], "family": family["id"] if family else None,
              "recipe": template.get("recipe") or "photo_overlay"}
    if source == "builtin":
        layout = template.get("layout") or {}
        variant = (layout.get("canvas_variants") or {}).get(shape) or {}
        text_box = variant.get("text_group_box") or layout.get("text_group_box")
        product_box = variant.get("product_region_norm") or layout.get("product_region_norm")
        generation = template.get("generation") or {}
        style = (family or {}).get("style") or {}
        lines = []
        if product_box:
            mapped = canvas_to_frame(product_box, band)
            lines.append(f"Product: {where(mapped)}, {pct(mapped)}; large, sharp and fully visible.")
        if text_box:
            mapped = canvas_to_frame(text_box, band)
            calm = _first(generation.get("reserved_space"), 120)
            lines.append(f"Text block: {where(mapped)}, {pct(mapped)}, over a calm, low-detail area"
                         + (f" ({calm.rstrip('.')})" if calm else "") + "; keep the product and props out of it.")
        note = re.sub(r"^(Square|Portrait|Wide A\+|Wide) composition:\s*", "", _first(variant.get("composition_note"), 190))
        if note:
            lines.append(f"Composition: {note}")
        design["layout"] = lines
        # The template's generic background yields to the agent's own scene (see compile_secondary).
        design["background"] = _clean(generation.get("background"), 200)
        design["look"] = [part for part in (
            _clean(generation.get("lighting"), 200),
            _clean(generation.get("focus"), 200), "Palette: " + _first(style.get("palette"), 160) if style.get("palette") else "",
            "Photography: " + _first(style.get("photography"), 160) if style.get("photography") else "",
            "Graphics: " + _first(style.get("graphics"), 140) if style.get("graphics") else "") if part]
        ink = layout.get("text_color")
        family_face = "serif" if layout.get("headline_family") == "serif" else "sans"
        design["typography"] = {
            "headline": _typeface(family_face, layout.get("headline_weight")) + (f", colour {ink}" if ink else ""),
            "body": _typeface("sans", 400) + (f", colour {ink}" if ink else ""),
            "align": layout.get("align"),
            "surface": (layout.get("text_surface") or {}).get("color") if (layout.get("text_surface") or {}).get("kind") == "solid" else None}
        # The family's typography sentence names fonts the model cannot use and can contradict the
        # template's own headline face; the per-line typefaces above are authoritative.
        design["scene"] = _clean(template.get("scene_default"), 200)
        avoid = [item for item in list((family or {}).get("avoid") or []) + list(template.get("avoid") or [])
                 if not re.search(r"text_mode|approved|product identity|evidence|protection region|hidden (geometry|structure)|"
                                  r"safe-use|\bsources?\b|\bsamples?\b|reference|\bverified\b|current project|rejected|"
                                  r"establish", item, re.I)]
        design["avoid"] = list(dict.fromkeys(_clean(item, 140) for item in avoid))[:3]
        design["plate"] = None
        return design
    # The user's own (V2) template.
    tokens = (family or {}).get("tokens") or {}
    names = tokens.get("palette_names") or {}
    palette = ", ".join(f"{role} {value}" + (f" ({names[role]})" if names.get(role) else "")
                        for role, value in (tokens.get("palette") or {}).items())
    generation = template.get("generation") or {}
    photo = tokens.get("photography") or {}
    look = []
    for key in USER_LOOK_KEYS:
        value = generation.get(key)
        text = without_people(_clean(value, 160)) if value and not isinstance(value, (list, dict)) else ""
        if text:
            look.append(f"{key.replace('_', ' ').capitalize()}: {text}.")
    photo_text = without_people("; ".join(str(value) for value in photo.values())) if photo else ""
    design["look"] = [line for line in (f"Colours: {palette}." if palette else "", *look,
                                        f"Photography: {photo_text}." if photo_text else "") if line]
    observed = template.get("observed_shape") == shape
    layout = template.get("layout") or {}
    lines = []
    product_box = layout.get("product_region_norm")
    if product_box and observed:
        mapped = canvas_to_frame(product_box, band)
        lines.append(f"Product: {where(mapped)}, {pct(mapped)}; large, sharp and fully visible.")
    design["groups"] = []
    fonts = tokens.get("fonts") or {}
    palette_values = tokens.get("palette") or {}
    for group in layout.get("text_groups", []):
        font = fonts.get(group.get("font_role"), {})
        colour = palette_values.get(group.get("color_role"))
        description = _typeface(font.get("face"), font.get("weight"), group.get("case") or font.get("case"),
                                group.get("letter_spacing_em") or font.get("letter_spacing_em"))
        if colour:
            description += f", colour {colour}"
        if group.get("size"):
            description += f", about {group['size'] / 360 * 100:.0f}% of the image width tall"
        if (group.get("pill") or {}).get("color_role") in palette_values:
            description += f", on a rounded {palette_values[group['pill']['color_role']]} pill"
        if (group.get("divider") or {}).get("color_role") in palette_values:
            description += f", with a short {palette_values[group['divider']['color_role']]} divider line"
        place = ""
        if group.get("box") and observed:
            mapped = canvas_to_frame(group["box"], band)
            place = f"{where(mapped)}, {pct(mapped)}"
        design["groups"].append({"role": group.get("role"), "style": description, "where": place,
                                 "align": group.get("align")})
    design["layout"] = lines
    design["typography"] = {}
    design["scene"] = ""          # the agent writes an original scene (plan.json scene is required here)
    design["avoid"] = [_clean(item, 140) for item in ((family or {}).get("avoid") or [])][:3]
    design["plate"] = (template.get("assets") or {}).get("plate_sha256")
    return design


def design_custom(entry, plan_style):
    design = entry.get("design") or {}
    return {"source": "custom", "template": "custom", "family": None, "recipe": "custom",
            "layout": [f"Layout: {design['layout']}"] if design.get("layout") else [],
            "look": [line for line in (design.get("style") and f"Style: {design['style']}",
                                       plan_style and f"Set style: {plan_style}") if line],
            "typography": {"note": design.get("typography")} if design.get("typography") else {},
            "scene": "", "avoid": [], "plate": None}


# ---------------------------------------------------------------- compiler

def _product_lines(product):
    parts = [product["name"], product["look"], product.get("scale")]
    lines = ["Product: " + " ".join(part.rstrip(" .") + "." for part in parts if part)]
    if product.get("keep"):
        lines.append("Must stay visible and correct: " + "; ".join(product["keep"]) + ".")
    lines.append("Show the product exactly as in the product photos: same shape, proportions, colours, materials, parts, "
                 "count and printed details; do not add, remove or redesign anything.")
    return lines


def _input_lines(photos, tone_path, tone_colours=()):
    lines = ["Input images (in order):"]
    for index, photo in enumerate(photos, 1):
        hidden = HIDDEN_NOTE if photo.get("hidden") else ""
        if photo.get("role") == "detail":
            lines.append(f"Image {index} - product detail photo: the exact look of this detail.{hidden}")
        else:
            lines.append(f"Image {index} - product photo, {photo.get('view', 'view')}: the actual product. Match its shape, "
                         f"proportions, colours, materials and printed details exactly.{hidden}")
    if tone_path:
        lines.append(TONE_LINE.format(n=len(photos) + 1)
                     + (TONE_COLOURS.format(colours=", ".join(tone_colours)) if tone_colours else ""))
    lines.append(PRODUCT_ONLY)
    return lines


def people_line(value, cast, tone=False):
    """The People line: none, hands, or the set's newly cast model."""
    if value in ("person", True):
        return PERSON_LINE.format(cast=(cast or PERSON_FALLBACK).strip().rstrip("."),
                                  tone=" or the colour reference" if tone else "")
    if value == "hands":
        return HANDS_CAST_LINE.format(cast=cast.strip().rstrip(".")) if cast else PEOPLE_LINES["hands"]
    return PEOPLE_LINES[False]


def without_people(text):
    """Drop every clause that mentions a person (template texts describe someone else's photo)."""
    kept = []
    for sentence in re.split(r"(?<=[.;])\s+", str(text or "").strip()):
        clauses = [clause.strip(" ;.") for clause in sentence.split(",")]
        clauses = [clause for clause in clauses if clause and not PEOPLE_WORDS.search(clause)]
        if clauses:
            kept.append(", ".join(clauses))
    return "; ".join(kept)


def with_identity(prompt, number):
    """Insert the identity line as Image `number` after the last input image line (once)."""
    lines = prompt.split("\n")
    if "Input images (in order):" not in lines or any(line.startswith("Image ") and "this set's model" in line for line in lines):
        return prompt
    start = lines.index("Input images (in order):")
    last = start
    for index in range(start + 1, len(lines)):
        if not lines[index].startswith("Image "):
            break
        last = index
    lines.insert(last + 1, IDENTITY_LINE.format(n=number))
    return "\n".join(lines)


def _text_lines(copy, design):
    if not copy:
        return ["Text: none - no words, letters, numbers, logos or captions anywhere in the image."]
    typography = design.get("typography") or {}
    groups = list(design.get("groups") or [])
    by_role = {}
    for group in groups:
        by_role.setdefault(group.get("role"), []).append(group)
    lines = ["Text - render exactly these words, each once, and no other text:"]
    number = 0

    def take(role):
        pool = by_role.get(role) or []
        return pool.pop(0) if pool else None

    entries = []
    if copy.get("eyebrow"):
        entries.append(("Eyebrow", copy["eyebrow"], take("eyebrow"), "small, above the headline"))
    if copy.get("headline"):
        entries.append(("Headline", copy["headline"], take("headline"), "the largest text"))
    if copy.get("subline"):
        entries.append(("Subline", copy["subline"], take("body"), "about half the headline size, below it"))
    for index, item in enumerate(copy.get("callouts") or [], 1):
        group = take("label") or take("feature") or take("badge")
        entries.append((f"Callout {index}", item, group, CALLOUT_WORDS.get(design.get("recipe"), "short label")))
    for label, words, group, default in entries:
        number += 1
        if group:
            style = group["style"] + (f", {group['where']}" if group.get("where") else "") + (
                f", {group['align']}-aligned" if group.get("align") else "")
        elif label == "Headline" and typography.get("headline"):
            style = typography["headline"] + (f", {typography['align']}-aligned" if typography.get("align") else "")
        elif label in {"Subline", "Eyebrow"} and typography.get("body"):
            style = typography["body"]
        else:
            style = default
        lines.append(f'{number}. {label}: "{words}" - {style}.')
    if typography.get("surface"):
        lines.append(f"Place the text on a clean solid {typography['surface']} panel.")
    if typography.get("note"):
        lines.append(f"Typography style: {typography['note'].rstrip(' ;,.')}.")
    lines.append("Typography: spell every word exactly as given (case, punctuation, numbers); only line breaks may change. "
                 "Crisp, evenly spaced letters with strong contrast against their background, all text at least 4% inside "
                 "the edges and legible when the image is shown 360 px wide. No logos, badges, prices, ratings, "
                 "watermarks or extra captions.")
    return lines


def compile_secondary(project, plan, slot, entry, design, photos, tone_path=None, tone_colours=()):
    """Full prompt text and its reference order for one secondary / A+ image."""
    product = plan["product"]
    frame, frame_text = frame_lines(slot["canvas"])
    role = slot["role"].replace("a_plus_", "").replace("_", " ")
    lines = [f"Create one finished Amazon {'A+ module' if slot['kind'] == 'a_plus' else 'listing'} image "
             f"({role}, {shape_of(slot['canvas'])}): a photorealistic product photograph with the marketing text "
             "designed into it, ready to publish.",
             *_input_lines(photos, tone_path, tone_colours), *_product_lines(product),
             f"Message: {entry['message']}"]
    scene = entry.get("scene") or design.get("scene")
    if scene:
        lines.append(f"Scene: {scene}")
    lines.append(people_line(entry.get("people", False), plan.get("cast"), bool(tone_path)))
    arrangement = RECIPE_WORDS.get(design.get("recipe"))
    layout = list(design.get("layout") or [])
    if layout or arrangement:
        lines.append("Layout (x from the left, y from the top):")
        if arrangement and design.get("recipe") != "custom":
            lines.append(f"- Arrangement: {arrangement}.")
        lines.extend(f"- {item}" for item in layout)
    look = ([design["background"]] if design.get("background") and not entry.get("scene") else []) + list(design.get("look") or [])
    if look:
        lines.append("Look: " + " ".join(part.rstrip(" ;,.") + "." for part in look))
    if entry.get("direction"):
        lines.append(f"Art direction: {entry['direction']}")
    lines.extend(_text_lines(entry.get("copy") or {}, design))
    avoid = ["brands, text, claims, people or settings from the product photos" + (" or the colour reference" if tone_path else ""),
             "extra product units", "distorted proportions", "clutter hiding the product"] + list(design.get("avoid") or [])
    lines.append("Avoid: " + "; ".join(dict.fromkeys(item.rstrip(" ;,.") for item in avoid)) + ".")
    lines.extend(frame_text)
    return "\n".join(lines) + "\n", frame


def compile_main(project, plan, slot, photos, *, backdrop_hex, backdrop_name, view=None, corrections=()):
    product = plan["product"]
    frame, frame_text = frame_lines(slot["canvas"])
    white = backdrop_name == "white"
    lines = ["Create the MAIN Amazon product image: a clean studio packshot of the actual product.",
             *_input_lines(photos, None), *_product_lines(product)]
    if view:
        lines.append(f"View: {view}.")
    else:
        lines.append("View: the most recognisable angle, as in Image 1.")
    if white:
        lines.append("Backdrop: seamless pure white (#FFFFFF), perfectly flat edge to edge: no floor line, horizon, "
                     "gradient, vignette, texture or reflection.")
    else:
        lines.append(f"Backdrop: perfectly flat, uniform neutral grey ({backdrop_hex}) filling the whole frame edge to edge "
                     "(it is replaced with pure white afterwards): no floor line, horizon, gradient, vignette, texture or "
                     "reflection.")
    lines += ["Shadows: none at all - no contact shadow, drop shadow, reflection or glow; shadowless light-tent lighting; "
              "the product floats.",
              "Framing: the whole product centred, filling about 80% of the frame, clear space on every side; nothing "
              "touches or crosses the frame edge.",
              "Lighting: soft, even, high-key studio light that shows the true colours and materials.",
              "Nothing else: no text, logos (other than those printed on the product), badges, props, hands, people or "
              "packaging unless the product photos show it as part of the product."]
    for correction in corrections:
        lines.append(f"Correction - the previous attempt had this problem: {correction}. Fix it; keep everything else.")
    lines.extend(frame_text)
    return "\n".join(lines) + "\n", frame


def redo_prompt(base_prompt, reason):
    return base_prompt.rstrip("\n") + (f"\nCorrection - the previous attempt had this problem: {reason}. "
                                       "Fix it; keep everything else as specified.\n")
