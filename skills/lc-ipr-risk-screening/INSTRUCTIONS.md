# LC IPR Risk Screening 执行指令（US，Ruleset 2.0）

本 Skill 一次处理一个美国商品。正式结果必须完成双计划发现、候选全量迁移与处置、八模块审阅和 v2 release gate。它是风险筛查，不是官方法律状态确认或法律意见。

## 1. 两层运行时与权威边界

选择当前平台的 legacy 采集 CLI，并记为 `<IPR_CLI>`：

- Windows x64：`tools/bin/lc-ipr-risk-screening-windows-amd64.exe`
- Linux x64：`tools/bin/lc-ipr-risk-screening-linux-amd64`
- macOS Intel：`tools/bin/lc-ipr-risk-screening-darwin-amd64`
- macOS Apple Silicon：`tools/bin/lc-ipr-risk-screening-darwin-arm64`

后文 `<IPR_V2_RUNTIME>` 代表以下命令前缀：

```bash
node tools/ipr-risk-v2.mjs
```

二者职责不可交换：

- legacy CLI 只负责认证、商品事实、计划、候选发现、原始证据、证据账本与证据冻结。
- v2 runtime 负责 legacy 候选迁移、v2 候选校验、八模块规则计算、二审事实重算、四维结果、报告和 release gate。
- 禁止调用 legacy `finalize-assessment`、`render-report` 或 `validate-release` 生成正式 v2 结果。
- legacy `material/not_material/needs_review` 和其草稿 `high/low` 只属于兼容数据，不是 v2 风险结论。

macOS 首次运行前静默执行：

```bash
chmod +x tools/bin/lc-ipr-risk-screening-darwin-*
xattr -dr com.apple.quarantine tools/bin/ 2>/dev/null || true
```

第一条业务命令必须是：

```bash
<IPR_CLI> auth-check --config config.json
```

只有 `reason_code=AUTH_PASSED` 才能继续。随后立即校验 v2 runtime 与规则：

```bash
<IPR_V2_RUNTIME> version
<IPR_V2_RUNTIME> rules describe
```

两条命令必须确认 `ruleset_version=2.0`，并能加载 `references/risk-rules.v2.json`。runtime 或规则不可用时，可以完成发现并交付证据，但不得由 Agent 自行推导或显示正式法律风险。

## 2. 凭据

`LAOCHEN_BACKEND_TOKEN` 优先于 `config.json.backend_token`。公开网页检索只读进程环境变量 `SERPER_API_KEY`：

- 环境里有 Key：本机直连 Serper，费用由用户自己的账户承担。
- 对话、本轮附件或用户上传文件里出现 Key / 疑似 Key：只注入当前会话环境变量，然后在同一会话直接运行 CLI；不要再问、不要要求修改系统变量或重启 Agent。
- 环境和对话都没有：问一次。用户明确没有时跳过公开网页检索，继续云端商品详情和知识产权发现。
- 禁止把 Key 写入 `config.json`、命令参数、任务目录或报告，禁止回显。

## 3. 输入与任务目录

只接受 `marketplace=US`、美国 ASIN 或 `amazon.com` 链接。非 US 在任何远程调用或图片上传前停止。

认证通过后，首轮提示必须同时暴露图片输入能力：

> 请发送一个美国 Amazon 商品的 ASIN 或 `amazon.com` 商品链接；也可以同时上传商品主图和细节图。一次仅处理一个商品。

ASIN/链接路径会通过云端商品详情优先取得可信 Amazon 主图，用户上传图片是可选补充。若用户改用完整人工资料，则必须提供标题、至少一条五点、长描述和至少一张清晰主图；缺失时只追问缺失项，不启动远程筛查。

为本轮确定一个尚不存在的唯一目录 `ipr_screening_YYYYMMDD_HHMMSS/`，放在技能包外，不要提前创建空目录。禁止把 `--output-dir` 或 `--task-dir` 设为 `.`、技能包根目录或 `tools/`，任务产物不得写入 `SKILL.md` 所在目录。`collect-product --output-dir` 会通过临时目录原子生成正式任务目录；后续命令必须始终复用它，不能再建第二个任务目录。按 `references/input-routing.md` 执行：

```bash
<IPR_CLI> inspect-input <输入参数>
<IPR_CLI> collect-product <输入参数> --task-id <task-id> --output-dir <task-dir>
<IPR_CLI> validate-product --input <task-dir>/02_product_facts.json
```

