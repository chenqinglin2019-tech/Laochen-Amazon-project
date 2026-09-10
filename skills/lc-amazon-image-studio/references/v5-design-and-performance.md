# V6 设计与性能契约（兼容 V5）

本文件按需说明设计字段、特殊效果和历史兼容；唯一生产主流程见 [SKILL.md](../SKILL.md)，命令与恢复见[运行管线](runtime-pipeline.md)。所有生产动作（包括 status、compact、恢复与工具编排）继续服从 SKILL 的原有鉴权边界，本文不另设放行。文档字段不能替代真实脚本校验。

## 参考编译

新项目默认 `design_template_policy={version:1,mode:auto}`，详见[英文模板库](design-template-library.md)。先选套系再选图位，正文与参数化提示词英文，产品与批准文案来自当前项目。`design_template_set_id/design_template_set_revision` 指定项目套系，`job.design_template_id/design_template_revision` 指定单图；已采用文本在 `design_template_selection` 与 `design_resolution.binding` 以 ID、revision、完整 snapshot 和 content_hash 固定。新库或新 revision 不自动改变已有绑定。模板模式不读旧风格原图；校验快照和编译 brief，不取消真实产品来源检查。无匹配时撰写项目原创 brief 并填写 `design_template_original_reason`，标记 matched=false，不自动入库。

V6 新项目使用 V3 `style_contract`，设计指定值优先；显式文字组／layout > 项目颜色与字体角色 > brief 默认 > recipe。V1 固定字体/文字色与 V2 自适应行为仅为兼容，不自动迁移。`headline_treatment={plain|outline|shadow}` 仍可用，`typography_decision` 分别记录请求设计、显式设置、解析结果及允许调整。Native 的 brief.layout 进入生成依赖；local 的字体/精确位置及局部效果只进入对应效果／layout 依赖。

### 历史项目与外部参考

兼容的旧项目恢复先查 `status`，不例行迁移。确需旧 schema 升级时才运行 `migrate --manifest <manifest> --json`，按缺项补 `--marketplace`／`--language`；保留迁移备份、`legacy_text_overlays` 和旧审核记录，按变化重新审核，不能将旧 A+ 一律猜为 970×600。迁移不自动切换提示、审核规则或设计 profile，也不重写历史审核哈希。

以下外部参考接口仅用于未启用模板模式的旧项目，或当前明确选择的外部参考。保留 `style_reference_index.json`、`design_reference_units.json` 及其真实来源绑定，不自动迁移：

```bash
python3 <skill-root>/scripts/lc_style_reference.py prepare \
  --product-context <project-dir>/style_reference_context.json \
  --selection-output <project-dir>/style_reference_selection.json
```

上下文 `product` 必填；建议提供 `category`、`intents`、`composition`、`lighting`（字符串或列表）。缺项只可由真实 `product`／`selling_job` 有限推导，无依据则 unknown／needs_input。结果选择一个主参考及最多两个辅助参考，保存路径／哈希、评分和 `style_profile_hint`，项目通过 `style_reference_selection_path` 绑定。已有 Python 接口为 `prepare_selection({"product": product, "category": category, "intents": selling_job}, selection_path)`；输入未变复用选择结果。参考只提供设计方向，不借用来源商品、品牌、文案、CTA 或像素。

单元索引 schema_version=1、asset_policy=external_regions_only。每项 id、绝对external_path、sha256、unit_region_norm、recipe、generation、layout、reviewed=true、product_evidence=false。区域指向单张成品，排除下载按钮和文件名；重叠编号列为排除内容，不复制进生成图。

项目可设 design_reference_units_path 与 design_reference_ids，单图 design_reference_id 更优先。未指定本轮参考时，保留已确认 authored design_brief，否则通用品类匹配。外层 *_left_*_right 对照板关系不得变成海报构图。

prepare_design_briefs 编译 job.design_brief={version:1,reference_ids,generation,layout}；design_resolution 记录状态、input_hash、brief_hash、来源与外部路径/哈希/成品区域。通过 job.design_overrides.generation/layout 修改自动默认，不反复手改派生产物。

