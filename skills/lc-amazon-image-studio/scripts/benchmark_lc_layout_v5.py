"""Compare a pinned legacy engine and this engine on local project layouts only."""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import time

from PIL import Image

import lc_layout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--jobs", nargs="+", default=["05_visible_details", "08_a_plus_visual", "10_a_plus_visible_details"])
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a fresh benchmark output directory; existing results are never overwritten")
    args.output.mkdir(parents=True)
    spec = importlib.util.spec_from_file_location("legacy_lc_layout", args.legacy / "scripts/lc_layout.py")
    legacy = importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    jobs = [copy.deepcopy(job) for job in manifest["jobs"] if job["id"] in args.jobs]
    if {job["id"] for job in jobs} != set(args.jobs):
        parser.error("Every selected job must exist in the manifest")
    report = {"model_calls": 0, "scope": "local layout preparation/render/preview only", "engines": {}, "pixel_identical": {}}
    for name, engine in (("legacy", legacy), ("v5", lc_layout)):
        root = args.output / name;root.mkdir()
        for job in jobs:
            resources = [job["layout_input"]] + [item["image"] for item in job.get("layout", {}).get("items", []) if item.get("image")]
            for resource in resources:
                destination = root / resource;destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(args.manifest.parent / resource, destination)
        started = time.perf_counter()
        results = engine.render_batch(manifest, root, jobs)
        elapsed = time.perf_counter() - started
        report["engines"][name] = {"batch_seconds": round(elapsed, 4), "passed": all(result["passed"] for result in results.values()),
                                  "jobs": {jid: {"passed": item["passed"], "runtime": item["runtime"]} for jid, item in results.items()}}
        for job in jobs:
            if not results[job["id"]]["passed"]:
                report["engines"][name]["jobs"][job["id"]]["failed_checks"] = [check for check in results[job["id"]]["checks"] if not check["passed"]]
    for job in jobs:
        relative = Path("review/layouts") / (job["id"] + ".png")
        with Image.open(args.output / "legacy" / relative) as old, Image.open(args.output / "v5" / relative) as new:
            report["pixel_identical"][job["id"]] = old.size == new.size and old.convert("RGBA").tobytes() == new.convert("RGBA").tobytes()
    report["speedup"] = round(report["engines"]["legacy"]["batch_seconds"] / report["engines"]["v5"]["batch_seconds"], 3)
    report["saved_percent"] = round((1 - report["engines"]["v5"]["batch_seconds"] / report["engines"]["legacy"]["batch_seconds"]) * 100, 1)
    fonts, _ = lc_layout._font_payload(["An Easter Accent", "Black with a checked bow."], version=2, headline_family="serif", subset=True)
    report["english_font_payload_bytes"] = sum(len(face["uri"]) for face in fonts)
    report["all_pixel_identical"] = all(report["pixel_identical"].values())
    report["first_image_encoding"] = {}
    for name, engine in (("legacy", legacy), ("v5", lc_layout)):
        if hasattr(engine, "_raster_uri_cached"):
            engine._raster_uri_cached.cache_clear()
        source = args.output / name / jobs[0]["layout_input"]
        started = time.perf_counter();uri = engine._raster_uri(source)
        report["first_image_encoding"][name] = {"seconds": round(time.perf_counter() - started, 6), "data_uri_bytes": len(uri), "source_bytes": source.stat().st_size}
    (args.output / "benchmark.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "engines"}, ensure_ascii=False, indent=2))
    return 0 if report["all_pixel_identical"] and all(engine["passed"] for engine in report["engines"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
