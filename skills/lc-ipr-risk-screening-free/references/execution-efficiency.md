# 新任务执行效率策略

新任务冻结 `execution_efficiency_revision=execution-efficiency-v2`；既有 v1 保持原执行语义，缺少效率标记的历史任务亦不升级。已有任务、签名和报告不补字段、不迁移。报告格式锁、样式、评级、来源授权及鉴权/凭据流程保持原合同。

## 画像与检索

`record_product_scope.py` 或 `record_product_analysis.py` 的同一次输入可增加顶层 `investigation_profile` 数组。每条对应一个 `scenario_id + object_id + right_type`，必须包含：

- `intensity`：`baseline` 或 `focused`。
- `reason`、`fact_ids`、`evidence_refs`：画像中的实际对象、事实与来源；不存在的引用拒绝。
- `questions`、`escalation_conditions`、`limitations`：本方向的问题、深入条件与资料限制，均为文字数组。

普通印花毛巾的技术方向可以轻查，图案和外观重点查；特殊纤维、织造、处理方法或专利声明需要单独技术问题。无内部结构资料继续保留未知，不要求用户反复提供，不凭“看不到内部结构”排除技术专利。

`resolve_discovery_work_policy()` 是画像、初始与扩展计划排序、缺词修复卡和工作视图的共同解释入口。轻查优先使用已有商品/类别线索，其他线索保留；未填写的方向采取保守重点策略，九类范围仍由原法律适用和对象范围合同决定。已取得候选不自动等于阳性；入选后的专项调查不受原轻查强度限制。

新录入画像同时绑定对象与所引事实的语义摘要。事实更正、撤回或对象变化只让受影响画像出现稳定修订缺口；原记录保留，其他方向继续。旧记录不补签名、不迁移。缺词修复卡及 compact 动作卡包含真实问题、资料缺口与取证阶段，不能只反复调用计划生成器。画像提示不改变原工作状态和完成条件。

v2 按现有对象情景规则解析画像（保留正品转售例外）；工作卡有对象绑定时使用准确对象，没有绑定时保守汇总本情景对象。共享查询采用全部有效范围中的最高强度。同情景新增未画像对象仍重点查，参考品牌变化不影响本体技术画像。

计划保留国家/方向的轮转公平性，只在同一轮安排重点优先。一个必要问题优先用一个已授权且有相应字段的来源；相同问题的同义词可在原查询编译器支持范围内用 OR，独立问题不得用过窄 AND 混合。首轮先取标题、摘要、代表图；只有入选或有具体缺口才取完整内容、状态及地域信息。原 `stop_bounded_discovery` 有据停止规则仍有效，最大页数/调整次数不是必跑数量。

执行端沿用已有 discovery 搜索与 candidate_detail/具体补证操作：不向不支持字段裁剪的提供方编造 fields 参数，也不删除已返回正文；已有有效字段优先复用，确需细节时才按当前入选或 needs_info 依据追加最小操作。调查强度不是来源调用授权。

缺事实的工作卡显示稳定 `gap_id` 与准确问题。材料未变时，不重复生成画像、关键词或扩展计划；先完成现有工作卡的实际阅读/登记。未知、失败、截断和零结果的覆盖含义保持不变。

## 图片采集与批量分流

对当前视觉候选运行：

```text
python scripts/visual_triage_host.py --task-dir DIR
```

该宿主取得全部当前待分流视觉候选，先调用候选媒体采集，再分批原生模型比较，直接调用原 `decisions[]` 登记合同。成功批次不需要主 Agent 重写；失败仅保留具体错误和待办，不登记排除结论。技术专利保留文本/权利要求路线。

如只需采图：`candidate_media.py --task-dir DIR --candidate-id ID`，可重复指定 ID。不能通过该入口传入任意 URL。

