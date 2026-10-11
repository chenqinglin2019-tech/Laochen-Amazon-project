# 模板库、参考套图入库与选模板（V8.1）

适用：用户提供参考套图、选择或指定套系、管理模板库。只在本项目参考一下的图不用入库，用 `init --refs` / `add-refs` 登记即可（见第 4 节）。命令在 skill 根目录执行，`P` 为 `verify` 返回的 Python；库脚本都可在子命令前加 `--library-dir D` 临时指定库目录。

## 1. 用户库位置

- 优先级：`--library-dir` > 环境变量 `LC_TEMPLATE_LIBRARY_DIR` > 默认目录。
  - 默认目录：macOS/Linux 为 `~/.lc-amazon-image-studio/library`；Windows 为 `%LOCALAPPDATA%\lc-amazon-image-studio\library`。
- 库在 skill 目录之外，覆盖升级 skill 不会冲掉用户模板；V7 和 V8 共用同一个库，不需要迁移。
- 目录内容：`settings.json`（内置库开关）、`user_templates.json`（套系/模板/来源）、`asset_index.json`、`assets/<aa>/<sha>.<ext>`（原图、风格底板、缩略图，按内容寻址）、`intake/`、`backups/`。
- 风格底板只留在库里，从不原样交给生图模型；`plan` 只在图位写了 `tone_ref` 时，把它缩成强模糊的色调光线板放进项目（`design/tones/`）。之后清空或修改库不影响已经编译好的提示。

## 2. 库管理 `scripts/lc_template_library.py`

| 命令 | 作用 | 备份 |
|---|---|---|
| `status` | 库目录、内置是否启用、各类数量、资产字节、备份数 | — |
| `list [--source all\|user\|builtin]` | 只列 ID/名称/品类/图位覆盖/一句话摘要 | — |
| `builtin --enable\|--disable` | 启用/停用内置模板库（只写 settings，不删文件） | — |
| `clear --builtin\|--user\|--all [--reason]` | `--user` 清空用户记录与资产；`--builtin` 等同停用内置库 | `--user`/`--all` 先完整备份 |
| `restore --backup <名>\|--latest [--no-settings]` / `restore --builtin` | 从备份恢复（恢复前再备份当前状态）/ 重新启用内置库 | 自动安全备份 |
| `backups` | 列出备份名 | — |
| `export --output x.zip [--no-originals]` | 导出库，含哈希清单 | — |
| `import --archive x.zip [--mode merge\|replace]` | 导入；只接受白名单文件名，逐文件核对哈希，拒绝路径穿越 | — |
| `migrate` | 迁入很早期版本放在 skill 内的用户文件 | — |
| `gc [--apply]` | 列出/删除无引用资产（默认只演练） | — |

- **一键清空全部模板**：`P scripts/lc_template_library.py clear --all --reason "用户要求"`。恢复用户库用 `restore --latest`，恢复内置库用 `builtin --enable`。
- 两个库都为空时目录会提示，每个图位都写 `"template": "custom"` 自己策划，生产不受阻。

## 3. 入库：从参考套图生成用户模板 `scripts/lc_template_intake.py`

1. `P scripts/lc_template_intake.py prepare --images <文件或目录…> [--set-name "Warm Kitchen"]`：每次调用处理一套。
   - 只接受 PNG/JPEG/WebP，拒绝符号链接。
   - 计算 sha 并与库去重（`duplicate_of`、相似图 `similar_to`），识别画幅（square/portrait/wide），提取调色板并猜测颜色角色；四角近白的图提示为 `main`。
   - 生成一张带编号、10% 刻度的 `contact_sheet.jpg` 和包骨架 `intake/<id>/packet.json`：确定性字段已预填，观察字段为 null，所有可选枚举写在包的 `vocabulary` 里。
