# V6 设计与性能契约（兼容 V5）

本文件补充运行流程。V1/V2旧项目保持旧语义，明确选择V5才接入设计brief及新审阅要求；文档字段不能替代真实脚本校验。

## 参考编译

新项目默认 `design_template_policy={version:1,mode:auto}`，详见[英文模板库](design-template-library.md)。先选套系再选图位，正文与参数化提示词英文，产品与批准文案来自当前项目。`design_template_set_id/design_template_set_revision` 指定项目套系，`job.design_template_id/design_template_revision` 指定单图；已采用文本在 `design_template_selection` 与 `design_resolution.binding` 以 ID、revision、完整 snapshot 和 content_hash 固定。新库或新 revision 不自动改变已有绑定。模板模式不读旧风格原图；校验快照和编译 brief，不取消真实产品来源检查。无匹配时撰写项目原创 brief 并填写 `design_template_original_reason`，标记 matched=false，不自动入库。

以下外部参考接口仅用于未启用模板模式的旧项目，或当前明确选择的外部参考，不自动迁移：

单元索引 schema_version=1、asset_policy=external_regions_only。每项 id、绝对external_path、sha256、unit_region_norm、recipe、generation、layout、reviewed=true、product_evidence=false。区域指向单张成品，排除下载按钮和文件名；重叠编号列为排除内容，不复制进生成图。

项目可设 design_reference_units_path 与 design_reference_ids，单图 design_reference_id 更优先。未指定本轮参考时，保留已确认 authored design_brief，否则通用品类匹配。外层 *_left_*_right 对照板关系不得变成海报构图。

prepare_design_briefs 编译 job.design_brief={version:1,reference_ids,generation,layout}；design_resolution 记录状态、input_hash、brief_hash、来源与外部路径/哈希/成品区域。通过 job.design_overrides.generation/layout 修改自动默认，不反复手改派生产物。

V6 新项目使用 V3 `style_contract`，设计指定值优先；显式文字组／layout > 项目颜色与字体角色 > brief 默认 > recipe。V1 固定字体/文字色与 V2 自适应行为仅为兼容，不自动迁移。`headline_treatment={plain|outline|shadow}` 仍可用，`typography_decision` 分别记录请求设计、显式设置、解析结果及允许调整。Native 的 brief.layout 进入生成依赖；local 的字体/精确位置及局部效果只进入对应效果／layout 依赖。

显式参考缺失或变化为 needs_input、required=true，暂停该图新生成，不删除有效旧文件；可选通用参考不可用不阻断全局，但不能签“匹配参考”的设计结论。新空项目无产品上下文时保留needs_input，由产品证据门正常阻断，不抛选择器异常。

## 路线和唯一文案源

render_mode管产品像素来源，text_mode管营销字来源。has_marketing_text管事实/文字审核，needs_local_layout管渲染器，两者不可混用。

- none：无营销字，主图必需。
- model_native：copy={headline,body}，headline必填；当前结构上限180/200字符不是建议塞满。main及pixel_composite不允许native，不可同时有本地文字、icons、panels。
- local_overlay：文字只在layout。V3优先text_groups，不与顶层headline/body/label并存。可选局部浅浮雕挂在一个组的 decorative_effect，整图仍本地排版；无字但有panels仍需本地渲染。

## V3有限版式

layout.version=3。recipe为photo_overlay、header_footer、photo_sidebar、scene_grid、detail_callouts、steps。

模板模式在 `layout.canvas_variants` 为 square/portrait/wide 分别保存 text_group_box、product_region_norm 和英文 composition_note；编译时仅激活当前画布。激活的产品区／文字区进入生成构图说明，实际本地排版共用该坐标。`brief.layout.product_region_norm` 是可覆盖的生成容器，显式 `job.layout.product_region_norm` 更优先；并非可绕过来源校验的实际商品像素框。未配置此字段的旧图保持六类配方默认几何。已批准排字可本地调整，确需更改生成构图仍遵循 generation_geometry_lock 原流程。

