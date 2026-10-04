# Codex 内置生图与系统 imagegen Skill 协作（V7）

本 Skill 负责产品约束、提示绑定、队列、审核和交付；实际生成与编辑使用 Codex 内置生图能力，配合当前环境的系统默认 `imagegen` Skill 执行。`imagegen` Skill 是执行指引，不是可直接调用的 JavaScript API；读取它后，使用宿主实际提供的内置生图接口。

适配器 `scripts/orchestrate_imagegen.mjs` 通过调用方提供的 `imagegen` 回调交接已绑定的提示，不绑定具体工具名，也不提供模型后端、鉴权或审核。生产前提（鉴权、`verify`）见 SKILL.md。维护测试只用合成回调。

## 生图入口

- 从当前宿主技能列表定位并读取系统默认 `imagegen` Skill，按其内置生图流程确认可用能力和输入方式；宿主提供工具发现入口时，先发现再判断。
- 不因没有某个固定工具名或 JavaScript 方法名就判定无法生图，也不要求用户单独安装名为 `image_gen` 的工具。具体调用名、参数、参考图传入和结果展示遵循当前宿主接口。
- 若确认当前会话确实未提供 Codex 内置生图能力，在派发前说明实际缺失及宿主给出的恢复条件；不进入 `generating`，不伪造输出，不自动改用 CLI/API。系统 Skill 本身不能补出宿主未提供的能力。
- 管线 `dispatch.action == "image_gen"` 是已有的“需要生成图片”动作枚举，不是工具安装要求；保留该枚举及原状态契约。

## 宿主支持 JavaScript 回调时

按系统 `imagegen` Skill 和当前宿主接口接好 `invokeBuiltinImageGeneration` 回调；这个名字只是调用方的本地函数名，不是要求宿主提供的工具。回调仅调用 Codex 内置生图能力，参数在 `readBoundInput` 阶段准备好；不把它替换为 CLI/API 或第三方生图服务。

在可用工具的 JavaScript 单元里，先用本地命令读取适配器源码，保存为 `lcImagegenAdapter`。读取时使用选定 Python 的 argv（`P -X utf8 -c <读文件>`），Windows 用 PowerShell 引号规则。以下为接入示意，回调需按本节约定实现后使用；若宿主无法在 JS 中调用内置生图，使用下方逐图流程。

```javascript
const adapter = new Function(load("lcImagegenAdapter").replace(/^export /gm, "") +
  "\nreturn {runImagegenQueue, safeImageSummary};")();
const result = await adapter.runImagegenQueue({
  initialPlan: planResult,                          // 本轮唯一一次 plan 的结果（或一次 status 结果）
  command: pipeline,                                // 执行 lc_image_pipeline.py <args> --manifest M --json，解析单个 JSON
  readInput: readBoundInput,                        // 返回含 prompt 的当前内置接口参数
  imagegen: invokeBuiltinImageGeneration,          // 按系统 imagegen Skill 接入当前宿主的内置生图
  selectArtifact: actualArtifactPath,               // 从工具返回元数据取真实绝对路径
  showImage: showNativeImage,                      // 当前宿主支持的原生图片展示方式
  onReviewReady: item => notify(item), onProgress: p => notify(p),
  onFailure: recordFailure
});
text(result); // 只含路径/状态，不含 Base64 或原始工具对象
```

## 回调约定

- `pipeline(args)`：使用 `verify` 返回的 Python（`LC_LAYOUT_*` 已从 selection.json 自动补齐），追加 `--manifest` 和 `--json`，按 UTF-8 解码，等待命令结束。命令退出码非零或 `ok:false` 视为失败。
- `readBoundInput(entry)`：返回含 `prompt` 的当前内置接口真实参数，不修改已绑定内容。
  - 原样读取 `entry.prompt_file`，读到截断内容时拒绝。
  - 把 `entry.generation_reference_paths` 按项目目录解析，按顺序给出：商品参考在前，风格底板（`design/plates/…`）在最后。
  - 按系统 `imagegen` Skill 和宿主要求预先查看本地编辑目标，将参考图作为当前接口支持的输入；不支持路径参数时使用宿主的附件或会话图片方式，不能静默丢掉参考图。
  - 新图没有附件时省略当前接口的参考图参数。不得增强文字，不得在 transition 之后再拼参考。
