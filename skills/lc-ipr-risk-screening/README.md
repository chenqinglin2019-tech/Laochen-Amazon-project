# LC IPR Risk Screening 1.0.3

对单个美国 Amazon 商品执行知识产权风险筛查，使用老陈云端服务完成核心查询，
再由 Agent 审阅候选并生成离线报告。报告不是法律意见，未检出不等于没有风险。

## 安装或更新

- Skilldeck 用户：在技能市场刷新，更新 IPR Skill，再新建任务或选择新版技能。
  已有任务可能仍绑定旧版本，更新不会自动重跑或迁移它们。
- 手工安装用户：先备份旧的 `lc-ipr-risk-screening` 目录和个人配置，再用本包的同名
  目录整体替换旧版技能目录。不要把新旧 `tools/` 文件混用。
- 保留个人老陈 Token；推荐通过 `LAOCHEN_BACKEND_TOKEN` 环境变量提供。
  本包 `config.json` 的 Token 默认留空，不包含客户凭据。
- 保留已有任务、原始结果和回执。任务目录应放在 Skill 包外；如果此前误放在包内，
  先将完整任务目录保全到包外，再替换 Skill，不要覆盖或删除任务资料。
- 更新完成后，让 Agent 重新读取 `SKILL.md`，执行 `auth-check` 验证授权，再创建新筛查任务。
  遇到旧 V1 的 HTTP 410 / `SKILL_UPGRADE_REQUIRED` 时停止，不更换请求 ID 重提旧任务。

## 使用

向 Agent 提供美国 Amazon 链接或 ASIN，也可附主图和细节图。运行流程以
`SKILL.md`、`INSTRUCTIONS.md` 和 `references/` 为准。需要有效的老陈 Token 和本技能授权。
`SERPER_API_KEY` 为可选公开网页增强；没有时可跳过，继续云端核心流程。

包内包含 Windows x64、Linux x64、macOS Intel 和 Apple Silicon 程序。
macOS 首次运行的权限处理见 `INSTRUCTIONS.md`。

## 本版修复

- 配套云端后端已修复文字商标检索参数；保留历史请求与回执绑定。
- 单项明确待核对时，后续独立查询继续执行；未决请求和已有成功结果保留。
- 图搜待核对时，已成功来源可正常导入；后续独立 TRO 案卷不会被前一项阻断。
- 兼容历史版权图片摘要，避免已有图片被误判为未绑定。

计费价格与退款规则不变。更新本身不会自动重跑旧任务、补扣或退款。
