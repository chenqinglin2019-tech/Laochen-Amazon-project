# 生产规则（V7）

硬规则与循环上限见 SKILL.md §3–§4，此处不重复；字段见 [fields.md](fields.md)。

## 图位策略

默认 7 张（顺序可替换；不用无依据尺寸、空泛特写或假前后对比凑数）：

| 图位 | 核心结论 |
|---|---|
| `01_main` | 白底展示实际商品及包含物，无文案（SKILL §3 主图规则） |
| `02_size_or_components` | 已确认的尺寸或套装内容 |
| `03_primary_use_case` | 最有价值的真实使用任务 |
| `04_compatibility_or_installation` | 适配、连接、安装或操作逻辑 |
| `05_material_or_detail` | 有清晰实拍证据的材质、工艺、结构 |
| `06_storage_or_package` | 收纳、携带、包装或完整包含物 |
| `07_problem_solution` | 解决一个真实购买顾虑 |

- **策略分支**：用户给出任一图位意图就用 `user_planned`，保留其意图并补齐空缺；否则用 `competitor_learning`，只学竞品的信息顺序与目的，不抄画面和主张。
- **A+**：`init --include-a-plus --a-plus-modules name[:WxH],...` 逐图设模块与画布（默认 6 个，`--a-plus-count` 调数量）；每个模块独立构图，不把方图压扁成横幅。
- **每张图**：一个核心结论和焦点；记录目标视角、参考依据、render_mode 理由、text_mode、产品区、细节可见性、文案来源、design_brief；拼版逐 panel 写来源与阅读顺序。
- **产品检查点**（不加审批轮次）：买家、任务、环境、最大顾虑；已确认规格；未知面；四项锁与 P0/P1。缺单图资料只停该图，共享身份不明才阻断整套；未确认规格 HOLD，不进队列和交付。
- **文案/场景**：标题一个结果、正文必要限定、标注给证据；数值/兼容/性能/认证须有来源，不加保证章、购买按钮、排名或贬低竞品。场景解释用法，支撑、接触、遮挡物理可信。

## 品类侧重

跨品类时按买家的主要购买顾虑归类（如厨房抽屉用的理线器归收纳，狗狗车载安全绳归宠物）。

| 品类 | 买家关心 → 重点图位 | 场景 / 避免 |
|---|---|---|
| 工具/五金 | 适配、耐用、安装、套件完整 → 组件、安装、材质、问题解决 | 安装/拧紧/干活中 / 奢华生活方式 |
| 家居/收纳/厨房 | 放哪、容量、省空间 → 使用、收纳、问题解决、尺寸 | 真实台面、橱柜、抽屉 / 讲不清功能的客厅大片 |
| 美妆个护 | 舒适、卫生、质地、用法 → 使用、材质、包装 | 干净个护环境 / 夸大或医疗化主张 |
| 宠物 | 尺码、安全、好用、易洗 → 使用、尺码、材质 | 真实宠物行为 / 不可能姿势、不安全用法 |
| 汽车/骑行 | 兼容、安装位置、耐用 → 安装、材质、尺寸 | 装在对应车辆上 / 安装逻辑含糊、商品太小 |
| 电子/桌面 | 接口、兼容、线缆逻辑 → 使用、兼容、细节 | 桌面、充电、出行 / 遮住产品的霓虹科技风 |

## 区域质量与生成路线

来源审阅一次完成：`source-review-prepare` → 看 `review/source/sheet.jpg`（必要时看原尺寸裁图）→ 按包内说明逐参考填 `quality_review`（clarity/evidence/defects/notes）、逐图填 `source_assessment`（scene_fit/evidence/degradation/reason），全部 P0/P1 来源看过后才设 `critical_detail_census_completed` → `source-review-submit`。一个事务内绑定参考审阅与任务上下文指纹，无需手抄。只看实际使用的商品区域和细节；高像素、锐化边缘、清晰背景都不等于主体清晰。

| 情况 | 路线 | 要点 |
|---|---|---|
| 商品清晰、视角匹配、有可用遮罩/图层 | `pixel_composite` | 用 `render_decision.pixel_source_reference_id`，不默认第一张参考；模型只生成背景 |
| 商品清晰、视角匹配，但没有遮罩 | `reference_edit`（编辑背景、保留商品） | 想复用原像素：`cutout --manifest M --reference R` → 看 `review/cutouts/<ref>-overlay.jpg` → 确认后按返回的 `suggested_layer` 填 product_layers → plan |
| 轻微软化/噪点 | `reference_edit` 保守处理 | 必须复查；伪造纹理、锐化光晕不算改善 |
| 仅局部模糊，有清晰局部证据 | `reference_edit` 定向编辑 | 保护其余清晰区域 |
| 角度对但整体模糊，其他实拍足以确认结构与细节 | `reference_generate` 同视角重绘 | 依据证据完整性，不看放大倍率 |
| 新视角、姿态、受光或互动 | `reference_generate` | 重查结构、部件关系、尺寸感和接触 |
| 必需 P0/P1 在所有实拍都不可辨认 | 阻断该图 | 补资料或改构图；重绘不能产生真实接口、文字或材质证据 |

