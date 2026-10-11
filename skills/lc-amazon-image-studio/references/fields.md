# 字段、状态与错误码（V8.1）

## plan.json

项目文件夹里唯一由 Agent 编写的文件。`plan` 会校验全部字段，所有问题一次返回在 `errors[]`（`path` 为 JSON 路径，`code` 见下表）。

| 字段 | 说明 |
|---|---|
| `version` | 固定为 `1` |
| `family` | 整套使用的套系 id（目录里的 `families[].id`）；全部自定义时写 `"custom"` 或省略 |
| `style` | 可选，≤300 字符：整套 custom 图共用的风格说明 |
| `people` | 全套默认：`false`（默认）/ `"hands"` / `"person"` / `true` |
| `cast` | 有图位 `people` 为 `"person"` 或 `true` 时必填，英文，≤300 字符：新模特的年龄段、发型发色、肤色、体型、穿着风格；要和参考图里的人明显不同，不得写参考或真人名人 |
| `cast_anchor` | 可选：由哪个带模特的图位先定下模特（默认第一个） |
| `hide` | 可选：`{"<照片 id>": [[x, y, w, h], …]}`，每张照片最多 8 个框；框里的人脸、人物或无关品牌会被抹掉，模型只看到遮挡后的照片 |
| `product.name` | 必填，≤80 字符 |
| `product.look` | 必填，英文，≤500 字符：形状、颜色、材质、有辨识度的部件 |
| `product.scale` | 可选，≤240 字符：真实尺寸或相对参照 |
| `product.keep[]` | 必须可见且正确的细节，≤10 条，建议 ≤4 条 |
| `product.facts[]` | 已确认的事实原文，≤30 条；文案中的数字和认证类词语只能来自这里 |
| `product.transparent` | 玻璃等透明产品写 `true`：主图总用白背景生成 |
| `slots.<id>` | 每个图位都要出现；不用的写 `{"skip": true}` |

**主图 `slots.01_main`**：

| 字段 | 说明 |
|---|---|
| `route` | `auto`（默认：有合格实拍图就本地合成，否则生成）/ `photo`（必须用实拍图）/ `generate`（必须生成） |
| `photo` | 可选：指定用于本地合成的照片 id（默认用 `main_candidate`） |
| `photos` | 生成路线的参考照片 id（默认最多 3 张整体照，正面和 3/4 视角优先） |
| `view` | 可选：想要的角度（≤60 字符），默认与第一张参考照相同 |
| `backdrop` | 生成时的背景：`auto`（默认，按产品颜色挑选）/ `white` / `light_grey` / `mid_grey` |

主图不能有 `copy`（`MAIN_HAS_COPY`），也不能有 `tone_ref`。`scene`、`direction`、`style`、`design.*` 和 `cast` 里不得出现指向参考的说法（reference、template、competitor、"the reference image" 等，`COPY_WORDING`）。

**副图和 A+ `slots.<id>`**：

