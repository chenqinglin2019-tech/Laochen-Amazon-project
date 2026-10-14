# 美国站（amazon.com） 禁限售与合规要求

> 由调研分册合并生成（2026-10-11）。本文描述亚马逊平台政策和当地法规要求，不构成法律意见。
> [SRC-…] 为来源编号（见 rules/sources/），[R:…] 为机读规则编号（见 rules/sites/）。

## 第一部分 · 亚马逊平台政策（L1–L4）

> 规则包版本：draft · 调研日期：2026-10-10 · 本文描述亚马逊平台政策，不构成法律意见。
> 本文件只覆盖模板的 A、B、C、D 节，F 节中亚马逊自身的要求，G 节中亚马逊政策变化，以及 H 节和“待核实”。美国当地法规（L5/L6，模板 E 节）由另一份文档负责。
> 每条结论后用 [SRC-…] 标注来源（见 rules/sources/US_amazon.yaml），用 [R:规则ID] 关联机读规则（rules/sites/US_amazon.yaml）。
> 来源级别：S1 亚马逊官方 · S2 政府官方 · S3 二手。本文全部结论来自 S1（亚马逊卖家平台帮助页，经 r.jina.ai 渲染抓取，快照在 policy/snapshots/US/）。

### 速览：中国卖家最需要知道的事

1. **18650/21700 等圆柱形可充电锂电池全面禁售**：额定 ≥3.0V 的圆柱可充电锂电芯（14500、16340、18650、21700、26650、32650 等）以单节、电池组、备用电池、以及“使用这类电芯的产品”（手电、头灯、电动工具、充电宝、电池盒）形式都不能卖；只有带端子连接器且包覆密封的电池组例外，改按锂电池政策审核 [SRC-US-AMZ-G2HSXA2KM59YX5AT] [R:US-L1-BATT-001]。
2. **强化安全类目要 100 万美元产品责任险 + 授权 TIC 验证**：儿童产品、补充剂和口服 OTC、锂电池及锂电产品、小家电、户外动力/取暖、个人防护、床垫、轮胎、水上安全等 11 组类目，必须提交每次事故及累计 ≥100 万美元、事故发生制、以 Amazon.com Services LLC 为附加被保险人的 COI，并由亚马逊授权 TIC 机构代交检测文件 [SRC-US-AMZ-G4RUG6EAT2ZLVSRT] [R:US-L2-ENHANCED-001] [R:US-L2-ENHANCED-002]。
3. **农药与“抗菌/防霉/驱虫”宣称**：只有美国居民才能在美国站卖农药/农药器械；普通商品只要写了抗菌、防霉、防螨、杀菌、驱蚊，就可能被判为农药而下架；宣称杀菌的 UV 灯一律禁售 [SRC-US-AMZ-G202115120] [R:US-L1-PEST-001] [R:US-L2-PEST-010] [R:US-L1-PEST-005]。
4. **植物种子不能跨境卖**：从美国境外进口或由非美国居民销售的植物、种子禁售 [SRC-US-AMZ-G201737480] [R:US-L1-PLANT-001]。
5. **疾病宣称红线**：任何类目都不得在未获 FDA 批准时宣称治疗/预防疾病，亚马逊把 Anti-Bacterial、Anti-Fungal、Anti-Microbial、Nano silver、COVID-19、肥胖等都列为不可宣称词 [SRC-US-AMZ-G202024200] [R:US-L1-CLAIM-001]。
6. **儿童产品三件套**：CPSC 认可实验室报告 + 儿童产品证书（CPC，7 项要素，亚马逊不能作进口商）+ 产品和包装上的永久追踪标签；玩具还须在详情页设置 CPSIA 窒息警示和最低月龄 [SRC-US-AMZ-GKJRA3FRPRKVBJJS] [SRC-US-AMZ-GSGB43AFZNDWD4U8] [R:US-L3-TOY-001] [R:US-L3-CPSC-001]。
7. **大量“中国常见品”直接禁售**：孔明灯、派对拉炮/仙女棒/摔炮、娱乐用磁力珠、睡眠封口贴、耳烛、去痣去皮赘产品、车用座椅加热垫、HID/LED 大灯改装套件、溶剂收集器、蝴蝶刀/弹簧刀、指虎（含猫耳钥匙扣）、棕榈叶餐具、食用墨水打印机等 [SRC-US-AMZ-G200164570] [SRC-US-AMZ-G200164410] [SRC-US-AMZ-G200164950]。

### A. 禁售清单（L1）

下表按亚马逊“受限商品”类目汇总平台禁售项（L1）。“禁止销售的典型商品”一栏是对应规则的主题；完整触发条件、关键词见规则文件。凡标“地域限制”的允许项，亚马逊会按州自动屏蔽销售。

| 类别 | 亚马逊页面（G 编号） | 禁止销售的典型商品 | 例外/允许销售的情况 | 规则ID |
| --- | --- | --- | --- | --- |
| 酒类 | G200164340 | 含酒精（>0.0% ABV）饮料、提及酿酒的蒸馏套件、酒类许可证、面向 21 岁以上顾客或封装纯酒精的商品禁售（预批准卖家除外） [SRC-US-AMZ-G200164340] [SRC-US-AMZ-G200164550] | 预批准卖家可售酒类及 0–0.5% ABV 无醇饮料；0.0% ABV 饮料、开瓶器醒酒器等酒具、不含酒的纪念品、非酒精用途蒸馏器可售 | R:US-L1-ALCOHOL-001 |
| 动物及动物制品 | G200164370 | 濒危/受保护物种及其制品（含皮毛、羽毛）禁售；含动物象牙的产品禁售；活体动物禁售（昆虫、鱼、贝类、甲壳类除外）；鲨鱼、鲸、海豚、海豹等海洋哺乳动物来源产品禁售；熊、美洲狮、猫、狗部位及制品禁售；违反《候鸟条约法》的产品及未获进口许可的燕窝禁售；人用和兽用疫苗及不符合《病毒-血清-毒素法》的产品禁售；宠物剪耳、断尾、去爪等肢体改造工具禁售；动物粪便、植物害虫、未注册宠物食品禁售 [SRC-US-AMZ-G200164370] | 活体贝类甲壳类；饵料/饲料用活昆虫蠕虫（地域限制）；标明人造的仿制品；不受限动物制品（如鲨鱼牙饰品）；兽医指导下的处方粮 | R:US-L1-ANIMAL-001<br>R:US-L1-ANIMAL-002<br>R:US-L1-ANIMAL-003<br>R:US-L1-ANIMAL-004<br>R:US-L1-ANIMAL-005<br>R:US-L1-ANIMAL-006<br>R:US-L1-ANIMAL-007<br>R:US-L1-ANIMAL-008 |
| 艺术品 | G201279060、G200164390 | 侵犯版权或商标的未授权艺术复制品禁售 [SRC-US-AMZ-G200164390] | 标题和描述注明 reproduction 的复制品；有真实性证明的真品；Fine Art 类目须审核 | R:US-L1-ART-003 |
| 汽车与动力运动 | G200164410、GJQMR3AUDBH6RXR5 | 排放控制系统破坏装置（Delete 套件、删除/性能调校器等）禁售；车用安全气囊、安全带及其部件禁售；仿官方应急车辆的警示灯禁售；HID 氙气/LED 大灯改装套件及不符合 FMVSS 108 的道路用替换灯具禁售；不符合 FMVSS 的车辆安全产品禁售（如不合规摩托车头盔）；规避执法、干扰车辆或道路安全功能的产品禁售；驾照、临时车牌、残障停车证、VIN 牌及 DOT/年检/注册贴纸禁售；车用座椅加热垫禁售；未加苦味剂且乙二醇含量超 10% 的防冻液、未经 EPA 认证的便携燃油罐禁售；二手/曾装配的轮胎、轮毂、轮辋、车轮配件及超龄轮胎禁售；需登记上牌的机动车禁售 [SRC-US-AMZ-G200164410] [SRC-US-AMZ-GRLKLZ6WQ9R259LC] [SRC-US-AMZ-G200164570] [SRC-US-AMZ-GKMN8QPMQ6K8SK3E] | 汽车蓄电池；全新合规轮胎；保持排放功能的零件；持 CARB EO 的性能调校器；EPA 认证便携油罐；脚垫、雨刮等配件；Amazon Autos 项目卖家的整车 | R:US-L1-AUTO-001<br>R:US-L1-AUTO-002<br>R:US-L1-AUTO-003<br>R:US-L1-AUTO-004<br>R:US-L1-AUTO-005<br>R:US-L1-AUTO-006<br>R:US-L1-AUTO-007<br>R:US-L1-AUTO-008<br>R:US-L1-AUTO-009<br>R:US-L1-TIRE-001<br>R:US-L1-AUTO-013 |
| 人造板制品 | GKY5NBH8EHAUFQ27 | 甲醛释放不达标或未按 EPA 规定逐件标签的人造板产品禁售 [SRC-US-AMZ-GKY5NBH8EHAUFQ27] | 符合 EPA 甲醛标准且逐件贴 TSCA Title VI 标签的产品 | R:US-L1-COMPWOOD-001 |
| 化妆品与护肤护发 | G200164470 | 掺假/错误标识化妆品（含未获 FDA 批准的色素）、被 FDA 召回/警告的产品、受管制物质禁售；含禁用成分的化妆品禁售（比马前列素、异丙基氯前列醇等）；高浓度酸、过氧化氢、米诺地尔超限的产品及无晒伤警示的果酸焕肤产品禁售；存在不合理伤害风险的化妆品禁售（含汞护肤品、Kohl 眼妆、永久睫毛染料、皮肤用指甲花、塑料微珠、加热释放甲醛产品）；处方或需专业人员监督使用的美容产品禁售（彩色/矫正隐形眼镜、注射类产品）；总量超过 16 盎司的丙酮（如洗甲水）禁售 [SRC-US-AMZ-G200164470] | 合规化妆品须满足 L3 标签/资料要求；兼属药品的须满足药品要求 | R:US-L1-COSM-001<br>R:US-L1-COSM-002<br>R:US-L1-COSM-003<br>R:US-L1-COSM-004<br>R:US-L1-COSM-005<br>R:US-L1-COSM-006 |
| CPAP 清洁消毒设备 | GZ4E8J47K2YNXLQ9 | 未经 FDA 批准/许可的 CPAP 清洁消毒设备（臭氧型、紫外线型）禁售 [SRC-US-AMZ-GZ4E8J47K2YNXLQ9] | 仅限获 FDA 授权的产品 | R:US-L1-CPAP-001 |
| 货币、硬币、现金等价物与礼品卡 | G200164450 | 纸币、仿制/伪造货币、改动过的法定货币、印钞设备、股票证券禁售；礼品卡/储值卡、现金等价物、非货币化金银条、贵金属圆币、未检视币袋、福利券禁售 [SRC-US-AMZ-G200164450] | 收藏硬币（须审核）；永久标 COPY 且尺寸合规的道具钞；货币化金银币；标注的复制币；预批准卖家的零售礼品卡（≤2 | R:US-L1-CURRENCY-001<br>R:US-L1-CURRENCY-002 |
| 膳食补充剂 | G201829010 | 被 FDA 召回/警示/警告信点名、被 FTC 点名虚假宣传或标识不当的膳食补充剂禁售；含 CBD 及其他受管制物质/DEA List I 化学品的补充剂禁售；含未批准药物或处方成分的补充剂禁售（多肽 BPC-157 等、GLP-1 受体激动剂）；作为膳食补充剂或排毒产品营销的皮肤贴片禁售；掺假或不安全补充剂禁售（tejocote 根、巴西籽/黄夹竹桃、纯咖啡因粉、受保护动物成分）；性功能增强和减肥补充剂不得以单粒或两粒装销售 [SRC-US-AMZ-G201829010] | 符合 cGMP、经 TIC 验证、宣称合规的补充剂 | R:US-L1-SUPP-001<br>R:US-L1-SUPP-002<br>R:US-L1-SUPP-003<br>R:US-L1-SUPP-004<br>R:US-L1-SUPP-005<br>R:US-L1-SUPP-006 |
| 药品与吸毒用具 | G200164490 | 被 FDA/DEA/FTC 认定为错误标识、误导、未批准、召回或不得销售的药品禁售；受管制物质及 DEA 关注药物/化学品禁售（含 poppers、罂粟壳、碘 >2.2% 等）；致幻剂、迷幻剂及模仿其效果的产品禁售；CBD 及致醉性大麻产品禁售（全谱/广谱大麻油、含 THC、可发芽大麻籽、合成大麻素）；违背制造商用途的营销（风味/大容量笑气罐、提及毒品用途的 Listing）禁售；处方药及其活性成分禁售（可待因、麻黄碱、麦角胺、鱼用抗生素、GLP-1、疫苗、非持证药房销售的兽用处方药）；未经批准的药物禁售（kratom、kanna、顺势疗法出牙产品、注射剂、洛哌丁胺 >48 mg、苯丙醇胺、“合法类固醇”等）；吸毒用具禁售（水烟枪/非烟草烟斗、研磨器、雾化器、BHO 提取器、压片机、尿检作弊品等）；治疗痣、皮赘、脂溢性角化、传染性软疣的产品禁售 [SRC-US-AMZ-G200164490] [SRC-US-AMZ-G201829010] | 合规 OTC 药品；当地法律允许的芬太尼检测试纸；符合补充剂政策的 Kanna 补充剂、混合草本茶、酊剂、精油 | R:US-L1-DRUG-001<br>R:US-L1-DRUG-002<br>R:US-L1-DRUG-003<br>R:US-L1-DRUG-004<br>R:US-L1-DRUG-005<br>R:US-L1-DRUG-006<br>R:US-L1-DRUG-007<br>R:US-L1-DRUG-008<br>R:US-L1-DRUG-009 |
| 电子产品 | G200164510 | 美国禁售的反垄断/网络安全软件产品禁售；序列号被移除或篡改的电子产品禁售；干扰警用雷达、激光测速或交通信号的设备禁售；未经授权解扰有线/卫星电视的设备、智能卡和教程禁售；促成盗版或绕过版权保护的设备禁售（破解卡、DVD 拷贝机、去区码蓝光机、违规流媒体盒子）；不当绕过手机网络锁的产品（越狱/解锁手机、解锁码、坏 ESN 手机、改剪的 Micro SIM）禁售；美国国会图书馆 NLS 盲人有声书播放器及配件禁售；不合规的节日灯串、装饰灯、延长线及不符合 USB-IF 规范的 USB-C 线缆/适配器禁售；Apple/iPhone 品牌替换电池、三星 Galaxy Note 7、过期电池禁售 [SRC-US-AMZ-G200164510] [SRC-US-AMZ-G202137960] [SRC-US-AMZ-GRLKLZ6WQ9R259LC] | 合法、符合行业标准、不干扰其他电子设备、不规避版权等技术控制的电子产品 | R:US-L1-ELEC-001<br>R:US-L1-ELEC-002<br>R:US-L1-ELEC-003<br>R:US-L1-ELEC-004<br>R:US-L1-ELEC-005<br>R:US-L1-ELEC-006<br>R:US-L1-ELEC-007<br>R:US-L1-ELEC-008<br>R:US-L1-ELEC-009 |
| 射频设备 | GHXJGN6T5K8HGGWW | 未取得 FCC 授权的射频设备、无美国责任方的 SDoC 设备、FCC“受管控清单”设备、宣传超出批准频段的设备禁售；信号干扰器、GPS 转发器、CB 功率放大器、工业级信号放大器、非航海用途 AIS、600/700 MHz 无线麦克风禁售 [SRC-US-AMZ-GHXJGN6T5K8HGGWW] [SRC-US-AMZ-G200164510] | 取得 FCC 授权（认证或 SDoC+美国责任方）且只宣传批准频段的设备 | R:US-L1-RF-001<br>R:US-L1-RF-002 |
| 锂电池 | G7PAP6BJAUXRM4LH、G2HSXA2KM59YX5AT | 圆柱形可充电锂电池（18650/21700/26650 等）及含此类电池的产品禁售 [SRC-US-AMZ-G2HSXA2KM59YX5AT] [SRC-US-AMZ-G7PAP6BJAUXRM4LH] [SRC-US-AMZ-G200164510] [SRC-US-AMZ-GRLKLZ6WQ9R259LC] | 带端子连接器、包覆密封的圆柱锂电池组（按锂电池政策审核）；其他锂电池经保险+TIC 后可售 | R:US-L1-BATT-001 |
| 爆炸物、武器及相关物品 | G200164950 | 枪支弹药及弹药部件禁售（子弹、霰弹、底火、火药、弹壳、空包弹）；爆炸物禁售（烟花、信号弹及发射器、手榴弹/烟雾弹、地雷、IED 训练器材、爆炸性材料）；枪支（含 3D 打印枪及图纸、古董枪、伪装枪、电子枪、发令枪）及无标识仿真枪禁售；全自动/连发改装件禁售（自动扳机阻铁、机枪改装套件、Bump stock、扳机加速器、突击武器改装套件）；消音器/抑制器（含假消音器、软弹/气枪用）及溶剂收集器禁售；弹匣及相关件、指定口径弹匣装填器、制造弹匣套件禁售；突击武器/枪支结构件和外部配件禁售（机匣、枪管、护木、导轨、可调枪托、手枪支架、垂直握把等）；枪械内部活动件、AR 专用工具、枪械生产设备禁售；违禁刀具禁售（弹簧刀、蝴蝶刀、重力刀、伪装刀、指虎刀、推刀、飞镖/飞刀卡、剑杖等）；防弹衣、防弹插板及防弹头盔/服装禁售；指虎、双节棍、警棍、甩棍、短棍、拐、铁蒺藜等打击类武器禁售；喷火器、发令枪/空包枪、钢夹兽夹、隐藏式武器、军警专用物品禁售 [SRC-US-AMZ-G200164950] | BB/软弹/彩弹枪及弹（地域限制）；1898 年前枪支的不可击发仿制品；有法定标识的玩具枪；枪托底板、固定枪托、枪套、两点式枪带等配件；猎刀、厨刀、仿制剑、砍刀；伞刀和助力开合刀（地域限制）；防狼喷雾、电击器、弓弩、弹弓、手铐、吹箭（地域限制）；泡棉双节棍、kubotan、战术笔、鱼枪、捕鼠器；安全求救信号弹（地域限制、不可 FBA）；塑料玩具手榴弹 | R:US-L1-WEAPON-001<br>R:US-L1-WEAPON-002<br>R:US-L1-WEAPON-003<br>R:US-L1-WEAPON-004<br>R:US-L1-WEAPON-005<br>R:US-L1-WEAPON-006<br>R:US-L1-WEAPON-007<br>R:US-L1-WEAPON-008<br>R:US-L1-WEAPON-009<br>R:US-L1-WEAPON-010<br>R:US-L1-WEAPON-011<br>R:US-L1-WEAPON-012 |
| 赌博与彩票 | G200685250 | 彩票、投币老虎机及可改装为投币的老虎机禁售 [SRC-US-AMZ-G200685250] | 仅用于展示或作为玩具的不可用老虎机 | R:US-L1-GAMBLE-001 |
| 人体部位与随葬文物 | G200164590 | 人体部位、遗骸、体液、墓碑及原住民/联邦土地文物禁售 [SRC-US-AMZ-G200164590] | 医学用途且销售地合法的人类头骨/骨骼；人发制品（假发） | R:US-L1-HUMAN-001 |
| 食品饮料 | G200164550 | 酒精含量 >0.5% 的食品饮料（食品类目内）、提及酿酒的酿造套件、酒类许可证禁售；槟榔、驴/马/骡肉、疯狂蜂蜜（含木藜芦毒素）、浓度 >10% 的亚硝酸钠禁售；食用墨水类商品（含营销用于食用墨水的打印机、墨盒、补充瓶）禁售；不符合美国进口条件的食品禁售（中国产肉及肉制品含牛油、韩国牛肉、无许可燕窝、内嵌玩具食品、泰国箭叶橙叶等）；槟榔叶鞘（棕榈叶）材质的食品接触餐具禁售；非批准品牌或单包超过 1 磅的罂粟籽禁售；未满足 FDA 上市前要求的婴儿配方奶粉禁售 [SRC-US-AMZ-G200164550] [SRC-US-AMZ-GRLKLZ6WQ9R259LC] | 0.0% ABV 饮料；批准品牌且 ≤1 磅的罂粟籽；≤10% 亚硝酸钠；附进口许可的燕窝；合规食品须满足 L3 标签要求 | R:US-L1-FOOD-001<br>R:US-L1-FOOD-002<br>R:US-L1-FOOD-003<br>R:US-L1-FOOD-004<br>R:US-L1-FOOD-005<br>R:US-L1-FOOD-006<br>R:US-L1-FOOD-007 |
| 危险品与禁售物品 | G200164570、GRLKLZ6WQ9R259LC | 含二氯甲烷的产品禁售（脱漆剂、稀释剂、溶剂等）；危险化学品禁售（四氯化碳、氢氟酸、硝酸、叠氮化钠、乙醇胺、红磷、铝热剂、氰化物、>12% 过氧化氢、仅限工业用途化学品）；烟火类小商品禁售（拉炮/礼花筒、摔炮、仙女棒、玩具枪火药纸、引信、闪光纸、爆炸靶、道路信号弹、汽油）及爆炸物制作信息；孔明灯/河灯（天灯、漂浮灯笼）禁售；汞及含汞产品禁售（体温计、温控器、血压计、汞开关、新奇玩具/首饰等）；娱乐用小型强磁体/磁力珠套装禁售（Buckyballs 等）及 IMDEN 磁力片；婴儿睡眠高危产品禁售（软垫床围、倾斜睡眠产品、婴儿吊床、可放下侧栏婴儿床、大象睡枕）；琥珀/串珠/蘑菇形出牙产品、婴儿口罩、儿童颈部充气泳圈禁售；儿童上衣抽绳服装、草坪飞镖、水上步行球、牙签弩、飞镖指尖陀螺、打火机刀指尖陀螺禁售；军用式防毒面具及滤罐、细菌培养物（大肠杆菌）、不合规含氚产品、放射性污染产品、“标量量子能量”产品、废油禁售；不符合《安全饮用水法》的产品禁售（含铅水龙头、管件等） [SRC-US-AMZ-G200164570] [SRC-US-AMZ-GW6HK2RDRNNFW2ML] [SRC-US-AMZ-GRLKLZ6WQ9R259LC] [SRC-US-AMZ-G200164950] | 不含汞电池和可充电电池；EPA 认证便携油罐（地域限制）；≤8.4 g/支且每包 ≤10 支的笑气奶油弹（仅自配送）；含汞 ≤25 mg 的碱锰纽扣电池 | R:US-L1-HAZ-001<br>R:US-L1-HAZ-002<br>R:US-L1-HAZ-003<br>R:US-L1-HAZ-004<br>R:US-L1-HAZ-005<br>R:US-L1-HAZ-006<br>R:US-L1-HAZ-007<br>R:US-L1-HAZ-008<br>R:US-L1-HAZ-009<br>R:US-L1-HAZ-010<br>R:US-L1-HAZ-011 |
| 珠宝与宝石 | G200166630 | 贵金属标记不合规或不符合 FTC 珠宝指南的首饰禁售；辐照宝石（未获 NRC 授权）、非金伯利进程钻石、净度改善白钻、充填玻璃红宝石、俄罗斯原产钻石禁售 [SRC-US-AMZ-G200166630] | 打标正确、符合 FTC 指南的贵金属首饰；金伯利进程合规钻石；经 NRC 授权的辐照宝石 | R:US-L1-JEWEL-001<br>R:US-L1-JEWEL-002 |
| 激光产品 | G201689020 | 3B/4 级且 ≥5mW 激光产品、303nm 激光、超 1 级的儿童激光产品、超 3R 级冷激光理疗仪、无分级报告的“大功率/远射程”激光禁售 [SRC-US-AMZ-G201689020] [SRC-US-AMZ-G201707070] | 激光切割/雕刻设备及模组不受 ≥5mW 禁令；1/2/3R 级经 TIC 验证可售；<5mW 的 3B/4 级须预批准 | R:US-L1-LASER-001 |
| 照明 | G201997070、GRTV7X82BHXYCS9L | 不符合能效标准的灯泡（含光效 <45 lm/W 的通用照明灯）及非标准灯座转接器禁售 [SRC-US-AMZ-G201997070] [SRC-US-AMZ-GRTV7X82BHXYCS9L] | 光效 ≥45 lm/W 并完成 DOE 认证的通用照明灯 | R:US-L1-LIGHT-001 |
| 开锁与盗窃工具 | G200164850 | 开锁工具、配钥匙设备、防盗磁扣解锁器、读卡盗刷器、遥控截码器、汽车万能钥匙禁售 [SRC-US-AMZ-G200164850] | 空白钥匙坯 | R:US-L1-LOCK-001 |
| 医疗器械及配件 | G200164650 | 未获 FDA 许可/未注册列名、掺假或错误标识、带 FDA 标志、过期、“试用装”、二手翻新医疗器械禁售；耳烛和口闭胶带（睡眠封口贴及类似胶带）禁售 [SRC-US-AMZ-G200164650] [SRC-US-AMZ-GGS4MAMUUG4K5TJN] [SRC-US-AMZ-GRLKLZ6WQ9R259LC] | 已在 FDA 注册列名并按分类获 510(k)/PMA（或豁免）的 OTC 器械；Rx 器械仅限 PHC 项目 | R:US-L1-MED-001<br>R:US-L1-MED-002 |
| 冒犯性与争议性内容 | G200164670 | 宣扬仇恨、暴力、不宽容、恐怖组织或种族刻板印象的商品禁售（书籍音像除外）；利用人类悲剧或自然灾害的商品、描绘受害者或肇事者的商品禁售；描绘儿童虐待/剥削、对儿童性暗示、含成人内容的儿童产品禁售 [SRC-US-AMZ-G200164670] | 图书、音乐、影视不适用本政策；具纪念、历史或学术意义的悲剧相关商品 | R:US-L1-OFFENSIVE-001<br>R:US-L1-OFFENSIVE-002<br>R:US-L1-OFFENSIVE-003 |
| 其他受限商品 | G200685320 | 邦联旗商品和“Washington Redskins”商品禁售；非实物/非商品类 Listing 禁售（优惠券、域名、活动门票、不动产、数字下载/兑换码、个人信息名单、神秘盒、站外引流）；真实或仿制的政府/军方签发物品禁售（徽章、证件、疫苗卡、护照、执照、臂章、重型设备操作证、总统/国会印章）；含石棉、多氯联苯（PCB）产品及宣传未变性/可饮用的乙醇禁售；Magic Wine Decanter、不符合 USPS 要求的信箱、无 MIC/HIN 的休闲船艇、二手燃气连接管、Your Baby Can Read 产品、可放下侧栏婴儿床禁售；教师版教材、教师/考官用习题答案、UPC/EAN 条码标签及生成器禁售 [SRC-US-AMZ-G200685320] [SRC-US-AMZ-GRLKLZ6WQ9R259LC] [SRC-US-AMZ-G200164570] | 学生用教材及答案；预批准的视频游戏捆绑；详情页列明内容的盲盒 | R:US-L1-OTHER-001<br>R:US-L1-OTHER-002<br>R:US-L1-OTHER-003<br>R:US-L1-OTHER-004<br>R:US-L1-OTHER-005<br>R:US-L1-OTHER-006 |
| 农药与害虫防治 | G202115120 | 非美国居民卖家不得销售农药和农药器械（含所有带杀菌/抗菌/驱虫宣称、被认定为农药的商品）；未在 EPA/州注册的农药、非美版农药、限制使用/专业用农药、白蚁专用药、无 EPA 标识的农药器械禁售；农药产品作“安全/无毒/全天然”等虚假宣称或公共卫生宣称禁售；非批准品牌的驱蚊手环和驱蚊贴禁售；宣称杀菌消毒的紫外线装置禁售（无论是否有 EPA 编号）；户外用新烟碱类杀虫剂、破包/改量分装农药、翻新农药器械禁售；无有效 EPA 编号的泳池/水疗氯片、离子发生器、盐氯机禁售 [SRC-US-AMZ-G202115120] | 美国居民卖家、通过培训并获批、有 EPA 注册号/企业号或符合豁免的农药；批准品牌驱蚊手环/贴 | R:US-L1-PEST-001<br>R:US-L1-PEST-002<br>R:US-L1-PEST-003<br>R:US-L1-PEST-004<br>R:US-L1-PEST-005<br>R:US-L1-PEST-006<br>R:US-L1-PEST-007 |
| 植物与种子 | G201737480 | 非美国居民销售或从美国境外进口的植物、植物产品、繁殖材料和种子禁售；有害杂草、受检疫植物、Lacey Act/CITES 受保护植物、接触或食用致命的植物种子禁售 [SRC-US-AMZ-G201737480] | 美国居民、非进口、持证卖家销售的合规植物种子 | R:US-L1-PLANT-001<br>R:US-L1-PLANT-002 |
| 邮资机与邮票 | G200164730 | 邮资机销售/租赁、伪造邮票及制假设备、USPS 美国国旗永久邮票（非装裱纪念品）禁售 [SRC-US-AMZ-G200164730] | 邮资机耗材；现行邮票（国旗永久邮票除外）；信息披露完整的收藏邮票；已标注的复制邮票；装裱的国旗永久邮票纪念品 | R:US-L1-POSTAGE-001 |
| 禁止的商品宣称 | G202024200 | 未经 FDA 批准宣称诊断、治疗、缓解、预防疾病的商品禁售（含“抗菌/抗真菌/纳米银”、新冠、流感、癌症、糖尿病、肥胖等）；插电式节电盒/汽车节油器、违背科学的“不可能”产品和欺骗性功能宣称产品禁售且不可恢复 [SRC-US-AMZ-G202024200] [SRC-US-AMZ-GWTRG6BMJHECNCFR] [SRC-US-AMZ-GZ93G4JTAEVEJW62] | 经 FDA 批准/许可/授权的疾病宣称 | R:US-L1-CLAIM-001<br>R:US-L1-CLAIM-005 |
| 召回商品 | G200164750 | 被召回、市场撤回或停售的产品禁售 [SRC-US-AMZ-G200164750] | 满足召回恢复要求后 | R:US-L1-RECALL-001 |
| 制冷剂 | G5ER6LTGH2GFJLHQ | 消耗臭氧层物质（R-12、R-22 等）、仅限持证技师的替代制冷剂、列管 HFC（R-32、R-125、R-134a、R-410A 等）禁售 [SRC-US-AMZ-G5ER6LTGH2GFJLHQ] | ≤2 磅自封阀罐装、非 ODS/非列管 HFC 的汽车空调豁免制冷剂；R-744、R-728；含制冷剂电器；空罐（均受地域限制） | R:US-L1-REFRIG-001 |
| 随处可划火柴 | GEENN56JW9QU8MJS | 随处可划火柴（strike anywhere）及含此类火柴的套装禁售 [SRC-US-AMZ-GEENN56JW9QU8MJS] | 需专用擦火面的安全火柴 | R:US-L1-MATCH-001 |
| 监控设备 | G200164870 | 窃听/监听设备、伪装成非录音物品的录音或音视频设备、偷拍用于性目的的设备、通信入侵设备禁售 [SRC-US-AMZ-G200164870] | 不录音的纯视频隐藏摄像头；婴儿监视器；摄像机；答录机；夜视配件 | R:US-L1-SURV-001 |
| TSCA 限制化学品 | GNPGY2ZEUMKSA62F | TSCA 限制化学品产品禁售（二氯甲烷、温石棉、三氯乙烯、PBT 物质、含四氯乙烯的手工胶和不锈钢抛光剂）；含四氯乙烯（PCE）的消费品自 2027-03-08 起禁售 [SRC-US-AMZ-GNPGY2ZEUMKSA62F] [SRC-US-AMZ-G200164570] | 不含 MC/温石棉/TCE/PCE/受管制 PBT 的同类产品 | R:US-L1-TSCA-001<br>R:US-L1-TSCA-002 |
| 烟草及相关产品 | G200164910 | 烟草制品及宣称产生类尼古丁效果的产品禁售；电子烟、雾化器及全部配件禁售（无论是否含尼古丁）；未经 FDA 批准的戒烟产品禁售（尼古丁吸入器/鼻喷剂、Tabex 等）；带卷烟/无烟烟草品牌或标志的推广周边禁售 [SRC-US-AMZ-G200164910] | FDA 批准的 OTC 尼古丁口香糖/含片/贴片；无烟草品牌标识的烟灰缸、雪茄剪、水烟壶、保湿盒、打火机、烟斗；卷烟纸（AZ/AR/MD/MO/RI 禁售） | R:US-L1-TOBACCO-001<br>R:US-L1-TOBACCO-002<br>R:US-L1-TOBACCO-003<br>R:US-L1-TOBACCO-004 |
| 保修、服务方案、合约和担保 | G200164930 | 单独销售延保、服务计划、保证类商品禁售（未获预先批准） [SRC-US-AMZ-G200164930] [SRC-US-AMZ-GQHQGBTD7XB7EECN] [SRC-US-AMZ-G201613540] | 亚马逊预批准卖家（目前不接受新申请） | R:US-L1-WARRANTY-001 |
| 婴幼儿与儿童产品（专项政策中的禁售项） | GPCC6385YHNT35A9、GX44XMQX3ZKWRPZR、GKDFVJSUHPYTRHW3、GUG6JJCDN6YYQYJP、GX9BGE7LAFRWAFHF、GFEUQFB9X4YWFVXD、G202137200、G8FDB4PSHS4AACQ5、GPQBDFAYL3LCWYD2 | 加重婴幼儿睡眠产品、婴儿睡眠定位器、带误导性睡眠宣称的非睡眠产品禁售；婴儿自主喂食装置、防吐奶/喂奶枕、免手持奶瓶支架禁售；串珠牙胶夹/牙胶链（含带奶嘴的）、水晶梦（crystal dream）安抚奶嘴禁售；水晶珠/吸水珠（彩色或面向儿童/玩乐用途）禁售；布质（无硬框架）儿童汽车约束装置禁售；2T–12 码带帽绳/领口抽绳的儿童外穿上衣禁售；美人鱼尾泳衣（含一体蹼、泳装套装）禁售 [SRC-US-AMZ-GKDFVJSUHPYTRHW3] [SRC-US-AMZ-GPCC6385YHNT35A9] [SRC-US-AMZ-GX44XMQX3ZKWRPZR] [SRC-US-AMZ-GRLKLZ6WQ9R259LC] | 经检测符合 16 CFR / ASTM 标准的婴儿睡眠、坐卧、出行、喂养、牙胶、安全座椅等产品可售（资料要求见 C 节） | R:US-L1-SLEEP-001<br>R:US-L1-INFANT-005<br>R:US-L1-INFANT-007<br>R:US-L1-WATERBEAD-001<br>R:US-L1-CARSEAT-001<br>R:US-L1-CHILD-001<br>R:US-L1-CHILD-004 |
| 漱口水 | GPWPSA5MVZQLLLKR | 带泵头的漱口水/抗菌漱口液以及含酒精（乙醇）的漱口水禁售 [SRC-US-AMZ-GPWPSA5MVZQLLLKR] | 非泵头、符合 PPPA 儿童防护包装要求的漱口水 | R:US-L1-MOUTHWASH-001 |
| 风筝线 | GC277GB53473J65C | 磨砂（涂玻璃粉）风筝线禁售（manja） [SRC-US-AMZ-GC277GB53473J65C] [SRC-US-AMZ-GRLKLZ6WQ9R259LC] [SRC-US-AMZ-GKJRA3FRPRKVBJJS] | 非磨砂（无玻璃粉/金属涂层）的普通风筝线 | R:US-L1-KITE-001 |
| 日食观测产品 | G202171660 | 日食望远镜/双筒镜、日食相机镜头及用于望远镜/双筒镜/相机镜头的太阳滤镜禁售 [SRC-US-AMZ-G202171660] [SRC-US-AMZ-GRLKLZ6WQ9R259LC] | 符合 ISO 12312-2 的日食眼镜和手持观测卡 | R:US-L1-ECLIPSE-001 |
| 眼科药品 | G6VSU6Q86RKZKEZW | 顺势疗法眼科产品（滴眼液、眼膏等）禁售 [SRC-US-AMZ-G6VSU6Q86RKZKEZW] | 非顺势疗法、提交保险并经 TIC 验证的眼药 | R:US-L1-OPHTH-002 |
| 产品安全上架限制表中的化学品 | GRLKLZ6WQ9R259LC | 甲醛水箱处理剂、含 NMP 的脱漆产品、亚硝酸钠、硝酸钠、三氯乙酸禁售（产品安全禁售清单） [SRC-US-AMZ-GRLKLZ6WQ9R259LC] [SRC-US-AMZ-GW6HK2RDRNNFW2ML] | 食品页允许浓度 ≤10% 的亚硝酸钠（与限制表口径冲突，见待核实） | R:US-L1-SAFECHEM-001 |
| 电动出行设备 | GMUW6CKYLY4AP8MK | 电机功率 >750W 或纯电驱动时速 >20 mph（32 km/h）的电动自行车/三轮车禁售 [SRC-US-AMZ-GMUW6CKYLY4AP8MK] | 电机 ≤750W 且纯电驱动时速 ≤20 mph、提交保险并经 TIC 验证的电动自行车/滑板车等 | R:US-L1-EMOB-001 |
| 电池加热服装和鞋垫 | GFQMECECLTJCUE3H、GRLKLZ6WQ9R259LC | 锂电池位于承重位置的加热鞋垫/加热服装禁售 [SRC-US-AMZ-GFQMECECLTJCUE3H] [SRC-US-AMZ-GRLKLZ6WQ9R259LC] | 电池不在承重位置、具备检测报告的加热服装（专页口径；与限制表笼统禁售冲突） | R:US-L1-HEATWEAR-001 |
| 吹风机 | GW5CVACPVTQNTWHX | 未配备一体式防浸水保护插头的吹风机禁售 [SRC-US-AMZ-GW5CVACPVTQNTWHX] | 插头带一体式防浸水保护装置并有检测报告的吹风机 | R:US-L1-HAIRDRY-001 |
| 凝胶/液体燃料火盆壁炉 | G5P5YMQXX9Y34NVU | 凝胶燃料和液体燃料火盆、壁炉（含酒精壁炉）全球禁售 [SRC-US-AMZ-G5P5YMQXX9Y34NVU] [SRC-US-AMZ-GRLKLZ6WQ9R259LC] | 无（全部禁售） | R:US-L1-FIREPIT-001 |
| 小房子与预制结构 | GUJFA3KVVEHVKKYE | 供人居住的小房子、预制房屋、集装箱房、模块化住宅及住房用 DIY 图纸禁售 [SRC-US-AMZ-GUJFA3KVVEHVKKYE] [SRC-US-AMZ-GRLKLZ6WQ9R259LC] | 仅作储物且不宣传可居住的花园棚屋 | R:US-L1-TINYHOME-001 |
| 成人用品 | G200339940 | 露骨性图像（含打码/模糊）、未成年人性化、未授权色情图像、兽交/动物造型性玩具、带头部或儿童特征的性爱娃娃禁售 [SRC-US-AMZ-G200339940] [SRC-US-AMZ-G200164670] | 无露骨图文、临床化描述、归入 Sexual Wellness 并标成人的两性用品（见 US-L2-ADULT-002） | R:US-L1-ADULT-001 |
| 贸易管制（受制裁地区原产/进口商品） | G201575280 | 自古巴、伊朗、朝鲜、克里米亚、“顿涅茨克/卢甘斯克人民共和国”地区进口或原产的商品禁售 [SRC-US-AMZ-G201575280] | 非受制裁国家/地区原产且不涉及拒绝交易方的商品 | R:US-L1-TRADE-001 |

### B. 审核与限售（L2）

#### B.1 审核的类型和申请路径
[SRC-US-AMZ-G200333160] [R:US-L2-APPROVAL-001]
- **查状态**：卖家平台 > 目录 > 添加商品 > 搜索商品，看提示：“不可用”（不能上架）、“销售此商品”（无需审核）、“申请销售”（需审核）；点“显示限制条件”看具体要求。
- **限制的层级**：单个 ASIN、品牌、品牌+类目、类目、子类目；同一商品可能需要多项批准。
- **常备材料**：180 天内的采购发票、商品各面清晰照片、品牌授权书（如适用）、安全认证（需要时）、商业责任险文件（特定类目）。审核一般 2–7 个工作日；出现 “Your account does not qualify” 表示不能卖且不能申诉。
- **会失去资格的情形**：类目新增限制、账户收到绩效通知、合规要求变化、保险过期或失效。

#### B.2 需预先批准的类目和商品
[SRC-US-AMZ-G200333160] 及各类目申请页

| 类目 | 当前状态 / 硬性条件 | 规则ID |
| --- | --- | --- |
| 高级珠宝（Fine Jewelry） | 专业销售计划；订单缺陷率 ≤1%、发货前取消率 ≤2.5%、迟发率 ≤4%；只卖全新正品、单价 ≤30 万美元；符合 FTC 珠宝指南（标 silver/sterling 须含银 ≥92.5%、仿制宝石注明 simulated、披露处理）；除主要珠宝品牌外不得跟卖他人 ASIN [SRC-US-AMZ-G200332590] | R:US-L2-APPROVAL-002 |
| 手表 | 同上表现指标；须用制造商 UPC，并说明有无制造商保修 [SRC-US-AMZ-G200316090] | R:US-L2-APPROVAL-002 |
| 收藏硬币、娱乐收藏品、体育收藏品、美术品、邮票 | **目前不接受新卖家申请**；现有卖家须持续满足评级/认证机构等条件（如 ≥1,900 美元硬币须 PCGS/NGC 评级，签名品须 PSA/DNA、JSA、Beckett 等认证）[SRC-US-AMZ-G201526800] [SRC-US-AMZ-G200944120] [SRC-US-AMZ-G200800780] [SRC-US-AMZ-G201257400] [SRC-US-AMZ-GWHRWJTHCX9MQU46] | R:US-L2-APPROVAL-003、R:US-L2-ART-001、R:US-L2-CURRENCY-004、R:US-L2-POSTAGE-002 |
| 服务 | 须背景审查和美国执照；与保修页“不接受申请”的说法冲突（见待核实）[SRC-US-AMZ-G201613540] | R:US-L2-APPROVAL-003、R:US-L1-WARRANTY-001 |
| 服装与配饰 | 提供品牌和数量、该类目预计年营收、公司联系方式和简介；获批后遵守服装风格指南 [SRC-US-AMZ-G200316920] | R:US-L2-APPROVAL-004 |
| 视频、DVD 与蓝光 | 订单缺陷率 ≤1%、取消率 ≤2.5%、迟发率 ≤4%；至少 3 张来自最大货源的发票/采购单 [SRC-US-AMZ-G201607580] | R:US-L2-APPROVAL-004 |
| 音乐与 DVD | 至少 1 张最大货源发票；不接受形式发票；伪造文件直接取消销售权限 [SRC-US-AMZ-G202188990] | R:US-L2-APPROVAL-004 |
| 流媒体播放器 | 逐型号申请：寄送样机（不退还、运费自付），提交系统版本、预装应用和全部 APK 清单、软件来源 [SRC-US-AMZ-G202183590] | R:US-L2-APPROVAL-005 |
| 视频游戏捆绑套装 | 须预先批准 [SRC-US-AMZ-G200685320] | R:US-L2-OTHER-007 |
| Made in Italy | 属于徽章/展示项目，不是准入限制，未单独写规则 [SRC-US-AMZ-G201852310] | — |

**账户级商业责任险** [SRC-US-AMZ-G200386300] [R:US-L2-INSURANCE-001] [R:US-L2-INSURANCE-002]：在 Amazon.com 单月销售额超过 1 万美元后 30 天内（或亚马逊要求时）须投保商业综合/超额/伞式责任险：事故发生制、每次事故及累计 ≥100 万美元、免赔额 ≤1 万美元并写在 COI 上、覆盖在美国站上架的全部商品、附加被保险人为 "Amazon.com Services LLC and its affiliates and assignees"、无日落条款、被保险人名称与账户法人名一致、保险公司 S&P/AM Best A- 及以上并具备全球理赔能力、取消/修改/不续保须提前 30 天通知亚马逊。**2026-11-02 起**：销售强化安全类目商品的卖家不论销售额都须投保；**注册地在中国大陆的卖家须通过亚马逊保险加速器（AIA）投保**，除非亚马逊书面同意。

#### B.3 强化安全上架要求类目（保险 ≥100 万美元 + TIC 验证）
[SRC-US-AMZ-G4RUG6EAT2ZLVSRT] [SRC-US-AMZ-GUQ848NB5HZ6M6A4] [R:US-L2-ENHANCED-001] [R:US-L2-ENHANCED-002]

| 类目组 | 包含的商品 |
| --- | --- |
| 儿童产品 | 儿童安全座椅/增高座椅/旅行系统；儿童玩具；婴儿支撑垫和哺乳枕；婴幼儿睡眠产品；游戏围栏；儿童便携床护栏 |
| 可食用及可摄入产品 | 膳食补充剂；口服 OTC 药品；眼科药品 |
| 消防相关产品 | 灭火器；烟雾和一氧化碳报警器 |
| 一般家用设备 | 浸入式热水器（热得快）；小型厨房电器（台面或灶上使用的电动/非电动烹饪加热设备） |
| 家用医疗器械 | 医疗移动和转移设备；家用呼吸护理用品；助行器和带轮助行器 |
| 锂电池产品 | 电动出行配件；电动出行设备；锂电池；锂电家用电器；锂电智能家居和消费电子；便携电源 |
| 户外动力与取暖设备 | 电动切割工具；燃气户外取暖产品；便携发电机；高压清洗机 |
| 个人安全装备 | 攀岩安全带；攀岩绳；防坠落安全带；登山扣；登山头盔；安全头盔（骑行、轮滑、运动、建筑等） |
| 睡眠产品 | 成人便携床护栏；床垫 |
| 交通相关产品 | 汽车和摩托车轮胎 |
| 水上与海上安全产品 | 穿戴式或充气漂浮产品；泳池安全和准入控制产品（报警器、围栏、泳池盖、门） |

要求：
1. **产品责任险**：不论月销售额多少，都须持有并维持每次事故及累计 ≥100 万美元、事故发生制（occurrence basis）、附加被保险人写 "Amazon.com Services LLC and its affiliates and assignees" 的保单；在“设置 > 商业保险验证”提交 COI，审核通过才开通销售 [SRC-US-AMZ-G200333160]。
2. **第三方检测**：所有被通知的 ASIN 由亚马逊授权 TIC 服务商验证并代为提交文件；用非授权实验室的结果须经授权 TIC 复核。
3. **持续抽检**：可能随时被随机抽检；严重安全问题亚马逊须报告监管机构，卖家可能须召回。
4. **会被下架的情形**：验证或抽检不合格需改设计；确认与安全事故/财产损失有关；保险失效或不达标；品牌授权被撤销或过期；无法确认合法供应链（如只在亚马逊销售的品牌）。

#### B.4 其他需审核、限定卖家或地域限制的情形
- **农药**：仅限美国居民；须通过卖家大学农药课程（≥80 分）并签署保证书；每个产品提供 EPA 注册号 [R:US-L2-PEST-008]。
- **激光**：<5 mW 的 3B/4 级须邮件 electronics-safety@amazon.com 预批准 [R:US-L2-LASER-002]；Fine Art、收藏硬币、视频游戏捆绑、酒类、活体/鲜切圣诞树及绿植均须预批准 [R:US-L2-ART-001] [R:US-L2-CURRENCY-004] [R:US-L2-OTHER-007] [R:US-L2-ALCOHOL-002] [R:US-L2-PLANT-003]。
- **处方/专业用医疗器械**：仅限受邀的 Professional Healthcare 项目，且不可 FBA [R:US-L2-MED-003]；Ascensia/OneTouch 血糖试纸、COVID-19 检测试剂仅限授权卖家 [R:US-L2-MED-004]。
- **限定品牌**：驱蚊手环/贴只允许 23 个批准品牌 [R:US-L1-PEST-004]；罂粟籽只允许 11 个批准品牌且 ≤1 磅 [R:US-L1-FOOD-006]。
- **亚马逊自动地域限制（卖家无需操作）**：烟草相关商品（AZ、CA、VT）、卷烟纸（AZ、AR、MD、MO、RI）[R:US-L2-TOBACCO-006]；化妆品州法（CA、HI、MD、NY、WA 及 10 个 PFAS 州）[R:US-L2-COSM-012]；BB/软弹/彩弹枪、伞刀、助力刀、防狼喷雾、电击器、弓弩、弹弓、手铐 [R:US-L2-WEAPON-013] [R:US-L2-WEAPON-015] [R:US-L2-WEAPON-016]；加州皮草/鹅肝/特定动物制品 [R:US-L2-ANIMAL-010]；华盛顿州 EPS 泡沫制品 [R:US-L2-EPS-001]；豁免制冷剂和含制冷剂电器 [R:US-L2-REFRIG-002]；EPA 认证油罐 [R:US-L1-AUTO-009]。


#### B.5 L2 规则一览

| 主题 | 要求（做什么、谁出具） | 申请/提交路径 | 严重度 | 规则ID |
| --- | --- | --- | --- | --- |
| 强化安全上架要求类目：须提交 ≥100 万美元产品责任险（COI）才能开通销售 [SRC-US-AMZ-G4RUG6EAT2ZLVSRT] [SRC-US-AMZ-GUQ848NB5HZ6M6A4] [SRC-US-AMZ-G200333160] [SRC-US-AMZ-G200386300] | 产品责任险保险证明（COI）：每次事故及累计 ≥100 万美元、事故发生制、附加被保险人为 Amazon.com Services LLC and its affiliates and assignees（保险公司） | 卖家平台 > 设置 > 商业保险验证（Business Insurance verification） | approval_required | R:US-L2-ENHANCED-001 |
| 强化安全上架要求类目：所有被通知 ASIN 须经亚马逊授权 TIC 机构验证并接受随机抽检 [SRC-US-AMZ-G4RUG6EAT2ZLVSRT] [SRC-US-AMZ-GUQ848NB5HZ6M6A4] [SRC-US-AMZ-GUTZ2R2DD6P2UMVB] | 授权 TIC 服务商的 Direct product validation（新检测或复核既有报告）（亚马逊授权 TIC 服务商） | 卖家平台 > 账户状况 > 第三方检测、检验与认证服务（TIC） | approval_required | R:US-L2-ENHANCED-002 |
| 需预先批准的类目和商品（收藏邮票、收藏硬币、娱乐/体育收藏品、美术品、珠宝、意大利制造、音乐与 DVD、服装配饰、服务、流媒体播放器、视频/DVD/蓝光、手表） [SRC-US-AMZ-G200333160] | 类目/品牌/ASIN 销售申请 | 卖家平台 > 目录 > 添加商品 > 搜索商品 > 显示限制 > 申请销售；在“销售申请”页面跟踪 | approval_required | R:US-L2-APPROVAL-001 |
| 商品捆绑须为原制造商或品牌包装的组合（2026-09-30 起扩展至大多数类目） [SRC-US-AMZ-GQHQGBTD7XB7EECN] | 捆绑须为品牌/制造商原装组合，或提供品牌授权书 | 卖家平台 > 账户状况 > 商品信息政策违规 | compliance_required | R:US-L2-BUNDLE-001 |
| 酒类及 0–0.5% ABV 无醇饮料仅限预先批准的卖家；酒具、纪念品、非酒精蒸馏器可售 [SRC-US-AMZ-G200164340] [SRC-US-AMZ-G200333160] | 酒类销售预先批准（需联邦 TTB 及州酒类许可）（亚马逊；美国酒精烟草税务贸易局（TTB）/ 州酒类管理部门） | — | approval_required | R:US-L2-ALCOHOL-002 |
| 仿动物制品和不受限动物制品可售，但须写明非真品 [SRC-US-AMZ-G200164370] | 标题和描述明确标注 "faux"/"artificial"/"imitation"，说明不是真品 | — | compliance_required | R:US-L2-ANIMAL-009 |
| 加州配送限制：皮草制品、鹅肝、蟒/眼镜蛇/袋鼠等制品不得发往加州 [SRC-US-AMZ-G200164370] | 上述产品不得配送至加州地址（设置配送限制） | — | compliance_required | R:US-L2-ANIMAL-010 |
| 处方宠物药须由持证宠物药房销售；兽医处方粮须在兽医指导下销售 [SRC-US-AMZ-G200164370] | 持证宠物药房资质（处方宠物药）（州药房委员会）；按亚马逊兽医处方粮常见问题要求上架 | — | approval_required | R:US-L2-ANIMAL-011 |
| 活体昆虫/蠕虫（饵料、饲料）及活体贝类可售但有地域限制 [SRC-US-AMZ-G200164370] | 遵守配送地域限制，必要时持 USDA-APHIS PPQ 许可 | — | compliance_required | R:US-L2-ANIMAL-012 |
| 美术品（Fine Art）类目须预先获亚马逊批准，并只接受符合条件的原作和限量版 [SRC-US-AMZ-G201279060] [SRC-US-AMZ-G200333160] [SRC-US-AMZ-G201257400] | Fine Art 类目销售申请（Categories and Products Requiring Approval > Fine Art）；真品/来源证明：签名编号或真品证书（COA）；二次销售作品须有购买凭证或所有权证明并提供给买家，详情页注明流转记录（provenance） | 卖家平台 > 目录 > 添加商品 > 显示限制 > 申请销售 | approval_required | R:US-L2-ART-001 |
| 不符合 Fine Art 类目条件的艺术品不得在 Fine Art 类目上架 [SRC-US-AMZ-G201279060] | 上述作品不得进入 Fine Art 类目（可视情况改在家居装饰等类目合规上架） | — | prohibited | R:US-L2-ART-002 |
| 家居装饰艺术品：复制品须标注 "reproduction"，真品须能证明真实性 [SRC-US-AMZ-G200164390] | 复制品在标题和描述中注明 "reproduction"；披露状况与修复情况；真品真实性证明（按要求提供） | — | compliance_required | R:US-L2-ART-004 |
| 排放相关售后零件须保留排放控制功能；性能调校器须持 CARB EO [SRC-US-AMZ-G200164410] [SRC-US-AMZ-G202082160] | CARB Executive Order（EO）编号（性能调校器/影响排放的改装件）（加州空气资源委员会（CARB）） | 在 Listing 合规属性中填写 CARB EO 编号（见 CARB 帮助页 G202082160） | compliance_required | R:US-L2-AUTO-010 |
| 汽配州级销售限制：刹车片铜含量、含铅平衡块、加州 CARB、铅酸电池、催化转换器 [SRC-US-AMZ-G200164410] | 刹车片铜含量合规标识（如 LeafMark/N 级标识）；催化转换器、改装件、油罐的 CARB 认证（销往加州/CO/ME/NY）；遵守加州铅酸电池回收法（2016）等州规定 | — | compliance_required | R:US-L2-AUTO-011 |
| 汽车蓄电池、经 EPA 认证的便携油罐、车用配件（脚垫、雨刮）属于允许销售示例 [SRC-US-AMZ-G200164410] | 确认产品符合 FMVSS 和清洁空气法等适用法规 | — | info | R:US-L2-AUTO-012 |
| 化妆品宣称限制：不得用 FDA 标志、不得称 FDA 批准、不得做疾病治疗或未经验证的宣称 [SRC-US-AMZ-G200164470] [SRC-US-AMZ-G202024200] | 文案和图片不含 FDA 标志、FDA 批准、疾病治疗和未经验证的宣称 | — | compliance_required | R:US-L2-COSM-010 |
| 兼属化妆品和药品的产品（去屑洗发水、含防晒成分的护肤品、止汗剂）须同时符合药品要求 [SRC-US-AMZ-G200164470] [SRC-US-AMZ-G200164490] | Drug Facts 标签（有效成分、用途、警示、用法、非活性成分）；FDA 药品企业注册与 NDC 列名（美国 FDA） | — | compliance_required | R:US-L2-COSM-011 |
| 化妆品州级限制（加州、夏威夷、马里兰、纽约、华盛顿、PFAS 州）由亚马逊自动限售 [SRC-US-AMZ-G200164470] | 关注配方是否含州法限制成分（PFAS、1,4-二噁烷、甲醛释放体、羟苯甲酮/甲氧基肉桂酸辛酯等） | — | info | R:US-L2-COSM-012 |
| 道具/仿真钞须永久标注 "COPY" 并满足尺寸要求 [SRC-US-AMZ-G200164450] | 永久醒目标注 "COPY"；彩色单面；尺寸 <75% 或 >150% 真钞 | — | compliance_required | R:US-L2-CURRENCY-003 |
| 收藏硬币类目须预先批准；货币化金银币、复制币须满足信息与标记要求 [SRC-US-AMZ-G200164450] [SRC-US-AMZ-G200333160] [SRC-US-AMZ-G201526800] | 收藏硬币类目申请；复制币实物标注 "COPY"，标题和描述写明 reproduction/replica/copy；反洗钱（AML）计划（贵金属/宝石交易商，31 CFR 1027，按需提供） | 卖家平台 > 目录 > 添加商品 > 申请销售（Collectible Coins） | approval_required | R:US-L2-CURRENCY-004 |
| 膳食补充剂属强化合规类目：须验证商业保险并经授权 TIC 机构验证全部被通知 ASIN [SRC-US-AMZ-G201829010] [SRC-US-AMZ-G4RUG6EAT2ZLVSRT] [SRC-US-AMZ-GUTZ2R2DD6P2UMVB] | 商业保险证明（COI）——卖家平台商业保险验证（Business Insurance verification）；授权 TIC 服务商的 Direct product validation 验证 | 卖家平台 > 设置 > 商业保险（Business Insurance）；卖家平台 > 账户状况 > 第三方检测、检验与认证服务（TIC） | approval_required | R:US-L2-SUPP-007 |
| 膳食补充剂宣称限制（疾病宣称、药品替代、合法类固醇、虚标提取物含量、非转基因宣称须有证明） [SRC-US-AMZ-G201829010] [SRC-US-AMZ-G202024200] | 文案不得有疾病、药品替代、类固醇、虚标含量宣称；Non-GMO 宣称证明（Non-GMO Project Verified / Nutrasource IGEN / PCR 报告 / USDA Organic） | — | compliance_required | R:US-L2-SUPP-011 |
| 口服 OTC 药品属高级合规类目：须保险验证并经授权 TIC 验证检测报告和 cGMP [SRC-US-AMZ-G200164490] [SRC-US-AMZ-G4RUG6EAT2ZLVSRT] [SRC-US-AMZ-GUTZ2R2DD6P2UMVB] [SRC-US-AMZ-GWZVJXQCVTCKA5F6] | 商业保险证明（COI）——卖家平台商业保险验证；ISO 17025 实验室检测报告（API、重金属 USP<232>、EG/DEG、微生物 USP<61>/<62>、溶出度）（ISO/IEC 17025 认可实验室）；cGMP 证书（21 CFR 210/211 或 NSF/ANSI 455-4），ISO 17065 认证机构签发；产品和包装上永久标示 NDC 号；符合 PPPA 儿童防护包装和 21 CFR 351 | 亚马逊授权 TIC 服务商代为提交；卖家平台 > 设置 > 商业保险 | approval_required | R:US-L2-DRUG-011 |
| 药品宣称限制：OTC 专论药不得称 FDA 批准、不得超出批准标签宣称 [SRC-US-AMZ-G200164490] [SRC-US-AMZ-G202024200] | 文案宣称不得超出批准标签；不得使用 FDA 标志 | — | compliance_required | R:US-L2-DRUG-012 |
| 锂电池（单独销售的锂离子/锂聚合物/磷酸铁锂及替换电池）属强化安全类目：须保险验证并经授权 TIC 验证 [SRC-US-AMZ-G7PAP6BJAUXRM4LH] [SRC-US-AMZ-G4RUG6EAT2ZLVSRT] [SRC-US-AMZ-GUTZ2R2DD6P2UMVB] | 商业保险证明（COI）；亚马逊授权 TIC 服务商验证（Direct product validation） | 卖家平台 > 设置 > 商业保险；卖家平台 > 账户状况 > 第三方检测、检验与认证服务 | approval_required | R:US-L2-BATT-002 |
| 软弹枪、BB 枪、气枪、彩弹枪、玩具枪可售但受地域限制并须有法定标识 [SRC-US-AMZ-G200164950] | 仿真/玩具枪的法定橙色枪口等标识（15 U.S.C. 5001 / 15 CFR 272）；Listing 写明空气/弹簧驱动和弹药类型；遵守州/地方对仿真枪和气枪的销售限制（亚马逊会设置地域限制） | — | compliance_required | R:US-L2-WEAPON-013 |
| 允许销售的枪械配件（握把、隐蔽枪套、激光瞄准器、瞄准镜含夜视、两脚架、复装设备等）受地域限制 [SRC-US-AMZ-G200164950] [SRC-US-AMZ-G201689020] [SRC-US-AMZ-GJS7C6DGM9BD6L4B] | 激光瞄准器须标注激光功率和等级（亦须符合激光产品政策）；遵守地域销售限制及出口管制 | — | compliance_required | R:US-L2-WEAPON-014 |
| 伞刀、助力开合刀受地域限制；猎刀、厨刀、仿制剑、砍刀、爪刀可售 [SRC-US-AMZ-G200164950] | 遵守州/地方刀具法规（亚马逊设置地域限制） | — | compliance_required | R:US-L2-WEAPON-015 |
| 吹箭、弩和弓、手铐、防狼喷雾、弹弓、电击器受地域限制；甩棍以外的防身工具（kubotan、战术笔）可售 [SRC-US-AMZ-G200164950] | 遵守州/地方对防身用品和弓弩的限制（亚马逊设置地域限制） | — | compliance_required | R:US-L2-WEAPON-016 |
| ITAR 国防物品和 EAR 两用物品须取得出口许可，否则不得销售/出口 [SRC-US-AMZ-GJS7C6DGM9BD6L4B] [SRC-US-AMZ-G200164950] | ITAR 出口许可/豁免（美国国务院 DDTC）或 EAR 出口许可（美国商务部 BIS）（美国国务院国防贸易管制局（DDTC）/ 商务部工业与安全局（BIS）） | — | compliance_required | R:US-L2-EXPORT-001 |
| 不符合加州农场动物圈养法（Prop 12）的产品（非笼养鸡蛋等）不得销往加州 [SRC-US-AMZ-G200164550] | 不得向加州配送不合规产品；有机水产须 CPF 项目与第三方有机认证 | — | compliance_required | R:US-L2-FOOD-008 |
| 食品宣称限制：不得 FDA 标志/批准、不得疾病宣称；“有机”须 USDA 有机认证并注明认证机构 [SRC-US-AMZ-G200164550] [SRC-US-AMZ-G202024200] | USDA 有机认证（宣称有机时）（USDA 认可的有机认证机构） | — | compliance_required | R:US-L2-FOOD-010 |
| 州级 PFAS、BPA 限制及加州异丙醇/VOC 溶剂限值 [SRC-US-AMZ-G200164570] [SRC-US-AMZ-GUDRMYJ7JL4PGNAB] | PFAS/BPA 检测或供应商声明（销往限制州）；加州销售的异丙醇须在容器上注明外用/医疗/食品表面消毒用途说明 | — | compliance_required | R:US-L2-HAZ-012 |
| 低于 5mW 的 3B/4 级激光产品须预先获亚马逊批准并提交 FDA 登记和测试报告 [SRC-US-AMZ-G201689020] | 激光产品预先批准；21 CFR 1040.10/1040.11 或 IEC 60825-1 整机测试报告（12 个月内）（NRTL 或 ISO/IEC 17025 认可实验室）；FDA 激光产品报告确认（accession number）（美国 FDA 器械与放射健康中心（CDRH）） | 邮件 electronics-safety@amazon.com | approval_required | R:US-L2-LASER-002 |
| 处方（Rx）和专业用医疗器械只能通过受邀制 Professional Healthcare 项目销售，且不得 FBA [SRC-US-AMZ-G200164650] | Professional Healthcare（PHC）项目邀请与资质；医疗器械供应商许可证（州级）（各州主管机构） | — | approval_required | R:US-L2-MED-003 |
| Ascensia/OneTouch 血糖试纸和 COVID-19 检测试剂盒仅限授权卖家 [SRC-US-AMZ-G200164650] | 品牌授权/授权经销商身份确认 | — | approval_required | R:US-L2-MED-004 |
| 医疗器械宣称限制：不得使用 FDA 标志；未获批不得称 FDA approved/cleared；未获授权不得做疾病宣称 [SRC-US-AMZ-G200164650] [SRC-US-AMZ-G200164330] [SRC-US-AMZ-G202024200] | 文案和图片中的 FDA 相关宣称须与实际许可状态一致 | — | compliance_required | R:US-L2-MED-006 |
| 视频游戏捆绑套装须预先获亚马逊批准 [SRC-US-AMZ-G200685320] [SRC-US-AMZ-G200333160] | 视频游戏捆绑套装预先批准 | — | approval_required | R:US-L2-OTHER-007 |
| 农药类目须申请批准：仅限美国居民、须通过卖家大学培训（≥80 分）并签署保证书 [SRC-US-AMZ-G202115120] [SRC-US-AMZ-G200333160] | 农药销售申请 + 卖家大学农药培训（≥80%）+ 签署保证书 | 卖家平台 > 目录 > 添加商品 > 申请销售 > 请求批准 | approval_required | R:US-L2-PEST-008 |
| 普通商品的抗菌/防霉/防螨宣称会被判为农药：须删除宣称或符合“处理物品豁免” [SRC-US-AMZ-G202115120] [SRC-US-AMZ-G202024200] | 删除农药宣称，或提供处理物品豁免依据（所用抗菌剂的 EPA 注册号、宣称限于保护产品本身） | 修改 Listing 并在 Pesticide marking 属性中选择豁免类型 | compliance_required | R:US-L2-PEST-010 |
| 活体/鲜切圣诞树及圣诞绿植（花环、花饰）须获批准，仅限认证供应商 [SRC-US-AMZ-G201737480] | 圣诞树及绿植销售批准（认证供应商） | — | approval_required | R:US-L2-PLANT-003 |
| 收藏邮票须披露真伪和状态；复制邮票须标注 [SRC-US-AMZ-G200164730] [SRC-US-AMZ-GWHRWJTHCX9MQU46] | 收藏邮票信息披露；复制邮票标注 | — | compliance_required | R:US-L2-POSTAGE-002 |
| 误导性宣称：认证宣称须属实、性能/成分/产地宣称须可验证、最高级用语须有证据、环保宣称须符合 FTC 绿色指南 [SRC-US-AMZ-G202024200] | 准备宣称佐证（检测报告、证书、产地证明、比较测试数据）；环保宣称按 FTC Green Guides | — | compliance_required | R:US-L2-CLAIM-002 |
| “美国制造”(Made in USA) 宣称须符合 FTC 标准并可能需提交合规声明 [SRC-US-AMZ-G202024200] | Made in USA 合规声明（Attestation of Compliance PDF） | 卖家平台 > 账户状况（按要求提交） | compliance_required | R:US-L2-CLAIM-003 |
| 允许的豁免制冷剂（汽车空调 ≤2 lb 自封阀罐、R-744、R-728）和含制冷剂电器须标明信息并受地域限制 [SRC-US-AMZ-G5ER6LTGH2GFJLHQ] | 标明制冷剂种类、用途、容器容量、阀门类型；遵守州 HFC 法规（WA/CA/NY），接受亚马逊地域限制 | — | compliance_required | R:US-L2-REFRIG-002 |
| 仅视频不录音的隐藏摄像头、婴儿监视器、摄像机、答录机可售 [SRC-US-AMZ-G200164870] | 伪装式摄像头须无音频录制功能，Listing 不得暗示偷拍用途 | — | compliance_required | R:US-L2-SURV-002 |
| 华盛顿州禁止销售发泡聚苯乙烯（EPS）填充物、餐具、食品容器和便携冷藏箱 [SRC-US-AMZ-GEU8B9UPLKJHKU9G] | 不得向华盛顿州销售上述 EPS 产品 | — | compliance_required | R:US-L2-EPS-001 |
| 详情页不得声称 “CPSC certified/approved”（CPSC 不认证产品） [SRC-US-AMZ-GKHQEFBM7834V6AV] | 删除 “CPSC certified/approved” 等表述及 CPSC 标志图片 | — | compliance_required | R:US-L2-CPSC-005 |
| 仅兼容亚马逊设备（Echo、Kindle、Fire 等）的配件须放入 Amazon Device Accessories 类目并遵守合理使用与兼容性准则 [SRC-US-AMZ-G200500100] | 正确归类到 Amazon Device Accessories 类目；遵守亚马逊设备合理使用与兼容性准则（G200500120） | — | compliance_required | R:US-L2-DEVACC-001 |
| 眼科药品（滴眼液、眼膏等）属强化安全类目：须 COI + 授权 TIC 验证（12 个月内报告与 cGMP 证书）及 Drug Facts [SRC-US-AMZ-G6VSU6Q86RKZKEZW] [SRC-US-AMZ-G4RUG6EAT2ZLVSRT] [SRC-US-AMZ-GUTZ2R2DD6P2UMVB] | 产品责任险 COI（≥100 万美元）；21 CFR 200.50 / 21 CFR 211.132 测试报告（12 个月内）（ISO/IEC 17025 认可实验室）；cGMP 证书（21 CFR 210/211 或 NSF/ANSI 455-4）（ISO/IEC 17065 认可认证机构）；Drug Facts（21 CFR 201 Subpart C、21 CFR 349）+ 眼科警示语 | 亚马逊授权 TIC 服务商（卖家平台 > 账户状况 > TIC 服务）；卖家平台 > 设置 > 商业保险验证 | approval_required | R:US-L2-OPHTH-001 |
| 助行器和带轮助行器（rollator）属强化安全类目：须 COI + 授权 TIC 验证 ISO 11199-1/-2:2021 报告 [SRC-US-AMZ-GCJU83NDQS8JX26Q] [SRC-US-AMZ-G4RUG6EAT2ZLVSRT] [SRC-US-AMZ-GUTZ2R2DD6P2UMVB] | 产品责任险 COI（≥100 万美元）；ISO 11199-1:2021（助行架）/ ISO 11199-2:2021（带轮助行器）测试报告，12 个月内（ISO/IEC 17025 认可实验室） | 亚马逊授权 TIC 服务商；卖家平台 > 设置 > 商业保险验证 | approval_required | R:US-L2-WALKER-001 |
| 商业责任险：单月销售额超 1 万美元后 30 天内须投保（保额 ≥100 万美元、免赔额 ≤1 万美元、亚马逊为附加被保险人） [SRC-US-AMZ-G200386300] [SRC-US-AMZ-G200333160] | 商业责任险保险证明（COI），满足上述 11 项条件（评级 A- 及以上、具全球理赔能力的保险公司） | 卖家平台 > 设置 > 商业保险（Business Insurance verification） | approval_required | R:US-L2-INSURANCE-001 |
| 2026-11-02 起：中国大陆卖家须通过亚马逊保险加速器（AIA）投保；强化安全类目不论销售额均须投保 [SRC-US-AMZ-G200386300] | 经 AIA 渠道取得的商业责任险保单及 COI（中国大陆卖家）（Amazon Insurance Accelerator 合作保险公司） | 卖家平台 > 设置 > 商业保险 | approval_required | R:US-L2-INSURANCE-002 |
| 高级珠宝（Fine Jewelry）和手表类目须申请批准：专业卖家、ODR ≤1%、取消率 ≤2.5%、迟发率 ≤4%、全新正品 [SRC-US-AMZ-G200332590] [SRC-US-AMZ-G200316090] [SRC-US-AMZ-G201707070] | 高级珠宝/手表类目销售申请（Request approval）；按 FTC 珠宝指南如实标注金属成色、仿制宝石和处理方式；手表注明是否有制造商保修 | 卖家平台 > 目录 > 添加商品 > 申请销售 | approval_required | R:US-L2-APPROVAL-002 |
| 收藏硬币、娱乐收藏品、体育收藏品、美术品、邮票目前不接受新卖家申请；服务类须背景审查与美国执照 [SRC-US-AMZ-G201526800] [SRC-US-AMZ-G200944120] [SRC-US-AMZ-G200800780] [SRC-US-AMZ-G201257400] [SRC-US-AMZ-GWHRWJTHCX9MQU46] [SRC-US-AMZ-G201613540] | 类目批准（当前暂停新申请）；现有卖家维持绩效与认证要求；第三方认证/评级或可验证的真品证书（COA/LOA）（PSA/DNA、JSA、Beckett、CGC、NGC、PCGS 等） | 卖家平台 > 添加商品 > 申请销售（如重新开放） | approval_required | R:US-L2-APPROVAL-003 |
| 服装配饰、音乐与 DVD、视频/DVD/蓝光类目须申请：提交货源、预计销量和经核实的采购发票 [SRC-US-AMZ-G200316920] [SRC-US-AMZ-G202188990] [SRC-US-AMZ-G201607580] | 类目/商品销售申请（Listing limitations apply > Request approval） | 卖家平台 > 目录 > 添加商品 > 搜索商品 > Listing limitations apply > 申请 | approval_required | R:US-L2-APPROVAL-004 |
| 流媒体播放器须逐型号申请：寄送样机并提交系统、预装应用及 APK 清单 [SRC-US-AMZ-G202183590] [SRC-US-AMZ-G200164510] | 流媒体播放器类目申请（含申请表）；样机（每个型号）+ 软硬件与 APK 清单 | 卖家平台 > 添加商品 > Listing limitations apply > Request approval，上传申请表 | approval_required | R:US-L2-APPROVAL-005 |
| 成人/两性用品须归入 Sexual Wellness 并做成人分类；仅限全新、临床化描述、不得露骨图文、须标有效期 [SRC-US-AMZ-G200339940] | 正确类目与 Adult 分类；临床化文案；无露骨图片；标示有效期 | 创建/编辑 Listing 时选择 Sexual Wellness 类目节点 | compliance_required | R:US-L2-ADULT-002 |
| 误导宣称的分类处理：性能/认证/等级/成分/纯度宣称须提交 ISO 实验室报告或证书，否则删除；绝对化宣称必须删除 [SRC-US-AMZ-GZ93G4JTAEVEJW62] [SRC-US-AMZ-G201707070] [SRC-US-AMZ-G200832300] | 宣称佐证：ISO 17025 实验室报告或有效认证证书（与型号一致） | 卖家平台 > 账户状况 > 申诉/提交合规信息；或删除宣称后提交前后截图申诉 | compliance_required | R:US-L2-CLAIM-004 |
| 投影仪亮度宣称只能用 ANSI 流明/ISO 21118 流明，并须提交白光（ISO/IEC 21118）和彩色亮度（IDMS 15.4）报告 [SRC-US-AMZ-GLWWB4Z3M566RGLM] | ISO/IEC 21118:2020 白光亮度报告（ISO 17025 第三方实验室）+ IDMS 15.4 彩色亮度报告（VESA 授权测试中心） | 卖家平台 > 账户状况 > 提交合规信息或申诉 | compliance_required | R:US-L2-CLAIM-006 |
| 空气净化器/滤网的 HEPA 宣称须按 IEST-RP-CC001.7 或 UL 586 在最大风量下检测；冰箱替换滤芯须 NSF/ANSI 42/53/401 认证 [SRC-US-AMZ-G92A8N8UP4W8C4JQ] [SRC-US-AMZ-G201707070] | IEST-RP-CC001.7 / UL 586 HEPA 测试报告 + 最大风量文件（说明书/规格书或 AHAM CADR）（ISO/IEC 17025 认可实验室）；冰箱滤芯 NSF/ANSI 42（及 53/401）认证（NSF、WQA、IAPMO 等 ANSI 认可机构） | 卖家平台 > 账户状况 > 提交合规信息或申诉 | compliance_required | R:US-L2-CLAIM-007 |
| 电视天线不得宣称 ≥85 英里接收距离；放大镜/口袋望远镜放大倍数和床品织数宣称须有 ISO 17025 报告 [SRC-US-AMZ-G9RST2AGVGCW6ZCT] [SRC-US-AMZ-GDQ28DB2X4NV6872] [SRC-US-AMZ-GK652STVCYSPCRUQ] | 放大倍数报告（ANSI Z80.9/ISO 15253 或 ISO 14133）；织数报告（ASTM D3775 + AATCC 20A/ASTM D629）（ISO/IEC 17025 认可实验室） | 放大倍数经授权 TIC 或直接提交；织数直接提交亚马逊 | compliance_required | R:US-L2-CLAIM-008 |
| 加州 CARB：售后汽配、催化转换器、室内空气净化器、小型汽油发动机、便携油罐须有 CARB EO 编号，否则不得在加州销售 [SRC-US-AMZ-G202082160] [SRC-US-AMZ-G201707090] | CARB Executive Order（EO）编号；室内空气净化器 CARB 认证（加州空气资源委员会（CARB）） | 卖家平台 > 管理所有库存 > 编辑 Listing > Safety & Compliance > Product Compliance Certification | compliance_required | R:US-L2-CARB-001 |
| 加州 CAL FIRE：烟雾/一氧化碳报警器须在州消防局批准清单内，灭火器须符合加州标签认证，否则不得销往加州 [SRC-US-AMZ-GRE7PT254E4AFJFU] | 列入 CAL FIRE 批准清单（报警器）；加州州消防署长标签与认证（灭火器）（加州林业与消防局（CAL FIRE）州消防署长办公室） | 申诉邮箱 lifesafetyequipment@amazon.com | compliance_required | R:US-L2-CALFIRE-001 |
| 生鲜农产品/冷藏冷冻食品须第三方食品安全审核（经 Azzule 提交）且不可 FBA；饮料须履行各州容器押金义务 [SRC-US-AMZ-GLT9B78P9URHB6TR] [SRC-US-AMZ-GUCMGZBFXQ97P2SU] [SRC-US-AMZ-GX6ZFCE8L5J4SV2W] | 第三方食品安全审核证书（GFSI / GAP / GMP）（经认可的审核机构）；各州饮料容器押金注册与申报（各州主管机构） | Azzule SCP 门户（将 Amazon 加入客户列表） | compliance_required | R:US-L2-FOODSAFE-001 |
| FDA 批准的 OTC 戒烟产品（尼古丁口香糖/含片/贴片）可售但须符合药品法规 [SRC-US-AMZ-G200164910] | FDA 药品企业注册与药品列名（NDC）（美国 FDA）；符合 21 CFR 201 的 OTC 药品标签（Drug Facts）；儿童防护包装（16 CFR 1700） | — | compliance_required | R:US-L2-TOBACCO-005 |
| 烟草相关配件（烟灰缸、雪茄剪、水烟壶、保湿盒、烟斗、打火机）可售但有条件 [SRC-US-AMZ-G200164910] | 不得出现烟草品牌标识；不得宣称健康益处/治疗作用/纯度（除非有认证检测证据）；符合 TCA（21 U.S.C. 387）、21 CFR 1100/1140/1143、15 U.S.C. 1333 及 ATF 27 CFR 40–41 等适用要求 | — | compliance_required | R:US-L2-TOBACCO-006 |

### C. 按品类的平台合规资料（L3）

亚马逊对合规文件的通用要求 [SRC-US-AMZ-GFYECKCN9TSQ8H5B] [SRC-US-AMZ-GKHQEFBM7834V6AV] [R:US-L3-COMPLIANCE-001] [R:US-L3-CPSC-004]：

- **儿童产品**（主要供 12 岁及以下使用）：CPSC 认可实验室的检测报告 + 美国进口商或国内制造商出具的 CPC（境外实体也可以作进口商，但亚马逊不能被列为进口商或记录保存人）[R:US-L3-CPSC-001]。
- **普通消费品**：ISO/IEC 17025 认可实验室报告 + GCC；部分品类可用 NRTL 的合规证书或标志授权书（Marking Authorization Letter）代替报告。报告须含申请人和制造商全称地址、产品描述、型号（与 Listing 不一致时须申请人出具声明书 affidavit）、与 ASIN 一致的产品图片、儿童产品还须写年龄分级。
- **文件形式**：原件、不可编辑（PDF/JPEG），不得修改、不得由电脑或 AI 生成；不能来自“暂停验证实验室”；结果只能是 Pass 或 N/A。
- **提交入口**：卖家平台 > 绩效 > 账户状况 > 管理您的合规性 > 商品合规性请求（单个“提供文件/申诉”或批量模板上传）；新建 Listing 被拦截时在“管理所有库存 > 查看 Listing 限制 > 查看拦截原因”的操作面板提交 [SRC-US-AMZ-GKCHRSWHXB5WZHAU] [SRC-US-AMZ-GC35Z63FGCUCUWXX]。
- **走 TIC 的品类**：收到账户状况通知后，在“账户状况 > 政策合规 > 食品和商品安全问题 > 提交 > 验证您的商品”中创建检测请求单（TRF），选择“检测”或“验证已有文件”，把 TRF 编号交给 TIC；TRF 状态为“进行中”时 Listing 不会被停用；同一 ASIN 在多个站点只需一张 TRF [SRC-US-AMZ-GUTZ2R2DD6P2UMVB]。美国站由授权 TIC 服务的品类包括：成人床护栏、儿童首饰、儿童玩具、储物柜、膳食补充剂、可食用金属箔、电动切割工具、电动出行设备及配件、燃气户外取暖、婴幼儿睡眠产品、激光产品、锂离子电池、锂电家电、床垫、眼科药品、口服 OTC 止痛药、便携电源、高压清洗机、美白产品、烟雾/一氧化碳报警器、助行器、饮水输送产品。授权 TIC 名单含 SGS、Intertek、BV、TÜV、UL 及多家中国机构（如安博、倍测、威凯、中国质量认证中心、广州/宁波/南京海关技术中心等），以卖家平台“选择服务商”菜单为准。

下表按规则逐条列出（同一产品族可能对应多条）：


| 产品/主题 | 亚马逊要求的文件/Listing 属性 | 提交位置 | 规则ID |
| --- | --- | --- | --- |
| 合规文件通用要求：原件、非 AI 生成、语言为销售国语言、图片与详情页一致、非暂停实验室出具 [SRC-US-AMZ-GFYECKCN9TSQ8H5B] [SRC-US-AMZ-GXMGGPL6LC4CVXHT] [SRC-US-AMZ-GC35Z63FGCUCUWXX] | 按通用要求准备合规文件；提交前核对暂停实验室名单（GQG5MW4Q93L59T5K） | 卖家平台 > 账户状况 > 商品合规性请求 / 提交合规信息或申诉 | R:US-L3-COMPLIANCE-001 |
| INFORM 消费者法：高销量卖家须提交并每年认证身份、地址、银行、税号等信息 [SRC-US-AMZ-GJ4JUGLSAPRM3LU7] | 身份/地址/银行/税号核验 + 年度 INFORM 认证 | 卖家平台 > 账户状况 > INFORM 认证（按邮件/通知） | R:US-L3-INFORM-001 |
| 动物及动物制品发货标签与进口要求 [SRC-US-AMZ-G200164370] | 发货单/外箱标注发货人、收货人、来源地和内容物；野生动物制品进口须经 USFWS 指定口岸或取得 DPEP（美国鱼类及野生动物管理局（USFWS）） | 按亚马逊通知提交（账户状况 > 商品合规性请求） | R:US-L3-ANIMAL-013 |
| 人造板产品须符合 EPA TSCA Title VI 甲醛标准并逐件贴合规标签 [SRC-US-AMZ-GKY5NBH8EHAUFQ27] | EPA TSCA Title VI / CARB Phase 2 甲醛释放认证（板材由 EPA 认可的 TPC 认证）（EPA 认可的第三方认证机构（TPC））；每件产品或其包装贴 "TSCA Title VI Compliant" 标签 | 按亚马逊通知提交（账户状况 > 商品合规性请求） | R:US-L3-COMPWOOD-002 |
| 化妆品详情页属性、图片和英文 MoCRA 标签要求 [SRC-US-AMZ-G200164470] | 英文 MoCRA 合规标签：产品名、成分表、美制净含量、产品属性声明、警示语、香料过敏原、美国不良事件联系方式；标签全部面的原始图片（不得为电脑或 AI 生成）；套装须分别提供每件产品图片；包装显示矩阵码、批号或序列号；全新原厂密封 | 卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-COSM-007 |
| 儿童化妆品须填写警示语和最低适用月龄属性 [SRC-US-AMZ-G200164470] [SRC-US-AMZ-GKJRA3FRPRKVBJJS] | 强制警示语 + 最低年龄（月）属性 | 按亚马逊通知提交（账户状况 > 商品合规性请求） | R:US-L3-COSM-008 |
| 美白/淡斑类护肤品须经亚马逊授权 TIC 机构验证（检测报告、cGMP、MoCRA 注册） [SRC-US-AMZ-G200164470] [SRC-US-AMZ-GUTZ2R2DD6P2UMVB] [SRC-US-AMZ-GC37KSM44NPNZED6] | ISO 17025 实验室 12 个月内出具的检测报告（ISO/IEC 17025 认可实验室）；cGMP 证书（ISO 22716:2007 或 NSF/ANSI 455-3、ASEAN、韩国 cGMP 等同等标准）（ISO/IEC 17065 认可认证机构）；MoCRA 设施注册与产品列名（FDA Form 5066 / 5067，可提供 Direct 数据库截图）（美国 FDA（Cosmetics Direct））；完整英文标签图片（MoCRA 标签；兼属药品的含 Drug Facts） | 通过亚马逊授权 TIC 服务商提交（Direct product validation） | R:US-L3-COSM-009 |
| 膳食补充剂须提供第三方 cGMP 认证（21 CFR 111/117 或同等） [SRC-US-AMZ-G201829010] | 第三方 cGMP 证书（21 CFR 111/117 或同等，如 NSF/ANSI 455-2、ISO 22000、FSSC 22000、BRCGS）（经认可的第三方认证机构） | 交给亚马逊授权 TIC 服务商验证后由其提交 | R:US-L3-SUPP-008 |
| 健身、关节、性功能、运动营养、体重管理类补充剂须做重金属/微生物/掺假检测（NSF/ANSI 173） [SRC-US-AMZ-G201829010] | 重金属、微生物（必要时农药）检测 + 成分含量 + 掺假物检测报告（NSF/ANSI 173-2024 或 USP）（ISO 17025 认可实验室（经授权 TIC 验证）） | 亚马逊授权 TIC 服务商 | R:US-L3-SUPP-009 |
| 膳食补充剂详情页属性和英文标签图片要求 [SRC-US-AMZ-G201829010] | 英文 Supplement Facts 标签 + 批号/序列号 + 责任方名称地址；标签全部面的原始图片（不得 AI 生成）；套装逐件提供 | 按亚马逊通知提交（账户状况 > 商品合规性请求） | R:US-L3-SUPP-010 |
| OTC 药品详情页属性、Drug Facts 图片、儿童防护和防篡改包装要求 [SRC-US-AMZ-G200164490] | 英文 Drug Facts 面板 + 产品属性声明 + 警示语；FDA 药品企业注册与 NDC 列名（21 CFR 207）（美国 FDA）；儿童防护包装（PPPA，16 CFR 1700）与防篡改包装 | 按亚马逊通知提交（账户状况 > 商品合规性请求） | R:US-L3-DRUG-010 |
| 射频设备须取得相应 FCC 设备授权（认证 FCC ID 或 SDoC + 美国责任方），宣传频段须与 FCC 批准一致 [SRC-US-AMZ-GHXJGN6T5K8HGGWW] | FCC 设备授权：Certification（FCC ID，经 TCB）或 SDoC（FCC 认可电信认证机构（TCB）/ 美国责任方）；SDoC 产品须有美国境内合规责任方（Responsible Party）；Listing 宣传的工作频段须与 FCC OET KDB 批准范围一致 | 按亚马逊通知提交（账户状况 > 商品合规性请求） | R:US-L3-RF-003 |
| 锂电池检测报告（UL 2054/62133-2 等 + UN38.3 + 测试摘要）及永久警示标签要求 [SRC-US-AMZ-G7PAP6BJAUXRM4LH] | UL 2054 / UL 62133-2 / UL 1642 / UL 1973 / UL 2271 / UL 2580 / UL 2595（按适用）测试报告，12 个月内（ISO/IEC 17025 认可实验室）；UN 38.3 测试报告 + 电池测试摘要（Test Summary），12 个月内（ISO/IEC 17025 认可实验室）；产品和包装永久警示语、合规标志、型号、责任方名称地址 | 交给亚马逊授权 TIC 服务商验证后提交 | R:US-L3-BATT-003 |
| 单独销售的纽扣/硬币电池须符合 PPPA 儿童防护包装或 ANSI C18.3M，并有警示标签 [SRC-US-AMZ-GUBLQYWAJDBADUVK] | 16 CFR 1700.15 & 1700.20 或 ANSI C18.3M 测试报告（ISO/IEC 17025 认可实验室）；一般符合性证书（GCC）或警示语图片（美国进口商或制造商）；包装和（可行时）产品上的吞食危险警示；儿童防护包装 | 卖家平台 > 账户状况 > 提交合规信息或申诉（直接交亚马逊） | R:US-L3-BATT-004 |
| 含纽扣/硬币电池的消费品须符合 Reese 法（16 CFR 1263）和 ANSI/UL 4200A [SRC-US-AMZ-GUBLQYWAJDBADUVK] | 16 CFR 1263 + ANSI/UL 4200A 测试报告（ISO/IEC 17025 认可实验室）；一般符合性证书（GCC）；若为儿童产品则为 CPC（美国进口商或制造商）；Reese 法警示标签（包装、产品、说明书） | 卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-BATT-005 |
| 食品饮料须全英文 FDA/USDA 标签、保质期 >90 天、原厂密封，并填写保质期等属性 [SRC-US-AMZ-G200164550] | 英文 FDA 食品标签（21 CFR 101）：名称、净含量、责任方、成分、过敏原、营养成分表、原产国；保质期 >90 天；详情页保质期、到期类型等属性 | 按亚马逊通知提交（账户状况 > 商品合规性请求） | R:US-L3-FOOD-009 |
| 婴儿配方奶粉须提交生产地清单、FDA 注册和 GFSI 审核证书；婴儿辅食须 GFSI 或 cGMP 证书 [SRC-US-AMZ-G200164550] | 婴儿配方合规请求模板（含生产地清单）；婴儿配方生产商 FDA 注册（美国 FDA）；GFSI 认可审核证书（配方：每个生产地）；辅食：GFSI 或 cGMP 证书（经认可的第三方认证机构） | 卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-FOOD-011 |
| 可食用金箔/银箔须经授权 TIC 验证（检测报告 + 21 CFR 117 cGMP） [SRC-US-AMZ-G200164550] [SRC-US-AMZ-GUTZ2R2DD6P2UMVB] | ISO 17025 实验室检测报告（EU 231/2012、21 CFR）；21 CFR 117 cGMP 第三方证书 | 亚马逊授权 TIC 服务商 | R:US-L3-FOOD-012 |
| 1/2/3R 级激光产品（激光笔、激光水平仪、测距仪、宠物激光、花园投影灯、条码枪、校枪器、红外照明、激光玩具）须经授权 TIC 验证 [SRC-US-AMZ-G201689020] [SRC-US-AMZ-GUTZ2R2DD6P2UMVB] [SRC-US-AMZ-G201707070] | 21 CFR 1040.10/1040.11 或 IEC 60825-1 测试报告（12 个月内）（ISO/IEC 17025 认可实验室）；FDA 激光产品报告（Product Report，取得 accession number）（美国 FDA CDRH）；激光警示标签、分级标签、责任方名称地址；详情页须写明激光危险等级和人体可及输出功率（mW） | 亚马逊授权 TIC 服务商 | R:US-L3-LASER-003 |
| 通用照明灯（GSIL/CFL/LED/OLED）须按 DOE 测试和认证，详情页须写流明和瓦数 [SRC-US-AMZ-GRTV7X82BHXYCS9L] [SRC-US-AMZ-G201997070] | DOE 合规认证（CCMS 数据库登记）（美国能源部（DOE））；10 CFR 430.23(gg) 能效测试报告；详情页列出流明（lumens）和功率（watts）；包装 FTC Lighting Facts 标签 | 卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-LIGHT-002 |
| 花洒、水龙头等管道配件/洁具须符合 DOE 和加州节水节能标准并在 DOE CCMS 登记 [SRC-US-AMZ-GFVTL7E262KFAAXC] [SRC-US-AMZ-GUDRMYJ7JL4PGNAB] | DOE CCMS 认证报告与合规声明（每个基本型号）（美国能源部（DOE））；准确标注流量（gpm）等性能；随附安装说明；加州 CEC Title 20 节水认证（销往加州的花洒/水龙头等） | 按亚马逊通知提交（账户状况 > 商品合规性请求） | R:US-L3-PLUMB-001 |
| 医疗器械须 FDA 注册列名、按分类取得 510(k)/PMA/De Novo，并有带 UDI 的英文 FDA 标签 [SRC-US-AMZ-G200164650] | FDA 企业注册与器械列名（21 CFR 807）（美国 FDA）；510(k) 许可 / PMA 批准 / De Novo 分类（按器械分类）（美国 FDA）；英文 FDA 标签（21 CFR 801）含 UDI、责任方地址、用途、批号、有效期；不得覆盖贴标 | 卖家平台 > 账户状况 > 提交合规信息或申诉（按要求） | R:US-L3-MED-005 |
| 农药/农药器械及带农药宣称商品须填写 "Pesticide marking" 属性（EPA 注册号/企业号或豁免） [SRC-US-AMZ-G202115120] | EPA 农药注册号（产品）和/或 EPA 企业号（生产场所）；必要时州农药注册（如加州 CDPR）（美国环保署（EPA）/ 州农业或农药监管部门）；FIFRA 标签（EPA Reg. No. / EPA Est. No.，或最低风险农药成分标签） | Listing 合规属性 "Pesticide marking"（Compliance ID attribute） | R:US-L3-PEST-009 |
| 植物、种子发货标签（含加州醒目标注）、加州种子销售授权及肥料州注册 [SRC-US-AMZ-G201737480] | 发货标签：发货人、收货人、产地、内容物；加州种子销售授权；肥料州注册/许可（加州食品农业部（CDFA）/ 各州肥料主管机构） | 按亚马逊通知提交（账户状况 > 商品合规性请求） | R:US-L3-PLANT-004 |
| 电子产品回收：部分州禁止电子产品填埋，须引导消费者按州规定回收 [SRC-US-AMZ-G202089380] | 核查目标州电子废弃物生产者责任要求（由 L5 规则细化） | 按亚马逊通知提交（账户状况 > 商品合规性请求） | R:US-L3-RECYCLE-001 |
| 儿童玩具（≤12 岁，毛绒玩具不论年龄、身高 ≤160cm 的扮演服饰）须经授权 TIC 验证 CPSC 认可实验室报告和 CPC [SRC-US-AMZ-GKJRA3FRPRKVBJJS] [SRC-US-AMZ-G4RUG6EAT2ZLVSRT] [SRC-US-AMZ-GSGB43AFZNDWD4U8] | CPSC 认可实验室 12 个月内报告：ASTM F963-23、CPSIA 108 邻苯、追踪标签、16 CFR 1501（<3 岁）（CPSC 认可第三方实验室）；儿童产品证书（CPC）（美国进口商或国内制造商）；产品责任险 COI（强化安全类目） | 亚马逊授权 TIC 服务商（卖家平台 > 账户状况 > TIC 服务） | R:US-L3-TOY-001 |
| 儿童玩具详情页须填型号、品牌、强制警示语、最低适用月龄；产品和包装须有永久追踪标签和警示 [SRC-US-AMZ-GKJRA3FRPRKVBJJS] [SRC-US-AMZ-G200292910] | 详情页强制警示语 + 最低年龄（月）属性；产品与包装永久追踪标签和警示 | 卖家平台 > 库存 > 管理所有库存 > 编辑 > Safety and compliance | R:US-L3-TOY-002 |
| 儿童产品证书（CPC）须包含 7 项要素，亚马逊不得列为进口商/责任方 [SRC-US-AMZ-GSGB43AFZNDWD4U8] [SRC-US-AMZ-GKHQEFBM7834V6AV] | 儿童产品证书（CPC，英文，含 7 项要素）（美国进口商或国内制造商（可为境外实体）） | 按亚马逊要求通过账户状况 > 商品合规性请求或 TIC 提交 | R:US-L3-CPSC-001 |
| 儿童产品须有永久追踪标签；耐用婴幼儿产品须附邮资已付的产品注册卡（16 CFR 1130） [SRC-US-AMZ-GN9YK5Y7TYGRGNRG] [SRC-US-AMZ-GKHQEFBM7834V6AV] | 产品和包装永久追踪标签；耐用婴幼儿产品消费者注册卡（16 CFR 1130）；16 CFR 1130 检测报告（耐用婴幼儿产品）（CPSC 认可实验室） | 卖家平台 > 账户状况 > 提交合规文件或申诉 | R:US-L3-CPSC-002 |
| 含小零件/小球/弹珠/气球的儿童玩具和游戏须在详情页设置 CPSIA 窒息警示语 [SRC-US-AMZ-G200292910] | 详情页 CPSIA 窒息警示语 + 包装警示 | 卖家平台 > 库存 > 编辑 Listing > Safety and compliance > Mandatory cautionary statement | R:US-L3-CPSC-003 |
| CPSC 管辖的普通（非儿童）产品须备 GCC 和 ISO 17025 实验室报告；PPPA 产品须儿童防护包装检测 [SRC-US-AMZ-GKHQEFBM7834V6AV] | 一般符合性证书（GCC）/ 儿童产品证书（CPC）（美国进口商或国内制造商）；ISO/IEC 17025 认可实验室报告（儿童产品为 CPSC 认可实验室）；PPPA 产品按 16 CFR 1700 | 卖家平台 > 绩效 > 账户状况 > 管理您的合规性 > 商品合规性请求（单个或批量模板上传） | R:US-L3-CPSC-004 |
| 婴幼儿睡眠产品（摇篮/睡篮、床边床、婴儿床、游戏围栏、幼儿床、婴儿床垫等）须按各自 16 CFR/ASTM 标准检测，属强化安全类目（保险 + TIC 实测） [SRC-US-AMZ-GPCC6385YHNT35A9] [SRC-US-AMZ-GVRVVLWW9T3TWXGD] [SRC-US-AMZ-G424NXBNPK995GST] [SRC-US-AMZ-GVACXTSVATE36M4M] [SRC-US-AMZ-G6DYF8YUYEV5H6AY] [SRC-US-AMZ-G4RUG6EAT2ZLVSRT] | CPSC 认可实验室 12 个月内报告：CPSIA 101/108、追踪标签、16 CFR 1130，及对应产品标准（1217/1218/1219/1220/1221/1222/1235/1241/1632–1633 或对应 ASTM）（CPSC 认可第三方实验室（经亚马逊授权 TIC 验证或实测））；儿童产品证书（CPC）（美国进口商或国内制造商）；产品责任险 COI（每次事故及累计 ≥100 万美元）；永久追踪标签、16 CFR 1130 注册卡、标准规定的警示标签 | 卖家平台 > 设置 > 商业保险验证；卖家平台 > 账户状况 > 食品和产品安全问题 > 验证您的商品（TIC） | R:US-L3-SLEEP-002 |
| 床垫（含沙发床垫、蒲团、带软包层的气垫床、儿童床垫）须符合 16 CFR 1632/1633，属强化安全类目（保险 + TIC，每个 ASIN 和尺寸单独验证） [SRC-US-AMZ-GBSYAXLHERCMCSQW] [SRC-US-AMZ-G4RUG6EAT2ZLVSRT] | 16 CFR 1632 + 16 CFR 1633 测试报告（至少一个样品按 1633 方法实测，逐 ASIN/尺寸验证）（CPSC 认可实验室（经亚马逊授权 TIC））；一般符合性证书（GCC）；儿童床垫为 CPC（美国进口商或国内制造商）；产品责任险 COI（≥100 万美元） | 卖家平台 > 设置 > 商业保险验证；卖家平台 > 账户状况 > TIC 服务 | R:US-L3-MATTRESS-001 |
| 成人便携床护栏须符合 16 CFR 1270 / ASTM F3186-24，属强化安全类目（保险 + TIC）；带医疗宣称的还须 FDA 注册列名 [SRC-US-AMZ-GBG6Z6TKMZHXQU7X] [SRC-US-AMZ-G4RUG6EAT2ZLVSRT] | ASTM F3186-24 或 16 CFR 1270 测试报告（12 个月内）（ISO/IEC 17025 认可实验室（经亚马逊授权 TIC））；一般符合性证书（GCC）（美国进口商或国内制造商）；有医疗宣称时：FDA 企业注册号与器械列名（美国 FDA）；产品责任险 COI（≥100 万美元）；产品和包装永久警示标签（F3186-24 / 16 CFR 1270） | 卖家平台 > 设置 > 商业保险验证；卖家平台 > 账户状况 > TIC 服务 | R:US-L3-SLEEP-003 |
| 衣物储物柜（高 ≥27 英寸、重 ≥30 磅、容积 ≥3.2 立方英尺）须符合 STURDY 法 16 CFR 1261 防倾倒标准并经授权 TIC 验证 [SRC-US-AMZ-G7L7RKBERYDEJ8QQ] | 16 CFR 1261 或 ASTM F2057-23、16 CFR 1303、40 CFR 770 测试报告（12 个月内）；儿童款另加 1500.48/1500.49、CPSIA（ISO/IEC 17025 认可实验室（儿童款为 CPSC 认可实验室），经亚马逊授权 TIC 验证）；GCC（儿童款为 CPC）（美国进口商或国内制造商）；永久防倾倒警示标签、防倾倒约束件和安装说明；详情页填写高度、重量 | 卖家平台 > 账户状况 > TIC 服务 | R:US-L3-CSU-001 |
| 婴幼儿坐具类耐用产品（餐椅、挂桌椅、增高座、弹跳椅、固定活动中心、秋千、儿童椅凳）须按各自 16 CFR 标准检测并提交 CPC [SRC-US-AMZ-G76DURDA6ZW48DX7] [SRC-US-AMZ-GUFQGCVJXHSYBL2Z] [SRC-US-AMZ-GYN5BF6ACA23ADZJ] [SRC-US-AMZ-G5YG8BBQQ9JQ4ZPD] [SRC-US-AMZ-GFUE3CNVCTY84VUG] | CPSC 认可实验室报告：CPSIA、追踪标签、16 CFR 1130 + 对应标准（1223/1229/1231/1232/1233/1237/1238 或对应 ASTM）（CPSC 认可第三方实验室）；儿童产品证书（CPC）（美国进口商或国内制造商）；永久追踪标签、16 CFR 1130 注册卡、警示标签 | 卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-INFANT-001 |
| 婴幼儿出行携带类耐用产品（推车、学步车、婴儿背带/腰凳/背架）须按 16 CFR 1227/1216/1226/1228/1230 检测并提交 CPC [SRC-US-AMZ-G4SX7HDHVCGK33UD] [SRC-US-AMZ-GGYR8DS2R8Q7R2SF] [SRC-US-AMZ-GGLAL34T93UJQ6KD] | CPSC 认可实验室报告：CPSIA、追踪标签、16 CFR 1130 + 1227/1216/1226/1228/1230（背带另加 16 CFR 1610）（CPSC 认可第三方实验室）；儿童产品证书（CPC）（美国进口商或国内制造商）；永久追踪标签、注册卡、标准规定的警示 | 卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-INFANT-002 |
| 洗浴、换尿布、安全门/围栏和儿童床护栏类耐用产品须按 16 CFR 1215/1234/1235/1239/1224 检测并提交 CPC [SRC-US-AMZ-GKVBB4SMC8PD3UWJ] [SRC-US-AMZ-GAMHBVRVCE4UNKPG] [SRC-US-AMZ-GHFCQ3SCKXWDYZN2] [SRC-US-AMZ-GR2MJURQF2UBYRPK] [SRC-US-AMZ-GXPFG3RRZB9WFPJE] [SRC-US-AMZ-G4RUG6EAT2ZLVSRT] | CPSC 认可实验室报告：CPSIA、追踪标签 + 1215/1234/1235/1239/1224（或 ASTM F1967/F3343/F2670/F2388/F1004/F2085）及 16 CFR 1130（CPSC 认可第三方实验室）；儿童产品证书（CPC）（美国进口商或国内制造商）；永久追踪标签、注册卡、标准规定的警示；儿童便携床护栏：产品责任险 COI（≥100 万美元） | 卖家平台 > 设置 > 商业保险验证；卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-INFANT-003 |
| 婴儿支撑垫（躺垫、婴儿窝、趴睡/坐立辅助垫）和哺乳枕须符合 16 CFR 1243/1242，属强化安全类目 [SRC-US-AMZ-GF37SYYLMCRJZ35Q] [SRC-US-AMZ-G4RUG6EAT2ZLVSRT] | CPSC 认可实验室报告：16 CFR 1243 或 1242/ASTM F3669-24 + CPSIA 101/108 + 追踪标签 + 1130 + 1303 + 1501（CPSC 认可第三方实验室）；儿童产品证书（CPC）；产品责任险 COI（≥100 万美元）；详情页强制警示语 + 最低月龄；产品和包装永久警示 | 卖家平台 > 设置 > 商业保险验证；卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-INFANT-004 |
| 婴幼儿喂养用品（奶瓶、学饮杯、餐具、餐碗、母乳/奶粉储存袋）及围兜须提交 CPSC 实验室报告和 CPC [SRC-US-AMZ-GUG6JJCDN6YYQYJP] [SRC-US-AMZ-GUDREU3TUSEM3D3B] | CPSC 认可实验室报告：CPSIA 铅/邻苯、追踪标签；围兜另加 16 CFR 1501、1610 或 1611（CPSC 认可第三方实验室）；儿童产品证书（CPC）；产品和包装永久追踪标签 | 卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-INFANT-006 |
| 牙胶、安抚奶嘴（16 CFR 1511 / ASTM F963-23 §4.20）和无串珠奶嘴夹须提交 CPSC 实验室报告和 CPC [SRC-US-AMZ-GDPSRCGVBFSFY78H] [SRC-US-AMZ-GX9BGE7LAFRWAFHF] | CPSC 认可实验室报告：ASTM F963-23（奶嘴 §4.20 或 16 CFR 1511）、CPSIA、追踪标签；奶嘴夹 16 CFR 1501（CPSC 认可第三方实验室）；儿童产品证书（CPC）；详情页年龄分级与报告一致 + 警示语 | 卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-INFANT-008 |
| 儿童汽车安全座椅、增高垫、手提婴儿篮及旅行系统须符合 FMVSS 213，属强化安全类目（须保险） [SRC-US-AMZ-G202137200] [SRC-US-AMZ-G4RUG6EAT2ZLVSRT] | FMVSS No. 213 测试报告（ISO 17025 实验室）；手提篮/旅行系统另加 ASTM F2050-19、F833-19（CPSC 认可实验室）（ISO/IEC 17025 / CPSC 认可实验室）；制造商声明（CoC/DoC/GCC/CPC 之一，含 CPSIA 101 铅检测）；产品责任险 COI（≥100 万美元）；FMVSS 213 警示标签和产品注册卡 | 卖家平台 > 设置 > 商业保险验证；卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-CARSEAT-002 |
| 儿童睡衣（0–9 个月婴儿睡衣、9 个月至 14 码）须符合 16 CFR 1610/1615/1616 阻燃要求，紧身款须有 “WEAR SNUG-FITTING” 标签和黄色吊牌 [SRC-US-AMZ-G5NGAYYZAY559SCZ] | CPSC 认可实验室报告：16 CFR 1610 / 1615 / 1616（或 ASTM D6545-22）、CPSIA、追踪标签，适用时 1501、1611（CPSC 认可第三方实验室）；儿童产品证书（CPC）；紧身款 “WEAR SNUG-FITTING, NOT FLAME RESISTANT” 尺码标签 + 黄色吊牌；永久追踪标签 | 卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-CHSLEEP-001 |
| 2T–16 码腰部/下摆带抽绳的儿童上衣须符合 ASTM F1816-18（外露 ≤3 英寸、无绳结/扣件、连续绳须加固缝） [SRC-US-AMZ-G8FDB4PSHS4AACQ5] | CPSC 认可实验室报告：ASTM F1816-18、CPSIA 101、16 CFR 1610、追踪标签（CPSC 认可第三方实验室）；儿童产品证书（CPC） | 卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-CHILD-002 |
| 儿童文具/学习用品（书包、书皮、午餐袋/盒、笔袋）须做铅、邻苯、镉检测并提交 CPC [SRC-US-AMZ-GXT3EFQS54LRKYM3] | CPSC 认可实验室报告：CPSIA 101、RCW 70.240.020（邻苯/镉）、追踪标签、16 CFR 1501（<3 岁）（CPSC 认可第三方实验室）；儿童产品证书（CPC）；详情页强制警示语 + 最低月龄；永久追踪标签 | 卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-CHILD-003 |
| 儿童自行车（座高 ≤25 英寸或供 12 岁以下）须符合 16 CFR 1512 并提交 CPSC 实验室报告和 CPC [SRC-US-AMZ-GVZJ58NTH3JDHC28] | CPSC 认可实验室报告：16 CFR 1512、CPSIA 101、追踪标签，适用时 1501、1500.19/1500.20（CPSC 认可第三方实验室）；儿童产品证书（CPC）；详情页座高属性；永久追踪标签、警示 | 卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-CHBIKE-001 |
| 儿童自行车头盔须符合 16 CFR 1203 并在详情页填写 CPSC 认证标签声明；儿童滑雪/单板头盔须符合 ASTM F2040 等 [SRC-US-AMZ-GCF2U4MHLT5D82H8] [SRC-US-AMZ-GTG9WQP9QK9EMDA6] | CPSC 认可实验室报告：自行车头盔 16 CFR 1203 + ASTM F1447/F1898 或 Snell B-90A/B-95；滑雪头盔 ASTM F2040-18/CSA Z263.1/Snell RS-98/S-98；CPSIA、追踪标签、小零件（CPSC 认可第三方实验室）；儿童产品证书（CPC）；头盔内 16 CFR 1203.6/1203.34 认证标签；详情页 legal_disclaimer 填 CPSC 符合性声明 | 卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-CHHELMET-001 |
| 蹦床及护网须符合 ASTM F381-24、F2225-24，儿童用蹦床另须 CPSC 实验室报告和 CPC [SRC-US-AMZ-G4UEALPJHSP85VRX] | ASTM F381-24、F2225-24、16 CFR 1500.44、16 CFR 1303、总铅测试报告（儿童用须 CPSC 认可实验室）（ISO/IEC 17025 认可实验室 / CPSC 认可实验室）；儿童用蹦床：儿童产品证书（CPC） | 卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-TRAMP-001 |
| 有绳窗饰（百叶、卷帘、罗马帘、蜂巢帘、窗帘轨道等）须符合 ANSI/WCMA A100.1-2022，警示和说明须英西双语 [SRC-US-AMZ-GT7F5YBQFRDZCAG8] | ANSI/WCMA A100.1-2022 测试报告（ISO/IEC 17025 认可实验室）；英文 + 西班牙文勒颈警示标签（产品和包装永久贴附）及双语说明书 | 卖家平台 > 账户状况 > 提交合规信息或申诉（或 Compliance Fast-Track） | R:US-L3-WINDOW-001 |
| 儿童首饰（含 DIY 首饰套件、儿童手表）须经授权 TIC 验证 ASTM F2923-20、CPSIA 铅、镉等检测并提交 CPC [SRC-US-AMZ-GT3XLUHYCWPM3THX] [SRC-US-AMZ-GUTZ2R2DD6P2UMVB] | CPSC 认可实验室报告：ASTM F2923-20、CPSIA 101，适用时 16 CFR 1262/1263/1501；另须满足 RCW 70.240.020 铅/镉/邻苯限值（CPSC 认可第三方实验室（经亚马逊授权 TIC 验证））；儿童产品证书（CPC）（美国进口商或国内制造商）；详情页强制警示语 + 最低月龄；产品和包装永久追踪标签；DIY 套件危险警示 | 卖家平台 > 账户状况 > TIC 服务 | R:US-L3-CHJEWEL-001 |
| 锂电供电的智能家居/消费电子和家用电器（耳机、音箱、摄像头、平板、传感器、吸尘器、榨汁机、风扇、加湿器、卷发棒等）属强化安全类目：须 COI + 授权 TIC 验证整机 UL 标准及电池 UL 2054/62133-2 等 + UN38.3 [SRC-US-AMZ-GA2PQDTU5HMC7CRZ] [SRC-US-AMZ-G8TM22XFM7WXCRDC] [SRC-US-AMZ-G4RUG6EAT2ZLVSRT] [SRC-US-AMZ-GUTZ2R2DD6P2UMVB] | 产品责任险保险证明（COI，≥100 万美元，见 US-L2-ENHANCED-001）；12 个月内 ISO 17025 整机报告（62368-1、61010 系列、UL 499/1017/982/963/507/998/859、60335-2-40，按产品类型）（ISO/IEC 17025 认可实验室）；充电器 UL 1310/1012/60335-2-29/62368-1；电池 UL 1642/2054/2595/62133-2 + UN 38.3 报告 + BTS（12 个月内）（ISO/IEC 17025 认可实验室）；详情页填写型号/零件号、制造商或品牌 | 亚马逊授权 TIC 服务商（卖家平台 > 账户状况 > TIC 服务）；卖家平台 > 设置 > 商业保险验证 | R:US-L3-LIBATT-001 |
| 移动电源和便携储能电站须 COI + 授权 TIC 验证（UL 2056 或 62368-1+62133-2/UL 2054；储能站 UL 2743；均需 UN38.3+BTS）；汽车应急启动电源须 UL 2743 报告 [SRC-US-AMZ-GSJFE8S8AES7F7VG] [SRC-US-AMZ-G6WCA7BRX5QWHMNF] [SRC-US-AMZ-G4RUG6EAT2ZLVSRT] | 产品责任险 COI（移动电源/储能站）；移动电源 UL 2056 或 62368-1 + 62133-2/UL 2054；储能站 UL 2743；UN 38.3 报告 + BTS（12 个月内）（ISO/IEC 17025 认可实验室）；汽车应急启动电源 UL 2743 报告（ISO/IEC 17025 认可实验室）；产品与包装永久警示语、型号、责任方名称 | 亚马逊授权 TIC 服务商；卖家平台 > 设置 > 商业保险验证；卖家平台 > 账户状况 > 提交合规信息或申诉（直接交亚马逊） | R:US-L3-PPS-001 |
| 笔记本/手机替换电池、笔记本充电器、手机墙充和车充须提交 ISO 17025 实验室 UL 安全测试报告 [SRC-US-AMZ-G202156120] | 按产品类型的 UL/IEC 安全报告（UL 2054/62133/62368-1/UL 1310/60950-1/UL 2089）；笔记本电池另需 UN 38.3 + BTS（ISO/IEC 17025 认可实验室）；详情页型号、品牌、警示语；产品标签含合规标志和责任方名称地址 | 卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-CHARGER-001 |
| 锂电加热服装（夹克、背心、手套、袜、帽、头带）和可拆电池加热鞋垫须提交 62368-1/UL 499/60335-2-17 及电池 UL 2054 或 62133-2 + UN38.3 报告 [SRC-US-AMZ-GFQMECECLTJCUE3H] | 62368-1 / UL 499 / 60335-2-17（整机）+ UL 2054 或 62133-2 + BTS + UN 38.3（电池包）（认可实验室（ISO/IEC 17025））；型号、品牌、责任方名称地址、合规标志 | 卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-HEATWEAR-002 |
| 电动出行设备（电动自行车/三轮车、平衡车、电动滑板、电动滑板车、电动独轮车）及其单独销售的电池、充电器、改装套件须 COI + TIC 验证（UL 2849/16 CFR 1512、UL 2272、UL 2271 等 + UN38.3）；纽约州另有多语言说明书和警示要求 [SRC-US-AMZ-GMUW6CKYLY4AP8MK] [SRC-US-AMZ-G7HM69VDEMRW7TPE] [SRC-US-AMZ-G4RUG6EAT2ZLVSRT] [SRC-US-AMZ-GUTZ2R2DD6P2UMVB] | 产品责任险 COI；电动自行车/三轮车 16 CFR 1512 + UL 2849；其他 UL 2272；替换电池 UL 2271；充电器 UL 1310/1012/62368-1；改装套件 UL 2272 或 UL 2849；含电池的另加 UN 38.3 报告 + BTS（12 个月内）（ISO/IEC 17025 认可实验室）；产品与包装永久警示和合规标志；纽约州：13 种语言操作手册 PDF、红色充电线标签、礼让行人告示、检测机构标志图片 | 亚马逊授权 TIC 服务商；卖家平台 > 设置 > 商业保险验证；邮件 pars-rp-core-sellerappeals-transfer@amazon.com | R:US-L3-EMOB-002 |
| 饮用水输送产品（管道、管件、水龙头、水泵水箱、洁具、接水电器、焊料）须 ANSI 认可机构的无铅认证（NSF/ANSI/CAN 61 或 372）；净水器须 NSF/ANSI 42/53/55/58/62/401 [SRC-US-AMZ-GYD98N4N2ASSPVLE] [SRC-US-AMZ-GUTZ2R2DD6P2UMVB] | 无铅认证 NSF/ANSI/CAN 61 或 372（ANSI 认可认证机构）（ANSI 认可认证机构（如 NSF、IAPMO、CSA、UL、WQA））；净水器 NSF/ANSI/CAN 42/55/58/62；健康宣称加 53；新兴污染物宣称加 401；加州终端器件 NSF/ANSI/CAN 61（CA H&S Code 116876） | 亚马逊授权 TIC 服务商 | R:US-L3-WATERDEL-001 |
| 泳池/水疗排水盖须符合 VGB 法案 16 CFR 1450 或 ANSI/APSP/ICC-16 2017 [SRC-US-AMZ-GTT32L3J5ZG23FMF] | 16 CFR 1450 或 ANSI/APSP/ICC-16 2017 测试报告（或合规标识图片）（ISO/IEC 17025 认可实验室） | 卖家平台 > 账户状况 > 提交合规文件或申诉 | R:US-L3-POOL-001 |
| 便携式发电机/逆变发电机须 COI 和 16 CFR 1407 + PGMA G300/UL 2201（或 RVIA EGS-1/UL 2200）报告；便携逆变器须 UL 458 或 UL 2743 [SRC-US-AMZ-GXCXR3BN2ESL6TQC] [SRC-US-AMZ-G4RUG6EAT2ZLVSRT] | 产品责任险 COI；发电机 16 CFR 1407 + PGMA G300 & UL 2201（或 RVIA EGS-1 & UL 2200）；逆变器 UL 458 或 UL 2743（ISO/IEC 17025 认可实验室）；永久一氧化碳警示标签、16 CFR 1407 性能标签 | 卖家平台 > 设置 > 商业保险验证；卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-GENSET-001 |
| 灯串（UL 588）、灯带/管灯（UL 2388）及附带 Class 2 电源（UL 1310）须提交 ISO 17025 测试报告 [SRC-US-AMZ-G202137960] [SRC-US-AMZ-G200164510] | UL 588（灯串）/ UL 2388（绳灯管灯）/ UL 1310（Class 2 电源）（ISO/IEC 17025 认可实验室）；永久警示和合规标志（产品与包装） | 卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-STRLIGHT-001 |
| 家用/轻商用高压清洗机须 COI + TIC 验证 UL 1776 或 UL 60335-2-79；详情页须写 PSI、流量、水管和电源线长度 [SRC-US-AMZ-GCEQ79CVX6XPVK4B] [SRC-US-AMZ-G4RUG6EAT2ZLVSRT] | 产品责任险 COI；UL 1776 或 UL 60335-1 + 60335-2-79；充电器 UL 1012/1310/60335-2-29；电池 UL 2054/62133-2 + UN 38.3 + BTS（ISO/IEC 17025 认可实验室）；详情页属性：动力来源、最大 PSI、最大流量、水管长度、电源线长度 | 亚马逊授权 TIC 服务商 | R:US-L3-PWASH-001 |
| 电暖器须 UL 1278 报告；吹风机须 UL 859/UL 1727 报告并带一体式防浸水保护插头 [SRC-US-AMZ-GGUXTDB7TLY6F5LE] [SRC-US-AMZ-GW5CVACPVTQNTWHX] | 电暖器 UL 1278；吹风机 UL 859 或 UL 1727（ISO/IEC 17025 认可实验室）；合规标志、警示、责任方名称地址；吹风机一体式防浸水保护插头（IDCI/ALCI） | 卖家平台 > 账户状况 > 提交合规文件或申诉 | R:US-L3-HEATER-001 |
| 便携燃油容器（100 mL–20 L，空罐或预灌装）须儿童防护 ASTM F2517-22 与防火焰装置（ASTM F3326-21/UL 30 或 F3429）报告及 GCC [SRC-US-AMZ-GEJBWFAU7W5MC3ZA] [SRC-US-AMZ-G200164410] | ASTM F2517-22 + （ASTM F3326-21 或 UL 30:2022）；预灌装：F2517-22 + F3429/F3429M-24（ISO/IEC 17025 认可实验室）；一般符合性证书（GCC，CPSA 14(a)）（美国进口商或国内制造商） | 卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-FUELCAN-001 |
| 燃气户外取暖产品（火盆、户外壁炉、天井取暖器）须 COI + TIC 验证 ANSI Z21.97 或 Z83.26 证书，并接受强制抽样测试 [SRC-US-AMZ-GDQULCAPUQQ9D9Z8] [SRC-US-AMZ-G4RUG6EAT2ZLVSRT] [SRC-US-AMZ-GUTZ2R2DD6P2UMVB] | 产品责任险 COI；ANSI Z21.97/CSA 2.41 或 ANSI Z83.26/CSA 2.37 合格证书（ISO 17065 认可机构）（ISO/IEC 17065 认可认证机构（如 CSA、ITS、UL、BV））；天井取暖器 Z83.26 第 5.18、5.22 条补充测试；认证与标签核查（TIC 抽样）；永久一氧化碳警示、铭牌、NRTL 标志 | 亚马逊授权 TIC 服务商 | R:US-L3-PATIOHEAT-001 |
| 电动切割工具（各类电锯、角磨、砂光机、修边机、劈木机等）须 COI + TIC 验证 UL 987/UL 60745/UL 62841 系列报告，电池加 UN38.3 [SRC-US-AMZ-G47MZUS764W88ZRP] [SRC-US-AMZ-G4RUG6EAT2ZLVSRT] [SRC-US-AMZ-GUTZ2R2DD6P2UMVB] | 产品责任险 COI；UL 987 / UL 60745 系列 / UL 62841 系列（按工具类型）；充电器与电池标准；UN 38.3 + BTS（ISO/IEC 17025 认可实验室）；电压额定值、永久警示、合规标志 | 亚马逊授权 TIC 服务商 | R:US-L3-CUTTOOL-001 |
| 自 2028-09-05 起电动切割工具须符合 UL 62841 系列 [SRC-US-AMZ-G47MZUS764W88ZRP] | UL 62841-1 + 对应部分（2-3、2-4、2-5、2-8、2-11、2-13/4-1、2-17、2-20、3-1、3-5、3-9、3-10 等）（ISO/IEC 17025 认可实验室） | 亚马逊授权 TIC 服务商 | R:US-L3-CUTTOOL-002 |
| 不含二氯甲烷/NMP 的脱漆产品须提交 SDS 和标签图片 [SRC-US-AMZ-GW6HK2RDRNNFW2ML] | 安全数据表（SDS）（制造商）；标签、危险警示、使用说明图片 | 卖家平台 > 账户状况 > 提交合规文件或申诉 | R:US-L3-PAINTRM-001 |
| 消防类产品：烟雾/一氧化碳/燃气/感温报警器须 COI + TIC 验证 UL 217/2034/1484/539 证书；灭火器须 COI + UL 8/626/299/154/2129 报告 [SRC-US-AMZ-GXUCN5ZRJSYN9W9S] [SRC-US-AMZ-GS972L5FPTCLNYNR] [SRC-US-AMZ-G4RUG6EAT2ZLVSRT] [SRC-US-AMZ-GUTZ2R2DD6P2UMVB] | 产品责任险 COI；报警器：UL 217 Ed.9+/UL 2034 Ed.5/UL 1484 Ed.6/UL 539 Ed.8 合格证书（ISO 17065 认可机构）（ISO/IEC 17065 认可认证机构（如 UL、ITS、SGS、TÜV））；灭火器：UL 8/UL 626/UL 299/UL 154/UL 2129 报告（ISO/IEC 17025 认可实验室）；NRTL 合规标志、永久警示（压力容器、放射性材料等） | 亚马逊授权 TIC 服务商；卖家平台 > 设置 > 商业保险验证；卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-ALARM-001 |
| 非玩具磁铁产品（娱乐、首饰含儿童首饰、解压/益智用可分离磁铁）须符合 16 CFR 1262 或 ASTM F963 第 4.38 条 [SRC-US-AMZ-GXDAVVP3RBLKV4GP] [SRC-US-AMZ-GS62X9B3B79U8HGK] | 16 CFR 1262 或 ASTM F963 第 4.38 条测试报告（ISO 17025 实验室）；或 GCC / 分析证书（COA，如适用）（ISO/IEC 17025 认可实验室；GCC 由美国进口商或国内制造商出具）；详情页型号、品牌、年龄分级（与报告一致）、危险警示语；图片含责任方名称地址、标签、包装、合规标志、警示、说明书 | 卖家平台 > 账户状况 > 提交合规文件或申诉 | R:US-L3-MAGNET-001 |
| 自行车、滑雪/单板、登山、马术头盔须按对应标准检测并提交报告（自行车头盔须符合 CPSC 16 CFR 1203） [SRC-US-AMZ-GHRAUBNDL7K7EZSG] [SRC-US-AMZ-G6676M3NTXR26CAY] [SRC-US-AMZ-GAPBV3UDXPHP3C42] [SRC-US-AMZ-GYACVQUFWV28PZ2H] [SRC-US-AMZ-G4RUG6EAT2ZLVSRT] | 自行车 16 CFR 1203 + ASTM F1447/Snell B-90A/B-95；滑雪 ASTM F2040/CSA Z263.1/Snell RS-98/S-98；登山 UIAA 106/EN 12492/Snell N-94；马术 ASTM F1163-15/Snell E-2001（ISO/IEC 17025 认可实验室（UIAA 106 须 UIAA 认可实验室；儿童头盔须 CPSC 认可实验室））；GCC（自行车、滑雪头盔）；儿童头盔为 CPC（美国进口商或国内制造商）；产品责任险 COI（安全头盔属强化安全类目） | 卖家平台 > 设置 > 商业保险验证；卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-HELMET-001 |
| 摩托车头盔须符合 FMVSS 218（DOT 标签）或 Snell M2010/M2015；儿童摩托车头盔另须 CPSIA 检测和 CPC [SRC-US-AMZ-GKMN8QPMQ6K8SK3E] [SRC-US-AMZ-G200164410] | FMVSS 218 合规（DOT 标签，S5.6）或 Snell M-2010/M-2015 认证（制造商自我认证（FMVSS）/ Snell 基金会）；儿童摩托车头盔：CPSC 认可实验室报告（CPSIA 铅、追踪标签、16 CFR 1501、1500.19/1500.20）+ CPC（CPSC 认可实验室；CPC 由美国进口商或国内制造商出具）；DOT 标签；儿童款详情页强制警示语 + 最低年龄（月） | 卖家平台 > 账户状况 > 提交合规文件或申诉 | R:US-L3-HELMET-002 |
| 漱口水须符合《防毒包装法》(16 CFR 1700) 儿童防护包装，提交 GCC 或乙醇 <3 g 成分表及 ISO 17025 报告 [SRC-US-AMZ-GPWPSA5MVZQLLLKR] [SRC-US-AMZ-GKHQEFBM7834V6AV] | 16 CFR 1700（PPPA）测试报告（ISO/IEC 17025 认可实验室）；GCC，或乙醇 <3 g 的成分表（美国进口商或国内制造商）；详情页有效成分表图片 + 型号/品牌 | 卖家平台 > 账户状况 > 提交合规文件或申诉 | R:US-L3-MOUTHWASH-002 |
| 攀岩绳、攀岩安全带、登山扣、防坠落安全带须按 UIAA/EN/ASTM/ANSI Z359 检测，并提交 ≥100 万美元保险证明 [SRC-US-AMZ-GXQA3Y847TZVJE3R] [SRC-US-AMZ-GNW6TTB8WVHHECFR] [SRC-US-AMZ-G52LHU99LA38NLU7] [SRC-US-AMZ-GL8P7RSBPB3HS553] [SRC-US-AMZ-G4RUG6EAT2ZLVSRT] | 产品责任险 COI（≥100 万美元，强化安全类目）；绳 UIAA 101/EN 892；安全带 ASTM F1772-24/EN 12277/UIAA 105；登山扣 ANSI Z359.12/ASTM F1774/EN 12275/UIAA 121；防坠落 ANSI Z359.1/Z359.11/OSHA 1910.140（ISO/IEC 17025 认可实验室（UIAA 标准须 UIAA 认可实验室；儿童产品须 CPSC 认可实验室））；永久警示语、合规标志；儿童安全带追踪标签、注册卡、强制警示语和最低月龄 | 卖家平台 > 设置 > 商业保险验证；卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-CLIMB-001 |
| 个人润滑剂、男用/女用避孕套属医疗器械：须提交 FDA 510(k) 许可函和 FURLS 注册/列名截图 [SRC-US-AMZ-GNEJ9DZASWJL4S4U] [SRC-US-AMZ-G4EX3SEAAQRMLKN8] [SRC-US-AMZ-G200164650] | FDA 510(k) 许可函（21 CFR 807 Subpart E）（美国 FDA）；FDA 企业注册号与器械列名（FURLS 截图）（美国 FDA） | 卖家平台 > 账户状况 > 提交合规文件或申诉 | R:US-L3-SEXWELL-001 |
| 紧急避孕药（左炔诺孕酮）须符合 PPPA 儿童防护包装和 NDC 列名，提交 ISO 17025 报告和 GCC [SRC-US-AMZ-G5QJSTMF6TLDXW53] [SRC-US-AMZ-G200164490] | 16 CFR 1700 / 21 CFR 207 Subpart C 合规测试报告（ISO/IEC 17025 认可实验室）；GCC（美国进口商或国内制造商）；FDA 药品列名 NDC 号（美国 FDA） | 卖家平台 > 账户状况 > 提交合规文件或申诉 | R:US-L3-CONTRA-001 |
| 卫生棉条须 FDA 注册列名 + 510(k)；卫生巾、月经裤、月经杯/碟须 FDA 注册列名 [SRC-US-AMZ-GMFZGW34G9Y5HU75] [SRC-US-AMZ-G200164650] | FDA 企业注册与器械列名（FURLS 截图）（美国 FDA）；卫生棉条 FDA 510(k) 许可函（美国 FDA） | 卖家平台 > 账户状况 > 提交合规文件或申诉 | R:US-L3-MENSTRUAL-001 |
| 日食眼镜和手持太阳观测卡须符合 ISO 12312-2:2015，并提交 ISO 17025 实验室报告 [SRC-US-AMZ-G202171660] | ISO 12312-2:2015 测试报告（ISO/IEC 17025 认可实验室） | 卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-ECLIPSE-002 |
| 指尖陀螺须按儿童玩具标准（ASTM F963、CPSIA 铅/邻苯、16 CFR 1501）检测并提供 CPC 和小零件警示 [SRC-US-AMZ-G202155900] [SRC-US-AMZ-GKJRA3FRPRKVBJJS] | ASTM F963-23/-17、CPSIA 铅/邻苯、16 CFR 1501 测试报告（CPSC 认可实验室）；儿童产品证书（CPC）（美国进口商或国内制造商）；详情页小零件警示语 | 卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-FIDGET-001 |
| 呼吸防护口罩（N95 等须 NIOSH 42 CFR 84 批准；KN95/FFP2/KF94 按原标准且不得冒充 N95）及火灾逃生面罩（ASTM E2952-24）须提交证书和报告 [SRC-US-AMZ-GUBJLLVL96U285RQ] [SRC-US-AMZ-GGB3K8RJ6ZEB8QQ6] [SRC-US-AMZ-G200301050] | NIOSH 批准证书（42 CFR 84）+ 组装矩阵；外科 N95 另需 FDA 510(k)；KF94 产品批准证书（英文）（美国 NIOSH/CDC；美国 FDA；韩国 MFDS）；KN95 GB 2626（CNAS 实验室英文报告）/ FFP EN 149 / 逃生面罩 ASTM E2952-24（ISO 17025 实验室）（CNAS 或 ISO/IEC 17025 认可实验室）；KN95/KF94/FFP 不得标示或宣传为 N95 或 NIOSH 批准 | 卖家平台 > 账户状况 > 提交合规信息或申诉 | R:US-L3-RESP-001 |
| 救生衣、浮力背心、浮力辅助、救生圈、浮垫等个人漂浮装置须符合 USCG/UL 标准；非 PFD 产品不得称“救生衣” [SRC-US-AMZ-G202162990] [SRC-US-AMZ-G4RUG6EAT2ZLVSRT] | USCG 批准号/批准证书，或 UL 1123/1175/1177/1180/1517/12402-5、46 CFR 160.055、SOLAS 测试报告（美国海岸警卫队 / ISO/IEC 17025 认可实验室）；非 PFD 产品禁止使用救生衣类措辞；产品责任险 COI（可穿戴或充气漂浮产品属强化安全类目） | 卖家平台 > 账户状况 > 提交合规文件或申诉 | R:US-L3-PFD-001 |
| 医用检查手套（乳胶/丁腈/PVC）须 FDA 510(k) 和企业注册列名 [SRC-US-AMZ-GWU7WD8984FT4YLJ] [SRC-US-AMZ-G200164650] | FDA 510(k) 许可函（美国 FDA）；FDA 企业注册与器械列名（FURLS 截图）（美国 FDA） | 卖家平台 > 账户状况 > 提交合规文件或申诉 | R:US-L3-MEDGLOVE-001 |
| 医用体温计：电子（接触式/非接触额温枪）须 FDA 注册列名 + 510(k)；变色一次性体温计须注册列名 [SRC-US-AMZ-GJFNF3SE7N7ZLE78] [SRC-US-AMZ-G200164650] [SRC-US-AMZ-GN9YK5Y7TYGRGNRG] | 电子体温计 FDA 510(k) 许可函（美国 FDA）；FDA 企业注册与器械列名（FURLS 截图）（美国 FDA） | 卖家平台 > 账户状况 > 提交合规文件或申诉 | R:US-L3-THERMO-001 |
| 成人自行车（座高 >25 英寸及人行道自行车、公路卧式车）须符合 16 CFR 1512，提交 ISO 17025 报告和 GCC [SRC-US-AMZ-GBVSAAJFBSKYNT8Q] | 16 CFR 1512 测试报告（ISO/IEC 17025 认可实验室）；GCC（美国进口商或国内制造商） | 卖家平台 > 账户状况 > 提交合规文件或申诉 | R:US-L3-BICYCLE-001 |
| 羊绒产品须经授权 TIC 验证纤维成分检测（羊毛标签法、纺织品纤维标识法；AATCC TM 020/020A、ISO 1833 或 JIS L1030-2） [SRC-US-AMZ-GVP5GB6WPLQNSW5M] [SRC-US-AMZ-GUTZ2R2DD6P2UMVB] | 纤维成分检测报告（AATCC TM 020/020A-2021、ISO 1833 或 JIS L1030-2）（认可实验室，经亚马逊授权 TIC 验证）；纤维成分（降序、通用名、合计 100%）、RN 号、洗护说明（美国 FTC（RN 号）） | 卖家平台 > 账户状况 > 第三方检测、检验与认证服务（TIC） | R:US-L3-CASHMERE-001 |
| FTC 能源标签规则（EnergyGuide/Lighting Facts/E 图标/用水量）及加州 CEC Title 20 能效登记 [SRC-US-AMZ-G201814570] [SRC-US-AMZ-G7PNYFCP46WHA3RL] [SRC-US-AMZ-G201707090] | EnergyGuide / Lighting Facts 标签图片、E 图标、用水量信息（制造商或自有品牌商）；加州 CEC MAEDbS 能效登记（销往加州的受管产品）（加州能源委员会（CEC）） | 卖家平台 > 通过上传添加商品（工具与家装、家居园艺、照明、消费电子模板） | R:US-L3-ENERGY-001 |
| 有保质期商品（食品、补充剂、护肤洗护、清洁剂、带 PAO 标志等）须留足剩余保质期并按格式标注日期 [SRC-US-AMZ-GD646NUBNNJLQADP] | 有效期/生产日期标注（格式与位置要求）；发货时剩余保质期满足使用周期；食品批次管控 | 按亚马逊通知提交（账户状况 > 商品合规性请求） | R:US-L3-EXPIRY-001 |
| 食品/药品/医疗器械/化妆品须提供 FFDCA 持续保证；补充剂须加 FDA 免责声明；农药类须作 FIFRA 保证 [SRC-US-AMZ-G201707070] [SRC-US-AMZ-G201707090] | FFDCA 持续保证（continuing guarantee）；FIFRA 保证（农药类）；补充剂结构/功能宣称附 FDA 免责声明 | 按亚马逊通知提交（账户状况 > 商品合规性请求） | R:US-L3-LISTING-001 |
| 纺织品、羊毛制品、毛皮服饰 Listing 须按纺织法/羊毛法/毛皮法披露原产地（Imported）和纤维成分 [SRC-US-AMZ-G201707090] | Listing 与标签一致的原产地（Imported）和纤维成分百分比；毛皮动物名与 Fur Origin | 品类模板或 Additional Product Information 模板 | R:US-L3-LISTING-002 |
| 含加州 Prop 65 清单化学物质的商品须在 Listing 链接亚马逊 Prop 65 说明页 [SRC-US-AMZ-G201707090] | Prop 65 警示（Listing 链接 Prop 65 说明页；产品/包装按 OEHHA 安全港格式警示） | 按亚马逊通知提交（账户状况 > 商品合规性请求） | R:US-L3-LISTING-003 |
| 产品安全调查、违规处置与合规工具（Compliance Reference、Compliance Fast-Track） [SRC-US-AMZ-G4QUDFLRX8GBFPVV] [SRC-US-AMZ-GX9VRVWH8HXTDTK7] [SRC-US-AMZ-G2JX2MAWJ27DWAY6] [SRC-US-AMZ-GNHU43TN2RHER9BQ] [SRC-US-AMZ-GWGLZQPAQN6VJZND] | 保存全部安全与合规文件，按通知期限答复；可选通过 Fast-Track 机构认证 | 卖家平台 > 账户状况；库存 > 编辑 > Compliance > Compliance Regulation Type / Regulatory Identification | R:US-L3-INVESTIG-001 |
| 软包家具、床品、绗缝制品须符合联邦披露和各州填充物标签法 [SRC-US-AMZ-G8V5URH2QPKMY3NS] | 州法填充物内容标签（Law Label），注明填充物材料及重量百分比、URN/许可证号；相关州床品/软包家具制造商、进口商、经销商许可证（如犹他州 Bedding, Upholstered Furniture and Quilted Clothing Program）（各州主管机构） | 按亚马逊通知提交（账户状况 > 商品合规性请求） | R:US-L3-UPHOL-001 |
| 燃油发动机及燃油/电动车辆须提交 EPA 合格证书（CoC）编号或 CARB EO 编号 [SRC-US-AMZ-GKJXWS7VY64WZZ7K] [SRC-US-AMZ-G202082160] [SRC-US-AMZ-GXCXR3BN2ESL6TQC] | EPA Certificate of Conformity（CoC）编号，或 CARB Executive Order 编号（美国环保署（EPA）/ 加州空气资源委员会（CARB）） | 卖家平台 > 库存 > 管理库存 > 编辑 > Safety & Compliance 标签 > Compliance Regulation Type 选 "EPA Certificate of Conformity (CoC)"，在 Regulatory Identification 填编号；批量用库存文件模板的 Compliance 属性组 | R:US-L3-EPA-001 |
| 儿童服装（12 岁及以下）须提供 CPSC 认可实验室检测报告和 CPC [SRC-US-AMZ-GJJPTVHXVDA5PAG7] [SRC-US-AMZ-GSGB43AFZNDWD4U8] | CPSC 认可实验室检测报告：CPSIA 铅（含表面涂层）、16 CFR 1610 服装易燃性、16 CFR 1501 小零件（3 岁以下适用）（CPSC 认可的第三方实验室）；儿童产品证书（CPC）（美国进口商或国内制造商）；CPSA 第 14(a)(5) 条永久追踪标签（产品和包装）；公司名称与卖家 ID、联系方式、在售儿童服装清单、包装各面照片和标签照片、说明书 | 卖家平台 > 绩效 > 账户状况 > 管理您的合规性 > 商品合规性请求（Product Compliance Requests）> 添加/申诉合规 | R:US-L3-CHAPPAREL-001 |
| 儿童鞋（12 岁及以下）须提供 CPSC 认可实验室检测报告和 CPC [SRC-US-AMZ-GK9K2S3L8J2QJW22] [SRC-US-AMZ-GSGB43AFZNDWD4U8] | CPSC 认可实验室检测报告：CPSIA 101 铅、16 CFR 1501 小零件（3 岁以下适用）（CPSC 认可的第三方实验室）；儿童产品证书（CPC）；CPSA 第 14(a)(5) 条追踪标签 | 卖家平台 > 绩效 > 账户状况 > 商品合规性请求 | R:US-L3-CHFOOTWEAR-001 |
| 机动车轮胎、轮毂、轮辋须提交 FMVSS 合规证书和测试报告 [SRC-US-AMZ-GJQMR3AUDBH6RXR5] | 亚马逊 FMVSS 合规证书表（Certificate of Compliance to FMVSS）（制造商或记录进口商）；FMVSS 测试报告（轮胎和车轮）（内部或第三方实验室）；轮胎登记（TIN 记录） | 卖家平台 > 管理您的合规性（MYC）> 添加/申诉合规 | R:US-L3-TIRE-002 |

### D. FBA 与危险品（L4）

#### D.1 FBA 禁运清单
可以在亚马逊销售、但不能发 FBA 的商品 [SRC-US-AMZ-G201730840] [SRC-US-AMZ-G200140860] [R:US-L4-FBA-001] [R:US-L4-FBA-002]：
- 酒精饮料（包括无醇啤酒）、车辆轮胎、礼品卡/礼券等储值工具、散装电池、单件 ≥50 磅的危险品。
- 带非亚马逊营销材料或预贴价签、未按要求预处理、破损缺陷（二手正确标注除外）、标签未登记或不符、仿冒的商品；亚马逊可拒绝仿冒品的移除申请并直接销毁。
- 其他政策中写明“不可 FBA”的：处方/专业用医疗器械（误入仓将被销毁且费用由卖家承担）[R:US-L2-MED-003]；安全求救信号弹 [R:US-L1-WEAPON-002]；笑气奶油弹（仅限自配送）[R:US-L4-HAZ-013]；FBA 禁止类别的危险品 [R:US-L4-DG-001]。

#### D.2 危险品分类与资料
- 危险品是否成立取决于成品的理化特性，不按商品类型预设；笔记本、手机、家用清洁剂、喷漆、化妆品、含磁铁的音箱都可能是危险品。所有可能涉及的商品都须上传 SDS 或豁免表，14 个工作日内完成；入仓时“无法分类”的商品会被设为不可售，未确认分类就发货的可能被无偿销毁 [SRC-US-AMZ-G201003400] [R:US-L4-DG-002]。
- FBA 绝对禁止：第 1 类爆炸品、2.3 有毒气体、4.2 自燃、4.3 遇湿危险、6.2 感染性物质、第 7 类放射性物质 [R:US-L4-DG-001]。
- 可经 FBA 危险品计划销售（等候名单制，有限数量包装，多为地面运输，受易燃/气雾剂仓容限制）：2.1、2.2、3、4.1、5.1、5.2、6.1、8、9 类，包括锂电池 UN3480/3481/3090/3091、电池驱动车辆 UN3556/3557/3558/3171、磁性物质 UN2807 [SRC-US-AMZ-GZLZBQ7W6QZRKWWK] [R:US-L4-DG-003]。

#### D.3 锂电池、喷雾、液体、磁铁等常见情形
- **锂电池入仓上限（美国站）**：电芯锂离子 ≤60 Wh / 锂金属 ≤5 g，电池锂离子 ≤300 Wh / 锂金属 ≤25 g 可接收；电芯 >60 Wh 或电池 >300 Wh（锂金属 >5 g / >25 g）拒收。100–300 Wh 一档美国站接收、欧洲/澳洲等站拒收，储能站多超过 300 Wh，只能自配送 [SRC-US-AMZ-G200383420] [R:US-L4-FBALIB-001]。
- **上架时须填电池与危险品属性**：设备内或随设备包装的锂离子电池须回答荷电状态（SoC）问题；锂电池须上传 UN38.3 测试摘要；SDS 须为 16 节格式且品名品牌与详情页一致，豁免表只适用于电池类和不含有害化学品的商品（见 D.4 中 DGDOC 规则）[SRC-US-AMZ-G201371860] [SRC-US-AMZ-G201749580]。
- **气雾剂、易燃液体（香水、指甲油、含酒精产品）、腐蚀品**：属 2.1/2.2/3/8 类，须加入 FBA 危险品计划并按有限数量包装，受“易燃/气雾剂”仓容限制 [R:US-L4-DG-003]。
- **磁性物质**：含磁铁的音箱、耳机、磁贴、工具、玩具可能属第 9 类 UN2807，须提交分类资料 [R:US-L4-DG-002]。
- **有效期商品与易融商品**：有效期商品入仓剩余保质期须满足规定天数，易融商品有季节性入仓和处置期，详见 D.4 中 FBAEXP、FBAMELT 规则 [SRC-US-AMZ-G201003420] [SRC-US-AMZ-G202125070]。


#### D.4 L4 规则一览

| 主题 | 要求 | FBA 处理 | 规则ID |
| --- | --- | --- | --- |
| 笑气奶油气弹（≤8.4 g/支、每包 ≤10 支）只能自发货，不得 FBA；允许的危险品须按 DOT 规定运输 [SRC-US-AMZ-G200164570] [SRC-US-AMZ-G200164490] | 笑气气弹仅限 MFN；危险品按 DOT 49 CFR 及 USPS Publication 52 运输 | prohibited | R:US-L4-HAZ-013 |
| FBA 禁运商品：酒精饮料（含无醇啤酒）、车辆轮胎、礼品卡/储值卡、散装电池、单件 ≥50 磅的危险品 [SRC-US-AMZ-G201730840] [SRC-US-AMZ-G200140860] | 上述商品不得发往亚马逊运营中心，只能自配送 | prohibited | R:US-L4-FBA-001 |
| FBA 不接收：带非亚马逊营销材料/预贴价签、未按要求预处理、破损缺陷、标签未登记或不符、仿冒品 [SRC-US-AMZ-G201730840] | 按 FBA 包装与预处理要求备货；不得夹带营销材料或价签 | prohibited | R:US-L4-FBA-002 |
| FBA 禁止的危险品类别：第 1 类爆炸品、2.3 有毒气体、4.2 自燃、4.3 遇湿危险、6.2 感染性物质、第 7 类放射性物质 [SRC-US-AMZ-G201003400] [SRC-US-AMZ-GZLZBQ7W6QZRKWWK] | 上述类别危险品不得 FBA | prohibited | R:US-L4-DG-001 |
| 可能属危险品的 FBA 商品须提交 SDS 或豁免表并完成危险品分类（14 个工作日内） [SRC-US-AMZ-G201003400] [SRC-US-AMZ-GZLZBQ7W6QZRKWWK] [SRC-US-AMZ-G201371860] [SRC-US-AMZ-G201749580] [SRC-US-AMZ-G200383420] [SRC-US-AMZ-GHLPCM24G965CHSK] [SRC-US-AMZ-G200525640] | 安全数据表（SDS，GHS 16 节格式）或亚马逊危险品豁免表；锂电池须含 UN38.3 测试摘要等信息 | dg_review | R:US-L4-DG-002 |
| FBA 危险品计划：2.1/2.2/3/4.1/5.1/5.2/6.1/8/9 类须加入计划且按有限数量包装，仅地面运输 [SRC-US-AMZ-G201003400] [SRC-US-AMZ-GZLZBQ7W6QZRKWWK] | 加入 FBA 危险品计划（Manage Dangerous Goods Classification > FBA Dangerous Goods program > 申请）；按有限数量（Limited Quantity）要求包装和贴标 | dg_review | R:US-L4-DG-003 |
| 美国站 FBA 不接收能量超限的锂电池：电池 >300 Wh（锂金属 >25 g）、电芯 >60 Wh（锂金属 >5 g） [SRC-US-AMZ-G200383420] | 超过能量上限的锂电池/含锂电池商品不得 FBA | prohibited | R:US-L4-FBALIB-001 |
| FBA 上架/转 FBA 时必须填写电池与危险品信息；锂电池须上传 UN38.3 测试摘要、自证荷电状态 <30%；SDS/豁免表须满足格式要求 [SRC-US-AMZ-G201371860] [SRC-US-AMZ-G200383420] [SRC-US-AMZ-G201749580] [SRC-US-AMZ-GHLPCM24G965CHSK] [SRC-US-AMZ-G200525640] | 电池/危险品信息属性（含 Wh、锂含量、包装方式、SoC<30% 自证）；UN 38.3 测试摘要（锂电池，ASIN 设置时上传）；SDS（5 年内、GHS、16 节、名称品牌一致）或亚马逊 Excel 豁免表 | dg_review | R:US-L4-DGDOC-001 |
| FBA 有效期商品：入仓剩余保质期须 ≥ 消耗周期 + 90 天（婴儿配方 180 天），须正确设置有效期属性和日期标签 [SRC-US-AMZ-G201003420] | 商品及外箱到期日/生产日期标签（可食用品必须；医疗器械 YYYY-MM-DD）；ASIN 有效期属性（Is Expiration Dated Product、Product Expiration Type、FC Shelf Life）；STA 录入到期日与实物一致 | — | R:US-L4-FBAEXP-001 |
| FBA 易融商品（巧克力、软糖、蛋白棒、果冻/蜡基商品）受季节性入仓限制 [SRC-US-AMZ-G202125070] | 按易融季节安排入仓/移除；如被误列须提交制造商耐温声明信 | — | R:US-L4-FBAMELT-001 |

#### D.5 其他层级规则中标注的 FBA 限制

| 规则主题 | FBA 处理 | 规则ID |
| --- | --- | --- |
| 圆柱形可充电锂电池（18650/21700/26650 等）及含此类电池的产品禁售 | prohibited | R:US-L1-BATT-001 |
| 枪支弹药及弹药部件禁售（子弹、霰弹、底火、火药、弹壳、空包弹） | prohibited | R:US-L1-WEAPON-001 |
| 爆炸物禁售（烟花、信号弹及发射器、手榴弹/烟雾弹、地雷、IED 训练器材、爆炸性材料） | prohibited | R:US-L1-WEAPON-002 |
| 危险化学品禁售（四氯化碳、氢氟酸、硝酸、叠氮化钠、乙醇胺、红磷、铝热剂、氰化物、>12% 过氧化氢、仅限工业用途化学品） | prohibited | R:US-L1-HAZ-002 |
| 烟火类小商品禁售（拉炮/礼花筒、摔炮、仙女棒、玩具枪火药纸、引信、闪光纸、爆炸靶、道路信号弹、汽油）及爆炸物制作信息 | prohibited | R:US-L1-HAZ-003 |
| 汞及含汞产品禁售（体温计、温控器、血压计、汞开关、新奇玩具/首饰等） | prohibited | R:US-L1-HAZ-005 |
| 消耗臭氧层物质（R-12、R-22 等）、仅限持证技师的替代制冷剂、列管 HFC（R-32、R-125、R-134a、R-410A 等）禁售 | prohibited | R:US-L1-REFRIG-001 |
| 随处可划火柴（strike anywhere）及含此类火柴的套装禁售 | prohibited | R:US-L1-MATCH-001 |
| 凝胶燃料和液体燃料火盆、壁炉（含酒精壁炉）全球禁售 | prohibited | R:US-L1-FIREPIT-001 |
| 处方（Rx）和专业用医疗器械只能通过受邀制 Professional Healthcare 项目销售，且不得 FBA | prohibited | R:US-L2-MED-003 |
| 生鲜农产品/冷藏冷冻食品须第三方食品安全审核（经 Azzule 提交）且不可 FBA；饮料须履行各州容器押金义务 | prohibited | R:US-L2-FOODSAFE-001 |

### F. 标签、语言与本地责任人（亚马逊要求部分）

当地法规层面的标签要求（FPLA、FTC 纺织品标签、原产地标记等）见另一份 L5/L6 文档；下表只列亚马逊政策页明确要求的内容。

| 要求 | 适用商品 | 亚马逊具体要求 | 来源 / 规则 |
| --- | --- | --- | --- |
| 英文标签 | 所有提交合规资料的商品 | 说明书、安全信息、标签、警示语须为销售国语言（美国为英语）；图片须展示产品/包装所有面 | [SRC-US-AMZ-GFYECKCN9TSQ8H5B] [R:US-L3-COMPLIANCE-001] |
| 英文 FDA/USDA 食品标签 | 食品饮料 | 包装上若有其他语言，强制标示项仍须有英文；名称、净含量、责任方（非制造商写 "manufactured for/distributed by"）、成分、过敏原、营养成分表、准确原产国；USDA 检验肉品须有检验标志和工厂编号 | [SRC-US-AMZ-G200164550] [R:US-L3-FOOD-009] |
| MoCRA 化妆品标签 | 化妆品、护肤护发、牙膏 | 英文标签须含美国地址/电话/网站或邮箱（用于不良事件报告）、成分表、美制净含量、产品属性声明、警示和香料过敏原 | [SRC-US-AMZ-G200164470] [R:US-L3-COSM-007] |
| Supplement Facts | 膳食补充剂 | 贴在产品上的完整英文标签、批号/序列号、品牌方/制造商/包装商/经销商名称地址；不得有 FDA 标志 | [SRC-US-AMZ-G201829010] [R:US-L3-SUPP-010] |
| Drug Facts 与 NDC | OTC 药品 | Drug Facts 面板；口服 OTC 须在产品和包装上永久印 NDC 号；儿童防护盖和防篡改包装 | [SRC-US-AMZ-G200164490] [R:US-L3-DRUG-010] [R:US-L2-DRUG-011] |
| 医疗器械 UDI | 医疗器械 | 英文 FDA 标签含 UDI、责任方完整地址、用途、批号、有效期；不得使用覆盖贴标（over-label） | [SRC-US-AMZ-G200164650] [R:US-L3-MED-005] |
| 追踪标签 | 所有儿童产品 | 产品和包装永久标注制造商/进口商/自有品牌商或品牌、生产地点和日期、批次等；标签上的制造商可为境外实体 | [SRC-US-AMZ-GN9YK5Y7TYGRGNRG] [R:US-L3-CPSC-002] |
| 注册卡 | 耐用婴幼儿产品 | 邮资已付、全英文、≥3.5×5 英寸、含美国联系方式（注册卡要求页写“U.S. address and telephone number”）；亚马逊不能作为责任方 | [SRC-US-AMZ-GN9YK5Y7TYGRGNRG] [SRC-US-AMZ-GFYECKCN9TSQ8H5B] [R:US-L3-CPSC-002] |
| CPC/GCC 的认证方 | 儿童产品/受 CPSC 监管的产品 | 由美国进口商或国内制造商出具；进口商可以是境外实体；亚马逊不能被列为进口商、记录保存人或其他责任方 | [SRC-US-AMZ-GSGB43AFZNDWD4U8] [R:US-L3-CPSC-001] |
| 美国责任方 | 走 SDoC 的射频设备 | 声称按 SDoC 授权但在美国没有合规责任方的设备禁售 | [SRC-US-AMZ-GHXJGN6T5K8HGGWW] [R:US-L1-RF-001] |
| 美国居民身份 | 农药/农药器械、植物种子 | 只允许美国居民销售；植物种子不得从境外进口 | [SRC-US-AMZ-G202115120] [SRC-US-AMZ-G201737480] [R:US-L1-PEST-001] [R:US-L1-PLANT-001] |
| 制造商/进口商签署 | 轮胎、轮毂 | 亚马逊 FMVSS 合规证书由制造商授权代表签署，境外制造商可由制造商或记录进口商（IoR）签署 | [SRC-US-AMZ-GJQMR3AUDBH6RXR5] [R:US-L3-TIRE-002] |
| 卖家信息披露 | 高销量卖家 | INFORM 法：身份、地址、银行、税号核验并每年认证；名称地址展示在卖家资料页 | [SRC-US-AMZ-GJ4JUGLSAPRM3LU7] [R:US-L3-INFORM-001] |
| 原产地宣称 | 全部 | “Made in USA” 须符合 FTC 标准并可能需提交合规声明；“意大利制造”实为仅组装属误导 | [SRC-US-AMZ-G202024200] [R:US-L2-CLAIM-003] [R:US-L2-CLAIM-002] |
| 发货标签 | 动物制品、植物种子 | 每批发货标明发货人、收货人、来源地、内容物；运往加州的植物须醒目标注 | [SRC-US-AMZ-G200164370] [SRC-US-AMZ-G201737480] [R:US-L3-ANIMAL-013] [R:US-L3-PLANT-004] |
| 警示语 | 玩具、电池、焕肤产品、激光 | CPSIA 窒息警示；锂电池 “WARNING: Risk of Fire and Burns” 等；Reese 法纽扣电池警示；AHA/BHA 晒伤警示；激光分级与警示标签 | [R:US-L3-CPSC-003] [R:US-L3-BATT-003] [R:US-L3-BATT-005] [R:US-L1-COSM-003] [R:US-L3-LASER-003] |


### G. 2024–2026 亚马逊政策变化与生效日期

只列亚马逊页面上能看到日期的变化；“页面未注明日期”的近期变化单列。法规本身的生效日期（如 Reese 法、MoCRA、ASTM F963-23）见 L5 文档。

| 日期 | 变化 | 影响的产品 | 规则ID | 来源 |
| --- | --- | --- | --- | --- |
| 2023-02-06（持续执行） | FCC“受管控清单”设备不得获设备授权，亚马逊据此禁售 | 华为、中兴、海康、大华、海能达等受管控设备 | R:US-L1-RF-001 | [SRC-US-AMZ-GHXJGN6T5K8HGGWW] |
| 2023-06-27（持续执行） | INFORM 消费者法：高销量卖家信息核验与年度认证 | 所有高销量卖家 | R:US-L3-INFORM-001 | [SRC-US-AMZ-GJ4JUGLSAPRM3LU7] |
| 2024-03-01 | 开锁与盗窃工具页更新 | 开锁工具、解码器、万能钥匙 | R:US-L1-LOCK-001 | [SRC-US-AMZ-G200164850] |
| 2024-11-08 | 爆炸物、武器及相关物品页更新（枪械配件、刀具清单） | 枪械配件、刀具、防身用品 | R:US-L1-WEAPON-001…012 | [SRC-US-AMZ-G200164950] |
| 2024 年底 | 消费品类商品捆绑须为制造商/品牌原装组合 | 消费品捆绑 | R:US-L2-BUNDLE-001 | [SRC-US-AMZ-GQHQGBTD7XB7EECN] |
| 2025-01-21 | 照明页更新（通用照明灯 45 lm/W） | 灯泡 | R:US-L1-LIGHT-001 | [SRC-US-AMZ-G201997070] |
| 2025-03-28 | 动物及动物制品页更新（加州皮草、鹅肝等） | 皮草、动物制品 | R:US-L2-ANIMAL-010 | [SRC-US-AMZ-G200164370] |
| 2025-04-30 | 低价商品店铺政策改名为 Amazon Haul 计划政策并扩展到更多国家 | Haul 商品 | 见 HAUL 规则 | [SRC-US-AMZ-GQHQGBTD7XB7EECN] |
| 2025-06-30 | 新设独立“赃物政策”（禁止销售赃物，须保留合法供应链文件） | 全部 | —（账户政策） | [SRC-US-AMZ-GQHQGBTD7XB7EECN] |
| 2025-07-17 | 邮资页更新：USPS 国旗永久邮票受限 | 邮票 | R:US-L1-POSTAGE-001 | [SRC-US-AMZ-G200164730] |
| 2025-10-24 | 制冷剂页更新（ODS、替代品、列管 HFC、州 HFC 法） | 制冷剂、含 HFC 产品 | R:US-L1-REFRIG-001、R:US-L2-REFRIG-002 | [SRC-US-AMZ-G5ER6LTGH2GFJLHQ] |
| 2026-01-06 | TSCA：受管制 PBT 物质、含 PCE 手工胶禁售 | 化学品、胶粘剂 | R:US-L1-TSCA-001 | [SRC-US-AMZ-GNPGY2ZEUMKSA62F] |
| 2026-07-15 | 服务与保修政策更新：只有受邀个人或实体可向买家提供服务，禁售示例扩充 | 延保、安装服务 | R:US-L1-WARRANTY-001 | [SRC-US-AMZ-GQHQGBTD7XB7EECN] |
| 2026-07-27 | 商品名称上限改为 75 字符，新增 125 字符“商品亮点”属性（媒介类除外） | 全部 Listing | —（详情页规则） | [SRC-US-AMZ-GQHQGBTD7XB7EECN] |
| 2026-09-30 | 商品捆绑政策扩展至大多数类目 | 捆绑商品 | R:US-L2-BUNDLE-001 | [SRC-US-AMZ-GQHQGBTD7XB7EECN] |
| **2026-11-02（未来）** | 商业责任险新规：强化安全类目不论销售额都须投保；中国大陆卖家须经亚马逊保险加速器（AIA）投保 | 强化安全 11 组类目；全部中国大陆卖家 | R:US-L2-INSURANCE-002、R:US-L2-ENHANCED-001 | [SRC-US-AMZ-G200386300] |
| **2027-03-08（未来）** | TSCA：含四氯乙烯（PCE）的产品禁售 | 刹车清洗剂、除油剂、点渍剂等 | R:US-L1-TSCA-002 | [SRC-US-AMZ-GNPGY2ZEUMKSA62F] |
| **2028-09-05（未来）** | 电动切割工具须符合 UL 62841 系列 | 电锯、角磨等电动切割工具 | R:US-L3-CUTTOOL-002 | [SRC-US-AMZ-G47MZUS764W88ZRP] |

页面未注明日期、但属近期新增或强化的要求（建议在实际经营中以账户状况通知为准）：
- 圆柱形可充电锂电池及含此类电池产品全面禁售 [R:US-L1-BATT-001]。
- 强化安全上架要求类目（11 组）：100 万美元产品责任险 + 授权 TIC 直接验证 + 持续抽检 [R:US-L2-ENHANCED-001] [R:US-L2-ENHANCED-002]。
- “Direct product validation”：补充剂、口服 OTC、美白产品、玩具、锂电池、激光等改由授权 TIC 代交文件，不再直接交给亚马逊 [SRC-US-AMZ-GUTZ2R2DD6P2UMVB]。
- 儿童玩具政策引用 ASTM F963-23；化妆品政策引用 MoCRA（设施注册和产品列名 FDA 5066/5067）[R:US-L3-TOY-001] [R:US-L3-COSM-009]。

### H. 来源清单

本文及规则引用的全部来源（亚马逊卖家平台帮助页均为 S1，访问日期 2026-10-10；快照存于 policy/snapshots/US/）。

| 来源ID | 标题 | URL | 级别 | 访问日期 |
| --- | --- | --- | --- | --- |
| SRC-US-AMZ-G200140860 | FBA product restrictions | https://sellercentral.amazon.com/help/hub/reference/external/G200140860 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200164330 | Restricted products | https://sellercentral.amazon.com/help/hub/reference/external/G200164330 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200164340 | Alcohol | https://sellercentral.amazon.com/help/hub/reference/external/G200164340 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200164370 | Animals and animal-related products | https://sellercentral.amazon.com/help/hub/reference/external/G200164370 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200164390 | Art - Home Decor | https://sellercentral.amazon.com/help/hub/reference/external/G200164390 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200164410 | Automotive and powersports | https://sellercentral.amazon.com/help/hub/reference/external/G200164410 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200164450 | Currency, Coins, Cash Equivalents, and Gift Cards | https://sellercentral.amazon.com/help/hub/reference/external/G200164450 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200164470 | Cosmetics, skin, and hair care | https://sellercentral.amazon.com/help/hub/reference/external/G200164470 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200164490 | Drugs and drug paraphernalia | https://sellercentral.amazon.com/help/hub/reference/external/G200164490 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200164510 | Electronics | https://sellercentral.amazon.com/help/hub/reference/external/G200164510 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200164550 | Food and beverages | https://sellercentral.amazon.com/help/hub/reference/external/G200164550 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200164570 | Hazardous and prohibited items | https://sellercentral.amazon.com/help/hub/reference/external/G200164570 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200164590 | Human Parts & Burial Artifacts | https://sellercentral.amazon.com/help/hub/reference/external/G200164590 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200164650 | Medical devices and accessories | https://sellercentral.amazon.com/help/hub/reference/external/G200164650 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200164670 | Offensive and controversial materials | https://sellercentral.amazon.com/help/hub/reference/external/G200164670 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200164730 | Postage meters and stamps | https://sellercentral.amazon.com/help/hub/reference/external/G200164730 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200164750 | Recalled products | https://sellercentral.amazon.com/help/hub/reference/external/G200164750 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200164850 | Lock picking and theft devices | https://sellercentral.amazon.com/help/hub/reference/external/G200164850 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200164870 | Surveillance Equipment | https://sellercentral.amazon.com/help/hub/reference/external/G200164870 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200164910 | Tobacco and tobacco-related products | https://sellercentral.amazon.com/help/hub/reference/external/G200164910 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200164930 | Warranties, Service Plans, Contracts, Services, and Guarantees | https://sellercentral.amazon.com/help/hub/reference/external/G200164930 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200164950 | Explosives, weapons, and related items | https://sellercentral.amazon.com/help/hub/reference/external/G200164950 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200166630 | Jewelry and precious gems | https://sellercentral.amazon.com/help/hub/reference/external/G200166630 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200292910 | CPSIA cautionary statements | https://sellercentral.amazon.com/help/hub/reference/external/G200292910 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200301050 | Category, product, and listing restrictions | https://sellercentral.amazon.com/help/hub/reference/external/G200301050 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200316090 | Watches | https://sellercentral.amazon.com/help/hub/reference/external/G200316090 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200316920 | Clothing & Accessories | https://sellercentral.amazon.com/help/hub/reference/external/G200316920 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200332590 | Jewelry | https://sellercentral.amazon.com/help/hub/reference/external/G200332590 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200333160 | Categories and products that require approval | https://sellercentral.amazon.com/help/hub/reference/external/G200333160 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200339940 | Adult products, sexual wellness products and content guidelines | https://sellercentral.amazon.com/help/hub/reference/external/G200339940 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200383420 | Requirements for lithium batteries and products powered by lithium batteries | https://sellercentral.amazon.com/help/hub/reference/external/G200383420 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200386300 | Commercial Liability Insurance Requirements | https://sellercentral.amazon.com/help/hub/reference/external/G200386300 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200500100 | Amazon Device Accessories Policy | https://sellercentral.amazon.com/help/hub/reference/external/G200500100 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200525640 | 可能的危险品示例 | https://sellercentral.amazon.com/help/hub/reference/external/G200525640 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200685250 | Gambling and lottery | https://sellercentral.amazon.com/help/hub/reference/external/G200685250 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200685320 | Other restricted products | https://sellercentral.amazon.com/help/hub/reference/external/G200685320 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200800780 | Sports Collectibles | https://sellercentral.amazon.com/help/hub/reference/external/G200800780 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200832300 | Listing restrictions | https://sellercentral.amazon.com/help/hub/reference/external/G200832300 | S1 | 2026-10-10 |
| SRC-US-AMZ-G200944120 | Entertainment Collectibles | https://sellercentral.amazon.com/help/hub/reference/external/G200944120 | S1 | 2026-10-10 |
| SRC-US-AMZ-G201003400 | Dangerous goods identification guide (hazmat) | https://sellercentral.amazon.com/help/hub/reference/external/G201003400 | S1 | 2026-10-10 |
| SRC-US-AMZ-G201003420 | Expiration dates on FBA products | https://sellercentral.amazon.com/help/hub/reference/external/G201003420 | S1 | 2026-10-10 |
| SRC-US-AMZ-G201257400 | Fine Art | https://sellercentral.amazon.com/help/hub/reference/external/G201257400 | S1 | 2026-10-10 |
| SRC-US-AMZ-G201279060 | Art - Fine Art | https://sellercentral.amazon.com/help/hub/reference/external/G201279060 | S1 | 2026-10-10 |
| SRC-US-AMZ-G201371860 | Dangerous goods (hazmat) required information and documentation | https://sellercentral.amazon.com/help/hub/reference/external/G201371860 | S1 | 2026-10-10 |
| SRC-US-AMZ-G201526800 | Collectible Coins | https://sellercentral.amazon.com/help/hub/reference/external/G201526800 | S1 | 2026-10-10 |
| SRC-US-AMZ-G201575280 | Trade control laws | https://sellercentral.amazon.com/help/hub/reference/external/G201575280 | S1 | 2026-10-10 |
| SRC-US-AMZ-G201607580 | Video, DVD, & Blu-ray | https://sellercentral.amazon.com/help/hub/reference/external/G201607580 | S1 | 2026-10-10 |
| SRC-US-AMZ-G201613540 | Services | https://sellercentral.amazon.com/help/hub/reference/external/G201613540 | S1 | 2026-10-10 |
| SRC-US-AMZ-G201689020 | Laser products | https://sellercentral.amazon.com/help/hub/reference/external/G201689020 | S1 | 2026-10-10 |
| SRC-US-AMZ-G201707070 | General Listing Restrictions | https://sellercentral.amazon.com/help/hub/reference/external/G201707070 | S1 | 2026-10-10 |
| SRC-US-AMZ-G201707090 | Listing restrictions that require statements or disclosures | https://sellercentral.amazon.com/help/hub/reference/external/G201707090 | S1 | 2026-10-10 |
| SRC-US-AMZ-G201730840 | FBA prohibited products | https://sellercentral.amazon.com/help/hub/reference/external/G201730840 | S1 | 2026-10-10 |
| SRC-US-AMZ-G201737480 | Plant and seed products | https://sellercentral.amazon.com/help/hub/reference/external/G201737480 | S1 | 2026-10-10 |
| SRC-US-AMZ-G201749580 | Dangerous goods review process (hazmat) | https://sellercentral.amazon.com/help/hub/reference/external/G201749580 | S1 | 2026-10-10 |
| SRC-US-AMZ-G201814570 | Energy Labeling Rule | https://sellercentral.amazon.com/help/hub/reference/external/G201814570 | S1 | 2026-10-10 |
| SRC-US-AMZ-G201829010 | Dietary supplements | https://sellercentral.amazon.com/help/hub/reference/external/G201829010 | S1 | 2026-10-10 |
| SRC-US-AMZ-G201997070 | Lighting | https://sellercentral.amazon.com/help/hub/reference/external/G201997070 | S1 | 2026-10-10 |
| SRC-US-AMZ-G202024200 | Misleading and prohibited claims | https://sellercentral.amazon.com/help/hub/reference/external/G202024200 | S1 | 2026-10-10 |
| SRC-US-AMZ-G202082160 | California Air Resources Board (CARB) | https://sellercentral.amazon.com/help/hub/reference/external/G202082160 | S1 | 2026-10-10 |
| SRC-US-AMZ-G202089380 | Recycling electronics | https://sellercentral.amazon.com/help/hub/reference/external/G202089380 | S1 | 2026-10-10 |
| SRC-US-AMZ-G202115120 | Pest control products and pesticides | https://sellercentral.amazon.com/help/hub/reference/external/G202115120 | S1 | 2026-10-10 |
| SRC-US-AMZ-G202125070 | Meltable FBA inventory | https://sellercentral.amazon.com/help/hub/reference/external/G202125070 | S1 | 2026-10-10 |
| SRC-US-AMZ-G202137200 | Child restraint systems, booster seats, and travel systems | https://sellercentral.amazon.com/help/hub/reference/external/G202137200 | S1 | 2026-10-10 |
| SRC-US-AMZ-G202137960 | String lights and rope lights | https://sellercentral.amazon.com/help/hub/reference/external/G202137960 | S1 | 2026-10-10 |
| SRC-US-AMZ-G202155900 | Fidget spinners | https://sellercentral.amazon.com/help/hub/reference/external/G202155900 | S1 | 2026-10-10 |
| SRC-US-AMZ-G202156120 | Device batteries and chargers | https://sellercentral.amazon.com/help/hub/reference/external/G202156120 | S1 | 2026-10-10 |
| SRC-US-AMZ-G202162990 | Personal flotation devices | https://sellercentral.amazon.com/help/hub/reference/external/G202162990 | S1 | 2026-10-10 |
| SRC-US-AMZ-G202171660 | Eclipse glasses and solar viewing filters | https://sellercentral.amazon.com/help/hub/reference/external/G202171660 | S1 | 2026-10-10 |
| SRC-US-AMZ-G202183590 | Streaming Media Players | https://sellercentral.amazon.com/help/hub/reference/external/G202183590 | S1 | 2026-10-10 |
| SRC-US-AMZ-G202188990 | Music & DVD | https://sellercentral.amazon.com/help/hub/reference/external/G202188990 | S1 | 2026-10-10 |
| SRC-US-AMZ-G2HSXA2KM59YX5AT | Cylindrical rechargeable lithium batteries | https://sellercentral.amazon.com/help/hub/reference/external/G2HSXA2KM59YX5AT | S1 | 2026-10-10 |
| SRC-US-AMZ-G2JX2MAWJ27DWAY6 | Compliance Reference | https://sellercentral.amazon.com/help/hub/reference/external/G2JX2MAWJ27DWAY6 | S1 | 2026-10-10 |
| SRC-US-AMZ-G424NXBNPK995GST | Toddler beds | https://sellercentral.amazon.com/help/hub/reference/external/G424NXBNPK995GST | S1 | 2026-10-10 |
| SRC-US-AMZ-G47MZUS764W88ZRP | Electric cutting tools | https://sellercentral.amazon.com/help/hub/reference/external/G47MZUS764W88ZRP | S1 | 2026-10-10 |
| SRC-US-AMZ-G4EX3SEAAQRMLKN8 | Male and female condoms | https://sellercentral.amazon.com/help/hub/reference/external/G4EX3SEAAQRMLKN8 | S1 | 2026-10-10 |
| SRC-US-AMZ-G4QUDFLRX8GBFPVV | Product safety investigations | https://sellercentral.amazon.com/help/hub/reference/external/G4QUDFLRX8GBFPVV | S1 | 2026-10-10 |
| SRC-US-AMZ-G4RUG6EAT2ZLVSRT | Product categories with enhanced safety listing requirements | https://sellercentral.amazon.com/help/hub/reference/external/G4RUG6EAT2ZLVSRT | S1 | 2026-10-10 |
| SRC-US-AMZ-G4SX7HDHVCGK33UD | Carriages and strollers | https://sellercentral.amazon.com/help/hub/reference/external/G4SX7HDHVCGK33UD | S1 | 2026-10-10 |
| SRC-US-AMZ-G4UEALPJHSP85VRX | Trampolines | https://sellercentral.amazon.com/help/hub/reference/external/G4UEALPJHSP85VRX | S1 | 2026-10-10 |
| SRC-US-AMZ-G52LHU99LA38NLU7 | Mountaineering carabiners | https://sellercentral.amazon.com/help/hub/reference/external/G52LHU99LA38NLU7 | S1 | 2026-10-10 |
| SRC-US-AMZ-G5ER6LTGH2GFJLHQ | Refrigerants: Ozone-depleting substances and substitutes | https://sellercentral.amazon.com/help/hub/reference/external/G5ER6LTGH2GFJLHQ | S1 | 2026-10-10 |
| SRC-US-AMZ-G5NGAYYZAY559SCZ | Children's sleepwear | https://sellercentral.amazon.com/help/hub/reference/external/G5NGAYYZAY559SCZ | S1 | 2026-10-10 |
| SRC-US-AMZ-G5P5YMQXX9Y34NVU | Gel and liquid fuel burning fire pits and fireplaces | https://sellercentral.amazon.com/help/hub/reference/external/G5P5YMQXX9Y34NVU | S1 | 2026-10-10 |
| SRC-US-AMZ-G5QJSTMF6TLDXW53 | Emergency contraceptives | https://sellercentral.amazon.com/help/hub/reference/external/G5QJSTMF6TLDXW53 | S1 | 2026-10-10 |
| SRC-US-AMZ-G5YG8BBQQ9JQ4ZPD | Infant swings | https://sellercentral.amazon.com/help/hub/reference/external/G5YG8BBQQ9JQ4ZPD | S1 | 2026-10-10 |
| SRC-US-AMZ-G6676M3NTXR26CAY | Ski and snowboard helmets | https://sellercentral.amazon.com/help/hub/reference/external/G6676M3NTXR26CAY | S1 | 2026-10-10 |
| SRC-US-AMZ-G6DYF8YUYEV5H6AY | Non-full-size cribs | https://sellercentral.amazon.com/help/hub/reference/external/G6DYF8YUYEV5H6AY | S1 | 2026-10-10 |
| SRC-US-AMZ-G6VSU6Q86RKZKEZW | Ophthalmic drug products | https://sellercentral.amazon.com/help/hub/reference/external/G6VSU6Q86RKZKEZW | S1 | 2026-10-10 |
| SRC-US-AMZ-G6WCA7BRX5QWHMNF | Portable automotive jump starters | https://sellercentral.amazon.com/help/hub/reference/external/G6WCA7BRX5QWHMNF | S1 | 2026-10-10 |
| SRC-US-AMZ-G76DURDA6ZW48DX7 | Baby or toddler feeding furniture | https://sellercentral.amazon.com/help/hub/reference/external/G76DURDA6ZW48DX7 | S1 | 2026-10-10 |
| SRC-US-AMZ-G7HM69VDEMRW7TPE | Electronic mobility (e-mobility) accessories | https://sellercentral.amazon.com/help/hub/reference/external/G7HM69VDEMRW7TPE | S1 | 2026-10-10 |
| SRC-US-AMZ-G7L7RKBERYDEJ8QQ | Clothing storage units | https://sellercentral.amazon.com/help/hub/reference/external/G7L7RKBERYDEJ8QQ | S1 | 2026-10-10 |
| SRC-US-AMZ-G7PAP6BJAUXRM4LH | Lithium batteries | https://sellercentral.amazon.com/help/hub/reference/external/G7PAP6BJAUXRM4LH | S1 | 2026-10-10 |
| SRC-US-AMZ-G7PNYFCP46WHA3RL | California Energy Commission (CEC) | https://sellercentral.amazon.com/help/hub/reference/external/G7PNYFCP46WHA3RL | S1 | 2026-10-10 |
| SRC-US-AMZ-G8FDB4PSHS4AACQ5 | Children's upper clothing with drawstrings | https://sellercentral.amazon.com/help/hub/reference/external/G8FDB4PSHS4AACQ5 | S1 | 2026-10-10 |
| SRC-US-AMZ-G8TM22XFM7WXCRDC | Lithium battery powered home appliances | https://sellercentral.amazon.com/help/hub/reference/external/G8TM22XFM7WXCRDC | S1 | 2026-10-10 |
| SRC-US-AMZ-G8V5URH2QPKMY3NS | Upholstered furniture, bedding, and other quilted products | https://sellercentral.amazon.com/help/hub/reference/external/G8V5URH2QPKMY3NS | S1 | 2026-10-10 |
| SRC-US-AMZ-G92A8N8UP4W8C4JQ | HEPA claims for air purifiers and replacement air filters | https://sellercentral.amazon.com/help/hub/reference/external/G92A8N8UP4W8C4JQ | S1 | 2026-10-10 |
| SRC-US-AMZ-G9RST2AGVGCW6ZCT | TV antennas with misleading range claims | https://sellercentral.amazon.com/help/hub/reference/external/G9RST2AGVGCW6ZCT | S1 | 2026-10-10 |
| SRC-US-AMZ-GA2PQDTU5HMC7CRZ | Lithium battery powered smart home devices and consumer electronics | https://sellercentral.amazon.com/help/hub/reference/external/GA2PQDTU5HMC7CRZ | S1 | 2026-10-10 |
| SRC-US-AMZ-GAMHBVRVCE4UNKPG | Infant bath tubs | https://sellercentral.amazon.com/help/hub/reference/external/GAMHBVRVCE4UNKPG | S1 | 2026-10-10 |
| SRC-US-AMZ-GAPBV3UDXPHP3C42 | Mountaineering helmets | https://sellercentral.amazon.com/help/hub/reference/external/GAPBV3UDXPHP3C42 | S1 | 2026-10-10 |
| SRC-US-AMZ-GBG6Z6TKMZHXQU7X | Adult portable bed rails | https://sellercentral.amazon.com/help/hub/reference/external/GBG6Z6TKMZHXQU7X | S1 | 2026-10-10 |
| SRC-US-AMZ-GBSYAXLHERCMCSQW | Mattresses | https://sellercentral.amazon.com/help/hub/reference/external/GBSYAXLHERCMCSQW | S1 | 2026-10-10 |
| SRC-US-AMZ-GBVSAAJFBSKYNT8Q | Bicycles | https://sellercentral.amazon.com/help/hub/reference/external/GBVSAAJFBSKYNT8Q | S1 | 2026-10-10 |
| SRC-US-AMZ-GC277GB53473J65C | Abrasive kite strings | https://sellercentral.amazon.com/help/hub/reference/external/GC277GB53473J65C | S1 | 2026-10-10 |
| SRC-US-AMZ-GC35Z63FGCUCUWXX | Submit compliance information or an appeal | https://sellercentral.amazon.com/help/hub/reference/external/GC35Z63FGCUCUWXX | S1 | 2026-10-10 |
| SRC-US-AMZ-GC37KSM44NPNZED6 | Skin-lightening products | https://sellercentral.amazon.com/help/hub/reference/external/GC37KSM44NPNZED6 | S1 | 2026-10-10 |
| SRC-US-AMZ-GCEQ79CVX6XPVK4B | Pressure washers | https://sellercentral.amazon.com/help/hub/reference/external/GCEQ79CVX6XPVK4B | S1 | 2026-10-10 |
| SRC-US-AMZ-GCF2U4MHLT5D82H8 | Children’s bicycle helmets | https://sellercentral.amazon.com/help/hub/reference/external/GCF2U4MHLT5D82H8 | S1 | 2026-10-10 |
| SRC-US-AMZ-GCJU83NDQS8JX26Q | Walkers and rollators | https://sellercentral.amazon.com/help/hub/reference/external/GCJU83NDQS8JX26Q | S1 | 2026-10-10 |
| SRC-US-AMZ-GD646NUBNNJLQADP | Expiration dates on seller-fulfilled products | https://sellercentral.amazon.com/help/hub/reference/external/GD646NUBNNJLQADP | S1 | 2026-10-10 |
| SRC-US-AMZ-GDPSRCGVBFSFY78H | Baby teething products | https://sellercentral.amazon.com/help/hub/reference/external/GDPSRCGVBFSFY78H | S1 | 2026-10-10 |
| SRC-US-AMZ-GDQ28DB2X4NV6872 | Magnification claims | https://sellercentral.amazon.com/help/hub/reference/external/GDQ28DB2X4NV6872 | S1 | 2026-10-10 |
| SRC-US-AMZ-GDQULCAPUQQ9D9Z8 | Gas-fueled outdoor heating products | https://sellercentral.amazon.com/help/hub/reference/external/GDQULCAPUQQ9D9Z8 | S1 | 2026-10-10 |
| SRC-US-AMZ-GEENN56JW9QU8MJS | Strike anywhere matches | https://sellercentral.amazon.com/help/hub/reference/external/GEENN56JW9QU8MJS | S1 | 2026-10-10 |
| SRC-US-AMZ-GEJ6L4MMBHVZGLND | Toothpick crossbows | https://sellercentral.amazon.com/help/hub/reference/external/GEJ6L4MMBHVZGLND | S1 | 2026-10-10 |
| SRC-US-AMZ-GEJBWFAU7W5MC3ZA | Portable fuel containers | https://sellercentral.amazon.com/help/hub/reference/external/GEJBWFAU7W5MC3ZA | S1 | 2026-10-10 |
| SRC-US-AMZ-GEU8B9UPLKJHKU9G | Washington State expanded polystyrene | https://sellercentral.amazon.com/help/hub/reference/external/GEU8B9UPLKJHKU9G | S1 | 2026-10-10 |
| SRC-US-AMZ-GF37SYYLMCRJZ35Q | Infant support cushions and nursing pillows | https://sellercentral.amazon.com/help/hub/reference/external/GF37SYYLMCRJZ35Q | S1 | 2026-10-10 |
| SRC-US-AMZ-GFEUQFB9X4YWFVXD | Water beads | https://sellercentral.amazon.com/help/hub/reference/external/GFEUQFB9X4YWFVXD | S1 | 2026-10-10 |
| SRC-US-AMZ-GFQMECECLTJCUE3H | Battery-operated heated apparel and insoles | https://sellercentral.amazon.com/help/hub/reference/external/GFQMECECLTJCUE3H | S1 | 2026-10-10 |
| SRC-US-AMZ-GFUE3CNVCTY84VUG | Children’s folding and non-folding chairs and stools | https://sellercentral.amazon.com/help/hub/reference/external/GFUE3CNVCTY84VUG | S1 | 2026-10-10 |
| SRC-US-AMZ-GFVTL7E262KFAAXC | Plumbing fittings and fixtures | https://sellercentral.amazon.com/help/hub/reference/external/GFVTL7E262KFAAXC | S1 | 2026-10-10 |
| SRC-US-AMZ-GFYECKCN9TSQ8H5B | Product compliance documentation | https://sellercentral.amazon.com/help/hub/reference/external/GFYECKCN9TSQ8H5B | S1 | 2026-10-10 |
| SRC-US-AMZ-GGB3K8RJ6ZEB8QQ6 | Fire and smoke masks | https://sellercentral.amazon.com/help/hub/reference/external/GGB3K8RJ6ZEB8QQ6 | S1 | 2026-10-10 |
| SRC-US-AMZ-GGLAL34T93UJQ6KD | Baby carriers | https://sellercentral.amazon.com/help/hub/reference/external/GGLAL34T93UJQ6KD | S1 | 2026-10-10 |
| SRC-US-AMZ-GGS4MAMUUG4K5TJN | Mouth tape | https://sellercentral.amazon.com/help/hub/reference/external/GGS4MAMUUG4K5TJN | S1 | 2026-10-10 |
| SRC-US-AMZ-GGUXTDB7TLY6F5LE | Electric space heaters | https://sellercentral.amazon.com/help/hub/reference/external/GGUXTDB7TLY6F5LE | S1 | 2026-10-10 |
| SRC-US-AMZ-GGYR8DS2R8Q7R2SF | Infant walkers | https://sellercentral.amazon.com/help/hub/reference/external/GGYR8DS2R8Q7R2SF | S1 | 2026-10-10 |
| SRC-US-AMZ-GHFCQ3SCKXWDYZN2 | Baby changing products | https://sellercentral.amazon.com/help/hub/reference/external/GHFCQ3SCKXWDYZN2 | S1 | 2026-10-10 |
| SRC-US-AMZ-GHLPCM24G965CHSK | Maximum allowable quantity limits for dangerous goods | https://sellercentral.amazon.com/help/hub/reference/external/GHLPCM24G965CHSK | S1 | 2026-10-10 |
| SRC-US-AMZ-GHRAUBNDL7K7EZSG | Bicycle helmets | https://sellercentral.amazon.com/help/hub/reference/external/GHRAUBNDL7K7EZSG | S1 | 2026-10-10 |
| SRC-US-AMZ-GHXJGN6T5K8HGGWW | Radio frequency devices | https://sellercentral.amazon.com/help/hub/reference/external/GHXJGN6T5K8HGGWW | S1 | 2026-10-10 |
| SRC-US-AMZ-GJ4JUGLSAPRM3LU7 | About the INFORM Consumers Act | https://sellercentral.amazon.com/help/hub/reference/external/GJ4JUGLSAPRM3LU7 | S1 | 2026-10-10 |
| SRC-US-AMZ-GJFNF3SE7N7ZLE78 | Medical thermometers | https://sellercentral.amazon.com/help/hub/reference/external/GJFNF3SE7N7ZLE78 | S1 | 2026-10-10 |
| SRC-US-AMZ-GJJPTVHXVDA5PAG7 | Children's apparel | https://sellercentral.amazon.com/help/hub/reference/external/GJJPTVHXVDA5PAG7 | S1 | 2026-10-10 |
| SRC-US-AMZ-GJQMR3AUDBH6RXR5 | Automotive tires, wheels, and rims | https://sellercentral.amazon.com/help/hub/reference/external/GJQMR3AUDBH6RXR5 | S1 | 2026-10-10 |
| SRC-US-AMZ-GJS7C6DGM9BD6L4B | Export Controls | https://sellercentral.amazon.com/help/hub/reference/external/GJS7C6DGM9BD6L4B | S1 | 2026-10-10 |
| SRC-US-AMZ-GK652STVCYSPCRUQ | Thread count claims in bed linens | https://sellercentral.amazon.com/help/hub/reference/external/GK652STVCYSPCRUQ | S1 | 2026-10-10 |
| SRC-US-AMZ-GK9K2S3L8J2QJW22 | Children's footwear | https://sellercentral.amazon.com/help/hub/reference/external/GK9K2S3L8J2QJW22 | S1 | 2026-10-10 |
| SRC-US-AMZ-GKDFVJSUHPYTRHW3 | Weighted infant and toddler sleep products | https://sellercentral.amazon.com/help/hub/reference/external/GKDFVJSUHPYTRHW3 | S1 | 2026-10-10 |
| SRC-US-AMZ-GKHQEFBM7834V6AV | Consumer Product Safety Commission (CPSC) regulated products | https://sellercentral.amazon.com/help/hub/reference/external/GKHQEFBM7834V6AV | S1 | 2026-10-10 |
| SRC-US-AMZ-GKJRA3FRPRKVBJJS | Children's toys | https://sellercentral.amazon.com/help/hub/reference/external/GKJRA3FRPRKVBJJS | S1 | 2026-10-10 |
| SRC-US-AMZ-GKJXWS7VY64WZZ7K | Products that require EPA Certificate of Conformity | https://sellercentral.amazon.com/help/hub/reference/external/GKJXWS7VY64WZZ7K | S1 | 2026-10-10 |
| SRC-US-AMZ-GKMN8QPMQ6K8SK3E | Motorcycle helmets | https://sellercentral.amazon.com/help/hub/reference/external/GKMN8QPMQ6K8SK3E | S1 | 2026-10-10 |
| SRC-US-AMZ-GKVBB4SMC8PD3UWJ | Infant bath seats | https://sellercentral.amazon.com/help/hub/reference/external/GKVBB4SMC8PD3UWJ | S1 | 2026-10-10 |
| SRC-US-AMZ-GKY5NBH8EHAUFQ27 | Composite Wood Products | https://sellercentral.amazon.com/help/hub/reference/external/GKY5NBH8EHAUFQ27 | S1 | 2026-10-10 |
| SRC-US-AMZ-GL8P7RSBPB3HS553 | Fall-protection harnesses | https://sellercentral.amazon.com/help/hub/reference/external/GL8P7RSBPB3HS553 | S1 | 2026-10-10 |
| SRC-US-AMZ-GLT9B78P9URHB6TR | Fresh produce | https://sellercentral.amazon.com/help/hub/reference/external/GLT9B78P9URHB6TR | S1 | 2026-10-10 |
| SRC-US-AMZ-GLWWB4Z3M566RGLM | Brightness Claims for Video Projectors | https://sellercentral.amazon.com/help/hub/reference/external/GLWWB4Z3M566RGLM | S1 | 2026-10-10 |
| SRC-US-AMZ-GMFZGW34G9Y5HU75 | Menstrual devices | https://sellercentral.amazon.com/help/hub/reference/external/GMFZGW34G9Y5HU75 | S1 | 2026-10-10 |
| SRC-US-AMZ-GMUW6CKYLY4AP8MK | Electronic mobility (e-mobility) devices | https://sellercentral.amazon.com/help/hub/reference/external/GMUW6CKYLY4AP8MK | S1 | 2026-10-10 |
| SRC-US-AMZ-GN9YK5Y7TYGRGNRG | Marking and labeling requirements for children’s products | https://sellercentral.amazon.com/help/hub/reference/external/GN9YK5Y7TYGRGNRG | S1 | 2026-10-10 |
| SRC-US-AMZ-GNEJ9DZASWJL4S4U | Personal lubricants | https://sellercentral.amazon.com/help/hub/reference/external/GNEJ9DZASWJL4S4U | S1 | 2026-10-10 |
| SRC-US-AMZ-GNHU43TN2RHER9BQ | Compliance Fast-Track program | https://sellercentral.amazon.com/help/hub/reference/external/GNHU43TN2RHER9BQ | S1 | 2026-10-10 |
| SRC-US-AMZ-GNPGY2ZEUMKSA62F | Toxic Substances Control Act chemical restrictions | https://sellercentral.amazon.com/help/hub/reference/external/GNPGY2ZEUMKSA62F | S1 | 2026-10-10 |
| SRC-US-AMZ-GNW6TTB8WVHHECFR | Climbing harnesses | https://sellercentral.amazon.com/help/hub/reference/external/GNW6TTB8WVHHECFR | S1 | 2026-10-10 |
| SRC-US-AMZ-GPCC6385YHNT35A9 | Infant and toddler sleep products | https://sellercentral.amazon.com/help/hub/reference/external/GPCC6385YHNT35A9 | S1 | 2026-10-10 |
| SRC-US-AMZ-GPQBDFAYL3LCWYD2 | Mermaid tail swimwear | https://sellercentral.amazon.com/help/hub/reference/external/GPQBDFAYL3LCWYD2 | S1 | 2026-10-10 |
| SRC-US-AMZ-GPWPSA5MVZQLLLKR | Mouthwash | https://sellercentral.amazon.com/help/hub/reference/external/GPWPSA5MVZQLLLKR | S1 | 2026-10-10 |
| SRC-US-AMZ-GQHQGBTD7XB7EECN | 计划政策变更 | https://sellercentral.amazon.com/help/hub/reference/external/GQHQGBTD7XB7EECN | S1 | 2026-10-10 |
| SRC-US-AMZ-GR2MJURQF2UBYRPK | Children’s gates and enclosures | https://sellercentral.amazon.com/help/hub/reference/external/GR2MJURQF2UBYRPK | S1 | 2026-10-10 |
| SRC-US-AMZ-GRE7PT254E4AFJFU | California Department of Forestry and Fire Protection (CAL FIRE) | https://sellercentral.amazon.com/help/hub/reference/external/GRE7PT254E4AFJFU | S1 | 2026-10-10 |
| SRC-US-AMZ-GRLKLZ6WQ9R259LC | Product safety listing restrictions | https://sellercentral.amazon.com/help/hub/reference/external/GRLKLZ6WQ9R259LC | S1 | 2026-10-10 |
| SRC-US-AMZ-GRTV7X82BHXYCS9L | General service lamps | https://sellercentral.amazon.com/help/hub/reference/external/GRTV7X82BHXYCS9L | S1 | 2026-10-10 |
| SRC-US-AMZ-GS62X9B3B79U8HGK | Powerful Magnets | https://sellercentral.amazon.com/help/hub/reference/external/GS62X9B3B79U8HGK | S1 | 2026-10-10 |
| SRC-US-AMZ-GS972L5FPTCLNYNR | Fire extinguishers | https://sellercentral.amazon.com/help/hub/reference/external/GS972L5FPTCLNYNR | S1 | 2026-10-10 |
| SRC-US-AMZ-GSGB43AFZNDWD4U8 | Children’s Product Certificate (CPC) | https://sellercentral.amazon.com/help/hub/reference/external/GSGB43AFZNDWD4U8 | S1 | 2026-10-10 |
| SRC-US-AMZ-GSJFE8S8AES7F7VG | Portable power supplies | https://sellercentral.amazon.com/help/hub/reference/external/GSJFE8S8AES7F7VG | S1 | 2026-10-10 |
| SRC-US-AMZ-GT3XLUHYCWPM3THX | Children's jewelry | https://sellercentral.amazon.com/help/hub/reference/external/GT3XLUHYCWPM3THX | S1 | 2026-10-10 |
| SRC-US-AMZ-GT7F5YBQFRDZCAG8 | Corded window coverings | https://sellercentral.amazon.com/help/hub/reference/external/GT7F5YBQFRDZCAG8 | S1 | 2026-10-10 |
| SRC-US-AMZ-GTG9WQP9QK9EMDA6 | Children’s ski and snowboard helmets | https://sellercentral.amazon.com/help/hub/reference/external/GTG9WQP9QK9EMDA6 | S1 | 2026-10-10 |
| SRC-US-AMZ-GTT32L3J5ZG23FMF | Pool and spa drain covers | https://sellercentral.amazon.com/help/hub/reference/external/GTT32L3J5ZG23FMF | S1 | 2026-10-10 |
| SRC-US-AMZ-GUBJLLVL96U285RQ | Respirators and respirator accessories | https://sellercentral.amazon.com/help/hub/reference/external/GUBJLLVL96U285RQ | S1 | 2026-10-10 |
| SRC-US-AMZ-GUBLQYWAJDBADUVK | Button cell and coin batteries and consumer products containing such batteries | https://sellercentral.amazon.com/help/hub/reference/external/GUBLQYWAJDBADUVK | S1 | 2026-10-10 |
| SRC-US-AMZ-GUCMGZBFXQ97P2SU | Food safety and compliance | https://sellercentral.amazon.com/help/hub/reference/external/GUCMGZBFXQ97P2SU | S1 | 2026-10-10 |
| SRC-US-AMZ-GUDREU3TUSEM3D3B | Infant and toddler bibs | https://sellercentral.amazon.com/help/hub/reference/external/GUDREU3TUSEM3D3B | S1 | 2026-10-10 |
| SRC-US-AMZ-GUDRMYJ7JL4PGNAB | California regulations | https://sellercentral.amazon.com/help/hub/reference/external/GUDRMYJ7JL4PGNAB | S1 | 2026-10-10 |
| SRC-US-AMZ-GUFQGCVJXHSYBL2Z | Infant bouncer seats | https://sellercentral.amazon.com/help/hub/reference/external/GUFQGCVJXHSYBL2Z | S1 | 2026-10-10 |
| SRC-US-AMZ-GUG6JJCDN6YYQYJP | Infant and toddler feeding products | https://sellercentral.amazon.com/help/hub/reference/external/GUG6JJCDN6YYQYJP | S1 | 2026-10-10 |
| SRC-US-AMZ-GUJFA3KVVEHVKKYE | Tiny homes and prefabricated structures | https://sellercentral.amazon.com/help/hub/reference/external/GUJFA3KVVEHVKKYE | S1 | 2026-10-10 |
| SRC-US-AMZ-GUQ848NB5HZ6M6A4 | Product categories with enhanced safety listing compliance requirements | https://sellercentral.amazon.com/help/hub/reference/external/GUQ848NB5HZ6M6A4 | S1 | 2026-10-10 |
| SRC-US-AMZ-GUTZ2R2DD6P2UMVB | Direct product validation: Third-party testing, inspection, and certification services | https://sellercentral.amazon.com/help/hub/reference/external/GUTZ2R2DD6P2UMVB | S1 | 2026-10-10 |
| SRC-US-AMZ-GVACXTSVATE36M4M | Full-size cribs | https://sellercentral.amazon.com/help/hub/reference/external/GVACXTSVATE36M4M | S1 | 2026-10-10 |
| SRC-US-AMZ-GVP5GB6WPLQNSW5M | Cashmere products | https://sellercentral.amazon.com/help/hub/reference/external/GVP5GB6WPLQNSW5M | S1 | 2026-10-10 |
| SRC-US-AMZ-GVRVVLWW9T3TWXGD | Infant bedside sleepers | https://sellercentral.amazon.com/help/hub/reference/external/GVRVVLWW9T3TWXGD | S1 | 2026-10-10 |
| SRC-US-AMZ-GVZJ58NTH3JDHC28 | Children's bicycles | https://sellercentral.amazon.com/help/hub/reference/external/GVZJ58NTH3JDHC28 | S1 | 2026-10-10 |
| SRC-US-AMZ-GW5CVACPVTQNTWHX | Hair dryers | https://sellercentral.amazon.com/help/hub/reference/external/GW5CVACPVTQNTWHX | S1 | 2026-10-10 |
| SRC-US-AMZ-GW6HK2RDRNNFW2ML | Paint removal products | https://sellercentral.amazon.com/help/hub/reference/external/GW6HK2RDRNNFW2ML | S1 | 2026-10-10 |
| SRC-US-AMZ-GWGLZQPAQN6VJZND | Improve your Compliance Fast-Track experience | https://sellercentral.amazon.com/help/hub/reference/external/GWGLZQPAQN6VJZND | S1 | 2026-10-10 |
| SRC-US-AMZ-GWHRWJTHCX9MQU46 | Postage stamps | https://sellercentral.amazon.com/help/hub/reference/external/GWHRWJTHCX9MQU46 | S1 | 2026-10-10 |
| SRC-US-AMZ-GWTRG6BMJHECNCFR | Misleading energy and fuel-saving device claims | https://sellercentral.amazon.com/help/hub/reference/external/GWTRG6BMJHECNCFR | S1 | 2026-10-10 |
| SRC-US-AMZ-GWU7WD8984FT4YLJ | Medical gloves | https://sellercentral.amazon.com/help/hub/reference/external/GWU7WD8984FT4YLJ | S1 | 2026-10-10 |
| SRC-US-AMZ-GWZVJXQCVTCKA5F6 | Oral over-the-counter (OTC) medications | https://sellercentral.amazon.com/help/hub/reference/external/GWZVJXQCVTCKA5F6 | S1 | 2026-10-10 |
| SRC-US-AMZ-GX44XMQX3ZKWRPZR | Infant sleep positioning products | https://sellercentral.amazon.com/help/hub/reference/external/GX44XMQX3ZKWRPZR | S1 | 2026-10-10 |
| SRC-US-AMZ-GX6ZFCE8L5J4SV2W | Beverage container deposits | https://sellercentral.amazon.com/help/hub/reference/external/GX6ZFCE8L5J4SV2W | S1 | 2026-10-10 |
| SRC-US-AMZ-GX9BGE7LAFRWAFHF | Pacifiers and pacifier clips | https://sellercentral.amazon.com/help/hub/reference/external/GX9BGE7LAFRWAFHF | S1 | 2026-10-10 |
| SRC-US-AMZ-GX9VRVWH8HXTDTK7 | Account enforcement for Regulatory and Safety Compliance violations | https://sellercentral.amazon.com/help/hub/reference/external/GX9VRVWH8HXTDTK7 | S1 | 2026-10-10 |
| SRC-US-AMZ-GXCXR3BN2ESL6TQC | Portable generators, portable inverter generators, and related devices | https://sellercentral.amazon.com/help/hub/reference/external/GXCXR3BN2ESL6TQC | S1 | 2026-10-10 |
| SRC-US-AMZ-GXDAVVP3RBLKV4GP | Magnet products | https://sellercentral.amazon.com/help/hub/reference/external/GXDAVVP3RBLKV4GP | S1 | 2026-10-10 |
| SRC-US-AMZ-GXMGGPL6LC4CVXHT | Safety, compliance, and product restrictions | https://sellercentral.amazon.com/help/hub/reference/external/GXMGGPL6LC4CVXHT | S1 | 2026-10-10 |
| SRC-US-AMZ-GXPFG3RRZB9WFPJE | Children’s portable bed rails | https://sellercentral.amazon.com/help/hub/reference/external/GXPFG3RRZB9WFPJE | S1 | 2026-10-10 |
| SRC-US-AMZ-GXQA3Y847TZVJE3R | Climbing ropes | https://sellercentral.amazon.com/help/hub/reference/external/GXQA3Y847TZVJE3R | S1 | 2026-10-10 |
| SRC-US-AMZ-GXT3EFQS54LRKYM3 | Children’s school supplies | https://sellercentral.amazon.com/help/hub/reference/external/GXT3EFQS54LRKYM3 | S1 | 2026-10-10 |
| SRC-US-AMZ-GXUCN5ZRJSYN9W9S | Smoke and carbon gas alarms | https://sellercentral.amazon.com/help/hub/reference/external/GXUCN5ZRJSYN9W9S | S1 | 2026-10-10 |
| SRC-US-AMZ-GYACVQUFWV28PZ2H | Equestrian helmets | https://sellercentral.amazon.com/help/hub/reference/external/GYACVQUFWV28PZ2H | S1 | 2026-10-10 |
| SRC-US-AMZ-GYD98N4N2ASSPVLE | Water delivery products | https://sellercentral.amazon.com/help/hub/reference/external/GYD98N4N2ASSPVLE | S1 | 2026-10-10 |
| SRC-US-AMZ-GYN5BF6ACA23ADZJ | Stationary activity centers | https://sellercentral.amazon.com/help/hub/reference/external/GYN5BF6ACA23ADZJ | S1 | 2026-10-10 |
| SRC-US-AMZ-GZ4E8J47K2YNXLQ9 | CPAP Cleaning and Disinfecting Devices | https://sellercentral.amazon.com/help/hub/reference/external/GZ4E8J47K2YNXLQ9 | S1 | 2026-10-10 |
| SRC-US-AMZ-GZ93G4JTAEVEJW62 | Misleading claims categories and resolution | https://sellercentral.amazon.com/help/hub/reference/external/GZ93G4JTAEVEJW62 | S1 | 2026-10-10 |
| SRC-US-AMZ-GZLZBQ7W6QZRKWWK | FBA dangerous goods (hazmat) program | https://sellercentral.amazon.com/help/hub/reference/external/GZLZBQ7W6QZRKWWK | S1 | 2026-10-10 |

### 待核实/冲突

以下事项本次没能从官方页面确认，或页面之间存在矛盾，规则已按“从严”处理，需人工复核：

1. **圆柱锂电禁令的生效日期与豁免边界**：G2HSXA2KM59YX5AT、G7PAP6BJAUXRM4LH 未注明生效日期（二手资料显示 2025 年下半年起大量下架，仅作线索）；“带端子连接器且包覆密封”的豁免是否覆盖内置焊接电芯的充电宝、电动工具电池包，页面未举例。Electronics 页（G200164510）写“包括所有使用这些电池类型的产品，即使电池不在产品内”，与圆柱电池页的豁免表述不完全一致 [R:US-L1-BATT-001]。
2. **照明页禁止示例与联邦定义冲突**：G201997070 把家电灯、黑光灯、驱虫灯、彩色灯、植物灯、红外灯等特殊用途灯列为“禁止示例”，但这些在 DOE 规则中本是通用照明灯（GSL）定义的排除项；GRTV7X82BHXYCS9L 只点名前四种。实际执行尺度待核实 [R:US-L1-LIGHT-001]。
3. **“美国居民”的认定**：农药（G202115120）和植物种子（G201737480）都限美国居民销售，但未说明以公司注册地、税务居民还是经营者居住地判断；中国卖家以美国公司主体能否申请待核实 [R:US-L1-PEST-001] [R:US-L1-PLANT-001]。
4. **高级合规要求页抓取失败**：口服 OTC 和补充剂页链接的 “Product categories with elevated compliance requirements”（GKF4ESYYJU833XED）只抓到导航壳，推测与强化安全类目页（G4RUG6EAT2ZLVSRT）内容一致，规则改引后者 [R:US-L2-DRUG-011]。
5. **亚硝酸钠浓度**：食品页写“浓度 >10% 的亚硝酸钠”禁售，产品安全上架限制表（GRLKLZ6WQ9R259LC）只写 “Sodium nitrite”、“Sodium nitrate” 未给阈值，两处口径不同 [R:US-L1-FOOD-002]。
6. **FBA 禁运页内容疑似不完整**：G201730840 本次渲染只有 11 项（历史版本更长，含更多危险品示例），可能是页面改版或渲染截断，建议人工打开核对 [R:US-L4-FBA-001]。
7. **派对拉炮/仙女棒**：危险品页把 party poppers、sparklers、snap caps 列为爆炸物；不含火药的压缩空气礼花筒是否也禁售未说明 [R:US-L1-HAZ-003]。
8. **LED 大灯“仅限越野使用”**：汽车页禁止 LED 大灯改装套件，但未说明标注 off-road only 的灯泡是否可售 [R:US-L1-AUTO-004]。
9. **激光雕刻/切割机**：不受“≥5 mW 的 3B/4 级禁售”约束，但是否也需 electronics-safety@amazon.com 预批准未说明 [R:US-L2-LASER-002]。
10. **被美国禁止的网络安全软件**：Electronics 页未点名具体产品，规则以卡巴斯基为关键词属推断 [R:US-L1-ELEC-001]。
11. **Apple 替换电池范围**：“Apple or iPhone branded replacement batteries” 是否包括“适用于 iPhone”的第三方电池，页面措辞有歧义 [R:US-L1-ELEC-009]。
12. **尼古丁替代疗法是否需类目审核**：烟草页允许 FDA 批准的 OTC 尼古丁口香糖/含片/贴片，但未说明是否另需药品类目审核或 TIC [R:US-L2-TOBACCO-005]。
13. **毒蝇伞（Amanita）软糖、水弹枪、Delta-8 等新兴品**：药品页未点名，规则按“模仿致幻效果”“软弹玩具枪”“合成大麻素”分别处理，待核实 [R:US-L1-DRUG-003] [R:US-L2-WEAPON-013] [R:US-L1-DRUG-004]。
14. **刹车片铜含量标识（LeafMark）**：汽车页只写“未经制造商认证符合州铜/重金属/石棉限制的刹车片受州法限制”，具体标识要求待 L5 核实 [R:US-L2-AUTO-011]。


15. **日食眼镜**：危险品页（G200164570）把 "Eclipse glasses and filters for solar viewing" 列为禁售，而专页 G202171660 允许符合 ISO 12312-2 的日食眼镜；本规则库按专页处理（眼镜可售、望远镜/相机滤镜禁售）[R:US-L1-ECLIPSE-001] [R:US-L3-ECLIPSE-002]。
16. **汞体温计**：医用体温计页把汞体温计列为需 FDA 注册的品类，危险品页则禁售含汞体温计；按禁售处理 [R:US-L1-HAZ-005] [R:US-L3-THERMO-001]。
17. **加热服装**：产品安全上架限制表笼统禁售“电池加热服装和鞋垫”，专页只禁电池承重设计，按专页处理 [R:US-L1-HEATWEAR-001]。
18. **漱口水**：页面禁售含酒精漱口水，却又接受“乙醇 <3 g 的成分表”代替 GCC [R:US-L1-MOUTHWASH-001]。
19. **经期用品**：页面要求所有产品提交 510(k)，但法规表只对卫生棉条要求 510(k) [R:US-L3-MENSTRUAL-001]。
20. **“crystal dream pacifiers” 与 “Polar pen”**：只出现在产品安全上架限制表中，未给定义；前者推断为镶钻奶嘴，后者无法归类，未写入规则 [R:US-L1-INFANT-007]。
21. **婴幼儿睡眠产品的提交路径**：旧版单页（床边婴儿床、婴儿床、幼儿床、儿童床护栏）写直接交亚马逊，合并后的婴幼儿睡眠产品页与强化安全类目写经 TIC，以后者为准 [R:US-L3-SLEEP-002]。
22. **Amazon Haul 页面**：Haul 首饰、Haul 食品接触材料两页挂在美国帮助中心，但内容只适用于欧洲 Haul 店铺（REACH、EU 10/2011），未写美国规则。
23. **易融商品页**：温度阈值写 155°F（疑为笔误），并同时出现 2026-05-01 和 2027-05-01 两个处置日期 [R:US-L4-FBAMELT-001]。
24. **FBA 食品指南（G200660860）** 英文、中文均只抓到导航壳，未引用。
25. **电动切割工具**：UL 62841 系列合规截止日 2028-09-05 之后 UL 60745 报告是否失效，页面未说明 [R:US-L3-CUTTOOL-002]。
26. **水弹枪凝胶弹**：彩色凝胶弹本质是水晶珠，可能落入水晶珠禁售 [R:US-L1-WATERBEAD-001]。
27. **强化安全类目投保的生效时间**：强化安全类目页（G4RUG6EAT2ZLVSRT）和审核页（G200333160）把“不论销售额都须投保”写成现行要求，商业责任险页（G200386300）则写 2026-11-02 起生效；规则按现行处理 [R:US-L2-ENHANCED-001] [R:US-L2-INSURANCE-002]。
28. **激光等级上限**：Listing 限制页（G201707070）写不得上架超过 IIIA（3R）级的激光产品，激光产品页则允许 <5 mW 的 3B/4 级经预批准销售 [R:US-L1-LASER-001] [R:US-L2-LASER-002]。
29. **儿童抽绳上衣范围**：Listing 限制页和危险品页写 2T–12 码所有带抽绳的儿童上衣禁售，抽绳专页只禁兜帽/颈部抽绳并对腰部/下摆抽绳给出条件 [R:US-L1-HAZ-009] [R:US-L1-CHILD-001] [R:US-L3-CHILD-002]。
30. **服务类申请**：服务类申请页（G201613540）写可以申请，保修/服务政策页写目前不接受申请 [R:US-L1-WARRANTY-001] [R:US-L2-APPROVAL-003]。


#### 规则备注中标注“待核实”的事项（自动汇总）

- [R:US-L1-AUTO-004] 标注“仅限越野使用”的 LED 大灯泡通常仍被判为 LED 大灯改装套件，待核实亚马逊具体执行尺度。
- [R:US-L1-DRUG-003] 毒蝇伞（Amanita muscaria）“蘑菇软糖”页面未点名，可能按“模仿致幻效果的产品”处理，待核实。
- [R:US-L1-ELEC-001] 页面未点名具体产品；卡巴斯基为 2024 年美国商务部禁令对象，系推断，待核实。
- [R:US-L1-ELEC-009] “适用于 iPhone 的第三方替换电池”是否被视为 "Apple or iPhone branded" 有歧义，按标题中是否以 Apple/iPhone 作品牌判断，待核实。
- [R:US-L1-BATT-001] 例外条款“带端子连接器且包覆密封”的界定（例如电动工具电池包、内置电芯焊接成组的充电宝是否豁免）页面未详述，按“用户可直接取放裸电芯即禁售”理解，待核实。18650 充电器、电池盒在 Electronics 页面中是否同时禁售：Electronics 页写“含这些电池类型的所有产品，即使电池不在产品内”，因此专用 18650 充电器/电池盒/使用 18650 的手电也禁售。
- [R:US-L1-HAZ-005] 医用体温计页（GJFNF3SE7N7ZLE78）把汞体温计列为需 FDA 注册的品类，与本页禁售汞体温计冲突，按禁售处理，待核实。
- [R:US-L1-LASER-001] Listing 限制页（G201707070）写“不得上架超过 IIIA（3R）级发射限值的激光产品”，比激光产品页（3B/4 级 <5mW 经预批准可售）更严，两页冲突，待核实。
- [R:US-L1-LIGHT-001] 照明页列出的特殊用途灯在联邦法规中原本是“通用照明灯定义的排除项”，亚马逊却列为禁止示例，含义存疑（可能指以通用照明为目的营销的此类灯），待核实；通用照明灯页仅点名家电灯、黑光灯、驱虫灯、彩色灯为禁止示例。
- [R:US-L1-PEST-001] 是否以“公司注册地/税务居民”判断“US residents”页面未定义，待核实；中国卖家常以美国公司主体申请，需注意亚马逊审核尺度。
- [R:US-L1-SURV-001] 带麦克风的伪装摄像头即落入禁售；仅视频（无录音）的隐藏摄像头可售。Flipper Zero 类工具是否被认定为“入侵设备”为推断，待核实。
- [R:US-L1-INFANT-007] 英文 crystal dream pacifiers 只出现在产品安全上架限制表中，未给定义，推断指镶水钻/水晶装饰的奶嘴，待核实。
- [R:US-L1-WATERBEAD-001] 水弹枪（gel blaster）配套的彩色凝胶弹本质为水晶珠，可能落入“彩色水晶珠无论用途”禁售范围，待核实；透明无儿童营销的园艺保水珠理论上不在禁售清单内。
- [R:US-L1-HEATWEAR-001] 产品安全禁售清单（GRLKLZ6WQ9R259LC）笼统写“Battery-operated heated apparel and insoles”禁售，而专页（GFQMECECLTJCUE3H）只禁止电池承重设计、其余可凭检测报告销售，存在冲突，按专页理解，待核实。
- [R:US-L1-SAFECHEM-001] 食品政策（G200164550）只禁止浓度 >10% 的亚硝酸钠，而产品安全禁售清单笼统列出亚硝酸钠/硝酸钠；含少量亚硝酸钠的腌制盐（Prague Powder #1 约 6.25%）是否可售存在冲突，待核实。
- [R:US-L1-MOUTHWASH-001] 同页又允许以“乙醇含量 <3 g 的成分表”代替 GCC 提交，似乎意味着含微量乙醇（<3 g/包装）的漱口水可售，与“含乙醇即禁售”表述存在张力，待核实。
- [R:US-L1-WARRANTY-001] 服务类申请页（G201613540）写可以申请（须背景审查和美国执照），与本页“不接受申请”冲突，待核实。2026-07-15 起相关政策更新，明确只有受邀个人或实体才能向亚马逊买家提供服务，并扩充了禁售示例。规则只针对“把服务/保修本身作为商品销售”的 Listing；商品自带的制造商保修说明不受此限，但须真实。
- [R:US-L2-ENHANCED-001] 11 组类目明细见文档 B 节。商业责任险页（G200386300）另要求：免赔额 ≤1 万美元并写在 COI 上、无日落条款、被保险人名称与账户法人名一致、保险公司 S&P/AM Best A- 及以上、取消或修改须提前 30 天通知亚马逊；并把“强化安全类目不论销售额均须投保”写为 2026-11-02 起生效，而强化安全类目页写为现行要求，两页冲突，本规则按现行处理。2026-11-02 起中国大陆卖家须通过亚马逊保险加速器（AIA）投保（见 US-L2-INSURANCE-002）。触发条件宽泛，最终以账户状况（Account Health）通知为准。
- [R:US-L2-WEAPON-013] 水弹枪（gel blaster）是否被归为软弹/玩具枪，页面未点名，待核实。
- [R:US-L2-LASER-002] 激光雕刻/切割机不受 ≥5mW 禁令限制，但其合规路径（是否同样需预先批准）页面未明确，待核实。
- [R:US-L2-INSURANCE-002] 对中国卖家影响大：已有的第三方保单在 2026-11-02 后是否仍被认可、是否有过渡期，页面未说明，待核实。
- [R:US-L2-APPROVAL-003] 服务类页面（G201613540）写可申请，而保修/服务政策页（G200164930）写“目前不接受服务或保修销售申请”，两者冲突，待核实。
- [R:US-L2-TOBACCO-005] 亚马逊另有药品类目审核（见 Drugs 类目规则）；尼古丁产品常需额外批准，待核实是否需要类目审核。
- [R:US-L3-SUPP-008] 中国工厂常见做法为 ISO 22000、FSSC 22000 或 BRCGS 证书；中国 GMP 证书是否被接受未在页面列明，待核实。
- [R:US-L3-CUTTOOL-002] 页面仅一句“UL 62841 系列合规截止日为 2028-09-05”，未明确 UL 60745 报告届时是否失效，待核实。
- [R:US-L3-ALARM-001] 灭火器属有效期/危险品（压缩气体 2.2 项）商品，FBA 须危险品分类；“灭火喷雾/灭火球”是否适用 UL 灭火器标准页面未说明，待核实。
- [R:US-L3-CLIMB-001] 装饰用/钥匙扣用登山扣若不宣称承重攀登用途，是否落入本政策页面未说明；建议标题注明 "Not for climbing"，待核实。
- [R:US-L3-MENSTRUAL-001] 页面文件清单对所有经期用品都列出 510(k) 许可函，但法规表中卫生巾和月经杯只要求注册列名；按“适用时提交”理解，待核实。
- [R:US-L3-ECLIPSE-002] 危险及禁售品页（G200164570）把 "Eclipse glasses and filters for solar viewing" 列为禁售，与本页“日食眼镜可售”冲突；以较新的专页为准，待核实。
- [R:US-L4-FBAMELT-001] 页面温度阈值写作 "155 degrees Fahrenheit"，与行业惯例（约 75°F）不符，可能为笔误；页面同时出现 "May 1, 2026" 与 "May 1, 2027" 两个处置日期，季节具体起止以卖家平台通知为准，待核实。

## 第二部分 · 美国法规与进口要求（L5–L6）

> 规则包版本：draft · 调研日期：2026-10-10 · 本文只覆盖美国当地法规（L5）与进口/清关（L6），对应模板 E、F（法规部分）、G（法规变化）、H 节和「待核实」；亚马逊平台政策（A–D 节，L1–L4）由另一份文档负责。本文不构成法律意见。
> 每条结论后用 [SRC-…] 标注来源（见 `rules/sources/US_regulation.yaml`），用 [R:规则ID] 关联机读规则（`rules/sites/US_regulation.yaml`）。
> 来源级别：S2 政府官方（eCFR、Federal Register、govinfo 美国法典、各机构与州政府网站）· S3 二手（律所、检测机构）。只有 S3 支撑的结论标注「（二手来源，待核）」；只在搜索摘要中看到的政府页面，对应规则标为 unverified。
> 规则统计：共 200 条（L5 180 条、L6 20 条）；禁售 27 条、需政府许可 17 条、强制合规 150 条、提示 6 条。

**读表说明**：E 节每个产品族先列 2–5 条要点，再列规则表。「适用法规」一栏开头的【禁售】【需政府许可】【强制合规】【提示】对应规则的 severity；只在部分州禁止的事项标为「强制合规」，须对相应州设置配送限制。

**谁是「进口商」**：美国法规里大量义务落在「进口商」（importer）身上——CPSC 证书的出具方是进口商 [SRC-US-GOV-ECFR-16CFR1110]，DOE 把进口商视为制造商 [SRC-US-GOV-ECFR-10CFR429_12]，FDA 器械的首次进口商须注册 [SRC-US-GOV-ECFR-21CFR807]。中国卖家用 FBA 时，亚马逊不担任记录进口商（IOR），这些义务通常由卖家本身（作为非居民进口商）或其委托的美国进口主体承担 [R:US-L6-IMPORT-001]。

### E. 当地法规（L5，按产品族）

#### E.1 通用（所有消费品）
- 受 CPSC 任一强制规则约束的产品都要有证书：儿童产品用 CPC（须 CPSC 认可第三方实验室检测），其他产品用 GCC；证书英文、随货、提供给零售商，CPSC/CBP 要求时 24 小时内提供，记录保存 5 年 [SRC-US-GOV-ECFR-16CFR1110] [R:US-L5-CPSC-001] [R:US-L5-CPSIA-001]。
- 销售被召回或不符合强制规则的产品是违法行为；发现缺陷须按 15(b) 条在 24 小时内报告 CPSC [SRC-US-GOV-USC-15USC2068] [SRC-US-GOV-USC-15USC2064] [R:US-L5-CPSC-002]。
- 加州 Prop 65：网店须在商品页（或「WARNING」链接、结账前）展示警示；2025-01-01 起生效的修订要求简式警示写出化学物名称，2028-01-01 前生产贴标的产品可沿用旧格式 [SRC-US-GOV-OEHHA-P65-ART6-2024] [R:US-L5-PROP65-001] [R:US-L5-PROP65-002]。
- 不得对中国制造商品宣称「Made in USA」；不得刷单、买好评、压差评（FTC 评论规则 2024-10-21 起）[SRC-US-GOV-ECFR-16CFR323] [SRC-US-GOV-ECFR-16CFR465] [R:US-L5-FTC-004] [R:US-L5-FTC-009]。
- PFAS：明尼苏达 2025 年起 11 类、缅因 2026 年起 9 类产品禁含有意添加 PFAS，两州 2032 年起原则上全面禁止；明尼苏达申报截止日已延至 2026-09-15（二手来源，待核）[SRC-US-GOV-MN-STAT-116-943] [SRC-US-GOV-ME-DEP-PFAS-PRODUCTS] [R:US-L5-PFAS-004] [R:US-L5-PFAS-005]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【强制合规】受 CPSC 规则约束的非儿童产品须出具一般符合性证书 GCC [SRC-US-GOV-ECFR-16CFR1110] [SRC-US-GOV-USC-15USC2063] [SRC-US-GOV-FR-2024-30826] | 一般符合性证书 GCC；支持 GCC 的检测报告 | — | — | CPSC | [R:US-L5-CPSC-001] |
| 【提示】不得销售被召回或不符合 CPSC 强制规则的消费品；发现缺陷须 24 小时内向 CPSC 报告 [SRC-US-GOV-USC-15USC2068] [SRC-US-GOV-USC-15USC2064] [SRC-US-GOV-ECFR-16CFR1115] | — | 上架前核查 CPSC 召回清单；第 15(b) 条缺陷/不合规报告 | — | CPSC | [R:US-L5-CPSC-002] |
| 【强制合规】泳池/水疗排水盖须符合 VGB 法（16 CFR 1450） [SRC-US-GOV-ECFR-16CFR1450] | ANSI/APSP/ICC-16 测试；GCC | — | — | CPSC | [R:US-L5-HOME-005] |
| 【强制合规】不得对中国制造商品宣称「Made in USA」 [SRC-US-GOV-ECFR-16CFR323] | — | — | 原产地宣称须真实（中国制造须标 Made in China）；必备语句：不得在标题、图片、包装中宣称 Made in USA / American Made（除非完全符合 FTC 标准） | FTC | [R:US-L5-FTC-004] |
| 【强制合规】消费品包装须标明品名、净含量（公制与英制）和责任方（FPLA） [SRC-US-GOV-ECFR-16CFR500] | — | — | 品名、双单位净含量、责任方名称地址 | FTC | [R:US-L5-FTC-008] |
| 【提示】禁止虚假评论、购买好评和压制差评（FTC 评论规则，2024-10-21 生效） [SRC-US-GOV-ECFR-16CFR465] | — | 不得刷单、索评换利益、伪造评论或威胁差评买家 | — | FTC | [R:US-L5-FTC-009] |
| 【强制合规】加州 Prop 65：产品可能使消费者接触清单化学物时须提供警示，网店须在详情页或下单前展示 [SRC-US-GOV-OEHHA-P65-ART6-2024] [SRC-US-S3-BCLP-P65-SHORTFORM] | 铅、邻苯（DEHP/DINP 等）、BPA、镉等清单物质检测，判定是否需要警示 | — | 产品/包装 Prop 65 警示（完整或简式，含 ⚠ 符号与 WARNING）；亚马逊详情页或结账前展示同样警示；必备语句：向加州销售且可能接触 Prop 65 物质的产品，包装与详情页须有：⚠ WARNING: ... See www.P65Warnings.ca.gov.（2028-01-01 起新贴标产品的简式警示须写出化学物名称） | 加州 OEHHA / 检察长 | [R:US-L5-PROP65-001] |
| 【强制合规】加州 Prop 65 高风险材质：PVC/乙烯基、黄铜/含铅金属、陶瓷釉、合成皮革、电源线等 [SRC-US-GOV-OEHHA-P65-ART6-2024] | 目标物质检测（邻苯、铅、镉、BPA 等） | — | 如未能证明低于安全港水平，则加 Prop 65 警示（产品 + 详情页） | 加州 OEHHA / 检察长 | [R:US-L5-PROP65-002] |
| 【强制合规】有意添加 PFAS 的婴童用品、地毯、织物处理剂、清洁剂、牙线、月经用品、滑雪蜡、软包家具：明尼苏达 2025、缅因 2023/2026 起禁售；禁止事项：不得向明尼苏达（2025 起）、缅因（2023/2026 起）销售所列类别中含有意添加 PFAS 的产品 [SRC-US-GOV-MN-STAT-116-943] [SRC-US-GOV-ME-DEP-PFAS-PRODUCTS] | — | 供应链无 PFAS 声明或检测 | — | 各州环保部门（MN PCA、ME DEP 等） | [R:US-L5-PFAS-004] |
| 【强制合规】明尼苏达 PFAS 产品申报：含有意添加 PFAS 的产品制造商须向 MPCA 报告（截止日已延至 2026-09-15） [SRC-US-GOV-MN-STAT-116-943] [SRC-US-S3-BDLAW-MN-PFAS-2026] | — | MPCA PFAS in Products 报告（PRISM 系统）；供应链 PFAS 调查记录 | — | 各州环保部门（MN PCA、ME DEP 等） | [R:US-L5-PFAS-005] |

#### E.2 电子电器
- 含数字电路的电子产品须做 FCC SDoC，SDoC 负责方必须在美国境内；带无线功能的另见 E.4 [SRC-US-GOV-ECFR-47CFR2_909] [SRC-US-GOV-ECFR-47CFR2_1077] [R:US-L5-FCC-002]。电磁炉、微波炉、超声波设备走 Part 18 [R:US-L5-FCC-003]。
- 能效：受联邦标准约束的产品（外部电源、充电器、灯泡、吊扇、除湿机、移动空调、小冰箱等）上市前须由制造商/进口商在 DOE CCMS 认证；外部电源须 Level VI 并标「VI」；在加州还须在 CEC MAEDbS 列名 [SRC-US-GOV-ECFR-10CFR429_12] [SRC-US-GOV-ECFR-10CFR430_32] [R:US-L5-DOE-001] [R:US-L5-DOE-002] [R:US-L5-CAT20-001]。DOE 2025-05 提议撤销电池充电器与外部电源标准，截至调研日未定稿 [SRC-US-GOV-FR-2025-08598] [SRC-US-GOV-FR-2025-08587]。
- 冰箱、空调、电视、吊扇等须有 EnergyGuide 标签，网页须展示标签图片 [SRC-US-GOV-ECFR-16CFR305_27] [R:US-L5-FTC-007]。
- PIP(3:1) 阻燃增塑剂：2026-10-31 起禁止分销含有意添加 PIP(3:1) 的物品（电路板、线束等除外）[SRC-US-GOV-ECFR-40CFR751_407] [R:US-L5-TSCA-003]。
- 延长线、吹风机分别须具备 UL 817、UL 859/1727 规定特性，否则属实质性产品危害 [SRC-US-GOV-ECFR-16CFR1120] [R:US-L5-SPH-003] [R:US-L5-SPH-001]；加州空气净化器须 CARB 认证（臭氧 <0.050 ppm）[R:US-L5-CARB-001]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【强制合规】延长线须具备 UL 817 规定特性（SPH 清单） [SRC-US-GOV-ECFR-16CFR1120] | UL 817 相关条款测试 | — | — | CPSC | [R:US-L5-SPH-003] |
| 【强制合规】自动车库门开门机须符合 16 CFR 1211（UL 325 防夹） [SRC-US-GOV-ECFR-16CFR1211] | UL 325 / 16 CFR 1211 测试；GCC | — | — | CPSC | [R:US-L5-HOME-002] |
| 【强制合规】家用冰箱门须可从内部打开（16 CFR 1750） [SRC-US-GOV-ECFR-16CFR1750] | 16 CFR 1750 开门力测试；GCC | — | — | CPSC | [R:US-L5-HOME-004] |
| 【强制合规】含数字电路的电子产品须做 FCC SDoC（供应商符合性声明），美国境内须有负责方 [SRC-US-GOV-ECFR-47CFR15] [SRC-US-GOV-ECFR-47CFR2_909] [SRC-US-GOV-ECFR-47CFR2_1077] | Part 15 Subpart B（或 Part 18）测试报告 | SDoC 合规信息声明（2.1077）；美国境内负责方（responsible party） | 15.19 合规声明标签；必备语句：产品或说明书须有 FCC Part 15 合规声明及美国负责方信息（SDoC） | FCC | [R:US-L5-FCC-002] |
| 【强制合规】电磁炉、微波炉、超声波设备等 ISM 设备须符合 47 CFR Part 18 [SRC-US-GOV-ECFR-47CFR18] | Part 18 测试报告（消费级 ISM 限值） | SDoC 或认证，以及用户信息（18.213） | — | FCC | [R:US-L5-FCC-003] |
| 【强制合规】微波炉须符合 21 CFR 1030.10 辐射泄漏与联锁要求 [SRC-US-GOV-ECFR-21CFR1030_10] [SRC-US-GOV-ECFR-21CFR1002] | 1030.10 泄漏与联锁测试 | CDRH 产品报告 | 1030.10 警示与认证标签 | FDA CDRH | [R:US-L5-RAD-003] |
| 【强制合规】含 PIP (3:1) 的物品 2026-10-31 后禁止在美分销（电路板与线束等除外） [SRC-US-GOV-ECFR-40CFR751_407] | — | 供应链声明/检测证明产品不含有意添加的 PIP(3:1)；合规记录保存 5 年 | — | EPA | [R:US-L5-TSCA-003] |
| 【强制合规】家电与灯泡须有 EnergyGuide / Lighting Facts 标签，网页须展示标签图片 [SRC-US-GOV-ECFR-16CFR305] [SRC-US-GOV-ECFR-16CFR305_27] | — | — | EnergyGuide / Lighting Facts 标签（产品或包装）；详情页展示标签图片；必备语句：适用家电/灯泡详情页须展示 EnergyGuide 或 Lighting Facts 标签图片 | FTC | [R:US-L5-FTC-007] |
| 【强制合规】受联邦能效标准约束的产品须在上市前向 DOE 认证（CCMS），进口商视为制造商 [SRC-US-GOV-ECFR-10CFR429_12] [SRC-US-GOV-ECFR-10CFR430_32] [SRC-US-GOV-FR-2025-08596] | 按 DOE 测试程序（10 CFR 430 附录）的测试报告 | DOE CCMS 认证报告（每个基本型号） | — | DOE | [R:US-L5-DOE-001] |
| 【强制合规】外部电源须满足 Level VI 能效并标注「VI」 [SRC-US-GOV-ECFR-10CFR430_32] [SRC-US-GOV-ECFR-10CFR429_12] [SRC-US-GOV-FR-2025-08587] | DOE 附录 Z 测试 | DOE CCMS 认证 | 铭牌 Level VI 标记 | DOE | [R:US-L5-DOE-002] |
| 【需政府许可】加州：室内空气净化器须经 CARB 认证（臭氧 <0.050 ppm），包装标注 ARB 认证（官方页面仅见摘要，待核） [SRC-US-GOV-CARB-AIR-CLEANER] | CARB 室内空气净化设备认证；UL 867（或 UL 507）臭氧与电气安全测试 | — | 包装上的 ARB 认证标识（17 CCR 94806 规定格式） | 加州 CARB | [R:US-L5-CARB-001] |
| 【强制合规】加州 Title 20：受监管电器须在 CEC 数据库（MAEDbS）认证列名才能在加州销售（官方页面仅见摘要，待核） [SRC-US-GOV-CEC-APPLIANCE-EFFICIENCY] | — | CEC MAEDbS 认证列名 | Title 20 规定的标记（如适用） | 加州能源委员会 CEC | [R:US-L5-CAT20-001] |

#### E.3 电池
- 含纽扣/硬币电池的所有消费品须符合 Reese's Law（16 CFR 1263 采纳 UL 4200A-2023）：电池仓防儿童开启、性能测试、产品/包装/说明书警示；单独销售的纽扣电池包装须有规定警示（2024-09-21 起）并使用儿童防护包装 [SRC-US-GOV-ECFR-16CFR1263] [SRC-US-GOV-USC-15USC2056E] [R:US-L5-BTN-001] [R:US-L5-BTN-002] [R:US-L5-BTN-003]。CPSC 2026-09 就 UL 4200A 修订版征求意见，强制版本可能更新 [SRC-US-GOV-FR-2026-18103]。
- 锂电池运输：电芯/电池制造商及后续分销商须提供 UN 38.3 测试摘要 [SRC-US-GOV-ECFR-49CFR173_185] [R:US-L5-PHMSA-001]。
- 微出行锂电池（电动自行车、滑板车、平衡车）见 E.19。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【强制合规】含纽扣/硬币电池的消费品须符合 Reese's Law（16 CFR 1263 / UL 4200A-2023）（生效 2023-10-23） [SRC-US-GOV-ECFR-16CFR1263] [SRC-US-GOV-USC-15USC2056E] [SRC-US-GOV-FR-2026-18103] | ANSI/UL 4200A-2023 检测报告；GCC 或 CPC 列明 16 CFR 1263 | — | 产品/包装/说明书纽扣电池警示；必备语句：包装须有纽扣电池吞咽危险警示（WARNING 信号词、警示符号，按 UL 4200A / 16 CFR 1263） | CPSC | [R:US-L5-BTN-001] |
| 【强制合规】单独销售的纽扣/硬币电池包装须有规定警示（2024-09-21 起） [SRC-US-GOV-ECFR-16CFR1263] | — | — | 电池包装警示（16 CFR 1263.4 图 1–3） | CPSC | [R:US-L5-BTN-002] |
| 【强制合规】纽扣/硬币电池须采用儿童防护包装（PPPA）（生效 2023-02-12） [SRC-US-GOV-USC-15USC2056E] [SRC-US-GOV-ECFR-16CFR1700] | 儿童防护包装测试（16 CFR 1700.20）；GCC 列明 PPPA 要求 | — | — | CPSC | [R:US-L5-BTN-003] |
| 【强制合规】锂电池及含锂电池产品须有 UN 38.3 测试摘要，并按危险品规则包装运输 [SRC-US-GOV-ECFR-49CFR173_185] [SRC-US-GOV-ECFR-49CFR172] | UN 38.3 测试报告与测试摘要（Test Summary） | 危险品运输分类、包装与标记（UN3480/3481/3090/3091） | — | DOT PHMSA | [R:US-L5-PHMSA-001] |

#### E.4 无线
- 有意辐射体须取得 FCC 认证（FCC ID），认证申请人须指定美国送达代理人；未获授权不得营销（含在线市场）[SRC-US-GOV-ECFR-47CFR2] [SRC-US-GOV-ECFR-47CFR2_803] [R:US-L5-FCC-001]。
- FCC 2026-09-11 新规（2026-10-13 生效）：在线市场须在销售页展示 FCC ID——对商品有实物控制的（如代仓发货）2027-03-01 起，仅撮合第三方的 2027-06-01 起（须核验卖家提供的 FCC ID 并让卖家声明准确）[SRC-US-GOV-FR-2026-18535] [R:US-L5-FCC-004]。
- Covered List：华为、中兴、海能达、海康、大华等设备不得获得授权；2024 年及以前列入清单的已授权设备自 2026-07-16 起禁止继续进口与营销 [SRC-US-GOV-FR-2026-13518] [R:US-L5-FCC-005]。
- 测试实验室：受禁止实体拥有/控制的 TCB 和实验室自 2025-09-08 起不再被承认，其报告不能用于认证或 SDoC [SRC-US-GOV-FR-2025-14970] [R:US-L5-FCC-007]。
- 信号干扰器一律禁售；手机信号放大器须认证并提示用户向运营商注册；对讲机须 Part 95/90 认证 [SRC-US-GOV-USC-47USC302A] [R:US-L5-FCC-008] [R:US-L5-FCC-009] [R:US-L5-FCC-010]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【需政府许可】无线发射设备须取得 FCC 认证（FCC ID） [SRC-US-GOV-ECFR-47CFR2] [SRC-US-GOV-ECFR-47CFR15] [SRC-US-GOV-ECFR-47CFR15_19] | FCC 设备认证（Certification）；47 CFR Part 15 / 22 / 24 / 27 / 95 等适用条款测试报告 | 美国送达代理人（agent for service of process） | FCC ID 标签与 Part 15 合规声明 | FCC | [R:US-L5-FCC-001] |
| 【强制合规】未经授权不得营销射频设备；在线市场须展示 FCC ID（规则 2026-10-13 生效） [SRC-US-GOV-ECFR-47CFR2_803] [SRC-US-GOV-FR-2026-18535] | — | 上架前确认设备已获有效 FCC 授权且未被限制 | 在 listing 中提供准确的 FCC ID | FCC | [R:US-L5-FCC-004] |
| 【禁售】FCC「受管控清单」（Covered List）企业的设备禁止授权、进口和营销；禁止事项：不得进口、销售或营销 Covered List 实体生产的设备（含白牌/贴牌产品） [SRC-US-GOV-ECFR-47CFR2_903] [SRC-US-GOV-FR-2026-13518] [SRC-US-GOV-FR-2026-18535] | — | — | — | FCC | [R:US-L5-FCC-005] |
| 【强制合规】FCC 测试/认证不得使用受禁止实体拥有或控制的实验室和认证机构 [SRC-US-GOV-FR-2025-14970] [SRC-US-GOV-FR-2026-09822] [SRC-US-GOV-ECFR-47CFR2] | 选用仍在 FCC 承认名单内、非受禁止实体控制的实验室出具报告 | — | — | FCC | [R:US-L5-FCC-007] |
| 【禁售】信号干扰器（手机/GPS/Wi-Fi 屏蔽器）禁止销售、进口和广告；禁止事项：信号干扰器禁售 [SRC-US-GOV-USC-47USC302A] [SRC-US-GOV-USC-47USC333] [SRC-US-GOV-ECFR-47CFR2_803] | — | — | — | FCC | [R:US-L5-FCC-008] |
| 【强制合规】手机信号放大器须获认证并标注用户须经运营商同意和注册 [SRC-US-GOV-ECFR-47CFR20_21] | FCC 认证（20.21 网络保护标准） | — | 20.21 规定的消费者警示标签（须取得运营商同意并注册） | FCC | [R:US-L5-FCC-009] |
| 【需政府许可】对讲机：FRS/GMRS 须 Part 95 认证；可在业余频段外发射的手台不得作为业余电台销售；禁止事项：不得销售 FRS 与其他业务的组合手台；不得销售可在授权频段外发射的未认证手台 [SRC-US-GOV-ECFR-47CFR95] [SRC-US-GOV-ECFR-47CFR2_803] | Part 95（FRS/GMRS）或 Part 90 认证 | — | — | FCC | [R:US-L5-FCC-010] |

#### E.5 灯具
- 通用照明灯泡光效须 ≥45 lm/W，传统白炽灯泡已不能销售 [SRC-US-GOV-ECFR-10CFR430_32] [R:US-L5-DOE-003]；灯泡须有 Lighting Facts 标签并在网页展示 [R:US-L5-FTC-007]；120V 插电节日灯串须具备 UL 588 规定特性 [R:US-L5-SPH-002]。
- LED 灯、驱动电源适用 FCC SDoC [R:US-L5-FCC-002]；在加州销售的 LED 灯须在 CEC 列名 [R:US-L5-CAT20-001]。汽车灯见 E.18。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【强制合规】120V 节日/装饰灯串须具备 UL 588 规定特性（SPH 清单） [SRC-US-GOV-ECFR-16CFR1120] | UL 588 相关条款测试 | — | — | CPSC | [R:US-L5-SPH-002] |
| 【禁售】光效低于 45 lm/W 的通用照明灯泡（白炽灯等）禁止销售；禁止事项：不得销售光效 <45 lm/W 的通用照明灯泡（A19 白炽灯等） [SRC-US-GOV-ECFR-10CFR430_32] | DOE 测试程序光效测试与 CCMS 认证 | — | — | DOE | [R:US-L5-DOE-003] |

#### E.6 儿童玩具（含儿童产品通用要求）
- 「儿童产品」= 主要供 12 岁及以下儿童使用（看标签、包装、广告与通常认知）[SRC-US-GOV-ECFR-16CFR1200]。须：CPSC 认可第三方实验室检测 + CPC + 周期性复测 + 追踪标签；铅（基材 100 ppm、涂层 90 ppm）、邻苯（8 种各 0.1%，玩具与儿童护理用品）[SRC-US-GOV-ECFR-16CFR1107] [SRC-US-GOV-USC-15USC1278A] [SRC-US-GOV-ECFR-16CFR1307] [R:US-L5-CPSIA-001] [R:US-L5-CPSIA-002] [R:US-L5-CPSIA-003] [R:US-L5-CPSIA-004] [R:US-L5-CPSIA-005]。
- 玩具标准为 ASTM F963-23（16 CFR 1250）；新增吸水珠专项要求（2026-03-12 起）和 4 岁以下颈圈浮具专项要求（2026-06-15 起）[SRC-US-GOV-ECFR-16CFR1250] [SRC-US-GOV-FR-2025-22643] [SRC-US-GOV-FR-2025-22827] [R:US-L5-TOY-001] [R:US-L5-TOY-005] [R:US-L5-TOY-006]。
- 3 岁以下儿童用品不得含小零件（禁售）；3–6 岁含小零件的玩具、气球、小球、弹珠须有窒息警示，且亚马逊详情页上也必须展示同样警示 [SRC-US-GOV-ECFR-16CFR1500_19] [SRC-US-GOV-USC-15USC1278] [R:US-L5-TOY-002] [R:US-L5-TOY-003]。
- 磁力珠等可分离小强磁产品磁通指数须 <50；仿真枪须有橙色枪口标记；草坪飞镖禁售；联网玩具须遵守 COPPA [SRC-US-GOV-ECFR-16CFR1262] [SRC-US-GOV-ECFR-16CFR1272] [R:US-L5-MAG-001] [R:US-L5-TOY-007] [R:US-L5-FHSA-003] [R:US-L5-FTC-011]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【强制合规】儿童产品须由 CPSC 认可的第三方实验室检测并出具 CPC [SRC-US-GOV-ECFR-16CFR1107] [SRC-US-GOV-ECFR-16CFR1110] [SRC-US-GOV-ECFR-16CFR1112] | CPSC 认可第三方实验室检测报告；儿童产品证书 CPC | 检测与证书记录保存 | — | CPSC | [R:US-L5-CPSIA-001] |
| 【强制合规】儿童产品可触及部件基材铅含量 ≤100 ppm [SRC-US-GOV-USC-15USC1278A] [SRC-US-GOV-FR-2026-12695] [SRC-US-GOV-ECFR-16CFR1110] | 可触及基材总铅检测（100 ppm）；在 CPC 中列明 15 U.S.C. 1278a 铅含量要求 | — | — | CPSC | [R:US-L5-CPSIA-002] |
| 【强制合规】油漆/表面涂层铅含量 ≤90 ppm（儿童用品与家具） [SRC-US-GOV-ECFR-16CFR1303] [SRC-US-GOV-USC-15USC1278A] | 涂层铅含量检测（90 ppm）；CPC（儿童产品）或 GCC（家具、油漆等非儿童产品） | — | — | CPSC | [R:US-L5-CPSIA-003] |
| 【强制合规】儿童玩具与儿童护理用品 8 种邻苯二甲酸酯各 ≤0.1% [SRC-US-GOV-ECFR-16CFR1307] [SRC-US-GOV-ECFR-16CFR1110] | 邻苯二甲酸酯（8 种）检测；在 CPC 中列明 16 CFR 1307 | — | — | CPSC | [R:US-L5-CPSIA-004] |
| 【强制合规】儿童产品及包装须有永久性追踪标签 [SRC-US-GOV-USC-15USC2063] | — | — | 产品与包装追踪标签；必备语句：产品本体和包装须有永久性追踪标签（制造商/贴牌商、生产地、生产日期、批次） | CPSC | [R:US-L5-CPSIA-005] |
| 【强制合规】玩具须符合 ASTM F963-23（16 CFR 1250） [SRC-US-GOV-ECFR-16CFR1250] [SRC-US-GOV-ECFR-16CFR1500_48] [SRC-US-GOV-ECFR-16CFR1500_49] | ASTM F963-23 全项检测报告；CPC 列明 16 CFR 1250；玩具磁铁条款 | — | F963 要求的警示和年龄标识 | CPSC | [R:US-L5-TOY-001] |
| 【禁售】供 3 岁以下儿童的玩具/用品不得含小零件；禁止事项：供 3 岁以下儿童的产品含小零件即禁售 [SRC-US-GOV-ECFR-16CFR1500_18] [SRC-US-GOV-ECFR-16CFR1501] | 小零件及使用/滥用测试（16 CFR 1500.51–1500.53、1501） | — | — | CPSC | [R:US-L5-TOY-002] |
| 【强制合规】含小零件/气球/小球/弹珠的玩具须加窒息警示，网页广告同样须展示 [SRC-US-GOV-USC-15USC1278] [SRC-US-GOV-ECFR-16CFR1500_19] [SRC-US-GOV-ECFR-16CFR1500_20] | — | — | 包装与说明书窒息警示；网络广告（商品详情页）展示同一警示；必备语句：小零件：WARNING: CHOKING HAZARD--Small parts. Not for children under 3 yrs. / 气球：WARNING: CHOKING HAZARD--Children under 8 yrs. can choke or suffocate on uninflated or broken balloons. Adult supervision required. Keep uninflated balloons from children. Discard broken balloons at once. / 小球：WARNING: CHOKING HAZARD--This toy is a small ball (或 contains a small ball). Not for children under 3 yrs. / 弹珠：WARNING: CHOKING HAZARD--This toy is a marble (或 contains a marble). Not for children under 3 yrs. / 上述警示须同时出现在亚马逊详情页（网络广告）上 | CPSC | [R:US-L5-TOY-003] |
| 【强制合规】120V 市电供电的儿童电动玩具须符合 16 CFR 1505 [SRC-US-GOV-ECFR-16CFR1505] | 16 CFR 1505 检测 | — | 1505 规定的标签与说明 | CPSC | [R:US-L5-TOY-004] |
| 【强制合规】吸水珠（水晶泥/water beads）玩具专项要求（2026-03-12 起） [SRC-US-GOV-ECFR-16CFR1250] [SRC-US-GOV-FR-2025-22643] | 吸水珠尺寸膨胀与丙烯酰胺检测（16 CFR 1250.4） | — | 吸水珠警示（产品、包装、珠子容器；无包装的须挂牌） | CPSC | [R:US-L5-TOY-005] |
| 【强制合规】幼儿颈圈游泳圈（neck float）专项要求（2026-06-15 起） [SRC-US-GOV-ECFR-16CFR1250] [SRC-US-GOV-FR-2025-22827] [SRC-US-GOV-FR-2026-09977] | 16 CFR 1250.5 颈圈浮具检测；CPC 列明 16 CFR 1250.5 | — | 颈圈浮具警示标签（按 1250.5） | CPSC | [R:US-L5-TOY-006] |
| 【强制合规】仿真枪/玩具枪须有橙色枪口塞等法定标记 [SRC-US-GOV-ECFR-16CFR1272] | — | — | 法定标记（blaze orange 枪口塞/枪管环/透明/亮色） | CPSC | [R:US-L5-TOY-007] |
| 【强制合规】可分离小磁铁产品（磁力珠/磁力套装、磁性首饰、解压磁铁）磁通指数须 <50 [SRC-US-GOV-ECFR-16CFR1262] | 磁通指数检测（16 CFR 1262.4）；GCC（非儿童产品）或 CPC（儿童产品）列明 16 CFR 1262 | — | — | CPSC | [R:US-L5-MAG-001] |
| 【禁售】草坪飞镖（lawn darts）禁售；禁止事项：草坪飞镖禁售 [SRC-US-GOV-ECFR-16CFR1306] | — | — | — | CPSC | [R:US-L5-FHSA-003] |
| 【强制合规】面向 13 岁以下儿童、收集个人信息的联网玩具/App 须遵守 COPPA [SRC-US-GOV-ECFR-16CFR312] | — | COPPA 隐私政策与家长同意机制 | — | FTC | [R:US-L5-FTC-011] |

#### E.7 婴童
- 《婴儿安全睡眠法》：倾角 >10° 的婴儿倾斜睡眠产品与软垫床围一律禁售（网状无软垫床围除外）[SRC-US-GOV-ECFR-16CFR1310] [SRC-US-GOV-ECFR-16CFR1309] [R:US-L5-SLEEP-001] [R:US-L5-SLEEP-002]。
- 20 类耐用婴幼儿产品各有 16 CFR 12xx 强制标准，须第三方检测、CPC，并附产品注册卡 [SRC-US-GOV-ECFR-16CFR1130] [R:US-L5-CPSIA-006]。2025–2026 年多项标准更新：哺乳枕（2025-04-23）、婴儿支撑垫/躺垫（2025-05-05）、婴儿床垫 F2933-25（2026-05-03）、门栏与挂桌椅（2026-07-19）、秋千（2026-07-25）、全尺寸婴儿床 F1169-25（2026-08-01）、幼儿床 F1821-26（2026-08-29）[R:US-L5-SLEEP-008] [R:US-L5-SLEEP-007] [R:US-L5-SLEEP-006] [R:US-L5-JUV-006] [R:US-L5-JUV-003] [R:US-L5-JUV-005] [R:US-L5-SLEEP-005] [R:US-L5-JUV-008]。
- 婴儿奶瓶/学饮杯不得用聚碳酸酯 [SRC-US-GOV-ECFR-21CFR177_1580] [R:US-L5-FCM-003]；汽车安全座椅适用 NHTSA FMVSS 213，侧碰 213a 合规日推迟至 2026-12-05 [SRC-US-GOV-FR-2026-18380] [R:US-L5-NHTSA-004]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【强制合规】耐用婴幼儿产品须附产品注册卡并在产品上永久标识 [SRC-US-GOV-ECFR-16CFR1130] | — | — | 产品注册卡（Product Registration Card）；产品永久标识 | CPSC | [R:US-L5-CPSIA-006] |
| 【禁售】婴儿倾斜睡眠产品（睡眠面倾角 >10°）禁售；禁止事项：倾斜睡眠产品禁售 [SRC-US-GOV-ECFR-16CFR1310] [SRC-US-GOV-USC-15USC2057D] | — | — | — | CPSC | [R:US-L5-SLEEP-001] |
| 【禁售】婴儿床围（crib bumpers）禁售；禁止事项：婴儿床围禁售 [SRC-US-GOV-ECFR-16CFR1309] [SRC-US-GOV-USC-15USC2057E] | — | — | — | CPSC | [R:US-L5-SLEEP-002] |
| 【强制合规】婴儿睡眠产品须符合 16 CFR 1236（ASTM F3118-17a） [SRC-US-GOV-ECFR-16CFR1236] [SRC-US-GOV-ECFR-16CFR1130] | 16 CFR 1236（ASTM F3118-17a 及修改）检测；CPC | — | 产品注册卡与警示标签 | CPSC | [R:US-L5-SLEEP-003] |
| 【强制合规】摇篮/睡篮与床边睡床须符合 16 CFR 1218 / 1222 [SRC-US-GOV-ECFR-16CFR1218] [SRC-US-GOV-ECFR-16CFR1222] | ASTM F2194-25 / ASTM F2906-23（按 16 CFR 修改）检测；CPC | — | — | CPSC | [R:US-L5-SLEEP-004] |
| 【强制合规】婴儿床与游戏床须符合 16 CFR 1219/1220/1221 [SRC-US-GOV-ECFR-16CFR1219] [SRC-US-GOV-ECFR-16CFR1220] [SRC-US-GOV-ECFR-16CFR1221] | ASTM F1169 / F406 检测；CPC | — | 警示标签、产品注册卡（16 CFR 1130） | CPSC | [R:US-L5-SLEEP-005] |
| 【强制合规】婴儿床垫须符合 16 CFR 1241（ASTM F2933-25，2026-05-03 起） [SRC-US-GOV-ECFR-16CFR1241] [SRC-US-GOV-FR-2026-02855] | 16 CFR 1241 检测；CPC（含 1241、1632/1633） | — | — | CPSC | [R:US-L5-SLEEP-006] |
| 【强制合规】婴儿支撑垫（躺垫/定位枕/婴儿 lounger）须符合 16 CFR 1243（2025-05-05 起） [SRC-US-GOV-ECFR-16CFR1243] [SRC-US-GOV-FR-2024-25181] | 16 CFR 1243 检测；CPC | — | 1243 规定的警示与注册卡 | CPSC | [R:US-L5-SLEEP-007] |
| 【强制合规】哺乳枕须符合 16 CFR 1242（2025-04-23 起） [SRC-US-GOV-ECFR-16CFR1242] [SRC-US-GOV-FR-2024-24403] | 16 CFR 1242 检测；CPC | — | — | CPSC | [R:US-L5-SLEEP-008] |
| 【强制合规】婴儿车/推车须符合 16 CFR 1227（ASTM F833-21） [SRC-US-GOV-ECFR-16CFR1227] [SRC-US-GOV-ECFR-16CFR1130] | ASTM F833-21 检测；CPC | — | — | CPSC | [R:US-L5-JUV-001] |
| 【强制合规】婴儿背带/背巾/提篮须符合 16 CFR 1225/1226/1228/1230 [SRC-US-GOV-ECFR-16CFR1225] [SRC-US-GOV-ECFR-16CFR1226] [SRC-US-GOV-ECFR-16CFR1228] | ASTM F2050 / F2236-24 / F2907 / F2549 对应检测；CPC | — | — | CPSC | [R:US-L5-JUV-002] |
| 【强制合规】高脚椅/增高座椅/挂桌椅/儿童折叠椅凳须符合 16 CFR 1231/1237/1233/1232 [SRC-US-GOV-ECFR-16CFR1231] [SRC-US-GOV-ECFR-16CFR1237] [SRC-US-GOV-ECFR-16CFR1233] | ASTM F404 / F2640 / F1235 / F2613 检测；CPC | — | — | CPSC | [R:US-L5-JUV-003] |
| 【强制合规】婴儿浴座与婴儿浴盆须符合 16 CFR 1215/1234 [SRC-US-GOV-ECFR-16CFR1215] [SRC-US-GOV-ECFR-16CFR1234] | ASTM F1967 / F2670 检测；CPC | — | 防溺水警示 | CPSC | [R:US-L5-JUV-004] |
| 【强制合规】学步车、秋千、弹跳椅、固定活动中心须符合 16 CFR 1216/1223/1229/1238 [SRC-US-GOV-ECFR-16CFR1216] [SRC-US-GOV-ECFR-16CFR1223] [SRC-US-GOV-ECFR-16CFR1229] | ASTM F977 / F2088 / F2167 / F2012 检测；CPC | — | — | CPSC | [R:US-L5-JUV-005] |
| 【强制合规】儿童安全门栏/围栏须符合 16 CFR 1239（2026-07-19 起 ASTM F1004-25） [SRC-US-GOV-ECFR-16CFR1239] [SRC-US-GOV-FR-2026-06306] | ASTM F1004 检测；CPC | — | — | CPSC | [R:US-L5-JUV-006] |
| 【强制合规】尿布台/婴儿换尿布产品须符合 16 CFR 1235 [SRC-US-GOV-ECFR-16CFR1235] | ASTM F2388 检测；CPC | — | — | CPSC | [R:US-L5-JUV-007] |
| 【强制合规】幼儿床与儿童便携床栏须符合 16 CFR 1217/1224 [SRC-US-GOV-ECFR-16CFR1217] [SRC-US-GOV-ECFR-16CFR1224] [SRC-US-GOV-FR-2026-09640] | ASTM F1821 / F2085 检测；CPC | — | — | CPSC | [R:US-L5-JUV-008] |
| 【强制合规】安抚奶嘴与摇铃须符合 16 CFR 1511 / 1510 [SRC-US-GOV-ECFR-16CFR1511] [SRC-US-GOV-ECFR-16CFR1510] | 16 CFR 1511 / 1510 检测；CPC | — | 奶嘴警示；必备语句：安抚奶嘴包装须有：Warning—Do Not Tie Pacifier Around Child's Neck as it Presents a Strangulation Danger. | CPSC | [R:US-L5-JUV-009] |
| 【强制合规】聚碳酸酯（含 BPA）不得用于婴儿奶瓶和学饮杯；禁止事项：婴儿奶瓶、学饮杯不得使用聚碳酸酯 [SRC-US-GOV-ECFR-21CFR177_1580] | — | 材质声明/检测（PP、PPSU、硅胶、玻璃等） | — | FDA | [R:US-L5-FCM-003] |
| 【强制合规】儿童汽车安全座椅须符合 FMVSS 213（侧碰 213a 合规日推迟至 2026-12-05）并附注册卡 [SRC-US-GOV-ECFR-49CFR571_213A] [SRC-US-GOV-FR-2026-18380] [SRC-US-GOV-ECFR-49CFR571] | FMVSS 213 / 213a 自我认证与测试 | — | 标签、说明书、49 CFR 588 注册卡 | NHTSA | [R:US-L5-NHTSA-004] |

#### E.8 儿童用品与童装
- 儿童睡衣（0–14 码）须通过阻燃测试或符合紧身尺寸并挂黄色吊牌 [SRC-US-GOV-ECFR-16CFR1615] [R:US-L5-CHILD-001]；童装帽/颈部不得有拉绳 [SRC-US-GOV-ECFR-16CFR1120] [R:US-L5-CHILD-002]。
- 儿童双层床、儿童折叠椅凳有专门标准 [R:US-L5-CHILD-004] [R:US-L5-JUV-003]；美术材料须按 ASTM D4236 评估并标注 [SRC-US-GOV-ECFR-16CFR1500_14] [R:US-L5-CHILD-005]。
- 童装同样适用 CPC、铅、追踪标签（E.6）和纺织标签（E.22）。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【强制合规】儿童睡衣（0–14 码）须符合阻燃标准 16 CFR 1615/1616 [SRC-US-GOV-ECFR-16CFR1615] [SRC-US-GOV-ECFR-16CFR1616] | 16 CFR 1615/1616 阻燃检测或紧身尺寸核查；CPC | — | 紧身睡衣黄色吊牌与永久标签；必备语句：紧身睡衣须挂黄色吊牌：For child's safety, garment should fit snugly. This garment is not flame resistant. Loose-fitting garment is more likely to catch fire. | CPSC | [R:US-L5-CHILD-001] |
| 【强制合规】童装上衣拉绳要求（2T–16 码） [SRC-US-GOV-ECFR-16CFR1120] | — | 按 ASTM F1816-97 设计核查 | — | CPSC | [R:US-L5-CHILD-002] |
| 【强制合规】双层床须防夹持（16 CFR 1213 / 1513） [SRC-US-GOV-ECFR-16CFR1213] [SRC-US-GOV-ECFR-16CFR1513] | 16 CFR 1213/1513 检测；GCC（成人）或 CPC（儿童） | — | 双层床警示标签 | CPSC | [R:US-L5-CHILD-004] |
| 【强制合规】美术材料须按 LHAMA / ASTM D4236 评估和标签 [SRC-US-GOV-ECFR-16CFR1500_14] | — | 毒理学家评估（LHAMA） | Conforms to ASTM D-4236 声明及警示；必备语句：美术材料标签须含：Conforms to ASTM D-4236 | CPSC | [R:US-L5-CHILD-005] |

#### E.9 食品接触
- 接触食品的材料只能使用 FDA 许可物质（21 CFR 174–178、GRAS、FCN），按对应条款做萃取测试 [SRC-US-GOV-ECFR-21CFR177] [R:US-L5-FCM-001]；陶瓷铅镉溶出须合规，装饰陶瓷须标「Not for Food Use」[SRC-US-GOV-ECFR-21CFR109_16] [R:US-L5-FCM-002]。
- 含 PTFE 等有意添加 PFAS 的炊具在明尼苏达（2025 起）、缅因（2026 起）禁售 [SRC-US-GOV-MN-STAT-116-943] [R:US-L5-PFAS-002]；加州 Prop 65 对含铅陶瓷、含 BPA 制品常见 [R:US-L5-PROP65-002]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【强制合规】食品接触材料只能使用 FDA 许可物质并满足迁移/萃取限值 [SRC-US-GOV-ECFR-21CFR174] [SRC-US-GOV-ECFR-21CFR177] | 按 21 CFR 175–177 对应条款的萃取/迁移测试 | 原料供应商 FDA 合规声明（DoC） | — | FDA | [R:US-L5-FCM-001] |
| 【强制合规】陶瓷/搪瓷餐具铅镉溶出须合规，装饰性陶瓷须标「Not for Food Use」 [SRC-US-GOV-ECFR-21CFR109_16] | 铅、镉溶出测试（ASTM C738 等） | — | 装饰性陶瓷标签 | FDA | [R:US-L5-FCM-002] |
| 【强制合规】有意添加 PFAS 的炊具：明尼苏达（2025）、缅因（2026）等州禁售；禁止事项：不得向明尼苏达、缅因销售含有意添加 PFAS 的炊具（含 PTFE 不粘涂层） [SRC-US-GOV-MN-STAT-116-943] [SRC-US-GOV-ME-DEP-PFAS-PRODUCTS] | — | 涂层材料声明（PTFE/含氟聚合物与否） | — | 各州环保部门（MN PCA、ME DEP 等） | [R:US-L5-PFAS-002] |

#### E.10 化妆品
- MoCRA：设施注册（每两年续期）、产品列名（每年更新）、标签须有美国境内联系方式（2024-12-29 起）、严重不良事件 15 个工作日内报告 [SRC-US-GOV-USC-21USC364C] [SRC-US-GOV-USC-21USC364E] [SRC-US-GOV-USC-21USC364A] [R:US-L5-COSM-001] [R:US-L5-COSM-002] [R:US-L5-COSM-003] [R:US-L5-COSM-004]。
- 化妆品不得作药品宣称（生发、美白、祛痘、SPF、抗菌等）；含氢醌的 OTC 美白产品、含塑料微珠的冲洗型产品禁售 [SRC-US-GOV-FDA-HYDROQUINONE-OTC] [SRC-US-GOV-USC-21USC331] [R:US-L5-COSM-007] [R:US-L5-DRUG-004] [R:US-L5-COSM-008]。
- 色素须为 FDA 批准且须认证的批次认证；汞等禁用成分 [R:US-L5-COSM-005] [R:US-L5-COSM-006]。滑石粉石棉检测规则已于 2025-11-28 撤回 [SRC-US-GOV-FR-2025-21407]。
- 州法：加州《无毒化妆品法》禁 24 种成分（二手来源，待核）、加州/明尼苏达/缅因禁含 PFAS 化妆品 [R:US-L5-STATE-006] [R:US-L5-PFAS-003]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【强制合规】化妆品生产/加工设施须在 FDA 注册（MoCRA），每两年续期 [SRC-US-GOV-USC-21USC364C] [SRC-US-GOV-FDA-COSMETIC-REGISTRATION] [SRC-US-GOV-FDA-MOCRA] | — | 化妆品设施注册（Facility Registration）；美国代理人（外国设施） | — | FDA | [R:US-L5-COSM-001] |
| 【强制合规】化妆品须由责任人在 FDA 完成产品列名并每年更新（MoCRA） [SRC-US-GOV-USC-21USC364C] [SRC-US-GOV-FDA-COSMETIC-REGISTRATION] | — | 化妆品产品列名（Product Listing） | — | FDA | [R:US-L5-COSM-002] |
| 【强制合规】化妆品标签：英文、成分降序、净含量、责任方，以及美国境内联系方式（2024-12-29 起） [SRC-US-GOV-ECFR-21CFR701] [SRC-US-GOV-ECFR-21CFR740] [SRC-US-GOV-USC-21USC364E] | — | — | 英文标签要素（701.3 成分、701.11–701.13 品名与净含量、701.12 责任方）；美国境内联系方式（地址/电话/网站）；740 规定警示（如气雾剂、泡泡浴、晒黑类无防晒成分等）；必备语句：化妆品标签须含美国境内地址、电话或网站，用于接收不良事件报告 | FDA | [R:US-L5-COSM-003] |
| 【强制合规】化妆品严重不良事件 15 个工作日内报告，并保存安全性证明记录 [SRC-US-GOV-USC-21USC364A] [SRC-US-GOV-FDA-MOCRA] | — | 严重不良事件报告（MedWatch 3500A）；安全性证明与不良事件记录 | — | FDA | [R:US-L5-COSM-004] |
| 【强制合规】化妆品只能使用 FDA 批准的色素，FD&C/D&C 色素须批次认证 [SRC-US-GOV-ECFR-21CFR73] [SRC-US-GOV-ECFR-21CFR74] | — | 色素合规核查（21 CFR 73/74/82） | — | FDA | [R:US-L5-COSM-005] |
| 【强制合规】化妆品禁用/限用成分（21 CFR 700.11–700.35，如汞、氯仿、六氯酚）；禁止事项：配方不得含 21 CFR 700 subpart B 禁用成分 [SRC-US-GOV-ECFR-21CFR700] [SRC-US-GOV-ECFR-21CFR700_13] [SRC-US-GOV-FR-2025-21407] | 高风险品类（美白霜、进口膏霜）重金属/汞检测 | — | — | FDA | [R:US-L5-COSM-006] |
| 【强制合规】化妆品不得作药品宣称（治疗、生发、美白祛斑、祛痘、防晒等即按药品管理） [SRC-US-GOV-ECFR-21CFR701] [SRC-US-GOV-FDA-HYDROQUINONE-OTC] | — | 宣称审核：化妆品只可作外观/清洁/美化宣称 | — | FDA | [R:US-L5-COSM-007] |
| 【禁售】含塑料微珠的冲洗型化妆品（含牙膏）禁售；禁止事项：冲洗型产品不得有意添加塑料微珠 [SRC-US-GOV-USC-21USC331] | — | — | — | FDA | [R:US-L5-COSM-008] |
| 【强制合规】煤焦油染发剂须印法定警示语并附皮肤测试说明 [SRC-US-GOV-USC-21USC361] | — | — | 煤焦油染发剂 Caution 警示语与皮肤测试说明；必备语句：Caution—This product contains ingredients which may cause skin irritation on certain individuals and a preliminary test according to accompanying directions should first be made. This product must not be used for dyeing the eyelashes or eyebrows; to do so may cause blindness. | FDA | [R:US-L5-COSM-009] |
| 【禁售】含氢醌的非处方美白/祛斑产品禁售（自 2020-09-23）；禁止事项：含氢醌的 OTC 美白/祛斑霜、含汞美白霜禁售 [SRC-US-GOV-FDA-HYDROQUINONE-OTC] [SRC-US-GOV-ECFR-21CFR700_13] | — | — | — | FDA CDER | [R:US-L5-DRUG-004] |
| 【强制合规】有意添加 PFAS 的化妆品：加州（2025）、明尼苏达（2025）、缅因（2026）等州禁售；禁止事项：不得向上述州销售含有意添加 PFAS 的化妆品 [SRC-US-GOV-MN-STAT-116-943] [SRC-US-GOV-ME-DEP-PFAS-PRODUCTS] [SRC-US-S3-MORGANLEWIS-PFAS-TEXTILES-2025] | — | 配方 INCI 核查（PTFE、perfluoro-/polyfluoro- 成分等） | — | 各州环保部门（MN PCA、ME DEP 等） | [R:US-L5-PFAS-003] |
| 【强制合规】加州《无毒化妆品法》禁止 24 种成分（2025-01-01 起），多州跟进（二手来源，待核）；禁止事项：不得向加州销售含 AB 2762 所列成分的化妆品 [SRC-US-S3-SHEPPARD-CA-TFCA] | — | 配方 INCI 对照禁用清单核查 | — | 州/市政府 | [R:US-L5-STATE-006] |

#### E.11 个护健康
- 防晒、免洗洗手液、含氟牙膏、止痛贴等是 OTC 药品：药品注册列名（NDC）、Drug Facts 标签、符合专论；2026 年防晒专论新增 bemotrizinol、剔除 PABA 与水杨酸三乙醇胺 [SRC-US-GOV-ECFR-21CFR207] [SRC-US-GOV-FR-2026-11578] [SRC-US-GOV-FR-2026-18551] [R:US-L5-DRUG-001] [R:US-L5-DRUG-002] [R:US-L5-DRUG-003]。
- 太阳镜/老花镜须落球抗冲击测试，属 I 类器械须注册列名 [SRC-US-GOV-ECFR-21CFR801_410] [R:US-L5-DEV-006]；晒黑灯属 II 类器械且有辐射标准 [R:US-L5-RAD-002]。
- 夏威夷禁售含羟苯甲酮/甲氧基肉桂酸辛酯的防晒霜 [R:US-L5-STATE-004]；手持吹风机须防浸水保护 [R:US-L5-SPH-001]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【强制合规】手持吹风机须有整体防浸水保护（SPH 清单） [SRC-US-GOV-ECFR-16CFR1120] | UL 859 / UL 1727 防浸水保护测试 | — | — | CPSC | [R:US-L5-SPH-001] |
| 【强制合规】成人便携床栏须符合 16 CFR 1270（ASTM F3186-17） [SRC-US-GOV-ECFR-16CFR1270] | ASTM F3186-17 检测；GCC | — | 1270 规定的警示与说明 | CPSC | [R:US-L5-HOME-006] |
| 【需政府许可】晒黑灯/日光灯（sunlamp）须符合 21 CFR 1040.20 且属 II 类医疗器械 [SRC-US-GOV-ECFR-21CFR1040_20] [SRC-US-GOV-ECFR-21CFR878_4635] | — | FDA 510(k) 与器械注册列名 | 1040.20 警示标签与 18 岁以下禁用警示 | FDA CDRH | [R:US-L5-RAD-002] |
| 【强制合规】OTC 药品须做 FDA 药品企业注册与产品列名（NDC），并符合 OTC 专论或经批准 [SRC-US-GOV-ECFR-21CFR207] [SRC-US-GOV-ECFR-21CFR201_66] | — | 药品企业注册 + 产品列名（NDC）；OTC 专论符合性或 NDA 批准；cGMP（21 CFR 210/211） | Drug Facts 标签（21 CFR 201.66） | FDA CDER | [R:US-L5-DRUG-001] |
| 【强制合规】防晒产品按 OTC 药品管理（专论 M020），SPF/广谱宣称须测试 [SRC-US-GOV-FR-2026-11578] [SRC-US-GOV-FR-2026-18551] [SRC-US-GOV-ECFR-21CFR207] | SPF 与广谱（broad spectrum）测试 | 药品注册与列名（NDC） | Drug Facts 标签与防晒标签要求 | FDA CDER | [R:US-L5-DRUG-002] |
| 【强制合规】免洗洗手液等抗菌产品按 OTC 药品管理 [SRC-US-GOV-ECFR-21CFR207] [SRC-US-GOV-ECFR-21CFR201_66] | 乙醇/异丙醇含量与甲醇杂质检测 | 药品注册与列名（NDC） | Drug Facts 标签 | FDA CDER | [R:US-L5-DRUG-003] |
| 【强制合规】太阳镜和非处方眼镜须通过抗冲击（落球）测试；属 I 类器械 [SRC-US-GOV-ECFR-21CFR801_410] [SRC-US-GOV-ECFR-21CFR886_5850] [SRC-US-GOV-ECFR-21CFR807] | 落球抗冲击测试（801.410） | 器械企业注册与列名（I 类） | — | FDA CDRH | [R:US-L5-DEV-006] |
| 【强制合规】夏威夷禁售含羟苯甲酮、甲氧基肉桂酸辛酯的防晒霜（2021-01-01 起）（官方页面仅见摘要，待核）；禁止事项：不得向夏威夷销售含 oxybenzone/octinoxate 的防晒产品 [SRC-US-GOV-HI-SB2621-2020] | — | — | — | 州/市政府 | [R:US-L5-STATE-004] |

#### E.12 医疗器械
- 有诊断/治疗/缓解疾病用途即为医疗器械，多数 II 类须 510(k)；企业（含首次进口商）须注册、器械须列名并缴年费；标签含 UDI；质量体系 QMSR 自 2026-02-02 起与 ISO 13485 对齐 [SRC-US-GOV-ECFR-21CFR807] [SRC-US-GOV-ECFR-21CFR820] [R:US-L5-DEV-001] [R:US-L5-DEV-002] [R:US-L5-DEV-003]。
- 隐形眼镜（含无度数美瞳）须凭处方核验销售，跨境卖家实际无法合规销售 [SRC-US-GOV-ECFR-16CFR315] [R:US-L5-DEV-005]；OTC 助听器须符合 21 CFR 800.30 [R:US-L5-DEV-004]。
- 不得把 FDA「注册」说成「FDA 批准/认证」[SRC-US-GOV-ECFR-21CFR807_39] [SRC-US-GOV-ECFR-21CFR207_77] [R:US-L5-DRUG-005]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【强制合规】不得把 FDA 注册/列名宣传成「FDA 批准/认证」 [SRC-US-GOV-ECFR-21CFR207_77] [SRC-US-GOV-ECFR-21CFR807_39] | — | Listing 和包装去除「FDA approved/certified/registered」类表述（除非确有批准/许可） | — | FDA CDER | [R:US-L5-DRUG-005] |
| 【需政府许可】医疗器械须按分类取得上市许可（多数 II 类须 510(k)） [SRC-US-GOV-ECFR-21CFR807] | — | 510(k) 许可 / De Novo / PMA（按分类）；器械分类判定依据 | — | FDA CDRH | [R:US-L5-DEV-001] |
| 【强制合规】医疗器械企业（含外国工厂与首次进口商）须注册并做器械列名、缴年费 [SRC-US-GOV-ECFR-21CFR807] | — | FDA 器械企业注册 + 器械列名（FURLS/DRLM）；美国代理人（外国企业） | — | FDA CDRH | [R:US-L5-DEV-002] |
| 【强制合规】医疗器械标签（含 UDI）、质量管理体系（QMSR，2026-02-02 起对齐 ISO 13485）与不良事件报告 [SRC-US-GOV-ECFR-21CFR801] [SRC-US-GOV-ECFR-21CFR820] [SRC-US-GOV-ECFR-21CFR803] | — | QMSR/ISO 13485 质量体系；MDR 不良事件报告程序（803） | 21 CFR 801 标签与 UDI | FDA CDRH | [R:US-L5-DEV-003] |
| 【强制合规】OTC 助听器须符合 21 CFR 800.30；个人声音放大器（PSAP）不得宣称改善听力损失 [SRC-US-GOV-ECFR-21CFR800_30] | — | 器械注册列名（必要时 510(k)） | 800.30 规定的外包装与说明书标签 | FDA CDRH | [R:US-L5-DEV-004] |
| 【禁售】隐形眼镜（含美瞳/装饰性隐形眼镜）无处方核验不得销售；禁止事项：不得在无处方核验的情况下销售隐形眼镜/美瞳 [SRC-US-GOV-ECFR-16CFR315] | — | 隐形眼镜本身须有 FDA 上市许可与注册列名 | — | FDA CDRH | [R:US-L5-DEV-005] |
| 【需政府许可】家用诊断/监测器械（血压计、血氧仪、体温计、血糖仪、检测试剂）多须 510(k) [SRC-US-GOV-ECFR-21CFR807] [SRC-US-GOV-ECFR-21CFR801] | — | 510(k) 许可号（K 号）与注册列名 | 21 CFR 801 标签与 UDI | FDA CDRH | [R:US-L5-DEV-008] |
| 【需政府许可】理疗类器械（TENS/EMS、红光/LED 治疗、激光/IPL 脱毛、治疗用按摩器）按分类须 510(k) [SRC-US-GOV-ECFR-21CFR807] [SRC-US-GOV-ECFR-21CFR801] | — | 510(k) 许可与注册列名；宣称与许可适应症一致性审核 | — | FDA CDRH | [R:US-L5-DEV-009] |

#### E.13 农药与抗菌宣称
- 宣称驱虫、杀虫、消毒、杀菌、抗病毒的物质即为农药，须 EPA 登记（另须州登记）[SRC-US-GOV-ECFR-40CFR152_15] [R:US-L5-FIFRA-001]。
- 处理物品豁免只允许宣称「保护产品本身」；宣称保护人体健康（杀死 99.9% 细菌、防病毒）就须登记 [SRC-US-GOV-ECFR-40CFR152_25] [R:US-L5-FIFRA-002]；25(b) 最低风险产品须严格符合成分与标签条件 [R:US-L5-FIFRA-003]。
- UV 消毒器、超声波驱虫器、灭蚊灯等农药器械无需登记，但生产企业须有 EPA Est. No. 并标注，进口前须提交到货通知 [SRC-US-GOV-ECFR-40CFR152_500] [R:US-L5-FIFRA-004] [R:US-L6-IMPORT-002]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【需政府许可】农药（含消毒剂、驱虫剂、杀虫剂、灭鼠剂）须在 EPA 登记并取得 EPA Reg. No. [SRC-US-GOV-ECFR-40CFR152_15] [SRC-US-GOV-ECFR-40CFR167] | — | EPA 农药登记（EPA Reg. No.）；州农药登记 | EPA 批准的标签（含 EPA Reg. No. 与 EPA Est. No.） | EPA | [R:US-L5-FIFRA-001] |
| 【强制合规】处理物品豁免：抗菌/防霉处理的普通商品只能宣称保护物品本身 [SRC-US-GOV-ECFR-40CFR152_25] | — | 抗菌剂已登记且用于该物品的证明（供应商资料） | 宣称限于「保护产品本身」，不得作公共卫生宣称 | EPA | [R:US-L5-FIFRA-002] |
| 【强制合规】25(b) 最低风险农药（如精油驱蚊产品）须严格符合成分与标签条件 [SRC-US-GOV-ECFR-40CFR152_25] | — | 配方核对 152.25(f) 活性/惰性成分表；州登记（多数州要求） | 标签列明全部活性与惰性成分及百分比、生产者名称地址 | EPA | [R:US-L5-FIFRA-003] |
| 【强制合规】农药器械（紫外消毒器、超声波驱虫器、灭蚊灯、宣称杀菌的净化器）无需登记但须有生产企业注册号且不得虚假宣称 [SRC-US-GOV-ECFR-40CFR152_500] [SRC-US-GOV-ECFR-40CFR167] | — | 生产企业 EPA 注册（EPA Est. No.）并年度报告；功效宣称的依据（避免虚假宣称） | 标签标注 EPA Est. No. | EPA | [R:US-L5-FIFRA-004] |

#### E.14 化学品
- 家用危险化学品须 FHSA 警示标签；部分须儿童防护包装（PPPA）[SRC-US-GOV-ECFR-16CFR1500_121] [SRC-US-GOV-ECFR-16CFR1700] [R:US-L5-FHSA-001] [R:US-L5-PPPA-001]。
- 含二氯甲烷、TCE 的消费级产品已禁售；含 PCE 产品 2027-03-08 起零售商不得分销 [SRC-US-GOV-ECFR-40CFR751_107] [SRC-US-GOV-ECFR-40CFR751_305] [SRC-US-GOV-ECFR-40CFR751_605] [R:US-L5-TSCA-004]。
- HFC：GWP≥150 的气雾剂（如 HFC-134a 罐装除尘气）2025-01-01 起禁止制造/进口，2028 年起禁止销售；制冷剂原则上只卖给持证技师 [SRC-US-GOV-ECFR-40CFR84_54] [SRC-US-GOV-ECFR-40CFR82_154] [R:US-L5-HFC-001] [R:US-L5-HFC-002]。
- TSCA PFAS 一次性报告申报期最早 2027-01-31 开始 [SRC-US-GOV-FR-2026-07062] [R:US-L5-TSCA-002]；加州 VOC 限值 [R:US-L5-CARB-003]；烟花须 CPSC 合规与 DOT EX 编号 [R:US-L5-FHSA-004] [R:US-L5-PHMSA-003]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【强制合规】家用危险化学品须按 FHSA 加注警示标签 [SRC-US-GOV-ECFR-16CFR1500] [SRC-US-GOV-ECFR-16CFR1500_121] | — | 危害分类评估（毒性、可燃性、刺激性等） | FHSA 警示标签；必备语句：家用危险化学品包装须含 FHSA 警示（信号词 + 危害说明 + Keep out of reach of children + 急救说明） | CPSC | [R:US-L5-FHSA-001] |
| 【强制合规】蜡烛金属芯烛芯铅含量 ≤0.06% 并在外箱标注 [SRC-US-GOV-ECFR-16CFR1500_17] | 烛芯金属芯铅含量检测 | — | 外箱标注 Conforms to 16 CFR 1500.17(a)(13) | CPSC | [R:US-L5-FHSA-002] |
| 【强制合规】消费级烟花须符合 16 CFR 1500.17 / 1507 并标注警示 [SRC-US-GOV-ECFR-16CFR1507] [SRC-US-GOV-ECFR-16CFR1500_17] | 16 CFR 1507 / APA 87-1 检测；GCC | — | FHSA 警示标签 | CPSC | [R:US-L5-FHSA-004] |
| 【强制合规】特定家用物质须使用儿童防护包装（PPPA，16 CFR 1700.14） [SRC-US-GOV-ECFR-16CFR1700] | 儿童防护包装测试（16 CFR 1700.20）；GCC 列明 PPPA | — | — | CPSC | [R:US-L5-PPPA-001] |
| 【提示】TSCA PFAS 一次性报告：进口过含 PFAS 物品的企业须报告（申报期最早 2027-01-31 开始） [SRC-US-GOV-ECFR-40CFR705] [SRC-US-GOV-FR-2026-07062] [SRC-US-GOV-FR-2025-19882] | — | 梳理 2011–2022 年进口物品是否含 PFAS（防水防油整理、不粘涂层、含氟聚合物）；通过 EPA CDX 提交 PFAS 报告（如仍适用） | — | EPA | [R:US-L5-TSCA-002] |
| 【禁售】含二氯甲烷、三氯乙烯（TCE）的消费级化学品禁止销售；四氯乙烯（PCE）零售分销 2027-03-08 起禁止；禁止事项：不得销售含二氯甲烷、TCE 的消费级产品（脱漆剂、除胶剂、去污剂、刹车清洁剂、脱脂剂等） [SRC-US-GOV-ECFR-40CFR751_105] [SRC-US-GOV-ECFR-40CFR751_107] [SRC-US-GOV-ECFR-40CFR751_305] | — | SDS/配方核查 PCE（2027-03-08 起零售分销禁止） | — | EPA | [R:US-L5-TSCA-004] |
| 【强制合规】含高 GWP 氢氟碳化物的产品限制：2025 起禁止制造/进口，2028 起禁止销售 [SRC-US-GOV-ECFR-40CFR84_54] [SRC-US-GOV-ECFR-40CFR84_58] | — | 确认制冷剂/推进剂种类与 GWP（如 R-290、R-600a、HFC-152a 合规；HFC-134a、R-410A 受限） | 制冷空调产品永久标签（84.58） | EPA | [R:US-L5-HFC-001] |
| 【强制合规】制冷剂（含 HFC 替代品）原则上只能卖给持证技师；汽车空调小罐有例外；禁止事项：不得向未认证个人销售大罐 R-22、R-410A、R-32 等制冷剂 [SRC-US-GOV-ECFR-40CFR82_154] | — | 销售前核验买方 608/609 技师证书（例外情形除外） | — | EPA | [R:US-L5-HFC-002] |
| 【需政府许可】烟花须取得 DOT 爆炸品分类批准（EX 编号）方可运输 [SRC-US-GOV-ECFR-49CFR173_56] | — | PHMSA EX 分类批准 | — | DOT PHMSA | [R:US-L5-PHMSA-003] |
| 【强制合规】加州：气雾剂、清洁剂、发胶等消费品须满足 CARB VOC 限值并有生产日期码（官方页面仅见摘要，待核） [SRC-US-GOV-CARB-CONSUMER-PRODUCTS] | VOC 含量计算/检测 | — | 生产日期/日期码 | 加州 CARB | [R:US-L5-CARB-003] |

#### E.15 刀具武器
- 弹簧刀（按钮自动开刃）和重力刀禁止州际运输销售；助力开刀（有闭合偏置）不在联邦禁令内 [SRC-US-GOV-USC-15USC1242] [SRC-US-GOV-USC-15USC1244] [R:US-L5-KNIFE-001]；进口时蝴蝶刀也按弹簧刀处理 [SRC-US-GOV-ECFR-19CFR12_95] [R:US-L6-KNIFE-001]。
- 80% 机匣/零件套件属于枪支；auto sear、Glock switch、消音器零件属 NFA 管制物品，均不得作为普通商品销售 [SRC-US-GOV-ECFR-27CFR478_12] [SRC-US-GOV-ECFR-27CFR478_11] [R:US-L5-ATF-001] [R:US-L5-ATF-002]。
- 州/市限制（防弹衣、辣椒喷雾、指虎、大容量弹匣、电击器等）差异大，须按州设置配送限制 [R:US-L5-STATE-005]；仿真枪橙色标记见 E.6 [R:US-L5-TOY-007]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【禁售】枪支机匣/枪架（含 80% 半成品、武器零件套件）属于枪支，不得在平台以普通商品销售；禁止事项：不得销售机匣/枪架（含 80% lower、jig 套件组合）和可轻易组装成枪的零件套件 [SRC-US-GOV-ECFR-27CFR478_12] [SRC-US-GOV-ECFR-27CFR478_11] [SRC-US-GOV-SCOTUS-23-852] | — | — | — | ATF | [R:US-L5-ATF-001] |
| 【禁售】机枪改装件（auto sear、Glock switch）与消音器零件禁售；禁止事项：不得销售 auto sear、Glock switch、drop-in auto sear、消音器管体/挡片、可改装为消音器的 solvent trap 套件 [SRC-US-GOV-ECFR-27CFR478_11] | — | — | — | ATF | [R:US-L5-ATF-002] |
| 【禁售】弹簧刀（按钮自动弹出）与重力/惯性开刃刀禁止州际运输和销售；禁止事项：不得销售自动弹簧刀（OTF/侧弹）与重力刀 [SRC-US-GOV-USC-15USC1242] [SRC-US-GOV-USC-15USC1244] | — | — | — | DOJ / CBP | [R:US-L5-KNIFE-001] |
| 【强制合规】武器与防身用品的州/市限制：纽约禁止向平民销售防弹衣、限制辣椒喷雾销售渠道；多州禁大容量弹匣、指虎等（官方页面仅见摘要，待核）；禁止事项：按州设置配送限制：防弹衣（纽约）、辣椒喷雾（纽约等）、大容量弹匣、指虎、电击器、特定刀具 [SRC-US-GOV-NYDOS-BODY-ARMOR] | — | 维护州/市限售清单并定期更新 | — | 州/市政府 | [R:US-L5-STATE-005] |
| 【禁售】弹簧刀、蝴蝶刀（balisong）、重力刀、弹射刀及其零件禁止进口；禁止事项：不得进口弹簧刀、蝴蝶刀（含练习用开刃款，待核）、重力刀、弹射刀及零件 [SRC-US-GOV-ECFR-19CFR12_95] [SRC-US-GOV-ECFR-19CFR12_97] | — | — | — | DOJ / CBP | [R:US-L6-KNIFE-001] |

#### E.16 激光
- 受辐射性能标准约束的电子产品（激光、微波炉、晒黑灯）上市前须向 FDA CDRH 提交产品报告，加认证和识别标签，外国制造商须指定美国代理人 [SRC-US-GOV-ECFR-21CFR1002] [SRC-US-GOV-ECFR-21CFR1005_25] [R:US-L5-RAD-001]。
- 激光笔/演示类激光不得超过 IIIa 级（可见光 5 mW）；IIIb/IV 级灯光秀投影仪须 FDA variance；玩具激光应控制在 Class 1 [SRC-US-GOV-ECFR-21CFR1040_11] [SRC-US-GOV-FDA-LASER-INTERNET-ALERT] [R:US-L5-LASER-002] [R:US-L5-LASER-003] [R:US-L5-LASER-001]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【强制合规】受 FDA 辐射性能标准约束的电子产品须提交产品报告、加贴认证与识别标签、指定美国代理人 [SRC-US-GOV-ECFR-21CFR1002] [SRC-US-GOV-ECFR-21CFR1010] [SRC-US-GOV-ECFR-21CFR1005_25] | — | FDA CDRH 产品报告（Product Report）；美国代理人（agent for service of process） | 认证标签 + 识别标签 | FDA CDRH | [R:US-L5-RAD-001] |
| 【强制合规】激光产品须符合 21 CFR 1040.10 分级、安全功能与标签要求 [SRC-US-GOV-ECFR-21CFR1040_10] [SRC-US-GOV-FDA-LASER-INTERNET-ALERT] [SRC-US-GOV-FR-2014-29725] | 激光等级与输出功率测试（21 CFR 1040.10 / IEC 60825-1）；儿童玩具中的激光应控制在 FDA Class I / IEC Class 1 以内 | CDRH 产品报告（见 US-L5-RAD-001） | 激光警示标签与孔径标签 | FDA CDRH | [R:US-L5-LASER-001] |
| 【禁售】激光笔/演示用激光、测量水平激光超过 IIIa 级（5 mW 可见光）禁止销售；禁止事项：超 IIIa（>5 mW）的激光笔、演示/指示用激光禁售 [SRC-US-GOV-ECFR-21CFR1040_11] [SRC-US-GOV-FDA-LASER-INTERNET-ALERT] | — | — | — | FDA CDRH | [R:US-L5-LASER-002] |
| 【需政府许可】IIIb/IV 级激光灯光秀投影仪须取得 FDA variance [SRC-US-GOV-ECFR-21CFR1040_11] [SRC-US-GOV-FDA-LASER-INTERNET-ALERT] | — | FDA CDRH variance（激光灯光秀） | — | FDA CDRH | [R:US-L5-LASER-003] |

#### E.17 无人机
- 2025-12-22 FCC 把所有外国生产的无人机及关键部件列入 Covered List：外国生产的新型号无法取得 FCC 授权；已授权老型号目前仍可销售，但 FCC 已就禁止部分企业已授权产品的进口与营销征求意见 [SRC-US-GOV-FR-2026-15418] [SRC-US-GOV-FR-2026-17193] [R:US-L5-FCC-006]。
- 250 g 以上无人机须为标准远程识别机型并有 FAA 接受的 DOC [SRC-US-GOV-ECFR-14CFR89] [R:US-L5-FAA-001]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【需政府许可】外国生产的无人机及关键部件已列入 Covered List（2025-12-22）：新型号无法取得 FCC 授权 [SRC-US-GOV-ECFR-47CFR2_903] [SRC-US-GOV-FR-2026-15418] [SRC-US-GOV-FR-2026-17193] | 核实 FCC ID 的授权日期早于 2025-12-22 且未被限制 | 确认产品是否「外国生产」（含飞控、通信模块、摄像头、电池等关键部件） | — | FCC | [R:US-L5-FCC-006] |
| 【强制合规】无人机须具备远程识别（Remote ID）并有 FAA 接受的符合性声明 [SRC-US-GOV-ECFR-14CFR89] [SRC-US-GOV-ECFR-14CFR48] | — | FAA 接受的 Remote ID 符合性声明（Declaration of Compliance） | 说明书告知 Remote ID 与 FAA 注册义务 | FAA | [R:US-L5-FAA-001] |

#### E.18 汽配
- 排放篡改件（DPF/EGR 删除、调校器、O2 欺骗器）禁售；在加州销售影响排放的改装件须有 CARB EO [SRC-US-GOV-USC-42USC7522] [R:US-L5-CAA-001] [R:US-L5-CARB-002]。
- 轮胎、车灯、刹车软管/液、安全带、警示三角等须 FMVSS 自我认证并标 DOT；外国制造商须指定美国代理人；进口时须 HS-7 申报 [SRC-US-GOV-ECFR-49CFR571] [SRC-US-GOV-ECFR-49CFR551] [R:US-L5-NHTSA-001] [R:US-L6-IMPORT-003]。LED 替换大灯灯泡多不合规 [R:US-L5-NHTSA-002]；摩托车头盔须 DOT 认证标签 [R:US-L5-NHTSA-003]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【禁售】汽车排放篡改件（defeat device）禁止销售；禁止事项：不得销售 delete kit、tuner、O2 sensor spacer/simulator 等排放篡改件 [SRC-US-GOV-USC-42USC7522] [SRC-US-GOV-EPA-DEFEAT-DEVICE-FACTSHEET] | — | — | — | EPA | [R:US-L5-CAA-001] |
| 【强制合规】受 FMVSS 约束的汽车设备（轮胎、车灯、刹车软管/液、安全带、警示三角、玻璃）须自我认证合规并标 DOT [SRC-US-GOV-ECFR-49CFR571] [SRC-US-GOV-ECFR-49CFR574] [SRC-US-GOV-ECFR-49CFR551] | FMVSS 自我认证（DOT 标记） | NHTSA 制造商识别（566）与轮胎工厂代码（574）；美国送达代理人（49 CFR 551.45） | — | NHTSA | [R:US-L5-NHTSA-001] |
| 【强制合规】汽车大灯、尾灯等照明须符合 FMVSS 108；改装 LED 大灯灯泡多不合规 [SRC-US-GOV-ECFR-49CFR571_108] [SRC-US-GOV-NHTSA-RCL-21E006] | FMVSS 108 配光与尺寸测试 | — | DOT 标记（合规时） | NHTSA | [R:US-L5-NHTSA-002] |
| 【强制合规】摩托车头盔须符合 FMVSS 218 并有 DOT 认证标签；不得出售带假 DOT 贴纸的「装饰头盔」 [SRC-US-GOV-ECFR-49CFR571_218] | FMVSS 218 测试 | — | DOT FMVSS No. 218 CERTIFIED 认证标签及内部信息标签 | NHTSA | [R:US-L5-NHTSA-003] |
| 【需政府许可】加州：影响排放的汽车改装件须有 CARB 豁免令（EO）才能广告和销售（官方页面仅见摘要，待核）；禁止事项：无 EO 的排放相关改装件不得向加州销售 [SRC-US-GOV-CARB-AFTERMARKET] | — | CARB Executive Order（EO 号），标注于产品与 listing | — | 加州 CARB | [R:US-L5-CARB-002] |

#### E.19 自行车与个人出行
- 自行车与低速电助力自行车（<750 W、<20 mph、有脚踏）适用 16 CFR 1512；自行车头盔适用 16 CFR 1203（认证标签即证书）[SRC-US-GOV-ECFR-16CFR1512] [SRC-US-GOV-ECFR-16CFR1203] [R:US-L5-BIKE-001] [R:US-L5-BIKE-002]。
- 微出行锂电池：CPSC 2026-06-24 发布拟议规则（拟设 16 CFR 1265），尚无联邦强制标准 [SRC-US-GOV-FR-2026-12749] [R:US-L5-MICRO-001]；纽约市已强制 UL 2849/2272/2271，加州 2026-01-01 起要求电动自行车电池认证 [SRC-US-GOV-NYC-DCWP-LL39] [R:US-L5-STATE-001]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【强制合规】自行车（含低速电助力自行车）须符合 16 CFR 1512 [SRC-US-GOV-ECFR-16CFR1512] | 16 CFR 1512 检测；GCC（儿童自行车为 CPC） | — | 反光器与说明书等 | CPSC | [R:US-L5-BIKE-001] |
| 【强制合规】自行车头盔须符合 16 CFR 1203 [SRC-US-GOV-ECFR-16CFR1203] | 16 CFR 1203 头盔测试；儿童头盔另须 CPC（第三方检测） | — | 1203.34 永久认证标签（即该头盔的合规证书）；必备语句：头盔认证标签须写：Complies with U.S. CPSC Safety Standard for Bicycle Helmets for Persons Age 5 and Older（或 Age 1 and Older (Extended Head Coverage)） | CPSC | [R:US-L5-BIKE-002] |
| 【提示】电动滑板车/平衡车/电动自行车锂电池：CPSC 强制标准仍在拟议阶段，现以 UL 2272/2849/2271 为事实要求 [SRC-US-GOV-FR-2026-12749] [SRC-US-GOV-FR-2026-20296] [SRC-US-GOV-ECFR-16CFR1512] | UL 2272 / UL 2849 / UL 2271 认证（NRTL 出具） | 跟踪 CPSC 16 CFR 1265 最终规则 | — | CPSC（拟议） | [R:US-L5-MICRO-001] |
| 【强制合规】电动自行车/滑板车/平衡车：纽约市要求 UL 2849/2272/2271 认证，加州 2026 年起要求电动自行车电池认证；禁止事项：未认证产品不得向纽约市、加州（电动自行车）销售 [SRC-US-GOV-NYC-DCWP-LL39] [SRC-US-GOV-CA-ASM-SB1271-ANALYSIS] [SRC-US-S3-SGS-CA-SB1271] | UL 2849（电动自行车）/ UL 2272（滑板车、平衡车等）/ UL 2271（电池）认证 | — | 展示认证标志或实验室名称 | 州/市政府 | [R:US-L5-STATE-001] |

#### E.20 户外动力与燃料
- 便携燃料桶须儿童防护盖和火焰抑制装置 [SRC-US-GOV-ECFR-16CFR1460] [SRC-US-GOV-ECFR-16CFR1461] [R:US-L5-FUEL-001]；发电机须 CO 警示标签 [R:US-L5-HOME-001]；手推割草机须符合 16 CFR 1205 [R:US-L5-HOME-003]。
- 小型汽油机设备须 EPA 排放认证；加州 2024 年型起多数新小型汽油机须零排放 [SRC-US-GOV-ECFR-40CFR1054] [R:US-L5-CAA-002] [R:US-L5-CARB-004]。
- 打火机须儿童防护（CPSC）并经 PHMSA 批准方可运输 [SRC-US-GOV-ECFR-16CFR1210] [SRC-US-GOV-ECFR-49CFR173_308] [R:US-L5-LIGHTER-001] [R:US-L5-LIGHTER-002] [R:US-L5-PHMSA-002]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【强制合规】便携燃料桶须有儿童防护盖（16 CFR 1460）和火焰抑制装置（16 CFR 1461） [SRC-US-GOV-ECFR-16CFR1460] [SRC-US-GOV-ECFR-16CFR1461] | ASTM F2517-22e1 与 ASTM F3326-21/F3429 检测；GCC | — | — | CPSC | [R:US-L5-FUEL-001] |
| 【强制合规】一次性/新奇打火机须具儿童防护功能（16 CFR 1210）；纸板火柴须符合 16 CFR 1202 [SRC-US-GOV-ECFR-16CFR1210] [SRC-US-GOV-ECFR-16CFR1202] | 儿童防护性能测试（16 CFR 1210 subpart B）；GCC；纸板火柴（matchbooks）16 CFR 1202 结构与标签检测（如销售火柴） | — | — | CPSC | [R:US-L5-LIGHTER-001] |
| 【强制合规】多用途打火机（点火枪）须具儿童防护功能（16 CFR 1212） [SRC-US-GOV-ECFR-16CFR1212] | 16 CFR 1212 儿童防护测试并报告 CPSC；GCC | — | — | CPSC | [R:US-L5-LIGHTER-002] |
| 【强制合规】便携式发电机须加贴一氧化碳中毒危险标签（16 CFR 1407） [SRC-US-GOV-ECFR-16CFR1407] | GCC | — | 16 CFR 1407 CO 危险标签（产品 + 包装）；必备语句：发电机及包装须有 CO 危险标签：Using a generator indoors CAN KILL YOU IN MINUTES. Generator exhaust contains carbon monoxide... | CPSC | [R:US-L5-HOME-001] |
| 【强制合规】手推式动力割草机须符合 16 CFR 1205 [SRC-US-GOV-ECFR-16CFR1205] | 16 CFR 1205 检测；GCC | — | — | CPSC | [R:US-L5-HOME-003] |
| 【强制合规】小型非道路汽油机设备（发电机、割草机、链锯等）与便携油桶须有 EPA 排放认证与标签 [SRC-US-GOV-ECFR-40CFR1054] [SRC-US-GOV-ECFR-40CFR59] | EPA 符合性证书（Certificate of Conformity） | — | 排放控制信息标签（ECI label） | EPA | [R:US-L5-CAA-002] |
| 【需政府许可】打火机运输须经 PHMSA 批准（新设计须认可实验室测试） [SRC-US-GOV-ECFR-49CFR173_308] | — | PHMSA 打火机设计批准（approval number） | — | DOT PHMSA | [R:US-L5-PHMSA-002] |
| 【强制合规】加州：新的小型汽油发动机设备（割草机、吹叶机等）自 2024 年型起须零排放（官方页面仅见摘要，待核）；禁止事项：不得向加州销售不符合 SORE 规则的新汽油小型发动机设备（发电机 2028 年型前按过渡标准） [SRC-US-GOV-CARB-AB1346] | CARB 认证（EO） | — | — | 加州 CARB | [R:US-L5-CARB-004] |

#### E.21 家具木制品
- 衣柜、抽屉柜等储物家具须符合 STURDY 防倾倒标准 ASTM F2057-23（2023-09-01 起生产）[SRC-US-GOV-ECFR-16CFR1261] [R:US-L5-STURDY-001]；涂层铅 ≤90 ppm [R:US-L5-CPSIA-003]。
- 床垫须 1632/1633 阻燃并有法定标签；软包家具须 TB 117-2013 并加永久合规标签 [SRC-US-GOV-ECFR-16CFR1633] [SRC-US-GOV-ECFR-16CFR1640] [R:US-L5-FLAM-001] [R:US-L5-FLAM-002]；加州另有阻燃剂声明标签 [R:US-L5-STATE-007]。
- 人造板及其成品须 TSCA Title VI 认证并标注 [SRC-US-GOV-ECFR-40CFR770] [R:US-L5-TSCA-001]；含木材/竹材的家具进口须 Lacey 申报 [SRC-US-GOV-APHIS-LACEY] [R:US-L6-LACEY-001]。窗帘拉绳适用 SPH 清单（16 CFR 1260 已被法院撤销）[R:US-L5-WINDOW-001]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【强制合规】衣柜/抽屉柜等储物家具须符合防倾倒标准 16 CFR 1261（ASTM F2057-23） [SRC-US-GOV-ECFR-16CFR1261] | ASTM F2057-23 稳定性测试；GCC 列明 16 CFR 1261 | — | 防倾倒警示标签与吊牌（hang tag） | CPSC | [R:US-L5-STURDY-001] |
| 【强制合规】窗帘/百叶窗拉绳须符合 ANSI/WCMA A100.1-2018（实质性产品危害清单） [SRC-US-GOV-ECFR-16CFR1120] [SRC-US-GOV-FR-2026-19579] [SRC-US-S3-WCMA-V-CPSC-2023] | ANSI/WCMA A100.1-2018 相关条款检测 | — | 产品上制造商标签（ANSI/WCMA 5.3） | CPSC | [R:US-L5-WINDOW-001] |
| 【强制合规】床垫与床垫垫须符合 16 CFR 1632（香烟点燃）和 1633（明火） [SRC-US-GOV-ECFR-16CFR1632] [SRC-US-GOV-ECFR-16CFR1633] | 16 CFR 1632 与 1633 原型测试；GCC | 原型与生产质量控制记录 | 1633 永久标签；必备语句：床垫标签须含 1633 合规声明：This mattress meets the requirements of 16 CFR part 1633 (federal flammability (open flame) standard for mattresses) ... | CPSC | [R:US-L5-FLAM-001] |
| 【强制合规】软包家具须符合 16 CFR 1640（采纳加州 TB 117-2013）并加永久标签 [SRC-US-GOV-ECFR-16CFR1640] | TB 117-2013 阴燃测试 | — | 永久合规标签；必备语句：软包家具须有永久标签：Complies with U.S. CPSC requirements for upholstered furniture flammability | CPSC | [R:US-L5-FLAM-002] |
| 【强制合规】含人造板（刨花板、中纤板、胶合板）的木制品须符合 TSCA Title VI 甲醛排放标准并标注 [SRC-US-GOV-ECFR-40CFR770] | TSCA Title VI 第三方认证（TPC）的板材 | 进口商记录保存 3 年（供应商书面合规声明、提单、发票） | 成品或包装标签：TSCA Title VI compliant + 加工商名称 + 生产日期；必备语句：含人造板的成品或包装须标注：TSCA Title VI compliant | EPA | [R:US-L5-TSCA-001] |
| 【强制合规】加州：软包家具须加阻燃剂声明标签（SB 1019），软包家具、婴童用品、床垫限制阻燃剂（AB 2998）（官方页面仅见摘要，待核） [SRC-US-GOV-CA-SB1019-2014] | 阻燃剂含量检测（如声明不含） | — | 加州阻燃剂声明标签（勾选式） | 州/市政府 | [R:US-L5-STATE-007] |
| 【强制合规】含植物材料（木、竹、纸、植物精油等）的商品进口须按 Lacey 法提交植物申报 [SRC-US-GOV-APHIS-LACEY] | — | Lacey 植物申报（属/种学名、采伐国、价值、数量、回收材料比例）；向供应商收集木材/竹材种名与产地证明 | — | USDA APHIS / CBP | [R:US-L6-LACEY-001] |

#### E.22 纺织服装
- 标签：纤维成分、原产国、厂商名称或 RN 号、洗涤保养说明；网页须写明 Imported [SRC-US-GOV-ECFR-16CFR303] [SRC-US-GOV-ECFR-16CFR303_34] [SRC-US-GOV-ECFR-16CFR423] [R:US-L5-FTC-001]；毛皮制品须标动物名称与原产国 [R:US-L5-FTC-003]。
- 服装须达到 16 CFR 1610 可燃性 1/2 级；地毯须 1630/1631 [SRC-US-GOV-ECFR-16CFR1610] [R:US-L5-FLAM-003] [R:US-L5-FLAM-004]。
- 含有意添加 PFAS 的纺织品/服装在明尼苏达、缅因、加州、纽约等受限；加州禁售新毛皮制品（二手来源）[R:US-L5-PFAS-001] [R:US-L5-STATE-002]；涉疆棉为进口高风险 [R:US-L6-UFLPA-001]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【强制合规】服装纺织品须符合可燃性标准 16 CFR 1610（塑料薄膜服装 1611） [SRC-US-GOV-ECFR-16CFR1610] [SRC-US-GOV-ECFR-16CFR1611] | 16 CFR 1610 可燃性测试（或适用豁免说明）；GCC（儿童服装为 CPC） | — | — | CPSC | [R:US-L5-FLAM-003] |
| 【强制合规】地毯和小地毯须符合 16 CFR 1630/1631 表面可燃性 [SRC-US-GOV-ECFR-16CFR1630] [SRC-US-GOV-ECFR-16CFR1631] | 16 CFR 1630/1631 药丸测试；GCC | — | — | CPSC | [R:US-L5-FLAM-004] |
| 【强制合规】纺织品须标注纤维成分、原产国、厂商标识（RN 号）和洗涤保养说明，网页须披露进口/美国制造 [SRC-US-GOV-ECFR-16CFR303] [SRC-US-GOV-ECFR-16CFR303_34] [SRC-US-GOV-ECFR-16CFR300] | — | FTC RN 号（可选，用于替代厂商名称） | 纤维成分 + 原产国 + 厂商名称或 RN 号（英文，永久）；Listing 中注明 Imported；永久洗涤保养标签（服装，16 CFR 423）；必备语句：纺织品详情页须写明原产地（如 Imported） / 标签须写纤维成分百分比、原产国、厂商名称或 RN 号 | FTC | [R:US-L5-FTC-001] |
| 【强制合规】毛皮制品须按毛皮标签法标注动物名称、原产国，不得以假乱真 [SRC-US-GOV-ECFR-16CFR301] | — | — | 毛皮标签（动物名称、原产国、加工方式） | FTC | [R:US-L5-FTC-003] |
| 【强制合规】有意添加 PFAS 的纺织品、服装与家纺：多州禁售（加州、纽约 2025 起，明尼苏达 2025、缅因 2026 起）；禁止事项：不得向明尼苏达（2025 起）、缅因（2026 起）、加州/纽约（2025/2024 起）销售含有意添加 PFAS 的纺织/服装产品 [SRC-US-GOV-MN-STAT-116-943] [SRC-US-GOV-ME-DEP-PFAS-PRODUCTS] [SRC-US-S3-MORGANLEWIS-PFAS-TEXTILES-2025] | 总有机氟（TOF）或 PFAS 靶向检测；供应商无 PFAS 声明（防水防油整理是主要来源） | 加州：向销售方提供合规证书（AB 1817 要求） | — | 各州环保部门（MN PCA、ME DEP 等） | [R:US-L5-PFAS-001] |
| 【强制合规】加州禁售新的毛皮制品（AB 44，2023-01-01 起）（二手来源，待核）；禁止事项：不得向加州销售新的真皮草制品（人造毛不受影响，但须如实标注） [SRC-US-S3-LEGISCAN-CA-AB44] | — | — | — | 州/市政府 | [R:US-L5-STATE-002] |

#### E.23 珠宝
- 成色标记（14K、925 等）须真实并配责任方商标 [SRC-US-GOV-ECFR-16CFR23] [R:US-L5-FTC-006]；儿童首饰适用 CPC、铅 100 ppm [R:US-L5-CPSIA-002]；磁性首饰适用 16 CFR 1262 [R:US-L5-MAG-001]；象牙等受保护动物制品禁售 [R:US-L6-FWS-002]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【强制合规】贵金属首饰的成色标记须真实并带责任方商标（国家金银标记法、FTC 珠宝指南） [SRC-US-GOV-ECFR-16CFR23] | 成色检测（金、银含量） | — | 成色标记 + 责任方商标 | FTC | [R:US-L5-FTC-006] |

#### E.24 宠物
- 宠物食品须按 21 CFR 501 标签，设施须 FDA 注册（2026 续期），多数州另有登记 [SRC-US-GOV-ECFR-21CFR501] [R:US-L5-PETFDA-001]；动物药须 FDA 批准，外用驱虫滴剂/项圈多属 EPA 农药 [SRC-US-GOV-USC-21USC360B] [R:US-L5-PETFDA-002] [R:US-L5-FIFRA-001]。
- 含动物源成分的咀嚼物/零食进口须符合 APHIS 要求 [R:US-L6-APHIS-003]；含 CBD 的宠物食品禁售 [R:US-L5-HEMP-001]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【强制合规】宠物食品须符合 FDA 动物食品标签与设施注册要求（各州另按 AAFCO 模式法规管理） [SRC-US-GOV-ECFR-21CFR501] [SRC-US-GOV-ECFR-21CFR1_230] | — | FDA 食品设施注册（含 2026 续期）；各州宠物食品产品注册（如适用） | 21 CFR 501 标签 | FDA CVM | [R:US-L5-PETFDA-001] |
| 【需政府许可】兽药须经 FDA 批准、有条件批准或列入索引，未批准动物药不得销售；禁止事项：不得销售未经批准的动物药（含进口兽用抗生素、鱼药） [SRC-US-GOV-USC-21USC360B] | — | FDA 动物药批准（NADA/ANADA）或索引 | — | FDA CVM | [R:US-L5-PETFDA-002] |
| 【强制合规】动物源产品（羽毛、皮张、骨角、宠物咀嚼物等）进口须符合 APHIS 卫生要求或许可 [SRC-US-GOV-ECFR-9CFR95] | — | APHIS VS 进口许可（如需要）；出口国官方卫生证书或处理证明 | — | USDA APHIS | [R:US-L6-APHIS-003] |

#### E.25 植物种子
- 种植用植物和种子进口须 APHIS 许可（另有规定除外）和植物检疫证书，不得带土；州际销售种子须符合联邦种子法标签 [SRC-US-GOV-ECFR-7CFR319] [R:US-L6-APHIS-002]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【需政府许可】进口植物、种子（种植用）须有植物检疫证书并按需取得 APHIS 许可，禁止带土 [SRC-US-GOV-ECFR-7CFR319] | — | APHIS PPQ 进口许可（如 PPQ 587，或小批量种子许可）；出口国官方植物检疫证书 | 种子标签：品种、批号、发芽率、杂质/杂草种子含量等（联邦种子法/州法） | USDA APHIS | [R:US-L6-APHIS-002] |

#### E.26 动物制品
- 野生动物制品进口须 FWS 申报（3-177），商业进口须许可；象牙、海洋哺乳动物制品禁售；狗猫毛皮禁售 [SRC-US-GOV-ECFR-50CFR14] [SRC-US-GOV-ECFR-50CFR17_40] [SRC-US-GOV-USC-19USC1308] [R:US-L6-FWS-001] [R:US-L6-FWS-002] [R:US-L6-IMPORT-004]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【强制合规】野生动物及其制品进口须向 FWS 申报（3-177 表），商业进口须持 FWS 许可证，CITES 物种须许可 [SRC-US-GOV-ECFR-50CFR14] | — | FWS 3-177 申报（eDecs）；FWS 进出口许可证（商业进口）及 CITES 许可（如适用） | — | FWS | [R:US-L6-FWS-001] |
| 【禁售】象牙、海洋哺乳动物制品等受保护野生动物制品禁止进口和销售；禁止事项：不得进口或销售象牙制品、海洋哺乳动物制品（海豹皮、鲸骨、海象牙等）及鲨鱼鳍产品 [SRC-US-GOV-ECFR-50CFR17_40] [SRC-US-GOV-USC-16USC1372] | — | — | — | FWS | [R:US-L6-FWS-002] |
| 【强制合规】动物源产品（羽毛、皮张、骨角、宠物咀嚼物等）进口须符合 APHIS 卫生要求或许可 [SRC-US-GOV-ECFR-9CFR95] | — | APHIS VS 进口许可（如需要）；出口国官方卫生证书或处理证明 | — | USDA APHIS | [R:US-L6-APHIS-003] |
| 【禁售】狗毛、猫毛制品禁止进口、销售；禁止事项：不得进口或销售含狗毛、猫毛的制品 [SRC-US-GOV-USC-19USC1308] | 毛皮物种鉴定（必要时） | — | — | CBP 及相关 PGA | [R:US-L6-IMPORT-004] |

#### E.27 食品保健品
- 食品设施（含中国工厂）须 FDA 注册，**2026-10-01 至 12-31 是两年一次的续期窗口**，未续期注册失效 [SRC-US-GOV-ECFR-21CFR1_230] [R:US-L5-FOOD-001]；食品标签须英文、营养成分表、9 大过敏原 [R:US-L5-FOOD-002]。
- 补充剂：Supplement Facts、结构/功能宣称 30 天内通知 FDA 并加免责声明、cGMP；不得作疾病宣称 [SRC-US-GOV-ECFR-21CFR101_93] [R:US-L5-SUPP-001] [R:US-L5-SUPP-002] [R:US-L5-SUPP-003]。
- 红色 3 号色素 2027-01-15 起禁用于食品与补充剂 [SRC-US-GOV-FR-2025-00830] [R:US-L5-FOOD-003]；内嵌玩具的糖果禁售 [R:US-L5-FOOD-004]；CBD/THC 食品与补充剂禁售 [SRC-US-GOV-FDA-CBD] [R:US-L5-HEMP-001]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【强制合规】食品（含膳食补充剂）生产/加工/包装/储存设施须在 FDA 注册；2026-10-01 至 12-31 为两年一次续期窗口 [SRC-US-GOV-ECFR-21CFR1_230] | — | FDA 食品设施注册与 2026 年续期；美国代理人（外国设施） | — | FDA | [R:US-L5-FOOD-001] |
| 【强制合规】预包装食品须有英文标签、营养成分表和主要过敏原声明（含芝麻） [SRC-US-GOV-ECFR-21CFR101] | — | — | 21 CFR 101 全部必需标签要素（英文）；必备语句：食品标签须英文，含 Nutrition Facts 与主要过敏原声明（Contains: ...） | FDA | [R:US-L5-FOOD-002] |
| 【强制合规】FD&C Red No. 3（赤藓红）将于 2027-01-15 起禁用于食品和膳食补充剂；禁止事项：2027-01-15 起食品与补充剂不得含 FD&C Red No. 3（erythrosine） [SRC-US-GOV-FR-2025-00830] | — | 配方色素/添加剂合规核查 | — | FDA | [R:US-L5-FOOD-003] |
| 【禁售】嵌有非营养物品（玩具等）的糖果禁止销售；禁止事项：糖果中不得嵌入玩具等非营养物品 [SRC-US-GOV-USC-21USC342] | — | — | — | FDA | [R:US-L5-FOOD-004] |
| 【强制合规】婴儿配方奶粉须符合 21 CFR 106/107 并在上市前向 FDA 通报 [SRC-US-GOV-ECFR-21CFR106] [SRC-US-GOV-ECFR-21CFR107] | — | 婴儿配方生产商登记与新配方 90 天前通报 | 21 CFR 107 标签与使用说明 | FDA | [R:US-L5-FOOD-005] |
| 【强制合规】膳食补充剂标签：Supplement Facts、「dietary supplement」字样与美国联系方式 [SRC-US-GOV-ECFR-21CFR101_36] | — | — | Supplement Facts 及必需标签要素；美国境内地址或电话（不良事件报告） | FDA | [R:US-L5-SUPP-001] |
| 【强制合规】补充剂只能作结构/功能宣称：须 30 天内通知 FDA 并加免责声明，不得作疾病宣称 [SRC-US-GOV-ECFR-21CFR101_93] | — | 结构/功能宣称 30 天内通知 FDA | 免责声明（带星号）；必备语句：结构/功能宣称须附：This statement has not been evaluated by the Food and Drug Administration. This product is not intended to diagnose, treat, cure, or prevent any disease. | FDA | [R:US-L5-SUPP-002] |
| 【强制合规】补充剂须按 21 CFR 111 cGMP 生产；新膳食成分须提前通报；禁用麻黄碱类等成分；禁止事项：不得含麻黄碱类生物碱、CBD/THC 等被排除或禁用成分 [SRC-US-GOV-ECFR-21CFR111] [SRC-US-GOV-ECFR-21CFR119_1] [SRC-US-GOV-FDA-CBD] | — | cGMP 合规（21 CFR 111）与成分规格/检验记录；NDI 通报（如适用） | — | FDA | [R:US-L5-SUPP-003] |
| 【禁售】添加 CBD/THC 的食品、膳食补充剂和动物食品不得在州际销售；禁止事项：CBD/THC 食品、饮料、软糖、补充剂、宠物零食及带疗效宣称的 CBD 产品禁售 [SRC-US-GOV-FDA-CBD] [SRC-US-GOV-USC-21USC331] | — | — | — | FDA / DEA | [R:US-L5-HEMP-001] |

#### E.28 烟草电子烟
- 未获 FDA 上市许可的电子烟、烟油、烟弹不得销售；电子烟（含无尼古丁款及零部件）不得经 USPS 寄递，配送销售须登记与年龄核验 [SRC-US-GOV-USC-21USC387J] [SRC-US-GOV-USC-15USC375] [SRC-US-GOV-USC-18USC1716E] [R:US-L5-VAPE-001] [R:US-L5-VAPE-002] [R:US-L5-VAPE-003]。
- 2026-11-12 起联邦 hemp 定义收窄：每容器总 THC >0.4 mg 或含合成大麻素的成品回归受管制物质（Delta-8 等）[SRC-US-GOV-PL-119-37] [R:US-L5-HEMP-002]；多州禁调味电子烟 [R:US-L5-STATE-003]；吸毒用具禁售 [R:US-L6-IMPORT-005]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【禁售】未获 FDA 上市许可的电子烟（ENDS）及烟油、烟弹禁止销售；禁止事项：无 FDA 营销许可的电子烟、烟油、烟弹、雾化器不得销售 [SRC-US-GOV-USC-21USC387J] [SRC-US-GOV-FDA-ENDS] | — | — | — | FDA CTP / ATF / USPS | [R:US-L5-VAPE-001] |
| 【禁售】PACT Act：电子烟（含无尼古丁及零部件）不得经美国邮政寄递，配送销售须登记与年龄核验；禁止事项：不得通过 USPS 寄递 ENDS 及其零部件 [SRC-US-GOV-USC-15USC375] [SRC-US-GOV-USC-15USC376A] [SRC-US-GOV-USC-18USC1716E] | — | 向 ATF 与各州烟草税务机关登记并按月申报；交付时成人签收与年龄核验 | — | FDA CTP / ATF / USPS | [R:US-L5-VAPE-002] |
| 【强制合规】含尼古丁产品须有法定尼古丁警示语；液体尼古丁须儿童防护包装 [SRC-US-GOV-ECFR-21CFR1143_3] [SRC-US-GOV-USC-15USC1472A] | 液体尼古丁容器儿童防护包装测试（16 CFR 1700.20） | — | 尼古丁警示语（包装两主展示面 30%、广告 20%）；必备语句：WARNING: This product contains nicotine. Nicotine is an addictive chemical. | FDA CTP / ATF / USPS | [R:US-L5-VAPE-003] |
| 【禁售】2026-11-12 起联邦「hemp」定义收窄：每容器总 THC >0.4 mg 或含合成大麻素的成品归为大麻（受管制物质）；禁止事项：2026-11-12 起不得销售每容器总 THC >0.4 mg 或含合成大麻素的 hemp 衍生成品 [SRC-US-GOV-PL-119-37] [SRC-US-S3-CRS-IF13136] | 按总 THC（含 THCA）出具的第三方 COA | — | — | FDA / DEA | [R:US-L5-HEMP-002] |
| 【强制合规】多州禁售带口味的电子烟/烟草产品（如加州 2022-12-21 起）（官方页面仅见摘要，待核）；禁止事项：不得向加州、马萨诸塞、新泽西、纽约、罗得岛等州销售调味电子烟 [SRC-US-GOV-CDPH-FLAVOR-LAW] | — | — | — | 州/市政府 | [R:US-L5-STATE-003] |
| 【禁售】毒品吸食用具（drug paraphernalia）禁止进口和销售；禁止事项：不得进口、销售吸毒用具（含以大麻、毒品为暗示营销的烟具） [SRC-US-GOV-USC-21USC863] | — | — | — | CBP 及相关 PGA | [R:US-L6-IMPORT-005] |

#### E.29 酒类
- 进口酒类须 TTB 进口商基本许可、COLA 标签批准、FDA 注册与预先通报；各州直邮限制严格 [SRC-US-GOV-ECFR-27CFR1] [SRC-US-GOV-ECFR-27CFR13] [R:US-L6-ALC-001]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【需政府许可】进口酒类须持 TTB 进口商基本许可、取得 COLA 标签批准，并完成 FDA 注册与预先通报 [SRC-US-GOV-ECFR-27CFR1] [SRC-US-GOV-ECFR-27CFR13] [SRC-US-GOV-ECFR-21CFR1_279] | — | TTB 进口商基本许可（Basic Permit）；COLA 标签批准（TTB Form 5100.31）；FDA 食品设施注册与预先通报 | — | TTB / FDA | [R:US-L6-ALC-001] |

#### E.30 成人
- 避孕套、个人润滑剂属 II 类医疗器械，须 510(k) [SRC-US-GOV-ECFR-21CFR884_5300] [R:US-L5-DEV-007]；普通情趣用品无医疗宣称时一般不按器械管理（州法限制见「待核实」）。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【需政府许可】避孕套与个人润滑剂属 II 类医疗器械，须 510(k) [SRC-US-GOV-ECFR-21CFR884_5300] [SRC-US-GOV-ECFR-21CFR807] | — | 510(k) 许可与注册列名 | 21 CFR 801 与特殊控制标签（如乳胶过敏警示、有效期） | FDA CDRH | [R:US-L5-DEV-007] |

#### E.31 二手
- 转售二手/翻新儿童用品同样适用 CPSC 要求，召回品和不合规旧婴儿床不得转售 [SRC-US-GOV-USC-15USC2068] [R:US-L5-CHILD-006]；明尼苏达 PFAS 法不适用二手产品转售 [SRC-US-GOV-MN-STAT-116-943]；FCC ID 展示新规不适用二手设备 listing [SRC-US-GOV-FR-2026-18535]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【强制合规】二手/翻新儿童用品转售同样须合规，召回品不得转售；禁止事项：不得转售召回品或不符合现行强制标准的二手婴儿床、睡眠产品等 [SRC-US-GOV-USC-15USC2068] [SRC-US-GOV-ECFR-16CFR1219] | — | 核查 CPSC 召回清单（cpsc.gov/Recalls、SaferProducts.gov） | — | CPSC | [R:US-L5-CHILD-006] |

#### E.32 包装与环保
- 环保宣称须有依据并加限定（FTC 绿色指南）[SRC-US-GOV-ECFR-16CFR260] [R:US-L5-FTC-005]；纽约、华盛顿等州禁用 EPS 填充颗粒与泡沫餐盒/保温箱，纽约 2026-01-01 起扩至泡沫保温箱 [SRC-US-GOV-NYDEC-FOAM-FREE] [R:US-L5-PKG-001]。
- 加州 SB 343「可回收」标识限制原定 2026-10-04 生效，但已于 2026-07-14 被联邦法院初步禁止执行；多州包装 EPR 推进中（二手来源，待核）[R:US-L5-PKG-002]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【强制合规】环保宣称（可降解、可回收、可堆肥、环保）须有依据并加限定（绿色指南） [SRC-US-GOV-ECFR-16CFR260] | — | 环保宣称的检测/认证依据（如 ASTM D6400 可堆肥认证） | — | FTC | [R:US-L5-FTC-005] |
| 【强制合规】发泡聚苯乙烯（EPS）包装：纽约、华盛顿等州禁售泡沫填充颗粒、泡沫餐盒/保温箱；禁止事项：发往纽约、华盛顿等州的包裹不得使用 EPS 填充颗粒；不得向这些州销售 EPS 泡沫保温箱/一次性泡沫餐盒 [SRC-US-GOV-NYDEC-FOAM-FREE] [SRC-US-GOV-WA-ECOLOGY-EPS] | — | 改用纸质/可堆肥填充或块状 EPS 缓冲（块状缓冲通常不在禁令内） | — | 各州（NY DEC、WA Ecology、CalRecycle 等） | [R:US-L5-PKG-001] |
| 【提示】包装与回收标识：加州 SB 343「可回收」标识限制（2026-07 已被法院禁止执行）及各州包装 EPR（二手来源，待核） [SRC-US-S3-MORGANLEWIS-SB343-2026] | — | 跟踪 SB 343 诉讼与各州包装 EPR 登记义务 | — | 各州（NY DEC、WA Ecology、CalRecycle 等） | [R:US-L5-PKG-002] |

#### E.33 进口与清关（L6）
- **小额免税已全面暂停**：对中国/香港 2025-05-02 起、所有国家 2025-08-29 起；CBP 2026-06-24 起无限期暂停（邮政 2026-07-24）；法定废止 2027-07-01 生效。所有货物都须报关缴税，海运须 ISF [SRC-US-GOV-FR-2025-14897] [SRC-US-GOV-FR-2026-12670] [SRC-US-GOV-PL-119-21] [R:US-L6-IMPORT-001]。
- **关税**：IEEPA 关税已于 2026-02 终止（法院命令退税进行中）；122 条款 10% 临时附加税为期 150 天；2026-07-24 起对华加征 12.5% 强迫劳动 301 关税；原 301 与 232 关税继续 [SRC-US-GOV-FR-2026-03832] [SRC-US-GOV-FR-2026-03824] [SRC-US-GOV-FR-2026-15181] [R:US-L6-TARIFF-001]。
- **UFLPA**：涉疆商品推定禁止入境 [SRC-US-GOV-CBP-UFLPA] [R:US-L6-UFLPA-001]；**原产国标记**须英文永久 [SRC-US-GOV-ECFR-19CFR134] [R:US-L6-CBP-001]；假冒侵权商品扣押没收 [R:US-L6-CBP-002]。
- **PGA 申报**：CPSC eFiling（2026-07-08 起，FTZ 2027-01-08）[SRC-US-GOV-FR-2024-30826] [R:US-L6-EFILE-001]；FDA 预先通报/FSVP 与 FDA 入境申报 [R:US-L6-FDAIMP-001] [R:US-L6-FDAIMP-002]；EPA 到货通知/TSCA 证明 [R:US-L6-IMPORT-002]；NHTSA HS-7、FCC 进口条件 [R:US-L6-IMPORT-003]；木质包装 ISPM 15、Lacey 申报、动物源产品 [R:US-L6-APHIS-001] [R:US-L6-LACEY-001] [R:US-L6-APHIS-003]。

| 适用法规 | 必需的认证/测试 | 注册/备案/文件 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 【强制合规】小额包裹免税（$800 de minimis）已对所有国家暂停：每票货都须正式或非正式报关并缴税 [SRC-US-GOV-FR-2025-14897] [SRC-US-GOV-FR-2026-03829] [SRC-US-GOV-FR-2026-12670] | — | 确定美国进口商（IOR）、海关保证金与报关行；海运货物在装船前 24 小时提交 ISF（19 CFR 149）；按 HTS 归类与申报价值缴纳关税/税费（含 PGA 申报数据） | — | CBP 及相关 PGA | [R:US-L6-IMPORT-001] |
| 【提示】对华关税现状（以入境日为准）：IEEPA 关税已终止，301 条款关税（含 2026-07-24 起的强迫劳动 301 关税 12.5%）与 232 条款关税仍有效 [SRC-US-GOV-FR-2026-03832] [SRC-US-GOV-FR-2026-03824] [SRC-US-GOV-FR-2026-15181] | — | 入境前按 HTS 编码核对适用的 301/232/反倾销反补贴税率与豁免 | — | USTR / CBP | [R:US-L6-TARIFF-001] |
| 【禁售】新疆相关商品推定为强迫劳动产品，禁止进口（UFLPA）；禁止事项：不得进口含新疆原料/工序或 UFLPA 实体清单企业生产的商品 [SRC-US-GOV-CBP-UFLPA] [SRC-US-GOV-FR-2026-17926] | — | 供应链溯源文件（原料来源、采购合同、生产记录、运输单据），以备 CBP 扣留时举证 | — | CBP / DHS FLETF | [R:US-L6-UFLPA-001] |
| 【强制合规】进口商品须以英文永久标注原产国（如 Made in China） [SRC-US-GOV-ECFR-19CFR134] | — | — | 产品/包装英文原产国标记（Made in China / China）；必备语句：产品或最小销售包装须有英文原产国标记，如 Made in China | CBP | [R:US-L6-CBP-001] |
| 【禁售】带假冒商标或侵犯版权的商品禁止进口，CBP 可扣留没收；禁止事项：不得进口假冒商标、侵权复制品 [SRC-US-GOV-ECFR-19CFR133] | — | 品牌授权/商标注册证明，必要时在 CBP 做 IPR 备案 | — | CBP | [R:US-L6-CBP-002] |
| 【强制合规】CPSC 电子申报（eFiling）：受 CPSC 规则约束的进口消费品自 2026-07-08 起须在报关时申报证书数据 [SRC-US-GOV-ECFR-16CFR1110] [SRC-US-GOV-FR-2024-30826] | — | CPSC Product Registry 录入证书数据（可选，便于引用）；报关时经 ACE 提交 CPSC PGA 证书数据要素 | — | CPSC / CBP | [R:US-L6-EFILE-001] |
| 【强制合规】进口食品（含膳食补充剂、宠物食品）须提交 FDA 预先通报，进口商须实施 FSVP [SRC-US-GOV-ECFR-21CFR1_279] [SRC-US-GOV-ECFR-21CFR1_502] | — | FDA 预先通报（Prior Notice）；FSVP 计划与记录（FSVP 进口商须在入境申报中列明） | — | FDA / CBP | [R:US-L6-FDAIMP-001] |
| 【强制合规】化妆品、药品、医疗器械、辐射电子产品进口须向 FDA 申报（含 FDA 2877 表） [SRC-US-GOV-ECFR-21CFR1005] [SRC-US-GOV-FDA-FORM-2877] | — | FDA 入境申报数据与合规确认代码（AofC）；辐射电子产品 FDA 2877 申报与 accession number | — | FDA / CBP | [R:US-L6-FDAIMP-002] |
| 【强制合规】农药及农药器械进口前须提交 EPA 到货通知；化学品进口须做 TSCA 证明 [SRC-US-GOV-ECFR-19CFR12_112] [SRC-US-GOV-ECFR-19CFR12_121] | — | EPA 到货通知（Notice of Arrival, Form 3540-1）；TSCA 进口证明（正面/负面） | — | CBP 及相关 PGA | [R:US-L6-IMPORT-002] |
| 【强制合规】汽车设备进口须提交 NHTSA HS-7 申报；射频设备须满足 FCC 进口条件 [SRC-US-GOV-ECFR-49CFR591_5] [SRC-US-GOV-ECFR-47CFR2_1204] [SRC-US-GOV-ECFR-47CFR2_903] | — | NHTSA HS-7 申报（汽车设备）；FCC 授权信息（FCC ID/SDoC）以满足进口条件 | — | CBP 及相关 PGA | [R:US-L6-IMPORT-003] |
| 【强制合规】木质包装（托盘、木箱、垫木）须经 ISPM 15 热处理/熏蒸并加 IPPC 标识 [SRC-US-GOV-ECFR-7CFR319_40-3] | — | 托盘/木箱使用带 IPPC 标识的 ISPM 15 合规木质包装（或改用塑料/纸托盘） | — | USDA APHIS | [R:US-L6-APHIS-001] |
| 【强制合规】含植物材料（木、竹、纸、植物精油等）的商品进口须按 Lacey 法提交植物申报 [SRC-US-GOV-APHIS-LACEY] | — | Lacey 植物申报（属/种学名、采伐国、价值、数量、回收材料比例）；向供应商收集木材/竹材种名与产地证明 | — | USDA APHIS / CBP | [R:US-L6-LACEY-001] |
| 【强制合规】动物源产品（羽毛、皮张、骨角、宠物咀嚼物等）进口须符合 APHIS 卫生要求或许可 [SRC-US-GOV-ECFR-9CFR95] | — | APHIS VS 进口许可（如需要）；出口国官方卫生证书或处理证明 | — | USDA APHIS | [R:US-L6-APHIS-003] |
| 【强制合规】野生动物及其制品进口须向 FWS 申报（3-177 表），商业进口须持 FWS 许可证，CITES 物种须许可 [SRC-US-GOV-ECFR-50CFR14] | — | FWS 3-177 申报（eDecs）；FWS 进出口许可证（商业进口）及 CITES 许可（如适用） | — | FWS | [R:US-L6-FWS-001] |
| 【禁售】象牙、海洋哺乳动物制品等受保护野生动物制品禁止进口和销售；禁止事项：不得进口或销售象牙制品、海洋哺乳动物制品（海豹皮、鲸骨、海象牙等）及鲨鱼鳍产品 [SRC-US-GOV-ECFR-50CFR17_40] [SRC-US-GOV-USC-16USC1372] | — | — | — | FWS | [R:US-L6-FWS-002] |
| 【禁售】狗毛、猫毛制品禁止进口、销售；禁止事项：不得进口或销售含狗毛、猫毛的制品 [SRC-US-GOV-USC-19USC1308] | 毛皮物种鉴定（必要时） | — | — | CBP 及相关 PGA | [R:US-L6-IMPORT-004] |
| 【禁售】毒品吸食用具（drug paraphernalia）禁止进口和销售；禁止事项：不得进口、销售吸毒用具（含以大麻、毒品为暗示营销的烟具） [SRC-US-GOV-USC-21USC863] | — | — | — | CBP 及相关 PGA | [R:US-L6-IMPORT-005] |
| 【禁售】弹簧刀、蝴蝶刀（balisong）、重力刀、弹射刀及其零件禁止进口；禁止事项：不得进口弹簧刀、蝴蝶刀（含练习用开刃款，待核）、重力刀、弹射刀及零件 [SRC-US-GOV-ECFR-19CFR12_95] [SRC-US-GOV-ECFR-19CFR12_97] | — | — | — | DOJ / CBP | [R:US-L6-KNIFE-001] |

### F. 标签、语言与本地责任人（法规要求部分）
- **语言**：CPSC 证书、eFiling 数据须英文 [SRC-US-GOV-ECFR-16CFR1110]；纽扣电池包装警示、吸水珠警示、窒息警示须英文 [SRC-US-GOV-ECFR-16CFR1263] [SRC-US-GOV-ECFR-16CFR1250] [R:US-L5-BTN-002] [R:US-L5-TOY-005]；食品、化妆品、药品、器械标签须英文（外语可并列）[R:US-L5-FOOD-002] [R:US-L5-COSM-003]。
- **原产国**：进口商品须以英文永久标注原产国 [SRC-US-GOV-ECFR-19CFR134] [R:US-L6-CBP-001]；纺织品标签与网页均须披露 [R:US-L5-FTC-001]；不得虚标 Made in USA [R:US-L5-FTC-004]。
- **追踪与身份信息**：儿童产品及包装须有永久追踪标签 [SRC-US-GOV-USC-15USC2063] [R:US-L5-CPSIA-005]；耐用婴幼儿产品须永久标识与注册卡 [R:US-L5-CPSIA-006]；FPLA 要求包装标明责任方名称地址与双单位净含量 [R:US-L5-FTC-008]。
- **美国境内责任人/代理人**（中国卖家最容易漏的项目）：

| 制度 | 要求 | 规则ID |
|---|---|---|
| FCC SDoC | 负责方必须位于美国，合规信息声明随产品 [SRC-US-GOV-ECFR-47CFR2_909] | [R:US-L5-FCC-002] |
| FCC 认证 | 申请人须指定美国送达代理人 [SRC-US-GOV-ECFR-47CFR2] | [R:US-L5-FCC-001] |
| CPSC 证书 | 进口商为出证方，须列记录保管人联系方式 [SRC-US-GOV-ECFR-16CFR1110] | [R:US-L5-CPSC-001] |
| FDA 化妆品 | 外国设施注册须提供美国代理人；标签须有美国地址/电话/网站 [SRC-US-GOV-USC-21USC364C] [SRC-US-GOV-USC-21USC364E] | [R:US-L5-COSM-001] [R:US-L5-COSM-003] |
| FDA 食品 | 外国设施须指定美国代理人；FSVP 须有美国进口商 [SRC-US-GOV-ECFR-21CFR1_230] [SRC-US-GOV-ECFR-21CFR1_502] | [R:US-L5-FOOD-001] [R:US-L6-FDAIMP-001] |
| FDA 药品/器械 | 外国企业注册须指定美国代理人；器械首次进口商须注册 [SRC-US-GOV-ECFR-21CFR207] [SRC-US-GOV-ECFR-21CFR807] | [R:US-L5-DRUG-001] [R:US-L5-DEV-002] |
| FDA 辐射产品 | 外国制造商进口前须指定美国常住代理人 [SRC-US-GOV-ECFR-21CFR1005_25] | [R:US-L5-RAD-001] |
| NHTSA | 外国汽车设备制造商须指定美国送达代理人 [SRC-US-GOV-ECFR-49CFR551] | [R:US-L5-NHTSA-001] |
| 膳食补充剂/化妆品不良事件 | 标签须有美国地址或电话 [SRC-US-GOV-ECFR-21CFR101_36] | [R:US-L5-SUPP-001] |

- **必备警示语**（详见各规则 listing_constraints）：窒息警示（含网页）[R:US-L5-TOY-003]、奶嘴警示 [R:US-L5-JUV-009]、紧身睡衣吊牌 [R:US-L5-CHILD-001]、软包家具合规标签 [R:US-L5-FLAM-002]、床垫 1633 标签 [R:US-L5-FLAM-001]、发电机 CO 标签 [R:US-L5-HOME-001]、尼古丁警示 [R:US-L5-VAPE-003]、补充剂免责声明 [R:US-L5-SUPP-002]、煤焦油染发剂警示 [R:US-L5-COSM-009]、Prop 65 警示 [R:US-L5-PROP65-001]、TSCA Title VI 标注 [R:US-L5-TSCA-001]、美术材料 D-4236 [R:US-L5-CHILD-005]。

### G. 2024–2026 法规变化与生效日期

| 日期 | 变化 | 影响的产品 | 规则ID | 来源 |
|---|---|---|---|---|
| 2024-03-19 | Reese's Law（16 CFR 1263）执法宽限结束 | 含纽扣电池的消费品 | [R:US-L5-BTN-001] | [SRC-US-GOV-ECFR-16CFR1263] [SRC-US-S3-SGS-REESES-LAW-2024] |
| 2024-09-21 | 纽扣电池包装警示要求生效 | 单独销售的纽扣电池 | [R:US-L5-BTN-002] | [SRC-US-GOV-ECFR-16CFR1263] |
| 2024-10-21 | FTC 虚假评论规则生效 | 所有商品 | [R:US-L5-FTC-009] | [SRC-US-GOV-ECFR-16CFR465] |
| 2024-10-31 | 禁止加工含 PIP(3:1) 的物品 | 电子电器塑料件等 | [R:US-L5-TSCA-003] | [SRC-US-GOV-ECFR-40CFR751_407] |
| 2024-12-29 | 化妆品标签须有美国联系方式（MoCRA 609(a)） | 化妆品 | [R:US-L5-COSM-003] | [SRC-US-GOV-USC-21USC364E] |
| 2025-01-01 | HFC 技术转型：GWP≥150 气雾剂、家用冰箱等禁止制造/进口 | 罐装除尘气、冰箱、空调、除湿机 | [R:US-L5-HFC-001] | [SRC-US-GOV-ECFR-40CFR84_54] |
| 2025-01-01 | 明尼苏达 11 类产品 PFAS 禁令；加州纺织品/化妆品 PFAS 禁令；Prop 65 简式警示修订生效 | 纺织、化妆品、炊具、婴童等 | [R:US-L5-PFAS-004] [R:US-L5-PFAS-001] [R:US-L5-PROP65-001] | [SRC-US-GOV-MN-STAT-116-943] [SRC-US-GOV-OEHHA-P65-ART6-2024] |
| 2025-04-23 / 05-05 | 哺乳枕、婴儿支撑垫强制标准 | 婴童 | [R:US-L5-SLEEP-008] [R:US-L5-SLEEP-007] | [SRC-US-GOV-ECFR-16CFR1242] [SRC-US-GOV-ECFR-16CFR1243] |
| 2025-05-02 | 对中国/香港取消小额免税 | 所有直邮商品 | [R:US-L6-IMPORT-001] | [SRC-US-GOV-FR-2025-14897] |
| 2025-05-05 / 06-16 | 二氯甲烷产品零售禁止；TCE 产品分销禁止 | 脱漆剂、清洁剂 | [R:US-L5-TSCA-004] | [SRC-US-GOV-ECFR-40CFR751_107] [SRC-US-GOV-ECFR-40CFR751_305] |
| 2025-08-29 | 对所有国家暂停小额免税 | 所有商品 | [R:US-L6-IMPORT-001] | [SRC-US-GOV-FR-2025-14897] |
| 2025-09-08 | FCC 受禁止实体实验室/TCB 不再被承认 | 全部射频/电子产品 | [R:US-L5-FCC-007] | [SRC-US-GOV-FR-2025-14970] |
| 2025-11-28 | FDA 撤回滑石粉石棉检测拟议规则 | 化妆品 | [R:US-L5-COSM-006] | [SRC-US-GOV-FR-2025-21407] |
| 2025-12-22 | 外国生产无人机及关键部件列入 FCC Covered List | 无人机 | [R:US-L5-FCC-006] | [SRC-US-GOV-FR-2026-15418] |
| 2026-01-01 | 缅因 9 类 PFAS 禁令；纽约泡沫保温箱禁令；加州电动自行车电池认证 | 纺织、炊具、化妆品、包装、电动自行车 | [R:US-L5-PFAS-004] [R:US-L5-PKG-001] [R:US-L5-STATE-001] | [SRC-US-GOV-ME-DEP-PFAS-PRODUCTS] [SRC-US-GOV-NYDEC-FOAM-FREE] |
| 2026-02-02 | 医疗器械 QMSR（对齐 ISO 13485）生效 | 医疗器械 | [R:US-L5-DEV-003] | [SRC-US-GOV-ECFR-21CFR820] |
| 2026-02-20/24 | IEEPA 关税终止；122 条款 10% 附加税（150 天）；继续暂停小额免税 | 所有进口商品 | [R:US-L6-TARIFF-001] [R:US-L6-IMPORT-001] | [SRC-US-GOV-FR-2026-03832] [SRC-US-GOV-FR-2026-03824] [SRC-US-GOV-FR-2026-03829] |
| 2026-03-12 | 吸水珠玩具强制要求 | 玩具 | [R:US-L5-TOY-005] | [SRC-US-GOV-FR-2025-22643] |
| 2026-05-03 | 婴儿床垫 ASTM F2933-25 | 婴儿床垫 | [R:US-L5-SLEEP-006] | [SRC-US-GOV-FR-2026-02855] |
| 2026-06-10 / 09-11 | 防晒专论新增 bemotrizinol；剔除 PABA 与水杨酸三乙醇胺 | 防晒 | [R:US-L5-DRUG-002] | [SRC-US-GOV-FR-2026-11578] [SRC-US-GOV-FR-2026-18551] |
| 2026-06-15 | 颈圈浮具强制要求（第三方检测可延至 08-16） | 婴幼儿水上玩具 | [R:US-L5-TOY-006] | [SRC-US-GOV-FR-2025-22827] [SRC-US-GOV-FR-2026-09977] |
| 2026-06-24 | CPSC 微出行锂电池拟议规则（16 CFR 1265）| 电动自行车/滑板车/平衡车 | [R:US-L5-MICRO-001] | [SRC-US-GOV-FR-2026-12749] |
| 2026-06-24 / 07-24 | CBP 无限期暂停 de minimis（非邮政/邮政）| 所有商品 | [R:US-L6-IMPORT-001] | [SRC-US-GOV-FR-2026-12670] [SRC-US-GOV-FR-2026-12669] |
| 2026-07-08 | CPSC eFiling 生效（FTZ 2027-01-08）| 受 CPSC 规则约束的进口商品 | [R:US-L6-EFILE-001] | [SRC-US-GOV-FR-2024-30826] |
| 2026-07-14 | 加州 SB 343 被联邦法院初步禁止执行 | 包装回收标识 | [R:US-L5-PKG-002] | [SRC-US-S3-MORGANLEWIS-SB343-2026] |
| 2026-07-16 | 2024 年及以前列入 Covered List 的已授权设备禁止进口与营销 | 海康、大华等设备 | [R:US-L5-FCC-005] | [SRC-US-GOV-FR-2026-13518] |
| 2026-07-19 至 08-29 | 门栏、挂桌椅、秋千、全尺寸婴儿床、幼儿床标准更新 | 婴童 | [R:US-L5-JUV-006] [R:US-L5-JUV-003] [R:US-L5-JUV-005] [R:US-L5-SLEEP-005] [R:US-L5-JUV-008] | [SRC-US-GOV-FR-2026-06306] [SRC-US-GOV-FR-2026-08632] [SRC-US-GOV-FR-2026-09640] |
| 2026-07-24 | 对华 12.5% 强迫劳动 301 关税 | 所有中国商品（有豁免） | [R:US-L6-TARIFF-001] | [SRC-US-GOV-FR-2026-15181] |
| 2026-09-15 | 明尼苏达 PFAS 产品申报截止（延期后，二手来源） | 含 PFAS 产品 | [R:US-L5-PFAS-005] | [SRC-US-S3-BDLAW-MN-PFAS-2026] |
| 2026-10-01 至 12-31 | FDA 食品设施两年一次注册续期 | 食品、补充剂、宠物食品 | [R:US-L5-FOOD-001] | [SRC-US-GOV-ECFR-21CFR1_230] |
| 2026-10-13 | FCC 在线市场 FCC ID 展示规则生效（合规 2027-03-01 / 06-01）| 射频设备 listing | [R:US-L5-FCC-004] | [SRC-US-GOV-FR-2026-18535] |
| 2026-10-31 | 禁止分销含 PIP(3:1) 的物品 | 电子电器等 | [R:US-L5-TSCA-003] | [SRC-US-GOV-ECFR-40CFR751_407] |
| 2026-11-12 | 联邦 hemp 定义收窄生效 | CBD/THC 产品 | [R:US-L5-HEMP-002] | [SRC-US-GOV-PL-119-37] |
| 2026-12-05 | FMVSS 213a 侧碰合规日 | 儿童汽车座椅 | [R:US-L5-NHTSA-004] | [SRC-US-GOV-FR-2026-18380] |
| 2027-01-15 | 红色 3 号禁用于食品与补充剂 | 糖果、软糖、补充剂 | [R:US-L5-FOOD-003] | [SRC-US-GOV-FR-2025-00830] |
| 2027-01-31 | TSCA PFAS 报告申报期最早开始 | 进口含 PFAS 物品者 | [R:US-L5-TSCA-002] | [SRC-US-GOV-FR-2026-07062] |
| 2027-03-08 | 含 PCE 产品零售分销禁止 | 去污剂、刹车清洁剂 | [R:US-L5-TSCA-004] | [SRC-US-GOV-ECFR-40CFR751_605] |
| 2027-07-01 | 商业货物 de minimis 法定废止 | 所有商品 | [R:US-L6-IMPORT-001] | [SRC-US-GOV-PL-119-21] |
| 2028-01-01 | Prop 65 旧简式警示过渡期结束；HFC 受限产品禁止销售 | 加州销售商品；含 HFC 产品 | [R:US-L5-PROP65-001] [R:US-L5-HFC-001] | [SRC-US-GOV-OEHHA-P65-ART6-2024] [SRC-US-GOV-ECFR-40CFR84_54] |

### H. 来源清单

| 来源ID | 标题 | URL | 级别 | 访问方式 | 访问日期 |
|---|---|---|---|---|---|
| SRC-US-GOV-APHIS-LACEY | Lacey Act (plant product declaration) | https://www.aphis.usda.gov/plant-imports/lacey-act | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-CA-ASM-SB1271-ANALYSIS | SB 1271 (2024) e-bike battery safety – Assembly Transportation Committee analysis | https://atrn.assembly.ca.gov/media/3338 | S2 | search_snippet | 2026-10-10 |
| SRC-US-GOV-CA-SB1019-2014 | California SB 1019 (2014) flame retardant chemicals labeling – bill text | https://www.leginfo.ca.gov/pub/13-14/bill/sen/sb_1001-1050/sb_1019_bill_20140421_amended_sen_v97.html | S2 | search_snippet | 2026-10-10 |
| SRC-US-GOV-CARB-AB1346 | 2021 – Assembly Bill 1346 (Berman), Small Off-Road Engines | https://ww2.arb.ca.gov/2021-assembly-bill-1346-berman-marc-small-road-engines-chaptered | S2 | search_snippet | 2026-10-10 |
| SRC-US-GOV-CARB-AFTERMARKET | Manufacturers of Aftermarket Parts (VC 27156 Executive Orders) | https://ww2.arb.ca.gov/manufacturers-aftermarket-parts | S2 | search_snippet | 2026-10-10 |
| SRC-US-GOV-CARB-AIR-CLEANER | California's Regulation to Limit Ozone Emissions from Indoor Air Cleaning Devices (fact sheet) | https://ww2.arb.ca.gov/resources/fact-sheets/californias-regulation-limit-ozone-emissions-indoor-air-cleaning-devices | S2 | search_snippet | 2026-10-10 |
| SRC-US-GOV-CARB-CONSUMER-PRODUCTS | Consumer Products Regulation (17 CCR 94507–94517) | https://ww2.arb.ca.gov/node/27806 | S2 | search_snippet | 2026-10-10 |
| SRC-US-GOV-CBP-UFLPA | Uyghur Forced Labor Prevention Act | https://www.cbp.gov/trade/forced-labor/UFLPA | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-CDPH-FLAVOR-LAW | California Flavored Tobacco Law Fact Sheet (SB 793) | https://www.cdph.ca.gov/Programs/CCDPHP/DCDIC/CTCB/CDPH%20Document%20Library/CAFlavorTobaccoLaw/FlavorLawFactSheet.pdf | S2 | search_snippet | 2026-10-10 |
| SRC-US-GOV-CEC-APPLIANCE-EFFICIENCY | Appliance Efficiency Program (Title 20, MAEDbS) | https://www.energy.ca.gov/programs-and-topics/programs/appliance-efficiency-program-outreach-and-education/appliance | S2 | search_snippet | 2026-10-10 |
| SRC-US-GOV-ECFR-10CFR429_12 | 10 CFR 429.12 General requirements applicable to certification reports | https://www.ecfr.gov/current/title-10/section-429.12 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-10CFR430_32 | 10 CFR 430.32 Energy and water conservation standards and their compliance dates | https://www.ecfr.gov/current/title-10/section-430.32 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-14CFR48 | 14 CFR Part 48 Registration and Marking Requirements for Small Unmanned Aircraft | https://www.ecfr.gov/current/title-14/part-48 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-14CFR89 | 14 CFR Part 89 Remote Identification of Unmanned Aircraft | https://www.ecfr.gov/current/title-14/part-89 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1107 | 16 CFR Part 1107 Testing and Labeling Pertaining to Product Certification | https://www.ecfr.gov/current/title-16/part-1107 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1110 | 16 CFR Part 1110 Certificates of Compliance | https://www.ecfr.gov/current/title-16/part-1110 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1112 | 16 CFR Part 1112 Requirements Pertaining to Third Party Conformity Assessment Bodies | https://www.ecfr.gov/current/title-16/part-1112 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1115 | 16 CFR Part 1115 Substantial Product Hazard Reports | https://www.ecfr.gov/current/title-16/part-1115 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1120 | 16 CFR Part 1120 Substantial Product Hazard List | https://www.ecfr.gov/current/title-16/part-1120 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1130 | 16 CFR Part 1130 Requirements for Consumer Registration of Durable Infant or Toddler Products | https://www.ecfr.gov/current/title-16/part-1130 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1200 | 16 CFR Part 1200 Definition of Children's Product Under the CPSA | https://www.ecfr.gov/current/title-16/part-1200 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1202 | 16 CFR Part 1202 Safety Standard for Matchbooks | https://www.ecfr.gov/current/title-16/part-1202 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1203 | 16 CFR Part 1203 Safety Standard for Bicycle Helmets | https://www.ecfr.gov/current/title-16/part-1203 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1205 | 16 CFR Part 1205 Safety Standard for Walk-Behind Power Lawn Mowers | https://www.ecfr.gov/current/title-16/part-1205 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1210 | 16 CFR Part 1210 Safety Standard for Cigarette Lighters | https://www.ecfr.gov/current/title-16/part-1210 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1211 | 16 CFR Part 1211 Safety Standard for Automatic Residential Garage Door Operators | https://www.ecfr.gov/current/title-16/part-1211 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1212 | 16 CFR Part 1212 Safety Standard for Multi-Purpose Lighters | https://www.ecfr.gov/current/title-16/part-1212 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1213 | 16 CFR Part 1213 Safety Standard for Entrapment Hazards in Bunk Beds | https://www.ecfr.gov/current/title-16/part-1213 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1215 | 16 CFR Part 1215 Safety Standard for Infant Bath Seats | https://www.ecfr.gov/current/title-16/part-1215 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1216 | 16 CFR Part 1216 Safety Standard for Infant Walkers | https://www.ecfr.gov/current/title-16/part-1216 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1217 | 16 CFR Part 1217 Safety Standard for Toddler Beds | https://www.ecfr.gov/current/title-16/part-1217 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1218 | 16 CFR Part 1218 Safety Standard for Bassinets and Cradles | https://www.ecfr.gov/current/title-16/part-1218 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1219 | 16 CFR Part 1219 Safety Standard for Full-Size Baby Cribs | https://www.ecfr.gov/current/title-16/part-1219 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1220 | 16 CFR Part 1220 Safety Standard for Non-Full-Size Baby Cribs | https://www.ecfr.gov/current/title-16/part-1220 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1221 | 16 CFR Part 1221 Safety Standard for Play Yards | https://www.ecfr.gov/current/title-16/part-1221 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1222 | 16 CFR Part 1222 Safety Standard for Bedside Sleepers | https://www.ecfr.gov/current/title-16/part-1222 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1223 | 16 CFR Part 1223 Safety Standard for Infant and Cradle Swings | https://www.ecfr.gov/current/title-16/part-1223 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1224 | 16 CFR Part 1224 Safety Standard for Portable Bed Rails | https://www.ecfr.gov/current/title-16/part-1224 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1225 | 16 CFR Part 1225 Safety Standard for Hand-Held Infant Carriers | https://www.ecfr.gov/current/title-16/part-1225 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1226 | 16 CFR Part 1226 Safety Standard for Soft Infant and Toddler Carriers | https://www.ecfr.gov/current/title-16/part-1226 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1227 | 16 CFR Part 1227 Safety Standard for Carriages and Strollers | https://www.ecfr.gov/current/title-16/part-1227 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1228 | 16 CFR Part 1228 Safety Standard for Sling Carriers | https://www.ecfr.gov/current/title-16/part-1228 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1229 | 16 CFR Part 1229 Safety Standard for Infant Bouncer Seats | https://www.ecfr.gov/current/title-16/part-1229 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1230 | 16 CFR Part 1230 Safety Standard for Frame Child Carriers | https://www.ecfr.gov/current/title-16/part-1230 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1231 | 16 CFR Part 1231 Safety Standard for High Chairs | https://www.ecfr.gov/current/title-16/part-1231 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1232 | 16 CFR Part 1232 Safety Standard for Children's Folding Chairs and Stools | https://www.ecfr.gov/current/title-16/part-1232 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1233 | 16 CFR Part 1233 Safety Standard for Portable Hook-on Chairs | https://www.ecfr.gov/current/title-16/part-1233 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1234 | 16 CFR Part 1234 Safety Standard for Infant Bath Tubs | https://www.ecfr.gov/current/title-16/part-1234 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1235 | 16 CFR Part 1235 Safety Standard for Baby Changing Products | https://www.ecfr.gov/current/title-16/part-1235 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1236 | 16 CFR Part 1236 Safety Standard for Infant Sleep Products | https://www.ecfr.gov/current/title-16/part-1236 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1237 | 16 CFR Part 1237 Safety Standard for Booster Seats | https://www.ecfr.gov/current/title-16/part-1237 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1238 | 16 CFR Part 1238 Safety Standard for Stationary Activity Centers | https://www.ecfr.gov/current/title-16/part-1238 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1239 | 16 CFR Part 1239 Safety Standard for Gates and Enclosures | https://www.ecfr.gov/current/title-16/part-1239 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1241 | 16 CFR Part 1241 Safety Standard for Crib Mattresses | https://www.ecfr.gov/current/title-16/part-1241 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1242 | 16 CFR Part 1242 Safety Standard for Nursing Pillows | https://www.ecfr.gov/current/title-16/part-1242 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1243 | 16 CFR Part 1243 Safety Standard for Infant Support Cushions | https://www.ecfr.gov/current/title-16/part-1243 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1250 | 16 CFR Part 1250 Safety Standard for Toys (ASTM F963-23) | https://www.ecfr.gov/current/title-16/part-1250 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1261 | 16 CFR Part 1261 Safety Standard for Clothing Storage Units | https://www.ecfr.gov/current/title-16/part-1261 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1262 | 16 CFR Part 1262 Safety Standard for Magnets | https://www.ecfr.gov/current/title-16/part-1262 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1263 | 16 CFR Part 1263 Safety Standard for Button Cell or Coin Batteries and Consumer Products Containing Such Batteries | https://www.ecfr.gov/current/title-16/part-1263 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1270 | 16 CFR Part 1270 Safety Standard for Adult Portable Bed Rails | https://www.ecfr.gov/current/title-16/part-1270 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1272 | 16 CFR Part 1272 Marking of Toy, Look-Alike, and Imitation Firearms | https://www.ecfr.gov/current/title-16/part-1272 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1303 | 16 CFR Part 1303 Ban of Lead-Containing Paint and Certain Consumer Products Bearing Lead-Containing Paint | https://www.ecfr.gov/current/title-16/part-1303 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1306 | 16 CFR Part 1306 Ban of Hazardous Lawn Darts | https://www.ecfr.gov/current/title-16/part-1306 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1307 | 16 CFR Part 1307 Prohibition of Children's Toys and Child Care Articles Containing Specified Phthalates | https://www.ecfr.gov/current/title-16/part-1307 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1309 | 16 CFR Part 1309 Ban of Crib Bumpers | https://www.ecfr.gov/current/title-16/part-1309 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1310 | 16 CFR Part 1310 Ban of Inclined Sleepers for Infants | https://www.ecfr.gov/current/title-16/part-1310 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1407 | 16 CFR Part 1407 Portable Generators: Requirements to Provide Performance and Technical Data by Labeling | https://www.ecfr.gov/current/title-16/part-1407 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1450 | 16 CFR Part 1450 Virginia Graeme Baker Pool and Spa Safety Act Regulations | https://www.ecfr.gov/current/title-16/part-1450 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1460 | 16 CFR Part 1460 Children's Gasoline Burn Prevention Act Regulation | https://www.ecfr.gov/current/title-16/part-1460 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1461 | 16 CFR Part 1461 Portable Fuel Container Safety Act Regulation | https://www.ecfr.gov/current/title-16/part-1461 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1500 | 16 CFR Part 1500 Hazardous Substances and Articles: Administration and Enforcement Regulations | https://www.ecfr.gov/current/title-16/part-1500 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1500_121 | 16 CFR 1500.121 Labeling requirements; prominence, placement, and conspicuousness | https://www.ecfr.gov/current/title-16/section-1500.121 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1500_14 | 16 CFR 1500.14 Products requiring special labeling under section 3(b) of the act (incl. art materials) | https://www.ecfr.gov/current/title-16/section-1500.14 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1500_17 | 16 CFR 1500.17 Banned hazardous substances | https://www.ecfr.gov/current/title-16/section-1500.17 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1500_18 | 16 CFR 1500.18 Banned toys and other banned articles intended for use by children | https://www.ecfr.gov/current/title-16/section-1500.18 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1500_19 | 16 CFR 1500.19 Misbranded toys and other articles intended for use by children | https://www.ecfr.gov/current/title-16/section-1500.19 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1500_20 | 16 CFR 1500.20 Labeling requirement for advertising toys and games | https://www.ecfr.gov/current/title-16/section-1500.20 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1500_48 | 16 CFR 1500.48 Technical requirements for determining a sharp point in toys | https://www.ecfr.gov/current/title-16/section-1500.48 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1500_49 | 16 CFR 1500.49 Technical requirements for determining a sharp metal or glass edge in toys | https://www.ecfr.gov/current/title-16/section-1500.49 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1501 | 16 CFR Part 1501 Method for Identifying Toys ... Under 3 Years ... Small Parts | https://www.ecfr.gov/current/title-16/part-1501 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1505 | 16 CFR Part 1505 Requirements for Electrically Operated Toys | https://www.ecfr.gov/current/title-16/part-1505 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1507 | 16 CFR Part 1507 Fireworks Devices | https://www.ecfr.gov/current/title-16/part-1507 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1510 | 16 CFR Part 1510 Requirements for Rattles | https://www.ecfr.gov/current/title-16/part-1510 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1511 | 16 CFR Part 1511 Requirements for Pacifiers | https://www.ecfr.gov/current/title-16/part-1511 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1512 | 16 CFR Part 1512 Requirements for Bicycles | https://www.ecfr.gov/current/title-16/part-1512 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1513 | 16 CFR Part 1513 Requirements for Bunk Beds | https://www.ecfr.gov/current/title-16/part-1513 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1610 | 16 CFR Part 1610 Standard for the Flammability of Clothing Textiles | https://www.ecfr.gov/current/title-16/part-1610 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1611 | 16 CFR Part 1611 Standard for the Flammability of Vinyl Plastic Film | https://www.ecfr.gov/current/title-16/part-1611 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1615 | 16 CFR Part 1615 Flammability of Children's Sleepwear: Sizes 0 Through 6X | https://www.ecfr.gov/current/title-16/part-1615 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1616 | 16 CFR Part 1616 Flammability of Children's Sleepwear: Sizes 7 Through 14 | https://www.ecfr.gov/current/title-16/part-1616 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1630 | 16 CFR Part 1630 Surface Flammability of Carpets and Rugs (FF 1-70) | https://www.ecfr.gov/current/title-16/part-1630 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1631 | 16 CFR Part 1631 Surface Flammability of Small Carpets and Rugs (FF 2-70) | https://www.ecfr.gov/current/title-16/part-1631 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1632 | 16 CFR Part 1632 Flammability of Mattresses and Mattress Pads (FF 4-72) | https://www.ecfr.gov/current/title-16/part-1632 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1633 | 16 CFR Part 1633 Flammability (Open Flame) of Mattress Sets | https://www.ecfr.gov/current/title-16/part-1633 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1640 | 16 CFR Part 1640 Standard for the Flammability of Upholstered Furniture | https://www.ecfr.gov/current/title-16/part-1640 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1700 | 16 CFR Part 1700 Poison Prevention Packaging | https://www.ecfr.gov/current/title-16/part-1700 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR1750 | 16 CFR Part 1750 Devices to Permit the Opening of Household Refrigerator Doors from the Inside | https://www.ecfr.gov/current/title-16/part-1750 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR23 | 16 CFR Part 23 Guides for the Jewelry, Precious Metals, and Pewter Industries | https://www.ecfr.gov/current/title-16/part-23 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR260 | 16 CFR Part 260 Guides for the Use of Environmental Marketing Claims (Green Guides) | https://www.ecfr.gov/current/title-16/part-260 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR300 | 16 CFR Part 300 Rules and Regulations Under the Wool Products Labeling Act | https://www.ecfr.gov/current/title-16/part-300 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR301 | 16 CFR Part 301 Fur Products Labeling | https://www.ecfr.gov/current/title-16/part-301 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR303 | 16 CFR Part 303 Rules and Regulations Under the Textile Fiber Products Identification Act | https://www.ecfr.gov/current/title-16/part-303 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR303_34 | 16 CFR 303.34 Country of origin in mail order advertising | https://www.ecfr.gov/current/title-16/section-303.34 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR305 | 16 CFR Part 305 Energy and Water Use Labeling for Consumer Products (Energy Labeling Rule) | https://www.ecfr.gov/current/title-16/part-305 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR305_27 | 16 CFR 305.27 Paper catalogs and websites | https://www.ecfr.gov/current/title-16/section-305.27 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR312 | 16 CFR Part 312 Children's Online Privacy Protection Rule | https://www.ecfr.gov/current/title-16/part-312 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR315 | 16 CFR Part 315 Contact Lens Rule | https://www.ecfr.gov/current/title-16/part-315 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR323 | 16 CFR Part 323 Made in USA Labeling Rule | https://www.ecfr.gov/current/title-16/part-323 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR423 | 16 CFR Part 423 Care Labeling of Textile Wearing Apparel and Certain Piece Goods | https://www.ecfr.gov/current/title-16/part-423 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR465 | 16 CFR Part 465 Rule on the Use of Consumer Reviews and Testimonials | https://www.ecfr.gov/current/title-16/part-465 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-16CFR500 | 16 CFR Part 500 Regulations Under Section 4 of the Fair Packaging and Labeling Act | https://www.ecfr.gov/current/title-16/part-500 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-19CFR12_112 | 19 CFR 12.112 Notice of arrival of pesticides and devices | https://www.ecfr.gov/current/title-19/section-12.112 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-19CFR12_121 | 19 CFR 12.121 TSCA import certification reporting requirements | https://www.ecfr.gov/current/title-19/section-12.121 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-19CFR12_95 | 19 CFR 12.95 Switchblade knives: definitions (incl. balisong, butterfly, gravity, ballistic) | https://www.ecfr.gov/current/title-19/section-12.95 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-19CFR12_97 | 19 CFR 12.97 Switchblade knives: importations contrary to law | https://www.ecfr.gov/current/title-19/section-12.97 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-19CFR133 | 19 CFR Part 133 Trademarks, Trade Names, and Copyrights | https://www.ecfr.gov/current/title-19/part-133 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-19CFR134 | 19 CFR Part 134 Country of Origin Marking | https://www.ecfr.gov/current/title-19/part-134 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-19CFR149 | 19 CFR Part 149 Importer Security Filing | https://www.ecfr.gov/current/title-19/part-149 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR1002 | 21 CFR Part 1002 Records and Reports (electronic products) | https://www.ecfr.gov/current/title-21/part-1002 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR1005 | 21 CFR Part 1005 Importation of Electronic Products | https://www.ecfr.gov/current/title-21/part-1005 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR1005_25 | 21 CFR 1005.25 Service of process on manufacturers | https://www.ecfr.gov/current/title-21/section-1005.25 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR101 | 21 CFR Part 101 Food Labeling | https://www.ecfr.gov/current/title-21/part-101 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR1010 | 21 CFR Part 1010 Performance Standards for Electronic Products: General | https://www.ecfr.gov/current/title-21/part-1010 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR101_36 | 21 CFR 101.36 Nutrition labeling of dietary supplements | https://www.ecfr.gov/current/title-21/section-101.36 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR101_93 | 21 CFR 101.93 Certain types of statements for dietary supplements | https://www.ecfr.gov/current/title-21/section-101.93 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR1030_10 | 21 CFR 1030.10 Microwave ovens | https://www.ecfr.gov/current/title-21/section-1030.10 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR1040_10 | 21 CFR 1040.10 Laser products | https://www.ecfr.gov/current/title-21/section-1040.10 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR1040_11 | 21 CFR 1040.11 Specific purpose laser products | https://www.ecfr.gov/current/title-21/section-1040.11 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR1040_20 | 21 CFR 1040.20 Sunlamp products and ultraviolet lamps intended for use in sunlamp products | https://www.ecfr.gov/current/title-21/section-1040.20 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR106 | 21 CFR Part 106 Infant Formula Requirements Pertaining to CGMP, Quality Control Procedures, Records and Reports | https://www.ecfr.gov/current/title-21/part-106 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR107 | 21 CFR Part 107 Infant Formula | https://www.ecfr.gov/current/title-21/part-107 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR109_16 | 21 CFR 109.16 Ornamental and decorative ceramicware | https://www.ecfr.gov/current/title-21/section-109.16 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR111 | 21 CFR Part 111 CGMP in Manufacturing, Packaging, Labeling, or Holding Operations for Dietary Supplements | https://www.ecfr.gov/current/title-21/part-111 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR1143_3 | 21 CFR 1143.3 Required warning statement regarding addictiveness of nicotine | https://www.ecfr.gov/current/title-21/section-1143.3 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR119_1 | 21 CFR 119.1 Dietary supplements containing ephedrine alkaloids | https://www.ecfr.gov/current/title-21/section-119.1 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR174 | 21 CFR Part 174 Indirect Food Additives: General | https://www.ecfr.gov/current/title-21/part-174 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR177 | 21 CFR Part 177 Indirect Food Additives: Polymers | https://www.ecfr.gov/current/title-21/part-177 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR177_1580 | 21 CFR 177.1580 Polycarbonate resins | https://www.ecfr.gov/current/title-21/section-177.1580 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR1_230 | 21 CFR 1.230 When must you register or renew your registration? (food facilities) | https://www.ecfr.gov/current/title-21/section-1.230 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR1_279 | 21 CFR 1.279 When must prior notice be submitted to FDA? | https://www.ecfr.gov/current/title-21/section-1.279 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR1_502 | 21 CFR 1.502 What foreign supplier verification program (FSVP) must I have? | https://www.ecfr.gov/current/title-21/section-1.502 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR201_66 | 21 CFR 201.66 Format and content requirements for OTC drug product labeling | https://www.ecfr.gov/current/title-21/section-201.66 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR207 | 21 CFR Part 207 Requirements for Foreign and Domestic Establishment Registration and Listing for Human Drugs | https://www.ecfr.gov/current/title-21/part-207 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR207_77 | 21 CFR 207.77 What legal status is conferred by registration and listing? | https://www.ecfr.gov/current/title-21/section-207.77 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR501 | 21 CFR Part 501 Animal Food Labeling | https://www.ecfr.gov/current/title-21/part-501 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR700 | 21 CFR Part 700 Cosmetics: General (prohibited and restricted ingredients) | https://www.ecfr.gov/current/title-21/part-700 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR700_13 | 21 CFR 700.13 Use of mercury compounds in cosmetics | https://www.ecfr.gov/current/title-21/section-700.13 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR701 | 21 CFR Part 701 Cosmetic Labeling | https://www.ecfr.gov/current/title-21/part-701 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR73 | 21 CFR Part 73 Listing of Color Additives Exempt from Certification | https://www.ecfr.gov/current/title-21/part-73 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR74 | 21 CFR Part 74 Listing of Color Additives Subject to Certification | https://www.ecfr.gov/current/title-21/part-74 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR740 | 21 CFR Part 740 Cosmetic Product Warning Statements | https://www.ecfr.gov/current/title-21/part-740 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR800_30 | 21 CFR 800.30 Over-the-counter hearing aid controls | https://www.ecfr.gov/current/title-21/section-800.30 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR801 | 21 CFR Part 801 Labeling (medical devices) | https://www.ecfr.gov/current/title-21/part-801 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR801_410 | 21 CFR 801.410 Use of impact-resistant lenses in eyeglasses and sunglasses | https://www.ecfr.gov/current/title-21/section-801.410 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR803 | 21 CFR Part 803 Medical Device Reporting | https://www.ecfr.gov/current/title-21/part-803 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR807 | 21 CFR Part 807 Establishment Registration and Device Listing for Manufacturers and Initial Importers of Devices | https://www.ecfr.gov/current/title-21/part-807 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR807_39 | 21 CFR 807.39 Misbranding by reference to establishment registration or to registration number | https://www.ecfr.gov/current/title-21/section-807.39 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR820 | 21 CFR Part 820 Quality Management System Regulation | https://www.ecfr.gov/current/title-21/part-820 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR878_4635 | 21 CFR 878.4635 Sunlamp products and ultraviolet lamps intended for use in sunlamp products (device classification) | https://www.ecfr.gov/current/title-21/section-878.4635 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR884_5300 | 21 CFR 884.5300 Condom | https://www.ecfr.gov/current/title-21/section-884.5300 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-21CFR886_5850 | 21 CFR 886.5850 Sunglasses (nonprescription) | https://www.ecfr.gov/current/title-21/section-886.5850 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-27CFR1 | 27 CFR Part 1 Basic Permit Requirements Under the Federal Alcohol Administration Act | https://www.ecfr.gov/current/title-27/part-1 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-27CFR13 | 27 CFR Part 13 Labeling Proceedings (Certificate of Label Approval, COLA) | https://www.ecfr.gov/current/title-27/part-13 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-27CFR478_11 | 27 CFR 478.11 Meaning of terms (machine gun, firearm silencer) | https://www.ecfr.gov/current/title-27/section-478.11 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-27CFR478_12 | 27 CFR 478.12 Definition of Frame or Receiver | https://www.ecfr.gov/current/title-27/section-478.12 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-40CFR1054 | 40 CFR Part 1054 Control of Emissions from New, Small Nonroad Spark-Ignition Engines and Equipment | https://www.ecfr.gov/current/title-40/part-1054 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-40CFR152_15 | 40 CFR 152.15 Pesticide products required to be registered | https://www.ecfr.gov/current/title-40/section-152.15 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-40CFR152_25 | 40 CFR 152.25 Exemptions for pesticides of a character not requiring FIFRA regulation (treated articles, minimum risk) | https://www.ecfr.gov/current/title-40/section-152.25 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-40CFR152_500 | 40 CFR 152.500 Requirements for devices | https://www.ecfr.gov/current/title-40/section-152.500 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-40CFR167 | 40 CFR Part 167 Registration of Pesticide and Active Ingredient Producing Establishments | https://www.ecfr.gov/current/title-40/part-167 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-40CFR59 | 40 CFR Part 59 National Volatile Organic Compound Emission Standards for Consumer and Commercial Products (incl. portable fuel containers subpart F) | https://www.ecfr.gov/current/title-40/part-59 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-40CFR705 | 40 CFR Part 705 Reporting and Recordkeeping Requirements for Perfluoroalkyl and Polyfluoroalkyl Substances | https://www.ecfr.gov/current/title-40/part-705 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-40CFR751_105 | 40 CFR 751.105 Methylene chloride: consumer paint and coating removal | https://www.ecfr.gov/current/title-40/section-751.105 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-40CFR751_107 | 40 CFR 751.107 Methylene chloride: other consumer, industrial and commercial uses | https://www.ecfr.gov/current/title-40/section-751.107 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-40CFR751_305 | 40 CFR 751.305 Trichloroethylene (TCE): prohibitions | https://www.ecfr.gov/current/title-40/section-751.305 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-40CFR751_407 | 40 CFR 751.407 PIP (3:1) | https://www.ecfr.gov/current/title-40/section-751.407 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-40CFR751_605 | 40 CFR 751.605 Perchloroethylene (PCE): consumer use prohibitions | https://www.ecfr.gov/current/title-40/section-751.605 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-40CFR770 | 40 CFR Part 770 Formaldehyde Standards for Composite Wood Products | https://www.ecfr.gov/current/title-40/part-770 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-40CFR82_154 | 40 CFR 82.154 Prohibitions (refrigerant sales restriction) | https://www.ecfr.gov/current/title-40/section-82.154 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-40CFR84_54 | 40 CFR 84.54 Restrictions on the use of hydrofluorocarbons (Technology Transitions) | https://www.ecfr.gov/current/title-40/section-84.54 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-40CFR84_58 | 40 CFR 84.58 Labeling (HFC Technology Transitions) | https://www.ecfr.gov/current/title-40/section-84.58 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-47CFR15 | 47 CFR Part 15 Radio Frequency Devices | https://www.ecfr.gov/current/title-47/part-15 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-47CFR15_19 | 47 CFR 15.19 Labeling requirements | https://www.ecfr.gov/current/title-47/section-15.19 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-47CFR18 | 47 CFR Part 18 Industrial, Scientific, and Medical Equipment | https://www.ecfr.gov/current/title-47/part-18 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-47CFR2 | 47 CFR Part 2 Frequency Allocations and Radio Treaty Matters; General Rules and Regulations (Equipment Authorization) | https://www.ecfr.gov/current/title-47/part-2 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-47CFR20_21 | 47 CFR 20.21 Signal boosters | https://www.ecfr.gov/current/title-47/section-20.21 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-47CFR2_1077 | 47 CFR 2.1077 Compliance information | https://www.ecfr.gov/current/title-47/section-2.1077 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-47CFR2_1204 | 47 CFR 2.1204 Import conditions (radio frequency devices) | https://www.ecfr.gov/current/title-47/section-2.1204 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-47CFR2_803 | 47 CFR 2.803 Marketing of radio frequency devices prior to equipment authorization | https://www.ecfr.gov/current/title-47/section-2.803 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-47CFR2_903 | 47 CFR 2.903 Prohibition on authorization of equipment on the Covered List | https://www.ecfr.gov/current/title-47/section-2.903 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-47CFR2_909 | 47 CFR 2.909 Responsible party | https://www.ecfr.gov/current/title-47/section-2.909 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-47CFR95 | 47 CFR Part 95 Personal Radio Services (FRS/GMRS) | https://www.ecfr.gov/current/title-47/part-95 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-49CFR172 | 49 CFR Part 172 Hazardous Materials Table, Communications, Emergency Response Information, Training Requirements, and Security Plans | https://www.ecfr.gov/current/title-49/part-172 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-49CFR173_185 | 49 CFR 173.185 Lithium cells and batteries | https://www.ecfr.gov/current/title-49/section-173.185 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-49CFR173_308 | 49 CFR 173.308 Lighters | https://www.ecfr.gov/current/title-49/section-173.308 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-49CFR173_56 | 49 CFR 173.56 New explosives—definition and procedures for classification and approval | https://www.ecfr.gov/current/title-49/section-173.56 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-49CFR551 | 49 CFR Part 551 Procedural Rules (Subpart D: service of process on foreign manufacturers and importers) | https://www.ecfr.gov/current/title-49/part-551 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-49CFR566 | 49 CFR Part 566 Manufacturer Identification | https://www.ecfr.gov/current/title-49/part-566 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-49CFR571 | 49 CFR Part 571 Federal Motor Vehicle Safety Standards | https://www.ecfr.gov/current/title-49/part-571 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-49CFR571_108 | 49 CFR 571.108 FMVSS No. 108 Lamps, reflective devices, and associated equipment | https://www.ecfr.gov/current/title-49/section-571.108 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-49CFR571_213A | 49 CFR 571.213a FMVSS No. 213a Child restraint systems—side impact protection | https://www.ecfr.gov/current/title-49/section-571.213a | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-49CFR571_218 | 49 CFR 571.218 FMVSS No. 218 Motorcycle helmets | https://www.ecfr.gov/current/title-49/section-571.218 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-49CFR574 | 49 CFR Part 574 Tire Identification and Recordkeeping | https://www.ecfr.gov/current/title-49/part-574 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-49CFR591_5 | 49 CFR 591.5 Declarations required for importation (motor vehicle equipment, HS-7) | https://www.ecfr.gov/current/title-49/section-591.5 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-50CFR14 | 50 CFR Part 14 Importation, Exportation, and Transportation of Wildlife | https://www.ecfr.gov/current/title-50/part-14 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-50CFR17_40 | 50 CFR 17.40 Special rules—mammals (incl. (e) African elephant ivory) | https://www.ecfr.gov/current/title-50/section-17.40 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-7CFR319 | 7 CFR Part 319 Foreign Quarantine Notices (Subpart H 319.37: plants for planting) | https://www.ecfr.gov/current/title-7/part-319 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-7CFR319_40-3 | 7 CFR 319.40-3 Wood packaging material: general permits and ISPM 15 marking | https://www.ecfr.gov/current/title-7/section-319.40-3 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-ECFR-9CFR95 | 9 CFR Part 95 Sanitary Control of Animal Byproducts (except casings), and Hay and Straw, Offered for Entry into the United States | https://www.ecfr.gov/current/title-9/part-95 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-EPA-DEFEAT-DEVICE-FACTSHEET | EPA Fact Sheet re Aftermarket Defeat Devices and Tampering | https://www.epa.gov/enforcement/epa-fact-sheet-re-aftermarket-defeat-devices-and-tampering | S2 | search_snippet | 2026-10-10 |
| SRC-US-GOV-FDA-CBD | FDA Regulation of Cannabis and Cannabis-Derived Products, Including Cannabidiol (CBD) | https://www.fda.gov/news-events/public-health-focus/fda-regulation-cannabis-and-cannabis-derived-products-including-cannabidiol-cbd | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FDA-COSMETIC-REGISTRATION | Registration & Listing of Cosmetic Product Facilities and Products | https://www.fda.gov/cosmetics/registration-listing-cosmetic-product-facilities-and-products | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FDA-ENDS | E-Cigarettes, Vapes, and other Electronic Nicotine Delivery Systems (ENDS) | https://www.fda.gov/tobacco-products/tobacco-products-ingredients-components/e-cigarettes-vapes-and-other-electronic-nicotine-delivery-systems-ends | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FDA-FORM-2877 | Form FDA 2877 Declaration for Imported Electronic Products Subject to Radiation Control Standards | https://fda.gov/media/72236/download | S2 | search_snippet | 2026-10-10 |
| SRC-US-GOV-FDA-HYDROQUINONE-OTC | FDA works to protect consumers from potentially harmful OTC skin lightening products | https://www.fda.gov/drugs/drug-safety-communications/fda-works-protect-consumers-potentially-harmful-otc-skin-lightening-products | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FDA-LASER-INTERNET-ALERT | Consumer Safety Alert: Internet Sales of Laser Products | https://www.fda.gov/radiation-emitting-products/alerts-and-notices/consumer-safety-alert-internet-sales-laser-products | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FDA-MOCRA | Modernization of Cosmetics Regulation Act of 2022 (MoCRA) | https://www.fda.gov/cosmetics/cosmetics-laws-regulations/modernization-cosmetics-regulation-act-2022-mocra | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2014-29725 | Federal Register 2014-29725: Minimizing Risk for Children's Toy Laser Products; Guidance for Industry and FDA Staff | https://www.federalregister.gov/documents/2014/12/19/2014-29725/minimizing-risk-for-childrens-toy-laser-products-guidance-for-industry-and-food-and-drug | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2024-24403 | Federal Register 2024-24403: Safety Standard for Nursing Pillows (final rule) | https://www.federalregister.gov/documents/2024/10/25/2024-24403/safety-standard-for-nursing-pillows | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2024-25181 | Federal Register 2024-25181: Safety Standard for Infant Support Cushions (final rule) | https://www.federalregister.gov/documents/2024/11/04/2024-25181/safety-standard-for-infant-support-cushions | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2024-30826 | Federal Register 2024-30826: Certificates of Compliance (final rule, eFiling) | https://www.federalregister.gov/documents/2025/01/08/2024-30826/certificates-of-compliance | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2025-00830 | Federal Register 2025-00830: Revocation of FD&C Red No. 3 in Food and Ingested Drugs | https://www.federalregister.gov/documents/2025/01/16/2025-00830/color-additive-petition-from-center-for-science-in-the-public-interest-et-al-request-to-revoke-color | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2025-08587 | Federal Register 2025-08587: Energy Conservation Program: Energy Conservation Standards for External Power Supplies (proposed rescission) | https://www.federalregister.gov/documents/2025/05/16/2025-08587/energy-conservation-program-energy-conservation-standards-for-external-power-supplies | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2025-08596 | Federal Register 2025-08596: Proposed Withdrawal of Determination of Air Cleaners as a Covered Consumer Product | https://www.federalregister.gov/documents/2025/05/16/2025-08596/energy-conservation-program-proposed-withdrawal-of-determination-of-air-cleaners-as-a-covered | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2025-08598 | Federal Register 2025-08598: Energy Conservation Program: Rescinding the Efficiency Standards for Battery Chargers (proposed) | https://www.federalregister.gov/documents/2025/05/16/2025-08598/energy-conservation-program-rescinding-the-efficiency-standards-for-battery-chargers | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2025-14897 | Federal Register 2025-14897: Executive Order 14324: Suspending Duty-Free De Minimis Treatment for All Countries | https://www.federalregister.gov/documents/2025/08/05/2025-14897/suspending-duty-free-de-minimis-treatment-for-all-countries | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2025-14970 | Federal Register 2025-14970: Promoting the Integrity and Security of TCBs, Measurement Facilities, and the Equipment Authorization Program (FCC 25-27) | https://www.federalregister.gov/documents/2025/08/07/2025-14970/promoting-the-integrity-and-security-of-telecommunications-certification-bodies-measurement | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2025-19882 | Federal Register 2025-19882: PFAS Data Reporting and Recordkeeping Under TSCA; Revision to Regulation (proposed exemptions) | https://www.federalregister.gov/documents/2025/11/13/2025-19882/perfluoroalkyl-and-polyfluoroalkyl-substances-pfas-data-reporting-and-recordkeeping-under-the-toxic | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2025-21407 | Federal Register 2025-21407: Testing Methods for Detecting and Identifying Asbestos in Talc-Containing Cosmetic Products; Withdrawal | https://www.federalregister.gov/documents/2025/11/28/2025-21407/testing-methods-for-detecting-and-identifying-asbestos-in-talc-containing-cosmetic-products | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2025-22643 | Federal Register 2025-22643: Safety Standard for Toys: Requirements for Water Beads | https://www.federalregister.gov/documents/2025/12/12/2025-22643/safety-standard-for-toys-requirements-for-water-beads | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2025-22827 | Federal Register 2025-22827: Mandatory Toy Safety Standards: Requirements for Neck Floats | https://www.federalregister.gov/documents/2025/12/15/2025-22827/mandatory-toy-safety-standards-requirements-for-neck-floats | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2025-23912 | Federal Register 2025-23912: USTR Notice of Action: China's Acts, Policies, and Practices Related to Targeting of the Semiconductor Industry | https://www.federalregister.gov/documents/2025/12/29/2025-23912/notice-of-action-chinas-acts-policies-and-practices-related-to-targeting-of-the-semiconductor | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-02855 | Federal Register 2026-02855: Safety Standard for Crib Mattresses (direct final rule) | https://www.federalregister.gov/documents/2026/02/12/2026-02855/safety-standard-for-crib-mattresses | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-03824 | Federal Register 2026-03824: Proclamation 11012: Imposing a Temporary Import Surcharge (section 122) | https://www.federalregister.gov/documents/2026/02/25/2026-03824/imposing-a-temporary-import-surcharge-to-address-fundamental-international-payments-problems | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-03829 | Federal Register 2026-03829: Executive Order 14388: Continuing the Suspension of Duty-Free De Minimis Treatment for All Countries | https://www.federalregister.gov/documents/2026/02/25/2026-03829/continuing-the-suspension-of-duty-free-de-minimis-treatment-for-all-countries | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-03832 | Federal Register 2026-03832: Executive Order 14389: Ending Certain Tariff Actions (IEEPA duties) | https://www.federalregister.gov/documents/2026/02/25/2026-03832/ending-certain-tariff-actions | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-06080 | Federal Register 2026-06080: Safety Standard for Portable Hook-On Chairs (direct final rule) | https://www.federalregister.gov/documents/2026/03/30/2026-06080/safety-standard-for-portable-hook-on-chairs | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-06306 | Federal Register 2026-06306: Safety Standard for Gates and Enclosures (direct final rule) | https://www.federalregister.gov/documents/2026/04/01/2026-06306/safety-standard-for-gates-and-enclosures | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-07062 | Federal Register 2026-07062: Modification to the Start of the Submission Period for PFAS Reporting under TSCA 8(a)(7) | https://www.federalregister.gov/documents/2026/04/13/2026-07062/modification-to-the-start-of-the-submission-period-for-perfluoroalkyl-and-polyfluoroalkyl-substances | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-07638 | Federal Register 2026-07638: Safety Standard for Infant and Cradle Swings (direct final rule) | https://www.federalregister.gov/documents/2026/04/20/2026-07638/safety-standard-for-infant-and-cradle-swings | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-08632 | Federal Register 2026-08632: Safety Standard for Full-Size Baby Cribs (direct final rule) | https://www.federalregister.gov/documents/2026/05/04/2026-08632/safety-standard-for-full-size-baby-cribs | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-09640 | Federal Register 2026-09640: Safety Standard for Toddler Beds (direct final rule) | https://www.federalregister.gov/documents/2026/05/14/2026-09640/safety-standard-for-toddler-beds | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-09822 | Federal Register 2026-09822: Promoting the Integrity and Security of TCBs, Measurement Facilities, and the Equipment Authorization Program (2026 order) | https://www.federalregister.gov/documents/2026/05/15/2026-09822/promoting-the-integrity-and-security-of-telecommunications-certification-bodies-measurement | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-09977 | Federal Register 2026-09977: Extension of the Date by Which Neck Floats Must Be Tested and Certified | https://www.federalregister.gov/documents/2026/05/19/2026-09977/extension-of-the-date-by-which-neck-floats-must-be-tested-and-certified-subject-to-the-submission-of | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-11578 | Federal Register 2026-11578: Amending OTC Monograph M020: Sunscreen (bemotrizinol) final order | https://www.federalregister.gov/documents/2026/06/10/2026-11578/amending-over-the-counter-monograph-m020-sunscreen-drug-products-for-over-the-counter-human-use-and | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-12669 | Federal Register 2026-12669: Indefinite Suspension of the De Minimis Exemption for Mail Shipments and New Postal Informal Entry Process (IFR) | https://www.federalregister.gov/documents/2026/06/24/2026-12669/indefinite-suspension-of-the-de-minimis-exemption-for-mail-shipments-and-new-postal-informal-entry | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-12670 | Federal Register 2026-12670: Indefinite Suspension of the De Minimis Exemption for Merchandise Arriving Through All Modes Other Than the International Postal Network (IFR) | https://www.federalregister.gov/documents/2026/06/24/2026-12670/indefinite-suspension-of-the-de-minimis-exemption-for-merchandise-arriving-through-all-modes-other | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-12695 | Federal Register 2026-12695: Determination Regarding Technological Feasibility of Lead Content Reduction | https://www.federalregister.gov/documents/2026/06/24/2026-12695/notice-of-commission-determination-regarding-technological-feasibility-of-lead-content-reduction | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-12749 | Federal Register 2026-12749: Safety Standard for Lithium-Ion Batteries Used in Micromobility Products (NPR) | https://www.federalregister.gov/documents/2026/06/24/2026-12749/safety-standard-for-lithium-ion-batteries-used-in-micromobility-products-and-electrical-systems-of | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-13518 | Federal Register 2026-13518: Prohibiting Importation and Marketing of Previously Authorized Covered Communications Equipment Added to the Covered List in 2024 or Earlier | https://www.federalregister.gov/documents/2026/07/06/2026-13518/prohibiting-importation-and-marketing-of-previously-authorized-covered-communications-equipment | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-15181 | Federal Register 2026-15181: USTR Notice of Actions in Section 301 Investigations (forced labor import prohibitions, 60 economies) | https://www.federalregister.gov/documents/2026/07/28/2026-15181/notice-of-actions-in-section-301-investigations-of-acts-policies-and-practices-of-various-economies | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-15418 | Federal Register 2026-15418: Seeking Comment on Prohibiting the Importation and Marketing of Certain Covered UAS and UAS Critical Components (FY2025 NDAA sec. 1709) | https://www.federalregister.gov/documents/2026/07/30/2026-15418/seeking-comment-on-prohibiting-the-importation-and-marketing-of-certain-covered-uas-and-uas-critical | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-17193 | Federal Register 2026-17193: Comment Sought on Prohibiting the Importation and Marketing of Certain Covered UAS and UAS Critical Components | https://www.federalregister.gov/documents/2026/08/24/2026-17193/comment-sought-on-prohibiting-the-importation-and-marketing-of-certain-covered-uas-and-uas-critical | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-17926 | Federal Register 2026-17926: Heightened Import Disclosures for Supply Chain Visibility (ANPRM) | https://www.federalregister.gov/documents/2026/09/02/2026-17926/heightened-import-disclosures-for-supply-chain-visibility | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-18103 | Federal Register 2026-18103: NOA: Revision to the Voluntary Standard for Products Containing Button Cell or Coin Batteries (UL 4200A) | https://www.federalregister.gov/documents/2026/09/03/2026-18103/notice-of-availability-and-request-for-comment-revision-to-the-voluntary-standard-for-products | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-18380 | Federal Register 2026-18380: FMVSS No. 213a amendments; compliance date delayed to December 5, 2026 | https://www.federalregister.gov/documents/2026/09/09/2026-18380/federal-motor-vehicle-safety-standard-no-213a-child-restraint-systems-side-impact-protection-federal | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-18535 | Federal Register 2026-18535: Protecting Against National Security Threats to the Communications Supply Chain Through the Equipment Authorization Program (FCC ID display in online marketplaces; component loophole) | https://www.federalregister.gov/documents/2026/09/11/2026-18535/protecting-against-national-security-threats-to-the-communications-supply-chain-through-the | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-18551 | Federal Register 2026-18551: Amending OTC Monograph M020: Sunscreen; PABA and Trolamine Salicylate final order | https://www.federalregister.gov/documents/2026/09/11/2026-18551/amending-over-the-counter-monograph-m020-sunscreen-drug-products-for-over-the-counter-human-use-and | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-19065 | Federal Register 2026-19065: Revocation of Obsolete Rules Regarding Infant Bouncer Seats and Stationary Activity Centers (withdrawal) | https://www.federalregister.gov/documents/2026/09/17/2026-19065/revocation-of-obsolete-rules-regarding-infant-bouncer-seats-and-stationary-activity-centers | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-19579 | Federal Register 2026-19579: Substantial Product Hazard List: Amendments to Requirements for Window Covering Cords (proposed) | https://www.federalregister.gov/documents/2026/09/24/2026-19579/substantial-product-hazard-list-amendments-to-requirements-for-window-covering-cords | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-20228 | Federal Register 2026-20228: Court-Ordered Refunds Under the IEEPA Worksheet (information collection) | https://www.federalregister.gov/documents/2026/10/05/2026-20228/agency-information-collection-activities-court-ordered-refunds-under-the-international-emergency | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-20296 | Federal Register 2026-20296: Micromobility Lithium-Ion Battery NPRM: opportunity for oral comments | https://www.federalregister.gov/documents/2026/10/05/2026-20296/safety-standard-for-lithium-ion-batteries-used-in-micromobility-products-and-electrical-systems-of | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-FR-2026-20650 | Federal Register 2026-20650: Low-Value Shipments (proposed rule) | https://www.federalregister.gov/documents/2026/10/08/2026-20650/low-value-shipments | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-HI-SB2621-2020 | Hawaii SB 2621 SD1 (2020) amending HRS 342D-21 (sunscreen with oxybenzone/octinoxate) | https://data.capitol.hawaii.gov/sessions/session2020/bills/SB2621_SD1_.htm | S2 | search_snippet | 2026-10-10 |
| SRC-US-GOV-ME-DEP-PFAS-PRODUCTS | PFAS in Products (Maine DEP) | https://www.maine.gov/dep/spills/topics/pfas/PFAS-products/index.html | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-MN-STAT-116-943 | Minnesota Statutes 116.943 Products containing PFAS (Amara's Law) | https://www.revisor.mn.gov/statutes/cite/116.943 | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-NHTSA-RCL-21E006 | NHTSA recall document 21E-006 (aftermarket LED headlamp bulbs, FMVSS 108 noncompliance) | https://static.nhtsa.gov/odi/rcl/2021/RCONL-21E006-7749.pdf | S2 | search_snippet | 2026-10-10 |
| SRC-US-GOV-NYC-DCWP-LL39 | City Reminds Retailers and Consumers to Only Purchase Certified Lithium-Ion Batteries and Mobility Devices (Local Law 39 of 2023) | https://www.nyc.gov/site/dca/news/044-23/city-reminds-retailers-consumers-only-purchase-certified-lithium-ion-batteries-mobility | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-NYDEC-FOAM-FREE | Expanded Polystyrene Foam Containers and Polystyrene Loose Fill Packaging Ban (NYS DEC) | https://dec.ny.gov/environmental-protection/recycling-composting/nys-plastics-reduction-laws/go-foam-free | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-NYDOS-BODY-ARMOR | Body Armor (eligible professions; Penal Law 270.20–270.22) | https://dos.ny.gov/body-armor | S2 | search_snippet | 2026-10-10 |
| SRC-US-GOV-OEHHA-P65-ART6-2024 | Proposition 65 Article 6 Clear and Reasonable Warnings – final regulation text approved 2024-11-26 (27 CCR 25600 et seq.) | https://oehha.ca.gov/media/downloads/crnr/finalregtext112624approval.pdf | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-PL-119-21 | Public Law 119-21 (One Big Beautiful Bill Act) sec. 70531: modifications to de minimis entry privilege | https://www.govinfo.gov/content/pkg/PLAW-119publ21/html/PLAW-119publ21.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-PL-119-37 | Public Law 119-37 (Nov. 12, 2025), Div. B sec. 781: amended hemp definition (7 U.S.C. 1639o) | https://www.govinfo.gov/content/pkg/PLAW-119publ37/html/PLAW-119publ37.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-SCOTUS-23-852 | Bondi v. VanDerStok, No. 23-852 (U.S. Mar. 26, 2025) | https://www.supremecourt.gov/opinions/24pdf/23-852_o7jp.pdf | S2 | search_snippet | 2026-10-10 |
| SRC-US-GOV-USC-15USC1242 | 15 U.S.C. 1242 Switchblade knives: introduction, manufacture, transportation or distribution in interstate commerce | https://www.govinfo.gov/content/pkg/USCODE-2023-title15/html/USCODE-2023-title15-chap29-sec1242.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-USC-15USC1244 | 15 U.S.C. 1244 Switchblade knives: exceptions | https://www.govinfo.gov/content/pkg/USCODE-2023-title15/html/USCODE-2023-title15-chap29-sec1244.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-USC-15USC1278 | 15 U.S.C. 1278 Requirements for labeling certain toys and games | https://www.govinfo.gov/content/pkg/USCODE-2023-title15/html/USCODE-2023-title15-chap30-sec1278.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-USC-15USC1278A | 15 U.S.C. 1278a Children's products containing lead; lead paint rule | https://www.govinfo.gov/content/pkg/USCODE-2023-title15/html/USCODE-2023-title15-chap30-sec1278a.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-USC-15USC1472A | 15 U.S.C. 1472a Special packaging for liquid nicotine containers | https://www.govinfo.gov/content/pkg/USCODE-2023-title15/html/USCODE-2023-title15-chap39A-sec1472a.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-USC-15USC2056E | 15 U.S.C. 2056e Reese's Law: Button cell or coin batteries | https://www.govinfo.gov/content/pkg/USCODE-2023-title15/html/USCODE-2023-title15-chap47-sec2056e.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-USC-15USC2057D | 15 U.S.C. 2057d Banning of inclined sleepers for infants | https://www.govinfo.gov/content/pkg/USCODE-2023-title15/html/USCODE-2023-title15-chap47-sec2057d.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-USC-15USC2057E | 15 U.S.C. 2057e Banning of crib bumpers | https://www.govinfo.gov/content/pkg/USCODE-2023-title15/html/USCODE-2023-title15-chap47-sec2057e.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-USC-15USC2063 | 15 U.S.C. 2063 Product certification and labeling | https://www.govinfo.gov/content/pkg/USCODE-2023-title15/html/USCODE-2023-title15-chap47-sec2063.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-USC-15USC2064 | 15 U.S.C. 2064 Substantial product hazards (reporting) | https://www.govinfo.gov/content/pkg/USCODE-2023-title15/html/USCODE-2023-title15-chap47-sec2064.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-USC-15USC2068 | 15 U.S.C. 2068 Prohibited acts | https://www.govinfo.gov/content/pkg/USCODE-2023-title15/html/USCODE-2023-title15-chap47-sec2068.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-USC-15USC375 | 15 U.S.C. 375 PACT Act definitions (incl. electronic nicotine delivery system) | https://www.govinfo.gov/content/pkg/USCODE-2023-title15/html/USCODE-2023-title15-chap10A-sec375.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-USC-15USC376A | 15 U.S.C. 376a PACT Act delivery sales (age verification, registration) | https://www.govinfo.gov/content/pkg/USCODE-2023-title15/html/USCODE-2023-title15-chap10A-sec376a.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-USC-16USC1372 | 16 U.S.C. 1372 Marine Mammal Protection Act prohibitions | https://www.govinfo.gov/content/pkg/USCODE-2023-title16/html/USCODE-2023-title16-chap31-subchapII-sec1372.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-USC-18USC1716E | 18 U.S.C. 1716E Tobacco products and ENDS nonmailable | https://www.govinfo.gov/content/pkg/USCODE-2023-title18/html/USCODE-2023-title18-partI-chap83-sec1716E.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-USC-19USC1308 | 19 U.S.C. 1308 Prohibition on importation of dog and cat fur products | https://www.govinfo.gov/content/pkg/USCODE-2023-title19/html/USCODE-2023-title19-chap4-subtitleII-partI-sec1308.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-USC-21USC331 | 21 U.S.C. 331 Prohibited acts (incl. (ll) food with added approved drug; (ddd) rinse-off cosmetics containing plastic microbeads) | https://www.govinfo.gov/content/pkg/USCODE-2023-title21/html/USCODE-2023-title21-chap9-subchapIII-sec331.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-USC-21USC342 | 21 U.S.C. 342 Adulterated food (confectionery with nonnutritive objects) | https://www.govinfo.gov/content/pkg/USCODE-2023-title21/html/USCODE-2023-title21-chap9-subchapIV-sec342.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-USC-21USC360B | 21 U.S.C. 360b New animal drugs | https://www.govinfo.gov/content/pkg/USCODE-2023-title21/html/USCODE-2023-title21-chap9-subchapV-partA-sec360b.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-USC-21USC361 | 21 U.S.C. 361 Adulterated cosmetics (coal-tar hair dye caution) | https://www.govinfo.gov/content/pkg/USCODE-2023-title21/html/USCODE-2023-title21-chap9-subchapVI-sec361.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-USC-21USC364A | 21 U.S.C. 364a Adverse events (cosmetics, MoCRA) | https://www.govinfo.gov/content/pkg/USCODE-2023-title21/html/USCODE-2023-title21-chap9-subchapVI-sec364a.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-USC-21USC364C | 21 U.S.C. 364c Registration and product listing (cosmetics, MoCRA) | https://www.govinfo.gov/content/pkg/USCODE-2023-title21/html/USCODE-2023-title21-chap9-subchapVI-sec364c.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-USC-21USC364E | 21 U.S.C. 364e Labeling (cosmetics, MoCRA) | https://www.govinfo.gov/content/pkg/USCODE-2023-title21/html/USCODE-2023-title21-chap9-subchapVI-sec364e.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-USC-21USC387J | 21 U.S.C. 387j Application for review of certain tobacco products (premarket authorization) | https://www.govinfo.gov/content/pkg/USCODE-2023-title21/html/USCODE-2023-title21-chap9-subchapIX-sec387j.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-USC-21USC863 | 21 U.S.C. 863 Drug paraphernalia | https://www.govinfo.gov/content/pkg/USCODE-2023-title21/html/USCODE-2023-title21-chap13-subchapI-partD-sec863.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-USC-42USC7522 | 42 U.S.C. 7522 Prohibited acts (Clean Air Act section 203; defeat devices) | https://www.govinfo.gov/content/pkg/USCODE-2023-title42/html/USCODE-2023-title42-chap85-subchapII-partA-sec7522.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-USC-47USC302A | 47 U.S.C. 302a Devices which interfere with radio reception | https://www.govinfo.gov/content/pkg/USCODE-2023-title47/html/USCODE-2023-title47-chap5-subchapIII-partI-sec302a.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-USC-47USC333 | 47 U.S.C. 333 Willful or malicious interference | https://www.govinfo.gov/content/pkg/USCODE-2023-title47/html/USCODE-2023-title47-chap5-subchapIII-partI-sec333.htm | S2 | webfetch | 2026-10-10 |
| SRC-US-GOV-WA-ECOLOGY-EPS | Expanded polystyrene (EPS) ban (Washington Ecology) | https://ecology.wa.gov/epsban | S2 | search_snippet | 2026-10-10 |
| SRC-US-S3-BCLP-P65-SHORTFORM | Prop 65 Short-Form Warnings Are About to Get Longer | https://www.bclplaw.com/en-US/events-insights-news/prop-65-short-form-warnings-are-about-to-get-longer.html | S3 | search_snippet | 2026-10-10 |
| SRC-US-S3-BDLAW-MN-PFAS-2026 | Minnesota Extends PFAS in Products Reporting Deadline to September 15, 2026 | https://www.bdlaw.com/publications/minnesota-extends-pfas-in-products-reporting-deadline-to-september-15-2026/ | S3 | search_snippet | 2026-10-10 |
| SRC-US-S3-CRS-IF13136 | CRS In Focus IF13136: Changes to the Statutory Definition of Hemp and Issues for Congress (May 2026, mirror) | https://www.everycrsreport.com/files/2026-05-28_IF13136_e25fb2e82448ad460a067afe1f8d55e15bc61fa5.html | S3 | webfetch | 2026-10-10 |
| SRC-US-S3-LEGISCAN-CA-AB44 | California AB 44 (2019) fur products – chaptered text (LegiScan) | https://legiscan.com/CA/text/AB44/2019 | S3 | search_snippet | 2026-10-10 |
| SRC-US-S3-MORGANLEWIS-PFAS-TEXTILES-2025 | New York and California Bans on PFAS in Textiles and Apparel Begin January 1, 2025 | https://www.morganlewis.com/pubs/2024/11/new-york-and-california-bans-on-pfas-in-textiles-and-apparel-begin-january-1-2025 | S3 | search_snippet | 2026-10-10 |
| SRC-US-S3-MORGANLEWIS-SB343-2026 | Federal Court Blocks Enforcement of California Truth in Recycling Law (SB 343) | https://www.morganlewis.com/pubs/2026/07/federal-court-blocks-enforcement-of-california-truth-in-recycling-law | S3 | search_snippet | 2026-10-10 |
| SRC-US-S3-SGS-CA-SB1271 | SGS SafeGuardS 164/24: California passes bill legislating electric bicycle batteries | https://www.sgs.com/en/news/2024/11/safeguards-16424-us-california-state-passes-bill-legislating-electric-bicycle | S3 | search_snippet | 2026-10-10 |
| SRC-US-S3-SGS-REESES-LAW-2024 | SGS SafeGuardS 33/24: CPSC Reminds Interested Parties About Reese's Law Implementation Dates | https://www.sgs.com/en/news/2024/02/safeguards-3324-cpsc-reminds-interested-parties-about-reeses-law-implementation-dates | S3 | search_snippet | 2026-10-10 |
| SRC-US-S3-SHEPPARD-CA-TFCA | California's Toxic-Free Cosmetics Act Bans 24 Ingredients from Cosmetic Products | https://www.sheppard.com/insights/blogs/californias-toxic-free-cosmetics-act-bans-24-ingredients-from-cosmetic-products | S3 | search_snippet | 2026-10-10 |
| SRC-US-S3-WCMA-V-CPSC-2023 | Window Covering Manufacturers Association v. CPSC, No. 22-1300 (D.C. Cir. 2023) | https://law.justia.com/cases/federal/appellate-courts/cadc/22-1300/22-1300-2023-09-12.html | S3 | search_snippet | 2026-10-10 |

### 待核实/冲突

1. **IEEPA 关税的司法结论与退税**：EO 14389（2026-02-20）已终止 IEEPA 关税，CBP 在办理「法院命令的 IEEPA 退税」，但本次未打开最高法院/国际贸易法院判决原文；122 条款 10% 附加税 150 天到期后是否被国会延长也未见官方文件 [R:US-L6-TARIFF-001]。
2. **对华关税叠加**：原 301 清单（1–4A）税率、2024 四年审查提税项、232 条款衍生品清单与 2026-07-24 起的 12.5% 强迫劳动 301 关税的叠加关系与豁免清单，须按 HTS 逐项核对 [R:US-L6-TARIFF-001]。
3. **FCC 外国对手国家实验室**：FCC 25-27 中扩展到「位于外国对手国家的实验室」的条款被无限期推迟；在中国的实验室能否继续出具 FCC 报告须逐家核实 [R:US-L5-FCC-007]。
4. **无人机**：Covered List 中「UAS 关键部件」的范围、微型玩具无人机是否被覆盖、已授权大疆等机型何时可能被禁止进口营销，需跟踪 FCC 公告 [R:US-L5-FCC-006]。
5. **Covered List 白牌产品**：EZVIZ、HiLook、Lorex、Amcrest 等品牌与清单实体的关系，以及「兼容」配件是否受限，需按具体产品核实 [R:US-L5-FCC-005]。
6. **CPSC 定制窗饰**：16 CFR 1260 已被法院撤销但仍见于 eCFR；2026-09-24 SPH 拟议规则的最终结果待定 [R:US-L5-WINDOW-001]。
7. **CPSC 微出行锂电池最终规则**（拟设 16 CFR 1265）时间表未知 [R:US-L5-MICRO-001]。
8. **DOE 能效标准撤销**：电池充电器、外部电源标准撤销与空气净化器覆盖撤回均为 2025-05 拟议，截至调研日未见最终规则；需持续核查 [R:US-L5-DOE-001] [R:US-L5-DOE-002]。
9. **TSCA PFAS 报告**：EPA 2025-11 拟议对物品进口商等的豁免是否定稿，直接决定跨境卖家是否需要申报 [R:US-L5-TSCA-002]。
10. **MoCRA 配套规则**：化妆品 GMP 与香料过敏原标签规则法定期限已过但未发布；滑石粉石棉检测规则已撤回待重提 [R:US-L5-COSM-006]。
11. **Hemp 新定义**：国会有推迟两年或修改的提案（H.R. 7024、H.R. 7010、S. 3686、H.R. 7567 等，二手来源 CRS），2026-11-12 生效前须复核；FDA 的「类 THC 大麻素」清单截至 2026-05 未公布 [R:US-L5-HEMP-002]。
12. **加州法规原文**：leginfo、OEHHA、CARB、CEC 网站对本次抓取工具拒绝访问，Prop 65 以外的加州条目（CARB 空气净化器/EO/VOC/SORE、Title 20、SB 1019/AB 2998 阻燃剂、AB 44 毛皮、AB 2762 化妆品、SB 1271 电动自行车、AB 1817/AB 2771/AB 652 PFAS）多为政府页面搜索摘要或二手来源，规则标为 unverified/secondary_only，需人工打开原文复核 [R:US-L5-CARB-001] [R:US-L5-CARB-002] [R:US-L5-CARB-003] [R:US-L5-CARB-004] [R:US-L5-CAT20-001] [R:US-L5-STATE-007] [R:US-L5-STATE-002] [R:US-L5-STATE-006]。
13. **加州 BHGS 许可与 law label**：软包家具/床品生产商、进口商须持加州许可证并加法定标签的要求本次未能核实 [R:US-L5-STATE-007]。
14. **明尼苏达 PFAS 申报**：2026-09-15 截止日是否再延期、跨境卖家是否属「制造商」须向 MPCA 核实 [R:US-L5-PFAS-005]。
15. **其他州 PFAS**：科罗拉多、佛蒙特、康涅狄格、华盛顿、新墨西哥、伊利诺伊、马里兰、罗得岛等州的产品类别与日期未逐一核实 [R:US-L5-PFAS-001] [R:US-L5-PFAS-004]。
16. **SB 343 与包装 EPR**：初步禁令后续（上诉、本案判决）及各州 EPR 对跨境卖家的「生产者」认定 [R:US-L5-PKG-002]。
17. **州刀具/防身/武器法**：辣椒喷雾、电击器、指虎、蝴蝶刀、大容量弹匣、防弹衣在各州的具体限制需逐州建表；纽约辣椒喷雾规定仅有二手来源 [R:US-L5-STATE-005]。
18. **调味电子烟与 PMTA 目录州法**：州清单变化快，本次只核到加州（搜索摘要）[R:US-L5-STATE-003]。
19. **成人用品州法**：阿拉巴马等州限制销售性玩具的法律现状未核实（搜索预算用尽）。
20. **汽车 LED 大灯**：NHTSA 对 LED 替换卤素灯泡的正式解释立场未打开原文，仅有召回文件摘要 [R:US-L5-NHTSA-002]。
21. **ATF**：强制复位扳机（FRT）2025 年和解后的地位、撞火枪托在 Cargill 案后的联邦地位、溶剂收集器的执法口径未核实 [R:US-L5-ATF-002]。
22. **蝴蝶刀练习刀**：无刃 trainer 是否落入 19 CFR 12.95 定义需查 CBP 裁定 [R:US-L6-KNIFE-001]。
23. **FDA 进口细节**：FDA 2877 表的电子提交方式、DMAA 等补充剂禁用成分依据、魔芋果冻进口警示均未打开原页 [R:US-L6-FDAIMP-002] [R:US-L5-SUPP-003]。
24. **EPA 篡改件执法政策**：2025 年起关于淡化（尤其刑事）执法的报道未找到 EPA 原文 [R:US-L5-CAA-001]。
25. **鲨鱼鳍销售禁令**：2022 年《鲨鱼鳍销售消除法》的法典位置与生效日未打开原文 [R:US-L6-FWS-002]。
26. **APHIS 种子**：「小批量种子」许可的现行条件与网购种子的具体处理，本次只核到 7 CFR 319.37 的一般要求 [R:US-L6-APHIS-002]。
27. **ASTM F2057-23 适用阈值**（高度/重量/容积）未打开标准原文，规则中以「以标准为准」表述 [R:US-L5-STURDY-001]。
28. **调研限制**：本次未能使用并行子代理，网页搜索额度在后段用尽，r.jina.ai 渲染服务被限流；eCFR/Federal Register/govinfo 均通过官方 API 直接核对。
