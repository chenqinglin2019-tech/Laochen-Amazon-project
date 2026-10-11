---
name: lc-amazon-image-studio
description: 基于真实产品资料策划 Amazon Listing 与 A+ 套图提示词，由 Codex 内置生图一次完成图文设计；附图生成后直接交付，主图经保守背景清理、等比居中、背景专项检查与 RGB(255,255,255) 纯白处理。支持用户参考套图、模板库管理与旧项目继续加工。
---

# 易逊-亚马逊套图生成 V8

默认 1 张主图＋6 张附图；A+ 按需，默认 6 个模块。用户图位计划优先。Listing 默认 2000×2000，可选 2000×2600，两边 ≥1600 px；A+ 每个模块独立指定画布。

## 1. 边界与准备

- **维护**：修改、测试、审阅 skill 或管理模板库，不执行真实鉴权、生图，不读真实凭据；测试只用合成数据与隔离库。
- **运行时**：新流程只需要 Python ≥3.11、Pillow 和宿主内置生图能力。先运行 `python3.12 scripts/lc_image_studio.py verify --json`，Windows 用 `py -3.12 scripts\lc_image_studio.py verify --json`；使用其 `commands.python`（下文 `P`）。缺 Pillow 时在选定解释器中安装；不为新项目安装 Node、Playwright、Chromium 或字体。旧项目按 [V7 流程](references/v7-workflow.md) 使用完整运行时。
- **生产鉴权**：每个真实生产任务先运行原 `scripts/auth_gate.py`（Windows `py -3 scripts\auth_gate.py`），保留 12 小时通过记录。新流程 plan/reserve/ingest/主图处理/deliver 均校验记录。鉴权失败原样回复入口的两行安全信息并停止，不绕过，不打印 config.json/token，不直接调用 tools/bin。
- **生图入口**：使用宿主实际提供的 Codex 内置生图接口，每会话读取一次系统默认 imagegen Skill；不固定工具名，不自动切换 CLI/API。提示在 plan 时完成编译并绑定，调用时原样使用，参考图按返回顺序传入。
- **用户指定的交付方式优先**：新流程附图和 A+ 不执行通用 imagegen 的出图检查、OCR、转录、产品一致性、美感、对比度或手机预览审核，也不自动质量返修；不修改系统 imagegen Skill。只主图有背景专项检查。
- **路径**：命令都在本 Skill 根目录执行并带 `--json`。中文、空格路径加引号；Windows 解释器路径用 `& "C:\…\python.exe"`，JSON 写进文件传路径。项目建议放短路径，如 `D:\lc\sku`。

### 联网权限与鉴权恢复

