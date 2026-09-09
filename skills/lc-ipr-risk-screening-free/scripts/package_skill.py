#!/usr/bin/env python3
"""Build a portable, allowlisted ZIP without modifying the installed skill."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import zipfile

SCHEMA = "SKILL-DISTRIBUTION/1.0"
MANIFEST = "DISTRIBUTION-MANIFEST.json"
HISTORY_PATH = "references/upgrade-validation-v24.md"
HISTORY_TRANSFORM = "redact_sender_history_v1"
PRIVATE_FILES = {".env", "config.json", "config.local.json"}
FORBIDDEN_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
                   ".ruff_cache", "runs", "runs-free", "raw", "screenshots", "logs", "reports",
                   "quota", "quota-state", "dist", "build", ".ds_store"}
STATE_FILES = {"task.json", "evidence.json", "assessment.json", "normalized-candidates.json",
               "materiality-annotations.json", "supplemental-evidence.json", "source-capabilities.json",
               "browser-execution-status.json", "action-recoveries.json", "rolling-seven-days.json"}
SECRET_KEY = re.compile(r"(?:token|secret|password|api[_-]?key|consumer[_-]?key|client[_-]?id)$", re.I)
# Reject concrete user profile paths, not URL paths such as https://host/home/index/.
MACHINE_PATH = re.compile(r"(?<![\w:/])(?:/[U]sers/[^\s`\"'<>\)\]]+|/[h]ome/[^\s`\"'<>\)\]]+|"
                          r"/[v]ar/folders/[^\s`\"'<>\)\]]+|[A-Za-z]:[\\/]+Users[\\/]+[^\s`\"'<>\)\]]+)")
BINARY_MACHINE_PATH = re.compile(MACHINE_PATH.pattern.removeprefix(r"(?<![\w:/])"))
PLATFORM_BINARIES = {"tools/bin/lc-ipr-auth-check-"+suffix for suffix in
                     ("darwin-amd64", "darwin-arm64", "linux-amd64", "windows-amd64.exe")}
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(rb"\bsk_live_[A-Za-z0-9]{16,}\b"),
)


class PackageError(ValueError):
    """Errors disclose a rule and relative filename, never matching contents."""


def _fail(code, path=""):
    raise PackageError(code + (": " + path if path else ""))


def _relative_path(value):
    if not isinstance(value, str) or not value or "\\" in value:
        _fail("INVALID_DISTRIBUTION_PATH")
    path = PurePosixPath(value)
    parts = path.parts
    if (not parts or path.is_absolute() or path.as_posix() != value or any(p in {".", ".."} for p in parts)
            or any(re.search(r'[<>:"|?*\x00-\x1f]', p) or p.endswith((".", " "))
                   or p.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *["COM"+str(i) for i in range(1, 10)], *["LPT"+str(i) for i in range(1, 10)]}
                   for p in parts)):
        _fail("INVALID_DISTRIBUTION_PATH")
    lower = {p.lower() for p in parts}
    filename = parts[-1].lower()
    if (lower & FORBIDDEN_PARTS or lower & PRIVATE_FILES or filename in STATE_FILES
            or filename.endswith((".pyc", ".pyo", ".log", ".zip", ".lock"))
            or filename.startswith(".env.") and filename != ".env.example"
            or filename == MANIFEST.lower()):
        _fail("PRIVATE_OR_RUNTIME_PATH_FORBIDDEN", value)
    return value


def _read_regular(root, relative):
    """No symlink traversal, special files, or hardlink aliases of private files."""
    path = root
    for part in PurePosixPath(relative).parts:
        path /= part
        try:
            info = path.lstat()
        except FileNotFoundError:
            _fail("REQUIRED_DISTRIBUTION_FILE_MISSING", relative)
        if stat.S_ISLNK(info.st_mode):
            _fail("DISTRIBUTION_SYMLINK_FORBIDDEN", relative)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        _fail("DISTRIBUTION_FILE_TYPE_FORBIDDEN", relative)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_ino, opened.st_dev) != (info.st_ino, info.st_dev):
            _fail("SOURCE_CHANGED_DURING_READ", relative)
        content = stream.read()
        after = os.fstat(stream.fileno())
    if (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        _fail("SOURCE_CHANGED_DURING_READ", relative)
    return content


def _env_values(data):
    result = {}
    for line in data.decode("utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in result:
            _fail("INVALID_CREDENTIAL_REFERENCE")
        if value[:1] in {"'", '"'}:
            if len(value) < 2 or value[-1] != value[0]:
                _fail("INVALID_CREDENTIAL_REFERENCE")
            value = value[1:-1]
        result[key] = value
    return result


def _reference_secrets(root):
    # Private files are never copied, hashed into the deliverable, or printed.
    result = []
    for name in sorted(PRIVATE_FILES):
        if not os.path.lexists(root / name):
            continue
        try:
            data = _read_regular(root, name)
            values = _env_values(data) if name == ".env" else json.loads(data)
        except (OSError, UnicodeError, json.JSONDecodeError):
            _fail("INVALID_CREDENTIAL_REFERENCE")
        def visit(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if SECRET_KEY.search(key) and isinstance(item, str) and item:
                        result.append(item)
                    else:
                        visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)
        visit(values)
    return result


def _secret_needles(values):
    needles = set()
    for value in values:
        if not isinstance(value, str):
            _fail("INVALID_KNOWN_SECRET_TYPE")
        entropy = -sum((value.count(char) / len(value)) * math.log2(value.count(char) / len(value))
                       for char in set(value)) if value else 0
        # A single letter is not a reliable fingerprint. Empty-template checks still
        # reject every populated credential, including short/low-entropy values.
        if len(value) < 8 or entropy < 2.5:
            continue
        needles.update((value.encode(), value.encode("utf-16-le"),
                        json.dumps(value, ensure_ascii=True)[1:-1].encode()))
    return needles


def _empty_template(relative, content):
    filename = PurePosixPath(relative).name.lower()
    try:
        if filename in {".env.example", ".env"} and any(_env_values(content).values()):
            _fail("POPULATED_CREDENTIAL_TEMPLATE", relative)
        if filename == "config.example.json":
            obj = json.loads(content)
            if (not isinstance(obj, dict) or set(obj) != {"backend_url", "backend_token"}
                    or obj["backend_token"] != "" or not isinstance(obj["backend_url"], str)
                    or not obj["backend_url"].startswith("https://")
                    or re.search(r"[?@#]", obj["backend_url"])):
                _fail("POPULATED_OR_INVALID_CONFIG_TEMPLATE", relative)
    except (UnicodeError, json.JSONDecodeError):
        _fail("INVALID_CREDENTIAL_TEMPLATE", relative)


def _transform(relative, content, transform):
    if transform is None:
        return content
    if relative != HISTORY_PATH or transform != HISTORY_TRANSFORM:
        _fail("UNSUPPORTED_DISTRIBUTION_TRANSFORM", relative)
    text = content.decode("utf-8-sig")
    # Never manufacture an executable recipient restore command from sender history.
    text = re.sub(r"```[^\n]*\n.*?```", lambda m: "```text\n发送者历史本机恢复命令已脱敏；不适用于接收者环境。\n```"
                  if MACHINE_PATH.search(m[0]) else m[0], text, flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: m[1]+"（发送者历史本机路径已脱敏）"
                  if MACHINE_PATH.search(m[2]) else m[0], text)
    text = MACHINE_PATH.sub("发送者历史本机路径已脱敏", text)
    return ("> 分发说明：以下保留发送者历史记录；本机路径及恢复命令已脱敏，不提供接收者可执行的历史恢复命令。\n\n" + text).encode()


def _scan(relative, content, kind, needles, sender_roots):
    if any(needle in content for needle in needles) or any(pattern.search(content) for pattern in SECRET_PATTERNS):
        _fail("SECRET_DETECTED", relative)
    for root in sender_roots:
        for encoding in ("utf-8", "utf-16-le"):
            if root and root.encode(encoding) in content:
                _fail("SENDER_MACHINE_PATH_DETECTED", relative)
    if kind == "binary":
        # Native executables can carry sender build paths in either string format.
        for encoding, offset in (("utf-8", 0), ("utf-16-le", 0), ("utf-16-le", 1)):
            if BINARY_MACHINE_PATH.search(content[offset:].decode(encoding, errors="ignore")):
                _fail("SENDER_MACHINE_PATH_DETECTED", relative)
    if kind == "text":
        try:
            text = content.decode("utf-8-sig")
        except UnicodeError:
            _fail("DISTRIBUTION_TEXT_NOT_UTF8", relative)
        if MACHINE_PATH.search(text):
            _fail("SENDER_MACHINE_PATH_DETECTED", relative)
        if relative.endswith(".json"):
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                _fail("DISTRIBUTION_JSON_INVALID", relative)
            if isinstance(obj, dict) and (str(obj.get("schema", "")).startswith("SERPER-ACCOUNT-")
                    or "source_runs" in obj or "credential_fingerprint" in obj or "account_fingerprint" in obj):
                _fail("ACCOUNT_OR_EVIDENCE_STATE_FORBIDDEN", relative)
    _empty_template(relative, content)


def package_skill(source_root, output_dir, *, allowlist_path=None, archive_name=None, known_secrets=()):
    root = Path(source_root).resolve(strict=True)
    destination = Path(output_dir).resolve()
    if destination == root or root in destination.parents:
        _fail("OUTPUT_MUST_BE_OUTSIDE_SOURCE")
    spec_path = Path(allowlist_path).resolve() if allowlist_path else root / "references/distribution-files.json"
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        _fail("INVALID_DISTRIBUTION_ALLOWLIST")
    if (not isinstance(spec, dict) or spec.get("schema") != SCHEMA
            or not isinstance(spec.get("package_name"), str)
            or not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", spec["package_name"])
            or not isinstance(spec.get("files"), list) or not spec["files"]):
        _fail("INVALID_DISTRIBUTION_ALLOWLIST")
    entries, seen = [], set()
    for entry in spec["files"]:
        if (not isinstance(entry, dict) or entry.get("kind") not in ("text", "binary")
                or entry.get("required") is not True or entry.get("mode") not in ("0644", "0755")
                or set(entry) - {"path", "kind", "required", "mode", "transform"}):
            _fail("INVALID_DISTRIBUTION_ENTRY")
        name = _relative_path(entry.get("path"))
        if entry["kind"] == "binary" and name not in PLATFORM_BINARIES:
            _fail("UNSUPPORTED_DISTRIBUTION_BINARY", name)
        if name.casefold() in seen:
            _fail("DUPLICATE_DISTRIBUTION_PATH", name)
        seen.add(name.casefold()); entries.append(entry)
    filename = archive_name or spec["package_name"] + ".zip"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.zip", filename):
        _fail("INVALID_ARCHIVE_NAME")
    final = destination / filename
    if os.path.lexists(final):
        _fail("OUTPUT_ALREADY_EXISTS")
    needles = _secret_needles([*_reference_secrets(root), *known_secrets,
                               os.environ.get("LAOCHEN_BACKEND_TOKEN", "")])
    roots = {str(root), str(Path(source_root).absolute()), str(Path.home()),
             str(root).replace("\\", "/")}
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".skill-package-stage-", dir=destination) as temporary:
        stage = Path(temporary); tree = stage / spec["package_name"]; tree.mkdir()
        manifest = {"schema": SCHEMA, "package_name": spec["package_name"], "files": []}
        source_hashes = {}
        for entry in sorted(entries, key=lambda item: item["path"]):
            relative = entry["path"]
            source = _read_regular(root, relative)
            source_hashes[relative] = hashlib.sha256(source).hexdigest()
            # Secret scanning also precedes the one permitted historical transform.
            if any(needle in source for needle in needles) or any(p.search(source) for p in SECRET_PATTERNS):
                _fail("SECRET_DETECTED", relative)
            content = _transform(relative, source, entry.get("transform"))
            _scan(relative, content, entry["kind"], needles, roots)
            target = tree / relative; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content); target.chmod(int(entry["mode"], 8))
            record = {"path": relative, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(), "mode": entry["mode"]}
            if entry.get("transform"):
                record.update(transform=entry["transform"], source_sha256=hashlib.sha256(source).hexdigest())
            manifest["files"].append(record)
        # Distribute an immediately editable empty file, never the sender's
        # populated .env. Only the already validated, allowlisted template may
        # supply this generated entry; source .env remains forbidden above.
        if ".env.example" in source_hashes:
            content = (tree / ".env.example").read_bytes()
            _scan(".env", content, "text", needles, roots)
            target = tree / ".env"
            target.write_bytes(content)
            target.chmod(0o600)
            manifest["files"].append({"path": ".env", "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(), "mode": "0600",
                "generated_from": ".env.example"})
        manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2)+"\n").encode()
        _scan(MANIFEST, manifest_bytes, "text", needles, roots)
        (tree / MANIFEST).write_bytes(manifest_bytes)
        for relative, expected in source_hashes.items():
            if hashlib.sha256(_read_regular(root, relative)).hexdigest() != expected:
                _fail("SOURCE_CHANGED_DURING_PACKAGE", relative)
        staged_zip = stage / "archive.zip"
        with zipfile.ZipFile(staged_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for entry in [*manifest["files"], {"path": MANIFEST, "mode": "0644"}]:
                name = entry["path"]; info = zipfile.ZipInfo(spec["package_name"]+"/"+name)
                info.create_system = 3; info.external_attr = (stat.S_IFREG | int(entry["mode"], 8)) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, (tree/name).read_bytes())
        with staged_zip.open("r+b") as stream:
            os.fsync(stream.fileno())
        with zipfile.ZipFile(staged_zip) as archive:
            if archive.testzip() is not None:
                _fail("ARCHIVE_INTEGRITY_FAILED")
            for entry in manifest["files"]:
                content = archive.read(spec["package_name"]+"/"+entry["path"])
                if hashlib.sha256(content).hexdigest() != entry["sha256"]:
                    _fail("ARCHIVE_MANIFEST_MISMATCH")
        digest = hashlib.sha256(staged_zip.read_bytes()).hexdigest()
        try:
            # Same-filesystem hardlink is an atomic, no-clobber publication on
            # POSIX and NTFS. Unsupported filesystems fail closed; no partial ZIP.
            os.link(staged_zip, final)
        except FileExistsError:
            _fail("OUTPUT_ALREADY_EXISTS")
        except OSError:
            _fail("ATOMIC_PUBLICATION_UNAVAILABLE")
    return {"archive": str(final), "sha256": digest, "file_count": len(manifest["files"]),
            "manifest": spec["package_name"]+"/"+MANIFEST}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allowlist", type=Path)
    parser.add_argument("--archive-name")
    args = parser.parse_args()
    try:
        result = package_skill(args.source_root, args.output_dir, allowlist_path=args.allowlist, archive_name=args.archive_name)
    except (PackageError, OSError) as error:
        # Raw OSError text can contain user-controlled paths/content. Only named
        # PackageError rules are user-facing; never log credentials or the spec.
        print(json.dumps({"status": "blocked", "error": str(error) if isinstance(error, PackageError) else "PACKAGE_IO_ERROR"}))
        return 2
    print(json.dumps({"status": "created", **result}, ensure_ascii=False)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
