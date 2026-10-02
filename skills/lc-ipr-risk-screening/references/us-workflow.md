# 美国风险筛查工作流

本工作流只接受 US。公开网页检索与云端知识产权服务是互补的候选发现层。云端知识产权发现使用 `LAOCHEN_BACKEND_TOKEN`。公开网页检索先读 `SERPER_API_KEY`：有则本机执行；没有就问一次。用户把 Key 发在对话里时注入当前会话环境变量并立刻继续，不要要求改系统变量或重启 Agent。用户明确没有则跳过公开网页、云端核心继续。不向用户逐次确认调用次数或积分。

## 七模块与能力分工

| 模块 | 发现能力 | 报告处理 |
|---|---|---|
| 外观设计 | 公开专利检索、云端外观图搜与反向图搜 | 对相似外观候选比较共同点、差异和商品关联性 |
| 实用专利 | 公开专利与网页检索 | 提取与产品结构、功能、技术卖点相关的候选和风险信号 |
| 申请中专利 | 公开专利与网页检索 | 单列申请中候选，提示不确定性和后续监控需求 |
| 文字商标 | 公开网页检索与云端文字标识检索 | 只使用 Agent 看图文后记录的检索标识；占位品牌、内部型号/SKU 不自动送检，明确无字标则不发这类请求，其它筛查继续 |
| 图形商标/商业外观 | 公开图片检索、云端图形标识检索 | 比较图形、包装和整体视觉识别特征 |
| 版权/创意资产 | 公开网页/图片检索、云端版权线索 | 对图片、文案、包装素材及来源链做风险筛查 |
| 公开维权信号 | 公开网页检索、云端公开案件与维权信号 | 识别公开争议和维权迹象，不把案件线索当成权利状态确认 |

发现结果只产生候选。本 Skill 不执行官方登记或法律状态浏览器核验；相关法律状态需要用户另行通过律师或官方渠道核实。

## 双计划

两份计划按依赖顺序生成，不得同时提前冻结。先准备并执行云端知识产权计划：

```bash
<IPR_CLI> prepare-us-screen \
  --product-facts <task-dir>/02_product_facts.json \
  --task-dir <task-dir>
```

命令会生成冻结计划与内部执行授权，用于稳定请求 ID、防重复提交、断点恢复和调用留痕。返回 `status=ready` 后直接继续，不向用户索要云端积分确认。云端知识产权发现不依赖 `SERPER_API_KEY`。

## 执行与证据导入

```bash
<IPR_CLI> us-screen \
  --config config.json \
  --product-facts <task-dir>/02_product_facts.json \
  --task-dir <task-dir> \
  --plan <task-dir>/us-screen/plan.json \
  --approval <task-dir>/us-screen/approval.json

<IPR_CLI> import-us-screen-evidence --task-dir <task-dir>

<IPR_CLI> prepare-serper-run --task-dir <task-dir>

<IPR_CLI> run-serper-plan \
  --config config.json \
  --task-dir <task-dir> \
  --plan <task-dir>/serper/plan.json \
  --approval <task-dir>/serper/approval.json
```

`import-us-screen-evidence` 和 `run-serper-plan` 把完成的 operation 写入同一 evidence ledger。人工本地图由 `us-screen` 上传一次；随后的 `prepare-serper-run` 从绑定的运行状态读取受控 HTTPS 地址，补齐图形商标/商业外观与版权两条反向图搜。云端知识产权服务的供应商 Key 不得进入用户环境、`config.json`、任务目录、命令参数、报告或聊天。公开网页检索只使用进程环境变量 `SERPER_API_KEY`。用户在对话中提供时，只注入当前会话后继续；不得写入 `config.json`、任务目录、命令参数、报告。

## 图片与远程边界

- Amazon HTTPS 主图可直接用于远程图搜。
- 本地图在 `us-screen` 内部计划冻结后上传到专属 IPR 后端；公开网页计划必须等该上传完成后再生成。
- 不得使用 `/dl/` 或第三方临时图床，不得把 base64 写入报告。
- 没有可用主图时，相关图搜必须记为 gap，不能用文字搜索冒充图片覆盖。

## 重试与失败语义

