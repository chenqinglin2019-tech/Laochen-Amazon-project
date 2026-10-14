# 英国站（amazon.co.uk）禁限售与合规要求

> 规则包版本：draft · 调研日期：2026-10-10 · 本文描述亚马逊平台政策和当地法规要求，不构成法律意见。
> 每条结论后用 [SRC-…] 标注来源（见 rules/sources/UK.yaml），用 [R:规则ID] 关联机读规则（rules/sites/UK.yaml，共 192 条）。
> 来源级别：S1 亚马逊官方 · S2 政府官方 · S3 二手。只有 S3 支撑的结论标注「（二手来源，待核）」。

**先看这几条（英国站与美国/欧盟站差异最大的地方）**

| 要点 | 说明 | 规则 |
|---|---|---|
| 刀具白名单 | 英国站只允许厨刀（须 FBA + 年龄核验）、剪刀、小型非锁定折刀（≤3 英寸）等少数刀具，匕首、战术刀、砍刀、剑、美工刀、肉斧等一律禁售 | [R:UK-L1-WEAPON-002] [R:UK-L2-KNIFE-001] |
| 18650 等圆柱锂电池 | 圆柱形可充电锂电芯（18650、21700、14500…）及“含这类电池的产品”禁售 | [R:UK-L1-LIION-001] |
| 激光笔 | 所有便携式激光产品（激光笔、逗猫激光、激光投影器）禁售，不论等级 | [R:UK-L1-ELEC-003] |
| 英标插头 | 电器必须配 BS 1363 三脚插头或永久封闭式转换插头，附送转换器不算 | [R:UK-L1-ELEC-001] [R:UK-L5-PLUG-001] |
| 真皮草、二手服装 | 任何真皮草及二手服装鞋类禁售 | [R:UK-L1-ANIMAL-002] [R:UK-L1-CLOTH-001] |
| 烟油/一次性电子烟 | 所有电子烟油、预灌装烟弹、一次性电子烟、尼古丁袋禁售；2025-06-01 起一次性电子烟全英违法 | [R:UK-L1-TOBACCO-001] [R:UK-L5-VAPE-001] |
| 酒类须英国设立 | 酒类只能自发货、须年龄核验，且卖家设立国必须在英国 | [R:UK-L2-ALCOHOL-001] |
| EPR 由亚马逊代缴 | 非英国设立卖家的包装 EPR 和（2025-08-12 起）WEEE 义务由亚马逊代为申报缴费，并按类目收年服务费，不可退出 | [R:UK-L5-PACK-001] [R:UK-L5-WEEE-001] |
| FBA 进口单号 | 非英国卖家进口货入 FBA，60 天内须补交 IEN，否则无法建新货件 | [R:UK-L4-FHDDS-001] |
| PSTI | 2024-04-29 起联网产品须满足密码/漏洞披露/更新期三项要求并随附符合性声明 | [R:UK-L5-PSTI-001] |

---

## A. 禁售清单（L1）

总则：亚马逊英国“类目、商品和内容限制”总览页列出 19 个类目子页；违规会被下架、暂停或永久移除销售权限；把禁售商品改为“缺货”并不算合规 [SRC-UK-AMZ-G201743940]。另有《产品安全禁售表》集中列出因安全原因禁售的商品 [SRC-UK-AMZ-GRLKLZ6WQ9R259LC]。

| 类别 | 亚马逊页面（G 编号） | 禁止销售的典型商品 | 例外/允许销售的情况 | 规则ID |
|---|---|---|---|---|
| 受限原产地 | G201743940、G201575280 | 原产/生产于朝鲜、古巴、伊朗、克里米亚、所谓 DNR/LNR 地区的商品；土库曼斯坦棉花 | — | UK-L1-ORIGIN-001 |
| 活体动物 | G201743950 | 活体动物 | 活贝类、蠕虫、昆虫，本地瓢虫幼虫 | UK-L1-ANIMAL-001 |
| 真皮草 | G201743950、G201744470 | 任何动物的真皮草或含真皮草商品（养殖或野生） | 确为人造毛的商品（亚马逊给出鉴别方法） | UK-L1-ANIMAL-002 |
| 濒危及特定动物制品 | G201743950、G201744470 | 海豹/鳍足类、猫狗、鳄鱼、大象（象牙）、袋鼠、珊瑚、海龟、蛇和多数爬行动物皮、鲨鱼鲸豚、未鞣制兽皮、野鸟蛋、英国产貂油 | 非濒危动物做成的合规食品 | UK-L1-ANIMAL-003 |
| 虐待动物用品 | G201743950 | 电击/静电狗项圈（含电子围栏）、内刺项圈、针对脊椎动物的粘鼠板、捕猫器、斗鸡刀、虐待动物媒体 | 电子捕鼠器、宠物芯片套件 | UK-L1-ANIMAL-004 |
| 养殖动物饲料 | G201743950 | 含活虫/未授权动物蛋白的饲料 | — | UK-L1-ANIMAL-005 |
| 汽车 | G201743960 | 整车、二手汽配、车牌 | 全新汽配、轮胎、电池、机油、儿童安全座椅、头盔、反光背心、三角牌 | UK-L1-AUTO-001 |
| 汽车安全件 | G201743960、GRLKLZ6WQ9R259LC | 安全气囊及气体发生器、安全带/延长带/卡扣、安全带警报消除器、汽车座椅加热垫 | — | UK-L1-AUTO-002 |
| 儿童车载约束 | G201743960、GRLKLZ6WQ9R259LC | 织物式儿童约束系统、通用 ISOFIX 转接器 | 合规 ECE R44/R129 座椅（见 C 节） | UK-L1-AUTO-003 |
| 电助力改装套件 | G201743960 | 超过 25 km/h 或 250 W 的电动自行车改装套件 | 合规套件（须 EN 15194/17128 报告） | UK-L1-AUTO-004 |
| 货币与礼品卡 | G201743970 | 法币（含收藏）、外国在流通货币、伪币伪邮票及制造设备、礼品卡/储值码/比特币/金银条、股票证券 | 无法币地位的收藏币（须披露真伪品相）、明示的仿制币/仿制邮票、按重量出售的贵金属 | UK-L1-CURRENCY-001 |
| 化妆品状态 | G201743980 | 开封/二手、过期、非原厂密封、去除批号码、tester/非卖品、分装香水、假货 | — | UK-L1-COSM-001 |
| 仿香 | G201743980 | “inspired by/similar to/dupe”仿品牌香水及对照表 | — | UK-L1-COSM-002 |
| 化妆品违禁成分 | G201743980 | 汞、氢醌、维 K1、kohl/surma、比马前列素睫毛液、三氯卡班>0.2%、曲酸>1%、牙齿美白>0.1% H2O2、蛇油、非天然 henna、濒危物种成分、动物测试产品、仅限专业使用的产品 | 外用且不来自花/果穗的 CBD 化妆品 | UK-L1-COSM-003、UK-L1-COSM-004 |
| 药品 | G201743990 | POM、P 药、含阿司匹林/扑热息痛/布洛芬/aloxiprin 的 GSL 药、未许可药品与草药/顺势疗法、POM-V 兽药 | 不含上述成分的 GSL 人用药、AVM-GSL 兽药；NFA-VPS/POM-VPS 须审核 | UK-L1-DRUG-001 |
| 管制药物与兴奋剂 | G201743990、GRLKLZ6WQ9R259LC | 大麻/THC/合成大麻素、legal highs、mad honey、GBL/GHB/DNP、麻黄碱、Poppers、WADA 禁用物质、生长激素、HCG、能量鼻吸粉 | — | UK-L1-DRUG-002 |
| 吸毒用具 | G201743990、G201744070 | 用于非法药物的烟斗/bong、合成尿液等规避药检产品 | 烟灰缸、雪茄剪、卷烟纸、卷烟机 | UK-L1-DRUG-003 |
| 补充剂超量/掺假 | G201743990 | 烟酸>50 mg、烟酰胺>500 mg、维 D>100 μg/日；掺假减肥/增肌/壮阳品（数百具名品牌）；抗癌、解酒、驱虫排毒宣称 | 合规食品补充剂（须审核，见 B 节） | UK-L1-SUPP-001、UK-L1-SUPP-002 |
| 过期与非零售 | G201744000、G201743990 | 过期、开封、非原厂密封、“not for retail sale”的食品/补充剂/药品 | — | UK-L1-EXPIRED-001 |
| CBD 与大麻 | GDB9KV3NJYRES4AQ | 可食用 CBD（油、含片、烟油、喷雾）、所有大麻软糖、全谱提取物 | 外用大麻/CBD 产品；大麻籽油食品；FSA 名单内且经亚马逊批准的 CBD 食品 | UK-L1-CBD-001 |
| 食品 | G201744000 | 鹅肝、未授权新型食品（神秘果、BHB、酮酯、覆盆子酮、淫羊藿、葛根）、卡瓦、锗、膨润土、迷你果冻杯、高氰杏仁核、BVO/丁烷等违禁添加剂、侵犯地理标志、形似毒品的糖果 | 合规食品 | UK-L1-FOOD-001 |
| 插头 | G201744010、G201416530 | 非英标插头电器（含附送转换器、Schuko） | 只配 USB 线；剃须刀/牙刷用 BS 4573 或 CEE 7/16；同时附英标与非英标可换插头 | UK-L1-ELEC-001 |
| 无线电 | G201744010 | 信号干扰器、手机信号放大器、FRS/GMRS、>0.5 W PMR446、非法频段对讲机、军用频段、带录音或 1.2 GHz 偷拍摄像头 | FM 发射器、Ofcom 许可设备、合规 DECT | UK-L1-ELEC-002 |
| 激光 | G201744010 | 激光笔、激光手电、宠物激光、303 激光、激光投影器 | — | UK-L1-ELEC-003 |
| 侵权/规避设备 | G201744010 | 盗版流媒体盒、解码器、游戏破解芯片/烧录卡、模拟器、智能卡编程器、里程表调校器、AdBlue 模拟器 | 正版光盘、PS3/4 硬盘扩容 | UK-L1-ELEC-004 |
| 电池 | G201744010、G7HVAWY2HGLXVVHU | NiCd 电池、汞>0.0005%/镉>0.002% 电池、Kindle 电池 | 应急报警、医疗、无绳工具用便携电池（镉豁免） | UK-L1-ELEC-005 |
| 圆柱锂电 | G7PAP6BJAUXRM4LH、G2HSXA2KM59YX5AT | 18650/21700/14500/16340/26650 等圆柱可充锂电芯、电池包、含此类电池的产品、任何 ≥3.0 V 圆柱可充电池 | — | UK-L1-LIION-001 |
| 联网设备信息 | G201744010 | Listing 披露默认密码等危及安全的信息 | — | UK-L1-ELEC-006 |
| 光源 | G201744010 | 磨砂白炽灯；15–100 W 指定瓦数透明白炽灯；非 R7/G9/GU5.3/G4/GY6.35 卤素灯 | 上述五种灯座卤素灯 | UK-L1-ELEC-007 |
| 手机 | G201744010 | 仅 3G 或 2G+3G 无 4G/5G 手机、合约机 | 锁网手机 | UK-L1-ELEC-008 |
| 节能器 | G201744010 | 插电式节能器/省油器 | — | UK-L1-ELEC-009 |
| 烟花 | G7HVAWY2HGLXVVHU、G201744040 | F2/F3/F4 烟花、T2/P2 烟火制品、户外仙女棒、黑火药 | F1、T1、P1（仅自发货 + 年龄核验） | UK-L1-HAZ-001 |
| BPA | G7HVAWY2HGLXVVHU | 含 BPA 的食品接触产品（含婴儿入口产品） | — | UK-L1-HAZ-002 |
| 放射/臭氧层 | G7HVAWY2HGLXVVHU | 放射性产品（无授权）、铝热剂、四氯化碳 | 经英国主管机关授权且上架前提供证明 | UK-L1-HAZ-003 |
| F-gas | G7HVAWY2HGLXVVHU | GWP≥150 HFC 移动空调/冰箱/技术气雾剂/信号喇叭、制冷剂罐、人造雪/亮片喷雾 | 分体空调/热泵（须安装商证明） | UK-L1-HAZ-004 |
| 化学品 | G7HVAWY2HGLXVVHU、G201744040 | 专业用途化学品、毒物法附表 1A 毒物、未 REACH 注册化学品、叠氮化钠 | — | UK-L1-HAZ-005 |
| 爆炸物前体 | G7HVAWY2HGLXVVHU | 丙酮>35%、H2O2>12%、硝酸>3%、硫酸>15%、铝/镁粉≥100 g、高锰酸钾≥1 kg 等 | 洗甲水、含氮<16% 冰袋、<30% 硝基燃料 | UK-L1-HAZ-006 |
| 汞 | G7HVAWY2HGLXVVHU | 液态汞、水银体温计、汞柱血压计 | — | UK-L1-HAZ-007 |
| 强磁 | G7HVAWY2HGLXVVHU | ≤31.75 mm 磁球/磁方块玩具、作为玩具的稀土磁铁、BISS 外 >100 颗稀土磁铁 | — | UK-L1-HAZ-008 |
| 召回 | G7HVAWY2HGLXVVHU | 制造商或各国政府召回、RAPEX 严重风险产品 | — | UK-L1-HAZ-009 |
| 风筝线/防毒面具 | G7HVAWY2HGLXVVHU | 斗风筝线、磨料风筝线、古董军用防毒面具 | — | UK-L1-HAZ-010 |
| 不安全产品 | G7HVAWY2HGLXVVHU | 无 CE/UKCA 的新玩具和电器；未经专家检测的二手/翻新电器 | — | UK-L1-UNSAFE-001 |
| 珠宝 | G201744030、G9MJWDA8TTMZFAXE | 无检验印记贵金属、>1 g 未经检定衡器称重、非金伯利毛坯钻、重金属超标首饰 | 获审核后销售 | UK-L1-JEWEL-001 |
| 医疗器械 | G201744020 | 处方/专业/二手器械、植入物、影像设备、手术器械、针头、助听器、隐形眼镜（含美瞳）、处方眼镜、牙科专业器械与隐形牙套、皮肤填充剂、IUD、临床 IVD 等 | 血氧仪、体温计、无夸大宣称的血压计、伤口敷料、妊娠/DNA 检测、纹身穿孔套件、AED 等 | UK-L1-MED-001 |
| 伪医疗/宣称 | G201744020 | Rife 机、Zapper、奥根、胎儿性别预测、无创测糖手表；“MHRA approved/NHS supplier/clinically validated”血压计 | — | UK-L1-MED-002 |
| 其他 | G201744040 | 服务、数字码、账号、域名、邮件名单、房产、EAN 码、盲盒福袋、体验日、电视订阅、未授权保修 | — | UK-L1-OTHER-001 |
| 其他 | G201744040 | 人体器官（真发假发除外）、赃物、侵犯隐私物品、犯罪用印刷设备、>300 年文物 | — | UK-L1-OTHER-002 |
| 农药 | G201744040 | 未许可/专业用农药、POPs 农药、吡虫啉/噻虫嗪/噻虫胺 | 有 HSE 授权的业余用途产品 | UK-L1-PEST-001 |
| 生物杀灭剂 | G201744040、G57NEMV9CTC3W6F3 | 无 GB BPR 授权（或有效豁免）的消毒、驱虫、灭鼠等产品 | 已授权并合规标注的产品 | UK-L1-BIOCIDE-001 |
| 植物与泥炭 | G201744040 | 不合规植物种子、有害植物、园艺泥炭 | 合规种子植物（活植物不能 FBA） | UK-L1-PLANT-001 |
| 一次性塑料 | G201744040 | 塑料餐具、盘、搅拌棒、气球棒、EPS 餐盒杯、软塑料吸管、>100 根吸管装、塑料棉签、氧化降解塑料 | 医疗器械用途 | UK-L1-OTHER-003 |
| 竹纤维塑料 | G201744040 | 含未授权物质的塑料食品接触材料（竹纤维/玉米淀粉/稻壳+塑料） | — | UK-L1-OTHER-004 |
| 笑气 | G201744040、G8KZHJBNC2647269 | 笑气气罐/气弹、奶油发泡器 | — | UK-L1-OTHER-005 |
| 争议商品 | G201744040 | 邦联旗、Washington Redskins 商品、钓鱼铅坠 | — | UK-L1-OTHER-006 |
| 纹身墨水 | G201744040 | 含禁用物质或标签不全的纹身/半永久墨水 | — | UK-L1-OTHER-007 |
| 冒犯性内容 | GQKVFBUXQJ4FR2G9 | 仇恨、暴力、恐怖组织、种族歧视、灾难、儿童性化商品 | 图书音像另有内容准则 | UK-L1-OFFENSIVE-001 |
| 成人 | G201744060 | R18 色情、仿真/儿童样性爱娃娃、与人体部位相连的性玩具、二手内衣 | 原厂密封避孕套、润滑剂、性玩具、非色情成人媒体 | UK-L1-ADULT-001 |
| 烟草电子烟 | G201744070、GZTAPBBRLZ3EU96H | 烟草、尼古丁产品（含尼古丁袋）、所有烟油、预灌装烟弹/烟杆、一次性电子烟、>2 ml 烟仓、未通报电子烟、水烟、草本烟、新奇打火机 | 不含烟油的已注册电子烟设备及 HnB 设备（见 B 节） | UK-L1-TOBACCO-001 |
| 吸引未成年人的电子烟 | G201744070 | 卡通、类食品外观、未满 25 岁形象等 | — | UK-L1-TOBACCO-002 |
| 枪支 | G201744080 | 枪支、气枪、Airsoft/BB/彩弹枪、发令枪、仿真/去功能化枪、消音器、弹药配件 | 不逼真的玩具枪；非弹药类 BB 弹 | UK-L1-WEAPON-001 |
| 刀具 | G201744080、G201730840 | 白名单以外的刀具（匕首、蝴蝶刀、弹簧刀、战术刀、僵尸刀、砍刀、剑、肉斧、美工刀、狩猎/潜水刀、非园艺斧等） | 调色刀、修枝工具、剪刀、≤3 英寸非锁定折刀、模型刀、餐具套装餐刀、封装剃刀片；厨刀须 FBA + 年龄核验 | UK-L1-WEAPON-002 |
| 其他武器 | G201744080 | 电击器、胡椒喷雾、甩棍、指虎、双节棍、飞镖、战术笔、吹箭、鱼枪、弩/弹弓（玩具除外） | 仅染色不含刺激物的防身喷雾、非武器类弓 | UK-L1-WEAPON-003 |
| 博彩 | G201744450 | 彩票、刮刮卡、非持牌卖家的老虎机 | 持牌卖家老虎机、无功能/玩具老虎机 | UK-L1-GAMBLE-001 |
| 服装 | G201744470 | 二手服装和鞋 | 全新服装鞋包 | UK-L1-CLOTH-001 |
| 酒类 | G201744410 | ≥70% ABV 酒、酒类许可证、违反 CAP 守则的 Listing | 其他酒类须审核且自发货 | UK-L1-ALCOHOL-001 |
| 婴童安全禁售表 | GRLKLZ6WQ9R259LC、GUG6JJCDN6YYQYJP | 睡眠定位器、加重睡眠产品、床围、自助喂食器、防吐奶/喂奶枕、免手扶奶瓶架 | — | UK-L1-CHILD-001 |
| 出牙/安抚 | GRLKLZ6WQ9R259LC | 琥珀/串珠牙胶首饰、串珠奶嘴链夹、蘑菇形牙胶/安抚奶嘴、感统咀嚼项链 | 合规牙胶（见 C 节） | UK-L1-CHILD-002 |
| 儿童水上/服装/秋千 | GRLKLZ6WQ9R259LC | 颈圈泳圈、美人鱼尾泳衣、带抽绳儿童上装、治疗/感统/瑜伽秋千 | — | UK-L1-CHILD-003 |
| 高风险玩具 | GRLKLZ6WQ9R259LC、GKJRA3FRPRKVBJJS | 吸水珠、牙签弩、飞镖形指尖陀螺、婴幼儿类目指尖陀螺 | — | UK-L1-CHILD-004 |
| 儿童口罩 | GDQHATC3NQPXKLGF | 儿童/婴儿口罩及儿童用呼吸防护面罩 | — | UK-L1-CHILD-005 |
| 家居工具 | GRLKLZ6WQ9R259LC、GFQMECECLTJCUE3H | 角磨机链锯盘/套件、灭火球、凝胶/液体燃料火盆壁炉、电池受压的加热鞋垫和衣物 | — | UK-L1-HOUSE-001 |
| 报警器 | GXUCN5ZRJSYN9W9S | 烟雾探测器（接消防主机型）、通用款一氧化碳报警器 | 合规家用烟雾报警器、品牌 CO 报警器、可燃气体报警器 | UK-L1-ALARM-001 |

