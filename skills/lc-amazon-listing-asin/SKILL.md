---
name: amazon-listing-image-studio
description: Use when the user wants Codex to build a non-copycat Amazon image system from the user's own product photos, product facts, selling points, and either user-provided image planning ideas or a competitor Amazon listing URL/ASIN. If the user provides image generation planning or per-image design ideas, use those ideas directly and skip competitor teardown even when a competitor ASIN is also present. If only a competitor reference is provided as the strategy source, review competitor main images, gallery images, and A+ modules for strategy only. In both branches, preserve the user's real product proportions, structure, visible details, and dimension ratios from source references when available.
---

# Amazon Listing Image Studio

Use this skill when the user wants Amazon listing images built from real product inputs plus either the user's own image plan or competitor research, instead of generic prompt-only image generation.

Read `references/amazon-listing-image-sop.md` when:
- starting a new listing-image project,
- debugging poor image logic or messy scenes,
- the user asks for the workflow itself,
- you need the delivery checklist.

Read `references/category-playbooks.md` when:
- the product belongs to a specific category,
- the default 7+1 structure feels too generic,
- you need better scene logic or selling angles.

Read `references/web-chatgpt-prompt-template.md` when:
- handing the project to web ChatGPT / Image 2,
- creating an alternate prompt pack for A/B exploration.

## Goal

Produce a sellable Amazon image system that is based on the real product and guided by the correct strategy source:

- `7` listing images at `1600x1600`
- `1` A+ image, normally `970x600`
- a product-understanding checkpoint
- a strategy-source branch decision: user-planned branch or competitor-learning branch
- a competitor-image teardown covering main image, gallery, and A+ logic only when the competitor-learning branch is selected
- an image strategy table
- prompts for Codex image generation
- a second prompt pack for web ChatGPT / Image 2

The Codex-generated set is primary. Web ChatGPT output is secondary reference material unless the user explicitly says otherwise.

## Non-Negotiables

- Read the user-provided images before planning prompts or scenes.
- Ask for missing core inputs before planning: product images, product selling points or relevant facts, and at least one strategy source: either the user's image generation plan/design ideas or one competitor Amazon URL/ASIN.
- Treat the user's own product images as source truth for structure, proportions, materials, finish, included parts, and use context.
- Build a `Geometry Lock` before planning any image. If the user or listing provides numeric dimensions, normalize them into a reusable `L:W:H` ratio. If only some axes are supported, record only the supported ratios and explicitly mark unsupported axes as unknown.
- Never invent a hidden dimension from a single view. If depth, thickness, or another axis is not supported by the listing or reference images, ask for another image or carry the uncertainty forward instead of guessing.
- Lock the product's physical truth from the user images before prompt writing: exact proportions, silhouette, thickness, relative part sizes, attachment geometry, cutouts, seams, ports, buttons, fasteners, textures, finish, included parts, and any visible identifying details.
- Do not stretch, compress, widen, slim, elongate, shorten, thicken, or otherwise alter the product's real geometry. Scaling the whole product larger or smaller in the frame is allowed; changing its proportions is not.
- Do not add, remove, move, simplify, redesign, smooth out, sharpen, or "clean up" any visible product detail unless the user explicitly confirms that the source detail is wrong or flexible.
- Reuse the `Geometry Lock` in every checkpoint, prompt, review pass, and regeneration decision. It is not optional context.
- Treat the user's selling points, product facts, and design ideas as source truth for what should be emphasized.
- If the user provides image generation planning, per-image concepts, a storyboard, or concrete composition advice, select the user-planned branch. In that branch, do not decompose competitor ASINs or competitor images, even if a competitor reference is also present, unless the user explicitly asks to compare against it.
- If the user-planned branch is selected, use the user's image plan as the primary composition source. Fill gaps from product truth, buyer logic, Amazon policy, and category playbooks, not from competitor teardown.
- If no user image plan is provided and a competitor Amazon URL or ASIN is the strategy source, select the competitor-learning branch and inspect the listing before interpreting the market image logic.
- When the competitor-learning branch is selected, review competitor main image, gallery images, and A+ images for strategy only.
- Use the real images to understand shape, structure, scale, materials, accessories, and use environment. Do not clone the source photos.
- Prefer an edit/composite workflow over full re-render whenever exact product fidelity matters. Keep the real product as the anchor and generate the scene, background, callouts, or layout around it instead of repainting the product body from scratch.
- When converting outputs to square listing images or A+ sizes, preserve aspect ratio and product geometry. Use padding, extra background, or scene recomposition. Never distort the product to fill the canvas.
- Do not copy competitor layouts, text, badge systems, brand names, packaging, or distinctive compositions.
- Main image must stay Amazon-safe: white background, product only, no claims, no props, no scene, no people.
- Every image must have one visual lead and one selling job.
- A scene image must show the product doing one believable task, not just sitting in a pretty background.
- Do not state performance, certification, warranty, or safety claims unless the user provided support for them.
- Unless the user explicitly asks for immediate generation, stop after the Product Understanding Checkpoint and ask for confirmation.

