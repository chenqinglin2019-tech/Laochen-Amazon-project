# 10C 按类型文件与必要材料

显式 `presentation_policy_revision=operator-report-v1` 额外交付 `operator-appendix.html`（完整候选、逐要素比较、缺口及恢复条件）和 `technical-audit.html`（内部追溯）。两文件由同一报告数据生成，纳入 required_artifacts、Manifest 字节与哈希校验以及实际入口验收。运营正文只链接附录，不把完整 JSON 或内部待办塞进主 HTML 的折叠区。未带运营标记的历史任务保持原文件清单；不自动追加附录。

新任务采用 `report_package_revision=report-package-stage-c-v1`，旧任务沿原合同。完整／受限报告必需 `report.html`、`report-data.json`、`report-manifest.json` 及本次必要引用的真实留存材料；是否业务完成仍读 10B。新任务默认不生成 Markdown／CSV，创建任务时按用户要求、交付约定或具体使用需要传 `--report-export markdown`、`--report-export csv`（可重复），对应冻结在 `report_exports`。不要为满足旧固定套装无故生成可选文件。

所有实际导出取自同一报告记录。核心文件和已约定导出写入 `report_package_stage_c.required_artifacts`，Manifest 对实际产物登记字节与哈希，附件另列 `material_files`。校验按该合同核文件，未要求且未生成的导出不是缺项；约定文件缺失、错版／字节错误或出现未登记的旧导出均拒绝通过。可选文件失败只续作相应导出，未受影响的业务成果不因此重跑。页面只提供本次实际文件的链接。

报告沿用原注册文件、证据引用和复制校验，不扫描全部缓存、不为相同材料重复复制。必要材料按稳定证据 ID 绑定实际文件；当前阶段引用也纳入相同证据索引。真实留存的结构化事实／来源内容可以绑定 `report-data.json` 内具体 JSON 位置及记录摘要，注明只交付留存记录、不声称交付原文。URL／候选号／占位不能证明交付原文；无可交付材料的引用以 `business_material_gaps/not_obtained` 披露，不生成空文件。已留存的必要材料缺文件／哈希不符属于交付缺项；来源网站暂不可用时仍可交付有效留存字节，不重新联网探测。业务缺口不会因清单登记自动消失。

阶段成果保留同一已校验 `stage-result.json` 和版本追溯，不要求完整报告套装。新任务默认以答复载体交接：本地 `stage-result.txt` 保存待交接的确切文字，CLI 返回同一 `reply`；仍不表示实际送达。创建任务时可用 `--stage-carrier html|markdown|csv|reply` 指定一个或多个载体，冻结在 `stage_carriers`，均从同一阶段记录导出并独立校验；没有选 HTML 就不强制生成页面。CSV 保存范围、判断状态、信号、进度、剩余工作和同一模型摘要，不另编评级。内部阶段 JSON／Manifest／校验收据用于留存与复验，不是要求用户接收完整文件包。

旧的本地发布完成字段仍不等于实际可访问入口。独立交付重读／修复见 [10D](delivery-inspection-stage-d.md)，版本／实际本地入口验收见 [10E](delivery-versions-stage-e.md)。
