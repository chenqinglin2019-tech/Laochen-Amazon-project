# 专利与外观专项核验

新任务使用 `specialty-analysis-v1`。只处理当前已纳入且有效 `selected`、已有 05C `selected_handoff` 的专利、实用新型、注册或未注册外观范围。用 `scripts/record_specialty_analysis.py --task-dir DIR --input FILE` 追加一项审阅事件；输入 JSON 的 `kind` 选择事件。每项都带 `candidate_id/scenario_id/jurisdiction/right_type`、`reviewer/reason`。本模块只记录事实与比较，不定风险等级。

## 原子批处理与一次比较收尾

`known-findings-risk-v1` 或 `operator-report-v1` 任务可使用同一命令提交 `events[]`，也可单独提交 `kind=comparison_close`。无新策略的历史任务继续只接收原单事件；旧 `kind=batch` 仍表示材料批次去向，不表示原子事务。

```bash
/usr/bin/python3 scripts/record_specialty_analysis.py --task-dir /absolute/task \
  --input /absolute/specialty-transaction.json
```

批输入顶层提供 `scope`（candidate_id、scenario_id、jurisdiction、right_type）、`reviewer`、`reason` 一次，`events` 按真实顺序列子事件。子事件可显式覆盖范围或审阅者；范围同字段冲突会拒绝。顶层可共享准确 `intake_event_id/assessment_date`；没有提供时，非 intake 子事件引用已经实际登记的本范围最新 intake 和原评估日，不生成新的日期。

- 子事件用 `alias` 命名；后项通过 `{"$event":"前项alias"}` 引用其真实事件 ID。只允许引用已执行前项，前向引用、未知或重复别名拒绝。
- 所有旧字段、原文、阅读、来源、状态、证据引用与依赖门禁继续执行。事务不自动建立阅读记录、权利状态、unknown 原因或恢复证明。
- 子事件先在调用内副本逐项校验、保留原哈希链；所有项及最终投影有效才一次原子写入。任一末项失败，所有前项不落盘。原输入在 triage snapshot 中保持不变，草稿完成后只刷新一次最终 decision snapshot／专项投影。
- `transaction_id` 可显式提供；未提供时按完整请求生成。相同请求和当前输入重复提交返回 `status=reused`，不增事件、不改原签名。同 ID 换请求、输入版本或来源能力变化、原件字节变化、事件／凭据篡改会拒绝复用。只使用本次调用缓存，原文件和准确搬迁哈希每次仍检查。

`comparison_close` 包含实际 `comparison` 以及仍有 unknown 时的真实 `gap`、`followup` 处置。比较的必要要素／视图、原文、实际产品事实及各 unknown 理由仍必须完整。已确定且没有 unknown 的比较只产生 comparison，不伪造 gap 或 followup。

记录器和工作投影共同使用 `comparison_blockers` 派生同一份比较缺口。收尾自动绑定 `gap.basis_event_id/comparison_event_id/affected_judgment/inventory_event_id/unit_id`、各 `obligation_bindings` 的准确比较 ID，自动生成 gap ID，绑定 followup 的 gap ID 和事件 ID。默认复制比较的实际证据引用；不重复要求输入这些关联字段。若收尾有 `alias=cmp`，返回 `cmp`、`cmp.gap`、`cmp.followup` 三个真实别名。

调用者必须真实提供 gap 的问题、最小动作、完成条件、已有材料处理和补查价值，以及 followup 的实际结果、剩余影响、处置／恢复选择。`user_fact` 仍要求既有准确未解决反馈记录（结构策略下也可为 `unavailable`）；来源限制仍要求原来源／计划证明；`limited` 仍须真实限制依据、合法类型和恢复条件。缺少处置或恢复证明时整个比较收尾回滚，不能把未知写成完成。

外观同时有视图未知和线型范围未知时，可在 `gap.blocker_reasons` 选择本次实际处理的派生原因；未选择部分继续在工作投影中显示。专业等待可只选 `SPECIALTY_DESIGN_SCOPE_UNKNOWN`，记录器按准确已读原件计算 `professional_packet` 并绑定 followup 的 packet 哈希；没有实际专业意见仍为 unknown。其他必要依赖事实可通过 `gap.additional_bindings` 保留其真实事件 ID；API 保护内容限制的比较绑定可提供准确 `protection_fact_event_id`。这些字段只连接已有证明，不创造法律事实或来源限制。

