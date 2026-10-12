# 输入与中间文件契约

## 来自市场主报告的文件

- `cleaned_30d_listings.json`：近 30 天有效 Listing；不在本 Skill 重新清洗或补抓。
- `01_input_manifest.json`：站点、核心词、类目和源文件路径；站点继承项目，不在本 Skill 覆盖。
- `agent_listing_tags.json`：最终标签、归一化值、中文展示值与证据。
- `07_opportunity_analysis.json`：其正式机会组合是多维组合候选的来源（只读）；`市场机会深挖看板.html`：原报告，只读。

## 初筛输入与产物

用户提供商机探测器细分市场 `.xlsx`，工作表为`细分市场列表`。必需列只有`细分市场名称`和`细分市场分类1`；其余指标只作需求证据、风险显示与参考，不参与评分。

Agent 创建 `niche_candidate_definitions.json`，声明商机表候选的需求边界、标签表达式、`exact` 主行、direct 关键词归属及互斥关系，并在 `combo_reviews` 中审核每个多维组合候选（格式见 `niche_recommendation_contract.md` §2）。冻结前可补标；冻结后任何商品、标签、关键词、商机表或定义变化均需重跑。

初筛产物保留原文件名：

- `niche_shortlist.json`：四项评分、固定 Top3 ID 与排名、候补 ID 与原因、冻结输入和状态；它是唯一 Top3 与候补来源。
- `niche_shortlist_keywords.json`、`niche_shortlist_memberships.json`：核心词、完整成员和未知成员。
- `niche_shortlist_core_keywords.csv`、`niche_shortlist_top20_asins.csv`：供用户统一补转化表及查看榜单。
- `niche_shortlist_run.json`、`市场机会深挖看板-两轮初筛.html`：回执和初筛报告。

## 进一步分析输入与产物

用户一次提供冻结市场数 2 倍的 `.xlsx`（Top3 时 6 个），顺序不限：每个市场 1 个细分市场关键词转化表及 1 个卖家精灵关键词表。两类表分工固定：关键词转化表（如 `关键词-20260905-….xlsx`）只取关键词、点击量和购买量，表内“最高出价／最低出价／建议出价”等出价列一律忽略；建议竞价只取自卖家精灵关键词反查表（如 `ExpandKeywords-US-<ASIN>-batch(20)-….xlsx`，以含 `Asin` 工作表识别）的 `PPC竞价` 列。转化表选择第一个同时含`关键词`、点击量和购买量的工作表；接受`近90天点击量`／`点击量-近90天`／`点击量`和`近90天购买量`／`购买量-近90天`／`销量-近90天`／`购买量`／`销量`。表头已显式标明近90天时可视为统一窗口；其他表必须有统一有效周期或显式传 `--conversion-period`。若有站点列则必须匹配项目站点。卖家精灵表必须含`关键词`、`PPC竞价`、`流量占比`，并在名称为`Asin`（大小写不敏感）的工作表中提供与该市场冻结 Top20 完全一致的 ASIN（不足 20 个时按实际数量）。

`refine --keyword-input-xlsx <2×市场数 files>` 通过 `--shortlist-result` 绑定当前成功的 v10 初筛，不能另传定义或商机表，不能扩大冻结成员。每份卖家精灵表的 ASIN 必须与一个冻结细分市场 Top20 ASIN 完全一致；转化表必须与其卖家精灵表累计流量占比前90%关键词至少80%精确重叠。单文件参数 `--keyword-conversion-xlsx` 已停用。

进一步分析产物保留原文件名：

- `08_niche_recommendations.json`：绑定固定 Top3 的八项结论和各市场分析状态，不重新选择 Top3。
- `09_niche_keyword_assignments.json`、`10_niche_product_memberships.json`：参与词（同时有转化与建议竞价）计算明细、成员、Top20、文件关联和排除原因。
- `niche_top20_asins.csv`、`niche_rule_conclusions.json`、`niche_recommendation_run.json`、`市场机会深挖看板-两轮复评.html`：结果、回执和报告。

## 阶段与交接

初筛成功且有正式 Top 市场时 manifest 状态为`awaiting_keyword_conversion`（只有候补时为 `shortlist_pending`）；进一步分析全部可判定时为`refined_ready`，任何一个市场有缺项时为`refinement_pending`。失败只更新当次回执与失败状态，历史成功产物保留阅读。

下游必须核对当前规则版本、粗筛／进一步分析运行 ID、输入指纹、成功回执、产物哈希、固定 Top3 ID 与顺序，再消费 08 及同批 09／10。不得根据 `feature_distribution`、Listing 占比或供需指数再次选择市场。
