---
name: lc_amazon_listing
description: 基于用户提供的卖家精灵关键词表格、目标站点和真实产品资料，生成多语言 Amazon Listing 与主附图/A+策划；本地完整导入关键词，支持单品及父子体、三类词池、US Rufus 问题采集及非 US 跳过，交付 Markdown、JSON 和七章节 HTML 报告。
---

# 易逊-Listing文案生成（用户表格版）

先读 [INSTRUCTIONS.md](INSTRUCTIONS.md) 执行完整流程；字段定义见 [knowledge/data_contract.md](knowledge/data_contract.md)。

## 快速指引

1. 锁定完整产品核心名称、真实参数与子体清单；用 scripts/import_keywords.py 完整导入用户 XLSX/CSV/TSV 关键词表格，再分配关键词和购买意图。不需要竞品 ASIN，不调用云端扩词，也不使用旧 CLI parse-keywords 的预筛选结果。
2. 筛词先读 keyword_filter_rules，通过 scripts/keyword_quality.py prepare/check/export 维护可用、待评估、剔除三类词池，逐词记录完整意图与当前分类依据，禁止临时白名单批量删除；不再设置剔除词第二轮复核，保留最终文案与关键词一致性复审。读站点与相关写作规则；family 加读 variation_rules，图片/A+ 加读 image_planning_rules；来源在 knowledge/sources.json。
3. US 普通尺寸用 scripts/listing_quality.py 换算为英寸；文案、尺寸图和 A+ 共用展示值。
4. 多子体完整输出父体及每个子体标题和单条 Item Highlight，五点是独立字段。
5. 单品及系列共用方案均为 1 主图、6 附图、至少 5 张 A+ 图片；系列另出逐子体方案。外观一致且仅尺寸/数量不同，每子体只单独策划主图，附图/A+ 共用构图并绑定各自参数；其余情况每子体完整策划 1 主图和 6 附图，不另出子体 A+。
6. 本地检查、当前筛词审查、绑定当前文件的语义复审和后端业务校验均通过后完成；scripts/render_listing.py 从 JSON 生成纯文案 Markdown 和完整 HTML 报告，缺验收不能标通过。最终固定提供 07_listing.md、07_listing.json、report.html 三个链接。
7. HTML 严格沿用既定示例的七章节版式与简洁段落；不新增导航、验收面板或逐图技术字段列表。完整引用与校验保留在内嵌数据，页面只显示简短状态和必要待确认事项。

## 环境变量

- `LAOCHEN_BACKEND_URL`：后端地址
- `LAOCHEN_BACKEND_TOKEN`：访问 token

统一通过 `scripts/backend_cli.py` 调原 CLI：自动从本 Skill 的 config.json 读取凭据、检查缺失、注入子进程环境并脱敏输出，无需手工设置环境变量。`listing_quality.py backend` 已接入同一入口。非 US 跳过 qa；缺 token 时停止在后端请求前，不阻止本地资料整理。不要另写带凭据的命令或临时启动脚本。
