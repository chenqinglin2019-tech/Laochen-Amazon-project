# Lc amazon Data Crawl Configuration

## Runner Layout

`setup_runner.sh` creates this structure:

```text
lc-amazon-data-crawl-runner/
  lc-amazon-data-crawl.sh
  requirements.txt
  scripts/
  config/
  inputs/
  outputs/
  chrome_profiles/
```

Configs are plain JSON. Relative paths are resolved from the runner root.

## Browser Modes

- `browser_backend: "cdp"`: default; connect Playwright to visible Chrome
  through `debugger_address` without invoking ChromeDriver.
- `browser_backend: "selenium"`: explicit compatibility fallback.
- `launch`: start a dedicated Chrome owned by the crawler; it closes when the crawler exits.
- `attach`: connect to an already running Chrome debugging port.
- `reuse`: keep a user-owned CDP browser open across commands. The runner shell
  automatically starts it before real runs and `sellersprite-check` when the
  endpoint is not already available.
- `applescript`: only supported by front/category crawlers, for manual Chrome control fallback.

`browser_backend` selects the automation implementation. `browser_mode`
selects who starts and owns the Chrome process. In CDP `attach`/`reuse` mode the
runner opens a separate crawl tab and disconnects without closing the user's
browser.

Common fields:

- `chrome_binary: "auto"`: locate the newest installed Chrome for Testing,
  including the Playwright browser cache installed by the runner.
- `chrome_user_data_dir`: dedicated profile folder, by default
  `chrome_profiles/lc-amazon-data-crawl-cft`.
- `debugger_address`: default `127.0.0.1:9222`.
- `extension_path`: local SellerSprite extension folder. Leave empty if using a Chrome profile where the extension is already installed and the script can work without loading an unpacked extension.
- `extension_path: "auto"`: when starting the dedicated CDP browser with
  `cdp-browser-start`, scan normal Chrome Profiles for the newest installed
  SellerSprite version and load that extension into the dedicated Profile.
  No credentials, cookies, or other Profile files are copied.
- `extension_path: "auto"` must use Chrome for Testing or Chromium. Branded
  Chrome 137+ ignores command-line extension loading.
- `activate_plugin`: false by default. SellerSprite injects automatically;
  enabling it only permits clicks inside detected plugin containers.

`install` provisions the required Chrome for Testing runtime:

```bash
./lc-amazon-data-crawl.sh install
./lc-amazon-data-crawl.sh doctor
```

Real run and readiness commands automatically start or reuse the configured
browser. It can also be prepared explicitly:

```bash
./lc-amazon-data-crawl.sh cdp-browser-start --config config/amazon_front_storefront.json
./lc-amazon-data-crawl.sh sellersprite-check --config config/amazon_front_storefront.json
```

`cdp-browser-start` verifies the configured Profile path and leaves Chrome
running; later runner commands close only the tabs they created.

Chrome Profile verification is mandatory for CDP. The Profile Path shown by
`chrome://version` must equal `chrome_user_data_dir/chrome_profile_directory`.
This prevents attaching to a different Chrome profile that does not contain the
expected SellerSprite installation and login session.

## SellerSprite Readiness

Use these fields for SellerSprite-enriched modes:

- `sellersprite_required`: fail closed when actual plugin data is unavailable.
- `sellersprite_min_enriched_records`: minimum ASIN records with plugin fields;
  default 1.
- `sellersprite_min_fields_per_record`: minimum SellerSprite-only fields per
  qualifying ASIN; default 2.
- `sellersprite_stable_checks`: consecutive identical data checks required
  before writing; default 3.

The readiness states are `browser_unreachable`, `plugin_absent`,
`login_required`, `data_loading`, `ready`, and `blocked`. Title, price, rating,
empty plugin tables, and plugin DOM nodes without parsed SellerSprite fields do
not satisfy the gate.

Check the first real target without writing records:

```bash
./lc-amazon-data-crawl.sh sellersprite-check --config config/amazon_front_keyword_search.json
```

