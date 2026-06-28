---
name: lc_amazon_market_opportunity
description: 仅在当前对话上下文已经有 lc_amazon_market_research 刚生成并明确输出的 market_project_<YYYYMMDD_HHmmss>/ 项目根目录时，继续做 Amazon 商品机会深挖：通过服务器端关键词词根能力拆解 Top90 关键词，生成消费者决策维度候选，让 agent 完成维度确认和逐 listing 打标，再由本地 CLI 计算特征分布、维度透视、多维组合供需指数、正式机会组合和单文件 HTML 看板。上下文没有真实项目目录时必须停止，不询问路径、不扫描猜测、不重新读取原始 Excel；agent 不处理上游供应商凭据。
---

# Amazon Market Opportunity

本 skill 是 `lc_amazon_market_research` 的下一段：商品维度打标、多维透视和供需指数。它是连续上下文专用 skill，不是独立入口；不重新跑市场主报告，也不重新读原始 Excel。

## 使用方式

1. 先读 `INSTRUCTIONS.md`。
2. 先从当前对话上下文读取上一段明确输出的 `本次项目目录`、`PROJECT_ROOT` 或真实 `market_project_<YYYYMMDD_HHmmss>/` 路径。
3. 如果当前上下文没有该路径，立即停止，不询问用户补路径、不扫描本地目录、不选择最新项目。
4. 按当前系统选择对应平台 CLI 二进制，不要调用其他平台文件。
5. 调用 CLI 的 `inspect-report` 检查目录；传项目根时 CLI 会自动定位 `market_research/`。
6. 调用 `fetch-roots`。关键词词根请求必须走服务器 `/market-opportunity/keyword-roots`；CLI 自行从环境变量或用户本机私有配置读取我们后端的访问凭据，agent 不处理上游供应商凭据。
7. 调用 `dimension-candidates` 聚合词根需求覆盖，生成维度候选。
8. Agent 基于候选词根和品类常识确认 3-6 个最终维度，写 `agent_dimensions.json`。
9. 调用 `tagging-template` 生成待打标 listing 工作区。
10. Agent 逐 listing 判断所有确认维度，写 `agent_listing_tags.json`。文本能判断就不用图片；无法判断填“不可识别”。
11. 调用 `analyze-tags` 计算特征分布、维度有效性、多维组合供需指数和 HTML 看板；HTML 里每个有效维度都要展示“两柱一线”透视图：Listing占比和销量占比用柱状图，平均销量用单独折线。传项目根作为 `--output-dir` 时，结果会自动写入同项目的 `market_opportunity/` 并更新 `project_manifest.json`。

## 资源

- `tools/bin/market-opportunity-linux-amd64`：Linux CLI。
- `tools/bin/market-opportunity-darwin-arm64`：macOS Apple Silicon CLI。
- `tools/bin/market-opportunity-darwin-amd64`：macOS Intel CLI。
- `tools/bin/market-opportunity-windows-amd64.exe`：Windows CLI。
- `references/input_contract.md`：输入、agent 中间文件和输出约定。
- `references/agent_workflow.md`：维度确认、逐 listing 打标、特征归一化和解释边界。
