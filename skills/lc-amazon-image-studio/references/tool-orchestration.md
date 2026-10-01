# 内置 image_gen 薄适配（V7）

适配器 `scripts/orchestrate_imagegen.mjs` 只把已绑定的提示交给内置 `image_gen`，不是另一个调度器、模型后端、鉴权或审核机构。生产前提（鉴权、`verify`）见 SKILL.md。维护测试只用合成回调：`node --test scripts/test_orchestrate_imagegen.mjs`。

## 调用

在可用工具的 JavaScript 单元里，先用本地命令读取适配器源码，保存为 `lcImagegenAdapter`。读取时使用选定 Python 的 argv（`P -X utf8 -c <读文件>`），Windows 用 PowerShell 引号规则。然后执行：

```javascript
const adapter = new Function(load("lcImagegenAdapter").replace(/^export /gm, "") +
  "\nreturn {runImagegenQueue, safeImageSummary};")();
const result = await adapter.runImagegenQueue({
  initialPlan: planResult,                          // 本轮唯一一次 plan 的结果（或一次 status 结果）
  command: pipeline,                                // 执行 lc_image_pipeline.py <args> --manifest M --json，解析单个 JSON
  readInput: readBoundInput,                        // 返回 {prompt, referenced_image_paths}
  imagegen: args => tools.image_gen__imagegen(args),// 实际内置工具，不用 CLI/API 替代
  selectArtifact: actualArtifactPath,               // 从工具返回元数据取真实绝对路径
  showImage: r => generatedImage(r),
  onReviewReady: item => notify(item), onProgress: p => notify(p),
  onFailure: recordFailure
});
text(result); // 只含路径/状态，不含 Base64 或原始工具对象
```

## 回调约定

- `pipeline(args)`：使用 `verify` 返回的 Python（`LC_LAYOUT_*` 已从 selection.json 自动补齐），追加 `--manifest` 和 `--json`，按 UTF-8 解码，等待命令结束。命令退出码非零或 `ok:false` 视为失败。
- `readBoundInput(entry)`：
  - 原样读取 `entry.prompt_file`，读到截断内容时拒绝。
  - 把 `entry.generation_reference_paths` 按项目目录解析，按顺序给出：商品参考在前，风格底板（`design/plates/…`）在最后。
  - 新图没有附件时省略 paths 字段。不得增强文字，不得在 transition 之后再拼参考。
- `actualArtifactPath`：
  - 返回工具实际写出的绝对路径（接受 Windows 盘符/UNC 路径），不猜目标位置，不序列化图片。
  - 路径缺失或有歧义属于可恢复的交接失败：保留该图和 attempt，找到真实路径后手动 `ingest`，**不再生图**。
- 原生图片用 `generatedImage`/`image` 展示；需要文字诊断时用 `safeImageSummary`；禁止对原始工具结果 `JSON.stringify`。
- 单元内的 promise 必须等全部已发起的模型调用落定后才能结束，包括出错路径；不 fire-and-forget，不起系统后台进程。

## 适配器做什么

1. 对 plan/status 的 `dispatch` 列表中 `image_gen`/`compose` 项，按 `scheduler.effective_concurrency` 放行：
   - 跳过 `next_actions` 里标为 diagnose 的图。
   - 同一 job+prompt 绑定在一次调用里最多尝试一次。
2. 先 `readInput`，再 `transition --status generating`。**只有返回 `status == "generating"` 且没有 `dispatch_refused` 时才调用 image_gen。**
   - 预算用尽或被拒时，命令退出码 2、`ok:false`，状态会持久化为 blocked/failed，不花模型调用。
   - `prompt_hash` 与预读不一致时，要求重新 plan 该图。
3. 调用开始后用 `attempt-event --event tool_started` 记录真实开始时间，结果返回时立刻 `ingest --tool-returned-at <epoch>`。`--tool-returned-at` 可选，缺少开始事件时只把计时标为不可用，图照常入库。
4. 每完成一张，只做一次只读 `status` 来补槽位，不等同批最慢的图或审核。agent 自己不要再逐图调用 `status`。
5. 返回的 `review_ready` 表示“需要真实审核”，不代表整套完成；`retry_after_seconds` 和 `next_actions` 照原样执行。

锚点图入库后：看 raw，然后 `anchor-approve --job J --notes "..."`（或 `--verdicts` 覆盖 geometry/material/components/clarity），再从 `status` 续跑放行兄弟图。适配器不代写注释、转录或结论。

## 没有 JS 工具单元时（手动顺序）

1. `plan --manifest M --json`，得到 `dispatch`（每项含 prompt_file、generation_reference_paths、prompt_hash）。
2. `transition --manifest M --job J --status generating --reason "dispatch" --json`：返回 `status` 不是 `generating`（退出码 2）时停止这张图。
3. 调用 `image_gen`：提示为 prompt_file 原文，附件按 generation_reference_paths 顺序。
4. 返回后立即 `ingest --manifest M --job J --artifact <绝对路径> --attempt-id <A> --tool-returned-at <epoch> --json`。
5. `status --manifest M --json` 取下一批 dispatch，重复 2–5；锚点入库后先 `anchor-approve`。

失败时照 `retry_after_seconds` 等待后从 `status` 续跑。不得手改状态或 attempt 哈希；诊断规则见 [maintenance.md](maintenance.md#状态诊断与计时契约)。
