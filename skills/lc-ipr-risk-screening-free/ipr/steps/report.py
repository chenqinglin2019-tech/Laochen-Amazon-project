"""出报告（R-008）：把当前状态套模板写成报告。中途停下的情况也照样出。"""
from __future__ import annotations

from html import escape

from .. import config
from ..report import render


def run(ctx) -> None:
    task = ctx.task
    html = render.render(task, ctx.usage.summary(), getattr(ctx, "result", {}) or {})
    path = task.dir / config.REPORT_FILE
    path.write_text(config.mask_secrets(html), encoding="utf-8")
    ctx.say("  报告：%s" % path)


def write_fallback(ctx, error: str) -> None:
    """正式报告生成失败时的最简版：至少说清总评、各类权利的等级和出了什么错。"""
    task = ctx.task
    overall = task["overall"] or {}
    shown = {"not_applicable": "不适用", "not_searched": "未检索", "nothing": "无可查项"}
    rows = "".join("<li>%s：%s　%s</li>" % (escape(str(r.get("name", ""))), escape(shown.get(r.get("state"), r.get("risk") or "—")),
                                          escape(str(r.get("basis", "")))) for r in task["rights_summary"] or [])
    html = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>侵权风险排查报告（简版）</title></head><body>'
            "<h1>侵权风险排查报告（简版）</h1><p>正式报告生成时出错：%s。下面是已有的结论，完整数据在任务目录的 %s 里。</p>"
            "<p>总风险等级：%s　置信度：%s</p><p>%s</p><ul>%s</ul></body></html>") % (
        escape(error), config.STATE_FILE, escape(str(overall.get("risk", config.RISK_PENDING))),
        escape(str(overall.get("confidence") or "—")), escape(str(overall.get("advice", ""))), rows)
    (task.dir / config.REPORT_FILE).write_text(config.mask_secrets(html), encoding="utf-8")
