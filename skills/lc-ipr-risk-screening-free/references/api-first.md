# API 优先检索契约

新任务采用 `retrieval_workflow_revision=api-first-v3`、`review_policy_revision=final-double-review-v1` 与 `completion_policy_revision=necessary-work-v3`，先按 [API 直接采信与最终双审](api-direct-final-review.md) 执行。已满足的 API 事实不再要求官方网页复核；美国外观保留 SerpApi DESIGN 路线，图像和维权查询按实际权利路由。下文 v2 的来源发现、预算和历史补搜合同在不冲突处继续适用，标记为 v2 的官方核验与双审前置只适用于历史任务；两者冲突时以本节及 [API 直接采信与最终双审](api-direct-final-review.md) 的 v3 规则为准。业务鉴权保持原规则；新任务来源消费采用[来源账户策略](source-policy.md)。

## 执行与分工

产品事实及素材盘点 → API 发现 → 合并与全量轻分流 → 按字段直接采信并最小补证 → 专项调查与比较 → 冻结后最终独立双审 → 发布。官方网页仅用于影响结论且 API 尚未解决的具体缺口或冲突。

新修订按“国家 × 权利类型 × 阶段”选择路由：首选完成最适合的步骤，配合来源补全内容或维度，备选只在首选不可用、已审结果不足或不覆盖时启用。候选发现、保护内容和目标国状态是不同步骤；Google Patents 的 Serper 与 SerpApi 是同一上游，不作为独立交叉验证。OPS 用于跨国发现，但 US、DE、JP 的权利要求全文不得作为 OPS 必经成果；JPO 仅用于已知号核验，不能生成关键词召回。具体冻结顺序由 `scripts/provider_routing.py` 保存至计划行的 `provider_role`、`source_upstream`。

`next_work.py` 是唯一工作入口。`run_api_plan.py --phase discovery` 运行初始及已获审阅依据的发现；`--phase verification` 运行候选核验、必要补证和原文读取。`run_browser_plan.py --phase verification` 只核验准确记录；`--phase fallback` 只执行已经绑定依据的有限补搜。指定 query ID 或直接客户端也必须经过同一情景分流门禁。历史任务保留原 wave 参数与语义。

API 可用性按来源、国家、权利、操作和当前账号能力判断。优先复用现有 Serper Patents/Search/Images、SerpApi Patents/Lens、Signa、OPS、INPI 和 EUIPO API；JPO 用于其支持的已知号，EPS 用于 EP 原文。来源未配置、账户容量不可确认、生产审批欠缺及响应契约未实测分别记录，其他工作继续。浏览器不绕过已有受限网页路线。

## 发现、分流与有限补搜

按目标国家、权利及事实线索形成可审阅的意图，优先高相似商品，但不删除核心结构相关而外形不同的专利。品牌、制造商等身份线索不能自动当作权利人。各 API 使用其实际支持的语法，地区和语言参数不证明权利国别。

搜索代理首批请求 10 条，官方 API 使用现有受支持的首批大小。Lens 原生接口无法限制响应条数，新行明确记录 `requested_candidates=10`、`response_limit_enforceable=false`；实际返回超出时保留并审阅全部卡片，记录实际数量、无续页及验收偏差，不宣称已经实现 10 条响应上限。保留完整公开号、标题、摘要片段、主体、日期、源页面及图片/PDF线索，缺值不编造。实际读过的图片或文献才进入比较证据；不批量下载所有候选全文。

全部已经取得且去重的候选进入既有 materiality 分流：selected 才深入核验；needs_info 仅补下一步必要材料；not_selected 留下具体依据。来源排名不代替 Agent 判断。不能因为没有案号就丢掉有价值的商品、作者和许可线索，这些先留在公开调查证据中。

`needs_info` 的素材来源补查使用现有 `source_lookup`，指定 `provider=asset_provenance`、`operation=provenance_review`；Agent 的 `params` 必须包含准确候选 ID 与当前 `asset_scope_sha256`，`reading_scope.investigation_step` 必须明确为该权利允许的调查步骤（如版权的 `provenance` 或 `visual_comparison`）。生成器保持参数原样，把合法步骤写入 `search_dimension`；缺失、过期或不适用时留下 `NEEDS_INFO_ACTION_UNSUPPORTED` 计划缺口，先修正分流动作再追加计划，不生成无法登记的调查行。历史无修订标记的动作保持原语义。

`API_DISCOVERY_TERMS_MISSING` 只适用于存在关键词/API 发现路线但没有可用搜索词的范围。无合格搜索词且当前适用范围只有 `asset_provenance/provenance_review` 的 Agent 路线时，该范围继续保留独立素材来源调查队列，不生成缺词待办；旧计划中遗留的同类缺词 gap 也不再投影为待办。有合格商品线索时仍按冻结路由和策略生成补充 API 发现；缺少 Agent provenance 路线也不会因此被视为已覆盖。

