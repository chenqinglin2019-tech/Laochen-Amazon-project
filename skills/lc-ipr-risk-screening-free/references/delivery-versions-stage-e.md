# 10E 固定版本、可靠本地交付与更正

新任务显式启用 `delivery-versions-stage-e-v1`。旧任务不静默迁移。报告生成和阶段答复生成都先登记固定来源快照及独立交付版本，再构建于新目录；生成／独立校验失败记实际步骤，构建通过仅表示 `build_verified / not_delivered`，不提供正式成功入口。版本和可变交付状态存于原任务 `delivery-versions.json`，不回写已验收页面、JSON 或清单。

## 构建与交付

运营版推荐一次调用：`python scripts/publish_report.py --task-dir TASK --first-review FIRST --second-review SECOND --adjudication CHIEF --output-dir NEW_BUILD --deliver-to NEW_ENTRY --require-complete --mode auto`。同一进程内完成构建、固定版本、真实复制、入口验收及完成检查。完整语义复算一次；之后内容绑定检查保留全部原件、输入、审阅、产物和链接的实际校验。失败不返回正式成功入口；独立续跑或检查入口不复用已保存的成功标记。

运营必交项增加 `operator-appendix.html` 与 `technical-audit.html`，同正文及材料一起固定哈希、复制及验收。页面用“本轮调查结束／具体事实仍待补充”陈述冻结时的业务状态；实际入口状态由交付日志及本次返回的入口表示，不通过交付后改写已冻结 HTML 来改变结论。

`publish_report.py`、`create_stage_result.py` 沿用原构建参数；新任务返回 `version_id`。实际本地交付需明确目的位置：

`python scripts/delivery_versions_stage_e.py --task-dir TASK --action deliver --version-id DV_ID --destination NEW_DIRECTORY`

脚本重读当前已知来源与实际审阅，核对快照仍适用，重核构建文件，再复制并重读目的位置全部应交项、字节和本地引用／锚点。成功后才返回本次入口和 `entry_verified`；不要求用户已读，不把业务状态改为完成。仅核本地可访问位置，不调用网络或证明外部托管入口；若用户另有托管／发送请求，必须另验实际载体与授权。

纯追加的合法工作项完成事件，或仅追加调查暂停，须由当前 09 阶段模型证明身份、判断、引用与审阅状态未改变，才复用已验收旧版，并在交付状态说明中披露旧进度／评级截止及较新进度／暂停。新事实、新来源回执、变更计划／范围／候选或审阅不猜作无害进度；交回原链定向复核。需要展示较新内容则生成新版本。核对只读已知资料，不做联网刷新、固定有效期或自动监控。 复制前后重建变化投影沿用该版本已冻结的 `generated_at`（历史缺字段则用版本 `created_at`）；时间跨秒不构成实质变化，输入、原材料及风险内容仍完整核对。

复制或实际入口验收失败，返回本次失败步骤、无成功入口，保留构建和原依据；新建失败目录尽量移到 `.failed-delivery-*`，隔离状态记录保存原尝试及位置。旧入口及文件不被覆盖。重试使用同一版本及新的目的目录，重新核快照和实际文件，不重跑调查／审阅，不重置计数或解除暂停。构建失败但完整产物仍有效，可 `--action retry-build --version-id DV_ID` 重验原构建；缺项／字节错误用 10D 定向修复到新目录后采用。

`--action status` 只读输出版本、实际入口可用性、当前判断适用性及更正关系；构建位置本身不能让完成门禁通过。完成检查另要求对应目的位置仍与本版一致。

## 更正与新旧关联

先经原责任环节核定问题及实际影响，再用 `--action correction --version-id OLD_DV_ID --input REQUEST_JSON` 记录原因、修改内容与前版。

- 展示修正：`kind=display`、`reason`、非空 `changes`。采用 10D 在新目录恢复的规范文件；新旧结果内容及来源快照须相同，允许交付版本不同。事实、引用对象、适用范围或等级改变不能归为展示修正。
- 实质更正：`kind=material` 另要求 `affected_judgment_ids` 和真实 `upstream_refs`；必须已沿 09 追加有依据的失效事件，校验原事件链及每项暂停依据，直接引用影响及恢复动作，不另造判断记录。当前状态立即展示原判断／整体待复核，独立有效部分由当前阶段模型保留；新增文件不等于已经补证或必要审阅通过。

新构建通过 `--correction-id DC_ID` 绑定原更正（报告／阶段 CLI 均支持）。已修复且独立验收通过的目录可 `--action adopt --build-dir REPAIRED_DIRECTORY --correction-id DC_ID` 登记新版本，不重跑调查。实质更正仅在受影响范围有当前有效、实际主审通过的新判断后标替代；未完成必要复核的合格阶段成果只记 `interim_stage_delivered`，旧判断仍暂停，失败也不恢复。

更正说明记录前版入口、原因、修改、对象／范围、原判断影响和新版关系；保留全部旧文件及历史证据，不声称已下载副本同步更新。迟到材料仍通过 08C 核原任务、对象、范围、版本、历史计数、解除依赖和剩余动作；本记录不自动恢复暂停、不发起调查或监控。报告版本不刷新实际取证日、评估时点或审阅版本。

### 原始 HTML 附件的链接边界

`files/` 内保留的原始网页按原件哈希验证，不把其中的来源站点根路径当成本地报告依赖，也不改写原件。报告入口 HTML 仍须检查本地文件、JSON 指针和锚点；路径越界或缺失返回交付错误。所有附件仍必须复制且哈希一致。

### 本轮证据交付与业务完成

在当前发布门禁、双审、文件校验和实际入口 entry_errors 全部通过后，evidence 模式且业务状态 awaiting_dependency 的版本由完成检查记为 limited_round_closed；business_completion=incomplete，等待项和恢复条件保留。final 模式仍须 business_complete。未交付、损坏文件、变动输入及可执行待办均不能关闭本轮。

`advance_work --require-complete` 的退出规则与完成检查及 Stop 门禁一致：接受完整业务完成或已核验的本轮受限交付；这不会把 limited_round_closed 改为业务完成。
