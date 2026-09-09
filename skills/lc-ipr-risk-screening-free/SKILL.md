---
name: lc-ipr-risk-screening-free
description: 使用免费或免费额度数据源，对单个 Amazon 商品在美国、英国、法国、德国、意大利、西班牙和日本的专利、外观、商标及版权风险进行证据排查，分国家输出五级风险预判、三级置信度、推论依据、核查事项和离线报告。
---

# 免费知识产权风险排查

新任务默认 `retrieval_workflow_revision=api-first-v1`：产品与素材分析后，先用已选择且具备有效使用依据的 API 发现，再由 Agent 轻量分流，按需补证并用官方 API／CDP 核验准确记录。浏览器关键词补搜须有 API 执行及审阅依据，使用有限样本。实施和执行前读取 [API 优先检索契约](references/api-first.md)。云端鉴权遵循用户确认的原包冻结基准；风险定级、发布和报告生成逻辑保持现有规则；API 发现不自动满足官方覆盖或效力核验。无此标记历史任务沿用下文原规划。

新任务使用 `2.4-free` / `automation-first-v1`、`assessment_policy=evidence-estimate-v1`，并启用 `screening_revision=recall-integrity-v1` 与 `decision_workflow_revision=scenario-triage-v1`。先固定情景，再全量轻量分流，仅对入选候选深入核验。有依据的主情景风险预判、置信度和业务完成度独立显示；无依据保持待评，不默认判低或判中。历史任务保留原修订与产物，重新排查创建新目录。先执行 [INSTRUCTIONS.md](INSTRUCTIONS.md) 的业务云端鉴权；该鉴权检查 Token 和本 Skill 使用权限，不扣业务积分。开发、审计、离线测试或恢复 Skill 文件不是执行商品排查。

新建任务同时启用 `recall_planning_revision=identity-discovery-v1`：保留产品身份线索、逐项承接已采分析、允许有证据的召回不足补搜。历史无此字段者保持原规划；不要通过给旧任务补版本字段改变已执行语义。

新任务同时启用 `workflow_correction_revision=workflow-correction-v1`。执行前读取[流程纠错与必要工作契约](references/workflow-correction.md)：统一证据上下文、按作用域重开判断、范围审阅义务、可恢复尝试、按需原文读取及统一待办。缺少此标记者保留历史语义，不原地补标记；它不是新的平行工作流。

