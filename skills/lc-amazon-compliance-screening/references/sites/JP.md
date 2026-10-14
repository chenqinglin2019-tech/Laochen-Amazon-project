# 日本站（amazon.co.jp） 禁限售与合规要求

> 由调研分册合并生成（2026-10-11）。本文描述亚马逊平台政策和当地法规要求，不构成法律意见。
> [SRC-…] 为来源编号（见 rules/sources/），[R:…] 为机读规则编号（见 rules/sites/）。

## 第一部分 · 亚马逊平台政策（L1–L4）

> 规则包版本：draft · 调研日期：2026-10-10 · 本文只写亚马逊平台政策（L1 平台禁售、L2 平台限售/审核、L3 平台合规资料、L4 FBA/危险品）；日本法规（L5–L6，E 节及 F/G 节的法规部分）由另一份文件负责。不构成法律意见。
> 每条结论后用 [SRC-…] 标注来源（见 `rules/sources/JP_amazon.yaml`），用 [R:规则ID] 关联机读规则（`rules/sites/JP_amazon.yaml`）。
> 来源级别：本文引用的全部是 S1（亚马逊日本卖家平台帮助页，以 ja_JP 版为主、少数用 zh_CN 版，经 r.jina.ai 渲染抓取，快照在 `policy/snapshots/JP/`）。来源 ID 形如 [SRC-JP-AMZ-G200164330]，G 编号即帮助页编号。

### 先看这几条（运营速览）

1. **海外卖家 = 特定进口事业者（2025-12-25 起）**：从中国直接卖（自发货或 FBA）PSE、PSC、PSTG、PSLPG 四法对象商品，必须选任「国内管理人」，并以卖家自己的名义向经产省做事业届出；亚马逊审核时会看届出书上是否写有卖家本身和国内管理人的名称地址，不合格就删除 ASIN [SRC-JP-AMZ-GJXRBNGX52EMJZZB][R:JP-L3-4LAW-001]。
2. **锂电池收紧**：18650、21700 等圆柱形可充电锂电池（单卖、电池组、备用电芯、含此类电池的商品）在日本站禁售 [SRC-JP-AMZ-G2HSXA2KM59YX5AT][R:JP-L1-CYLLI-001]；锂电池、移动电源、便携电源须经亚马逊认可的第三方检测机构（TIC）验证 JIS C 62133-2、JIS C 62368-1 和 UN38.3 [SRC-JP-AMZ-GCWQ4DJP8LKVNRX8][R:JP-L3-LIB-001]，同时还要交 PSE 文件 [R:JP-L3-PSE-003]。
3. **种子类一刀切**：从海外进口或由海外居民销售的栽培用种子、苗、穗木、球根禁售；任何含植物种子的商品都不能入 FBA [SRC-JP-AMZ-G201737480][SRC-JP-AMZ-G201730840][R:JP-L1-SEED-001]。
4. **FBA 禁运范围宽**：气雾剂、消防法危险物、需设管理者的医疗器械（血压计、血氧仪、彩色隐形眼镜等）、钕磁铁、医药品、CBD、金券均不能入仓 [SRC-JP-AMZ-G201730840][R:JP-L4-FBA-006][R:JP-L4-MEDDEV-001]；但《危险品确认指南》又允许参加危险物纳品项目者限量入仓部分类别，两页说法冲突（见待核实）。
5. **健康类宣称极严**：没有取得医药品/医疗器械承认的食品、保健品、杂货不能标榜治疗/预防疾病，禁用词表包括「抗菌」「殺菌」「免疫」「ダイエット」「デトックス」「アンチエイジング」「育毛」等 [SRC-JP-AMZ-G202024200][R:JP-L1-CLAIM-001]。

### A. 禁售清单（L1）

亚马逊日本《制限対象商品》页共列 22 类 [SRC-JP-AMZ-G200164330]，另有《商品安全出品限制》禁售清单 [SRC-JP-AMZ-GRLKLZ6WQ9R259LC]。违规时亚马逊可立即暂停/终止销售、无偿销毁 FBA 库存，涉嫌违法时还可冻结或没收款项 [SRC-JP-AMZ-G200164330]。页面所列例子不是穷举；「可售例子」中的商品也仍须符合全部法令 [SRC-JP-AMZ-G200164330]。

#### A-1 按亚马逊 22 个制限类目

| 类别 | 亚马逊页面 | 禁止销售的典型商品 | 例外/允许销售的情况 | 规则ID |
|---|---|---|---|---|
| 酒类 | アルコール G200164340 | 无「酒類販売業免許」卖家出品的酒类；不符合酒税法的酒类；在「ワイン」以外分类出品的酒类、无酒精饮料及含其的礼盒 [SRC-JP-AMZ-G200164340] | 酒精度 <1% 饮料（无酒精啤酒风味饮料除外）、开瓶器/醒酒器、不含酒精的酿造套件、含酒精的点心、不含酒精的酒类纪念品 | JP-L1-ALCOHOL-001、JP-L2-ALCOHOL-001 |
| 动物及动物制品 | 動物と動物商品 G200164370 | 大部分活体动物；濒危物种（虎、豹、象、鳄、穿山甲、海龟、骆马等）及其毛皮羽毛；熊胆、猫狗部位、鲸豚鲨部位（鱼翅、鲸肉）；含动物牙齿的商品；特定外来生物、病害虫、需「动物取扱业」登记的动物；虎夹、雾网；尖刺项圈；人用/动物用疫苗 [SRC-JP-AMZ-G200164370] | 活贝类和甲壳类；饵料/饲料用活昆虫和蠕虫；明确标注为仿制品的仿龟甲等；鲨鱼牙饰品（与「含动物牙齿」禁令冲突） | JP-L1-ANIMAL-001、JP-L1-ANIMAL-002、JP-L1-ANIMAL-003、JP-L1-ANIMAL-004、JP-L1-PET-001、JP-L1-VACCINE-001 |
| 汽车摩托用品 | カー&バイク用品 G200164410 | 不合规消音器（含挡板易拆）、喇叭、尾翼、突出长螺母、车检不合格部件、违法改装件；限速解除器、排放作弊（含氧传感器模拟器）、故障灯屏蔽、里程表篡改；反测速车牌罩/喷剂；影响信号灯的装置；干扰器；驾驶证/VIN 牌；产权有瑕疵车辆；**电动滑板车、轻便摩托、原付、摩托车、电动乘骑玩具**；无型式认定的电助力自行车；无 E 标志儿童座椅；安全气囊和安全带及其组件 [SRC-JP-AMZ-G200164410] | 符合保安基准的 HID 套件、轮胎、汽车电池；符合消防法的汽油携行罐；取得型式认定的电助力自行车；特定小型原付须亚马逊许可 | JP-L1-AUTO-001、JP-L1-AUTO-002、JP-L1-AUTO-003、JP-L1-AUTO-004、JP-L1-AUTO-005、JP-L1-AUTO-006、JP-L1-AUTO-007、JP-L2-SMALLMOPED-001、JP-L3-AUTOPARTS-001、JP-L3-CARSEAT-001 |
| 医药部外品与化妆品 | 医薬部外品および化粧品 G200164470 | 无承认的医药部外品、无届出的化妆品；分装品；**个人进口代行**（无制造销售业许可者接单、海外直送）；药检作弊品；过期、开封、非原厂密封、缺外盒、「試供品/小売販売不可」；缺日文法定标示（含海外版包装平行进口）；召回品；含 THC/HHC 类物质或曾检出 THC 的 CBD 品牌系列 [SRC-JP-AMZ-G200164470] | 已依药机法正确标示的医药部外品、指定医药部外品、防除用医药部外品、动物用医药部外品、化妆品 | JP-L1-COSME-001、JP-L1-HEALTH-001、JP-L1-HEALTH-002、JP-L1-HEALTH-003、JP-L1-HEALTH-004、JP-L1-DRUGTEST-001、JP-L1-CANNABIS-001 |
| 货币及现金等价物 | 通貨、硬貨、および現金同等品 G200164450 | 现行法定纸币/硬币/纪念币；商品券、礼品券、礼品码、POSA 卡（亚马逊事先批准者除外）；汇票、邮票、旅行支票；伪钞及制造设备；加密资产；股票债券；金银铂地金 [SRC-JP-AMZ-G200164450] | 奖章、纪念章、挑战币、非贵金属纪念币等币状非货币物 | JP-L1-CURRENCY-001、JP-L1-CURRENCY-002、JP-L1-CURRENCY-003 |
| 保健品 | 栄養補助食品 G201829010 | 违法/危险药物；含医药成分或标榜药效的保健品（未承认医药品）；海外药品；需处方的商品；含麻黄、鹿茸、甲状腺/肾上腺提取物、锗；USADA 高风险补充剂；宣称类固醇效果；用病名作关键词；过期或到货即过期；开封、非原厂密封、试用装；缺法定标示；THC/CBD 相关 [SRC-JP-AMZ-G201829010] | 未被禁止且标示全部成分名称的保健品 | JP-L1-DRUGS-001、JP-L1-DRUGS-002、JP-L1-SUPP-001、JP-L1-SUPP-002、JP-L1-HEALTH-001、JP-L1-FOOD-003 |
| 医药品 | 医薬品 G200164490 | 违法/危险药物；未承认医药品；**要指导医药品**；体外诊断用医药品；处方药（医疗用医药品）；需处方或专业指导的商品（隐形眼镜除外）；分装药；**个人进口代行**；诊断用途检测试剂盒及需寄样本的检测；新冠等违法功效表示；亚马逊禁止的 OTC 药 [SRC-JP-AMZ-G200164490] | 持「医薬品店舗販売業/薬局」许可并通过亚马逊 OTC 审核者，可出品亚马逊 OTC 清单内药品；持许可的动物用医药品 | JP-L1-DRUGS-001、JP-L1-DRUGS-002、JP-L1-DRUGS-003、JP-L1-DRUGS-004、JP-L2-DRUGS-001、JP-L2-VETDRUG-001 |
| 武器 | 武器および武器を模した商品 G200164950 | 弹药、火药、底火、空包、空弹壳；爆炸物、信号弹/信号枪、手榴弹（含训练用）、地雷、烟雾弹；全部枪炮及主要部件、古董枪、麻醉枪、水中枪、线圈枪；可能被认定为真枪/仿造枪的玩具枪；钢制双刃 ≥5.5cm、刃长 ≥15cm 的刀；蝴蝶刀、匕首、笔刀、靴刀、推刀、潜水刀、投掷刀；自动/弹簧助开/重力/指虎刀、卡兰比特；伪装刀、手里剑（含手里剑陀螺）、隐形刀；棍棒、警棍、指虎、双节棍、拐、万力锁、狼牙棒；泰瑟枪、弹弓、弩；军警专用品 [SRC-JP-AMZ-G200164950] | BB 弹、海绵弹；枪托、枪套、瞄准镜等配件；ASGK/JASG/STGA 会员厂商的玩具枪；水枪、泡泡枪；菜刀、水果刀、瑞士军刀、剪刀、柴刀（剑鉈除外）、斧、击剑剑、未开刃练习刀、非钢制模造刀；6–15cm 单刃刀加注两条警示；辣椒喷雾、战术笔、夜视仪；加注「18 岁以下请勿购买」的手铐 | JP-L1-AMMO-001、JP-L1-EXPLOSIVE-001、JP-L1-FIREARM-001、JP-L1-TOYGUN-001、JP-L1-KNIFE-001、JP-L1-KNIFE-002、JP-L1-KNIFE-003、JP-L1-KNIFE-004、JP-L1-WEAPON-001、JP-L1-WEAPON-002、JP-L2-TOYGUN-001、JP-L3-KNIFE-001、JP-L3-HANDCUFF-001 |
| 食品饮料 | 食品&飲料 G200164550 | 不符合食品卫生法、食品标示法、JAS 法、健康增进法、计量法、景表法的进口食品；盐/米/酒/畜产品/含医药成分保健品的个人进口代行；易腐食品、带透气孔的味噌；无许可制造的商品、无许可酒类；过期或到货即过期；鲸/豚/鲨肉；无个体识别号的特定牛肉；未标「加热用」的牛肝；禁止进口地区的肉类；冒充特别用途食品（如「経口補水液」）[SRC-JP-AMZ-G200164550] | 依法标示、包装、密封并妥善保管运输的食品饮料 | JP-L1-FOOD-001、JP-L1-FOOD-002、JP-L1-FOOD-003、JP-L1-FOOD-004、JP-L1-FOOD-005、JP-L1-FOOD-006、JP-L1-HEALTH-003 |
| 成人用品 | アダルト商品 G201856210 | 卖家创建成人 DVD 的 ASIN；无著作权许可的成人同人作品；未设成人标志或不在规定浏览节点的成人商品；露出性器等部位的商品；带头部的性爱娃娃（充气娃娃除外）；逼真性器仿制品；非自愿暴力性交/兽交主题；青少年条例指定有害图书；违反刑法/儿童色情法；含性刺激的未满 18 岁儿童图像 [SRC-JP-AMZ-G201856210] | 经 JCRC/VISC/JVPS/EOCS/EJCS/CERO 审查并有审查编号的成人影像和游戏 | JP-L1-ADULT-001、JP-L1-ADULT-002、JP-L2-ADULTMEDIA-001、JP-L3-ADULTFLAG-001 |
| 令人不快商品 | 不快感を与える商品 G201856230 | 宣扬仇恨、暴力、歧视、恐怖组织、自杀或美化罪犯的商品；人道悲剧与灾害相关商品；描绘儿童虐待或性化儿童；含成人内容的儿童用品；不符年龄的儿童商品（不适用于图书、音乐、影像、DVD）[SRC-JP-AMZ-G201856230] | 亚马逊判断具有历史意义的商品 | JP-L1-OFFENSIVE-001、JP-L1-OFFENSIVE-002 |
| 亚马逊设备 | G202029820 | Kindle/Fire 等亚马逊设备本体及其维修/保养配件一律禁止第三方出品 [SRC-JP-AMZ-G202029820] | 非维修配件按配件指南出品 | JP-L1-AMZDEVICE-001、JP-L2-AMZACC-001 |
| 电器与电子 | 電化製品・電子機器 G202082120 | 助长侵权的流媒体播放器；影响信号灯的商品；序列号被去除/篡改；CB 功放；各类干扰器、雷达移频器；有线/卫星电视解扰设备及手册；便携式激光商品；破解版权保护的 DVD 复制机；区域码破解蓝光机；ESN 不正当手机；**无 PSE 的彩灯和延长线**；特定流媒体/语音助手设备及配件；无 PSE 的电气用品、无技适的无线设备、无 PSC 的特定制品、无家庭用品质量标示的家电 [SRC-JP-AMZ-G202082120] | 有技适的无线设备和微弱无线设备；有 PSE 的电气用品；有 PSC 的消费生活用制品（便携激光除外） | JP-L1-ELEC-001、JP-L1-ELEC-002、JP-L1-STREAMING-001、JP-L3-PSE-001、JP-L3-RADIO-001、JP-L3-HOUSEHOLDLABEL-001 |
| 激光商品 | レーザー商品 G201689020 | 3R、3B 及以上激光（激光笔、激光秀投影仪）；无 PSC 的便携式激光应用装置 [SRC-JP-AMZ-G201689020] | 1 级、2 级激光（详情页须写等级） | JP-L1-LASER-001、JP-L3-LASER-001 |
| 医疗器械 | 医療機器の取り扱いについて G202112340 / 医療機器および関連商品 G200164650 | 未承认/无许可医疗器械（例：祛痣膏、未承认激光脱毛器）；需处方的器械；分装品；无许可进口；过期、开封、非原厂密封、试用装、缺法定标示；向消费者无限制销售的医家向器械；被改动性能/用法的器械；**FBA 销售特定管理/特定保守管理器械** [SRC-JP-AMZ-G200164650] | 一般医疗器械、管理医疗器械、特定管理医疗器械在法定标示齐全、无广告销售限制时可售；FBA 仅限一般医疗器械和家庭用管理医疗器械 [SRC-JP-AMZ-G202112340] | JP-L1-MEDDEV-001、JP-L2-MEDDEV-001、JP-L4-MEDDEV-001、JP-L4-MEDDEV-002 |
| 盗窃品与开锁工具 | 盗難品およびピッキングツール G200164850 | 序列号被去除/篡改的商品；破坏用锁芯扳手、开孔锯、猫眼开锁器、自动锁旁路钥匙/抖动钥匙、手铐隐藏钥匙、数字解码器、撬锁卡/拨片枪、撬锁套装、防盗标签解除器、开车门钢片、张力扳手、试开钥匙、管状锁撬锁器；钥匙复制装置；代码截取设备；万能钥匙；透明练习挂锁 [SRC-JP-AMZ-G200164850] | 空白钥匙 | JP-L1-LOCKPICK-001、JP-L1-STOLEN-001 |
| 植物与种子 | 植物および種子製品 G201737480 | 有害植物、特定外来生物、稀有物种；植物防疫法不准进口的植物；致命植物（海檬果种子等）；**海外进口或海外居民销售的栽培用种子、苗、穗木、球根** [SRC-JP-AMZ-G201737480] | 不受管制的植物、植物制品和种子（日本国内卖家） | JP-L1-PLANT-001、JP-L1-SEED-001 |
| 召回商品 | リコール対象商品 G200164750 | 被制造商、进口商、事业者或行政机关召回的商品 [SRC-JP-AMZ-G200164750] | — | JP-L1-RECALL-001 |
| 烟草 | タバコおよびタバコ関連商品 G200164910 | 卷烟、雪茄、鼻烟、尼古丁凝胶、加热烟草、无烟烟草（片状烟、口香糖、嚼烟、Dip、Snus、Wad）；含尼古丁/医药成分的电子烟及其烟弹、雾化器、充电器、烟油；尼古丁吸入器/鼻喷剂；未获日本批准的戒烟产品（Tabex）；大麻水烟管、各类吸食烟斗、Rose in a Glass、金属丝卷烟纸；THC/HHC 相关 [SRC-JP-AMZ-G200164910] | 烟灰缸、雪茄剪、卷烟纸、水烟管、雪茄保湿盒、打火机、烟斗、加热烟草配件、无烟草收藏品、已获准市售的尼古丁口香糖/贴片 | JP-L1-TOBACCO-001、JP-L1-VAPE-001、JP-L1-PARAPHERNALIA-001、JP-L1-CANNABIS-001 |
| 其他商品 | その他の商品 G201856250 | 裸石/未加工宝石；非正规经销或无厂商保证的宝石商品（含手表）；无 PSC 的 PSC 对象；无 PSTG/PSLPG 的燃气器具；无检查刻印的高压气瓶；需许可的放射性同位素（氚）商品；核原料物质；计量法不合规商品；无质量标示的家庭用品；不符合食品卫生法的餐厨具、容器、玩具；无 PSC 的磁铁套装、吸水膨胀球；禁止 RMT 的游戏货币/道具；无 JAN/ISBN 的书籍（同人志）；不合规进口食品；尖刺项圈；不合规饲料；特定继续性服务和业务提供诱引销售交易；内容不明的神秘盒；未加注法规提示的焚烧炉；10L 以上汽油类燃料（须写容量）；「Washington Redskins」商品；制裁对象（从古巴、伊朗、朝鲜、克里米亚、顿涅茨克、卢甘斯克进口或原产的商品 [SRC-JP-AMZ-G201575280]）；帮助标志（ヘルプマーク）[SRC-JP-AMZ-G201856250] | — | JP-L1-GEMS-001、JP-L1-RMT-001、JP-L1-DOUJIN-001、JP-L1-MYSTERYBOX-001、JP-L1-GASOLINE-001、JP-L1-RADIOACTIVE-001、JP-L1-SANCTIONS-001、JP-L1-REDSKINS-001、JP-L1-HELPMARK-001、JP-L3-GAS-001、JP-L3-GAS-002、JP-L3-HPGAS-001、JP-L3-KEIRYO-001、JP-L3-FEED-001、JP-L3-INCINERATOR-001、JP-L3-FOODCONTACT-001 |
| 化学品、农药、肥料 | 化学物質、農薬および肥料 GD3XAGGJX2T2NRCK | 毒物剧物；不符合有害物质含有家庭用品规制法的商品；含或可能含石棉的商品；含化审法规制成分的商品；未做农药销售届出者出品农药；无第 16 条标示的农药；被禁止销售的农药；无第 22 条标示的除草剂；未做肥料销售届出者出品肥料；无保证票/未登录的普通肥料、无标示的特殊肥料 [SRC-JP-AMZ-GD3XAGGJX2T2NRCK] | 已届出且标示合规的农药、肥料；有标示并注明「農薬として使用することができない」的除草剂 | JP-L1-CHEM-001、JP-L1-CHEM-002、JP-L1-ASBESTOS-001、JP-L1-PESTICIDE-001、JP-L3-PESTICIDE-001、JP-L3-HERBICIDE-001、JP-L3-FERTILIZER-001、JP-L3-HAZHOUSEHOLD-001 |
| CBD | カンナビジオール（CBD）商品 G47GNYPBWSRVPADT | 含尼古丁/医药成分的 CBD；含 THC 的大麻制品；曾检出 THC 的 CBD（含同品牌/系列）；有医药功效或夸大宣称；类 THC/HHC 物质；**FBA 一律禁运** [SRC-JP-AMZ-G47GNYPBWSRVPADT] | 逐 ASIN 提交 THC 分析报告并获出品许可，且仅限自发货 | JP-L1-CBD-001、JP-L1-CANNABIS-001、JP-L2-CBD-001、JP-L4-FBA-011 |

#### A-2 《商品安全出品限制》禁售清单（不适用文件审核）

亚马逊日本以安全为由直接禁售以下商品，不走文件审核流程 [SRC-JP-AMZ-GRLKLZ6WQ9R259LC][SRC-JP-AMZ-GXMGGPL6LC4CVXHT]：

| 类别 | 禁售商品 | 规则ID |
|---|---|---|
| 化学制品 | 燃烧室开放或可燃烧中补燃料的凝胶/液体燃料火盆和壁炉 [SRC-JP-AMZ-G5P5YMQXX9Y34NVU]；叠氮化钠 [SRC-JP-AMZ-GXE3TPKYT83DDWJM]；三氯乙酸（TCA）及含 TCA 商品 [SRC-JP-AMZ-GKD2ZVSS3AZM4AQT]；含二氯甲烷或 NMP 的脱漆剂（2019-03 起）[SRC-JP-AMZ-GW6HK2RDRNNFW2ML] | JP-L1-FIREPIT-001、JP-L1-CHEM-003、JP-L1-CHEM-004、JP-L1-PAINTSTRIP-001 |
| 儿童用品 | 研磨风筝线 [SRC-JP-AMZ-GC277GB53473J65C]；串珠/琥珀磨牙首饰、串珠夹和串珠链、蘑菇形磨牙器/奶嘴 [SRC-JP-AMZ-GDPSRCGVBFSFY78H]；儿童颈部浮圈 [SRC-JP-AMZ-G9LKRHDUQ5AV3ECD]；兜帽/领口带抽绳、面向 7 岁以下或 120cm 以下儿童的上衣 [SRC-JP-AMZ-G8FDB4PSHS4AACQ5]；婴儿床围（含成套寝具中的）[SRC-JP-AMZ-G2E9DBAG4GYSQ5LT]；婴儿睡姿固定器、大象睡枕、婴儿枕、带支撑枕的垫子、倾斜型婴儿床及配件 [SRC-JP-AMZ-GX44XMQX3ZKWRPZR]；布制婴幼儿固定系统 [SRC-JP-AMZ-G202137200]；2 岁以下婴幼儿口罩 [SRC-JP-AMZ-GRBE9D3BXQJPMA6V]；婴儿自主喂食装置、免手扶奶瓶支架 [SRC-JP-AMZ-GUG6JJCDN6YYQYJP]；美人鱼尾泳衣（含单鳍款）[SRC-JP-AMZ-GPQBDFAYL3LCWYD2]；牙签弩 [SRC-JP-AMZ-GEJ6L4MMBHVZGLND]；婴幼儿加重寝具 [SRC-JP-AMZ-GKDFVJSUHPYTRHW3] | JP-L1-KITESTRING-001、JP-L1-TEETHING-001、JP-L1-NECKFLOAT-001、JP-L1-DRAWSTRING-001、JP-L1-CRIBBUMPER-001、JP-L1-SLEEPPOS-001、JP-L3-CARSEAT-001、JP-L1-INFANTMASK-001、JP-L1-SELFFEED-001、JP-L1-MERMAID-001、JP-L1-TOOTHPICKXBOW-001、JP-L1-WEIGHTEDBED-001 |
| 电子 | 电池驱动的加热衣物和鞋垫 [SRC-JP-AMZ-GFQMECECLTJCUE3H]；圆柱形可充电锂电池（18650/21700 等，热缩密封带端子连接器的除外）[SRC-JP-AMZ-G2HSXA2KM59YX5AT]；附圆柱形锂离子电池（含带充电端子者）的 LED 头灯 [SRC-JP-AMZ-GGKSRLQBRTPLHH7C]；家用 UVC 灭菌器、小型 UVC 杀菌灯、更换用 UVC 灯泡 [SRC-JP-AMZ-G5ZEPL3F3YQR5GUS]；E-27 型 LED 灯泡；Samsung Galaxy Note 7 | JP-L1-HEATEDWEAR-001、JP-L1-CYLLI-001、JP-L1-HEADLAMP-001、JP-L1-UVC-001、JP-L1-E27LED-001、JP-L1-NOTE7-001 |
| 生活/汽车 | 安全气囊（新品和二手）及组件、安全带警报消除器、车用加热座垫（有起火事故报告）、安全带导向带等辅助器、安全带 [SRC-JP-AMZ-G7TCXG6EJL23BY7E][SRC-JP-AMZ-GT8V6T7U8GZZK3SU] | JP-L1-AUTO-005、JP-L1-AUTO-006 |
| 食品 | Mad Honey（疯狂蜂蜜，又称 Deli Bal）[SRC-JP-AMZ-GK6MW7WEWN6BP587] | JP-L1-MADHONEY-001 |

