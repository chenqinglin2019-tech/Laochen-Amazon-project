# 沙特站（amazon.sa）禁限售与合规要求

> 规则包版本：draft · 调研日期：2026-10-10 · 本文描述亚马逊平台政策和当地法规要求，不构成法律意见。
> 每条结论后用 [SRC-…] 标注来源（见 rules/sources/SA.yaml、GCC.yaml、AE.yaml），用 [R:规则ID] 关联机读规则（rules/sites/GCC.yaml、SA.yaml）。
> 来源级别：S1 亚马逊官方 · S2 政府官方 · S3 二手。只有 S3 支撑的结论标注「（二手来源，待核）」。
> 沙特站与阿联酋站共用的平台规则写在 GCC.yaml（`sites: [AE, SA]`）。两站受限商品页大部分逐字相同（已逐页比对），本文完整列出并注明沙特站的差异；阿联酋站情况见 policy/AE.md。

**先读这 7 条（对中国卖家影响最大）**
1. 沙特站禁售**所有**电子烟（不论是否含尼古丁）、水烟壶及配件、各类烟斗、电子香薰笔、草本香烟——比阿联酋站严格得多 [R:SA-L1-TOBACCO-001] [R:SA-L1-TOBACCO-002] [SRC-SA-AMZ-G201744070]。
2. 所有商品（SFDA 监管品除外）须符合《产品安全法》：能提供 PCoC（或 IECEE RC、SQM、G-Mark 等替代证书），标签和 Listing 须有阿拉伯语的制造商/沙特进口商信息与安全警示 [R:SA-L3-PSL-001] [R:SA-L5-PSL-001] [SRC-SA-AMZ-G7BF8EFS2VHV3ZH3]。
3. 2025-10-01 起，所有进口商品报关前须在 SABER 取得每批货运证书（SC）；2026 年 9 月起 SC 有效期由 60 天延至 90 天 [R:SA-L5-SABER-001] [SRC-SA-GOV-SASO-SC-BEFORE-DECL-2025] [SRC-SA-GOV-SASO-SC-90D]。
4. 2026-10-01 起，电动平衡车、婴儿推车/儿童座椅、小型光伏等 10 项法规产品须在产品本体标注沙特供应商名称和商业登记号（二手来源，待核）[R:SA-L5-CRLABEL-001]。
5. USB-C：手机、平板、耳机等 2025-01-01 起；8 类（相机、键鼠、音箱、路由器等）宽限至 2026-05-01；笔记本 2026-04-01 起 [R:SA-L5-USBC-001] [SRC-SA-GOV-CST-USBC-2024]。
6. 健康类（GSL 药、补充剂、医疗器械、隐形眼镜、公共卫生杀虫剂）要求沙特商业登记 + Balady 市政执照 + SFDA 执照/产品注册，跨境卖家基本无法满足 [R:SA-L2-MEDICINE-001] [R:SA-L2-SUPPL-001] [R:SA-L2-MEDDEV-001] [R:SA-L2-OPTICAL-001] [R:SA-L2-PESTICIDE-001]。
7. 与阿联酋站相同：圆柱形 ≥3.0V 可充电锂电池及内含产品禁售；FBA 只接受单电芯 ≤20 Wh、电池组 ≤100 Wh；不支持 220V 的电器禁售 [R:GCC-L1-SAFETY-001] [R:GCC-L4-LIION-001] [R:GCC-L1-ELEC-002]。

---

## A. 禁售清单（L1）

| 类别 | 亚马逊页面（G 编号） | 禁止销售的典型商品 | 例外/允许销售的情况 | 规则ID |
|---|---|---|---|---|
| 动物及动物制品 | G201743950 | CITES 所列物种；真皮草；尖刺/电击项圈、粘鼠板、捕猫器、斗鸡刀、虐待动物内容；海豹、猫狗、濒危物种（象牙、鳄鱼、蛇皮、珊瑚、海龟壳）、鲨鱼鲸海豚、未鞣制生皮 [SRC-SA-AMZ-G201743950] | 合规非濒危动物食品；电子灭鼠器 | SA-L1-ANIMAL-001、GCC-L1-ANIMAL-001、GCC-L1-ANIMAL-002、GCC-L1-ANIMAL-003 |
| 汽车摩托 | G201743960 | 整车；二手配件；安全气囊及气体发生器；安全带及组件；翻新轮胎；缺认证的车用电器配件 [SRC-SA-AMZ-G201743960] | 新电瓶、头盔、反光背心、三角牌、轮胎、配件、机油、油桶 | GCC-L1-AUTO-001 |
| 货币、礼品卡 | G201743970 | 礼品卡/储值码、比特币、汇票、金银条、证券、可在沙特以外流通的外币；伪钞伪邮票及设备 [SRC-SA-AMZ-G201743970] | 非流通收藏币（披露信息）、标明的复制品 | GCC-L1-CURRENCY-001、GCC-L1-CURRENCY-002 |
| 化妆品 | G201743980 | 开封/过期/非原厂密封/去码/试用装；专业或处方级（牙齿美白 >0.1% H2O2）；禁用成分；蛇油；非纯天然指甲花 [SRC-SA-AMZ-G201743980] | 原厂密封、标签合规的美妆（须类目审核，SFDA 列名） | GCC-L1-COSMETIC-001、GCC-L1-COSMETIC-002 |
| 药品 | G201743990、GF77H4GPLRVCNBWT | 处方药、须药剂师销售的药、未许可药、兽用处方药与疫苗；**非“一般销售”类药品**；带药用宣称的草本补充剂和草本茶包 [SRC-SA-AMZ-G201743990] [SRC-SA-AMZ-GF77H4GPLRVCNBWT] | 持证卖家可售一般销售药品（GSL）（与阿联酋站不同：沙特站受限页未把 OTC 列为禁售） | GCC-L1-DRUG-001、SA-L1-MEDICINE-001、SA-L2-MEDICINE-001 |
| 毒品与“合法兴奋剂” | G201743990 | 非法药物、合成大麻、legal highs、麻黄碱、GBL、GHB、DNP、Poppers、合成尿液 | — | GCC-L1-DRUG-002 |
| 补充剂（掺假/特定成分） | G201743990 | 掺假减肥/健身/性功能补充剂及品牌清单；鹿茸、甲状腺提取物、鲨鱼软骨；WADA 禁用物质、生长激素、HCG；治癌、解酒宣称；烟酸/烟酰胺超量 | 合规补充剂（须执照与 SFDA 注册） | GCC-L1-SUPPL-001、GCC-L1-HEALTH-001 |
| 吸毒用具与烟具 | G201743990 | bong、vaporizer、美化毒品商品；**烟斗、Dokha 烟斗、水烟、shisha、雪茄剪**（沙特站列为“烟草相关禁售品”）[SRC-SA-AMZ-G201743990] | 打火机、烟灰缸、卷烟纸、烟盒 | GCC-L1-PARAPH-001、SA-L1-TOBACCO-002 |
| 食品饮料 | G201744000 | 含猪源成分；**含酒精食品**；**青蛙肉**；鹅肝；鲨鱼鲸肉；含毒品糖果；Kava、膨润土、迷你果冻杯、**肉豆蔻**、疯蜂蜜；未注册新资源食品；过期/非零售；健康宣称 [SRC-SA-AMZ-G201744000] | 合规食品（须审核，阿语标签，仅英文标签须监管部门书面批准） | GCC-L1-FOOD-001、GCC-L1-FOOD-002、GCC-L1-FOOD-003、SA-L1-FOOD-001 |
| 电子 | G201744010 | 干扰器、雷达探测器、交通信号操控、里程表篡改、解码破解、手机解锁、智能卡编程器、AdBlue 模拟器、刷卡终端；偷拍设备；侵权流媒体；不支持 220V；游戏模拟器与破解芯片；Kindle 电池；合约机；**带摄像头手表、带投放器/激光/25 kg 以上无人机、按摩棒** [SRC-SA-AMZ-G201744010] | 杀毒软件、安防摄像头、导航、蓝牙设备、报警器、婴儿监视器、智能手表（无摄像头） | GCC-L1-ELEC-001、GCC-L1-ELEC-002、GCC-L1-ELEC-003、GCC-L1-ELEC-004、SA-L1-ELEC-001 |
| 激光、监控 | G201689020、G200164870 | Class 2 及以上激光、激光舞台灯；隐藏摄像头、窃听器、GPS 追踪器、夜视镜、键盘记录器 [SRC-SA-AMZ-G200164330] | Class 1/1C/1M 激光（口径冲突，见待核实） | GCC-L1-LASER-001、GCC-L1-SURVEIL-001 |
| 医疗器械 | G201744020 | 二手器械；需处方/专业监督器械；助听器、处方眼镜、针头、带针注射器、IUD、性病自测等 [SRC-SA-AMZ-G201744020] | 隐形眼镜、太阳镜、验孕排卵试纸、避孕套、血压计袖带、尼古丁贴、**润滑剂**（须审核与执照） | GCC-L1-MEDDEV-001 |
| 珠宝 | G201744030 | 无合规戳记的纯贵金属/宝石；**贵金属金条**；未经检定衡器称重；非金伯利毛坯钻 [SRC-SA-AMZ-G201744030] | 一般首饰 | GCC-L1-JEWEL-001 |
| 其他商品 | G201744040 | 同阿联酋站（广告 Listing、账号、域名、福袋、服务、数字码、盗版软件、文物、铅坠、笑气弹、农药毒药、植物种子等），另加**宗教圣像、面具、万圣节服装、渗渗泉水** [SRC-SA-AMZ-G201744040] | — | GCC-L1-OTHER-001、GCC-L1-OTHER-002、GCC-L1-OTHER-003、GCC-L1-PESTICIDE-001、GCC-L1-PLANTS-001、SA-L1-OTHER-001 |
| 两性用品 | G201744060 | 色情、裸露、成人游戏、情趣玩具、**情趣新奇用品、紧致/延时/增强凝胶、按摩棒、情趣服装**、性增强品 [SRC-SA-AMZ-G201744060] | 原包装避孕套、润滑剂、按摩油 | GCC-L1-ADULT-001、SA-L1-ELEC-001 |
| 烟草 | G201744070 | 一切烟草；**所有电子烟及烟弹烟油（不论尼古丁）**、vape、电子水烟、bakhoor 电子香薰笔；水烟及配件；各类烟斗；新奇打火机；尼古丁口香糖；**草本香烟** [SRC-SA-AMZ-G201744070] | 烟灰缸、雪茄剪（与药品页冲突）、保湿盒、卷烟纸、卷烟机 | GCC-L1-TOBACCO-001、SA-L1-TOBACCO-001、SA-L1-TOBACCO-002 |
| 武器 | G201744080 | 同阿联酋站（枪械气枪仿真枪、弓弩、电击器、胡椒喷雾、警棍指虎、各类刀具、爆炸物），另列**潜水刀** [SRC-SA-AMZ-G201744080] | 留色防身喷雾、非逼真玩具枪、瑞士军刀、剪刀、成套餐刀等 | GCC-L1-WEAPON-001、GCC-L1-WEAPON-002、GCC-L1-WEAPON-003、GCC-L1-WEAPON-004 |
| 酒类 | G201744410 | 酒精饮料、含酒精食品（含液体甜味剂）、酒类许可证、酿酒套件、**发酵套件、酒类品牌周边（T 恤、海报、打火机）** [SRC-SA-AMZ-G201744410] | 化妆品级酒精产品、消毒湿巾、镜头清洁剂 | GCC-L1-ALCOHOL-001、SA-L1-ALCOHOL-001 |
| 赌博彩票 | G201744450 | 21 点桌、刮刮卡、彩票、老虎机（含不能运行的）、筹码、轮盘、塔罗牌 [SRC-SA-AMZ-G201744450] | 扑克牌、骰子、洗牌机 | GCC-L1-GAMBLING-001 |
| 服装 | G201744470 | 印裸露/毒品/冒犯内容；二手服装鞋；猪皮及受保护动物皮革 [SRC-SA-AMZ-G201744470] | 服装、鞋、包 | GCC-L1-ANIMAL-001、GCC-L1-ANIMAL-003、GCC-L1-OFFENSIVE-001 |
| 视频游戏 | G9NQF8P6KC9D4KNC | 国际版或非 GAMR 批准版本；盗版 [SRC-SA-AMZ-G9NQF8P6KC9D4KNC] | GAMR 批准版本（须执照与分级标识） | SA-L1-VIDEOGAME-001、SA-L2-VIDEOGAME-001 |
| 杀虫剂 | G6E2SRU9QL3E3CG5 | 未注册、限制使用、仅限专业的农药；误导性“安全无毒”宣称 [SRC-SA-AMZ-G6E2SRU9QL3E3CG5] | 仅家用农药（须 SFDA 注册） | GCC-L1-PESTICIDE-001、SA-L2-PESTICIDE-001 |
| 危险品、人体部位、冒犯内容、开锁、艺术品、邮票、保修 | G200164570 等（主页链接与阿联酋站相同的子页） | 见 policy/AE.md A 节同名行 | — | GCC-L1-HAZMAT-001、GCC-L1-HAZMAT-002、GCC-L1-HAZMAT-003、GCC-L1-HAZMAT-004、GCC-L1-HAZMAT-005、GCC-L1-HUMAN-001、GCC-L1-OFFENSIVE-001、GCC-L1-LOCKPICK-001、GCC-L1-ART-001 |
| 产品安全 Listing 限制 | GRLKLZ6WQ9R259LC（内容与阿联酋站一致） | 圆柱形可充电锂电池；斗风筝线、出牙首饰、颈圈泳圈、抽绳童装、床围、婴幼儿类目指尖陀螺、飞镖陀螺、自主喂食器、睡眠定位器、美人鱼尾泳衣、蘑菇牙胶、牙签弩、吸水珠、加重睡眠用品；承重位电池加热衣物鞋垫、汽车座椅加热垫、布质儿童座椅、通用 CO 报警器、烟雾探测器、奶油发泡器、气囊安全带；凝胶燃料火盆、叠氮化钠、三氯乙酸、角磨机链锯盘；疯蜂蜜 [SRC-SA-AMZ-GRLKLZ6WQ9R259LC] | — | GCC-L1-SAFETY-001、GCC-L1-SAFETY-002、GCC-L1-SAFETY-003、GCC-L1-SAFETY-004 |
| 照明（Lighting）、SIM 卡 | G201997070、GYCN5C8V4KBMD6X6 | 照明页抓取结果只有标题无正文；SIM 卡沙特版未抓取 | — | 待核实 |

