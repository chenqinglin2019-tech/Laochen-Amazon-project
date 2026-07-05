# Report Schema

Use this JSON shape for `scripts/build_zhihuiya_report.py` and `scripts/feishu_writeback.py`.

```json
{
  "product": {
    "title": "",
    "sku": "",
    "asin": "",
    "marketplace": "",
    "source_image": ""
  },
  "feishu": {
    "app_token": "",
    "table_id": "",
    "record_ids": [],
    "risk_field": "专利",
    "pdf_field": "专利pdf"
  },
  "zhihuiya_evidence": [
    {
      "task_url": "",
      "search_mode": "appearance/design image search",
      "selected_jurisdiction": "",
      "status": "executed",
      "result_count": "",
      "screenshot_paths": [],
      "candidates": [
        {
          "record_number": "",
          "title_or_article": "",
          "country": "",
          "rank": 1,
          "similarity_score": null,
          "similarity_note": "",
          "screenshot_path": "",
          "official_verification": {
            "status": "not_checked",
            "source": "",
            "url": "",
            "notes": ""
          }
        }
      ],
      "notes": ""
    }
  ],
  "conclusion": {
    "risk_value": "",
    "confidence": "",
    "core_reasons": []
  },
  "outputs": {
    "report_md": "",
    "report_pdf": "",
    "findings_csv": ""
  },
  "writeback": {
    "status": "",
    "pdf_file_token": "",
    "updated_record_ids": []
  }
}
```

## Risk Values

Write exactly one of these values to Feishu by default:

- `高`
- `中`
- `低`

The field names are configurable. If a user wants different values, pass them through script arguments or adjust the evidence JSON before writeback.
