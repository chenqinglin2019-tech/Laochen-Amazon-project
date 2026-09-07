# 2.4 数据与审阅契约

新任务同时绑定 `workflow_correction_revision=workflow-correction-v1`；作用域摘要、统一补充加载、必要审阅、提交恢复以及 `core-risk-evidence-v2/compact-evidence-v1` 数据增量集中见[纠错契约](workflow-correction.md)。下文原修订用于兼容历史；新记录不得沿用失效的旧摘要或回执。

采集流程使用 `task.schema_version=2.4-free`、`free_policy_revision=automation-first-v1`；评级另以 `assessment_policy` 分派。新任务默认 `evidence-estimate-v1`，历史任务缺少该字段时继续旧行为。`2.3-free` 的计划、来源选择和旧报告分支保留；新建仅 2.4，测试工具可创建 2.3 fixture，不能将历史任务改版本迁移。

新任务另写 `screening_revision:recall-integrity-v1`。该修订绑定产品分析、路由和阶段性报告语义，审阅 digest 包含此字段；无修订历史任务使用原合同。不要给旧任务补标记后覆盖旧结果，重新排查创建新目录。

## 任务和计划

`task.json` 保存 product、images、query_terms、target_jurisdictions、coverage_requirements、execution_policy、checkpoints。product 包含 input_role、structure、assets、image_coverage；图片保留实际路径、source_url、MIME、尺寸和 SHA-256。

`query_terms[]` 由 Agent 生成，包含 value、kind、derived_from，以及需要时的 language、scheme。常用 kind：structural_feature、category、product、function、brand、ocr、translation、synonym、owner、applicant、ipc、cpc、locarno、nice、phonetic、original_japanese、reading、romaji。分类必须是有效分类，不用代码冒充普通词查询；字段不受接口支持时记录缺口。

严格修订还支持 design、inventor、uspc 与 `strategy:boolean|phrase`。词条来源指向产品字段、图片或实际候选/证据；外观使用独立的 design 词，不用结构/营销段落代替。`product.analysis={status:confirmed,identity_sha256:...}` 的摘要由 `workflow_v24.product_identity_digest(product)` 计算，绑定 ASIN、变体、采集内容和媒体身份；身份变化使分析过期。`product.raw_capture` 保留原始采集事实，与 Agent 的 structure/assets/query_terms 分离。

新建任务另写 `recall_planning_revision=identity-discovery-v1`，计划须匹配此字段。`workflow_v24.product_clue_inventory(task)` 返回实际有内容的结构、已采形状及 OCR 线索；`product.analysis.clue_dispositions[]` 对每条保存 `source_path、source_sha256、disposition、reason`。`disposition=mapped` 另有 `query_term_sha256[]`，值为 `common.sha256_json` 对当前完整原始词条计算的摘要；`excluded` 须说明该线索为何不进入查询。未知或空采集字段不制造映射义务。制造商词用 `kind=manufacturer`，只作身份发现，不转换为 owner。修订、原始术语和补搜决定加入新任务审阅摘要；无修订历史输入的摘要不变。

`product.patent_claim_followup={status:completed,evidence_ids:[...],findings:...}` 表示已经追踪过商品声明；引用仍需校验真实证据，completed 不证明专利类型、权属或有效性。未解决处明确写入 findings，不编造案号。

`coverage_requirements[]` 按国家和权利拆分；phase 为 official_recall、candidate_verification 或 provenance。检索 requirement 另外规定 required_axes、required_language、expansion_required；同类合格来源可替代，不要求全部可选 API 都联网成功。要求使用固定构建器生成，不能删要求来获取低风险。

`search-plan.json.queries` 按 provider 存储操作。每行包括全局唯一 query_id、operation、jurisdiction、right_type、requirement_ids、required_for、wave、derived_from、execute_by_default、实际请求参数，以及 search_dimension、search_language、execution_phase、publication_scope。query_id 绑定请求语义；整行 SHA-256 同时绑定其元数据。计划只追加，不能为补信息重写已经执行的行。

