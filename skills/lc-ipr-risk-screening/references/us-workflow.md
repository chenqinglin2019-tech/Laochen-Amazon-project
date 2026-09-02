# 美国风险筛查工作流（Ruleset 2.0）

本工作流只接受 US。公开网页检索与云端知识产权服务是互补的候选发现层；二者只负责产生可追溯候选，不直接产生法律风险。

`tools/bin/lc-ipr-risk-screening-*` 是 legacy 采集 CLI，后文记为 `<IPR_CLI>`。`node tools/ipr-risk-v2.mjs` 是 v2 评级 runtime，后文记为 `<IPR_V2_RUNTIME>`。legacy CLI 负责商品事实、发现、证据账本与冻结；v2 runtime 接管候选法律语义、八模块评级、报告和 release gate。

## 发现能力与八模块审阅

legacy 查询计划仍可以使用七条发现链，其中 `figurative_trade_dress` 是共享召回入口。v2 正式审阅必须拆成以下八个模块：

1. `appearance_design`：公开专利检索、云端外观图搜与反向图搜；正式审阅比较官方完整图组、主张部分与整体视觉印象。
2. `utility_patent`：公开专利与网页检索；正式审阅使用独立权利要求逐元素映射。
3. `pending_patent`：公开申请与网页检索；正式审阅单列未来范围、程序状态和监控动作。
4. `word_mark`：品牌、型号和明确专有标识检索；正式审阅组合判断标识、商品服务、渠道、消费者和标识强度。
5. `figurative_mark`：图形标识、Logo 与包装来源标识召回；正式审阅图形整体商业印象与来源识别功能。
6. `trade_dress`：产品造型、包装和整体视觉识别特征召回；正式审阅非功能性、显著性、来源识别和混淆。
7. `copyright_creative_ip`：网页/图片检索与版权来源线索；正式审阅产品造型和 Listing 素材的可保护表达、具体复制、权属与授权链。
8. `enforcement_public_signals`：公开案件、投诉和维权线索；正式审阅案件主体、权利、目标商品与程序状态。

发现结果只回答“有哪些线索值得审阅”。图搜分数、标题相似度、排名、候选数量和同款商城页数量都不能直接设置 `legal_risk`。

本 Skill 不执行官方登记或法律状态浏览器核验。相关权利状态与正式法律意见需要用户另行通过官方渠道或律师核实；v2 runtime 只能受控登记这些外部流程已经完成的核验事件。

## 双计划与凭据

云端知识产权发现使用 `LAOCHEN_BACKEND_TOKEN`，不依赖 `SERPER_API_KEY`。公开网页检索只读当前进程的 `SERPER_API_KEY`：

- 有 Key 就本机执行；
- 环境没有时问一次；
- 用户在对话中给出 Key 时只注入当前会话并立即继续，不要求改系统变量或重启 Agent；
- 用户明确没有时跳过公开网页检索，继续云端核心发现并记录 coverage gap；
- 不向用户逐次确认调用次数或积分。

两份计划按依赖顺序生成，不能同时提前冻结。先准备并执行云端知识产权计划：

```bash
<IPR_CLI> prepare-us-screen \
  --product-facts <task-dir>/02_product_facts.json \
  --task-dir <task-dir>

<IPR_CLI> us-screen \
  --config config.json \
  --product-facts <task-dir>/02_product_facts.json \
  --task-dir <task-dir> \
  --plan <task-dir>/us-screen/plan.json \
  --approval <task-dir>/us-screen/approval.json

<IPR_CLI> import-us-screen-evidence --task-dir <task-dir>
```

计划与内部执行授权用于稳定 request ID、防重复提交、断点恢复和调用留痕。`prepare-us-screen` 返回 `status=ready` 后直接继续，不向用户索要云端积分确认或供应商 Key。

云端证据导入后，再准备并执行公开网页计划：

```bash
<IPR_CLI> prepare-serper-run --task-dir <task-dir>

<IPR_CLI> run-serper-plan \
  --config config.json \
  --task-dir <task-dir> \
  --plan <task-dir>/serper/plan.json \
  --approval <task-dir>/serper/approval.json
```

`import-us-screen-evidence` 和 `run-serper-plan` 把完成的 operation 写入同一 evidence ledger。本地图由 `us-screen` 上传一次；`prepare-serper-run` 必须等上传完成后读取受控 HTTPS 地址，才能冻结反向图搜计划。提前运行返回 `SERPER_IMAGE_TRANSPORT_NOT_READY`，该结果是 coverage gap，不是零候选。

