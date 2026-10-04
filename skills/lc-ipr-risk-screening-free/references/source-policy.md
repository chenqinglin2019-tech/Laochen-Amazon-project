# 来源账户容量与冻结配置

新任务采用 `free_policy_revision=existing-account-capacity-v1` 和 `source_settings_revision=frozen-source-settings-v1`。已有任务不补标记、不改预算、不替换回执或旧审阅。`2.4-free`、`free_policy`、`*_free_enhancement` 和 `--enable-*-free`、额度账本及回执中的 `local_free_*` 保留为兼容字段及入口名称；它们在新任务中不代表只能使用免费账户。

- Serper、Signa、SerpApi 仍默认关闭，必须逐来源显式启用；Key 已配置不会启用来源。启用后的新任务可消耗账户现有免费或付费套餐、积分，费用不保证为零。Skill 不自动购买、充值、升级、主动续费或启用超额，不新增付费提供方。
- `runtime-config.json.source_access_policy` 是新任务的账户规则；顶层 `free_policy` 及提供方中的 `free_plan_only/allow_paid/allow_extra_credits` 保留为历史免费客户端的配置基线，不覆盖新任务的版本化账户门禁。
- Serper 启用时冻结有次数上限的现有余额授权，不要求免费属性证明。回执记录余额及费用未核实；配额错误停止，未知消耗不退额。历史任务继续使用原账户证明或原显式余额授权。
- SerpApi 请求前核对活跃账户、套餐名称、非负月费、套餐余量及额外积分；新任务可用容量为套餐余量加现有额外积分。保留实际套餐与容量字段，不将付费套餐费用写为零，不购买或补充积分。历史任务保留 Free 计划门禁。
- Signa 保留权限、目标 office、数据新鲜度、真实 usage/credit 字段及请求后检查。新任务不因现有付费套餐、非零积分或 billing_preview 字段而拒绝，但未知／负值容量、权限缺失、非 live office 或配额耗尽仍停止。搜索、详情和媒体共用任务预算，未知提交不重复请求。
- `cost_ceiling_usd=null` 表示没有零费用承诺，不表示费用已核实；实际费用未知时记录 `cost_verified=false`。任何报告不得仅凭来源成功宣称本轮零费用。

创建任务时冻结 `api_first` 的调用预算和 `performance.dynamic_evidence_max_age_hours` 到 `task.retrieval_policy`。有效期必须为正的有限数；后续调度、响应复用及动态事实采信读取同一冻结值。Signa 配置允许 1—3 次，搜索、详情、媒体一起计数；SerpApi 默认 10 次，由搜索、详情、Lens 共享。全局配置变更不扩大已创建任务预算。

v3 Signa 操作配置采用 `v3_supported_operations`，完整集合为 `trademark_search/candidate_detail/trademark_media`。图形、组合、三维类型筛选属于文字及字段查询，不代表图片相似检索。旧 `supported_operations` 保持历史搜索契约。

SerpApi 详情支持 `--attempt-id/--retry-reason`。新尝试先校验原回执与当前恢复审阅；未知提交、未复核失败或已用完恢复次数不得重发。损坏／缺失原件或过期成功响应需要调度器生成准确绑定的修复凭据。新 attempt 重新占额；JPO 数据端点不隐式重试，失败按已有恢复流程处理。

账户策略不改变业务鉴权、凭据文件位置、原始文件完整性、来源操作验收、候选分流、国家适用判断和最终独立双审。离线验证使用合成账户与 loopback，不调用真实账户；新策略尚需在获授权的真实账户上验收。
