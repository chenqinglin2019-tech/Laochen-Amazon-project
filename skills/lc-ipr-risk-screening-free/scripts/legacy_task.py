"""Recognise a task created before the current grading and workflow policy (best-estimate-risk-v2).

Policies are frozen into task.json at creation, so a task created with an earlier skill version keeps its
original rules even when it is continued with this one: no one-command pipeline, no program triage defaults,
no core dossier or comparison host, no review-packet slimming, no 极高 rule and no report evidence block.
Continuing such a task usually costs more than a new run (its final-review inputs can exceed the host limit).
This module only reports the fact; it never changes a task.
"""
from __future__ import annotations

CURRENT = "best-estimate-risk-v2"
CODE = "LEGACY_TASK_POLICY"


def notice(task: dict | None) -> dict | None:
    """A notice for a task created before best-estimate-risk-v2, else None."""
    if not isinstance(task, dict) or task.get("best_estimate_revision") == CURRENT:
        return None
    url = ((task.get("request") or {}).get("url")) or "<商品链接>"
    countries = ",".join(task.get("target_jurisdictions") or []) or "US"
    return {
        "code": CODE,
        "task_policy": task.get("best_estimate_revision") or "none",
        "current_policy": CURRENT,
        "created_at": task.get("created_at"),
        "message": ("这是用旧版技能创建的任务（评级标记 " + (task.get("best_estimate_revision") or "无") + "）。"
                    "新版的一键流水线、程序分流、核心专利自动比较、终审材料瘦身、极高规则和报告证据区块都不会对它生效，"
                    "续跑通常比新建更慢，终审输入还可能超出上限。除非用户明确要求续跑这个旧任务，"
                    "请先告诉用户这一点，并用一键流水线在新目录新建任务。"),
        "recommended_command": ("python -X utf8 scripts/run_pipeline.py --task-dir <新目录> --url '" + url
                                + "' --jurisdictions " + countries
                                + " --all-sources --use-serper-existing-balance"
                                + " --guard-session-id \"$CODEX_THREAD_ID\" --chief '<主审>'"),
    }