2. **实际看联系表**（必要时看单图），用英文填写每张 `include=true` 的图：
   - `slot_role`、`recipe`（主图填 `none`）、`observation`（只供入库校验，永远不进提示）。
   - `product_bbox_norm`：商品框，占画面 1–98%。
   - `text_boxes_norm`、`logo_boxes_norm`：必须覆盖**全部**可见文字和 Logo，风格底板靠它们抹掉；每框不超过半张图。
   - `person_boxes_norm`：框出**每一个**人物、人脸、手或身体部位，入库时从底板里抹平，任何人都不会被复制。
   - `layout.product_region_norm` 和 `layout.text_groups[]`：
     - 基本字段：`id`（唯一、小写）、`role`（eyebrow/headline/body/label/feature/badge）、`box`（在 2% 安全边内，不压商品区）、`align`、`font_role`、`size`（按 360 px 宽预览的字号，12–64）、`color_role`。
     - 可选风格字段：`case`（none/uppercase）、`letter_spacing_em`（-0.05–0.3）、`line_height`（0.9–2）、`surface{kind,color_role,opacity,radius_em,border_color_role,border_width_px,shadow}`、`pill{color_role,text_color_role}`（标签胶囊）、`divider{color_role,width_px 1–6,length_em 0–20}`。
     - **只记结构，不记样张文字。**
   - `generation`：background、props、surface、lighting、color_grade、camera、depth_of_field、product_placement、product_scale、shadow、negative_space、mood，至少填一项。
     - 写风格层面的描述（"bright kitchen, pale stone surface, soft window light"），不要逐件清点别人的布景。
     - 人物只按角色、取景和姿势描述（"adult model, waist-up, holding the product"）。
     - **不写长相**：发型发色、肤色、年龄、族裔、体型、纹身等出现在人物描述里会被拒绝。
   - `family`：`name`、`description`；`product_profile` 的 `categories`/`attributes` 取自包里的 `vocabulary`；`tokens.palette`（background/surface/ink/muted/accent/accent_text → `#RRGGBB`，可加 `palette_names` 给颜色起名）；`tokens.fonts`（display/text/label → `face` 取自 `font_faces`，可带 weight/case/letter_spacing_em）；`photography`；`avoid`。
   - 最后设 `review.visual_reviewed=true` 并写 notes。
   - 色值用取色命令，不要目测：`P scripts/lc_template_intake.py sample-colors --packet <p> --image N --box x,y,w,h`。
3. `P scripts/lc_template_intake.py submit --packet <p> --project D [--product-mode flatten|blur] [--dry-run]`：
   - 校验通过后生成风格底板和缩略图，编译为套系 `<slug>-<6hex>`，模板 ID 为 `<套系>-<slot>`；校验问题一次列全。
   - 库锁下按语义哈希去重、原子合并；同一套图重交会复用已有套系。
   - 带 `--project` 时把这个套系记为本项目优先（目录里 `preferred: true`、排在最前），这就是"本轮用户参考优先"。
4. 出图后需要微调模板：`P scripts/lc_template_intake.py revise --project D --template <id> --patch patch.json`。
   - patch 只能改 generation / layout / tokens，生成新 revision；**每个项目只能调整一次**。
   - 之后重跑 `plan`：用到这个模板的未完成图会用新提示；已完成的图要 `--regenerate <job>` 才会重做（会花生图次数）。

**风格底板**（style plate）是参考图的中性化版本，只存在库里：
- 文字和 Logo 框外扩 12% 后用周边颜色填平并模糊；
- 商品框外扩 6%、人物框外扩 8% 后抹平（`--product-mode blur` 把商品改为强模糊）；
- 文字/Logo 区的边缘能量 >0.2、商品区或人物区 >0.25 时拒绝，提示扩大对应框后重交。

**色调光线板**（tone board）是交给生图模型的唯一形式：
- 对底板（或 `--refs` 参考图）的颜色和明暗做稳健的平滑拟合；
- 与周围不同的局部色块（人物、产品、道具、文字）被当作离群点剔除，人和物不会留下任何轮廓或色块；
- 最终只剩整体色调、明暗和光线方向；
- 主色另外以 hex 文字写进提示（"Main colours of that reference …"）；
- 旧模板也自动按这个方式处理，不用重新入库。

## 4. 读模板目录、选模板

