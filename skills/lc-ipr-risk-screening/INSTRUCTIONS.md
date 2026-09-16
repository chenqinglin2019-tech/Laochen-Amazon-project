# LC IPR Risk Screening 执行指令（US）

本 Skill 一次处理一个美国商品。正式结果必须完成云端核心发现、候选全批次处置、七模块审阅和 release gate；Serper 公开网页计划是可选增强。它是风险筛查，不是官方法律状态确认或法律意见。

## 1. CLI 与凭据

后文将当前平台程序记为 `<IPR_CLI>`：

| 平台 | CLI |
|---|---|
| Windows x64 | `tools/bin/lc-ipr-risk-screening-windows-amd64.exe` |
| Linux x64 | `tools/bin/lc-ipr-risk-screening-linux-amd64` |
| macOS Intel | `tools/bin/lc-ipr-risk-screening-darwin-amd64` |
| macOS Apple Silicon | `tools/bin/lc-ipr-risk-screening-darwin-arm64` |

macOS 首次运行前静默执行：

```bash
chmod +x tools/bin/lc-ipr-risk-screening-darwin-*
xattr -dr com.apple.quarantine tools/bin/ 2>/dev/null || true
```

第一条业务命令：

```bash
<IPR_CLI> auth-check --config config.json
```

只有 `reason_code=AUTH_PASSED` 才能继续。`LAOCHEN_BACKEND_TOKEN` 优先于 `config.json.backend_token`。公开网页检索先读环境变量 `SERPER_API_KEY`：有则本机直连官方接口，费用由用户自己的 Serper 账户承担。对话、本轮会话附件或用户上传文件里出现 Key / 疑似 Serper Key 时，立刻注入当前会话环境变量（PowerShell 用 `$env:SERPER_API_KEY='...'`，然后在**同一会话**里跑 CLI）并直接用，不要再问、不要要求改系统变量、不要要求重启 Agent。环境里没有、用户也没给，再问一次。禁止写入 `config.json`、命令参数、任务目录、报告；禁止回显。用户明确没有则跳过公开网页检索，商品详情和云端知识产权发现仍只用老陈 Token 并继续走完。

## 2. 输入与任务目录

只接受 `marketplace=US`、美国 ASIN 或 `amazon.com` 链接。非 US 在任何远程调用或图片上传前停止。

认证通过后，首轮提示必须同时暴露图片输入能力，可直接使用：

> 请发送一个美国 Amazon 商品的 ASIN 或 `amazon.com` 商品链接；也可以同时上传商品主图和细节图。一次仅处理一个商品。

ASIN/链接路径会通过云端商品详情优先取得可信 Amazon 主图，因此用户上传图片是可选补充，不得误报为必填。若用户不提供 ASIN/链接、选择提交完整人工商品资料，则必须同时提供标题、至少一条五点、长描述和至少一张清晰主图；缺失时只追问缺失项，不启动远程筛查。

为本轮确定一个尚不存在的唯一目录 `ipr_screening_YYYYMMDD_HHMMSS/`，放在技能包外面，不要提前创建空目录。禁止把 `--output-dir` 或 `--task-dir` 设为 `.`、技能包根目录或 `tools/`。任务产物不得写入 `SKILL.md` 所在目录。`collect-product --output-dir` 会以临时目录原子生成正式任务目录；后续命令始终复用它。按 `references/input-routing.md` 依次执行：

```bash
<IPR_CLI> inspect-input <输入参数>
<IPR_CLI> collect-product <输入参数> --task-id <task-id> --output-dir <task-dir>
<IPR_CLI> validate-product --input <task-dir>/02_product_facts.json
```

两条输入路由都先做检索标识判断：实际打开冻结商品图，结合标题、品牌栏、包装和用户资料判断哪些文字是在标识商品来源；不要把品牌栏占位、品类描述、内部型号/SKU 原样当字标。完整值为 `Generic`（忽略大小写和首尾空格）固定排除，不作为品牌或字标查询；其他词不套用固定排除表。按 `references/input-routing.md` 生成 `<task-dir>/input-metadata/search-identity.json`，执行：

```bash
<IPR_CLI> record-search-identity --task-dir <task-dir> --input <task-dir>/input-metadata/search-identity.json
```

此命令保留原始字段，只绑定 Agent 的检索判断并更新事实摘要。必须在 ASIN 核对和 `init-task` **之前**运行，不得手工改事实、摘要或已有任务。明确没有字标则记录空标识及图文依据，不为凑查询而造一个品牌；其它筛查继续。图片看不清或身份冲突时先核实，不把未知冒充没有。

