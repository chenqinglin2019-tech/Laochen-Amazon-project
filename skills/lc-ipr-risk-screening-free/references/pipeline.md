# 一键流水线（best-estimate-risk-v2 新任务）

`scripts/run_pipeline.py` 按固定顺序调用本 Skill 已有的命令行工具，只在三个检查点停下来等 Agent。它不自己写任何账本：每一步仍由原记录器校验，失败或无效的宿主判断不会被当成排除。macOS 与 Windows 相同（全部以参数列表调用 `python -X utf8 …` 或 `node tools/cdp/cdp-cli.mjs …`，不经过 shell）。

```bash
# 新任务（链接入口）
python -X utf8 scripts/run_pipeline.py --task-dir /absolute/new-run --url 'https://www.amazon.com/dp/B012345678' \
  --jurisdictions US --all-sources --use-serper-existing-balance --guard-session-id "$CODEX_THREAD_ID" --chief '<主审姓名>'
# 检查点处理完、或修复失败原因后继续
python -X utf8 scripts/run_pipeline.py --task-dir /absolute/new-run --resume --chief '<主审姓名>'
# 只看计划，不运行、不写文件
python -X utf8 scripts/run_pipeline.py --task-dir /absolute/new-run --dry-run
```

资料入口把 `--url` 换成 `--product-input /absolute/product-input.json`。`--task-dir` 必须是新的空目录（`create_task.py --output-dir`）。

## 来源授权与两道停止条件

| 参数 | 传给 `create_task.py` | 作用 |
|---|---|---|
| `--all-sources` | `--enable-serper-free --enable-serpapi-free --enable-signa-free` | 网页、图片、Google Patents、外观设计与商标发现 |
| `--enable-serper-free`／`--enable-serpapi-free`／`--enable-signa-free` | 同名 | 单独启用 |
| `--use-serper-existing-balance` | 同名 | 用户对 Serper 已有额度的使用授权（免费额度用尽后仍能检索） |
| `--allow-limited-sources` | — | 确需只用 EPO 时放行下面第一道停止条件 |

- 建任务后若 Serper 与 SerpApi 都未启用，流水线以 `PIPELINE_DISCOVERY_SOURCES_DISABLED` 停下：只有 EPO 时计划里没有网页、图片、Google Patents 与外观设计发现，跑下去只会得到空报告。用新目录重建任务并补上参数。
- 来源轮次结束后若没有任何一次检索真正提交（`source_runs` 为空），以 `PIPELINE_NO_SOURCE_EXECUTED` 停下，不进入比较与终审。输出给出计划行数、就绪行数和被推迟的原因。
- 每个命令以严格模式运行：记录器或宿主报错即停在该阶段并给出错误码，不再吞掉错误继续空转。

## 阶段

| 阶段 | 调用 | 说明 |
|---|---|---|
| auth | `auth_gate.py` | 鉴权逻辑原样不变 |
| create | `create_task.py` | 已有 `task.json` 时跳过 |
| credentials | `preflight.py --phase credentials` | |
| capture | `cdp-cli.mjs doctor`、`capture-amazon`、`record_browser_product.py`（资料入口：`record_user_product.py`） | |
| understanding | `product_understanding_host.py` | 产品理解宿主写出范围与分析草稿（`checkpoints/1-scope.json`、`1-analysis.json`、`1-marking.json`）；初始范围即含 `enforcement`，避免中途改版 |
| 检查点 1 | — | 见下 |
| scope | `record_product_scope.py`、`record_product_analysis.py`、`product_understanding_host.py --complete-inventory`（程序补齐商品资产清单 `checkpoints/1-inventory.json`）、`preflight.py --phase evidence`、`product_change.py --rebase-progress` | |
| plan | `generate_search_plan.py`、`mechanical_ledger.py --steps progress` | |
| sources | 每轮：`mechanical_ledger.py` → `discovery_review_host.py --stages direction,before`（先审方向与提交前） → `mechanical_ledger.py --steps progress` → `advance_work.py --execute-sources`（只提交尚无返回的查询，同一查询一批只提交一次） → `merge_candidates.py` → `triage_defaults.py`（先把新卡挂到范围） → `text_triage_host.py` 与 `visual_triage_host.py` 并行 → `provenance_host.py`（版权与商业外观来源调查） → `mechanical_ledger.py`（单页检索有界收口） → `discovery_review_host.py --stages after`（只审剩余结果） → `mechanical_ledger.py` → `auto_refine.py`（自动细化，见下） → `generate_search_plan.py --expand` | 就绪即停；最多 6 轮；进度签名（含语义审阅、进度事件、来源调查与尝试数）一轮不变即停 |
| core | 最多 3 轮：`mechanical_ledger.py` → `discovery_review_host.py --stages direction,before`（本阶段新追加的细化查询也先审） →（有就绪查询时）`advance_work.py --execute-sources`、结果审阅、合并、`triage_defaults.py` 与分流宿主 → `core_dossier.py`（先登记详情记录的逐段阅读，再写专项事件与字段限制） → `comparison_host.py` → `mechanical_ledger.py` → `generate_search_plan.py --expand` | 入选候选的原文、附图与逐要素比较 |
| marking | 页面有 PATENTED 但无号码时 | 比对单元中有逐要素无不同要素的美国专利 → 程序把检索与比对结果记入 `patent_claim_followup`（`checkpoints/1b-marking-auto.json`）；没有 → 检查点 1b |
| readiness | `review_readiness.readiness()` | 未就绪 → 检查点 2 |
| review | `report_review_host.py --preflight`，再正式运行（`--max-parallel 6`） | 输出目录 `RUN/final-review`；中断后自动 `--resume-existing` |
| adjudication | `prepare_adjudication.py --draft-selected-candidates --auto-agree` | 有分歧行 → 检查点 3 |
| publish | `publish_report.py --deliver-to RUN/report-entry --require-complete` | 目录已存在时自动用 `-2`、`-3` 后缀 |

## 三个检查点（退出码 3）

1. **产品范围**：打开 `checkpoints/1-scope.json`，只核对或修改三处：`scope.objects[0].description`（本体描述）、`scope.objects[0].visual_evidence.limitation_reason`（主图呈现限制）、`scope.reasoning`（备注），然后 `--resume`。加 `--trust-host` 可不停。

   **1b 专利标注（只在需要时）**：页面标注 PATENTED 但没有号码时，标注解析放在发现检索与逐要素比对之后。有界检索已选出、且某项独立权利要求与产品图片逐要素比对没有不同要素的美国专利时，程序直接把这一结果记入 `patent_claim_followup`（写明标注与号码的对应未经确认），不停。否则在 `checkpoints/1b-marking.json` 停下，附已比对的专利候选：① 品牌官网虚拟标记页（`record_public_source.py` 留存）；② Google Patents 检索——品牌名只能找到以公司名义申请的专利，个人持有的专利要用产品结构的通用名词（2–3 个词，不用宣传词）检索，再看近似专利的 Similar documents／Cited by；③ 解析出号码用 `record_candidate_lead.py` 登记；④ `record_product_analysis.py --revise` 记入 `patent_claim_followup`（找不到也如实记录）。确实无法解析时可用 `--skip-marking` 继续（日志留痕）。
2. **分流例外**：只有宿主留下被拒单元或仍有准备阻断项时才停，清单在 `checkpoints/2-triage.json`。r5d4 起的新任务先直接 `--resume` 一次（程序先补跑一轮），仍停下再按 `advance_work.py --output-format compact` 的动作卡处理后 `--resume`；不要直接调用 `run_api_plan.py`。程序未登记的项不会被当作排除。
3. **主审签字**：两审等级一致的行由 `--auto-agree` 预填理由；有分歧的行列在 `checkpoints/3-adjudication.json`，主审在 `adjudication.json` 对应行填写 `risk`、`assessment_status`、`adjudication_reasoning`（对照 `adjudication-worksheet.json`）后 `--resume`。

## 检索词、自动细化与默认分流（r5d 起的新任务）

- **检索词**：产品理解会话按专利文献写法给出 2–3 个通用名词的检索词，并按把握排序；程序删去 universal、reusable、premium 等宣传词。检索词只能挂在已确认的范围事实上（标题、首条要点、主图），从图片看到的结构挂在主图事实上；程序兜底词只补模型没给的那一类。检索计划对每条线索先用排在最前的词。
- **路线**：美国发明专利的关键词发现先走 EPO（标题／摘要逐词匹配），细化时转 SerpApi Google Patents；不再走 Serper 专利检索（该接口不认 `country:` 条件，会返回外国记录）。r5d20 起的新任务改走 Google Patents、按概念组检索，EPO 只作后备，见下文"外观先看主体、专利用语检索"。
- **自动细化 `auto_refine.py`**：结果审阅判定"未覆盖"的发现检索，程序按 `api_first_planning.append_followup` 契约追加一条细化查询（审阅人 `program:auto-refine`）：第一轮用同一线索的下一个未用检索词、原引擎；第二轮转 Google Patents。细化轮次（`max_refinement_rounds`，默认 2）、可用检索词或来源额度用尽时，程序记录 `stop_bounded_discovery` 有界停止，该方向作为"有界检索、剩余召回未核实"的证据限制披露，不表示没有相关权利。已追加细化的原查询由其细化查询承接。
- **第三方零售页默认不入选**：Amazon、eBay、Walmart、Lowe's、Etsy、Temu、AliExpress 等零售平台的商品页卡片（含图片卡），标题与摘要没有专利号、注册号或维权字样时，由 `triage_defaults.py` 判为不入选（其他卖家的同类商品展示，不是权利记录），写明重开条件。
- **审阅附图**：方向、提交前与结果审阅都附上商品图片，图片事实以附图形式出现，不再只给哈希值。
- **外观设计比对**：入选的外观设计专利由 `comparison_host.py` 逐幅比较授权附图与产品图片（实线／虚线保护部分、整体视觉印象），程序登记专项盘点与比较；`core_dossier.py` 为外观设计留存最多 10 幅附图。

