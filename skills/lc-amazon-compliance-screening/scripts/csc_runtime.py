"""Portable text I/O and distribution checks. Python 3.9+, standard library."""
import codecs
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys


def configure_stdio():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")


def decode_text(raw, legacy_csv=False):
    # UTF-32 also starts with a UTF-16 BOM; do not misinterpret it.
    if raw.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        raise ValueError("不支持 UTF-32；请另存为 UTF-8 或带 BOM 的 UTF-16")
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw.decode("utf-16")
    if raw.startswith(codecs.BOM_UTF8):
        return raw.decode("utf-8-sig")
    for encoding in (("utf-8", "gb18030") if legacy_csv else ("utf-8",)):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise ValueError("无法识别文件编码；请另存为 UTF-8 或带 BOM 的 UTF-16")


def read_json(path):
    return json.loads(decode_text(Path(path).read_bytes()))


def write_csv(path, text):
    # render_csv already includes one BOM and CRLF; disable OS newline translation.
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def require_excel():
    try:
        import openpyxl
    except ImportError as exc:
        raise ValueError("处理 .xlsx 需要 openpyxl；请使用当前 Python（" + sys.executable +
                         "）执行 -m pip install -r <Skill目录>/requirements.txt；或先运行 doctor --require-excel") from exc
    try:
        version = tuple(int(p) for p in openpyxl.__version__.split(".")[:2])
    except (AttributeError, ValueError) as exc:
        raise ValueError("无法识别 openpyxl 版本，请按 requirements.txt 安装") from exc
    if not (3, 1) <= version < (4, 0):
        raise ValueError("需要 openpyxl>=3.1,<4；请使用当前 Python 按 requirements.txt 安装")
    return openpyxl


def manifest_entries(root, manifest):
    """Validate the whitelist before reading files or putting any path in a ZIP."""
    root = Path(root).resolve()
    if not isinstance(manifest, dict) or manifest.get("schema") != "SKILL-DISTRIBUTION/1.0":
        raise ValueError("发行清单格式不正确")
    if manifest.get("package_name") != "lc-amazon-compliance-screening":
        raise ValueError("发行包名称不正确")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("发行清单缺少文件列表")
    seen = set()
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("发行清单文件条目必须包含字符串 path")
        name = item.get("path", "")
        p = PurePosixPath(name)
        if (not name or p.is_absolute() or ".." in p.parts or "\\" in name or ":" in name
                or name != p.as_posix() or name.casefold() == "distribution-manifest.json"
                or p.name.casefold() == "config.local.json"
                or any(part.startswith(".") or part == "__pycache__" for part in p.parts)
                or p.suffix in (".pyc", ".zip") or name.casefold() in seen):
            raise ValueError("发行清单包含不安全或重复路径：" + name)
        seen.add(name.casefold())
        path = root.joinpath(*p.parts)
        if any(root.joinpath(*p.parts[:i]).is_symlink() for i in range(1, len(p.parts) + 1)):
            raise ValueError("发行文件不能使用符号链接：" + name)
        if not path.is_file():
            raise ValueError("发行文件缺失：" + name)
        yield item, path


AUTH_BINARIES = tuple("lc-compliance-auth-check-" + suffix for suffix in (
    "darwin-amd64", "darwin-arm64", "linux-amd64", "windows-amd64.exe"))


def read_auth_settings(root):
    auth = read_json(Path(root) / "tools/auth.json")
    if not isinstance(auth, dict):
        raise ValueError("内部鉴权配置必须为对象")
    timeout = auth.get("timeout_seconds")
    hashes = auth.get("binary_sha256")
    if type(timeout) is not int or timeout <= 0:
        raise ValueError("内部鉴权超时必须为正整数")
    if not isinstance(hashes, dict) or set(hashes) != set(AUTH_BINARIES):
        raise ValueError("内部鉴权配置缺少四平台摘要")
    if any(not isinstance(h, str) or len(h) != 64 or
           any(c not in "0123456789abcdef" for c in h) for h in hashes.values()):
        raise ValueError("内部鉴权摘要格式无效")
    return timeout, hashes


def verify_manifest(root):
    manifest = read_json(Path(root) / "DISTRIBUTION-MANIFEST.json")
    count = 0
    for item, path in manifest_entries(root, manifest):
        data = path.read_bytes()
        if len(data) != item.get("bytes") or hashlib.sha256(data).hexdigest() != item.get("sha256"):
            raise ValueError("发行文件校验失败：" + item["path"])
        count += 1
    names = {item["path"] for item in manifest["files"]}
    binaries = AUTH_BINARIES
    required_files = ["SKILL.md", "scripts/csc.py", "data/rulepack.json", "data/business.json", "requirements.txt",
                      "INSTRUCTIONS.md", "config.json", "tools/auth.json", "scripts/auth_gate.py", "scripts/csc_runtime.py",
                      "scripts/csc_table.py", "scripts/build_distribution.py", "agents/openai.yaml",
                      "references/installation.md", "references/profile-guide.md", "references/judgment-rules.md",
                      "tests/auth_support.py", "tests/test_auth.py", "tests/test_portability.py", "tests/test_screening.py"]
    required_files.extend("scripts/compliance_engine/" + name + ".py" for name in (
        "__init__", "common", "match", "profile", "report", "review", "rulepack"))
    required_files.extend("references/sites/" + site + ".md" for site in (
        "US", "UK", "DE", "FR", "IT", "ES", "JP", "AU", "SA", "AE"))
    required_files.extend("tools/bin/" + name for name in binaries)
    for required in required_files:
        if required not in names:
            raise ValueError("发行清单缺少必需文件：" + required)
    config = read_json(Path(root) / "config.json")
    if not isinstance(config, dict) or config.get("backend_token") != "":
        raise ValueError("发行配置 backend_token 必须为空")
    if set(config) != {"backend_url", "backend_token"}:
        raise ValueError("发行 config.json 只允许 backend_url 和 backend_token")
    _, hashes = read_auth_settings(root)
    for name in binaries:
        if hashlib.sha256((Path(root) / "tools/bin" / name).read_bytes()).hexdigest() != hashes[name]:
            raise ValueError("鉴权二进制与配置摘要不一致：" + name)
    return manifest, count