新任务另默认启用 `completion_policy_revision=necessary-work-v1`：以 `next_work` 为唯一待办入口，完成仍可执行的必要工作，再进行同一冻结输入的独立范围双审。发布区分 `final` 与有具体阻碍的 `stage`，均须通过[必要工作发布门禁](references/workflow-correction.md#必要工作发布门禁necessary-work-v1)；停止说明不能替代实际执行或审阅。

新任务另启用 `specialty_workflow_revision=asset-scope-v1`，按[专项规则](references/trademark-copyright.md)固定素材用途并执行 Agent 调查待办。仅竞品链接默认另做摄影/文案，不生成竞品素材许可义务；产品本体表达仍审查。新生成报告默认 `visual_policy_revision=core-risk-evidence-v2`，沿用[核心选图规则](references/evidence-schema.md#核心视觉证据core-risk-evidence-v1)，并按[新版图证定位契约](references/workflow-correction.md#核心图证与报告)验证真实 PDF 页数及父子身份。

## 必守边界

- 来源支出上限始终为 `0 USD`，不购买积分、订阅、付费文件，不触发超额或自动充值。Serper、Signa、SerpApi 仍需创建任务时显式选择；已有来源授权可直接沿用。
- Agent 负责产品拆解、当地语言查询、分类、翻页、取证、候选挑选、比较、独立复核和报告。每条文本查询必须与目标国家所需语言及原文字形一致；例如 US/GB/EU 为英文，中文或日文不得标注为 `en` 后执行。语言/文字不一致时须追加有来源的目标语言词或保留语言缺口，不能把零结果作为排除证据。自动检索阶段人工仅处理登录、验证码、扫码、MFA、访问同意；不能要求人工输入业务查询、找案号、翻页、抄结果或截图。报告可以列具体专业复核及用户独有资料核查，但不得以此替代当前预判或 Agent 应完成的检索比较。
- 禁止自动查询的网页不使用“人工点击后采集”替代。EPO 网页、WIPO 查询系统及不兼容本场景的 J-PlatPat / EUIPO 网页路线保留缺口，使用允许的 API 或其他合格来源。
- 新 API 优先任务的 Serper 默认须通过官方账户页免费权益证明及额度预留后才执行；用户明确授权使用现有余额时，可按契约记录该授权并跳过余额登录检查，不声称免费余额已核实。缺少两种使用依据之一时保留阻碍并推进可用替代。历史 2.4 无新标记者保持计量前停止。文字 Images 不等于反向图片检索；可用的 Lens 承担后者。
- EPO OPS、EUIPO Production、JPO API 是可选能力；缺少账号或审批不阻止启动和其他模块。来源详情与实际验收状态见 [providers.md](references/providers.md) 和 [official-sources.md](references/official-sources.md)。不要把已写适配器、页面可打开或模拟测试等同于线上跑通。
- 产品身份、登记记录核验、侵权要件比较是三层证据。搜索摘要、同族信息、聚合状态和官方登记记录各有用途，不能相互替代。
- 已读补充原文按完整公开号、国家、权利类型和留存文件身份绑定候选；EV 编号不同不应丢失比较，同族或部分号码不能替代精确绑定。原文比较不证明当前效力，也不补齐检索覆盖。
- 最终风险仅为 `极高／高／中／低／极低`，置信度为 `高／中／低`；事实状态仍可未知。待评是执行状态而非第六级：无有效相关检索、也无具体排除依据时不生成最终低风险。已取得的具体风险不因其他模块缺口被清空；缺口本身不自动判中。
- 总评取同一主情景中主审确认的最高适用当前风险；不同销售情景分别汇总，不平均、不重复计算同申请文献或转载来源。置信度取决于驱动证据链；只有局部排除不能外推整体低风险。未来申请及维权记录单列。
- 新规则不静默迁移历史任务。`2.3-free` 保持其原执行与报告分支；`2.1/2.2` 只读历史证据。不得改旧任务的版本号或重写已执行计划行。

## 执行流程

1. 读取 [workflow-business-logic.md](references/workflow-business-logic.md)，记录产品身份、目标国家和销售情景。仅给竞品链接时默认“采用参考物可见结构与用途”的同结构选品假设，不假定实际实施或复制品牌素材；品牌沿用条件情景另列，正品转售仅显式启用。EU 层仅补充适用的欧盟权利，GB 单独处理。
2. 创建任务，运行凭据预检并再次执行原包鉴权。后台 Token 优先非空 `LAOCHEN_BACKEND_TOKEN`，否则读取 `config.json` 与 `config.local.json` 合并配置；第三方凭据仍只从本 Skill 的 `.env` 读取。非秘密运行规则统一存于 `references/runtime-config.json`。按实际可用免费能力推进，缺失来源记录具体缺口；配置规则见 [INSTRUCTIONS.md](INSTRUCTIONS.md#2-本地配置与凭据)，首次安装和跨平台诊断见 [installation.md](references/installation.md)。
3. 按 [browser-product-capture.md](references/browser-product-capture.md) 由 Agent 采集当前 ASIN/变体、产品多视图和文字资料。产品资料不足时可以询问用户缺失的自身产品事实或授权资料；不能把检索工作交给用户。
4. Agent 拆解结构、功能、标识、外观和素材清单，写入 `product.structure`、`product.assets`、带来源和语言的 `query_terms`，确认与本次产品身份绑定的 `product.analysis`。原始采集不能以缺失字段抹掉已确认分析。严格任务不从整段标题、营销 bullet 或类目面包屑自动生成召回；按用途与可见形状提供短词组、同义词组合、适用分类及主体线索。USPTO 关键词组合、短语、号码直查分别编译，不能一律给完整文本加引号。生成前检查分析、语言及路由契约，再执行两类计划；单源故障继续其他来源。
5. 官网、包装或原始文献已给出准确案号时，按 [可信案号入库契约](references/evidence-schema.md#可信外部案号入库) 用 `record_candidate_lead.py` 接入待审候选。对全部去重候选做轻量分流，在 `annotate_materiality.py` 台账记录入选、未入选或待补充及实际依据。未入选不是法律排除；待补充只取下一步必要资料，入选者才进入深入核验和主体／分类扩展。自动同名、来源分数及已核验状态都不是入选决定。完整规则见业务流程；同族关系或 EP 原文不证明目标国现行效力。
6. 运行 `generate_search_plan.py --expand`，追加权利人、分类和已取得响应的下一页；重新执行两类计划、合并、审阅。商品出现专利声明时优先追踪官网、包装案号、设计人和申请人，记录有证据的 `product.patent_claim_followup`，品牌不自动视为权利人。已有计划行不可修改；每查询最多 8 页，限制、失败或未支持的分页均保留截断。第二轮新增动作必须有执行记录；零结果后调整表达或维度，不继续轮换营销长句。
7. 新策略按 [risk-estimate-rules.md](references/risk-estimate-rules.md) 比较、定级并说明正反证据、推论、置信度及升降级条件；无策略字段的历史任务才使用 [risk-rules.md](references/risk-rules.md)。专利逐权利要求要素；外观核对实际必要视图；商标核对标识、商品服务与使用。运行 `record_asset_provenance.py --list-work`，完成图形标样比较、适用版权及商业外观公开调查，再通过同一记录器留存分步骤证据；API/浏览器均不执行这些 Agent 待办，不能跳过。调查完成与权属事实未知分别记录，登记库零结果不排除版权。
8. API/浏览器批次结束后读取 `next_work.py`，处理 `agent_investigation`、`agent_read`、`plan_repair`，登记证据、合并分流并重算待办。完成可执行工作后，冻结同一 evidence/candidates/materiality/plan、产品及情景 digest。独立 Agent 不看第一轮结论进行第二轮审阅，保存实际审阅会话标识；逐一检查必要情景、国家和权利范围，不要求未入选候选逐件五级评级。主审只能协调同情景分歧，有依据才选级；不投票、不平均、不默认取高。
9. 新修订用 `publish_report.py --mode final` 在新输出目录完成定稿、五项报告及独立验收；只有可执行 Agent 工作已处理、两轮范围均已审且剩余工作有具体阻碍时，才用 `--mode stage --stop-reason '具体停止原因'` 形成阶段报告。独立 `finalize_assessment/build_report/validate_run` 入口继续支持同一门禁。并列风险预判、置信度和工作完成度；关键工作未完成不清空已有风险。必要范围漏审、真实待补充与截断仍保留；缺口不填入反证栏。真实页面验收按 [浏览器契约](references/browser-product-capture.md) 与 [召回验收](references/recall-acceptance.md) 执行。

每轮结束检查仍可执行的 Agent 工作，不因某国某项受阻提前终止整个任务；也不能反复查询已明确禁止、额度耗尽或未经适配的路线。没有合格替代时输出具体国家和权利缺口，而非“七国全部无法执行”。

产品 `structure` 及采集到的形状/OCR 线索须在 `product.analysis.clue_dispositions` 映射到确认术语或给出排除理由，具体格式见 [数据契约](references/evidence-schema.md)。身份发现保留品牌、产品名和制造商线索，不能冒充申请人。首源成功但无相关候选时，按 [来源补搜规则](references/providers.md) 记录判断并执行已授权免费替代；技术成功不关闭召回。部分结果可以保留为真实发现证据，但不能被当作完整检索缓存；达到有限续跑边界后保留截断与未处理工作。

## 命令入口

以下全部由 Agent 执行，路径替换成实际任务目录。

macOS 首次运行直接使用 `scripts/auth_gate.py`：入口在哈希校验通过后，自动设置当前平台鉴权程序的执行权限，并在启动前移除其下载隔离标记；无标记时正常继续。无需另行递归处理 Skill 目录，启动准备失败按 `INSTRUCTIONS.md` 报告。

```bash
python scripts/auth_gate.py
python scripts/create_task.py --url 'https://www.amazon.com/dp/B012345678' --jurisdictions US,GB,FR,DE,IT,ES,JP
# 已选择免费增强时，创建命令追加 --enable-serper-free --enable-signa-free --enable-serpapi-free
python scripts/preflight.py --task /absolute/run/task.json --phase credentials
node tools/cdp/cdp-cli.mjs doctor
node tools/cdp/cdp-cli.mjs capture-amazon --task-dir /absolute/run
python scripts/record_browser_product.py --task-dir /absolute/run --capture /absolute/run/browser-capture.json
python scripts/preflight.py --task /absolute/run/task.json --phase evidence
python scripts/generate_search_plan.py --task-dir /absolute/run
python scripts/run_api_plan.py --task-dir /absolute/run --phase discovery
python scripts/next_work.py --task-dir /absolute/run
python scripts/blacklist_check.py --task-dir /absolute/run
python scripts/merge_candidates.py --task-dir /absolute/run
python scripts/annotate_materiality.py --task-dir /absolute/run --decisions /absolute/triage-decisions.json --reviewer agent-first
python scripts/merge_candidates.py --task-dir /absolute/run
python scripts/generate_search_plan.py --task-dir /absolute/run --expand
# 审阅发现结果并追加必要动作后，读取 next_work，仅执行已获当前分流授权的动作
python scripts/run_api_plan.py --task-dir /absolute/run --phase verification
python scripts/run_browser_plan.py --task-dir /absolute/run --phase verification
# 仅对有已绑定补搜判断的浏览器动作：--phase fallback
# 执行新增动作、专项调查并重新合并审阅后，再冻结审阅输入
python scripts/next_work.py --task-dir /absolute/run --first-review /absolute/run/first-review.json --second-review /absolute/run/second-review.json
python scripts/publish_report.py --task-dir /absolute/run --first-review /absolute/run/first-review.json --second-review /absolute/run/second-review.json --adjudication /absolute/run/adjudication.json --mode final --output-dir /absolute/new-report
```

2.4 历史输入显式重评及补充证据命令见 [evidence-schema.md](references/evidence-schema.md)；必须使用 `--assessment-policy evidence-estimate-v1` 与新 `--output-dir`，不改旧任务版本或既有产物。2.1/2.2/2.3 不通过修改版本号迁移。数据契约与审阅字段见该文件，商标和版权专项见 [trademark-copyright.md](references/trademark-copyright.md)。`report-data.json` 是 HTML、Markdown、CSV 的统一视图模型；五项产物均保留输入摘要、证据哈希和离线可读性。未查清部分不得用文字包装成清白证明。

来源重试的显式 attempt、共享额度与离线网络隔离见 [providers.md](references/providers.md)。修改 Skill 后先用 `scripts/verify_skill.py --mode fast`，交付前用 `--mode release` 执行完整离线验收，均指定新的 `--output-dir`。离线测试和布局通过不等于真实召回通过；召回修复另按 [召回验收](references/recall-acceptance.md) 用产品资料盲测并验证真实原始结果。报告 HTML/CSS 格式受锁保护，增强校验不改变用户模板。
