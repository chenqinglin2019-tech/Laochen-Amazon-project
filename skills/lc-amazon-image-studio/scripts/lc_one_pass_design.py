"""Compile complete image designs, approved text and pinned template snapshots."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from lc_one_pass_io import StudioError, digest, inside, sha256, write_bytes

ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")
NUMBERS = re.compile(r"\d+(?:[.,]\d+)?")
ROLES = {"headline", "body", "label", "dimension", "step", "faq_question", "faq_answer", "brand"}


def canvas_valid(value):
    return (isinstance(value, list) and len(value) == 2
            and all(type(n) is int and 1 <= n <= 10000 for n in value)
            and value[0] * value[1] <= 40_000_000)


def meaningful(value):
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(meaningful(item) for item in value.values())
    if isinstance(value, list):
        return any(meaningful(item) for item in value)
    return value is not None and value is not False


def validate_project(manifest):
    if manifest.get("workflow_policy") != "one_pass_v1":
        raise StudioError("UNKNOWN_WORKFLOW_POLICY")
    if not ID.fullmatch(str(manifest.get("project_id", ""))):
        raise StudioError("INVALID_PROJECT_ID")
    if not str(manifest.get("marketplace", "")).strip() or not re.fullmatch(
            r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", str(manifest.get("language", ""))):
        raise StudioError("MARKETPLACE_AND_LANGUAGE_REQUIRED")
    if type(manifest.get("concurrency")) is not int or not 1 <= manifest["concurrency"] <= 32:
        raise StudioError("INVALID_CONCURRENCY")
    jobs = manifest.get("jobs")
    if not isinstance(jobs, list) or not jobs or any(not isinstance(job, dict) for job in jobs):
        raise StudioError("JOBS_REQUIRED")
    ids = [job.get("id") for job in jobs]
    if any(not isinstance(value, str) or not ID.fullmatch(value) for value in ids) or len(set(ids)) != len(ids):
        raise StudioError("INVALID_OR_DUPLICATE_JOB_ID")
    for job in jobs:
        if job.get("kind") not in {"main", "secondary", "a_plus"} or not canvas_valid(job.get("canvas")):
            raise StudioError(f"INVALID_JOB_SPEC:{job['id']}")
        if job["kind"] != "a_plus" and min(job["canvas"]) < 1600:
            raise StudioError(f"LISTING_CANVAS_TOO_SMALL:{job['id']}")
        if job.get("status") not in {"pending", "generating", "awaiting_result", "main_background_pending",
                                     "ready_to_deliver", "needs_input", "failed", "blocked"}:
            raise StudioError("INVALID_JOB_STATUS")
        if not isinstance(job.get("generation_attempts"), list):
            raise StudioError("INVALID_GENERATION_ATTEMPTS")
        if "main_foreground_type" in job and (job["kind"] != "main" or
                job["main_foreground_type"] not in ("opaque", "translucent", "unknown")):
            raise StudioError("INVALID_MAIN_FOREGROUND_TYPE")
        if "main_prompt_version" in job and (type(job["main_prompt_version"]) is not int or
                job["main_prompt_version"] not in (1, 2)):
            raise StudioError("UNKNOWN_MAIN_PROMPT_VERSION")
        if "main_processing_version" in job and (type(job["main_processing_version"]) is not int or
                job["main_processing_version"] != 1):
            raise StudioError("UNKNOWN_MAIN_PROCESSING_VERSION")
    refs = manifest.get("references", [])
    if not isinstance(refs, list) or any(not isinstance(ref, dict) for ref in refs):
        raise StudioError("INVALID_REFERENCES")
    ref_ids = [ref.get("id") for ref in refs]
    if any(not isinstance(value, str) or not ID.fullmatch(value) for value in ref_ids) or len(set(ref_ids)) != len(ref_ids):
        raise StudioError("INVALID_OR_DUPLICATE_REFERENCE_ID")
    for ref in refs:
        if (ref.get("role") not in {"product", "style"} or not isinstance(ref.get("path"), str)
                or not ref["path"] or not re.fullmatch(r"[0-9a-f]{64}", str(ref.get("sha256", "")))):
            raise StudioError("INVALID_REFERENCE_RECORD")


def _reference(manifest, base, reference):
    path = inside(base, reference["path"])
    if sha256(path) != reference.get("sha256"):
        raise StudioError(f"REFERENCE_CHANGED:{reference['id']}")
    return {"path": reference["path"], "sha256": reference["sha256"],
            "role": reference.get("role", "product"), "id": reference["id"],
            "view": reference.get("view", "unspecified")}


def adopt_templates(manifest, base):
    """Read existing libraries once. Never compile their local layout workflows."""
    snapshot = manifest.get("template_snapshot")
    if snapshot is not None:
        if digest(snapshot["data"]) != snapshot.get("sha256"):
            raise StudioError("TEMPLATE_SNAPSHOT_CHANGED")
        for asset in snapshot["data"].get("assets", {}).values():
            if sha256(inside(base, asset["path"])) != asset["sha256"]:
                raise StudioError("TEMPLATE_ASSET_CHANGED")
        return
    from lc_template_library import Library
    from lc_template_select import candidate_families, recommend, slot_match
    library_dir = manifest.get("design_template_library_dir")
    if library_dir and not Path(library_dir).is_absolute():
        library_dir = str(inside(base, library_dir))
    library = Library(library_dir)
    rows = candidate_families(manifest, base, library)
    wanted = manifest.get("design_template_set_id")
    selected = ({"id": wanted} if wanted else recommend(manifest, base, library=library)["selected"])
    row = next((item for item in rows if selected and item[0]["id"] == selected["id"]), None)
    if wanted and row is None:
        raise StudioError("SELECTED_TEMPLATE_NOT_FOUND")
    data = {"family": None, "jobs": {}, "assets": {}}
    if row:
        family, templates, source, schema = row
        data["family"] = {"id": family["id"], "revision": family["revision"],
                          "design": copy.deepcopy(family.get("tokens") if schema == 2 else family.get("style")),
                          "avoid": family.get("avoid", [])}
        used = {}
        for job in manifest["jobs"]:
            if job["kind"] == "main":
                continue
            match = slot_match(row, rows, job, used=used)
            template = match.get("template")
            if schema == 1:
                role = match["slot_role"]
                template = next((item for item in templates if role in item.get("intents", [])
                                 and job["kind"] in item.get("kinds", [])), None)
            if not template:
                continue
            used[template["id"]] = used.get(template["id"], 0) + 1
            # Template geometry expresses design intent; no font measurement or renderer.
            data["jobs"][job["id"]] = {key: copy.deepcopy(template[key]) for key in
                ("id", "revision", "recipe", "generation", "layout", "avoid") if key in template}
            if schema == 2 and match["match"] in {"observed", "adapted"}:
                plate_hash = template.get("assets", {}).get("plate_sha256")
                if plate_hash:
                    source_path = library.asset_path(plate_hash)
                    if source_path.is_symlink() or sha256(source_path) != plate_hash:
                        raise StudioError("TEMPLATE_PLATE_HASH_MISMATCH")
                    relative = f"design/plates/{plate_hash}{source_path.suffix}"
                    write_bytes(inside(base, relative), source_path.read_bytes(), immutable=True)
                    data["assets"][job["id"]] = {"path": relative, "sha256": plate_hash,
                                                         "role": "style", "id": "template_plate"}
    manifest["template_snapshot"] = {"data": data, "sha256": digest(data)}


def compile_design(manifest, job, base, *, repair=False):
    truth = manifest.get("product_truth") or {}
    if not isinstance(truth, dict) or not meaningful(truth.get("product")):
        raise StudioError("PRODUCT_IDENTITY_REQUIRED")
    for key in ("geometry_lock", "material_lock", "scene_scale_lock"):
        if not meaningful(truth.get(key)):
            raise StudioError(f"PRODUCT_LOCK_REQUIRED:{key}")
    details = manifest.get("critical_details")
    if not isinstance(details, list):
        raise StudioError("CRITICAL_DETAILS_LIST_REQUIRED")
    refs = {ref["id"]: ref for ref in manifest.get("references", [])}
    selected = job.get("source_reference_ids")
    if selected is None:
        selected = [key for key, ref in refs.items() if ref.get("role", "product") == "product"]
    if (not isinstance(selected, list) or not selected or any(not isinstance(value, str) for value in selected)
            or len(set(selected)) != len(selected)):
        raise StudioError("PRODUCT_REFERENCES_REQUIRED")
    bindings = []
    for identifier in selected:
        if identifier not in refs or refs[identifier].get("role", "product") != "product":
            raise StudioError("INVALID_PRODUCT_REFERENCE")
        bindings.append(_reference(manifest, base, refs[identifier]))
    for detail in details:
        if not isinstance(detail, dict):
            raise StudioError("INVALID_CRITICAL_DETAIL")
        visibility = detail.get("visibility") or {}
        if not isinstance(visibility, dict):
            raise StudioError("INVALID_DETAIL_VISIBILITY")
        if detail.get("priority") in {"P0", "P1"} and visibility.get(job["id"]) == "required":
            locations = detail.get("locations") or []
            if not isinstance(locations, list) or any(not isinstance(location, dict) for location in locations):
                raise StudioError("INVALID_DETAIL_LOCATIONS")
            evidence = detail.get("evidence_refs", []) or [location.get("reference_id") for location in locations]
            if not evidence or any(identifier not in selected for identifier in evidence):
                raise StudioError("REQUIRED_DETAIL_EVIDENCE_MISSING")
    brief = job.get("design_brief") or {}
    if not isinstance(brief, dict) or any(not meaningful(brief.get(key)) for key in ("goal", "scene", "composition")):
        raise StudioError("DESIGN_BRIEF_REQUIRED:goal,scene,composition")
    human_source = job.get("human_source", "none")
    if not isinstance(human_source, str) or human_source not in {"none", "synthetic", "real", "non_photorealistic"}:
        raise StudioError("HUMAN_SOURCE_INTENT_REQUIRED")
    if not isinstance(job.get("export_keywords", []), list) or any(not isinstance(item, str) for item in job.get("export_keywords", [])):
        raise StudioError("INVALID_EXPORT_KEYWORDS")
    facts_list = manifest.get("facts", [])
    if not isinstance(facts_list, list) or any(not isinstance(fact, dict) for fact in facts_list):
        raise StudioError("INVALID_FACTS")
    if any(not isinstance(fact.get("id"), str) or not ID.fullmatch(fact["id"]) for fact in facts_list):
        raise StudioError("INVALID_OR_DUPLICATE_FACT_ID")
    facts = {fact.get("id"): fact for fact in facts_list}
    if len(facts) != len(facts_list) or any(not isinstance(key, str) or not ID.fullmatch(key) for key in facts):
        raise StudioError("INVALID_OR_DUPLICATE_FACT_ID")
    blocks = job.get("approved_copy", [])
    if not isinstance(blocks, list):
        raise StudioError("APPROVED_COPY_MUST_BE_LIST")
    if job["kind"] == "main" and blocks:
        raise StudioError("MAIN_MARKETING_TEXT_FORBIDDEN")
    copy_lines = []
    for block in blocks:
        if not isinstance(block, dict) or block.get("role") not in ROLES or not isinstance(block.get("text"), str) or not block["text"].strip():
            raise StudioError("INVALID_APPROVED_COPY_BLOCK")
        ids = block.get("fact_ids", [])
        if not isinstance(ids, list) or any(not isinstance(key, str) or key not in facts for key in ids):
            raise StudioError("COPY_FACT_NOT_FOUND")
        for key in ids:
            if not meaningful(facts[key].get("source")) or not meaningful(facts[key].get("value")):
                raise StudioError("COPY_FACT_SOURCE_REQUIRED")
        text = block["text"]
        if block["role"] == "step":
            text = re.sub(r"^\s*\d+[.)]\s*", "", text)
        supported = NUMBERS.findall(" ".join(str(facts[key].get("value", "")) + " " + str(facts[key].get("unit", "")) for key in ids))
        if any(number not in supported for number in NUMBERS.findall(text)):
            raise StudioError("NUMERIC_COPY_FACT_REQUIRED")
        for key in ids:
            value, unit = str(facts[key]["value"]), str(facts[key].get("unit") or "")
            if unit and NUMBERS.search(value) and value in text:
                if not re.search(re.escape(value) + r"\s*" + re.escape(unit) + r"(?![A-Za-z])", text):
                    raise StudioError("COPY_FACT_UNIT_MISMATCH")
        copy_lines.append(f"{block['role']}: {json.dumps(block['text'], ensure_ascii=False)}")
    snapshot = manifest.get("template_snapshot", {}).get("data", {})
    template = snapshot.get("jobs", {}).get(job["id"], {})
    style = {"suite": manifest.get("style_contract", {}), "family": snapshot.get("family"),
             "image_design": template, "explicit": brief.get("style", {})}
    if job["kind"] != "main":
        for reference in refs.values():
            if reference.get("role") == "style":
                bindings.append(_reference(manifest, base, reference))
        plate = snapshot.get("assets", {}).get(job["id"])
        if plate:
            if sha256(inside(base, plate["path"])) != plate["sha256"]:
                raise StudioError("TEMPLATE_ASSET_CHANGED")
            bindings.append(copy.deepcopy(plate))
    if repair:
        target = job["background_repair_target"]
        if sha256(inside(base, target["path"])) != target["sha256"]:
            raise StudioError("BACKGROUND_REPAIR_TARGET_CHANGED")
        bindings = [{**target, "role": "edit_target", "id": "main_edit_target"}, *bindings]
    captions = "\n".join(f"Image {i}: {item['role']} / {item['id']} / {item.get('view', '')}" for i, item in enumerate(bindings, 1))
    encode = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True)
    if repair:
        request = ("Extract the product in Image 1 onto a genuinely transparent background. Change only background separation; "
                   "keep product geometry, color, texture, labels and included components unchanged. Remove external shadows; "
                   "preserve holes, translucent materials and antialiased product edges. Return real RGBA, not a checkerboard.")
    elif job["kind"] == "main":
        request = ("Generate the exact product and included components as a complete catalog image on a genuinely transparent "
                   "RGBA background. No marketing text, props, external shadow or checkerboard. Preserve real product labels. "
                   "Keep the whole product visible and clear of all canvas edges; leave all external background and holes transparent.")
    else:
        request = ("Produce the finished commercial image in one pass: product, scene, complete typography, annotations and layout. "
                   "Design the supplied copy as part of the final image, rendering every approved string verbatim. "
                   "Use clear visual hierarchy, readable text and balanced product scale.")
    if job["kind"] == "main" and job.get("main_prompt_version", 1) == 2:
        request += (" Keep the complete assembly, including thin and dangling parts, within about 90 percent of the canvas "
                    "width and height, with clear transparent margins on every side. Do not crop any product part. "
                    "No external cast shadow, reflection, opaque background or faint background haze.")
    prompt = "\n\n".join([
        f"1. IMAGE GOAL\n{request}\nSlot: {job['id']} ({job['kind']}); goal: {brief['goal']}. "
        f"Canvas: {job['canvas'][0]}x{job['canvas'][1]}; language: {manifest['language']}; marketplace: {manifest['marketplace']}.",
        f"2. PRODUCT EVIDENCE AND LOCKS\n{captions}\nVerified product facts: {encode(truth)}\n"
        f"Critical details: {encode(details)}\nSupported claims: {encode([facts[key] for key in facts])}",
        f"3. SCENE AND COMPOSITION\n{encode({key: value for key, value in brief.items() if key != 'style'})}\nHuman source intent: {human_source}."
        + (" Do not add people or body parts." if human_source == "none" else ""),
        f"4. SUITE DESIGN\n{encode(style if job['kind'] != 'main' else {'photography': brief.get('lighting', 'neutral studio light')})}",
        "5. APPROVED COPY (VERBATIM, IN READING ORDER)\n" + ("\n".join(copy_lines) if copy_lines else "No added marketing copy for this slot."),
        "6. CONSTRAINTS\nProduct evidence controls identity, geometry, materials, scale and critical details. "
        "Never invent unknown dimensions, hidden parts, accessories, certifications or performance claims. "
        "Style inputs are design references only: never copy their product, brand, logo, sample copy or claims. "
        "Use only the supplied marketing copy. No watermark, sales buttons or unsupported badges."
    ])
    fingerprint = digest({"version": "one_pass_v1", "prompt": prompt, "references": bindings,
                          "transparent_background": job["kind"] == "main"})
    return {"prompt": prompt, "prompt_hash": digest(prompt), "generation_fingerprint": fingerprint,
            "references": bindings, "transparent_background": job["kind"] == "main"}
