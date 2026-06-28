# 站外推广公开证据追加契约

该契约只在用户明确要求“继续站外推广溯源 / 联网查站外推广 / 追加站外证据”时使用。主报告生成阶段不要自动联网写入站外结论。

## 搜索范围

允许搜索：

- 公开 Facebook 帖子或公开搜索摘要。
- 公开 deal/coupon 网站、Woot、Slickdeals、Reddit、论坛、博客、零售同步页。
- 公开页面中能看到 ASIN、促销价、原价、coupon/code、折扣、发帖/活动时间之一的信息。

禁止当作稳定来源：

- 私密群组、必须登录后才能看的内容。
- 只能看到品牌词但不能确认 ASIN 的页面。
- 只有转卖、拍卖、二手/清仓痕迹，无法判断为推广动作的页面。
- 无法公开核验的个人猜测。

## 搜索方式

围绕主报告中的 ASIN 逐个搜索，优先使用这些 query：

```text
"<ASIN>" deal
"<ASIN>" coupon code
"<ASIN>" Facebook
"<ASIN>" Slickdeals
"<ASIN>" Woot
"<ASIN>" discount
```

如果页面能打开并看到时间/价格/code，置信度可以是 `medium` 或 `high`。如果只能看到搜索摘要，必须标记为 `low`，并在 notes 中写明“详情页未稳定打开，只按公开搜索摘要记录”。

不要把相对时间强行写成精确日期。可以写：

- `约 2026-03`
- `时间待核验`
- `2026-03-15`

并配套 `date_type`：

- `posted_at`
- `deal_start_at`
- `deal_end_at`
- `relative_snippet_date`
- `search_snippet_relative_or_hidden`
- `unknown`

## JSON 文件

把结果写到本次输出目录：

```text
offsite_research_filled.json
```

结构：

```json
{
  "summary": {
    "overall": "公开站外促销证据的整体判断",
    "coverage": "覆盖哪些 ASIN，哪些没找到",
    "timing": "时间证据是否精确",
    "limitations": "主要限制"
  },
  "events": [
    {
      "asin": "B0XXXXXXXX",
      "platform": "Facebook Group",
      "source_url": "https://...",
      "source_title": "页面标题或搜索摘要标题",
      "source_type": "search_snippet",
      "event_date": "约 2026-03",
      "date_type": "relative_snippet_date",
      "date_confidence": "low",
      "regular_price": "$17.99",
      "promo_price": "$10.79",
      "discount": "40% off",
      "coupon_code": "CODE123",
      "evidence_summary": "公开页面或搜索摘要中可见的关键证据",
      "action_type": "社群促销放单",
      "action_summary": "这条证据到底代表竞品在做什么动作；如果不确定可省略，CLI 会按平台、价格、code 和站内匹配结果自动补齐。",
      "confidence": "low",
      "matched_window": "unmatched",
      "notes": "详情页未稳定打开，只按公开搜索摘要记录。"
    }
  ],
  "limits": [
    "站外证据只辅助解释站内动作，不推翻西柚和自动补充数据形成的结构化结论。"
  ]
}
```

要求：

- `asin` 必须属于本次主报告。
- `source_url` 必填。
- `evidence_summary` 必填，必须写可见证据，不要写推测。
- `action_type` / `action_summary` 可选；如果填写，必须是对这条证据的动作解释，例如“折扣站促销”“社群促销放单”“站外价格线索”。不要在这里写尽调结论。CLI 会重新标准化或补齐这两个字段，HTML 以标准化后的动作总结为准。
- 不确定时间就写低置信，不要编造精确日期。
- 站外证据不要写入动作有效性结论，只作为独立追加章节。
- 如果某个 ASIN 没找到公开证据，在 `summary.coverage` 中说明。
- 如果所有 ASIN 都没找到公开证据，允许 `events: []`，但必须在 `summary.overall` 写明“未发现可公开核验的站外促销证据”。
- 写入 JSON 时必须使用 UTF-8；生成后检查不能包含 `???`。

`matched_window` 只能使用：

- `same_day`：与站内识别动作同日。
- `within_3d`：与站内识别动作相差 3 天内。
- `within_7d`：与站内识别动作相差 7 天内。
- `inside_sample_window`：站外时间在样本期内，但没有匹配到具体站内动作。
- `outside`：站外时间在样本期外。
- `unmatched`：时间不可核验或无法判断。

## 追加命令

写好 JSON 后运行：

```bash
<CP_CLI> attach-offsite --output-dir "/path/to/competitor_promotion_YYYYMMDD_HHMMSS" --research-json "/path/to/offsite_research_filled.json"
```

Windows：

```powershell
& ".\tools\bin\competitor-promotion-windows-amd64.exe" attach-offsite --output-dir "C:\path\to\output" --research-json "C:\path\to\output\offsite_research_filled.json"
```

成功后会更新同一个 HTML，并新增：

- `04_offsite_promotion_research.json`
- `offsite_promotion_sources.csv`
