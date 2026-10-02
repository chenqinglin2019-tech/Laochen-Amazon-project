# 最终报告双审宿主入口

新任务使用 `final-double-review-v1`：可执行查询、已得材料、分流与比较完成后冻结共同输入，只进行一次最终独立双审。进度、日志、路径及不影响判断的计划元数据不触发重审；证据、产品或范围实质变化只重审受影响单元及总体影响。完整规则见[API 直接采信与一次最终双审](api-direct-final-review.md)。

## 新任务的模块并行执行

新任务同时默认 `final_review_execution_revision=module-double-review-v1`。同一最终双审分为两条隔离链，每链包含技术（发明专利、实用新型）、外观（外观专利、未注册外观）和表达（文字／图形商标、版权、商业外观、维权信号）三个模块。六个原文审阅会话完成后，各链只汇总自己的三个结果一次；正常首轮共八个真实原生会话，默认最多四个同时运行。

```bash
python scripts/report_review_host.py --task-dir /absolute/task \
  --output-dir /absolute/new-module-review --max-parallel 4 --timeout 1800
```

`python` 是安装检查确认的解释器（macOS 通常为 `.venv/bin/python`，Windows 为 `.venv\Scripts\python.exe`）。宿主自己运行 readiness 与发布准备，**不必先单独运行 `review_readiness.py`**；准备未通过时它一次列出全部问题并拒绝冻结。审阅完成后先用 `prepare_adjudication.py` 生成主审骨架与冲突工作表，再写主审、发布，见 [workflow-efficiency.md](workflow-efficiency.md)。

模块按明确权利与依赖分包，共享产品事实、全部情景及具体限制保留。已注册公开原文读取实际文件并保留全文；实际图片复制到独立工作区，通过原生 `--image` 送入，包内逐张列真实来源及哈希。扫描 PDF 无文本时只记录真实提取限制，不能编造 OCR；有准确登记的页图才能实际阅读相应权利要求和图样。旧阶段审阅收据、进度文字与重复执行日志不作为本轮另一审阅者意见；API 原始字段中的历史、更新时间和原文保留。

宿主只准备一次 readiness 与发布准备问题集合，生成不可通过 JSON 伪造的 `PreparedReviewContext`。冻结及登记继续检查同一当前语义摘要、已引用原件哈希与冻结文件哈希，复用准备结果；不反复计算工作视图。搬迁清单中的可变任务台账不会被要求保持旧搬迁初值，实际引用的原件必须通过准确搬迁及原哈希校验。事实或原件变化时准备上下文拒绝继续使用。

每个模块必须覆盖自身全部国家／情景／权利的整体范围，制度免查须有实际规则引用。具体候选未知原样保持 pending；`known-findings-risk-v1` 的运营评级另按已知适用具体风险汇总，未知只入进度和限制。每链汇总会话不重写模块行、信号或复用凭据，只形成当前总体、检索范围、限制与覆盖置信度。

整份与模块原文审阅使用同一状态合同：新输出逐行显式填写 `assessment_status: pending|assessed`，不能写 `completed` 或省略。`pending` 必须为 `risk:null` 并解释缺失事实；有依据的当前风险使用 `assessed` 和五级风险。已审信号及绑定任务的范围排除仅在各自既有条件满足时允许空风险，普通未知不能借此标为已审。`scope_applicability.status: applicable|not_applicable|unassessed` 属于制度适用性，不能代替审阅状态；制度不适用须实际证据，不自动变成低风险或任务排除。宿主保留原始输出并严格校验，不将非法状态改写为合法枚举；历史空值兼容规则不作迁移。

输出按 `1/technical`、`1/appearance`、`1/expression`、`1/summary` 及第二链对应目录保存原判断、真实原生日志、包、提示、图片和访问边界审计。最终文件为 `1/review.json`、`2/review.json`。`review_context.execution.module_execution` 保留各模块真实 session 及 summary session；单元原审来源取实际模块，不将 summary 的单一签名冒充全部模块作者。每个模型工作区都禁止读取全部其余工作区、任务目录和宿主输出，第二链不接收第一链当轮结论。

