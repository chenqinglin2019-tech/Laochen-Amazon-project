# 处置规则（compliance-review-v1）

## 候选类型
- `triggered`：画像满足规则条件。通常判 applies；如果画像本身写错了，回到画像修改后重新 match。
- `possible`：规则取决于画像里未知的属性（`_unknown` 列出）。能从图片/资料确认的，先补画像再 match；确认不了判 needs_info，并写出要问用户的问题。
- `keyword_flag`：标题/五点里出现了该规则的强关键词，但画像没有触发。核对后：确实相关→改画像或判 applies；误报→not_applicable + keyword_false_positive，说明误报原因（例如 "knife sharpener" 不是刀）。
- `general`：所有商品都要遵守的通用义务（如欧盟 GPSR），不需要处置，报告单列。

- 带 `_check` 提示的候选是「针对具体物品的禁令」（如棕榈叶餐具、信号干扰器、某类刀具）：产品族落在规则范围内不代表适用，先核对商品是否就是规则所说的物品；不是就判 not_applicable（different_product_type），并写一句理由。
- `_check` 也可能是另外三种提示，照提示做：
  - 「该规则只禁止这种情况：…」：禁令只针对某种情况（过期、含石棉、序列号被篡改、未获许可的药品成分等）。资料显示商品属于这种情况判 applies；没有任何迹象判 not_applicable（condition_not_met），reason_zh 写明依据（例如「全新商品，成分表无该物质」）；有迹象但不能确定判 needs_info。
  - 「只因文案宣称触发」：系统已把它降为合规级，新 Listing 会禁止该宣称。原文案确有该宣称就判 applies。
  - 「…起生效」：尚未生效，只作提醒。适用就判 applies，不影响结论。

## 三种决定
| 决定 | 必填 | 码 |
|---|---|---|
| applies | codes、reason_zh、evidence | family_match / attribute_match / claim_present / keyword_confirmed / visual_confirmed |
| not_applicable | codes、reason_zh、evidence | different_product_type / attribute_absent_verified / claim_absent / keyword_false_positive / condition_not_met / exemption_applies / duplicate_of_other_rule |
| needs_info | reason_zh、question_zh | — |

- 严重度为禁售或需审核的规则，判 not_applicable 只能用：different_product_type、attribute_absent_verified、keyword_false_positive、condition_not_met、exemption_applies。
- possible 候选的未知属性不能用 attribute_absent_verified 排除。
- 证据引用：`title`、`bullet:N`、`description`、`notes`、`image:img-N`、`user:<字段>`。必须是本任务真实存在的。
- 分数、相似度、同类产品别人在卖，都不是排除理由。

## 站点置信度（sites[]）
- high：关键属性都有资料或图片直接证明。
- medium：有推断成分，或有一两个次要属性未知。
- low：主要靠推断，或图片看不清。
- 程序还会按规则自动封顶（属性未知、没看图、未查 SP-API 等），以低者为准。

## 结论怎么来（程序计算，你改不了）
- 站点结论取 applies 规则里最严重的一级：禁售 > 需审核/许可 > 需合规资料 > 未发现特殊限制。
- 有比当前结论更严重的 needs_info，结论显示「信息不足」，报告为草稿。
- 未完成核验的禁售规则即使 applies，也只会显示为待补信息。
- FBA：命中 FBA 禁运规则→FBA 禁运；命中危险品规则→需危险品审核；电池、液体、喷雾、易燃、腐蚀、磁铁任一未知→FBA 情况未知。
