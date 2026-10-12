# 单细分全历史 VOC 工作流

## 1. 输入与检索计划

先完整阅读input_contract.md及consumer_voice_collection.md，冻结单细分完整输入，不重算上游。
```bash
python3 scripts/single_segment_contract.py --input INPUT.json --output-dir RUN
python3 scripts/consumer_voice_collector.py plan --run-dir RUN --single-segment-input INPUT.json
```
INPUT的search_plan须根据完整关键词由Agent生成三个互补表达；没有计划时planning_required，不机械取前三。新输出目录禁止覆盖旧快照。正式采集执行前沿用config.json本地鉴权和各供应商.env，认证逻辑不变。

## 2. 自动协作采集

主Agent读取并实际调度agent-reach及last30days，按RUN/agent_reach_queue.json中的任务执行，保留真实回执。不是collector隐式启动收费子进程；不能仅创建planned任务就说完成。网页消费者原声计social，研究资料单列。last30days的来源窗口不影响全历史处理。适配器导入RUN/agent_reach与RUN/last30days的明确records文件；不要将工具摘要当原文。

Amazon先前5，各最多1,000原始唯一评论ID；具体证据缺口才依序扩展至前50。社媒试采200。4,000评论/2,000社媒/6,000总数仅参考，达到可暂停扩量，未达可进入分析。成功页持久化先于游标推进，不确定收费失败不重发。Alexa冻结前5ASIN/前10关键词，问答单列。参见flyfus_v5.md。

`scripts/demand_insight_v5.py single-segment-progress --input PROGRESS.json --output NEXT.json`计算参考进度/下一评论批次；输入含sampling_plan、amazon_valid、social_valid、completed_asins、current_batch_processed、processing_complete、quality_passed、gap_check_recorded，以及实际通过方向数量和evidence_gap。字段以当前--help及实现为准。数字必须来自本轮验收统计，不能手填候选数冒充有效数。

## 3. 全量规则、疑难复核和质量

```bash
python3 scripts/consumer_voice_local_reprocess.py \
  --source-db RUN/collector.sqlite3 --task-id TASK \
  --selection-file RUN/selected_segments.json --taxonomy-profile TAXONOMY.json \
  --rule-config RULES.json --output-dir INSIGHT_V1
```

只读源库，新目录输出。已交接原机会看板时传`--dashboard ORIGINAL.html`保护哈希，未交接不阻碍运行。全历史、六类语义任一命中（OR）、无日期筛选、不输出置信度：
purchase_selection_recommendation、failure_complaint_return_alternative、satisfaction_recommendation_repurchase、installation_compatibility_scenario、diy_modification_workaround、feature_reverse_innovation。

RULES按references/voc_rule_config.example.json创建真实品类规则；示例只有购前询问，不足以覆盖整个市场。Python输出明确规则结果、agent_coding_queue.jsonl、review_batches.json及quality_review_queue.json。规则未命中不排除，冲突/隐含/新颖表达进疑难。批次最多20，输入目标8,000 tokens并预留其他上下文；长记录完整分段合并。不发全部6,000正文给同一上下文。

模型按每批原文/上下文、taxonomy版本和缓存键复核，用`--agent-coding REVIEW.jsonl`回填但编码方式写model_reviewed；rule_classified不冒充Agent。可传`--coding-cache CACHE.json`复用匹配哈希结果。拒绝漏ID、多ID、不存在的引文和不完整分段。

独立质量回执通过`--quality-review QUALITY.json`导入：taxonomy_sha256、results_sha256、reviewer、reviewed_cache_keys、open_issues。results_sha256绑定全批已验收结果；同一原文的编码决定改变后，旧回执失效。覆盖脚本抽检清单、问题为0且绑定当前结果才能通过；不要未复核便填通过。规则结果5%且Amazon/social各至少50（不足全检），不同规则族和异常增加样本。发现系统错误修规则/全量回扫并重验。

场景查漏通过`--single-segment-gap-fill GAP.json`保存status、rounds及实际查询/来源/结果，覆盖十类线索。首采、全量处理、质量闭环、查漏及三个方向通过即可停止，数量不用豁免。Codex自动执行全部复核批次并回填至pending为0；undetermined须实际复核且有理由，保留为已审证据不足。20/5/2或三批饱和只作观察。

