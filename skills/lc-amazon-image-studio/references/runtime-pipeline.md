# V6 运行流程

本地入口为 `scripts/lc_image_pipeline.py`；负责预检、提示编译、状态与缓存、内置排版、元数据及验收，不直接调用图像模型。实际生产先从 skill 根目录执行 `python3 scripts/auth_gate.py`，遵守 [SKILL.md](../SKILL.md) 原鉴权规则；本文件所有生产命令，包括 status、compact、恢复及并发适配，都不增加放行路径。正常生产顺序只以 SKILL 的主流程为准，本文提供各阶段的命令和失败处理。

## 环境与项目初始化

先按[环境准备](runtime-setup.md)运行标准库 `runtime_bootstrap.py inspect --json`，优先复用已安装的精确版本。仅当前权限明确完全访问时自动安装缺项；否则或无法自动安装时先向用户确认，不越权、sudo 或修改系统 Python。排版锁定 Node ≥20、Playwright 1.62.1、Chromium 149.0.7827.55、Pillow 12.3.0，NumPy 由 bootstrap 独立依赖规格固定；字体从 skill 内部加载，损坏须恢复原资源包，不近似替代。

下文管线命令的 `python3` 是 inspect 返回的选定 Python 占位；执行时必须替换为该真实路径，同时使用返回的 `LC_LAYOUT_NODE`、`LC_LAYOUT_NODE_MODULES`、`LC_LAYOUT_CHROMIUM`，包括薄适配内的子命令。不能装入 venv 后仍用系统 Python。标准库 bootstrap 与生产鉴权使用各自原入口；环境验证不代替鉴权。

inspect 只报告安装／版本状态，不证明运行成功。依赖齐全后本轮仍执行 `verify --json`，实际完成既有 doctor、Pillow／NumPy 导入及 Chromium 启动／内存截图；install 末尾已通过同一验证则不重复，未通过不得开始管线生产步骤。

```bash
python3 <skill-root>/scripts/runtime_bootstrap.py verify --json
python3 <skill-root>/scripts/lc_image_pipeline.py init \
  --project-dir <versioned-project-dir> --project-id <stable-id> \
  --listing-aspect 1:1 --short-edge 2000 \
  --marketplace US --language en --json
```

`--marketplace` 与 `--language` 必填。竖图使用 `--listing-aspect 1:1.3`；短边至少 1600 且竖图短边为 10 的倍数，保证精确比例，任何边不超过 10000。A+ 仅在用户要求时通过 `--include-a-plus --a-plus-canvas <WIDTH> <HEIGHT> --a-plus-module <module-name>` 加入，画布参数为两个整数；`--a-plus-count` 默认6，按用户明确数量调整；不使用 Listing 的比例和短边门槛推导 A+。

