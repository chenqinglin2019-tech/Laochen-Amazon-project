# Amazon Market Opportunity（Agent 入口）

完整指令读取 `INSTRUCTIONS.md`。消费者声音阶段同时完整读取 `references/consumer_voice_workflow.md` 与 `references/consumer_voice_contract.md`。

## 主流程

当前对话已经有上一段市场主报告明确输出的 `market_project_<YYYYMMDD_HHmmss>/` 项目根目录 → CLI 生成基础机会分析和固定看板 → 用户要求时，对本地已采集消费者语料执行全历史全量清洗 → 生成六语义、KANO、产品方向、概念图和独立离线 HTML。

## 启动边界

- 本 skill 是连续上下文入口。只有当前对话存在上一段 `lc_amazon_market_research` 明确输出的真实项目根目录时才能继续。
- 没有真实项目目录时直接停止；不补问路径、不扫描本地目录、不猜最新项目、不从原始 Excel 重建。
- 站点和 `listing_language` 只继承项目 manifest；不重新询问、不默认 US、不允许覆盖。
- 支持 `US`、`UK`、`DE`、`FR`、`JP`、`AU`、`CA`、`IT`、`ES`、`MX`；旧 `GB` 只规范为 `UK`。
- 固定停止话术：`商品机会深挖依赖上一段市场主报告结果；当前上下文没有可用的 market_project 项目目录，本轮不继续执行。请先完成市场主报告后，在同一上下文里继续。`

## 商品机会深挖边界

- 不重新读取原始 Excel，不绕过 `cleaned_30d_listings.json`。
- 关键词词根只通过 `market-opportunity fetch-roots` 调统一后端；不得读取、打印或复述后端凭据。
- 后端明确缺少访问 Token 时立即停止，不自行拆词根或绕过。
- 按系统选择唯一 CLI；macOS 首次执行前静默处理 quarantine 和执行权限。
- 维度确认、评分中的非搜索项、归一化和逐 Listing 打标由 Agent 完成；CLI 只做可复现计算。
- 每个 Listing 一次性判断全部维度；优先标题和参数，文本不足才看图片/链接，无法稳定判断填 `不可识别`。
- 非英语站点必须理解目标语言；原文证据保留源语言，`display_values` 使用中文。
- 原 `市场机会深挖看板.html` 由 CLI 固定生成；除用户明确要求开发模板外，不手改。

## 消费者声音核心口径

- Top3 只从 `07_opportunity_analysis.json.feature_distribution` 选择：有效维度、有效特征、`3% <= listing_share <= 20%`，按原始供需指数和固定并列规则排序；不足 3 个不放宽门槛。
- 分析范围是指定源 DB 中该 task 的本地全历史。发布日期允许缺失，只作追溯和年份分布，不参与准入、排除、权重、排序或 KANO。
- 已有明确源 `collector.sqlite3` 时不联网，直接全量处理；不得扫描其他项目猜测数据库。
- 只有用户明确要求首次采集或刷新时才调用 collector、`last30days`、`agent-reach` 和 YouTube Data API。采集档位只限制新增采集预算，不形成分析时间窗、样本截断或状态门槛。
- 每个品类必须生成或复核项目级 `consumer_voice_taxonomy.json`。内置规则只允许用于明确识别为车载手机支架的项目，其他品类不得复用。
- 每条硬身份唯一记录都必须进入 `voices` 或 `excluded_records`。进入分母需同时满足产品相关、消费者表达、非广告/机器人/媒体/卖家内容，并命中六类语义至少一类。
- 六类语义固定为：购买/选型/推荐；故障/抱怨/退货/替代；满意/推荐/复购；安装/兼容性/场景；DIY/改装/绕行；新功能/反向需求/创意。
- 只合并可证明为同一底层留言的重复发现。不同 ID 即使文本或语义相同，也分别计数；不得做文本哈希、高相似或语义去重。
- Coding、Analysis 和 HTML 不得输出置信度字段、置信度徽标或“证据不足”KANO。KANO 只允许必备型、期望型、魅力型、无差异型、反向型；无法分类的主题直接省略。
- 用户可见 HTML 不展示来源状态、证据 ID、证据类型计数、旧 scope、内部字段名或采集错误串。每项洞察最多展示 3 条代表性原声。
- “全历史”只能解释为本地已采集语料的全量处理，不得声称穷尽互联网全历史。

## 产物与状态

- 使用 `consumer_voice_local_reprocess.py` 生成全历史 Coding/Analysis；使用 `consumer_all_history_report.py` 生成并检查独立单文件 HTML。
- 默认输出 3 个产品方向，覆盖 JTBD、场景、KANO、技术、结构/材料/CMF、BOM、风险、验收、Design Thinking、MoSCoW、提示词和概念图。
- `ready` 依赖源 task 全量检查与对账、JSON/HTML/产品方向完整、无时间窗/置信度残留、源 DB 和机会看板不变；平台数量、日期覆盖率和旧研究档位不再决定状态。
- Manifest 只能原子增加 `consumer_voice_all_history_*` 三个 artifact 键和 `status.consumer_voice_all_history`，不得改写已有键。
- 第二阶段必须生成新 HTML；不覆盖、不注入原机会看板，交付前校验其 SHA-256 不变。

## 工具

- `<selected-cli> inspect-report|fetch-roots|dimension-candidates|tagging-template|analyze-tags`：基础机会分析。
- `python3 scripts/consumer_product_report.py select-segments ...`：兼容使用的独立 Top3 选择命令；不得调用该脚本的旧 v2 分析、渲染或最终化命令。
- `python3 scripts/consumer_voice_local_reprocess.py ...`：本地全历史全量清洗和汇总。
- `python3 scripts/consumer_all_history_report.py render|check|finalize-manifest ...`：独立报告与 Manifest 最终化。
- `python3 scripts/consumer_voice_collector.py doctor|plan|run|resume|receipt ...`：仅在用户明确要求首次采集或刷新时使用。