商业免费发现行的 required_for 固定 discovery_only、requirement_ids=[]、authoritative_for_final_rating=false。EPS 文献的 required_for=comparison、jurisdiction=EP、requirement_ids=[]，不会冒充某国现行状态。asset_provenance 为 Agent 来源/素材比较证据，非登记库 API。

## 来源与证据

`source-capabilities.json` 区分 automatic、access_verification_only、unvalidated、unavailable；可尝试真实调用的 unvalidated API 仍须通过其身份、免费条件和响应契约检查。线上验收必须保留具体来源、时间、操作、实际响应与边界；单元测试不充当线上验收。

`evidence.json.source_runs[]` 保存 run_id、query_id、plan_entry_sha256、requirement_ids、provider、operation、jurisdiction、right_type、status、脱敏请求、raw_paths、payload_digest、时间、错误码和配额信息。对应 collections 的 evidence 记录携带同样的计划与范围绑定；缺少或不匹配的哈希不满足发布条件。

状态限定 success、no_result、not_applicable、needs_user_action、access_limited、failed。no_result 必须明确成功且响应结构有效并确实为零；错误 JSON/XML、空异常 envelope、超时、429、登录页和不完整页面不是零结果。

检索统计在 `source_run.metadata.search_coverage`：

- total_hits、retrieved_hits、reviewed_hits；未知总量必须 null。
- schema_valid、truncated、stop_reason、source_updated_at；不知源更新时间保持 null，不用抓取时间替代。
- 视来源记录 range_start/range_end、page/page_size、position，以及浏览器实际页数/结果稳定性。

reviewed_hits 不能由 API 猜测；最终覆盖用归一化候选和 materiality ledger 实际审阅计算。分页总量一致、页段可确认、取得去重记录与实际候选审阅覆盖总量，才可称该查询系列完整；25/500、未知排名总量、限额停止都属于截断。

浏览器另外保存 `capture_provenance.query_execution`（回执路径、哈希）、Agent 自动操作、计划 hash、页面状态与截图 hash。用户通过登录验证之后仍由 Agent 发起查询；人工 attest 或手工 capture 不能满足 2.4 执行证据。

新 PPS 文本捕获和归一化记录显式带 `text_evidence_revision:retained-text-v1`，其 `document_retrieval` / `published_document` 同样带此标记。CDP 回执绑定原 capture 的 `rendered_text_stage:source`；录入先校验该回执与文本，再统一脱敏为 `retained` 阶段。`text_hash_algorithm:sha256-canonical-json-utf8` 表示 `rendered_text_sha256` 始终绑定本阶段实际文本的 canonical JSON 字符串 UTF-8 字节（不是裸文本字节）；`source_rendered_text_sha256` 与 `source_rendered_text_stage:source` 保留同算法的清洗前绑定，不替代留存文本校验。重复处理须幂等，阶段、算法、哈希或摘要与全文不一致均拒绝。新正文不把普通 `basic and` 当凭据；真实 Basic base64 user:pass、Bearer 及敏感 Header/键值/XML/URL 仍脱敏。无标记历史继续原清洗和证明规则，不补标记、不重算、不猜回 `[redacted]`。摘要只来自真实独立标题（包括 `ABSTRACT OF THE DISCLOSURE`），没有标题不能伪造摘要；已存精确全文可交 Agent 阅读，不代表摘要已取得或现行状态已核实。

## 候选和素材

`normalized-candidates.json` 保留 patents、trademarks、copyright_assets、enforcement 集合。候选字段包括 candidate_id、right_type、jurisdiction、号码、来源、evidence_refs、verification_refs、material/disposition、territorial_effects、right_state、comparison_elements、unresolved_issues、exclusion_basis。

right_type 包括 patent、utility_model、design、trademark_word、trademark_figurative、copyright、trade_dress、unregistered_design。enforcement 作为补充信号，不与当前侵权等级混算。候选状态 active/pending/expired/unknown 需要证据；原始 kind code 不能单独决定现行状态。

