# V8 输入与命令契约

仅适用于 workflow_policy="one_pass_v1"。旧 fields.md 的 layout、composition 和审核字段不用于此流程。

## 项目与策划输入

init 创建 project_manifest.json，默认 7 张 Listing；--listing-count 1 可只做主图。--listing-aspect 1:1.3 生成竖图。--include-a-plus 默认增加 6 个 1464×600 模块；可用 --a-plus-modules header:1464x600 feature:970x600 自定义。

使用 configure --manifest M --input planning.json；只接受策划字段，禁止通过输入修改 status、预约、哈希、历史或交付记录。jobs 按 id 更新现有图位。

planning.json 示例（其余图位也需要填写 design_brief）：

```json
{
  "product_truth": {
    "product": "实际商品名称和包含物",
    "geometry_lock": {"locked_structure": ["已核实结构"], "unknown": ["未见背面"]},
    "material_lock": {"materials": ["已确认材质"], "color": "已确认颜色"},
    "scene_scale_lock": {"support_surface": "台面", "contact": "按实际用法摆放"}
  },
  "facts": [{"id": "width", "value": "12", "unit": "cm", "source": "用户规格资料"}],
  "critical_details": [],
  "style_contract": {"palette": ["#FFFFFF", "#223344"], "typography": "Clear sans-serif hierarchy"},
  "jobs": [{
    "id": "02_size_or_components",
    "design_brief": {"goal": "解释确认尺寸", "scene": "Clean product setting", "composition": "Large product with readable dimension labels"},
    "approved_copy": [{"role": "headline", "text": "Fits your space"}, {"role": "dimension", "text": "12 cm", "fact_ids": ["width"]}],
    "human_source": "none"
  }]
}
```

批准文案 role：headline/body/label/dimension/step/faq_question/faq_answer/brand。主图 approved_copy 必须为空。无文案场景图可用空列表。保留用户已批准文案，不擅自转大写、改写或缩短。

facts 的 id 唯一，绑定的 value/source 非空；数字文案需在所绑定 facts 的 value/unit 中找到一致数字。兼容与性能等非数字主张由策划者核对来源并填写 fact_ids。必需 P0/P1 用 critical_details 中的 priority、visibility（job id→required）、evidence_refs（商品参考 id 列表）或 locations[].reference_id 绑定证据。

job 可设置 canvas、required、source_reference_ids、design_brief、approved_copy、human_source、export_keywords、template_slot_role、a_plus_module。主图另可设置 main_foreground_type（opaque/translucent/unknown，默认 unknown），仅影响本地处理；更改后重新 prepare-main 并检查，不改变生成指纹。默认使用全部 product 参考；显式设置列表时只使用所列商品证据。human_source 为 none/synthetic/real/non_photorealistic，是生成前意图，不是出图后审核结论。

project 可设置 marketplace、language、concurrency（1–32，须符合宿主实际能力）、product_profile、design_template_library_dir、design_template_set_id、design_template_policy。模板绑定后清库不影响已有项目；显式更换 design_template_set_id 会重新采用模板并使相应生成输入失效。

## 参考与模板

add-references --photos PATH... [--views front detail...] [--role product|style]：复制到项目并绑定 SHA-256。views 数量若填写必须与图片一致，支持 PNG/JPEG/WebP。只拒绝文件级损坏，不制作来源审核包。模板 prepare/submit 与库管理继续使用原专用命令；新项目提交模板时不向旧 intake 传 --manifest，改用 configure 的 design_template_set_id 或 prefer_family_ids。

模板在第一次 plan 时保存 template_snapshot 和底板副本，以后回放。底板的引用顺序在商品图之后。主图不使用风格底板和模板营销版式。

## 队列与交付

- plan [--job J]：绑定六段提示和参考哈希，返回各图状态与 next_actions；单图输入不足不阻断其他图。
- reserve [--max N] [--job J]：按容量预约，返回 job/attempt_id/kind/prompt/references/reference_roles/transparent_background。没有审核或样板前置。
- ingest-batch --item J A PATH（可重复）：逐图保存原始文件，附图导出 PNG 后 ready_to_deliver。errors 点名失败项，其他结果仍提交。
- ingest-batch --failed J A ERROR / --unknown J A REASON / --not-started J A：分别表示确定失败、提交未知、确定未提交。不能把未知结果当确定失败来重复生成。
- prepare-main --job J：只主图；显式处理已有已入库原图并恢复历史背景阻断。返回 raw_path/path/processing_id/attempt_id/processing。相同输入幂等，不新增模型预约或重置修复次数，拒绝活动/未知调用与过期生成输入的原图。
- main-background-check --job J --attempt-id A [--processing-id ID] --verdict pass|repair --observation TEXT：只主图；新版必须传入当前处理 ID，观察同时绑定原图和处理结果，通过后导出并验证纯白；历史未启用处理的主图兼容原命令。
- recover-attempt --job J --attempt-id A --reason TEXT：延续过期或未知预约，只为入库已有结果，不新增模型调用。
- release --job J --attempt-id A --reason TEXT：只用于确定没有提交的预约。
- reset-transient --job J --reason TEXT：用户明确要求后重开已耗尽瞬时预算，不重开主图背景修复预算。
- status：只读快照，包含 counts/jobs/scheduler/next_actions。
- deliver：只读并校验当前输入与文件绑定；返回 complete/image_count/expected_image_count/images[{id,path,sha256,canvas}]/missing_jobs。部分可交付时 ok=true、complete=false；不得据此称整套完成。

主要状态：pending、generating、awaiting_result、main_background_pending、ready_to_deliver、needs_input、failed、blocked。旧 qa_passed 不用于新流程。新流程不提供 review-*、compose、qa、finalize；这些旧命令通过历史路由继续可用。

主图 PNG 的 delivery.white_background 记录 RGB、背景 mask 路径及哈希、背景像素数和最终文件哈希；新版掩膜由实际处理图 alpha=0 区域生成，半透明和抗锯齿过渡保留为前景。main_processing 记录原图、处理图、设置与变换；delivery 额外绑定 processing_id 与 main_check_hash。主图背景分离由查看原图与处理图确认，不能根据四角或亮度自动推断产品边界。规则见 [main-background.md](main-background.md)。