## 核心聚焦（r5d2 起的新任务，`core_focus_revision`）

- **程序默认不入选（`triage_defaults.py`，审阅人 `program:triage-defaults`）**：① 美国发明专利按自身美国申请号的年份，申请年＋20 年＋5 年余量早于今年的，保护期已届满（`expired`）；美国外观设计授权超过 15 年的同样处理。外国优先权与临时申请不参与计算。② 只查美国时，WO／EP／外国公开文献本身在美国没有效力：同族已有美国文献时为 `family_duplicate`，否则为 `foreign_publication`。③ 网页检索返回的专利文献页面（Google Patents 等）不是维权或作品记录（`patent_page`）。④ 没有任何权利编号、登记号、案号或维权字样的公开网页卡与图片卡（`no_rights_identity`）。每条都写明重开条件，未入选不等于不侵权。
- **文本分流标准**：专利候选只有在保护的物品与产品同类或同用途，或摘要所写核心结构组合在产品上全部可见时才入选；只是某个部件相似、用途不同的判为不入选，并写出具体差异。入选另给 `priority`（`core`＝同类同用途，`related`＝其余），记在 `text-triage/priority.json`；视觉分流入选的外观设计按 `core` 记。
- **SerpApi 详情额度**：`related` 候选不能占用 `core` 候选还需要的详情请求（`candidate_api_actions._core_reserve`）。
- **授权版**：详情记录显示同一申请已授权（`worldwide_applications` 的 `this_app` 或 `events`）时，`core_dossier.py` 取回授权号的 Google Patents 公开页并登记为原始文献材料，逐要素比较改用授权权利要求，专利标注记录写授权号。
- **额度用完后的公开文本**：没有详情记录的入选专利／外观设计，`core_dossier.py` 取回 Google Patents 公开页（号码必须一致）、公开 PDF 与附图，登记为原始文献材料（支持身份与保护范围）；页面上的法律状态是网站推算，现时状态、地域效力与权利人保持未知，按记录字段缺口写入限制。比较宿主读取同一留存页的权利要求（文件哈希校验）。新任务不再派发 USPTO Patent Public Search 读取：该路线只有公开文本，其来源操作审阅要求的现时状态永远无法满足。
- **重复检索式**：细化时跳过已在同一引擎运行过的检索式。
- **专利数据库页面**：网页检索返回的 Google Patents、PatSnap、Justia、FreePatentsOnline、Lens、Espacenet、Patentscope 等专利页面按 `patent_page` 默认不入选（专利本身由专利检索路线判断）。
- **终审材料包**（`module_review.focus_diet`、`related_excerpt`）：不入选候选的卡片与检索结果条目只保留号码、标题、分流决定和原文哈希；扩展检索词只带分流决定编号；`related` 候选的公开文本只传首页、摘要与权利要求（说明书省略并注明）。完整冻结输入、摘要与校验索引不变，所有证据编号照常可引用。一次技术模块终审约容纳 15–17 个入选并完成比对的候选；超过上限时流水线以 `REPORT_REVIEW_HOST_INPUT_TOO_LARGE_AFTER_LOSSLESS_ENCODING` 停在终审阶段，并提示在检查点动作卡中按变更流程改判明显不同用途的入选候选。
- **工作视图提速**：详情记录绑定只读查找改为进程内共享读取（`common.load_json_shared`，文件一变即重读），r5d 演练中一次工作视图从 75 秒降到 30 秒，结果逐字节相同。

## 少停与终审提速（r5d3 起的新任务，`review_focus_revision`）

- **网页卡补读（`review_focus.py`）**：文本分流前，程序对只有标题／摘要的公开网页卡（无图、无权利号码）按卡片自身的公开地址取回网页（与其他留存文件相同的公开地址规则，HTML 或 PDF，最多 12 页／次），登记为该候选的留存公开来源（`page_role=card_page`），把开头部分及含产品检索词或权利／争议用语的段落（不超过 6000 字）交给分流会话。取不到的网页记入 `raw/card-pages/failures.json` 并写明原因，同一地址不再重取。网页的具体对象与产品无关时判不入选，差异写网页上的具体对象。
- **公开网页卡收口**：分流会话对公开网页卡给出的 `needs_info` 只有向用户索取第三方网页内容的动作时，程序改为不入选（与视觉宿主处理公开图片卡的规则相同），所缺事实写成重开条件。r5d2 真实运行中，3 张这样的卡曾让检查点 2 停下，由 Agent 手工打开网页处理。
- **比较宿主分批**：每次会话最多 2 个候选，会话并行，单次会话上限 360 秒（一次 6 个候选曾超时）。
- **终审单模块重跑**：某个模块（或汇总）的完整回答被校验器拒收时，只要本任务还有重跑余量、终审时限还容纳得下该会话加两份汇总，程序在同一次终审里只重跑这一处一次，不再退出等 Agent。执行失败（会话没有完成）不在此列。
- **汇总绑定**：链汇总不再要求模型照抄模块摘要哈希；程序以汇总材料包中的模块记录绑定（`FINAL_REVIEW_SUMMARY_FOREIGN_MODULES` 校验不变）。两条链的汇总都先接收再校验，一条被拒不再丢掉另一条。
- **终审材料包补充瘦身**：不入选候选的留存原文（网页、判决等）按分流决定改为存根（以分流台账的最新决定为准，候选文件投影滞后时也生效；记录在分模块时丢掉自身 payload 的，按完整冻结记录找回候选）；不入选候选的分流注释只保留决定、理由、审阅人、证据编号与具体差异，重复的卡片与产品描述改为整条注释的哈希。完整冻结输入、摘要与校验索引不变。
- **主审草稿**：两审对同一入选专利只有一方给出独立权利要求对照表时，草稿采用给出的那一份（不改等级）；否则发布会以 `SELECTED_PATENT_INDEPENDENT_CLAIM_COMPARISON_REQUIRED` 拒绝。此项对所有任务生效。

## 不中途停下与终审前筛查（r5d4 起的新任务，`pipeline_robust_revision`、`prereview_screen_revision`）

r5d4 修的是 B0FSJBDTF2 实测（约 75 分钟，没出报告）里程序能自己处理却停下或卡住的地方。

