# 历史评级策略（自 risk-estimate-rules.md 迁出，内容未改）

仅适用于保留 `recall-integrity-v1`、`partial-evidence-v1/v2` 或无评级策略字段的历史任务；新任务不读本文。

## 保留原版本的历史任务

新任务默认使用 `api-first-v3` 与 `final-double-review-v1`，以[API 直接采信与一次最终双审](../api-direct-final-review.md)为优先契约。已采信 API 字段不生成官方网页重复核验；过程保留事实分析，取消 09C 阶段双审前置。下文旧修订仅约束保留该版本的历史任务。

`workflow-correction-v1` 增加必要范围审阅及未来信号资格校验，详见[必要审阅](../workflow-correction.md#必要审阅)。下文“未来信号完成审阅”只适用于有依据的合格信号，不能免除有效当前权利的评级；旧无标记输入保留原计算语义。

适用于明确使用 `assessment_policy=evidence-estimate-v1` 且保留历史修订的任务。`assessment_revision=partial-evidence-v2` 的完整任务仍按既有证据评级，不完整报告也不得将未评范围派生为低风险。缺少该修订的历史任务继续其原分支，不因加载新版 Skill 改写旧结论、计划或证据。

保留 `screening_revision=recall-integrity-v1` 与 `decision_workflow_revision=scenario-triage-v1` 的历史任务按下节情景规则执行；仅有前者的历史任务保持后续“阶段性报告”合同，均不通过加载新代码静默迁移。

## 历史阶段性报告：仅 recall-integrity-v1

- 把执行完成、评级依据和文件完整性分开。无有效相关检索且无具体排除依据时，审阅项使用 `risk:null`、`assessment_status:pending`、`pending_reasoning`，保留已经取得的事实、证据和后续动作；待评不是第六级风险，也不是范围排除。
- 无候选低风险必须有同国家、同权利的合格召回及比较证据，通过 `search_comparison={reasoning,evidence_refs}` 绑定实际检索；产品图、失败请求、整段营销文字的零结果和“没有候选”不能单独满足依据门槛。候选的排除须绑定真实权利/比较证据。
- 同一公开号的已验证补充原文可按完整号码、国家、权利类型及文件身份绑定候选，不因 EV 编号不同抹掉实际比较；此绑定不把功能查询改成外观召回，不把原文授权日期当现行效力，也不让同族或仅部分号码匹配通过。
- 总任务尚有关键未执行动作、未解决的必要覆盖或无依据模块时返回 `status:incomplete` 与阶段性报告。`overall.risk` 不冒充全范围结论；`known_scoped_risk` 保留已取得的局部风险，不让 pending 参加最大值计算。具体已知中高风险仍清楚展示，不因其他模块未完成被抹掉。
- 同一模块同时有已评级候选与待评范围时，模块标签须写“已评局部”，并显示待评数量；HTML、Markdown 与 CSV 范围说明一致，不将局部低风险冒充整个模块的最终等级。
- 商品专利声明的追踪须引用实际来源或文献，不能用原营销句、失败记录或一个 completed 标记关闭。新增波次必须实际执行，或在计划外记录有理由且绑定原计划哈希的取消；取消不自动满足覆盖。
- “未完成检索”不是降低风险的事实。反证为空时显示“未取得降低风险的证据”，缺口放在覆盖与待评理由。`validate_run` 可验证阶段性文件合法，但不得把它称为完整排查通过。

以下等级定义、比较底线与双审要求继续适用有依据的结论；新情景修订以上节为准。任何“必须选级”都不授权修改原始双审中的待评项；`partial-evidence-v2` 仅可在冻结后、新摘要绑定的报告层使用下节规则。

## 不完整报告：partial-evidence-v2

- 真实 `assessment_completion`、`status/business_completion`、原始 first/second review 的 `risk:null, assessment_status:pending` 及 `right_state:unknown` 原样保留。不得把 pending 改成已审、把 unknown 改成已核实，也不得将未执行伪装为受阻。
- 只有已审且有充分依据的单项进入综合判断；pending/unknown 的 `risk` 保持 null，`risk_basis=insufficient_evidence`，不参与整体风险汇总。
- 已有具体证据支持的五级风险保留其等级与依据；已支持的低／极低结论也保留，不能因别处缺口被改写。报告同时显示未完成工作和可改变结论的限制。
- 如主情景没有已支持的当前风险，整体 `risk:null`、`assessment_status:pending`。这是可交付的证据报告，不是完整清查、无侵权意见或权利状态确认。