## Operating Model

Think in four layers, in order:

1. **Product truth**
   Read the real images until you understand what the product is and what must be rendered correctly. Inspect a listing only when it is the selected strategy source or when the user says it is the user's own listing.
2. **Buyer logic**
   Identify who buys it, what job it performs, and what objections must be answered visually.
3. **Image system**
   Assign one selling job to each image in the 7+1 set.
4. **Prompt execution**
   Only after the first three layers are solid should you write generation prompts.

Do not jump from "here are some product photos" straight to generation.

## Required Inputs

Collect these inputs when the user wants a full Amazon image system:

- `Product images`: one or more real images of the user's product
- `Product information`: core selling points, product facts, included parts, constraints, target buyer, or image ideas
- `Strategy source`: either user-provided image generation planning/design ideas or one Amazon competitor listing URL/ASIN

If product images, product information, or both strategy-source options are missing, proactively ask for the missing items. Use a short checklist such as:

```markdown
Before I build the image system, please send:
- 1 or more real product images
- your core selling points, product facts, and any image ideas you already have
- either your image generation plan/design ideas, or one Amazon competitor listing link/ASIN for reference
```

## Strategy Source Branches

Choose exactly one branch before product understanding:

- `User-planned branch`: Use this when the user provides image generation planning, per-image concepts, a storyboard, composition suggestions, image-by-image selling jobs, or clear creative direction. This branch has priority over competitor input. Do not inspect or decompose competitor ASINs in this branch unless the user explicitly asks for a comparison.
- `Competitor-learning branch`: Use this only when the user has not provided a usable image plan and has provided a competitor Amazon URL or ASIN as the strategy source. Study the competitor's image logic for selling jobs and objection handling, then create original compositions.

If the user's image plan is partial, stay in the user-planned branch. Preserve the provided ideas and fill missing slots from product truth, buyer logic, Amazon-safe category patterns, and `references/category-playbooks.md`.

## Workflow

1. **Collect inputs**
   Gather:
   - local product image paths or uploaded product images
   - core selling points, product facts, included parts, target buyer, and any image design ideas or per-image plan
   - competitor Amazon listing URL or ASIN, if the user wants competitor-learning branch or comparison
   - target marketplace, brand name, and whether the user wants only a strategy or full generation

2. **Choose the strategy branch and ask for missing inputs**
   If product images, product information, or both strategy-source options are missing, ask for the missing items before doing strategy work. Do not silently proceed with major assumptions unless the user explicitly asks you to. If the user provided image generation planning/design ideas, select the user-planned branch and skip competitor teardown even if an ASIN is present. If no image plan is provided and a competitor URL/ASIN is present, select the competitor-learning branch.

3. **Inspect the user's product inputs**
   Extract product type, dimensions, included parts, compatibility notes, visible product details, likely buyer, real use environment, product constraints, and the core claims or themes the user wants emphasized. Create a locked list of non-negotiable physical traits: exact proportions, silhouette, relative part sizes, thickness, attachment points, cutouts, seams, buttons, ports, fasteners, textures, finish, and included parts.

