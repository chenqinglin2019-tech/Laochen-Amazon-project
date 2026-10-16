---
name: lc-ipr-risk-screening-free
description: 使用官方来源及用户已启用的数据源账户容量（免费或付费），对单个 Amazon 商品或用户提供的产品资料在美国、英国、法国、德国、意大利、西班牙和日本的专利、外观、商标及版权风险进行证据排查，分国家输出五级风险预判、三级置信度、推论依据、核查事项和离线报告。
---

# 知识产权风险排查

新任务来源采用 `existing-account-capacity-v1` 与 `frozen-source-settings-v1`（见[来源账户策略](references/source-policy.md)）；不再要求免费余额或零费用，允许消耗已启用来源的现有免费／付费套餐及积分，不自动购买、充值、升级或启用超额。`2.4-free` 是保留的兼容标识。新任务使用 `2.4-free`、`api-first-v3`、`final-double-review-v1`、`discovery-purpose-budget-v1`、`discovery-semantics-v1`、`source-operation-v2`、`necessary-work-v3`、`known-findings-risk-v1`、`operator-report-v1`、`product_structure_policy=use_provided_else_unavailable_v1`、`adaptive-double-review-v2`、`execution-efficiency-v2`、`scenario-triage-v1`、`identity-discovery-v1`、`workflow-correction-v1`、`continuous-work-v2` 与 `asset-scope-v1`，以及 `failure-limits-v1` 与 `structured-conflicts-v1`（见 [提速与有据限制](references/workflow-efficiency.md)）。先固定销售情景和产品身份，再全量轻分流，仅深入核验入选候选。有效 API 字段直接支持判断，不强制通过 USPTO 等官方网页重复核验。仅最终冻结后独立双审一次；具体规则先读 [API 直接采信与最终双审](references/api-direct-final-review.md)。总体与各范围的运营筛查等级按已查明具体当前风险计算；没有完成复核的适用判断时显示风险待定，并给出暂缓上架建议；已有适用低风险依据时仍保留未完成事项。未完成动作、缺资料和失败进入真实进度、限制和上架建议，不机械改变已有依据的等级；候选未知／待判断事实不改成已核实或已排除。历史任务保留原策略。

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
- 权利要求层面的二次分流（默认关闭，须先校准）：[声明级二次分流宿主](references/claims-triage-host.md)。
- 比较与评级：[评级规则](references/risk-estimate-rules.md)（新任务 best-estimate-risk-v1 一节）、[制度适用表](references/jurisdiction-rights.md)；阶段选级与旧依据失效：[09B](references/stage-risk-stage-b.md)。
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
- 新任务最终审阅按[执行效率策略](references/execution-efficiency.md)测量完整材料：小包使用两个独立整合会话，大包保持专利、外观、标识与表达的六个模块会话及两个本链汇总会话。两链读同一冻结事实且互不可见，不追加阶段双审或第三轮全量审阅。实质分歧、适用性例外、总体极低和置信度覆写由主审给出依据；不投票、不平均、不默认取高。
- 未执行、失败、截断、提交未知、登记库零结果或可选来源缺失均不能冒充排除证据。未知提交不得盲目重试。
- 总评取主情景中有具体依据的最高适用当前风险；无完成复核的适用判断时风险待定，不从未知推出低风险或排除事实。查询进度独立展示，未完成动作不抬高已有等级，但影响上架建议。不同情景分别汇总；未来申请和维权信号单列。

## 执行流程

### 新任务主路径：一键流水线

新任务默认用一条命令跑完全程：`run_pipeline.py --task-dir <新目录> --url <链接> --all-sources --use-serper-existing-balance --guard-session-id "$CODEX_THREAD_ID" --chief '<主审>'`（r9 起不传 `--jurisdictions` 时按链接站点取国家：美国站 US、德国站 EU+DE、日本站 JP；PowerShell 里会话 ID 写 `$env:CODEX_THREAD_ID`，为空时程序自动取环境变量）。`--all-sources` 启用 Serper、SerpApi、Signa 免费额度，`--use-serper-existing-balance` 是用户对 Serper 已有额度的使用授权；两者缺任一使 Serper 与 SerpApi 都不可用时，流水线在建任务后以 `PIPELINE_DISCOVERY_SOURCES_DISABLED` 停下（只用 EPO 会得到空报告），确需仅用 EPO 时加 `--allow-limited-sources`；一轮检索都没有真正提交时以 `PIPELINE_NO_SOURCE_EXECUTED` 停下，不进入终审。它按固定顺序调用下文各命令，宿主与程序直接登记分流、专项事件、比较和主审草稿；只在检查点退出（退出码 3；r6 新任务只有 ① 和 ③，见下文“报告必出”）：① 产品范围草稿 `checkpoints/1-scope.json` 的三个字段（页面有 PATENTED 但无号码、且自动检索与逐要素比对没有找到对应专利时，另在 1b 做专利标注解析）；② 宿主留下被拒单元或准备阻断项；③ 两审有实质分歧的主审行。处理完用 `--resume` 继续；失败退出码 1 并打印错误码与恢复命令。结果审阅判定"未覆盖"的检索由程序自动细化（`auto_refine.py`），细化用尽时作为有界检索限制披露；第三方零售页卡片默认不入选。r5d2 起的新任务另有核心聚焦（`core_focus.py`）：已届满、非美国公开、专利页面和无权利身份的卡片由程序默认不入选，专利只在同类或同用途时入选，详情额度先给核心候选，已授权申请改用授权权利要求，额度用完后用公开页的公开文本比较。r5d3 起的新任务另有少停与终审提速（`review_focus.py`）：只有标题的公开网页卡由程序先取回网页再分流，只能问用户的第三方网页卡由程序收口，比较会话每次 2 个候选并行，终审某一模块或汇总被拒时在同一次终审里自动重跑一次，汇总不再抄写哈希，终审材料包不再携带不入选候选的原文与分流长文。r5d17 起的新任务另有外观终审前筛查（`design_screen.py`：逐视图比对与互不知情的复核会话都认定整体视觉印象明显不同的外观，移出终审、列入附录；整体相似或判断不了的照常双审）和提速（终审材料按内容去重、比对 5 路并行、空转轮跳过）。流水线输出 `status: delivered` 时，交付事务已含入口检查与完成检查：直接读取报告向用户汇报，不再运行 `publish_report.py`、`completion_check.py`，也不另建输出目录。阶段、状态文件与恢复见 [一键流水线](references/pipeline.md)。下文逐步流程是流水线内部顺序，也是手工续作路径。

