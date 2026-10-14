# 阿联酋站（amazon.ae）禁限售与合规要求

> 规则包版本：draft · 调研日期：2026-10-10 · 本文描述亚马逊平台政策和当地法规要求，不构成法律意见。
> 每条结论后用 [SRC-…] 标注来源（见 rules/sources/AE.yaml、GCC.yaml、SA.yaml），用 [R:规则ID] 关联机读规则（rules/sites/GCC.yaml、AE.yaml）。
> 来源级别：S1 亚马逊官方 · S2 政府官方 · S3 二手。只有 S3 支撑的结论标注「（二手来源，待核）」。
> 阿联酋站和沙特站共用的平台规则写在 GCC.yaml（`sites: [AE, SA]`），本文完整列出；两站差异在表中注明，沙特站情况见 policy/SA.md。

**先读这 6 条（对中国卖家影响最大）**
1. 不支持 220V 的电器一律禁售；插电电器还须配 G 型（英标三脚）插头或永久固定、须工具才能拆的转换插头。“欧版+送转换头”不行 [R:GCC-L1-ELEC-002] [R:AE-L3-PLUG-001] [SRC-AE-AMZ-G201744010] [SRC-AE-AMZ-G201416530]。
2. 所有额定 ≥3.0V 的圆柱形可充电电池（18650、21700、26650、14500、16340 等）及内含此类电池的产品禁售（带端子、包覆密封的电池组除外）——手电筒、头灯、充电电池套装基本无法上架 [R:GCC-L1-SAFETY-001] [SRC-AE-AMZ-G2HSXA2KM59YX5AT]。
3. 中东站 FBA 只接受单电芯 ≤20 Wh、电池组 ≤100 Wh 的锂离子电池 [R:GCC-L4-LIION-001] [SRC-AE-AMZ-G200383420]。
4. 带蓝牙/Wi-Fi 的商品须 TDRA 型号核准；TDRA 合格标志须在电商详情页醒目展示（政策 V4 的生效日期在来源原文中未找到，待核实） [R:AE-L5-TDRA-001] [R:AE-L5-TDRA-003] [SRC-AE-GOV-TDRA-TA-POLICY-V4]。
5. 健康类（补充剂、隐形眼镜、医疗耗材、血压计血糖仪等）要求阿联酋本地营业/药房执照，跨境卖家基本无法满足 [R:AE-L2-HEALTH-001] [R:AE-L2-HEALTH-002] [R:AE-L2-HEALTH-003] [R:AE-L2-HEALTH-004] [SRC-AE-AMZ-GFQWXF6XE3EAWTMP]。
6. 一次性塑料制品（餐具、杯、吸管、泡沫盒、购物袋）在阿联酋站禁售，2026-01-01 起联邦禁令扩大 [R:AE-L1-SINGLEUSE-001] [R:AE-L5-SUP-001]。

---

## A. 禁售清单（L1）

| 类别 | 亚马逊页面（G 编号） | 禁止销售的典型商品 | 例外/允许销售的情况 | 规则ID |
|---|---|---|---|---|
| 动物及动物制品 | G201743950 | 活体动物（含 2016 年第 22 号联邦法附件 1 危险动物）；真皮草；尖刺项圈、电击训狗项圈及电子围栏、粘鼠板（脊椎动物）、捕猫器、斗鸡刀、虐待动物内容；海豹/鳍足类、猫狗、濒危物种（象牙、鳄鱼、蛇皮、珊瑚、海龟壳等）、鲨鱼鲸海豚、未鞣制生皮 [SRC-AE-AMZ-G201743950] | 合规的非濒危动物食品；电子灭鼠器 | AE-L1-ANIMAL-001、GCC-L1-ANIMAL-001、GCC-L1-ANIMAL-002、GCC-L1-ANIMAL-003 |
| 汽车摩托 | G201743960 | 新旧整车；二手汽摩配件；安全气囊及气体发生器、安全带及组件（含延长扣）；翻新轮胎；缺必要认证的车用电器配件 [SRC-AE-AMZ-G201743960] | 新电瓶、头盔、反光背心、三角牌、轮胎、配件、机油（危险品另审）、油桶 | GCC-L1-AUTO-001 |
| 货币、礼品卡 | G201743970、G200164730 | 礼品卡/礼券/储值码、比特币、汇票、旅行支票、金银条、股票证券、可在境外流通的外币；伪钞、伪造邮票及制造设备 [SRC-AE-AMZ-G201743970] | 披露信息的收藏钱币（非可流通外币）；明确标为复制品的仿币/仿邮票；超过 1 g 贵金属按重量售 | GCC-L1-CURRENCY-001、GCC-L1-CURRENCY-002 |
| 化妆品 | G201743980 | 开封/过期/非原厂密封/追溯码被去除/试用装；仅限专业或需处方的产品（如释放 >0.1% 过氧化氢的牙齿美白）；含迪拜市政禁用成分；蛇油；非纯天然皮肤指甲花 [SRC-AE-AMZ-G201743980] | 原厂密封、标签合规的包装美妆护肤护发品（须类目审核） | GCC-L1-COSMETIC-001、GCC-L1-COSMETIC-002 |
| 药品 | G201743990 | 处方药、须药剂师销售的药、GSL/OTC 药（含阿司匹林、对乙酰氨基酚、布洛芬）、未许可药品、兽用处方药与疫苗、抗生素 [SRC-AE-AMZ-G201743990] | 健康产品页允许持阿联酋药房/类药品贸易执照且已注册的 OTC-G 药（冲突，见待核实） | GCC-L1-DRUG-001、AE-L1-DRUG-001 |
| 毒品与“合法兴奋剂” | G201743990 | 非法药物及仿效产品、合成大麻、legal highs、麻黄碱、GBL、GHB、DNP、Poppers、合成尿液 | — | GCC-L1-DRUG-002 |
| 补充剂（掺假/特定成分） | G201743990 | 掺西布曲明/DMAA/类固醇/西地那非等的减肥、健身、性功能补充剂（附数百品牌清单）；鹿茸、甲状腺提取物、鲨鱼软骨；WADA 禁用物质、生长激素、HCG；治癌、解酒、驱虫排毒宣称；烟酸 >50 mg/日、烟酰胺 >500 mg/日 | 合规膳食补充剂、药妆、消毒剂、符合迪拜市政通函的保健补充剂 | GCC-L1-SUPPL-001、GCC-L1-HEALTH-001 |
| 吸毒用具 | G201743990 | 带线卷烟纸、bong、金属/玻璃/陶瓷等材质烟斗、vaporizer、美化毒品的商品 | **阿联酋站允许**烟斗、Dokha 烟斗、水烟、雪茄剪、烟灰缸、卷烟纸（沙特站禁止） | GCC-L1-PARAPH-001、AE-L1-TOBACCO-001 |
| 食品饮料 | G201744000 | 含猪肉/猪源成分；鹅肝；鲨鱼/鲸肉；含毒品或仿毒品糖果；Kava、食用膨润土、牛肉噻吩、迷你果冻杯、疯蜂蜜；未注册新资源食品（神秘果、千日红、泰国野葛根、淫羊藿）；过期或“非零售”食品；带健康功效宣称的食品 [SRC-AE-AMZ-G201744000] | 正确包装标注的合规食品（须类目审核，阿英双语成分） | GCC-L1-FOOD-001、GCC-L1-FOOD-002、GCC-L1-FOOD-003 |
| 电子 | G201744010 | 干扰器、雷达探测器、交通信号操控、里程表篡改、解码破解、手机解锁、智能卡编程器、AdBlue 模拟器、刷卡终端；偷拍偷听设备；部分流媒体播放器/语音助手；**不支持 220V 的电器**；游戏模拟器与破解芯片；Kindle 电池；捆绑合约手机；**一次性充电器、2G 设备**（阿联酋站独有）[SRC-AE-AMZ-G201744010] | 杀毒软件、安防摄像头、导航、含 GPS 的设备、蓝牙设备、报警器、婴儿监视器、智能手表 | GCC-L1-ELEC-001、GCC-L1-ELEC-002、GCC-L1-ELEC-003、GCC-L1-ELEC-004、AE-L1-ELEC-001 |
| 激光产品 | G201689020 | Class 2/2M/3R/3B/4 激光笔（含 303）、手持激光逗猫、含激光玩具、花园激光投影；激光舞台灯、监控红外照明激光（不论等级）[SRC-AE-AMZ-G201689020] | Class 1/1C/1M（激光翻页笔、非手持逗猫器等）——但电子页称便携激光一律禁售（冲突） | GCC-L1-LASER-001 |
| 监控设备 | G200164870 | 隐藏/伪装摄像头和录音设备、窃听器、SIM 卡窃听器、夜视镜、独立 GPS 追踪器、雷达干扰/探测器、键盘记录器、GSM 监听器与放大器 [SRC-AE-AMZ-G200164870] | 答录机、摄像机、婴儿监视器、安防摄像头、导航 | GCC-L1-SURVEIL-001 |
| 医疗器械 | G201744020 | 二手器械；需处方/专业监督的器械；助听器、处方眼镜、针头、带针注射器、导管、IUD、临床 IVD、性病自测、除颤器、输液泵、诊断超声、手术器械等 45 类 [SRC-AE-AMZ-G201744020] | 隐形眼镜（含无处方美瞳）、太阳镜、验孕/排卵试纸、避孕套、血压计袖带、尼古丁贴（须类目审核及执照） | GCC-L1-MEDDEV-001 |
| 珠宝 | G201744030 | 无合规戳记的纯贵金属/宝石；未用检定衡器称重的 1 g 以上贵金属；非金伯利进程毛坯钻 | 一般珠宝首饰 | GCC-L1-JEWEL-001 |
| 其他商品 | G201744040 | 广告型 Listing、个人数据、域名、游戏账号、房产、EAN 码、福袋、服务、未授权延保、伪造优惠券、数字下载/兑换码、电视订阅、体验日；盗版及学术/测试版软件；300 年以上文物；钓鱼铅坠；犯罪用印刷设备；>10 支装或非食品用笑气弹；“Washington Redskins”；未许可/专业用农药、三种新烟碱、毒药、管制化学品；植物与种子 [SRC-AE-AMZ-G201744040] | — | GCC-L1-OTHER-001、GCC-L1-OTHER-002、GCC-L1-OTHER-003、GCC-L1-PESTICIDE-001、GCC-L1-PLANTS-001 |
| 两性用品 | G201744060 | 色情、裸露内容、成人游戏、情趣玩具、性功能增强品、穿过的内衣 [SRC-AE-AMZ-G201744060] | 原包装密封避孕套；润滑剂（含延时/脱敏/紧致类）；按摩油 | GCC-L1-ADULT-001 |
| 烟草 | G201744070 | 一切含烟草产品；**含尼古丁**电子烟/电子水烟及烟弹烟油；金属/玻璃等材质烟斗；新奇打火机；尼古丁口香糖等 [SRC-AE-AMZ-G201744070] | 烟灰缸、雪茄剪、保湿盒、卷烟纸、卷烟机；无尼古丁电子烟未被明确禁止（不建议） | GCC-L1-TOBACCO-001、AE-L1-TOBACCO-001 |
| 武器 | G201744080 | 枪支、气枪/airsoft/BB/彩弹枪、仿真枪及仿真子弹、空包枪、零件弹药配件；弓箭弩；电击器、胡椒喷雾、催泪瓦斯、警棍、指虎、双节棍、手里剑、吹箭、鱼枪、弹弓（玩具除外）；弹簧刀、蝴蝶刀、猎刀、砍刀、剑、剁骨刀等；黑火药、手榴弹、军用武器 [SRC-AE-AMZ-G201744080] | 留色无刺激防身喷雾、非逼真玩具枪、调色刀、瑞士军刀、园艺剪、锯片、剪刀、磨刀器、封装剃刀（刃露 <2 mm）、成套餐刀 | GCC-L1-WEAPON-001、GCC-L1-WEAPON-002、GCC-L1-WEAPON-003、GCC-L1-WEAPON-004 |
| 酒类 | G201744410 | 酒精饮料、含酒精食品（酒心巧克力）、酒类许可证、酿酒套件 [SRC-AE-AMZ-G201744410] | 含化妆品级酒精的卸甲水、香水、洗手液、消毒湿巾、镜头清洁剂 | GCC-L1-ALCOHOL-001 |
| 赌博彩票 | G201744450 | 老虎机（含不能运行的与玩具老虎机）、彩票、刮刮卡、筹码、轮盘、21 点、塔罗牌 [SRC-AE-AMZ-G201744450] | 扑克牌、骰子、洗牌机 | GCC-L1-GAMBLING-001 |
| 服装 | G201744470 | 印裸露/毒品/冒犯内容的服装；二手服装鞋；真皮草；猪皮及受保护动物皮革 [SRC-AE-AMZ-G201744470] | 服装、鞋、包及配饰 | GCC-L1-ANIMAL-001/003、GCC-L1-OFFENSIVE-001 |
| 视频游戏 | G9NQF8P6KC9D4KNC | 阿联酋版页面多次抓取均只得到导航壳，内容未获取（沙特版要求 GAMR 批准版本） | — | 待核实 |
| 杀虫剂 | G6E2SRU9QL3E3CG5 | 未注册、限制使用、仅限专业使用的农药；作“安全、无毒、无害、纯天然”等误导宣称的农药 [SRC-AE-AMZ-G6E2SRU9QL3E3CG5] | 仅家用农药（气雾杀虫剂、电热蚊香） | GCC-L1-PESTICIDE-001、AE-L3-PESTICIDE-001 |
| 危险品 | G200164570 | 含 BPA 产品；含四氯化碳产品；专业/工业化学品；烟花爆竹、火药帽、照明弹、汽油；大肠杆菌培养物；氢氟酸、硝酸、红磷、铝热剂、氰化物、含氚产品；儿童充气颈圈、水上步行球、斗风筝线、军用防毒面具；废油；辐射污染物；含汞产品（碱锰纽扣电池 ≤25 mg 除外）；小强磁球套装；家电中的氟利昂；车辆气囊；牙签弩 [SRC-AE-AMZ-G200164570] | 有限数量的气雾、香水、指甲油等（须危险品审核） | GCC-L1-HAZMAT-001、GCC-L1-HAZMAT-002、GCC-L1-HAZMAT-003、GCC-L1-HAZMAT-004、GCC-L1-HAZMAT-005 |
| 人体部位 | G200164590 | 器官、组织、血液、精卵、遗骸、排泄物、墓碑 | 人发假发；合法医学用骨骼 | GCC-L1-HUMAN-001 |
| 冒犯性内容 | G200164670 | 宣扬仇恨暴力宗教不容、犯罪现场/尸检照片、灾难现场物品、偷录内容、色情裸露 | — | GCC-L1-OFFENSIVE-001 |
| 盗窃与开锁 | G200164850 | 去序列号商品、开锁工具/枪/卡、解码器、配钥匙设备、防盗扣解锁器、侧录器、遥控码抓取器、万能钥匙 [SRC-AE-AMZ-G200164850] | 空白钥匙坯 | GCC-L1-LOCKPICK-001 |
| 艺术品 | G200164390、G201279060 | 侵权艺术复制品 | 标明“reproduction”的复制品；有真伪证明的原作 | GCC-L1-ART-001 |
| 保修与服务 | G200164930 | 延保、退款保证、换新计划、服务合同、回购、投资服务（目前不接受申请） | — | GCC-L1-OTHER-001 |
| SIM 卡 / 话费充值 | GYCN5C8V4KBMD6X6、GELZ6765AURFYKNB | 仅持牌电信商可售且不接受申请——第三方卖家实际禁售 | — | AE-L1-SIM-001、AE-L1-RECHARGE-001 |
| 一次性用品 | GSBDE3Q56FKDUB6N | 一次性塑料餐具/盘/吸管/杯、一次性购物袋、泡沫餐盒、一次性包装 [SRC-AE-AMZ-GSBDE3Q56FKDUB6N] | 可重复使用品、阿联酋本地回收制品、出口用品、药袋、垃圾袋、食品薄卷袋 | AE-L1-SINGLEUSE-001、AE-L5-SUP-001 |
| 产品安全 Listing 限制 | GRLKLZ6WQ9R259LC | 化学：凝胶/液体燃料火盆、叠氮化钠、三氯乙酸；儿童：斗风筝线、琥珀/串珠出牙首饰与奶嘴链、儿童颈圈泳圈、带抽绳儿童上衣、床围、婴幼儿类目指尖陀螺、飞镖陀螺、婴儿自主喂食器、睡眠定位器、美人鱼尾泳衣、蘑菇牙胶/奶嘴、牙签弩、吸水珠（玩具用途）、加重睡眠用品；电子：角磨机链锯盘/套件、**圆柱形可充电锂电池**；生活：气囊、承重位电池加热衣物鞋垫、汽车座椅加热垫、布质儿童座椅、通用 CO 报警器、烟雾探测器、安全带、奶油发泡器；食品：疯蜂蜜 [SRC-AE-AMZ-GRLKLZ6WQ9R259LC] | 加热夹克电池在非承重位的不在此列 | GCC-L1-SAFETY-001、GCC-L1-SAFETY-002、GCC-L1-SAFETY-003、GCC-L1-SAFETY-004 |