## B. 审核与限售（L2）

**通用流程**同阿联酋站：添加商品 → “Apply to sell”；材料为 180 天内发票、各面图片、品牌授权、安全证书；2–7 个工作日；2024-09-30 起合规文件须先获批 [R:GCC-L2-APPROVAL-001] [SRC-SA-AMZ-G200333160]。

**沙特站健康类资质**：提交至 mea-healthcare-compliance-accounts@amazon.sa（卖家执照）和 mea-healthcare-compliance-products@amazon.sa（产品注册证）。所有健康类都要求沙特商业登记（含指定 ISIC 活动代码）和 Balady 市政商业执照。

| 需审核的类目/商品 | 要求 | 申请/提交路径 | 规则ID |
|---|---|---|---|
| 美妆个护 | 类目审核；SFDA GHAD 列名 | 添加商品 > 申请销售 | GCC-L2-BEAUTY-001、SA-L5-COSMETIC-001 |
| 食品饮料 | 类目审核；阿语或阿英双语标签（仅英文须监管批准）[SRC-SA-AMZ-G201744000] | 同上 | GCC-L2-GROCERY-001 |
| 医疗器械类目 | 类目审核 | 同上 | GCC-L2-MEDDEV-001 |
| 流媒体播放器 | 寄样 + 软件清单 + 申请表 [SRC-SA-AMZ-G202183590] | 搜索 ASIN > Request approval | GCC-L2-SMP-001 |
| 一般销售药品（GSL） | SFDA 药品机构执照或 MOH 药房执照或 CR（461041、464951、521025、477250、477223、477211 等）+ Balady（827757、1629、1709、861757、1712、860919、1708）；符合 MOH 附件 20；仅满足储存条件的药房和食品零售店可售 [SRC-SA-AMZ-GF77H4GPLRVCNBWT] | 邮件提交 | SA-L2-MEDICINE-001 |
| 膳食补充剂 | 上述执照（另可用 471131 迷你超市、471132 杂货店等代码）+ Balady + 每个产品 SFDA 注册证（产品/药品/草本/健康产品）[SRC-SA-AMZ-GNHUT67GAR39XJ9D] | 邮件提交 | SA-L2-SUPPL-001 |
| 医疗器械与耗材 | CR（521023、464956、477221、477222、477224 等）+ Balady；器械另需 SFDA MDEL + 每个产品 MDMA；耗材需 MDEL 或药品机构执照 [SRC-SA-AMZ-GANZMW59X43K46C3] | 邮件提交 | SA-L2-MEDDEV-001 |
| 处方眼镜、隐形眼镜（含美瞳）、护理液 | SFDA MDEL 或 MOH 私立医疗机构执照或 CR（464971、477321）+ Balady（852846、1717）[SRC-SA-AMZ-GAMA3EHSBQLETA84] | 邮件提交 | SA-L2-OPTICAL-001 |
| 公共卫生杀虫剂/驱避剂 | CR（466922、466923、477354、466926、477358）+ Balady（862081、861958）+ 每个产品 SFDA PNR 证书 [SRC-SA-AMZ-GWVV3PMKJ28ULL9S] | 邮件提交 | SA-L2-PESTICIDE-001 |
| 电子游戏 | CR 含 474151/474120；GAMR 无异议函或零售执照；GAMR 年龄分级标识（3/7/12/16/18/待分级）[SRC-SA-AMZ-G9NQF8P6KC9D4KNC] | GAMR 电子服务 | SA-L2-VIDEOGAME-001 |
| 笔记本电脑（2026-03-05 起全部） | 授权分销商发票（近 6 个月 ≥10 台）；升级版标题含“Upgraded”、固定五点、保修说明 [SRC-SA-AMZ-GHHSFDR8QJKL3J67] | 提交支持文件 | SA-L2-LAPTOP-001 |

## C. 按品类的平台合规资料（L3）

沙特站合规参考列表与阿联酋站相同（少了阿联酋独有的洗涤剂、食品接触材料、瓶装水三页，多了“KSA 产品安全法”页）[SRC-SA-AMZ-G2JX2MAWJ27DWAY6]。已逐页核对的沙特版（玩具、锂电池、圆柱电池、产品安全限制、流媒体）内容与阿联酋版一致，仅把“ECAS”换成“SASO 签发的 CoC”。

