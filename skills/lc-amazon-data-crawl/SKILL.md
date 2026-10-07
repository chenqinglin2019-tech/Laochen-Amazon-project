---
name: lc-amazon-data-crawl
description: 采集 Amazon 关键词搜索、类目榜单、店铺和图片相似竞品数据，并可结合卖家精灵字段与筛选条件导出。
metadata:
  last_updated: 2026-10-07
---

# 易逊-亚马逊数据采集

Local crawler for public Amazon pages in a visible Chrome (CDP), enriched by the
user's own SellerSprite (卖家精灵) extension. This file is the operating runbook;
field-level details live in `references/configuration.md`.

| Mode (config template) | What it crawls |
|---|---|
| `keyword_search` (`amazon_front_keyword_search.json`) | search results per keyword × sort, `max_pages_per_keyword` pages |
| `storefront` (`amazon_front_storefront.json`) | seller storefront lists per store × sort, 1–20 pages or explicit `all` to natural end |
| `bsr_category` (`amazon_front_bsr_category.json`) | a Best Sellers / New Releases URL **and its child categories** (recursive; start page always included; defaults `max_depth: 3`, `max_pages_per_category: 2`) → `dedup_total.xlsx` |
| `category-rank` (`category_rank_crawler.json`) | recursive category tree from `start_url` (`include_root` decides whether the start node itself is crawled) |
| `image-competitor` (`amazon_image_competitors.json`) | same-product competitor counts via Find Similar / Amazon Lens + Doubao cascade |

## Hard rules

1. **Cloud auth gate first.** Before editing configs, installing, opening Chrome,
   dry-run or crawling, run `bash "<runner or skill dir>/scripts/check_auth.sh"`
   (Windows: `powershell -ExecutionPolicy Bypass -File "<dir>\scripts\check_auth.ps1"`). Never run
   `tools/bin/lc-auth-check-*` directly. On failure stop and say only:
   `云端鉴权未通过，本轮不继续执行。` (A "启动准备失败" message is a local setup problem,
   not an invalid token — report it as such.) Runner commands re-check auth themselves.
2. **Never log in to Amazon.** If Amazon shows a sign-in page the run stops; say exactly:
   `Amazon 弹出了登录页；本工具不使用也不需要 Amazon 买家账号，本条采集已停止。请稍后重试，不要登录买家账号。`
   SellerSprite login (in the extension) is separate and may be needed.
3. **Secrets stay in files.** Cloud token: `config.local.json` (written by the installer).
   Ark keys: `config/doubao_embedding_vision.json` and `config/doubao_same_product_mini.json`.
   Never ask the user to paste a key into chat, never print one.
4. **One crawl per computer.** Never start a second crawl command while one runs
   (it exits 50 anyway). Never delete files under `~/.lc-amazon-data-crawl/safety/`
   by hand; use `safety-status` / `safety-clear`.
5. Do not change timing/traffic values to "speed up": spacing, rests, retries and
   plugin waits are fixed by `operation_mode` in code and are not config keys.

## Install / update

The installer reads the token from a hidden prompt, so **the user runs it in their own terminal**:

- macOS/Linux: `bash /path/to/lc-amazon-data-crawl/scripts/install_for_user.sh`
- Windows: `powershell -ExecutionPolicy Bypass -File C:\path\to\lc-amazon-data-crawl\scripts\install_for_user.ps1`

It creates `lc-amazon-data-crawl-runner` beside the skill, installs Python deps and runs `doctor`.
If `doctor`/a run reports that Chrome for Testing is missing, run `install-browser` once.
After updating the skill, refresh an existing runner (keeps configs, inputs, outputs, credentials):
`bash "$SKILL_DIR/scripts/setup_runner.sh" <runner>` (Windows: `powershell -ExecutionPolicy Bypass -File scripts\setup_runner.ps1 <runner>`).

