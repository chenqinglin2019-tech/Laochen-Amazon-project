# 提速、精简输出与有据限制（新任务）

本页说明新任务额外启用的运行优化与两项门禁修订。均只对新建任务生效；历史任务、已交付报告及其重新校验保持原行为。

## 任务修订标记（`create_task.py` 写入）

| 标记 | 含义 |
|---|---|
| `limited_delivery_revision=failure-limits-v1` | 失败／停止的动作在已有精确记录时可作为有据限制进入受限（evidence）报告 |
| `review_conflict_revision=structured-conflicts-v1` | 两条独立审阅链只在结论性字段上算冲突 |
| `best_estimate_revision=best-estimate-risk-v1` | 每个适用范围给出最佳估计等级，待定仅限既无检索收据、无材料也无制度依据的范围；制度不适用范围引用随技能发布的制度表（[jurisdiction-rights.md](jurisdiction-rights.md)，`evidence.collections.institution_references`）；维权信号参与总体；未提供的自有品牌不锁上架建议。规则见 [risk-estimate-rules.md](risk-estimate-rules.md) |

以上标记都进入最终审阅的输入摘要，变更即需要重新审阅。

## 核心优先顺序与跨进程备忘（best-estimate-risk-v1 新任务）

- `advance_work.py` 的 `source`／`agent` 动作卡按核心优先稳定排序：`PATENT_MARKING_RESOLUTION_REQUIRED`（页面标注 patent／patented 时由 `product_scope.work_entries` 生成，`patent_claim_followup` 完成后消失）→ 其他产品分析 → 入选候选的核验／补证（`professional_review`、带 `candidate_id` 的条目；来源行中 `discovery_role=marking_resolution` 与核验阶段行先于发现行）→ 原件阅读 → 发现检索。预算受限时先执行排在前面的来源行。等待项、条目内容与历史任务的顺序不变。
- `work_view_memo.py`：工作视图与审阅输入摘要的跨进程备忘，以任务目录内全部文件（≤8 MB 按内容哈希，其余按大小＋修改时间）、脚本与配置文件的大小／修改时间、调用选项为键，存于系统临时目录 `lc-ipr-work-view-memo/`；任何文件变化即失效，不改变视图语义，不读取凭据；`LC_IPR_WORK_VIEW_MEMO=0` 关闭。
- `mechanical_ledger.py` 程序默认收尾（`STEPS` 末尾的 `operation_reviews`、`bounded_stop`，默认步骤已包含，须在 `discovery_review_host.py` 之前运行）：`operation_reviews` 只对公开单页路线（serper_web、serper_images、serpapi_google_patents、epo_ops）中计划行冻结为单页有界、留存请求回显与计划行一致、且有精确 03C 验收证明（持久化的 `evidence.operation_acceptances` 仍被 `current_operation_acceptance` 接受，或同一已验收操作对本次响应重算仍通过）的运行写 `accepted` 操作审阅（`checks.pagination=single_page`，`reviewer=program:operation_reviews`）；HTTP 成功本身不算。`bounded_stop` 对同类单元在有方向审阅、有效 before 审阅且尚无 after 审阅时，先在内存中组装 after 语义事件（`problem_covered=false`、`next_action=awaiting_capability`、`uncovered_clues`＝before 未覆盖线索 ∪ 方向线索）与 `stop_bounded_discovery` 后续审阅，通过 `discovery_semantics` 的有界范围证明后才落盘并从磁盘重证，失败则逐字节回滚（`reviewer=program:bounded_stop`）。多页行、lens 路线、凭据或适配器已变化、卡片／分流／处理证明不成立、已有 `refine` after 审阅的单元一律留给 Agent；程序默认不是覆盖声明，Agent 可事后改判。

## 有据限制：failure-limits-v1

