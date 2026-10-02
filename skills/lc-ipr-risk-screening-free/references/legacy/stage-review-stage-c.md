# 09C 阶段批次、独立双审与主审

新任务默认使用 `api-first-v3` 与 `final-double-review-v1`，以[API 直接采信与一次最终双审](../api-direct-final-review.md)为优先契约。已采信 API 字段不生成官方网页重复核验；过程保留事实分析，取消 09C 阶段双审前置。下文旧修订仅约束保留该版本的历史任务。

仅 `stage_review_revision=stage-review-stage-c-v1` 的新任务启用。先按 09B 记录已审成果、实质失效和信号；09C 将同一情景、国家、权利和产品版本的当前判断及信号作为一个可交付批次。普通批次在专项成果可解释、用户要阶段结果、等待／停止交接或交付前截点冻结；重大失效须引用 09B `invalidate` 事件立即定向冻结。暂停、鉴权和访问边界仍由原工作流控制。

通过 `python scripts/record_stage_review.py --task-dir /absolute/run --input /absolute/freeze.json` 追加 `kind=freeze`。输入须包含 `actor`、`scope`（`scenario_id`、`jurisdiction`、`right_type`、`product_version`）、`trigger`、`trigger_reasoning`、该范围全部当前 `item_ids` 和四条 `coverage_notes`：`necessary_directions`、`excluded_candidates`、`unreviewed_material`、`unresolved_scopes`，各条有 `disposition` 与 `reasoning`；确实没有的项目明确记 `none`。原候选清单中同权利但未进入判断的候选会单列 `unjudged_candidate_ids`，排除说明须逐个列出这些 ID，并说明已排除、尚未审或不适用。允许的触发值为 `deliverable_batch`、`user_stage_request`、`wait_or_stop`、`pre_delivery`、`material_invalidation`；后者另给 `invalidation_id`。冻结事件保存产品及情景快照、判断／信号原文与指纹、所引原始证据／比较事实、候选身份与指纹、09A 计划范围及已知未审范围、排除／限制说明、来源与阶段判断截点和统一 `evidence_digest`。重大失效可把已暂停旧判断立即冻结供定向审查，旧等级不因此恢复；缺失原始事实列入 `missing_source_refs`，主审必须补证。零候选也须有 09B 已审零结果判断及覆盖限制，不能用空批次冒充已审。

使用 `--export-batch BATCH_ID --output /absolute/input.json` 导出不含任何审阅内容的冻结输入。宿主必须给两位审阅者分别开独立工作区，只挂载**同一导出输入**，不挂载任务目录、另一审阅的文件或中间输出；分别记录真实访问日志、独立 reviewer／session／agent／run／workspace。访问日志 JSON 必须有匹配的 `workspace_id`、`input_digest`，`mounted_artifacts` 与 `read_artifacts` 均仅为 `["frozen_input"]`，且 `task_directory_mounted=false`。提交前宿主以仅宿主持有的 `LC_IPR_REVIEW_HOST_KEY` 对规范 JSON 摘要签发 `isolation_receipt.host_hmac_sha256`。签名覆盖 `host`、五个身份、访问日志绝对路径与 SHA-256、`input_digest`、`first_review_visible=false`、空 `visible_review_ids`／`read_review_ids`、`output_created_after_isolation=true`、`task_directory_mounted=false`。不得由审阅者自行填写或签发。若宿主不能提供可核隔离凭据，程序拒绝把双审标为有效；布尔声明和不同 ID 单独不够。此签名证明宿主断言来源，实际隔离还依赖宿主正确执行和保留访问日志；离线测试不证明真实隔离。

两次 `kind=review` 分别绑定 `batch_id`、相同 `evidence_digest`、宿主凭据、`items` 和 `coverage`。每位均审全部未复用项；各项有 `stage_risk`（信号项改为 `signal_conclusion`，不抬升当前风险）、`evidence_refs`、`comparison`、`gaps`、`reasoning`。引用限于冻结事实。`coverage` 四项 `plan`、`unreviewed`、`exclusions`、`limitations` 都要实质说明。提交前有新增或变更的当前判断、计划范围变化，须先重新冻结共同版本；不能让主审处理输入分叉或泄露。

`kind=adjudicate` 包含两份审阅事件的 `event_id` 与规范 `review_sha256`、逐项 `decisions`、`coverage_reasoning`、`chief_reviewer`。每项明确 `conflict`，同级异据／理由不同也视为分歧；主审对无分歧项仍写事实与理由。事实足够时 `status=resolved` 且选择有据等级或信号结论，不投票、不平均、不默认高。缺关键事实时 `status=needs_supplement`，填 `gap.missing_fact`、`impact`、`minimal_action`、`responsible_step`；原 `next_work.entries` 和 08A 统一问题／动作视图出现一条最小补证待办，不另建任务队列。补证进入原证据，09B 更新受影响判断，再冻结共同新版本；可用 `reuse={item_id: prior_batch_id}` 复用指纹完全相同且已主审完成的未影响项，其他项双方定向复审。补证无法完成时保留待办和核实待评。

`next_work.stage_risk.stage_review` 显示批次状态，逐项 `review_status` 仅在两审和主审有效时变为 `chief_reviewed`；主审采纳另一等级时保留 `single_review_stage_risk`，显示裁决等级并重算范围汇总。高／极高及极低仍须满足 09B 已冻结的关键事实条件，不能靠主审文本跳过。任何范围、候选清单或原判断变化使旧批次 `stale_recheck_required`；09A 完成数变化本身不重审同一批。09C 不输出 09D 初步阶段结果，也不改变旧任务和完整报告的冻结合同。