| 字段 | 说明 |
|---|---|
| `template` | 必填：目录里的模板 id，或 `"custom"` |
| `design` | `custom` 时使用：`layout`（必填）、`style`、`typography`，各 ≤300 字符 |
| `message` | 必填，≤160 字符：这张图要让买家明白的一句话 |
| `scene` | ≤300 字符：环境、支撑面、少量道具。内置模板可省略（用模板的通用场景）；**用户模板必填**，必须为本产品原创 |
| `direction` | 可选，≤300 字符：额外的美术指示 |
| `tone_ref` | 可选：借色调与光线的参考——`"template"`（所选用户模板）、某个用户模板 id，或项目参考图 id（`"ref1"`）。只在判断确实适合时写；模型拿到的是强模糊的色调光线板 |
| `copy` | `eyebrow`、`headline`、`subline`、`callouts[]`；上限见 [production.md](production.md#文案档位) |
| `photos` | 参考照片 id，最多 4 张；默认最多 3 张整体照 |
| `people` | 覆盖全套默认值 |

## project.json（工具维护，只读）

- `slots[]`：`id`、`kind`（main / secondary / a_plus）、`role`、`canvas`、`purpose`。
- `photos[]`：`id`（由文件名生成）、`path`、`view`、`role`（whole / detail）、`size`、`main`（主图合格性：`eligible`、`reasons`、`upscale`）。
- `refs[]`：项目参考图 `id`（ref1…）、`path`（`refs/`）、`sha256`、`size`。只会以色调光线板的形式进入提示。
- `cast`：本套模特——`text`、`members`（带模特的图位）、`anchor`、`epoch`、`identity`（定下模特的那张原图：`job`、`attempt`、`path`、`sha256`）、`history`。
- `jobs.<id>`：`status`、`route`（photo / generate）、`prompt_file`、`references`、`size`、`aspect`、`attempts[]`、`redos`、`transient_failures`、`final`、`final_sha256`、`warnings`、`check_suggested`、`failed_reason`。
- `plan`（采用的计划摘要）、`plan_snapshot`（重生提示用）、`preferred_families`、`network`（并发与限流状态）。
- 同目录还有：`prompts/`（每张图的提示原文，重生时为 `<job>.redo.txt`；模特参考那一行在预约时才加上）、`raw/`（生图原图）、`final/`（成品）、`design/tones/`（色调光线板）、`design/hidden/`（遮挡后的产品照片）、`refs/`（参考图原件，从不发给模型）、`catalog/`（联系表）、`delivery_report.json`。

## 状态

| 状态 | 含义 | 下一步 |
|---|---|---|
| `pending` | 等待预约（首发、重试或重生） | 下一波会预约它 |
| `generating` | 已预约，等待登记结果 | `ingest-batch` 登记；30 分钟未登记自动收回 |
| `done` | 成品已导出到 `final/` | 交付 |
| `failed` | 瞬时失败用尽、主图重生用尽或被 `--reject` | 汇总给用户；同意后 `reset … --user-confirmed` |
| `skipped` | plan.json 里 `skip` | 不交付 |

预约的 `kind`：`initial`（首发）、`retry`（瞬时失败后重试）、`redo`（带更正说明的重生）。带模特的预约另有 `cast`：`anchor`（这张图定下模特）或 `same_model`（附带本套模特图作为长相参考）。还没定下模特时，其余带模特的图出现在 `refusals`（`WAITING_FOR_MODEL`）和 `waiting_for_model` 里。

## 错误码

**plan.json 校验**（`plan` 返回的 `errors[].code`）：

| code | 含义 |
|---|---|
| `REQUIRED` / `TYPE` / `UNKNOWN_KEY` / `VERSION` | 缺字段、类型不对、未知字段、版本不是 1 |
| `SLOT_MISSING` / `UNKNOWN_SLOT` | 漏写图位 / 项目里没有这个图位 |
| `FAMILY_UNKNOWN` / `TEMPLATE_UNKNOWN` | 套系或模板 id 不在目录里 |
| `PHOTOS_REQUIRED` / `PHOTO_UNKNOWN` / `TOO_MANY` | 没有整体照 / 照片 id 不存在 / 参考照或标注过多 |
| `ROUTE` / `BACKDROP` / `PEOPLE` | 枚举值不对 |
| `MAIN_HAS_COPY` | 主图写了文案 |
| `TOO_LONG` / `TOO_MUCH_TEXT` / `NOT_ALLOWED_HERE` | 超出该画布的文案档位 |
| `NUMBER_UNBACKED` | 文案里的数字不在 facts 里 |
| `FORBIDDEN_WORDING` | 价格、折扣、排名、Amazon's Choice 等 |
| `CLAIM_UNBACKED` | 认证、质保、防水等词没有 facts 依据 |
| `WRONG_SCRIPT` | 文案不是站点语言的文字 |
| `FAMILY_MIX`（警告） | 模板不属于整套选定的套系 |
| `CAST_REQUIRED` / `ENGLISH_REQUIRED` | 有图位出现人物却没写 `cast` / `cast` 不是英文 |
| `CAST_ANCHOR_INVALID` / `CAST_UNUSED`（警告） | `cast_anchor` 不是带模特的图位 / 写了 `cast` 但没有图位出现人物 |
| `COPY_WORDING` | 文字指向参考图、模板或竞品，或要求像某位真人、名人 |
| `SCENE_REQUIRED` / `SCENE_LIKE_REFERENCE`（警告） | 用户模板图位没写 `scene` / 场景沿用了模板原图的大部分场景用词 |
| `TONE_REF_UNKNOWN` / `TONE_REF_UNAVAILABLE` | `tone_ref` 指向不存在的参考 / 内置模板或没有色调图的模板 |
| `BOX_INVALID` / `PHOTO_MOSTLY_HIDDEN`（警告） | `hide` 的框不是合法比例框 / 照片大部分被遮挡 |

**命令错误**（一行 JSON 的 `error` 以代码开头，退出码 2）：

| code | 含义与处理 |
|---|---|
| `AUTH_PASS_REQUIRED` 等 `AUTH_PASS_*` | 没有有效鉴权记录：按 SKILL.md §1 运行 auth_gate.py |
| `LEGACY_PROJECT_V7` | 这是 V7 项目，见 [legacy.md](legacy.md) |
| `PROJECT_NOT_FOUND` / `PROJECT_EXISTS` / `PROJECT_INVALID` | 项目目录不对 / 已存在（`--force` 覆盖）/ project.json 损坏 |
| `PATH_TOO_LONG` | Windows 路径过长：把项目移到短路径 |
| `PHOTO_FORMAT` / `PHOTO_NOT_FOUND` | HEIC 等格式需先导出为 JPEG/PNG / 文件不存在 |
| `PLAN_NOT_FOUND` / `PLAN_INVALID_JSON` | plan.json 不存在 / 不是合法 JSON |
| `PLAN_BUSY` | 还有图在生成中，先登记或退回 |
| `MAIN_PHOTO_INELIGIBLE` | `route: photo` 但没有合格实拍图 |
| `MAIN_PHOTO_HIDDEN` | 指定做主图的照片有 `hide` 遮挡区域：换一张照片或改用 `route: generate` |
| `REF_NOT_FOUND` / `REF_FORMAT` | 参考图不存在 / 格式不支持（HEIC 需先导出） |
| `REF_IS_PRODUCT_PHOTO` / `PHOTO_IS_REFERENCE` | 同一个文件不能既是产品照片又是参考图 |
| `RECAST_NOT_ALLOWED` | `--recast` 只能用于定下本套模特的那张图；其它图用 `--redo` |
| `PLAN_OUTDATED`（预约拒绝） | 升级前规划的图还指向旧的风格底板：重新运行 `plan` |
| `NOTHING_TO_INGEST` / `ITEM_INVALID` | `ingest-batch` 没有任何条目 / 条目缺字段 |
| `ARTIFACT_NOT_FOUND` / `INGEST_CONFLICT` / `STALE_ATTEMPT` | 见 [tool-orchestration.md](tool-orchestration.md#限流超时与异常) |
| `REDO_LIMIT_REACHED` / `REDO_NOT_ALLOWED` / `REDO_REASON_REQUIRED` | 重生额度用尽 / 该图不能重生（未完成或实拍合成）/ 缺少问题描述 |
| `TRANSIENT_RETRY_LIMIT_REACHED` | 瞬时失败用尽，问用户后 `reset` |
| `USER_CONFIRMATION_REQUIRED` / `RESET_NOT_ALLOWED` | 需要用户同意 / 只有 failed 的图可以 reset |
| `FAMILY_UNKNOWN` | `templates --family` 的 id 不存在 |

**主图检查**（`results[].auto_redo` 或 `failed_reason`）：

| code | 含义 |
|---|---|
| `MAIN_BACKGROUND_NOT_PLAIN` | 背景不是一种平整的纯色 |
| `MAIN_SHADOW_AMBIGUOUS` | 有阴影或倒影，无法安全去除 |
| `MAIN_PRODUCT_CROPPED` | 产品碰到或超出画面边缘 |
| `MAIN_PRODUCT_TOO_SMALL` | 产品太小，放大会糊 |
| `MAIN_NO_PRODUCT` | 没分离出产品 |
| `MAIN_CUTOUT_INCOMPLETE` | 产品与背景太接近，抠图会缺块（下次换背景色） |
| `MAIN_VERIFY_FAILED` | 合成结果在 q95、q100 和无损 PNG 下都没通过 255/占比/居中校验（极少见；生成路线会自动重生） |

副图：`FRAME_CONTENT_CUT`（保留带外有较多内容，自动重生 1 次）、`frame_cut_risk`（重生后仍有裁切风险，交付时告知用户）。

交付：`deliver` 返回 `model_mismatch` 时，列出的是用之前的模特完成的图（发生过 `--recast` 或 `cast` 变更）；如实告诉用户，需要重做时经用户同意再 `--redo`。
