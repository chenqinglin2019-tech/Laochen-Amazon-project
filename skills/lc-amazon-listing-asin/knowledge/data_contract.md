# 本地数据契约 v2.1

本文是新增字段的唯一结构定义。已有单品字段继续有效；新生成内容使用 `schema_version: "2.1"`。历史文件缺少 `listing_mode` 时按 `single` 读取，但不能因兼容读取被宣布已通过新版验收。所有 JSON 使用 UTF-8。

## 产品画像：01_product_profile.json

保留 `site/listing_language/listing_language_code/category/audience/materials/functions/scenes/specs/limitations/pain_points`。新增：

- `listing_mode`: `single` 或 `family`。
- `brand`: 用户品牌字符串或 null；不造品牌。
- `product_identity`: `{original_name, canonical_name, protected_terms: [目标语言完整核心短语]}`。至少一个必保短语；比较只规范大小写、空白与连字符，不允许拆散名词短语。
- `facts`: `[{fact_id, field, value, source_ref, status}]`。`status` 为 `confirmed/unknown/conflict`；根级 facts 是明确适用于全部子体的共性，单品则是本品事实。只有 confirmed 且有来源的事实能支持声明。
- 购买数量事实使用 field=quantity/package_quantity/unit_count/pack_count/number_of_items，value 为正整数或正整数字符串，必须与配件数量分开。首版机器核对英文 2-Pack、2 count、2 pieces、Pack of 2、Set of 2、Quantity: 2 等表达的数值、范围及事实引用；图片数量声明须在 body_refs 正文引用同一数量事实。其他语言表达和画面实物数量仍需语义复审。
- `measurements`: `[{measurement_id, kind, subject, label, value, unit, source_ref, display_value?, display_unit?, display_text?, approximate?}]`。value 是原始十进制数字字符串；kind 为 `length/weight/volume/nominal/size`；subject 为 `product/package/fit`。label 标明 height/width/length/diameter 等。普通长度单位支持 mm/cm/m/in/ft；US 转 in，其他站点首版保留来源单位。公称规格和尺码不换算。重量、容量首版保留单位，禁止质量 oz 与容量 fl oz 混用。缺失值或单位不补造；需要表达的未知参数先补充资料。
- `images`: `[{image_id, source, applies_to: ["all"] 或 [variant_id, ...]}]`。source 是用户素材路径/URL/附件定位；不能把单一子体素材标成全系列通用。
- `forbidden_terms`: 用户禁用词数组，可为空。

`family` 另加：

- `parent_sku`: 字符串或 null。
- `variation_dimensions`: 有序属性名数组，例如 `["color", "size"]`；用户给定顺序优先。
- `variation_theme`: `{name, source_ref, status}`，status 为 `confirmed/unverified/conflict`。主题与类目支持情况及主题外差异仍需语义复审，不由代码枚举推断平台许可。
- `appearance_assessment`: `{status: same/different/unknown, differences_only_size_or_quantity: boolean, source_ref}`。仅 status=same、differences_only_size_or_quantity=true 且来源非空，允许仅主图独立；缺少此证据按完整逐子体方案处理。不能用“只有一个颜色维度”代替视觉/资料证据。
- `variants`: 按输入顺序排列的数组，每项 `{variant_id, sku, asin, attributes, facts, measurements, image_ids}`。variant_id 必须稳定且文件名安全（字母、数字、下划线、短横线）；缺 SKU/ASIN 用 null；不得生成未提供组合。
- `attributes`: 属性名到 `{value, display, title_value, measurement_id?}` 的映射。value 保留原值，display 是用户可读的目标语言值，title_value 是标题插槽文本。尺寸属性可引用 measurement_id；经 normalize 后其 display/title_value 使用同一 display_text，不能复制首个子体的值。

