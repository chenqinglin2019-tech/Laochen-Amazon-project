# Lc amazon Data Crawl Configuration

## Runner Layout

`setup_runner.sh` creates this structure:

```text
lc-amazon-data-crawl-runner/
  .gitignore
  lc-amazon-data-crawl.sh
  requirements.txt
  scripts/
  config/
    amazon_delivery_locations.json
    doubao_embedding_vision.json
    doubao_same_product_mini.json
  inputs/
  outputs/
  chrome_profiles/
```

Configs are plain JSON. Relative paths are resolved from the runner root.
`doubao_embedding_vision.json` and `doubao_same_product_mini.json` are local
credential files: setup creates each only when missing, sets mode `0600` where
supported, and never overwrites either one.

## Browser Modes

- `browser_backend: "cdp"`: required; connect Playwright to visible Chrome
  through `debugger_address` without invoking ChromeDriver.
- `launch`: start a dedicated Chrome owned by the crawler; it closes when the crawler exits.
- `attach`: connect to an already running Chrome debugging port.
- `reuse`: keep a user-owned CDP browser open across commands. The runner shell
  automatically starts it before real runs and `sellersprite-check` when the
  endpoint is not already available.

The five production modes reject Selenium and AppleScript backend values during
dry-run validation. Those backends cannot prove popup ownership strongly enough
for the crawler's cleanup contract. `reuse` is the default mode for a newly
created runner.

`browser_backend` selects the automation implementation. `browser_mode`
selects who starts and owns the Chrome process. In CDP `attach`/`reuse` mode the
runner opens a separate crawl tab and disconnects without closing the user's
browser.

`browser_tab_concurrency` controls how many crawl tabs may work at once:

- Default `1`; accepted range `1` to `3`, with `2` recommended for parallel
  front/category work.
- A value above `1` requires `browser_mode` set to `reuse` or `attach`; launch
  mode rejects that combination during config validation instead of silently
  downgrading it.
- Only independent queued sources run concurrently, such as different
  keyword/sort pairs, store/sort pairs, or independently queued category
  nodes. Pages within one source remain serial so pagination, repeated-page
  detection, and checkpoints stay ordered.
- Actual active tabs may be lower than the configured value when fewer
  independent sources are available.

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

### Crawler-owned tab lifecycle

Each worker has one dedicated crawler-owned working tab. The crawler may also
own result tabs or popups opened from that working tab. Ownership must be
positive and traceable; a tab is not crawler-owned merely because it appeared
after a list of handles was sampled.

- In CDP mode, track crawler-created pages from the working page's popup/opener
  events and propagate ownership to descendant popups. Use crawler ownership
  markers to recognize the worker page and any recoverable leftovers.
- No Selenium handle-difference cleanup is used. Production configs fail closed
  unless the CDP ownership tracker is active.
- Preserve every tab that existed before the operation and every unknown tab
  the user may have opened concurrently. Never navigate an arbitrary surviving
  user tab when a crawler working tab is lost; create a new crawler-owned
  working tab instead.
- Close owned result tabs and descendant popups after each product is committed
  or abandoned, before a retry or long wait, and during exception, `Ctrl-C`, or
  normal-exit cleanup. Re-scan every 500 milliseconds for up to 2 seconds so
  delayed popups are included; retry an individual close once and log failures.
- On startup, close only leftovers that carry a verifiable crawler ownership
  marker. Unknown pages and pages owned by the user remain untouched.

Cleanup always restores the worker's dedicated working tab, or replaces that
tab with a newly marked crawler-owned working tab if it no longer exists. The
ownership baseline must be initialized before an operation can register or
close child tabs; an exception before initialization must never cause all
existing browser tabs to be treated as crawler-created.

## Amazon Page Availability And Retry

All five crawler templates share this optional field and default:

```json
"amazon_page_unavailable_retry_schedule_seconds": [
  [180, 300],
  [180, 300],
  [1800, 1800],
  [3600, 3600]
]
```

