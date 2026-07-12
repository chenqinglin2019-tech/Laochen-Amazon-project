# 收费增强站外证据合并契约

本契约只在以下条件全部成立时使用：

1. 免费公开网页检索已经完成并通过 `attach-offsite` 写入同一 HTML。
2. 用户已经看到免费覆盖情况。
3. 用户再次明确同意使用按实际调用次数计费的增强检索。

没有明确同意时严禁运行 `paid-offsite-workspace`。不要询问或处理第三方 token；CLI 只读取 Skill 自带的统一后端配置。

## 工作区

运行 `paid-offsite-workspace` 后，CLI 会自动提交异步任务并轮询到完成。不要重复提交，也不要让 Agent 手工拼接任务状态请求。命令成功后读取：

如果本地执行超时或中断且日志已给出 `task_id`，使用同一命令附加 `--task-id "原 task_id"` 恢复。禁止重新提交；恢复任务不会重复扣费。

```text
offsite_paid_merge_workspace.json
```

重点字段：

- `free_events`：已写入 HTML 的免费证据，每条带稳定 `event_id`。
- `calls`：本次实际调用能力、成功状态、结果数和成本留痕。
- `candidates`：收费增强返回的候选证据。
- `decision_template`：必须全量填写的判断模板。

原始云端返回另存为 `06_paid_offsite_enhancement.json`。不要修改该文件。

## 逐条判断

每个 `candidate_id` 必须恰好选择一种：

- `new`：免费结果中没有同一证据，且收费候选能形成可公开核验的新事件。
- `duplicate`：与某条免费证据表达同一个来源和同一个核心事实，不新增事件。
- `enrich`：与某条免费证据是同一事实，但补充了更完整正文、日期、价格、折扣或 code；用补强后的最终事件替换目标免费事件。
- `conflict`：与某条免费证据指向同一事实，但日期、价格、折扣、code 或动作含义冲突；两条都保留，并明确写出冲突。
- `reject`：不是目标 ASIN、不是推广证据、仅有泛品牌词、页面不可公开核验、二手转卖/拍卖，或信息不足以形成事件。

不得因为来源收费而自动选择 `new` 或提高置信度。必须阅读 `evidence_text`，并与同 ASIN 的 `free_events` 对照。

## 判断文件

把工作区的 `decision_template` 填入：

```text
offsite_paid_merge_decisions.json
```

结构：

```json
{
  "summary": {
    "overall": "免费与收费增强合并后的整体判断",
    "coverage": "覆盖和缺失情况",
    "timing": "精确日期证据情况",
    "limitations": "公开证据限制"
  },
  "decisions": [
    {
      "candidate_id": "候选 ID",
      "decision": "new",
      "reason": "为什么形成新证据",
      "event": {
        "asin": "B0XXXXXXXX",
        "platform": "Facebook",
        "source_url": "https://...",
        "source_title": "公开页面标题",
        "source_type": "social_post",
        "event_date": "2026-03-15",
        "date_type": "posted_at",
        "date_confidence": "high",
        "regular_price": "$19.99",
        "promo_price": "$14.99",
        "discount": "25% off",
        "coupon_code": "SAVE25",
        "evidence_summary": "页面实际可见的证据",
        "action_type": "社群促销放单",
        "action_summary": "公开帖在该日期发布 ASIN、促销价与优惠码",
        "confidence": "high"
      }
    }
  ],
  "limits": [
    "收费增强候选仍是公开网页证据，不是投放归因或尽调结论。"
  ]
}
```

字段规则：

- 所有判断都必须填写非空 `reason`。
- `duplicate`：必须填写同 ASIN 的 `target_event_id`；不得填写 `event`。
- `enrich`：必须填写同 ASIN 的 `target_event_id` 和补强后的完整 `event`。
- `conflict`：必须填写同 ASIN 的 `target_event_id` 和收费候选对应的完整 `event`；`reason` 必须具体说明冲突字段。
- `new`：必须填写完整 `event`，不得填写 `target_event_id`。
- `reject`：不得填写 `event` 或 `target_event_id`。
- `event.source_url` 必须来自该收费候选；`enrich/conflict` 时也允许保留目标免费事件 URL。
- 日期、价格、折扣、code 只能填写候选正文或摘要中实际可见的信息。
- 不要填写站内匹配、前后 7 天自然流量或组合动作字段，这些由 CLI 重算。
- JSON 必须是 UTF-8，且不能包含 `???`。

## CLI 校验和输出

运行：

```bash
<CP_CLI> merge-paid-offsite \
  --output-dir "/path/to/output_dir" \
  --workspace "/path/to/output_dir/offsite_paid_merge_workspace.json" \
  --decisions "/path/to/output_dir/offsite_paid_merge_decisions.json"
```

CLI 会校验候选全覆盖、决策枚举、目标事件、ASIN 和来源 URL，再生成：

- `07_paid_offsite_merge_decisions.json`：Agent 决策留痕。
- `offsite_research_merged.json`：免费与收费证据最终合并结果。
- 更新后的 `04_offsite_promotion_research.json`、CSV、Markdown 和同一个 HTML。

免费证据不得整体丢弃。`duplicate/reject` 不新增；`enrich` 只替换指定目标；`conflict` 同时保留两条；`new` 追加一条。
