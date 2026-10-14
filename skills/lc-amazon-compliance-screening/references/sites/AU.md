# 澳大利亚站（amazon.com.au）禁限售与合规要求

> 规则包版本：draft · 调研日期：2026-10-10 · 本文描述亚马逊平台政策和当地法规要求，不构成法律意见。
> 每条结论后用 [SRC-…] 标注来源（见 rules/sources/AU.yaml），用 [R:规则ID] 关联机读规则（rules/sites/AU.yaml）。
> 来源级别：S1 亚马逊官方 · S2 政府官方 · S3 二手。只有 S3 支撑的结论标注「（二手来源，待核）」。
> 亚马逊帮助页通过 r.jina.ai 渲染抓取（快照见 policy/snapshots/AU/）；立法文本经 Federal Register of Legislation（legislation.gov.au）读取；部分政府网页经 jina 抓取并存快照。

## 速览：中国卖家最需要知道的 10 件事

1. **很多品类境外卖家直接做不了**：酒类须澳洲酒牌且卖家须在澳经营 [R:AU-L2-ALCOHOL-001]；活体植物、植物产品和种子不允许境外卖家销售 [R:AU-L1-PLANT-001]；肥料仅限澳洲境内卖家 [R:AU-L1-FERTILISER-001]；境外卖家不得销售整只动物（含干制/冻干） [R:AU-L1-ANIMAL-002]。[SRC-AU-AMZ-G201737480] [SRC-AU-AMZ-GD85NFMCQF2KNM2N]
2. **澳洲站禁售 18650/21700 等圆柱可充电锂电池及含此类电芯的产品**，范围扩展到任何 ≥3.0 V 的圆柱可充电电池 [R:AU-L1-ELEC-002] [SRC-AU-AMZ-G200164510] [SRC-AU-AMZ-G2HSXA2KM59YX5AT] [SRC-AU-AMZ-G7PAP6BJAUXRM4LH] [SRC-AU-AMZ-GRLKLZ6WQ9R259LC]。
3. **市电电器必须走 EESS**：责任供应商必须是澳洲/新西兰实体（海外公司不能注册），Level 3 产品（插头、旅行转换器、充电器/电源适配器、电热毯、电暖器、电水壶、美发器、按摩器等 62 类）须澳新 RECS 证书 + 注册 + RCM；亚马逊要求提交 CoC 和 EESS 设备注册号 [R:AU-L5-EESS-001] [R:AU-L5-EESS-002] [R:AU-L3-ELEC-001]。
4. **ACCC 47 项强制标准逐项落地**：亚马逊 GLV5ESPKUCWX9KPS 页列 47 项（纽扣电池、36 个月以下玩具、婴儿睡眠产品、婴儿车、太阳镜、易倾倒家具等），大部分品类有单独合规页要求提交 ISO 17025/NATA/CNAS/ILAC MRA 实验室报告和警示语图片 [R:AU-L3-ACCC-001]～[R:AU-L3-ACCC-047] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS]。
5. **亚马逊“产品安全限制清单”比法律更严**：婴儿床围、睡眠定位器、加重睡眠产品、带帽绳童装、琥珀磨牙链、吸水珠（面向儿童）、美人鱼尾泳衣、UVC 消毒器、凝胶/液体燃料火盆、电热水袋、直插式迷你暖风机、带禁止特征的旅行转换器、汽车座椅加热垫、增高座椅等一律禁售 [R:AU-L1-CHILD-001] [R:AU-L1-CHILD-002] [R:AU-L1-ELEC-005] [R:AU-L1-UVC-001] [R:AU-L1-FIREPIT-001] [SRC-AU-AMZ-GRLKLZ6WQ9R259LC]。
6. **武器类几乎全禁**：枪支配件、仿真枪、水弹枪、弹弓、弩、剑、弹簧/蝴蝶/重力刀、指虎、甩棍、防狼喷雾、电击器、防弹衣均禁售 [R:AU-L1-WEAPON-001]～[R:AU-L1-WEAPON-004]；海关附表 13 还要求“辅助开启折刀”须部长许可才能进口 [R:AU-L6-CUSTOMS-001]。
7. **电子烟、尼古丁、CBD 全禁**：2024 年电子烟改革后只有药房可售电子烟；尼古丁袋自 2026-07-24 起非 ARTG 不得进口或供应 [R:AU-L5-VAPE-001] [R:AU-L1-CBD-001]。
8. **治疗/抗菌/驱虫宣称会触发 TGA 或 APVMA**：治疗性宣称须 ARTG（澳洲申办者），驱虫/杀虫（含人体驱蚊）须 APVMA 注册，消毒剂作杀病毒等特定宣称须 ARTG [R:AU-L5-TGA-001] [R:AU-L5-APVMA-001] [R:AU-L5-TGA-004]。
9. **进口化妆品要先注册 AICIS**（无数量门槛，海外直发企业需 ARBN） [R:AU-L5-AICIS-001]；**石棉零容忍**，蜡笔、彩沙、刹车片等须带“未检出”报告进口 [R:AU-L6-ASBESTOS-001]。
10. **FBA 限制**：仅限量包装的 2.1/2.2/3/4.1/5.1/5.2/6.1/8/9 类危险品可入仓；锂离子电池 >100 Wh（电芯 >20 Wh）拒收；超 116×116×102 cm 或 >23 kg、真空压缩床垫、轮胎、不能在全澳合法销售的商品不能 FBA [R:AU-L4-DG-001] [R:AU-L4-DG-002] [R:AU-L4-FBA-002]。

## A. 禁售清单（L1）

澳洲站受限商品总页 G200164330 列出约 40 个受限类目页（与美国站不同，澳洲站有完整清单），另有“产品安全限制清单” GRLKLZ6WQ9R259LC 汇总因安全原因不得销售的商品，以及若干合规页中的“不能销售”部分 [SRC-AU-AMZ-G200164330] [SRC-AU-AMZ-GRLKLZ6WQ9R259LC]。违规可能导致立即暂停或终止销售权限、FBA 库存被处置且不赔偿 [SRC-AU-AMZ-G200164330]。申诉须说明违规内容、原因、纠正措施与预防措施四要素 [SRC-AU-AMZ-G201567350]。

| 类别 | 亚马逊页面（G 编号） | 禁止销售的典型商品 | 例外/允许销售的情况 | 规则ID |
| --- | --- | --- | --- | --- |
| 召回商品 | G200164750 | 被召回商品禁止上架 | 上架前在 ACCC Product Safety Australia 召回数据库（productsafety.gov.au/recalls）检索品牌/型号；已召回批次须下架并按召回方案处理。 | [R:AU-L1-RECALL-001] [SRC-AU-AMZ-G200164750] [SRC-AU-GOV-PSA-RECALLS] |
| 成人用品 | G200339940 | 露骨性图像、涉及未成年人的性暗示内容、带头部的性爱娃娃禁售 | 例外：充气娃娃（blow-up doll）及无头性爱娃娃按成人用品规则（AU-L3-ADULT-001）销售。 | [R:AU-L1-ADULT-001] [SRC-AU-AMZ-G200339940] |
| 汽车与动力运动 | G200164410 | 有色前大灯罩（透光率低于 85%）禁售（ACCC 永久禁令） | 前大灯罩须保证 ≥ 85% 光透射率；Photo blocker 类喷剂、车牌遮挡罩一律禁售。 | [R:AU-L1-AUTO-002] [SRC-AU-AMZ-G200164410] [SRC-AU-GOV-LEG-F2010L03297] [SRC-AU-GOV-PSA-BANS] |
| 汽车与动力运动 | G200164410、GRLKLZ6WQ9R259LC | 需注册的机动车、排放破解装置、气囊/安全带部件、里程表篡改等汽配禁售 | 允许：新的合规轮胎、轮毂、车用电池、合规替换件、养护工具、符合排放规定的设备。 | [R:AU-L1-AUTO-001] [SRC-AU-AMZ-G200164410] [SRC-AU-AMZ-GRLKLZ6WQ9R259LC] |
| 信号干扰器 | G200164410 | 信号干扰器（手机/GPS/Wi-Fi/雷达/激光干扰器）禁售 | 包括手机、GPS、PCS、Wi-Fi、雷达、激光干扰器；ACMA 禁止设备声明适用。 | [R:AU-L1-JAMMER-001] [SRC-AU-AMZ-G200164410] [SRC-AU-GOV-LEG-F2023L00214] |
| 食品饮料 | G200164550、GRLKLZ6WQ9R259LC | 未注册婴儿配方奶粉、HiPP 奶粉、含魔芋迷你果冻杯、中国产含肉食品、槟榔等食品禁售 | 中国产含肉零食（肉松、肉干、香肠、含肉方便面调料包等）同时受生物安全进口限制，见 AU-L6-BIOSEC-003。 | [R:AU-L1-FOOD-001] [SRC-AU-AMZ-G200164550] [SRC-AU-GOV-LEG-F2010L03298] [SRC-AU-GOV-PSA-BANS] [SRC-AU-AMZ-GRLKLZ6WQ9R259LC] |
| 酒类 | G200164340、GM9BQPTJNXU2KEDW | 无澳洲酒类许可证的酒精饮料、酒牌转让、21+营销商品、封装原酒精商品禁售 | 境外卖家一般无法满足“澳洲本地经营+酒牌+年龄核验承运商”条件（见 AU-L2-ALCOHOL-001）。 | [R:AU-L1-ALCOHOL-001] [SRC-AU-AMZ-G200164340] [SRC-AU-AMZ-GM9BQPTJNXU2KEDW] |
| 动物及动物制品 | G200164370 | 濒危/CITES 物种制品、象牙、猫狗制品、海豹皮、熊胆、鲨鱼/鲸/海豚成分禁售 | 合成或实验室培育替代品、植物基替代品不在此限；CITES 物种进口另需许可（见 AU-L6-CITES-001）。 | [R:AU-L1-ANIMAL-001] [SRC-AU-AMZ-G200164370] |
| 动物及动物制品 | G200164370 | 活体动物、境外卖家销售整只动物（含干制/冷冻/防腐）、动物粪尿、“植物害虫”昆虫禁售 | 动物制品进口另受 DAFF 生物安全管制（见 AU-L6-BIOSEC-003）。 | [R:AU-L1-ANIMAL-002] [SRC-AU-AMZ-G200164370] |
| 动物及动物制品 | G200164370 | 电击/项圈电击器、尖刺/P 字链项圈、脊椎动物粘鼠板、Opera-house 捕捞网禁售 | 振动/声音类止吠器是否允许需逐案确认；昆虫粘板不在“脊椎动物”范围。 | [R:AU-L1-ANIMAL-003] [SRC-AU-AMZ-G200164370] [SRC-AU-GOV-LEG-F1996B03651] |
| 动物及动物制品 | G200164370、G200164490 | 人/动物疫苗、未经 APVMA 注册的宠物药（含驱虫、跳蚤/蜱虫药）、观赏鱼抗生素禁售 | 已获 APVMA 注册（标签带 APVMA 批准号）的宠物驱虫/跳蚤产品可销售，见 AU-L5-APVMA-002。 | [R:AU-L1-ANIMAL-004] [SRC-AU-AMZ-G200164370] [SRC-AU-AMZ-G200164490] |
| 化妆品/护肤/护发 | G200164470 | 处方类美妆、含禁用/超限成分的化妆品、皮肤用指甲花、高浓度牙齿美白产品禁售 | 牙齿美白产品过氧化氢 ≤ 6%、过氧化脲 ≤ 18% 才可考虑销售；化妆品不得宣称治疗疾病（否则按治疗用品管理，见 AU-L5-TGA-001）。 | [R:AU-L1-COSMETIC-001] [SRC-AU-AMZ-G200164470] |
| 化妆品/护肤/护发 | G200164470 | 过期、已开封/二手、非原厂密封、“tester/非卖品”、刮码、缺法定成分标签的化妆品禁售 | 法定成分标签要求见 AU-L3-ACCC-015（化妆品成分标签信息标准）。 | [R:AU-L1-COSMETIC-002] [SRC-AU-AMZ-G200164470] |
| 货币/礼品卡/邮票 | G200164450、G200164730 | 纸币、伪币、未标“Copy”的仿真/道具钞、礼品卡与现金等价物、证券、非货币化金银条禁售 | 允许：收藏钱币（需类目审核，见 AU-L2-COINS-001）、可作为法定货币的贵金属铸币（monetised bullion）。 | [R:AU-L1-CURRENCY-001] [SRC-AU-AMZ-G200164450] [SRC-AU-AMZ-G200164730] |
| 膳食补充剂 | G201829010 | 含未申报药物成分/禁用成分的补充剂、疾病治疗宣称、非英文标签补充剂禁售 | 允许：标签合规（名称、净含量、营养标签、配料表、制造/包装/分销商名称和地址，详情页同步展示）且无疾病宣称的补充剂；涉及治疗性宣称须先列入 ARTG（见 AU-L5-TGA-001）。 | [R:AU-L1-SUPP-001] [SRC-AU-AMZ-G201829010] |
| CBD/大麻 | G201829010、G200164490 | CBD/大麻素产品、含 THC 或树脂的大麻制品、可发芽大麻种子禁售 | 例外：不含 CBD 的冷榨大麻籽油（hemp seed oil）及符合 FSANZ 标准的大麻籽食品。 | [R:AU-L1-CBD-001] [SRC-AU-AMZ-G201829010] [SRC-AU-AMZ-G200164490] |
| 药品与管制物质 | G200164490 | 管制药物、毒品、致幻/精神活性植物及仿效毒品效果的产品禁售 | 依据《毒物标准》（Poisons Standard/SUSMP）附表 8、9 及 ODC 管制清单。 | [R:AU-L1-DRUGS-001] [SRC-AU-AMZ-G200164490] |
| 药品与管制物质 | G200164490 | 处方药、未经批准药物（含未获批 GLP-1）、麻黄碱/伪麻黄碱、麦角胺、螯合剂、未经批准的癌症/性病疗法禁售 | 非处方药（OTC）在澳洲同样须列入 ARTG 并有澳洲申办者，见 AU-L5-TGA-001。 | [R:AU-L1-DRUGS-002] [SRC-AU-AMZ-G200164490] |
| 吸毒用具 | G200164490 | 吸毒用具（水烟枪/bong、非烟草烟斗、研磨器、电子汽化器、笑气爆气器、压片机等）禁售 | 研磨器、Mylar 袋、胶囊灌装机等通用器具也可能被判定，需避免任何与毒品相关的描述/图片。 | [R:AU-L1-PARAPHERNALIA-001] [SRC-AU-AMZ-G200164490] [SRC-AU-GOV-LEG-F1996B03651] |
| 武器 | G200164950 | 枪支（含仿真枪、气枪、Airsoft/BB 枪、发令枪）、弹药及枪械零配件禁售 | 水弹枪（gel blaster）在多数州按枪支/仿真枪管理；玩具枪若外观逼真也可能被认定为仿真枪（见 AU-L5-WEAPON-002）。 | [R:AU-L1-WEAPON-001] [SRC-AU-AMZ-G200164950] |
| 武器 | G200164950 | 禁售刀具：弹簧刀/自动刀、蝴蝶刀、重力刀、匕首、推刀、伪装刀、指虎刀、飞刀、剑及暗藏刀剑 | 普通厨刀、手动折刀、工具刀仍受各州向未成年人售刀限制（见 AU-L5-WEAPON-001）；弹簧助开刀被亚马逊列入禁售。 | [R:AU-L1-WEAPON-002] [SRC-AU-AMZ-G200164950] |
| 武器 | G200164950 | 指虎、双节棍、警棍/甩棍、战术笔/Kubotan、弩、弹弓、吹箭、链鞭等格斗武器禁售 | 弹弓在部分州为禁止武器（如带臂托弹弓）；亚马逊 AU 一律禁售弹弓。 | [R:AU-L1-WEAPON-003] [SRC-AU-AMZ-G200164950] |
| 武器 | G200164950 | 防狼/辣椒喷雾、电击器/泰瑟枪、飞镖枪、防弹衣及防弹插板/头盔、军警专用装备禁售 | 允许：个人报警器、哨子、安全灯。电击器、OC 喷雾、防弹衣同时属《海关（禁止进口）条例》需许可进口物品，见 AU-L6-CUSTOMS-001。 | [R:AU-L1-WEAPON-004] [SRC-AU-AMZ-G200164950] |
| 爆炸物/烟花 | G200164950、G200164570 | 烟花爆竹、烟雾弹、信号弹、玩具枪火帽、拉炮、仙女棒、爆炸靶、仿真手雷等禁售 | 压缩空气式礼花筒（不含火药）是否允许需逐案确认；彩色烟雾类产品通常被归入烟雾弹禁售。 | [R:AU-L1-EXPLOSIVE-001] [SRC-AU-AMZ-G200164950] [SRC-AU-AMZ-G200164570] |
| 危险品 | G200164570、G200685320 | 含 BPA 产品、含汞产品（灯泡/体温计/汞电池）、四氯化碳、氢氟酸/硝酸、红磷、铝热剂、氰化物、PCB 等危险化学品禁售 | 食品接触塑料（尤其聚碳酸酯奶瓶/水杯）建议在详情页和检测报告中证明不含 BPA；不含汞的电池、可充电电池允许销售。 | [R:AU-L1-HAZMAT-001] [SRC-AU-AMZ-G200164570] [SRC-AU-AMZ-G200685320] |
| 危险品 | G200164570 | 娱乐/解压用小强磁及磁力珠套装（Buckyballs、Neocube 等）、磁吸鼻环/唇钉禁售 | 工业/冰箱贴等非娱乐用途磁铁需注意 ACCC 小型强磁铁禁令的磁通指数（flux index）与尺寸界限，见 AU-L5-BAN-001。 | [R:AU-L1-HAZMAT-002] [SRC-AU-AMZ-G200164570] [SRC-AU-GOV-LEG-F2012L02171] |
| 危险品 | G200164570、GRLKLZ6WQ9R259LC、GC277GB53473J65C、GEJ6L4MMBHVZGLND、G9LKRHDUQ5AV3ECD | 儿童充气颈圈、水上步行球、斗风筝线、军用防毒面具、可发射牙签的玩具弩禁售 | — | [R:AU-L1-HAZMAT-003] [SRC-AU-AMZ-G200164570] [SRC-AU-AMZ-GRLKLZ6WQ9R259LC] [SRC-AU-AMZ-GC277GB53473J65C] [SRC-AU-AMZ-GEJ6L4MMBHVZGLND] [SRC-AU-AMZ-G9LKRHDUQ5AV3ECD] |
| 人体部位与墓葬文物 | G200164590 | 人体器官/组织/体液、人类遗骸、原住民陪葬品、从原住民土地/战场取得的文物禁售 | 人发制品（假发）一般不在此列；复制品须在标题中注明 replica。 | [R:AU-L1-HUMAN-001] [SRC-AU-AMZ-G200164590] |
| 赌博彩票 | G200685250 | 彩票、投币老虎机及可改装投币的老虎机禁售 | — | [R:AU-L1-GAMBLING-001] [SRC-AU-AMZ-G200685250] |
| 婴儿自主喂养 | GRGM8BSET2LH6KTL、GRLKLZ6WQ9R259LC | 婴儿自主喂养产品（免手扶奶瓶架、自喂枕、推车/婴儿床奶瓶支架）禁售 | — | [R:AU-L1-INFANT-001] [SRC-AU-AMZ-GRGM8BSET2LH6KTL] [SRC-AU-GOV-PSA-SELF-FEEDING-BAN] [SRC-AU-GOV-LEG-F2026L00610] [SRC-AU-AMZ-GRLKLZ6WQ9R259LC] |
| 珠宝宝石 | G200166630 | 不合规贵金属印记、辐照宝石、非金伯利进程钻石、净度改善白钻、充玻璃红宝石禁售 | 贵金属成色印记须真实（如 925、750）；钻石须具金伯利进程合规来源。 | [R:AU-L1-JEWELRY-001] [SRC-AU-AMZ-G200166630] |
| 激光产品 | G201689020 | 功率超过 1 mW 的激光笔/激光指示器及“303”型激光产品禁售 | 进口手持激光笔 >1 mW 需海关许可（见 AU-L6-LASER-001）；在新州等州 >1 mW 激光笔属禁止武器。 | [R:AU-L1-LASER-001] [SRC-AU-AMZ-G201689020] |
| 照明 | G201997070 | 不符合能效标准的白炽灯泡禁售 | LED 灯泡/灯管属 GEMS 管制灯具时须先在 GEMS 注册（见 AU-L5-GEMS-001）。 | [R:AU-L1-LIGHTING-001] [SRC-AU-AMZ-G201997070] [SRC-AU-GOV-LEG-F1996B03651] |
| 开锁与盗窃工具 | G200164850 | 防盗标签解锁器、读卡盗刷器、遥控截码器、万能钥匙、序列号被去除的商品禁售 | 普通开锁练习工具（lock pick set）未被点名禁售，但可能被视为“用于非法活动”，需谨慎。 | [R:AU-L1-LOCKPICK-001] [SRC-AU-AMZ-G200164850] |
| 电子电器 | G200164510、GQQWCXM7GWCFKVVM | 不符合澳洲电气安全要求（插头、电压、认证、标识）的电器禁售 | 合规路径见 AU-L3-ELEC-001（EESS 注册、RCM、证书）与 AU-L5-EESS-001～003。 | [R:AU-L1-ELEC-001] [SRC-AU-AMZ-G200164510] [SRC-AU-AMZ-GQQWCXM7GWCFKVVM] |
| 电子电器 | G200164510、G2HSXA2KM59YX5AT、G7PAP6BJAUXRM4LH、GRLKLZ6WQ9R259LC | 18650/21700 等圆柱锂离子电芯及含此类电芯的产品禁售 | 内置 18650 电芯的手电筒、头灯、移动电源等同样受影响，需核实电芯型号。 | [R:AU-L1-ELEC-002] [SRC-AU-AMZ-G200164510] [SRC-AU-AMZ-G2HSXA2KM59YX5AT] [SRC-AU-AMZ-G7PAP6BJAUXRM4LH] [SRC-AU-AMZ-GRLKLZ6WQ9R259LC] |
| 电子电器 | G200164510 | 非 USB-IF 规范的 USB-C 线缆/转接头、手机信号放大器、雷达探测器、694–820 MHz 无线设备、CB 功放等禁售 | USB-C 产品应保留 USB-IF 规范符合性证据（如测试报告/认证编号）；无线麦克风须确认频段不在 694–820 MHz。 | [R:AU-L1-ELEC-003] [SRC-AU-AMZ-G200164510] [SRC-AU-GOV-LEG-F2021L01177] |
| 电子电器 | G200164510 | 盗版/破解类流媒体播放器、卫星/有线电视解码器、DVD 拷贝器、解锁区域码播放器、改解锁手机禁售 | 合规流媒体播放器需类目审核，见 AU-L2-STREAMING-001。 | [R:AU-L1-ELEC-004] [SRC-AU-AMZ-G200164510] |
| 其他受限商品 | G200685320 | 可拆侧板婴儿床、不合规烟雾/一氧化碳报警器、二手燃气接头、Magic Wine Decanter、Your Baby Can Read 等禁售 | 烟雾报警器须符合 AS 3786 等澳洲标准（各州建筑法规要求）；具体证明文件待核实。 | [R:AU-L1-OTHER-001] [SRC-AU-AMZ-G200685320] |
| 其他受限商品 | G200685320 | 仿冒执法/军警徽章证件、优惠券、活动门票、域名、数字下载码、盲盒（内容不明）、UPC/EAN 条码、教师版教材、邦联旗等禁售 | 盲盒类商品须在详情页清楚列明可能包含的全部内容，否则禁售。 | [R:AU-L1-OTHER-002] [SRC-AU-AMZ-G200685320] |
| 农药 | G202115120 | 未经 APVMA 注册的农药/驱虫产品（含超声波驱虫器、驱虫手环）、第二代抗凝血灭鼠剂禁售 | 注册且标签合规的农药可在获得亚马逊农药类目审核后销售（见 AU-L2-PESTICIDE-001、AU-L5-APVMA-001）。 | [R:AU-L1-PESTICIDE-001] [SRC-AU-AMZ-G202115120] |
| 植物种子 | G201737480 | 境外卖家不得销售任何活体植物、植物产品和种子；本地卖家不得销售有害/检疫/非法/危险植物 | 种子进口须符合 BICON 条件，见 AU-L6-BIOSEC-001。含种子的“种植套装”同样受影响。 | [R:AU-L1-PLANT-001] [SRC-AU-AMZ-G201737480] |
| 监控设备 | G200164870 | 窃听器、电话/通信截听设备、伪装成非录音物品的录音设备、偷拍（性目的）设备禁售 | 伪装成充电器、笔、钟表等物品的摄像头若带录音功能即落入禁售；纯视频隐藏摄像头可售。 | [R:AU-L1-SURVEIL-001] [SRC-AU-AMZ-G200164870] |
| 烟草 | G200164910 | 烟草及含烟草产品、带烟草品牌标识的商品，以及卷烟纸、卷烟机、空烟管、烟斗等吸烟配件禁售 | 烟草广告受《烟草广告禁止法 1992》限制；含烟草品牌标识的周边商品同样禁售。 | [R:AU-L1-TOBACCO-001] [SRC-AU-AMZ-G200164910] |
| 电子烟 | G200164910 | 电子烟、电子水烟/烟斗/雪茄、烟油、烟弹、雾化器、电池等全部配件（无论是否含尼古丁）禁售 | — | [R:AU-L1-VAPE-001] [SRC-AU-AMZ-G200164910] [SRC-AU-GOV-TGA-VAPES-JUL2024] |
| 果树防护网 | GLL2YRZB4BUQBSLM | 网眼大于 5 mm×5 mm 的果树/水果防护网禁售 | 详情页应写明网孔尺寸（mm），超过即禁售。 | [R:AU-L1-NETTING-001] [SRC-AU-AMZ-GLL2YRZB4BUQBSLM] |
| 保修与服务 | G200164930 | 延保、服务计划、退款保证、安装服务等服务类 listing 禁售（仅限预批准卖家，目前不接受申请） | — | [R:AU-L1-WARRANTY-001] [SRC-AU-AMZ-G200164930] |
| 卫浴排水 | GVVAHF4S3EZ7FPAY | 无 WaterMark 认证的接入供水的坐便盖洁身器、手持花洒喷枪等卫浴/排水产品，以及宣传可 DIY 安装的接饮用水洁身器禁售 | 认证路径见 AU-L5-WATERMARK-001；详情页须展示 WaterMark 标志或许可证信息（AU-L3-PLUMBING-001）。 | [R:AU-L1-PLUMBING-001] [SRC-AU-AMZ-GVVAHF4S3EZ7FPAY] |
| 肥料 | GD85NFMCQF2KNM2N | 肥料仅限澳洲境内卖家销售；不合规、非面向澳洲、限制使用或误导宣称的肥料禁售 | 本地卖家须符合州/领地肥料法规及《肥料描述与标签国家实务守则》。 | [R:AU-L1-FERTILISER-001] [SRC-AU-AMZ-GD85NFMCQF2KNM2N] |
| 一次性塑料 | GMMCLBZWLHDEWEKS | 一次性塑料餐具/吸管/搅拌棒/盘碗/杯盖/塑料棉签棒/塑料袋/泡沫餐盒/含塑料微珠个护品禁售 | 可重复使用塑料制品不在此列；“可降解/生物基”宣称不能豁免（氧化降解塑料明确禁售）。 | [R:AU-L1-PLASTIC-001] [SRC-AU-AMZ-GMMCLBZWLHDEWEKS] |
| 3G/非 VoLTE 设备 | GGA942GE8CSQ7KK5 | 仅支持 3G 或不支持 VoLTE 的手机、平板、智能手表、调制解调器、随身 Wi-Fi、医疗/紧急/跌倒报警器、物联网设备禁售 | 建议在详情页写明支持 VoLTE 及澳洲运营商频段；依据《电信（紧急呼叫服务）决定 2019》，运营商须对无法拨打 000 的设备通知并拒绝服务（运营商义务，法规未禁止零售 3G-only 设备，此禁售为亚马逊政策）。 | [R:AU-L1-3G-001] [SRC-AU-AMZ-GGA942GE8CSQ7KK5] [SRC-AU-GOV-LEG-F2019L01509] |
| 蹦床滑板车 | GAEKV7BNR2W6FGG3 | 无轮蹦床滑板车/蹦床滑板禁售 | — | [R:AU-L1-SCOOTER-001] [SRC-AU-AMZ-GAEKV7BNR2W6FGG3] |
| 带温度传感器婴儿浴盆 | G7A4NWJ8DH3KZTTL | 带温度传感器（及显示屏）的婴儿浴盆、婴儿洗澡座椅/支撑/浮圈禁售 | 普通浴盆/洗澡辅助器须符合 ACCC 婴儿洗澡辅助器强制标准，见 AU-L3-ACCC-002。 | [R:AU-L1-BATHTUB-001] [SRC-AU-AMZ-G7A4NWJ8DH3KZTTL] |
| 服装鞋履 | G200164430 | 二手服装和鞋履禁售（服装页另称服装鞋类仅限预批准卖家，与审核类目清单不一致） | — | [R:AU-L1-CLOTHING-001] [SRC-AU-AMZ-G200164430] |
| 儿童/婴幼儿产品（安全限制清单） | GRLKLZ6WQ9R259LC、G2E9DBAG4GYSQ5LT、GNU34E2V48PRHY84、GX44XMQX3ZKWRPZR、GKDFVJSUHPYTRHW3 | 婴儿床围（防撞护垫）、婴儿睡眠定位器、加重型婴幼儿睡眠产品、婴幼儿充气旅行床禁售 | — | [R:AU-L1-CHILD-001] [SRC-AU-AMZ-GRLKLZ6WQ9R259LC] [SRC-AU-AMZ-G2E9DBAG4GYSQ5LT] [SRC-AU-AMZ-GNU34E2V48PRHY84] [SRC-AU-AMZ-GX44XMQX3ZKWRPZR] [SRC-AU-AMZ-GKDFVJSUHPYTRHW3] |
| 儿童/婴幼儿产品（安全限制清单） | GRLKLZ6WQ9R259LC、G8FDB4PSHS4AACQ5、GDPSRCGVBFSFY78H、GFEUQFB9X4YWFVXD、GPQBDFAYL3LCWYD2、G202155900、GRBE9D3BXQJPMA6V、GKJRA3FRPRKVBJJS | 7 岁及以下儿童带帽/领口抽绳上衣、琥珀/串珠磨牙项链、蘑菇形牙胶/安抚奶嘴、面向儿童的吸水珠、美人鱼尾泳衣、指尖陀螺刀/打火机/飞镖陀螺禁售 | 儿童上衣若去除帽绳/领口抽绳可销售；吸水珠只能以非儿童用途（园艺等）描述且不得出现儿童图片。 | [R:AU-L1-CHILD-002] [SRC-AU-AMZ-GRLKLZ6WQ9R259LC] [SRC-AU-AMZ-G8FDB4PSHS4AACQ5] [SRC-AU-AMZ-GDPSRCGVBFSFY78H] [SRC-AU-AMZ-GFEUQFB9X4YWFVXD] [SRC-AU-AMZ-GPQBDFAYL3LCWYD2] [SRC-AU-AMZ-G202155900] [SRC-AU-AMZ-GRBE9D3BXQJPMA6V] [SRC-AU-AMZ-GKJRA3FRPRKVBJJS] |
| 电子电器 | GRLKLZ6WQ9R259LC、GQQWCXM7GWCFKVVM | 电热水袋、无批准标识的 Level 3 家用电器、直插插座的迷你暖风机、插脚无绝缘的电源/充电器、带禁止特征的旅行转换器禁售 | 合规的 Level 3 电器须有 RCM 与 EESS 证书/注册（见 AU-L5-EESS-002）；充电器插脚须有绝缘套。 | [R:AU-L1-ELEC-005] [SRC-AU-AMZ-GRLKLZ6WQ9R259LC] [SRC-AU-GOV-EESS-OPERATOR-GUIDE] [SRC-AU-AMZ-GQQWCXM7GWCFKVVM] |
| 化学品（安全限制清单） | GRLKLZ6WQ9R259LC、GKD2ZVSS3AZM4AQT、GW6HK2RDRNNFW2ML、GXE3TPKYT83DDWJM、GFN9WH6A9844V2T2 | 含二氯甲烷/NMP 的脱漆剂、叠氮化钠、三氯乙酸、灭火球禁售 | — | [R:AU-L1-CHEM-001] [SRC-AU-AMZ-GRLKLZ6WQ9R259LC] [SRC-AU-AMZ-GKD2ZVSS3AZM4AQT] [SRC-AU-AMZ-GW6HK2RDRNNFW2ML] [SRC-AU-AMZ-GXE3TPKYT83DDWJM] [SRC-AU-AMZ-GFN9WH6A9844V2T2] |
| 凝胶/液体燃料火盆 | G5P5YMQXX9Y34NVU、GRLKLZ6WQ9R259LC | 凝胶/液体燃料火盆和壁炉（含桌面酒精火炉、生物乙醇壁炉）全球禁售 | — | [R:AU-L1-FIREPIT-001] [SRC-AU-AMZ-G5P5YMQXX9Y34NVU] [SRC-AU-AMZ-GRLKLZ6WQ9R259LC] |
| UVC 设备 | G5ZEPL3F3YQR5GUS、GRLKLZ6WQ9R259LC | 家用便携 UVC 消毒器、UVC 消毒棒、UVC 灯泡禁售 | 美甲 UV 灯、驱蚊灯等非 UVC 消毒用途产品不在此列，但需确认波段与宣称。 | [R:AU-L1-UVC-001] [SRC-AU-AMZ-G5ZEPL3F3YQR5GUS] [SRC-AU-AMZ-GRLKLZ6WQ9R259LC] |
| 电热服饰与座椅加热垫 | GFQMECECLTJCUE3H、GT8V6T7U8GZZK3SU、GRLKLZ6WQ9R259LC | 电池位于承重位置的电热服装/电热鞋垫、汽车座椅加热垫禁售 | — | [R:AU-L1-HEATED-001] [SRC-AU-AMZ-GFQMECECLTJCUE3H] [SRC-AU-AMZ-GT8V6T7U8GZZK3SU] [SRC-AU-AMZ-GRLKLZ6WQ9R259LC] |
| 燃气器具 | GRLKLZ6WQ9R259LC | LCC27 气瓶转接头、LPG 柜式燃气取暖器禁售 | — | [R:AU-L1-GAS-001] [SRC-AU-AMZ-GRLKLZ6WQ9R259LC] |

