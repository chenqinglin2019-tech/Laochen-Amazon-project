"""没装 EGO 时用本机 Chrome 采集：tools/chrome_capture.mjs（Node + playwright-core）打开一个看得见的 Chrome 窗口。"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .. import config
from ..outcome import NoProduct, StepFailed, WaitingUser
from .ego import BLOCKED_TEXT, parse_result

HERE = Path(__file__).resolve().parent
SCRIPT = config.SKILL_DIR / "tools" / "chrome_capture.mjs"
WAIT_FOR_USER_SECONDS = 120
TIMEOUT_SECONDS = 45 + WAIT_FOR_USER_SECONDS + 15 + 6 * 20 + 60  # 比脚本里各段等待加起来还长


def available() -> str:
    """Chrome 采集要有 node，而且 tools/ 里装好了 playwright-core。能用返回 node 的路径，否则返回空字符串。"""
    node = shutil.which("node") or ""
    if not node or not (config.SKILL_DIR / "tools" / "node_modules" / "playwright-core").is_dir():
        return ""
    return node


def capture(url: str, task_dir: Path, label: str, runner=None) -> dict:
    runner = runner or subprocess.run
    node = available()
    if not node:
        raise StepFailed("Chrome 采集用不了：没有 node，或者 tools/ 里没装 playwright-core（安装脚本会装）")
    payload = {"url": url, "imageDir": str((Path(task_dir) / "images").resolve()), "maxImages": config.PRODUCT_IMAGES_MAX,
               "profileDir": str(Path.home() / ".lc-ipr" / "chrome-profile"), "extract": (HERE / "extract.js").read_text(encoding="utf-8"),
               "timeout": 45000, "waitForUserSeconds": WAIT_FOR_USER_SECONDS}
    try:
        result = runner([node, str(SCRIPT)], input=json.dumps(payload, ensure_ascii=False), text=True, encoding="utf-8",
                        errors="replace", capture_output=True, timeout=TIMEOUT_SECONDS, env=config.child_env())
    except subprocess.TimeoutExpired:
        raise StepFailed("Chrome 超过 %d 秒没有采完" % TIMEOUT_SECONDS)
    except OSError as exc:
        raise StepFailed("Chrome 采集没能启动（%s）" % type(exc).__name__)
    try:
        data = parse_result(result.stdout, result.stderr)
    except StepFailed:
        tail = ((result.stderr or "").strip().splitlines() or [""])[-1]
        raise StepFailed("Chrome 没有返回采集结果（%s）" % tail[:200])
    status = data.get("status")
    if status == "blocked":
        text = BLOCKED_TEXT.get(data.get("kind"), BLOCKED_TEXT["captcha"]).replace("在 EGO 浏览器里打开的那个页面上", "在续跑时再次打开的 Chrome 窗口里")
        raise WaitingUser(text, browser="chrome")
    if status == "missing":
        raise NoProduct("没拿到商品资料：这个商品页不存在或已下架。可以改用资料入口：自己提供一张产品图和一句描述。")
    if status == "no_title":
        raise StepFailed("打开的页面上没有找到商品标题（页面标题：%s）" % str(data.get("pageTitle", ""))[:80])
    if status != "ok":
        raise StepFailed("Chrome 采集出错：%s" % str(data.get("message", "原因不明"))[:200])
    return {"product": data.get("product") or {}, "images": data.get("images") or [], "space_id": None,
            "failed_images": data.get("failedImages") or []}
