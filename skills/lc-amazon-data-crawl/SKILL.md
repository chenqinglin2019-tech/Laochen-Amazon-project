---
name: lc-amazon-data-crawl
description: Run and maintain a reusable Amazon data crawler for front-end product collection with SellerSprite-enriched fields. Use when the user needs to crawl Amazon keyword search result pages with selectable sort orders, Best Sellers/New Releases category ranking nodes, storefront product lists with selectable sort orders and up to 20 pages per store, or image-search similar competitor counts/details; also use when packaging this crawler for another Codex installation.
metadata:
  last_updated: 2026-08-18
---

# Lc amazon Data Crawl

Use this skill to create and operate a local Amazon crawler runner. The bundled scripts support:

- `keyword_search`: crawl Amazon search results from a keyword file, with sort choices such as Featured, Newest Arrivals, Best Sellers, and price/review sorts.
- `storefront`: crawl Amazon storefront product lists, usually with `Newest Arrivals` or `Best Sellers`, up to 20 pages per store/sort.
- `bsr_category`: crawl a single Amazon ranking/listing URL through the unified front crawler.
- `category-rank`: crawl a ranking category node recursively, including child category nodes.
- `image-competitor`: crawl Amazon image-search similar products and optionally compare/count competitors.

Front and category crawls also collect SellerSprite child-category BSR ranks in
`subcategory_bsr_ranks` and can optionally filter products by fulfillment and
the presence of a child-category rank before records are written.

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

Setup creates `config/doubao_embedding_vision.json` and
`config/doubao_same_product_mini.json` from empty public examples, protects
both with mode `0600` where supported, and adds both to the runner
`.gitignore`. It never overwrites either file on later setup runs. Before an
image-competitor cascade run, the user must bind their own Volcengine Ark API
key in both local files. Never ask the user to paste the key into chat.

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
- `browser_tab_concurrency` defaults to `1` and accepts `1` to `3`. Values above
  `1` are supported only by CDP with `browser_mode: "reuse"` or `"attach"`.
  Tabs process independent sources concurrently while pagination within one
  source remains serial.
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
- `subcategory_bsr_ranks` is a structured list such as
  `[{"rank": 130, "category_name": "Fruit Bowls"}]`. A single BSR row is kept
  as a child category; when multiple rows exist, the first broad parent row is
  excluded and all subsequent child-category rows are retained.
- `product_filters` defaults to no filtering. It supports mutually exclusive
  fulfillment allow/deny lists through `allowed_fulfillment_methods` and
  `excluded_fulfillment_methods`, plus `allow_missing_fulfillment` and
  `require_subcategory_rank`; active conditions are combined with AND. Use
  `excluded_fulfillment_methods: ["FBA"]` with a required child rank when every
  confirmed non-FBA, missing, or unknown method should be retained.
- Fulfillment evidence is parsed only from an explicit fulfillment label,
  mapped table column, or configured selector. SellerSprite text such as
  `配送:FBM卖家:1` is normalized to `FBM` while the captured raw evidence remains
  in JSONL. Within those explicit fulfillment contexts, a value beginning with
  `FBA`, `FBM`, or `AMZ` uses that canonical method regardless of its suffix;
  unrelated card fields such as a standalone `FBA费用` do not count as
  fulfillment.
- Changing the output schema, fulfillment parsing semantics, or
  `product_filters` is incompatible with an old job that already contains
  records or completed pages. Use a new `job_id` instead of mixing old and new
  records.
- One process owns a `job_id` at a time. Atomic page shards drive JSONL
  materialization and crash recovery; a second process using the same job is
  rejected instead of racing the state writer.
- For same-product quantity matching, recommend `match_mode: "cascade"`.
  `doubao-embedding-vision-251215` performs a low-cost visual prescreen; only
  sources with at most 10 prescreen matches are reviewed by
  `doubao-seed-2-0-mini-260428`. The final business count comes only from the
  Mini review, never directly from embedding similarity.
- Cascade currently requires `result_mode: "count_only"`; use the legacy modes
  for detailed competitor rows.
- Keep Ark API keys only in `config/doubao_embedding_vision.json` and
  `config/doubao_same_product_mini.json`, referenced by
  `doubao_embedding_config_file` and `doubao_mini_config_file`. Never put a key
  in a crawl config, log, state, archive, or message.