#### A-3 广告宣传语禁令

日本未取得医药品或医疗器械承认的商品（食品、保健品、杂货等，部分保健功能食品除外）不得宣称治愈、缓解、治疗、预防疾病。亚马逊列出的禁用疾病/功效包括：癌症、性病类、肝炎、HIV/AIDS、阿尔茨海默、痴呆、心脑血管、糖尿病、流感、青光眼/白内障、ADHD、抗细菌、抗微生物、抗真菌、抑郁、肥胖、自闭症、增强性能力、丰胸、血压/血栓/血糖、抗衰老、代谢综合征、滋养强壮、花粉症、便秘、骨质疏松、特应性皮炎、胆固醇、风湿、关节痛、过敏、更年期、激素、免疫、湿疹瘙痒、感冒咳嗽、减肥瘦身、排毒、痤疮、腰痛肩颈痛、贫血、宿醉、增肌、血液清洁、血液循环、抗氧化、细胞再生、龋齿牙周病、视力听力、疤痕、新陈代谢、失眠、体质改善、生发、抑毛、浮肿、打鼾、拇外翻、睡眠呼吸暂停、杀菌、对特定细菌病毒有效、疲劳恢复等 [SRC-JP-AMZ-G202024200][R:JP-L1-CLAIM-001]。环境表示不得误导 [R:JP-L3-ECOCLAIM-001]。

### B. 审核与限售（L2）

#### B-1 出品许可（出品許可）通用流程

- **哪些要许可**：可能针对单个 ASIN、品牌、特定分类中的品牌、分类、子分类设限，一个商品可能要多个许可 [SRC-JP-AMZ-G200333160][SRC-JP-AMZ-G84EFS4CKK43USMF]。日本站帮助页**没有**公布完整的需许可分类清单（已确认的有「食品」类目 [SRC-JP-AMZ-G201511970]（见「カテゴリー別の補足ガイドライン」[SRC-JP-AMZ-G200333170]） 和流媒体播放器 [SRC-JP-AMZ-G202183590]），只能在卖家平台「商品登録」搜索商品看状态：「非対応」=不能卖、「この商品を出品する」=无需许可、「出品許可を申請」=需要许可，点「制限を表示」看要求 [SRC-JP-AMZ-G200333160][R:JP-L2-APPROVAL-001]。
- **准备材料**：180 天内的采购发票、商品各面清晰照片、品牌授权书（如适用）、安全证书（如需要）[SRC-JP-AMZ-G200333160]。
- **路径**：卖家平台 > 商品登録 > 搜索商品 > 「出品を申請」> 填表上传 > 等待 2–7 个工作日；草稿和进度在「出品申請」控制面板管理 [SRC-JP-AMZ-G200333160]。
- **结果**：显示「申請に必要な要件を満たしていません」即不能出品、不能申诉，卖家支持也不提供更多信息；已在售商品可能因新限制、绩效通知或合规要求变化失去权限 [SRC-JP-AMZ-G200333160][SRC-JP-AMZ-G84EFS4CKK43USMF]。
- **品牌名**：创建 ASIN 时品牌名报错，按「Amazon 品牌名称政策」提交品牌信息、带品牌标识的商品图片和库存信息 [SRC-JP-AMZ-G200333160]。

#### B-2 商品级审核与资质

| 品类 | 要求 | 申请/提交位置 | 规则ID |
|---|---|---|---|
| 酒类 | 酒類販売業免許（通信销售须通信販売酒類小売業免許）；仅在「ワイン」分类出品；年龄确认 [SRC-JP-AMZ-G200164340] | 具体提交路径页面未写（待核实） | JP-L2-ALCOHOL-001 |
| 一般用医药品（OTC） | 医薬品店舗販売業或薬局许可 + 卖家信息页写明必要事项 + 亚马逊 OTC 出品审核；只能卖亚马逊 OTC 清单内商品，不能自建 ASIN [SRC-JP-AMZ-G200164490] | 按亚马逊 OTC_Drugs_Guideline 申请 | JP-L2-DRUGS-001 |
| 动物用医药品 | 動物用医薬品店舗販売業许可 + 卖家信息页写明必要事项 [SRC-JP-AMZ-G200164490][SRC-JP-AMZ-G200329080] | — | JP-L2-VETDRUG-001 |
| 医疗器械 | 收到亚马逊邮件后提交医疗器械信息登记表、附带文书、法定标示照片；高度管理/特定保守管理器械须出示销售业许可证；不同店铺可登录的器械类别不同 [SRC-JP-AMZ-G202112340] | Eメール cops-jp-umcc-seller@amazon.co.jp | JP-L2-MEDDEV-001 |
| CBD | 每个 ASIN 的 THC 成分分析报告 + 实物标签照片；不能 FBA [SRC-JP-AMZ-G47GNYPBWSRVPADT] | 帮助 > 获取支持 > Amazon 出品服务 > 我的问题未列出 > 「CBD商品の出品申請」> Eメール | JP-L2-CBD-001 |
| 玩具枪/气枪 | 仅 ASGK、JASG、STGA 会员厂商或亚马逊认可品牌 [SRC-JP-AMZ-G200164950] | 页面未写（待核实） | JP-L2-TOYGUN-001 |
| 流媒体播放器 | 列在需出品许可商品中 [SRC-JP-AMZ-G200333160] | 出品許可申請 | JP-L2-STREAMING-001 |
| 亚马逊设备用配件 | 商品名不得含亚马逊设备商标；无 WWAA 认证不得写「Alexa 対応」[SRC-JP-AMZ-G200500100] | — | JP-L2-AMZACC-001 |
| 成人影像/游戏 | 日本伦理审查团体审查编号；卖家不得创建成人 DVD ASIN [SRC-JP-AMZ-G201856210] | — | JP-L2-ADULTMEDIA-001 |
| 特定小型原付 | 汽车页写「亚马逊许可的除外」，电动出行页直接列为禁售 [SRC-JP-AMZ-G200164410][SRC-JP-AMZ-GMUW6CKYLY4AP8MK] | 未写 | JP-L2-SMALLMOPED-001 |
| 食品类目（含饮料、保健品、宠物食品） | 限制新卖家：须申请批准；采购发票须含 ≥10 件商品（不收收据/形式发票/报价单）；之后提供分析报告等；新品、日文标签、JAN 码、政府许可；冷藏/冷冻/温控商品按温度储运（鲜肉 -2～5℃、冷藏 0～10℃、冷冻 ≤-15℃、巧克力 <28℃）[SRC-JP-AMZ-G201511970] | 类目要求页「请求批准」 | JP-L2-FOOD-001 |
| 新品限定类目 | ドラッグストア、ビューティ、食品&飲料、ジュエリー、腕時計、服&ファッション小物、シューズ&バッグ只能以新品出品，二手/翻新不可 [SRC-JP-AMZ-G200332540] | 出品时选择状况 | JP-L2-CONDITION-001 |

#### B-3 季节性限制

本次在日本站帮助页中**没有找到**季节性销售限制（如美国站巧克力等温敏商品的夏季限制）的页面；与之相关的只有 FBA 不收需冷藏/温控商品 [SRC-JP-AMZ-G201730840][R:JP-L4-FBA-002]。列入待核实。

#### B-4 强化安全合规（文件审核）类目

《リコールと商品の安全性》页列出出品时须提交文件审核的商品类型 [SRC-JP-AMZ-GXMGGPL6LC4CVXHT]，要点：
- 电气用品的本体、附带 AC 适配器和可拆卸锂电池都按 PSE 审核；带 Wi-Fi/Bluetooth 的商品按电波法审核；带 Qi 无线充电或 UVC 消毒功能的另交文件 [SRC-JP-AMZ-GXMGGPL6LC4CVXHT]。
- 覆盖类别：玩具（儿童饰品、指尖陀螺、隐形墨水笔、捏捏乐、磁性橡皮泥、磁力片、发射玩具、组合玩具、户外游具、磁铁娱乐用品、吸水树脂玩具、儿童玩具）；儿童用品（背带、儿童伞、推车风扇、推车、学步车、双层床）；防灾安全（防烟/防毒/防尘口罩、火灾报警器、CO 报警器、灭火器、坠落制止器、日食眼镜）；生活用品（暖水袋、硅藻土、压力锅）；家电（AC 适配器、充电器、延长线、智能插座、各类锂电池、灯具、取暖器、厨电、美容美发、风扇、空净、加湿除湿、吸尘器、熨斗、碎纸机、UVC、发射器、无线 LAN、无线充、音箱、摄像头、干扰器、投影仪、耳机、手表）；休闲（便携电源、便携冰箱、登山绳、无人机、头灯、对讲机）；车辆（电瓶充电器、应急启动电源、千斤顶、儿童座椅、头盔、电动出行设备、改装套件）；激光（带激光的测温枪、测距仪、激光笔）；化学品（脱漆剂）；燃气（卡式炉、燃气暖炉）[SRC-JP-AMZ-GXMGGPL6LC4CVXHT]。
- 新建 Listing 可能先被拦截，须在「出品制限を確認する」提交合规信息 [SRC-JP-AMZ-GKCHRSWHXB5WZHAU][R:JP-L3-NEWLISTING-001]；已在售商品在「账户状况 > 商品規約の遵守」提交文件或申诉 [SRC-JP-AMZ-GC35Z63FGCUCUWXX]。
- 部分品类（锂电池、移动电源、便携电源）改为由亚马逊认可的第三方检测/认证机构（TIC）直接验证并代交，卖家不再自行上传 [SRC-JP-AMZ-GCWQ4DJP8LKVNRX8]。

### C. 按品类的平台合规资料（L3）

提交文件的通用要求：原件、未修改、不得由计算机/AI 生成；不得来自「暂停中的验证实验室」；说明书/标签/警告须为日文；图片须证明与详情页商品一致并显示各面；套装逐件提供；文件名含 ASIN [SRC-JP-AMZ-GHJPQ6KDLA9N5F4L][SRC-JP-AMZ-G9JNNQBWXCMMCGE2][R:JP-L3-DOCQUALITY-001]。

| 产品族 | 亚马逊要求的文件/Listing 属性 | 提交位置 | 规则ID |
|---|---|---|---|
| 电气用品通用（PSE） | 事业届出副本（经产省受理章+型式区分；或保安ネット信息；海外卖家须含本人名称和国内管理人）；全数自主检查记录；铭牌照片（PSE 标志、届出事业者名、额定值）；简称承认证明（如有）；可用 S 标志证书+届出替代 [SRC-JP-AMZ-GHJPQ6KDLA9N5F4L]；吹风机/卷发棒、电暖器、延长线、串灯、吸顶灯、脱毛仪、LED 灯泡、美容仪、煤油暖风机、汽车电瓶充电器等产品页均按此审核 [SRC-JP-AMZ-GKC4WZW2VWSAPLKT][SRC-JP-AMZ-GBJZXSGPP8KTAHES][SRC-JP-AMZ-G8Z2QTQFT3KSZ9KR][SRC-JP-AMZ-G202137960][SRC-JP-AMZ-G7PDM6BTH8UZTZRZ][SRC-JP-AMZ-GKP4BFU3VHDXXEXV][SRC-JP-AMZ-G23UM4EWBTCN7B9M][SRC-JP-AMZ-GAPFH5HZK2U2H4PF][SRC-JP-AMZ-GG286TPSDRM6PLE2][SRC-JP-AMZ-G8U478XNGKRPLH3B] | jp-electronics-safety@amazon.co.jp | JP-L3-PSE-001 |
| AC 适配器、USB 充电器、延长线等特定电气用品（菱形 PSE） | 上述文件 + 登记检查机关签发的适合性检查证明书（型号与铭牌一致）；铭牌须显示检查机关名 [SRC-JP-AMZ-GDJWZYLHGEFVQ9KK][SRC-JP-AMZ-GHJPQ6KDLA9N5F4L] | 同上 | JP-L3-PSE-002 |
| 移动电源、更换/兼容锂电池、便携电源 | 圆形 PSE 文件；或 PSE 对象外的体积能量密度确认书+规格书；另附公司名、卖家 token、ASIN 及每个 ASIN 的进口商/工厂名 [SRC-JP-AMZ-GSJFE8S8AES7F7VG][SRC-JP-AMZ-GP8ECC9H3JWXRCAP][SRC-JP-AMZ-GYR9JPM3V2MDWPQ2][SRC-JP-AMZ-G2TJY9F8283XBAB2] | 同上 | JP-L3-PSE-003 |
| 锂电池、移动电源、便携电源、应急启动电源 | JIS C 62133-2（或 IEC/EN）、JIS C 62368-1（或 IEC/EN）、UN38.3 报告 + BTS，ISO 17025 实验室出具，经 TIC 验证（应急启动电源页同）[SRC-JP-AMZ-GCWQ4DJP8LKVNRX8][SRC-JP-AMZ-GUTZ2R2DD6P2UMVB][SRC-JP-AMZ-GGRZ8EFYCTYN7VRD] | TIC 机构代交（GUTZ2R2DD6P2UMVB） | JP-L3-LIB-001 |
| 锂电池家电 | JIS C 9335-1 + 对应 9335-2-x 分则（吸尘器 2-2、料理机 2-14、空净 2-65、风扇 2-80、加湿器 2-98、除湿/空调 2-40、吹风机 2-23、充电器 2-29）+ 电池 62133-2/UN38.3/BTS [SRC-JP-AMZ-G8TM22XFM7WXCRDC] | 账户状况页面 | JP-L3-LIAPPL-001 |
| 锂电池智能家居/消费电子 | JIS C 62368-1（耳机、音箱、摄像头、平板、门铃等）或 JIS C 1010 系列（环境传感器、万用表、钳表）+ 电池报告 [SRC-JP-AMZ-GA2PQDTU5HMC7CRZ] | 账户状况页面 | JP-L3-LISMART-001 |
| 无线设备（Bluetooth/Wi-Fi 等） | 技适证明书 + 技适铭牌照片；详情页写明符合电波法和频段；无线耳机、智能手表、无线 LAN、无线音箱、智能插座、对讲机、发射器、家用摄像头、（合法用途的）干扰类设备页均按此审核 [SRC-JP-AMZ-GV3N5ES8KNR3W3VG][SRC-JP-AMZ-G202082120][SRC-JP-AMZ-GFVXRS7EZ8DY8TLT][SRC-JP-AMZ-GABNR57VJTUDKECV][SRC-JP-AMZ-GRBJLG9QTR5ZQURQ][SRC-JP-AMZ-GDFTVKADLD9EU58M][SRC-JP-AMZ-GSQZZGJ8SXC2HC4Q][SRC-JP-AMZ-GS828T4S4CFMFREQ][SRC-JP-AMZ-GR5HZPEMV6MQUDGJ][SRC-JP-AMZ-G9FTYWHNN48XP4ZZ][SRC-JP-AMZ-GJT34NFP87EZXQ2K] | jp-giteki-safety@amazon.co.jp | JP-L3-RADIO-001 |
| 微弱无线（FM 发射器等） | 微弱无线局检测报告或 JAAMA/EMCC/TELEC 证明 + ELP/TELEC 标志 [SRC-JP-AMZ-GV3N5ES8KNR3W3VG] | 同上 | JP-L3-RADIO-002 |
| 指定无线设备（业余/CB 无线电） | 详情页写明需执照+频段；售后告知执照要求、刑罚、申请地点 [SRC-JP-AMZ-G202082120] | 详情页/买家联系 | JP-L3-RADIO-003 |
| 无线充电器 | Qi ID、品牌、商品名、型号、登记日期，须与 WPC 登记一致 [SRC-JP-AMZ-G2VRUQKXAFZUVNP9] | jp-giteki-safety@amazon.co.jp | JP-L3-QI-001 |
| 无人机 | PSE + 电波法文件 [SRC-JP-AMZ-GD8DGXG3Q3Y92UYH] | 同 PSE/电波法 | JP-L3-DRONE-001 |
| 平衡车、电动独轮车、电动滑板、电助力自行车 | PSE、电波法、UL 2272 报告；电助力车提交型式认定证明和标签图片 [SRC-JP-AMZ-GMUW6CKYLY4AP8MK] | jp-e-mobility@amazon.co.jp | JP-L3-EMOBILITY-001 |
| 电动出行电池 | 电动自行车/滑板车用：UL 2271；其他：PSE [SRC-JP-AMZ-G7HM69VDEMRW7TPE] | 账户状况页面 | JP-L3-EMOBBATT-001 |
| PSC 特别特定制品（婴儿床、便携激光、打火机等） | 事业届出、登记检查机关适合性证明书（含有效期）、检查记录、PSC 标志等标示照片；激光笔、激光测距仪、带激光测温枪按此审核 [SRC-JP-AMZ-G9JNNQBWXCMMCGE2][SRC-JP-AMZ-GYZPAMEJCXFTZHH5][SRC-JP-AMZ-GCWJK56TEF5RHCZ4] | 账户状况页面 | JP-L3-PSC-001 |
| PSC 特定制品（压力锅、乘车头盔、登山绳、石油暖炉、磁铁玩具、吸水树脂玩具） | 事业届出、检查记录、标示照片；煤油暖风机另须 PSE [SRC-JP-AMZ-G9JNNQBWXCMMCGE2][SRC-JP-AMZ-GYATMS8KBP6VYCFF][SRC-JP-AMZ-GG286TPSDRM6PLE2] | 账户状况页面 | JP-L3-PSC-002 |
| 3 岁以下儿童玩具（儿童用 PSC，2025-12-25 起） | 事业届出；儿童用 PSC 标志、届出事业者名、对象年龄、使用注意的照片；详情页填型号、品牌、最低月龄（≥检测年龄）[SRC-JP-AMZ-G9JNNQBWXCMMCGE2][SRC-JP-AMZ-GKJRA3FRPRKVBJJS] | 账户状况页面 + 详情页 | JP-L3-PSC-003 |
| 磁铁娱乐用品 | PSC 文件；详情页 3 条警告语 + 最低年龄 [SRC-JP-AMZ-GT7A9YNUV4MY43GB] | 账户状况页面 + 详情页 | JP-L3-MAGNETSET-001 |
| 吸水珠玩具 | PSC 文件及尺寸确认；详情页 3 条警告语 + 最低年龄 [SRC-JP-AMZ-GFEUQFB9X4YWFVXD] | 同上 | JP-L3-WATERBEADS-001 |
| 玩具、发射型玩具、捏捏乐、指尖陀螺、磁性橡皮泥、磁力片、组合玩具 | 食品卫生法/ST/ASTM F963/EN 71/ISO 8124 之一的报告；用 ST 须永久贴 ST 标志；带蓝牙的指尖陀螺另交电波法文件 [SRC-JP-AMZ-GXZQD85B3GHE8W89][SRC-JP-AMZ-GV9VZ5A7PJZQYRFF][SRC-JP-AMZ-G202155900][SRC-JP-AMZ-GU7U29CYFK6PNU2V][SRC-JP-AMZ-GZHMAZAQU5H54P9Z][SRC-JP-AMZ-GZH3YZUQDTU9XY4Z] | 账户状况页面 | JP-L3-TOY-001 |
| 儿童饰品 | 食品卫生法/ST/EN 71/ISO 8124 报告 [SRC-JP-AMZ-GT3XLUHYCWPM3THX] | 账户状况页面 | JP-L3-KIDSJEWEL-001 |
| 婴儿推车 | SG/ASTM/EN/GB/AS/NZS ISO 之一的安全检查资料 [SRC-JP-AMZ-G48PY7AYJEZT264V]；另一页列 SG CPSA 0001/ASTM F833/EN 1888 [SRC-JP-AMZ-G4SX7HDHVCGK33UD] | child-safety@amazon.co.jp | JP-L3-STROLLER-001 |
| 婴儿摇篮、床边床、婴儿床、弹跳椅、秋千 | CPSC 认可试验机关的 ASTM F2194/F2906/F1169/F406/F2167/F2088 或 EN 1130/14036/16232 报告 [SRC-JP-AMZ-GX44XMQX3ZKWRPZR] | 账户状况页面 | JP-L3-INFANTSLEEP-001 |
| 内置 UVC 的空气净化器、杀菌盒、吸尘器 | IEC/EN 62471 或 JIS C 7550 光生物安全报告（ISO 17025）+ PSE（如适用）；家用 UVC 灭菌器、小型 UVC 杀菌灯、UVC 灯泡禁售 [SRC-JP-AMZ-G5ZEPL3F3YQR5GUS] | jp-electronics-safety@amazon.co.jp / 账户状况 | JP-L3-UVC-001、JP-L1-UVC-001 |
| 日食眼镜、太阳观察滤镜 | ISO 12312-2:2015 检测报告 [SRC-JP-AMZ-G202171660] | 账户状况页面 | JP-L3-ECLIPSE-001 |
| 防烟面罩、防毒/防尘口罩、N95、KN95 | 消防法 / 劳动安全卫生法（国家检定）/ NIOSH / GB 2626-2019 [SRC-JP-AMZ-G3HK6F5AVZ8R2K7V] | 账户状况页面 | JP-L3-RESPIRATOR-001 |
| 灭火器、火灾报警器、一氧化碳报警器 | 日本消防检定协会检定标志（气雾式 NS 标志）；CO 报警器 KHK 绿标或 JIA 认证；正品证明 [SRC-JP-AMZ-G3YXCKTLZV2W3BAW][SRC-JP-AMZ-GRVULZL8LVDHD49P][SRC-JP-AMZ-GQTEXVLXTNPZGYVW] | 账户状况页面 | JP-L3-FIRESAFETY-001 |
| 坠落制止用器具 | 符合「墜落制止用器具の規格」的资料，第 9 条标示 [SRC-JP-AMZ-GVS6B9TTVLM63JMM] | 账户状况页面 | JP-L3-FALLARREST-001 |
| 暖水袋 | SG CPSA 0033/ASTM D4316/BS 1970；充电式 PSE；微波式日本カイロ工業会基准 [SRC-JP-AMZ-GXDAD4N3TU3AK5TD] | 账户状况页面 | JP-L3-HOTWATERBOTTLE-001 |
| 隐形墨水笔 | ST 等玩具安全报告；永久标示「口に入れないでください」「目や皮膚への接触を避けてください」[SRC-JP-AMZ-G2D2BL839NUB5QTK] | 账户状况页面 | JP-L3-INKPEN-001 |
| 婴儿背带 | SG CPSA 0027 或 EN 13209 报告 [SRC-JP-AMZ-GV49WNPCZU5GW9WX] | 账户状况页面 | JP-L3-CARRIER-001 |
| 汽车千斤顶 | SG CPSA 0040、SG CPSA 0133 或 ASME PASE 2024 报告 [SRC-JP-AMZ-GRKGPHRX533JSRCK] | 账户状况页面 | JP-L3-CARJACK-001 |
| 双层床/高架床 | SG CPSA 0016、EN 747 或 AS/NZS ISO 4220 报告 [SRC-JP-AMZ-GUTKF9TQM6VWTSYB] | 账户状况页面 | JP-L3-BUNKBED-001 |
| 婴儿学步车 | SG CPSA 0002 或 EN 1273 报告 [SRC-JP-AMZ-GU32QMNPJS8L3JHJ] | 账户状况页面 | JP-L3-WALKER-001 |
| 儿童雨伞 | SG CPSA 0047/JUPA/KAKEN/BOKEN 之一的报告；JUPA 须永久贴标 [SRC-JP-AMZ-GK6VQDZ22W23PKDH] | 账户状况页面 | JP-L3-KIDUMBRELLA-001 |
| 登山绳 | PSC 文件；3 条危险警告；半绳/双绳永久标「1/2」[SRC-JP-AMZ-GZ4263KL7TUX2KCG] | 账户状况页面 + 商品/包装 | JP-L3-CLIMBROPE-001 |
| 2 岁以上儿童口罩 | 详情页写「2歳未満の子どもには使用しないでください。」和最低月龄；不得写「新生児」「ベビー」「幼い子ども」或用儿童佩戴图片 [SRC-JP-AMZ-GRBE9D3BXQJPMA6V] | 详情页 | JP-L3-KIDSMASK-001 |
| 儿童安全座椅 | ECE R44/04 或 R129 报告或 E 标志证书；布制座椅禁售 [SRC-JP-AMZ-G202137200] | 账户状况页面 | JP-L3-CARSEAT-001 |
| 自行车/摩托车头盔 | SG CPSA 0056/JCF/ASTM F1447/F1898/EN 1078；摩托车头盔 PSC [SRC-JP-AMZ-GCF2U4MHLT5D82H8] | 账户状况页面 | JP-L3-HELMET-001 |
| 激光产品 | 仅 1/2 级，详情页写等级；便携激光 PSC 文件 [SRC-JP-AMZ-G201689020][SRC-JP-AMZ-GHSP9NQX42SC792H] | 详情页 + 账户状况 | JP-L3-LASER-001 |
| 液化石油气器具（卡式炉、喷枪） | 事业届出、（菱形）适合性证明书或（圆形）检查记录、铭牌照片 [SRC-JP-AMZ-GRF7Z2NN4T35ZZFD][SRC-JP-AMZ-GR4K5294J35J5VM5][SRC-JP-AMZ-GEX5KG3UZD2LTG6W] | jp-gas-safety@amazon.co.jp | JP-L3-GAS-001 |
| 城市燃气用品 | 同上（PSTG）[SRC-JP-AMZ-GRF7Z2NN4T35ZZFD][SRC-JP-AMZ-GFX3B3BCVRKZ9TYK] | 同上 | JP-L3-GAS-002 |
| 高压气瓶 | 容器检查合格及刻印 [SRC-JP-AMZ-G201856250] | — | JP-L3-HPGAS-001 |
| 硅藻土制品 | 石棉含量 ≤0.1%（重量）的检测报告 [SRC-JP-AMZ-GCFUSU5JXQTX2DGA] | 账户状况页面 | JP-L1-ASBESTOS-001 |
| 刀具 | 详情页写刃长和材质；6–15cm 单刃刀加两条警示 [SRC-JP-AMZ-G200164950] | 详情页 | JP-L3-KNIFE-001 |
| 家电回收法对象（空调、电视、冰箱、洗衣机） | 「特定商取引法に基づく表記」公布收集运输费；回收体系 [SRC-JP-AMZ-GRB4UM99MAKCHRZZ] | 卖家信息 | JP-L3-KADENRECYCLE-001 |
| 家庭用品 | 家庭用品质量标示法的日文标示 [SRC-JP-AMZ-G202082120][SRC-JP-AMZ-G201856250] | 商品/包装 | JP-L3-HOUSEHOLDLABEL-001 |
| 餐厨具、容器、婴幼儿玩具 | 食品卫生法规格基准 [SRC-JP-AMZ-G201856250] | 页面未写 | JP-L3-FOODCONTACT-001 |
| 纺织、婴儿用品、家用化学品 | 有害物质含有家庭用品规制法基准 [SRC-JP-AMZ-GD3XAGGJX2T2NRCK] | 页面未写 | JP-L3-HAZHOUSEHOLD-001 |
| 农药、除草剂、肥料、饲料 | 农药销售届出+第 16 条标示；除草剂第 22 条标示+「農薬として使用することができない」；肥料届出/登录/保证票；饲料安全法 [SRC-JP-AMZ-GD3XAGGJX2T2NRCK][SRC-JP-AMZ-G201856250] | — | JP-L3-PESTICIDE-001、JP-L3-HERBICIDE-001、JP-L3-FERTILIZER-001、JP-L3-FEED-001 |
| 成人用品 | 设置成人标志并放在规定浏览节点 [SRC-JP-AMZ-G201856210] | 商品属性 | JP-L3-ADULTFLAG-001 |
| 汽车用品 | HID、轮胎、汽车电池须符合保安基准；汽油携行罐须符合消防法 [SRC-JP-AMZ-G200164410] | — | JP-L3-AUTOPARTS-001 |
| 计量器 | 符合计量法 [SRC-JP-AMZ-G201856250] | — | JP-L3-KEIRYO-001 |

