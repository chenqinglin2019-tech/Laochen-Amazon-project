---
name: lc-ipr-risk-screening-free
description: 使用官方来源及用户已启用的数据源账户容量（免费或付费），对单个 Amazon 商品或用户提供的产品资料在美国、英国、法国、德国、意大利、西班牙和日本的专利、外观、商标及版权风险进行证据排查，分国家输出五级风险预判、三级置信度、推论依据、核查事项和离线报告。
---

# 知识产权风险排查

新任务来源采用 `existing-account-capacity-v1` 与 `frozen-source-settings-v1`（见[来源账户策略](references/source-policy.md)）；不再要求免费余额或零费用，允许消耗已启用来源的现有免费／付费套餐及积分，不自动购买、充值、升级或启用超额。`2.4-free` 是保留的兼容标识。新任务使用 `2.4-free`、`api-first-v3`、`final-double-review-v1`、`discovery-purpose-budget-v1`、`discovery-semantics-v1`、`source-operation-v2`、`necessary-work-v3`、`known-findings-risk-v1`、`operator-report-v1`、`product_structure_policy=use_provided_else_unavailable_v1`、`module-double-review-v1`、`scenario-triage-v1`、`identity-discovery-v1`、`workflow-correction-v1`、`continuous-work-v2` 与 `asset-scope-v1`，以及 `failure-limits-v1` 与 `structured-conflicts-v1`（见 [提速与有据限制](references/workflow-efficiency.md)）。先固定销售情景和产品身份，再全量轻分流，仅深入核验入选候选。有效 API 字段直接支持判断，不强制通过 USPTO 等官方网页重复核验。仅最终冻结后独立双审一次；具体规则先读 [API 直接采信与最终双审](references/api-direct-final-review.md)。总体与各范围的运营筛查等级按已查明具体当前风险计算；没有完成复核的适用判断时显示风险待定，并给出暂缓上架建议；已有适用低风险依据时仍保留未完成事项。未完成动作、缺资料和失败进入真实进度、限制和上架建议，不机械改变已有依据的等级；候选未知／待判断事实不改成已核实或已排除。历史任务保留原策略。

实际商品排查的第一条业务命令必须按 [INSTRUCTIONS.md](INSTRUCTIONS.md) 执行云端鉴权。创建任务后的 credentials 预检保留第二次鉴权。鉴权、凭据位置和鉴权失败行为属于冻结协议，不修改；数据源费用规则按新来源账户策略执行。开发、审计、离线测试和恢复 Skill 文件不执行真实鉴权。