The initial navigation is attempt 1. Each of the four entries controls the wait
before attempts 2 through 5, so there are exactly five attempts in one retry
cycle. A pair is an inclusive random `[minimum, maximum]` range in seconds.
Config validation requires exactly four pairs of finite, non-negative numbers
with `minimum <= maximum`; invalid values fail dry-run before Chrome opens.
Omitting the field uses the same default. The retry schedule is operational
policy and is not added to crawl-plan or provider fingerprints, so changing it
alone does not invalidate an existing checkpoint.

The shared page-health classifier is stage-aware. Product pages, search and
category pages, Amazon Lens upload pages, and Lens result pages each require
their expected content DOM after the configured timeout. These conditions are
retryable page-unavailable failures:

- Amazon dog/error pages, rate-limit pages, Access Denied, and HTTP 429 or 5xx;
- network, DNS, connection, or navigation failures;
- an empty/blank response, or a page that still lacks the stage's expected DOM
  after timeout.

Text such as `sorry` inside an otherwise healthy product page does not by
itself make the page unavailable. Only a stage-specific, explicit Amazon or
Lens no-results state is a valid empty result; an ambiguous blank or partial
page must never be committed as a zero count. CAPTCHA/Robot Check remains a
manual-action pause and does not turn into a zero result. An Amazon buyer
sign-in wall is terminal and uses the documented sign-in message instead of
this retry schedule. SellerSprite data stalls continue to use the independent
plugin retry and relaunch settings under **Stall Handling**.

Before every long wait, the crawler closes owned result/popup tabs, chooses the
actual wait once, and atomically persists it. `state.json` may include:

```json
"amazon_page_retry": {
  "status": "waiting",
  "domain": "www.amazon.com",
  "work_key": "source-or-page-key",
  "stage": "product",
  "cycle": 1,
  "attempts_completed": 1,
  "next_attempt": 2,
  "selected_wait_seconds": 247,
  "remaining_wait_seconds": 247,
  "next_retry_at": 1788336247.0,
  "url": "https://www.amazon.com/...",
  "error": "redacted retryable summary"
}
```

`next_retry_at` is a Unix timestamp in seconds. The URL and error fields must
not contain secrets, credentials, cookie values, or authorization data. Waits
are split into chunks of no more than 60 seconds;
each chunk updates `state.json` and prints a countdown/heartbeat. If the process
is interrupted while waiting, the next invocation uses the persisted
`next_retry_at` and waits only the remaining duration rather than drawing a new
delay.

Cooldown applies by exact Amazon domain. While any worker is waiting on a
retryable unavailable page, other workers must not begin a new navigation to
that domain. A worker whose page had already loaded may complete local
extraction and its single atomic commit. Navigation to a different domain is
not blocked.

If attempt 5 still fails, the crawler closes tabs owned by that work item,
leaves that item and all other unfinished work pending, writes no page/product
record, count, completion shard, or inferred zero, and appends one deduplicated
`amazon_page_unavailable_retry_exhausted` event to `failures.jsonl`. It then
sets the checkpoint to `manual_resume_required` and exits. Re-running the same
runner command is the manual continuation action: completed work remains
committed, while only the current pending work item starts a new five-attempt
cycle. If the previous process was merely interrupted during a scheduled wait,
the remaining persisted wait takes precedence and the current cycle continues.

## Amazon Delivery Location

All five crawler templates enable marketplace-specific delivery selection:

- `delivery_location_enabled`: default `true`.
- `delivery_locations_file`: default
  `config/amazon_delivery_locations.json`.
- `delivery_location_timeout`: automatic attempt timeout in seconds; default
  `20`.
- `manual_pause_timeout`: existing manual-action timeout; default `900`.

The mapping file has a `locations` object keyed by exact Amazon domain. Each
entry supplies `city`, string-valued `postal_code`, and `strategy`. See
`references/delivery-locations.md` for the fixed 19-market mapping and UAE
exception.

For every business navigation, the runner handles Amazon verification first,
checks the header location, sets the mapped destination if needed, reopens the
original URL, and confirms the result before extraction. A confirmed result is
cached only for the current driver and exact domain; browser restarts and
domain changes require another confirmation.

If automatic selection fails, complete the address prompt in the current
visible browser. If the location is still unconfirmed after
`manual_pause_timeout`, the run stops with `delivery_location_unconfirmed` and
does not write records for that page. The delivery mapping digest is part of
the non-sensitive resume fingerprint: if an existing job already has records
and the mapping changed, use a new `job_id` instead of mixing results.

