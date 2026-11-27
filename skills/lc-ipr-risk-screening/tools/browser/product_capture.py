"""Browser-first collection and the local corroboration gate for CLI 1.0.4."""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


IMAGE_LIMIT = 20 * 1024 * 1024
IMAGE_HOSTS = {"m.media-amazon.com", "images-na.ssl-images-amazon.com", "images.amazon.com"}
ASIN_PATTERN = re.compile(r"[A-Z0-9]{10}")
REVIEW_REFS = {
    "identifier_binding": {"/asin", "/marketplace", "input-metadata/browser-capture.json#/selected_asin"},
    "text_internal_consistency": {"/facts/title", "/facts/brand", "/facts/category"},
    "main_image_consistency": {"/facts/title"},
}
CAPTURE_REF = "input-metadata/browser-capture.json"
REVIEW_REF = "input-metadata/browser-corroboration.json"
DOM_SCRIPT = Path(__file__).with_name("amazon-product.js")
FIELD_LIMITS = {
    "title": 1000, "brand": 500, "platform_category": 1000, "long_description": 20000,
    "model_number": 200, "manufacturer": 500, "color": 200, "dimensions": 500,
}


class Halt(Exception):
    def __init__(self, code, message, **context):
        super().__init__(message)
        self.code = code
        self.context = context


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def json_file(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        try:
            stream.write((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            stream.close()
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)


def sha_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(128 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def run(command, timeout=20, *, browser=False):
    env = os.environ.copy()
    if browser:
        for key in ("LAOCHEN_BACKEND_TOKEN", "SERPER_API_KEY"):
            env.pop(key, None)
        env["NO_PROXY"] = ",".join(filter(None, [env.get("NO_PROXY"), "localhost", "127.0.0.1", "::1"]))
        env["no_proxy"] = env["NO_PROXY"]
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, env=env)


def cli_call(args, command, *values, timeout=30):
    result = run([args.cli, command, *map(str, values)], timeout)
    try:
        data = json.loads(result.stdout)
    except ValueError as exc:
        raise Halt("CLI_OUTPUT_INVALID", f"无法读取 {command} 的 JSON 结果。") from exc
    if result.returncode or data.get("status") != "ready":
        raise Halt(data.get("reason_code", "CLI_FAILED"), f"{command} 未通过。",
                   missing_fields=data.get("missing_fields", []))
    return data


def chrome_installed():
    if any(shutil.which(name) for name in ("google-chrome", "google-chrome-stable", "chrome", "chrome.exe")):
        return True
    if sys.platform == "darwin":
        return any((root / "Google Chrome.app").is_dir()
                   for root in (Path("/Applications"), Path.home() / "Applications"))
    if os.name == "nt":
        import winreg
        key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, key) as entry:
                    if Path(winreg.QueryValue(entry, None)).is_file():
                        return True
            except OSError:
                pass
        return any((Path(os.environ[key]) / "Google/Chrome/Application/chrome.exe").is_file()
                   for key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA") if os.environ.get(key))
    return any(Path(p).is_file() for p in ("/opt/google/chrome/chrome", "/usr/bin/google-chrome"))


def ego_installed():
    if sys.platform == "darwin":
        return any((root / name).is_dir()
                   for root in (Path("/Applications"), Path.home() / "Applications")
                   for name in ("Ego Lite.app", "Ego.app"))
    if os.name == "nt":
        return any((Path(os.environ[key]) / suffix).exists()
                   for key in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)") if os.environ.get(key)
                   for suffix in ("Programs/Ego Lite", "Programs/ego-lite", "Ego Lite", "Ego"))
    return False


def chrome_bridge(opencli):
    check = run([opencli, "profile", "list"], 7, browser=True)
    if check.returncode:
        raise Halt("OPENCLI_SETUP_REQUIRED", "OpenCLI 无法确认 Chrome 扩展连接，请检查本机安装。")
    try:
        data = json.loads(check.stdout)
    except ValueError:
        if "No Browser Bridge profiles connected." in check.stdout:
            return False
        if re.search(r"— connected v\d", check.stdout):
            return True
        raise Halt("OPENCLI_SETUP_REQUIRED", "OpenCLI 返回了未知的扩展连接状态。")
    if not isinstance(data, dict) or data.get("ok") is not True:
        raise Halt("OPENCLI_SETUP_REQUIRED", "OpenCLI 无法确认 Chrome 扩展连接。")
    entries = data.get("data")
    if isinstance(entries, dict):
        entries = entries.get("profiles")
    if not isinstance(entries, list):
        raise Halt("OPENCLI_SETUP_REQUIRED", "OpenCLI 返回了未知的扩展连接状态。")
    return bool(entries)


def canonical_asin(url):
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    if parsed.scheme != "https" or parsed.netloc not in {"www.amazon.com", "amazon.com"}:
        return None
    found = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:/|$)", parsed.path)
    return found.group(1) if found else None