`inspect-input` 在 ASIN 路径返回 `seller_lookup.provider=laochen_backend` 与 `action=product_detail`。`collect-product` 使用 `config.json` + `LAOCHEN_BACKEND_TOKEN` 自动调用云端商品详情并冻结事实；不要在本机安装、配置或调用任何上游数据工具。**仅 ASIN 路径**再按契约把语义核对写入 `<task-dir>/input-metadata/product-corroboration.json`，绑定上一步输出的新摘要，然后完成：

```bash
<IPR_CLI> validate-product-corroboration --task-dir <task-dir>
```

人工资料完整时禁止调用 SellerSprite。商品字段、图片角色、来源、版权/许可链和 SHA-256 必须按契约冻结；不能用一句标题和一张图代替完整采集。

## 3. 初始化正式任务

`init-task` 只初始化上一步已经由 `collect-product` 生成、且包含冻结商品事实的任务目录；它不负责另建项目外壳或第二个任务目录。

```bash
<IPR_CLI> init-task --task-dir <task-dir>
<IPR_CLI> transition-task --task-dir <task-dir> --to planning_queries --reason "开始美国 IPR 查询规划"
<IPR_CLI> plan-queries --task-dir <task-dir>
<IPR_CLI> validate-query-plan --task-dir <task-dir>
<IPR_CLI> init-evidence --task-dir <task-dir> --query-plan-digest <plan-digest>
<IPR_CLI> transition-task --task-dir <task-dir> --to collecting_evidence --reason "执行已批准的发现计划" --basis-digest <plan-digest>
```

查询计划固定覆盖七个模块：外观设计、实用专利、申请中专利、文字商标、图形商标/商业外观、版权/创意资产、公开维权信号。

## 4. 云端知识产权计划与内部自动授权

先准备云端知识产权计划：

```bash
<IPR_CLI> prepare-us-screen \
  --product-facts <task-dir>/02_product_facts.json \
  --task-dir <task-dir>
```

`prepare-us-screen` 会同时生成冻结计划与内部执行授权文件。这些文件只用于稳定请求 ID、防止重复提交、断点恢复和调用留痕。

Agent 应在 `prepare-us-screen` 返回 `status=ready` 后直接继续：

- 不向用户展示最多调用次数或积分上限以请求确认；
- 不向用户发起任何执行或费用确认；
- 不索要云端供应商 Key。对话或本轮附件里出现 `SERPER_API_KEY` / 疑似 Key 时，只注入当前会话环境变量后直接用，不得写入文件或命令参数，不得回显，不得要求重启 Agent；
- 计划、商品事实或图片发生变化时，必须新建任务目录；不得修补冻结计划或原始证据。

## 5. 执行云端知识产权发现与公开网页检索

先执行云端知识产权发现计划并导入正式证据：

```bash
<IPR_CLI> us-screen \
  --config config.json \
  --product-facts <task-dir>/02_product_facts.json \
  --task-dir <task-dir> \
  --plan <task-dir>/us-screen/plan.json \
  --approval <task-dir>/us-screen/approval.json

<IPR_CLI> import-us-screen-evidence --task-dir <task-dir>
```

`us-screen` 完成且证据导入后，再准备并执行公开网页正式计划：

```bash
<IPR_CLI> prepare-serper-run --task-dir <task-dir>

<IPR_CLI> run-serper-plan \
  --config config.json \
  --task-dir <task-dir> \
  --plan <task-dir>/serper/plan.json \
  --approval <task-dir>/serper/approval.json
```

顺序不可调换：本地主图的受控 HTTPS 地址由 `us-screen` 生成，`prepare-serper-run` 必须在其后读取已绑定的上传状态，才能把图形商标/商业外观和版权两条反向图搜写入冻结执行计划。提前执行会返回 `SERPER_IMAGE_TRANSPORT_NOT_READY`，不会提交公开网页请求，也不能把缺口当成无结果继续。

执行规则：