## 图片与证据边界

- Amazon HTTPS 主图可以直接用于远程图搜。
- 本地图只由 `us-screen` 上传到专属 IPR 后端；不得使用 `/dl/`、第三方临时图床或把 base64 写入报告。
- 没有可用主图时，相关图搜必须记为 gap，不能用文字搜索冒充图片覆盖。
- `raw/`、供应商响应、evidence ledger 和 provider item 是不可变审计证据；Agent 不得修补原始字节或删除弱候选。
- 每个 provider item 必须以 `(run_id, source_index)` 保留。后续聚类只能消除虚假证据强度，不能隐藏原始来源。
- 商城和社交页面可以成为来源线索，但不能单独证明权利、权属、有效性或侵权。
- 版权模块拟为 `very_low`、总体拟为 `very_low` 或运营动作拟为 `proceed` 时，每张 `product.images[]` 必须由唯一的 `state=provided` 来源声明按路径/SHA-256 覆盖；每条声明还要引用 `raw/copyright-provenance/` 中与资产、作者、权利人和权利基础一致的结构化证明，且商业使用、Amazon 使用、美国地域与有效期限四项均为 `true`。缺失时必须补证或阻断，候选核验事件不能替代。

## 重试与失败语义

- 复跑必须复用任务目录、冻结计划、内部授权和稳定 request ID。
- `uncertain` 表示结果状态未知且可能已计费：停止当前付费链，不得换 request ID 重提。
- 明确 HTTP 5xx 且未消耗 credit 的 Serper 行记录为 coverage gap，继续其余独立查询，不自动重试失败项。
- 401/403/402/429 记录该条失败后停止后续公开网页提交；不阻断已经完成的云端发现，但覆盖不能视为完整。
- Serper 单条响应可用候选保留率不低于 90% 时，孤立畸形项进入 parser warnings；原始响应、`items/total` 差异和拒绝原因仍全部保留。低于 90% 为 `partial`，零条可用为失败。
- `ready`、可审计的 `partial` 或 `SERPER_SKIPPED_NO_KEY` 可以进入候选完整性阶段；`blocked` 必须留在当前阶段恢复。
- 图片任务慢时等待轮询，不要因数分钟等待重复提交。
- `no_result` 必须来自成功且结构有效的零候选响应；认证、配额、超时、畸形 JSON 和解析失败都不是 `no_result`。
- URL 与候选字段的规范化由运行时完成；失败时复用原任务和 operation 恢复，不改原始证据、不换 ID 重提。

这些缺口只影响 `coverage_confidence`、`risk_confidence`、正式结论门禁或 `operational_action`。它们本身不构成法律风险 floor。

## legacy 完整性门禁与冻结

发现结束后进入 `verifying_candidates`。当前 legacy CLI 要求旧版全批次处置时，读取 `serper/candidate_review_workspace.json`，一次性覆盖所有 provider item。每条必须包含 legacy disposition、结构化理由、全部证据引用和 actor/session；不得只处理高分项或用聚类隐藏来源：

```bash
<IPR_CLI> transition-task --task-dir <task-dir> --to verifying_candidates --reason "发现完成，开始来源条目完整性核对"
<IPR_CLI> apply-candidate-review --task-dir <task-dir> --input <legacy-candidate-review.json>
<IPR_CLI> evaluate-coverage --task-dir <task-dir>
<IPR_CLI> evaluate-candidate-verification --task-dir <task-dir>
<IPR_CLI> freeze-evidence --task-dir <task-dir>
<IPR_CLI> evaluate-coverage --task-dir <task-dir>
<IPR_CLI> evaluate-candidate-verification --task-dir <task-dir>
```

该处置只用于满足旧版候选清单与证据冻结门禁。`material/not_material/needs_review` 绝不参与 v2 定级：

- `material` 和 `needs_review` 迁移为 `legal_materiality=unresolved`、`risk_driver_eligible=false`；
- `not_material` 迁移为 `not_material`，但仍保留证据和排除理由供 v2 校验；
- legacy 模块 `high/low`、候选数量或 `material_total` 不得写入 v2 Assessment。

任一来源条目缺失时补齐或记录可审计 gap，不能修改 ledger 绕过门禁。证据冻结后变更任何输入或证据，都必须重新执行 v2 迁移与评估。

## v2 接管

证据冻结后只使用 v2 runtime：

```bash
<IPR_V2_RUNTIME> migrate-candidates --task-dir <task-dir>
```

