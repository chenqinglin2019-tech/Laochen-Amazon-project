# 必要方向与两次语义审阅（03B）

新任务冻结 `discovery_semantics_revision=discovery-semantics-v1`；旧任务无此标记，沿历史计划恢复。先以模块 02 的 `product-scope-input-v2` 登记对象、事实性质、来源、待确认问题及方向依赖，再生成检索计划。来源路线缺失不能删掉必要方向；每个销售情景、国家／权利层和权利类型分别核对。同一 Signa 多 office 请求可用一个计划行与一次来源运行服务多个国家；每国的方向、事前表达和结果审阅仍独立绑定。单次执行与计数已由离线 A043 用例验证，真实来源效果另需授权回执。

使用 `record_discovery_semantics.py --task-dir DIR --input REVIEW.json` 依次保存三类审阅：

1. `stage=direction`：填写 `scenario_id`、`jurisdiction`、`right_type`、`reviewer`、`reason`；`directions[]` 须逐一覆盖当前范围中的方向，记录 `direction_id`、`question`、准确的 `clue_ids`、`method`、`proposed_sources`、`evidence_needed`、`supplement_trigger`。`clues[]` 须逐一处置这些方向引用的事实 `fact:<id>` 及对象 `object:<id>`；完全未被任何方向采用的范围事实另列 `unmapped_clues[]`，不可直接写成已纳入。处置状态为 `included`、`irrelevant`、`awaiting_information`、`awaiting_capability` 或 `covered_by_other`，逐项写理由；复用必须给 `evidence_refs`。其他原始重要线索仍按商品分析的线索去向检查，不能因没有进入本权利方向而静默消失。只有确实无关的线索可排除，资料或能力不足继续进入待办。
2. `stage=before`：对拟提交的每条发现查询、每个适用方向填写 `query_id`、`direction_id`、相应范围、`reviewer`、`reason`、`semantic_fit`（`full`／`partial`／`mismatch`）、`expression_reason`、`concepts_in_query`、`uncovered_clues`、`independent_structure` 和 `whole_product_constraint`。记录器绑定实际 `q`、完整计划行摘要、目的、版本和最新方向审阅。独立部件／结构查询不应默认被整体品名限制；确有必要附加时写 `constraint_reason`。`partial` 可执行但不能直接完成方向；`mismatch` 阻止提交。分类查询另填 `classification_basis` 的来源、含义和产品适用性；翻译／当地语言表达另填 `language_basis` 的原词、提交词、来源及派生关系。审阅实际来源参数和专用字段，不以线索引用、营销标题或全文模拟字段检索。
3. `stage=after`：取得成功或真实零条的来源回执后，填写 `source_run_id`、对应的 `evidence_refs`、`original_problem_checked=true`、`problem_covered`、`result_reason`、`uncovered_clues`、`excluded_by_narrowing`、`next_action`，并保留同一范围与查询身份。记录器绑定此前审阅、实际运行及留存证据。零条、有命中或候选减少都不自动证明充分；宽查截断后窄查仍须核对被排除内容。若未覆盖，`next_action` 选定调整、换源或待补事实／能力，原缺口继续显示。

`after.problem_covered=false` 默认仍投影为可执行复核。只有 `awaiting_information` 精确对应当前方向审阅中等待用户提供的线索，或 `awaiting_capability` 同时绑定同一 query/run 的有效有界停止审阅（所有已获取卡片均已合并分流且无保留的可执行跟进）、完整来源回执、精确来源操作 `accepted` 且分页结论为 `single_page`，并由该回执证明仍有未取结果时，才可转为外部等待。另有一条限于真实来源错误的等待：结果处理器必须以原始字节摘要证明 `non_result_error`、无解析结果且 `zero_proven=false`；同一运行须有当前 API 有界停止审阅及来源操作 `rejected`（分页/字段效果未知）。该状态显示 `SOURCE_FAULT_UNVERIFIED`，仍明确覆盖未知，不把 fault 记成零条，也不关闭有效后继查询。两种等待都不能有未分流/待跟进卡片；缺少任一绑定则继续显示可执行待办。`refine`／`fallback` 继续生成计划修复。

对某个 `classification` 官方轴，若同一当前 query/run 已通过上述完整 bounded-stop 校验，且其所有已取结果均完成合并和分流，可以把该轴标记为本轮 `BOUNDED_DISCOVERY_OFFICIAL_COVERAGE_UNVERIFIED` 外部限制。它只说明本次报告未检索剩余页；不证明分类检索完整，也不排除其它官方路由。其它 purpose、候选核验、来源和材料工作仍以独立 work entry 保留，并继续阻断报告发布；静态参数编译器能列出的未实际编译/执行替代路由，不会单独让同一分类轴无限重复计划。

每次审阅以任务中的追加式事件和本地原始收据保存；只对该方向实际依赖的事实／对象变化使相关旧审阅失效，无关事实更新不重开该方向；查询行变化使该查询的提交前／结果审阅失效，但不删除旧查询、回执和阳性材料。执行前检查缺少方向或表达审阅时只保留待审状态，不将查询永久取消；结果审阅及已取得材料未处理完时，工作视图与覆盖仍有缺口。语义是否匹配须由审阅者判断，程序只校验范围、事实／对象清单、实际参数、版本、来源回执与审阅结论之间的绑定。

历史查询已真实提交，而其当前before审阅缺失或因方向变化失效时，统一待办进入既有DISCOVERY_DIRECTION_GAP_REPLAN_REQUIRED计划复核，并标记historical_expression_review_missing及原source_run_id，不要求补写提交前审阅。未提交查询仍须before；实际提交门禁和TOO_LATE拒绝不变。历史证据须审阅复用依据与剩余缺口，计划复核不授权重提交、不新增目的或恢复预算，也不自动完成方向。