ASIN 路径的 `inspect-input` 应返回 `seller_lookup.provider=laochen_backend` 与 `action=product_detail`。`collect-product` 使用 `config.json` 与 `LAOCHEN_BACKEND_TOKEN` 调用云端商品详情并冻结事实；不要在本机安装、配置或调用其他上游商品数据工具。再按契约写入 `<task-dir>/input-metadata/product-corroboration.json`，然后执行：

```bash
<IPR_CLI> validate-product-corroboration --task-dir <task-dir>
```

人工资料完整时禁止调用 SellerSprite。商品字段、图片角色、来源、版权/许可链和 SHA-256 必须冻结；不能用一句标题和一张图代替完整采集。

若希望版权模块形成 `very_low`、总体形成 `very_low` 或运营动作形成 `proceed`，必须在商品事实冻结前准备完整的逐图片版权来源：

- `product.images[]` 中每张图片恰有一条 `state=provided` 的 `provenance_declarations[]`，其 `asset_ref` 和 `asset_sha256` 与图片路径、摘要精确匹配；不得存在 `state=unknown` 的来源声明。
- 每条声明填写非空作者、权利人、明确的 `rights_basis`、商业/Amazon 使用范围、仍有效的 `term`，并把 `territory` 写为 runtime 可识别的 `US / USA / United States / United States of America / worldwide / global` 之一；同时至少引用一份任务内 `raw/copyright-provenance/` 结构化证明。
- 每份证明绑定同一任务、资产、SHA-256、作者、权利人和权利基础，并明确 `commercial_use_allowed=true`、`amazon_use_allowed=true`、`territory_includes_us=true`、`term_valid=true`。普通 discovery evidence ID 不能替代这类证明。

资料不足时如实冻结为 `unknown` 并走补证动作；不得为取得 `very_low/proceed` 而补写无法验证的声明。

## 4. 初始化 legacy 发现任务

`init-task` 只初始化已经由 `collect-product` 生成的任务目录：

```bash
<IPR_CLI> init-task --task-dir <task-dir>
<IPR_CLI> transition-task --task-dir <task-dir> --to planning_queries --reason "开始美国 IPR 查询规划"
<IPR_CLI> plan-queries --task-dir <task-dir>
<IPR_CLI> validate-query-plan --task-dir <task-dir>
<IPR_CLI> init-evidence --task-dir <task-dir> --query-plan-digest <plan-digest>
<IPR_CLI> transition-task --task-dir <task-dir> --to collecting_evidence --reason "执行已批准的发现计划" --basis-digest <plan-digest>
```

旧查询计划可以继续使用七条发现链，其中 `figurative_trade_dress` 是图形商标与商业外观的共享召回入口。v2 正式审阅必须拆为八模块：

1. `appearance_design`
2. `utility_patent`
3. `pending_patent`
4. `word_mark`
5. `figurative_mark`
6. `trade_dress`
7. `copyright_creative_ip`
8. `enforcement_public_signals`

## 5. 云端知识产权发现与公开网页检索

先准备、执行并导入云端知识产权计划：

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

`prepare-us-screen` 返回 `status=ready` 后直接继续，不向用户展示积分上限或请求费用确认，不索要云端供应商 Key。计划、商品事实或图片变化时必须新建任务目录，不得修补冻结计划或原始证据。

云端导入完成后，才能准备并运行公开网页计划：

```bash
<IPR_CLI> prepare-serper-run --task-dir <task-dir>

<IPR_CLI> run-serper-plan \
  --config config.json \
  --task-dir <task-dir> \
  --plan <task-dir>/serper/plan.json \
  --approval <task-dir>/serper/approval.json
```

顺序不可调换。本地主图的受控 HTTPS 地址由 `us-screen` 生成，`prepare-serper-run` 必须在其后读取绑定状态。提前运行会返回 `SERPER_IMAGE_TRANSPORT_NOT_READY`，不能把该缺口当成无结果。

执行要求：

