# 制度适用表（jurisdiction-rights-v1）

`references/jurisdiction-rights.json` 是本表的机器可读版本，由 `scripts/jurisdiction_rights.py` 读取；创建任务时，表中涉及目标国家的条目被写入 `evidence.collections.institution_references`（证据 ID `EV-INST-<国家>-<权利类型>`）。审阅者只能引用这些条目把一个范围声明为 `scope_applicability.not_applicable`；收尾时程序对表中 `applicable:false` 的范围补默认声明（留痕 `applicability_basis=program_default`）。

它只回答一个问题：**该国家是否存在这种权利制度**。它不是检索结果，不说明任何具体权利的存在、效力或权属。每条附官方来源页面；`verification` 标明页面是否在核对日被实际打开（`page_read`）或仅由官方站点的索引列出（`listed_by_search`，jpo.go.jp 与 japaneselawtranslation.go.jp 拒绝自动抓取）。

| 国家 | 权利类型 | 是否存在 | 依据（官方来源） |
|---|---|---|---|
| US | 实用新型 | 否 | USPTO 专利基础：只有发明、外观、植物三种专利 |
| US | 未注册外观 | 否 | USPTO 外观专利说明；版权局船体设计登记（唯一的非专利外观保护，须登记）。未注册产品外观按商业外观范围处理 |
| EU | 实用新型 | 否 | WIPO：实用新型只在部分国家由国家法设立；欧盟无统一制度 |
| EU／FR／DE／IT／ES | 未注册外观 | 是 | Regulation (EU) 2026/715 第 12 条：自欧盟境内首次公开起 3 年（前身 6/2002 第 11 条，2026-06-30 失效） |
| FR | 实用新型 | 是 | INPI certificat d'utilité，最长 10 年 |
| DE | 实用新型 | 是 | DPMA Gebrauchsmuster |
| IT | 实用新型 | 是 | UIBM brevetto per modello di utilità，10 年 |
| ES | 实用新型 | 是 | OEPM modelo de utilidad，10 年 |
| GB | 实用新型 | 否 | UK IPO 概览：版权、专利、外观、商标 |
| GB | 未注册外观 | 是 | GOV.UK：补充未注册外观 3 年；未注册设计权 10／15 年 |
| JP | 实用新型 | 是 | JPO 実用新案 |
| JP | 未注册外观 | 是（形态模仿规则） | 不正当竞争防止法第 2 条第 1 款第 3 项、第 19 条第 1 款：首次销售起 3 年 |

更新表时：改 JSON、改本表、更新 `retrieved` 与 `verification`，并运行 `test_jurisdiction_rights.py`。