## B. 审核与限售（L2）

**申请路径**：卖家平台 > 目录 > 添加商品 > 搜索 ASIN > “显示限制/Listing limitations apply” > “申请销售/Request approval”；新建商品时在上架流程中申请。部分限制在 ASIN、品牌或子类目层级 [SRC-AU-AMZ-G200333160]。当前需审核类目：食品饮料、音乐 CD、影视（DVD/蓝光）、酒类、农药、婴儿配方奶粉；另可申请：大家电、部分二手商品；分类清单还列有娱乐收藏品、艺术品、珠宝、流媒体播放器 [SRC-AU-AMZ-G200333160]。

**共性要求**：多数审核类目要求专业销售计划、该类目商品多于一个、在澳洲有退货地址（或免费退货）、提供澳洲本地语言客服、商品为新品且面向澳洲市场、带有效条码、英文标签 [SRC-AU-AMZ-GSHFYZ3G4JSZGTHE] [SRC-AU-AMZ-GQR5FX94UKK38Q9Q] [SRC-AU-AMZ-GEHDL3P6RLYX8UUZ]。另外，服装类页面称服装鞋类仅限预批准卖家，但审核类目清单未列服装，见待核实 [SRC-AU-AMZ-G200164430]。

| 类目 | 要求摘要 | 所需材料 | 申请路径 | 规则ID |
| --- | --- | --- | --- | --- |
| 酒类须类目审核 | 销售酒精饮料须获亚马逊预批准：专业销售计划、在本类目有多于一个商品、在澳洲经营并有澳洲退货地址（或免费退货）、提供澳洲本地语言客服、使用送货时进行年龄核验的承运商、在“关于卖家”页展示酒牌信息；商品须为新品、有有效条码、符合 FSANZ 标准 2.7.1（英文标签、酒精含量和标准饮酒量）、有效期为 DD/MM/YYYY。 | 有效的澳洲酒类许可证（含持证人名称和地址、证号、状态有效、起止日期）；年龄核验配送承诺函（公司抬头、签名、与酒牌一致的企业名、承运商名称、确认送货时核验年龄）；FSANZ 标准 2.7.1 英文标签，含酒精度及标准饮酒量 | 卖家平台 > 目录 > 添加商品 > 显示限制 > 申请销售 | [R:AU-L2-ALCOHOL-001] [SRC-AU-AMZ-GM9BQPTJNXU2KEDW] [SRC-AU-AMZ-G200333160] |
| 艺术品（Fine Art）类目须预批准；限量版须 ≤400 版并签名编号 | 只有预先批准的卖家可在 Fine Art 类目销售原创画作、水彩、素描、二维综合材料，以及限量 ≤400 版、签名编号或附艺术家签名证书的版画/摄影；二次销售作品须有出处与购买凭证。雕塑、纺织/考古艺术、无署名艺术家作品、量产手绘、复制品、画布微喷（Giclée）、宣传海报、开放版、超过 400 版的作品不符合 Fine Art 类目。Fine Art 目前不接受新卖家申请；将来开放时须满足至少两项：经营 ≥3 年、在 1stDibs/Artsy 等有显著线上展示、有策展元素；ODR < 0.75%；不接受艺术家自售或量产画廊。 | 真品证明/签名编号/出处与销售历史 | 卖家平台 > 申请销售（Fine Art） | [R:AU-L2-FINEART-001] [SRC-AU-AMZ-G201279060] [SRC-AU-AMZ-G201257400] [SRC-AU-AMZ-G200333160] |
| 收藏钱币类目须事先获得亚马逊批准 | 在 Collectible Coins 类目刊登收藏钱币前须获得亚马逊批准；可作为法定货币的贵金属铸币（monetised bullion）在合规前提下允许。 | — | 卖家平台 > 申请销售 | [R:AU-L2-COINS-001] [SRC-AU-AMZ-G200164450] |
| 食品饮料类目审核 | 销售食品饮料须申请类目审核：专业销售计划、该类目商品多于一个、在澳洲有退货地址（或免费退货）、提供本地语言客服；商品须为新品、为澳洲市场生产并符合澳洲法律、带有效条码；须提交签名声明（遵守 Seller Central 要求及澳洲食品法规）和 5 个食品的照片，显示英文标签、净含量、DD/MM/YYYY 有效期、建议/警示声明与营养信息。目前不接受生鲜和冷冻食品申请。 | 签名声明“I will adhere to the requirements outlined on Seller Central and all applicable laws and regulations regarding food products in Australia”；5 个产品的英文标签照片（净含量、DD/MM/YYYY 有效期、警示/过敏原声明、营养信息） | 卖家平台 > 库存 > 添加商品 > Listing limitations apply > Request approval | [R:AU-L2-FOOD-001] [SRC-AU-AMZ-GSHFYZ3G4JSZGTHE] [SRC-AU-AMZ-G200333160] |
| 农药类目审核 | 在 Lawn & Garden 类目销售农药须申请审核：专业销售计划、多于一个商品、澳洲退货地址（或免费退货）、本地语言客服、可提供有效发票，并能提供每个产品的 APVMA 注册证明或摘要；商品须为新品、面向澳洲市场、有有效条码、英文标签并持有有效 APVMA 注册（法律要求时）。澳洲“农药”定义比其他国家宽（含驱虫剂、防霉、宠物驱虫等）。 | 每个产品的 APVMA 注册证明/产品摘要（PUBCRIS 可查） | 上架时 Request Approval（Lawn & Garden > Pesticides） | [R:AU-L2-PESTICIDE-001] [SRC-AU-AMZ-GQR5FX94UKK38Q9Q] [SRC-AU-AMZ-G200333160] |
| 婴儿配方奶粉须类目审核并符合 FSANZ 食品标准 2.9.1、英文标签 | 销售婴儿配方奶粉须在 Health & Personal Care 申请审核：专业计划、多于一个商品、澳洲退货地址、本地语言客服、有效发票及产品标签照片；商品须为新品、面向澳洲市场、有效条码、英文标签并符合食品标准 2.9.1（婴儿配方产品）。未注册配方奶及 HiPP 奶粉禁售（见 AU-L1-FOOD-001）。FSANZ P1028 修订的标准 2.9.1 及附表 29 自 2024-09-13 生效，5 年过渡期内可选新旧标准，2029-09-13 起须全部符合新规（新增婴儿特殊医学用途产品类别、强制营养信息声明、禁止代理广告）。 | 符合 FSANZ 标准 2.9.1 的英文标签照片 | 上架时 Request Approval | [R:AU-L2-FORMULA-001] [SRC-AU-AMZ-GEHDL3P6RLYX8UUZ] [SRC-AU-AMZ-G200333160] [SRC-AU-GOV-FSANZ-P1028] |
| 大家电（洗碗机、洗衣机、干衣机、冰箱、冰柜）须邮件申请，须能配送全澳主要城市并支 | Major Domestic Appliances 类目限制新卖家：须能配送澳洲所有首府城市、能安排退货、可通过 API 或第三方方案对接订单跟踪和预约配送；符合条件者发邮件至 au-mda@amazon.com.au 申请。佣金 7%。此类电器同时受 EESS、GEMS 能效注册与标签、WELS 等法规约束。 | — | 邮件 au-mda@amazon.com.au | [R:AU-L2-APPLIANCE-001] [SRC-AU-AMZ-G4TKMFYMP2XJNJPH] [SRC-AU-AMZ-G200333160] |
| 音乐 CD、影视（DVD/蓝光）类目须审核 | 部分音乐 CD 商品受限或需申请，须提供主要货源、预计销售数量及至少 1 张最大货源发票；Video, DVD & Blu-ray 类目要求订单缺陷率 ≤1%、取消率 ≤2.5%、迟发率 ≤4%，并提供至少 3 张最大货源发票或采购单。发票将被核实，伪造文件将被移除销售权限。 | 货源发票（音乐 ≥1 张；影视 ≥3 张）及销量预估 | 添加商品 > Listing limitations apply > Request approval | [R:AU-L2-MEDIA-001] [SRC-AU-AMZ-G202188990] [SRC-AU-AMZ-G201607580] [SRC-AU-AMZ-G200333160] |
| 流媒体播放器（电视盒子等）须类目审核 | 销售流媒体播放器须逐型号申请：向亚马逊寄送每个型号的样机（不退不补、运费自付），并提交品牌、制造商、型号、硬件配置、操作系统版本、全部预装软件和 .apk 清单、软件来源仓库、出厂安装的应用/更新清单及申请表；亚马逊可随时抽查并撤销权限。 | — | 添加商品 > Listing limitations apply > Request approval，上传申请表 | [R:AU-L2-STREAMING-001] [SRC-AU-AMZ-G202183590] [SRC-AU-AMZ-G200333160] |
| 二手/翻新状态须遵守类目状态指南；可食用/可涂抹/消耗品一律只能以“新品”销售 | 二手（Like New/Very Good/Good）和翻新状态只能在类目状态指南允许时使用，部分二手商品需申请审核；美妆、食品杂货、健康护理、维生素及补充剂等消耗、入口或外用商品必须以“New”状态销售；不能正常工作、不清洁、缺关键部件、促销样品、过期或被指定销毁的商品不得上架。 | 按状态指南如实选择状态并披露缺件/瑕疵 | 添加商品 > 显示限制 > 申请销售 | [R:AU-L2-USED-001] [SRC-AU-AMZ-G200339950] [SRC-AU-AMZ-G200333160] |
| 珠宝（Jewelry）类目须审核并遵守珠宝质量保证标准 | Jewelry 列于需审核类目。珠宝质量保证标准要求：真实准确的贵金属印记与含量信息，印记须附商标或制造商名称；金须披露成色（10K/14K/24K），低于 10K 不得称为 gold（如“9K gold”不允许），公差一般 ±0.003；纯银须 92.5%；标“PLAT/PLATINUM”须 950‰，不足须标“900 PLAT”等；镀金铜等无贵金属印记；宣称“hypoallergenic”的不得含镍或其他已知致敏物质；儿童首饰须符合法律。另须符合设计、镶嵌、珍珠与有色宝石标准。 | 准确的贵金属印记（附商标/制造商名）与详情页金属含量 | 卖家平台 > 申请销售 | [R:AU-L2-JEWELRY-001] [SRC-AU-AMZ-G200333160] [SRC-AU-AMZ-G200332590] [SRC-AU-AMZ-G201269180] |
| 娱乐收藏品（签名照、电影海报、限量手办、动画原画、非体育卡、道具戏服）类目须邀请 | Entertainment Collectibles 类目限制新卖家：须专业计划、绩效达标，申请邮件 cfa-application@amazon.com；签名或拍摄/演出使用过的物品须提供 PSA/DNA、JSA、CGC、Celebrity Authentics 等第三方鉴定，或可在线验证编号的 COA/LOA/全息标、拍卖行出处、与名人的合同、签名过程照片等；复制品标题须含“Reproduction”；犯罪现场/验尸照片、灾难现场物品、宣扬仇恨的商品、伪装刀具、暗藏刀剑禁售。 | 第三方鉴定或可验证 COA/LOA/出处证明 | cfa-application@amazon.com | [R:AU-L2-COLLECTIBLES-001] [SRC-AU-AMZ-G200944120] [SRC-AU-AMZ-G200333160] |

**品牌与季节性限制**：本次未在澳洲站帮助页找到季节性限售（如美国站的 Q4 玩具限制）或“强化安全合规类目”的完整说明页（GUQ848NB5HZ6M6A4 仅能抓到导航壳），但锂电池页明确要求商业保险证明（COI）和授权第三方检测认证（TIC）验证 [R:AU-L3-LIBATT-001] [SRC-AU-AMZ-G7PAP6BJAUXRM4LH]。

## C. 按品类的平台合规资料（L3）

**通用提交规则**（各合规页一致）：检测报告须来自 ISO/IEC 17025、NATA、CNAS（部分页面为 ILAC MRA）认可实验室，结果只接受“Pass”或“NA”，不得来自亚马逊暂停认可的实验室；文件须为原始未修改格式、非 AI 生成；图片须显示产品各面、型号、标签、合规标识、警示语，套装须分别提供；说明书、警示须为英文；提交入口为“卖家平台 > 账户状况 > 提交合规信息或申诉”（GC35Z63FGCUCUWXX） [SRC-AU-AMZ-GUBLQYWAJDBADUVK] [SRC-AU-AMZ-G85BLBNFDCZ4BQP7]。部分品类（锂电池、移动电源等）已改为通过亚马逊授权 TIC 机构“直接产品验证”：在账户状况 > 食品和产品安全问题 > Verify your product 创建测试申请单（TRF），由 TIC 机构代为提交 [SRC-AU-AMZ-GUTZ2R2DD6P2UMVB]。可用“合规参考工具”（/ckp）按商品类型或 ASIN 查看要求 [SRC-AU-AMZ-G2JX2MAWJ27DWAY6]。