## B. 审核与限售（L2）

**通用流程** [R:GCC-L2-APPROVAL-001] [SRC-AE-AMZ-G200333160]：在“添加商品”搜索 → 显示“Apply to sell”即需申请；“Show limitations”看具体要求。限制层级可以是 ASIN、品牌、品牌+类目、类目或子类目，一个商品可能需要多重审批。常备材料：180 天内采购发票、产品各面清晰照片、品牌授权书、安全证书；审核 2–7 个工作日；“Your account does not qualify”不可申诉。自 2024-09-30 起，若亚马逊要求合规文件，须提交并获批后才能创建新 Listing [SRC-AE-AMZ-GKCHRSWHXB5WZHAU]。

| 需审核的类目/商品 | 要求 | 申请路径 | 规则ID |
|---|---|---|---|
| 美妆个护 | 类目审核；原厂密封、标签合规 [SRC-AE-AMZ-G201743980] | 添加商品 > 申请销售 | GCC-L2-BEAUTY-001 |
| 食品饮料 | 类目审核；至少阿拉伯语+英语成分；符合 GSO 标准 [SRC-AE-AMZ-G201744000] | 同上 | GCC-L2-GROCERY-001 |
| 医疗器械 | 类目审核；宣称与厂家指引和法律一致 [SRC-AE-AMZ-G201744020] | 同上 | GCC-L2-MEDDEV-001 |
| 流媒体播放器 | 每型号寄样（不退）、硬件/系统/预装 APK 清单及来源、申请表 [SRC-AE-AMZ-G202183590] | 搜索 ASIN > Listing limitations apply > Request approval | GCC-L2-SMP-001 |
| 膳食补充剂 | 含膳食补充剂/类药品贸易范围的阿联酋营业执照，或药房/电子药房执照；减肥与性功能补充剂另须迪拜市政产品注册 [SRC-AE-AMZ-GFQWXF6XE3EAWTMP] | 账户状况 > 商品政策合规 | AE-L2-HEALTH-001 |
| 隐形眼镜及护理液 | 一般贸易/类药品营业执照，或药房、电子药房、眼镜店、医疗用品批发执照 | 同上 | AE-L2-HEALTH-002 |
| 医疗耗材与配件（含 IPL 脱毛仪、TENS、N95、验孕排卵试纸、体温计、吸奶器、轮椅等） | 保健品/类药品营业执照，或药房/电子药房/医疗用品批发执照 | 同上 | AE-L2-HEALTH-003 |
| 血糖仪/试纸、血压计、胆固醇检测、吸鼻器、雾化器、血氧仪 | 药房或电子药房执照 + MoHAP（现 EDE）产品注册 | 同上 | AE-L2-HEALTH-004 |
| OTC-G 药（Panadol、Brufen、Strepsils 等） | 保健品/类药品营业执照或药房执照 + MoHAP 注册（与受限页“禁售”冲突） | 同上 | AE-L1-DRUG-001 |
| “阿联酋版”笔记本 | 授权分销商发票（近 60 天 ≥10 台）；升级版标题含“Upgraded”、固定五点措辞、“1 Year Seller Warranty” [SRC-AE-AMZ-G9NT3CUVHJSBM4WM] | 添加商品 > 申请销售 | AE-L2-LAPTOP-001 |
| SIM 卡、话费充值、保修服务 | 不接受申请 | — | AE-L1-SIM-001、AE-L1-RECHARGE-001、GCC-L1-OTHER-001 |

