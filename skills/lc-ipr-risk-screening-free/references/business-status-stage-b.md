# 10B 业务完成与受限结束

新任务默认使用 `api-first-v3` 与 `final-double-review-v1`，以[API 直接采信与一次最终双审](api-direct-final-review.md)为优先契约。已采信 API 字段不生成官方网页重复核验；过程保留事实分析，取消 09C 阶段双审前置。下文旧修订仅约束保留该版本的历史任务。

新任务使用 `business_status_revision=business-status-stage-b-v1`。报告构建时只读 09D 当前阶段快照、08 统一待办、09A 计划进度和 09C 双审／主审，不创建第二套义务、判断或交付账本。旧任务不自动迁移。

`business_complete` 仅表示当前产品与范围版本的必要义务均已完成或有据免做／替代、无未决工作／暂停／技术停止，计划进度 C=N，当前判断已经必要审阅且完整评估为完成。文件生成、独立校验及实际可访问入口不参与这个业务判定。

`limited_round_closed` 仍是整项业务未完成。仅当剩余原待办全部处于真实外部限制、原限制证明经现有 `necessary_completion` 门禁核实、未留可执行动作或已得未审材料、每项均有当前范围／版本、恢复条件与适用审阅政策下所审判断影响（新任务为最终双审），且无未解决恢复依赖时才可出现。对于“无合格替代路线”，当前仅接受由原计划和能力快照验证的 `route_absence`；单次失败回执或填写限制标签不证明路线已穷尽。共用限制在投影中按原 `work_id` 去重并列出影响范围，原待办仍保留。缺证明、材料、路线、影响或审阅时，输出对应缺口并回原环节处理。

其余状态保留为 `continue`、`awaiting_dependency`、`user_paused`、`review_pending` 或 `integrity_unavailable`（evidence 模式报告已发布并核实实际入口后，仅剩 `awaiting_dependency` 的版本由完成检查记为 `limited_round_closed`，见 [10E](delivery-versions-stage-e.md)；`business_completion` 仍为 incomplete）。暂停、临时失败、提交未知、重试耗尽、技术停止与 C=N 均不能单独关闭本轮。报告 HTML、Markdown、CSV、JSON 和 Manifest 共享同一投影，分别显示业务状态与 `delivery_status=not_verified`；后者明确表示尚未核实际可访问入口。原 `publication.delivery_status` 与 `completion_check.status` 仍是旧版本地生成／工作流合同，10C—10E 将继续统一按类型文件、独立校验和实际送达语义；此阶段不得将其读作已交付。

新任务的 `assessment.final_review` 为唯一最终审阅状态。`API_RECORD_FACT_GAP` 只有在对应 M06/M07 未知字段已读、批次材料已处理、补查审阅记录具体限制与恢复条件后，才允许受限结束；重新出现可用字段路线会重开。缺比较、未读材料、提交未知、冲突和未审变更仍阻止结束，不能用限制标签代替处理。

## 已知结果评级及运营版

`known-findings-risk-v1` 与 `operator-report-v1` 将已知结果风险、事实未决、计划进度和本轮结束分别投影。未完成步骤及低置信度不参与风险计算；原候选 unknown/pending 仍保留。

最终双审通过后，10B 消费同一 `assessment.publication` 已验收的本轮限制，不再用历史阶段限制证明重复审核。要求当前最终摘要相符、剩余工作及来源绑定一致、没有可执行或提交未知事项、没有主动暂停或技术停止。符合 evidence 发布契约的有界调查记为 `limited_round_closed`；真实进度、未查明事实及尚未登记的恢复条件继续披露，不因此补成业务完全完成。

`publication` 不能由磁盘 passed 标记代替；独立语义校验重算它，后续事务重核所有输入及文件绑定。交付状态存于 10E 可变日志，运营页面陈述冻结时的本轮状态，不写死“已核入口”或“入口未核对”；实际送达必须返回验收后的入口。历史任务仍用原 10B 条件。