- 复跑必须复用同一任务目录、计划和内部授权文件。
- 公开网页检索先读 `SERPER_API_KEY`；有则本机执行。没有则问一次。用户把 Key 发在对话里时，注入当前会话环境变量并立刻重跑 `run-serper-plan`，不要让用户改系统环境变量或重启 Agent。用户明确不提供时 `run-serper-plan` 返回 `SERPER_SKIPPED_NO_KEY`，跳过公开网页，云端知识产权发现继续。
- 云端知识产权发现使用稳定请求 ID 和后端 operation；状态不确定时停止，不得换 ID 重复付费。
- 云端知识产权发现的计费由云端倍率和流水统一处理；公开网页检索费用由用户自己的 Serper 账户承担。Agent 不向用户发起积分计划确认。
- Serper 单条查询明确返回 HTTP 5xx 且未消耗 credit 时，保留该可选查询的失败记录，并继续执行计划中其余独立查询；不得自动重试失败项。401/403/402/429 记为该条失败后停止后续公开网页提交，不自动重试，也不阻断云端核心结论；最终 Serper 摘要为 `partial`。
- Serper 响应中孤立的畸形候选由 CLI 逐条拒绝。当可用候选保留率不低于 90% 时，该查询仍完成 coverage，但必须保留原始响应、`items/total` 差异和 parser warnings；低于 90% 仍为 `partial`，零条可用仍为失败。不得修改原始证据或重复付费提交。
- Serper 每完成或明确失败一条查询都会从 evidence ledger 全量刷新候选工作区；即使计划中途停止，也必须以刷新后的工作区为审阅入口。
- `run-serper-plan` 返回 `ready`、可审计的 `partial` 或 `SERPER_SKIPPED_NO_KEY` 时进入 `verifying_candidates`。`SERPER_SKIPPED_NO_KEY` 时问用户一次；用户给出 Key 就注入当前会话并立刻重跑，不要停下来让用户去设系统变量。用户明确没有则继续云端结果审阅；Serper 行保留为未执行的可选查询，不进入 release gap。返回 `blocked` 时保留当前任务状态并按 `reason_code` 恢复。
- 图片任务慢时等待轮询；不要把数分钟等待当失败并重复提交。
- `no_result`、解析失败、配额错误、访问受限必须严格区分。`no_result` 不等于安全。
- `raw/` 和已经落盘的供应商响应是不可变审计证据。候选规范化失败时只能复用同一任务、计划和 operation 让 CLI 恢复；不得手工改写、复制替换或重新编码原始响应，也不得换请求 ID 重复提交。

## 6. 候选全批次处置

先读取 `references/risk-judgment.md`。对重点外观候选尝试取得并查看完整图纸，用 `record-supplemental-evidence` 登记补充材料，再读取最新候选工作区并提交全批次处置。缺少部分视图可形成有依据的暂定等级和低置信度；无法基本比较时保持 needs_review。

云端核心发现执行完成，且 Serper 已完成、可审计地结束或因无 Key 跳过后，先锁定当前全量候选清单并进入核验状态：

```bash
<IPR_CLI> transition-task --task-dir <task-dir> --to verifying_candidates --reason "发现完成，开始候选全批次处置"
```

再读取 `<task-dir>/serper/candidate_review_workspace.json`。Agent 必须逐条处理工作区中的**全部候选**，生成符合 `candidate-review-batch.schema.json` 的单个批次文件，然后执行：

```bash
<IPR_CLI> apply-candidate-review --task-dir <task-dir> --input <candidate-review.json>
```

不得分批遗漏、只处理高分项或用分组隐藏来源条目。每条候选必须使用 `material`、`not_material` 或 `needs_review` 的结构化结论，并带理由、全部证据引用和 actor/session。检索分数只用于排序，不是法律风险或整体视觉相似结论。

候选审阅 JSON 必须以 UTF-8 写入。Windows 下提交前先确认 `rationale` 可读且未出现连续 `????` 或替换字符；CLI 会将此类编码损坏视为整个批次无效，并保证一条候选都不写入证据账本。发生该错误时，从未修改的候选工作区重新生成 UTF-8 批次后再提交，不要在坏批次落盘后另建修正版；当前写入工具不能可靠保存中文时，直接使用可读英文理由，不得用问号占位。

视觉候选按以下规则处置：

- 不同品牌、不同品类、不同法域、重复记录等可先依据结构化字段快速排除；每条仍需单独留下排除码。
- 先用图像查看能力打开 `<task-dir>/input-images/` 下的冻结目标图，再打开候选摘要 `image_ref` 指向的本地图片。外观图位于 `<task-dir>/us-screen/evidence-images/<专利号>.img`，图形商标以 `tm-` 开头，版权图片以 `copyright-` 开头；本地缓存缺失时再从对应 `us-screen/raw/*.json` 的 `imageUrl` 获取。只读原始响应，不得修改 `raw/`。
- 外观设计、图形商标/商业外观、版权图片以及 Serper Images/Lens 候选，只要准备标为 `material`，必须实际打开冻结目标图和候选图并比较整体轮廓、核心结构、比例、装饰元素和使用方式。在 `rationale` 中明确写出共同点、关键差异和整体视觉印象。
- 同一专利或完全相同图片可以归组看代表图，但每个来源条目仍需独立处置；任何用于抬高风险的候选都必须有实际图像复核。
- 候选图无法访问、内容不可辨认或无法与目标图并排核对时使用 `needs_review`，不得仅凭 Trohub/Serper 相似度、标题或搜索排名判为视觉实质候选。
- 文字商标只有在文字近似且 `tmClass` 商品/服务与目标商品存在实际重叠时才可标为 `material`，必须同时使用 `word_mark_similarity` 与 `goods_services_overlap`。同名但类别无关时使用 `different_goods_services` 排除，不能仅凭完全同名判高风险。
- 同时回看 `02_product_facts.json.search_identity` 的图文判断：候选命中了原品牌栏的占位描述，不代表命中了商品真实标识。明确无字标的 `not_applicable` 行是未发起查询，不是 `no_result`，七模块审阅仍要说明实际可见文字与本轮范围，不能自动得出无商标风险。
- 已按检索标识发起的文字商标查询会保留全部有效返回候选，包括近似拼写和明显噪声；由 Agent 在全批次中逐条判定相关性及类别重叠，不把“进入候选表”当成相关或高风险。

