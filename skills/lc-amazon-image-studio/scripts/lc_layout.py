#!/usr/bin/env python3
"""Offline Amazon image typography. Geometry uses normalized [x,y,width,height].

render_batch() consumes full-canvas text-free job.layout_input images. It never
resizes products or calls a generation service. A failed check is review material,
not a deliverable. Run this module with --doctor for the pinned runtime preflight.
"""
from __future__ import annotations
import argparse
import base64
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import time
from typing import Any
from PIL import Image, __version__ as PILLOW_VERSION

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
TEMPLATES = {"scene", "split", "benefits", "detail", "dimensions", "components"}
# Keep the legacy font set separate from v2 resources.  In particular, adding a
# new optional display face must not invalidate v1 layout fingerprints.
FONT_FILES = {"Latin": ["NotoSans-Regular.ttf", "NotoSans-Bold.ttf"],
              "Arabic": ["NotoSansArabic-Regular.ttf", "NotoSansArabic-Bold.ttf"],
              "CJK": ["NotoSansCJKsc-Regular.otf", "NotoSansCJKsc-Bold.otf"]}
V2_SANS_FONT_FILES = {"Latin": {400: "NotoSans-Regular.ttf", 600: "NotoSans-Bold.ttf"},
                      "Arabic": {400: "NotoSansArabic-Regular.ttf", 600: "NotoSansArabic-Bold.ttf"},
                      "CJK": {400: "NotoSansCJKsc-Regular.otf", 600: "NotoSansCJKsc-Bold.otf"}}
V2_SERIF_FONT_FILES = {400: "NotoSerif-Regular.ttf", 600: "NotoSerif-SemiBold.ttf"}
V2_MOBILE_DEFAULTS = {"headline": 24, "body": 12, "label": 12}
V2_MOBILE_FLOORS = {"headline": 18, "body": 12, "label": 12}

class LayoutError(ValueError):
    pass

def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()

def file_hash(path: Path) -> str:
    # Reuse only the caller's bounded command/snapshot context. A process-wide
    # mtime/size cache can conceal same-size file replacement between commands.
    from lc_assets import file_hash as hash_asset
    return hash_asset(path)

