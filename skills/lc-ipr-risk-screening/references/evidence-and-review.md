# Evidence, Review, And Release Gates

## Seven modules

冻结查询计划和审阅必须完整覆盖：

1. `appearance_design`
2. `utility_patent`
3. `pending_patent`
4. `word_mark`
5. `figurative_trade_dress`
6. `copyright_creative_ip`
7. `enforcement_public_signals`

## Candidate integrity

- 每个 provider item 都必须按 `(run_id, source_index)` 进入候选记录，分组不能隐藏条目。
- Agent 必须一次性处置当前工作区中的全部候选。
- `material` 表示需要在报告中重点提示和复核；`not_material` 必须带结构化排除理由；`needs_review` 会阻断最终评估。
- 候选处置只基于冻结证据，不能把无结果解释成不存在权利。

## Assessment review

使用 `assessment-review-input.schema.json` 完成七模块审阅。风险按模块取最高值，置信度取最低值。CLI 规则可以抬高风险下限、限制置信度、要求第二审或阻断结论；Agent 文案不得降低这些约束。

需要第二审时，必须使用不同 reviewer ID 和 session；没有真实运行时隔离证明时不得声称 `runtime_enforced`。两审默认按更高风险、更低置信度保守合并。只有两级风险差、同一 finding 内容冲突、最高风险模块集合完全错位，或 `disputed_class_overlap` / `module_conflict` 等仍需人工判断的实质争议才使用 `human-resolution-input.schema.json`。证据缺口类 trigger 继续由确定性 floor、cap 和 formal block 处理，不重复要求用户裁决。

## Release rules

- `report_data.json` 是报告唯一视图模型。
- 正式输出写入 `report/`，不完整输出写入 `report-draft/`。
- 报告必须明确说明它是风险筛查，不是官方法律状态确认或法律意见。
- manifest 绑定每个产物的 SHA-256 和字节数；任何摘要不一致都必须失败。
- 缺少证据时输出 `not_assessable`，不得编造低风险结论。