| 产品族 | 亚马逊要求的文件/Listing 属性 | 提交位置 | 规则ID |
| --- | --- | --- | --- |
| 成人用品须归入 Sexual Wellness 类目、仅限全新、无裸露/粗俗用语、标注有效期、使用临床式描述 | 正确设置 Adult 标记并放入 Sexual Wellness 对应子类目（卖家）；图片与包装无裸露；标题无粗俗/露骨用语；适用商品显示有效期（卖家） | 卖家平台 > 添加商品（类目与 adult_product 属性）；商品详情页 | [R:AU-L3-ADULT-001] [SRC-AU-AMZ-G200339940] |
| 食品饮料须完整标签与详情页属性（制造/进口商名址、DD/MM/YYYY 有效期、净含量、营养信息），原厂密封，保质期要求 | 英文食品标签（FSANZ 标准 1.2.1 等）（卖家/进口商）；详情页必填属性：制造/进口商名址、有效期（DD/MM/YYYY）、净含量、营养信息（卖家） | 卖家平台 > 编辑商品；商品包装与详情页 | [R:AU-L3-FOOD-001] [SRC-AU-AMZ-G200164550] [SRC-AU-AMZ-G201829010] |
| 治疗用品（非附表药品）须提交 ARTG 证书/公开摘要，详情页显示 ARTG 号、药品名、警示语；附表 3/4/8/9/10 药品禁售 | 附表 3/4/8/9/10 药品不得销售（亚马逊；TGA（毒物标准））；ARTG 证书或公开摘要（PDF，不可编辑）（TGA）；详情页展示 ARTG 编号、药品名称、警示语（卖家） | 不适用；卖家平台 > 账户状况 > 商品政策合规性（提交合规文件或申诉）；商品详情页 | [R:AU-L3-TGA-001] [SRC-AU-AMZ-GV8XARHLGCMHQY5C] |
| 电子游戏、DVD、蓝光须取得澳洲分级并显示澳洲分级标识 | 澳洲分级（Classification Board）（澳洲分级委员会（Classification Board））；包装显示澳洲分级标识（G/PG/M/MA15+/R18+）及消费者提示（卖家/发行商） | classification.gov.au；商品包装与详情页 | [R:AU-L3-MEDIA-001] [SRC-AU-AMZ-GS3MLGJS3SQKG3LQ] [SRC-AU-GOV-LEG-F2023L01424] |
| WaterMark 范围卫浴/排水产品须在详情页展示 WaterMark 标志或许可证信息 | WaterMark 认证（许可证号）（JAS-ANZ 认可的 WaterMark 认证机构（WMCB））；产品带 WaterMark 标志及许可证号（制造商） | 产品/包装；商品详情页显示；必要时提交卖家平台 | [R:AU-L3-PLUMBING-001] [SRC-AU-AMZ-GVVAHF4S3EZ7FPAY] |
| 环保宣称须真实、具体、可证实；“eco-friendly”“sustainable”“green”等笼统未限定的环保宣称不允许 | 宣称依据（检测报告/认证/数据），应要求提交亚马逊（卖家/制造商） | 应亚马逊要求提交 | [R:AU-L3-CLAIMS-001] [SRC-AU-AMZ-GJDWGWRZQJPFBN9P] |
| EESS Level 2/3 电器（剃须刀、按摩器、美发器、厨房电器、灯串、电源适配器/排插/延长线、电热毯、充电器等）须提交 RECS 符合性证书与 EESS 设备注册号、RCM 图片；旅行转换器另须 AS/NZS 3122/3112 并禁止特定设计 | RECS 认证机构签发的 EESS 符合性证书（CoC）（RECS 认可认证机构（SAA Approvals、Global-Mark、TÜV Rheinland Australia 等））；EESS 注册数据库设备编号（EESS（由澳新责任供应商注册））；产品 RCM 标志与型号图片（责任供应商）；带禁止特征的旅行转换器不得销售（亚马逊） | 不适用；卖家平台 > 提交合规信息；卖家平台 > 提交合规信息或申诉；卖家平台（图片） | [R:AU-L3-ELEC-001] [SRC-AU-AMZ-GQQWCXM7GWCFKVVM] [SRC-AU-GOV-EESS-LEVELS] [SRC-AU-GOV-EESS-OPERATOR-GUIDE] |
| 儿童水上玩具须符合《消费品（水上玩具）安全标准 2026》并带警示语 | 水上玩具安全标准 2026 检测报告（AS/NZS ISO 8124.1:2023 或 ISO 8124-1:2022 第 4.20 条）（ISO 17025、NATA 或 ILAC MRA 认可实验室）；产品与包装永久警示语（制造商） | 产品/包装；图片提交亚马逊；卖家平台 > 账户状况 > 提交合规信息或申诉 | [R:AU-L3-ACCC-001] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-AMZ-G437RJUPBUEZFHVU] [SRC-AU-GOV-LEG-F2026L00797] |
| 婴儿洗澡辅助器（浴椅、浴架等）须符合 ASTM F1967-13 及永久溺水警示 | ASTM F1967-13 检测报告（ISO 17025、NATA 或 CNAS 认可实验室）；产品和包装永久溺水警示语（按标准字号与三角符号）（制造商） | 产品/包装；图片提交亚马逊；卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-002] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-AMZ-GBSBVUXSS65RPBBP] [SRC-AU-GOV-LEG-F2017L01394] |
| 婴儿安抚奶嘴及奶嘴链须符合 AS 2432:2015 或 EN 1400 / EN 12586 | AS 2432:2015 或 EN 1400（奶嘴）/ EN 12586（奶嘴链）检测报告（认可第三方实验室）；按标准要求的警示与使用说明（制造商） | 产品/包装；卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-003] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2017L00516] [SRC-AU-AMZ-GX9BGE7LAFRWAFHF] |
| 婴儿学步车须符合 ASTM F977-12（含标签要求） | ASTM F977-12 检测报告（认可第三方实验室）；ASTM F977 规定的警示标签（制造商） | 产品/包装；卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-004] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2013L00190] [SRC-AU-AMZ-GPJ984JUMZWCU96F] |
| 气球吹制套装（塑胶泡泡/气球胶）不得含苯 | 苯含量检测（不得检出）（认可第三方实验室） | 应要求提交亚马逊 | [R:AU-L3-ACCC-005] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F1997B01840] |
| 篮球架/篮板须有“不当安装或悬挂可致重伤或死亡”警示（≥15 mm） | 篮板/篮架永久警示标签与安装说明（制造商）；按标准的检测/符合性报告（认可第三方实验室） | 产品/包装；图片提交亚马逊；卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-006] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2017L01657] [SRC-AU-AMZ-GLBSMWBUENTFMEX6] |
| 懒人豆袋及袋套须用儿童防护拉链并带红色窒息警示 | 豆袋安全标准 2014 检测报告（ISO 17025、NATA 或 ILAC MRA 认可实验室）；产品与包装永久窒息警示（红色）（制造商） | 产品/包装；图片提交亚马逊；卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-007] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-AMZ-G5H9CJ6RJTZRVZK7] [SRC-AU-GOV-LEG-F2014L01587] |
| 自行车头盔须完全符合 AS/NZS 2063、EN 1078、ASTM F1447、16 CFR 1203 或 Snell B95 之一 | 上列任一标准的完整检测报告（认可第三方实验室）；按所选标准的标识（标准号、尺寸、警示等）（制造商） | 产品/包装；卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-008] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2024L00362] [SRC-AU-AMZ-GHRAUBNDL7K7EZSG] |
| 脚踏自行车须符合 AS/NZS 1927:1998（经修订） | AS/NZS 1927 符合性检测报告（认可第三方实验室）；按标准的反光器、铃及说明书（制造商） | 产品/包装；卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-009] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2005B01053] [SRC-AU-AMZ-GBVSAAJFBSKYNT8Q] |
| 室内带拉绳窗帘/百叶窗须有绳索安全装置、警示标签（供应标准） | 产品/包装上的儿童勒颈警示标签及安装说明（制造商）；符合供应标准的检测/评估报告（认可第三方实验室） | 产品/包装；图片提交亚马逊；卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-010] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2010L01930] [SRC-AU-AMZ-GT7F5YBQFRDZCAG8] |
| 双层床须符合 AS/NZS 4220:1994（经修订，护栏、95 mm 间隙、警示） | AS/NZS 4220 符合性检测报告（认可第三方实验室）；床体永久警示标签（制造商） | 产品/包装；卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-011] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2005B01055] [SRC-AU-AMZ-GXCWBPZVZMQDNWRS] |
| 单独销售的纽扣/硬币电池须符合 ACCC 安全标准（儿童防护包装）与信息标准（警示），提交检测报告 | 纽扣/硬币电池安全标准 + 信息标准检测报告（ISO/IEC 17025、NATA 或 CNAS 认可实验室）；包装警示语、远离儿童与安全警示符号；≥20 mm 锂硬币电池印 KOOROC 符号（制造商）；详情页填写型号/零件号、制造商或品牌（卖家） | 产品/包装；图片提交亚马逊；卖家平台 > 账户状况 > 提交合规信息或申诉；商品详情页 | [R:AU-L3-ACCC-012] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-AMZ-GUBLQYWAJDBADUVK] [SRC-AU-AMZ-G85BLBNFDCZ4BQP7] [SRC-AU-GOV-LEG-F2020L01658] [SRC-AU-GOV-LEG-F2020L01659] |
| 服装、纺织品须有英文永久护理标签（AS/NZS 1957 或 ISO 3758 符号） | 英文永久护理标签（洗涤、干燥、熨烫、干洗说明或 ISO 3758 符号）（制造商） | 产品缝制标签 | [R:AU-L3-ACCC-013] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2023L01187] |
| 儿童汽车安全座椅须符合 AS/NZS 1754；织物座椅、安全背心、头部固定配件、摩托车儿童座椅/束带禁售 | AS/NZS 1754 合规证明（检测报告/认证）（认可第三方实验室/认证机构）；头部固定配件、约束背心、织物座椅、增高座椅、上拉带、摩托车儿童座椅/束带不得销售（亚马逊） | 不适用；卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-014] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-AMZ-G202137200] [SRC-AU-GOV-LEG-F2014L01252] [SRC-AU-AMZ-GRLKLZ6WQ9R259LC] |
| 化妆品须在容器上用英文或 INCI 名按含量降序列出全部成分（化妆品信息标准 2020） | 英文/INCI 全成分表（降序）（制造商/进口商） | 产品容器/包装；详情页建议同步 | [R:AU-L3-ACCC-015] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2020L01469] |
| 酒精/凝胶燃料装饰器具（桌面火炉、壁炉）须符合 EN 16647 并带永久警示 | EN 16647 相关条款检测报告（认可第三方实验室）；永久警示标签（制造商） | 产品/包装；卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-016] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2017L00909] [SRC-AU-AMZ-G5P5YMQXX9Y34NVU] |
| 一次性/可充气打火机须达儿童防护标准（ASTM F400 或 EN 13869） | 儿童防护（child resistance）检测报告（认可第三方实验室） | 卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-017] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2019L00132] |
| 弹力行李绑带须在黄色底上永久标注回弹伤眼警示 | 产品与包装永久警示（黄色底）（制造商） | 产品/包装；图片提交亚马逊 | [R:AU-L3-ACCC-018] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-AMZ-G33UY7AQ98SXVHJB] [SRC-AU-GOV-LEG-F2017L00382] |
| 健身单车须符合 AS 4092-1993（经修订） | AS 4092 符合性检测报告（认可第三方实验室）；按标准的警示与说明（制造商） | 产品/包装；卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-019] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2005B01068] [SRC-AU-AMZ-GG6Z9HM4W4S6BEJQ] |
| 折叠/便携婴儿床须符合婴儿睡眠产品安全标准 2024（AS/NZS 2195:2010 或 ASTM F406-22 + 通用要求） | AS/NZS 2195 或 ASTM F406-22 + 婴儿睡眠产品通用要求检测报告（认可第三方实验室）；婴儿产品信息标准 2024 警示与标记（见 AU-L3-ACCC-023）（制造商/进口商） | 产品/包装/详情页；卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-020] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2024L00891] [SRC-AU-GOV-PSA-INFANT-SLEEP] [SRC-AU-AMZ-GZHGJY9GCWWRYJM2] |
| 热水袋须符合壁厚、塞子、防漏测试并带烫伤警示 | 热水袋安全标准检测报告（认可第三方实验室）；烫伤警示与信息标签（制造商） | 产品/包装；卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-021] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2008L00651] [SRC-AU-AMZ-GXDAD4N3TU3AK5TD] |
| 家用婴儿床须符合婴儿睡眠产品安全标准 2024（AS/NZS 2172:2013、BS EN 716-1 或 ASTM F1169-19 + 通用要求） | AS/NZS 2172、BS EN 716-1 或 ASTM F1169-19 + 通用要求检测报告（认可第三方实验室）；婴儿产品信息标准 2024 警示与标记（制造商/进口商） | 产品/包装/详情页；卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-022] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2024L00891] [SRC-AU-GOV-PSA-INFANT-SLEEP] [SRC-AU-AMZ-GZHGJY9GCWWRYJM2] |
| 婴儿睡眠产品（摇篮、睡篮、睡袋式睡床、床垫等）及倾斜类非睡眠产品须符合 2024 安全标准与信息标准（在线 listing 须展示警示） | 婴儿睡眠产品安全标准 2024 检测报告（认可第三方实验室）；婴儿产品信息标准 2024：产品/外包装警示、原产国+澳洲进口商名称、说明书警示（制造商/澳洲进口商）；在线 listing 展示规定警示语（卖家） | 产品/包装；卖家平台 > 提交合规信息或申诉；商品详情页 | [R:AU-L3-ACCC-023] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2024L00891] [SRC-AU-GOV-LEG-F2024L00892] [SRC-AU-GOV-PSA-INFANT-SLEEP] [SRC-AU-AMZ-GZHGJY9GCWWRYJM2] |
| 迷你摩托车须符合《消费品（迷你摩托车）安全标准 2019》（油门、制动等设计要求） | 迷你摩托车安全标准符合性报告（认可第三方实验室） | 卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-024] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2019L01633] |
| 可移动足球门（≥28 kg）须通过稳定性测试并在 3 处标注“始终固定球门”警示 | AS 4866.1 稳定性测试报告（认可第三方实验室）；3 处永久警示（制造商） | 产品；卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-025] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2010L03061] [SRC-AU-AMZ-G7JKRNAKF5HRTDLT] |
| 儿童睡衣及部分日装、纸样须按 AS/NZS 1249:2014 分级并加火险标签 | AS/NZS 1249:2014 燃烧性能检测与分类报告（认可第三方实验室）；火险标签（按分类）（制造商） | 卖家平台 > 提交合规信息或申诉；服装缝制标签 | [R:AU-L3-ACCC-026] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2017L00452] [SRC-AU-AMZ-G5NGAYYZAY559SCZ] |
| 一次性氦气罐须含 21%±1% 氧气并标注“勿吸入，可致窒息” | 气体成分（含氧量）检测/证书（认可第三方实验室/气体供应商）；钢瓶与包装窒息警示（制造商） | 产品/包装；卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-027] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2023L00038] [SRC-AU-AMZ-GP27QYBAUSUCWB99] |
| 便携气溶胶灭火器须符合 AS/NZS 4353:1995 | AS/NZS 4353 符合性报告/认证（认可第三方实验室/认证机构） | 卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-028] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2005B01049] [SRC-AU-AMZ-GS972L5FPTCLNYNR] |
| 便携非气溶胶灭火器须符合 AS/NZS 1841.1–.8:2007 | AS/NZS 1841 符合性（通常为第三方产品认证）（认可认证机构） | 卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-029] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2021L01844] [SRC-AU-AMZ-GS972L5FPTCLNYNR] |
| 便携式车辆坡道须符合 AS 2640:2016 | AS 2640 符合性检测报告（认可第三方实验室）；额定载荷等标记与说明（制造商） | 产品/包装；卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-030] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2017L01559] [SRC-AU-AMZ-GRKGPHRX533JSRCK] |
| 便携式泳池须在泳池和零售包装上永久标注溺水警示 | 泳池与包装永久溺水警示（制造商） | 产品/包装；图片提交亚马逊 | [R:AU-L3-ACCC-031] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2013L00049] [SRC-AU-AMZ-GFP2U2S6M3UWBXKF] |
| 婴儿推车须符合 AS/NZS 2088:2000（经修订：红色驻车制动、手腕系带、安全带、稳定性等） | AS/NZS 2088 检测报告（ISO 17025、NATA 或 CNAS 认可实验室）；标准规定的警示语（制造商） | 产品/包装；图片提交亚马逊；卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-032] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-AMZ-G4SX7HDHVCGK33UD] [SRC-AU-GOV-LEG-F2007L01895] |
| 含纽扣/硬币电池的产品须电池仓防儿童开启、通过滥用测试，并在包装/说明书标注警示 | 含纽扣电池产品安全标准检测报告（电池仓与滥用测试）（ISO 17025、NATA 或 CNAS 认可实验室）；说明书警示、包装正面安全警示符号（无包装则吊牌/贴纸）（制造商） | 产品/包装；图片提交亚马逊；卖家平台 > 账户状况 > 提交合规信息或申诉 | [R:AU-L3-ACCC-033] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2020L01656] [SRC-AU-GOV-LEG-F2020L01657] [SRC-AU-AMZ-GD3HX7SAHCTDJ6QU] |
| 弹射玩具（动能 >0.08 J）须标注“勿对准眼睛或面部” | 弹射玩具相关条款检测报告（认可第三方实验室）；“WARNING: Do not aim at eyes or face” 警示（动能 >0.08 J 时）（制造商） | 卖家平台 > 提交合规信息或申诉；说明书/包装 | [R:AU-L3-ACCC-034] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2020L00687] [SRC-AU-AMZ-GKJRA3FRPRKVBJJS] |
| 四轮摩托车（ATV）须符合 ANSI/SVIA 1-2017 或 EN 15997，带侧翻警示、横向稳定性及操作者保护装置 | ANSI/SVIA 1-2017 或 EN 15997 + 稳定性测试报告（认可第三方实验室）；侧翻警示标签与吊牌（制造商） | 产品；卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-035] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2019L01321] [SRC-AU-AMZ-G74TRGJ7KW7DUK2A] |
| 车辆拖车/救援带须带永久警示与使用说明 | 永久警示标签与说明（制造商）；标准符合性报告（认可第三方实验室） | 产品/包装；图片提交亚马逊；卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-036] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2017L01560] [SRC-AU-AMZ-GNMG498S7WTV4TYT] |
| 平衡车（hoverboard）须符合 IEC 62133-2 + AS/NZS 60335 相关条款或 UL 2272 | IEC 62133-2 + 60335 相关条款，或 UL 2272 检测报告（认可第三方实验室） | 卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-037] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2018L00659] [SRC-AU-AMZ-GMUW6CKYLY4AP8MK] |
| 太阳镜及时尚眼镜须符合 AS/NZS 1067.1:2016（镜片类别与 UV 标签） | AS/NZS 1067.1:2016 检测报告（镜片类别、透光率、UV）（认可第三方实验室）；镜片类别与适用警示标签（制造商） | 卖家平台 > 提交合规信息或申诉；吊牌/包装 | [R:AU-L3-ACCC-038] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2017L01391] [SRC-AU-AMZ-GCP5RFFKH834SU3W] [SRC-AU-AMZ-G202171660] |
| 游泳辅助浮具（臂圈、浮力背心、游泳圈等）须符合 AS/NZS 1900:2014 | AS/NZS 1900:2014 检测报告（认可第三方实验室）；标准规定的警示（“非救生设备”“仅在看护下使用”等）（制造商） | 产品/包装；卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-039] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2017L01662] [SRC-AU-AMZ-GTVZL2BE4YZJWLTE] |
| 易倾倒家具（≥686 mm 衣柜/书柜/斗柜等及任意高度电视柜）须加永久防倾倒警示并在在线 listing 展示 | 永久防倾倒警示标签（含禁止攀爬图示与固定说明）（制造商）；在线 listing 描述中展示防倾倒警示（卖家） | 产品；图片提交亚马逊；商品详情页 | [R:AU-L3-ACCC-040] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2024L00512] [SRC-AU-GOV-PSA-TOPPLING] [SRC-AU-AMZ-GFF2FG9J54JMMB4C] |
| 儿童玩具中铅及其他 7 种元素迁移量须符合 AS/NZS ISO 8124.3（CPN 1/2009） | AS/NZS ISO 8124.3（或 ISO 8124-3/EN 71-3 等效）元素迁移检测报告（认可第三方实验室） | 卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-041] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2009L00223] [SRC-AU-AMZ-GKJRA3FRPRKVBJJS] |
| 含磁铁玩具须符合 AS/NZS ISO 8124.1、ISO 8124-1、EN 71-1 或 ASTM F963 的磁铁/磁通指数条款 | 磁铁相关条款检测报告（磁通指数、浸泡、拉力等）（认可第三方实验室） | 卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-042] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2020L01074] [SRC-AU-AMZ-GKJRA3FRPRKVBJJS] |
| 36 个月及以下儿童玩具须符合 2023 安全标准（小零件等机械物理条款） | 2023 标准所列条款检测报告（认可第三方实验室） | 卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-043] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2023L01185] [SRC-AU-AMZ-GKJRA3FRPRKVBJJS] |
| 跑步机须有“始终让幼儿远离本机”永久警示标签 | 永久儿童警示标签（制造商） | 产品；图片提交亚马逊 | [R:AU-L3-ACCC-044] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2009L02165] [SRC-AU-AMZ-GX9TKTXYKB6T22YH] |
| 卧式千斤顶（trolley jack）须符合 AS 2615:2016 | AS 2615 符合性检测报告（认可第三方实验室）；额定载荷标记与说明（制造商） | 产品；卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-045] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2017L01656] [SRC-AU-AMZ-GRKGPHRX533JSRCK] |
| 车辆千斤顶（剪式、瓶式等）须符合 AS/NZS 2693:2007 | AS/NZS 2693 符合性检测报告（认可第三方实验室）；标准规定的警示与标记（制造商） | 产品；卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-046] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2010L00295] [SRC-AU-AMZ-GRKGPHRX533JSRCK] |
| 车辆支撑架（马凳/jack stand）须符合 AS 2538:2016 | AS 2538 符合性检测报告（认可第三方实验室）；额定载荷等标记（制造商） | 产品；卖家平台 > 提交合规信息或申诉 | [R:AU-L3-ACCC-047] [SRC-AU-AMZ-GLV5ESPKUCWX9KPS] [SRC-AU-GOV-LEG-F2017L01563] [SRC-AU-AMZ-GRKGPHRX533JSRCK] |
| 医疗器械及配件须提交 ARTG 证书与澳洲申办者证明（或申办者授权信/采购发票），图片须与 ARTG 信息一致 | ARTG 证书（TGA（澳洲申办者））；申办者身份证明或申办者授权信/采购发票（澳洲申办者）；产品/包装图片（与 ARTG 一致，含制造商/进口商名址、警示、说明书）（制造商/申办者） | 卖家平台；卖家平台 > 提交合规信息；卖家平台 > 账户状况 > 提交合规信息或申诉 | [R:AU-L3-MEDDEV-001] [SRC-AU-AMZ-GL7SLDV3WUGZAEQZ] [SRC-AU-AMZ-G200164650] |
| 婴幼儿喂养用品（奶瓶、学饮杯、餐具、储奶袋）及围兜须提交食品接触/BPA/邻苯检测报告 | 食品接触 + BPA + EN 14372/EN 14350 检测报告（围兜：邻苯检测）（ISO 17025、NATA、CNAS 或 ILAC MRA 认可实验室） | 卖家平台 > 提交合规信息或申诉 | [R:AU-L3-FEEDING-001] [SRC-AU-AMZ-GUG6JJCDN6YYQYJP] [SRC-AU-AMZ-GUDREU3TUSEM3D3B] |
| 儿童玩具（含电动玩具、指尖陀螺、牙胶）须按年龄与类型提交机械物理、元素迁移、邻苯、磁铁等检测报告，详情页年龄须与报告一致 | 按玩具类型的检测报告（机械物理、元素迁移、邻苯、磁铁、电动玩具、纽扣电池等）（ISO 17025、NATA、CNAS 或 ILAC MRA 认可实验室）；年龄分级与小零件等警示（产品+包装，永久）（制造商） | 产品/包装；详情页；卖家平台 > 提交合规信息或申诉（或经授权 TIC 机构） | [R:AU-L3-TOY-001] [SRC-AU-AMZ-GKJRA3FRPRKVBJJS] [SRC-AU-AMZ-G202155900] [SRC-AU-AMZ-GDPSRCGVBFSFY78H] |
| 锂电池及锂电池供电家电/智能设备：强化合规（商业保险 COI + 授权 TIC 机构验证）、IEC 62133-2/62619 与 UN38.3 报告（12 个月内）、警示语 | 商业保险证明（COI，通过 Business Insurance verification）（保险公司）；安全标准检测报告 + UN 38.3 报告 + BTS（均 12 个月内）（ISO 17025 认可实验室；经亚马逊授权 TIC 机构验证）；产品与包装永久火灾/烫伤警示（制造商） | 产品/包装；卖家平台 > 商业保险验证；账户状况 > 食品和产品安全问题 > Verify your product（TIC 订单） | [R:AU-L3-LIBATT-001] [SRC-AU-AMZ-G7PAP6BJAUXRM4LH] [SRC-AU-AMZ-G8TM22XFM7WXCRDC] [SRC-AU-AMZ-GA2PQDTU5HMC7CRZ] [SRC-AU-AMZ-GUTZ2R2DD6P2UMVB] |
| 移动电源/储能电站（62368.1 + 62133-2/UL 2054 + UN38.3，经授权 TIC 验证）、应急启动电源（UL 2743）、笔记本/手机电池与充电器（RCM、62368.1、EESS 证书） | AS/NZS 62368.1 + 62133-2（或 UL 2054）+ UN 38.3；应急启动电源 UL 2743（认可实验室；授权 TIC 机构验证） | 账户状况 > Verify your product（TIC） | [R:AU-L3-POWER-001] [SRC-AU-AMZ-GSJFE8S8AES7F7VG] [SRC-AU-AMZ-G6WCA7BRX5QWHMNF] [SRC-AU-AMZ-GUTZ2R2DD6P2UMVB] [SRC-AU-AMZ-G202156120] |
| 电动出行设备及配件（电动自行车/三轮车/滑板车/滑板/平衡车/独轮车及电池、充电器、改装套件）须提交 NSW 批准证书、UN38.3、RCM/批准号 | NSW 批准证书（整车/电池）；充电器 EESS 符合性证书与注册号（NSW Fair Trading/REAS；EESS RECS 认证机构）；UN 38.3 报告（+ BTS）；平衡车另附安全标准报告（ISO 17025、NATA 或 ILAC MRA 认可实验室）；RCM 或 REAS 批准号及火灾警示（产品与包装）（供应商） | 产品/包装；卖家平台 > 提交合规信息 | [R:AU-L3-EMOB-001] [SRC-AU-AMZ-GMUW6CKYLY4AP8MK] [SRC-AU-AMZ-G7HM69VDEMRW7TPE] |
| 插电灯串/装饰灯链须符合 AS/NZS 60598.2.20（带控制器另加 61347.2.13）、RCM 与 EESS 注册，转售商须有授权信 | AS/NZS 60598.2.20（及 61347.2.13）检测报告（认可实验室）；EESS 型号注册证书（EESS）；转售商：制造商授权经销信（制造商） | 卖家平台；卖家平台 > 提交合规信息 | [R:AU-L3-STRINGLIGHT-001] [SRC-AU-AMZ-G202137960] |
| 美发电器（理发器、吹风机、卷/直发器）须 RCM、AS/NZS 60335.2.8 或 2.23 报告及 EESS 注册 | AS/NZS 60335.2.8 或 60335.2.23 检测报告（ISO 17025、NATA 或 CNAS 认可实验室）；EESS 注册证书/型号注册（Level 3 另需符合性证书）（EESS）；RCM 标签（责任供应商） | 产品；卖家平台 > 提交合规信息 | [R:AU-L3-HAIR-001] [SRC-AU-AMZ-GW5CVACPVTQNTWHX] [SRC-AU-GOV-EESS-LEVELS] |
| 救生衣/浮力背心/救生圈等个人漂浮装置须符合 AS 4758.1:2022 或 ISO 12402:2020 | AS 4758.1:2022 或 ISO 12402:2020 检测报告（ISO 17025 认可实验室） | 卖家平台 > 提交合规信息 | [R:AU-L3-PFD-001] [SRC-AU-AMZ-G202162990] |
| 沙类产品（彩沙、玩沙、动力沙等）须提交 AS 5370-2024 或 ISO 22262-1 石棉检测“未检出”报告 | AS 5370-2024 或 ISO 22262-1 石棉检测报告（N.D./NAD）（ISO 17025、NATA 或 ILAC MRA 认可实验室） | 卖家平台 > 提交合规信息 | [R:AU-L3-SAND-001] [SRC-AU-AMZ-G9Y54S338CEWN96N] [SRC-AU-GOV-ABF-ACN-2025-33] |
| 烟雾报警器须符合 AS 3786:2014，一氧化碳报警器须符合 AS 7240.6:2017 | AS 3786:2014 / AS 7240.6:2017 检测报告（ISO 17025、NATA 或 CNAS 认可实验室） | 卖家平台 > 提交合规信息 | [R:AU-L3-ALARM-001] [SRC-AU-AMZ-GXUCN5ZRJSYN9W9S] [SRC-AU-AMZ-G200685320] |
| 对讲机须提交 ACMA 格式符合性声明（含责任供应商编号与 ABN/NZBN，须与 EESS 数据库一致）及 RCM 图片 | ACMA 格式供应商符合性声明（DoC）（澳洲供应商（制造商/进口商/代理））；产品上的 RCM 标志（提交图片）（供应商） | 产品；卖家平台；卖家平台 > 提交合规信息 | [R:AU-L3-RADIO-001] [SRC-AU-AMZ-GYLCR8T54SJ7JAYV] [SRC-AU-GOV-LEG-F2021L00661] |
| 儿童便携床护栏须符合 ASTM F2085-19 或 BS 7972:2001+A1:2009 | ASTM F2085-19 或 BS 7972 检测报告（认可第三方实验室） | 卖家平台 > 提交合规信息 | [R:AU-L3-BEDRAIL-001] [SRC-AU-AMZ-GXPFG3RRZB9WFPJE] |
| 燃气器具须有燃气合规标志（GCM）及带认证/批准号的数据铭牌 | 燃气器具认证（GCM 标志 + 证书号）（GTRC 认可认证机构）；数据铭牌（认证/批准号）与 GCM 图片（制造商） | 产品；卖家平台；卖家平台 > 提交合规信息 | [R:AU-L3-GAS-001] [SRC-AU-AMZ-G5L9AARKDVRSGCWR] [SRC-AU-GOV-GTRC] |

