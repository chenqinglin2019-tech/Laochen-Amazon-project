# LC IPR Risk Screening Free 启动门禁

本 Skill 的云端鉴权以用户指定的原始 `lc-ipr-risk-screening-free-auth-gated-20260811(1).zip` 为唯一基准。协议、四个平台组件及验证基线见 [鉴权冻结契约](references/auth-contract.md)。API 优先检索、双审、发布门禁和报告内容及布局保持现有规则。

## 1. 强制第一步

每次实际商品排查，第一条业务命令必须执行 `scripts/auth_gate.py`。通过前不解析 ASIN、图片等业务输入，不打开 Amazon/CDP，不调用第三方来源，不创建业务任务。鉴权通过后按 [SKILL.md](SKILL.md) 执行；创建任务后的 `preflight.py --phase credentials` 仍再次鉴权，不因首次通过而跳过。

安装准备、开发、审计、恢复文件和离线测试不属于商品排查，不要求先调用真实鉴权。离线测试使用临时假凭据及模拟／loopback 来源，父子进程不得读取真实凭据或访问真实账号。

先按 [安装与平台验收](references/installation.md) 准备本机依赖，再在 Skill 根目录使用同一 Python 环境运行：

```bash
python scripts/auth_gate.py
```

这里的 `python` 指安装检查确认的解释器；macOS 通常为 `.venv/bin/python`，Windows 为 `.venv\Scripts\python.exe`。入口选择当前平台组件，核对 `references/runtime-config.json` 的 SHA-256 后执行。macOS 保留针对已校验当前组件的执行权限及下载隔离标记准备，不递归清理目录或关闭系统安全设置。

## 2. 本地配置与凭据

后台鉴权和第三方 API 凭据分开读取：

- 后台 Token 优先使用**非空进程环境变量 `LAOCHEN_BACKEND_TOKEN`**；否则使用 `config.json` 与 `config.local.json` 合并后的 `backend_token`。`config.local.json` 覆盖 `config.json` 的同名字段，保留原包行为。不要删除接收者已有覆盖文件。
- 后台地址来自上述合并配置的 `backend_url`。初始化模板为 `https://mcp.yixunkuajing.com`，请求固定 `/auth/skill-check`，固定 `skill_id=ipr_risk_screening_free`。不改成账户余额接口，不调用业务接口代替鉴权。
- 第三方 API Key、Client ID、Secret、用户名和密码只从本 Skill 根目录 `.env` 读取，沿用 [.env.example](.env.example) 的 12 个字段；不回退到其它 Skill、进程环境或 Keychain。缺少或留空只影响相应来源。
- `references/runtime-config.json` 保存非秘密运行规则、额度、浏览器参数及组件哈希。旧后台配置中其它业务字段不覆盖这里的新检索规则。

分发包根目录已附带列出 12 个字段、值全部留空的 `.env`，接收者直接在等号后填写自己的凭据。Mac Finder 按 `⌘ + Shift + .` 显示该隐藏文件。用 `setup_skill.py --init` 仅补建缺失的空 `config.json` 和 `.env`；已有文件不覆盖、不搬迁、不自动更换权限。macOS/Unix 的新私密文件使用 `0600`；Windows 使用当前用户目录权限，不将 POSIX 位检查冒充 Windows ACL 校验。`.env` 作为 UTF-8 文本解析，支持 BOM、CRLF，不执行 shell、不展开变量或修改进程环境。

接收者填写自己的后台 Token 和获准使用的第三方凭据。Key 已配置不代表来源获得授权、生产审批通过或仍有免费额度；创建任务时仍按来源规则明确选择。Serper 可以由接收者明确授权使用现有余额，不继承发送者的授权、余额证明或额度账本。EUIPO 本轮暂停，不自动测试或启用。

禁止把完整 Token、Key、用户名、密码或 Cookie 写入命令行、任务、日志、报告或回复。发送者的 `config.json`、`config.local.json`、`.env` 不进入分发包；包内空 `.env` 仅由校验通过的 `.env.example` 在暂存目录生成，不能复制发送者现用文件。配置值不得用来生成公开调试信息。

## 3. 失败与成功

原包成功条件、超时和退出行为不改。鉴权失败时，Agent 原样展示入口已过滤的两行停止信息，不省略原因、不输出原始服务响应。例如：

```text
云端鉴权未通过，本轮不继续执行。
原因：当前账户缺少本 Skill 权限。
```

原因以程序实际输出为准，包含原包的 Skill 未登记、Skill 停用、权限缺失／未启用，以及 Token、账户、余额、限流、服务、配置和组件错误。立即停止本轮业务，不绕过或伪造成功；仍可执行不依赖业务鉴权的开发排错。

本次恢复只改变前端调用与原包的对齐，不改变后端授权状态；有效 Token 仍须获得此 Skill 的后台权限。鉴权不扣业务积分，也不采用新增会话缓存。此门禁约束官方分发包正常执行流程，不是不可绕过的 DRM。
