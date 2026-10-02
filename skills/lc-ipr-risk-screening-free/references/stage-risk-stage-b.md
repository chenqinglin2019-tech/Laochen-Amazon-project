# 09B 阶段判断、核实与失效

新任务默认使用 `api-first-v3` 与 `final-double-review-v1`，以[API 直接采信与一次最终双审](api-direct-final-review.md)为优先契约。已采信 API 字段不生成官方网页重复核验；过程保留事实分析，取消 09C 阶段双审前置。下文旧修订仅约束保留该版本的历史任务。

新任务启用 `stage_risk_revision=stage-risk-stage-b-v1`。先完成 01—08 原来源、候选、专项与结果处理，再用 `record_stage_risk.py --task-dir <任务目录> --input <JSON>` 追加 `review`、`invalidate` 或 `signal_review`。记录写入 `evidence.json.stage_risk_events`；`next_work.stage_risk` 与 `advance_work` 读取同一投影，不另建来源、候选或业务进度。09C 的独立双审与主审、09D 的初步交付和完整报告接入仍须另行验收。

`review` 必须绑定 `scope`（`scenario_id`、`jurisdiction`、`right_type`、`product_version`、`module_id`，具体候选另写 `candidate_id`）、`assessment_date`、实际已完成且经审阅的 `outcome_refs`、原事实 `evidence_refs`、支持与降低风险事实、实际比较及相邻等级理由。原引用保留指纹；运行零结果须原回执已提交、返回真实且原始结果处理完成，单纯发请求／等待／失败不能选级。专项比较引用原 06／07 事件；中、高、极高必须绑具体候选和正面事实，高及极高另核当前权利状态、地域适用与反证，极高还需核重要排除依据。极低只用于充分范围内有决定性排除依据的核实判断，局部极低不外推整体。

核实不足用 `verification_status=pending`，同时按已完成材料给有据 `stage_risk=低`（`basis=no_specific_lead` 或 `weak_leads`）或 `stage_risk=中`（`basis=credible_conflict`），并写每个关键缺口的事实、影响与最小动作。弱线索逐项写来源引用、为何尚非可信冲突及最小核查；可信冲突写具体产品关联与冲突点，不因未能最终定性改写成弱线索。此时 `confidence=null`，投影显示“核实置信度未形成”。单项核实选级用 `verification_status=verified`，须有充分比较与相应等级依据，`confidence` 才可为低／中／高且须解释稳定性。整体与国别汇总在 09C 前保守保持核实待评及空置信度；`coverage_ready_for_09C` 只是待双审的覆盖预检，不从一个已核实局部或 100% 进度自动推出整体核实。

新材料实质推翻旧判断时立即追加 `invalidate`，引用原 `judgment_id`、已有上游事件、影响及恢复动作；原等级留在历史且暂停当前适用。产品版本或引用指纹变化也在投影中自动暂停，不会自动降为低。若失效项可能改变整体最高级，整体显示 `pending_recheck`、上次等级和其余有效部分最高级；独立有效的更高级判断仍可驱动当前整体。新事实经定向重审追加新 `review`，须绑定 `prior_judgment_id` 与改判理由，旧事件不删除。等待、失败、超时或任务关闭不自行恢复。

未来申请与公开维权材料使用 `signal_review` 单列原来源、关联、状态／事件时间、实际含义与复核条件；它不进入当前风险最高级。材料中的可用于当前权属或比较的事实须另经相应专项核验后再引用。不同销售情景、国家和产品版本分别汇总，主情景最高有效等级不按进度打折；条件情景独列。计划范围内无已审完成成果时没有阶段等级，视图保留真实工作状态。旧 `risk=null` 不能批量转低；须逐范围对现存成果重审后才追加新判断。

09B 投影用于工作中的判断复核；报告展示、可校验初步阶段包及完整交付将在 09D 接入。当前 09B 的 `review_status=single_review_pending_09C` 明确表示尚未取得 09C 独立双审，不能当成审定结论或发布许可。

M07的本地asset_provenance调查成果也可作outcome_refs：判断使用既有专项标识 copyright_ip 或 figurative_trade_dress（不是流程环节编号 M07）；须对应当前精确计划行/产品版本、同国家/权利/候选范围，并通过原生本地调查完成与留存文件哈希检查。partial或其他范围不接受。此接入仅核成果身份和调查完成；未知法律事实继续进入gaps，选级、核实、置信度、09C双审及交付保护均不变。