无 `decision_workflow_revision` 的历史任务仍由 `annotate_materiality.py` 将 material/excluded 判断写入 1.0 append-only ledger。新任务使用下述 2.0 三类分流合同，不能用启发式 material=true 代替实际审阅。

## 情景与三类分流：scenario-triage-v1

任务显式保存 `decision_workflow_revision:scenario-triage-v1`、`primary_scenario_id` 和 `assessment_scenarios[]`。情景包括 scenario_id/type/title、适用行为与假设 assumptions、事实来源 fact_sources、conditional 和 scenario_sha256；摘要变化使依赖判断失效。仅竞品 URL 的 product.input_role 为 reference_product，主情景 product_entry；brand_reuse 是独立条件情景，适用文字/图形商标；genuine_resale 需要 request.genuine_resale 明确开启。实际产品确认须有可追溯依据。

新 `materiality-annotations.json` 使用 schema_version 2.0。annotation 按 candidate_id/scenario_id/jurisdiction/right_type 定位，包含 annotation_id、decision（selected/not_selected/needs_info）、reason、reviewer、annotated_at、evidence_refs、reading_level、basis_summary、reopen_conditions，以及 candidate_identity_fingerprint、product_identity_sha256、scenario_sha256、candidate_content_sha256、basis_sha256。缺记录或旧依据失效为 unreviewed 工作状态，不是第四种已完成决定。

- reading_level 如 result_record、abstract、independent_claims、drawings、full_document，须如实反映已读资料，不由脚本猜测。证据与判断理由均须足以支持该分流。
- needs_info 额外要求 missing_information 和 next_actions；source_lookup 动作声明 action_id/purpose/provider/operation/params/max_attempts:1。用户独有资料或专业判断可用 user_information/professional_review 与 question，不把 Agent 可执行的查询转交用户。
- 只有当前有效 selected 可生成深入核验、权利人及分类扩展。material/disposition 是台账兼容投影；priority_signals 不授予执行权。not_selected 无五级评级义务，也不构成法律反证。
- 内容摘要绑定实际身份、保护文本、相关图及情景；重复获取、路径或抓取时间改变不重开。实质新增资料只重开受影响决定；同族公开申请与后续授权不得共享排除判断。

计划行保存 decision_workflow_revision、scenario_id/scenario_sha256 或共享召回的 scenario_bindings；候选衍生行再绑定 triage_decision_id/triage_decision_sha256、triage_candidate_id/triage_jurisdiction。action_purpose、evidence_obligation_id 标明动作目的与必要义务，needs_info 另有 triage_action_id。这些字段参与 query_id/计划哈希，不发送给外部接口。

`action_substitutions[]` 绑定 old_query_id/old_plan_entry_sha256、new_query_id/new_plan_entry_sha256、jurisdiction/right_type、scenario_id/scenario_sha256、action_purpose、reason、reviewer。只有同范围同目的、真实完整且合格的新结果才满足原义务；拒绝自替代、循环及哈希不符。撤销写入 execution_dispositions，保留旧计划字节。调度器和单动作入口统一重查当前分流及撤销状态。

版权/未注册权利无需登记号。`record_asset_provenance.py --task-dir DIR --query-id QRY --input FILE` 的 input 包含 jurisdiction、right_type、candidate_id（范围审阅可为空）、reviewer、source_url 或 source_document、ownership_or_source_reasoning、artifacts（path/sha256/bytes/role）、unresolved。来源不是可读网页时引用真实源文件和许可材料。完整资产盘点还需 `coverage_attestation={asset_ids:[...],reviewed_asset_ids:[...],inventory_complete:true}`。旧合同与 task.product.assets 对齐；`asset-scope-v1` 与该情景的实际适用资产对齐，具体用途、分类不适用、步骤/事实分离及证据门槛集中见 [trademark-copyright.md](trademark-copyright.md)。不完整清单仍为缺口，参考照片不自动产生摄影许可义务。

