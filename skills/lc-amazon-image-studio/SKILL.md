---
name: lc-amazon-image-studio
description: 基于真实产品图和卖点规划、生成与质检 Amazon Listing 与 A+ 图片，严格保留产品比例、材质和关键细节。
---

# 易逊-亚马逊套图生成

Build a sellable `7+1` Amazon image system without repainting or simplifying the real product unnecessarily.

## Cloud Auth Gate

Before reading product images, inspecting competitor listings, planning image slots, writing prompts, generating images, or giving strategy output, run the Laochen cloud auth gate from this skill root.

The user's key goes in `config.json`:

```json
{
  "backend_url": "https://mcp.yixunkuajing.com",
  "backend_token": ""
}
```

Choose the binary for the current platform:

- Linux: `tools/bin/lc-auth-check-linux-amd64`
- macOS Apple Silicon: `tools/bin/lc-auth-check-darwin-arm64`
- macOS Intel: `tools/bin/lc-auth-check-darwin-amd64`
- Windows: `tools/bin/lc-auth-check-windows-amd64.exe`

On macOS, before the first run, silently execute:

```bash
xattr -dr com.apple.quarantine tools/bin 2>/dev/null || true
chmod +x tools/bin/* 2>/dev/null || true
```

Then run the selected auth tool from the skill root. Never print or reveal the full key.

If auth fails, the token is missing, or the binary is unavailable, stop immediately and use only:

```text
云端鉴权未通过，本轮不继续执行。
```

## Load Only What Is Needed

- Read `references/runtime-pipeline.md` for every full generation, edit, resume, QA, or delivery run.
- Read `references/amazon-listing-image-sop.md` for product/buyer strategy, slot planning, and the delivery checklist.
- Read `references/category-playbooks.md` when category-specific scenes or objections matter.
- Read `references/web-chatgpt-prompt-template.md` only when the user requests a secondary web ChatGPT/Image 2 prompt pack.

## Required Inputs

Collect before planning:

- one or more real product images
- confirmed product facts, included parts, constraints, and selling points
- either the user's image plan or one competitor Amazon URL/ASIN
- target marketplace and requested output

Choose exactly one strategy branch:

- `user_planned`: select whenever the user specifies the purpose, content, composition, or sequence of at least one requested image; a partial plan is usable and may be completed from product truth
- `competitor_learning`: select only when no usable user plan exists; learn selling jobs and objection handling, never copy execution

## Non-Negotiable Product Truth

Inspect source images at original detail before writing prompts.

Build one reusable `Product Truth Profile`:

- `Geometry Lock`: confirmed dimensions, normalized ratios, silhouette, thickness, relative part sizes, supported views, and unknown axes
- `Material Lock`: substrate, color, finish, gloss/roughness, translucency, texture, edges, and light behavior
- `Scene Scale Lock`: physical dimensions, support surface, camera view, known reference-object range, contact point, and shadow logic
- `Critical Detail Lock`: ports, buttons, indicators, screws, holes, clips, hinges, seams, stitching, scales, logos, labels, and other identifying details

Never infer a hidden axis, surface, component, accessory, port, label, or texture from an unsupported view.

Never stretch, squeeze, widen, slim, elongate, shorten, thicken, smooth, redesign, add, delete, close, move, or simplify the real product.

## Source-Quality Gate

Judge the product's effective pixel area, not only the full image size.

- Allow `original_pixels` when final product pixels require at most `1.25x` enlargement.
- Treat `1.25x–1.75x` as marginal; do not use it for macro material or critical-detail claims.
- Block direct pixel compositing above `1.75x`; create and confirm one restored master or request better photos.

Do not claim that upscaling restored real details. If a logo, label, interface, scale, or texture is unreadable, request a close-up.

## Critical Detail Census

Register every functional or identifying micro-detail as `P0`, `P1`, or `P2`:

- `P0`: functional; missing, moved, filled, or redesigned is a hard failure
- `P1`: identifying; obvious change is a failure
- `P2`: minor appearance; reasonable lighting variation is allowed

For every detail, record:

