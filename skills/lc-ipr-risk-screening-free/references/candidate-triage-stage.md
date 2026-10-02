# 候选批次、交接、重开与阶段完成（05C）

仅新任务 `triage_stage_revision=candidate-triage-stage-v1` 启用。模块 04 的真实 `source_runs`、逐位置处理和候选来源引用是批次实收与解析去向的依据；本协议投影每批已得材料、已分流候选、待审原始位置、`needs_info`／对象范围／身份定位依赖及入选待交接，并用 `--kind batch-review` 冻结一次实收批次进度快照，不另建执行队列或重计发现额度。新批次追加；旧快照及未审事项保留，冲突／重开、已得未审材料和旧批次轻分流优先于继续执行新来源，优先级只调整顺序，不删除任何候选义务。

已纳入且当前 `selected` 可立即交专项，不等其他来源结束。用 `record_candidate_triage_stage.py --kind selected-handoff` 提交候选、情景、国家／权利方向、当前 `annotation_id`、本次已读 `evidence_refs`、实际 `reading_scope`、未完成核验事实及 reviewer／reason。事件冻结原决定、产品／候选版本、关联比较和身份缺口；未知身份可作为专项缺口传递，但不能伪造具体国家或权利出网资格。交接完成不等于专项核验或整项交付完成。

有来源支持的实质变化使用 `--kind reopen`，列出变化种类、内容、证据、新旧决定关联、直接或合理扩大的受影响范围、依赖义务及合并／拆分归属。受影响旧结论立即暂停当前可用性，旧证据与阳性材料留存；未受影响方向继续。无法归属的拆分部分保持待核对，绝不把旧入选或不入选复制到所有新候选。已有材料足够时先写新决定，再以 `--kind reopen-review` 绑定变化事件、旧／新决定、实际重读证据和依据；同结论必须额外说明继续适用理由。仍不足时按 05B 补证、等待或保留限制；访问恢复本身不自动触发重开。仅来源包装重复且事实内容一致时用 `--kind duplicate-reference` 追加引用，实质内容不同会被拒绝并应走变化审阅。

`next_work.candidate_triage_stage` 独立给出每批进度、本模块 `normal_complete`／`waiting`／`limited`／`in_progress` 及当前材料／版本摘要。仍有原始位置未处理、已得候选未分流、`needs_info`、待确认范围、待复核决定、已入选未准确交接或正在返回的来源时，不会给出正常完成。等待须有具体依赖，受限须有真实硬限制且无待恢复事项；它们不是义务满足。来源仍在返回时只说明已得批次进度，新候选和实质变化重算投影；专项核验、独立风险审阅及交付仍各走原门禁。

命令：

```bash
python scripts/record_candidate_triage_stage.py --task-dir /absolute/run --kind batch-review --input /absolute/batch.json
python scripts/record_candidate_triage_stage.py --task-dir /absolute/run --kind selected-handoff --input /absolute/handoff.json
python scripts/record_candidate_triage_stage.py --task-dir /absolute/run --kind reopen --input /absolute/change.json
python scripts/record_candidate_triage_stage.py --task-dir /absolute/run --kind reopen-review --input /absolute/review.json
python scripts/record_candidate_triage_stage.py --task-dir /absolute/run --kind duplicate-reference --input /absolute/duplicate.json
```
