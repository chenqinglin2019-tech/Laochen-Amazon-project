# 计算与规则编译

## 口径与分摊

主指标按最终未退款销售单位，所有费用转换为站点币种。`E=1 站点币种对应 CNH`，采购人民币 / E；外币报价按该币 CNH 值 / 站点币 CNH 值交叉转换。CNY 键仅代表采购人民币成本基数 1，不是把 CNY 市场报价当 CNH 汇率。

- R：成交价减实际缴纳的价内销售税；价外买家税对应销售税扣减为零。全额单一价内税可写 `price-price/(1+t)`；简易 / 复合税按实核规则表达。
- C：采购及包装、标签、送至货代交货点前国内支出。
- H：交货点至 FBA 仓的运输、清关服务、附加费、派送、中转、保险及分仓差额；已含进口税保留在 H，除非满足凭证抵扣。
- M：佣金、媒介交易费、个人计划按件收费。
- F：FBA 配送、旺季和低库存等配送附加费。
- S：基础仓储、仓储使用率和超龄库存附加费。
- I：入库配置、缺陷、计划外服务、预处理和贴标；承运人运输归 H。
- A：`R × adRatio`，输入可 >100%。若广告花费含服务税，按确认口径拆分净额与税。促销已含时不得再追加。
- T：物流未含的关税 / 不可抵扣进口税、不可抵扣费用服务税等。销售税和所得税预扣不入 T。
- O：确认的其他可选或补充成本。

每发货单位补充费用的留存部分入原类别，退货部分通过 D；每入库单位 / 每票摊销成本的报废部分进入已投入成本；每月 / 一次性费用按确认的留存销量直接分摊。

## 退货

`keep=1-r`，`D=r×L/keep`。

引擎自动构造 `L=returnLoss净额及不可抵扣税 + 每发货单位补充费用 + u×已投入成本`。已投入成本包括 C/H/I/S、未含头程的单位进口税及相关不可抵扣入库服务税、其他每入库单位成本。

**returnLoss 规则只写剩余退货费用**：不可退原配送费、净退款管理费、退货处理费、`u×移除或弃置费`、不可追回退货服务税、确认的再次入库仓储等。不得再次写 `u×invested`、退款本金、广告或全额采购 / 头程，否则重复计算。逐项税率不同的退货费用在公式中先按净损失合并，并保存明细来源；不能以统一税率强拆。

受销量 / 阈值影响时，先按官方条件算每月退货总费用，再除以 `monthlyShipments×r` 写为每退货单位费用；r=0 时引擎不执行退货规则。实际销量或阈值缺失则继续追问。

## 广告转换

使用 `normalizeAdvertising()`，留存口径固定后保持该 adRatio，不因之后调 r 重新按原分母转换。

- 比例：`A=ratio×(含税分母?price:R)/(已扣退款?1:keep)`，新 adRatio=A/R。
- ACOS：还需同口径广告销售占比，二者相乘后按上述转换；缺此数据不计算。
- 预算：同期广告预算 / 同期留存销量，再 / R。
- 退货敏感性对照使用 `adRatio基准×keep基准/keep新`，保持每发货单广告支出不变。负退货率或 r>=1 场景标无效，不裁剪。

## 受限 JSON 公式

金额和比例用十进制字符串，40 位有效数字运算；最终展示两位金额，JPY 零位，毛利率两位百分数。平台逐项舍入用显式 round，不因页面显示精度改变内部值。

- 常数：`"6.25"`；引用：`{"ref":"price"}`。
- 运算：`{"op":"add|sub|mul|div|min|max|ceilStep","args":[...]}`；sub/div 两参数，ceilStep 为值、步长。
- 舍入：`{"op":"round","args":[...],"places":2,"mode":4}`。mode 为 Decimal 舍入枚举，4=四舍五入、2=向正无穷取整、1=截断；必须据官方要求选择。
- 整段费率：`{"op":"tier","mode":"whole","base":{"ref":"price"},"bands":[{"upTo":"100","rate":"0.1"},{"upTo":null,"rate":"0.15"}]}`。upTo 为包含上限，null 为无上限。
- 累计费率：同结构 `mode:"progressive"`；最低费写外层 max，不能用整段费率代替累计。
- 多条件分档：`{"op":"select","rows":[{"when":{"weightKg":{"lte":"0.5"}},"value":"5"},{"when":{"weightKg":{"gt":"0.5","lte":"1"}},"value":"7"}]}`。必须恰好命中一行，重叠和缺档都失败。
- 条件支持精确相等及 gt/gte/lt/lte/eq/in；同一 when 各字段为 AND。复杂 OR 展开为互斥行。只执行这些操作符，不执行字符串代码、eval 或网络。

