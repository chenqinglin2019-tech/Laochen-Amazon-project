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
- local credential files

`config.json` is committed with the backend URL and an empty token. Configure the
token only in your local environment, and do not commit it back to GitHub.

## Files

- `SKILL.md` - Codex skill entrypoint
- `INSTRUCTIONS.md` - full platform-neutral workflow
- `AGENTS.md` - generic agent entrypoint
- `knowledge/distilled/` - listing writing rules
- `knowledge/examples/` - good/bad examples
- `tools/listing_report_template.html` - local HTML report template
- `tools/bin/` - authorized CLI binaries

## Local Setup

1. Set the token locally without committing it:

```bash
export LAOCHEN_BACKEND_TOKEN="your-token"
```

2. On macOS, run:

```bash
./tools/bin/install.sh
```

3. Read `INSTRUCTIONS.md` before running a listing task.

## Security Notes

Never commit real tokens, cookies, API keys, or local credential files. If a
token is accidentally exposed, revoke it immediately before continuing work.
