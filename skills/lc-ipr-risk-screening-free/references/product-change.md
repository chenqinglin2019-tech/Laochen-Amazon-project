# 商品变化与定向复核（02B）

本协议由 `product_change_revision=product-change-v1` 激活，只作用于已有 02A 交付的任务及显式目标变更；无标记历史任务沿原合同。用户只说明业务变化，Agent 核查资料并形成输入 JSON。所有变化保留原始资料、旧范围收据、旧查询和已取得的候选，不通过删改历史清除影响。

## 识别变化

- **事实纠正、撤回、补充证据或对象范围变化**：继续用 `product-scope-input-v2` 提交完整范围快照与当前 `expected_scope_sha256`。同一重要事实内容变化时保留 `fact_id`、提高 `version`，新值或 `unknown/conflict`、性质、核对状态、来源、原因及最小问题均明确；原快照由范围收据保存。记录器计算变化前后关系、受影响方向、旧查询及候选。缺少候选到比较事实的精确依赖时，只扩大到相关国家和权利方向并留理由，不自动全量重搜。
- **Amazon 显式换目标／身份纠正**：先留存用户明确换目标的原话，或可核对的纠错来源；生成 `--change-review` 文件，包含 `kind=target_change|identity_correction`、旧 `expected_target_sha256`、新 `actual_asin`、已核对 `variant`、`reason`，换目标还需 `user_statement`。若 URL 变更填 `new_url`，不得跨原任务 Amazon Host。先用 `node tools/cdp/cdp-cli.mjs capture-amazon --task-dir DIR --change-review REVIEW` 捕获当前页，再用 `record_browser_product.py --task-dir DIR --capture CAPTURE --change-review REVIEW` 提交。普通刷新没有此审阅记录仍拒绝替换；新图、ASIN、当前选项、页面和来源继续通过原有验证。
- **用户资料显式换目标／身份纠正**：准备一份已审 `product-input-v2` 新资料及同类 change-review，运行 `record_user_product.py --task-dir DIR --product-input NEW_INPUT --change-review REVIEW`。原资料和文件不覆盖。两种入口切换后只保留当前目标的产品资料，当前范围改为待重新登记；新范围首次 `expected_scope_sha256` 为空，事实的 `applies_to.product_id` 引用新目标。旧查询行不改，新的行绑定当前目标和变化版本。
- **仅重压缩／同内容裁剪**：用 `record_product_image.py` 的 `product-image-change-v1` 输入，填 `relation=recompression|crop`、原 `original_image_id`、新文件 path、当前目标/范围摘要和 `review={reviewer,reason,content_effect:same_content}`。程序保留新旧文件的 hash 与关系到 `image-relationships.json`；原证据、主图、查询与结论不会仅因文件字节变化被改写。Agent 必须真实核对内容与引用，不能仅凭哈希不同或相同作业务判断。
- **新增视图或揭示新信息的裁剪**：同一输入用 `relation=additional_view|crop`、`content_effect=new_information`，并列出受影响的 `affected_fact_ids`／`affected_object_ids`。新图只登记为辅图，不能静默成为查询主图；相关动作进入待范围复核。下一次完整范围快照必须用对象 `visual_evidence.image_ids` 或事实 `source_refs` 绑定该图的留存证据，才可继续。

## 复核与复用

每项变化有递增产品版本、不可改的变化收据、旧／新范围或目标关系及影响清单。直接依赖从事实、对象和方向传到查询；候选由查询来源关联，比较依赖不明时在同国家与权利范围内有界扩大。旧查询成功不是新目标的覆盖证明，旧阳性材料也不机械删除。

对变化清单里的历史候选，Agent 检查其原来源、当前产品和范围，形成 `product-applicability-v1` 输入，填写当前 `product_version`、`target_sha256`、`scope_sha256`，每项 review 含 `change_id`、`candidate_id`、`status=usable|not_applicable|needs_info`、`reviewer`、`reason`、真实 `source_refs`，再运行 `record_product_applicability.py --task-dir DIR --input REVIEW`。`usable` 保留继续适用理由；`not_applicable` 不能作为当前在范围内判断；`needs_info` 仍阻止最终结论。复核收据不可原位改写，后续新变化产生新版本再审。

最终独立双审仍绑定当前完整输入摘要；适用性审阅只决定历史材料能否用于当前分析，不代替候选比较和法律判断。`assessment.json` 与 HTML/Markdown 报告绑定当前产品目标、范围摘要和产品版本；未审受影响候选、旧目标待重新登记、或不适用结果仍被纳入当前判断时拒绝完成。适用性和版本在报告既有产品区域展示，不改变八节七模块布局。
