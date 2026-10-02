# 最小补证、结果审阅与真实动作分类（05B）

本协议只用于 `triage_followup_revision=candidate-followup-v1` 的新任务，依赖 [05A 候选范围](candidate-triage-scope.md)。历史决定和运行不补造该标记。`needs_info` 的每个 `next_actions[]` 除原字段外，填写 `followup_basis`：`missing_fact`、`decision_effect`、`evidence_needed`、`existing_material_review`、`existing_evidence_refs`、`obligation_ids`、`completion_condition`、`new_value`。这些字段说明缺什么、为何影响相关性、现有材料检查结果、最小证据、何时足够以及下一动作独有的价值；已有材料引用必须进入本次决定的阅读证据。

先读已保存的原文、图片和回执。`kind=agent_read` 引用留存 `evidence_refs` 与阅读范围，不产生新来源运行。只在用户独有且确有必要时用 `user_information`，附 `user_exclusive_reason`；用户未回复保留等待，不自动宣称受限。

`kind=professional_review` 用于确需外部专业判断、且具体问题和已读材料均已绑定的待办。写明 `question`，在 `followup_basis.existing_evidence_refs` 列出实际已读材料；不得附 provider、operation、params 或伪装为来源查询。结果审阅可记录 `waiting`，引用该基础材料并准确说明专业意见尚未取得、真实依赖与恢复条件；这只把工作转为外部依赖等待，保留原 `needs_info`，不表示已委托、存在来源硬限制、专业意见内容或正常完成。收到意见后须登记材料并基于新证据形成新决定。

外部请求按**真实操作、参数与查询表达**分类，不依据动作名称：

- `kind=source_lookup` 仅用于已知唯一对象的定向身份补证、原文或状态读取。`target_locator={kind,value,evidence_refs,unique_reason}` 应来自已读材料，并与实际参数一致。准确号码、可追溯链接、来源内部唯一记录可作定位依据；号码残缺但来源唯一行可定位时，记该行身份及唯一性理由。宽泛标题、申请人、分类、家族或主动推荐扩展不冒充唯一对象。
- 寻找未知对象用现有发现计划与预算。分流动作写 `kind=discovery_binding`、已生成计划的 `query_id`、`request_mode=discovery` 和实际范围理由；通过 `record_candidate_followup.py --kind bind-discovery` 在执行前绑定。原计划仍受目的、版本、页数、路线、浏览器候选及来源能力门禁，不因候选补证改名获得新名额。
- 确实无法拆分的发现兼核验请求，在同一动作写 `request_mode=mixed`、已知对象 `target_locator` 及 `verification_obligation_ids`，计划行必须体现该定位与主动发现的实际表达。登记一次发现计划行、一次真实运行，另引用发现与核验义务；发现边界不足则不能执行混合请求，应改用合格纯核验路线或保留对应限制。必要核验被动返回的其他候选仍按模块 04 全量留存与去向处理，不反写成另一条发现执行；继续主动展开才是新发现动作。

每次本地阅读或真实来源结果后调用：

```bash
python scripts/record_candidate_followup.py --task-dir /absolute/run --kind bind-discovery --input /absolute/binding.json
python scripts/record_candidate_followup.py --task-dir /absolute/run --kind review-result --input /absolute/review.json
```

结果审阅输入绑定原 `annotation_id`、`action_id`、候选／情景／国家／权利范围，来源动作另绑定 `query_id`、`run_id`，引用本次已得证据并写 reviewer、reason。`sufficient` 须先提交引用补充证据的新 `selected` 或 `not_selected` 决定；`continue` 写未解决事实、下一动作新增价值和剩余边界；`waiting` 写待解决依赖与恢复条件；`limited` 仅在真实运行给出明确且无待恢复事项的硬限制时记录依据、影响和恢复条件。失败、零结果、未知提交或用户沉默不会自动变为不入选或低风险。一次动作的 `max_attempts=1` 是该请求的执行边界，不是候选或缺口的补证总次数。

绑定和结果审阅作为 `task.json` 的追加事件保存原计划行哈希、原运行哈希及前序事件 ID；原 `source_runs` 和发现计数不复制、不返还。材料审阅、范围处理、相关性决定、专项核验分别保持自身完成条件。05B 处理动作和出口，批次优先级、完整定向重开与模块整体完成仍由 05C 承接。

### 专业复核等待与 evidence 交付

当前 `needs_info` 的 `professional_review` 等待凭证由同一投影和发布验证器重算，绑定当前情景、候选、分流、动作、等待事件与已读材料哈希。仅记录真实外部依赖和恢复条件，不表示取得专业意见、官方核实或风险排除。证据、动作或当前分流变化后凭证失效；缺少材料或其他可执行动作仍阻断发布。代码修复而冻结业务输入未变化时，当前双审继续有效。

partial-evidence-v2 报告中，无具体候选、risk=null、right_state=unknown 且已由双审或主审处理的范围，可以披露为 reviewed_scope_gap；引用材料必须存在并绑定哈希，coverage_status 仍为 unknown。语境材料不作为权利、排除或覆盖完成证明。全部可执行及未审动作仍先阻断发布，final 模式不适用此披露规则。

### API v3：历史请求由独立已读原件补齐

`review-result` 新增 `outcome=resolved_by_material`，仅用于 `api-first-v3` 的准确记录 `source_lookup`：原动作只缺 `protection_content`、`independent_claims`、`representative_figures` 或 `design_views`，随后已取得并实际阅读准确原件，当前新分流已为 `not_selected`，或 `needs_info` 且余下动作全部为 `user_information`。它只关闭历史采集结果的审阅；不改变旧 run、不声称全部视图、当前权属或效力已清楚，也不解除实际产品资料等待。

- 原 run 仍须精确绑定旧 annotation/action/query/plan 和 `original_run_sha256`；`effective_submission` 必须已确认提交。失败须有已登记故障或提交核对回执。未明提交、运行中请求和未读来源动作不能用该结果关闭。
- `result_evidence_refs` 仍只引用原 run 的真实 EV。原故障没有 EV 时保持空列表；用 `original_raw_sha256` 逐文件绑定原 run 的真实原文，并用 `original_response_reading` 说明实际故障/返回内容，不能把 PDF 伪装为 API 的成功输出。
- `resolved_annotation_id`、`resolved_annotation_sha256` 绑定当前新决定；`resolved_facts` 与旧动作的必要字段一致。`replacement_materials` 逐项记录真实 `evidence_id`、准确 `publication_number`、`jurisdiction`、`reading_level`、`pages_read`、`identity_reading`、`content_reading`、`limitations` 和 `file_refs[{path,sha256}]`。原件必须已进入新决定的证据引用。
- 登记的 PDF 需准确号码/地域、原始文档身份、页数及实际文件哈希；必须读封面身份及所列内容页。OPS 已留存图页复用经 `source_result_processing.progress` 验证的原阅读回执，URL、缩略图或未读媒体不能满足图样阅读。
- 错号、另国、文件篡改、原回执篡改、未完成当前来源动作或旧决定失效均拒绝。消费时继续检查旧 run、备用证据/文件、恢复回执与原新决定的不可变凭据。

OPS `images` 单页的已读事实只依赖准确 publication、country、原 run/entry、原 XML、媒体 SHA 与页范围。后续 merge 将同一已读图物化进候选聚合不构成新的原页；历史阅读签名完整保留，仅在比较阅读依赖时忽略旧聚合 `candidate_content_sha256`。真实原图、页、号码、国家、请求或回执变化仍会失效。此兼容仅适用 OPS 图页，不普遍清除其他记录审阅的内容依赖。
