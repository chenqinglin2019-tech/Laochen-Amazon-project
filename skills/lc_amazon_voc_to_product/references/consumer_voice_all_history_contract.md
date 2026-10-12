# 全历史契约兼容入口

新运行使用单细分输入与 `references/consumer_voice_workflow.md`、`references/consumer_voice_contract.md`。全历史仍表示指定任务已保存语料的无日期筛选处理，不表示穷尽互联网；六类语义任一命中（OR），不输出置信度。

旧 Top3 运行和 `3.0.0-all-history` 产物继续读取兼容，但不能用本兼容入口恢复全品类采集、固定时间窗或旧 Top3 选择。新单细分运行只允许 `selected_segment_all_history` 作用域。