| 产品族 | 亚马逊要求的文件 / Listing 属性 | 提交位置 | 规则ID |
|---|---|---|---|
| 所有商品（SFDA 监管品除外） | PCoC 或替代证书（CST 批准、SASO IECEE RC、IECEx RC、SQM、G-Mark、SFDA 注册确认、用水效率标签）；制造商与沙特进口商名称/地址/邮箱（阿语）；阿语安全警示与说明书（PDF 直链或 PS01–PS06 图片）；“KSA PSL 安全声明/符合性声明”属性 [SRC-SA-AMZ-G7BF8EFS2VHV3ZH3] | 管理库存 > 编辑 Listing > Safety & Compliance / Compliance media | SA-L3-PSL-001 |
| 儿童玩具 | GSO EN 71 / ASTM F963-23 / EN 71（电动加 IEC 62115）报告（SASO/EIAC/GAC/ILAC 实验室）；型号、品牌、警示、最小年龄；G-Mark 图片 [SRC-SA-AMZ-GKJRA3FRPRKVBJJS] | 提交合规信息或申诉 | GCC-L3-TOYS-001 |
| 婴童用品 | 对应 ASTM/EN/GSO 标准 PASS 报告与图片 | 同上 | GCC-L3-INFANT-001 |
| 锂电池 | SASO CoC 或 ISO 17025 的 IEC 62133-2/62619 报告 + UN38.3 + BTS；阿英说明书 [SRC-SA-AMZ-G7PAP6BJAUXRM4LH] | 同上 | GCC-L3-LIBATT-001 |
| 电池与充电器 | DoC / 实验室报告 / GCC-GSO-SASO-PCoC 证书；CE/SQM/G-Mark 图片 | 同上 | GCC-L3-CHARGER-001 |
| 移动电源、储能电站、启动电源 | UL 2056/UL 2743 或 IEC 62368-1 + 62133-2 + UN38.3 | 同上 | GCC-L3-POWERBANK-001 |
| 锂电池家电 | IEC 60335-1 + Part 2；电池 62133-2 + UN38.3 + BTS | 同上 | GCC-L3-LIAPPLIANCE-001 |
| 电动出行设备及配件 | EN 15194/UL 2849/EN 17128/UL 2272 + UN38.3 + BTS；阿英说明书 | 同上 | GCC-L3-EMOBILITY-001 |
| 含沙儿童产品、日食眼镜、逃生面罩 | ISO 22262-1 / ISO 12312-2 / ASTM E2952 或 EN 403 | 同上 | GCC-L3-MISC-001 |
| 亚马逊设备兼容配件 | 不得用亚马逊商标命名 | — | GCC-L3-DEVACC-001 |
| 儿童座椅、灯串、报警器、灭火器 | 沙特站列出同名页面，沙特版内容未抓取；阿联酋版要求 ECAS/民防局证书，沙特版应为 SASO/SABER 证书（推定） | 同上 | 待核实（参见 AE-L3-CARSEAT-001 等） |

## D. FBA 与危险品（L4）

与阿联酋站相同（两站 FBA 页面逐条一致，仅法律名称换成沙特《麻醉品法》，且沙特站无“FBA 出口”额外排除）[R:GCC-L4-FBA-001] [SRC-SA-AMZ-G201730840] [SRC-SA-AMZ-G200140860]：

| 情形 | 处理 |
|---|---|
| 长 >150 cm、重 >30 kg、周长 >3 m；酒精饮料（含无醇啤酒）；车辆轮胎；礼品卡；预贴价/营销材料；未预处理；散装电池；破损；标签不符；仿冒；在沙特不能合法销售的商品 | FBA 禁运 |
| 第 1 类、2.3、4.2、4.3、6.2、第 7 类，>1 L 压缩气体，自充气救生器材，>300 Wh 锂电池，>30 kg 受管制危险品 | FBA 禁止 [R:GCC-L4-DG-001] |
| 气雾、香水、指甲油、油漆、氧化剂、腐蚀品、锂电池、磁性材料 | 有限数量陆运；提交 SDS/豁免表 [R:GCC-L4-DG-002] [R:GCC-L4-DG-003] |
| 锂电池 | 中东：单电芯 ≤20 Wh、电池组 ≤100 Wh；UN38.3 测试摘要；SoC 申报 [R:GCC-L4-LIION-001] |

## E. 当地法规（L5，按产品族）

**总体框架**
- **SABER 合格评定**：受技术法规管辖产品须 SASO 认可合格评定机构签发的 PCoC；所有进口商品（含非受监管产品的自我声明）报关前须每批取得 SC（2025-10-01 起），SC 有效期 90 天（2026-09 起）；SABER 与 FASAH 海关系统对接；SABER 账户须为持沙特商业登记的进口商 [R:SA-L5-SABER-001] [SRC-SA-GOV-SASO-SC-BEFORE-DECL-2025] [SRC-SA-GOV-SASO-SC-90D]。PCoC 1 年有效、SC 每批约 350 里亚尔、风险分级等细节为二手来源，待核 [SRC-SA-S3-HQTS-SABER-GUIDE]。
- **《产品安全法》**（王室法令 M/36，实施细则 2024-11-22 公布）：阿语安全信息；进口商名称地址标在产品上；网店 72 小时处理不安全产品报告；制造商在境外时网店/分销商视为制造商；罚款最高 500 万里亚尔（重犯 1,000 万）[R:SA-L5-PSL-001] [SRC-SA-GOV-SASO-PSL]。
- **SFDA** 监管食品、化妆品、药品、医疗器械、补充剂、农药、烟草，不走 SABER；SFDA 电商规则要求产品已注册/列名、广告素材预先获批 [R:SA-L5-SFDAECOM-001] [SRC-SA-GOV-SFDA-ECOM-STORES]。

### 电子电器
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 海湾低压电气技术法规 BD-142004-01（2016-07-01，清单 2 的 13 类家电须 G-Mark）；RoHS 技术法规（2022-01-05）；电磁兼容（2023-11-17 公布）；待机能耗（2023-05-19 公布） | CB 报告（含沙特国家差异，插头 SASO 2203）、RoHS、EMC | SABER PCoC；G-Mark 须与沙特供应商 CR 在 GCTS 关联（二手来源，待核）；IECEE RC（19 类） | 阿语说明书与安全信息 | SASO / GSO | GCC-L5-LVE-001、SA-L5-ROHS-001、SA-L5-ELEC-001、SA-L5-IECEE-001、GCC-L1-ELEC-002 |
| 能效通用技术法规（附件 1 的 13 类：空调、冰箱、洗衣机、干衣机、热水器、洗碗机、照明三部分、电机、轮胎等） | 能效测试 | SASO 能效卡（按型号，1 年） | 产品与包装均贴能效标签；无标签不得广告 | SASO | SA-L5-EE-001 |
| 沙特质量标志（SQM）：电气连接产品 2020-08-07 起强制（二手来源，待核） | — | SQM 许可 | SQM 标志 | SASO | SA-L5-QMARK-001 |

### 电池
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 电池技术法规（2019-06-21 强制，锂电池是否在范围内未核实）；移动电源与手机电池属 IECEE RC 清单 | IEC 62133-2、UN38.3、CB 报告 | SABER PCoC + IECEE RC | 阿语说明 | SASO | SA-L5-ELEC-001、SA-L5-IECEE-001、GCC-L3-LIBATT-001、GCC-L3-POWERBANK-001、GCC-L1-SAFETY-001 |

### 无线设备
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 《通信与信息技术设备技术法规》（2024-08-16 公布，约 2025-02-12 适用，已在市场产品整改至约 2025-08-16）；USB-C 统一接口（附件 2） | RF/EMC 测试；USB-C/PD 按 SASO IEC 62680-1-2/-1-3 | SABER PCoC（1a 型，原 CST 平台审批已迁入 SABER——二手来源）；手机、手表、电脑等另需 IECEE RC | 阿语标签：频段、最大功率、原产国、警示；CST 合格标识；USB-C 充电器图示与功率 | CST / SASO | SA-L5-ICT-001、SA-L5-USBC-001、SA-L5-IECEE-001 |

### 灯具
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 照明能效（SASO 2870、2902、2927）；照明及配件属 IECEE RC 清单 | 能效与安全测试 | 能效卡；IECEE RC；SABER PCoC | 能效标签、阿语说明 | SASO | SA-L5-EE-001、SA-L5-IECEE-001 |

### 儿童玩具
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 海湾儿童玩具技术法规 BD-131704-01（沙特采纳） | GSO EN 71 等（电动加 IEC 62115） | G-Mark / SABER PCoC | 阿语警示与说明、进口商名称地址；网购前可见警示 | SASO / GSO | GCC-L5-TOYS-001、GCC-L3-TOYS-001、GCC-L1-SAFETY-002 |

### 婴童用品
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 儿童约束系统与婴儿推车技术法规（2022-03-31 批准）；2026-10-01 起本体标注供应商名称与 CR | UNECE R44/R129、推车标准；亚马逊另按 ASTM/EN | SABER PCoC | 本体 CR 标注（二手来源，待核） | SASO | SA-L5-CHILD-001、SA-L5-CRLABEL-001、GCC-L3-INFANT-001 |

### 食品接触材料
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 厨房工具与器具食品安全技术法规（2020-02-02 强制） | 迁移/重金属测试 | SABER PCoC | 食品接触标识 | SASO | SA-L5-KITCHEN-001、GCC-L1-HAZMAT-002（BPA） |

### 化妆品
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 《化妆品法》（M/49）；SFDA.CO/GSO 1943 标签、GSO 2528 宣称、SFDA.CO 6000 产品信息档案 | 安全评估/PIF | **SFDA GHAD 列名**（原称 eCosma）；申请人须持化妆品经营范围沙特 CR（外资另需投资部许可）；到期前 90 天续期 | 阿语标签；不得提及 SFDA 通报；每变体唯一条码 | SFDA | SA-L5-COSMETIC-001、GCC-L1-COSMETIC-001、GCC-L1-COSMETIC-002 |