## C. 按品类的平台合规资料（L3）

提交位置：除特别注明外均为「卖家平台 > 账户状况 > 商品政策合规性 > 提交合规信息或申诉（GC35Z63FGCUCUWXX）」，可单个或批量模板上传。文件须为原件、不得来自亚马逊“暂停验证实验室”，结果须为 Pass 或 N/A，说明与警示须为阿拉伯语（多数页面要求阿英双语）。

| 产品族 | 亚马逊要求的文件 / Listing 属性 | 规则ID |
|---|---|---|
| 儿童玩具（≤14 岁，含毛绒、装扮服、遥控/电动玩具） | GSO EN 71 / ASTM F963-23 / EN 71（电动加 IEC 62115）报告，须 SASO/EIAC/GAC/ILAC 认可实验室；属性：型号、品牌、强制警示、最小年龄（不低于报告）；图片：六面、警示、制造商/进口商、G-Mark [SRC-AE-AMZ-GKJRA3FRPRKVBJJS] | GCC-L3-TOYS-001 |
| 玩具警示属性 | gcc_toys_safety_directive_age_warning / _warning / _language 三字段，阿语或阿英双语 [SRC-AE-AMZ-G200686210] | AE-L3-TOYWARN-001 |
| 婴童用品（睡衣、高脚椅、摇椅秋千、婴儿床及床垫、背带、喂养用品、床护栏、牙胶、奶嘴、浮力辅助） | 对应 ASTM/EN/GSO 标准 PASS 报告 + 图片 [SRC-AE-AMZ-GECCHPZ45P4KVFN6] 等 | GCC-L3-INFANT-001 |
| 儿童汽车座椅 | UNECE R44-04/R129；型式认证或 ECAS CoC 或 GSO 证书；EQM/G-Mark/ECE 标签图片；布质座椅禁售 [SRC-AE-AMZ-G202137200] | AE-L3-CARSEAT-001 |
| 单独销售的锂电池 | ECAS 或 ISO 17025 的 IEC 62133-2/62619 报告 + UN38.3 + BTS；阿英说明书 [SRC-AE-AMZ-G7PAP6BJAUXRM4LH] | GCC-L3-LIBATT-001 |
| 手机/笔记本电池与充电器 | DoC 或认可实验室报告或 GCC/GSO/SASO/PCoC/ECAS 证书；CE/SQM/G-Mark 图片 [SRC-AE-AMZ-G202156120] | GCC-L3-CHARGER-001 |
| 移动电源、储能电站、应急启动电源 | ECAS 或 ISO 17025 报告（UL 2056/UL 2743 或 UAE.S IEC 62368-1 + 62133-2）+ UN38.3 [SRC-AE-AMZ-GSJFE8S8AES7F7VG] | GCC-L3-POWERBANK-001 |
| 锂电池家电 | IEC 60335-1 + 对应 Part 2 的 ECAS/ISO 17025 报告；电池 62133-2 + UN38.3 + BTS；详情页警示 [SRC-AE-AMZ-G8TM22XFM7WXCRDC] | GCC-L3-LIAPPLIANCE-001 |
| 电动出行设备及配件 | EN 15194/UL 2849/EN 17128/UL 2272 等 + UN38.3 + BTS，SASO/EIAC/GAC/ILAC 实验室；阿英说明书 [SRC-AE-AMZ-GMUW6CKYLY4AP8MK] | GCC-L3-EMOBILITY-001 |
| 插电电器 | G 型插头或永久固定转换插头 [SRC-AE-AMZ-G201416530] | AE-L3-PLUG-001 |
| 灯串 | DoC 或 ECAS（EN 60598-2-20）；CE 或 EQM 图片 [SRC-AE-AMZ-G202137960] | AE-L3-STRINGLIGHT-001 |
| 烟雾/CO/可燃气体报警器 | DoC/性能声明或阿联酋民防局 CoC；通用 CO 报警器与商用烟雾探测器禁售 [SRC-AE-AMZ-GXUCN5ZRJSYN9W9S] | AE-L3-ALARM-001 |
| 灭火器 | EC 型式检验或 GSO 证书或民防局 CoC [SRC-AE-AMZ-GS972L5FPTCLNYNR] | AE-L3-EXTINGUISHER-001 |
| 膳食补充剂 | GSO 9/2571/654/2209 等；六面包装图、说明书；DM/ZAD/其他酋长国食品注册证 [SRC-AE-AMZ-G201829010] | AE-L3-SUPPL-001 |
| 食品接触材料 | UAE.S/GSO 2231、1863、ISO 6486-2；“for food contact”或叉杯标；ECAS 或 EQM 证书 [SRC-AE-AMZ-GV8K5FS8ULTYFNZJ] | AE-L3-FCM-001 |
| 瓶装饮用水 | EQM 标志（3 年，每年监督）[SRC-AE-AMZ-GSSRCRM5TJJXU6RG] | AE-L3-WATER-001 |
| 家用洗涤剂 | 产品注册、认可实验室测试、阿/英不可撕标签、迪拜经营执照；不接受仅限专业用 [SRC-AE-AMZ-GNQ3RZSPZBMKKQJ3] | AE-L3-DETERGENT-001 |
| 农药/抗菌宣称商品 | 阿联酋注册（EDE/原 MOCCAE）；仅家用农药 [SRC-AE-AMZ-G6E2SRU9QL3E3CG5] | AE-L3-PESTICIDE-001 |
| 含沙儿童产品、日食眼镜、火灾逃生面罩 | 石棉 ISO 22262-1、ISO 12312-2、ASTM E2952-24/EN 403 报告 [SRC-AE-AMZ-G5Z5K2WQ3ZYG9E6F] [SRC-AE-AMZ-G202171660] [SRC-AE-AMZ-GGB3K8RJ6ZEB8QQ6] | GCC-L3-MISC-001 |
| 亚马逊设备兼容配件 | 名称与包装不得用亚马逊商标；未认证不得写“Works with Alexa” [SRC-AE-AMZ-G200500100] | GCC-L3-DEVACC-001 |

## D. FBA 与危险品（L4）

**FBA 禁运** [R:GCC-L4-FBA-001] [SRC-AE-AMZ-G201730840]：长度 >150 cm、重量 >30 kg 或周长 >3 m；在阿联酋不能合法销售的商品；酒精饮料（含无醇啤酒）；车辆轮胎；礼品卡等储值工具；附宣传单/价签/非亚马逊贴纸或预贴价；未按预处理要求处理；散装电池；破损/缺陷；标签未登记或不符；仿冒；1995 年第 14 号联邦法管制物质。违规库存可被拒收、销毁且不补偿。
**FBA 出口额外排除** [R:AE-L4-EXPORT-001]：药品、维生素、食品与补充剂、草本补充剂、除草杀虫产品、种子植物、烟花、医疗植入物、文物化石、需年龄分级/验证的商品、锁网手机等。

**危险品** [R:GCC-L4-DG-001] [R:GCC-L4-DG-002] [R:GCC-L4-DG-003] [SRC-AE-AMZ-G200164570] [SRC-AE-AMZ-G201003400]

| 情形 | 处理 |
|---|---|
| 第 1 类爆炸品、2.3 毒性气体、4.2 自燃、4.3 遇水危险、6.2 感染性、7 放射性（含离子式烟雾报警器）、>1 L 压缩气体、自动充气救生器材、>300 Wh 锂电池、>30 kg 受管制危险品 | FBA 禁止 |
| 2.1/2.2 气体（发胶、空气清新剂、丁烷罐、打火机、CO2 灭火器、氦气罐）、3 易燃液体（香水、指甲油、油漆、身体油）、4.1、5.1 氧化剂（牙齿美白、漂发剂、氯片）、5.2、8 腐蚀品（铅酸电池、除锈剂、马桶清洁剂）、9 杂项 | 仅以有限数量（陆运）入仓；须提交 SDS 或豁免表（管理危险品分类） |
| 锂电池 | “中东”只批准单电芯 ≤20 Wh（锂金属 ≤1 g）、电池组 ≤100 Wh（锂金属 ≤2 g）；须填电池属性、上传 UN38.3 测试摘要（2020-01-01 起）、电池豁免表，随设备锂离子电池须申报荷电状态 [R:GCC-L4-LIION-001] [SRC-AE-AMZ-G200383420] |
| 磁性材料（大音箱等） | 仅本土陆运 |
| 液体、喷雾、化妆品 | 依成分判定，常需 SDS |

## E. 当地法规（L5，按产品族）

**总体框架**：联邦《产品安全法》（2018 年第 10 号）适用所有上市产品，违者监禁和/或 50 万–300 万迪拉姆罚款 [R:AE-L5-PSL-001] [SRC-AE-GOV-PRODUCT-SAFETY-LAW-10-2018]。受技术法规管辖的产品须 MoIAT 的 ECAS 符合性证书（Emirates Conformity Assessment Scheme，阿联酋符合性评定体系），由 MoIAT 或其公告机构签发，申请人须持阿联酋营业执照，费用约 600+620+500 迪拉姆，通常 1 年有效；EQM（Emirates Quality Mark，阿联酋质量标志）执照 3 年 [R:AE-L5-ECAS-001] [SRC-AE-GOV-MOIAT-ECAS-SERVICE] [SRC-AE-GOV-CR-13-2021-FEES]。迪拜另有 Montaji 消费品注册，电商直邮同样适用 [R:AE-L5-MONTAJI-001] [SRC-AE-GOV-DM-ECOM-GU18]。

