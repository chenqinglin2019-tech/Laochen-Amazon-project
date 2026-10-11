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


ANSWERS_SCHEMA = "lc-review-answers/1"
EXPLICIT_FIELDS = ("model_text_review", "panel_reviews", "title_effect_review")
PEOPLE = {"none": "none", "synthetic": "synthetic", "real": "real", "non_photorealistic": "non_photorealistic"}
_PEOPLE_WORDS = ("person", "people", "woman", "women", "man ", "men ", "hand", "hands", "model wearing", "child", "kid",
                 "baby", "user holding", "holding", "人", "手", "模特", "宝宝", "孩子")


def _people_planned(job):
    text = " ".join(str(job.get(key) or "") for key in ("selling_job", "scene", "composition"))
    text += " " + json.dumps((job.get("layout") or {}).get("text_groups", []), ensure_ascii=False)
    text += " " + json.dumps(((job.get("design_brief") or {}).get("generation") or {}), ensure_ascii=False)
    lowered = f" {text.lower()} "
    return any(word in lowered for word in _PEOPLE_WORDS)


def _measured_readability(job):
    """pass + numbers when every measured glyph-contrast and text-fit check passed, else None."""
    checks = (job.get("layout_result") or {}).get("checks") or []
    contrast = [c for c in checks if c.get("check") == "glyph_contrast"]
    fit = [c for c in checks if c.get("check") in {"text_fit", "text_group_fit"}]
    if not contrast or not fit or not all(c.get("passed") for c in contrast + fit):
        return None
    minimum = min(float(c.get("ratio_min") or 0) for c in contrast)
    return f"Measured on the final render: glyph-core contrast >= {minimum:.2f}:1 (min 4.5) and all text fits its region."


def prefill_for(manifest, job, packet):
    """Deterministic review values, all valid under the unchanged QA rules."""
    import lc_image_pipeline as p
    reviews = packet.get("reviews", {})
    prefill, hidden = {}, set()

    def put(field, key, verdict, notes, hide=True):
        if key in reviews.get(field, {}) and (reviews[field][key] or {}).get("verdict") is None:
            prefill[f"{field}.{key}"] = {"verdict": verdict, "notes": notes}
            if hide:
                hidden.add(f"{field}.{key}")
    is_main, text = job.get("kind") == "main", p.has_text(job)
    if not is_main:
        put("policy_qa_results", "main_product_only", "not_applicable", "Not the main image; the main-image-only rule does not apply.")
    else:
        put("semantic_qa_results", "scene_scale", "not_applicable", "Main image: product alone on white; no scene to scale.")
    if not text:
        for key in ("text_readability", "mobile_readability"):
            put("policy_qa_results", key, "not_applicable", "No marketing text in this image.")
        if job.get("text_mode") == "none":
            put("policy_qa_results", "visual_design", "pass", "No marketing text or graphics; composition judged in the overall observation.")
    else:
        measured = _measured_readability(job)
        if measured:
            for key in ("text_readability", "mobile_readability"):
                put("policy_qa_results", key, "pass", measured, hide=False)
    if manifest is not None and manifest.get("anchor_job_id") == job.get("id"):
        try:
            from lc_anchor import anchor_quick_proof_valid
            if anchor_quick_proof_valid(manifest, job, Path(packet.get("_base", "."))):
                for key in ("geometry", "material", "components", "clarity"):
                    put("semantic_qa_results", key, "pass", "Confirmed by the bound anchor product check of this exact raw image.", hide=False)
        except Exception:  # noqa: BLE001 - a prefill is optional
            pass
    people_required = _people_planned(job)
    if not people_required:
        prefill["ai_disclosure"] = {"human_source": "none", "notes": "No person planned; set 'people' if one appears in the image."}
    explicit = [field for field in EXPLICIT_FIELDS if field in reviews]
    from lc_composition import applies
    if manifest is not None and applies(manifest, job):
        explicit.append("visual_design")
    return {"schema": "lc-review-prefill/1", "job": job.get("id"), "review_id": packet.get("review_id"),
            "values": prefill, "hidden": sorted(hidden), "people_required": people_required, "explicit": explicit}


def write_prefill(base, packet_path, manifest, job):
    base = Path(base).resolve()
    packet = json.loads(Path(packet_path).read_text(encoding="utf-8"))
    packet["_base"] = str(base)
    record = prefill_for(manifest, job, packet)
    out = base / "review" / "packets" / f"{packet['job']}.prefill.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    keys = [f"{field}.{key}" for field, values in packet.get("reviews", {}).items()
            if field not in EXPLICIT_FIELDS and field != "ai_disclosure" and isinstance(values, dict) for key in values]
    to_check = [key for key in keys if key not in record["hidden"]]
    return {"rid": packet["review_id"][:8], "check": to_check, "people_required": record["people_required"],
            "explicit": record["explicit"]}