def capture_ego(exe, url, resume=None):
    guide = run([exe, "skill"], 8, browser=True)
    if guide.returncode or "[ego-browser:skill] end of guide" not in guide.stdout:
        raise Halt("EGO_SETUP_REQUIRED", "EGO CLI 的操作指南不可用，请检查安装。")
    name = json.dumps(f"IPR Amazon product {canonical_asin(url)}")
    create = (f'entry.ownership === "agentDelegatedToUser" ? await takeOverTaskSpace({resume}) : '
              f'entry.ownership === "user" ? await claimTaskSpace({resume}) : await taskSpace({resume})'
              if resume else f"await taskSpace({name})")
    page = 'task.userPage() || task.page("p1")' if resume else 'task.page("p1")'
    navigate = "" if resume else f"await page.goto({json.dumps(url)}, {{timeout: 18000}});"
    check_space = (f"const entry = (await listTaskSpaces()).find(s => s.id === {resume} && s.name === {name}); "
                   'if (!entry) throw new Error("IPR_EGO_SPACE_INVALID");' if resume else "")
    src = DOM_SCRIPT.read_text(encoding="utf-8")
    script = f"""
{check_space}
const task = {create};
console.log("IPR_SPACE=" + task.spaceId);
try {{
  let page = {page};
  if (!page.label) page = await task.adopt(page);
  {navigate}
  let product;
  for (let attempt = 0; attempt < 6; attempt++) {{
    product = await page.evaluate({src});
    if (product.challenge || (product.title && product.main_image)) break;
    await new Promise(resolve => setTimeout(resolve, 500));
  }}
  if (product.challenge) await task.handOff();
  console.log("IPR_PAGE=" + JSON.stringify(product));
}} catch (error) {{
  console.log("IPR_PAGE_ERROR=" + String(error.code || error.name));
}}
"""
    result = run([exe, "nodejs", "-e", script], 35, browser=True)
    output = result.stdout + "\n" + result.stderr
    space = re.search(r"^IPR_SPACE=(\d+)\s*$", output, re.M)
    page_data = next((line[9:] for line in output.splitlines() if line.startswith("IPR_PAGE=")), None)
    if not space:
        if resume:
            raise Halt("EGO_SPACE_UNAVAILABLE", "无法接回该商品的原 EGO 空间。", ego_space=resume)
        raise Halt("EGO_SETUP_REQUIRED", "EGO 无法建立商品自动化空间，请检查桌面连接。")
    session = int(space.group(1))
    if page_data is None:
        raise Halt("EGO_PAGE_FAILED", "EGO 商品页未能读取，请在原空间核实页面后续采。", ego_space=session)
    data = json.loads(page_data)
    if data["challenge"]:
        raise Halt("BROWSER_USER_ACTION", "请在 EGO 原空间完成登录或验证，再继续采集。", ego_space=session)
    return data, session


def close_ego(exe, space):
    script = f"const task = await taskSpace({space}); await task.finish({{keep: []}});"
    return run([exe, "nodejs", "-e", script], 12, browser=True).returncode == 0


def chrome_result(exe, major, session, command, *args, timeout=8):
    argv = [exe, "browser"]
    if major == 1:
        argv += [session, command, *args]
    else:
        argv += [command, *args, "--session", session]
    result = run(argv, timeout, browser=True)
    if result.returncode:
        raise Halt("OPENCLI_COMMAND_FAILED", f"OpenCLI {command} 未成功。")
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return None
    if isinstance(data, dict) and "ok" in data:
        if data["ok"] is not True:
            raise Halt("OPENCLI_COMMAND_FAILED", f"OpenCLI {command} 未成功。")
        return data.get("data")
    return data


