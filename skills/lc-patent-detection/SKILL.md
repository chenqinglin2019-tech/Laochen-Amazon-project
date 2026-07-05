---
name: Lc Patent Detection
description: Run a Wisdom Bud / PatSnap image-search patent workflow and write results back to the user's own Feishu/Lark Bitable. Use when Codex needs to process product rows or product images by using the user's configured Wisdom Bud account, capture candidate patent/design evidence, optionally attempt official-source verification, skip official checks that cannot be found, generate a concise report, upload it to Feishu, and update configured Feishu fields. Requires the recipient user to provide their own Wisdom Bud access and Feishu credentials/table mapping.
---

# Lc Patent Detection

Use this skill for one workflow only: use the user's own 智慧芽 / PatSnap account to search product-image patent/design candidates, generate evidence, and write the result back to the user's own Feishu/Lark Bitable.

## 云端使用权限门禁

开始读取产品行、打开智慧芽、生成 evidence、生成报告、上传 PDF 或写回飞书之前，必须先通过老陈云端鉴权。

这个门禁只验证当前用户是否允许使用本 skill。它不替代用户自己的智慧芽 / PatSnap 账号，也不替代用户自己的飞书 app、tenant token、表格配置。

用户 key 填在 `config.json`：

```json
{
  "backend_url": "https://mcp.yixunkuajing.com",
  "backend_token": ""
}
```

不要在对话、报告、日志里输出完整 key。

macOS 首次运行前，从 skill 根目录静默执行：

```bash
xattr -dr com.apple.quarantine tools/bin 2>/dev/null || true
chmod +x tools/bin/* 2>/dev/null || true
```

`scripts/` 里的 Python 入口会自动调用鉴权工具。如果鉴权失败、`backend_token` 缺失，或鉴权工具不存在，必须立即停止。不要打开智慧芽，不要生成 evidence，不要生成报告，不要写回飞书。只输出安全提示：

```text
云端鉴权未通过，本轮不继续执行。
```

## Data Handling

- Never put real Wisdom Bud accounts, Feishu app credentials, access tokens, table IDs, record IDs, private URLs, or local user paths into skill files.
- Treat accounts and table mapping as runtime configuration supplied by the user.
- Keep task evidence in the current task output folder.
- Treat this as seller operations screening, not a legal opinion.

## Required User Setup

The user who receives this skill must provide:

- Wisdom Bud / PatSnap login or an already logged-in browser session.
- Feishu/Lark app credentials or an existing authenticated Feishu API token.
- Feishu Bitable `app_token`, `table_id`, target record IDs, and field names.
- Product image field or local product image paths.
- Output field for patent risk, for example `专利`.
- Optional output field for report PDF attachment, for example `专利pdf`.

Read `references/feishu-writeback.md` before writing to Feishu.

## Workflow

1. Read the current product row or product input.
2. Build a task dossier: product title, MSKU/SKU when present, marketplace/site metadata, product image path, and any known patent/design/trademark number.
3. Read `references/zhihuiya-workflow.md`.
4. Use the user's Wisdom Bud / PatSnap access to run image search.
5. Use appearance/design image search first.
6. Upload only the product image for the current task.
7. Record each selected jurisdiction or result branch separately.
8. Save candidate numbers, titles/articles, countries, result URL, screenshots, and candidate-card screenshots.
9. If official-source verification is available, check candidate numbers. If an official source cannot find the candidate or cannot be accessed, mark that check as `skipped_not_found` or `access_limited` and continue.
10. Build `evidence.json` using `references/report-schema.md`.
11. Generate `report.md`, `findings.csv`, and optionally `report.pdf` with `scripts/build_zhihuiya_report.py`.
12. Write back the risk value and optional PDF attachment to Feishu with `scripts/feishu_writeback.py`.

## Risk Mapping

Use the strongest Wisdom Bud / PatSnap candidate evidence as the default risk signal:

- `高`: exact or near-exact visual match, similarity score `>=80`, or a candidate explicitly marked high risk.
- `中`: candidate exists but official status is skipped, unavailable, incomplete, or similarity is `60-79`.
- `低`: no meaningful candidate found, or candidates are unrelated / similarity `<60`.

Official-source failure does not block writeback. If a candidate is not found in an official source, keep the Wisdom Bud evidence, set official verification to `skipped_not_found`, and continue.

## CLI

Build a report from Wisdom Bud evidence:

```bash
python scripts/make_evidence_template.py \
  --title "Product title" \
  --source-image "<product-image-path>" \
  --record-ids "<record_id>" \
  --output evidence.json
```

```bash
python scripts/build_zhihuiya_report.py \
  --input evidence.json \
  --output-md report.md \
  --output-csv findings.csv \
  --output-pdf report.pdf
```

Write the result back to Feishu:

```bash
python scripts/feishu_writeback.py \
  --evidence-json evidence.json \
  --report-pdf report.pdf \
  --record-id "<record_id>" \
  --risk-field "专利" \
  --pdf-field "专利pdf"
```

Run a local queue:

```bash
python scripts/run_task_queue.py references/queue-example.json --output-dir queue-output
```

## Resources

- `references/zhihuiya-workflow.md`: Wisdom Bud / PatSnap search path and evidence capture method.
- `references/feishu-writeback.md`: generic Feishu/Lark Bitable configuration and writeback rules.
- `references/report-schema.md`: evidence JSON shape.
- `references/queue-example.json`: fake local queue example.
- `scripts/make_evidence_template.py`: create a blank evidence JSON for one product or Feishu row.
- `scripts/build_zhihuiya_report.py`: generate Markdown, CSV, JSON-derived risk, and optional PDF.
- `scripts/feishu_writeback.py`: generic Feishu/Lark upload and row update script.
- `scripts/run_task_queue.py`: sequential local runner.
