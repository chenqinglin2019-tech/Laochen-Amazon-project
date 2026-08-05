# 全历史消费者声音与产品创意开发工作流

本文件定义机会看板完成后的消费者声音主流程。唯一分析口径是“本项目本地已采集语料的全历史全量清洗”；发布日期不参与筛选，也不再建立 30/90 天分层、跨窗口对比或置信度等级。

## 目录

1. 启动边界
2. 数据来源与可选采集
3. Top3 与全历史 Scope
4. 项目级语义词典
5. 全量清洗和六语义准入
6. 硬身份去重
7. 分母与统计
8. KANO、满意度和新需求
9. 产品开发
10. 执行命令
11. HTML 与 Manifest
12. 质量门

## 1. 启动边界

仅在以下条件全部满足时执行：

- 当前对话中存在经 `inspect-report` 验证的真实 `market_project_<YYYYMMDD_HHmmss>/`。
- `market_opportunity/07_opportunity_analysis.json`、`市场机会深挖看板.html` 已生成。
- `project_manifest.json.status.market_opportunity=ready`。
- 用户已明确要求消费者声音、KANO、产品创意或产品开发，或在机会看板完成后确认继续。

继承项目站点、`listing_language`、核心词、类目和 Top3，不重新询问或覆盖。全历史只表示“本项目本地已经抓取并落盘的全部可用记录”，不表示穷尽互联网、平台私有数据、已删除内容或未发现帖子。

执行前读取：

- `references/consumer_voice_contract.md`
- `references/social_voice_all_history_coding.schema.json`
- `references/social_voice_all_history_analysis.schema.json`
- `references/consumer_voice_taxonomy.schema.json`
- 本轮明确需要调用的采集 Skill 指令

## 2. 数据来源与可选采集

### 2.1 已有本地语料

当前上下文已经明确给出源 `collector.sqlite3` 时，直接只读处理该数据库：

- 不执行 `run` 或 `resume`。
- 不调用 `last30days`、`agent-reach`、YouTube Data API、yt-dlp、浏览器搜索或其他网络请求。
- 不扫描项目或其他目录猜测数据库。
- 不修改源 DB、旧运行目录、旧报告或原机会看板。

### 2.2 首次采集或刷新

只有用户明确要求首次采集、继续采集或刷新数据时，才使用 `consumer_voice_collector.py` 获取候选。若用户未指定采集档位，按既有规则直接用 `quick`，同时非阻塞提醒还可选择更耗时的 `standard` 或 `deep`；不得等待二次确认。

采集档位只限制本轮新增数据的数量预算和运行时长，不属于分析口径：

- 不以采集档位上限截断已经落盘的本地语料。
- 不用发布日期决定最终纳入。
- 不把 collector 的旧 `within_window`、`technical_eligible` 或 v2 分母作为 v3 统计输入。
- 采集结束后仍对源 DB 中该 task 的全部硬身份唯一记录逐条检查。

工具分工：

- `last30days` 只负责公开内容候选发现；其工具名称和搜索能力不构成报告时间窗。
- `agent-reach` 负责重点 Reddit/X 帖子与可访问回复树深读，先运行 `doctor --json`，完成后运行 `check-update`。
- YouTube Data API 负责已发现视频的公开一级评论和回复分页；日期只保存为元数据，不用于 v3 准入。
- yt-dlp 仅作 YouTube 的 best-effort 降级。

新采集无法证明互联网全历史覆盖。最终报告必须披露发现渠道、平台分布、缺日期比例和最大线程/视频贡献率，但不得把来源运行状态或内部错误串放进用户可见报告。

## 3. Top3 与全历史 Scope

Top3 只从 `07_opportunity_analysis.json.feature_distribution` 产生：

- 所属维度 `valid=true`。
- 标签 `is_effective_feature=true`。
- 排除空值、其他、不可识别及其同义占位项。
- `0.03 <= listing_share <= 0.20`，边界包含。
- 按原始 `supply_demand_index`、Listing 数、销量占比、维度顺序和名称执行固定排序。
- 父子或同义标签先做语义去重；候选不足 3 个时不放宽门槛。

分析 Scope 固定为：

- `category_all_history`
- `segment_1_all_history`
- `segment_2_all_history`
- `segment_3_all_history`

查询命中只记录发现来源，不能直接证明细分归属。`segment_memberships` 必须由留言正文或已确认的本地父级语境判断。同一留言可属于多个细分，因此细分占比不可相加。

## 4. 项目级语义词典

