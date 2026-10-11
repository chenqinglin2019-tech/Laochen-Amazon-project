#!/usr/bin/env python3
"""Maintainer benchmark: agent tool calls and local CLI time for a full V8 set (fake image model).

Counts what the agent actually does: shell commands (auth, verify, studio.py), the one
plan.json write, image calls and extra image views. No model, network or real auth;
the auth gate is bypassed and counted as one call.

    python scripts/benchmark_studio_agent.py [--out runs.json]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from studio_test_support import basic_plan, fake_model_image, isolated_env, product_photo  # noqa: E402


class Agent:
    def __init__(self, env, base):
        self.env, self.base = env, base
        self.calls = {"auth": 1, "verify": 0, "cli": 0, "plan_write": 0, "image": 0, "view": 0}
        self.cli_seconds = 0.0
        self.log = []

    def run(self, *args, kind="cli"):
        started = time.perf_counter()
        done = subprocess.run([sys.executable, "-X", "utf8", *map(str, args)], capture_output=True, text=True,
                              encoding="utf-8", env=self.env)
        elapsed = time.perf_counter() - started
        self.calls[kind] += 1
        self.cli_seconds += elapsed
        line = next((item for item in reversed(done.stdout.splitlines()) if item.startswith("{")), "{}")
        payload = json.loads(line)
        self.log.append({"command": str(args[1]) if len(args) > 1 else str(args[0]), "seconds": round(elapsed, 2),
                         "ok": payload.get("ok", payload.get("ready"))})
        return payload

    def studio(self, *args):
        return self.run(SCRIPTS / "studio.py", *args)

    def generate(self, reservation, cut=False, main=False):
        self.calls["image"] += 1
        width, height = map(int, reservation["size"].split("x"))
        path = self.base / f"{reservation['job']}-{reservation['attempt_id']}.png"
        if main:
            return fake_model_image(path, (width, height), backdrop=(255, 255, 255), product_box=(0.25, 0.12, 0.75, 0.88), text=False)
        box = (0.55, 0.02, 0.9, 0.98) if cut else (0.3, 0.2, 0.7, 0.85)
        return fake_model_image(path, (width, height), product_box=box)


def scenario(name, *, a_plus, lifestyle, cut_job=None, redo_job=None):
    with tempfile.TemporaryDirectory(prefix="lc-v8-bench-") as temp:
        base = Path(temp)
        env = isolated_env(base)
        agent = Agent(env, base)
        project = base / "proj"
        agent.run(SCRIPTS / "runtime_bootstrap.py", "verify", "--json", kind="verify")
        init = ["init", "--project-dir", project, "--project-id", name, "--marketplace", "US", "--language", "en",
                "--photos", product_photo(base / ("scene.jpg" if lifestyle else "front.jpg"), lifestyle=lifestyle)]
        if a_plus:
            init += ["--a-plus-modules", a_plus]
        created = agent.studio(*init)
        plan = basic_plan(created["catalog"], created["slots"])
        (project / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        agent.calls["plan_write"] += 1
        result = agent.studio("plan", "--project", project)
        cut_done, redo_done = set(), set()
        waves = 0
        while result.get("reservations") or result.get("retry_after_seconds"):
            if not result.get("reservations"):
                time.sleep(min(2, result["retry_after_seconds"] or 0))
                result = agent.studio("reserve", "--project", project)
                continue
            waves += 1
            items = []
            for reservation in result["reservations"]:
                job = reservation["job"]
                cut = job == cut_job and job not in cut_done
                cut_done.add(job)
                path = agent.generate(reservation, cut=cut, main=job == "01_main")
                items += ["--item", job, reservation["attempt_id"], path]
                if job == redo_job and job not in redo_done:
                    redo_done.add(job)
                    items += ["--redo", job, "headline misspelled"]
            result = agent.studio("ingest-batch", "--project", project, *items)
            if result.get("main_check"):
                agent.calls["view"] += 1
        delivered = agent.studio("deliver", "--project", project)
        total = sum(agent.calls.values())
        return {"scenario": name, "images": delivered.get("image_count"), "waves": waves, "calls": agent.calls,
                "total_calls": total, "local_cli_seconds": round(agent.cli_seconds, 1), "log": agent.log}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    runs = [scenario("listing7_photo_main", a_plus=None, lifestyle=False),
            scenario("set13_generated_main", a_plus="header:1464x600,feature,detail,lifestyle:1464x600,comparison,story",
                     lifestyle=True, cut_job="08_a_plus_header", redo_job="03_primary_use_case")]
    for run in runs:
        print(json.dumps({key: value for key, value in run.items() if key != "log"}, ensure_ascii=False))
    if args.out:
        Path(args.out).write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
