# 原始结果与处理进度（04A）

仅新任务使用 `source-result-processing-v1`。真实来源执行仍由原 API／网页入口承担；本合同只处理已留存的回执，不发请求、不增加页数或候选额度。导入准确案号与历史证据复用保留原真实入口；没有原始检索回执时不补造结果位置。

发现类 `source_runs[]` 的 `result_processing` 记录原回执摘要、已得行位置／哈希、来源返回量、原始解析量与零条证明。能直接定位 JSON 或 EPO／INPI XML 行时按原行记录；解析少于返回量时，仅以与原行完全一致且唯一的号码字段绑定解析位置，歧义继续待解析。只有可信响应计数而无逐行位置时记 `response_count_only`，仍待核对；总命中量不当作已得量。来源结果状态、解析、候选入库与材料审阅是独立进度。仅在真实提交、适配器确认响应有效且已得行明确为空时记 `zero_proven`；登录、加载、错误或未提交不得借 `no_result` 字样成立零条。

执行 `next_work.py` 后，未处理回执以 `SOURCE_RESULTS_PENDING_PROCESSING` 进入原统一待办；回执缺失、哈希或索引不符为 `SOURCE_RESULT_RECEIPT_OR_INDEX_INVALID`。已得 57 行即保留 57 行并逐行审阅，不按 50 的主动获取上限删行；是否继续获取仍由模块 03 的目的预算决定。回执已保存而解析中断时，只从校验合格的原回执处理，不再次提交来源。

对已保留的错误回执，可单独提交 `{"receipt_disposition":{"outcome":"non_result_error","reviewer":"...","reason":"..."}}`。该入口只接受明确失败／访问受限状态，或可识别的 EPO／INPI XML `fault` 信封；原回执必须经哈希核验，且不能包含可识别结果行、已解析行或已归档的结果材料。该审核只关闭回执材料处理待办，不更改 source run、返回量、`zero_proven`、查询覆盖或风险结论。成功响应、有效空结果、含部分结果行的回执，以及仅因解析器返回未知的响应均拒绝此处置。

本地恢复使用 `record_source_result_processing.py --task-dir DIR --source-run-id RUN --input INPUT.json`。单个操作保持兼容，也可在同一个原子输入中提交 `parsed_rows` 和 `decisions`：

- `{"parsed_rows":[{"position":25,"candidate":{"publication_number":"US..."},"reviewer":"agent","reason":"原回执第25行"}]}`：原回执行必须可定位且哈希有效；补入原运行对应 collection。重复提交同一内容幂等，冲突拒绝。随后重跑 `merge_candidates.py` 并核对候选；未能形成候选的行仍有明确缺口。Serper／SerpAPI 的原卡片具有严格等量、等哈希合同，手工补解析被拒绝，须由原适配器仅重放已留存回执并复验，不得改写来源行或发新请求。
- `{"decisions":[{"position":25,"outcome":"candidate","candidate_ids":["CAND-..."],"reviewer":"agent","reason":"原回执显示具体文献"}]}`：经审阅将行关联到同源候选；可选 `duplicate_source` 或 `non_candidate`，后者必须写依据。一个原始行可含多个候选 ID。整批先校验后一次写入，重复提交幂等，改写旧决定拒绝；身份合并／拆分纠正留给 04B 追加关系处理。
- `{"receipt_disposition":{"outcome":"non_result_error","reviewer":"agent","reason":"来源返回明确错误回执"}}`：显式审核无结果错误回执，不能用作逐行结果的处置。

补解析会追加 `result_parses`：原始行哈希、解析候选摘要、审阅人和理由都留痕；不会改写原始回执或旧来源运行。没有可枚举原始结果行的失败请求维持原失败待办，不伪造位置；声称零条却缺少可验证空响应时，评估与报告都保留 `ZERO_RESULT_UNVERIFIED` 缺口。

`material_processing_complete` 仅表示本回执的已得位置均有可追溯去向且无解析／计数缺口，不代表候选分流完成、权利有效、查询覆盖充分或整项任务可交付。分流仍用 `annotate_materiality.py` 的整批验证与一次落盘，不从本页的结果去向推导 `selected/not_selected`。

多回执统一输入使用 `{"events":[{"source_run_id":"RUN", "parsed_rows":[...], "decisions":[...]}, ...]}`，命令省略 `--source-run-id`。每个事件可携带上述解析、逐行决定、`receipt_disposition` 或 `record_content_review`；按解析→决定→错误材料→完整阅读的顺序在同一内存快照验证，整批通过后 evidence 只写一次，每个来源回执只刷新一次材料进度。任一事件失败则整个批次不落盘。重复完全相同输入不写新记录。关联候选仍须已经通过合并并绑定到对应原始行；这一批量入口不会自行作候选分流、补造阅读或授权重试。XML 派生涉及独立文件完整性，仍保留单独的转换入口。