### 个护健康电器
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 低压电气（吹风机、电暖器、剃须刀等）；剃须刀属 IECEE RC 清单；具医疗用途的（TENS 等）归 SFDA 医疗器械 | IEC 60335-2-23 等 | SABER PCoC / IECEE RC / SFDA MDMA | 阿语说明 | SASO / SFDA | GCC-L5-LVE-001、SA-L5-IECEE-001、SA-L5-MDMA-001、GCC-L3-LIAPPLIANCE-001 |

### 医疗器械
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 《医疗器械法》（M/54）；MDS-REQ 1（MDMA）；MDS-REQ 9（机构执照，电子商店属销售点） | 依风险等级 | SFDA MDMA（GHAD，境外制造商经授权代表）；进口/分销/网店须 SFDA 机构执照；SFDA 许可仓库 | UDI、符合性声明 | SFDA | SA-L5-MDMA-001、SA-L2-MEDDEV-001、SA-L2-OPTICAL-001、GCC-L1-MEDDEV-001 |

### 农药与抗菌宣称
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| SFDA 公共卫生农药清关要求；GSO 133/2004；海湾农药法（M/67）；亚马逊把抗菌、防霉宣称产品视为农药 | — | SFDA 国家农药登记（PNR）；批准仓库；每批进口许可 | 禁“无毒、安全”宣称 | SFDA | SA-L5-PESTICIDE-001、SA-L2-PESTICIDE-001、GCC-L1-PESTICIDE-001 |

### 化学品
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 洗涤剂、油漆清漆、胶粘剂（2021-12-17 公布）技术法规；润滑油 | 对应标准 | SABER PCoC；**油漆清漆环境性能卡 2026-10-01 起**（Maneh 平台） | 阿语警示 | SASO | SA-L5-CHEM-001、GCC-L1-HAZMAT-002 |

### 刀具武器
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 《武器弹药法》；ZATCA 禁止武器弹药、催泪瓦斯、电击器入境 | — | — | — | 内政部 / ZATCA | GCC-L1-WEAPON-001、GCC-L1-WEAPON-002、GCC-L1-WEAPON-003、GCC-L1-WEAPON-004、SA-L6-CUSTOMS-001 |

### 激光
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| ZATCA 禁带清单：激光笔（旅客仅可带 1 支 ≤5 mW 红光） | IEC 60825-1 | — | 等级标签 | ZATCA | SA-L6-CUSTOMS-001、GCC-L1-LASER-001 |

### 无人机
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| GACA 无人机规定（官网无法访问，二手来源称 250 g–25 kg 须注册、进口须登记序列号）；ZATCA 禁止带隐藏摄像头的飞行器 | 遥控/图传须通信设备法规 | GACA 注册与进口证明（待核）；SABER PCoC | — | GACA / CST / ZATCA | SA-L5-DRONE-001、SA-L1-ELEC-001、SA-L5-ICT-001 |

### 汽配
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 汽车备件技术法规（2018-05-07）；车辆与轮胎数据登记与能效卡（2022-03-25 公布）；轮胎能效（SASO 2857） | 对应标准 | SABER PCoC；轮胎能效卡 | 能效标签 | SASO | SA-L5-OTHER-001、SA-L5-EE-001、GCC-L1-AUTO-001 |

### 家具木制品
沙特 SASO 官方技术法规清单中未见家具或一般儿童用品专项法规；适用《产品安全法》通用要求与 SABER 自我声明 + 货运证书 [R:SA-L5-PSL-001] [R:SA-L5-SABER-001] [SRC-SA-GOV-SASO-TR-LIST]。门窗、建筑材料另有法规。

### 纺织服装
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 纺织品技术法规第 2 版（2024-07-12 强制）；鞋类及配件（2021-05-25）；皮革制品（2022-01-05） | 成分、有害物质（细节未核实） | SABER PCoC | 阿语成分、原产国、护理标签 | SASO | SA-L5-TEXTILE-001、GCC-L1-SAFETY-002 |

### 珠宝
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 饰品与配饰技术法规（2022-09-23 公布）；贵金属戳记 | 有害物质（细节未核实） | SABER PCoC | 纯度戳记 | SASO | SA-L5-TEXTILE-001、GCC-L1-JEWEL-001 |

### 宠物
亚马逊禁售兽用处方药与疫苗 [R:GCC-L1-DRUG-001]；SFDA 电商规则覆盖非处方兽药与饲料（须 SFDA 注册）[R:SA-L5-SFDAECOM-001]；宠物食品适用 SFDA 食品/饲料清关 [R:SA-L5-FOOD-001]。活体动物进口归 MEWA（未核实）。

### 植物种子
亚马逊沙特站“其他商品”页禁售植物和种子 [R:GCC-L1-PLANTS-001] [SRC-SA-AMZ-G201744040]；植物进口检疫归 MEWA（未核实）。

### 食品保健品
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| SFDA 食品清关条件（2026-08）；SFDA.FD/GSO 9；SFDA 药品/草本/健康产品注册规则（DS-REQ-074） | — | Ghad 企业与产品注册；FASAH 清关；SFDA 许可仓库（≤5 批/年且 ≤2,000 kg 可豁免）；健康产品 SFDA 注册 + 原产国 CPP/自由销售证明 | 阿语标签；清真证书 | SFDA | SA-L5-FOOD-001、SA-L5-HEALTH-001、GCC-L5-FOODLABEL-001、SA-L2-SUPPL-001 |

### 烟草电子烟
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| SFDA.FD 5005（尼古丁 ≤20 mg/ml、补充瓶 ≤30 ml、烟弹 ≤2 ml、仅水果/烟草/薄荷口味）；电子烟设备技术法规 M.E-172-19-04-03（2020-01-05）；嚼烟禁止进口 | 成分检测；设备 IECEE RC | SFDA 进口商注册 | 警示占正反面 ≥30% | SFDA / SASO | SA-L5-ECIG-001（亚马逊沙特站全面禁售：SA-L1-TOBACCO-001） |

### 酒类
亚马逊沙特站禁售酒类、含酒精食品、酒类品牌周边和发酵套件 [R:GCC-L1-ALCOHOL-001] [R:SA-L1-ALCOHOL-001]；ZATCA 将麻醉品、酒精饮品列为禁止物品 [R:SA-L6-CUSTOMS-001] [SRC-SA-GOV-ZATCA-PROHIBITED]。

### 成人用品
亚马逊沙特站禁售范围比阿联酋站更广（另含情趣新奇用品、紧致/增强凝胶、按摩棒、情趣服装）[R:GCC-L1-ADULT-001] [R:SA-L1-ELEC-001]；ZATCA 禁止性器具和未在 SFDA 注册的性功能增强品入境 [R:SA-L6-CUSTOMS-001]。

### 二手商品
亚马逊禁售二手汽配、二手服装鞋、二手医疗器械、已开封化妆品与健康产品 [R:GCC-L1-AUTO-001] [R:GCC-L1-COSMETIC-001] [R:GCC-L1-MEDDEV-001]。

### 其他 SASO 法规
个人防护装备（2019-12-07）、燃气器具（2017-10-14）、节水器具（2018-01-01）、可降解塑料制品（2017-04-14）、汽车备件、润滑油、纸制品等须合格评定 [R:SA-L5-OTHER-001] [SRC-SA-GOV-SASO-TR-LIST]。

### 电子商务法
《电子商务法》（M/126）适用于境外卖家：须披露名称、地址、联系方式、商业登记；7 天撤回权；交付延迟超过 15 天可取消；广告不得虚假或使用未授权标识；罚款最高 100 万里亚尔 [R:SA-L5-ECOMLAW-001] [SRC-SA-GOV-ECOMMERCE-LAW]。

### 进口与清关（L6）
- ZATCA 禁止物品（17 项）：毒品与酒精饮品、不道德内容存储介质、伪钞、烟花、嚼烟、催泪瓦斯、武器弹药、隐藏摄像头设备（含无人机）、激光笔、电击器、测速雷达探测器、Qoroo 果、违规出版物、未经 SFDA 注册的药丸/乳膏/性增强品/堕胎药/草药、肉豆蔻、性器具、窃听设备 [R:SA-L6-CUSTOMS-001] [SRC-SA-GOV-ZATCA-PROHIBITED]。
- 海湾共同海关法：禁止商品不得进口，限制商品须主管部门批准 [R:GCC-L6-CUSTOMS-001] [SRC-SA-GOV-ZATCA-CUSTOMS-LAW]。
- 跨境直邮：商品+运保 <1,000 里亚尔免关税但须缴增值税；SFDA 个人自用限额（化妆品 20 件/15 kg，OTC/补充剂 3 个月用量）[R:SA-L6-ESTORE-001] [SRC-SA-GOV-ZATCA-ESTORES] [SRC-SA-GOV-SFDA-PERSONAL-IMPORT]。
- 商业进口文件：商业发票、提单、原产地证、IECEE 证书（适用时）、主管部门注册；按 12 位 HS 编码（2025-01-01 起）查综合税则 [SRC-SA-GOV-ZATCA-IMPORT-INSTR]。

## F. 标签、语言与本地责任人