## 历史策略的两轮审阅

以下审阅与发布门禁保留给没有 `assessment_policy` 的历史任务。新策略结构见下节。

first-review.json / second-review.json 使用以下结构，由 Agent 完成：

```json
{
  "reviewer": "independent-agent-id",
  "review_context": {"session_id": "unique-session", "evidence_digest": "digest", "first_review_visible": false},
  "assessments": [],
  "future_applications": [],
  "enforcement_signals": []
}
```

digest 是 `assessment_v24.review_digest(evidence,candidates,ledger,plan,task)`，连同 task 中的产品、图片、目标国家与覆盖要求计算；任一输入变化即重新审阅。两轮 reviewer/session 不同且第二轮不见首轮意见。

每个 assessment 包含 jurisdiction、right_type、candidate_id、risk、evidence_confidence、reasoning、evidence_refs、right_state、right_state_evidence_refs、comparison、confidence_basis、findings。风险无法判断可引用不足原因；中高风险必须有具体候选和 findings，finding 包含 finding_id、title、evidence_refs、recommended_action。

comparison.criteria 每项使用 criterion、result、reasoning、evidence_refs；result 为 supports_risk、excludes_risk、unknown、not_applicable。所有权利的实际必需 criterion 名由 `assessment_v24.CRITERIA` 定义，详见 risk-rules.md。comparison.unresolved 保留所有未解决问题。

专利还需 claims：每项 claim_id、claim_evidence_refs、elements；要素包含 claim_element、claim_quote（原文要素引句）、product_feature、result、evidence_refs、product_evidence_refs（单独绑定实际产品证据）。必要视图放 comparison.visual_coverage：required_views、product_views、right_views；两侧视图元素为 view、evidence_refs、artifact_sha256，分别绑定实际产品图和权利媒体。

confidence_basis 的 identity、scope、status、product、comparison 各为 satisfied、reasoning、evidence_refs。不能写没有来源的百分比。未来申请、维权信号均有 reasoning 和 evidence_refs，独立于当前侵权评级。

## 历史策略的结论和产物

assessment 使用 `SCOPED-IPR/1.0`。assessments[] 各自有 risk、evidence_confidence、confidence_gaps、coverage、publication、publication_gaps、authoritative_evidence_refs。publication 为 confirmed_scoped 或 discovery_only，overall.known_scoped_risk 表示已确认的局部最高风险；未完成全部范围时 overall.risk 留空。

五项报告：report-data.json、report.html、report.md、report-findings.csv、report-manifest.json。延续离线版八段 DOM 和哈希清单；report-data 是唯一展示模型。`validate_run.py` 重建结论及视图模型、校验计划/证据/媒体哈希、链接和离线产物，不能通过手写报告绕过门禁。


## evidence-estimate-v1 审阅与主审

策略定义见 [risk-estimate-rules.md](risk-estimate-rules.md)。两轮审阅各保留 `reviewer`、`review_context={session_id,evidence_digest,first_review_visible:false}` 和 `assessments`；两轮 reviewer/session 必须不同，第二轮不得读取首轮结论。旧审阅文件不能直接覆盖为新意见；重评产出新的审阅和主审记录。

`risk` 的数据枚举为 `极低、低、中、高、极高`，`evidence_confidence` 与 `coverage_confidence_cap` 为 `低、中、高`。每个纳入范围的 assessment 必须提供：

- 身份与等级：`jurisdiction`、`right_type`、`candidate_id`、`module_id`、`title`、`risk`、`evidence_confidence`、`scope`。
- 正反依据：`supporting_evidence`、`counter_evidence`，每项含 `reasoning`、`evidence_refs`；空数组分别需要 `no_supporting_evidence_reasoning` 或 `no_counter_evidence_reasoning`，不能以空字段假装完成比较。
- 推论与把握：`reasoning`、`assumptions`、`confidence_reasoning`、`evidence_refs`。`reasoning` 解释为什么选此等级及为何不更高/更低；原始状态未知留在事实层。
- 后续条件：`human_checks`、`raise_if`、`lower_if`；核查项使用 `action` 与 `reviewer`，或详细对象 `priority、owner、question、evidence_needed、raise_if、lower_if`；也接受含核查对象和适合核查者的完整文字。无需进一步核查时给出理由。
- 极低风险另需 `decisive_exclusion={reasoning,evidence_refs}`，绑定决定性排除证据。

