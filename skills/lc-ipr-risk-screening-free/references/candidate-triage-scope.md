# 候选范围、身份定位与三路决定（05A）

本协议适用于新任务 `triage_scope_revision=candidate-triage-scope-v1`；历史任务保留原分流合同，不补版本字段。任务目标国、查询入口、候选来源身份和对象范围分别记录。查询曾在美国外观方向取得线索，不代表候选就是美国外观权利。候选国家不在目标国或未知时，台账先显示一条 `UNLOCATED` 范围；权利类型未知保持 `unknown`。只有逐范围的已读依据才能增加明确目标国决定，不能自动铺满所有目标国或权利类型。

先在 [对象范围](product-scope.md) 的 `candidate_links` 以来源引用把稳定候选 ID 关联具体产品对象。`default_excluded`、`user_excluded` 只登记范围去向；`pending` 保留范围核查待办。部分纳入时只对 `included` 对象做相关性分流，其他对象继续保留各自去向。对象未纳入不能写成 `not_selected`，相关性不明也不能借身份未知改成用户对象用途待确认。

新任务向 `annotate_materiality.py` 提交每条 `decisions[]` 时，除原字段外填写：

- `candidate_relation`：`product_object_ids` 为已纳入且已绑定的对象；`direction_ids` 为这些对象已就绪的方向（入选至少一项）；`scope_reason` 写明关联；`evidence_refs` 指向本次已读材料；`identity_gaps` 明确尚未知的 `target_jurisdiction`、`right_type`、号码或其他身份缺口。有缺口时另填 `identity_location={reason,affected_work,next_action}`，写清未定位原因、受影响工作和最小定位动作。关联材料引用必须包含在决定的 `evidence_refs` 内。
- `comparison`：`candidate_content`、`product_content`、`relationship` 分别写候选实际可读内容、所比较的产品对象与两者的具体关系。`selected` 加 `investigation_question`；`not_selected` 加有证据的 `difference` 与 `applicability_limit`；`needs_info` 加 `missing_fact_effect`、`completion_condition` 和 `existing_material_review`，另保留原合同的缺口与最小动作。排名、相似度、空结果和读取失败本身都不足以排除。

证据已足以证明某项具体结构关联时，即使案号残缺、国家或类型未知，也可先 `selected`；把未知身份交给定位待办。摘要模糊到无法判断关系时用 `needs_info`，先审现有材料。已读资料足以证明特定范围内无实质关系时才用 `not_selected`，它不等于法律不侵权或全家族排除。决定绑定候选内容、证据、情景、对象及方向摘要；身份纠正或范围变化使受影响决定变为待复核，历史记录与旧阳性材料保留。

`selected` 只是相关性决定。只有候选实际来源国家等于目标国、权利类型已知、当前决定有效且专项操作原有条件均满足，才可派生国家／权利专项出网动作；手工计划也经过同一身份门禁。来源国未知、非目标国或权利类型未知时，统一待办提示定位，不自动读取全族或把 `UNLOCATED` 当作实际国家。决定性地域／期限事实在下游专项记录处理，不反向改写相关性；读取失败保留入选和核验缺口。

完整美国实用文献号码和 A/B/C/E 种类码按现有 office-kind 规则投影为 patent，不从查询方向推定类型。植物文献、缺少可确认种类码或未知种类继续 unknown；WO 仍保留非美国来源和 UNLOCATED 范围，不借美国召回查询继承美国权利。

无身份合同、无 API-first 标记的旧 Serper/SerpAPI 记录沿用原显式 right_type 和键，不自动迁移旧口径；当前身份合同及官方 EPO 公开号投影使用上述准确类型规则。
# 公开销售线索的有界身份调查

仅 `api-first-v3` + `public-discovery-v1` 支持 `record_public_identity.py --task-dir ... --input ...`。适用对象限定于 `copyright_assets` 中 Lens 公开视觉销售／来源卡片：无登记号或权利要求，类型与权利地域仍未知，已有当前 `UNLOCATED/unknown` 关联入选决定，且没有可执行补图、阅读或其他 `next_actions`。

输入保留 `candidate_id/scenario_id/jurisdiction=UNLOCATED/right_type=unknown`，明确 `reading_purpose=source_association`、`individual_image_use=not_used_for_expression_or_authorship`，以及 `unresolved_facts` 中的 `right_type/rights_holder/first_publication/supply_chain_authorization`。还需指定五个 `shared_query_ids`：版权来源、视觉比较、商业外观公开使用、来源识别及功能性；提供 `reviewer/reason/resume_condition`。记录器复核原始位置和卡片标题／链接、当前轻分流、共享实际影像与文本的完整读取凭据，以及具体供应商授权／原创材料依赖。

记录采用追加形式并绑定当前候选内容、来源、情景、原查询和共享材料。有效记录只支持本轮 evidence 受限交付，不证明登记权利、不补填作者／首发／地域，不授权未知类型专项出网。单个卡片未读图片须明确未用于表达或作者判断；具体补图待办仍需完成。未知专利、商标、维权事件及未审来源不能使用此例外。材料、决定或适用范围实质变化后旧记录不再满足当前义务。