4. **Build the Geometry Lock**
   Create a structured geometry block before any image planning:
   - confirmed dimensions from the user or listing
   - normalized `L:W:H` ratio when supported
   - visible-axis ratio for the reference view when full `L:W:H` is not supported
   - reference image anchors for front, side, top, `45deg`, detail, or packaging views when available
   - axes or details that remain uncertain
   - locked visible details that must remain unchanged
   If full `L:W:H` cannot be supported, say so explicitly and do not pretend otherwise.

5. **Use the selected strategy source**
   In the user-planned branch:
   - normalize the user's image plan into image slots, selling jobs, visual leads, render modes, and must-avoid constraints
   - preserve the user's intended composition unless it conflicts with product truth, Amazon policy, or clear conversion logic
   - fill missing slots from product truth, buyer logic, and category playbooks
   - do not inspect or summarize competitor image logic

   In the competitor-learning branch:
   - review the competitor's main image, gallery images, and A+ images
   - extract what selling jobs each image is trying to do
   - extract what visual hierarchy or sequencing seems effective
   - identify what objections they answer well
   - identify what gaps, weak angles, or stale patterns should be improved in our version
   - identify what must not be copied

6. **Write a Product Understanding Checkpoint**
   Output:
   - product type
   - buyer
   - primary use
   - confirmed dimensions
   - normalized `L:W:H` ratio when supported
   - unsupported or uncertain axes
   - physical structures that must render correctly
   - locked proportions and silhouette that must not change
   - visible details that must not be added, removed, or redesigned
   - included parts and why they matter
   - trust-building facts to show
   - high-risk claims to avoid
   - user-requested selling angles or design ideas
   - selected strategy branch and why
   - user image plan to preserve, when using the user-planned branch
   - competitor image logic worth learning from, only when using the competitor-learning branch
   - competitor logic to avoid copying, only when using the competitor-learning branch
   - uncertain facts needing confirmation

7. **Wait for confirmation**
   If the user did not explicitly skip confirmation, stop and ask for confirmation or corrections.

8. **Choose category strategy**
   Route the product into the closest playbook from `references/category-playbooks.md`. Adapt the default 7+1 structure if the category requires it.

9. **Plan the image system**
   Create an image strategy table with one visual lead, one selling job, and one render mode per image. In the user-planned branch, the user's plan controls the composition and sequencing unless it conflicts with product truth, Amazon policy, or clear conversion logic. In the competitor-learning branch, use competitor research to sharpen sequencing and objection handling, but keep the execution original:
   - `01_main`
   - `02_size_or_components`
   - `03_primary_use_case`
   - `04_compatibility_or_installation`
   - `05_material_or_detail`
   - `06_storage_or_package`
   - `07_problem_solution`
   - `08_a_plus`
   Default render-mode guidance:
   - Prefer `composite/edit` for `01_main`, `02_size_or_components`, `05_material_or_detail`, and `06_storage_or_package`
   - Use `reference-constrained generation` only when the surrounding scene matters more than reusing the original product cutout, and still keep the `Geometry Lock` in the prompt

10. **Write prompts**
   Write fresh prompts from the current product facts. Never reuse a prompt from another product. Every prompt must begin with a `Geometry Lock` block that carries forward the supported dimensions, normalized ratio, supported view anchors, uncertain axes, and locked visible details. Every prompt must explicitly state that the exact product proportions, structure, and visible details from the user images are locked and must not be altered.

11. **Generate and postprocess**
   Generate separate images when possible. When a slot is marked `composite/edit`, preserve the original product body and modify only the surroundings, labels, or layout. Resize listing images to exactly `1600x1600` and A+ to the requested module size while preserving aspect ratio. If a square or wide canvas needs adjustment, extend background or recompose the scene instead of stretching the product. If any output changes product proportions, structure, or visible details, reject it and regenerate. If text is garbled, regenerate or simplify.

12. **Deliver**
   Return image paths, a review contact sheet when available, prompt pack, and a short note on what still needs human review.

## Product Understanding Checkpoint Template

```markdown
## Product Understanding Checkpoint
- Product:
- Buyer:
- Primary use:
- Confirmed dimensions:
- Normalized L:W:H ratio:
- Unsupported / uncertain axes:
- Reference image anchors:
- Real use environment:
- Must-render structures:
- Locked proportions / silhouette:
- Visible details that must not change:
- Included parts:
- Trust-building facts to show:
- Main objections to answer:
- Claims to avoid:
- User selling points / ideas to preserve:
- Selected strategy branch:
- User image plan to preserve:
- Competitor image logic worth learning from:
- Competitor logic to avoid:
- Must-not-generate list:
- Uncertain facts needing confirmation:
```