原规则下任一动作被 08D 技术停止，或来源失败重试耗尽、提交后限流／额度／鉴权依赖、已审仍未知的提交，都没有任何可发布出口，整单无报告。带标记的任务在原审阅要求全部满足时接受以下状态为**有据限制**，可完成最终双审并交付 `limited_round_closed` 的受限报告：

- `TECHNICAL_EXECUTION_STOPPED`：须有对应的 08D `technical_stop` 事件及其 `recovery_condition`；限制类型 `internal_technical_failure`。
- `SOURCE_AUTOMATIC_RETRY_EXHAUSTED`、`SOURCE_RETRY_DEPENDENCY_REQUIRED`、`SUBMISSION_UNKNOWN_EVIDENCED_LIMIT／DEPENDENCY`：须绑定 08B 原运行引用，逐个核对 `run_id` 与运行记录哈希；限制类型 `source_retry_exhausted`、`source_access_dependency`、`submission_unknown_reviewed`。

不变的部分：原待办、恢复条件和提交状态照旧保留，不代表权利或来源已核查（`official_verification=not_verified`）；仍有可执行工作、未审材料、未经审阅的提交未知、暂停，仍阻断发布；仍须一次最终双审。阶段已到裁决／发布／交付／校验时，Stop 钩子不再因这些状态返回等待或执行停止，而继续推动这些步骤。

## 结构化冲突：structured-conflicts-v1

原规则把要素说理、引文、产品特征描述、实施方案标题／描述／自拟编号等自由文字的任何差异都算冲突，两条独立模型链几乎不可能一致，导致每个有比较的单元都要主审手写完整裁决行。带标记的任务只比较：风险、权利状态、排除依据、逐项标准结论、按**权利要求号**归一后的权利要求结论（类型＋结论）、视觉覆盖（产物哈希）、置信度及其依据勾选、适用范围类标志，以及决定性排除／适用性例外（类型）／范围适用性（状态）是否存在。结论一致的单元采用第一审阅链的行；带 `applicability_exception` 的行仍须主审裁决。

主审辅助：`python scripts/prepare_adjudication.py --task-dir TASK [--reviewer NAME]` 校验两份审阅与当前输入摘要一致，写出 `adjudication.json` 骨架（`review_context.evidence_digest`、整份审阅哈希 `review_refs`、每个需要裁决的单元一条草稿行）和 `adjudication-worksheet.json`（冲突字段与两审取值并列）。`reviewer`、`session_id`、每条 `adjudication_reasoning` 故意留空，发布门禁在主审真正裁决并填写前会拒绝该文件；本脚本不改任何校验规则，不覆盖已有文件。

## 精简输出（不改变落盘数据）

- `run_api_plan.py`（2.4 任务）默认打印摘要：状态、计数、问题行、`details_file`；`--output-format full` 恢复原输出，完整记录始终在 `execution-status.json`。
- `advance_work.py --output-format compact`（默认）：`review_progress` 只含计数和分范围合计，`stage_risk` 只含标题与计数，`per_work_progress` 只列需关注的动作；单行 JSON。完整数据在 `continuous-work-status.json`，`--output-format full` 保持原输出。
- `record_*.py`（progress、stage_risk、review_progress、continuation、specialty、distinctive_rights、public_identity、candidate_followup、candidate_triage_stage）默认只回显 id、状态和短字段；`--verbose` 恢复完整记录。

## 批量输入（结果与逐条记录相同）

- `record_progress.py`、`record_stage_risk.py`、`record_discovery_semantics.py` 接受 `{"events":[...]}`（discovery 为 `{"events":[…]}` 内每项是一条原样审阅）：一次加锁、一次加载、内存中按顺序逐条按原规则校验、一次写入；stage_risk 与 discovery 全部通过才落盘。08D 批仅允许全 begin 或全 finish。
- `advance_work.py` 内部对同一调度的全部 begin／finish 各只推导一次工作视图并写一次 evidence，调用 API 批时加 `--skip-final-view`。

## 发布与入口