- **防睡眠（`keep_awake.py`）**：流水线运行期间请求系统不进入空闲睡眠，结束（交付、检查点或失败）即释放。Mac 用 `caffeinate -i -s -w <pid>`，Windows 用 `SetThreadExecutionState`，其他系统不处理。失败不影响运行。
- **审阅失败重跑**：`discovery_review_host.py` 的会话失败时，同一次调用内重跑一次；方向、提交前、结果三个阶段的单元平均分给最多 3 个并行会话。审阅失败的轮次不算“无进展”。
- **门槛不占轮次**：方向审阅、提交前审阅等临时门槛没过的检索，`advance_work.py` 在计算本次派发上限之前先剔除（状态里记 `source_dispatch_gated`），不再每次推迟都消耗一轮无进展额度；轮数按每次流水线调用重新计算。
- **视觉分流**：商品图超过 `vision_product_images`（6）张时，按商品图顺序（主图优先）去重后取前 6 张，略去的图写进决定的限制。准备或取图阶段已被拒的卡不再挡住检索派发，列入检查点 2 清单。美国外观卡在视觉分流前先取 Google Patents 页面和附图（并行取页、串行登记），附图取不到的按程序规则保守入选（`program:design-picture-unavailable`）。
- **外观号码与“查无此记录”**：EPO 写作 `USD1110120S` 的外观专利，SerpApi／Google 用 `USD1110120S1`；程序取详情时一律改用后者（号码 ≥ D435000；更早的号码不变）。来源对准确记录请求明确答复“查无此记录”（`PROVIDER_RECORD_NOT_FOUND`）时，`pipeline_robust.py --closeouts` 写回执处理和失败复核（`retry_constraint.kind=source_record_absent`），候选带着“记录事实未知”的限制继续。
- **公开下载与 fake-IP**：下载进程第一次遇到非公网地址时做一次 DNS 探测（与 `network-check.json` 同一规则，`candidate_media.fake_ip_mode_confirmed`），确认本机处于 fake-IP 模式时，解析到 198.18.0.0/15 的公开地址可以下载；其他内网、回环地址照旧拒绝。r9 起：同时返回的 IPv6 内网占位地址（fc00::/7）不连接、改用 198.18 的地址；本机没有 fake-IP 但设了系统代理或 `HTTPS_PROXY` 时，下载经该代理的 CONNECT 隧道（见下文 r9 一节）。
- **没有详情记录的入选候选**：核心资料以候选自己的检索卡片登记专项阅读，事实全为未知，并带 `API_RECORD_FACT_GAP` 限制，核心阶段和就绪检查不再卡住；终审按假设评级并写明缺什么。
- **GIF／TIFF 原件**：登记时转成 PNG（首帧、无损、结果确定），原件哈希、大小和格式记在 `derived_from`；已登记的旧原件在终审读取时同样转换。其他读不了的图片格式在登记时报错。终审预检先核对材料清单（`validate_inventory`），不再等模型会话跑完才发现清单不全。
- **检查点 2 之前补跑**：核心阶段结束时若仍有可派发的检索，再派发一次；仍发不出时以 `PIPELINE_READY_SOURCES_UNDISPATCHED` 停下并列出原因。就绪检查不过时，程序先自动补跑一轮核心流程，再决定是否停在检查点 2。
- **终审前筛查（`prereview_screen.py`，美国发明专利；r5d17 起的新任务另筛外观，见下一节）**：核心阶段每轮按 `--status` → `core_dossier.py` → `comparison_host.py` 与 `--claims` 并行 → `--commit` 的顺序运行。
  - S1 法律状态（程序规则）：可信详情记录与其状态事件一致显示已放弃满 2 年且从未授权，或保护期已届满，并且记录所列美国关联申请都已终止，才改判未入选（`program:prereview-status`）。
  - 主审采纳（r5d15，r5d4 起的新任务）：`prepare_adjudication --auto-agree` 自动采纳一种情况：只有一份终审列出、没有候选、未定等级的待判断单元（例如未提供自有品牌名称或 Logo 时的自有品牌行），照录为待判断并写明原因，不赋予等级。若只有一份终审列出、但给了等级，仍交主审。续跑遇到旧版本生成、仍有空行的采纳草稿时，只要草稿里每条已填理由的行都与按现行规则重建的结果完全相同（即都由程序填写），就用重建结果替换，日志记 `adjudication_draft_refreshed`；有人工填写的行时保留原文件。
  - 公开页权利要求（r5d13）：免费任务的 SerpApi 次数用完后，入选候选只能靠 Google Patents 公开页。读取时接受不补零的编号（`num="8"`）；编号区段（`num="1-7"`）和已取消的权利要求一律跳过。公开页读不出权利要求时，`core_dossier` 改走"没有准确记录"的登记路径：以检索卡片为材料，事实标为未知，并加上限制，不再让该候选处于未登记状态。
  - S1 保护期（r5d12，`prereview_term_revision`）：候选自己的保护期已届满，并且记录所列每个美国关联申请已终止或保护期已届满，也改判未入选。保护期届满不能恢复，"欠费失效"也算在内。届满日按两种方式取：记录里写明的预计或调整后到期日；没有写明时，按最早美国非临时申请日起 20 年，另加 5 年期限调整余量推算。临时申请日和外国优先权日不作为起算日。状态为 Active 或 Pending 的一律保留。附录写明届满日与依据。
  - S2 两次判断：逐要素比对（A）与一个互不知情的排除复核会话（B，必须逐字引用每项独立权利要求原文并给出产品图片编号）都认定产品在每项独立权利要求上缺少必要特征，才改判未入选（`native-screen-<会话>`）。缺配套物品、等同结构、看不到的部位、宽泛措辞一律保留。任何不一致、失败或超时都保留候选进终审。
  - 改判走“重开 → 新决定 → 重开复核”的登记路径；之后 `--rebind` 按当前分流重新绑定受影响的有界检索结论，避免重复细化。被排除的候选只列在报告附录，终审材料包里的专项事件改为存根。
- **USPTO 官方附图（r5d7）**：Google Patents 对 2025 年后授权的美国外观常常没有页面（HTTP 404），或列出附图却拒绝下载（HTTP 403，任何人都一样）。此时程序从 USPTO 官方原始文件入口 `https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/D<号码>` 取回授权 PDF（`raw/design-pictures/<号码>/uspto-grant.pdf`），用 pypdf 与 Pillow 取出每页扫描图样（灰度 PNG，长边 ≤ 1600 像素，最多 10 页，页上印有案号与图号），登记为该候选的 `patent_drawing_image`（`figure_label=USPTO-P01…`，`derived_from` 记 PDF 哈希与页码），再做视觉分流。不需要 pdftoppm，Mac／Windows 相同。两处都明确拒绝的号码记入 `raw/design-pictures/failures.json`，不再重试；网络类失败下一轮重试。
- **补跑重复到不再变化（r5d7）**：就绪检查前的补跑最多 3 轮，每轮有变化（新的细化、审阅、分流）才继续，最后一轮规划的细化会在下一轮审阅并派发。没有新派发的轮次也会重做已过期的结果审阅（分流改判后会过期）。在提交前就被撤销的细化不再视为父查询的后续，父查询改用下一表达或按有界检索收口。
- **授权 PDF 作为外观的专项材料（r5d8）**：`core_dossier` 对已留存 USPTO 授权 PDF 页面的美国外观：没有准确记录也没有公开页时，以该 PDF 为记录材料（`original_document`，支持号码身份与保护内容），状态、地域与权利人保持未知并按计划登记的 `API_RECORD_FACT_GAP` 限制；有准确记录但附图取不到时，另登一份 PDF 材料支持保护内容。比较宿主随后按 `USPTO-P01…` 逐页比较（首页只有文字时取 unknown）。旧版本已登记、缺保护内容的同一外观，续跑时在同一登记轮次补登 PDF 材料，并改登仍未知事实的限制、关闭被取代的旧限制。`record_gap_planned` 不再要求已有登记（以前对没有登记的范围永远为假）。来源答复"查无此记录"、计划动作随后被撤销的详情查询，按无重试限制收口。
- **睡眠检测（r5d8）**：每个步骤比较墙钟与进程时钟（电脑睡眠时进程时钟停止），差值超过 60 秒记为 `system_sleep`（`pipeline-log.jsonl`），累计写入 `pipeline-state.json` 的 `slept_seconds`，并在流水线输出中给出 `slept_minutes` 与 `sleep_warning`。Mac 上启动 `caffeinate` 后用 `pmset -g assertions` 核对一次：日志 `keep_awake:caffeinate` 表示系统已登记，`caffeinate_unconfirmed`／`caffeinate_exited` 表示未登记或已退出。
- **分析额度不计睡眠（r5d9）**：`host-triage-budget.json` 的 `used_seconds` 按进程时钟（`perf_counter`，电脑睡眠时停止）记账；旧版本按墙钟记账的宿主步骤，按 `runtime-timings.jsonl` 中同一步骤墙钟与进程时钟之差（≥60 秒，同名重叠步骤只计一次）退回，记在 `sleep_credit_seconds`，`awake_since` 之后开始的步骤不退。额度剩余不足 120 秒时，检查点 2 清单带 `analysis_budget`（剩余秒数、上限与说明）。
- **终审规则**：审阅提示词写明“除非任务登记了用户事先提供的许可，否则按没有任何许可评估”，不把索取许可或授权链写成下一步；材料包给出每个入选候选可绑定的证据 `candidate_counter_refs`，评级行不满足发布阶段的绑定条件时整份退回、同一次终审内重跑一次（r5d3 任务续跑到终审时同样适用）。

## 外观终审前筛查与提速（r5d17 起的新任务，`prereview_design_revision`、`pipeline_speed_revision`）

r5d17 来自 B0HF19R4YF 实测（出了报告，约 41 分钟）：8 件入选外观里，核心比对已逐视图判定 7 件"整体视觉印象明确不同"，终审仍完整双审，外观模块单个会话 12–13 分钟；其中 7 件两审一个评极低、一个评低，由主审在检查点 3 逐件裁决。

- **外观终审前筛查（`design_screen.py`，用户 2026-10-13 决定）**：核心阶段与比对会话并行运行 `--check`，在专利筛查提交之后运行 `--commit`。
  - A（程序）：该外观最新一次逐视图比对没有"相同"视图；"明确不同"至少 2 幅，且不少于已比对视图的一半。"图片看不到"的视图允许存在，比对列出的共同点不作为保留理由。
  - B（复核会话，看不到 A 的结论）：只看实线部分，判断普通购买者眼中两者整体视觉印象是否明显不同。个别共同点和个别看不到的视图不影响判断；整体形状、主要构成或比例相近，或者判断不了，选 keep。exclude 须在至少 2 个不同视图上写出附图与产品的具体差异，并给出产品图片编号。颜色、材质、尺寸、虚线、文字或标志不能作为依据，不得使用百分比或评分。
  - A、B 都判明显不同，才走"重开 → 新决定 → 重开复核"登记为未入选（`native-screen-<会话>`）。原因写明专利号和主要差异，只列在附录。任何不一致、失败或超时都保留候选进终审双审。之后与专利筛查一样运行 `--rebind`。