Changing delivery location updates Amazon cookies in the dedicated Chrome
Profile. It may change price, availability, delivery promises, and search
results.

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

## Child-Category BSR And Product Filters

Front and category crawls expose SellerSprite child-category ranks as the
structured JSONL field `subcategory_bsr_ranks`:

```json
[
  {"rank": 130, "category_name": "Fruit Bowls"}
]
```

If the card has one BSR row, that row is retained as a child category. When
multiple rows exist, the first row is treated as the broad parent category and
omitted while all later child-category rows are retained. A card with no BSR
row has `[]`. Excel renders the same data as `#130 in Fruit Bowls ; ...`
without changing the JSONL structure.

Filtering is optional and disabled by every bundled template:

```json
"product_filters": {
  "allowed_fulfillment_methods": [],
  "excluded_fulfillment_methods": [],
  "allow_missing_fulfillment": false,
  "require_subcategory_rank": false
}
```

- Fulfillment filtering is enabled when either fulfillment list is non-empty
  or `allow_missing_fulfillment` is true. With both lists empty and a false
  missing-value flag, that condition is disabled.
- The allowlist is an OR condition using only `FBA`, `FBM`, and `AMZ`.
  `allow_missing_fulfillment: true` additionally accepts a genuinely blank
  value; a non-empty unknown value is not accepted.
- The denylist accepts genuinely blank and unknown non-empty values, and
  rejects only records whose canonical method is listed. The allowlist and
  denylist are mutually exclusive; `allow_missing_fulfillment` applies only to
  allowlist mode.
- `require_subcategory_rank: true` keeps only products whose
  `subcategory_bsr_ranks` list is non-empty.
- Fulfillment and rank conditions are combined with AND. Any active filter
  requires `sellersprite_required: true`; invalid objects, keys, types, or
  fulfillment labels fail during config validation before the browser opens.

For the requested workflow—keep every product with a child-category rank unless
its canonical fulfillment method is FBA—use:

```json
"product_filters": {
  "allowed_fulfillment_methods": [],
  "excluded_fulfillment_methods": ["FBA"],
  "allow_missing_fulfillment": false,
  "require_subcategory_rank": true
}
```

This retains FBM, AMZ, genuinely missing, and unknown non-empty fulfillment
values while excluding confirmed FBA. Use an allowlist instead when unknown
values must fail closed.

Fulfillment evidence is accepted only after an explicit `配送`/`fulfillment`
label, from a mapped fulfillment table column, or from an explicit field
selector. Known values may touch the next SellerSprite label in flattened DOM
text, so `配送:FBM卖家:1` becomes canonical `FBM` with raw evidence `FBM卖家`.
Within those explicit fulfillment contexts, any value beginning with `FBA`,
`FBM`, or `AMZ` is normalized to that method regardless of its suffix, so
`FBA Fee` and `FBMPlus` are canonical FBA and FBM respectively. Context checks
still keep unrelated card fields such as a standalone `FBA费用`, `配送时长`, or
`配送费` from being interpreted as fulfillment. Selector, structured table,
and labelled card evidence are considered in that source order; any recognized
canonical value is stronger than an unknown raw value.

Filtering affects only records written to JSONL/Excel. Page traversal and
repeated-page detection continue to use all extracted ASINs, so a page with no
qualifying products does not prematurely stop later pages.

The resume contract fingerprint includes the normalized filter object, record
schema version, child-rank semantics, and fulfillment parsing semantics. A
separate crawl-plan fingerprint
tracks the mode/start URL, source inputs, page/depth limits, sponsored setting,
and field selectors; `browser_tab_concurrency` is intentionally excluded so it
may be changed before resume. A job containing progress is rejected when either
fingerprint differs; use a new `job_id`. A pending-only state is rebuilt from
the new plan. Existing runner configs are preserved by `setup_runner.sh`, so
omitted new keys retain their backward-compatible defaults
(`browser_tab_concurrency: 1`, filters disabled), but old records cannot be
backfilled with child-category ranks without a fresh crawl.