### 电子电器
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 低压电气产品 ECAS（委员会决议 2009/26）；海湾低压技术法规 BD-142004-01（内阁决议 2019/6 采纳）；UAE RoHS（内阁决议 2017/10，2018/2020 分阶段）；插头 UAE.S/BS 1363 | IEC 60335/62368 CB 报告 + EMC；RoHS 报告 | ECAS CoC；清单 2 家电 G-Mark | 阿英双语说明书；G 型插头 | MoIAT | AE-L5-LVE-001、AE-L5-ROHS-001、GCC-L5-LVE-001、AE-L3-PLUG-001、GCC-L1-ELEC-002 |
| 能效标签 EESL（UAE.S 5010 系列；冰箱 CR 1/2024；空调 CR 157/2025 自 2025-11-15、过渡 365 天；电视 5010-8） | 能效测试 | MoIAT 能效注册 | 1–5 星 RFID 标签 | MoIAT | AE-L5-EESL-001（部分二手来源） |

### 电池
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 未找到单独的电池/移动电源 MoIAT 方案（推定落入低压/RoHS）；亚马逊平台要求更严 | IEC 62133-2、UN38.3、BTS；移动电源 UL 2056 或 62368-1 | ECAS（亚马逊接受 ECAS 或 ISO 17025 报告） | 阿英说明书 | MoIAT | GCC-L3-LIBATT-001、GCC-L3-POWERBANK-001、GCC-L1-SAFETY-001 |

### 无线设备
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| TDRA 型号核准政策 V4（生效日期待核实）；短距离设备法规 V5（2.4 GHz ≤100 mW 等）；禁止 GSM 干扰器、放大器、扫描接收机 | 三级合格评定（DoC / ILAC 实验室报告 / 技术检查），500+200 迪拉姆，3 年有效 | TDRA 经销商注册（5,500 迪拉姆，5 年，境外公司可办）；每批进口须 TDRA 海关放行许可，仅发给阿联酋注册进口商 | 包装不可撕 + 设备上 TDRA 标志；**电商详情页须显示** | TDRA | AE-L5-TDRA-001、AE-L5-TDRA-002、AE-L5-TDRA-003、AE-L6-TDRA-001 |

### 灯具
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 内阁决议 2013/34 照明法规 | 能效与汞限值测试 | ECAS 注册 | 包装星级标签、阿语说明；未注册不得零售 | MoIAT | AE-L5-LIGHTING-001、AE-L3-STRINGLIGHT-001 |

### 儿童玩具
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 海湾儿童玩具技术法规 BD-131704-01（内阁决议 2015/22 采纳） | GSO EN 71 / ASTM F963 / EN 71（+IEC 62115） | G-Mark（GSO 公告机构）；路径（ECAS/G-Mark）待核实；迪拜 Montaji 可能要求注册 | 阿语警示与说明、进口商名称地址；网购前可见警示 | MoIAT / GSO / 迪拜市政 | GCC-L5-TOYS-001、AE-L5-CHILD-001、GCC-L3-TOYS-001、AE-L3-TOYWARN-001 |

### 婴童用品
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 婴幼儿护理用品（内阁决议 2019/34）；儿童约束系统（2017/27） | ASTM/EN/GSO 对应标准；UNECE R44/R129 | ECAS CoC | 阿语警示 | MoIAT | AE-L5-CHILD-001、GCC-L3-INFANT-001、AE-L3-CARSEAT-001、GCC-L1-SAFETY-002 |

### 食品接触材料
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 内阁决议 2015/20；UAE.S/GSO 2231、GSO 1863（塑料）、ISO 6486-2（陶瓷） | 迁移测试（报告 3 年内） | ECAS 或 EQM | “for food contact”或叉杯标 | MoIAT（迪拜注册要求有冲突说法） | AE-L5-FCM-001、AE-L3-FCM-001、GCC-L1-HAZMAT-002（BPA） |

### 化妆品
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 内阁决议 2014/18（UAE.S GSO 1943）；香水 2014/5；具医疗作用的化妆品归 EDE | GSO 1943 报告（3 年内）、自由销售证明 | ECAS（670+620 迪拉姆，每证 ≤25 SKU）+ 销售地酋长国注册（迪拜 Montaji） | 阿语标签；动物源成分可能需清真 | MoIAT / 迪拜市政 / EDE | AE-L5-COSMETIC-001、AE-L5-MONTAJI-001、GCC-L1-COSMETIC-001/002 |

### 个护健康电器
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 低压电气 + RoHS；IPL、TENS 等被亚马逊归为医疗耗材 | IEC 60335-2-23 等 | ECAS；亚马逊要求阿联酋执照 | 阿英说明书 | MoIAT / EDE | AE-L5-LVE-001、AE-L2-HEALTH-003、GCC-L3-LIAPPLIANCE-001 |

### 医疗器械
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 2024 年第 38 号联邦法令（2025-01-02 生效，EDE 统一监管）；电子药房仅限持证药房 | — | EDE（原 MoHAP）产品注册；亚马逊要求药房执照 | 不得作未批准宣称；广告须 EDE 批准 | EDE | AE-L5-EDE-002、AE-L2-HEALTH-002、AE-L2-HEALTH-003、AE-L2-HEALTH-004、GCC-L1-MEDDEV-001 |

### 农药与抗菌宣称
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 2020 年第 10 号联邦农药法；抗菌/防霉宣称即视为农药 | 有效性/安全数据 | EDE 农药注册（600 迪拉姆/年，5 年）；消毒剂另有 EDE 医疗保健产品许可；迪拜 Montaji 注册杀生物剂 | 禁“无毒、安全”宣称 | EDE / 迪拜市政 | AE-L5-PESTICIDE-001、AE-L3-PESTICIDE-001、AE-L5-EDE-001、GCC-L1-PESTICIDE-001 |

### 化学品
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 洗涤剂方案（内阁决议 2024/96，取代 2014/3）；油漆清漆（2016/6）；润滑油（2024/28）；AdBlue（2026/108） | 重金属、pH、表面活性剂等 | ECAS；迪拜 Montaji | 阿/英不可撕标签、警示 | MoIAT / 迪拜市政 | AE-L3-DETERGENT-001、AE-L5-AUTO-001、GCC-L1-HAZMAT-002 |

### 刀具武器
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 2013 年第 5 号武器法；武器弹药烟花进口须国防/内政部门许可 | — | — | — | 国防部 / 内政部 | GCC-L1-WEAPON-001、GCC-L1-WEAPON-002、GCC-L1-WEAPON-003、GCC-L1-WEAPON-004、AE-L6-CUSTOMS-002 |

### 激光
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 内阁决议 2013/41 激光产品 | IEC 60825-1 | ECAS | 等级标签、阿英说明书 | MoIAT | AE-L5-LASER-001、GCC-L1-LASER-001 |

### 无人机
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 2022 年第 26 号联邦法令；内阁决议 2023/110 无人机方案；迪拜 2020 年第 4 号法；GCAA 休闲飞行规则（禁搭载摄像头）；GCAA 安全决定 2026-03（暂停所有无人机飞行） | TDRA 核准 + 测试证书 | MoIAT 产品状态声明（200 迪拉姆）+ 每台标签卡；迪拜 DCAA 进口/销售许可 | 标签卡 | MoIAT / TDRA / GCAA / DCAA | AE-L5-DRONE-001 |

### 汽配
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 汽车备件（内阁决议 2018/12）；新轮胎 ECAS + RFID；翻新/二手轮胎（迪拜禁止进口） | — | ECAS | 轮胎 RFID | MoIAT | AE-L5-AUTO-001、GCC-L1-AUTO-001、AE-L6-CUSTOMS-001 |

### 家具木制品
未找到阿联酋针对家具/人造板甲醛的强制技术法规（MoIAT 2022 年受监管产品表未列）。适用通用《产品安全法》与消费者保护法标签要求 [R:AE-L5-PSL-001] [R:AE-L5-CPL-001]。列入待核实。

### 纺织服装
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 纺织品技术法规（内阁决议 2019/54，ECAS） | 成分、偶氮等（细节未核实） | ECAS（适用范围待核实） | 成分、洗护、原产国标签 | MoIAT | AE-L5-TEXTILE-001（unverified）、GCC-L1-SAFETY-002（儿童抽绳） |

### 珠宝
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 贵金属戳记与计量（MoIAT，具体法规未核实）；毛坯钻石须金伯利进程（2004 年第 13 号联邦法） | — | — | 纯度戳记 | MoIAT / 金伯利办公室 | GCC-L1-JEWEL-001 |

### 宠物
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 兽医医疗产品（2025 年第 21 号联邦法令，2026-01-01 起，EDE 注册）；宠物食品属食品注册；活体动物进口 MOCCAE 许可 | — | EDE 兽药注册；MOCCAE 许可 | — | EDE / MOCCAE | AE-L5-PESTICIDE-001、AE-L6-MOCCAE-001、GCC-L1-ANIMAL-002 |

### 植物种子
亚马逊阿联酋站禁售活体植物、鲜花与种子，仅人造花草可售 [R:GCC-L1-PLANTS-001] [SRC-AE-AMZ-G201737480]；进口须 MOCCAE 许可与植物检疫证书（二手来源，待核）[R:AE-L6-MOCCAE-001]。

### 食品保健品
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 2015 年第 10 号联邦食品安全法；UAE.S GSO 9 标签；清真（内阁决议 2014/10）；补充剂受 EDE（膳食补充剂）与迪拜市政（保健补充剂）双重管理 | — | ZAD / 迪拜 FIRS / 阿布扎比 FIEMIS；EDE 医疗保健产品许可（5,000 迪拉姆，5 年） | 阿语（亚马逊要求阿英双语成分） | 气候变化与环境部 / 迪拜市政 / ADAFSA / EDE / MoIAT | AE-L5-FOOD-001、AE-L5-EDE-001、AE-L5-HALAL-001、GCC-L5-FOODLABEL-001、AE-L3-SUPPL-001 |

### 烟草电子烟
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| UAE.S 5030（内阁决议 2019/5）：尼古丁 ≤20 mg/ml、儿童防开、阿英警示 >50%、18+；烟草控制法 2009/15；100% 消费税 | 每口味浓度测试；设备 CB/电池/RoHS/EMC | ECAS；进口须 MoIAT 许可 | 阿英警示 | MoIAT | AE-L5-ECIG-001（亚马逊仍禁售含尼古丁产品：GCC-L1-TOBACCO-001） |