质量回执的`open_issues`为未闭环问题的整数数量，完成时必须为0；问题明细另存`open_issue_details`数组，不能以空数组替代数量字段。回执必须绑定当前taxonomy与results哈希，且覆盖抽样cache_key集合。

## 4. 需求、KANO与Alexa

从Python精确统计与完整原声索引按需求做证据包；稳定need_id贯穿。模型解释相关性、适用场景、任务/障碍/后果/替代，未知字段不补造。不同原始声同观点不合并，作者单独统计。

### 4.1 固定的消费者语义总结

在KANO前，对所有 `eligible=true` 需求固定执行一次逐需求语义总结。它不是把频次换一种说法：Codex须阅读当前证据包，归纳消费者在什么场景受阻、想达成什么结果、造成何种后果，以及该需求的可设计边界。每项输出都必须绑定输入指纹与真实证据ID；没有足够证据时写明资料不足，不能从商品定义或设计方案反推消费者动机。

```bash
python3 scripts/consumer_all_history_report.py prepare-need-summaries \
  --analysis INSIGHT_V1/social_voice_analysis.json --output NEED_SUMMARY_INPUT.json

# Codex 按 need_id 分批处理（每批最多20项）后，导入一个
# consumer-need-semantic-summaries-1.0 文件：need_id、source_sha256、summary、
# need_statement、evidence_ids、review_version。
python3 scripts/consumer_all_history_report.py import-need-summaries \
  --analysis INSIGHT_V1/social_voice_analysis.json --semantic-summaries NEED_SUMMARIES.json \
  --output ANALYSIS_WITH_NEED_SUMMARIES.json
```

单文件HTML对每个主要依据固定按此顺序展示：**消费者声音语义总结 → 对应需求的具体描述 → 证据使用边界**。替代解释、逐条原声、完整引文和适用性判定明细继续写入审计产物，不进入报告正文。重跑后若证据指纹变化，旧总结必须失效并重新生成。

KANO仅具体need_id提及率>=3%进任务，Codex完整读取证据/反证后综合判断，不能逐声投票或拿愿望直接判魅力。提交consumer-need-judgments-1.0的needs：need_id、status（classified/insufficient/conflict/not_applicable）、classification、rationale、review_version、evidence_ids、counter_evidence_ids、applicable_scenarios、validation_questions及source_sha256。脚本保留count/denominator；below_threshold不进任务。重跑传--prior-analysis，只有相同证据指纹可复用结论。机会采用严格具体新需求/绕行与既有需求改进双轨，各自按stable need_id全量统计并以0.5%筛选；不将宽泛需求的频次挪给具体机制。所有比例分母为全部有效VOC。

```bash
python3 scripts/consumer_all_history_report.py prepare-qa-analysis --run-dir RUN --output QA_RECORDS.json
python3 scripts/consumer_all_history_report.py import-insights \
  --analysis INSIGHT_V1/social_voice_analysis.json --need-judgments NEEDS.json \
  --qa-records QA_RECORDS.json --qa-analysis QA_ANALYSIS.json --output ANALYSIS_V2.json
```

QA_ANALYSIS schema consumer-qa-analysis-1.0，每条records含record_id、question_summary、answer_summary、claim_kind、conflict_check、next_verification、review_version、need_ids、buying_dimensions、unknown_conditions、evidence_quotes。`disposition` 为 adopted/irrelevant/parse_failed/insufficient；仅 adopted 须关联需求或选购维度，其余仍须有实际处理理由与真实引文，在报告中隐藏但计入处理数量。空回答单列 `empty_records`，不能计为有用洞察。问题/答案绑定真实回执与强校验source_sha256。研究资料不进VOC/KANO票数；导入只是结构/引文验真，模型必须实际读答案后分析。

## 5. v2.3 实际工作坊、概念图与报告

