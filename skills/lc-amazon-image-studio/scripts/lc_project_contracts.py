"""Opt-in project typography and concise-copy contracts, with no model calls.

The manifest owns the contract; ``_project_style`` is its derived per-job binding.
Old manifests without these fields retain their existing copy and typography.
"""
from __future__ import annotations

import copy
import math
import re
import unicodedata
from pathlib import Path


def default_style_contract() -> dict:
    from lc_typography import default_contract
    return default_contract()


def adaptive_style_contract() -> dict:
    """Legacy V2 contract; kept unchanged for explicitly versioned projects."""
    return {"version": 2, "selection": "adaptive_per_image", "body_weight": 400,
            "label_weight": 400, "min_contrast_ratio": 4.5,
            "mobile_sizes": {"headline": 24, "body": 12, "label": 12}}


def legacy_style_contract() -> dict:
    """The original fixed-palette contract, retained for existing manifests."""
    return {"version": 1, "text_color": "#171717", "surface_color": "#F7F1E8",
            "font_family": "sans", "headline_weight": 700, "body_weight": 400,
            "label_weight": 400, "mobile_sizes": {"headline": 24, "body": 12, "label": 12}}


def default_copy_budget() -> dict:
    # A baseline is evidence supplied for an existing draft, never invented.
    return {"version": 1, "max_headline_words": 5, "max_ordinary_words": 25,
            "max_supporting_points": 3, "required_text": [], "required_fact_ids": []}


def _finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def contrast_ratio(a: str, b: str) -> float:
    def luminance(color):
        channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
        return sum(v * weight for v, weight in zip(linear, (.2126, .7152, .0722)))
    light, dark = sorted((luminance(a), luminance(b)), reverse=True)
    return (light + .05) / (dark + .05)


