# 测试夹具

`fixtures/rating-v2/manifest.json` 是风险评级 v2 的统一夹具入口。运行器应按 manifest 顺序加载每一组 `input` 与 `expected`：

1. 将 `*.input.json` 原样传给 ruleset v2 评估器。
2. 对评估器结果做稳定化处理，移除时间戳、digest、文件路径等运行时字段。
3. 对 `*.expected.json` 的 `expected` 执行递归子集匹配；实际结果可以包含额外的审计字段。对象数组按 `module`、`candidate_id` 等稳定身份字段匹配，不按数组位置匹配。
4. `assertions.must_include_trace_codes` 中的代码必须出现在 decision trace；`must_not_include_trace_codes` 中的代码不得出现。
5. `assertions.counts` 用于校验去重前后计数，不能通过省略原始候选来伪造聚类结果。

所有输入固定使用 `schema_version=2.0` 与 `ruleset_version=2.0`，并且必须恰好包含以下 8 个唯一正式模块：

- `appearance_design`
- `utility_patent`
- `pending_patent`
- `word_mark`
- `figurative_mark`
- `trade_dress`
- `copyright_creative_ip`
- `enforcement_public_signals`

夹具中的 `reasoning` 只解释事实，不作为评级依据；测试运行器必须仅根据结构化候选、模块事实、覆盖状态和复审冲突计算结果。

Coverage gap 必须显式携带 `blocking`；评级事实冲突使用 `status` 表示 `unresolved` 或已解决状态。缺少这两个字段应按输入契约错误处理。

运行全部回归：

```bash
node --test tests/ipr-risk-v2.test.mjs
```

除 10 组评级夹具外，测试还覆盖 legacy 迁移、冻结源清单、官方/版权核验录入、二审事实重算、草稿徽章、正式报告重算与 release gate。商品、查询、账本、覆盖、截图、版权证明或 Assessment 任一工件在封存后变化，正式发布必须失败。