读取consumer_product_development.md，prepare→十二独立角色七阶段→register-roles/validate-stage→完整池competition_audit→finalize。同一角色可续回合，不能一个Agent模拟十二人；未实际执行不交付虚构回执。v2.3先运行`consumer_opportunity_recheck.py prepare`，由Codex按最多20条一批逐条回查并用`import-results`验证全覆盖；每项回执必须回传输入的`record_source_sha256`，再用`consumer_voice_v22_enrich.py`生成新的 v2.3 Analysis 和统一需求登记。新需求先进入该登记、统计、语义总结和 KANO，再进入产品开发；不得复用旧主题标签声称完成机会复核。

v2.3六名发散角色各至少三条独立机制（总数至少18）；架构师先形成6–9个实质不同候选，再交九名评审。所有原始想法必须有处置理由，所有评审必须有用户收益、机制差异、普通替代方案与配件组合、取舍和验证结论。KANO证据包必须逐需求给出分类、反证、场景、适用性和验证问题；工作坊把M/O/A/I/R转成具体设计策略，不能按字母机械选择功能。每案分别输出研究/打样与暂定上市V1的MoSCoW，Must依赖必须闭合。

先由工作坊冻结每案JTBD、完整任务流、KANO决策链、功能与技术方案、结构、材料与外观；正式恰好三个通过创新评审的方向，不足返回修订，功能证据、机制、代价、BOM假设和三类测试计划齐全。

按销量前10%先筛主对标候选，再按冻结核心特征重叠、销量、ASIN选出一案一品；unknown不是功能缺失。每案形成“竞品已有设计→需求依据→我方升级→预期改善→取舍→测试”矩阵，涉及机制、竞品或关键判断变化时必须复评。

概念图使用Image Gen：产品整体、关键结构/升级机制、使用场景各一张。生成提示词逐项引用同一工作坊冻结的JTBD、功能与技术方案、结构、材料与外观；后两张使用首图作为参考。图像保存新运行目录，哈希写入`concept_image_assets`，渲染时内嵌；仅标为概念示意。

报告固定使用 HTML 1.5.0，先按 `consumer_report_layout_contract.md` 执行 `prepare-report-copy --analysis <冻结开发分析> --output <摘要包>`；Codex读取每案产品、竞品与反证，填入面向运营/开发的短摘要，然后用 `import-report-copy --analysis <冻结开发分析> --presentation <已完成摘要包> --output <新的展示分析文件>`。摘要独立存于顶层 `report_presentation`，绑定每案产品及竞品指纹，不改已冻结的 `product_concepts` 或工作坊回执。导入仅验收结构与来源，不能冒充实际语义审查。

`scripts/consumer_all_history_report.py render --analysis <展示分析文件> --output <报告>` 直接使用 `assets/consumer_all_history_report.template.html`；完整交付加 `--final`。十章节、侧导航、深色页头和白卡保持，Alexa紧随六类表达；清洗漏斗先于Amazon/站外四张数量卡。每案功能证据、KANO链、双版本MoSCoW和六步过程均桌面两列、窄屏单列；任务与成本在图前，整体图独占一行，另两图默认折叠；竞品短卡紧接对应方向，三案后展示运营/开发行动清单。主要依据仅eligible。原声正文、角色名字/空阶段状态、长篇对标审计和ID不在HTML展示；完整审计保留。只显示所选细分，所有数量和指标由本轮数据读取，不复用样例。执行现有报告测试及离线校验，浏览器可用时检查桌面/手机展开布局与打印。

每阶段分别标记：采集、处理、疑难/质量、需求KANO、Alexa内容、工作坊、竞品、验证计划、HTML。未完成如实阶段性，不把渲染成功等同正式研究完成。来源hash与上游hash检查在交付前通过。

页面中的非阻断数量检查标为“参考目标已达/未达（不阻断）”，不能用“未通过”暗示交付失败。Alexa展开项优先使用已有need_ids；只有buying_dimensions时用明确的展示别名表归档，未匹配名称原样保留，不另行按词语猜类别。多维度回答可重复归档，维度数量不可相加，原始处理总数独立展示。新版本不再显示旧V5汇总缺失造成的“未执行Alexa”提示。
