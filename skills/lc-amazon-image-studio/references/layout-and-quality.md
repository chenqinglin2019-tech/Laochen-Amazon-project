# 商品区域质量与内置排版

## 清晰度检查与证据

检查范围是每个任务实际使用的商品区域及关键细节，不是整张文件，也不是默认第一张参考图。读取原尺寸商品裁图、必要细节和按成品占比呈现的预览。

判断四个互相独立的问题：

- **有效像素：** 商品占图大小及输出占比，实际需要放大多少。
- **可辨认程度：** 失焦、运动模糊、局部软化、压缩块、噪点、磨皮、锐化光晕是否破坏轮廓或纹理。
- **证据完整性：** 必须展示的结构、材质、文字和部件是否能由该图或其他实拍证实。
- **画面适配：** 参考与目标的视角、透视、姿态、光照、接触和遮挡是否兼容。

边缘能量等算法信号仅用于提醒检查。不能用单一锐度阈值把光滑塑料、玻璃判为不清晰，也不能把高像素、锐化边缘或清晰背景判为主体清晰。重采样放大后的低清图仍是低清证据。

逐参考记录 `quality_review`：`clarity` 为 `clear/mild_softness/blurred/unknown`，`evidence` 为 `sufficient/insufficient/unknown`，同时记录 `defects`、`notes`、`reviewed_sha256` 及 `reviewed_region_fingerprint`。更改原图或商品框后审阅必须失效，不能把旧哈希改成新值代替重看。区域期望值为 `reference.quality_metrics.region_fingerprint`。先逐参考完成目视审阅并绑定源文件及区域指纹，再重新 `prepare` 取得 `job.assessment_context_fingerprint`，最后完成任务审阅并绑定；不能复制参考审阅前的旧任务指纹。

逐任务记录 `source_assessment`：`scene_fit` 为 `matched/local_change/new_view/unknown`，`evidence` 为 `sufficient/insufficient/unknown`，`degradation` 为 `none/mild/localized/global/unknown`，另写 `reason`、`reviewed_reference_hashes` 和 `reviewed_context_fingerprint`。任务可以整合多个角度和局部实拍，不能仅因参考名称不等于目标视角名称而判定无证据。不同命名却实际兼容时，可在 `matched_reference_ids` 显式记录已审阅的适配参考；不能从不兼容角度里挑最清晰一张来通过合成检查。`job.render_decision.required_reference_hashes` 包含必须可见 P0/P1 的局部来源，任务审阅也要绑定它们。

## 生成方式决策

`pixel_composite`、`reference_edit`、`reference_generate` 不设固定优先顺序。以能满足清晰度和真实性的最小操作为准：

1. 商品清晰且画面适配：使用原像素合成。使用 `job.render_decision.pixel_source_reference_id`，不要默认第一张参考。背景、遮罩、接触阴影和真实商品图层一起构成目标画面。
2. 轻微噪点或软化：可保守处理，但必须重新看成品。不能以伪造纹理、变薄边缘或锐化光晕制造“高清感”。
3. 角度正确但主体整体模糊：其他实拍足以确认结构、材料及必需细节时，允许同视角参考重绘。
4. 仅局部模糊：有清晰局部证据时优先定向编辑或替换局部；保护其余已清晰区域。
5. 新视角、姿态、受光或互动关系：使用证据约束的参考重绘，重新检查结构、部件关系、尺寸感和接触。
6. 必需 P0/P1 在所有实拍都不可辨认：该图阻断，先调整构图或补资料。重绘不能凭空产生真实接口、文字或材质证据。

仅在原像素合成时，目标商品框是可用容器，按等比 contain 后商品实际像素与源商品有效像素计算倍率，最终实际商品框另记；不能用容器长宽比拉伸商品。倍率规则：`≤1.25×` 可用，`1.25–1.75×` 边缘可用但不用于微距／关键材质特写，`>1.75×` 禁止直接复用。倍率通过仍须商品清晰；重绘用证据完整性而非这个倍率作为前提。

