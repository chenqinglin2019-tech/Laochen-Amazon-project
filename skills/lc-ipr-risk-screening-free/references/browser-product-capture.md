# Amazon browser capture contract

Use visible Chrome desktop through `tools/cdp/cdp-cli.mjs capture-amazon`. Run credential preflight first. The CDP launcher uses a dedicated non-default profile and a loopback-only random port. Do not inspect cookies, local storage, the default browser profile, or passwords. If Amazon requires authentication or CAPTCHA, preserve the visible page and let the user complete it.

Save a UTF-8 JSON object with:

```json
{
  "browser": "chrome_desktop",
  "capture_transport": "cdp",
  "browser_version": "Chrome/150.0.7871.187",
  "protocol_version": "1.3",
  "cdp_session_id": "sanitized-session-id",
  "status": "success",
  "requested_url": "https://www.amazon.com/dp/B012345678",
  "final_url": "https://www.amazon.com/dp/B012345678",
  "requested_asin": "B012345678",
  "actual_asin": "B012345678",
  "variant": {"label": "Color", "value": "Black", "confirmed": true},
  "title": "...",
  "brand": "...",
  "brand_byline_raw": "Visit the … Store",
  "brand_placeholder": false,
  "manufacturer": "...",
  "category": "...",
  "bullets": ["..."],
  "specifications": {"Material": "..."},
  "structure": ["..."],
  "visible_ip_claims": ["..."],
  "ocr_text": ["..."],
  "visual_features": ["..."],
  "main_image": {
    "path": "/absolute/run/images/main.jpg",
    "source_url": "https://m.media-amazon.com/images/I/...",
    "width": 1600,
    "height": 1600,
    "format": "JPEG",
    "sha256": "..."
  },
  "screenshots": {
    "product_core": "/absolute/run/screenshots/product-core.png",
    "product_details": "/absolute/run/screenshots/product-details.png"
  },
  "collected_at": "2026-01-01T00:00:00Z"
}
```

For a robot check, use `status: robot_check`, include the CDP provenance fields, `requested_url`, `final_url`, and a screenshot path. Do not guess product fields. The ingestion script requires a final URL on the requested Amazon host containing the actual ASIN, title/category, an Amazon media HTTPS main-image URL, a recent timezone-aware collection time, file containment, hashes, image magic bytes/dimensions, current-variant confirmation, and two screenshots. It calculates screenshot hashes itself.

For `screening_revision=recall-integrity-v1`, capture facts are stored in `product.raw_capture`; missing capture analysis fields must not erase the Agent's confirmed `structure`, assets or query terms. Confirm analysis separately using `product.analysis` and the current product identity digest. A changed ASIN, variant, material listing content or media identity makes prior analysis stale; capture timestamps alone do not.

`brand_byline_raw` preserves the visible original byline; `brand` removes the anchored `Brand:` or `Visit the … Store` wrapper. `brand_placeholder` identifies a byline-sourced Generic/Unbranded placeholder. New completion-policy tasks do not generate trademark searches from that placeholder alone; an independently confirmed same-name mark in the image/mark inventory remains eligible. Legacy captures without these fields do not inherit a previous capture's placeholder flag. A changed byline-source fact reopens analysis and the affected trademark identity, while unchanged structural scopes retain their prior identity.

Strict recaptures retain uniquely named screenshots/media/capture files and append separate original product evidence and source runs. Re-ingesting the identical capture is idempotent. Prior image hashes and raw captures remain valid; `task.images` and the browser-product checkpoint identify the current capture. Ratings, ranks and unrelated video controls are not product variant identity.

Never place an endpoint, WebSocket URL, debugging port, profile path, cookies, local storage, or passwords in the capture. `cdp_session_id` is a random, non-secret correlation value and cannot encode the endpoint or profile.

## 2.4 自动执行边界

`2.4-free` 使用 `automation-first-v1`。用户仅处理登录、验证码、扫码、MFA 或访问同意；采集、变体识别、切换产品图、截图和比较均由 Agent 完成。一般拒绝访问标为 `access_limited`，不得要求用户代做业务查询。