- **终审材料按内容去重**：同一文件内容只附一次，来源编号合并（B0HF19R4YF：外观模块由 157 份材料、143 张图降为 100 份、86 张）。
- **比对会话**：5 路并行。模型写的部件或实施方案编号只是格式不合规（过长、大写、连字符）时，程序将其规范化（在词边界截到 31 个字符以内，重名加后缀），不再整批作废。
- **去掉空转轮**：检索阶段一轮若只多了候选详情读取、API 尝试记录或进度事件，按空转处理并结束本阶段，结束前照常检查可派发的检索。核心阶段第 1 轮后已经就绪，就不再跑第 2 轮。
- **结束输出**：`status: delivered` 时同时输出 `completion_status` 和 `next`。交付事务内已完成入口检查与完成检查，Agent 直接读取报告汇报，不再运行 `publish_report.py`、`completion_check.py`，也不另建输出目录。
- **技能版本缓存（所有任务）**：`run_pipeline.py` 启动时用 `DISTRIBUTION-MANIFEST.json` 的哈希判断技能是否换了版本，换了就清掉 `scripts/__pycache__` 等编译缓存。B0HF19R4YF：r5d16 的一处修改没有改变文件大小，旧缓存被继续使用，建计划时报 `API_FIRST_RETRIEVAL_POLICY_INVALID`。

## 同一文件只有一个候选（r5d18）

r5d18 来自 B0H16FDSD8 实测：在检查点 2 停下，唯一阻断项是 `SOURCE_RESULTS_PENDING_PROCESSING`。EPO 检索卡写作 `USD1035381S`（docdb 写法），Google 检索卡写作 `USD1035381S1`，两者是同一件外观专利，却被当成两个候选：
- 各读了一次详情，多用了 1 次 SerpApi；
- 各做了一次比对和外观筛查。

核心资料步骤给每个候选取"同号码里最新的一份详情"，两个候选都取到了后读回的那份，先读回的那份始终没有登记读取。以往 7 次实测中有 3 次出现过这种成对的候选。B0FSJBDTF2 那次，同一件外观一个写法入选、另一个写法不入选。

- **合并（r5d18 起的新任务，`candidate_number_revision`）**：候选身份键按规范写法计算（`common.canonical_patent_number`：美国外观 `USD…S1`，美国申请公开 11 位）。两种写法合并为一个候选：
  - 两张卡的来源都保留；
  - 原始写法都留在 `field_claims` 里，原回执逐行核对仍能找到；
  - 编号写法不同不再记为字段冲突；
  - 显示的编号沿用先到的那张卡。

  旧任务不改，因为改了候选编号会使已有决定失效。
- **补登读取（r5d17 起的任务）**：`core_dossier.py` 每轮结束时检查成功的 SerpApi 详情记录。没有登记读取、但同一文件（规范写法相同）已有读取登记的，由程序按记录器自己的读取单元补登，读取人为 `program:core_dossier`，原因写明已读的那份记录。登记被记录器拒绝的列在 `core-dossier.json` 的 `same_document_readings.left_for_agent`；没有任何同文件读取的记录，仍留给 Agent。

## 未启用的条件情景（r5d19）

r5d19 来自 B0H16FDSD8 用 r5d18 续跑：过了检查点 2，终审其余模块都已完成，表达模块两条链三次被拒（`OUT_OF_SCOPE_NOT_BOUND_TO_TASK`），另有一次被网络切断。用户在检查点 1 说明用自己的品牌、忽略对方品牌和外包装，产品范围因此没有启用“沿用参考标识”条件情景（`execution_scenario_ids` 只有 `product_entry`），`necessary_scenario_right_types` 也不给它任何必做工作；终审仍要求它的两行，两位审阅者都写了 `out_of_scope`。校验只认 `assessment_scope_exclusions` 里的排除，没有把任务自己的这条记录当作绑定，再续跑一次会以 `FINAL_REVIEW_SLOT_RETRY_LIMIT_REACHED` 停下。

- **规则（所有情景工作流任务）**：条件情景（`conditional:true`、不是主情景）在任务里没有必做工作时（continuous-work-v2 任务未列入 `execution_scenario_ids`），它的行可以写 `out_of_scope:true`、`risk:null` 和 `scope_reasoning`，由任务记录绑定。主情景、已启用的情景和没有这条记录的任务仍只认 `assessment_scope_exclusions`；`out_of_scope` 行本身的要求（risk 为空、有理由与标题）不变，每个必需范围仍须有行。审阅者写待定或评级照旧有效。
- **主审（r5d4 起的任务）**：两审对这样的行一条写未纳入范围、一条写待定时，两边都没有等级可比，`prepare_adjudication --auto-agree` 照录草稿行，不在检查点 3 停下；有一边给了等级的仍交主审。
- **报告**：运营报告只展示主情景，这两行不论写待定还是未纳入范围，报告正文相同；该条件情景的汇总仍是未定级（与 B0GLNPC6K8 相同）。
- **续跑**：提示词和材料包没有改变，续跑时已完成的模块审阅按原样复用（终审预检显示 0 个新模块会话，只补跑两条链的汇总）。

## 外观先看主体、专利用语检索（r5d20 起的新任务，`design_assessment_revision`、`recall_revision`）

r5d20 来自用户的两份报告：两款商品用户都知道有美国外观专利，报告却都是"低风险"。
- B0H16FDSD8（滚动烧烤篮）：USD1035381S1 "Rolling grilling basket" 被检索到并入选，但核心比对 9 个视图全判"不同"（每个视图都带着单独画出的双叉工具或网格端面），终审前外观筛查两次都判"整体明显不同"，移出终审；同为圆筒网篮、只略带锥度的 USD1055634S1 两条链都评了低。
- B0GLNPC6K8（电动蝴蝶逗猫棒）：USD1152251S "Cat teaser"（2026-10-06 授权，早于任务 1 周）从未被检索到。外观只有一条检索 "butterfly cat toy"（0 条结果），发明专利只走 EPO 标题／摘要逐词匹配；卖点 2–4 里的电机驱动、旋转模式、触碰唤醒从未进入检索；检索审阅说"应改用 pet toy／teaser"，补检只会换用最初抽出的下一个词。

**外观（`design_overall.py`，用户 2026-10-14 决定）**
- **核心比对**：比对会话先写品类关系（`article_relation`）和双方主体造型（`main_body`：基本形状、主要几何、比例、主表面构成；关系取 same_form／similar_form_prominent_difference／different_form），再把端面、把手、按钮、扣件、装饰和**与主物品分开画出的附件**写成次要差异（`secondary_differences`，minor／noticeable）。视图结论按该视图的整体印象：主体一致记 corresponds，只有主体轮廓或构成不同才记 differs。
- **终审前筛查 v2**：A 直接读比对记录的主体关系；B 先写双方主体形状再判断。两次都认定**主体基本形状不同**（如扁平夹篮对圆筒篮）才移出；端面、把手、附件、表面图案不能作为移出依据，B 说 exclude 但主体关系不是 different_form 的按 keep 处理。
- **终审评级**：终审外观模块的指令写明分步规则（同品类、主体造型相同、只有次要差异 → 高；近似照抄 → 极高；同类造型但主体有明显差异 → 中；主体形状不同或不同物品 → 低，有决定性证据才极低），外观"低"的比较依据改为 `article`、`main_body_form` 和若干 `secondary:<部位>`，不再按视图逐项列。
- **主审保底**：`prepare_adjudication --auto-agree` 不让外观行低于比对记录的主体关系所对应的等级（same_form → 高；做过筛查的取两次判断中较弱的关系。r5d21 起取消 similar_form_prominent_difference → 中 的保底，用户 2026-10-15 决定：八边形开槽板篮被判为相近后两审都评低、理由充分，却被抬成中）。两审都低于下限时由程序定为下限并写明理由；一审在下限之上、两审不一致的留给主审，工作表写明下限。届满、放弃等决定性排除不受下限约束。