- evidence level: `visual_confirmed`, `user_claim_only`, `listing_fact`, or `unknown`
- separate visual confirmation: `confirmed`, `unverifiable`, or `unknown`
- supported reference and view
- normalized bounding box inside the product box
- component, position, shape, orientation, color, and surrounding structure
- per-image visibility: `required`, `optional`, or `hidden`

Extract a separate detail reference crop. Mark it `unverifiable` when every crop has a longest edge below `32px`, a shortest edge below `8px`, or cannot be visually identified. Block any image that requires an unverifiable P0/P1 detail.

Set `critical_detail_census_completed=true` only after inspecting all source images at original resolution. For every P0/P1 detail, explicitly assign `required`, `optional`, or `hidden` to every job. A user's statement that a USB port exists is product evidence, but without a readable view and location it remains `user_claim_only` and blocks any image that must show it.

Do not force a detail into an angle where it should be hidden. Never move a USB port to another surface to make it visible.

## Render Modes

Choose the safest mode per slot:

- `pixel_composite`: preserve real or confirmed-master product pixels; use first for main, size, material, detail, and package slots
- `reference_edit`: change only the requested background, light, or local environment
- `reference_generate`: use only for complex interaction scenes; require full geometry/material/scale/detail review

Prefer generating around the product over generating the product again.

Main image requirements:

- pure white background
- actual product only
- no text, claims, props, people, watermark, or invented component

## Fast Resumable Execution

Use `scripts/lc_image_pipeline.py` and `assets/project_manifest.template.json` as described in `references/runtime-pipeline.md`.

Default to `risk_gated_auto`:

- pause only for missing product truth, insufficient source quality, an unverified restored master, or an unverifiable required P0/P1 detail
- obey the manifest-wide `generation_gate`; do not generate other required jobs while it is closed
- generate two anchors first: main image and primary-use scene
- after anchor QA, generate remaining jobs in pairs with concurrency `2`
- reduce concurrency to `1` after rate limiting or repeated timeouts
- generate only the requested `7+1`; do not add bonus images by default
- retry transient failures twice with the same prompt hash
- allow one targeted quality repair per job
- reuse every unchanged `qa_passed` job

The built-in `image_gen` path remains the default. Do not switch to CLI/API generation unless the user explicitly requests it.

## Prompt Contract

Begin every per-image prompt with the four locks. Include only critical details relevant to that view.

Label every input image role explicitly:

- whole-product reference
- edit target
- critical-detail reference
- material reference
- component or package reference

Generate text-free bases. Add dimensions, headlines, and callouts deterministically during local postprocessing.

For edits, say `change only X; keep everything else unchanged`. Repeat product invariants on every repair.

## Hard QA Gate

Do not deliver from a contact-sheet-only review.

For every required P0/P1 detail:

1. locate the expected region from the output product box and normalized detail coordinates
2. generate a side-by-side reference/output detail comparison
3. inspect it at original detail
4. record an explicit `pass` or `fail` in `detail_qa_results`

Treat a missing verdict as `repair_needed`. Treat an unverifiable required detail as `blocked`.

Also record explicit semantic verdicts for geometry, material, components, and scene scale, plus policy verdicts for main-image content, claims, competitor copying, and text readability. A prompt is an instruction, not QA evidence.

When a P0/P1 detail fails, perform one precise-object edit using the generated repair prompt. Change only that local detail. If it fails again, block the job and request a better close-up or human retouch.

## Delivery Gate

Deliver only when:

- all required jobs are `qa_passed`
- every required P0/P1 detail has an explicit pass
- listing images are exactly `1600x1600`
- A+ matches the requested module, normally `970x600`
- no non-uniform scaling, unsupported component, hallucinated claim, copied competitor execution, or unreadable text remains
- `project_manifest.json`, `qa_report.json`, final contact sheet, and micro-detail contact sheet exist

Run the runtime `delivery-check`; file presence alone is insufficient because it also verifies current prompt/output hashes and every required job state.

If any required job is `blocked`, `repair_needed`, or `failed`, identify it as not production-ready. Never describe an incomplete set as finished.