r5d4 起的新任务（`pipeline_robust_revision`、`prereview_screen_revision`）另有“不中途停下”与终审前筛查：运行期间保持电脑不睡眠（Mac `caffeinate`、Windows `SetThreadExecutionState`；合盖用电池仍可能睡眠，跑任务请接电源）；方向或提交前审阅没过的检索不再占用轮次，审阅会话失败自动重跑一次；商品图超过 6 张时视觉分流取前 6 张并披露；美国外观专利号按 Google 写法（`USD…S1`）取详情，来源明确答复“查无此记录”的由程序收口并作为限制保留；检测到本机 fake-IP 代理（198.18.0.0/15）时公开附图可经代理下载；GIF／TIFF 原件登记为 PNG；进入终审前，已放弃满 2 年且从未授权（或保护期届满）、美国关联申请也都终止的发明专利由程序规则排除，逐要素比对与独立排除复核两次判断一致认定产品在每项独立权利要求上都缺少必要特征的发明专利也排除，排除的只列在报告附录。外观专利在 r5d4–r5d16 的任务里不做终审前筛查；r5d17 起的新任务见下文。

**报告必出（r6，用户 2026-10-15 决定）**：task.json 里 `stability_revision` 为 `report-always-v1` 的新任务，只在两处停下等人——检查点 1（用户确认产品描述）和检查点 3（主审裁决分歧行）；不再出现检查点 2、检查点 1b 和 owner_action，下文针对这三者的规则对这类任务不适用。
- 终审某一审阅链的某个模块重试后仍取不到可用结果（网络中断两次、回答无法解析、时间或额度用尽），该模块在这一链按待定处理（`fallback`），由另一审和主审在检查点 3 裁决；两审都取不到的行显示风险待定，报告照常发布。
- 模块回答里个别不合规的行由程序修正或转为待定（写明原因），不再整份拒收；场景哈希、模块号等字段由程序补齐。链汇总由程序写。终审有截止时间，全程不超过 40 分钟。
- 检查点 3 的工作表里标有 `other_review_unavailable` 的行只有一审给出结论：主审核对这一审的依据后填写等级、状态和理由，可以改判。其余分歧行照旧对照两审裁决。
- 发明专利定级：全部要素可见且对应→高；可见要素都对应、有看不到的要素→中，写明需拿样品核对的要素；要素一个都看不到→低，提示核对；有要素不对应→低。极高只在页面标注的专利号就是该专利、现行有效且全部要素对应时适用，"patent pending"不算标注。程序在主审草稿里执行这条规则。
- 页面标注 PATENTED 却查不到对应专利时，程序记为"未解析"并在报告中提示，不停下手工检索。
- 输出里有 `degraded_steps`（程序的记账步骤失败后跳过并披露）时照常继续；出现 `PIPELINE_UNEXPECTED_*`、`PIPELINE_READINESS_NOT_SETTLED` 等失败时，把输出原样转告用户并打包运行目录，不要手工改记录或脚本。

**专利检索一定执行、检索词只用本品叫法（r7，用户 2026-10-16 决定）**：task.json 里 `search_guard_revision` 为 `search-guard-v1` 的新任务另有：
- 开跑前和生成检索计划前各读一次 SerpApi 余额（账户接口，不计次），输出里的 `search_notice`（剩余几次、哪天恢复、本次走哪条路）原样转告用户。
- 余额不够本次美国发明与外观检索时，这几条检索改用 EPO（只查美国文献，条数不变）；EPO 也不能用时在开跑前以 `PIPELINE_PATENT_SEARCH_UNAVAILABLE` 停下。检索阶段结束时美国发明、外观检索一条都没成功，以 `PIPELINE_PATENT_SEARCH_NOT_EXECUTED` 停下，不出报告；转告用户，等额度恢复后新建任务，不要手工补检索。
- 外观检索只用含本品核心词的叫法（眼线印章笔不再用 cosmetic applicator 这类领域总称），发明检索名单不变；图片、网页与维权检索改用确认的具体叫法，每类权利一条。
- SerpApi 深查详情每个任务最多 8 次，先给外观同款主体层和发明核心层候选，其余候选的现行状态记为未核验；没有详情的已授权公开申请，由免费公开页找出同一申请的授权号，按授权权利要求比较。
- 终审提示词重新写明比较依据格式（r6 遗漏）；审阅把比较依据写成文字时程序保留原文，低风险行不再被改成待定，外观不再显示“已入选待比较”。细节见 [一键流水线](references/pipeline.md) 的 r7 一节。

**r8（2026-10-16，新任务 `search_guard_revision` 为 `search-guard-v2`；旧值 `search-guard-v1` 的任务照旧受上面各条保护）**：
- 美国外观的 EPO 路线写进新任务的路线表；一条检索被来源拒绝时只记这一条，同批其他检索照常发出。图片、网页、维权的品名检索不再在发出前被撤销。
- 发明、外观、版权等某一范围的检索全部在发出前被程序撤销时，报告照出，并把该范围列为“未检索、无结论”的限制，不写成低风险。
- **SerpApi 备用 key**：`.env` 可另填 `SERPAPI_API_KEY_BACKUP`（主 key 仍是 `SERPAPI_API_KEY`）。开跑前的余额检查发现主 key 不够本任务（美国检索 + 最多 8 次详情）而备用 key 够时，本任务全程改用备用 key；`search_notice` 会写明。已经发出 SerpApi 请求的任务不再换 key。用户在对话中给出备用 key 时，用 `scripts/configure_backup_key.py`（标准输入 `{"SERPAPI_API_KEY_BACKUP": "..."}`）保存，规则与上面的凭据填写相同。
- 停在发布环节、报错 `EVIDENCE_UNRESOLVED_SCOPE_WITHOUT_LIMITATION` 的 r7 任务，装好 r8 后用 `--resume` 续跑即可出报告，不再消耗检索次数。