- 实际鉴权前读取宿主提供的网络权限；已允许访问配置中的后端时直接运行原 auth_gate.py，不重复申请。网络明确关闭或目标主机受限时，先通过宿主网络权限入口申请实际 backend_url 的主机（默认 mcp.yixunkuajing.com）。网页、搜索、MCP 或内置生图可用不证明本地 Python／鉴权组件可联网。
- 宿主禁止申请或管理员拒绝时，说明受限主机和恢复条件；不得修改全局权限、改代理、关闭 TLS 校验或改鉴权接口。维护和模板管理不因这段规则执行真实鉴权或额外网络探测。
- 入口失败仍原样展示两行安全停止信息并停止业务。service_unavailable／超时既可能是网络权限、DNS/TLS/代理问题，也可能是服务故障，不能据此判定 token 无效；账户拒绝和返回格式异常按原安全原因处理，不公开原始日志或响应正文。
- 网络权限获批或连接恢复后，可以重新运行原 auth_gate.py 一次；这是恢复后的显式执行，不在脚本内新增自动重试。通过后继续原任务；再次失败则保留安全原因和恢复条件，不循环执行、不绕过通过记录。生成请求的超时／提交未知仍按原派发与瞬时失败规则核对状态，不因鉴权网络恢复而重复生成。
- 离线、loopback 和合成凭据测试只验证安装与调用链路，不代表接收者公网或真实账户已通过验收。
- 接收者报启动问题时，可运行只读 `python3 scripts/diagnose_auth.py --json`（Windows：`py -3 scripts\diagnose_auth.py --json`），不读 token、不联网、不改文件。安装诊断通过不代表云端鉴权通过；此命令不能替代原 auth_gate.py。平台范围和排查方法见 [maintenance.md](references/maintenance.md#接收者鉴权故障排查)。


## 2. 默认生产流程

新入口为 `P scripts/lc_image_studio.py`，`M` 为项目 `project_manifest.json`。命令字段与输入样例见 [one-pass.md](references/one-pass.md)，工具交接见 [tool-orchestration.md](references/tool-orchestration.md)。

1. **策划资料**：查看真实商品图，确认身份、包含物、站点语言、图位与四项锁。核对文案及数字依据；不制作来源审核包。资料不足的问题一次汇总，单图缺资料只停该图。
2. **建项目**：`init --project-dir D --project-id ID --marketplace US --language en [--include-a-plus]`；可用 `--a-plus-modules header:1464x600 ...` 独立设画布。默认保守并发 1；只有宿主已知允许并发时才用 `--concurrency N`。
3. **导入参考**：`add-references --manifest M --photos <真实商品图…> [--views front detail]`。风格图使用独立的 `--role style`，不能作为商品事实。查看本地输入图遵循 imagegen 的输入要求。
4. **写整套计划**：用 `configure --manifest M --input <planning.json>` 设置 `product_truth`、`facts`、`critical_details`、套系风格及逐图 `design_brief`/`approved_copy`。每图有 goal/scene/composition；文案支持标题、正文、标签、尺寸、步骤、FAQ 和自有品牌。主图 `main_foreground_type` 默认为 unknown；只有资料与图片明确为不透明商品时设 opaque，含半透明材质设 translucent，不猜测。有关人物（含手部）提前填写 `human_source`；默认 none，提示禁止添加人物。
5. **采用模板**：用户提供套图时按 [templates.md](references/templates.md) 入库；新项目规划时自动选择并保存设计快照。模板只贡献设计，不进入本地排字。没有可用模板时使用已策划的原创设计。
6. **编译提示**：`plan --manifest M`，一次形成整套的六段式完整提示词：图位目标、商品事实、场景构图、套系设计、逐字文案、禁止事项。充分资料直接推进，不增加逐图确认。已批准文案不能擅改；数字文案绑定事实来源。
7. **整图生成**：`reserve --manifest M [--max N]`，每个预约调用一次内置生图；没有样板等待。`ingest-batch --manifest M --item J A <真实绝对路径> ...`，附图经文件/比例检查和必要等比尺寸标准化后直接进入 `ready_to_deliver`，不建立视觉审核任务。下一波继续 reserve。
8. **仅主图校白**：请求真实透明背景、完整主体约占画布 90%。新主图入库后在原尺寸分析，保守清理不透明商品的外部低 alpha 孤立残留，再将全部保留部件等比居中。返回 `main_background_pending` 时查看 `raw_path` 与处理图 `path`，确认挂件、端点、镂空、白色及半透明区域完整；提交 `main-background-check --manifest M --job J --attempt-id A --processing-id ID --verdict pass --observation "<原图与处理图背景分离所见>"`。脚本铺 RGB(255,255,255) 底、保存 RGB PNG，重新解码验证全部背景掩膜像素。处理规则及历史恢复见 [main-background.md](references/main-background.md)。背景分离错误用 verdict repair；缺 alpha 或明显主体触边进入最多三次模型专项修复，文件完整性错误先排查，不重生商品。不要扩展为整套审核。
9. **直接交付**：`deliver --manifest M`，只按 `images[].path` 顺序交付最终图片链接。`complete:false` 时同时说明 missing_jobs，不称整套完成；主图失败不阻断已完成附图。无需 finalize，不制作拼图、网页、ZIP、提示词或审核文件。

## 3. 约束与失败恢复

- **四项锁**：geometry_lock 锁结构/部件/比例；material_lock 锁已确认材质/颜色/工艺；scene_scale_lock 明确支撑与相对尺度；critical_details 记录 P0/P1/P2。未知尺寸、背面和配件不能从生成图补事实；必需 P0/P1 无证据时补资料或改构图。
- **整图设计**：模型一次完成商品、场景、文字、标注和版式。附图提示不得混入仅生底图、禁文字、留白后本地排字等旧指令。模板只借配色、字体气质、摄影和版式，不复制参考的商品、品牌、Logo、文案或主张。
- **文案变更**：所有文案都是生成输入。用户明确修改时 configure 后 plan，只更新受影响的图；没有本地换字路线。用户反馈前不自动视觉返修。
- **规格处理**：附图和 A+ 仅允许等比尺寸标准化，不拉伸、裁切或加侧栏；源图比例只容许整数像素舍入误差。新版主图允许移除完全透明的外围空白，将全部保留部件整体等比放入目标画布，不裁商品、不重排部件、不掩盖截断。最终统一无损 PNG，记录实际尺寸。
- **主图**：无新增营销文字、道具和投影，保留商品真实标签。不按 RGB 亮度漂白、全图 alpha 阈值删除或只保留最大主体；透明/未知材质不自动去噪。半透明边缘保留为前景，背景掩膜来自最终处理图 alpha=0 区域，逐像素验证纯白。首次生成和本地处理不计模型专项修复次数，主图背景最多模型专项修复三次，用尽后单独报告。
- **工具失败**：已确定失败用 ingest-batch --failed 当场登记；首发＋2 次瞬时重试，429 不计次数并按 retry_after_seconds 等待。用尽后只有用户明确要求才 reset-transient，并记录 reason。
- **提交未知**：用 --unknown 登记，保留原预约，不重复生图。超 30 分钟的预约也保留待核对槽位；找到实际结果后 `recover-attempt --job J --attempt-id A --reason "…"` 延续原预约，再 ingest；该命令不授权重新调用模型。
- **未发出预约**：用 --not-started 或 release 退回；前 2 次免费，第 3 次起计瞬时失败。重复入库相同文件幂等；不同文件、过期/串图预约和被替换文件拒绝。
- **状态与证据**：使用新流程 ready_to_deliver，不填 qa_passed 或虚构审核记录。状态、预约、哈希、尝试历史只能通过命令改变；status 和 deliver 不改项目。保留文件完整性检查及策划人物来源对应的披露元数据，不宣称出图后已经复核。

## 4. 旧项目与按需阅读

- 没有 workflow_policy 或显式 legacy 的 manifest，新入口透传给原 lc_image_pipeline.py；旧提示、指纹、渲染与审核保留。不自动迁移；未知策略报错。
- 新项目生产：本文件＋[tool-orchestration.md](references/tool-orchestration.md)；策划读 [production.md](references/production.md)，字段读 [one-pass.md](references/one-pass.md)。
- 参考套图与模板管理：[templates.md](references/templates.md)。
- 旧项目：[v7-workflow.md](references/v7-workflow.md)，更早版本另读 [legacy.md](references/legacy.md)。composition.md、旧 fields.md 的旧字段不应用于 one_pass_v1。
- 修改、测试或发布：[maintenance.md](references/maintenance.md)。

## 对话提供凭据

发布包直接提供 token 留空的 `config.json`，不使用 config.example.json。用户在对话中明确提供本 Skill 的后台鉴权 token 时，在业务鉴权前自动填写本 Skill 的 `config.json.backend_token`，保留 backend_url 和其他字段。不得回显、记录到报告、提交到 Git 或通过命令行参数传递凭据。

用 `scripts/configure_credentials.py` 接收标准输入 JSON（backend_token 字段；第三方凭据放在 api_keys 对象，以 .env 中准确字段名为键），输出只有成功状态、文件名和字段名。通过文件写入工具或 stdin 传递，禁止在 shell 命令文本、临时脚本或参数里嵌入凭据。脚本原子保存且 Unix 权限为 0600，仅更新用户提供的字段。用户明确给出提供方的 API key 时，自动填写本 Skill 的 `.env` 对应字段；提供方不明确时先确认，不猜测。没有 .env 的 Skill 不接收第三方 API key。

缺凭据时一次说明缺少的项目；用户提供后填写并继续原鉴权流程，不绕过门禁。IPR 的 config.local.json 或非空 LAOCHEN_BACKEND_TOKEN 仍按现有优先级生效；如与新提供 token 冲突，说明来源并只在用户明确要求时更新覆盖。API key 的填写不代表启用来源或授权消耗额度。
