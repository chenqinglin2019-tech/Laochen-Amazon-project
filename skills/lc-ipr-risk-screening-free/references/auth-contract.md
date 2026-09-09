# 原包鉴权冻结契约

唯一来源：`lc-ipr-risk-screening-free-auth-gated-20260811(1).zip`，SHA-256 `f61510d4a55b0da503b30d81ad598d85fbc5b7611796d7388bb75169d8d5c04f`。不再参考 Listing 鉴权、账户接口或其它文件夹版本。

## 保持的鉴权行为

- 原包四个 Go 组件逐字节恢复，不重新编译；对应哈希、协议字段与冻结代码摘要见 [机器校验基线](../scripts/fixtures/auth-contract-20260811.json)。
- 原生组件执行 `POST /auth/skill-check`，JSON `api_key` 携带 Token，`skill_id` 固定 `ipr_risk_screening_free`。HTTP 200、`allowed: true` 且去除首尾空白后的 `reason` 为大小写精确的 `permission_enabled` 才通过；不另写一套成功判断。
- 默认超时 20 秒，无新增自动重试或会话缓存。每次业务首次鉴权和 credentials 预检再次鉴权均保留。只有原有两个显式测试开关同时匹配时保留测试跳过，离线入口另隔离真实凭据。
- 非空进程 `LAOCHEN_BACKEND_TOKEN` 优先；否则 `config.local.json` 覆盖 `config.json`，使用合并后台 Token。保持原包非空及字符串转换行为，不以新来源配置规则拒绝原包合法后台配置。
- 保留 Skill 未登记、已停用、权限缺失、权限未启用等原有安全原因。预检只传递允许的两行安全信息，任务错误状态保持原样。

## 安装和配置适配

当前 Python 入口保留已验证组件的 macOS 启动准备、UTF-8 子进程传输和临时配置清理。这些适配不改变云端请求、成功条件、权限或扣费行为；组件准备失败使用单独的脱敏启动原因。实际鉴权由原包二进制负责。

后台合并配置仅供应鉴权地址与 Token，旧包其它业务设置不覆盖现代 API 优先检索规则。第三方 12 个凭据只读取本 Skill 的 `.env`；不恢复旧版第三方 Key 搜索路线，不继承发送者来源使用授权或额度状态。

## 验证与维护

`scripts/test_auth_binary_contract.py` 校验四个组件、运行哈希及代码冻结摘要，并在具备隔离条件的 macOS 运行假 Token／loopback 原生响应案例。其它平台的静态／mock 结果不冒充原生执行。原包与优化版 Python 入口差分记录随本次交付验收结果提供。

今后修改检索、报告或来源适配时不应修改本冻结基线来掩盖鉴权变化。确需改变鉴权时，先取得用户明确的新基准，再做请求、响应、配置优先级及重复鉴权对照。本次无后端代码改动。