def capture_chrome(exe, url, asin, resume=None):
    ver = run([exe, "--version"], 6, browser=True)
    match = re.search(r"\b([12])\.\d+\.\d+\b", ver.stdout)
    if ver.returncode or not match:
        raise Halt("OPENCLI_SETUP_REQUIRED", "无法识别 OpenCLI 会话参数版本。")
    major = int(match.group(1))
    session = resume or "ipr-product-" + uuid.uuid4().hex
    src = DOM_SCRIPT.read_text(encoding="utf-8")
    if not resume:
        try:
            chrome_result(exe, major, session, "open", url, timeout=11)
        except (subprocess.TimeoutExpired, Halt):
            # Chrome may already have navigated. Do not issue another navigation.
            pass
    deadline = time.monotonic() + 24
    while time.monotonic() < deadline:
        try:
            tabs = chrome_result(exe, major, session, "tab", "list", timeout=5) or []
            matches = [tab for tab in tabs if canonical_asin(tab.get("url", "")) == asin]
            if len(matches) > 1:
                raise Halt("CHROME_TAB_AMBIGUOUS", "商品会话内有多个同 ASIN 标签。", chrome_session=session)
            if matches:
                current = matches[0]
            elif len(tabs) == 1 and re.match(r"^https://www\.amazon\.com/(?:ap/signin|errors/validateCaptcha)", tabs[0].get("url", "")):
                raise Halt("BROWSER_USER_ACTION", "请在 Chrome 原标签完成登录或验证后继续。", chrome_session=session)
            elif len(tabs) == 1 and canonical_asin(tabs[0].get("url", "")):
                raise Halt("BROWSER_ASIN_MISMATCH", "原 Chrome 标签跳转到了不同 ASIN。", chrome_session=session)
            else:
                time.sleep(0.7)
                continue
            data = chrome_result(exe, major, session, "eval", "--tab", current["page"], src, timeout=6)
            if data and data.get("challenge"):
                raise Halt("BROWSER_USER_ACTION", "请在 Chrome 原标签完成登录或验证后继续。", chrome_session=session)
            if data and data.get("title"):
                return data, session, major
        except subprocess.TimeoutExpired:
            pass
        except Halt as exc:
            if exc.code != "OPENCLI_COMMAND_FAILED":
                raise
        time.sleep(0.7)
    raise Halt("CHROME_PAGE_FAILED", "无法在原 Chrome 会话确认商品页。请检查网络、跳转或扩展状态。",
               chrome_session=session)


def browser_capture(url, asin, args):
    ego = shutil.which("ego-browser")
    chrome = chrome_installed()
    opencli = shutil.which("opencli")
    ego_error = None
    if args.ego_space and not ego:
        raise Halt("EGO_SETUP_REQUIRED", "找不到原 EGO 空间所需的 CLI。")
    if ego and not args.chrome_session:
        try:
            data, space = capture_ego(ego, url, args.ego_space)
        except Halt as exc:
            if exc.code != "EGO_SETUP_REQUIRED" or args.ego_space:
                raise
            ego_error = exc
        else:
            return data, "ego", space, lambda: close_ego(ego, space)
    if opencli and chrome_bridge(opencli):
        data, session, major = capture_chrome(opencli, url, asin, args.chrome_session)
        return data, "chrome_opencli", session, lambda: chrome_result(opencli, major, session, "close") is not False
    if chrome or args.chrome_session:
        raise Halt("OPENCLI_SETUP_REQUIRED", "检测到 Chrome，请启动 Chrome 并连接 OpenCLI Browser Bridge。")
    if ego_error:
        raise ego_error
    if ego_installed():
        raise Halt("EGO_SETUP_REQUIRED", "检测到 EGO，请配置可用的 ego-browser 命令。")
    return None


def trusted_image(url):
    parsed = urllib.parse.urlsplit(url)
    return (parsed.scheme == "https" and parsed.netloc in IMAGE_HOSTS
            and not parsed.query and not parsed.fragment and bool(parsed.path))


class ImageRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not trusted_image(newurl):
            raise Halt("IMAGE_HOST_INVALID", "主图跳转到了不受信任的地址。")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_main(url, directory):
    if not url or not trusted_image(url):
        return None
    opener = urllib.request.build_opener(ImageRedirect())
    try:
        with opener.open(url, timeout=12) as reply:
            image = reply.read(IMAGE_LIMIT + 1)
            kind = reply.headers.get_content_type()
    except (OSError, Halt):
        return None
    suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
              "image/gif": ".gif", "image/avif": ".avif"}.get(kind)
    if not suffix or not image or len(image) > IMAGE_LIMIT:
        return None
    path = directory / ("amazon-main" + suffix)
    path.write_bytes(image)
    return {"path": str(path), "role": "main", "source_rank": 0, "public_url": url}


