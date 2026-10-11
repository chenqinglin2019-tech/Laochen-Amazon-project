# V7 项目生产流程（兼容专用）

仅用于没有 `workflow_policy` 或显式 `legacy` 的历史项目。继续使用原 `lc_image_pipeline.py`、完整运行时与实际审核；不自动迁移。先读 [V7 编排](v7-orchestration.md)、[V7 生产规则](v7-production.md)，构图规则见 [composition.md](composition.md)。鉴权和凭据处理沿用 SKILL.md。

## 2. 生产命令序列（先设计图文，再生底图）

命令都在 skill 根目录执行并带 `--json`。`P` 指 `verify` 返回的 `commands.python`；`M` 指项目的 `project_manifest.json`。

1. **运行时**：`python3 scripts/runtime_bootstrap.py verify --json`（Windows：`py -3 scripts\runtime_bootstrap.py verify --json`）。7 天内命中缓存；失败时按 §0 处理，管线会自动使用选中的运行时。
2. **产品事实**：确认产品、包含物、站点语言和图位计划，建立四项锁，一次写完整套批准文案。宽幅 A+（1464×600）文案要短：标题约 ≤20 个字符、正文 ≤40 个字符，否则任何版式都放不下。
3. **建项目**：
   - `P scripts/lc_image_pipeline.py init --project-dir D --project-id ID --marketplace US --language en [--include-a-plus --a-plus-modules header:1464x600,...]`
   - `add-references --manifest M --photos <实拍图…> [--views front three_quarter detail]`：自动复制照片、识别视角、在纯色背景上测量商品框。
   - 在 manifest 里写：`product_truth`（四项锁）、`facts`、`critical_details`、各图 `layout.text_groups` 的批准文案。
   - 每张带本地文字的附图填写 `composition_intent`（留白方式、主体大小、版式理由），并确定产品区、文字框和关键保护区，字段与操作见 [composition.md](composition.md)。场景图优先自然留白；尺寸/步骤图可预先设计分区。
   - 细节在某图未写可见性时默认 optional；数字文案与 facts 精确匹配时自动绑定 claim。
4. **模板**：用户给了参考套图，按 [templates.md](templates.md) 入库；否则无需手动选，plan 会按产品自动选并钉住。
5. **来源审阅**（一次）：
   - `source-review-prepare --manifest M`，然后看 `review/source/sheet.jpg`。主图抠图提案也在这张图上（洋红色 = 被去掉的背景）。
   - 包里已有实测预评：只改与所见不符的，补齐为 null 的。
   - `source-review-submit --manifest M --packet review/source/packet.json --observation "<一句所见>" [--confirm-layers 01_main:0 | --reject-layers 01_main:0]`
6. **规划**：`plan --manifest M`。用真实字体实测文案容量；新项目返回候选版式供代理结合主体大小和图位用途重新设计，不再仅因“塞得下”静默换成侧栏。完成图文构图后再派发；批准文案不擅自缩短。
7. **生成**（按波次，见 [tool-orchestration.md](tool-orchestration.md)）：
   - `reserve --manifest M`：返回本波每张图的提示正文和参考图路径。
   - 每个预约调用一次内置生图：提示原样，参考按顺序；宿主允许就同一回合并行。
   - `ingest-batch --manifest M --item <job> <attempt_id> <绝对路径> …`：原图入库并返回 `composition_review_required`。新项目先生成主要使用场景附图作为样板，没有此图位时选第一张带本地文字的附图；样板完整通过第 8 步后，再 `reserve` 并行其余图。产品快审不能替代完整样板审核。
   - 报错用 `--failed` 当场登记，没发出去的用 `--not-started` 退回。
   - 波与波之间不调用 status/plan。
