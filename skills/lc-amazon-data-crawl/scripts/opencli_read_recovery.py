"""Persisted, bounded recovery for explicitly read-only OpenCLI operations."""
from __future__ import annotations

import datetime as dt
import time

from opencli_bridge import BridgeTransientError
from run_outcome import CrawlStop, needs_human
from safety_control import SafetyPausedError


class BridgeReadRecoveryExhausted(CrawlStop):
    def __init__(self):
        super().__init__(
            "OpenCLI 原标签连续读取故障已达到 30 分钟，断点及待确认操作已保留。",
            exit_code=20,
            next_action="报告连接故障；修复后从原断点恢复。不要跳过当前来源、重复加载或重复导出。")


class ReadRecovery:
    KEY = "bridge_read_recovery"
    DELAYS = (2, 2, 30, 60, 120)
    LIMIT = 30 * 60

    def __init__(self, bridge, data, save, safety, *, now=time.time, sleep=time.sleep):
        self.bridge, self.data, self.save, self.safety = bridge, data, save, safety
        self.now, self.sleep = now, sleep
        self.blocked_seconds = 0.0
        self.generation = 0
        # An explicitly restarted process may check an expired outage once,
        # without obtaining another 30-minute retry budget.
        self.resume_probe = bool(data.get(self.KEY) and data[self.KEY]["deadline"] <= now())

    def _check_pause(self):
        pause = getattr(self.safety, "_load_pause", lambda: None)()
        if isinstance(pause, dict) and pause.get("active") and not (
            getattr(self.safety, "_review_mode", False) is True and pause.get("review_attempt_pending")
        ):
            raise SafetyPausedError("本机存在风险暂停，停止原标签自动读取恢复。",
                                    resume_at=str(pause.get("not_before", "")))

    def read(self, operation, callback):
        """Only snapshot / target listing / download status callbacks belong here.

        Never pass a write, bind or a whole business stage: their replies can
        be lost after execution. Other successful reads cannot clear an outage
        belonging to this operation (important on process restart).
        """
        started = self.now()
        pending = self.data.get(self.KEY)
        interrupted = bool(pending and pending["operation"] == operation)
        probe = bool(pending and self.resume_probe)
        try:
            while True:
                self._check_pause()
                if pending:
                    if (pending["target"], pending["session"]) != (self.bridge.target, self.bridge.session):
                        raise needs_human("读取恢复记录与原工作标签不一致；未自动重新绑定。")
                    until = min(pending["next_attempt_at"], pending["deadline"])
                    while self.now() < until:
                        interrupted = True
                        self._check_pause()
                        self.safety.heartbeat("bridge_retry_wait",
                            until=dt.datetime.fromtimestamp(until).astimezone().isoformat(),
                            detail=f"原标签只读恢复，第 {pending['attempt']} 次重试；{pending['code']}")
                        self.sleep(min(2, until - self.now()))
                    if self.now() >= pending["deadline"] and not probe:
                        raise BridgeReadRecoveryExhausted()
                try:
                    self._check_pause()
                    if pending:
                        if (pending["target"], pending["session"]) != (self.bridge.target, self.bridge.session):
                            raise needs_human("等待期间原工作标签绑定发生变化，停止读取恢复。")
                        # Bound even an in-flight CLI call by the remaining outage budget.
                        remaining = 35 if probe else pending["deadline"] - self.now()
                        self.bridge.read_deadline = time.monotonic() + remaining
                        self.bridge.validate_target()
                        if self.now() >= pending["deadline"] and not probe:
                            raise BridgeReadRecoveryExhausted()
                    result = callback()
                except BridgeTransientError as exc:
                    interrupted = True
                    self.generation += 1
                    if probe:
                        self.resume_probe = False
                        raise BridgeReadRecoveryExhausted() from exc
                    if not pending:
                        pending = dict(target=self.bridge.target, session=self.bridge.session,
                                       started_at=started, deadline=started + self.LIMIT, attempt=0,
                                       operation=operation)
                    attempt = pending["attempt"]
                    delay = self.DELAYS[attempt] if attempt < len(self.DELAYS) else 300
                    pending.update(attempt=attempt + 1, code=exc.bridge_code,
                                   next_attempt_at=min(self.now() + delay, pending["deadline"]))
                    self.data[self.KEY] = pending
                    self.save()
                    print(f"OpenCLI 读取暂时失败（{exc.bridge_code}），保存断点后等待 {delay} 秒复核原标签。", flush=True)
                    continue
                finally:
                    self.bridge.read_deadline = None
                if pending and pending["operation"] == operation:
                    self.data.pop(self.KEY, None)
                    self.resume_probe = False
                    self.save()
                    print("OpenCLI 原标签读取已恢复，继续原断点。", flush=True)
                return result
        finally:
            if interrupted:
                self.blocked_seconds += max(0, self.now() - started)
                # Reset stability even when resuming a persisted outage.
                self.generation += 1