- 每候选先一张代表图，并发最多 4、每 URL 15 秒、8 MiB；失败不自动重试，最多试原卡片中的一个备用地址。
- 图片 URL 必须来自逐字节校验后的真实保留回执；HTTPS、公网地址、重定向、大小和解码均校验。连接绑定已验证的 IP，公共媒体请求不带 API Key、Cookie、授权头或代理凭据。
- 同 URL、同回执内容的有效图片复用，文件按内容哈希去重；各候选各保留来源关联。缩略图和代表图均不能冒充完整权利视图。下载不新增查询数或独立来源数。
- 默认每批 6 个候选、最多 2 张相关商品图、最多 2 个批次并行、180 秒单批上限（冻结了 `host_triage_revision` 的新任务默认每批 10 个候选、最多 3 个批次并行，见文末“批量判断宿主与机械账目”）；总过程使用原 sources 执行预算并保留最终复核额度。必要商品视图超过预算时拆批；单对象仍无法容纳则保留明确缺口，不删必要视图凑批。
- 模型必须说明实读图片、可比较程度、具体相同点/差异/限制，并给出 selected/not_selected/needs_info 及调查问题或最小材料需求。编号、来源、哈希、时间和台账由程序处理。
- 图片不全、遮挡、分辨率不足不得排除；不使用数值相似度阈值。输出漏项、错范围、引用未附图、原件变化、无比较依据或不满足既有补证合同，整批拒绝登记。
- 失败日志保留，下一次只处理仍待办的候选。补充或变化视图仍需按原图片/产品变更入口绑定受影响对象，不能覆盖旧原件。
- 商品图片按对象的 `visual_evidence.image_ids` 选择。显式引用失效不回退到无关图片；单候选准备失败保留原待办和具体执行回执，其他独立候选继续。最多两个槽位逐批准备和执行，成功后才复用槽位。执行回执的 needs_info 不冒充模型判断或候选台账登记。

v2 采集将单 URL 超时和共享任务预算分开：请求前预算耗尽不登记尝试、不缓存 URL 失败、不启动备用地址；请求可能已发出后的中断保留失败和提交状态。旧失败缺少请求状态时按未知保留，不能靠超时文案清除。最多四个请求在途，完成后再派发；成功图片按完成顺序在锁内增量保存，停止前复验来源并登记已成功材料，再明确报告预算停止。

v2 在单次采集内复用已验证回执索引，提交前逐回执重新验证；18 个候选共享一份回执时完整验证为两次。视觉待办按候选、情景、国家和权利类型分组，每组只发送一个判断单元，宿主保留所有原 work/action 关联；提交前在锁内重核本组待办、事实与图片，无关候选变化不使本批失效。

来源已确认提交但执行失败时，正式登记且原件、行位置、行哈希与证据关联均可核验的候选卡片仍可提供图片。未绑定卡片、损坏原件和查询身份不明不能借失败材料获准；提交未知仍按原恢复规则处理。取得图片不改写原来源失败状态，不增加查询完成数，也不解除覆盖或恢复义务。

来源引用已有 `source_position` 时，准备和提交前均按准确位置定位，并核对行哈希及已有集合；重复卡片可以有相同哈希，不能因此丢弃正确位置的图片。位置冲突不回退选另一行；无位置时仍要求哈希唯一。该修复不改变下载预算、失败缓存、查询数或来源数。

依赖通过现有本地虚拟环境安装：Python 3.9 对应 Pillow 11.3.0，Python 3.10+ 对应 12.3.0。`setup_skill.py` 与 `verify_skill.py` 检查实际版本及导入，不新增视觉服务 Key。

## 补证与多国身份

同一候选、情景、国家、缺失事实、实际操作/参数及当前内容，不因改 action/annotation/query ID 获得新额度。已返回材料先审阅，未知提交继续核原提交，失败恢复沿用原查询的授权与恢复入口。

v2 补证结果登记只与同动作当前最新事件做完整语义幂等比较，合法“继续→等待→继续”会追加新事件；纯时间变化不重复追加，历史事件和旧任务规则保留。

