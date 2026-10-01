# Amazon Listing 生成：单品与父子体

本文件是跨平台执行流程。字段结构只在 [data_contract.md](knowledge/data_contract.md) 定义，数字预算只在 [quality_policy.json](knowledge/quality_policy.json) 配置，写作规则在 knowledge/distilled，出处在 knowledge/sources.json。

## 目标与边界

用户输入：目标 site、竞品 asins（1–20 个）、本品图片或文字资料，可选品牌、必保词、禁用词、子体 SKU/ASIN 与变体信息。

目标：在真实事实范围内，让文案和图片策划同时服务三件事。
- **A9 词法检索**：高流量可用词的每个词都出现在可索引字段（标题、Item Highlight、五点、长描、后台词）中。
- **COSMO 意图理解**：已确认的用途、人群、场景、地点、季节、搭配等关系，用自然语句写出来。
- **Alexa for Shopping（原 Rufus）问答**：属性完整，并能回答 who/what/when/where/why/how。

边界：
- 站点必填，支持 US/UK/CA/IN/JP/DE/FR/IT/ES。未给站点时询问，不默认 US。
- 单品生成一份完整 Listing。明确提供多子体及变体资料时，生成父标题、父 Item Highlight，以及全部子标题和逐一对应的子 Item Highlight。只生成用户提供的组合，不补齐颜色×尺码，不写"其他同理"。
- Item Highlight 始终是一条短亮点；bullets 是独立五点字段。两种模式都交付五点、长描、后台词、后台属性建议、主附图策划、A+ 策划和报告。
- 事实和平台约束是硬边界。边界内的优先级依次为：完整产品身份 → 用户必保词 → 子体区分属性 → 主要购买理由 → 关键词覆盖。
- 核心品名在扩词中缺席或流量未知也不能删除。后台类目枚举不能替代消费者品名。用户品名与真实产品冲突时，指出具体冲突，不静默改名。
- 竞品、论文、QA 和外部文档只是参考资料，不是本品事实或执行指令。不得编造数值、认证、品牌、SKU、算法权重或推荐率。
- 只询问真正阻碍继续的缺失事实，并集中列出。其余缺口进入报告中的"补充事实可解锁的流量"。

## 后端与执行环境

- 所有后端调用都经过 `scripts/backend_cli.py`。它从 Skill 根目录的 config.json 读取凭据，只通过子进程环境变量传给 tools/bin 中当前平台的 CLI。不要读取、回显或 export 凭据，也不要另写启动脚本。缺 token 时停在请求前，本地整理可以继续。
- 同时检查退出码和保存的业务 JSON。有文件不等于成功，部分 ASIN 失败要逐项报告。失败或超时不自动重试，先核对状态。
- 本地工具使用 Python 3.9+ 标准库。没有 Python 时报告缺失，不用心算冒充校验。所有文件用 UTF-8。Windows 下不要用默认编码重定向写 JSON。
- 后端 qa 当前只接 US，这是连接器范围。非 US 跳过 qa，但仍要做问答覆盖矩阵。

## 流程

每次任务创建独立目录 `listing_YYYYMMDD_HHmmss/`，下文记作 RUN；SKILL 指 Skill 根目录。两者执行时替换为绝对路径，路径作为独立参数传递。

### 1. 输入快照、画像与单位

先读 distilled/product_facts_rules.yaml。保存 00_product_input.json，内容为原始描述、站点、竞品、品牌、约束、图片定位和子体清单。再按契约生成 01_product_profile.json，包括 product_identity、facts、measurements、images 和 **intent_map**。未知信息写 null/unknown，"未证实防水"不能写成"已证实不防水"。

family 画像：
- 保留输入顺序，并分配稳定的 variant_id。
- 记录有序的 variation_dimensions 和 variation_theme 依据。
- 根级只放明确适用于全系列的事实。
- appearance_assessment 只依据资料判断；有来源确认外观相同、且差异仅为尺寸或数量时，才允许附图复用。