### 酒类
亚马逊阿联酋站禁售酒类 [R:GCC-L1-ALCOHOL-001]；当地酒类进口须迪拜警察等许可 [R:AE-L6-CUSTOMS-002] [SRC-AE-GOV-UAE-CUSTOMS]。

### 成人用品
亚马逊禁售情趣玩具等 [R:GCC-L1-ADULT-001]；阿联酋海关禁止违背伊斯兰教义及道德的出版物与物品入境 [R:AE-L6-CUSTOMS-001]。

### 二手商品
亚马逊禁售二手汽配、二手服装鞋、二手医疗器械、已开封化妆品与健康产品 [R:GCC-L1-AUTO-001] [R:GCC-L1-COSMETIC-001] [R:GCC-L1-MEDDEV-001]；迪拜海关禁止进口二手/翻新轮胎 [R:AE-L6-CUSTOMS-001]；《产品安全法》不适用于二手产品 [SRC-AE-GOV-PRODUCT-SAFETY-LAW-10-2018]。

### 一次性塑料（环保）
联邦第 380/2022 号部长决议：2024-01-01 禁一次性购物袋；2026-01-01 禁一次性杯盖、餐具（含筷子）、盘、吸管搅拌棒、泡沫餐盒及 <50 微米的任何材质一次性袋（2026 年清单来自二手新闻转述官方公告，待核）；迪拜按 2023 年第 124 号决议分阶段执行，罚款 200–2,000 迪拉姆 [R:AE-L5-SUP-001] [SRC-AE-GOV-MOCCAE-SUP-GUIDE-2025] [SRC-AE-GOV-DM-SUP-FINAL-PHASE] [SRC-AE-S3-GULFNEWS-SUP-2026]。

### 电动代步、燃气器具与个人防护
| 适用法规 | 认证/测试 | 注册/备案 | 标签 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 电动自平衡车（委员会决议 2016/12，IEC 60335-2-114）；LPG 气瓶及附件（2014/81）；个人防护装备（内阁决议 2016/3）与健康防护用品（2020/83） | 对应 IEC/EN 报告；电池 IEC 62133 + UN38.3 | ECAS CoC | 阿英说明书 | MoIAT | AE-L5-EMOBILITY-001、AE-L5-GAS-001、AE-L5-PPE-001、GCC-L3-EMOBILITY-001 |

### 进口与清关（L6）
- 阿联酋禁止入境：毒品、盗版内容、伪钞、巫术物品、违背伊斯兰教义的出版物和艺术品、赌博工具；迪拜另禁尼龙渔网、活猪、二手/翻新轮胎、辐射污染物、槟榔叶 [R:AE-L6-CUSTOMS-001] [R:GCC-L6-CUSTOMS-001] [SRC-AE-GOV-UAE-CUSTOMS] [SRC-AE-GOV-DUBAI-CUSTOMS-PROHIBITED]。
- 须许可进口：动植物/农药（MOCCAE）、武器烟花（国防/内政）、药品器械（EDE）、出版物（媒体主管部门）、核能产品（FANR）、无线设备（TDRA）、酒类（迪拜警察）、化妆品/电子烟/新轮胎（MoIAT）、食品化妆品（迪拜市政）、毛坯钻石（金伯利办公室）[R:AE-L6-CUSTOMS-002]。
- 无线设备每批须 TDRA 海关放行许可，仅发给阿联酋注册进口商 [R:AE-L6-TDRA-001] [R:AE-L5-TDRA-002]；种子、植物、活体动物须 MOCCAE 许可（二手来源，待核）[R:AE-L6-MOCCAE-001]。

## F. 标签、语言与本地责任人

| 要求 | 内容 | 来源 / 规则 |
|---|---|---|
| 阿拉伯语信息 | 电商供应商须以阿拉伯语提供产品信息、规格及合同/付款/保修条款；面向消费者的数据、广告、合同用阿语（可附他语） | 消费者保护法 2020/15 第 25、26 条 [SRC-AE-GOV-CPL-15-2020] [R:AE-L5-CPL-001] |
| 包装标签 | 品名成分、“Made in + 原产国”、出口国、生产商或进口商名称地址、生产与保质期、储存使用条件、误用风险、需特别注意人群 | 内阁决定 2023/66 第 3 条 [SRC-AE-GOV-CD-66-2023] [R:AE-L5-CPL-001] |
| 说明书 | 低压电器、空调、激光、电子烟设备、锂电池、电动出行设备等须阿语+英语说明书 | [SRC-AE-GOV-MOIAT-CAD-REGULATED-SHEET] [SRC-AE-AMZ-G7PAP6BJAUXRM4LH] |
| 食品 | 至少阿拉伯语+英语成分（亚马逊），UAE.S GSO 9 | [SRC-AE-AMZ-G201744000] [R:GCC-L5-FOODLABEL-001] |
| 玩具 | 阿拉伯语警示，Listing 填 GCC 玩具警示属性 | [R:AE-L3-TOYWARN-001] [R:GCC-L5-TOYS-001] |
| 合格标志 | ECAS/EQM 新版标志（2025-04 更新，过渡 6/12 个月）；TDRA 标志须显示在电商页面 | [R:AE-L5-MARKS-001] [R:AE-L5-TDRA-003] |
| 本地责任人 | ECAS 申请人须持阿联酋营业执照；TDRA 商业清关只发给阿联酋注册进口商；迪拜电商主体须在迪拜/指定自贸区持照；健康类目要求阿联酋药房/贸易执照；EDE 许可须本地代理 | [R:AE-L5-ECAS-001] [R:AE-L6-TDRA-001] [R:AE-L5-MONTAJI-001] [R:AE-L5-EDE-001] |

## G. 2024–2026 变化与生效日期

| 日期 | 变化 | 影响的产品 | 规则ID | 来源 |
|---|---|---|---|---|
| 2024-01-01 | 联邦禁止一次性购物袋（含可降解）；迪拜同步 | 购物袋、包装袋 | AE-L5-SUP-001、AE-L1-SINGLEUSE-001 | SRC-AE-GOV-MOCCAE-SUP-GUIDE-2025 |
| 2024-09-02 | 洗涤剂新方案（内阁决议 2024/96），零售须 ECAS 注册 | 洗涤剂 | AE-L3-DETERGENT-001 | SRC-AE-GOV-MOIAT-LAWS-LIST |
| 2024-09-30 | 亚马逊要求的合规文件须获批后才能创建新 Listing | 所有受合规要求的商品 | GCC-L2-APPROVAL-001 | SRC-AE-AMZ-GKCHRSWHXB5WZHAU |
| 2025-01-02 | 2024 年第 38 号联邦法令生效，EDE 统一监管药品、器械、补充剂、医疗作用化妆品；2025 年底 MoHAP 服务移交 | 健康类 | AE-L5-EDE-001、AE-L5-EDE-002 | SRC-AE-GOV-FDL-38-2024 |
| 2025-04-09 | MoIAT 更新 12 个合格标志（进口 6 个月、在售 12 个月过渡） | ECAS/EQM 产品 | AE-L5-MARKS-001 | SRC-AE-GOV-MOIAT-MARKS-2025 |
| 2025-11-15 | 空调能效新标准 UAE.S 5010-1/-5:2025（365 天过渡） | 空调 | AE-L5-EESL-001 | SRC-AE-S3-TUV-EESL（二手来源，待核） |
| 2026-01-01 | 一次性塑料禁令第二阶段（杯盖、餐具、盘、吸管、泡沫盒、<50 微米袋）；迪拜最终阶段 | 一次性餐饮用品 | AE-L5-SUP-001 | SRC-AE-GOV-DM-SUP-FINAL-PHASE、SRC-AE-S3-GULFNEWS-SUP-2026 |
| 2026-01-01 | 兽医医疗产品法（2025 年第 21 号联邦法令）生效 | 宠物药、驱虫 | AE-L5-PESTICIDE-001 | SRC-AE-GOV-EDE-HOME |
| 2026-03-27 | GCAA 安全决定 2026-03 第 2 版：暂停所有无人机飞行 | 无人机 | AE-L5-DRONE-001 | SRC-AE-GOV-GCAA-SD-2026-03 |
| 待核实 | TDRA 型号核准政策 V4 生效（核验未在原文找到 2026-05-01 这一日期）：三级评定、费用调整、电商页面须显示合格标志、每批进口许可 | 所有无线设备 | AE-L5-TDRA-001、AE-L5-TDRA-002、AE-L5-TDRA-003、AE-L6-TDRA-001 | SRC-AE-GOV-TDRA-TA-POLICY-V4 |

## H. 来源清单

