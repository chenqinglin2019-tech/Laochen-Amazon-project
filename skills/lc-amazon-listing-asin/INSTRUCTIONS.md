# Laochen — Amazon Listing 生成 Skill 核心指令

> 本文件是平台无关的核心指令。无论你在 Claude Code、Codex 还是其他 agent 环境，
> 读完本文件就能完整执行任务。

---

## 后端配置

读取 `config.json` 获取后端地址、token 和默认站点。

交付给用户的 skill 包里，`backend_token` 可能被留空。调用 `expand` / `qa` / `validate` 前必须先检查：
- 如果 `backend_token` 有值：按下方方式设置环境变量后继续。
- 如果 `backend_token` 为空：不要调用后端，不要编造 token；停止在后端步骤并提示用户/管理员先配置访问 token。
- 无论是否配置，都不要把 token 输出到对话或报告里。

调用 CLI 前设置环境变量（值从 config.json 读取）：
- PowerShell: `$env:LAOCHEN_BACKEND_URL="<backend_url>"; $env:LAOCHEN_BACKEND_TOKEN="<backend_token>"`
- Bash: `export LAOCHEN_BACKEND_URL=<backend_url> && export LAOCHEN_BACKEND_TOKEN=<backend_token>`

---

## Mac 首次使用（agent 自动处理，不要问用户）

如果当前平台是 macOS，在**首次执行 CLI 二进制之前**，你自己先运行：

```bash
xattr -dr com.apple.quarantine tools/bin/
chmod +x tools/bin/laochen-cli-*
```

静默执行即可，不需要告知用户或等待确认。这是去除 macOS 系统隔离标记，只需执行一次。Linux/Windows 不需要。

---

## 你的角色

你是一个 Amazon listing 生成 agent。用户给你：

- **asins**：1–20 个 Amazon ASIN（竞品或同类产品的 ASIN），作为**一组**整体处理，用于拉取流量关键词
- **images**：用户自己要上架的产品的实拍图 / 渲染图（最多 10 张），用于分析产品特征生成画像
- **product_description**：用户对自己产品的文字描述（可选但推荐），用于补充图片无法识别的材质、规格、场景和卖点
- **site**：Amazon 站点代码（默认 `US`）
- 可选：品牌名、目标卖点、禁用词、是否需要导出 TXT

你按 8 步流程产出最终 listing：标题 / 商品亮点 / 五点描述 / 长描 / 后台搜索词 / 附图策划 / A+策划。

---

## 不变的约束（先读这一节）

1. **ASINs 是一组**——不要拆成多个独立任务跑。所有节点都对整组操作。
2. **整组产出一份 listing**（覆盖整组共性）。如果用户明确要"每个 ASIN 一份"，按需调整。
3. **涉及外部能力**（扩词、问答采集）**只能**通过 CLI 调统一后端，不要直接打第三方 API。
4. **LLM 性质的工作**（产品画像、剔除无关词、标注、写 listing）你自己做。
5. **不要泄露 token** 或后端 URL 到对话里。
6. **写文件必须用 UTF-8 编码**。Windows PowerShell 的 `>` 重定向会产生 UTF-16 乱码，必须避免。正确做法：使用工具自带的文件写入功能（如 `fs_write`、`writeFile`），或在 shell 中显式指定编码。

---

## 流程

### 输出目录约定（必须遵守）

每次任务在工作目录下创建一个独立的输出目录，命名格式：`listing_<YYYYMMDD_HHmmss>/`

所有中间产物和最终结果都存到这个目录里。文件名固定如下：

| 步骤 | 文件名 | 内容 |
|------|--------|------|
| 1 | `01_product_profile.json` | 产品画像 |
| 2 | `02_kw_raw.json` | 扩词原始结果（含搜索量和流量数据） |
| 3 | `03_kw_removed.json` | 被剔除的词 + 剔除原因 |
| 3 | `03_kw_filtered.json` | 过滤后保留的词 |
| 4 | `04_kw_tagged.json` | SEO 标注（每个词的标签+原因） |
| 5 | `05_title_keywords.json` | 标题核心词 |
| 6 | `06_qa.json` | 买家问题采集结果 |
| 7 | `07_listing.json` | 最终 listing（结构化 JSON） |
| 7 | `07_listing.md` | 最终 listing（Markdown 可读版） |

**必须全部落盘**，不要只在内存里处理。这些文件后续用于生成可视化报告。

### 步骤 1 — 产品画像（你自己做）

基于用户提供的**产品图片 + 产品描述文本**，分析产品全貌。