- 同一任务仅允许一个 `us-screen` 进程。CLI 从读取运行状态到完成落盘持有任务锁；`TASK_LOCKED` 时等待原执行，不得另开轮询、删除锁或对活跃进程执行 `recover-stale-lock`。Ctrl+C / SIGTERM 会取消请求（包括报告图片下载）、保留任务身份并释放锁，取消的 HTML 渲染不会返回成功。SIGKILL、断电或强制结束进程仍可能遗留锁；恢复命令只接受同机、已确认退出且达到最短时长的进程。异机、PID 被复用或身份无法核实时拒绝恢复，不得强删。恢复命令自身异常退出可能留下 `.lc-ipr-mutation.lock.recovery`，需人工核实原进程和恢复进程均已退出后处理。
- 独立 `render-us-screen-html` 从读取报告到图片下载、HTML 落盘全程持有同一任务锁；遇到 `TASK_LOCKED` 等待原任务结束后再运行。
- 默认轮询间隔为 10 秒，最短为 5 秒；等待中的工具会话不是超时，继续等待同一会话。查询进度也占账户请求额度，不得同时手工请求后端状态。
- 复跑必须复用任务目录、计划、内部授权和稳定 request ID。
- `GATEWAY_RATE_LIMITED` 表示响应明确来自账户网关限流，不是供应商配额结论。CLI 在当前超时预算内按响应头 `Retry-After` 或响应体 `retry_after` 等待；首次提交被明确拒绝时记录 `not_submitted`，已存在的任务身份和状态不会被清空。结束等待后仍未完成时，确认原进程退出，再复跑同一命令；不修改计划、不换 ID。
- `CLOUD_RATE_LIMITED` 表示收到了 429，但来源没有确认。状态查询可等待后继续查询同一任务；来源不明的提交 429 不自动重提，也不能据此认定上游额度耗尽。网络中断仍保留 `unknown`；已受理 operation 返回的 `UPSTREAM_RATE_LIMITED` 是上游拒绝，不会自动重新执行付费请求。
- 本地图上传也遵守网关 429 等待规则；来源不明的 429 或网络错误不自动重传。上传请求失败后本次命令停止，不再继续付费查询。
- 检查 CLI 和发现报告的 `operation_errors`，其中包含能力、原请求 ID 和安全错误码；运行状态的 `status` / `error_code` 保留最后确认的远程结果，本次网络或取消错误另存 `last_attempt_error_code`；只有收到新的后端状态才更新远程结果。`UPSTREAM_RATE_LIMITED` 不会被统一的 `US_SCREEN_PARTIAL` 覆盖；明确失败的子任务保留缺口，其余独立查询可以继续。已有失败状态恢复时仍使用原请求 ID，不承诺失败项会被上游重新执行。
- `import-us-screen-evidence` 会把明确失败的云端操作导入正式账本，保留原请求 ID、安全错误码和不可变状态快照；返回 `US_SCREEN_EVIDENCE_PARTIAL` 及 `failed_queries`。全失败批次也可留痕，失败不算覆盖完成；复跑导入不产生新远程请求或重复记录。补充反查失败不会抹掉已成功的主查询，`uncertain` 不转成明确失败。导入中断后可复跑同一命令：已完成记录通过身份校验后复用，保留并继续未完成项，不清空其他活动操作。
- 新版状态文件应继续使用新版 CLI；旧版严格 JSON 读取器可能拒绝新增错误字段，不能通过删字段或换请求 ID 绕过。

- `uncertain` 表示结果状态未知且可能已计费：停止当前付费链，不得换 request ID 重提。
- 明确 HTTP 5xx 且未消耗 credit 的 Serper 行记录为可选来源失败，继续其余独立查询，不自动重试失败项；它可以限制对应模块置信度，但不进入正式结论的必需 coverage gap。
- Serper 单条响应可用候选保留率不低于 90% 时，孤立畸形项记入 parser warnings 而不阻断 coverage；原始响应、`items/total` 差异和拒绝原因仍全部保留。低于 90% 为 `partial`，零条可用为失败。
- `run-serper-plan` 在 `ready`、可审计的 `partial` 或 `SERPER_SKIPPED_NO_KEY` 时进入候选处置；`SERPER_SKIPPED_NO_KEY` 时问一次，用户给出 Key 就注入当前会话并立刻重跑，用户明确没有则继续云端结果。Serper 行仍保留在冻结计划中，但属于可选增强，不进入必需 coverage gap。`blocked` 必须留在当前阶段恢复。
- 图片任务慢时等待轮询，不要因数分钟等待重复提交。
- `no_result` 必须来自成功且结构有效的零候选响应；认证、配额、超时、畸形 JSON 和解析失败都不是 `no_result`。
- 供应商原始响应与 `raw/` 证据不可由 Agent 修补。URL 和候选字段的可移植规范化由 CLI 完成；失败时复用原任务和稳定 operation 恢复，不改原始字节、不换 ID 重提。
- `no_result` 不等于不存在权利。

## 候选全批次处置

提交全批次处置前，按 `risk-judgment.md` 补充并登记重点候选材料。补充材料不计入发现查询覆盖；登记后读取最新候选工作区。

两条发现链结束后进入 `verifying_candidates`，读取 `serper/candidate_review_workspace.json`，一次性覆盖其中全部候选：

```bash
<IPR_CLI> apply-candidate-review --task-dir <task-dir> --input <candidate-review.json>
```

每个来源条目只能有一个处置。`material` 进入报告重点提示；`not_material` 必须带结构化排除依据；`needs_review` 会阻断最终评估。Trohub/Serper 相似度只用于候选排序。视觉候选拟进入 `material` 时，Agent 必须实际打开目标图与候选图，在理由中写清共同点、关键差异和整体视觉印象；图片不可读取时使用 `needs_review`，不得用搜索分数替代看图。

## 完成条件

1. 五条云端核心查询完成；Serper 可选计划已完成、可审计地结束或因无 Key 跳过；
2. 所有 provider item 已进入候选清单；
3. 候选全批次处置完整且没有 `needs_review`；
4. 按 `risk-judgment.md` 完成一次证据绑定的七模块审阅；
5. `finalize-assessment`、`render-report`、`validate-release` 全部通过。

云端核心条件不满足时输出 draft/incomplete 并说明缺口。没有 Serper Key 本身不阻断正式筛查报告；Agent 仍须给出七模块判断，但只能说“本轮未发现明确风险信号”，不能把未检出写成不存在权利。有 Serper 时，其候选进入同一账本和审阅并可改变风险。完整报告仍是风险筛查，不是官方法律状态确认或法律意见。
