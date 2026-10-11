"""Project state for the V8 one-shot pipeline (project.json; tool-owned).

Slots, registered photos, and one job per planned image with its attempts. Every
state change goes through these functions under the project lock; the agent only
writes plan.json. Budgets: transient failures = first try + 2 retries (429 is not
counted; concurrency drops to 1 and the retry delay is honoured), 2 free releases of
reservations that were never sent, regenerations (agent request or automatic check)
1 per image, 2 for the main image; more only with --user-confirmed.

The set's model (V8.1, `cast`): images whose plan shows a person are members. The
anchor (first member, or plan.json cast_anchor) is reserved first; its first good
result defines the model (`identity`, an epoch-stamped raw image). Every later member
attempt gets that image appended to its references plus an identity line, inserted
here at reservation time so retries and redos stay consistent. A failed anchor hands
over to the next member; `recast` clears the model and starts a new epoch.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

SCHEMA = "lc-studio-project/8"
PROJECT_FILE = "project.json"
PLAN_FILE = "plan.json"
MAX_TRANSIENT_RETRIES = 2
FREE_RELEASES = 2
MAX_REDOS = 1
MAX_REDOS_MAIN = 2
TIMEOUT_SECONDS = 1800
DEFAULT_CONCURRENCY = 4
PHOTO_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}

LISTING_SLOTS = (("01_main", "main", "main"),
                 ("02_size_or_components", "secondary", "size_or_components"),
                 ("03_primary_use_case", "secondary", "primary_use_case"),
                 ("04_compatibility_or_installation", "secondary", "compatibility_or_installation"),
                 ("05_material_or_detail", "secondary", "material_or_detail"),
                 ("06_storage_or_package", "secondary", "storage_or_package"),
                 ("07_problem_solution", "secondary", "problem_solution"))
A_PLUS_MODULES = ("header", "feature", "detail", "lifestyle", "comparison", "story")
A_PLUS_DEFAULT_CANVAS = (970, 600)
SLOT_PURPOSE = {
    "main": "the exact product alone on pure white; no text, props or people",
    "size_or_components": "real size or exactly what is included, with short labels",
    "primary_use_case": "the product doing its main job in a believable scene",
    "compatibility_or_installation": "how it fits, connects or installs",
    "material_or_detail": "close-up of confirmed materials or construction",
    "storage_or_package": "storage, carrying or the complete set",
    "problem_solution": "one buyer problem and how the product solves it",
    "a_plus_header": "brand/hero banner", "a_plus_feature": "key features at a glance",
    "a_plus_detail": "detail or specification close-ups", "a_plus_lifestyle": "lifestyle scene",
    "a_plus_comparison": "comparison of variants or before/after", "a_plus_story": "brand or product story",
}
A_PLUS_KEYWORDS = {"a_plus_header": ("header", "hero", "banner", "brand", "logo"),
                   "a_plus_feature": ("feature", "grid", "benefit", "highlight", "icon"),
                   "a_plus_detail": ("detail", "close", "material", "spec"),
                   "a_plus_lifestyle": ("lifestyle", "scene", "use"),
                   "a_plus_comparison": ("comparison", "compare", "chart", "table", "versus"),
                   "a_plus_story": ("story", "about", "mission")}
VIEW_WORDS = (("three_quarter", ("three_quarter", "3-4", "34view", "angle", "oblique", "45")),
              ("back", ("back", "rear")), ("side", ("side", "left", "right", "profile")),
              ("top", ("top", "above")), ("bottom", ("bottom", "underside")),
              ("detail", ("detail", "closeup", "close-up", "macro", "zoom")), ("front", ("front", "main")))


class StudioError(RuntimeError):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code or (message.split(":", 1)[0] if ":" in message and message.split(":", 1)[0].isupper() else None)


# ---------------------------------------------------------------- storage

def project_path(project_dir):
    return Path(project_dir) / PROJECT_FILE


def detect_legacy(project_dir):
    folder = Path(project_dir)
    return (folder / "project_manifest.json").is_file() and not (folder / PROJECT_FILE).is_file()


def guard_path_length(project_dir):
    """Windows without long-path support: fail early with advice."""
    if os.name != "nt":
        return
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            if winreg.QueryValueEx(key, "LongPathsEnabled")[0] == 1:
                return
    except OSError:
        pass
    longest = len(str(Path(project_dir).resolve())) + 64
    if longest > 259:
        raise StudioError(f"PATH_TOO_LONG: project paths reach ~{longest} characters (Windows limit 260). Move the project "
                          "to a short folder such as D:\\lc\\<sku>, or enable Windows long paths, then retry.")


def load(project_dir):
    path = project_path(project_dir)
    if detect_legacy(project_dir):
        raise StudioError("LEGACY_PROJECT_V7: this folder is a V7 project (project_manifest.json); finish it with the "
                          "V7.2 package. V8 starts new projects with `studio.py init`.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise StudioError(f"PROJECT_NOT_FOUND: {path} does not exist; run `studio.py init` first") from None
    except ValueError as exc:
        raise StudioError(f"PROJECT_INVALID: {path}: {exc}") from None
    if value.get("schema") != SCHEMA:
        raise StudioError(f"PROJECT_INVALID: unsupported schema {value.get('schema')!r}")
    return value


def save(project, project_dir):
    import lc_fsretry
    path = project_path(project_dir)
    payload = (json.dumps(project, ensure_ascii=False, indent=1, sort_keys=False) + "\n").encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".project.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        lc_fsretry.replace(temporary, path)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


@contextmanager
def locked(project_dir):
    """Load under the project lock and save on success."""
    from lc_jsonstore import _selection_lock
    with _selection_lock(project_path(project_dir)):
        project = load(project_dir)
        before = json.dumps(project, sort_keys=True)
        yield project
        if json.dumps(project, sort_keys=True) != before:
            save(project, project_dir)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path, project_dir):
    return Path(path).resolve().relative_to(Path(project_dir).resolve()).as_posix()


def absolute(relative, project_dir):
    return str((Path(project_dir) / relative).resolve())


# ---------------------------------------------------------------- creation

def _a_plus_slots(spec, canvas):
    slots, used = [], set()
    items = [item.strip() for item in (spec or "").split(",") if item.strip()] if isinstance(spec, str) else list(spec or [])
    for index, item in enumerate(items):
        name, _, size = item.partition(":")
        name = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_") or f"module{index + 1}"
        if size:
            match = re.fullmatch(r"(\d{2,5})x(\d{2,5})", size.lower())
            if not match:
                raise StudioError(f"A_PLUS_CANVAS_INVALID: {item!r}; use name:WIDTHxHEIGHT, e.g. header:970x600")
            width, height = int(match[1]), int(match[2])
        else:
            width, height = canvas
        role = next((role for role, words in A_PLUS_KEYWORDS.items() if any(word in name for word in words)), "a_plus_feature")
        base = f"{8 + index:02d}_a_plus_{name}"
        slot_id = base if base not in used else f"{base}_{index}"
        used.add(slot_id)
        slots.append({"id": slot_id, "kind": "a_plus", "role": role, "module": name, "canvas": [width, height],
                      "purpose": SLOT_PURPOSE.get(role, "")})
    return slots


def create(project_dir, project_id, marketplace, language, *, listing_aspect="1:1", short_edge=2000,
           a_plus_modules=None, a_plus_canvas=None, force=False):
    folder = Path(project_dir)
    if detect_legacy(folder):
        raise StudioError("LEGACY_PROJECT_V7: this folder holds a V7 project; use a new folder or the V7.2 package")
    if (folder / PROJECT_FILE).exists() and not force:
        raise StudioError(f"PROJECT_EXISTS: {folder / PROJECT_FILE} already exists (use --force to start over)")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", project_id or ""):
        raise StudioError("PROJECT_ID_INVALID: use letters, digits, '-' or '_' (max 64)")
    if not re.fullmatch(r"[A-Z]{2}", (marketplace or "").upper()):
        raise StudioError("MARKETPLACE_INVALID: use a two-letter marketplace code such as US, DE, JP")
    if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", language or ""):
        raise StudioError("LANGUAGE_INVALID: use a BCP-47 tag such as en, de, ja, zh-CN")
    if not 1600 <= int(short_edge) <= 10000:
        raise StudioError("SHORT_EDGE_INVALID: listing images need a short edge of 1600-10000 px")
    if listing_aspect not in {"1:1", "1:1.3"}:
        raise StudioError("LISTING_ASPECT_INVALID: use 1:1 or 1:1.3")
    folder.mkdir(parents=True, exist_ok=True)
    guard_path_length(folder)
    edge = int(short_edge)
    listing = [edge, edge] if listing_aspect == "1:1" else [edge, round(edge * 1.3)]
    canvas = A_PLUS_DEFAULT_CANVAS
    if a_plus_canvas:
        match = re.fullmatch(r"(\d{2,5})x(\d{2,5})", str(a_plus_canvas).lower())
        if not match:
            raise StudioError("A_PLUS_CANVAS_INVALID: use WIDTHxHEIGHT, e.g. 970x600")
        canvas = (int(match[1]), int(match[2]))
    slots = [{"id": slot_id, "kind": kind, "role": role, "canvas": list(listing), "purpose": SLOT_PURPOSE[role]}
             for slot_id, kind, role in LISTING_SLOTS]
    if a_plus_modules is True:
        a_plus_modules = list(A_PLUS_MODULES)
    slots += _a_plus_slots(a_plus_modules, canvas)
    for name in ("source", "prompts", "raw", "final", "work", "design/tones", "design/hidden", "refs", "catalog"):
        (folder / name).mkdir(parents=True, exist_ok=True)
    project = {"schema": SCHEMA, "project_id": project_id, "marketplace": marketplace.upper(), "language": language,
               "created_at": time.time(), "concurrency": DEFAULT_CONCURRENCY,
               "export": {"quality": 92, "main_quality": 95}, "photos": [], "slots": slots,
               "preferred_families": [], "refs": [], "cast": None, "plan": None, "design": {}, "jobs": {},
               "network": {"retry_after_until": 0, "cap": None, "successes": 0}, "history": []}
    save(project, folder)
    return project


def slot(project, slot_id):
    found = next((item for item in project["slots"] if item["id"] == slot_id), None)
    if found is None:
        raise StudioError(f"UNKNOWN_SLOT: {slot_id}")
    return found


def job(project, slot_id):
    found = project["jobs"].get(slot_id)
    if found is None:
        raise StudioError(f"UNKNOWN_JOB: {slot_id} has not been planned (run plan)")
    return found


# ---------------------------------------------------------------- photos

def _guess_view(name):
    lowered = name.lower()
    for view, words in VIEW_WORDS:
        if any(word in lowered for word in words):
            return view
    return None


def _safe_id(stem, taken):
    base = re.sub(r"[^a-z0-9_]+", "_", stem.lower()).strip("_") or "photo"
    if not re.match(r"[a-z]", base):
        base = "photo_" + base
    candidate, index = base[:48], 2
    while candidate in taken:
        candidate, index = f"{base[:44]}_{index}", index + 1
    return candidate


def add_photos(project, project_dir, photos, views=None):
    import studio_main
    folder = Path(project_dir)
    views = list(views or [])
    added, skipped = [], []
    known = {photo["sha256"]: photo for photo in project["photos"]}
    taken = {photo["id"] for photo in project["photos"]}
    for index, value in enumerate(photos):
        source = Path(value).expanduser()
        if not source.is_file():
            raise StudioError(f"PHOTO_NOT_FOUND: {source}")
        suffix = source.suffix.lower()
        if suffix in {".heic", ".heif"}:
            raise StudioError(f"PHOTO_FORMAT: {source.name} is HEIC; export it as JPEG or PNG first")
        if suffix not in PHOTO_TYPES:
            raise StudioError(f"PHOTO_FORMAT: {source.name}: use JPEG, PNG, WebP, TIFF or BMP")
        digest = sha256_file(source)
        if digest in known:
            skipped.append({"photo": str(source), "existing": known[digest]["id"]})
            continue
        reference = next((ref for ref in project.get("refs", []) if ref["sha256"] == digest), None)
        if reference:
            raise StudioError(f"PHOTO_IS_REFERENCE: {source.name} is registered as reference {reference['id']}; "
                              "product photos must show the user's own product")
        photo_id = _safe_id(source.stem, taken)
        taken.add(photo_id)
        target = folder / "source" / f"{photo_id}{suffix}"
        shutil.copyfile(source, target)
        image, alpha = studio_main.open_normalized(target)
        view = views[index] if index < len(views) and views[index] else (_guess_view(source.stem) or
                                                                         ("front" if not project["photos"] and not added else f"angle_{len(project['photos']) + len(added) + 1}"))
        role = "detail" if view == "detail" else "whole"
        record = {"id": photo_id, "path": rel(target, folder), "sha256": digest, "size": list(image.size),
                  "view": view, "role": role, "transparent": alpha is not None, "added_at": time.time()}
        if role == "whole":
            main_canvas = slot(project, "01_main")["canvas"]
            record["main"] = studio_main.photo_candidate(target, tuple(main_canvas))
        project["photos"].append(record)
        known[digest] = record
        added.append(record)
    return {"added": [summary_photo(photo) for photo in added], "skipped": skipped}


def summary_photo(photo):
    main = photo.get("main") or {}
    return {"id": photo["id"], "view": photo["view"], "role": photo["role"], "size": photo["size"],
            "main_eligible": main.get("eligible"), "main_reasons": main.get("reasons"),
            **({"main_upscale": main.get("upscale")} if main.get("upscale") else {})}


def main_photo_candidate(project, exclude=()):
    """Best photo for a local main image: eligible, smallest upscale, front views first."""
    options = [photo for photo in project["photos"] if photo.get("role") == "whole" and (photo.get("main") or {}).get("eligible")
               and photo["id"] not in set(exclude)]
    if not options:
        return None
    return min(options, key=lambda photo: (photo["view"] not in {"front", "three_quarter"}, photo["main"].get("upscale", 9)))["id"]


# ---------------------------------------------------------------- jobs and attempts

def redo_budget(project, slot_id):
    return MAX_REDOS_MAIN if slot(project, slot_id)["kind"] == "main" else MAX_REDOS


def effective_concurrency(project, now=None):
    network = project.setdefault("network", {"retry_after_until": 0, "cap": None, "successes": 0})
    limit = int(project.get("concurrency") or DEFAULT_CONCURRENCY)
    if network.get("cap"):
        limit = min(limit, int(network["cap"]))
    return max(1, limit)


def sweep_timeouts(project, now=None):
    now = time.time() if now is None else now
    released = []
    for slot_id, item in project["jobs"].items():
        attempt = active_attempt(item)
        if item.get("status") == "generating" and attempt and now - attempt.get("reserved_at", now) > TIMEOUT_SECONDS:
            attempt.update(outcome="timeout", ended_at=now)
            _count_transient(item, "GENERATION_TIMEOUT: no result within 30 minutes")
            released.append(slot_id)
    return released


def active_attempt(item):
    attempt_id = item.get("active_attempt")
    return next((attempt for attempt in item.get("attempts", []) if attempt["id"] == attempt_id), None)


def _count_transient(item, reason):
    item["transient_failures"] = item.get("transient_failures", 0) + 1
    item.pop("active_attempt", None)
    if item["transient_failures"] > MAX_TRANSIENT_RETRIES:
        item.update(status="failed", failed_reason=f"TRANSIENT_RETRY_LIMIT_REACHED: {reason}"[:300])
    else:
        item.update(status="pending", last_error=str(reason)[:300])
        item.setdefault("pending_kind", "retry")


def reserve(project, project_dir, *, max_count=None, jobs=None, now=None):
    """Reserve the next wave: one attempt per pending job, within the concurrency limit."""
    now = time.time() if now is None else now
    timed_out = sweep_timeouts(project, now)
    network = project["network"]
    if network.get("retry_after_until", 0) > now:
        wait = round(network["retry_after_until"] - now)
        return {"reservations": [], "refusals": [], "retry_after_seconds": wait, "timed_out": timed_out}
    active = sum(1 for item in project["jobs"].values() if item.get("status") == "generating")
    capacity = effective_concurrency(project, now) - active
    if isinstance(max_count, int) and max_count > 0:
        capacity = min(capacity, max_count)
    wave = "w" + uuid.uuid4().hex[:6]
    reservations, refusals, waiting = [], [], []
    cast = project.get("cast") or {}
    members = set(cast.get("members") or [])
    identity = live_identity(project, project_dir) if members else None
    anchor = effective_anchor(project) if members and not identity else None
    for slot_record in sorted(project["slots"], key=lambda record: record["id"] != anchor):   # anchor first
        slot_id = slot_record["id"]
        item = project["jobs"].get(slot_id)
        if not item or item.get("status") != "pending" or item.get("route") != "generate":
            continue
        if jobs and slot_id not in jobs:
            continue
        if any(str(path).startswith("design/plates/") for path in item.get("references", [])):
            refusals.append({"job": slot_id, "reason": "PLAN_OUTDATED: this image still points at an old style plate; "
                                                       "run plan again"})
            continue
        role = None
        if slot_id in members:
            if identity:
                role = "same_model"
            elif slot_id == anchor:
                role = "anchor"
            else:
                waiting.append(slot_id)
                refusals.append({"job": slot_id, "reason": f"WAITING_FOR_MODEL: starts after {anchor or 'the first image with the model'} "
                                                           "has defined the set's model"})
                continue
        if capacity <= 0:
            refusals.append({"job": slot_id, "reason": "CAPACITY: waiting for the current wave"})
            continue
        kind = item.get("pending_kind") or "initial"
        prompt_file = item.get("redo_prompt_file") if kind in {"redo", "auto_redo"} and item.get("redo_prompt_file") else item["prompt_file"]
        prompt = (Path(project_dir) / prompt_file).read_text(encoding="utf-8")
        references = list(item.get("references", []))
        if role == "same_model":
            import studio_prompt
            prompt = studio_prompt.with_identity(prompt, len(references) + 1)
            references.append(identity["path"])
        attempt = {"id": "a" + uuid.uuid4().hex[:10], "kind": kind, "wave": wave, "reserved_at": now,
                   "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(), "references": references}
        if role:
            attempt.update(cast_role=role, cast_epoch=cast.get("epoch"))
            if role == "same_model":
                attempt["identity_sha256"] = identity["sha256"]
        item.setdefault("attempts", []).append(attempt)
        item.update(status="generating", active_attempt=attempt["id"])
        capacity -= 1
        reservations.append({"job": slot_id, "attempt_id": attempt["id"], "kind": kind, "prompt": prompt,
                             "references": [absolute(path, project_dir) for path in references],
                             "size": item.get("size"), "aspect": item.get("aspect"), **({"cast": role} if role else {})})
    return {"wave": {"id": wave, "concurrency": effective_concurrency(project, now)}, "reservations": reservations,
            "refusals": refusals, "retry_after_seconds": None, "timed_out": timed_out,
            **({"waiting_for_model": waiting} if waiting else {})}


def store_raw(project_dir, slot_id, attempt_id, artifact):
    source = Path(artifact).expanduser()
    if not source.is_file():
        raise StudioError(f"ARTIFACT_NOT_FOUND: {source}")
    suffix = source.suffix.lower() if source.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} else ".png"
    target = Path(project_dir) / "raw" / f"{slot_id}-{attempt_id}{suffix}"
    digest = sha256_file(source)
    if target.exists() and sha256_file(target) != digest:
        raise StudioError(f"INGEST_CONFLICT: {target.name} already holds a different image")
    if not target.exists():
        shutil.copyfile(source, target)
    return target, digest


def begin_ingest(project, slot_id, attempt_id, digest):
    """Validate the attempt; returns ('ingest'|'duplicate', item, attempt)."""
    item = job(project, slot_id)
    attempt = next((entry for entry in item.get("attempts", []) if entry["id"] == attempt_id), None)
    if attempt is None:
        raise StudioError(f"STALE_ATTEMPT: {slot_id} has no attempt {attempt_id}")
    if attempt.get("raw_sha256") == digest:
        return "duplicate", item, attempt
    if attempt.get("raw_sha256"):
        raise StudioError(f"INGEST_CONFLICT: attempt {attempt_id} already has a different image")
    newer = [entry for entry in item["attempts"] if entry.get("reserved_at", 0) > attempt.get("reserved_at", 0) and entry.get("raw_sha256")]
    if newer:
        raise StudioError(f"STALE_ATTEMPT: {slot_id} already has a newer result")
    if item.get("status") != "generating" and attempt.get("outcome") != "timeout":
        raise StudioError(f"STALE_ATTEMPT: {slot_id} is {item.get('status')}, not waiting for {attempt_id}")
    return "ingest", item, attempt


def finish_ok(project, item, attempt, *, raw_rel, digest, final_rel, final_sha, checks, warnings, now=None):
    now = time.time() if now is None else now
    attempt.update(outcome="done", raw=raw_rel, raw_sha256=digest, returned_at=now)
    item.update(status="done", final=final_rel, final_sha256=final_sha, checks=checks, warnings=warnings,
                done_at=now)
    if attempt.get("identity_sha256"):
        item["identity_sha256"] = attempt["identity_sha256"]
    for key in ("active_attempt", "pending_kind", "correction", "last_error", "failed_reason"):
        item.pop(key, None)
    _record_success(project)


def finish_auto_redo(project, slot_id, item, attempt, *, raw_rel, digest, code, hint, project_dir, compile_redo, now=None):
    """An automatic check failed: regenerate within the budget, else fail (main) / warn (others)."""
    now = time.time() if now is None else now
    attempt.update(outcome=f"auto_check:{code}", raw=raw_rel, raw_sha256=digest, returned_at=now)
    item.pop("active_attempt", None)
    _record_success(project)
    if item.get("redos", 0) < redo_budget(project, slot_id):
        item["redos"] = item.get("redos", 0) + 1
        item.update(status="pending", pending_kind="auto_redo", correction=hint, last_check=code)
        compile_redo(item, hint)
        return "redo"
    return "exhausted"


def record_failure(project, slot_id, attempt_id, error, now=None):
    now = time.time() if now is None else now
    item = job(project, slot_id)
    attempt = active_attempt(item)
    if item.get("status") != "generating" or attempt is None or attempt["id"] != attempt_id:
        raise StudioError(f"STALE_ATTEMPT: {slot_id} has no active attempt {attempt_id}")
    text = str(error or "")
    attempt.update(outcome="tool_error", error=text[:300], ended_at=now)
    item.pop("active_attempt", None)
    if re.search(r"\b429\b|rate.?limit|too many requests", text, re.IGNORECASE):
        match = re.search(r"retry[^0-9]{0,20}(\d{1,4})\s*(s|sec|seconds)?", text, re.IGNORECASE)
        wait = int(match.group(1)) if match else 60
        network = project["network"]
        network.update(retry_after_until=now + wait, cap=1, successes=0)
        item.update(status="pending", last_error=text[:300])
        return {"job": slot_id, "status": "pending", "rate_limited": True, "retry_after_seconds": wait}
    _count_transient(item, text)
    return {"job": slot_id, "status": item["status"], "transient_failures": item["transient_failures"]}


def release(project, slot_id, attempt_id, reason="not started", now=None):
    now = time.time() if now is None else now
    item = job(project, slot_id)
    attempt = active_attempt(item)
    if item.get("status") != "generating" or attempt is None or attempt["id"] != attempt_id:
        raise StudioError(f"STALE_ATTEMPT: {slot_id} has no active reservation {attempt_id}")
    attempt.update(outcome="released", ended_at=now, reason=str(reason)[:200])
    item.pop("active_attempt", None)
    if item.get("free_releases", 0) < FREE_RELEASES:
        item["free_releases"] = item.get("free_releases", 0) + 1
        item["status"] = "pending"
        return {"job": slot_id, "released": True, "charged": False}
    _count_transient(item, f"RELEASED_AFTER_FREE_LIMIT: {reason}")
    return {"job": slot_id, "released": True, "charged": True, "status": item["status"]}


def request_redo(project, slot_id, reason, *, user_confirmed=False, compile_redo=None):
    item = job(project, slot_id)
    if item.get("status") not in {"done"}:
        raise StudioError(f"REDO_NOT_ALLOWED: {slot_id} is {item.get('status')}; only a finished image can be regenerated")
    if item.get("route") != "generate":
        raise StudioError(f"REDO_NOT_ALLOWED: {slot_id} was made locally from a photo; change plan.json (route) instead")
    if not str(reason or "").strip():
        raise StudioError("REDO_REASON_REQUIRED: say what is wrong, e.g. --redo 03_primary_use_case \"headline misspelled\"")
    if item.get("redos", 0) >= redo_budget(project, slot_id) and not user_confirmed:
        raise StudioError(f"REDO_LIMIT_REACHED: {slot_id} was already regenerated; ask the user, then add --user-confirmed")
    item["redos"] = item.get("redos", 0) + 1
    item.update(status="pending", pending_kind="redo", correction=str(reason).strip()[:400])
    if compile_redo:
        compile_redo(item, item["correction"])
    return {"job": slot_id, "status": "pending", "redos": item["redos"]}


def reject(project, slot_id, reason):
    item = job(project, slot_id)
    item.update(status="failed", failed_reason=f"REJECTED: {str(reason)[:300]}", rejected=True)
    item.pop("active_attempt", None)
    return {"job": slot_id, "status": "failed"}


def reset(project, slot_id, reason):
    item = job(project, slot_id)
    if item.get("status") != "failed":
        raise StudioError(f"RESET_NOT_ALLOWED: {slot_id} is {item.get('status')}, not failed")
    item.setdefault("resets", []).append({"at": time.time(), "reason": str(reason)[:300]})
    item.update(status="pending", transient_failures=0, pending_kind="retry")
    for key in ("failed_reason", "rejected"):
        item.pop(key, None)
    return {"job": slot_id, "status": "pending"}


# ---------------------------------------------------------------- the set's model (V8.1)

def update_cast(project, text, members, anchor=None):
    """plan: store the cast; a changed cast text clears the model and starts a new epoch."""
    text = (text or "").strip()
    state = project.get("cast")
    if not text or not members:
        if state:
            state.update(members=[], anchor=None)
        return state
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if not state or state.get("sha256") != digest:
        history = list((state or {}).get("history") or [])
        if state and state.get("identity"):
            history.append({"identity": state["identity"], "reason": "cast text changed", "at": time.time()})
        state = {"text": text, "sha256": digest, "members": [], "anchor": None,
                 "epoch": int((state or {}).get("epoch") or 0) + 1, "identity": None, "history": history}
        project["cast"] = state
    state["members"] = list(members)
    if not state.get("identity"):
        if anchor in members:
            state["anchor"] = anchor
        elif state.get("anchor") not in members:
            state["anchor"] = None
    return state


def effective_anchor(project):
    """The member that defines the model: the stored anchor while it can still produce one, else the
    first member that can (persisted, so two anchors never exist)."""
    state = project.get("cast") or {}
    if not state.get("members"):
        return None
    if state.get("identity"):
        return state["identity"]["job"]

    def usable(slot_id):
        item = project["jobs"].get(slot_id) or {}
        return item.get("status") in {"pending", "generating"} and item.get("route") == "generate"
    if state.get("anchor") in state["members"] and usable(state["anchor"]):
        return state["anchor"]
    for slot_id in state["members"]:
        if usable(slot_id):
            state["anchor"] = slot_id
            return slot_id
    return None


def live_identity(project, project_dir):
    """The current model image, or None (cleared when its file is missing/changed or its job left the set)."""
    state = project.get("cast") or {}
    identity = state.get("identity")
    if not identity:
        return None
    path = Path(project_dir) / identity["path"]
    if identity["job"] not in (state.get("members") or []):
        clear_identity(project, "the image that defined the model no longer shows a person")
        return None
    if not path.is_file() or sha256_file(path) != identity["sha256"]:
        clear_identity(project, "the model image is missing or changed on disk")
        return None
    return identity


def note_identity(project, slot_id, item, attempt, raw_rel, digest):
    """An anchor result of the current epoch defines the set's model (once). Returns True when it did."""
    state = project.get("cast") or {}
    if (state.get("identity") or attempt.get("cast_role") != "anchor" or attempt.get("cast_epoch") != state.get("epoch")
            or state.get("anchor") != slot_id):
        return False
    state["identity"] = {"job": slot_id, "attempt": attempt["id"], "path": raw_rel, "sha256": digest,
                         "epoch": state.get("epoch"), "at": time.time()}
    item["identity_sha256"] = digest
    attempt["identity_sha256"] = digest
    return True


