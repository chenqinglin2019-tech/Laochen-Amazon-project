---
name: lc-amazon-data-crawl
description: 采集 Amazon 关键词搜索、类目榜单、店铺和图片相似竞品数据，并可结合卖家精灵字段与筛选条件导出。
metadata:
  last_updated: 2026-10-15
---

# 易逊-亚马逊数据采集

关键词与店铺使用日常 Chrome + OpenCLI 操作卖家精灵面板：加载更多 → 原生导出 → 校验、截取、去重与筛选。完整说明见 `references/plugin-collection.md`。找同款也使用日常 Chrome 后台标签，开始前必须确认退出卖家精灵登录，详见 `references/image-background.md`。只有类目保留原 CDP 流程。

| Mode (config template) | What it crawls |
|---|---|
| `keyword_search` (`amazon_front_keyword_search.json`) | 每个关键词默认最多 2000 条，排序共享预算 |
| `storefront` (`amazon_front_storefront.json`) | 每个店铺默认最多 1008 条，排序共享预算 |
| `bsr_category` (`amazon_front_bsr_category.json`) | a Best Sellers / New Releases URL **and its child categories** (recursive; start page always included; defaults `max_depth: 3`, `max_pages_per_category: 2`) → `dedup_total.xlsx` |
| `category-rank` (`category_rank_crawler.json`) | recursive category tree from `start_url` (`include_root` decides whether the start node itself is crawled) |
| `image-competitor` (`amazon_image_competitors.json`) | 每来源默认 48 个候选，图片网址搜索 + Doubao cascade；运行前确认退出插件登录 |

## Hard rules

1. **Cloud auth gate first.** Before editing configs, installing, opening Chrome,
   dry-run or crawling, run `bash "<runner or skill dir>/scripts/check_auth.sh"`
   (Windows: `powershell -ExecutionPolicy Bypass -File "<dir>\scripts\check_auth.ps1"`). Never run
   `tools/bin/lc-auth-check-*` directly. On failure stop and preserve the entry's safe output: the first line is
   `云端鉴权未通过，本轮不继续执行。`, followed by a fixed redacted reason.
   Configuration conflicts, network/service failures and account rejection are distinct;
   network failure does not prove an invalid token. A "启动准备失败" message is a local setup problem.
   Never print native stdout/stderr or backend bodies. Runner commands re-check auth themselves.
2. **Never log in to Amazon.** If Amazon shows a sign-in page the run stops; say exactly:
   `Amazon 弹出了登录页；本工具不使用也不需要 Amazon 买家账号，本条采集已停止。请稍后重试，不要登录买家账号。`
   SellerSprite login (in the extension) is separate and may be needed.
3. **Secrets stay in files.** Cloud token: `config.local.json` (written by the installer or `configure_credentials.py`; legacy nonempty `config.json` is supported).
   Ark keys: `config/doubao_embedding_vision.json` and `config/doubao_same_product_mini.json`.
   Never ask the user to paste a key into chat, never print one.
4. **One crawl per computer.** Never start a second crawl command while one runs
   (it exits 50 anyway). Never delete files under `~/.lc-amazon-data-crawl/safety/`
   by hand; use `safety-status` / `safety-clear`.
5. 使用各流程已定义的频率策略，不临时绕过间隔、休息或风险暂停。用户明确修改频率时，同步更新实现、说明与模拟时钟测试；频率不作为任意配置字段。
6. **原始下载表无损合并。** 凡基于下载表格合并，必须保留原始表的所有字段及顺序、图片、颜色、字体、数字格式、列宽、行高、布局、链接、冻结和其他格式。不得从标准化 JSON 字段重建简化表，不添加替代模板或审计工作表。店铺/关键词使用 `scripts/native_export_merge.py`（正式输出自动调用）；跨任务或旧断点重合并用 `scripts/merge_plugin_outputs.py`。无法完整保留时明确报错、保留原文件和已有成品，修复兼容性后再本地合并，禁止静默降级。详见 `references/plugin-collection.md` 的“原生格式合并”。

## Install / update

The installer reads the token from a hidden prompt, so **the user runs it in their own terminal**:

- macOS/Linux: `bash /path/to/lc-amazon-data-crawl/scripts/install_for_user.sh`
- Windows: `powershell -ExecutionPolicy Bypass -File C:\path\to\lc-amazon-data-crawl\scripts\install_for_user.ps1`

