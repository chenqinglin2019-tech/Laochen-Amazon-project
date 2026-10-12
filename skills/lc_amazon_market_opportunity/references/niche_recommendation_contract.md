# Top3 粗筛与进一步分析契约

本契约定义 `niche_recommendation.py` 的独立推荐层。规则版本为 `niche_recommendation_v10_dual_source_robust`，输出 schema 为 `5.0.0`。它只在原 `analyze-tags` 成功后运行，不改变原 CLI、鉴权、API、API Key 填写／读取／校验、二进制、市场研究产物或原机会评分。

“全量”指用户提供的数据全集，不代表整个亚马逊市场。不得新增商品抓取、调用飞鱼 API、重清洗商品、执行 VOC 或产品开发。

## 1. 输入、阶段与冻结

先执行：

```bash
python3 <SKILL_ROOT>/tools/niche_recommendation.py prepare \
  --project-root <PROJECT_ROOT> \
  --poe-xlsx <USER_PROVIDED_POE_XLSX>

python3 <SKILL_ROOT>/tools/niche_recommendation.py shortlist \
  --project-root <PROJECT_ROOT> \
  --poe-xlsx <USER_PROVIDED_POE_XLSX> \
  --definitions <NICHE_CANDIDATE_DEFINITIONS_JSON>
```

辅助命令：`status --project-root <PROJECT_ROOT>`（只读阶段路由）；`validate --project-root … --poe-xlsx … --definitions …`（一次列出全部定义错误，记录轮次，不写推荐产物）。

`prepare`只写工作区（商机表行、可用标签、多维组合候选与 `combo_review_template`），不生成推荐。Agent 完成商机表需求定义、多维组合审核、direct 核心词归属和必要补标后运行 `shortlist`；`run` 是 `shortlist` 兼容别名。初筛直接选出最多 Top3，冻结候选 ID 和排名、需求边界、主商机行、完整核心词、完整成员、原始输入指纹和报告哈希，并把商机表与候选定义复制到 `market_opportunity/frozen_inputs/`（第二轮只读这份副本，原文件移动或删除不影响）。

用户随后提供每个冻结市场各 2 个 Excel（Top3 时共 6 个）：每个冻结市场 1 份细分市场关键词转化表与 1 份卖家精灵关键词表（顺序不限），再执行：

```bash
python3 <SKILL_ROOT>/tools/niche_recommendation.py refine \
  --project-root <PROJECT_ROOT> \
  --shortlist-result <PROJECT_ROOT>/market_opportunity/niche_shortlist.json \
  --keyword-input-xlsx <ONE_CONVERSION_AND_ONE_SELLERSPRITE_XLSX_PER_FROZEN_MARKET> \
  --conversion-period <UNIFIED_PERIOD_IF_NOT_IN_WORKBOOK>
```

`refine` 只接受当前项目的成功 v10 粗筛结果，且验证回执、运行 ID、哈希、项目 ID、规则版本与 `target_k=3`。产品、标签、多维分析结果（07）、完整关键词、商机表、定义、基础报告或实现变化后必须重跑粗筛。进一步分析必须继承同一 Top3 ID 和顺序，不允许额外候选、重排或淘汰。

## 2. 候选池与候选定义

候选市场有两类来源，进入同一套评分与选择：

1. **商机表细分市场**：Agent 逐行处理商机表（`poe_row_dispositions` 覆盖每一行，取值 `direct_need`／`brand_navigation`／`accessory`／`other_use`／`ambiguous`，`direct_need` 必须关联候选），把直接需求翻译成标签条件。
2. **多维打标组合**：脚本从 `07_opportunity_analysis.json` 的正式机会组合按机会分取前 20 个组合核心（"优先复核方向"Top10 必含）。生成规则：
   - "未体现X""未特别强调X"等缺失类取值从组合中剥离，剥离前供需指数最高的变体保留为"切入点提示"；
   - "泛X"类取值按"带X（任意）"处理，即该维度任一具体取值均可；
   - 含"不可识别"取值或有效条件超过 3 个的组合跳过并留痕；
   - 与某个商机表候选条件完全相同的组合并入该候选（来源记为"商机表+多维组合"），不再单列。

候选定义文件（`--definitions`）为 JSON 对象：

| 字段 | 说明 |
|---|---|
| `project_id` | 可选；存在时必须与项目一致 |
| `poe_row_dispositions[]` | `row_number`、`disposition`、`reason`、`candidate_ids` |
| `candidates[]` | 商机表候选：`id`（小写字母数字、`_`、`-`）、`name`、`definition`、`task`、`selection_constraint_reason`、`demand_status`（`established`／`pending`）、`dedupe_group`（唯一）、`exclusive_with`（双向；元素为候选 id，或 `{"id": …, "reason": 互斥依据}`，依据会显示在冲突原因中）、`tag_expression.any_of[].all_of[]`（每个 OR 分支 1—3 个 `{dimension, values}`，不得使用不可识别或缺失类取值）、`poe_matches[]`（`row_number`、`relationship`=`exact`／`partial`／`none`、`reason`）、可选 `primary_poe_row_number`、`keyword_assignments[]`（`keyword`、`type`=`direct`／`extended`／`ambiguous`、`reason`，关键词必须在完整关键词表中） |
| `combo_reviews[]` | 对 `combo_review_template` 中每个未并入商机表的组合审核一次：`id`、`decision`（`keep`／`drop`，`drop` 必须写 `reason`）、可选 `name`、`task`、`reason`、`keyword_assignments[]` |