新任务发布：`python scripts/publish_report.py --task-dir TASK --first-review … --second-review … --adjudication … --mode auto --output-dir NEW_BUILD --deliver-to NEW_ENTRY --require-complete`，或 `advance_work.py … --output-dir NEW_BUILD --deliver-to NEW_ENTRY --publish --require-complete`。交付成功后 Stop 钩子自动改绑到 `NEW_ENTRY`；`completion_check.py --output-dir NEW_ENTRY` 检查的是交付入口而不是构建目录。

## 输入模板：input_template.py

对最常见的 Agent 动作卡，`python scripts/input_template.py --task-dir TASK --output-dir NEW_DIR [--work-id WORK-…]` 直接写出输入文件：范围、query／direction／run／候选编号、完整的线索与方向清单（`clue_ids` 已是必须的精确集合）、待处理的结果位置、必需的身份缺口等由任务状态决定的字段全部预填，**每个判断字段一律为 `null`**——记录器拒绝 `null`，未填写的模板不可能被误记录。不带 `--work-id` 时为当前所有受支持的待办生成文件：

| 文件 | 覆盖的待办 | 交给 |
|---|---|---|
| `discovery-direction／before／after.json`（`{"events":[...]}`） | 方向审阅、提交前表达审阅、结果语义审阅 | `record_discovery_semantics.py` |
| `source-operation.json`（`{"reviews":[...]}`） | 来源操作审阅 | `record_source_operation.py` |
| `result-processing.json`（`{"events":[{source_run_id,decisions:[...]}]}`） | 已取得结果的逐位置处理（`SOURCE_RESULTS_PENDING_PROCESSING`）；已解析的待处理位置逐个列出，`decisions` 只有 position／outcome／reviewer／reason，`candidate_ids` 只在 outcome 为 candidate／duplicate_source 时自行添加（可选值见 guide 的 `bound_candidates_by_position`）；未解析位置需先补 `parsed_rows`；整条专利记录（whole_record_receipt）不生成，仍按动作卡的 reading_units 处理 | `record_source_result_processing.py`（不带 `--source-run-id`） |
| `triage-decisions.json`（`{"decisions":[...]}`） | 候选轻分流与需补证复核（`kind=triage`）；预填候选／情景／国家／权利类型，`candidate_relation`（含必需的 `identity_gaps` 及其 `identity_location` 骨架）与 `comparison` 的公共键；`selected`／`not_selected`／`needs_info` 各自还需的 `comparison` 键、`missing_information`、`next_actions` 见 guide | `annotate_materiality.py --input` |
| `review-progress.json` | 未登记查询的进度登记 | `record_review_progress.py` |
| `candidate-handoff.json` | 候选交接（`CANDIDATE_HANDOFF_READY`）：所有就绪候选合成一批，每个候选的每个未完成情景／国家一条 `scope_reviews`（`applicability`／`reason`／`evidence_refs` 待填），批次级 `reviewer`／`reason` 待填；guide 给出各候选可引用的就绪证据编号 | `record_candidate_handoff.py` |
| `recovery-<run_id>.json` | 来源恢复审阅：失败已提交（`SOURCE_FAILURE_RECOVERY_REVIEW_REQUIRED`）→ `failure_review`（新运营任务为 `failure_closeout`，含回执处置与重试决定的包装）；确认未提交（`PRE_SUBMISSION_REPAIR_REVIEW_REQUIRED`）→ `pre_submission_repair`；提交未知（`VERIFY_PRIOR_SUBMISSION_BEFORE_RETRY`）→ `unknown_check`。`source_run_id`／`source_run_sha256`、`receipt_paths`、`failure_cause`（取自运行记录）预填，其余判断字段待填；每个运行一个文件 | `record_recovery_review.py` |

标准输出只列文件、待填字段路径、允许取值、须审阅的实际查询文本、候选标签和证据编号；动作卡的 `input_template` 字段给出对应命令；输出目录必须不存在。工具不选择任何审阅结论，也不改动任务。
