# Skill 边界与不变量

只处理明确选择的一个细分市场；不重算Top3，不扫描猜测项目，不改上游、历史源库/看板/报告。新运行冻结输入和版本，旧运行只读兼容。

全历史、六类语义OR、不输出置信度。Python规则与模型复核共同进入经过校验的有效集合；未命中不直接排除。不同原始ID的相同观点不去重，已知作者另算，网页消费者声音归社媒，Alexa和研究资料单列。

PRD v2参考目标为Amazon有效评论4,000、社媒（含网页原声）2,000、总量6,000；均非硬门槛，无需数量豁免。完成首采、十类查漏、处理、质量及三个通过评审的方向可停止；补采依具体证据缺口。20/5/2和三批饱和仅历史信息。

鉴权相关路径/读取优先级/字段/权限/请求头/端点/脱敏/恢复逻辑完全不变。后端仍config.json；独立供应商API仍独立.env，不迁移、不回显、不互换Key，不自动读取新Cookie。收费不确定请求不自动重发；无预算上限不等于允许重复收费。

采集任务自动协作agent-reach与last30days；先读其Skill及实际所需参考，只执行已授权能力。修改Skill或离线分析不联网，不自动安装/注册。详细协议见references/consumer_voice_collection.md。

KANO仅分析提及率>=3%的具体need_id，机会仅分析>=0.5%，按全部有效VOC作分母且不隐式合并同名需求。Codex自动清完待执行复核和KANO；已审证据不足单列。实际十二角色工作坊须恰好三个通过方向；全池核验、Alexa分析、验证计划与渲染各有独立完成证据。

默认链路：references/consumer_voice_workflow.md、references/consumer_voice_contract.md、scripts/consumer_voice_local_reprocess.py、scripts/consumer_all_history_report.py。六类语义任一命中（OR），无日期筛选，不输出置信度。
