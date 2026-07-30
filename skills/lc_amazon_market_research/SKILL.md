---
name: lc_amazon_market_research
description: 通过用户访问校验后，输入本地卖家精灵市场调研 Excel（近30天竞品表、近12个月竞品月表、头部ASIN关键词反查表、核心关键词转化率表），创建 market_project_<YYYYMMDD_HHmmss>/ 项目目录，在 market_research/ 下生成 Amazon 市场主报告、辅助分析 Excel、单文件 HTML 看板、运行日志和 project_manifest.json，并可在主报告后追加 Top10 品牌/卖家外部调研。用于用户已经准备好 Excel 文件、需要做市场规模、趋势、垄断度、广告压力、基础透视、规则结论、头部品牌/卖家公开信息推断分析的场景；不负责浏览器采集、商品维度打标或多维机会深挖。
---

# Amazon Market Research

> 最近更新：2026-07-30 23:42（UTC+8）

本 skill 用本地 SellerSprite / 卖家精灵 Excel 导出文件生成市场主报告。执行前必须联网完成一次不扣积分的用户访问校验；通过后，主报告的数据处理和生成全部在本地执行。主报告完成后，可按固定流程追加“头部品牌/卖家外部调研”。外部调研属于公开信息推断，不是尽调结论。

支持站点：`US`、`UK`、`DE`、`FR`、`JP`、`AU`、`CA`、`IT`、`ES`、`MX`。用户输入 `GB` 时统一按 Amazon 英国站 `UK` 保存。

## 使用方式

1. 先读 `INSTRUCTIONS.md`。
2. 按平台选择 Go CLI：Windows 用 `tools/bin/market-research-windows-amd64.exe`；Linux 用 `tools/bin/market-research-linux-amd64`；macOS Intel 用 `tools/bin/market-research-darwin-amd64`；macOS Apple Silicon 用 `tools/bin/market-research-darwin-arm64`。macOS 首次运行前默认按 `INSTRUCTIONS.md` 执行 `chmod +x` 和 `xattr -d com.apple.quarantine` 预处理。
3. 读取 `config.json`，调用所选 CLI 的 `auth-check`。校验失败、Token 缺失、账户停用、余额不足或校验服务不可用时立即停止，不读取输入、不创建项目目录、不运行分析命令。
4. 校验通过后，让用户确认目标 Amazon 站点，并提供本次调研 Excel 所在文件夹，或四类 Excel 文件。
5. 调用所选 CLI 的 `inspect-inputs` 识别文件类型、文件名站点、核心关键词和主类目；文件名站点只用于核对，后续 `run --marketplace` 必须使用用户确认的站点。
6. 在当前工作目录创建本次任务的 `market_project_<YYYYMMDD_HHmmss>/` 项目目录，主报告写入 `market_research/`。
7. 调用所选 CLI 的 `relevance-workspace` 生成硬规则清洗后的全量 listing 相关性工作区；agent 必须给每个 ASIN 标 `related` / `irrelevant` / `uncertain`，再用 `relevance-exclusions` 导出 `agent_exclude_asins.csv`。只有 `irrelevant` 会被剔除。
8. 调用所选 CLI 的 `run` 把所有产物写入 `market_research/`；其中 `cleaned_30d_listings.json` 是硬规则清洗和 agent 明显不相关 ASIN 剔除后给后续机会深挖使用的有效 listing 样本，项目根目录的 `project_manifest.json` 是下一段 skill 的精准入口。
9. 主报告完成后必须询问一次：`主报告已完成。是否继续联网调研 Top10 品牌/卖家，并追加到同一个 HTML 看板里？` 未得到明确同意时停在主报告，不自动联网。
10. 用户明确同意后，调用所选 CLI 的 `external-targets` 生成 Top 品牌/卖家调研对象，按对象逐个联网搜索并写入固定 JSON，再调用 `attach-external` 追加到同一个 HTML。
11. 让用户直接打开 `market_research/市场调研报告看板.html`，不要启动本地服务。
12. 按 `INSTRUCTIONS.md` 固定顺序解读，不新增文档未定义的指标或互动流程。

## 资源

- `references/input_contract.md`：输入 Excel 文件和字段要求。
- `references/calculation_spec.md`：指标、透视和规则结论口径。
- `config.json`：用户访问校验配置；`backend_token` 由用户填写。
- `tools/market_report_template.html`：本地 HTML 看板模板。
- `tools/bin/market-research-windows-amd64.exe`：Windows x64 CLI。
- `tools/bin/market-research-linux-amd64`：Linux x64 CLI。
- `tools/bin/market-research-darwin-amd64`：macOS Intel CLI。
- `tools/bin/market-research-darwin-arm64`：macOS Apple Silicon CLI。
