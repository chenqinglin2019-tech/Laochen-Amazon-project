/** Thin, dependency-injected adapter for the *existing* built-in tool workflow.
 * No credentials, network client, subprocess, model API, or detached work.
 * Load this trusted module in a tool-enabled JS cell; keep the returned Promise
 * awaited across yields. `command` calls the existing authorized pipeline CLI.
 */

function isAbsoluteArtifact(value) {
  if (typeof value !== "string" || /[\r\n\0]/.test(value)) return false;
  // Accept native drive paths and real UNC server/share paths, never a lone
  // backslash (drive-relative) or a Windows device namespace.
  return /^(\/|[A-Za-z]:[\\/])/.test(value) || /^\\\\[^\\/.?][^\\/]*[\\/][^\\/]+[\\/].+/.test(value);
}

export function safeImageSummary(result) {
  // Do not traverse, clone, stringify, or return an image's Base64 payload.
  if (!result || typeof result !== "object") return { has_image: false };
  const blocks = Array.isArray(result.content) ? result.content : [];
  const paths = [result.path, result.output_path, result.image_path]
    .filter(isAbsoluteArtifact);
  return { has_image: blocks.some(block => block?.type === "image") || Boolean(result.image_url),
    artifact_paths: paths };
}

function errorMessage(error) {
  return String(error?.message || error).replace(/data:image\/[^;,\s]+;base64,[A-Za-z0-9+/=]+/g,
    "[native image omitted]").slice(0, 1000);
}