fact_id、measurement_id 和 image_id 在画像中全局唯一。子体有效事实及参数＝根级共性＋本子体记录；不允许引用其他子体的事实。未明确适用于全部子体的信息不能提升到根级。

## 关键词与问题：02—06

- `02_kw_raw.json` 保留完整后端响应，不覆盖来源数据。
- `03_keyword_decisions.json` 是关键词分类唯一依据，新版不生成或依赖 `03_keyword_review.json`；旧文件仅留作历史资料，详细结构见下文。
- `03_kw_filtered.json` 是原始词中 eligible 的字符串数组；`03_kw_removed.json` 是 excluded 的 `{keyword, reason, reason_code, keyword_id, applies_to}` 数组；新增 `03_kw_pending.json` 保存 deferred 并增加 `promotion_condition`。三者只由统一工具导出，补充词不混入原始词统计。
- `03_keyword_validation.json` 保存当前检查结果；总验收与报告重算数据，不信任此文件的缓存 passed。
- `04_kw_tagged.json` 保留原 keyword/label/reason；增加 `role`（identity/attribute/intent/synonym）、`intent_group`、`source`、`traffic_percentage`（未知为 null）、`applies_to`。旧 high/relevant 标签用于兼容，不决定核心品名优先级。该数组由统一工具导出，仅含 eligible 原始词及补充词，另有 keyword_id、origin=raw/product、searches、restrictions；未知流量为 null，0 保持真实的 0。
- `05_title_keywords.json` 保留 `title_keywords: {high: [], relevant: []}` 供原 CLI；增加 `protected_terms`、`placement_plan: [{keyword, target_field, applies_to, reason}]`。这些是候选与实际投放安排，不是全部进标题的配额。high/relevant 数组必须存在，placement_plan 非空并逐项填写 keyword/target_field/applies_to/reason；protected_terms 至少覆盖画像中的全部必保词。
- `06_qa.json` 保留 status/site/qa_pairs。US 原始响应先存 `06_qa.raw.json`，再补充 `requested_keywords`、`question_reviews: [{question, keyword, relevance: relevant/irrelevant/uncertain, fact_ids, applies_to, disposition: answered/unsupported/excluded}]`。保留原问题，不把自行整理的问题混充后端返回；不相关或无本品证据的问题不用于声称功能。非 US 用 status=skipped、reason_code=rufus_us_only、qa_pairs=[]。
- US 本次未采集时用 `status=unavailable` 和明确 `reason`，上述三个数组均为空；验收为 incomplete，不把未采集标成已完成，也不伪造请求关键词。实际请求失败时另外保留原始错误和请求记录，不能用此状态掩盖已返回的问题。

### 关键词分类结构（keyword_schema_version: "1.1"）

带明确产品事实的判断示例见 [keyword_examples.json](keyword_examples.json)，不要把示例事实当成本次商品事实。

此版本独立于 Listing 的 schema_version 2.1，不改变后端接口。工具命令均使用 `--run-dir RUN`：prepare 建草稿；check 检查分类及已有导出/下游数据；export 从通过检查的分类记录生成三个词池及 04 标注。prepare 不自动完成语义分类；没有额外的剔除词第二轮复核命令或强制步骤。

`03_keyword_decisions.json`：

- `source_fingerprints`: 01_product_profile.json 和 02_kw_raw.json 的字节 SHA-256，工具生成。画像或原词改变后先逐条重新核对，再更新绑定并重新校验；不单改哈希冒充重新审查。
- `records`: 按原始词首次出现顺序排列的唯一词记录。工具生成且不得改写 `keyword_id/keyword/normalized/source_positions/original_forms/origin`；source_positions 为原始 keywords 数组的零基位置。重复记录保存所有位置和原词，norm 保留词序、否定词、数字和单位。
- `supplemental_terms`: 单独登记本品新增表达。字段同逐词记录，但 origin=product、source_ref 为真实来源，无原始词位置。编号为 `product-` 加规范化词的规范 JSON SHA-256 前 20 位；核心名称由 prepare 预登记。不能通过新增同词补充记录绕过原词的暂缓或剔除。