It creates `lc-amazon-data-crawl-runner` beside the skill, installs Python deps and runs `doctor`.
关键词/店铺需要 OpenCLI CLI、日常 Chrome 中的 Browser Bridge 和卖家精灵，不需要测试浏览器。只有类目旧流程缺少专用浏览器时才使用 `install-browser`。
After updating the skill, refresh an existing runner (keeps task configs, inputs, outputs and model API keys; synchronizes the verified cloud token):
`bash "$SKILL_DIR/scripts/setup_runner.sh" <runner>` (Windows: `powershell -ExecutionPolicy Bypass -File scripts\setup_runner.ps1 <runner>`).

All commands below run inside the runner (`./lc-amazon-data-crawl.sh …` on macOS/Linux,
`.\lc-amazon-data-crawl.cmd …` on Windows; same command names):

```
install | install-browser | doctor
amazon-front-dry-run / amazon-front-run          --config config/<front config>.json
category-rank-dry-run / category-rank-run        --config config/category_rank_crawler.json
image-competitor-dry-run / image-competitor-run  --config config/amazon_image_competitors.json
sellersprite-check --config <config>     cdp-browser-start --config <config>
safety-status                            safety-clear --confirm-reviewed
plugin-export-review [--confirm-no-active-download]
front/image: --rebind
image: --confirm-sellersprite-logged-out, --migrate-from-job OLD_JOB_ID
options for *-run: --operation-mode supervised|unattended, --resume-after-review, --no-resume
```

## 云端 token 配置与替换

- 鉴权入口使用现有原生程序和 `/public/account` 协议，具体规则见 [references/authentication.md](references/authentication.md)。鉴权准备使用 Python 3.8+ 标准库；采集运行时仍按原要求使用 Python 3.10+。
- 空的本地 token 不覆盖可用的旧 `config.json`；本地 token 可继承公开配置的 backend_url。两个非空 token 不同时明确报告配置冲突，不静默尝试另一个账户。显式替换统一写私有 `config.local.json` 并清空旧公开 token，保留其他字段。
- 用户主动提供本 Skill 的新鉴权 token 时，自动用 `scripts/configure_credentials.py` 接收标准输入 JSON（`backend_token` 字段，可选 `backend_url`）；不回显、不嵌入 shell 命令文本／参数／临时脚本，不把第三方 API key 当作云端 token。随后运行原 `check_auth` 门禁，通过后对本次已知 runner 执行 `setup_runner` 并复核 runner 的门禁，再继续原任务。不要只写 Skill 却继续使用 runner 的旧凭据。
- 用户在自己的终端替换：macOS/Linux 为 `bash scripts/install_for_user.sh <runner> --replace-token`；Windows 为 `powershell -ExecutionPolicy Bypass -File scripts\install_for_user.ps1 <runner> -ReplaceToken`。输入保持隐藏，更新流程验证后同步已有 runner。
- 安装内 10 分钟复用只适用于相同 backend_url/token 的已验证凭据；换 token 必须重验。正式采集每次重新鉴权，无自动鉴权重试。网络、配置与账户失败均先停止，按脱敏原因恢复；不得绕过门禁。

## Task workflow

1. Copy the matching template in `config/` to a new file and give it a **new `job_id`**
   (a job_id is a checkpoint; reuse it only to resume the same task).
2. Put the user's input (CSV/XLSX) in `inputs/` and point the config at it.
   Columns: keywords `keyword`/`关键词`/`search_term`; stores `store_url`(+`store_name`);
   images `ASIN`, `商品URL`, `主图URL`；仅本地图片必须补充链接。
3. Set only business fields: marketplace/start URL, sorts, quantity limits (keyword/store) or page limits (legacy category), `include_sponsored`,
   `product_filters`, image `result_mode`/`match_mode`. See `references/configuration.md`.
4. Run the matching `*-dry-run`. Fix every error before a real run (exit 40 = config error).
5. 关键词/店铺：用户先选好日常 Chrome 工作标签，脚本绑定并固定 ID。之后可以切去其他页面或应用。不得启动测试浏览器、切换窗口/标签、移动系统鼠标或读取插件内部变量。可运行 `sellersprite-check` 核对已打开的面板。找同款也遵守上述后台约束，并先取得本次退出卖家精灵登录的明确确认；只有类目检查专用 Profile。
6. Start the real run **in the background with output to a log file** (crawls take minutes to
   hours), e.g. `nohup ./lc-amazon-data-crawl.sh amazon-front-run --config config/x.json > outputs/x.log 2>&1 &`
   (Windows: `Start-Process` with `-RedirectStandardOutput`). Do not run it as a blocking command
   that your tool may kill; never start it twice.
