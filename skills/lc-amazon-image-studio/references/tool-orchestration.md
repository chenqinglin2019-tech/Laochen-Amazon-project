# Codex 内置生图与系统 imagegen Skill 协作（V8.1）

本 Skill 负责产品约束、把模板编译成一次成图提示、队列、主图纯白处理和交付；实际生成使用 Codex 内置生图能力，配合当前环境的系统默认 `imagegen` Skill 执行。`imagegen` Skill 是执行指引，不是可直接调用的 JavaScript API；读取它后，使用宿主实际提供的内置生图接口。生产前提（鉴权、`verify`）见 SKILL.md。

## 生图入口

- 从当前宿主技能列表定位并读取系统默认 `imagegen` Skill，按其内置生图流程确认可用能力和输入方式；宿主提供工具发现入口时，先发现再判断。
- 不因没有某个固定工具名或 JavaScript 方法名就判定无法生图，也不要求用户单独安装名为 `image_gen` 的工具。具体调用名、参数、参考图传入和结果展示遵循当前宿主接口。
- 若确认当前会话确实未提供 Codex 内置生图能力，在派发前说明实际缺失及宿主给出的恢复条件；预约用 `--not-started` 退回，不伪造输出，不自动改用 CLI/API。系统 Skill 本身不能补出宿主未提供的能力。

## 按波次派发

每一波只有一次 CLI 调用做登记，其余都是生图调用本身。

1. **取得预约**：第一波由 `plan` 直接返回，之后每次 `ingest-batch` 都会带回下一波；单独取用 `P scripts/studio.py reserve --project D`。每个预约包含：
   - `job`、`attempt_id`、`kind`（initial / retry / redo）；
   - `prompt`：完整提示正文；
   - `references`：参考图绝对路径，按附件顺序——产品照片（有 `hide` 时是 `design/hidden/…` 遮挡版）在前，然后是色调光线板（`design/tones/…`，仅写了 `tone_ref` 的图位），最后是本套模特图（仅 `cast: same_model` 的预约）；
   - `cast`（带模特的预约才有）：`anchor` 表示这张图定下本套模特，`same_model` 表示附带了模特图作为长相参考；
   - `size`（如 `1536x1024`）和 `aspect`：生图工具接受尺寸参数就传，不接受也没关系，入库时会处理。
   - 另有 `refusals`（逐张说明本波没预约的原因，如 `CAPACITY`、`WAITING_FOR_MODEL`）、`waiting_for_model`（等模特定下来的图）和 `wave.concurrency`（默认 4，限流后为 1）。宿主一次只能生成一张图时，在 `plan` / `reserve` / `ingest-batch` 后加 `--max 1`；定下模特的那张图总是排在最前。
2. **生图**：每个预约调用一次内置生图。
   - 提示用 `prompt` 原文，不改写、不增强、不翻译。
   - 参考图按 `references` 顺序全部传入；接口不收路径时按宿主方式附上，不能丢。
   - **只附 `references` 里列出的图**：不得另加用户的参考图、参考套图原图、联系表或其它图片——模型看到什么就会照抄什么。
   - 宿主允许在同一回合发起多次生图时，整波一起发；只能逐张生图时，按返回顺序连续发，中间不调用任何 CLI。
   - 每张图返回时按 SKILL.md §4 看一眼。
3. **登记**：整波一次 `P scripts/studio.py ingest-batch --project D …`：
   - `--item <job> <attempt_id> <图片绝对路径>`：每张返回的图一个。路径取工具实际写出的文件（Windows 盘符、UNC 均可）。路径缺失或有歧义时先找到真实文件再登记，**不要为此重生**。
   - `--failed <job> <attempt_id> "<错误原文>"`：生图报错当场登记。限流（429）不计入重试次数。
   - `--not-started <job> <attempt_id>`：根本没发出去的预约，免费退回，每图最多 2 次。
   - `--redo <job> "<具体问题>"`：看图发现 §4 的明显问题时重生 1 次，可以和该图的 `--item` 放在同一条命令里。带模特的图普通重生不换人。
   - `--recast <job> "<问题>"`：只用于定下本套模特的那张图，人不对时换一位新模特（占这张图的重生次数）；返回的 `made_with_previous_model` 列出已完成的旧模特图。
   - `--reject <job> "<原因>"`：图不能用、又不再重生时标记为失败（交付时会列在 `missing` 里）。
   - `--people <job> yes|no`：更正 AI 披露（同一像素重新导出，不重生）。对定下模特的那张图写 `no`（画面里其实没人）会清除本套模特，由下一张带模特的图重新定。
   - 条目很多时可写成文件：`--results r.json`，内容 `{"items":[{"job","attempt_id","artifact"|"error"|"not_started":true}],"redo":[{"job","reason"}],"recast":[{"job","reason"}],"reject":[…],"people":[{"job","value"}]}`。
4. **读返回**：
   - `results[]`：每张图的 `status`（done / pending / failed）、成品路径 `final`；`auto_redo` 表示工具自己判定要重生（主图 `MAIN_*`，副图 `FRAME_CONTENT_CUT`），重生预约已在下一波里；`model: "defined"` 表示这张图定下了本套模特，等待中的带模特图会排进下一波；`idempotent: true` 表示同一张图已登记过，没有重复处理；`warnings: ["frame_cut_risk"]` 要在交付时告诉用户。
   - `errors[]`：逐条说明哪个条目没登记成功，其它条目不受影响。
   - `reservations`：下一波，有就回到第 2 步；没有且 `summary` 里没有 pending/generating 就去交付。
   - `retry_after_seconds`：等够秒数再 `reserve`。
   - `main_check`：主图抠图处于临界状态，看一次给出的文件；有问题时见下文“主图返工”。
5. 波与波之间不调用 `status` 或 `plan`。只有改了 plan.json（文案、模板、场景）才重新 `plan`；已完成的图提示变了会被保留并列在 `changed_done`，需要重做时 `plan --regenerate <job>`。

## 主图返工

- 生成路线的主图由工具自动检查和重生（最多 2 次），一般不需要手动处理；确有问题时 `--redo 01_main "<问题>"`。
- 实拍图合成的主图不能 `--redo`（`REDO_NOT_ALLOWED`）：在 plan.json 把 `01_main` 改成 `{"route": "generate"}`（或指定另一张 `"photo"`），再 `plan --regenerate 01_main`。

## 限流、超时与异常

- **限流**：返回 429 或 rate limit 时并发降为 1，按 `retry_after_seconds` 等待；连续成功后自动恢复。
- **超时**：预约 30 分钟没有登记结果会自动收回（计 1 次瞬时失败，`GENERATION_TIMEOUT`）。
- **`STALE_ATTEMPT`**：这个预约已被收回、已登记过或已有更新的结果。不要为它重生；用下一波的新预约。
- **`INGEST_CONFLICT`**：同一个预约登记了不同的图片。核对路径，只登记该预约真正返回的那张。
- **`ARTIFACT_NOT_FOUND`**：路径不存在。找到工具实际写出的文件后再登记。
- **`PLAN_BUSY`**：还有图在生成中时不能重新 `plan`；先登记它们（或 `--not-started` 退回）。
- **`PLAN_OUTDATED`**：升级前规划的图还指向旧的风格底板，重新运行 `plan` 即可（已完成的图保留）。
- **定模特的图失败**：被拒绝或重试用尽时，下一张带模特的图自动接替去定模特，不需要处理。
- 不得手改 `project.json`；状态只能通过命令改变。