`init` 和 `templates --project D` 返回同一份紧凑目录（约 15 KB）：

- `families[]`：
  - 用户套系：`source: "user"`、`code`（U1、U2…，与联系表上的编号对应）、`preferred`、`for`（适用品类）、`palette`（hex）、`fonts`、`photography`，`templates[]` 每行有 `slot`、`shape`、`recipe`、`text`（文字组角色）、`layout`（文字和产品的位置）、`tile`（联系表格子）、`tone`（能否用 `tone_ref` 借色调光线）。
  - 内置套系：`source: "builtin"`、`for`、`look`、`type`，`templates[]` 每行有 `fits`（适合的图意）、`recipe`、`layout`、`text`（能放多少文字）。
- `slots[]`：每个图位的 `purpose`、`canvas`、生图 `frame`、`keep_band`（非整幅时）和文案档位 `budget`。
- `copy_rules`：文案规则摘要。`contact_sheet`：有用户模板时的缩略图联系表，**只给 Agent 看**，不传给生图模型。
- `refs` / `refs_sheet`：本项目登记的参考图 id 和联系表（`init --refs` 或 `add-refs --project D --refs …`），同样只给 Agent 看。
- 需要某个套系的完整记录时：`templates --project D --family <id>`。观察记录已去掉；用户模板的 background/props/surface 也已去掉，因为那是别人的场景。

**怎么选**：
1. 整套只选一个 family，保持风格统一；有 `preferred: true` 且适合这件产品的优先用它。
2. 每个副图位按这张图要讲的事选模板：`fits`/`slot` 与图意匹配，`text` 能装下你的文案，`layout` 与想要的构图一致。
3. 没有合适的就 `custom`：`design.layout` 写清产品和每块文字的位置，`design.style` 写场景和光线，`design.typography` 写字体风格。plan 顶层可写 `style` 作为整套 custom 图的统一风格。
4. 混用其它套系的模板时 `plan` 会给 `FAMILY_MIX` 警告，有意为之可以忽略。
5. **是否借色调光线**：逐图判断用户模板或参考图（`refN`）的配色和光线是否适合这件产品、这张图。适合才写 `tone_ref`；参考图本身没什么参考价值时不写，自主设计。场景（`scene`）永远自己写。

## 5. 模板怎样变成一次成图提示

- **内置模板**：用结构化字段编译，不用旧的提示原文：画布变体里的产品区和文字区换算到生图画幅（如 "Text block: upper-left area, x 6-46%, y 6-26%"），加上背景、光线、焦点、套系配色和摄影风格，以及标题/正文的字体风格、颜色和对齐。
- **用户模板**：
  - 写入配色 hex（带颜色名），以及光线、调色、机位、景深、氛围、留白和产品位置/比例；不写原图的背景、道具、台面，也不写任何人物描述。
  - 文案按顺序对应文字组（eyebrow/headline/subline/callouts），每条写明位置、对齐、字体风格、颜色和相对字号。
  - 场景用 plan.json 里 Agent 原创的 `scene`。
  - 写了 `tone_ref` 时，色调光线板作为产品照片之后的参考图，提示里写明"只取配色、明暗和光线方向，场景、物件和人物都要自己构思，画面必须清晰"。
- **custom**：直接使用 `design` 里的三段描述。
- `direction` 作为 "Art direction" 附加；文案永远逐字加引号写入，并要求每段只出现一次、不得有其它文字。

## 6. 防抄袭与真实性

- **只借色调、光线、版式和字体风格**：不复制参考图里的人物、场景、商品、品牌、文案、Logo、数字或主张。
- **交给生图模型的参考图**只有色调光线板，而且要 Agent 判断合适并写了 `tone_ref`；原图、底板、缩略图、联系表和观察记录都不进提示。plan.json 里也不能出现指向参考的文字（`COPY_WORDING`）。
- **模特每套新选**：`cast` 写一位与参考图里的人明显不同的新人物，整套同一人（见 production.md）。
- **产品身份**只来自用户的产品照片和 plan.json 里的事实；产品照片里的人和场景会被忽略，必要时用 `hide` 遮挡。