成功响应包含本次真实 `events`、`aliases`、`derived_gaps` 和最后一次 `projection`。`specialty_transaction_receipts` 保存请求／输入指纹及子事件哈希，用于幂等和审计；它不能替代事实审阅、最终双审或发布凭据。

1. `intake` 引用准确 `selected_handoff_event_id` 和 `assessment_date`（YYYY-MM-DD），并说明 `assessment_date_basis`。未指定评估时间时记录器以本轮专项启动的本机日期为基准并留默认依据；保存原产品／候选版本及交接缺口。后续事件带该 `intake_event_id` 与固定 `assessment_date`。新一轮评估日期或入选交接改变时引用 `prior_intake_event_id/new_round_reasoning`，旧证据与判断保留历史，不能只改报告日期。身份未知时继续不依赖它的材料阅读，不能猜填具体权利、地域或版本。
2. `material` 写 `document_id/document_version/evidence_refs/acquired_at/source_form/purposes/reading_locations/status/support_reasoning`。`source_form` 区分官方登记／事件／决定、原始文献、产品原件、摘要、OCR、翻译或其他；这是审阅声明，仍须核对真实来源。`status` 分 `acquired`、`read`、`sufficient_for_listed_purposes`；仅后两种须有真实阅读位置，充分性另列 `supported_facts`。OCR、翻译、摘要写 `original_evidence_refs/original_locations/original_verified`，关键内容须回原图／原文。跨本轮复用可用 `reuse_from_event_id/reuse_applicability_reasoning`，保持原取得时间、版本、证据和用途边界，不能提升原阅读充分性。取得、文件哈希、下载成功均不证明当前状态或全部用途充分。
3. `fact` 写 `fact_id/fact_kind/outcome/raw_statement/reasoning/document_version/reading_locations/evidence_refs/material_event_ids`，其用途、版本及证据必须与实际已读材料相符；`supported` 还须有该用途的充分性审阅。用途为 `identity/territory/status/protection/product/rights_holder/legal_conditions`；状态与地域还写具体 `right_identity/territory_basis`，状态保存 `source_checked_date`，当前外观权利主体须说明评估时点适用性。`outcome` 为 `supported/unknown/conflicted`；冲突保留双方来源，支持新判断时用 `resolves_fact_event_ids/adoption_reasoning` 显式解决。交接缺口只在相应事实给出 `resolves_handoff_gaps` 后关闭，不能因本模块启动而自动消失。决定性事实另写 `excludes_action_ids/exclusion_reasoning/assessment_applicability_reasoning`。查询、事件、评估时间分别保存，不用重新打开文件改变评估基准日。
4. `exemption` 写 `action_id/fact_event_ids/right_identity/territory_basis/scenario_basis/reasoning/remaining_obligations`。需有身份事实和明确标记该动作的决定性地域或状态事实，后者须基于已读且按用途核实的官方登记、事件或决定；摘要不能独立充当依据，冲突须先解决。只关闭指定动作。整个必要比较免做时 `action_id=all_comparisons`，仍保留其它专项义务、入选记录和历史。比较途中发现差异不能构成此依据。
5. `inventory` 按实际文献版本列每项独立权利要求或具体设计的 `units`，绑定已读的 `material_event_ids`，并说明真实阅读范围和完整性。专利单元写 `unit_id/kind/implementation_id/product_configuration/original_location/necessary_elements`，设计单元写 `unit_id/kind=design/design_id/product_configuration/product_state/original_location/necessary_views`。`comparison` 逐单元给出 `compared/exempt/pending` 去向；专利比较的 `elements` 须覆盖清单全部必要要素，设计 `views` 须覆盖全部必要视图并给对应原图／产品图位置。每项仍可标 `unknown` 并说明影响，不因一处差异停止其他项。设计另记 `design_scope_parts` 中逐部分被主张／排除／未知的标示依据、整体视觉关系、同异与未知、拍摄限制、保护范围依据和注册分支；注册与未注册义务分开。
6. `gap` 绑定具体问题、受影响判断、已有材料核对、最小动作、完成条件及补充价值；`action_kind` 区分已有材料阅读、已知权利核验、追加发现和用户独有产品事实，后者须引用已由模块 02 记录的未解决 `product_feedback_request_id`（`requested` 或结构策略下的 `unavailable`）。实际结构不足不再向用户询问：先核对已有资料，按精确当前未知绑定记录缺口；结构不可提供回执和 `waiting/limited` 结果投影为有依据的 `PRODUCT_STRUCTURE_UNAVAILABLE` 限制，未知继续为无法判定。`followup` 引用 `gap_event_id` 审阅本次结果，区分 `resolved/continue/waiting/limited`；`resolved` 必须关联缺口之后的新事实、比较或免做判断，`continue` 还要说明下一步的补充价值，`limited` 须明确硬限制类别、证据和恢复条件。非结构信息等待用户或暂时访问失败保留 `waiting`；实际结构按模块 02 默认不可提供处理，不进入用户待答队列。`change` 仅在实质影响时列受影响旧事件，`change_review` 逐项覆盖影响；结论改变时用 `replacement_by_affected` 逐项关联新判断，旧依据停止作为当前依据。路径变化不重开。`batch` 绑定来源运行或准确导入证据，写 `received_evidence_refs/disposition_by_evidence_ref` 和已得、已处理材料事件；本范围候选来源引用没有批次去向时不能正常完成，仅已取得未阅读的材料须有明确不需阅读的去向理由。`handoff` 对具体版权／商业外观线索交 07，对剩余待办交 08，对核验及待审问题交 09，对范围版本、完成与限制交 10；交接不关闭义务。

