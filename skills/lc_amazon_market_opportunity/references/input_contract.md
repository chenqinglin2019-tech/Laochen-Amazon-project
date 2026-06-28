# 输入与中间文件契约

## 来自市场主报告的文件

- `cleaned_30d_listings.json`：近 30 天有效 listing，已经完成硬规则清洗和 agent 明显不相关 ASIN 剔除。
- `06_top90_keywords.json`：按流量占比累计到 90% 的关键词。
- `03_market_metrics.json`：总指标和垄断/趋势指标。
- `01_input_manifest.json`：站点、核心词、类目、源文件路径。
- `report_data.json`：HTML 看板使用的公开数据。

## 本 skill 生成的文件

- `02_keyword_roots.json`：后端关键词词根返回和请求计数。
- `03_dimension_candidates.json`：按词根类型聚合的维度候选。
- `agent_dimensions.json`：agent 确认的最终维度。
- `04_tagging_workspace.json`：给 agent 逐 listing 打标的工作区。
- `agent_listing_tags.json`：agent 打标结果。
- `07_opportunity_analysis.json`：结构化机会分析结果。
- `市场机会深挖看板.html`：最终阅读入口。

## Agent 文件必须包含的追溯字段

`agent_dimensions.json`：

- `llm_calls`
- `dimensions`
- `rejected_dimensions`
- `supplemented_dimensions`

`agent_listing_tags.json`：

- `llm_calls`
- `tags`
- `normalization_dictionary`
- `unrecognized_samples`
- `review_summary`

`tags` 内每条 ASIN 必须同时包含：

- `values`：原始识别值
- `normalized_values`：标准语义值
- `display_values`：中文展示标签，供 CLI 统计、CSV 和 HTML 使用
- `evidence`：每个维度的判断依据

`normalization_dictionary` 每条映射必须包含 `display_value`，用于追溯 `display_values`。
