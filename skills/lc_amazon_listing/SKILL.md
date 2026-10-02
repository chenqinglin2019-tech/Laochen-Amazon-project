---
name: lc_amazon_listing
description: 基于用户提供的卖家精灵关键词表格（本地完整导入，不调用云端扩词）、目标站点和真实产品资料，生成兼顾 A9 关键词覆盖、COSMO 意图和 Alexa for Shopping 问答的多语言 Amazon Listing 与主附图/A+ 策划；支持单品及父子体，交付 Markdown、JSON 和完整 HTML 报告。
---

# 易逊-Listing文案生成（用户表格版）

按 [INSTRUCTIONS.md](INSTRUCTIONS.md) 执行完整流程；字段定义见 [knowledge/data_contract.md](knowledge/data_contract.md)，数字预算见 knowledge/quality_policy.json。

## 快速指引

1. 先确定站点和语言，锁定完整核心品名、真实参数、子体清单和 intent_map（用途/人群/场景/地点/季节/搭配等已确认关系）。
2. 用 `scripts/import_keywords.py` 本地完整导入用户 XLSX/CSV/TSV（不截断、不预筛，终端只看汇总）；筛词先 `view --clusters`，读 03_keyword_view.tsv，用意图组判定 + `keyword_quality.py apply` 填逐词账本，再 check/export。三类词池与全部校验不变，不做剔除词二轮复核。
3. US 公制自动换成 in/ft、oz/lb、fl oz/gal；按英尺销售的品类设 `preferred_unit`。
4. QA 请求词 ≤8 个；非 US 跳过 qa，但仍完成问答覆盖矩阵。
5. 文案：标题 ≤75 字符并尽量用满，Highlight ≤125，五点每条约 150–250 字符，后台词按站点字节预算用满且不重复标题词，另给后台属性建议。写完跑一次 `keyword_quality.py coverage`，最多改进一轮，再用 `--write-placement` 生成实际投放计划。
6. 图片：单品/系列共用 1 主图＋6 附图＋至少 5 张 A+ 图片；系列另出逐子体方案（外观相同且仅尺寸/数量不同时仅主图独立）。
7. 验收顺序：local check → backend（自动复用未变子体）→ review-template（保留未变 target 的结论）→ 语义复审 → 最终 check → render。全局最多修复 2 轮。
8. 固定交付 07_listing.md、07_listing.json、report.html；HTML 沿用七章节版式。

## 后端凭据

qa/validate 统一经 `scripts/backend_cli.py` 调用 tools/bin 中的 laochen-cli-v2：自动从本 Skill 的 config.json 读取 `backend_url/backend_token`，注入子进程环境变量 `LAOCHEN_BACKEND_URL/LAOCHEN_BACKEND_TOKEN` 并脱敏输出。无需手工 export，不要另写带凭据的命令。缺 token 时停在请求前，不阻止本地整理。
