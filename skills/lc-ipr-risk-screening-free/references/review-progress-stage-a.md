# 09A 唯一计划项与进度

新任务启用 `review_progress_revision=review-progress-stage-a-v1`。生成查询计划后、任何来源提交前，用 `record_review_progress.py --task-dir <目录> --input <JSON>` 追加 `initialize` 事件。首次事件可用空 `items` 表示当前核实无待执行项；此时 C/N 为 `0/0`、百分比为 `null`，绝非 100%。未初始化时 `next_work.review_progress.status=plan_required`；此阶段兼容旧执行入口，不把未登记的旧运行追认成完成项。初始化之后，只允许已登记且仍处于计划中的原查询继续提交。

每个工作项写稳定的 `ITEM-...`、`kind`（`query` 或 `issue`）、`scope`（`scenario_id`、`jurisdiction`、`right_type`、`product_version`）、`module_ids` 和具体 `acceptance_condition`。查询项另写计划中的 `query_id`，问题项另写 08A 中当前精确开放的 `issue_id`。同一义务不能换编号或改验收文字再加入；一项可属于多个专项，整体只计一次，专项小计注明重叠。计划版本按事件递增，保存变更前后 C、N；不能覆写历史。

输入示例：

```json
{"kind":"initialize","actor":"agent","reasoning":"按已核实范围预先定义查询义务","items":[{"item_id":"ITEM-US-PAT-1","kind":"query","query_id":"<计划中真实 query_id>","scope":{"scenario_id":"<真实情景>","jurisdiction":"US","right_type":"patent","product_version":"<当前产品版本>"},"module_ids":["M03","M06"],"acceptance_condition":"原查询提交成功或真实零结果，原始回执可核对"}]}
```

`complete` 必须引用当前计划项及现存事实 `evidence_refs`。查询项还须提供 `source_run_id`，运行记录须与原提供方、query_id、计划行指纹一致，确认为已提交的成功或真实零结果；等待、失败、提交未知及仍需执行的原查询不能完成。问题项必须在统一待办中不再开放，并有原事实引用。共用一次执行可以分别完成多个**预先登记**的不同项，绝不把运行次数当完成项数。完成查询不等于风险已核实、双审完成或可发布。 本地公开调查的读取引用同时按原 `scenario_supplement` 合同核验补充材料并加入注册表；仅补充文件存在不代表步骤完成。真实已读公开步骤可以完成查询，私人供货授权／作者记录仍独立保留，缺引用、原件变化、公开待办或非法私有依赖仍拒绝。

`known-findings-risk-v1` 或 `operator-report-v1` 的查询验收使用原运行哈希绑定的 `effective_submission/effective_result`：合法提交审计已证明提交且真实响应成功时，可追加完成事件；原 `submission_state:unknown` 和原运行记录保持不变。已审“submitted_failed”仍是失败，不完成。新的完成事件同时保存原 run 指纹、有效提交状态和实际结果。真实零结果须重新校验留存原件、原查询与计数投影；`no_result` 字符串、404、空摘要或失败正文都不能单独验收。已留存 OPS `NoResults` 精确 XML 可按原零行规则验收，无需再提交查询。漏记完成通过追加事件修正，不修改旧签名、不删除失败项提高百分比。

覆盖总状态使用同一已采信检索、分流和核验步骤：三个子状态均 complete 且无真实缺口时显示满足已定义要求；仍有独立事实／语义限制时显示部分完成并保留缺口。不得因为空的执行义务集合把已完成步骤重新显示为“待执行”。风险独立读取新评级策略，不由该覆盖状态决定等级。

多条查询完成可以向同一记录器提交 `{"kind":"complete_query_batch","completions":[{"kind":"complete","item_id":"ITEM-原编号","source_run_id":"ATT-真实运行","evidence_refs":["ATT-真实运行","EV-真实材料"],"actor":"实际审阅人","reasoning":"具体完成依据"}]}`。仅允许非空、无重复 item 的 query complete；问题项仍走原单条入口。单一证据锁内构建一次真实统一待办，每条使用原完整验收函数；绑定任务、计划、候选、分流、补充及已声明原件的当前内容，期间变化即整批拒绝。整批验收后一次写入，逐条保存原 complete 事件、版本及 C/N 前后历史，不跨调用缓存，也不因采用批量而删除原查询缺口。任何一条失败均不追加本批完成记录。

`add`、`remove`、`exempt`、`reopen` 均需 `upstream_ref` 指向已有上游变更／核实事件，并写具体 `reasoning`；`add` 提供新 `items`，后三者提供 `item_id`。移除和免做从当前 C、N 同步剔除，重开原已完成项只减 C、保留旧完成证据。新增项增加 N；不可因失败、访问受限、暂停或技术停止自动移除／免做。

产品范围版本相邻递增且某查询义务本身未受影响时，可用 `rebind` 将原 query item 绑定到新版本，不换 `item_id`、不改 `acceptance_condition`。目前仅接受可解析且相邻的整数版本（如 `2→3`）或 `V` 加整数版本（如 `V1→V2`）；跳过中间版本或无法判定相邻关系时拒绝重绑，应按当前范围新建必要义务并重审。输入须指定 `item_id`、真实 `product_change_history.change_id` 作为 `upstream_ref` 和理由。只允许同一计划行哈希、提供方、查询、国家和权利范围保持不变，且上游变更未列出该查询/其产品方向、事实或对象为受影响项；存在受影响候选而无法将候选影响排除时拒绝重绑。问题项、版本未变、计划哈希变化、变更事件不真实或版本不匹配均拒绝。重绑以追加事件保存旧/新版本和原条目指纹；完成条目转为待办，旧完成凭据移入历史且不被修改，必须按当前版本重新完成验收。重绑只处理当前义务的范围版本，不声明风险审查或双审完成。

示例（只适用于已证明未受本次产品变更影响、且计划行哈希未变的 query item）：

```json
{"kind":"rebind","actor":"agent","reasoning":"CHG-真实编号 未改变该查询依赖；原查询及计划行哈希不变，需在新产品版本重新完成验收","item_id":"ITEM-原稳定编号","upstream_ref":"CHG-真实编号"}
```

任务当前进度读取 `next_work.review_progress`、`advance_work` 状态；`by_scope` 按情景、国家、权利类型、产品版本分组，`by_scope_module` 是可重叠小计。

09A 仅交付计划与工作进度。风险等级、双审和初步阶段报告仍分别由 09B—09D 实施；当前 100% 也不是完整交付许可。旧任务没有该标记，继续旧投影，不补标记迁移。

本地asset_provenance/provenance_review调查不向外部提交请求，保留not_submitted。唯一计划项完成仅接受同计划行、同当前范围的success/local_agent_review回执，且单一对应证据的文件哈希有效、原生investigation_complete成立（全部当前对象已审、该调查步骤完成、无剩余调查动作）。partial、其他提供方/操作、失败或未知不适用；调查完成不等于未知权属、授权或功能性条件成立。
