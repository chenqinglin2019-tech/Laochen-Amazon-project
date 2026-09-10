# Official imagegen Integration and Images 2.5 Prompt Profile

Use this guide when planning, compiling, generating or editing images. Load the official `imagegen` skill from the current available-skills catalog, then its `references/prompting.md`; read only applicable `product-mockup`, `ads-marketing` or edit examples from `references/sample-prompts.md`. Reuse material already read in the same turn. Missing official guidance blocks model-dependent steps, not independent maintenance. Do not copy or modify the official skill.

The Amazon skill owns product evidence, four locks, templates, copy routing and its existing production workflow. Official imagegen provides prompt-shaping and tool-use guidance inside that workflow. One agent uses both; this does not create another queue, review cycle, authentication step or output workflow. Follow the existing authentication and output instructions unchanged.

## Profile and compatibility

- New jobs set `prompt_profile: "images_2_5_v1"`. This selects a local prompt compiler, not a model/API parameter and not proof that the backend uses Images 2.5.
- Missing `prompt_profile` or explicit `legacy` retains legacy prompt bytes and generation fingerprints. Existing source-code hash checks may still require local layout/QA revalidation; this does not regenerate an unchanged base image or permit rewriting historical review hashes. Do not promise unchanged QA/layout cache-rule hashes. Explicitly upgrading a job invalidates only that job's affected generation/review dependencies; preserve historical attempts, adopted template snapshots and user libraries. Do not bump the global pipeline version.
- Official documentation updates alone do not invalidate existing compiled prompts or accepted images. Changes enter new jobs, or an explicitly revised job, through normal project inputs and preparation.
- Complete interpretation, augmentation, canvas resolution and normalization before prompt compilation/fingerprint binding. Send the resulting bound prompt unchanged; never run a second official augmentation pass after `transition`.

## One concise, resolved prompt

Use short labeled sections in this order; omit empty or irrelevant lines:

```text
Use case: <applicable official taxonomy slug>
Asset type: <Amazon image position and canvas purpose>
Primary request: <one image, generation or the specific edit>
Input images: <Image 1: role and permitted use; Image 2: role and permitted use>
Scene/backdrop: <evidence-compatible environment and support>
Subject: <verified product and included parts>
Composition/framing: <resolved viewpoint, product region and text region>
Lighting/mood: <light direction, reflections and contact shadows>
Materials/textures: <visible or verified properties only>
Text (verbatim): <exact approved headline and optional body, once each; native only>
Constraints: <four locks, protected content and allowed changes>
Avoid: <only relevant failure modes and unsupported content>
```

Classify reference-led product photography as `product-mockup`, complete photographic marketing posters as `ads-marketing`, and localized changes as the applicable edit category such as `precise-object-edit` or `text-localization`. A reference is not automatically an edit target: preserve a supplied base when the task is an edit; use reference evidence for a new composition when it is generation.

Resolve the active square/portrait/A+ variant and explicit overrides before writing composition instructions. Emit one agreed arrangement, not competing generic and selected left/right layouts. Remove only complete duplicate prompt fragments; retain distinct requirements and immutable template snapshots. Exact local copy remains in `layout`; native copy remains in `job.copy` and is never duplicated in design guidance.

Resolve inherited information-field positions into the current placement containers while retaining their tone and background treatment. In native typography, adapt an unchanged template reading order without discarding its content sequence; preserve an explicit project override. Set-level rhythm stays in planning. Local graphics remain in the adopted brief for local layout and review, outside the model's text-free-base prompt. Deduplicate identical product safeguards without removing unique design constraints.

Normalize detailed prompts without new creative requirements. For underspecified requests, add only useful photography/framing guidance supported by the product and selected design. Do not invent accessories, brand palettes, slogans, grain, wear, internal materials or claims. Describe concrete lighting and material response instead of repeating quality adjectives. An official example's “no logos” must not erase authentic product branding; “no added marketing text” does not mean removing real labels.

## Reference roles and four locks

Number inputs in exactly the order of the actual `generation_reference_paths`/tool attachments. Label whole-product evidence, detail evidence, edit target and style input separately; state how they interact. Include only necessary references. A design image supplies composition/style, never product identity, hidden features or marketing claims. Inspect a local edit target with `view_image` before editing and use only attachment mechanisms exposed by the current tool.

- **Geometry:** preserve physical structure, parts relationships, verified ratios and dimensions. Allow target-camera perspective, projected silhouette and physically plausible occlusion. Do not force the source photograph's two-dimensional outline onto another view, invent unknown surfaces or relocate a hidden port into view.
- **Material:** preserve known material identity, product color, finish and identifying texture. Allow scene-dependent illumination, reflections and shadows; photorealism is not permission to invent grain or replace a substrate.
- **Scene Scale:** specify the support, grip, attachment, relative scale and contact. Use only confirmed numerical dimensions; props cannot establish unknown specifications.
- **Critical Detail:** include this image's required/hidden P0/P1/P2 instructions and their actual readable sources. Required P0/P1 without evidence remains blocked or needs recomposition. Accepted generated assets retain real-photo dependencies and never become evidence for unknown facts.

