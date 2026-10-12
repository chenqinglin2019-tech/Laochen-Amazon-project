# 社媒、网页与协作采集

## 范围与计数

单细分社媒2,000、Amazon评论4,000、总有效6,000均为参考目标，先200社媒试采，无3,000上界。数量不足不阻断交付：完成首采、十类查漏、全量处理、质量及三个评审方向即可停止，无需豁免。来源集中度和主题稳定性用于披露，不做删除记录或硬门槛。

真实用户评论、原创提问、非推广第一人称体验视频和网页均可纳入。网页统一进资料池；论坛发言、个人体验文章、问答按原始表达计social。品牌/规格/编辑综述保留research_signal，搜索摘要或模型摘要不计声音。全文的一多个段落不增加声音，其下不同原始评论分别计数。不同作者同观点、同作者不同留言均保留；同一发言经多工具重复抓取不多计。

## 自动协作协议

正式采集/补采时无需用户再次点名，主Agent必须自动读取并使用：

- agent-reach：当前安装入口 /Users/laochen/.agents/skills/agent-reach/SKILL.md。多后端先doctor --json，按active_backend选择；读取search/social/web/video中本次实际需要的文档。负责网页搜索、原帖/评论、论坛/博客/视频原文和上下文获取。
- last30days：当前安装入口 /Users/laochen/.codex/skills/last30days/SKILL.md。按该版本预检和query plan调用真实scripts/last30days.py，使用其agent机器输出例外获取结构化结果；不传不存在的CLI --agent。保留真实source_status与时间窗，不冒称失败来源无讨论。
- 继续使用已有ScrapeCreators抓取深层评论/回复；Flyfus仍负责Amazon评论与问答。

安装位置变化时由当前可用Skill目录定位，不凭空假定命令。last30days要求Python3.12+；能力缺失、初次配置或Cookie授权需求记blocked并询问必要授权，不自动安装/注册/购买或读取新Cookie。不共享不同供应商密钥；不改外部Skill及其鉴权来源。更新Skill、只读复算不触发研究引擎。

两个Skill产物先保存在各自允许的位置，再按明确返回路径导入本运行；不扫描猜测最新产物。记录companion任务、版本、实际查询、后端、原文件路径/哈希、source_window、成功/失败/零返回与消费。队列planned不等于执行成功；blocked不是来源耗尽。

last30days只补近期视角，默认30天窗口须披露；不删除此前保存的历史原声。其热度分数/聚类/摘要只作发现线索，不作为VOC数量或KANO票数。只拿到高亮时回取完整原文，不以截取段冒充完整记录。

## 检索计划

从完整关键词归纳主体、规格/空间限制、用途、场景，选择三个自然互补表达；保存supporting_keywords、intent、reason、false_positive_scope及planner_version。参见input_contract.md。紧凑电脑桌示例为small computer desk、small office desk、desk for small spaces；不是其他品类固定检索词。

三层：3裸表达→简短意图扩展→原声缺口驱动补查。保留选购使用/问题改进，并覆盖任务结果、具体限制、重复动作、取舍、未买停用、凑合替代、满意收益、发生条件、生活共用、情绪秩序十类线索。不能把一串意图强塞给所有平台。发现原帖后获取可访问评论，不按搜索意图词筛掉未命中的留言。

## 原文导入

collector的companion任务由Agent实际调度后导入，不自行运行任意外部命令。导入保留platform、content_id或url、exact_text、author、父上下文、evidence_kind=consumer_original、collector_skill和source_window。网页platform=web时必须有可验证直链，站点不同的原生ID/作者不相混。research_signal/model_summary分别保存，不计有效候选。后续还必须通过统一相关性与编码校验，不是标consumer_original即可有效。

## 分页、费用与停止

成功页先保存回执再推进游标。原始空、规范化空、无新增、可靠末页、超时/限流/鉴权失败分别记录。保留既有重试和收费不确定保护；不改Key、认证头、端点、预算账本及登录态。不设置本任务credits cap，但未授权的新付费源不得自动开通。

优先处理存量→补上下文→补同义/任务/条件→补反证/独立讨论→补深层回复。每次补查记录影响纳排、KANO或方向的具体缺口、查询、来源和结果，不因数量差额补采。十类逐类记成功/失败/未执行/历史不可追溯，不能从旧原声倒推发现来源。单来源达参考目标可暂停扩量，最终停止还需业务完成。单讨论/作者/平台集中需披露，不删真声“调比例”。