### Historical fulfillment sidecar repair

Changing fulfillment parsing semantics does not mutate completed page shards.
For a completed front-crawler job whose `records.jsonl` retained audited raw
values, run:

```bash
.venv/bin/python scripts/repair_fulfillment_outputs.py \
  outputs/<old-job-id> \
  --output-dir outputs/<old-job-id>-repaired \
  --expected-record-count <count> \
  --expected-unique-asin-count <count>
```

The output directory must not already exist and cannot be inside the old job.
The tool opens the source job read-only, promotes explicit raw values beginning
with `FBA`, `FBM`, or `AMZ`, leaves every other unknown raw value unconverted
and reported, and atomically publishes repaired JSONL, a full
workbook, a ranked non-FBA JSONL/workbook, and `repair_report.json`. Future
live crawls must still use a new `job_id`.

Each completed page is first committed as an atomic JSON file under
`outputs/<job_id>/page_results/`. `records.jsonl` is materialized from those
page shards and deduplicated by `(page_key, asin)`, so a crash between the page
commit and `state.json` update can be recovered without duplicate records.
`state.json` uses schema version 2 and exposes `pending`, `in_flight`,
`completed_pages`, `completed_sources`, scan/keep/filter counters, rejection
reason totals, and current manual-pause information. The recursive category
crawler also retains its compatible `queue`, `in_flight_categories`, and
`done_categories` names. `failures.jsonl` contains page/source context plus a
machine-readable reason and message; rejected product details are never stored.

Only one process may write a given `job_id` at a time. A second invocation is
rejected by `outputs/<job_id>/.run.lock`; use another `job_id` instead of running
two processes against one checkpoint.

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
- `match_mode`: `cascade`, `embedding`, or `chat`. The recommended
  same-product count workflow uses `cascade`; the two older modes preserve
  their existing behavior.
- `doubao_embedding_config_file`: default
  `config/doubao_embedding_vision.json` for embedding prescreening.
- `prescreen_min_similarity`: default `0.70`; visual-near-match threshold used
  only by the cascade prescreen.
- `prescreen_max_matches`: default `10`; the 11th match triggers early
  exclusion.
- `doubao_mini_config_file`: default
  `config/doubao_same_product_mini.json` for the final same-product review.
- `mini_batch_size`: default `6` candidates per Mini request.
- `mini_retry_attempts`: default `3`, including retries for malformed
  structured JSON.
- `mini_retry_backoff_seconds`: default `1`.
- `min_match_confidence`: retained for legacy `embedding`/`chat`
  compatibility. It is not the cascade prescreen threshold.

`cascade` currently requires `result_mode: "count_only"`. Use the legacy
`embedding` or `chat` modes when a detailed competitor workbook is required.

Bind the user's own Volcengine Ark API key in both dedicated local files. The
embedding file is:

```json
{
  "api_key": "",
  "model": "doubao-embedding-vision-251215",
  "base_url": "https://ark.cn-beijing.volces.com/api/v3",
  "api_path": "embeddings/multimodal",
  "encoding_format": "float"
}
```

The Mini file is:

```json
{
  "api_key": "",
  "model": "doubao-seed-2-0-mini-260428",
  "base_url": "https://ark.cn-beijing.volces.com/api/v3",
  "api_path": "chat/completions"
}
```

The two provider interfaces are deliberately separate. A shared Skill user only
needs to fill their own `api_key` in each local file; the two keys may be the
same Ark key or different scoped keys. Do not ask the user to paste either key
into chat. Do not copy populated local credential files into source control or
a release archive. Dedicated Doubao endpoints must use HTTPS and cannot contain
userinfo, query parameters, fragments, or redirects.
`./lc-amazon-data-crawl.sh doctor` reports only `missing`, `unconfigured`, or
`ready` for `doubao_embedding_vision` and `doubao_same_product_mini`; it never
prints their contents.

### Cascade matching semantics

Cascade uses embedding only as a low-cost visual-near-match prescreen. It
processes Lens candidates in page order and applies these states:

- No prescreen match: `processing_status` is `verified_zero`,
  `prescreen_visual_match_count` is `0`, and `same_product_count` is the real
  value `0`; Mini is not called.