def _project_file(base: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute() or "://" in value:
        raise LayoutError("Image paths must be nonempty project-relative local paths")
    path = (base / value).resolve()
    if not path.is_relative_to(base.resolve()) or not path.is_file():
        raise LayoutError(f"Missing or out-of-project image: {value}")
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise LayoutError("Only PNG/JPEG/WebP raster inputs are supported")
    return path

def _box(value: Any, label: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise LayoutError(f"{label} must be normalized [x,y,width,height]")
    if any(isinstance(v, bool) or not isinstance(v, (int,float)) or not math.isfinite(v) for v in value):
        raise LayoutError(f"{label} must have finite numeric coordinates")
    x,y,w,h = value
    if min(x,y) < 0 or min(w,h) <= 0 or x+w > 1.00001 or y+h > 1.00001:
        raise LayoutError(f"{label} lies outside the canvas")
    return list(value)

def _point(value: Any, label: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise LayoutError(f"{label} must be normalized [x,y]")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in value):
        raise LayoutError(f"{label} must have normalized finite coordinates")
    return list(value)

def _layout_version(layout: dict) -> int:
    version = layout.get("version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version not in {1, 2, 3}:
        raise LayoutError("layout.version must be 1, 2 or 3")
    return version


def resolve_layout_defaults(job: dict) -> dict:
    from lc_layout_v3 import resolve_layout_defaults as resolve
    try:
        return resolve(job)
    except ValueError as exc:
        raise LayoutError(str(exc)) from exc

def _v2_variant(width: int, height: int) -> str:
    if height / width > 1.12:
        return "portrait"
    if width / height > 1.35:
        return "wide"
    return "square"

def _v2_defaults(variant: str, template: str) -> tuple[list[float], list[float]]:
    """Generic v2 defaults; project layouts can always supply text_group.box."""
    defaults = {
        "square": ([.07, .07, .86, .27], [.08, .39, .84, .53]),
        "portrait": ([.07, .06, .86, .23], [.08, .34, .84, .59]),
        "wide": ([.07, .20, .42, .56], [.55, .12, .38, .76]),
    }
    group, product = defaults[variant]
    if template == "detail":
        detail_defaults = {
            "square": ([.06, .08, .36, .28], [.07, .42, .50, .49]),
            "portrait": ([.07, .06, .42, .24], [.07, .36, .50, .56]),
            "wide": ([.06, .18, .31, .54], [.43, .12, .27, .76]),
        }
        group, product = detail_defaults[variant]
    return list(group), list(product)

def _v2_default_item_slot(template: str, index: int, count: int, variant: str,
                          width: int, height: int) -> dict:
    """Return only a generic slot; absent slots flow through the content group."""
    ratio = width / height
    if template == "detail":
        if variant == "wide":
            x, y, text_width = .75, .15 + index * .36, .19
        elif variant == "portrait":
            x, y, text_width = .63, .39 + index * .24, .29
        else:
            x, y, text_width = .63, .37 + index * .24, .29
        image_height = .13 * ratio
        return {"box": [x, y, text_width, min(.23, image_height + .09)],
                "image": [x, y, .13, image_height],
                "text": [x, y + image_height + .012, text_width, .08]}
    if template in {"benefits", "components", "dimensions"}:
        cell = .9 / max(1, count)
        x = .05 + index * cell
        slot = {"box": [x, .82, cell - .025, .13], "text": [x, .84, cell - .025, .09]}
        if template == "benefits":
            slot["icon"] = [x, .775, .04, .04 * ratio]
        elif template == "components":
            slot["number"] = [x, .84, .04, .09]
            slot["text"] = [x + .055, .84, cell - .08, .09]
        return slot
    return {}

def _v2_item_slots(layout: dict, template: str, variant: str, width: int, height: int) -> tuple[list[dict], list[dict]]:
    items = layout.get("items") or []
    slots, lines = [], []
    for index, item in enumerate(items):
        default = _v2_default_item_slot(template, index, len(items), variant, width, height)
        waypoints = [_point(point, f"items[{index}].leader_waypoints[{waypoint_index}]")
                     for waypoint_index, point in enumerate(item.get("leader_waypoints", []))]
        box = _box(item["box"], f"items[{index}].box") if item.get("box") is not None else default.get("box")
        image = _box(item["image_box"], f"items[{index}].image_box") if item.get("image_box") is not None else default.get("image")
        text = _box(item["text_box"], f"items[{index}].text_box") if item.get("text_box") is not None else default.get("text")
        if box is not None and item.get("image") and image is None:
            image = box
        if box is not None and item.get("text") and not item.get("image") and text is None:
            text = box
        slot = {"box": box, "image": image, "text": text,
                "image_shape": item.get("image_shape", "rect"),
                "align": item.get("align"), "leader_waypoints": waypoints}
        for name in ("icon", "number"):
            if name == "number" and item.get("image"):
                continue
            configured = item.get(name + "_box", default.get(name))
            if configured is not None:
                slot[name] = _box(configured, f"items[{index}].{name}_box")
        slots.append(slot)
        if template == "detail" and image is not None and item.get("target") is not None:
            target = _point(item["target"], f"detail item[{index}].target")
            cx, cy = image[0] + image[2] / 2, image[1] + image[3] / 2
            next_point = waypoints[0] if waypoints else target
            start = [image[0] if next_point[0] < cx else image[0] + image[2], cy]
            lines.append({"id": f"leader-{index}", "points": [start, *waypoints, target], "target": target,
                          "waypoints": waypoints, "source_item": index, "source_evidence_id": f"evidence-{index}", "thin": True})
        elif template == "dimensions":
            axis = item.get("axis", "horizontal" if index == 0 else "vertical")
            if axis not in {"horizontal", "vertical"}:
                raise LayoutError("dimension axis must be horizontal or vertical")
            points = item.get("dimension_points", [[.23, .78], [.82, .78]] if axis == "horizontal" else [[.19, .36], [.19, .76]])
            if not isinstance(points, list) or len(points) != 2:
                raise LayoutError("dimension_points must contain two normalized endpoints")
            lines.append({"id": f"dimension-{index}", "points": [_point(point, "dimension endpoint") for point in points], "arrow": True})
    return slots, lines

def _layout_geometry_v2(job: dict, layout: dict, width: int, height: int, template: str) -> dict:
    variant = _v2_variant(width, height)
    default_group, product = _v2_defaults(variant, template)
    configured_group = layout.get("text_group") or {}
    group = _box(configured_group["box"], "text_group.box") if configured_group.get("box") is not None else default_group
    slots, lines = _v2_item_slots(layout, template, variant, width, height)
    text_zones = [group] + [slot["text"] for slot in slots if slot.get("text")]
    return {"template": template, "version": 2, "variant": variant, "canvas": [width, height],
            "safe_margin": .05, "product_zone": product, "headline": group, "body": group,
            "text_group": group, "text_zones": text_zones, "image_region_norm": product,
            "product_region_norm": product, "text_regions_norm": text_zones,
            "items": slots, "lines": lines}

def layout_geometry(job: dict) -> dict:
    """Single source of truth for generation reservations and rendered positions."""
    width,height = job.get("canvas", [2000,2000])
    if any(isinstance(v,bool) or not isinstance(v,int) for v in [width,height]) or min(width,height) <= 0 or max(width,height)>10000:
        raise LayoutError("canvas must contain positive integer dimensions <= 10000")
    portrait = height/width > 1.12
    layout = resolve_layout_defaults(job)
    if not isinstance(layout, dict):
        raise LayoutError("layout must be an object")
    version = _layout_version(layout)
    name = layout.get("template", "scene")
    if name not in TEMPLATES:
        raise LayoutError(f"Unknown layout template: {name}")
    if job.get("kind") == "main":
        return {"template":"main","canvas":[width,height],"product_zone":[.075,.075,.85,.85],"text_zones":[],"image_region_norm":[.075,.075,.85,.85],"product_region_norm":[.075,.075,.85,.85],"text_regions_norm":[],"items":[],"lines":[]}
    if version == 3:
        from lc_layout_v3 import geometry
        return geometry(job, layout, width, height)
    if version == 2:
        validate_layout_v2(layout)
        return _layout_geometry_v2(job, layout, width, height, name)
    items = layout.get("items") or []
    if not isinstance(items,list) or len(items)>3:
        raise LayoutError("layout.items must be a list of at most three items")
    count = max(1,len(items))
    head = [.05,.05,.9,.16 if portrait else .19]
    body = [.05,.215 if portrait else .25,.9,.085 if portrait else .11]
    product = [.05,.38 if not portrait else .34,.9,.56 if not portrait else .60]
    slots,lines = [],[]
    if name == "split" and not portrait:
        head,body,product = [.05,.19,.40,.29],[.05,.51,.40,.18],[.50,.12,.45,.81]
    elif name == "split":
        product = [.07,.34,.86,.61]
    elif name == "benefits":
        product = [.10,.38 if not portrait else .33,.8,.34 if not portrait else .40]
        for i in range(len(items)):
            cell = .9/count
            slots.append({"box":[.05+i*cell,.79,cell-.025,.15],"text":[.05+i*cell,.845,cell-.025,.10],"icon":[.05+i*cell,.775,.048,.048*width/height]})
    elif name == "detail":
        product = [.05,.38,.52,.55]
        for i in range(len(items)):
            y = .35+i*.205
            slots.append({"box":[.63,y,.32,.18],"image":[.63,y,.14,.14*width/height],"text":[.785,y,.165,.16]})
            target=items[i].get("target")
            if target is not None:
                if not isinstance(target,list) or len(target)!=2 or any(not isinstance(v,(int,float)) or not 0<=v<=1 for v in target):
                    raise LayoutError("detail item.target must be normalized [x,y]")
                lines.append({"id":f"leader-{i}","points":[[.625,y+.07*width/height],[.595,y+.07*width/height],target],"target":target})
    elif name == "dimensions":
        product = [.22,.36,.60,.45]
        for i,item in enumerate(items):
            axis=item.get("axis","horizontal" if i==0 else "vertical")
            if axis not in {"horizontal","vertical"}:
                raise LayoutError("dimension axis must be horizontal or vertical")
            if axis == "horizontal":
                slots.append({"box":[.25,.86,.54,.09],"text":[.25,.89,.54,.055]})
                lines.append({"id":f"dimension-{i}","points":[[.23,.86],[.82,.86]],"arrow":True})
            else:
                slots.append({"box":[.05,.49,.155,.14],"text":[.05,.49,.13,.14]})
                lines.append({"id":f"dimension-{i}","points":[[.19,.36],[.19,.81]],"arrow":True})
    elif name == "components":
        product = [.05,.38,.48,.55]
        for i,item in enumerate(items):
            y=.35+i*.20
            has_image=bool(item.get("image"))
            slots.append({"box":[.59,y,.36,.18],"image":[.59,y,.14,.14*width/height] if has_image else None,
                          "number":[.59,y,.05,.05*width/height] if not has_image else None,
                          "text":[.75 if has_image else .665,y,.20 if has_image else .285,.16]})
    elif name == "scene" and items:
        # A scene can carry one small supporting line below its visual, not cards.
        product=[.05,.38 if not portrait else .34,.9,.40 if not portrait else .46]
        cell=.9/count
        for i in range(len(items)):
            slots.append({"box":[.05+i*cell,.85,cell-.025,.1],"text":[.05+i*cell,.85,cell-.025,.1]})
    if name == "split" and items:
        raise LayoutError("split uses headline/body only; use benefits for supporting items")
    return {"template":name,"canvas":[width,height],"variant":"portrait" if portrait else "square",
            "safe_margin":.05,"product_zone":product,"headline":head,"body":body,
            "text_zones":[head,body]+[s["text"] for s in slots],"image_region_norm":product,"product_region_norm":product,"text_regions_norm":[head,body]+[s["text"] for s in slots],"items":slots,"lines":lines}

@lru_cache(maxsize=24)
def _font_cmap(path: str, digest: str) -> frozenset[int]:
    """Read Unicode cmap formats 4/12/13 from bundled sfnt; no fontTools dependency."""
    data=Path(path).read_bytes()
    count=struct.unpack_from(">H",data,4)[0]
    cmap=None
    for i in range(count):
        tag,_,offset,_=struct.unpack_from(">4sIII",data,12+i*16)
        if tag==b"cmap": cmap=offset; break
    if cmap is None: raise LayoutError(f"Font has no cmap: {path}")
    points=set()
    for i in range(struct.unpack_from(">H",data,cmap+2)[0]):
        platform,encoding,offset=struct.unpack_from(">HHI",data,cmap+4+i*8)
        if platform not in {0,3} or (platform==3 and encoding not in {1,10}): continue
        sub=cmap+offset; fmt=struct.unpack_from(">H",data,sub)[0]
        if fmt in {12,13}:
            groups=struct.unpack_from(">I",data,sub+12)[0]
            for k in range(groups):
                start,end,glyph=struct.unpack_from(">III",data,sub+16+k*12)
                if fmt==13 and glyph==0: continue
                points.update(range(start+(glyph==0),end+1))
        elif fmt==4:
            n=struct.unpack_from(">H",data,sub+6)[0]//2
            ends=struct.unpack_from(f">{n}H",data,sub+14)
            starts=struct.unpack_from(f">{n}H",data,sub+16+2*n)
            deltas=struct.unpack_from(f">{n}h",data,sub+16+4*n)
            ranges=sub+16+6*n
            for j,(start,end,delta) in enumerate(zip(starts,ends,deltas)):
                ro=struct.unpack_from(">H",data,ranges+2*j)[0]
                for cp in range(start,min(end,0xfffe)+1):
                    glyph=struct.unpack_from(">H",data,ranges+2*j+ro+2*(cp-start))[0] if ro else (cp+delta)&65535
                    if glyph:points.add(cp)
    return frozenset(points)

def _font_records(version: int, headline_family: str = "sans") -> list[tuple[str, int, str]]:
    if version == 1:
        return [(family, weight, name)
                for family, names in FONT_FILES.items()
                for weight, name in zip((400, 700), names)]
    records = [(family, weight, name)
               for family, weights in V2_SANS_FONT_FILES.items()
               for weight, name in weights.items()]
    if headline_family == "serif":
        records.extend(("Serif", weight, name) for weight, name in V2_SERIF_FONT_FILES.items())
    if version == 3:
        records.extend((family, 700, weights[600]) for family, weights in V2_SANS_FONT_FILES.items())
    return records

@lru_cache(maxsize=16)
def _font_uri(path: str, digest: str) -> str:
    font = Path(path)
    return "data:font/" + ("otf" if font.suffix == ".otf" else "ttf") + ";base64," + base64.b64encode(font.read_bytes()).decode()


def _font_payload(texts: list[str], *, version: int = 1, headline_family: str = "sans", subset: bool = False,
                  weights: tuple[int, ...] | None = None, primary_families: tuple[str, ...] = ()) -> tuple[list[dict], list[str]]:
    required = {ord(c) for text in texts for c in text if not c.isspace() and c not in "\u200c\u200d\u200e\u200f"}
    fonts: list[dict] = []
    required_weights = weights or ((400, 700) if version == 1 else (400, 600, 700) if version == 3 else (400, 600))
    coverage = {weight: set() for weight in required_weights}
    for family, weight, name in _font_records(version, headline_family):
        if weight not in coverage:
            continue
        path = ASSETS / "fonts" / name
        if not path.is_file():
            raise LayoutError(f"Missing bundled font: {name}")
        digest = file_hash(path)
        cmap = _font_cmap(str(path), digest)
        # Sans fallback order remains Latin -> Arabic/CJK as before.  Keep the
        # explicitly selected Serif face even when Latin covers the same glyphs.
        primary_required = family in primary_families and bool(required.intersection(cmap))
        if subset and family != "Serif" and not primary_required and not (required - coverage[weight]).intersection(cmap):
            continue
        coverage[weight].update(cmap)
        fonts.append({"family": family, "weight": weight,
                      "uri": _font_uri(str(path), digest)})
    missing = required - set.intersection(*(coverage[weight] for weight in required_weights))
    return fonts, [f"U+{cp:04X}" for cp in sorted(missing)]

def _discover_runtime() -> dict:
    lock=_json(ASSETS/"layout-runtime.json")
    dependency=Path.home()/".cache/codex-runtimes/codex-primary-runtime/dependencies"
    nodes=[os.environ.get("LC_LAYOUT_NODE"), shutil.which("node"),str(dependency/"node/bin/node")]
    node=next((p for p in nodes if p and Path(p).is_file()),None)
    modules_candidates=[os.environ.get("LC_LAYOUT_NODE_MODULES"),str(ROOT/"node_modules"),str(dependency/"node/node_modules")]
    modules=next((p for p in modules_candidates if p and (Path(p)/"playwright/package.json").exists()),None)
    browsers=[]
    if os.environ.get("LC_LAYOUT_CHROMIUM"):browsers.append(Path(os.environ["LC_LAYOUT_CHROMIUM"]))
    cache_roots=[Path.home()/"Library/Caches/ms-playwright",Path.home()/".cache/ms-playwright"]
    if os.environ.get("LOCALAPPDATA"):cache_roots.append(Path(os.environ["LOCALAPPDATA"])/"ms-playwright")
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):cache_roots.insert(0,Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"]))
    for cache in cache_roots:
        for pattern in ["chromium*/chrome-headless-shell*/chrome-headless-shell","chromium*/chrome-headless-shell*/headless_shell.exe","chromium*/chrome-*/chrome","chromium*/chrome-*/chrome.exe","chromium*/chrome-*/Chromium.app/Contents/MacOS/Chromium"]:
            browsers.extend(sorted(cache.glob(pattern),reverse=True))
    selected=None; seen=[]
    for browser in browsers:
        try:
            version=subprocess.check_output([str(browser),"--version"],text=True,stderr=subprocess.DEVNULL,timeout=6).strip()
            seen.append(version)
            if lock["chromium_version"] in version: selected=str(browser);break
        except (OSError,subprocess.SubprocessError):continue
    errors=[]
    if not node:errors.append("Node not found: configure LC_LAYOUT_NODE")
    else:
        version=subprocess.check_output([node,"--version"],text=True,timeout=6).strip()
        if int(version.lstrip("v").split(".")[0])<lock["node_min_major"]:errors.append("Node version is too old")
    if not modules:errors.append("Playwright not found: configure LC_LAYOUT_NODE_MODULES")
    elif _json(Path(modules)/"playwright/package.json")["version"] != lock["playwright_version"]:errors.append("Playwright version does not match runtime lock")
    if not selected:errors.append(f"Pinned Chromium {lock['chromium_version']} not found; detected {seen}")
    if PILLOW_VERSION != lock["pillow_version"]:errors.append(f"Pillow {PILLOW_VERSION} does not match {lock['pillow_version']}")
    return {"passed":not errors,"errors":errors,"node":node,"modules":modules,"chromium":selected,"versions":lock}

def doctor() -> dict:
    result=_discover_runtime()
    for names in FONT_FILES.values():
        for name in names:
            path=ASSETS/"fonts"/name
            if not path.is_file():result["errors"].append(f"Missing bundled font: {name}")
    try:
        font_manifest=_json(ASSETS/"fonts/manifest.json")
        for item in font_manifest["fonts"]:
            font_path=ASSETS/"fonts"/item["file"]
            if not font_path.is_file() or file_hash(font_path)!=item["sha256"]:result["errors"].append(f"Bundled font hash mismatch: {item['file']}")
        for license_file in font_manifest["license_files"]:
            if not (ASSETS/"fonts"/license_file).is_file():result["errors"].append(f"Missing font license: {license_file}")
    except (OSError,KeyError,ValueError) as exc:result["errors"].append(f"Font lock unavailable: {exc}")
    result["passed"]=not result["errors"]
    return result

def layout_fingerprint(manifest: dict, job: dict, base: Path | None = None) -> str:
    """Layout-only dependencies: excludes AI metadata and generation prompt."""
    layout = resolve_layout_defaults(job)
    version = _layout_version(layout)
    headline_family = layout.get("headline_family", "sans") if version >= 2 else "sans"
    if version == 3 and any(group.get("headline_family", headline_family) == "serif" for group in layout.get("text_groups", [])):
        headline_family = "serif"
    dependencies = {}
    # Hash only the type resources this layout can use.  A newly bundled display
    # font should not make an unchanged legacy layout stale.
    for _, _, name in _font_records(version, headline_family):
        path = ASSETS / "fonts" / name
        dependencies[str(path.relative_to(ROOT))] = file_hash(path)
    themes = _json(ASSETS / "layouts/themes.json")
    theme = layout.get("theme", "neutral")
    dependencies["theme:" + str(theme)] = _digest(themes.get(theme))
    icons = _json(ASSETS / "icons/icons.json")
    for icon in sorted({item.get("icon") for item in layout.get("items", []) if isinstance(item, dict) and item.get("icon")}):
        dependencies["icon:" + icon] = _digest(icons.get(icon))
    for path in [ASSETS/"layout-runtime.json",Path(__file__),Path(__file__).with_name("render_layout.mjs")]:
        dependencies[str(path.relative_to(ROOT))]=file_hash(path)
    if version == 3:
        path = Path(__file__).with_name("lc_layout_v3.py")
        dependencies[str(path.relative_to(ROOT))] = file_hash(path)
        if job.get("_project_style"):
            path = Path(__file__).with_name("lc_project_contracts.py")
            dependencies[str(path.relative_to(ROOT))] = file_hash(path)
    from lc_typography import enabled
    if enabled(job):
        path = Path(__file__).with_name("lc_typography.py")
        dependencies[str(path.relative_to(ROOT))] = file_hash(path)
        from lc_title_effects import has_effect
        if has_effect(job):
            from lc_dependencies import title_effect_dependencies as effect_dependencies
            path = Path(__file__).with_name("lc_title_effects.py")
            dependencies[str(path.relative_to(ROOT))] = file_hash(path)
            if base is not None:
                dependencies["title_effect"] = effect_dependencies(job, base)
    if base is not None:
        for item in layout.get("items",[]):
            if item.get("image"):
                image=_project_file(Path(base),item["image"]);dependencies["image:"+item["image"]]=file_hash(image)
        for panel in layout.get("panels", []):
            image = _project_file(Path(base), panel["image"])
            dependencies["panel:" + panel["image"]] = file_hash(image)
    fingerprint = {"layout":layout,"version":version,"canvas":job.get("canvas"),"kind":job.get("kind"),
                   "language":job.get("language",manifest.get("language",manifest.get("output_language","en"))),
                   "product_box":job.get("output_product_bbox_norm"),"dependencies":dependencies}
    # layout already captures all v2 fields; retain routing explicitly so review
    # reports make it clear that a changed polyline requires a new layout pass.
    if version >= 2:
        fingerprint["leader_waypoints"] = [item.get("leader_waypoints", []) for item in layout.get("items", []) if isinstance(item, dict)]
    return _digest(fingerprint)

def _text(value: Any, label: str, max_length: int=500) -> str:
    if not isinstance(value,str) or len(value)>max_length:raise LayoutError(f"{label} must be text <= {max_length} characters")
    if any(c in value for c in "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"):
        raise LayoutError("Explicit bidi overrides are unsupported; use language/direction")
    # Keep numerical measurements together; do not rewrite claims or legal qualifiers.
    return re.sub(r"(?<=\d) +(?=(?:cm|mm|m|kg|g|ml|mL|L|oz|lb|lbs|in|inch|inches|ft|W|V|°C|°F)\b)","\u00a0",value)

def _v2_mobile_sizes(layout: dict) -> dict[str, float]:
    """Return CSS-pixel design tokens for a 360px-wide preview.

    Rendered output scales these tokens by canvas_width / 360.  The values are
    never reduced to make overflowing copy fit; callers must recompose the
    content group or request confirmation instead.
    """
    configured = layout.get("mobile_sizes", {})
    if not isinstance(configured, dict):
        raise LayoutError("mobile_sizes must be an object of 360px-preview tokens")
    values: dict[str, float] = {}
    maximum = {"headline": 48, "body": 28, "label": 28}
    for key, default in V2_MOBILE_DEFAULTS.items():
        value = configured.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise LayoutError(f"mobile_sizes.{key} must be a finite 360px-preview token")
        if not V2_MOBILE_FLOORS[key] <= value <= maximum[key]:
            raise LayoutError(f"mobile_sizes.{key} must be {V2_MOBILE_FLOORS[key]}..{maximum[key]} at 360px preview")
        values[key] = float(value)
    unknown = set(configured) - set(V2_MOBILE_DEFAULTS)
    if unknown:
        raise LayoutError(f"Unknown mobile_sizes fields: {', '.join(sorted(unknown))}")
    return values

def validate_layout_v2(layout: dict) -> None:
    """Validate version-two layout fields for pipeline callers.

    Valid layouts return ``None``; invalid layouts raise ``LayoutError`` so the
    pipeline can preserve its existing validation/error-reporting contract.
    """
    if not isinstance(layout, dict):
        raise LayoutError("layout must be an object")
    if _layout_version(layout) != 2:
        raise LayoutError("validate_layout_v2 requires layout.version=2")
    if "font_sizes" in layout:
        raise LayoutError("layout.font_sizes is legacy-only; use mobile_sizes with layout.version=2")
    surface = layout.get("text_surface", "transparent")
    if surface not in {"transparent", "solid", "gradient"}:
        raise LayoutError("text_surface must be transparent/solid/gradient")
    group = layout.get("text_group", {})
    if not isinstance(group, dict):
        raise LayoutError("text_group must be an object")
    if "box" in group:
        _box(group["box"], "text_group.box")
    if group.get("align", "left") not in {"left", "center", "right"}:
        raise LayoutError("text_group.align must be left/center/right")
    gap = group.get("gap_em", .55)
    if isinstance(gap, bool) or not isinstance(gap, (int, float)) or not math.isfinite(gap) or not 0 <= gap <= 2:
        raise LayoutError("text_group.gap_em must be a finite 0..2 em value")
    if "max_height" in group:
        max_height = group["max_height"]
        if isinstance(max_height, bool) or not isinstance(max_height, (int, float)) or not math.isfinite(max_height) or not 0 < max_height <= 1:
            raise LayoutError("text_group.max_height must be a normalized 0..1 canvas height")
    if layout.get("headline_family", "sans") not in {"sans", "serif"}:
        raise LayoutError("headline_family must be sans/serif")
    if layout.get("headline_weight", 600) not in {400, 600}:
        raise LayoutError("headline_weight must be 400/600")
    _v2_mobile_sizes(layout)
    faq = layout.get("faq", [])
    if not isinstance(faq, list) or len(faq) > 2:
        raise LayoutError("faq must be a list of at most two question/answer groups")
    for index, pair in enumerate(faq):
        if not isinstance(pair, dict):
            raise LayoutError(f"faq[{index}] must be an object")
        _text(pair.get("question", ""), f"faq[{index}].question", 180)
        _text(pair.get("answer", ""), f"faq[{index}].answer", 500)
        if not pair.get("question") or not pair.get("answer"):
            raise LayoutError(f"faq[{index}] needs nonempty question and answer")
    items = layout.get("items", [])
    if not isinstance(items, list) or len(items) > 3:
        raise LayoutError("layout.items must be a list of at most three items")
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise LayoutError(f"items[{index}] must be an object")
        for field in ("box", "image_box", "text_box", "icon_box", "number_box"):
            if field in item:
                _box(item[field], f"items[{index}].{field}")
        if "target" in item:
            _point(item["target"], f"items[{index}].target")
        if "leader_waypoints" in item:
            waypoints = item["leader_waypoints"]
            if not isinstance(waypoints, list) or len(waypoints) > 4:
                raise LayoutError(f"items[{index}].leader_waypoints must be a list of at most four normalized points")
            if layout.get("template", "scene") != "detail" or not item.get("image") or item.get("target") is None:
                raise LayoutError(f"items[{index}].leader_waypoints requires a detail item with image and target")
            for waypoint_index, point in enumerate(waypoints):
                _point(point, f"items[{index}].leader_waypoints[{waypoint_index}]")
        if item.get("align") is not None and item["align"] not in {"left", "center", "right"}:
            raise LayoutError(f"items[{index}].align must be left/center/right")
        if item.get("image_shape", "rect") not in {"circle", "rect"}:
            raise LayoutError(f"items[{index}].image_shape must be circle/rect")

def validate_layout_v3(layout: dict) -> None:
    from lc_layout_v3 import validate_layout_v3 as validate
    validate(layout)


@lru_cache(maxsize=8)
def _raster_uri_cached(path_value: str, digest: str) -> str:
    import io
    path = Path(path_value)
    with Image.open(path) as im:
        # Canonical pipeline PNGs already have their orientation/color handled.
        # Re-encoding them consumed more time than browser rendering.  Untrusted
        # metadata, palette transparency and other formats retain normalization.
        if im.format == "PNG" and im.mode in {"RGB", "RGBA"} and set(im.info).issubset({"dpi", "interlace"}):
            return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()
        im=im.convert("RGBA")
        buffer=io.BytesIO();im.save(buffer,format="PNG")
    return "data:image/png;base64,"+base64.b64encode(buffer.getvalue()).decode()


def _raster_uri(path: Path) -> str:
    return _raster_uri_cached(str(path.resolve()), file_hash(path))

def _prepare_job(manifest: dict, base: Path, job: dict) -> dict:
    job_id=job.get("id")
    if not isinstance(job_id,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,100}",job_id):raise LayoutError("Invalid job id")
    layout=resolve_layout_defaults(job)
    if not isinstance(layout,dict):raise LayoutError("layout must be an object")
    version=_layout_version(layout)
    if version == 2:
        # layout_geometry() deliberately exits early for main images; retain the
        # same public validation contract for callers that prepare one anyway.
        validate_layout_v2(layout)
    elif version == 3:
        validate_layout_v3(layout)
    geometry=layout_geometry(job)
    path=_project_file(base,job.get("layout_input"))
    with Image.open(path) as im:
        if list(im.size)!=geometry["canvas"]:raise LayoutError("layout_input must already match the complete canvas without resizing")
    headline=_text(layout.get("headline",""),"headline",180)
    body=_text(layout.get("body",""),"body",500)
    items=[]
    icons=_json(ASSETS/"icons/icons.json")
    for i,item in enumerate(layout.get("items") or []):
        if not isinstance(item,dict):raise LayoutError("Each layout item must be an object")
        refs=item.get("evidence_refs",[])
        if not isinstance(refs,list) or any(not isinstance(ref,str) or not ref.strip() for ref in refs):
            raise LayoutError("item.evidence_refs must be a list of nonempty evidence identifiers")
        entry={"text":_text(item.get("text",""),"item.text",180),"icon":item.get("icon","")}
        if version >= 2:
            entry["image_shape"]=item.get("image_shape","rect")
            entry["align"]=item.get("align")
        if entry["icon"] and entry["icon"] not in icons:raise LayoutError(f"Unknown icon {entry['icon']!r}")
        if item.get("image"):
            entry["image"]=_raster_uri(_project_file(base,item["image"]))
            if not item.get("evidence_refs"):raise LayoutError("Detail/component image needs evidence_refs")
        # V2 permits an evidence-only inset: its source and leader are still
        # checked, but it need not invent an additional label.  V1 keeps the
        # historic nonempty-label requirement byte-for-byte compatible.
        if not entry["text"] and (version == 1 or not entry.get("image")):
            raise LayoutError("Item text cannot be empty unless a v2 evidence inset is supplied")
        if geometry["template"]=="detail" and (not entry.get("image") or not item.get("target")):
            raise LayoutError("Every detail item needs image, evidence_refs and target")
        if geometry["template"]=="dimensions":
            if not re.search(r"\d",entry["text"]) or not re.search(r"(?:cm|mm|kg|ml|oz|lbs?|in(?:ch(?:es)?)?|ft|[mgLWV]|厘米|毫米|英寸|公分|吋|سم|ملم)\b",entry["text"]) or not item.get("evidence_refs"):
                raise LayoutError("Dimensions require a value, explicit unit, and evidence_refs")
        items.append(entry)
    if geometry["template"] in {"detail","dimensions","components","benefits"} and not items:
        raise LayoutError(f"{geometry['template']} requires supporting items")
    if geometry["template"]=="dimensions" and len({v.get("axis","horizontal" if i==0 else "vertical") for i,v in enumerate(layout.get("items",[]))})!=len(items):
        raise LayoutError("Only one horizontal and one vertical measurement per dimensions layout")
    faq=[]
    if version >= 2:
        faq=[{"question":_text(pair["question"],f"faq[{i}].question",180),
              "answer":_text(pair["answer"],f"faq[{i}].answer",500)}
             for i,pair in enumerate(layout.get("faq",[]))]
    if job.get("kind")=="main" and (headline or body or items or faq or layout.get("text_groups") or layout.get("panels")):raise LayoutError("Main images cannot contain layout text/items/panels")
    if version < 3 and job.get("kind")!="main" and not headline and (body or items or faq):raise LayoutError("Text layouts require a headline")
    language=job.get("language",manifest.get("language",manifest.get("output_language","en")))
    if not isinstance(language,str) or not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*",language):raise LayoutError("Use a BCP-47 language tag")
    direction=layout.get("direction","rtl" if language.split("-")[0] in {"ar","fa","ur","he"} else "ltr")
    if direction not in {"ltr","rtl"}:raise LayoutError("direction must be ltr or rtl")
    theme=layout.get("theme","neutral")
    themes=_json(ASSETS/"layouts/themes.json")
    if theme not in themes:raise LayoutError("Unknown theme")
    surface=layout.get("text_surface","transparent")
    if surface not in {"transparent","solid","gradient"}:raise LayoutError("text_surface must be transparent/solid/gradient")
    ink=layout.get("text_color",themes[theme]["ink"])
    if not re.fullmatch(r"#[0-9a-fA-F]{6}",ink):raise LayoutError("text_color must be #RRGGBB")
    protected=[]
    if job.get("output_product_bbox_norm") and not (version == 3 and layout.get("canvas_background") and layout.get("panels")):
        protected.append({"kind":"product","bbox":_box(job["output_product_bbox_norm"],"output product box")})
    for region in layout.get("protected_regions",[]):
        protected.append({"kind":region.get("kind","protected") if isinstance(region,dict) else "protected",
                          "bbox":_box(region.get("bbox") if isinstance(region,dict) else region,"protected region")})
    if version == 1:
        sizes={"headline":140,"body":78,"label":68}
        for key,(low,high) in {"headline":(120,160),"body":(72,88),"label":(64,80)}.items():
            value=layout.get("font_sizes",{}).get(key,sizes[key])
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not low<=value<=high:raise LayoutError(f"{key} size must be {low}..{high} at 2000px short edge")
            sizes[key]=value*min(geometry["canvas"])/2000
        text_group=None
        headline_family="sans"
        headline_weight=700
    else:
        # V2 values are design tokens at a 360px-wide preview.  They scale from
        # the canvas *width* so a 1464px A+ strip and a portrait listing each
        # retain an independently intentional hierarchy; no overflow path ever
        # reduces these computed sizes.
        tokens=_v2_mobile_sizes(layout)
        scale=geometry["canvas"][0]/360
        sizes={key:max(tokens[key],V2_MOBILE_FLOORS[key])*scale for key in tokens}
        group_config=layout.get("text_group") or {}
        group=geometry["text_group"]
        max_norm=min(float(group[3]),float(group_config.get("max_height",group[3])))
        text_group={"box":group,
                    "align":group_config.get("align","right" if direction=="rtl" else "left"),
                    "gap_em":float(group_config.get("gap_em",.55)),
                    "max_height_px":max_norm*geometry["canvas"][1],
                    # Padding belongs to the one adaptive content surface, not
                    # to each headline/body/FAQ paragraph.
                    "padding_px":max(8,round(sizes["body"]*.65)) if surface!="transparent" else 0}
        headline_family=layout.get("headline_family","sans")
        headline_weight=layout.get("headline_weight",600)
    result = {"id":job_id,"version":version,"geometry":geometry,"headline":headline,"body":body,"faq":faq,"items":items,"language":language,
            "direction":direction,"theme":themes[theme],"ink":ink,"surface":surface,"sizes":sizes,
            "text_group":text_group,"headline_family":headline_family,"headline_weight":headline_weight,"protected":protected,
            "base_image":_raster_uri(path),"base_hash":file_hash(path),"fingerprint":layout_fingerprint(manifest,job,base)}
    if version == 3:
        from lc_layout_v3 import prepare_groups, panel_placement, mapped_product_box
        result["theme"] = {**result["theme"], "accent": layout.get("graphic_color", result["theme"]["accent"])}
        result["label_weight"] = layout.get("label_weight", 600)
        result["graphic_surface_color"] = layout.get("graphic_surface_color", "#171717")
        result["graphic_text_color"] = layout.get("graphic_text_color", layout.get("graphic_color", "#FFFFFF"))
        result["text_groups"] = prepare_groups(layout, geometry, direction)
        result["canvas_background"] = layout.get("canvas_background")
        result["headline_family"] = "serif" if any(group["headline_family"] == "serif" for group in result["text_groups"]) else "sans"
        result["panels"] = []
        for panel, slot in zip(layout.get("panels", []), geometry["panels"]):
            source = _project_file(base, panel["image"])
            with Image.open(source) as image:
                source_size = list(image.size)
            prepared_panel = {"id": slot["id"], "image": _raster_uri(source), "box": slot["box"], "source_size": source_size,
                              "source_crop": panel.get("source_crop", [0, 0, 1, 1]), "fit": panel.get("fit", "cover"),
                              "product_bbox_norm": panel.get("product_bbox_norm")}
            if layout["recipe"] == "steps":
                prepared_panel["step_number"] = len(result["panels"]) + 1
            prepared_panel["placement"] = panel_placement(prepared_panel, geometry["canvas"])
            mapped = mapped_product_box(prepared_panel, geometry["canvas"])
            if mapped:
                protected.append({"kind": "product", "bbox": mapped, "panel": slot["id"]})
            result["panels"].append(prepared_panel)
    from lc_typography import enabled, decision
    result["typography_proof"] = enabled(job)
    if result["typography_proof"]:
        result["typography_decision"] = decision(job, layout)
    return result

def _prepared_texts(job: dict) -> list[str]:
    """Every visible string, including FAQ copy, for glyph coverage checks."""
    return ([job["headline"],job["body"]]
            + [group[key] for group in job.get("text_groups", []) for key in ("headline", "body", "label")]
            + [value for pair in job.get("faq",[]) for value in (pair["question"],pair["answer"])]
            + [item["text"] for item in job["items"]])


def _prepared_font_weights(job: dict) -> set[int]:
    """Do not ship the same CJK bold binary at unused 600 and 700 aliases."""
    weights = set()
    if job["version"] == 3:
        for group in job.get("text_groups", []):
            if group["headline"]:
                weights.add(group["headline_weight"])
            if group["body"]:
                weights.add(400)
            if group["label"]:
                weights.add(group.get("label_weight", 600))
        if any(panel.get("step_number") for panel in job.get("panels", [])):
            weights.add(job.get("label_weight", 600))
    else:
        if job["headline"]:
            weights.add(job["headline_weight"])
        if job["body"]:
            weights.add(400)
    if job.get("faq"):
        weights.update((400, 600))
    if any(item.get("text") for item in job["items"]) or any(slot.get("number") for slot in job["geometry"].get("items", [])):
        weights.add(700 if job["version"] == 1 else job.get("label_weight", 600))
    return weights or {400}

def render_batch(manifest: dict, base: Path, jobs: list[dict], *, measure_only: bool = False) -> dict:
    """Render a batch, or measure its layout without screenshot/preview artifacts."""
    base=Path(base).resolve();results={};prepared=[];start=time.monotonic()
    batch_id = f"layout-{time.time_ns()}"
    preparation_times = {}
    output=base/"review/layouts"
    if not measure_only:
        output.mkdir(parents=True,exist_ok=True)
    if len({j.get("id") for j in jobs})!=len(jobs):raise LayoutError("Duplicate job ids")
    for job in jobs:
        job_started = time.monotonic()
        try:prepared.append(_prepare_job(manifest,base,job))
        except (LayoutError,OSError,ValueError,KeyError,TypeError) as exc:
            results[job.get("id", "unknown")]={"passed":False,"checks":[{"check":"input_validation","passed":False,"detail":str(exc)}],"bboxes":[],"output_path":None,"runtime":{}}
        preparation_times[job.get("id", "unknown")] = round(time.monotonic() - job_started, 4)
    if not prepared:return results
    try:
        phase_started = time.monotonic()
        runtime=doctor()
        shared_metrics = {"doctor_seconds": round(time.monotonic() - phase_started, 4), "batch_id": batch_id,
                          "job_count": len(prepared), "shared_costs_recorded_once": True,
                          "timing_relationship": "renderer_process_seconds includes child browser/parse/render/screenshot phases; do not sum overlapping scopes"}
        if not runtime["passed"]:raise LayoutError("; ".join(runtime["errors"]))
        # Font coverage is checked per layout variant so a new v2 display face
        # cannot change the outcome of a legacy job sharing this render batch.
        phase_started = time.monotonic()
        fonts_by_key={}
        weights_by_key={}
        primary_families_by_key={}
        missing_by_key={}
        for j in prepared:
            key=(j["version"],j["headline_family"])
            fonts_by_key.setdefault(key,[]).extend(_prepared_texts(j))
            weights_by_key.setdefault(key, set()).update(_prepared_font_weights(j))
            language = j["language"].split("-")[0]
            primary = "CJK" if language in {"zh", "ja", "ko"} else "Arabic" if language in {"ar", "fa", "ur"} else "Latin"
            primary_families_by_key.setdefault(key, set()).add(primary)
        for key,texts in list(fonts_by_key.items()):
            fonts_by_key[key],missing_by_key[key]=_font_payload(texts,version=key[0],headline_family=key[1],subset=True,weights=tuple(sorted(weights_by_key[key])),primary_families=tuple(sorted(primary_families_by_key[key])))
        shared_metrics["font_prepare_seconds"] = round(time.monotonic() - phase_started, 4)
        # Report glyph failures per job; unrelated jobs may still render.
        eligible=[]
        for j in prepared:
            key=(j["version"],j["headline_family"])
            chars={f"U+{ord(c):04X}" for t in _prepared_texts(j) for c in t if not c.isspace() and c not in "\u200c\u200d\u200e\u200f"}
            absent=sorted(chars.intersection(missing_by_key[key]))
            if absent:
                results[j["id"]]={"passed":False,"checks":[{"check":"font_coverage","passed":False,"detail":absent}],"bboxes":[],"output_path":None,"runtime":runtime["versions"]}
            else:eligible.append(j)
        if not eligible:return results
        # A mixed legacy/v2 batch can request the same family at different
        # weights.  De-duplicate only exact family/weight faces.
        fonts=[];seen_faces=set()
        for j in eligible:
            key=(j["version"],j["headline_family"])
            for face in fonts_by_key[key]:
                identity=(face["family"],face["weight"])
                if identity not in seen_faces:
                    seen_faces.add(identity);fonts.append(face)
        payload={"jobs":eligible,"fonts":fonts,"icons":_json(ASSETS/"icons/icons.json"),"chromium":runtime["chromium"],"mode":"measure" if measure_only else "render",
                 "playwright":str(Path(runtime["modules"])/"playwright/index.mjs"),"output_dir":str(output),"versions":runtime["versions"]}
        shared_metrics["font_payload_bytes"] = sum(len(face["uri"]) for face in fonts)
        phase_started = time.monotonic()
        serialized = json.dumps(payload, ensure_ascii=False)
        shared_metrics["payload_serialize_seconds"] = round(time.monotonic() - phase_started, 4)
        shared_metrics["payload_bytes"] = len(serialized.encode("utf-8"))
        phase_started = time.monotonic()
        run=subprocess.run([runtime["node"],str(Path(__file__).with_name("render_layout.mjs"))],input=serialized,text=True,capture_output=True,timeout=max(90,40*len(eligible)))
        shared_metrics["renderer_process_seconds"] = round(time.monotonic() - phase_started, 4)
        if run.returncode:raise LayoutError(f"Renderer failed: {run.stderr[-2000:]}")
        rendered=json.loads(run.stdout)
        for job_id,item in rendered.items():
            preview_started = time.monotonic()
            if item.get("output_path"):
                image_path=Path(item["output_path"])
                source_job = next(j for j in jobs if j["id"] == job_id)
                from lc_title_effects import has_effect
                if not has_effect(source_job) and source_job.get("title_effect_state"):
                    source_job["title_effect_state"].update(status="disabled", fallback_reason="TITLE_EFFECT_DISABLED")
                    source_job["title_effect_state"].pop("applied", None)
                from lc_typography import enabled, raster_contrast, proof_paths, include_glyph_overhang
                if enabled(source_job):
                    paths = proof_paths(base, job_id)
                    # Browser screenshots are RGB; effects require an explicit L mask.
                    with Image.open(paths["glyph_mask"]) as mask_image:
                        glyph_mask = mask_image.convert("L")
                    glyph_mask.save(paths["glyph_mask"])
                    item["bboxes"] = include_glyph_overhang(glyph_mask, item["bboxes"])
                    prepared_job = next(j for j in prepared if j["id"] == job_id)
                    width, height = source_job["canvas"]
                    for box_item in (b for b in item["bboxes"] if b.get("kind") == "text"):
                        b = box_item["bbox"]
                        safe = min(width, height) * .05
                        safe_ok = b["x"] >= safe-1 and b["y"] >= safe-1 and b["x"]+b["width"] <= width-safe+1 and b["y"]+b["height"] <= height-safe+1
                        item["checks"].append({"check": "glyph_safe_margin", "element": box_item["id"], "passed": safe_ok})
                        for protected in prepared_job["protected"]:
                            x, y, w, h = protected["bbox"]
                            overlap = (min(b["x"]+b["width"], (x+w)*width) > max(b["x"], x*width)
                                       and min(b["y"]+b["height"], (y+h)*height) > max(b["y"], y*height))
                            if overlap:
                                item["checks"].append({"check": "glyph_product_protection", "element": box_item["id"], "passed": False})
                    if has_effect(source_job):
                        from lc_title_effects import composite
                        effect = composite(source_job, base, image_path, paths["background"], paths["glyph_mask"], item["bboxes"], manifest=manifest)
                        if effect["applied"]:
                            Path(effect["output_path"]).replace(image_path)
                        effect["output_path"] = str(image_path.relative_to(base))
                        item["title_effect"] = effect
                    with Image.open(image_path) as fg, Image.open(paths["background"]) as bg, Image.open(paths["glyph_mask"]) as mask:
                        item["checks"].extend(raster_contrast(fg.convert("RGB"), bg.convert("RGB"), mask, item["bboxes"]))
                    item["typography_proof_hashes"] = {name: file_hash(path) for name, path in paths.items()}
                    item["typography_decision"] = next(j["typography_decision"] for j in prepared if j["id"] == job_id)
                    item["passed"] = all(check["passed"] for check in item["checks"])
                with Image.open(image_path) as im:
                    preview=im.convert("RGB");preview.thumbnail((360,10000),Image.Resampling.LANCZOS)
                    preview_path=output/f"{job_id}-360.png";preview.save(preview_path)
                item["mobile_preview_binding"] = {"sha256": file_hash(preview_path),
                                                  "layout_sha256": file_hash(image_path)}
                item["output_path"]=str(image_path.relative_to(base))
                item["preview_path"]=str(preview_path.relative_to(base))
            item["runtime"]["preview_seconds"] = round(time.monotonic() - preview_started, 4)
            item["runtime"]["python_prepare_seconds"] = preparation_times[job_id]
            item["runtime"]["batch_id"] = batch_id
            item["checks"].append({"check":"font_coverage","passed":True})
            item["requires_visual_review"]=True
            item["review_note"]="Inspect original-size text/product plus 360px preview; automated pass is not semantic product or claim approval."
            results[job_id]=item
        if rendered:
            owner_id = next(iter(rendered))
            owner = results[owner_id]
            owner["runtime"].setdefault("batch_metrics", {}).update(shared_metrics)
            owner["runtime"]["batch_metrics"]["through_preview_seconds"] = round(time.monotonic() - start, 4)
            # Historical batch_elapsed_seconds was a repeated cumulative value.
            # Keep it only on the batch owner, explicitly non-additive.
            owner["runtime"]["batch_elapsed_seconds"] = round(time.monotonic() - start, 3)
            owner["runtime"]["batch_elapsed_measurement"] = "shared_batch_through_previews_not_per_job"
        for job_id, item in rendered.items():
            if not measure_only:
                report=output/f"{job_id}.json"
                report.write_text(json.dumps(item,ensure_ascii=False,indent=2),encoding="utf-8")
    except (LayoutError,OSError,subprocess.SubprocessError,json.JSONDecodeError) as exc:
        for j in prepared:
            if j["id"] not in results:results[j["id"]]={"passed":False,"checks":[{"check":"runtime","passed":False,"detail":str(exc)}],"bboxes":[],"output_path":None,"runtime":{}}
    return results

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--doctor",action="store_true")
    parser.add_argument("--manifest",type=Path)
    args=parser.parse_args()
    if args.doctor: result=doctor()
    elif args.manifest:
        manifest=_json(args.manifest);result=render_batch(manifest,args.manifest.parent,manifest["jobs"])
    else:parser.error("Use --doctor or --manifest PATH")
    print(json.dumps(result,ensure_ascii=False,indent=2))