## D. FBA 与危险品（L4）

- **危险品**：澳洲多数 ADG（澳大利亚危险品运输规范）界定的危险品不能 FBA；仅第 2.1、2.2、3、4.1、5.1、5.2、6.1、8、9 类在限量包装、新品、已加入 FBA 危险品计划的条件下可入仓；第 1、2.3、4.2、4.3、6.2、7 类禁止 FBA；违规送仓者库存被处置且不赔偿 [R:AU-L4-DG-001] [SRC-AU-AMZ-G200140860] [SRC-AU-AMZ-GYS2KBEE7MYVCGE3] [SRC-AU-AMZ-G201003400]。
- **需 SDS/豁免表的情形**：上架后可能要求安全数据表（SDS）或电池豁免表，通过“管理危险品分类”上传；常见可能被判为危险品的商品：喷雾除臭剂、发胶、染发剂、香水、指甲油、驱虫剂、洗手液、清洁剂、精油、移动电源、手机、智能手表、无线耳机、发光鞋、暖宝宝、营地炉、电动自行车/滑板车、带电池玩具等 [SRC-AU-AMZ-G200525640] [SRC-AU-AMZ-G201371860]。
- **锂电池**：电芯锂离子 ≤20 Wh（锂金属 ≤1 g）、电池组 ≤100 Wh（≤2 g）可接收，超出拒收；须填写电池类型、配置、Wh/锂含量、上传豁免表，并为随设备包装的锂离子电池申报荷电状态 [R:AU-L4-DG-002] [R:AU-L4-DG-003] [SRC-AU-AMZ-G200383420]。
- **FBA 禁运清单**：不能在全澳合法销售的商品、孔明灯、车辆轮胎、礼品卡、散装电池、超尺寸/超重（>116×116×102 cm 或 >23 kg）及拆包后超尺寸的真空压缩商品（如床垫）、带预贴价签/未授权营销材料、损坏/缺陷、仿冒商品等 [R:AU-L4-FBA-002] [SRC-AU-AMZ-G201730840]。
- **有效期与易融**：须正确设置有效期属性；易融商品仅 4 月 30 日—10 月 1 日入仓，仓温 10–38 °C；食品批次商品保质期须 >180 天，距到期约 50 天将被标为不可售 [R:AU-L4-FBA-001] [SRC-AU-AMZ-G201003420] [SRC-AU-AMZ-G202125070] [SRC-AU-AMZ-G200164550]。
- **喷雾、液体、磁铁**：气雾剂多为 2.1/2.2 类，须走危险品计划；强磁铁娱乐套装本身禁售（不是 FBA 问题） [R:AU-L1-HAZMAT-002]；肥料、部分农药为危险品不能 FBA [SRC-AU-AMZ-GD85NFMCQF2KNM2N] [SRC-AU-AMZ-G202115120]。

| 规则 | 内容 | FBA | 规则ID |
| --- | --- | --- | --- |
| FBA 危险品计划：仅接受第 2.1、2.2、3、4.1、5.1、5.2、6.1、8、9 类限量包装危险品；第 1、2.3、4.2、4.3、6.2、7 类禁止入仓；须上传 SDS/豁免表 | 澳洲多数按《澳大利亚危险品运输规范》（ADG）界定的危险品不能使用 FBA；仅第 2.1、2.2、3、4.1、5.1、5.2、6.1、8、9 类（含部分锂电池）在“限量包装”且为新品、已注册 FBA 的条件下经危险品计划审核后可入仓（UN3171 电池驱动车辆须符合特殊规定 288）；第 1 类爆炸品、2.3 毒性气体、4.2 易自燃、4.3 遇湿危险、6.2 感染性物质、7 放射性物质禁止 FBA。上架后可能被要求提供安全数据表（SDS）或豁免表，信息不完整或矛盾将被阻止销售；违规送仓的危险品将被销毁且不赔偿；危险品计划可能设库容上限。 | dg_review | [R:AU-L4-DG-001] [SRC-AU-AMZ-G200140860] [SRC-AU-AMZ-GYS2KBEE7MYVCGE3] [SRC-AU-AMZ-G201003400] [SRC-AU-AMZ-G201371860] [SRC-AU-AMZ-G200525640] |
| FBA 锂电池限值：锂离子电芯 ≤20 Wh、电池 ≤100 Wh（锂金属电芯 ≤1 g、电池 ≤2 g）可入仓，超过即被拒；须填写电池信息、上传豁免表/BTS 并申报荷电状态 | 亚马逊澳洲 FBA 对锂电池的接收上限：电芯（含单电芯电池）锂离子 ≤20 Wh、锂金属 ≤1 g 可接收，>20 Wh 或 >1 g 拒收；电池（多电芯组）锂离子 ≤100 Wh、锂金属 ≤2 g 可接收，>100 Wh 或 >2 g 拒收。创建 listing 或转 FBA 时须提供完整电池信息（电池类型、与设备关系：内置/随附/独立、Wh 或锂含量、电池重量等），上传电池豁免表，并为随设备包装的锂离子电池申报荷电状态；信息不完整或矛盾将被阻止 FBA 销售。 | dg_review | [R:AU-L4-DG-002] [SRC-AU-AMZ-G200383420] [SRC-AU-AMZ-G201371860] |
| 锂电池能量 >100 Wh（或电芯 >20 Wh）的产品不能使用 FBA | 便携储能电站、大容量电池组、电动出行电池等锂离子电池能量超过 100 Wh（或单电芯 >20 Wh）的商品被亚马逊澳洲 FBA 拒收，只能自发货（且须符合 ADG 危险品运输规定及澳洲站其他禁售规则）。 | prohibited | [R:AU-L4-DG-003] [SRC-AU-AMZ-G200383420] |
| FBA 有效期与易融商品：须正确设置有效期属性；食品批次商品保质期 >180 天、距到期约 50 天标为不可售；易融商品仅 4 月 30 日–10 月 1 日间接收，仓温 10–38 °C | 任何有保质期或随时间失效的商品（食品、宠物食品、婴儿配方奶、OTC 药、补充剂、儿童安全座椅、医疗器械、灭火器、护肤品、清洁剂、驱虫剂、带 PAO 标识的美妆等）须在创建 ASIN 时准确设置“是否有效期商品”“有效期类型”“保质期”；食品政策要求批次商品保质期 >180 天，FBA 距到期约 50 天的单位将被标为不可售。易融商品仅在每年 4 月 30 日至 10 月 1 日之间接收，10 月 1 日后在仓的易融库存将被标为不可售并销毁；商品须能承受 10–38 °C 仓储温度，箱唛不得标注其他温度要求。 | None | [R:AU-L4-FBA-001] [SRC-AU-AMZ-G201003420] [SRC-AU-AMZ-G202125070] [SRC-AU-AMZ-G200164550] |
| FBA 禁运：不能在全澳所有州合法销售的商品、车辆轮胎、孔明灯、礼品卡、散装电池、超尺寸（>116×116×102 cm 或 >23 kg）及拆包后超尺寸的真空压缩商品（如床垫）等 | 以下商品不得使用 FBA 及多渠道配送（MCF）：任何不能在澳洲所有司法辖区合法销售和配送的商品（如仅部分州允许的刀具/武器类）；孔明灯/漂浮灯；车辆轮胎；礼品卡等储值工具；带未授权营销材料或预贴价签的商品；尺寸大于 116 cm × 116 cm × 102 cm 或重量超过 23 kg 的商品（部分电视/显示器可放宽至 193 × 122 × 102 cm、45 kg），以及拆封后超过上述尺寸的真空压缩商品（如床垫）；未按要求预处理的商品；散装电池；损坏或有缺陷的商品；标签未正确注册或不匹配的商品；仿冒商品。FBA Export 另排除纳粹纪念品、除草/杀虫产品、文物化石、未显示所需年龄分级的商品、运营商锁定手机等。 | prohibited | [R:AU-L4-FBA-002] [SRC-AU-AMZ-G201730840] [SRC-AU-AMZ-G200140860] |

## E. 当地法规（L5，按产品族）

**总体框架**：澳大利亚消费者法（ACL，《竞争与消费者法 2010》附表 2）规定：供应、要约供应（含 listing）、为供应而持有（含 FBA 仓内库存）不符合强制安全标准、信息标准或永久禁令的商品均属违法；海外制造商在澳无营业地时，进口商被视为“制造商”；供应商须在知悉死亡/严重伤害后 2 日内向 ACCC 强制报告，自愿召回须 2 日内通知部长；公司最高罚款 1 亿澳元或收益 3 倍或营业额 30%（2026-03-28 起） [R:AU-L5-ACL-001] [SRC-AU-GOV-LEG-C2004A00109] [SRC-AU-GOV-PSA-MANDATORY-REPORTING]。截至 2026-10 澳洲尚无“一般安全条款”（GSP），Treasury 于 2026-09-20 至 10-18 就上市后监管征求意见 [SRC-AU-GOV-TREASURY-CRIS-2026]。ACCC 官网“禁售产品”清单共 19 项永久禁令 [SRC-AU-GOV-PSA-BANS]。

### E.1 电子电器（市电）

| 项目 | 内容 |
| --- | --- |
| 适用法规 | 各州电气安全法 + EESS（AS/NZS 4417、AS/NZS 3820 基本安全）；NSW 独立审批制度（66 类申报电气产品）；ACL；能效产品适用 GEMS [SRC-AU-GOV-EESS-LEVELS] [SRC-AU-GOV-NSW-ELEC-APPROVAL] |
| 必需的认证/测试 | Level 3（62 类：插头、旅行转换器、充电器/外置电源、延长线插座、电热毯、电暖器、熨斗、电水壶、面包机、微波炉、厨师机、吸尘器、风扇、按摩器、美发器、剃须刀、灯串、LED 灯等）须 RECS 认证机构签发的澳/新 CoC；Level 2（电视、投影仪、软加热垫等 11 类）须完整测试报告存档；Level 1 须英文合规证据 [SRC-AU-GOV-EESS-LEVELS] [SRC-AU-GOV-EESS-RECS] |
| 注册/备案 | 责任供应商（须为澳新实体，海外公司不能注册）在 EESS 平台注册，Level 2/3 设备销售前注册（2026-07-01 起 A$239.74/年；设备 A$89.85/1 年起） [SRC-AU-GOV-EESS-RESPONSIBLE-SUPPLIER] [SRC-AU-GOV-EESS-FEES] |
| 标签要求 | RCM 标志（外表面、靠近铭牌）；AS/NZS 3112 插头、230 V；listing 尽量展示 RCM；不得销售依赖旅行转换器使用的电器或带伸缩/旋转插脚的转换器 [SRC-AU-GOV-EESS-SELLER-GUIDE] [SRC-AU-GOV-EESS-OPERATOR-GUIDE] |
| 主管机构 | ERAC/各州电气监管机构（ESV、NSW Fair Trading、QLD ESO 等） |
| 规则ID | [R:AU-L1-ELEC-001] [R:AU-L1-ELEC-005] [R:AU-L3-ELEC-001] [R:AU-L3-HAIR-001] [R:AU-L3-STRINGLIGHT-001] [R:AU-L5-EESS-001] [R:AU-L5-EESS-002] [R:AU-L5-EESS-003] [R:AU-L5-EESS-004] |

### E.2 电池与移动电源

| 项目 | 内容 |
| --- | --- |
| 适用法规 | ACCC 纽扣/硬币电池安全标准与信息标准 2020（单独电池、含电池产品各一套）；亚马逊锂电池/移动电源/锂电家电政策；NSW 电动出行电池认证 [SRC-AU-GOV-LEG-F2020L01658] [SRC-AU-GOV-LEG-F2020L01656] |
| 必需的认证/测试 | 纽扣电池：儿童防护包装测试；含纽扣电池产品：电池仓防儿童开启与滥用测试（AS/NZS 62115、62368.1、ISO 8124.1、UL 4200A 等）；锂电池：IEC 62133-2/62619 + UN 38.3 + BTS（12 个月内）；移动电源：AS/NZS 62368.1 + 62133-2/UL 2054 + UN 38.3 [SRC-AU-AMZ-G7PAP6BJAUXRM4LH] [SRC-AU-AMZ-GSJFE8S8AES7F7VG] |
| 注册/备案 | 锂电池类：商业保险证明（COI）+ 授权 TIC 验证；墙插充电器须 EESS 注册/证书 [SRC-AU-AMZ-G202156120] |
| 标签要求 | 纽扣电池包装警示、远离儿童符号、锂电池“2 小时内可致严重或致命伤害”，≥20 mm 锂硬币电池印 KOOROC 符号；含纽扣电池产品：“Warning: Contains button or coin cell battery. Hazardous if swallowed - see instructions” [SRC-AU-GOV-LEG-F2020L01659] [SRC-AU-AMZ-GD3HX7SAHCTDJ6QU] |
| 主管机构 | ACCC；EESS 监管机构；NSW Fair Trading |
| 规则ID | [R:AU-L1-ELEC-002] [R:AU-L3-ACCC-012] [R:AU-L3-ACCC-033] [R:AU-L3-LIBATT-001] [R:AU-L3-POWER-001] [R:AU-L4-DG-002] [R:AU-L4-DG-003] |

### E.3 无线/通信设备

| 项目 | 内容 |
| --- | --- |
| 适用法规 | 《无线电通信设备（通用）规则 2021》、EMC 标签通告 2017、《低干扰潜力设备类许可 2025》（2025-10-01 起）、电信用户设备标签文书 2025、移动设备空中接口标准 2022 [SRC-AU-GOV-LEG-F2021L00661] [SRC-AU-GOV-LEG-F2025L01047] [SRC-AU-GOV-LEG-F2025L00401] |
| 必需的认证/测试 | 符合性声明（DoC）+ 英文测试报告，保存 5 年；对讲机须按 ACMA C02 表格提交 DoC（含责任供应商编号与 ABN/NZBN） [SRC-AU-AMZ-GYLCR8T54SJ7JAYV] |
| 注册/备案 | 供应商须为在澳洲的制造商/进口商/书面授权代理，并在国家数据库注册后方可加贴 RCM [SRC-AU-GOV-LEG-F2018L00028] |
| 标签要求 | RCM ≥3 mm；无法贴产品时贴包装（>1% 面积）与文件；带屏设备可电子标签 |
| 禁止事项 | 信号干扰器（2023 永久禁令）、手机信号放大器（2021 声明）、694–820 MHz 无线设备、3G-only/非 VoLTE 设备（亚马逊政策） [SRC-AU-GOV-LEG-F2023L00214] [SRC-AU-GOV-LEG-F2021L01177] [SRC-AU-AMZ-GGA942GE8CSQ7KK5] |
| 主管机构 | ACMA |
| 规则ID | [R:AU-L1-JAMMER-001] [R:AU-L1-ELEC-003] [R:AU-L1-3G-001] [R:AU-L3-RADIO-001] [R:AU-L5-ACMA-001] [R:AU-L5-ACMA-002] |

### E.4 灯具

| 项目 | 内容 |
| --- | --- |
| 适用法规 | EESS（自镇流 LED 灯、双端 LED 灯管、便携灯具、装饰灯串属 Level 3）；GEMS（LED 灯 2025 决定约 2026-03 起须标光通量/色温；白炽灯、紧凑型荧光灯）；海关条例 4VA（白炽灯进口须许可） [SRC-AU-GOV-EESS-LEVELS] [SRC-AU-GOV-LEG-C2012A00132] [SRC-AU-GOV-LEG-F1996B03651] |
| 必需的认证/测试 | 灯串：AS/NZS 60598.2.20（带控制器 + 61347.2.13）[SRC-AU-AMZ-G202137960] |
| 注册/备案 | EESS 注册；GEMS 型号注册（适用灯具） |
| 标签要求 | RCM；GEMS 规定的灯具参数 |
| 主管机构 | EESS 监管机构；DCCEEW（GEMS） |
| 规则ID | [R:AU-L1-LIGHTING-001] [R:AU-L3-STRINGLIGHT-001] [R:AU-L5-GEMS-001] [R:AU-L5-EESS-002] |

### E.5 儿童玩具

| 项目 | 内容 |
| --- | --- |
| 适用法规 | ACCC：36 个月以下玩具 2023 标准（2025-03-05 起仅新规）、弹射玩具 2020、含磁铁玩具 2020、玩具铅及元素 CPN 1/2009、水上玩具 2026（2026-06-26 起）；永久禁令：小型强磁铁、DEHP>1%、口吹含珠充气玩具、悠悠水球；海关附表 2 玩具涂层重金属限量 [SRC-AU-GOV-LEG-F2023L01185] [SRC-AU-GOV-LEG-F2026L00797] [SRC-AU-GOV-LEG-F2012L02171] |
| 必需的认证/测试 | AS/NZS ISO 8124.1/ISO 8124-1/EN 71-1/ASTM F963；元素迁移 AS/NZS ISO 8124.3；电动玩具 AS/NZS 62115；邻苯（牙胶等） [SRC-AU-AMZ-GKJRA3FRPRKVBJJS] |
| 注册/备案 | 无注册制度；亚马逊要求提交报告，部分经 TIC |
| 标签要求 | 年龄警示（“Not suitable for children under 36 months”、小零件窒息警示）、弹射玩具“Do not aim at eyes or face”；详情页年龄 ≥ 报告年龄 |
| 主管机构 | ACCC；ABF（进口重金属、石棉） |
| 规则ID | [R:AU-L3-TOY-001] [R:AU-L3-ACCC-001] [R:AU-L3-ACCC-034] [R:AU-L3-ACCC-041] [R:AU-L3-ACCC-042] [R:AU-L3-ACCC-043] [R:AU-L5-BAN-001] [R:AU-L5-BAN-002] [R:AU-L5-BAN-003] [R:AU-L5-BAN-006] [R:AU-L6-CUSTOMS-003] [R:AU-L1-CHILD-002] [R:AU-L1-HAZMAT-002] [R:AU-L1-HAZMAT-003] |

### E.6 婴童用品

| 项目 | 内容 |
| --- | --- |
| 适用法规 | ACCC：婴儿睡眠产品安全标准 2024（取代家用/折叠婴儿床标准，2026-01-19 起第 3 部分强制）、婴儿产品信息标准 2024（2026-01-19 起，listing 须展示警示）、婴儿车 CPN 8/2007、学步车 CPN 1/2013、洗澡辅助器 2017、安抚奶嘴 2017、儿童汽车约束 CPN 3/2014、游泳浮具 2017；奶瓶自喂装置永久禁令 2026（2026-05-26 起） [SRC-AU-GOV-LEG-F2024L00891] [SRC-AU-GOV-LEG-F2024L00892] [SRC-AU-GOV-LEG-F2026L00610] [SRC-AU-GOV-PSA-INFANT-SLEEP] |
| 必需的认证/测试 | 对应 AS/NZS、EN、ASTM 标准报告；喂养用品 EN 14372/EN 14350 + 食品接触 + BPA；床护栏 ASTM F2085-19/BS 7972 [SRC-AU-AMZ-GUG6JJCDN6YYQYJP] [SRC-AU-AMZ-GXPFG3RRZB9WFPJE] |
| 注册/备案 | 无 |
| 标签要求 | 婴儿睡眠/倾斜产品：耐久警示 + 原产国 + 澳洲进口商/分销商名称（永久标记）；洗澡辅助器溺水警示；婴儿车警示等 |
| 亚马逊禁售 | 床围、睡眠定位器、加重睡眠产品、充气旅行床、自主喂养产品、带温度传感器浴盆、可拆侧栏婴儿床、儿童约束背心/织物座椅/增高座椅/上拉带、3 岁以下口罩 [SRC-AU-AMZ-GRLKLZ6WQ9R259LC] |
| 主管机构 | ACCC |
| 规则ID | [R:AU-L3-ACCC-002] [R:AU-L3-ACCC-003] [R:AU-L3-ACCC-004] [R:AU-L3-ACCC-014] [R:AU-L3-ACCC-020] [R:AU-L3-ACCC-022] [R:AU-L3-ACCC-023] [R:AU-L3-ACCC-032] [R:AU-L3-ACCC-039] [R:AU-L3-FEEDING-001] [R:AU-L3-BEDRAIL-001] [R:AU-L1-CHILD-001] [R:AU-L1-INFANT-001] [R:AU-L1-BATHTUB-001] |

### E.7 食品接触材料

| 项目 | 内容 |
| --- | --- |
| 适用法规 | 澳洲未见独立的食品接触材料注册/符合性声明制度（本次未查到专门法规，待核实）；亚马逊禁售含 BPA 产品；婴幼儿喂养用品须按欧盟 FCM 法规测试；施釉陶瓷食具进口须金属溶出证书（CPIR 4E/附表 7）；一次性塑料餐具禁售 [SRC-AU-AMZ-G200164570] [SRC-AU-GOV-LEG-F1996B03651] [SRC-AU-AMZ-GMMCLBZWLHDEWEKS] |
| 必需的认证/测试 | 陶瓷：NMI 或 NATA 实验室铅镉溶出证书；婴童餐具：EN 14372、(EC) 1935/2004、(EU) 10/2011、(EU) 2018/213 |
| 注册/备案 | 无 |
| 标签要求 | — |
| 主管机构 | ABF；ACCC；各州食品管理部门 |
| 规则ID | [R:AU-L1-HAZMAT-001] [R:AU-L6-CERAMIC-001] [R:AU-L3-FEEDING-001] [R:AU-L1-PLASTIC-001] |

### E.8 化妆品

| 项目 | 内容 |
| --- | --- |
| 适用法规 | 化妆品信息标准 2020（ACL）；AICIS（工业化学品引入）；毒物标准（SUSMP）；TGA 治疗用品边界；防晒（TGA/AS/NZS 2604）；海关附表 2（铅 >250 mg/kg 禁入） [SRC-AU-GOV-LEG-F2020L01469] [SRC-AU-GOV-AICIS-COSMETICS] [SRC-AU-GOV-LEG-F2026L01327] [SRC-AU-GOV-TGA-COSMETIC-OR-THERAPEUTIC] |
| 必需的认证/测试 | 成分合规（汞、氢醌 ≤2%、铅 ≤10 mg/kg、禁用邻苯、过氧化物美白限值）；防晒 SPF 测试 |
| 注册/备案 | 进口前 AICIS 企业注册 + 年度申报（11 月 30 日前）；主要防晒或 SPF>15 保湿须 ARTG |
| 标签要求 | 英文/INCI 全成分降序标注于容器；酒精洗手液标 %v/v 及 5 条警示 |
| 亚马逊禁售 | 处方类、美瞳、Latisse/Obagi、氢醌 >2%、汞、Kohl、永久睫毛染、henna 纹身、过氧化氢 >6%/过氧化脲 >18% 美白、tester、过期/拆封 [SRC-AU-AMZ-G200164470] |
| 主管机构 | ACCC；AICIS；TGA；州卫生部门 |
| 规则ID | [R:AU-L1-COSMETIC-001] [R:AU-L1-COSMETIC-002] [R:AU-L3-ACCC-015] [R:AU-L5-AICIS-001] [R:AU-L5-POISONS-001] [R:AU-L5-TGA-002] [R:AU-L5-TGA-003] |

### E.9 个护健康电器

| 项目 | 内容 |
| --- | --- |
| 适用法规 | EESS（美发器、剃须/理发器、按摩器为 Level 3）；TGA（作治疗宣称即为医疗器械）；ACCC 热水袋标准 [SRC-AU-GOV-EESS-LEVELS] [SRC-AU-GOV-TGA-DEVICE-ARTG] [SRC-AU-GOV-LEG-F2008L00651] |
| 必需的认证/测试 | AS/NZS 60335.2.8 / 2.23；RECS CoC |
| 注册/备案 | EESS 注册 |
| 标签要求 | RCM；不得作治疗宣称（除非 ARTG） |
| 亚马逊禁售 | UVC 消毒器/灯泡、电热水袋 [SRC-AU-AMZ-G5ZEPL3F3YQR5GUS] [SRC-AU-AMZ-GRLKLZ6WQ9R259LC] |
| 主管机构 | EESS 监管机构；TGA；ACCC |
| 规则ID | [R:AU-L3-HAIR-001] [R:AU-L3-ACCC-021] [R:AU-L1-UVC-001] [R:AU-L1-ELEC-005] [R:AU-L5-TGA-001] |

### E.10 医疗器械与药品

