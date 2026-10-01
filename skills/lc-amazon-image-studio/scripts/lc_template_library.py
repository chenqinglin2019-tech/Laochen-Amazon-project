#!/usr/bin/env python3
"""User template library outside the skill folder (survives upgrades).

Layout under <library dir> (see lc_paths.library_dir):
  settings.json           built-in library enabled/disabled, migrations
  user_templates.json     schema v2 families/templates/sources (lc_template_schema)
  user_templates_v1.json  earlier text-only user records migrated from the skill folder
  asset_index.json        {sha256: {kind, ext, size, bytes, derived_from}}
  assets/<aa>/<sha>.<ext> content-addressed originals, style plates, thumbnails
  intake/<packet>/  backups/<utc>-<op>/  .library.lock
Existing projects never read the library after adoption (they keep snapshots and
project copies of plates), so clearing or restoring never changes them.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from lc_paths import library_dir  # noqa: E402

ROOT = SCRIPT_DIR.parent
SKILL_USER_FILE = ROOT / "assets/layouts/design_templates.user.json"
ARCHIVE_FORMAT = "lc-template-library"
ARCHIVE_MEMBER = re.compile(r"^(?:settings|user_templates|user_templates_v1|asset_index|manifest)\.json$"
                            r"|^assets/[0-9a-f]{2}/[0-9a-f]{64}\.(?:jpg|jpeg|png|webp)$")
MAX_ARCHIVE_MEMBERS, MAX_ARCHIVE_BYTES = 20000, 4 * 1024 ** 3
ASSET_KINDS = {"reference", "plate", "thumb"}


class LibraryError(RuntimeError):
    pass


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _replace(source: Path, target: Path) -> None:
    """os.replace with a short retry (Windows antivirus/indexer locks)."""
    for attempt in range(20):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.1)


class Library:
    def __init__(self, root=None):
        self.root = library_dir(root)

    # ---- paths -----------------------------------------------------------
    @property
    def settings_path(self):
        return self.root / "settings.json"

    @property
    def v2_path(self):
        return self.root / "user_templates.json"

    @property
    def v1_path(self):
        return self.root / "user_templates_v1.json"

    @property
    def index_path(self):
        return self.root / "asset_index.json"

    def asset_path(self, sha: str, ext: str | None = None) -> Path:
        if ext is None:
            ext = (self.asset_index().get(sha) or {}).get("ext", "jpg")
        return self.root / "assets" / sha[:2] / f"{sha}.{ext}"

    def lock(self):
        from lc_style_reference import _selection_lock
        self.root.mkdir(parents=True, exist_ok=True)
        return _selection_lock(self.root / "library")

    # ---- documents -------------------------------------------------------
    def _read(self, path, default):
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return copy.deepcopy(default)
        except (OSError, ValueError) as exc:
            raise LibraryError(f"Cannot read {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise LibraryError(f"{path} must contain a JSON object")
        return value

    def _write(self, path, value):
        from lc_style_reference import _write_json
        _write_json(Path(path), value)

    def settings(self) -> dict:
        value = self._read(self.settings_path, {"schema_version": 1, "builtin": {"enabled": True}, "migrations": {}})
        value.setdefault("builtin", {"enabled": True})
        value.setdefault("migrations", {})
        return value

    def builtin_enabled(self) -> bool:
        return self.settings()["builtin"].get("enabled", True) is not False

    def set_builtin(self, enabled: bool) -> dict:
        with self.lock():
            settings = self.settings()
            settings["builtin"] = {"enabled": bool(enabled), "changed_at": time.time()}
            self._write(self.settings_path, settings)
        return settings

    def load_v2(self) -> dict:
        from lc_template_schema import empty_document, validate_document
        document = self._read(self.v2_path, empty_document())
        errors = validate_document(document)
        if errors:
            raise LibraryError("User template library v2 is invalid:\n- " + "\n- ".join(errors[:20]))
        return document

    def asset_index(self) -> dict:
        return self._read(self.index_path, {})

    # ---- assets ----------------------------------------------------------
    def add_asset(self, payload: bytes, kind: str, ext: str, *, derived_from: str | None = None,
                  size=None) -> str:
        if kind not in ASSET_KINDS or ext not in {"jpg", "jpeg", "png", "webp"}:
            raise LibraryError(f"Unsupported asset {kind}/{ext}")
        sha = _sha_bytes(payload)
        target = self.asset_path(sha, ext)
        if target.is_file():
            if _sha_file(target) != sha:
                raise LibraryError(f"Stored asset {sha} is corrupted; restore the library from a backup")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(dir=target.parent, prefix=".asset-", delete=False)
            try:
                with handle:
                    handle.write(payload)
                _replace(Path(handle.name), target)
            finally:
                if os.path.exists(handle.name):
                    os.unlink(handle.name)
        index = self.asset_index()
        index[sha] = {"kind": kind, "ext": ext, "bytes": len(payload), "size": list(size) if size else None,
                      "derived_from": derived_from}
        self._write(self.index_path, index)
        return sha

    # ---- migration -------------------------------------------------------
    def migrate_skill_user_file(self) -> dict:
        """Copy earlier in-skill user records once (the skill file is never modified)."""
        if not SKILL_USER_FILE.is_file():
            return {"migrated": False, "reason": "no in-skill user file"}
        payload = SKILL_USER_FILE.read_bytes()
        try:
            document = json.loads(payload)
        except ValueError:
            return {"migrated": False, "reason": "in-skill user file is not valid JSON; left untouched"}
        if not any(document.get(key) for key in ("sources", "families", "templates")):
            return {"migrated": False, "reason": "in-skill user file is empty"}
        marker = _sha_bytes(payload)
        with self.lock():
            settings = self.settings()
            if settings["migrations"].get("skill_user_json", {}).get("sha256") == marker:
                return {"migrated": False, "reason": "already migrated"}
            import lc_design_templates as v1
            result = v1.import_library(document, user_path=self.v1_path, builtin_path=v1.DEFAULT_BUILTIN)
            settings["migrations"]["skill_user_json"] = {"sha256": marker, "at": time.time()}
            self._write(self.settings_path, settings)
        return {"migrated": True, "added": result.get("added"), "reused": result.get("reused")}

    # ---- backups / clear / restore ---------------------------------------
    def _backup(self, operation: str) -> str:
        import uuid
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"-{uuid.uuid4().hex[:6]}-{operation}"
        target = self.root / "backups" / stamp
        target.mkdir(parents=True, exist_ok=False)
        for name in ("settings.json", "user_templates.json", "user_templates_v1.json", "asset_index.json"):
            if (self.root / name).is_file():
                shutil.copy2(self.root / name, target / name)
        if (self.root / "assets").is_dir():
            shutil.copytree(self.root / "assets", target / "assets")
        (target / "backup.json").write_text(json.dumps({"operation": operation, "at": time.time()}), encoding="utf-8")
        return stamp

    def backups(self) -> list:
        folder = self.root / "backups"
        return sorted(item.name for item in folder.iterdir() if item.is_dir()) if folder.is_dir() else []

    def clear(self, *, builtin=False, user=False, reason="") -> dict:
        if not builtin and not user:
            raise LibraryError("Choose --builtin, --user or --all")
        from lc_template_schema import empty_document
        with self.lock():
            backup = self._backup("clear") if user else None
            if user:
                for name in ("user_templates.json", "user_templates_v1.json", "asset_index.json"):
                    (self.root / name).unlink(missing_ok=True)
                shutil.rmtree(self.root / "assets", ignore_errors=True)
                self._write(self.v2_path, empty_document())
            if builtin:
                settings = self.settings()
                settings["builtin"] = {"enabled": False, "changed_at": time.time(), "reason": reason}
                self._write(self.settings_path, settings)
        return {"builtin_enabled": self.builtin_enabled(), "user_cleared": bool(user), "backup": backup,
                "note": "Existing projects keep their adopted snapshots and plates."}

    def restore(self, backup: str | None = None, *, latest=False, builtin=False, restore_settings=True) -> dict:
        if builtin and not backup and not latest:
            return {"builtin_enabled": self.set_builtin(True)["builtin"]["enabled"]}
        names = self.backups()
        name = names[-1] if latest and names else backup
        if not name or name not in names:
            raise LibraryError(f"Unknown backup {backup!r}; available: {names}")
        source = self.root / "backups" / name
        with self.lock():
            safety = self._backup("before-restore")
            for item in ("user_templates.json", "user_templates_v1.json", "asset_index.json") + (("settings.json",) if restore_settings else ()):
                if (source / item).is_file():
                    shutil.copy2(source / item, self.root / item)
                elif item != "settings.json":
                    (self.root / item).unlink(missing_ok=True)
            shutil.rmtree(self.root / "assets", ignore_errors=True)
            if (source / "assets").is_dir():
                shutil.copytree(source / "assets", self.root / "assets")
        self.load_v2()
        return {"restored": name, "safety_backup": safety}

    # ---- export / import -------------------------------------------------
    def export(self, output: Path, *, originals=True) -> dict:
        output = Path(output)
        index = self.asset_index()
        files = {}
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in ("settings.json", "user_templates.json", "user_templates_v1.json", "asset_index.json"):
                path = self.root / name
                if path.is_file():
                    archive.write(path, name)
                    files[name] = _sha_file(path)
            for sha, meta in sorted(index.items()):
                if meta.get("kind") == "reference" and not originals:
                    continue
                path = self.asset_path(sha, meta.get("ext"))
                if path.is_file():
                    member = f"assets/{sha[:2]}/{sha}.{meta.get('ext', 'jpg')}"
                    archive.write(path, member)
                    files[member] = sha
            archive.writestr("manifest.json", json.dumps({"format": ARCHIVE_FORMAT, "format_version": 1,
                                                          "files": files, "includes_originals": originals}))
        return {"archive": str(output), "files": len(files), "includes_originals": originals}

    def import_archive(self, archive_path: Path, *, mode="merge") -> dict:
        from lc_template_schema import validate_document
        archive_path = Path(archive_path)
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_MEMBERS or sum(item.file_size for item in infos) > MAX_ARCHIVE_BYTES:
                raise LibraryError("Library archive is too large")
            for item in infos:
                if item.is_dir():
                    continue
                if not ARCHIVE_MEMBER.fullmatch(item.filename):
                    raise LibraryError(f"Unexpected archive member {item.filename!r}; refusing to import")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("format") != ARCHIVE_FORMAT:
                raise LibraryError("Not a template library archive")
            with tempfile.TemporaryDirectory(dir=self.root.parent if self.root.parent.exists() else None) as temp:
                stage = Path(temp)
                for item in infos:
                    if item.is_dir():
                        continue
                    data = archive.read(item)
                    expected = manifest["files"].get(item.filename) if item.filename != "manifest.json" else None
                    if item.filename.startswith("assets/"):
                        if _sha_bytes(data) != Path(item.filename).stem or expected not in (None, Path(item.filename).stem):
                            raise LibraryError(f"Asset hash mismatch in archive: {item.filename}")
                    elif expected is not None and _sha_bytes(data) != expected:
                        raise LibraryError(f"File hash mismatch in archive: {item.filename}")
                    target = stage / item.filename
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                incoming = json.loads((stage / "user_templates.json").read_text(encoding="utf-8")) if (stage / "user_templates.json").is_file() else None
                if incoming is not None:
                    errors = validate_document(incoming)
                    if errors:
                        raise LibraryError("Archive library is invalid:\n- " + "\n- ".join(errors[:20]))
                with self.lock():
                    safety = self._backup("before-import")
                    index = self.asset_index()
                    staged_index = json.loads((stage / "asset_index.json").read_text(encoding="utf-8")) if (stage / "asset_index.json").is_file() else {}
                    for path in (stage / "assets").rglob("*") if (stage / "assets").is_dir() else []:
                        if path.is_file():
                            target = self.root / path.relative_to(stage)
                            target.parent.mkdir(parents=True, exist_ok=True)
                            if not target.exists():
                                shutil.copy2(path, target)
                            index.setdefault(path.stem, staged_index.get(path.stem, {"kind": "reference", "ext": path.suffix[1:]}))
                    self._write(self.index_path, index)
                    if incoming is not None:
                        if mode == "replace":
                            self._write(self.v2_path, incoming)
                            merged = incoming
                        else:
                            merged = merge_documents(self.load_v2(), incoming)
                            self._write(self.v2_path, merged)
                    if (stage / "user_templates_v1.json").is_file() and mode == "replace":
                        shutil.copy2(stage / "user_templates_v1.json", self.v1_path)
        return {"imported": str(archive_path), "mode": mode, "safety_backup": safety,
                "families": len((incoming or {}).get("families", []))}

    # ---- status / listing ------------------------------------------------
    def status(self) -> dict:
        import lc_design_templates as v1
        from lc_template_schema import latest
        document = self.load_v2()
        index = self.asset_index()
        usage = sum(meta.get("bytes", 0) for meta in index.values())
        builtin = v1._read_json(v1.DEFAULT_BUILTIN) if v1.DEFAULT_BUILTIN.is_file() else {"families": [], "templates": []}
        return {"library_dir": str(self.root), "builtin_enabled": self.builtin_enabled(),
                "builtin": {"families": len(builtin.get("families", [])), "templates": len(builtin.get("templates", []))},
                "user_v2": {"families": len(latest(document["families"])), "templates": len(latest(document["templates"]))},
                "user_v1_records": len(self._read(self.v1_path, {"families": []}).get("families", [])),
                "assets": len(index), "asset_bytes": usage, "backups": len(self.backups())}

    def list_families(self, source="all") -> list:
        import lc_design_templates as v1
        from lc_template_schema import latest
        rows = []
        if source in {"all", "user"}:
            document = self.load_v2()
            templates = latest(document["templates"])
            for family in latest(document["families"]):
                slots = sorted({t["slot_role"] for t in templates if t["family_id"] == family["id"]})
                rows.append({"id": family["id"], "revision": family["revision"], "source": "user", "name": family["name"],
                             "categories": family["product_profile"].get("categories", []), "slots": slots,
                             "summary": (family.get("description") or "")[:140]})
        if source in {"all", "builtin"} and self.builtin_enabled() and v1.DEFAULT_BUILTIN.is_file():
            builtin = v1._read_json(v1.DEFAULT_BUILTIN)
            for family in builtin.get("families", []):
                intents = sorted({i for t in builtin.get("templates", []) if t.get("family_id") == family["id"] for i in t.get("intents", [])})
                rows.append({"id": family["id"], "revision": family["revision"], "source": "builtin", "name": family.get("name"),
                             "categories": family.get("categories", []), "intents": intents,
                             "summary": (family.get("description") or "")[:140]})
        return rows

    def gc(self, *, dry_run=True) -> dict:
        document = self.load_v2()
        referenced = set()
        for template in document["templates"]:
            referenced.update((template.get("assets") or {}).values())
        for source in document["sources"]:
            referenced.add(source.get("sha256"))
        index = self.asset_index()
        orphans = [sha for sha in index if sha not in referenced]
        if not dry_run:
            with self.lock():
                for sha in orphans:
                    self.asset_path(sha, index[sha].get("ext")).unlink(missing_ok=True)
                    index.pop(sha, None)
                self._write(self.index_path, index)
        return {"orphans": len(orphans), "removed": 0 if dry_run else len(orphans), "dry_run": dry_run}


def merge_documents(current: dict, incoming: dict) -> dict:
    """Append new records; identical id/revision must be identical content."""
    from lc_template_schema import content_hash, validate_document
    merged = copy.deepcopy(current)
    for key in ("sources", "families", "templates"):
        existing = {(r["id"], r.get("revision")): r for r in merged[key]}
        for record in incoming.get(key, []):
            identity = (record["id"], record.get("revision"))
            if identity in existing:
                if content_hash(existing[identity]) != content_hash(record):
                    raise LibraryError(f"Conflicting {key} record {identity}; import aborted")
                continue
            merged[key].append(copy.deepcopy(record))
    errors = validate_document(merged)
    if errors:
        raise LibraryError("Merged library is invalid:\n- " + "\n- ".join(errors[:20]))
    return merged


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--library-dir")
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("status")
    listing = subs.add_parser("list")
    listing.add_argument("--source", choices=("all", "user", "builtin"), default="all")
    builtin = subs.add_parser("builtin")
    group = builtin.add_mutually_exclusive_group(required=True)
    group.add_argument("--enable", action="store_true")
    group.add_argument("--disable", action="store_true")
    clear = subs.add_parser("clear")
    clear.add_argument("--builtin", action="store_true")
    clear.add_argument("--user", action="store_true")
    clear.add_argument("--all", action="store_true")
    clear.add_argument("--reason", default="")
    restore = subs.add_parser("restore")
    restore.add_argument("--backup")
    restore.add_argument("--latest", action="store_true")
    restore.add_argument("--builtin", action="store_true", help="Re-enable the built-in library")
    restore.add_argument("--no-settings", action="store_true")
    subs.add_parser("backups")
    export = subs.add_parser("export")
    export.add_argument("--output", required=True)
    export.add_argument("--no-originals", action="store_true")
    importer = subs.add_parser("import")
    importer.add_argument("--archive", required=True)
    importer.add_argument("--mode", choices=("merge", "replace"), default="merge")
    subs.add_parser("migrate")
    gc = subs.add_parser("gc")
    gc.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    library = Library(args.library_dir)
    try:
        if args.command != "migrate":
            library.migrate_skill_user_file()
        if args.command == "status":
            result = library.status()
        elif args.command == "list":
            result = {"families": library.list_families(args.source)}
        elif args.command == "builtin":
            result = {"builtin_enabled": library.set_builtin(args.enable)["builtin"]["enabled"]}
        elif args.command == "clear":
            result = library.clear(builtin=args.builtin or args.all, user=args.user or args.all, reason=args.reason)
        elif args.command == "restore":
            result = library.restore(args.backup, latest=args.latest, builtin=args.builtin,
                                     restore_settings=not args.no_settings)
        elif args.command == "backups":
            result = {"backups": library.backups()}
        elif args.command == "export":
            result = library.export(Path(args.output), originals=not args.no_originals)
        elif args.command == "import":
            result = library.import_archive(Path(args.archive), mode=args.mode)
        elif args.command == "migrate":
            result = library.migrate_skill_user_file()
        else:
            result = library.gc(dry_run=not args.apply)
        print(json.dumps({"ok": True, "command": args.command, **result}, ensure_ascii=False))
        return 0
    except (LibraryError, OSError, ValueError, zipfile.BadZipFile) as exc:
        print(json.dumps({"ok": False, "command": args.command, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
