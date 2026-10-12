# 单细分执行契约

执行顺序以SKILL.md为入口，详细运行参数见references/consumer_voice_workflow.md，字段与计数见references/consumer_voice_contract.md。

默认执行scripts/consumer_voice_local_reprocess.py与scripts/consumer_all_history_report.py。六类语义任一命中（OR），无日期筛选，不输出置信度。已有看板时用--dashboard核验哈希，未交接则不需要看板。

1. 冻结完整输入与统计期；从完整关键词形成三个互补检索表达及支撑词。未完成检索计划不能自动截取前三词代替。
2. 社媒采集自动调度agent-reach与last30days，网页原始消费者表达计社媒；接口/工具摘要和非消费者资料单列。last30days时间窗保留为来源元数据，不改变全历史处理。
3. 评论先前5、每ASIN1,000原始ID，实际证据缺口驱动扩至前50；社媒试采200。4,000评论/2,000社媒/6,000总量均为参考目标，无须强制或豁免。成功页落盘后推进游标，错误与末页区分。
4. Python全量规则处理；疑难/冲突/未覆盖小批复核；规则结果分层抽检，系统错误回扫。不同原始记录不做语义去重；同一记录重复抓取不膨胀数量。rule_classified/model_reviewed与历史agent_reviewed明确区分。
5. Codex自动完成待执行复核和KANO；证据不足须已实际复核且单列。KANO仅具体need_id提及率>=3%，机会>=0.5%，全有效集合为分母。版本和证据哈希绑定结论；同中文名不自动合并。Alexa逐条归纳选购维度/竞品声明/验证并完成验收；未知不补造。
6. 十二独立角色七阶段工作坊保留实际回执，正式恰好三个方案须评审并核验完整商品池；不足返回修订。unknown不当缺失，成本估计/测试计划不当真实报价/测试。
7. 首采、十类查漏、处理、质量及三个方向均完成即可完整交付，数量无需达标。报告使用 `scripts/consumer_all_history_report.py` 和 HTML 1.5.0 固定母版，详细顺序与布局见 `references/consumer_report_layout_contract.md`。十章固定，Alexa紧随六类表达；前部先清洗漏斗再分渠道数量，四类产品详情采用两列卡片，各方向后分别展示竞品对标，最后展示运营/开发行动。先准备并导入带来源指纹的短摘要，再渲染；仅展示主要依据，完整原声与角色过程外置。新运行不得回退旧版报告生成器或事后拼接样例内容。

后端仍使用根目录config.json的backend_url/backend_token及原0600校验。第三方.env、Key优先级、供应商端点、认证头、账本、任务注册表、浏览器和问答恢复逻辑不变。新API示例只空值，不写真实凭据。

恢复遵循现有权限：planned/paused及中断running可安全续接；error必须现有显式retry入口，预留/不确定收费不重发。引用已完成页和已验收编码，不覆盖历史运行。修改Skill不自动采集。
