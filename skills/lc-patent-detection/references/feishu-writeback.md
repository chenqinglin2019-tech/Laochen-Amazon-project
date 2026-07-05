# Feishu / Lark Writeback

This workflow writes results to the receiving user's own Feishu/Lark Bitable. It must be configured at runtime.

## Required Runtime Configuration

Use command arguments or environment variables:

- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_APP_TOKEN`
- `FEISHU_TABLE_ID`
- `FEISHU_RISK_FIELD`, default `专利`
- `FEISHU_PDF_FIELD`, default `专利pdf`

The user can also provide a tenant access token directly:

- `FEISHU_TENANT_ACCESS_TOKEN`

Do not store these values in the skill.

## Writeback Rule

For every completed product group:

1. Generate `evidence.json`.
2. Generate `report.md`, `findings.csv`, and optionally `report.pdf`.
3. Upload `report.pdf` as a Bitable file when a PDF field is configured.
4. Update every target `record_id` with:
   - risk field: `高`, `中`, or `低`
   - PDF field: Bitable attachment token when available
5. Save writeback response to task output.

## Official Source Skip Rule

If official source lookup fails, cannot find the candidate, or is blocked:

- keep the Wisdom Bud candidate evidence
- mark official status as `skipped_not_found` or `access_limited`
- do not block Feishu writeback

## Safety Rule

Before calling the write API, confirm:

- target `record_id` is from the current task
- risk value is one of the configured allowed values
- report PDF exists when uploading a PDF
- credentials come from runtime config, not skill files