7. Supervise (next section), then deliver the workbook and summarize `run_summary.json`.

## 关键词与店铺约束

- 默认每店铺 `store_max_records: 1008`、每关键词 `keyword_max_records: 2000`。明确数量覆盖默认；明确全部才设 `"all"`。先按导出顺序截取，再去重筛选，不补抓。
- `entry_mode=current_tab|batch`；batch 也只导航同一绑定标签。明确标签关闭、网址或文档被改就停；读取超时按下述只读恢复规则处理；人工选好替代页后用 `--rebind`，未完成目标重采并替换快照。
- 每轮一次加载，等上一轮完成、数据稳定、间隔与休息到期。远程操作共享下述持久化调度，跨来源与重启不清零；DOM 每 2 秒只读检查。
- **仅关键词异常恢复**：正常流程不增加等待、读取或结束复核。关键词已发出的加载先观察 180 秒，异常才延长至单次累计 600 秒有效观察；条数不增且按钮消失、点击回复丢失均保留待确认，不能判完成或盲目补点。明确的本轮失败/确认未点击才按原 60 秒一次（有人值守）或 120、300 秒两次（无人值守）重试。断点先确认旧加载，预算跨重启保留，连接不可观察时间排除；到期返回 20。详见 plugin-collection.md“仅关键词加载恢复”；店铺原行为保持不变。
- 店铺商品页在 Amazon 主搜索区明确显示无搜索结果且连续稳定 10 秒时，视为店铺消失或暂无可售商品，记录 `store_no_results` 和 `skipped_items`，直接跳过并继续下一店铺；不操作缺失的插件控件，不导出空文件。验证码、加载超时、仅插件无数据不能据此跳过。
- 默认结束时导出一次；每 100 次成功加载做中间导出，恰好结束合并最终导出。全局导出间隔至少 60 秒；未确认下载不得重点击，明确失败只重试一次。
- 区分 `limit_reached` 和 `source_exhausted`；数量不符保留原文件并报告部分完成。插件显示“2000 条上限”须以真实文件核对，不能假定不存在截断。
- 旧分页参数/断点必须显式迁移到新模板和新 job_id，不换算为加载轮数。所有细节以 `references/plugin-collection.md` 为准。

## 找同款约束

完整配置、恢复与迁移见 `references/image-background.md`。必须先提醒用户退出卖家精灵账号并保持插件启用，取得本次任务确认后才能传 `--confirm-sellersprite-logged-out`；不得从历史确认或用户要求开始采集推断退出。后台未确认则退出 30，不查询。

- 固定日常 Chrome 标签，读取公开 DOM 主图网址并在同标签打开 `/stylesnap?q=…`；不点击会激活新标签的原按钮，不下载再上传图片，不使用插件私有接口。
- `entry_mode=batch|current_tab`，默认每来源最多 48 个候选，`count_only` + `cascade`。纯本地图片报错。实际数量只代表采集范围。
- 找同款不调用登录后的插件指标或导出。普通登录入口不算故障；明确仍已登录则停止并提醒退出。店铺和关键词的登录要求保持独立。
- cascade 按批流式粗筛：每批候选稳定后立即复用现有 Embedding 规则，累计视觉命中超过 10 个即停止后续加载、记录 `prescreen_excluded` 并进入下一产品；未超限才继续到原采集结束条件，然后按原规则调用 Mini。提前排除不写成精确同款数；部分候选和向量保存断点。
- 模型优先使用图片网址，必要时仅在内存转码并有界缓存复用；已有候选和成功模型结果必须复用。普通阶段失败自动恢复一次，连续失败留空并继续后续来源；风险、身份变化与凭据错误不自动重试。未完成导航先核对原标签；已确认到达目标且有主图／候选但文档持续加载时，按原节流规则仅重新加载一次，预算跨重启保留；未知导航不重放，标签丢失仍需人工 `--rebind`。同文档且 DOM ASIN 一致的商品页允许 `th=1` 规范化改写；身份校验异常保存脱敏差异，详见 image-background.md。
- 旧任务用新配置、新 job_id 和 `--migrate-from-job` 显式迁移，原输出保持不动。不得把旧上传／CDP 配置静默继续执行。

