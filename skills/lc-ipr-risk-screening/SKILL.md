---
name: lc-ipr-risk-screening
description: 对单个美国 Amazon 商品执行知识产权风险筛查。冻结商品事实，经老陈云端完成商品详情和知识产权候选发现；有 SERPER_API_KEY 时本机补公开网页检索，没有也不阻断。再做全批次候选处置、七模块审阅和离线报告。不是法律意见；未检出不等于安全。
---

# LC IPR Risk Screening（US）

一次只处理一个美国商品。用户提供老陈访问 Token。公开网页检索先读环境变量 `SERPER_API_KEY`：有 Key 则本机跑完整检索；读不到就询问用户，用户没有也不阻断，云端商品详情和知识产权发现继续走完。

## 开始前

1. 读取 `INSTRUCTIONS.md`、`references/input-routing.md`、`references/us-workflow.md`、`references/risk-judgment.md`。
2. 选择 `tools/bin/` 中当前平台 CLI；macOS 首次运行前按 `INSTRUCTIONS.md` 处理 quarantine。
3. 官方包第一条业务命令必须是 `auth-check`。失败时说明原因并停止。
4. 先读环境变量 `SERPER_API_KEY`。对话、本轮会话附件或用户上传文件里出现 Key / 疑似 Serper Key 时，立刻注入当前会话环境变量后直接用，不要再问、不要要求改系统变量、不要要求重启 Agent。禁止写入 `config.json`、命令参数、任务目录，禁止回显。环境里没有、用户也没给，再问一次；用户说没有则跳过公开网页检索。
5. 仅接受 `marketplace=US` / `amazon.com`。非 US 必须在上传图片或远程调用前停止。

认证通过后，向用户索取一个美国 Amazon ASIN 或 `amazon.com` 商品链接，并明确说明可以同时上传商品主图和细节图。ASIN/链接路径会自动获取商品资料和可信主图，用户图片是可选补充；用户不提供 ASIN/链接而改用完整人工资料时，至少一张清晰主图是必填项。一次只接收一个商品。

## 正式流程

1. 按输入路由采集并冻结商品事实。先在技能包外指定尚不存在的 `ipr_screening_YYYYMMDD_HHMMSS/`，禁止把任务写进技能包根目录。ASIN 路径由 `collect-product` 使用 `LAOCHEN_BACKEND_TOKEN` 经云端补齐资料。
2. 先看商品文字和实际图片，判断哪些文字是在作为品牌或字标使用，按 `references/input-routing.md` 用 `record-search-identity` 记录，再做 ASIN 语义核对、初始化任务和查询计划。品牌栏不是检索指令：占位值、通用描述、内部型号/SKU 不自动当商标。其中完整值为 `Generic`（忽略大小写和首尾空格）固定作为通用品牌占位排除，不作为品牌或字标查询；其他词仍按图文证据判断。明确没有可识别字标时不发文字商标查询，其余筛查照常；看不清不能冒充没有。
3. 先运行 `prepare-us-screen`、`us-screen` 和 `import-us-screen-evidence`。本地主图会在这一阶段上传到专属后端并绑定受控 HTTPS 地址。云端知识产权发现不依赖 `SERPER_API_KEY`。
4. 再运行 `prepare-serper-run` 与 `run-serper-plan`。有 `SERPER_API_KEY` 则本机跑完整公开网页检索。返回 `SERPER_SKIPPED_NO_KEY` 时问用户一次；用户把 Key 发在对话里就注入当前会话环境变量并立刻重跑 `run-serper-plan`，不要让用户去设系统变量或重启 Agent。用户明确没有就跳过公开网页、继续候选审阅。禁止把 Key 写入 `config.json`、命令参数、任务目录或报告。
5. 进入候选审阅，对工作区中的全部候选一次性完成 `material`、`not_material` 或 `needs_review` 处置。不得遗漏来源条目。审阅 JSON 必须保持 UTF-8；连续 `????` 或替换字符会使整批失败，Windows 写入工具不能可靠保存中文时直接使用可读英文理由。检索相似度只用于排序；外观设计、图形商标/商业外观、版权图片等视觉候选若可能进入 `material`，Agent 必须调用图像查看能力实际打开 `input-images/` 中的目标图和候选摘要 `image_ref` 对应的图片，分别记录共同点、关键差异与整体视觉印象。候选图不可读取时使用 `needs_review`，不得凭分数判高风险。文字商标还必须同时确认文字近似与商品/服务类别重叠。
6. 通过查询覆盖、候选完整性和候选处置门禁后，冻结证据并由当前 Agent 完成一次完整的七模块审阅。Serper 是可选增强：未提供 Key 或单条检索失败都不阻断云端核心证据形成正式筛查结论；有 Key 时，其候选进入同一证据账本和审阅流程，并可改变模块及综合风险。没有 Serper 候选时只能表述“本轮未发现明确风险信号”，不得表述为不存在权利。一审完成后直接定稿，不启动独立二审，不向用户索要人工裁决。
7. 执行 `finalize-assessment`、`render-report`、`validate-release`，交付离线 HTML 及结构化产物。

## 边界

新任务按 `references/risk-judgment.md` 判断风险。对重点外观候选尝试取得完整图纸，在全批次处置前登记补充证据；风险与置信度分别判断，允许保留候选但下调等级。所有 material 候选必须有 finding；视觉 finding 记录整体印象、实际查看文件、证据缺口及重新评级条件。

- 本 Skill 是风险筛查，不执行官方登记或法律状态浏览器核验，也不声称确认官方法律状态。
- `no_result` 只表示该次检索未返回候选，不表示不存在权利或可以销售。
- 云端结果用于候选发现和风险判断，不能替代律师的 FTO、有效性或侵权分析。
- 草稿报告中的候选数量和检索相似度不是综合风险等级；没有完成绑定证据的七模块审阅时，风险必须显示为“无法判断”。
- 对高风险候选、权利状态不清或拟正式上线的商品，应建议用户咨询美国知识产权律师。
- 不得把 Token、上游服务 Key、Cookie 或浏览器凭据写入任务目录、报告或聊天。

## 资源

- `INSTRUCTIONS.md`：完整命令顺序与停机条件。
- `references/input-routing.md`：商品输入和事实冻结。
- `references/us-workflow.md`：双发现计划和候选流程。
- `references/evidence-and-review.md`：证据、审阅与判定约束。
