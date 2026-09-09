# 2.4 地域覆盖与免费信息源

本版支持 US、GB、FR、DE、IT、ES、JP；具体任务按用户目标选择，未指定时沿用商品站点默认国家。欧洲 EU 层为相应目标国家补充，不自动扩展到 EU27。本文是可追溯来源目录，**不是七国已经完整自动跑通的声明**。执行能力以逐操作验收和当次证据为准；账号与免费接口细节见 [providers.md](providers.md)。

## 地域与证据不能互相顶替

- 普通 EP、UP、国家专利分开。EPO 原文证明公开内容；EPO/INPADOC 法律事件可辅助追踪，目标国效力仍需相应权威依据。
- UP 依据该具体权利的登记及有效地域判断，不套用所有 EU 国家；英国和西班牙不能因 EU/EP 标签自动被计入 UP。普通 EP 仍可能在这两个国家有效。[EPO UP 地域说明](https://www.epo.org/en/legal/guidelines-up/2026/section_1_5_1)
- EU 商标及注册外观与国家商标/外观分别排查。英国独立核验，历史 EU 转换产生的英国权利不能遗漏，也不能直接沿用今天的 EU 状态。[英国转换权利说明](https://www.gov.uk/guidance/eu-trade-mark-protection-and-comparable-uk-trade-marks)
- 专利同族关联有助于找案号，不能代替不同国家的权利要求、期限和效力；WO 公开申请不代表一项全球有效专利。
- 注册事实、法律状态、保护范围比较分别留证。官方页面截图不自动证明相似产品落入保护范围；搜索结果零条不等于法律上的无权利。

## 美国 US

免费可用的信息入口：

- [USPTO Patent Public Search](https://ppubs.uspto.gov/basic/)：发明及设计专利公开文献发现、原文及图像；授权文献本身不证明今日有效。
- [USPTO Assignment Center](https://assignmentcenter.uspto.gov/)：权利转让记录补证，不能单独代替全部现行所有权和专利效力判断。
- [USPTO Trademark Search](https://tmsearch.uspto.gov/)：文字、读音近似、商品服务及图形检索；[design search codes](https://www.uspto.gov/trademarks/search/design-search-codes) 用于图形召回。
- [TSDR](https://tsdr.uspto.gov/)：已知商标案的状态、权利人、商品服务、图样和档案核验。
- [Copyright Public Records](https://publicrecords.copyright.gov/)：特定公开版权登记及文书，不能覆盖所有自动取得保护的作品。
- [TTABVUE](https://ttabvue.uspto.gov/ttabvue/)、[PTAB](https://ptab.uspto.gov/)、[CCB](https://ccb.gov/)：各自范围的行政/版权争议记录；它们的合并结果不是全部联邦诉讼。

现有 PPS/TM Search/TSDR CDP 执行器采用逐查询自动验收，用户只处理必要的登录和验证码。真实执行、产品驱动召回正例及覆盖完整度必须在各任务中分别保存；单个美国专利正例通过不升级为外观、商标或全部路线已完成。其他入口未有本版合格自动查询能力时保持缺口，不交给用户手工搜索。不强制办理复杂 USPTO API 身份认证。

EPO OPS、通过免费账户门禁的 SerpApi 可提高公开专利发现；无 `api-first-v1` 标记的历史 2.4 Serper 仍暂停计量；新任务按 [API 优先契约](api-first.md)核验使用依据。仍须分别解决权利要求、设计专利完整图纸和当期状态。上述缺口不会因 Google Patents 的状态摘要或某一诉讼库无命中而消失。

## EU 层与 EP 文献

- [EPO OPS](https://ops.epo.org/)：注册免费、结构化发现与同族/分类补充；访问获批不确定时用其他合格发现源继续，不能阻塞全任务。
- [EPO Publication Server](https://www.epo.org/en/searching-for-patents/data/web-services/publication-server)：免注册下载 EP 文献；当前代码已真实验证 XML 单案提取，缺原始图像或现行地域效力时仍保留缺口。
- [EPO Federated Register](https://www.epo.org/en/searching-for-patents/legal/register/documentation/federated-register)：了解普通 EP 国家登记与路由；其网页当前不作为可自动执行且已验收的替代。
- [EUIPO API Portal](https://dev.euipo.europa.eu/product)：Production 1.1.0 的 EU 文字商标、外观搜索及详情；免费但需审核，Sandbox 只用于测试。
- [EUIPO eSearch](https://euipo.europa.eu/eSearch/)、[TMview](https://www.tmdn.org/tmview/)、[DesignView](https://www.tmdn.org/tmdsview-web/)：有跨库及图像/分类发现价值，但当前受限网页不进入无人值守查询，也不安排人工业务回退。聚合数据不是目标国法律状态登记簿。

EUIPO Trademark Search API 不支持 Vienna 分类召回。文字商标查询不能填补图形商标检索要求；仅得到外观名称命中也不能填补图片比对。没有兼容免费自动路由时，报告具体缺口而不宣称 EU 全覆盖。[EUIPO 检索说明](https://www.euipo.europa.eu/en/help-centre/design/faq-search-availability)

## 欧洲五个目标国家

### 英国 GB

[专利检索入口](https://www.gov.uk/search-for-patent)、[商标检索入口](https://www.gov.uk/search-for-trademark)、[外观检索入口](https://www.gov.uk/search-registered-design) 分别对应英国权利。规划包括 GB 国家专利及可能在英国有效的普通 EP；不将 EU 权利或 UP 直接计为英国有效。

本版本英国网页操作尚未完成自动查询/取证验收；“UKIPO 公共页面存在”不等于有已验证的免费 API。One IPO 等后续开放能力仅是持续核查候选，不写死上线时间，不猜生产接口。

### 法国 FR

[DATA INPI](https://data.inpi.fr/)、[免费 PI API](https://data.inpi.fr/content/editorial/apis_pi)、[PI API 技术文档](https://www.inpi.fr/sites/default/files/Inpi_doc_tech_API_PI_v1.0_0.pdf)。注册与激活后可通过已实现客户端调用，真实登录后响应仍待验收。

区分法国专利、`certificat d'utilité`（本 Skill 表示为 utility_model）、商标和外观。API 可提供部分 EP、WO、EU 数据，但本版默认 FR 查询不能声称已查其他集合；法国数据不能代替其他国家效力。法国外观完整视图清单目前未通过验收，不能将 notice 自动评为完整外观核验。

### 德国 DE

[DPMAregister](https://register.dpma.de/DPMAregister/Uebersicht)、[DPMA 检索服务说明](https://www.dpma.de/english/search/)及 DEPATISnet 分别提供登记和专利文献能力。德国专利、实用新型、商标、外观保持不同权利类型；EU 层另行覆盖。

本版本未有已验收的德国自动单案核验路线。DPMAconnectPlus 收取接入费用，不符合零支出边界，不能作为自动回退。[DPMAconnectPlus](https://www.dpma.de/english/search/data_supply_services/dpmaconnect/index.html)

### 意大利 IT

[UIBM 官方数据库](https://www.uibm.gov.it/bancadati/home/index/)用于国家专利、实用新型、商标、外观，EU 权利另行覆盖。当前适配器入口不等于自动查询完成；本版本没有已经验证的低门槛免费公共 API 或完整 CDP 业务执行路线。保留相应检索与效力缺口。

### 西班牙 ES

[OEPM Localizador](https://consultas2.oepm.es/LocalizadorWeb/)、[CEO 状态查询](https://ceo.oepm.es/)用于商标及档案状态，OEPM 的专利/外观数据库补相应文献。西班牙实用新型独立排查；普通 EP 可能在 ES 有效，但不自动计入 UP。

[OEPM 免费 Web Services](https://www.oepm.es/es/sobre-OEPM/servicios-al-ciudadano/servicios-gratuitos/Servicios-web-de-la-OEPM/index.html)是值得优先验证的机器接口，需要申请账号。**本版本未实现和验收该账号接口，不生成猜测的 SOAP/REST 调用。** 获取官方现行契约、确认境外账号可用和真实核验后才提升为自动来源。

## 日本 JP

[JPO API 申请说明](https://www.jpo.go.jp/system/laws/sesaku/data/api-provision.html)、[JPO API 技术参考](https://ip-data.jpo.go.jp/api_guide/api_reference.html)、[J-PlatPat](https://www.j-platpat.inpit.go.jp/)。JPO API 仅核验支持的已知专利、意匠、商标号码；不做关键词/全文/图片召回，也不覆盖实用新案。

日本检索需日语词、读音、类似群代码及适用分类，保留翻译出处。当前 J-PlatPat 自动业务路线未获本版兼容验收，不把“人工低频查询”当成补救；因此意匠、商标、实用新案召回可能存在实质缺口。实用新案还需记录与行权相关的技术评价材料，不能仅看登记。[JPO 实用新案说明](https://www.jpo.go.jp/e/faq/yokuaru/utility.html)

## 版权、未注册权利和争议记录

版权的存在通常不以登记为前提。Lens 反向图片发现、公开作者/品牌/素材来源、用户提供的授权和生产资料用于证据链；政策说明页只能支持规则，不能作为“版权库已检索”的来源记录。[美国版权局说明](https://www.copyright.gov/help/faq/faq-general.html)

未注册外观和商业外观须结合国家规则、公开时间、市场识别及产品使用方式。免费登记库不能穷尽这些权利，不能强制要求登记号才能形成风险发现，也不能因没有登记号直接排除。

[法院公开案件 API：CourtListener](https://www.courtlistener.com/help/api/rest/)及 RECAP 可作为后续免费案件发现来源，但**本版本尚未实现该客户端**。不得借用付费 PACER 代取、会员搜索或付费服务填补缺口；也不能宣称公开案件集合完整。争议活跃度影响处置优先级，不替代侵权要件比较。

## WIPO 与第三方发现

PATENTSCOPE、Global Brand Database、Global Design Database 各自服务和条款不同；当前直接 WIPO 网络路线不执行。禁止以可见 CDP 或人工点击开始来绕过自动查询限制。[PATENTSCOPE 条款](https://www.wipo.int/en/web/patentscope/data/terms_patentscope)、[品牌库条款](https://www.wipo.int/en/web/global-brand-database/terms_and_conditions)

EPO/INPI 等合法渠道的 WO 文献可以作为线索，不因文献国别 WO 而删除；仍须找到相关国家权利及效力。现有 Signa office WO 继续由其冻结免费发现契约排除，不代表产品已经查清所有国际指定权利。

SerpApi 与 Signa 经账户门禁后可使用免费额度发现。Serper 新任务使用依据见 [API 优先契约](api-first.md)；无新标记历史 2.4 固定在计量请求前停止；不能把注册赠额推定为任意现有 Key 均可零费用执行，细节见 providers.md。两个 Google 检索代理不算两个独立数据库；增加语言、结构、分类、权利人、图片维度才可能扩大召回。发现层内容不能伪称官方登记或证明权利现行有效。新策略可将真实线索作为带假设、低置信度的预判依据；不把线索转换为已核实事实。无策略字段的历史任务仍按旧正式评级门禁执行。

## 后续替代路线与验收门槛

- [BigQuery Sandbox](https://docs.cloud.google.com/bigquery/docs/sandbox)：无需信用卡的免费受限环境，可能用于公开专利数据的有界 SQL；未实现数据表版本、更新频率和扫描预算验收，不能视作现有 OPS 替代。
- UKIPO 官方 API、OEPM Web Services：以官方已发布契约、账号门槛和免费权限为准；未提供或未验收时不猜接口、不注册付费服务。
- [PatentsView](https://search.patentsview.org/docs/docs/Search%20API/SearchAPIReference/)及 [Lens.org API 条款](https://about.lens.org/lens-api-terms-of-use/)须重新确认免费注册、商业使用及可申请性；不把机构订阅或非商业试用默认用于卖家业务。Lens.org 与已实现的 SerpApi Google Lens 是不同服务。

所有升级为自动可用的路线需有当前日期、官方契约、允许的操作范围、真实正例/零结果/详情/截断及访问失败证据。用户只解决登录或验证码后，Agent 应能完成剩余业务。当前验收记录见 [provider-live-acceptance-v24.json](provider-live-acceptance-v24.json)，其中未实测项不能据离线测试改成通过。

历史 `2.3-free` 的来源选择和计划保持冻结，不按此文静默改写；`2.1/2.2` 仅保留历史证据及报告读取。任何未完成路线都应具体说明影响的国家、权利、检索维度或比较字段；未公开申请、未知授权链和未注册权利的覆盖限制不能被转述为无风险。