| 要求 | 内容 | 来源 / 规则 |
|---|---|---|
| 安全信息语言 | 安全警示、说明与技术文件须阿拉伯语；网络平台上的安全信息须阿语（实施细则第 32 条）；违者中等违规罚 10,001–1,000,000 里亚尔 | [SRC-SA-GOV-SASO-PSL] [R:SA-L5-PSL-001] |
| 亚马逊 PSL 属性 | 制造商与沙特进口商名称、注册地址、邮箱、联系方式至少阿语；阿语安全信息上传 | [SRC-SA-AMZ-G7BF8EFS2VHV3ZH3] [R:SA-L3-PSL-001] |
| 进口商标识 | 进口商名称/商号/商标与邮寄、电子邮箱地址标在产品上（第 19 条）；不得遮盖制造商标签（第 20 条） | [SRC-SA-GOV-SASO-PSL] [R:SA-L5-PSL-001] |
| 供应商 CR | 2026-10-01 起 10 项法规产品本体标沙特供应商名称与 CR | [R:SA-L5-CRLABEL-001]（二手来源，待核） |
| 通信设备 | 阿语标签（以阿语为准）：供应商、商标、制造商、型号、原产国、频段与最大功率、CST 标识 | [SRC-SA-GOV-SASO-ICT-TR] [R:SA-L5-ICT-001] |
| 低压电器、玩具 | 阿语安全信息与说明；符合性声明阿英双语 | [SRC-SA-GOV-SASO-LVE-TR] [R:GCC-L5-LVE-001] [R:GCC-L5-TOYS-001] |
| 食品 | 阿语标签（SFDA.FD/GSO 9）；亚马逊：阿语或阿英双语，仅英文须监管批准 | [SRC-SA-GOV-SFDA-FOOD-CLEARANCE] [SRC-SA-AMZ-G201744000] [R:SA-L5-FOOD-001] |
| 化妆品 | SFDA.CO/GSO 1943 阿语标签 | [R:SA-L5-COSMETIC-001] |
| 本地责任人 | SABER 账户、SFDA GHAD 化妆品账户、健康类目卖家资质、MDMA 授权代表、GAMR 执照均要求沙特实体（CR）；《产品安全法》下制造商在境外时网店/分销商承担制造商责任 | [R:SA-L5-SABER-001] [R:SA-L5-COSMETIC-001] [R:SA-L5-MDMA-001] [R:SA-L2-MEDICINE-001] |

## G. 2024–2026 变化与生效日期

| 日期 | 变化 | 影响的产品 | 规则ID | 来源 |
|---|---|---|---|---|
| 2024-07-12 | 纺织品技术法规第 2 版强制 | 服装、家纺 | SA-L5-TEXTILE-001 | SRC-SA-GOV-SASO-TR-LIST |
| 2024-09-30 | 亚马逊合规文件须获批后才能创建新 Listing | 受合规要求商品 | GCC-L2-APPROVAL-001 | SRC-AE-AMZ-GKCHRSWHXB5WZHAU |
| 2024-11-22 | 《产品安全法》实施细则公布施行 | 所有非 SFDA 产品 | SA-L5-PSL-001 | SRC-SA-GOV-SASO-PSL |
| 2025-01-01 | USB-C 第一阶段（手机、平板、耳机、相机、掌机、键鼠、音箱、路由器等）；ZATCA 12 位税则 | 便携电子 | SA-L5-USBC-001 | SRC-SA-GOV-CST-USBC-2024 |
| 2025-01-15 | SFDA MDS-REQ 9 v2.0（网店属销售点，须机构执照） | 医疗器械 | SA-L5-MDMA-001 | SRC-SA-GOV-SFDA-MDS-REQ9 |
| 约 2025-02-12 | 《通信与信息技术设备技术法规》适用；审批迁入 SABER（二手来源） | 无线/通信设备 | SA-L5-ICT-001 | SRC-SA-GOV-SASO-ICT-TR、SRC-SA-S3-ELEOS-CST-SABER |
| 2025-10-01 | 所有进口商品报关前须 SABER 货运证书 | 全部 | SA-L5-SABER-001 | SRC-SA-GOV-SASO-SC-BEFORE-DECL-2025 |
| 2025-10-26 | SFDA 个人自用进口要求 v3.0 | 跨境直邮化妆品、补充剂 | SA-L6-ESTORE-001 | SRC-SA-GOV-SFDA-PERSONAL-IMPORT |
| 2026-03-05 | 亚马逊沙特站笔记本发票要求 | 笔记本 | SA-L2-LAPTOP-001 | SRC-SA-AMZ-GHHSFDR8QJKL3J67 |
| 2026-04-01 | USB-C 第二阶段（笔记本） | 笔记本 | SA-L5-USBC-001 | SRC-SA-GOV-CST-USBC-2024 |
| 2026-05-01 | 8 类产品 USB-C 宽限期结束 | 相机、电子阅读器、音箱、键鼠、导航、路由器 | SA-L5-USBC-001 | SRC-SA-S3-CAICT-USBC-GRACE（二手来源，待核） |
| 2026-09-15/16 | SABER 货运证书有效期 60 → 90 天 | 全部进口 | SA-L5-SABER-001 | SRC-SA-GOV-SASO-SC-90D |
| 2026-10-01 | 10 项技术法规产品本体须标沙特供应商名称与 CR | 平衡车、推车/座椅、光伏、船只、挂车、压力容器、电梯等 | SA-L5-CRLABEL-001 | SRC-SA-S3-UL-CR-MARKING-2026（二手来源，待核） |
| 2026-10-01 | 油漆清漆环境性能卡强制 | 油漆、清漆 | SA-L5-CHEM-001 | SRC-SA-GOV-SASO-PAINTS-EPC-2026 |

## H. 来源清单

以下为本文与关联规则（GCC.yaml 中适用沙特站的规则 + SA.yaml）引用的全部来源，按级别排序。快照位于 policy/snapshots/SA/ 与 policy/snapshots/AE/。