def validate_project_contracts(manifest: dict) -> list[str]:
    """Validate configuration only; draft copy gates are in the report/preflight."""
    errors = []
    style = manifest.get("style_contract")
    if "style_contract" in manifest:
        if not isinstance(style, dict):
            errors.append("style_contract must be an object")
        else:
            version = style.get("version", 1)
            if type(version) is not int:
                errors.append("style_contract.version must be the integer 1, 2 or 3")
                version = 0
            defaults = legacy_style_contract() if version == 1 else adaptive_style_contract() if version == 2 else default_style_contract()
            resolved = {**defaults, **style}
            if set(style) - set(defaults):
                errors.append("style_contract contains unsupported fields")
            if version == 1:
                colors_valid = True
                for key in ("text_color", "surface_color"):
                    if not isinstance(resolved[key], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", resolved[key]):
                        errors.append(f"style_contract.{key} must be #RRGGBB"); colors_valid = False
                if colors_valid and contrast_ratio(resolved["text_color"], resolved["surface_color"]) < 4.5:
                    errors.append("style_contract text/surface contrast must be at least 4.5:1; change the surface, not per-image ink")
                for key, value in (("font_family", "sans"), ("headline_weight", 700), ("body_weight", 400), ("label_weight", 400)):
                    if resolved[key] != value or isinstance(resolved[key], bool):
                        errors.append(f"style_contract.{key} must be {value}")
            elif version in {2, 3}:
                selection = "adaptive_per_image" if version == 2 else "design_first"
                if resolved["selection"] != selection:
                    errors.append(f"style_contract.selection must be {selection}")
                for key, value in (("body_weight", 400), ("label_weight", 400), ("min_contrast_ratio", 4.5)):
                    if resolved[key] != value or isinstance(resolved[key], bool):
                        errors.append(f"style_contract.{key} must be {value}")
                if version == 3:
                    from lc_typography import validate_contract
                    errors.extend(validate_contract(resolved))
            else:
                errors.append("style_contract.version must be 1, 2 or 3")
            try:
                from lc_layout import _v2_mobile_sizes
                _v2_mobile_sizes({"mobile_sizes": resolved["mobile_sizes"]})
            except (ValueError, TypeError) as exc:
                errors.append(f"style_contract.{exc}")
    budget = manifest.get("copy_budget")
    if "copy_budget" in manifest:
        if not isinstance(budget, dict):
            errors.append("copy_budget must be an object")
        else:
            known = set(default_copy_budget()) | {"baseline_words", "target_ratio", "tolerance"}
            if set(budget) - known:
                errors.append("copy_budget contains unsupported fields")
            if budget.get("version", 1) != 1:
                errors.append("copy_budget.version must be 1")
            for key in ("max_headline_words", "max_ordinary_words", "max_supporting_points"):
                n = budget.get(key, default_copy_budget()[key])
                if isinstance(n, bool) or not isinstance(n, int) or n < 1:
                    errors.append(f"copy_budget.{key} must be a positive integer")
            if "baseline_words" in budget:
                n = budget["baseline_words"]
                if isinstance(n, bool) or not isinstance(n, int) or n < 1:
                    errors.append("copy_budget.baseline_words must be the positive original rendered word count")
            elif "target_ratio" in budget or "tolerance" in budget:
                errors.append("copy_budget reduction needs an explicit baseline_words; do not invent a draft")
            target, tolerance = budget.get("target_ratio", .7), budget.get("tolerance", [.65, .75])
            if (not _finite(target) or not 0 < target < 1 or not isinstance(tolerance, list) or len(tolerance) != 2
                    or any(not _finite(v) for v in tolerance) or not 0 < tolerance[0] <= target <= tolerance[1] < 1):
                errors.append("copy_budget target_ratio must lie within finite 0..1 tolerance [minimum, maximum]")
            requirements = budget.get("required_text", [])
            job_ids = {j.get("id") for j in manifest.get("jobs", []) if isinstance(j, dict)}
            if not isinstance(requirements, list):
                errors.append("copy_budget.required_text must be a list")
            else:
                for item in requirements:
                    if isinstance(item, str) and item.strip():
                        continue
                    if (not isinstance(item, dict) or set(item) - {"text", "job_id"}
                            or not isinstance(item.get("text"), str) or not item["text"].strip()
                            or item.get("job_id") not in job_ids):
                        errors.append("required_text entries need nonempty text, optionally bound to an existing job_id")
            ids = budget.get("required_fact_ids", [])
            known_facts = {f.get("id") for f in manifest.get("facts", []) if isinstance(f, dict)}
            if not isinstance(ids, list) or any(not isinstance(v, str) or v not in known_facts for v in ids):
                errors.append("copy_budget.required_fact_ids must reference existing facts")
    return errors


def resolved_style_contract(manifest: dict) -> dict | None:
    if not isinstance(manifest.get("style_contract"), dict):
        return None
    raw = copy.deepcopy(manifest["style_contract"])
    version = raw.get("version", 1)
    defaults = legacy_style_contract() if version == 1 else adaptive_style_contract() if version == 2 else default_style_contract()
    result = {**defaults, **raw}
    result["mobile_sizes"] = {**defaults["mobile_sizes"], **result["mobile_sizes"]}
    return result


def apply_project_contracts(manifest: dict, jobs=None) -> list[str]:
    """Bind style to jobs before fingerprints/prepare; never rewrite/truncate copy.

    Returns changed job IDs. Configuration errors raise ValueError before edits.
    Removing a contract removes its derived binding without altering old layouts.
    """
    errors = validate_project_contracts(manifest)
    if errors:
        raise ValueError("; ".join(errors))
    style, changed = resolved_style_contract(manifest), []
    selected = None if jobs is None else set(jobs)
    for job in manifest.get("jobs", []):
        if selected is not None and job.get("id") not in selected:
            continue
        before = copy.deepcopy(job)
        if style is None:
            job.pop("_project_style", None)
        else:
            job["_project_style"] = copy.deepcopy(style)
            if job.get("kind") == "main":
                job["text_mode"] = "none"
            else:
                job.setdefault("text_mode", "local_overlay")
        if job != before:
            changed.append(job.get("id"))
    return changed


def style_job_issues(job: dict) -> list[str]:
    """Called by the ordinary design validator after project binding."""
    if not job.get("_project_style"):
        return []
    errors = []
    from lc_design import resolve_text_mode, has_marketing_text
    if resolve_text_mode(job) == "model_native":
        reason = job.get("model_native_reason")
        if (not isinstance(reason, dict) or reason.get("kind") not in {"artistic_lettering", "integrated_material"}
                or not isinstance(reason.get("notes"), str) or not reason["notes"].strip()):
            errors.append("model_native requires model_native_reason kind artistic_lettering/integrated_material and specific notes; ordinary copy uses local_overlay")
    elif has_marketing_text(job) and (job.get("layout") or {}).get("version") != 3:
        errors.append("project typography requires layout.version=3; migrate the layout explicitly before adopting the contract")
    return errors


def apply_style_to_layout(job: dict, layout: dict) -> dict:
    """Resolve style safeguards without rewriting approved copy or adaptive choices."""
    style = job.get("_project_style")
    if not style or layout.get("version") != 3:
        return layout
    layout = copy.deepcopy(layout)
    if style["version"] == 3:
        from lc_typography import resolve_layout
        return resolve_layout(job, layout)
    if style["version"] == 2:
        layout.setdefault("body_weight", style["body_weight"])
        layout.setdefault("label_weight", style["label_weight"])
        layout.setdefault("mobile_sizes", copy.deepcopy(style["mobile_sizes"]))
        for group in layout.get("text_groups", []):
            group.setdefault("body_weight", style["body_weight"])
            group.setdefault("label_weight", style["label_weight"])
            group.setdefault("mobile_sizes", copy.deepcopy(style["mobile_sizes"]))
        return layout
    layout.update(text_color=style["text_color"], headline_family=style["font_family"],
                  headline_weight=style["headline_weight"], body_weight=style["body_weight"],
                  label_weight=style["label_weight"], mobile_sizes=copy.deepcopy(style["mobile_sizes"]),
                  graphic_color=style["text_color"], graphic_surface_color=style["surface_color"])
    for group in layout.get("text_groups", []):
        group.update(text_color=style["text_color"], headline_family=style["font_family"],
                     headline_weight=style["headline_weight"], body_weight=style["body_weight"],
                     label_weight=style["label_weight"], mobile_sizes=copy.deepcopy(style["mobile_sizes"]))
        # Keep purposeful transparent/gradient photography treatment, while a
        # visible backing surface must share the project's surface pigment.
        surface = group.get("surface")
        if surface is None:
            group["surface"] = {"kind": "solid", "color": style["surface_color"], "opacity": 1}
        elif isinstance(surface, dict):
            surface["color"] = style["surface_color"]
    return layout


_ADAPTIVE_TONES = {
    "technical": {"ink": ["#102637", "#0B3150", "#F2FAFF", "#FFFFFF"], "surface": ["#102637", "#F0F6FA"], "family": "sans"},
    "natural": {"ink": ["#173327", "#30251F", "#FFF9EB", "#FFFFFF"], "surface": ["#173327", "#F7F1E8"], "family": "serif"},
    "premium": {"ink": ["#241811", "#4A2818", "#FFF0D4", "#FFFFFF"], "surface": ["#241811", "#FFF0D4"], "family": "serif"},
    "playful": {"ink": ["#233426", "#243B62", "#FFF7DA", "#FFFFFF"], "surface": ["#233426", "#FFF7DA"], "family": "sans"},
    "minimal": {"ink": ["#17212B", "#FFFFFF", "#111111", "#FFF8EE"], "surface": ["#17212B", "#FFFFFF"], "family": "sans"},
}


def _rgb_luminance(value: tuple[int, int, int]) -> float:
    channels = [channel / 255 for channel in value]
    linear = [channel / 12.92 if channel <= .04045 else ((channel + .055) / 1.055) ** 2.4 for channel in channels]
    return sum(channel * weight for channel, weight in zip(linear, (.2126, .7152, .0722)))


def _hex_luminance(value: str) -> float:
    return _rgb_luminance(tuple(int(value[index:index + 2], 16) for index in (1, 3, 5)))


def _pixel_contrast(ink: str, pixels: list[tuple[int, int, int]]) -> tuple[float, float]:
    foreground = _hex_luminance(ink)
    ratios = [(max(foreground, _rgb_luminance(pixel)) + .05) / (min(foreground, _rgb_luminance(pixel)) + .05)
              for pixel in pixels]
    ratios.sort()
    return (ratios[0], ratios[max(0, round((len(ratios) - 1) * .05))]) if ratios else (0.0, 0.0)


def _adaptive_tone(manifest: dict, job: dict) -> str:
    decision = job.get("typography_decision") or {}
    requested = decision.get("product_tone")
    if requested in _ADAPTIVE_TONES:
        return requested
    context = " ".join(str(value).lower() for value in (
        manifest.get("category", ""), manifest.get("product_truth", {}).get("product", ""),
        job.get("selling_job", ""), job.get("scene", ""), job.get("composition", "")))
    if any(word in context for word in ("install", "tool", "technical", "component", "hardware", "adapter")):
        return "technical"
    if any(word in context for word in ("wood", "leather", "luxury", "jewelry", "premium")):
        return "premium"
    if any(word in context for word in ("garden", "plant", "organic", "natural", "outdoor")):
        return "natural"
    if any(word in context for word in ("kids", "toy", "colorful", "playful")):
        return "playful"
    return "minimal"


def apply_adaptive_typography(manifest: dict, job: dict, base: Path) -> bool:
    """Resolve V2 local typography from the actual, text-free image layer.

    This is deterministic for one source hash and only changes local layout
    fields. It therefore never changes the already-dispatched model prompt or
    generation geometry lock.
    """
    style = job.get("_project_style") or resolved_style_contract(manifest)
    if (not style or style.get("version") != 2 or job.get("text_mode") != "local_overlay"
            or not isinstance(job.get("layout"), dict) or job["layout"].get("version") != 3
            or not job["layout"].get("text_groups") or not job.get("layout_input")):
        return False
    from PIL import Image, ImageStat
    import hashlib
    from lc_layout import layout_geometry, resolve_layout_defaults

    before_layout, before_decision = copy.deepcopy(job["layout"]), copy.deepcopy(job.get("typography_decision"))
    source = Path(base) / job["layout_input"]
    if not source.is_file():
        return False
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    resolved = resolve_layout_defaults(job)
    geometry = layout_geometry(job)
    tone = _adaptive_tone(manifest, job)
    palette = _ADAPTIVE_TONES[tone]
    existing = job.get("typography_decision") if isinstance(job.get("typography_decision"), dict) else {}
    groups_record, fingerprint_parts = {}, []
    with Image.open(source) as opened:
        image = opened.convert("RGB")
        for index, (group, slot) in enumerate(zip(job["layout"]["text_groups"], geometry["text_groups"])):
            x, y, width, height = slot["box"]
            crop = image.crop((round(x * image.width), round(y * image.height), round((x + width) * image.width), round((y + height) * image.height)))
            crop.thumbnail((96, 96))
            pixels = list(crop.get_flattened_data())
            mean = tuple(round(value) for value in ImageStat.Stat(crop).mean)
            candidates = []
            for ink in palette["ink"]:
                minimum, p05 = _pixel_contrast(ink, pixels)
                candidates.append({"color": ink, "ratio_min": round(minimum, 2), "ratio_p05": round(p05, 2)})
            valid = [candidate for candidate in candidates if candidate["ratio_min"] >= style["min_contrast_ratio"]]
            selected = max(valid, key=lambda candidate: (candidate["ratio_p05"], candidate["ratio_min"])) if valid else None
            use_surface = selected is None
            if use_surface:
                surface_color, ink = palette["surface"]
                if contrast_ratio(surface_color, ink) < style["min_contrast_ratio"]:
                    surface_color, ink = "#17212B", "#FFFFFF"
                selected = {"color": ink, "ratio_min": round(contrast_ratio(ink, surface_color), 2),
                            "ratio_p05": round(contrast_ratio(ink, surface_color), 2)}
                group["surface"] = {"kind": "solid", "color": surface_color, "opacity": .96, "padding_em": .65}
            group["text_color"] = selected["color"]
            if "headline_family" not in group and "headline_family" not in job["layout"]:
                group["headline_family"] = palette["family"]
            groups_record[group.get("id", f"group-{index}")] = {
                "dominant_color": "#{:02X}{:02X}{:02X}".format(*mean), "candidate_colors": candidates,
                "selected_color": selected["color"], "contrast_min": selected["ratio_min"],
                "contrast_p05": selected["ratio_p05"], "surface_added": use_surface,
                "headline_family": group.get("headline_family", job["layout"].get("headline_family", palette["family"])),
                "headline_treatment": copy.deepcopy(group.get("headline_treatment", {"kind": "plain"})),
            }
            fingerprint_parts.append({"id": group.get("id", index), "box": slot["box"], "pixels": groups_record[group.get("id", f"group-{index}")]["dominant_color"]})
    decision = {
        "version": 1, "rendering_route": "local_overlay", "product_tone": tone,
        "rationale": existing.get("rationale") if isinstance(existing.get("rationale"), str) and existing["rationale"].strip()
                     else "Selected from product context and the actual text-region background.",
        "background": {"path": job["layout_input"], "sha256": source_hash,
                       "fingerprint": hashlib.sha256(repr(fingerprint_parts).encode()).hexdigest(), "groups": groups_record},
    }
    job["typography_decision"] = decision
    return job["layout"] != before_layout or job.get("typography_decision") != before_decision


_WORDS = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]|[^\W_\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]+(?:[-.’'][^\W_\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]+)*", re.UNICODE)


def word_count(text: str) -> int:
    """Count visible words/numbers; CJK characters are units, never zero words."""
    # Combining vowels/accents are glyph marks, not extra words (Arabic, etc.).
    normalized = "".join(c for c in unicodedata.normalize("NFC", text) if unicodedata.category(c) != "Mn")
    return len(_WORDS.findall(normalized))


def rendered_copy_blocks(job: dict) -> list[dict]:
    from lc_design import copy_blocks
    blocks = copy_blocks(job)
    layout = job.get("layout") or {}
    if layout.get("recipe") == "steps":
        blocks += [{"id": f"step-number:{i + 1}", "role": "label", "text": str(i + 1), "evidence_refs": []}
                   for i in range(len(layout.get("panels", [])))]
    if layout.get("template") == "components":
        blocks += [{"id": f"component-number:{i + 1}", "role": "label", "text": f"{i + 1:02}", "evidence_refs": []}
                   for i in range(len(layout.get("items", [])))]
    return blocks


def _normal(text):
    return re.sub(r"\s+", " ", text).strip().casefold()


def _contains(text, phrase):
    return bool(re.search(r"(?<!\w)" + re.escape(_normal(phrase)) + r"(?!\w)", _normal(text)))


def project_contract_report(manifest: dict) -> dict:
    """Set-wide copy gate; no automatic shortening or fabricated fact reviews."""
    errors = validate_project_contracts(manifest)
    if errors:
        return {"passed": False, "issues": errors, "jobs": []}
    budget = ({**default_copy_budget(), **manifest["copy_budget"]} if "copy_budget" in manifest else None)
    jobs, total, used_facts, all_text = [], 0, set(), []
    style = resolved_style_contract(manifest)
    for source_job in manifest.get("jobs", []):
        job = dict(source_job)
        if style is not None:
            job["_project_style"] = style
        else:
            job.pop("_project_style", None)
        blocks = rendered_copy_blocks(job)
        words = sum(word_count(b["text"]) for b in blocks)
        total += words
        texts = [b["text"] for b in blocks]
        all_text.extend(texts)
        for block in blocks:
            used_facts.update(block.get("evidence_refs", []))
        issues = style_job_issues(job)
        layout = job.get("layout") or {}
        # Dense factual layouts retain their required specifications and steps.
        factual = (job.get("copy_role") in {"faq", "dimensions", "steps", "scene_grid"}
                   or layout.get("template") in {"dimensions", "components"}
                   or layout.get("recipe") in {"steps", "scene_grid"} or bool(layout.get("faq")))
        if budget and not factual:
            language = job.get("language", manifest.get("language", manifest.get("output_language", "en")))
            # CJK uses visible characters as units; two characters approximate
            # one word for density only. Existing-draft reduction counts stay exact.
            multiplier = 2 if str(language).split("-")[0] in {"zh", "ja", "ko"} else 1
            word_limit, headline_limit = budget["max_ordinary_words"] * multiplier, budget["max_headline_words"] * multiplier
            if words > word_limit:
                issues.append(f"COPY_DENSITY: {words} units exceeds {word_limit}; an explicit legacy-copy revision is required, never shrink the font")
            for block in blocks:
                if block["role"] == "headline" and word_count(block["text"]) > headline_limit:
                    issues.append(f"COPY_HEADLINE: {block['id']} exceeds {headline_limit} units")
            supporting = sum(1 for block in blocks if block["role"] != "headline")
            if supporting > budget["max_supporting_points"]:
                issues.append(f"COPY_SUPPORT: {supporting} blocks exceeds {budget['max_supporting_points']}; combine repeated points")
        jobs.append({"id": job.get("id"), "words": words, "issues": issues})
        errors.extend(f"{job.get('id')}: {issue}" for issue in issues)
    report = {"words": total, "jobs": jobs}
    if budget:
        if "baseline_words" in budget:
            baseline, tolerance = budget["baseline_words"], budget.get("tolerance", [.65, .75])
            ratio = total / baseline
            report.update(baseline_words=baseline, target_words=round(baseline * budget.get("target_ratio", .7)),
                          actual_ratio=round(ratio, 4), allowed_words=[math.ceil(baseline * tolerance[0]), math.floor(baseline * tolerance[1])])
            if not tolerance[0] <= ratio <= tolerance[1]:
                errors.append(f"COPY_BUDGET: {total}/{baseline} words ({ratio:.1%}), required {tolerance[0]:.0%}–{tolerance[1]:.0%}; edit copy while preserving required facts")
        by_id = {j.get("id"): j for j in manifest.get("jobs", [])}
        for requirement in budget.get("required_text", []):
            phrase = requirement if isinstance(requirement, str) else requirement["text"]
            texts = all_text if isinstance(requirement, str) else [b["text"] for b in rendered_copy_blocks(by_id[requirement["job_id"]])]
            if not any(_contains(text, phrase) for text in texts):
                errors.append(f"COPY_REQUIRED_TEXT_MISSING: {phrase}")
        for fact in budget.get("required_fact_ids", []):
            if fact not in used_facts:
                errors.append(f"COPY_REQUIRED_FACT_MISSING: {fact}; retain a visible block bound to this fact")
    report.update(passed=not errors, issues=errors)
    return report


def preflight_project_contracts(manifest: dict, base: Path, jobs: list[dict] | None = None) -> dict:
    """Cheap pre-dispatch checks: contracts, geometry, glyph coverage and sizes.

    This is a planning check, never a product/layout review verdict. Actual
    raster contrast and text fit remain mandatory in the existing renderer.
    """
    report = project_contract_report(manifest)
    if not report["passed"]:
        return report
    from lc_design import resolve_text_mode
    import lc_layout as renderer
    checks = []
    for job in manifest.get("jobs", []) if jobs is None else jobs:
        if not job.get("_project_style") or resolve_text_mode(job) != "local_overlay":
            continue
        try:
            layout = renderer.resolve_layout_defaults(job)
            renderer.validate_layout_v3(layout)
            renderer.layout_geometry(job)
            # Use the families and weights the adaptive layout actually asks
            # for. This remains a cheap glyph gate; the measurement renderer
            # below is the authoritative per-role font and fit check.
            groups = layout.get("text_groups", [])
            families = {group.get("headline_family", layout.get("headline_family", "sans")) for group in groups}
            weights = {400}
            for group in groups:
                if group.get("headline"):
                    weights.add(group.get("headline_weight", layout.get("headline_weight", 600)))
                if group.get("label"):
                    weights.add(group.get("label_weight", layout.get("label_weight", 400)))
            required = {ord(char) for block in rendered_copy_blocks(job) for char in block["text"]
                        if not char.isspace() and char not in "\u200c\u200d\u200e\u200f"}
            coverage = {weight: set() for weight in weights}
            for _, weight, name in renderer._font_records(3, "serif" if "serif" in families else "sans"):
                if weight not in coverage:
                    continue
                path = renderer.ASSETS / "fonts" / name
                coverage[weight].update(renderer._font_cmap(str(path), renderer.file_hash(path)))
            missing = required - set.intersection(*(coverage[weight] for weight in weights))
            if missing:
                raise ValueError("missing bundled glyphs: " + ", ".join(f"U+{codepoint:04X}" for codepoint in sorted(missing)))
            checks.append({"id": job.get("id"), "passed": True})
        except (ValueError, TypeError, KeyError, OSError) as exc:
            issue = f"{job.get('id')}: TYPOGRAPHY_PREFLIGHT: {exc}"
            report["issues"].append(issue)
            checks.append({"id": job.get("id"), "passed": False, "issue": issue})
    report.update(passed=not report["issues"], typography_preflight=checks)
    return report


def preflight_layout_fit(manifest: dict, base: Path, jobs=None) -> dict:
    """Measure planned text with the real renderer before paying for generation.

    Synthetic placeholders supply geometry only: their contrast/product pixels
    cannot approve an image. Results are cached per selected job's exact layout
    and source aspect ratios; temporary geometry inputs are discarded immediately.
    """
    import hashlib
    import json
    import tempfile
    from PIL import Image
    import lc_layout as renderer
    from lc_design import resolve_text_mode

    selected = None if jobs is None else set(jobs)
    candidates = [j for j in manifest.get("jobs", [])
                  if (selected is None or j.get("id") in selected) and j.get("_project_style")
                  and resolve_text_mode(j) == "local_overlay" and rendered_copy_blocks(j)]
    base, results, pending = Path(base), [], []
    with tempfile.TemporaryDirectory(prefix="lc-typography-preflight-") as temporary:
        temporary = Path(temporary)
        for job in candidates:
            try:
                candidate = copy.deepcopy(job)
                resolved = renderer.resolve_layout_defaults(job)
                dimensions, placeholders = {}, []
                for collection in ("panels", "items"):
                    for index, item in enumerate(resolved.get(collection, [])):
                        if not item.get("image"):
                            continue
                        source = renderer._project_file(base, item["image"])
                        with Image.open(source) as image:
                            size = image.size
                        dimensions[f"{collection}:{index}"] = list(size)
                        # Pixel content is deliberately excluded from a text-fit
                        # observation; crop/source edits still invalidate final QA.
                        name = f"{job['id']}-{collection}-{index}.png"
                        placeholders.append((name, size))
                        item["image"] = name
                identity = {"layout": renderer.layout_fingerprint(manifest, job), "source_sizes": dimensions,
                            "planned_product": job.get("target_product_bbox_norm")}
                digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
                previous = job.get("typography_preflight") or {}
                if previous.get("fingerprint") == digest:
                    results.append({"id": job["id"], **copy.deepcopy(previous), "cached": True})
                    continue
                for name, size in placeholders:
                    Image.new("RGB", size, "#F7F1E8").save(temporary / name)
                candidate["layout"] = resolved
                candidate["layout_input"] = f"{job['id']}-canvas.png"
                candidate["output_product_bbox_norm"] = job.get("target_product_bbox_norm")
                Image.new("RGB", tuple(job["canvas"]), "#F7F1E8").save(temporary / candidate["layout_input"])
                pending.append((job, candidate, digest))
            except (ValueError, OSError, KeyError, TypeError) as exc:
                results.append({"id": job.get("id"), "passed": False, "checks": [{"check": "typography_preflight", "passed": False, "detail": str(exc)}]})
        if pending:
            rendered = renderer.render_batch(manifest, temporary, [item[1] for item in pending], measure_only=True)
            for job, _, digest in pending:
                result = rendered.get(job["id"], {})
                checks = [check for check in result.get("checks", []) if check.get("check") != "text_contrast"]
                if not checks:
                    checks = [{"check": "renderer", "passed": False, "detail": "No typography measurements returned"}]
                record = {"fingerprint": digest, "passed": all(c.get("passed") is True for c in checks),
                          "checks": checks, "purpose": "planned_text_fit_only"}
                job["typography_preflight"] = record
                results.append({"id": job["id"], **copy.deepcopy(record), "cached": False})
    return {"passed": all(r["passed"] for r in results), "jobs": results,
            "issues": [f"{r['id']}: TYPOGRAPHY_PREFLIGHT: enlarge or recompose its planned region; preserve approved copy"
                       for r in results if not r["passed"]]}
