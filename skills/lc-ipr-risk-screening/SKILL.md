---
name: lc-ipr-risk-screening
description: 针对单个美国 Amazon 商品汇总云端与公开网页候选，按八模块完成知识产权风险审阅，并以发现状态、法律风险、置信度和运营动作四维结果输出离线报告。
---

# 易逊-知识产权排查（付费接口）

一次只处理一个美国商品。用户提供老陈访问 Token。公开网页检索先读环境变量 `SERPER_API_KEY`：有 Key 则本机跑完整检索；读不到就询问用户，用户没有也不阻断，云端商品详情和知识产权发现继续走完。

本 Skill 使用 `ruleset_version=2.0`。必须严格区分两层运行时：

- `tools/bin/lc-ipr-risk-screening-*` 是 **legacy 采集 CLI**，只负责认证、商品事实、候选发现、证据账本与证据冻结。
- `node tools/ipr-risk-v2.mjs` 是 **v2 评级 runtime**，是候选法律语义、八模块审阅、风险聚合、报告和 release gate 的唯一权威实现。
- legacy CLI 产生的 `material`、`not_material`、`needs_review`、`high`、`low` 或 draft 风险字段都只属于旧版发现元数据，禁止复制、映射或解释为 v2 法律风险。

后文把二者分别记为 `<IPR_CLI>` 与 `<IPR_V2_RUNTIME>`。

## 开始前

1. 完整读取 `INSTRUCTIONS.md`、`references/input-routing.md`、`references/us-workflow.md` 和 `references/evidence-and-review.md`。
2. 选择 `tools/bin/` 中当前平台的 `<IPR_CLI>`；macOS 首次运行前按 `INSTRUCTIONS.md` 处理 quarantine。
3. 官方包第一条业务命令必须是 `<IPR_CLI> auth-check`。失败时说明原因并停止。
4. 执行 `<IPR_V2_RUNTIME> version`，必须确认 `ruleset_version=2.0`；再用 `rules describe` 锁定本轮规则。runtime 不可用时只能交付发现层结果，不得自行评级。
5. 先读环境变量 `SERPER_API_KEY`。对话、本轮会话附件或用户上传文件里出现 Key / 疑似 Serper Key 时，立刻注入当前会话环境变量后直接使用。禁止写入 `config.json`、命令参数、任务目录或报告，禁止回显。环境里没有、用户也没有时，跳过公开网页检索并记录 coverage gap。
6. 仅接受 `marketplace=US` / `amazon.com`。非 US 必须在上传图片或远程调用前停止。

认证通过后，向用户索取一个美国 Amazon ASIN 或 `amazon.com` 商品链接，并明确说明可以同时上传商品主图和细节图。ASIN/链接路径会自动获取商品资料和可信主图，用户图片是可选补充；完整人工资料路径至少需要一张清晰主图。一次只接收一个商品。

## 正式流程

1. 按输入路由采集并冻结商品事实。在技能包外指定尚不存在的 `ipr_screening_YYYYMMDD_HHMMSS/`，不得把任务写进技能包根目录。
2. 使用 legacy CLI 初始化任务、生成发现计划和证据账本；依次完成云端知识产权发现、证据导入以及可选的 Serper 公开网页检索。legacy CLI 到此只提供候选和证据，不提供 v2 评级。
3. 完成覆盖与来源条目完整性检查，冻结原始证据。若当前 legacy CLI 为冻结证据强制要求旧版候选处置，只把该步骤视为兼容性账本动作；其 `material` 等标签不得进入 v2 结果。
4. 运行 `<IPR_V2_RUNTIME> migrate-candidates --task-dir <task-dir>`。legacy `material` 和 `needs_review` 一律迁移为 `unresolved`、`risk_driver_eligible=false`；旧 `not_material` 可以保留，但仍必须接受 v2 校验。v2 再按 `record_kind`、`legal_materiality`、证据角色、权威层级、法域和去重组重新处置，旧标签不得自动转成 `risk_bearing`。完整 legacy 冻结链的四个核心来源产物齐备时，迁移同时生成正式发布必需的 `<task-dir>/v2/source-manifest.json`。
5. 如用户、律师、后端或其他授权流程已经完成官方记录核验或版权来源链核验，可在冻结 ledger、完整 coverage checkpoint 与当前 source manifest 上用 `<IPR_V2_RUNTIME> record-verification --kind <official|copyright> --task-dir <task-dir> --input <verification.json>` 受控录入。该命令只校验并登记现有核验事件，不执行浏览器查询或确认外部材料真实性。录入会更新 evidence revision、coverage 与 source manifest；此后必须重新执行 `migrate-candidates`，并重建候选、Assessment 和报告，旧产物不得继续发布。
6. 在 `<task-dir>/v2/candidate-review-workspace.json` 上一次性审阅全部候选并完成聚类，写入 `<task-dir>/v2/candidate-review.json`，再用 `validate-candidates` 校验。所有冻结核验事件都必须写入对应原候选的 `verification_refs`。只有经过 v2 结构化审阅且标记为 `risk_bearing`、`risk_driver_eligible=true` 的独立候选，才能驱动正式法律风险。
7. 运行 `prepare-assessment --candidate-review <task-dir>/v2/candidate-review.json` 生成 `<task-dir>/v2/assessment-input.json`，再按八模块完成审阅：外观设计、实用专利、申请中专利、文字商标、图形商标、商业外观、版权/创意资产、公开维权信号。各模块必须满足其专属法律测试，不能用标题命中、候选数量或图搜分数替代。
8. 输出四个互不替代的维度：

   - `discovery_status`：`no_lead / leads_found / review_required / blocked`
   - `legal_risk`：`not_assessable / very_low / low / medium / high / critical`
   - `risk_confidence`：`low / medium / high`
   - `operational_action`：`proceed / proceed_with_conditions / hold_for_evidence / escalate_legal`

   另以 `coverage_confidence=low / medium / high` 单独表达八模块发现覆盖质量，不与 `risk_confidence` 混合。
