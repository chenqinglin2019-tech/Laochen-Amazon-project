# 模板库、入库与自动选择（V7）

适用：用户提供参考套图、选择或指定套系、管理模板库。命令在 skill 根目录执行，`P` 为 `verify` 返回的 Python；三个脚本都可在子命令前加 `--library-dir D` 临时指定库目录。

## 1. 用户库位置

- 优先级：`--library-dir` > 环境变量 `LC_TEMPLATE_LIBRARY_DIR` > 默认目录。
  - 默认目录：macOS/Linux 为 `~/.lc-amazon-image-studio/library`；Windows 为 `%LOCALAPPDATA%\lc-amazon-image-studio\library`。
- 库在 skill 目录之外，覆盖升级 skill 不会冲掉用户模板。旧版 skill 内的 `assets/layouts/design_templates.user.json` 首次使用时自动迁入（`migrate` 可手动执行），原文件不动。
- 目录内容：`settings.json`（内置库开关）、`user_templates.json`（v2 套系/模板/来源）、`user_templates_v1.json`（迁入的旧记录）、`asset_index.json`、`assets/<aa>/<sha>.<ext>`（原图/底板/缩略图，按内容寻址）、`intake/`、`backups/`。
- 项目采用模板后不再读库（快照和底板已复制进项目），清空或修改库不影响已有项目。

## 2. 库管理 `scripts/lc_template_library.py`

| 命令 | 作用 | 备份 |
|---|---|---|
| `status` | 库目录、内置是否启用、各类数量、资产字节、备份数 | — |
| `list [--source all\|user\|builtin]` | 只列 ID/名称/品类/图位覆盖/一句话摘要（不输出整库） | — |
| `builtin --enable\|--disable` | 启用/停用内置 v1 库（只写 settings，不删文件） | — |
| `clear --builtin\|--user\|--all [--reason]` | `--user` 清空用户记录与资产；`--builtin` 等同停用内置库 | `--user`/`--all` 先完整备份 |
| `restore --backup <名>\|--latest [--no-settings]` / `restore --builtin` | 从备份恢复（恢复前再备份当前状态）/ 重新启用内置库 | 自动安全备份 |
| `backups` | 列出备份名 | — |
| `export --output x.zip [--no-originals]` | 导出库，含哈希清单 | — |
| `import --archive x.zip [--mode merge\|replace]` | 导入；只接受白名单文件名，逐文件核对哈希，拒绝路径穿越 | — |
| `migrate` | 迁入 skill 内旧用户文件 | — |
| `gc [--apply]` | 列出/删除无引用资产（默认只演练） | — |

**一键清空全部模板**：`P scripts/lc_template_library.py clear --all --reason "用户要求"`。
- 恢复用户库：`restore --latest`。
- 恢复内置库：`builtin --enable`。
- 两个库都清空后，新项目的规划不会阻断：没有套系时，由 agent 为该图撰写原创 `design_brief`。

## 3. 入库：从参考套图生成用户模板 `scripts/lc_template_intake.py`

1. `P scripts/lc_template_intake.py prepare --images <文件或目录…> [--set-name "Warm Kitchen"]`：每次调用处理一套。
   - 只接受 PNG/JPEG/WebP，拒绝符号链接。
   - 计算 sha 并与库去重（`duplicate_of`、相似图 `similar_to`），识别画幅（square/portrait/wide），提取调色板并猜测颜色角色；四角近白的图提示为 `main`。
   - 生成一张带编号、10% 刻度的 `contact_sheet.jpg`，以及包骨架 `intake/<id>/packet.json`：确定性字段已预填，观察字段为 null，可选枚举写在 `vocabulary` 里。
2. **实际看联系表**（必要时看单图），用英文填写每张 `include=true` 的图：
   - `slot_role`、`recipe`（主图填 `none`）、`observation`。
   - `product_bbox_norm`：商品框，占画面 1–98%。
   - `text_boxes_norm`、`logo_boxes_norm`：必须覆盖**全部**可见文字和 Logo，底板靠它们去除；每框不超过半张图。
   - `layout.product_region_norm` 和 `layout.text_groups[]`：
     - 基本字段：`id`、`role`（eyebrow/headline/body/label/feature/badge）、`box`（在 2% 安全边内，不压商品区）、`align`、`font_role`、`size`（360 px 预览字号 12–64）、`color_role`。
     - 可选风格字段：`case`（none/uppercase）、`letter_spacing_em`（-0.05–0.3）、`line_height`（0.9–2）、`surface{kind,color_role,opacity,radius_em,border_color_role,border_width_px,shadow}`、`pill{color_role,text_color_role}`（标签胶囊）、`divider{color_role,width_px 1–6,length_em 0–20}`。
     - **只记结构，不记样张文字。**
   - `generation`：background、props、surface、lighting、color_grade、camera、depth_of_field、product_placement、product_scale、shadow、negative_space、mood，至少填一项。
   - `family`：
     - `name`、`description`。
     - `product_profile`：`categories` 和 `attributes`，词表见 `P scripts/lc_template_select.py taxonomy`。
     - `tokens.palette`：background/surface/ink/muted/accent/accent_text → `#RRGGBB`。
     - `tokens.fonts`：display/text/label → `face` 取自 `font_faces`（noto_sans、noto_serif、montserrat、poppins、oswald、bebas_neue、nunito、libre_baskerville、pacifico），可带 weight/case/letter_spacing_em。
     - `photography`、`avoid`。
   - 最后设置 `review.visual_reviewed=true` 并写 notes。
   - 色值用取色命令，不要目测：`P scripts/lc_template_intake.py sample-colors --packet <p> --image N --box x,y,w,h`。