| 项目 | 内容 |
| --- | --- |
| 适用法规 | 《治疗用品法 1989》、医疗器械条例 2002、毒物标准、广告守则 2021 [SRC-AU-GOV-LEG-F2002B00237] [SRC-AU-GOV-TGA-ADVERTISING-REPRESENTATIONS] |
| 必需的认证/测试 | ARTG 列入（器械 Class I–III；药品 AUST L/R） |
| 注册/备案 | 澳洲申办者（sponsor）向 TGA 申请；亚马逊要求 ARTG 证书/公开摘要 + 申办者证明或授权信/采购发票 [SRC-AU-AMZ-GL7SLDV3WUGZAEQZ] [SRC-AU-AMZ-GV8XARHLGCMHQY5C] |
| 标签要求 | 详情页显示 ARTG 号、药名、警示语；附表 3/4/8/9/10 药品亚马逊禁售 |
| 主管机构 | TGA |
| 规则ID | [R:AU-L3-TGA-001] [R:AU-L3-MEDDEV-001] [R:AU-L5-TGA-001] [R:AU-L1-DRUGS-001] [R:AU-L1-DRUGS-002] |

### E.11 农药与抗菌/杀菌宣称

| 项目 | 内容 |
| --- | --- |
| 适用法规 | Agvet Code（APVMA）；TGO 104（消毒剂，TGA）；Agvet Code 条例附表 3 的“处理物品”排除 [SRC-AU-GOV-APVMA-REGISTRATION] [SRC-AU-GOV-LEG-F1996B00288] [SRC-AU-GOV-TGA-DISINFECTANTS] |
| 必需的认证/测试 | APVMA 产品注册（标签带 APVMA 号）；消毒剂特定宣称须 ARTG |
| 注册/备案 | APVMA（海外注册人须澳洲代理人）；亚马逊农药类目审核 [SRC-AU-AMZ-GQR5FX94UKK38Q9Q] |
| 标签要求 | 不得写 safe/non-toxic/harmless/all natural；不得作公共卫生宣称；家用消毒剂不得称 hospital grade |
| 要点 | 抗菌织物/塑料只要不对外宣称杀灭害虫可免注册；一旦宣称杀菌/驱虫即失去排除；APVMA 称超声波等声/光/电磁驱虫设备无需注册，但亚马逊将“未经 APVMA 注册的驱虫装置”列为禁售，实际不可售（口径冲突，见待核实）[SRC-AU-AMZ-G202115120] [SRC-AU-GOV-APVMA-SCOPE] |
| 主管机构 | APVMA；TGA |
| 规则ID | [R:AU-L1-PESTICIDE-001] [R:AU-L2-PESTICIDE-001] [R:AU-L5-APVMA-001] [R:AU-L5-TGA-004] |

### E.12 化学品

| 项目 | 内容 |
| --- | --- |
| 适用法规 | AICIS；毒物标准；海关条例（ODS/SGG 许可、汞、石棉）；亚马逊危险品与安全限制清单 [SRC-AU-GOV-AICIS-WHO-MUST-REGISTER] [SRC-AU-GOV-LEG-F1996B03651] |
| 必需的认证/测试 | SDS（FBA）；脱漆剂不得含二氯甲烷/NMP |
| 注册/备案 | AICIS 企业注册；ODS/SGG 进口许可证（制冷剂、预充装空调等） |
| 亚马逊禁售 | 含 BPA 产品、四氯化碳、氢氟酸、硝酸、红磷、铝热剂、氰化物、PCB、仅限专业用途化学品、叠氮化钠、三氯乙酸、灭火球 [SRC-AU-AMZ-G200164570] [SRC-AU-AMZ-GRLKLZ6WQ9R259LC] |
| 主管机构 | AICIS；DCCEEW；ABF |
| 规则ID | [R:AU-L1-HAZMAT-001] [R:AU-L1-CHEM-001] [R:AU-L5-AICIS-001] [R:AU-L6-ODS-001] [R:AU-L4-DG-001] |

### E.13 刀具与武器

| 项目 | 内容 |
| --- | --- |
| 适用法规 | 海关（禁止进口）条例第 4F/4H 条、附表 6/13（2026-01-22 起新增公共安全测试）；各州武器法（新州《武器禁止法 1998》、维州《武器管控法 1990》、昆州《武器类别条例 1997》、西澳《武器条例 1999》、南澳《简易罪行法》、首都领地《禁止武器法 1996》、北领地、塔州） [SRC-AU-GOV-LEG-F1996B03651] [SRC-AU-GOV-ABF-WEAPONS] [SRC-AU-GOV-VICPOL-PROHIBITED] [SRC-AU-GOV-QLD-WEAPONS-CAT] |
| 必需的认证/测试 | 进口许可（部长 B710 或警察证明 B709A/B709B），普通卖家基本无法取得 |
| 注册/备案 | — |
| 销售限制 | 多数州 18 岁以下禁购刀具（新州、首都领地 16 岁）；昆州规定适用于州外网店；维州 2025-09-01 起砍刀为禁止武器；南澳 2025-07-01 起剑和砍刀为禁止武器 [SRC-AU-GOV-QPS-KNIFE-SELLERS] [SRC-AU-GOV-VICPOL-MACHETE] [SRC-AU-GOV-SA-LAWHANDBOOK-WEAPONS] [SRC-AU-GOV-WAPOL-KNIFE] |
| 州法差异（简表） | 弹弓：维州、西澳全部禁止，其他州主要禁带臂托款；水弹枪：新州、首都领地按枪支，维州、西澳禁止，昆州管控 18+，塔州 2025-11-19 起未改装不算枪支；激光笔：维州/首都领地/北领地 >1 mW 禁止或管控，西澳任何功率管控；OC 喷雾：维州、首都领地、北领地禁止，西澳管控，昆州 R 类许可 [SRC-AU-GOV-VICPOL-PROHIBITED] [SRC-AU-GOV-WAPOL-KNIFE] [SRC-AU-GOV-ACT-PROHIBITED-WEAPONS] [SRC-AU-GOV-QLD-WEAPONS-CAT] |
| 主管机构 | ABF；各州/领地警察 |
| 规则ID | [R:AU-L1-WEAPON-001] [R:AU-L1-WEAPON-002] [R:AU-L1-WEAPON-003] [R:AU-L1-WEAPON-004] [R:AU-L5-WEAPON-001] [R:AU-L5-WEAPON-002] [R:AU-L6-CUSTOMS-001] [R:AU-L6-CUSTOMS-002] |

### E.14 激光产品

| 项目 | 内容 |
| --- | --- |
| 适用法规 | 海关条例附表 13 第 44 项（>1 mW 手持激光笔进口须许可）；各州武器法；亚马逊仅允许 ≤1 mW 激光笔 [SRC-AU-GOV-LEG-F1996B03651] [SRC-AU-AMZ-G201689020] |
| 必需的认证/测试 | 激光等级/功率检测（建议），≤1 mW |
| 注册/备案 | — |
| 标签要求 | —（未查到 ACL 层面的激光笔强制标准，待核实） |
| 主管机构 | ABF；各州警察 |
| 规则ID | [R:AU-L1-LASER-001] [R:AU-L6-LASER-001] [R:AU-L5-WEAPON-002] |

### E.15 无人机与遥控模型

| 项目 | 内容 |
| --- | --- |
| 适用法规 | 无线电部分按 ACMA 规定（RCM、DoC）；CASA 飞行与注册规则约束操作者，本次未取得 CASA 具体条款，待核实 |
| 必需的认证/测试 | 射频符合性（AS/NZS 4268 等） |
| 注册/备案 | ACMA 供应商注册；（CASA 无人机注册要求待核实） |
| 标签要求 | RCM |
| 主管机构 | ACMA；CASA |
| 规则ID | [R:AU-L5-ACMA-001] [R:AU-L4-DG-001] |

### E.16 汽配

| 项目 | 内容 |
| --- | --- |
| 适用法规 | ACCC：车辆千斤顶、卧式千斤顶、支撑架、便携坡道、救援带、儿童约束、四轮摩托、迷你摩托强制标准；有色大灯罩永久禁令（透光 <85%）；海关石棉管控（刹车片、垫片） [SRC-AU-GOV-LEG-F2010L00295] [SRC-AU-GOV-LEG-F2010L03297] [SRC-AU-GOV-ABF-ASBESTOS-GOODS] |
| 必需的认证/测试 | AS/NZS 2693、AS 2615、AS 2538、AS 2640、AS/NZS 1754、ANSI/SVIA 1 或 EN 15997；刹车片石棉“未检出”报告 |
| 注册/备案 | — |
| 标签要求 | 救援带、千斤顶警示；四轮摩托侧翻警示与吊牌 |
| 亚马逊禁售 | 需上牌车辆、排放破解装置、气囊/安全带及部件、里程表篡改、方向盘配重、遮挡车牌喷剂、干扰器、汽车座椅加热垫 [SRC-AU-AMZ-G200164410] [SRC-AU-AMZ-GRLKLZ6WQ9R259LC] |
| 主管机构 | ACCC；ABF |
| 规则ID | [R:AU-L1-AUTO-001] [R:AU-L1-AUTO-002] [R:AU-L1-HEATED-001] [R:AU-L3-ACCC-014] [R:AU-L3-ACCC-024] [R:AU-L3-ACCC-030] [R:AU-L3-ACCC-035] [R:AU-L3-ACCC-036] [R:AU-L3-ACCC-045] [R:AU-L3-ACCC-046] [R:AU-L3-ACCC-047] [R:AU-L6-ASBESTOS-001] |

### E.17 家具与木制品

| 项目 | 内容 |
| --- | --- |
| 适用法规 | 易倾倒家具信息标准 2024（2025-05-04 起）；双层床 CPN 1/2003；豆袋 2014；生物安全（木竹藤制品、ISPM 15 包装、BMSB 季节措施）；人造石进口禁令 [SRC-AU-GOV-LEG-F2024L00512] [SRC-AU-GOV-PSA-TOPPLING] [SRC-AU-GOV-DAFF-TIMBER-PACKAGING] [SRC-AU-GOV-DAFF-BMSB] |
| 必需的认证/测试 | 双层床 AS/NZS 4220；豆袋拉链与警示 |
| 注册/备案 | — |
| 标签要求 | ≥686 mm 储物家具与任意高度电视柜：永久防倾倒警示 + 说明书警示 + 在线 listing 警示 |
| 主管机构 | ACCC；DAFF |
| 规则ID | [R:AU-L3-ACCC-040] [R:AU-L3-ACCC-011] [R:AU-L3-ACCC-007] [R:AU-L6-BIOSEC-002] [R:AU-L6-BIOSEC-004] [R:AU-L6-ENGSTONE-001] [R:AU-L4-FBA-002] |

### E.18 纺织服装

| 项目 | 内容 |
| --- | --- |
| 适用法规 | 护理标签信息标准 2023（2025-03-05 起完全适用）；儿童睡衣安全标准 2017（AS/NZS 1249:2014）；猫狗毛皮进口禁令 [SRC-AU-GOV-LEG-F2023L01187] [SRC-AU-GOV-LEG-F2017L00452] [SRC-AU-GOV-LEG-F1996B03651] |
| 必需的认证/测试 | 儿童睡衣燃烧性能分类报告 |
| 注册/备案 | — |
| 标签要求 | 英文永久护理标签（AS/NZS 1957 或 ISO 3758 符号）；儿童睡衣火险标签 |
| 亚马逊禁售 | 二手服装鞋履；7 岁及以下带帽绳/领口抽绳外穿上衣；美人鱼尾泳衣；电池承重的电热服装 [SRC-AU-AMZ-G200164430] [SRC-AU-AMZ-G8FDB4PSHS4AACQ5] |
| 主管机构 | ACCC；ABF |
| 规则ID | [R:AU-L3-ACCC-013] [R:AU-L3-ACCC-026] [R:AU-L1-CLOTHING-001] [R:AU-L1-CHILD-002] [R:AU-L1-HEATED-001] [R:AU-L6-FUR-001] |

### E.19 珠宝

| 项目 | 内容 |
| --- | --- |
| 适用法规 | ACL（误导性宣称）；贵金属印记规则（亚马逊珠宝质量标准）；金伯利进程；CITES [SRC-AU-AMZ-G200166630] [SRC-AU-AMZ-G201269180] |
| 必需的认证/测试 | 成色检测（金 ≥10K 才可称 gold；925 银；950 铂） |
| 注册/备案 | Jewelry 类目审核 |
| 标签要求 | 印记附商标或制造商名；“hypoallergenic”不得含镍 |
| 主管机构 | ACCC；DCCEEW（CITES） |
| 规则ID | [R:AU-L1-JEWELRY-001] [R:AU-L2-JEWELRY-001] [R:AU-L6-CITES-001] [R:AU-L5-BAN-003] |

### E.20 宠物用品与宠物药

| 项目 | 内容 |
| --- | --- |
| 适用法规 | APVMA（兽药、跳蚤蜱虫产品；宠物食品 4 项排除条件）；生物安全（宠物食品、生皮咬胶） [SRC-AU-GOV-APVMA-SCOPE] [SRC-AU-GOV-LEG-F2021L00258] |
| 必需的认证/测试 | 宠物食品质量体系（如 AS 5812-2023 等） |
| 注册/备案 | 兽药 APVMA 注册 |
| 亚马逊禁售 | 电击/尖刺项圈、脊椎动物粘捕板、未注册宠物药、疫苗、观赏鱼抗生素 [SRC-AU-AMZ-G200164370] |
| 主管机构 | APVMA；DAFF |
| 规则ID | [R:AU-L1-ANIMAL-003] [R:AU-L1-ANIMAL-004] [R:AU-L5-APVMA-002] [R:AU-L6-BIOSEC-003] |

### E.21 植物、种子、园艺

| 项目 | 内容 |
| --- | --- |
| 适用法规 | 《生物安全法》与 BICON（种子须为允许物种、植物检疫证书；活植物须许可/检疫；土壤须许可或处理）；州肥料法规；州一次性塑料法规 [SRC-AU-GOV-DAFF-SEEDS] [SRC-AU-AMZ-GD85NFMCQF2KNM2N] |
| 必需的认证/测试 | 植物检疫证书；2025-07-01 起十字花科、葫芦科种子须进口许可 |
| 注册/备案 | — |
| 亚马逊禁售 | 境外卖家不得销售任何活体植物/植物产品/种子；境外卖家不得销售肥料；网孔 >5 mm 果树网 [SRC-AU-AMZ-G201737480] [SRC-AU-AMZ-GLL2YRZB4BUQBSLM] |
| 主管机构 | DAFF；州农业部门 |
| 规则ID | [R:AU-L1-PLANT-001] [R:AU-L1-FERTILISER-001] [R:AU-L1-NETTING-001] [R:AU-L6-BIOSEC-001] |

### E.22 食品与保健品

| 项目 | 内容 |
| --- | --- |
| 适用法规 | 《澳新食品标准法典》（标准 1.2.1 标签、2.9.1 婴儿配方、2.9.4 运动食品、1.4.4 大麻籽）；《进口食品管制法 1992》与 IFIS；原产国食品标签信息标准 2016；TGA 宣布的治疗用品令（口服美容、片剂运动补充剂） [SRC-AU-GOV-FSANZ-IMPORTED] [SRC-AU-GOV-DAFF-IFIS] [SRC-AU-GOV-LEG-F2016L00528] [SRC-AU-GOV-LEG-F2019L01352] |
| 必需的认证/测试 | 进口检验（风险食品 100% 起）；必要时证书 |
| 注册/备案 | 亚马逊食品类目审核（暂不接受生鲜冷冻）；治疗性补充剂 AUST L |
| 标签要求 | 英文标签、营养信息、过敏原、DD/MM/YYYY 有效期、澳洲供应商名址、原产国声明（优先食品加框） |
| 亚马逊禁售 | 未注册配方奶、HiPP、魔芋果冻杯、中国产含肉食品、槟榔、疯蜜、卡瓦、育亨宾、麻黄、CBD 等 [SRC-AU-AMZ-G200164550] [SRC-AU-AMZ-G201829010] |
| 主管机构 | FSANZ；DAFF；州食品机构；TGA |
| 规则ID | [R:AU-L1-FOOD-001] [R:AU-L1-SUPP-001] [R:AU-L1-CBD-001] [R:AU-L2-FOOD-001] [R:AU-L2-FORMULA-001] [R:AU-L3-FOOD-001] [R:AU-L5-FOOD-001] [R:AU-L5-FOOD-002] [R:AU-L5-FOOD-003] [R:AU-L5-TGA-002] [R:AU-L5-BAN-003] |

### E.23 烟草与电子烟

| 项目 | 内容 |
| --- | --- |
| 适用法规 | 电子烟改革（2024-01-01、2024-03-01、2024-07-01、2024-10-01 分阶段）；毒物标准（尼古丁附表 4）；海关条例 4DA（烟草）、5A（电子烟）；烟草广告禁止法 [SRC-AU-GOV-TGA-VAPES-JUL2024] [SRC-AU-GOV-TGA-VAPES-RETAILERS] [SRC-AU-GOV-ABF-VAPES] |
| 要点 | 仅药房可售治疗性电子烟；非药房零售、商业持有（≥9 支器具/60 配件/400 mL）违法；亚马逊澳洲禁售全部烟草、电子烟及多数吸烟配件 |
| 主管机构 | TGA；ODC；ABF；卫生部 |
| 规则ID | [R:AU-L1-TOBACCO-001] [R:AU-L1-VAPE-001] [R:AU-L5-VAPE-001] [R:AU-L6-TOBACCO-001] |

### E.24 酒类

| 项目 | 内容 |
| --- | --- |
| 适用法规 | 州/领地酒类许可法；FSANZ 标准 2.7.1（酒精含量、标准饮酒量） [SRC-AU-AMZ-GM9BQPTJNXU2KEDW] |
| 注册/备案 | 澳洲酒类许可证 + 亚马逊审核 + 年龄核验承运商 |
| 标签要求 | 英文标签、DD/MM/YYYY、酒精度与标准饮酒量 |
| 主管机构 | 州/领地酒类监管机构；FSANZ |
| 规则ID | [R:AU-L1-ALCOHOL-001] [R:AU-L2-ALCOHOL-001] |

### E.25 成人用品

| 项目 | 内容 |
| --- | --- |
| 适用法规 | 分级法（RC 内容禁止进口/销售）；海关条例 4A（儿童外观性爱娃娃明确禁止） [SRC-AU-GOV-LEG-F1996B03651] |
| 亚马逊要求 | 带头部的性爱娃娃（充气娃娃除外）禁售；须放入 Sexual Wellness 子类目、仅新品、无裸露、标有效期 [SRC-AU-AMZ-G200339940] |
| 主管机构 | 分级委员会；ABF |
| 规则ID | [R:AU-L1-ADULT-001] [R:AU-L3-ADULT-001] [R:AU-L6-RC-001] |

### E.26 二手与翻新

| 项目 | 内容 |
| --- | --- |
| 适用法规 | ACL 消费者保障（不可排除）；召回商品禁售 [SRC-AU-AMZ-G200164750] |
| 亚马逊要求 | 按状态指南选择状态；消耗/入口/外用品仅可新品；二手服装鞋履、开封化妆品禁售；部分二手商品需审核 [SRC-AU-AMZ-G200339950] |
| 主管机构 | ACCC |
| 规则ID | [R:AU-L2-USED-001] [R:AU-L1-CLOTHING-001] [R:AU-L1-RECALL-001] |

### E.27 卫浴、节水、燃气与其他

| 项目 | 内容 |
| --- | --- |
| WaterMark | 龙头、花洒、马桶、洁身器、接饮用水的净水器、软管等须 WaterMark 认证（标志+许可证号），2026-05-01 起仅可生产无铅认证产品、2028-05-01 起仅可安装无铅产品；亚马逊禁售未认证或宣传 DIY 安装的接水洁身器 [R:AU-L5-WATERMARK-001] [R:AU-L1-PLUMBING-001] [R:AU-L3-PLUMBING-001] [SRC-AU-GOV-WATERMARK-SCHEDULE] [SRC-AU-GOV-WATERMARK-LEADFREE] [SRC-AU-AMZ-GVVAHF4S3EZ7FPAY] |
| WELS | 龙头、花洒、马桶、小便器、限流器、洗碗机、洗衣机须 WELS 注册与星级标签（AS/NZS 6400） [R:AU-L5-WELS-001] [SRC-AU-GOV-LEG-F2013L01574] |
| GEMS | 空调、冰箱、洗衣机、干衣机、洗碗机、电视、显示器、外置电源、LED 灯等须在供应或要约供应前注册型号，零售须随附能效标签 [R:AU-L5-GEMS-001] [SRC-AU-GOV-LEG-C2012A00132] |
| 燃气器具 | 须经 GTRC 认可机构认证、带数据铭牌并列入国家数据库；亚马逊要求 GCM 标志与认证号；维州不接受海外 CSA/CE；LCC27 转接头与 LPG 柜式取暖器禁售 [R:AU-L5-GAS-001] [R:AU-L3-GAS-001] [R:AU-L1-GAS-001] [SRC-AU-GOV-GTRC] [SRC-AU-GOV-ESV-GAS-ONLINE] [SRC-AU-AMZ-G5L9AARKDVRSGCWR] |
| 电动出行 | NSW 2026-02-01 起整车、电池、充电器须认证并带批准标识（listing 须展示）；联邦 2026-08 指示 ACCC 制定全国标准 [R:AU-L5-EMOB-001] [R:AU-L3-EMOB-001] [SRC-AU-GOV-NSW-EMOBILITY] [SRC-AU-GOV-TREASURY-EBIKE-2026] |
| 环保宣称 | 不得使用未限定的 eco-friendly/sustainable/green 宣称 [R:AU-L3-CLAIMS-001] [SRC-AU-AMZ-GJDWGWRZQJPFBN9P] |

### E.28 进口与清关要求汇总（L6）

以下为《海关（禁止进口）条例 1956》（CPIR）、生物安全（BICON）、CITES 与 GST 等进口环节要求；CPIR 的结构为：附表 1 绝对禁止、附表 2 须部长许可、附表 3 有条件进口，武器在第 4H 条/附表 13，枪支与仿真枪在第 4F 条/附表 6 [SRC-AU-GOV-LEG-F1996B03651]。