**检索（`recall.py`、`recall_screen.py`，用户授权）**
- **专利用语概念组**：产品理解另给 `search_concepts`：3–8 个专利常用品名（含上位名称）和 2–4 个核心功能概念（各 2–5 种写法），可取自标题或任意一条卖点（产品范围多一条事实 `F-BULLETS`，指向全部卖点）。程序据此组成：外观 D1＝具体品名组（模型标为 `broad` 的上位品类名如 cat toy、pet toy 不进 D1：2026-10-14 实查，加上它们检出 428 件、按相关度前 100 件没有一件逗猫棒；只用具体叫法检出 5 件全是同类），D2＝中心词组 AND 修饰词组（含上位名，按新到旧）；发明 U1–U3＝品名组 AND 第 k 个功能组。每组是独立的检索目的（`discovery_problem_id`：`recall-v1:…`），不再一个线索来源只发一条；模型没给出可用的概念组时，程序用标题里的商品短语兜底。专利、外观只用概念组；版权、商业外观、维权仍用原来的检索词。
- **来源**：美国专利与外观的发现检索都走 SerpApi Google Patents（每条 100 条结果、外观 `type=DESIGN`、发明 `type=PATENT`、优先权日下限：外观近 16 年、发明近 21 年；D2 按授权时间从新到旧排序，保证拥挤品类里刚授权的外观能看到）。EPO 只在 SerpApi 不可用或额度用完时补位，且只查美国文献（`pn=US`）。读单件著录与法律状态照常用 EPO。每任务 SerpApi 上限仍为 20 次。
- **补检**：结果审阅判定 `refine` 时可另给 `refine_query`（品名、功能写法），`auto_refine.py` 优先用它组成同一目的的补检；没有时才回退到下一个旧词。已取消且从未发出的补检不再计为兄弟行，不会让后续补检永久被拒（`API_DISCOVERY_FOLLOWUP_AMBIGUOUS`）。
- **结果初筛 `recall_screen.py`**：待分流的美国专利不少于 25 件、外观不少于 15 件时，先做批量初筛：专利每批最多 80 件，只看标题与摘要开头；外观每批 20 件，只看首图。每批只返回可能相关的编号，其余登记为未入选（审阅人 `native-recall-screen-<会话>`，写明只依据初筛内容）；卡片文字不足以排除的、没有图的外观，以及会话失败或超时的，一律留给原来的分流。留下的照常进入文本／视觉分流。

- **已知限制：刚授权的美国外观查不到。** 美国外观授权前不公开；Google Patents（SerpApi 用的同一数据）与 EPO 收录新授权有一到两个月延迟（2026-10-14 实查：按号查 USD1152251S1 为 0，2026-08-20 之后公开的美国外观一件也查不到）。USD1152251S 2026-10-06 授权、任务 10-13 运行，任何检索词都检不到；要覆盖需另接 USPTO 来源，尚待用户决定。

**不变的**：报告格式与锁定函数、鉴权与 API Key、发明专利的权利要求比对规则、SerpApi 每任务 20 次上限；没有新标记的旧任务行为不变。

## 缩小候选、30 分钟内出报告（r5d21 起的新任务，`candidate_precision_revision`、`time_box_revision`）

r5d21 来自用户用 r5d20 重跑的两个任务（2026-10-14，两个任务同时跑）：烧烤篮查准了（USD1035381S1 评高），但机器跑了 86 分钟、另在检查点 2 停了约 40 分钟（Codex 改了 4 个脚本才过去）；逗猫棒机器跑了 90 分钟，60 分钟模型分析额度耗尽，停在检查点 2。用户要求在获取候选环节就缩小范围、提高精准度，单个任务最长 40 分钟、最好 30 分钟内。

**所有任务（只改调度，不改任何判断）**
- **模型会话名额与限流**：同一用户在本机的全部模型会话共用 4 个名额（`model_slots.py`，锁文件在系统临时目录；两个任务同时跑也共用，各自会变慢）。会话在没有任何输出前遇到 429 / Too Many Requests 时，写入共享冷却时间，等待 30/60/120 秒后在同一步里重跑同一会话（最多 4 次），每次被限流的轨迹另存为 `*.ratelimit-N.jsonl`，清单在 `*.ratelimit.json`。额度用尽类错误（usage limit、quota）不重跑。批量宿主不再把限流失败拆半重排；终审模块把限流和网络中断一样在本轮重跑一次。终审模块按提示词长短依次取名额。
- **分析额度**：同时运行的宿主不再各扣一份，按各宿主运行区间的并集扣。
- **产品理解**：会话失败先重跑（共 3 次）；仍失败才用程序兜底词，检查点 1 的提示写明这一点。
- **程序记账提速**：一次工作视图推导里，同一补充证据清单、同一留存文件、同一事件链只校验一次（`derivation_memo.py`；推导之外每次照常全量校验）；跨步骤缓存的键不再计入流水线日志、状态文件和步骤计时，图片与 PDF 按大小、修改时间和 inode 判断。逗猫棒运行副本上一次工作视图推导从 270 秒降到 45 秒（本机计时）。

**候选精准度（`precision.py`、`recall_screen.py`，用户 2026-10-15 决定）**
- **已失效的直接排除**：检索卡片的 Google Patents 美国状态为 NOT_ACTIVE 的专利或外观，由 `triage_defaults.py` 按 `inactive_us_status` 规则登记为不入选，不进任何模型（逗猫棒那次：发明 100 件中 50 件、入选的 29 件中 16 件已失效）。
- **兜底词变窄**：没有模型概念组时只用完整商品短语（不再截出 "cat toy" 这类两词泛称，不生成"中心词 + 修饰词"组）。审阅者的外观补检词里，理解阶段标为上位品类名的（如 pet toy、grill basket）不进按相关度排序的外观检索。
- **初筛即分流**：每件待分流的美国专利和外观都先过初筛（不再有件数门槛）。外观看检索卡片首图（没有首图时先取 USPTO 授权 PDF 前两页），只列出 same（同品类、主体造型相同）和 similar（同品类、主体有明显差异）；发明看标题和摘要开头，只列出 core（同一类物品且核心结构组合可能具备）和 related（物品不同但涉及本品核心机构），"只是用途相同"不列。每个列出的给一句关系说明，作为入选理由写进报告；没列出的登记为不入选。这两类不再进入逐件文本／视觉分流，也不产生需人工补证的 needs_info。
- **深查上限**：外观最多 8 件（same 先、附图未取得但标题同名的其次、similar 最后），发明最多 6 件（core 先、related 后）；超出的登记为"超出本轮深查上限、未深查、可重开"（审阅人 `program:deep-check-cap`）。
- **取不到附图的外观**：检索卡片附图和 USPTO 授权 PDF 都取不到时，只有标题与本品的具体叫法相同（D1 品名，词尾 -s／-ing／-ed 视为相同）才深查，其余登记为"附图未取得、未深查"（审阅人 `program:unseen-design`）。原来的"无图保守入选"不再用于这类任务。
- **复核只开必要的会话**：外观复核 B 只对比对记录为 different_form 的候选开，发明复核 S2 只对比对记录已逐项找到缺失要素的候选开，两者都在比对之后运行。
- **检索审阅用低推理强度**：方向、提交前和结果审阅会话的推理强度为 low；初筛、比对和终审不变。
- **轮次**：检索阶段最多 2 轮（首轮加 1 轮补检，补检轮数上限 1），核心阶段最多 2 轮；检查点前补做 1 轮（有时间预算的任务在预算内最多 3 轮）。
- **终审材料**：各模块不再列出不入选候选的记录桩和它们的检索运行（改为一份"候选 → 证据编号"索引），也不再带其他模块的事件桩；烧烤篮那次的冻结输入上，外观模块从 61 万字降到 46 万字。
- **会话目录**：初筛、分流、比对类会话提交后删除工作目录里复制的图片（清单 `image-copies-removed.json`），失败尝试不保留图片；终审目录不动。
- **零结果**：SerpApi 零结果回执经核实为零时按检索完成处理，不再被当作"结果被截断"。

**时间预算（`time_box.py`，用户 2026-10-15 决定：到点照常出报告）**
- 计时只算机器运行时间（各阶段秒数之和，不含检查点 1 等用户的时间）。机器时间 12 分钟后不再开新的检索轮，22 分钟后不再开新的核心轮。
- 进入终审前，补做之后仍有未完成项时，程序把它们写进 `time-box.json`，工作视图把这些项显示为有据限制（状态 blocked、理由 `TIME_BOX_REACHED`，与该记录的哈希绑定），随后照常终审、发布；报告显示"已完成部分查询"并列出未完成项，不在检查点 2 停下。一次任务只收口一次，之后新出现的工作不在其列。
- 终审单个会话超时 15 分钟。
- 逗猫棒那次停下时的运行副本上验证：收口 28 项后，终审准备检查从 28 个阻断项变为通过。

**不变的**：报告格式与锁定函数、鉴权与 API Key、来源客户端、`runtime-config.json`、发明权利要求比对规则、两审加主审结构、SerpApi 每任务 20 次上限；没有新标记的旧任务只受"所有任务"一节的调度改动影响。

## 卡住的会话（r5d22，所有任务）

r5d22 来自用户用 r5d21 跑的烧烤篮（2026-10-15，经 fake-IP 代理联网）：初筛把 79 件美国候选缩到外观 6 件、发明 1 件，USD1035381S1 在内；但 29 个模型会话里有 3 个开始后一个事件都没有返回：两次检索审阅各等满 240 秒才重跑，终审第二审的外观模块等满 15 分钟被掐断（第一审同样的材料 392 秒做完），终审失败，没有出报告。

