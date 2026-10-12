# Skill 边界

本 Skill 仅处理市场机会。消费者语料、评论、社媒、Alexa/Rufus、KANO、工作坊和产品建议均不在此入口执行。

必须保持原机会 CLI、二进制、配置路径、Token 读取、计费和失败处理不变。不得修改市场研究产物、原机会分析字段、分析阈值或排序。

`analyze-tags` 完成后才运行独立推荐层：`prepare` → Agent 写候选定义与多维组合审核 → `shortlist`（`run` 为兼容别名）直接选出 Top3（不足时如实输出，候补只记入 JSON）→ 用户为每个冻结市场提供 1 份关键词转化表和 1 份卖家精灵表 → `refine` 补充八项结论与进入建议，不重排、不淘汰。只读取明确项目的完整关键词、清洗后商品、标签、多维分析结果和用户提供的表格，不调用飞鱼 API、不重清洗或新增抓取商品。规则以 `references/niche_recommendation_contract.md` 为准。

两轮新增独立产物与 manifest 键，并生成新的初筛／复评 HTML；原报告不得覆盖。`niche_shortlist.json` 是唯一 Top3 来源（候补只作参考），报告保持原始 `two-round-competition-v1` 格式，最终 08 文件只能由复评写入。修改推荐层时须以哈希校验鉴权、Token 配置、API 文件及现有二进制保持不变。
