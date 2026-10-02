# 候选身份、关系与纠正（04B）

仅新任务使用 `candidate-identity-v1`；历史任务不迁移。`merge_candidates.py` 为每条真实来源行生成稳定 `source_anchor`，保留 `sources[]`、`field_claims`、`original_identifiers` 和规范化号码。专利只有带主管局和文献种类的准确公开文献号才自动合并；同申请的 A1/B2 仍是两个候选。商标及公开记录只按明确号码和号码种类合并；标题、权利人、商标文字、图片相似或来源 URL 均不单独证明同一对象。残缺号码或无号但指向具体对象的来源行保留为 `identity_pending` 候选，未知权利类型保持 `unknown`，不得从查询范围猜补。普通导航／登录／错误内容由 04A 记 `non_candidate` 与依据。

`normalized-candidates.json.identity_relationships` 分开记录同申请、同族、同标题疑似重复和来源声称的地域关联。同标题仅建立 `review_required` 提示，不作为同一对象证明。家族清单中的号码放入 `member_leads`（`lead_only`），不生成独立已得权利、继承父记录来源、状态或风险。区域权利和国家适用声明仍待模块 06—07 核实；关系本身不新增检索额度或转移分流结论。

确有原材料证明合并／拆分／字段取舍时，先审阅来源行锚点、候选 ID 和原证据，再将单个 JSON 输入传给 `record_candidate_identity_correction.py --task-dir DIR --input FILE.json`，随后重跑 `merge_candidates.py`。每次事件追加到 `candidate-identity-corrections.json`，记录审阅人、理由、原文摘录和证据引用；旧事件不覆盖。未重跑 merge 前不能登记下一次纠正。

- 合并：`{"kind":"merge","candidate_ids":["CAND-A","CAND-B"],"evidence_refs":["EV-A","EV-B"],"reviewer":"agent","reason":"同一具体对象的原文依据","quote":"原文摘录"}`。整组来源行以新稳定身份投影，`identity_aliases` 保留两个旧 ID 指向新 ID；新出现的同名弱线索不会自动加入。
- 拆分：`{"kind":"split","candidate_ids":["CAND-OLD"],"partitions":[["SRC-..."],["SRC-..."]],"evidence_refs":["EV-A","EV-B"],"reviewer":"agent","reason":"误合并依据","quote":"原文摘录"}`。分组必须精确覆盖原候选全部来源行；旧 ID 映射到全部新 ID，旧材料只归各自来源组，旧分流判断不复制到拆分后的候选。被拆分身份的旧自动归并键同时作废；后续相同号码的新来源先单列待核对。
- 字段取舍：`{"kind":"field_selection","candidate_ids":["CAND-A"],"field":"owner","selected_value":"B","evidence_refs":["EV-B"],"reviewer":"agent","reason":"核对来源","quote":"原文摘录"}`。所选值必须在该候选的有来源字段声明中；备选值和来源不删除。当前采用值与事件 ID 保存在 `field_resolutions`。
- 关系：`kind=relation`，`candidate_ids` 恰为两个，`relation` 可为 `same_application`、`same_family`、`territorial_applicability`、`suspected_duplicate`；均须原文摘录与相关证据。关系只组织记录，不自动合并或传递结论。

`right_type=unknown` 的候选仍可在模块 05 的产品进入／真实转售情景做结果级轻分流：有足够来源依据时记 `not_selected`，缺关键事实时记 `needs_info` 和最小动作。未启用 05A 标记的历史任务，类型未确定时沿原合同禁止 `selected`；启用 `candidate-triage-scope-v1` 的新任务，已读具体关联可先 `selected` 并保留类型定位缺口，但不派生专项出网核验。品牌复用情景仍须先确认商标类型及品牌范围，未知类型不能借该情景自动入选。候选引用的实质身份纠正使旧判断按候选 ID／身份摘要失效并进入既有审阅流程；重复发现若没有新增事实，只补来源引用，不重开内容判断。执行时预算和增量交接由 04C 处理。来源事实的语义正确性仍需审阅人核对原文；程序只检验来源引用与批次结构，不能代替原文判断。