每条记录需填写：

- `initial_decision`：初次 eligible/deferred/excluded；`decision`：最终分类，同样三个值。null 表示尚未审查，不能完成验收。原始词必须全部且仅归一类。
- `reason_code` 对应当前 `decision`：eligible 使用 identity/attribute/intent/synonym；deferred 使用 ambiguous_intent/unknown_fact/seasonal_unconfirmed/identity_conflict；excluded 使用 product_mismatch/fact_conflict/user_restriction/unusable_query。该代码不是机器自动分类结果。
- `reason/query_intent/evidence/reviewer`：非空字符串，分别解释当前分类的具体理由、完整搜索意图、本品证据及真实执行者。不得只写“无关”“白名单外”或通用套话。
- `role`：identity/attribute/intent/synonym；`label`：high/relevant；`intent_group`：同意图分组。组内不同分类时，每项补 `group_difference` 说明真实差异；不应以另建同义组掩盖冲突。
- `fact_ids/measurement_ids`：无重复引用数组；仅限全系列共性和对应子体；`identity_basis` 为布尔值，仅在产品身份本身足以支持相关性时填写 true。eligible 引用的事实必须 confirmed 且有 source_ref，属性词必须引用已确认事实/规格，不能只用产品名称作证。
- `applies_to`：["all"] 或已提供的子体编号数组；`restrictions`：使用限制字符串。包含子体专属事实的词不能扩大为全系列。
- `promotion_condition`：deferred 必填，说明疑点与晋级所需事实；已审查的 deferred 可以留档，不使审查阶段失败。核心品名明确冲突时用 identity_conflict 暂缓，并保持未完成，不能静默丢弃。
- `resolution`：初次与当前分类不同时必填；保留原初次判断，且同步更新当前 reason_code/reason/evidence。可用 initial_reason 另行保存旧理由，不用旧理由导出当前词池。`matched_terms` 为可选的完整词/短语命中证据数组，只校验词边界，不决定相关性。

事实冲突不能引用 unknown/conflict 事实作为已证实反证。user_restriction 必须对应画像中用户明确提供的 forbidden_terms；不能自造禁词。unusable_query 只用于没有有效文字或数字的查询，有有效内容时先修复或暂缓判断。

旧版兼容：可读取 1.0 分类记录，但也须满足当前理由与 decision 一致的要求。旧 03_keyword_review.json 的缺失、过期、结论或格式不参与当前校验及导出；不自动把旧复核结论合入分类记录。沿用历史修正时，将有依据的当前理由明确写回 03_keyword_decisions.json，再导出。旧报告继续可读，缺当前分类或最终文案复审时不能仅凭历史通过状态宣布新版验收完成。

三个词池和 04 标注只从当前 decision、reason、reason_code 导出；改变分类时的初次判断与 resolution 保留追溯。自动统计：原始记录数＝唯一词数＋重复记录数；唯一词数＝eligible＋deferred＋excluded；补充词另计。完整任务的关键词阶段还校验导出一致性、05 候选/投放范围、QA 请求词和后台中的完整暂缓/剔除词组。较短歧义短语被有依据的完整词组覆盖时不按子串误伤。

自然正文、图片和后台倒装表达的语义由最终 `keyword_usage` 复审负责，核对实际采用的词及相关同意图表达，不要求将全部未采用或剔除词再审一遍。该复审不通过词袋交集自动认定违规，也不能用程序检查代替语义复核。最终语义复审额外保存 `keyword_fingerprints`，绑定原词、分类和 05 投放计划；修改这些文件后须重新复审关键词使用。

## 最终内容：07_listing.json

公共字段：schema_version、listing_mode、site、listing_language、listing_language_code、brand_name（字符串或 null）、buyer_question_coverage（数组）、excluded_claims（字符串数组）。