## 实际宿主接入预检与停止重复尝试

冻结前先核宿主是否能为两位审阅者提供各自受控工作区、仅冻结输入的挂载/读取边界、真实访问日志以及仅宿主持有的签发能力。普通共享文件系统Agent工具本身不提供这些证明，不能把“要求不要读取其他文件”当作挂载隔离，也不能自行生成一份声明日志冒充宿主访问记录。

缺能力时一次记录精确依赖（两份受控执行上下文、相同input_digest、宿主真实访问日志与签名），将正式双审保持未完成；可独立完成的来源修复和离线交付检查继续。相同环境、冻结输入和能力未变时不再重复启动两审、不换ID/新建批次期待通过、不反复审相同材料。恢复以宿主实际提供新能力/凭据并通过原验证器为条件，不能放宽PRD的真实隔离或原签名合同；不存在宿主接入时如实列未验收，初步阶段输出不能替代正式验收。

## 已安装Codex CLI的本机macOS宿主

当前Mac可用 `scripts/macos_review_host.py`，保留原09C签名/覆盖/主审校验，不改任务冻结协议。先确认已有原生Codex CLI、已有ChatGPT登录与系统sandbox-exec；不要求用户新建服务或复制凭据。传入原生可执行文件路径，不能把Node包装脚本当作原生程序。默认路径只支持文本冻结输入；外部原文、图片路径不自动变成已阅读。需要实际图文时使用下述受控材料入口，未提供的视图或事实仍记录真实缺口。

```bash
python scripts/macos_review_host.py --task-dir /absolute/run --batch-id STAGE-REVIEW-ID --codex-binary /absolute/native/codex --output-dir /absolute/new-host-run --record
# 主审独立写好裁决后，复用原宿主凭据，不重跑两审：
python scripts/macos_review_host.py --task-dir /absolute/run --adjudication /absolute/chief.json --host-run-dir /absolute/host-run
```

宿主创建两个独立临时工作目录，只置入同一冻结输入；以macOS内核禁止读取/写入业务目录、宿主输出和另一工作目录，并用真实存在的控制文件先验证读写边界。所谓“不挂载任务目录”在此指任务材料未向审阅进程暴露，依靠内核读写禁止实现，不声称使用容器挂载命名空间或整台机器隔离。两审均为新的CLI线程，禁用该子进程的shell工具/快照及Code Mode，忽略用户MCP/执行规则配置但保留更严格的外层内核边界；不改变全局配置或原任务鉴权。运行实际cwd先切到独立目录，不能只依赖-C修复启动时访问被禁目录。

输入由宿主经stdin传入；宿主保留冻结摘要、实际PID/线程、内核控制回执、完整CLI事件与配置指纹。任何工具活动、请求失败、未完成或多轮轨迹均拒绝签发。子进程环境不含宿主密钥或来源凭据；两个输出先共同通过原09C验证器再追加。新生成签发密钥以0600仅保存在被审阅进程禁止访问的宿主输出，供后续主审核原凭据；不进入Skill包，不复制到审阅输入或日志。已有外部管理密钥继续用原环境，不另写入。

脚本只记录双审，不自动裁决或完成业务；主审仍逐项处理真实分歧和缺口。已有审阅时拒绝再次整对执行；中途故障不自动重试或重新建立批次。当前支持Mac本机文本输入的有界能力，不代表所有宿主/视觉双审已接入。

## 同源图文材料入口

本机命令添加 `--read-retained-materials`。只取当前冻结项实际引用、已留存、带SHA256且有原公开source_url的公开来源/商品采集材料；用户文件不因本地路径存在自动外传。路径必须在原任务内，字节与原指纹匹配，否则在模型调用前拒绝。没有图像、材料超出支持类型或资源界限时明确停止，不截断、不改为已读。

每位审阅者自己的冻结输入包包含同一材料清单、必要正文及图片字节。图片通过原生CLI初始附图参数传入，顺序只对应清单中的attached_image行，编号与原证据引用分别保留；HTML只交可见正文，PDF只交逐页抽取文字，PDF图像及版式未核验，抽取空白不是无内容。禁止拼接混款或不同卖家视图为同一实物。

原任务、另一工作区及宿主日志依旧禁止访问。控制回执逐图核字节；宿主在签名覆盖的日志内保存完整材料包摘要、图片摘要、传入方式和审阅者逐材料实际观察。观察属于实际模型输出，不由宿主伪造；图片传入证明与具体实体结论的有效性仍由主审分别核对。只挂载frozen_input在此指包含清单和图文的冻结输入包，不暴露任务其他文件。

已有文字批次不得重启。仅在已登记的实际图文阅读缺口获得新能力后，为受影响项另冻同源批次，并写明新输入能力与原待补证的关系；保留旧审阅/主审。不因有图片自动推定完整视图、作者、许可或权利成立，不对同输入反复双审以追求特定等级。

跨批次的10D/10E实际凭据复验仍须宿主密钥上下文。需要同时验多个当前批次时，宿主复用同一受保护本地签发密钥（从首个宿主输出取得），通过临时环境供记录器和校验器使用；子进程继续移除此密钥，不写入任务/报告/包，不复制其他Skill密钥，不改全局环境。不同批次的审阅身份与输入仍独立；不能缺密钥时跳过原HMAC校验。
