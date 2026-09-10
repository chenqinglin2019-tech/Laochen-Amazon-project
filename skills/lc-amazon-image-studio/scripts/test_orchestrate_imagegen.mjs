import assert from "node:assert/strict";
import test from "node:test";
import { runImagegenQueue, safeImageSummary } from "./orchestrate_imagegen.mjs";

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

test("artifact paths include Windows drives and UNC, not relative or device paths", () => {
  for (const path of ["/tmp/图片.png", "C:/图片/a.png", String.raw`C:\图片\a.png`, String.raw`\\server\share\图片.png`]) {
    assert.deepEqual(safeImageSummary({ path }).artifact_paths, [path]);
  }
  for (const path of ["a.png", "C:a.png", String.raw`\图片.png`, String.raw`\\server`, String.raw`\\.\pipe\name`, String.raw`\\?\C:\a.png`, "/tmp/a\n.png"]) {
    assert.deepEqual(safeImageSummary({ path }).artifact_paths, []);
  }
});

test("UNC artifact returned by the real tool schema is ingested unchanged", async () => {
  const f = fixture(1, [1]);
  const artifact = String.raw`\\server\share\图片.png`;
  f.options.selectArtifact = () => artifact;
  const original = f.options.command;
  f.options.command = args => {
    if (args[0] === "ingest") assert.equal(args[args.indexOf("--artifact") + 1], artifact);
    return original(args);
  };
  const result = await runImagegenQueue(f.options);
  assert.equal(result.completed[0].artifact, artifact);
  assert.deepEqual(result.errors, []);
});

function fixture(capacity = 2, delays = [5, 40, 5]) {
  const jobs = delays.map((delay, i) => ({ id: `j${i}`, delay, status: "pending", prompt_hash: `p${i}` }));
  const log = [];
  const events = {};
  const queue = () => ({ ok: true, scheduler: { effective_concurrency: capacity },
    dispatch: jobs.filter(job => job.status === "pending").slice(0,
      Math.max(0, capacity-jobs.filter(job => job.status === "generating").length))
      .map(job => ({ id: job.id, prompt_hash: job.prompt_hash, action: "image_gen" })),
    deterministic_resume: jobs.filter(job => job.status === "generated").map(job => job.id) });
  const command = async args => {
    const value = key => args[args.indexOf(key) + 1];
    const job = jobs.find(job => job.id === value("--job"));
    if (args[0] === "status") return queue();
    log.push(`${args[0]}:${job.id}`);
    if (args[0] === "transition") {
      assert.equal(job.status, "pending");
      assert.ok(jobs.filter(job => job.status === "generating").length < capacity);
      job.status = "generating";
      return { ok: true, attempt_id: `a-${job.id}`, prompt_hash: job.prompt_hash };
    }
    if (args[0] === "attempt-event") {
      await sleep(10); // Local event writer is intentionally slower than image 0.
      events[job.id] = { started: Number(value("--timestamp")) };
      return { ok: true };
    }
    if (args[0] === "ingest") {
      assert.equal(job.status, "generating");
      assert.ok(events[job.id]);
      events[job.id].returned = Number(value("--tool-returned-at"));
      job.status = "generated";
      return { ok: true, status: "generated", dispatch: queue().dispatch };
    }
    throw new Error(`unexpected synthetic command ${args[0]}`);
  };
  let active = 0;
  let maximumActive = 0;
  const options = {
    initialPlan: queue(), command,
    readInput: async entry => { log.push(`read:${entry.id}`); return { prompt: entry.id }; },
    imagegen: async input => {
      const job = jobs.find(job => job.id === input.prompt);
      log.push(`model:${job.id}`);
      job.actualStart = Date.now()/1000;
      active += 1;
      maximumActive = Math.max(maximumActive, active);
      await sleep(job.delay);
      active -= 1;
      job.actualReturn = Date.now()/1000;
      log.push(`return:${job.id}`);
      return { artifact_path: `/synthetic/${job.id}.png`, content: [{ type: "image", data: "NEVER_PRINT" }] };
    },
    selectArtifact: result => result.artifact_path,
  };
  return { options, jobs, log, events, maximumActive: () => maximumActive };
}

