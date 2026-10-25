# 站点与来源路由

本文件是**查找路线**，没有预置现行税率或费率。下列官方域名用于限定搜索；实际计算必须打开具体规则正文，记录发布日期、生效日期、商品税类、卖家资格、计费基数、税价和来源定位。搜索摘要不构成规则已核验。

## 各站点

- US：amazon.com / USD。Amazon 美国 Selling on Amazon、FBA fulfillment、monthly inventory storage、inbound placement；税与海关 irs.gov / cbp.gov，各州销售税仅在影响 R 或卖家承担税额时补查。
- JP：amazon.co.jp / JPY。Amazon 日本销售费用、FBA 配送代行手续费、仓储；税关税 nta.go.jp / customs.go.jp。金额展示零位不代表所有中间值可提前舍入。
- UK：amazon.co.uk / GBP。Amazon 英国 selling fees、FBA fee card；税关税 gov.uk。核实库存地、主体及平台 VAT 责任，不用欧盟规则替代。
- DE：amazon.de / EUR。Amazon 德国官方费用；税关税 bundesfinanzministerium.de / bzst.de / zoll.de。当地商品税类、EPR 和主体服务费条件独立。
- FR：amazon.fr / EUR。Amazon 法国官方费用；impots.gouv.fr / douane.gouv.fr。独立核验税和当地附加费，不因同 EUR 合并。
- IT：amazon.it / EUR。Amazon 意大利官方费用；agenziaentrate.gov.it / adm.gov.it。
- ES：amazon.es / EUR。Amazon 西班牙官方费用；sede.agenciatributaria.gob.es / agenciatributaria.es。
- SA：amazon.sa / SAR。Amazon 沙特当地费用；zatca.gov.sa。必须独立查询，不套 amazon.ae / AED；当前 SellerSprite 单商品工具缺 SA，改官方页面或人工材料。
- MX：amazon.com.mx / MXN。Amazon 墨西哥费用；sat.gob.mx / anam.gob.mx。主体类型、当地登记、所得税预扣和销售间接税预扣分开处理。
- CA：amazon.ca / CAD。Amazon 加拿大费用；canada.ca / cbsa-asfc.gc.ca。GST/HST/PST/QST 适用性按交易与资格核验；价外买家税不重复扣净收入。
- AU：amazon.com.au / AUD。Amazon 澳大利亚费用；ato.gov.au / abf.gov.au。核验 GST、进口与凭证资格。

Amazon 公开费用页面常位于 sell.amazon.*、sellercentral.amazon.* 或对应站点服务子域。以上不是认证凭据；访问要求登录时沿用用户已有只读访问或请用户提供页面/账单，不索取密码。

## 可复用检索模板

- `site:<当地 Amazon 官方域名> FBA fees <year> effective <日期>`，用当地语言补充配送 / 仓储 / 销售佣金搜索词。
- `site:<当地税局> online marketplace <seller establishment> VAT GST withholding <year>`。
- `site:<当地海关> <已确认海关编码> tariff origin <原产国>`。
- 检查后续修订与未来已公布费率；只读取当前测算需要及敏感性会触达的相邻档位，不泛抓整个站点。

## 快照验收记录模板

每个真实常规 / 边界案例保存：站点、子 ASIN、销售单位、采集方式（自动 / 人工）、价格、包装、卖家资格、销售计划、费表日期、具体来源 URL 与定位、规则快照 id、逐项预期值、引擎结果、舍入差异解释、核验人和时间。

各站点至少一个常规和一个分档边界；对照同日期同资格官方费表或官方计算器。SA 单独验证商品数据路径；JP 验证精度；欧洲验证价内税；CA/MX 验证条件税务。没有真实证据时保持未验收。

## 需求给出的参考入口

- [Amazon 美国站销售费用](https://sell.amazon.com/pricing)
- [Amazon 英国站销售费用](https://sell.amazon.co.uk/pricing)
- [Amazon 沙特站销售费用](https://sell.amazon.sa/pricing)
- [Amazon 收费类别说明](https://sellercentral.amazon.com/help/hub/reference/external/GNJSJ7GP26PD5XWJ)
- [Amazon FBA 尺寸等级](https://sellercentral.amazon.com/help/hub/reference/external/GG5KW835AHDJCH8W)
- [Amazon 入库配置费用](https://sellercentral.amazon.com/help/hub/reference/external/GC3Q44PBK8BXQW3Z)
- [Amazon 基础仓储费用](https://sellercentral.amazon.com/gp/help/external/G3EDYEF6KUCFQTNM)
- [英国税务局平台 VAT](https://www.gov.uk/guidance/charging-vat-when-using-an-online-marketplace-to-sell-goods-to-customers-in-the-uk)

入口来自需求参考，不表示本次已取得这些页面全部有效费率；任务执行时重新打开核验。
