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

- `launch`: start a dedicated Chrome with `chrome_user_data_dir`; best for repeatable crawling.
- `attach`: connect to an already running Chrome debugging port.
- `reuse`: require an already running debugging port; fail if not available.
- `applescript`: only supported by front/category crawlers, for manual Chrome control fallback.

Common fields:

- `chrome_binary`: usually `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` on macOS.
- `chrome_user_data_dir`: dedicated profile folder, for example `chrome_profiles/lc-amazon-data-crawl`.
- `debugger_address`: default `127.0.0.1:9222`.
- `extension_path`: local SellerSprite extension folder. Leave empty if using a Chrome profile where the extension is already installed and the script can work without loading an unpacked extension.
- `activate_plugin`: true to try to click/activate SellerSprite injected data.

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
