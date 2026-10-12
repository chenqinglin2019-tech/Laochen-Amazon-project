---
name: lc_amazon_market_opportunity
description: 接续已完成的市场调研项目，完成词根、维度、Listing 打标和供需机会组合；按四项指标直接选出 Top3，再基于三组转化表／卖家精灵表生成各市场八项结论与 Top20 ASIN。
---

# 易逊-细分市场机会分析

仅负责细分市场机会分析。消费者声音、评价、Alexa/Rufus、KANO 和产品开发由 `lc_amazon_voc_to_product` 处理。

1. 先运行只读命令 `tools/niche_recommendation.py status --project-root <PROJECT_ROOT>` 判断当前阶段，再阅读 `INSTRUCTIONS.md` 与 `references/agent_workflow.md` 中该阶段相关的部分；已完成的步骤不得重跑。
2. 只接受当前对话明确给出的 `market_project_<YYYYMMDD_HHmmss>` 项目根目录；不扫描、不猜测项目。
3. 使用当前平台唯一对应的 `tools/bin/market-opportunity-*`，先执行 `inspect-report` 校验项目，再继承 manifest 的站点与 `listing_language`。
4. 基础机会分析只在 `status` 显示未完成时，从未完成的那一步起依序执行词根获取、维度候选、人工维度确认、打标模板、全量 Listing 打标和 `analyze-tags`（命令格式见 `INSTRUCTIONS.md`）。不改变既有筛选门槛、供需指数、排序或归一化。
5. 推荐阶段先接收用户商机探测器细分市场 Excel，运行 `tools/niche_recommendation.py prepare`。候选市场有两类来源：商机表细分市场（Agent 逐行处理并写标签条件）和多维打标组合（脚本按机会分取前 20 个，Agent 在 `combo_reviews` 中逐个审核并归属 direct 核心词）。Agent 完成上述工作和必要补标后运行 `shortlist`；`run` 是兼容别名。粗筛直接选出最多 Top3（不足 3 个时如实输出，不放宽门槛），导出这些市场的核心词、完整成员和月销量 Top20 ASIN；不冲突的未达标市场作为候补只记入 `niche_shortlist.json`（含原因），不进入第二轮、CSV 和报告。
6. 粗筛只按供需指数 80%、竞争开放度 10%、新品进入证据 5%、需求承接规模 5% 评分，所有候选都用本品类商品样本计算；供需指数为去掉前 3 个爆款并向品类平均收缩后的稳健指数，低于 1.0 不能正式推荐；共享月销量占较小市场一半及以上的两个市场只能选一个。商机表数据只作需求证据和风险参考，不参与评分。广告压力、关键词转化率、搜索增长与退货率不参与粗筛入选；后两项仅展示风险。口径细节以 `references/niche_recommendation_contract.md` 为准。
7. 粗筛完成后要求用户上传每个冻结市场各 2 个 Excel（Top3 时共 6 个）：每个市场 1 份细分市场关键词转化表及 1 份对应卖家精灵关键词表，顺序不限。两类表分工固定：关键词转化表（如 `关键词-20260905-….xlsx`）只取关键词、点击量和购买量，表内“最高出价／最低出价／建议出价”等出价列一律忽略；建议竞价只取自卖家精灵关键词反查表（如 `ExpandKeywords-US-<ASIN>-batch(20)-….xlsx`，以含 `Asin` 工作表识别）的 `PPC竞价` 列。`refine --keyword-input-xlsx <2×市场数 files>` 先以卖家精灵 `Asin` 工作表与该市场冻结 Top20 ASIN 完全一致（不足 20 个时按实际数量）识别市场，再以转化表关键词与该卖家精灵累计流量占比前90%关键词的高重叠完成一对一配对。进一步分析不重新排名、不淘汰市场，Top20 与成员沿用冻结结果（价格或销量无效的商品只从八项结论样本中剔除并留痕）；只用同时有转化数据（点击量>0、购买量有效）和卖家精灵建议竞价（`PPC竞价`>0）的关键词：转化率为这些词的购买量之和／点击量之和，加权CPC为这些词的“词点击量／这些词点击量之和×词PPC竞价”累加；缺任一项的关键词整行忽略，不用其他来源（如关键词表推荐竞价）补齐。广告压力为加权CPC／（转化率×本市场完整有效商品算术均价）。不得进行关键词相关性筛选。
8. 两轮报告必须使用内置的 `two-round-competition-v1` 版式（用户冻结的原始格式），不得根据品类、数据量或 Agent 判断增删、改名、调序或另起 CSS。固定顺序为：粗筛评分表 → Top3 折叠卡 → 关键词与广告指标表 → Top3 细分市场竞争环境分析；每个复评市场固定呈现市场解读、四张摘要卡、8 项规则结论表和评论数／上架天数／评分／售价四维透视。原 HTML 不覆盖；详细结构、表格列、对齐、边框和窄屏规则见 `references/report_layout_contract.md`。
9. Top20 板块必须展示“复制这 N 个 ASIN”按钮，按榜单顺序逐行复制 ASIN；不足 20 个如实显示，空集合不可复制。
10. `niche_shortlist.json` 是唯一的 Top3 名单与排名来源。`backup_candidate_ids` 只作参考记录。`08_niche_recommendations.json` 只保存绑定该名单的进一步分析、关键词明细、八项结论，以及只写在数据里的 `entry_advice`（进入建议／风险等级）和 `ad_cost_evidence.low_coverage`（参与词点击覆盖低于 60%）；这两项不在报告中展示，不改变排名；它不得重选 Top3。交接时核对阶段、运行 ID、输入指纹、粗筛绑定和提交哈希。

原 CLI 的 Token、配置、请求、计费和失败处理保持原样；不得因升级更改后端权限标识、环境变量、用户配置路径或二进制。

## 资源

- `INSTRUCTIONS.md`：机会分析执行契约。
- `references/input_contract.md`：上游项目、输入与产物契约。
- `references/agent_workflow.md`：维度确认、归一化、打标和质量校验。
- `references/niche_recommendation_contract.md`：粗筛、进一步分析、Top20、八项结论和交接契约。
- `references/report_layout_contract.md`：两轮复评 HTML 的固定页面结构与视觉版式契约。
