# LC IPR Risk Screening Free 启动门禁

本文件规定本地配置初始化与老陈云端鉴权。鉴权通过后，严格按 `SKILL.md` 执行原有知识产权排查流程，不改变其业务规则。

这里的调用指实际商品排查业务。开发、审计、测试或恢复 Skill 文件不执行业务鉴权；离线测试须使用模拟或 loopback 来源及临时虚拟凭据，父子进程均不得读取真实本地凭据文件，不借测试模式访问真实账号。

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

`scripts/auth_gate.py` 会选择当前平台的专用 Go 二进制，并按 `references/runtime-config.json` 中的 SHA-256 校验后执行。

## 2. 本地配置与凭据

运行时只从 Skill 根目录的本地文件读取配置和凭据：

- `config.json` 严格只包含 `backend_url`、`backend_token` 两个字符串字段。后台 Token 只读取这里的 `backend_token`。
- `.env` 保存第三方 API Key、Client ID、Secret、用户名和密码；完整的 12 个字段见 [.env.example](.env.example)。缺少或留空的可选凭据仅影响对应来源。
- `references/runtime-config.json` 保存版本、来源规则、浏览器参数、执行限制和鉴权组件 SHA-256 等非秘密设置。Python 与浏览器端共用该文件；`load_skill_config()` 返回运行设置及后台地址，不携带 Token。

`credential(config, name)` 按凭据类型读取对应文件，不从进程环境变量、Keychain 或 `config.local.json` 回退。测试开关、超时等非凭据环境变量仍有效；`.env` 作为文本解析，不执行 shell、不展开变量，也不修改进程环境。

首次安装时从 [config.example.json](config.example.json) 初始化 `config.json`，填写本 Skill 的后台地址和 Token；从 `.env.example` 初始化 `.env`，仅填写已有且获授权使用的凭据。已有文件不得被模板覆盖；不可复用其他 Skill 的 Token。

macOS/Unix 上将 `config.json` 与 `.env` 权限设为 `0600`。文件缺失、格式错误、重复键、字段类型错误或权限不符须输出脱敏原因；后台配置不可用则停止业务鉴权，可选来源凭据不可用则保留相应来源缺口。

迁移本 Skill 旧安装时，仅一次性将既有固定 Keychain 项中的后台 Token 写入 `config.json`，保留已有 `.env` 值；缺失值留空。完成迁移后删除只含重复后台地址的 `config.local.json`，运行时不再访问 Keychain，也没有双配置覆盖机制。

本地 `config.json`、`.env` 均排除出版本控制和分发包。分发时保留空 Token 的 `config.example.json`、空值的 `.env.example` 与不含凭据的 `references/runtime-config.json`；打包前显式排除两个本地凭据文件，不能仅依赖 `.gitignore`。不得把完整 Token、Key、用户名、密码或会话 Cookie 写入命令行、运行目录、日志、报告或回复。

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
