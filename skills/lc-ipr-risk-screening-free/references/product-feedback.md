# 比较阶段最小事实反馈（02C）

在 `product-scope-input-v2` 已交付且下游确实缺某一产品事实时，先核对现有资料。仍不足时用 `record_product_feedback.py --task-dir DIR --input INPUT` 记录 `product-feedback-v1` 请求。模块 03 的规划请求用 `stage=search_planning`，候选比较用 `stage=candidate_comparison` 并提供真实 `candidate_id`。两者均须绑定当前目标和范围摘要、已有 `direction_id`／`fact_id`、具体国家、用途 `purpose`、最小资料 `minimum_information`、精确问题、原因、请求者及真实 `source_refs`。不能在反馈中另造事实或把整份产品资料笼统推给用户。

请求进入现有统一待办 `PRODUCT_FACT_FEEDBACK_PENDING`，工作编号稳定且能记录已问过的问题；待补候选不能给当前确定风险等级，其他无依赖方向继续。反馈事件、来源和当时的事实版本不可原位改写；明确换目标后旧请求保留历史，但不阻断新目标。

取得资料后仍由 `record_product_scope.py` 提交完整 v2 范围快照：使用原 `fact_id`，提高 `version`，更新值、核对状态、来源及相关方向。比较阶段的答复必须有 `status=confirmed, verification=verified` 的事实；只把另一段未经核实声明改写进去不能关闭比较缺口。提交后用同一记录器输入 `action=resolve`，填原 `request_id`、当前目标／范围摘要、审阅者、理由和新事实的来源引用。记录器要求该事实的版本已推进且有对应的 02B 变化事件；受影响候选仍须按 02B 审阅历史材料适用性。

两位独立审阅者要基于更新后的输入摘要重新比较受影响候选；旧审阅摘要不再匹配。反馈关闭不等于候选适用、检索覆盖充分或法律结论成立。补证后只复核事实实际影响的方向、查询、候选和判断；需要追加检索时沿模块 03 的原目的、版本与预算边界处理，不因反馈创建额外免费额度。