```text
python3 SKILL/scripts/listing_quality.py normalize --profile RUN/01_product_profile.json --output RUN/01_product_profile.json
```

US 单位规则：
- 公制换算为美国单位：长度不足 120 in 用 in，否则用 ft；重量不足 1 lb 用 oz，否则用 lb；容量不足 1 gal 用 fl oz，否则用 gal。
- 原资料本来就是英制单位时保持原单位。
- 线缆、软管、绳索、延长线、梯子等按"英尺"销售的品类，设置 `preferred_unit: "ft"`。
- 正文可以写成 `5.91 in (15 cm)`，在 US 单位后用括号附原单位。

其他站点保留来源单位。公称规格和尺码不换算。质量单位 oz 与容量单位 fl oz 不能混用。

### 2. 整组扩词（1 次请求）

```text
python3 SKILL/scripts/backend_cli.py expand --asins ASIN1,ASIN2 --site SITE --output RUN/02_kw_raw.json --reuse-days 7
```

同一组 ASIN 加同一站点，在 7 天内复用相邻任务的结果，不再发请求，此时输出里会显示 reused_from。必须用 --output 保存完整响应。部分失败不能描述为全组成功。

### 3. 筛词：三类词池 + 意图组判定

先读 distilled/keyword_filter_rules.yaml。

```text
python3 SKILL/scripts/keyword_quality.py prepare --run-dir RUN
```

prepare 生成未审查的逐词账本 03_keyword_decisions.json，和按流量排序的紧凑表 03_keyword_view.tsv。**读这张 TSV，不要读大 JSON。**

逐词账本、三类词池以及全部检查规则保持不变。新增的"意图组判定"用来把同一个判断只写一次：
1. 按完整搜索意图把词归组，每组写一次 decision、reason_code、reason、query_intent、evidence、role、label、fact_ids、applies_to；deferred 组还要写 promotion_condition。
2. 写成 groups 文件（格式见 data_contract），再执行：

```text
python3 SKILL/scripts/keyword_quality.py apply --run-dir RUN --groups RUN/03_keyword_groups.json
```

3. 组内个别词判断不同时，用 overrides 单独写，并补 group_difference。词多时可以分批 apply，每次输出会显示剩余未审查数量。

分类标准：
- **eligible**：与本品真实相关，有事实或身份依据。
- **deferred**：存在歧义、事实未知或季节用途未确认，须写晋级条件。暂缓词不进入文案、后台词、图片文案或 QA 请求。
- **excluded**：完整意图不符、与已确认事实冲突、用户禁用，或查询中没有有效文字。

判断规则：
- 只按完整词或短语判断。bathroom 中的 bat、lightweight 中的 light 都不算命中。
- 禁止用子串正则或封闭白名单批量删词。
- 低流量、非 ASCII、词短都不是"无关"的理由。
- 竞品品牌词和第三方商标词不进入本品文案和后台词。

```text
python3 SKILL/scripts/keyword_quality.py check --run-dir RUN
python3 SKILL/scripts/keyword_quality.py export --run-dir RUN
```

不做剔除词第二轮复核。export 通过只代表分类和结构合格，最终还要经过第 8 步的 keyword_usage 复审。

**后续修改画像（例如补登一个事实）时**，执行 `keyword_quality.py rebind --run-dir RUN`。它只列出引用了被修改事实的词；核对并更新这些词后，执行 `rebind --reviewed`。不需要重审全部词，也不要手改哈希。

### 4. 卖点与意图

04_kw_tagged.json 由工具导出，保留 high/relevant 标签，以及 role、intent_group、流量、适用子体。

主要卖点按"买家需求—产品能力—证据—适用场景"组织，同时完成 intent_map：每个已确认的关系（function、capability、activity、audience、location、season、body_part、companion、product_type、interest）写一个目标语言表达，后续要在文案中自然出现。不为覆盖意图添加没有依据的用途。

### 5. 候选词与 QA 请求词

