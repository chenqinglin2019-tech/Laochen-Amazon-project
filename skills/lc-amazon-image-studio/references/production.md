# 生产规则（V8.1，规划图位、文案、场景时读）

硬规则与循环上限见 SKILL.md §3–§4，此处不重复；字段见 [fields.md](fields.md)。

## 图位策略

默认 7 张。顺序可以换；不要用没有依据的尺寸、空泛特写或假的前后对比来凑数。

| 图位 | 核心结论 |
|---|---|
| `01_main` | 纯白底上的实际商品及包含物，没有文字（SKILL §3 主图规则） |
| `02_size_or_components` | 已确认的尺寸或套装内容 |
| `03_primary_use_case` | 最有价值的真实使用任务 |
| `04_compatibility_or_installation` | 适配、连接、安装或操作逻辑 |
| `05_material_or_detail` | 有清晰实拍依据的材质、工艺、结构 |
| `06_storage_or_package` | 收纳、携带、包装或完整包含物 |
| `07_problem_solution` | 解决一个真实的购买顾虑 |

- **用户计划优先**：用户给了任何图位意图就照用，只补齐空缺；没有时参考竞品的信息顺序和目的，不抄画面和主张。
- **A+**：`init --a-plus-modules name[:WxH],...`，模块名取 header / feature / detail / lifestyle / comparison / story，默认 970×600。每个模块单独构图，不把方图压扁成横幅。
- **每张图只讲一件事**：一个核心结论、一个视觉焦点。场景要讲清用法；支撑、接触、遮挡要符合物理常识。
- **产品检查**（不加审批轮次）：买家是谁、要完成什么任务、在什么环境、最大的顾虑是什么；哪些规格已确认；哪些面没有照片。缺某张图的资料只影响那张图（先 `skip` 或换图位），产品身份不明才暂停整套。

## 品类侧重

跨品类时按买家的主要购买顾虑归类（如厨房抽屉用的理线器归收纳，狗狗车载安全绳归宠物）。

| 品类 | 买家关心 → 重点图位 | 场景 / 避免 |
|---|---|---|
| 工具/五金 | 适配、耐用、安装、套件完整 → 组件、安装、材质、问题解决 | 安装、拧紧、干活中 / 奢华生活方式 |
| 家居/收纳/厨房 | 放哪、容量、省空间 → 使用、收纳、问题解决、尺寸 | 真实台面、橱柜、抽屉 / 讲不清功能的客厅大片 |
| 美妆个护 | 舒适、卫生、质地、用法 → 使用、材质、包装 | 干净的个护环境 / 夸大或医疗化主张 |
| 宠物 | 尺码、安全、好用、易洗 → 使用、尺码、材质 | 真实宠物行为 / 不可能的姿势、不安全用法 |
| 汽车/骑行 | 兼容、安装位置、耐用 → 安装、材质、尺寸 | 装在对应车辆上 / 安装逻辑含糊、商品太小 |
| 电子/桌面 | 接口、兼容、线缆逻辑 → 使用、兼容、细节 | 桌面、充电、出行 / 遮住产品的霓虹科技风 |

## 写好 plan.json（一次成图的质量取决于它）

- **product.look**（英文）：具体写形状、颜色、材质和有辨识度的部件，例如 "Rounded rectangular box in matte navy plastic with a yellow front band and two side handles"。不写营销词。
- **product.keep**：必须出现且正确的细节，最多 4 条（如印刷的刻度、按钮位置）。生图模型最容易画错的就是这些。
- **product.scale**：真实尺寸或相对参照（"About 30 cm tall, fits on a desk"），让场景比例可信。
- **product.facts**：用户资料里确认的事实原文，数字带单位（"30 x 20 x 10 cm"、"3 compartments"）。文案里的数字只能来自这里。
- **photos**（每图可选，最多 4 张）：整体照放第一张；细节图位加细节照。默认自动选整体照。
- **message**：这张图要让买家明白的一句话。**scene**：环境、支撑面、少量道具，为这件产品原创（用了用户模板时必填）。**direction**（可选，≤300 字符）：额外的美术指示，例如 "top-down view, morning light"。
- **copy**：短而具体。标题讲一个好处，标注给证据。模型写长句容易拼错，所以宁短勿长，用常见词，数字与 facts 一字不差。
- **people**：`false`（默认，画面无人）、`"hands"`（只露手）、`"person"` 或 `true`（真实感人物）。出现真实感人物会写入 AI 披露关键字；`"person"` 需要 `cast`（见下文"模特与场景"）。
- **模板与 custom**：选模板时，提示里会写入它的版式位置、配色、字体风格和画面参数；`custom` 时你的 `design.layout` 决定一切，要写清产品和每块文字的位置，例如 "product right two thirds, headline top left, three callouts stacked bottom left"。