- One to ten prescreen matches: Mini reviews those candidates in batches of six,
  `processing_status` is `verified`, and only Mini's decisions contribute to
  `same_product_count`.
- The 11th prescreen match: stop additional embedding calls immediately, do
  not call Mini, set `processing_status` to `prescreen_excluded`, and leave
  `same_product_count` blank. The row is deliberately excluded without
  pretending that `11` is a final same-product count.

The source-level cascade output fields are:

- `prescreen_visual_match_count`
- `processing_status`
- `same_product_count`
- `same_product_confidence`
- `match_reason`

`mini_confirmed_same_product_count` remains in the source-level JSONL audit
record, but is intentionally not added to the review workbook.

`same_product_confidence` is the minimum Mini confidence among products counted
as same-product. It stays blank for `prescreen_excluded`, `verified_zero`, and
`verified` results whose final count is zero. In Excel, `same_product_count`
continues to use the existing `相似竞品数量` column for compatibility. The final
review workbook removes `最佳页码`、`最佳排名`、`加载状态`、`备注` and the legacy
`mini复核确认同款数量` output column. It inserts a duplicate, clickable `商品URL`
immediately before `相似竞品数量`, then appends four audit columns:
`视觉粗筛命中数`、`处理状态`、`同款判断置信度`、`同款判断说明`.

Mini judges the primary product/body. Different colors, accessory quantities,
sale quantities, bundle counts, product compositions, and backgrounds remain
the same product when core function and core structure are the same. Different
product categories, core functions, or core structures are rejected. Source
and candidate primary images are the decision evidence; titles are only an
auxiliary clue for category and structure. The Mini response is structured
JSON, and malformed output is retried instead of silently turning into a zero.

In cascade mode, both dedicated credential files are validated by dry-run
before Chrome opens. Missing files, invalid JSON, and empty keys fail with an
instruction to fill the local file. `embedding` mode uses the embedding file;
legacy `vision_model` and `openai_*` fields remain available with a deprecation
warning. `chat` mode continues to use its legacy provider fields.

The Ark multimodal request retries timeouts, HTTP 408/429, and 5xx responses.
Authentication/authorization errors and invalid endpoint or model access fail
immediately. Returned vectors must be non-empty, finite, and dimensionally
consistent. If both a candidate URL and local-image fallback fail, the source
is recorded as failed/retryable instead of being written as zero competitors.

Each count JSONL row also stores non-secret `provider_metrics`, including actual
Embedding/Mini HTTP call attempts and any token/image-token usage returned by
Ark. Use those measurements plus the Ark bill for a paid pilot cost check; the
crawler does not hard-code a volatile per-token price.

The resume fingerprint includes non-secret embedding and Mini models,
endpoints, cascade thresholds, batching and prompt semantics, delivery mapping,
the input file digest, the normalized source queue and its order. It never
includes either API key. Each completed cascade source is first committed to an
atomic `source_results/` shard; `candidates.jsonl`, `records.jsonl`, and
`counts.jsonl` are deterministic materializations of those shards. A crash can
therefore rebuild aggregate files without repeating a paid model call. Use a
new `job_id` when resuming an old progressed job whose fingerprint predates
cascade or source-shard semantics.

`prescreen_min_similarity: 0.70` is a safe configuration default, not a claim
of universal accuracy. Before claiming at least 90% final Mini precision,
label at least 300 image pairs, stratify them by category, choose the embedding
threshold only on a calibration split, and measure Mini precision once on a
frozen evaluation split. Without that labeled dataset, document the workflow
as implemented but uncalibrated rather than claiming the target was met.

Provider references: [Volcengine Ark quick start](https://www.volcengine.com/docs/82379/1795150),
[Ark multimodal Chat API](https://api.volcengine.com/api-explorer/?action=ChatCompletions&groupName=%E5%AF%B9%E8%AF%9D%28Chat%29+API&serviceCode=ark&version=2024-01-01),
and [Ark multimodal embeddings API](https://api.volcengine.com/api-docs/view?action=EmbeddingsMultimodal&serviceCode=ark&version=2024-01-01).

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