统一 `next_work.specialty_analysis` 独立显示每个范围及本轮 `in_progress/normal_complete/waiting/limited`。正常完成要求准确基础事实、必要内容与产品事实、每项必要比较或有效免做、逐材料去向、补证与变化复核；已支持的局部结果可先交接。等待与受限均不是正常完成，模块 06 完成也不等于模块 09 风险审阅或模块 10 发布通过。旧任务无修订标记时保持原合同，不倒填历史事实。来源请求仍由既有动作分类和预算执行，本记录器绝不直接访问外部来源。

## 人工审阅时不能省略的判断

- 地域状态按具体权利、目标国和评估日处理。国家权利、普通 EP、UP、区域设计及其各国适用关系分别核对；同族、办公室名称、申请／授权文本和今日取得日期都不能自动证明当前地域效力。原始状态、事件发生／生效／公布／来源更新及实际查询日期分开记，难归类时保留原意。旧材料不套固定有效天数，说明其对象、用途、时点为何仍适用；新查询失败不得覆盖旧材料。冲突先排查对象、文献版本、时间和用途，未解决部分只暂停实际依赖的判断。
- 专利／实用新型以真实实施方案×所采用版本的每项独立权利要求为单位。先据原文识别所有独立项，按自身文字和必要定义、引用关系、限定及附图说明处理；从属项只在具体问题需要时审其引用链，不把从属限制移入独立项。要素结果分有依据对应、有依据差异与未知，产品图片看不到内部结构不能写成不存在。裸件、实际组合与方法操作依据已知销售和使用事实分开；间接侵权条件只列已知事实、缺口和待审问题。某一要素有差异后仍登记其余必要要素，但补证依影响和价值确定，不无限补齐表格。技术记录交模块 09，不能直接写成不侵权。
- 外观以具体设计×实际产品版本与状态为单位。原图实线、虚线和其它标示结合说明及目标地域规则解释，保护范围未明可先记视觉事实。逐视图核对两侧覆盖、位置、比例、轮廓、表面与空间关系；六张重复正面图不能代替背面，裁切保留原图对应。视角、光照、遮挡及状态可能造成差异，先查已有可对应图，再按价值补图。整体观察同时解释相同、差异与未知，不以数量、相似度分数、颜色、标志或一处局部差异提前排除。
- 注册外观分开核对号码、官方身份、图示、主体变更和当前状态；申请不是授权，历史主体不是当前权利人。未注册外观先核实具体地域法律条件，再逐项核对形成、主体、公开／使用、地域联系与期限等实际适用事实；没有登记号不等于未注册，找到注册也不自动关闭其它已纳入权利。公开证据须绑定当时的设计版本、内容、日期与地域依据，当前图片不得回填旧页面日期；最早检索记录不等于首次公开，网站域名或语言不证明地域。视觉关系、接触／复制、独立开发与许可分别记录，不用相似补复制，不用缺少复制证据证明独立开发，也不把供应商口头保证当许可。
- 共享材料只形成一份来源和真实读取，每项权利仍分别判断用途适用性。缺口先查已有原文、图证和事件，确认最小且可执行的动作；一次补证可服务多项缺口，但必须逐项审阅结果。实际结构先使用已有资料，未提供或资料不足默认用户无法提供，走模块 02 的结构不可提供记录，不询问或等待用户。其他用户独有且必要的非结构事实仍走模块 02 的定向反馈，用户未回复保留等待；暂时失败或价值低不足以认定永久受限。动作分类及发现额度沿模块 03／05 执行，不能把未知对象发现改名为核验。产品事实、保护内容或状态实质变化时沿直接和间接依赖复核，有合理不确定性时解释扩大范围；路径更名或重复下载不重开。旧比较、免做与交接保留历史，受影响项在复核前暂停使用，复核即使同结论也需留下继续适用依据。

