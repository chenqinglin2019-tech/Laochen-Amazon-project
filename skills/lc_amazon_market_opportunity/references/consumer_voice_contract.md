# 全历史消费者声音与产品创意数据契约

本契约是消费者声音阶段的唯一默认契约，约束本地源语料、全量清洗、六语义编码、统计、KANO、HTML 和 Manifest。旧 30/90 天 v2 契约仅用于读取既有历史产物，不得用于新任务。

## 目录

1. 输入与不变量
2. 输出
3. 项目级 Taxonomy
4. Coding JSON
5. Analysis JSON
6. 六语义准入
7. 硬身份与全量对账
8. 分母和比例
9. 无时间筛选
10. 无置信度与 KANO
11. 产品与供给验证
12. HTML
13. Manifest
14. 状态

## 1. 输入与不变量

输入只来自当前对话已确认的同一项目：

- `project_manifest.json`
- `market_research/01_input_manifest.json`
- `market_opportunity/07_opportunity_analysis.json`
- `market_opportunity/市场机会深挖看板.html`
- 当前上下文明确给出的 `collector.sqlite3`
- 当前项目的 `selected_segments.json`
- 当前项目的 `consumer_voice_taxonomy.json`

不得扫描其他项目猜测源 DB，不得重新读取原始 Excel。处理前记录源 DB 和原机会看板的路径、大小、mtime 与 SHA-256；处理后必须再次校验不变。

源 DB 使用 SQLite `mode=ro` 和 `PRAGMA query_only=ON` 打开。处理阶段不执行任何网络请求。

## 2. 输出

每次创建独立目录：

```text
market_opportunity/
  consumer_voice_all_history_<YYYYMMDD_HHmmss>/
    consumer_voice_taxonomy.json
    selected_segments.json
    source_snapshot.json
    social_voice_all_history_coding.json
    social_voice_all_history_analysis.json
    local_reprocess_receipt.json
    prompts/
    images/
  消费者声音与产品创意开发报告-全历史-<YYYYMMDD_HHmmss>.html
```

新任务不得覆盖旧运行目录、旧消费者报告或原机会看板。

## 3. 项目级 Taxonomy

`consumer_voice_taxonomy.json` 遵循 `consumer_voice_taxonomy.schema.json`，并包含：

- `schema_version`、`profile_id` 和 `product_label`
- `product_terms` 与 `implicit_product_terms`
- `semantic_extensions`：仅允许六个固定语义代码
- `topics[]`：稳定 code、中文 label 和匹配规则
- `segments[]`：1 至 3 个 `segment_*_all_history` 的匹配规则
- `kano_mapping`：主题 code 到五类中文 KANO 的映射

`terms` 按字面量转义后匹配；可选 `patterns` 按正则表达式编译，必须由 Agent 复核且通过配置加载校验。Taxonomy 是项目产物，必须保留供复算。内置手机支架词典只在项目关键词明确匹配车载手机支架时允许使用。

## 4. Coding JSON

`social_voice_all_history_coding.json` 必须通过 `social_voice_all_history_coding.schema.json` 和脚本跨字段校验，顶层至少包含：

- `schema_version`
- `metadata`
- `project`
- `top3_selection`
- `segments`
- `scope_definitions`
- `semantic_taxonomy`
- `funnel`
- `voices`
- `excluded_records`
- `validation`
- `limitations`

`metadata` 必须明确：

```text
mode = all_history_local_reprocess
no_network = true
date_filter_applied = false
semantic_match_rule = 六类语义任一命中（OR）
```

每条 `voices[]` 至少保存：

- `voice_id` 与 `hard_identity`
- 平台、内容/线程/父级 ID
- 作者标识、公开作者标签
- 原始发布时间和采集时间（允许为空）
- 规范化直链（允许为空）
- 短原文
- 一个或多个六语义代码
- 主题代码
- 产品语境来源与纳入理由
- `category_all_history` 和可选细分归属
- 全部发现路由

每条 `excluded_records[]` 保存 `record_id`、平台、唯一排除原因、短原文和可选日期。排除记录不得静默丢弃。

## 5. Analysis JSON

`social_voice_all_history_analysis.json` 必须从 Coding JSON 确定性汇总，并通过 `social_voice_all_history_analysis.schema.json` 与跨文件对账。顶层至少包含：

- `schema_version`
- `metadata`
- `project`
- `funnel`
- `sample_structure`
- `semantic_categories`
- `category_summary`
- `top_segments`
- `kano`
- `new_needs`
- `product_concepts`
- `validation`
- `limitations`
- `representative_voices`

Analysis 可以补充 Agent 产品方案和供给验证，但不得手填或覆盖由 Coding 重算的分母、计数和占比。

## 6. 六语义准入

可识别消费者表达必须满足产品相关、消费者表达、非广告/机器人/媒体正文/卖家促销，并至少命中以下一类：

1. `purchase_selection_recommendation`
2. `failure_complaint_return_alternative`
3. `satisfaction_recommendation_repurchase`
4. `installation_compatibility_scenario`
5. `diy_modification_workaround`
6. `feature_reverse_innovation`

`semantic_taxonomy` 必须恰好按上述六个代码各出现一次。每条纳入声音的 `semantic_codes` 必须非空、唯一且只能来自这六类。

查询 scope 不能单独证明产品相关。产品上下文只允许来自：

- 本条显式产品锚点。
- 本地已保存且明确相关的父级/根内容。
- 同一线程内多个独立作者的产品锚点达到已记录的相对比例门槛。

## 7. 硬身份与全量对账

