# V2 Runtime Pipeline

Use this reference for every full image-generation run. The local pipeline is deterministic; it does not call an image model.

## Contents

- [Runtime contract](#runtime-contract)
- [Project setup](#project-setup)
- [Source-quality gate](#source-quality-gate)
- [Critical Detail Census](#critical-detail-census)
- [Prompt preparation](#prompt-preparation)
- [Generation waves](#generation-waves)
- [Postprocess and QA](#postprocess-and-qa)
- [Repair and resume](#repair-and-resume)
- [Delivery gate](#delivery-gate)

## Runtime contract

Use the built-in `image_gen` path by default. Do not switch to CLI/API batch generation unless the user explicitly asks for it.

The agent owns:

- reading product images at original detail
- completing `project_manifest.json`
- assigning reference roles and normalized bounding boxes
- calling built-in image generation/edit tools
- visually reviewing geometry, materials, scene scale, and detail comparison sheets
- recording semantic, policy, and critical-detail QA verdicts

The local script owns:

- manifest validation and source-resolution calculations
- critical-detail reference crops
- prompt compilation and reference hashing
- task state, retry limits, and cache invalidation
- aspect-safe postprocessing and deterministic text overlays
- contact sheets, micro-detail comparison sheets, and QA gates

Never treat a prompt as proof that a detail was preserved. A P0/P1 detail needs an explicit QA result.

## Project setup

Locate a Python runtime with Pillow. Prefer the bundled workspace runtime when the system Python lacks it.

Initialize a versioned project:

```bash
python <skill-root>/scripts/lc_image_pipeline.py init \
  --project-dir <versioned-project-dir> \
  --project-id <stable-project-id>
```

Copy source images into `source/`, then edit `project_manifest.json`.

For each reference image, record:

- `id`: stable identifier
- `path`: project-relative or absolute path
- `role`: whole-product, edit-target, material-detail, component, or packaging reference
- `view`: front, rear, left, right, top, bottom, `45deg`, detail, or packaging
- `visual_quality`: `sufficient`, `marginal`, `insufficient`, or `unknown`
- `product_bbox_norm`: `[x, y, width, height]` inside the full image, normalized to `0..1`

Keep `concurrency` at `2`. Reduce it to `1` after rate limiting or repeated timeouts.

## Source-quality gate

Use the product's effective pixel area, not the full source-image resolution.

The preflight step calculates:

```text
effective_upscale_ratio = max(
  target_product_pixel_width / source_product_pixel_width,
  target_product_pixel_height / source_product_pixel_height
)
```

Interpret it as:

- `<=1.25`: sufficient for `original_pixels`
- `>1.25 and <=1.75`: marginal; do not use for macro material/detail claims
- `>1.75`: insufficient; block `pixel_composite`

Do not claim that resampling recovered real details. If a critical logo, port, label, scale, or texture is unreadable, request a close-up.

Choose `master_asset_mode`:

- `original_pixels`: use a clean real cutout or real product pixels
- `restored_master`: create one high-resolution product master, validate it once, then reuse it
- `blocked`: stop high-fidelity slots until better evidence exists

A restored master is a reconstruction, not verified truth. Never reconstruct text or a component that is not legible in any reference.

## Critical Detail Census

Inspect every product image at original resolution. Do not rely on a resized contact sheet.

Register functional and identifying micro-details:

- ports, buttons, indicators, knobs
- screws, rivets, clips, magnets
- vents, holes, cutouts
- hinges, joints, mounts
- seams, stitching, scales, logos, labels

Use priorities:

- `P0`: functional; missing, moved, closed, or redesigned means hard failure
- `P1`: identifying; obvious change means failure
- `P2`: minor appearance; reasonable lighting variation is allowed

Example detail:

```json
{
  "id": "usb_c_port",
  "name": "USB-C charging port",
  "priority": "P0",
  "status": "unknown",
  "evidence_level": "visual_confirmed",
  "visual_confirmation": "confirmed",
  "component": "rear edge of base",
  "description": "one small recessed USB-C opening with its surrounding seam",
  "shape": "horizontal rounded rectangle",
  "orientation": "parallel to the base edge",
  "color": "dark opening in the white shell",
  "locations": [
    {
      "reference_id": "product_rear",
      "view": "rear",
      "bbox_in_product_norm": [0.72, 0.81, 0.09, 0.035],
      "position_description": "rear-right edge of the base"
    }
  ],
  "visibility": {
    "01_main": "hidden",
    "02_size_or_components": "hidden",
    "03_primary_use_case": "hidden",
    "04_compatibility_or_installation": "required",
    "05_material_or_detail": "required",
    "06_storage_or_package": "hidden",
    "07_problem_solution": "optional",
    "08_a_plus": "optional"
  }
}
```

The bounding box is relative to the product box, not the full image.

The extractor marks a detail `unverifiable` when every supported crop has:

- longest visible edge below `32px`, or
- shortest visible edge below `8px`

Pixel size is necessary but not sufficient. `visual_confirmation` must also be `confirmed`; blur, glare, compression, or ambiguity keeps the crop unverifiable even when its bounding box is large.

Use `evidence_level=user_claim_only` with an empty `locations` array when the user says a component exists but no source image proves its view and position. Never guess normalized coordinates. Any job requiring that component is blocked until a readable close-up is supplied.

For every P0/P1 detail, `visibility` must explicitly cover every job. After inspecting all source images, set `critical_detail_census_completed=true`. Leaving the detail array empty is valid only when the completed census genuinely found no critical details.

If a detail is visible in only one view, do not force it into another view. Mark it `hidden` rather than moving it to a visible surface.

## Prompt preparation

Run:

```bash
python <skill-root>/scripts/lc_image_pipeline.py prepare \
  --manifest <project-dir>/project_manifest.json
```

This command:

- validates the manifest
- measures product effective pixels and safe upscale ratio
- writes `detail_refs/`
- blocks required but unverifiable P0/P1 details
- compiles one short prompt per job under `prompts/`
- hashes prompts and references for resume safety
- closes the manifest-wide `generation_gate` if any required job is blocked

Each prompt starts with:

- `Geometry Lock`
- `Material Lock`
- `Scene Scale Lock`
- `Critical Detail Lock`

Attach only the whole-product references and critical-detail crops listed in the job's `generation_reference_paths`.

When using built-in edit mode on a local image, view the edit target first so it is present in conversation context. Label every image role explicitly.

## Generation waves

Generate text-free bases only.

Wave 1:

- `01_main`
- the highest-value core scene, normally `03_primary_use_case`

Dispatch at most two built-in image calls concurrently. Inspect both anchors before continuing.

Do not start any generation while `generation_gate.status` is `closed`. Resolve the reported required job first; this prevents a mostly completed set from hiding a product-truth blocker.

Wave 2:

- dispatch the remaining jobs in pairs
- never generate optional bonus images by default
- skip jobs already in `qa_passed` with an unchanged prompt/reference hash

Use rendering modes strictly:

- `pixel_composite`: keep real or confirmed-master product pixels; generate around them
- `reference_edit`: change only the requested surroundings or local environment
- `reference_generate`: use only when complex scene interaction requires it

Prefer generating a compatible background and compositing a real product over repainting the full product.

Before each call, transition the job:

```bash
python <skill-root>/scripts/lc_image_pipeline.py transition \
  --manifest <manifest> --job <job-id> --status generating
```

After saving the raw output, transition it to `generated`.

The transition stores the prompt hash used for the attempt. A raw/final output generated from an older prompt cannot be accepted after the prompt, execution contract, or any referenced file changes.

## Postprocess and QA

Fill each job's `raw_output` and record `raw_product_bbox_norm` after inspecting the generated base. Postprocessing converts it to `output_product_bbox_norm` after any aspect-ratio padding; detail QA cannot locate a port reliably without one of these boxes.

For a perspective view where a detail no longer follows its source-relative product coordinates, record an exact full-output override:

```json
"detail_output_bbox_norms": {
  "usb_c_port": [0.68, 0.74, 0.035, 0.018]
}
```

Use the override only for cropping/QA. It does not authorize moving the detail.

Run local processing:

```bash
python <skill-root>/scripts/lc_image_pipeline.py finalize \
  --manifest <project-dir>/project_manifest.json
```

This command:

- converts outputs with uniform scaling only
- pads rather than distorts mismatched aspect ratios
- applies optional deterministic text overlays
- checks exact canvas size and main-image white corners
- produces `final/contact_sheet.png`
- produces `review/micro_detail_contact_sheet.png`
- writes `qa_report.json`

Open the micro-detail sheet at original detail. Compare each P0/P1 output crop with its reference for:

- existence
- exact supported position
- shape and orientation
- surrounding seam/edge
- unreasonable occlusion
- deletion, filling, relocation, or replacement

Record each verdict in the job:

```json
"detail_qa_results": {
  "usb_c_port": {
    "verdict": "pass",
    "notes": "present at the rear-right base edge; shape and orientation match"
  }
}
```

Allowed verdicts are `pass` and `fail`. Missing verdicts for required P0/P1 details keep the job in `repair_needed`.

Also record explicit semantic results:

```json
"semantic_qa_results": {
  "geometry": {"verdict": "pass"},
  "material": {"verdict": "pass"},
  "components": {"verdict": "pass"},
  "scene_scale": {"verdict": "pass"}
}
```

And policy results:

```json
"policy_qa_results": {
  "main_product_only": {"verdict": "not_applicable"},
  "claims": {"verdict": "pass"},
  "competitor_copy": {"verdict": "pass"},
  "text_readability": {"verdict": "not_applicable"}
}
```

Use `not_applicable` only where the runtime permits it: scene scale on the main image, main-product-only on non-main images, and text readability when there are no overlays.

Rerun `qa` after recording verdicts.

## Repair and resume

For each failed detail, QA creates `repairs/<job>__<detail>.txt`.

Use it as a precise-object edit:

- change only the missing/incorrect detail
- keep all other pixels, geometry, materials, scene, lighting, shadows, and framing unchanged
- attach the edit target and exact detail reference crop

Allow one quality repair per job. If it fails again, set the job to `blocked` and request a better close-up or human retouch.

Allow two transient retries after the initial generation attempt. Retrying a network/tool error must reuse the same prompt hash.

Never regenerate a job in `qa_passed` unless its prompt or reference hash changed.

## Delivery gate

Deliver only when:

- all required jobs are `qa_passed`
- no P0/P1 detail lacks an explicit pass
- no output exceeds the safe upscale policy for its rendering mode
- listing images are exactly `1600x1600`
- A+ uses the requested canvas, normally `970x600`
- geometry, materials, scene scale, components, claims, and text were reviewed
- contact sheets and `qa_report.json` exist

Run the final hard gate:

```bash
python <skill-root>/scripts/lc_image_pipeline.py delivery-check \
  --manifest <project-dir>/project_manifest.json
```

It verifies required job states, current prompt binding, final output hashes, and required artifacts, then writes `delivery_report.json`. A stale or modified output fails even if an older QA report says it passed.

If any required job is `blocked`, `repair_needed`, or `failed`, identify it as not production-ready. Do not describe the set as complete.