命令输出 `<task-dir>/v2/candidate-review-workspace.json`，并在完整 legacy 冻结链的四个核心来源产物齐备时生成正式发布所需的 `<task-dir>/v2/source-manifest.json`，封存当前来源图谱中的任务内文件。Agent 逐条完成法律语义、法域、权威层级和去重组，写入 `<task-dir>/v2/candidate-review.json`，再执行：

```bash
<IPR_V2_RUNTIME> validate-candidates \
  --input <task-dir>/v2/candidate-review.json
```

如用户、律师、后端或其他授权流程已经提供官方记录核验或版权来源链核验，应优先在任何 Assessment 之前受控录入：

```bash
<IPR_V2_RUNTIME> record-verification \
  --kind official \
  --task-dir <task-dir> \
  --input <official-verification.json>

<IPR_V2_RUNTIME> record-verification \
  --kind copyright \
  --task-dir <task-dir> \
  --input <copyright-provenance-verification.json>
```

该命令要求冻结 ledger、完整 discovery coverage checkpoint 与当前 `v2/source-manifest.json`，只登记已完成且绑定原候选的核验事件，不发起官方查询。`official` 事件写入 `normalized/official-verifications/`；`copyright` 事件必须绑定当前 evidence revision、任务内 `raw/` 资产和 `raw/copyright-provenance/` 证明，并写入 `normalized/copyright-provenance-verifications/`。录入会增加 ledger revision、重封 source manifest，并返回 `assessment_rebuild_required=true`。

因此，录入后必须重新执行 `migrate-candidates`，全量复评并把所有冻结事件加入对应原候选的 `verification_refs`，再重新运行 `validate-candidates`。若此前已经生成 Assessment、二审、裁决或报告，它们都属于旧 evidence revision，不得复用。

随后生成 Assessment：

```bash
<IPR_V2_RUNTIME> prepare-assessment \
  --task-dir <task-dir> \
  --candidate-review <task-dir>/v2/candidate-review.json
```

正式审阅填写 `<task-dir>/v2/assessment-input.json`。候选必须按 `references/evidence-and-review.md` 聚类并完成八模块专属测试；只有 `legal_materiality=risk_bearing`、`risk_driver_eligible=true` 的独立候选能驱动法律风险。

先 dry-run，再定稿和发布：

```bash
<IPR_V2_RUNTIME> rules evaluate \
  --input <task-dir>/v2/assessment-input.json \
  --dry-run

<IPR_V2_RUNTIME> finalize-assessment \
  --task-dir <task-dir> \
  --input <task-dir>/v2/assessment-input.json

<IPR_V2_RUNTIME> render-report --task-dir <task-dir>
<IPR_V2_RUNTIME> validate-release --task-dir <task-dir>
```

v2 输出必须分开给出：

- `discovery_status`
- `legal_risk`
- `risk_confidence`
- `coverage_confidence`
- `operational_action`

证据不足可以形成 `hold_for_evidence`，但不能自动把 `legal_risk` 改成 `high`。

## 完成条件

正式 v2 报告必须同时满足：

1. 双计划中的全部必需查询已完成，discovery coverage checkpoint 为 `complete/assessment_ready`，`gap_query_ids` 为空；失败或跳过项只能形成 draft/incomplete，不能进入正式发布；
2. 所有 provider item 已进入候选清单，legacy 证据已冻结；
3. v2 候选全量处置、聚类和校验通过，没有 `unresolved`；全部冻结核验事件已由对应原候选的 `verification_refs` 引用；
4. 八模块结构化审阅及必要的独立二审/人工事实裁决完成；
5. 所有 `high/critical` 满足强制证据条件；
6. v2 `finalize-assessment`、`render-report`、`validate-release` 全部通过。

任一条件不满足时只能输出 draft/incomplete：`legal_risk=not_assessable`、`risk_confidence=low`，首页显示“评估尚未完成”，不显示正式风险徽章。草稿可以展示发现状态与缺口，但不能把发现紧急度命名为法律风险。

正式发布会通过 `v2/source-manifest.json` 逐文件绑定冻结 product、query plan、evidence ledger、discovery coverage 及其引用来源，并交叉绑定 Assessment coverage、全量候选、核验事件和每条 legacy 候选的 `legacy_reassessed` 状态。任一来源或状态变化后必须重建 Assessment 与报告。

完整报告仍是风险筛查，不是官方法律状态确认或法律意见；受控录入核验事件也不改变这条边界。
