# 08B 来源失败、重试与提交未知

新任务 `continuous_recovery_revision=continuous-recovery-stage-b-v1` 沿原 `evidence.source_runs` 和唯一 `next_work` 工作，不建立第二份来源执行记录。恢复对象由任务、来源操作、查询语义版本及页码／资源目标确定；`query_id`、动作名和 `work_id` 变化不返还次数。已知对象若只有资源目标，不补造发现查询版本。原来源回执及部分阳性材料保留；来源提交、结果、材料处理和业务义务分别核对。

再次出网前先看原回执与留存材料。确认未提交后用 `record_recovery_review.py --task-dir DIR --input REVIEW.json` 记录 `pre_submission_repair`，说明故障、实际修复与重新核对的执行条件；它不消耗已提交失败次数，也不凭“未提交”直接重发。已提交确认失败最多自动重试一次，且须先用同一记录器追加绑定原 `source_run_id`／SHA-256 的 `failure_review`。输入须说明原回执、材料处理、剩余工作、失败原因、修复依据、来源规则引用及是否允许恢复；无原文件时明确说明缺失原因。来源限流、许可／访问依赖优先，成功零条、业务证据不足、语义修复和本地续处理均不是技术失败重试。浏览器已有更严的部分恢复和限流边界继续生效；发现预算及真实获取量不重置。重试耗尽仅停止同一自动重复，不关闭调查义务。

提交未知先核原请求、原页面／回执或合格的只读状态入口；`unknown_check` 必须引用原运行和实际核查依据。合格状态查询必须标明只读与来源规则，不能借“查询”名称重新提交业务请求。可记录确认未提交、已提交仍运行、已提交失败、取得绑定结果或仍未知；原 `source_run` 的未知历史不改写。仍未知时保留名额，继续可执行核查或等待具体依赖；仅在材料已审、必要动作已做、无核查入口和恢复依赖四项均有具体依据时，才可记录执行部分的 `limited`，最终报告仍由交付门禁判断。交付门禁只在任务带 `limited_delivery_revision=failure-limits-v1` 时接受 `SUBMISSION_UNKNOWN_EVIDENCED_LIMIT／DEPENDENCY`、`SOURCE_AUTOMATIC_RETRY_EXHAUSTED`、`SOURCE_RETRY_DEPENDENCY_REQUIRED` 作为有据限制（须绑定原运行的 id 与哈希，见 [workflow-efficiency.md](workflow-efficiency.md)）；无该标记的历史任务这些状态仍阻断发布。迟到结果通过 `late_result_link` 核对同一来源目标，回接原动作并继续材料处理；不算第二次执行。

`next_work.entries[].recovery` 显示恢复对象、原运行引用、提交未知预留数、次数及恢复状态。`awaiting_review` 的来源项由 `advance_work.py` 给出原回执审阅卡；`submission_unknown`、访问依赖与次数耗尽留在同一待办，独立工作继续。原记录器仍决定材料位置和专项义务是否满足。恢复前任务／版本、暂停与局部依赖核对留 08C；逐工作无进展诊断留 08D。

## v3：已审失败但不请求重试

`api-first-v3` 的已确认提交失败可仍使用 `failure_review`，明确 `source_allows_retry=false`、`retry_disposition=not_requested`、`no_retry_reason`。原回执、原件完整性和04A实际处理要求不变；未知提交不适用。此记录只停止本轮重试，不确认权利零结果、不改变09A的planned/failed进度，也不独立授予发布许可。

任务额度用 `retry_constraint={kind: task_request_limit, provider, plan_entry_sha256, max_queries_per_task, consumed_queries}` 明确表示；消费者重算当前任务上限与实际物理请求消费。仅此精确额度证明与同候选、情景、地域和权利的当前M06/API字段缺口limited凭据同时有效时，才可将该失败请求投影为受限交付。配额、原件、计划或事实阅读实变会重新打开相应待办，不能解释为提供方永久禁止重试。

准确登记原件且当前M06已充分阅读的保护内容，可满足对应保护字段；图文原件来源与API来源分别保留。原件不提供当前状态、当前权利人或目标地域效力的确定事实时，这些字段仍保持未知。

当前 `api_record_fact_gap` 的计划摘要哈希含额度提示等元数据。v3 专项分流在重新验证当前候选、再生计划和发布凭据后，按未变的字段范围、事实依据、阅读事件及范围判断复用旧审阅；仅额度提示导致摘要变化不重开。旧签名与原记录保留，新路由可执行、字段或准确记录/阅读依据变化仍重开；其他状态路线凭据不适用此例外。

已取消的 v3 发现请求只有在取消记录与原计划准确绑定、提交状态已知、原失败审阅完整且哈希有效、实际留存材料处理完成并无剩余卡片工作时，才能归档执行待办。历史适配器未留存正文的失败须复用真实缺失审阅，不能补造04A阅读或有效零结果；报告保留原失败及正文缺失的具体未知限制，原消费与进度不改写。发布计算使用现有不可变调用域缓存，计算结束即释放，跨发布请求重新验证。

## 新运营任务：一次失败收尾

`api-first-v3`、`known-findings-risk-v1`、`operator-report-v1` 同时启用时，原命令支持 `kind=failure_closeout`，输入只绑定一次准确 `source_run_id`、`source_run_sha256`，并提供 `receipt_disposition` 与 `failure_review`。也可直接调用 `recovery_stage_b.record_failure_closeout(task_dir, source_run_id=..., source_run_sha256=..., receipt_disposition=..., failure_review=...)`。旧单条审计命令和历史追加行为保持兼容。

同一证据锁内先核验原失败和可读正文，登记04A错误回执处置，再执行原08B失败及重试判断契约；全部通过后只写一次 evidence，材料进度只计算一次。04A处置的 reviewer 可复用08B reviewer，reason 可复用实际提供的 receipt_review；失败代码、原来源说明、路径、原提交及额度直接读取准确 run。实际材料结论、剩余工作、修复／恢复依据、来源规则和明确重试选择仍须提供，不能从失败响应自动捏造审阅通过。没有正文时用 `receipt_disposition=null`，须明确正文缺失原因；有未读结果材料时继续原处理流程，不能当纯错误回执关闭。

`evidence.failure_closeouts` 是两个原子子事件的共同绑定索引，保存原run哈希、两个子事件哈希及原提交／额度／错误事实；下游08B和04A仍读取原子事件，不新增来源调用、重置消费或授予发布许可。完全相同的当前收尾复用原凭据，第二事件失败时第一事件不落盘；输入或原件在收尾期间变化则拒绝提交。未知提交、零结果与确认未提交不能通过此入口伪装成已确认失败。
