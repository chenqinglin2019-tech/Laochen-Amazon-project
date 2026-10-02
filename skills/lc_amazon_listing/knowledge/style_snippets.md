# 写法参考（演示用，不是本品事实）

只学结构、长度和信息密度，不抄数值。示例产品的已确认事实如下（均为演示假设）：
- 天鹅造型透明玻璃单枝花瓶，高 15.24 cm、宽 7.62 cm
- 可插 1 枝鲜花或干花，用于书架、书桌、餐桌
- 手洗
- 附 1 个礼盒（accessory_count=1）
- 用户确认可作为乔迁或母亲节礼物

## intent_map（01 画像）

```json
[{"relation": "function", "expression": "single stem", "fact_ids": ["use"]},
 {"relation": "location", "expression": "bookshelf, desk or dining table", "fact_ids": ["use"]},
 {"relation": "activity", "expression": "fresh or dried flowers", "fact_ids": ["use"]},
 {"relation": "season", "expression": "housewarming or Mother's Day gift", "fact_ids": ["gift"]},
 {"relation": "product_type", "expression": "bud vase", "fact_ids": ["identity"]}]
```

## 意图组判定（03_keyword_groups.json，节选）

```json
{"reviewer": "model-first-pass",
 "groups": {
  "bud-vase-core": {"decision": "eligible", "reason_code": "identity", "role": "identity", "label": "high",
    "reason": "完整对象均为单枝小花瓶，与本品身份一致；词序或单复数不同不改变意图。",
    "query_intent": "寻找插单枝花的小花瓶", "evidence": "product_identity；use 事实",
    "fact_ids": ["use"], "identity_basis": true, "applies_to": ["all"],
    "keywords": ["bud vase", "small bud vases", "single flower vase", "vase for single stem"]},
  "bulk-wedding": {"decision": "deferred", "reason_code": "unknown_fact", "role": "intent", "label": "relevant",
    "reason": "批量婚礼桌花需要多件装，本品件数之外的婚礼用途未确认。", "query_intent": "批量采购婚礼桌面小花瓶",
    "evidence": "只确认单件和桌面用途", "fact_ids": ["use"], "applies_to": ["all"],
    "promotion_condition": "确认是否提供多件装或婚礼用途", "keywords": ["bud vases in bulk for wedding"]}},
 "overrides": {}}
```

## US 单品

**Title（73 字符）**
`Swan Glass Bud Vase, 6 in Clear Single Flower Vase for Shelf, Desk, Table`

**Item Highlight（≤125）**
`Holds one fresh or dried stem; gift-boxed for housewarming or Mother's Day`

**Bullets（每条约 150–250 字符）**
- `【SWAN SILHOUETTE】The clear glass body is shaped like a swan, so a single stem reads as a small sculpture on a bookshelf, desk or dining table instead of a plain jar.`
- `【SIZED FOR ONE STEM】At 6 in tall and 3 in wide, the bud vase holds one fresh or dried flower, a eucalyptus sprig or a dried pampas stem without crowding a narrow shelf.`
- `【CLEAR GLASS】Transparent glass keeps the stem and water line visible, so you can see when to refresh the water and the vase matches any color of flower.`
- `【READY TO GIVE】Arrives in a gift box, making it a simple housewarming or Mother's Day gift for someone who keeps fresh flowers at home.`
- `【EASY CARE】Hand wash with warm water and a narrow bottle brush, then dry upside down; the smooth glass wipes clean between stems, so the vase stays clear for every new flower.`

**Description**
`This swan glass bud vase holds one fresh or dried flower stem. It stands 6 in tall and 3 in wide, small enough for a bookshelf, office desk or dining table. The clear glass shows the stem and water level. It comes in a gift box. Hand wash only.`

**Search Terms（196 字节；不重复标题中的词，也不重复 Highlight 中已有的词）**
`centerpiece minimalist floral vessel dried stem holder eucalyptus pampas tabletop decor bedroom nightstand office bathroom counter mantel accent present boyfriend girlfriend glassware small modern`

（只写 eligible 词；示例中的每个词都假设已经过筛词，且有事实支持。）

**attribute_suggestions**

```json
[{"attribute": "item_type_name", "value": "Bud Vase", "fact_ids": ["identity"]},
 {"attribute": "material", "value": "Glass", "fact_ids": ["material"]},
 {"attribute": "item_height", "value": "6 in", "measurement_ids": ["height"]},
 {"attribute": "included_components", "value": "Vase, Gift Box", "fact_ids": ["gift_box"]},
 {"attribute": "occasion", "value": "Housewarming, Mother's Day", "fact_ids": ["gift"]}]
```

**buyer_question_coverage（至少 6 项）**
每项写一行：
- What is it made of? → 五点 3
- How big is it? → 五点 2、长描
- Where can I put it? → 标题、五点 1
- Is it a good gift? → Highlight、五点 4
- How do I clean it? → 五点 5
- Is it dishwasher safe? → not_claimed（未提供事实）

## 反例（都会被检查或复审拦下）

- `Swan Vase!! Best Vase Vase Vase for Flowers`：含禁用字符；同一个词超过 2 次；用了主观词。
- 后台词 `Swan Glass Bud Vase, Clear`：重复了标题中的词；含大写和标点。
- `Fits all flowers, unbreakable`：没有事实依据。
- 五点只写 `【CARE】Hand wash.`：浪费可索引空间，也没回答买家问题。
