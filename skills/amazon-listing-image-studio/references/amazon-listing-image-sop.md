# Amazon Listing Image Generation SOP

Use this SOP when you need the full execution logic behind `amazon-listing-image-studio`.

## 1. Inputs

Collect:
- Amazon URL or ASIN
- real product photos, supplier photos, packaging photos, or component photos
- target marketplace
- brand name if available
- whether the user wants strategy only or final image generation

Treat missing inputs as explicit risk. Do not silently invent facts that should have come from the listing or real images.

## 2. Product Research

Inspect the Amazon listing first when possible. Extract:
- title and product type
- dimensions, colors, variants, included parts
- compatibility and exclusions
- visible review pain points
- the practical job the product performs
- trust signals buyers need before purchase

Then inspect the real images. Identify:
- overall shape and silhouette
- exact proportions and relative part sizes
- material clues
- attachment points or moving parts
- cutouts, seams, ports, buttons, fasteners, textures, finish, and other visible identifying details
- scale
- packaging or storage method
- whether the product works alone or as part of a kit

Create a locked product-truth list from the real images before planning prompts. This list should capture the physical traits that must not change across any generated image.
Build a `Geometry Lock` from the same evidence:
- confirmed dimensions from the user or listing
- normalized `L:W:H` ratio when supported
- visible-axis ratio for the current view when full `L:W:H` is unsupported
- which reference images support each axis or detail
- which axes remain uncertain

Never invent hidden depth or thickness from a single angle. If the reference set cannot support a full `L:W:H` lock, keep the unsupported axis marked uncertain and ask for another view when needed.

Use the listing and images together. Do not trust either one in isolation when they conflict.

## 3. Product Understanding Checkpoint

Before planning images, write a structured checkpoint:

- What is the product exactly?
- Who buys it?
- What practical problem does it solve?
- What confirmed dimensions do we have?
- What normalized `L:W:H` ratio can we support, if any?
- Which axes remain uncertain?
- What physical details must render correctly?
- Which proportions and silhouette traits are locked?
- Which visible details must not be added, removed, or redesigned?
- What should be shown to build buyer trust?
- Which claims are safe, and which need proof?
- Which competitor patterns should be avoided?
- What is still uncertain?

Default behavior: stop here and ask the user to confirm or correct.

## 4. Image-System Design

Build a system, not eight unrelated pictures.

Each image needs:
- one visual lead
- one selling job
- one reason it exists in the sequence

Default sequence:

1. `01_main`
   White background, product only. Zero scene logic.
2. `02_size_or_components`
   Show measurements, variants, or included parts.
3. `03_primary_use_case`
   Show the product performing its most purchase-driving task.
4. `04_compatibility_or_installation`
   Explain fit, attachment, mounting, or tool relationship.
5. `05_material_or_detail`
   Explain physical quality through close-up evidence.
6. `06_storage_or_package`
   Show organization, carrying, packaging, or kit completeness.
7. `07_problem_solution`
   Resolve a pain point through before/after, workflow, or efficiency logic.
8. `08_a_plus`
   Premium summary visual for A+ content.

If the category does not need one slot, replace it rather than forcing a weak image.

Assign a render mode to each slot:
- `composite/edit` when the product body itself must remain exact and the surroundings can change
- `reference-constrained generation` when the scene matters more, but the product still must follow the `Geometry Lock`

Default guidance:
- `01_main`, `02_size_or_components`, `05_material_or_detail`, and `06_storage_or_package`: prefer `composite/edit`
- `03_primary_use_case`, `04_compatibility_or_installation`, `07_problem_solution`, and `08_a_plus`: use `reference-constrained generation` only if needed

## 5. Composition Rules

- Main image: white background, product only, no human, no prop, no text.
- Scene image: the product must be actively doing a believable job.
- Detail image: zoom in only on features that matter to conversion.
- Infographic image: keep copy short and readable.
- A+ image: more editorial, but still product-truthful.
- Never stretch, compress, slim, widen, elongate, shorten, or otherwise warp the product to fit the canvas.
- Never add, remove, simplify, relocate, or redesign visible product details unless the user explicitly confirmed the change.

When in doubt, simplify. Clutter is usually a sign that the selling job is unclear.

## 6. Anti-Copy Rules

Borrow only the competitor's information logic, never their exact execution.

Allowed inspiration:
- which buyer objection they tried to answer
- which feature needed explanation
- which usage moment was important

Not allowed:
- same layout
- same headline structure
- same badge stack
- same scene composition
- same brand terms or packaging cues

## 7. Prompt Writing

Prompts should encode:
- product truth
- buyer context
- the single selling job of the current image
- scene or composition constraints
- what must not appear
- size and framing requirements

Every prompt must explicitly say:
- include the `Geometry Lock` block with confirmed dimensions, normalized ratio when supported, reference-view anchors, and uncertain axes
- preserve the exact proportions, silhouette, and relative part sizes from the user images
- preserve all visible product details from the user images
- do not stretch, compress, slim, widen, or otherwise distort the product
- do not add, remove, or redesign components or visible details

If the tool supports image references, attach the real product images on every generation pass. Do not rely on text-only geometry reminders when the images themselves can be passed in.

Do not write one giant prompt for the full set unless the tool requires it. Prefer one prompt per image.

## 8. Postprocess

After generation:
- if the slot was `composite/edit`, confirm the real product body was preserved and only surroundings/layout changed
- resize listing images to exactly `1600x1600` with aspect ratio preserved; use padding or extra background instead of stretching the product
- resize or crop A+ to `970x600` unless told otherwise, while preserving product geometry and using recomposition or background extension instead of distortion
- check text readability
- check shape consistency across images
- reject any image where an unsupported axis was silently guessed or where the geometry lock was dropped from the prompt
- reject any image where the product proportions changed or any visible detail was added, removed, or redesigned
- remove or regenerate any hallucinated accessory, mount, button, or texture

## 9. Delivery

Deliver:
- final output folder
- image index with role of each image
- prompt pack
- review notes

Always state:
- which assets are production-ready
- which need human verification
- that text, dimensions, compliance statements, and IP risk still need final human review
