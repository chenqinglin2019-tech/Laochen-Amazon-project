---
name: lc-amazon-image-studio
description: 基于真实产品资料制作 Amazon Listing 与 A+ 套图（V8.1 一次成图）。Agent 从模板库（内置模板＋用户参考套图拆解的专属模板）选出最合适的模板或自行策划，本地编译提示后由生图模型一次画出产品、场景和文案，直接交付成品文件；参考图只借色调与光线，模特每套新选且整套同一人，绝不照抄参考图里的人和场景；主图保证 255 纯白底。
---

# 易逊-亚马逊套图生成 V8.1

默认 1 张主图＋6 张副图；A+ 按需（模块默认 970×600，可逐个指定，如 `header:1464x600`）。用户的图位计划优先。Listing 默认 2000×2000（可选 2000×2600），两边 ≥1600 px。

## 0. 首次准备（每台电脑一次）

- **鉴权 token**：打开本 Skill 根目录的 `config.json`，在 `"backend_token": ""` 的引号里填入自己的 token；也可以在对话里把 token 交给 Codex 自动填写（见文末“对话提供凭据”）。
- **Python ≥3.11**（生产需要；鉴权本身 Python ≥3.8 即可）：
  - macOS：从 python.org 安装 3.12，装完运行一次 “Install Certificates.command”；或 `brew install python@3.12`。系统自带的 3.9 不够用。
  - Windows 11：`winget install -e --id Python.Python.3.12`（或 python.org 安装包，勾选 Add to PATH），之后一律用 `py -3`。不要用 Microsoft Store 的 `python3` 别名。
- **运行时**：只需要 Pillow 和 NumPy，不需要 Node、浏览器或字体。`verify` 找到合适的 Python 就直接用；缺少时经用户同意后执行 `install --authorization user-confirmed`（私有缓存里建 venv，只装锁定版本的 wheel，不用 sudo、不改系统 Python）。以后 7 天内 `verify` 直接命中缓存。
- **PowerShell 写法**：
  - 解释器路径含空格时写成 `& "C:\…\python.exe" scripts\studio.py …`。
  - 含空格或中文的路径加双引号。
  - 带引号的 JSON 一律写进文件再传路径，不要放在命令行里。
- 项目文件夹放在路径较短的位置，比如 `D:\lc\<sku>`。Windows 未开启长路径时，路径过长会报 `PATH_TOO_LONG`。

## 1. 边界（先判断再动手）

- **维护**：修改、测试、审阅 skill 或管理模板库（清空/恢复/导入导出），不需要鉴权与生产输入；只用合成配置，不读真实凭据、不访问真实账户。
- **生产**：分析真实产品、生成、编辑、恢复或交付。每个生产任务开始时鉴权一次：
  - macOS/Linux：`python3 scripts/auth_gate.py`
  - Windows：`py -3 scripts\auth_gate.py`（任意 Python ≥3.8，无需 Pillow）
  - 成功后写入 12 小时通过记录，`plan`/`deliver` 会校验它，同一任务内不重复鉴权。失败时原样回复入口输出的两行（“云端鉴权未通过，本轮不继续执行。”＋脱敏原因）并停止。不得打印 config.json 或 token，不直接运行 tools/bin 下的二进制。
- **生图协作**：整个生图使用 Codex 内置生图能力，并配合当前环境的系统默认 `imagegen` Skill；从宿主技能列表定位并每个会话读一次它的 SKILL.md，需要自行策划设计（`custom`）或返修时才按需读它的提示参考。提示由本地编译器根据所选模板和 plan.json 生成，生图时原样使用，不再二次增强。
- **执行入口**：遵循系统 `imagegen` Skill 的内置生图流程，具体工具名称、参数和图片展示方式以当前宿主实际提供的接口为准，不将固定工具名或 JavaScript 方法名作为额外安装依赖。接入方式见 [tool-orchestration.md](references/tool-orchestration.md)，不自动改用 CLI/API。

### 联网权限与鉴权恢复

