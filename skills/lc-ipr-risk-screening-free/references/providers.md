# 2.4 免费来源与接口契约

新 `workflow-correction-v1` 的三态提交、按需原文成功、本批次/全任务状态和同快照发布复用见[纠错契约](workflow-correction.md)；原免费、访问、时效和来源真实性约束不变。

本文适用于新任务 `2.4-free`、`free_policy_revision=automation-first-v1`。来源的实际能力、检索覆盖与法律结论分别判断；“官方”“免费”“账号存在”“接口有响应”均不等于某模块已经查清。

当前新任务的 necessary-work-v2 对范围轮转、规划预留释放、无 API 首查替代及来源证据报告采用[统一增量规则](workflow-correction.md#有界取证交付necessary-work-v2)。下文的旧发布限制不覆盖该增量；来源授权、消费账本、禁止路线与原始回执真实性仍完整适用。

## 执行与成本边界

- 数据源支出上限固定 `0 USD`。只执行官方免费服务或已明确选中的商业免费额度；不购买、升级、充值、自动续费、使用付费积分或超额额度。
- EPO OPS、EUIPO Production、JPO API、INPI API 的账号是可选能力，缺少任一账号只影响相应路线，不阻止商品采集和其他来源继续执行。
- Serper、Signa、SerpApi 默认关闭，只能在创建任务时分别用 `--enable-serper-free`、`--enable-signa-free`、`--enable-serpapi-free` 选择；仅配置 Key 不会启用。已选但不可用的发现增强记非阻断缺口。
- 三类商业来源的计划行固定 `required=false`、`required_for=discovery_only`、`requirement_ids=[]`、`authoritative_for_final_rating=false`。可选来源失败不降低已经核实事实的置信度；其发现的实质候选仍必须审阅。
- 自动检索阶段人工只负责登录、验证码、扫码、MFA、访问授权确认。查询、筛选、翻页、下载、取证、比对、独立审阅和报告由 Agent 完成；报告仍可列具体专业或供应链核查事项，用于提高把握或调整已输出的当前评级。受限来源不能改成“请用户搜索、复制结果或截图”。
- CDP 是浏览器操作方式，不改变站点自动化条款。来源禁止自动查询或没有通过自动执行验收时保留缺口，不以“用户触发”“低频”“可见窗口”推定许可。

客户端从 `--task-dir` 和 `--query-id` 指向的全局唯一计划行取得参数，校验任务策略、来源、操作、国家、权利类型、候选和参数绑定。任务中的元数据 `search_dimension/search_language/execution_phase/publication_scope` 不发送给外部接口。run 与 evidence 保留同一 `plan_entry_sha256`。SerpApi Patents/Lens 与 Signa 另支持下面的显式重试参数。

全部第三方凭据只从 Skill 根目录 `.env` 读取，无环境变量或 Keychain 回退；后台授权恢复原包规则：非空进程 `LAOCHEN_BACKEND_TOKEN` 优先，否则读取同目录 `config.json` 与 `config.local.json` 合并后的 `backend_token`。新建私密文件使用当前用户权限，macOS/Unix 为 `0600`；缺失、格式或权限问题输出脱敏原因；可选凭据不可用只影响对应来源。`.env` 不执行 shell、不展开变量、不修改进程环境。会话 Token、Cookie 仅存内存；凭据不写入任务、原始响应、报表或命令参数。初始化与分发见 [本地配置与凭据](../INSTRUCTIONS.md#2-本地配置与凭据)。

`.env` 沿用 12 个既有字段名：`EPO_OPS_CONSUMER_KEY`、`EPO_OPS_CONSUMER_SECRET`、`EUIPO_CLIENT_ID`、`EUIPO_CLIENT_SECRET`、`JPO_API_USERNAME`、`JPO_API_PASSWORD`、`INPI_USERNAME`、`INPI_PASSWORD`、`SERPER_API_KEY`、`SIGNA_API_KEY`、`SERPAPI_API_KEY`、`RAPIDAPI_KEY`。空值表示未配置；保留 `RAPIDAPI_KEY` 字段不代表启用新来源。云端 Skill 授权与知识产权数据源账号独立，后台 Token 不存入 `.env`。

### 请求与重试安全

- 公共 HTTP 每次跳转保持同一 scheme/host/port，拒绝跨源及 HTTPS 降级；EPS/INPI 的自有传输保留更严格的禁止跳转。公共响应有 32 MiB 上限，单次重试最多 3 次，429 不重试；计量请求保持 retries=0。`LC_IPR_OPERATION_DEADLINE_EPOCH` 限制同一操作的剩余时间，重试不另起完整计时。
- SerpApi 与 Signa 在每次计量请求前，用本机跨进程账本原子预留一份免费搜索额度；SerpApi Patents/Lens 共用余额。账本只保存凭据指纹、计划/尝试指纹与计数，不保存 key。范围是本机同一凭据；其他设备及同账号的另一把 key 无法由此观察，服务端账户检查和拒绝仍优先。
- 默认 `attempt_id=initial`，相同 task/query/plan hash/attempt 不重复占额。响应丢失、原文哈希损坏、动态证据过期或已记录的条件变化需要新请求时，使用新的 `--attempt-id ID --retry-reason '具体原因'`；Agent 先持久记录这次修复或重试身份。新 attempt 重新预留额度，旧超时/崩溃的未知消耗不退款；任务次数上限和实时 Free-plan 校验仍生效，不因换 ID 放宽。
- 远端余额升高不能直接冲销本地预留。SerpApi 仅在真实账号响应给出更晚的续期日期、旧日期已到且新日期尚未到时切换周期；没有可信周期的来源（当前 Signa）不自行推算月初回补。相关本地额度停止应明确说明需要核查周期事实，不能删账本绕过。
- `LC_IPR_TEST_MODE=1` 下 SerpApi 必须显式 loopback HTTP 地址并使用固定 dummy key；不读取真实本地 key。`LC_IPR_OFFLINE_TESTS=1` 下父子进程只使用临时虚拟凭据，均不得读取真实 `config.json/.env`，各 HTTP 入口禁止非 loopback 实际请求，不改变生产配置/来源标记测试。单元模拟不代表线上执行能力。
- SerpApi 的零结果需要成功 envelope；唯一精确零结果提示也必须配合 `search_metadata.status=Success`。包含 “no results” 的超时、额度等错误不再转换成零命中。
- 2.4 的 Serper→SerpApi 回退在调度器与客户端两层统一检查当前计划 hash、原始文件完整性及动态时效；旧成功但原文缺失、哈希变化或过期不能阻止可用替代来源。2.3 的历史回退规则保留。
- `identity-discovery-v1` 的备用策略另支持显式召回不足补搜：`task.discovery_followups[]` 每项包含备用 `query_id、plan_entry_sha256`、已完成 Serper 的 `source_run_id、evidence_ids[]`、`reason_code=zero_results|insufficient_relevant_candidates`、`reason、reviewer`。Agent 必须先审阅实际结果再作决定；调度与客户端共同验证原始证据、时效及计划绑定。只执行既有未消费备用行，不启用未选来源、不增加任务预算、不退款旧消费、不放宽账户门禁。决定随请求及审阅摘要留存。
- 任务预算与 evidence 写入使用同一跨进程锁实现：POSIX flock / Windows msvcrt，锁等待默认最多 30 秒且服从操作截止时间；没有锁能力即停止相关写入/请求，不能无锁继续。

### 可调执行边界

报告校验只完整重算一次可信评估，后续视图复用同次结果；执行缺口从已算覆盖派生。`decision_snapshot` 仅在单次不可变输入作用域复用纯索引/判断，退出核对内容摘要并清空；真实源文件仍核验，不能用mtime或跨运行缓存代替哈希。批次浏览器入口 `run_browser_plan.py --task-dir DIR --query-ids QRY1 QRY2` 只装载协调一次，逐条回执/检查点保持独立，每动作检查当前字节与撤销状态；不提高同源并发，部分成功遇限流也暂停该来源。

`necessary-work-v1` 新任务的普通浏览器已提交失败，按现有 `source_runs` 中相同 provider、query_id 和完整 `plan_entry_sha256` 计数：初次失败后至多恢复一次，默认值 `cdp.submitted_failure_resume_limit=1` 位于 `references/runtime-config.json`。待办、批次执行器与直接浏览器入口共用同一判断；两次失败后显示 `BROWSER_SUBMITTED_FAILURE_RECOVERY_EXHAUSTED`，保留失败原因、回执引用和次数，不再自动提交。删除状态文件、修改实现摘要均不重置次数；历史无标记任务沿用原行为。成功和部分成功走已有完成／部分结果恢复机制；限流冷却、未提交动作不消耗普通失败次数，未知提交先核验，查询语法拒绝交 Agent 修计划。耗尽仅证明该准确计划行的来源执行受阻，仍须处理其他来源、分类补查和 Agent 调查后才能按阶段报告规则停止。

先处理身份、主体和核心结构，再补缺失维度；宽泛查询按有证据的用途/分类拆分，原截断与未处理候选保留，不以命中一件专利终止必要召回。PDF/已登记页图/TSDR合格事实复用，不重复下载或为显示用途重查。双审可并行读取同一冻结快照，主审等两方完成；证据实质变化重开受影响项。fast/release仅在Skill修改时执行，商品排查仍运行鉴权、输入/证据/报告验证。阶段计时分别记录调度、网站、合并、评估、渲染与验证，不将来源时间字段或离线提速外推整轮速度。

`references/runtime-config.json` 中的 `performance.max_api_concurrency` 默认 3，调度器限定 1–3，单来源 lane 内仍串行；共享 SerpApi/Serper 及 EUIPO 路线分别共用 lane。`dynamic_evidence_max_age_hours` 默认 48，必须为正的有限数；动态查询/状态证据超过该时长不直接复用，原始文件与 hash 也必须完整。EPS 静态已公开文献按文件完整性复用，不能把其当成新状态查询。

`performance.api_operation_timeout_seconds` 默认 180，API 调度器限制为 1–180 秒；`cdp.operation_timeout_ms` 默认 165000，浏览器计划调度中的有效操作预算限制为 1–165 秒，单条总预算 180 秒。降低这些值可能增加超时缺口，提高配置不能突破调度上限、免费额度或计划次数。来源 CLI 保持独立子进程；本次没有增加跨任务缓存或常驻 Token 复用。

## 官方 API

### EPO OPS：结构化发现与候选扩展

- 角色：公开专利召回、书目、分类、同族和法律事件补充；不独立证明授权后目标国现行效力。注册及审批可能受阻，不能设为启动前提。
- 当前注册免费量为每周 4 GB；任务仍受同账号、本机跨进程周配额账本约束。每次真实数据请求先原子预留，响应后结算；失败或崩溃的未知用量不自动释放。付费 Header、429、配额拒绝或不可信窗口均停止后续请求。[官方免费政策](https://www.epo.org/en/service-support/ordering/fair-use)
- 2.4 搜索使用 `GET https://ops.epo.org/3.2/rest-services/published-data/search/biblio,abstract?q=<CQL>`，计划参数为 `q/range/right_type`；通过官方 `X-OPS-Range` 请求分页，例如 `1-25`。首轮按文献分别保存标题、摘要、申请人、IPC/CPC、申请号和优先权号；缺失字段不编造。2.3 保持原 search 路径。OAuth Token 在内存缓存。
- 只有实质候选追加 `candidate_detail`，其中 `detail_operation=biblio|family|legal`，携带已知文献号和 `candidate_id`。这些补充不代替官方单案核验。
- `2.3` 保留每任务 6 次搜索；`2.4` 使用独立 `limits.epo_search_queries_per_task_v24=96`，供多国、多维查询使用。提高本地次数不提高 4 GB 免费边界，也不证明检索充分；达到次数或字节门槛均记缺口。
- 生产搜索必须包含可识别的搜索 envelope 和 `total-result-count`；2.4 正命中还须核对响应 `ops:range` 与请求分页一致，服务器返回第一页不能冒充后续页。异常 XML、缺失身份字段、与计数冲突的空页不能是 `no_result`。首屏 25/500 条会记录截断。新增书目路径与页码核对已做离线契约测试，本次没有获批账号的线上验证。

接口依据：[OPS 官方技术文档](https://link.epo.org/web/searching-for-patents/data/en-ops-v3.2-documentation-version-1.3.20.pdf)。

### EPO Publication Server：免注册 EP 原文

- 新来源 `epo_publication_server/document_retrieval`；`scripts/eps_client.py` 已实现 XML 下载、案号核对、权利要求和说明书提取。它是文献内容证据，`authority_scope=published_document_only`，不作为国家法律状态核验。
- 官方 REST 1.2 无需注册。当前网页写每 IP 滚动七天 5 GB，参考 PDF 写 10 GB；实现采用更严格的 `5,000,000,000` 字节，预留 50 MB 安全余量，单响应上限 32 MiB。[服务与额度](https://www.epo.org/en/searching-for-patents/data/web-services/publication-server)、[REST 契约](https://data.epo.org/publication-server/doc/EPS%20REST%20services.pdf)
- 计划参数 `q/document=EP<编号><kind>`、`format=xml`、`candidate_id/right_type=patent`；实际地址为 `/publication-server/rest/v1.2/patents/EP<编号><correction><kind>/document.xml`，普通文献 correction 使用 `NW`。
- 跨任务账本位于本机应用状态目录，采用滚动七天预留和结算；无法观测共享同一公网 IP 的其他设备用量，服务端拒绝始终停止。404 表示文献格式不可用，不是检索零结果。
- 旧验收摘要记录一个官方阳性文献，但本次在 Skill 和当前工作区未找到与其绑定的原始响应及收据，因此当前标为“历史摘要待补证”，不继续作为可复核的 passed 验收。当前客户端未下载 PDF/ZIP/TIFF，原始附图仍需另有合格来源。2006 年前 XML 可能是转换结果，必要时应取得官方 PDF，不能据旧 XML 单独完成排除。[官方格式说明](https://www.epo.org/en/searching-for-patents/technical/publication-server/help)

历史摘要见 [provider-live-acceptance-v24.json](provider-live-acceptance-v24.json)：它记载 EP1004359B1、32,699 字节和解析统计；这些是旧记录的自述，不是本次重新取得的证据。下一次获授权真实调用须留存原文、哈希和收据后再更新验收状态。

### DATA INPI：注册免费法国 PI API

- `scripts/inpi_client.py` 实现官方 API PI 的认证、搜索、已知号 notice 和图形商标图片。账号在 DATA INPI 选择 PI 内容，按官方流程激活 API 账号；不是企业 RNE API，也不是 PISTE OAuth 接口。[免费账号与覆盖](https://data.inpi.fr/content/editorial/apis_pi)、[官方技术文档](https://www.inpi.fr/sites/default/files/Inpi_doc_tech_API_PI_v1.0_0.pdf)
- 凭据为已激活 PI 账号的 `INPI_USERNAME/INPI_PASSWORD`。HTTPS 证书验证始终开启；不照抄旧示例中的 `curl -k`、回显 Token 或 Cookie 文件。
- 认证：`GET /services/uaa/api/authenticate` 获取内存 XSRF；`POST /auth/login` 携带 username/password，建立内存 Cookie 会话。生产域名固定 `https://api-gateway.inpi.fr`，异常跳转停止。
- 搜索：`POST /services/apidiffusion/api/{brevets|marques|modeles}/search`，JSON 参数为 `collections/query/position/size`。计划中的 `q` 保存完整 INPI 语法；专利 `[(TIT OU ABFR)=(taille* haie*)]`，商标 `[Mark_Exp=example]`，外观 `[DesignTitle=fauteuil*]`。不能发送裸关键词并声称已检索。
- `collections:["FR"]` 是官方支持值；专利还可用 EP/WO/CCP，商标可用 EU/WO，外观可用 WO。当前自动计划默认 FR，不把能力列表误报为已执行其他集合；第三方合法提供的 WO 数据不等于执行 WIPO 网站请求。
- 文档规定分页上限：brevets position 500/size 500，marques position 500/size 200，modeles position 200/size 100；超出边界不能靠无限分页解决，需拆分有依据的检索条件并保留截断。
- 已知号：专利 `GET /brevets/notice/pubnum/{number}`，商标 `/marques/notice/{number}`，外观 `/modeles/notice/{number}`；前缀均为 `/services/apidiffusion/api`。图形商标媒体用 `/marques/image/{number}/std` 并校验文件类型、尺寸和 SHA-256。
- Notice 必须核对身份、权利人、状态、分类；法国记录不能证明其他国家效力。EP/EU/WO 聚合记录即使取到，也不能冒充相应主管局的最终效力核验。
- **当前未做激活账号实测。** 已实现真实端点和 fail-closed 解析；未知响应 envelope 保存原文并记 `INPI_RESPONSE_CONTRACT_UNVALIDATED`。外观完整视图清单尚待验收，当前不能给出完整外观核验；不得把离线测试当作线上成功。

### EUIPO Production：EU 文字商标与外观

- 官方 API 免费，但 Production 需要集成测试及审核资料；账号未获批只形成该路线缺口。Sandbox、fixture 和测试端点永远不能满足正式或低风险门禁。[官方接入 FAQ](https://dev.euipo.europa.eu/faq)
- 1.1.0 Production Token：`https://euipo.europa.eu/cas-server-webapp/oidc/accessToken`；API bases：`https://api.euipo.europa.eu/trademark-search`、`https://api.euipo.europa.eu/design-search`。Sandbox 的 `auth-sandbox` 与 `api-sandbox` 只能成套用于测试，禁止混接。
- 搜索 HTTP 参数仅 `query=<RSQL>/page/size`；计划另保留 `q/right_type`。文字例：`wordMarkSpecification.verbalElement==*example*`；外观名称用 `productIndications`，Locarno 用 `locarnoClasses`。构建器函数为 `search_rsql(product,value,right_type)`。
- Trademark Search 1.1.0 没有 Vienna 分类搜索字段，不能把 Vienna 代码放入文字字段。现有 2.4 自动计划未承诺完成 EU 图形商标分类及图像召回；相关受限网页不安排人工查询替代。
- 单案详情与所需媒体分别取得、绑定身份及 SHA-256。商标状态完整不等于商标混淆分析完成；外观只有一张图也不代表视图充分。缺字段、缺图和异常 JSON 保留缺口。

### JPO API：日本已知号码核验

官方免费、需注册申请，支持已知专利、意匠和商标号码的对应数据；不承担关键词、全文或图片相似检索，不支持实用新案。读取配置中的端点日限额及运行结果，Token 仅内存缓存，未知号码类型不得猜测转换。[官方申请入口](https://www.jpo.go.jp/system/laws/sesaku/data/api-provision.html)、[API 技术参考](https://ip-data.jpo.go.jp/api_guide/api_reference.html)

JPO 号码核验成功不能填补 J-PlatPat 关键词、图像召回缺口；在当前“人工仅登录或验证”的边界内，没有通过自动化条款及路线验收的网页不启用人工业务回退。缺媒体或状态字段的候选仍为不完整。

## 可选商业免费发现

### Serper

`api-first-v1` 新任务采用 [API 优先契约](api-first.md)：Serper 三操作共享 30 次；有官方免费证明或用户明确现有余额授权后执行。以下 10 次及固定停止规则仅用于无新标记历史任务。

初始提供 2,500 次免费查询，无需信用卡；不是每月恢复的额度。仅使用 `patents/search/images`，任务共 10 次，上限分别 4/3/3；文字 Images 不等于反向图片搜索。[官方免费额度](https://serper.dev/)

**2.4 当前不发送 Serper 计量查询。** 只有 Key 或本地 `allow_paid=false` 无法证实账号仍有免费额度、没有付费 credits 且没有自动充值；本版本尚未实现和验收官方账户页自动取证。因此在网络请求前记录 `FREE_ACCOUNT_UNVERIFIED`，保留精确的 SerpApi fallback。2.3 历史执行规则维持原契约。

当前更稳妥的免费发现接入是 SerpApi，因为其 Account API 能在计量请求前核实套餐、余额和付费积分。Serper 客户端既有发现与解析代码保留，未来须先由 Agent 从官方账户页自动核实免费权益并建立跨任务账本；人工仅协助登录，不抄余额、不提交任意 JSON 充当证明。搜索摘要、图片结果和 Google Patents 聚合状态只能发现线索。

### SerpApi Google Patents 与 Google Lens

当前 Free 计划每月 250 次、每小时 50 次。每次计量搜索前调用免计量 Account API，必须同时确认 Free/Free Plan、月费 0、账户 active、额外积分 0、免费余量正数；缺字段、付费套餐和额度耗尽在搜索前停止。[定价](https://serpapi.com/pricing)、[Account API](https://serpapi.com/account-api)

- 两引擎共享同一账号、任务锁、硬停止记录和**每任务合计三次**预算，不能各算三次。存在产品图时默认最多两条专利＋一条 Lens。
- 专利计划使用 `q/num/country/right_type`；已绑定且正常完成的 Serper 同查询使该 SerpApi fallback 跳过。[Google Patents API](https://serpapi.com/google-patents-api)
- 新规划在相同预算内保留身份发现与产品特征查询；未有上述召回不足决定时，正常完成的主源仍按原备用规则跳过。源成功不等于相关性充分，不得把跳过备用报告为第二个来源已搜索。
- Lens 来源为 `serpapi_google_lens/image_search`；计划使用 `q/image_url/type/hl/country/right_type=copyright`。只接收已在 `task.images` 记录并具有摘要的公开 Amazon 媒体 URL；禁止上传本地图片或自动公开产品资料。[Google Lens API](https://serpapi.com/google-lens-api)
- Lens 查询参数映射到 `engine=google_lens,url,type,hl,country`；原始响应只把有来源页面的 visual/exact matches 归一化为发现线索。不推定首次创作、权利人或侵权概率，未知搜索总量记截断。
- Lens 已完成离线契约及免费保护测试，未使用真实 Key 做在线计量查询；不能宣称已在线验收。

### Signa

默认关闭；每任务最多三次、每次最多 25 条，仅文字商标 `exact/phonetic/fuzzy/prefix`。搜索前使用 account/plan/usage/credits/offices 等安全检查确认免费边界，禁止 known-mark 搜索探测；有待结算消费、付费积分、无法确认的自动充值或超额信号即停。

以实时 `/v1/offices` 为准合并目标法域，EU 使用 EM，不假定 DE/IT/ES/JP 全覆盖；现有适配器仍排除 WO。图像/Beta/合作账号接口没有实现为普通账号能力。免费额度公开口径可能变化，以当前免费账户契约为准，不写死营销数字。[服务说明](https://signa.so/compare)、[配额参考](https://docs.signa.so/api-reference/rate-limits)、[OpenAPI](https://api.signa.so/v1/openapi.json)

## 浏览器路线、验收与失败

浏览器按“来源×国家×权利×操作”记录能力，而非按网站主页能否打开评估。US PPS/TM Search/TSDR 有现有查询执行器，但本次没有逐项线上验收；国家适配器仅有元数据或打开入口时仍为 unvalidated。EPO Register、EUIPO eSearch、TMview、DesignView、WIPO 受限网站以及当前未有兼容自动操作的 J-PlatPat 不用人工完成业务查询。

真实验收至少含阳性、明确零结果、单案详情、查询和身份绑定、分页截断、访问验证后继续以及拒绝/页面变化。一次正例不能升级整站所有操作，fixture 不能出具正式覆盖。详细地域与不可替代字段见 [official-sources.md](official-sources.md)。

来源状态仍只有 `success/no_result/not_applicable/needs_user_action/access_limited/failed`。`needs_user_action` 只承载简单访问验证；其他需要资料、接口开发或条款支持的事项写 Agent 缺口。失败不能降格为零结果。

检索 payload 的 `search_metadata` 同步到 `run.metadata.search_coverage`，含 `total_hits/retrieved_hits/reviewed_hits/truncated/stop_reason/source_updated_at/schema_valid`。API 不判断已审阅数量，初值 `null`，由审阅 ledger 推导；来源更新日期未知也用 `null`。完成一个分页不等于检索充分。

## 历史兼容与未来候选

`2.3-free` 的来源选择、预算、规则和计划哈希保持冻结，不能用本文 2.4 路由静默重建或迁移；历史 default-discovery/optional-discovery 语义仍按持久化策略读取。`2.1/2.2` 只读证据与重建报告。新客户端要求 2.4，不能注入历史计划。

OEPM 免费 Web Services、Google BigQuery Sandbox 公共专利数据、UKIPO 未来开放接口、CourtListener/RECAP 免费案件发现均保留为候选能力；未有本版本可执行客户端和真实验收者不得加入“已自动可用”清单。付费 DPMAconnectPlus、收费 Lens.org API、无可用免费注册入口的服务不作为可执行回退；没有免费合格替代时保存已完成结果和具体缺口，不生成自动付费升级动作。
# 本地阶段计时

`runtime-timings.jsonl` 是快照之外的辅助计时，不是取证日期或业务完成证明。新专项任务的合并、分流、评估定稿、报告构建和验证入口以 monotonic 时钟记录 `cli_main_inclusive` 耗时；报告构建包含该入口原有验证与渲染，不称纯 HTML 渲染时间。浏览器/API 的单动作、初始化及调度耗时复用已有字段，不重复统计。历史任务无新修订标记且无显式输出目录时不写计时；日志写入失败不得改变业务返回值或异常。