`capture-amazon` 除主图外，会逐个查看当前可见图片缩略图（单次上限 12 个，无最低图片数量要求）。图片按当前 ASIN、来源 URL、文件 SHA-256 和真实尺寸绑定并去重。`product_images` 保存额外视角，`image_coverage` 保存可见缩略图数、尝试数、取得数、截断状态和失败原因。已取得相册图片不能证明背面、内部结构或包装齐全；材料完整性继续标 `unknown`，由产品证据审阅说明缺口。

专利和商标浏览器计划统一执行：

```sh
# 以下 wave 命令仅用于无 api-first-v1 标记历史任务；新任务见 API 优先契约的 --phase verification/fallback。
python3 scripts/run_browser_plan.py --task-dir /absolute/run --wave 1
python3 scripts/run_browser_plan.py --task-dir /absolute/run --wave 2
```

调度器串行调用已有美国自动适配器，自动附加 `--acceptance-probe`，无需用户逐条批准。美国专利文字召回/已知案号、文字商标文字召回、修订后的图形商标 DC/DE 召回和 TSDR 已知案号具备可尝试 executor；所有路线的真实线上验收仍以任务内执行回执为准，静态清单不等于验收。精确补查可用 `--query-ids ID ID` 批次入口；一批协调一次，逐条独立回执与恢复，同源仍串行。

命令 `node tools/cdp/cdp-cli.mjs automation-capability --provider uspto_patent_browser --jurisdiction US --right-type patent --operation patent_recall` 只读返回能力。完整实现状态见 `browser-acceptance-v24.json`。EPO GUI、WIPO 全球库和 EUIPO 网页路线禁止自动查询；J-PlatPat 和国家通用网页适配器未验收，均保留缺口。旧 `capture-registry-search` 的人工查询声明仅适用于历史 2.3，不可完成 2.4 任务。

`browser-execution-status.json` 保存每条计划的状态、执行回执、采集文件哈希及覆盖缺口。成功/零结果断点恢复须通过原查询、截图、回执、采集文件和 source_run 校验。只有登录/CAPTCHA/扫码/MFA/访问同意产生 `needs_user_action`；完成访问验证后 Agent 重跑相同 wave，继续自动提交查询和取证。

检索 `result_coverage` 区分网页明确报告的总数、实际取得数和截断状态；仅抓到当前页不声明完整召回。US recorder 将其放入 `source_run.metadata.search_coverage` 和证据 `capture_provenance.result_coverage`。外观候选的 `media_coverage` 不会把首幅图当作全部官方附图。

PPS 结果与查询绑定必须等待真实结果就绪，再按同一 L 号、完整查询和计数校验历史记录；短暂 Loading 或历史面板未就绪可在同一有界等待内重试绑定，不重提交，也不放宽匹配。虚拟表滚动与可见同族展开分别留证；首批 500 行或折叠的同族不等于全部结果。部分成功保留已读字段和真实文献，但调度标为 incomplete；只允许一次自动续跑，仍截断时保留 partial_deferred 及缺口，不当作完整成功缓存。单案逐页读取在操作前写 pending journal，结束写 final 或 error；中断遗留 pending 不是已完成取证。

PPS 必须先读取初始可见行，再点击实际的 `+N` 同族按钮，恢复滚动锚点并等待虚拟行稳定，不能点击整格或把未取得数全部归因于同族。发现 `Too Many Requests` 时记录 `BROWSER_RATE_LIMITED`，保留页面并暂停该来源；本地 15 分钟退避不是网站承诺的恢复时间。不得关闭限制弹窗、换会话或反复提交以追求验收通过，其他免费来源可继续。

错误、警告、可见弹窗和遮罩独立采集，不依赖可能截断的整页正文。在提交、同族展开、点击失败及封存结果时检查；`Query Error`、连续操作符或缺少操作数归类 `USPTO_QUERY_REJECTED`，不等待通用语义超时。限流始终使用大写 `BROWSER_RATE_LIMITED`，优先于通用点击超时。900 秒冷却、一次部分结果恢复、8 页上限统一取现有运行配置；冷却不消耗尝试，恢复前只读检查原页面，仍受限则不提交。

