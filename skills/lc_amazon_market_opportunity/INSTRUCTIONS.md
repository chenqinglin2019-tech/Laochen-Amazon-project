# 细分市场机会分析执行契约

输入只能是已完成市场调研项目的明确根目录。读取 `project_manifest.json` 和既有市场研究产物，继承站点、Listing 语言和项目 ID；禁止扫描其他项目或覆盖既有市场研究结果。

## 阶段路由（每次进入项目先做）

先运行只读命令 `python3 <SKILL_ROOT>/tools/niche_recommendation.py status --project-root <PROJECT_ROOT>`，按返回的 `stage` 和 `next` 从当前阶段继续。已有产物的步骤不得重跑；尤其是基础分析完成后不得重跑 `fetch-roots`（计费）或重新打标，否则标签哈希改变、已冻结的 Top3 失效，用户已按 Top20 拉取的表格也会作废。

## 基础分析命令（原 CLI，二进制与参数不变）

`<BIN>` 为 `tools/bin/` 下与平台对应的 `market-opportunity-darwin-arm64`／`-darwin-amd64`／`-linux-amd64`／`-windows-amd64.exe`；`<R>`=`<PROJECT_ROOT>/market_research`，`<O>`=`<PROJECT_ROOT>/market_opportunity`。顺序为：

1. `<BIN> inspect-report <R>`
2. `<BIN> fetch-roots --report-dir <R> --output-dir <O>`（计费；生成 `02_keyword_roots.json`）
3. `<BIN> dimension-candidates --report-dir <R> --roots-file <O>/02_keyword_roots.json --output-dir <O>`
4. Agent 整理维度并请用户确认，写 `<O>/agent_dimensions.json`（`dimension_candidates[]` 含 `name`、`selected`、`agent_confirmed`、五项维度分、`dimension_score`、`reason`，另有 `rejected_dimensions`、`agent_trace`）
5. `<BIN> tagging-template --report-dir <R> --dimensions-file <O>/agent_dimensions.json --output-dir <O>`（生成 `04_tagging_workspace.json`，内含打标规则）
6. Agent 全量打标，写 `<O>/agent_listing_tags.json`：顶层含 `dimensions`、`review_summary`（`primary_fields`、`image_checked_count`、`product_url_checked_count`、`notes`）、`normalization_dictionary`、`unrecognized_samples`、`llm_calls`；`tags[]` 每项含 `asin`、`values`、`normalized_values`、`display_values`、`evidence`
7. `<BIN> analyze-tags --report-dir <R> --dimensions-file <O>/agent_dimensions.json --tags-file <O>/agent_listing_tags.json --output-dir <O>`

以上参数整理自二进制的用法提示与案例产物位置；若二进制报参数错误，以其提示为准并记录。每个 Listing 都按共享的固定维度与归一化字典打标，合并后交由原 CLI 做全量校验。

## 重试与循环上限

- `fetch-roots`：成功一次即可；网络超时或连接错误最多重试 1 次；鉴权、额度、参数错误不重试，停下并报告原文。
- 打标：每批约 100 个 Listing 写入一次中间结果，中断后跳过已完成 ASIN 继续；同一批最多重试 1 次。
- `analyze-tags` 校验失败：只修正报错的 ASIN；最多 3 轮，或连续 2 轮报错数未下降即停止并报告。
- 候选定义：先运行 `validate`，一次改完全部错误再重跑；输出 `stop_recommended=true` 时停止修改并报告。
- `refine` 输入错误属于用户数据问题：不自动重试，按报错说明哪份文件、缺什么；不得为此重跑粗筛。
- 同一会话内本 Skill 的脚本累计失败 8 次时停止，汇总已完成产物与缺口后报告。
- 以上上限中，`validate` 的轮次由脚本记录并提示；其余依赖执行纪律，没有运行层的硬性拦截。

机会看板保留既有总览、市场背景、条件性提醒、优先方向、单维度观察、机会信号矩阵、决策维度、有效维度透视、正式组合、小样本观察和剔除追溯。不得修改筛选阈值、排序、原看板模板或项目产物键。

## Top3 粗筛与进一步分析

