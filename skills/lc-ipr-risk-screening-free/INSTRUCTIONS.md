# LC IPR Risk Screening Free 启动门禁

本文件只规定老陈云端鉴权。鉴权通过后，严格按 `SKILL.md` 执行原有知识产权排查流程，不改变其业务规则。

这里的调用指实际商品排查业务。开发、审计、测试或恢复 Skill 文件不执行业务鉴权；离线测试须使用模拟或 loopback 来源，不借测试模式访问真实账号。

## 1. 强制第一步

每次调用本 Skill，第一条业务命令必须执行云端鉴权。鉴权之前不得：

- 解析或核对用户的 ASIN、Amazon URL、图片及其它业务输入。
- 读取业务 reference、打开 Amazon、启动 Chrome/CDP 或调用第三方服务。
- 创建任务目录、运行 `scripts/create_task.py` 或写入任何业务文件。

先进入 Skill 根目录，再按当前平台准备二进制：

### Linux x64

```bash
chmod +x tools/bin/lc-ipr-auth-check-linux-amd64
python scripts/auth_gate.py
```

### macOS Intel / Apple Silicon

执行当前平台的鉴权入口；入口先核对二进制 SHA-256，再设置该文件执行权限：

```bash
python scripts/auth_gate.py
```

若系统隔离标记导致已核验的当前平台组件无法执行，仅针对该组件处理，不递归解除整个目录的隔离标记。

### Windows x64

```powershell
python scripts\auth_gate.py
```

`scripts/auth_gate.py` 会选择当前平台的专用 Go 二进制，并按 `config.json` 中的 SHA-256 校验后执行。

## 2. Token 读取顺序

1. 当前进程已有 `LAOCHEN_BACKEND_TOKEN` 时直接使用。
2. macOS 上否则读取固定 Keychain 项：service `com.laochen.codex.lc-ipr-risk-screening-free`、account `LAOCHEN_BACKEND_TOKEN`。
3. 非 macOS 不使用本地文件回退，只允许环境变量。两处都没有 Token，或 Token 无效、账户停用、余额不足、服务不可用、二进制缺失/损坏时，鉴权失败。

`config.json` 与 `config.local.json` 都不是凭据来源；即使其中残留非空 `backend_token`，运行时也必须忽略并由预检报告。运行时非秘密设置仅加载 `config.json`；`config.local.json` 中兼容保留的 `backend_url` 不构成生效覆盖。在 macOS 中录入时使用末尾无明文参数的交互式命令：

```bash
security add-generic-password -U -s com.laochen.codex.lc-ipr-risk-screening-free -a LAOCHEN_BACKEND_TOKEN -w
```

不要把密码追加在 `-w` 后面。任何曾写入配置文件、日志或命令参数的后台 Token 都应在后台管理端轮换；本 Skill 不能代替用户轮换外部凭据。

不得把完整 Token 写入命令行、运行目录、日志、报告或回复，不得猜测或复用其它 Skill 的 Token。

## 3. 失败与成功

鉴权失败时，`scripts/auth_gate.py` 会输出固定停止语和一条脱敏原因，例如：

```text
云端鉴权未通过，本轮不继续执行。
原因：账户余额不足。
```

Agent 必须把这两行原样告知用户，不得省略原因、改成含糊的“鉴权失败”，也不得自行猜测更具体的后台信息。安全原因仅限：未配置 Token、Token 无效或无权访问、账户停用、余额不足、服务限流/不可用、服务返回异常、配置无效、鉴权组件缺失或校验失败。

告知原因后立即停止，不得尝试绕过、伪造成功或继续原有业务流程。

鉴权通过后，从 [SKILL.md 的执行流程](SKILL.md#执行流程) 第 1 步继续。该鉴权只查询账户可用状态和余额，不扣除业务积分。

此门禁约束官方分发包的正常执行流程，不是不可绕过的 DRM。