`needs_review` 未解决或完整批次不通过时不得进入七模块审阅。

## 7. 候选门禁、冻结与七模块审阅

新任务按 v2 逐模块填写风险理由和 `confidence_reason`。每个 material 候选必须有 finding，视觉 finding 按 `references/risk-judgment.md` 填写完整 comparison。权利有效或未知不单独抬高风险、也不单独阻断暂定筛查结论；版权来源约束、置信度限制和证据完整性门禁仍生效。v2 不启用额外加一级的 compound_escalation。

```bash
<IPR_CLI> evaluate-coverage --task-dir <task-dir>
<IPR_CLI> evaluate-candidate-verification --task-dir <task-dir>
```

这里的 candidate verification 只验证候选清单完整、来源条目完整且每个候选已有明确处置，不执行任何官方登记或法律状态浏览器核验。任一 gate 不通过时，按返回的 gap 补齐或交付不完整结果；两者通过后：

```bash
<IPR_CLI> freeze-evidence --task-dir <task-dir>
<IPR_CLI> evaluate-coverage --task-dir <task-dir>
<IPR_CLI> evaluate-candidate-verification --task-dir <task-dir>
<IPR_CLI> prepare-assessment --task-dir <task-dir>
```

CLI 先生成与当前 readiness、evidence digest 绑定的审阅工作区。审阅者只能在该工作区上填写七个模块。外观设计、图形商标/商业外观、版权与创意资产中的候选 finding 必须填写非空的 `similarities` 和 `differences`；升为高/极高风险时必须绑定至少一条已经实际看图比较的 `material` 候选。通用结构相似而关键造型明显不同，不足以单独支撑高风险：

未提供 Serper Key 时也必须填写全部七个模块，并依据已冻结的云端核心候选和商品事实给出筛查等级。实用专利、申请中专利或公开网页维权信号没有增强候选时，可写“本轮未发现明确风险信号”并使用与证据范围相称的低置信度；不得写成“没有专利/商标/版权”，也不得仅因 Serper 未启用把全部模块改成 `not_assessable`。有 Serper 结果时，将其与云端候选一起审阅，新增实质候选可以抬高风险。

```bash
<IPR_CLI> prepare-assessment-review --task-dir <task-dir> --round first --reviewer-id <reviewer-id> --session-id <session-id>
```

填写生成的工作区后提交：

```bash
<IPR_CLI> record-review --task-dir <task-dir> --input <first-review.json>
```

完成第一次七模块审阅并通过内容门禁后，直接运行 `finalize-assessment`。当前产品流程不启动 `--round second`，不等待隔离证明，不因风险等级、单一视图、版权来源不完整或可选数据源失败向用户索要二审/人工裁决。证据限制继续由确定性 risk floor、confidence cap 和 formal block 保守表达；一审必须自己完成看图、类别重叠、共同点/差异点和证据绑定，不得通过取消二审降低审阅质量。二审命令仅为历史任务兼容保留，新任务不调用。

## 8. 报告与 release gate

```bash
<IPR_CLI> finalize-assessment --task-dir <task-dir>
<IPR_CLI> render-report --task-dir <task-dir>
<IPR_CLI> validate-release --task-dir <task-dir>
```

只有 `formal_conclusion_allowed=true`、风险筛查报告已渲染且 `validate-release` 返回通过，任务才能进入 `completed`。Serper 未配置或可选行失败本身不阻断该条件；云端核心行失败、候选遗漏、`needs_review` 或审阅门禁失败仍只能交付 draft/incomplete。这里的正式仅表示本轮筛查流程完整，不表示官方法律状态确认或律师法律意见。

最终回复应包含：任务目录、报告路径、七模块结论、主要证据与未闭合项、法律边界。不得把“低风险”写成“可以放心销售”，不得把无结果写成无权利。