## OpenCLI 只读自动恢复

关键词、店铺、找同款共用 `scripts/opencli_read_recovery.py`。已绑定原标签的读取暂态故障先等 2、2 秒，再等 30、60、120 秒，之后每 300 秒复核；从首次失败调用开始累计最多 30 分钟，含命令耗时，跨进程保留期限。只重试原标签状态、公开 DOM 快照和下载状态读取，不自动重放加载、导出、导航、滚动或绑定。具体保护、例外和测试见 [references/opencli-read-recovery.md](references/opencli-read-recovery.md)。

恢复时复核原标签身份及页面风险；断线时间不消耗业务观察预算，连续稳定计时重新开始。现有判断、远程操作计数、间隔与休息不变。到期返回 `retry_later`（20），保留当前来源与待确认操作，不跳过、不写零、不转成普通加载重试。人工修复后重跑原命令可做只读复核，失败即退出，不重新获得 30 分钟预算。

## Supervising a run

Check every few minutes, not continuously. Read `outputs/<job_id>/run_heartbeat.json`
(`pid`, `phase`, `updated_at`, optional `until`, `detail`) and the log tail.

- `phase` `waiting` (rest/cooldown with a future `until`: 插件 1–1.5 / 2–3 min；旧类目 3–5 / 10–12 / 15–20 min), `retry_wait`,
  `plugin_wait`, `bridge_retry_wait` or `manual_wait` are planned waits. Do **not** report them as a stall or restart anything.
- Healthy otherwise: `updated_at` changed within the last 5 minutes.
- Stalled: the pid is gone without `phase: exited`, or no update for > 5 minutes outside a wait.
  Then read the log tail and `state.json`, tell the user what the page is doing, and only then
  stop/restart.
- 关键词/店铺需要人工处理时保存断点并退出；处理后重跑原命令。不要为此创建 CONTINUE 文件。
- Legacy category manual actions (CAPTCHA by day, delivery address, SellerSprite login): tell the user which
  visible Chrome page needs attention. The crawler re-checks the page by itself every few seconds;
  if the user says it is done and it has not continued, create the file `outputs/<job_id>/CONTINUE`.

## When a run ends: exit code → next step

`outputs/<job_id>/run_summary.json` always holds `status`, `message`, `next_action`, `resume_at`
and `skipped_items`. Follow `next_action`; the table is the same rule:

| Exit | status | Do this |
|---|---|---|
| 0 | completed | Deliver the workbook. |
| 10 | completed_with_skips | Deliver; list `skipped_items` (明确无搜索结果的店铺直接跳过；其他旧流程为 bounded retries exhausted, new image sources may exhaust both cycles in one run). The same job_id will not retry them; to try again later, run a new job with only those inputs. |
| 20 | retry_later | Temporary failure, checkpoint saved. If `resume_at` is set (network/platform outage), wait until then; otherwise re-run the same command. Legacy category items may be skipped after repeated item failures; plugin jobs preserve the current target. |
| 21 | risk_pause | Amazon/SellerSprite risk signal. 店铺/关键词明确验证码在用户确认本次验证通过后，可立即加 `--resume-after-review` 提前复核；其他风险不得提前恢复。Otherwise do not re-run before `resume_at`. Afterwards ask the user to confirm the browser shows normal pages, then run once with `--resume-after-review`. Any pending item can serve as the review probe; the pause clears only when that page loads cleanly. |
| 30 | needs_human | Tell the user the concrete action in `next_action` (CAPTCHA, delivery address, SellerSprite login, close/relaunch the dedicated Chrome, install-browser). Re-run after they confirm. |
| 40 | config_error | Fix config/input, dry-run again. |
| 50 | lock_held | Another crawl is running on this computer. Wait; do not start another. |
| 2 | error | Report the message; do not retry blindly. Auth failures exit 2/3/4 from `check_auth`. |

`safety-status` shows any active risk pause, its `not_before`, and whether a crawl is running.
`safety-clear --confirm-reviewed` removes an **expired** pause after the user confirmed the
browser is fine (it never shortens an active one).

## Operation modes (fixed in code)

