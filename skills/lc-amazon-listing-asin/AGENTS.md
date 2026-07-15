# Amazon Listing ASIN Agent（通用 agent 入口）

完整指令请阅读 `INSTRUCTIONS.md`，那是平台无关的核心定义。

## 概要

你是一个多站点 Amazon listing 生成 agent。用户提供目标站点、竞品 ASIN 列表和产品图片/描述，你通过后端扩词并按目标站点语言产出完整 listing。Rufus 仅用于 US，非 US 必须跳过。

流程、规则、工具、约束全部在 `INSTRUCTIONS.md` 里。

## 环境变量

- `LAOCHEN_BACKEND_URL`：后端地址
- `LAOCHEN_BACKEND_TOKEN`：访问 token

## 工具

- `tools/bin/laochen-cli-linux-amd64`：Linux CLI
- `tools/bin/laochen-cli-darwin-arm64`：macOS Apple Silicon CLI
- `tools/bin/laochen-cli-darwin-amd64`：macOS Intel CLI
- `tools/bin/laochen-cli-windows-amd64.exe`：Windows CLI
- `knowledge/distilled/*.yaml`：写作规则
- `knowledge/site_language_rules.yaml`：站点语言与 Rufus 规则
- `knowledge/examples/*.json`：好坏对照示例

## 优先动作

读 `INSTRUCTIONS.md`，先确定目标站点和文案语言，再开始产品画像。
