# 结束保护与断点恢复

新任务默认使用 `api-first-v3` 与 `final-double-review-v1`，以[API 直接采信与一次最终双审](api-direct-final-review.md)为优先契约。已采信 API 字段不生成官方网页重复核验；过程保留事实分析，取消 09C 阶段双审前置。下文旧修订仅约束保留该版本的历史任务。

本规则只增加运行保护，不改鉴权、来源授权、0 USD 上限、评级、双审和 HTML/CSS。业务第一条命令仍为 auth_gate.py；鉴权失败立即按原门禁停止，不能让钩子反复执行鉴权。开发、规划、状态问答、离线测试不绑定业务任务。

## 安装与真实能力边界

在 Skill 根目录用安装检查确认的 Python 执行 `python scripts/install_codex_guard.py --preview`，确认后不带 `--preview` 安装。仅合并本 Skill 的 SessionStart、UserPromptSubmit、Stop、Interrupt 命令；已有 hooks.json 先按原字节备份。遇到内联 hooks 配置拒绝自动混写；其他匹配钩子可能覆盖继续决定，须检查冲突。`--uninstall` 仅移除本 Skill 的四个命令，保留其他钩子及恢复记录。

用户必须在 Codex 原生 `/hooks` 界面审阅并信任确切定义；不得修改信任数据库或使用 trust bypass。脚本变更后重新运行安装器，让命令指纹变化并重新信任。用户级设置不保证当前桌面宿主加载，重载／新会话后必须真实验证。安装回执始终先标记 `not_enabled_until_native_trust_and_desktop_smoke_test`，不能以 CLI 版本、mock 或直接调用脚本替代桌面验收。

Stop 的 block 在模型已经结束后创建继续提示，不隐藏先前回答。用户中断、退出应用、权限、额度、宿主跳过／超时或其他钩子的 `continue:false` 仍可能停止执行；这是防误结束机制，不是不可绕过的安全边界。官方接口：https://developers.openai.com/zh-Hans/docs/hooks

## 绑定与执行

1. 获取本轮真实 `CODEX_THREAD_ID` 或宿主钩子提供的 `session_id`，不能编造 ID。非 Codex 宿主缺少此能力时，披露“结束保护未启用”，仍执行人工调用的完成检查。
2. 业务鉴权通过后，`create_task.py` 或新目录 `resume_continuous_work.py` 带 `--guard-session-id`。现有 continuous-work 任务明确继续时用 `codex_guard.py resume --session-id ID --task-dir DIR`，旧策略任务必须先走新目录迁移入口。
3. 按 `next_work` 执行。`advance_work.py --guard-session-id ID` 可以同步显式 `--first-review/--second-review/--adjudication/--output-dir`；未指定审阅路径时，完成检查默认读取任务目录下 first-review.json、second-review.json、adjudication.json。不猜报告目录，不从旧状态文件推断交付。
4. 完成发布后以 `completion_check.py --task-dir DIR --output-dir REPORT_DIR` 重新校验；非默认审阅路径必须同传。退出 0 仅表示完整交付，2 表示有待办／等待，3 表示检查故障。返回 status、stage、reasons、next_actions、progress_digest 和完成时的报告路径。
5. 钩子只调用此只读检查，不做调查、联网或发布。运行元数据位于 Codex 用户目录的 `lc-ipr-guard/sessions/`，不写业务证据，不形成第二份待办队列。摘要忽略无意义时间更新——包括 08D 的 begin/finish/diagnosis 簿记事件、`recorded_at／observed_at／started_at／finished_at／elapsed_ms／generated_at`（只计入有效进展的 finish、repair、technical_stop、reopen）；错误日志不回显原始凭据或异常内容。完成检查的钩子超时为 110 秒（钩子本身 120 秒，须高于前者），改动 `codex_guard.py`／`completion_check.py` 后须重新运行安装器并在 `/hooks` 重新信任。交付成功后 `publish_report.py --deliver-to` 与 `delivery_versions_stage_e.py --action deliver` 会把钩子绑定改为实际交付入口，完成检查须对交付入口而非构建目录运行。

`advance_work.py`、报告发布和钩子共用独立交付校验，重算当前证据、审阅、报告，而不是相信 completed 字符串。新交付回执还绑定补充清单、来源能力、浏览器状态与候选记录的存在性和字节哈希。历史回执仍按原格式读取，但不得借旧状态跳过完整独立验证。

## 继续、等待、失败与用户控制

- 有可执行工作时 Stop 返回继续指令。每次都重新检查实际文件；只有未续跑的初始通知、同轮次、相同输入和路径才复用响应以防重复计数。`stop_hook_active=true` 即使沿用 turn_id 也重验并计入诊断机会。业务进展重置计数；重新 bind 同一活动任务不重置计数。
- 控制状态使用短跨进程锁；长时间验收不持锁。同任务更新只写路径，检查前后比较路径和控制快照。旧任务已完成后更换绑定须重新核验，不能相信保存的 complete；期间发生用户中断则取消切换。
- 同一业务摘要连续两次未变化，分别派出第 1、2 次诊断续跑：检查当前动作、执行回执、文件和命令故障，不能盲目重复来源调用。随后仍无变化则标记 `failed`，显示“执行失败／未完成”，保存检查结果及 resume 命令；这不是外部来源限制或完整报告。诊断提示发出不等于修复实际成功。
- 等待仅在当前没有其他可执行动作、没有待澄清提交，且现有待办明确要求用户独有资料或访问操作时成立。已完成有界调查的外部缺口可以进入 evidence 最终报告，不能借此跳过双审或发布。带 `failure-limits-v1` 的任务在阶段已到裁决／发布／交付／校验时不再返回 `awaiting_user`／`execution_stopped`，钩子继续推动这些步骤。
- 用户点击停止触发 Interrupt，保存 interrupted 状态；检查器运行期间的用户中断优先。用户用文字要求停止或换题时，UserPromptSubmit 暂停自动续跑；Agent 按实际意图答复，不自动 resume。只有精确匹配本钩子发出的继续提示才保持续跑。
- 普通新问题（包括进度问答）暂停本轮强制续跑，保留证据。新消息明确要求继续排查时，先重新执行原业务鉴权，再 resume。审计、规划不得恢复。规划模式不触发业务续跑。
- SessionStart／压缩只提示已有绑定和恢复状态，不执行业务命令。应用重新打开但用户已停止时不得自动继续；未停止的活动任务可读断点继续，不重复已登记来源调用。
- `codex_guard.py status --session-id ID` 查看运行状态；`pause` 仅用于用户明确停止／暂停。不能为规避未完成工作调用 pause/resume，不能把内部故障改成完成。

## 验收

离线回归覆盖读原文／调查／分流未完、缺双审／裁决／HTML、伪造完成、篡改报告及原件、外部限制下合法交付、重复 Stop、多会话、规划、新问题、中断竞争、异常和有界诊断；fast 与 release 仍必须通过。

桌面冒烟必须在隔离的合成任务执行，明确非业务证据、不访问真实来源：先保留可执行动作并故意结束，检查宿主真实 Stop 事件和自动继续；完成样本双审裁决及报告后再次结束，确认独立检查通过。记录宿主版本、session_id、触发事件、续跑轮次和最终报告摘要。未信任、未触发或只能直接调用 hook 脚本时记 `not_run`／`not_enabled`，不能标已启用。不得给真实排查任务写合成审阅。