for (const capacity of [1, 2, 4]) {
  test(`capacity ${capacity}: all actual calls stay awaited and within admitted slots`, async () => {
    const f = fixture(capacity, [5, 40, 5, 5, 5]);
    const result = await runImagegenQueue(f.options);
    assert.equal(result.completed.length, 5);
    assert.deepEqual(result.errors, []);
    assert.ok(f.maximumActive() <= capacity);
    if (capacity > 1) assert.ok(f.maximumActive() > 1);
    assert.equal(result.review_ready.length, 5);
    for (const job of f.jobs) {
      assert.ok(f.log.indexOf(`read:${job.id}`) < f.log.indexOf(`transition:${job.id}`));
      assert.ok(f.events[job.id].started <= job.actualStart);
      assert.ok(f.events[job.id].returned >= job.actualReturn);
      assert.ok(f.events[job.id].returned-f.events[job.id].started < .2);
    }
    assert.ok(!JSON.stringify(result).includes("NEVER_PRINT"));
  });
}

test("refill follows first ingest, while slow sibling and review notification remain pending", async () => {
  const f = fixture(2, [5, 80, 5]);
  let releaseReview;
  const review = new Promise(resolve => { releaseReview = resolve; });
  f.options.onReviewReady = () => review;
  const running = runImagegenQueue(f.options);
  await sleep(45);
  assert.ok(f.log.includes("model:j2"));
  assert.ok(!f.log.includes("return:j1"));
  releaseReview();
  const result = await running;
  assert.equal(result.completed.length, 3);
  assert.ok(f.log.indexOf("model:j2") < f.log.indexOf("return:j1"));
});

test("one model error does not cancel or drop sibling results", async () => {
  const f = fixture(2);
  const original = f.options.imagegen;
  f.options.imagegen = input => input.prompt === "j0" ? Promise.reject(new Error("synthetic timeout")) : original(input);
  f.options.onFailure = async failure => { f.jobs.find(job => job.id === failure.job).status = "failed"; };
  const result = await runImagegenQueue(f.options);
  assert.equal(result.completed.length, 2);
  assert.equal(result.errors.length, 1);
  assert.equal(result.errors[0].job, "j0");
});

test("event-write failure awaits the tool and exposes recoverable path without ingesting", async () => {
  const f = fixture(1, [20]);
  const original = f.options.command;
  f.options.command = args => args[0] === "attempt-event" ? Promise.reject(new Error("synthetic lock error")) : original(args);
  const result = await runImagegenQueue(f.options);
  assert.ok(f.log.includes("return:j0"));
  assert.equal(result.completed.length, 0);
  assert.equal(result.errors[0].artifact, "/synthetic/j0.png");
  assert.ok(!f.log.includes("ingest:j0"));
});

test("changed dispatch binding never invokes a model", async () => {
  const f = fixture(1, [5]);
  const original = f.options.command;
  f.options.command = async args => {
    const result = await original(args);
    return args[0] === "transition" ? { ...result, prompt_hash: "changed" } : result;
  };
  const result = await runImagegenQueue(f.options);
  assert.equal(result.completed.length, 0);
  assert.ok(!f.log.includes("model:j0"));
});

test("diagnosed job does not repeat while independent jobs continue", async () => {
  const f = fixture(2);
  const next_actions = [{ action: "diagnose", jobs: ["j0"], command: "plan" }];
  f.options.initialPlan.next_actions = next_actions;
  const original = f.options.command;
  f.options.command = async args => {
    const result = await original(args);
    return args[0] === "status" ? { ...result, next_actions } : result;
  };
  const result = await runImagegenQueue(f.options);
  assert.ok(!f.log.includes("model:j0"));
  assert.equal(result.completed.length, 2);
  assert.equal(result.next_actions[0].action, "diagnose");
});

test("native images are never traversed or serialized for summary", () => {
  const image = { type: "image", get data() { throw new Error("must not access payload"); } };
  assert.deepEqual(safeImageSummary({ content: [image], path: "/synthetic/a.png" }),
    { has_image: true, artifact_paths: ["/synthetic/a.png"] });
  assert.deepEqual(safeImageSummary(null), { has_image: false });
});
