# Amazon 商品机会深挖 Skill 指令

## 启动门槛

本 skill 是连续上下文专用入口。开始执行前必须先从当前对话上下文读取上一段 `lc_amazon_market_research` 明确输出的真实项目根目录，例如：

```text
本次项目目录：/path/to/market_project_<YYYYMMDD_HHmmss>
PROJECT_ROOT=/path/to/market_project_<YYYYMMDD_HHmmss>
```

支持继承的 Amazon 站点固定为：`US`、`UK`、`DE`、`FR`、`JP`、`AU`、`CA`、`IT`、`ES`、`MX`。站点以项目里的 `01_input_manifest.json` 为唯一依据。本 skill 不重新询问站点、不默认 US、不接受另一个站点覆盖项目；旧项目中的 `GB` 仅规范为 `UK`。

只有满足以下条件才继续：

- 当前上下文中已经出现真实 `market_project_<YYYYMMDD_HHmmss>/` 项目根目录，且不是 agent 临时猜测出来的。
- 该目录里有 `project_manifest.json` 和 `market_research/`。
- `inspect-report` 校验为 `status=ready`。

如果当前上下文没有真实项目目录，必须直接停止，不询问用户补路径，不扫描本地目录，不选择最新项目，不尝试读取原始 Excel。固定回复：

```text
商品机会深挖依赖上一段市场主报告结果；当前上下文没有可用的 market_project 项目目录，本轮不继续执行。请先完成市场主报告后，在同一上下文里继续。
```

## 输入

正常输入来自当前上下文里的上一段 `lc_amazon_market_research` 生成项目根目录：

```text
market_project_<YYYYMMDD_HHmmss>/
  project_manifest.json
  market_research/
  market_opportunity/
```

CLI 会根据 `project_manifest.json` 自动定位 `market_research/`。本 skill 的正常入口是项目根目录，不要求用户补 `market_research/` 子目录。

本 skill 不直接接收原始 Excel。`market_research/` 目录必须包含：

- `cleaned_30d_listings.json`
- `06_top90_keywords.json`
- `03_market_metrics.json`
- `01_input_manifest.json`
- `report_data.json`

如果缺少 `cleaned_30d_listings.json`，停止并说明需要先在同一上下文完成新版 `lc_amazon_market_research` 市场主报告。

后端访问配置由 CLI 自行读取。agent 只调用 CLI，不读取、不打印、不在回复中复述任何后端凭据；也不要询问或记录外部供应商接口、账号或凭据。

如果 `fetch-roots` 明确返回缺少后端 token，立即停止，不生成维度候选、不自行拆词根、不使用其他 Skill 的 token。固定回复：

```text
商品机会深挖访问配置缺失，本轮不继续执行。请补齐该 Skill 的用户访问 Token 后，在同一上下文继续。
```

这里需要的是统一后端的用户访问 Token；不要向用户询问任何外部供应商 token。

---

## CLI 入口

`tools/bin/` 只包含四个平台 CLI。按当前系统选择一个，不要调用其他平台文件：

| 平台 | CLI |
|------|-----|
| Linux | `tools/bin/market-opportunity-linux-amd64` |
| macOS Apple Silicon | `tools/bin/market-opportunity-darwin-arm64` |
| macOS Intel | `tools/bin/market-opportunity-darwin-amd64` |
| Windows | `tools/bin/market-opportunity-windows-amd64.exe` |

如果当前平台是 macOS，在首次执行 CLI 前由 agent 静默处理一次：

```bash
xattr -dr com.apple.quarantine tools/bin/ 2>/dev/null || true
chmod +x tools/bin/market-opportunity-darwin-* 2>/dev/null || true
```

Linux/Windows 不需要执行这一步。

---

## 固定流程

### 1. 检查输入目录

这里的输入目录必须来自启动门槛中识别到的当前上下文项目根目录，不得由 agent 扫描猜测。

Linux/macOS：

```bash
./tools/bin/market-opportunity-<platform> inspect-report "/path/to/market_project_YYYYMMDD_HHMMSS"
```

Windows：

```powershell
& ".\tools\bin\market-opportunity-windows-amd64.exe" inspect-report "C:\path\to\market_project_YYYYMMDD_HHMMSS"
```

确认 `status=ready` 后继续。

同时读取命令返回的：

