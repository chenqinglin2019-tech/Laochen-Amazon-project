# Web ChatGPT / Image 2 Prompt Template

Use this when you want web ChatGPT / Image 2 to create a secondary reference set, not a copied clone of marketplace images.

## Usage Rules

- Replace every placeholder with current product facts.
- Keep the product facts grounded in the user's facts, selected strategy source, and real images.
- Preserve the exact product proportions, structure, and visible details from the real images.
- If numeric dimensions are known, preserve the normalized `L:W:H` ratio from those dimensions. If any axis is unsupported, keep it marked uncertain instead of guessing it.
- If using the user-planned branch, tell web ChatGPT to follow the user's image plan and not introduce competitor-derived composition logic.
- If using the competitor-learning branch, tell web ChatGPT to learn from the competitor references without copying layouts or text.
- Tell web ChatGPT explicitly that canvas fitting must happen through padding, background extension, or scene recomposition, never by stretching or warping the product.
- Prefer using the real product as a reference anchor or composite source for high-fidelity images instead of repainting the product body from scratch.
- If the product category is obvious, inject category-specific scene logic from `category-playbooks.md`.

## Master Prompt Template

```markdown
I am providing real product images and this strategy source: [USER IMAGE PLAN or COMPETITOR REFERENCE].

Strategy branch:
- [User-planned branch: follow the user's image generation plan/design ideas directly. Do not analyze or borrow competitor image logic unless I explicitly ask for comparison.]
- [Competitor-learning branch: use the competitor reference only to understand selling jobs, objection handling, and market image logic. Do not copy exact layouts, text, brand names, badge systems, packaging, composition, or visual style.]

Use the real product images to understand the product's structure, size, materials, included parts, and real usage context. Preserve the exact product proportions, silhouette, relative part sizes, and visible details from the real product images. Preserve the normalized `L:W:H` ratio from confirmed dimensions when available. If an axis is unsupported by the user facts, listing, or reference views, keep it uncertain instead of inventing it. Do not stretch, compress, slim, widen, elongate, shorten, or otherwise distort the product. Do not add, remove, relocate, simplify, or redesign any visible product detail or component.

Task:
Create a new Amazon image set for [PRODUCT TYPE].

Product truth:
- [FACT 1]
- [FACT 2]
- [FACT 3]
- [FACT 4]

Geometry Lock:
- Confirmed dimensions: [L x W x H or N/A]
- Normalized L:W:H ratio: [RATIO or N/A]
- Reference image anchors: [front / side / top / 45deg / detail]
- Unsupported or uncertain axes: [NONE or DETAILS]

Locked physical traits that must not change:
- [PROPORTION / SILHOUETTE FACT]
- [VISIBLE DETAIL FACT]
- [INCLUDED PART / ATTACHMENT FACT]

Buyer context:
- Buyer: [WHO BUYS IT]
- Use environment: [WHERE IT IS USED]
- Core job: [WHAT PROBLEM IT SOLVES]
- Main objection to answer visually: [OBJECTION]

User image plan to preserve:
- [IMAGE PLAN ITEM or N/A]
- [IMAGE PLAN ITEM or N/A]

Output required:
- 7 square Amazon listing images at 1600x1600
- 1 A+ style image

Render-mode guidance:
- Prefer composite/edit for main, size/components, detail/material, and storage/package images so the real product body stays unchanged.
- Use reference-constrained generation only when the scene must change substantially, and still keep the product locked to the Geometry Lock.

Image system:
1. Main image: white background, product only, no text, no scene.
2. Size/components image: explain dimensions, variants, or included parts.
3. Primary use image: show the product doing its most important real task.
4. Compatibility/installation image: explain fit, mounting, connection, or workflow.
5. Detail/material image: close-up evidence of construction quality or feature logic.
6. Storage/package image: show storage, carrying, packaging, or set completeness if relevant.
7. Problem/solution image: show pain point, workflow improvement, before/after, or efficiency logic.
8. A+ image: premium wide image combining product, context, and concise value.

Style:
Photorealistic product photography mixed with clean Amazon infographic structure. Keep text short, readable, and secondary to the product. Use original composition. Avoid fake certifications, impossible scenes, over-claims, copied layouts, warped product geometry, or altered product details.
```

## Per-Image Prompt Template

```markdown
Create Amazon listing image [IMAGE NUMBER] for [PRODUCT TYPE].

Selling job:
[ONE SELLING JOB]

Render mode:
[composite/edit or reference-constrained generation]

Product facts that must stay accurate:
- [FACT]
- [FACT]

Geometry Lock:
- Confirmed dimensions: [L x W x H or N/A]
- Normalized L:W:H ratio: [RATIO or N/A]
- Reference image anchors: [front / side / top / 45deg / detail]
- Unsupported or uncertain axes: [NONE or DETAILS]

Locked physical traits that must remain unchanged:
- [PROPORTION / SILHOUETTE FACT]
- [VISIBLE DETAIL FACT]

Scene/composition:
- [WHAT MUST BE SHOWN]
- [WHAT THE PRODUCT IS DOING]
- [WHAT SHOULD STAY SIMPLE]

Do not show:
- [CLAIM OR VISUAL TO AVOID]
- [COMPETITOR-LIKE ELEMENT TO AVOID]
- any altered proportions, warped geometry, or modified product details

Style:
Clean, photorealistic, conversion-focused Amazon visual. Readable text only if necessary.
```
