# Built-in ImageGen orchestration adapter

This is a thin adapter over the existing pipeline, not another scheduler, model backend, authentication implementation or review authority. All production operations keep the authentication requirements in `SKILL.md` unchanged. Run the original gate at its original production boundary before using this adapter. Maintenance tests use only synthetic callbacks and never run real authentication or ImageGen.

## Adapter lifecycle

Follow the single [production workflow](../SKILL.md#生产主流程); this section only defines tool handoff. Read the adapter source once and execute `runImagegenQueue` in an awaited tool-enabled JavaScript cell, starting from the existing plan or current read-only status result. `readInput` reads the bound prompt unchanged and inspects local references before transition. Use the tool's actual reported concurrency; do not impose capacity 1 without evidence. Explicit capacity uses `--tool-capacity`, `--tool-capacity-source` and `--tool-capacity-reason` on the existing plan command.

The adapter reserves each attempt with `transition`, invokes the actual built-in ImageGen tool immediately, records the real invocation timestamp while that call runs, and captures the actual settlement timestamp inside the promise callback. A result is ingested before entering the independent review queue. A slow image or review notification does not hold up the next admitted generation.

The adapter never invents annotations, transcripts or verdicts. The first anchor still needs genuine QA before siblings become eligible. Resume from `status --json` after actual review submissions; only changed inputs, stale preparation or a controlled repair require a new plan.

`runImagegenQueue` stops when no new generation/local-compose job is presently admitted. Its `review_ready` result is a request for actual review, not a claim that the whole suite is finished. An adapter invocation attempts a given job/prompt binding at most once; existing retry and repair budgets remain authoritative. Record a real tool failure through the existing transition/diagnostic path, follow the reported retry delay, then resume from status. Never rewrite statuses or attempt hashes manually.

## Functions tool-cell integration

The module has no imports or ambient filesystem/network dependencies. Read its trusted source using the normal local command tool and store it in the current tool session. For example, in a `functions.exec` cell, with `skillRoot` already resolved from the active skill catalog:

```javascript
// isWindows comes from the observed host. Use PowerShell on Windows and the
// normal POSIX shell on macOS. selectedPython comes from runtime verification.
const quote = value => "'" + String(value).replace(/'/g, isWindows ? "''" : "'\\''") + "'";
const reader = "from pathlib import Path; import sys; sys.stdout.write(Path(sys.argv[1]).read_text(encoding='utf-8'))";
const argv = [selectedPython, "-X", "utf8", "-c", reader,
  skillRoot + "/scripts/orchestrate_imagegen.mjs"];
const source = await tools.exec_command({
  cmd: (isWindows ? "& " : "") + argv.map(quote).join(" "),
  max_output_tokens: 16000
});
if (source.exit_code !== 0) throw new Error("Adapter source could not be read");
store("lcImagegenAdapter", source.output);
```

The production cell injects **existing** local command and image-tool callbacks. [Runtime setup](runtime-setup.md) must pass `verify` for this run (or the identical verification at the end of install); inspect alone only confirms dependency presence/version. This requires the existing doctor, actual Pillow/NumPy imports and browser launch, without replacing account authentication. `pipeline(args)` must use the returned Python and `LC_LAYOUT_*` environment, append the current `--manifest` and `--json`, parse the single JSON result, and await any command session to completion. Do not install into a venv and then launch the system Python. `readBoundInput` reads `entry.prompt_file` and resolves `entry.generation_reference_paths` against the project directory, displays each required local image once, and returns exactly `{prompt, referenced_image_paths}` (omit the paths field for a truly new image). It must reject truncated prompt reads. `actualArtifactPath` selects the actual local path from the tool's returned metadata/text; it must not guess a destination or serialize the image payload.

```javascript
// @exec: {"yield_time_ms": 120000, "max_output_tokens": 2000}
const adapter = new Function(
  load("lcImagegenAdapter").replace(/^export /gm, "") +
  "\nreturn {runImagegenQueue, safeImageSummary};"
)();
const result = await adapter.runImagegenQueue({
  initialPlan: preparedPlan, // The one existing plan result, or a fresh status result.
  command: pipeline,
  readInput: readBoundInput,
  imagegen: args => tools.image_gen__imagegen(args), // Actual built-in tool; no CLI/API substitute.
  selectArtifact: actualArtifactPath,
  showImage: result => generatedImage(result),
  onReviewReady: item => notify({review_ready: item.job, artifact: item.artifact}),
  onProgress: progress => notify(progress),
  onFailure: recordExistingWorkflowFailure
});
text(result); // Contains paths/status only, never Base64 or the raw tool object.
```

The callback names in this snippet are explicit adapters to the active tool's observed return schema and the already-selected runtime/project, not additional services. A missing/ambiguous artifact path is a recoverable handoff failure: keep the returned image and attempt, resolve its real path, then call the existing ingest command with the captured timestamps. Do not start another model call for that handoff error.

The pipeline emits UTF-8 JSON, including Windows redirected streams. Decode command output as UTF-8 and preserve Unicode paths. Accept actual absolute drive/UNC paths returned by the tool; never convert them using POSIX-only quoting or `sed`. Use the selected Python's argv interface wherever the host tool supports it. UNC handoff support does not certify a network filesystem's cross-process locking; keep mutable projects on a local volume until that share has been tested.

Keep the tool cell's promise awaited until every started model call is settled, including error paths. Use the product's yielded-cell wait mechanism; never fire-and-forget model promises or launch an OS background worker. Deliver native images with `generatedImage` / `image`, and use `safeImageSummary` only when a compact text diagnostic is needed. Do not use `text(result)` or `JSON.stringify(result)` on the raw image-tool result.

## State, diagnostics and timing contracts

- `lc_runtime_status.build_status(manifest, base, now=None, detail=False)` is read-only: a private snapshot, no prepare/render, filesystem writes, lock creation or recovery mutation. It reports counts, actual capacity evidence, in-flight attempts, eligible dispatch, review queue, blockers, next actions and timing coverage.
- `set_tool_capacity(manifest, capacity, source=..., reason=..., now=...)` retains the historical integer capacity and records evidence separately. Old integer-only manifests remain valid; absent evidence is reported as absent, never fabricated as a tool observation.
- Command failures are recorded with the current business-input fingerprint, command and job scope. Two successive identical failures on unchanged inputs raise `diagnosis_required`; they do not change any job, consume repair budget, certify QA or stop independent dispatch. A real success clears that scope's streak. These diagnostic fields are excluded from visual dependencies.
- Structurally invalid manifests, retired backends and unknown job scopes retain their original atomic rejection: no diagnostic write to the rejected project. Recoverable production failures bind actual source-file hashes, including missing inputs. The fingerprint also includes lightweight installed-runtime identities (Python/Pillow, Node, Playwright package/lock and Chromium path metadata), so restoring a source or repairing dependencies unlocks the next valid attempt without editing the Manifest. This check does not start a browser or run doctor.
- Explicit attempt start/return events measure actual tool calls. `timing_summary` unions overlapping intervals and reports per-call sums separately. Missing historical boundaries remain `null`. A complete explicit observation window is needed to compute an unclassified gap; that gap must not be described as measured model or agent reasoning time. Duration-only legacy records are never retroactively placed on a timeline.
- An existing immutable successful product-review submission may keep the anchor scheduling gate open during local-only rework, after verifying its bytes and current product/raw/evidence/annotations/rules. This does not pass final QA or delivery. Changed raw, provenance, product facts or composition closes that proof; legacy fallback with a project base still checks the current final and QA bindings.

## Maintenance checks

Run the Python scheduler/runtime-status tests and `node --test scripts/test_orchestrate_imagegen.mjs`. Fixtures cover capacity 1/2/4, first-result refill, slow review notification, out-of-order returns, independent failure, event-write recovery, stale dispatch, missing timing and payload suppression. These are no-model tests and do not establish an end-to-end production speedup.