### D. FBA 与危险品（L4）

#### D-1 FBA 禁运清单 [SRC-JP-AMZ-G201730840]

| 禁运商品 | 说明 | 规则ID |
|---|---|---|
| 不符合日本规格/法律的商品 | 缺日文法定标签的海外化妆品、医药部外品、食品；无承认医疗器械；未完成届出/许可的商品 | JP-L4-FBA-001 |
| 不能常温保管的商品 | 需冷藏/温控；带透气孔可能胀裂的味噌等 | JP-L4-FBA-002 |
| 动植物 | 活的或死的动物；任何含植物种子的商品 | JP-L4-FBA-003 |
| 消防法危险物第 1–6 类 | 氧化性固体、可燃性固体、自燃/禁水性物质、引火性液体（第 1 石油类、醇类等）、自反应性物质、氧化性液体 | JP-L4-FBA-004 |
| 火药类/毒剧物/航空禁运/带危险标识 | 火药类取缔法、毒剧法对象；IATA/JACIS/Peach 指定危险物；骷髅或火焰标志；「火気厳禁」「危険物第～類」「可燃性ガス」「40度以上にしない」等警告 | JP-L4-FBA-005 |
| 气雾剂 | 发胶、慕斯、育发喷雾、喷漆、杀虫喷雾、氧气罐、喷胶、除尘罐、便携灭火器、止汗喷雾 | JP-L4-FBA-006 |
| 须设管理者的医疗器械 | 特定管理（电子血压计、耳温计、低频治疗器、助听器）、高度管理（隐形眼镜含彩瞳）、特定保守管理（血氧仪）[SRC-JP-AMZ-G202112340] | JP-L4-MEDDEV-001 |
| 医药品 | 全部 | JP-L4-FBA-008 |
| 金券、贵金属、钱币 | 商品券、预付卡、邮票、印花、门票（≤6 个月的预付 SIM 卡除外）；贵金属锭；金银铜币、纪念币；古钱古钞 | JP-L4-FBA-009 |
| 磁性商品 | 钕磁铁及可能影响其他商品的磁性商品 | JP-L4-FBA-010 |
| CBD/THC | 全部 | JP-L4-FBA-011 |
| 召回或日本禁售商品 | — | JP-L4-FBA-012 |

FBA 可收的医疗器械仅限一般医疗器械和厚生劳动省告示第 68 号所列家庭用管理医疗器械（家用按摩器、磁疗器、温灸器、吸入器、电解水生成器、电子体温计、避孕套等）[SRC-JP-AMZ-G202112340][R:JP-L4-MEDDEV-002]。

#### D-1b 有效期与冷冻食品

- **有效期管理**：日本 FBA 把所有外用品和消费品（含保健品，人用/动物用，即使未标期限）视为有期限商品；食品饮料须批次管理，入仓时剩余保质期 >60 天，≤45 天直接列为销毁且不退回；定期消费品须「消费期间 + 60 天」；婴儿奶粉 ≥180 天；期限格式 YYYY/MM/DD 或 YYYY/MM，制造日期须被期限标签覆盖；须贴亚马逊商品标签（品牌注册正规代理商除外）[SRC-JP-AMZ-G201003420][R:JP-L4-EXPIRY-001]。
- **冷冻食品 FBA**：日本站有冷冻食品 FBA（-23～-27℃，TPR1/TPR2/TPR4 仓），输送箱 ≤40kg、商品 ≤10kg 且在规定尺寸内，2025-07-30 起含冰淇淋；特殊温度（如 -50℃ 金枪鱼、-10℃ 以上冷藏乳品）、冷冻年菜、冷冻酒类、冷冻宠物食品不可；每件加收 375 日元 [SRC-JP-AMZ-G201003420][R:JP-L4-FROZEN-001]。这与《FBA 禁止商品》「冷藏/温控商品禁运」的表述并存（见待核实）。

#### D-2 危险品分类（Hazmat）

- 危险品与否由成品理化特性决定，没有按商品类型预先确定的分类；即使不是危险品也可能被要求提交信息 [SRC-JP-AMZ-G201003400]。可能被审核的例子：充电帽子/马甲、汽车护理用品、铅酸电池、止汗喷雾、发胶、染发剂、香水、杀菌剂、驱虫剂、移动电源、手机、音箱、智能手表、无线耳机、精油、高度酒、洗涤剂、手部消毒剂、硒鼓墨盒、胶水、马克笔、宠物驱虫药、露营炉、一次性暖贴、电动助力车、电池玩具、化学实验套装等 [SRC-JP-AMZ-G200525640]。
- 创建 Listing 或转 FBA 时必须填写电池和危险品信息（UN 编号、重量/容量、GHS 象形图、SDS URL、闪点等）；之后可能被要求在「危険物の分類を管理する」上传 SDS（16 项）或适用除外表；完整信息 2 个工作日内审核；在仓库存被要求补件时 14 个工作日内不交即自费销毁 [SRC-JP-AMZ-G201371860][SRC-JP-AMZ-G201749580][R:JP-L4-DG-001]。
- **FBA 危险物纳品项目**（候补名单制）：参加者可在限量（Limited Quantity）内入仓 2.1/2.2/3/4.1/5.1/5.2/6.1/8/9 类；第 9 类含锂电池（UN3480/3481/3090/3091）、电池驱动车辆（UN3556/3557/3558/3171）、磁性材料（UN2807）。《高压气体保安法》《消防法》（第 4 类除外）《毒剧法》《火药类取缔法》对象不可入 FBA。各仓库对每类危险物还有数量上限，超出时货件计划报错 [SRC-JP-AMZ-G201003400][SRC-JP-AMZ-GHLPCM24G965CHSK][R:JP-L4-DG-002]。

#### D-3 锂电池

- 必须完整填写电池信息；锂离子电池随设备包装的须回答充电状态是否 ≤30%（不答则不能空运）；上传电池适用除外表和 UN38.3 试验概要；符合 IATA DGR 包装说明 965–970 [SRC-JP-AMZ-G200383420][SRC-JP-AMZ-G201371860][R:JP-L4-LIB-001]。
- 亚马逊的能量分档表把日本站各档（含 >300Wh 电池、>60Wh 电芯）均标为「許可済み」，与多数站点不同 [SRC-JP-AMZ-G200383420]——实际以 ASIN チェック结果为准。
- 平台层面另有：圆柱形可充电锂电池禁售 [R:JP-L1-CYLLI-001]、TIC 验证 [R:JP-L3-LIB-001]、PSE 文件 [R:JP-L3-PSE-003]。

#### D-4 喷雾、液体、磁铁

- 气雾剂：《FBA 禁止商品》页明确禁运 [R:JP-L4-FBA-006]；危险品指南允许项目参与者限量入仓 2.1/2.2 类——冲突。
- 液体：消防法第 4 类引火性液体在《FBA 禁止商品》页禁运，危险品指南则把第 4 类除外——冲突 [R:JP-L4-FBA-004]。10L 以上汽油类燃料平台禁售 [R:JP-L1-GASOLINE-001]。
- 磁铁：钕磁铁及强磁商品禁运 [R:JP-L4-FBA-010]；危险品指南把 UN2807 磁性材料（音箱、耳机、磁贴、玩具）列为可入仓的第 9 类——冲突。

### E. 当地法规（L5）

本文件不写 E 节；日本法规（PSE/PSC/电波法/药机法/食品卫生法等的法规原文要求、主管机构、注册备案）见日本法规部分文件（规则 `rules/sites/JP_regulation.yaml`）。本文只写亚马逊在这些法规之上的平台审核要求。

### F. 标签、语言与本地责任人（亚马逊要求部分）

| 主题 | 亚马逊要求 | 规则ID |
|---|---|---|
| 日文法定标示 | 化妆品、医药部外品、药品、保健品、医疗器械缺日文法定标示（含海外版包装平行进口）禁售 [SRC-JP-AMZ-G200164470][SRC-JP-AMZ-G201829010]；缺日文标签的海外化妆品/医药部外品/食品不能入 FBA [SRC-JP-AMZ-G201730840] | JP-L1-HEALTH-001、JP-L4-FBA-001 |
| 日文说明书/警告 | 提交合规文件时，说明书、安全信息、标签、警告须为销售国（日本）语言 [SRC-JP-AMZ-GHJPQ6KDLA9N5F4L][SRC-JP-AMZ-G9JNNQBWXCMMCGE2] | JP-L3-DOCQUALITY-001 |
| PS 标志与事业者名 | PSE 铭牌须相邻标示 PSE 标志、届出事业者名、额定值（菱形加登记检查机关）；PSC/PSLPG/PSTG 标示届出事业者名、使用注意等；用简称/商标须经产省承认/届出 [SRC-JP-AMZ-GHJPQ6KDLA9N5F4L][SRC-JP-AMZ-GJXRBNGX52EMJZZB] | JP-L3-PSE-001、JP-L3-PSC-001、JP-L3-PSC-002、JP-L3-GAS-001、JP-L3-GAS-002 |
| 不得写「PSE 认证取得」 | PSE 是履行义务后自行标示的标志，不是「从国家取得」；广告写「PSE認証取得」等可能违反景品表示法；对象外商品不得标 PSE [SRC-JP-AMZ-GHJPQ6KDLA9N5F4L] | JP-L3-PSE-001 |
| 国内管理人 | 2025-12-25 起海外卖家须选任国内管理人；亚马逊要求届出书载明海外卖家本人名称地址和国内管理人名称地址；找不到可在「服务提供商网络」查找 [SRC-JP-AMZ-GJXRBNGX52EMJZZB] | JP-L3-4LAW-001 |
| 特定商取引法表记 | 家电回收法对象的收集运输费写在「特定商取引法に基づく表記」；OTC 药/动物药卖家须在卖家信息页写明必要事项 [SRC-JP-AMZ-GRB4UM99MAKCHRZZ][SRC-JP-AMZ-G200164490] | JP-L3-KADENRECYCLE-001、JP-L2-DRUGS-001 |
| 详情页必写声明 | 电波法符合声明和频段；指定无线设备需执照；激光等级；刀具刃长和材质、6–15cm 单刃刀两条警示；手铐「18歳未満の方は購入しないでください。」；磁铁/吸水珠警告和最低月龄；汽油容量；焚烧炉守法提示；除草剂「農薬として使用することができない」；成人书籍模特拍摄时 18 岁以上 [SRC-JP-AMZ-G202082120][SRC-JP-AMZ-G201689020][SRC-JP-AMZ-G200164950][SRC-JP-AMZ-GT7A9YNUV4MY43GB][SRC-JP-AMZ-GFEUQFB9X4YWFVXD][SRC-JP-AMZ-G201856250][SRC-JP-AMZ-GD3XAGGJX2T2NRCK][SRC-JP-AMZ-G201856210] | 见 C 节对应规则 |

### G. 2024–2026 亚马逊政策变化与生效日期

| 日期 | 变化 | 影响的产品 | 规则ID | 来源 |
|---|---|---|---|---|
| 2025-12-25 | 海外卖家成为四法「特定进口事业者」：须选任国内管理人、本人名义届出；亚马逊对 12-25 后审核的 ASIN 要求届出书载明海外卖家本人和国内管理人，否则可删除商品 | PSE/PSC/PSTG/PSLPG 对象全部商品 | JP-L3-4LAW-001、JP-L3-PSE-001、JP-L3-PSC-001、JP-L3-PSC-002、JP-L3-GAS-001、JP-L3-GAS-002 | [SRC-JP-AMZ-GJXRBNGX52EMJZZB][SRC-JP-AMZ-GHJPQ6KDLA9N5F4L][SRC-JP-AMZ-G9JNNQBWXCMMCGE2][SRC-JP-AMZ-GRF7Z2NN4T35ZZFD] |
| 2025-12-25 | PSC 新增「子供向け特定製品」（乳幼儿用玩具），须儿童用 PSC 标志 | 未满 3 岁玩具 | JP-L3-PSC-003 | [SRC-JP-AMZ-G9JNNQBWXCMMCGE2][SRC-JP-AMZ-GJXRBNGX52EMJZZB] |
| 2025-12（预定） | 海外事业者可经 e-Gov 电子申请届出（此前暂行邮件提交） | 四法对象 | JP-L3-4LAW-001 | [SRC-JP-AMZ-GJXRBNGX52EMJZZB] |
| 页面未标日期（本次首次见到） | 圆柱形可充电锂电池（18650/21700 等）及含此类电池商品禁售 | 手电、头灯、电芯、电池组 | JP-L1-CYLLI-001、JP-L1-HEADLAMP-001 | [SRC-JP-AMZ-G2HSXA2KM59YX5AT][SRC-JP-AMZ-GRLKLZ6WQ9R259LC] |
| 页面未标日期 | 锂电池/移动电源/便携电源改由 TIC 机构验证 JIS C 62133-2、62368-1、UN38.3 | 锂电池类 | JP-L3-LIB-001 | [SRC-JP-AMZ-GCWQ4DJP8LKVNRX8] |
| 页面未标日期 | 锂电池家电、智能家居设备须提交 JIS C 9335 / 62368-1 / 1010 报告 | 锂电池家电和消费电子 | JP-L3-LIAPPL-001、JP-L3-LISMART-001 | [SRC-JP-AMZ-G8TM22XFM7WXCRDC][SRC-JP-AMZ-GA2PQDTU5HMC7CRZ] |
| 页面未标日期 | 新建 Listing 须先证明合规（「出品制限を確認する」），不影响已在售商品 | 全部 | JP-L3-NEWLISTING-001 | [SRC-JP-AMZ-GKCHRSWHXB5WZHAU] |
| 页面未标日期 | 合规文件不得由计算机或 AI 生成 | 全部提交文件 | JP-L3-DOCQUALITY-001 | [SRC-JP-AMZ-GHJPQ6KDLA9N5F4L][SRC-JP-AMZ-G9JNNQBWXCMMCGE2] |
| 页面未标日期 | 《商品安全出品限制》禁售清单（儿童睡眠用品、加热衣物、UVC、Mad Honey 等） | 见 A-2 | 见 A-2 | [SRC-JP-AMZ-GRLKLZ6WQ9R259LC] |
| 页面未标日期 | 药品/化妆品/保健品/烟草页增加「类 THC/HHC 物质」和「曾检出 THC 的 CBD 品牌/系列」禁令 | CBD、保健品、化妆品、电子烟 | JP-L1-CANNABIS-001 | [SRC-JP-AMZ-G200164470][SRC-JP-AMZ-G200164910] |

### H. 来源清单

<!-- H-SECTION -->
本文共引用 143 个来源，全部为 S1（亚马逊日本卖家平台帮助页，经 r.jina.ai 抓取；139 个为 ja_JP 版，4 个因 ja_JP 版只返回导航壳而采用 zh_CN 版）。访问方式均为 jina_reader。