先运行 `prepare`，完成商机行清理与需求定义、多维组合审核（`combo_reviews`）、direct 核心词归属和必要补标；用 `validate` 检查到无错误后再运行 `shortlist`。粗筛会把商机表和候选定义复制到 `market_opportunity/frozen_inputs/`，第二轮只读这份副本。`run` 是兼容别名。粗筛直接从全部合格候选中精确选择最多 3 个不冲突市场，冻结候选 ID、排名、需求边界、核心词、成员与输入指纹。

粗筛只计算四项：供需指数 80%、竞争开放度 10%、新品进入证据 5%、需求承接规模 5%，商机表候选与多维组合候选都按本品类商品样本计算。供需指数使用去掉前 3 个爆款并向品类平均收缩后的稳健指数，母集与锚点不变；稳健指数低于 1.0 不能正式推荐。共享月销量占较小市场一半及以上的候选只能选一个。商机表指标只作需求证据与风险参考。公式见 `references/niche_recommendation_contract.md` §4。广告压力、关键词转化率、搜索增长和退货率都不参与粗筛；搜索增长及退货率只显示风险。缺项只使对应候选待验证，不得为凑数放宽门槛；正式市场不足 3 个时如实输出；不冲突的未达标市场作为候补只记入 `niche_shortlist.json`，不进入第二轮和报告。

粗筛报告必须给出 Top3 的完整成员、月销量 Top20 和可一键复制的 ASIN 列表，并提醒用户提供每个冻结市场各 2 个 Excel（Top3 时共 6 个）：每个市场 1 份细分市场关键词转化表及 1 份卖家精灵关键词表。两类表分工固定：关键词转化表（如 `关键词-20260905-….xlsx`）只取关键词、点击量和购买量，表内“最高出价／最低出价／建议出价”等出价列一律忽略；建议竞价只取自卖家精灵关键词反查表（如 `ExpandKeywords-US-<ASIN>-batch(20)-….xlsx`，以含 `Asin` 工作表识别）的 `PPC竞价` 列。转化表必须包含同周期关键词、点击量和购买量；卖家精灵表必须包含关键词、`PPC竞价`、`流量占比`和 `Asin` 工作表，其 ASIN 与该市场冻结 Top20 完全一致（不足 20 个时按实际数量）。项目原有关键词表只作历史核验，不能自动替代。

`refine --shortlist-result --keyword-input-xlsx <2×市场数 files>` 必须绑定成功的当前粗筛。它先以卖家精灵 `Asin` 工作表与冻结 Top20 ASIN 完全一致识别每份卖家精灵表所属市场；再以每份转化表关键词和卖家精灵累计流量占比前90%关键词的重叠率（至少80%）完成一对一配对。它只对冻结市场分别计算广告压力和八项结论，Top20 与成员沿用冻结结果，不重新评分、排序、淘汰或引入候选。只用同时有转化数据（点击量>0、购买量有效）和卖家精灵建议竞价（`PPC竞价`>0）的关键词：转化率为这些词的购买量之和／点击量之和，加权CPC为这些词的“词点击量／这些词点击量之和×词PPC竞价”累加；缺任一项的关键词整行忽略，不用其他来源（如关键词表推荐竞价）补齐。广告压力为加权CPC／（转化率×本市场完整有效商品算术均价）。不再识别或筛除关键词相关性。缺转化、缺竞价或商品字段时，仅相应广告项或结论显示无法判断；其他市场及粗筛 Top3 不受影响。

任一冻结商品、标签、完整关键词、商机表、候选定义、基础报告或推荐实现变化，须重新粗筛；进一步分析不得静默扩大边界。评分口径、边界、文件接口和失败处理详见 `references/niche_recommendation_contract.md`。

## 报告与交接

两阶段均创建新 HTML，原 HTML 不覆盖。在原正式组合折叠区之后、`h2#small`之前追加独立增量区，复用原报告格式。初筛展示 Top3；进一步分析展示固定 Top3 的关键词计算、Top20 和各市场独立八项结论。复制控件按排名顺序逐行复制 ASIN，不能把标题、排名或父 ASIN 混入。

`niche_shortlist.json` 是唯一 Top3 来源。`08_niche_recommendations.json` 与 `niche_recommendation_run.json` 只证明该粗筛 Top3 的进一步分析结果；下游核对阶段、规则版本、粗筛／进一步分析运行 ID、输入指纹、Top3 ID 与排名、成功回执和产物哈希后，直接使用冻结名单。不得从 `feature_distribution`、Listing 占比或供需指数重新选 Top3。