## 模特与场景（绝不照抄参考）

- **参考图先分析**：看参考联系表（`refs_sheet`，用户模板看 `contact_sheet`），判断它对这件产品、这张图有没有参考价值：
  - 适合：画质专业，配色和光线与产品颜色、目标氛围相配 → 在需要的图位写 `tone_ref`，只借色调与光线（模型拿到的是强模糊的色调光线板，人和物都看不出来）。
  - 不适合：画质差、配色和产品冲突、主体只是人物或别人的场景、风格与用户要的不同 → 不写 `tone_ref`，选内置模板或 custom 自主设计。
- **场景原创**：`scene` 为这件产品重新构思（环境、支撑面、道具、机位），不复述参考图里的房间、家具和摆设；用户模板只提供版式、字体、配色和光线感觉。
- **新模特（`cast`）**：用英文写一位具体的新人物——年龄段、发型发色、肤色、体型、穿着风格，例如 "Man in his 40s, short salt-and-pepper hair, light olive skin, athletic build, navy overshirt"。
  - 要和参考图里的人明显不同（看联系表对照），也不得写"像某某""like the reference"之类的话。
  - 符合目标买家：站点和品类的主要人群；面向日本站的家居产品可选东亚面孔等。
  - 换新项目重新写一位，不沿用上个项目的描述。
- **整套同一个人**：第一张带模特的图（或 `cast_anchor`）先生成，登记后成为本套的长相参考，其余带模特的图自动带上它；普通 `--redo` 不换人。
- **换模特**：定下模特的那张图里，人像参考图里的人、像名人，或与 `cast` 明显不符时，用 `--recast <job> "<问题>"`。已完成的旧模特图会列在 `made_with_previous_model`，交付时出现在 `model_mismatch`，要不要重做先问用户。
- **产品照片里有人**：比如模特上身展示的服装、手拿的包。在 `hide` 里框出脸和人物（不要框住产品），模型只看到遮挡后的照片，并被要求忽略照片里的人和场景；这类照片不会被用来本地合成主图。
- **只露手**（`"hands"`）不需要 `cast`；写了 `cast` 时，手会与本套模特一致。

## 文案档位

| 档位 | 适用画布 | 上限（拉丁文字） |
|---|---|---|
| standard | Listing 方图/竖图、A+ 970×600、300×300 | eyebrow ≤3 词；headline ≤6 词/42 字符；subline ≤12 词；callouts ≤4 条×≤4 词；全图 ≤30 词 |
| wide | A+ 1464×600、1464×625、350×175 | headline ≤5 词；subline ≤8 词；callouts ≤3 条×≤3 词；全图 ≤18 词 |
| narrow | A+ 970×300 | 只放 headline，≤4 词 |

- 中文、日文、韩文按字符：standard 档 headline ≤12、subline ≤24、callouts ≤4 条×≤8；wide 和 narrow 更严。
- **数字**：文案中的每个数字都必须出现在 `product.facts` 里。
- **一律禁止**：价格和货币符号、sale/discount/deal/coupon、best seller、#1/No. 1、top rated、Amazon's Choice、money-back、cheapest。
- **有依据才能写**：guarantee/warranty、FDA/CE/UL/FCC 等认证、certified/approved、patented、organic、BPA-free、non-toxic、eco-friendly、waterproof/water-resistant、dishwasher-safe、100%、antibacterial 等，必须在 facts 里写明。
- 文案用站点语言（文字系统要匹配）；主图不放文字。

## 画幅与保留带

生图模型只出 1:1、3:2、2:3 三种画幅。画布比例不同时，提示会说明保留哪一条带，产品、全部文字和图形都必须在带内；带外只能是延伸的背景。

| 画布 | 生图画幅 | 保留带 |
|---|---|---|
| 2000×2000 | 1:1（1024×1024） | 整幅 |
| 2000×2600 | 2:3（1024×1536） | y 6.7–93.3% |
| 970×600 | 3:2（1536×1024） | y 3.6–96.4% |
| 1464×600 | 3:2 | y 19.3–80.7% |
| 970×300 | 3:2 | y 26.8–73.2% |

