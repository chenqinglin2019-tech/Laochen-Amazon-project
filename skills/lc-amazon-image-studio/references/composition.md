# 图文构图与底图验收（layout_first/1）

适用新项目的 `composition_policy: {version: 1, mode: layout_first}`，配合 `anchor_policy: {version: 1, mode: full_review_first}`。旧项目缺此策略时不自动迁移，不改变其提示词；明确要求升级旧项目时才设置这两个策略并重新规划受影响图片，说明这可能需要重生。

## 生图前设计

每图围绕一个购买信息确定文案、图位用途和视觉焦点，然后用 `layout.text_groups`、`layout.product_region_norm`、`layout.protected_regions` 表达最终区域。位置使用 `[x,y,width,height]`，归一化到最终画布。文字区与产品区分离，沿用短边 5% 安全边距。

每张 `local_overlay` 附图还要写：

```json
"composition_intent": {
  "negative_space": "左侧为连续、低纹理的浅色墙面，给标题和两行正文留空间",
  "subject_scale": "完整产品位于右侧，包含所有挂件，主体明显且保留呼吸空间",
  "layout_reason": "使用场景图以真实墙面自然留白，避免把照片缩进文字卡片"
}
```

- 场景图优先自然留白；尺寸、组件、步骤图可事先规划侧栏、标注或分镜。不要让整套图机械重复同一布局，也不要给所有商品硬套同一留白百分比。
- `plan` 实测文字容量。候选配方只是容量证据，代理要结合产品形态、主体大小和画面重心选择后重新 plan；当前版本不自动用另一配方覆盖新项目设计。
- 不足以支撑某项卖点时改图位目的；不要把“来源未确认”“内部审核说明”等流程文字塞进销售图片。
- 参考商品图用于锁产品身份和细节；允许为最终图文布局调整机位、商品位置和画布内展示大小。实际物理比例、结构和真实场景尺度仍受四项锁约束。
- 派发时保存 `composition_contract`，由实际布局派生，和 `generation_geometry_lock` 同时核对。不要手改快照、哈希或历史记录。颜色、字体与换行可在原文字框内调整；画幅、产品区、文字框、裁剪与面板结构不能事后改成补救方案。

## 样板与底图检查

先选 `03_primary_use_case`；没有它就选第一张有本地文字的附图。`reserve` 在样板完整合格前只派发样板，样板失败不自动换另一张绕过门禁。样板审核由代理完成，不额外要求用户确认。

入库后执行：

```text
P scripts/lc_image_pipeline.py review-prepare --manifest M --stage composition --job J --json
```

看返回的 `look_at` 无字画面（有面板/插图时为按计划合成的画面，`raw` 另保留原底图），填写 `packet`：

- `observed_product_bbox_norm`：实际产品完整轮廓的外接框，不能照抄计划框。细长挂件也包含在内。
- `observed_protected_regions`：实际人物、手、关键接触点或动作的外接框；没有则为 `[]`。
- `checks`：`text_space`、`subject_scale`、`subject_complete`、`natural_space`，各自填 `verdict: pass/fail` 与具体 `notes`。不得自动预填为通过。

提交仍使用 `review-submit --manifest M --packet <packet> --json`。代码检查实际框是否侵占文字区、是否偏离产品容器、画幅比例是否匹配，并绑定实际原图、构图、相关图层及审核规则哈希。产品容器允许 2% 坐标偏差，文字区不允许重叠；画幅比例允许 1% 生成误差。外接框检查是保守检查，不是自动分割，也不能代替视觉判断。

`pixel_composite` 走同一准备入口，先输出真实商品图层与背景合成的无字画面，再检查；不会用一张空背景冒充合成验收。构图包只在内部保存，不制作给用户的套图预览。

底图合格后执行 `review-prepare --stage final --job J`，进行本地排字与原有产品/细节/手机端审核。

## 显式成品美感判断

新项目 `answers.template.json` 的 `explicit.visual_design` 需要完整填写：

```json
{
  "verdict": "pass",
  "notes": "结合实际成品说明总体判断",
  "checks": {
    "text_relationship": {"verdict": "pass", "notes": "文字所在背景、对齐与产品关系"},
    "subject_scale": {"verdict": "pass", "notes": "主体大小、重点细节与手机端辨识"},
    "composition_integrity": {"verdict": "pass", "notes": "边缘、挂件完整性、无补救边框和异常裁切"},
    "series_consistency": {"verdict": "pass", "notes": "与样板及整套字体、配色、光线的关系"}
  }
}
```

失败时总体 verdict 为 `fail`，并写 `failure_stage: base` 或 `typography`。底图占位/机位/主体大小问题选 base；字体/换行/对齐/文字对比度选 typography。任一底图问题存在时选 base。不能因为“没有遮住产品”就认定构图美观。

底图失败进入 `generation_repair_needed`，`plan --jobs J` 绑定原失败底图和具体原因，再预约一次质量返修。仍失败即阻断，不重置预算。本地像素合成失败需要修正来源/图层设计，返回 `QUALITY_COMPOSITION_LOCAL_REPLAN`，只能在原产品容器内修正商品图层，再执行 `review-prepare --stage composition --repair-local --job J`，消耗同一个一次质量返修预算并保留旧快照/失败记录；画布、文字框、文案、面板必须不变。先按原入口更新所需来源审核，不能冒充模型返修或偷偷改冻结构图。

最终只交付成品图片链接。逐图 sheet、360px 检查、构图记录和 QA 报告为内部证据；不再为交付生成项目总览、细节汇总、ZIP。
