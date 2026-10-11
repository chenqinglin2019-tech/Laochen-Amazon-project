# V8 路由提示

`workflow_policy="one_pass_v1"` 的字段见 [one-pass.md](one-pass.md)。本页下面的布局、排字、审核和旧项目状态字段只适用于历史管线；新项目不要填写 qa_passed 或旧审核结论。

# 字段速查（V7.1）

只在报错点名了不认识的字段时查阅。以脚本校验为准：`validate --manifest M --json` 会列出全部问题。旧项目字段见 [legacy.md](legacy.md)。

## 项目级（project_manifest.json）

| 字段 | 取值 / 说明 |
|---|---|
| `design_template_policy` | v2（新项目）：`{version:2, mode:"auto", prefer_family_ids?:[id]}`；v1：`{version:1, mode:"auto"}`（只允许这两个键） |
| `product_profile` | `{category, attributes:{material,color_tone,size_class,style_mood,audience,use_environment,price_tier}}`，词表见 `lc_template_select.py taxonomy`，用于自动选套系 |
| `design_template_set_id` / `_revision` | 固定项目套系。recommend `--apply` 或首次 plan 采用后会写入；只有用户指定时才手改 |
| `design_template_library_dir` | 可选，项目相对的模板库目录，默认 `~/.lc-amazon-image-studio/library`，也可用环境变量 `LC_TEMPLATE_LIBRARY_DIR` |
| `design_template_selection` | 派生值（套系快照、选择理由、`token_prefill` 台账），勿手改 |
| `style_contract` | v3：`selection:"design_first"`、`color_roles`、`font_roles`、`body_weight:400`、`label_weight:400`、`min_contrast_ratio:4.5`、`mobile_sizes`、`allowed_adjustments⊆[lightness,position,local_surface]` |
| `style_contract.color_roles` | 角色 headline/body/label/accent/graphic → `#RRGGBB`。v2 模板会预填空角色，显式值优先 |
| `style_contract.font_roles` | 同上角色 → `{family:sans\|serif, weight}`；Sans 400/600/700，Serif 400/600。展示字体（Montserrat 等）写在 layout 的 style 里，不写在这里 |
| `scheduler_policy` | `{version:1, mode:"adaptive", max_concurrency:2..4}` |
| `review_rule_profile` | `scoped_v1`（新）或 `legacy`；job 级同名字段可覆盖 |
| `review_dependency_version` | 2 = 只绑定本图用到的事实、层和来源 |
| `delivery_profile` | `{name:"compact_jpg", jpeg_quality:92\|95}` 或 `legacy`；`standalone_html:true` 会被拒绝 |
| `critical_detail_census_completed` | 通过 source-review-submit 设置 |

## 任务级（jobs[]）

| 字段 | 取值 / 说明 |
|---|---|
| `id` | 小写字母、数字、`_`、`-` |
| `kind` | `main` / `listing` / `a_plus`（a_plus 必须有 `a_plus_module`） |
| `canvas` | main/listing：1:1 或 1:1.3（宽:高），两边 ≥1600 |
| `render_mode` | `pixel_composite` / `reference_edit` / `reference_generate` |
| `text_mode` | `none` / `local_overlay` / `model_native` |
| `copy` | 仅 model_native 使用：`{headline(必填,≤180), body?(≤200)}` |
| `model_native_reason` | `{kind, notes}`；kind 为 `native_poster`（需要 images_2_5_v1，文案不能含数字）、`artistic_lettering` 或 `integrated_material` |
| `embedding_decision` | `{kind:none\|surface_embedded_3d, reason, surface, material_lighting}`；3D 只用于 1–5 词、无数字、无 body、无 claim_ids 的标题 |
| `prompt_profile` | `images_2_5_v1`（新）/ `legacy`（缺省即 legacy） |
| `prompt_edit` | `{target_path, failures:[...]}`，由 plan 从 QA 报告派生，需要 images_2_5_v1；改用新构图时清除 |
| `generation_dependency_version` | 1 / 2（新图用 2） |
| `status` | pending, generating, generated, review_pending, qa_passed, blocked, failed, repair_needed, layout_repair_needed, generation_repair_needed, export_repair_needed。只能通过命令修改 |
| `target_product_bbox_norm` | `[x,y,w,h]`（0..1），计划商品容器；`raw_/output_product_bbox_norm` 是实测值 |
| `generation_geometry_lock` | 只允许 `image_region_norm`、`product_region_norm`、`text_regions_norm` |
| `claim_ids` / `source_reference_ids` | 必须指向已登记的 facts / references |
| `hold` / `publication_status` | 未确认规格 → hold，不派发、不交付 |
| `template_slot_role` | 指定图位角色（taxonomy 的 slot_roles），不填则由 kind/selling_job 推断 |
| `design_template_id` / `_revision` | 单图指定模板，不能与 `design_reference_id` 同时使用 |
| `design_template_original_reason` | 不套模板、使用原创 brief 时填写 |
| `design_overrides` | `{generation:{...}, layout:{...}}`，对模板编译结果做有意的逐图调整 |
| `design_brief` | 编译结果（v2 模板为 version 2）；手写原创 brief 时需要非空 `generation` |
| `export.quality` | 92 / 95 |
| `ai_disclosure.human_source` | synthetic / real / none / non_photorealistic / unknown |