All commands below run inside the runner (`./lc-amazon-data-crawl.sh …` on macOS/Linux,
`.\lc-amazon-data-crawl.cmd …` on Windows; same command names):

```
install | install-browser | doctor
amazon-front-dry-run / amazon-front-run          --config config/<front config>.json
amazon-front-supervise                          --config config/<store or keyword config>.json
verify-output --job outputs/<job_id> [--live]
category-rank-dry-run / category-rank-run        --config config/category_rank_crawler.json
image-competitor-dry-run / image-competitor-run  --config config/amazon_image_competitors.json
sellersprite-check --config <config>     cdp-browser-start --config <config>
safety-status                            safety-clear --confirm-reviewed
options for *-run: --operation-mode supervised|unattended, --resume-after-review, --no-resume
```

## Task workflow

1. Copy the matching template in `config/` to a new file and give it a **new `job_id`**
   (a job_id is a checkpoint; reuse it only to resume the same task).
2. Put the user's input (CSV/XLSX) in `inputs/` and point the config at it.
   Columns: keywords `keyword`/`关键词`/`search_term`; stores `store_url`(+`store_name`);
   images `ASIN`, `商品URL`, `主图URL`, `本地图片路径`.
3. Set only business fields: marketplace/start URL, sorts, page limits, `include_sponsored`,
   `product_filters`, image `result_mode`/`match_mode`. See `references/configuration.md`.
4. Run the matching `*-dry-run`. Fix every error before a real run (exit 40 = config error).
5. If SellerSprite fields are required, run `sellersprite-check` once on a new profile.
6. Start the real run **in the background with output to a log file** (crawls take minutes to
   hours), Storefront/keyword default to `nohup ./lc-amazon-data-crawl.sh amazon-front-supervise --config config/x.json > outputs/x.log 2>&1 &`; category runs retain `amazon-front-run`
   (Windows: `Start-Process` with `-RedirectStandardOutput`). Do not run it as a blocking command
   that your tool may kill; never start it twice.
7. Supervise (next section), then check `data_quality`, `scope_completion` and `delivery_ready` in `run_summary.json` before delivery.
8. Ignoring an Amazon buyer-account login suggestion never changes `sellersprite_required`. Keep it true for enriched data; false is only for an explicitly requested basic-data task.
9. Record each newly discovered runtime failure immediately in the workspace `运行报错.md`: evidence, affected job, root cause or uncertainty, mitigation and validation status. Append corrections and preserve history.

## Supervising a run

Check every few minutes, not continuously. Read `outputs/<job_id>/run_heartbeat.json`
(`pid`, `phase`, `updated_at`, optional `until`, `detail`) and the log tail.

Storefront and keyword long tasks use `amazon-front-supervise`; `amazon-front-run`
remains one attempt. The supervisor continues retryable exits automatically at
`resume_at`, validates this attempt's heartbeat/commits, and stops on auth failure,
risk pause or human action. No repeated chat message “继续” is needed. Run only one
supervisor; it holds a separate machine lock and the child holds the crawl lock.
`supervisor.json` records the supervisor's final reason and `exit_code`, plus the
last child's separate `child_exit_code`; it is
authoritative for recovery/manual-action stops. `run_summary.json` describes the
last collection attempt and must not be treated as a later supervisor result.

SellerSprite collection uses the dedicated foreground: actual spacing/rest ends
before checking cancellation/lock, activating the exact browser PID and its owned
tab, confirming visibility, then navigating/clicking. On macOS, lock pauses access
until unlock, up to the manual wait limit (including system sleep); unknown inspection or activation failure
requires human action. Hidden/no-frame evidence alone never proves a crash.
On macOS the supervisor holds a temporary `caffeinate -di -w <supervisor_pid>`
power assertion for required SellerSprite collection, preventing idle display/system
sleep. It releases on exit, keeps system settings unchanged, and never unlocks a
locked computer or changes manual-lock handling.

