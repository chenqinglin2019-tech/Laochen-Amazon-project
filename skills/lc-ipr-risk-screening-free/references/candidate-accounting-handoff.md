# 执行计数、范围复用与增量交接（04C）

新任务使用 `candidate-acquisition-v1` 和 `candidate-handoff-v1`；历史任务不迁移。浏览器发现回执进入 `record_result` 时，在同一 `source_run` 留 `candidate_acquisition`：每条已解析卡片的位置、执行时准确身份或临时身份、当次新增去重数及累计数。准确文献多次命中只消耗一个身份；身份不完整的不同来源行分别消耗。原回执已得超额卡片全部保留。后续合并、拆分和交接只更新 `normalized-candidates.json` 当前统计，不重写原始执行收据或返还五十候选名额。本地补解析向 `result_parses` 追加身份键，执行消耗按原收据与追加解析合并计算，原 `source_run` 不改写。未解析的已得位置单列 `unparsed_result_positions`，核清前暂停同目的浏览器继续获取；有效页数仍按 03A 真实执行规则累计。

`discovery_budget.snapshot(..., candidates=normalized_candidates)` 同时给出 `execution_consumed_count` 与 `current_candidate_count`。前者取冻结的来源执行收据，后者仅是当前候选投影；同申请或同族关系不减少实体数。来源操作、取得页、路线与证据独立性仍按已有合同审阅，计数不证明覆盖完成。

`next_work` 将有可审来源的候选列为 `CANDIDATE_HANDOFF_READY`。Agent 对具体候选、情景与国家分别核对适用性后，向 `record_candidate_handoff.py --task-dir DIR --input FILE.json` 提交批次：`candidate_ids`、`reviewer`、`reason`、`scope_reviews[]`；每个范围审阅含 `candidate_id`、`scenario_id`、`jurisdiction`、`applicability`（`applicable`／`not_applicable`／`unknown`）、`reason` 和该候选已审来源的 `evidence_refs`。可以先交一部分范围或候选；同一真实运行与候选只保留一份，多个范围引用同一来源，但逐范围理由独立。`unknown` 是待核实的交接状态，不是覆盖或法律结论。重交同一内容幂等；身份或实质内容变化会重新列出受影响候选，纯重复发现不会重开内容交接。

`candidate-handoffs.json` 按批次追加，记录当时身份／内容摘要、已审与待处理来源、范围审阅及前一批次校验 ID。`next_work.candidate_handoff.material_processing_complete` 只在相关已得回执逐位置解析、入库、去向核对完成后为真；候选局部交接不把其他待解析结果标成完成，也不代表模块 05 分流、必要方向覆盖、双审或整项任务交付完成。未知身份、未定位引用与待解析材料继续留在统一待办，模块 05 决定无关或最小补证。已有导入和历史证据复用保持原入口、原时间、适用性审阅；本交接不制造新请求或独立来源。