最小示例见 `tests/test_dual_source_pool.py` 的 `build()` 与 `review()`。

## 3. 数据边界与校验

- 商机表工作表为`细分市场列表`，必需列只有`细分市场名称`和`细分市场分类1`。商机表的搜索量、销量、点击集中度、新品数等只作需求证据与风险参考，不参与评分：其销量只是商品在该细分市场前 20 个搜索词的搜索结果页上产生的销量，不是商品总销量，不能用来衡量商品集合的规模或覆盖度。
- 需求证据：商机表候选需要 `exact` 主行或有搜索量的 `direct` 核心词；多维组合必须有有搜索量的 `direct` 核心词，否则只能作候补。每个正式候选还必须至少 10 个完整匹配有效 ASIN、至少一条正月销量、稳健供需指数 ≥1.0，且四项粗筛分数齐备。
- `direct` 核心词完整满足需求边界，`extended`和`ambiguous`不参与核心词集合。不能用泛词、附件词、品牌导航词或商品占比扩充规模或成员。
- 每份用户转化表必须含关键词、点击量、购买量及统一统计周期；可选站点若存在必须与项目一致。规范化只统一大小写与空白；不得跨期累加，且必须满足 `0 ≤ 购买量 ≤ 点击量`。不进行关键词语义相关性识别或筛除；只有同时有转化数据和卖家精灵建议竞价的关键词进入广告计算（见 §5）。
- 每份卖家精灵表必须含关键词、`PPC竞价`、`流量占比`和`Asin`工作表。每个 Asin 集合必须与一个冻结细分市场 Top20 ASIN 完全一致（不足 20 个时按实际数量）；文件数必须为冻结市场数的 2 倍；每份转化表必须与其卖家精灵累计流量占比前90%关键词至少80%精确重叠。任一一对一匹配并列、缺失或不达阈值均拒绝猜测。
- 所有冻结输入、新卖家精灵表与新转化表均保留来源行、指纹、文件关联与排除原因。单文件参数 `--keyword-conversion-xlsx`（曾用项目关键词表竞价）已停用。两类表分工固定：关键词转化表（如 `关键词-20260905-….xlsx`）只取关键词、点击量和购买量，表内“最高出价／最低出价／建议出价”等出价列一律忽略；建议竞价只取自卖家精灵关键词反查表（如 `ExpandKeywords-US-<ASIN>-batch(20)-….xlsx`，以含 `Asin` 工作表识别）的 `PPC竞价` 列。

## 4. 粗筛：四项评分并直接选 Top3

粗筛权重是供需指数 **80%**、竞争开放度 **10%**、新品进入证据 **5%**、需求承接规模 **5%**，所有候选（商机表与多维组合）都按本品类商品样本计算，口径一致。每项先计算 0—100 分，再加权；不存在广告压力分、关键词转化率分或趋势分。

1. 稳健供需指数：母集固定为原始品类有效商品全集。先从本市场与母集同时去掉本市场月销量前 3 个 ASIN，计算 `(q/Q)/(n/N)`，再按 `(n×指数+20×1.0)/(n+20)` 向品类平均收缩（n 为去掉头部后的商品数）。0／0.8／1／1.2／1.4／1.6／1.8 对应 0／30／50／70／80／90／100 分，区间线性插值，1.8 以上封顶。原始指数与去掉的头部 ASIN 同时留痕。稳健指数低于 1.0 的候选不能正式推荐，只能作候补。
2. 竞争开放度：本市场前 5 商品月销量占比与前 5 已知品牌月销量占比，各自 ≤20% 得 100 分、≥90% 得 0 分，中间线性，两者取平均。
3. 新品进入证据：本市场 360 天内上架的商品为新品，进入本市场月销量前 20% 的新品为成功，公式为 `50 + (100×成功数/新品数−50)×新品数/(新品数+5)`。新品数为 0 表示证据不足。
4. 需求承接规模：在本轮可比候选中，本市场月销量（60%）与 direct 核心词月搜索量（40%）分别取平均名次百分位后合成。

搜索增长和退货率只显示风险，不能降低排名或阻止入选。初筛不读取、匹配或计算任何竞价／广告指标。

