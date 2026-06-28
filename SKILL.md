---
name: lc-amazon-listing-asin
description: 输入竞品 ASIN 列表（1-20 个，整组）+ 用户产品图片/描述，后端调用 SellerSprite 扩词并生成符合 Amazon 新规则的 listing（标题 / 商品亮点 / 五点 / 长描 / 后台搜索词 / 附图策划 / A+策划）。涉及外部能力（SellerSprite 扩词 / Rufus 问答 / 校验）一律走统一后端。
---

# Amazon Listing ASIN Skill

完整指令在 `INSTRUCTIONS.md`，请先阅读它再开始工作。

## 快速指引

1. 读 `INSTRUCTIONS.md` —— 完整流程、输出目录、约束
2. 读 `knowledge/distilled/*.yaml` —— 写作规则（标题 / 商品亮点 / 五点 / 长描 / 搜索词）
3. 读 `knowledge/examples/*.json` —— 好坏对照示例
4. 用 `tools/bin/laochen-cli-<platform>` —— CLI 工具

## 环境变量

- `LAOCHEN_BACKEND_URL`：后端地址
- `LAOCHEN_BACKEND_TOKEN`：访问 token

`expand` / `qa` / `validate` 都需要后端环境变量。
