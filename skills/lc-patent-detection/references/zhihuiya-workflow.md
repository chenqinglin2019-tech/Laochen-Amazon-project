# 智慧芽 / PatSnap Workflow

Use 智慧芽 / PatSnap as the candidate-discovery layer. This file describes the search path and evidence that must be captured. It does not contain account details.

## Access

- Use the receiving user's own 智慧芽 / PatSnap account.
- If browser login is needed, the receiving user completes it.
- Do not save account names, passwords, cookies, private entry URLs, or screenshots of login pages in the skill.

## Search Path

1. Open 智慧芽 / PatSnap.
2. Enter image search.
3. Choose appearance/design search first for product-shape screening.
4. Upload the representative product image for the current row/product.
5. Run the search.
6. Save the all-results URL or task URL.
7. Filter or record results by requested country/jurisdiction when the interface supports it.
8. Capture each branch separately:
   - selected jurisdiction
   - search mode
   - result count when visible
   - top candidate numbers
   - candidate titles/articles
   - candidate countries
   - screenshots
9. Crop or capture candidate cards when possible.
10. Do not use the uploaded product image as final report evidence.

## Evidence To Save

For every product group, create one `evidence.json` with:

- product metadata
- Feishu record IDs when used
- source image path
- requested jurisdictions
- `zhihuiya_evidence`
- optional official verification attempts
- final risk value for Feishu writeback
- report paths

For each candidate, save:

- `record_number`
- `title_or_article`
- `country`
- `rank`
- `similarity_score` when visible or manually assessed
- `similarity_note`
- `screenshot_path`
- `official_verification.status`

## Official Verification Rule

Official verification is optional follow-up. It should improve confidence when available, but it must not block Feishu writeback.

Use these statuses:

- `verified`: official source confirms the material record.
- `skipped_not_found`: official source did not find the candidate.
- `access_limited`: official source could not be reached or required unavailable access.
- `not_checked`: no official verification was attempted.

When official verification is `skipped_not_found`, `access_limited`, or `not_checked`, continue with the Wisdom Bud evidence and write back the risk value.
