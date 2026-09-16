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
- 候选审阅批次必须是 UTF-8；连续 `????` 或 Unicode 替换字符表示理由已损坏，整个批次必须在写入证据账本前拒绝。
- Trohub/Serper 的相似度、排名和供应商风险文字只是发现信号，不能直接换算为模块或综合风险。
- 视觉候选拟标为 `material` 前，Agent 必须实际查看目标图与候选图，并在处置理由中分别记录共同点、关键差异和整体视觉印象。图片不可用时标为 `needs_review`，不得猜测。
- 冻结目标图在 `input-images/`；云端外观、图形商标和版权候选图优先读候选摘要中的 `image_ref`（位于 `us-screen/evidence-images/`）。缓存缺失时只读对应 `us-screen/raw/*.json` 的 `imageUrl` 获取，不得改写原始响应。Agent 必须调用图像查看能力，不能把供应商 `reason` 改写一遍冒充自己看过图。
- 文字商标标为 `material` 必须同时确认文字近似和商品/服务类别重叠。完全同名但 `tmClass` 与目标商品无关时使用 `different_goods_services` 排除，不得直接抬高风险。
- 明显不同品牌、品类、法域或重复记录可以依据结构化字段快速排除；相同图片可归组审阅代表图，但每个来源条目仍要独立处置。

## Assessment review

新任务先读 `risk-judgment.md`，并以该文档为风险判断规范。所有 material 候选必须有 finding；每个模块填写 confidence_reason。视觉 comparison 绑定实际查看文件，并记录整体判断、缺口、补证和重新评级条件。v2 不按权利状态单独抬高风险，不启用复合加一级；保留版权来源下限、置信度上限和完整性门禁。无规则版本的历史任务按 v1 校验。

使用 `assessment-review-input.schema.json` 完成一次完整的七模块审阅。风险按模块取最高值，置信度取最低值。CLI 规则可以抬高风险下限、限制置信度或阻断结论；Agent 文案不得降低这些约束。

视觉模块的 material candidate finding 必须同时写明 `similarities` 与 `differences`。检索分数高但关键造型差异明显时，应根据整体比较决定等级；可以保留为 material 候选并判中或低风险，也可以在关联较弱且有依据时排除。高/极高风险必须说明为何现有差异不足以改变整体判断，不能由检索分数直接得出。

一审通过后直接定稿。新任务不启动独立二审或人工冲突裁决；高风险仍必须绑定具体候选和 Agent 自己的证据比较，不能仅凭供应商结论。证据限制继续由确定性 floor、cap 和 formal block 处理。

## Release rules

- `report_data.json` 是报告唯一视图模型。
- 正式输出写入 `report/`，不完整输出写入 `report-draft/`。
- 报告必须明确说明它是风险筛查，不是官方法律状态确认或法律意见。
- manifest 绑定每个产物的 SHA-256 和字节数；任何摘要不一致都必须失败。
- 缺少必需的云端核心证据时输出 `not_assessable`，不得编造低风险结论。Serper 是可选增强；没有 Key 时依据云端核心证据完成七模块筛查，并以较低置信度准确描述本轮未发现的风险信号。
- 草稿没有完成七模块正式审阅时，模块和综合风险均显示 `not_assessable`；候选数量和发现层止损信号单独展示。