## B. 审核与限售（L2）

**通用流程**：在“添加商品”搜索 ASIN，显示“Apply to sell”即需申请；准备 180 天内采购发票、六面产品图、品牌授权书（如适用）、安全认证；审核 2–7 个工作日；“Your account does not qualify”不可申诉；限制可能随时新增，应定期查看绩效通知和账户状况 [SRC-UK-AMZ-G200333160] [R:UK-L2-GENERAL-001]。

| 类目/商品 | 要求 | 申请路径 | 规则ID |
|---|---|---|---|
| 珠宝、宝石、贵金属 | 类目审核；>1 g 贵金属按重量销售；须有英国检验印记和 dealer’s notice | 添加商品 > 申请销售 | UK-L2-JEWEL-001 [SRC-UK-AMZ-G201744030] |
| 啤酒、葡萄酒、烈酒 | 类目审核；**卖家设立国必须在英国**；英国退货地址或包邮、英语客服、消费税已缴证明、GTIN、详情页显示 ABV、英文标签；仅售 18+、仅自发货并年龄核验 | 添加商品 > 申请销售 | UK-L2-ALCOHOL-001 [SRC-UK-AMZ-G201815620] [SRC-UK-AMZ-G201744410] |
| 食品补充剂 | 类目审核；HPC 正确 product type；生产商 GFSI/HACCP/GMP 证书（含有效期和产品范围） | 申请销售；账户状况 > 提交合规资料 | UK-L2-SUPP-001 [SRC-UK-AMZ-G202156050] |
| CBD 食品 | 仅 FSA 公示名单 validated/awaiting evidence 产品；邮件 food-safety-cbd-approvals-uk@amazon.co.uk 提交 RP 编号、含 THC 的检测报告、标签 | 邮件 | UK-L2-CBD-001 [SRC-UK-AMZ-GDB9KV3NJYRES4AQ] |
| NFA-VPS/POM-VPS 兽药 | 仅 VMD 认可网络零售商；RCVS 场所注册、SQP/药剂师名单及注册证明；逐单审核宠物信息 | 邮件 amazon-nfavps@amazon.co.uk | UK-L2-VETMED-001 [SRC-UK-AMZ-GXS3BR7H8J432E4N] |
| 电子烟设备 / HnB 设备（无烟油） | 年龄限制、Health & Personal Care 类目、MHRA 注册号、强制声明“不含尼古丁或烟草液体/替换装”、无促销、烟仓 ≤2 ml | 账户状况 > 提交合规资料 | UK-L2-ECIG-001 [SRC-UK-AMZ-G201744070] [SRC-UK-AMZ-GZTAPBBRLZ3EU96H] |
| 厨刀、刀具套装 | 只能 FBA，年龄核验交付（Challenge 25） | 自动加年龄标记；可在账户状况申诉 | UK-L2-KNIFE-001 [SRC-UK-AMZ-G201744080] |
| F1 烟花 / T1、P1 烟火 | 只能自发货 + 年龄核验交付 + 上传追踪号 | 订单管理 > 确认发货 | UK-L2-PYRO-001 [SRC-UK-AMZ-G7UCQ6RPZYGBXVQM] |
| 含 F-gas 分体空调/热泵 | 售前取得认证安装商证明、记录保存 5 年 | — | UK-L2-FGAS-001 [SRC-UK-AMZ-G7HVAWY2HGLXVVHU] |
| 流媒体播放器 | 每型号寄样机（不退）、提交硬件/系统/全部 APK 及来源清单、申请表 | Listing limitations apply > Request approval | UK-L2-STREAMING-001 [SRC-UK-AMZ-G202183590] |
| 手表 | 专业计划、库存 >1、英国退货地址或包邮、英语客服、发票 | 申请销售 | UK-L2-WATCH-001 [SRC-UK-AMZ-G200316090] |
| 音乐/DVD、有机食品、Made in Italy、服装等 | 审核清单列出，具体材料见各子页 | 申请销售 | UK-L2-CATEGORY-001 [SRC-UK-AMZ-G200333160] |