| 来源 ID | 标题 | 级别 | 访问方式 | 访问日期 | URL |
|---|---|---|---|---|---|
| SRC-AE-AMZ-G200140860 | FBA product restrictions | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G200140860 |
| SRC-AE-AMZ-G200164390 | Art - Home Decor | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G200164390 |
| SRC-AE-AMZ-G200164570 | Hazardous and Dangerous Items | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G200164570 |
| SRC-AE-AMZ-G200164590 | Human Parts & Burial Artifacts | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G200164590 |
| SRC-AE-AMZ-G200164670 | Offensive and Controversial Materials | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G200164670 |
| SRC-AE-AMZ-G200164730 | Postage meters and stamps | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G200164730 |
| SRC-AE-AMZ-G200164850 | Stolen Property & Lock Picking Devices | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G200164850 |
| SRC-AE-AMZ-G200164870 | Surveillance Equipment | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G200164870 |
| SRC-AE-AMZ-G200164930 | Warranties, Service Plans, Contracts, and Guarantees | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G200164930 |
| SRC-AE-AMZ-G200333160 | Categories and products that require approval | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G200333160 |
| SRC-AE-AMZ-G200383420 | Requirements for lithium batteries and products that are shipped with lithium batteries | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G200383420 |
| SRC-AE-AMZ-G200500100 | Amazon Device Accessories | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G200500100 |
| SRC-AE-AMZ-G200686210 | Toy Safety Directive - Mandatory Safety Warnings | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G200686210 |
| SRC-AE-AMZ-G201003400 | Amazon Easy Ship – Dangerous goods identification guide (hazmat) | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G201003400 |
| SRC-AE-AMZ-G201689020 | Laser products | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G201689020 |
| SRC-AE-AMZ-G201730840 | FBA prohibited products | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G201730840 |
| SRC-AE-AMZ-G201737480 | Plants, Plant Products, and Seeds | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G201737480 |
| SRC-AE-AMZ-G201743950 | Animals and Animal Products | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G201743950 |
| SRC-AE-AMZ-G201743960 | Car & Motorbike | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G201743960 |
| SRC-AE-AMZ-G201743970 | Currency, Coins, Cash Equivalents and Gift Cards | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G201743970 |
| SRC-AE-AMZ-G201743980 | Cosmetics | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G201743980 |
| SRC-AE-AMZ-G201743990 | Drugs, Drug Paraphernalia and Dietary Supplements | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G201743990 |
| SRC-AE-AMZ-G201744000 | Food & Beverage | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G201744000 |
| SRC-AE-AMZ-G201744010 | Electronics | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G201744010 |
| SRC-AE-AMZ-G201744020 | Medical Devices | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G201744020 |
| SRC-AE-AMZ-G201744030 | Jewelry | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G201744030 |
| SRC-AE-AMZ-G201744040 | Other Products | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G201744040 |
| SRC-AE-AMZ-G201744060 | Sex and Sensuality | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G201744060 |
| SRC-AE-AMZ-G201744070 | Tobacco and Tobacco-Related Products | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G201744070 |
| SRC-AE-AMZ-G201744080 | Weapons | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G201744080 |
| SRC-AE-AMZ-G201744410 | Alcohol | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G201744410 |
| SRC-AE-AMZ-G201744450 | Gambling & Lottery | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G201744450 |
| SRC-AE-AMZ-G201744470 | Clothing | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G201744470 |
| SRC-AE-AMZ-G201829010 | Dietary supplements | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G201829010 |
| SRC-AE-AMZ-G202137200 | Child restraint systems, booster seats, and travel systems | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G202137200 |
| SRC-AE-AMZ-G202156120 | Device batteries and chargers | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G202156120 |
| SRC-AE-AMZ-G202162990 | Personal flotation devices | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G202162990 |
| SRC-AE-AMZ-G202171660 | Eclipse glasses and solar viewing filters | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G202171660 |
| SRC-AE-AMZ-G202183590 | Streaming Media Players | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G202183590 |
| SRC-AE-AMZ-G2HSXA2KM59YX5AT | Cylindrical rechargeable lithium batteries | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G2HSXA2KM59YX5AT |
| SRC-AE-AMZ-G5NGAYYZAY559SCZ | Children's sleepwear | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G5NGAYYZAY559SCZ |
| SRC-AE-AMZ-G5Z5K2WQ3ZYG9E6F | Sand based children's products | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G5Z5K2WQ3ZYG9E6F |
| SRC-AE-AMZ-G6E2SRU9QL3E3CG5 | Pesticides and insecticides | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G6E2SRU9QL3E3CG5 |
| SRC-AE-AMZ-G76DURDA6ZW48DX7 | High chairs and hook-on chairs | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G76DURDA6ZW48DX7 |
| SRC-AE-AMZ-G7HM69VDEMRW7TPE | Electronic mobility (e-mobility) accessories | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G7HM69VDEMRW7TPE |
| SRC-AE-AMZ-G7PAP6BJAUXRM4LH | Lithium batteries | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G7PAP6BJAUXRM4LH |
| SRC-AE-AMZ-G8KZHJBNC2647269 | Whipped cream dispensers | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G8KZHJBNC2647269 |
| SRC-AE-AMZ-G8TM22XFM7WXCRDC | Lithium battery powered home appliances | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G8TM22XFM7WXCRDC |
| SRC-AE-AMZ-GDPSRCGVBFSFY78H | Baby teething products | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GDPSRCGVBFSFY78H |
| SRC-AE-AMZ-GECCHPZ45P4KVFN6 | Cribs, cradles, bassinets, and bedside sleepers | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GECCHPZ45P4KVFN6 |
| SRC-AE-AMZ-GFEUQFB9X4YWFVXD | Water beads | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GFEUQFB9X4YWFVXD |
| SRC-AE-AMZ-GFQMECECLTJCUE3H | Battery-operated heated apparel and insoles | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GFQMECECLTJCUE3H |
| SRC-AE-AMZ-GGB3K8RJ6ZEB8QQ6 | Fire and smoke masks | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GGB3K8RJ6ZEB8QQ6 |
| SRC-AE-AMZ-GGLAL34T93UJQ6KD | Infant Slings and Soft Carriers | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GGLAL34T93UJQ6KD |
| SRC-AE-AMZ-GKCHRSWHXB5WZHAU | Creating new selection with compliance requirements | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GKCHRSWHXB5WZHAU |
| SRC-AE-AMZ-GKJRA3FRPRKVBJJS | Children's toys | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GKJRA3FRPRKVBJJS |
| SRC-AE-AMZ-GMUW6CKYLY4AP8MK | Electronic mobility (e-mobility) devices | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GMUW6CKYLY4AP8MK |
| SRC-AE-AMZ-GRLKLZ6WQ9R259LC | Product safety listing restrictions | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GRLKLZ6WQ9R259LC |
| SRC-AE-AMZ-GSJFE8S8AES7F7VG | Portable power supplies | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GSJFE8S8AES7F7VG |
| SRC-AE-AMZ-GT8V6T7U8GZZK3SU | Car seat heating pads | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GT8V6T7U8GZZK3SU |
| SRC-AE-AMZ-GUFQGCVJXHSYBL2Z | Infant bouncers, swings, and rockers | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GUFQGCVJXHSYBL2Z |
| SRC-AE-AMZ-GUG6JJCDN6YYQYJP | Infant and toddler feeding products | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GUG6JJCDN6YYQYJP |
| SRC-AE-AMZ-GX9BGE7LAFRWAFHF | Pacifiers and pacifier clips | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GX9BGE7LAFRWAFHF |
| SRC-AE-AMZ-GXPFG3RRZB9WFPJE | Portable bed rails | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GXPFG3RRZB9WFPJE |
| SRC-SA-AMZ-G200140860 | FBA product restrictions | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G200140860 |
| SRC-SA-AMZ-G200164330 | Restricted products | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G200164330 |
| SRC-SA-AMZ-G200333160 | Categories and products that require approval | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G200333160 |
| SRC-SA-AMZ-G201730840 | FBA prohibited products | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G201730840 |
| SRC-SA-AMZ-G201743950 | Animals and Animal Products | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G201743950 |
| SRC-SA-AMZ-G201743960 | Car & Motorbike | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G201743960 |
| SRC-SA-AMZ-G201743970 | Currency, Coins, Cash Equivalents and Gift Cards | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G201743970 |
| SRC-SA-AMZ-G201743980 | Cosmetics | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G201743980 |
| SRC-SA-AMZ-G201743990 | Drugs, Drug Paraphernalia and Dietary Supplements | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G201743990 |
| SRC-SA-AMZ-G201744000 | Food & Beverage | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G201744000 |
| SRC-SA-AMZ-G201744010 | Electronics | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G201744010 |
| SRC-SA-AMZ-G201744020 | Medical Devices | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G201744020 |
| SRC-SA-AMZ-G201744030 | Jewellery | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G201744030 |
| SRC-SA-AMZ-G201744040 | Other Products | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G201744040 |
| SRC-SA-AMZ-G201744060 | Sex and Sensuality | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G201744060 |
| SRC-SA-AMZ-G201744070 | Tobacco and Tobacco-Related Products | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G201744070 |
| SRC-SA-AMZ-G201744080 | Weapons | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G201744080 |
| SRC-SA-AMZ-G201744410 | Alcohol | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G201744410 |
| SRC-SA-AMZ-G201744450 | Gambling & Lottery | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G201744450 |
| SRC-SA-AMZ-G201744470 | Clothing | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G201744470 |
| SRC-SA-AMZ-G202183590 | Streaming Media Players | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G202183590 |
| SRC-SA-AMZ-G2HSXA2KM59YX5AT | Cylindrical rechargeable lithium batteries | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G2HSXA2KM59YX5AT |
| SRC-SA-AMZ-G2JX2MAWJ27DWAY6 | Compliance Reference | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G2JX2MAWJ27DWAY6 |
| SRC-SA-AMZ-G6E2SRU9QL3E3CG5 | Pesticides and insecticides | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G6E2SRU9QL3E3CG5 |
| SRC-SA-AMZ-G7BF8EFS2VHV3ZH3 | KSA Product Safety Law (PSL) | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G7BF8EFS2VHV3ZH3 |
| SRC-SA-AMZ-G7PAP6BJAUXRM4LH | Lithium batteries | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G7PAP6BJAUXRM4LH |
| SRC-SA-AMZ-G9NQF8P6KC9D4KNC | Video games | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G9NQF8P6KC9D4KNC |
| SRC-SA-AMZ-GAMA3EHSBQLETA84 | Optical products | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/GAMA3EHSBQLETA84 |
| SRC-SA-AMZ-GANZMW59X43K46C3 | Medical devices and accessories | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/GANZMW59X43K46C3 |
| SRC-SA-AMZ-GF77H4GPLRVCNBWT | Medicinal products | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/GF77H4GPLRVCNBWT |
| SRC-SA-AMZ-GHHSFDR8QJKL3J67 | KSA Version Laptop Products and Upgraded Laptop Products | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/GHHSFDR8QJKL3J67 |
| SRC-SA-AMZ-GKJRA3FRPRKVBJJS | Children's toys | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/GKJRA3FRPRKVBJJS |
| SRC-SA-AMZ-GNHUT67GAR39XJ9D | Dietary supplements | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/GNHUT67GAR39XJ9D |
| SRC-SA-AMZ-GRLKLZ6WQ9R259LC | Product safety listing restrictions | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/GRLKLZ6WQ9R259LC |
| SRC-SA-AMZ-GWVV3PMKJ28ULL9S | Public health pesticides | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/GWVV3PMKJ28ULL9S |
| SRC-AE-GOV-CR-123-2024 | Cabinet Resolution No. 123 of 2024 approving GCC lists of prohibited and restricted goods | S2 | search_snippet | 2026-10-10 | https://uaelegislation.gov.ae/en/legislations/2710 |
| SRC-AE-GOV-MOIAT-CAD-REGULATED-SHEET | MoIAT List of technical requirements for regulated products (CAD regulated sheet, 2022) | S2 | webfetch | 2026-10-10 | https://moiat.gov.ae/-/media/site/moiat/document/services-user-manual/cad-regulated-sheet.ashx |
| SRC-AE-GOV-MOIAT-LAWS-LIST | MoIAT Laws and Legislation (list of technical regulations / Cabinet Resolutions) | S2 | webfetch | 2026-10-10 | https://moiat.gov.ae/en/about-us/laws-and-legislation |
| SRC-AE-GOV-TDRA-TYPE-APPROVAL | TDRA Type Approval (incl. prohibited devices list) | S2 | jina_reader | 2026-10-10 | https://tdra.gov.ae/en/About/tdra-sectors/telecommunication/departments/technology-development-affairs-department/type-approval |
| SRC-AE-GOV-UAE-CUSTOMS | u.ae - Customs clearance (banned and restricted goods) | S2 | jina_reader | 2026-10-10 | https://u.ae/en/information-and-services/visiting-and-exploring-the-uae/Tourist-services-and-information/Customs-clearance |
| SRC-GCC-GOV-GSO-GMARK | GSO - Gulf Conformity Mark (G-Mark) | S2 | webfetch | 2026-10-10 | https://www.gso.org.sa/en/conformity/gcc-conformity-mark/ |
| SRC-GCC-GOV-GSO-TOYS-TR | GCC Technical Regulation on Children Toys BD-131704-01 (Issue 2, 2013-05-08) | S2 | webfetch | 2026-10-10 | https://www.gso.org.sa/wp-content/uploads/2018/10/GSO_TechnicalRegulationForChildrenToys.pdf |
| SRC-SA-GOV-CST-RADIO-DIST | CST service - Radio equipment distribution | S2 | webfetch | 2026-10-10 | https://www.cst.gov.sa/business/services/Radio-Equipment-Distribution |
| SRC-SA-GOV-CST-USBC-2023 | CST - Announcing the mandatory stages of unifying charging ports (2023-08-06) | S2 | webfetch | 2026-10-10 | https://www.cst.gov.sa/media-center/news/Announcing-the-mandatory-stages-of-unifying-charging-ports-for-mobile-phones-and-electronic-devices |
| SRC-SA-GOV-CST-USBC-2024 | CST/SASO joint press release - USB-C unified charging port phases (2024-10-23) | S2 | jina_reader | 2026-10-10 | https://cst.gov.sa/en/mediacenter/pressreleases/Pages/2024102301.aspx |
| SRC-SA-GOV-ECOMMERCE-LAW | Saudi E-Commerce Law (Royal Decree M/126, 1440H) - official translation (MISA) | S2 | webfetch | 2026-10-10 | https://misa.gov.sa/app/uploads/2025/07/E-Commerce-Law.pdf |
| SRC-SA-GOV-SABER-CR-CIRCULAR | SABER circular - supplier name and CR number on product (from 2026-10-01) [not opened] | S2 | search_snippet | 2026-10-10 | https://saber.sa/Assets/Home/Circular_Supplier_Name_and_CR_on_Product.pdf |
| SRC-SA-GOV-SASO-CONFORMITY-MODELS | SASO General Regulation for Conformity Models (2023) | S2 | webfetch | 2026-10-10 | https://www.saso.gov.sa/ar/Laws-And-Regulations/Technical_regulations/Documents/TR-General-Regulation-for-Conformity-Models.pdf |
| SRC-SA-GOV-SASO-EE-CARD | SASO energy efficiency card service | S2 | jina_reader | 2026-10-10 | https://www.saso.gov.sa/ar/sectors/certificates/efficiency_card/pages/default.aspx |
| SRC-SA-GOV-SASO-EE-TR | SASO General Technical Regulation for Energy Efficiency (Issue 1, Amendment 3) | S2 | webfetch | 2026-10-10 | https://www.saso.gov.sa/ar/Laws-And-Regulations/Technical_regulations/Documents/TR-Regulation-Energy-Efficiency.pdf |
| SRC-SA-GOV-SASO-ICT-TR | Technical Regulation for Communications and Information Technology Devices (SASO/CST, published 2024-08-16) | S2 | webfetch | 2026-10-10 | https://www.saso.gov.sa/ar/Laws-And-Regulations/Technical_regulations/Documents/TR-Communications-and-Information-Technology-Devices.pdf |
| SRC-SA-GOV-SASO-IECEE | SASO IECEE / IECEx national recognition certificates (product list and documents) | S2 | jina_reader | 2026-10-10 | https://www.saso.gov.sa/ar/sectors/certificates/iec/Pages/default.aspx |
| SRC-SA-GOV-SASO-LVE-LIST2 | GSO List No. 2 (TC143307-01) - low voltage products requiring G-Mark (Annex 4) | S2 | webfetch | 2026-10-10 | https://www.saso.gov.sa/ar/Laws-And-Regulations/Technical_regulations/SiteAssets/Pages/regulation3/tc143307-01-ar-en.pdf |
| SRC-SA-GOV-SASO-LVE-TR | Gulf Technical Regulation for Low Voltage Electrical Equipment and Appliances BD-142004-01 (SASO-hosted) | S2 | webfetch | 2026-10-10 | https://www.saso.gov.sa/en/Laws-And-Regulations/Technical_regulations/Documents/Gulf-Technical-Regulation-for-Low-Voltage-Electrical-Equipment-and-Appliances-BD-142004-01.pdf |
| SRC-SA-GOV-SASO-NEWS-1230 | SASO news 1230 - IECEE/IECEx additional products from 2021-11-01 | S2 | webfetch | 2026-10-10 | https://www.saso.gov.sa/ar/mediacenter/news/Pages/saso_news_1230.aspx |
| SRC-SA-GOV-SASO-NEWS-913 | SASO news 913 - IECEE phase 2 (2018-08-01) | S2 | webfetch | 2026-10-10 | https://www.saso.gov.sa/en/mediacenter/news/Pages/saso_news_913.aspx |
| SRC-SA-GOV-SASO-PAINTS-EPC-2026 | SASO news - environmental performance card for paints and varnishes mandatory from 2026-10-01 | S2 | webfetch | 2026-10-10 | https://www.saso.gov.sa/ar/mediacenter/news/Pages/environmental-performance-label-paints-varnishes-2026.aspx |
| SRC-SA-GOV-SASO-PSL | Product Safety Law (Royal Decree M/36, 1446H) and Executive Regulations (published 2024-11-22) | S2 | jina_reader | 2026-10-10 | https://saso.gov.sa/ar/Laws-And-Regulations/exeRules/Pages/Product-Safety-System.aspx |
| SRC-SA-GOV-SASO-PSL-GUIDE | SASO Guidance Manual for the Product Safety Law (linked from Amazon PSL page) | S2 | search_snippet | 2026-10-10 | https://www.saso.gov.sa/en/Laws-And-Regulations/guidelines/Documents/Guidanec-manual-for-the-Product-Safety-System-English.pdf |
| SRC-SA-GOV-SASO-QMARK-TR | SASO General Regulations for the Saudi Quality Mark | S2 | webfetch | 2026-10-10 | https://www.saso.gov.sa/en/Laws-And-Regulations/Technical_regulations/Documents/TR-saudi-quality-mark.pdf |
| SRC-SA-GOV-SASO-SC-90D | SASO news - SABER shipment certificate validity extended from 60 to 90 days (Sep 2026) | S2 | jina_reader | 2026-10-10 | https://www.saso.gov.sa/ar/mediacenter/news/Pages/saber-shipment-certificates-validity-90-days.aspx |
| SRC-SA-GOV-SASO-SC-BEFORE-DECL-2025 | SASO news - Shipment certificate required before customs declaration for all products (effective 2025-10-01) | S2 | jina_reader | 2026-10-10 | https://www.saso.gov.sa/ar/mediacenter/news/Pages/saso-news-1483.aspx |
| SRC-SA-GOV-SASO-TOYS-TR | GCC Technical Regulation on Children Toys BD-131704-01 (SASO-hosted) | S2 | webfetch | 2026-10-10 | https://www.saso.gov.sa/ar/Laws-And-Regulations/Technical_regulations/Documents/bd-131704-01.pdf |
| SRC-SA-GOV-SASO-TR-LIST | SASO list of technical regulations (with approval/publication/mandatory dates) | S2 | webfetch | 2026-10-10 | https://www.saso.gov.sa/en/Laws-And-Regulations/Technical_regulations/Pages/default.aspx |
| SRC-SA-GOV-SFDA-COSMETIC-NOTIF | SFDA Guidance and Requirements of Cosmetic Product Notification (GHAD; PDF v2025-03) | S2 | webfetch | 2026-10-10 | https://www.sfda.gov.sa/en/regulations/guidance-and-requirements-cosmetic-product-notification |
| SRC-SA-GOV-SFDA-ECOM-STORES | SFDA Requirements to be followed by e-commerce stores (advertising/promotion of SFDA-regulated products) | S2 | webfetch | 2026-10-10 | https://www.sfda.gov.sa/en/regulations/requirements-be-followed-e-commerce-stores |
| SRC-SA-GOV-SFDA-ENDS | SFDA.FD 5005 E-liquids and heated tobacco in ENDS | S2 | webfetch | 2026-10-10 | https://www.sfda.gov.sa/en/regulations/electronic-nicotine-delivery-systems |
| SRC-SA-GOV-SFDA-FOOD-CLEARANCE | SFDA Conditions and Requirements for Food Clearance (2026-08) | S2 | webfetch | 2026-10-10 | https://www.sfda.gov.sa/en/regulations/17763 |
| SRC-SA-GOV-SFDA-HEALTH-PRODUCT-REG | SFDA Registration Rules for Pharmaceutical, Herbal and Health Product Manufacturers and Products (DS-REQ-074) | S2 | webfetch | 2026-10-10 | https://www.sfda.gov.sa/en/regulations/registration-rules-pharmaceutical-herbal-and-health-product-manufacturers-and-their |
| SRC-SA-GOV-SFDA-MDS-REQ1 | SFDA MDS-REQ 1 Requirements for Medical Devices Marketing Authorization (v6.0) | S2 | webfetch | 2026-10-10 | https://www.sfda.gov.sa/en/regulations/requirements-medical-devices-marketing-authorization-mds-req-1 |
| SRC-SA-GOV-SFDA-MDS-REQ9 | SFDA MDS-REQ 9 Requirements for Licensing Medical Devices Establishments (v2.0, 2025-01-15) | S2 | webfetch | 2026-10-10 | https://www.sfda.gov.sa/en/regulations/requirements-licensing-medical-devices-establishments-mds-req9 |
| SRC-SA-GOV-SFDA-PERSONAL-IMPORT | SFDA requirements for clearance of personal-use shipments (OPS-REQ-090 v3.0, 2025-10-26) | S2 | webfetch | 2026-10-10 | https://www.sfda.gov.sa/en/regulations/19371 |
| SRC-SA-GOV-SFDA-PESTICIDE-CLEARANCE | SFDA Clearance conditions and requirements of public health pesticides | S2 | webfetch | 2026-10-10 | https://www.sfda.gov.sa/en/regulations/clearance-conditions-and-requirements-public-health-pesticides |
| SRC-SA-GOV-SFDA-TOBACCO-CLEARANCE | SFDA Requirements and conditions for tobacco products clearance (v2, 2020) | S2 | webfetch | 2026-10-10 | https://www.sfda.gov.sa/en/regulations/requirements-and-conditions-tobacco-products-clearance |
| SRC-SA-GOV-ZATCA-CUSTOMS-LAW | GCC Common Customs Law (ZATCA copy) - prohibited and restricted goods definitions | S2 | webfetch | 2026-10-10 | https://zatca.gov.sa/ar/RulesRegulations/Taxes/Documents/customs%20law.pdf |
| SRC-SA-GOV-ZATCA-ESTORES | ZATCA - goods purchased from foreign online stores (SAR 1,000 duty threshold) | S2 | jina_reader | 2026-10-10 | https://zatca.gov.sa/en/RulesRegulations/Taxes/Pages/customs-individual/e-stores-customers.aspx |
| SRC-SA-GOV-ZATCA-IMPORT-INSTR | ZATCA import instructions (commercial) | S2 | webfetch | 2026-10-10 | https://zatca.gov.sa/en/RulesRegulations/Taxes/Pages/customs-bussiness/import-pages/Import-Instructions.aspx |
| SRC-SA-GOV-ZATCA-PROHIBITED | ZATCA - Prohibited goods (travellers), Minister of Finance Decision 2597 | S2 | jina_reader | 2026-10-10 | https://zatca.gov.sa/ar/RulesRegulations/Taxes/Pages/customs-individual/Prohibited-goods.aspx |
| SRC-SA-S3-ARABNEWS-DRONES | Arab News - Saudi GACA drone registration rules (2019) | S3 | search_snippet | 2026-10-10 | https://www.arabnews.pk/node/1434066 |
| SRC-SA-S3-ARABNEWS-QMARK-2020 | Arab News - Quality mark deadline alert for electrical products in KSA (2020) | S3 | webfetch | 2026-10-10 | https://www.arabnews.com/saudi-arabia/quality-deadline-alert-for-electrical-products-in-ksa-1700521 |
| SRC-SA-S3-CAICT-USBC-GRACE | CAICT GMA - SASO circular extending USB-C grace for 8 product types to 2026-05-01 | S3 | webfetch | 2026-10-10 | https://gma.caict.ac.cn/en/update/11/1263 |
| SRC-SA-S3-ELEOS-CST-SABER | Eleos Compliance - Saudi Arabia transitions from CST platform to SABER (2025-02) | S3 | webfetch | 2026-10-10 | https://eleoscompliance.com/en/article/saudi-arabia-transitions-from-cst-platform-to-saber |
| SRC-SA-S3-HQTS-CR-LABEL | HQTS - SASO new labeling rule (2026) | S3 | webfetch | 2026-10-10 | https://www.hqts.com/saso-new-labeling-rule/ |
| SRC-SA-S3-HQTS-SABER-GUIDE | HQTS - SABER certificate guide (risk classes, PCoC, SC) | S3 | search_snippet | 2026-10-10 | https://www.hqts.com/saber-certificate-guide/ |
| SRC-SA-S3-MENACERT-CR-LABEL | MENACERT - Saudi Arabia new SASO product labeling rules effective October 1, 2026 | S3 | webfetch | 2026-10-10 | https://mena-cert.com/news/saudi-arabia-new-saso-product-labeling-rules-effective-october-1-2026 |
| SRC-SA-S3-UL-CR-MARKING-2026 | UL - SASO issues new product marking requirements (supplier name and CR, 2026-10-01) | S3 | webfetch | 2026-10-10 | https://www.ul.com/news/saso-issues-new-product-marking-requirements |
| SRC-SA-S3-UL-SABER-GMARK | UL - SABER requires association of local suppliers with G-Mark (2020) | S3 | webfetch | 2026-10-10 | https://ul.com/news/saudi-arabia-saber-e-platform-requires-mandatory-association-local-suppliers-g-mark |