- 复跑必须复用同一任务目录、计划、内部授权文件和稳定 request ID。
- 状态 `uncertain` 可能已经计费，必须停止当前付费链，不得换 ID 重提。
- Serper 单条 HTTP 5xx 且明确未消耗 credit 时，将该条记为 coverage gap，继续其他独立查询，不自动重试。
- 401/403/402/429 记录失败并停止后续公开网页提交；不阻断已完成的云端发现，但最终覆盖不能视为完整。
- 单条响应可用候选保留率不低于 90% 时可以保留 coverage，但必须保存原始响应、`items/total` 差异和 parser warnings；低于 90% 为 `partial`，零条可用为失败。
- Serper 每完成或明确失败一条查询，legacy CLI 都会从 evidence ledger 全量刷新候选工作区；即使计划中途停止，也必须以最新工作区为完整性核对入口。
- `SERPER_SKIPPED_NO_KEY` 时问用户一次；用户给 Key 就注入当前会话并立刻重跑，用户明确没有则继续云端结果并保留缺口。
- 图片任务慢时等待轮询，不要因数分钟等待重复提交。
- `no_result` 只表示成功、结构有效的零候选响应，不表示不存在权利。
- `raw/` 与供应商响应不可修改。规范化失败时复用原任务和 operation 恢复，不得改原始字节或换 ID 重提。

## 6. legacy 完整性门禁与证据冻结

发现链结束后进入 `verifying_candidates`：

```bash
<IPR_CLI> transition-task --task-dir <task-dir> --to verifying_candidates --reason "发现完成，开始来源条目完整性核对"
```

当前 legacy CLI 如要求 `apply-candidate-review` 才能冻结证据，必须读取 `<task-dir>/serper/candidate_review_workspace.json`，一次性覆盖工作区全部 provider item，并按旧契约提交。每条必须有 disposition、结构化理由、全部证据引用和 actor/session；不得只处理高分项或用分组隐藏来源条目：

```bash
<IPR_CLI> apply-candidate-review --task-dir <task-dir> --input <legacy-candidate-review.json>
<IPR_CLI> evaluate-coverage --task-dir <task-dir>
<IPR_CLI> evaluate-candidate-verification --task-dir <task-dir>
<IPR_CLI> freeze-evidence --task-dir <task-dir>
<IPR_CLI> evaluate-coverage --task-dir <task-dir>
<IPR_CLI> evaluate-candidate-verification --task-dir <task-dir>
```

这一步只为证明候选清单、来源条目和冻结账本完整，不是正式法律处置：

- legacy `material` 与 `needs_review` 在 v2 迁移时一律变成 `unresolved`、`risk_driver_eligible=false`。
- legacy `not_material` 可以保留，但 v2 仍校验证据和排除理由。
- legacy 候选数量、图搜分数和模块 `high/low` 不得写入 v2 Assessment。
- legacy gate 不通过时补齐来源条目或记录 coverage gap；不得用手工修改 ledger 的方式绕过。

新任务要通过 legacy freeze gate，兼容批次中的 `needs_review` 必须在 legacy 层先解决；迁移规则保留 `needs_review -> unresolved`，是为了兼容尚未冻结的历史任务和已有旧产物。

冻结后再次确认 digest 和覆盖结果。冻结证据发生任何变化都必须重新执行 v2 迁移和评估，旧 Assessment 立即失效。

## 7. v2 候选迁移、聚类与校验

运行迁移：

```bash
<IPR_V2_RUNTIME> migrate-candidates --task-dir <task-dir>
```

迁移固定生成 `<task-dir>/v2/candidate-review-workspace.json`、`<task-dir>/v2/legacy-report-metadata.json` 与 `<task-dir>/v2/legacy-discovery-report.html`。当完整 legacy 冻结链的 `02_product_facts.json`、`04_query_plan.json`、`05_evidence_ledger.json` 与 `checkpoints/coverage.json` 齐备时，还会生成正式发布必需的 `<task-dir>/v2/source-manifest.json`，以 SHA-256 和字节数封存当前商品、查询、ledger、coverage 及其引用的任务内图片、provider/raw 证据与核验文件。引用文件缺失或越界时迁移失败，不能手工删减来源清单；runtime 没有独立的 source seal 命令。Agent 必须以迁移工作区为唯一候选入口，逐条处理全部候选并补齐：

- `record_kind`：`right_record / application / enforcement_event / marketplace_page / creative_source / comparison_material / non_right_page`
- `legal_materiality`：`risk_bearing / provenance_lead / comparison_only / mitigating / not_material / unresolved`
- `evidence_role`：`risk_driver / provenance / context / mitigating`
- `authority_tier`：`official / authoritative / primary / commercial / unknown`
- `target_jurisdiction`、`source_jurisdiction`、`right_jurisdiction`
- `evidence_cluster_id`、`duplicate_of`、`independence_group`
- `risk_driver_eligible`

同图、同商品、同权利或转载页必须聚类。拆分 legacy `figurative_trade_dress` 时，可分别进入 `figurative_mark` 与 `trade_dress`，但必须共享证据簇，不能变成两项独立权利。