- `stall_guard.py`：会话还没有任何回答（既无推理事件也无回复）时，按已完成的同类会话判断是否卡住：
  - 批处理会话（宿主目录下以 64 位哈希命名的会话目录）：同一目录已有至少 2 个会话完成后，超过其中最慢者的 3 倍（至少 120 秒）即停止；
  - 终审模块与汇总（`<终审目录>/<1|2>/<模块>`）：另一审的同一模块完成后，超过其用时的 1.6 倍且至少多 180 秒即停止。
- 停止的会话在执行记录里写 `status: stalled`、`failure_code: REPORT_REVIEW_HOST_STALLED` 和 `stall_limit_seconds`。批处理宿主照原来的超时重跑；终审把它当作这一位置的失败回合，与网络中断一样在同一次终审内重跑一次，所需时间按另一审的用时估算。
- 已经开始回答的会话不受此规则影响，仍按原超时；没有已完成的同类会话时什么都不变。
- 续跑终审的时间估算：没有任何回答就被掐断的回合，另一审同一模块已完成时按另一审用时计算，不再按"掐断时长加余量"要求追加终审额度（烧烤篮这次续跑估算从 1160 秒降为 531 秒，剩余 888 秒够用）。
- 检查点 1：本次调用新生成的范围草稿（首次运行，或用户删除 `1-*.json` 后续跑重新生成）一定先停下给用户核对；此前续跑时重新生成的草稿会不经核对直接继续。

## 卡住的分流与回答后断线（r5d23，所有任务）

r5d23 来自用户用 r5d21 跑的逗猫棒（2026-10-15，同样经 fake-IP 代理联网）。深查阶段失败，没有出报告：
- 一张诉讼网页卡（Kitchinventions 诉 Walmart）的网页正文因网络错误没读到。文本宿主给出"需补材料"，但拿不出可执行的下一步，记录器拒收，这张卡一直是未完成的分流。
- "先分流再发新检索"的规则因此从第 2 轮起挡住了全部 7 条检索（11 个待办项）：两条首轮补检（cat teaser／cat wand 发明、butterfly toy 外观）、两条版权图片检索、三件已入选专利的详情读取。
- 同一张卡被原样送审 12 次，每次约 25 秒。
- 深查结束时检查发现仍有可派发的检索，阶段失败（`PIPELINE_READY_SOURCES_UNDISPATCHED`）。
- 另有一次检索审阅在 72 秒就交了完整回答，但回合结束事件一直没来，等满 240 秒才重跑。

改动：
- `pipeline_robust.light_triage_pending`：文本宿主上一次运行（含它自己的重试）后仍未能登记的候选，不再挡新检索的派发。它仍是未完成的分流，在检查点 2 列出，或由时间预算收口列为本轮未完成。
- `text_triage_host`：同一份送审材料两次都得到同一种记录器必拒的回答（目前只有"需补材料但没有可执行动作"）后，不再为它开会话，直接列为未登记（`repeat:`）。记录在 `text-triage/dead-ends.json`；材料一有变化（读到网页、新回执），送审材料就变了，照常送审。
- `stall_guard.answered_stalled`：回答已完整交出、之后 30 秒既无新事件也没有回合结束的会话，按卡住停止（`stall_kind: answered_turn_not_closed`）。回答不采用（未结束的回合不算审阅），由原有重试重跑。两次运行的 82 个正常会话里，回答到回合结束最多相隔 3 秒。续跑终审估算这类回合时按回答交出的时间算。
- `run_pipeline.s_core`：有时间预算的任务（time-box-v1）在深查结束时仍有未发出的检索，不再判阶段失败，而是记入 `undispatched_at_core_exit` 后进入就绪检查，由补做轮发出或由收口列为本轮未完成。其他任务照旧报错。

## 外观初筛取图与终审附图（r5d24）

r5d24 来自用户用 r5d23 新建的逗猫棒任务（2026-10-15）。检索、深查都走完了，终审一开始就失败（`FINAL_REVIEW_ORIGINAL_IMAGE_BUNDLE_TOO_LARGE`）：
- 103 件美国外观等待看图初筛。程序先为每件取回并登记了全部附图：65 件先取 Google 页面（附图被拒，403），再取 USPTO 授权 PDF 并转出最多 10 页；其余 38 件取 Google 的全部附图。合计约 960 张图、17 分钟，而初筛本身只用了 52 秒，每件只看前两张。
- 终审的整体审阅路线把这 958 张图（104 MB）全部打包，超过 64 MB 上限。设计上超限应改走分模块审阅（各模块只带本模块入选候选的原件），但附图打包放在了这个判断之外，于是整个终审报错。分模块路线在这份数据上的附图只有 1–2 MB，提示词 30–52 万字。

改动：
- `adaptive_review.prepare`（所有任务）：整体路线的附图打包超限与其他尺寸超限一样，改走分模块审阅。原件被改动等其他错误照旧报错。
- `report_review_host --preflight`（所有任务）：终审在准备阶段就失败时，输出目录里只有 `frozen-input.json`，没有任何会话。续跑时流水线带 `--resume-existing` 先做预检，预检找不到已留存会话的运行环境，报 `FINAL_REVIEW_RETAINED_RUNTIME_UNCONFIRMED`，终审永远开不了跑。现在预检与正式运行一致：这种目录按全新终审检查。
- `pipeline_robust.retain_design_pictures`（precision-v1 任务的看图初筛）：
  - 每件只取初筛要看的前两张（`precision.SCREEN_DRAWINGS`）：Google 附图取前两张，USPTO 授权 PDF 只转前两页图。
  - 授权约 16 个月内的外观（`recent_design`）直接取 USPTO 授权 PDF，不再先取 Google 页面；这些 PDF 与较早外观的 Google 页面同时下载（USPTO 6 路并行）。一条路线失败时改走另一条。
  - 依据：这次 Google 对 2025-07 以前授权的外观都给附图，之后的一律拒绝。
- `core_dossier` + `pipeline_robust.complete_uspto_pages`（precision-v1 任务）：入选深查的外观，从已留存的同一份授权 PDF 补登其余页（最多 10 页），不再发请求。Google 路线的外观在深查时照旧补齐附图。
- 按这次的数据回放：Google 页面 103 → 33，Google 附图 341 → 66，USPTO PDF 65 → 70，登记约 1040 → 约 240 次，预计取图从 17 分钟降到 7–8 分钟。初筛看到的图不变。

## 精准检索与报告一致性（r5d25）

r5d25 来自两次真实运行（2026-10-15）：逗猫棒 `B0GLNPC6K8-US-20261015-r5d23`（r5d24 续跑出报告）和烧烤篮 `B0H16FDSD8-US-20261015-r5d21`。用户的方向是：靠减少候选、提高检索精准度来提高报告可靠性和速度，不靠更多补查或扩大候选。

- **外观只用一条品名词组检索**（`recall.compose_terms(phrases=True)`，新任务标记 `design_query_revision='title-phrases-v1'`）：
  - 原来的"中心词 × 修饰词、按最新排序"检索 `(teaser OR wand OR toy) AND (cat OR interactive OR electric OR pet)` 取回拖车接头、积木、儿童车、吸尘器杆等 100 条，只入选 2 件；而只放具体品名的那条把 cat toy 这类品类名也排除了，只返回 5 条。
  - 现在只发一条按相关度排序的检索：具体品名加本品所属的品类名，加引号用 OR 连接，不含更上位的名称（`recall.name_levels`：broad 名称以具体品名的中心词结尾、且修饰词不全是 pet／kitchen 这类泛称时算品类名，否则算上位名）。已被更短词组包含的名称不再重复（"interactive cat toy" 已含 "cat toy"）。
  - 现场核对：逗猫棒 `("cat teaser" OR "teaser wand" OR "cat wand" OR "cat toy")` 共 56 条，全是猫玩具，4 件入选外观都在；烧烤篮 `("grill basket" OR "grilling basket" OR "barbecue basket" OR "roasting basket")` 约 21 条，5 件评级外观都在。外观检索从 2 次减到 1 次。
  - 发明检索的品名组用同一组词组，不再放 "pet toy" 这类上位名；审阅者要求细化时给出的上位名同样不用。
  - 三级名称写在这条检索的说明里（具体叫法／品类名／未检索的上位名），`precision.specific_names`、`precision.broad_names` 从中读取，"无图外观按标题相符才深查"仍只认具体叫法。