text_groups最多6个平级组：id、headline/body/label、box归一化[x,y,w,h]、align、headline_family、headline_weight、mobile_sizes、text_color、headline_treatment、surface、evidence_refs；V3设计契约还可用color_role/font_role。第一组可用默认槽位，额外组明确box。引题、主标题、说明通过现有组和对齐关系表达，不新增任意富文本系统。`headline_treatment` 仅支持 plain/outline/shadow，不能降低主填充字的对比度要求。Sans字重400/600/700，Serif400/600，回退仍检查缺字/许可/哈希。

surface只含kind（transparent/solid/gradient）、color、opacity、padding_em、direction（horizontal/vertical）。普通卡片按内容收缩；完整页眉或侧栏使用有目的的画布/摄影分区，不用两个空文本框。

panels最多4张：id、image、box、fit（cover/contain）、source_crop、product_bbox_norm、evidence_refs。商品框相对源图片；裁切后映射并保护。canvas_background可铺不透明底色，此时隐藏底图不再作为可见商品，面板各自受保护。

每张panel.image须注册为同路径references，evidence_refs含该图ID，只有fact ID不够。生成/恢复来源需要provenance.kind、source_reference_ids、真实来源reviewed_source_hashes与实际qa_verdict。不能把生成图升级为未知材质、尺寸或配件证据。

纯本地四场景可使用pixel_composite的4个真正可见product_layers先合成raw，然后V3只排字；不用隐藏无用层伪造完成，不重复贴相同panels。

方图和A+独立构图。360px为最终图缩略图，不是移动端重排；headline>=18、body/label>=12。FAQ用明确问题headline+回答body的具名组。横幅放不下应扩展文字区、换模块或请求确认，不能改写批准文案或继续缩字。

## 审核与修复

review-prepare支持单图/同轮ready批处理，相同成品、坐标及文案复用审核包。Native reviews.model_text_review须有verdict/notes、blocks中每块id、实际text、最终bbox_norm，以及unexpected_text数组；逐字核对拼写/标点/额外声明，不能复制计划copy后签发。

reviews.panel_reviews[panel_id]分别记录provenance、product_identity、crop的verdict/notes。旧图片、坐标、裁切、来源或360预览变化拒绝旧提交。缺结论review_pending；native文字错走generation_repair，本地排字错走layout_repair。

visual_design说明焦点、主次、分组间距、背景用途、图文融合和参考方向；原尺寸、360预览、整套重复度均需人工判断。几何通过不自动签设计通过。

局部浅浮雕通过正常审核包的 `reviews.title_effect_review` 实际观察，填写当前 binding、逐字 transcription、unexpected_text、bbox_norm、observed_surface、verdict/notes，以及原尺寸/360可读性、承载面、透视、受光接触、产品与其他文字未变、纯装饰用途等逐项结论。计划文案、ingest或已有产品审阅都不能替代这些结论。

最终 JPG 使用字形核心遮罩检查最低对比度 4.5:1，排除抗锯齿边缘及外部阴影，保留无文字背景、字形遮罩和实际成品绑定。普通平面字与浅浮雕记录各自方法；不以文字框平均亮度放行。默认质量92失败时该图重试95，仍不通过返回修复。A/B 比较需在项目中显式统一尺寸与编码质量，不自动创建四图试验。

## 事务、缓存和队列

新图声明 generation_dependency_version=2，细节可见性只绑定本图，避免修改其他图引起重生。旧项目缺字段保留旧hash算法。已有raw升级使用 migrate-dependencies --source-manifest 的真实旧快照；重建旧依赖视图必须明确 source-kind=reconstructed_verified_dependency_view，并严格重现已ingested attempt与raw SHA后验证本图新依赖等价。不能直接手改旧generated hash。明确创建新版项目时 --allow-project-fork 只放开project_id差异，其余验证不变并记录两边项目ID。

短锁快照 → 隔离写时复制暂存 → 锁外重处理 → 目标任务与共享证据CAS → 短锁合并。可恢复日志保护多文件提交，不同任务互不覆盖，同任务陈旧提交拒绝。暂存必须包括Manifest所有真实声明依赖，即使文件位于revision目录；只跳过不需要的历史报告/归档。

ingest仅校验当前attempt/提示/artifact并原子提交，立即释放生成槽。锚图通过后并发2，限流降1；审核/排版独立推进，不为凑本地批次等待模型。

