"""一单结束只有四种结果，以及让流程提前收场的几种信号。
所有信号的说明文字在产生时就过一遍脱敏，之后写到哪里都不会带出 key。"""
from __future__ import annotations

from . import config

DONE = "done"                    # 完成，报告已出
QUOTA_STOPPED = "quota_stopped"  # AI 额度用尽已停，报告已出（标明未完成）
ERROR_STOPPED = "error_stopped"  # 出错已停，能出报告就已出
WAITING_USER = "waiting_user"    # 采集遇到验证码或登录墙，等用户处理后续跑

EXIT_CODES = {DONE: 0, ERROR_STOPPED: 1, QUOTA_STOPPED: 3, WAITING_USER: 4}  # 2 留给"命令行参数写错"

TITLES = {
    DONE: "完成",
    QUOTA_STOPPED: "AI 额度用尽，已停",
    ERROR_STOPPED: "出错",
    WAITING_USER: "等你处理",
}


class StopSignal(Exception):
    """流程要提前收场时抛出；message 是给用户看的一句人话。"""

    kind = ERROR_STOPPED

    def __init__(self, message: str, **extra):
        message = config.redact(message)
        super().__init__(message)
        self.message = message
        self.extra = extra


class NoProduct(StopSignal):
    """没拿到商品资料：唯一不出报告的情况。"""

    kind = ERROR_STOPPED


class WaitingUser(StopSignal):
    """要用户在浏览器里处理验证码或登录，处理完同一条命令续跑。"""

    kind = WAITING_USER


class QuotaExhausted(StopSignal):
    """AI 额度用尽：停掉后面所有 AI 步骤，用已有结果出报告。extra 里可带 resume_at。"""

    kind = QUOTA_STOPPED


class NotReady(StopSignal):
    """这一步的真实实现还没做到（开发阶段用），不冒充已完成。"""

    kind = ERROR_STOPPED


class StepFailed(Exception):
    """某一步没成，但流程可以带着"没查完"继续往下走。"""

    def __init__(self, message: str):
        message = config.redact(message)
        super().__init__(message)
        self.message = message