v2 的补证依据由记录器计算证据内容摘要，证据编号、重复引用、引用顺序或同哈希文件路径变化不产生新额度。有语义顺序的请求参数保持顺序；历史动作只读核验，无法核验时列出明确待办。即使增加材料，同一实际请求尚未解决的提交未知仍须先核原提交；经原恢复合同确认未提交后才允许合法恢复。

新任务的公开身份收尾输入用 `shared_query_ids_by_country`，每个目标国家绑定该国原有的五项公开调查查询。来源查询国家记为 `query_jurisdiction`，权利地域独立记为 `right_jurisdiction`，未知地域仍为 UNLOCATED。未有全部国家的独立有效调查依据时，不能整体收尾。旧单国事件与签名保持有效。

## 最终双审

新任务使用 `adaptive-double-review-v2`，阈值冻结于 `task.execution_efficiency`。四项同时满足才使用两个整合会话：完整去重原文 ≤60,000 Unicode 字符、实际唯一图片 ≤12、必要审阅单元 ≤24、完整解码 JSON ≤120,000 字符。自己的前次可复用判断也计入实际输入规模。

新任务另冻结 `review_unit_count_revision=selected-scope-units-v1`：必要单元包含原整体范围和现有分流/必要范围规则要求的候选判断，不用候选总数代替。旧任务无此标记时按原算法验证既有签名，不回填标记；候选或分流台账无法准确计量时回到原模块流程。

新任务冻结 `review_material_policy_revision=classified-public-originals-v1`，生成 `public-originals-v3`：公开原件沿用原发送边界；正式范围、反馈、产品变更及适用性记录器生成的内部回执须核文件、哈希、事件与所属任务、历史引用以及完整包或模块包中的实际内联投影，内联数据计入实际完整 JSON。缺失、不一致或未识别的回执不能按目录或自称类型获豁免；结构无法提供继续保留未知和限制。已登记但未传送的本地用户原件只核完整性，保留引用、哈希、原因和受影响范围，不能标为已读。限制通过既有审阅限制、待核事项和技术附录表达，不增加报告模块。旧包仍按原计量、提示与签名核验，不重签为新版。

超限、无法计量或原件清单不全使用原六模块加两汇总流程；不能截断材料换取整合模式。两种路径都保留实际会话、图片附件、原生日志、逐单元双审、主审、`1/review.json` 与 `2/review.json`。整合签名是一个真实 `integrated_execution`，不是伪装的三个模块签名。两链不得共享当轮结论。成功位置按原原件/输入条件续用，失败位置单独恢复。

## 发布与计量

独立校验器仍执行一次完整语义复算。它实际计算的工作视图仅保存在本次进程内，完成检查在重验冻结输入、控制状态、原件、交付字节和入口后复用。磁盘上的成功标志没有复用权限；独立 CLI、跨进程续跑、用户验收及 Stop hook 仍做完整检查。

当前进程还保存真实执行验证器已核验的审计依赖路径与原哈希，包括日志、输入、提示、判断、正式隔离策略、图片和协议规定的执行观测，以及递归引用的历史审阅依赖。每次复用前后均重新检查，初次语义校验结束也检查；发生变化后该上下文失效，恢复文件后须重新建立有效上下文。临时工作区和原 CLI 不属于成功成果的依赖。此清单不写入交付 journal，不改变历史快照、审阅签名或旧审计。

`publish_report.py --deliver-to NEW_ENTRY --require-complete` 已包含真实入口完成检查。返回 complete/limited_round_closed 后不立刻重复同一 CLI；其他状态按原义务继续工作。limited_round_closed 不表示调查完成。

性能记录仍在 `runtime-timings.jsonl`，新增工作视图、媒体和视觉批次阶段。阶段耗时包含子阶段，不能重复相加。离线调度计量不代表真实模型/网络耗时或召回率，不因超时改变报告风险或完成状态。