- `marketplace`：本轮唯一目标站点。
- `listing_language`：关键词、标题和参数的主要语言。

非英语站点的维度确认和逐 listing 打标必须理解目标语言。原始关键词、标题、参数和证据保留源语言；中文看板继续使用 `display_values`。不得把英文关键词规则硬套到其他语言，也不得因为不是英语就直接放弃；先做语义判断，确实存在歧义或证据不足时才填 `不可识别`。

### 2. 创建输出目录

输出目录固定使用同一个项目下的：

```text
market_project_<YYYYMMDD_HHmmss>/market_opportunity/
```

所有中间文件、agent 文件、最终看板都写入该机会输出目录。

### 3. 获取关键词词根

必须走我们的统一后端，不得直连任何外部词根服务。agent 只调用 CLI，不需要知道后端如何获取词根，也不要询问、记录或复述任何外部供应商信息。

```bash
./tools/bin/market-opportunity-<platform> fetch-roots \
  --report-dir "/path/to/market_project_YYYYMMDD_HHMMSS" \
  --output-dir "/path/to/market_project_YYYYMMDD_HHMMSS"
```

输出：

- `02_keyword_roots.json`

计费由后端处理。agent 只需要在结果中引用 CLI 返回的 `request_count`，不要自行解释外部供应商计费。

### 4. 生成维度候选

```bash
./tools/bin/market-opportunity-<platform> dimension-candidates \
  --report-dir "/path/to/market_project_YYYYMMDD_HHMMSS" \
  --roots-file "/path/to/market_project_YYYYMMDD_HHMMSS/market_opportunity/02_keyword_roots.json" \
  --output-dir "/path/to/market_project_YYYYMMDD_HHMMSS"
```

输出：

- `03_dimension_candidates.json`
- `03_dimension_candidate_words.csv`

在进入 agent 维度确认前，必须阅读 `references/agent_workflow.md` 的“维度确认输出契约”。

CLI 只计算搜索需求分。以下分数必须由 agent 判断：

- 区分产品分
- 购买影响分
- 可打标分
- 业务可用分

维度总分公式：

```text
搜索需求分 * 35%
+ 区分产品分 * 20%
+ 购买影响分 * 20%
+ 可打标分 * 15%
+ 业务可用分 * 10%
```

入选阈值：维度得分 >= 60。最终确认 3-6 个维度，一般不要超过 6 个。

Agent 写入 `agent_dimensions.json`，格式：

```json
{
  "llm_calls": [
    {
      "call_type": "dimension_clustering",
      "input_summary": "Top90 词根和需求覆盖",
      "output_summary": "聚类为功能/痛点、材质、使用场景等候选维度",
      "is_inference": true
    }
  ],
  "dimensions": [
    {
      "name": "功能/痛点",
      "type": "multi",
      "source": "keyword_roots+agent",
      "selected": true,
      "search_demand_score": 88,
      "product_separation_score": 80,
      "purchase_influence_score": 85,
      "taggability_score": 90,
      "business_utility_score": 80,
      "dimension_score": 82,
      "reason": "Top90 词根覆盖高，标题/参数中可稳定识别，适合做供需指数。"
    }
  ],
  "rejected_dimensions": [
    {
      "name": "颜色",
      "dimension_score": 28,
      "reason": "搜索需求覆盖低且样本中难形成稳定市场分层。"
    }
  ],
  "supplemented_dimensions": [
    {
      "name": "结构/形状",
      "source": "LLM推断",
      "reason": "品类常识中可能影响坐感和安装方式，但 Top90 词根覆盖不足。"
    }
  ]
}
```

### 5. 生成打标工作区

```bash
./tools/bin/market-opportunity-<platform> tagging-template \
  --report-dir "/path/to/market_project_YYYYMMDD_HHMMSS" \
  --dimensions-file "/path/to/market_project_YYYYMMDD_HHMMSS/market_opportunity/agent_dimensions.json" \
  --output-dir "/path/to/market_project_YYYYMMDD_HHMMSS"
```

输出：

- `04_tagging_workspace.json`

Agent 基于 `04_tagging_workspace.json` 做逐 listing 打标，写 `agent_listing_tags.json`。

打标前必须阅读 `references/agent_workflow.md` 的“逐 listing 打标与归一化输出契约”。

要求：

