# 输入与中间文件契约

## 来自市场主报告的文件

- `cleaned_30d_listings.json`：近 30 天有效 listing，已经完成硬规则清洗和 agent 明显不相关 ASIN 剔除。
- `06_top90_keywords.json`：按流量占比累计到 90% 的关键词。
- `03_market_metrics.json`：总指标和垄断/趋势指标。
- `01_input_manifest.json`：站点、Excel 原币种、核心词、类目、源文件路径。站点必须是 `US`、`UK`、`DE`、`FR`、`JP`、`AU`、`CA`、`IT`、`ES`、`MX` 之一；旧值 `GB` 只规范为 `UK`。
- `report_data.json`：HTML 看板使用的公开数据。

## 本 skill 生成的文件

- `02_keyword_roots.json`：统一后端关键词词根返回、项目站点、主要语言和请求计数。
- `03_dimension_candidates.json`：按词根类型聚合的维度候选。
- `agent_dimensions.json`：agent 确认的最终维度。
- `04_tagging_workspace.json`：给 agent 逐 listing 打标的工作区。
- `agent_listing_tags.json`：agent 打标结果。
- `07_opportunity_analysis.json`：结构化机会分析结果。
- `市场机会深挖看板.html`：最终阅读入口。

## 可选消费者声音阶段输入

- `07_opportunity_analysis.json.feature_distribution`：Top3 的唯一选择来源。
- 当前上下文明确给出的 `collector.sqlite3`：全历史全量清洗的唯一源语料；不得扫描其他项目猜测。
- `selected_segments.json`：Top3 选择痕迹，输出时映射为 `segment_1_all_history` 至 `segment_3_all_history`。
- `consumer_voice_taxonomy.json`：当前品类的产品词、六语义扩展词、主题、Top3 和 KANO 映射。
- 用户明确要求首次采集或刷新时，可额外读取 `last30days` 原始候选、`agent-reach` 深读结果和 YouTube Data API 评论；这些采集字段不形成分析时间窗。
- 当前机会报告快照中的 listing 标题、参数、图片与详情，用于 Top3 供给验证。

## 可选消费者声音阶段输出

- `market_opportunity/consumer_voice_all_history_<timestamp>/selected_segments.json`
- `market_opportunity/consumer_voice_all_history_<timestamp>/consumer_voice_taxonomy.json`
- `market_opportunity/consumer_voice_all_history_<timestamp>/source_snapshot.json`
- `market_opportunity/consumer_voice_all_history_<timestamp>/social_voice_all_history_coding.json`
- `market_opportunity/consumer_voice_all_history_<timestamp>/social_voice_all_history_analysis.json`
- `market_opportunity/consumer_voice_all_history_<timestamp>/` 下的三份概念图提示词与图片。
- `market_opportunity/消费者声音与产品创意开发报告-全历史-<timestamp>.html`：独立离线阅读入口，不覆盖基础机会看板。

`project_manifest.json` 仅原子增加：

- `artifacts.consumer_voice_all_history_coding`
- `artifacts.consumer_voice_all_history_analysis`
- `artifacts.consumer_voice_all_history_report_html`
- `status.consumer_voice_all_history = ready | partial | failed`

详细字段、全历史分母和无置信度约束见 `consumer_voice_contract.md` 及两个全历史 JSON Schema。

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

非英语站点的原始值和 evidence 必须保留源语言；`display_values` 必须是中文展示标签。项目站点在本 skill 内不可更改。

消费者声音的每条记录还必须保留可审计来源、可选发布时间、采集 scope、query ID、细分语义归属和硬身份去重 trace；同一底层声音的多路发现来源要合并，不能复制成多条。无日期和早期内容必须正常进入全量语义检查，日期不得决定量化资格。
