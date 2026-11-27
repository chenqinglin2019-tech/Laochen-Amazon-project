"""一个任务只有一个状态文件 state.json：每一步做完就把结果写进去，续跑时从它接着做。"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from . import config


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class TaskState:
    def __init__(self, task_dir: Path, data: dict):
        self.dir = Path(task_dir)
        self.data = data
        self.current_step = ""

    # ---- 建立与读取 ----
    @classmethod
    def create(cls, task_dir: Path, entry: dict, country: str, demo: str = "") -> "TaskState":
        task_dir = Path(task_dir)
        task_dir.mkdir(parents=True, exist_ok=True)
        for sub in ("raw", "images", "rights", "sessions"):
            (task_dir / sub).mkdir(exist_ok=True)
        data = {
            "version": config.VERSION,
            "created_at": now_iso(),
            "country": country,
            "entry": entry,
            "demo": demo,  # 非空表示用录好的数据演示，报告里会写明
            "product": {},
            "understanding": {},
            "searches": [],
            "search_notes": [],
            "lens": [],
            "enforcement": [],
            "candidates": [],
            "findings": [],
            "rights_summary": [],
            "overall": {},
            "incomplete": [],
            "steps": {name: {"status": "pending"} for name in config.STEPS},
            "outcome": {},
        }
        state = cls(task_dir, data)
        state.save()
        return state

    @classmethod
    def load(cls, task_dir: Path) -> "TaskState":
        path = Path(task_dir) / config.STATE_FILE
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):  # 早先版本建的任务没有这几项
            for key in ("search_notes", "lens", "enforcement"):
                data.setdefault(key, [])
        return cls(Path(task_dir), data)

    @staticmethod
    def exists(task_dir: Path) -> bool:
        return (Path(task_dir) / config.STATE_FILE).is_file()

    def save(self) -> None:
        """先写临时文件再改名，中途断电也不会留下半个文件。"""
        path = self.dir / config.STATE_FILE
        tmp = self.dir / (config.STATE_FILE + ".tmp")
        tmp.write_text(config.mask_secrets(json.dumps(self.data, ensure_ascii=False, indent=1)), encoding="utf-8")
        os.replace(tmp, path)

    # ---- 取值的简写 ----
    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value

    @property
    def country(self) -> str:
        return self.data["country"]

    # ---- 步骤状态 ----
    def step(self, name: str) -> dict:
        return self.data["steps"][name]

    def step_done(self, name: str) -> bool:
        return self.step(name).get("status") == "done"

    def begin(self, name: str) -> float:
        self.current_step = name
        self.data["steps"][name] = {"status": "running", "started_at": now_iso()}
        self.save()
        return time.monotonic()

    def finish(self, name: str, started: float, status: str = "done", note: str = "") -> None:
        step = self.step(name)
        step["status"] = status
        step["seconds"] = round(time.monotonic() - started, 1)
        if note:
            step["note"] = note
        self.save()

    # ---- "没查完"清单 ----
    def add_incomplete(self, what: str, why: str, right_type: str = "") -> None:
        item = {"what": what, "why": why, "step": self.current_step}
        if right_type:
            item["right_type"] = right_type
        if item not in self.data["incomplete"]:
            self.data["incomplete"].append(item)

    def candidate(self, cand_id: str):
        for cand in self.data["candidates"]:
            if cand["id"] == cand_id:
                return cand
        return None
