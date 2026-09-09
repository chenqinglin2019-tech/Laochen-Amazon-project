# API 优先检索契约

仅适用 `retrieval_workflow_revision=api-first-v1`。新建任务默认采用该修订，历史任务不补标记、不改已执行计划。继续先执行现有业务鉴权；鉴权、定级、发布和报告生成代码不因本修订改变。

## 执行与分工

产品事实及素材盘点 → API 发现 → 合并与全量轻分流 → 最小必要补证 → 官方准确记录核验 → 专项调查 → 现有独立双审和发布。

`next_work.py` 是唯一工作入口。`run_api_plan.py --phase discovery` 运行初始及已获审阅依据的发现；`--phase verification` 运行候选核验、必要补证和原文读取。`run_browser_plan.py --phase verification` 只核验准确记录；`--phase fallback` 只执行已经绑定依据的有限补搜。指定 query ID 或直接客户端也必须经过同一情景分流门禁。历史任务保留原 wave 参数与语义。

API 可用性按来源、国家、权利、操作和当前账号能力判断。优先复用现有 Serper Patents/Search/Images、SerpApi Patents/Lens、Signa、OPS、INPI 和 EUIPO API；JPO 用于其支持的已知号，EPS 用于 EP 原文。来源未配置、免费资格不明、生产审批欠缺及响应契约未实测分别记录，其他工作继续。浏览器不绕过已有受限网页路线。

## 发现、分流与有限补搜

按目标国家、权利及事实线索形成可审阅的意图，优先高相似商品，但不删除核心结构相关而外形不同的专利。品牌、制造商等身份线索不能自动当作权利人。各 API 使用其实际支持的语法，地区和语言参数不证明权利国别。

搜索代理首批请求 10 条，官方 API 使用现有受支持的首批大小。Lens 原生接口无法限制响应条数，新行明确记录 `requested_candidates=10`、`response_limit_enforceable=false`；实际返回超出时保留并审阅全部卡片，记录实际数量、无续页及验收偏差，不宣称已经实现 10 条响应上限。保留完整公开号、标题、摘要片段、主体、日期、源页面及图片/PDF线索，缺值不编造。实际读过的图片或文献才进入比较证据；不批量下载所有候选全文。

全部已经取得且去重的候选进入既有 materiality 分流：selected 才深入核验；needs_info 仅补下一步必要材料；not_selected 留下具体依据。来源排名不代替 Agent 判断。不能因为没有案号就丢掉有价值的商品、作者和许可线索，这些先留在公开调查证据中。

`needs_info` 的素材来源补查使用现有 `source_lookup`，指定 `provider=asset_provenance`、`operation=provenance_review`；Agent 的 `params` 必须包含准确候选 ID 与当前 `asset_scope_sha256`，`reading_scope.investigation_step` 必须明确为该权利允许的调查步骤（如版权的 `provenance` 或 `visual_comparison`）。生成器保持参数原样，把合法步骤写入 `search_dimension`；缺失、过期或不适用时留下 `NEEDS_INFO_ACTION_UNSUPPORTED` 计划缺口，先修正分流动作再追加计划，不生成无法登记的调查行。历史无修订标记的动作保持原语义。

后续动作绑定父 query ID、父计划哈希、实际 source run、审阅理由及当前分流摘要。同意图最多两轮细化，切换来源不重新计轮数；每查询最多八页，不支持分页的路线明确止于首批。预算按意图分配，未分配范围保留可见缺口。首轮先跨国家安排结构、功能及分类线索；共享额度不少于 8 次时预留约四分之一供已审补搜，保留额度不自动转用备用来源。版权与商业外观的商品范围不自动复用独立品牌标识词。

SerpApi Google Patents 在主来源不可用或已审结果相关性不足时补搜；Lens 可独立承担图片发现。Serper Patents 与 SerpApi Google Patents 的上游均为 Google Patents，不算两个独立数据库。精确公开号去重并保留两份原始回执；同族不等于同一国家权利。

有限浏览器补搜须有当前 API 失败或已审但相关性不足的证据，每必要范围最多两条收窄查询，每条最多保留 50 个去重候选。取得限定样本即返回 Agent，保留总量、未采部分及 stop reason；不得自动重复采同一批样本。普通收窄不是旧宽查询的等价替代。

## 追加计划与审阅接口

使用 `generate_search_plan.py --task-dir TASK --discovery-followup REQUEST.json` 追加记录。原查询及回执保持原字节；新行经统一分流门禁校验后才能提交。请求中的 `parent_query_id` 指向唯一父行，程序计算并保存父计划、原始回执、当前分流和限定范围的绑定信息。