显式参考缺失或变化为 needs_input、required=true，暂停该图新生成，不删除有效旧文件；可选通用参考不可用不阻断全局，但不能签“匹配参考”的设计结论。新空项目无产品上下文时保留needs_input，由产品证据门正常阻断，不抛选择器异常。

## 路线和唯一文案源

render_mode管产品像素来源，text_mode管营销字来源。has_marketing_text管事实/文字审核，needs_local_layout管渲染器，两者不可混用。

- none：无营销字，主图必需。
- model_native：copy={headline,body}，headline必填；当前结构上限180/200字符不是建议塞满。新版普通摄影海报可选 `model_native_reason={kind:native_poster,notes:非空理由}`，用一个标题与可选简短非数值正文，事实性卖点绑定 `job.claim_ids`；不得扩写或截断批准文案。main及pixel_composite不允许native，不可同时有本地文字、icons、panels。
- local_overlay：文字只在layout。尺寸、数值规格、步骤、FAQ、必要限制及需精确重现的营销品牌／Logo，整图使用此路线。V3优先text_groups，不与顶层headline/body/label并存。可选局部浅浮雕挂在一个组的 decorative_effect，整图仍本地排版；无字但有panels仍需本地渲染。

### Images 2.5 提示配置

新图设置 `job.prompt_profile: images_2_5_v1`，规范见 [联合 imagegen 提示契约](imagegen-prompt-profile.md)。Agent 联合加载官方 imagegen 与 prompting 指导，所有增强在本地编译／指纹绑定前进入项目输入；派发原样使用已绑定提示，官方 Skill 不额外改写或调度。当前画布与显式覆盖先解析成唯一构图，只删完整重复提示片段，批准文案及独有设计要求保留；参考编号与实际附件顺序一致。

缺该字段或显式 legacy 的旧图保持原提示字节及生成指纹，不自动迁移；现有源码哈希机制仍可要求下次本地排版／QA复核，不保证旧缓存规则哈希不变，也不重生未变底图或修改历史审核哈希。显式升级只影响该图对应依赖，不提升全局流水线版本，不改旧 attempt 或模板快照。官方指南更新不会自动改变已绑定生成提示，profile 名称不代表工具底层模型已切换。四项锁和证据结构保持，摄影允许合理透视、照明与接触变化；像素不变仍由既有合成保护实现。

新版模型质量修复先 `plan`，编译器从当前绑定 qa_report 派生 `job.prompt_edit={target_path,failures}`，将失败raw冻结为编辑目标并纳入实际提示、附件与生成指纹。此字段只描述修复，不提供新产品事实；修复旁文件仅作建议，不可绕过编译直接派发。新构图或重新创建生成计划时显式清除旧prompt_edit；普通reference_edit目标按现有pixel_source_reference_id／匹配整图来源解析，有歧义须补明确来源。

## V3有限版式

layout.version=3。recipe为photo_overlay、header_footer、photo_sidebar、scene_grid、detail_callouts、steps。

模板模式在 `layout.canvas_variants` 为 square/portrait/wide 分别保存 text_group_box、product_region_norm 和英文 composition_note；编译时仅激活当前画布。激活的产品区／文字区进入生成构图说明，实际本地排版共用该坐标。`brief.layout.product_region_norm` 是可覆盖的生成容器，显式 `job.layout.product_region_norm` 更优先；并非可绕过来源校验的实际商品像素框。未配置此字段的旧图保持六类配方默认几何。已批准排字可本地调整，确需更改生成构图仍遵循 generation_geometry_lock 原流程。

text_groups最多6个平级组：id、headline/body/label、box归一化[x,y,w,h]、align、headline_family、headline_weight、mobile_sizes、text_color、headline_treatment、surface、evidence_refs；V3设计契约还可用color_role/font_role。第一组可用默认槽位，额外组明确box。引题、主标题、说明通过现有组和对齐关系表达，不新增任意富文本系统。`headline_treatment` 仅支持 plain/outline/shadow，不能降低主填充字的对比度要求。Sans字重400/600/700，Serif400/600，回退仍检查缺字/许可/哈希。

V3 单个文字组可显式设置 `headline_max_lines: 1|2|3`，省略时仍为 2；仅调整该组标题行数上限。预检与最终渲染使用同一值，字体大小、文字容量、产品保护区与字形对比度要求不变；三行标题仍须实际查看原尺寸和 360 预览。