**年龄限制商品**：酒类、电子烟、刀具等在详情页标为年龄限制；FBA 由亚马逊安排年龄核验交付，自发货须用可核验年龄的承运服务并上传追踪号 [SRC-UK-AMZ-G7UCQ6RPZYGBXVQM] [R:UK-L3-AVD-001]。

**强化安全合规类目（TIC 直连验证）**：玩具、锂电池、移动电源、电动出行设备及配件等，卖家不再直接向亚马逊上传报告，而须通过亚马逊授权的第三方检测认证（TIC）服务商检测或验证已有报告，TIC 代为提交；产品可能被随机抽检，不合格立即下架 [SRC-UK-AMZ-GKJRA3FRPRKVBJJS] [SRC-UK-AMZ-GUTZ2R2DD6P2UMVB] [R:UK-L3-CEUKCA-001]。

## C. 按品类的平台合规资料（L3）

提交位置未特别说明的，均为“卖家平台 > 账户状况 > 提交合规资料或申诉（GC35Z63FGCUCUWXX）”；标注 TIC 的走“第三方检测认证服务（GUTZ2R2DD6P2UMVB）”。所有报告须来自公告机构/UKAS 或 EU 认可/ILAC-IAF 认可实验室，结果为 Pass 或 N/A，不得来自被暂停实验室，不得修改或 AI 生成 [SRC-UK-AMZ-GNK66Q26HRWH6CTS] [R:UK-L3-LAB-001]。

| 产品族 | 亚马逊要求的文件/Listing 属性 | 提交位置 | 规则ID |
|---|---|---|---|
| 所有 CE/UKCA 产品 | 授权 TIC 报告；UK/EU DoC 与技术文件；召回时 letter of compliance | TIC | UK-L3-CEUKCA-001 |
| 玩具（<14 岁） | BS EN 71（电动玩具 + BS EN 62115）；属性：型号、品牌、警示语、最小年龄（不低于报告）；图片：六面、制造商/进口商名址、警示、CE/UKCA | TIC | UK-L3-TOY-001 |
| 玩具警示语 | 英文警示；填写 3 个警示属性；上传警示图 | 编辑商品 | UK-L3-TOY-002 |
| 锂电池 | IEC/EN 62133-2 或 62619 + UN 38.3 + BTS | TIC | UK-L3-LIION-001 |
| 移动电源/户外电源/应急启动电源 | 12 个月内 62368-1 + 62133-2 + UN 38.3 + BTS | TIC | UK-L3-POWERBANK-001 |
| 手机/笔记本电池与充电器 | DoC + ISO 17025 报告（62133 / 62368-1 或 LVD / 车充 EMC）；原厂配件免报告 | 账户状况 | UK-L3-CHARGER-001 |
| 智能插座 | RED + EMC + RoHS + 适用 BS EN；报告 + DoC | 账户状况 | UK-L3-SMARTPLUG-001 |
| 墙装开关/智能开关 | BS EN 60669-1（-2-1）+ 15.2 节或 BS EN 60529 报告 | 账户状况 | UK-L3-SWITCH-001 |
| 电暖器/电热毯/美发电器 | LVD/EMC/RoHS + BS EN 60335-1 及对应 Part 2；DoC + 图片 | 账户状况 | UK-L3-APPLIANCE-001 |
| 灯串 | EN 60598-2-20（户外 EN 60529/IP44）+ DoC | 账户状况 | UK-L3-STRINGLIGHT-001 |
| 电动车充电器 | EESR 2016 + EN 61851-1 等 + DoC | 账户状况 | UK-L3-EVCHARGER-001 |
| 电动出行设备 | e-bike：BS EN 15194；平衡车/滑板车/独轮车：BS EN 17128；+ UN 38.3 + BTS；e-bike ≤250 W/25 km/h、e-scooter ≤500 W/25 km/h 无座椅；图片不得出现公共道路骑行 | TIC | UK-L3-EMOB-001 |
| 电动出行配件 | 电池 EN 62133/EN 50604；充电器 EN 60335-2-29/62368-1；改装套件 EN 17128/15194 + UN 38.3；无保护电路裸电芯禁售 | TIC | UK-L3-EMOBACC-001 |
| PPE（攀岩安全带、安全鞋、日食镜） | UK 型式检验证书（≤5 年）；安全鞋可用 2022 版 ISO 20345 报告；日食镜 ISO 12312-2 + DoC | 账户状况 | UK-L3-PPE-001 |
| 自行车/滑板头盔 | EN 1078 型式检验 + DoC | 账户状况 | UK-L3-HELMET-001 |
| 救生衣/浮力背心/游泳浮具 | BS EN 12402 / EN 13138-1 型式检验 + DoC | 账户状况 | UK-L3-PFD-001 |
| 医用口罩、FFP 口罩 | EN 14683 报告或型式检验；EN 149 型式检验（Module B + C2/D）；DoC | 账户状况 | UK-L3-MASK-001 |
| 婴儿睡眠产品 | EN 1130 / EN 716 / EN 1466 / EN 12227 / EN 16890 报告；年龄与报告一致 | 账户状况 | UK-L3-INFANTSLEEP-001 |
| 喂养、推车、高脚椅、摇椅秋千 | EN 14350/14372/93/11、EN 1888、EN 14988/EN 1272、EN 16232/EN 12790 报告 | 账户状况 | UK-L3-CHILDCARE-001 |
| 儿童安全座椅 | ECE R44-04 / R129 政府型式批准证书；提篮另需 FFR 1988 报告；ECE 标签图 | 账户状况 | UK-L3-CARSEAT-001 |
| 儿童睡衣 | Nightwear (Safety) Regulations 1985 可燃性 + UK REACH 报告 | 账户状况 | UK-L3-SLEEPWEAR-001 |
| 牙胶 | DoC + 玩具警示属性 | 账户状况 | UK-L3-TEETHING-001 |
| 烟雾/CO/可燃气体报警器 | 公告机构 EN 14604/50291/50194 认证 + DoC；插电式须 Type G 插头 | 账户状况 | UK-L3-ALARM-001 |
| 灭火器 | EN 3-7 + PED 型式检验证书 | 账户状况 | UK-L3-FIREEXT-001 |
| 首饰 | REACH 镉/铅/镍声明（含 SVHC 清单、ASIN 识别）或检测报告 | 应要求提交 | UK-L3-JEWEL-002 |
| 贵金属首饰命名 | 检验印记；不得写 8ct/10ct/333 金；“gold-plated brass”写法；dealer’s notice | Listing | UK-L3-HALLMARK-001 |
| 化妆品 | 英国责任人、SCPN 通报、PIF、英文标签 | 应要求提交 | UK-L3-COSM-001 |
| 预包装食品 | 英文标签与详情页强制信息、英国食品经营者地址 | 库存文件 | UK-L3-FOODINFO-001 |
| 食品补充剂标签与宣称 | “food supplement”、剂量警示、仅 GB NHC 注册宣称 | Listing | UK-L3-SUPP-002 |
| HFSS 食品 | 库存文件填 HFSS 状态，不填默认“Less healthy” | 批量上传 | UK-L3-HFSS-001 |
| 食品接触材料 | DoC、24 个月内迁移测试、“for food contact”/杯叉标志、英国责任主体 | 应要求提交 | UK-L3-FCM-001 |
| 纺织品 | 英文纤维成分标签 | 产品标签 | UK-L3-TEXTILE-001 |
| 鞋类 | 鞋面/内里/外底材质图标或英文，网店解释图标 | 产品标签 + 详情页 | UK-L3-FOOTWEAR-001 |
| 能效标签产品 | 英国版能效标签 + 产品信息表上传详情页 | 上传能效信息 | UK-L3-ENERGY-001 |
| 生物杀灭剂 | 授权号 + “Use biocides safely…”声明 + SDS | Listing / 危险品分类 | UK-L3-BIOCIDE-002 |
| 外用大麻/大麻籽油食品 | 无健康宣称、无 full spectrum/%/CO2/CB 受体字样，成分写 hemp seed oil | Listing | UK-L3-CBD-001 |
| 电子烟/HnB | 只能陈述事实，烟仓容量与法定警示语 | Listing | UK-L3-ECIG-001 |
| 含刀具套装 | 含刀声明 + PT 位刀具图 | 编辑商品 | UK-L3-KNIFE-002 |
| 所有商品宣称 | 禁止把 CE/UKCA 当卖点等自明性宣称；环保、检测标志、Made in 须可证 | Listing | UK-L3-CLAIMS-001 |
| 非药品疾病宣称 | 禁止治疗/预防疾病宣称（含新冠等关键词） | Listing | UK-L3-CLAIMS-002 |
| 汽车灯具/油桶 | ECE 认证；汽油桶符合 2014 石油条例 | 应要求提交 | UK-L3-AUTO-001 |
| 纽扣电池产品 | 建议遵循 PAS 7055:2025 | — | UK-L3-BUTTON-001 |
| 医疗器械 | CE/UKCA、英文 DoC、MHRA 注册/UKRP | 应要求提交 | UK-L3-MED-001 |

## D. FBA 与危险品（L4）

**FBA 禁运（可自发货）** [SRC-UK-AMZ-G201730840]：

| 商品 | 说明 | 规则ID |
|---|---|---|
| 酒类、酒心糖果 | 只能自发货 + 年龄核验 | UK-L4-FBA-001 |
| T1/P1 烟火制品 | 只能自发货 + 年龄核验 | UK-L4-FBA-002 |
| 带刃/尖锐物品 | 例外：封装剃刀片、餐具套装餐刀、≤3 英寸非锁定折刀、厨刀/牛排刀（年龄核验）；刀尖须全程包覆 | UK-L4-FBA-003 |
| 无 BBFC/PEGI 分级的影视游戏软件 | DVD 区码须 0/2/All，蓝光 B 区或无区码 | UK-L4-FBA-004 |
| 裸宝石、活植物、需出口许可商品、非授权经销商商品 | 另：FBA 出口 EU 排除杀虫除草、种子植物 | UK-L4-FBA-005 |
| 包装与物理限制 | >300 cm 或 >140 kg；>1 L 液体须牢固密封；颗粒防漏（125 cm 跌落）；易融品 10–30 °C；有效期商品须贴标不混仓 | UK-L4-FBA-006 |

**危险品** [SRC-UK-AMZ-G201003400]：

| 类别 | 处理 | 规则ID |
|---|---|---|
| 1 类爆炸品、2.3 毒性气体、4.2 自燃、4.3 遇水危险、6.2 感染性、7 类放射性 | 禁止 FBA | UK-L4-DG-001 |
| 2.1/2.2 气体（气雾剂）、3 易燃液体、4.1 易燃固体、5.1/5.2 氧化剂/有机过氧化物、6.1 毒性、8 腐蚀、9 杂项 | 仅限 ADR 有限数量包装；上传 SDS 或豁免表，经危险品审核；可申请 FBA 危险品计划 | UK-L4-DG-002 |
| 锂电池 | 欧洲（含英国）FBA：锂离子电芯 ≤20 Wh、电池 ≤100 Wh（锂金属 ≤1 g / ≤2 g）可入仓，超出拒收；须电池属性、BTS、豁免表，带设备包装的锂离子电池须报荷电状态 [SRC-UK-AMZ-G200383420] | UK-L4-DG-003 |
| 磁性材料（UN 2807）、电池驱动车辆 | 第 9 类，须危险品审核 | UK-L4-DG-004 |
| 进口单号（FHDDS） | 非英国卖家进口货入仓后 60 天内补 IEN；须英国 VAT 号；DDP/境内采购须留正式发票 [SRC-UK-AMZ-G97ZA85WXA334DR2] | UK-L4-FHDDS-001 |

很多日用品（化妆品、香水、清洁剂、含磁铁音箱）也可能被归为危险品，无标签不代表不是危险品；被认定为不可配送危险品的入仓库存可能被销毁且不赔偿 [SRC-UK-AMZ-G201003400]。

## E. 当地法规（L5，按产品族）

**跨品类基础**