已验证方向、色彩、透明度的规范化PNG直接读取原字节；不确定元数据仍规范化。按实际文字加载最小字体，不省略许可证/哈希/缺字检查。就绪批次复用浏览器，不设常驻服务。

本地改字只该图layout→review→export；局部效果的文案、字号、区域、承载面/受光、素材或遮罩改变只更新效果及受影响排版/审阅，不重生未变raw；native改字仅该图模型修复；构图改变只相关raw；元数据只export。无变化模型调用/渲染器启动/审核素材重建为0，以实际计数及文件指纹验证。总览在完整finalize交付或明确预览请求时更新，之后delivery-check。

## 计时口径

记录参考、规划、就绪等待、工具调用、交接、锁等待、编码、字体、渲染、审核准备/等待、导出、打包。工具调用含网络和服务端排队，不是纯推理时间；审核生命周期含用户/编排等待。共享batch开销只记一次，逐图不可重复记整批累计时间。

历史generation保留lifecycle含义，不回填虚构拆分。生产工具返回瞬间捕获epoch，再attempt-event；取锁后时间不能代表真实交接起点。

实际字段口径：reference_compile 是本地参考选择/指纹编译，planning 是本地 prepare 校验与规划（包含 reference_compile）；外部代理看图分析和创作文案没有可观测事件时记录 unavailable，不计为 0。review_prepare 是准备执行，review_wait 是包 ready_at 至提交开始（包含观察及等待），review_submit 是本地校验/导出/QA；旧 review 仍保留生命周期。

重事务在事务 journal 的 metrics 记录快照和提交锁；轻量 transition/ingest 在 job.timings 记录 lock_wait 与 lock_recovery。批级共享 span 只挂在首个参与任务，并列出 jobs 和 includes，不能按图重复累加。布局编码/字体/浏览器/截图使用 layout_result.runtime 及批次拥有者的共享指标；交付仅记录实际发生的阶段。失败或旧历史未采集的阶段标缺失，不外推补值；纯模型计算及纯人工活跃审阅时间不可从工具/审阅生命周期反推。

验收目标而非预先承诺：真实返回→入库p95<=30秒；无暂停/限流/共享阻断时入库→下一派发p95<=10秒；当前英文例字体<5MiB；无变化模型/渲染器/审核材料重建为0。小样本标n及待验证，事务夹具不可代替真实模型p95。

同机同素材测冷启动、已就绪批处理、单图改字、无变化、断点恢复，报告中位数、p95、调用数、返工率与端到端时间。保留原始事件；设计/安全未通过不能用速度结果抵消。


## V6 默认契约与紧凑交付

`init` 创建 V3 `style_contract`、`delivery_profile`、`review_dependency_version: 2`；新项目不创建 `copy_budget`。缺少字段或已有显式预算的旧项目保持原行为。A+ 按用户要求启用，`--a-plus-count` 默认 6，因此普通 Listing 七张加六张 A+ 共十三张；每个 A+ 仍独立规划模块与画布。

`style_contract` version=1 保留固定设计，version=2 保留 `adaptive_per_image`。新项目 version=3 使用 `selection=design_first`、`color_roles`、`font_roles` 和 `allowed_adjustments=[lightness,position,local_surface]`；正文/标签400、mobile_sizes、`min_contrast_ratio=4.5` 保留。角色默认空，Agent 必须按产品或明确参考填写颜色、字体；没有设计色返回 DESIGN_COLOR_REQUIRED，不靠节日关键词或最高对比度补白字。

支持 headline/body/label/accent/graphic 角色；颜色为 #RRGGBB，字体角色为 `{family:sans|serif,weight:400|600|700}`，Serif仅400/600。组的 color_role/font_role 选角色，显式 group/layout 字段优先；缺少角色不能掩盖未完成的设计决策。设计色已达标即保留，失败只可在允许范围内调整明度、位置或局部柔和背景，并保存请求值与实际值及调整；仍失败进入本地图文修复，禁止静默追求最高对比、统一纯白字或96%不透明大衬底。角色共享设计关系，单图仍按用途安排层级与构图。

