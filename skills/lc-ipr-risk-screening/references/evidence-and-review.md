# Evidence, Review, And Release Gates（Ruleset 2.0）

本文件定义 v2 的正式判定语义。机器可读规则以 `references/risk-rules.v2.json` 为准，并由 `references/contracts/risk-rules.schema.json` 校验。legacy CLI 只负责采集、账本与冻结；`node tools/ipr-risk-v2.mjs` 是候选法律语义、评级、聚合、报告和 release gate 的唯一权威实现。任何 legacy `material` 或草稿 `high/low` 都不是 v2 法律结论。

## 八个正式模块

冻结查询计划可以继续复用旧版共享发现链，但正式审阅必须分别覆盖：

1. `appearance_design`
2. `utility_patent`
3. `pending_patent`
4. `word_mark`
5. `figurative_mark`
6. `trade_dress`
7. `copyright_creative_ip`
8. `enforcement_public_signals`

旧模块 `figurative_trade_dress` 只允许存在于 legacy 发现记录。迁移时应根据证据内容拆到 `figurative_mark`、`trade_dress`。如需派生第二条候选，必须保留原候选，让派生候选以 `duplicate_of` 直接引用它，并共享 `evidence_cluster_id` 与 `independence_group`；不得把同一来源当成两项独立风险证据。

## 四维结果

四个维度必须分别计算、分别展示，不能相互代替。

### `discovery_status`

- `no_lead`：已完成计划范围内的发现，未产生需要进一步审阅的线索；不等于低风险或可以销售。
- `leads_found`：只存在已处置的 `provenance_lead`、`comparison_only` 或缓释/背景线索，尚未形成合格风险驱动候选。
- `review_required`：至少存在 `risk_bearing`、`unresolved`，或关键来源链问题需要补证和结构化法律测试。
- `blocked`：关键覆盖、迁移、证据、评级事实冲突或处理门禁失败，当前无法完成要求的审阅。

### `legal_risk`

- `not_assessable`：证据或结构化法律测试不足，不能形成正式等级。
- `very_low`：覆盖充分、来源链完整，且不存在合格的风险驱动候选。
- `low`：候选已完成审阅，但保护范围、整体印象、商品服务、表达或执法对象存在明确实质差异。
- `medium`：存在具体且有意义的重合或来源链冲突，但权利、范围、复制、授权或其他关键事实尚未闭合。
- `high`：权威证据支持相关权利，受保护范围与目标商品高度重合，且没有有效授权、排除事实或其他可信缓释证据。
- `critical`：已经满足 `high`，并存在针对同一商品或同一风险对象的投诉、诉讼、TRO、扣押或平台执法等现实紧迫性。

未知事实本身不构成 `medium/high`。只有“已有具体风险事实 + 未闭合的关键事实”才能形成 `medium`；纯粹缺证据应为 `not_assessable`。

### `risk_confidence`

- `high`：关键事实有权威或可追溯的一手证据，覆盖完整，模块法律测试无关键未知项。
- `medium`：结论的主要事实已被支持，但仍有不改变方向的次要缺口。
- `low`：关键图片、权利范围、权属、授权、状态、法域、来源或数据源缺失，或审阅事实存在争议。

`risk_confidence` 衡量现有法律风险结论的可信程度。另用 `coverage_confidence` 表示八模块整体发现覆盖质量；总体 `risk_confidence` 只随最高风险驱动模块计算，不机械取所有模块最低值。

### `operational_action`

- `proceed`：风险不高于 `low`、证据与覆盖充分，且没有未闭合门禁。
- `proceed_with_conditions`：风险可控，但必须落实指定设计修改、授权留档、标识调整或监控措施。
- `hold_for_evidence`：法律风险尚不能确认，需先补图、权属、授权、权利范围、来源或覆盖证据。
- `escalate_legal`：存在 `high/critical`，或复杂的 `medium` 事实需要美国知识产权律师判断。

证据中性的法律评级与保守的运营门禁可以并存，例如 `legal_risk=medium`、`risk_confidence=low`、`operational_action=hold_for_evidence`。

## 候选完整性与 v2 法律语义

- 每个 provider item 都必须按 `(run_id, source_index)` 进入候选记录，分组不能隐藏来源条目。
- Agent 必须一次性处置当前 v2 工作区中的全部候选；未解决条目使 `discovery_status=review_required` 并阻断正式评估。
- legacy `material` 或 `needs_review` 只表示旧流程曾要求重点查看或继续审阅。迁移后必须设为 `legal_materiality=unresolved`、`risk_driver_eligible=false`，不得自动成为风险驱动候选。
- 所有迁移记录初始为 `legacy_reassessed=false`。此时 `material/needs_review` 必须保持 `unresolved`，`not_material` 必须保持 `not_material`；只有审阅者重新核对原始证据并显式设为 `legacy_reassessed=true` 后，才能按 v2 事实重新分类。
- `legacy_reassessed=true` 不删除或改写 `legacy_disposition`，只记录 v2 复评已经发生。需要拆分模块时使用带 `duplicate_of` 的派生候选，不能删除原 provider item。

