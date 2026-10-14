# Lc amazon Data Crawl Configuration

关键词和店铺自 2026-10-12 起使用 [插件采集流程](plugin-collection.md)。本文件的 CDP、专用 Profile、当前页卡片、配送地址设置、手动等待及页重试说明仅适用于类目与历史任务，不得用于新版关键词/店铺/找同款入口；找同款参见 [image-background.md](image-background.md)。业务筛选纯函数继续复用。

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

The legacy category mode rejects Selenium and AppleScript backend values during
dry-run validation. Those backends cannot prove popup ownership strongly enough
for the crawler's cleanup contract. `reuse` is the default mode for a newly
created runner.

`browser_backend` selects the automation implementation. `browser_mode`
selects who starts and owns the Chrome process. In CDP `attach`/`reuse` mode the
runner opens a separate crawl tab and disconnects without closing the user's
browser.

`browser_tab_concurrency` controls how many crawl tabs may work at once:

- It is fixed at `1` for SellerSprite-enabled front and category runs. A
  higher value fails dry-run rather than creating extra browser traffic.
- The crawler uses one visible Chrome Profile and one crawler-owned working
  tab. This local process boundary does not control other computers or manual
  browser activity using the same account.

`page_extraction_engine` selects how configured `field_selectors` are read
from an already-rendered product card:

- `browser` (default): use the existing in-page browser selector extraction.
- `scrapling`: export a card's HTML only when at least one custom selector is
  configured, then parse those selectors locally with Scrapling. Missing fields
  fall back to the existing browser extraction. This mode makes no network
  request and does not open or control a second browser.

Scrapling requires Python 3.10 or newer. `install` automatically creates and
uses `.venv-scrapling` when the runner's existing `.venv` is older. This does
not alter authentication, browser-profile state, SellerSprite login, or any
provider/API settings.

Common fields:

- `chrome_binary: "auto"`: locate the newest installed Chrome for Testing or
  Playwright Chromium (including the Playwright browser cache). If none is
  found, run `./lc-amazon-data-crawl.sh install-browser` once (Windows:
  `.\lc-amazon-data-crawl.cmd install-browser`); `install` itself never downloads a browser.
- `chrome_user_data_dir`: dedicated profile folder, by default
  `chrome_profiles/lc-amazon-data-crawl-cft`.
- `debugger_address`: default `127.0.0.1:9222`.
- `extension_path`: local SellerSprite extension folder. Leave empty if using a Chrome profile where the extension is already installed and the script can work without loading an unpacked extension.
- `extension_path: "auto"`: whenever the runner starts the dedicated CDP
  browser (automatically before a real run / `sellersprite-check`, or via
  `cdp-browser-start`), scan normal Chrome Profiles for the newest installed
  SellerSprite version and load that extension into the dedicated Profile.
  No credentials, cookies, or other Profile files are copied. If the dedicated
  Chrome is already running without the extension, the run stops with exit 30
  and asks the user to close that window so the runner can relaunch it.
- `extension_path: "auto"` must use Chrome for Testing or Chromium. Branded
  Chrome 137+ ignores command-line extension loading.
- `activate_plugin`: false by default. SellerSprite injects automatically;
  enabling it only permits clicks inside detected plugin containers.

`install` installs Python dependencies only; `install-browser` provisions
Playwright Chromium for `chrome_binary: "auto"` when no Chrome for Testing exists:

```bash
./lc-amazon-data-crawl.sh install
./lc-amazon-data-crawl.sh install-browser   # only if doctor reports no Chrome for Testing
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
  normal-exit cleanup. Re-scan every 100 milliseconds for up to 250 milliseconds so
  delayed popups are included; retry an individual close once and log failures.
- On startup, close only leftovers that carry a verifiable crawler ownership
  marker. Unknown pages and pages owned by the user remain untouched.

Cleanup always restores the worker's dedicated working tab, or replaces that
tab with a newly marked crawler-owned working tab if it no longer exists. The
ownership baseline must be initialized before an operation can register or
close child tabs; an exception before initialization must never cause all
existing browser tabs to be treated as crawler-created.

## Safety Pause, Page Availability And Retry

Front and category runs use one shared local safety record at
`~/.lc-amazon-data-crawl/safety/risk-pause.json`, independent of `job_id`.
The runner records only platform, reason, time, wait-until and a redacted page
URL. It never stores cookies, extension tokens, credentials, or page HTML.

- Every crawler-owned navigation or refresh checks this record first. Amazon
  403/429, CAPTCHA/robot/abnormal-traffic/access-denied pages and explicit
  SellerSprite rate-limit, account-restriction, verification or quota messages
  stop new navigation, refresh, plugin clicks and scrolling immediately.
- `operation_mode` is `supervised` by default and can be overridden with
  `--operation-mode supervised|unattended` (CLI wins). Select it at startup;
  checkpoint and restart to switch modes. The shared persistent attempt counter
  survives mode changes and job changes. A restart during a rest continues the
  persisted deadline instead of drawing a new one. All timing values in this
  section are fixed in code by `operation_mode`; they are not config keys
  (setup removes the old keys from runner configs).
- Supervised: 20–30-second navigation spacing; 3–5-minute rest before the next
  navigation after every 20 attempts, except every 100th uses 10–12 minutes.
  Unattended: 45–75-second spacing and 15–20 minutes after every 10 attempts.
  Failed attempts count; page commits do not. No next navigation means no rest.
- Supervised temporary page faults retry once after 60 seconds. Unattended
  faults retry twice after 2 and 5 minutes, then defer the work item and
  continue independent work; three consecutive failures or five in the most
  recent 20 stop the run. Both retain a 90-second page-load timeout.
- The storefront plugin keeps its 40-second total budget and 10-second stable
  check. Other supervised lists wait 40 seconds, extending once to 80 only on
  new cards or required fields in the last 10 seconds. Image Find Similar waits
  20 seconds, Lens 40 seconds or at most 60 on valid progress, and image plugin
  gate 20 seconds. Unattended required plugin data waits up to 180 seconds on
  the original page, without this extension. Pre-scroll is adaptive (short
  steps, stops after 2 stable bottom checks; see "Page Preload Scroll").
- First 429 or explicit rate limit pauses at least 30 minutes (longer trusted
  `Retry-After` wins), then the next run sends one automatic probe with
  whichever item is pending (any job). The pause is cleared only after that
  probe page actually loaded and passed the Amazon risk check (SellerSprite
  pauses: after the probe page committed). If the probe never reaches a verdict
  (navigation error, timeout), no second request is sent in that run and the
  pause stays (exit 21). A repeat within 24 hours
  requires at least 24 hours and manual review. 403, abnormal traffic and
  account restriction also require 24-hour manual review. Daytime CAPTCHA waits
  for human clearance then cools 10 minutes; nighttime CAPTCHA saves the
  checkpoint and stops. After a manual pause expires, run once with
  `--resume-after-review`. A run that ends before its probe is sent never
  escalates the pause.
- Text markers (captcha, robot check, unusual traffic, too many requests,
  request blocked, access denied, "click the button below to continue
  shopping", 拒绝访问, 异常流量…) count only on short pages (≤4000 characters of
  visible text) — real block pages are tiny. Longer pages trip only on an exact
  block-page title (Robot Check, Sorry! Something went wrong!, ERROR: The
  request could not be satisfied, Access Denied, 429 Too Many Requests), so
  search/product titles containing the user's keyword ("access denied sign",
  "captcha t-shirt") never pause the machine. HTTP 403/429 always count.
- `./lc-amazon-data-crawl.sh safety-status` prints the active pause, its
  `not_before`, rest deadlines and whether a crawl is running.
  `safety-clear --confirm-reviewed` removes an expired pause after the user
  confirmed the browser is normal; it refuses to shorten an active one. Do not
  delete the safety files by hand.
- Every navigation and wait updates `outputs/<job_id>/run_heartbeat.json`
  (`pid`, `phase`, `updated_at`, optional `until`/`detail`); it ends with
  `phase: exited`. `run_summary.json` records operational counts plus the final
  `status`, `exit_code`, `next_action`, `resume_at` and `skipped_items`.

## Amazon Page Availability And Retry

The retry schedule is fixed by `operation_mode` (supervised: one retry after
60 seconds; unattended: retries after 2 and 5 minutes). The initial navigation
is attempt 1. Risk signals never use this retry path; they use the hard safety
pause above. The schedule is operational policy and is not part of crawl-plan
or provider fingerprints.

The shared page-health classifier is stage-aware. Product pages, search and
category pages, Amazon Lens upload pages, and Lens result pages each require
their expected content DOM after the configured timeout. These conditions are
retryable page-unavailable failures:

- non-risk Amazon dog/error pages and temporary 5xx transport failures;
- network, DNS, connection, or navigation failures that do not contain a
  risk marker;
- an empty/blank response, or a page that still lacks the stage's expected DOM
  after timeout.

Text such as `sorry` inside an otherwise healthy product page does not by
itself make the page unavailable. Only a stage-specific, explicit Amazon or
Lens no-results state is a valid empty result; an ambiguous blank or partial
page must never be committed as a zero count. CAPTCHA/Robot Check, 403/429,
rate-limit and Access Denied are risk pauses, not automatic retries. An Amazon
buyer sign-in wall is terminal and uses the documented sign-in message instead
of this retry schedule. SellerSprite data stalls wait on the existing page and
then require manual handling; they never relaunch Chrome automatically.

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
  "selected_wait_seconds": 60,
  "remaining_wait_seconds": 60,
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

When the last attempt of a cycle fails, the crawler closes tabs owned by that
work item, writes no page/product record, count, completion shard or inferred
zero, and appends one `amazon_page_unavailable_retry_exhausted` event to
`failures.jsonl`. The item's failure record (`item_failure_cycles` /
`item_failure_meta` in `state.json`, reset when the item later succeeds) then
decides. At most one failed cycle per item is counted per run, and failures are
classified:

- **Item-specific** (Amazon Page Not Found / dog page, a loaded page without the
  expected content, an unusable source image): the item is skipped when it
  fails in a second run.
- **Environment** (network errors, timeouts, HTTP 5xx/429, blank pages,
  SellerSprite data not loading, Doubao 429/5xx/timeouts, source time budget,
  every Lens candidate unscorable — usually a page-structure change):
  these do not count toward the two-run rule. The item is skipped only after 4
  such runs in which other items succeeded, or after 6 runs in any case, so an
  outage never wipes out healthy work and nothing loops forever. The run's
  `run_summary.json` carries a `resume_at` about 10 minutes later; wait until
  then before re-running.
- Never skip while the failure is the third in a row in the current run (an
  outage in progress): the run stops (exit 20) instead.

Until an item is skipped: supervised keeps it first in the queue and exits 20
(`retry_later`); unattended defers it to the end of the queue and continues.
Skipped items are recorded in `skipped_items` and `failures.jsonl`
(`quarantined_after_repeated_failures`); a run that finishes with skipped items
exits 10 (`completed_with_skips`).

A run never reports completion while deferred items remain; it exits 20
instead. If the previous process was merely interrupted during a scheduled
wait, the remaining persisted wait takes precedence and the current cycle
continues.

## Amazon Delivery Location

All five crawler templates enable marketplace-specific delivery selection:

- `delivery_location_enabled`: default `true`.
- `delivery_locations_file`: default
  `config/amazon_delivery_locations.json`.
- `delivery_location_timeout`: automatic attempt timeout in seconds; default
  `20`.
- Manual-action timeout is fixed by `operation_mode`: supervised 900 seconds;
  unattended saves its checkpoint and exits immediately.

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
visible browser. The crawler re-checks the page by itself every few seconds
(no terminal input is needed); creating `outputs/<job_id>/CONTINUE` forces an
immediate re-check. If the location is still unconfirmed after 15 minutes
(supervised; unattended exits immediately), the run stops with
`delivery_location_unconfirmed` (exit 30) and does not write records for that
page. The delivery mapping digest is part of
the non-sensitive resume fingerprint: if an existing job already has records
and the mapping changed, use a new `job_id` instead of mixing results.

Changing delivery location updates Amazon cookies in the dedicated Chrome
Profile. It may change price, availability, delivery promises, and search
results.

## SellerSprite Readiness

Storefront mode applies a per-ASIN rendered-card gate before its existing page
extraction. A 40-second budget covers scrolling and a 10-second stable period.
A card is complete when it is visible without active loading indicators and
parent/child 30-day sales, FBA fee and gross margin each show a rendered value:
numbers (including negative ones such as `-12%`), `N/A`, `0`, `< 5`, and
placeholders `--`, `-`, `—`, `暂无`, `无` all count. Only those four fields decide;
empty optional labels do not block.

The page is written when at least 95 % of the selected non-sponsored cards are
complete (allowed incomplete cards = floor(cards × 5 %), so pages with fewer
than 20 cards still need every card). Incomplete cards are written with blank
plugin fields and `plugin_fields_status: "插件字段未加载"` (complete cards:
`"完整"`), shown in the workbook. Below the threshold the page is not written;
it counts as a failed cycle for that page (see "Amazon Page Availability And
Retry"), so a page that never loads is skipped after its second cycle.
The `sellersprite_min_enriched_records` and `sellersprite_stable_checks` settings
continue to govern other front modes.

Use these fields for SellerSprite-enriched modes:

- `sellersprite_required`: fail closed when actual plugin data is unavailable.
- `sellersprite_min_enriched_records`: minimum ASIN records with plugin fields;
  default 1.
- `sellersprite_min_fields_per_record`: minimum SellerSprite-only fields per
  qualifying ASIN; default 2.
- `sellersprite_stable_checks`: consecutive identical data checks required
  before writing; default 3.

`sellersprite-check` prints a JSON report whose `status` maps to the shared exit
codes: `ready` (0); `data_loading` / `page_unavailable` (20, try again later);
`plugin_absent`, `login_required`, `blocked`, `browser_unreachable` (30, the user
must act in the dedicated Chrome — install/load SellerSprite, log in, complete a
verification, or start the browser); `config_error` (40); `risk_pause` (21);
`lock_held` (50). Title, price, rating, empty plugin tables, and plugin DOM nodes
without parsed SellerSprite fields do not satisfy the gate, and Amazon's own
`nav-sprite` header classes are not counted as plugin nodes.

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

Pagination stops on: no next link, the page cap, an empty page, a repeated
URL or repeated ASIN set, or a next link that is not a results page (product
`/dp/` links, another host, or leaving the search list are rejected as
`invalid_next_url`).

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

Only one crawler process may run per computer user (machine-wide lock in
`~/.lc-amazon-data-crawl/safety/crawler.lock`, plus a per-job
`outputs/<job_id>/.run.lock`). A second invocation exits 50 (`lock_held`),
names the running process and job, and does not touch the browser. Wait for the
running crawl instead of starting another.

## Page Preload Scroll

Before extracting each page, front/category/image enrichment flows should scroll the visible browser downward so Amazon lazy-loaded product cards and SellerSprite-injected fields have a chance to render.

Configurable fields: `page_scroll_before_extract` (default true; keep enabled for
SellerSprite-enriched crawls) and `page_scroll_step_ratio` (step as a fraction
of the viewport). Round counts and per-step waits are set by `operation_mode`.
The scroll is adaptive: it moves on quickly while nothing new appears and stops
after two stable bottom checks; the SellerSprite readiness gate that follows
remains the real guarantee that plugin fields are present.

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
- `keyword_max_records`: 默认 2000；正整数或 `"all"`，同一关键词不同排序共用。
- `entry_mode`: `current_tab` 或 `batch`；`browser_backend`: `opencli`。
- `keyword_sort_orders`: one or more supported sort labels.
- `include_sponsored`: 默认 true；设为 false 时导出必须包含可识别广告标识。

## Storefront Crawl

Use `config/amazon_front_storefront.json`.

Input file columns:

- `store_url`: Amazon storefront/search URL, commonly a URL containing `me=<seller id>`.
- `store_name`: optional display name.

Important fields:

- `mode`: `storefront`
- `store_urls_file`: CSV/XLSX path.
- `store_sort_orders`: one or more supported sort labels.
- `store_max_records`: 默认 1008；正整数或 `"all"`，同一店铺不同排序共用。
- `entry_mode`: `current_tab` 或 `batch`；`browser_backend`: `opencli`。
- 旧分页参数与断点不能直接复用，参见 [迁移说明](plugin-collection.md)。

## BSR/New Releases Category URL (recursive)

Use `config/amazon_front_bsr_category.json` when the user provides a Best
Sellers / New Releases URL. The URL itself is always crawled, and its child
categories are crawled recursively through the category crawler; the result is
`dedup_total.xlsx` (ASIN-deduplicated, written even after an early stop). The
category runner's intermediate `total_<job_id>_merged.xlsx` is removed so there
is a single workbook; all records stay in `records.jsonl`.

Important fields:

- `mode`: `bsr_category`
- `start_url`: Amazon category/ranking URL.
- `max_depth` (default 3) and `max_pages_per_category` (default 2 — ranking
  lists have two pages of 50) apply when absent or empty. Set `max_depth: 0`
  to crawl only the given URL.
- `max_pages_per_keyword` is not used for this mode.

## Recursive Category Rank Crawl

Use `config/category_rank_crawler.json` when the user wants a category node and all child category nodes.

Important fields:

- `start_url`: Amazon Best Sellers/New Releases category node.
- `include_root`: true to also crawl the starting node itself.
- `max_depth`: recursion depth below the start node; absent or `""` means 3,
  `0` means the start node only, `null` means unbounded.
- `max_pages_per_category`: page cap per category; absent or `""` means 2
  (ranking lists have two pages of 50), `null` means unbounded (hard cap 50).
- `max_categories`: optional total of crawled categories across resumes
  (skipped intermediate nodes do not count), useful for test runs.
- Caps are not part of the resume fingerprint: lowering `max_depth` or
  `max_pages_per_category` on a job in progress is allowed and drops queued
  work beyond the new cap; raising them on a job with progress is rejected
  (exit 40) — use a new `job_id`, because categories already finished under the
  lower cap would otherwise stay short.
- If the start node shows no child categories, the run warns and records
  `children_discovery_zero: true` in `state.json`/`run_summary.json`.

## Image Competitor Crawl

找同款已改为日常 Chrome + OpenCLI，在固定标签使用图片网址搜索。启动前必须确认退出卖家精灵登录，不使用旧 CDP／上传流程。配置、输入、数量、后台约束及旧任务迁移以 [image-background.md](image-background.md) 为准。

默认 `entry_mode=batch`、`result_mode=count_only`、`match_mode=cascade`、每来源最多 48 个候选。支持 ASIN、商品链接、当前商品页或公开图片网址；仅本地图片须补充链接。detail 也可用 cascade，并保留来源状态页。模型阈值、最多 10 个粗筛命中和第 11 个命中早停的规则保持下文语义。

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
`counts.jsonl` are deterministic materializations of those shards. While a
source is still in progress, every returned embedding vector, Mini batch verdict
and the Lens candidate list are saved immediately under
`source_progress/<row>-<hash>/` (bound to the source, provider and plan
fingerprints), so a crash, provider error or restart never re-navigates or
re-pays completed work; the folder is removed once the source is committed. Use a
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

Plugin waits, retries and manual-action windows are fixed by `operation_mode`
(see "Safety Pause"). Supervised list pages wait 40 seconds for SellerSprite
data, extended once to 80 seconds when new cards or required fields appear in
the last 10 seconds; storefront pages have a 40-second total budget;
unattended waits up to 180 seconds. The workflow never refreshes the page or
relaunches Chrome automatically.

To judge whether a run is stuck, read `outputs/<job_id>/run_heartbeat.json`:
`phase` `waiting` (with a future `until`), `retry_wait`, `plugin_wait` or
`manual_wait` is a planned wait; otherwise an
`updated_at` older than 5 minutes, or a dead `pid` without `phase: exited`, is a
stall. Then inspect the log, `state.json`, the visible Chrome page and
`failures.jsonl` before restarting anything.