| 主题 | 要求 | 规则ID |
| --- | --- | --- |
| 《海关（禁止进口）条例》附表 13：弹簧/辅助开刀、蝴蝶刀、推刀、暗藏刀、指虎、电击器、防狼喷雾等进口须部长许可（多数无消费者途径） | CPIR 第 4H 条/附表 13 第 2 部分规定以下武器进口须内政部长书面许可（表格 B710）：仅部长许可（无警察证明途径）的有弹道刀、自动刀（含“辅助开启”折刀）、暗藏刀刃/尖刺物品（皮带扣刀、梳子刀）、刀鞘可缩入刀柄的刀、推刀、战壕刀、爪刀（karambit）、非金属非陶瓷刀刃、蝴蝶刀，以及指虎、带凸起手套、手爪、加重手套、电击器（含电击手电，≤6 V 屏蔽网电蚊拍除外）、声波驱散装置、电池喷射气体/液体的手持装置、防狼/OC 喷雾；可经警察证明（表格 B709B）的有双刃匕首、飞镖星、飞刀/飞斧、吹箭、双节棍、弩（玩具弩除外）、带臂托或扳机的弹弓、钉头锤、链枷、防弹衣（防弹/防破片）、伸缩棍、>1 mW 手持激光笔。2026-01-22 起新增“公共安全测试”，可拒绝任何进口。最高 2,500 罚款单位和/或 10 年监禁。 | [R:AU-L6-CUSTOMS-001] [SRC-AU-GOV-LEG-F1996B03651] [SRC-AU-GOV-ABF-WEAPONS] |
| 仿真枪（无论颜色，含逼真玩具枪/NERF 类、游戏手柄）、水弹枪/Airsoft 及零件和水弹，按枪支管制进口须警察证明 | CPIR 第 4F 条/附表 6：仿真枪（外观像枪且可能被合理认为是枪，不论颜色；ABF 称可包括摆件、玩具、游戏手柄、NERF 类玩具）进口须州/领地枪支登记处出具警察证明（B709A）；水弹枪和 Airsoft（“skirmish markers”）按枪支管理（附表 6 第 14B 项），包括零件、弹匣以及水弹本身（塑料/聚合物/吸水聚合物弹珠），并须满足序列号和安全测试要求；彩弹枪及彩弹为 14A 项。2026-01-22 起增加公共安全测试。 | [R:AU-L6-CUSTOMS-002] [SRC-AU-GOV-LEG-F1996B03651] [SRC-AU-GOV-ABF-IMITATION-FIREARMS] |
| 进口重金属限量（附表 2）：玩具涂层、铅笔/画笔、仿食物橡皮擦、存钱罐铅 ≤90 mg/kg 等；化妆品铅 ≤250 mg/kg | CPIR 附表 2 规定超限商品须部长许可方可进口：玩具涂层限量为铅 90、砷 25、锑 60、镉 75、硒 500、汞 60、铬 60、钡 1000（mg/kg）；铅笔和画笔、仿食物外形橡皮擦同限；存钱罐铅 >90 mg/kg；化妆品铅 >250 mg/kg（醋酸铅染发剂除外）。 | [R:AU-L6-CUSTOMS-003] [SRC-AU-GOV-LEG-F1996B03651] [SRC-AU-GOV-ABF-LIST] |
| 可达输出 >1 mW 的手持激光笔进口须许可（附表 13 第 44 项，警察证明） | CPIR 附表 13 第 44 项：手持激光指示器或类似装置可达发射功率 >1 mW 的，进口须通过官方用途、指定人员、经销商或警察证明等测试取得许可；警察证明须由州/领地警察出具进口人持证或无需持证的声明。 | [R:AU-L6-LASER-001] [SRC-AU-GOV-LEG-F1996B03651] [SRC-AU-GOV-ABF-WEAPONS] |
| 石棉绝对禁止进口（任何含量），高风险商品（蜡笔、彩沙、刹车片、垫片、滑石产品、养蜂熏烟器等）须提供 NATA/ILAC 认可实验室“未检出”报告 | CPIR 第 4C 条禁止进口含任何量石棉的商品，“asbestos free”标签及海外阈值（<0.1%/<1%）不被接受，含天然石棉的矿物商品（石材、滑石）也受限。ACN 2024/32（2024-09-03）：ABF 对 100% 进口做风险评估，仅凭声明不构成证据；须提供 NATA 或经 ILAC/APAC 互认的海外实验室以 PLM/DS 方法、针对该批货物出具的英文报告，写明“任何水平均未检出石棉”（不接受便携 XRF）；否则货物被扣并在澳检测，费用由进口商承担，且石棉货物不得邮寄。高风险商品包括刹车片/刹车蹄与离合器片、垫片和密封件、水泥板/夹芯板、组装房、蜡笔、彩色沙、含滑石产品、纹理涂料、胶粘剂、灭火毯、手套、纱线、取暖设备、养蜂熏烟器、切割石材；自 2015 年起原产中国的儿童蜡笔和玩具套装须回答石棉问题，ACN 2025/33 自 2025-12-04 起对彩沙/造型膏/部分玩具税号（2505.10.00、2505.90.00、3407.00.00、9503.00.30、9503.00.99）新增石棉问题。含石棉防毒面具亦为 ACCC 永久禁令。 | [R:AU-L6-ASBESTOS-001] [SRC-AU-GOV-LEG-F1996B03651] [SRC-AU-GOV-ABF-ASBESTOS] [SRC-AU-GOV-ABF-ASBESTOS-GOODS] [SRC-AU-GOV-ABF-ACN-2024-32] [SRC-AU-GOV-ABF-ACN-2025-33] [SRC-AU-GOV-ABF-ACN-2015-27] |
| 猫狗毛皮及含猫狗毛皮的商品禁止进口（部长许可除外） | CPIR 第 4W 条：进口家猫（Felis catus）或家犬（Canis familiaris）毛皮及全部或部分由其制成的商品须部长许可，实际上禁止；涵盖毛皮镶边服装、玩具及配饰。亚马逊亦禁售猫狗制品（AU-L1-ANIMAL-001）。 | [R:AU-L6-FUR-001] [SRC-AU-GOV-LEG-F1996B03651] [SRC-AU-GOV-ABF-LIST] |
| 完税价 ≤A$5 的一次性/新奇/可充气打火机进口须提交符合美国标准的合规证书法定声明 | CPIR 第 4S 条：海关价值 A$5 或以下的一次性、新奇或可充气卷烟打火机，进口时须提供符合美国标准的合规证书的法定声明，或取得财政部长许可（ACCC 管理）。 | [R:AU-L6-LIGHTER-001] [SRC-AU-GOV-LEG-F1996B03651] [SRC-AU-GOV-ABF-LIST] |
| 施釉陶瓷食品器皿进口须附 NMI 或 NATA 认可实验室的金属溶出检测证书 | CPIR 第 4E 条/附表 7：施釉陶瓷餐具等食品器皿进口须提供国家计量院（NMI）或 NATA 认可实验室出具的金属（铅/镉）溶出检测证书；仅作装饰陈列的物品豁免。 | [R:AU-L6-CERAMIC-001] [SRC-AU-GOV-LEG-F1996B03651] [SRC-AU-GOV-ABF-LIST] |
| 臭氧消耗物质及合成温室气体（HFC/HCFC 等，含预充装空调、制冷设备、气雾剂、灭火器）进口须 DCCEEW 许可证 | CPIR 第 5K 条：HFC、HCFC 等气体及含这些气体的空调与制冷设备、气雾剂、灭火器进口须 DCCEEW 许可证。小量及 R600a/R290/CO2 设备豁免、HCFC 设备禁入、2024-07-01 起 GWP >750 的小型空调禁入等细节仅见搜索摘要，待核实。 | [R:AU-L6-ODS-001] [SRC-AU-GOV-LEG-F1996B03651] [SRC-AU-GOV-ABF-LIST] |
| 烟草（卷烟、散烟丝、水烟烟草、加热不燃烧）进口须 ABF 许可、不得国际邮寄；电子烟商品进口须 ODC 许可证与许可且不得邮寄 | CPIR 第 4DA 条（2019-07-01 起）：卷烟、散装烟草、水烟烟草和加热不燃烧产品进口须 ABF 许可，不得通过国际邮件进口，商业货物须符合平装规定；第 5A 条：电子烟器具、配件、烟油及所有液态尼古丁进口须 ODC 许可证和许可、不得邮寄（一次性电子烟 2024-01-01 起，其他 2024-03-01 起），仅限向药房供货的生产商或研究机构，消费者即使有处方也不能自行进口。嚼烟/鼻烟附表 3 第 12 项限 1.5 kg。 | [R:AU-L6-TOBACCO-001] [SRC-AU-GOV-LEG-F1996B03651] [SRC-AU-GOV-ABF-VAPES] |
| 违禁物品（拒绝分级 RC 出版物/影片/游戏、儿童外观性爱娃娃）禁止进口；2026-01-22 起扩展至暴力极端主义材料和“禁止符号”（如纳粹标志）商品 | CPIR 第 4A 条：RC 出版物、影片、电脑游戏，以及明确点名的儿童外观性爱娃娃禁止进口；2026-01-22 起（《打击反犹、仇恨与极端主义（枪支与海关法）法 2026》）扩展至“暴力极端主义材料”和印有“禁止符号”（如纳粹符号）的任何实物商品（含旗帜），并取消 25 件“商业数量”门槛。许可仅由分级委员会主任在极有限情况下签发。 | [R:AU-L6-RC-001] [SRC-AU-GOV-LEG-F1996B03651] [SRC-AU-AMZ-G200164670] |
| 带“ANZAC”字样、皇家纹章、联邦/州纹章或旗帜图案的商品进口须相应批准 | CPIR 第 4V 条：带“ANZAC”字样的商品须退伍军人事务部（DVA）许可；附表 2 第 16 项：皇家纹章图像须许可；附表 3 第 10 项：联邦纹章/旗帜/印章须总理内阁部设计批准，第 10A 项：州/领地纹章或旗帜须州长部门批准。 | [R:AU-L6-SYMBOLS-001] [SRC-AU-GOV-LEG-F1996B03651] [SRC-AU-GOV-ABF-LIST] |
| 种子进口须为 BICON 允许物种、洁净、新包装标注属种名，多数须植物检疫证书；活植物须许可、检验和隔离；土壤须许可或处理 | 种子：物种须列于 BICON（否则须先做杂草风险评估），种子须洁净、装于标有属和种名的新包装，多数须植物检疫证书（2022-04-28 起谷斑皮蠹措施），2025-07-01 起十字花科、葫芦科种子须进口许可。活植物（苗木）一律须许可、检验及入境后隔离。土壤须许可或经批准处理（影响盆景、生态瓶、营养土）。亚马逊另禁止境外卖家销售任何植物和种子（AU-L1-PLANT-001）。 | [R:AU-L6-BIOSEC-001] [SRC-AU-GOV-DAFF-SEEDS] [SRC-AU-GOV-LEG-F2021L00258] |
| 木制品、竹藤制品须无树皮、无虫蛀；竹须干燥不可萌发；木质包装须 ISPM 15 处理与标识 | 木制品与竹、藤制品须干燥、不可萌发、无树皮（带树皮者另有 BICON 条件）、无昆虫和蛀孔，否则可能被检验、处理或销毁；木质包装（托盘、木箱等）须经 ISPM 15 处理并加盖标识，海运货物须附包装声明；厚度 ≤6 mm 的木材、胶合板、刨花板豁免，不合规包装由进口商承担处理、退运或销毁费用。 | [R:AU-L6-BIOSEC-002] [SRC-AU-GOV-DAFF-TIMBER-PACKAGING] [SRC-AU-GOV-LEG-F2021L00258] |
| 动物制品进口条件：羽毛须洁净并完全封装于制成品或经处理；皮须鞣制；生皮咬胶须石灰/辐照处理；宠物食品须杀菌罐装+官方兽医证书；肉、乳、蛋商业进口须许可 | 《生物安全（有条件非禁止商品）决定 2021》：羽毛须洁净且完全封装在制成品中，或经处理，或个人用 ≤10 根；皮张须鞣制或保存处理；生皮咬胶须石灰处理（pH ≥12.5）或 50 kGy 辐照（≤10 件个人用除外）；无许可的宠物食品须为高压灭菌、常温稳定、密封包装并附政府兽医证书；蜂蜜和蜂产品须纯净（西澳另需证书）；商业进口肉、乳、蛋制品须许可。 | [R:AU-L6-BIOSEC-003] [SRC-AU-GOV-LEG-F2021L00258] |
| 褐纹蝽（BMSB）季节性措施（9 月 1 日–4 月 30 日装运）：中国属“新兴风险国”，第 39、94、95 章（塑料、家具/灯具、玩具）等货物可能被随机检验 | BMSB 季节性措施适用于每年 9 月 1 日至次年 4 月 30 日装运的货物：对目标高风险国家的第 44、45、57、68、69、70、72–76、78–89 章货物强制处理（56 °C 30 分钟热处理、溴甲烷、硫酰氟或甲酸乙酯）；中国未列入强制处理名单，但为“新兴风险国”，到港后随机检验，并新增第 39、94、95 章（塑料制品、家具/灯具、玩具）；中国空运的目标高风险货物亦可能被随机检验。2026-27 季已开始。 | [R:AU-L6-BIOSEC-004] [SRC-AU-GOV-DAFF-BMSB] |
| 邮寄/小包：全部经 X 光或检疫犬筛查；不得用稻草、干植物材料或木箱包装；须逐项申报 | 所有国际邮件均经 X 光或检疫犬筛查；不得使用稻草、干燥植物材料或木箱作包装；须逐项申报内容（“gift”不被接受）；需处理的物品每件收取约 A$94 处理费，不合规物品被销毁或退回。 | [R:AU-L6-BIOSEC-005] [SRC-AU-GOV-DAFF-MAIL] |
| CITES 物种制品（象牙、珊瑚、海马、爬行动物皮革、部分兰花和木材）进出口须许可，违者最高 10 年监禁 | 《环境保护与生物多样性保护法 1999》第 13A 部分：未经许可进口 CITES 标本最高 10 年监禁/1,000 罚款单位；附录 I 商业进口仅限注册人工繁育来源，附录 II 须出口国出口许可；持有非法进口 CITES 标本最高 5 年。 | [R:AU-L6-CITES-001] [SRC-AU-GOV-LEG-C2004A00485] |
| 低价值进口商品 GST：≤A$1,000 的 B2C 商品由亚马逊（电子分销平台）代收 GST；FBA 备货在澳销售属国内应税供应，卖家须正常 GST 注册 | 自 2018-07-01 起，海关价值 ≤A$1,000 的 B2C 进口商品在销售时征收 GST；经亚马逊等电子分销平台销售的，由平台承担 GST，相关销售不计入卖家 GST 营业额，卖家自有渠道销售额达 A$75,000 须注册。>A$1,000 的货物在边境由进口商缴纳 GST 与关税。使用 FBA 等在澳库存销售的，进口时在边境缴纳 GST/关税，后续销售为国内应税供应、平台不承担 GST，卖家须以 ABN 进行标准 GST 注册并可抵扣进口 GST。 | [R:AU-L6-GST-001] [SRC-AU-GOV-ATO-LVIG] [SRC-AU-AMZ-G200404870] |
| 含 ≥1% 结晶二氧化硅的人造石台面板/板材禁止进口（生效日待核实） | CPIR 第 5M 条：结晶二氧化硅含量 ≥1% 的人造石台面、面板或板材进口被禁止（除 WHS 许可或豁免），据搜索摘要生效日期为 2025-01-01（待核实）。 | [R:AU-L6-ENGSTONE-001] [SRC-AU-GOV-LEG-F1996B03651] |

## F. 标签、语言与本地责任人

| 主题 | 要求 | 规则/来源 |
| --- | --- | --- |
| 语言 | 澳洲站 listing 须用英文与澳元；产品说明、安全信息、警示须为英文；食品法定标签须英文（其他语言不得矛盾）；化妆品成分用英文或 INCI 名 | [SRC-AU-AMZ-G200404870] [SRC-AU-GOV-LEG-F2015L00386] [R:AU-L3-ACCC-015] |
| 日期格式 | 食品、酒类有效期须为澳洲格式 DD/MM/YYYY | [R:AU-L3-FOOD-001] [R:AU-L2-ALCOHOL-001] |
| 原产地 | 食品须原产国标签（Product of/Made in，优先食品加框）；婴儿睡眠/倾斜产品须永久标记原产国及澳洲进口商/分销商名称 | [R:AU-L5-FOOD-002] [R:AU-L3-ACCC-023] |
| 电气责任供应商 | EESS 责任供应商必须是澳洲或新西兰实体（ABN/IRD + 本地营业），海外公司不能在 EESS 数据库注册 | [R:AU-L5-EESS-001] [SRC-AU-GOV-EESS-RESPONSIBLE-SUPPLIER] |
| 无线电供应商 | ACMA 供应商须为在澳洲的制造商、进口商或书面授权代理，并在国家数据库注册 | [R:AU-L5-ACMA-001] [SRC-AU-GOV-LEG-F2018L00028] |
| 治疗用品申办者 | ARTG 申办者须为澳洲居民或在澳经营企业；医疗器械须提供申办者授权 | [R:AU-L5-TGA-001] [R:AU-L3-MEDDEV-001] |
| 农药 | 海外 APVMA 注册人须指定澳洲代理人 | [R:AU-L5-APVMA-001] |
| 化学品/化妆品引入者 | 进口前 AICIS 注册；海外直发企业须 ARBN，否则由澳洲代理进口 | [R:AU-L5-AICIS-001] |
| 进口商 = 制造商 | 海外制造商在澳无营业地时，进口商被视为 ACL 下的制造商 | [R:AU-L5-ACL-001] |
| 国际卖家义务 | 准确写明发货国、承担进口关税与税费、24 小时内用站点语言回复客户、退货政策不低于亚马逊标准且不得限制 ACL 权利、listing 包含全部税费（GST、关税） | [SRC-AU-AMZ-G200404870] |
| GST | ≤A$1,000 B2C 进口商品由亚马逊代收 GST；FBA 本地库存销售须卖家自行 GST 注册（ABN） | [R:AU-L6-GST-001] [SRC-AU-GOV-ATO-LVIG] |

## G. 2024–2026 变化与生效日期

| 日期 | 变化 | 影响的产品 | 规则ID | 来源 |
| --- | --- | --- | --- | --- |
| 2024-01-01 | 禁止进口一次性电子烟（含个人进口） | 电子烟 | [R:AU-L5-VAPE-001] | [SRC-AU-GOV-TGA-VAPES-JUL2024] |
| 2024-03-01 | 所有电子烟进口须 ODC 许可证与许可、TGA 上市前通知 | 电子烟及配件 | [R:AU-L6-TOBACCO-001] | [SRC-AU-GOV-ABF-VAPES] |
| 2024-03-14 | 行业自评分级（电影、游戏）开始 | 影视、游戏 | [R:AU-L3-MEDIA-001] | [SRC-AU-GOV-LEG-F2023L01424] |
| 2024-03-22 | 自行车头盔安全标准 2024 生效（过渡至 2025-09-21） | 自行车头盔 | [R:AU-L3-ACCC-008] | [SRC-AU-GOV-LEG-F2024L00362] |
| 2024-07-01 | 电子烟改革法生效：仅药房可售；新列入 ARTG 的防晒须符合 AS/NZS 2604:2021 | 电子烟；防晒 | [R:AU-L5-VAPE-001] [R:AU-L5-TGA-003] | [SRC-AU-GOV-TGA-VAPES-JUL2024] [SRC-AU-GOV-TGA-SUNSCREEN] |
| 2024-07-19 | 婴儿睡眠产品安全标准 2024 生效，取代家用/折叠婴儿床标准 | 婴儿床、睡篮、床垫等 | [R:AU-L3-ACCC-020] [R:AU-L3-ACCC-022] [R:AU-L3-ACCC-023] | [SRC-AU-GOV-LEG-F2024L00891] |
| 2024-09-01 | 昆州禁止向 18 岁以下售刀/砍刀/剑/斧，适用州外网店 | 刀具 | [R:AU-L5-WEAPON-001] | [SRC-AU-GOV-QPS-KNIFE-SELLERS] |
| 2024-09-03 | ACN 2024/32 石棉进口保证与检测要求 | 高风险进口商品 | [R:AU-L6-ASBESTOS-001] | [SRC-AU-GOV-ABF-ACN-2024-32] |
| 2024-09-13 | 婴儿配方新标准（P1028）生效，过渡至 2029-09-13 | 婴儿配方奶粉 | [R:AU-L2-FORMULA-001] | [SRC-AU-GOV-FSANZ-P1028] |
| 2024-09-22 | 含 loot box 游戏至少 M 级、模拟赌博 R18+ | 电子游戏 | [R:AU-L3-MEDIA-001] | [SRC-AU-GOV-LEG-F2023L01424] |
| 2024-10-01 | 18 岁以上可在药房无处方购买 ≤20 mg/mL 治疗性电子烟 | 电子烟 | [R:AU-L5-VAPE-001] | [SRC-AU-GOV-TGA-VAPES-RETAILERS] |
| 2024-12-20 | 西澳带刃武器新规（18 岁以下禁售） | 刀具 | [R:AU-L5-WEAPON-001] | [SRC-AU-GOV-WAPOL-KNIFE] |
| 2025-02-01 / 2025-02-19 | NSW 电动出行产品安全标准与信息标准生效 | 电动自行车/滑板车/平衡车及电池、充电器 | [R:AU-L5-EMOB-001] | [SRC-AU-GOV-NSW-EMOBILITY] |
| 2025-03-05 | 36 个月以下玩具 2023 标准与护理标签 2023 标准过渡期结束 | 婴幼儿玩具；服装纺织品 | [R:AU-L3-ACCC-043] [R:AU-L3-ACCC-013] | [SRC-AU-GOV-LEG-F2023L01185] [SRC-AU-GOV-LEG-F2023L01187] |
| 2025-05-04 | 易倾倒家具信息标准生效（含在线 listing 警示） | 衣柜、斗柜、书柜、电视柜等 | [R:AU-L3-ACCC-040] | [SRC-AU-GOV-PSA-TOPPLING] |
| 2025-07-01 | 南澳售刀年龄提至 18、剑与砍刀为禁止武器；十字花科/葫芦科种子须进口许可 | 刀剑；种子 | [R:AU-L5-WEAPON-001] [R:AU-L6-BIOSEC-001] | [SRC-AU-GOV-SA-LAWHANDBOOK-WEAPONS] [SRC-AU-GOV-DAFF-SEEDS] |
| 2025-09-01 | 维州砍刀成为禁止武器 | 砍刀 | [R:AU-L5-WEAPON-001] | [SRC-AU-GOV-VICPOL-MACHETE] |
| 2025-09-22 | 自行车头盔仅可按新标准供应 | 自行车头盔 | [R:AU-L3-ACCC-008] | [SRC-AU-GOV-LEG-F2024L00362] |
| 2025-10-01 | 低干扰潜力设备类许可 2025 生效 | 短距离无线设备 | [R:AU-L5-ACMA-001] | [SRC-AU-GOV-LEG-F2025L01047] |
| 2025-12-04 | 彩沙/造型膏/部分玩具税号新增石棉申报问题（ACN 2025/33） | 彩沙、玩沙 | [R:AU-L6-ASBESTOS-001] [R:AU-L3-SAND-001] | [SRC-AU-GOV-ABF-ACN-2025-33] |
| 2026-01-19 | 婴儿睡眠产品标准第 3 部分强制；婴儿产品信息标准生效（listing 警示、原产国+进口商标记） | 婴儿睡眠与倾斜产品 | [R:AU-L3-ACCC-023] | [SRC-AU-GOV-LEG-F2024L00892] |
| 2026-01-22 | 海关条例新增公共安全测试；禁止符号/暴力极端主义材料纳入违禁物品 | 武器、枪支、含纳粹符号商品 | [R:AU-L6-CUSTOMS-001] [R:AU-L6-RC-001] | [SRC-AU-GOV-LEG-F1996B03651] |
| 2026-02-01 | NSW 电动出行产品须认证并加贴批准标识后方可销售 | 电动出行产品 | [R:AU-L5-EMOB-001] | [SRC-AU-GOV-NSW-EMOBILITY] |
| 2026-03-28 | ACL 公司罚款上限提至 1 亿澳元 | 所有商品 | [R:AU-L5-ACL-001] | [SRC-AU-GOV-LEG-C2004A00109] |
| 2026-05-01 | WaterMark 仅可生产无铅认证产品（2028-05-01 仅可安装无铅产品） | 龙头、卫浴 | [R:AU-L5-WATERMARK-001] | [SRC-AU-GOV-WATERMARK-LEADFREE] |
| 2026-05-26 | 奶瓶自喂装置永久禁令生效 | 婴儿奶瓶支架、自喂枕 | [R:AU-L1-INFANT-001] | [SRC-AU-GOV-PSA-SELF-FEEDING-BAN] |
| 2026-06-26 | 水上玩具安全标准 2026 生效（旧标准过渡约至 2028-06-25） | 充气水上玩具 | [R:AU-L3-ACCC-001] | [SRC-AU-GOV-LEG-F2026L00797] |
| 2026-07-01 | EESS 新费率；南澳售刀网购信息告知义务 | 电器；刀具 | [R:AU-L5-EESS-001] [R:AU-L5-WEAPON-001] | [SRC-AU-GOV-EESS-FEES] [SRC-AU-GOV-SA-LAWHANDBOOK-WEAPONS] |
| 2026-07（v1.0） | EESS 发布在线市场卖家/平台/买家指南 | 市电电器、旅行转换器 | [R:AU-L5-EESS-003] | [SRC-AU-GOV-EESS-SELLER-GUIDE] |
| 2026-07-24 | 尼古丁袋非 ARTG 不得进口或供应 | 尼古丁袋 | [R:AU-L5-VAPE-001] | [SRC-AU-GOV-ABF-VAPES] |
| 2026-08-06 | 联邦指示 ACCC 制定电动自行车/滑板车/电动滑板全国安全标准（未定时间） | 电动出行 | [R:AU-L5-EMOB-001] | [SRC-AU-GOV-TREASURY-EBIKE-2026] |
| 2026-09-20 至 10-18 | Treasury 就加强上市后监管征求意见（网络市场另行咨询） | 所有商品 | [R:AU-L5-ACL-001] | [SRC-AU-GOV-TREASURY-CRIS-2026] |

## H. 来源清单

共 298 个来源（S1 亚马逊 146 个；S2 政府 152 个；S3 0 个）。访问日期均为 2026-10-10。

