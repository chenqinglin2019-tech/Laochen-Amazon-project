# 单细分 Flyfus 评论与 Alexa/Rufus 研究信号

按冻结的评论与问答范围使用 Flyfus，不设置本次 Flyfus points 上限。保留 `scripts/flyfus_client.py` 的配置路径、0600 权限、环境变量优先级、Bearer 请求头、端点、逐请求账本、回执、异常状态和恢复账本；不得为单细分改写鉴权或接口接入。

## 冻结名单

先运行 `scripts/demand_insight_v5.py plan-single-segment --input <INPUT.json> --output <RUN_DIR>/single_segment_sampling_plan.json`，或使用 `single_segment_contract.py` 已生成的同名计划。

- 评论：完整商品清单按同一销量统计期降序，销量并列按 ASIN，冻结前50候选；默认先采前5。当前批次处理完且存在实际证据缺口时，依次启用下一ASIN，最多第50名。每ASIN最多1,000个原始唯一review ID。评论4,000、社媒2,000、总有效6,000均为参考目标，不强制来源分别达标。
- 关键词 Alexa：完整关键词清单按流量占比降序，文本并列排序，取前 10 个关键词。
- 商品 Alexa：复用评论的前 5 个 ASIN。

评论的1,000是跨页原始采样上限，不是有效数或单请求承诺。先首批探测并核对分页/计费合同。fetch-review-pages把每成功页写入OUTPUT.json.pages/page-NNNNNN.json，再推进下一页；后页失败前页仍可用。恢复由主Agent核对页回执和已有收费账本后指定安全起始页，不自动重发不确定收费请求。原始空、标准化空、分页停滞、上限、可靠末页、请求失败分别记录；异常不等于已采全部。

## API 与计数

既有端点不变：`POST /api/v2/product/review`、`POST /api/v2/product/question`、`POST /api/v2/keyword/question`。商品问答只按已有分页能力读取；关键词问答不假设分页。答案缺失、无关和请求失败分别记录，模型不得补写接口答案。

每个 ASIN 保留请求出现记录和唯一评论实体。站点内同一 review ID 出现在多个 ASIN 时保留全部来源关系，但需求统计只计一次。评论原始数、有效文字数、完成编码数分别披露；不能为凑有效文字突破任一 ASIN 的 1,000 原始上限。points 实际或不确定消费只记录，不作为停止条件。

Alexa/Rufus 问题和答案只作研究信号：用于发现选购维度、平台承诺、评论/社媒冲突和待验证假设；不进入消费者 VOC、作者、渠道、KANO 或需求占比。主动提问仍遵循既有浏览器登录态和问答恢复状态机，且不会因本 Skill 自动发起。

已有答案全部由Codex分批归纳，answer正文和recommendedProduct分别规范化；每条有分析、无关、空白或解析失败终态。采用结论绑定回执和需求/维度/方向，竞品声明分已独立核实、冲突、待核实，待核实含具体方法。重复答案可复用但保留原返回映射；无答案为资料受限，不以空集合通过。关键缺口只调用实际支持的接口；不支持自定义问题时转商品资料核验或原型测试，不宣称已向Alexa提问。

所有回执写在运行目录并脱敏。Flyfus points 与 ScrapeCreators credits 绝不折算；后端 Token 不能视为任一供应商的独立 Key。
