---
name: lc_amazon_competitor_promotion
description: 输入本地西柚找词“流量得分趋势”Excel 文件夹（1-10 个竞品 ASIN，同一站点、近一年日维度），先识别和校验 ASIN、站点、日期范围、价格促销、评分评论、自然/广告流量和新增广告活动字段，再生成亚马逊竞品推广手段拆解报告；商品画像、销量预测、Woot、上架时间和类目背景由 skill 内置 CLI 自动补充，agent 不要求用户提供除西柚目录之外的额外数据。适用于用户已从西柚下载竞对流量最大的子体近一年流量日趋势表，需要分析竞品价格、促销、广告、评价、销量、Woot、样本内季节性和动作有效性的场景；用户明确继续时，可基于公开网页证据追加站外推广溯源章节。
---

# Amazon Competitor Promotion

本 skill 用于生成《竞争对手运营手段拆解与总结报告》。核心输入是用户本地准备好的西柚找词“流量得分趋势”Excel 文件夹；商品画像、销量预测、Woot、上架时间和类目背景由 CLI 自动补充，不要求用户提供除西柚目录之外的额外数据。默认最终交付为单文件 HTML 报告；用户明确要求继续站外溯源时，可追加公开站外促销证据到同一个 HTML。

## 使用方式

1. 先读 `INSTRUCTIONS.md`。
2. 开场只要求用户提供一个本地文件夹，文件夹内放 1-10 个竞品 ASIN 的西柚“流量得分趋势”Excel。
3. 按平台选择 Go CLI：Windows 用 `tools/bin/competitor-promotion-windows-amd64.exe`；Linux 用 `tools/bin/competitor-promotion-linux-amd64`；macOS Intel 用 `tools/bin/competitor-promotion-darwin-amd64`；macOS Apple Silicon 用 `tools/bin/competitor-promotion-darwin-arm64`。macOS 首次运行前按 `INSTRUCTIONS.md` 处理 `chmod` 和 quarantine。
4. 调用 CLI 的 `inspect-inputs <目录>`，识别文件、ASIN、站点、日期范围、字段完整性。
5. 只有输入识别为 `ready` 后，才继续运行 `run`：本地解析西柚表、自动补充商品画像和销量/Woot 等数据、计算价格/促销/广告/评价/Woot 动作、弱风险和样本内季节性，并生成单文件 HTML 报告。
6. 如果用户在主报告后明确要求继续站外推广溯源，读取 `references/offsite_research_contract.md`，逐 ASIN 搜索公开网页证据，写入 `offsite_research_filled.json` 后运行 `attach-offsite` 追加 HTML。

## 资源

- `references/input_contract.md`：用户需要准备的文件、字段、目录规则。
- `references/supplemental_data_contract.md`：自动补充数据所需字段和禁止覆盖边界。
- `references/offsite_research_contract.md`：站外公开促销证据的搜索范围、JSON 契约和追加命令。
- `tools/bin/`：跨平台 Go CLI。
