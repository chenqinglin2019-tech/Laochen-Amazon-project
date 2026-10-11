#!/usr/bin/env python3
"""易逊-亚马逊套图生成 V8: one-shot designed images (agent-chosen template -> one image call -> deliver).

    init        create a project, register photos (and --refs), return slots + template catalog
    add-photos  register more product photos
    add-refs    register reference images (never product photos; only their colour/light can be borrowed)
    templates   template catalog (or --family F for full records)
    plan        validate plan.json, compile prompts, build a photo main image, reserve wave 1   [auth pass]
    reserve     reserve the next wave of image calls
    ingest-batch  record results (--item/--failed/--not-started/--redo/--recast/--reject/--people) and get the next wave
    deliver     final image files only                                                       [auth pass]
    status      read-only overview
    reset       fresh retry budget for a failed image (after the user agrees)

Every command prints one JSON line and exits 2 on error.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
RELAUNCH_MARKER = "LC_RUNTIME_RELAUNCHED"
GUIDANCE = ("Pillow and NumPy are required. Run `python scripts/runtime_bootstrap.py verify --json` from the skill root "
            "(installs are separate and need the user's confirmation), then use its commands.python.")


def _ensure_runtime():
    try:
        import numpy  # noqa: F401
        import PIL  # noqa: F401
        return
    except ImportError:
        pass
    if os.environ.get(RELAUNCH_MARKER) != "1":
        try:
            from runtime_bootstrap import RuntimeBootstrap
            python = (RuntimeBootstrap()._selection() or {}).get("python")
        except Exception:  # noqa: BLE001
            python = None
        if isinstance(python, str) and Path(python).is_file() and Path(python).absolute() != Path(sys.executable).absolute():
            import subprocess
            env = dict(os.environ, **{RELAUNCH_MARKER: "1"})
            raise SystemExit(subprocess.run([python, "-X", "utf8", *sys.argv], env=env).returncode)
    raise SystemExit(GUIDANCE)


def _safe(value):
    if isinstance(value, str):
        return value.encode("utf-8", "replace").decode("utf-8")
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    return value


def emit(command, payload, *, ok=True, project=None):
    record = {"ok": ok, "command": command, **({"project": str(project)} if project else {}), **_safe(payload)}
    text = json.dumps(record, ensure_ascii=False)
    try:
        sys.stdout.write(text + "\n")
    except UnicodeEncodeError:
        sys.stdout.buffer.write((text + "\n").encode("utf-8"))
    sys.stdout.flush()


def _auth_gate(command):
    """Same production gate as V7: a short-lived pass written by scripts/auth_gate.py."""
    if command in {"plan", "deliver"}:
        from lc_auth_pass import check_pass
        passed, reason = check_pass(SCRIPT_DIR.parent)
        if not passed:
            from studio_project import StudioError
            raise StudioError(reason, code="AUTH_PASS_REQUIRED")


# ---------------------------------------------------------------- helpers

def _catalog(project, project_dir, library_dir=None):
    import studio_catalog
    catalog = studio_catalog.load(library_dir)
    return catalog, studio_catalog.compact(catalog, project, project_dir)


def _photo(project, photo_id):
    return next(photo for photo in project["photos"] if photo["id"] == photo_id)


def _reference_photos(project, project_dir, photo_ids, hide):
    """Photo dicts for the prompt (with `hidden`) and the files to attach (hidden copies where asked)."""
    import studio_refs
    photos, paths = [], []
    for photo_id in photo_ids or []:
        photo = dict(_photo(project, photo_id))
        boxes = (hide or {}).get(photo_id)
        if boxes:
            photo["hidden"] = True
            paths.append(studio_refs.hidden_copy(project_dir, photo, boxes))
        else:
            paths.append(photo["path"])
        photos.append(photo)
    return photos, paths


def _tone_for(entry, catalog, project_dir):
    """The opted-in colour/light board for a slot: (project-relative path, main colours) or (None, [])."""
    import studio_refs
    tone = entry.get("tone_ref")
    if not tone:
        return None, []
    source = (catalog["library"].asset_path(tone["sha256"]) if tone["kind"] == "plate"
              else Path(project_dir) / tone["path"])
    return studio_refs.tone_board(source, project_dir, tone["sha256"])


def _main_canvas(project):
    import studio_project as sp
    return tuple(sp.slot(project, "01_main")["canvas"])


def _final_path(project_dir, slot_id, suffix=".jpg"):
    return Path(project_dir) / "final" / f"{slot_id}{suffix}"


def _clear_final(project_dir, slot_id):
    for suffix in (".jpg", ".png"):
        _final_path(project_dir, slot_id, suffix).unlink(missing_ok=True)


def _rank_backdrops(choice):
    """Backdrops ordered from safest to riskiest (same rule as studio_main.choose_backdrop)."""
    rows = choice.get("candidates") or {}
    if not rows:
        return [choice["backdrop"]] + [name for name in ("white", "mid_grey", "light_grey") if name != choice["backdrop"]]

    def risk(name):
        row = rows[name]
        return 0.6 * row["confusable"] + (0.8 if row["separation"] < 25 else 0) + (0.2 if row["separation"] < 45 else 0)
    ordered = sorted(rows, key=risk)
    return [choice["backdrop"]] + [name for name in ordered if name != choice["backdrop"]]


# ---------------------------------------------------------------- plan

def _plan_main(project, project_dir, plan, entry, item, slot):
    """Photo route builds the final now; generate route writes the prompt."""
    import studio_main
    import studio_prompt
    import studio_project as sp
    route = entry.get("route", "auto")
    hidden = set(plan.get("hide") or {})
    if entry.get("photo") in hidden and route != "generate":
        raise sp.StudioError(f"MAIN_PHOTO_HIDDEN: {entry['photo']} has hidden areas (a person or unrelated items) and cannot "
                             "become the main image; give another photo or use route generate")
    photo_id = entry.get("photo") or sp.main_photo_candidate(project, exclude=hidden)
    if route == "photo" and (not photo_id or not (_photo(project, photo_id).get("main") or {}).get("eligible")):
        reasons = (_photo(project, photo_id).get("main") or {}).get("reasons") if photo_id else ["NO_PHOTO"]
        raise sp.StudioError(f"MAIN_PHOTO_INELIGIBLE: {photo_id or 'no photo'} cannot become the main image locally ({reasons}); "
                             "use route auto/generate or give a plain-background photo")
    if route in {"auto", "photo"} and photo_id and (_photo(project, photo_id).get("main") or {}).get("eligible"):
        source = Path(project_dir) / _photo(project, photo_id)["path"]
        _clear_final(project_dir, slot["id"])
        result = studio_main.build_from_photo(source, _final_path(project_dir, slot["id"]), tuple(slot["canvas"]))
        final = Path(result["path"])
        item.update(status="done", route="photo", photo=photo_id, final=sp.rel(final, project_dir),
                    final_sha256=sp.sha256_file(final), checks={"verify": result["verify"], "cutout": _small(result["cutout"])},
                    check_suggested=result.get("check_suggested", False), warnings=[], done_at=time.time())
        for key in ("pending_kind", "active_attempt", "correction"):
            item.pop(key, None)
        return {"route": "photo", "photo": photo_id, "final": str(final), "check_suggested": result.get("check_suggested", False)}
    photos, photo_paths = _reference_photos(project, project_dir, entry.get("photos"), plan.get("hide"))
    if not photos:
        raise sp.StudioError("PHOTOS_REQUIRED: the main image needs at least one product photo")
    if entry.get("backdrop", "auto") != "auto":
        name = entry["backdrop"]
        choice = {"backdrop": name, "hex": studio_main.BACKDROP_HEX[name], "candidates": {}}
    else:
        images = [studio_main.open_normalized(Path(project_dir) / path) for photo, path in zip(photos, photo_paths)
                  if photo["role"] == "whole"][:2]
        choice = studio_main.choose_backdrop(images, transparent=plan["product"].get("transparent", False))
    order = _rank_backdrops(choice)
    strategy = {"backdrop": choice["backdrop"], "order": order, "tried": [choice["backdrop"]], "corrections": [],
                "light_product": bool(choice["backdrop"] == "white" and choice.get("light_fraction", 0) > 0.08),
                "choice": {k: v for k, v in choice.items() if k != "measured_from"}}
    prompt, frame = studio_prompt.compile_main(project, plan, slot, photos, backdrop_hex=studio_main.BACKDROP_HEX[strategy["backdrop"]],
                                               backdrop_name=strategy["backdrop"], view=entry.get("view"))
    return {"route": "generate", "prompt": prompt, "frame": frame, "photos": photos, "photo_paths": photo_paths,
            "strategy": strategy}


def _small(info):
    return {key: value for key, value in (info or {}).items() if key in {"method", "shadow_removed", "holes_removed", "parts",
                                                                       "light_edge", "faint_outline", "tolerance", "bbox"}}


def cmd_plan(args):
    import hashlib
    import studio_catalog
    import studio_plan
    import studio_project as sp
    import studio_prompt
    project_dir = Path(args.project)
    plan_path = Path(args.plan) if args.plan else project_dir / sp.PLAN_FILE
    plan_raw = studio_plan.load_plan(plan_path)
    with sp.locked(project_dir) as project:
        if any(item.get("status") == "generating" for item in project["jobs"].values()):
            raise sp.StudioError("PLAN_BUSY: images are being generated; ingest-batch their results (or --not-started) first")
        catalog = studio_catalog.load(args.library_dir)
        plan, errors, warnings = studio_plan.validate(plan_raw, project, catalog)
        if errors:
            return {"errors": errors, "warnings": warnings, "fix": "edit plan.json and run plan again"}, False
        project["plan_snapshot"] = plan   # used for redo prompts (no re-validation later)
        regenerate = set(args.regenerate or [])
        changed_done, main_result = [], None
        for slot in project["slots"]:
            entry = plan["slots"][slot["id"]]
            item = project["jobs"].setdefault(slot["id"], {"status": "pending", "attempts": [], "transient_failures": 0,
                                                          "free_releases": 0, "redos": 0})
            if entry.get("skip"):
                if item.get("status") != "generating":
                    item["status"] = "skipped"
                continue
            if item.get("status") == "skipped":
                item["status"] = "pending"
            if slot["kind"] == "main":
                if item.get("status") == "done" and slot["id"] not in regenerate and item.get("plan_entry") == entry:
                    continue
                outcome = _plan_main(project, project_dir, plan, entry, item, slot)
                item["plan_entry"] = entry
                if outcome["route"] == "photo":
                    main_result = outcome
                    continue
                prompt, frame = outcome["prompt"], outcome["frame"]
                references = list(outcome["photo_paths"])
                item["main_strategy"] = outcome["strategy"]
                main_result = {"route": "generate", "backdrop": outcome["strategy"]["backdrop"]}
                people = False
            else:
                if entry["template"] == "custom":
                    design = studio_prompt.design_custom(entry, plan.get("style"))
                    project["design"][slot["id"]] = {"source": "custom", "template": "custom"}
                else:
                    source, family, template = studio_catalog.resolve(catalog, entry["template"])
                    design = studio_prompt.design_from_template(source, family, template, slot)
                    project["design"][slot["id"]] = {"source": source, "template": template["id"],
                                                     "revision": template.get("revision"), "family": family["id"] if family else None}
                photos, photo_paths = _reference_photos(project, project_dir, entry["photos"], plan.get("hide"))
                tone_rel, tone_colours = _tone_for(entry, catalog, project_dir)
                design_record = project["design"].setdefault(slot["id"], {"source": "custom", "template": "custom"})
                design_record.update(tone_ref=(entry.get("tone_ref") or {}).get("value"), tone=tone_rel)
                prompt, frame = studio_prompt.compile_secondary(project, plan, slot, entry, design, photos, tone_rel,
                                                               tone_colours)
                references = photo_paths + ([tone_rel] if tone_rel else [])
                people = entry.get("people", False) is not False
            prompt_file = project_dir / "prompts" / f"{slot['id']}.txt"
            digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
            inputs = hashlib.sha256((prompt + "\n" + "\n".join(references)).encode("utf-8")).hexdigest()
            if item.get("status") == "done" and item.get("inputs_sha256") != inputs and slot["id"] not in regenerate:
                changed_done.append(slot["id"])
                continue
            if item.get("status") == "done" and item.get("inputs_sha256") == inputs and slot["id"] not in regenerate:
                continue
            prompt_file.write_text(prompt, encoding="utf-8")
            item.update(route="generate", prompt_file=sp.rel(prompt_file, project_dir), prompt_sha256=digest,
                        inputs_sha256=inputs, references=references, size=frame["size"], aspect=frame["frame"],
                        people=people, canvas=slot["canvas"])
            if item.get("status") in {"done", "failed"} or slot["id"] in regenerate:
                item.update(status="pending", pending_kind="initial", redos=0, transient_failures=0)
                item.pop("redo_prompt_file", None)
            elif item.get("status") != "generating":
                item["status"] = "pending"
                item.setdefault("pending_kind", "initial")
                if item.get("pending_kind") in {"redo", "auto_redo"} and item.get("correction"):
                    # a pending correction is rebuilt on the new base prompt (never sent with old wording)
                    _compile_redo(project, project_dir, slot["id"])(item, item["correction"])
        project["plan"] = {"sha256": hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest(),
                           "family": plan.get("family"), "planned_at": time.time(), "people": plan.get("people", False)}
        sp.update_cast(project, plan.get("cast"), plan.get("cast_members") or [], plan.get("cast_anchor"))
        wave = sp.reserve(project, project_dir, max_count=args.max)
        cast = sp.cast_summary(project)
        result = {"main": main_result, "warnings": warnings, **wave, **({"cast": cast} if cast else {}),
                  "next": "One image call per reservation (prompt verbatim, references in order, size if accepted); glance "
                          "at each result; then ONE ingest-batch call with all results."}
        if changed_done:
            result["changed_done"] = changed_done
            result["changed_done_note"] = ("these images are already finished and their prompt changed; they are kept. "
                                           "Pass --regenerate <job> to make them again.")
        return result, True


# ---------------------------------------------------------------- ingest

def _compile_redo(project, project_dir, slot_id):
    """Closure writing the redo prompt for a job (main: recompiled with backdrop/corrections)."""
    import studio_main
    import studio_prompt
    import studio_project as sp

    def write(item, reason):
        target = Path(project_dir) / "prompts" / f"{slot_id}.redo.txt"
        if sp.slot(project, slot_id)["kind"] == "main":
            strategy = item["main_strategy"]
            if reason and reason not in strategy["corrections"]:
                strategy["corrections"].append(reason)
            plan = project["plan_snapshot"]
            photos, _ = _reference_photos(project, project_dir, item["plan_entry"].get("photos"), plan.get("hide"))
            prompt, _ = studio_prompt.compile_main(project, plan, sp.slot(project, slot_id), photos,
                                                   backdrop_hex=studio_main.BACKDROP_HEX[strategy["backdrop"]],
                                                   backdrop_name=strategy["backdrop"], view=item["plan_entry"].get("view"),
                                                   corrections=strategy["corrections"][-3:])
        else:
            base = (Path(project_dir) / item["prompt_file"]).read_text(encoding="utf-8")
            prompt = studio_prompt.redo_prompt(base, reason)
        target.write_text(prompt, encoding="utf-8")
        item["redo_prompt_file"] = sp.rel(target, project_dir)
    return write


def _process(project, project_dir, slot_id, item, attempt, raw_path, digest):
    import studio_export
    import studio_main
    import studio_project as sp
    slot = sp.slot(project, slot_id)
    raw_rel = sp.rel(raw_path, project_dir)
    if slot["kind"] == "main":
        strategy = item["main_strategy"]
        try:
            _clear_final(project_dir, slot_id)
            result = studio_main.build_from_generated(raw_path, _final_path(project_dir, slot_id), tuple(slot["canvas"]),
                                                      light_product=strategy.get("light_product", False))
        except studio_main.MainError as exc:
            hint = studio_main.REDO_HINTS.get(exc.code, "make a clean single-product packshot on the flat backdrop")
            if exc.code == "MAIN_CUTOUT_INCOMPLETE":
                untried = [name for name in strategy["order"] if name not in strategy["tried"]]
                if untried:
                    strategy["backdrop"] = untried[0]
                    strategy["tried"].append(untried[0])
                    strategy["light_product"] = False
            outcome = sp.finish_auto_redo(project, slot_id, item, attempt, raw_rel=raw_rel, digest=digest, code=exc.code,
                                          hint=hint, project_dir=project_dir, compile_redo=_compile_redo(project, project_dir, slot_id))
            if outcome == "exhausted":
                item.update(status="failed", failed_reason=f"{exc.code}: 主图无法自动得到干净纯白底：请提供白底或纯色背景的实拍图"
                                                           "（本地抠图合成），或换角度后重试")
                return {"job": slot_id, "status": "failed", "code": exc.code}
            return {"job": slot_id, "status": "pending", "auto_redo": exc.code, "backdrop": strategy["backdrop"]}
        final = Path(result["path"])
        sp.finish_ok(project, item, attempt, raw_rel=raw_rel, digest=digest, final_rel=sp.rel(final, project_dir),
                     final_sha=sp.sha256_file(final), checks={"verify": result["verify"], "cutout": _small(result["cutout"])},
                     warnings=[])
        item["check_suggested"] = result.get("check_suggested", False)
        return {"job": slot_id, "status": "done", "final": str(final), "check_suggested": item["check_suggested"]}
    work_png = Path(project_dir) / "work" / f"{slot_id}.png"
    result = studio_export.finish_secondary(raw_path, _final_path(project_dir, slot_id), tuple(slot["canvas"]),
                                            people=item.get("people", False),
                                            quality=project["export"].get("quality", 92), work_png=work_png)
    # The raw frame is complete even when the crop check asks for a redo, so it can define the model.
    model = {"model": "defined"} if sp.note_identity(project, slot_id, item, attempt, raw_rel, digest) else {}
    if result.get("cut"):
        hint = ("text or the product went outside the kept strip of the frame; keep every word, the product and graphics "
                "well inside the stated strip")
        outcome = sp.finish_auto_redo(project, slot_id, item, attempt, raw_rel=raw_rel, digest=digest, code="FRAME_CONTENT_CUT",
                                      hint=hint, project_dir=project_dir, compile_redo=_compile_redo(project, project_dir, slot_id))
        if outcome == "redo":
            return {"job": slot_id, "status": "pending", "auto_redo": "FRAME_CONTENT_CUT", "cut_risk": result["cut_risk"], **model}
        warnings = ["frame_cut_risk"]
    else:
        warnings = []
    final = Path(result["path"])
    sp.finish_ok(project, item, attempt, raw_rel=raw_rel, digest=digest, final_rel=sp.rel(final, project_dir),
                 final_sha=sp.sha256_file(final), checks={k: result.get(k) for k in ("cut_risk", "upscale", "band", "keywords")},
                 warnings=warnings)
    return {"job": slot_id, "status": "done", "final": str(final), **({"warnings": warnings} if warnings else {}), **model}


def _items(args):
    items = []
    for job_id, attempt_id, artifact in args.item or []:
        items.append({"job": job_id, "attempt_id": attempt_id, "artifact": artifact})
    for job_id, attempt_id, error in args.failed or []:
        items.append({"job": job_id, "attempt_id": attempt_id, "error": error})
    for job_id, attempt_id in args.not_started or []:
        items.append({"job": job_id, "attempt_id": attempt_id, "not_started": True})
    redo = [{"job": job_id, "reason": reason} for job_id, reason in args.redo or []]
    recast = [{"job": job_id, "reason": reason} for job_id, reason in args.recast or []]
    reject = [{"job": job_id, "reason": reason} for job_id, reason in args.reject or []]
    people = [{"job": job_id, "value": value} for job_id, value in args.people or []]
    if args.results:
        payload = json.loads(Path(args.results).read_text(encoding="utf-8-sig"))
        items += payload.get("items", [])
        redo += payload.get("redo", [])
        recast += payload.get("recast", [])
        reject += payload.get("reject", [])
        people += payload.get("people", [])
    return items, redo, recast, reject, people


def cmd_ingest(args):
    import studio_project as sp
    project_dir = Path(args.project)
    items, redo, recast, reject, people = _items(args)
    if not (items or redo or recast or reject or people):
        raise sp.StudioError("NOTHING_TO_INGEST: give --item/--failed/--not-started/--redo/--recast/--reject/--people or --results")
    results, errors = [], []
    with sp.locked(project_dir) as project:
        for entry in items:
            slot_id, attempt_id = entry.get("job"), entry.get("attempt_id")
            try:
                if entry.get("artifact"):
                    raw_path, digest = sp.store_raw(project_dir, slot_id, attempt_id, entry["artifact"])
                    mode, item, attempt = sp.begin_ingest(project, slot_id, attempt_id, digest)
                    if mode == "duplicate":
                        results.append({"job": slot_id, "status": item["status"], "idempotent": True})
                        continue
                    results.append(_process(project, project_dir, slot_id, item, attempt, raw_path, digest))
                elif entry.get("error") is not None:
                    results.append(sp.record_failure(project, slot_id, attempt_id, entry["error"]))
                elif entry.get("not_started"):
                    results.append(sp.release(project, slot_id, attempt_id))
                else:
                    raise sp.StudioError("ITEM_INVALID: each item needs artifact, error or not_started")
            except (sp.StudioError, OSError, ValueError) as exc:
                errors.append({"job": slot_id, "error": str(exc)[:400]})
        for entry in people:
            try:
                item = sp.job(project, entry["job"])
                value = str(entry["value"]).lower() in {"yes", "true", "1", "person", "hands"}
                item["people"] = value
                cast = project.get("cast") or {}
                if not value and entry["job"] in (cast.get("members") or []):
                    cast["members"] = [member for member in cast["members"] if member != entry["job"]]
                    sp.live_identity(project, project_dir)          # clears the model if this image defined it
                if item.get("status") == "done" and item.get("route") == "generate" and sp.slot(project, entry["job"])["kind"] != "main":
                    import studio_export
                    studio_export.rewrite_keywords(project_dir / "work" / f"{entry['job']}.png",
                                                   project_dir / item["final"], people=value,
                                                   quality=project["export"].get("quality", 92))
                    item["final_sha256"] = sp.sha256_file(project_dir / item["final"])
                results.append({"job": entry["job"], "people": value})
            except (sp.StudioError, OSError, KeyError) as exc:
                errors.append({"job": entry.get("job"), "error": str(exc)[:400]})
        for entry in redo:
            try:
                results.append(sp.request_redo(project, entry["job"], entry.get("reason"), user_confirmed=args.user_confirmed,
                                               compile_redo=_compile_redo(project, project_dir, entry["job"])))
            except (sp.StudioError, KeyError) as exc:
                errors.append({"job": entry.get("job"), "error": str(exc)[:400]})
        for entry in recast:
            try:
                results.append(sp.recast(project, entry["job"], entry.get("reason"), user_confirmed=args.user_confirmed,
                                         compile_redo=_compile_redo(project, project_dir, entry["job"])))
            except (sp.StudioError, KeyError) as exc:
                errors.append({"job": entry.get("job"), "error": str(exc)[:400]})
        for entry in reject:
            try:
                results.append(sp.reject(project, entry["job"], entry.get("reason", "")))
            except sp.StudioError as exc:
                errors.append({"job": entry.get("job"), "error": str(exc)[:400]})
        payload = {"results": results, "errors": errors}
        if not args.no_reserve:
            payload.update(sp.reserve(project, project_dir, max_count=args.max))
        payload["summary"] = sp.summary(project)["counts"]
        cast = sp.cast_summary(project)
        if cast:
            payload["cast"] = cast
        main = project["jobs"].get("01_main") or {}
        if main.get("check_suggested") and main.get("status") == "done":
            payload["main_check"] = "borderline cut-out: look once at " + str(project_dir / main["final"])
    return payload, not errors


# ---------------------------------------------------------------- deliver / status

def cmd_deliver(args):
    import studio_project as sp
    project_dir = Path(args.project)
    with sp.locked(project_dir) as project:
        missing, files = [], []
        for slot in project["slots"]:
            item = project["jobs"].get(slot["id"])
            if not item or item.get("status") == "skipped":
                continue
            if item.get("status") != "done":
                missing.append({"job": slot["id"], "status": item.get("status") if item else "unplanned",
                                **({"reason": item.get("failed_reason")} if item and item.get("failed_reason") else {})})
                continue
            path = project_dir / item["final"]
            if not path.is_file() or sp.sha256_file(path) != item.get("final_sha256"):
                missing.append({"job": slot["id"], "status": "final_missing_or_changed"})
                continue
            files.append(path.resolve())
        if missing and not args.partial:
            return {"missing": missing, "fix": "finish or reject these images, or deliver --partial"}, False
        output = Path(args.out).resolve() if args.out else (project_dir / "final").resolve()
        if args.out:
            output.mkdir(parents=True, exist_ok=True)
            copied = []
            for path in files:
                target = output / path.name
                shutil.copyfile(path, target)
                copied.append(target)
            files = copied
        mismatch = sp.model_mismatch(project)
        report = {"delivered_at": time.time(), "output_dir": str(output), "files": [str(path) for path in files],
                  "image_count": len(files), **({"missing": missing} if missing else {}),
                  **({"model_mismatch": mismatch, "model_mismatch_note": "these images show an earlier model; tell the "
                      "user, or --redo them with the user's consent"} if mismatch else {})}
        (project_dir / "delivery_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        return report, True


def cmd_status(args):
    import studio_project as sp
    project = sp.load(args.project)
    return {**sp.summary(project), "photos": [sp.summary_photo(photo) for photo in project["photos"]],
            "refs": [{"id": ref["id"], "size": ref["size"]} for ref in project.get("refs", [])],
            "main_candidate": sp.main_photo_candidate(project), **({"cast": sp.cast_summary(project)} if sp.cast_summary(project) else {})}, True


# ---------------------------------------------------------------- CLI

def build_parser():
    parser = argparse.ArgumentParser(prog="studio.py", description=__doc__.split("\n")[0])
    subs = parser.add_subparsers(dest="command", required=True)

    init = subs.add_parser("init")
    init.add_argument("--project-dir", required=True)
    init.add_argument("--project-id", required=True)
    init.add_argument("--marketplace", required=True)
    init.add_argument("--language", required=True)
    init.add_argument("--listing-aspect", default="1:1", choices=["1:1", "1:1.3"])
    init.add_argument("--short-edge", type=int, default=2000)
    init.add_argument("--a-plus-modules", help="comma list name[:WxH], e.g. header,feature:970x600 (default size 970x600)")
    init.add_argument("--a-plus-canvas", help="default A+ size WxH (970x600)")
    init.add_argument("--photos", nargs="+")
    init.add_argument("--views", nargs="+")
    init.add_argument("--refs", nargs="+", help="reference images (style ideas only; never product photos)")
    init.add_argument("--force", action="store_true")
    init.add_argument("--no-catalog", action="store_true")
    init.add_argument("--library-dir")

    add = subs.add_parser("add-photos")
    add.add_argument("--project", required=True)
    add.add_argument("--photos", nargs="+", required=True)
    add.add_argument("--views", nargs="+")

    refs = subs.add_parser("add-refs")
    refs.add_argument("--project", required=True)
    refs.add_argument("--refs", nargs="+", required=True)

    templates = subs.add_parser("templates")
    templates.add_argument("--project", required=True)
    templates.add_argument("--family")
    templates.add_argument("--library-dir")

    plan = subs.add_parser("plan")
    plan.add_argument("--project", required=True)
    plan.add_argument("--plan", help="default <project>/plan.json")
    plan.add_argument("--max", type=int)
    plan.add_argument("--regenerate", nargs="+")
    plan.add_argument("--library-dir")

    reserve = subs.add_parser("reserve")
    reserve.add_argument("--project", required=True)
    reserve.add_argument("--max", type=int)
    reserve.add_argument("--jobs", nargs="+")

    ingest = subs.add_parser("ingest-batch")
    ingest.add_argument("--project", required=True)
    ingest.add_argument("--item", nargs=3, action="append", metavar=("JOB", "ATTEMPT_ID", "IMAGE_PATH"))
    ingest.add_argument("--failed", nargs=3, action="append", metavar=("JOB", "ATTEMPT_ID", "ERROR"))
    ingest.add_argument("--not-started", nargs=2, action="append", metavar=("JOB", "ATTEMPT_ID"))
    ingest.add_argument("--redo", nargs=2, action="append", metavar=("JOB", "REASON"))
    ingest.add_argument("--recast", nargs=2, action="append", metavar=("JOB", "REASON"),
                        help="regenerate the image that defined the set's model with a new person")
    ingest.add_argument("--reject", nargs=2, action="append", metavar=("JOB", "REASON"))
    ingest.add_argument("--people", nargs=2, action="append", metavar=("JOB", "yes|no"))
    ingest.add_argument("--results", help="JSON {items:[{job, attempt_id, artifact|error|not_started}], redo:[...], ...}")
    ingest.add_argument("--user-confirmed", action="store_true")
    ingest.add_argument("--no-reserve", action="store_true")
    ingest.add_argument("--max", type=int)
    ingest.add_argument("--library-dir")

    deliver = subs.add_parser("deliver")
    deliver.add_argument("--project", required=True)
    deliver.add_argument("--out")
    deliver.add_argument("--partial", action="store_true")

    status = subs.add_parser("status")
    status.add_argument("--project", required=True)

    reset = subs.add_parser("reset")
    reset.add_argument("--project", required=True)
    reset.add_argument("--job", required=True)
    reset.add_argument("--reason", required=True)
    reset.add_argument("--user-confirmed", action="store_true")
    return parser


def run(argv=None):
    args = build_parser().parse_args(argv)
    project = getattr(args, "project", None) or getattr(args, "project_dir", None)
    try:
        _auth_gate(args.command)          # before the project is read
        _ensure_runtime()
        import studio_project as sp
        if args.command == "init":
            created = sp.create(args.project_dir, args.project_id, args.marketplace, args.language,
                                listing_aspect=args.listing_aspect, short_edge=args.short_edge,
                                a_plus_modules=args.a_plus_modules, a_plus_canvas=args.a_plus_canvas, force=args.force)
            payload = {"slots": [{"id": s["id"], "role": s["role"], "canvas": s["canvas"]} for s in created["slots"]]}
            with sp.locked(args.project_dir) as state:
                if args.photos:
                    payload["photos"] = sp.add_photos(state, args.project_dir, args.photos, args.views)
                if args.refs:
                    import studio_refs
                    payload["refs"] = studio_refs.add_refs(state, args.project_dir, args.refs)
                payload["main_candidate"] = sp.main_photo_candidate(state)
                if not args.no_catalog:
                    _, payload["catalog"] = _catalog(state, args.project_dir, args.library_dir)
            payload["next"] = ("Choose one family and a template per slot (or custom) from catalog, write plan.json in the "
                               "project folder, then run plan.")
            ok = True
        elif args.command == "add-photos":
            with sp.locked(args.project) as state:
                payload = sp.add_photos(state, args.project, args.photos, args.views)
                payload["main_candidate"] = sp.main_photo_candidate(state)
            ok = True
        elif args.command == "add-refs":
            import studio_refs
            with sp.locked(args.project) as state:
                payload = studio_refs.add_refs(state, args.project, args.refs)
            ok = True
        elif args.command == "templates":
            import studio_catalog
            state = sp.load(args.project)
            catalog = studio_catalog.load(args.library_dir)
            if args.family:
                detail = studio_catalog.family_detail(catalog, args.family)
                if detail is None:
                    raise sp.StudioError(f"FAMILY_UNKNOWN: {args.family}")
                payload, ok = detail, True
            else:
                payload, ok = studio_catalog.compact(catalog, state, args.project), True
        elif args.command == "plan":
            payload, ok = cmd_plan(args)
        elif args.command == "reserve":
            with sp.locked(args.project) as state:
                payload = sp.reserve(state, args.project, max_count=args.max, jobs=args.jobs)
            ok = True
        elif args.command == "ingest-batch":
            payload, ok = cmd_ingest(args)
        elif args.command == "deliver":
            payload, ok = cmd_deliver(args)
        elif args.command == "status":
            payload, ok = cmd_status(args)
        elif args.command == "reset":
            if not args.user_confirmed:
                raise sp.StudioError("USER_CONFIRMATION_REQUIRED: a reset spends more image calls; ask the user, then add --user-confirmed")
            with sp.locked(args.project) as state:
                payload = sp.reset(state, args.job, args.reason)
            ok = True
        else:  # pragma: no cover
            raise SystemExit(2)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - one JSON line for every failure
        code = getattr(exc, "code", None)
        emit(args.command, {"error": str(exc), **({"code": code} if code else {})}, ok=False, project=project)
        return 2
    emit(args.command, payload, ok=ok, project=project)
    return 0 if ok else 2


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