def supplied_images(user, base):
    if user.get("image_folder"):
        directory = base / user["image_folder"]
        images = [p for p in directory.iterdir() if not p.is_symlink() and p.is_file()
                  and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif"}]
        images.sort(key=lambda p: [int(part) if part.isdigit() else part
                                  for part in re.split(r"(\d+)", p.name.lower())])
        return [{"path": str(p), "role": "main" if index == 0 else "product_detail", "source_rank": index}
                for index, p in enumerate(images)]
    return [{**image, "path": str(base / image["path"])} for image in user.get("images", [])]


def freeze(args, output, asin, data, provider):
    final_url = data.get("origin", "") + data.get("pathname", "")
    if canonical_asin(final_url) != asin or data.get("selected_asin") != asin:
        raise Halt("BROWSER_ASIN_MISMATCH", "页面地址或选中的子 ASIN 与请求不一致。")
    if not data.get("title"):
        raise Halt("BROWSER_PRODUCT_INCOMPLETE", "页面商品标题缺失。")
    user = json_file(args.product_json) if args.product_json else {}
    base = Path(args.product_json).absolute().parent if args.product_json else Path.cwd()
    product = {key: str(data.get(key) or "")[:limit] for key, limit in FIELD_LIMITS.items()}
    product["bullet_points"] = [value[:3000] for value in data.get("bullet_points", [])]
    product["materials"] = [value[:500] for value in data.get("materials", [])]
    product.update({key: value for key, value in user.get("product", {}).items() if value})
    images = supplied_images(user, base)
    if not product["long_description"] or not product["bullet_points"]:
        raise Halt("BROWSER_PRODUCT_INCOMPLETE", "需要真实的商品描述和至少一条卖点。")
    with tempfile.TemporaryDirectory(prefix=".ipr-browser-", dir=output.parent) as temporary:
        root = Path(temporary)
        main = download_main(data.get("main_image", ""), root)
        if main:
            images = [main, *[{**img, "role": "product_detail"} if img["role"] == "main" else img for img in images]]
        if not any(image["role"] == "main" for image in images):
            raise Halt("BROWSER_MAIN_IMAGE_MISSING", "无法下载可信页面主图，请补充可核对的本地主图。")
        source = {key: user[key] for key in ("screening_tier", "jurisdictions", "feishu_record_id",
                                          "feature_inventory", "provenance_declarations") if key in user}
        source.update(schema_version="0.1", input_mode="manual_detail", marketplace="US", asin=asin,
                      product_url=final_url, product=product, images=images)
        info = root / "product.json"
        write_json(info, source)
        staged = root / "task"
        cli_call(args, "collect-product", "--product-json", info, "--task-id", args.task_id,
                 "--output-dir", staged)
        facts = json_file(staged / "02_product_facts.json")
        frozen = next(image for image in facts["images"] if image["role"] == "main")
        evidence = {key: value for key, value in data.items() if key in FIELD_LIMITS or key in ("materials", "bullet_points")}
        browser_url = data.get("main_image") or ""
        capture = {
            "schema_version": "0.1", "provider": provider, "task_id": args.task_id, "marketplace": "US",
            "requested_asin": asin, "selected_asin": data["selected_asin"], "product_url": final_url,
            "captured_at": now(), "product": evidence, "main_image": frozen["path"],
            "main_sha256": frozen["sha256"], "main_source": "amazon_page" if main else "user",
            "amazon_image_url": browser_url if trusted_image(browser_url) else "",
        }
        write_json(staged / CAPTURE_REF, capture)
        if output.exists() or output.is_symlink():
            raise Halt("OUTPUT_EXISTS", "任务目录已存在，不能覆盖。")
        staged.rename(output)


def collection(args):
    output = Path(args.output_dir).absolute()
    if output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise Halt("OUTPUT_INVALID", "请选择技能包外的、尚不存在的任务目录。")
    skill = Path(__file__).resolve().parents[2]
    if skill in (output.resolve(), *output.resolve().parents):
        raise Halt("OUTPUT_INVALID", "任务目录必须位于技能包外。")
    flags = (["--product-json", args.product_json] if args.product_json else
             ["--product-url", args.product_url] if args.product_url else ["--asin", args.asin, "--marketplace", "US"])
    route = cli_call(args, "inspect-input", *flags, "--input-mode", "asin_lookup")
    lookup = route.get("seller_lookup") or {}
    asin = lookup.get("asin", "")
    if lookup.get("marketplace") != "US" or not ASIN_PATTERN.fullmatch(asin):
        raise Halt("US_ASIN_REQUIRED", "只接受一个有效的美国站 ASIN 或商品链接。")
    url = f"https://www.amazon.com/dp/{asin}"
    picked = browser_capture(url, asin, args)
    if not picked:
        data = cli_call(args, "collect-product", *flags, "--input-mode", "asin_lookup",
                        "--config", args.config, "--task-id", args.task_id, "--output-dir", output, timeout=120)
        return {"route": "sellersprite", "task_dir": str(output), "collection": data}
    data, provider, session, close = picked
    try:
        freeze(args, output, asin, data, provider)
    except Halt as exc:
        exc.context["ego_space" if provider == "ego" else "chrome_session"] = session
        raise
    try:
        clean = close()
    except (OSError, subprocess.TimeoutExpired, Halt):
        clean = False
    return {"route": provider, "task_dir": str(output), "capture": CAPTURE_REF, "session_closed": clean}


def timestamp(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def browser_bindings(args):
    task = Path(args.task_dir).resolve()
    product_path = task / "02_product_facts.json"
    cli_call(args, "validate-product", "--input", product_path)
    facts = json_file(product_path)
    browser = json_file(task / CAPTURE_REF)
    if (facts.get("input_mode") != "manual_detail" or not facts.get("search_identity")
            or browser.get("provider") not in {"ego", "chrome_opencli"}
            or browser.get("task_id") != facts["task_id"] or facts["marketplace"] != browser.get("marketplace")
            or facts["marketplace"] != "US"
            or not ASIN_PATTERN.fullmatch(facts.get("asin") or "")
            or not facts["asin"] == browser.get("requested_asin") == browser.get("selected_asin")
            or canonical_asin(browser.get("product_url", "")) != facts["asin"]):
        raise Halt("BROWSER_CORROBORATION_BINDING_INVALID", "浏览器资料、ASIN 或检索标识与任务事实不匹配。")
    image = next(item for item in facts["images"] if item["role"] == "main")
    path = task / image["path"]
    if (image["path"] != browser["main_image"] or image["sha256"] != browser["main_sha256"]
            or task not in path.resolve().parents or path.is_symlink() or not path.is_file()
            or path.stat().st_size > IMAGE_LIMIT or sha_file(path) != image["sha256"]):
        raise Halt("BROWSER_CORROBORATION_IMAGE_INVALID", "主图与采集记录或冻结摘要不一致。")
    binding = {
        "schema_version": "0.1", "task_id": facts["task_id"], "product_facts_digest": facts["digest"],
        "capture_sha256": sha_file(task / CAPTURE_REF), "main_image_sha256": image["sha256"],
    }
    refs = {name: set(anchors) for name, anchors in REVIEW_REFS.items()}
    refs["main_image_consistency"].add(image["path"])
    return task, facts, browser, binding, refs


def review_context(args):
    _, _, _, binding, refs = browser_bindings(args)
    return {"review": {
        **binding, "reviewer": {"type": "agent", "id": ""}, "reviewed_at": now(),
        "checks": [{"name": name, "outcome": "unknown", "evidence_refs": sorted(anchors), "rationale": ""}
                   for name, anchors in refs.items()],
        "decision": "needs_user_action", "rationale": "",
    }}


def init_browser_task(args):
    task, facts, browser, binding, refs = browser_bindings(args)
    try:
        review = json_file(args.review)
    except (FileNotFoundError, ValueError) as exc:
        raise Halt("BROWSER_CORROBORATION_REVIEW_INVALID", "缺少有效的三项浏览器核对记录。") from exc
    reviewer = review["reviewer"]
    if (any(review.get(key) != value for key, value in binding.items())
            or timestamp(review["reviewed_at"]) < max(timestamp(facts["frozen_at"]), timestamp(browser["captured_at"]))
            or reviewer["type"] not in {"agent", "user", "reviewer"} or not reviewer["id"].strip()
            or not review["rationale"].strip()):
        raise Halt("BROWSER_CORROBORATION_REVIEW_INVALID", "核对记录未绑定到当前的任务、商品资料和主图。")
    checks = {check["name"]: check for check in review["checks"]}
    if len(review["checks"]) != 3 or set(checks) != set(REVIEW_REFS):
        raise Halt("BROWSER_CORROBORATION_REVIEW_INVALID", "核对必须覆盖原来的三项检查。")
    for name, anchors in refs.items():
        check = checks[name]
        if not anchors <= set(check["evidence_refs"]) or not check["rationale"].strip():
            raise Halt("BROWSER_CORROBORATION_REVIEW_INVALID", "每项核对必须写明对应证据与判断依据。")
        if check["outcome"] != "corroborated":
            raise Halt("BROWSER_CORROBORATION_NOT_ACCEPTED", "图文核对有未通过项，须先解决冲突或缺失。")
    if review["decision"] != "accepted":
        raise Halt("BROWSER_CORROBORATION_NOT_ACCEPTED", "图文核对未接受，不能初始化任务。")
    record = {**review, "provider": browser["provider"], "selected_asin": browser["selected_asin"]}
    receipt = task / REVIEW_REF
    lock_path = task / "input-metadata/.browser-init.lock"
    try:
        lock = lock_path.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise Halt("BROWSER_INIT_LOCKED", "浏览器任务初始化正在进行或上次中断，请核实原进程。") from exc
    try:
        with lock:
            lock.write(str(os.getpid()))
        if (json_file(task / "02_product_facts.json").get("digest") != binding["product_facts_digest"]
                or sha_file(task / CAPTURE_REF) != binding["capture_sha256"]
                or sha_file(task / browser["main_image"]) != binding["main_image_sha256"]):
            raise Halt("BROWSER_CORROBORATION_BINDING_INVALID", "核对后商品资料或主图发生变化，请重新核对。")
        if receipt.exists() and json_file(receipt) != record:
            raise Halt("BROWSER_CORROBORATION_ALREADY_RECORDED", "已有不同的接受记录，不能覆盖。")
        if not receipt.exists():
            if (task / "01_task.json").exists():
                raise Halt("BROWSER_TASK_ALREADY_INITIALIZED", "任务已绕过浏览器核对入口初始化。")
            write_json(receipt, record)
        task_file = task / "01_task.json"
        if task_file.is_file():
            if json_file(task_file).get("product_facts_digest") != binding["product_facts_digest"]:
                raise Halt("BROWSER_TASK_BINDING_INVALID", "已初始化任务与浏览器核对摘要不一致。")
            return {"route": browser["provider"], "corroboration": REVIEW_REF, "already_initialized": True}
        result = cli_call(args, "init-task", "--task-dir", task)
        if json_file(task_file).get("product_facts_digest") != binding["product_facts_digest"]:
            raise Halt("BROWSER_TASK_BINDING_INVALID", "已初始化任务与浏览器核对摘要不一致。")
        return {"route": browser["provider"], "corroboration": REVIEW_REF, "task": result}
    finally:
        lock_path.unlink(missing_ok=True)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="operation", required=True)
    collect = sub.add_parser("collect")
    collect.add_argument("--cli", required=True, type=lambda v: str(Path(v).resolve()))
    collect.add_argument("--config", required=True, type=lambda v: str(Path(v).resolve()))
    collect.add_argument("--task-id", required=True)
    collect.add_argument("--output-dir", required=True)
    inputs = collect.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--asin")
    inputs.add_argument("--product-url")
    inputs.add_argument("--product-json")
    resume = collect.add_mutually_exclusive_group()
    resume.add_argument("--ego-space", type=int)
    resume.add_argument("--chrome-session")
    context = sub.add_parser("review-context")
    init = sub.add_parser("init-browser-task")
    for command in (context, init):
        command.add_argument("--cli", required=True, type=lambda v: str(Path(v).resolve()))
        command.add_argument("--task-dir", required=True)
    init.add_argument("--review", required=True)
    return p


def main():
    args = parser().parse_args()
    try:
        if getattr(args, "chrome_session", None) and not re.fullmatch(r"ipr-product-[0-9a-f]{32}", args.chrome_session):
            raise Halt("CHROME_SESSION_INVALID", "只能续采本流程创建的 Chrome 会话。")
        operation = {"collect": collection, "review-context": review_context,
                     "init-browser-task": init_browser_task}[args.operation]
        result = operation(args)
        print(json.dumps({"status": "ready", **result}, ensure_ascii=True))
    except Halt as exc:
        print(json.dumps({"status": "blocked", "reason_code": exc.code, "message": str(exc), **exc.context},
                         ensure_ascii=True))
        return 1
    except (OSError, ValueError, TypeError, KeyError, StopIteration, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "blocked", "reason_code": "LOCAL_OPERATION_FAILED",
                          "message": f"本地输入、任务文件或命令未完成（{type(exc).__name__}）。"}, ensure_ascii=True))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
