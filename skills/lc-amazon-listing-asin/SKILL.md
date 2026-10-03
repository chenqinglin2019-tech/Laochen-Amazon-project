---
name: lc-amazon-listing-asin
description: 输入目标站点、竞品 ASIN 和真实产品资料，生成兼顾 A9 关键词覆盖、COSMO 意图和 Alexa for Shopping 问答的多语言 Amazon Listing 与主附图/A+ 策划；支持单品及父子体，交付 Markdown、JSON 和完整 HTML 报告。
---

# 易逊-Listing文案生成

按 [INSTRUCTIONS.md](INSTRUCTIONS.md) 执行完整流程；字段定义见 [knowledge/data_contract.md](knowledge/data_contract.md)，数字预算见 knowledge/quality_policy.json。

## 快速指引

1. 先确定站点和语言，锁定完整核心品名、真实参数、子体清单和 intent_map（用途/人群/场景/地点/季节/搭配等已确认关系）。
2. 扩词加 `--reuse-days 7`；筛词读 03_keyword_view.tsv，用意图组判定 + `keyword_quality.py apply` 填逐词账本，再 check/export。三类词池与全部校验不变，不做剔除词二轮复核。
3. US 公制自动换成 in/ft、oz/lb、fl oz/gal；按英尺销售的品类设 `preferred_unit`。
4. QA 请求词 ≤8 个；非 US 跳过 qa，但仍完成问答覆盖矩阵。
5. 文案：标题 ≤75 字符并尽量用满，Highlight ≤125，五点每条约 150–250 字符，后台词按站点字节预算用满且不重复标题词，另给后台属性建议。写完跑一次 `keyword_quality.py coverage`，最多改进一轮，再用 `--write-placement` 生成实际投放计划。
6. 图片：单品/系列共用 1 主图＋6 附图＋至少 5 张 A+ 图片；系列另出逐子体方案（外观相同且仅尺寸/数量不同时仅主图独立）。
7. 验收顺序：local check → backend（自动复用未变子体）→ review-template（保留未变 target 的结论）→ 语义复审 → 最终 check → render。全局最多修复 2 轮。
8. 固定交付 07_listing.md、07_listing.json、report.html；HTML 沿用七章节版式。

## 后端凭据

统一经 `scripts/backend_cli.py` 调用 tools/bin 中的 CLI：自动从本 Skill 的 config.json 读取 `backend_url/backend_token`，注入子进程环境变量 `LAOCHEN_BACKEND_URL/LAOCHEN_BACKEND_TOKEN` 并脱敏输出。无需手工 export，不要另写带凭据的命令。缺 token 时停在请求前，不阻止本地整理。

后端请求前按 [联网权限与恢复](INSTRUCTIONS.md#联网权限与恢复) 检查当前宿主网络权限；确有阻断时走宿主授权入口。连接失败不判定为 token 无效或成功零结果；权限恢复后仍先核对请求状态，再有界续跑。

## 对话自动填写鉴权 token

发布目录直接提供 backend_url 为 https://mcp.yixunkuajing.com、backend_token 留空的 config.json，不使用 config.example.json。用户在对话中明确提供本 Skill 的鉴权 token 后，在任何后端请求前自动调用 scripts/configure_credentials.py，将标准输入 JSON 的 backend_token 写入本 Skill 的 config.json；保留 backend_url 和其他字段。无需用户手工编辑文件或 export 环境变量。缺 token 时一次说明缺少鉴权 token，收到后填写并继续原流程。

通过工具的标准输入传递 JSON，禁止把 token 嵌入 shell 命令、命令行参数或临时脚本；不回显、不放入报告、日志或 Git。脚本原子写入、Unix 权限为 0600，拒绝空值、控制字符和符号链接，输出只有成功状态与文件名。之后由 backend_cli.py 从 config.json 读取并注入 CLI 子进程；服务端仍检查 token 有效性、账号权限和额度，失败保留原脱敏处理，不绕过授权、不自动重试。

本 Skill 的外部调用统一经过后台 CLI，没有直接读取第三方 API key 的 .env 路线；不得创建无调用入口的 .env、猜测 API 字段，或将第三方 API key 当成 backend_token。用户提供第三方 key 时明确说明支持范围，使用支持该来源的 Skill。