新策略使用 `assessment_object=product|own_brand` 区分评价对象，省略时默认 product；`unknown_own_brand` 自动归 own_brand。双审、主审定位和 `task.assessment_scope_exclusions` 均精确到对象。已查产品文字与未知自有品牌可在同一国家/权利类型下并列；后者不拖低产品判断置信度，也不能代替产品文字的实际清查。

未知且未纳入评价的自有品牌或 Logo 使用 `out_of_scope:true`、`risk:null` 及 `scope_reasoning`，明确标为范围排除，不显示为风险结论。`future_signal` 和 `enforcement` 是独立补充，不混入当前总评。

审阅文件另有 `coverage_confidence_cap` 及 `coverage_confidence_reasoning`，说明哪些检索或素材范围缺口可能影响总体判断；该字段限制总置信度，不机械改变单项风险等级。

主审文件为 `adjudication`：包含 `reviewer`、`review_context={session_id,evidence_digest}` 及 `decisions`。每个 decision 是完整最终 assessment，并增加 `adjudication_reasoning` 和 `review_refs={first,second}`；引用值分别为两轮文件规范 JSON 的 SHA-256。主审记录采用或不采用双方依据的理由，而非仅写“取中间值”。

若主审主张总体极低，还须提供 `overall_decisive_exclusion={scope,reasoning,evidence_refs}`，明确整体而非单件排除范围。只有总体裁决而无逐项 decisions 时，在主审顶层提供 `review_refs={first,second}` 绑定实际双审文件；整体置信度调整同样受此绑定。

新策略审阅 digest 绑定原 `assessment_v24.review_digest` 的全部输入、策略及补充证据清单。源文件错误、产品混用、引用缺失、哈希不符仍导致验证失败，不能通过调低置信度放行。

## 显式重评与真实补充证据

### 可信外部案号入库

`record_candidate_lead.py --task-dir DIR --input FILE` 是显式的已知原文线索入口，不是搜索或官方登记适配器。当前仅支持 strict 2.4 任务中的美国 patent/design 公开号（含 kind code）；已完成任务与旧任务只读。先把实际阅读的原始文献登记在本任务 evidence 或 supplemental 清单，再导入。

输入结构：

```json
{
  "schema": "IPR-CANDIDATE-LEAD/1.0",
  "publication_number": "US<准确公开号及kind>",
  "jurisdiction": "US",
  "right_type": "patent",
  "title": "原文标题",
  "product_identity_sha256": "当前产品身份摘要",
  "source_registration": {"kind": "supplement", "manifest": "supplemental-evidence.json", "evidence_id": "EV-原文"},
  "document": {"path": "任务内原文路径", "sha256": "真实文件摘要", "bytes": 1, "source_url": "https://原始来源"},
  "review": {"reviewer": "agent-id", "reviewed_at": "带时区时间", "number_location": "原文页码与字段", "number_quote": "包含准确案号的短摘录", "content_verification": "agent_read_original", "reasoning": "与产品对应的依据及限制"},
  "publication_relations": []
}
```

示例为字段说明，不能直接作为业务输入。原登记须有准确 `publication_number`、原文 kind 及匹配的国家/类型/文件/URL；`kind=evidence` 时省略 manifest。摘录是 Agent 阅读记录，不是系统自动证明 PDF 内容。来源路径必须在本任务内，导入及每次合并/评级都会重验原登记、产品身份、文件大小和哈希。