- 入库时按内容找损失最小的位置裁出保留带，再缩放到画布。
- 带外仍有较多文字或产品（`FRAME_CONTENT_CUT`）时自动重生 1 次；仍不行就保留最好的裁法并标记 `frame_cut_risk`，交付时告诉用户这张图边缘可能裁到内容。

## 主图

- **实拍图路线**（`route: auto` 时优先）：任何纯色背景都可以（白、灰、浅色无纹理），产品完整、不贴边，放大不超过 1.75 倍。`init` 返回的 `main_candidate` 就是合格的那张；`plan` 当场合成，不花生图次数。
- **生成路线**：工具按产品颜色挑选最容易干净抠图的背景（通常白色；白色或浅色产品用灰色 #C8C8C8 / #8C8C8C），提示要求纯平背景、无阴影、无倒影、无文字、产品完整居中。返回后本地抠图、贴到纯白画布、居中到 85%。
- **自动重生**（主图 2 次，附针对性更正）：背景不平（`MAIN_BACKGROUND_NOT_PLAIN`）、有阴影或倒影（`MAIN_SHADOW_AMBIGUOUS`）、产品被切（`MAIN_PRODUCT_CROPPED`）、产品太小（`MAIN_PRODUCT_TOO_SMALL`）、找不到产品（`MAIN_NO_PRODUCT`）、抠图不完整（`MAIN_CUTOUT_INCOMPLETE`，同时换一种背景色）。
- **校验**：最终 JPEG 解码后，不碰产品的每个 8×8 块必须全是 (255,255,255)，四边全白，产品长边占 85%±1.2%，居中误差 ≤1%。q95 不过就 q100，再不过就交无损 PNG。
- **透明/玻璃产品**：在 `product` 里写 `"transparent": true`（总用白背景），尽量提供实拍图；透过玻璃看到的背景阴影是唯一已知的残余风险。
- 主图失败（额度用尽）时如实告诉用户："主图无法自动得到干净纯白底：请提供白底或纯色背景的实拍图，或换角度后重试"。

## 失败状态 → 动作

| 返回 | 动作 |
|---|---|
| `plan` 返回 `errors` | 按 JSON 路径改 plan.json，再跑一次 `plan`；不要逐条来回问用户 |
| `FAMILY_MIX`（警告） | 有意混用可忽略；否则换成同一套系的模板 |
| `changed_done` | 已完成的图提示变了但被保留；确需重做时 `plan --regenerate <job>` |
| `retry_after_seconds` | 等够秒数后 `reserve --project D` |
| `TRANSIENT_RETRY_LIMIT_REACHED` / 状态 `failed` | 汇总给用户；同意后 `reset … --user-confirmed` |
| `REDO_LIMIT_REACHED` | 已重生过；小问题直接交付，大问题问用户是否 `--user-confirmed` 再重生 |
| `WAITING_FOR_MODEL`（预约拒绝） | 正常：等第一张带模特的图定下模特；登记它之后自动排进下一波 |
| `model_mismatch`（交付时） | 这些图是之前的模特；告诉用户，同意后再 `--redo` |
| `PLAN_OUTDATED`（预约拒绝） | 升级前规划的图：重新运行 `plan` |
| `MAIN_PHOTO_INELIGIBLE` | 改 `route: auto/generate`，或请用户给纯色背景实拍图 |
| `deliver` 返回 `missing` | 补完这些图，或在 plan.json 把它们改成 `skip` 后重跑 `plan`；用户同意时 `deliver --partial` |

## AI 图片规则

最近核对：2026-09-05。站点、类目或渠道规则变化时，重新读官方来源并记录版本。

- **平台要求**：含逼真 AI 人物（含只露手、半身）的 Listing/A+ 图片须在 XMP `dc:subject` 写 `contains-synthetic-performer`（[Amazon 公告](https://sellercentral.amazon.com/seller-forums/discussions/t/aa0aee06-aff4-497a-a4b6-9b2ebe06f715)）。无人、非逼真人物、仅真人（即使经 AI 修改）不适用；生成的背景或商品不算。广告素材另按 [Amazon Ads 指南](https://advertising.amazon.co.uk/help/GZZX6RJVMWBVBB6W) 核对。
- **本 skill 的做法**：plan 里每图的 `people` 决定是否写关键字（`false` 不写，其它值都写）。导出时写入 XMP 并回读核对；看图时发现与声明不符，用 `ingest-batch --people <job> yes|no` 改正，工具用同一像素重新导出，不重生。
- 主图不放人物、不加水印。本地嵌入元数据不等于平台审核通过。
