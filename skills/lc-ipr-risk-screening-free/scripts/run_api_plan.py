#!/usr/bin/env python3
"""Execute resumable API-only search-plan entries with bounded concurrency."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from common import ensure_object, load_json, load_skill_config


API_PROVIDERS = {
    "serpapi_google_patents", "serper_patents", "serper_web", "serper_images",
    "epo_ops", "signa", "rapidapi_uspto_trademark", "euipo_trademark", "euipo_design",
}
TERMINAL = {"success", "no_result", "not_applicable"}


def flag(command: list[str], name: str, value: Any) -> None:
    if value not in (None, "", []):
        command.extend([name, str(value)])


def command_for(scripts: Path, task_dir: Path, provider: str, item: dict[str, Any]) -> list[str]:
    q = str(item.get("q") or "")
    if provider == "serpapi_google_patents":
        command = [sys.executable, str(scripts / "serpapi_patents_client.py"), "--task-dir", str(task_dir), "--query", q]
        for key in ("jurisdiction", "country", "status", "type", "assignee", "inventor", "before", "after"):
            flag(command, f"--{key.replace('_', '-')}", item.get(key))
        return command
    if provider.startswith("serper_"):
        operation = {"serper_patents": "patents", "serper_web": "search", "serper_images": "images"}[provider]
        command = [sys.executable, str(scripts / "serper_client.py"), operation, "--task-dir", str(task_dir), "--query", q]
        flag(command, "--jurisdiction", item.get("jurisdiction"))
        flag(command, "--num", item.get("num"))
        return command
    if provider == "epo_ops":
        command = [sys.executable, str(scripts / "epo_ops_client.py"), "--task-dir", str(task_dir), "--operation", "search", "--query", q]
        flag(command, "--jurisdiction", item.get("jurisdiction"))
        flag(command, "--range", item.get("range"))
        return command
    if provider == "signa":
        command = [sys.executable, str(scripts / "signa_client.py"), "--task-dir", str(task_dir), "--query", q]
        flag(command, "--jurisdiction", item.get("jurisdiction"))
        flag(command, "--office", item.get("office"))
        return command
    if provider == "rapidapi_uspto_trademark":
        command = [sys.executable, str(scripts / "rapidapi_uspto_trademark_client.py"), "--task-dir", str(task_dir), "--query", q]
        flag(command, "--search-type", item.get("search_type"))
        return command
    if provider in {"euipo_trademark", "euipo_design"}:
        product = "trademark" if provider.endswith("trademark") else "design"
        command = [sys.executable, str(scripts / "euipo_client.py"), product, "--task-dir", str(task_dir), "--query", q]
        flag(command, "--page", item.get("page"))
        flag(command, "--size", item.get("size"))
        return command
    raise ValueError(f"Unsupported API provider: {provider}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run API entries from search-plan.json with resume support.")
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--wave", choices=("1", "2", "all"), default="1")
    parser.add_argument("--include-optional", action="store_true")
    parser.add_argument("--max-workers", type=int, default=0)
    args = parser.parse_args()
    task_dir = args.task_dir.resolve()
    plan = ensure_object(load_json(task_dir / "search-plan.json"), "search-plan.json")
    evidence = ensure_object(load_json(task_dir / "evidence.json"), "evidence.json")
    completed = {
        str(run.get("query_id")) for run in evidence.get("source_runs", [])
        if run.get("status") in TERMINAL and run.get("query_id")
    }
    pending: list[tuple[str, dict[str, Any]]] = []
    for provider, entries in plan.get("queries", {}).items():
        if provider not in API_PROVIDERS:
            continue
        for item in entries:
            if not isinstance(item, dict) or item.get("query_id") in completed:
                continue
            if not item.get("required", True) and not args.include_optional:
                continue
            if args.wave != "all" and int(item.get("wave", 1)) != int(args.wave):
                continue
            pending.append((provider, item))

    scripts = Path(__file__).resolve().parent
    config = load_skill_config()
    maximum = int(config.get("performance", {}).get("max_api_concurrency", 3))
    workers = max(1, min(args.max_workers or maximum, maximum, len(pending) or 1))
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(subprocess.run, command_for(scripts, task_dir, provider, item), capture_output=True, text=True, check=False): (provider, item)
            for provider, item in pending
        }
        for future in as_completed(futures):
            provider, item = futures[future]
            result = future.result()
            results.append({
                "provider": provider, "query_id": item.get("query_id"), "q": item.get("q"),
                "returncode": result.returncode, "status": result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "failed",
                "stderr": result.stderr.strip()[-500:],
            })
    print(json.dumps({"workers": workers, "scheduled": len(pending), "results": results}, ensure_ascii=False, indent=2))
    if any(item["returncode"] != 0 for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