模块调用失败或判断无效时保存日志并报错，不自动重试、不改写等级。各审阅位的旧文件仍可通过原 `--previous-first-review`／`--previous-second-review` 传入；只引用本位未变单元，模块行及其原审来源保持原签名，变化单元和本链总体影响重新审阅。历史无模块标记任务继续以下原整份执行规则，不自动迁移。

任一会话失败、超时或宿主在后续校验处中断后，可先修复确定性的错误，再对**原输出目录**运行 `report_review_host.py --task-dir TASK --output-dir ORIGINAL_REVIEW_DIR --resume-existing`（隔离后端须与原运行相同）。宿主逐会话处理：原生事件日志包含完整、无工具调用的单次回合，且模块包和提示与重算结果逐字相同、原件观察合同有效、法律判断通过实际模块范围及字段校验、已留存判断及审计完整性匹配的会话直接复用，不重新调用；日志缺失、不完整或完整但原件观察缺失／错引用／空内容的会话，其目录改名保留为 `<模块>.attempt-N` 后以同一冻结输入、包和提示开启全新会话（全部改名记录写入 `freeze-receipt.json` 的 `resume_attempts`）；已存在的模块包或提示与重算结果不同则立即拒绝。两条本链汇总因输入含各模块记录，通常需要重跑。不重新调用满足合同的已完成模块会话。完整但原件观察不合格或本轮法律输出合同不合格，只在显式恢复时归档并重跑该模块，不自动重试；已注册来源先完成完整性校验，旧收据或未知校验故障保持硬阻断；文件、图片、原判断或已有审计被改动则拒绝，不能归档后掩盖篡改。显式恢复仍受同一累计预算约束，预算耗尽保留原结果和失败日志，不形成成功收据。旧审计有进程号则保留；中断前未落审计的模块明确标注进程号和退出码未留存，以原日志中的完整回合证明模型输出，不编造原生进程信息。任务图片编号只有登记路径、字节数及哈希全部匹配才可作为**商品侧**比较引用，不能充当第三方权利或状态的证明。

## 运行环境、隔离后端与选项

整份与模块提示共用 `required_product_scopes`，每位独立审阅者须覆盖每个适用情景／国家／权利的无候选 `product` 整体范围。候选、`own_brand`、未来或信号行不能替代；证据不足仍以整体 `pending/null` 行解释，不填低风险。登记、聚合及裁决准备拒绝漏项，模块仅检查本模块权利；裁决不能代填一位审阅者缺少的整体范围。原始输出与账务保留，不自动重跑。无情景定义的旧任务不被静默扩展为新情景，完整登记边界始终要求范围完整；已有原生/模块收据在聚合中同样严格。进度视图保留合法已有行并列出原生收据漏项，历史手工阶段审阅保持原有证据限制及部分交付规则，不将阶段交付标为完整双审。

- `--isolation auto|macos-sandbox|tool-free-process`：macOS 上 `auto` 即 `macos-sandbox`（`sandbox-exec` 内核读边界，永不自动降级）；Windows 与其他系统上 `auto` 即 `tool-free-process`：同一条禁用全部工具／插件／MCP 的 `codex exec` 命令、每会话独立临时工作区、直接以 `codex login status` 检查登录，并由宿主逐条校验事件轨迹只允许 agent_message／reasoning／error。它**没有内核级读边界**：每份审计写明 `isolation_method=tool_free_process`、`kernel_read_boundary=false`，并在 `isolation-policy.json` 记录 codex 二进制哈希与版本、禁用特性、工作区文件清单，且拒绝工作区上级目录存在 `AGENTS.md`。校验器（`validate_execution`）按方法分别核对，恢复不得跨后端。整份历史两审路径仍仅限 macOS。
- Codex 二进制：`--codex-binary`，否则 `LC_IPR_CODEX_BINARY`，否则 macOS 用 ChatGPT 应用内置路径、其他系统用 PATH 上的原生 `codex`／`codex.exe`；`.cmd`／`.bat`／`.ps1` 包装脚本一律拒绝。
- 模型与上下文参数读自 `references/review-host.json`（默认 `gpt-6-astra`、上下文 872000、压缩阈值 800000、推理强度 medium；`tool_free_codex_sandbox` 默认 `read-only`，仅当 Windows 真机冒烟显示该 Codex 版本启动即拒绝 `--sandbox read-only` 时才改为 `danger-full-access`——所有工具仍被禁用，轨迹校验照常生效，且写入策略文件）。
- `--timeout` 为每会话总时限 30..3600 秒（默认 1800）；`--max-parallel` 1..6（默认 4）。提示词、事件日志一律按 UTF-8 读写，与系统区域设置无关。
- 单个会话的提示超过 1,048,576 字符时在模型调用前明确拒绝，不截断材料；该任务须缩小范围后重新冻结，不能手工录入替代。
- 模块宿主每次运行只检查一次 ChatGPT 登录；历史整份路线保留逐工作区登录检查。