## 批量判断宿主与机械账目（`host_triage_revision=host-triage-v1`）

新任务由 `create_task.py` 同时冻结 `host_triage_revision` 与 `host_triage` 额度。原则只有一条：**模型只给判断，程序按现有记录器契约写账**；校验器、账本格式、范围、评级与报告均不变，也不放宽任何门禁。无此标记的任务不使用下列工具，行为与旧版一致。

| 工具 | 处理什么 | 谁写什么 |
|---|---|---|
| `mechanical_ledger.py --steps progress,dispositions,links,handoff,selected_handoff` | 09A 计划项登记、结果行→候选的位置处置、候选→对象关联、候选交接、入选交接 | 全部是可由已留存、哈希绑定事实推出的机械登记，reviewer 恒为 `program:*`，理由写明机械依据；不能唯一绑定的行/候选原样留给 Agent |
| `discovery_review_host.py [--stages direction,before,after]` | 03B 方向审阅（同情景×权利、清单相同的国家共用一次判断，拟用来源取实际计划行的提供方）、提交前语义审阅、结果审阅 | 模型给 fit/覆盖/下一步等判断；ID、哈希、清单、运行绑定由程序写入 `record_discovery_semantics` 原契约；无效单元保留待办 |
| `text_triage_host.py` | 专利/实用新型/文字商标/维权候选的文本分流 | 模型给 decision、relationship、difference/investigation_question（needs_info 另按 followup 契约）；候选卡片文字、对象文字、证据引用、范围绑定由程序写入；仅有号码/标题的卡片不得 `not_selected` |
| `visual_triage_host.py` | 外观/版权/商业外观/图形商标候选的图片分流 | 新任务用紧凑输出（`viewed_all`、`adequate`、`decision`、`relationship` 与分支字段）；每批默认 10 个候选、并行 3；卡片与图片完全相同的候选共用一次判断并保留各自证据；无效会话按一半重试一次 |
| `candidate_scope_link.py` | 候选→产品对象关联的规则实现（被 `mechanical_ledger.py` 调用，也可 `--dry-run`） | 先取候选自身查询计划的产品依赖对象；否则取全部已纳入且权利类型相容的对象；无可纳入对象的候选留给 Agent |
| `timing_attribution.py --run-dir DIR` | 只读：墙钟中程序步骤与模型书写/空闲的分布，按账本记录类型归因，并列出取数计划中的完全重复行 | 不写任务目录、不读凭据、不是门禁 |

典型顺序（每步都是幂等的，已登记的不会重复写；失败或无法绑定的项保留在统一待办里按原卡片处理）：

1. 生成检索计划后：`mechanical_ledger.py --task-dir DIR --steps progress`（登记 09A 计划项）→ `discovery_review_host.py --task-dir DIR --stages direction,before` → 执行 API／网页计划。
2. 取得来源结果后：`merge_candidates.py` → `mechanical_ledger.py --task-dir DIR --steps dispositions,links` → `text_triage_host.py`／`visual_triage_host.py` → `mechanical_ledger.py --task-dir DIR --steps handoff,selected_handoff`；结果语义审阅可用 `discovery_review_host.py --stages after`，API 发现结果审阅用 `input_template.py` 生成的 `discovery-review.json`（已预填 `triage_digest`）经 `record_discovery_review.py --input` 一次登记。
3. 入选候选的专项核验（权利要求逐要素、外观逐视图、商标逐维等）、独立双审与主审不变，仍由主 Agent 与终审宿主完成。

共同规则：

