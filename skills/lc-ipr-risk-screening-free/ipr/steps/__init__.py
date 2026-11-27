"""流水线的每一步一个函数 run(ctx)。做完把结果写进 ctx.task，由流水线负责存盘和计时。"""
from __future__ import annotations

from . import intake, understand, search, screen, compare, recheck, grade, report

RUNNERS = {
    "intake": intake.run,
    "understand": understand.run,
    "search": search.run,
    "screen": screen.run,
    "compare": compare.run,
    "recheck": recheck.run,
    "grade": grade.run,
    "report": report.run,
}
