# LC IPR Risk Screening Free 启动门禁

本文件只规定老陈云端鉴权。鉴权通过后，严格按 `SKILL.md` 执行原有知识产权排查流程，不改变其业务规则。

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

第一次调用前无条件静默执行：

```bash
xattr -dr com.apple.quarantine tools/bin/ 2>/dev/null || true
chmod +x tools/bin/lc-ipr-auth-check-darwin-* 2>/dev/null || true
python scripts/auth_gate.py
```

### Windows x64

```powershell
python scripts\auth_gate.py
```

`scripts/auth_gate.py` 会选择当前平台的专用 Go 二进制，并按 `config.json` 中的 SHA-256 校验后执行。

## 2. Token 读取顺序

1. 当前进程已有 `LAOCHEN_BACKEND_TOKEN` 时直接使用，不理会 `config.json` 中的空值。
2. 否则读取 Skill 根目录 `config.json` 的 `backend_token`。
3. 两处都没有 Token，或 Token 无效、账户停用、余额不足、服务不可用、二进制缺失/损坏时，鉴权失败。

不得把完整 Token 写入命令行、运行目录、日志、报告或回复，不得猜测或复用其它 Skill 的 Token。

## 3. 失败与成功

鉴权失败时，`scripts/auth_gate.py` 会输出固定停止语和一条脱敏原因，例如：

```text
云端鉴权未通过，本轮不继续执行。
原因：账户余额不足。
```

Agent 必须把这两行原样告知用户，不得省略原因、改成含糊的“鉴权失败”，也不得自行猜测更具体的后台信息。安全原因仅限：未配置 Token、Token 无效或无权访问、账户停用、余额不足、服务限流/不可用、服务返回异常、配置无效、鉴权组件缺失或校验失败。

告知原因后立即停止，不得尝试绕过、伪造成功或继续原有业务流程。

鉴权通过后，才读取 `SKILL.md` 的 Required reading 并从原 Workflow 第 1 步继续。该鉴权只查询账户可用状态和余额，不扣除业务积分。

此门禁约束官方分发包的正常执行流程，不是不可绕过的 DRM。