新版找同款：`supervised` 间隔 4–6 秒，每 20 次休息 20–35 秒，每 100 次改为 1–2 分钟；`unattended` 间隔 8–15 秒，每 10 次休息 20–35 秒，每 100 次改为 2–3 分钟。共用持久化计数，百次休息不叠加短休息。普通错误自动恢复范围和停止条件见 `references/image-background.md`。

关键词/店铺插件流程：远程操作间隔保持 supervised 20–30 秒、unattended 45–75 秒。supervised 每 20 次休息 1–1.5 分钟，每 100 次改为 2–3 分钟、不叠加；unattended 每 10 次休息 2–3 分钟，不另设百次长休息。计数与期限跨来源和重启持久化，插件稳定/重试/导出等待保持原规则，详见 references/plugin-collection.md。

关键词/店铺明确验证码（Amazon 或卖家精灵的 captcha_or_robot_check）：两种模式均立即保存断点退出，默认风险暂停 24 小时。用户明确确认本次验证码已通过后，可立即用原命令加 --resume-after-review 提前复核恢复；仍有验证码则再次停止。其他风险仍遵守原暂停期限。旧类目与找同款不适用此提前恢复规则。

以下原频率仅保留给旧类目流程（关键词/店铺普通故障等待仍使用下列同模式时间）：

- `supervised` (default): 20–30 s between remote actions (navigation, plugin queries, loads, retries, exports); rest 3–5 min after every 20, 10–12 min after
  every 100; one retry after 60 s for a temporary page failure; legacy plugin data waits 40 s (once
  extended to 80 s on progress); store panels wait up to 180 s without re-clicking; keyword load exceptions use the keyword-only recovery above. Legacy manual actions wait up to 15 min.
- `unattended`: 45–75 s spacing; 15–20 min rest after every 10; retries after 2 and 5 min, then the
  item is deferred to the end of the queue; plugin waits up to 180 s; anything needing a human
  saves the checkpoint and exits (CAPTCHA at night always stops).
- Risk signals (403/429, CAPTCHA, "too many requests", access denied, SellerSprite quota/rate/
  account messages) pause **all** crawls on this computer: a first rate limit for ≥30 min then one
  automatic probe; repeats, denial and account restriction for 24 h with manual review.
- A legacy item (page/category/old image source) that fails in two different runs for an item-specific
  reason (not found, broken page, unusable image) is skipped and recorded instead of blocking the
  job. Outage-type failures (network, timeouts, 5xx, plugin data not loading) do not count that way;
  see `references/configuration.md` "Amazon Page Availability And Retry".

## Outputs (`outputs/<job_id>/`)

- Front modes: `records.jsonl`, `dedup_total.xlsx`, `quality_report.json`.
- category-rank: `records.jsonl`, `total_<job_id>_merged.xlsx`.
- image-competitor: `*_相似竞品数量.xlsx` (count mode) or the detail workbook; cascade columns are
  explained in `references/configuration.md#cascade-matching-semantics`.
- Always: `state.json` (checkpoint), `run_summary.json`, `run_heartbeat.json`, optional `failures.jsonl`.
- Image: `image_collection_report.json`，迁移时的 `migration_report.json`，明细模式包含来源状态页。
- Keyword/store: `raw_exports/` 保留原生文件及校验报告；`dedup_total.xlsx` 使用原生下载表全部字段、图片和格式，不再输出固定字段简化表；审计信息仅写 JSON。数量/字段问题显式报告，不用旧卡片提取来补足。

## References

- `references/image-background.md` — 找同款未登录确认、后台搜索、输入、模型与迁移。

- `references/plugin-collection.md` — 关键词/店铺新流程、数量、节流、原生文件、恢复与迁移。
- `references/configuration.md` — every config field, product filters, fulfillment parsing,
  delivery location, SellerSprite readiness, cascade semantics, browser/tab ownership, checkpoints.
- `references/delivery-locations.md` — fixed postal codes per marketplace.
- Historical fulfillment repair (old jobs): `.venv/bin/python scripts/repair_fulfillment_outputs.py` —
  see configuration.md "Historical fulfillment sidecar repair".

## Maintenance

Update `scripts/`, `assets/config/` and this file together; run `python3 tests/run_non_browser_tests.py` (isolates traffic state and excludes the real browser integration test).
Build distributable zips only with `python3 scripts/package_skill.py` (excludes caches, local
credentials, outputs and profiles, and refuses a populated `config.json` token). Never publish
`config.local.json`, populated Doubao files, browser profiles, cookies or crawl outputs.