保留原始素材到项目 `source/`，填写 `project_manifest.json`。已有项目先 status 查看可恢复动作，兼容项目不运行 migrate；仅明确升级旧 schema 时按[历史兼容](v5-design-and-performance.md#历史项目与外部参考)迁移，不能把恢复请求当成全套升级。缺少模块信息的旧 A+ 不得只凭 `970×600` 猜 `a_plus_module`。

## 英文模板选择与保存

新 `init` 默认启用纯文本模板模式，按[英文模板库](design-template-library.md)先做套系与图位选择。用户新增参考实际看图、英文拆解、去重审核后用模板 importer 自动写用户库，再采用其 canonical ID。模板命令只读写 JSON，不调用模型、不复制图片。新项目的 recipe 初始不固定，由所选模板提供；没有设计 brief 时仅保留临时排版默认，不能把空骨架当成完成规划。

采用版本以文本快照绑定项目；编译 `design_brief.generation/layout`，对应阶段依赖保持分离。恢复已有图时不读源截图或重选最新库，新增用户模板不影响原项目。无合适模板时撰写项目原创说明并记录 `matched:false`，不强行匹配；主图继续使用白底专用规则。模板正文英文不改变目标站点文案语言，真实产品证据、字体／容量测量、最终目视审核仍必需。

新项目的 `style_contract.version=3`、`selection=design_first`，color_roles/font_roles默认空；Agent先按实际产品或明确参考填写角色，显式组／layout优先，不用最高对比候选覆盖已指定颜色。完整保留批准文案，不创建30%精简任务；容量不足先调整版式与既有图位，不能删词、缩字或擅自新增图位。旧V1/V2契约按原规则运行，应用新设计时仅重新验证受影响部分。

旧外部参考原图索引与选择命令仅在实际使用该模式时读取[历史项目与外部参考](v5-design-and-performance.md#历史项目与外部参考)。设计说明不提供产品事实；显式用户参考缺失或哈希变化只暂停受影响的新生成及匹配审核，其他独立任务继续。

## 输入与审阅记录

每张参考填稳定 `id`、`path`、`role`、`view`、`product_bbox_norm` 和 `quality_review`。商品框是整个参考图中的 `[x,y,width,height]`，均归一化到 0–1；不可使用整图尺寸替代产品区域质量。

参考角色明确区分整件产品、局部细节、材质、组件、包装和编辑目标。逐张原尺寸检查后，填 `quality_review.clarity/evidence/defects/notes/reviewed_sha256` 并绑定 `reviewed_region_fingerprint`；字段枚举及模式选择见 [区域质量与内置排版](layout-and-quality.md)。

每个任务填 `source_reference_ids`、目标 `view`、产品目标框、四项锁需要的事实、`source_assessment`、`render_mode` 与理由。目标视角可以由多张参考共同支持；不能只查看第一张参考，也不能只比较视角名称。`source_assessment.reviewed_context_fingerprint` 绑定本次任务上下文，区域或上下文变更后须重新审阅；先填写参考审阅并重新 `prepare`，再使用 `job.assessment_context_fingerprint` 作为本轮期望值；`reviewed_reference_hashes` 覆盖 `job.render_decision.required_reference_hashes`，包括必要局部来源，不自行猜值。

V2 的全局 `product_truth.source_quality/master_asset_mode/master_confirmed` 仅作历史兼容，不再必填或控制生成方式；V3 使用各任务的区域审阅与 `render_decision`。

逐 P0/P1 注册 `critical_details`：视觉证据与文字主张分开、参考坐标相对商品框、每张图明确 `required/optional/hidden`。原尺寸 census 完成后才设置 `critical_detail_census_completed=true`；所有候选裁图太小或模糊时保持 `unverifiable`。

生成前逐图明确 `text_mode`，它独立于商品 `render_mode`：主图及无营销文字图为 `none`；摄影海报、A+、卖点及拼版默认 `local_overlay`，尺寸、数值规格、FAQ、步骤、必要限制及精确营销品牌／Logo整图保持本地排字。新图声明 `prompt_profile: images_2_5_v1`，普通摄影海报可选 `model_native_reason.kind: native_poster`，使用一个标题与可选简短非数值正文，事实性卖点仍绑定 `job.claim_ids`。少量1–5词、无品牌/数字/事实的装饰标题可用文字组 `decorative_effect.kind=surface_emboss`，保留本地品牌及正文，整图不转native；艺术字与3D嵌字仍受原短标题规则约束。缺 prompt_profile 或显式legacy的旧图保留原提示字节与生成指纹，本地排版／QA仍遵守既有源码哈希复核，不因此重生底图或重写旧审核哈希。初始化只提供空白V3本地骨架，不自动虚构或改写文案；完成规划后再按用途选路。

`model_native` 的唯一文案入口是 `job.copy.headline/body`，不得再填本地文字、图标或 panels；模型一次设计完整海报，不能自行扩写。`local_overlay` 文案只放 `layout`，新项目使用 `layout.version: 3`，并提前确定构图、文字组和保护区。使用 `facts` 的 `id/text/evidence` 保存主张来源，`job.claim_ids` 关联本图事实；局部说明或尺寸另用 `evidence_refs` 绑定。数值、材质、性能与兼容性仍须真实依据，文字路线不改变证据门槛。

原像素合成使用 `product_layers` 的 `reference_id/asset_path/mask_path/bbox_norm`，可加 `crop_bbox_norm` 和 `shadow`。使用已检查的透明图或与商品资产尺寸完全一致的遮罩；脚本不会猜遮罩。确需保留整块矩形图时才明确 `opaque_rectangle: true`。像素来源须匹配 `job.render_decision.pixel_source_reference_id`，不默认第一张参考；原像素合成不是“给模型一句不要重绘”。

另外的抠图或附加遮罩需按 [图层来源绑定](layout-and-quality.md#生成方式决策) 填 `source_binding`；`prepare` 自动写入 `layer_asset_hashes`。资产、遮罩或裁框改变后，先重新审阅本层来源，再绑定更新后的任务指纹。每层的 `asset_origin` 与参考 `provenance` 一致，多组件层也须独立满足清晰度和视角要求。

## 准备与调度

```bash
python3 <skill-root>/scripts/lc_image_pipeline.py plan --manifest <manifest> --json
# 已有实际工具容量证据时，在本次 plan 同时提供：
# --tool-capacity 2 --tool-capacity-source <actual-source> --tool-capacity-reason <observed-limit>
```

`plan` 已调用 prepare 完成结构、区域像素／裁图、审阅证据、提示与分阶段依赖准备；不要例行 prepare→plan 双跑。独立 `prepare --jobs <id> ...` 接口保留，输入改变或准备绑定过期才重新 plan；恢复时先读 status。未知清晰度先审阅，必要细节缺实拍先补资料或改构图，不能把状态直接改成通过。

准备后的队列随 ingest／review-submit／status 返回，不反复 plan 查询下一张。共享商品身份或 census 未完成时不能生成；单张证据缺口仅阻断该图。风险最高的可执行锚点真实 QA 通过后从并发 2 开始；随后同档位连续两个不同 attempt 首次成功入库升一档，最高 4。429 降 1，单次超时降一档、连续两次超时降 1；退避后 60 秒不升速，遵守 Retry-After。旧 epoch／旧档位的迟到成功与重复回调不用于升档，降档不取消在途任务；旧项目无 scheduler_policy 保留原策略。

只有模型调用扣减容量；产品生图和局部标题编辑共享健康记录与槽位，本地 compose 独立列出，仍检查来源及锚门。`concurrency` 是当前档位，`network_health` 保存健康与工具能力证据；显式 `--tool-capacity 1..4` 必须同时带 source／reason，不能无依据设 1。默认每图一个候选，HOLD 不进模型队列；浅浮雕可为零，不增加固定样图或全套重生关卡。

生成与本地处理、审核分别推进，不能让待审图占生成 slot，也不能为凑本地批次等待模型。已绑定且指纹未变的 raw／布局／QA 必须复用；本地改字只重排，模型原生文字改字只修订该图，改元数据不重生。

实际调用使用[内置工具薄适配](tool-orchestration.md)，它复用现有 transition／attempt-event／ingest，不另建调度器。必须 await 全部在途工具调用，使用工具提供的 yielded-cell 等待机制；不能把生成任务丢到未等待的 Promise 或后台 shell。已有真实且仍匹配的锚图产品审核证明可在本地重排期间维持调度许可，但不能代替当前成品 QA 或交付。

## 生成、图层与提示绑定

`pixel_composite` 填好图层后运行 `compose --manifest <manifest>` 进行本地合成，无需进入模型生成状态。需要模型的任务在生成前运行：

```bash
python3 <skill-root>/scripts/lc_image_pipeline.py transition \
  --manifest <manifest> --job <id> --status generating --json
```

预读 plan/ingest/review-submit 返回的提示文件与参考路径，再紧接执行 transition、tool_started 和实际工具调用。派发锁内只核验来源内容、递归证据与准备绑定，不生成预览或排版；缺少或过期评估返回重新 plan 要求。transition JSON 的 `attempt_id`、`prompt_hash` 随工具调用保存；返回不等待其他 slot，立刻 ingest 绝对 raw 文件：

`dispatch.action` 返回 `image_gen` 或本地合成的 `compose`。模型任务按以下工具事件顺序调用并入库：

```bash
python3 <skill-root>/scripts/lc_image_pipeline.py attempt-event \
  --manifest <manifest> --job <id> --attempt-id <attempt-id> --event tool_started --json
# 调用 image_gen；在工具真实返回时捕获 <returned-epoch> 及 <absolute-raw-path>
python3 <skill-root>/scripts/lc_image_pipeline.py ingest \
  --manifest <manifest> --job <id> --artifact <absolute-raw-path> --attempt-id <attempt-id> \
  --tool-returned-at <returned-epoch> --json
```

`ingest` 绑定 raw、立即置为 `generated` 并释放 slot；同一 attempt 绑定同一 artifact 是幂等的，旧 attempt、旧 prompt、同一 attempt 的不同 artifact 或其他冲突会被拒绝。它不覆盖旧 raw：重试／修复使用 `raw/attempts/<job>-<attempt>.<ext>`。读取当前编译提示及 `generation_reference_paths`，只附本图必要的产品、细节和设计引用，按实际附件顺序编号并标明角色。编辑本地图像前先查看目标。新版提示按 [联合 imagegen 提示契约](imagegen-prompt-profile.md) 组织用途、参考、场景、构图、文字和四项锁，全部规范化在编译与绑定前完成；工具实际发送已绑定提示，不二次增强。`none/local_overlay` 不生成额外营销文字，`model_native` 只绘制已批准文案且每块一次，所有路线都保护商品自身真实标签。

`ingest --tool-returned-at` 在同一次提交校验真实事件顺序、记录返回时间及入库；仍兼容单独 `attempt-event --event tool_returned --timestamp <epoch>`。缺少真实时刻时不得补造；默认命令时刻不代表此前工具返回或锁等待。ingest 和 review-submit 返回最新 dispatch，预读后立即补位，无需再例行完整 plan。`tool` 是调用墙钟（含网络与服务端排队），不是纯推理；真实返回到入库 p95 ≤30 秒仍需正式生产验证。

内置调用明确网络失败时使用既有 `transition --status pending --reason <actual-error>`；工具明确给出等待秒数时追加 `--retry-after-seconds <seconds>`，不能仅在说明文字中记录而忽略调度等待。

同视角可复用已验收生成素材，但保留生成身份及实拍依赖。新视角必须重新定位商品框和关键细节：在 `detail_output_bbox_norms` 写整个最终画面的精确归一化框，不能沿用源图二维位置假定真实位置。

可选局部标题的字段、工具事件与额外视觉记录只在启用时读取[局部浅浮雕契约](v5-design-and-performance.md#可选局部浅浮雕)，普通套图不运行这组命令。

## 排版、导出与 QA

正常单图使用 review-prepare／真实观察／review-submit；提交已包含该图导出与 QA，不例行额外运行 postprocess、qa 或 finalize。全套 finalize 仅在交付前更新总览。

`local_overlay` 从无字底图或本地商品图层合成开始，等比适配画布后应用指定角色和显式设计值。颜色达到4.5:1即保留；不足时只在allowed_adjustments内调整明度、位置或局部柔和背景，并记录调整，仍失败则修复布局，不静默覆盖字色或增加大底框。`model_native` 使用完整模型海报，成品阶段跳过本地排字及对应字体加载（预检仍真实测量容量），仍做最终预览、文字与设计审阅。两路都执行导出及适用AI元数据；方图、竖图和A+横幅分别设计，不拉伸商品，不用补白代替构图。

`review-prepare` 先产生 `review/image_layers/<id>.png` 图像待审层；local 路线此层无营销叠字，native 已含模型文字。来源判断未完成时可能尚无可交付文件。逐张在审核包填写实际 `ai_disclosure`，由 review-submit 绑定 `reviewed_image_sha256` 并导出，无需重生。包含逼真合成人物时嵌入 `contains-synthetic-performer` 并回读验证，详见 [AI 图片规则](ai-image-policy.md)。主图白角检查只能筛查，不能证明整张背景纯白；近白且存在可信背景／产品阴影双遮罩时可选[本地规范化](v5-design-and-performance.md#可选主图背景规范化)，不降低最终 JPG 阈值。

含照片插图或拼版时，检查全部 `layout.items[].image` 和 `layout.panels[].image`，并将 `ai_disclosure.reviewed_visual_fingerprint` 绑定 `job.disclosure_visual_fingerprint`；该指纹覆盖底图像素及附图内容，清单见 `job.disclosure_extra_images`。附图含 AI 人物同样披露，不能只检查底图；仅本地改字不触发图像来源重审，附图内容改变则重审。

排版预览位于 `review/layouts/<id>.png`，检查结果为同名 JSON，移动端预览为 `<id>-360.png`（最终成品按宽 360 px 缩放的检查预览，不是独立重排图）；无营销排版的主图直接查看无字画面。查看成品原尺寸、商品及 P0/P1 对照、360 px 宽预览。缺审阅结论保持 `review_pending`，实际失败才进入相应修复流程；不通过联系表一次性签发全部细节。

V3设计契约在最终JPG字形核心检查最低4.5:1，保留实际成品、无文字背景及字形遮罩的绑定；不能以整框平均亮度或外部阴影替代。质量92不通过时仅该图重新编码95，仍不通过进入修复；其余图不重编码。A/B须显式设置相同画布及编码质量，不自动生成试验图。先检查统一尺寸无损合成的产品保护，再判断JPEG压缩损失。

先准备审阅包，annotations 仅可写 `raw_product_bbox_norm`（相对 raw 画布归一化）与 `detail_output_bbox_norms`（相对最终输出归一化）；命令制作待审成品、预览及细节对照，不签 pass。单图与批量共用实现：同轮就绪图一次共享准备和排版、正常批次最多一个浏览器，再逐图组包；逐图错误回滚，成功结果保留。360 预览绑定布局及自身内容哈希，已有有效预览不重复编码，缺失／篡改时重建，不省去逐图目视。`--job` 处理单图；`--jobs <id> ...` 处理同轮就绪图，省略两者处理全部就绪任务。批量 annotations 顶层以 job id 为键，未就绪和 HOLD 跳过：

```bash
python3 <skill-root>/scripts/lc_image_pipeline.py review-prepare \
  --manifest <manifest> --job <id> --annotations <annotations.json> --json
# 实际查看 review/packets/<id>.json、review/layouts/<id>.png 与细节对照后：
python3 <skill-root>/scripts/lc_image_pipeline.py review-submit \
  --manifest <manifest> --packet <review-packet.json> --json
```

`review-submit --packet` 接受单包、包数组或 job ID 为键的包映射；批量逐图绑定当前 image／visual／annotation 指纹，返回 results/errors，单图失败不撤销其他图成功；坐标、图像、文案或设计依赖变化须重新 `review-prepare`。各 QA 字段初始为 `{verdict: null, notes: ""}`，实际看图后填写。V5 任务须填写 `visual_design`，notes 覆盖焦点、层级、间距、背景用途、图文关系与选中样本；样本待确认不能签设计通过。

`model_native` 另填 `reviews.model_text_review`：从真实成品转录每个 block 的 `id/text/bbox_norm`，逐字核对拼写、标点、漏字，检查小字及徽章并填写 `unexpected_text`（检查后确实没有才填空列表）。不能把计划 copy 直接复制为目视记录，也不能把 native 当无字图跳过可读性审阅。模型错字或额外声明进入该图的生成修复。

原生字形不由本地字体／字形对比度检查自动签发；在既有 `model_text_review.notes` 记录当前最终 JPG 的路径／哈希、实际字形核心取样方法、最低对比度≥4.5:1及360预览标题≥18px／正文≥12px的测量依据。最终编码后补充观察使用 `review-prepare --force` 取得新包再提交，不修改旧已提交包，编码字节变化须重测；不改变输出流程。无法取得可验证证据则转local_overlay并使用正常无字底图，不重复叠字。

V3 panels 每张图片必须绑定已注册且路径匹配的参考，生成／修复素材保留已审阅实拍来源链；事实 ID 不能代替像素来源。按 packet 的实际裁切逐 panel 填 `panel_reviews` 的 `provenance/product_identity/crop` 及说明，素材或裁切变化使旧结论失效。

在 `detail_qa_results` 为每个必须展示的 P0/P1 填 `verdict: pass/fail` 及说明；在 `semantic_qa_results` 分别审阅 geometry、material、components、scene_scale、clarity 和 visual_integrity（图案、数量、镜像及互动合理性）；在 `policy_qa_results` 审阅 main_product_only、claims、competitor_copy、text_readability 和 mobile_readability。

`not_applicable` 仅用于确实不适用且运行时允许的检查：主图的场景尺度、非主图的主图内容、真正无营销文字图的可读性。模型原生文字不是“无本地排字所以不适用”；清晰度和商品结构也不能记为不适用。

```bash
python3 <skill-root>/scripts/lc_image_pipeline.py qa --manifest <manifest> [--jobs <id> ...] --json
```

任何必需失败都不能被之后的 P2 或其他通过结论覆盖。自动检查负责尺寸、依赖、字体、布局几何及元数据等确定性条件；目视审阅负责商品真实性、材质、场景物理关系和实际可读性。

## 修复、恢复与速度

```bash
python3 <skill-root>/scripts/lc_image_pipeline.py status --manifest <manifest> --json
```

status 只读私有快照，返回已完成数量、在途 attempt、实际容量证据、阻断原因、可执行动作及计时覆盖；不 prepare、渲染、写 Manifest／锁／报告或执行事务恢复。沿用已绑定提示与真实产物恢复交接；只有输入变更、准备过期或受控模型修复才重新 plan。真实生产的状态读取、恢复及 compact 仍先满足原鉴权。

同输入、同命令／图位连续两次相同错误会记录 `diagnosis_required`；停止对该错误重复 prepare／plan／force／审核，按错误指向检查一个实际原因（如缺文件依赖、源指纹、排版溢出或审核包时效），修正后再执行。它是诊断提示，不是自动放行、重置修复预算或停止独立任务；工具已返回但路径／入库失败先恢复同 attempt，不再生一张。

按失败所在阶段处理：

- **待审阅 `review_pending`：** 查看原尺寸及对照，补真实结论；不消耗生成次数。
- **布局失败 `layout_repair_needed`：** 修正文字、模板或保护区，再排版；没有改变构图时不重生底图。
- **导出失败 `export_repair_needed`：** 修复尺寸或元数据导出；复用底图与布局。
- **模型质量失败 `generation_repair_needed`：** 新版先 `plan`，编译器依据当前绑定 qa_report 派生 `job.prompt_edit={target_path,failures}`，冻结失败raw为编辑目标并纳入实际提示和附件指纹；该字段不是产品事实证据。只发送新编译的绑定提示，修复旁文件不能直接替代；local 路线再排版，native 路线重新核对实际文字。改用新构图或重新创建生成计划时显式清除旧prompt_edit。每图默认最多一次质量修复，重复失败则阻断并补资料或交由人工修图。
- **网络／工具瞬时失败：** 同一提示指纹最多重试两次；修改提示后不能冒充同一次重试。

来源审阅、生成、排版、导出与QA指纹分别绑定实际依赖。local文案、字体或允许范围内的设计修正只重排并重审该图；局部浅浮雕的文案、字号、区域、素材、遮罩、承载面或受光变化只更新相关效果/布局和审核，不重生未变的商品底图。native文案或旧3D嵌字变化只修订该模型海报；构图／留白变化仅影响依赖它的底图，元数据变化只重新导出核验。未变任务不调用模型、不启动渲染器、不重建审核素材。

新 init 使用 `review_rule_profile=scoped_v1`，按真实视觉／审核代码计算规则摘要，日志、CLI、调度和清理函数不再连带使观察失效。视觉阈值、实现、来源、坐标、文字或最终字节改变仍须相应复核；旧项目保持 legacy 完整源码哈希，不自动升级或修改旧审核记录。

重处理命令采用“短锁读取快照 → 独立暂存区锁外处理 → 校验目标与共享依赖后短锁提交”。单图快照保留全项目校验必需输入、共享报告和本图产物，包括历史目录中声明的真实依赖；省去其他图的无关 raw／final／缓存，副本独立，冲突拒绝，恢复先处理事务日志。提交只合并目标任务及有效产物，不用旧 Manifest 覆盖其他任务；图片编码、字体准备、排版与对照不持有整个执行期写锁。

同次来源评估按源图复用一次解码／方向校正／RGB 转换，供产品、目标画布与细节裁图使用，随后释放。细节裁图先校验来源、坐标、算法版本与缓存内容，命中不解码。内容摘要及只读资源仅在本次操作内复用，写入、文件变化、提交边界重新核验，不依赖跨命令时间戳缓存。字体、许可证、缺字与内容哈希检查保留，不引入常驻服务。

不要伪造哈希或仅修改 `status` 复用旧验收。性能报告分别记录参考／规划、就绪等待、工具墙钟、交接、锁等待、编码、字体、渲染、审核准备／等待、导出与打包；批级共享开销只记一次，不把累计时间重复当作逐图成本，也不相加重叠区间。交接为 `tool_returned → ingested`。历史 generation/review 生命周期保留原义，缺少真实事件的指标标记待验证。真实交接 p95 目标 ≤30 秒、无阻断派发空档 p95 目标 ≤10 秒，必须用足够实际生产样本验证，不承诺模型耗时固定。

## 交付门槛

```bash
python3 <skill-root>/scripts/lc_image_pipeline.py finalize --manifest <manifest> --json
python3 <skill-root>/scripts/lc_image_pipeline.py deliver --manifest <manifest> --json
```

交付前完整 finalize 刷新或复用总览及对照；deliver 核验当前来源、生成／排版依赖、成品哈希、审阅及元数据并准备平铺目录。它不执行缓存清理，不例行再加一次 delivery-check；后者只用于针对性交付诊断。任何必需图未通过都不能声明整套完成。

`deliver --json` 返回 `output_dir`、`images`（job_id、filename、path、sha256）和 `image_count`，清单来自当前 QA 任务，不扫描目录猜成品。新项目主图、副图、A+ 按原有序名称平铺于 `final/`，其中仅已通过 QA 的最终 JPG；最终回复链接 output_dir。Manifest、报告、底图与审核记录留在项目目录，总览／预览不作成品交付，不生成 ZIP 或 HTML。

旧项目仅在显式 deliver 时把分散的已审图片汇集到 `delivery/images-vNNN/`；额外文件或历史版本存在时也创建新版本，不覆盖原图与历史文件。没有 compact_jpg 的旧 PNG/JPEG 编码不改变；无变化重复交付逐文件验哈希后复用，不重编码、不重复复制。Listing 与选定尺寸、A+ 与请求模块仍须一致。


### 按需缓存清理

`compact --manifest <manifest> --json` 是交付后或明确需要时单独运行的生产操作，不是最终答复的前置步骤。仅在全套有效 QA 后保存证据，保留当前生成输入闭包（含 prompt_edit 目标）、采用素材、遮罩、实拍与真实审核记录；只隔离暂存已登记的未引用自有缓存／旧候选，核验成功后清除。失败回滚文件及原绑定；崩溃恢复由后续正常写命令的既有锁／事务入口处理，status 不恢复。不得以清理失败为由重生或重写审核哈希。

### 输出与诊断体积

命令使用 `--json`，stdout 为一个紧凑对象（含 ok、command、manifest 和必要动作／路径），日志到 stderr；完整审计按需 `--detail` 或读取具体报告。模型返回对象禁止直接 text／JSON 序列化，Base64 和 data:image 不进入文字日志；原生图像交给 generatedImage／image。批审核部分失败返回非零退出码及逐图 errors，成功任务保留。

V6 字段、例外及预算见 [设计与性能契约](v5-design-and-performance.md#v6-默认契约与紧凑交付)。缺少契约的旧项目不自动启用；维护过程中也不自动迁移或清理现有生产目录。
