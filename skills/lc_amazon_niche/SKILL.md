---
name: lc_amazon_niche
description: 批量输入飞鱼最新细分市场名称，拉取核心指标并按卖家类型评分排序，帮助筛选更容易切入的市场。
---

# 易逊-细分市场优选

细分市场评分工具。输入 niche 名称 → 后端拉指标 → CLI 本地评分 → Agent 解读。

## 快速指引

1. 读 `INSTRUCTIONS.md` — 完整流程
2. 看 `scoring/*.yaml` — 评分配置（可调阈值）
3. 用 `tools/bin/amazon-niche-choice-v3-*` — CLI 工具

## 环境变量

- `ANC_BACKEND_URL`：后端地址
- `ANC_BACKEND_TOKEN`：访问 token
- `ANC_SKILL_DIR`：Skill 目录（CLI 找 scoring YAML 用）