| 来源 ID | 标题（页面原文） | URL | 级别 | 访问日期 | 快照 |
|---|---|---|---|---|---|
| SRC-JP-AMZ-G200164330 | 制限対象商品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G200164330 | S1 | 2026-10-10 | `policy/snapshots/JP/G200164330.ja_JP.md` |
| SRC-JP-AMZ-G200164340 | アルコール | https://sellercentral.amazon.co.jp/help/hub/reference/external/G200164340 | S1 | 2026-10-10 | `policy/snapshots/JP/G200164340.ja_JP.md` |
| SRC-JP-AMZ-G200164370 | 動物と動物商品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G200164370 | S1 | 2026-10-10 | `policy/snapshots/JP/G200164370.ja_JP.md` |
| SRC-JP-AMZ-G200164410 | カー&バイク用品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G200164410 | S1 | 2026-10-10 | `policy/snapshots/JP/G200164410.ja_JP.md` |
| SRC-JP-AMZ-G200164450 | 通貨、硬貨、および現金同等品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G200164450 | S1 | 2026-10-10 | `policy/snapshots/JP/G200164450.ja_JP.md` |
| SRC-JP-AMZ-G200164470 | 医薬部外品および化粧品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G200164470 | S1 | 2026-10-10 | `policy/snapshots/JP/G200164470.ja_JP.md` |
| SRC-JP-AMZ-G200164490 | 医薬品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G200164490 | S1 | 2026-10-10 | `policy/snapshots/JP/G200164490.ja_JP.md` |
| SRC-JP-AMZ-G200164550 | 食品&飲料 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G200164550 | S1 | 2026-10-10 | `policy/snapshots/JP/G200164550.ja_JP.md` |
| SRC-JP-AMZ-G200164650 | 医療機器および関連商品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G200164650 | S1 | 2026-10-10 | `policy/snapshots/JP/G200164650.ja_JP.md` |
| SRC-JP-AMZ-G200164750 | リコール対象商品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G200164750 | S1 | 2026-10-10 | `policy/snapshots/JP/G200164750.ja_JP.md` |
| SRC-JP-AMZ-G200164850 | 盗難品およびピッキングツール | https://sellercentral.amazon.co.jp/help/hub/reference/external/G200164850 | S1 | 2026-10-10 | `policy/snapshots/JP/G200164850.ja_JP.md` |
| SRC-JP-AMZ-G200164910 | タバコおよびタバコ関連商品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G200164910 | S1 | 2026-10-10 | `policy/snapshots/JP/G200164910.ja_JP.md` |
| SRC-JP-AMZ-G200164950 | 武器および武器を模した商品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G200164950 | S1 | 2026-10-10 | `policy/snapshots/JP/G200164950.ja_JP.md` |
| SRC-JP-AMZ-G200329080 | Merchants@amazon.co.jp商品登録ルール | https://sellercentral.amazon.co.jp/help/hub/reference/external/G200329080 | S1 | 2026-10-10 | `policy/snapshots/JP/G200329080.ja_JP.md` |
| SRC-JP-AMZ-G200332540 | 商品カテゴリーの概要 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G200332540 | S1 | 2026-10-10 | `policy/snapshots/JP/G200332540.ja_JP.md` |
| SRC-JP-AMZ-G200333160 | 出品許可が必要なカテゴリーと商品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G200333160 | S1 | 2026-10-10 | `policy/snapshots/JP/G200333160.ja_JP.md` |
| SRC-JP-AMZ-G200333170 | カテゴリー別の補足ガイドライン | https://sellercentral.amazon.co.jp/help/hub/reference/external/G200333170 | S1 | 2026-10-10 | `policy/snapshots/JP/G200333170.ja_JP.md` |
| SRC-JP-AMZ-G200383420 | リチウム電池本体またはリチウム電池駆動の商品に対する要求事項 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G200383420 | S1 | 2026-10-10 | `policy/snapshots/JP/G200383420.ja_JP.md` |
| SRC-JP-AMZ-G200500100 | Amazonデバイス用アクセサリ | https://sellercentral.amazon.co.jp/help/hub/reference/external/G200500100 | S1 | 2026-10-10 | `policy/snapshots/JP/G200500100.ja_JP.md` |
| SRC-JP-AMZ-G200525640 | 危険物の可能性がある商品例 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G200525640 | S1 | 2026-10-10 | `policy/snapshots/JP/G200525640.ja_JP.md` |
| SRC-JP-AMZ-G201003400 | 危険物確認ガイド | https://sellercentral.amazon.co.jp/help/hub/reference/external/G201003400 | S1 | 2026-10-10 | `policy/snapshots/JP/G201003400.ja_JP.md` |
| SRC-JP-AMZ-G201003420 | 要期限管理商品および温度管理が必要な商品（冷凍食品） | https://sellercentral.amazon.co.jp/help/hub/reference/external/G201003420 | S1 | 2026-10-10 | `policy/snapshots/JP/G201003420.ja_JP.md` |
| SRC-JP-AMZ-G201371860 | 危険物（hazmat）に必要な情報および文書 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G201371860 | S1 | 2026-10-10 | `policy/snapshots/JP/G201371860.ja_JP.md` |
| SRC-JP-AMZ-G201511970 | 食品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G201511970 | S1 | 2026-10-10 | `policy/snapshots/JP/G201511970.zh_CN.md` |
| SRC-JP-AMZ-G201575280 | 貿易管理法 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G201575280 | S1 | 2026-10-10 | `policy/snapshots/JP/G201575280.ja_JP.md` |
| SRC-JP-AMZ-G201689020 | レーザー商品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G201689020 | S1 | 2026-10-10 | `policy/snapshots/JP/G201689020.ja_JP.md` |
| SRC-JP-AMZ-G201730840 | FBA禁止商品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G201730840 | S1 | 2026-10-10 | `policy/snapshots/JP/G201730840.ja_JP.md` |
| SRC-JP-AMZ-G201737480 | 植物および種子製品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G201737480 | S1 | 2026-10-10 | `policy/snapshots/JP/G201737480.ja_JP.md` |
| SRC-JP-AMZ-G201749580 | FBA危険物判定作業（Hazmat） | https://sellercentral.amazon.co.jp/help/hub/reference/external/G201749580 | S1 | 2026-10-10 | `policy/snapshots/JP/G201749580.ja_JP.md` |
| SRC-JP-AMZ-G201829010 | 栄養補助食品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G201829010 | S1 | 2026-10-10 | `policy/snapshots/JP/G201829010.ja_JP.md` |
| SRC-JP-AMZ-G201856210 | アダルト商品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G201856210 | S1 | 2026-10-10 | `policy/snapshots/JP/G201856210.ja_JP.md` |
| SRC-JP-AMZ-G201856230 | 不快感を与える商品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G201856230 | S1 | 2026-10-10 | `policy/snapshots/JP/G201856230.ja_JP.md` |
| SRC-JP-AMZ-G201856250 | その他の商品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G201856250 | S1 | 2026-10-10 | `policy/snapshots/JP/G201856250.ja_JP.md` |
| SRC-JP-AMZ-G202024200 | 禁止されている商品広告・宣伝文言 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G202024200 | S1 | 2026-10-10 | `policy/snapshots/JP/G202024200.ja_JP.md` |
| SRC-JP-AMZ-G202029820 | Amazon デバイスおよび修理・メンテナンス用アクセサリ商品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G202029820 | S1 | 2026-10-10 | `policy/snapshots/JP/G202029820.ja_JP.md` |
| SRC-JP-AMZ-G202082120 | 電化製品・電子機器 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G202082120 | S1 | 2026-10-10 | `policy/snapshots/JP/G202082120.ja_JP.md` |
| SRC-JP-AMZ-G202112340 | 医療機器の取り扱いについて | https://sellercentral.amazon.co.jp/help/hub/reference/external/G202112340 | S1 | 2026-10-10 | `policy/snapshots/JP/G202112340.ja_JP.md` |
| SRC-JP-AMZ-G202137200 | チャイルドシート、ブースターシート、トラベルシステム | https://sellercentral.amazon.co.jp/help/hub/reference/external/G202137200 | S1 | 2026-10-10 | `policy/snapshots/JP/G202137200.ja_JP.md` |
| SRC-JP-AMZ-G202137960 | ストリングライト | https://sellercentral.amazon.co.jp/help/hub/reference/external/G202137960 | S1 | 2026-10-10 | `policy/snapshots/JP/G202137960.ja_JP.md` |
| SRC-JP-AMZ-G202155900 | フィンガースピナー | https://sellercentral.amazon.co.jp/help/hub/reference/external/G202155900 | S1 | 2026-10-10 | `policy/snapshots/JP/G202155900.ja_JP.md` |
| SRC-JP-AMZ-G202171660 | 日食メガネおよび太陽観察用フィルター | https://sellercentral.amazon.co.jp/help/hub/reference/external/G202171660 | S1 | 2026-10-10 | `policy/snapshots/JP/G202171660.ja_JP.md` |
| SRC-JP-AMZ-G202183590 | ストリーミングメディアプレーヤー | https://sellercentral.amazon.co.jp/help/hub/reference/external/G202183590 | S1 | 2026-10-10 | `policy/snapshots/JP/G202183590.ja_JP.md` |
| SRC-JP-AMZ-G23UM4EWBTCN7B9M | LED電球 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G23UM4EWBTCN7B9M | S1 | 2026-10-10 | `policy/snapshots/JP/G23UM4EWBTCN7B9M.ja_JP.md` |
| SRC-JP-AMZ-G2D2BL839NUB5QTK | 透明インクペン | https://sellercentral.amazon.co.jp/help/hub/reference/external/G2D2BL839NUB5QTK | S1 | 2026-10-10 | `policy/snapshots/JP/G2D2BL839NUB5QTK.ja_JP.md` |
| SRC-JP-AMZ-G2E9DBAG4GYSQ5LT | 乳児用ベッドバンパー | https://sellercentral.amazon.co.jp/help/hub/reference/external/G2E9DBAG4GYSQ5LT | S1 | 2026-10-10 | `policy/snapshots/JP/G2E9DBAG4GYSQ5LT.ja_JP.md` |
| SRC-JP-AMZ-G2HSXA2KM59YX5AT | 円筒形の充電式リチウム電池 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G2HSXA2KM59YX5AT | S1 | 2026-10-10 | `policy/snapshots/JP/G2HSXA2KM59YX5AT.ja_JP.md` |
| SRC-JP-AMZ-G2TJY9F8283XBAB2 | 電動工具、家電用互換リチウムイオン蓄電池 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G2TJY9F8283XBAB2 | S1 | 2026-10-10 | `policy/snapshots/JP/G2TJY9F8283XBAB2.ja_JP.md` |
| SRC-JP-AMZ-G2VRUQKXAFZUVNP9 | ワイヤレス充電器 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G2VRUQKXAFZUVNP9 | S1 | 2026-10-10 | `policy/snapshots/JP/G2VRUQKXAFZUVNP9.ja_JP.md` |
| SRC-JP-AMZ-G3HK6F5AVZ8R2K7V | 防災・防煙、防毒・防塵マスク | https://sellercentral.amazon.co.jp/help/hub/reference/external/G3HK6F5AVZ8R2K7V | S1 | 2026-10-10 | `policy/snapshots/JP/G3HK6F5AVZ8R2K7V.ja_JP.md` |
| SRC-JP-AMZ-G3YXCKTLZV2W3BAW | 消火器 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G3YXCKTLZV2W3BAW | S1 | 2026-10-10 | `policy/snapshots/JP/G3YXCKTLZV2W3BAW.ja_JP.md` |
| SRC-JP-AMZ-G47GNYPBWSRVPADT | カンナビジオール（CBD）商品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G47GNYPBWSRVPADT | S1 | 2026-10-10 | `policy/snapshots/JP/G47GNYPBWSRVPADT.ja_JP.md` |
| SRC-JP-AMZ-G48PY7AYJEZT264V | ベビーカー | https://sellercentral.amazon.co.jp/help/hub/reference/external/G48PY7AYJEZT264V | S1 | 2026-10-10 | `policy/snapshots/JP/G48PY7AYJEZT264V.ja_JP.md` |
| SRC-JP-AMZ-G4SX7HDHVCGK33UD | 坐式婴儿车 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G4SX7HDHVCGK33UD | S1 | 2026-10-10 | `policy/snapshots/JP/G4SX7HDHVCGK33UD.zh_CN.md` |
| SRC-JP-AMZ-G5P5YMQXX9Y34NVU | ジェル燃料および液体燃料を使用するファイヤーピットや暖炉 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G5P5YMQXX9Y34NVU | S1 | 2026-10-10 | `policy/snapshots/JP/G5P5YMQXX9Y34NVU.ja_JP.md` |
| SRC-JP-AMZ-G5ZEPL3F3YQR5GUS | UVC製品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G5ZEPL3F3YQR5GUS | S1 | 2026-10-10 | `policy/snapshots/JP/G5ZEPL3F3YQR5GUS.ja_JP.md` |
| SRC-JP-AMZ-G7HM69VDEMRW7TPE | 電動モビリティ（Eモビリティ）機器のバッテリー | https://sellercentral.amazon.co.jp/help/hub/reference/external/G7HM69VDEMRW7TPE | S1 | 2026-10-10 | `policy/snapshots/JP/G7HM69VDEMRW7TPE.ja_JP.md` |
| SRC-JP-AMZ-G7PDM6BTH8UZTZRZ | シーリングライトおよびペンダントライト | https://sellercentral.amazon.co.jp/help/hub/reference/external/G7PDM6BTH8UZTZRZ | S1 | 2026-10-10 | `policy/snapshots/JP/G7PDM6BTH8UZTZRZ.ja_JP.md` |
| SRC-JP-AMZ-G7TCXG6EJL23BY7E | カー&バイク用品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G7TCXG6EJL23BY7E | S1 | 2026-10-10 | `policy/snapshots/JP/G7TCXG6EJL23BY7E.ja_JP.md` |
| SRC-JP-AMZ-G84EFS4CKK43USMF | 出品申請に関するよくある質問 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G84EFS4CKK43USMF | S1 | 2026-10-10 | `policy/snapshots/JP/G84EFS4CKK43USMF.ja_JP.md` |
| SRC-JP-AMZ-G8FDB4PSHS4AACQ5 | 引きひも付き子ども用トップス | https://sellercentral.amazon.co.jp/help/hub/reference/external/G8FDB4PSHS4AACQ5 | S1 | 2026-10-10 | `policy/snapshots/JP/G8FDB4PSHS4AACQ5.ja_JP.md` |
| SRC-JP-AMZ-G8TM22XFM7WXCRDC | リチウム電池駆動の家電 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G8TM22XFM7WXCRDC | S1 | 2026-10-10 | `policy/snapshots/JP/G8TM22XFM7WXCRDC.ja_JP.md` |
| SRC-JP-AMZ-G8U478XNGKRPLH3B | カーバッテリー充電器 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G8U478XNGKRPLH3B | S1 | 2026-10-10 | `policy/snapshots/JP/G8U478XNGKRPLH3B.ja_JP.md` |
| SRC-JP-AMZ-G8Z2QTQFT3KSZ9KR | 延長コードセット | https://sellercentral.amazon.co.jp/help/hub/reference/external/G8Z2QTQFT3KSZ9KR | S1 | 2026-10-10 | `policy/snapshots/JP/G8Z2QTQFT3KSZ9KR.ja_JP.md` |
| SRC-JP-AMZ-G9FTYWHNN48XP4ZZ | ホームカメラ | https://sellercentral.amazon.co.jp/help/hub/reference/external/G9FTYWHNN48XP4ZZ | S1 | 2026-10-10 | `policy/snapshots/JP/G9FTYWHNN48XP4ZZ.ja_JP.md` |
| SRC-JP-AMZ-G9JNNQBWXCMMCGE2 | 消費生活用製品安全法 | https://sellercentral.amazon.co.jp/help/hub/reference/external/G9JNNQBWXCMMCGE2 | S1 | 2026-10-10 | `policy/snapshots/JP/G9JNNQBWXCMMCGE2.ja_JP.md` |
| SRC-JP-AMZ-G9LKRHDUQ5AV3ECD | 子ども用ネックフロート | https://sellercentral.amazon.co.jp/help/hub/reference/external/G9LKRHDUQ5AV3ECD | S1 | 2026-10-10 | `policy/snapshots/JP/G9LKRHDUQ5AV3ECD.ja_JP.md` |
| SRC-JP-AMZ-GA2PQDTU5HMC7CRZ | リチウム電池駆動のスマートホームデバイスおよび消費者向け電化製品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GA2PQDTU5HMC7CRZ | S1 | 2026-10-10 | `policy/snapshots/JP/GA2PQDTU5HMC7CRZ.ja_JP.md` |
| SRC-JP-AMZ-GABNR57VJTUDKECV | スマートウォッチ | https://sellercentral.amazon.co.jp/help/hub/reference/external/GABNR57VJTUDKECV | S1 | 2026-10-10 | `policy/snapshots/JP/GABNR57VJTUDKECV.ja_JP.md` |
| SRC-JP-AMZ-GAPFH5HZK2U2H4PF | 美顔器 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GAPFH5HZK2U2H4PF | S1 | 2026-10-10 | `policy/snapshots/JP/GAPFH5HZK2U2H4PF.ja_JP.md` |
| SRC-JP-AMZ-GBJZXSGPP8KTAHES | 電気ヒーター | https://sellercentral.amazon.co.jp/help/hub/reference/external/GBJZXSGPP8KTAHES | S1 | 2026-10-10 | `policy/snapshots/JP/GBJZXSGPP8KTAHES.ja_JP.md` |
| SRC-JP-AMZ-GC277GB53473J65C | 研磨たこ糸 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GC277GB53473J65C | S1 | 2026-10-10 | `policy/snapshots/JP/GC277GB53473J65C.ja_JP.md` |
| SRC-JP-AMZ-GC35Z63FGCUCUWXX | コンプライアンス情報または申し立てを提出する | https://sellercentral.amazon.co.jp/help/hub/reference/external/GC35Z63FGCUCUWXX | S1 | 2026-10-10 | `policy/snapshots/JP/GC35Z63FGCUCUWXX.ja_JP.md` |
| SRC-JP-AMZ-GCF2U4MHLT5D82H8 | 自転車およびバイク用ヘルメット | https://sellercentral.amazon.co.jp/help/hub/reference/external/GCF2U4MHLT5D82H8 | S1 | 2026-10-10 | `policy/snapshots/JP/GCF2U4MHLT5D82H8.ja_JP.md` |
| SRC-JP-AMZ-GCFUSU5JXQTX2DGA | 珪藻土製品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GCFUSU5JXQTX2DGA | S1 | 2026-10-10 | `policy/snapshots/JP/GCFUSU5JXQTX2DGA.ja_JP.md` |
| SRC-JP-AMZ-GCWJK56TEF5RHCZ4 | レーザー付放射温度計 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GCWJK56TEF5RHCZ4 | S1 | 2026-10-10 | `policy/snapshots/JP/GCWJK56TEF5RHCZ4.ja_JP.md` |
| SRC-JP-AMZ-GCWQ4DJP8LKVNRX8 | リチウム電池とポータブル電源 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GCWQ4DJP8LKVNRX8 | S1 | 2026-10-10 | `policy/snapshots/JP/GCWQ4DJP8LKVNRX8.ja_JP.md` |
| SRC-JP-AMZ-GD3XAGGJX2T2NRCK | 化学物質、農薬および肥料 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GD3XAGGJX2T2NRCK | S1 | 2026-10-10 | `policy/snapshots/JP/GD3XAGGJX2T2NRCK.ja_JP.md` |
| SRC-JP-AMZ-GD8DGXG3Q3Y92UYH | ドローン製品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GD8DGXG3Q3Y92UYH | S1 | 2026-10-10 | `policy/snapshots/JP/GD8DGXG3Q3Y92UYH.ja_JP.md` |
| SRC-JP-AMZ-GDFTVKADLD9EU58M | ワイヤレススピーカー | https://sellercentral.amazon.co.jp/help/hub/reference/external/GDFTVKADLD9EU58M | S1 | 2026-10-10 | `policy/snapshots/JP/GDFTVKADLD9EU58M.ja_JP.md` |
| SRC-JP-AMZ-GDJWZYLHGEFVQ9KK | ACアダプター | https://sellercentral.amazon.co.jp/help/hub/reference/external/GDJWZYLHGEFVQ9KK | S1 | 2026-10-10 | `policy/snapshots/JP/GDJWZYLHGEFVQ9KK.ja_JP.md` |
| SRC-JP-AMZ-GDPSRCGVBFSFY78H | ベビー用歯ぐずり対策商品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GDPSRCGVBFSFY78H | S1 | 2026-10-10 | `policy/snapshots/JP/GDPSRCGVBFSFY78H.ja_JP.md` |
| SRC-JP-AMZ-GEJ6L4MMBHVZGLND | 爪楊枝（つまようじ）クロスボウ | https://sellercentral.amazon.co.jp/help/hub/reference/external/GEJ6L4MMBHVZGLND | S1 | 2026-10-10 | `policy/snapshots/JP/GEJ6L4MMBHVZGLND.ja_JP.md` |
| SRC-JP-AMZ-GEX5KG3UZD2LTG6W | カートリッジガスこんろ | https://sellercentral.amazon.co.jp/help/hub/reference/external/GEX5KG3UZD2LTG6W | S1 | 2026-10-10 | `policy/snapshots/JP/GEX5KG3UZD2LTG6W.ja_JP.md` |
| SRC-JP-AMZ-GFEUQFB9X4YWFVXD | ウォータービーズ玩具 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GFEUQFB9X4YWFVXD | S1 | 2026-10-10 | `policy/snapshots/JP/GFEUQFB9X4YWFVXD.ja_JP.md` |
| SRC-JP-AMZ-GFQMECECLTJCUE3H | 電池駆動の加熱式の衣服およびインソール | https://sellercentral.amazon.co.jp/help/hub/reference/external/GFQMECECLTJCUE3H | S1 | 2026-10-10 | `policy/snapshots/JP/GFQMECECLTJCUE3H.ja_JP.md` |
| SRC-JP-AMZ-GFVXRS7EZ8DY8TLT | ワイヤレスイヤホン | https://sellercentral.amazon.co.jp/help/hub/reference/external/GFVXRS7EZ8DY8TLT | S1 | 2026-10-10 | `policy/snapshots/JP/GFVXRS7EZ8DY8TLT.ja_JP.md` |
| SRC-JP-AMZ-GFX3B3BCVRKZ9TYK | ガスストーブ | https://sellercentral.amazon.co.jp/help/hub/reference/external/GFX3B3BCVRKZ9TYK | S1 | 2026-10-10 | `policy/snapshots/JP/GFX3B3BCVRKZ9TYK.ja_JP.md` |
| SRC-JP-AMZ-GG286TPSDRM6PLE2 | 灯油ヒーター | https://sellercentral.amazon.co.jp/help/hub/reference/external/GG286TPSDRM6PLE2 | S1 | 2026-10-10 | `policy/snapshots/JP/GG286TPSDRM6PLE2.ja_JP.md` |
| SRC-JP-AMZ-GGKSRLQBRTPLHH7C | LEDヘッドライト | https://sellercentral.amazon.co.jp/help/hub/reference/external/GGKSRLQBRTPLHH7C | S1 | 2026-10-10 | `policy/snapshots/JP/GGKSRLQBRTPLHH7C.ja_JP.md` |
| SRC-JP-AMZ-GGRZ8EFYCTYN7VRD | 車＆バイク用ポータブルジャンプスターター | https://sellercentral.amazon.co.jp/help/hub/reference/external/GGRZ8EFYCTYN7VRD | S1 | 2026-10-10 | `policy/snapshots/JP/GGRZ8EFYCTYN7VRD.ja_JP.md` |
| SRC-JP-AMZ-GHJPQ6KDLA9N5F4L | 電気用品安全法（PSE） | https://sellercentral.amazon.co.jp/help/hub/reference/external/GHJPQ6KDLA9N5F4L | S1 | 2026-10-10 | `policy/snapshots/JP/GHJPQ6KDLA9N5F4L.ja_JP.md` |
| SRC-JP-AMZ-GHLPCM24G965CHSK | 危険物の許容される最大数量制限 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GHLPCM24G965CHSK | S1 | 2026-10-10 | `policy/snapshots/JP/GHLPCM24G965CHSK.ja_JP.md` |
| SRC-JP-AMZ-GHSP9NQX42SC792H | レーザー距離計 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GHSP9NQX42SC792H | S1 | 2026-10-10 | `policy/snapshots/JP/GHSP9NQX42SC792H.ja_JP.md` |
| SRC-JP-AMZ-GJT34NFP87EZXQ2K | ジャマー | https://sellercentral.amazon.co.jp/help/hub/reference/external/GJT34NFP87EZXQ2K | S1 | 2026-10-10 | `policy/snapshots/JP/GJT34NFP87EZXQ2K.ja_JP.md` |
| SRC-JP-AMZ-GJXRBNGX52EMJZZB | 海外出品者向け製品安全4法法令遵守ガイド | https://sellercentral.amazon.co.jp/help/hub/reference/external/GJXRBNGX52EMJZZB | S1 | 2026-10-10 | `policy/snapshots/JP/GJXRBNGX52EMJZZB.ja_JP.md` |
| SRC-JP-AMZ-GK6MW7WEWN6BP587 | マッドハニー | https://sellercentral.amazon.co.jp/help/hub/reference/external/GK6MW7WEWN6BP587 | S1 | 2026-10-10 | `policy/snapshots/JP/GK6MW7WEWN6BP587.ja_JP.md` |
| SRC-JP-AMZ-GK6VQDZ22W23PKDH | 子ども用傘 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GK6VQDZ22W23PKDH | S1 | 2026-10-10 | `policy/snapshots/JP/GK6VQDZ22W23PKDH.ja_JP.md` |
| SRC-JP-AMZ-GKC4WZW2VWSAPLKT | ヘアドライヤー、ヘアアイロン | https://sellercentral.amazon.co.jp/help/hub/reference/external/GKC4WZW2VWSAPLKT | S1 | 2026-10-10 | `policy/snapshots/JP/GKC4WZW2VWSAPLKT.ja_JP.md` |
| SRC-JP-AMZ-GKCHRSWHXB5WZHAU | コンプライアンス要件に準拠した新しいセレクションの作成 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GKCHRSWHXB5WZHAU | S1 | 2026-10-10 | `policy/snapshots/JP/GKCHRSWHXB5WZHAU.ja_JP.md` |
| SRC-JP-AMZ-GKD2ZVSS3AZM4AQT | トリクロロ酢酸 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GKD2ZVSS3AZM4AQT | S1 | 2026-10-10 | `policy/snapshots/JP/GKD2ZVSS3AZM4AQT.ja_JP.md` |
| SRC-JP-AMZ-GKDFVJSUHPYTRHW3 | 乳幼児向け加重寝具 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GKDFVJSUHPYTRHW3 | S1 | 2026-10-10 | `policy/snapshots/JP/GKDFVJSUHPYTRHW3.ja_JP.md` |
| SRC-JP-AMZ-GKJRA3FRPRKVBJJS | 儿童玩具 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GKJRA3FRPRKVBJJS | S1 | 2026-10-10 | `policy/snapshots/JP/GKJRA3FRPRKVBJJS.zh_CN.md` |
| SRC-JP-AMZ-GKP4BFU3VHDXXEXV | 脱毛器 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GKP4BFU3VHDXXEXV | S1 | 2026-10-10 | `policy/snapshots/JP/GKP4BFU3VHDXXEXV.ja_JP.md` |
| SRC-JP-AMZ-GMUW6CKYLY4AP8MK | 電動モビリティ（Eモビリティ）機器 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GMUW6CKYLY4AP8MK | S1 | 2026-10-10 | `policy/snapshots/JP/GMUW6CKYLY4AP8MK.ja_JP.md` |
| SRC-JP-AMZ-GP8ECC9H3JWXRCAP | ポータブル電源 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GP8ECC9H3JWXRCAP | S1 | 2026-10-10 | `policy/snapshots/JP/GP8ECC9H3JWXRCAP.ja_JP.md` |
| SRC-JP-AMZ-GPQBDFAYL3LCWYD2 | マーメイドテール水着 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GPQBDFAYL3LCWYD2 | S1 | 2026-10-10 | `policy/snapshots/JP/GPQBDFAYL3LCWYD2.ja_JP.md` |
| SRC-JP-AMZ-GQTEXVLXTNPZGYVW | 一酸化炭素警報器 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GQTEXVLXTNPZGYVW | S1 | 2026-10-10 | `policy/snapshots/JP/GQTEXVLXTNPZGYVW.ja_JP.md` |
| SRC-JP-AMZ-GR4K5294J35J5VM5 | ガストーチ | https://sellercentral.amazon.co.jp/help/hub/reference/external/GR4K5294J35J5VM5 | S1 | 2026-10-10 | `policy/snapshots/JP/GR4K5294J35J5VM5.ja_JP.md` |
| SRC-JP-AMZ-GR5HZPEMV6MQUDGJ | トランスミッター | https://sellercentral.amazon.co.jp/help/hub/reference/external/GR5HZPEMV6MQUDGJ | S1 | 2026-10-10 | `policy/snapshots/JP/GR5HZPEMV6MQUDGJ.ja_JP.md` |
| SRC-JP-AMZ-GRB4UM99MAKCHRZZ | 家電リサイクル法に基づく義務に関する規約 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GRB4UM99MAKCHRZZ | S1 | 2026-10-10 | `policy/snapshots/JP/GRB4UM99MAKCHRZZ.ja_JP.md` |
| SRC-JP-AMZ-GRBE9D3BXQJPMA6V | 子ども用フェイスマスク | https://sellercentral.amazon.co.jp/help/hub/reference/external/GRBE9D3BXQJPMA6V | S1 | 2026-10-10 | `policy/snapshots/JP/GRBE9D3BXQJPMA6V.ja_JP.md` |
| SRC-JP-AMZ-GRBJLG9QTR5ZQURQ | 無線 LANデバイス | https://sellercentral.amazon.co.jp/help/hub/reference/external/GRBJLG9QTR5ZQURQ | S1 | 2026-10-10 | `policy/snapshots/JP/GRBJLG9QTR5ZQURQ.ja_JP.md` |
| SRC-JP-AMZ-GRF7Z2NN4T35ZZFD | ガスの法律および規制 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GRF7Z2NN4T35ZZFD | S1 | 2026-10-10 | `policy/snapshots/JP/GRF7Z2NN4T35ZZFD.ja_JP.md` |
| SRC-JP-AMZ-GRKGPHRX533JSRCK | 汽车用千斤顶 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GRKGPHRX533JSRCK | S1 | 2026-10-10 | `policy/snapshots/JP/GRKGPHRX533JSRCK.zh_CN.md` |
| SRC-JP-AMZ-GRLKLZ6WQ9R259LC | 商品の安全性に関する出品制限 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GRLKLZ6WQ9R259LC | S1 | 2026-10-10 | `policy/snapshots/JP/GRLKLZ6WQ9R259LC.ja_JP.md` |
| SRC-JP-AMZ-GRVULZL8LVDHD49P | 防災警報器、感知器 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GRVULZL8LVDHD49P | S1 | 2026-10-10 | `policy/snapshots/JP/GRVULZL8LVDHD49P.ja_JP.md` |
| SRC-JP-AMZ-GS828T4S4CFMFREQ | トランシーバー | https://sellercentral.amazon.co.jp/help/hub/reference/external/GS828T4S4CFMFREQ | S1 | 2026-10-10 | `policy/snapshots/JP/GS828T4S4CFMFREQ.ja_JP.md` |
| SRC-JP-AMZ-GSJFE8S8AES7F7VG | モバイルバッテリー/パワーバンク | https://sellercentral.amazon.co.jp/help/hub/reference/external/GSJFE8S8AES7F7VG | S1 | 2026-10-10 | `policy/snapshots/JP/GSJFE8S8AES7F7VG.ja_JP.md` |
| SRC-JP-AMZ-GSQZZGJ8SXC2HC4Q | スマートプラグ製品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GSQZZGJ8SXC2HC4Q | S1 | 2026-10-10 | `policy/snapshots/JP/GSQZZGJ8SXC2HC4Q.ja_JP.md` |
| SRC-JP-AMZ-GT3XLUHYCWPM3THX | 子ども用ジュエリー | https://sellercentral.amazon.co.jp/help/hub/reference/external/GT3XLUHYCWPM3THX | S1 | 2026-10-10 | `policy/snapshots/JP/GT3XLUHYCWPM3THX.ja_JP.md` |
| SRC-JP-AMZ-GT7A9YNUV4MY43GB | 磁石製娯楽用品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GT7A9YNUV4MY43GB | S1 | 2026-10-10 | `policy/snapshots/JP/GT7A9YNUV4MY43GB.ja_JP.md` |
| SRC-JP-AMZ-GT8V6T7U8GZZK3SU | 車用ヒートシート | https://sellercentral.amazon.co.jp/help/hub/reference/external/GT8V6T7U8GZZK3SU | S1 | 2026-10-10 | `policy/snapshots/JP/GT8V6T7U8GZZK3SU.ja_JP.md` |
| SRC-JP-AMZ-GU32QMNPJS8L3JHJ | 歩行器 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GU32QMNPJS8L3JHJ | S1 | 2026-10-10 | `policy/snapshots/JP/GU32QMNPJS8L3JHJ.ja_JP.md` |
| SRC-JP-AMZ-GU7U29CYFK6PNU2V | 磁性パテ | https://sellercentral.amazon.co.jp/help/hub/reference/external/GU7U29CYFK6PNU2V | S1 | 2026-10-10 | `policy/snapshots/JP/GU7U29CYFK6PNU2V.ja_JP.md` |
| SRC-JP-AMZ-GUG6JJCDN6YYQYJP | 乳児用セルフフィーディング商品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GUG6JJCDN6YYQYJP | S1 | 2026-10-10 | `policy/snapshots/JP/GUG6JJCDN6YYQYJP.ja_JP.md` |
| SRC-JP-AMZ-GUTKF9TQM6VWTSYB | 二段ベッド | https://sellercentral.amazon.co.jp/help/hub/reference/external/GUTKF9TQM6VWTSYB | S1 | 2026-10-10 | `policy/snapshots/JP/GUTKF9TQM6VWTSYB.ja_JP.md` |
| SRC-JP-AMZ-GUTZ2R2DD6P2UMVB | 商品の直接検証: サードパーティの試験、検査、認証サービス | https://sellercentral.amazon.co.jp/help/hub/reference/external/GUTZ2R2DD6P2UMVB | S1 | 2026-10-10 | `policy/snapshots/JP/GUTZ2R2DD6P2UMVB.ja_JP.md` |
| SRC-JP-AMZ-GV3N5ES8KNR3W3VG | 電波法 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GV3N5ES8KNR3W3VG | S1 | 2026-10-10 | `policy/snapshots/JP/GV3N5ES8KNR3W3VG.ja_JP.md` |
| SRC-JP-AMZ-GV49WNPCZU5GW9WX | 抱っこ紐 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GV49WNPCZU5GW9WX | S1 | 2026-10-10 | `policy/snapshots/JP/GV49WNPCZU5GW9WX.ja_JP.md` |
| SRC-JP-AMZ-GV9VZ5A7PJZQYRFF | スクイーズ玩具 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GV9VZ5A7PJZQYRFF | S1 | 2026-10-10 | `policy/snapshots/JP/GV9VZ5A7PJZQYRFF.ja_JP.md` |
| SRC-JP-AMZ-GVS6B9TTVLM63JMM | 墜落制止用器具 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GVS6B9TTVLM63JMM | S1 | 2026-10-10 | `policy/snapshots/JP/GVS6B9TTVLM63JMM.ja_JP.md` |
| SRC-JP-AMZ-GW6HK2RDRNNFW2ML | ペイントストリッパー | https://sellercentral.amazon.co.jp/help/hub/reference/external/GW6HK2RDRNNFW2ML | S1 | 2026-10-10 | `policy/snapshots/JP/GW6HK2RDRNNFW2ML.ja_JP.md` |
| SRC-JP-AMZ-GX44XMQX3ZKWRPZR | 乳児用スリープポジショナー関連商品 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GX44XMQX3ZKWRPZR | S1 | 2026-10-10 | `policy/snapshots/JP/GX44XMQX3ZKWRPZR.ja_JP.md` |
| SRC-JP-AMZ-GXDAD4N3TU3AK5TD | 湯たんぽ | https://sellercentral.amazon.co.jp/help/hub/reference/external/GXDAD4N3TU3AK5TD | S1 | 2026-10-10 | `policy/snapshots/JP/GXDAD4N3TU3AK5TD.ja_JP.md` |
| SRC-JP-AMZ-GXE3TPKYT83DDWJM | アジ化ナトリウム | https://sellercentral.amazon.co.jp/help/hub/reference/external/GXE3TPKYT83DDWJM | S1 | 2026-10-10 | `policy/snapshots/JP/GXE3TPKYT83DDWJM.ja_JP.md` |
| SRC-JP-AMZ-GXMGGPL6LC4CVXHT | リコールと商品の安全性 | https://sellercentral.amazon.co.jp/help/hub/reference/external/GXMGGPL6LC4CVXHT | S1 | 2026-10-10 | `policy/snapshots/JP/GXMGGPL6LC4CVXHT.ja_JP.md` |
| SRC-JP-AMZ-GXZQD85B3GHE8W89 | 発射型のおもちゃ | https://sellercentral.amazon.co.jp/help/hub/reference/external/GXZQD85B3GHE8W89 | S1 | 2026-10-10 | `policy/snapshots/JP/GXZQD85B3GHE8W89.ja_JP.md` |
| SRC-JP-AMZ-GYATMS8KBP6VYCFF | 圧力なべ | https://sellercentral.amazon.co.jp/help/hub/reference/external/GYATMS8KBP6VYCFF | S1 | 2026-10-10 | `policy/snapshots/JP/GYATMS8KBP6VYCFF.ja_JP.md` |
| SRC-JP-AMZ-GYR9JPM3V2MDWPQ2 | ノートパソコン用/スマートフォン用バッテリー | https://sellercentral.amazon.co.jp/help/hub/reference/external/GYR9JPM3V2MDWPQ2 | S1 | 2026-10-10 | `policy/snapshots/JP/GYR9JPM3V2MDWPQ2.ja_JP.md` |
| SRC-JP-AMZ-GYZPAMEJCXFTZHH5 | レーザーポインター | https://sellercentral.amazon.co.jp/help/hub/reference/external/GYZPAMEJCXFTZHH5 | S1 | 2026-10-10 | `policy/snapshots/JP/GYZPAMEJCXFTZHH5.ja_JP.md` |
| SRC-JP-AMZ-GZ4263KL7TUX2KCG | 登山用ロープ | https://sellercentral.amazon.co.jp/help/hub/reference/external/GZ4263KL7TUX2KCG | S1 | 2026-10-10 | `policy/snapshots/JP/GZ4263KL7TUX2KCG.ja_JP.md` |
| SRC-JP-AMZ-GZH3YZUQDTU9XY4Z | 組合せおもちゃ | https://sellercentral.amazon.co.jp/help/hub/reference/external/GZH3YZUQDTU9XY4Z | S1 | 2026-10-10 | `policy/snapshots/JP/GZH3YZUQDTU9XY4Z.ja_JP.md` |
| SRC-JP-AMZ-GZHMAZAQU5H54P9Z | 磁気ビルディングタイル | https://sellercentral.amazon.co.jp/help/hub/reference/external/GZHMAZAQU5H54P9Z | S1 | 2026-10-10 | `policy/snapshots/JP/GZHMAZAQU5H54P9Z.ja_JP.md` |
<!-- /H-SECTION -->