以下为本文与关联规则（GCC.yaml 中适用阿联酋站的规则 + AE.yaml）引用的全部来源，按级别排序。快照位于 policy/snapshots/AE/ 与 policy/snapshots/SA/。

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
| SRC-AE-AMZ-G201416530 | Electrical Goods Requirements: Plugs and Sockets | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G201416530 |
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
| SRC-AE-AMZ-G202137960 | String lights | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G202137960 |
| SRC-AE-AMZ-G202156120 | Device batteries and chargers | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G202156120 |
| SRC-AE-AMZ-G202162990 | Personal flotation devices | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G202162990 |
| SRC-AE-AMZ-G202171660 | Eclipse glasses and solar viewing filters | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G202171660 |
| SRC-AE-AMZ-G202183590 | Streaming Media Players | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G202183590 |
| SRC-AE-AMZ-G2HSXA2KM59YX5AT | Cylindrical rechargeable lithium batteries | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G2HSXA2KM59YX5AT |
| SRC-AE-AMZ-G2JX2MAWJ27DWAY6 | Compliance Reference | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G2JX2MAWJ27DWAY6 |
| SRC-AE-AMZ-G5NGAYYZAY559SCZ | Children's sleepwear | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G5NGAYYZAY559SCZ |
| SRC-AE-AMZ-G5Z5K2WQ3ZYG9E6F | Sand based children's products | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G5Z5K2WQ3ZYG9E6F |
| SRC-AE-AMZ-G6E2SRU9QL3E3CG5 | Pesticides and insecticides | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G6E2SRU9QL3E3CG5 |
| SRC-AE-AMZ-G76DURDA6ZW48DX7 | High chairs and hook-on chairs | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G76DURDA6ZW48DX7 |
| SRC-AE-AMZ-G7HM69VDEMRW7TPE | Electronic mobility (e-mobility) accessories | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G7HM69VDEMRW7TPE |
| SRC-AE-AMZ-G7PAP6BJAUXRM4LH | Lithium batteries | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G7PAP6BJAUXRM4LH |
| SRC-AE-AMZ-G8KZHJBNC2647269 | Whipped cream dispensers | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G8KZHJBNC2647269 |
| SRC-AE-AMZ-G8TM22XFM7WXCRDC | Lithium battery powered home appliances | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G8TM22XFM7WXCRDC |
| SRC-AE-AMZ-G9NT3CUVHJSBM4WM | UAE Version Laptop Products and Upgraded Laptop Products | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/G9NT3CUVHJSBM4WM |
| SRC-AE-AMZ-GDPSRCGVBFSFY78H | Baby teething products | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GDPSRCGVBFSFY78H |
| SRC-AE-AMZ-GECCHPZ45P4KVFN6 | Cribs, cradles, bassinets, and bedside sleepers | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GECCHPZ45P4KVFN6 |
| SRC-AE-AMZ-GELZ6765AURFYKNB | Prepaid Mobile Recharges | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GELZ6765AURFYKNB |
| SRC-AE-AMZ-GFEUQFB9X4YWFVXD | Water beads | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GFEUQFB9X4YWFVXD |
| SRC-AE-AMZ-GFQMECECLTJCUE3H | Battery-operated heated apparel and insoles | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GFQMECECLTJCUE3H |
| SRC-AE-AMZ-GFQWXF6XE3EAWTMP | Listing restrictions on healthcare products | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GFQWXF6XE3EAWTMP |
| SRC-AE-AMZ-GGB3K8RJ6ZEB8QQ6 | Fire and smoke masks | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GGB3K8RJ6ZEB8QQ6 |
| SRC-AE-AMZ-GGLAL34T93UJQ6KD | Infant Slings and Soft Carriers | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GGLAL34T93UJQ6KD |
| SRC-AE-AMZ-GKCHRSWHXB5WZHAU | Creating new selection with compliance requirements | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GKCHRSWHXB5WZHAU |
| SRC-AE-AMZ-GKJRA3FRPRKVBJJS | Children's toys | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GKJRA3FRPRKVBJJS |
| SRC-AE-AMZ-GMUW6CKYLY4AP8MK | Electronic mobility (e-mobility) devices | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GMUW6CKYLY4AP8MK |
| SRC-AE-AMZ-GNQ3RZSPZBMKKQJ3 | Detergents Regulation | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GNQ3RZSPZBMKKQJ3 |
| SRC-AE-AMZ-GRLKLZ6WQ9R259LC | Product safety listing restrictions | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GRLKLZ6WQ9R259LC |
| SRC-AE-AMZ-GS972L5FPTCLNYNR | Fire extinguishers | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GS972L5FPTCLNYNR |
| SRC-AE-AMZ-GSBDE3Q56FKDUB6N | Single-use products | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GSBDE3Q56FKDUB6N |
| SRC-AE-AMZ-GSJFE8S8AES7F7VG | Portable power supplies | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GSJFE8S8AES7F7VG |
| SRC-AE-AMZ-GSSRCRM5TJJXU6RG | Water Bottle Regulation | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GSSRCRM5TJJXU6RG |
| SRC-AE-AMZ-GT8V6T7U8GZZK3SU | Car seat heating pads | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GT8V6T7U8GZZK3SU |
| SRC-AE-AMZ-GUFQGCVJXHSYBL2Z | Infant bouncers, swings, and rockers | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GUFQGCVJXHSYBL2Z |
| SRC-AE-AMZ-GUG6JJCDN6YYQYJP | Infant and toddler feeding products | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GUG6JJCDN6YYQYJP |
| SRC-AE-AMZ-GV8K5FS8ULTYFNZJ | Food Contact Materials Regulation | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GV8K5FS8ULTYFNZJ |
| SRC-AE-AMZ-GX9BGE7LAFRWAFHF | Pacifiers and pacifier clips | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GX9BGE7LAFRWAFHF |
| SRC-AE-AMZ-GXPFG3RRZB9WFPJE | Portable bed rails | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GXPFG3RRZB9WFPJE |
| SRC-AE-AMZ-GXUCN5ZRJSYN9W9S | Smoke and carbon gas alarms | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GXUCN5ZRJSYN9W9S |
| SRC-AE-AMZ-GYCN5C8V4KBMD6X6 | SIM Cards | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.ae/help/hub/reference/external/GYCN5C8V4KBMD6X6 |
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
| SRC-SA-AMZ-G202183590 | Streaming Media Players | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G202183590 |
| SRC-SA-AMZ-G2HSXA2KM59YX5AT | Cylindrical rechargeable lithium batteries | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G2HSXA2KM59YX5AT |
| SRC-SA-AMZ-G2JX2MAWJ27DWAY6 | Compliance Reference | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G2JX2MAWJ27DWAY6 |
| SRC-SA-AMZ-G7PAP6BJAUXRM4LH | Lithium batteries | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/G7PAP6BJAUXRM4LH |
| SRC-SA-AMZ-GKJRA3FRPRKVBJJS | Children's toys | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/GKJRA3FRPRKVBJJS |
| SRC-SA-AMZ-GRLKLZ6WQ9R259LC | Product safety listing restrictions | S1 | jina_reader | 2026-10-10 | https://sellercentral.amazon.sa/help/hub/reference/external/GRLKLZ6WQ9R259LC |
| SRC-AE-GOV-ADAFSA-FOOD | ADAFSA Food safety (FIEMIS food product registration, Abu Dhabi) | S2 | webfetch | 2026-10-10 | https://www.adafsa.gov.ae/en/work/food-safety/Pages/default.aspx |
| SRC-AE-GOV-CD-66-2023 | Cabinet Decision No. 66 of 2023 - Executive Regulation of the Consumer Protection Law (excerpt) | S2 | webfetch | 2026-10-10 | https://www.moet.gov.ae/documents/20121/0/CabinetDecision_66_2023_pdf.pdf/01f05bd9-a15b-b353-b297-f834152e1c3a?t=1715053584650 |
| SRC-AE-GOV-CPL-15-2020 | Federal Law No. 15 of 2020 on Consumer Protection | S2 | webfetch | 2026-10-10 | https://www.moet.gov.ae/documents/20121/0/Law_15_2020_pdf.pdf/b676fd26-275c-3652-e949-8b3663e7bd79?t=1715057123879 |
| SRC-AE-GOV-CR-123-2024 | Cabinet Resolution No. 123 of 2024 approving GCC lists of prohibited and restricted goods | S2 | search_snippet | 2026-10-10 | https://uaelegislation.gov.ae/en/legislations/2710 |
| SRC-AE-GOV-CR-13-2021-FEES | Cabinet Resolution No. 13 of 2021 on MoIAT service fees (ECAS / EQM / energy label fees) | S2 | webfetch | 2026-10-10 | https://moiat.gov.ae/-/media/site/moiat/document/laws-legislation/2021/25_1_2021.ashx |
| SRC-AE-GOV-DHA-TELEHEALTH | DHA Standards for Telehealth Services (Appendix 6 OTC delivery by licensed pharmacies) | S2 | webfetch | 2026-10-10 | https://dha.gov.ae/uploads/012023/Standards%20for%20Telehealth%20Services2023158613.pdf |
| SRC-AE-GOV-DM-ECOM-GU18 | Dubai Municipality Technical Guidelines for Consumer Products E-Commerce (DM-HSD-GU18-ECOM2 V2.0, 2024) | S2 | jina_reader | 2026-10-10 | https://dmpmedia.dm.gov.ae/uploads/2024/07/DM-HSD-GU18-ECOM2_Technical-Guidelines-for-Consumer-Products-E-Commerce_V2.pdf |
| SRC-AE-GOV-DM-FIRS-GUIDE | Dubai Municipality Food Import and Re-Export System (FIRS) guide | S2 | webfetch | 2026-10-10 | https://dmpmedia.dm.gov.ae/uploads/2023/12/IRS-eng.pdf |
| SRC-AE-GOV-DM-GU100-CPIE2 | Dubai Municipality Technical Guidelines for Consumer Products Import and Re-export (DM-HSD-GU100-CPIE2 V2.0, 2025) | S2 | webfetch | 2026-10-10 | https://dmpmedia.dm.gov.ae/uploads/2025/05/DM-HSD-GU100-CPIE2_Guidelines-for-Consumer-Products-Import-and-Re-export-V.2.pdf |
| SRC-AE-GOV-DM-SERVICES | Dubai Municipality services (Register Consumer Products - Montaji; import permit; advertising permit) | S2 | webfetch | 2026-10-10 | https://www.dm.gov.ae/dubai-municipality-services/ |
| SRC-AE-GOV-DM-SUP-FINAL-PHASE | Dubai to enforce final phase of single-use plastic ban from 2026 | S2 | jina_reader | 2026-10-10 | https://www.dm.gov.ae/dubai-to-enforce-final-phase-of-single-use-plastic-ban-from-2026/ |
| SRC-AE-GOV-DUBAI-CUSTOMS-PAX-GUIDE | Dubai Customs Passenger Customs Guide v6-2025 | S2 | webfetch | 2026-10-10 | https://www.dubaicustoms.gov.ae/en/OpenData/Publications/PassengerCustomsGuide.pdf |
| SRC-AE-GOV-DUBAI-CUSTOMS-PROHIBITED | Dubai Customs - Prohibited and Restricted Goods | S2 | jina_reader | 2026-10-10 | https://www.dubaicustoms.gov.ae/en/mobile/Pages/ProhibitedandRestrictedGoods.aspx |
| SRC-AE-GOV-DUBAI-LAW-4-2020-DRONES | Dubai Law No. 4 of 2020 Regulating Unmanned Aircraft in the Emirate of Dubai | S2 | webfetch | 2026-10-10 | https://dlp.dubai.gov.ae/Legislation%20Reference/2020/Law%20No.%20(4)%20of%202020%20Regulating%20Unmanned%20Aircraft%20in%20the%20Emirate%20of%20Dubai.html |
| SRC-AE-GOV-DUBAI-MEDIA-SUP-124-2023 | Dubai Executive Council Resolution No. 124 of 2023 on single-use products (Dubai Media Office) | S2 | webfetch | 2026-10-10 | https://mediaoffice.ae/en/news/2023/december/31-12/hamdan-bin-mohammed-issues-resolution |
| SRC-AE-GOV-ECIG-CR-5-2019 | Cabinet Resolution No. 5 of 2019 - UAE.S 5030:2018 Electronic Nicotine Products mandatory | S2 | webfetch | 2026-10-10 | https://moiat.gov.ae/-/media/site/moiat/document/laws-legislation/2019/5---2019.ashx |
| SRC-AE-GOV-EDE-HEALTHCARE-MA | EDE Issuance of Marketing Authorization for a Healthcare Product | S2 | jina_reader | 2026-10-10 | https://www.ede.gov.ae/en/w/issuance-of-marketing-authorization-for-a-healthcare-product |
| SRC-AE-GOV-EDE-HOME | Emirates Drug Establishment (EDE) | S2 | webfetch | 2026-10-10 | https://www.ede.gov.ae |
| SRC-AE-GOV-EDE-PESTICIDE-REG | EDE Pesticide registration service (تسجيل مبيد) | S2 | webfetch | 2026-10-10 | https://www.ede.gov.ae/ar/w/%D8%AA%D8%B3%D8%AC%D9%8A%D9%84-%D9%85%D8%A8%D9%8A%D8%AF |
| SRC-AE-GOV-EXCISE-TAX | u.ae - Excise tax (incl. electronic smoking devices and liquids) | S2 | webfetch | 2026-10-10 | https://u.ae/en/information-and-services/finance-and-investment/taxation/excise-tax |
| SRC-AE-GOV-FDL-38-2024 | Federal Decree-Law No. 38 of 2024 on Medical Products, Pharmacy Profession and Pharmaceutical Establishments | S2 | webfetch | 2026-10-10 | https://www.ede.gov.ae/documents/d/ede/-38-2024-pdf |
| SRC-AE-GOV-GCAA-LAWS | GCAA Laws (Federal Decree-Law No. 26 of 2022 on unmanned aircraft) | S2 | webfetch | 2026-10-10 | https://www.gcaa.gov.ae/en/Pages/aboutgcaa/Laws.aspx |
| SRC-AE-GOV-GCAA-SD-2026-03 | GCAA Safety Decision 2026-03 Issue 02 - temporary suspension of drone operations | S2 | jina_reader | 2026-10-10 | https://www.gcaa.gov.ae/en/epublication/EPublications/Safety%20Decisions/2026/2019-SAFETY%20DECISION%202026-03%20-%20TEMPORARY%20SUSPENSION%20OF%20UNMANNED%20AIRCRAFT%20SYSTEMS%20DRONES%20LIGHT%20SPORT%20AIRCRAFT%20BALLOON%20AND%20SPECIALISED%20OPERATIONS%20WITHIN%20UAE%20AIRSPACE%20-%20ISSUE%2002.pdf |
| SRC-AE-GOV-LIGHTING-CR-34-2013 | Cabinet Resolution No. 34 of 2013 - UAE Regulation for Lighting Products | S2 | webfetch | 2026-10-10 | https://moiat.gov.ae/-/media/site/moiat/document/laws-legislation/2013/34-2013.ashx |
| SRC-AE-GOV-MOCCAE-CITES | MOCCAE Import of a species listed in CITES Appendices | S2 | search_snippet | 2026-10-10 | https://www.moccae.gov.ae/en/services/import-of-cites-listed-species |
| SRC-AE-GOV-MOCCAE-IMPORT-PERMIT | MOCCAE Import permit (agricultural consignments, seeds, plants, live animals) | S2 | search_snippet | 2026-10-10 | https://www.moccae.gov.ae/en/services/import-permit |
| SRC-AE-GOV-MOCCAE-PESTICIDE-REG | MOCCAE Registration of pesticides (linked from Amazon pesticides page; service since transferred to EDE) | S2 | search_snippet | 2026-10-10 | https://www.moccae.gov.ae/en/services/registration-accreditation/registration-of-pesticides.aspx |
| SRC-AE-GOV-MOCCAE-SUP-GUIDE-2025 | MOCCAE reveals guide on single-use plastic ban (Ministerial Resolution 380/2022) | S2 | jina_reader | 2026-10-10 | https://www.moccae.gov.ae/en/media-center/news/2/1/2025/ministry-of-climate-change-and-environment-reveals-details-of-comprehensive-guide-outlining |
| SRC-AE-GOV-MOIAT-CAD-REGULATED-SHEET | MoIAT List of technical requirements for regulated products (CAD regulated sheet, 2022) | S2 | webfetch | 2026-10-10 | https://moiat.gov.ae/-/media/site/moiat/document/services-user-manual/cad-regulated-sheet.ashx |
| SRC-AE-GOV-MOIAT-COSMETICS-CARD | MoIAT regulation card - Cosmetics and personal care products (Cabinet Resolution 18/2014, UAE.S GSO 1943) | S2 | webfetch | 2026-10-10 | https://eservices.moiat.gov.ae/backend/api/v1.1/UploadAttachment/GetAttachmentByRecordId?recordAttachmentId=649245&download=true |
| SRC-AE-GOV-MOIAT-DRONE-STATUS | Issue Product Status Statement for Drones | S2 | jina_reader | 2026-10-10 | https://moiat.gov.ae/en/services/issue-product-status-statement-for-drones |
| SRC-AE-GOV-MOIAT-ECAS-SERVICE | Issue Conformity Certificates for Regulated Products (ECAS) | S2 | jina_reader | 2026-10-10 | https://moiat.gov.ae/en/services/issue-conformity-certificates-for-regulated-products |
| SRC-AE-GOV-MOIAT-EQM-LICENSE | Issuance of license certificate to use National Conformity Marks (EQM) | S2 | webfetch | 2026-10-10 | https://moiat.gov.ae/en/services/issuance-of-license-certificate-to-use-national-conformity-marks |
| SRC-AE-GOV-MOIAT-HALAL | MoIAT Halal programme (Cabinet Resolution 10/2014 UAE System for Control of Halal Products) | S2 | webfetch | 2026-10-10 | https://moiat.gov.ae/en/programs/halal |
| SRC-AE-GOV-MOIAT-LAWS-LIST | MoIAT Laws and Legislation (list of technical regulations / Cabinet Resolutions) | S2 | webfetch | 2026-10-10 | https://moiat.gov.ae/en/about-us/laws-and-legislation |
| SRC-AE-GOV-MOIAT-MARKS-2025 | MoIAT updates national conformity marks (April 2025) | S2 | webfetch | 2026-10-10 | https://moiat.gov.ae/en/media-center/news/2025/04/09/conformity-marks-2025 |
| SRC-AE-GOV-PRODUCT-SAFETY-LAW-10-2018 | Federal Law No. 10 of 2018 on Product Safety | S2 | webfetch | 2026-10-10 | https://moiat.gov.ae/-/media/site/moiat/document/laws-legislation/2018/18_2018.ashx |
| SRC-AE-GOV-ROHS-CR-10-2017 | Cabinet Resolution No. 10 of 2017 - UAE Regulation to Control Hazardous Materials in Electrical and Electronic Devices (UAE RoHS) | S2 | webfetch | 2026-10-10 | https://moiat.gov.ae/-/media/site/moiat/document/laws-legislation/2017/uae-regulation-to-control-hazardous-materials-in-electrical-and-electronic-devices.ashx |
| SRC-AE-GOV-TDRA-CUSTOMS-PERMIT | TDRA Customs release permit for telecommunication devices | S2 | webfetch | 2026-10-10 | https://tdra.gov.ae/en/Services/customs-release-permit-for-telecommunication-devices |
| SRC-AE-GOV-TDRA-DEALER-REG | TDRA Register Telecom Supplier (Dealer Registration) | S2 | jina_reader | 2026-10-10 | https://tdra.gov.ae/en/Services/register-telecom-supplier |
| SRC-AE-GOV-TDRA-SRD-REG | TDRA Regulations - Ultra-Wide Band and Short Range Devices V5.0 (2023) | S2 | webfetch | 2026-10-10 | https://tdra.gov.ae/-/media/About/regulations-and-ruling/EN/UWB-and-SRD-Regulations-50.ashx |
| SRC-AE-GOV-TDRA-TA-POLICY-V4 | TDRA Policy - Type Approval Regime for Telecommunications Equipment V4.0 (effective 2026-05-01) | S2 | jina_reader | 2026-10-10 | https://tdra.gov.ae/-/media/About/Type-approval-PDF/Type-Approval-Policy-V4-EN.ashx |
| SRC-AE-GOV-TDRA-TA-SERVICE | TDRA Register and approve telecommunication equipment (type approval service) | S2 | webfetch | 2026-10-10 | https://tdra.gov.ae/en/Services/register-and-approve-telecommunication-equipment |
| SRC-AE-GOV-TDRA-TYPE-APPROVAL | TDRA Type Approval (incl. prohibited devices list) | S2 | jina_reader | 2026-10-10 | https://tdra.gov.ae/en/About/tdra-sectors/telecommunication/departments/technology-development-affairs-department/type-approval |
| SRC-AE-GOV-TOBACCO-PROVISIONS | u.ae - Tobacco provisions (Federal Law 15/2009 on Tobacco Control) | S2 | webfetch | 2026-10-10 | https://u.ae/en/information-and-services/health-and-fitness/Policy-and-governance/tobacco-provisions |
| SRC-AE-GOV-UAE-CUSTOMS | u.ae - Customs clearance (banned and restricted goods) | S2 | jina_reader | 2026-10-10 | https://u.ae/en/information-and-services/visiting-and-exploring-the-uae/Tourist-services-and-information/Customs-clearance |
| SRC-GCC-GOV-GSO-GMARK | GSO - Gulf Conformity Mark (G-Mark) | S2 | webfetch | 2026-10-10 | https://www.gso.org.sa/en/conformity/gcc-conformity-mark/ |
| SRC-GCC-GOV-GSO-TOYS-TR | GCC Technical Regulation on Children Toys BD-131704-01 (Issue 2, 2013-05-08) | S2 | webfetch | 2026-10-10 | https://www.gso.org.sa/wp-content/uploads/2018/10/GSO_TechnicalRegulationForChildrenToys.pdf |
| SRC-SA-GOV-SASO-LVE-LIST2 | GSO List No. 2 (TC143307-01) - low voltage products requiring G-Mark (Annex 4) | S2 | webfetch | 2026-10-10 | https://www.saso.gov.sa/ar/Laws-And-Regulations/Technical_regulations/SiteAssets/Pages/regulation3/tc143307-01-ar-en.pdf |
| SRC-SA-GOV-SASO-LVE-TR | Gulf Technical Regulation for Low Voltage Electrical Equipment and Appliances BD-142004-01 (SASO-hosted) | S2 | webfetch | 2026-10-10 | https://www.saso.gov.sa/en/Laws-And-Regulations/Technical_regulations/Documents/Gulf-Technical-Regulation-for-Low-Voltage-Electrical-Equipment-and-Appliances-BD-142004-01.pdf |
| SRC-SA-GOV-SASO-TOYS-TR | GCC Technical Regulation on Children Toys BD-131704-01 (SASO-hosted) | S2 | webfetch | 2026-10-10 | https://www.saso.gov.sa/ar/Laws-And-Regulations/Technical_regulations/Documents/bd-131704-01.pdf |
| SRC-SA-GOV-SFDA-FOOD-CLEARANCE | SFDA Conditions and Requirements for Food Clearance (2026-08) | S2 | webfetch | 2026-10-10 | https://www.sfda.gov.sa/en/regulations/17763 |
| SRC-SA-GOV-ZATCA-CUSTOMS-LAW | GCC Common Customs Law (ZATCA copy) - prohibited and restricted goods definitions | S2 | webfetch | 2026-10-10 | https://zatca.gov.sa/ar/RulesRegulations/Taxes/Documents/customs%20law.pdf |
| SRC-SA-GOV-ZATCA-PROHIBITED | ZATCA - Prohibited goods (travellers), Minister of Finance Decision 2597 | S2 | jina_reader | 2026-10-10 | https://zatca.gov.sa/ar/RulesRegulations/Taxes/Pages/customs-individual/Prohibited-goods.aspx |
| SRC-AE-S3-GULFNEWS-SUP-2026 | Gulf News - UAE to ban more single-use plastic items from January 1 (2026) | S3 | webfetch | 2026-10-10 | https://gulfnews.com/uae/government/uae-to-ban-more-single-use-plastic-items-from-january-1-1.500381533 |
| SRC-AE-S3-MONDAQ-CD66 | Mondaq - Seller beware - new Executive Regulations under UAE Consumer Protection Law | S3 | webfetch | 2026-10-10 | https://www.mondaq.com/seller-beware-the-impact-of-new-executive-regulations-under-the-uae's-consumer-protection-law/1367028 |
| SRC-AE-S3-TUV-EESL | TÜV Rheinland - UAE MoIAT Energy Efficiency Standardization & Labeling (EESL) | S3 | webfetch | 2026-10-10 | https://www.tuv.com/market-access-services/en/certification-filter/uae-moiat-energy-efficiency-standardization-labeling-(eesl).html |
| SRC-AE-S3-UAES-5030-TEXT | UAE.S 5030:2018 Electronic Nicotine Products (standard text hosted by Tobacco Control Laws) | S3 | webfetch | 2026-10-10 | https://assets.tobaccocontrollaws.org/uploads/legislation/United%20Arab%20Emirates/United-Arab-Emirates-UAE.S-50302018.pdf |
| SRC-AE-S3-UL-ROHS | UL - Middle East four new hazardous substances banned January 2020 (UAE RoHS) | S3 | webfetch | 2026-10-10 | https://www.ul.com/news/middle-east-four-new-hazardous-substances-will-be-banned-january-2020 |
| SRC-SA-S3-UL-SABER-GMARK | UL - SABER requires association of local suppliers with G-Mark (2020) | S3 | webfetch | 2026-10-10 | https://ul.com/news/saudi-arabia-saber-e-platform-requires-mandatory-association-local-suppliers-g-mark |

