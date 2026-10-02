# 对象范围与方向级推进（01B）

本协议只用于 `product_scope_revision=object-scope-v1`。新任务有 `product_scope_required=true`，身份冻结后必须先登记范围；旧任务不自动补版本。01A任务如需采用本协议，Agent 明确执行记录器的 `--migrate`，保留历史计划和证据；旧行未具备依赖绑定时进入复核，不冒充已覆盖。

新商品的 `product-scope-input-v2` 在本协议上补齐[02A 图像与事实交付](product-delivery.md)；v1 输入保持原合同，不会静默获得 v2 性质、许可或主图覆盖声明。已激活 v2 的任务不能降回 v1。

## 业务规则

- 默认拟售功能、结构、外观一致且用自己品牌的同款商品。默认假设不是一致性证明，更不是自有品牌已清查。
- 盘点观察对象、位置和来源，再判断目标关系与用户意图。参考品牌/Logo、参考摄影、普通附属包装默认未纳入；目标商品本体、固有装饰及作为目标的礼品盒/装饰画不能按附属物排除。
- 四态是 `included/default_excluded/user_excluded/pending`，分别对应已纳入、按默认未纳入、用户明确未纳入、待确认。明确使用/不使用须引用真实用户说明；不得把代理猜测标为用户说明。
- 只有资料核查后仍存在会改变范围的实质矛盾才问具体对象。`pending` 必须有 question 和 checked_information；问过后记录 `--mark-question-asked WORK_ID`，同一未决问题不反复询问。该标记不替代用户答复。
- OWN 与 REFERENCE 是不同对象；明确复用参考标识才启用 brand_reuse。查询绑定对象来源，参考品牌结果不计入自有品牌清查。正品转售须已有明确 genuine_resale 请求，不能从照片推断。

## Agent 记录格式

用户只提供产品与说明，不填写 JSON。Agent 依据现有资料生成 UTF-8 JSON，再执行：

```bash
python scripts/record_product_scope.py --task-dir /absolute/run --input /absolute/scope.json
python scripts/next_work.py --task-dir /absolute/run
```

顶层包含 `schema_version=product-scope-input-v1`、`expected_scope_sha256`（首次为空，补充使用当前摘要）、`sources`、`scope`，可附 `query_terms`。scope 是完整的当前范围快照，不是局部覆盖补丁，含 status=reviewed、reviewer、reasoning、objects、facts、directions，可附 candidate_links。

- sources：唯一 source_id，kind 为 user_statement/document/agent_observation，path 或 text 二选一；user_statement 必须为实际用户说明文本。文件复制留存，说明与其 hash 绑定留存事件。
- objects：稳定 object_id、kind（product/brand/logo/pattern/photograph/packaging/other）、relation（target/integrated/reference/ancillary/own）、intent（default/use/do_not_use/uncertain）、description、location、reason、right_types、source_refs。非 default 另有 statement_refs，使用 sources 中的 source_id 或已留存证据 ID。scope_status 由记录器计算。品牌文字可附 text/language；Logo 描述用于有来源的 mark_description 词。
- facts：稳定 fact_id、source_path、value、status（confirmed/unknown/conflict）、source_refs、reason；未确认项必须有最小 question。product.* 与 images[*] 路径的值必须对应现有资料，不能用范围录入偷偷修改冻结产品；新说明/新图可用 `evidence:EV-ID` 路径引用留存来源，并把相关检索词 derived_from 指向该事实。
- directions：稳定 direction_id、scenario_id、right_type、fact_ids、object_ids、reason。明确“哪项工作实际依赖哪些事实”。不同范围状态对象必须拆开方向；同一权利类型内独立结构也分别建方向。纳入对象没有方向时保留 Agent 复核；待确认对象没有方向时仍保留用户待办。
- candidate_links：候选合并后记录 candidate_id、object_ids、source_refs、reason。候选 ID 必须存在，关联依据必须留存；查询命中上下文不自动证明候选涉及某个对象。未定位的候选进入范围复核，已纳入后才使用既有 selected/needs_info/not_selected 相关性结果。

对象编号要与素材 asset_id/mark_id 一致，或在素材条目显式提供 object_id。来源调查只采用 included 对象；待确认不能算已审阅空清单。范围和相关性都不等于风险等级。

## 局部推进与补充

身份不明仍阻断依赖身份的工作。范围版本以方向依赖取代“整份产品资料全部充分”的门槛，但保留专利声明追查、线索交接和原有证据要求；未建方向的必要权利仍有覆盖缺口。

首次无计划也能运行 next_work/advance_work。已有计划出现局部冲突时，API 和 Browser 在提交前暂停相关动作，记 deferred/not_submitted，不创建零结果、扣费调用或永久取消；共享请求可在仍有效情景下使用，但未满足情景不计覆盖。查询本身用到的全部事实必须充分。

收到答复或新图，追加真实 sources，提交完整 scope 和当前 expected_scope_sha256。不得覆盖旧来源、旧查询或阳性材料。仅充分性/来源补足、查询实际内容不变时，原查询恢复使用；实际对象或内容改变则保持复核，按新的有依据术语扩展计划或原有显式查询更正流程处理。不得通过新任务、改次数或改 query_id 来绕过授权及预算。

补充后执行 `generate_search_plan.py --expand` 和 `advance_work.py`。未受影响方向和具体候选的判断摘要保持稳定；受影响判断必须重新审阅。整份最终双审仍使用新的冻结输入摘要，不重写历史审阅来冒充已复核。首次证据写入后任务写入中断，可重试同一输入恢复；跨目录用 resume_continuous_work.py 创建带清单的恢复副本，不能普通复制后改绝对路径。

HTML/Markdown 沿用既有版式，显示角色与来源、默认假设、四态对象及依据、局部问题。未纳入不显示低风险，局部完成不冒充全局完成。来源授权、零支出、双审与发布门槛保持原合同。

实际事实内容改变，但已有查询表达经审阅仍准确时，可在 scope 中增加 `query_revalidations`：每项填写新的唯一 review_id、既有 query_id、整行的 plan_entry_sha256、source_refs、reason。记录器验证原计划身份、全部方向已就绪并绑定当前方向摘要；旧行与查询次数不变。携带旧 review_id 时保留原摘要，不隐式刷新；新判断必须使用新的 review_id。后续内容再次变化时该复核自动失效；仍有冲突的方向不可通过此入口强行放行。它只确认查询继续适用，不认可旧比较或旧风险结论。

新任务 `api-first-v3` 的产品方向依赖按当前情景及权利的实际对象计算：没有适用对象、或适用对象全部明确未纳入时，空方向不产生产品依赖缺口。included/pending 对象缺方向、已有方向中的未知产品事实仍阻断；这不证明某项权利已检索完成或法律上不适用。旧版本保持原空方向语义。
