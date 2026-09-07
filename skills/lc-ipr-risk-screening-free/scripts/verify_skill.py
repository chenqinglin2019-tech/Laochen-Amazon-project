#!/usr/bin/env python3
"""One offline verification entry point; release mode requires browser layout QA.

No provider invocation is performed. Generated data is a synthetic local fixture,
kept under the requested output directory separately from business evidence.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent


def run_check(name, command, output, *, cwd=ROOT, env=None, timeout=180):
    started = time.monotonic()
    env = {**(env or os.environ), "LC_IPR_FREE_SEARCH_LEDGER_DIR": str(output / (name + "-test-ledger"))}
    try:
        process = subprocess.run(command, cwd=cwd, env=env, capture_output=True,
                                 text=True, timeout=timeout, check=False)
        text = process.stdout + "\n" + process.stderr
        code = process.returncode
    except subprocess.TimeoutExpired:
        text, code = "Verification command exceeded its bounded deadline.\n", 124
    # Logs are local test output, never a copy of the invoking process environment.
    (output / (name + ".log")).write_text(text)
    counts = {}
    for key in ("tests", "pass", "fail", "skipped"):
        match = re.search(r"^# " + key + r" (\d+)$", text, re.M)
        if match:
            counts[key] = int(match.group(1))
    match = re.search(r"Ran (\d+) tests? in", text)
    if match:
        counts["tests"] = int(match.group(1))
    result = {"name": name, "status": "passed" if code == 0 else "failed",
              "exit_code": code, "elapsed_seconds": round(time.monotonic() - started, 3),
              "counts": counts, "log": name + ".log"}
    if "SKIP report browser acceptance" in text:
        result["browser_acceptance_skipped"] = True
    print(name + ": " + result["status"], flush=True)
    return result


def generate_estimate_fixture(output, *, scenario=False):
    if scenario:
        from test_assessment_estimate_scenarios import scenario_fixture as fixture
    else:
        from test_assessment_estimate import fixture
    from common import now_iso, sha256_file
    from assessment_estimate import review_digest
    directory = output / ("scenario-fixture" if scenario else "estimate-fixture")
    directory.mkdir()
    values = fixture(directory)
    task, evidence, candidates, plan, ledger, first, second = values
    if scenario:
        from copy import deepcopy
        conditional = values[0]["assessment_scenarios"][1]
        for review in values[-2:]:
            review["assessments"][0]["risk"] = "中"
            row = deepcopy(review["assessments"][0])
            row.update(scenario_id=conditional["scenario_id"], scenario_sha256=conditional["scenario_sha256"], risk="极高")
            review["assessments"].append(row)
    # Release exercises the default core selector, not a presentation escape
    # hatch. These are explicitly synthetic local test assets, never source
    # receipts or business evidence. The old 25-image gallery remains covered
    # separately by test_report_estimate's explicit legacy-policy fixture.
    import struct
    import zlib
    def fixture_image(name, rgb):
        def chunk(kind, payload):
            return struct.pack('!I', len(payload)) + kind + payload + struct.pack('!I', zlib.crc32(kind + payload) & 0xffffffff)
        png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 12, 8, 8, 2, 0, 0, 0))
               + chunk(b'IDAT', zlib.compress((b'\x00' + bytes(rgb) * 12) * 8)) + chunk(b'IEND', b''))
        path = directory / name
        path.write_bytes(png)
        return {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}
    row = first["assessments"][0]
    visual_identity = {key: row[key] for key in ("candidate_id", "jurisdiction", "right_type")}
    visual_role = "registry_record" if scenario else "copyright_work"
    visual_source = {"kind": "rights_record", **visual_identity, "visual_role": visual_role,
        "source_url": "https://example.org/offline-release-fixture", "checked_at": now_iso(),
        "visual_reason": "离线合成权利图，仅测试候选绑定和报告渲染，不是业务证据。"}
    evidence["collections"]["release_visuals"] = [
        {**visual_source, "evidence_id": "EV-RELEASE-CORE", **fixture_image("rights-view.png", (25, 75, 115))},
        {**visual_source, "evidence_id": "EV-RELEASE-ZERO", "status": "no_result", **fixture_image("zero-results.png", (150, 160, 170))},
        {**visual_source, "evidence_id": "EV-RELEASE-FAIL", "status": "access_limited", **fixture_image("access-limited.png", (180, 80, 50))},
    ]
    for review in (first, second):
        for row in review["assessments"]:
            row["evidence_refs"].extend(["EV-RELEASE-CORE", "EV-RELEASE-ZERO", "EV-RELEASE-FAIL"])
        review["review_context"]["evidence_digest"] = review_digest(evidence, candidates, ledger, plan, task)
    for name, value in zip(("task", "evidence", "normalized-candidates", "search-plan",
                            "materiality-annotations", "first-review", "second-review"), values):
        (directory / (name + ".json")).write_text(json.dumps(value, ensure_ascii=False))
    main = values[0]["images"][0]
    figure = {"path": main["path"], "sha256": sha256_file(Path(main["path"])),
              "label": "离线合成测试图", "caption": "仅用于模板和原图哈希验收，不是业务证据。"}
    (directory / "presentation.json").write_text(json.dumps({
        "product_facts": {"main_visual": figure},
        "release_visual_fixture": {"schema": "CORE-VISUAL-RELEASE/1.0", "expected_core_refs": ["EV-RELEASE-CORE"],
            "excluded_refs": ["EV-RELEASE-ZERO", "EV-RELEASE-FAIL"], "scenario_isolation": scenario}}, ensure_ascii=False))
    return directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("fast", "release"), default="fast")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    # A new directory prevents a prior green manifest from hiding a failed run.
    if output.exists() and any(output.iterdir()):
        parser.error("Use a new or empty --output-dir; existing verification is read-only")
    output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.pop("REPORT_V2_HTML", None)
    env.pop("REPORT_ESTIMATE_HTML", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["LC_IPR_OFFLINE_TESTS"] = "1"
    env["LC_IPR_RELEASE_CHECK"] = "1" if args.mode == "release" else "0"
    results = []
    for directory in ("scripts", "tests"):
        results.append(run_check("python-" + directory,
            [sys.executable, "-m", "unittest", "discover", "-s", directory, "-p", "test_*.py"],
            output, env=env))
    if args.mode == "release":
        results.append(run_check("legacy-self-test", [sys.executable, "scripts/self_test.py"],
                                 output, env=env))
        if results[-1].get("browser_acceptance_skipped"):
            results[-1]["status"] = "incomplete"
        fixture = generate_estimate_fixture(output)
        for name, arguments in (
            ("estimate-finalize", ["finalize_assessment.py", "--task-dir", fixture,
                "--first-review", fixture / "first-review.json", "--second-review", fixture / "second-review.json"]),
            ("estimate-report", ["build_report.py", "--task-dir", fixture, "--report-content", fixture / "presentation.json"]),
            ("estimate-validate", ["validate_run.py", "--task-dir", fixture]),
        ):
            results.append(run_check(name, [sys.executable, str(ROOT / "scripts" / arguments[0]),
                                           *map(str, arguments[1:])], output, env=env))
            if results[-1]["status"] != "passed":
                break
        env["REPORT_ESTIMATE_HTML"] = str(fixture / "report.html")
        env["REPORT_SCREENSHOTS_DIR"] = str(output / "screenshots")
        scenario_fixture = generate_estimate_fixture(output, scenario=True)
        for name, arguments in (
            ("scenario-finalize", ["finalize_assessment.py", "--task-dir", scenario_fixture,
                "--first-review", scenario_fixture / "first-review.json", "--second-review", scenario_fixture / "second-review.json"]),
            ("scenario-report", ["build_report.py", "--task-dir", scenario_fixture, "--report-content", scenario_fixture / "presentation.json"]),
            ("scenario-validate", ["validate_run.py", "--task-dir", scenario_fixture]),
        ):
            results.append(run_check(name, [sys.executable, str(ROOT / "scripts" / arguments[0]),
                                           *map(str, arguments[1:])], output, env=env))
            if results[-1]["status"] != "passed":
                break
    node = shutil.which("node")
    if node:
        tests = sorted((ROOT / "tools/cdp").glob("*.test.mjs"))
        if args.mode == "release":
            # The old layout test already runs inside self_test with its own
            # generated legacy report; do not silently run it without an input.
            tests = [path for path in tests if path.name != "report-v2-layout.test.mjs"]
        results.append(run_check("javascript", [node, "--test", "--test-reporter=tap", *map(str, tests)], output,
                                 cwd=ROOT / "tools/cdp", env=env))
        if args.mode == "release" and results[-1]["counts"].get("skipped", 0):
            results[-1]["status"] = "incomplete"
        if args.mode == "release":
            scenario_env = {**env, "REPORT_ESTIMATE_HTML": str(scenario_fixture / "report.html"),
                            "REPORT_SCREENSHOTS_DIR": str(output / "scenario-screenshots")}
            results.append(run_check("scenario-layout", [node, "--test", "--test-reporter=tap",
                str(ROOT / "tools/cdp/report-estimate-layout.test.mjs")], output, cwd=ROOT / "tools/cdp", env=scenario_env))
    else:
        results.append({"name": "javascript", "status": "incomplete", "reason": "Node unavailable"})
    complete = all(item["status"] == "passed" for item in results)
    manifest = {"mode": args.mode, "status": "passed" if complete else "incomplete",
                "scope": "Offline fixtures and browser layout only; no live provider acceptance.",
                "live_recall_acceptance": {"status": "not_run", "required_separately": True,
                    "command": "scripts/verify_recall_acceptance.py --task-dir DIR --oracle FILE --output NEW_FILE"},
                "checks": results}
    (output / "verification.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(str(output / "verification.json"), flush=True)
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
