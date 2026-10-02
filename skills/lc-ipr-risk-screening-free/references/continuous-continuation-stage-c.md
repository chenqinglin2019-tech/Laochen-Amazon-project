# 08C 恢复前对账、访问与主动暂停

仅新任务启用 `continuous_continuation_revision=continuous-continuation-stage-c-v1`。`record_continuation.py --task-dir DIR --input EVENT.json` 只向原 `evidence.json.continuation_events` 追加控制事件，不发来源请求，也不改变原回执、预算或完成结论。`next_work` 的 `active_pauses`、`access_requests` 和原工作项仍是同一待办视图。

用户明确暂停、停止或换题时，记录 `kind=pause`、`actor`、`reasoning`、`intent=pause|stop|switch`，范围为 `{"level":"task"}` 或 `{"level":"right_type","right_type":"patent"}` 等准确方向。任务级停止所有工作；方向级只影响该方向，其他方向继续。主动暂停会阻止直接 API／浏览器调度和发布；待办显示原状态与原因，不将暂停写成业务完成或执行受限。仅登录反馈、补资料或等待时间不会解除主动暂停。历史任务保持原合同。

恢复先用同一记录器追加 `kind=reconcile`，引用活跃 `pause_id`、`original_target_sha256`、准确 `remaining_work` 的 work IDs、逐项 `dependency_checks`（每项含 `condition`=待办 work ID、`verified` 与具体 `basis`），以及 `material_review`、`evidence_reuse_review`、`retry_and_budget_review`。`historical_evidence_reviews` 必须逐一覆盖快照中已成功、零结果或留有原文件的来源运行，绑定 `source_run_id`／SHA-256，并填写对象、范围、版本、用途、原取证时间、评估日、稳定内容或动态事实、复用或重核决定及依据；旧动态事实若要直接复用，还须给出当前事实依据。记录器核对原目标、当前商品、该方向的计划版本、原来源运行／提交事实、未知名额、历史尝试、材料和剩余待办；快照及审核说明永久留存。若目标、商品或该方向计划在暂停期变化，先走 02 的受控变更入口，并在对账中准确引用暂停后新增的 `product_change_history[].change_id`；没有完整、哈希有效的上游变更链会被拒绝，不能将打开的新页面或直接改写当作旧任务继续。上游变化的受影响问题仍由其自身机制定向复核，原取证时间不被改写。

随后须有明确 `kind=resume`、`pause_id`、对应 `reconciliation_id` 与 `explicit_resume_intent`。若对账后来源回执、材料或其他事实变了，旧对账快照失效，重新对账。解除主动暂停也不解除未验证的访问、资料、提交未知或来源次数门禁；只续原工作未完成位置，原计数、阳性材料与已完成部分保留。资料缺口仍由 `record_product_feedback.py` 和上游产品范围记录处理，实质变化的受影响结论仍由上游定向复核，08C 对账不替它们作完成决定。

标为 `recheck` 的历史动态事实在统一待办中形成 `HISTORICAL_DYNAMIC_FACT_RECHECK_REQUIRED`，原结论在重核前不得当作当前事实。获得新来源运行并完成原始材料处理后，可追加 `kind=evidence_recheck_complete`，绑定 `reconciliation_id`、原 `source_run_id`、新 `replacement_source_run_id`／SHA-256、`object_match_basis`、`scope_match_basis`、`fact_review` 和 `material_review`。新运行须有较晚的实际时间、成功回执和有效留存文件；这只关闭来源事实重核待办，受影响专项结论仍由各自记录器复核。

`next_work.access_requests` 按来源及同一访问原因合并关联工作，给出只需用户完成登录、验证码、MFA、扫码或访问同意的操作与验证方式。`kind=access_notice` 引用当前 `dependency_key`，重复同一依赖、工作集合与能力版本的提示会被拒绝；新增受影响工作或实际能力版本变化允许更新一次。`kind=access_feedback` 记录 `query_capability_verified=true|false` 与 `condition_basis`，保留用户反馈；“已登录”本身不证明原查询能力恢复。不能把业务检索和材料整理转给用户，也不能以提示、反馈或沉默关闭业务义务。

08C 只处理主动暂停、访问依赖及恢复前对账；逐工作无进展诊断与技术停止由 08D 处理，原 51 条在 08D 后整体验收。真实来源访问与时效仍须实际任务核验。