| 法规 | 要点 | 主管机构 | 规则ID |
|---|---|---|---|
| 《2005 通用产品安全条例》（GPSR 2005） | 只可供应安全产品（新品、二手、翻新，药品/器械/食品除外）；“生产者”为英国设立的制造商/代表或英国进口商；产品/包装标生产者名址与型号/批号；风险警示；知悉不安全须通报 Trading Standards；召回 [SRC-UK-GOV-GPSR-2005-R7] [SRC-UK-AMZ-GEHZCTK8UVBGMADY] | OPSS / Trading Standards | UK-L5-GPSR-001 |
| 《2025 产品监管和计量法》 | 授权法，s2(3)(e) 允许对在线市场施加义务；2026-03-31 至 06-23 咨询 GPSR 改革（二手来源，待核）；尚无生效条例 [SRC-UK-GOV-PRAM-2025-S2] [SRC-UK-S3-LEWISSILKIN-GPSR-REFORM] | DBT / OPSS | UK-L5-PRAM-001 |
| UKCA / CE | 18 项 DBT 法规无限期认可 CE；UKCA 可贴标签/随附文件至 2027-12-31；制造商与进口商名址 [SRC-UK-GOV-UKCA-GUIDANCE] [SRC-UK-GOV-CE-EXTENSION-2023] | DBT / OPSS | UK-L5-UKCA-001 |
| 北爱尔兰 | 欧盟规则、CE（+UKNI）、EU/NI 进口商与责任人 [SRC-UK-AMZ-G3NRFVS4YUYRQ85J] | — | UK-L5-NI-001 |

### 电子电器
| 适用法规 | 必需的认证/测试 | 注册/备案 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 《2016 电气设备（安全）条例》[SRC-UK-GOV-EESR-2016] | 安全测试（如 BS EN 60335/62368）、技术文件、DoC | — | UKCA/CE、制造商与进口商名址、英文说明 | OPSS | UK-L5-EESR-001 |
| 《1994 插头插座（安全）条例》第 12 条 [SRC-UK-GOV-PLUGS-1994-R12] | BS 1363 插头 + BS 1362 保险丝，或认可的封闭转换插头 | — | — | OPSS / Trading Standards | UK-L5-PLUG-001 |
| 《2016 电磁兼容条例》 | EMC 测试 | — | UKCA/CE | OPSS | UK-L5-EMC-001 |
| 英国 RoHS（SI 2012/3032）[SRC-UK-AMZ-GX4K6RLBEN6DA576] | 铅、汞、六价铬、PBB、PBDE、DEHP、BBP、DBP、DIBP ≤0.1%，镉 ≤0.01%；技术文件（IEC 63000） | — | UKCA/CE、制造商与进口商名址；DoC 保存 10 年 | OPSS | UK-L5-ROHS-001 |
| PSTI 联网产品安全（2024-04-29 起）[SRC-UK-GOV-PSTI-REGIME] | 唯一或用户自设密码；漏洞报告途径；最短安全更新期 | — | 随附符合性声明（SoC，附表 4 内容）[SRC-UK-GOV-PSTI-SI-2023-1007-SCH4] | OPSS（代 DSIT） | UK-L5-PSTI-001 |
| 能效标签（2021 能源信息条例） | 技术文件 | — | 英国版能效标签 + 产品信息表 [SRC-UK-AMZ-GH2GFUC62R6M7RQW] | OPSS / ASA | UK-L3-ENERGY-001 |
| WEEE 2013（2025 修订） | — | 英国设立生产者注册；非英国卖家由亚马逊作为 OMP 生产者代缴 | 划叉垃圾桶标志；分销商回收信息 [SRC-UK-GOV-WEEE-AMEND-2025] | Environment Agency 等 | UK-L5-WEEE-001 |
| 机械（2008 条例） | 基本健康安全要求、技术文件 10 年 | — | UKCA/CE、英文说明与 DoC [SRC-UK-AMZ-G2SS7BARH2D53B5R] | OPSS / HSE | UK-L5-MACHINERY-001 |

### 电池
| 适用法规 | 必需的认证/测试 | 注册/备案 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 《2009 废电池条例》生产者责任 [SRC-UK-GOV-BATTERIES] | — | 便携电池 ≤1 吨直报 NPWD，>1 吨加入 BCS；工业/车用 28 天内向 OPSS 注册 | 回收标识（待核） | Environment Agency / OPSS | UK-L5-BATT-001 |
| 亚马逊政策 | 62133-2/62619 + UN 38.3；圆柱锂电禁售；NiCd 禁售 | — | — | — | UK-L3-LIION-001、UK-L1-LIION-001、UK-L1-ELEC-005 |
| PAS 7055:2025（纽扣电池，自愿） | 安全电池仓、警示 [SRC-UK-AMZ-G85BLBNFDCZ4BQP7] | — | 警示语 | OPSS | UK-L3-BUTTON-001 |

### 无线
| 适用法规 | 必需的认证/测试 | 注册/备案 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 《2017 无线电设备条例》[SRC-UK-AMZ-GXPGL8EWLEJQ3QVB] | 无线电、EMC、安全、射频暴露；技术文件、DoC | — | UKCA/CE、制造商与英国进口商名址、型号批号、使用限制区域 | OPSS / Ofcom | UK-L5-RER-001 |
| Ofcom 频率规则（亚马逊列明） | PMR446 ≤0.5 W；对讲机限 434.040–434.790 / 446.0–446.2 MHz | — | — | Ofcom | UK-L1-ELEC-002 |

### 灯具
| 适用法规 | 必需的认证/测试 | 注册/备案 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| EESR 2016、生态设计（亚马逊列明的白炽/卤素淘汰） | EN 60598 系列；灯串 EN 60598-2-20 | — | 能效标签（光源）、UKCA/CE | OPSS | UK-L5-EESR-001、UK-L1-ELEC-007、UK-L3-STRINGLIGHT-001 |

### 儿童玩具
| 适用法规 | 必需的认证/测试 | 注册/备案 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 《2011 玩具（安全）条例》[SRC-UK-GOV-TOYS-2011] | BS EN 71（电动 + 62115）、安全评估、DoC | — | UKCA/CE（第 18 条）、制造商名址（第 19 条）、英国进口商名址（第 27 条）、附表 5 警示 | OPSS / Trading Standards | UK-L5-TOY-001 |

### 婴童
| 适用法规 | 必需的认证/测试 | 注册/备案 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| GPSR 2005 + 指定 EN 标准（亚马逊要求） | EN 1130/716/1466/12227/16890、EN 14350/14372、EN 1888、EN 14988、EN 16232/12790 | — | 年龄、警示、说明 | OPSS | UK-L3-INFANTSLEEP-001、UK-L3-CHILDCARE-001 |
| 《1985 睡衣（安全）条例》 | 可燃性测试 | — | 睡衣可燃性标签 | Trading Standards | UK-L3-SLEEPWEAR-001 |
| ECE R44-04 / R129 | 型式批准证书 | — | ECE 标签 | DfT / VCA | UK-L3-CARSEAT-001 |

### 食品接触
| 适用法规 | 必需的认证/测试 | 注册/备案 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| GB 版 1935/2004、2023/2006、10/2011 等 [SRC-UK-AMZ-GHRHZMME849XMDCK] | 24 个月内迁移测试、DoC | — | “for food contact”/杯叉标志、英国责任主体名址、追溯标识 | FSA / 地方主管 | UK-L3-FCM-001 |
| 中国产聚酰胺/三聚氰胺厨具进口条件 | 每票货 PAA/甲醛肯定声明 + 报告 | 入境申报 | — | 港口卫生部门 | UK-L6-MELAMINE-001 |
| BPA、竹纤维塑料（亚马逊） | — | — | — | — | UK-L1-HAZ-002、UK-L1-OTHER-004 |

### 化妆品
| 适用法规 | 必需的认证/测试 | 注册/备案 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| GB 化妆品法规（保留版 1223/2009）[SRC-UK-GOV-COSMETICS-GB] | 安全评估（Part B 由合格评估员）、GMP（ISO 22716 可证明）、PIF 10 年 | SCPN 通报；纳米材料另报 | 英国责任人名址、原产国、净含量、保质期/PAO、警示、批号、功能、成分；关键信息英文 | OPSS | UK-L5-COSM-001、UK-L3-COSM-001 |

### 个护健康
| 适用法规 | 必需的认证/测试 | 注册/备案 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| EESR 2016、BS EN 60335-2-23 等（亚马逊） | 美发电器、按摩器等安全测试 | — | UKCA/CE | OPSS | UK-L3-APPLIANCE-001 |
| 宣称限制 | 不得宣称治疗疾病；不得用 MHRA/NHS 背书字样 | — | — | MHRA / ASA | UK-L3-CLAIMS-002、UK-L1-MED-002 |

### 医疗器械
| 适用法规 | 必需的认证/测试 | 注册/备案 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 《2002 英国医疗器械条例》[SRC-UK-GOV-MHRA-DEVICES] [SRC-UK-AMZ-GGKGRK6FV9X8TJDB] | 基本要求、技术文件、英文 DoC | MHRA 注册；境外制造商指定 UKRP | UKCA（标 UKRP 名址）或有效 CE（MDD 至 2028-06-30，MDR/IVDR 至 2030-06-30） | MHRA | UK-L5-MED-001、UK-L3-MED-001 |

### 农药与抗菌宣称
| 适用法规 | 必需的认证/测试 | 注册/备案 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| GB BPR（SI 2019/720 修订）[SRC-UK-AMZ-G57NEMV9CTC3W6F3] | — | HSE 产品授权、活性物质批准 | 授权号、持有人名址、用途、“Use biocides safely…”、SDS | HSE | UK-L5-BPR-001、UK-L1-BIOCIDE-001、UK-L3-BIOCIDE-002 |
| 植保产品（农药） | — | HSE 授权（亚马逊禁专业用、新烟碱类） | — | HSE | UK-L1-PEST-001 |

### 化学品
| 适用法规 | 必需的认证/测试 | 注册/备案 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| UK REACH [SRC-UK-GOV-REACH-DEADLINES] | 附件 XVII 限制物质检测 | 物质 ≥1 吨注册，过渡截止 2029-10-27 / 2030-10-27 / 2031-10-27 | — | HSE | UK-L5-REACH-001 |
| 《2019 攻击性武器法》腐蚀性产品 [SRC-UK-GOV-OWA-2019-SCH1] | — | — | — | 警方 / Trading Standards | UK-L5-CORROSIVE-001 |
| 洗涤剂（保留版 648/2004）[SRC-UK-AMZ-GNQ3RZSPZBMKKQJ3] | 生物降解性 | — | 成分与剂量标签、网站成分表 | Trading Standards | UK-L5-DETERGENT-001 |
| 爆炸物前体、毒物（亚马逊列明） | — | — | — | Home Office | UK-L1-HAZ-005、UK-L1-HAZ-006 |
| GB CLP | 危险化学品分类标签（亚马逊 CLP UK 页未抓取） | — | 英文 GHS 标签 | HSE | 待核实 |

### 刀具武器
| 适用法规 | 要点 | 主管机构 | 规则ID |
|---|---|---|---|
| CJA 1988 s141A/141B（OWA 2019 修订）[SRC-UK-GOV-OWA-2019-S35] | 不得售予 18 岁以下；远程销售须有效年龄核验系统、包裹标注、交付 18 岁以上本人、不得投柜 | 警方 / Trading Standards | UK-L5-KNIFE-001 |
| OWA 2019 s38 [SRC-UK-GOV-OWA-2019-S38] | 远程售“带刃产品”不得送往纯住宅（受 s40 抗辩约束） | 同上 | UK-L5-KNIFE-001 |
| 攻击性武器令附表 [SRC-UK-GOV-OFFWEAPONS-ORDER-1988] | 僵尸风格刀/砍刀（2024-09-24）、忍者剑（2025-08-01，2026-07-16 修订定义）等禁止制造、销售、进口 | Home Office | UK-L5-KNIFE-002 |
| 《2026 犯罪与治安法》s32、s42 [SRC-UK-GOV-CPA-2026-S32] | 远程售刀须证件 + 照片核验、批量销售报告（尚未生效） | Home Office | UK-L5-KNIFE-003 |
| VCRA 2006 s36/38 [SRC-UK-GOV-VCRA-2006-S36] | 逼真仿真枪禁止制造、销售、进口 | Home Office | UK-L5-FIREARM-001 |
| 《1987 弩法》[SRC-UK-GOV-CROSSBOWS-1987-S1] | 不得向 18 岁以下售/租弩 | 警方 | UK-L5-CROSSBOW-001 |
| 烟花法规 [SRC-UK-GOV-FIREWORKS-LAW] | 成人烟花 18+；4 类仅专业；节庆期外须持许可 | 地方政府 | UK-L5-FIREWORK-001 |