## 注册原件与执行观测

两条路线均复用同一个注册原件读取器：仅解析冻结材料中有 HTTP(S) 来源、实际路径与匹配 SHA-256 的原件；不扫描未注册目录、不额外联网。读取器对实际读到的同一份字节再验登记哈希／字节数；正文、PDF、图片及 XLSX 解析均使用这份已验缓冲区，XLSX 不重新打开路径。原件登记扫描与提示使用同一材料投影，先排除 result_task 旧快照及嵌入二进制字段，避免旧快照附件回流。JSON 原件为实际解码字符串或完整 JSON 文本，不以文件名/摘要替代正文；损坏 JSON 或字节不匹配拒绝送审。HTML 提取正文、PDF 提取文本的限制保留，未提供的视图不算已读。图片按 `attachment` 绑定实际字节，两位分别获得相同原件副本。

两条路线在发送前将包、提示、隔离文件、挂载视图及图片副本与内存合同绑定；发送前与原生结束后复核同一字节哈希。观察按已绑定字节解析的包校验，不能用运行后可变包降为 v1；审计引用发送前哈希。发现变化保留原生输出并拒绝收据。该机制不宣称防御同宿主恶意进程在检查间瞬时改写再还原附件。

新的 `public-originals-v2` 材料要求原生输出 `material_observations`：每个 `material_id` 恰有一个对象，包含原样 `source_refs`、具体可见内容 `observation` 和明确读取限制 `limitations`。漏件、错引用、空观察或缺限制均拒绝登记；宿主不代写观察。该结构检查只证明绑定完整，不自动证明观察正确、法律复核充分或供应商授权。历史 v1 已签收据仍按原合同校验；旧模块输出包/提示与新包不同则不能静默恢复，须保留旧结果、评估原件读取缺口后另开运行，并沿用累计预算。

每次原生调用实时保留事件及 stderr，并写 `events.execution.json`：实际进程号、提示哈希/字节数、首事件、turn 开始、首 reasoning/agent_message、turn 完成、最后事件、退出原因及可获得的真实 usage。没有实际事件或 usage 就是 null，reasoning 输出是输出用量的子项。时间是宿主以 100ms 间隔看到 CLI 事件的时间，不是网络 TTFT；5 秒日志刷新不算业务进展。

观测中的 `process_exited` 只表示进程正常退出，`review_validation=not_performed` 始终保留其观测层含义。必须继续通过完整回合、原件观察、评级字段、证据引用、实时摘要及两审独立性门槛，才有 `pair_validated` 收据。失败和超时仍保存已取得的原件包、提示、图片和部分事件；不补造风险结论、不自动重试。`--timeout` 仍被已有累计预算裁短，恢复或换输出目录不能重买时间。

## 历史整份执行规则

无模块标记的历史任务继续使用整份两审执行，规则见 [legacy/report-review-host-whole-input.md](legacy/report-review-host-whole-input.md)；新任务不读。该路径仅 macOS。

完整范围识别以输入摘要已绑定的任务合同为依据：当前连续整份/最终路线及模块要求产品整体范围，不能因收据缺少host_audit/module_execution降为阶段审阅；存在但不是对象的审计字段拒绝。necessary-work-v1/v2历史源范围阶段合同保留旧部分交付，不升级为当前完整双审；修改任务合同版本会改变审阅输入摘要。完整登记仍要求整体范围，进度保留逐行合法的部分工作并持续列漏项，主审不能绕过完整范围门槛。

聚合结果的review.scope_contract区分whole_product与legacy_stage_scopes，并保留两位product_scope_gaps；历史阶段范围不能据此声称当前完整产品清查。此字段是计算结果披露，不是审阅者可提供的降级授权。