- 报告会渲染的字段（分流 `reason`、`missing_information`）必须是模型本次的具体语句，程序只补内部管理字段（`basis_summary`、`reopen_conditions`、`scope_reason` 等）。
- 不以数值相似度、百分比、评分或排名作排除依据；没有可读摘要/商品服务的卡片只能入选或 `needs_info`；失败、超时或无效输出绝不登记排除，只留下待办与执行回执。
- 宿主使用独立的 analysis 额度（`host_triage.analysis_seconds`，任务内 `host-triage-budget.json`），不占用来源 1200 s 与终审 900 s；每个会话仍受各自超时限制。预算只约束宿主入口，不是整个对话的硬上限。
- 机械步骤的 reviewer 为 `program:*`；它们只证明“这一行/候选绑定到哪里”，相关性、适用性与风险仍由分流、专项和独立双审判断。
- 宿主依赖与终审相同的原生 Codex 会话；不可用时卡片仍给出原 `input_template.py` 手写路径，行为与旧版一致。


## 真实运行校正（B07HQL3SPZ_US 实测，2026-10-11）

一次完整的真实运行（1 国、110 个候选）把下面几处“离线用例走得通、真实数据走不通”的缺陷暴露出来。均为向后兼容的修正：不改报告、鉴权、校验器与账本格式，旧任务已留存的行不被改写。

| 现象（实测） | 原因 | 修正 |
|---|---|---|
| 58 个视觉候选全部 `VISUAL_SPLIT_REQUIRED_FOR_PRODUCT_VIEWS`，只能手写 | 商品对象绑定 3 张视图，而 `vision_product_images` 默认 2，任何一批都装不下 | 新任务的宿主额度新增 `vision_product_images`（默认 6）与 `vision_timeout_seconds`（默认 240）；已冻结 6 项额度的任务读到同样的默认值 |
| 51 个候选图下载全部在 1 秒内失败，原因不可见 | 本机 DNS 把全部域名解析到非公网地址（常见于代理“fake-IP”模式的 198.18.0.0/15），被公网地址规则拒绝 | 拒绝规则**不变**；失败原因现在带地址类别（如 `MEDIA_PUBLIC_ADDRESS_REQUIRED:benchmarking_198.18.0.0/15`），`candidate-media.json` 的 `attempted[].failure` 逐项记录 |
| 无候选图的单元仍被送入原生会话 | 会话只能回答 needs_info | 宿主不再把无留存候选图的候选送入会话，在 `last-run.json` 以 `phase=media` 报告一次原因，工作留在原手写路径 |
| 官方浏览器核验计划在出网前被拒 `CANDIDATE_PLAN_READING_CONTRACT_INVALID` | API 额度用尽后生成的 Patent Public Search 兜底行没有 `required_facts/reading_scope` | 兜底行带 `["protection_content"]` / `{"level":"protection_content"}`（与分流动作行同形；两者是元数据键，不改变 query_id） |
| EPO 来源的美国申请公布号（本次 37 个美国申请中 15 个）按原样请求 SerpApi 详情得到“无结果”，白耗额度 | EPO docdb 把申请号写成 `US2018201441A1`（缺前导 0），USPTO/Google/PPS 用 11 位 `US20180201441A1` | `common.canonical_patent_number`：比对键与向 SerpApi/PPS 发起的请求统一为 11 位；候选自身号码不改 |
| 设计检索的合法零结果被记成失败，重试耗掉额度 | `Google Patents hasn't returned any results…` 与客户端只认的 `Google hasn't…` 不同 | 增加该精确文本，仍要求成功信封且 `organic_results` 为空，其它错误文本仍不能变成零 |
| 一次“详情无结果”撤销了同操作的全部自动验收，7 条来源操作审阅只能手写 | 任何更晚的失败运行都会撤销首响应验收 | 成功信封下的精确“无此文献”应答记为 `PROVIDER_RECORD_NOT_FOUND`，不再撤销验收；候选仍走原兜底路线 |
| EPO 搜索无法自动验收 | 美国计划行的 CQL 同时请求 `pn=WO`，WO 记录被当成国家不一致 | 验收按计划 CQL 中的 `pn=XX` 办公室集合比对；未被请求的办公室仍判不一致 |
| 10 个 Serper 同款销售线索卡在“身份定位”，卡片却指向仅限 Lens 的记录器 | `record_public_identity.py` 只接受 Google Lens 视觉/精确匹配 | 该卡片按线索实际来源给出可用路线（有来源号码→身份更正；仅用户可补→`needs_info`+`user_information`；仅是销售页→`not_selected`），不再指向不适用的记录器 |
| 03B 结果审阅宿主对 9 个有界单页检索全选 `refine`，再被手写改成 `awaiting_capability` | 提示没说明各 `next_action` 的含义与路线限制 | 结果审阅单元带 `route_scope`、`refinement_round`、`max_refinement_rounds`，提示写明：只缺“这一页之外”的召回选 `awaiting_capability`，有具体更窄查询才选 `refine` |