**r9（2026-10-16，新任务 `portable_revision` 为 `portable-v1`；用户要求“流程已跑通，不大修大改”）**：
- **联网权限**：`run_pipeline.py` 要联网（鉴权、检索、下载）。Codex 请求授权时允许这条命令联网，或用可联网的权限运行；不要改用户的代理软件或系统网络设置。
- **流水线输出里的提示原样转告用户**：`search_notice`、`scope_notice`（本任务不会检索的国家／权利）、`market_notice`（链接站点不在所查国家内）、`network_notice`、`model_notice`（审阅模型在这个账号上不可用）。
  - `network_notice` 是“已自动兼容”的一行时，提一句即可。
  - 以 `PIPELINE_GOOGLE_UNREACHABLE` 停下时，把说明交给用户，等对方打开代理（TUN 或系统代理）后用同一条命令重跑。
  - 以 `PIPELINE_PYTHON_DEPENDENCIES_MISSING` 停下时，按说明运行 `setup_skill.py --install-deps`，改用技能 `.venv` 的 Python 后重跑。
  - 以 `PIPELINE_NOTHING_SEARCHABLE` 停下时（例如只查日本、本技能没有日语检索词），把说明原样转告用户；不要手工补检索词或改国家，由用户决定是否按美国新建任务。
- **代理**：本机 fake-IP 代理（198.18.0.0/15）和只开“系统代理”／设了 `HTTPS_PROXY` 的情况，下载都由程序自动适配，不需要改代理。
- **欧洲／日本**：用欧洲或日本链接时不要写死 `--jurisdictions US`。程序目前只生成英文检索词，德、法、意、西、日本国的专利、外观等范围不检索，报告列为“未检索、无结论”。欧盟层（EP 专利、欧盟商标）和英国照常检索。
- **报告里的外观检索覆盖**：读到单次上限（前 100 条）时写明“排在其后的结果没有读取”，不再写“某日之后授权的外观不在检索范围”。
- 细节见 [一键流水线](references/pipeline.md) 的 r9 一节，安装见 [安装](references/installation.md)。

r5d4 起对 Agent 的两条规则：
- **检查点 2**：先运行一次 `run_pipeline.py --task-dir <同一目录> --resume`（程序会先补跑一轮派发、分流、核心资料、比对和筛查，多数待办由此关闭），仍停下时再按清单处理。流水线管理的任务不要直接调用 `run_api_plan.py`，它绕过进度记账和派发门槛；需要派发时用 `advance_work.py --execute-sources` 或 `--resume`。
- **外观附图与分流不手工补**（r5d7）：美国外观在 Google Patents 没有页面（404）或附图被拒（403，2025 年后授权的多如此）时，程序自动从 USPTO 官方授权 PDF（`image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/D…`）逐页取图登记，再做视觉分流；检查点 2 前的补跑会重复到不再有变化（最多 3 轮），过期的结果审阅也由程序重做。Agent 不要自行下载附图、重开分流或手工审阅检索结果；这些手工改动会使已规划的细化检索作废并连锁出现新的待办。检查点 2 再次停下时，把清单与运行目录交给维护者。
- **外观以官方授权 PDF 为保护内容**（r5d8）：程序取到 USPTO 授权 PDF 的外观，专项登记直接以该 PDF 为保护内容材料（没有 SerpApi 记录时也以它确认号码与标题），再逐幅做视图比较；现时状态与权利人仍按记录缺口作为限制保留。已登记过的同一外观续跑时由程序补登，Agent 不要手工登记专项材料。
- **睡眠提示**（r5d8）：流水线输出里有 `sleep_warning` 时，原样转告用户（电脑睡眠了多少分钟、跑任务要接电源且不要合盖）；这不是错误，不要因此停下或改动任务。
- **分析额度**（r5d9）：模型分析时长额度只计电脑醒着的时间，旧版本按墙钟记下的睡眠会自动退回。检查点 2 的清单里有 `analysis_budget` 时，额度确已用完：把它的 `message` 原样转告用户并请其打包运行目录，不要手工补做比较或分流。
- **终审网络中断**（r5d10）：r5d4 起的新任务，终审中被网络切断的模块或汇总会话（`stream disconnected`、`Transport error` 等）在同一次终审内自动重跑一次，时间不够则停下。终审失败停下时，把失败原因原样告诉用户。如果剩余终审额度不够再跑一轮，只能请用户本人在终端运行 `extend_review_budget.py`，代理不得代为执行；之后再 `--resume`。不要手工改审阅结果。
- **终审前筛查与材料范围**（r5d12）：保护期已届满的美国发明专利（含欠费失效），只要全部美国关联申请也已终止或届满，就在终审前由程序排除，只列在报告附录。终审各模块只收自己的材料，同一专利只发一份全文。这些都是程序规则，Agent 不要手工改判或补发材料。
- **外观终审前筛查**（r5d17，用户 2026-10-13 决定）：逐视图比对与互不知情的复核会话都认定整体视觉印象明显不同的美国外观，在终审前由程序移出，只列在报告附录并写明专利号与差异；个别共同点或个别看不到的视图不影响移出，整体相似或判断不了的照常进终审双审。这是程序规则，Agent 不要手工改判，也不要把移出的外观送回终审。
- **同一文件两种编号写法**（r5d18）：EPO 与 Google 对同一件美国专利的写法不同（`USD1035381S`／`USD1035381S1`，申请公开号少一个 0）。r5d18 起的新任务把它们合并为一个候选；r5d17 任务里已经分成两个候选的，核心阶段由程序补登另一份详情记录的读取。检查点 2 的清单里出现 `SOURCE_RESULTS_PENDING_PROCESSING`（`read_retained_patent_record`）时，先按上文 `--resume` 一次，不要手工登记记录读取。
- **外观先看主体、专利用语检索**（r5d20，用户 2026-10-14 决定与授权）：新任务的外观比对、终审前筛查和终审评级都先看主体造型——同品类、主体造型相同、只有端面／把手／附件等次要差异的外观至少评高，主审预填不会把它定得更低；只有主体基本形状不同才在终审前移出。美国专利与外观改走 Google Patents，用产品理解给出的专利常用品名和核心功能概念组检索（每条 100 条、只取仍可能有效的权利），EPO 只作只查美国文献的后备；结果多时先做标题／首图批量初筛。这些是程序规则，Agent 不要手工改判外观等级，也不要把概念组改回商品标题短语。详见 [一键流水线](references/pipeline.md)。
- **缩小候选、30 分钟出报告**（r5d21，用户 2026-10-15 决定）：本机所有模型会话共用 4 个名额，遇到限流（429）在同一步里等待后重跑；一个用户同时跑两个任务也不会再被限流，但各自变慢，要 30 分钟内出结果请一次跑一个。新任务里，检索卡片显示美国已失效的专利由程序排除；初筛就是分流（外观看图分 same／similar，发明看标题摘要分 core／related，并写一句入选理由），深查最多外观 8 件、发明 6 件；取不到附图的外观只有标题与本品同名才深查。机器时间约 22 分钟仍有未完成项时，程序把它们列为本轮未完成（`TIME_BOX_REACHED`）并照常终审、发布，不在检查点 2 停下。这些是程序规则：Agent 不要手工改判初筛、不要绕过深查上限，也不要在收口后手工补做。详见 [一键流水线](references/pipeline.md)。
- **卡住的会话**（r5d22，所有任务）：模型会话开始后迟迟没有任何回答、而同类会话早已完成时，程序提前停止并重跑它（终审的模块在同一次终审内重跑一次）；执行记录里的 `stalled` 不是错误，Agent 不要因此手工处理。终审失败后续跑时，程序按另一审的用时估算所需时间。r5d23 起，回答已交出但回合迟迟不结束的会话同样提前停止重跑；文本初筛登记不了的候选不再挡住新检索，同一份材料不再反复送审。r5d24 起，外观看图初筛只取初筛要看的前两张附图（近期授权的外观直接取 USPTO 授权 PDF），入选深查后再补齐；终审附图总量超限时改走分模块审阅，不再报错。r5d25 起，新任务的美国外观只用一条品名词组检索（含本品品类名、不含上位名），候选更少更准，报告写明外观检索的授权日边界；评为中、高的外观在报告里显示为已比较；网络中断的检索和终审会话自动再跑一次。详见 [一键流水线](references/pipeline.md)。
- **未启用的条件情景**（r5d19）：用户说明用自己的品牌、不沿用对方品牌时，“沿用参考标识”条件情景（`brand_reuse`）不在任务的 `execution_scenario_ids` 里，没有必做工作。终审把它的两行写成未纳入范围（`out_of_scope`）是合法的，与写待定一样不进入报告正文。终审因 `OUT_OF_SCOPE_NOT_BOUND_TO_TASK` 停下时，换上 r5d19 或更新版本后 `--resume` 一次即可，已完成的模块审阅会直接复用；不要手工改审阅结果，也不要往 task.json 里加排除项。
- **终审额度不足**（r5d11）：流水线输出里有 `owner_action` 时，额度确实不够这一轮终审，开跑必然超时。把 `owner_action` 原样交给用户：里面有完整的终端命令和确认文字。用户在本机终端运行成功后，再 `--resume`。Agent 不得代为执行，也不要在额度不足时反复续跑。
- **许可默认无**：除非用户在任务开始前提供了许可和完整授权链文件，否则一律按用户没有任何许可评估。不得因许可未知而停下或向用户索取，也不要把“向供应商或权利人索取许可、授权链”写成下一步、上架前提或核实项。用户确有许可时，在检查点 1 的 `scope.reasoning`（备注）中写明并给出文件路径。