### 激光
英国站政策直接禁售所有便携式激光产品 [SRC-UK-AMZ-G201744010] [R:UK-L1-ELEC-003]。OPSS 激光笔指引的政府原文本次未找到可访问的 URL，列入待核实。

### 无人机
本次未找到亚马逊英国针对无人机的专门禁限售页面；无人机含无线与锂电池，适用 RER 2017、锂电池与 DG 规则 [R:UK-L5-RER-001] [R:UK-L4-DG-003]。英国民航局（CAA）对使用者的注册（Operator ID/Flyer ID）与 UK 类别标识（UK0–UK6）属使用侧要求，本次未核对原文，列入待核实。

### 汽配
| 适用法规 | 必需的认证/测试 | 标签要求 | 规则ID |
|---|---|---|---|
| UNECE 1958 协定车辆法规（亚马逊列明） | 车灯等 ECE 认证；汽油桶符合《2014 石油（合并）条例》 | E-mark | UK-L3-AUTO-001 |
| 轮胎能效标签 | — | A–E 级标签与信息表 | UK-L3-ENERGY-001 |
| 电助力自行车（EAPC 规则，亚马逊列明） | ≤250 W、≤25 km/h | — | UK-L1-AUTO-004、UK-L3-EMOB-001 |

### 家具木制品
| 适用法规 | 必需的认证/测试 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|
| 《1988 家具及家装（防火）（安全）条例》[SRC-UK-GOV-FURNITURE-FIRE-1988] | 泡沫、填充、隔层、香烟、火柴测试 | 展示标签（第 10 条）+ 永久标签（第 11 条） | Trading Standards | UK-L5-FIRE-001 |
| 英国木材法规（UKTR/FLEGT）[SRC-UK-AMZ-GVUSSGYL7U5CS2H8] | 尽职调查体系 | — | OPSS | UK-L5-TIMBER-001 |
| 建筑产品（保留版 305/2011）[SRC-UK-AMZ-GRUVKBN6Y6ZWNBRX] | DoP、技术文件 10 年 | UKCA/CE | OPSS | UK-L5-CPR-001 |

### 纺织服装
| 适用法规 | 要点 | 规则ID |
|---|---|---|
| 《2012 纺织品（标签与纤维成分）条例》[SRC-UK-AMZ-GJWU6Z34TSXJDBES] | 英文纤维成分，降序百分比，动物源非纺织部分须声明 | UK-L3-TEXTILE-001 |
| 《1995 鞋类（成分标示）标签条例》[SRC-UK-AMZ-GWCHQA5FTNGQK6BQ] | 三部位材质 | UK-L3-FOOTWEAR-001 |
| 亚马逊政策 | 真皮草、二手服装禁售；童装抽绳禁售 | UK-L1-ANIMAL-002、UK-L1-CLOTH-001、UK-L1-CHILD-003 |

### 珠宝
| 适用法规 | 要点 | 规则ID |
|---|---|---|
| 《1973 检验印记法》（亚马逊列明）[SRC-UK-AMZ-G201744030] | 金银铂钯须英国认可检验印记；dealer’s notice；不得写 8/10ct 金 | UK-L3-HALLMARK-001、UK-L1-JEWEL-001 |
| UK REACH 附件 XVII | 镉 ≤0.01%、铅 ≤0.05%、镍释放 0.2/0.5 μg/cm²/周 | UK-L3-JEWEL-002 |
| 俄罗斯制裁 | 俄产钻石、黄金及第三国加工品禁止进口 | UK-L6-SANCTION-001 |

### 宠物
| 适用法规 | 要点 | 规则ID |
|---|---|---|
| 兽药（VMD 制度） | AVM-GSL 可售；NFA-VPS/POM-VPS 仅 VMD 认可零售商经审核；POM-V 禁售 | UK-L2-VETMED-001、UK-L1-DRUG-001 |
| 动物福利（亚马逊列明） | 电击项圈、内刺项圈、粘鼠板禁售 | UK-L1-ANIMAL-004 |
| 饲料法规 | 未授权动物蛋白/活虫饲料禁售 | UK-L1-ANIMAL-005 |

### 植物种子
| 适用法规 | 要点 | 规则ID |
|---|---|---|
| 植物健康法规（保留版 2016/2031）、《2011 种子营销条例》 | 植物检疫证书/植物护照；种子质量包装标签；园艺泥炭禁售（亚马逊） | UK-L1-PLANT-001、UK-L6-PLANT-001 |

### 食品保健品
| 适用法规 | 要点 | 主管机构 | 规则ID |
|---|---|---|---|
| 保留版食品信息法规（FIC）[SRC-UK-AMZ-G2KV48AFJLLUWGJT] | 英文强制信息、英国食品经营者地址，详情页同步 | FSA / 地方 | UK-L3-FOODINFO-001 |
| 《2003 食品补充剂（英格兰）条例》、GB NHC 注册表 [SRC-UK-AMZ-G202156050] | 标签、剂量、授权宣称；禁疾病宣称 | FSA | UK-L3-SUPP-002 |
| 新型食品 / CBD [SRC-UK-GOV-CBD-FSA] | 无获批 CBD；仅 FSA 公示名单；10 mg/日、THC 70 μg/日 | FSA | UK-L5-FOOD-001 |
| HFSS 陈列限制（2021 英格兰条例） | 13 类食品按营养评分模型限制展示 | 地方主管 | UK-L5-HFSS-001、UK-L3-HFSS-001 |

### 烟草电子烟
| 适用法规 | 要点 | 规则ID |
|---|---|---|
| 一次性电子烟禁令 [SRC-UK-GOV-SINGLE-USE-VAPES] | 2025-06-01 起全英禁止销售/供应/储存待售 | UK-L5-VAPE-001 |
| 《2016 烟草及相关产品条例》[SRC-UK-GOV-ECIG-REGS] | MHRA 通报、烟仓 ≤2 ml、尼古丁 ≤20 mg/ml、补充瓶 ≤10 ml、儿童防护 | UK-L5-VAPE-002 |
| 《2026 烟草和电子烟法》[SRC-UK-GOV-TVA-2026-S1] | 2027-01-01 起禁向 2009-01-01 后出生者售烟；电子烟/尼古丁产品年龄、陈列、包装、口味、许可新规 | UK-L5-TOBACCO-001 |

### 酒类
亚马逊要求卖家设立在英国、自发货、年龄核验、提供消费税证明 [R:UK-L2-ALCOHOL-001]；≥70% ABV 禁售 [R:UK-L1-ALCOHOL-001]。英国本地酒类许可（Licensing Act 2003）与 AWRS 仅作为亚马逊列出的参考资源，具体是否需要视业务模式，待核实。

### 成人
亚马逊禁售 R18 色情、仿真性爱娃娃等 [R:UK-L1-ADULT-001]；避孕套须原厂密封零售包装 [SRC-UK-AMZ-G201744060]。“成人商品政策与露骨图像指南”（G200339940）已抓取快照，图片规则未逐条整理。

### 二手
二手服装鞋禁售 [R:UK-L1-CLOTH-001]；二手汽配、二手医疗器械禁售 [R:UK-L1-AUTO-001] [R:UK-L1-MED-001]；二手/翻新电器须经专家安全检测 [R:UK-L1-UNSAFE-001]；化妆品、食品、药品不得开封或二手 [R:UK-L1-COSM-001] [R:UK-L1-EXPIRED-001]。

### 环保与包装
| 适用法规 | 要点 | 规则ID |
|---|---|---|
| 包装 EPR（SI 2024/1332）[SRC-UK-GOV-EPR-PACKAGING] | 英国设立且 ≥£1m、>25 吨为生产者；非英国卖家由亚马逊代缴 | UK-L5-PACK-001 |
| 塑料包装税 [SRC-UK-AMZ-GDVSPV5QUPCUQPBF] | ≥10 吨成品塑料包装须注册（非英国卖家同样适用），向亚马逊提供 PPT 号 | UK-L5-PPT-001 |
| 英格兰一次性塑料禁令 [SRC-UK-GOV-SINGLE-USE-PLASTICS] | 搅拌棒、气球棒、餐具、聚苯乙烯容器禁；盘碗、吸管、棉签限 | UK-L5-PLASTIC-001 |
| 笑气 C 类管制 [SRC-UK-GOV-NITROUS-OXIDE] | 2023-11-08 起 | UK-L5-N2O-001 |
| 燃气器具（2018 条例）[SRC-UK-AMZ-G4CXN64DQ98BWWH2] | 型式检验、英文 DoC 与说明 | UK-L5-GAS-001 |
| PPE（GB 版 2016/425）[SRC-UK-AMZ-GNW6TTB8WVHHECFR] | II/III 类型式检验 | UK-L5-PPE-001 |

### 进口、清关与制裁（L6）
| 事项 | 要求 | 主管机构 | 规则ID |
|---|---|---|---|
| 亚马逊受限原产地 | 朝鲜、古巴、伊朗、克里米亚、DNR、LNR 原产商品及土库曼斯坦棉花禁售 [SRC-UK-AMZ-G201743940] [SRC-UK-AMZ-G201575280] | — | UK-L1-ORIGIN-001 |
| 俄罗斯制裁 | 禁止进口俄原产/发运的钢铁（2023-09-30 起含第三国加工）、金属、黄金及金饰、钻石（含第三国加工）、油品、煤、LNG、铀、创收商品；禁止进口乌克兰被占区（克里米亚、塞瓦斯托波尔及顿涅茨克、赫尔松、卢甘斯克、扎波罗热州非政府控制区）原产商品 [SRC-UK-GOV-RUSSIA-SANCTIONS] | DBT 进口制裁团队 | UK-L6-SANCTION-001 |
| 其他制裁与受限制方 | 白俄罗斯、叙利亚、索马里、利比亚、伊朗、朝鲜进口通告；亚马逊不与美/欧/英/加制裁名单方交易 [SRC-UK-GOV-IMPORT-CONTROLS] | DBT / HM Treasury | UK-L6-SANCTION-002 |
| 进口许可与禁令 | 枪支弹药须进口许可；猫狗毛皮禁止进出口；酷刑设备、杀伤人员地雷、核材料、分级定价药品受控 [SRC-UK-GOV-IMPORT-CONTROLS] | DBT 进口许可处 | UK-L6-IMPORT-001 |
| 武器进口 | 法定禁止武器（CJA 1988 s141(4)）与逼真仿真枪（VCRA s36）禁止进口 [SRC-UK-GOV-CJA-1988-S141] | Border Force | UK-L6-WEAPON-001 |
| 中国产三聚氰胺/尼龙厨具 | 每票货 PAA/甲醛肯定声明 + 检测报告，官方查验 [SRC-UK-AMZ-GHRHZMME849XMDCK] | 港口卫生部门 | UK-L6-MELAMINE-001 |
| VAT | 在线市场对 ≤£135 进口货件及海外卖家英国库存销售代扣 VAT；卖家负担进口 VAT 与关税 [SRC-UK-GOV-VAT-OMP] | HMRC | UK-L6-VAT-001 |
| EORI | 进口通常须 GB EORI [SRC-UK-GOV-EORI] | HMRC | UK-L6-EORI-001 |
| FHDDS / IEN | 非英国卖家 FBA 进口货 60 天内提交 IEN [SRC-UK-AMZ-G97ZA85WXA334DR2] | HMRC | UK-L4-FHDDS-001 |
| CITES | 濒危物种制品须 CITES 许可（亚马逊直接禁售）[SRC-UK-AMZ-G201743950] | APHA | UK-L6-CITES-001 |
| 植物种子 | 植物检疫证书/植物护照 [SRC-UK-AMZ-G201744040] | APHA / Defra | UK-L6-PLANT-001 |

## F. 标签、语言与本地责任人