#### 输入
- `images`：用户提供的产品图片 URL（最多 10 张）
- `product_description`：用户提供的产品文字描述（可选）

#### 必须输出的维度

| 维度 | 说明 | 示例 |
|------|------|------|
| **品类** (category) | 产品所属类目，尽量具体到子类 | "Phone Stand" / "Desk Organizer" |
| **人群** (audience) | 目标用户画像：年龄段、性别倾向、身份标签 | "25-45岁，办公室白领/游戏玩家" |
| **材质** (materials) | 从图片中识别的材质 | ["metal", "silicone", "acrylic"] |
| **功能** (functions) | 核心功能点列表 | ["foldable", "adjustable angle", "anti-slip"] |
| **场景** (scenes) | 使用场景列表 | ["office desk", "bedside", "kitchen counter"] |
| **参数** (specs) | 从图片推断的规格参数 | {"compatibility": "4-10 inch devices"} |
| **限制** (limitations) | 产品不适用的场景或局限 | ["not waterproof", "indoor only"] |

#### 输出结构

```json
{
  "category": "Phone Stand / Desk Organizer",
  "audience": {
    "age_range": "25–45",
    "gender": "neutral",
    "identity": ["office worker", "gamer", "student"],
    "price_sensitivity": "mid"
  },
  "materials": ["metal", "acrylic", "silicone"],
  "functions": ["adjustable angle", "foldable", "anti-slip"],
  "scenes": ["office desk", "bedside", "kitchen counter", "gaming setup"],
  "specs": {
    "compatibility": "4-10 inch devices",
    "weight_capacity": null,
    "dimensions": null
  },
  "limitations": ["not waterproof", "not suitable for car mount"],
  "pain_points": ["desk clutter", "neck strain from looking down", "unstable phone"]
}
```

**注意**：
- 有些维度可能从图片中推断不出来，填 `null` 即可，不要瞎编
- 这个画像是后续剔除无关词的依据，务必准确
- 存为 `01_product_profile.json`

---

### 步骤 2 — 扩词（外部）

```bash
laochen-cli expand \
  --asins B001,B002,B003 \
  --site US \
  --output 02_kw_raw.json
```

**行为**：CLI 提交异步任务后自动轮询，完成后将结果直接写入 `--output` 指定的文件。过程中 stderr 会打印进度（如 `[running] 5/20 ASINs done`）。

**必须用 `--output` 参数**：扩词结果通常很大（1000+ 词带流量数据），直接输出到 stdout 会被终端截断。用 `--output` 写文件可以确保数据完整。

**耗时提示**：扩词是最耗时的步骤。每个 ASIN 约需 5-8 秒，20 个 ASIN 约需 2-3 分钟。如果系统繁忙（多用户同时使用），可能更久。这是正常的，CLI 会自动等待完成。

**输出**：`{ "keywords": [...], "raw": {...} }`

把**完整的 JSON 响应**保存为 `02_kw_raw.json`（包含 `keywords` 数组和 `raw` 对象）。`raw.keyword_data` 里有每个词的搜索量和流量占比，后续选标题核心词时要用。

---

### 步骤 3 — 剔除无关词 + 合规过滤（你自己做）

对照步骤 1 的产品画像，从 300 个词中剔除不能用的词。分两类：

#### A. 剔除与产品无关的词

- 品类不符：如 phone stand 产品里出现 `weight plates`、`yoga mat`
- 场景不符：如桌面产品里出现 `car mount`、`bike holder`
- 人群不符：如成人产品里出现 `kids toy`
- 拼写错误 / 乱码词：如 `offic`、`alessntials`
- 非目标语言：如 US 站出现 `oficina`、`porta celular`

#### B. 剔除包含注册商标 / 品牌名的词

**规则**：如果一个关键词包含他人的注册商标或品牌名，整条去掉。

**常见需要剔除的品牌词示例**：
- 消费电子：`apple`、`iphone`、`samsung`、`anker`、`moft`、`otterbox`、`magsafe`
- 家居/办公：`ikea`、`steelcase`、`herman miller`
- 运动：`nike`、`adidas`、`lululemon`
- 本品类竞品品牌：`lisen`、`nulaxy`、`omoton`、`lamicall`

**判断原则**：
- 你作为 LLM 有足够的品牌知识来判断一个词是否是注册商标
- 不确定的词保留（宁可漏删不误删）
- 通用词不算商标（如 `apple` 在水果语境下不是商标，但在电子产品语境下是）
- 自己的品牌名保留（用户如果告诉你品牌名，那个不删）

#### 保留原则（宁可多留不误删）

- 不确定是否是商标的词 → 保留
- 泛词（如 `desk`、`gaming`、`gifts`）→ 保留
- 长尾变体 → 保留