`copy_budget` version=1 仅为旧项目的显式兼容字段。新项目没有总量、比例或密度压缩门禁，批准文案不得由系统自动精简。尺寸、FAQ、步骤和必要限制必须原样保留；容量失败只能通过重新构图、使用既有图位或请求确认解决。旧字段的计数、必留文案和事实绑定语义不变。

### 可选局部浅浮雕

只用于 `layout.version=3`、`text_mode=local_overlay` 的非主图，每张最多一个文字组，`headline_treatment` 须为plain。`group.decorative_effect` 使用 `version:1`、`kind:surface_emboss`、`purpose:decorative`、非空 reason/surface/material_lighting、allowed_bbox_norm，以及 `semantic_review={decorative_only:true,contains_brand:false,contains_facts:false}`；source_reference_ids 可显式指定，缺省用本图来源。标题只允许1–5词且无数字，不带品牌、事实、规格、步骤、FAQ或限制；该组不得用 evidence_refs/claim_ids 把事实标题标为装饰。

先用现有渲染器制作完整平面版本、去目标标题的背景与字形引导，再由实际编辑工具生成候选。整幅候选和灰度采用遮罩须与画布尺寸一致；遮罩完整覆盖原标题字形，只在 allowed_bbox_norm 内采用文字及接触阴影，与产品保护区及其他文字完全不相交。采用后只替换该组标题一次，品牌和正文保持本地字；失效恢复完整平面版本并记录 fallback_reason。

提示、原字形、来源、素材、遮罩、事件、绑定及真实转录保留；prepare/ingest 不签发新观察，不补造模型调用。初次、质量修复、瞬时重试历史分别计数，重新准备或降级不刷新预算。十三张套图建议最多1–2图使用，也可为零；不为凑数调用模型。

model_native 仍须 model_native_reason={kind: artistic_lettering|integrated_material, notes: 非空理由}。若 `embedding_decision.kind=surface_embedded_3d`，仅允许无数字、无 body、无 claim_ids 的 1–5 词装饰性标题，并记录承载面、材质/受光和理由；主图、像素合成、尺寸、FAQ、步骤、品牌和事实主张均不可用。真实商品印刷文字沿用来源，不是营销排字替换目标。prepare 对待模型生成的文字图用真实字体／Chromium测量容量和保护区；仅测量模式不截图、不生成预览、不签商品、对比度或成品 QA；缓存命中不启动渲染器。派发先核对 typography_dispatch_binding 对应当前文字、样式、构图和排版规则，过期须 prepare；通过后保存 generation_geometry_lock 及 attempt.geometry；后期文字位置可局部调整，确需不同模型构图时显式更新该锁并重新生成，禁止倒改历史 attempt。

`review_dependency_version: 2` 按本图所用事实、产品层、面板与递归真实来源计算审核依赖，不绑定其他图的派生预览。文字变化保留未变的产品事实证据，所有文字／布局／遮挡重新审核。review/submissions 保存真实提交；只有内容、来源、坐标与原观察校验一致时才能预填既有观察。初次生成、质量修复与瞬时重试以 generation_attempts[].kind 分别记录；prepare 不清零修复预算。

`delivery_profile={name: compact_jpg, jpeg_quality: 92}`：只导出最终 JPG，保持 canvas，4:4:4；单图 export.quality 可显式提高到95。所有实际输入保留一次，复用素材引用原路径；不再人工复制 accepted_ 文件或把成品 PNG 再拷贝一份。`deliver` 完整检查后保存输入、配置、成品及真实审核记录的绑定，再删除已登记、校验一致、未被引用的自有缓存和历史未采用候选。原始来源、采用底图、detail_refs、review/submissions 与证据 JSON 均保留；不扫描清理用户文件，不在尚有未完成任务时清理。独立 HTML 分享已移除；旧 profile 的 `standalone_html:false` 被忽略，`true` 会被拒绝。旧项目必须显式启用该 profile 并重新验证，不能用重写哈希继承不再适用的旧结论。

本案例预算：JPG约5.5 MiB、必要素材和可修改工作目录目标35 MiB内；不同项目按必要输入量调整，质量优先。普通十三张套图25–35分钟仅为同等模型服务速度下的目标；维护阶段只做真实素材压缩回放与无模型回归，下次正式生成记录端到端、模型等待、交接与本地阶段核验，不额外重生整套用于测速。
