---
name: lc_amazon_listing
description: 输入目标站点 + 产品图片/描述 + 卖家精灵关键词反查 Excel，生成对应站点语言的 Amazon listing。支持 US/JP/UK/DE/FR/IT/ES/CA/IN；关键词解析纯本地，Rufus 问答仅 US 走后端。
---

# Amazon Listing Skill v2

完整指令在 `INSTRUCTIONS.md`，请先阅读它再开始工作。

## 快速指引

1. 读 `INSTRUCTIONS.md` —— 完整流程（步骤 0-8）、交互引导、约束
2. 读 `knowledge/site_language_rules.yaml` 和 `knowledge/distilled/*.yaml` —— 站点语言与写作规则
3. 读 `knowledge/examples/*.json` —— 好坏对照示例
4. 用 `tools/bin/laochen-cli-v2-linux-amd64` —— CLI 工具

## 环境变量

- `LAOCHEN_BACKEND_URL`：后端地址（US qa / 全站点 validate 需要）
- `LAOCHEN_BACKEND_TOKEN`：访问 token（US qa / 全站点 validate 需要）

`parse-keywords` 命令纯本地执行，不需要环境变量。
