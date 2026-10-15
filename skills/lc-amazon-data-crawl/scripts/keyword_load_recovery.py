"""Keyword-only reconciliation of a single load; never replay an unknown write."""
from __future__ import annotations

import hashlib
import json
import uuid

from opencli_bridge import BridgeTransientError
from run_outcome import needs_human, retry_later


def error_fingerprint(snapshot):
    message = snapshot.get("keyword_load_error") or ""
    return hashlib.sha256(message.encode()).hexdigest() if message else ""


def keyword_busy(snapshot):
    return snapshot.get("keyword_busy", snapshot.get("busy", False))


class KeywordLoadRecovery:
    LIMIT = 600

    def __init__(self, crawler):
        self.c = crawler
        self.active = crawler.state.data["current_task"]
        self.record = self.active.get("keyword_load")

    def save(self):
        self.c.state.save()

    def new_record(self, before, retries=0):
        return dict(before_count=before, retries=retries, elapsed=0.0,
                    cycle_started_at=self.c.now(),
                    document_id=self.c.bridge.document_id, target=self.c.bridge.target,
                    attempt_id=uuid.uuid4().hex, status="unknown", baseline_error="")

    def start(self, before):
        self.record = self.new_record(before)
        self.record["status"] = "not_dispatched"
        self.active.update(load_pending=True, keyword_load=self.record)
        self.save()
        self.dispatch()
        return self.observe()

    def resume(self):
        if not self.record:
            # Old checkpoints contain no evidence about whether the click was sent.
            self.record = self.new_record(self.active["plugin_count"])
            self.record["attempt_id"] = ""
            self.active["keyword_load"] = self.record
            self.save()
        if (self.record["document_id"] != self.c.bridge.document_id or
                self.record["target"] != self.c.bridge.target):
            raise needs_human("关键词待确认加载的原页面身份已变化，未重新点击。")
        # Charge interrupted in-flight commands once, not the entire downtime.
        # A recorded Bridge outage is explicitly unobservable time.
        for key in ("read_started_at", "dispatch_started_at"):
            started = self.record.pop(key, None)
            if started is not None and not self.c.state.data.get("bridge_read_recovery"):
                self.record["elapsed"] += min(35, max(0, self.c.now() - started))
        self.save()
        if self.record["status"] == "not_dispatched":
            self.dispatch()
        return self.observe()

    def dispatch(self):
        # Same two reads and scheduler call as PluginCrawler.remote; no extra
        # browser call on the healthy path. The DOM performs the final guard.
        self.c.snapshot()
        self.c.safety.before_remote_action("plugin:load")
        current = self.c.snapshot()
        self.record.update(status="dispatching", baseline_error=error_fingerprint(current),
                           error_cleared=False, dispatch_started_at=self.c.now())
        self.save()  # A crash from this point onward must reconcile, not replay.
        started = self.c.observation_now()
        try:
            result = self.c.bridge.panel("load", keyword=True,
                expectedCount=self.record["before_count"], loadAttempt=self.record["attempt_id"])
            self.record["status"] = "not_clicked" if result.get("not_clicked") else "sent"
        except BridgeTransientError:
            self.record["status"] = "unknown"
        finally:
            self.record["elapsed"] += max(0, self.c.observation_now() - started)
            self.record.pop("dispatch_started_at", None)
            self.save()

    def read(self):
        started = self.c.observation_now()
        self.record["read_started_at"] = self.c.now()
        self.save()
        try:
            return self.c.snapshot()
        finally:
            self.record["elapsed"] += max(0, self.c.observation_now() - started)
            self.record.pop("read_started_at", None)
            self.save()

    def wait_observation(self, seconds):
        # Reserve observation time before sleeping; abrupt termination cannot
        # refund the wait on every restart. Bridge outages are excluded by read().
        self.record["elapsed"] += seconds
        self.save()
        phase = "plugin_wait"
        detail = ("关键词异常加载只读观察" if self.record["elapsed"] >= 180 else "等待插件计数与可观察字段稳定")
        self.c.wait(seconds, phase, detail)

    def failure_proven(self, snap):
        if self.record["status"] == "not_clicked":
            return True
        fresh_error = error_fingerprint(snap)
        return bool(self.record["attempt_id"] and
                    snap.get("keyword_load_attempt") == self.record["attempt_id"] and
                    fresh_error and (fresh_error != self.record["baseline_error"] or self.record.get("error_cleared")))

    def retry(self):
        schedule = [60] if self.c.cfg["operation_mode"] == "supervised" else [120, 300]
        index = self.record["retries"]
        if index >= len(schedule):
            raise retry_later("关键词明确失败的重试次数已用完，保留当前来源与断点。")
        if self.record["status"] != "retry_wait":
            self.record.update(status="retry_wait", retry_at=self.c.now() + schedule[index])
            self.save()
        self.c.wait(max(0, self.record["retry_at"] - self.c.now()), "retry_wait", "关键词明确失败后的原规则冷却")
        # Persist the consumed retry before dispatch. A lost reply never permits
        # this attempt to be dispatched again after restart.
        cycle_started = self.record.get("cycle_started_at", self.c.now())
        self.record = self.new_record(self.record["before_count"], index + 1)
        self.record["cycle_started_at"] = cycle_started
        self.record["status"] = "not_dispatched"
        self.active["keyword_load"] = self.record
        self.save()
        self.dispatch()

    def observe(self):
        previous, stable_since = None, self.c.observation_now()
        # After an exhausted checkpoint, only an already-arrived result may
        # receive one short stability check; no new 600-second window is issued.
        expired_grace = None
        while True:
            generation = self.c.read_recovery.generation
            snap = self.read()
            now = self.c.observation_now()
            if generation != self.c.read_recovery.generation:
                previous, stable_since = None, now
            count = snap.get("count")
            self.record["observed_count"] = count
            if not error_fingerprint(snap):
                self.record["error_cleared"] = True
            before = self.record["before_count"]
            if count is not None and count < before:
                raise needs_human("关键词插件条数回退，停止以免混写；待确认操作已保留。")
            busy = keyword_busy(snap)
            signature = (count, busy, snap.get("more"), snap.get("amazon_no_results"),
                         tuple(row.get("text", "") for row in snap.get("rows", [])))
            if signature != previous:
                previous, stable_since = signature, now
            progressed = bool(snap.get("panel") and count is not None and count > before and not busy)
            if progressed and now - stable_since >= 10:
                # run_task atomically records the successful load and clears the
                # pending record; don't create a separate success/count crash gap.
                print("keyword_load_confirmed " + json.dumps({
                    "before": before, "after": count, "retries": self.record["retries"],
                    "observation_seconds": round(self.record["elapsed"], 3),
                    "cycle_seconds": round(self.c.now() - self.record.get("cycle_started_at", self.c.now()), 3)
                }), flush=True)
                return snap
            if self.record["status"] == "retry_wait":
                if progressed:
                    pass  # A late response wins over an outstanding retry.
                elif not busy and snap.get("more") and count == before:
                    self.retry()
                    previous, stable_since = None, self.c.observation_now()
                    continue
            elif not busy and count == before and snap.get("panel") and snap.get("more") and self.failure_proven(snap):
                self.retry()
                previous, stable_since = None, self.c.observation_now()
                continue
            if self.record["elapsed"] >= self.LIMIT:
                if not progressed:
                    raise retry_later("关键词加载观察已达 10 分钟，结果仍未确认；未标记完成或重复点击。")
                if expired_grace is None:
                    expired_grace = now + 10
                if now >= expired_grace:
                    raise retry_later("关键词迟到结果仍未稳定，保留断点；未重新获得加载预算。")
            self.wait_observation(2)