- 实际鉴权前读取宿主提供的网络权限；已允许访问配置中的后端时直接运行原 auth_gate.py，不重复申请。网络明确关闭或目标主机受限时，先通过宿主网络权限入口申请实际 backend_url 的主机（默认 mcp.yixunkuajing.com）。网页、搜索、MCP 或内置生图可用不证明本地 Python／鉴权组件可联网。
- 宿主禁止申请或管理员拒绝时，说明受限主机和恢复条件；不得修改全局权限、改代理、关闭 TLS 校验或改鉴权接口。维护和模板管理不因这段规则执行真实鉴权或额外网络探测。
- 入口失败仍原样展示两行安全停止信息并停止业务。service_unavailable／超时既可能是网络权限、DNS/TLS/代理问题，也可能是服务故障，不能据此判定 token 无效；账户拒绝和返回格式异常按原安全原因处理，不公开原始日志或响应正文。
- 网络权限获批或连接恢复后，可以重新运行原 auth_gate.py 一次；这是恢复后的显式执行，不在脚本内新增自动重试。通过后继续原任务；再次失败则保留安全原因和恢复条件，不循环执行、不绕过通过记录。生成请求的超时／提交未知仍按原派发与瞬时失败规则核对状态，不因鉴权网络恢复而重复生成。
- 离线、loopback 和合成凭据测试只验证安装与调用链路，不代表接收者公网或真实账户已通过验收。
- 接收者报启动问题时，可运行只读 `python3 scripts/diagnose_auth.py --json`（Windows：`py -3 scripts\diagnose_auth.py --json`），不读 token、不联网、不改文件。安装诊断通过不代表云端鉴权通过；此命令不能替代原 auth_gate.py。平台范围和排查方法见 [maintenance.md](references/maintenance.md#接收者鉴权故障排查)。

## 2. 生产流程（V8.1 一次成图）

命令都在 skill 根目录执行，每个命令只输出一行 JSON，出错时退出码为 2。`P` 指 `verify` 返回的 `commands.python`；`D` 指项目文件夹。

1. **运行时**：`python3 scripts/runtime_bootstrap.py verify --json`（Windows：`py -3 scripts\runtime_bootstrap.py verify --json`）。7 天内命中缓存；失败时按 §0 处理。
2. **产品事实**：确认产品、包含物、站点语言和图位计划。只用用户资料里确认过的事实（尺寸、数量、材质、认证）；不知道的不写、不猜。
3. **建项目**：`P scripts/studio.py init --project-dir D --project-id ID --marketplace US --language en --photos <实拍图…> [--refs <参考图…>]`
   - `--photos` 只放用户自己产品的照片；别人的成品图、竞品图、灵感图一律放 `--refs`（以后可用 `add-refs --project D --refs …` 补充）。
   - 可选：`--views front side detail`（按照片顺序）、`--listing-aspect 1:1.3`（2000×2600）、`--a-plus-modules header,feature:1464x600`。
   - 返回图位 `slots`、照片 `photos`（含 id 和视角）、主图候选实拍图 `main_candidate`、参考图联系表 `refs_sheet`，以及模板目录 `catalog`（每个图位的画幅、保留带和文案档位也在里面）。
   - 用户给了想长期复用的参考套图：先按 [templates.md](references/templates.md) 入库（`submit … --project D`），再用 `templates --project D` 重新取目录。
4. **选模板、写 plan.json**（Agent 的核心工作；项目里只写这一个文件）：
   - 整套选一个 family，保持风格一致；`preferred:true` 的用户模板优先。目录带 `contact_sheet` 时看它一次。
   - 每个副图位选与该图信息最匹配的模板；都不合适就写 `"template": "custom"`，自己策划 `design.layout`（必填）、`design.style`、`design.typography`。
   - 每张图只讲一件事：`message`（这张图要说明什么）＋`scene`（场景）＋`copy`（eyebrow / headline / subline / callouts，按 §3 文案规则）。用了用户模板的图位必须自己写 `scene`。
   - **参考图先分析再决定**：看联系表，参考图的色调和光线确实适合这张图的设计时，才在该图位写 `"tone_ref"`（`"template"` 表示所选用户模板，或参考图 id 如 `"ref1"`），模型只能拿到它的色调光线；不合适或没有参考价值就不写，自主设计。
   - **有模特的图**：`people` 写 `"person"` 时必须写 `cast`（英文描述一位新模特：年龄段、发型发色、肤色、体型、穿着风格），要和参考图里的人明显不同。整套自动保持同一个人。
   - 产品照片里有人脸、人物或无关品牌时，在 `hide` 里框出（`{"<照片 id>": [[x, y, w, h]]}`），模型只看到遮挡后的照片。
   - 用不到的图位写 `{"skip": true}`。字段见 [fields.md](references/fields.md#planjson)；示例：
     ```json
     {"version": 1, "family": "<family id>", "people": false,
      "cast": "Woman in her 30s, shoulder-length curly dark-brown hair, warm medium skin, relaxed linen shirt",
      "product": {"name": "Desk organizer", "look": "Rounded blue box with a yellow front band",
                  "scale": "About 30 cm tall", "keep": ["yellow front band"], "facts": ["30 x 20 x 10 cm", "3 compartments"]},
      "slots": {"01_main": {"route": "auto"},
        "02_size_or_components": {"template": "<template id>", "message": "Real size and what is included",
                                  "copy": {"headline": "30 x 20 x 10 cm", "callouts": ["3 compartments"]}},
        "03_primary_use_case": {"template": "<user template id>", "message": "Keeps a home office desk tidy",
                                "scene": "sunlit oak desk by a window", "people": "person", "tone_ref": "template",
                                "copy": {"headline": "A Tidy Desk Every Day"}},
        "07_problem_solution": {"skip": true}}}
     ```
5. **规划**：`P scripts/studio.py plan --project D`（需要鉴权通过记录）。
   - 校验 plan.json 和全部文案规则，所有问题一次列在 `errors` 里（含 JSON 路径），改完再跑一次。
   - 为每张图编译一次成图提示。主图有合格实拍图时当场本地抠图合成（`main.route` 为 `photo`），否则编译主图生成提示。
   - 直接返回第一波预约 `reservations`。
6. **生成**（按波次；宿主接口细节见 [tool-orchestration.md](references/tool-orchestration.md)）：
   - 每个预约调用一次内置生图：`prompt` 原样使用；`references` 按顺序全部附上（产品照片在前，然后是色调光线板，最后是本套模特图），**只附这些，绝不另加用户的参考图或其它图片**；生图工具接受尺寸时传 `size`。宿主允许就整波并行。
   - 有模特的图里，第一张先生成；其余带模特的图会以 `WAITING_FOR_MODEL` 等待，第一张登记后自动排进下一波，并带上它作为长相参考。
   - 每张图返回时按 §4 看一眼，不填表、不额外调用命令。
   - 整波结果一次登记：`P scripts/studio.py ingest-batch --project D --item <job> <attempt_id> <图片绝对路径> […]`
     - 同一命令里可以带：`--redo <job> "<具体问题>"`、`--recast <job> "<问题>"`（换一位新模特）、`--failed <job> <attempt_id> "<错误原文>"`、`--not-started <job> <attempt_id>`、`--people <job> yes|no`。
     - 入库时直接导出成品到 `D/final/`。主图会抠图、强制纯白底、居中到 85%，并在解码后的 JPEG 上逐块校验 255。
     - 返回下一波 `reservations`，有就回到本步开头；返回 `retry_after_seconds` 时等够秒数再 `reserve --project D`。
     - 返回 `main_check` 时，看一次 `final/01_main.jpg`。
   - 波与波之间不调用 `status` 或 `plan`；只有改了 plan.json 才重新 `plan`。
7. **交付**：`P scripts/studio.py deliver --project D`（需要鉴权通过记录）。核对 `image_count`，只把返回的 `files`（最终图片文件）和 `output_dir` 回复给用户；返回 `model_mismatch` 时如实告诉用户哪些图是之前的模特。不做预览图，不打压缩包。

## 3. 硬规则（每条只写在这里）

- **产品真实**：产品照片是唯一的身份依据。提示要求按照片还原形状、比例、颜色、材质、部件、数量和印刷细节，画面里只有一件产品，不增不改。未知尺寸、背面、配件不得编造；必要细节没有照片时，请用户补拍或换构图。
- **一次成图**：副图由生图模型一次画出产品、场景和全部文案，本地不再排字，不再复核审查。提示由 `plan` 编译，原样使用。
- **文案**（`plan` 强制校验，不合格不出图）：
  - 标准档：标题 ≤6 个词或 42 个字符，副标题 ≤12 个词，标注 ≤4 条、每条 ≤4 个词，全图 ≤30 个词。
  - 宽幅档（如 A+ 1464×600）：标题 ≤5 个词，副标题 ≤8 个词，标注 ≤3 条。窄条档只放 ≤4 个词的标题。
  - 中文、日文、韩文按字符计，更严（标准档标题 ≤12 字）。
  - 文案里的数字必须出现在 `product.facts` 里。价格、折扣、best seller、#1、Amazon's Choice 一律禁止；质保、认证、防水、100% 等词只有 facts 写明时才能用。
  - 文案用站点语言；主图没有任何文字。
- **主图**（255,255,255 纯白底）：
  - 有合格实拍图（纯色背景、产品完整不贴边、放大不超过 1.75 倍）时，本地抠图合成：产品像素 100% 真实，不花生图次数。
  - 否则生成：工具为产品挑一个便于干净抠图的纯色背景（通常白色；白色或浅色产品用灰色），生成无阴影、无文字的产品图，再本地抠图、贴到纯白画布、居中到 85%。
  - 不画任何阴影或倒影。最终 JPEG 解码后，产品以外的像素全部是 255；校验不通过时自动改用 q100 或无损 PNG。
  - 玻璃等透明产品在 plan.json 写 `"transparent": true`（放在 `product` 里），并尽量提供实拍图。
- **参考只借色调与光线，绝不照抄**：
  - 参考图（用户模板或 `--refs`）只有在 Agent 判断适合、写了 `tone_ref` 时，才以"强模糊色调光线板"的形式交给模型：人物、物件、道具和场景都看不出来，只剩配色、明暗和光线方向。
  - 用户模板只提供版式、字体、配色和光线感觉；场景由 Agent 为本产品原创。
  - plan.json 里不得出现指向参考的说法（"像参考图一样""same model as the reference"），也不得要求像某位真人或名人。
  - 不抄参考图里的商品、品牌、文案、Logo 或主张；联系表、缩略图和观察记录只给 Agent 看。
- **模特**：每套新选一位模特（`cast`），绝不是产品照片或参考图里的人，也不像任何真人或名人；整套同一个人，换新项目重新选人。产品照片只用于产品本身，里面的人和场景一律忽略，必要时用 `hide` 遮挡。
- **AI 披露**：出现真实感人物（含手部）的图，导出时写入 Amazon 要求的 XMP 关键字。plan 里用 `people` 声明；看图时发现与声明不符，用 `--people <job> yes|no` 改正，不需要重生。详见 [production.md](references/production.md#ai-图片规则)。
- `project.json` 由工具维护，不得手改；状态只能通过命令改变。

## 4. 看图标准与循环上限（到达即停，汇总给用户）

- **看一眼**：每张图返回时只检查明显问题。以下情况用 `--redo <job> "<具体问题>"` 重生 1 次，更正说明会自动加进提示：
  - 文字乱码、拼错、缺字，或多出计划外的文字；
  - 产品明显不对（形状、颜色、部件、数量）；
  - 文字或产品被画面边缘切掉；
  - 主图不是干净的单个产品（工具已自动检查并重生，通常不用手动处理）；
  - 画面发虚、像在模仿模糊的色调板；场景几乎照搬参考图。
  小瑕疵不重生，直接交付。
- **模特不对**：定下模特的那张图里，模特像参考图里的人、像真人名人或与 `cast` 明显不符时，用 `--recast <job> "<问题>"` 换一位新模特（占这张图的重生次数）；之后带模特的图都会跟随新模特，返回里的 `made_with_previous_model` 列出已完成的旧模特图，需要重做时先问用户。其它带模特的图只是姿势、文字等问题时用普通 `--redo`，人不变。
- **重生额度**：副图每张 1 次（Agent 要求和自动裁切检查合计）；主图 2 次（自动检查会换背景并附上更正）。用尽后只有用户同意才能加 `--user-confirmed` 再重生。
- **瞬时失败**：首发＋最多 2 次重试；限流（429）不计入次数，并发自动降为 1，并按返回的秒数等待。用尽后状态为 `failed`，经用户同意再 `reset --project D --job <job> --reason "…" --user-confirmed`。
- **免费退回**：没发出去的预约用 `--not-started` 退回，每图最多免费退回 2 次。
- **超时**：预约 30 分钟没有登记结果会自动收回。
- **needs_input**：所有问题一次性汇总后问用户，不逐条来回询问。

## 5. 按场景读取

| 场景 | 读 |
|---|---|
| 每次生产 | 本文件；规划图位、文案、场景时读 [production.md](references/production.md) |
| 宿主生图接口不清楚、波次细节、报错处理 | [tool-orchestration.md](references/tool-orchestration.md) |
| 用户给参考套图、管理模板库、读模板目录 | [templates.md](references/templates.md) |
| plan.json / project.json 字段、状态、错误码 | [fields.md](references/fields.md) |
| 打开的是 V7 项目（`LEGACY_PROJECT_V7`） | [legacy.md](references/legacy.md) |
| 修改 skill、测试、平台细节、替换鉴权二进制 | [maintenance.md](references/maintenance.md) |

## 对话提供凭据

发布包直接提供 token 留空的 `config.json`，不使用 config.example.json。用户在对话中明确提供本 Skill 的后台鉴权 token 时，在业务鉴权前自动填写本 Skill 的 `config.json.backend_token`，保留 backend_url 和其他字段。不得回显、记录到报告、提交到 Git 或通过命令行参数传递凭据。

用 `scripts/configure_credentials.py` 接收标准输入 JSON（backend_token 字段；第三方凭据放在 api_keys 对象，以 .env 中准确字段名为键），输出只有成功状态、文件名和字段名。通过文件写入工具或 stdin 传递，禁止在 shell 命令文本、临时脚本或参数里嵌入凭据。脚本原子保存且 Unix 权限为 0600，仅更新用户提供的字段。用户明确给出提供方的 API key 时，自动填写本 Skill 的 `.env` 对应字段；提供方不明确时先确认，不猜测。没有 .env 的 Skill 不接收第三方 API key。

缺凭据时一次说明缺少的项目；用户提供后填写并继续原鉴权流程，不绕过门禁。IPR 的 config.local.json 或非空 LAOCHEN_BACKEND_TOKEN 仍按现有优先级生效；如与新提供 token 冲突，说明来源并只在用户明确要求时更新覆盖。API key 的填写不代表启用来源或授权消耗额度。