- `actualArtifactPath`：
  - 返回工具实际写出的绝对路径（接受 Windows 盘符/UNC 路径），不猜目标位置，不序列化图片。
  - 路径缺失或有歧义属于可恢复的交接失败：保留该图和 attempt，找到真实路径后手动 `ingest`，**不再生图**。
- `invokeBuiltinImageGeneration(args)`：调用当前宿主的 Codex 内置生图接口，等待完成并返回真实结果；不再次增强提示或改换参考图。
- `showNativeImage(result)`：按宿主原生图片方式展示（如可用的 `generatedImage`/`image`）；需要文字诊断时用 `safeImageSummary`；禁止对原始工具结果 `JSON.stringify`。
- 单元内的 promise 必须等全部已发起的模型调用落定后才能结束，包括出错路径；不 fire-and-forget，不起系统后台进程。

## 适配器做什么

1. 对 plan/status 的 `dispatch` 列表中 `image_gen`/`compose` 项，按 `scheduler.effective_concurrency` 放行：
   - 跳过 `next_actions` 里标为 diagnose 的图。
   - 同一 job+prompt 绑定在一次调用里最多尝试一次。
2. 先 `readInput`，再 `transition --status generating`。**只有返回 `status == "generating"` 且没有 `dispatch_refused` 时才调用内置生图能力。**
   - 预算用尽或被拒时，命令退出码 2、`ok:false`，状态会持久化为 blocked/failed，不花模型调用。
   - `prompt_hash` 与预读不一致时，要求重新 plan 该图。
3. 调用开始后用 `attempt-event --event tool_started` 记录真实开始时间，结果返回时立刻 `ingest --tool-returned-at <epoch>`。`--tool-returned-at` 可选，缺少开始事件时只把计时标为不可用，图照常入库。
4. 每完成一张，只做一次只读 `status` 来补槽位，不等同批最慢的图或审核。agent 自己不要再逐图调用 `status`。
5. 返回的 `review_ready` 表示“需要真实审核”，不代表整套完成；`retry_after_seconds` 和 `next_actions` 照原样执行。

锚点图入库后：看 raw，然后 `anchor-approve --job J --notes "..."`（或 `--verdicts` 覆盖 geometry/material/components/clarity），再从 `status` 续跑放行兄弟图。适配器不代写注释、转录或结论。

## 宿主不支持 JavaScript 回调时（逐图执行）

1. `plan --manifest M --json`，得到 `dispatch`（每项含 prompt_file、generation_reference_paths、prompt_hash）；先完整读取提示并按系统 `imagegen` Skill 和宿主要求准备、查看参考图，确认内置生图入口可用。
2. `transition --manifest M --job J --status generating --reason "dispatch" --json`：返回 `status` 不是 `generating`（退出码 2）时停止这张图。
3. 按系统默认 `imagegen` Skill 的内置流程生图：提示为 prompt_file 原文，参考图按 generation_reference_paths 顺序；具体工具名和参数以当前宿主为准。
4. 返回后立即 `ingest --manifest M --job J --artifact <绝对路径> --attempt-id <A> --tool-returned-at <epoch> --json`。
5. `status --manifest M --json` 取下一批 dispatch；每张下一图均先按第 1 步准备输入，再重复 2–5，不重复 plan；锚点入库后先 `anchor-approve`。

失败时照 `retry_after_seconds` 等待后从 `status` 续跑。不得手改状态或 attempt 哈希；诊断规则见 [maintenance.md](maintenance.md#状态诊断与计时契约)。
