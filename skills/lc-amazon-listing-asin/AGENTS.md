# Amazon Listing ASIN Agent（通用 agent 入口）

完整流程见 `INSTRUCTIONS.md`（平台无关的核心定义），字段见 `knowledge/data_contract.md`，数字预算见 `knowledge/quality_policy.json`。先确定目标站点和文案语言，再开始产品画像。

## 工具

- `scripts/backend_cli.py`：expand / qa / validate 的唯一入口；从 config.json 读取凭据、选择平台 CLI（`tools/bin/laochen-cli-*`）、脱敏输出；支持 expand 结果复用和 QA 请求词上限。
- `scripts/keyword_quality.py`：prepare / view / apply（意图组判定）/ check / export / rebind / coverage。
- `scripts/listing_quality.py`：normalize（单位）/ check / review-template / backend / prepare。
- `scripts/render_listing.py`：从 JSON 生成 07_listing.md 与 report.html。
- `knowledge/distilled/*.yaml`、`knowledge/site_language_rules.yaml`：写作规则；`knowledge/style_snippets.md`：写法参考；`knowledge/examples/*.json` 仅供测试。

修改脚本后运行 `python3 -m unittest discover -s tests`。语义判断不能伪装成确定性程序保证。

用户明确提供本 Skill 的鉴权 token 时，用 scripts/configure_credentials.py 从标准输入接收并保存，随后使用 backend_cli.py；凭据禁止回显或进入版本库。

后端请求前与失败后遵循 INSTRUCTIONS.md 的“联网权限与恢复”；区分连接、HTTP 鉴权与 JSON 格式错误，不以搜索/MCP 可用推断 CLI 可联网，不盲目重提未知请求。