确认过的修复或重绘素材可供相同视角复用。其 `reference.provenance` 填 `kind: generated`（修复母版可为 `restored`；原始实拍为 `real_photo`）、实拍 `source_reference_ids`、`reviewed_source_hashes` 和 `qa_verdict: pass`；原实拍及其有效审阅必须仍存在。原始证据变化、素材变化或新图需要未支持表面时重新审阅，不能把生成素材纳入“实拍证实”链条。

像素合成还会检查每一层实际采用的素材。`job.layer_asset_hashes` 由 `prepare` 自动计算，绑定商品资产、遮罩、裁框、目标框及实际放大倍率，并进入任务审阅指纹；它不是手填审阅结论。

使用另外的抠图资产或附加遮罩时，原尺寸检查其来自对应实拍、没有改动产品结构后，填写 `layer.source_binding`：`reviewed: true`、`reviewed_asset_sha256`、`reviewed_mask_sha256`（无遮罩为 null）及 `source_reference_hashes`。来源哈希至少覆盖本层 `reference_id`、`source_reference_ids` 和生成素材的实拍依赖；填写后重新 `prepare`，再绑定新的任务审阅指纹。多组件层通过 `matched_reference_ids` 明确确认各自视角，不能借主商品的清晰审阅掩盖模糊或不适配的组件层。

`layer.asset_origin` 必须符合其参考的 `provenance.kind`：实拍为 `original`，生成／修复分别为 `generated/restored`；不能把重绘层标为原像素。

## 关键细节和新视角

记录 `critical_details` 中每个细节的 P0/P1/P2、证据级别、视觉可确认性、来源视角、相对于源商品框的坐标，以及每张图 `required/optional/hidden` 的可见性。

每个裁图最长边低于 32 px、最短边低于 8 px，或虽够大却仍模糊、反光遮挡、无法辨认时，均不能算已证实。`user_claim_only` 只证明文字主张，不证明位置和形状；没有位置证据不能猜坐标。

完成所有原尺寸来源检查后才设置 `critical_detail_census_completed=true`。必须展示的 P0/P1 要有独立参考／成品对照和明确结论，P2 通过不能抹去此前的失败。

新角度的产品框和细节位置需重新查看成品确定。`detail_output_bbox_norms` 使用整个最终画面的归一化 `[x,y,width,height]`；它只决定 QA 裁图位置，不能授权将接口移到其他表面。

## 内置排版系统

先独立选择 `text_mode`：`none` 无营销文字，`local_overlay` 默认用本地精确排版；可选局部浅浮雕仍留在此路线，`model_native` 保留模型设计整张短文案海报的旧语义。商品生成的 `render_mode` 仍由清晰度、视角与证据决定；`model_native` 不用于主图或 `pixel_composite`，不能混入本地文字、图标和 panels 造成重复叠字。

本地版式属于本 skill：HTML/CSS/SVG、随包字体和图标经 Playwright／Chromium 渲染，Pillow 合成及导出。就绪任务在同批复用浏览器，资源本地加载；文案按文本转义，不执行 HTML 或脚本。native 路线跳过排字与字体加载，不跳过最终原尺寸、360 预览、产品及设计审阅。

生成前填写逐图 `design_brief`。local 路线还填 `job.layout` 的产品区、文字组与 `protected_regions`；native 路线把准确短 copy 和层级、阅读顺序、图文关系写进生成提示。保护区至少包含实际关键结构、人物脸部和操作接触区域，需要时包含整个产品。规划阶段先测文字容量与素材可用性，不到生成后才挤字。

### 参考驱动与版本兼容

新项目默认[英文文本模板模式](design-template-library.md)：套系风格固定、构图按方图／竖图／A+ 适配。采用模板的英文描述与完整快照进入项目，不依赖历史风格原图；真实产品照片和事实绑定不变。模板编译后提供当前画布的文字区与 `product_region_norm`，后者是生成容器，不是审核认定的真实像素框；本地布局、生成留白与保护检查共用同一几何。逐图原尺寸和360预览对照采用的设计说明审阅，不因没有历史样本图片而省略设计质检。