9. 需要二审时，合并双方确认的结构化事实后由 runtime 重新计算；禁止按“风险取高、置信度取低”机械合并。风险驱动事实存在未解决冲突时设为 `discovery_status=blocked`、`legal_risk=not_assessable`、`risk_confidence=low`、`human_resolution_required=true`、`operational_action=escalate_legal`，再交由人工裁决。
10. 用 v2 runtime 执行 `finalize-assessment`、`render-report` 和 `validate-release`。正式发布通过 `v2/source-manifest.json` 逐文件绑定冻结的商品事实、查询计划、evidence ledger、discovery coverage 及其引用来源，并交叉绑定 Assessment coverage、全量候选、核验事件和每条 legacy 候选的 `legacy_reassessed` 状态；任一项变化都必须重建后续产物。Assessment 未完成时，草稿只能显示“评估尚未完成”，法律风险必须为 `not_assessable`，不得显示正式高低风险徽章。

## 判定底线

- 候选数量、搜索排名、图搜相似度和同款商城页面数量只影响发现与审阅优先级，不直接抬高法律风险。
- 缺图、缺来源、服务失败、权属或状态未知只触发 `risk_confidence` 限制、正式结论阻断或 `hold_for_evidence`，不构成风险 floor。
- `high` 必须有权威证据、合格的独立风险驱动候选和完整模块法律测试；`critical` 还必须有针对同一商品的投诉、诉讼、TRO 或平台执法等现实紧迫性。
- `overall.legal_risk` 只取证据充分的最高模块风险。重复页面或同一证据跨模块出现不得触发自动升级。
- `no_result` 只表示该次检索未返回候选，不表示不存在权利或可以销售。覆盖不足时不得输出 `low` 或 `very_low`。
- 版权模块为 `very_low`、总体为 `very_low` 或运营动作拟为 `proceed` 时，正式发布要求每张冻结商品图片恰有一条 `state=provided` 的来源声明与路径/SHA-256 精确匹配；声明必须有结构化 `raw/copyright-provenance/` 证明，且证明中的商业使用、Amazon 使用、美国地域与有效期限均为 `true`。候选核验事件不能替代这项逐图片门禁。

## 边界

- 本 Skill 是风险筛查，不执行官方登记或法律状态浏览器核验，也不声称确认官方法律状态。`record-verification` 仅受控登记外部已完成的核验事件并校验其任务内绑定。
- 云端结果用于候选发现，不能替代律师的 FTO、有效性或侵权分析。
- 对高风险候选、现实执法信号、权利状态不清或拟正式上线的商品，应建议用户咨询美国知识产权律师。
- 不得把 Token、上游服务 Key、Cookie 或浏览器凭据写入任务目录、报告或聊天。

## 资源

- `INSTRUCTIONS.md`：v2 完整命令顺序、legacy/v2 边界与停机条件。
- `references/input-routing.md`：商品输入和事实冻结。
- `references/us-workflow.md`：双发现计划、证据冻结和 v2 接管点。
- `references/evidence-and-review.md`：候选语义、八模块审阅、聚合与 release gate。
- `references/risk-rules.v2.json`：`ruleset_version=2.0` 的机器可读判定规则。
- `references/workflow.md`：端到端流程摘要。