限流恢复时原会话或页面缺失、不可读，记录 `BROWSER_RATE_LIMIT_RECOVERY_UNVERIFIED` 并保留暂停，不启动新会话推定恢复；一次恢复已耗尽时保留 `BROWSER_RATE_LIMIT_RECOVERY_EXHAUSTED`，等待外部来源状态变化。正常首次查询仍按原浏览器启动流程执行。

新身份发现任务的美国文字商标计划逐行绑定 `query_compiler_revision=tm-field-tags-v1`。使用实际 `Field tag and Search builder` 控件及 `CM:"短词组"`；基础 Wordmark 多词输入并不等于精确短语。旧查询行不改写语义，升级时追加新 ID 并记录旧行被替代原因。依据：[USPTO 联邦商标检索指南](https://www.uspto.gov/trademarks/search/federal-trademark-searching)。

TM 结果需同时验证输入、实际搜索模式、结果标题中的完整查询、真实计数和非加载状态。支持卡片列表与查询仅命中一件时自动进入的详情页；详情页还须绑定单件标题、序号与 URL 案号。按号码直接打开详情不算产品关键词召回。零结果与残留卡片矛盾、结果仍加载、解析或查询绑定失败均不得入库为零结果或网站访问受限；Python 录入层独立复核计数和查询。只读取当前页时保留截断标志，商品/服务省略文本须保留 `goods_services_truncated`，不得称完整商品范围已核对。

没有数字查询标题的明确零结果页面，仅在本次成功提交、查询及模式一致、结果页面转换有证据、明确零结果且无卡片/加载、连续稳定采样时可绑定。`query_binding` 保存绑定方式及转换证据；没有可见查询标题时不填写虚构 `result_query`。JS 与 Python 同时验收，旧零结果页面只改输入框不得成为本次成功记录。

`tm-figurative-fields-v1` 编译实际盘点来源的 `design_code` 为 DC、`mark_description` 为 DE；Python/JS 同时校验派生来源、字段与语法。最多八页的本轮读取逐页绑定查询、计数、范围及截图；中途失败保留已取得页面与截断，不丢失前页、不假装完整。图样比较与分类召回分开；没有适用图形代码的可读特殊字体依实际盘点与官方指引判定该轴不适用，不能编造代码。详见 [trademark-copyright.md](trademark-copyright.md)。

TSDR 已知案号核验需按实际 key/value 读取 `US Serial Number`、当前状态，并展开 `Goods and Services` 与 `Current Owner(s) Information`。栏目标题或顶部结果提示不是持有人、商品或状态。严格任务的 capture、截图和标识媒体使用独立 query/UUID 名称；重跑不覆盖旧取证。录入沿用原计划的 `mode=agent`、`strategy=record_number` 等完整输入，不硬编码人工模式；解析失败保留具体错误及原始阶段记录，不伪装成网站拒绝访问。

严格任务的 US design 使用 `design_recall`，patent 使用 `patent_recall`。内部路由冲突在提交前记录 `failed`，不是 USPTO 访问受限。查询编译和录入校验必须保持一致；布尔组、短语和号码直查分别处理，不能为规避保留字而给完整商品文案加引号。主体字段及分类以 [USPTO searchable indexes](https://www.uspto.gov/patents/search/patent-public-search/searchable-indexes) 为准；字段筛选本身不证明当前权属。真实非零结果、图纸读取及分页验收仍须单独留证，参见 [recall-acceptance.md](recall-acceptance.md)。

新完成策略任务中新生成的文本 Boolean 行使用 `ppubs-boolean-v2`，号码读取继续 `ppubs-quoted-record-v1`；已执行行及历史无标记任务维持原修订。普通短词组可补 AND，已有引号、括号和 AND/OR/NOT 保持语义；尚不支持的裸露 WITH/SAME/ADJ/NEAR 等保留操作符提交前拒绝并转 `plan_repair`，不静默删除。Agent 根据产品结构追加修正查询、说明改写理由，原失败记录保留。三端编译以同一离线样例核对。

修正时替换当前 `query_terms` 中有问题的表达，在 `clue_dispositions` 记录理由并绑定新的术语摘要，再追加有效计划行。不要继续把已知非法的当前词条送入每轮规划；已经执行的旧计划行及失败回执仍原样保留。