### 每次退出前的强制闭环

本段适用于新任务、续跑及范围修订后的同一任务。代理不能仅凭已有线索或一次搜索给出“排查完成”的风险结论。每次准备结束当前轮次时：

1. 先运行 `advance_work.py --task-dir /absolute/run --output-format compact`，读取全部 `source`、`agent`、`repair`、`review` 动作卡和等待项；若本任务已有最终审阅、主审或交付目录，必须同时传入现存的 `--first-review`、`--second-review`、`--adjudication`、`--output-dir`，否则调度器会误把已完成审阅重新列为动作。有可执行动作就继续执行并重算，不把计划、搜索结果数、网页浏览或本地调查行当成已完成审阅。
2. 范围、产品事实或查询方向改变后，先修复受影响的计划绑定、语义审阅和执行进度，再进入来源提交；已有真实回执和候选仍要逐条处理。若动作重复或无进展，依 08D 诊断和技术停止规则处理一次，不靠重复运行调度器消耗轮次。
3. 仅当可执行来源、已取得材料、候选分流、专项比较和最终输入均已闭环，才调用 `report_review_host.py` 启动冻结后的独立双审；宿主给出的准备问题必须逐项关闭，不能手工伪造双审文件。
   对独立留存的官方批量导出先核对原始行数、去重身份数、当前候选台账与逐件分流数。若人工官方结果没有正式入账，`ready=true` 也只表示结构化输入可冻结；不得声称该批候选已全量分流，双审和 HTML 必须明确列出未入账范围及恢复条件。XLSX 等宿主不直接读取的格式应先生成与原件哈希绑定的纯文本阅读副本；图形候选须提供实际标样图片，不能仅给文字描述。
4. 统一发布命令 `publish_report.py --deliver-to NEW_ENTRY --require-complete` 已包含真实入口完成检查，成功返回后不立即重复运行相同 CLI；其他发布入口、跨进程续作和用户单独验收仍运行 `completion_check.py`。只有返回 `complete` 或 `limited_round_closed` 且报告入口真实可读，才能对用户输出对应的最终风险报告。返回 `continue`、`awaiting_user`、`execution_stopped` 或 `error` 时，只报告准确进度、已验证发现、具体缺口及恢复动作；不得把本轮发现包装成最终排除或完整核验。`limited_round_closed` 必须明示仍未完成的业务义务与恢复条件。

统一发布事务的内置完成检查或独立 `completion_check.py` 必须成功，才能宣称已交付；它只是只读门禁，不代替第 1 步的实际执行。用户请求继续时从现有任务目录和真实回执续作；但 `task.json` 的 `best_estimate_revision` 不是 `best-estimate-risk-v2` 时，它是旧版技能创建的任务（`advance_work.py` 输出首项 `legacy_task`、`run_pipeline.py` 以 `LEGACY_TASK_POLICY` 拒绝），新版流程对它都不生效：先如实告诉用户，并按输出的 `recommended_command` 用一键流水线在新目录新建任务；只有用户明确要求续跑这个旧任务时才继续（流水线加 `--allow-legacy`）。其余情况先运行该闭环，不新建同一商品任务或重做已完成查询。