每条 v2 候选至少要填写：

- `record_kind`：`right_record / application / enforcement_event / marketplace_page / creative_source / comparison_material / non_right_page`。
- `legal_materiality`：`risk_bearing / provenance_lead / comparison_only / mitigating / not_material / unresolved`。
- `evidence_role`：`risk_driver / provenance / context / mitigating`；`authority_tier`：`official / authoritative / primary / commercial / unknown`。
- `target_jurisdiction`、`source_jurisdiction`、`right_jurisdiction`：不得把页面站点、资料来源地与权利法域混为一谈。
- `evidence_cluster_id`、`duplicate_of`、`independence_group`：对同图、同商品、同权利、转载页和跨模块复用证据去重。
- `risk_driver_eligible`：只有 `legal_materiality=risk_bearing`、证据可追溯且模块测试完整时才可为 `true`。

商城、社交媒体、博客和反向图搜页面通常只能作为 `provenance_lead` 或 `comparison_only`。它们可以帮助寻找最早来源或权利人，但页面数量不证明权利数量、权属、有效性或侵权。

图搜分数、标题相似度、搜索排名和候选数量只能用于召回与排序，不得直接进入 `legal_risk` 计算。

## 证据聚类和独立性

- 同一商品、图片、权利记录或内容的转载页面必须归入同一 `evidence_cluster_id`。
- `duplicate_of` 必须指向簇内规范候选；报告同时保留原始结果数和去重证据组数。
- `independence_group` 表示能独立支撑风险判断的权利或事件。同一页面横跨商标、商业外观和版权模块时仍只是一组来源证据。
- 聚类只消除虚假证据强度，不得删除 provider item 或原始引用。
- v2 不执行候选数量累加或 `compound_escalation`。多项独立风险可以改变 `operational_action`，但不得机械把法律等级升一级。

## 受控核验事件

`record-verification` 只登记已经由用户、律师、后端或其他授权流程完成的核验，不访问官方站点、不验证任务外材料真伪，也不把未知事实自动改成已核实事实。命令要求先由 `migrate-candidates` 生成当前 `v2/source-manifest.json`，evidence ledger 已冻结、discovery coverage checkpoint 完整，且事件绑定冻结 ledger 中的原始候选：

```bash
<IPR_V2_RUNTIME> record-verification --kind official --task-dir <task-dir> --input <official-verification.json>
<IPR_V2_RUNTIME> record-verification --kind copyright --task-dir <task-dir> --input <copyright-provenance-verification.json>
```

- `official` 输入遵守 `official-verification.v2.schema.json`，绑定美国权利身份、现有 ledger `evidence_refs`、官方状态/授权、来源定位和核验主体；维权事件还要绑定案件、当前商品 digest 与底层风险候选。
- `copyright` 输入遵守 `copyright-provenance-verification.schema.json`，绑定当前 `candidate_key` 和 evidence revision；资产位于任务内 `raw/`，证明材料位于 `raw/copyright-provenance/`，所有文件均以 SHA-256 固定。该候选级事件不能替代 `very_low/proceed` 的逐商品图片来源声明门禁。
- runtime 生成或校验事件 digest，把事件分别登记到 `normalized/official-verifications/` 或 `normalized/copyright-provenance-verifications/`，同时增加 ledger revision、重新绑定 coverage checkpoint 并重封 source manifest。不得手工编辑 ledger、coverage、source manifest 或 normalized 事件。
- 录入返回 `assessment_rebuild_required=true`。此后必须从 `migrate-candidates` 重建全量候选，在对应原候选的 `verification_refs` 中纳入全部冻结事件，再重跑 Assessment、必要二审/裁决、报告和 release gate。旧 context digest、Assessment 与报告均不可复用。

## 模块专属审阅规则

### 外观设计 `appearance_design`

必须获取或明确记录以下事实：

- 美国外观专利或可适用权利的权威记录、法域与状态；
- 完整官方图组及实际主张部分，区分实线、虚线和不主张内容；
- 目标商品与权利图中的主导共同特征、主导差异和完整多视图比较；
- 同类购买者视角下的整体视觉印象结论。

