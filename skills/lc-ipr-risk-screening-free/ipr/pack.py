"""把一单打成可分享的运行包（--pack）：任务目录里的状态、检索留档、AI 会话的提示和回答、用量、报告和图片，外加一份说明。
打包前核对：包里不能出现这台电脑上填着的任何 key 或 token。"""
from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path

from . import config

SKIP_NAMES = {".running"}
TEXT_SUFFIXES = {".json", ".jsonl", ".txt", ".html", ".md", ".csv"}


def secrets_of(env: dict) -> list:
    return [str(v) for v in (env or {}).values() if isinstance(v, str) and len(v.strip()) >= 8]


def readme(task_dir: Path, state: dict) -> str:
    overall = state.get("overall") or {}
    entry = state.get("entry") or {}
    lines = ["侵权风险快查 运行包", "",
             "版本：%s" % state.get("version", ""),
             "打包时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M"),
             "目的国：%s" % config.COUNTRIES.get(state.get("country", ""), {}).get("name", state.get("country", "")),
             "入口：%s" % (entry.get("url") or "资料入口"),
             "总评：%s%s" % (overall.get("risk", "—"), "（仅就已查部分）" if overall.get("partial") else ""),
             "",
             "里面有什么：",
             "  state.json      这一单的全部状态：产品理解、每条检索、候选和去向、比对记录、各类权利的结论、没查完的",
             "  raw/            每条检索的留档：检索式、状态、命中数、返回的号码清单",
             "  sessions/       每个 AI 会话的提示（prompt.txt）、回答（answer.json）和过程（events.jsonl）",
             "  usage.json      用时和 token",
             "  report.html     报告（图片内嵌，离线可打开）",
             "  images/ rights/ 产品图和对方附图",
             "",
             "不含：key、token、账号配置。"]
    return "\n".join(lines) + "\n"


def pack(task_dir, env: dict = None, out: Path = None) -> Path:
    """返回压缩包路径。任务目录不对、或者发现包里会带上 key 时抛 ValueError（里面是给用户看的话）。"""
    task_dir = Path(task_dir).expanduser().resolve()
    state_file = task_dir / config.STATE_FILE
    if not state_file.is_file():
        raise ValueError("%s 不是任务目录（里面没有 %s）" % (task_dir, config.STATE_FILE))
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError("任务目录里的 %s 读不了" % config.STATE_FILE)
    secrets = secrets_of(env)
    files = [p for p in sorted(task_dir.rglob("*")) if p.is_file() and p.name not in SKIP_NAMES and not p.is_symlink()]
    for path in files:
        if path.suffix.lower() in TEXT_SUFFIXES and secrets:
            text = path.read_text(encoding="utf-8", errors="replace")
            if any(s in text for s in secrets):
                raise ValueError("没有打包：%s 里出现了这台电脑上填着的 key 或 token。请先删掉那一处再打包" % path.relative_to(task_dir))
    out = Path(out) if out else task_dir.with_name(task_dir.name + "-pack.zip")
    prefix = task_dir.name
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("%s/运行包说明.txt" % prefix, readme(task_dir, state))
        for path in files:
            archive.write(path, "%s/%s" % (prefix, path.relative_to(task_dir).as_posix()))
    return out
