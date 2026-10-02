# Amazon Listing 用户表格版 Agent（通用 agent 入口）

完整流程见 `INSTRUCTIONS.md`（平台无关的核心定义），字段见 `knowledge/data_contract.md`，数字预算见 `knowledge/quality_policy.json`。先确定目标站点和文案语言，再开始产品画像。

## 工具

- `scripts/import_keywords.py`：本地完整导入用户 XLSX/CSV/TSV（保留全部行列与来源，不预筛、不截断；终端只输出汇总）。
- `scripts/backend_cli.py`：qa / validate 的唯一入口；从 config.json 读取凭据、选择平台 CLI（`tools/bin/laochen-cli-v2-*`）、脱敏输出；QA 请求词上限 8。
- `scripts/keyword_quality.py`：prepare / view / apply（意图组判定）/ check / export / rebind / coverage。
- `scripts/listing_quality.py`：normalize（单位）/ check / review-template / backend / prepare。
- `scripts/render_listing.py`：从 JSON 生成 07_listing.md 与 report.html。
- `knowledge/distilled/*.yaml`、`knowledge/site_language_rules.yaml`：写作规则；`knowledge/style_snippets.md`：写法参考；`knowledge/examples/*.json` 仅供测试。

修改脚本后运行 `python3 -m unittest discover -s tests`。与 asin 版共用的文件改动后，用上一级目录的 `sync_shared.py` 同步并检查。语义判断不能伪装成确定性程序保证。

用户明确提供本 Skill 的鉴权 token 时，用 scripts/configure_credentials.py 从标准输入接收并保存，随后使用 backend_cli.py；凭据禁止回显或进入版本库。