surface只含kind（transparent/solid/gradient）、color、opacity、padding_em、direction（horizontal/vertical）。普通卡片按内容收缩；完整页眉或侧栏使用有目的的画布/摄影分区，不用两个空文本框。

panels最多4张：id、image、box、fit（cover/contain）、source_crop、product_bbox_norm、evidence_refs。商品框相对源图片；裁切后映射并保护。canvas_background可铺不透明底色，此时隐藏底图不再作为可见商品，面板各自受保护。

每张panel.image须注册为同路径references，evidence_refs含该图ID，只有fact ID不够。生成/恢复来源需要provenance.kind、source_reference_ids、真实来源reviewed_source_hashes与实际qa_verdict。不能把生成图升级为未知材质、尺寸或配件证据。

纯本地四场景可使用pixel_composite的4个真正可见product_layers先合成raw，然后V3只排字；不用隐藏无用层伪造完成，不重复贴相同panels。

方图和A+独立构图。360px为最终图缩略图，不是移动端重排；headline>=18、body/label>=12。FAQ用明确问题headline+回答body的具名组。横幅放不下应扩展文字区、换模块或请求确认，不能改写批准文案或继续缩字。

## 审核与修复

review-prepare支持单图/同轮ready批处理，相同成品、坐标及文案复用审核包。Native reviews.model_text_review须有verdict/notes、blocks中每块id、实际text、最终bbox_norm，以及unexpected_text数组；逐字核对拼写/标点/额外声明，不能复制计划copy后签发。

Native 字形不属于本地字体／字形对比度自动检查的覆盖范围。在已有 `reviews.model_text_review.notes` 中保存实际最终 JPG 的路径／哈希、字形核心取样方法及最低对比度数值，并保存 360px 标题≥18px、正文≥12px 的观察和测量依据；不以整框平均亮度或目测代替4.5:1检查。成品编码后需要补充证据时，以 `review-prepare --force` 取得新包再提交，不修改旧已提交包；最终编码字节变化须重测，不增加输出步骤。无法验证原有要求时，使用local_overlay及正常无字底图流程，不在native成品上重复叠字。

reviews.panel_reviews[panel_id]分别记录provenance、product_identity、crop的verdict/notes。旧图片、坐标、裁切、来源或360预览变化拒绝旧提交。缺结论review_pending；native文字错走generation_repair，本地排字错走layout_repair。

visual_design说明焦点、主次、分组间距、背景用途、图文融合和参考方向；原尺寸、360预览、整套重复度均需人工判断。几何通过不自动签设计通过。

局部浅浮雕通过正常审核包的 `reviews.title_effect_review` 实际观察，填写当前 binding、逐字 transcription、unexpected_text、bbox_norm、observed_surface、verdict/notes，以及原尺寸/360可读性、承载面、透视、受光接触、产品与其他文字未变、纯装饰用途等逐项结论。计划文案、ingest或已有产品审阅都不能替代这些结论。

最终 JPG 使用字形核心遮罩检查最低对比度 4.5:1，排除抗锯齿边缘及外部阴影，保留无文字背景、字形遮罩和实际成品绑定。普通平面字与浅浮雕记录各自方法；不以文字框平均亮度放行。默认质量92失败时该图重试95，仍不通过返回修复。A/B 比较需在项目中显式统一尺寸与编码质量，不自动创建四图试验。

## 事务、缓存和队列

新图声明 generation_dependency_version=2，细节可见性只绑定本图，避免修改其他图引起重生。旧项目缺字段保留旧hash算法。已有raw升级使用 migrate-dependencies --source-manifest 的真实旧快照；重建旧依赖视图必须明确 source-kind=reconstructed_verified_dependency_view，并严格重现已ingested attempt与raw SHA后验证本图新依赖等价。不能直接手改旧generated hash。明确创建新版项目时 --allow-project-fork 只放开project_id差异，其余验证不变并记录两边项目ID。

短锁快照 → 隔离写时复制暂存 → 锁外重处理 → 目标任务与共享证据CAS → 短锁合并。单图暂存只包含全项目校验必需输入、共享报告和本图产物；所有真实声明的校验依赖即使位于revision目录也保留，省去其他图的无关raw/final/缓存。副本使用独立inode，保留冲突校验、提交日志和崩溃恢复，不同任务互不覆盖，同任务陈旧提交拒绝。

