# 单细分数据与业务契约（PRD v2.3）

## 原始数据与身份

源库只读，哈希核验；新派生目录保存版本。原单位保留cache_key/record_id、platform、原生ID或确定直链、原文、上下文、批次、来源回执。查询scope不是相关性证据。无可靠身份待核验，不用相同文本制造身份或合并不同发言。

同一原ID重复请求保留发现关系但声音计1；不同ID同观点/同作者均保留。视频/文章全文及分段归同一父ID，评论各计1。网页真实消费者表达计social；research_signal、Alexa、模型输出不计有效VOC。

## 处理与版本

项目taxonomy字段：profile_id、product_label、product_terms、implicit_product_terms、semantic_extensions、topics[]、segments[]、kano_mapping、required_scenarios。kano_mapping只为历史结构兼容，新模式不得用它生成KANO分类。六类语义任一命中（OR），无日期筛选，不输出置信度。

全历史、无日期过滤、六类语义OR：purchase_selection_recommendation、failure_complaint_return_alternative、satisfaction_recommendation_repurchase、installation_compatibility_scenario、diy_modification_workaround、feature_reverse_innovation。检索十类线索不是六类互斥分类。

编码方法区分rule_classified、model_reviewed，历史agent_reviewed可读取但不能伪装新复核。规则必须声明版本和作用范围，真实原文证据；未命中/否定冲突/隐含语义/新颖表达进入疑难。需求以稳定topic_code/need_id贯穿显示、统计、充分性、KANO、开发和查询；别名只改映射不减原声。

相关性include/exclude/undetermined与未完成pending区分；已解释undetermined计已处理但不计有效。任务状态和语义归类状态另记。纳入真实购买意向、外观与替代用途等，即使无工程需求。不得靠星级、一个孤立词或模板填充推断适用性/负面/KANO。

## 数量、统计和门槛

唯一原始单位=include+exclude+undetermined+pending。发现数、作者、问答、需求提及分别计，不能相加充数。

Amazon4,000、social（含网页）2,000、总数6,000均为参考目标，quantity checks标记blocking=false，无须数量豁免。完成首采、十类查漏、全部处理、质量和三个通过方向可停止。数量差额不自动触发补采。无20/5/2或饱和硬门槛。未知适用性不强填current；主要依据仅eligible=true，即有支持原声和当前适用证据。

n(d)=提及稳定需求d的不同有效原始单位数；提及率=n(d)/该分析范围有效声音数。来源/平台用各自分母；同声同需最多1，跨需可多计，占比合计可超100%。作者数按已知账号去重，匿名不虚构人数。mixed同时属于support/counter，但合计不能重复作总数。分母0显示无可用分母。

## 规则质量与上下文

Python全量处理、统计和状态保存；模型规划检索/规则、疑难复核、需求/KANO/创新。固定种子抽检规则结果5%，Amazon/social各至少50（不足全检），覆盖规则族/决定状态，重点异常另查。系统错误定位影响集合回扫后复验。

批次最多20原始单位，输入目标8,000 tokens并预留系统/输出；长文分段完整合并，不截断，不多计。核对输入输出ID、版本/哈希、标签、引文，错误不入库。保存已验收缓存；新需求全量回查后才发布数量。

## KANO、Alexa和开发

KANO仅具体need_id提及率>=3%进入Codex综合推断，低于阈值为below_threshold不入队/不展示；其余pending由模型自动完成，保存classified/insufficient/conflict/not_applicable、M/O/A/I/R、依据、反证和验证问题。每项保留source_sha256、denominator与count；证据、映射、分母变化即失效重验。禁止逐声投票、静态词典补票、Better/Worse伪问卷指标。机会分两条轨道：创新/绕行的具体need_id，以及既有需求中的明确缺陷/限制。二者均在全体有效声音中计数且>=0.5%才分析展示；不能按同中文名隐式合并，也不能让宽泛需求为具体机构借用频次。

Alexa作为选购维度、竞品声明与验证问题研究资料。全部答案有分析/无关/空白/解析失败等终态，采纳要点关联原回执及需求/维度/方向，声明标已独立核实/冲突/待核实；待核实含具体方法。对象型回答分别保存answer与recommendedProduct。重复答案可复用但保存原始返回映射；无可用答案为资料受限，不以空集合判通过。Alexa不进入任何VOC分母。

机会语义复核对全部有效 VOC 逐条执行，记录“消费者表达→希望实现的结果→候选解决机制”；每批最多20，必须有真实原文引用、复核人、输入哈希及终态。具体新需求和既有需求改进严格分轨，父主题不能向具体机制转移频次。低于0.5%的具体线索只可作为设计假设，不能伪装正式市场机会。

十二独立角色实际七阶段产物先冻结JTBD、功能与技术方案、结构、材料与外观；协议为`consumer-12-role-workshop-3.1`。六位独立发散角色各提出至少3个不同机制，先形成至少18个原始创意；架构整合为6–9个实质不同候选，每个关键结果至少保留两条机制路径。每条原始创意必须有保留、合并、淘汰或待补证据的理由。九位评审逐项评价用户收益、机制差异、普通替代方案与配件组合、取舍和验证方法；正式恰好三个方向均须通过创新评审。

KANO为VOC推断而非问卷：M/O/A/I/R必须形成“需求→KANO判断→设计策略→候选机制→采用/拒绝理由→验证”链。研究/打样版与暂定上市V1分别建立MoSCoW，KANO字母不得机械映射优先级；每项Must依赖、成本假设和验收标准必须闭合。完整商品池逐要求covered/not_covered/unknown。主对标限定销量前10%入围商品，按已确认核心特征重叠数、销量、ASIN排序；unknown不是缺失；机制新颖性另核验完整池、常见配件组合和定向公开资料。概念图提示词只能由最终冻结产物派生；每案三张概念图及资产哈希必须与冻结方案版本关联。

## 报告与完成

十章固定母版：核心结论、全量清洗、六类消费者表达、Alexa选购洞察与验证、需求与口碑、细分市场声音、KANO、双轨产品机会、三个产品开发方向、方法与限制。Alexa紧随六类表达展示。原声正文/代表留言/ID列表、十类线索执行表和独立验证路线均外置审计数据。新快照标business_rules_version=voc-prd-v2.3、methodology.prd_version=2.3；thresholds声明3%/0.5%和软数量目标。产品章节扩展决策链、候选处置、双MoSCoW及三类验证计划，但不得重做深色页头、侧导航、白卡和章节框架。各阶段状态独立，render成功不等于业务完成。具体CLI参见consumer_voice_workflow.md。
# PRD v2 机会候选约束

机会候选只取创新/绕行原声中逐需求明确标记 `novel=true` 的具体 `need_id`，再在全部有效 VOC 中按该 ID 计数；不得把同一原声同时提及的常规需求自动视为创新机会。项目 taxonomy 预设宽泛主题即使 `novel=true` 也排除，除非逐需求明确验证 `opportunity_specific=true`；模型新增具体需求不受预设主题排除，但仍须满足0.5%。无达标具体机会可以如实为空，三个开发方向仍可由有依据的基础需求优化形成。
