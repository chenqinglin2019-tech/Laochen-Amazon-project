# Amazon Listing Image Strategy SOP

Use this reference for buyer logic, image-slot strategy, and product-understanding output. Use `runtime-pipeline.md` for execution, state, detail crops, retries, postprocessing, and QA.

## 1. Inputs and branch

Collect:

- real product, component, detail, and packaging photos
- confirmed facts, selling points, included parts, constraints, and target buyer
- target marketplace
- either the user's image plan or one competitor URL/ASIN

Select one branch:

- `user_planned`: use when the user specifies the purpose, content, composition, or sequence of at least one image; preserve that partial or complete plan and fill only its gaps
- `competitor_learning`: study only selling jobs, objections, and sequence; do not copy layout, wording, badges, branding, packaging, or composition

## 2. Product understanding

Inspect real product images at original resolution. Record:

- product type, buyer, primary job, and use environment
- confirmed dimensions and supported ratios
- supported front/rear/side/top/bottom/45-degree views
- silhouette, thickness, relative part sizes, attachment geometry, and included parts
- materials, finish, color, texture, transparency, and light behavior
- ports, buttons, indicators, screws, holes, clips, seams, labels, and other micro-details
- known and unknown facts
- claims that require proof

Build Geometry, Material, Scene Scale, and Critical Detail locks. Never infer hidden product truth.

## 3. Product Understanding Checkpoint

Output:

```markdown
## Product Understanding Checkpoint
- Product:
- Buyer:
- Primary use:
- Confirmed dimensions and ratios:
- Supported views:
- Unsupported axes / surfaces:
- Geometry Lock:
- Material Lock:
- Scene Scale Lock:
- P0/P1 Critical Detail Lock:
- Source quality and safe enlargement:
- Master asset mode:
- Included parts:
- Trust-building facts:
- Claims to avoid:
- Selected strategy branch:
- User plan to preserve:
- Competitor logic worth learning from:
- Must-not-generate list:
- Blocking uncertainties:
```

Under `risk_gated_auto`, stop only when a blocking uncertainty could change product truth, a restored master needs confirmation, or a required P0/P1 detail is unverifiable.

## 4. Image system

Default sequence:

1. `01_main`: exact product on white; no text or props
2. `02_size_or_components`: confirmed dimensions or confirmed set contents
3. `03_primary_use_case`: highest-value believable task
4. `04_compatibility_or_installation`: confirmed fit, connection, mounting, or workflow
5. `05_material_or_detail`: real construction evidence from a verified crop/master
6. `06_storage_or_package`: confirmed organization, carrying, package, or set completeness
7. `07_problem_solution`: resolve one buyer objection
8. `08_a_plus`: wide premium summary grounded in confirmed facts

Replace a weak slot when the category does not need it. Every image must have one visual lead and one selling job.

For every slot, record:

- selling job
- supported view
- render mode
- source references
- required and hidden critical details
- product output bounding box
- scene scale and support/contact logic
- facts and claims allowed in deterministic overlays

## 5. Composition and anti-copy rules

- Show a believable task, not decorative staging.
- Keep props subordinate to the product and physically plausible in size.
- Keep connection, installation, support, contact shadow, and occlusion physically coherent.
- Use padding, background extension, or recomposition instead of product distortion.
- Borrow only the objection being answered from competitors.
- Never copy a competitor's layout, headline, badge stack, scene, packaging cue, brand term, or distinctive execution.

## 6. Prompt strategy

Create one prompt per image from the manifest-generated lock blocks.

- Attach only references relevant to the current view.
- Attach a separate crop for every required P0/P1 detail.
- Mark details hidden from the view so the model does not relocate them.
- Ask for text-free bases.
- Prefer `pixel_composite`, then `reference_edit`, then `reference_generate`.
- Use targeted single-change edits for repairs; never rewrite the whole prompt and regenerate the full set.

## 7. Delivery checklist

- Required inputs and strategy branch recorded
- Source-quality gate completed
- Critical Detail Census explicitly completed after original-resolution inspection
- Every P0/P1 visibility rule covers every job
- Restored master confirmed when used
- Four locks present in every prompt
- Every required P0/P1 detail explicitly passed
- No hidden detail was moved into view
- No unsupported accessory, port, texture, label, or claim added
- Main image is product-only on pure white
- Listing images are `1600x1600`
- A+ matches requested size
- Text comes from deterministic postprocessing
- Manifest, QA report, contact sheet, and micro-detail sheet delivered
- Runtime `delivery-check` passed against current prompt and output hashes
- Human review risks stated for dimensions, compliance claims, and IP