def clear_identity(project, reason):
    state = project.get("cast")
    if not state or not state.get("identity"):
        return state
    state.setdefault("history", []).append({"identity": state["identity"], "reason": str(reason)[:300], "at": time.time()})
    state["identity"] = None
    state["epoch"] = int(state.get("epoch") or 0) + 1
    return state


def recast(project, slot_id, reason, *, user_confirmed=False, compile_redo=None):
    """Regenerate the image that defined the model with a brand-new person (counts as its redo)."""
    state = project.get("cast") or {}
    identity = state.get("identity")
    if not identity or identity["job"] != slot_id:
        holder = identity["job"] if identity else "none yet"
        raise StudioError(f"RECAST_NOT_ALLOWED: only the image that defined the set's model ({holder}) can be recast; "
                          "use --redo for other images")
    result = request_redo(project, slot_id, reason, user_confirmed=user_confirmed, compile_redo=compile_redo)
    previous = [member for member in state.get("members") or [] if member != slot_id
                and (project["jobs"].get(member) or {}).get("status") == "done"
                and project["jobs"][member].get("identity_sha256") == identity["sha256"]]
    clear_identity(project, f"recast: {reason}")
    state["anchor"] = slot_id
    project["jobs"][slot_id].pop("identity_sha256", None)
    return {**result, "recast": True, "made_with_previous_model": previous}