查询前以保留图片复核商品名称与实际构造；商品同时有功能件和独立装饰件时，两类相关分类都要进入方向清单。带 `AND`、`OR` 等保留字的商标短句使用来源支持的字段精确语法，并核对回显表达式与结果量。官方网页的人工结果只有在原件、实际查询及候选处理被当前任务绑定后才计入覆盖；工作区尚需跨轮复核时，在建立后及取得重要结果后即时按来源操作规范标记 `markHandoff()`，并及时导出原件，不等到退出前。同一阻断状态和证据摘要未变化时，不重复生成计划或重跑调度器，直接记录限制及恢复条件。

1. 鉴权后创建任务，记录 `input_role`、产品身份、国家和情景。仅有竞品链接时默认拟售功能、结构、外观一致且使用自己品牌的同款商品；参考品牌、摄影和附属包装按默认未纳入。本体装饰、作为目标商品的礼品盒或装饰画按真实关系处理，不普遍追问品牌用途。
2. 完成 credentials 预检；链接入口执行 Amazon 多视图采集，资料入口用 `product-input-v2` 明确选定查询主图或记录歧义，再执行 `record_user_product.py` 留存资料。首次核对后冻结具体目标，两路以 `product-scope-input-v2` 调用 `record_product_scope.py`，记录对象四态、逐项事实性质与版本、主图呈现限制、许可和方向依赖。仅针对已核查仍存在的实质矛盾询问具体对象，再用 `record_product_analysis.py` 登记可追溯术语；页面声明或模糊 OCR 可作待核实线索，不能直接写成已证实结构。原始线索须映射到术语或给出排除理由。页面或资料出现 patent／patented 等标注时，`advance_work.py` 会把 `PATENT_MARKING_RESOLUTION_REQUIRED` 排在动作卡最前：按动作卡先解析标注（官网虚拟标记页 → 一次 Google Patents 品牌＋产品词检索 → `record_candidate_lead.py` 登记号码并自动预留详情额度），再进入广泛发现检索；无法解析也要用 `record_product_analysis.py --revise` 记入 `patent_claim_followup`。新任务的动作卡按核心优先排序：标注解析 → 入选候选核验／补证 → 原件阅读 → 发现检索。
3. 生成初始计划后，先按[09A 唯一计划项与进度](references/review-progress-stage-a.md)登记执行前工作项，再按[方向与语义审阅](references/discovery-semantics.md)记录方向清单与每条发现查询的提交前审阅，再执行 API／网页计划；实际返回后记录第二次语义审阅，并按[来源操作验收](references/source-operations.md)检查实际字段、分页及操作能力。新任务先运行 `mechanical_ledger.py`（默认步骤含 `operation_reviews`、`bounded_stop`：仅对有精确验收证明、单页有界的公开检索自动写操作验收与 after 语义审阅／有界停止，留痕 `program:*`，证明不成立即留给 Agent），再运行 `discovery_review_host.py` 处理其余单元。图像路线只取绑定的目标主图，提交前复核图片、目标版本、来源能力及接收方/用途许可；用户文件目前不自动外传，路线不足记局部缺口，其他工作继续。来源故障继续其他来源；首源成功但无相关候选时，审阅真实结果后才按规则启用已授权替代。
4. 合并候选，先按[原始结果与处理进度](references/source-result-processing.md)核对每个真实回执的已得位置、解析与去向；失败回执的可读材料仍需处理，缺口不能写成零条或完成。再按[候选身份与纠正](references/candidate-identity.md)保留残缺身份线索、原始号码、同申请／同族／地域关系和旧引用；清单成员只是线索，不继承父记录来源或结论。归并、拆分与字段取舍须追加引用原来源行的审阅事件，实质受影响判断重审，纯重复发现只补来源。按[执行计数与增量交接](references/candidate-accounting-handoff.md)分开核对执行时消耗和当前候选，逐候选、情景及国家交接已审材料；局部交接不关闭其他结果缺口。通过范围记录中的 `candidate_links` 关联具体对象；按[候选分流范围](references/candidate-triage-scope.md)先处理未纳入／待确认，再对已纳入部分作有证据的三路决定。国别或类型未知的候选保留定位待办；具体关联可以先入选，但身份未定位不得派生专项出网动作。仅新版公开视觉销售线索可依候选分流范围规则追加有界身份调查凭据，转入带明确未知事实及恢复条件的 evidence 受限交付；实际补图或未审材料继续处理。可在一次输入中向 `annotate_materiality.py` 提交 `decisions[]` 和对应 `discovery_reviews[]`，记录器先验证整批，再一次落盘。已有准确案号通过 `record_candidate_lead.py` 接入，不伪造搜索命中。
5. `generate_search_plan.py --expand` 仅追加有依据的权利人、分类、分页和最小补证动作。对 `needs_info` 按[候选补证闭环](references/candidate-followup.md)先审已存材料、分类实际请求，再绑定发现或混合用途并逐次审阅结果；按[候选阶段闭环](references/candidate-triage-stage.md)先处理已得未审材料、及时交接入选、定向重开并单独判断模块完成。定向读取不借“核验”名义寻找未知对象。新任务按[发现目的与版本预算](references/discovery-purpose-budget.md)记录同一目的最多初始加两次审阅后调整；同版本跨来源合计最多实际获取八页、尝试两条路线，浏览器补搜最多主动取得五十个去重候选。已返回超额卡片全部保留；边界不是必跑量或覆盖证明。不要轮换营销长句或用固定 Top N 丢候选。
6. 绑定素材清单后执行图形标样、版权及商业外观公开调查。共享的创作、来源、首次发布和功能事实可用一次 `record_asset_provenance.py` 调用绑定多个兼容 `--query-id`；各国地域、期限和法律适用仍分别判断。
   对已交接的专利／外观入选对象，用 `record_specialty_analysis.py` 逐范围登记本轮核验基准日、材料实际阅读、基础事实及免做，随后记录每项权利要求／设计的比较、补证和批次去向；本模块事实与完成状态分别交后续待办、评级和交付，不在此处选风险等级。
   对已交接的商标／版权／商业外观入选对象，使用 `record_distinctive_rights.py` 记录当前对象和版本、07 独立评估日、登记及公开事实两条路线和实际材料阅读；商标另记逐维比较，版权另记来源、主体关系、表达及许可范围，商业外观另记主张、地域规则、使用、功能性与混淆。公开维权按事件保留原始主张、处置、进展、正式决定及来源层级。逐缺口先读已有材料并最小补证，按真实来源批次核对材料去向；局部结果可向 08—10 增量交接，正常完成、等待和有据受限分别按当前对象范围记录。局部事实和审阅不等于专项完成；无登记、零结果和失败均保留原含义。