`buyer_question_coverage` 每项 `{question, status, location, source?}`；status 使用 covered/partially_covered/not_claimed/not_applicable。location 用中文说明真实覆盖字段或未主张原因。自行整理的问题标 source=local_editorial，不包装成已采集问答。

单品继续使用顶层 `title/item_highlight/bullets/description/search_terms`；item_highlight 永远是字符串，bullets 是 5 条 `【大写卖点标签】正文` 字符串，无大小写文字的语言不强行大写。另加 claims、image_plan、a_plus_plan、media_strategy、image_sets。

系列结构：

- `parent`: `{sku, title, item_highlight, claims}`；父体不制造五点来满足单品后端校验。
- `title_template`: 一个目标语言模板，例如 `ACME Cotton T-Shirt, {color}, {size}`。每个变体维度恰有一个插槽，顺序同 variation_dimensions；普通共同文本保持一致。
- `shared_content`: `{bullets, description, search_terms}`，只包含全系列成立的信息。
- `variants`: 按输入顺序，每项 `{variant_id, sku, attributes, title, item_highlight, content_overrides, claims}`。这里 attributes 是属性名到目标语言 title_value 字符串的映射，必须与画像一致；content_overrides 只能覆盖 bullets/description/search_terms，数组整项替换。缺少覆盖项继承 shared_content。
- `image_plan` 和 `a_plus_plan`: 根级完整图片/模块策划，分组及复用通过 image_sets 表达；不将完整图片数组塞入每个子体。

子体 title 必须等于 title_template 按其 title_value 填入的结果；共同品名不得因子体不同而换词。父标题是无变体值的共同商品描述，不必机械复制某个子标题。父标题禁价格、库存和具体包装数量；父标题及 Highlight 不得泄漏具体变体值。数字材质如 304 不应被一概删除。

### 声明与图片引用

每个单品、父体或子体的 `claims` 是数组：`{field, fact_ids: [], measurement_ids: []}`。field 支持 title、item_highlight、bullets[0] 至 bullets[4]、description、search_terms；子体引用的是继承后完整内容。每个前台文本字段至少有一个声明记录，允许无可核查数值的场景文字用空引用并由语义复审说明；非空引用必须属于对应子体且已确认。含规格的字段记录 measurement_ids 并复用 display_text，保持维度标签；后台搜索词不强制声明记录。

### 图片集合与复用

新输出仅写 `a_plus_plan`；旧 `aplus_plan` 可读取。两字段同时存在且相同可兼容读取，不同时明确报错，不能默默择一。示例旧字段 image/direction/selling_point 及 module/direction 保留，新增证据字段不改变可读说明。

- `media_strategy`: single/per_variant_full/shared_secondary。
- `image_sets`: `{shared: {main: plan_id, secondary: [6 个 plan_id], a_plus: [plan_id, ...]}, variants: [{variant_id, main: plan_id, secondary: [6 个 plan_id]}]}`。引用必须存在、角色匹配、无重复；所有根级创意必须归入对应方案，不能隐藏遗漏或额外方案。
- single：shared 为唯一 1 主图＋6 附图＋至少 5 张 A+ 图片，variants=[]。
- family：shared 始终包含完整 1＋6＋至少 5 张 A+ 图片，variants 与画像的实际子体顺序完全一致。per_variant_full 每个子体引用独立 1＋6；shared_secondary 每子体独立 main、secondary 逐项引用 shared.secondary。不存在子体 a_plus 字段，所有子体使用 shared.a_plus。
- shared_secondary 需要画像中明确的 appearance_assessment 证据；颜色、图案、造型不同或不能确认外观相同，使用 per_variant_full。共用主图表达统一构图，不能把全系列不同商品画成同一个购买套装。
- A+ 默认 5 张图片，有明确需要可以增加。asset_type=text 的 FAQ 等文字模块不计入 5 张图片。总数由唯一创意及分组引用计算，不将重复引用虚算为新的创意。