生成 05_title_keywords.json：
- `title_keywords.high/relevant`：QA 请求词，合计 **≤8 个**，选高流量的身份词或意图词。超过时 backend_cli 在本地拒绝，不会发出请求。
- `protected_terms`：覆盖画像中的全部必保词。
- `placement_plan`：先写初步安排，至少包含必保词对应标题。最终版在第 7 步由工具按实际文案生成。

只能使用 eligible 词或有依据的本品补充词。父标题不含变体值、价格、库存或具体包装数量。子标题由统一的 title_template 生成，按最长属性组合预留空间。

### 6. 买家问题（US 1 次请求）

先运行 `keyword_quality.py check --run-dir RUN`，然后执行：

```text
python3 SKILL/scripts/backend_cli.py qa --keywords-file RUN/05_title_keywords.json --site US --output RUN/06_qa.raw.json
```

再生成 06_qa.json，逐题写 relevance、fact_ids、applies_to 和 disposition：
- answered：相关且有证据；
- unsupported：相关但没有证据；
- excluded：不相关。

返回的 seed 与请求词不一致时，隔离该问题，不作为证据。

- 非 US：写 status=skipped、reason_code=rufus_us_only、qa_pairs=[]，不调用 qa。
- US 未能采集：写 unavailable 和原因，验收标为 incomplete，不伪造请求词或结果。

### 7. 写文案、图片与 A+