7. 查询过程中不询问实际结构相关信息。用户已提供的结构资料默认使用，并留存来源及 `user_claim/claim_only` 等事实性质；没有提供默认用户无法提供，保留相应 unknown／无法判定并继续可判断部分。内部结构不能由外观相同、功能相同、营销声明或没看到某部件推定。结构缺口走 `record_product_feedback.py` 留存不可提供记录及受影响事实／候选，不进入用户待答；旧结构请求在用户明确采用本规则后也保留历史并按不可提供投影。非结构且实质阻断的范围矛盾仍按原规则处理。补充资料仍经 `record_product_scope.py` 追加留存，反馈关闭须引用已推进版本的事实和来源；旧查询、阳性证据和未受影响判断保留。事实纠正／撤回或范围变化产生有界影响清单；目标明确更换走 02B 受控入口，未审受影响候选不得混入当前判断。图片重压缩只保留原件／派生关系，新增视图要绑定受影响对象或事实。依赖冲突只暂停相关动作；同一权利类型不能整体停掉。持续运行 `advance_work.py`：依[08A 统一工作视图](references/continuous-work-stage-a.md)处理精确来源行、Agent 阅读、调查、分流、计划修复和范围审阅，再重算待办；共享动作只执行一次，各问题分别验收。已提交失败或提交未知按[08B 来源恢复](references/continuous-recovery-stage-b.md)核原回执与恢复依据后再安排；用户主动暂停和恢复前对账按[08C 任务控制](references/continuous-continuation-stage-c.md)处理，访问反馈须验证原查询能力且不自动解除主动暂停。逐工作进展、两轮诊断和有界技术停止按[08D 执行收尾](references/continuous-progress-stage-d.md)登记；技术停止只封锁相同动作，保留未完成与恢复条件。真实外部限制可以成为最终 evidence 报告限制，但可执行工作、未审材料和提交未知仍阻断发布。
8. 入选专利／外观候选先运行 `core_dossier.py --task-dir RUN`（留存 API 详情所列官方附图与授权 PDF，程序登记身份、地域、状态、保护内容、权利人等专项事件），再运行 `comparison_host.py --task-dir RUN`（一次模型会话按独立权利要求逐要素比较，引文必须逐字出自留存权利要求，程序登记清单与比较事件）；Agent 不再手写专项事件。对实际已完成并审阅的成果按[09B 阶段判断与失效](references/stage-risk-stage-b.md)记录事实分析和比较；新任务不执行 09C 阶段双审。所有可执行计划扩展、来源处理、分流和范围修复完成后，直接运行最终审阅宿主，由冻结入口一次性执行准备检查、列出全部问题并创建内容绑定收据；仅在准备通过时按[完整报告宿主](references/report-review-host.md)冻结共同输入并独立双审（宿主按平台自动选择隔离后端；单独的 `review_readiness.py` 不是必经步骤）。API 已支持的字段不再新增官方网页核验；具体缺口按已有材料、同来源、其他 API、必要网页的顺序有界补证。
9. 主审确认最终两审结果：先运行 `prepare_adjudication.py --draft-selected-candidates --auto-agree` 生成绑定当前摘要的 `adjudication.json` 骨架与冲突工作表（入选专利候选按专项比较事件预填 `comparison.implementations/claims`，`risk` 为空，主审只填等级、状态与理由），无实质分歧时绑定双方摘要；有争议时在对应决定行填写差异和依据（reviewer、session_id、adjudication_reasoning 须由主审填写，否则发布门禁拒绝）。新任务按 [best-estimate-risk-v2](references/risk-estimate-rules.md) 评级（`--auto-agree` 由程序写好两审一致行的主审理由，并在冻结输入满足“API 现行有效＋页面专利标注＋独立项要素对应”时按规则定极高；输出 `open_decisions` 为 0 时主审只签名）：每个适用范围给出最佳估计等级与置信度，待定仅限既无检索收据、无材料也无制度依据的范围；该国不存在的制度（如美国实用新型、未注册外观）引用 `EV-INST-*` 制度证据写不适用；维权信号参与总体等级；自有品牌未提供只单列提示，不锁上架建议。新任务采用语义输入摘要：进度日志、生成时间及同哈希文件路径变化不重审；实质变化只重审受影响单元及总体影响，使用各审阅位原审阅凭据引用未变化判断，保留旧摘要和执行签名。按[API 直接采信与最终双审](references/api-direct-final-review.md)执行复用，不改绑旧审阅。业务完成和 HTML 读取同一最终双审结果；剩余有据外部限制可以形成受限本轮报告。运营报告在新目录以 `publish_report.py --deliver-to <新交付目录> --require-complete` 一次执行构建、固定版本、复制与完成检查。一次真实独立语义复算后，只在本进程不可变事务内复用；后续每步重核来源、审阅、所有文件字节与本地引用，独立 CLI 检查仍完整复算。并按[10D 独立校验](references/delivery-inspection-stage-d.md)及[10E 固定版本与交付](references/delivery-versions-stage-e.md)核对实际送达入口。历史任务保持其原阶段／完整双审与发布协议。

## 命令入口

先使用本 Skill 的虚拟环境解释器。下例中的 `python` 在 macOS 替换为 `.venv/bin/python`，Windows PowerShell 替换为 `& .\.venv\Scripts\python.exe`；完整命令显式使用 `-X utf8`。鉴权调用顺序与 [INSTRUCTIONS.md](INSTRUCTIONS.md) 保持原样。