### 待核实/冲突

<!-- TODO-SECTION -->
| # | 事项 | 现状/冲突 | 涉及规则 |
|---|---|---|---|
| 1 | 需要出品许可的分类清单 | 日本站《出品許可が必要なカテゴリーと商品》（G200333160）和《商品カテゴリーの概要》（G200332540）都没有列出完整分类；本次只确认了「食品」类目（G201511970，zh_CN 版）和流媒体播放器需申请。其他（如珠宝、手表、药妆）是否需要，须在卖家后台逐个 ASIN 查看 | JP-L2-APPROVAL-001、JP-L2-FOOD-001 |
| 2 | FBA 与消防法危险物 | 《FBA 禁止商品》说消防法第 1–6 类全部禁运；《危险物确认指南》说「消防法（第 4 类除外）」不可 FBA，并允许危险物纳品项目参与者限量入仓第 3 类可燃液体 | JP-L4-FBA-004、JP-L4-DG-002 |
| 3 | FBA 与气雾剂 | 《FBA 禁止商品》明确禁运气雾剂（发胶、止汗喷雾、喷漆等）；《危险物确认指南》把 2.1/2.2 类气体列为项目参与者可限量入仓 | JP-L4-FBA-006 |
| 4 | FBA 与磁铁 | 《FBA 禁止商品》禁运钕磁铁及强磁商品；《危险物确认指南》把 UN2807 磁性材料（音箱、耳机、磁贴、玩具）列为可入仓第 9 类 | JP-L4-FBA-010 |
| 5 | 锂电池能量档 | 《锂电池要求》表格把日本站所有能量档（含 >300Wh 电池、>60Wh 电芯）都标「許可済み」，与其他站点差异很大，疑为表格口径问题；实际以 ASIN チェック为准 | JP-L4-LIB-001 |
| 6 | 特定小型原付 | 《カー&バイク用品》写「亚马逊许可的除外」禁售，《电动出行设备》页直接列为禁售；《电动出行设备》页还把电动滑板车同时列在禁售例子和文件要求里 | JP-L2-SMALLMOPED-001、JP-L1-AUTO-004、JP-L3-EMOBILITY-001 |
| 7 | 平衡车 | 汽车页禁止「电动机驱动的车辆」，电动出行页允许平衡车/电动独轮车/电动滑板凭 PSE+电波法+UL 2272 文件销售；按后者处理 | JP-L1-AUTO-004、JP-L3-EMOBILITY-001 |
| 8 | 动物牙齿 | 动物页把「鲨鱼牙饰品」列为可售，同页又禁止「含动物牙齿的商品」 | JP-L1-ANIMAL-003 |
| 9 | 烟斗/水烟管 | 烟草页允许「水烟管」「烟斗」，又禁止各种材质的吸食烟斗（吸毒用具）；边界按用途和文案判断 | JP-L1-PARAPHERNALIA-001 |
| 10 | 加热衣物 | 《商品安全出品限制》禁售电池加热衣物和鞋垫，但《リコールと商品の安全性》仍列有「衣類用モバイルバッテリー」文件审核页 | JP-L1-HEATEDWEAR-001 |
| 11 | E-27 型 LED 灯泡 | 安全禁售清单列出「E-27タイプLED電球」，但 LED 电球页只是 PSE 文件审核页，没有说明禁售的具体条件（日本主流灯头为 E26/E17） | JP-L1-E27LED-001 |
| 12 | 无尼古丁电子烟 | 烟草页只禁止含尼古丁/医药成分的电子烟及其配件；无尼古丁 VAPE 是否可售、可否 FBA 未写明 | JP-L1-VAPE-001 |
| 13 | 菜刀刃长 | 武器页禁止刃长 15cm 以上的钢制刀具，同时把菜刀列为可售；超过 15cm 的厨刀是否可售未写明 | JP-L1-KNIFE-001 |
| 14 | 海外卖家自发货化妆品 | 个人进口代行禁令文字针对「日本国内卖家接单、海外直送」；海外卖家从中国直接发货化妆品是否被允许，未见明文（法规层面需日本制造销售业者，属 L5） | JP-L1-HEALTH-003、JP-L1-COSME-001 |
| 15 | 资质提交路径 | 酒类许可、玩具枪会员资格、计量法、食品接触材料的提交方式页面都未写明 | JP-L2-ALCOHOL-001、JP-L2-TOYGUN-001、JP-L3-KEIRYO-001、JP-L3-FOODCONTACT-001 |
| 16 | 提交邮箱不一致 | PSE 页写 jp-electronics-safety@amazon.co.jp，无线类商品页写 jp-giteki-safety@amazon.co.jp，串灯页写 jp-safety-regulation@amazon.co.jp，推车页写 child-safety@amazon.co.jp；PSC 页未写邮箱（走账户状况） | JP-L3-PSE-001、JP-L3-RADIO-001 |
| 17 | 儿童饰品标准 | 政策表列食品卫生法/ST/ASTM F963/EN 71/ISO 8124/GB 6675，提交清单只列食品卫生法/ST/EN 71/ISO 8124 | JP-L3-KIDSJEWEL-001 |
| 18 | PSE 页旧表述 | PSE 页仍写「2024 年时点海外事业者不能做届出」，与同页 2025-12-25 新制度并存，以新制度为准 | JP-L3-PSE-001、JP-L3-4LAW-001 |
| 19 | 生效日期缺失 | 圆柱形锂电池禁售、TIC 验证、锂电池家电 JIS 报告、新建 Listing 预审、「文件不得 AI 生成」等政策页均无生效日期 | 见 G 节 |
| 20 | 季节性限制 | 未找到日本站季节性（如夏季温敏商品）销售限制页面 | — |
| 21 | 未映射到规则的禁令 | 「其他商品」页禁止《特定商取引法》规制的特定继续性服务提供和业务提供诱引销售交易（属交易类型，无对应产品族），只在 A 节记录 | — |
| 22 | 冷藏/冷冻与 FBA | 《FBA 禁止商品》说需冷藏或温控的商品禁运；《要期限管理商品および温度管理が必要な商品》显示日本站已有冷冻食品 FBA（特定仓库、-23～-27℃）。冷藏（チルド）商品仍不可 | JP-L4-FBA-002、JP-L4-FROZEN-001 |
| 23 | 珠宝手表正规经销要求 | 「非正规经销商或无厂商保证书的宝石商品（含手表）」对自有品牌饰品是否适用未说明 | JP-L1-GEMS-001 |
| 24 | 未能抓取正文的页面 | 「乳幼儿用口罩」（GKHXPRALUELYGM47）、「吸水树脂玩具」（GWXVGXZX8BTDPC9V）、「倾斜型乳幼儿床」（G5CGB945FHXGU62C）的 ja_JP 和 zh_CN 版多次只返回导航壳，相关结论改以《商品安全出品限制》（GRLKLZ6WQ9R259LC）及同类页面为依据；另有 6 个页面（儿童玩具、坐式婴儿车、汽车千斤顶、食品类目、三氯乙酸等）只取得 zh_CN 版或重试后才取得 | JP-L1-INFANTMASK-001、JP-L3-WATERBEADS-001、JP-L1-SLEEPPOS-001 |
<!-- /TODO-SECTION -->

## 第二部分 · 日本法规与进口要求（L5–L6）

> 规则包版本：draft · 调研日期：2026-10-10 · 本文描述日本当地法规（L5）和进口清关要求（L6），不构成法律意见；亚马逊平台政策（L1–L4）见平台层文档。
> 每条结论后用 [SRC-…] 标注来源（见 `rules/sources/JP_regulation.yaml`），用 [R:规则ID] 关联机读规则（`rules/sites/JP_regulation.yaml`）。
> 来源级别：S1 亚马逊官方 · S2 政府官方 · S3 二手。本文所用来源全部为 S2（经产省、总务省、厚劳省、消费者厅、国交省、警察厅、税关、都道府县页面，以及 e-Gov 法令检索的条文全文）；只看到搜索摘要的标注「（仅搜索摘要，待核）」。
> 抓取说明：经产省页面经 `tools/fetch_help.py`（r.jina.ai）抓取；其他政府页面、PDF 直接 HTTP 抓取；法律条文经 e-Gov 法令 API v1 取全文。快照均在 `policy/snapshots/JP/`。

### 本章要点（给运营的 5 句话）

1. **2025-12-25 起，海外卖家本人就是「特定输入事业者」**：只要用亚马逊（FBA 或自发货）把 PSE、PSC、PSTG、PSLPG 对象产品直接卖给日本消费者，就必须以自己名义向经产省做事业届出、选任日本国内管理人，并在产品上标示自己的名称和 PS 标志；否则平台可被经产省要求下架 [SRC-JP-GOV-METI-TOKUTEIYUNYU][SRC-JP-GOV-METI-HANREISHU] [R:JP-L5-PSIMPORT-001][R:JP-L5-PSIMPORT-003]。
2. **亚马逊 PSE 帮助页「海外事业者不能届出」一句已过时**，以新法为准 [R:JP-L5-PSIMPORT-004]。
3. **儿童产品进入「子供 PSC」时代**：3 岁以下玩具（2025-12-25）、婴儿床（2025-12-25 指定，旧标志 2027-03-25 起禁售）、床护栏与婴儿车（2026-07-08 起，过渡期分别到 2027-07-07、2028-07-07）[R:JP-L5-PSC-010]～[R:JP-L5-PSC-014]。
4. **移动电源三重管：PSE 圆标（2019 起）＋资源有效利用促进法自主回收（2026-04-01 起追加一体型移动电源）＋FBA 危险品** [R:JP-L5-PSE-003][R:JP-L5-RECYCLE-002]。
5. **文案红线**：杂货/食品/化妆品不得宣称治疗、美白、育毛、驱蚊（卫生害虫）、杀菌消毒等医药品或医药部外品功效（药机法第66、68条，课征金 4.5%）；刀具不得宣传护身携带；电动车不得把带油门的车称作「电动助力自行车」[R:JP-L5-PMDADS-001][R:JP-L5-COSMETIC-003][R:JP-L5-KNIFE-002][R:JP-L5-MOBILITY-004]。

---

### E. 当地法规（L5，按产品族）

#### E.0 共通框架：制品安全 4 法与「特定输入事业者」

日本用 4 部法律给高风险消费品贴「PS 标志」：电气用品安全法（PSE）、消费生活用制品安全法（PSC／子供PSC）、燃气事业法（PSTG）、液化石油气法（PSLPG）。制造/输入事业者须届出、确认符合技术基准、做检查并自行标示；销售者（含平台卖家）不得销售无标志的对象产品 [SRC-JP-GOV-METI-TOKUTEIYUNYU-2604]。

| 法律 | 菱形（须登录检查机关检查） | 圆形（自主检查） | 子供 PSC |
|---|---|---|---|
| 电安法（PSE，共 457 品目） | 特定电气用品 116 品目：AC 适配器、电源线、插头、排插、延长线、电动/电热玩具、电气按摩器、观赏鱼加热器等 [SRC-JP-GOV-METI-DENAN-SPECIFIED] | 341 品目：LED 灯具、电视、音响、锂离子蓄电池（移动电源）、电热毯、电饭煲等 [SRC-JP-GOV-METI-DENAN-NONSPECIFIED] | — |
| 消安法（PSC，共 15 品目） | 特别特定制品：婴儿床、激光笔、浴缸温水循环器、打火机 | 特定制品：家用压力锅、摩托车头盔、登山绳、石油暖炉/热水器/浴锅、磁铁娱乐用品、吸水树脂玩具 | 乳幼儿用玩具、婴儿床、床护栏、婴儿车 [SRC-JP-GOV-EGOV-SHOUAN-REI] |
| 燃气事业法（PSTG，8 品目） | 燃气浴锅燃烧器等 4 品目 | 燃气灶等 4 品目 | — |
| 液石法（PSLPG，17 品目） | 卡式炉、携带用 LPG 喷灯（含燃气喷枪）等 8 品目 | 一般燃气灶等 9 品目 | — |

