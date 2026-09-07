# V6 运行流程

本地入口为 `scripts/lc_image_pipeline.py`；负责预检、提示编译、状态与缓存、内置排版、元数据及验收，不直接调用图像模型。实际生产先按 [SKILL.md](../SKILL.md) 鉴权，再使用内置 `image_gen`；用户明确要求其他后端时才改变。

## 环境与项目初始化

选择带 Pillow 的 Python 3，以下 `python3` 代表该解释器；系统 Python 缺包时使用 Codex bundled Python 路径。排版运行时锁定 Node ≥20、Playwright 1.62.1、Chromium 149.0.7827.55、Pillow 12.3.0；依赖缺失或版本不符时按 `doctor` 诊断修复，不静默退回其他字体或调用其他 skill。可通过 `LC_LAYOUT_NODE`、`LC_LAYOUT_NODE_MODULES`、`LC_LAYOUT_CHROMIUM` 定位当前机器的运行时，字体从 skill 内部加载。

```bash
python3 <skill-root>/scripts/lc_image_pipeline.py doctor
python3 <skill-root>/scripts/lc_image_pipeline.py init \
  --project-dir <versioned-project-dir> --project-id <stable-id> \
  --listing-aspect 1:1 --short-edge 2000 \
  --marketplace US --language en
```

`--marketplace` 与 `--language` 必填。竖图使用 `--listing-aspect 1:1.3`；短边至少 1600 且竖图短边为 10 的倍数，保证精确比例，任何边不超过 10000。A+ 仅在用户要求时通过 `--include-a-plus --a-plus-canvas <WIDTH> <HEIGHT> --a-plus-module <module-name>` 加入，画布参数为两个整数；`--a-plus-count` 默认6，按用户明确数量调整；不使用 Listing 的比例和短边门槛推导 A+。

保留原始素材到项目 `source/`，填写 `project_manifest.json`。恢复旧项目时先运行 `migrate --manifest <manifest>`；缺少站点或语言时追加 `--marketplace`、`--language`。迁移备份旧 Manifest，保留来源、历史成品及原尺寸，将原叠字备份到 `legacy_text_overlays` 并生成待审初始布局；不要把迁移视为已经完成新版排版。

新版区域审阅、布局及合规结论须补齐；保留的旧 A+ 还需填写对应 `a_plus_module`，不能只凭 `970×600` 猜模块。旧 `qa_passed` 不能直接成为新版通过。

## 英文模板选择与保存

新 `init` 默认启用纯文本模板模式，按[英文模板库](design-template-library.md)先做套系与图位选择。用户新增参考实际看图、英文拆解、去重审核后用模板 importer 自动写用户库，再采用其 canonical ID。模板命令只读写 JSON，不调用模型、不复制图片。新项目的 recipe 初始不固定，由所选模板提供；没有设计 brief 时仅保留临时排版默认，不能把空骨架当成完成规划。

采用版本以文本快照绑定项目；编译 `design_brief.generation/layout`，对应阶段依赖保持分离。恢复已有图时不读源截图或重选最新库，新增用户模板不影响原项目。无合适模板时撰写项目原创说明并记录 `matched:false`，不强行匹配；主图继续使用白底专用规则。模板正文英文不改变目标站点文案语言，真实产品证据、字体／容量测量、最终目视审核仍必需。

下面保留 V5 外部参考接口，仅适用于旧项目或本轮明确外部引用；普通新项目不运行这一路选择：

首次 `plan` 前集中规划整套文案与设计。设计参考优先级为本轮用户参考、项目已确认设计、通用样本库；V5 将选中的单张成品参考编译为逐图 `design_brief`，实际进入对应的生成或本地排版依赖。`design_brief.generation` 约束摄影、构图及图形关系，`design_brief.layout` 约束排版；它们不是产品事实，不可重写 `references` 或四项产品锁。

新项目的 `style_contract.version=3`、`selection=design_first`，color_roles/font_roles默认空；Agent先按实际产品或明确参考填写角色，显式组／layout优先，不用最高对比候选覆盖已指定颜色。完整保留批准文案，不创建30%精简任务；容量不足先调整版式与既有图位，不能删词、缩字或擅自新增图位。旧V1/V2契约按原规则运行，应用新设计时仅重新验证受影响部分。

