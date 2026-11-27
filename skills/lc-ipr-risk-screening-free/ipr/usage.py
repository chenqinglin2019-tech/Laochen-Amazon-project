"""用时和 token 计量（需求 R-010）：每步用时、每个 AI 会话的用量，写进 usage.json 和报告末尾。"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import config, faults


class Usage:
    def __init__(self, task_dir: Path):
        self.path = Path(task_dir) / config.USAGE_FILE
        if self.path.is_file():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
            if not (isinstance(self.data, dict) and isinstance(self.data.get("steps"), dict) and isinstance(self.data.get("sessions"), list)
                    and isinstance(self.data.get("source_calls"), dict)):
                raise ValueError("用量文件的内容不对")
        else:
            self.data = {"active_seconds": 0.0, "steps": {}, "sessions": [], "source_calls": {}}
        self._run_started = time.monotonic()
        self._base_seconds = float(self.data.get("active_seconds") or 0.0)
        self._run_first = len(self.data["sessions"])  # 这一次运行开的会话从这里数起
        self.lock = None  # run.py 开跑时挂上：用来心跳，和看这台电脑上还有没有别的单在跑

    def tick(self) -> None:
        """每到一步、每开完一个会话都碰一下：报个心跳；发现同时还有别的单在跑，就把这一单的时间线放宽（放宽了就不再收回）。"""
        if self.lock is None:
            return
        self.lock.beat()
        if not self.data.get("shared") and self.lock.others() > 0:
            self.data["shared"] = True

    def limits(self) -> dict:
        limits = dict(config.BUDGET_SHARED if self.data.get("shared") else config.BUDGET)
        if faults.wrapup_seconds() is not None:  # 测试开关
            limits["wrapup_seconds"] = faults.wrapup_seconds()
        return limits

    # ---- 记录 ----
    def add_step(self, name: str, seconds: float) -> None:
        self.data["steps"][name] = round(self.data["steps"].get(name, 0.0) + seconds, 1)
        self.save()

    def add_session(self, step: str, key: str, model: str, seconds: float, usage: dict = None, ok: bool = True) -> None:
        """usage 为 None 表示拿不到用量数字：记"未知"，不估算。"""
        record = {"step": step, "key": key, "model": model, "seconds": round(seconds, 1), "ok": ok}
        if usage is None:
            record["tokens_known"] = False
        else:
            record["tokens_known"] = True
            record["input_tokens"] = int(usage.get("input_tokens") or 0)
            record["cached_input_tokens"] = int(usage.get("cached_input_tokens") or 0)
            record["output_tokens"] = int(usage.get("output_tokens") or 0)
        self.data["sessions"].append(record)
        self.tick()
        self.save()

    def add_source_call(self, source: str, count: int = 1) -> None:
        self.data["source_calls"][source] = self.data["source_calls"].get(source, 0) + count
        self.save()

    # ---- 汇总 ----
    def seconds(self) -> float:
        """本任务累计的机器运行时间（续跑时接着上次的算）。"""
        return self._base_seconds + (time.monotonic() - self._run_started)

    def tokens(self) -> int:
        return sum(s.get("input_tokens", 0) + s.get("output_tokens", 0) for s in self.data["sessions"])

    def run_seconds(self) -> float:
        """这一次运行到现在用了多久（续跑不把上一次的算进来）。"""
        return time.monotonic() - self._run_started

    def run_tokens(self) -> int:
        return sum(s.get("input_tokens", 0) + s.get("output_tokens", 0) for s in self.data["sessions"][self._run_first:])

    def unknown_sessions(self) -> int:
        return sum(1 for s in self.data["sessions"] if not s.get("tokens_known"))

    def should_wrap_up(self) -> bool:
        """这一次运行到了 6 分钟或 40 万 token（同时还有别的单在跑时是 9 分钟）：不再开新的深查，收口出报告。
        按本次运行算：续跑的时候不把上一次花掉的算进来，不然一续跑就收口，永远做不完。"""
        self.tick()
        limits = self.limits()
        return self.run_seconds() >= limits["wrapup_seconds"] or self.run_tokens() >= limits["wrapup_tokens"]

    def summary(self) -> dict:
        sessions = self.data["sessions"]
        return {
            "seconds": round(self.seconds(), 1),
            "sessions": len(sessions),
            "tokens": self.tokens(),
            "input_tokens": sum(s.get("input_tokens", 0) for s in sessions),
            "output_tokens": sum(s.get("output_tokens", 0) for s in sessions),
            "unknown_sessions": self.unknown_sessions(),
            "steps": dict(self.data["steps"]),
            "source_calls": dict(self.data["source_calls"]),
            "run_seconds": round(self.run_seconds(), 1),
            "run_tokens": self.run_tokens(),
            "resumed": self._base_seconds > 0,
            "shared": bool(self.data.get("shared")),
            "limit_seconds": self.limits()["limit_seconds"],
            "limit_tokens": self.limits()["limit_tokens"],
            "within_limit": self.seconds() <= self.limits()["limit_seconds"] and self.tokens() <= self.limits()["limit_tokens"],
        }

    def save(self) -> None:
        self.data["active_seconds"] = round(self.seconds(), 1)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(config.mask_secrets(json.dumps(self.data, ensure_ascii=False, indent=1)), encoding="utf-8")
        os.replace(tmp, self.path)