**`design_resolution`（schema_version 2，只读）**

| 字段 | 说明 |
|---|---|
| `status` | 值为 `selected` 或 `needs_input` |
| `match` | 取值：`observed`（本套系在该画幅实拍过）、`adapted`（同套系换画幅）、`cross_family`（借用其他套系的模板，换上本套系令牌）、`original`（只用令牌生成） |
| `binding` | 套系、模板、令牌来源的 id、revision、快照和哈希，编译器版本 1 |
| `assets.plate` / `assets.reference_thumbnail` | 格式为 `{path, sha256}`，指向项目内 `design/plates`、`design/references` 下的副本。清空模板库不影响已采用的项目 |
| `brief_hash`、`request`、`selection_reasons`、`layout_prefill`、`scaffold_removed` | 追溯用字段。issue `design_template_brief_changed_run_prepare` 表示需要重新 plan |

风格底板只作为最后一张附件附给非主图，且只在 match 为 observed/adapted、没有 prompt_edit 时附加。它不进 `references`，不参与商品清晰度审核，但计入生成指纹。

## Layout V3

`layout.version=3`。`recipe`：photo_overlay / header_footer / photo_sidebar / scene_grid / detail_callouts / steps。

| 键 | 说明 |
|---|---|
| `product_region_norm` | 生成时的商品容器（不是实测商品框）；优先级：显式 layout > brief.layout > recipe |
| `canvas_background` | `#RRGGBB`，必须配合非空 panels |
| `text_groups[]` | 最多 6 组。键：`id`、`headline`/`body`/`label`（≤180/500/180 字符，至少有一项）、`box`（第一组之后必填）、`align` left/center/right、`headline_family` sans/serif、`headline_weight`、`headline_max_lines` 1–3（默认 2）、`mobile_sizes` {headline≥18, body/label≥12}（360 px 预览下的尺寸）、`text_color`、`color_role`/`font_role`、`gap_em` 0–2、`surface`、`headline_treatment`、`decorative_effect` |
| `surface` | `kind` transparent/solid/gradient、`color`、`opacity` 0–1、`padding_em` 0–2、`direction` horizontal/vertical |
| `headline_treatment` | 取值：plain；outline（color, width_em .01–.12）；shadow（color, offset_em [±.3,±.3], blur_em 0–.3, opacity） |
| `panels[]` | 最多 4 张：`id`、`image`（必须是已登记且路径相同的 reference）、`box`、`fit` cover/contain、`source_crop`、`product_bbox_norm`、`evidence_refs`（非空） |
| `items[]` | 最多 4 项：text/icon/image/evidence_refs/target（detail 类必须有 image + target；dimensions 类必须写数值和单位） |
| `protected_regions[]` | 归一化框或 `{kind, bbox}` |
| 禁止 | `font_sizes`（V1）、顶层 `faq`、顶层 headline/body 与 text_groups 同时存在 |

**style_v1 扩展**（`layout.renderer:"style_v1"`，由 v2 模板自动预填，也可手写）。每个文字组的 `style` 可包含以下键（parts = headline/body/label）：

