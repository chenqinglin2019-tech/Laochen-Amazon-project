# 商标、版权与非注册权利专项（2.4）

新 `workflow-correction-v1` 将标识/素材作用域摘要与采集元数据分离，采用[输入更新及必要审阅契约](workflow-correction.md)。共享盘点可用 `inventory_identity_sha256_by_right` 分别绑定各权利摘要；原单值字段保留兼容，不能用同一说明文字替代实际盘点。

本文的检索与比较要求对新旧策略共用；新策略的最终五级评级、置信度及主审流程见 [risk-estimate-rules.md](risk-estimate-rules.md)。

文字、Logo、角色、图案、照片、包装和产品形状分别建立素材/标识清单。Agent 从产品信息、图片 OCR 和图样识别得到查询词与来源，不要求用户去登记库查询。

文字商标先做原词、规范化、近音、拼写变体、翻译/音译、权利人及商品服务检索；日本增加假名读音、罗马字和适用类似群。分类或近音接口未支持时保留缺口，不能将字符串搜索伪称语义/分类召回。Signa 是可选文字发现，当前普通接口不提供可用的图片或语义召回。

用户未给定的自有品牌名称和 Logo 不纳入本轮清查，也不使用竞品页面品牌代替。已评产品通用文字、可见标识与未纳入的新品牌分别说明；未知新品牌不清空其他已审范围的评级。

图形商标与外观相近不代表成立侵权。需要核对具体注册图样、保护元素、商品服务、实际使用、来源混淆与授权。EUIPO 文字 API 不能完成 Vienna 图形分类召回，未经允许的 eSearch 人工代查不是回退。

版权没有登记不等于无权利。只对当前情景中适用的作品追溯原始发布、创作或采购资料、许可主体、地域与用途。搜索引擎或登记库零结果不能证明原创或获许可。[英国 IPO 说明版权自动产生且没有英国版权登记库](https://www.gov.uk/copyright)。

SerpApi Lens 只使用已公开且与任务图片绑定的 Amazon 图片 URL，不上传本地产品秘密图片；结果只做相似来源发现。反向搜图没有命中不构成许可证明；返回的原作品网页/文件要由 Agent 取得实际证据并进行比较。

没有登记号的具体疑似作品可通过 asset_provenance 形成来源证据和局部风险发现；不要强制创建 copyright registration_number。缺少用户自有的采购合同/授权文件属于产品事实缺失；已声明没有授权时按此事实推进，不重复索要不存在的文件。报告列供应链来源核查、应核材料及等级调整条件，但不以核查未完成为由拒绝当前五级预判。不得要求用户完成查询、截图或代替 Agent 判断侵权。

trade_dress 在 US 可对应商业外观，在其他国家必须注明实际适用的非注册标识、混淆或不正当竞争依据，不能假定七国权利规则一样。EU、GB 非注册外观另查首次披露、保护期限、地域、复制和排除条件。记录期限与地域，不根据外观热度自动判高。

既有维权、投诉、诉讼或平台下架记录单列 enforcement_signals，先核对当事人、标的和结果；它影响行动紧迫度，但不能直接代替当前产品与具体权利的侵权比较。未建成某国完整免费执法检索链时明确其范围，不把法院官网入口当已查询所有案件。

## 情景专项调查：asset-scope-v1

仅链接且未说明为用户自己的产品：按可见外观、功能相同且照片/文案另做的选品假设，参考照片只用于识别商品，不调查竞品摄影/文案复制风险。用户提供自己的产品图片、文案或明确拟使用素材时，检查这些素材；“自己的”不是已获许可的证明。两种情况均检查产品本体造型、内置图案、角色和装饰；功能性与可独立识别艺术表达分开，不把版权等同外观专利。

`product.assets` 必须为实际盘点列表，条目保存 asset_id、usage、right_types、scenario_ids、scope_reasoning、evidence_refs；usage 为 reference_only/intended_material/integrated_expression/product_configuration/intended_packaging。不得把不完整条目静默筛成空清单。`asset_scope_review` 保存 status=reviewed、reviewer、reasoning、evidence_refs，以及 `record_asset_provenance.inventory_identity_sha256(task,right_type)` 的摘要；产品、图片或清单变更后重新核对盘点。来源日期保持原取证时间。

`product.mark_inventory` 分 plain_text/stylized_text/graphic/composite，保存 mark_id、form、graphic_description、scenario_ids、evidence_refs；另有同格式 mark_inventory_review。缺图片/缺盘点不等于无图形。美国实际可见图形可派生 `query_terms.kind=design_code`（六位USPTO代码）或 mark_description（英文），derived_from 精确指 product.mark_inventory[index]。新计划使用 tm-figurative-fields-v1，DC 分类、DE 描述与视觉比较分别留证；不将普通品牌全文搜索当图形召回。代码以当前官方 Design Search Code Manual 核对，不能混用同数字 Vienna 分类。[USPTO 字段说明](https://www.uspto.gov/sites/default/files/documents/TM-FederalTrademarkSearching-FieldTags-handout.pdf)。

USPTO 不提供反向图片搜索；`visual_comparison` 是取得与阅读真实标样，不是 image_search。经实际盘点没有适用图形时，可留有图像依据的不适用审阅；不能为测试强造Logo或为结束任务删掉图形义务。

风格化文字不当然有图形分类码。核对实际图样和官方手册后，确无适用代码者在该标识 classification_review 保存 status=not_applicable、design_codes=[]、reasoning、evidence_refs；同情景所有适用标识满足时，通过classification轴Agent记录留证，不强造DC查询。存在可用代码则仍须执行实际分类召回；描述和标样比较义务独立保留，不能用单轴不适用关闭整个模块。

执行 `record_asset_provenance.py --task-dir DIR --list-work` 获取现有计划中的 Agent 待办。版权：provenance、visual_comparison；商业外观：public_use、source_identification、functionality；图形商标：visual_comparison。版权公开调查追溯适用作品/本体表达与必要注册线索；商业外观另读品牌/制造商原页、历史宣传、相关产品配置注册与已发现公开争议，核对具体主张、使用、来源识别、混淆及功能性。合格既有原文/标样/TSDR事实直接复用；只补缺项，不重查整套事实。

来源记录器仍是本地记录器，不是联网API。每次提交绑定查询、情景、asset_scope_sha256、当前适用资产 coverage_attestation；investigation_steps[] 保存 step/status/reasoning/evidence_refs/artifact_sha256。completed 或有依据 not_applicable 是步骤状态；outstanding_actions 记录未做的必要工作，unresolved 保留尚未知的权属/许可等事实。完成依据必须连接已登记实际来源及哈希文件，自写说明不能单独代替公开调查。失败保持具体下一步，不自动转排除/低风险；缺用户独有材料与 Agent 尚未查资料分开。

同情景、同当前资产范围且完整通过取证与必要步骤校验的 Agent 比较，可支持其明确范围内的风险预判，无需伪造数据库搜索回执；局部排除不外推整个情景低风险，未知权属事实仍保留。

实用专利的具体功能教导可用于商业外观功能性比较，但不自动排除所有形状/颜色/装饰组合。来源识别/显著性与非功能性分别审查；不要求统一商业外观登记号，也不声称免费渠道穷尽全部未注册权利。