首次鉴权及获准来源调用前按 [联网权限与恢复](references/installation.md#联网权限与恢复) 检查宿主网络权限。确有阻断时走宿主授权入口，鉴权失败仍停止业务并展示原安全原因；恢复后重跑原入口。来源提交未知须先核对回执，网络恢复不重置额度或提交次数。

## 必读路由

按当前阶段读取，不把全部参考文档常驻上下文（每份文档只在对应阶段读一次）：

- 入口与身份冻结：[产品入口](references/product-entry.md)、[对象范围与局部推进](references/product-scope.md)（`record_product_scope.py` 登记四态、对象来源和方向依赖）。
- 新商品主图、事实性质与四部分交付：[商品采集与事实交付](references/product-delivery.md)；采集：[浏览器采集](references/browser-product-capture.md)。
- 目标变更、事实纠正／撤回、补图、历史材料复用：[商品变化与定向复核](references/product-change.md)；缺具体产品事实：[最小事实反馈](references/product-feedback.md)。
- 启动与规划：[业务流程](references/workflow-business-logic.md)、[API 优先检索](references/api-first.md)、[流程纠错与必要工作](references/workflow-correction.md)；查询前唯一计划项与进度：[09A](references/review-progress-stage-a.md)。
- 必要方向、查询表达与结果审阅：[方向与语义审阅](references/discovery-semantics.md)；来源能力、字段／分页反馈、范围取消及 CUA 工作区、绑定与交接（基础页不出结果不能反复提交）：[来源操作验收](references/source-operations.md)。
- 来源受阻、恢复或配额：[来源规则](references/providers.md)。
- 候选：对象范围与三路决定[候选分流范围](references/candidate-triage-scope.md)；`needs_info` 补证[候选补证闭环](references/candidate-followup.md)；批次、交专项、重开、模块 05 完成[候选阶段闭环](references/candidate-triage-stage.md)。
- 专项：专利／外观[专项核验](references/specialty-analysis.md)；商标／版权／商业外观及公开维权[模块 07](references/distinctive-rights.md)、[标识与版权规则](references/trademark-copyright.md)。
- 比较与评级：[评级规则](references/risk-estimate-rules.md)；阶段选级与旧依据失效：[09B](references/stage-risk-stage-b.md)。
- 最终双审、主审骨架、有据限制、精简输出与批量输入：[完整报告双审宿主](references/report-review-host.md)（macOS 沙箱／Windows 无工具进程隔离）、[提速与有据限制](references/workflow-efficiency.md)、[API 直接采信与最终双审](references/api-direct-final-review.md)。
- 已确认报告格式：[运营格式与动态数据](references/report-presentation-stage-a.md)、[格式锁](references/report-format-lock.json)；固定绿色七章节九模块、产品/权利图片对照、独立候选和技术附录，风险等级与置信度按本次证据生成，无法判断的项明确待定。查询完成率统一读取 `actual_query_execution_progress`，按真实去重查询和已读回执计算，附逐项 `query-progress.html/json`；不能用台账漏记的验收率替代。
- 报告与交付：[09D 初步阶段结果](references/stage-delivery-stage-d.md)、[10A 呈现](references/report-presentation-stage-a.md)、[10B 业务状态与受限结束](references/business-status-stage-b.md)（实际送达须另核可访问入口）、[10C 文件与材料包](references/report-package-stage-c.md)。
- 发布与续跑：[结束保护](references/continuation-guard.md)、[数据契约](references/evidence-schema.md)的相关章节。
- 仅历史任务才读：[09C 阶段批次与双审](references/legacy/stage-review-stage-c.md)（新任务不创建阶段双审前置）、[历史兼容](references/legacy-compatibility.md)；不得给旧任务补版本字段来改变语义。

## 不可削减的判断边界

- 产品身份、销售情景、国家、权利类型、准确案号及原始文件身份分别绑定。可信 API 原字段按准确身份、地域和时间直接采信；搜索摘要、同族信息和历史事件不补成缺失的当前记录事实。
- US、GB、FR、DE、IT、ES、JP 分别判断；FR/DE/IT/ES 另补适用 EU 权利，GB 不继承 EU 商标或外观。当地语言查询的文字必须与语言标记一致。
- 全部取得的去重候选做轻量分流。`not_selected` 只是无需深入核验；`needs_info` 只取最小必要材料；`selected` 才核验身份、地域效力、保护内容和产品关系。
- 专利比较独立权利要求必要要素，外观核对必要视图，商标核对标识、商品服务及实际使用，版权核对可保护表达、来源和授权，商业外观核对来源识别、非功能性、地域与期限。
- 最终审阅按专利、外观、标识与表达分组，使用同一冻结输入及精确依赖子包；每组两条独立 Agent 链，每链只汇总自己的模块判断，第二链不看第一链结论，不再追加一轮全量双审。实质分歧、适用性例外、总体极低和置信度覆写由主审给出依据；不投票、不平均、不默认取高。
- 未执行、失败、截断、提交未知、登记库零结果或可选来源缺失均不能冒充排除证据。未知提交不得盲目重试。
- 总评取主情景中有具体依据的最高适用当前风险；无完成复核的适用判断时风险待定，不从未知推出低风险或排除事实。查询进度独立展示，未完成动作不抬高已有等级，但影响上架建议。不同情景分别汇总；未来申请和维权信号单列。

## 执行流程

### 每次退出前的强制闭环

本段适用于新任务、续跑及范围修订后的同一任务。代理不能仅凭已有线索或一次搜索给出“排查完成”的风险结论。每次准备结束当前轮次时：

1. 先运行 `advance_work.py --task-dir /absolute/run --output-format compact`，读取全部 `source`、`agent`、`repair`、`review` 动作卡和等待项；若本任务已有最终审阅、主审或交付目录，必须同时传入现存的 `--first-review`、`--second-review`、`--adjudication`、`--output-dir`，否则调度器会误把已完成审阅重新列为动作。有可执行动作就继续执行并重算，不把计划、搜索结果数、网页浏览或本地调查行当成已完成审阅。
2. 范围、产品事实或查询方向改变后，先修复受影响的计划绑定、语义审阅和执行进度，再进入来源提交；已有真实回执和候选仍要逐条处理。若动作重复或无进展，依 08D 诊断和技术停止规则处理一次，不靠重复运行调度器消耗轮次。
3. 仅当可执行来源、已取得材料、候选分流、专项比较和最终输入均已闭环，才调用 `report_review_host.py` 启动冻结后的独立双审；宿主给出的准备问题必须逐项关闭，不能手工伪造双审文件。
   对独立留存的官方批量导出先核对原始行数、去重身份数、当前候选台账与逐件分流数。若人工官方结果没有正式入账，`ready=true` 也只表示结构化输入可冻结；不得声称该批候选已全量分流，双审和 HTML 必须明确列出未入账范围及恢复条件。XLSX 等宿主不直接读取的格式应先生成与原件哈希绑定的纯文本阅读副本；图形候选须提供实际标样图片，不能仅给文字描述。
4. 报告发布后运行 `completion_check.py`，只有返回 `complete` 或 `limited_round_closed` 且报告入口真实可读，才能对用户输出对应的最终风险报告。返回 `continue`、`awaiting_user`、`execution_stopped` 或 `error` 时，只报告准确进度、已验证发现、具体缺口及恢复动作；不得把本轮发现包装成最终排除或完整核验。`limited_round_closed` 必须明示仍未完成的业务义务与恢复条件。

`completion_check.py` 的退出码为 0 才能宣称已交付；它只是只读门禁，不代替第 1 步的实际执行。用户请求继续时从现有任务目录和真实回执续作，先运行该闭环，不新建同一商品任务或重做已完成查询。

查询前以保留图片复核商品名称与实际构造；商品同时有功能件和独立装饰件时，两类相关分类都要进入方向清单。带 `AND`、`OR` 等保留字的商标短句使用来源支持的字段精确语法，并核对回显表达式与结果量。官方网页的人工结果只有在原件、实际查询及候选处理被当前任务绑定后才计入覆盖；工作区尚需跨轮复核时，在建立后及取得重要结果后即时按来源操作规范标记 `markHandoff()`，并及时导出原件，不等到退出前。同一阻断状态和证据摘要未变化时，不重复生成计划或重跑调度器，直接记录限制及恢复条件。

1. 鉴权后创建任务，记录 `input_role`、产品身份、国家和情景。仅有竞品链接时默认拟售功能、结构、外观一致且使用自己品牌的同款商品；参考品牌、摄影和附属包装按默认未纳入。本体装饰、作为目标商品的礼品盒或装饰画按真实关系处理，不普遍追问品牌用途。
2. 完成 credentials 预检；链接入口执行 Amazon 多视图采集，资料入口用 `product-input-v2` 明确选定查询主图或记录歧义，再执行 `record_user_product.py` 留存资料。首次核对后冻结具体目标，两路以 `product-scope-input-v2` 调用 `record_product_scope.py`，记录对象四态、逐项事实性质与版本、主图呈现限制、许可和方向依赖。仅针对已核查仍存在的实质矛盾询问具体对象，再用 `record_product_analysis.py` 登记可追溯术语；页面声明或模糊 OCR 可作待核实线索，不能直接写成已证实结构。原始线索须映射到术语或给出排除理由。
3. 生成初始计划后，先按[09A 唯一计划项与进度](references/review-progress-stage-a.md)登记执行前工作项，再按[方向与语义审阅](references/discovery-semantics.md)记录方向清单与每条发现查询的提交前审阅，再执行 API／网页计划；实际返回后记录第二次语义审阅，并按[来源操作验收](references/source-operations.md)检查实际字段、分页及操作能力。图像路线只取绑定的目标主图，提交前复核图片、目标版本、来源能力及接收方/用途许可；用户文件目前不自动外传，路线不足记局部缺口，其他工作继续。来源故障继续其他来源；首源成功但无相关候选时，审阅真实结果后才按规则启用已授权替代。
4. 合并候选，先按[原始结果与处理进度](references/source-result-processing.md)核对每个真实回执的已得位置、解析与去向；失败回执的可读材料仍需处理，缺口不能写成零条或完成。再按[候选身份与纠正](references/candidate-identity.md)保留残缺身份线索、原始号码、同申请／同族／地域关系和旧引用；清单成员只是线索，不继承父记录来源或结论。归并、拆分与字段取舍须追加引用原来源行的审阅事件，实质受影响判断重审，纯重复发现只补来源。按[执行计数与增量交接](references/candidate-accounting-handoff.md)分开核对执行时消耗和当前候选，逐候选、情景及国家交接已审材料；局部交接不关闭其他结果缺口。通过范围记录中的 `candidate_links` 关联具体对象；按[候选分流范围](references/candidate-triage-scope.md)先处理未纳入／待确认，再对已纳入部分作有证据的三路决定。国别或类型未知的候选保留定位待办；具体关联可以先入选，但身份未定位不得派生专项出网动作。仅新版公开视觉销售线索可依候选分流范围规则追加有界身份调查凭据，转入带明确未知事实及恢复条件的 evidence 受限交付；实际补图或未审材料继续处理。可在一次输入中向 `annotate_materiality.py` 提交 `decisions[]` 和对应 `discovery_reviews[]`，记录器先验证整批，再一次落盘。已有准确案号通过 `record_candidate_lead.py` 接入，不伪造搜索命中。
5. `generate_search_plan.py --expand` 仅追加有依据的权利人、分类、分页和最小补证动作。对 `needs_info` 按[候选补证闭环](references/candidate-followup.md)先审已存材料、分类实际请求，再绑定发现或混合用途并逐次审阅结果；按[候选阶段闭环](references/candidate-triage-stage.md)先处理已得未审材料、及时交接入选、定向重开并单独判断模块完成。定向读取不借“核验”名义寻找未知对象。新任务按[发现目的与版本预算](references/discovery-purpose-budget.md)记录同一目的最多初始加两次审阅后调整；同版本跨来源合计最多实际获取八页、尝试两条路线，浏览器补搜最多主动取得五十个去重候选。已返回超额卡片全部保留；边界不是必跑量或覆盖证明。不要轮换营销长句或用固定 Top N 丢候选。
6. 绑定素材清单后执行图形标样、版权及商业外观公开调查。共享的创作、来源、首次发布和功能事实可用一次 `record_asset_provenance.py` 调用绑定多个兼容 `--query-id`；各国地域、期限和法律适用仍分别判断。
   对已交接的专利／外观入选对象，用 `record_specialty_analysis.py` 逐范围登记本轮核验基准日、材料实际阅读、基础事实及免做，随后记录每项权利要求／设计的比较、补证和批次去向；本模块事实与完成状态分别交后续待办、评级和交付，不在此处选风险等级。
   对已交接的商标／版权／商业外观入选对象，使用 `record_distinctive_rights.py` 记录当前对象和版本、07 独立评估日、登记及公开事实两条路线和实际材料阅读；商标另记逐维比较，版权另记来源、主体关系、表达及许可范围，商业外观另记主张、地域规则、使用、功能性与混淆。公开维权按事件保留原始主张、处置、进展、正式决定及来源层级。逐缺口先读已有材料并最小补证，按真实来源批次核对材料去向；局部结果可向 08—10 增量交接，正常完成、等待和有据受限分别按当前对象范围记录。局部事实和审阅不等于专项完成；无登记、零结果和失败均保留原含义。
7. 查询过程中不询问实际结构相关信息。用户已提供的结构资料默认使用，并留存来源及 `user_claim/claim_only` 等事实性质；没有提供默认用户无法提供，保留相应 unknown／无法判定并继续可判断部分。内部结构不能由外观相同、功能相同、营销声明或没看到某部件推定。结构缺口走 `record_product_feedback.py` 留存不可提供记录及受影响事实／候选，不进入用户待答；旧结构请求在用户明确采用本规则后也保留历史并按不可提供投影。非结构且实质阻断的范围矛盾仍按原规则处理。补充资料仍经 `record_product_scope.py` 追加留存，反馈关闭须引用已推进版本的事实和来源；旧查询、阳性证据和未受影响判断保留。事实纠正／撤回或范围变化产生有界影响清单；目标明确更换走 02B 受控入口，未审受影响候选不得混入当前判断。图片重压缩只保留原件／派生关系，新增视图要绑定受影响对象或事实。依赖冲突只暂停相关动作；同一权利类型不能整体停掉。持续运行 `advance_work.py`：依[08A 统一工作视图](references/continuous-work-stage-a.md)处理精确来源行、Agent 阅读、调查、分流、计划修复和范围审阅，再重算待办；共享动作只执行一次，各问题分别验收。已提交失败或提交未知按[08B 来源恢复](references/continuous-recovery-stage-b.md)核原回执与恢复依据后再安排；用户主动暂停和恢复前对账按[08C 任务控制](references/continuous-continuation-stage-c.md)处理，访问反馈须验证原查询能力且不自动解除主动暂停。逐工作进展、两轮诊断和有界技术停止按[08D 执行收尾](references/continuous-progress-stage-d.md)登记；技术停止只封锁相同动作，保留未完成与恢复条件。真实外部限制可以成为最终 evidence 报告限制，但可执行工作、未审材料和提交未知仍阻断发布。
8. 对实际已完成并审阅的成果按[09B 阶段判断与失效](references/stage-risk-stage-b.md)记录事实分析和比较；新任务不执行 09C 阶段双审。所有可执行计划扩展、来源处理、分流和范围修复完成后，直接运行最终审阅宿主，由冻结入口一次性执行准备检查、列出全部问题并创建内容绑定收据；仅在准备通过时按[完整报告宿主](references/report-review-host.md)冻结共同输入并独立双审（宿主按平台自动选择隔离后端；单独的 `review_readiness.py` 不是必经步骤）。API 已支持的字段不再新增官方网页核验；具体缺口按已有材料、同来源、其他 API、必要网页的顺序有界补证。
9. 主审确认最终两审结果：先运行 `prepare_adjudication.py` 生成绑定当前摘要的 `adjudication.json` 骨架与冲突工作表，无实质分歧时绑定双方摘要；有争议时在对应决定行填写差异和依据（reviewer、session_id、adjudication_reasoning 须由主审填写，否则发布门禁拒绝）。新任务采用语义输入摘要：进度日志、生成时间及同哈希文件路径变化不重审；实质变化只重审受影响单元及总体影响，使用各审阅位原审阅凭据引用未变化判断，保留旧摘要和执行签名。按[API 直接采信与最终双审](references/api-direct-final-review.md)执行复用，不改绑旧审阅。业务完成和 HTML 读取同一最终双审结果；剩余有据外部限制可以形成受限本轮报告。运营报告在新目录以 `publish_report.py --deliver-to <新交付目录> --require-complete` 一次执行构建、固定版本、复制与完成检查。一次真实独立语义复算后，只在本进程不可变事务内复用；后续每步重核来源、审阅、所有文件字节与本地引用，独立 CLI 检查仍完整复算。并按[10D 独立校验](references/delivery-inspection-stage-d.md)及[10E 固定版本与交付](references/delivery-versions-stage-e.md)核对实际送达入口。历史任务保持其原阶段／完整双审与发布协议。

## 命令入口

```bash
python scripts/auth_gate.py
# --guard-session-id 取当前会话的真实 ID：bash/zsh 为 "$CODEX_THREAD_ID"，PowerShell 为 $env:CODEX_THREAD_ID；非 Codex 宿主不传并披露“结束保护未启用”
python scripts/create_task.py --url 'https://www.amazon.com/dp/B012345678' --jurisdictions US,GB,FR,DE,IT,ES,JP --guard-session-id "$CODEX_THREAD_ID"
python scripts/preflight.py --task /absolute/run/task.json --phase credentials
# 用户资料入口改用以下创建命令，不与上一条同时执行：
# python scripts/create_task.py --product-input /absolute/product-input.json --jurisdictions DE --guard-session-id '<真实 Codex session_id>'
# credentials 预检后资料入口执行 record_user_product.py，跳过下面的 Amazon 采集三条命令。
# python scripts/record_user_product.py --task-dir /absolute/run
node tools/cdp/cdp-cli.mjs doctor
node tools/cdp/cdp-cli.mjs capture-amazon --task-dir /absolute/run
python scripts/record_browser_product.py --task-dir /absolute/run --capture /absolute/run/browser-capture.json
python scripts/record_product_scope.py --task-dir /absolute/run --input /absolute/scope.json
python scripts/record_product_analysis.py --task-dir /absolute/run --input /absolute/analysis.json
python scripts/preflight.py --task /absolute/run/task.json --phase evidence
python scripts/generate_search_plan.py --task-dir /absolute/run
python scripts/record_review_progress.py --task-dir /absolute/run --input /absolute/review-progress-initialize.json
python scripts/record_discovery_semantics.py --task-dir /absolute/run --input /absolute/direction-review.json
python scripts/record_discovery_semantics.py --task-dir /absolute/run --input /absolute/before-query-review.json
python scripts/run_api_plan.py --task-dir /absolute/run --phase discovery
python scripts/record_discovery_semantics.py --task-dir /absolute/run --input /absolute/after-result-review.json
python scripts/record_source_operation.py --task-dir /absolute/run --input /absolute/source-operation-review.json
python scripts/merge_candidates.py --task-dir /absolute/run
python scripts/annotate_materiality.py --task-dir /absolute/run --input /absolute/triage-and-discovery-reviews.json
python scripts/generate_search_plan.py --task-dir /absolute/run --expand
python scripts/advance_work.py --task-dir /absolute/run --execute-sources --write-agent-packet --output-format compact
# 动作卡带 input_template 时，先用它生成预填的输入文件再只填 null 字段：python scripts/input_template.py --task-dir /absolute/run --output-dir /absolute/new-templates
python scripts/record_stage_risk.py --task-dir /absolute/run --input /absolute/stage-risk-review.json
# 新任务最终双审必须经宿主（自带 readiness 与冻结；macOS 沙箱、Windows 无工具进程隔离；手工 record_independent_review.py 仅用于历史任务）
python scripts/report_review_host.py --task-dir /absolute/run --output-dir /absolute/new-review --max-parallel 4 --timeout 1800
python scripts/prepare_adjudication.py --task-dir /absolute/run --first-review /absolute/new-review/1/review.json --second-review /absolute/new-review/2/review.json --reviewer '<主审>' --output /absolute/run/adjudication.json
# 主审对照 adjudication-worksheet.json 填写 adjudication.json 后发布并交付到新入口目录：
python scripts/publish_report.py --task-dir /absolute/run --first-review /absolute/new-review/1/review.json --second-review /absolute/new-review/2/review.json --adjudication /absolute/run/adjudication.json --mode auto --output-dir /absolute/new-build --deliver-to /absolute/new-entry --require-complete
python scripts/completion_check.py --task-dir /absolute/run --first-review /absolute/new-review/1/review.json --second-review /absolute/new-review/2/review.json --adjudication /absolute/run/adjudication.json --output-dir /absolute/new-entry
```

Serper、Signa、SerpApi 只有在创建任务时显式启用或已有任务授权时使用，可使用现有免费或付费账户容量，不承诺来源费用为零；不自动购买、充值、升级或启用超额。Lens 物理响应只在同一提供方、同一国家、相同实际请求参数和有效期内复用；不同权利范围仍分别分流和评级，复用记录不增加独立来源数量。

业务完成要求全部必要义务满足、最终范围双审及主审有效；本轮有界调查结束可交付带具体限制的报告，未查清事实与恢复条件保留。文件构建通过不等于交付成功：统一事务按 10E 核实际入口及应交文件，再由完成检查判定。最终答复风险只来自当前适用且已验证的 `report-data.json`。主页面展示本次主情景、九类结果、已查／发现／未完成和来源日期；完整候选及逐要素比较在 `operator-appendix.html`，代码、JSON、内部编号与技术签名在 `technical-audit.html`，不拼入运营正文。

新任务发布示例：见上方命令；构建目录（`--output-dir`）与交付入口（`--deliver-to`）必须是两个新目录，完成检查对交付入口运行。准备与发布使用同一问题收集器，准备仅省去尚未开始的最终审阅；缺字段不计风险，但伪造身份、损坏原件和未处理可执行材料仍需修复。已有任务只有用户明确重评时创建带前版来源的副本，原件按准确哈希搬迁，旧审阅和旧报告保持不变。

修改 Skill 后的离线验证（`scripts/verify_skill.py --mode fast|release`）与真实召回验收见[安装](references/installation.md)与[召回验收](references/recall-acceptance.md)；离线通过不等于真实召回通过。

## Generic 通用占位品牌

`api-first-v3` 对 Amazon 品牌字段（无 byline 时取 `product.brand`；有 byline 时去掉 `Brand:` 前缀或 `Visit the … Store` 包装后）精确 `strip().casefold() == "generic"` 的通用占位，不执行该名称的文字商标发现或详情查询；所有支持国家一致。报告参考品牌名称查询项显示 **无风险（Generic 通用占位，仅名称项）**。真实复合品牌、独立图样／OCR／标识清单中的标识和用户另行提供的自有品牌仍按相应范围处理；未提供的自有品牌保持未评估。此名称项不改变专利、版权、商业外观、图形商标或总体评级。保留原始品牌字段、历史任务和已发布报告，不新增查询或阶段审核。


### 自动执行累计预算

新任务遵循 `references/continuous-progress-stage-d.md` 的 bounded-execution-v1 限制。来源、回退和排队复核不得靠换动作或重启重置额度。达到额度保留证据、逐项待定原因和运营建议，记录 incomplete/停止原因。预算停止不等于业务完成，九类复核和发布门槛继续适用。历史无标记任务及入口外执行不具备该保证。


内部预算停止后，只对确实未执行且没有关联原件的范围保留“未查询／风险待定”和预算原因，可在已有材料完成双审后生成证据模式部分报告。未读原件、未知提交和完整性异常不能用预算豁免。嵌套执行必须通过受控执行器复用任务进程组；全局截止时间不因分批或重启重置。具体规则见上述预算参考文档。

## 对话提供凭据

发布包直接提供 token 留空的 `config.json`，不使用 config.example.json。用户在对话中明确提供本 Skill 的后台鉴权 token 时，在业务鉴权前自动填写本 Skill 的 `config.json.backend_token`，保留 backend_url 和其他字段。不得回显、记录到报告、提交到 Git 或通过命令行参数传递凭据。

用 `scripts/configure_credentials.py` 接收标准输入 JSON（backend_token 字段；第三方凭据放在 api_keys 对象，以 .env 中准确字段名为键），输出只有成功状态、文件名和字段名。通过文件写入工具或 stdin 传递，禁止在 shell 命令文本、临时脚本或参数里嵌入凭据。脚本原子保存且 Unix 权限为 0600，仅更新用户提供的字段。用户明确给出提供方的 API key 时，自动填写本 Skill 的 `.env` 对应字段；提供方不明确时先确认，不猜测。没有 .env 的 Skill 不接收第三方 API key。

缺凭据时一次说明缺少的项目；用户提供后填写并继续原鉴权流程，不绕过门禁。IPR 的 config.local.json 或非空 LAOCHEN_BACKEND_TOKEN 仍按现有优先级生效；如与新提供 token 冲突，说明来源并只在用户明确要求时更新覆盖。API key 的填写不代表启用来源或授权消耗额度。