## 已审未知与用户资料依赖

`gap.obligation_bindings[]` 可逐一绑定 `SPECIALTY_FACT_REQUIRED`（`fact_kind`）、`SPECIALTY_HANDOFF_GAP_OPEN`（`handoff_gap`）或 `SPECIALTY_COMPARISON_UNKNOWN`（`unit_id`）。每项须有当前同范围同 intake 的 `basis_event_id` 和 `reasoning`；基础必须是最新已审未知事实或当前 inventory 下含 unknown 的已完成比较。非结构信息仅在 `user_fact`、有效待处理反馈请求和后续 `waiting` 同时成立时转为 `user_evidence/awaiting_user`。实际结构采用 `use_provided_else_unavailable_v1`：准确未解决的结构反馈（`unavailable` 或历史 `requested`）与当前已审未知及结果 `waiting/limited` 精确绑定时，投影为 `blocked / PRODUCT_STRUCTURE_UNAVAILABLE`，不再向用户发问；程序在发布时重验事实、范围、反馈、缺口和最新未知依据。事实仍为 unknown，比较仍未确定，不构成正常完成。

新事实、新比较、实质变化暂停或反馈请求关闭后，旧绑定不能继续豁免审阅；需重新核对。未审材料、缺少事实记录、冲突及没有已完成比较的 unit 不能转为等待。`limited` 的文字声明不等于发布许可，外部来源限制仍须通过发布器已有的可复核限制凭据。

专项工作投影以范围、intake、具体义务及其事实/单元/材料定位生成稳定 `obligation_id`；状态从待审转为等待不改变该标识。派发、进度和验收均据此区分同候选的多个义务，旧记录保留。

来源硬限制可用 `verify_known_right/discovery` 的 gap 逐项绑定已审未知，并填写同候选、同国家/权利范围的 `source_query_id`。录入时冻结当前计划行哈希；后续 `limited` 必须找到当前派发队列中的相同查询及计划行，并通过发布器既有 `_delivery_limit_valid` 的来源运行、能力快照或路由缺失证明验证。只转移精确绑定的义务，公开保留原专项原因和来源限制；未审材料、未知提交、可执行/可修复来源、仅有文字的限制或已变化计划不能使用此路径。发布时再次验证来源凭据，不继承一次性放行。

依赖类型必须匹配：产品反馈仅能绑定产品事实和产品比较未知；官方来源依赖仅能绑定权利事实，且 `required_facts` 必须覆盖具体事实（例如 `current_status` 对应 status）。官方状态查询不能代替产品拆机事实，也不能豁免产品逐要素比较；录入及每次工作投影都重验该对应关系。

## 已读未知与技能路由技术限制

美国专利仅有两种固定的技术限制：计划中的 `US_PATENT_STATUS_ROUTE_UNIMPLEMENTED`（`required_facts=["current_status"]`）和 `US_PATENT_OWNER_ROUTE_UNIMPLEMENTED`（`required_facts=["rights_holder"]`）。它们表示当前技能没有实现相应路由，不代表官方没有可查来源、已经提交查询或已经核实事实。`verify_known_right` gap 可填写当前准确 `source_plan_gap_sha256/source_capabilities_sha256`，逐项绑定最新已读 unknown 的 status 或 rights_holder 事实。记录器保存候选、当前 selected/intake、事实、具体计划缺口及能力指纹；每次投影与发布重新派生当前证明。真实查询/能力路由恢复后，技术限制失效。整份计划、候选元数据投影或无关操作验收中不影响该依赖的变化只刷新当前证明；当前证明仍完整绑定最新能力，恢复对应状态/主体路由即失效，相关缺口、事实、selected/intake 或依据变化仍需重审。此路径仅支持披露限制的 evidence 交付，不能作为正常完成或 final 交付依据。

旧 handoff 自由文本不能猜词自动关闭。用 `kind=handoff_classification` 追加对当前 intake 的 `handoff_gap` 精确原句分类，填写 `fact_kinds`、已读 `material_event_ids/evidence_refs/reading_locations`、`classification_reasoning` 和常规 reviewer/reason。分类修订须引用最新 `supersedes_event_id/revision_reasoning`；不修改 intake、unknown 事实或其它已审结果。gap 的 handoff binding 引用 `handoff_classification_event_id/handoff_classification_sha256` 和对应 `fact_kind`。多种义务按分类投影为独立 facet，各需对应事实及依赖，status 限制不能覆盖 rights_holder。分类、阅读依据或未知事实被替代/暂停后，旧绑定停止使用。投影回显最新分类，始终保留原句与 unknown。

