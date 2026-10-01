# 旧项目兼容（V1–V6）

只在 `status` 判定为旧项目，或 manifest 缺少新字段时阅读。总原则是恢复而不迁移：旧项目保持原行为，不例行运行 migrate。本页不改变 SKILL.md 的鉴权和硬规则。

## 永不自动升级的内容

- 缺少 `prompt_profile`（或显式 `legacy`）的图：保持原提示字节和生成指纹，不会因升级重新生成。`PIPELINE_VERSION` 保持不变。某张图显式改为 `images_2_5_v1` 只影响这一张。
- 缺少 `generation_dependency_version`：沿用旧的哈希算法。
- 缺少 `scheduler_policy`：沿用旧并发策略（上限 2）。
- 缺少 `review_rule_profile`（或显式 `legacy`）：审核规则摘要仍按完整源码计算，不改写历史审核哈希。
- 缺少 `delivery_profile`（或 `legacy`）：旧交付方式与编码保持不变。
- 缺少 `design_template_policy`：走外部参考路线（见下）；v1 项目不会自动变成 v2。
- `style_contract` version 1/2、`copy_budget`：按原规则运行。
- 升级后可能需要本地复核，不花模型调用：排版代码哈希变化会让已排版图重新本地渲染并重审排版结论；审核规则摘要变化时，QA 会用已存结论重新签发。不会重新生成未变的底图。

## 版式 V1 / V2

| 版本 | 特征 |
|---|---|
| V1 | 顶层 `headline/body/items`，`font_sizes`（以 2000 px 短边为基准：headline 120–160、body 72–88、label 64–80），固定 Noto Sans 400/700，`template` ∈ scene/split/benefits/detail/dimensions/components，`theme` ∈ neutral/warm/technical/playful，`text_surface` transparent/solid/gradient，`text_color` |
| V2 | `mobile_sizes`（360 px 预览 token）、单个 `text_group{box, align, gap_em, max_height}`、`headline_family` sans/serif、`faq[{question,answer}]`、items 最多 3 项；禁止 `font_sizes` |

- `template/theme` 目前也会在 V3 上按 V1 列表校验（theme 文件还计入布局指纹）；新项目 init 不写这两个字段。
- `job.text_overlays` 是更早期的字段，校验会要求把文案迁到结构化 layout。
- 旧项目套用新的 `style_contract` v3 时，带营销文字的图必须显式迁移到 `layout.version=3`，只重新验证受影响部分。

## 模板策略 v1（内置文本模板）

- `design_template_policy={version:1,mode:"auto"}`：本地排序器按 kind/画幅过滤，再按意图/recipe 打分；品类门槛只认少量标签，常常 needs_input。
- 控制字段：`design_template_set_id/_revision`、`job.design_template_id/_revision`、`design_style_preferences`、`design_template_library_path` / `design_template_user_library_path`、`design_overrides`、`design_template_original_reason`（无合适模板时写原创 brief，记为 matched=false）。
- 快照固定：库更新不会改变已采用的版本。要重选同一套系，只删除对应的派生 `design_template_selection` / `design_resolution`，然后重新 prepare 并复审。
- 模板的 `prompt_template` 只用 `{product}` `{scene}` `{selling_job}` 占位；`layout.canvas_variants` 按 square/portrait/wide 给出文字框和商品框。
- 库文件：`assets/layouts/design_templates.json`（内置）。旧的 skill 内 `design_templates.user.json` 首次使用时会迁入外部库（原文件不动）。内置库可停用：`lc_template_library.py builtin --disable`。

## 外部参考路线（未启用模板模式的旧项目）

- 命令：`lc_style_reference.py prepare --product-context <ctx.json> --selection-output <sel.json>`。项目通过 `style_reference_selection_path` 绑定，选一个主参考、最多两个辅助参考。
- 单元索引 `design_reference_units.json`（schema 1，`asset_policy: external_regions_only`）每项含绝对 `external_path`、sha256、`unit_region_norm`、recipe、generation、layout、`reviewed:true`、`product_evidence:false`。项目用 `design_reference_units_path` + `design_reference_ids`，单图用 `design_reference_id`。
- **不可移植**：现有索引写死了作者 Mac 的 `/Users/...` 路径，换机器后原图缺失，显式参考会变成 needs_input 并暂停受影响的新生成。可选的通用参考不可用时不阻断，但不能签“匹配参考”。建议改为用这些原图做一次 `intake`，生成 v2 用户模板。
- 对照板外层的左右关系、UI、编号都不是目标设计。

## 迁移命令（仅在明确要求升级时使用）

- `migrate --manifest M [--marketplace --language]`：升级旧 schema，保留备份、`legacy_text_overlays` 和旧审核记录。旧 A+ 不能只凭 970×600 猜 `a_plus_module`。迁移不切换提示、审核规则或设计 profile。
- `migrate-dependencies --manifest M --source-manifest OLD --jobs ... [--source-kind historical_snapshot|reconstructed_verified_dependency_view] [--allow-project-fork]`：把已有 raw 升级到依赖 v2，必须严格重现已入库的 attempt 和 raw SHA。重建视图时需显式声明 source-kind；project fork 只放开 project_id 差异。
- 不得手改旧 generated 哈希或状态来冒充完成。

## copy_budget（仅旧项目显式字段）

`{version:1, max_headline_words, max_ordinary_words, max_supporting_points, baseline_words?, target_ratio (0.7), tolerance ([.65,.75]), required_text[{text, job_id?}]}`。有精简目标时必须给出真实的 `baseline_words`。新项目不创建该字段，也不压缩文案。

## 旧交付

- 显式 deliver 旧项目时，分散的已审成品会汇集到 `delivery/images-vNNN/`，不覆盖历史版本，也不改变原 PNG/JPEG 编码；无变化时重复交付会复用。
- 旧 profile 中的 `standalone_html:false` 会被忽略，`true` 会被拒绝。
- 要改用 `compact_jpg`，必须显式设置并重新验证，不能重写旧审核哈希。

## 旧 product_truth 字段

`product_truth.source_quality/master_asset_mode/master_confirmed` 仅作兼容保留，不再控制生成方式；V3 使用逐图的来源审阅与 `render_decision`。