原响应登记的真实状态、来源字段、行位置、信任材料及来源操作验收通过同一次 `record_result` 写入自动投影；不得为展示来源再手工复制相同 response 或重新调用 API。辅助计时独立留在 `runtime-timings.jsonl`，不改变原回执日期和事实摘要。

USPTO 浏览器的 CUA 留存可用 `rows[].cells[]` 枚举实际可见行，仅该提供方支持，单元格列表须非空，单元格为字符串或含字符串 text 的对象。旧回执索引为 unknown 且原文哈希有效时，在读取层派生行索引，不改写旧运行、原文或失败状态；已知索引不符仍拒绝。结果历史未绑定时，枚举行仅证明已得材料，不证明查询归属、成功召回或恢复许可；不得据此把线索自动导入为已验证候选。

对明确 `history_binding_verified=false` 的 USPTO 可见行，本地补解析拒绝 `RESULT_PROCESSING_QUERY_BINDING_REQUIRED`，自动位置绑定也不执行。保留原行待核，不靠手工补解析将未绑定线索升级为正式候选。

## 旧 EPO XML 脱敏损坏的受限恢复

只有旧通用 URL 脱敏把 XML URL 中的 `&amp;` 转成 `&amp%3B`、导致整文严格 XML 解析失败时，才可单独提交 `{"xml_derivation":{"transform":"xml-url-amp-semicolon-v1","reviewer":"...","reason":"..."}}`。此入口只接受原 EPO 专利 XML 的 response_count_only 回执；精确替换 URL 内已知字节序列后，整文必须严格解析成功，EPO 已得数、页范围、原 exchange-document 字节块数量及逐行唯一 US/WO 身份必须一致。其他损坏、混合错误、有效 XML、计数冲突都拒绝。

原始 raw、payload_digest 与 source run 不变；追加 `result_xml_derivations`，保留转换位置、原/派生哈希、派生文件与每行原始字节跨度/哈希。每次投影都重放转换并核验原件、派生文件和记录。合法旧 XML 的已有 ElementTree 行哈希与索引不变。派生文件只是解析材料，不是新的来源执行或原始官方文献。

之后单独提交 `{"parsed_rows":[{"position":1,"bind_existing_publication_number":"US...A1","reviewer":"...","reason":"..."}]}`；仅按该原始字节块的精确唯一公开号绑定已归档、尚无位置的候选，追加旧候选摘要→新位置证明，不修改旧候选 payload、不复制候选。派生字节块不接受手工补造新 candidate。重跑 merge 后才可作原 04A 逐行处置与候选交接；材料审阅、相关性决定和总命中剩余覆盖继续保留各自原门禁。

## API 完整专利记录

`api-first-v3` 的 SerpApi `google_patents_details` 明确 Success 回执按 `whole_record_receipt` 处理：原始完整 JSON 只有一个阅读对象，`returned_count=1`、`parsed_count=0`；引用、相似文献和同族列表不生成新的搜索候选。旧 unknown 索引只在原件哈希、准确请求号、目标国家、已登记候选和来源 payload 一致后产生只读投影，原运行与原始字段不改写。

使用同一记录器提交 `{"record_content_review":{"reading_units":["identity","document_text","claims","image_links"],"reviewer":"实际阅读者","reason":"实际读到的内容及限制"}}`；缺 claims 或 image 链接时分别省略该阅读单元。回执追加到 `record_content_reviews`，绑定具体候选内容、原文/运行/规范记录哈希及准确身份关系；图样 URL 仅为链接阅读，不能证明图样已经获取或视觉比较。缺字段或截断原意保留，专项缺图仍有待办。

候选号与详情号不同，不能自动补 S1、借同族或标题视作同一文献。只接受原准确 locator 及已登记、经哈希核对的已读原文；原文须明确同时出现候选号、详情号和同申请号，并绑定同候选与国家。事实或材料发生实质变化时可追加新的完整阅读，保留旧凭据且不改绑旧签名。普通 `non_candidate` 或 `duplicate_source` 行处置不能替代完整记录阅读。

OPS `candidate_detail/images` 的准确 `document-inquiry` 可使用同一完整记录入口，阅读单元为 `["identity","image_metadata","retained_media"]`。只接受相符的 epodoc/docdb 文献号、目标国家和实际完整图像路径；每份 TIFF 校验原哈希、字节数、尺寸及文献/页号，缩略图或纯URL不能替代。保留原 `parsed_count=1`，不制造搜索行位置；完整记录阅读只关闭04A材料处理，未获取的其他视图及具体比较任务仍待处理。其他 OPS fulltext/biblio 回执没有凭此 images schema 自动完成。