PSC 各品目对应规则：摩托车头盔 [R:JP-L5-PSC-001]、家用压力锅 [R:JP-L5-PSC-002]、登山用绳（身体确保用）[R:JP-L5-PSC-003]、石油暖炉/热水器/浴锅 [R:JP-L5-PSC-004]、磁铁娱乐用品 [R:JP-L5-PSC-005]、吸水树脂玩具 [R:JP-L5-PSC-006]、激光笔 [R:JP-L5-PSC-007]、打火机 [R:JP-L5-PSC-008]、浴缸用温水循环器 [R:JP-L5-PSC-009]、乳幼儿用玩具 [R:JP-L5-PSC-010]、婴儿床 [R:JP-L5-PSC-011][R:JP-L5-PSC-012]、床护栏 [R:JP-L5-PSC-013]、婴儿车 [R:JP-L5-PSC-014]（品目定义见消安法施行令别表第一 [SRC-JP-GOV-EGOV-SHOUAN-REI]，指定/施行日见 [SRC-JP-GOV-METI-SHOUAN-MARK]）。

**特定输入事业者制度（2025-12-25 施行）** [SRC-JP-GOV-METI-TOKUTEIYUNYU][SRC-JP-GOV-METI-TOKUTEIYUNYU-2604][SRC-JP-GOV-EGOV-DENAN][SRC-JP-GOV-EGOV-SHOUAN]

| 项目 | 要求 | 规则 |
|---|---|---|
| 谁是特定输入事业者 | 在外国、不经日本国内输入事业者、利用取引数字平台等把对象产品直接卖给日本消费者的海外事业者。经产省「凡例集」：FBA（フルフィルメントサービス）模式和海外直邮模式，届出者都是海外卖家本人；若海外卖家先卖给日本国内事业者、由其在平台销售，则由国内事业者届出并在产品上标国内事业者名称；个人输入、输入代行不算「输入」 [SRC-JP-GOV-METI-HANREISHU] | [R:JP-L5-PSIMPORT-001] |
| 事业届出 | 按产品「区分」逐一届出，事业开始后 30 日内；届出书须日文；海外事业者无法使用保安ネット（需法人番号），按 METI 指引用电子邮件/e-Gov 或纸质，或委托日本代理人（附委任状） | [R:JP-L5-PSIMPORT-001] |
| 国内管理人 | 个人或法人均可；须在日本有住所、能用日语会话、被授予接收处分通知的权限、遵守法令；双方须签含 5 项内容的委托合同；按产品区分选任 | [R:JP-L5-PSIMPORT-001] |
| 附件 | 国内管理人登记事项证明书或住民票（3 个月内）、权限证明书、委托合同副本（日/英文）、誓约书、委任状（代办时） | [R:JP-L5-PSIMPORT-001] |
| 持续义务 | 国内管理人每满 1 年报告联络体制；解约须提前 30 日报告；检查记录副本交国内管理人保存 | [R:JP-L5-PSIMPORT-002] |
| 执法 | 经产大臣可要求平台删除危险出品；届出事项公表；违法者公表；「連絡不通事業者リスト」 | [R:JP-L5-PSIMPORT-003] |

> **与亚马逊页面的矛盾**：亚马逊 PSE 帮助页（GHJPQ6KDLA9N5F4L，S1，平台层登记）正文仍写「2024 年时点海外事业者不能届出，须由日本国内有住所的事业者届出」。这句话来自 METI 2018 年解释（海外企业只有在日本登记代表者时才能届出）[SRC-JP-GOV-METI-DENAN-KAIGAI-2018]。但电安法第3条第2号已于 2025-12-25 修订，明确海外事业者可作为特定输入事业者届出 [SRC-JP-GOV-EGOV-DENAN]；同一页面「海外の出品者への注意事項」和「海外出品者向け製品安全4法法令遵守ガイド」（GJXRBNGX52EMJZZB）也已要求提交写有海外卖家本人及国内管理人名称住所的届出书。**结论：以新法为准，旧句应视为过时。** [R:JP-L5-PSIMPORT-004]

#### E.1 电子电器（电气用品安全法，PSE）

| 适用法规 | 必需的认证/测试 | 注册/备案 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 电气用品安全法 | 圆形：技术基准适合确认（解释别表第八或第十二/J 规格，含 EMC）＋全数自主检查；菱形：另加登录检查机关适合性检查证明书 | 电气用品制造/输入事业届出（区分别） | PSE 标志（圆/菱）、届出事业者名、额定电压/功率；菱形另标登录检查机关名 | 经济产业省 | [R:JP-L5-PSE-001][R:JP-L5-PSE-002] |

- 销售或以销售为目的陈列无 PSE 标志的电气用品违法，新品二手同样适用；处 1 年以下拘禁刑或 100 万日元以下罚金 [SRC-JP-GOV-EGOV-DENAN] [R:JP-L5-PSE-004][R:JP-L5-PSE-007]。
- AC 适配器、USB 充电头、电源线、排插、延长线、卷线盘都是**菱形**品；带 AC 插头的电动/电热玩具、电气按摩器、高频脱毛器、电击灭蚊器、观赏鱼加热器/气泵、电气便座、携带发电机也是菱形 [SRC-JP-GOV-METI-DENAN-SPECIFIED] [R:JP-L5-PSE-002]。
- 纯 USB/电池供电的小电器本体一般不在 PSE 范围，但随附适配器须菱形 PSE（「本体非对象」为推导，待核实）[R:JP-L5-PSE-006]。
- IEC/UL 报告不等于符合日本技术基准，日本差异项须补测（METI 移动电源 FAQ A12）[SRC-JP-GOV-METI-DENAN-MLB-FAQ]。
- 家电回收法：空调、电视、冰箱/冷冻柜、洗衣机/干衣机的零售业者负有旧机回收义务 [SRC-JP-GOV-EGOV-KADEN-RECYCLE] [R:JP-L5-RECYCLE-003]。

#### E.2 电池与移动电源

| 适用法规 | 必需的认证/测试 | 注册/备案 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 电安法（锂离子蓄电池，单电芯 ≥400Wh/L） | J62368-1(2023)＋J55032，或 J62133-2(2021)；外观与输出电压全数检查，记录保存 3 年 | 事业届出（区分：リチウムイオン蓄電池） | 外壳标圆形 PSE、届出事业者名、额定电压（升压后输出值）、额定容量等 | 经产省 | [R:JP-L5-PSE-003] |
| 资源有效利用促进法 | — | 自主回收与再资源化体制；2026-04-01 起一体型移动电源、智能手机、加热式烟草设备追加为对象，电源装置年 1,000 台以上受劝告/命令 | 小型二次电池回收标示 | 经产省、环境省 | [R:JP-L5-RECYCLE-001][R:JP-L5-RECYCLE-002] |

- 移动电源（含锂聚合物）自 2019-02-01 起无 PSE 不得销售；耳机/电子烟充电盒按移动电源处理；AC 输出的便携电源、UPS、带保护装置的汽车应急启动电源本体非移动电源对象 [SRC-JP-GOV-METI-DENAN-MLB-FAQ] [R:JP-L5-PSE-003][R:JP-L5-PSE-005]。
- 电芯可拆卸的移动电源：外壳非对象，但装着的锂离子电池是对象 [SRC-JP-GOV-METI-DENAN-PORTABLE-LI]。
- 资源有效利用促进法施行令别表第八：电源装置以年生产/输入 1,000 台为劝告命令对象门槛 [SRC-JP-GOV-EGOV-SHIGEN-REI][SRC-JP-GOV-METI-RECYCLE-2604]。

#### E.3 无线设备（电波法）

| 适用法规 | 必需的认证/测试 | 注册/备案 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 电波法 | 技术基准适合证明或工事设计认证（技适），由登录证明机关出具 | — | 技适标志＋R 编号（本体或电子显示；内置认证模块的产品可在外部标同一表示） | 总务省 | [R:JP-L5-RADIO-001] |

- 蓝牙耳机/音箱也会发射电波，必须有技适；无技适设备的使用可构成不法无线局（1 年以下拘禁刑或 100 万日元以下罚金）[SRC-JP-GOV-SOUMU-GITEKI-QA]。
- 制造/输入/销售业者有不销售基准不适合设备的努力义务，总务大臣可对广泛销售的不适合设备劝告、公表、命令（第102条の11）；总务省每年试买网购品并公布超标型号、要求停售并通报平台 [SRC-JP-GOV-EGOV-DENPA][SRC-JP-GOV-SOUMU-SHIBAI-R6] [R:JP-L5-RADIO-005]。
- 不能合法使用的品类：FRS/GMRS 对讲机、外国规格婴儿监视器、外国动物追踪器 [R:JP-L5-RADIO-002]；手机信号放大器 [R:JP-L5-RADIO-003]；干扰器 [R:JP-L5-RADIO-004]（推导，待核实）。
- 无人机 5.7/5.8GHz 图传须免许与资格 [SRC-JP-GOV-SOUMU-DRONE-RADIO] [R:JP-L5-RADIO-006]。

#### E.4 灯具

LED 电灯器具（1W 以上）、LED 灯泡、电气台灯等为圆形 PSE 品，配套 AC 适配器为菱形 [SRC-JP-GOV-METI-DENAN-NONSPECIFIED] [R:JP-L5-PSE-001][R:JP-L5-PSE-002]。台灯用荧光灯器具还在家庭用品品质表示法电气机械器具清单内 [R:JP-L5-HOUSEHOLDLABEL-003]。

#### E.5 儿童玩具

| 适用法规 | 必需的认证/测试 | 注册/备案 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 消安法：乳幼儿用玩具（未满 36 个月） | 技术基准（ISO 8124-1/-2、EN 71、ASTM F963 等例示规格；ST 基准适合视为符合）＋使用年龄基准 | 事业届出（海外卖家＋国内管理人） | 圆形子供 PSC、届出事业者名、日文对象年龄、「保護者の下で遊ばせてください」等监护警示 | 经产省 | [R:JP-L5-PSC-010] |
| 消安法：磁铁娱乐用品、吸水树脂玩具 | 技术基准（磁通量、膨胀等） | 事业届出 | 圆形 PSC | 经产省 | [R:JP-L5-PSC-005][R:JP-L5-PSC-006] |
| 食品卫生法：指定玩具（6 岁未满会入口的玩具） | 告示 370 号玩具规格（重金属、PVC 邻苯类可塑剂等） | 输入时食品等输入届出 | — | 消费者厅（规格）、厚劳省检疫所（输入） | [R:JP-L5-TOYFOOD-001][R:JP-L6-TOYFOOD-001] |
| 电安法：电动/电热玩具（AC） | 菱形 PSE | 事业届出 | 菱形 PSE | 经产省 | [R:JP-L5-PSE-002] |
| 电波法：遥控玩具 | 微弱基准或技适 | — | 技适（如需） | 总务省 | [R:JP-L5-RADIO-005] |

- 2025-12-25 以后制造或输入的 3 岁以下玩具没有子供 PSC 就不能卖；之前制造/输入的库存可继续卖 [SRC-JP-GOV-METI-GANGU-KISEI][SRC-JP-GOV-METI-PS-GUIDE]。
- 对象年龄必须有合理依据，不能为规避规制标偏高年龄；外文或纯数字的年龄标示须改为日文 [SRC-JP-GOV-METI-GANGU-KISEI]。
- 二手子供用特定制品有「中古品特例」，具体条件待核实 [R:JP-L5-PSC-016]。

#### E.6 婴童用品（婴儿床、床护栏、婴儿车）

| 品目 | 区分 | 时间点 | 要求 | 规则ID |
|---|---|---|---|---|
| 婴儿床（24 个月以内，摇动型除外） | 特别特定制品＋子供用特定制品 | 2025-12-25 指定；**2027-03-25 起旧标志品不得销售**（含流通库存） | 登录检查机关检查、子供 PSC、日文对象年龄与警示 | [R:JP-L5-PSC-011][R:JP-L5-PSC-012] |
| 床护栏（60 个月以内） | 子供用特定制品＋特定制品 | 2026-07-08 起；过渡期至 2027-07-07 | 技术基准（SG「幼児用ベッドガード」基准检查被认可）、禁止 18 个月未满使用的表示、圆形子供 PSC | [R:JP-L5-PSC-013] |
| 婴儿车（36 个月以内，步行推行） | 子供用特定制品＋特定制品 | 2026-07-08 起；过渡期至 2028-07-07 | 技术基准（SG Type I/II 认可）、圆形子供 PSC；三轮车/乘用玩具、带座行李箱、医院保育所专用品除外 | [R:JP-L5-PSC-014] |

来源：[SRC-JP-GOV-METI-BEDGUARD-STROLLER][SRC-JP-GOV-METI-PS-GUIDE][SRC-JP-GOV-METI-SHOUAN-MARK][SRC-JP-GOV-EGOV-SHOUAN-REI]。
- **2026-04 的床护栏/婴儿车「草案」已定稿**：技术基准省令 2026-04-27 改正，政令把两品目列入施行令别表第一第14、15号，2026-07-08 起施行；2026-07-17 与制品安全协会交换无行动函（SG 基准检查可作为适合确认方法）[SRC-JP-GOV-METI-BEDGUARD-STROLLER][SRC-JP-GOV-EGOV-SHOUAN-REI]。
- 婴儿奶瓶等哺乳用具在家庭用品品质表示法杂货工业品清单内，且作为食品接触器具受食品卫生法约束 [R:JP-L5-HOUSEHOLDLABEL-003][R:JP-L5-FOODCONTACT-001]。

#### E.7 食品接触材料

| 适用法规 | 必需的认证/测试 | 注册/备案 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 食品卫生法第18条＋告示 370 号 | 材质试验与溶出试验 | — | — | 消费者厅（2024-04-01 起） | [R:JP-L5-FOODCONTACT-001] |
| 合成树脂正面清单 | 基材、添加剂须收载于正面清单；向下游传达适合信息 | — | — | 消费者厅 | [R:JP-L5-FOODCONTACT-002] |
| 食品卫生法第27条 | — | **每次输入**向检疫所提交食品等输入届出 | — | 厚劳省检疫所 | [R:JP-L6-FOODCONTACT-001] |
| 家庭用品品质表示法 | — | — | 合成树脂餐厨具：树脂种类、耐热温度等；金属锅/水壶/保温瓶、强化玻璃餐具、铝箔等也有表示规程 | 消费者厅 | [R:JP-L5-HOUSEHOLDLABEL-002][R:JP-L5-HOUSEHOLDLABEL-003] |

- 正面清单的经过措置 2025-05-31 满了，2025-06-01 起全面适用（2020-06-01 施行）[SRC-JP-GOV-CAA-KIGU-PL]。
- 输入届出与数量、运输形态无关，国际邮件也要届出；不合格品须废弃或退运 [SRC-JP-GOV-MHLW-FOOD-IMPORT]。
- 家用压力锅还是消安法特定制品 [R:JP-L5-PSC-002]。

#### E.8 食品、饮料、保健食品

- 输入食品/保健食品须逐次做食品等输入届出 [SRC-JP-GOV-MHLW-FOOD-IMPORT] [R:JP-L6-FOOD-001]。
- 普通食品不得宣称治疗、预防、增强免疫、燃脂减肥等医药品功效（药机法第68条未承认医药品广告禁止、第66条虚假夸大广告），可被命令停止并处课征金 [SRC-JP-GOV-MHLW-AD-RULES][SRC-JP-GOV-EGOV-YAKKI] [R:JP-L5-FOOD-001]。
- 含医药品成分的「健康食品」即未承认医药品，不能卖 [SRC-JP-GOV-MHLW-PERSONAL-IMPORT] [R:JP-L5-FOOD-002]。
- 食品表示法（日文标签）、机能性表示食品/特定保健用食品制度本次未调研，见待核实。

#### E.9 化妆品与医药部外品

| 适用法规 | 必需的认证/测试 | 注册/备案 | 标签要求 | 主管机构 | 规则ID |
|---|---|---|---|---|---|
| 药机法（化妆品） | GQP/GVP 体制 | 化妆品制造贩卖业许可（＋制造业许可：包装・表示・保管）；品目别制造贩卖届出；外国制造业者届出（经 PMDA） | 第61条法定表示：制造贩卖业者名称住所、名称、批号、指定成分（全成分）、使用期限等，日文 | 都道府县药务课、厚劳省、PMDA | [R:JP-L5-COSMETIC-001][R:JP-L5-COSMETIC-002] |
| 药机法（医药部外品） | 品目承认 | 医药部外品制造贩卖业许可＋承认 | 法定表示 | 厚劳省/都道府县 | [R:JP-L5-QUASIDRUG-001] |

- 自行输入并在国内贴日文标签需制造业许可；即使海外已贴日文标签，也要在国内许可制造所暂存并检查（大阪府、神奈川县）[SRC-JP-GOV-OSAKA-COSME-IMPORT][SRC-JP-GOV-KANAGAWA-COSME]。从日本制造贩卖业者进货、原样销售者不需许可。
- 海外卖家通常须找日本制造贩卖业者作为「制造贩卖元」。个人输入的化妆品转售违法 [SRC-JP-GOV-MHLW-PERSONAL-IMPORT] [R:JP-L6-DRUG-001]。
- **宣称红线**：化妆品只能在「化妆品效能范围」内宣称；美白、育毛/防脱、祛痘、杀菌、止汗除臭、驱蚊等属医药部外品功效，须承认 [SRC-JP-GOV-EGOV-YAKKI][SRC-JP-GOV-MHLW-AD-RULES] [R:JP-L5-COSMETIC-003][R:JP-L5-QUASIDRUG-001]。

#### E.10 药品、个护健康电器、医疗器械

| 品类 | 法规要求 | 规则ID |
|---|---|---|
| 医药品（含 OTC、外用贴剂、眼药） | 销售须药局/医药品销售业许可，投放市场须制造贩卖业许可与承认；海外卖家不能取得 → 不可上架 | [R:JP-L5-DRUG-001] |
| 医疗器械（低周波治疗器、家用电气按摩器、温热治疗器、体温计、血压计、助听器等） | 制造贩卖业许可＋按等级取得承认（第23条の2の5）/认证（第23条の2の23）/届出（第23条の2の12） | [R:JP-L5-MEDDEV-001] |
| 销售管理医疗器械 | 营业所所在地保健所销售业届出 | [R:JP-L5-MEDDEV-002] |
| 隐形眼镜（含无度数美瞳）等高度管理医疗器械 | 销售业许可＋营业所管理者 | [R:JP-L5-MEDDEV-002] |
| 美容仪、按摩枪、护具等「健康杂货」 | 不宣称医疗功效即非医疗器械；宣称治疗/缓解疼痛/改善血流即违反第68条 | [R:JP-L5-PMDADS-001] |

来源：[SRC-JP-GOV-TOKYO-MEDDEV-RISK][SRC-JP-GOV-EGOV-YAKKI][SRC-JP-GOV-MHLW-AD-RULES]。药机法第66条虚假夸大广告的课征金为违法期间对价的 4.5%（不足 225 万日元不课）[R:JP-L5-PMDADS-002]。电气按摩器、家用温热治疗器、高频脱毛器、磁气治疗器同时出现在特定电气用品清单中，医疗器械品与杂货品的 PSE 适用关系待核实。

#### E.11 农药、杀虫驱虫、抗菌/消毒宣称

| 品类 | 法规 | 要求 | 规则ID |
|---|---|---|---|
| 农作物/园艺用杀虫、杀菌、除草剂 | 农药取缔法 | 须农林水产大臣登录；销售者只能卖有登录表示的农药 | [R:JP-L5-PESTICIDE-001] |
| 驱除蚊、蝇、蟑螂、跳蚤、螨等卫生害虫的产品 | 药机法（医药部外品/医药品） | 须制造贩卖承认；未承认不得宣称驱除卫生害虫 | [R:JP-L5-PESTICIDE-002][R:JP-L5-QUASIDRUG-001] |
| 人体消毒、杀菌 | 药机法 | 属医药品/医药部外品功效 | [R:JP-L5-COSMETIC-003] |
| 「抗菌」「除菌」等性能表述（杂货） | 景品表示法 | 须有试验依据（不实证广告规制） | [R:JP-L5-PREMIUMS-001] |

来源：[SRC-JP-GOV-EGOV-NOYAKU][SRC-JP-GOV-EGOV-YAKKI][SRC-JP-GOV-EGOV-KEIHYO]。

#### E.12 化学品、喷雾、易燃品

| 法规 | 要点 | 规则ID |
|---|---|---|
| 化审法第24条（L6） | 第一种特定化学物质使用制品禁止输入：PFOA/PFOS/PFHxS 拒水拒油处理面料/衣服/地毯、含 PFAS 灭火器与地板蜡；HBCD 阻燃面料/窗帘；デクロランプラス 电子部件；UV-328 胶带/涂料等 | [R:JP-L6-CHEM-001] |
| 有害物质含有家庭用品规制法 | 家用气雾剂：甲醇 ≤5%、氯乙烯不检出、四氯/三氯乙烯 ≤0.1%；液体洗净剂碱 ≤5% | [R:JP-L5-HARMFUL-004] |
| 毒物剧物取缔法 | 毒物剧物销售须登录 | [R:JP-L5-POISON-001] |
| 消防法 | 指定数量以上危险物须在许可设施贮藏 | [R:JP-L5-FIRESVC-001] |
| 高压气体保安法 | 气雾剂、卡式气罐、CO2 气瓶须满足适用除外条件与法定表示（细节待核实） | [R:JP-L5-HPGAS-001] |
| 火药类取缔法（L6） | 烟花等火药类输入须都道府县知事许可，否则税关禁止输入 | [R:JP-L6-FIREWORKS-001] |

来源：[SRC-JP-GOV-EGOV-KASHINHO][SRC-JP-GOV-EGOV-KASHINHO-REI][SRC-JP-GOV-EGOV-YUGAI-KISOKU][SRC-JP-GOV-EGOV-DOKUGEKI][SRC-JP-GOV-EGOV-SHOBO][SRC-JP-GOV-EGOV-KOATSU][SRC-JP-GOV-EGOV-KAYAKU]。

#### E.13 燃气器具与户外炉具（PSLPG / PSTG）

| 品类 | 标志 | 时间点 | 规则ID |
|---|---|---|---|
| 卡式炉、户外 LPG 喷灯 | 菱形 PSLPG（特定，登录检查机关检查） | — | [R:JP-L5-LPG-001] |
| 燃气喷枪（ガストーチ，直连卡式/户外气罐） | 菱形 PSLPG | 2025-02-06 起；过渡期 2026-02-06 结束 | [R:JP-L5-LPG-002] |
| 城市燃气器具 | PSTG（菱/圆） | — | [R:JP-L5-GAS-001] |
| 石油暖炉、石油热水器 | 圆形 PSC | — | [R:JP-L5-PSC-004] |

燃气喷枪除外：连接部到火口 35cm 以上、经软管连接气瓶、使用防漏吸收材气瓶的产品 [SRC-JP-GOV-METI-GASTORCH]。

#### E.14 刀具、武器、防身、开锁

