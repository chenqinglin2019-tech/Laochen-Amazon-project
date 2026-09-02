---
name: lc_amazon_competitor_promotion
description: 读取西柚流量趋势 Excel，拆解竞品价格、促销、广告、评价、销量及站外推广动作，生成 HTML 报告。
---

# 易逊-竞品推广手段拆解

本 skill 用于生成《竞争对手运营手段拆解与总结报告》。核心输入是用户本地准备好的西柚找词“流量得分趋势”Excel 文件夹；商品画像、销量预测、Woot、上架时间和类目背景由 CLI 自动补充，不要求用户提供除西柚目录之外的额外数据。默认最终交付为单文件 HTML 报告。站外溯源分两步：先由当前 Agent 免费检索公开网页；完成后再单独询问用户是否启用收费增强检索。两步结果都必须经过 Agent 证据判断和 CLI 校验后写入同一个 HTML。

## 使用方式

1. 先读 `INSTRUCTIONS.md`。
2. 开场只要求用户提供一个本地文件夹，文件夹内放 1-10 个竞品 ASIN 的西柚“流量得分趋势”Excel。
3. 按平台选择 Go CLI：Windows 用 `tools/bin/competitor-promotion-windows-amd64.exe`；Linux 用 `tools/bin/competitor-promotion-linux-amd64`；macOS Intel 用 `tools/bin/competitor-promotion-darwin-amd64`；macOS Apple Silicon 用 `tools/bin/competitor-promotion-darwin-arm64`。macOS 首次运行前按 `INSTRUCTIONS.md` 处理 `chmod` 和 quarantine。
4. 调用 CLI 的 `inspect-inputs <目录>`，识别文件、ASIN、站点、日期范围、字段完整性。
5. 只有输入识别为 `ready` 后，才按 `INSTRUCTIONS.md` 用系统时间创建唯一输出目录；禁止手填 `000000` 或示例时间。随后运行 `promotion-workspace`，读取 `references/promotion_semantics_contract.md`，逐个审核去重后的完整促销组合并生成 `promotion_semantic_map.json`。
6. 使用 `run --promotion-map ...`：本地解析西柚表、校验 Agent 促销语义映射、自动补充商品画像和销量/Woot 等数据、计算价格/促销/广告/评价/Woot 动作、弱风险和样本内季节性，并生成单文件 HTML 报告。
7. 如果用户在主报告后明确要求继续站外推广溯源，读取 `references/offsite_research_contract.md`，逐 ASIN 使用当前 Agent 的免费联网能力搜索公开网页证据，写入 `offsite_research_filled.json` 后运行 `attach-offsite`；精确日期证据会进入对应 ASIN 的站外轨和前后 3 天动作链。
8. 免费站外证据追加成功后，说明免费覆盖情况，并单独询问是否启用收费增强检索。只有用户明确同意后，才运行 `paid-offsite-workspace`。随后读取 `references/paid_offsite_merge_contract.md`，逐条判断收费候选是 `new / duplicate / enrich / conflict / reject`，最后运行 `merge-paid-offsite` 更新同一 HTML。没有明确同意时严禁调用收费命令。

## 资源

- `references/input_contract.md`：用户需要准备的文件、字段、目录规则。
- `references/promotion_semantics_contract.md`：促销组合的 Agent 语义映射格式、判断边界和 CLI 校验要求。
- `references/supplemental_data_contract.md`：自动补充数据所需字段和禁止覆盖边界。
- `references/offsite_research_contract.md`：站外公开促销证据的搜索范围、JSON 契约和追加命令。
- `references/paid_offsite_merge_contract.md`：收费增强的确认边界、逐条证据合并规则和 CLI 硬校验要求。
- `tools/bin/`：跨平台 Go CLI。