| 来源ID | 标题 | URL | 级别 | 访问方式 | 访问日期 |
| --- | --- | --- | --- | --- | --- |
| SRC-AU-AMZ-G200164750 | Recalled products | https://sellercentral.amazon.com.au/help/hub/reference/external/G200164750?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-PSA-RECALLS | Search consumer product recalls | https://www.productsafety.gov.au/recalls | S2 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G200339940 | Adult products policies & guidelines | https://sellercentral.amazon.com.au/help/hub/reference/external/G200339940?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G200164410 | Automotive & powersports products | https://sellercentral.amazon.com.au/help/hub/reference/external/G200164410?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2010L03297 | Permanent Ban – Tinted Headlight Covers (luminous transmittance below 85%) | https://www.legislation.gov.au/F2010L03297/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-PSA-BANS | Find banned products | https://www.productsafety.gov.au/product-safety-laws/safety-standards-bans/product-bans | S2 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GRLKLZ6WQ9R259LC | Product safety listing restrictions | https://sellercentral.amazon.com.au/help/hub/reference/external/GRLKLZ6WQ9R259LC?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2023L00214 | Radiocommunications (Jamming Equipment) Permanent Ban 2023 | https://www.legislation.gov.au/F2023L00214/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-G200164550 | Food and beverages | https://sellercentral.amazon.com.au/help/hub/reference/external/G200164550?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2010L03298 | Permanent Ban – Mini-cup Jelly Confectionery Containing Konjac | https://www.legislation.gov.au/F2010L03298/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-G200164340 | Alcohol | https://sellercentral.amazon.com.au/help/hub/reference/external/G200164340?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GM9BQPTJNXU2KEDW | Alcohol approval requirements | https://sellercentral.amazon.com.au/help/hub/reference/external/GM9BQPTJNXU2KEDW?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G200164370 | Animals and animal products | https://sellercentral.amazon.com.au/help/hub/reference/external/G200164370?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F1996B03651 | Customs (Prohibited Imports) Regulations 1956 | https://www.legislation.gov.au/F1996B03651/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-G200164490 | Drugs and drug paraphernalia | https://sellercentral.amazon.com.au/help/hub/reference/external/G200164490?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G200164470 | Cosmetics, skin, and hair care | https://sellercentral.amazon.com.au/help/hub/reference/external/G200164470?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G200164450 | Currency, coins, cash equivalents and gift cards | https://sellercentral.amazon.com.au/help/hub/reference/external/G200164450?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G200164730 | Postage meters and stamps | https://sellercentral.amazon.com.au/help/hub/reference/external/G200164730?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G201829010 | Dietary supplements | https://sellercentral.amazon.com.au/help/hub/reference/external/G201829010?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G200164950 | Explosives, weapons and related items | https://sellercentral.amazon.com.au/help/hub/reference/external/G200164950?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G200164570 | Hazardous and dangerous items | https://sellercentral.amazon.com.au/help/hub/reference/external/G200164570?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G200685320 | Other restricted products | https://sellercentral.amazon.com.au/help/hub/reference/external/G200685320?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2012L02171 | Consumer Protection Notice No. 5 of 2012 – Permanent Ban on Small High Powered Magnets | https://www.legislation.gov.au/F2012L02171/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GC277GB53473J65C | Abrasive kite strings | https://sellercentral.amazon.com.au/help/hub/reference/external/GC277GB53473J65C?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GEJ6L4MMBHVZGLND | Toothpick crossbows | https://sellercentral.amazon.com.au/help/hub/reference/external/GEJ6L4MMBHVZGLND?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G9LKRHDUQ5AV3ECD | Children’s neck floats | https://sellercentral.amazon.com.au/help/hub/reference/external/G9LKRHDUQ5AV3ECD?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G200164590 | Human parts and burial artefacts | https://sellercentral.amazon.com.au/help/hub/reference/external/G200164590?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G200685250 | Gambling and lottery | https://sellercentral.amazon.com.au/help/hub/reference/external/G200685250?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GRGM8BSET2LH6KTL | Infant self-feeding products | https://sellercentral.amazon.com.au/help/hub/reference/external/GRGM8BSET2LH6KTL?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-PSA-SELF-FEEDING-BAN | Baby bottle self-feeding devices ban | https://www.productsafety.gov.au/business/find-banned-products/baby-bottle-self-feeding-devices-ban | S2 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2026L00610 | Consumer Goods (Baby Bottle Self-feeding Devices) Permanent Ban 2026 | https://www.legislation.gov.au/F2026L00610/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-G200166630 | Jewellery and precious gems | https://sellercentral.amazon.com.au/help/hub/reference/external/G200166630?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G201689020 | Laser products | https://sellercentral.amazon.com.au/help/hub/reference/external/G201689020?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G201997070 | Lighting | https://sellercentral.amazon.com.au/help/hub/reference/external/G201997070?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G200164850 | Lock picking devices and theft devices | https://sellercentral.amazon.com.au/help/hub/reference/external/G200164850?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G200164510 | Electronics Electrical and electronic products | https://sellercentral.amazon.com.au/help/hub/reference/external/G200164510?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GQQWCXM7GWCFKVVM | Electrical Equipment | https://sellercentral.amazon.com.au/gp/help/external/GQQWCXM7GWCFKVVM?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G2HSXA2KM59YX5AT | Cylindrical rechargeable lithium batteries | https://sellercentral.amazon.com.au/help/hub/reference/external/G2HSXA2KM59YX5AT?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G7PAP6BJAUXRM4LH | Lithium batteries | https://sellercentral.amazon.com.au/help/hub/reference/external/G7PAP6BJAUXRM4LH?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2021L01177 | Telecommunications (Prohibition of Mobile Phone Boosters) Declaration 2021 | https://www.legislation.gov.au/F2021L01177/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-G202115120 | Pesticides | https://sellercentral.amazon.com.au/help/hub/reference/external/G202115120?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G201737480 | Plants, Plant Products, and Seeds | https://sellercentral.amazon.com.au/help/hub/reference/external/G201737480?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G200164870 | Surveillance Equipment | https://sellercentral.amazon.com.au/help/hub/reference/external/G200164870?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G200164910 | Tobacco and tobacco-related products | https://sellercentral.amazon.com.au/help/hub/reference/external/G200164910?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-TGA-VAPES-JUL2024 | New vaping laws to commence 1 July 2024 ／ Therapeutic Goods Administration (TGA) | https://www.tga.gov.au/news/media-releases/new-vaping-laws-commence-1-july-2024 | S2 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GLL2YRZB4BUQBSLM | Tree and fruit netting | https://sellercentral.amazon.com.au/help/hub/reference/external/GLL2YRZB4BUQBSLM?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G200164930 | Warranties, service plans, contracts, and guarantees | https://sellercentral.amazon.com.au/help/hub/reference/external/G200164930?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GVVAHF4S3EZ7FPAY | Bidets and other plumbing and drainage products | https://sellercentral.amazon.com.au/help/hub/reference/external/GVVAHF4S3EZ7FPAY?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GD85NFMCQF2KNM2N | Fertilisers | https://sellercentral.amazon.com.au/help/hub/reference/external/GD85NFMCQF2KNM2N?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GMMCLBZWLHDEWEKS | Single-use plastics | https://sellercentral.amazon.com.au/help/hub/reference/external/GMMCLBZWLHDEWEKS?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GGA942GE8CSQ7KK5 | 3G and non-VoLTE devices | https://sellercentral.amazon.com.au/help/hub/reference/external/GGA942GE8CSQ7KK5?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2019L01509 | Telecommunications (Emergency Call Service) Determination 2019 | https://www.legislation.gov.au/F2019L01509/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GAEKV7BNR2W6FGG3 | Trampoline scooters and skateboards | https://sellercentral.amazon.com.au/help/hub/reference/external/GAEKV7BNR2W6FGG3?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G7A4NWJ8DH3KZTTL | Infant bath tubs and bath support aids with temperature sensors | https://sellercentral.amazon.com.au/help/hub/reference/external/G7A4NWJ8DH3KZTTL?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G200164430 | Clothing | https://sellercentral.amazon.com.au/help/hub/reference/external/G200164430?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G2E9DBAG4GYSQ5LT | cot bumpers | https://sellercentral.amazon.com.au/help/hub/reference/external/G2E9DBAG4GYSQ5LT?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GNU34E2V48PRHY84 | Inflatable infant and toddler travel beds | https://sellercentral.amazon.com.au/help/hub/reference/external/GNU34E2V48PRHY84?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GX44XMQX3ZKWRPZR | Infant sleep-positioning products | https://sellercentral.amazon.com.au/help/hub/reference/external/GX44XMQX3ZKWRPZR?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GKDFVJSUHPYTRHW3 | Weighted infant and toddler sleep products | https://sellercentral.amazon.com.au/help/hub/reference/external/GKDFVJSUHPYTRHW3?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G8FDB4PSHS4AACQ5 | Children's upper clothing with drawstrings | https://sellercentral.amazon.com.au/help/hub/reference/external/G8FDB4PSHS4AACQ5?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GDPSRCGVBFSFY78H | Baby teething products | https://sellercentral.amazon.com.au/help/hub/reference/external/GDPSRCGVBFSFY78H?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GFEUQFB9X4YWFVXD | Water beads | https://sellercentral.amazon.com.au/help/hub/reference/external/GFEUQFB9X4YWFVXD?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GPQBDFAYL3LCWYD2 | Mermaid tail swimwear | https://sellercentral.amazon.com.au/help/hub/reference/external/GPQBDFAYL3LCWYD2?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G202155900 | Fidget spinners | https://sellercentral.amazon.com.au/help/hub/reference/external/G202155900?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GRBE9D3BXQJPMA6V | Children’s face masks | https://sellercentral.amazon.com.au/help/hub/reference/external/GRBE9D3BXQJPMA6V?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GKJRA3FRPRKVBJJS | Children’s toys | https://sellercentral.amazon.com.au/help/hub/reference/external/GKJRA3FRPRKVBJJS?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-EESS-OPERATOR-GUIDE | EESS Online Marketplace Operators Guide v1.0 (July 2026) | https://www.eess.gov.au/wp-content/uploads/2026/07/EESS-Online-Marketplace-Operators-Guide-v1.0.pdf | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GKD2ZVSS3AZM4AQT | Trichloroacetic acid | https://sellercentral.amazon.com.au/help/hub/reference/external/GKD2ZVSS3AZM4AQT?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GW6HK2RDRNNFW2ML | Paint removal products | https://sellercentral.amazon.com.au/help/hub/reference/external/GW6HK2RDRNNFW2ML?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GXE3TPKYT83DDWJM | Sodium azide | https://sellercentral.amazon.com.au/help/hub/reference/external/GXE3TPKYT83DDWJM?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GFN9WH6A9844V2T2 | Fire extinguishing balls | https://sellercentral.amazon.com.au/help/hub/reference/external/GFN9WH6A9844V2T2?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G5P5YMQXX9Y34NVU | Gel and liquid fuel-burning fire pits and fireplaces | https://sellercentral.amazon.com.au/help/hub/reference/external/G5P5YMQXX9Y34NVU?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G5ZEPL3F3YQR5GUS | Ultraviolet-C (UVC) devices | https://sellercentral.amazon.com.au/help/hub/reference/external/G5ZEPL3F3YQR5GUS?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GFQMECECLTJCUE3H | Battery-operated heated clothing and insoles | https://sellercentral.amazon.com.au/help/hub/reference/external/GFQMECECLTJCUE3H?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GT8V6T7U8GZZK3SU | Car seat heating pads | https://sellercentral.amazon.com.au/help/hub/reference/external/GT8V6T7U8GZZK3SU?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G200333160 | Categories and products that require approval | https://sellercentral.amazon.com.au/help/hub/reference/external/G200333160?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G201279060 | Art and fine art | https://sellercentral.amazon.com.au/help/hub/reference/external/G201279060?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G201257400 | Fine Art | https://sellercentral.amazon.com.au/help/hub/reference/external/G201257400?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GSHFYZ3G4JSZGTHE | Food and Beverages approval requirements | https://sellercentral.amazon.com.au/help/hub/reference/external/GSHFYZ3G4JSZGTHE?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GQR5FX94UKK38Q9Q | Pesticides approval requirements | https://sellercentral.amazon.com.au/help/hub/reference/external/GQR5FX94UKK38Q9Q?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GEHDL3P6RLYX8UUZ | Infant formula approval requirements | https://sellercentral.amazon.com.au/help/hub/reference/external/GEHDL3P6RLYX8UUZ?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-FSANZ-P1028 | FSANZ – P1028 Infant formula | https://www.foodstandards.gov.au/food-standards-code/proposals/P1028 | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-G4TKMFYMP2XJNJPH | Major Domestic Appliances | https://sellercentral.amazon.com.au/help/hub/reference/external/G4TKMFYMP2XJNJPH?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G202188990 | Music, CDs | https://sellercentral.amazon.com.au/help/hub/reference/external/G202188990?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G201607580 | Video, DVD, & Blu-ray | https://sellercentral.amazon.com.au/help/hub/reference/external/G201607580?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G202183590 | Streaming Media Players | https://sellercentral.amazon.com.au/help/hub/reference/external/G202183590?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G200339950 | Condition guidelines | https://sellercentral.amazon.com.au/help/hub/reference/external/G200339950?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G200332590 | Jewelry | https://sellercentral.amazon.com.au/help/hub/reference/external/G200332590?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G201269180 | Jewellery Quality Assurance Standards | https://sellercentral.amazon.com.au/help/hub/reference/external/G201269180?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G200944120 | Entertainment Collectibles | https://sellercentral.amazon.com.au/help/hub/reference/external/G200944120?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GV8XARHLGCMHQY5C | Therapeutic goods | https://sellercentral.amazon.com.au/help/hub/reference/external/GV8XARHLGCMHQY5C?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GS3MLGJS3SQKG3LQ | Australian media classification requirements | https://sellercentral.amazon.com.au/help/hub/reference/external/GS3MLGJS3SQKG3LQ?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2023L01424 | Guidelines for the Classification of Computer Games 2023 (loot boxes and simulated gambling) | https://www.legislation.gov.au/F2023L01424/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GJDWGWRZQJPFBN9P | Prohibited product claims | https://sellercentral.amazon.com.au/help/hub/reference/external/GJDWGWRZQJPFBN9P?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-EESS-LEVELS | EESS In-scope Equipment Definitions and Risk Levels v4.3 (AS/NZS 4417.2:2020) | https://www.eess.gov.au/wp-content/uploads/2024/07/EESS-Inscope-Equipment-Definitions-and-Risk-Levels-v4.3-Approved.pdf | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GLV5ESPKUCWX9KPS | Australian Competition and Consumer Commission – Product Safety Mandatory Standards | https://sellercentral.amazon.com.au/help/hub/reference/external/GLV5ESPKUCWX9KPS?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G437RJUPBUEZFHVU | Children’s aquatic toys | https://sellercentral.amazon.com.au/help/hub/reference/external/G437RJUPBUEZFHVU?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2026L00797 | Consumer Goods (Aquatic Toys) Safety Standard 2026 | https://www.legislation.gov.au/F2026L00797/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GBSBVUXSS65RPBBP | Infant bath tubs and bath support aids | https://sellercentral.amazon.com.au/help/hub/reference/external/GBSBVUXSS65RPBBP?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2017L01394 | Consumer Goods (Baby Bath Aids) Safety Standard 2017 | https://www.legislation.gov.au/F2017L01394/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2017L00516 | Consumer Goods (Babies' Dummies and Dummy Chains) Safety Standard 2017 | https://www.legislation.gov.au/F2017L00516/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GX9BGE7LAFRWAFHF | Pacifiers and pacifier clips | https://sellercentral.amazon.com.au/help/hub/reference/external/GX9BGE7LAFRWAFHF?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2013L00190 | Consumer Protection Notice No. 1 of 2013 – Consumer Product Safety Standard: Baby Walkers | https://www.legislation.gov.au/F2013L00190/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GPJ984JUMZWCU96F | Baby Walkers | https://sellercentral.amazon.com.au/help/hub/reference/external/GPJ984JUMZWCU96F?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F1997B01840 | Trade Practices (Consumer Product Safety Standards) Regulations (reg 10 – balloon blowing kits) | https://www.legislation.gov.au/F1997B01840/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2017L01657 | Consumer Goods (Basketball Rings and Backboards) Safety Standard 2017 | https://www.legislation.gov.au/F2017L01657/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GLBSMWBUENTFMEX6 | Basketball rings and backboards | https://sellercentral.amazon.com.au/help/hub/reference/external/GLBSMWBUENTFMEX6?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G5H9CJ6RJTZRVZK7 | Bean bags and covers | https://sellercentral.amazon.com.au/help/hub/reference/external/G5H9CJ6RJTZRVZK7?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2014L01587 | Consumer Goods (Bean Bags) Safety Standard 2014 | https://www.legislation.gov.au/F2014L01587/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2024L00362 | Consumer Goods (Bicycle Helmets) Safety Standard 2024 | https://www.legislation.gov.au/F2024L00362/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GHRAUBNDL7K7EZSG | Bicycle helmets | https://sellercentral.amazon.com.au/gp/help/external/GHRAUBNDL7K7EZSG?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2005B01053 | Consumer Protection Notice No. 6 of 2004 – Consumer Product Safety Standard: Pedal Bicycles | https://www.legislation.gov.au/F2005B01053/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GBVSAAJFBSKYNT8Q | Bicycles | https://sellercentral.amazon.com.au/help/hub/reference/external/GBVSAAJFBSKYNT8Q?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2010L01930 | Trade Practices (Consumer Product Safety Standard) (Corded Internal Window Coverings) Regulations 2010 | https://www.legislation.gov.au/F2010L01930/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GT7F5YBQFRDZCAG8 | Corded window coverings | https://sellercentral.amazon.com.au/help/hub/reference/external/GT7F5YBQFRDZCAG8?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2005B01055 | Consumer Protection Notice No. 1 of 2003 – Consumer Product Safety Standard: Bunk Beds | https://www.legislation.gov.au/F2005B01055/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GXCWBPZVZMQDNWRS | Bunk beds | https://sellercentral.amazon.com.au/help/hub/reference/external/GXCWBPZVZMQDNWRS?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GUBLQYWAJDBADUVK | Stand-alone button and coin batteries | https://sellercentral.amazon.com.au/help/hub/reference/external/GUBLQYWAJDBADUVK?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G85BLBNFDCZ4BQP7 | Button and coin batteries | https://sellercentral.amazon.com.au/help/hub/reference/external/G85BLBNFDCZ4BQP7?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2020L01658 | Consumer Goods (Button/Coin Batteries) Safety Standard 2020 | https://www.legislation.gov.au/F2020L01658/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2020L01659 | Consumer Goods (Button/Coin Batteries) Information Standard 2020 | https://www.legislation.gov.au/F2020L01659/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2023L01187 | Consumer Goods (Care Labelling for Clothing and Textile Products) Information Standard 2023 | https://www.legislation.gov.au/F2023L01187/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-G202137200 | Child restraint systems, booster seats and travel systems | https://sellercentral.amazon.com.au/help/hub/reference/external/G202137200?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2014L01252 | Consumer Protection Notice No. 3 of 2014 – Child Restraints for Motor Vehicles | https://www.legislation.gov.au/F2014L01252/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2020L01469 | Consumer Goods (Cosmetics) Information Standard 2020 | https://www.legislation.gov.au/F2020L01469/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2017L00909 | Consumer Goods (Decorative Alcohol Fuelled Devices) Safety Standard 2017 | https://www.legislation.gov.au/F2017L00909/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2019L00132 | Consumer Goods (Disposable Cigarette Lighters) Safety Standard 2019 | https://www.legislation.gov.au/F2019L00132/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-G33UY7AQ98SXVHJB | Elastic luggage straps | https://sellercentral.amazon.com.au/help/hub/reference/external/G33UY7AQ98SXVHJB?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2017L00382 | Consumer Goods (Elastic Luggage Straps) Safety Standard 2017 | https://www.legislation.gov.au/F2017L00382/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2005B01068 | Consumer Protection Notice No. 9 of 1997 – Consumer Product Safety Standard: Exercise Cycles | https://www.legislation.gov.au/F2005B01068/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GG6Z9HM4W4S6BEJQ | Exercise cycles | https://sellercentral.amazon.com.au/help/hub/reference/external/GG6Z9HM4W4S6BEJQ?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2024L00891 | Consumer Goods (Infant Sleep Products) Safety Standard 2024 | https://www.legislation.gov.au/F2024L00891/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-PSA-INFANT-SLEEP | Infant sleep products mandatory standards | https://www.productsafety.gov.au/business/search-mandatory-standards/infant-sleep-products-mandatory-standards | S2 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GZHGJY9GCWWRYJM2 | Infant sleep products | https://sellercentral.amazon.com.au/help/hub/reference/external/GZHGJY9GCWWRYJM2?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2008L00651 | Trade Practices (Consumer Product Safety Standard) (Hot Water Bottles) Regulations 2008 | https://www.legislation.gov.au/F2008L00651/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GXDAD4N3TU3AK5TD | Hot water bottles | https://sellercentral.amazon.com.au/help/hub/reference/external/GXDAD4N3TU3AK5TD?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2024L00892 | Consumer Goods (Infant Products) Information Standard 2024 | https://www.legislation.gov.au/F2024L00892/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2019L01633 | Consumer Goods (Miniature Motorbikes) Safety Standard 2019 | https://www.legislation.gov.au/F2019L01633/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2010L03061 | Consumer Protection Notice No. 28 of 2010 – Consumer Product Safety Standard: Movable Soccer Goals | https://www.legislation.gov.au/F2010L03061/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-G7JKRNAKF5HRTDLT | Moveable soccer goals | https://sellercentral.amazon.com.au/help/hub/reference/external/G7JKRNAKF5HRTDLT?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2017L00452 | Consumer Goods (Children's Nightwear and Limited Daywear and Paper Patterns for Children's Nightwear) Safety Standard 2017 | https://www.legislation.gov.au/F2017L00452/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-G5NGAYYZAY559SCZ | Children’s sleepwear | https://sellercentral.amazon.com.au/help/hub/reference/external/G5NGAYYZAY559SCZ?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2023L00038 | Consumer Goods (Non-refillable Helium Cylinders) Safety Standard 2022 | https://www.legislation.gov.au/F2023L00038/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GP27QYBAUSUCWB99 | Non-refillable helium cylinders | https://sellercentral.amazon.com.au/help/hub/reference/external/GP27QYBAUSUCWB99?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2005B01049 | Consumer Protection Notice No. 9 of 2004 – Consumer Product Safety Standard: Portable Fire Extinguishers (Aerosol Type) | https://www.legislation.gov.au/F2005B01049/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GS972L5FPTCLNYNR | Fire extinguishers | https://sellercentral.amazon.com.au/help/hub/reference/external/GS972L5FPTCLNYNR?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2021L01844 | Consumer Goods (Portable Fire Extinguishers) Safety Standard 2021 | https://www.legislation.gov.au/F2021L01844/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2017L01559 | Consumer Goods (Portable Ramps for Vehicles) Safety Standard 2017 | https://www.legislation.gov.au/F2017L01559/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GRKGPHRX533JSRCK | Portable automotive jacks and ramps | https://sellercentral.amazon.com.au/help/hub/reference/external/GRKGPHRX533JSRCK?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2013L00049 | Consumer Goods (Portable Swimming Pools) Safety Standard 2013 | https://www.legislation.gov.au/F2013L00049/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GFP2U2S6M3UWBXKF | Portable swimming pools | https://sellercentral.amazon.com.au/help/hub/reference/external/GFP2U2S6M3UWBXKF?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G4SX7HDHVCGK33UD | Carriages and strollers | https://sellercentral.amazon.com.au/help/hub/reference/external/G4SX7HDHVCGK33UD?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2007L01895 | Consumer Protection Notice No. 8 of 2007 – Consumer Product Safety Standard: Prams and Strollers | https://www.legislation.gov.au/F2007L01895/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2020L01656 | Consumer Goods (Products Containing Button/Coin Batteries) Safety Standard 2020 | https://www.legislation.gov.au/F2020L01656/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2020L01657 | Consumer Goods (Products Containing Button/Coin Batteries) Information Standard 2020 | https://www.legislation.gov.au/F2020L01657/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GD3HX7SAHCTDJ6QU | Products containing button or coin batteries | https://sellercentral.amazon.com.au/gp/help/external/GD3HX7SAHCTDJ6QU?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2020L00687 | Consumer Goods (Projectile Toys) Safety Standard 2020 | https://www.legislation.gov.au/F2020L00687/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2019L01321 | Consumer Goods (Quad Bikes) Safety Standard 2019 | https://www.legislation.gov.au/F2019L01321/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-G74TRGJ7KW7DUK2A | Quad bikes | https://sellercentral.amazon.com.au/help/hub/reference/external/G74TRGJ7KW7DUK2A?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2017L01560 | Consumer Goods (Motor Vehicle Recovery Straps) Safety Standard 2017 | https://www.legislation.gov.au/F2017L01560/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GNMG498S7WTV4TYT | Motor vehicle recovery straps | https://sellercentral.amazon.com.au/help/hub/reference/external/GNMG498S7WTV4TYT?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2018L00659 | Consumer Goods (Self-balancing Scooters) Safety Standard 2018 | https://www.legislation.gov.au/F2018L00659/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GMUW6CKYLY4AP8MK | Electronic mobility (e-mobility) devices | https://sellercentral.amazon.com.au/help/hub/reference/external/GMUW6CKYLY4AP8MK?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2017L01391 | Consumer Goods (Sunglasses and Fashion Spectacles) Safety Standard 2017 | https://www.legislation.gov.au/F2017L01391/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GCP5RFFKH834SU3W | Sunglasses and fashion spectacles | https://sellercentral.amazon.com.au/help/hub/reference/external/GCP5RFFKH834SU3W?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G202171660 | Solar eclipse glasses | https://sellercentral.amazon.com.au/help/hub/reference/external/G202171660?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2017L01662 | Consumer Goods (Swimming and Flotation Aids) Safety Standard 2017 | https://www.legislation.gov.au/F2017L01662/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GTVZL2BE4YZJWLTE | Swimming and flotation aids | https://sellercentral.amazon.com.au/help/hub/reference/external/GTVZL2BE4YZJWLTE?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2024L00512 | Consumer Goods (Toppling Furniture) Information Standard 2024 | https://www.legislation.gov.au/F2024L00512/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-PSA-TOPPLING | Toppling furniture mandatory standard | https://www.productsafety.gov.au/business/search-mandatory-standards/toppling-furniture-mandatory-standard | S2 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GFF2FG9J54JMMB4C | Freestanding household furniture | https://sellercentral.amazon.com.au/help/hub/reference/external/GFF2FG9J54JMMB4C?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2009L00223 | Consumer Protection Notice No. 1 of 2009 – Lead and Certain Elements in Children's Toys | https://www.legislation.gov.au/F2009L00223/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2020L01074 | Consumer Goods (Toys Containing Magnets) Safety Standard 2020 | https://www.legislation.gov.au/F2020L01074/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2023L01185 | Consumer Goods (Toys for Children up to and including 36 Months of Age) Safety Standard 2023 | https://www.legislation.gov.au/F2023L01185/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2009L02165 | Trade Practices (Consumer Product Safety Standard) (Treadmills) Regulations 2009 | https://www.legislation.gov.au/F2009L02165/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GX9TKTXYKB6T22YH | Treadmills | https://sellercentral.amazon.com.au/help/hub/reference/external/GX9TKTXYKB6T22YH?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2017L01656 | Consumer Goods (Trolley Jacks) Safety Standard 2017 | https://www.legislation.gov.au/F2017L01656/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2010L00295 | Consumer Protection Notice No. 1 of 2010 – Consumer Product Safety Standard: Vehicle Jacks | https://www.legislation.gov.au/F2010L00295/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2017L01563 | Consumer Goods (Vehicle Support Stands) Safety Standard 2017 | https://www.legislation.gov.au/F2017L01563/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GL7SLDV3WUGZAEQZ | Medical devices | https://sellercentral.amazon.com.au/help/hub/reference/external/GL7SLDV3WUGZAEQZ?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G200164650 | Medical devices and accessories | https://sellercentral.amazon.com.au/help/hub/reference/external/G200164650?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GUG6JJCDN6YYQYJP | Infant and toddler feeding products | https://sellercentral.amazon.com.au/help/hub/reference/external/GUG6JJCDN6YYQYJP?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GUDREU3TUSEM3D3B | Infant and toddler bibs | https://sellercentral.amazon.com.au/help/hub/reference/external/GUDREU3TUSEM3D3B?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G8TM22XFM7WXCRDC | Lithium battery-powered Home appliances | https://sellercentral.amazon.com.au/help/hub/reference/external/G8TM22XFM7WXCRDC?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GA2PQDTU5HMC7CRZ | Lithium battery powered smart home devices and consumer electronics | https://sellercentral.amazon.com.au/help/hub/reference/external/GA2PQDTU5HMC7CRZ?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GUTZ2R2DD6P2UMVB | Direct product validation: Third‑party testing, inspection and certification services | https://sellercentral.amazon.com.au/help/hub/reference/external/GUTZ2R2DD6P2UMVB?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GSJFE8S8AES7F7VG | Portable power supplies | https://sellercentral.amazon.com.au/help/hub/reference/external/GSJFE8S8AES7F7VG?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G6WCA7BRX5QWHMNF | Portable automotive jump starters | https://sellercentral.amazon.com.au/help/hub/reference/external/G6WCA7BRX5QWHMNF?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G202156120 | Device batteries and chargers | https://sellercentral.amazon.com.au/help/hub/reference/external/G202156120?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G7HM69VDEMRW7TPE | Electronic mobility (e-mobility) accessories | https://sellercentral.amazon.com.au/help/hub/reference/external/G7HM69VDEMRW7TPE?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G202137960 | String lights | https://sellercentral.amazon.com.au/help/hub/reference/external/G202137960?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GW5CVACPVTQNTWHX | Hair styling appliances | https://sellercentral.amazon.com.au/help/hub/reference/external/GW5CVACPVTQNTWHX?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G202162990 | Personal flotation devices | https://sellercentral.amazon.com.au/help/hub/reference/external/G202162990?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G9Y54S338CEWN96N | Sand-based products containing asbestos | https://sellercentral.amazon.com.au/help/hub/reference/external/G9Y54S338CEWN96N?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-ABF-ACN-2025-33 | Australian Customs Notice 2025/33 – New asbestos community protection question (sand and modelling products) | https://www.abf.gov.au/help-and-support-subsite/CustomsNotices/2025-33.pdf | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GXUCN5ZRJSYN9W9S | Smoke and carbon gas alarms | https://sellercentral.amazon.com.au/help/hub/reference/external/GXUCN5ZRJSYN9W9S?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GYLCR8T54SJ7JAYV | Two-way radios | https://sellercentral.amazon.com.au/help/hub/reference/external/GYLCR8T54SJ7JAYV?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2021L00661 | Radiocommunications Equipment (General) Rules 2021 | https://www.legislation.gov.au/F2021L00661/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-GXPFG3RRZB9WFPJE | Portable bed rails | https://sellercentral.amazon.com.au/help/hub/reference/external/GXPFG3RRZB9WFPJE?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G5L9AARKDVRSGCWR | Gas appliances | https://sellercentral.amazon.com.au/help/hub/reference/external/G5L9AARKDVRSGCWR?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-GTRC | Gas Technical Regulators Committee (GTRC) – gas appliance certification and national database | https://www.gtrc.gov.au/ | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-G200140860 | FBA product restrictions | https://sellercentral.amazon.com.au/help/hub/reference/external/G200140860?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-GYS2KBEE7MYVCGE3 | FBA Dangerous Goods Program Policy | https://sellercentral.amazon.com.au/help/hub/reference/external/GYS2KBEE7MYVCGE3?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G201003400 | Dangerous goods identification guide (hazmat) | https://sellercentral.amazon.com.au/help/hub/reference/external/G201003400?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G201371860 | Dangerous goods (hazmat) required information and documentation | https://sellercentral.amazon.com.au/help/hub/reference/external/G201371860?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G200525640 | Examples of products that might be regulated as dangerous goods | https://sellercentral.amazon.com.au/help/hub/reference/external/G200525640?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G200383420 | Requirements for lithium batteries and products that are shipped with lithium batteries | https://sellercentral.amazon.com.au/help/hub/reference/external/G200383420?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G201003420 | Expiry dates on FBA products | https://sellercentral.amazon.com.au/help/hub/reference/external/G201003420?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G202125070 | Meltable FBA inventory | https://sellercentral.amazon.com.au/help/hub/reference/external/G202125070?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G201730840 | Fulfilment by Amazon prohibited products | https://sellercentral.amazon.com.au/help/hub/reference/external/G201730840?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-C2004A00109 | Competition and Consumer Act 2010 (Schedule 2 – Australian Consumer Law) | https://www.legislation.gov.au/C2004A00109/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-PSA-MANDATORY-REPORTING | Make a mandatory report | https://www.productsafety.gov.au/business/make-a-mandatory-report | S2 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-TREASURY-CRIS-2026 | Treasury Consultation RIS – Strengthening post-market regulation of unsafe products (2026) | https://consult.treasury.gov.au/c2026-802968 | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2011L00192 | Consumer Protection Notice No. 11 of 2011 – Permanent Ban on Children's Products Containing More Than 1% DEHP | https://www.legislation.gov.au/F2011L00192/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2011L00227 | Consumer Protection Notice No. 17 of 2011 – Permanent Ban on Sky Lanterns | https://www.legislation.gov.au/F2011L00227/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2011L00220 | Consumer Protection Notice No. 12 of 2011 – Permanent Ban on Combustible Candle Holders | https://www.legislation.gov.au/F2011L00220/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2010L03296 | Permanent Ban – Candles and Candle Wicks Containing Lead | https://www.legislation.gov.au/F2010L03296/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2010L03299 | Consumer Protection Notice No. 4 of 2010 – Permanent Ban on Fire Footbags | https://www.legislation.gov.au/F2010L03299/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2011L00228 | Consumer Protection Notice No. 18 of 2011 – Permanent Ban on Toy-like Novelty Cigarette Lighters | https://www.legislation.gov.au/F2011L00228/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2011L00225 | Consumer Protection Notice No. 15 of 2011 – Permanent Ban on Novelty Cigarettes Containing Talc | https://www.legislation.gov.au/F2011L00225/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2011L00230 | Consumer Protection Notice No. 20 of 2011 – Permanent Ban on Yo-yo Water Balls | https://www.legislation.gov.au/F2011L00230/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2011L00222 | Consumer Protection Notice No. 13 of 2011 – Permanent Ban on Mouth-inflatable Toys Containing Small Beads | https://www.legislation.gov.au/F2011L00222/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2010L03300 | Consumer Protection Notice No. 18 of 2010 – Permanent Ban on "No Holes" Vacuum Tongue Studs | https://www.legislation.gov.au/F2010L03300/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2010L03293 | Permanent Ban – Glucomannan in Tablet Form | https://www.legislation.gov.au/F2010L03293/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2010L03279 | Consumer Protection Notice No. 4 of 2009 – Toothpaste Containing Diethylene Glycol | https://www.legislation.gov.au/F2010L03279/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2011L00223 | Consumer Protection Notice No. 16 of 2011 – Permanent Ban on Swimming Pools and Spas with Unsafe Design Features | https://www.legislation.gov.au/F2011L00223/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2011L00229 | Consumer Protection Notice No. 19 of 2011 – Permanent Ban on Children's Art/Craft/Stationery Sets with Undeclared Knives or Cutters | https://www.legislation.gov.au/F2011L00229/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-EESS-RESPONSIBLE-SUPPLIER | EESS – Manufacturers and importers (Responsible Suppliers) | https://www.eess.gov.au/responsible-supplier/manufacturers-and-importers-responsible-suppliers/ | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-EESS-FEES | EESS – Registration fees | https://www.eess.gov.au/registration/registration-fees/ | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-EESS-JURISDICTIONS | EESS – Participating jurisdictions | https://www.eess.gov.au/about/participating-jurisdictions/ | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-EESS-LEVEL3 | EESS – Level 3 in-scope electrical equipment registration | https://www.eess.gov.au/registration/registration-in-scope-electrical-equipment/level-3/ | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-EESS-RECS | EESS – Recognised External Certification Scheme (RECS) certifiers | https://www.eess.gov.au/safety-requirements/certification-general/recognised-external-certification-scheme-recs-certifiers/recs/ | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-EESS-SELLER-GUIDE | EESS Online Marketplace Seller Guide v1.0 (July 2026) | https://www.eess.gov.au/wp-content/uploads/2026/07/EESS-Online-Marketplace-Seller-Guide-v1.0.pdf | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-NSW-ELEC-APPROVAL | NSW Government – Electrical approval schemes (declared electrical articles) | https://www.nsw.gov.au/business-and-economy/running-a-business/selling-goods-and-services/electrical-approval-schemes | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-NSW-EMOBILITY | NSW Government – Supplying e-micromobility products | https://www.nsw.gov.au/business-and-economy/running-a-business/selling-goods-and-services/supplying-e-micromobility-products | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-ESV-EMOBILITY | Energy Safe Victoria – Electrical safety requirements for e-transport devices | https://www.energysafe.vic.gov.au/electrical-safety-requirements-e-transport-devices | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-TREASURY-EBIKE-2026 | Treasury Ministers – Stronger product safety standards for e-bikes (6 Aug 2026) | https://ministers.treasury.gov.au/ministers/andrew-leigh-2025/media-releases/stronger-product-safety-standards-e-bikes | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2018L00028 | Radiocommunications Labelling (Electromagnetic Compatibility) Notice 2017 | https://www.legislation.gov.au/F2018L00028/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2025L01047 | Radiocommunications (Low Interference Potential Devices) Class Licence 2025 | https://www.legislation.gov.au/F2025L01047/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2025L00401 | Telecommunications (Labelling Notice for Customer Equipment and Customer Cabling) Instrument 2025 | https://www.legislation.gov.au/F2025L00401/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2022L01624 | Telecommunications (Mobile Equipment Air Interface) Technical Standard 2022 | https://www.legislation.gov.au/F2022L01624/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-C2012A00132 | Greenhouse and Energy Minimum Standards Act 2012 | https://www.legislation.gov.au/C2012A00132/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-ENERGYRATING-APPLICANT | GEMS Registration System – Create an applicant | https://reg.energyrating.gov.au/application/help/create_an_applicant/ | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-WATERMARK-WHAT | ABCB WaterMark – What is WaterMark | https://watermark.abcb.gov.au/consumers/what-watermark | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-WATERMARK-SCHEDULE | ABCB WaterMark – Schedule of Products (2026-2) | https://watermark.abcb.gov.au/certification/schedule-products | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-WATERMARK-LEADFREE | ABCB WaterMark – Lead-free plumbing products | https://watermark.abcb.gov.au/plumbers/lead-free-plumbing-products | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2013L01574 | Water Efficiency Labelling and Standards Determination 2013 (No. 2) | https://www.legislation.gov.au/F2013L01574/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-C2005A00004 | Water Efficiency Labelling and Standards Act 2005 | https://www.legislation.gov.au/C2005A00004/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-ESV-GAS-ONLINE | Energy Safe Victoria – Gas appliances online sales | https://www.energysafe.vic.gov.au/industry-guidance/gas-and-pipelines/gas-appliances-equipment-and-manufacturers/gas-appliances-online-sales | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-TGA-DEVICE-ARTG | Confirm your product needs to be in the ARTG as a medical device ／ Therapeutic Goods Administration (TGA) | https://www.tga.gov.au/products/medical-devices/application-and-market-authorisation/supply-medical-device/medical-device-inclusion-process/confirm-your-product-needs-be-artg-medical-device | S2 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2002B00237 | Therapeutic Goods (Medical Devices) Regulations 2002 | https://www.legislation.gov.au/F2002B00237/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-TGA-ADVERTISING-REPRESENTATIONS | Restricted and prohibited representations in advertising | https://www.tga.gov.au/products/regulations-all-products/advertising/applying-advertising-code/restricted-and-prohibited-representations-advertising | S2 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-TGA-COSMETIC-OR-THERAPEUTIC | Determining if your product is a cosmetic or therapeutic good | https://www.tga.gov.au/resources/guidance/determining-if-your-product-cosmetic-or-therapeutic-good | S2 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2019L01352 | Therapeutic Goods (Declared Goods) Order 2019 | https://www.legislation.gov.au/F2019L01352/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-TGA-SUNSCREEN | Sunscreen regulation in Australia ／ Therapeutic Goods Administration (TGA) | https://www.tga.gov.au/products/medicines/therapeutic-sunscreens/overview/sunscreen-regulation-australia | S2 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-TGA-DISINFECTANTS | Understanding regulation of disinfectants, sterilants and sanitary products | https://www.tga.gov.au/resources/guidance/understanding-regulation-disinfectants-sterilants-and-sanitary-products | S2 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-TGA-VAPES-RETAILERS | Vapes: information for retailers | https://www.tga.gov.au/products/unapproved-therapeutic-goods/therapeutic-vaping-goods/vaping-hub/vapes-information-retailers | S2 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-ABF-VAPES | ABF – Nicotine, electronic cigarettes and vapes | https://www.abf.gov.au/importing-exporting-and-manufacturing/prohibited-goods/tobacco/nicotine-electronic-cigarettes-vapes | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2026L01327 | Therapeutic Goods (Poisons Standard—October 2026) Instrument 2026 | https://www.legislation.gov.au/F2026L01327/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-APVMA-REGISTRATION | Which products/chemicals require registration | https://www.apvma.gov.au/registrations-and-permits/chemical-product-registration/which-products-chemicals-require-registration | S2 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-APVMA-SCOPE | The chemicals and products we regulate | https://www.apvma.gov.au/about/about-us/apvma-basics/chemicals-and-products-we-regulate | S2 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-APVMA-IMPORT | Importing agricultural or veterinary chemicals | https://www.apvma.gov.au/registrations-and-permits/import-and-export/importing-agricultural-or-veterinary-chemicals | S2 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F1996B00288 | Agricultural and Veterinary Chemicals Code Regulations 1995 | https://www.legislation.gov.au/F1996B00288/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-AICIS-WHO-MUST-REGISTER | What is registration and who must register? | https://www.industrialchemicals.gov.au/business/getting-started-registration-importing-and-manufacturing/what-registration-and-who-must-register | S2 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-AICIS-COSMETICS | Personal care, skincare, make-up and other cosmetic products | https://www.industrialchemicals.gov.au/cosmetics-and-soap/personal-care-skincare-make-and-other-cosmetic-products | S2 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-FSANZ-IMPORTED | FSANZ – Imported foods | https://www.foodstandards.gov.au/consumer/imported-foods | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-DAFF-IFIS | Imported Food Inspection Scheme - DAFF | https://www.agriculture.gov.au/biosecurity-trade/import/goods/food/inspection-testing/ifis | S2 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2015L00386 | Australia New Zealand Food Standards Code – Standard 1.2.1 – Requirements to have labels or otherwise provide information | https://www.legislation.gov.au/F2015L00386/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2015L00421 | Australia New Zealand Food Standards Code – Standard 2.9.4 – Formulated supplementary sports foods | https://www.legislation.gov.au/F2015L00421/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2016L00528 | Competition and Consumer (Industry Code—Country of Origin Food Labelling Information Standard) 2016 | https://www.legislation.gov.au/F2016L00528/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-FSANZ-COO | FSANZ – Country of origin labelling | https://www.foodstandards.gov.au/consumer/labelling/coo | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-LEG-F2015L00416 | Australia New Zealand Food Standards Code – Standard 1.4.4 – Prohibited and restricted plants and fungi | https://www.legislation.gov.au/F2015L00416/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-QPS-KNIFE-SELLERS | Queensland Police – End Knife Violence: Guide for Sellers (2024) | https://www.police.qld.gov.au/sites/default/files/2024-07/End-Knife-Violence-Guide-for-Sellers-Booklet1.pdf | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-VICPOL-MACHETE | Victoria Police – Machete ban | https://www.police.vic.gov.au/machete-ban | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-VICPOL-PROHIBITED | Victoria Police – List of prohibited weapons | https://www.police.vic.gov.au/list-prohibited-weapons | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-WAPOL-KNIFE | WA Police – Knife and edged weapon laws | https://www.wa.gov.au/organisation/western-australia-police-force/wa-knife-and-edged-weapon-laws | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-SA-LAWHANDBOOK-WEAPONS | SA Law Handbook – Prohibited weapons and dangerous articles | https://www.lawhandbook.sa.gov.au/ch12s07s07.php | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-QLD-WEAPONS-CAT | Weapons Categories Regulation 1997 (Qld) | https://www.legislation.qld.gov.au/view/pdf/inforce/current/sl-1997-wcr | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-ACT-PROHIBITED-WEAPONS | Prohibited Weapons Act 1996 (ACT) | https://www.legislation.act.gov.au/a/1996-75 | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-ABF-WEAPONS | ABF – Weapons (prohibited goods) | https://www.abf.gov.au/importing-exporting-and-manufacturing/prohibited-goods/categories/weapons | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-ABF-IMITATION-FIREARMS | ABF – Importing imitation firearms to Australia | https://www.abf.gov.au/importing-exporting-and-manufacturing/prohibited-goods/firearms/importing-imitation-firearms-to-australia | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-ABF-LIST | ABF – Prohibited and restricted goods list of items | https://www.abf.gov.au/importing-exporting-and-manufacturing/prohibited-goods/list-of-items | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-ABF-ASBESTOS | ABF – Asbestos | https://www.abf.gov.au/importing-exporting-and-manufacturing/prohibited-goods/asbestos | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-ABF-ASBESTOS-GOODS | ABF – Goods that might contain asbestos | https://www.abf.gov.au/importing-exporting-and-manufacturing/prohibited-goods/asbestos/goods-that-might-contain-asbestos | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-ABF-ACN-2024-32 | Australian Customs Notice 2024/32 – Asbestos border controls (assurance and testing) | https://www.abf.gov.au/help-and-support-subsite/CustomsNotices/2024-32.pdf | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-ABF-ACN-2015-27 | DIBP Notice 2015/27 – Asbestos CPQ for children's crayons and toy sets from China | https://www.abf.gov.au/help-and-support-subsite/CustomsNotices/2015-27.pdf | S2 | webfetch | 2026-10-10 |
| SRC-AU-AMZ-G200164670 | Offensive and controversial materials | https://sellercentral.amazon.com.au/help/hub/reference/external/G200164670?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-DAFF-SEEDS | Importing seeds for planting - DAFF | https://www.agriculture.gov.au/biosecurity-trade/import/goods/plant-products/seeds-for-sowing | S2 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-F2021L00258 | Biosecurity (Conditionally Non-prohibited Goods) Determination 2021 | https://www.legislation.gov.au/F2021L00258/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-DAFF-TIMBER-PACKAGING | Timber and bamboo packaging - DAFF | https://www.agriculture.gov.au/biosecurity-trade/import/goods/timber-packaging | S2 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-DAFF-BMSB | Seasonal measures for Brown marmorated stink bug (BMSB) | https://www.agriculture.gov.au/biosecurity-trade/import/before/brown-marmorated-stink-bugs | S2 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-DAFF-MAIL | Sending or ordering goods online from outside Australia | https://www.agriculture.gov.au/biosecurity-trade/travelling/bringing-mailing-goods/mail | S2 | jina_reader | 2026-10-10 |
| SRC-AU-GOV-LEG-C2004A00485 | Environment Protection and Biodiversity Conservation Act 1999 (Part 13A – international wildlife trade) | https://www.legislation.gov.au/C2004A00485/latest/text | S2 | webfetch | 2026-10-10 |
| SRC-AU-GOV-ATO-LVIG | GST on low value imported goods | https://www.ato.gov.au/businesses-and-organisations/international-tax-for-business/gst-for-non-resident-businesses/gst-on-low-value-imported-goods | S2 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G200404870 | Important information for international sellers | https://sellercentral.amazon.com.au/help/hub/reference/external/G200404870?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G201567350 | Additional information and resources for sellers about our Restricted Products policy | https://sellercentral.amazon.com.au/help/hub/reference/external/G201567350?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G2JX2MAWJ27DWAY6 | Compliance Reference | https://sellercentral.amazon.com.au/help/hub/reference/external/G2JX2MAWJ27DWAY6?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |
| SRC-AU-AMZ-G200164330 | Restricted products | https://sellercentral.amazon.com.au/help/hub/reference/external/G200164330?mons_sel_locale=en_AU | S1 | jina_reader | 2026-10-10 |