共 162 个来源（S1 102，S2 54，S3 6）。

## 待核实/冲突

**亚马逊页面之间的冲突**
1. **非处方药（OTC/GSL）**：受限商品页（G201743990）列为禁售；“医疗健康商品 Listing 限制”页（GFQWXF6XE3EAWTMP）允许持阿联酋药房/类药品贸易执照且已在 MoHAP 注册的卖家销售 OTC-G 药。规则按“无执照即禁售、conflicting”处理 [R:AE-L1-DRUG-001]。
2. **激光**：电子类目页（G201744010）称便携激光（激光笔、激光投影、含激光玩具）一律禁售；激光页（G201689020）允许 Class 1/1C/1M [R:GCC-L1-LASER-001]。
3. **锂电池 FBA 上限**：危险品页（2018 年更新）把 100–300 Wh“中型锂电池”描述为可运；锂电池要求页的分区表对“Middle East”标为 Rejected。规则采用较新的锂电池页 [R:GCC-L4-LIION-001]。
4. **尼古丁贴**：医疗器械页列为允许示例（需审核），烟草页又把“其他尼古丁产品”列为禁售 [R:GCC-L1-TOBACCO-001]。
5. **烟雾/CO 报警器**：产品安全 Listing 限制页禁售“烟雾探测器”和“通用 CO 报警器”，报警器合规页又给出 DoC/民防局 CoC 的合规路径；“generic”的含义未定义 [R:AE-L3-ALARM-001]。