export async function runImagegenQueue(options) {
  const { command, readInput, imagegen, selectArtifact, showImage, onReviewReady,
    onFailure, onProgress, now = () => Date.now() / 1000, initialPlan } = options;
  for (const [name, value] of Object.entries({ command, readInput, imagegen, selectArtifact })) {
    if (typeof value !== "function") throw new TypeError(`${name} callback is required`);
  }
  const active = new Map();
  const attempted = new Set();
  const reviews = new Set(initialPlan?.deterministic_resume || []);
  const errors = [];
  const completed = [];
  const notifications = [];
  let snapshot = initialPlan;

  function notify(callback) {
    notifications.push(Promise.resolve().then(callback).catch(error => {
      errors.push({ phase: "notification", error: errorMessage(error) });
    }));
  }

  async function call(args) {
    const value = await command(args);
    if (!value || value.ok === false) {
      const error = new Error(value?.error || `Pipeline command failed: ${args[0]}`);
      error.command = args[0];
      throw error;
    }
    return value;
  }

  async function generate(entry) {
    let attempt;
    let artifact;
    let returnedAt;
    let phase = "pre_read";
    try {
      // Read exactly the already-bound prompt; inspect all local edit targets
      // here. Never augment text or assemble references after transition.
      const input = await readInput(entry);
      if (!input || typeof input.prompt !== "string" || !input.prompt.trim()) {
        throw new Error("Pre-read must return the bound prompt and actual tool arguments");
      }
      phase = "transition";
      attempt = await call(["transition", "--job", entry.id, "--status", "generating",
        "--reason", "Dispatching the pre-read bound prompt to the built-in image tool"]);
      if (!attempt.attempt_id || attempt.prompt_hash !== entry.prompt_hash) {
        throw new Error("Dispatch binding changed after pre-read; re-plan this job before generation");
      }
      phase = "tool";
      // Invoke immediately, capture settlement *inside* this promise, then
      // persist the actual start while the model runs. Never include the CLI's
      // event-recording latency in the measured model interval. Attach both
      // handlers synchronously to avoid an unhandled fast rejection.
      const toolPromise = Promise.resolve().then(() => {
        // This microtask is the actual invocation boundary, not pre-read time.
        const actualStartedAt = now();
        return { actualStartedAt, value: imagegen(input) };
      });
      const invoked = await toolPromise;
      const settled = Promise.resolve(invoked.value).then(
        result => ({ result, returnedAt: now() }),
        error => ({ error, returnedAt: now() }));
      let eventError;
      try {
        await call(["attempt-event", "--job", entry.id, "--attempt-id", attempt.attempt_id,
          "--event", "tool_started", "--timestamp", String(invoked.actualStartedAt)]);
      } catch (error) { eventError = error; }
      const outcome = await settled; // Never abandon a tool call, even on event-write failure.
      returnedAt = outcome.returnedAt;
      if (outcome.error) throw outcome.error;
      if (outcome.result?.isError) {
        const message = (outcome.result.content || []).filter(block => block?.type === "text")
          .map(block => String(block.text || "").slice(0, 500)).join(" ");
        throw new Error(message || "Built-in image tool returned an error");
      }
      phase = "artifact";
      artifact = await selectArtifact(outcome.result, entry);
      if (!isAbsoluteArtifact(artifact)) {
        throw new Error("selectArtifact must return the actual absolute generated-image path");
      }
      if (eventError) throw eventError;
      phase = "ingest";
      const ingested = await call(["ingest", "--job", entry.id, "--artifact", artifact,
        "--attempt-id", attempt.attempt_id, "--tool-returned-at", String(returnedAt)]);
      completed.push({ job: entry.id, attempt_id: attempt.attempt_id, artifact,
        tool_returned_at: returnedAt, status: ingested.status });
      reviews.add(entry.id);
      // Native output stays native. The callback must use generatedImage/image;
      // no result object is ever included in this adapter's JSON summary.
      if (showImage) notify(() => showImage(outcome.result));
      if (onReviewReady) notify(() => onReviewReady({ job: entry.id, artifact, status: ingested.status }));
      return ingested;
    } catch (error) {
      const failure = { job: entry.id, attempt_id: attempt?.attempt_id, phase,
        error: errorMessage(error), artifact, tool_returned_at: returnedAt };
      errors.push(failure);
      // Let the existing retry/diagnostic writer record a true failure. It must
      // not sign QA or reset counters. A failed job never cancels sibling calls.
      if (onFailure) {
        try { await onFailure(failure); }
        catch (recordError) { failure.failure_record_error = errorMessage(recordError); }
      }
      return { failed: true, ...failure };
    }
  }

  async function local(entry) {
    try {
      await call(["review-prepare", "--job", entry.id]);
      reviews.add(entry.id);
      if (onReviewReady) await onReviewReady({ job: entry.id, status: "review_pending" });
    } catch (error) {
      const failure = { job: entry.id, phase: "local", error: errorMessage(error) };
      errors.push(failure);
      if (onFailure) await onFailure(failure);
    }
  }

  while (true) {
    // Status only reads. Normal runs use the supplied plan once and status
    // subsequently; inputs/error changes are the caller's reason to re-plan.
    snapshot = snapshot || await call(["status"]);
    for (const id of snapshot.deterministic_resume || []) reviews.add(id);
    for (const id of snapshot.review_pending || []) reviews.add(id);
    const dispatch = Array.isArray(snapshot.dispatch) ? snapshot.dispatch : [];
    const diagnosing = new Set((snapshot.next_actions || []).filter(value => value.action === "diagnose")
      .flatMap(value => value.jobs || []));
    const ceiling = snapshot.scheduler?.effective_concurrency ?? snapshot.concurrency ?? 1;
    for (const entry of dispatch) {
      const key = `${entry.id}:${entry.prompt_hash || entry.action}`;
      if (attempted.has(key) || active.has(entry.id) || diagnosing.has(entry.id)) continue;
      const modelCount = [...active.values()].filter(value => value.model).length;
      if (entry.action === "image_gen" && modelCount >= ceiling) continue;
      if (!new Set(["image_gen", "compose"]).has(entry.action)) continue;
      attempted.add(key);
      const promise = (entry.action === "image_gen" ? generate(entry) : local(entry))
        .catch(error => { errors.push({ job: entry.id, phase: "adapter", error: errorMessage(error) }); })
        .then(() => entry.id);
      active.set(entry.id, { promise, model: entry.action === "image_gen" });
    }
    if (!active.size) break;
    // Refill after the first completed ingest, not the slowest image in a batch.
    const finished = await Promise.race([...active.values()].map(value => value.promise));
    active.delete(finished);
    if (onProgress) {
      const progress = { completed: completed.length, active: active.size,
        review_ready: [...reviews], failed: errors.length };
      notify(() => onProgress(progress));
    }
    try { snapshot = await call(["status"]); }
    catch (error) {
      // Status failure stops new dispatch, but all already-started calls must
      // finish and retain their results in this same awaited cell lifetime.
      errors.push({ phase: "status", error: errorMessage(error) });
      await Promise.allSettled([...active.values()].map(value => value.promise));
      active.clear();
      break;
    }
  }
  const notificationResults = await Promise.allSettled(notifications);
  for (const result of notificationResults) {
    if (result.status === "rejected") errors.push({ phase: "notification", error: errorMessage(result.reason) });
  }
  return { completed, review_ready: [...reviews], errors,
    retry_after_seconds: snapshot?.scheduler?.retry_after_seconds || 0,
    next_actions: snapshot?.next_actions || [],
    note: "Images require real visual review and the existing review-submit/finalize/deliver gates." };
}