| 品类 | 法规 | 结论 | 规则ID |
|---|---|---|---|
| 刀剑类：刃长 15cm 以上的刀/枪/薙刀，5.5cm 以上的剑/匕首，45° 以上自动开刃弹簧刀 | 銃刀法第2、3条 | 原则禁止持有 → 不可卖（登录美术刀剑除外） | [R:JP-L5-KNIFE-001] |
| 厨刀、折刀、工具刀等一般刃物 | 銃刀法第22条（6cm 超禁止携带）、轻犯罪法第1条第2号 | 可卖；文案不得宣传护身、随身携带 | [R:JP-L5-KNIFE-002] |
| 金属模造刀剑 | 銃刀法第22条の4 | 可卖，禁止携带 | [R:JP-L5-KNIFE-003] |
| 金属模造手枪 | 銃刀法第22条の2 | 禁止持有 → 不可卖 | [R:JP-L5-FIREARM-001] |
| 金属模拟枪器（带击发结构） | 銃刀法第22条の3 | 禁止以销售为目的持有 | [R:JP-L5-FIREARM-002] |
| 高威力气枪/软弹枪（准空气铳） | 銃刀法第21条の3 | 禁止持有；合法品须在基准值以下（0.98J 阈值待核实） | [R:JP-L5-FIREARM-003] |
| 真枪、空气枪、电磁石枪及部件 | 銃刀法第2、3条；关税法 | 须许可，不可在平台卖 | [R:JP-L5-FIREARM-004] |
| 十字弓 | 銃刀法第3条（2022-03-15 起） | 原则禁止持有（许可制） | [R:JP-L5-WEAPON-001] |
| 防狼喷雾、电击器 | 轻犯罪法 | 销售本身未见明文禁止（待核实），文案不得鼓励携带 | [R:JP-L5-DEFENSE-001] |
| 撬锁工具 | 特殊开锭用具所持禁止法第3条 | 无正当理由禁止持有 → 不可向消费者卖 | [R:JP-L5-LOCKPICK-001] |

来源：[SRC-JP-GOV-EGOV-JUTOHO][SRC-JP-GOV-KEISHICHO-HAMONO][SRC-JP-GOV-EGOV-KEIHAN][SRC-JP-GOV-EGOV-KAIJO][SRC-JP-GOV-NPA-CROSSBOW]（十字弓页面仅搜索摘要）。

#### E.15 激光产品

激光笔（以可见激光显示文字图形的携带用装置）是消安法**特别特定制品**，须登录检查机关检查、菱形 PSC [SRC-JP-GOV-EGOV-SHOUAN-REI][SRC-JP-GOV-METI-SHOUAN-MARK] [R:JP-L5-PSC-007]。输出功率上限（通行理解 1mW 未满）本次未核对解释通达。激光测距、激光雕刻等不属本品目。

#### E.16 无人机与航模

- 100g 以上（含电池）在屋外飞行的无人机/遥控航空器须由所有者在 DIPS2.0 登录、标示登录记号并搭载 Remote ID，未登录不得飞行（2022-06-20 起）[SRC-JP-GOV-MLIT-DRONE-PORTAL][SRC-JP-GOV-EGOV-KOKU] [R:JP-L5-DRONE-001]。
- 遥控与图传须技适或无线局免许 [R:JP-L5-RADIO-001][R:JP-L5-RADIO-006]。

#### E.17 个人代步工具

| 车辆 | 条件 | 要求 | 规则ID |
|---|---|---|---|
| 特定小型原动机付自转车（电动滑板车等） | 长 ≤190cm、宽 ≤60cm、额定 ≤0.6kW、最高 20km/h 且行驶中不能改速、最高速度显示灯 | 保安基准（性能等确认贴纸）、号牌、自赔责、16 岁以上免驾照 | [R:JP-L5-MOBILITY-001] |
| 超出上述条件的电动车 | — | 一般原付/汽车：驾照、号牌、保险、保安装置；不满足保安基准不能上路 | [R:JP-L5-MOBILITY-002] |
| 电动助力自行车 | 助力比基准（24km/h 以上停止助力） | 不符合即原付；可申请国家公安委员会型式认定 | [R:JP-L5-MOBILITY-003] |
| 带踏板的电动车（モペット） | 2024 年改正道交法：仅踩踏板也算驾驶原付 | 不得称「电动助力自行车」 | [R:JP-L5-MOBILITY-004] |

来源：[SRC-JP-GOV-NPA-TOKUTEI-KOGATA][SRC-JP-GOV-MLIT-TOKUTEI-KOGATA][SRC-JP-GOV-NPA-DENDO-KOKUSEN][SRC-JP-GOV-NPA-ASSIST-TYPE][SRC-JP-GOV-NPA-PEDAL-MOPED]。

#### E.18 汽配与头盔

摩托车/原付用头盔是消安法特定制品，须圆形 PSC（自行车头盔不在此列）[SRC-JP-GOV-EGOV-SHOUAN-REI] [R:JP-L5-PSC-001]。其他汽配（排放相关部件等）本次未调研。

#### E.19 家具、家纺、纺织服装、皮具

| 适用法规 | 要求 | 规则ID |
|---|---|---|
| 家庭用品品质表示法（纺织品） | 纤维组成、洗涤记号（JIS L 0001）、表示者名与联系方式 | [R:JP-L5-HOUSEHOLDLABEL-001] |
| 家庭用品品质表示法（杂货工业品） | 衣柜、桌、椅、特定床垫、皮革服装/手套、皮包、洋伞、鞋等按规程标示 | [R:JP-L5-HOUSEHOLDLABEL-003] |
| 有害物质规制法 | 24 个月以下婴幼儿纺织品甲醛（吸光度差 0.05 以下）；内衣/睡衣/袜子等 75μg/g；偶氮染料 24 种芳香胺 30μg/g；寝具/窗帘/地毯阻燃剂；有机锡、有机汞 | [R:JP-L5-HARMFUL-001][R:JP-L5-HARMFUL-002][R:JP-L5-HARMFUL-003] |
| 化审法（L6） | PFAS 拒水拒油处理衣服/面料/地毯、HBCD 阻燃窗帘禁止输入 | [R:JP-L6-CHEM-001] |

来源：[SRC-JP-GOV-CAA-HOUSEHOLD][SRC-JP-GOV-EGOV-KATEIYOHIN-REI][SRC-JP-GOV-EGOV-YUGAI-KISOKU][SRC-JP-GOV-EGOV-KASHINHO-REI]。日本对易倾倒家具没有类似美国 STURDY 的强制法（未见相关法规，未专门调研）。

#### E.20 宠物用品

- 观赏鱼加热器、气泵（AC）为菱形 PSE [R:JP-L5-PSE-002]。
- 含肉宠物食品/零食输入可能受家畜传染病预防法检疫 [R:JP-L6-ANIMAL-001]；宠物跳蚤驱除剂属动物用医药品（农水省所管，未调研）[R:JP-L5-PESTICIDE-002]。
- 外国动物追踪发信器无法在日本合法使用 [R:JP-L5-RADIO-002]；活体特定外来生物禁止销售 [R:JP-L5-ALIEN-001]。

#### E.21 植物种子、动物制品、濒危物种

| 品类 | 法规 | 要求 | 规则ID |
|---|---|---|---|
| 土、营养土、带土植物 | 植物防疫法第7条 | 禁止输入 | [R:JP-L6-PLANT-001] |
| 植物、种子、球根 | 植物防疫法第6条 | 输出国植物检疫证明书＋输入检查 | [R:JP-L6-PLANT-002] |
| 肉制品、骨、皮、毛、羽毛 | 家畜传染病预防法第36、37条 | 检查证明书＋动物检疫；部分产地禁止 | [R:JP-L6-ANIMAL-001] |
| CITES 对象物种制品（鳄鱼皮、蟒蛇皮、珊瑚、麝香、部分木材） | 外为法/CITES | 输出国 CITES 许可书；附属书 I 等须输入承认 | [R:JP-L6-CITES-001] |
| 象牙、玳瑁等希少种制品 | 种保存法 | 原则禁止转让；象牙事业须登录 | [R:JP-L5-SPECIES-001] |
| 特定外来生物活体 | 外来生物法 | 禁止转让 | [R:JP-L5-ALIEN-001] |

来源：[SRC-JP-GOV-EGOV-SHOKUBO][SRC-JP-GOV-EGOV-KADENHO][SRC-JP-GOV-METI-CITES][SRC-JP-GOV-EGOV-SHUNOHOZON][SRC-JP-GOV-EGOV-GAIRAI]。

#### E.22 烟草与电子烟

- 卷烟、加热式烟草烟棒等制造烟草零售须财务大臣许可 [SRC-JP-GOV-EGOV-TABAKO] [R:JP-L5-TOBACCO-001]。
- 含尼古丁电子烟液按医药品管理（通行解释，待核实），无尼古丁电子烟可售但不得宣称戒烟 [R:JP-L5-VAPE-001]。
- 加热式烟草设备 2026-04-01 起为资源有效利用促进法自主回收对象 [R:JP-L5-RECYCLE-002]；设备充电器须 PSE [R:JP-L5-PSE-002]。

#### E.23 酒类

- 酒类销售须酒类销售业免许，跨都道府县网络销售为通信贩卖酒类小売业免许；免许以日本国内销售场为单位 [SRC-JP-GOV-EGOV-SHUZEI] [R:JP-L5-ALCOHOL-001]。
- 容器须有品目等法定表示，遵守酒类表示基准（含未成年饮酒防止表示，告示原文待核实）[SRC-JP-GOV-EGOV-SHURUI-KUMIAI] [R:JP-L5-ALCOHOL-002]。

#### E.24 CBD 与大麻

- 大麻（THC 制品、大麻叶/花/树脂）属麻药，禁止输入与销售 [SRC-JP-GOV-EGOV-TAIMA][SRC-JP-GOV-EGOV-MAYAKU][SRC-JP-GOV-CUSTOMS-PROHIBITED] [R:JP-L6-CANNABIS-001]。
- CBD 制品以 Δ9-THC 残留限度值判断（通行理解：油脂/粉末 10ppm、水溶液 0.1ppm、其他 1ppm，**数值未在官方条文中确认**），须批次 COA [R:JP-L5-CANNABIS-002]。
- 「合法香草/浴盐」中的指定药物禁止输入 [R:JP-L6-CUSTOMS-004]。

#### E.25 成人用品

成人用品本身可售；但含无修正描写的影像、图片、包装可被认定为「有害风俗」物品而在税关被扣 [SRC-JP-GOV-CUSTOMS-PROHIBITED] [R:JP-L6-CUSTOMS-003]。宣称治疗勃起障碍等医疗功效违反药机法 [R:JP-L5-PMDADS-001]。

#### E.26 二手商品

- 以业务买卖二手品须古物商许可（公安委员会），网上销售须登记 URL [SRC-JP-GOV-EGOV-KOBUTSU] [R:JP-L5-USED-001]。
- 二手电器同样须有 PSE 标志 [R:JP-L5-PSE-004]；二手子供用特定制品有中古品特例 [R:JP-L5-PSC-016]。

#### E.27 监控与追踪设备

GPS 追踪器、隐藏摄像头本身可售，但未经同意获取他人位置信息属跟踪骚扰规制法对象；文案只能写防丢、看护等合法用途 [SRC-JP-GOV-EGOV-STALKER] [R:JP-L5-SURVEIL-001]。含 LTE/蓝牙的追踪器须技适 [R:JP-L5-RADIO-001]。

#### E.28 珠宝首饰

象牙、玳瑁、珊瑚、鳄鱼皮表带等涉及种保存法与 CITES [R:JP-L5-SPECIES-001][R:JP-L6-CITES-001]。贵金属纯度表示等未调研。

#### E.29 所有消费品共通

| 法规 | 要求 | 规则ID |
|---|---|---|
| 景品表示法 | 禁止优良误认/有利误认；被要求时须提交合理依据；课征金 3%（反复违反 4.5%）；2024-10-01 起确约手续等新制度 | [R:JP-L5-PREMIUMS-001] |
| 景品表示法（隐性营销） | 2023-10-01 起，隐藏广告性质的表示违法（含委托网红、伪装评论） | [R:JP-L5-PREMIUMS-002] |
| 特定商取引法 | 通信贩卖表示：卖家名称、住所、电话、负责人、价格运费、交付时期、退货条件 | [R:JP-L5-SCTA-001] |
| 特定商取引法第15条の3 | 未表示返品特约时，收货后 8 日内可退货 | [R:JP-L5-SCTA-002] |
| 消安法第35条 | 重大制品事故 10 日内向消费者厅报告 | [R:JP-L5-PSC-015] |
| 制造物责任法 | 输入者为「制造业者等」，承担无过失责任 | [R:JP-L5-PL-001] |

来源：[SRC-JP-GOV-EGOV-KEIHYO][SRC-JP-GOV-CAA-KEIHYO][SRC-JP-GOV-CAA-STEALTH][SRC-JP-GOV-CAA-TOKUSHO-MAILORDER][SRC-JP-GOV-EGOV-TOKUSHO][SRC-JP-GOV-EGOV-PL]。

#### E-L6 进口与清关

| 类别 | 内容 | 规则ID |
|---|---|---|
| 关税法第69条の11 禁止输入货物（13 类） | 麻药、向精神药、大麻、鸦片、兴奋剂及鸦片吸食具；指定药物；手枪、步枪等及弹药、手枪部件；爆炸物；火药类；化学武器原料；病原体；伪造货币/证券/卡（含模造品、生卡）；有害公安风俗的物品；儿童色情；知识产权侵权品；海外事业者寄给日本个人的商标/外观设计侵权品；不正竞争防止法违反物品 | [R:JP-L6-CUSTOMS-001][R:JP-L6-CUSTOMS-002][R:JP-L6-CUSTOMS-003] |
| 指定药物伪装品 | 「合法香草、香薰油、浴盐」 | [R:JP-L6-CUSTOMS-004] |
| 他法令确认 | 食品卫生法、植物防疫法、家畜传染病预防法、药机法、CITES、銃刀法等 | [R:JP-L6-CUSTOMS-005] |
| 食品/器具/乳幼儿玩具 | 每次输入届出 | [R:JP-L6-FOOD-001][R:JP-L6-FOODCONTACT-001][R:JP-L6-TOYFOOD-001] |
| 药机法对象品 | 营业用输入证明；个人输入品不得转售 | [R:JP-L6-DRUG-001] |
| 化审法 | 第一种特定化学物质使用制品禁止输入 | [R:JP-L6-CHEM-001] |
| 火药类 | 须知事许可 | [R:JP-L6-FIREWORKS-001] |
| 动植物 | 土禁止；植物/肉制品须检疫证明 | [R:JP-L6-PLANT-001][R:JP-L6-PLANT-002][R:JP-L6-ANIMAL-001] |
| CITES | 输出许可书/输入承认 | [R:JP-L6-CITES-001] |

来源：[SRC-JP-GOV-CUSTOMS-PROHIBITED][SRC-JP-GOV-EGOV-KANZEI]。

---

### F. 标签、语言与本地责任人（法规部分）

**日本没有「所有商品都必须有日文标签」的通用法律**，日文表示义务分散在各法：

| 法律 | 必须用日文/法定表示的内容 | 谁负责 | 规则ID |
|---|---|---|---|
| 电安法 | PSE 标志、届出事业者名（可用承认略称/登录商标）、额定值；移动电源按 J 规格标示 | 届出事业者（海外卖家作为特定输入事业者时为其本人名称） | [R:JP-L5-PSE-001][R:JP-L5-PSE-003] |
| 消安法 | PSC/子供 PSC、届出事业者名；子供用特定制品的对象年龄与警示**必须日文** | 届出事业者 | [R:JP-L5-PSC-010] |
| 电波法 | 技适标志与编号（无语言要求） | 认证取得者 | [R:JP-L5-RADIO-001] |
| 药机法 | 化妆品/医药部外品/医疗器械直接容器的法定表示 | 日本制造贩卖业者 | [R:JP-L5-COSMETIC-002] |
| 家庭用品品质表示法 | 纤维组成、洗涤记号、树脂种类、耐热温度、消费电力等＋表示者名与地址/电话 | 制造/销售/表示事业者 | [R:JP-L5-HOUSEHOLDLABEL-001]～[R:JP-L5-HOUSEHOLDLABEL-003] |
| 酒类业组合法 | 酒类品目等表示、表示基准 | 酒类制造/销售业者 | [R:JP-L5-ALCOHOL-002] |
| 特定商取引法 | 网店上的经营者表示（名称、住所、电话、负责人、退货条件） | 卖家 | [R:JP-L5-SCTA-001] |

**本地责任人一览**

| 角色 | 何时需要 | 依据 |
|---|---|---|
| 国内管理人（国内管理人） | 海外卖家销售 PSE/PSC/PSTG/PSLPG 对象产品 | 电安法第3条等 [R:JP-L5-PSIMPORT-001] |
| 化妆品/医药部外品/医疗器械制造贩卖业者（製造販売業者） | 化妆品、医药部外品、医疗器械投放市场 | 药机法第12条、第23条の2 [R:JP-L5-COSMETIC-001][R:JP-L5-MEDDEV-001] |
| 食品等输入者 | 食品、器具、容器包装、乳幼儿玩具输入 | 食品卫生法第27条 [R:JP-L6-FOOD-001] |
| 酒类销售业免许持有者 | 酒类销售 | 酒税法第9条 [R:JP-L5-ALCOHOL-001] |
| 古物商许可持有者 | 二手品买卖 | 古物营业法第3条 [R:JP-L5-USED-001] |
| 医疗器械销售业（届出/许可） | 管理/高度管理医疗器械销售 | 药机法第39条、第39条の3 [R:JP-L5-MEDDEV-002] |

---

### G. 2024–2026 法规变化与生效日期

| 日期 | 变化 | 影响的产品 | 规则ID | 来源 |
|---|---|---|---|---|
| 2022-03-15 | 十字弓原则禁止持有（许可制） | 十字弓 | JP-L5-WEAPON-001 | SRC-JP-GOV-NPA-CROSSBOW（摘要）、SRC-JP-GOV-EGOV-JUTOHO |
| 2022-06-20 | 100g 以上无人机登录制度施行（Remote ID） | 无人机、航模 | JP-L5-DRONE-001 | SRC-JP-GOV-MLIT-DRONE-PORTAL |
| 2023-07-01 | 特定小型原动机付自转车制度施行 | 电动滑板车 | JP-L5-MOBILITY-001 | SRC-JP-GOV-NPA-TOKUTEI-KOGATA |
| 2023-10-01 | 隐性营销纳入景品表示法 | 全部 | JP-L5-PREMIUMS-002 | SRC-JP-GOV-CAA-STEALTH |
| 2023-12-19 | 磁铁娱乐用品、吸水树脂玩具成为 PSC 特定制品（本施行） | 磁力珠、水宝宝 | JP-L5-PSC-005、JP-L5-PSC-006 | SRC-JP-GOV-METI-SHOUAN-MARK |
| 2024-04-01 | 食品卫生基准行政由厚劳省移交消费者厅 | 食品接触材料、玩具 | JP-L5-FOODCONTACT-001 | SRC-JP-GOV-MHLW-KIGU |
| 2024-05-24 公布 | 改正道交法：带踏板原付仅踩踏板也算驾驶（6 个月内施行） | 电动自行车/モペット | JP-L5-MOBILITY-004 | SRC-JP-GOV-NPA-PEDAL-MOPED |
| 2024-06-26 公布 | 改正制品安全 4 法公布（2025-12-25 施行） | PS 对象全部 | JP-L5-PSIMPORT-001 | SRC-JP-GOV-METI-TOKUTEIYUNYU-2604 |
| 2024-10-01 | 改正景品表示法施行（确约手续、课征金加重等） | 全部 | JP-L5-PREMIUMS-001 | SRC-JP-GOV-CAA-KEIHYO |
| 2024-12-12（日期待核实） | 大麻改正：大麻列为麻药、以 THC 限度值判断 CBD 制品 | CBD、大麻 | JP-L6-CANNABIS-001、JP-L5-CANNABIS-002 | SRC-JP-GOV-EGOV-TAIMA、SRC-JP-GOV-EGOV-MAYAKU |
| 2025-02-06 | 燃气喷枪须菱形 PSLPG（1 年过渡） | 燃气喷枪 | JP-L5-LPG-002 | SRC-JP-GOV-METI-GASTORCH |
| 2025-06-01 | 食品接触合成树脂正面清单全面适用（经过措置 5-31 满了） | 塑料/树脂餐厨具 | JP-L5-FOODCONTACT-002 | SRC-JP-GOV-CAA-KIGU-PL |
| 2025-12-25 | 海外卖家为「特定输入事业者」，须届出与国内管理人；平台删除要请、届出公表、违法者公表 | PS 对象全部 | JP-L5-PSIMPORT-001～004 | SRC-JP-GOV-METI-TOKUTEIYUNYU |
| 2025-12-25 | 乳幼儿用玩具（3 岁以下）子供 PSC 施行；婴儿床指定为子供用特定制品 | 3 岁以下玩具、婴儿床 | JP-L5-PSC-010、JP-L5-PSC-011 | SRC-JP-GOV-METI-GANGU-KISEI、SRC-JP-GOV-METI-PS-GUIDE |
| 2026-02-06 | 燃气喷枪过渡期结束 | 燃气喷枪 | JP-L5-LPG-002 | SRC-JP-GOV-METI-GASTORCH |
| 2026-04-01 | 改正资源有效利用促进法施行：一体型移动电源、智能手机、加热式烟草设备追加为自主回收对象 | 移动电源等 | JP-L5-RECYCLE-002 | SRC-JP-GOV-METI-RECYCLE-2604 |
| 2026-04-01 | 液石法运用解释与技术基准运用改正 | LPG 器具 | JP-L5-LPG-001 | SRC-JP-GOV-METI-EKISEKI |
| 2026-04-27 | 床护栏、婴儿车技术基准省令改正（2026-04 草案定稿） | 床护栏、婴儿车 | JP-L5-PSC-013、JP-L5-PSC-014 | SRC-JP-GOV-METI-SHOUAN-INDEX、SRC-JP-GOV-METI-BEDGUARD-STROLLER |
| 2026-07-08 | 床护栏、婴儿车子供 PSC 规制开始 | 床护栏、婴儿车 | JP-L5-PSC-013、JP-L5-PSC-014 | SRC-JP-GOV-METI-BEDGUARD-STROLLER |
| **2027-03-25** | 婴儿床旧标志品禁止销售 | 婴儿床 | JP-L5-PSC-012 | SRC-JP-GOV-METI-PS-GUIDE |
| **2027-07-07** | 床护栏过渡期结束 | 床护栏 | JP-L5-PSC-013 | SRC-JP-GOV-METI-BEDGUARD-STROLLER |
| **2028-07-07** | 婴儿车过渡期结束 | 婴儿车 | JP-L5-PSC-014 | SRC-JP-GOV-METI-BEDGUARD-STROLLER |

### H. 来源清单

共 91 个来源，全部为 S2（政府官方）；其中 1 个仅见搜索摘要（SRC-JP-GOV-NPA-CROSSBOW，直接访问 403）。快照路径见 `rules/sources/JP_regulation.yaml` 的 snapshot 字段。