后续动作绑定父 query ID、父计划哈希、实际 source run、审阅理由及当前分流摘要。同意图最多两轮细化，切换来源不重新计轮数；每查询最多八页（同一发现目的同一版本跨来源另有合计上限，见[发现目的与版本预算](discovery-purpose-budget.md)，二者取更严者），不支持分页的路线明确止于首批。预算按意图分配，未分配范围保留可见缺口。v2 首轮按国家、权利及检索维度轮转，不让结构同义词先占满共享额度；共享额度不少于 8 次时预留约四分之一供已审补搜。该来源首批全部审阅后，运行 `generate_search_plan.py --task-dir TASK --expand` 可释放预留名额，优先补未覆盖范围；新行绑定首批回执和审阅哈希，不提高总额度。`API_DISCOVERY_BUDGET_RESERVED_FOR_FOLLOWUP` 仍是待完成工作，不能作为预算耗尽的报告依据。版权与商业外观的商品范围不自动复用独立品牌标识词。

SerpApi Google Patents 在主来源不可用或已审结果相关性不足时补搜；美国外观在 v3 保留 DESIGN 专用首选路线。Lens 可独立承担适用的图片发现。Serper Patents 与 SerpApi Google Patents 的上游均为 Google Patents，不算两个独立数据库。精确公开号去重并保留原始回执；同族不等于同一国家权利，不为增加来源数量重复查询同一事实。

API-first-v3 在初始规划时就把同一 Lens 实际请求、国家及有效图像许可绑定到一条物理请求。各权利用途保留独立的逻辑范围和分流任务，后续逻辑用途引用 `discovery_scope.physical_response_plan_reuse`，不占第二份调用预留，不经过“先创建重复调用再取消”的流程。可用已存响应须通过原文件完整性、原卡片契约及48小时有效期检查；运行时再次核对当前产品图像许可。同源未取得可用响应时，引用用途等待源回执，不自行重复提交同一请求。实际失败、未知消耗和其他国家请求不释放额度，复用也不增加独立来源数量。

有限浏览器补搜须有当前 API 失败或已审但相关性不足的证据，每必要范围最多两条收窄查询，每条最多保留 50 个去重候选。取得限定样本即返回 Agent，保留总量、未采部分及 stop reason；不得自动重复采同一批样本。普通收窄不是旧宽查询的等价替代。

v2 若首查没有可用且已授权的 API，不必制造失败请求来取得父查询：先完成本任务的来源能力检查，再生成或扩展计划。生成器仅为支持的美国浏览器文本路线生成无父查询的 `browser_fallback`，在 `discovery_scope.capability_basis` 绑定能力快照、具体国家/权利/操作和冻结授权策略；仍沿用上述范围及样本上限，图片查询不得改用文本路线冒充。能力缺失或未实测仍是 Agent 待办，浏览器实际接入验收和执行门禁也不会被该依据跳过。

## 追加计划与审阅接口

使用 `generate_search_plan.py --task-dir TASK --discovery-followup REQUEST.json` 追加记录。原查询及回执保持原字节；新行经统一分流门禁校验后才能提交。请求中的 `parent_query_id` 指向唯一父行，程序计算并保存父计划、原始回执、当前分流和限定范围的绑定信息。

- `role=refinement|fallback|browser_fallback`：提供 `provider`、`term`（kind/value/language/derived_from/strategy）、`source_run_id`、`evidence_ids`、`triage_digest`、`reviewer`、`reason` 和 `reason_code`。理由码限于 `source_unavailable`、`zero_results`、`insufficient_relevant_candidates`、`refine_scope`；备用来源须保持父查询语义，浏览器补搜须使用前三种理由。细化轮次继承同一意图，不能通过更名或换来源重置。
- `role=review`：不提交查询。提供 `source_run_id`、`evidence_ids`、`triage_digest`、`reviewer`、`reason` 和 `outcome=proceed_to_verification|stop_bounded_discovery|blocked`。`blocked` 还须提供具体 `blocker`；有限发现停止不关闭官方覆盖缺口。零结果或成功回执均须显式留下继续/停止判断，失败也须留下阻碍与替代来源判断。
- `role=plan_repair`：仅修复未提交的计划。支持把 Serper 已启用时误排为 SerpApi 主查询的同一意图追加到 Serper；提供 `provider=serper_patents`、原始 `term`、`reviewer` 和 `reason`。v2 无父首查的能力快照变化时，也可提供旧行的 `parent_query_id`、同一 `provider`、`reviewer` 和 `reason`，追加绑定新快照的同语义行。旧行保留并写入既有取消记录；不得更改查询含义，不能修复已经提交或提交状态未知的行。

v2 的未知提交先检查原始回执。未审阅时保留 `submission_unknown`，不得重复请求；若实际审阅后仍无法确认，使用同一 `role=review` 接口，设置 `outcome=blocked`、具体 `blocker`，并提供 `submission_review.state=unknown_after_receipt_review` 和具体 `submission_review.reasoning`。若原运行没有原始回执路径，还必须说明 `submission_review.raw_receipt_absence_reason`；其余审阅字段仍全部必填。记录器从本地实际文件计算回执哈希、字节数和 source run 哈希，绑定当前分流，不接受自填哈希代替取证。有效审阅仅允许把这一限制披露为未官方核验，不改原提交状态、不释放未知消费、不允许重发；回执、运行记录或审阅依据变化后重新打开待办。

