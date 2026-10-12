# 单细分输入与产物契约

## 接收 JSON

`scripts/single_segment_contract.py --input <INPUT.json> --output-dir <RUN_DIR>` 只接受一个明确细分：

```json
{
  "schema_version": "single-segment-input-1.0",
  "project": {"project_id": "optional", "marketplace": "US", "language": "en"},
  "selected_segment": {"id": "optional-stable-id", "name": "必填细分名称", "definition": "可选边界"},
  "sales_stat_period": "同一统计期",
  "products": [{"asin": "必填", "sales": 123, "...": "保留上游商品详情"}],
  "keywords": [{"keyword": "必填", "traffic_share": 0.12, "...": "保留上游关键词详情"}]
}
```

商品可使用 `sales`、`units_sold` 或 `monthly_sales`；关键词可使用 `traffic_share`、`traffic_ratio` 或 `traffic_percent`。同一 ASIN、同一关键词不可重复；全部商品必须有同一销量统计期。字段不足以排序或确定细分边界时停止并请求补充，不猜测。

## 初始检索规划

输入另附`search_plan`，包含`planner_version`及恰好三个`expressions`。每个表达包含：`expression`（检索用表达）、`supporting_keywords`（原关键词列表中的支持词）、`intent`（互补检索目的）、`reason`（商品核心特征依据）、`false_positive_scope`（容易误采的范围）。主Agent先读取完整关键词列表再总结，不能将细分名称与关键词拼接后机械取前三。

没有有效规划时返回`planning_required`，补齐后再采集；示例品类或历史项目不能充当其他运行的默认规划。agent-reach和last30days沿用该规划及扩展意图，不各自改写研究边界。

## 冻结产物与目标

新运行目录生成并保留：

- `single_segment_input_snapshot.json`：规范化输入、内容哈希和来源引用。
- `single_segment_sampling_plan.json`：评论候选的销量前 50 ASIN（默认先启用前 5）、流量前 10 关键词、社媒目标、完整商品池摘要及停止规则。
- `selected_segments.json`：单细分兼容选择文件，供采集器和离线重处理使用。

完整竞品池保留ASIN、销量、统计期及商品详情，供开发阶段核验，不只保留前50个。v2参考目标为Amazon评论4,000条、社媒（含网页消费者原声）2,000条、总量6,000条；不强制达到。首采、十类查漏、已采数据处理、质量复核和三个方向均完成即可停止，数量差额不自动扩量。

输入快照变化、细分变化或统计期变化必须新建运行；不得混用旧样本或覆盖上游文件、旧报告、源数据库、看板和 manifest 既有键。旧 Top3 入口只保留历史读取兼容，不是新模式输入。
