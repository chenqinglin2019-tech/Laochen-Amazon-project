# 商品输入（原完整路由，仅限美国）

输入层保持原来的复杂采集，不换成简化 JSON 捷径。本版只接受美国商品：`marketplace` 必须是 `US`；Amazon 链接只接受 `amazon.com`。用户要其他站点时停止。

采集本身不做专利、商标、版权或维权检索。字段契约见 `references/contracts/product-input.schema.json` 和 `product-facts.schema.json`。

## 接受的输入形态

- `--product-json`（`--input` 仍是兼容别名）
- 无 JSON 的 `--product-url`
- 裸 ASIN + `--marketplace US`
- 完整人工 JSON，带显式图片列表、本地 `image_folder`，或两者都有

`schema_version` 默认 `0.1`，`input_mode` 默认 `auto`。marketplace / ASIN 可写在顶层或 `product` 下，冲突则阻断。仍接受 `screening_tier`（`low_cost` / `high_risk`）、`jurisdictions`、可选 `feishu_record_id`。本版落地只跑美国；非 US 的 jurisdictions 不要继续筛查。

## 路由

`auto` 顺序：

1. 人工资料完整 → `manual_detail`
2. 否则有效 ASIN 或 Amazon URL → `asin_lookup`
3. 否则 `needs_confirmation`，返回确切缺失字段

人工完整门槛：marketplace、标题、至少一条五点、长描述、一张可读的 `role=main` 常规图片。资料完整时即使同时有 ASIN/URL 也走人工。

`manual_detail` 禁止探测、调用或记录 SellerSprite。把 SellerSprite 结果传给这条路由是错误。

缺字段只追问，不对外查询，不生成风险等级。

## 命令

```bash
<IPR_CLI> inspect-input --product-json /absolute/product.json
<IPR_CLI> inspect-input --product-url https://www.amazon.com/dp/B0XXXXXXXX [--input-mode asin_lookup]
<IPR_CLI> inspect-input --asin B0XXXXXXXX --marketplace US

<IPR_CLI> collect-product --product-json /absolute/product.json --task-id ipr_<unique_id> --output-dir /absolute/ipr_screening_YYYYMMDD_HHMMSS
<IPR_CLI> collect-product --product-url https://www.amazon.com/dp/B0XXXXXXXX --task-id ipr_<unique_id> --output-dir /absolute/output

<IPR_CLI> validate-product --input <task-dir>/02_product_facts.json
<IPR_CLI> validate-product-corroboration --task-dir <task-dir>
```

`asin_lookup` 时 inspect 返回云端 `seller_lookup`（`provider=laochen_backend`，`action=product_detail`），不返回任何本机上游命令。用户需要 ASIN/`amazon.com` 链接和 `LAOCHEN_BACKEND_TOKEN`。公开网页检索先读 `SERPER_API_KEY`，没有就问一次；用户把 Key 发在对话里时注入当前会话继续，明确没有也不阻断采集和云端发现。卖家精灵等云端上游凭据不进入用户环境。`collect-product` 自动调用 `/ipr/product-detail`，分发 CLI 不接受本地上游结果文件。用户已给的非空字段优先，云端详情只补缺口。身份（ASIN / marketplace / title）缺失或冲突则阻断。

`--output-dir` 必须指向技能包外面、尚不存在的正式任务目录，禁止 `.` 或 `SKILL.md` 所在目录。成功采集通过临时目录和原子重命名一次性创建该目录，并写入 `01_collection_result.json`、`02_product_facts.json`、`input-images/`。CLI、原始输入和临时文件可以放在独立工作目录，但不要再创建第二个任务目录。缺输入或图片问题不留下半成品任务目录。后续 `init-task` 只初始化这个已有目录。

## ASIN 语义核对

结构合法的 SellerSprite 结果还不是最终商品身份。进入后续筛查前必须有 `input-metadata/product-corroboration.json`，绑定当前 product-facts digest，核对：

- 请求的 ASIN 与 marketplace
- 标题、品牌、类目内部一致
- 标题与冻结主图一致

三项都是 `corroborated` 才能继续。`conflict` / `unknown` 要停下来问用户。人工完整资料不走这条 SellerSprite 核对。

## 图片采集（输入层冻结，检索层负责公网传输）

输入层会冻结主图副本和 SHA-256，也可带 `public_url`。这不代表云端知识产权发现或公开网页图搜已经可跑。

- 显式图片保留调用者顺序、角色、排名、原文件名、可选公开 HTTPS URL、任务内副本、SHA-256。
- `image_folder` 不递归；自然序 `1,2,10`；第一张当主图，其余为细节图。文件夹与显式列表同时存在时，文件夹优先。
- `manual_detail` 冻结选中的本地主图。
- `asin_lookup` 优先 SellerSprite 第一张可信 Amazon HTTPS 主图；下不下来才退回用户给的本地主图并告警。
- Seller 图跳转不得离开受信任的 Amazon 图片 host。拒绝凭据、query string、fragment。
- 文件必须是常规非符号链接、≤ 20 MiB、有效图片签名、解码尺寸有上限。

`external_upload_allowed` 只保留调用者意图。采集阶段不创建、不推断 provider 上传授权。

公网图传输见 `us-workflow.md`：Amazon HTTPS 主图直接使用；本地主图在
`us-screen` 阶段经专属后端上传。七模块查询计划先以冻结图片 ID 和 SHA-256 绑定这两条反向图搜，`us-screen` 成功后再由 `prepare-serper-run` 把受控 HTTPS 地址写入执行请求。采集阶段本身不上传，也禁止自建图床。

## 未知与来源

每个已填字段记录来源类型、来源引用和采集时间。外形、结构、机构、文字、logo、角色、图案、包装、创意资产、宣称都要出现在 feature inventory。缺类目写成 `unknown`，不要 silently 省略。缺授权或创意来源写成带出处的 `unknown`。