def cast_summary(project):
    state = project.get("cast") or {}
    if not state.get("members"):
        return None
    identity = state.get("identity")
    return {"members": state["members"], "anchor": effective_anchor(project), "epoch": state.get("epoch"),
            "model_defined_by": identity["job"] if identity else None}


def model_mismatch(project):
    """Finished member images that were not made with the current model."""
    state = project.get("cast") or {}
    identity = state.get("identity")
    if not state.get("members") or not identity:
        return []
    return [member for member in state["members"] if (project["jobs"].get(member) or {}).get("status") == "done"
            and project["jobs"][member].get("identity_sha256") != identity["sha256"]]


def _record_success(project):
    network = project["network"]
    if network.get("cap"):
        network["successes"] = network.get("successes", 0) + 1
        if network["successes"] >= 2:
            network["cap"] = int(network["cap"]) + 1
            network["successes"] = 0
            if network["cap"] >= int(project.get("concurrency") or DEFAULT_CONCURRENCY):
                network["cap"] = None


def summary(project):
    rows = []
    for slot_record in project["slots"]:
        item = project["jobs"].get(slot_record["id"])
        row = {"job": slot_record["id"], "status": item.get("status") if item else "unplanned"}
        if item:
            for key in ("route", "final", "warnings", "failed_reason", "redos", "transient_failures", "check_suggested"):
                if item.get(key):
                    row[key] = item[key]
        rows.append(row)
    counts = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {"jobs": rows, "counts": counts}