- 一个 listing 一次性判断所有维度。
- 优先看 `title`、`params`、`category_path`。
- 文本不能判断的维度，才看 `image_url` 或 `product_url`。
- 不确定填 `不可识别`。
- 多选维度使用数组；单选维度也可以使用单元素数组，便于 CLI 统一处理。
- `values` 保存原始识别值。
- `normalized_values` 保存标准语义值，可保留英文、行业术语或接口原词，用于追溯。
- `display_values` 保存中文展示标签，是 CLI 统计、CSV 和 HTML 的唯一展示标签来源；前端不得直接展示英文 `normalized_values`。
- 必须输出 `normalization_dictionary` 和 `unrecognized_samples`，用于过程追溯。
- 必须输出每个 ASIN、每个维度的 `evidence`。证据要说明来自标题、参数、类目、图片或商品链接。
- 如果文本字段不足并实际查看了图片或商品链接，必须在 `review_summary.image_checked_count` / `review_summary.product_url_checked_count` 中记录数量；如果未查看，也必须在 `review_summary.notes` 中说明仅基于文本字段打标。
- `不可识别` 必须写入 `unrecognized_samples`，不能只在标签值里填不可识别。
- 归一化后的主要标签必须在 `normalization_dictionary` 中可追溯。
- `normalization_dictionary` 每条映射必须有 `display_value`，且 `display_value` 必须是中文展示标签。可以包含 `PU`、`USB-C` 等必要行业词，但不能只有英文原词。

格式：

```json
{
  "llm_calls": [
    {
      "call_type": "listing_tagging",
      "input_summary": "清洗后近30天 listing + 已确认维度",
      "output_summary": "逐 listing 维度标签和证据",
      "is_inference": true
    }
  ],
  "normalization_dictionary": [
    {
      "dimension": "材质",
      "raw_value": "memory foam",
      "standard_value": "memory foam",
      "upper_group": "foam",
      "display_value": "泡棉/记忆棉",
      "merge_reason": "同属泡棉材质，不改变消费者决策含义。"
    }
  ],
  "unrecognized_samples": [
    {
      "asin": "B0XXXX",
      "dimension": "材质",
      "reason": "标题、参数和图片均未提供可确认材质。"
    }
  ],
  "review_summary": {
    "primary_fields": ["title", "params", "category_path"],
    "image_checked_count": 0,
    "product_url_checked_count": 0,
    "notes": "本次未进行图片/链接复核，仅基于文本字段打标。"
  },
  "tags": [
    {
      "asin": "B0XXXX",
      "values": {
        "功能/痛点": ["lumbar support", "pain relief"],
        "材质": ["memory foam"],
        "使用场景": ["driving"]
      },
      "normalized_values": {
        "功能/痛点": ["lumbar support", "pain relief"],
        "材质": ["foam"],
        "使用场景": ["driving"]
      },
      "display_values": {
        "功能/痛点": ["腰背支撑", "疼痛/压力缓解"],
        "材质": ["泡棉/记忆棉"],
        "使用场景": ["驾驶/通勤"]
      },
      "evidence": {
        "功能/痛点": "title mentions lumbar support and pain relief",
        "材质": "title mentions memory foam",
        "使用场景": "title mentions car/driving"
      }
    }
  ]
}
```

### 6. 计算机会结果

```bash
./tools/bin/market-opportunity-<platform> analyze-tags \
  --report-dir "/path/to/market_project_YYYYMMDD_HHMMSS" \
  --dimensions-file "/path/to/market_project_YYYYMMDD_HHMMSS/market_opportunity/agent_dimensions.json" \
  --tags-file "/path/to/market_project_YYYYMMDD_HHMMSS/market_opportunity/agent_listing_tags.json" \
  --output-dir "/path/to/market_project_YYYYMMDD_HHMMSS"
```

输出：

- `07_opportunity_analysis.json`
- `feature_distribution.csv`
- `dimension_statuses.csv`
- `combo_pivots.csv`
- `formal_opportunities.csv`
- `small_sample_observations.csv`
- `市场机会深挖看板.html`

HTML 看板要求：