源 task 的每条硬身份唯一记录必须被检查。只允许合并同一底层留言的重复发现：

- 同一平台内容/评论 ID。
- 明确指向同一留言对象的规范化直链。
- 同一后端可验证的确定性替代 ID。

不同 ID 即使文本完全相同、语义相同、作者相同或跨平台转载，也分别保存和计数。

必须满足：

```text
examined_records = hard_unique_records
hard_unique_records = qualified_consumer_voices + excluded_records
```

并且：

- `voices[].voice_id` 无重复。
- `excluded_records[].record_id` 无重复。
- 两组 ID 互斥。
- 两组 ID 的并集等于源 task 的全部硬身份唯一记录。

`discovered_records` 是发现关系数，可以大于硬身份唯一记录数，不能作为消费者表达分母。

## 8. 分母和比例

主分母：

```text
N_all_history = funnel.qualified_consumer_voices
```

六语义、需求、满意、不满意、场景、DIY 和创意的 `share`：

```text
share = 该项唯一 voice_id 数 / N_all_history
```

每个 Top3 细分使用其语义成员留言数作为独立分母。分母为 0 时 share 为 `null` 或 0，必须在同一文件内保持一致并由脚本校验。

同一留言可命中多个语义或主题，所以各项占比之和允许超过 1。任何占比都只能解释为“本地已抓取语料中的表达分布”，不能解释为总体市场人口比例。

## 9. 无时间筛选

`published_at` 允许缺失。早于任意日期、无日期或旧 collector 标记为窗口外的记录，都必须按正文和本地语境正常检查。

日期只允许用于：

- 原声追溯。
- 最早/最晚日期描述。
- 年份分布和无日期数量。

日期不得用于：

- 准入或排除。
- 分母或抽样上限。
- 权重、排序或 KANO。
- 生成趋势、最近窗口或跨窗口比较。

新的 Coding、Analysis 和 HTML 不得出现 `windows`、`time_window`、`within_window_records`、旧 30/90 scope 或最近子集字段。

## 10. 无置信度与 KANO

Coding、Analysis 和 HTML 不得包含：

- `confidence`、`evidence_confidence`、`sample_confidence`、`affects_confidence` 或同义分级字段。
- 高/中/低置信度标签或徽标。
- `evidence_insufficient`、证据不足或待验证作为 KANO 类型。

KANO 只允许：

- 必备型
- 期望型
- 魅力型
- 无差异型
- 反向型

无法形成方向性判断的主题直接不进入 KANO 数组。所有 KANO 仍是社媒语料方向性归纳，`formal_survey=false`，不得声称完成正式双向问卷。

## 11. 产品与供给验证

满意和不满意分别最多展示 Top10；每项保留留言数、占比、作者数、线程数、平台数和最多 3 条代表性原声。

新需求类型：

- `consumer_explicit_idea`
- `diy_workaround`
- `inferred_latent_need`
- `agent_design_concept`

`agent_design_concept` 的直接留言数和作者数必须为 0。正式“经消费者证据支持的新需求”至少需要 5 名独立作者、3 个线程、可追溯原声和失败/绕行/现有方案不足证据。

`product_concepts` 固定 3 项，包含目标消费者/JTBD/场景、证据、KANO、功能与技术、结构材料和 CMF、价格/BOM、风险依赖、验收指标、Design Thinking、MoSCoW、完整提示词和图片状态。未执行的工程、专利、法规、认证和正式问卷只能列为计划。

## 12. HTML

独立 HTML 必须：

- 单文件、UTF-8、CSS 和图片内嵌。
- 无 CDN、远程字体、相对资源、JavaScript、iframe、form 或运行时网络请求。
- 断网可完整阅读，支持桌面、移动和 A4 打印。
- 分析 SHA-256 内嵌且与输入 Analysis JSON 一致。
- 不展示来源状态、证据 ID、证据类型计数、内部字段名、旧 scope、时间窗或置信度。
- KANO 全部中文，每项洞察最多展示 3 条代表性原声。
- 明确“全历史”只指本地已采集语料，不等于互联网全量。
- 标注“AI概念表达，非工程图或认证结果”。

## 13. Manifest

最终化前校验：

- Coding 与 Analysis 的源 DB SHA-256 一致。
- 实际源 DB SHA-256 与快照一致。
- 原机会看板 SHA-256 与计划/快照一致。
- HTML 内嵌 Analysis SHA-256 与实际文件一致。
- Coding、Analysis、HTML 通过全部契约校验。

Manifest 只能原子增加或更新：

```json
{
  "artifacts": {
    "consumer_voice_all_history_coding": "<relative-path>",
    "consumer_voice_all_history_analysis": "<relative-path>",
    "consumer_voice_all_history_report_html": "<relative-path>"
  },
  "status": {
    "consumer_voice_all_history": "ready | partial | failed"
  }
}
```

既有键和 `status.market_opportunity` 不得修改。任何校验失败都必须在写入前停止，或原子恢复原文件。

## 14. 状态

- `ready`：源 task 全量检查和对账完成；两份 JSON、HTML、3 个产品方向和所需图片完整；无时间筛选/置信度残留；源 DB、机会看板和 Manifest 门禁通过。
- `partial`：全量清洗和核心报告可复算，但供给验证、产品方案或概念图存在明确缺项。
- `failed`：无法完成全量对账、无法形成任何可复算消费者表达，或核心 JSON/HTML 无法通过契约。

平台数量、日期覆盖率、旧研究档位和样本上限不参与状态判定，只作为样本结构与限制披露。
