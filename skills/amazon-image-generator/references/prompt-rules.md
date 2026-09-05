# Prompt Rules

Use these rules when helping the user refine `title` and `desc` before submitting the FeiyuShentu task.

## Product Description

- Keep the product type, materials, color, size, and core use cases explicit.
- Include practical Amazon shopping details when available: capacity, dimensions, included parts, compatibility, and target users.
- Do not invent certifications, performance claims, warranties, or brand names.
- Do not add medical, safety, or regulated claims unless the user provided them.

## Image Intent

- The initial skill scope does not split images into Amazon subtypes.
- If the user asks for a more specific visual direction, fold it into `desc` as product and scene guidance.
- Prefer clear product visibility, realistic lighting, clean commercial composition, and marketplace-appropriate styling.

## Text In Images

- Respect the `language` choice from `fixedSetting`.
- If the user chooses `No Text`, avoid requesting text in the image.
- If text is requested, keep it short and grounded in the provided product facts.

## Compliance

- Avoid fake logos, fake badges, fake reviews, fake awards, and unverifiable claims.
- Do not imply that generated images are official Amazon assets.
- Keep generated imagery consistent with the reference product image.
