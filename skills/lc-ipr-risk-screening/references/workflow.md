# Workflow（Ruleset 2.0）

## 运行时边界

- legacy `<IPR_CLI>`：认证、商品事实、发现计划、云端/Serper 候选、证据账本和证据冻结。
- v2 `<IPR_V2_RUNTIME>`：`node tools/ipr-risk-v2.mjs`，负责候选法律语义、八模块审阅、风险计算、报告和 release gate。
- legacy `material/not_material/needs_review` 与草稿 `high/low` 都不是 v2 法律风险。legacy CLI 的候选处置仅用于完成旧版证据冻结门禁。

## 端到端顺序

1. 按 `references/input-routing.md` 采集并冻结一个美国商品的完整事实。
2. 用 legacy CLI 依次执行云端知识产权发现和可选 Serper 公开网页检索；Amazon HTTPS 主图可直接使用，本地图由 `us-screen` 经专属后端上传。
3. 保留每个 provider item，完成 legacy 来源完整性门禁并冻结 evidence ledger。上传、来源或查询失败必须记录 gap，不能解释为零候选。
4. 运行 `<IPR_V2_RUNTIME> migrate-candidates --task-dir <task-dir>`，生成 `<task-dir>/v2/candidate-review-workspace.json`；完整 legacy 冻结链的四个核心来源产物齐备时还会生成正式发布必需的 `<task-dir>/v2/source-manifest.json`。legacy `material/needs_review` 迁为 `unresolved`，旧 `not_material` 保持 `not_material`。
5. 如用户、律师、后端或其他授权流程已经完成官方记录或版权来源链核验，用 `<IPR_V2_RUNTIME> record-verification --kind <official|copyright> --task-dir <task-dir> --input <verification.json>` 受控登记。命令只接受绑定冻结原候选、ledger、coverage 与当前 source manifest 的现有核验事件，不执行浏览器查询；录入后必须重新执行 `migrate-candidates`，并重建全部 v2 下游产物。
6. 全量完成候选法律语义、证据层级、法域和去重组，写入 `<task-dir>/v2/candidate-review.json`，将所有冻结核验事件写入对应原候选的 `verification_refs`，再运行 `validate-candidates`。
7. 运行 `prepare-assessment` 生成 `<task-dir>/v2/assessment-input.json`，完成八模块专属法律测试：`appearance_design`、`utility_patent`、`pending_patent`、`word_mark`、`figurative_mark`、`trade_dress`、`copyright_creative_ip`、`enforcement_public_signals`。
8. 运行 `rules evaluate --dry-run`。需要二审时先合并结构化事实，再重新计算；不执行“风险取高、置信度取低”。风险驱动事实仍冲突时设 `discovery_status=blocked`、`legal_risk=not_assessable`、`human_resolution_required=true`、`operational_action=escalate_legal`，再进入人工裁决。
9. 用 v2 runtime 执行 `finalize-assessment`、`render-report` 和 `validate-release`。正式产物只认 `<task-dir>/v2/` 与 `<task-dir>/report-v2/`；release 通过 `v2/source-manifest.json` 逐文件绑定冻结 product/query/ledger/discovery coverage 及其引用来源，并交叉绑定 Assessment coverage、全量候选、核验事件和每条 legacy 候选的 `legacy_reassessed` 状态，任一变化都要求重建。

## 输出语义

正式报告分开展示：

- `discovery_status`：发现阶段状态；
- `legal_risk`：实体法律风险；
- `risk_confidence`：最高风险驱动结论的可信度；
- `coverage_confidence`：八模块发现覆盖质量；
- `operational_action`：上线、补证或升级律师处理的动作。

缺证据只触发置信度限制、正式结论阻断或 `hold_for_evidence`，不自动提高法律风险。候选数量、图搜分数和重复商城页也不得直接参与风险计算。

版权模块为 `very_low`、总体为 `very_low` 或运营动作为 `proceed` 时，每张冻结商品图片必须有唯一的 `state=provided` 来源声明按路径/SHA-256 覆盖，并引用 `raw/copyright-provenance/` 中商业使用、Amazon 使用、美国地域和有效期限均为 `true` 的结构化证明；候选级版权核验事件不能替代这项 release gate。

Assessment 未完成或任一 release gate 未闭合时，草稿必须使用 `legal_risk=not_assessable`、`risk_confidence=low`，首页显示“评估尚未完成”，不得显示正式风险徽章。

本流程不包含官方登记或法律状态浏览器核验，不输出官方法律状态确认，也不替代律师意见；`record-verification` 只登记外部已完成的核验事件。
