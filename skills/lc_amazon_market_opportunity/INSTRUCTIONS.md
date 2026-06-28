# Amazon 商品机会深挖 Skill 指令

## 启动门槛

本 skill 是连续上下文专用入口。开始执行前必须先从当前对话上下文读取上一段 `lc_amazon_market_research` 明确输出的真实项目根目录，例如：

```text
本次项目目录：/path/to/market_project_<YYYYMMDD_HHmmss>
PROJECT_ROOT=/path/to/market_project_<YYYYMMDD_HHmmss>
```

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

CLI 会根据 `project_manifest.json` 自动定位 `market_research/`。为了兼容旧产物，也可以接受当前上下文中已经明确出现的 `market_research/` 输出目录；但不要在缺少上下文时要求用户补目录。

本 skill 不直接接收原始 Excel。`market_research/` 目录必须包含：

- `cleaned_30d_listings.json`
- `06_top90_keywords.json`
- `03_market_metrics.json`
- `01_input_manifest.json`
- `report_data.json`

如果缺少 `cleaned_30d_listings.json`，停止并说明需要先在同一上下文完成新版 `lc_amazon_market_research` 市场主报告。

后端配置由 CLI 从环境变量或本机私有 `config.json` 读取；这是访问我们后端的凭据，不是上游词根服务账号、key 或 token。

- `LAOCHEN_BACKEND_URL`：默认 `https://mcp.yixunkuajing.com`
- `LAOCHEN_BACKEND_TOKEN`：访问我们后端的 token。开发测试目录可以放在本机私有 `config.json`；面向用户交付的包不要内置 token。agent 不要读取、打印或在回复中复述该 token。

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

### 2. 创建输出目录

如果输入是 `market_project_<YYYYMMDD_HHmmss>/`，输出目录固定使用同一个项目下的：

```text
market_project_<YYYYMMDD_HHmmss>/market_opportunity/
```

如果输入是旧式 `market_research/` 目录，则在当前工作目录创建 `market_opportunity_<YYYYMMDD_HHmmss>/`。所有中间文件、agent 文件、最终看板都写入机会输出目录。

### 3. 获取关键词词根

必须走后端，不得直连上游词根服务。agent 只调用 CLI；CLI 会从环境变量或本机私有配置读取我们后端的访问凭据。agent 不需要知道上游供应商凭据，也不要询问、记录或复述；上游凭据只存在服务端。

```bash
./tools/bin/market-opportunity-<platform> fetch-roots \
  --report-dir "/path/to/market_project_YYYYMMDD_HHMMSS" \
  --output-dir "/path/to/market_project_YYYYMMDD_HHMMSS"
```

输出：

- `02_keyword_roots.json`

计费口径：当前按后端实际成功请求词根服务的 batch 数计次。Top90 关键词通常一个 batch 即一次请求；如果后续确认上游按关键词收费，再调整后端和用户计费配置。上游凭据只在服务端，不进入 skill。

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