仍未放宽的规则（需要由你决定）：本机代理的 fake-IP 地址（198.18.0.0/15）是否允许用于候选图下载。当前保持拒绝；放行只会让下载连接到代理分配的地址，TLS 仍须校验原主机名，但这属于安全边界，不替你默认放开。（后续：r5d4 起按用户决定 F3 放行——确认本机 fake-IP 时可经代理下载公开文件；r9 起只开系统代理时下载经该代理，见 [一键流水线](pipeline.md) 的 r9 一节。）

## 第五轮（真实运行 US-B07HQL3SPZ-20261011-100725 的校正）

终审“最后一公里”的失败与现场补丁的回收：下表每项都在该运行的持久化数据上做过回放（摘要 `b11648b7…` 不变、六个留存模块包与提示逐字相同、`work_view` 与 Codex 最终状态一致）。

| 现象 | 根因 | 处理 |
|---|---|---|
| 终审 2 秒内失败 `REVIEW_MATERIAL_CLASSIFICATION_REQUIRED` | 非技术模块把带来源的专利文献记录按 US 前缀剔除，但资产溯源仍以同一路径与哈希引用该 PDF，文件清单只看本模块投影判为非公开 | `module_packet` 新增 `shared_public_originals`（仅非空时出现，旧回执字节不变），分类与附件据此认公开来源 |
| 6 个模块全部跑完仍无报告 | 行级 `evidence_refs` 漏列 1 条已出现在嵌套字段中的 ID；校验按顺序遇错即停 | 行级并集派生（`row-evidence-ref-rollup-v1`，留痕、可复算）+ 逐位置捕获；归档尝试经派生合格后提升复用 |
| 补跑被 900 秒预算截断 | 额度按一次通过设计，早失败也按整段计费 | `bounded-execution-v2`：终审额度随国家数增加、最多 3 次启动、每槽 1 次内容重试；`--preflight` 干跑；所有者终端追加通道 |
| 2 个 PPS 外观核验 + 核心专利 0 次成功 | PPS 4.4.0 把注册通知改成模态结构，旧识别依赖 4.3 的内部类名而放弃关闭；点击仍被遮挡 | 按通知自身文字识别、只经页眉关闭控件关闭（绝不触碰“Create USPTO.gov account”），点击被其遮挡时关闭后重试一次；2026-11-07 起通知变为强制登录，仍不处理 |
| 14 条无图网页线索被视觉宿主接走只能手写 | 视觉宿主的类型集合含 `unknown`，无图线索“无图可比” | 无图的公开网页线索（`right_type=unknown`、`candidate_nature=web_result`）交文本宿主；视觉宿主让出（仅新任务） |
| 核心专利拿不到 API 现行状态/权属 | SerpApi 额度（r5d16 前为 10 次，新任务 20 次）被摘要级候选先到先得占满 | 每个尚无自己详情请求的“产品自称专利”线索为其保留 1 个额度（最多 2）；该线索自身与无线索任务不受影响 |
| EPO 记录无 JSON 卡片时整个 `collect` 中止 | 无行哈希的 XML 回执被当作位置不一致 | 无卡片回执不供链接，不再抛错 |
| 美国申请公开号零补位使详情绑定被拒 | 用 `!=` 比较 docdb 与 11 位拼写 | 两侧都规范化后比较（仍拒绝类型或国家不同） |
| 仅改“未映射线索”说明的方向复审使已提交查询全部孤立 | 比较含理由/时间/摘要等非语义字段 | 新任务（host_triage 族）按语义同一方向保留已提交链；`input_template.py --direction-rereview 情景:权利:国家` 生成方向复审模板并自动带入在案复审的未变部分（首次复审与线索/方向清单变化时仍为全空模板） |
| 已读准确原件的身份事实被忽略后重复浏览器核验 | 只信 protection，不信 identity | identity 同样可抵（仍永不抵现行状态/权属/地域） |
| 4 个 Serper Images 单页检索永远要求重新规划 | 方向语义不认 images 操作 | 加入 `bounded_public_images_api` 路线（操作、权利、法域与请求参数精确匹配） |
| 追加式有界审阅被“恰好一条”误判 | 5 处取唯一，2 处取首条有效 | 新任务取当前有效末条（被取代的 stop 不复活） |
| 每次计算进度视图约 30 秒 | 同一回执在一次计算里被解析数百次 | 对只依赖回执字节的纯解析按内容哈希备忘（输出逐字节不变；约 33→20 秒）；`validate_supplement` 的文件校验按设计从不缓存 |
| 本机代理 fake-IP 使全部图片被拒 | 零售站域名不可穷举 | `setup_skill.py --check-network` 只做 DNS 解析并给出 Clash/Surge 修法；下载失败时汇总一次说明 |

