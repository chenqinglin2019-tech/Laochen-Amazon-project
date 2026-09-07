import test from "node:test";
import assert from "node:assert/strict";
import crypto from "node:crypto";
import { extractPpubsAbstract, ppubsTextEvidenceMetadata } from "./cdp-cli.mjs";

test("abstract stops at observed PPS Background/Summary, not the claims section", () => {
  const value = "DOCUMENT ID\nUS 20260233895 A1\nAbstract\n\nA container has a lid.\nA second abstract paragraph.\n\nBackground/Summary\n\n[0001] Detailed background.\n\nClaims\n1. A container.";
  assert.equal(extractPpubsAbstract(value), "A container has a lid.\nA second abstract paragraph.");
});

test("published-section boundaries are whole headings, not words in the abstract", () => {
  for (const heading of ["BACKGROUND", "BACKGROUND OF THE INVENTION", "Summary", "SUMMARY OF INVENTION", "Description", "DETAILED DESCRIPTION", "BRIEF DESCRIPTION OF THE DRAWINGS", "Claims", "WHAT IS CLAIMED IS:"]) {
    assert.equal(extractPpubsAbstract(`(57) ABSTRACT\r\n\r\nThis description discusses claims and background.\r\n${heading}\r\nOther text.`), "This description discusses claims and background.");
  }
});

test("missing or empty abstract is not reported as acquired", () => {
  for (const value of [null, undefined, {}, "", "A reference to an abstract.\nClaims\n1. A lid.", "Abstract\n\nClaims\n1. A lid."]) {
    assert.equal(extractPpubsAbstract(value), "");
  }
  assert.equal(extractPpubsAbstract("Abstract:\nA lid.\n"), "A lid.");
});

test("old published ABSTRACT OF THE DISCLOSURE is a real whole heading", () => {
  const abstract = "A basic structure and a retaining strap.\nAnother paragraph.";
  for (const heading of ["ABSTRACT OF THE DISCLOSURE", "Abstract of the Disclosure:", "(57) ABSTRACT OF THE DISCLOSURE"]) {
    assert.equal(extractPpubsAbstract(`DOCUMENT ID\nUS3431004A\n${heading}\n${abstract}\nClaims\n1. A strap.`), abstract);
  }
  assert.equal(extractPpubsAbstract("A sentence about the abstract of the disclosure.\nClaims\n1. A strap."), "");
  assert.equal(extractPpubsAbstract("ABSTRACT OF THE DISCLOSURE\nClaims\n1. A strap."), "");
});

test("source metadata binds canonical JSON string bytes before Python retention", () => {
  const text = 'Basic principles and basic and.\nBearer synthetic-fixture\n中文 "quoted"';
  const value = ppubsTextEvidenceMetadata(text);
  assert.equal(value.text_evidence_revision, "retained-text-v1");
  assert.equal(value.text_hash_algorithm, "sha256-canonical-json-utf8");
  assert.equal(value.rendered_text_stage, "source");
  assert.equal(value.source_rendered_text_stage, "source");
  assert.equal(value.rendered_text_sha256, crypto.createHash("sha256").update(JSON.stringify(text)).digest("hex"));
  assert.equal(value.source_rendered_text_sha256, value.rendered_text_sha256);
  assert.notEqual(value.rendered_text_sha256, crypto.createHash("sha256").update(text).digest("hex"));
  for (const bad of [null, undefined, "", " ", 123]) assert.throws(() => ppubsTextEvidenceMetadata(bad));
});