用户截图通过 `design_reference_units_path`、`design_reference_ids` 和逐图 `design_reference_id` 引用已审阅单元；保存外部源文件哈希、成品区域、选择理由和排除内容。只学习成品内部的阅读顺序、分区比例、裁切、字体层级与背景用途，排除 UI、编号、下载按钮、原图区及 before/after 对比板的外层结构。没有用户参考时才使用以下通用选择入口：

```bash
python3 <skill-root>/scripts/lc_style_reference.py prepare \
  --product-context <project-dir>/style_reference_context.json \
  --selection-output <project-dir>/style_reference_selection.json
```

`style_reference_context.json` 至少放 `product`，建议放 `category`、`intents`、`composition`、`lighting`；字段可为单个字符串或列表。`category`／`intents` 为空的旧资料会用有限关键词从 `product` 和 `selling_job` 归纳；未匹配留下 `inference: unknown` 与 `selection_status: needs_input`，不把某个样本品类强套给所有产品。保存 1 个 `primary` 与最多 2 个 `auxiliaries` 及其 path/hash、评分理由和 `style_profile_hint`；禁止迁移样本产品、文字、CTA、品牌或像素。Manifest 可保留 `style_reference_selection_path: "style_reference_selection.json"`。

缺少通用选择文件且产品信息充分时，选择 hook 可调用 Python API：

```python
prepare_selection({"product": product, "category": category, "intents": selling_job}, selection_path)
```

内容指纹未变时复用选择与编译结果，不逐图重复分析全部样本。显式用户参考缺失或哈希改变时，受影响任务记录 `design_resolution.status: needs_input`，不能继续依据过期参考派发新生成，也不能签发样本一致性的视觉通过；其他独立任务继续，既有原图与历史成品不删除。未选择 V5 的旧项目保持原路由与指纹，不因读取升级而全套失效。字段及覆盖规则见 [V5 设计与性能](v5-design-and-performance.md)。

## 输入与审阅记录

每张参考填稳定 `id`、`path`、`role`、`view`、`product_bbox_norm` 和 `quality_review`。商品框是整个参考图中的 `[x,y,width,height]`，均归一化到 0–1；不可使用整图尺寸替代产品区域质量。

参考角色明确区分整件产品、局部细节、材质、组件、包装和编辑目标。逐张原尺寸检查后，填 `quality_review.clarity/evidence/defects/notes/reviewed_sha256` 并绑定 `reviewed_region_fingerprint`；字段枚举及模式选择见 [区域质量与内置排版](layout-and-quality.md)。

每个任务填 `source_reference_ids`、目标 `view`、产品目标框、四项锁需要的事实、`source_assessment`、`render_mode` 与理由。目标视角可以由多张参考共同支持；不能只查看第一张参考，也不能只比较视角名称。`source_assessment.reviewed_context_fingerprint` 绑定本次任务上下文，区域或上下文变更后须重新审阅；先填写参考审阅并重新 `prepare`，再使用 `job.assessment_context_fingerprint` 作为本轮期望值；`reviewed_reference_hashes` 覆盖 `job.render_decision.required_reference_hashes`，包括必要局部来源，不自行猜值。

V2 的全局 `product_truth.source_quality/master_asset_mode/master_confirmed` 仅作历史兼容，不再必填或控制生成方式；V3 使用各任务的区域审阅与 `render_decision`。

逐 P0/P1 注册 `critical_details`：视觉证据与文字主张分开、参考坐标相对商品框、每张图明确 `required/optional/hidden`。原尺寸 census 完成后才设置 `critical_detail_census_completed=true`；所有候选裁图太小或模糊时保持 `unverifiable`。

生成前逐图明确 `text_mode`，它独立于商品 `render_mode`：主图及无营销文字图为 `none`；摄影海报、A+、卖点、尺寸、FAQ、步骤及拼版默认 `local_overlay`。少量1–5词、无品牌/数字/事实的装饰标题可用文字组 `decorative_effect.kind=surface_emboss`，保留本地品牌及正文，整图不转native。旧 `model_native`、`model_native_reason` 及 `embedding_decision` 仍按既有整图规则运行。初始化只提供空白V3本地骨架，不自动虚构或改写文案；完成规划后再按用途选路。