## Generation and repair branches

- `pixel_composite`: any model request is for the required background only. Existing local product layers and protection checks preserve product pixels; “do not redraw” is not pixel compositing.
- `reference_edit`: resolve the edit target through the existing `pixel_source_reference_id` or the matching whole-product source; if ambiguous, supply an explicit source rather than choosing the first attachment. Name the defect/change region and content to retain. Repeat the relevant invariants on every repair.
- `reference_generate`: describe the supported target view and physical interaction, using all needed product evidence without hallucinating missing surfaces.
- Detail repair: select evidence using the same per-image source/visibility logic as initial generation. Do not emit empty detail references or replace an explicit source with an incompatible view. Fix the observed failure, not an imagined redesign.
- Native text repair: quote the corrected approved block, identify the failed text region and preserve correct blocks, product facts and scene. Stay within the existing per-image repair budget.
- Surface emboss: use the exact flat-letter guide and intended surface/perspective/lighting. Existing local adoption masks decide which returned pixels are used; do not invent a built-in mask parameter or promise that a model preserves all other pixels exactly.

For a new-profile model quality repair, run `plan` before dispatch. The compiler derives `job.prompt_edit={target_path,failures}` from the current bound `qa_report`, freezing the failed raw image as the edit target. This is derived repair context, not evidence for new product facts. Both the actual prompt and attachment fingerprints include that target and the observed failures; use the newly bound prompt and attachment order. Repair sidecar files are diagnostic suggestions and must not replace the bound prompt at tool invocation. Explicitly clear old `prompt_edit` when changing to a new composition or creating a fresh generation plan, so the next task is not accidentally constrained to the failed image.

The existing generation transition rejects an unprepared new-profile repair and asks for `plan`. A failed QA status alone does not rewrite the compiled prompt or generation fingerprint.

Use built-in `image_gen` by default. Batch means one existing queued call per image, not automatic CLI mode. CLI/API fallback requires the user's explicit choice and official fallback instructions. Tool capabilities, not prompt labels, determine valid model, size, quality, path and mask parameters. Immediately hand results back to the existing `ingest` flow; do not add a separate save/delivery sequence.

## Native poster text and actual verification

For this profile, `model_native_reason={kind:"native_poster",notes:"<reason>"}` permits one approved non-numerical headline and optional brief non-numerical body on an ordinary photographic poster. Factual benefits still require `job.claim_ids` and real evidence. `copy.headline/body` retain their existing 180/200-character schema limits; those limits are not target copy lengths. Do not abbreviate, rewrite, crop or omit approved words to fit.

Dimensions, numerical specifications, steps, FAQ, required limitations and precision marketing brand/Logo reproduction require `local_overlay` for the whole image. Main images use `none`; `pixel_composite` cannot use native text. Do not mix native marketing copy with local text/icons/panels. Change composition or use local typography if approved copy cannot fit; do not add image positions.

`artistic_lettering` and `integrated_material` remain decorative-title reasons. Surface-embedded 3D text additionally requires `embedding_decision`; it and local surface emboss remain limited to 1–5 words without numbers, body, brands or factual claims, with a credible receiving surface and lighting. Ordinary factual poster copy must not be reclassified as decorative text to bypass evidence checks.

Inspect original size, the 360px preview and actual encoded JPG. In `reviews.model_text_review`, transcribe the visible blocks and bounding regions and inventory unexpected small print/badges. Planned copy cannot substitute for observation. Existing local font/contrast automation does not certify model-generated glyphs.

Use the existing review `notes` to identify the actual final JPG/path/hash, glyph-core sampling method, measured minimum contrast (at least 4.5:1) and the evidence for headline/body readability at 360px (at least 18/12px). Exclude antialiased fringe, outline and shadow from glyph cores; a whole-box brightness average or visual guess is not contrast evidence. When the encoded artifact becomes available after an earlier review, inspect it, use `review-prepare --force` to obtain a new review packet, and submit the new evidence; never modify an already-submitted packet. Repeat measurement if the final encoded bytes change. Do not introduce an output stage or claim a new automatic check. If the existing readability/contrast requirements cannot be verified, use `local_overlay` and its normal text-free-base workflow, never duplicate text over a native poster.

Evaluate real visual performance using the next authorized production anchor. Maintenance fixtures validate compilation and compatibility, not model fidelity; no additional set of production images is required.
