# 输入、输出与本地持久化

版本：`schemaVersion:"1.0"`。使用 `examples/input-template.json` 建草稿，两个 case 文件仅用于结构参考和验收，不能将它们的零值、资格或费率用到真实测算。

## 顶层对象

- product：site、currency、asin（10 位字母数字）、childConfirmed、title、unitsPerSale（包装内实物件数）、price、priceIncludesDiscounts、goodsType、feeCategory、packaging.cm（三个正厘米值）、packaging.kg。可附原始单位字段、商品净重和商品尺寸，但只使用包装字段计算。
- scenario：calculationDate、shipDate、entryDate、exitDate（null 时按库龄推导）、ageDays、purchaseCny、adRatio（0.1=10%）、adTax、returnRate、unsellableRatio、channel。需要时 monthlyShipments、dateBoundaryConfirmedAt、adInput。
- sellerProfile：localFba=true、salesPlan=professional/individual、taxMethod=general/simplified/confirmedActual。依规则加入 establishment、entityType、vatRegistered、canRecoverInputTax、importerQualification 等必要资格，绝不填完整税号。
- logistics：固定 express / air / fastSea / slowSea 四个 key，每个有 active/pending/excluded 状态；excluded 必须 reason、confirmedAt。
- ruleSnapshot：id、fx、rules；可附 createdAt、发布 / 生效证据、站点验收状态。
- provenance：product、price、packaging、purchase、advertising、returns、inventory、taxProfile、costBoundary 九类必要来源；可加逐字段来源。
- feeReview：见下方核对清单。extraFees：独立补充费用数组，确无项目才为空。
- assumptions：`[{text,confirmedAt,scope,source}]`，必须是用户明确接受的假设。history：覆盖历史数组。
- editableParameters（可选）：`[{label,path,type,unit}]`，HTML 仅允许规则 expression 常数或 tax.rate、补充费用 expression 常数。只开放用户有权且可合理修改的值，修改后仍执行原 scope / binding 验证；不得藉此更改官方费率而冒充官方来源。
- savedScenarios（可选）：`[{name,at,input}]`，input 为完整输入，内部不要再次嵌套 savedScenarios。
- reportPreferences（可选）：`{targetMargin:"0.2"}`，表示用户自行设置的 20% 毛利目标；省略、null 或空字符串表示未设置，非空时范围为 0 至 1（不含 1）。此字段只影响目标比较与广告参考线，不改变 G；随导出和命名场景保存。禁止将演示目标作为真实任务默认值。

所有经营金额、汇率、比例建议使用十进制字符串。空值用 null，表示待补，绝不补零。计费单位数为正整数；库龄 / 时效使用非负整天。数组和对象没有静默默认，明确空数组表示没有对应独立项目。

## 来源与字段状态

每个 source 至少有 type（official/user/thirdParty/fixture）、locator（来源 URL、文档页码 / 单元格、用户消息位置）、at（获取或确认时间）。人工报价按 user；第三方商品详情按 thirdParty。`fixture` 只能出现在 fixture:true 的测试数据中。

关键字段来源可扩展 `{value,unit,rawValue,rawUnit,status,scope,original,overrideReason}`，status 区分 valid/missing/conflict/expired/acceptedEstimate。冲突和过期不得仅改为 valid 而不处理；保留旧值、当前值、确认时间。

引擎的基础验证只能检查结构和数值，不能证明来源真伪、资格有效或重复费用的业务语义。Skill 必须先核实输入，不得用伪造确认时间、虚构 URL 或 fixture 来源通过校验。

## FX

`{kind:"CNH",cnhPerCurrency:{CNY:"1",USD:"7.1",EUR:"7.8"},source,quoteTime,originalPair,chain}`。

示例数字仅展示结构。每种实际出现的币种必须有 >0 汇率。chain 记录交叉换算原始报价、乘除方向和时间。新测算取当前离岸报价；报告历史锁定。用户刷新生成新 id 和新文件。

## 规则对象

普通规则共有字段：

```json
{
  "status": "active",
  "site": "US",
  "currency": "USD",
  "validFrom": "2026-01-01",
  "validTo": "2026-12-31",
  "scope": {"product.feeCategory":"已核实收费类别"},
  "source": {"type":"official","locator":"真实规则来源及定位","at":"实际读取时间"},
  "expression": {"op":"mul","args":[{"ref":"price"},"实际确认费率"]},
  "tax": {"mode":"none"}
}
```

这不是可直接执行的真实规则。需要按 calculation.md 编译表达式。status 为 notApplicable 时须 reason；excluded 另需 confirmedAt 并标条件估算。关键 salesTax 不允许 excluded。人工费用 source.type=user 时绑定当前条件，纯常数不能通过 dynamic:true 绕过。

rules 必须包含 salesTax、commission、fulfillment、storage、inbound、importTax、otherTax、returnLoss、withholding；r=0 时 returnLoss 不参与计算，但仍应记录无退货发生的依据。

- salesTax expression 为每销售单位实际价内税额，不是税率。currency 必填；价外税填确认的零。
- importTax.covers 为 duty/importTax/customsLevy 税种数组，正额不能为空；各税种都未包含于 H 时才可在同条合并。混合包含范围时拆到独立条目并人工核对，不能让含税报价重复扣税。
- withholding.recoverable 为布尔值，预扣为零也明确其适用情况；其 tax.mode=none。
- storage 可为普通固定规则，或 `{mode:"monthly",periods:[规则]}`；periods 每条需 volumeCm3PerUnit。
- tax 为 `{mode:"none"}` 或 `{mode:"included|excluded",rate:"0.1",recoverable:false}`。真实比例必须来自适用规则 / 用户确认。
- acceptedExtension（可选）为 `{from,to,confirmedAt,reason}`；只能依据用户明确接受延用填写，保留原有效期。
- source 的 excerpt / location / qualification 保存适用证据，不能只摘金额。