宽泛的“其它美国专利/设计是否全面搜完”不应形成一个无法被有界检索支持的第二执行队列。经明确范围审阅，可记录 `kind=handoff_discovery_scope/classification=residual_discovery`，精确绑定当前 intake 原句及完整的 US patent/design `official_recall` coverage IDs、当前 `direction_refs`（direction_id/right_type/sha256）。保存已读 `material_event_ids/evidence_refs/reading_locations`、`scope_reasoning/remaining_impact`，`excluded_fact_kinds` 须完整列出全部事实类别；`nondelegated_event_ids` 完整列出本 intake 的 fact/inventory/comparison/exemption，记录器冻结其哈希。已有事实分类或精确 handoff 事实绑定不能使用此委派。修订须引用最新 `supersedes_event_id/revision_reasoning`。

此记录只将重复的剩余发现责任指向现有规范检索队列，不关闭原句，不宣称全面召回，不影响已知权利的状态、主体、权利要求、产品或比较义务。模块保留 `residual_discovery_pending`，仅剩技术限制和此类委派时显示 `waiting_discovery`，不会正常完成。evidence 发布重新验证结构化委派证明，规范来源/语义/已得未审工作仍按原门禁阻止发布；final/completed 不因此放行。范围、覆盖要求、方向、已知判断或审阅依据变动后须复核映射。

当前 selected 专利的 `document_content` 查询若仅要求 `protection_content`，可直接使用本 intake 最新 supported protection 事实及其充分且实际已读的 original_document 材料。必须与已正式登记并重新验证的 candidate_lead 原件完全匹配具体公开号、原登记 evidence ref、文件路径/字节/哈希，保留事实和材料事件哈希及真正取得/读取时间。该信用只满足同案已读权利要求内容，不新增来源查询、运行或收据，不满足当前状态、主体、其它同族、附图或发现覆盖。只读信用在 dispatch 专用进度门禁之前判定，当前计划/范围/selected/intake、原件哈希与实际阅读仍完整重验；真实未执行查询不冒充 09A completed。材料暂停、未知/冲突事实或真内容变化均撤销信用。

## 已读设计范围的专业等待

保持 current selected/intake 的设计，可用 `gap.action_kind=professional_review` 绑定一个当前 `SPECIALTY_DESIGN_SCOPE_UNKNOWN` 单元；它不能绑定状态、权属、地域、产品或其它事实。`professional_packet` 由 `professional_scope_packet` 生成，绑定准确 intake/inventory/comparison 摘要、全部必要视图、充分读取原件的材料事件及实际阅读位置、引用索引与文件哈希。必须已完成逐视图记录，且具体 `design_scope_parts` 仍 unknown；未读图样不能借此等待。

`followup.outcome=waiting` 要有 `professional_dependency=qualified_design_scope_interpretation`、准确 `professional_packet_sha256`、完整 packet 引用、真实未获专业意见的审阅、外部依赖和 `resume_condition`。准备 packet 不表示已向外发送委托。专业意见未得到时保持未知，不能宣称范围确认、侵权排除或 normal_complete。产品缺失照片仍走独立正式 `user_fact`；其等待不能代替专利线型解释。

`professional_wait_entry` 在每次投影和发布重新验证 current selected、当前 intake/单元/比较/读材/文件；返回 `professional_wait` 精确证明，范围或引用改变、意见已替换旧 unknown、材料暂停、新 packet/followup 或篡改均使旧等待失效。只有这个重新计算的证明可作为 evidence 交付的外部专业等待；final/completed 仍由未完成义务阻断。

美国专利和注册外观设计的 `current_status`、`rights_holder` 继续分别绑定 `US_PATENT_*`／`US_DESIGN_*` 的候选核验缺口。设计地域效力只可从同一 `US_DESIGN_STATUS_ROUTE_UNIMPLEMENTED` 绑定 `fact_kind=territory`，并使用独立 `territory_current_effect_plan_gap` 证明；它保留地域效力未知，不能由申请/授权记录推断在美有效，也不能被状态或权属等待替代。只有当前候选、intake、unknown事实、计划缺口和能力快照完全匹配的证明，才可作为报告限制。