- `role=refinement|fallback|browser_fallback`：提供 `provider`、`term`（kind/value/language/derived_from/strategy）、`source_run_id`、`evidence_ids`、`triage_digest`、`reviewer`、`reason` 和 `reason_code`。理由码限于 `source_unavailable`、`zero_results`、`insufficient_relevant_candidates`、`refine_scope`；备用来源须保持父查询语义，浏览器补搜须使用前三种理由。细化轮次继承同一意图，不能通过更名或换来源重置。
- `role=review`：不提交查询。提供 `source_run_id`、`evidence_ids`、`triage_digest`、`reviewer`、`reason` 和 `outcome=proceed_to_verification|stop_bounded_discovery|blocked`。`blocked` 还须提供具体 `blocker`；有限发现停止不关闭官方覆盖缺口。零结果或成功回执均须显式留下继续/停止判断，失败也须留下阻碍与替代来源判断。
- `role=plan_repair`：仅修复未提交的错误主备分配。当前支持把 Serper 已启用时误排为 SerpApi 主查询的同一意图追加到 Serper；提供 `provider=serper_patents`、原始 `term`、`reviewer` 和 `reason`。旧行写入既有取消记录，不能更改查询含义，不能修复已经提交或提交状态未知的行。

`triage_digest` 由 `api_first_planning.triage_digest(..., query_id=父查询ID)` 生成；它绑定该查询全部候选的当前分流。来源成功不直接清空待办：真实响应中的每张卡片先按来源记录哈希关联归一化候选，再按候选实际权利类型完成必要范围的轻审，最后作补搜或停止判断。缺卡、缺哈希、原始回执与载荷不一致、未分流、未决补证均不能授权后续搜索。跨类型卡片保留真实类型，专利查询返回外观记录时也须据实际类型审阅。

`next_work.py` 派生显示 `API_DISCOVERY_MERGE_REQUIRED`、`API_DISCOVERY_TRIAGE_REQUIRED` 和 `API_DISCOVERY_REVIEW_REQUIRED` 等待办，继续保留原有官方范围缺口。查询和计划错误、尚未支持的 USPC 等原生分类字段与额度不足分别留下具体计划缺口；不能把不支持的字段改作普通文本后宣称分类已检索。

## 免费额度

`references/runtime-config.json` 的 `api_first` 是新默认值唯一配置源，创建时冻结到 task.retrieval_policy。Serper 合计 30 次、三类操作动态共享；SerpApi 合计 10 次、Patents/Lens共享；Signa 3 次。旧任务仍按旧 10/3 等上限核验。次数不是积分单位；请求前同时核对任务次数和实际免费积分边界。

Serper 使用官方账户页面只读取证。证明须由当前账户实际可见的 Key 和账户信息导出指纹，保留脱敏正文及哈希；不能用本地 Key 指纹冒充页面取证。明确免费余额、付费余额、充值状态和支持操作的计费单位必须一致，证明最长有效 30 分钟。未知字段、过期、账户不匹配或缺 Key 均在计量前停止。本机缺 Key 时只可声明离线验收，不能声称已接通。

用户明确授权使用 Serper 现有余额、且不要求核实其免费属性时，创建任务可追加 `--use-serper-existing-balance`。这项授权与账户 Key 分离，保留授权时间、任务次数上限及禁止购买/充值的范围；不能由 Key 已配置自动推定。该分支不登录查余额，也不宣称余额已核实免费：回执标记 `user_authorized_existing_balance`、`balance_verified=false`，积分余额未知，响应实际报告的积分另行记录；继续执行跨任务原子请求预留和配额错误即停。

SerpApi 沿用免费 Account API。跨任务额度复用原子预留账本，未知消费不自动退还，跨机器余额以服务端为准。来源耗尽或限流停止同源后续动作，继续其他已授权路线；不购买、充值或启用超额。

## 与现有报告的关系

发现证据仍为 `discovery_only`，不提高其权威等级。新计划和执行记录保留本轮意图、采样范围及限制，通过现有证据接口进入报告。API 首批成功、零结果或未入选候选不能证明官方原查询完整或权利当前无效。

保持现有定级及发布判断：未满足官方覆盖、必要比较或用户独有证据时仍保留缺口。不得为把“有限发现完成”显示为“全面核验完成”修改输出判据，也不为得到某个风险等级改写证据。发布仍使用现有冻结双审和 final/stage 接口。