以下原图索引／哈希规则仅针对旧外部参考模式，或明确选择该模式的用户参考：

本轮用户参考优先于已确认项目设计，通用库仅补充适合当前品类和用途的参考。截图解析为单张成品单元，保存源哈希和区域；原图／成品并列的对比板结构、UI 按钮及编号不属于目标设计。只提取摄影、明暗、层级、分区、裁切与底框用途，禁止迁移样本商品、文案、CTA、品牌、包装、认证或未经确认主张。

V5 的 `design_brief.generation` 进入本图生成依赖，`design_brief.layout` 为本地设计默认值；native 还将 layout 作为整体海报的排版设计指令。新项目 `style_contract.version=3` 按设计选颜色与字体角色，显式组／layout 优先于项目角色，再由 brief／配方提供其他默认值；V1 固定设计、V2 自适应规则仅为兼容。`typography_decision` 保留指定值与采用值；已满足4.5:1的颜色不换成更高对比色。失败时只按 allowed_adjustments 调整明度、位置或局部柔和背景，仍失败则修复该图，不静默增加大底框。`headline_tone` 等描述不能直接当字体 API；使用明确的 `color_role/font_role/headline_family/headline_weight/text_color/headline_treatment/align` 等字段。选中用户参考失效时本图设计待确认，不能签样本一致性通过或派发依据旧参考的新生成。

旧 V1/V2 缺少 `text_mode` 时保持原行为与依赖指纹。V2 的 `layout.version: 2`、`text_group`、`text_surface`、`mobile_sizes` 和 FAQ/item slots 继续可用，`headline_family` 为 `sans|serif`、`headline_weight` 为 `400|600`。新项目用 V3，不自动改写旧项目。所有坐标区分 raw 画布和最终输出，不因换字体而冒改生成时锁定的构图。

### V3 有界设计配方

`layout.version: 3` 使用六类 `recipe`：`photo_overlay` 全幅叠字、`header_footer` 页眉／页脚、`photo_sidebar` 摄影侧栏、`scene_grid` 四场景、`detail_callouts` 细节卡／标注、`steps` 步骤分镜。它们是可配置构图起点，不要求全套重复使用一种风格；方图、竖图与 A+ 横幅分别安排分区，不能直接挤压方图。

- `text_groups` 最多 6 个扁平组，使用独立 `id`、归一化 `box`、`headline/body/label`、`align`、`headline_family/headline_weight`、`mobile_sizes`、`text_color`、`gap_em` 与 `surface`；颜色/字体角色用 `color_role/font_role`。利用现有组表达引题、主标题、说明，FAQ 用每组 question headline + answer body，不与 V2 `faq` 混填。
- 一组内标题和正文共享对齐线并紧凑排列；不要同时填写顶层 headline/body/label 和 `text_groups`。native 文案只放 `job.copy.headline/body`，不复制到 layout。
- `surface` 可用 `transparent/solid/gradient`，可设 color、opacity、padding_em、direction。普通卡片随内容收缩；完整页眉／侧栏是构图区，不是给标题和正文各画一个空框。整片背景用已规划的摄影／画布分区表达。
- `panels` 最多 4 张，每张用 `image/evidence_refs/box/fit/source_crop/product_bbox_norm`。crop 和 product bbox 相对该素材，`cover/contain` 后重新映射保护区域，不能沿用原坐标；可用 `canvas_background` 显式设置画布底色。
- panel 图片必须匹配已注册 reference 的路径，`evidence_refs` 包含该 reference ID；只有 fact ID 不构成像素证据。生成／修复素材保留实拍依赖、哈希及已验收 provenance，不能当新实拍证据。
- V3 保留已实现的图标、编号、尺寸箭头与引线，最多 4 个辅助项。图标不是装饰性认证；尺寸仍需数据来源，步骤不得暗示未确认功能或包含物。

详细字段和混合路线接口见 [V5 设计与性能](v5-design-and-performance.md)。

### 兼容模板与辅助项

以下六种 `template` 保留语义及旧版兼容，V3 在其基础上指定 `recipe`：

