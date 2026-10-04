import test from "node:test";
import assert from "node:assert/strict";
import { ACCOUNT_CAPACITY_POLICY, ACCOUNT_CAPACITY_POLICY_REVISION, ACTIVE_FREE_POLICY, assertActiveTaskPayload } from "./cdp-cli.mjs";

const task = (revision, policy) => ({ schema_version: "2.4-free", free_policy_revision: revision,
  free_policy: structuredClone(policy), coverage_requirements: [{ requirement_id: "COV-1" }] });

test("CDP accepts versioned account capacity and retains historical zero-cost policy", () => {
  assert.doesNotThrow(() => assertActiveTaskPayload(task(ACCOUNT_CAPACITY_POLICY_REVISION, ACCOUNT_CAPACITY_POLICY)));
  assert.doesNotThrow(() => assertActiveTaskPayload(task("automation-first-v1", ACTIVE_FREE_POLICY)));
  assert.throws(() => assertActiveTaskPayload(task("automation-first-v1", ACCOUNT_CAPACITY_POLICY)), /FREE_POLICY_INVALID/);
});

test("CDP rejects purchase, recharge, upgrade, overage and missing policy fields", () => {
  for (const field of ["allow_new_purchase", "allow_recharge", "allow_upgrade", "allow_overage"]) {
    const altered = task(ACCOUNT_CAPACITY_POLICY_REVISION, ACCOUNT_CAPACITY_POLICY);
    altered.free_policy[field] = true;
    assert.throws(() => assertActiveTaskPayload(altered), /FREE_POLICY_INVALID/);
  }
  const altered = task(ACCOUNT_CAPACITY_POLICY_REVISION, ACCOUNT_CAPACITY_POLICY);
  delete altered.free_policy.allow_new_purchase;
  assert.throws(() => assertActiveTaskPayload(altered), /FREE_POLICY_INVALID/);
});