只有有效、相关法域的权利与目标商品在受保护整体印象上高度接近时，才允许 `high`。检索图片相似度再高，也只能用于召回。缺官方图组或主张范围时限制置信度或设为 `not_assessable`，不得因“状态有效”自动设置风险 floor。

### 实用专利 `utility_patent`

必须以独立权利要求为单位建立逐元素映射，逐项记录 `present / absent / unknown` 及证据引用。标题、摘要、技术主题、分类号或同属一个产品类别都不能替代 claim chart。

只有至少一项可适用且可执行的独立权利要求，其全部必要元素都有证据映射，并且没有明确缺失元素时，才允许 `high`。存在明确缺失元素通常不高于 `low`；缺少完整权利要求或产品结构证据时应限制置信度或 `not_assessable`。

### 申请中专利 `pending_patent`

申请中的公开权利要求用于监控未来范围，不视为当前已授权权利。审阅仍需逐元素映射，并记录程序状态、权利要求可能变化以及后续监控日期。

单凭申请中记录不得形成 `high/critical`。具体且高度重合的申请可以形成 `medium` 与 `proceed_with_conditions` 或 `hold_for_evidence`；标题或技术主题命中只构成发现线索。

### 文字商标 `word_mark`

必须组合判断：标识相似程度、商品/服务关联、销售渠道、消费者、标识强度以及现有混淆证据。文字完全相同但商品/服务和市场渠道实质无关时不得为 `high`。

正式风险驱动候选应有可追溯的美国权利记录或其他可信权利基础。只命中一个品牌词、型号片段或搜索结果页通常为 `comparison_only` 或 `not_material`。

### 图形商标 `figurative_mark`

仅审阅作为来源标识使用的图形、Logo、图案或包装标识。必须比较主导图形要素、整体商业印象、商品/服务关联、渠道和消费者。商品造型相似但没有来源标识功能的内容不得在本模块驱动风险。

### 商业外观 `trade_dress`

必须识别权利人主张的具体元素组合，并评估：

- 非功能性；
- 固有显著性或第二含义；
- 作为来源标识使用的证据；
- 目标商品与该组合造成混淆的可能性。

泛化的产品风格、同款商城页或反向图搜命中不构成可识别的商业外观权利主张。缺少非功能性或显著性事实时不得为 `high`。

### 版权/创意资产 `copyright_creative_ip`

必须分别审阅产品雕塑/装饰造型与 Listing 图片、文案、包装等素材。每一类至少记录：可保护表达、具体共同表达与差异、复制或接触线索、作者/创作者、最早可验证来源、权利人、授权范围、地区、期限以及 Amazon 商业使用权限。

- 同款商城页通常只属于 `provenance_lead`；页面存在不证明其发布者拥有版权。
- 只有具体可保护表达高度一致且权利基础可信、确认没有所需授权时，才允许 `high`。
- 具体表达高度一致但权属/授权链未闭合时可为 `medium + low confidence + hold_for_evidence`。
- 多个商城 `provenance_lead` 即使确认是同一具体资产，也只能触发来源补证和 `hold_for_evidence`；没有另行复核为 `risk_bearing` 的创意来源或权利候选时，不得把法律风险升为 `medium`。所有转载页仍须聚为一个证据簇。
- 纯粹缺少来源材料、没有具体复制或相似事实时应为 `not_assessable`，不得自动升高风险。
- 版权模块为 `very_low`、总体为 `very_low` 或运营动作为 `proceed` 时，release gate 额外要求 `product.images[]` 每张图片恰有一条 `state=provided` 的来源声明与路径/SHA-256 精确匹配，且不能混入 `unknown` 声明。每条声明必须有非空作者、权利人、明确权利基础、允许商业/Amazon 使用的范围、覆盖美国的地区和有效期限，并引用任务内 `raw/copyright-provenance/` 结构化证明；证明中的 `commercial_use_allowed`、`amazon_use_allowed`、`territory_includes_us`、`term_valid` 必须均为 `true`，且资产与权利身份和声明一致。

### 公开维权信号 `enforcement_public_signals`

候选必须绑定可识别的案件、投诉主体、相关权利、目标商品/卖家和程序状态。泛泛讨论“侵权”“专利”或某权利人的其他案件，不是目标商品的执法信号。

本模块单独评估现实紧迫性，并与相关实体权利模块建立引用。只有已经满足实体 `high`，且存在针对同一商品或同一风险对象的有效投诉、诉讼、TRO、扣押或平台执法时，整体才允许 `critical`；两类候选必须使用同一 `independence_group` 建立案件/风险对象关联。

## 约束、聚合与决策追踪