每个品类生成 `<RUN_DIR>/consumer_voice_taxonomy.json`，结构遵循 `consumer_voice_taxonomy.schema.json`。词典至少包含：

- 产品类别名称和显式产品词。
- 组件、安装部位、典型场景等隐式产品锚点。
- 六类固定语义的目标语言扩展词。
- 可行动主题的稳定 `topic_code`、中文名称和匹配词。
- Top3 的 `segment_*_all_history` 匹配词。
- 可形成方向性 KANO 的主题映射。

所有词条使用目标站点语言，并可补充语料中实际出现的其他语言。Agent 必须结合项目关键词、Listing 标题/参数、Top3 和抽样原声复核词典。不得把车载手机支架的产品词、主题或细分规则用于其他品类。

内置词典只作为明确车载手机支架项目的回归配置。其他品类缺少 taxonomy 时停止处理，并要求先生成项目级词典；不能静默使用错误品类规则。

## 5. 全量清洗和六语义准入

源数据单位是指定 task 下按硬身份唯一化后的帖子、评论或回复。每条记录都必须得到且只能得到一个最终结果：进入 `voices` 或进入 `excluded_records`。

进入消费者表达分母必须同时满足：

- 原文非空，是独立观点、经验、意图、问题或建议。
- 能通过本条原文、已保存父级/根内容或达到门槛的多作者产品锚点确认与目标产品相关。
- 是消费者表达，不是品牌、卖家、媒体正文、创作者口播或新闻转述。
- 不是广告、促销、机器人、纯链接、纯转发或无新观点引用。
- 六类语义至少命中一类。

六类固定语义为：

1. `purchase_selection_recommendation`：购买、选型、比较和寻求推荐。
2. `failure_complaint_return_alternative`：故障、抱怨、退货、退款、替换和寻找替代。
3. `satisfaction_recommendation_repurchase`：满意、基于使用经验主动推荐、再次购买和复购。
4. `installation_compatibility_scenario`：安装、位置、兼容性、操作和实际使用场景。
5. `diy_modification_workaround`：DIY、改装、自制、修补和绕行方案。
6. `feature_reverse_innovation`：新功能愿望、明确不想要的属性、负效用和创意。

六类是 OR 关系。一条留言可命中多类，每类最多计一次；“寻求推荐”归第 1 类，“有使用经验后主动推荐”归第 3 类。

`published_at` 可为空。日期只用于追溯、年份分布和描述性时间跨度，不参与准入、排除、权重、排序或 KANO。

## 6. 硬身份去重

只允许以下同一底层留言合并：

1. 同一平台内容/评论 ID 精确相同。
2. 规范化留言直链明确指向同一内容对象。
3. 同一后端的确定性替代 ID 可验证映射到同一留言。

文本哈希相同、语义相近、同一作者重复表达、跨平台转载、父评论引用或共享线程 URL 都不是去重键。500 条不同留言都表达“需要更强固定”，该需求计数就是 500；同一留言被多个查询发现时联合分母只计一次，并保留全部发现关系。

## 7. 分母与统计

主分母固定为：

```text
N_all_history = qualified_consumer_voices
```

所有需求、满意、不满意、场景、DIY、创意和六语义占比均使用该分母。每个 Top3 的占比使用其 `segment_*_all_history` 成员留言数作为独立分母。

报告至少对账：

- `discovered_records`：发现关系数，只作采集审计，不作占比分母。
- `hard_unique_records`：硬身份唯一记录数。
- `examined_records`：全量检查数，必须等于硬身份唯一记录数。
- `qualified_consumer_voices`：进入消费者表达分母的留言数。
- `excluded_records`：排除数及原因。
- 平台、作者、线程、社区和年份分布。
- 最大平台、最大线程/视频贡献率和作者识别覆盖率。
- 六语义各自的留言数、占比、作者数、线程数和平台数。

必须满足：

```text
hard_unique_records
= qualified_consumer_voices + excluded_records
```

同一留言可命中多个主题，所以主题占比和六语义占比之和可以超过 100%。所有比例只描述本地语料结构，不能解释为市场人口概率、渗透率或美国消费者总体比例。

## 8. KANO、满意度和新需求

KANO 是社媒消费者表达的方向性归纳，固定 `formal_survey=false`。用户可见类型只有：

- 必备型
- 期望型
- 魅力型
- 无差异型
- 反向型

无差异型必须有明确“不在乎、不影响选择”的原声；反向型必须有明确拒绝、隐私/复杂度/安全负效用或“宁愿不要”的原声。没有足够方向性依据的需求直接不进入 KANO 表，不创建“证据不足”“待验证”或高/中/低等级。

