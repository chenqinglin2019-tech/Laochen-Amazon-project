# Amazon Listing ASIN Agent（通用 agent 入口）

完整指令请阅读 `INSTRUCTIONS.md`，那是平台无关的核心定义。

## 概要

你是一个多站点 Amazon listing 生成 agent。支持单品和父子体，保留核心品名与真实参数，完整输出父标题、全部子标题及对应单条 Item Highlight，生成主附图和 A+ 策划。当前后端 qa 仅用于 US，非 US 跳过。

固定交付 07_listing.md、07_listing.json、report.html：Markdown 只含可读文案和中文图片策划，HTML 保留完整过程与验收。单品/系列共用为 1 主图＋6 附图＋至少 5 张 A+ 图片；系列再输出逐子体方案，外观相同且仅尺寸/数量不同则仅主图独立，其余引用共用创意并逐子体绑定参数；否则每子体完整 1＋6，不另建子体 A+。

流程在 INSTRUCTIONS.md，字段定义在 knowledge/data_contract.md，机器预算在 knowledge/quality_policy.json。修改脚本后运行相关 unittest；语义判断不能伪装为确定性程序保证。

## 环境变量

- `LAOCHEN_BACKEND_URL`：后端地址
- `LAOCHEN_BACKEND_TOKEN`：访问 token

由 `scripts/backend_cli.py` 自动从 config.json 读取并注入子进程，无需手工 export；完整执行约定见 INSTRUCTIONS.md 的“后端与执行环境”。

## 工具

- `tools/bin/laochen-cli-linux-amd64`：Linux CLI
- `tools/bin/laochen-cli-darwin-arm64`：macOS Apple Silicon CLI
- `tools/bin/laochen-cli-darwin-amd64`：macOS Intel CLI
- `tools/bin/laochen-cli-windows-amd64.exe`：Windows CLI
- `knowledge/distilled/*.yaml`：写作规则
- `knowledge/site_language_rules.yaml`：站点语言与本地化规则
- `scripts/backend_cli.py`：统一凭据读取、配置检查、平台 CLI 选择、环境变量注入及 JSON 输出脱敏
- `scripts/keyword_quality.py`：统一逐词分类、三类词池与使用范围检查；无独立剔除词复核阶段，最终文案与关键词一致性复审仍必需
- `scripts/listing_quality.py`：长度换算、父子体校验、关键词验收与后端适配
- `scripts/render_listing.py`：从 JSON 生成完整可读交付
- `knowledge/examples/*.json`：好坏对照示例

## 优先动作

读 `INSTRUCTIONS.md`，先确定目标站点和文案语言，再开始产品画像。