def write_answers_template(base, entries):
    """One file the agent fills for the whole batch (exceptions-only review)."""
    base = Path(base).resolve()
    answers = {}
    for entry in entries:
        item = {"rid": entry["rid"], "observation": "", "exceptions": {}}
        if entry.get("people_required"):
            item["people"] = ""
        for field in entry.get("explicit", []):
            item.setdefault("explicit", {})[field] = None
        answers[entry["job"]] = item
    template = {"schema": ANSWERS_SCHEMA, "answers": answers,
                "how": ("For each image: look at its sheet, write one specific observation (>=20 chars, different per image). "
                        "Every listed check not in 'exceptions' is recorded as pass with that observation; put only failed or "
                        "doubtful checks in exceptions as {\"<field>.<key>\": {\"verdict\": \"fail\", \"notes\": \"...\"}}. "
                        "people: none/synthetic/real/non_photorealistic when a person may appear. Then review-submit --packet <this file>.")}
    out = base / "review" / "packets" / "answers.template.json"
    out.write_text(json.dumps(template, ensure_ascii=False, indent=1), encoding="utf-8")
    return out.relative_to(base).as_posix()


def _expand_answers(base, payload):
    answers = payload.get("answers")
    if not isinstance(answers, dict) or not answers:
        raise ValueError("Review answers need a nonempty 'answers' map keyed by job id")
    packets, problems, seen = [], [], {}
    for job_id, answer in answers.items():
        where = f"{job_id}:"
        todo_path = base / "review" / "packets" / f"{job_id}.todo.json"
        prefill_path = base / "review" / "packets" / f"{job_id}.prefill.json"
        if not isinstance(answer, dict) or not todo_path.is_file() or not prefill_path.is_file():
            problems.append(f"{where} no prepared review; run review-prepare first")
            continue
        todo = json.loads(todo_path.read_text(encoding="utf-8"))
        prefill = json.loads(prefill_path.read_text(encoding="utf-8"))
        packet_path = (base / todo["packet"]).resolve()
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        rid = str(answer.get("rid") or "")
        if (not rid or not packet.get("review_id", "").startswith(rid) or prefill.get("review_id") != packet.get("review_id")
                or todo.get("review_id") != packet.get("review_id")):
            problems.append(f"{where} STALE_REVIEW_PACKET: rid does not match the latest review packet; re-run review-prepare")
            continue
        observation = str(answer.get("observation") or "").strip()
        if len(observation) < 20:
            problems.append(f"{where} observation must describe what you saw (>= 20 characters)")
            continue
        if observation.lower() in seen:
            problems.append(f"{where} observation duplicates {seen[observation.lower()]}; describe this image specifically")
            continue
        seen[observation.lower()] = job_id
        reviews = copy.deepcopy(packet.get("reviews", {}))
        for dotted, value in prefill.get("values", {}).items():
            if dotted == "ai_disclosure":
                reviews["ai_disclosure"] = copy.deepcopy(value)
                continue
            field, key = dotted.split(".", 1)
            if key in reviews.get(field, {}):
                reviews[field][key] = copy.deepcopy(value)
        exceptions = answer.get("exceptions") or {}
        if not isinstance(exceptions, dict):
            problems.append(f"{where} exceptions must be an object")
            continue
        bad = []
        for dotted, value in exceptions.items():
            field, _, key = str(dotted).partition(".")
            if (field in EXPLICIT_FIELDS or field == "ai_disclosure" or key not in reviews.get(field, {})
                    or not isinstance(value, dict) or value.get("verdict") not in {"pass", "fail", "not_applicable"}
                    or not str(value.get("notes") or "").strip()):
                bad.append(str(dotted))
                continue
            reviews[field][key] = {"verdict": value["verdict"], "notes": str(value["notes"]).strip()}
        if bad:
            problems.append(f"{where} unknown or incomplete exceptions {bad}; use <field>.<key> with verdict and notes")
            continue
        for field, values in reviews.items():
            if field in EXPLICIT_FIELDS or field == "ai_disclosure" or not isinstance(values, dict):
                continue
            for key, value in values.items():
                if isinstance(value, dict) and value.get("verdict") is None:
                    values[key] = {"verdict": "pass", "notes": f"Reviewed on the sheet: {observation}"}
        people = answer.get("people")
        if people:
            if people not in PEOPLE:
                problems.append(f"{where} people must be one of {sorted(PEOPLE)}")
                continue
            reviews["ai_disclosure"] = {"human_source": PEOPLE[people], "notes": f"Observed on the sheet: {observation}"}
        elif prefill.get("people_required") or (reviews.get("ai_disclosure") or {}).get("human_source") in {None, "unknown"}:
            problems.append(f"{where} a person may appear: set people to none/synthetic/real/non_photorealistic")
            continue
        explicit = answer.get("explicit") or {}
        missing_explicit = [field for field in prefill.get("explicit", []) if not explicit.get(field)]
        if missing_explicit:
            problems.append(f"{where} fill the explicit review fields {missing_explicit} (see the todo guidance)")
            continue
        for field in prefill.get("explicit", []):
            if field == "visual_design":
                reviews.setdefault("policy_qa_results", {})[field] = copy.deepcopy(explicit[field])
            else:
                reviews[field] = copy.deepcopy(explicit[field])
        packet["reviews"] = reviews
        packets.append(packet)
    if problems:
        raise ValueError("Review answers rejected (nothing submitted):\n- " + "\n- ".join(problems))
    return packets


def expand_todos(base, payload):
    """Turn compact todos (single, list or map) or exceptions-only answers into full bound packets."""
    base = Path(base).resolve()
    if isinstance(payload, dict) and payload.get("schema") == ANSWERS_SCHEMA:
        return _expand_answers(base, payload)

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
