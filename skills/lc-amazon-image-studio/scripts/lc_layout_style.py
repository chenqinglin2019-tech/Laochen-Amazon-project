"""style_v1: opt-in typographic styling for V3 local layouts (layout.renderer = "style_v1").

The frozen renderer files (lc_layout.py, lc_layout_v3.py, render_layout.mjs) stay
byte-identical, so no existing layout fingerprint moves. install() wraps four
lc_layout attributes; every job without renderer=style_v1 reaches the original
functions unchanged. Style jobs are validated, fingerprinted with this module,
render_layout_style.mjs and the faces they use, and rendered by the forked script.

Per text group ``style`` (every key optional; parts are headline/body/label):
  faces {part: face}            bundled display faces (assets/fonts/faces.json)
  weights {part: int}           must be a weight bundled for that face
  colors {part: #RRGGBB}        per-part ink (glyph contrast is measured per part)
  case {part: none|uppercase}   letter_spacing_em {part: -0.05..0.3}   line_height {part: 0.9..2}
  pill {color, text_color?}     label drawn on a rounded pill
  divider {after: headline|body, color, width_px 1..6 (360px preview), length_em 0..20 (0 = full)}
  surface {radius_em 0..3, border_color?, border_width_px 0..4, shadow bool}  (solid/gradient surfaces)
Non-Latin glyphs fall back to the bundled Noto faces; overflow/contrast/mobile-size rules are unchanged.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import threading
from functools import lru_cache
from pathlib import Path

import lc_layout as core

STYLE_SCRIPT = Path(__file__).with_name("render_layout_style.mjs")
FACES_FILE = core.ASSETS / "fonts" / "faces.json"
PARTS = ("headline", "body", "label")
HEX = re.compile(r"#[0-9A-Fa-f]{6}")
STYLE_KEYS = {"faces", "weights", "colors", "case", "letter_spacing_em", "line_height", "pill", "divider", "surface"}
_ORIGINAL: dict = {}
_LOCK = threading.RLock()


@lru_cache(maxsize=1)
def faces() -> dict:
    return json.loads(FACES_FILE.read_text(encoding="utf-8"))["faces"]


def uses_style(job) -> bool:
    layout = job.get("layout") if isinstance(job, dict) else None
    return isinstance(layout, dict) and layout.get("version") == 3 and layout.get("renderer") == "style_v1"


def _number(value, low, high, where):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise core.LayoutError(f"{where} must be {low}..{high}")


def _hex(value, where):
    if not isinstance(value, str) or not HEX.fullmatch(value):
        raise core.LayoutError(f"{where} must be #RRGGBB")


def _per_part(style, key, check, where):
    values = style.get(key, {})
    if not isinstance(values, dict) or set(values) - set(PARTS):
        raise core.LayoutError(f"{where}.{key} maps headline/body/label only")
    for part, value in values.items():
        check(value, f"{where}.{key}.{part}")


def validate_style(layout) -> None:
    if not isinstance(layout, dict) or layout.get("version") != 3:
        return
    renderer = layout.get("renderer")
    if renderer not in (None, "style_v1"):
        raise core.LayoutError("layout.renderer must be style_v1 when present")
    groups = layout.get("text_groups", [])
    for index, group in enumerate(groups if isinstance(groups, list) else []):
        if not isinstance(group, dict) or "style" not in group:
            continue
        where = f"text_groups[{index}].style"
        style = group["style"]
        if renderer != "style_v1":
            raise core.LayoutError(f"{where} requires layout.renderer=style_v1")
        if not isinstance(style, dict) or set(style) - STYLE_KEYS:
            raise core.LayoutError(f"{where} accepts {sorted(STYLE_KEYS)}")
        registry = faces()

        def face(value, at):
            if value not in registry:
                raise core.LayoutError(f"{at} must be one of {sorted(registry)}")
        _per_part(style, "faces", face, where)

        def weight(value, at):
            part = at.rsplit(".", 1)[1]
            chosen = style.get("faces", {}).get(part)
            if not chosen or str(value) not in registry[chosen]["weights"]:
                raise core.LayoutError(f"{at} must be a bundled weight of the chosen face")
        _per_part(style, "weights", weight, where)
        _per_part(style, "colors", _hex, where)

        def case(value, at):
            if value not in {"none", "uppercase"}:
                raise core.LayoutError(f"{at} must be none/uppercase")
        _per_part(style, "case", case, where)
        _per_part(style, "letter_spacing_em", lambda v, at: _number(v, -.05, .3, at), where)
        _per_part(style, "line_height", lambda v, at: _number(v, .9, 2, at), where)
        if "pill" in style:
            pill = style["pill"]
            if not isinstance(pill, dict) or set(pill) - {"color", "text_color"} or not group.get("label"):
                raise core.LayoutError(f"{where}.pill needs {{color, text_color?}} and label copy")
            _hex(pill.get("color"), f"{where}.pill.color")
            if "text_color" in pill:
                _hex(pill["text_color"], f"{where}.pill.text_color")
        if "divider" in style:
            divider = style["divider"]
            if not isinstance(divider, dict) or set(divider) - {"after", "color", "width_px", "length_em"} \
                    or divider.get("after") not in {"headline", "body"} or not group.get(divider.get("after")):
                raise core.LayoutError(f"{where}.divider needs after=headline|body with that copy present")
            _hex(divider.get("color"), f"{where}.divider.color")
            _number(divider.get("width_px", 2), 1, 6, f"{where}.divider.width_px")
            _number(divider.get("length_em", 0), 0, 20, f"{where}.divider.length_em")
        if "surface" in style:
            surface = style["surface"]
            kind = (group.get("surface") or {}).get("kind", "transparent")
            if not isinstance(surface, dict) or set(surface) - {"radius_em", "border_color", "border_width_px", "shadow"}:
                raise core.LayoutError(f"{where}.surface accepts radius_em/border_color/border_width_px/shadow")
            if kind == "transparent":
                raise core.LayoutError(f"{where}.surface styles a solid/gradient group surface")
            _number(surface.get("radius_em", 0), 0, 3, f"{where}.surface.radius_em")
            _number(surface.get("border_width_px", 0), 0, 4, f"{where}.surface.border_width_px")
            if surface.get("border_width_px"):
                _hex(surface.get("border_color"), f"{where}.surface.border_color")
            if not isinstance(surface.get("shadow", False), bool):
                raise core.LayoutError(f"{where}.surface.shadow must be true/false")


def used_faces(layout) -> list[tuple[str, int]]:
    """(face, weight) pairs this layout renders, nearest bundled weight per part."""
    registry, used = faces(), set()
    for group in layout.get("text_groups", []) if isinstance(layout, dict) else []:
        style = group.get("style") or {}
        for part, face in (style.get("faces") or {}).items():
            if face in registry and group.get(part):
                used.add((face, _weight(face, part, group, layout)))
    return sorted(used)


def _weight(face, part, group, layout):
    explicit = (group.get("style") or {}).get("weights", {}).get(part)
    requested = explicit or {"headline": group.get("headline_weight", layout.get("headline_weight", 600)),
                             "body": group.get("body_weight", layout.get("body_weight", 400)),
                             "label": group.get("label_weight", layout.get("label_weight", 600))}[part]
    return min((int(w) for w in faces()[face]["weights"]), key=lambda w: (abs(w - requested), -w))


def _file_hash(path: Path) -> str:
    return core.file_hash(path)


def rule_hashes(job) -> dict:
    """Code and font dependencies a style job adds to its layout/dispatch bindings."""
    layout = core.resolve_layout_defaults(job)
    result = {name: _file_hash(Path(__file__).with_name(name)) for name in ("lc_layout_style.py", "render_layout_style.mjs")}
    result["faces.json"] = _file_hash(FACES_FILE)
    for face, weight in used_faces(layout):
        entry = faces()[face]["weights"][str(weight)]
        result[f"face:{face}:{weight}"] = entry["sha256"]
    return result


def layout_fingerprint(manifest, job, base=None):
    original = _ORIGINAL["layout_fingerprint"](manifest, job, base)
    if not uses_style(job):
        return original
    payload = json.dumps({"core": original, "style_v1": rule_hashes(job)}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def validate_layout_v3(layout):
    _ORIGINAL["validate_layout_v3"](layout)
    validate_style(layout)


@lru_cache(maxsize=32)
def _face_uri(path: str, digest: str) -> str:
    return "data:font/woff2;base64," + base64.b64encode(Path(path).read_bytes()).decode()


def _resolved_style(group, layout, scale):
    style = group.get("style") or {}
    registry = faces()
    resolved = {key: dict(style.get(key, {})) for key in ("colors", "case", "letter_spacing_em", "line_height")}
    resolved["faces"], resolved["weights"] = {}, {}
    for part, face in (style.get("faces") or {}).items():
        resolved["faces"][part] = f'"LCFace_{face}"'
        resolved["weights"][part] = _weight(face, part, group, layout)
        resolved.setdefault("generic", {})[part] = registry[face]["generic"]
    if style.get("pill"):
        resolved["pill"] = {"color": style["pill"]["color"],
                            "text_color": style["pill"].get("text_color", style.get("colors", {}).get("label"))}
    if style.get("divider"):
        divider = style["divider"]
        resolved["divider"] = {"after": divider["after"], "color": divider["color"],
                               "width_px": max(1, divider.get("width_px", 2) * scale),
                               "length_em": divider.get("length_em", 0)}
    if style.get("surface"):
        surface = style["surface"]
        resolved["surface"] = {"radius_em": surface.get("radius_em", 0), "shadow": surface.get("shadow", False),
                               "border_width_px": surface.get("border_width_px", 0) * scale,
                               "border_color": surface.get("border_color")}
    return resolved


class _StyleSubprocess:
    """Routes the renderer invocation of lc_layout.render_batch to the forked script."""

    def __getattr__(self, name):
        return getattr(subprocess, name)

    @staticmethod
    def run(args, **kwargs):
        args = list(args)
        args[1] = str(STYLE_SCRIPT)
        return subprocess.run(args, **kwargs)


def _render_styled(manifest, base, jobs, measure_only):
    needed: set = set()
    prepare, font_payload = _ORIGINAL["_prepare_job"], _ORIGINAL["_font_payload"]

    def styled_prepare(manifest_, base_, job):
        prepared = prepare(manifest_, base_, job)
        layout = core.resolve_layout_defaults(job)
        scale = prepared["geometry"]["canvas"][0] / 360
        for group, source in zip(prepared.get("text_groups", []), layout.get("text_groups", [])):
            group["style"] = _resolved_style(source, layout, scale)
        needed.update(used_faces(layout))
        prepared["renderer"] = "style_v1"
        return prepared

    def styled_fonts(*args, **kwargs):
        fonts, missing = font_payload(*args, **kwargs)
        for face, weight in sorted(needed):
            entry = faces()[face]["weights"][str(weight)]
            path = core.ASSETS / "fonts" / entry["file"]
            if _file_hash(path) != entry["sha256"]:
                raise core.LayoutError(f"Bundled face hash mismatch: {entry['file']}")
            fonts.append({"family": f"Face_{face}", "weight": weight, "uri": _face_uri(str(path), entry["sha256"])})
        return fonts, missing

    with _LOCK:
        saved = (core._prepare_job, core._font_payload, core.subprocess)
        core._prepare_job, core._font_payload, core.subprocess = styled_prepare, styled_fonts, _StyleSubprocess()
        try:
            return _ORIGINAL["render_batch"](manifest, base, jobs, measure_only=measure_only)
        finally:
            core._prepare_job, core._font_payload, core.subprocess = saved


def render_batch(manifest, base, jobs, *, measure_only=False):
    plain = [job for job in jobs if not uses_style(job)]
    styled = [job for job in jobs if uses_style(job)]
    results = {}
    if plain:
        results.update(_ORIGINAL["render_batch"](manifest, base, plain, measure_only=measure_only))
    if styled:
        results.update(_render_styled(manifest, base, styled, measure_only))
    return results


def discover_runtime():
    """Windows Chrome for Testing builds often print nothing for `--version`.

    The frozen discovery then reports the pinned browser as missing although it is
    there. Only in that exact case, accept the browser when the verified bootstrap
    matcher (version manifest / Playwright revision) confirms it.
    """
    import os
    result = _ORIGINAL["_discover_runtime"]()
    chromium_errors = [e for e in result["errors"] if e.startswith("Pinned Chromium")]
    candidate = os.environ.get("LC_LAYOUT_CHROMIUM")
    if result["passed"] or not chromium_errors or not candidate or not Path(candidate).is_file():
        return result
    try:
        from runtime_bootstrap import RuntimeBootstrap
        matched = RuntimeBootstrap()._chromium_matches(candidate, result.get("modules"))
    except Exception:  # noqa: BLE001 - keep the original diagnosis
        return result
    if matched:
        result["errors"] = [e for e in result["errors"] if e not in chromium_errors]
        result.update(chromium=candidate, passed=not result["errors"], chromium_detection="manifest_or_revision")
    return result


def install():
    """Idempotent. Imported by lc_image_pipeline so every CLI path routes style jobs."""
    if _ORIGINAL:
        return
    for name in ("render_batch", "layout_fingerprint", "validate_layout_v3", "_prepare_job", "_font_payload", "_discover_runtime"):
        _ORIGINAL[name] = getattr(core, name)
    core.render_batch = render_batch
    core.layout_fingerprint = layout_fingerprint
    core.validate_layout_v3 = validate_layout_v3
    core._discover_runtime = discover_runtime


install()