迁移生成的每条 legacy 候选都带 `legacy_reassessed=false`：

- `material/needs_review` 在复评前必须保持 `legal_materiality=unresolved`；`not_material` 在复评前必须保持 `not_material`。
- 审阅者核对原始证据并完成 v2 重新分类后，必须显式改为 `legacy_reassessed=true`；这个字段表示“已复评”，不是沿用旧标签。
- 需要把一个 `figurative_trade_dress` 来源拆成两个正式模块时，保留原候选，并让派生候选以 `duplicate_of` 直接指向原候选，使用相同 `evidence_cluster_id` 与 `independence_group`。不得删除原候选或把派生项伪装成独立证据。

只有 `legal_materiality=risk_bearing`、证据可追溯且模块专属测试可以完成时，`risk_driver_eligible` 才能为 `true`。商城页面通常只能是 `provenance_lead` 或 `comparison_only`。

将完整处置写入 `<task-dir>/v2/candidate-review.json`，然后校验：

```bash
<IPR_V2_RUNTIME> validate-candidates \
  --input <task-dir>/v2/candidate-review.json
```

任一 `unresolved`、缺少来源引用、聚类断链、重复引用循环或无资格的风险驱动标记都会阻断正式 Assessment。不得只审阅高分候选或用分组隐藏 provider item。

## 8. 受控核验事件录入（按需）

`record-verification` 不会访问官方站点、判断外部文件真伪或替代律师核验。它只把用户、律师、后端或其他授权流程已经完成的核验结果，按不可变事件受控登记到当前冻结 evidence ledger。没有真实核验材料时跳过本节，保留未知事实或补证门禁，不得编造事件。

录入前必须满足：

- `<task-dir>/05_evidence_ledger.json` 已冻结，且 `<task-dir>/checkpoints/coverage.json` 完整并绑定同一 ledger；
- 已成功运行 `migrate-candidates`，`<task-dir>/v2/source-manifest.json` 存在并仍与当前来源图一致；
- `candidate_id` 是冻结 ledger 中已经存在的原始候选；
- 输入中适用的证据、文件路径、摘要、任务 ID、候选身份和 evidence revision 均来自当前任务，不能引用任务外或旧 revision 的材料；
- 原始 ledger、coverage checkpoint 和已有 normalized 事件不得手工修改。

官方记录、状态、授权或执法事件使用：

```bash
<IPR_V2_RUNTIME> record-verification \
  --kind official \
  --task-dir <task-dir> \
  --input <official-verification.json>
```

输入字段按 `references/contracts/official-verification.v2.schema.json`：必须绑定当前 `task_id`、冻结 `candidate_id`、美国 `right_identity`、ledger 中已有的 `evidence_refs`、来源定位、核验主体与时间。`enforcement_public_signals` 还必须提交 `enforcement_identity`，绑定投诉人、案件/投诉号、程序状态、当前商品 digest 和底层风险候选。runtime 会生成或校验事件 digest，并把通过的事件写入 `<task-dir>/normalized/official-verifications/<verification_id>.json`。

版权权属、授权和使用范围核验使用：

```bash
<IPR_V2_RUNTIME> record-verification \
  --kind copyright \
  --task-dir <task-dir> \
  --input <copyright-provenance-verification.json>
```

输入字段按 `references/contracts/copyright-provenance-verification.schema.json`：必须绑定冻结候选的 `candidate_id`、`candidate_key` 和当前 `evidence_revision`。`asset_ref` 指向任务内已有的 `raw/` 文件，`proof_refs[].path` 指向任务内已有的 `raw/copyright-provenance/` 文件；文件与输入中的 SHA-256 必须一致。事件还要明确作者、权利人、权利基础、许可范围、地区、期限、商业使用与 Amazon 使用状态。该命令不复制或收集证明文件；通过后只登记为 `<task-dir>/normalized/copyright-provenance-verifications/<verification_id>.json`。候选级核验事件不能替代 `very_low/proceed` 所需的逐商品图片 `provenance_declarations` 与结构化证明。

成功录入会原子更新 evidence ledger 的 revision/digest，重新绑定 discovery coverage checkpoint，并以新 revision 重封 source manifest；相同 ID 与相同内容可返回 `already_registered`，不同内容复用同一 ID 会失败。命令返回的 `assessment_rebuild_required=true` 是强制信号：