**交付后自检补上的可达性缺口**（功能已实现但真实流程里没有入口）：

| 缺口 | 处理 |
|---|---|
| 无图网页线索：宿主已让出，但动作卡仍写“运行 visual_triage_host”，且不给 `batch_text_triage` | 动作卡与宿主同判（`host_triage.text_only_lead`）：这类线索只带 `batch_text_triage`，视觉卡不再指向它们 |
| 有界公开检索的“范围结束”证明要求对**这一份响应**有明确 accepted 的来源操作审阅；操作级的验收复用（同提供方/操作/国家/权利的某次首响应）不等于审阅这一份，且它会压住 `SOURCE_OPERATION_REVIEW_REQUIRED`，剩下的只有一个永远关不掉的“重新规划”（真实运行里靠读代码才发现） | 其余条件都满足、只缺这条审阅时，host_triage 任务改给 `SOURCE_OPERATION_REVIEW_REQUIRED`（带 `purpose=bounded_public_scope_proof`，`input_template.py` 出 operation 模板）；判断仍由主 Agent 对实际回执作出 |
| `after` 审阅已给出 `refine`，主 Agent 要改判时没有模板 | 带 `source_run_id`/`direction_id` 的“重新规划”条目（非历史表达缺失）现在给 after 模板，`next_action` 等判断字段仍为空 |
| 主动重审方向（线索原为 awaiting_information、现有证据已回答）没有任何工作条目，带入模板无从触发 | `input_template.py --direction-rereview 情景:权利:国家` 显式请求 |
| 图片下载全部因 fake‑IP 失败时，宿主只给原因，不给修法 | 宿主 `next_action` 直接写出原因、`setup_skill.py --check-network` 与 Clash/Surge 修法 |
| 声明级宿主校准在全是“人工排除”的任务上会“零不安全分歧”地空洞通过 | 校准报告新增 `positive_controls`/`verdict`：没有人工保持入选的对照时为 `inconclusive_no_positive_control`，不得据此启用 |

**仍不做的事**（经分析没有可安全优化的点，不硬改）：来源操作验收与有界停止属判断型账目，不由程序代签；`review_transport_view` 重复计算每次不足数秒，且提示必须与留存字节逐字相同，不为它冒风险；7 国任务单会话提示越过 1,048,576 字符，当前设计装不下，保持“缩小范围重新冻结”，建议每任务不超过 2 国。
