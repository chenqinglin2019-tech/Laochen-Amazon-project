# 双入口与目标身份（01A）

新建 `2.4-free` 任务默认携带 `product_entry_revision=dual-entry-v1`。历史无标记任务保留旧入口/ASIN规则，不给历史任务补标记或新建任务来重置记录。未知版本拒绝执行。

## 使用顺序

实际排查第一条业务命令仍是 `auth_gate.py`；通过前不解析业务输入。开发和离线测试不调用真实鉴权。通过后识别入口，先核对用户已有资料，只询问阻塞身份确定所需的最小缺项。新任务启用 `product_structure_policy=use_provided_else_unavailable_v1`，查询过程中不询问实际结构；已有用户结构资料按来源使用，未提供默认无法提供，缺少结构不阻断其他可执行查询或报告。

- Amazon：`create_task.py --url URL`，国家缺省沿站点；credentials 预检后由现有 CDP 采集、录入。首次有效页可落到与请求 ASIN 不同的当前子体，不主动切变体；保存请求链接、实际页面、ASIN和选项。后续依据冻结目标核对，页面变成其他子体/选项时保留原身份并报告冲突，不能把失败记录当成替换目标。
- 用户资料：Agent 核对一个具体产品及用途、适用变体和当前必要资料，形成下述 JSON；`create_task.py --product-input /absolute/product-input.json --jurisdictions DE`。无链接时国家必须由用户明确，不能从语言或品牌推断。credentials 预检后执行 `record_user_product.py --task-dir DIR`，再登记[对象范围与方向依赖](product-scope.md)，执行 evidence 预检和产品分析。无需运行 Amazon 采集，不伪造 ASIN、Marketplace 或浏览器记录。

两类入口使用同一 task/evidence/analysis/plan。`awaiting_browser` 为现有兼容状态名，用户资料入口在该状态等待资料录入；依据 `request.entry_type` 分支，不能仅凭状态名打开浏览器。鉴权预检未通过不得录入。

## 用户资料输入

由 Agent 按已有用户资料生成，不能要求用户填写技术 JSON。新任务推荐 `product-input-v2`，需按[02A 商品采集与事实交付](product-delivery.md)增加 `image_selection`；v1 仅用于现有兼容路径。下列是合成旧格式示例，不是业务证据：

```json
{
  "schema_version": "product-input-v1",
  "product": {"title": "折叠支架", "purpose": "支撑手机", "structure": ["铰接支撑结构"]},
  "sources": [
    {"source_id": "photo-1", "kind": "image", "path": "product.png"},
    {"source_id": "description-1", "kind": "description", "text": "用户说明：一个折叠支架，无其他变体。"}
  ],
  "identity_review": {
    "single_product": true, "status": "confirmed", "reviewer": "agent",
    "reasoning": "说明与图片指向同一支架，用途明确，无产品或变体冲突。",
    "source_ids": ["photo-1", "description-1"], "conflicts": []
  },
  "readiness": {
    "status": "ready", "reasoning": "当前方向所需外形和铰接特征可辨识。",
    "nonblocking_gaps": ["未给出颜色；不影响当前启动方向。"]
  }
}
```

`product` 是单个对象；允许 title、purpose、brand、manufacturer、category、bullets、specifications、structure、variant、visible_ip_claims。不支持的字段拒绝。title/purpose须明确，其他字段按真实资料给出，不虚构内部结构、变体、规格或品牌。规格/变体不是通用必填清单。
`sources` 每项有唯一 source_id，kind为 image/specification/description，path或text二选一；image必须为实际文件。相对路径以输入JSON目录解析。identity_review引用存在的来源并给出实际判断依据；程序只检查记录与文件，不证明Agent判断真实或图片充分。

多个产品混杂、用途或关键变体不明时不写身份 confirmed；在身份核对前不得启动依赖身份的检索。身份已确定但局部资料不足时，readiness 显式设置 `revision=directional-readiness-v1`、`status=partial`（或 needs_info），再通过对象范围记录具体受影响事实与内部分析问题；实际结构不足按默认不可提供处理，不生成用户待答事项；未采用该版本仍要求 ready。nonblocking_gaps 只用于非关键缺项，不能把关键冲突改称非阻塞。

## 留存、冻结与恢复

create_task仅建立待核对任务与输入指纹；record_user_product在预检后复制资料到本任务raw/user_materials，核对文件实际字节、尺寸及hash，记录用户来源、Agent身份审阅和source_run，不从示例捏造来源。记录后不再依赖原输入文件存在；相同资料重复录入幂等。证据已写入而任务写入中断时，重试核对并复用原记录，不重复追加。使用既有 resume_continuous_work.py 创建恢复副本后，来源按 recovery-manifest.json 核验，即使原目录已不可用也可继续。创建后资料变更会拒绝录入，不能偷偷改任务中的指纹；需明确处理输入变化，再按适用流程恢复。

冻结身份以稳定product_id、入口类型及适用ASIN/变体绑定，不要求“资料全部充分”。新范围版本保留原核对与线索交接要求，按明确依赖判断局部是否可继续；无范围版本的历史任务保留全量分析门槛。普通刷新不得替换冻结目标；用户明确换目标或纠正身份时走[02B 受控变化入口](product-change.md)，保留旧记录并定向复核。

数据和报告来源：用户资料入口显示产品ID、用途和真实资料来源；无ASIN不显示虚构编号或空商品链接。图片仍按实际文件和hash展示，主图不代表所有视图充分。