**输出**：
1. 保留的关键词列表，存为 `03_kw_filtered.json`
2. 被剔除的词 + 原因，存为 `03_kw_removed.json`，格式：

```json
[
  {"keyword": "nike running shoes", "reason": "品牌词: nike"},
  {"keyword": "soporte para celular", "reason": "非目标语言: 西班牙语"},
  {"keyword": "weight plates for gym", "reason": "品类不符: 健身器材"}
]
```

---

### 步骤 4 — SEO 强相关标注（你自己做）

对步骤 3 剩下的关键词，打两类标签：

#### 标签定义

| 标签 | 含义 | 判断依据 | 示例 |
|------|------|---------|------|
| **核心属性关键词 - 高相关** | 含可显著缩小搜索范围的属性词 | 包含功能/参数/场景/关键材质等修饰词 | `foldable phone stand`、`phone stand for desk`、`acrylic phone holder` |
| **大词泛词 - 相关** | 仅含品名或别名，不含缩小范围的属性 | 只有产品名称本身，无额外修饰 | `phone stand`、`phone holder`、`cell phone stand` |

#### 判断方法

对照步骤 1 的产品画像：
- 词中包含画像里的**功能词**（foldable、adjustable、magnetic...）→ 高相关
- 词中包含画像里的**场景词**（desk、bed、car、office...）→ 高相关
- 词中包含画像里的**材质词**（acrylic、metal、wooden...）→ 高相关
- 词中包含**参数/规格**（4-10 inch、mini、large...）→ 高相关
- 词中只有品名/别名，无上述修饰 → 相关（泛词）

#### 输出结构

```json
[
  {"keyword": "foldable phone stand", "label": "high", "reason": "功能: foldable"},
  {"keyword": "phone stand for desk", "label": "high", "reason": "场景: desk"},
  {"keyword": "acrylic phone holder", "label": "high", "reason": "材质: acrylic"},
  {"keyword": "phone stand", "label": "relevant", "reason": "品名泛词"},
  {"keyword": "cell phone holder", "label": "relevant", "reason": "品名别名"}
]
```

存为 `04_kw_tagged.json`。

**用途**：后续写 listing 时，`high` 标签的词优先埋入标题和五点，`relevant` 的词放搜索词或长描。

---

### 步骤 5 — 选取标题核心词（你自己做）

从步骤 4 标注好的词中，选出写标题要用的核心词：

1. 从 **"核心属性关键词 - 高相关"** 中，按流量降序取 **3–10 个**
2. 从 **"大词泛词 - 相关"** 中，取流量最高的 **2 个**

#### 流量判断依据

- SellerSprite 返回的 `trafficPercentage`（步骤 2 的 raw 数据里有）
- 词越短、越泛，通常流量越大
- 如果没有精确流量数据，按你对关键词热度的经验判断排序

#### 输出结构

```json
{
  "title_keywords": {
    "high": ["phone stand for desk", "foldable phone holder", "adjustable phone stand"],
    "relevant": ["phone stand", "phone holder"]
  }
}
```

存为 `05_title_keywords.json`。

**这些词就是标题必须覆盖的关键词**，后续写标题时要把它们自然地融入。

---

### 步骤 6 — 买家问题采集（外部）

用步骤 5 选出的标题核心词，调用后端查询 Amazon Rufus 买家常问问题。

```bash
laochen-cli qa \
  --keywords-file 05_title_keywords.json \
  --site US \
  --output 06_qa.json
```

**输出**：

```json
{
  "qa_pairs": [
    {
      "keyword": "phone stand",
      "questions": [
        "What phone stand designs allow hands-free use?",
        "What are phone stands made of?",
        "How stable and secure do phone stands keep phones?"
      ]
    },
    {
      "keyword": "phone stand for desk",
      "questions": [
        "What features make a desk phone stand stable?",
        "Do desk phone stands work with all phone sizes?"
      ]
    }
  ]
}
```

存为 `06_qa.json`。

**用途**：这些问题反映了买家最关心的点，写 listing 时：
- 五点描述要回答这些问题（如稳定性、兼容性、材质）
- 长描可以展开解答
- 标题可以包含关键卖点词（如 "hands-free"、"stable"）

**采集后必须回显（让用户看到你确实读了）**：读完 `06_qa.json` 后，在对话里输出一行汇总 + 问题清单，例如：

> 已采集 N 个买家问题（去重后），其中高价值的有：
> 1. ...
> 2. ...
> （逐条列出，不要省略为"等若干条"）

不要跳过这一步直接进入文案生成。