- 每个有效维度都显示一个维度透视图。
- 透视图必须采用“两柱一线”：`Listing占比` 和 `销量占比` 是两个柱状图，`平均销量` 是单独折线。
- 透视图只展示 `feature_distribution.csv` 已有结果，不改变供需指数、正式机会组合或打标口径。
- HTML 看板由 CLI 固定模板生成；agent 不要手改 HTML，不要在运行中临时设计新图表。前端模板调整属于开发行为，只在用户明确要求修改 skill 时进行。

`07_opportunity_analysis.json` 会保留 agent trace，包括维度 LLM 调用记录、打标 LLM 调用记录、补充维度、剔除维度、归一化字典和不可识别样本。

`analyze-tags` 会做硬校验：

- `agent_dimensions.json` 必须有 3-6 个 `selected=true` 维度。
- 每个入选维度必须有 5 项评分、总分和入选原因，且总分不得低于 60。
- `agent_listing_tags.json` 必须和清洗后 listing ASIN 一一对应，不得缺失、重复或混入额外 ASIN。
- 每个 ASIN 的每个确认维度必须有原始值、归一值和证据。
- 每个 ASIN 的每个确认维度必须有中文 `display_values`。
- `normalization_dictionary` 必须提供中文 `display_value`，且 `display_values` 必须能从归一化字典追溯。
- `不可识别` 必须进入 `unrecognized_samples` 留痕。
- 缺少 `review_summary` 或未做图片/链接复核不会阻塞，但会进入报告提醒。

---

## 7. 全历史消费者声音与产品创意开发（可选第二阶段）

仅在基础机会看板成功后执行。用户已明确要求消费者声音、KANO 或产品创意开发时直接继续；否则只询问一次。开始前完整阅读 `references/consumer_voice_workflow.md`、`references/consumer_voice_contract.md` 和两个全历史 Schema。

运行目录固定为：

```text
<PROJECT_ROOT>/market_opportunity/consumer_voice_all_history_<YYYYMMDD_HHmmss>/
```

### 7.1 数据来源

优先使用当前上下文已经明确给出的 `collector.sqlite3`：

- 只读打开，不扫描其他项目寻找数据库。
- 不执行 collector `run/resume`。
- 不调用 `last30days`、`agent-reach`、YouTube Data API、yt-dlp 或其他网络请求。
- 记录源 DB 和原 `市场机会深挖看板.html` 的 SHA-256，结束前复核不变。

只有用户明确要求首次采集、继续采集或刷新数据时，才进入采集流程。此时 collector 的 `quick/standard/deep` 只控制新增采集的预算和时长；不形成分析时间窗、样本截断、分母或状态门槛。未指定采集档位时沿用 collector 的非阻塞默认与提醒，不等待二次确认。

新采集时：

- `last30days` 只发现公开候选，其搜索能力不构成报告时间窗。
- `agent-reach` 先运行 `doctor --json`，实际深读队列中的 Reddit/X 线程，最后运行 `check-update`。
- YouTube Data API 分页抓取已发现视频的公开一级评论和回复；yt-dlp 仅作降级。
- 平台/API 失败不能中断其他平台；密钥、原始来源状态和错误串只留在采集回执，不进入用户可见 HTML。
- 采集结束后仍以源 DB 全部硬身份唯一记录为清洗输入，不使用 collector 的旧窗口资格或 v2 编码结果。

### 7.2 Top3 与项目级 Taxonomy

Top3 只从 `07_opportunity_analysis.json.feature_distribution` 选择：

- 维度 `valid=true` 且标签 `is_effective_feature=true`。
- 排除空值、其他、不可识别及同义占位项。
- `3% <= listing_share <= 20%`，边界包含。
- 按原始供需指数、Listing 数、销量占比、维度顺序和名称执行固定排序。
- 父子或同义标签先做语义去重；不足 3 个时不放宽门槛。

兼容选择命令：

```bash
python3 scripts/consumer_product_report.py select-segments \
  --analysis <PROJECT_ROOT>/market_opportunity/07_opportunity_analysis.json \
  --output <RUN_DIR>/selected_segments.json
```

随后由 Agent 依据项目核心词、站点语言、Listing 标题/参数、Top3 和抽样原声，生成 `<RUN_DIR>/consumer_voice_taxonomy.json`。结构遵循 `references/consumer_voice_taxonomy.schema.json`，至少包括产品显式词、隐式组件/场景词、六语义扩展词、可行动主题、Top3 词和 KANO 映射。

