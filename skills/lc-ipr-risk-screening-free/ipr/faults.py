"""测试开关：故意制造故障，用来演练"出了错也要出报告"（开发计划第 4 阶段）。平时不设，设了的那一单结果不能当真。
环境变量 LC_IPR_FAULT，几项用逗号隔开：
  quota:compare     名字以 compare 开头的 AI 会话一律当作"额度用尽"
  fail:serper.dev   网址里带 serper.dev 的请求一律当作"连不上"
  wrapup:90         本次运行到 90 秒就收口（平时是 6 分钟）
报告和屏幕上都会写明这一单开着测试开关。"""
from __future__ import annotations

import os
import time

ENV = "LC_IPR_FAULT"


def active() -> dict:
    found = {"quota": [], "fail": [], "wrapup": None}
    for item in (os.environ.get(ENV) or "").split(","):
        kind, _, value = item.strip().partition(":")
        value = value.strip()
        if kind in ("quota", "fail") and value:
            found[kind].append(value)
        elif kind == "wrapup" and value.isascii() and value.isdigit():
            found["wrapup"] = int(value)
    return found


def describe() -> str:
    """开着哪些测试开关；一个都没开返回空字符串。"""
    found = active()
    parts = ["把名字以 %s 开头的 AI 会话当作额度用尽" % name for name in found["quota"]]
    parts += ["把发往 %s 的请求当作连不上" % name for name in found["fail"]]
    if found["wrapup"] is not None:
        parts.append("本次运行到 %d 秒就收口" % found["wrapup"])
    return "；".join(parts)


def ai_quota(key: str) -> str:
    """这个会话要不要模拟额度用尽；要的话返回一个"恢复时间"，不要返回空字符串。"""
    if any(key.startswith(prefix) for prefix in active()["quota"]):
        return time.strftime("%H:%M", time.localtime(time.time() + 300)) + "（测试开关模拟的）"
    return ""


def url_blocked(url: str) -> bool:
    return any(fragment in str(url) for fragment in active()["fail"])


def wrapup_seconds():
    return active()["wrapup"]
