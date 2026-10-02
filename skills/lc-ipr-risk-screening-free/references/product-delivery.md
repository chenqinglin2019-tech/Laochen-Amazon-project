# 商品采集与事实交付（02A）

本协议是 `image-fact-v1`，由 `product-scope-input-v2` 激活；既有 v1 输入和未标记历史任务保留原合同。先按[产品入口](product-entry.md)冻结真实目标，再按[对象范围](product-scope.md)登记来源、事实和方向。用户只提供商品资料或意图，Agent 负责形成技术 JSON；程序核对留存、绑定、版本和已声明的性质，不代替图片理解或法律判断。

## 查询主图

- 用户资料使用 `product-input-v2`，增加 `image_selection`：`status=selected` 时填 `source_id`、`selected_by=user|agent` 与具体 `reason`。用户指定时另填 `statement_source_id`，指向已留存的文字说明；未指定时 Agent 选择能代表同一目标的整体图并说明依据。存在实质歧义填 `needs_clarification`、原因与最小 `question`；暂无合适图填 `unavailable` 和原因。不能靠文件列表顺序暗选。图片可留作 `product_view`，只有被选中且核对的图片标 `main`。
- Amazon 入口沿首次有效当前子体的页面主图，保留相册和截图；主图与冻结目标、来源 URL、原始文件 hash 和选图依据绑定。辅图仅用于事实、线索、对象位置及比较，不改名为另一张主图发起查询。
- `product.query_image` 记录选图、来源形式、目标绑定和版本时点。其他公开 URL 须在 v2 图片来源中提供本地留存文件、HTTPS `source_url` 与 `public_url_review={status:confirmed,reviewer,reason}`，由 Agent 核对 URL 与该文件的实际对应关系；程序核查留存文件和声明结构，不能独立证明远端内容未变化。范围 v2 的对象 `visual_evidence` 记录 `image_ids`、`main_visibility=sufficient|limited|not_visible|unknown` 和关键限制原因。主图查询成功不能解除“背面图案仅在辅图可见”等对象缺口。
- `scope.image_permissions` 按接收方与用途记录 `provider=serpapi_google_lens`、`purpose=image_discovery`、`status=allowed|not_allowed|unknown`、真实说明/文件 `source_refs` 和 `reason`。Agent 自述不能授予外传许可；选择主图也不自动授权。当前仅能把有留存与对应关系的公开 HTTPS 主图 URL 用于具备相应能力的 Lens 路线；用户本地文件不自动上传、托管或伪造公开 URL。许可或输入能力不足时仅留相关路线缺口，文本工作继续，不记零结果。旧计划提交前再次核对主图、目标版本和许可。

## 事实、线索和四部分交付

`product-scope-input-v2` 沿用 v1 的四态、来源、对象和方向，`scope.delivery_revision=image-fact-v1`。每个事实至少保留稳定 `fact_id`、正整数 `version`、`source_path/value/status/source_refs/reason`、`applies_to.product_id`，并增加：

- `nature=direct_observation|page_claim|user_statement|analysis_inference`：记录信息是什么性质；`page_claim` 必须能回指 Amazon 页面或留存文件，用户说明必须回指用户资料或留存用户表述。
- `verification=verified|claim_only|unverified|conflict`：页面声明和分析推断不能被标为已核实结构。已确认声明文字可用 `status=confirmed, verification=claim_only` 作为带性质的查询线索，不能自动成为确定工作原理或比较结论。未知、冲突继续走方向级最小问题。
- OCR 模糊但可能重要时，原文必须保留在 `product.raw_capture.ocr_text[n]`。`analysis.clue_dispositions` 对该路径可填 `disposition=needs_verification`、原文摘要、原因和精确 `question`，同时在 v2 范围登记同一路径、同原文的 `status=unknown, verification=unverified` 事实及相同问题；此时不得把该路径映射成查询词。关联方向等待核实，未绑定方向仍进入统一待办；独立方向可继续。无关 OCR 才用有理由的 `excluded`。
- 对象继续使用一个稳定 `object_id`；同一原图通过 `image_ids` 被多个对象引用，不复制或丢弃原图。已纳入的关键视觉对象若主图不充分，必须说明具体限制。

记录器从已审范围生成 `task.product_delivery` 四部分：`product_range`、`facts_and_clues`、`objects_and_marks`、`gaps_and_conflicts`，附选中主图、已知许可与可继续方向编号。事实、对象和主图可见性缺口列出受影响方向；图像路线缺口只指向图片发现动作。不得手改投影；规划前验证它与原始范围一致。实际查询行记录所用事实的 `fact_id/version/nature/verification`；事实版本变化后旧行暂停复核，旧查询和材料仍保留。针对比较或风险结论的完整历史适用性复核属于 02B，不能把 02A 的查询可用性当作结论已核实。

报告在原八节七模块内显示产品角色来源“系统默认”、事实性质、主图依据与对象级限制。示例和离线 Mock 只验证协议，不证明真实商品、来源许可或视觉覆盖。