## 待核实/冲突

1. **服装类是否需审核（冲突）**：服装页 G200164430 称服装鞋类仅限预批准卖家，而需审核类目页 G200333160 未列服装。规则只收录了“二手服装鞋履禁售”[R:AU-L1-CLOTHING-001]，是否需类目审核以卖家后台为准。[SRC-AU-AMZ-G200164430] [SRC-AU-AMZ-G200333160]
2. **“强化安全 listing 合规”类目清单未取得**：GUQ848NB5HZ6M6A4 与“安全风险产品销售限制” GKKYJ3C25DG334PW 两页用 en_AU、zh_CN 均只抓到导航壳，哪些类目需要商业保险（COI）未能列全；目前仅锂电池页明确要求 COI。
3. **EESS Level 3 清单**：由调研代理按官方 PDF 表格坐标解析出 62 类，关键品类（例如按摩器、风扇、厨师机）请人工复核原 PDF。[SRC-AU-GOV-EESS-LEVELS]
4. **移动电源是否在 EESS 范围**：官方未明说；按电压定义推定（ELV、非市电）不在范围，但亚马逊仍要求 62368.1 等报告。
5. **NSW 电气审批与 EESS 的互认**：NSW 是否直接承认 RECS 证书仅见检测机构资料；NSW 电动出行规定引用的政府公报编号（No 291/17 Jul 2026 vs No 203/23 May 2025）不一致。
6. **新州、南澳、北领地、塔州武器法细节**：新州立法网站屏蔽，新州 OC 喷雾、防弹衣、双节棍、弹弓的条文及 2024 刀具法改革生效日仅见二手/摘要；南澳水弹枪、仿真枪、防弹衣、伸缩棍状态，西澳/昆州防弹衣，塔州 OC 喷雾，北领地 2024 年后版本未核实。
7. **维州砍刀特赦期**（至 2025-11-30）与 ACL 临时供应禁令（2025-05-28 至 08-31）仅见搜索摘要。
8. **人造石进口禁令生效日**：CPIR 第 5M 条已确认，2025-01-01 生效日仅见搜索摘要 [R:AU-L6-ENGSTONE-001]。
9. **ODS/SGG 设备许可细节**：小量豁免、R600a/R290/CO2 设备豁免、2024-07-01 起 GWP>750 小型空调禁入仅见摘要 [R:AU-L6-ODS-001]。
10. **ACN 2025/33 适用国家**：通知称“certain countries”，未点名中国；2025 年 11 月中国产彩沙石棉召回（ACCC）细节仅见摘要。
11. **ACMA、Energy Rating、WELS 官网**无法访问（超时/404），相关要求以立法文本为准；ACMA 称国家数据库即 EESS 平台仅见摘要。
12. **无人机（CASA）**：未取得 CASA 注册与运营规则的具体条款，E.15 仅覆盖 ACMA 射频要求。
13. **食品接触材料**：未查到澳洲专门的食品接触材料注册/声明制度；亚马逊“含 BPA 产品”禁售的适用范围（是否仅限食品接触/儿童用品）页面未细化，规则按字面处理 [R:AU-L1-HAZMAT-001]。
14. **烟雾报警器标准**：亚马逊合规页给出 AS 3786:2014 与 AS 7240.6:2017，受限商品页只说“澳洲强制标准”，各州建筑法规是否要求特定认证未核实 [R:AU-L3-ALARM-001]。
15. **带温度传感器婴儿浴盆禁售原因**：亚马逊未说明，页面关联纽扣电池标准，属推测 [R:AU-L1-BATHTUB-001]。
16. **亚马逊受限商品页中的美国式条目**：化妆品页仍引用 FDA（如“未经 FDA 批准的米诺地尔”），补充剂页引用 FDA 链接，可能为全球模板遗留，澳洲执行口径待核。
17. **AICIS 与 FBA**：中国卖家用 FBA 头程、由货代作为进口商时谁是“引入者”，AICIS 未明确；2026–27 注册年度费用未取得。
18. **宠物食品排除条件、TGA 申办者要求页面**：调研代理经网页存档读取（APVMA stockfeed-petfood、TGA regulation essentials），本次 jina 复抓 TGA 页面失败（HTTP 422/429），相关细节以已抓取的 TGA/APVMA 其他页面为准。
19. **州电动出行规定（维州、昆州）**：维州 ESV 2025 年咨询后截至 2026-02 未有决定；昆州无售卖认证规定（仅议会建议），均需跟进。
20. **ACCC 起诉亚马逊案（NSD905/2026，2026-05-29 提起，涉及缺失纽扣电池警示的儿童背包）与 City Beach 1,400 万澳元罚款**：仅见新闻/摘要（二手来源，待核），未纳入规则。
21. **州单一用途塑料禁令与肥料重金属限值**：亚马逊已统一禁售；各州具体清单与肥料 MPC 未逐州核实。
22. **州象牙/犀牛角国内交易禁令**：未核实。
23. **超声波驱虫器（冲突）**：APVMA 称声/光/电磁设备无需注册，亚马逊农药页却禁售“未经 APVMA 注册的驱虫装置（如超声波驱蚁器）”，两者结合等于不可售，规则按亚马逊口径处理 [R:AU-L1-PESTICIDE-001] [SRC-AU-AMZ-G202115120] [SRC-AU-GOV-APVMA-SCOPE]。
24. **ACL 一般安全条款（GSP）**：截至 2026-09 无立法；Treasury 2026 年咨询为“第一阶段”，后续时间表未知。