Ordinary CDP calls have a process-external 10 s watchdog; navigation and plugin
loading retain their own budgets. Screenshots have 3 s and diagnostics 10 s. If
calls stop returning, the supervisor stops the child before recovery, rebuilds
exports from immutable commits and probes an owned local blank page. A healthy
browser gets a new worker tab; two browser-level CDP failures allow restarting only
the exact executable/profile/PID/creation-time identity. Recovery itself runs in a
bounded subprocess. The profile, committed data, cooldowns and risk pauses remain.
Two browser restarts without a successful commit stop automatic recovery. Local
lock/window/browser failures without a completed page attempt do not increment
item skip counts. A real page failure retains the existing skip thresholds.

Storefront and keyword results support both traditional Next links and a main-list
**Show more results** button. Each successful click is another logical page/batch;
only new ASINs enter its commit. On restart, replay earlier clicks under normal
traffic limits, then exclude all already visited ASINs. A disappearing control can
end the source; a busy/disabled button or a click without confirmed new ASINs is a
retryable failure, never proof of completeness. Keep an already identified control
when its busy/disabled label changes to “Loading…”. Page limits count batches too.

Use `verify-output --job outputs/<job_id> --live` for a committed snapshot while
running; after the supervisor exits run it without `--live` to compare commits,
JSONL and Excel, including duplicate/extra rows and source evidence. Only `passed`
confirms extraction consistency; missing evidence is `not_evaluated`. Delivery also
requires the existing quality and scope report. Do not change historical outputs.

- `phase` `waiting` (rest/cooldown with a future `until`: 3–5, 10–12, 15–20 min), `retry_wait`,
  `plugin_wait` or `manual_wait` are planned waits. Do **not** report them as a stall or restart anything.
- Healthy otherwise: `updated_at` changed within the last 5 minutes.
- A normal interrupt during front-mode collection keeps committed pages, exports
  them before exit, and leaves the unfinished page in its checkpoint. Verify the
  final heartbeat and export result before resuming; interrupting early setup does
  not certify an export.
- Stalled: the pid is gone without `phase: exited`, or no update for > 5 minutes outside a wait.
  Then read the log tail and `state.json`, tell the user what the page is doing, and only then
  stop/restart.
- Manual actions (CAPTCHA by day, delivery address, SellerSprite login): tell the user which
  visible Chrome page needs attention. The crawler re-checks the page by itself every few seconds;
  if the user says it is done and it has not continued, create the file `outputs/<job_id>/CONTINUE`.

## When a run ends: exit code → next step

`outputs/<job_id>/run_summary.json` always holds `status`, `message`, `next_action`, `resume_at`
and `skipped_items`. Front modes also hold `data_quality`, `scope_completion`, and `delivery_ready`. Explicit source N/A is valid; missing, invalid, unloaded and unconfirmed zeros are disclosed. Exit 0 alone does not certify completeness. Follow `next_action`:

| Exit | status | Do this |
|---|---|---|
| 0 | completed | The queue ended. Deliver as complete only when `delivery_ready=true`; otherwise disclose and resolve quality/range gaps. |
| 10 | completed_with_skips | Disclose `skipped_items`, their recorded reasons and unfinished scope; do not claim full delivery. The same job_id will not retry them; to try again later, run a new job with only those inputs. |
| 20 | retry_later | Temporary failure, checkpoint saved. If `resume_at` is set (network/platform outage), wait until then; otherwise re-run the same command. Items that keep failing are skipped automatically, so this cannot loop. |
| 21 | risk_pause | Amazon/SellerSprite risk signal. Do not re-run before `resume_at`. Afterwards ask the user to confirm the browser shows normal pages, then run once with `--resume-after-review`. Any pending item can serve as the review probe; the pause clears only when that page loads cleanly. |
| 30 | needs_human | Tell the user the concrete action in `next_action` (CAPTCHA, delivery address, SellerSprite login, close/relaunch the dedicated Chrome, install-browser). Re-run after they confirm. |
| 40 | config_error | Fix config/input, dry-run again. |
| 50 | lock_held | Another crawl is running on this computer. Wait; do not start another. |
| 2 | error | Report the message; do not retry blindly. Auth failures exit 2/3/4 from `check_auth`. |