共 151 个来源（S1 99，S2 43，S3 9）。

## 待核实/冲突

**亚马逊页面之间的冲突**
1. **雪茄剪**：沙特站药品/吸毒用具页列为“烟草相关禁售品”，烟草页列为允许商品 [R:SA-L1-TOBACCO-002]。
2. **激光**：电子页称便携激光一律禁售，激光页允许 Class 1/1C/1M（激光页沙特版未单独抓取）[R:GCC-L1-LASER-001]。
3. **锂电池 FBA 上限**：危险品页（2018）与锂电池页“Middle East Rejected”口径不一致 [R:GCC-L4-LIION-001]。
4. **尼古丁贴**：医疗器械页允许、烟草页禁“其他尼古丁产品” [R:GCC-L1-TOBACCO-001]。

**亚马逊页面未能获取或口径不清**
5. **“安全风险商品销售限制”页（GKKYJ3C25DG334PW）**：以 en_AE、ar_AE、zh_CN、?locale=en-AE 参数，/help/hub 与 /gp/help 两种路径，沙特与阿联酋两个域名多次抓取（含等待渲染），均只得到导航壳或被限流（429），页面可能须登录，内容未知。
6. **照明页（G201997070）**只有标题无正文；**SIM 卡页**沙特版未抓取；儿童座椅、灯串、报警器、灭火器的沙特版页面未抓取（阿联酋版要求 ECAS/民防局证书）。
7. **活体动物**：沙特站动物页首条为“CITES 物种”，未逐字写“活体动物禁售” [R:SA-L1-ANIMAL-001]。
8. **“面具”禁售范围**（是否包括装扮面具以外的面罩）页面未说明 [R:SA-L1-OTHER-001]。
9. **普通厨刀/折叠刀、含 BPA 产品范围、CBD** 同阿联酋站待核实项 [R:GCC-L1-WEAPON-003] [R:GCC-L1-HAZMAT-002] [R:GCC-L1-DRUG-002]。

