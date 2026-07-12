# 促销语义映射契约

西柚的 `Subscribe`、`Coupon`、`Promotion`、`Other` 可能包含满额、买多件、会员条件、多优惠并列和带金额门槛的自然语言。不得用“抓第一个数字”的脚本直接计算最后成交价。

## 固定流程

1. CLI 从全部 Excel 中按四个字段的完整组合去重，生成 `promotion_semantic_workspace.json`。
2. Agent 逐个阅读 `signatures`。相同组合只判断一次，不重复审核每天相同的文本。
3. Agent 复制工作区里的 `mapping_template`，填写后另存为 UTF-8 `promotion_semantic_map.json`。
4. `run --promotion-map ...` 校验全量覆盖并计算最后成交价。

不得跳过未识别项，不得用正则或关键词脚本替 Agent 完成语义判断。可以用结构化写文件工具落盘，但结论必须来自 Agent 对完整促销组合的阅读。

模板里的初始 `status=pending` 不能直接用于 `run`。Agent 必须把每一条改为下列四种最终状态之一，并填写具体 `evidence`；CLI 会拒绝任何残留的 `pending`。

## 映射格式

```json
{
  "version": 1,
  "mappings": [
    {
      "signature_id": "promo_xxxxxxxxxxxxxxxx",
      "status": "parsed",
      "usable_for_final_price": true,
      "subscribe": {"type": "none", "value": 0, "apply": false},
      "coupon": {"type": "percent", "value": 10, "apply": true},
      "promotion": {"type": "none", "value": 0, "apply": false},
      "other": {"type": "none", "value": 0, "apply": false},
      "evidence": "Coupon 明确表示当前单件价格再减 10%。"
    }
  ]
}
```

`status` 只能是：

- `parsed`：语义明确，并完成结构化映射。
- `not_applicable`：是满额、买多件、特定会员等条件优惠，不能直接用于当前单件价格。
- `ambiguous`：优惠叠加或适用条件无法确认。
- `no_discount`：文本存在，但不构成可量化扣减。

扣减字段：

- `type=none`：`value=0` 且 `apply=false`。
- `type=percent`：`value` 使用 0-100，例如 15 表示 15%。
- `type=amount`：`value` 使用美元金额。

## 判断边界

- `Buy $99, Save 30%` 是消费门槛优惠，不等于单件直接减 99% 或 30%；默认 `not_applicable`，除非完整文本明确证明当前单件满足门槛。
- `Subscribe` 有值时走 Subscribe 分支，不再叠加 Coupon。
- `Promotion` 和 `Other` 只有明确可与主优惠叠加时才设 `apply=true`。
- 多个优惠互斥关系不清、适用数量不清或会员资格不清时，`usable_for_final_price=false`。
- `evidence` 必须用一句中文解释判断依据，不能只写“已解析”。
- CLI 会拒绝缺少 signature、重复 signature、非法类型、负数折扣、百分比大于 100，以及计算后价格小于等于 0 的映射。