1. 从 `migrate-candidates` 重新生成工作区，全量复评并在对应原候选的 `verification_refs` 中纳入所有冻结核验事件。
2. 重新执行 `validate-candidates`、`prepare-assessment`、必要二审/裁决、`rules evaluate --dry-run`、`finalize-assessment`、`render-report` 和 `validate-release`。旧 review/context digest、Assessment 或报告不得复用。

## 9. 八模块 Assessment

先从已经通过校验的候选处置准备 Assessment：

```bash
<IPR_V2_RUNTIME> prepare-assessment \
  --task-dir <task-dir> \
  --candidate-review <task-dir>/v2/candidate-review.json
```

命令固定生成 `<task-dir>/v2/assessment-input.json`。Agent 必须严格按 `risk-evaluation-input.v2.schema.json` 填写，不能增加 Schema 不接受的自由字段：

- `candidates[].factors` 保存模块专属法律测试、关键相似/差异、权利状态、授权与缓释事实；证据引用保存在候选的 `evidence_refs`、`verification_refs`。
- `modules[]` 必须覆盖八个模块，并填写 `assessability`、`confidence`、`candidate_ids`。`provenance_complete=true` 表示该模块所需的来源、权利范围和授权链已完成核验，是无风险驱动时评为 `very_low` 的完成门禁；版权模块还必须按版权来源链的专门含义填写。
- 影响评级的未决事实写入 `unresolved_material_facts`；非空时该模块为 `not_assessable` 并阻断正式结论，不能用自由文本 reasoning 隐藏。
- `coverage` 保存完整性、覆盖置信度和逐模块 gaps。
- `review.fact_conflicts` 保存二审事实冲突；无冲突时使用空数组。
- `reasoning` 只解释已经结构化的事实，不参与评级，也不能替代候选 factors。

四维结果由 runtime 计算，审阅者不得用自由文本标签绕过规则：

- `discovery_status`：`no_lead / leads_found / review_required / blocked`
- `legal_risk`：`not_assessable / very_low / low / medium / high / critical`
- `risk_confidence`：`low / medium / high`
- `operational_action`：`proceed / proceed_with_conditions / hold_for_evidence / escalate_legal`

`coverage_confidence=low/medium/high` 独立表示八模块发现覆盖。缺图片、来源失败、状态/权属/授权未知只产生 confidence cap、formal block 或补证动作，不得自动抬高法律风险。

正式计算前先 dry-run：

```bash
<IPR_V2_RUNTIME> rules evaluate \
  --input <task-dir>/v2/assessment-input.json \
  --dry-run
```

检查输出中的规则版本、风险驱动资格、模块测试、置信度限制、阻断原因和聚合过程。不得为了得到期望等级而改写冻结证据或跳过失败规则。

## 10. 二审与人工冲突解决

runtime 要求二审时，每轮输入必须符合 `assessment-review-input.v2.schema.json`，使用不同 reviewer ID 和 session，分别提交 `fact_observations`、证据引用和模块结论。没有真实运行时隔离证明时不得声称 `runtime_enforced`；第二审确实未读取第一审时才可填写 `prior_review_read=false`。

每轮提交必须定稿为 `assessment-review.v2.schema.json`：包含 `review_id` 和不可变 `digest`。其中 `context_digest` 是待合并 assessment input 的规范化 SHA-256，`evidence_digest` 是其 `candidates` 数组的规范化 SHA-256；`digest` 是删除自身 `digest` 字段后对完整 review 做键排序规范化得到的 SHA-256。两审都必须覆盖每个 `risk_bearing` 候选的全部必需评级 factors；模块标签本身不参与合并。单边观察不得改写评级事实，只有两审对同一路径给出相同值且均有支持证据时才会合并。

使用 runtime 合并并重新评级：

```bash
<IPR_V2_RUNTIME> merge-reviews \
  --assessment-input <task-dir>/v2/assessment-input.json \
  --first-review <first-review.json> \
  --second-review <second-review.json> \
  --output <task-dir>/v2/assessment-input.merged.json
```

若存在冲突，先按 `human-resolution.v2.schema.json` 生成带 `resolution_id` 和不可变 `digest` 的裁决文件，再加 `--resolution <resolution.json>` 重跑同一命令。runtime 会把两份审阅和裁决复制到 `<task-dir>/normalized/`，在 Assessment 中记录引用；review 自行声明 `resolved_by_*` 无效。后续 dry-run 与定稿必须使用合并后的 input。

二审处理顺序固定为：