内置 taxonomy 只适用于明确识别为车载手机支架的项目。其他品类未提供项目级 taxonomy 时停止处理，不得套用错误品类词典。

### 7.3 全量清洗与六语义 OR

指定 task 下每条硬身份唯一记录都必须被检查，且最终只能进入 `voices` 或 `excluded_records`。

进入消费者表达分母必须同时满足：

- 原文非空，包含独立观点、经验、意图、问题或建议。
- 能由本条原文、已保存父级/根内容或多作者产品锚点确认与目标商品相关。
- 是消费者表达，不是品牌、卖家、媒体正文、创作者口播或新闻转述。
- 不是广告、促销、机器人、纯链接、纯转发或无新观点引用。
- 命中六类固定语义至少一类。

六类语义固定为以下六类，并采用任一命中即可纳入的 OR 规则：

1. 购买、选型和推荐。
2. 故障、抱怨、退货和替代。
3. 满意、推荐和复购。
4. 安装、兼容性和使用场景。
5. DIY、改装和绕行方案。
6. 新功能、反向需求和创意。

发布日期允许为空，只作追溯和年份分布；不得用于准入、排除、权重、排序或 KANO。旧 `within_window`、`technical_eligible`、30/90 scope 和 v2 分母不得成为新统计输入。

只合并能证明为同一底层留言的重复发现：相同平台内容/评论 ID、同一留言直链或确定性替代 ID。不同 ID 即使文本、语义或作者相同也分别计数；500 条不同留言表达同一需求，该需求计数为 500。

### 7.4 执行与确定性对账

执行：

```bash
python3 scripts/consumer_voice_local_reprocess.py \
  --source-db <SOURCE_RUN_DIR>/collector.sqlite3 \
  --output-dir <RUN_DIR> \
  --task-id <TASK_ID> \
  --selection-file <RUN_DIR>/selected_segments.json \
  --taxonomy-profile <RUN_DIR>/consumer_voice_taxonomy.json \
  --dashboard <PROJECT_ROOT>/market_opportunity/市场机会深挖看板.html \
  --prior-analysis <可选旧分析JSON>
```

输出：

```text
<RUN_DIR>/source_snapshot.json
<RUN_DIR>/social_voice_all_history_coding.json
<RUN_DIR>/social_voice_all_history_analysis.json
<RUN_DIR>/local_reprocess_receipt.json
```

必须满足：

```text
examined_records = hard_unique_records
hard_unique_records = qualified_consumer_voices + excluded_records
```

`voices` 与 `excluded_records` 的 ID 必须各自唯一、互斥，且并集等于源 task 全部硬身份唯一记录。`discovered_records` 是发现关系数，只作审计，不能作为占比分母。

主分母为 `N_all_history = qualified_consumer_voices`。六语义、需求、满意、不满意、场景、DIY 和创意都用该分母；Top3 各用自己的 `segment_*_all_history` 成员留言数。同一留言可多标签，因此各项占比之和可以超过 100%。

### 7.5 KANO、新需求与产品开发

KANO 是方向性归纳，`formal_survey=false`。用户可见类型只允许：必备型、期望型、魅力型、无差异型、反向型。无差异型必须有明确“不在乎”原声，反向型必须有明确拒绝或负效用原声。无法形成方向性判断的主题直接不进入 KANO 表。

Coding、Analysis 和 HTML 均不得包含 `confidence`、`evidence_confidence`、高/中/低徽标，或把“证据不足/待验证”用作 KANO 类型。

满意和不满意分别输出全品类 Top10 与各 Top3 主要项。每项显示留言数、占比、作者数、线程数、平台数和最多 3 条代表性原声；完整逐条证据留在 Coding JSON，不在 HTML 展示内部证据 ID。

正式“经消费者证据支持的新需求”至少需要 5 名独立作者、3 个线程、可追溯原声，以及失败、绕行或现有方案不足证据。Agent 设计创意的直接留言数固定为 0。

默认生成 3 个产品方向，每项包括消费者/JTBD/场景、消费者证据、KANO、功能与技术、结构/材料/CMF、目标价格/BOM、风险依赖、验收指标、Design Thinking、MoSCoW、完整提示词和概念图。未执行的工程、专利、法规、认证和正式问卷只能列为计划。

### 7.6 HTML、状态与 Manifest