- 确定性风险 floor 只允许由已核实的结构化风险事实触发，例如有效权利与完整保护范围高度重合，或确认无授权地复制具体版权资产。
- 数据源失败、图片覆盖不足、权属/状态未知和来源链不完整只能形成 `confidence_cap`、`formal_conclusion_blocked` 或补证动作。
- `overall.legal_risk` 取拥有合格风险驱动候选和完整模块测试的最高模块风险。覆盖充分、八模块均完成且没有风险驱动候选时可以为 `very_low`；因缺口而没有任何可评估模块时为 `not_assessable`，不能从候选数量推导。
- `overall.risk_confidence` 由最高风险驱动模块决定；`coverage_confidence` 独立反映八模块发现覆盖。
- runtime 必须在 `decision-trace.json` 中记录规则版本、输入摘要、风险驱动候选、命中条件、置信度限制、阻断项、聚合过程和运营动作原因。
- 所有 `high/critical` 必须至少关联一个权威来源、一个 `risk_driver_eligible=true` 的独立候选以及完整的模块专属测试字段，否则 release gate 失败。

## 独立二审与冲突处理

- 需要二审时每轮输入遵守 `assessment-review-input.v2.schema.json`，使用不同 reviewer ID 和 session；没有真实运行时隔离证明时不得声称 `runtime_enforced`。
- 审阅者提交结构化事实、证据引用和法律测试，不以自由文本标签覆盖规则引擎。两审都必须覆盖每个 `risk_bearing` 候选的全部必需评级 factors；漏审、单边观察或未知状态不能沿用 base input 的旧事实。
- 每份正式 review 必须有 `review_id` 和不可变 digest，并绑定同一 assessment context、候选 evidence digest、独立 reviewer/session。只有两审对同一路径给出相同值且均有支持证据时才合并，再让 v2 runtime 从合并后的事实重新计算风险和置信度。
- 禁止执行“风险取高、置信度取低”的标签级合并。
- 对评级无影响的措辞差异不触发人工裁决。风险驱动事实、证据身份、保护范围或授权状态存在未解决冲突时，相关模块和总体设为 `discovery_status=blocked`、`legal_risk=not_assessable`、`risk_confidence=low`、`human_resolution_required=true`、`operational_action=escalate_legal`，再记录人工裁决。
- 人工裁决遵守 `human-resolution.v2.schema.json`，必须选择有证据支持的结构化事实并绑定 context/evidence digest，不能绕过 `high/critical` 的硬性证据要求。
- review 不能自行写入 `resolved_by_*`。只有 `merge-reviews --resolution ...` 验证通过的不可变裁决文件才能改变冲突状态；既有未解决冲突会跨再次合并保留。

## Draft 与 release 规则

- `report-v2/report_data.json` 是 v2 报告的唯一视图模型；HTML 和 Markdown 必须只从它渲染。
- Assessment 未完成、候选仍有 `unresolved`、关键冲突未解决或正式结论被阻断时，只能输出 draft/incomplete。
- 草稿的 `legal_risk` 必须是 `not_assessable`、`risk_confidence` 必须是 `low`，首页显示“评估尚未完成”，不得显示 `very_low/low/medium/high/critical` 风险徽章。
- 草稿可以显示 `discovery_status`、候选数量、去重组数量和具体缺口，但不得把发现紧急度命名为法律风险。
- 正式报告必须分别显示发现状态、法律风险、风险置信度、覆盖置信度和运营动作，并列出风险驱动证据与去重口径。
- manifest 绑定每个产物的 SHA-256 和字节数；任一摘要、规则版本或输入 digest 不一致都必须失败。
- `source-manifest.json`、`assessment-input.snapshot.json`、`coverage.json`、`decision-trace.json` 以及必要时的核验、二审和裁决事件必须与 Assessment 交叉绑定。正式发布还要逐文件核对冻结 product/query/ledger/discovery coverage 及其引用来源、全量候选及其 ledger lineage、全部冻结核验事件和候选 `verification_refs`、每条原始候选的 `legacy_disposition/legacy_reassessed`；替换任一来源、规则、候选、核验、审阅或裁决后旧报告不得通过 release。
- `validate-release` 只允许 v2 runtime 生成并校验 `<task-dir>/report-v2/`；legacy `report/` 或 `report-draft/` 不得作为 v2 正式交付。
- 已存在的 legacy 报告只作为历史发现证据，展示时必须标记 `legacy discovery report`；不得覆盖原文件或把旧 `high/low` 重新解释为 v2 法律评级。
- 报告必须明确说明它是风险筛查，不是官方法律状态确认或法律意见；`low/very_low` 也不得表述为“可以放心销售”。