每个 image_plan/a_plus_plan 项：

`{plan_id, role, image? 或 module?, direction, applies_to, buyer_question, selling_point, visual_evidence, scene_intent, overlay_text, native_text?, fact_ids, measurement_ids, source_image_ids, body_refs, mobile_check, production_notes, status?, asset_type?, variant_bindings?}`。

- role：main/secondary/aplus；applies_to 为 ["all"] 或明确 variant_id 列表，单品使用 ["all"]。
- image_plan 各组 image 从“图1（主图）”到“图7（主题）”顺序编号；每组重新编号，plan_id 仍全局唯一。a_plus_plan 使用 module=“模块N：主题”和 asset_type=image/text；direction 是中文画面或模块组织说明，不能只写内部编号。
- status 可为 ready/pending，默认 ready 仅表示策划已具备依据；pending 必须在 production_notes 说明缺少的事实或素材，并保持验收未完成。不能以 ready 覆盖缺素材或引用失败；未生成实图不能写成已验收成图。
- overlay_text 是图片嵌字的目标站点语言字符串；native_text 是可选的 A+ 原生模块文字，缺省为空，避免为兼容字段把原生文字烧入图片。主图两种文案均为空；其他策划说明中文。A+ 参数可在 native_text 或 overlay_text 中准确表达。
- body_refs 使用与 claims.field 相同的定位，指向该图适用子体解析后的正文。关键参数必须在对应正文中也有表达和引用。
- 共同图本体只能引用根级共性及通用素材。子体图引用对应子体；需要图片但解析后 source_image_ids 为空时保留缺口并使验收 incomplete，production_notes 明确需要补拍什么。纯文字模块不要求实物图片素材。
- 共用构图可添加 `variant_bindings: [{variant_id, fact_ids, measurement_ids, source_image_ids, body_refs, overlay_text, native_text?, direction?, visual_evidence?, production_notes?, status?}]`。一旦提供绑定，必须按画像输入顺序完整提供所有子体，不遗漏、重复或新增组合。每项以本子体字段替换模板对应字段，不把兄弟子体引用合并为共同事实。
- 每个绑定必须显式填写 fact_ids/measurement_ids/source_image_ids/body_refs/overlay_text；引用限根级加本子体，尺寸和数量分别绑定自己的事实、单位及正文。可选文字字段未写时继承模板。模板采用绑定时允许本体素材留空，但逐绑定解析结果必须各自具备适用素材。
- 复用方案不复制整套创意，仍完整展示 SKU/内部编号、真实属性和每张图的替换参数、素材及上图文案。关键尺寸/数量只进入对应子体图文；不能把单一容量写成全系列参数。
- 移动端可读性、画面事实和场景合理性由语义复审检查。引用检查只验证范围与数值，不证明营销承诺成立。

## 验收与后端适配

- `08_semantic_review.json`: 绑定当前 profile/listing/qa 文件 SHA-256 的复审记录。目标为 single 或 parent＋各 variant_id，另含 media。每项 `{target, check, status: pass/fail/not_applicable/pending, evidence}`。文本检查 identity/readability/factual_support/language/variant_scope/qa_relevance/keyword_usage；media 检查 image_truth。not_applicable 需要原因；pending/fail 或缺项不能交付通过。不得为了过关机械填 pass。
- `08_backend_validation.json`: `{records: [{target, payload_sha256, exit_code, response}]}`。target 为 single 或具体 variant_id；response 保留后端 JSON，仅 `ok=true` 且 `errors=[]`、退出码为 0 才通过。父节点只本地检查。响应或 payload 指纹缺失/过期不通过。
- `08_validation.json`: 汇总本地、关键词审查、语义、后端检查（local/keywords/semantic/backend）；`status` 为 passed/failed/incomplete；fingerprints 绑定 profile/listing/qa 原文件 SHA-256，evidence_fingerprints 的 review_sha256/backend_sha256 绑定复审与后端文件的规范 JSON SHA-256，keywords_sha256 绑定重新计算的关键词阶段结果 SHA-256（UTF-8、ensure_ascii=False、sort_keys=True、separators=(',',':')）。报告核对原验收文件存在且指纹匹配；缺失、过期为 incomplete，不以生成了文件代替完成。