- `scene`：完整场景配顶部或侧面留白，适合使用场景。
- `split`：产品与说明分区，适合适配／安装。
- `benefits`：主视觉配底部最多三个卖点。
- `detail`：主商品配最多三处局部说明。
- `dimensions`：已证实尺寸及适配标注，不从透视图像测量商品尺寸。
- `components`：真实包含物或短操作步骤。

主题使用 `neutral/warm/technical/playful` 提供参考方向和间距，不替产品决定最终配色。V3 设计契约的颜色与字体角色默认空，按品牌、卖点、材质和摄影气质选择，不沿用万圣节案例配色；共享角色关系而非逐图随机字体。随包 Noto 字体按实际文字、地区字形、字体与字重最小加载，氛围标题可选Regular，功能标题可选粗体；保留缺字、许可证及哈希检查，不回退未知系统字体。正文与标签默认400，旧V1仍固定Sans标题700；V2旧自适应行为保留。已验证规范化PNG可走安全原字节路径，其他图像先规范化。

V1/V2 的文案入口为 `headline/body/items`；`split` 不接受辅助项，其余最多三个。V3 主文案使用上述 `text_groups`，辅助项最多四个。商品自身标签属于真实产品视觉，与营销文案分开。

辅助项字段：

- `text`：短标签或步骤；`evidence_refs`：关联当前项目的事实／来源 ID，不得用不存在的 ID 假装有依据。
- `icon`：内置 `check/leaf/ruler/tool/layers/care/water/light`；不能暗示未经证实的认证或功能。
- `image`：项目内的 PNG/JPEG/WebP，若引用清晰细节，保留来源。
- `target`：`detail` 必需的归一化指向点；`detail` 同时必须有 `image` 和 `evidence_refs`。
- V2 `leader_waypoints`：最多 4 个归一化 `[x,y]` 中间点，用于绕开其他局部图片；起点来自本项图片边缘，终点仍为 `target`。引线穿过其他局部图片会被 QA 拒绝。
- `axis`：`dimensions` 使用 `horizontal/vertical`，`dimension_points` 可指定两个最终画布归一化端点；箭头位置由构图确定，尺寸文本必须含实测数值、单位和 `evidence_refs`，不能从端点距离反推物理尺寸。
- `components` 有图片时关联证据；没有图片时以序号表达真实步骤。

`protected_regions` 接受 `[x,y,w,h]` 或 `{bbox:[x,y,w,h],kind:"face"}` 等描述。`text_surface` 可选 `transparent/solid/gradient`，`text_color` 使用 `#RRGGBB`；`direction` 默认为语言对应方向，必要时明确 `ltr/rtl`。V2 的 `mobile_sizes` 是最终图片缩放至 360 px 宽时使用的 CSS px token，实际像素为 `token × canvas_width / 360`；它保证该预览的字号，不产生独立移动端布局或重排图。旧 `font_sizes` 仍按 2000 像素短边范围处理。

## 布局规则与失败处理

- 安全边距默认短边的5%；一张图一个核心结论。标题优先不超过两行，完整保留批准的标题和正文，不按30%目标删词或改写；V1/V2辅助项最多三个，V3最多四个。不要为了填满版式而新增空泛文案。
- 2000 像素短边默认标题 120–160 px、正文 72–88 px、标签 64–80 px；其他尺寸按比例适配，真实排版以字体度量为准。wide A+ 的 360 px 预览是同一最终图片的等比缩放预览，不是独立布局；以 `mobile_sizes` 的宽度换算保证字号并实际检查可读性。
- 保持必要的数字与单位、品牌及限定词组合；德文长词、中日韩换行、阿拉伯语从右向左都需查看实际渲染。
- 文字溢出先调整文字区或换配方；仍无法容纳则保留原文并请求确认，不以裁字、省略关键条件、自动精简或无限缩字放行。V2/V3 mobile 的最小 token 为 headline 18、body 12、label 12；native 也按 360 px 预览实查，不因模型排字而降低标准。
- 背景处理按信息用途选择：自然留白可直接叠字，项目允许local_surface时可用局部柔和渐变；已规划页眉／侧栏可成为完整分区。禁止因对比度失败静默换白字或增加整块实色框，也不要把“无框衬线字”固定套到整套。
- 文字块、卡片及引线不能遮挡保护区；自动检查实际行数、溢出、字体覆盖、元素碰撞、保护区和安全边距，最终编码后检查字形核心最低4.5:1对比度。整框平均亮度、阴影和外轮廓不能代替主字形检查，自动结果仍不替代目视审阅。
- local路线缺字、溢出、碰撞进入本地布局修复；颜色、文字或局部背景修正只重排该图。局部浅浮雕只修相关效果/排版，失效时恢复完整平面字；旧native错字或设计失败仍进入该图模型修复，不重复叠本地字。改变生成构图才重生相关底图，按受控次数停止无效试错。

