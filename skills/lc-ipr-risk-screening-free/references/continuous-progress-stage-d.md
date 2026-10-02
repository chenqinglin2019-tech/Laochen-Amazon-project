# 08D 逐工作进展、诊断和执行停止

仅新任务启用 `continuous_progress_revision=continuous-progress-stage-d-v1`。使用 `record_progress.py --task-dir DIR --input EVENT.json` 向原 `evidence.json.progress_events` 追加控制记录；它不调用来源、不增加查询／重试额度，也不替代原来源、材料、候选和专项记录器。

可执行工作先记 `kind=begin`、`work_id`、`actor`、`reasoning`，执行原动作后记 `kind=finish`、`begin_id`、实际 `action_taken`。`advance_work.py --execute-sources` 对实际来源提交自动包住这两个事件；Agent 工作须按动作卡显式登记。记录器以该稳定问题／动作的前后原始事实及待办是否关闭判断有效进展。纯等待、提醒和没有就绪来源可派发的只读运行不算轮次；每次实际派发就绪来源时 `advance_work.py` 为每个稳定动作自动记一轮 begin/finish（同一调度的全部 begin、全部 finish 各批量一次落盘，结果与逐条记录相同）；上次调度被中断而遗留的未关闭 begin 由下一次调度先以 `action_taken=interrupted_dispatch_recovered` 关闭。另一动作得到结果不会清零本动作的无进展次数。仍需审阅真实成果的用途和质量，记录器的事实变化不自动批准业务结论。

连续两轮没有有效进展后，先记 `kind=diagnosis`、`action_id`，逐项填写 `checks.command`、`receipt`、`retained_files`、`adapter`、`submission`，审原回执与文件并决定本地续作、提交未知核查或符合原限额的重试。随后 `kind=repair` 须提供可验文件 `evidence_ref={"path":"...","sha256":"..."}`；同一修复依据不得重复登记。修复后的同项轮次仍无进展，记 `kind=technical_stop` 与具体 `recovery_condition`；此时再登记新的 `repair` 会被 `PROGRESS_TECHNICAL_STOP_REQUIRED_AFTER_FAILED_REPAIR` 拒绝，不能用反复修复重开同一循环。停止仅封锁对应动作，保留未完成状态、原运行回执、历史次数、未知名额和独立待办，不宣称业务完成或来源受限。

新修复事实到来后，只有原 08C 对账记录、可验的新证据与 `kind=reopen` 明确绑定，才能解除技术停止；用户主动暂停仍须 08C 的显式恢复，原来源预算与提交未知规则始终有效。`completion_check.py` 是只读检查：报告 `continue`、`awaiting_user`、`user_paused`、`execution_stopped` 或 `complete`，不自己调查、联网或发布。阶段性受限交付仍由原独立审阅和报告门禁判断；主动暂停始终阻断最终发布，技术停止对无 `limited_delivery_revision=failure-limits-v1` 的任务同样阻断，带该标记的新任务见 [workflow-efficiency.md](workflow-efficiency.md)（技术停止可作为有据限制进入受限报告）。历史任务无 08D 标记，仍按冻结合同执行。完成检查另可返回 `limited_round_closed` 与 `error`。`record_progress.py` 接受 `{"events":[...]}` 批量输入（全 begin 或全 finish 为原子批；其他种类按顺序逐条应用）。


## A04/A05 累计终止（bounded-execution-v1）

新任务冻结 runtime-config 的 execution_budget：自动执行累计 1800 秒、独立复核累计最多 900 秒；来源阶段保留 600 秒给复核。最多 96 个登记轮次、累计 12 个无进展轮次，跨查询、提供方、回退和重新调用累计，不因 reopen/repair 清零。现有单动作两轮无进展后诊断、一次可验证修复后仍失败则技术停止的限制继续生效。修复/重开不能仅换路径复用同一证据哈希。

进展比较忽略失败 run、新 ID、时间戳和重复说明，比较去重内容摘要、collections 和状态变化；复核队列尚有同一动作时不能以普通队列消失声称完成。内容变化只是调度信号，不代替原件哈希、相关性复核和发布验收。

advance_work、API/browser 和 report_review_host 共用 task 内 execution-budget.json。预算绑定任务和冻结参数；中断遗留租约按全部预留时长扣费，防止重启获得新额度。排队模块、汇总和双审共用截止时间；超时终止 POSIX 子进程组并保留已写证据和日志。限额停止新来源执行，输出 execution_stopped/incomplete 与原因，不授予成功或降低风险。剩余额度可继续复核和部分交付，完整发布门槛不变。

历史任务没有版本标记时不静默迁移。参数变更触发绑定错误，不自动重置。预算只约束上述入口，不能约束入口外模型思考、手工工具或直接 provider CLI；不是整个对话 40 分钟硬保证。Windows 清理分支未测试，真实端到端时限和 token 改善未测量。


### 2026-10-01 挑战验收后的修正

- 进展判断先按当前动作筛选关联来源，再核对原件哈希与成功语义。JSON 原件只比较去重的实际响应内容，重复响应的采集时间、run ID、诊断 metadata 不清除停滞。缺失/错误原件与证据删除不算新增进展；真实有效证据和解除义务仍算。读取复用仅限单次判断，跨判断重新核对文件。
- 轮次是08D已登记动作的准入额度，不是HTTP请求数。一次批次按剩余动作额度和无进展额度的较小值截取（以本批全无进展为保守上界），已准入动作通过任务租约传给子执行器，不再二次扣除；换查询/提供方和重启仍不能清零。直接API/browser入口共用时间预算，其动作轮次依赖08D记录器。
- POSIX 外层执行器独占进程组，由 process_group_exec.py 在exec前写入真实组ID；嵌套执行器验证并复用该组。全局超时由外层清理，局部操作超时只清理该操作子树，保留父进程与同组其他工作；输出回收等待额外限制2秒。主动脱离该组的外部进程和Windows尚未验证，不承诺清理共享浏览器。
- 内部预算停止可把确实未执行、无关联原件的来源/远程调查项目投影为受限待定，并继续预留复核时间、证据模式部分交付。限额证明绑定任务参数、日志、进展与具体计划行；恢复预算或相关输入变化后重算。没有双审、未读原件、候选分流、原件完整性错误、未知提交仍不得豁免；final模式不因停止而通过。stage模式的外部阻塞合同保持原样。
- 开始API/browser实际执行前先保留unknown提交状态，中断不能被“缺少run”误标成未查询。已登记执行但没有明确提交结果的查询，也不允许用未执行额度证明跳过。
- 预算初步校准仅使用本机真实子进程的合成耗时任务：六个模块会话、四并行、两条汇总共用复核截止时间。默认30分钟/复核最多15分钟/来源预留10分钟、96动作/12无进展保持初始值；保留10分钟意味着两波模块加一波汇总平均每波需在200秒以内（还须扣除准备/校验时间）。这只是调度容量计算，不是模型耗时测量。真实免费来源、模型双审与完整任务尚未校准，不宣称40分钟目标达成。
