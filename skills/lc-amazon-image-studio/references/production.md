# V8 图位、文案与整图提示策划

适用于 one_pass_v1；历史项目读 [v7-production.md](v7-production.md)。先完成策划，模型一次生成成品，附图生成后直接交付。

## 图位与产品事实

默认 01_main、02_size_or_components、03_primary_use_case、04_compatibility_or_installation、05_material_or_detail、06_storage_or_package、07_problem_solution。用户有图位计划时保留其意图；缺尺寸证据可改为包含物或其他真实信息，不编造尺寸凑图。

每图一个核心结论。A+ 每模块独立构图和画幅，不把方图压扁为横幅。工具、家居、宠物、电子等商品优先回答真实购买顾虑，场景必须有合理支撑、接触、比例和用途。

product_truth 记录商品身份与 geometry_lock、material_lock、scene_scale_lock；critical_details 记录 P0 功能、P1 识别、P2 次要细节。必须展示的 P0/P1 细节绑定该图使用的商品证据；看不清或未知的结构不用模型补事实。

## 文案与设计

- 批准文案只存 approved_copy，按阅读顺序排列 role/text/fact_ids。数字与单位需要事实绑定；step 的开头序号不算规格事实。兼容、认证和性能主张也要绑定对应资料，即使没有数字。
- 标题表达一个清晰结果，正文只补必要限定。宽幅 A+ 用短标题与短正文，生成前控制密度，不再依赖本地字体测量。保持批准文案逐字一致。
- design_brief 指定 goal、scene、composition，可加 lighting、style 和局部信息层级。以自然摄影、主体比例和清晰阅读关系为目标；不为所有产品强制同一种配方。
- 模板提供套系配色、字体气质、图形语言、摄影与版式。原布局坐标只用于说明相对关系，不作为本地排字任务；不附带参考图的商品身份、文字或主张。
- 人物或手部在策划时设置 human_source=synthetic/real/non_photorealistic，默认 none 会明确禁止添加人物。synthetic 导出含 contains-synthetic-performer 的 XMP 关键词。保留现有披露约定，不虚构已审核的图片来源。

## 六段式提示

编译器固定输出图位目标 → 商品证据与锁 → 场景构图 → 套系设计 → 逐字文案 → 约束。附图要求一次完成商品、场景、文字、标注与版式；支持多文案块、尺寸、步骤和 FAQ。

商品图作为 product，设计图作为 style；编辑目标为 edit_target。附件顺序与提示编号保持一致，来源文件哈希进入生成指纹。风格图不能提供新商品事实。

主图请求真实透明背景、产品与包含物，无新增营销文字、道具或投影；本地仅铺纯白背景并验证最终 PNG。主图背景专项检查不扩展为附图审核。

## 输出边界

附图入库只进行文件检查和必要等比尺寸标准化，无 OCR、产品一致性、美感、对比度或手机预览复核，不自动质量返修。源画幅比例错误时报告单图规格异常；不拉伸或裁主体。

修改批准文案或场景会改变对应图的生成指纹，需要新生成；无输入变化的 plan/reserve/deliver 不重生。用户未提出修改时按图位交付。
