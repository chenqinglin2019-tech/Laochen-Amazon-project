# lc-amazon-listing-asin

Codex skill for generating Amazon listings from a competitor ASIN set and a
seller's own product images or description.

The skill guides an agent through:

- product profile extraction
- SellerSprite keyword expansion through an authorized backend
- keyword filtering and SEO tagging
- Rufus buyer-question collection through an authorized backend
- Amazon-compliant listing generation
- image plan and A+ content planning
- a self-contained HTML reasoning report

## Safe Public Package

This public package intentionally does not include:

- backend tokens
- private backend URLs
- local credential files
- compiled `laochen-cli-*` binaries

`config.json` is committed with empty backend fields. Configure credentials only
in your local environment, and do not commit them back to GitHub.

## Files

- `SKILL.md` - Codex skill entrypoint
- `INSTRUCTIONS.md` - full platform-neutral workflow
- `AGENTS.md` - generic agent entrypoint
- `knowledge/distilled/` - listing writing rules
- `knowledge/examples/` - good/bad examples
- `tools/listing_report_template.html` - local HTML report template
- `tools/bin/` - place authorized CLI binaries here locally

## Local Setup

1. Copy an authorized `laochen-cli-*` binary into `tools/bin/`.
2. Set local credentials without committing them:

```bash
export LAOCHEN_BACKEND_URL="https://your-backend.example.com"
export LAOCHEN_BACKEND_TOKEN="your-token"
```

3. On macOS, run:

```bash
./tools/bin/install.sh
```

4. Read `INSTRUCTIONS.md` before running a listing task.

## Security Notes

Never commit real tokens, cookies, API keys, or private backend URLs. If a token
is accidentally exposed, revoke it immediately before continuing work.