`triage_digest` 由 `api_first_planning.triage_digest(..., query_id=父查询ID)` 生成；它绑定该查询全部候选的当前分流。来源成功不直接清空待办：真实响应中的每张卡片先按来源记录哈希关联归一化候选，再按候选实际权利类型完成必要范围的轻审，最后作补搜或停止判断。缺卡、缺哈希、原始回执与载荷不一致、未分流、未决补证均不能授权后续搜索。跨类型卡片保留真实类型，专利查询返回外观记录时也须据实际类型审阅。

跨境或来源法域未知的卡片按其实际候选范围分流；例如 WO 文献可在 `UNLOCATED` 范围作当前判断，不能借用同批 US 候选判断。`stop_bounded_discovery` 可保留当前 `needs_info` 卡片，但每个 action 都须有当前有效依据和准确材料引用；`professional_review` 必须有匹配的追加式 `waiting` 结果记录、外部依赖和恢复条件，`user_information` 须由当前注释明确记为仅用户可提供的信息。遗漏或失效的动作继续阻止停止。`needs_info` 仍显示未解决，不会被改记为 ordinary triage complete。此例外仅服务有界停止，普通来源卡片门禁仍要求 `selected` 或 `not_selected`。

历史追加的分页行不能扩展父查询冻结的 `max_pages`／`max_candidates` 预算。超出预算的行保留原计划和回执，但在执行／工作视图投影为版本限额阻断，不能重置计数或提交超范围页面。

`next_work.py` 派生显示 `API_DISCOVERY_MERGE_REQUIRED`、`API_DISCOVERY_TRIAGE_REQUIRED` 和 `API_DISCOVERY_REVIEW_REQUIRED` 等待办，继续保留原有官方范围缺口。查询和计划错误、尚未支持的 USPC 等原生分类字段与额度不足分别留下具体计划缺口；不能把不支持的字段改作普通文本后宣称分类已检索。

v2 每次从当前能力重算旧计划缺口。`API_DISCOVERY_REPLAN_REQUIRED` 表示已恢复路线或能力尚待核验：先完成对应来源检查，再运行 `--expand`；已有无父首查提示 `API_DISCOVERY_CAPABILITY_SNAPSHOT_CHANGED` 时使用上述 `plan_repair`。仅真实不可用来源或已审有限发现能形成保留限制，不能把旧 gap 标签、缺失能力快照或尚未读/未审结果当成终止证据。

## 调用预算与账户容量

`references/runtime-config.json` 的 `api_first` 是新默认值唯一配置源，创建时冻结到 task.retrieval_policy。Serper 合计 30 次、三类操作动态共享；SerpApi 合计 10 次、Patents/Lens共享；Signa 3 次。旧任务仍按旧 10/3 等上限核验。次数不是积分单位；新任务允许现有付费容量，不自动购买、充值、升级或启用超额，历史任务仍核对免费边界。Signa 搜索、详情、媒体共同服从冻结预算。

以下账户免费属性证明适用于历史免费任务；新任务启用 Serper 即冻结现有余额使用授权，不因未证明免费属性而停止。

Serper 历史免费任务使用官方账户页面只读取证。证明须由当前账户实际可见的 Key 和账户信息导出指纹，保留脱敏正文及哈希；不能用本地 Key 指纹冒充页面取证。明确免费余额、付费余额、充值状态和支持操作的计费单位必须一致，证明最长有效 30 分钟。未知字段、过期、账户不匹配或缺 Key 均在计量前停止。本机缺 Key 时只可声明离线验收，不能声称已接通。

用户明确授权使用 Serper 现有余额、且不要求核实其免费属性时，创建任务可追加 `--use-serper-existing-balance`。这项授权与账户 Key 分离，保留授权时间、任务次数上限及禁止购买/充值的范围；不能由 Key 已配置自动推定。该分支不登录查余额，也不宣称余额已核实免费：回执标记 `user_authorized_existing_balance`、`balance_verified=false`，积分余额未知，响应实际报告的积分另行记录；继续执行跨任务原子请求预留和配额错误即停。

SerpApi 沿用 Account API，新任务接受现有付费套餐及额外积分，历史任务保持免费套餐门禁。跨任务额度复用原子预留账本，未知消费不自动退还，跨机器余额以服务端为准。来源耗尽或限流停止同源后续动作，继续其他已授权路线；不购买、充值或启用超额。

## 与现有报告的关系

发现证据仍为 `discovery_only`，不提高其权威等级。新计划和执行记录保留本轮意图、采样范围及限制，通过现有证据接口进入报告。API 首批成功、零结果或未入选候选不能证明官方原查询完整或权利当前无效。

官方覆盖或核验未完成时仍保留缺口，不把有限发现标成全面核验。v2 完成有界调查与冻结双审后默认 `--mode auto`，可交付明确未经官方核验的 evidence 报告；必要 Agent 工作未做仍阻断。历史 v1 保留原 final/stage 接口。