- Treat those as two independent local provider interfaces. A user of a shared
  Skill fills only their own `api_key` in each file; setup creates both with
  mode `0600`, preserves existing values, and release packages contain empty
  examples only. Dedicated Doubao endpoints must be HTTPS and never follow
  redirects.
- Cascade processes Lens candidates in page order. Zero prescreen matches means
  `verified_zero` with final count `0`. One to ten matches enter Mini review in
  batches of six. On the 11th prescreen match, stop additional embedding calls,
  skip Mini, mark `prescreen_excluded`, and leave `same_product_count` blank.
  The final Excel also adds `mini复核确认同款数量`: it shows a numeric count only
  for `verified` Mini-reviewed results, stays blank for `verified_zero`, and
  shows `Embedding判断同款数量大于10` for `prescreen_excluded`.
- Mini judges the primary product and ignores color, accessory quantity, sale
  quantity, bundle count, composition, and background when the product's core
  function and structure are the same. Different category, core function, or
  core structure is not the same product.
- Bind resumable cascade jobs to the input-file digest and normalized source
  order. Commit each completed source to an atomic `source_results/` shard and
  materialize aggregate JSONL from those shards, so a crash cannot duplicate a
  paid model call or attach an old row's count to a different ASIN.
- Image-competitor runs close every popup/result tab explicitly created while
  processing a product as soon as that product is committed or abandoned.
  Tabs that existed before the product started are preserved, and the crawler
  restores its original working tab before continuing to the next product.
- Run `doctor` to see only whether each Doubao credential is `missing`,
  `unconfigured`, or `ready`. Run image-competitor dry-run before opening
  Chrome; missing, invalid, or empty required credential configuration must
  fail there.
- `match_mode` accepts `cascade`, `embedding`, and `chat`. The latter two remain
  backward-compatible modes; legacy `openai_*` fields remain a deprecated
  compatibility path for their existing provider behavior.
- Do not claim 90% same-product precision without validation data. Calibrate
  the embedding threshold on a category-stratified set of at least 300 labeled
  image pairs, keep a frozen evaluation split, and report measured Mini
  precision from that frozen split.
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
- Image competitor crawler writes mode-specific JSONL files and an Excel result
  ending in `_相似竞品数量.xlsx` or a detailed competitor workbook. Cascade
  count output includes `prescreen_visual_match_count`, `processing_status`,
  `same_product_count`, `same_product_confidence`, and `match_reason`;
  `prescreen_excluded` rows intentionally have a blank final count. The final
  review workbook permanently removes `最佳页码`、`最佳排名`、`加载状态`、`备注` and
  `mini复核确认同款数量`, and adds a duplicate, clickable `商品URL` immediately
  before `相似竞品数量` for manual review.
  `same_product_confidence` is the minimum confidence among Mini-accepted
  products and remains blank when the final count is zero. The JSONL also
  records non-secret provider call/token metrics for paid-pilot cost review.

## Historical Fulfillment Repair

Completed jobs are not rewritten when fulfillment parsing semantics change.
Use the conservative sidecar repair tool when the historical JSONL retained
auditable raw values such as `FBM卖家` or `FBA卖家`:

```bash
.venv/bin/python scripts/repair_fulfillment_outputs.py \
  outputs/<old-job-id> \
  --output-dir outputs/<old-job-id>-repaired \
  --expected-record-count <count> \
  --expected-unique-asin-count <count>
```

The destination must not exist and must be outside the source job. The tool
does not modify source state, page shards, JSONL, or workbooks. It promotes raw
fulfillment values beginning with `FBA`, `FBM`, or `AMZ`, reports all remaining
unknown raw evidence without inferring it, and produces full plus ranked
non-FBA comparison workbooks in the new directory.

## Maintenance

When updating this skill, update the bundled scripts in `scripts/`, templates in `assets/config/`, and this `SKILL.md` together. Validate with:

```bash
python3 /path/to/skill-creator/scripts/quick_validate.py /path/to/lc-amazon-data-crawl
```

Public packages may include the empty
`assets/config/doubao_embedding_vision.example.json` and
`assets/config/doubao_same_product_mini.example.json`, but must never include
populated local credential files, browser Profiles, cookies, or crawl outputs.
Preserve existing archives when creating a new dated package.