写入 `evidence.collections.candidate_leads`，不伪造 `source_runs`、搜索命中或官方回执。合并后保持 `unreviewed、right_state=unknown、authority_scope=published_document_only`；经正常 materiality 审阅后才生成号码核验动作。相同导入幂等，冲突不覆盖。原文支持同申请关系时，先在原登记的 `publication_relations` 写准确号码和 `relation=prior_publication|same_application`，导入关系再包含 `location、quote`；不从相似标题猜同族，不自动建立未登记的另一件文献。导入引用的原登记此后不可原地改写，新增证据追加独立条目。

`--supplement` 接收独立补充清单：`schema`、`evidence[]`、`coverage_notes[]`；schema 使用非空版本名，推荐 `IPR-EVIDENCE-SUPPLEMENT/1.0`。每条 evidence 包含 `evidence_id`、`path`、`sha256`、`bytes`、`kind`、`checked_at`，以及真实 HTTP(S) `source_url` 或实存原文 `source_document` 至少一项。相对路径从 `--evidence-root` 解析（默认原 task-dir）；绝对路径和 source_document 也必须在该根目录内，本地声明及历史意见不能伪造网页 URL。`checked_at` 带时区；若表示本轮留存文件哈希核验时间，须标明 `checked_at_meaning=retained_file_hash_verification`，用 `source_checked_at` 保留原取证日期，不把重新核验描述为新查询。逐文件核对真实哈希和大小，查询日期与源更新时间不得混用。

补充证据具有独立身份，不冒充原 adapter 的已执行查询、不伪造 PPS/ODP 回执、不改原计划行。清单变化影响新的审阅绑定，不修改既有冻结记录。原始来源记录继续保持实际成功、失败、截断等状态。

`scenario-triage-v1` 可将 `kind=historical_source_reuse` 登记于同一补充清单，复用经过校验的原始来源事实。`task.historical_evidence_root`、补充清单 `evidence_root` 与显式根目录必须一致；该根目录纳入审阅摘要。条目以原 `evidence.json` 的 path/sha256/bytes 绑定留存字节，`historical_source` 绑定原 task/plan 文件、run_id、query_id、完整计划行哈希和全部 evidence_ids；`reuse_binding` 绑定新产品身份、scenario_id/scenario_sha256、国家、权利类型、action_purpose、reviewer 与理由。

TSDR 的归一化 raw 可能按既有脱敏规则移除 URL 片段；此时可追加 `historical_source.capture={path,sha256,bytes}` 指向旧任务内完整原始 capture。必须与 raw 共享同一回执，除已知 URL/CDP 会话脱敏转换外内容全等，并用旧计划重新验原回执；不得拼接、补写或重绑旧执行。产品 `analysis.clue_dispositions.source_path` 是由实际字段及 source_sha256 验证的定位符，不当作文件路径；其他文件边界和哈希校验不放松。

产品身份只排除规格栏精确字段 `Best Sellers Rank`、`Customer Reviews` 的波动；结构、尺寸、材质、图像等变化仍触发复审。合格 TSDR 明细按同 candidate/serial/国家/权利与来源时间补齐注册号及商品服务，缺失截断标记保留 unknown，不自动宣称完整；`goods_services_truncated` 的实质变化也进入分流重开摘要。

复用器逐动作核对原始回执、文件、完整性、实际来源日期和外部参数等价，只有原动作最新且完整的合格结果能满足对应义务。动态证据沿用配置中的时效限制；公开原文只用于保护内容，不能证明当前权属或效力。旧截断、过期结果、候选身份重映射、未支持的多查询分页合并不能通过复用消除缺口。原始候选事实可以重新进入本轮候选池，但必须重新分流；不得复制旧意见、制造新 source_runs，或将事实复用算作本轮盲测召回。