可用引用：`price,R,C,H,M,F,S,I,A,r,u,keep,invested,returnExtra,weightKg,longCm,midCm,shortCm,volumeCm3,ageDays`，以及 `product.* / scenario.* / sellerProfile.*`。引用必须在该费用计算时已存在：销售税只用价格与原始输入，佣金先于 F/I/S，退货最后计算；不能依赖尚未计算值。

FBA 需完整表达当地尺寸排序、重量 / 体积重、计费进位、售价计划和资格；使用独立费表条件。厘米、公斤转换成英寸 / 磅可在公式内用精确因子 2.54 / 0.45359237。不套物流体积系数。数字服务等附加费与原费用合并或独立同类别条目，非服务税。

## 日期与范围

每条规则有站点、有效期、资格范围、source、税价状态。佣金、配送、退货按代表出库日；入库与进口税按入仓日；头程按发货日；S 按实际库存区间切月和费率区间。

月仓储 `mode:"monthly",periods:[完整规则...]`；每条 expression 是单位体积每月费率，`volumeCm3PerUnit` 为该计费体积的 cm³（m³=1000000，ft³=28316.846592）。入仓日包含、出库日不包含，分母为当月实际天数。跨费率须记录 dateBoundaryConfirmedAt。

适用范围 scope 必须约束官方规则依赖的类别、商品属性、主体资格、价格和包装档位。合成案例 scope={} 只为测试，生产不能照抄。规则之外的价格 / 尺寸不外推。

人工固定费用采用保守绑定：product.site、product.asin、product.price、product.packaging、product.goodsType、product.feeCategory、sellerProfile、shipDate、entryDate、exitDate、scenario.purchaseCny、scenario.returnRate、scenario.ageDays 必须完整保存；若有不可再售比例或月销量，还须 scenario.unsellableRatio / scenario.monthlyShipments。其他实际依赖（例如人工运费的装箱资料、线路）也要加入。任何绑定变化后重新确认。对有明确可计算公式的用户报价可 `dynamic:true`，但纯常数金额仍不能绕过绑定。

F / M / H / I / S 引用表示内置基础费用，不包括 extraFees；补充费用的退货部分由引擎按 unit 自动分摊，勿在 returnLoss 再引用同一补充费用。此约束避免旺季等发货型附加费重复计入 D。

默认敏感性必须覆盖相邻官方档位，否则显示需要更新规则。允许用户确认未来沿用最近已知规则，但须填写 acceptedExtension 的 from/to/confirmedAt，保留原有效期并标条件估算。

## 物流

逐箱或整票比较实重 / 体积重；分泡时 `actual+max(0,vol-actual)×dimShare`，dimShare 是客户承担比例。依报价顺序进位、最低计费重、重量费用与最低收费、附加费、数量分摊、币种转换。

附加费公式可引用 freight（最低收费处理后基础运费）、weight、boxCount、units；明确报价的百分比基数。各项同币种；异币种附加费用在快照中先换算，保存换算链。quote.tax 拆服务税；已含可抵扣进口税以站点币种填写 includedImportTaxRecovery，附自身进口主体及抵扣凭证证明。

报价中 duty/importTax 已包含时，其他进口税规则 covers 不能再次覆盖同税种。未包含 / 实报实销边界必须在 resolvedComponents 指向实际费用条目（明确不发生可指向有依据的 notApplicable 规则）。

复杂的整票比较后逐箱进位、整票重量与逐箱最低收费分配、阶梯运价、每立方报价等，若当前 DSL 不足则使用严格绑定的人工每销售单位金额及外部算式证据。不硬套每公斤算法。

入库配置方案先分别构造 `I+H差额` 完整渠道方案，比较总毛利并选择符合条件的最低总成本；无法取得各方案头程差额时请用户指定，不擅选最低 I。多供应商保存独立命名场景，本次每渠道选择一个方案。

## 防重复与审核

替代已有费项：保留旧快照到 history，新规则覆盖同一 key，不能另外追加同义补充费。独立追加必须提供唯一支出标识和未含于原费用的理由。导入的标签不足以证明没有重复，编排层仍须核对每笔原始凭证。

费用税 `mode:none|included|excluded`，有税需 rate 与 recoverable。简易计税不再允许进项抵扣。平台代扣销售税已反映在 R，不得另列 T；退货服务税只能在 L。

Decimal.js 10.6.0 已随包固定并附 MIT 许可证，无需 npm 安装。来源：[官方仓库](https://github.com/MikeMcl/decimal.js)、[API 文档](https://mikemcl.github.io/decimal.js/)。