`safety-status` shows any active risk pause, its `not_before`, and whether a crawl is running.
`safety-clear --confirm-reviewed` removes an **expired** pause after the user confirmed the
browser is fine (it never shortens an active one).

## Operation modes (fixed in code)

- `supervised` (default): 20–30 s between navigations; rest 3–5 min after every 20, 10–12 min after
  every 100; one retry after 60 s for a temporary page failure; plugin data waits 40 s (once
  extended to 80 s on progress; storefront 40 s total); manual actions wait up to 15 min.
- `unattended`: 45–75 s spacing; 15–20 min rest after every 10; retries after 2 and 5 min, then the
  item is deferred to the end of the queue; plugin waits up to 180 s; anything needing a human
  saves the checkpoint and exits (CAPTCHA at night always stops).
- Risk signals (403/429, CAPTCHA, "too many requests", access denied, SellerSprite quota/rate/
  account messages) pause **all** crawls on this computer: a first rate limit for ≥30 min then one
  automatic probe; repeats, denial and account restriction for 24 h with manual review.
- An item (page/category/image source) that fails in two different runs for an item-specific
  reason (not found, broken page, unusable image) is skipped and recorded instead of blocking the
  job. Outage-type failures (network, timeouts, 5xx, plugin data not loading) do not count that way;
  see `references/configuration.md` "Amazon Page Availability And Retry".

## Outputs (`outputs/<job_id>/`)

- Front modes: `records.jsonl`, `dedup_total.xlsx`, `quality_report.json`.
- Verification stops: `block_evidence.jsonl` with visible-node evidence. Hidden DOM and buyer-account suggestions are not challenges. `CONTINUE` rechecks the page.
- category-rank: `records.jsonl`, `total_<job_id>_merged.xlsx`.
- image-competitor: `*_相似竞品数量.xlsx` (count mode) or the detail workbook; cascade columns are
  explained in `references/configuration.md#cascade-matching-semantics`.
- Supervisor/verification: `supervisor.json`, `supervisor_events.jsonl`, `runtime_watchdog.json`, `verification_live.json`, `verification_final.json`.
- Always: `state.json` (checkpoint), `run_summary.json`, `run_heartbeat.json`, optional `failures.jsonl`.
- Storefront rows whose SellerSprite card did not finish loading (≤5 % of a page) are kept with
  blank plugin fields and `插件字段未加载` in the plugin status column.

## References

- `references/configuration.md` — every config field, product filters, fulfillment parsing,
  delivery location, SellerSprite readiness, cascade semantics, browser/tab ownership, checkpoints.
- `references/delivery-locations.md` — fixed postal codes per marketplace.
- Historical fulfillment repair (old jobs): `.venv/bin/python scripts/repair_fulfillment_outputs.py` —
  see configuration.md "Historical fulfillment sidecar repair".

## Maintenance

Update `scripts/`, `assets/config/` and this file together; run `python3 -m unittest discover -s tests` for offline regression. Run browser tests separately with `LC_RUN_BROWSER_TESTS=1`. A stability release also needs a new isolated job with ≥100 verified pages/batches and `save_page_evidence:true`, covering short and long rests; launching it alone is not acceptance. Confirm cached country/BSR evidence reaches records and final Excel, including recycled cards.
Build distributable zips only with `python3 scripts/package_skill.py` (excludes caches, local
credentials, outputs and profiles, and refuses a populated `config.json` token). Never publish
`config.local.json`, populated Doubao files, browser profiles, cookies or crawl outputs.