渲染并检查：

```bash
python3 scripts/consumer_all_history_report.py render \
  --analysis <RUN_DIR>/social_voice_all_history_analysis.json \
  --output <PROJECT_ROOT>/market_opportunity/消费者声音与产品创意开发报告-全历史-<timestamp>.html \
  --concept-image <CONCEPT_ID>=<IMAGE_PATH>

python3 scripts/consumer_all_history_report.py check \
  --report <PROJECT_ROOT>/market_opportunity/消费者声音与产品创意开发报告-全历史-<timestamp>.html>
```

报告固定使用 `assets/consumer_all_history_report.template.html`：单文件、CSS/图片内嵌、无外部运行依赖，支持桌面、移动和 A4 打印。不展示来源状态、证据 ID、证据类型计数、内部字段名、旧 scope、时间窗或置信度。每项洞察最多展示 3 条代表性原声，并明确“全历史”只指本地已采集语料。

状态：

- `ready`：源 task 全量检查与对账完成；两份 JSON、HTML、3 个产品方向和所需概念图完整；无时间筛选或置信度残留；源 DB、机会看板和 Manifest 门禁通过。
- `partial`：核心全量清洗与报告可复算，但供给验证、产品方案或概念图存在明确缺项。
- `failed`：无法完成全量对账、无法形成任何可复算消费者表达，或核心 JSON/HTML 无法通过契约。

平台数量、发布日期覆盖率、采集档位和旧样本上下限不参与状态判定，只作为样本结构和限制披露。

最终化：

```bash
python3 scripts/consumer_all_history_report.py finalize-manifest \
  --manifest <PROJECT_ROOT>/project_manifest.json \
  --coding <RUN_DIR>/social_voice_all_history_coding.json \
  --analysis <RUN_DIR>/social_voice_all_history_analysis.json \
  --report <REPORT_HTML> \
  --source-db <SOURCE_RUN_DIR>/collector.sqlite3 \
  --source-snapshot <RUN_DIR>/source_snapshot.json \
  --dashboard <PROJECT_ROOT>/market_opportunity/市场机会深挖看板.html \
  --status <ready|partial|failed>
```

Manifest 只能原子增加 `consumer_voice_all_history_coding`、`consumer_voice_all_history_analysis`、`consumer_voice_all_history_report_html` 和 `status.consumer_voice_all_history`。任何校验失败都必须在写入前停止；既有键、源 DB 和原机会看板不得改变。

## 解释口径

- 供需指数 = 该标签或组合的销量占比 / Listing 数量占比。数值越大，表示样本内“销量占比相对供给占比”越强。
- 多选标签下，Listing占比和销量占比都是标签覆盖口径，不是排他市场份额，不能相加。
- 正式机会组合必须 `Listing 数量 >= 10`、`供需指数 > 1` 且销量占比达到最低展示门槛。
- 小样本观察不作为正式机会判断。
- `不可识别`、`其他`、空值不计入维度有效子维度数量。
- 有效子维度数量低于 2 的维度直接剔除，不进入组合透视。
- 这部分结果依赖 agent 打标质量，必须说明是“结构化计算 + agent 语义打标”，不能包装成纯客观数据。
- 正式机会方向不能只看供需指数最高，还要同时看样本量、销量占比、平均销量和组合是否有明确产品意义。
- HTML Top 方向按机会分展示；机会分综合样本量、销量占比、平均销量和供需指数。

---

## 交付要求

完成后必须向用户同时突出项目根目录和最终 HTML，不要只列中间 CSV：

```text
本次项目目录：
<真实 market_project_<YYYYMMDD_HHmmss> 绝对路径>

商品机会深挖看板：
<同一项目下 market_opportunity/市场机会深挖看板.html>
```

项目路径必须来自当前上下文中上一段真实项目，并经 `inspect-report` 校验；不要重新扫描或猜测。说明本次实际处理的清洗后 listing 数、最终有效维度数和正式机会组合数，并明确结果性质为“结构化计算 + Agent 语义打标”。不要启动本地 HTTP 服务。

若执行了消费者声音第二阶段，还要同时突出新的独立 HTML、四路有效留言量（仅合并同一底层留言）、Top3 名称、`ready|partial|failed` 状态及未完成项；不要把它说成对原机会看板的覆盖更新。