For `image-competitor` count-only mode, set `sellersprite_required: false`
because that output does not request SellerSprite fields. Detail mode must use
either `sellersprite_on_lens` or `enrich_accepted_results` when the gate is
required.

## Page Preload Scroll

Before extracting each page, front/category/image enrichment flows should scroll the visible browser downward so Amazon lazy-loaded product cards and SellerSprite-injected fields have a chance to render.

Relevant fields:

- `page_scroll_before_extract`: default true. Keep enabled for SellerSprite-enriched crawls.
- `page_scroll_max_rounds`: maximum downward scroll rounds before extraction.
- `page_scroll_step_ratio`: scroll step as a fraction of viewport height.
- `page_scroll_wait_seconds`: wait after each scroll step so Amazon and SellerSprite can load.
- `page_scroll_stable_rounds`: stop after this many bottom-of-page rounds where product/plugin DOM metrics no longer change.

## Search And Storefront Sort Labels

Use these exact labels in `keyword_sort_orders` and `store_sort_orders`:

- `Featured`
- `Price: Low to High`
- `Price: High to Low`
- `Avg. Customer Review`
- `Newest Arrivals`
- `Best Sellers`

## Keyword Search

Use `config/amazon_front_keyword_search.json`.

Input file columns:

- `keyword`
- or `关键词`
- or `search_term`

Important fields:

- `mode`: `keyword_search`
- `keywords_file`: CSV/XLSX path.
- `max_pages_per_keyword`: page limit per keyword and sort.
- `keyword_sort_orders`: one or more supported sort labels.
- `include_sponsored`: false unless sponsored products should be included.

## Storefront Crawl

Use `config/amazon_front_storefront.json`.

Input file columns:

- `store_url`: Amazon storefront/search URL, commonly a URL containing `me=<seller id>`.
- `store_name`: optional display name.

Important fields:

- `mode`: `storefront`
- `store_urls_file`: CSV/XLSX path.
- `store_sort_orders`: one or more supported sort labels.
- `store_page_limit`: 1-20. If fewer pages exist, the crawler stops naturally.

## BSR/New Releases Single Category URL

Use `config/amazon_front_bsr_category.json` when the user provides one specific list/ranking URL and wants product rows from that page sequence.

Important fields:

- `mode`: `bsr_category`
- `start_url`: Amazon category/ranking URL.
- `max_pages_per_keyword` is not used for this mode.

## Recursive Category Rank Crawl

Use `config/category_rank_crawler.json` when the user wants a category node and all child category nodes.

Important fields:

- `start_url`: Amazon Best Sellers/New Releases category node.
- `include_root`: true to also crawl the starting node itself.
- `max_depth`: optional recursion depth; empty means no fixed depth cap.
- `max_pages_per_category`: optional page cap per category.
- `max_categories`: optional total category cap for test runs.

## Image Competitor Crawl

Use `config/amazon_image_competitors.json`.

Input file columns:

- `ASIN`
- `商品URL`
- `主图URL`
- `本地图片路径`

Important fields:

- `marketplace`: for example `美国站`.
- `result_mode`: `count_only` for competitor counts, `detail` for detailed rows.
- `match_mode`: `embedding` or `chat`.
- `openai_api_key_env`, `openai_base_url`, `openai_api_path`, `vision_model`: vision comparison provider settings.

## Stall Handling

The crawler configs include:

- `plugin_retry_attempts`: default 5.
- `plugin_retry_wait_seconds_min`: default 10.
- `plugin_retry_wait_seconds_max`: default 20.
- `plugin_relaunch_retry_attempts`: retry count after closing/relaunching Chrome.
- `plugin_relaunch_wait_seconds`: first relaunch sleep, usually 300 seconds.
- `plugin_second_relaunch_retry_attempts`: retry count after second close/relaunch.
- `plugin_second_relaunch_wait_seconds`: second relaunch sleep, usually 600 seconds.

If the page stops taking crawl actions for more than 3 minutes, inspect terminal output, `state.json`, the Chrome page, and `failures.jsonl` if present, then report the cause before continuing.
