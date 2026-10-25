# v2 数据契约

`examples/quick-shoe-bundle.json` 是真实 US 链接与本会话用户参数的例子，不能作为其他任务的默认经营值。`examples/quick-input-template.json` 是空缺项模板。旧 examples/case-* 均属 v1 人工验收。

## 采集 bundle

- `url`：完整受支持站点 ASIN URL。
- `raw`：详情工具返回 JSON、MCP content、data 包裹或规范化对象。
- `product`：可选页面/用户覆盖：price、category、variant、salesUnit、packQuantity、packaging `{cm:[长,宽,高],kg,basis:"package"|"proxy"}`。cm/kg 使用数值字符串。明确来源保存在 `fieldMeta`，页面补值应标 extracted，不误记用户确认。
- `user`：purchaseCny、returnRate、可选 adRatio/unsellableRatio/ageDays、channel、logistics。
- `logistics`：express、air、fastSea、slowSea、sea 中至少一项；值为元/kg数字或 `{pricePerKg,divisor,currency:"CNY"}`。头程和采购按**一个销售包装**；多件装不再次乘 packQuantity。
- 比例采用 0–1；returnRate 必须小于 1。采购 0、退货 0、报价 0 是明确数值，空字符串/null 是缺失。

## 准备后的 v2 input

`schemaVersion:"2.0"`、`kind:"screening"`、product、scenario、logistics、feePack、fx、fieldMeta、notes、excluded、source。asOf 是资料测算快照时间，**不是发货/入仓/出库日期**。

feePack 包括 site、revision、source/sources、checkedAt、effectiveFrom、可选 validUntil/invalidated、goodsTypes、commissions、fulfillment、storage、returns、salesTax。费用表达式使用旧引擎受限 JSON 运算，不执行字符串代码。

- fulfillment 为按优先级排序的明确档位，可带 categories/excludeCategories、maxCm/maxSumCm/maxKg/maxDimKg、minPrice/maxPrice/priceBelow、weightMode、divisor、roundStepKg、expression、returnProcessing、storageSize。
- storage 独立保存 low/peak、volumeCm3PerUnit、可选 category/size 范围，绝不按日历选一个季节。
- returns 表达式计算每次退货的费用，不包括货款本金、广告和不可售投资。未知适用门槛可以用有依据的保守处理费，带 estimated、source、note。
- 固定费用 overrides 支持 commission/fulfillment，必须给 source、note、bindings。佣金绑定 site/category/price；配送另绑定 packaging。采购、广告、退货改变不触发无关失效。超档或绑定变化返回缺项，不能继续使用旧金额。
- fx.kind 明确 CNY 或 CNH；`cnhPerCurrency` 为兼容字段名，含义“每单位当地货币折多少人民币”。公开默认汇率为 CNY，报告不冒称 CNH；允许已有有来源 CNH 快照覆盖。
- 不支持危险品/特殊税类时自动取对应规则，不把 ordinary 默认解释为已完成合规认定。

## 缓存与审定

`data/rates/{SITE}.json`、`data/fx.json` 是共享缓存。本次参数不可写回团队默认。缓存刷新失败保留原快照和检查日；已知 invalidated/validUntil 不可延用。

费率过 7 天后抓取 source/sources 比较 SHA-256。若有变更，保存 `data/pending/{SITE}.json`，Agent 打开来源核对、更新表达式与适用档位，再记录正确 checkedAt、sourceHashes、revision。不能把“抓取成功”当作“费表未变”。HTML 动态壳变化可触发人工 Agent 核对，这是保守行为，不是需要用户批准。

快照和费率不包含凭据、Cookie、API key。report/CLI 会拒绝敏感字段。