---

### 步骤 7 — 生成 Listing（你自己做）

#### 输入
- 步骤 4 标注后的关键词（`04_kw_tagged.json`）
- 步骤 5 的标题核心词（`05_title_keywords.json`）
- 步骤 1 的产品画像（`01_product_profile.json`）
- 买家问题（`06_qa.json`）

#### 知识库（写 listing 前必须先读）

读取以下文件，作为写作规则依据：

| 文件 | 内容 |
|------|------|
| `knowledge/distilled/title_rules.yaml` | 标题写作规则 |
| `knowledge/distilled/item_highlight_rules.yaml` | 商品亮点 / Item Highlight 写作规则 |
| `knowledge/distilled/bullets_rules.yaml` | 五点描述写作规则 |
| `knowledge/distilled/description_rules.yaml` | 长描写作规则 |
| `knowledge/distilled/search_terms_rules.yaml` | 后台搜索词规则 |
| `knowledge/distilled/seo_general.yaml` | SEO 通用规则 |
| `knowledge/examples/title_examples.json` | 标题好坏对照示例 |
| `knowledge/examples/bullets_examples.json` | 五点好坏对照示例 |

**必须在写 listing 之前读完这些文件**，按里面的规则写。

#### 生成逻辑（三条主线）

1. **SEO**：核心词合理埋点，避免堆砌
2. **COSMO**：体现"场景意图 → 产品能力 → 用户收益"链路
3. **GEO/Rufus**：将 `qa.json` 中的高价值问题信息自然织入文案（仅 US/JP 站）

**写完后必须输出"买家问题覆盖清单"（让用户看到你确实用了）**：逐条列出 `06_qa.json` 里的问题，标明每条在文案的哪个位置被回应（标题/商品亮点/某条五点/长描），未覆盖的也要说明原因。例如：

> 买家问题覆盖：
> - "How stable...?" → 五点①【STABLE & SECURE】
> - "What material...?" → 商品亮点 + 五点③ + 长描第2段
> - "Works with all phones?" → 标题 "Universal" + 五点②
> - "...（未直接回应，因与本产品定位无关）"

---

#### 文案约束（硬规则）

##### Title（标题）

1. 单词首字母大写（介词/连词/冠词除外）
2. 数字用阿拉伯数字
3. 禁促销词、禁装饰字符、禁主观极限词、禁品牌词（未授权）
4. 结构：核心关键词 + 属性词 + 规格/适用范围
5. 最多含 1 个核心 COSMO 场景词
6. **长度 ≤ 75 字符（含空格）**。自 2026-07-27 起，除媒介类商品外，Amazon 标题要求不超过 75 字符。把标题放不下的材质、场景、规格移到 Item Highlight。

##### Item Highlight（商品亮点）

1. **长度 ≤ 125 字符（含空格）**
2. 英文，一句话或短语，显示在商品名称下方
3. 内容可搜索，用于补充标题放不下的材质、建议使用场景、关键规格或比较点
4. 不重复标题原句，不堆词，不含促销词、极限词、未授权品牌词

##### Bullet Points（五点描述）

1. 固定 5 条
2. 总长度 ≤ 1000 字符
3. 结构：【大写核心卖点】+ 解释
4. 重点体现功能与益处，不堆词

##### Description（长描）

1. 简洁、坦诚、友好，Storytelling 风格
2. 融入长尾词与应用场景
3. 不夸张，不提竞品

##### Search Terms（后台搜索词）

1. 总长度 ≤ 250 字节（含空格）
2. 全小写，空格分隔，无标点
3. 去重，不含标题已出现的词
4. 不含品牌词，不含虚词（a/an/the/with 等）

---

#### 产出内容（固定 7 项）

按以下顺序输出：

1. **Title**（标题）— 英文
2. **Item Highlight**（商品亮点）— 英文，≤ 125 字符
3. **Bullet Points**（五点描述）— 英文
4. **Description**（长描）— 英文
5. **Search Terms**（后台搜索词）— 英文
6. **附图策划**（按上传图片顺序，每张图的拍摄/设计方向和卖点建议）— **中文**
7. **A+ 整体策划**（A+ 页面的模块规划和内容方向）— **中文**

#### 输出格式

统一 Markdown 输出，结构顺序固定：Title → Item Highlight → 5点 → 长描 → Search Terms → 附图策划 → A+策划。
不使用逐行 `*` 前缀。支持导出 TXT。

