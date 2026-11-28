"""流水线：按固定顺序走各步。任何一步失败只有三种去向——步骤内重试、记进"没查完"继续走、明确停下说人话。
只要拿到了商品资料，最后一定定级并出报告（R-009）。"""
from __future__ import annotations

import time

from . import config, faults, outcome
from .state import now_iso
from .steps import RUNNERS
from .steps import report as report_step

WORK_STEPS = [s for s in config.STEPS if s not in ("grade", "report")]


def _clear_products(task, name: str, partial: bool) -> None:
    """清掉某一步留下的结果。partial=True 表示这一步自己要重做，但已经做成的那部分留着（比过的不再比）。"""
    if name == "intake":
        task["product"] = {}
        task["competitors"] = []
    elif name == "understand":
        task["understanding"] = {}
    elif name == "search":
        task["searches"], task["candidates"] = [], []
        task["lens"], task["enforcement"], task["search_notes"], task["manual_marks"] = [], [], [], []
        for old in (task.dir / "raw").glob("search-S*.json"):  # 检索整段重来、编号从 S1 起：上次的留档清掉，免得和这次的对不上
            try:
                old.unlink()
            except OSError:
                pass
    elif name == "screen":
        for cand in task["candidates"]:
            if not partial or (cand.get("screen") or {}).get("retry"):  # 只重做没做成的：别的决定留着，不再问一遍 AI
                cand.pop("screen", None)
    elif name == "compare":
        task["findings"] = [f for f in task["findings"] if partial and f.get("status") == "compared"]
    elif name == "recheck":
        # 复核没做完就停下的，续跑时把没成的再试一次（上限按这一次重新数）。
        for finding in task["findings"]:
            old = finding.get("recheck") or {}
            if not (partial and old.get("status") == "done"):
                if old.get("status") == "done" and old.get("first_risk") in config.RISK_ORDER:
                    finding["risk"] = old["first_risk"]  # 上次复核把等级抬高过：重做前还原，免得把抬高后的当成"第一次"
                finding.pop("recheck", None)


def _prepare_resume(task) -> None:
    """续跑前：从第一个没做完的步骤起，它和它后面的步骤都重新做，免得上游重做了、下游还留着旧结果。"""
    first = next((i for i, name in enumerate(WORK_STEPS) if not task.step_done(name)), None)
    if first is None:
        return
    for position, name in enumerate(WORK_STEPS[first:]):
        # 从初筛或比对续跑时候选还是那一批：已经比过的记录、已经做完的复核都还有效，留着不重做
        # （比对那一步会丢掉不再入选的；复核只补还没复核的那几件）
        keep = position == 0 or (WORK_STEPS[first] in ("screen", "compare") and name in ("compare", "recheck"))
        _clear_products(task, name, partial=keep)
        task.data["steps"][name] = {"status": "pending"}
    redo = set(WORK_STEPS[first:]) | {"grade", "report", ""}
    task["incomplete"] = [i for i in task["incomplete"] if i.get("step") not in redo]


def run(ctx) -> dict:
    task, usage = ctx.task, ctx.usage
    result = {"kind": outcome.DONE, "message": ""}
    _prepare_resume(task)
    stop_ai = False
    halted = False
    test_faults = faults.describe()
    if test_faults:  # 测试开关开着：屏幕和报告上都写明，免得把演练的结果当真
        ctx.say("【测试开关】%s。这一单的结果不能当真。" % test_faults)

    for index, name in enumerate(WORK_STEPS, 1):
        if task.step_done(name):
            continue
        title = config.STEP_NAMES[name]
        if halted or (stop_ai and name in config.AI_STEPS):
            task.current_step = name
            task.step(name).update(status="skipped", note="前面已停下，这一步没有做")
            if task["product"]:
                task.add_incomplete(title, "前面已停下（%s），这一步没有做" % (result["message"] or "原因见上"))
            continue
        ctx.say("[%d/%d] %s" % (index, len(WORK_STEPS), title))
        usage.tick()  # 心跳；顺便看看这台电脑上是不是还有别的单在跑
        started = task.begin(name)
        clock = time.monotonic()
        try:
            RUNNERS[name](ctx)
            task.finish(name, started)
        except outcome.QuotaExhausted as stop:
            task.finish(name, started, "stopped", stop.message)
            task.add_incomplete(title, "AI 额度用尽，这一步没有做完")
            result = {"kind": stop.kind, "message": stop.message, "resume_at": config.redact(stop.extra.get("resume_at", ""))}
            stop_ai = True
        except outcome.StopSignal as stop:
            task.finish(name, started, "stopped", stop.message)
            if task["product"]:
                task.add_incomplete(title, stop.message)
            if result["kind"] == outcome.DONE:  # 前面已经因为别的原因停下（比如额度用尽）时，保留那个原因
                result = {"kind": stop.kind, "message": stop.message}
            halted = True
        except outcome.StepFailed as failed:
            message = config.redact(failed.message, ctx.env)
            task.finish(name, started, "failed", message)
            task.add_incomplete(title, message)
            if result["kind"] == outcome.DONE:
                result = {"kind": outcome.ERROR_STOPPED, "message": "%s没有完成：%s" % (title, message)}
        except Exception as exc:  # 意料之外的错误：说清楚，带着已有结果出报告
            message = config.redact("%s: %s" % (type(exc).__name__, exc), ctx.env)
            task.finish(name, started, "failed", message)
            task.add_incomplete(title, "程序出错：%s" % message)
            if result["kind"] == outcome.DONE:
                result = {"kind": outcome.ERROR_STOPPED, "message": "%s时程序出错（%s）" % (title, message)}
            halted = True
        finally:
            usage.add_step(name, time.monotonic() - clock)

    result["finished_at"] = now_iso()
    result["task_dir"] = str(task.dir)
    if test_faults:
        result["test_faults"] = test_faults
    if task["product"]:  # 没拿到商品资料是唯一不出报告的情况
        ctx.result = result
        task["overall"], task["rights_summary"] = {}, []  # 不让上一次的结论混进这一次
        for name in ("grade", "report"):
            started = task.begin(name)
            try:
                RUNNERS[name](ctx)
                task.finish(name, started)
            except Exception as exc:  # 定级或出报告自己出错：也要留下一份能打开的东西
                message = config.redact("%s: %s" % (type(exc).__name__, exc), ctx.env)
                task.finish(name, started, "failed", message)
                note = "%s时程序出错（%s）" % (config.STEP_NAMES[name], message)
                if result["kind"] == outcome.DONE:
                    result["kind"] = outcome.ERROR_STOPPED
                result["message"] = (result["message"] + "；另外" + note) if result["message"] else note
                if name == "report":
                    report_step.write_fallback(ctx, message)
        result["report"] = str(task.dir / config.REPORT_FILE)
    result["usage"] = usage.summary()
    task["outcome"] = result
    task.save()
    usage.save()
    return result
