# 美国风险筛查工作流

本工作流只接受 US。公开网页检索与云端知识产权服务是互补的候选发现层。云端知识产权发现使用 `LAOCHEN_BACKEND_TOKEN`。公开网页检索先读 `SERPER_API_KEY`：有则本机执行；没有就问一次。用户把 Key 发在对话里时注入当前会话环境变量并立刻继续，不要要求改系统变量或重启 Agent。用户明确没有则跳过公开网页、云端核心继续。不向用户逐次确认调用次数或积分。

## 七模块与能力分工

| 模块 | 发现能力 | 报告处理 |
|---|---|---|
| 外观设计 | 公开专利检索、云端外观图搜与反向图搜 | 对相似外观候选比较共同点、差异和商品关联性 |
| 实用专利 | 公开专利与网页检索 | 提取与产品结构、功能、技术卖点相关的候选和风险信号 |
| 申请中专利 | 公开专利与网页检索 | 单列申请中候选，提示不确定性和后续监控需求 |
| 文字商标 | 公开网页检索与云端文字标识检索 | 只使用品牌、型号和明确专有标识，不把整段 listing 拆词送检 |
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

- 复跑必须复用任务目录、计划、内部授权和稳定 request ID。
- `uncertain` 表示结果状态未知且可能已计费：停止当前付费链，不得换 request ID 重提。
- 明确 HTTP 5xx 且未消耗 credit 的 Serper 行记录为 coverage gap，继续其余独立查询，不自动重试失败项。
- Serper 单条响应可用候选保留率不低于 90% 时，孤立畸形项记入 parser warnings 而不阻断 coverage；原始响应、`items/total` 差异和拒绝原因仍全部保留。低于 90% 为 `partial`，零条可用为失败。
- `run-serper-plan` 在 `ready`、可审计的 `partial` 或 `SERPER_SKIPPED_NO_KEY` 时进入候选处置；`SERPER_SKIPPED_NO_KEY` 时问一次，用户给出 Key 就注入当前会话并立刻重跑，用户明确没有则继续云端结果并保留公开网页缺口。`blocked` 必须留在当前阶段恢复。
- 图片任务慢时等待轮询，不要因数分钟等待重复提交。
- `no_result` 必须来自成功且结构有效的零候选响应；认证、配额、超时、畸形 JSON 和解析失败都不是 `no_result`。
- 供应商原始响应与 `raw/` 证据不可由 Agent 修补。URL 和候选字段的可移植规范化由 CLI 完成；失败时复用原任务和稳定 operation 恢复，不改原始字节、不换 ID 重提。
- `no_result` 不等于不存在权利。

## 候选全批次处置

两条发现链结束后进入 `verifying_candidates`，读取 `serper/candidate_review_workspace.json`，一次性覆盖其中全部候选：

```bash
<IPR_CLI> apply-candidate-review --task-dir <task-dir> --input <candidate-review.json>
```

每个来源条目只能有一个处置。`material` 进入报告重点提示；`not_material` 必须带结构化排除依据；`needs_review` 会阻断最终评估。

## 完成条件

1. 双计划执行完毕或失败项已有明确、可审计的 gap；
2. 所有 provider item 已进入候选清单；
3. 候选全批次处置完整且没有 `needs_review`；
4. 七模块审阅及必要的独立复审/人工解决完成；
5. `finalize-assessment`、`render-report`、`validate-release` 全部通过。

任一条件不满足时输出 draft/incomplete 并说明缺口。完整报告仍是风险筛查，不是官方法律状态确认或法律意见。