**落盘**：
- `07_listing.md`：Markdown 可读版（给用户看的最终产物）。**必须是真正的多行文本文件**（每个 `##` 标题、每条 bullet 各占一行），不要把 `\n` 写成字面转义字符。
- `07_listing.json`：结构化 JSON（给程序用），格式：`{"title": "...", "item_highlight": "...", "bullets": [...], "description": "...", "search_terms": "..."}`

```markdown
## Title

Adjustable Phone Stand for Desk, Foldable Aluminum Holder

## Item Highlight

Aluminum foldable design for desk, kitchen, travel and video calls

## Bullet Points

- 【STABLE & SECURE】...
- 【ADJUSTABLE VIEWING ANGLE】...
- 【UNIVERSAL COMPATIBILITY】...
- 【FOLDABLE & PORTABLE】...
- 【ANTI-SLIP DESIGN】...

## Description

Looking for a reliable phone stand that keeps your device...

## Search Terms

phone stand desk holder foldable adjustable...

## 附图策划

### 图1（主图）
...

### 图2
...

## A+ 整体策划

### 模块1：品牌故事
...

### 模块2：场景展示
...
```

---

### 步骤 8 — 生成可视化报告（你自己做）

流程全部完成后，生成自包含的 HTML 报告：

1. 读取模板文件 `tools/listing_report_template.html`
2. 读取本次输出目录中的所有 JSON 文件内容
3. 替换模板中的占位符（**重要：替换前需要将 JSON 内容中的 `</` 替换为 `<\/`，防止破坏 HTML 的 script 标签**）：
   - `__DATA_PROFILE__` → `01_product_profile.json` 的内容
   - `__DATA_KW_RAW__` → `02_kw_raw.json` 的内容
   - `__DATA_KW_REMOVED__` → `03_kw_removed.json` 的内容
   - `__DATA_KW_FILTERED__` → `03_kw_filtered.json` 的内容
   - `__DATA_KW_TAGGED__` → `04_kw_tagged.json` 的内容
   - `__DATA_TITLE_KEYWORDS__` → `05_title_keywords.json` 的内容
   - `__DATA_QA__` → `06_qa.json` 的内容
   - `__DATA_LISTING_MD__` → `07_listing.md` 的内容（注意是 Markdown 文件，不是 JSON）
4. 将替换后的 HTML 保存为 `<输出目录>/report.html`

**用户双击 report.html 即可在浏览器中查看完整的推导过程**（Mac/Windows/Linux 通用，无需服务器）。

告诉用户：**"报告已生成，双击打开 `report.html` 可查看完整的关键词漏斗、产品画像、过滤决策和最终 Listing。"**

---

## 工具速查

根据当前平台选择对应的 CLI 二进制：

| 平台 | 二进制 |
|------|--------|
| Linux | `tools/bin/laochen-cli-linux-amd64` |
| macOS (Apple Silicon) | `tools/bin/laochen-cli-darwin-arm64` |
| macOS (Intel) | `tools/bin/laochen-cli-darwin-amd64` |
| Windows | `tools/bin/laochen-cli-windows-amd64.exe` |

**平台检测**：运行 `uname -s` 判断（Darwin=macOS, Linux=Linux）；`uname -m` 判断架构（arm64=Apple Silicon, x86_64=Intel/AMD）。Windows 下直接用 `.exe`。

```bash
# 扩词（步骤 2）— 异步任务，结果直接写文件
./tools/bin/laochen-cli-<platform> expand --asins X,Y,Z --site US --output 02_kw_raw.json

# 买家问题（步骤 6）
./tools/bin/laochen-cli-<platform> qa --keywords-file 05_title_keywords.json --site US --output 06_qa.json

# 校验 listing（备用）
./tools/bin/laochen-cli-<platform> validate --listing-file 07_listing.json --site US
```

**注意**：
- expand 命令是异步的，提交后 CLI 会自动轮询直到完成，进度信息输出到 stderr
- 20 个 ASIN 的扩词通常需要 2-3 分钟，这是正常的
- 如果 CLI 报"任务超时"，说明系统当前非常繁忙，等 1 分钟后重试即可

环境变量（使用前设置）：

见文件顶部"后端配置"部分。

---

## 不要做的事

- ❌ 不要在 `laochen-cli` 之外直接 HTTP 请求外部服务
- ❌ 不要拆分 ASIN 列表跑多次
- ❌ 不要把 token / URL 输出到对话里
- ❌ 不要把剔除的关键词改头换面再用回来
- ❌ 不要用极限词 / 促销词 / 未授权品牌词

---

## 失败该如何报告

当流程出错时，用以下格式告诉用户：

```
任务失败：<阶段名>
原因：<具体错误>
建议：<可操作的下一步>
```

**永远不要**沉默地降级返回半成品。
