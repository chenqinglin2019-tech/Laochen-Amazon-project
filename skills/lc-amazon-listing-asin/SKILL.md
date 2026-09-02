---
name: lc-amazon-listing-asin
description: 输入目标站点、竞品 ASIN 与产品资料，扩展关键词并生成对应站点语言的 Amazon Listing，支持多个站点。
---

# 易逊-Listing文案生成

完整指令在 `INSTRUCTIONS.md`，请先阅读它再开始工作。

## 快速指引

1. 读 `INSTRUCTIONS.md` —— 完整流程、输出目录、约束
2. 读 `knowledge/site_language_rules.yaml` 和 `knowledge/distilled/*.yaml` —— 站点语言与写作规则
3. 读 `knowledge/examples/*.json` —— 好坏对照示例
4. 用 `tools/bin/laochen-cli-<platform>` —— CLI 工具

## 环境变量

- `LAOCHEN_BACKEND_URL`：后端地址
- `LAOCHEN_BACKEND_TOKEN`：访问 token

`expand` / `validate` 以及 US 的 `qa` 需要后端环境变量；非 US 不调用 `qa`。