```bash
# 本机网络（可选，只读，不鉴权、不取数）：DNS、正在用的代理（fake-IP／系统代理）和与 Google 专利网站的 TLS 握手；fake-IP 已自动兼容，不用改代理
# python -X utf8 scripts/setup_skill.py --check-network
# 新任务主路径（一键流水线；检查点处理后加 --resume 继续；--dry-run 只列阶段；不传 --jurisdictions 时按链接站点取国家）
python -X utf8 scripts/run_pipeline.py --task-dir /absolute/new-run --url 'https://www.amazon.com/dp/B012345678' --all-sources --use-serper-existing-balance --guard-session-id "$CODEX_THREAD_ID" --chief '<主审>'
# 以下为流水线内部各步，供手工续作：
python -X utf8 scripts/auth_gate.py
# --guard-session-id 取当前会话的真实 ID：bash/zsh 为 "$CODEX_THREAD_ID"，PowerShell 为 $env:CODEX_THREAD_ID；非 Codex 宿主不传并披露“结束保护未启用”
python -X utf8 scripts/create_task.py --url 'https://www.amazon.com/dp/B012345678' --jurisdictions US,GB,FR,DE,IT,ES,JP --guard-session-id "$CODEX_THREAD_ID"
python -X utf8 scripts/preflight.py --task /absolute/run/task.json --phase credentials
# 用户资料入口改用以下创建命令，不与上一条同时执行：
# python -X utf8 scripts/create_task.py --product-input /absolute/product-input.json --jurisdictions DE --guard-session-id '<真实 Codex session_id>'
# credentials 预检后资料入口执行 record_user_product.py，跳过下面的 Amazon 采集三条命令。
# python -X utf8 scripts/record_user_product.py --task-dir /absolute/run
node tools/cdp/cdp-cli.mjs doctor
node tools/cdp/cdp-cli.mjs capture-amazon --task-dir /absolute/run
python -X utf8 scripts/record_browser_product.py --task-dir /absolute/run --capture /absolute/run/browser-capture.json
python -X utf8 scripts/record_product_scope.py --task-dir /absolute/run --input /absolute/scope.json
python -X utf8 scripts/record_product_analysis.py --task-dir /absolute/run --input /absolute/analysis.json
python -X utf8 scripts/preflight.py --task /absolute/run/task.json --phase evidence
python -X utf8 scripts/generate_search_plan.py --task-dir /absolute/run
python -X utf8 scripts/record_review_progress.py --task-dir /absolute/run --input /absolute/review-progress-initialize.json
python -X utf8 scripts/record_discovery_semantics.py --task-dir /absolute/run --input /absolute/direction-review.json
python -X utf8 scripts/record_discovery_semantics.py --task-dir /absolute/run --input /absolute/before-query-review.json
python -X utf8 scripts/run_api_plan.py --task-dir /absolute/run --phase discovery
python -X utf8 scripts/record_discovery_semantics.py --task-dir /absolute/run --input /absolute/after-result-review.json
python -X utf8 scripts/record_source_operation.py --task-dir /absolute/run --input /absolute/source-operation-review.json
python -X utf8 scripts/merge_candidates.py --task-dir /absolute/run
python -X utf8 scripts/annotate_materiality.py --task-dir /absolute/run --input /absolute/triage-and-discovery-reviews.json
python -X utf8 scripts/generate_search_plan.py --task-dir /absolute/run --expand
python -X utf8 scripts/advance_work.py --task-dir /absolute/run --execute-sources --write-agent-packet --output-format compact
# 动作卡带 input_template 时，先用它生成预填的输入文件再只填 null 字段：python -X utf8 scripts/input_template.py --task-dir /absolute/run --output-dir /absolute/new-templates
# 主动重审某个方向（例如未映射线索原为 awaiting_information、现有证据已回答）：加 --direction-rereview 情景:权利:国家（如 product_entry:design:US），同一线索清单与方向时自动带入在案复审的未变部分，只填 reviewer、reason 和未映射线索
# 新任务（create_task 已冻结 host_triage_revision）：下列宿主各自处理全部当前待办并直接登记，失败/无效项保留待办，不登记排除；动作卡的 batch_* / mechanical_ledger 字段会给出对应命令
python -X utf8 scripts/mechanical_ledger.py --task-dir /absolute/run
# 默认步骤已含 operation_reviews、bounded_stop（须在 discovery_review_host.py 之前运行；只在精确验收证明与单页有界范围可证明时登记，其余留待 Agent）
python -X utf8 scripts/discovery_review_host.py --task-dir /absolute/run
python -X utf8 scripts/text_triage_host.py --task-dir /absolute/run
python -X utf8 scripts/visual_triage_host.py --task-dir /absolute/run
# 可选（默认关闭，仅创建任务时 --claims-triage-host 才启用；先在已完成任务上 --calibrate，不安全分歧须为 0）：权利要求层面的二次初筛
# python -X utf8 scripts/claims_triage_host.py --task-dir /absolute/run --calibrate
# 只读诊断：墙钟里程序步骤与书写/空闲的分布、取数计划重复行
python -X utf8 scripts/timing_attribution.py --run-dir /absolute/run
python -X utf8 scripts/record_stage_risk.py --task-dir /absolute/run --input /absolute/stage-risk-review.json
# 新任务最终双审必须经宿主（自带 readiness 与冻结；macOS 沙箱、Windows 无工具进程隔离；手工 record_independent_review.py 仅用于历史任务）
# 启动前先干跑（只读：不写文件、不启动模型、不扣预算）：核对运行时钉住、就绪、各模块提示词大小(<1,048,576 字符)、留存槽位与预算；退出码非 0 不要启动，按输出的错误码处理
python -X utf8 scripts/report_review_host.py --task-dir /absolute/run --output-dir /absolute/new-review --preflight
python -X utf8 scripts/report_review_host.py --task-dir /absolute/run --output-dir /absolute/new-review --max-parallel 6 --timeout 1800
# 中断或个别模块失败后：同一输出目录加 --resume-existing（留存的已通过会话与已变为有效的归档尝试直接复用，只补缺口）。
# 终审预算用尽时只能由任务所有者在终端手动追加（需键入确认；非交互环境拒绝，代理不得代为执行）：
#   python -X utf8 scripts/extend_review_budget.py --task-dir /absolute/run --add-seconds 600 --reason "<原因>"
# 遇到 scripts/ 内部错误不要现场修改脚本；先 --preflight，再把错误码与输出原样回报给用户。
python -X utf8 scripts/core_dossier.py --task-dir /absolute/run
python -X utf8 scripts/comparison_host.py --task-dir /absolute/run
python -X utf8 scripts/prepare_adjudication.py --task-dir /absolute/run --first-review /absolute/new-review/1/review.json --second-review /absolute/new-review/2/review.json --reviewer '<主审>' --output /absolute/run/adjudication.json --draft-selected-candidates --auto-agree
# 主审对照 adjudication-worksheet.json 填写 adjudication.json 后发布并交付到新入口目录：
python -X utf8 scripts/publish_report.py --task-dir /absolute/run --first-review /absolute/new-review/1/review.json --second-review /absolute/new-review/2/review.json --adjudication /absolute/run/adjudication.json --mode auto --output-dir /absolute/new-build --deliver-to /absolute/new-entry --require-complete
# 仅跨进程续作、其他发布入口或用户单独验收时运行；上述统一发布成功后不重复：
python -X utf8 scripts/completion_check.py --task-dir /absolute/run --first-review /absolute/new-review/1/review.json --second-review /absolute/new-review/2/review.json --adjudication /absolute/run/adjudication.json --output-dir /absolute/new-entry
```