本地工具命令统一使用 `python3 scripts/listing_quality.py`：

1. `normalize --profile FILE --output FILE`：计算展示值并输出画像（允许原位原子替换）。
2. `check --profile FILE --listing FILE [--qa FILE] [--review FILE] [--backend FILE] --output FILE`：只检查，不自动改文案；缺验收为 incomplete，退出非零。
3. `prepare --profile FILE --listing FILE --output-dir DIR`：检查可确定的结构后，导出逐子体现有格式 payload 与 manifest；不向后端发送嵌套 family。
4. `review-template --profile FILE --listing FILE [--qa FILE] --output FILE`：生成绑定指纹的 pending 清单，供独立语义复审填写。
5. `backend --profile FILE --listing FILE [--cli CLI_PATH] [--config FILE] [--timeout SECONDS] --output FILE`：逐个投影单品 payload，通过 backend_cli.py 统一读取配置并调用原 CLI validate；无需调用者设置环境变量。捕获脱敏业务 JSON 及原进程退出码；启动/配置错误的 exit_code 为 null，并附 error_code、failure_reason。默认超时 120 秒。配置和二进制内容不修改。

后端统一入口 `python3 scripts/backend_cli.py`：

- `expand --asins ASIN1,ASIN2 --site SITE --output FILE` 和 `qa --keywords-file FILE --site US --output FILE`：仅从 CLI 的完整临时输出读取 JSON，脱敏后原子写入原有结构，不把终端摘要当作原始数据。
- `validate --listing-file FILE --site SITE [--output FILE]`：原 CLI 单品接口；无 output 时返回的安全摘要含 response。系列统一使用上述 listing_quality.py backend 完成逐子体投影。
- 三个命令均可选 --config、--cli、--timeout；凭据只能从配置文件读取，无环境变量回退或 token 命令行参数。默认配置相对 Skill 定位，不依赖工作目录。
- 非零进程退出、无有效 JSON、超时和显式业务失败均返回非零；validate 仍要求 ok=true 且 errors=[]。进程已执行时保留真实 exit_code，未执行/未正常返回时为 null。错误响应可留档，不代表验收通过；无新有效响应时旧文件不覆盖、不视为本次结果。原始进程日志不透传。

报告工具 `python3 scripts/render_listing.py --run-dir DIR` 从同一 JSON 生成 07_listing.md 与 report.html。

- Markdown 单品依次为 Title、Item Highlight、Bullet Points、Description、Search Terms、附图策划、A+ 整体策划、买家问题覆盖清单。系列先父体与全部子体标题/Highlight，再共用正文及差异；图片策划按共用方案、逐子体方案展开。只显示文案、中文创意说明和必要替换信息，不放 claims、画像、指纹、校验 JSON。
- HTML 严格保持示例的报头、摘要漏斗、七个章节和白底 Listing 文档卡片；父子体、完整图片创意与复用关系用标题和自然段展开。禁止新增导航条、验收面板、原始 JSON 或逐图技术字段列表；图片保留画面说明、目标语言文案及必要的制作前待确认事项。技术引用和完整验收记录存入内嵌 JSON，摘要仅显示简短状态；缺失或旧版校验不能标通过。HTML 的简洁展示不删改结构化 JSON 或 Markdown 的内容。
- 最终固定链接 07_listing.md、07_listing.json、report.html 三份文件；中间采集/校验文件保留追溯，不另建“文案预览”。