| 来源ID | 标题 | URL | 级别 | 访问日期 | 获取方式 |
|---|---|---|---|---|---|
| SRC-JP-GOV-METI-TOKUTEIYUNYU | 海外事業者が製品安全４法の規制対象となりました（特定輸入事業者特設ページ，最終更新 2025-12-18） | https://www.meti.go.jp/product_safety/tokuteiyunyu/tokuteiyunyu.html | S2 | 2026-10-10 | jina_reader |
| SRC-JP-GOV-METI-TOKUTEIYUNYU-2604 | 消費生活用製品安全法等の一部を改正する法律の概要（海外事業者の規制対象化）令和8年4月版 | https://www.meti.go.jp/policy/consumer/seian/shouan/contents/tokuteiyunyu_kaisei_Japanese.pdf | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-METI-HANREISHU | 輸入事業者の明確化のための凡例集（令和7年12月19日） | https://www.meti.go.jp/product_safety/consumer/pdf/hanreishu.pdf | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-METI-4LAW-FAQ | 製品安全4法改正に関するFAQ（2025-12-09 改訂版） | https://www.meti.go.jp/policy/consumer/seian/shouan/contents/gangu_faq_2.pdf | S2 | 2026-10-10 | jina_reader |
| SRC-JP-GOV-METI-PS-GUIDE | 製品安全ガイド（最終更新 2026-08-31） | https://www.meti.go.jp/product_safety/ | S2 | 2026-10-10 | jina_reader |
| SRC-JP-GOV-EGOV-DENAN | 電気用品安全法（条文，e-Gov 法令検索） | https://laws.e-gov.go.jp/law/336AC0000000234 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-METI-DENAN-OUTLINE | 電気用品安全法の概要 | https://www.meti.go.jp/policy/consumer/seian/denan/act_outline.html | S2 | 2026-10-10 | jina_reader |
| SRC-JP-GOV-METI-DENAN-SPECIFIED | 特定電気用品（116品目）一覧 | https://www.meti.go.jp/policy/consumer/seian/denan/specified_electrical.html | S2 | 2026-10-10 | jina_reader |
| SRC-JP-GOV-METI-DENAN-NONSPECIFIED | 特定電気用品以外の電気用品（341品目）一覧 | https://www.meti.go.jp/policy/consumer/seian/denan/non_specified_electrical.html | S2 | 2026-10-10 | jina_reader |
| SRC-JP-GOV-METI-DENAN-MLB-FAQ | モバイルバッテリーに関するFAQ（電気用品安全法） | https://www.meti.go.jp/policy/consumer/seian/denan/mlb_faq.html | S2 | 2026-10-10 | jina_reader |
| SRC-JP-GOV-METI-DENAN-PORTABLE-LI | ポータブルリチウムイオン蓄電池の対象非対象について（令和元年10月11日） | https://www.meti.go.jp/policy/consumer/seian/denan/file/97_faq/Portable_lithium_ion_chikudenchi.pdf | S2 | 2026-10-10 | jina_reader |
| SRC-JP-GOV-METI-DENAN-KAIGAI-2018 | 海外事業者による届出事業者届出の可否について（平成30年10月3日，改正前の解释） | https://www.meti.go.jp/policy/consumer/seian/denan/file/97_faq/Kaigai_jigyousya_no_todokede_ni_tsuite_kai.pdf | S2 | 2026-10-10 | jina_reader |
| SRC-JP-GOV-METI-DENAN-SELLER-GUIDE | 電気用品安全法の概要と販売事業者の留意点について（中国販売者向け電安法セミナー，令和5年11月1日） | https://www.meti.go.jp/policy/consumer/seian/denan/file/06_guide/seller_guide01.pdf | S2 | 2026-10-10 | jina_reader |
| SRC-JP-GOV-EGOV-SHOUAN | 消費生活用製品安全法（条文） | https://laws.e-gov.go.jp/law/348AC0000000031 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-SHOUAN-REI | 消費生活用製品安全法施行令（別表第一：特定製品 15 品目） | https://laws.e-gov.go.jp/law/349CO0000000048 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-METI-SHOUAN-INDEX | 消費生活用製品安全法（最終更新 2026-05-27） | https://www.meti.go.jp/policy/consumer/seian/shouan/index.html | S2 | 2026-10-10 | jina_reader |
| SRC-JP-GOV-METI-SHOUAN-MARK | 消費生活用製品安全法～特定製品とマークの変遷 | https://www.meti.go.jp/policy/consumer/seian/shouan/contents/mark.htm | S2 | 2026-10-10 | jina_reader |
| SRC-JP-GOV-METI-GANGU-KISEI | 乳幼児用玩具に対して新しい規制が導入されました（最終更新 2026-06-15） | https://www.meti.go.jp/product_safety/kodomo/gangu_kisei.html | S2 | 2026-10-10 | jina_reader |
| SRC-JP-GOV-METI-BEDGUARD-STROLLER | 乳幼児用ベッドガード、ベビーカーに対して新しい規制が導入されました（最終更新 2026-06-26） | https://www.meti.go.jp/product_safety/kodomo/bedguardstroller.html | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-METI-GASTORCH | ガストーチに対する規制が開始されました（最終更新 2026-02-27） | https://www.meti.go.jp/product_safety/consumer/gastorch.html | S2 | 2026-10-10 | jina_reader |
| SRC-JP-GOV-METI-EKISEKI | 液化石油ガスの保安の確保及び取引の適正化に関する法律（製品安全ページ） | https://www.meti.go.jp/policy/consumer/seian/ekiseki/index.html | S2 | 2026-10-10 | jina_reader |
| SRC-JP-GOV-EGOV-EKISEKI | 液化石油ガスの保安の確保及び取引の適正化に関する法律（条文） | https://laws.e-gov.go.jp/law/342AC0000000149 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-METI-GASJI | ガス事業法（ガス用品，製品安全ページ） | https://www.meti.go.jp/policy/consumer/seian/gasji/index.html | S2 | 2026-10-10 | jina_reader |
| SRC-JP-GOV-EGOV-GASJI | ガス事業法（条文） | https://laws.e-gov.go.jp/law/329AC0000000051 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-SHIGEN-REI | 資源の有効な利用の促進に関する法律施行令（別表第八 等） | https://laws.e-gov.go.jp/law/403CO0000000327 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-METI-RECYCLE-2604 | 改正資源有効利用促進法等の施行について（産構審 資源循環経済小委員会 資料3，令和8年4月） | https://www.meti.go.jp/shingikai/sankoshin/sangyo_gijutsu/resource_circulation/pdf/013_03_00.pdf | S2 | 2026-10-10 | jina_reader |
| SRC-JP-GOV-METI-BATTERY-RECYCLE | 小型二次電池のリサイクル（資源有効利用促進法） | https://www.meti.go.jp/policy/it_policy/kaden/index03.html | S2 | 2026-10-10 | jina_reader |
| SRC-JP-GOV-EGOV-KADEN-RECYCLE | 特定家庭用機器再商品化法（家電リサイクル法，条文） | https://laws.e-gov.go.jp/law/410AC0000000097 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-SOUMU-GITEKI-QA | 技適マークのＱ＆Ａ（電波利用ポータル） | https://www.tele.soumu.go.jp/j/adm/monitoring/summary/qa/giteki_mark/ | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-SOUMU-GITEKI-MARK | 技適マークの表示の方法（電波利用ポータル） | https://www.tele.soumu.go.jp/j/sys/equ/tech/gitekimark/index.htm | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-SOUMU-DRONE-RADIO | ドローン等に用いられる無線設備について（電波利用ポータル） | https://www.tele.soumu.go.jp/j/sys/others/drone/ | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-SOUMU-SHIBAI-R6 | 令和6年度無線設備試買テスト中間報告（第1次）の公表 | https://www.soumu.go.jp/menu_news/s-news/01kiban17_02000056.html | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-DENPA | 電波法（条文：第4条、第38条の7、第102条の11、第110条等） | https://laws.e-gov.go.jp/law/325AC0000000131 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-MLIT-DRONE-PORTAL | 無人航空機登録ポータルサイト | https://www.mlit.go.jp/koku/drone/ | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-MLIT-DRONE-REG | 航空：無人航空機の登録制度 | https://www.mlit.go.jp/koku/koku_ua_registration.html | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-KOKU | 航空法（条文：第2条第22項、第132条の2〜第132条の5 等） | https://laws.e-gov.go.jp/law/327AC0000000231 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-NPA-TOKUTEI-KOGATA | 特定小型原動機付自転車に関する交通ルール等について | https://www.npa.go.jp/bureau/traffic/anzen/tokuteikogata.html | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-MLIT-TOKUTEI-KOGATA | 特定小型原動機付自転車について（性能等確認制度） | https://www.mlit.go.jp/jidosha/jidosha_fr7_000058.html | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-NPA-DENDO-KOKUSEN | 道路交通法の基準に適合しない「電動アシスト自転車」と称する製品について（平成29年6月29日広報資料） | https://www.npa.go.jp/bureau/traffic/bicycle/pdf/dendokokusen.pdf | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-NPA-ASSIST-TYPE | 人の力を補うため原動機を用いる自転車の型式認定（手続案内） | https://www.npa.go.jp/policies/application/form/17/27.html | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-NPA-PEDAL-MOPED | 改正道路交通法の概要等（ペダル付き原動機付自転車に関する規定の整備）令和6年6月27日 | https://www.npa.go.jp/bureau/traffic/council/newmobility0803.pdf | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-SHOKUEI | 食品衛生法（条文：第18条、第27条、第68条 等） | https://laws.e-gov.go.jp/law/322AC0000000233 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-CAA-KIGU-PL | 食品用器具・容器包装のポジティブリスト制度について（2025年6月1日以降） | https://www.caa.go.jp/policies/policy/standards_evaluation/appliance/positive_list_new/ | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-CAA-APPLIANCE | 器具・容器包装、おもちゃ、洗浄剤（消費者庁） | https://www.caa.go.jp/policies/policy/standards_evaluation/appliance/ | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-CAA-TOY-QA | 指定おもちゃの範囲等に関するＱ＆Ａについて（平成21年9月14日 食安基発0914第2号） | https://www.caa.go.jp/policies/policy/standards_evaluation/appliance/assets/20090914-1_1.pdf | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-MHLW-KIGU | 器具・容器包装、おもちゃ、洗浄剤に関する情報（2024-04-01 起食品卫生基准行政移交消费者厅） | https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/shokuhin/kigu/index.html | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-MHLW-FOOD-IMPORT | 食品等輸入手続について（検疫所への輸入届出） | https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000144562.html | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-YAKKI | 医薬品、医療機器等の品質、有効性及び安全性の確保等に関する法律（薬機法，条文） | https://laws.e-gov.go.jp/law/335AC0000000145 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-MHLW-AD-RULES | 医薬品等の広告規制について | https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/iyakuhin/koukokukisei/index.html | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-MHLW-PERSONAL-IMPORT | 医薬品等を海外から購入しようとされる方へ（個人輸入） | https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/iyakuhin/kojinyunyu/index.html | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-MHLW-COSME-QD | 化粧品・医薬部外品等ホームページ | https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/iyakuhin/keshouhin/index.html | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-OSAKA-COSME-IMPORT | 化粧品を輸入して販売するには許可が必要ですか。（大阪府 FAQ） | https://www.pref.osaka.lg.jp/faq/faq_002047.html | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-KANAGAWA-COSME | 化粧品の製造、輸入または製造販売等について（神奈川県） | https://www.pref.kanagawa.jp/docs/n3x/yakumu/kyoninka/kesyohin.html | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-TOKYO-MEDDEV-RISK | 医療機器のリスク分類と販売業・貸与業の許可・届出（東京都保健医療局） | https://www.hokeniryo.metro.tokyo.lg.jp/anzen/iyaku/sonota/sale_leas/risk.html | S2 | 2026-10-10 | jina_reader |
| SRC-JP-GOV-CAA-HOUSEHOLD | 家庭用品品質表示法（消費者庁） | https://www.caa.go.jp/policies/policy/representation/household_goods/ | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-KATEIYOHIN | 家庭用品品質表示法（条文） | https://laws.e-gov.go.jp/law/337AC0000000104 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-KATEIYOHIN-REI | 家庭用品品質表示法施行令（別表：繊維製品・合成樹脂加工品・電気機械器具・雑貨工業品） | https://laws.e-gov.go.jp/law/337CO0000000390 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-YUGAI | 有害物質を含有する家庭用品の規制に関する法律（条文） | https://laws.e-gov.go.jp/law/348AC0000000112 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-YUGAI-KISOKU | 有害物質を含有する家庭用品の規制に関する法律施行規則（別表第1：有害物質・対象家庭用品・基準） | https://laws.e-gov.go.jp/law/349M50000100034 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-CAA-KEIHYO | 景品表示法（消費者庁） | https://www.caa.go.jp/policies/policy/representation/fair_labeling/ | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-CAA-STEALTH | 令和5年10月1日からステルスマーケティングは景品表示法違反となります。 | https://www.caa.go.jp/policies/policy/representation/fair_labeling/stealth_marketing/ | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-KEIHYO | 不当景品類及び不当表示防止法（条文：第5条、第7条、第8条） | https://laws.e-gov.go.jp/law/337AC0000000134 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-CAA-TOKUSHO-MAILORDER | 通信販売｜特定商取引法ガイド | https://www.no-trouble.caa.go.jp/what/mailorder/ | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-TOKUSHO | 特定商取引に関する法律（条文：第11条、第15条の3 等） | https://laws.e-gov.go.jp/law/351AC0000000057 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-PL | 製造物責任法（条文） | https://laws.e-gov.go.jp/law/406AC0000000085 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-JUTOHO | 銃砲刀剣類所持等取締法（銃刀法，条文：第2条、第3条、第21条の3、第22条〜第22条の4） | https://laws.e-gov.go.jp/law/333AC0000000006 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-KEISHICHO-HAMONO | 刃物の話（警視庁） | https://www.keishicho.metro.tokyo.lg.jp/kurashi/drug/hamono/hamono.html | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-KEIHAN | 軽犯罪法（条文：第1条） | https://laws.e-gov.go.jp/law/323AC0000000039 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-NPA-CROSSBOW | クロスボウの所持が禁止されます！（警察庁，直接访问 403，仅见搜索摘要） | https://www.npa.go.jp/bureau/safetylife/hoan/crossbow/ | S2 | 2026-10-10 | search_snippet |
| SRC-JP-GOV-EGOV-KAIJO | 特殊開錠用具の所持の禁止等に関する法律（ピッキング防止法，条文） | https://laws.e-gov.go.jp/law/415AC0000000065 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-SHUZEI | 酒税法（条文：第9条 酒類の販売業免許） | https://laws.e-gov.go.jp/law/328AC0000000006 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-SHURUI-KUMIAI | 酒税の保全及び酒類業組合等に関する法律（第86条の5、第86条の6 表示） | https://laws.e-gov.go.jp/law/328AC0000000007 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-TABAKO | たばこ事業法（条文：第22条 製造たばこの小売販売業の許可） | https://laws.e-gov.go.jp/law/359AC0000000068 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-KOBUTSU | 古物営業法（条文：第2条、第3条、第5条） | https://laws.e-gov.go.jp/law/324AC0000000108 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-KASHINHO | 化学物質の審査及び製造等の規制に関する法律（化審法，第24条 輸入の制限） | https://laws.e-gov.go.jp/law/348AC0000000117 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-KASHINHO-REI | 化学物質の審査及び製造等の規制に関する法律施行令（第1条 第一種特定化学物質、第7条 輸入禁止製品） | https://laws.e-gov.go.jp/law/349CO0000000202 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-NOYAKU | 農薬取締法（条文：第3条、第18条、第24条） | https://laws.e-gov.go.jp/law/323AC0000000082 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-DOKUGEKI | 毒物及び劇物取締法（条文：第3条） | https://laws.e-gov.go.jp/law/325AC0000000303 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-SHOBO | 消防法（条文：第10条 危険物の貯蔵・取扱い） | https://laws.e-gov.go.jp/law/323AC1000000186 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-KOATSU | 高圧ガス保安法（条文） | https://laws.e-gov.go.jp/law/326AC0000000204 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-KAYAKU | 火薬類取締法（条文：第24条 輸入） | https://laws.e-gov.go.jp/law/325AC0000000149 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-SHOKUBO | 植物防疫法（条文：第6条 輸入の制限、第7条 輸入の禁止） | https://laws.e-gov.go.jp/law/325AC0000000151 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-KADENHO | 家畜伝染病予防法（条文：第36条 輸入禁止、第37条 検査証明書） | https://laws.e-gov.go.jp/law/326AC1000000166 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-GAIRAI | 特定外来生物による生態系等に係る被害の防止に関する法律（外来生物法，第4条、第8条） | https://laws.e-gov.go.jp/law/416AC0000000078 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-SHUNOHOZON | 絶滅のおそれのある野生動植物の種の保存に関する法律（種の保存法，第12条、第33条の6） | https://laws.e-gov.go.jp/law/404AC0000000075 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-METI-CITES | ワシントン条約（CITES）（経済産業省 野生動植物貿易審査室） | https://www.meti.go.jp/policy/external_economy/trade_control/02_exandim/06_washington/index.html | S2 | 2026-10-10 | jina_reader |
| SRC-JP-GOV-CUSTOMS-PROHIBITED | 輸出入禁止・規制品目（税関） | https://www.customs.go.jp/mizugiwa/kinshi.htm | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-KANZEI | 関税法（条文：第69条の11 輸入してはならない貨物） | https://laws.e-gov.go.jp/law/329AC0000000061 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-TAIMA | 大麻草の栽培の規制に関する法律（旧 大麻取締法，第2条 定義） | https://laws.e-gov.go.jp/law/323AC0000000124 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-MAYAKU | 麻薬及び向精神薬取締法（第2条：大麻を麻薬として定義） | https://laws.e-gov.go.jp/law/328AC0000000014 | S2 | 2026-10-10 | webfetch |
| SRC-JP-GOV-EGOV-STALKER | ストーカー行為等の規制等に関する法律（第2条：位置情報記録・送信装置） | https://laws.e-gov.go.jp/law/412AC0100000081 | S2 | 2026-10-10 | webfetch |

另：亚马逊页面（S1）在本文仅作对照引用，未登记到本文件来源清单：GHJPQ6KDLA9N5F4L「電気用品安全法（PSE）」、GJXRBNGX52EMJZZB「海外出品者向け製品安全4法法令遵守ガイド」（快照在 `policy/snapshots/JP/`，由平台层登记来源 ID）。

### 待核实/冲突

**冲突**

1. **亚马逊 PSE 页与新法矛盾**：GHJPQ6KDLA9N5F4L 正文「2024 年时点海外事业者不能届出」vs 电安法第3条第2号（2025-12-25 施行，海外事业者可作为特定输入事业者届出）。本文按新法处理 [R:JP-L5-PSIMPORT-004]；建议平台层在规则中注明该句过时，并核实亚马逊审核实际接受「海外卖家本人＋国内管理人」的届出书（GJXRBNGX52EMJZZB 显示接受）。
2. **海外卖家的届出渠道**：METI 特设页称海外事业者不能用保安ネット（需法人番号）；亚马逊指南引用 METI 称「暂以电子邮件直接届出，计划 2025-12 起开放 e-Gov 电子申请」。e-Gov 渠道目前是否已开放未确认。

**待核实（本次未能在官方原文中确认，或只确认了部分）**

3. 特定输入事业者以外的义务是否同样落到海外卖家：消安法重大事故 10 日报告 [R:JP-L5-PSC-015]、资源有效利用促进法自主回收 [R:JP-L5-RECYCLE-001][R:JP-L5-RECYCLE-002]、家电回收法零售业者回收义务 [R:JP-L5-RECYCLE-003]。
4. USB/直流供电小电器本体不属电气用品——未打开 METI「対象・非対象一覧」(subject.html) [R:JP-L5-PSE-006]。
5. 医疗器械与电安法重叠：电气按摩器、家用温热治疗器、高频脱毛器、磁气治疗器既在特定电气用品清单中，又可能是管理医疗器械；医疗器械品是否仍需 PSE 未确认。
6. 激光笔技术基准的输出上限（通行理解 1mW 未满、JIS C 6802 クラス2 以下）未打开解释通达 [R:JP-L5-PSC-007]。
7. 电子点烟器（电弧打火机）是否属 PSC「打火机」；电气压力锅是否同时属 PSC 压力锅 [R:JP-L5-PSC-008][R:JP-L5-PSC-002]。
8. 子供用特定制品中古品特例的具体条件（FAQ 第 14 章未逐条阅读）[R:JP-L5-PSC-016]。
9. 资源有效利用促进法命令违反的罚金额（二手资料称 50 万日元以下）未在官方资料确认 [R:JP-L5-RECYCLE-002]。
10. 准空气铳动能阈值（3.5J/cm²，6mm BB 约 0.98J）、合法模型枪的形态要求（内阁府令）未打开原文 [R:JP-L5-FIREARM-001][R:JP-L5-FIREARM-003]。
11. 双刃匕首（ダガー）按「剑」处理的解释；甩棍、指虎、防狼喷雾、电击器在日本销售的合法性 [R:JP-L5-KNIFE-001][R:JP-L5-DEFENSE-001]。
12. 十字弓：施行日 2022-03-15 与 6.0J 阈值只见警察厅页面搜索摘要（直接访问 403）[R:JP-L5-WEAPON-001]。
13. 高压气体保安法下气雾剂适用除外条件（内容积、压力）与法定警示文字 [R:JP-L5-HPGAS-001]。
14. CBD：Δ9-THC 残留限度值（油脂/粉末 10ppm、水溶液 0.1ppm、其他 1ppm）与改正施行日 2024-12-12 均未在本次取得的条文中定位 [R:JP-L5-CANNABIS-002][R:JP-L6-CANNABIS-001]。
15. 含尼古丁电子烟液属医药品——未打开厚劳省专门页面 [R:JP-L5-VAPE-001]。
16. 酒类：通信贩卖酒类小売业免许可售国产酒的范围（年课税移出量 3,000kl 未满酿造者等）、「20 歳未满饮酒禁止」表示告示原文；海外卖家无法取得免许系推导 [R:JP-L5-ALCOHOL-001][R:JP-L5-ALCOHOL-002]。
17. 古物营业法：仅销售自用品、或从海外采购二手品再销售时是否需许可；无日本营业所的海外卖家如何适用 [R:JP-L5-USED-001]。
18. 化审法新追加物质（UV-328、デクロランプラス 等）的输入禁止施行日 [R:JP-L6-CHEM-001]。
19. 化妆品效能范围（56 项）清单与全成分表示告示原文 [R:JP-L5-COSMETIC-003][R:JP-L5-COSMETIC-002]。
20. 食品：46 通知（「专ら医药品」原料清单）、机能性表示食品/特定保健用食品、食品表示法日文标签——本次未调研。
21. 指定玩具规格中邻苯类可塑剂的具体物质与限值、皮革制品的有害物质对象范围 [R:JP-L5-TOYFOOD-001][R:JP-L5-HARMFUL-002]。
22. 合成树脂正面清单是否涵盖硅胶（橡胶不在内）[R:JP-L5-FOODCONTACT-002]。
23. 外来生物法「条件付特定外来生物」（红耳龟、美国螯虾，2023-06-01）未在条文摘录确认 [R:JP-L5-ALIEN-001]。
24. 带踏板电动车改正道交法的施行日；电动平衡车/独轮车能否作为特定小型原付取得性能等确认 [R:JP-L5-MOBILITY-004][R:JP-L5-MOBILITY-002]。
25. 家庭用品品质表示法：鞋、包、床垫等限内阁府令所定素材/种类，各表示规程未逐一打开 [R:JP-L5-HOUSEHOLDLABEL-003]。
26. 植物防疫：椰糠、泥炭是否视为「土」；干花、木制品免检范围。动物检疫：羽绒成品、皮革成品是否须检疫 [R:JP-L6-PLANT-001][R:JP-L6-ANIMAL-001]。
27. 药机法课征金制度施行日（2021-08-01）、景表法合理依据提交期限（15 日）、特商法 8 日退货期以外的细节 [R:JP-L5-PMDADS-002][R:JP-L5-PREMIUMS-001]。
28. 刑法第175条（猥亵物）、性的姿態撮影等処罰法（偷拍）、小型无人机等飞行禁止法未打开条文 [R:JP-L6-CUSTOMS-003][R:JP-L5-SURVEIL-001][R:JP-L5-DRONE-001]。
29. 燃气事业法、液石法各品目的特定/特定以外归属只依据 METI 2026-04 概要资料的计数与例示，未逐条核对施行令别表 [R:JP-L5-LPG-001][R:JP-L5-GAS-001]。
30. 汽配（排放部件等）、贵金属纯度表示、玩具烟花国内销售检查（SF 标志）、动物用医药品（宠物驱虫）未调研。
31. 调研后段 WebSearch 配额用尽，以上部分事项无法再检索，只能依据 e-Gov 条文与已抓取页面。