`model_native` 的唯一文案入口是 `job.copy.headline/body`，不得再填本地文字、图标或 panels；模型一次设计完整海报，不能自行扩写。`local_overlay` 文案只放 `layout`，新项目使用 `layout.version: 3`，并提前确定构图、文字组和保护区。使用 `facts` 的 `id/text/evidence` 保存主张来源，`job.claim_ids` 关联本图事实；局部说明或尺寸另用 `evidence_refs` 绑定。数值、材质、性能与兼容性仍须真实依据，文字路线不改变证据门槛。

原像素合成使用 `product_layers` 的 `reference_id/asset_path/mask_path/bbox_norm`，可加 `crop_bbox_norm` 和 `shadow`。使用已检查的透明图或与商品资产尺寸完全一致的遮罩；脚本不会猜遮罩。确需保留整块矩形图时才明确 `opaque_rectangle: true`。像素来源须匹配 `job.render_decision.pixel_source_reference_id`，不默认第一张参考；原像素合成不是“给模型一句不要重绘”。

另外的抠图或附加遮罩需按 [图层来源绑定](layout-and-quality.md#生成方式决策) 填 `source_binding`；`prepare` 自动写入 `layer_asset_hashes`。资产、遮罩或裁框改变后，先重新审阅本层来源，再绑定更新后的任务指纹。每层的 `asset_origin` 与参考 `provenance` 一致，多组件层也须独立满足清晰度和视角要求。

## 准备与调度

```bash
python3 <skill-root>/scripts/lc_image_pipeline.py plan --manifest <manifest> --json
# 仅当实际工具能力较低时登记，例如：--tool-capacity 2
```

`plan` 已调用 prepare 完成结构、区域像素／裁图、审阅证据、提示与分阶段依赖准备；不要例行 prepare→plan 双跑。独立 `prepare --jobs <id> ...` 接口保留，输入改变或恢复状态不明时重新 plan。读取阻断原因；未知清晰度需要先审阅，必要细节缺实拍需要补资料或改构图，不能把状态直接改成通过。

`plan` 用于决定下一批操作。共享商品身份或 census 等全局事实未完成时不能生成；单张证据缺口仅阻断该图，其他独立任务继续。先做风险最高的一个可执行锚点，真实 QA 通过后从并发 2 开始。新项目默认 adaptive 策略：当前档位连续两个不同 attempt 首次成功入库升一档，最高 4；429 降 1，单次超时降一档、连续两次超时降 1。退避后 60 秒不升速，工具明确 Retry-After 期间不新增模型派发；旧 epoch 或旧档位在途成功不用于升档，重复回调不计数，降档不取消在途任务。旧项目无 scheduler_policy 保留既有策略，不自动升级。

只有模型调用扣减容量；产品生图和局部标题编辑共享健康记录与槽位，本地 compose 独立列出，仍检查来源及锚门。`concurrency` 是当前档位，`network_health` 保存健康与实际工具上限；`plan --tool-capacity 1..4` 记录较低工具能力，未传保留已知值。默认每图一个候选，HOLD 不进模型队列；浅浮雕可为零，不增加固定样图或全套重生关卡。

生成与本地处理、审核分别推进，不能让待审图占生成 slot，也不能为凑本地批次等待模型。已绑定且指纹未变的 raw／布局／QA 必须复用；本地改字只重排，模型原生文字改字只修订该图，改元数据不重生。

图像调用由 agent 执行；本地 `plan` 不是模型调度服务。可直接合成的任务走本地图层，不调用图像模型；等待模型时可准备其他来源、排版已完成图或执行 QA。

## 生成、图层与提示绑定

`pixel_composite` 填好图层后运行 `compose --manifest <manifest>` 进行本地合成，无需进入模型生成状态。需要模型的任务在生成前运行：

```bash
python3 <skill-root>/scripts/lc_image_pipeline.py transition \
  --manifest <manifest> --job <id> --status generating
```

预读 plan/ingest/review-submit 返回的提示文件与参考路径，再紧接执行 transition、tool_started 和实际工具调用。派发锁内只核验来源内容、递归证据与准备绑定，不生成预览或排版；缺少或过期评估返回重新 plan 要求。transition JSON 的 `attempt_id`、`prompt_hash` 随工具调用保存；返回不等待其他 slot，立刻 ingest 绝对 raw 文件：

```bash
python3 <skill-root>/scripts/lc_image_pipeline.py attempt-event \
  --manifest <manifest> --job <id> --attempt-id <attempt-id> --event tool_started
# 调用 image_gen；在工具真实返回时捕获 <returned-epoch> 及 <absolute-raw-path>
python3 <skill-root>/scripts/lc_image_pipeline.py ingest \
  --manifest <manifest> --job <id> --artifact <absolute-raw-path> --attempt-id <attempt-id> \
  --tool-returned-at <returned-epoch> --json
```

`ingest` 绑定 raw、立即置为 `generated` 并释放 slot；同一 attempt 绑定同一 artifact 是幂等的，旧 attempt、旧 prompt、同一 attempt 的不同 artifact 或其他冲突会被拒绝。它不覆盖旧 raw：重试／修复使用 `raw/attempts/<job>-<attempt>.<ext>`。读取当前编译提示及 `generation_reference_paths`，只附本图必要的产品、细节和设计引用，标明角色。编辑本地图像前先查看目标。提示以 Geometry、Material、Scene Scale、Critical Detail 四项锁开头；`none/local_overlay` 不生成额外营销文字，`model_native` 只绘制已批准的准确短文案，所有路线都保护商品自身真实标签。

`ingest --tool-returned-at` 在同一次提交校验真实事件顺序、记录返回时间及入库；仍兼容单独 `attempt-event --event tool_returned --timestamp <epoch>`。缺少真实时刻时不得补造；默认命令时刻不代表此前工具返回或锁等待。ingest 和 review-submit 返回最新 dispatch，预读后立即补位，无需再例行完整 plan。`tool` 是调用墙钟（含网络与服务端排队），不是纯推理；真实返回到入库 p95 ≤30 秒仍需正式生产验证。

网络失败使用既有 `transition --status pending --reason <actual-error>`；工具明确给出等待秒数时追加 `--retry-after-seconds <seconds>`，不能仅在说明文字中记录而忽略调度等待。

同视角可复用已验收生成素材，但保留生成身份及实拍依赖。新视角必须重新定位商品框和关键细节：在 `detail_output_bbox_norms` 写整个最终画面的精确归一化框，不能沿用源图二维位置假定真实位置。

## 可选局部标题效果

本流程只在V3 local_overlay的一个文字组声明 `decorative_effect.kind=surface_emboss` 时使用。配置字段见[局部浅浮雕契约](v5-design-and-performance.md#可选局部浅浮雕)；先有当前可用底图、精确文字及保护区，准备命令复用现有排版器产生平面字引导，不调用模型。

```bash
python3 <skill-root>/scripts/lc_image_pipeline.py title-effect-prepare \
  --manifest <manifest> --job <id> --json
python3 <skill-root>/scripts/lc_image_pipeline.py title-effect-event \
  --manifest <manifest> --job <id> --event tool_started --attempt-id <new-attempt-id> --json
# 实际调用编辑工具：先查看引导图，按返回prompt仅编辑指定短标题。
python3 <skill-root>/scripts/lc_image_pipeline.py title-effect-event \
  --manifest <manifest> --job <id> --event tool_returned --attempt-id <same-attempt-id> --json
python3 <skill-root>/scripts/lc_image_pipeline.py title-effect-ingest \
  --manifest <manifest> --job <id> --attempt-id <same-attempt-id> \
  --artifact <actual-returned-image> --mask <reviewed-grayscale-mask> --json
```

事件可用 `--timestamp <epoch>` 记录真实工具时刻；工具失败使用 `--event failed --reason <reason>`，明确等待时追加 `--retry-after-seconds <seconds>`。新尝试用新attempt-id，质量修复/瞬时重试分别填写 `--kind quality_repair|transient_retry --reason <reason>`；历史独立保存，调度容量／退避／成功计数与产品生图共用。prepare、event和ingest只登记真实操作，不能代替实际编辑或伪造返回时间。

派发前校验原字形确实位于允许区内，且不碰产品或其他文字；版式失败及 HOLD 不得派发。局部效果与产品生成共用项目并发上限，工具返回后释放效果槽位。禁用效果使用 `decorative_effect={"kind":"none"}` 或移除该字段；保留历史但不再绑定弃用候选。

候选是与画布同尺寸的不透明图，采用遮罩为同尺寸灰度图。遮罩完整覆盖原目标标题，只在allowed_bbox_norm内采用文字及接触阴影，不得覆盖其他文字或产品保护区。采用素材、遮罩、来源和提示进入指纹，变更使相关效果/排版失效，保留未变产品底图；无有效效果时返回平面版本并记录fallback_reason。

入库后走正常 `review-prepare → 实际看图 → review-submit`。在 `reviews.title_effect_review` 填当前binding、transcription、unexpected_text、bbox_norm、observed_surface、verdict/notes；原尺寸/360可读、承载面可见、材质透视、受光接触、产品与其他文字未变、纯装饰用途均须真实观察。不得复制计划短标题当转录，也不得把ingest成功当最终效果通过。

## 排版、导出与 QA

```bash
python3 <skill-root>/scripts/lc_image_pipeline.py finalize --manifest <manifest> [--jobs <id> ...]
```

`local_overlay` 从无字底图或本地商品图层合成开始，等比适配画布后应用指定角色和显式设计值。颜色达到4.5:1即保留；不足时只在allowed_adjustments内调整明度、位置或局部柔和背景，并记录调整，仍失败则修复布局，不静默覆盖字色或增加大底框。`model_native` 使用完整模型海报，跳过本地排字及字体加载，但仍做最终预览、文字与设计审阅。两路都执行导出及适用AI元数据；方图、竖图和A+横幅分别设计，不拉伸商品，不用补白代替构图。

`review-prepare` 会先产生 `review/image_layers/<id>.png` 的图像待审层；local 路线此时无营销叠字，native 路线已含模型文字。来源判断未完成时可能尚无可交付文件。逐张查看并填写 `ai_disclosure`，将 `reviewed_image_sha256` 绑定 `job.image_sha256`，再执行导出，无需因此重生。包含逼真合成人物时嵌入 `contains-synthetic-performer` 并回读验证，详见 [AI 图片规则](ai-image-policy.md)。主图白角自动检查只能筛查，不能证明整张背景纯白或内容符合类目。

含照片插图或拼版时，检查全部 `layout.items[].image` 和 `layout.panels[].image`，并将 `ai_disclosure.reviewed_visual_fingerprint` 绑定 `job.disclosure_visual_fingerprint`；该指纹覆盖底图像素及附图内容，清单见 `job.disclosure_extra_images`。附图含 AI 人物同样披露，不能只检查底图；仅本地改字不触发图像来源重审，附图内容改变则重审。

排版预览位于 `review/layouts/<id>.png`，检查结果为同名 JSON，移动端预览为 `<id>-360.png`（最终成品按宽 360 px 缩放的检查预览，不是独立重排图）；无营销排版的主图直接查看无字画面。查看成品原尺寸、商品及 P0/P1 对照、360 px 宽预览。缺审阅结论保持 `review_pending`，实际失败才进入相应修复流程；不通过联系表一次性签发全部细节。

V3设计契约在最终JPG字形核心检查最低4.5:1，保留实际成品、无文字背景及字形遮罩的绑定；不能以整框平均亮度或外部阴影替代。质量92不通过时仅该图重新编码95，仍不通过进入修复；其余图不重编码。A/B须显式设置相同画布及编码质量，不自动生成试验图。先检查统一尺寸无损合成的产品保护，再判断JPEG压缩损失。

先准备审阅包，annotations 仅可写 `raw_product_bbox_norm`（相对 raw 画布归一化）与 `detail_output_bbox_norms`（相对最终输出归一化）；命令制作待审成品、预览及细节对照，不签 pass。单图与批量共用实现：同轮就绪图一次共享准备和排版、正常批次最多一个浏览器，再逐图组包；逐图错误回滚，成功结果保留。360 预览绑定布局及自身内容哈希，已有有效预览不重复编码，缺失／篡改时重建，不省去逐图目视。`--job` 处理单图；`--jobs <id> ...` 处理同轮就绪图，省略两者处理全部就绪任务。批量 annotations 顶层以 job id 为键，未就绪和 HOLD 跳过：

```bash
python3 <skill-root>/scripts/lc_image_pipeline.py review-prepare \
  --manifest <manifest> --job <id> --annotations <annotations.json>
# 实际查看 review/packets/<id>.json、review/layouts/<id>.png 与细节对照后：
python3 <skill-root>/scripts/lc_image_pipeline.py review-submit \
  --manifest <manifest> --packet <review-packet.json>
```

`review-submit --packet` 接受单包、包数组或 job ID 为键的包映射；批量逐图绑定当前 image／visual／annotation 指纹，返回 results/errors，单图失败不撤销其他图成功；坐标、图像、文案或设计依赖变化须重新 `review-prepare`。各 QA 字段初始为 `{verdict: null, notes: ""}`，实际看图后填写。V5 任务须填写 `visual_design`，notes 覆盖焦点、层级、间距、背景用途、图文关系与选中样本；样本待确认不能签设计通过。

`model_native` 另填 `reviews.model_text_review`：从真实成品转录每个 block 的 `id/text/bbox_norm`，逐字核对拼写、标点、漏字，检查小字及徽章并填写 `unexpected_text`（检查后确实没有才填空列表）。不能把计划 copy 直接复制为目视记录，也不能把 native 当无字图跳过可读性审阅。模型错字或额外声明进入该图的生成修复。

V3 panels 每张图片必须绑定已注册且路径匹配的参考，生成／修复素材保留已审阅实拍来源链；事实 ID 不能代替像素来源。按 packet 的实际裁切逐 panel 填 `panel_reviews` 的 `provenance/product_identity/crop` 及说明，素材或裁切变化使旧结论失效。

在 `detail_qa_results` 为每个必须展示的 P0/P1 填 `verdict: pass/fail` 及说明；在 `semantic_qa_results` 分别审阅 geometry、material、components、scene_scale、clarity 和 visual_integrity（图案、数量、镜像及互动合理性）；在 `policy_qa_results` 审阅 main_product_only、claims、competitor_copy、text_readability 和 mobile_readability。

`not_applicable` 仅用于确实不适用且运行时允许的检查：主图的场景尺度、非主图的主图内容、真正无营销文字图的可读性。模型原生文字不是“无本地排字所以不适用”；清晰度和商品结构也不能记为不适用。

```bash
python3 <skill-root>/scripts/lc_image_pipeline.py qa --manifest <manifest> [--jobs <id> ...]
```

任何必需失败都不能被之后的 P2 或其他通过结论覆盖。自动检查负责尺寸、依赖、字体、布局几何及元数据等确定性条件；目视审阅负责商品真实性、材质、场景物理关系和实际可读性。

## 修复、恢复与速度

按失败所在阶段处理：

- **待审阅 `review_pending`：** 查看原尺寸及对照，补真实结论；不消耗生成次数。
- **布局失败 `layout_repair_needed`：** 修正文字、模板或保护区，再排版；没有改变构图时不重生底图。
- **导出失败 `export_repair_needed`：** 修复尺寸或元数据导出；复用底图与布局。
- **模型质量失败 `generation_repair_needed`：** 使用定向修复提示，从本图当前底图或完整 native 海报修复目标区域；local 路线再排版，native 路线重新核对实际文字。每图默认最多一次质量修复，重复失败则阻断并补资料或交由人工修图。
- **网络／工具瞬时失败：** 同一提示指纹最多重试两次；修改提示后不能冒充同一次重试。

来源审阅、生成、排版、导出与QA指纹分别绑定实际依赖。local文案、字体或允许范围内的设计修正只重排并重审该图；局部浅浮雕的文案、字号、区域、素材、遮罩、承载面或受光变化只更新相关效果/布局和审核，不重生未变的商品底图。native文案或旧3D嵌字变化只修订该模型海报；构图／留白变化仅影响依赖它的底图，元数据变化只重新导出核验。未变任务不调用模型、不启动渲染器、不重建审核素材。

重处理命令采用“短锁读取快照 → 独立暂存区锁外处理 → 校验目标与共享依赖后短锁提交”。单图快照保留全项目校验必需输入、共享报告和本图产物，包括历史目录中声明的真实依赖；省去其他图的无关 raw／final／缓存，副本独立，冲突拒绝，恢复先处理事务日志。提交只合并目标任务及有效产物，不用旧 Manifest 覆盖其他任务；图片编码、字体准备、排版与对照不持有整个执行期写锁。

同次来源评估按源图复用一次解码／方向校正／RGB 转换，供产品、目标画布与细节裁图使用，随后释放。细节裁图先校验来源、坐标、算法版本与缓存内容，命中不解码。内容摘要及只读资源仅在本次操作内复用，写入、文件变化、提交边界重新核验，不依赖跨命令时间戳缓存。字体、许可证、缺字与内容哈希检查保留，不引入常驻服务。

不要伪造哈希或仅修改 `status` 复用旧验收。性能报告分别记录参考／规划、就绪等待、工具墙钟、交接、锁等待、编码、字体、渲染、审核准备／等待、导出与打包；批级共享开销只记一次，不把累计时间重复当作逐图成本，也不相加重叠区间。历史 generation/review 生命周期保留原义，缺少真实事件的指标标记待验证。真实交接 p95 目标 ≤30 秒、无阻断派发空档 p95 目标 ≤10 秒，必须用足够实际生产样本验证，不承诺模型耗时固定。

## 交付门槛

```bash
python3 <skill-root>/scripts/lc_image_pipeline.py delivery-check --manifest <manifest>
```

单图操作不重建整套总览；交付前运行不带 `--jobs` 的全项目 `finalize`，统一刷新或复用联系表和完整对照，再运行 `deliver --json`。后者复用紧凑整理前后两次必要门禁，不在其前再重复整套检查；单独诊断仍可使用 delivery-check。门槛重查当前来源、生成与排版依赖、成品哈希、审阅及元数据。任何必需图未通过都不能声明整套完成。

`deliver --json` 返回 `output_dir`、`images`（job_id、filename、path、sha256）和 `image_count`，清单来自当前 QA 任务，不扫描目录猜成品。新项目主图、副图、A+ 按原有序名称平铺于 `final/`，其中仅已通过 QA 的最终 JPG；最终回复链接 output_dir。Manifest、报告、底图与审核记录留在项目目录，总览／预览不作成品交付，不生成 ZIP 或 HTML。

旧项目仅在显式 deliver 时把分散的已审图片汇集到 `delivery/images-vNNN/`；额外文件或历史版本存在时也创建新版本，不覆盖原图与历史文件。没有 compact_jpg 的旧 PNG/JPEG 编码不改变；无变化重复交付逐文件验哈希后复用，不重编码、不重复复制。Listing 与选定尺寸、A+ 与请求模块仍须一致。


### 自动化调用与最短正常流程

命令推荐带 `--json`，stdout 返回一个对象（含 ok、command、manifest），日志到 stderr。一次 plan → 预读本图提示和参考 → transition／真实工具开始 → 工具返回立即 ingest → 同轮就绪图 review-prepare → 实际逐图观察 → review-submit，随返回 dispatch 补位。待本地合成图直接 review-prepare，无需额外 compose→prepare 循环，也不等待其他模型凑批。批审核部分失败返回非零退出码与逐图 errors，成功任务保留。整套最后一次 finalize→deliver，回复成品文件夹入口。清理后未变成品复用，修改单图只物化其必需缓存。

V6 字段、例外及预算见 [设计与性能契约](v5-design-and-performance.md#v6-默认契约与紧凑交付)。缺少契约的旧项目不自动启用；维护过程中也不自动迁移或清理现有生产目录。
