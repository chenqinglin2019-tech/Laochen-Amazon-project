---
name: lc-amazon-data-crawl
description: Run and maintain a reusable Amazon data crawler for front-end product collection with SellerSprite-enriched fields. Use when the user needs to crawl Amazon keyword search result pages with selectable sort orders, Best Sellers/New Releases category ranking nodes, storefront product lists with selectable sort orders and up to 20 pages per store, or image-search similar competitor counts/details; also use when packaging this crawler for another Codex installation.
---

# Lc amazon Data Crawl

Use this skill to create and operate a local Amazon crawler runner. The bundled scripts support:

- `keyword_search`: crawl Amazon search results from a keyword file, with sort choices such as Featured, Newest Arrivals, Best Sellers, and price/review sorts.
- `storefront`: crawl Amazon storefront product lists, usually with `Newest Arrivals` or `Best Sellers`, up to 20 pages per store/sort.
- `bsr_category`: crawl a single Amazon ranking/listing URL through the unified front crawler.
- `category-rank`: crawl a ranking category node recursively, including child category nodes.
- `image-competitor`: crawl Amazon image-search similar products and optionally compare/count competitors.

## Cloud Auth Gate

Before editing configs, installing dependencies, opening Chrome, running a dry-run, or starting any crawl, the Laochen cloud auth gate must pass.

This gate only verifies whether the current user may use this skill. It does not change the crawler logic and does not replace the user's Amazon, Chrome, SellerSprite, OpenAI, or local browser setup.

The user's key goes in `config.json`:

```json
{
  "backend_url": "https://mcp.yixunkuajing.com",
  "backend_token": ""
}
```

Never print or reveal the full key.

On macOS, before the first run, silently execute this once from the skill or generated runner root:

```bash
xattr -dr com.apple.quarantine tools/bin 2>/dev/null || true
chmod +x tools/bin/* 2>/dev/null || true
```

If auth fails, if `backend_token` is missing, or if the auth binary is unavailable, stop immediately. Do not inspect inputs, edit configs, run `install`, open Chrome, run dry-run, or start crawling. Use only this safe message:

```text
云端鉴权未通过，本轮不继续执行。
```

If auth passes, continue the normal local crawler workflow. `scripts/setup_runner.sh` enforces this gate before creating a runner, and the generated runner enforces the same gate before every runner command.

## First Step

If the current workspace does not already contain a runner, create one from this skill:

```bash
SKILL_DIR="/path/to/lc-amazon-data-crawl"
bash "$SKILL_DIR/scripts/setup_runner.sh" ./lc-amazon-data-crawl-runner
```

Then use the generated runner folder for all task-specific config edits and executions.

## Runner Commands

Run these from the generated runner folder:

```bash
./lc-amazon-data-crawl.sh install
./lc-amazon-data-crawl.sh doctor
./lc-amazon-data-crawl.sh amazon-front-dry-run --config config/amazon_front_keyword_search.json
./lc-amazon-data-crawl.sh amazon-front-run --config config/amazon_front_keyword_search.json
./lc-amazon-data-crawl.sh amazon-front-run --config config/amazon_front_storefront.json
./lc-amazon-data-crawl.sh category-rank-run --config config/category_rank_crawler.json
./lc-amazon-data-crawl.sh image-competitor-run --config config/amazon_image_competitors.json
```

Always run the matching `*-dry-run` command before a real run after editing config or input files.

## Configuration Rules

Read `references/configuration.md` when creating or editing configs. The key operational rules are:

- Replace example input files under `inputs/` with the user's real Excel/CSV files, or point config paths to the real files.
- For keyword search sorting, set `keyword_sort_orders` to any of: `Featured`, `Price: Low to High`, `Price: High to Low`, `Avg. Customer Review`, `Newest Arrivals`, `Best Sellers`.
- For storefront crawling, set `store_sort_orders` with the same labels and set `store_page_limit` from 1 to 20.
- Prefer `browser_mode: "launch"` with a dedicated `chrome_user_data_dir` when creating a new runner.
- If using SellerSprite enrichment, fill `extension_path` with the local SellerSprite Chrome extension folder, or leave it empty and use a Chrome profile where the extension is already installed.
- Keep `page_scroll_before_extract: true` so each visible Amazon page is scrolled downward before extraction; this triggers lazy-loaded product cards and SellerSprite-injected fields before records are written.
- Do not use legacy third-party browser-container workflows; this skill is only for normal Chrome/Selenium Amazon front-end crawling.

## Long-Running Crawl Supervision

For real runs, monitor terminal output and the `outputs/<job_id>/state.json` file:

- If no new records, state updates, or browser actions happen for more than 3 minutes, report the current reason to the user.
- If Amazon or SellerSprite needs manual action, tell the user exactly which browser window/page is waiting.
- Before writing records, the crawler scrolls the page until the Amazon/product DOM and SellerSprite/plugin DOM stop changing, then waits for SellerSprite data to stabilize.
- The scripts include retry/relaunch behavior for SellerSprite data stalls: five plugin retries with random 10-20 second waits, then browser relaunch waits of 5 minutes and 10 minutes for later retry rounds when configured.

## Output Expectations

Outputs are written under `outputs/<job_id>/`.

- Unified front crawler writes `records.jsonl`, `state.json`, optional `failures.jsonl`, and `dedup_total.xlsx`.
- Category-rank crawler writes `records.jsonl`, `state.json`, optional `failures.jsonl`, and `total_<job_id>_merged.xlsx`.
- Image competitor crawler writes mode-specific JSONL files and an Excel result ending in `_相似竞品数量.xlsx` or a detailed competitor workbook.

## Maintenance

When updating this skill, update the bundled scripts in `scripts/`, templates in `assets/config/`, and this `SKILL.md` together. Validate with:

```bash
python3 /path/to/skill-creator/scripts/quick_validate.py /path/to/lc-amazon-data-crawl
```
