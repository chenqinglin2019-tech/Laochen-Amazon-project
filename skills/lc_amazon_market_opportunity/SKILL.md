---
name: lc_amazon_market_opportunity
description: 接续市场调研项目，拆解词根、确认决策维度并逐 Listing 打标，输出供需机会组合和离线看板。
---

# 易逊-细分市场机会深挖-产品开发

> 最近更新：2026-08-05（UTC+8）

本 skill 是 `lc_amazon_market_research` 的连续下游：先完成商品机会深挖；用户要求时，再完成全历史消费者声音与产品开发。它不是独立入口，不重新读取原始 Excel。

## 商品机会深挖

1. 完整阅读 `INSTRUCTIONS.md`。
2. 只从当前对话读取上一段明确输出的项目根目录。没有真实 `market_project_<YYYYMMDD_HHmmss>/` 路径时，按固定停止话术结束；不补问、不扫描、不猜测最新项目。
3. 按当前系统选择 `tools/bin/` 中唯一对应的 CLI，并用 `inspect-report` 校验项目。
4. 继承 manifest 中的站点和 `listing_language`；不得重新询问、默认或覆盖站点。
5. 依次执行 `fetch-roots`、`dimension-candidates`、Agent 维度确认、`tagging-template`、Agent 全量 Listing 打标和 `analyze-tags`。
6. 维度确认、归一化和打标完整遵循 `references/agent_workflow.md`。原文证据保留源语言，HTML 展示标签使用中文。
7. 只从 `07_opportunity_analysis.json.feature_distribution` 选择消费者声音阶段的 Top3：有效维度、有效特征、`3% <= listing_share <= 20%`，按原始供需指数及固定并列规则排序；不足 3 个时不放宽门槛。

## 全历史消费者声音与产品开发

8. 用户已明确要求消费者声音/KANO/产品创意时直接继续；否则在机会看板完成后只询问一次。
9. 开始前完整阅读 `references/consumer_voice_workflow.md`、`references/consumer_voice_contract.md`、两个全历史 Schema，以及本轮实际调用的采集 Skill。
10. 将分析范围固定为“本项目本地已采集语料的全历史”。`published_at` 可缺失，只作追溯和年份分布，不参与纳入、排除、权重或排序。报告不得暗示穷尽互联网全历史。
11. 已有明确来源的 `collector.sqlite3` 时直接全量处理，不再联网；不得扫描其他项目寻找数据库。只有用户明确要求首次采集或刷新数据时，才使用 `consumer_voice_collector.py`、`last30days`、`agent-reach` 和 YouTube Data API 获取候选。采集档位只限制本次新增采集的预算和时长，不形成分析时间窗、样本截断或报告分母。
12. 为当前品类生成或复核项目级 `consumer_voice_taxonomy.json`，再运行 `scripts/consumer_voice_local_reprocess.py`；必须通过 `--dashboard` 传入原机会看板以记录并复核其 SHA-256。内置词典只适用于明确识别出的车载手机支架项目；其他品类必须提供项目级 taxonomy，不得套用手机支架词典。
13. 全量检查源 DB 的每条硬身份唯一记录。只有同时满足“产品相关、消费者表达、非广告/机器人/纯链接/无观点引用”，并命中以下至少一类，才进入消费者表达分母：

   - 购买、选型和推荐
   - 故障、抱怨、退货和替代
   - 满意、推荐和复购
   - 安装、兼容性和使用场景
   - DIY、改装和绕行方案
   - 新功能、反向需求和创意
14. 只合并同一平台内容/评论 ID、同一留言直链或确定性替代身份证明为同一底层留言的重复发现。不同 ID 即使原文或语义相同，也分别计数；同一留言可命中多类，但联合分母只计一次。
15. Coding、Analysis 和 HTML 均不得包含置信度字段、置信度徽标或把“证据不足”当作 KANO 类型。KANO 只展示有方向性依据的“必备型、期望型、魅力型、无差异型、反向型”；无法分类的需求直接不进入 KANO 表。
16. 使用 `scripts/consumer_all_history_report.py render` 生成独立离线 HTML，再用 `check` 校验。报告沿用 `assets/consumer_all_history_report.template.html`，不得修改或覆盖原 `市场机会深挖看板.html`。
17. 产品分析默认输出 3 个方向，覆盖 JTBD、场景、消费者证据、KANO、技术方案、结构/材质/CMF、BOM、风险、验收指标、Design Thinking、MoSCoW、提示词和概念图。Agent 创意不得伪装成消费者直接留言。
18. 用 `scripts/consumer_all_history_report.py finalize-manifest` 原子增加全历史消费者声音的 3 个 artifact 键和 1 个状态键；既有 manifest 键、源 DB 和原机会看板必须保持不变。

## 核心资源

- `INSTRUCTIONS.md`：完整执行指令。
- `references/agent_workflow.md`：维度确认、归一化和逐 Listing 打标契约。
- `references/consumer_voice_workflow.md`：全历史消费者声音、KANO、产品开发和报告工作流。
- `references/consumer_voice_contract.md`：全历史数据、计数、状态、HTML 和 manifest 契约。
- `references/social_voice_all_history_coding.schema.json`：逐条编码 Schema。
- `references/social_voice_all_history_analysis.schema.json`：汇总分析 Schema。
- `references/consumer_voice_taxonomy.schema.json`：项目级产品语义词典 Schema。
- `scripts/consumer_voice_local_reprocess.py`：只读全量清洗、六语义编码和确定性汇总。
- `scripts/consumer_all_history_report.py`：离线 HTML 渲染、检查和 manifest 最终化。
- `assets/consumer_all_history_report.template.html`：固定报告模板。
- `scripts/consumer_voice_collector.py`：仅在用户明确要求首次采集或刷新时使用的候选采集器；其旧 v2 编码/报告入口不属于默认主链。

旧 `social_voice_coding.schema.json`、`social_voice_analysis.schema.json`、`consumer_product_report.py` 的 v2 分析/渲染命令和 `consumer_product_report.template.html` 仅用于复核历史产物；新任务不得调用。`consumer_product_report.py select-segments` 在独立 Top3 选择器完成迁移前可兼容使用，但其输出必须映射为 `*_all_history` scope。