| 项目 | 要求 | 来源/规则 |
|---|---|---|
| 语言 | 英国站警示语、说明书、安全信息须为英文；玩具警示须英文 [SRC-UK-AMZ-G200686210]；化妆品警示、功能、净含量、日期须英文；食品强制信息英文；能效标签只含英文 | UK-L3-TOY-002、UK-L3-COSM-001、UK-L3-FOODINFO-001、UK-L3-ENERGY-001 |
| 生产者信息 | GPSR 2005：产品或包装标生产者名址和型号/批号 | UK-L5-GPSR-001 |
| 英国进口商 | UKCA/CE 产品须标注英国进口商名称与地址（EEA 进口品至 2027-12-31 可标在产品以外） | UK-L5-UKCA-001 |
| 化妆品责任人 | 必须在英国设立，地址不可为邮件转寄或 PO Box | UK-L5-COSM-001 |
| 医疗器械 | 境外制造商须指定唯一 UKRP，UKCA 产品标 UKRP 名址 | UK-L5-MED-001 |
| 食品 | GB 销售须标英国食品经营者地址 | UK-L3-FOODINFO-001 |
| 食品接触材料 | 标在英国设立的制造商/加工者/销售者 | UK-L3-FCM-001 |
| 无线电设备 | 授权代表须在英国（北爱须 NI/EEA） | UK-L5-RER-001 |
| PSTI | 境外制造商可指定英国授权代表，但仍承担责任 | UK-L5-PSTI-001 |
| 酒类 | 卖家须在英国设立 | UK-L2-ALCOHOL-001 |
| 北爱尔兰 | EU/NI 进口商和欧盟责任人；CE（+UKNI） | UK-L5-NI-001 |
| 原产地 | 化妆品进口品须标原产国；食品适用时标原产国 | UK-L3-COSM-001、UK-L3-FOODINFO-001 |
| 税务登记 | FBA 卖家须提供经验证的英国 VAT 号；进口须 EORI | UK-L4-FHDDS-001、UK-L6-VAT-001、UK-L6-EORI-001 |

## G. 2024–2026 变化与生效日期

| 日期 | 变化 | 影响的产品 | 规则ID | 来源 |
|---|---|---|---|---|
| 2024-04-29 | PSTI 联网产品安全制度生效 | 智能家居、联网摄像头、穿戴设备等 | UK-L5-PSTI-001 | SRC-UK-GOV-PSTI-REGIME |
| 2024-09-24 | 僵尸风格刀具和砍刀纳入法定禁止武器 | 刀具 | UK-L5-KNIFE-002 | SRC-UK-GOV-OFFWEAPONS-ORDER-1988 |
| 2024（具体日待核） | 《2024 产品安全与计量（修订）条例》确认 GB 继续认可 CE | 18 类 DBT 法规产品 | UK-L5-UKCA-001 | SRC-UK-GOV-UKCA-GUIDANCE |
| 2025-01-01 | 包装 EPR 生效（2025 年起收费） | 所有带包装商品 | UK-L5-PACK-001 | SRC-UK-AMZ-GA4K825NTF757RBT |
| 2025-04-30 | PAS 7055:2025 纽扣电池规范发布 | 含纽扣电池产品 | UK-L3-BUTTON-001 | SRC-UK-AMZ-G85BLBNFDCZ4BQP7 |
| 2025-06-01 | 一次性电子烟禁令 | 电子烟 | UK-L5-VAPE-001 | SRC-UK-GOV-SINGLE-USE-VAPES |
| 2025-06-16 | MHRA 强化上市后监督 | 医疗器械 | UK-L5-MED-001 | SRC-UK-GOV-MHRA-DEVICES |
| 2025-07（御准） | 《2025 产品监管和计量法》 | 全品类（授权法） | UK-L5-PRAM-001 | SRC-UK-GOV-PRAM-2025-S15 |
| 2025-08-01 | 忍者剑纳入法定禁止武器 | 刀剑 | UK-L5-KNIFE-002 | SRC-UK-GOV-OFFWEAPONS-ORDER-1988 |
| 2025-08-12 | 亚马逊为非英国卖家代履行 WEEE 义务（WEEE 2025 修订，在线市场成为 OMP 生产者；新增电子烟类别 7.1） | 电子电器、电子烟 | UK-L5-WEEE-001 | SRC-UK-AMZ-GA4K825NTF757RBT、SRC-UK-GOV-WEEE-AMEND-2025 |
| 2026-03-31 ~ 06-23 | GPSR 改革与在线市场义务咨询（二手来源，待核） | 全品类 | UK-L5-PRAM-001 | SRC-UK-S3-LEWISSILKIN-GPSR-REFORM |
| 2026-05-28 | 北爱尔兰医疗器械须在 EUDAMED 注册 | 医疗器械（NI） | UK-L3-MED-001 | SRC-UK-AMZ-GGKGRK6FV9X8TJDB |
| 2026（御准） | 《2026 烟草和电子烟法》成法 | 烟草、电子烟、尼古丁产品 | UK-L5-TOBACCO-001 | SRC-UK-GOV-TVA-2026 |
| 2026（御准，条款待生效） | 《2026 犯罪与治安法》远程售刀/弩新规 | 刀具、弩 | UK-L5-KNIFE-003 | SRC-UK-GOV-CPA-2026-S32 |
| 2026-07-16 | 忍者剑定义修订（SI 2026/836） | 刀剑 | UK-L5-KNIFE-002 | SRC-UK-GOV-OFFWEAPONS-ORDER-1988 |
| 2027-01-01 | 禁止向 2009-01-01 及以后出生者出售烟草 | 烟草 | UK-L5-TOBACCO-001 | SRC-UK-GOV-TVA-2026-S175 |
| 2027-12-31 | UKCA 贴标签/随附文件、EEA 进口品进口商信息标在产品外的过渡期结束 | UKCA 产品 | UK-L5-UKCA-001 | SRC-UK-GOV-UKCA-GUIDANCE |
| 2028-06-30 / 2030-06-30 | CE 医疗器械在 GB 的认可截止（MDD/AIMDD；MDR/IVDR/IVDD） | 医疗器械 | UK-L5-MED-001 | SRC-UK-GOV-MHRA-DEVICES |
| 2029-10-27 / 2030-10-27 / 2031-10-27 | UK REACH 过渡注册截止（按吨位/危害） | 化学物质进口商 | UK-L5-REACH-001 | SRC-UK-GOV-REACH-DEADLINES |
| 2023-09-30 起（持续扩展至 2026-05-20） | 俄罗斯制裁：第三国加工钢铁、钻石、油品进口禁令 | 钢铁制品、珠宝 | UK-L6-SANCTION-001 | SRC-UK-GOV-RUSSIA-SANCTIONS |

## H. 来源清单

共 146 个来源（S1 96、S2 47、S3 3）。S1 快照存于 `policy/snapshots/UK/`。