- 合成放大倍率：≤1.25× 可用；1.25–1.75× 边缘可用（不用于微距/关键材质）；>1.75× 禁用。细节裁图最长边 <32 px、最短边 <8 px 或无法辨认都不算证实；`user_claim_only` 不证明位置和形状。
- 已验收生成/修复素材可同视角复用，`provenance` 保留实拍依赖，不能成为未知事实证据；附加遮罩层填 `layer.source_binding`。

## 提示与参考角色

- `prompt_profile: images_2_5_v1` 是本地编译器版本（不代表底层模型）；旧图保留原提示字节。**提示措辞任何变化（含手改 scene/composition/lighting）都会改变生成指纹并重生该图**；只改本地文字不重生。
- 附件编号严格等于 `generation_reference_paths` 的实际顺序：整品证据 → 细节证据 → 编辑目标 →（v2 模板图）**风格底板**。底板是参考图的中性化版本（商品/文字/Logo 区已抹平），标注 "style plate only"：只学背景、光线、调色、机位、构图、留白。它不进 `references`、不参与清晰度审核，但哈希进入生成指纹；主图和 `prompt_edit` 返修不附。
- v2 项目中仍等于 init 骨架原文的 scene/composition/lighting 会被移除，让模板参数生效；显式 job 字段优先。
- 官方 taxonomy：产品摄影 `product-mockup`，营销海报 `ads-marketing`，局部修改用编辑类别。不发明配件、配色、口号或纹理；“无营销文字”不等于去掉商品真实标签。
- **质量返修**：先 `plan`，编译器从绑定的 qa_report 派生 `job.prompt_edit={target_path,failures}`（失败 raw 为编辑目标，进入指纹）；旁文件只供诊断。换新构图时清除旧 `prompt_edit`。普通 reference_edit 的目标由 `pixel_source_reference_id` 决定。

## 排版规则

- **V3 六类配方**：`photo_overlay` 全幅叠字、`header_footer` 页眉/页脚、`photo_sidebar` 摄影侧栏、`scene_grid` 四格场景、`detail_callouts` 细节卡/标注、`steps` 步骤分镜。方图、竖图、A+ 横幅各自安排分区，整套不必只用一种风格。
- **文字组**：`text_groups` ≤6 组（`id/box/headline/body/label/align/mobile_sizes/text_color/surface`），组内共享对齐线；FAQ 每组一问（headline）一答（body）；不与顶层 headline/body 混用。`panels` ≤4（需 `image`+`evidence_refs`），辅助项 ≤4。安全边距为短边 5%。
- **底框**：`surface` 为 transparent/solid/gradient，按用途选；卡片随内容收缩，页眉/侧栏是构图区。对比度不够只在 `allowed_adjustments` 范围内调明度、位置或局部柔和背景，不静默换白字或加整块实色框。
- **角色**：v2 项目由套系令牌预填空的 `style_contract` 角色，显式设置优先；`typography_decision` 记录指定值与采用值。
- **style_v1（可选）**：`layout.renderer: "style_v1"` 加每组 `style`，提供展示字体（Montserrat/Poppins/Oswald/Bebas Neue/Nunito/Libre Baskerville/Pacifico，非拉丁回退 Noto）、分部件颜色、大写、字距、行高、胶囊标签、分隔线、圆角/描边/阴影卡片；用户模板观察到时自动预填。字段见 [fields.md](fields.md)。
- **容量**：plan 已用真实字体测量；放不下时看 plan 返回的 `layout_alternatives`（能放下的配方/默认框）换配方或扩框，每图最多 3 次（SKILL §4）。
- 长词、CJK 换行、RTL 看实际渲染；数字与单位不拆开。

## 审核要点

`review-prepare` 生成总图 `review/sheets/<job>.jpg`（成品、360 预览、细节对照、模板参考缩略图）和清单 `review/packets/<job>.todo.json`；默认只看总图。首次调用就带 annotations（`raw_product_bbox_norm`、`detail_output_bbox_norms`），缺时报错列出框名。