8. **先验收底图，再排字审核**：
   - `review-prepare --manifest M --stage composition --job J`：看返回的实际无字底图，填写观测产品框、人物/动作保护框和四项构图结论，`review-submit --packet <构图包>`。本地合成也检查真实合成画面。失败先修底图，不进入排字。
   - `review-prepare --manifest M --stage final [--job J]`，然后逐张看返回的 sheet。
   - 填 `review/packets/answers.template.json`：每图一句 ≥20 字、各图不同的观察；只把不通过/存疑项写进 `exceptions`；可能出现人物时填 `people`。
   - 新项目还必须填写 `explicit.visual_design` 的图文关系、主体大小、构图完整、套系一致性；不能用“无异常”代替美感判断。失败注明 `base` 或 `typography`，对应底图返修或本地排字修复。
   - `review-submit --manifest M --packet <该文件>` 一次提交。
9. **交付**：`deliver --manifest M`，核对 `image_count`，只按图位顺序提供 `images[].path` 对应的最终图片文件链接。不制作或交付整套预览拼图、网页、ZIP、提示词和审核文件；内部逐图质检保留。不要为交付调用 `finalize`。缓存清理只在用户要求时 `compact`。

## 3. 硬规则（每条只写在这里）

- **四项锁**：
  - Geometry：锁定结构、部件关系和真实比例。
  - Material：锁定已知材质、颜色和工艺。
  - Scene Scale：明确支撑面、相对尺度和接触方式，不编造尺寸。
  - Critical Detail：P0 功能 / P1 识别 / P2 次要。
  - 未知尺寸、基材、背面、配件不能从参考图或生成图补事实。必要的 P0/P1 细节没有依据时，补资料或改构图。
- **路线**：逐图选择 pixel_composite / reference_edit / reference_generate，依据是区域质量、放大倍率和证据。合成需要遮罩；实拍白底图可先 `cutout --reference R`，看叠加图确认后再用。
- **文字路线**（每图设置 text_mode）：
  - `none`：主图和白底图。
  - `local_overlay`：默认路线。尺寸、数值、步骤、FAQ、必要限制、品牌/Logo 都走这条；文案只写在 layout 里。
  - `model_native`：只用于一个非数值标题＋可选短正文，并写明 `model_native_reason`。对比度用 `native-text-measure` 测，不能目测。
- **文案**：不删、不缩、不改写批准文案；放不下时换配方、扩大文字区或重新分配图位，仍放不下就 `needs_input`。
- **构图先行**：上述文案与构图调整在生图前完成。生图后不得为救文字缩整幅底图、裁主体、扩画布、临时加侧栏；已规划好的信息分区允许。底图侵占文字区归入质量返修，字体/换行/对比度才归本地排字修复。
- **可读性**：最终 JPG 字形核心对比度 ≥4.5:1；按宽 360 px 预览时，标题 ≥18 px，正文/标签 ≥12 px。
- **主图**：纯白底（255），无营销文字和道具。新项目会优先用合格的白底实拍图本地抠图合成主图：商品像素真实，不占生图时间。不合格或被拒绝时才调用生图。
- **模板只借设计**：不抄参考图里的商品、品牌、文案、Logo 或主张。参考底板只用于学习背景、光线、机位和构图。
- AI 图片披露与站点规则见 [production.md](production.md#ai-图片规则)。
- 历史记录与哈希不得手改；状态只能通过命令改变。

## 4. 循环上限（到达即停，汇总给用户）

- **瞬时失败**：首发＋最多 2 次重试，限流（429）不计入次数。用尽后必须经用户确认，再执行 `transition --status pending --reset-transient --reason "..."`。
- **质量修复**：每图 1 次。达到上限后是终态，plan 不会自动解封。
- **样板**（新项目）：先完成一张附图的底图、排字、产品一致性与美感审核，达到 `qa_passed` 后再批量；不增加用户确认轮次。仅主图任务沿用主图流程。旧项目保留原锚点策略。
- **免费退回**：没发出去的预约每图最多免费退回 2 次，第 3 次按失败计。
- **本地修复**：排版/容量问题每图 3 次，超过即 `needs_input`。
- **同命令同输入连续两次同样的错误**：按 `diagnosis_required` 做针对性检查，不要重复 plan/force/审核。锁 10 分钟后过期；瞬时错误不计次。
- **needs_input**：所有问题一次性汇总后问用户，不逐条来回询问。