- **外观检索的时间边界写进报告**（同一标记）：外观模块材料包带 `design_search_boundary`（本次结果中最新的美国外观授权日）。Google Patents 收录新授权的美国外观约滞后两个月，终审在外观整体行写明此日之后授权的不在本次范围，不据此调整等级，也不另行补查。
- **评为中、高的外观也写比较依据**（design-overall-v1 任务）：原来只有评低的行必须写 `comparison.criteria`，评中、评高的外观在冻结的报告里显示成"已入选待比较"（烧烤篮的 USD1035381S1 评高却显示待比较）。现在凡评级的入选外观都给 article 和 main_body_form 两项；评高的行不得写 excludes_risk。
- **深查轮先合并、再审阅检索结果**（所有任务）：`core_round` 原来先做结果审阅、后合并候选，审阅包里返回 2 条和 4 条的细化检索都是 `result_count: 0`，审阅员写了"零命中"又要求再细化，两份终审都指出了这处矛盾。现在与检索轮顺序相同。
- **网络中断的检索再发一次**（所有任务，`pipeline_robust.retry_network_failures`，随 `--closeouts` 运行）：SerpApi 请求在传输中失败、没有任何回执时，程序登记一次重发决定，下一次派发时按原参数重发（同参数一小时内由 SerpApi 缓存应答，不重复计费，仍计入本任务次数上限）。再次失败的照旧列为未完成。这不是新增检索。
- **终审调度**（所有任务）：全机模型会话名额 4 → 6，终审的 6 个模块会话同时开始；网络中断的模块会话在失败后立即重跑，不再等整轮结束（仍是每个模块一次，截止时间不够时不重跑）。

## 报告必出（r6 起的新任务，`stability_revision=report-always-v1`）

用户 2026-10-15 的要求：不同商品都要跑完、出报告。眼线印章笔运行（B0GFNWR8FW）两审都给出了 USD959051S1 高风险，却因一行反证引用了该专利自己的 Google 页面（程序不认它属于该候选）整模块被拒、重试原样重发、没有兜底，最终没有报告。r6 起的新任务：

- **候选证据一份定义**（`candidate_evidence.py`）：候选自己的检索卡片、准确详情记录、留存的公开文本和附图都算它的证据。终审材料包按候选列出（`candidate_evidence`），模块校验与发布采用同一条规则（低：比较依据＋至少一条反驳论据引用候选证据；中及以上：至少一条支持论据引用候选证据）。
- **逐行修复**（`module_repair.py`）：模块回答按原样留存，程序推导有效判断——补齐场景哈希、模块号、标题等程序字段，去掉外国权利、未入选候选的评级行，漏写的必需范围和入选候选补待定行；仍不合规的行转为待定并写明原因（`demoted_from` 保留原审意见），不再整模块拒收。发布前用同一纯函数重算核对。
- **模块兜底**：网络中断两次、回答无法解析、时间或额度用尽、重试上限——该链该模块记为 `fallback`，各行待定，交检查点 3 主审结合另一审裁决；两审都没有的行显示风险待定。
- **程序写链汇总**、**带原因的重试**（只在回答无法解析或缺 assessments 时）、**终审截止时间**（全程 2400 秒内，每个会话最长 600 秒）、**材料瘦身**（只保留入选候选之间的身份关系、分流注释和产品关联，其余计数）。
- **流水线不再因可恢复状态停下**：记账步骤（`mechanical_ledger`、`advance_work`、`merge_candidates`、`--expand`）失败重试一次后跳过并记入 `degraded_steps`（文件完整性错误仍停止）；未预期异常转为 `PIPELINE_UNEXPECTED_*` 并给出续跑命令；时间收口后再做一次进度登记与合并收口，不再停在检查点 2；页面 PATENTED 无号码时记为"未解析"，不再停在检查点 1b；终审目录与输入不再对应时改名为 `final-review.stale-N` 重来。
- 仍会停下的：检查点 1、检查点 3；鉴权、凭据、商品页采集或检索来源缺失；重试一轮后仍无任何外部检索提交；文件完整性错误；发布校验程序本身的缺陷；任务锁被占用。
- 检索与判断：发明专利初筛不再因摘要多出部件排除（只排除不同物品或用途），深查名额在同一层级内按检索结果的相关度排名分配；维权网页检索改用 "Schedule A"、TRO 等用语（条数不变）；发明专利定级与极高规则见 [评级规则](risk-estimate-rules.md) 的 r6 一节。

## 专利检索一定执行（r7 起的新任务，`search_guard_revision=search-guard-v1`）

用户 2026-10-16 的三次运行都出了报告，但烧烤篮（B0H16FDSD8）已知的外观专利 USD1035381S1 没有出现：SerpApi 账户每月 250 次，本期 10-21 恢复，眼线笔运行用完最后几次后，逗猫棒与烧烤篮的 4 条美国发明与外观检索一条都没发出，EPO 也从未改用，报告标题仍写“低风险”。同一外观检索式复核共 21 条，USD1035381S1 排第 4。眼线笔的外观检索则被 cosmetic applicator 等领域总称挤满：230 条只读前 100 条，9 件眼线类外观（含 “Dual-ended eyeliner stamp device”、两件 “Eyeliner stamp”）从未进入候选。r7 起的新任务（`search_guard.py`）：

- **余额检查**：`run_pipeline` 在 credentials 阶段与生成检索计划前调用 `search_guard.py --check-capacity`：读 SerpApi 账户接口（不计次）与本机共享额度账本（`free_search_budget.peek`，只读），取较小值写入 `serpapi-capacity.json`（不含 Key）。可用次数 ≥ 本任务美国发现检索条数 → SerpApi；不够且 EPO 可执行 → 这几条检索改用 EPO（`provider_routing` 的 `api-first-v3-recall-guard` 给美国外观也加 EPO 兜底；`(pn=US) and (ta="…" or …)`，每条最多 25 条）；都不行 → `PIPELINE_PATENT_SEARCH_UNAVAILABLE`。检查点、失败与交付输出带 `search_notice`。
- **检索后兜底**：`s_sources` 结束时美国发明、外观发现检索一条都没成功 → `PIPELINE_PATENT_SEARCH_NOT_EXECUTED`，不进入比较与终审。
- **额度挡下的请求**：冻结客户端在发请求前报出的额度信息（本机账本用完、账户余额为 0 等）记为 `FREE_QUOTA_EXHAUSTED`／`not_submitted`，不再记成提交状态未知；本轮随即停用 SerpApi，计划登记额度缺口。
- **外观检索词**：`recall.design_name_levels(guard=True)`——宽泛名必须含有至少半数具体叫法共有的词，否则只用于发明检索（任务词条原因里列为“外观不检索、只用于发明检索的宽泛名”）。烧烤篮、逗猫棒的检索式不变。
- **图片、网页、维权检索**：理解环节另给一个品名词条（`search-guard-v1:product-names`，值为具体叫法的 OR 组），copyright、trade_dress、unregistered_design、enforcement 只用它，每类权利一条；其他权利不用它。重算查询式的各处统一用 `api_first_planning.task_params`，与首轮一致。
- **深查详情**：SerpApi 详情每个任务最多 8 次（不超过余额减去发现检索），外观同款主体层、发明核心层先拿（`search_guard.detail_issue`）；拿不到的登记 `API_RECORD_FACT_GAP`。没有详情的已授权公开申请，由公开页事件表找出同一申请的授权号（`core_focus.page_granted_publication`），授权文本照旧以 `granted_publication` 留存比较。
- **终审**（所有 `report-always-v1` 任务）：提示词加入 r6 版证据绑定规则（比较依据格式、外观 article／main_body_form 两项及中高行的条款）；新标记任务的行派生记为 `module-row-repair-v2`，文字写成的比较依据保留为 `result: unknown` 的条目，发布核对按记录的版本重算。

## r8：EPO 外观路线、品名检索不被撤销、备用 key（`search_guard_revision=search-guard-v2`）

用户 2026-10-16 用 r7 跑的逗猫棒（B0GLNPC6K8-US-r7）和烧烤篮（B0H16FDSD8-US-r7）都停在发布环节：`PUBLICATION_PREFLIGHT_FAILED: EVIDENCE_UNRESOLVED_SCOPE_WITHOUT_LIMITATION`。原因有两个，都是 r7 引入的：

- r7 在余额不足时把美国外观检索交给 EPO，但任务的路线表（`coverage_v3.build_requirements`）只给美国发明列了 EPO。冻结的 EPO 客户端拒绝了外观这一行，运行器记录这次拒绝时又抛出同一错误，整条 EPO 通道中止，排在后面的发明检索也没有发出。两轮无进展后，这几条检索被撤销（`PROGRESS_DIAGNOSIS_OR_REPAIR_REQUIRED`）。
- 品名词条（`search-guard-v1:product-names`）不在程序组合目的的豁免里，图片、网页、维权检索在计划时就被撤销（`DISCOVERY_NEW_PURPOSE_PARENT_REQUIRED`）。

r8 的处理：