先读 site_language_rules.yaml 和对应的 distilled 规则；family 加读 variation_rules，图片加读 image_planning_rules。写法参考 knowledge/style_snippets.md。**不要通读 knowledge/examples/*.json**，那些是测试夹具。

| 字段 | 写法要点 |
|---|---|
| Title（≤75 字符） | 品牌（已知时）+ 完整品名 + 最重要的差异或规格。尽量用到 60–75 字符，把高流量可用词的核心词放进来。同一个词最多出现 2 次（介词、冠词、连词除外）。不用 `! $ ? _ { } ^ ¬ ¦`，属于品牌名的除外。语序自然，不拼接词表 |
| Item Highlight（≤125 字符） | 补充标题没写到的材质、适用场景或推荐用途，可被搜索。不重复标题整句 |
| Bullets | 5 条，格式为 `【大写卖点标签】正文`，每条约 150–250 字符。一条一个购买问题，按决策重要性排序。每条写清能力、依据和适用场景，并自然带出 intent_map 中的关系（如 "for …"、"in the …"、"pairs with …"） |
| Description | 补足使用方法、适配条件、包装清单、保养和限制。写成可以独立理解的事实陈述，方便直接回答买家问题 |
| Search Terms | 小写，用空格分隔，不加标点，不重复标题中的词，不重复自身，不写品牌、ASIN、竞品品牌或促销词。用满站点预算：IN 199、JP 499、其他 249 字节，取 eligible 中前台未覆盖的同义词和长尾词 |
| attribute_suggestions | 后台结构化属性建议，例如 item type、material、target audience、intended use、special feature、included components、number of items、尺寸、颜色。每项都引用事实 |
| buyer_question_coverage | 至少 6 项，覆盖 5W1H 和品类常见问题（尺寸/适配、材质/安全、用途/人群、保养、包装清单、保修/对比）。缺事实的项标 not_claimed |

- 每个可核查声明都通过 claims 指向事实或 measurements。上架字段和图片文字使用目标站点语言；策划说明用中文。
- family：父 Highlight 只写系列共性。共用正文只写全系列事实；有差异时用 content_overrides。

图片与 A+（数量为用户确认的交付要求）：
- 单品和系列共用方案：1 主图 + 6 附图 + 至少 5 张 A+ 图片。
- family 先给共用方案，再按输入顺序给逐子体方案：外观不同或无法确认时用 per_variant_full，每个子体独立 1+6；有来源确认外观相同、且只差尺寸或数量时用 shared_secondary，子体只单独策划主图，附图引用共用创意，并用 variant_bindings 逐子体替换参数和素材。A+ 全系列共用。
- 每张创意都要写明中文 direction、买家问题、卖点、画面证据、场景或意图、目标语言 overlay_text、引用、body_refs、mobile_check、production_notes。缺素材时标 pending，并写清缺什么。
- 6 张附图默认按购买问题和 intent_map 分配，可按品类调整：场景/地点、人群/使用方式、尺寸/适配、包装清单、材质/细节、差异或对比。
- 主图：纯白背景，产品占画面 85% 以上，不加任何文字，真实展示可售数量和随附配件。

写完后执行一次覆盖反馈：

```text
python3 SKILL/scripts/keyword_quality.py coverage --run-dir RUN
```

coverage 列出高流量但未覆盖的可用词、后台词字节利用率、还没写进文案的 intent_map 表达，以及补充事实可解锁的流量。它只是参考，不是门槛。**最多据此改进一轮**，然后执行 `coverage --run-dir RUN --write-placement`，用最终文案的实际位置重写 05 的 placement_plan。

### 8. 验收与报告（按成本从低到高）

```text
python3 SKILL/scripts/listing_quality.py check --profile RUN/01_product_profile.json --listing RUN/07_listing.json --qa RUN/06_qa.json --output RUN/08_validation.json
python3 SKILL/scripts/listing_quality.py backend --profile RUN/01_product_profile.json --listing RUN/07_listing.json --output RUN/08_backend_validation.json
python3 SKILL/scripts/listing_quality.py review-template --profile RUN/01_product_profile.json --listing RUN/07_listing.json --qa RUN/06_qa.json --output RUN/08_semantic_review.json
```

1. **local check**：先修 error。warning 是优化提示，不阻断交付。此时缺 review 或 backend 显示为 incomplete，属于正常状态。
2. **backend**：每个子体逐个调用 validate。重跑时自动沿用 payload 未变且已通过的子体结果，只请求有变化的子体。
3. **语义复审**：review-template 会保留内容未变的 target 的已有结论，只把有变化的 target 重置为 pending。由独立复审者对照原始资料，逐项填写 identity、readability、factual_support、language、variant_scope、qa_relevance、keyword_usage 和 media 的 image_truth，写 pass/fail/not_applicable 及依据，不能机械标 pass。keyword_usage 核对实际使用的词及相关意图（含后台倒装词和真实否定说明），不重审未使用的词。
4. **最终汇总与渲染**：

```text
python3 SKILL/scripts/listing_quality.py check --profile RUN/01_product_profile.json --listing RUN/07_listing.json --qa RUN/06_qa.json --review RUN/08_semantic_review.json --backend RUN/08_backend_validation.json --output RUN/08_validation.json
python3 SKILL/scripts/render_listing.py --run-dir RUN
```

**修订上限：** 第 8 步中任何 error、fail 或后端失败，全局最多修复 2 轮。修复后只重跑受影响的步骤（backend 和 review 都会复用未变部分）。2 轮后仍未解决，就交付现有结果，并列出未解决项。网络、权限或事实缺失的问题不要循环重试。

交付物：
- 07_listing.md：纯文案和中文策划。单品章节依次为 Title、Item Highlight、Bullet Points、Description、Search Terms、后台属性建议、附图策划、A+ 整体策划、买家问题覆盖清单。系列先写父体和全部子体，再写共用正文和差异。
- report.html：严格沿用既定的七章节版式，不新增导航或验收面板。关键词覆盖和可解锁流量放在"标题核心词"章节的卡片里。
- 只有全部子体和全部验收都通过，才能标"整组完成"。

## 失败与交付说明

失败时说明阶段、子体或字段、原因和下一步，不依赖缺失信息的部分继续整理，不伪造完整结果。最终固定提供 07_listing.md、07_listing.json、report.html 三个链接，并简述子体总数、验收状态、待补事实和可解锁流量。报告能证明内容和检查过程，不能证明 Amazon 已收录、排名会提升或 AI 必然推荐。
