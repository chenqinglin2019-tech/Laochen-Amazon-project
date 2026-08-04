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

This gate only verifies whether the current user may use this skill. It does not change the crawler logic and does not replace the user's Amazon, Chrome, SellerSprite, Doubao, or local browser setup.

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

Setup creates `config/doubao_embedding_vision.json` from an empty public
example, protects it with mode `0600` where supported, and adds it to the
runner `.gitignore`. It never overwrites that file on later setup runs. Before
an image-competitor embedding run, the user must put their own Volcengine Ark
API key in that local file. Never ask the user to paste the key into chat.

## Runner Commands

Run these from the generated runner folder:

```bash
./lc-amazon-data-crawl.sh install
./lc-amazon-data-crawl.sh doctor
./lc-amazon-data-crawl.sh amazon-front-dry-run --config config/amazon_front_keyword_search.json
./lc-amazon-data-crawl.sh amazon-front-run --config config/amazon_front_keyword_search.json
./lc-amazon-data-crawl.sh amazon-front-run --config config/amazon_front_storefront.json
./lc-amazon-data-crawl.sh category-rank-run --config config/category_rank_crawler.json
./lc-amazon-data-crawl.sh image-competitor-dry-run --config config/amazon_image_competitors.json
./lc-amazon-data-crawl.sh image-competitor-run --config config/amazon_image_competitors.json
./lc-amazon-data-crawl.sh cdp-browser-start --config config/amazon_front_keyword_search.json
./lc-amazon-data-crawl.sh sellersprite-check --config config/amazon_front_keyword_search.json
```

Always run the matching `*-dry-run` command before a real run after editing config or input files.

## Configuration Rules

Read `references/configuration.md` when creating or editing configs and
`references/delivery-locations.md` before changing delivery behavior. The key
operational rules are:

- Replace example input files under `inputs/` with the user's real Excel/CSV files, or point config paths to the real files.
- Keep `delivery_location_enabled: true`,
  `delivery_locations_file: "config/amazon_delivery_locations.json"`, and
  `delivery_location_timeout: 20` in crawler configs. Before extraction, the
  crawler confirms the marketplace-specific delivery city/postal code. If
  automatic and manual confirmation both fail, it stops without writing that
  page.
- Delivery selection updates Amazon cookies in the dedicated Chrome Profile
  and can change price, stock, shipping promises, and search results. A new
  browser driver or exact Amazon domain must confirm the address again.
- For keyword search sorting, set `keyword_sort_orders` to any of: `Featured`, `Price: Low to High`, `Price: High to Low`, `Avg. Customer Review`, `Newest Arrivals`, `Best Sellers`.
- For storefront crawling, set `store_sort_orders` with the same labels and set `store_page_limit` from 1 to 20.
- Default to `browser_backend: "cdp"` and `browser_mode: "reuse"` with
  `chrome_binary: "auto"` and a dedicated `chrome_user_data_dir`. Real run and
  readiness commands automatically start a persistent Chrome for Testing when
  the configured CDP endpoint is not already running.
- `./lc-amazon-data-crawl.sh install` installs the Python dependencies and the
  Playwright Chromium/Chrome for Testing runtime used by automatic extension
  loading.
- `browser_backend: "selenium"` remains available as an explicit fallback.
- If using SellerSprite enrichment, set `extension_path: "auto"` to scan normal
  Chrome Profiles for the newest installed SellerSprite version and load it
  into the dedicated CDP Profile. This loads extension code only; it never
  copies credentials, cookies, or other Profile data.
- Automatic extension loading requires Chrome for Testing or Chromium. Official
  branded Chrome 137+ ignores `--load-extension`; on those versions either use
  Chrome for Testing or load the unpacked extension once from
  `chrome://extensions`.
- With `browser_mode: "reuse"`, the runner connects to a separate crawl tab and
  does not close the user-owned browser. `cdp-browser-start` remains available
  when the browser should be prepared before a check or crawl command.
- A fixed local extension folder remains supported in `extension_path`; leave
  it empty only when the dedicated Profile already has the extension.
- Keep `activate_plugin: false` by default. SellerSprite content scripts inject
  automatically; avoiding broad activation clicks prevents accidental Amazon
  navigation.
- Keep `page_scroll_before_extract: true` so each visible Amazon page is scrolled downward before extraction; this triggers lazy-loaded product cards and SellerSprite-injected fields before records are written.
- Run `sellersprite-check` when preparing a profile or diagnosing plugin data.
  It opens the first real target page and writes no crawl records.
- When `sellersprite_required` is true, do not write page records until at
  least the configured number of ASINs contains real SellerSprite-only fields
  and the data remains stable for the configured number of checks.
- For image-competitor quantity matching, recommend `match_mode: "embedding"`
  with `doubao-embedding-vision-251215` through Volcengine Ark
  `/api/v3/embeddings/multimodal`. Keep the API key only in
  `config/doubao_embedding_vision.json`, referenced by
  `doubao_embedding_config_file`; do not put it in a crawl config, log, state,
  archive, or message.
- Run `doctor` to see only whether the Doubao credential is `missing`,
  `unconfigured`, or `ready`. Run the image-competitor dry-run before opening
  Chrome; missing, invalid, or empty credential configuration must fail there.
- `match_mode` accepts only `embedding` and `chat`. New Doubao configuration
  takes precedence. Legacy `openai_*` fields remain a deprecated compatibility
  path, while `chat` keeps its existing provider behavior.
- Do not use legacy third-party browser-container workflows; this skill is only
  for normal visible Chrome crawling through CDP, with Selenium as a fallback.

## Long-Running Crawl Supervision

For real runs, monitor terminal output and the `outputs/<job_id>/state.json` file:

- If no new records, state updates, or browser actions happen for more than 3 minutes, report the current reason to the user.
- If Amazon or SellerSprite needs manual action, tell the user exactly which browser window/page is waiting.
- If delivery auto-selection fails, tell the user to set the requested location
  in the current visible Amazon page. After `manual_pause_timeout`, treat an
  unconfirmed location as `delivery_location_unconfirmed` and stop before
  extraction.
- Before writing records, the crawler scrolls the page until the Amazon/product DOM and SellerSprite/plugin DOM stop changing, then waits for SellerSprite data to stabilize.
- CDP reachability, plugin injection, plugin login prompts and actual enriched
  fields are separate readiness checks. A plugin node or empty table alone is
  never treated as ready.
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

Public packages may include
`assets/config/doubao_embedding_vision.example.json`, but must never include a
populated `config/doubao_embedding_vision.json`, browser Profiles, cookies, or
crawl outputs. Preserve existing archives when creating a new dated package.