## Image Strategy Table Template

```markdown
## Image Strategy Before Generation
| Image | Visual lead | Selling job | Render mode | Real task / scene | Must avoid |
|---|---|---|---|---|---|
| 01 Main | | | composite/edit | Product only | |
| 02 Size / Components | | | composite/edit | | |
| 03 Primary Use | | | reference-constrained generation | | |
| 04 Compatibility / Install | | | reference-constrained generation | | |
| 05 Detail / Material | | | composite/edit | | |
| 06 Storage / Package | | | composite/edit | | |
| 07 Problem / Solution | | | reference-constrained generation | | |
| 08 A+ | | | reference-constrained generation | | |
```

## Prompting Rules

- Write prompts from the current product facts, not from a saved template.
- Start every prompt with a `Geometry Lock` block that includes confirmed dimensions, normalized ratio when supported, visible-view anchors, uncertain axes, and locked details.
- Preserve physical truth: exact proportions, silhouette, thickness, relative part sizes, attachment points, included parts, visible details, and real usage logic.
- Put a hard negative constraint in every prompt that says the product must keep the exact proportions and visible details from the user images.
- If the tool supports image references, always attach the relevant product images. Do not rely on text-only geometry descriptions when source images are available.
- If full `L:W:H` is unsupported, say so explicitly and lock only the supported view geometry. Ask for another view instead of guessing depth.
- Never use non-uniform scaling, stretching, squeezing, slimming, widening, or other warping to fit the canvas.
- Do not add, remove, relocate, simplify, redesign, or guess at visible product details. If a detail is unclear, flag it for confirmation instead of inventing it.
- For high-fidelity slots, prefer "keep the real product unchanged and generate around it" over "redraw the product from scratch."
- Carry the user's provided selling points and image ideas forward unless they conflict with Amazon policy, product truth, or clear conversion logic.
- In the user-planned branch, do not add competitor-derived visual logic unless the user explicitly asks for it.
- In the competitor-learning branch, use competitor images to understand what selling jobs the market is trying to solve, not to copy layouts or compositions.
- Keep text overlays short. If the image model struggles with text, reduce text and preserve the visual logic.
- Prefer simple, believable scenes over dramatic but fake scenes.
- If the user asks for web ChatGPT / Image 2 prompts too, create a second prompt pack that clearly says "use references to understand the product, not to copy the layout."

## Final Validation

Before final delivery, confirm:

- the product-understanding checkpoint was confirmed or intentionally skipped by user request
- missing required inputs were requested before planning, or the user explicitly waived them
- the selected strategy branch is recorded before planning
- if the user provided image generation planning/design ideas, the user-planned branch was used and competitor teardown was skipped unless the user explicitly asked for comparison
- if no user image plan was provided, the competitor-learning branch used the competitor main image, gallery, and A+ for strategy only, not copying
- the `Geometry Lock` exists and was carried from research into checkpoint, strategy, prompts, and review
- any normalized `L:W:H` ratio used in prompts came from user/listing dimensions or supported reference views, not from guessing
- unsupported axes remained marked uncertain instead of being invented
- every image has one visual lead and one selling job
- the main image is Amazon-safe
- listing images are `1600x1600`
- the A+ image exists at the requested size
- composite/edit slots kept the original product body geometry and visible details intact
- square and A+ outputs preserve product aspect ratio; any canvas fitting was done with padding, background extension, or scene recomposition rather than product distortion
- scenes are realistic for the category
- product structure is consistent across the set
- no image shows stretched, squashed, slimmed, widened, elongated, shortened, thickened, or otherwise distorted product geometry
- no visible product detail, component, or included part was added, removed, moved, or redesigned without explicit user confirmation
- competitor-derived logic, if used, came only from the competitor-learning branch and was used for strategy only, not copied
- no copied brand, logo, text, or layout remains
- claims are grounded in visible or confirmed facts
- any risky text, dimensions, or compliance statements are flagged for human review
