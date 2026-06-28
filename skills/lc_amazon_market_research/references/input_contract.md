# 输入契约

## 必填输入

- `last30`：近 30 天竞品表。
- `monthly` 或 `monthly-dir`：近 12 个月竞品月表。
- `keywords`：头部 ASIN 关键词反查表。
- `conversion`：核心关键词转化率表。

## 自动识别上下文

运行 `tools/bin/market-research inspect-inputs` 后，从本地 Excel 自动识别：

- `marketplace`：站点，例如 `US`。优先从文件名 `Competitor-US-*`、`ExpandKeywords-US-*`、`KeywordConversionRate-US-*` 识别。
- `keyword`：核心关键词 / 市场名。优先从 `KeywordConversionRate-US-car seat cushion(164)-Last 90 days.xlsx` 或 sheet 名识别；识别不到时从表内第一条关键词兜底。
- `primary_category`：主类目路径。从近 30 天竞品表 `类目路径` 的众数识别。

只有识别缺失或冲突时，才让用户补充。

## 可选输入

- `agent_relevance_workspace.json`：由 `market-research relevance-workspace` 生成，包含硬规则清洗后的近 30 天有效 listing 全量相关性打标工作区。
- `agent_relevance_tags.json`：Agent 对工作区中每个 ASIN 输出的相关性标签。`relevance` 只能是 `related`、`irrelevant`、`uncertain`；只有 `irrelevant` 会被剔除。
- `exclude-asins`：由 `market-research relevance-exclusions` 从 `agent_relevance_tags.json` 校验导出的明显不相关 ASIN 清单。仅用于原始文档要求的“明显不相关产品剔除”。只有传入 `exclude-asins` 的 ASIN 才会从主分析样本和月表中剔除。

CSV 格式：

```csv
asin,reason
B0XXXXXXX,明显不相关：不是当前核心关键词对应产品
```

也可以直接把通过校验的 `agent_relevance_tags.json` 传给 `run --exclude-asins`，CLI 会只读取其中 `relevance=irrelevant` 的 ASIN；主流程仍建议先用 `relevance-exclusions` 生成 CSV 和审计文件。

## 竞品表关键字段

第一张非 `Notes` sheet 必须包含：

- `ASIN`
- `品牌`
- `商品标题`
- `父ASIN`
- `类目路径`
- `月销量`
- `月销售额($)`
- `价格($)`
- `评分数`
- `评分`
- `上架天数`
- `BuyBox卖家` 或 `卖家信息`

缺失价格、价格为 0、缺失销量或销量为 0 的行会从主分析样本剔除。`exclude-asins` 中的 ASIN 也会剔除。缺失评分数或评分按 0 处理。

## 关键词反查表关键字段

第一张非 `Notes` sheet 必须包含：

- `关键词`
- `流量占比`
- `月搜索量`
- `月购买量`
- `点击量`
- `PPC竞价`

如果文件含 `Unique Words` sheet，CLI 会读取词频数据，仅作为关键词结构参考。

## 转化率表关键字段

第一张非 `Notes` sheet 必须包含：

- `关键词`
- `近90天点击量`
- `近90天购买量`
- `PPC竞价-推荐($)`

`PPC竞价-推荐($)` 为空或无法解析的行会被剔除；平均转化率和加权 PPC 只基于保留词计算。