- `semantic_qa_results`：geometry、material、components、scene_scale、clarity、visual_integrity——对照产品证据，不对照参考图。
- `policy_qa_results`：main_product_only、claims、competitor_copy、text_readability、mobile_readability，需要时加 visual_design（层级、间距/底框用途、图文关系、与参考的一致性，四项都写进 notes）。
- `detail_qa_results`：每个 required 的 P0/P1 细节一条，看对照图。
- `ai_disclosure`：见下文 AI 图片规则。
- **design_fidelity**（清单 guidance 会提示）：对照参考缩略图，在 visual_design notes 里逐项写版式、配色、字体、光线的一致程度（close/partial/off）；商品本身只看产品证据。
- **模型文字**：逐字转录每块文字及区域，盘点意外小字/徽章，计划文案不能冒充观察。`native-text-measure --manifest M --job J --blocks <转录框JSON>` 在最终编码 JPG 上测对比度（写 `review/native_text/<job>.json`），同次 review-submit 提交，无需 `--force` 二审；不达标改 local_overlay，不叠字。
- 自动几何检查通过不等于真实或好看；拼版逐 panel 审。规则代码更新时 QA 用已存真实结论重签；文字、布局、遮挡变化必须重看。旧清单被拒（`STALE_REVIEW_PACKET`）时用最新 todo。

## 失败状态 → 动作

`plan`/`status` 的 `next_actions` 已给出具体做法；下表速查。

| 原因/状态 | 动作 |
|---|---|
| `QUALITY_SOURCE_*` / `QUALITY_*` / `SOURCE_*` | `source-review-prepare` → 看总图 → `source-review-submit` → `plan` |
| `CENSUS_*` | 在来源审阅里看完所有 P0/P1 来源，再设 `critical_detail_census_completed` |
| `DESIGN_REFERENCE_REQUIRED` | `lc_template_select.py recommend --manifest M --apply`，或为该图写原创 design_brief |
| `DESIGN_COPY:TYPOGRAPHY_PREFLIGHT` | 按 `layout_alternatives` 换配方或扩大文字框 |
| `DESIGN_COPY:LAYOUT_FIT_BUDGET_EXHAUSTED` | 3 次都放不下：问用户要更短的批准文案，或换图位/模块 |
| `DESIGN_COPY:*`（含 `DESIGN_COLOR_REQUIRED`） | 修正所列的文案或设计契约（如填颜色角色/text_color），再 `plan` |
| `DETAIL_UNVERIFIABLE` / `DETAIL_VIEW_UNVERIFIABLE` | 补可辨认的细节来源，或在该视角把细节设为 hidden |
| `LOCAL_BACKGROUND:*` | 修正背景规范化输入，再 `plan` |
| `QUALITY_REPAIR_LIMIT_REACHED`（终态） | 有新证据或用户同意后 `transition --job J --status pending --reason "..."` |
| 瞬时失败预算用尽（failed） | 用户确认后 `transition --job J --status pending --reset-transient --reason "..."` |
| `generating` 超 30 分钟 | 下次 plan 自动记超时并释放槽位 |
| `transition` 返回 `dispatch_refused` / 退出码 2 | 不派发生图；按 errors 处理后再 plan |
| `layout_repair_needed` | 只本地修复该图的布局（框、配方、颜色），不重生底图 |
| `export_repair_needed`（`FINAL_GLYPH_CONTRAST`） | allowed_adjustments 内调颜色/位置/局部背景，本地重排（92 失败自动试 95） |
| `generation_repair_needed` | `plan` 派生 prompt_edit 后按适配器重新派发（受每图 1 次质量修复限制） |
| `diagnosis_required` | 执行其中给出的针对性检查命令；锁 10 分钟后过期 |

## AI 图片规则

最近核对：2026-09-05。站点、类目或渠道规则变化时，重新读官方来源并记录版本。

- **平台要求**：含逼真 AI 人物（含只露手/半身）的 Listing/A+ 须在 XMP `dc:subject` 写 `contains-synthetic-performer`（[Amazon 公告](https://sellercentral.amazon.com/seller-forums/discussions/t/aa0aee06-aff4-497a-a4b6-9b2ebe06f715)）；无人、非逼真人物、仅真人（即使经 AI 修改）不适用，生成背景/商品不算。广告素材另按 [Amazon Ads 指南](https://advertising.amazon.co.uk/help/GZZX6RJVMWBVBB6W) 核对。
- **字段**：`ai_disclosure.human_source` 取 `synthetic`（任何逼真合成人物，混合也选它）/`real`/`none`/`non_photorealistic`/`unknown`（不能交付）并写 notes；看过当前画面后用 `reviewed_image_sha256` 绑定 `job.image_sha256`，有插图/panel 时再用 `reviewed_visual_fingerprint` 绑定 `job.disclosure_visual_fingerprint`。依据素材、过程和成品，不看提示词；插图变化须重审，只改本地文字不用。
- **导出**：压缩完成后写 XMP，回读核对后再算哈希；JSON 不能替代文件内元数据；补写不触发生成。不沿用编辑前的 C2PA 签名；主图不加水印；本地嵌入≠平台通过。
