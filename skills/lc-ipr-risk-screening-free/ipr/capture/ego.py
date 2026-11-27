"""用 EGO 浏览器（ego lite）采集 Amazon 商品页：把脚本通过标准输入交给 `ego-browser nodejs`，不需要 AI 参与。"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from .. import config
from ..outcome import NoProduct, StepFailed, WaitingUser

HERE = Path(__file__).resolve().parent
MARK = "IPR_RESULT "
TIMEOUT_SECONDS = 330  # 比脚本里各段等待（打开 45、等标题 15、每张图两种下法各 20）加起来还长
BLOCKED_TEXT = {
    "captcha": "Amazon 要求输入验证码。请在 EGO 浏览器里打开的那个页面上完成验证，然后把同一条命令再跑一次。",
    "login": "Amazon 要求登录。请在 EGO 浏览器里打开的那个页面上登录，然后把同一条命令再跑一次。",
}


def available() -> str:
    """装了就返回 ego-browser 命令的路径，没装返回空字符串。"""
    return shutil.which("ego-browser") or ""


def build_script(url: str, image_dir: Path, label: str, space_id=None) -> str:
    """把参数填进脚本模板。参数一律按 JSON（纯 ASCII 转义）写进去，链接里夹带任何字符都只是字符串，变不成代码。"""
    template = (HERE / "ego_script.mjs").read_text(encoding="utf-8")
    extract = (HERE / "extract.js").read_text(encoding="utf-8")
    asin = label if re.fullmatch(r"[A-Z0-9]{10}", label or "") else ""
    payload = {"url": url, "imageDir": str(Path(image_dir).resolve()), "label": label, "asin": asin,
               "spaceId": space_id if isinstance(space_id, int) else None,
               "maxImages": config.PRODUCT_IMAGES_MAX, "timeout": 45000}
    # 先填取数函数（模板里只有一处），再填参数：这样参数里即使出现占位符字样也不会被二次替换。
    return template.replace("__EXTRACT__", json.dumps(extract), 1).replace("__INPUT__", json.dumps(payload), 1)


def parse_result(*streams: str) -> dict:
    """结果是一行以 IPR_RESULT 开头的 JSON。EGO 把脚本的输出写在标准错误里，所以两个通道都找。"""
    for line in reversed("\n".join(s or "" for s in streams).splitlines()):
        if line.startswith(MARK):
            try:
                value = json.loads(line[len(MARK):])
            except ValueError:
                break
            if isinstance(value, dict):
                return value
    raise StepFailed("EGO 浏览器没有返回采集结果")


def capture(url: str, task_dir: Path, label: str, space_id=None, runner=None) -> dict:
    """返回 {"product": 页面取到的资料, "images": [{file, url}], "space_id": …}。
    验证码或登录抛 WaitingUser（带 space_id，续跑时接着用同一个工作区）；商品不存在抛 NoProduct；其他问题抛 StepFailed。"""
    runner = runner or subprocess.run
    binary = available()
    if not binary:
        raise StepFailed("没有装 EGO 浏览器")
    script = build_script(url, Path(task_dir) / "images", label, space_id)
    try:
        result = runner([binary, "nodejs"], input=script, text=True, encoding="utf-8", errors="replace",
                        capture_output=True, timeout=TIMEOUT_SECONDS, env=config.child_env())
    except subprocess.TimeoutExpired:
        raise StepFailed("EGO 浏览器超过 %d 秒没有采完" % TIMEOUT_SECONDS)
    except OSError as exc:
        raise StepFailed("EGO 浏览器没能启动（%s）" % type(exc).__name__)
    try:
        data = parse_result(result.stdout, result.stderr)
    except StepFailed:
        tail = ((result.stderr or "").strip().splitlines() or (result.stdout or "").strip().splitlines() or [""])[-1]
        raise StepFailed("EGO 浏览器没有返回采集结果（%s）" % tail[:200])
    status = data.get("status")
    if status == "blocked":
        raise WaitingUser(BLOCKED_TEXT.get(data.get("kind"), BLOCKED_TEXT["captcha"]), space_id=data.get("spaceId"), browser="ego")
    if status == "missing":
        raise NoProduct("没拿到商品资料：这个商品页不存在或已下架。可以改用资料入口：自己提供一张产品图和一句描述。")
    if status == "no_title":
        raise StepFailed("打开的页面上没有找到商品标题（页面标题：%s）" % str(data.get("pageTitle", ""))[:80])
    if status != "ok":
        raise StepFailed("EGO 浏览器采集出错：%s" % str(data.get("message", "原因不明"))[:200])
    return {"product": data.get("product") or {}, "images": data.get("images") or [], "space_id": data.get("spaceId"),
            "failed_images": data.get("failedImages") or []}