| 键 | 值 |
|---|---|
| `faces {part: face}` | montserrat, poppins, oswald, bebas_neue, nunito, libre_baskerville, pacifico（只有拉丁字形，其他文字回退 Noto） |
| `weights {part: int}` | 该字体已内置的字重（见 `assets/fonts/faces.json`） |
| `colors {part: #RRGGBB}` | 逐部分设定颜色，对比度逐部分实测 |
| `case {part: none\|uppercase}`、`letter_spacing_em {part: -0.05..0.3}`、`line_height {part: 0.9..2}` | |
| `pill {color, text_color?}` | 标签药丸底，需要 label 文案 |
| `divider {after: headline\|body, color, width_px 1..6, length_em 0..20}` | length_em 为 0 表示整宽 |
| `surface {radius_em 0..3, border_color?, border_width_px 0..4, shadow}` | 只用于 solid/gradient 类型的 surface |

不带 renderer 的布局走原渲染器，字节不变。溢出、4.5:1 对比度、360 px 尺寸规则相同。

## 来源审阅包 `review/source/packet.json`（lc-source-review/1）

- `references[]`：填写 `clarity`（clear/mild_softness/blurred/unknown）、`evidence`（sufficient/insufficient/unknown）、`defects[]`、`notes`（必填）。sha256 与 region_fingerprint 由工具绑定，不要改。
- `jobs[]`：填写 `scene_fit`（matched/local_change/new_view/unknown）、`evidence`、`degradation`（none/mild/localized/global/unknown）、`reason`（必填）、`matched_reference_ids`。`context_changed_since_last_review` 列出的是变化了的字段。
- `layers[].reviewed=true`：逐个核对抠图和遮罩后才能设。`critical_detail_census_completed=true`：所有 P0/P1 来源都看过后才能设。

## 审核包与 todo（review/packets/`<job>`.todo.json）

每项都是 `{verdict: pass|fail|not_applicable, notes}`。

| 组 | 键 |
|---|---|
| `semantic_qa_results` | geometry, material, components, scene_scale, clarity, visual_integrity |
| `policy_qa_results` | main_product_only, claims, competitor_copy, text_readability, mobile_readability（需要时加 visual_design）。not_applicable 只能用于非主图的 main_product_only，或无文字图的可读性两项 |
| `detail_qa_results` | 每个 P0/P1 细节的 id |
| `ai_disclosure` | human_source + notes |
| `model_text_review` | verdict、notes、`blocks[{id,text,bbox_norm}]`（实际转录）、`unexpected_text[]`；3D 嵌字另有 `embedding{...}` |
| `panel_reviews[id]` | provenance, product_identity, crop |
| `title_effect_review` | binding、transcription、unexpected_text、bbox_norm、observed_surface，以及 readable_original/readable_360/carrier_surface_visible/material_perspective_pass/lighting_contact_pass/product_unchanged/other_text_unchanged/decorative_only |

`guidance.design_fidelity` 出现时，在 visual_design 的 notes 中逐项写版式/配色/字体/光线与参考缩略图的接近程度（close/partial/off）。旧 review_id 会被拒绝（STALE_REVIEW_PACKET）。

`native-text-measure --blocks blocks.json`（文件内容 `[{"id":"…","bbox_norm":[x,y,w,h]}]`；也接受内联 JSON，但 PowerShell 下请用文件）：按最终 JPG 编码测量字形核心对比度（p05 ≥4.5），结果写入 `review/native_text/<job>.json`。

## 可选效果（默认关闭）

**局部浅浮雕** `text_groups[].decorative_effect`

- 前提：V3 + local_overlay、非主图、每图最多一组，该组的 headline_treatment 为 plain。
- 配置：`{version:1, kind:"surface_emboss", purpose:"decorative", reason, surface, material_lighting, allowed_bbox_norm, semantic_review:{decorative_only:true, contains_brand:false, contains_facts:false}, source_reference_ids?}`。
- 标题限制：1–5 词，不含数字、品牌或事实，不绑定 evidence_refs 或 claim_ids。
- 流程：`title-effect-prepare` → 在真实工具调用前后打 `title-effect-event --event tool_started|tool_returned|failed` → `title-effect-ingest --artifact --mask`；之后走正常审核。
- 失效时恢复平面版本并记录 fallback_reason。整套图建议 0–2 张使用。

