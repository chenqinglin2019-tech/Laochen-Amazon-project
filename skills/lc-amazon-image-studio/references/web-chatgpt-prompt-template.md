# 可选网页 ChatGPT 提示包

仅在用户明确要求额外的网页版提示包时使用。常规生成与内置排版不需要此流程，不切换默认生成后端，不自动追加额外图片。

把以下占位内容替换为当前产品已核实事实。输出仍回到本 skill 的路由、质量和元数据流程；仅 `local_overlay` 再本地排字，`model_native` 不重复叠字。网页模型的响应尺寸、文字及产品细节不能直接视为验收通过。

## 整套说明模板

```text
Create the requested image assets for [PRODUCT] for Amazon [MARKETPLACE]. All approved marketing copy uses [LANGUAGE].
Deliver one candidate for each of [REQUESTED LISTING COUNT; DEFAULT 7] images with width:height [1:1 or 1:1.3]. The local final exporter will produce [2000×2000 or 2000×2600] Listing images, with neither edge below 1600 pixels. Add A+ only if requested, for [MODULE AND CANVAS]. Do not create extra variants or a draft-then-regenerate sequence by default.

Strategy: [user_planned or competitor_learning].
User plan to preserve: [PURPOSES / CONTENT / COMPOSITIONS / ORDER].
Buyer and primary task: [FACTS].
Confirmed product facts and evidence: [FACTS WITH SOURCE IDS].
Unknown facts and surfaces: [UNSUPPORTED CONTENT].

Inspect the product region at original detail, not just the file dimensions. Assess actual clarity, effective product pixels, target-view fit and available evidence. A high-resolution file may still contain a blurred product. A clear source may still have the wrong angle.
Choose pixel composite when product pixels are clear and fit the target scene; local reference edit when only part needs correction; reference-constrained generation when the product is globally blurred but supported by sufficient other evidence, or when the target view, lighting, pose or interaction requires reconstruction. Do not use a fixed render-mode order.

Preserve physical dimensions, structure, material identity, included parts and evidence-backed identifying details. Allow realistic perspective, visible silhouette, highlights and shadows to change with the target camera and environment. Never invent hidden ports, labels, textures or components. Reconstructed assets remain generated interpretations, not new evidence.

Each image must express one core selling job. Product render mode and marketing text mode are independent decisions. Follow the per-image text_mode exactly:
- none: no added marketing text; main images use this route.
- local_overlay: generate a text-free base with the planned text space and protection regions; approved headings, dimensions, FAQ, precise labels and grids are composed locally afterward.
- model_native: compose a complete photographic poster with integrated typography and purposeful graphics, rendering exactly the approved headline/body once each. Do not add claims, logos, badges or unexpected small print. There will be no local marketing text overlay afterward.
Preserve authentic product labels in every route. Never use model_native for the main image or a pixel_composite job. Keep copy readable in the final image at 360px width; shorten or recompose instead of endlessly shrinking text.
Design-reference priority: current user references, confirmed project design, then category-appropriate generic samples. Learn visual hierarchy, image crop, panel proportions, reading order and background purpose from individual finished units only; ignore screenshot UI, numbering and outer before/after comparison-board structure. References are not product facts. Use original execution; never transfer sample copy, products, packaging, brands, badges, purchase buttons or unsupported claims.
```

## 单图提示模板

```text
Geometry Lock:
- Confirmed physical dimensions, ratios and structure: [FACTS]
- Source views: [REFERENCES]
- Target view and allowed projection changes: [CAMERA / POSE]
- Unsupported surfaces and axes: [UNKNOWNS]

Material Lock:
- Material, colour, finish and texture identity: [FACTS]
- Permitted lighting and reflection changes: [SCENE]

Scene Scale Lock:
- Physical size and scale context: [FACTS]
- Support, attachment, contact and occlusion: [RELATIONSHIPS]

Critical Detail Lock:
- Required P0/P1 details: [DETAIL, LOCATION, EVIDENCE CROP]
- Hidden details: [DO NOT MOVE INTO VIEW]
- Any required detail without readable evidence: [BLOCK OR RECOMPOSE]

Image: [ID / SELLING JOB]
Render mode and rationale: [pixel_composite / reference_edit / reference_generate; QUALITY AND FIT REASON]
Text mode: [none / local_overlay / model_native]
Approved copy: [EXACT headline AND optional body; model_native ONLY]
Input roles: [WHOLE PRODUCT / EDIT TARGET / DETAIL / MATERIAL / COMPONENT]
Reference clarity and local defects: [ASSESSMENT]
Design brief: [REFERENCE UNIT / READING ORDER / TYPE HIERARCHY / IMAGE-TEXT RELATIONSHIP / BACKGROUND PURPOSE]
Layout and product region: [RECIPE / CANVAS / PRODUCT BOUNDS]
Reserved text region and protected regions: [BOUNDS]
Scene and lighting: [DESCRIPTION]
Forbidden claims or additions: [LIST]

For none/local_overlay, create a photorealistic base without added marketing text. For model_native, create the complete designed poster with only the approved copy above; render text values only, not metadata or evidence IDs. Do not stretch the product. Preserve authentic product labels. For a repair, change only [X] and keep all other established product features, correct text and scene regions unchanged.
```

导出前实际核对原尺寸及 360 预览；native 逐字转录真实成品并检查意外文字，不能拿提示文案当审阅结果。逐图记录是否含逼真 AI 人物，包括局部人物；规则与写入方式见 [AI 图片来源与导出](ai-image-policy.md)。不要要求网页模型在主图直接绘制 AI 水印来代替元数据。未知规格保持 HOLD，不生成虚构尺寸；本模板不授权 Amazon 上传。
