# V8 内置生图交接

仅适用于 workflow_policy=one_pass_v1；历史项目读 [v7-orchestration.md](v7-orchestration.md)。生产前读取系统默认 imagegen Skill；模型接口、参数及结果展示采用宿主实际能力。新路径不使用旧 orchestrate_imagegen.mjs，其 transition/审核回调属于旧流程。

## 波次生成

1. `P scripts/lc_image_studio.py reserve --manifest M --json [--max N]`。
2. 对每个 reservations 条目调用一次宿主内置生图：prompt 原文；references 按顺序附上；transparent_background 按条目传入。reference_roles 区分 product、style、edit_target。模型能力支持透明时请求真实 alpha；不把棋盘格当透明。
3. 等待已发起调用全部落定，保存工具实际返回的绝对路径。按宿主接口展示结果；附图不再查看和评价输出，不调用 OCR 或审核命令。
4. `ingest-batch --manifest M --item <job> <attempt_id> <绝对路径> ... --json`。每张结果一项；部分失败不丢弃其他成功结果。
5. 若返回主图 main_background_pending，查看 raw_path 与实际处理图 path，检查背景分离与端点完整，按 SKILL.md 的 main-background-check 提交返回的 processing_id、attempt_id；历史没有处理 ID 的主图兼容原命令。无需审核包。其他图直接 ready_to_deliver。
6. 再 reserve 派发余下图片。没有样板或 anchor 等待；不在每波之间重复 plan。
7. deliver 返回按项目图位顺序排列的 images 与 missing_jobs；complete=false 时照常交付完成部分，并说明缺失。

默认并发 1；已知宿主容量后，在 init --concurrency N 或 configure 中设置。reserve --max 只能缩小一波，不能越过项目容量。所有生成由宿主工具执行，脚本本身不调用任何模型或 API。

## 失败与恢复

- 确定工具失败：`ingest-batch --failed J A "<错误>"`；429 返回等待，其他失败沿用首发＋2 次预算。
- 没有提交：`ingest-batch --not-started J A` 或 `release --job J --attempt-id A --reason "…"`。
- 提交结果未知：`ingest-batch --unknown J A "<原因>"`。预约保持占槽，禁止重复生成。
- 已返回图片但找不到路径：保持原预约，核对工具真实输出；找到后 ingest，不重新生成。
- 预约超过 30 分钟：保留等待结果。确定已有结果后 `recover-attempt --job J --attempt-id A --reason "已找到真实返回文件"`，再 ingest；不会产生新 attempt 或调用模型。
- 主图背景修复：新主图先自动执行 [保守本地处理](main-background.md)，不占模型修复额度。历史背景阻断使用 prepare-main 复用原图恢复，保留已用次数。有效 alpha 缺失或明显触边会绑定原图为 edit_target；透明分离不正确时 main-background-check verdict repair。下一次 reserve 返回一轮背景专项编辑，仍保持商品结构、材质、标签和包含物。首次生成不计次数，最多三次模型专项修复；每轮基于最新返回图，工具确定失败的瞬时重试仍受独立预算，不重复占用专项修复次数。
- 附图视觉修改只响应用户明确要求：更新该图 approved_copy/design_brief，再 plan；不自动从交付文件推断质量问题。

入库只证明文件、规格与绑定有效，不证明附图内容经过审核。主图背景验证只证明被确认的透明掩膜区域在最终 PNG 中为纯白；透明分离的语义正确性由主图专项查看确认。