**当地法规未能读到官方原文或仅有二手来源**
10. **供应商名称与 CR 本体标注通函**（saber.sa 无法访问）：生效日 2026-10-01 与 10 项法规清单多家二手来源一致，通函编号（有称 247 号）及“仅包装不够”的说法未核实 [R:SA-L5-CRLABEL-001]。
11. **SABER 细节**：PCoC 1 年有效、SC 单次有效与 15 天 FASAH 登记、SC 费用、风险分级、2020 年 SABER–FASAH 对接均为二手来源 [R:SA-L5-SABER-001]。
12. **SC 有效期**：官方新闻为 90 天（2026-09）；部分检测机构仍写 60 天、甚至 1 年。
13. **USB-C 日期冲突**：法规与 CST 公告为 2025-01-01；有检测机构称整体推迟到 2026-01-01；官方通函图片显示宽限仅限 8 类（至 2026-05-01）。规则按“手机/平板/耳机/掌机 2025-01-01，8 类 2026-05-01，笔记本 2026-04-01”处理 [R:SA-L5-USBC-001]。
14. **CST 型号核准是否已完全并入 SABER**：二手来源称 2025-02-12 迁移，另有物流资料称仍需单独 CST 核准；CST 官网未找到迁移公告和消费类蓝牙/Wi-Fi 设备的进口商注册要求 [R:SA-L5-ICT-001]。
15. **任务说明的法规编号写反**：官方文件显示低压电气为 BD-142004-01，玩具为 BD-131704-01 [R:GCC-L5-LVE-001] [R:GCC-L5-TOYS-001]。
16. **化妆品系统名称**：任务说明中的“eCosma”在 SFDA 现行指南（2025）中为 GHAD；列名有效期长度未核实 [R:SA-L5-COSMETIC-001]。
17. **沙特质量标志强制清单**（仅见 2020 年新闻的“电气连接产品”）[R:SA-L5-QMARK-001]；**能效卡申请平台**名称、电视是否需能效标签、热水器标准号（官方页 SASO 2883 疑为 2884 之误）[R:SA-L5-EE-001]。
18. **电池技术法规**是否覆盖锂电池、**EV 法规**是否覆盖充电桩、**可降解塑料法规**对一次性塑料制品的具体要求未读原文 [R:SA-L5-ELEC-001] [R:SA-L5-OTHER-001]。
19. **ZATCA 商业进口禁止/限制清单**：官方页面只有旅客清单，未找到列明猪肉、宗教物品、赌具、仿冒品的商业清单；限制商品对应审批机构清单未找到 [R:SA-L6-CUSTOMS-001] [R:GCC-L6-CUSTOMS-001]。
20. **GACA 无人机注册与进口许可**（官网超时）仅见 2019 年新闻 [R:SA-L5-DRONE-001]。
21. **商务部阿语标签/商业数据法**、《电子商务法》实施细则全文（mc.gov.sa 证书错误）未读 [R:SA-L5-ECOMLAW-001]。
22. **MEWA** 对农业农药、活体动物、植物进口的管辖未核实；**食品形态补充剂与“健康产品”的分类界线**未核实 [R:SA-L5-PESTICIDE-001] [R:SA-L5-HEALTH-001]。
23. **MDMA 有效期**未核实 [R:SA-L5-MDMA-001]；**纺织/鞋类/饰品法规**的标签与限值条款未读原文 [R:SA-L5-TEXTILE-001]。
24. **工业部（MIM）声明**：纸板、福米卡板、婴儿纸尿裤、塑料管、陶土管申请 SC 须附 MIM 批准声明（2025-04-17 起，2025-09-15 扩大 HS 范围），仅见二手来源，未纳入规则。
