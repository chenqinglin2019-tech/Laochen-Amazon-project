---
name: lc-amazon-image-studio
description: 基于真实产品资料制作 Amazon Listing 与 A+ 套图。用户可提供自己满意的成品图套系，skill 拆解后生成用户专属模板（参考底板＋版式＋配色＋字体），按产品特性自动选择并近似还原；内置模板可一键停用或清空；本地精确排字、产品一致性审核、增量交付。
---

# 易逊-亚马逊套图生成 V7

默认 1 张主图＋6 张副图；A+ 按需（默认 6 个模块，可逐图设模块与画布）。用户的图位计划优先。Listing 默认 2000×2000（可选 2000×2600），两边 ≥1600 px。

## 1. 边界（先判断再动手）

- **维护**：修改、测试、审阅 skill 或管理模板库（清空/恢复/导入导出），不需要鉴权与生产输入；只用合成配置，不读真实凭据、不访问真实账户。
- **生产**：分析真实产品、生成、编辑、恢复或交付。每个生产任务开始时鉴权一次：
  - macOS/Linux：`python3 scripts/auth_gate.py`
  - Windows：`py -3 scripts\auth_gate.py`（任意 Python ≥3.8，无需 Pillow）
  - 成功后写入 12 小时通过记录，`plan`/`deliver` 会校验它，同一任务内不重复鉴权。失败时原样回复入口输出的两行（“云端鉴权未通过，本轮不继续执行。”＋脱敏原因）并停止。不得打印 config.json 或 token，不直接运行 tools/bin 下的二进制。
- 官方 `imagegen`：每个会话读一次它的 SKILL.md；它的 `references/prompting.md`、`sample-prompts.md` 只在撰写原创 brief 或返修时按需读取。提示由本地编译器生成并绑定指纹，调用 `image_gen` 时原样使用，不再二次增强；默认用内置 `image_gen`，不自动改用 CLI/API。

### 联网权限与鉴权恢复

- 实际鉴权前读取宿主提供的网络权限；已允许访问配置中的后端时直接运行原 auth_gate.py，不重复申请。网络明确关闭或目标主机受限时，先通过宿主网络权限入口申请实际 backend_url 的主机（默认 mcp.yixunkuajing.com）。网页、搜索、MCP 或 image_gen 可用不证明本地 Python／鉴权组件可联网。
- 宿主禁止申请或管理员拒绝时，说明受限主机和恢复条件；不得修改全局权限、改代理、关闭 TLS 校验或改鉴权接口。维护和模板管理不因这段规则执行真实鉴权或额外网络探测。
- 入口失败仍原样展示两行安全停止信息并停止业务。service_unavailable／超时既可能是网络权限、DNS/TLS/代理问题，也可能是服务故障，不能据此判定 token 无效；账户拒绝和返回格式异常按原安全原因处理，不公开原始日志或响应正文。
- 网络权限获批或连接恢复后，可以重新运行原 auth_gate.py 一次；这是恢复后的显式执行，不在脚本内新增自动重试。通过后继续原任务；再次失败则保留安全原因和恢复条件，不循环执行、不绕过通过记录。生成请求的超时／提交未知仍按原派发与瞬时失败规则核对状态，不因鉴权网络恢复而重复生成。
- 离线、loopback 和合成凭据测试只验证安装与调用链路，不代表接收者公网或真实账户已通过验收。

## 2. 生产命令序列

以下命令都在 skill 根目录执行，并带 `--json`。`P` 表示 `verify` 返回的 `commands.python`。

1. **运行时**：`python3 scripts/runtime_bootstrap.py verify --json`，7 天内有缓存，命中时约 0.1 秒。失败时看 `inspect --json` 的缺失项；只有用户明确授权，或当前权限明确为完全访问时，才执行 `install --authorization user-confirmed`（不用 sudo，不改系统 Python）。之后管线会自动读取已选运行时，无需手抄 `LC_LAYOUT_*`。
2. **产品事实**：确认产品身份、真实图片、包含物、站点语言和图位计划，建立四项锁（§3），一次写完整套批准文案。
3. **建项目**：`P scripts/lc_image_pipeline.py init --project-dir D --project-id ID --marketplace US --language en [--include-a-plus --a-plus-modules header:1464x600,feature,...]`。随后填写 manifest 的 `product_profile`（品类与属性，词表见 `lc_template_select.py taxonomy`）。
4. **模板**（详见 [templates.md](references/templates.md)）：
   - 用户给了参考套图：先按 templates.md 入库（`intake prepare` → 看联系表填观察 → `intake submit --manifest D/project_manifest.json`），本轮入库的套系自动优先。
   - 然后 `P scripts/lc_template_select.py recommend --manifest M --apply`；只有用户指定套系时才改 `design_template_set_id`。
