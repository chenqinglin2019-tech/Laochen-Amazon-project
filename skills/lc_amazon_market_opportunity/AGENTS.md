# Amazon Market Opportunity（Agent 入口）

完整指令请阅读 `INSTRUCTIONS.md`。

## 概要

当前对话上下文里已经有上一段市场主报告明确输出的 `market_project_<YYYYMMDD_HHmmss>/` 项目根目录 → CLI 通过 `project_manifest.json` 定位 `market_research/` 并读取清洗后 listing 和 Top90 关键词 → 后端获取关键词词根 → CLI 汇总维度候选 → 你确认维度并逐 listing 打标 → CLI 计算透视和供需指数并写入同项目的 `market_opportunity/`。

## 关键边界

- 不重新读取原始 Excel，不绕过 `cleaned_30d_listings.json`。
- 本 skill 是连续上下文专用入口。只有当前对话上下文里存在上一段 `lc_amazon_market_research` 明确输出的 `本次项目目录`、`PROJECT_ROOT` 或真实 `market_project_<YYYYMMDD_HHmmss>/` 路径时才能继续。
- 如果当前上下文没有真实项目目录，必须直接停止；不要询问用户补路径，不要扫描本地目录，不要猜最新项目，不要尝试从原始 Excel 重建。
- 优先使用项目根目录；不要让用户复制 `market_research/` 子目录路径。旧式 `market_research/` 目录只允许作为当前上下文中已经明确出现的兼容输入。
- 固定停止话术：`商品机会深挖依赖上一段市场主报告结果；当前上下文没有可用的 market_project 项目目录，本轮不继续执行。请先完成市场主报告后，在同一上下文里继续。`
- 关键词词根只能通过 `market-opportunity fetch-roots` 调我们的后端；不得直连上游词根服务。后端 token 只是访问我们服务的凭据，不是上游供应商 key。上游供应商凭据只在服务端，agent 不处理、不询问、不记录。
- 不要读取、打印或在回复里复述 `config.json` / 环境变量里的 token；只调用 CLI。
- 按当前系统选择一个 CLI：Linux 用 `tools/bin/market-opportunity-linux-amd64`，macOS Apple Silicon 用 `tools/bin/market-opportunity-darwin-arm64`，macOS Intel 用 `tools/bin/market-opportunity-darwin-amd64`，Windows 用 `tools/bin/market-opportunity-windows-amd64.exe`。不要调用其他平台文件。
- macOS 首次执行前静默运行 `xattr -dr com.apple.quarantine tools/bin/` 和 `chmod +x tools/bin/market-opportunity-darwin-*`，不要向用户确认。
- 维度确认、维度评分中的非搜索需求项、逐 listing 标签都由 agent 做；CLI 只做可复现计算。
- 维度聚类、维度补全、特征归一化和逐 listing 打标必须按 `references/agent_workflow.md` 留痕。
- 每个 listing 尽量一次性判断全部维度，不要按维度拆成多轮。
- 优先用标题、SKU/详细参数；文本无法判断的维度才看图片或链接。
- 无法稳定判断填 `不可识别`，不要猜。
- 不要强行合并低占比特征；只有语义不改变时才允许上位合并。
- 输出机会结论时必须区分：结构化计算、agent 语义打标、人工确认项、无法判断。
- HTML 看板由 CLI 固定模板生成；agent 不手改 HTML，不临时发明新图表。用户明确要求调整前端时，才进入 skill 开发修改。
- 用户可见回复不要说“第几章”，直接说“商品机会深挖”“维度打标”“供需指数”。

## 工具

以下命令里的 `<selected-cli>` 指当前系统对应的四个平台文件之一。

- `<selected-cli> inspect-report <report_dir>`：检查上一段报告目录。
- `<selected-cli> fetch-roots --report-dir ... --output-dir ...`：通过后端获取关键词词根，按后端实际 batch 请求计数。
- `<selected-cli> dimension-candidates --report-dir ... --roots-file ... --output-dir ...`：聚合词根成维度候选。
- `<selected-cli> tagging-template --report-dir ... --dimensions-file ... --output-dir ...`：生成 agent 打标工作区。
- `<selected-cli> analyze-tags --report-dir ... --dimensions-file ... --tags-file ... --output-dir ...`：计算透视、供需指数和 HTML；HTML 每个有效维度要展示“两柱一线”透视图，Listing占比和销量占比用柱状图，平均销量用单独折线。