1. 合并双方一致的候选身份、证据、权利范围、相似/差异和授权事实。
2. 对事实冲突保留双方证据与冲突标记，不直接选择更高风险标签。
3. 将合并后的结构化事实重新交给 `rules evaluate --dry-run` 计算。
4. 风险驱动事实仍有冲突时，相关模块与总体设为 `discovery_status=blocked`、`legal_risk=not_assessable`、`risk_confidence=low`、`human_resolution_required=true`、`operational_action=escalate_legal`，再由人工基于证据裁决。

禁止沿用 legacy 的“风险取高、置信度取低”合并。人工裁决必须符合 `human-resolution.v2.schema.json`，绑定 context/evidence digest 和具体 `fact_path`；也不能绕过 `high/critical` 所需的权威证据、合格风险驱动候选和完整模块测试。

## 11. v2 定稿、报告与 release gate

完成 dry-run 与必要二审后执行。没有二审时 `<final-assessment-input>` 是 `assessment-input.json`；运行过 `merge-reviews` 时必须使用它输出的 `assessment-input.merged.json`：

```bash
<IPR_V2_RUNTIME> finalize-assessment \
  --task-dir <task-dir> \
  --input <final-assessment-input>

<IPR_V2_RUNTIME> render-report --task-dir <task-dir>
<IPR_V2_RUNTIME> validate-release --task-dir <task-dir>
```

固定产物：

- `<task-dir>/v2/assessment.json`
- `<task-dir>/v2/assessment-input.snapshot.json`
- `<task-dir>/v2/coverage.json`
- `<task-dir>/v2/decision-trace.json`
- `<task-dir>/v2/source-manifest.json`
- 按需录入核验时：`<task-dir>/normalized/official-verifications/*.json` 与 `<task-dir>/normalized/copyright-provenance-verifications/*.json`
- 必要二审时：`<task-dir>/normalized/reviews/*.json` 与 `<task-dir>/normalized/resolutions/*.json`
- `<task-dir>/report-v2/report_data.json`
- `<task-dir>/report-v2/ipr-risk-screening-report.html`
- `<task-dir>/report-v2/ipr-risk-screening-report.md`
- `<task-dir>/report-v2/manifest.json`

`report_data.json` 是 HTML 与 Markdown 的唯一视图模型。报告必须分开展示发现状态、法律风险、风险置信度、覆盖置信度和运营动作，并同时显示原始结果数、去重证据组数、风险驱动候选和证据引用。

正式发布不仅绑定最终 Assessment 和报告，还会通过 `v2/source-manifest.json` 逐文件校验当前冻结的 `02_product_facts.json`、`04_query_plan.json`、`05_evidence_ledger.json`、`checkpoints/coverage.json` 及其引用来源，再交叉校验 Assessment coverage、全量候选及其 ledger lineage、全部冻结核验事件与候选 `verification_refs`，以及每条原始 legacy 候选的 `legacy_disposition/legacy_reassessed`。任何来源文件、digest、evidence revision、核验事件、候选集合或复评状态变化，都会使旧 Assessment/报告失效并要求重建。

只有 v2 Assessment 完成、所有门禁闭合且 `validate-release` 通过时，才能交付正式报告。否则：

- `legal_risk` 强制为 `not_assessable`，`risk_confidence` 强制为 `low`；
- 首页显示“评估尚未完成”，不得显示任何正式风险徽章；
- 可以显示 `discovery_status`、证据数量和缺口；
- `operational_action` 应为 `hold_for_evidence` 或按阻断原因升级；
- legacy `report/`、`report-draft/` 不得冒充 v2 报告。
- 已有旧报告只能作为历史证据附件，并明确标记 `legacy discovery report`；不得重写其旧风险字段或把它重新解释为 v2 法律评级。

`high` 必须至少关联一个权威来源、一个 `risk_driver_eligible=true` 的独立候选和完整模块测试。`critical` 还必须有针对同一商品或风险对象的现实执法事件。任一条件缺失都必须 release 失败。

## 12. 最终回复

最终回复应包含：

- 任务目录和 `report-v2` 报告路径；
- 发现状态、法律风险、风险置信度、覆盖置信度和运营动作；
- 八模块结论及实际驱动总体风险的模块；
- 原始结果数、去重证据组数、主要风险驱动证据与未闭合项；
- `ruleset_version` 与法律边界。

不得把 `low/very_low` 写成“可以放心销售”，不得把 `no_result` 写成不存在权利，也不得把 `hold_for_evidence` 偷换成高法律风险。