同任务已执行的 `needs_info` 动作失去调度权限后，其合格事实不随之失效：当前目标仍为有效 selected、同 candidate/准确号码/国家/权利且外部参数一致时，可只读重验原计划、原 run/EV、原始 capture/回执、文件哈希及证据时效后满足必要登记义务。当前仅支持完整 US TSDR；缺状态、非真实来源、错身份或篡改均不获信用。归一化 raw 的 URL 片段问题仅允许在原任务内有界定位同 query 的完整原 capture，并执行上述已知转换与原回执验证，不拼接字段。覆盖与调度共用此校验，输出 `fact_reused/not_submitted/source_query_performed:false` 及原 query/run/EV/hash/date，绝不改绑回执、重发失效动作或新增 source_runs；精确绑定且已留存的美国原始 PDF 只满足 `document_content`，不满足当前效力或召回义务。

评级可引用上述完整历史核验对应的原 EV，但 `retained_source_record` 包装本身没有官方证据资格。必须与本轮重新验证的 `historical_reuse` 逐项核对原任务、原 entry SHA、源文件 SHA/字节、原日期、完整 payload、候选与情景，才可作为正证或反证；仅文件哈希、旧报告意见或同族关联均不足。合法复用不应把已审候选重置为 pending，也不制造新来源执行记录。

候选与补充原文的 EV 编号不必相同，但实质比较必须有精确身份绑定。对经过本地文件校验的 `patent_document/design_drawings`，仅在 `authority_scope=published_document_only`、国家、权利类型和完整公开号一致时允许绑定；保留 kind code，不能按标题、部分数字、申请号或同族关系替代。哈希只证明留存字节一致，原文号码与保护内容仍需实际阅读。该绑定仅供内容比较，不补齐检索覆盖，也不证明当前效力。

现有 `2.4-free` 历史输入按以下入口显式重评；task、plan、evidence、candidates 必须同属该 schema。`--output-dir` 必须是新的目录，原 task-dir 只作输入。2.1/2.2/2.3 继续原分支，本入口未提供跨 schema 迁移；不能改版本号绕过校验。新任务默认策略不需要再次传 `--assessment-policy`。

```bash
python scripts/finalize_assessment.py --assessment-policy evidence-estimate-v1 --task-dir /absolute/original-run --first-review /absolute/reassessment/first-review.json --second-review /absolute/reassessment/second-review.json --adjudication /absolute/reassessment/adjudication.json --supplement /absolute/reassessment/supplement.json --evidence-root /absolute/evidence-root --output-dir /absolute/reassessment/output
python scripts/build_report.py --task-dir /absolute/original-run --output-dir /absolute/reassessment/output --report-content /absolute/reassessment/report-content.json
python scripts/validate_run.py --task-dir /absolute/original-run --output-dir /absolute/reassessment/output
```

`--supplement` 和 `--evidence-root` 用于存在真实补充资料的场景；仅原任务证据的重评省略它们。`--report-content` 用于补充模板正文/图证，不代替评级或产品身份；普通构建可省略。build/validate 根据输出 assessment 的 `assessment_policy` 自动分派，不修改旧 schema_version。

展示内容的 `product_facts` 只能与冻结 `task.product` 一致；主图须匹配 `task.product.main_visual` 或 task.images 中已冻结主图的路径与哈希。lead/summary 来自 canonical overall；范围来自 `task.product.report_scope/intended_use`；模块置信度上限由 `adjudication.module_confidence_caps` 裁决。展示文件必须已登记于任务/证据，来源 URL 必须与登记值绑定，不能为同一文件换成未登记网址。旧宽松输入若不满足新校验，应修复输入后在新目录重评，不回退策略规避，也不改旧导出原件。

## 新策略结论与报告

新策略结论合同为 `EVIDENCE-ESTIMATE/1.0`。每个纳入评价的最终项均有五级 risk 和三级 evidence_confidence。总体 `overall` 包括 `risk`、`confidence`、`drivers`、`reasons`、`coverage_confidence_cap`、`provisional:true`、`all_scope_clearance:false`；`drivers` 追溯最高适用当前风险，未纳入范围及补充信号不参与聚合。没有覆盖整个未知权利空间的“清白”字段推断。