**亚马逊页面未能获取或口径不清**
6. **视频游戏页（G9NQF8P6KC9D4KNC）阿联酋版**多次抓取（en_AE、zh_CN、等待渲染）只得到导航壳，内容未知；沙特版要求 GAMR 批准版本，阿联酋是否有类似要求（如国家媒体委员会/媒体理事会分级）未核实。
7. **普通厨刀、折叠刀**：武器页允许清单只列“与叉勺成套的餐刀”，单独厨师刀、折叠刀是否可售不清楚 [R:GCC-L1-WEAPON-003]。
8. **“含双酚 A（BPA）的产品”**禁售范围（是否限于婴幼儿用品）页面未说明 [R:GCC-L1-HAZMAT-002]。
9. **CBD**：帮助页未单列，按“非法药物/大麻”条款推定禁售 [R:GCC-L1-DRUG-002]。
10. **无尼古丁电子烟**：阿联酋站只明确禁售含尼古丁电子烟 [R:AE-L1-TOBACCO-001]。
11. **无醇啤酒**：FBA 禁运清单明确列入；是否可自配送销售未说明 [R:GCC-L4-FBA-001]。
12. **汽车电瓶/轮胎“回收（take back）”义务**：汽摩页提及，未找到阿联酋对应法规原文 [R:GCC-L1-AUTO-001]。
13. 合规参考体系中多数页面引用美国/欧盟标准（16 CFR、ASTM、EN），这是亚马逊平台口径，不等于阿联酋当地法定要求。

**当地法规未能读到官方原文或仅有二手来源**
14. **ECAS CoC 有效期 1 年**仅见检测机构资料和费用表“每年”措辞 [R:AE-L5-ECAS-001]；MoIAT 受监管产品表为 2022 年版本，可能已有新增。
15. **玩具合格评定路径**（ECAS、G-Mark 或二者）未读到内阁决议 2015/22 原文；迪拜市政对玩具是否需 Montaji 注册说法不一；食品接触材料是否需 Montaji 注册亦有冲突（GU100 称暂不需要，服务页称可注册）[R:AE-L5-CHILD-001] [R:AE-L5-MONTAJI-001]。
16. **纺织品技术法规（内阁决议 2019/54）**仅见标题，适用范围未核实 [R:AE-L5-TEXTILE-001]。
17. **能效标签**各部分标准号（5010-2/-4/-6/-7）和空调新规（CR 157/2025）日期来自搜索摘要和 TÜV（二手来源，待核）[R:AE-L5-EESL-001]。
18. **一次性塑料第二阶段（2026-01-01）清单**来自海湾新闻转述 MOCCAE 公告；第 380/2022 号部长决议原文（uaelegislation.gov.ae 拒绝访问）未读 [R:AE-L5-SUP-001]。
19. **无人机**：截至 2026-10-10 未找到 GCAA 解除 2026-03 号暂停决定的官方文件；有博客称 2026-06-30 恢复商业飞行（低可信度）[R:AE-L5-DRONE-001]。
20. **TDRA 禁止设备清单文件**未在网上找到；“2G 设备禁售”的当地依据（2G 关网）仅见二手资料 [R:AE-L1-ELEC-001]；旧式“TRA REGISTERED No/DEALER No”标签格式未在官方文件中找到。
21. **海关**：2024 年第 123 号内阁决议（GCC 统一禁限清单）附件未读；激光笔、象牙犀角、偶像雕像、猪肉制品（活猪以外）等是否在官方禁止清单中未核实 [R:AE-L6-CUSTOMS-001]。
22. **补充剂监管路径**：迪拜市政“保健补充剂”注册与 EDE“膳食补充剂”上市许可如何分流未找到官方规则；2024 年第 38 号联邦法令实施细则（第 41 条非药房渠道 OTC）未找到 [R:AE-L5-EDE-001]。
23. **MOCCAE** 进口许可费用、CITES 许可、动物产品许可费仅见搜索摘要（网站防火墙拦截）[R:AE-L6-MOCCAE-001]。
24. **内阁决定 2023/66 第 40 条**（网站展示合格标志、平台对第三方卖家负责）仅见律所文章 [R:AE-L5-CPL-001]。
25. **家具/人造板、贵金属戳记**的阿联酋强制法规编号未找到 [R:GCC-L1-JEWEL-001]。
26. **手机充电器、移动电源、自行车、头盔**未找到单独 MoIAT 方案，推定落入低压/RoHS 或 PPE 范围 [R:AE-L5-LVE-001]。
27. **USB-C 统一接口**：未找到阿联酋（MoIAT/TDRA）强制要求（沙特已实施，见 SA.md）。
28. **其他酋长国**（沙迦、阿布扎比）消费品注册制度未调研；本文的地方注册以迪拜为主。