**去重**：两个候选共有商品的月销量占较小市场月销量 ≥50% 时视为同一需求，不得同选；候选定义中声明的 `exclusive_with` 同样不得同选。选择器先最大化无冲突市场数量（最多 3），再最大化总分；同分优先竞争开放度，再以稳定 ID 决定。少于 3 个时如实输出，不放宽正式门槛。

**候补**：正式市场不足 3 个时，从未入选且与所有已选市场（含已选候补）都不冲突的候选中补足到 3 个，写入 `backup_candidate_ids`，按缺失评分项数量升序、总分（不完整时用下限分）降序、竞争开放度降序、ID 排序。候补不进入 `selected_candidate_ids`，只在 `niche_shortlist.json` 中记录 `backup_rank` 与具体未达标原因（如“完整匹配 ASIN 仅 8 个，低于正式门槛 10 个”）；候补不进入进一步分析、CSV 和报告。

## 5. 进一步分析与八项结论

进一步分析不产生第二套综合分，也不改变冻结成员与 Top20。它针对固定 Top3 的每个市场，使用其完整成员中价格与月销量均为正的有效商品（被剔除商品写入 `refined_product_evidence.excluded_products`）、已关联转化表全量关键词与配对卖家精灵表独立计算：

- 参与词：转化表中点击量>0 且 0≤购买量≤点击量、并在配对卖家精灵表中有唯一正 `PPC竞价` 的关键词。缺转化数据或缺建议竞价的关键词整行忽略（同时不进入转化率和加权CPC），不用关键词表推荐竞价等其他来源补齐。
- 90天转化率 `C=Σ参与词购买量/Σ参与词点击量`；加权CPC `B=Σ(参与词点击量/Σ参与词点击量×PPC竞价)`；广告压力 `A=B/(本市场商品算术均价×C)`。零购买但有点击和竞价的词照常参与。没有参与词、参与词没有购买或商品均价无效时广告压力无法判断；不设覆盖门槛。
- 八项结论只使用本市场完整成员：评论依赖性、评分值依赖性、价格敏感度、最值得进入价格带、新品打造周期、商品垄断度、品牌垄断度、广告压力指数。前七项使用原市场研究的分箱、前 10% 与稳定并列规则；无可判定区间或字段时显示依据和“无法判断”。少于 50 个有效商品标低置信度。

**进入建议／风险等级**（只作提示，不改变排名或成员）：风险旗标为商品垄断度、品牌垄断度或广告压力达“较高”及以上，广告低覆盖，有效商品少于 50 个，近90天与180天搜索量均下降≥20%，以及候补身份；0 个为低、1—2 个为中、≥3 个为高。八项中有 2 项及以上无法判断或广告压力无法判断时建议“证据不足，先补数据”；否则风险高或候补为“谨慎进入，需差异化验证”，风险中为“可进入，关注所列风险”，风险低为“建议优先进入”。结果只写入 08 中每个市场的 `entry_advice`，不在报告展示。

**广告低覆盖**：参与词点击量占转化表全部有效点击量低于 60% 时，`ad_cost_evidence.low_coverage=true` 并写入 `coverage_note`；只记录在数据中，不在报告展示，不设门槛，不改变广告压力计算。

每个市场单独记录 `deep_analysis_status`。全部市场的所有八项证据就绪时 manifest 为 `refined_ready`；任一市场存在数据缺口时为 `refinement_pending`，但已完成的其他结论及固定 Top3 保留可读。

## 6. 产物、报告与验收

粗筛输出：`niche_shortlist.json`、`niche_shortlist_keywords.json`、`niche_shortlist_memberships.json`、`niche_shortlist_core_keywords.csv`、`niche_shortlist_top20_asins.csv`、`niche_shortlist_run.json`、`市场机会深挖看板-两轮初筛.html`。`niche_shortlist.json.selected_candidate_ids` 是唯一正式 Top3 名单和排名来源，`backup_candidate_ids` 是唯一候补来源。

进一步分析输出：`08_niche_recommendations.json`、`09_niche_keyword_assignments.json`、`10_niche_product_memberships.json`、`niche_top20_asins.csv`、`niche_rule_conclusions.json`、`niche_recommendation_run.json`、`市场机会深挖看板-两轮复评.html`。08 必须保留绑定粗筛的正式与候补 ID、顺序和四项分数；不得把它解释为重新选择的 Top3，也不得把候补当作正式推荐。

两份 HTML 都从原报告的“正式机会组合明细”之后、`h2#small`之前添加 owned 区域；原报告字节不变，重跑不重复插入。Top20 按有效月销量降序、同销量 ASIN 升序，复制按钮只复制当前榜单的 ASIN，每行一个；剪贴板受限时显示并选中只读文本供手动复制。

回执记录阶段、运行 ID、粗筛绑定、输入指纹、成功状态、Top3、各市场进一步分析状态、产物哈希和耗时。粗筛失败写 `shortlist_failed`，进一步分析失败写 `refine_failed`；历史成功产物只能阅读，不能冒充本轮交接。