- 新任务（`search-guard-v2`）的美国外观路线表多一条 EPO search（fallback）；v1 任务的路线表不变（路线表在创建时固定，规范校验按任务标记重算）。
- `discovery_budget.dispatch_block`：品名词条与 recall 组合词条一样，不需要父目的（v1、v2 都生效）。
- `runtime_v24`：守卫任务记录检索缺口时如被证据记录器拒绝，只返回这一行的未提交结果，不中止整条通道。
- `necessary_completion._cancelled_discovery_limits`（report-always 任务）：某范围的缺口全部是检索义务、且每条检索都在发出前被撤销时，该范围作为限制 `DISCOVERY_CANCELLED_BEFORE_SUBMISSION` 披露，报告照出；有任何其他缺口时仍按原规则拒绝发布。
- 备用 key：`.env` 的 `SERPAPI_API_KEY_BACKUP`。`search_guard.check_capacity` 先读主账户；主账户不够本任务（美国检索 + 详情上限 8）且配置了备用 key 时再读备用账户，按 `choose_slot` 选一个，记入 `serpapi-capacity.json` 的 `key_slot` 与 `accounts`（不含 key）。流水线进程设 `LC_IPR_SERPAPI_KEY_SLOT`，`.env` 解析（`common._local_env_values`）按它把备用值交给 `SERPAPI_API_KEY`，所有 SerpApi 客户端随之使用同一账户；12 个凭据字段、`configure_credentials.py` 和冻结的鉴权函数都不变；续跑时按记录重新设置；任务发出过 SerpApi 请求后不再换。本机额度账本按 key 分开。
- 验证：两份 r7 运行原样续跑即出报告（烧烤篮 高／不建议上架，驱动 USD1035381S1；逗猫棒 中／暂缓上架，外观、版权、商业外观列为“未检索”）；三件商品的离线派发检查无撤销、无路线拒绝，4 条 EPO 检索同批都到达客户端。

## r9（2026-10-16，新任务 `portable_revision` 为 `portable-v1`；用户要求“流程已跑通，不大修大改”）

只修说法错误、Windows／Mac 上会出错的地方和网络适配，流程、检索、评级、报告格式不变。

- **外观检索覆盖说明**（新任务）：`module_review.design_search_coverage` 按每条外观检索实际读取的条数写 `design_search_boundary`。读到单次请求上限（SerpApi 100 条、EPO 25 条）时写“排在其后的结果没有读取”，读完时只写 Google 约两个月的收录滞后。审阅提示不再要求写“某日之后授权的外观不在本次检索范围”。来自 B0FHQ475MY：外观检索命中 529 条只读前 100 条，报告却写成“2024-12-03 之后不在检索范围”。
- **提速常数**（所有提速任务）：初筛取图线程 4→6（`pipeline_robust.GOOGLE_WORKERS`），看图初筛 3→5 路（`recall_screen.IMAGE_PARALLEL`），比对 5→6 路（`comparison_host.SPEED_PARALLEL`）。全机 6 个模型名额不变。
- **Windows**（所有任务；Mac／Linux 行为不变）：
  - 本机额度账本用可写句柄刷盘（`free_search_budget`）。此前 Windows 上每次 SerpApi／Serper／Signa 预留都失败，检索一条也发不出去。
  - 交付检查的文件名统一用 `/`（`delivery_inspection_stage_d`、`delivery_validation`）。此前 Windows 上留存的网页原件被当作报告页检查链接，导致发布失败。
  - `common.atomic_write_*` 在 Windows 上遇到文件被占用时短暂重试。
  - `advance_work`、`record_product_analysis` 的子进程用 UTF-8 模式。
  - 结束保护钩子命令在 Windows 上加 `-X utf8`，只影响新安装。
  - `run_pipeline` 建任务时，会话 ID 为空则取环境变量 `CODEX_THREAD_ID`（PowerShell 的 `"$CODEX_THREAD_ID"` 是空串）。
- **Mac**：npm 安装的 Codex 只在 PATH 上放了 JS 启动脚本，现在会到 `@openai/codex` 包里找原生程序（`native_runtime_discovery`）。续跑命令打印实际解释器和绝对路径。新任务开跑前检查 Pillow、pypdf，缺了就停下说明。`setup_skill --check` 不再把 Poppler `pdftoppm` 当必需，并对 Microsoft Store 版 Python 和 Python 3.9 给出提示。
- **网络**（所有任务）：
  - `candidate_media.PublicConnection` 在本机没有 fake-IP、但设了系统代理或 `HTTPS_PROXY` 时，经代理的 CONNECT 隧道连接（用户 2026-10-16 决定）。仍先做公网地址检查，TLS 校验真实主机名；SOCKS、PAC 不读取。
  - 每个已通过检查的地址按 IPv4 优先依次尝试。
  - 新任务建任务前做一次可达性检查（DNS + 与两台 Google 专利主机的 TLS 握手，不发请求、不读凭据）；两台都连不上时以 `PIPELINE_GOOGLE_UNREACHABLE` 停下，说明怎么开代理。
  - 鉴权失败且设置了 `CODEX_SANDBOX_NETWORK_DISABLED` 时，输出带 `network_notice` 说明要允许联网；鉴权原有的两行原因不变。
  - fake-IP 和系统代理只给一行“已自动兼容”的 `network_notice`。
- **审阅模型**：第一次模型会话（产品理解）或终审报告模型不可用时，输出 `model_notice`，说明 `references/review-host.json` 里的模型这个账号用不了。不改模型。
- **欧洲／日本第一步**（新任务）：
  - 流水线不传 `--jurisdictions` 时按链接站点取国家（德国站 → EU+DE，日本站 → JP，美国站仍是 US；用户资料入口仍默认 US）。传入的国家不含站点国家时给 `market_notice`。
  - 程序只生成英文检索词，冻结的语言门要求德、法、意、西、日用当地语言。这些国家本国的范围不检索、无结论：
    - 检查点 1 的 `scope_notice` 按任务的召回要求预先列出（商标随销售情景而定，不预列）；生成计划后按计划里的 `API_DISCOVERY_TERMS_MISSING` 缺口更新。
    - 时间收口关闭这些范围级工作时，限制原因仍是 `TIME_BOX_REACHED`，另带 `limitation_detail: LOCAL_LANGUAGE_TERMS_NOT_GENERATED`，说明文字写明“未生成当地语言检索词”。候选级工作仍用原来的时间收口说明。
    - 计划里一条可执行的检索都没有（只查日本的任务就是这样）时，规划后立即以 `PIPELINE_NOTHING_SEARCHABLE` 停下，不耗检索额度。
    - 离线演练（颈枕任务改为 EU+DE、JP 重新规划）：德国本国六类权利、日本全部六类权利都没有检索词。德国任务仍规划欧盟层的 EP 专利、欧盟外观和图片／网页检索。
  - 欧、英、日外观的优先权日过滤按 25 年（美国仍按 16 年）。日本已授权专利号按授权号格式发给 JPO。SerpApi 余额提示按任务国家措辞。
- 流水线输出里的 `search_notice`、`scope_notice`、`market_notice`、`network_notice`、`model_notice` 都原样转告用户。

## 状态与恢复

- `RUN/pipeline-state.json`：每阶段的 `status`（running／completed／checkpoint／failed）、开始与结束时间、`input_sha256`（阶段开始时 task／evidence／plan／candidates／annotations 的组合哈希）、输出与秒数；`rounds` 记录每轮来源处理前后的进度签名。
- `RUN/pipeline-log.jsonl`：每条命令的脚本名、参数、退出码、耗时和输出末尾。
- 已完成的阶段在 `--resume` 时跳过；`--redo <阶段>` 强制重做。阶段失败（退出码 1）时输出 `error_code`、错误末尾和准确的恢复命令；按错误码修复后 `--resume`，不要现场修改 `scripts/`。
- 同一运行目录已有流水线状态时，不带 `--resume` 会被拒绝，避免重复建任务。

## 程序默认（v2 新任务）

- `triage_defaults.py`：同一商品的零售／图片卡（参考品牌＋商品名主干、相同标题或相同 ASIN）与无身份网页卡（无专利号、注册号、案号，未提到品牌或商品名，正文 ≥40 字）登记为不入选，`reviewer=program:triage-defaults`；含维权字样或编号的卡留给宿主。Agent 可按原流程改判。
- 视觉宿主：公开第三方卡片上只能问用户的 `needs_info` 改为不入选，所缺事实保留为重开条件（用户无法补充第三方卡片信息）。
- 加法范围变更（只新增方向／权利类型）：不重开既有查询，受影响候选自动写 `usable` 适用性复核（`program:additive_scope_change`）；`product_change.py --rebase-progress` 把旧版本进度项按当前版本重登或退役。
- 终审前就绪检查纳入发布门槛：适用性复核缺失（`PRODUCT_CHANGE_APPLICABILITY_REVIEW_REQUIRED`）或仍待用户回答的反馈（`PRODUCT_FEEDBACK_ANSWER_PENDING`）在终审前阻断，不再在发布时才失败。

## 仍由 Agent 手工完成

- 品牌官网虚拟专利标记页的读取与留存（需要真实浏览器）。
- 检查点 1–3 中列出的字段与例外。
- 用户明确提出的范围或品牌变化（走 `record_product_scope.py`）。

## 旧版任务

`task.json` 的 `best_estimate_revision` 不是 `best-estimate-risk-v2` 的任务是旧版技能创建的，新版流程对它都不生效（策略在创建时冻结）。流水线遇到它会以 `LEGACY_TASK_POLICY` 退出并给出新建任务的命令；`advance_work.py` 输出首项 `legacy_task`，终审预检列出同名警告。应先告诉用户，用一键流水线在新目录新建任务（新任务另有完整的 API 额度）。只有用户明确要求续跑旧任务时才加 `--allow-legacy`。