5. **来源审阅**：`source-review-prepare --manifest M` → 看 `review/source/sheet.jpg` → 按包内说明填写 → `source-review-submit --manifest M --packet review/source/packet.json`，一次完成绑定。
6. **规划**：`plan --manifest M` 一次列出全部问题和 `next_actions`，按列表集中修完再 plan；输入没变就不重复 plan。查看进度用只读的 `status`。
7. **生成**：按 [tool-orchestration.md](references/tool-orchestration.md) 用适配器派发。锚点图入库后先看 raw，只核对商品身份、结构、材质和清晰度，然后 `anchor-approve --manifest M --job J --notes "..."`，兄弟图随即放行（最终完整审核照常进行）。
8. **审核**：`review-prepare --manifest M --jobs ...`，第一次调用就带 annotations → 默认只看 `review/sheets/<job>.jpg` 这一张总图，需要时再看原尺寸 → 填写 `review/packets/<job>.todo.json` → `review-submit --manifest M --packet <todo>`。
9. **交付**：`deliver --manifest M`（总览过期时会自动刷新），核对 `image_count`，然后回复 `output_dir`。缓存清理由用户另行要求时再执行 `compact`。

## 3. 硬规则（每条只写在这里）

- **四项锁**：
  - Geometry：锁定结构、部件关系和真实比例。
  - Material：锁定已知材质、颜色和工艺。
  - Scene Scale：明确支撑面、相对尺度和接触方式，不编造尺寸。
  - Critical Detail：P0 功能 / P1 识别 / P2 次要。
  - 未知尺寸、基材、背面、配件不能从参考图或生成图补事实。必要的 P0/P1 细节没有依据时，补资料或改构图。
- **路线**：逐图选择 pixel_composite / reference_edit / reference_generate，依据是区域质量、放大倍率和证据。合成需要遮罩；实拍白底图可先 `cutout --reference R`，看叠加图确认后再用。
- **文字路线**（每图设置 text_mode）：
  - `none`：主图和白底图。
  - `local_overlay`：默认路线。尺寸、数值、步骤、FAQ、必要限制、品牌/Logo 都走这条；文案只写在 layout 里。
  - `model_native`：只用于一个非数值标题＋可选短正文，并写明 `model_native_reason`。对比度用 `native-text-measure` 测，不能目测。
- **文案**：不删、不缩、不改写批准文案；放不下时换配方、扩大文字区或重新分配图位，仍放不下就 `needs_input`。
- **可读性**：最终 JPG 字形核心对比度 ≥4.5:1；按宽 360 px 预览时，标题 ≥18 px，正文/标签 ≥12 px。
- **主图**：纯白底（255），无营销文字和道具。
- **模板只借设计**：不抄参考图里的商品、品牌、文案、Logo 或主张。参考底板只用于学习背景、光线、机位和构图。
- AI 图片披露与站点规则见 [production.md](references/production.md#ai-图片规则)。
- 历史记录与哈希不得手改；状态只能通过命令改变。

## 4. 循环上限（到达即停，汇总给用户）

- **瞬时失败**：首发＋最多 2 次重试，限流（429）不计入次数。用尽后必须经用户确认，再执行 `transition --status pending --reset-transient --reason "..."`。
- **质量修复**：每图 1 次。达到上限后是终态，plan 不会自动解封。
- **本地修复**：排版/容量问题每图 3 次，超过即 `needs_input`。
- **同命令同输入连续两次同样的错误**：按 `diagnosis_required` 做针对性检查，不要重复 plan/force/审核。锁 10 分钟后过期；瞬时错误不计次。
- **needs_input**：所有问题一次性汇总后问用户，不逐条来回询问。

## 5. 按场景读取

| 场景 | 读 |
|---|---|
| 每次生产 | 本文件 + [production.md](references/production.md) + [tool-orchestration.md](references/tool-orchestration.md) |
| 用户给参考套图、选模板、管理模板库 | [templates.md](references/templates.md) |
| 报错里出现不认识的字段或枚举 | [fields.md](references/fields.md) |
| `status` 判定为旧项目（V1/V2、外部参考、copy_budget） | [legacy.md](references/legacy.md) |
| 修改 skill、测试、性能、平台细节、替换鉴权二进制 | [maintenance.md](references/maintenance.md) |

## 对话提供凭据

发布包直接提供 token 留空的 `config.json`，不使用 config.example.json。用户在对话中明确提供本 Skill 的后台鉴权 token 时，在业务鉴权前自动填写本 Skill 的 `config.json.backend_token`，保留 backend_url 和其他字段。不得回显、记录到报告、提交到 Git 或通过命令行参数传递凭据。

用 `scripts/configure_credentials.py` 接收标准输入 JSON（backend_token 字段；第三方凭据放在 api_keys 对象，以 .env 中准确字段名为键），输出只有成功状态、文件名和字段名。通过文件写入工具或 stdin 传递，禁止在 shell 命令文本、临时脚本或参数里嵌入凭据。脚本原子保存且 Unix 权限为 0600，仅更新用户提供的字段。用户明确给出提供方的 API key 时，自动填写本 Skill 的 `.env` 对应字段；提供方不明确时先确认，不猜测。没有 .env 的 Skill 不接收第三方 API key。

缺凭据时一次说明缺少的项目；用户提供后填写并继续原鉴权流程，不绕过门禁。IPR 的 config.local.json 或非空 LAOCHEN_BACKEND_TOKEN 仍按现有优先级生效；如与新提供 token 冲突，说明来源并只在用户明确要求时更新覆盖。API key 的填写不代表启用来源或授权消耗额度。
