# Agent Workflow Contract

本文件只约束 agent 判断和留痕，不替代 CLI 计算。

## 维度确认输出契约

Agent 必须基于 `03_dimension_candidates.json` 做四件事：

1. 去掉品类主词和无效词根。
2. 将词根按语义聚类成消费者决策维度。
3. 按文档 5 项分数给维度打分。
4. 基于品类常识补充搜索词未覆盖但可能重要的维度。

搜索需求分来自 CLI 的候选结果；其余四项由 agent 判断：

- 区分产品分：0 几乎无法分层，50 能分出 2-3 个有量子维度，100 能清晰分成多个子维度且销量差异明显。
- 购买影响分：0 消费者基本不看，50 部分人会参考，100 购买前几乎必比。
- 可打标分：0 标题/图片/规格都难稳定识别，50 需图片辅助且部分可识别，100 标题或规格稳定明确。
- 业务可用分：0 后续供需/竞品/机会分析用不上，100 可直接用于供需指数、竞品对比、机会判断。

维度总分：

```text
搜索需求分 * 35%
+ 区分产品分 * 20%
+ 购买影响分 * 20%
+ 可打标分 * 15%
+ 业务可用分 * 10%
```

必须记录：

- `dimensions`：最终入选或候选维度，至少含 3-6 个 `selected=true` 维度。
- `rejected_dimensions`：低于 60 分或不适合打标的维度及原因。
- `supplemented_dimensions`：LLM 基于品类常识补充的维度，必须标注 `source: "LLM推断"`。
- `llm_calls`：维度聚类和维度补全的输入摘要、输出摘要、是否推断。

## 逐 listing 打标与归一化输出契约

Agent 必须对每个 listing 一次性判断所有确认维度，不要一个维度一轮。

判断顺序：

1. 先看 `title`、`params`、`category_path`。
2. 文本无法判断时，才看 `image_url`。
3. 图片仍无法判断时，再看 `product_url`。
4. 仍无法稳定判断，填 `不可识别`。

输出值分三层：

```text
原始识别值 -> 标准语义值 -> 中文展示标签
```

示例：

```json
{
  "dimension": "材质",
  "raw_value": "memory foam",
  "standard_value": "memory foam",
  "upper_group": "foam",
  "display_value": "泡棉/记忆棉",
  "merge_reason": "同属泡棉材质，不改变消费者决策含义。"
}
```

归一化规则：

- 只合并词义高度接近的表达。
- 低占比不能作为强行合并理由。
- 只有存在明确上位语义且不改变消费者决策含义时，才允许上位合并。
- 无法合理合并的 1%-10% 特征标记为长尾候选；不要硬并进主流特征。
- `<1%` 可归入 `其他`，但原始值仍要在 `normalization_dictionary` 留痕。
- `display_value` 必须是中文展示标签。可以保留必要行业缩写，例如 `PU皮革`、`USB-C接口`，但不能只写英文原词。

`agent_listing_tags.json` 必须包含：

- `tags`：每个 ASIN 的原始值、归一值、中文展示值和证据。
- `normalization_dictionary`：原始值到标准词义/中文展示标签的映射。
- `unrecognized_samples`：不可识别样本和原因。
- `llm_calls`：打标与归一化调用记录。
- `review_summary`：记录主要使用字段、图片复核数量、商品链接复核数量和说明。

质量底线：

- `tags` 必须和清洗后有效 listing 的 ASIN 一一对应。
- 每个 ASIN 的每个确认维度都必须有 `values`、`normalized_values`、`display_values` 和 `evidence`。
- `display_values` 是 CLI 统计和 HTML 展示的唯一标签来源，必须能从 `normalization_dictionary.display_value` 追溯。
- 如果某个维度填 `不可识别`，必须在 `unrecognized_samples` 中记录 ASIN、维度和原因。
- 如果只基于文本字段打标，必须在 `review_summary.notes` 中说明；如使用图片或商品链接复核，必须记录数量并在 evidence 中说明。

## 机会解释边界

Agent 最终解释时必须区分：

- 结构化计算：CLI 算出的占比、平均销量、供需指数。
- Agent 语义打标：维度、特征值、归一化和证据。
- 人工确认项：用户确认的最终维度。
- 无法判断：数据不足、不可识别占比过高、小样本。

不要把小样本观察项说成正式机会。正式机会必须同时看：

- Listing 数量 >= 10
- 供需指数 > 1
- 销量占比明显高于 Listing 数量占比
- 平均销量较高
- 组合维度具有明确产品意义

供需指数 = 该标签或组合的销量占比 / Listing 数量占比。数值越大，表示样本内“销量占比相对供给占比”越强；但不能脱离样本量、销量占比、平均销量和产品意义单独判断。

多选标签下，Listing占比和销量占比都是标签覆盖口径，不是排他市场份额，不能直接相加。