| 来源ID | 标题 | URL | 级别 | 访问日期 | 方式 |
|---|---|---|---|---|---|
| SRC-UK-AMZ-G200140860 | FBA product restrictions | https://sellercentral.amazon.co.uk/help/hub/reference/external/G200140860?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G200301050 | Products requiring additional approvals | https://sellercentral.amazon.co.uk/help/hub/reference/external/G200301050?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G200316090 | Watches | https://sellercentral.amazon.co.uk/help/hub/reference/external/G200316090?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G200333160 | Categories and products that require approval | https://sellercentral.amazon.co.uk/help/hub/reference/external/G200333160?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G200383420 | Requirements for lithium batteries and products that are shipped with lithium batteries | https://sellercentral.amazon.co.uk/help/hub/reference/external/G200383420?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G200686210 | EU Toy Safety Directive – Mandatory safety warnings | https://sellercentral.amazon.co.uk/help/hub/reference/external/G200686210?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G201003400 | Dangerous goods identification guide (hazmat) | https://sellercentral.amazon.co.uk/help/hub/reference/external/G201003400?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G201416530 | Electrical Goods Requirements: Plugs and Sockets | https://sellercentral.amazon.co.uk/help/hub/reference/external/G201416530?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G201575280 | Trade control laws | https://sellercentral.amazon.co.uk/help/hub/reference/external/G201575280?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G201730840 | FBA prohibited products | https://sellercentral.amazon.co.uk/help/hub/reference/external/G201730840?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G201743940 | Category, Product, and Content Restrictions | https://sellercentral.amazon.co.uk/help/hub/reference/external/G201743940?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G201743950 | Animals and animal products | https://sellercentral.amazon.co.uk/help/hub/reference/external/G201743950?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G201743960 | Automotive | https://sellercentral.amazon.co.uk/help/hub/reference/external/G201743960?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G201743970 | Currency, coins, cash equivalents and gift cards | https://sellercentral.amazon.co.uk/help/hub/reference/external/G201743970?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G201743980 | Cosmetics | https://sellercentral.amazon.co.uk/help/hub/reference/external/G201743980?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G201743990 | Drugs, drug paraphernalia and dietary supplements | https://sellercentral.amazon.co.uk/help/hub/reference/external/G201743990?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G201744000 | Food and beverage | https://sellercentral.amazon.co.uk/help/hub/reference/external/G201744000?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G201744010 | Electronics | https://sellercentral.amazon.co.uk/help/hub/reference/external/G201744010?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G201744020 | Medical devices | https://sellercentral.amazon.co.uk/help/hub/reference/external/G201744020?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G201744030 | Jewellery | https://sellercentral.amazon.co.uk/help/hub/reference/external/G201744030?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G201744040 | Other products | https://sellercentral.amazon.co.uk/help/hub/reference/external/G201744040?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G201744060 | Sex and sensuality | https://sellercentral.amazon.co.uk/help/hub/reference/external/G201744060?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G201744070 | Tobacco, e-cigarettes and related products | https://sellercentral.amazon.co.uk/gp/help/external/G201744070?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G201744080 | Weapons | https://sellercentral.amazon.co.uk/help/hub/reference/external/G201744080?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G201744410 | Alcohol | https://sellercentral.amazon.co.uk/help/hub/reference/external/G201744410?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G201744450 | Gambling and lottery | https://sellercentral.amazon.co.uk/help/hub/reference/external/G201744450?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G201744470 | Clothing | https://sellercentral.amazon.co.uk/help/hub/reference/external/G201744470?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G201815620 | Beer, Wine & Spirits | https://sellercentral.amazon.co.uk/help/hub/reference/external/G201815620?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G202137200 | Child restraint systems, booster seats and travel systems | https://sellercentral.amazon.co.uk/help/hub/reference/external/G202137200?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G202137960 | String lights | https://sellercentral.amazon.co.uk/help/hub/reference/external/G202137960?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G202156050 | Food supplements | https://sellercentral.amazon.co.uk/help/hub/reference/external/G202156050?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G202156120 | Device batteries and chargers | https://sellercentral.amazon.co.uk/help/hub/reference/external/G202156120?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G202162990 | Personal flotation devices | https://sellercentral.amazon.co.uk/gp/help/external/G202162990?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G202183590 | Streaming Media Players | https://sellercentral.amazon.co.uk/help/hub/reference/external/G202183590?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G2HSXA2KM59YX5AT | Cylindrical rechargeable lithium batteries | https://sellercentral.amazon.co.uk/help/hub/reference/external/G2HSXA2KM59YX5AT?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G2JX2MAWJ27DWAY6 | Compliance Reference | https://sellercentral.amazon.co.uk/help/hub/reference/external/G2JX2MAWJ27DWAY6?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G2KV48AFJLLUWGJT | Regulations about the United Kingdom provision of food information to consumers | https://sellercentral.amazon.co.uk/help/hub/reference/external/G2KV48AFJLLUWGJT?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G2SS7BARH2D53B5R | UK requirements for machinery | https://sellercentral.amazon.co.uk/help/hub/reference/external/G2SS7BARH2D53B5R?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G3NRFVS4YUYRQ85J | EU and UK product marking guidance: CE and UKCA marking | https://sellercentral.amazon.co.uk/gp/help/external/G3NRFVS4YUYRQ85J?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G4CXN64DQ98BWWH2 | UK requirements for gas appliances | https://sellercentral.amazon.co.uk/help/hub/reference/external/G4CXN64DQ98BWWH2?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G4SX7HDHVCGK33UD | Pushchairs and prams | https://sellercentral.amazon.co.uk/help/hub/reference/external/G4SX7HDHVCGK33UD?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G57NEMV9CTC3W6F3 | Information on the sale of biocidal products – United Kingdom | https://sellercentral.amazon.co.uk/help/hub/reference/external/G57NEMV9CTC3W6F3?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G5NGAYYZAY559SCZ | Children’s sleepwear | https://sellercentral.amazon.co.uk/help/hub/reference/external/G5NGAYYZAY559SCZ?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G6GFTJ2TEFCTKN6Q | Misleading and prohibited product claims | https://sellercentral.amazon.co.uk/help/hub/reference/external/G6GFTJ2TEFCTKN6Q?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G76DURDA6ZW48DX7 | High chairs and hook-on chairs | https://sellercentral.amazon.co.uk/help/hub/reference/external/G76DURDA6ZW48DX7?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G7HM69VDEMRW7TPE | Electronic mobility (e-mobility) accessories | https://sellercentral.amazon.co.uk/help/hub/reference/external/G7HM69VDEMRW7TPE?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G7HVAWY2HGLXVVHU | Hazardous and dangerous items | https://sellercentral.amazon.co.uk/help/hub/reference/external/G7HVAWY2HGLXVVHU?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G7PAP6BJAUXRM4LH | Lithium batteries | https://sellercentral.amazon.co.uk/help/hub/reference/external/G7PAP6BJAUXRM4LH?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G7UCQ6RPZYGBXVQM | Age verification on delivery requirements | https://sellercentral.amazon.co.uk/help/hub/reference/external/G7UCQ6RPZYGBXVQM?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G85BLBNFDCZ4BQP7 | Button and coin batteries | https://sellercentral.amazon.co.uk/help/hub/reference/external/G85BLBNFDCZ4BQP7?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G8KZHJBNC2647269 | Whipped cream dispensers | https://sellercentral.amazon.co.uk/help/hub/reference/external/G8KZHJBNC2647269?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G97ZA85WXA334DR2 | UK’s Fulfilment House Due Diligence Scheme (FHDDS) | https://sellercentral.amazon.co.uk/help/hub/reference/external/G97ZA85WXA334DR2?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-G9MJWDA8TTMZFAXE | Jewellery | https://sellercentral.amazon.co.uk/help/hub/reference/external/G9MJWDA8TTMZFAXE?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GA4K825NTF757RBT | Extended Producer Responsibility requirements: United Kingdom | https://sellercentral.amazon.co.uk/help/hub/reference/external/GA4K825NTF757RBT?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GDB9KV3NJYRES4AQ | Cannabidiol (CBD) and hemp products | https://sellercentral.amazon.co.uk/help/hub/reference/external/GDB9KV3NJYRES4AQ?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GDPSRCGVBFSFY78H | Baby teething products | https://sellercentral.amazon.co.uk/help/hub/reference/external/GDPSRCGVBFSFY78H?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GDQHATC3NQPXKLGF | Medical and particulate-filtering respirators | https://sellercentral.amazon.co.uk/help/hub/reference/external/GDQHATC3NQPXKLGF?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GDVSPV5QUPCUQPBF | UK Plastic Packaging Tax | https://sellercentral.amazon.co.uk/help/hub/reference/external/GDVSPV5QUPCUQPBF?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GECCHPZ45P4KVFN6 | Infant sleep products | https://sellercentral.amazon.co.uk/help/hub/reference/external/GECCHPZ45P4KVFN6?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GEHZCTK8UVBGMADY | UK General Product Safety Regulations | https://sellercentral.amazon.co.uk/help/hub/reference/external/GEHZCTK8UVBGMADY?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GFQMECECLTJCUE3H | Battery-operated heated clothing and insoles | https://sellercentral.amazon.co.uk/help/hub/reference/external/GFQMECECLTJCUE3H?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GGKGRK6FV9X8TJDB | UK Medical Devices Regulation | https://sellercentral.amazon.co.uk/help/hub/reference/external/GGKGRK6FV9X8TJDB?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GGUXTDB7TLY6F5LE | Electric space heaters | https://sellercentral.amazon.co.uk/help/hub/reference/external/GGUXTDB7TLY6F5LE?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GH2GFUC62R6M7RQW | Energy labeling requirements | https://sellercentral.amazon.co.uk/help/hub/reference/external/GH2GFUC62R6M7RQW?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GHRAUBNDL7K7EZSG | Bicycle, skateboard and similar helmets | https://sellercentral.amazon.co.uk/help/hub/reference/external/GHRAUBNDL7K7EZSG?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GHRHZMME849XMDCK | UK requirements for food contact materials | https://sellercentral.amazon.co.uk/help/hub/reference/external/GHRHZMME849XMDCK?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GHTHAAPYZLHVD6RN | Food (Promotion and Placement) (England) Regulations 2021: foods high in fat, salt and sugar | https://sellercentral.amazon.co.uk/help/hub/reference/external/GHTHAAPYZLHVD6RN?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GJWU6Z34TSXJDBES | UK requirements for textile products | https://sellercentral.amazon.co.uk/help/hub/reference/external/GJWU6Z34TSXJDBES?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GKJRA3FRPRKVBJJS | Children’s toys | https://sellercentral.amazon.co.uk/help/hub/reference/external/GKJRA3FRPRKVBJJS?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GKZKGXGS4EGP68LA | Electric heating blankets | https://sellercentral.amazon.co.uk/help/hub/reference/external/GKZKGXGS4EGP68LA?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GMUW6CKYLY4AP8MK | Electronic mobility (e-mobility) devices | https://sellercentral.amazon.co.uk/help/hub/reference/external/GMUW6CKYLY4AP8MK?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GNK66Q26HRWH6CTS | Laboratory requirements for test reports | https://sellercentral.amazon.co.uk/gp/help/external/GNK66Q26HRWH6CTS?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GNQ3RZSPZBMKKQJ3 | UK requirements for detergent products | https://sellercentral.amazon.co.uk/gp/help/external/GNQ3RZSPZBMKKQJ3?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GNW6TTB8WVHHECFR | Personal protective equipment (PPE) | https://sellercentral.amazon.co.uk/help/hub/reference/external/GNW6TTB8WVHHECFR?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GQKVFBUXQJ4FR2G9 | Offensive and Controversial Materials | https://sellercentral.amazon.co.uk/help/hub/reference/external/GQKVFBUXQJ4FR2G9?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GRLKLZ6WQ9R259LC | Product safety listing restrictions | https://sellercentral.amazon.co.uk/help/hub/reference/external/GRLKLZ6WQ9R259LC?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GRUVKBN6Y6ZWNBRX | UK requirements for construction products | https://sellercentral.amazon.co.uk/help/hub/reference/external/GRUVKBN6Y6ZWNBRX?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GS972L5FPTCLNYNR | Fire extinguishers (UK) | https://sellercentral.amazon.co.uk/help/hub/reference/external/GS972L5FPTCLNYNR?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GSJFE8S8AES7F7VG | Portable power supplies | https://sellercentral.amazon.co.uk/help/hub/reference/external/GSJFE8S8AES7F7VG?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GSQZZGJ8SXC2HC4Q | Smart plugs | https://sellercentral.amazon.co.uk/help/hub/reference/external/GSQZZGJ8SXC2HC4Q?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GTN7A3NRVUZGRPBG | Electric vehicle chargers | https://sellercentral.amazon.co.uk/help/hub/reference/external/GTN7A3NRVUZGRPBG?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GTVZL2BE4YZJWLTE | Swimming and flotation aids | https://sellercentral.amazon.co.uk/help/hub/reference/external/GTVZL2BE4YZJWLTE?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GUFQGCVJXHSYBL2Z | Infant bouncers, swings and rockers | https://sellercentral.amazon.co.uk/help/hub/reference/external/GUFQGCVJXHSYBL2Z?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GUG6JJCDN6YYQYJP | Infant and toddler feeding products | https://sellercentral.amazon.co.uk/help/hub/reference/external/GUG6JJCDN6YYQYJP?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GUH6FA4XSJ2LZFLY | Product safety and compliance | https://sellercentral.amazon.co.uk/help/hub/reference/external/GUH6FA4XSJ2LZFLY?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GURBES6E6XZAB8GN | UK requirements for cosmetic products | https://sellercentral.amazon.co.uk/help/hub/reference/external/GURBES6E6XZAB8GN?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GUTZ2R2DD6P2UMVB | Direct product validation: Third‑party testing, inspection and certification services | https://sellercentral.amazon.co.uk/help/hub/reference/external/GUTZ2R2DD6P2UMVB?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GVUSSGYL7U5CS2H8 | UK requirements for timber and timber products | https://sellercentral.amazon.co.uk/help/hub/reference/external/GVUSSGYL7U5CS2H8?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GW5CVACPVTQNTWHX | Hair styling appliances | https://sellercentral.amazon.co.uk/help/hub/reference/external/GW5CVACPVTQNTWHX?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GWCHQA5FTNGQK6BQ | UK requirements for the labelling of footwear components | https://sellercentral.amazon.co.uk/help/hub/reference/external/GWCHQA5FTNGQK6BQ?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GX4K6RLBEN6DA576 | UK Regulations on the restriction of hazardous substances (UK RoHS) | https://sellercentral.amazon.co.uk/help/hub/reference/external/GX4K6RLBEN6DA576?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GXPGL8EWLEJQ3QVB | UK Radio Equipment Regulations | https://sellercentral.amazon.co.uk/help/hub/reference/external/GXPGL8EWLEJQ3QVB?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GXS3BR7H8J432E4N | Selling NFA-VPS/POM-VPS veterinary medicines | https://sellercentral.amazon.co.uk/help/hub/reference/external/GXS3BR7H8J432E4N?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GXUCN5ZRJSYN9W9S | Smoke and carbon gas alarms | https://sellercentral.amazon.co.uk/help/hub/reference/external/GXUCN5ZRJSYN9W9S?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GYHKL6FHQUUWS2VK | Mechanical and electronic switches | https://sellercentral.amazon.co.uk/help/hub/reference/external/GYHKL6FHQUUWS2VK?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-AMZ-GZTAPBBRLZ3EU96H | E-cigarette and heated tobacco products | https://sellercentral.amazon.co.uk/help/hub/reference/external/GZTAPBBRLZ3EU96H?mons_sel_locale=en_GB | S1 | 2026-10-10 | jina_reader |
| SRC-UK-GOV-BATTERIES | Waste batteries: producer responsibility | https://www.gov.uk/guidance/waste-batteries-producer-responsibility | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-CBD-FSA | Cannabidiol (CBD) guidance (Food Standards Agency) | https://www.gov.uk/government/publications/cannabidiol-cbd-guidance/cannabidiol-cbd-guidance | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-CE-EXTENSION-2023 | UK government announces extension of CE mark recognition for businesses (1 August 2023) | https://www.gov.uk/government/news/uk-government-announces-extension-of-ce-mark-recognition-for-businesses | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-CJA-1988-S141 | Criminal Justice Act 1988, section 141 (Offensive weapons) | https://www.legislation.gov.uk/ukpga/1988/33/section/141 | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-COSMETICS-GB | Making cosmetic products available to consumers in Great Britain | https://www.gov.uk/guidance/making-cosmetic-products-available-to-consumers-in-great-britain | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-CPA-2026 | Crime and Policing Act 2026 (c. 20) — contents | https://www.legislation.gov.uk/ukpga/2026/20/contents | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-CPA-2026-S255 | Crime and Policing Act 2026, section 255 (Commencement) | https://www.legislation.gov.uk/ukpga/2026/20/section/255 | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-CPA-2026-S32 | Crime and Policing Act 2026, section 32 (Remote sales of knives etc: England and Wales) | https://www.legislation.gov.uk/ukpga/2026/20/section/32 | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-CROSSBOWS-1987-S1 | Crossbows Act 1987, section 1 (Sale and letting on hire) | https://www.legislation.gov.uk/ukpga/1987/32/section/1 | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-ECIG-REGS | E-cigarettes: regulations for consumer products | https://www.gov.uk/guidance/e-cigarettes-regulations-for-consumer-products | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-EESR-2016 | The Electrical Equipment (Safety) Regulations 2016 (SI 2016/1101) | https://www.legislation.gov.uk/uksi/2016/1101/contents | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-EORI | Get an EORI number | https://www.gov.uk/eori | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-EPR-PACKAGING | Extended producer responsibility for packaging: who is affected and what to do | https://www.gov.uk/guidance/extended-producer-responsibility-for-packaging-who-is-affected-and-what-to-do | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-FIREWORKS-LAW | Fireworks: the law | https://www.gov.uk/fireworks-the-law | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-FURNITURE-FIRE-1988 | The Furniture and Furnishings (Fire) (Safety) Regulations 1988 (SI 1988/1324) | https://www.legislation.gov.uk/uksi/1988/1324/contents | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-GPSR-2005-R7 | The General Product Safety Regulations 2005, regulation 7 (Other obligations of producers) | https://www.legislation.gov.uk/uksi/2005/1803/regulation/7 | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-HSE-BIOCIDES | HSE: Biocides (UK biocides regulation index) | https://www.hse.gov.uk/biocides/index.htm | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-IMPORT-CONTROLS | Import controls | https://www.gov.uk/guidance/import-controls | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-MHRA-DEVICES | Regulating medical devices in the UK | https://www.gov.uk/guidance/regulating-medical-devices-in-the-uk | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-NITROUS-OXIDE | Possession of nitrous oxide is now illegal (8 November 2023) | https://www.gov.uk/government/news/possession-of-nitrous-oxide-is-now-illegal | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-OFFWEAPONS-ORDER-1988 | The Criminal Justice Act 1988 (Offensive Weapons) Order 1988, Schedule (as amended) | https://www.legislation.gov.uk/uksi/1988/2019/schedule | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-OWA-2019 | Offensive Weapons Act 2019 — contents | https://www.legislation.gov.uk/ukpga/2019/17/contents | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-OWA-2019-S1 | Offensive Weapons Act 2019, section 1 (Sale of corrosive products to persons under 18) | https://www.legislation.gov.uk/ukpga/2019/17/section/1 | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-OWA-2019-S3 | Offensive Weapons Act 2019, section 3 (Delivery of corrosive products to residential premises etc) | https://www.legislation.gov.uk/ukpga/2019/17/section/3 | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-OWA-2019-S35 | Offensive Weapons Act 2019, section 35 (inserting CJA 1988 s141B remote sale defence conditions A-D) | https://www.legislation.gov.uk/ukpga/2019/17/section/35 | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-OWA-2019-S38 | Offensive Weapons Act 2019, section 38 (Delivery of bladed products to residential premises etc) | https://www.legislation.gov.uk/ukpga/2019/17/section/38 | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-OWA-2019-SCH1 | Offensive Weapons Act 2019, Schedule 1 (Corrosive products) | https://www.legislation.gov.uk/ukpga/2019/17/schedule/1 | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-PLUGS-1994-R12 | The Plugs and Sockets etc. (Safety) Regulations 1994, regulation 12 | https://www.legislation.gov.uk/uksi/1994/1768/regulation/12/made | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-PRAM-2025-S15 | Product Regulation and Metrology Act 2025, section 15 (Commencement) | https://www.legislation.gov.uk/ukpga/2025/20/section/15 | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-PRAM-2025-S2 | Product Regulation and Metrology Act 2025, section 2 (Product regulations: supplementary) | https://www.legislation.gov.uk/ukpga/2025/20/section/2 | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-PSTI-REGIME | The UK Product Security and Telecommunications Infrastructure (Product Security) regime | https://www.gov.uk/government/publications/the-uk-product-security-and-telecommunications-infrastructure-product-security-regime | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-PSTI-SI-2023-1007-SCH3 | PSTI (Security Requirements for Relevant Connectable Products) Regulations 2023, Schedule 3 (Excepted connectable products) | https://www.legislation.gov.uk/uksi/2023/1007/schedule/3/made | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-PSTI-SI-2023-1007-SCH4 | PSTI Regulations 2023, Schedule 4 (Statement of compliance: minimum information) | https://www.legislation.gov.uk/uksi/2023/1007/schedule/4/made | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-REACH-DEADLINES | HSE: Recognising EU REACH registrations under UK REACH (grandfathering) — submission deadlines | https://www.hse.gov.uk/reach/grandfathering-registrations.htm | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-RUSSIA-SANCTIONS | Russia sanctions: guidance (trade sanctions — imports) | https://www.gov.uk/government/publications/russia-sanctions-guidance/russia-sanctions-guidance | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-SINGLE-USE-PLASTICS | Single-use plastics bans and restrictions (England) | https://www.gov.uk/guidance/single-use-plastics-bans-and-restrictions | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-SINGLE-USE-VAPES | Single-use vapes ban | https://www.gov.uk/guidance/single-use-vapes-ban | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-TOYS-2011 | The Toys (Safety) Regulations 2011 (SI 2011/1881) | https://www.legislation.gov.uk/uksi/2011/1881/contents | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-TVA-2026 | Tobacco and Vapes Act 2026 (c. 18) — contents | https://www.legislation.gov.uk/ukpga/2026/18/contents | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-TVA-2026-S1 | Tobacco and Vapes Act 2026, section 1 (Sale of tobacco etc) | https://www.legislation.gov.uk/ukpga/2026/18/section/1 | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-TVA-2026-S175 | Tobacco and Vapes Act 2026, section 175 (Commencement: Parts 1 to 4) | https://www.legislation.gov.uk/ukpga/2026/18/section/175 | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-UKCA-GUIDANCE | Using the UKCA marking | https://www.gov.uk/guidance/using-the-ukca-marking | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-VAT-OMP | VAT and overseas goods sold to customers in the UK using online marketplaces | https://www.gov.uk/guidance/vat-and-overseas-goods-sold-to-customers-in-the-uk-using-online-marketplaces | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-VCRA-2006-S36 | Violent Crime Reduction Act 2006, section 36 (Manufacture, import and sale of realistic imitation firearms) | https://www.legislation.gov.uk/ukpga/2006/38/section/36 | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-VCRA-2006-S38 | Violent Crime Reduction Act 2006, section 38 (Meaning of realistic imitation firearm) | https://www.legislation.gov.uk/ukpga/2006/38/section/38 | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-WEEE-AMEND-2025 | The Waste Electrical and Electronic Equipment (Amendment, etc.) Regulations 2025 (made as SI 2025/910) | https://www.legislation.gov.uk/ukdsi/2025/9780348272512 | S2 | 2026-10-10 | webfetch |
| SRC-UK-GOV-WEEE-DISTRIBUTOR | Electrical waste: retailer and distributor responsibilities | https://www.gov.uk/electricalwaste-producer-supplier-responsibilities | S2 | 2026-10-10 | webfetch |
| SRC-UK-S3-HSF-OMP-2026 | From passive host to proactive gatekeeper: online marketplaces in the spotlight (HSF Kramer, 2026) | https://www.hsfkramer.com/ru/notes/tmt/2026-posts/from-passive-host-to-proactive-gatekeeper-online-marketplaces-in-the-spotlight | S3 | 2026-10-10 | search_snippet |
| SRC-UK-S3-LEWISSILKIN-GPSR-REFORM | UK government consults on proposals to reform the UK's general product safety framework (Lewis Silkin, 2026-06-01) | https://www.lewissilkin.com/en/insights/2026/06/01/uk-government-consults-on-proposals-to-reform-the-uks-general-product-safety-fra-102mzh8 | S3 | 2026-10-10 | search_snippet |
| SRC-UK-S3-QIMA-PSTI | Managing and Maintaining UK PSTI Statements of Compliance: A Guide | https://www.qima.com/blog/eletronics/guide-to-uk-psti-statement-of-compliance | S3 | 2026-10-10 | search_snippet |