满意与不满意分别输出全品类 Top10 和各 Top3 的主要项。每项显示留言数、留言占比、作者数、线程数、平台数和最多 3 条代表性原声；完整逐条证据留在 Coding JSON，不在 HTML 展示内部证据 ID。

新需求分为：

- 消费者明确创意。
- DIY 或绕行方案。
- 从重复痛点推导的潜在需求。
- Agent 产品设计创意。

前三类统计真实留言；Agent 创意的直接留言数固定为 0。正式称为“经消费者证据支持的新需求”仍至少需要 5 名独立作者、3 个独立线程、可追溯原声，以及失败、绕行或现有解决方案不足证据。未完成供给验证时只能称“供给缺口假设”。

## 9. 产品开发

默认生成 3 个产品方向，优先各绑定一个可用 Top3，并吸收全品类共性需求。每个方向包含：

- 目标消费者、JTBD 和使用场景。
- 全历史消费者证据及对应六语义/KANO。
- 功能、技术方案、结构、材料、颜色和表面处理。
- 目标价格、BOM 假设、风险、依赖和量化验收指标。
- `Empathize / Define / Ideate / Prototype / Test / Iteration`。
- `Must / Should / Could / Won't this release`。
- 完整概念图提示词、概念图及“AI概念表达，非工程图或认证结果”声明。

没有实际完成访谈、打样、道路测试、专利检索、法规/认证或正式 KANO 问卷时，只能写成后续计划。

## 10. 执行命令

Top3 可暂时使用旧报告工具中独立、无报告副作用的选择命令：

```bash
python3 scripts/consumer_product_report.py select-segments \
  --analysis <PROJECT_ROOT>/market_opportunity/07_opportunity_analysis.json \
  --output <RUN_DIR>/selected_segments.json
```

随后生成 `consumer_voice_taxonomy.json`，执行全量清洗：

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

这一步必须以 SQLite 只读模式打开源 DB，并生成：

```text
<RUN_DIR>/source_snapshot.json
<RUN_DIR>/social_voice_all_history_coding.json
<RUN_DIR>/social_voice_all_history_analysis.json
<RUN_DIR>/local_reprocess_receipt.json
```

生成并检查报告：

```bash
python3 scripts/consumer_all_history_report.py render \
  --analysis <RUN_DIR>/social_voice_all_history_analysis.json \
  --output <PROJECT_ROOT>/market_opportunity/消费者声音与产品创意开发报告-全历史-<timestamp>.html \
  --concept-image <CONCEPT_ID>=<IMAGE_PATH>

python3 scripts/consumer_all_history_report.py check \
  --report <PROJECT_ROOT>/market_opportunity/消费者声音与产品创意开发报告-全历史-<timestamp>.html>
```

## 11. HTML 与 Manifest

HTML 固定复用 `assets/consumer_all_history_report.template.html`：

- 单文件、UTF-8、CSS 和图片全部内嵌。
- 无 CDN、远程字体、相对资源、脚本、运行时网络请求或外部渲染依赖。
- 支持 1440、768、390 像素和 A4 打印。
- 不展示来源状态、证据 ID、证据类型计数、内部 scope、内部字段名或任何置信度。
- 不展示研究档位、采集上限或旧时间窗作为分析分母。
- 每项洞察最多展示 3 条代表性原声。

最终化命令：

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

只允许增加或更新：

```text
artifacts.consumer_voice_all_history_coding
artifacts.consumer_voice_all_history_analysis
artifacts.consumer_voice_all_history_report_html
status.consumer_voice_all_history
```

## 12. 质量门

`ready` 必须同时满足：

- 源 task 的全部硬身份唯一记录均被检查。
- `voices` 与 `excluded_records` 互斥、无重复，且并集等于源硬身份唯一记录。
- 六语义分类、主题、分母、计数和占比可从 Coding JSON 自动复算。
- 不因日期缺失或早于某天排除任何记录。
- Coding、Analysis 和 HTML 不含置信度字段/展示、旧时间窗字段或“证据不足”KANO。
- KANO 只使用五种中文类型。
- 3 个产品方向和所需报告板块完整；概念图失败则保留提示词并标记 `partial`。
- 两份 JSON、离线 HTML、源 DB SHA-256、原机会看板 SHA-256 和 Manifest 增量更新全部校验通过。

已完成全量清洗但产品方案、供给验证或概念图缺失时为 `partial`。无法完成全量对账，或没有形成任何可复算消费者表达时为 `failed`。平台数量、发布日期覆盖率和采集档位不再决定状态，只作为样本结构与限制披露。