**主图背景规范化** `background_normalization`（仅主图）

- 配置：`{version:1, reviewed:true, protection_covers_product_and_shadow:true, source_pixel_sha256, background_mask:{path,sha256}, protection_mask:{path,sha256}, near_white_min:250..254}`。
- 两张遮罩必须是与画布同尺寸的二值图，且互不重叠；`source_pixel_sha256` 是等比合成后画布的像素哈希。
- 只把与边界连通、且位于背景许可区内的近白像素置为 255。raw 与生成指纹不变，最终 JPG 仍需整图审核。


## V7.1 新字段

**项目级**（新项目由 init 写入，旧项目没有这些字段时保持原行为）

| 字段 | 含义 |
|---|---|
| `concurrency: 4` | 起步并发（原为 2），仍受 `scheduler_policy.max_concurrency`、限流退避约束 |
| `anchor_policy {version:1, mode:"parallel_first_wave"}` | 仅旧项目兼容：首批兄弟图与锚点同时开始，兄弟图的 attempt 带 `speculative` 标记 |
| `main_image_policy {version:1, mode:"auto_composite"}` | 主图优先用合格实拍图本地合成 |
| `manifest_defaults` | 自动补默认值的台账：`visibility_optional`、`location_view`、`claims_bound` |

**任务级**

| 字段 | 含义 |
|---|---|
| `prompt_format: "compact_v2"` | 精简提示格式；`prompt_profile` 仍为 `images_2_5_v1` |
| `default_recipe` / `layout_recipe_source` | 图位的默认版式意图；只有布局和设计简报都没选配方时才使用 |
| `layout_heal` | 删除旧 `layout.template` 陷阱的记录 |
| `layout_autofit {from,to,at}` | 自动换版式的记录 |
| `layout_recipe_locked: true` | 禁止自动换版式 |
| `main_composite {status: proposed/confirmed/rejected/ineligible, reference_id, ref_sha256, upscale, overlay}` | 主图本地合成的提案及状态 |
| `free_releases` | 已用的免费退回次数（上限 2） |
| `speculative_voided` | 首批作废记录 |
| `anchor_product_failure` | 锚点快审失败记录（之后不再投机派发） |

**attempt 级**
- `speculative {anchor_job_id, anchor_generation}`、`speculative_outcome: voided | void_on_ingest`
- `released_unstarted`、`wave_id`
- `undo`：免费退回用的快照，入库或失败后删除

**审核 answers**（`lc-review-answers/1`）

```json
{"schema":"lc-review-answers/1","answers":{"<job>":{"rid":"<8位>","observation":"<≥20字，每图不同>",
 "exceptions":{"semantic_qa_results.scene_scale":{"verdict":"fail","notes":"…"}},"people":"none","explicit":{}}}}
```

**来源审阅包**：条目带 `proposed: true` 表示实测预评；`census_proposed` 同理。接受任何预评时，`source-review-submit` 必须带 `--observation`。cutout 层用 `--confirm-layers <job>:<index>` 确认，用 `--reject-layers` 拒绝。

## V7.2 构图先行（新项目默认）

- `composition_policy: {version:1, mode:"layout_first"}` 与 `anchor_policy: {version:1, mode:"full_review_first"}` 必须同时使用。无策略的旧项目保持原流程。
- `job.composition_intent`：negative_space、subject_scale、layout_reason 三项非空设计说明。
- `job.composition_contract`：派发时从既有布局派生的快照和摘要，不另建一套坐标，不手改。
- `job.composition_review`：审核记录文件、哈希、提交摘要；绑定底图、实际资产、构图和审核规则，改变后过期。
- `job.composition_observed_bbox_norm`：根据实际画面标注的完整产品外接框，不是计划框。
- `job.composition_failure` / `composition_repair_history`：失败原因及受控本地重排历史，使用既有一次质量预算。
- `explicit.visual_design`：checks 为 text_relationship、subject_scale、composition_integrity、series_consistency，每项必须显式 verdict/notes，总体失败时加 failure_stage base 或 typography。
- `dispatch.review_stage`、回调 `stage`：composition 表示先审底图；入库返回 composition_review_required。

详细格式及命令见 [composition.md](composition.md)。交付字段仍为 `deliver.images[].path`，不要求项目级总览。