Serper、Signa、SerpApi 只有在创建任务时显式启用或已有任务授权时使用，可使用现有免费或付费账户容量，不承诺来源费用为零；不自动购买、充值、升级或启用超额。Lens 物理响应只在同一提供方、同一国家、相同实际请求参数和有效期内复用；不同权利范围仍分别分流和评级，复用记录不增加独立来源数量。

业务完成要求全部必要义务满足、最终范围双审及主审有效；本轮有界调查结束可交付带具体限制的报告，未查清事实与恢复条件保留。文件构建通过不等于交付成功：统一事务按 10E 核实际入口及应交文件，再由完成检查判定。最终答复风险只来自当前适用且已验证的 `report-data.json`。主页面展示本次主情景、九类结果、已查／发现／未完成和来源日期；完整候选及逐要素比较在 `operator-appendix.html`，代码、JSON、内部编号与技术签名在 `technical-audit.html`，不拼入运营正文。

新任务发布示例：见上方命令；构建目录（`--output-dir`）与交付入口（`--deliver-to`）必须是两个新目录，完成检查对交付入口运行。准备与发布使用同一问题收集器，准备仅省去尚未开始的最终审阅；缺字段不计风险，但伪造身份、损坏原件和未处理可执行材料仍需修复。已有任务只有用户明确重评时创建带前版来源的副本，原件按准确哈希搬迁，旧审阅和旧报告保持不变。

修改 Skill 后的离线验证（`scripts/verify_skill.py --mode fast|release`）与真实召回验收见[安装](references/installation.md)与[召回验收](references/recall-acceptance.md)；离线通过不等于真实召回通过。

## Generic 通用占位品牌

`api-first-v3` 对 Amazon 品牌字段（无 byline 时取 `product.brand`；有 byline 时去掉 `Brand:` 前缀或 `Visit the … Store` 包装后）精确 `strip().casefold() == "generic"` 的通用占位，不执行该名称的文字商标发现或详情查询；所有支持国家一致。报告参考品牌名称查询项显示 **无风险（Generic 通用占位，仅名称项）**。真实复合品牌、独立图样／OCR／标识清单中的标识和用户另行提供的自有品牌仍按相应范围处理；未提供的自有品牌保持未评估。此名称项不改变专利、版权、商业外观、图形商标或总体评级。保留原始品牌字段、历史任务和已发布报告，不新增查询或阶段审核。


### 自动执行累计预算

新任务遵循 `references/continuous-progress-stage-d.md` 的 bounded-execution 限制（v2：终审额度随国家数增加，最多 3 次终审启动，模块失败后每槽最多重试 1 次；v1 任务保持原限制）。来源、回退和排队复核不得靠换动作或重启重置额度。达到额度保留证据、逐项待定原因和运营建议，记录 incomplete/停止原因。预算停止不等于业务完成，九类复核和发布门槛继续适用。历史无标记任务及入口外执行不具备该保证。


内部预算停止后，只对确实未执行且没有关联原件的范围保留“未查询／风险待定”和预算原因，可在已有材料完成双审后生成证据模式部分报告。未读原件、未知提交和完整性异常不能用预算豁免。嵌套执行必须通过受控执行器复用任务进程组；全局截止时间不因分批或重启重置。具体规则见上述预算参考文档。

## 对话提供凭据

发布包直接提供 token 留空的 `config.json`，不使用 config.example.json。用户在对话中明确提供本 Skill 的后台鉴权 token 时，在业务鉴权前自动填写本 Skill 的 `config.json.backend_token`，保留 backend_url 和其他字段。不得回显、记录到报告、提交到 Git 或通过命令行参数传递凭据。

用 `scripts/configure_credentials.py` 接收标准输入 JSON（backend_token 字段；第三方凭据放在 api_keys 对象，以 .env 中准确字段名为键），输出只有成功状态、文件名和字段名。通过文件写入工具或 stdin 传递，禁止在 shell 命令文本、临时脚本或参数里嵌入凭据。脚本原子保存且 Unix 权限为 0600，仅更新用户提供的字段。用户明确给出提供方的 API key 时，自动填写本 Skill 的 `.env` 对应字段；提供方不明确时先确认，不猜测。没有 .env 的 Skill 不接收第三方 API key。

缺凭据时一次说明缺少的项目；用户提供后填写并继续原鉴权流程，不绕过门禁。IPR 的 config.local.json 或非空 LAOCHEN_BACKEND_TOKEN 仍按现有优先级生效；如与新提供 token 冲突，说明来源并只在用户明确要求时更新覆盖。API key 的填写不代表启用来源或授权消耗额度。

执行效率新任务入口见 [execution-efficiency.md](references/execution-efficiency.md)：画像录入同时填写 investigation_profile；出现待分流视觉候选时运行 `visual_triage_host.py --task-dir DIR`，它处理全部当前视觉候选并直接登记成功批次。新任务另冻结批量判断宿主与机械账目（`host_triage_revision`，见同文档“批量判断宿主与机械账目”）：模型只给判断，程序按原记录器契约写账；宿主占用独立 analysis 额度，不挤占来源与终审额度。技术专利继续按文本/权利要求分析。画像强度不改变九类范围、覆盖完成、风险评级或未知含义。成功批次不再由主 Agent 重写；失败批次按具体原因修复。鉴权、API Key 配置、来源授权和原预算均沿用当前门禁。