3. `P scripts/lc_template_intake.py submit --packet <p> [--manifest <项目manifest>] [--product-mode flatten|blur] [--dry-run]`：
   - 校验通过后生成风格底板和缩略图，编译为套系 `<slug>-<6hex>`，模板 ID 为 `<套系>-<slot>`。
   - 库锁下按语义哈希去重、原子合并；同一套图重交复用已有套系。
   - 带 `--manifest` 时，套系写入项目的 `design_template_policy.prefer_family_ids`；若项目尚未开始生成且只有这一个优先套系，还会自动钉选为 `design_template_set_id`。这就是“本轮用户参考优先”。
4. 正式生产后，如需按审核意见微调：`revise --manifest M --template <id> --patch patch.json`。
   - patch 只能改 generation/layout/tokens，生成新 revision。
   - **每个项目只能调整一次**。已采用该模板的图要重新选择才会使用新版本，会导致重生。

**风格底板**（style plate）：参考图的中性化版本。
- 处理方式：
  - 文字框和 Logo 框外扩 12%，用周边颜色填充后模糊。
  - 商品框外扩 6%，默认用周边插值抹平（`--product-mode blur` 改为强模糊）。
- 边缘能量闸门：文字/Logo 区 >0.2、商品区 >0.25 时拒绝，报错提示扩大对应框后重交。
- 用途：随生图附带，只学背景、道具、光线、调色、机位、构图和留白。

## 4. 自动选择 `scripts/lc_template_select.py`

`P scripts/lc_template_select.py recommend --manifest M [--top 3] [--apply]` 输出前几名的分项得分和逐图覆盖；`--apply` 把第一名写入 `design_template_set_id`。

- **画像**：优先读 manifest 的 `product_profile`（`category`、`secondary_categories`、`attributes`）；缺失时从产品文字推断，并提示补填。
- **打分**：
  - 品类：完全匹配 40；次品类命中或同大类 20。
  - 属性：material 8、style_mood 8、color_tone 6、use_environment 6、audience 4、size_class 4、price_tier 4；有序属性相邻得一半。
  - 覆盖：每张 observed 图 +2，adapted/cross_family 图 +1。
  - 优先套系：+100（`prefer_family_ids`）。
- **资格**：品类不符的套系只有在属于优先套系、或属性分达到属性满分一半时才参选。同分时用户套系排在内置之前。
- **逐图降级链**（永不 needs_input）：
  1. 本套系、同 slot、同画幅（observed）；
  2. 本套系、同 slot、异画幅（adapted）；
  3. 本套系近似 slot（adapted，见 `slot_similarity`）；
  4. 其他用户套系同 slot，换用本套系的配色和字体（cross_family，主图不用）；
  5. 由套系令牌生成原创 brief（original）。
- **主图**：只接受 observed/adapted 模板，且只取机位、摆放、占比、阴影；不带文字、道具和底板，白底 255 规则不变。
- 内置 v1 套系映射到同一词表参与打分；选中后走冻结的 v1 路线（无底板）。

## 5. plan 时如何采用（`lc_template_workflow_v2.py`，policy version 2）

- **钉选**：未显式指定时，把选中套系写入 `design_template_set_id`/`_revision`，以后回放快照、不再重选。钉选的套系从库里消失后，照常回放已采用快照，**不会**改选内置或其他套系。
- **资产**：底板复制到 `design/plates/<sha>.jpg`，参考缩略图复制到 `design/references/<sha>.jpg`，用 sha 绑定。
  - 底板仅附给 observed/adapted 的非主图，排在商品参考之后。
  - 底板不进入 `manifest.references`，因此不参与商品清晰度审核和编辑目标选择；它的字节进入生成指纹。
- **去掉通用脚手架**：init 预填的 scene/composition/lighting 只要仍与脚手架原文相同就删除，让模板参数进入提示；agent 改写过的值保留且优先。
- **令牌预填**（带 ledger）：
  - `style_contract` 中空的颜色/字体角色用套系令牌填写（headline←ink，body←muted，label/accent/graphic←accent）；显式值不覆盖。新项目因此不会再遇到 `DESIGN_COLOR_REQUIRED`。
  - `layout.text_groups` 中缺的 box（仅 observed，且非首组）、align、text_color、mobile_sizes、surface 按骨架补齐。
  - 观察到的风格字段转成 `style` 并设 `layout.renderer="style_v1"`（字体、分色、大小写、字距、胶囊、分隔线、圆角/描边/阴影卡片）。
  - 批准文案只在 layout 一处，工具从不写入。
- **失效与回放**：`design_resolution.schema_version=2` 记录 match、slot_role、binding 快照、assets、brief_hash 和选择理由。编译器是确定性的，库被清空后 plan 结果逐字不变。
  - 快照或 brief 被改动时报 `design_template_brief_changed_run_prepare`。
  - 用 `design_overrides` 做逐图的显式调整。

## 6. 防抄袭与真实性

- 只借设计（版式、配色、字体、光线、机位、构图），不抄参考里的商品、品牌、Logo、样张文案、主张、包装或配件数量；底板的模糊/抹平区是空占位。
- 商品外观只服从本项目证据和四项锁，冲突时以证据为准。
- 审核总图并排显示参考缩略图；`visual_design` 备注按版式/配色/字体/光线逐项写 close/partial/off。

## 7. 兼容

- 旧项目（policy version 1 或无 policy）走原 v1 规则，提示字节和指纹不变，详见 [legacy.md](legacy.md)。
- 内置库仍为 v1 纯文本模板（`assets/layouts/design_templates.json`），默认启用。停用、文件缺失或为空时都按空库处理，不报错。
