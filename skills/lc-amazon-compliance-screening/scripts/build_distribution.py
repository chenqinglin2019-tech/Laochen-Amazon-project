"""Build a checked, whitelist-only ZIP; never include local user data or caches."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import zipfile

import csc_runtime as runtime

ROOT = Path(__file__).resolve().parent.parent


def build(destination, refresh=False):
    target = Path(destination).resolve()
    if target.suffix.lower() != ".zip":
        raise ValueError("输出文件必须为 .zip")
    manifest_path = ROOT / "DISTRIBUTION-MANIFEST.json"
    if refresh:
        manifest = runtime.read_json(manifest_path)
        # Refresh only existing whitelist entries; never scan the directory for additions.
        for item, path in runtime.manifest_entries(ROOT, manifest):
            data = path.read_bytes()
            item.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    manifest, count = runtime.verify_manifest(ROOT)
    from compliance_engine import RulePack
    pack = RulePack.load(ROOT / "data/rulepack.json")
    if pack.version != manifest.get("rulepack") or pack.digest != manifest.get("rulepack_digest"):
        raise ValueError("规则包与发行清单不一致")
    with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".zip", delete=False) as fh:
        temporary = Path(fh.name)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for item, path in runtime.manifest_entries(ROOT, manifest):
                data = path.read_bytes()
                if hashlib.sha256(data).hexdigest() != item["sha256"]:
                    raise ValueError("打包时文件发生变化：" + item["path"])
                entry = zipfile.ZipInfo(manifest["package_name"] + "/" + item["path"])
                entry.create_system = 3  # Unix mode metadata, including builds on Windows.
                executable = item["path"].startswith("tools/bin/") and not item["path"].endswith(".exe")
                entry.external_attr = (0o100755 if executable else 0o100644) << 16
                archive.writestr(entry, data, compress_type=zipfile.ZIP_DEFLATED)
            archive.writestr(manifest["package_name"] + "/DISTRIBUTION-MANIFEST.json", manifest_path.read_bytes())
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return {"ok": True, "zip": str(target), "files": count + 1,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}


def main():
    runtime.configure_stdio()
    parser = argparse.ArgumentParser(description="按发行清单打包 Skill")
    parser.add_argument("--out", required=True)
    parser.add_argument("--refresh-manifest", action="store_true", help="维护者修改代码后，重新计算白名单文件摘要")
    args = parser.parse_args()
    try:
        result = build(args.out, args.refresh_manifest)
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