## 待核实/冲突

1. **激光产品范围**：电子类目页禁止“便携式激光（含激光投影器）”，但审核页另列“Laser pointers and other laser products”（G201689020，抓取失败）。激光测距仪、激光水平仪、激光雕刻机、带激光的星空灯是否受限不明；OPSS 激光笔指引原文未找到可访问 URL。[R:UK-L1-ELEC-003]
2. **圆柱锂电池禁令的边界**：锂电池政策页把“含这些电池的产品”也列为禁售，但未说明内置不可拆卸电池组（如充电宝内部 18650 电芯）是否包括；电子类目页旧版只列 6 种型号。需以 G2HSXA2KM59YX5AT 全文与卖家实际申诉结果确认。[R:UK-L1-LIION-001]
3. **草本烟矛盾**：烟草页“允许”列有“已通报、不含烟草尼古丁的草本香烟和草本吸食混合物”，“禁止”又列“Herbal products for smoking”。规则按禁止处理。[R:UK-L1-TOBACCO-001]
4. **UK REACH 亚马逊专页**（GV2DFY75B5XRVXP9）、**GB CLP 专页**（GC2S377CLTYCA4WJ）、**EU BPR 页的 GB 部分**、**安抚奶嘴页**（GX9BGE7LAFRWAFHF）多次抓取只拿到导航壳或未抓取，亚马逊对 UK REACH/CLP 的具体文件要求（如 SDS、SVHC 声明）未核实；UK REACH 物品中 SVHC>0.1% 的信息传递义务原文未核对。[R:UK-L5-REACH-001]
5. **PSTI 无亚马逊专页**：搜索未发现亚马逊英国 PSTI 帮助页；亚马逊是否会要求上传 PSTI 符合性声明未知。“随附”是否可用链接存在争议（BSI 观点为不可，二手来源）。[R:UK-L5-PSTI-001]
6. **《2025 产品监管和计量法》后续条例**：2026 年三份咨询的日期、内容（在线市场义务、英国责任人、标签）仅来自律所文章搜索摘要，政府原文与最终结论未核实。[R:UK-L5-PRAM-001]
7. **《2026 烟草和电子烟法》御准日期**未在 legislation.gov.uk 页面显示，“御准后 6 个月生效”的第 1–4 部分（含第 10 条向 18 岁以下售电子烟/尼古丁产品）的确切生效日待核实。[R:UK-L5-TOBACCO-001]
8. **《2026 犯罪与治安法》**远程售刀/售弩新规（s32–43）为 prospective，未见生效令；需持续跟踪。[R:UK-L5-KNIFE-003]
9. **OWA 2019 第 40 条抗辩与第 41 条“bladed product”定义**未打开原文；远程售刀能否送往住宅地址取决于抗辩条件。[R:UK-L5-KNIFE-001]
10. **VCRA 仿真枪认可颜色清单**（条例原文）未打开。[R:UK-L5-FIREARM-001]
11. **家具防火条例适用范围**（第 3/4 条与附表细节）及 OPSS 改革进展未核实。[R:UK-L5-FIRE-001]
12. **电池法规**：分销商（年售 >32 kg）回收义务、电池标识要求未在本次政府页确认；英国新电池法规（参照欧盟 2023/1542）立法进展未核实。[R:UK-L5-BATT-001]
13. **HFSS**：批量促销限制和电视/线上付费广告禁令（《2022 健康与护理法》）的最新生效日期未核实；亚马逊页仍写“预计 2023-10”，明显过时。[R:UK-L5-HFSS-001]
14. **电热毯标准笔误**：亚马逊电热毯页写“SANS 60335-2-17”（南非标准编号），应为 BS EN 60335-2-17。[R:UK-L3-APPLIANCE-001]
15. **酒类许可**：亚马逊只把 Licensing Act 2003、AWRS 列为参考资源，是否必须持英国酒类许可视业务模式；但“卖家设立国须在英国”是明确要求。[R:UK-L2-ALCOHOL-001]
16. **审核子页未逐一核读**：服装审核（G200316920）、音乐/DVD、Made in Italy、有机食品（G2A9HY385WHJ4F84，已抓取未整理）等的英国站具体材料未整理。[R:UK-L2-CATEGORY-001]
17. **粘鼠板与电击项圈的英国法律依据**（《2022 粘鼠板（犯罪）法》、《2023 动物福利（电子项圈）（英格兰）条例》）未打开政府原文，规则仅以亚马逊政策为准。[R:UK-L1-ANIMAL-004]
18. **园艺泥炭**：亚马逊禁售，但英格兰业余园艺泥炭销售禁令的立法状态未核实。[R:UK-L1-PLANT-001]
19. **“通用款”一氧化碳报警器**的判定标准亚马逊未公开。[R:UK-L1-ALARM-001]
20. **无人机**：未找到亚马逊英国无人机专页；英国 CAA 的 UK 类别标识（UK0–UK6）和产品侧要求未核实。
21. **生物杀灭剂“处理过的物品”**（宣称抗菌的纺织品、砧板等）在 GB BPR 下的标签要求未核实。[R:UK-L5-BPR-001]
22. **英国站 GPSR 责任人**：与欧盟不同，GPSR 2005 没有单独的“英国责任人”条款；亚马逊英国是否会推出类似欧盟的“负责人”属性要求，取决于 PRaM 法案后续条例。[R:UK-L5-GPSR-001]
23. **FBA 食品**：FBA 禁运页把“食品饮料”列在“不符合条件的商品”项下（实为须符合食品指南 G200660860 与 Grocery 类目要求），本库按“合规后可 FBA”处理。[R:UK-L4-FBA-006]
24. **北爱尔兰**：亚马逊英国订单可配送至北爱，本库未对“仅售 GB”与“含 NI”分别建模；如需覆盖 NI，须同时满足 EU 规则（CE、EU 责任人、CPNP、EU 能效标签等）。[R:UK-L5-NI-001]