## 物流报价

所有 active 报价共有：type、destination、goodsType、currency、source、validFrom、validTo。validTo=null 表示未注明，须 validityConfirmedAt。过期沿用须 acceptedExpired.confirmedAt 和理由；货物属性替代须 acceptedGoodsMismatch.confirmedAt 并标条件估算。

inclusions 固定七项 pickup、clearance、duty、importTax、lastMile、overseasAWD、insurance，值 included/excluded/passThrough。未含或实报实销的项目通过 resolvedComponents 指向对应内置 / 补充条目；服务归 H，税归 T。没有该成本必须用有确认依据的 notApplicable 费用条目，不以缺失代替。

每公斤报价 `mode:"perKg"`：

- boxes：`[{cm:[长,宽,高],kg:整箱毛重,units:每箱销售单位数,count:同型箱数}]`，支持混合箱型。
- pricePerKg；divisor 可省略使用类型默认值；compareScope / roundScope / minimumWeightScope / minimumChargeScope 为 box/shipment。
- roundStepKg、minimumWeightKg、minimumCharge：明确无此要求时为 "0"；dimShare 无分泡时为 "1"。
- surcharges：`[{id,expression,source,reason}]`。百分比基数必须依报价约定引用 freight/weight/boxCount/units。
- tax 表示物流费用服务税状态，不是进口税。includedImportTaxRecovery 以站点币种记，没有抵扣须用户确认零；正额须 importRecoveryEvidence.ownImporter=true、voucher=true，且非简易计税。
- packageEstimate（可选）：{confirmedAt,reason}，表示以单件包装估算外箱。

人工报价 `mode:"manual"`：manualRule 为完整 active 规则，expression 为确认的每销售单位头程金额；quote.currency 与 manualRule.currency 必须相同。绑定包装、数量、线路及适用日期；不要将每箱金额当每件输入。人工零头程是 active 的 "0"，不能用 notApplicable 绕过物流金额。

transitDays 可选，若有则按发货日加时效取入仓；quote.exitDate 可覆盖代表出库日。ruleOverrides 可按渠道覆盖 importTax、inbound 等规则，但不得覆盖无关费用来制造不可比口径。

## 补充费用

`{id,category,uniqueCostKey,reason,unit,rule,dateBasis,unitsPerShipment,allocationUnits}`。

category 是 H/M/F/S/I/T/O。uniqueCostKey 对应独立真实支出，不能用 commission 等内置键；同一支出不能以不同 ID 重复申报，编排层需检查原始凭证。替代原费用直接覆盖相应 rule 并保存 history。

unit：retained（留存单位）、shipped（发货单位）、inbound（入库单位）、shipment（每票，需 unitsPerShipment）、month（每月，需 scenario.monthlyShipments）、oneTime（一次性，需 allocationUnits 为分摊留存销量）、ratio（expression 已乘约定基数，输出每留存单位金额）。

dateBasis 为 ship/entry/exit，省略按 exit。monthlyShipments 的分母是发货量，引擎乘 keep 得月留存量。

## 费用核对清单

每个 feeReview 项目为 `{status:"included|notApplicable|excluded",reason,confirmedAt,itemId}`，included 需 itemId 对应实际条目：

mediaFee、individualPlan、peakDelivery、lowInventory、storageUtilization、agedInventory、inboundPlacement、inboundDefect、prepLabel、partneredCarrier、overseasAWD、digitalService、promotion、payoutFX、epr、serviceTax、importTax、withholding、returns。

只在真实不适用时标 notApplicable；尚未查询、资格不明不能如此处理。included 可指向合并了同类费用的主条目，但须在表达式说明中提供完整构成。

## 预设文件

使用 UTF-8 JSON 本地文件，格式 `{schemaVersion:"1.0",kind:"logistics|taxProfile|optionalFees|productHistory",id,match,validFrom,validTo,confirmedAt,source,data,history}`。

match 保存站点、线路、货物属性、报价包含范围及币种；productHistory 另须精确子 ASIN。读取多个匹配先让用户选择。过期或有效期未知需确认。税务预设每次回显确认；商品级历史每项待确认。合并顺序：本次用户输入 > 本次明确覆盖 > 确认后的同 ASIN 历史 / 匹配预设 > 展示型产品默认值。

预设写入必须先取得用户对可复用内容的确认；不存在预设不创建虚构默认。报告 history 保留覆盖项和理由。草稿用户部分回答时随时保存，下一轮只问仍缺的字段。

## 输出与兼容

calculate 输出 status、missingItems、metrics、totals、feeItems、assumptions、dates、sources、channel。CLI calculate 另附 scenarioResults（物流与敏感性）。金额字符串完整保存，展示不反写内部精度。

HTML 导出完整输入、规则、来源、历史、命名场景，重新导入后用共享引擎复算；不信任缓存的利润值。未知 schemaVersion 明确拒绝，不静默迁移。导入失败保留当前数据，最多 5 MiB。历史 JSON 原样备份，新版本另存。
