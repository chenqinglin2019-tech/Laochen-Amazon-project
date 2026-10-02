# 产品事实缺口与结构资料默认规则（02C）

新任务固定 `product_structure_policy=use_provided_else_unavailable_v1`。查询过程中不询问实际结构、内部构造、工作原理或材料细节。先读取已有资料：用户已经提供的结构描述、图纸或文件按实际来源留存并使用；口头／文本说明保持 `nature=user_statement, verification=claim_only`，不得自动变成已核实结构。没有资料或资料不足，默认用户无法提供，不等待用户答复。缺失要素保持 `unknown`／无法判定，继续已有材料阅读、可执行查询、风险分级和报告；不能把未知当作不存在或已经排除。

结构事实和反馈按所需信息填写 `information_category=actual_structure|material_composition|product_performance`；非结构问题填 `other`。来源路径始终保持原位置（例如 `product.bullets[1]`），不能为适配策略改写出处。已规范绑定 `product.structure` 等技术字段的事实也识别为结构；历史反馈没有类别时，仅在技术权利范围按具体内部构造、独立外套、空腔、预压缩、回弹实测等请求文字分类，分类字段、命中文字和依据随限制证明保留，可复核。未知事实仍保存内部分析问题和已有材料核对；程序投影不向用户显示问题。需要记录候选比较的具体缺口时，用 `record_product_feedback.py --task-dir DIR --input INPUT` 留存 `product-feedback-v1` 输入。结构 `action=request` 会记录为 `kind=unavailable` 的不可提供回执；`question` 仅是内部待判问题，不发送给用户。

输入仍须绑定当前目标／范围摘要、已有 `direction_id`／`fact_id`、具体国家、用途 `purpose`、最小资料 `minimum_information`、问题、原因、请求者及真实 `source_refs`。规划缺口为 `stage=search_planning`，比较缺口为 `stage=candidate_comparison` 并提供真实 `candidate_id`。反馈中不能另造事实。新策略启用前已经留存的结构请求按不可提供投影，原回执和事件不改写。

产品结构缺口投影为 `blocked / PRODUCT_STRUCTURE_UNAVAILABLE`，带精确事实／范围／来源绑定的报告限制，不进入 `awaiting_user`。已审阅的未知专项要素须经具体 `gap` 和结果 `followup` 绑定，才可按结构资料不足投影；缺失的比较、未读材料、新未知或失效依据仍须 Agent 审阅。结构资料不足不能关闭真实权利核验、检索覆盖或独立审阅门禁。非结构的品牌意图、授权等反馈保留原定向待办逻辑。

用户之后主动提供资料时，由 `record_product_scope.py` 追加完整 v2 范围快照，使用原 `fact_id`、提高 `version` 并更新来源性质。`action=resolve` 仍要求事实版本推进及对应 02B 变化事件；候选比较须有可核实事实，仅多一段未经核实声明不能关闭比较缺口。受影响候选按 02B 审阅历史材料适用性，两位独立审阅者重新比较受影响范围；其他查询、阳性证据和未受影响判断保留。

历史未启用新结构策略的任务沿用原请求／反馈语义。用户明确采用本默认规则时，仍走同一记录器，输入 `{"action":"adopt_structure_policy","reviewer":"实际操作人","reason":"用户明确要求不再询问结构"}`；它核验原始范围、刷新受政策影响的派生事实交付、留审计依据并失效旧输出绑定，避免只改字段造成 `PRODUCT_DELIVERY_PROJECTION_CHANGED`。原事实、范围回执和反馈记录不改写。明确换目标后旧请求保留历史，不阻断新目标。结构限制解除不等于候选适用、检索充分或法律结论成立；追加查询仍沿原版本和预算边界处理，不创建额外免费额度。