生产入口与执行次序只按 [SKILL 主流程](../SKILL.md#生产主流程)，真实并发接入见[工具薄适配](tool-orchestration.md)。派发锁内只复核真实来源内容、递归实拍证据和当前任务绑定；缺少／过期评估要求重新 plan，不生成预览或重新排版。

新项目 `scheduler_policy={version:1,mode:adaptive,max_concurrency:4}`；`concurrency`为当前上限，`network_health`沿用健康记录，额外保存epoch、当前档位成功数、升速冷却、Retry-After及tool_capacity。真实锚QA通过后从2开始，当前epoch和档位中连续两个不同attempt首次成功入库升一档，最高4，initial/quality_repair/transient_retry均适用。429降1，单次超时降一档、连续两次超时降1；退避后60秒不升速，明确Retry-After期间暂停新增调用。重复回调不计数，旧epoch/旧档位在途成功不用于升档；降档不取消在途任务。

产品生成与局部标题编辑共用容量和健康记录；本地动作独立列出，不被模型槽满截断，但来源与锚门保持生效。实际工具较低上限通过 `plan --tool-capacity 1..4 --tool-capacity-source <source> --tool-capacity-reason <evidence>` 保存，调度取配置／工具能力较小值；不能因 Agent 手工串行而无证据设为 1。旧数值缺少证据时显式报告，不暗中伪造能力证明。无 scheduler_policy 的旧项目保持原行为。`ingest --tool-returned-at <epoch>` 同次校验真实返回时刻和产物，也兼容原分步事件；不得编造开始或返回时间。

单图与批量审核准备共用实现：共享准备与排版后逐图组包，正常就绪批次只启动一次浏览器并共用字体加载，逐图错误与回滚不影响成功图。已绑定布局和内容哈希的360预览不重复编码，缺失／篡改／内容变化才重建；仍逐图看原尺寸、移动预览和细节。

同次来源评估每张源图只必要解码、方向校正和RGB转换一次，供产品裁图、画布预览、细节裁图复用，处理完释放；细节缓存先检查源、坐标、算法与内容再决定解码，细节循环不重复整图RGB转换。字形对比度只计算实际文字区域，但检查全部核心像素，原float32公式／阈值／最终JPG检查不变；成品、无字背景、字形遮罩证据用途不合并。

同次操作复用重复内容摘要与只读资源检查，写入或文件变化立即失效，提交及独立门禁使用新校验边界，不保留跨命令时间戳缓存。已验证方向、色彩、透明度的规范化PNG直接读取原字节；不确定元数据仍规范化。字体许可证／哈希／缺字检查保留，不设常驻服务。

本地改字只该图layout→review→export；局部效果的文案、字号、区域、承载面/受光、素材或遮罩改变只更新效果及受影响排版/审阅，不重生未变raw；native改字仅该图模型修复；构图改变只相关raw；元数据只export。无变化模型调用/渲染器启动/审核素材重建为0，以实际计数及文件指纹验证。总览在完整finalize交付或明确预览请求时更新，交付接续deliver；delivery-check仅用于独立诊断，不例行额外执行。

`status` 用私有只读视图返回状态、在途、阻塞、恢复建议、审核待办与 dispatch，不写清单、不取写锁、不恢复事务。同一命令／相同输入连续两次相同错误进入针对性诊断，不反复盲跑或重置 QA／修复预算；无关联的就绪任务继续。仍有效的逐项产品观察仅可保持锚点调度开放，不能替代最终整图 QA 与交付门禁。

## 计时口径

记录参考、规划、就绪等待、工具调用、交接、锁等待、编码、字体、渲染、审核准备/等待、导出及交付整理（保留旧计时字段兼容，不代表生成ZIP）。工具调用含网络和服务端排队，不是纯推理时间；审核生命周期含用户/编排等待。共享batch开销只记一次，逐图不可重复记整批累计时间。

历史generation保留lifecycle含义，不回填虚构拆分。生产工具返回瞬间捕获epoch，优先用ingest --tool-returned-at一次提交，也兼容attempt-event；取锁后时间不能代表真实交接起点。

实际字段口径：reference_compile 是本地参考选择/指纹编译，planning 是本地 prepare 校验与规划（包含 reference_compile）；外部代理看图分析和创作文案没有可观测事件时记录 unavailable，不计为 0。review_prepare 是准备执行，review_wait 是包 ready_at 至提交开始（包含观察及等待），review_submit 是本地校验/导出/QA；旧 review 仍保留生命周期。

重事务在事务 journal 的 metrics 记录快照和提交锁；轻量 transition/ingest 在 job.timings 记录 lock_wait 与 lock_recovery。批级共享 span 只挂在首个参与任务，并列出 jobs 和 includes，不能按图重复累加。布局编码/字体/浏览器/截图使用 layout_result.runtime 及批次拥有者的共享指标；交付仅记录实际发生的阶段。失败或旧历史未采集的阶段标缺失，不外推补值；纯模型计算及纯人工活跃审阅时间不可从工具/审阅生命周期反推。

验收目标而非预先承诺：真实返回→入库p95<=30秒；无暂停/限流/共享阻断时入库→下一派发p95<=10秒；当前英文例字体<5MiB；无变化模型/渲染器/审核材料重建为0。小样本标n及待验证，事务夹具不可代替真实模型p95。

同机同素材测冷启动、已就绪批处理、单图改字、无变化、断点恢复，报告中位数、p95、调用数、返工率与端到端时间。保留原始事件；设计/安全未通过不能用速度结果抵消。


## V6 默认契约与紧凑交付

`init` 创建 V3 `style_contract`、`delivery_profile`、`review_dependency_version: 2`、`review_rule_profile: scoped_v1` 及上述 scheduler_policy；新项目不创建 `copy_budget`。缺少字段或已有显式预算的旧项目保持原行为，不自动切换审核规则 profile。A+ 按用户要求启用，`--a-plus-count` 默认 6，因此普通 Listing 七张加六张 A+ 共十三张；每个 A+ 仍独立规划模块与画布。

`style_contract` version=1 保留固定设计，version=2 保留 `adaptive_per_image`。新项目 version=3 使用 `selection=design_first`、`color_roles`、`font_roles` 和 `allowed_adjustments=[lightness,position,local_surface]`；正文/标签400、mobile_sizes、`min_contrast_ratio=4.5` 保留。角色默认空，Agent 必须按产品或明确参考填写颜色、字体；没有设计色返回 DESIGN_COLOR_REQUIRED，不靠节日关键词或最高对比度补白字。

支持 headline/body/label/accent/graphic 角色；颜色为 #RRGGBB，字体角色为 `{family:sans|serif,weight:400|600|700}`，Serif仅400/600。组的 color_role/font_role 选角色，显式 group/layout 字段优先；缺少角色不能掩盖未完成的设计决策。设计色已达标即保留，失败只可在允许范围内调整明度、位置或局部柔和背景，并保存请求值与实际值及调整；仍失败进入本地图文修复，禁止静默追求最高对比、统一纯白字或96%不透明大衬底。角色共享设计关系，单图仍按用途安排层级与构图。

`copy_budget` version=1 仅为旧项目的显式兼容字段。新项目没有总量、比例或密度压缩门禁，批准文案不得由系统自动精简。尺寸、FAQ、步骤和必要限制必须原样保留；容量失败只能通过重新构图、使用既有图位或请求确认解决。旧字段的计数、必留文案和事实绑定语义不变。

### 可选主图背景规范化

`job.background_normalization` 默认缺省、不启用，既有成品字节不因该功能变化。仅主图可显式配置 `version:1`、`reviewed:true`、`protection_covers_product_and_shadow:true`；`source_pixel_sha256` 绑定 `lc_assets.pixel_hash` 计算的等比合成后、处理前完整目标 RGB 画布，不是 raw 文件 SHA。

必须提供 `background_mask` 与 `protection_mask`，两者均为 `{path,sha256}`：项目相对真实路径、哈希匹配、与目标画布同尺寸的二值灰度 L／1 图，非空且不重叠。前者仅标记人工确认的背景；后者完整排除商品及阴影，算法另保护已知的整块商品框。缺失、未审、过期、尺寸不符、符号链接或校验失败均拒绝处理，不自动猜测或拉伸遮罩。

`near_white_min` 默认 250，仅允许 250–254 整数。只将背景许可区中、RGB 三通道均达阈值且与画布边界连通的像素置为 255；白色商品高光与阴影保护区不处理。算法在 `image_prepare` 等比合成之后、本地排版／导出之前运行，保留 raw、模型 attempt 和生成指纹。配置、两个遮罩及算法进入本地 layout／export／审核依赖；最终 JPEG 仍走原 92／4:4:4 编码、254.5 白底阈值及整张背景真实视觉审核，不以局部角落通过替代全图验收。

### 可选局部浅浮雕

只用于 `layout.version=3`、`text_mode=local_overlay` 的非主图，每张最多一个文字组，`headline_treatment` 须为plain。`group.decorative_effect` 使用 `version:1`、`kind:surface_emboss`、`purpose:decorative`、非空 reason/surface/material_lighting、allowed_bbox_norm，以及 `semantic_review={decorative_only:true,contains_brand:false,contains_facts:false}`；source_reference_ids 可显式指定，缺省用本图来源。标题只允许1–5词且无数字，不带品牌、事实、规格、步骤、FAQ或限制；该组不得用 evidence_refs/claim_ids 把事实标题标为装饰。

先用现有渲染器制作完整平面版本、去目标标题的背景与字形引导；实际查看引导图后，按绑定提示由编辑工具生成候选。不透明整幅候选和灰度采用遮罩须与画布尺寸一致；遮罩完整覆盖原标题字形，只在 allowed_bbox_norm 内采用文字及接触阴影，与产品保护区及其他文字完全不相交。采用后只替换该组标题一次，品牌和正文保持本地字；失效恢复完整平面版本并记录 fallback_reason。

提示、原字形、来源、素材、遮罩、事件、绑定及真实转录保留；prepare/ingest 不签发新观察，不补造模型调用。初次、质量修复、瞬时重试历史分别计数，重新准备或降级不刷新预算。十三张套图建议最多1–2图使用，也可为零；不为凑数调用模型。

仅需要该效果时执行下列接口；实际工具调用位于 started 与 returned 之间，返回即入库，不等待整批：

```bash
python3 <skill-root>/scripts/lc_image_pipeline.py title-effect-prepare --manifest <manifest> --job <job-id> --json
python3 <skill-root>/scripts/lc_image_pipeline.py title-effect-event --manifest <manifest> --job <job-id> --attempt-id <attempt-id> --event tool_started --timestamp <actual-epoch> --json
# 使用已绑定 prompt／references 执行真实编辑工具；此处不是模拟回调。
python3 <skill-root>/scripts/lc_image_pipeline.py title-effect-event --manifest <manifest> --job <job-id> --attempt-id <attempt-id> --event tool_returned --timestamp <actual-epoch> --json
python3 <skill-root>/scripts/lc_image_pipeline.py title-effect-ingest --manifest <manifest> --job <job-id> --attempt-id <attempt-id> --artifact <candidate.png> --mask <adoption-mask.png> --json
```

时间戳必须取真实调用／返回时刻；工具失败使用 `--event failed --reason <reason>`，明确等待时加 `--retry-after-seconds <seconds>`。重试用新 attempt-id，质量修复／瞬时重试分别填 `--kind quality_repair|transient_retry --reason <reason>`，沿用同一容量、健康记录和预算。HOLD、排版失败或保护区冲突不得派发。移除效果或设 `kind:none` 保留历史并恢复平面版本，不继续绑定已退役效果；入库后回到正常逐图 review-prepare／真实观察／review-submit，不以入库成功签效果通过。

model_native 须填 model_native_reason；新版 `native_poster` 按上述普通海报规则使用，`artistic_lettering/integrated_material` 保留装饰性短标题用途。若 `embedding_decision.kind=surface_embedded_3d`，仅允许无数字、无 body、无 claim_ids 的 1–5 词装饰性标题，并记录承载面、材质/受光和理由；主图、像素合成、尺寸、FAQ、步骤、品牌和事实主张均不可用于立体编辑。真实商品印刷文字沿用来源，不是营销排字替换目标。prepare 对待模型生成的文字图用真实字体／Chromium测量容量和保护区；仅测量模式不截图、不生成预览、不签商品、对比度或成品 QA；缓存命中不启动渲染器。派发先核对 typography_dispatch_binding 对应当前文字、样式、构图和排版规则，过期须 prepare；通过后保存 generation_geometry_lock 及 attempt.geometry；后期文字位置可局部调整，确需不同模型构图时显式更新该锁并重新生成，禁止倒改历史 attempt。

`review_dependency_version: 2` 按本图所用事实、产品层、面板与递归真实来源计算审核依赖，不绑定其他图的派生预览。文字变化保留未变的产品事实证据，所有文字／布局／遮挡重新审核。review/submissions 保存真实提交；只有内容、来源、坐标与原观察校验一致时才能预填既有观察。初次生成、质量修复与瞬时重试以 generation_attempts[].kind 分别记录；prepare 不清零修复预算。

### 审核规则版本

新项目 `review_rule_profile: scoped_v1` 对视觉模块的完整真实源码，以及 pipeline／workflow 中视觉相关定义和常量计算内容摘要；仅明确排除 CLI、日志、调度、清理等无关定义，未分类新 helper 保守纳入。混合视觉函数的内容变化仍会失效，不能把阈值、视觉算法、来源或成品变化伪装为无关更新。

缺该字段或显式 `legacy` 的旧项目继续原完整源码哈希语义，本次不迁移旧项目或重写历史哈希。任何规则变化仍须完成受影响的本地审核，不能给旧结论换绑定冒充新观察；不会因此改变生成提示、版本、attempt 或 raw。

### 交付与按需清理

`delivery_profile={name: compact_jpg, jpeg_quality: 92}` 描述 JPG 成品契约，不表示自动清理：保持 canvas、4:4:4，单图 export.quality 可显式提高到95。实际输入保留一次，复用素材引用原路径；不人工复制 accepted_ 文件或把成品 PNG 再拷贝一份。`deliver` 只完成检查、成品目录准备与报告，随后立即回复成品入口；按需 `compact` 是独立动作，不阻塞交付答复。独立 HTML 分享已移除；旧 profile 的 `standalone_html:false` 被忽略，`true` 会被拒绝。旧项目须显式选择该 profile 并重新验证，不能重写旧审核哈希。

新项目有序主图／副图／A+ JPG 平铺在 `final/`，其中不交付报告、总览、预览或 ZIP。`deliver --json` 和 delivery_report.json 返回 `output_dir`、`images:[{job_id,filename,path,sha256}]`、`image_count`；清单来自当前 QA 通过任务，并逐文件核验。旧项目显式 deliver 时，对分散产物或混有其他文件的 final 建立 `delivery/images-vNNN/`，不覆盖旧版本、不改变旧编码；重复交付内容相同即复用，不重编码或重复复制。

`compact` 只整理已登记、校验一致且不再被当前依赖引用的自有缓存和历史未采用候选。来源、采用底图、当前 `prompt_edit.target_path`、两个背景遮罩、detail_refs、review/submissions 与证据 JSON 均保留；不扫描清理用户文件，不在尚有未完成任务时清理。先持久化输入／配置／成品／真实审核证据，再隔离暂存候选并复查交付，失败回滚；中断后的下一次正常写命令通过原事务恢复处理，`status` 不触发恢复。工作资料仍留项目目录，不以目录体积目标删除当前依赖。

本次运行优化不改变生成提示或PIPELINE_VERSION，既有产品底图的生成指纹不因本地实现更新失效；相关布局／审核脚本改变仍触发必要的本地复核，不改写历史哈希继承旧审核。维护验收使用无模型回归及同机1/3/13张cold/cache/single-edit/recovery回放，模型等待与本地耗时分开报告，真实端到端下一次正式生成核验。

本案例参考预算：JPG 约 5.5 MiB、必要素材和可修改工作目录目标 35 MiB 内；不同项目按必要输入量调整，依赖与质量优先。普通十三张套图 25–35 分钟仅为同等模型服务速度下的待验证目标，不是承诺。维护阶段只做真实素材压缩回放与无模型回归，下次正式生成记录端到端、模型等待、交接与本地阶段核验，不额外重生整套用于测速。
