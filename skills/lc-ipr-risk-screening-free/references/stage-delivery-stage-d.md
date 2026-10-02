# 09D 初步阶段结果与完整报告交接

新任务启用 `stage_delivery_revision=stage-delivery-stage-d-v1`。在已有可说明调查成果、用户要求阶段结果、等待／停止交接或交付前，需要初步输出时，运行：

```text
python scripts/create_stage_result.py --task-dir /absolute/run --output-dir /absolute/new-stage-output
python scripts/create_stage_result.py --task-dir /absolute/run --output-dir /absolute/new-stage-output --validate-only
```

输出目录必须是新的，不能覆盖任务或旧版。`stage-result.json` 是统一结果记录；`stage-result.md` 和 `stage-result.html` 只由该记录渲染，`stage-manifest.json` 保存字节指纹，`stage-validation.json` 表示本地独立校验通过。校验会重新读取当前任务、证据、候选、计划、统一待办与阶段判断，并重建模型和渲染字节；源文件、引用或输出改变后旧结果校验失败，需要新版本。这里的本地校验不等于用户已收到或可访问，也不改 `task` 的业务完成状态。

结果分别给出计划版本、当前唯一工作项 C/N 与各专项小计、来源运行截止、阶段判断与批次审阅截止，以及每批冻结时与当前已完成项数的差别。最近的审定等级若基于较早批次，显示尚未纳入该等级的后续成果；取证、评估日期不因生成结果刷新。等级、核实状态、审阅状态、可用性和工作进度独立显示；未双审只能标“初步判断／待双审”，可执行剩余工作、核实待评和用户暂停不会被阶段结果自动改为完成或恢复。

阶段校验核对冻结产品身份、任务与证据一致性、原判断事件、引用事实与留存文件内容指纹、候选身份和可核的 09C 隔离日志。局部坏引用或身份错误仅暂停依赖它的判断，重算受影响汇总并列隔离原因；独立有效部分仍可交接。整体产品绑定失败时只交进度、问题和下一步，不交风险等级。09C 宿主凭据当前无法复验时回退到原单审等级及待双审标签，不能展示主审选级为已审定。

本入口是简明阶段结果，不调用 `publish_report.py`，不生成 `assessment.json`、完整报告文件或完整报告通过状态。完整／受限报告继续走原 `publish_report.py`、`necessary_completion.py`、`completion_check.py` 的必要工作、来源、双审／主审与产物校验；模块 10 另验实际交付位置与文件。已生成阶段结果不会自动满足这些门禁。
