---
name: lc_amazon_niche
description: 输入细分市场（niche）名称列表（最多 100 个），自动从数据库拉取 9 项指标并评分排序，帮助卖家找到最容易切入的细分市场。支持 4 种卖家 profile 个性化评分。
---

# Amazon Niche Choice v2

细分市场评分工具。输入 niche 名称 → 后端拉指标 → CLI 本地评分 → Agent 解读。

## 快速指引

1. 读 `INSTRUCTIONS.md` — 完整流程
2. 看 `scoring/*.yaml` — 评分配置（可调阈值）
3. 用 `tools/bin/amazon-niche-choice-v2-*` — CLI 工具

## 环境变量

- `ANC_BACKEND_URL`：后端地址
- `ANC_BACKEND_TOKEN`：访问 token
- `ANC_SKILL_DIR`：Skill 目录（CLI 找 scoring YAML 用）