### 局部浅浮雕与保护

在非主图的一个V3文字组上配置 `decorative_effect.kind=surface_emboss`，该组 `headline_treatment=plain`，整图仍为local_overlay。只接收1–5词、无品牌、数字和事实的装饰性标题，明确承载面、材质/受光、采用范围和语义判断。普通说明、尺寸、步骤和FAQ不进入效果；十三张套图建议最多1–2张，也可不用，不强制先做四张样图。

现有渲染器先生成平面引导及字形遮罩，外部实际编辑工具返回候选，再用同画布灰度遮罩采用文字和接触阴影。采用范围须覆盖原标题字形、位于允许区域内，且与产品及其他文字完全不相交；合成只替换该标题一次，品牌和正文仍为本地字。保留采用素材、遮罩、提示与来源，输入变化使旧效果和审核失效；降级时恢复平面版本并记录原因。

## 成品清晰度与视觉验收

产品真实性与清晰度单独判断：尺寸结构正确但商品模糊，或非常锐利但纹理／接口虚构，均不能通过。查看原尺寸商品及细节，检查局部失焦、假锐化、塑料化、贴图边缘及标签错误。

原尺寸看全部文字与细节，360 px 宽预览看文字主次及可读性，再对照选中成品参考和整套总览检查焦点、分组、间距、背景用途、图文融合、重复度。自动碰撞或尺寸检查不能签发设计通过。native 另转录实际文字及区域，逐字核对并盘点意外小字、徽章和声明；不能只看计划文案。

浅浮雕另在正常审核包填写 `title_effect_review` 的实际转录、区域、承载面、透视、受光接触、产品与其他文字未变、原尺寸/360可读性；普通文字与浅浮雕分别记录检查方法。最终JPG字形核心最低4.5:1，质量92失败时仅该图重试95，仍失败则修复。A/B须由项目明确统一画布、编码质量和对照条件。产品保护先核对统一尺寸的无损合成，再检查JPEG细字与效果边缘损失，不声称有损成品与源PNG逐点相同。

## V5 运行协调接口

- 参考选择按内容指纹复用；V5 编译为 `design_brief` 并进入相关阶段依赖，产品事实始终独立。显式参考缺失只暂停依赖它的新生成与设计验收，不删除已有素材或阻断其他图。
- `attempt_id/prompt_hash/raw_output` 绑定本次模型调用；raw 返回立即 ingest，幂等冲突检查保留。local 排字只消费已绑定输入，native 成品不得重新叠营销字；审核不占生成 slot。
- `raw_product_bbox_norm` 相对 raw，`output_product_bbox_norm/detail_output_bbox_norms` 相对最终输出。panels 另依据 crop/fit 映射自身保护区；改变坐标或素材后重新 `review-prepare`，逐 panel 审来源、产品一致性与裁切。
- `review-prepare --jobs` 只合并已经就绪的任务，复用输入与坐标未变的审核包、360 预览和对照；实际看图后 `review-submit`。模型文字审阅与设计审阅都绑定当前成品；待审不等于导出失败。
- 重处理在独立暂存区锁外执行，短锁校验及提交，拒绝陈旧结果；批级共享计时只记录一次。总览在全项目 `finalize` 时更新或复用，单图改字不重做全套总览。