仅 `recall-integrity-v1` 且无 decision_workflow_revision 的历史任务保留整体未就绪时 `overall.risk:null` 和 `overall.known_scoped_risk` 行为。两种合同的阶段性项均可用 `risk:null,assessment_status:pending,pending_reasoning` 保留事实；pending 不是 out_of_scope 或第六级风险。无候选低风险仍需 search_comparison={reasoning,evidence_refs}，绑定已完成的同国同权利召回与比较。

`scenario-triage-v1` 两轮及主审的每个判断再绑定 scenario_id/scenario_sha256；不能把跨情景判断当作评级分歧合并。scenario_confidence_caps 按情景声明摘要、confidence、reasoning、evidence_refs，避免全局缺口重复压低已核实单项。专利实施方案和独立权利项合同集中见 [评级规则](risk-estimate-rules.md)。

新合同 `overall.risk` 是主情景有证据支持的当前风险预判，`status/business_completion` 独立表示工作状态。scenario_summaries 分别呈现各情景的风险、置信度及分流/必要核验/必要召回完成度，条件情景不参加主情景最大值。有效的局部中高风险在 incomplete 时仍保留；只有局部排除不能外推全情景低风险。未入选与已审未来申请不算当前漏评；未审、待补充、真实截断和缺失必要证据仍算工作缺口。

新修订 CSV 的 `assessment_status` 与 JSON 相同，表示已有当前预判或待评（assessed/pending）；`assessment_completion` 单独表示必要评级工作的 complete/incomplete，不能混用。overall 行的 `business_completion` 表示全任务完成度，其余工作状态对应主情景。摘要区分必要范围分流、本情景全量台账及全任务分流台账；跨情景及权利范围记录不等于独立候选数，未纳入必要工作范围也不是法律排除。

继续生成 `report-data.json`、`report.html`、`report.md`、`report-findings.csv`、`report-manifest.json`。HTML/Markdown/CSV 从同一数据模型生成；八章节、七模块及真实图证保持一致。主摘要显示总风险和置信度，“人工核查与注意事项”展示有针对性的核查及升降级条件，证据缺口仍独立可见。

验证同时检查五级字段、完整推论、主审及双审阅绑定、原始来源/计划/补充媒体哈希、链接和离线产物。风险重评不伪装成新查询；历史策略回归、负例和新策略验证分别记录。

## 核心视觉证据：core-risk-evidence-v1

本节记录 core-risk-evidence-v1 的基础筛选语义；新生成报告默认 core-risk-evidence-v2，并增加[页图定位验证](workflow-correction.md#核心图证与报告)。只读验证旧报告沿用原标记/无标记规则，不重写产物；显式展示配置和自动配置使用相同筛选，空配置不能关闭必要图证。仅具体且适用情景中的中/高/极高当前已评候选进入重点视觉板；低置信度不影响入选。未来信号、待评、低/极低、零结果、登录/错误/空文献和纯操作留痕保留于历史与详情，不进入重点板。

按情景→候选→核心权利页分组，保留关键反证以及直接用于比较的必要产品图，不自动重复整套相册。被引用的原始PDF通过完整公开号、国家/权利类型、source_document及source_document_sha256反查已登记页图；页图另有自身path/sha256/bytes。页图登记 visual_role=document_identity/patent_claims/patent_drawings/registry_record/product_comparison、1-based page_number、可选figure_labels、visual_reason。页码、案号与页面内容须实际核对；缺失页从原始已核验PDF渲染，不凭文件名猜测、不重绘。只展示必要页，但不固定页数上限造成遗漏。

缺核心页时记录具体 visual_gaps 和原文链接，不隐藏已知风险。卡片含情景、候选/案号、风险、用途、原取证日期及原图/完整文献离线链接；HTML内嵌原图字节。不同判断共用同一图像字节时保留各自关联；board数量与整个HTML图片资产数量分别计算。HTML/Markdown/CSV与manifest由统一模型生成；核心图证EV可追溯至原文EV。详细筛选由report_estimate及行为测试集中维护，不以通过格式锁替代业务图证验收。
