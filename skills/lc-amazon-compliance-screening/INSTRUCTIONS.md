# 云端权限前置

本技能使用独立权限 `amazon_compliance_screening`，通过现有 `/auth/skill-check` 查询。
需要有效 Token、启用账户、正余额、启用的技能及用户权限；查询不扣积分。

## 每次调用

1. 选择可用的 Python 3.9+，运行 `<Python> <Skill目录>/scripts/auth_gate.py`。不要求切换工作目录。
2. 只有输出 `{"ok":true,"message":"auth_passed"}` 且退出码为 0 才继续 SKILL.md 的业务流程。
3. 失败时转述 JSON 的 `error`（固定停止语及安全原因），立即停止，不处理商品输入、访问网页或生成业务文件。

鉴权脚本按当前平台选择 `tools/bin/` 下的 Go 程序，校验 tools/auth.json 中的 SHA-256 后执行。
支持 macOS Intel/Apple Silicon、Linux x64、Windows x64；其它平台会拒绝。
macOS 若系统隔离阻止已核验来源的二进制运行，按宿主工具的安装规则处理，不能把执行失败当作授权成功。
独立执行 `scripts/csc.py` 的业务命令也会重新鉴权，不复用上次成功状态。
帮助及 `doctor` 是离线诊断入口，不代表云端权限通过。

## Token 和配置

- 优先使用当前进程的 `LAOCHEN_BACKEND_TOKEN`，否则读取配置中的 `backend_token`。
- `config.json` 仅包含 `backend_url` 和 `backend_token`，随包 Token 必须为空；用户可在技能根目录的私有 `config.local.json` 中配置自己的 Token。
- `tools/auth.json` 保存内部超时和四平台二进制摘要，由构建流程维护，用户无需修改。
- `config.local.json` 只允许 `backend_token`、`backend_url`，不进入 Git 或发行清单。
- 后端地址默认 `https://mcp.yixunkuajing.com`。仅本地隔离测试允许回环 HTTP；远程地址必须使用 HTTPS，鉴权请求不跟随重定向。
- 不把 Token 放入命令行参数、任务资料、日志或报告。不要使用其它用户的 Token。

缺 Token、停用、零余额、缺权限、服务异常或二进制损坏均停止。离线状态不能运行业务命令。
此机制约束官方包正常流程，不防止用户修改本地源码或规则文件。
