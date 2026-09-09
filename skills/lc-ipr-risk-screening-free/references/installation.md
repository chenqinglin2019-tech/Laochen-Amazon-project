# 安装、分发与平台验收

## 安装边界

解压到接收者可写的 Skill 目录，路径可以含中文和空格。不要覆盖已有凭据或旧任务。使用接收者本机 Python、Node、Google Chrome 和 PDF 工具，不复制发送者的虚拟环境、浏览器配置或系统程序。

目标环境：macOS 14 及以上的 Intel x64／Apple Silicon ARM64；Windows 10 22H2 x64、Windows 11 24H2／25H2 x64。安装器分别记录宿主架构、Python 进程架构及 Rosetta；Windows ARM、32 位进程、未知系统组合不标为兼容。版本识别成功只表示满足项目目标条件，原生端到端验收另记。

本次完整工作流要求 Python 3.12 及以上、Node 22 及以上，建议选择 Node 22 LTS，并保留实际版本。package.json 的 Node 20 下限仅描述 CDP 组件，不代表完整安装验收基线。Python 依赖只安装既有 pypdf；Node 使用包内 package-lock.json 的 playwright-core。Chrome 用系统安装版本，不自动下载浏览器。PDF 页图需要本机 `pdftoppm`（Poppler）可在 PATH 找到，并实际运行成功；Windows 还须具备配套 DLL。

Windows 10 是本项目需单独实测的兼容目标，不能因带有 Windows 二进制便宣称完整支持。Playwright 的当前上游系统要求从 Windows 11 起；本 Skill 使用系统 Chrome 的 CDP 路线，Windows 10 仍须独立实际验证。

## 初始化与依赖

进入解压后的 Skill 根目录，包内已预置各字段值为空的 `.env`，可以直接填写自己的第三方 API Key。Mac Finder 按 `⌘ + Shift + .` 显示隐藏文件；`.env.example` 保留为恢复模板。初始化只补建缺失的空 config.json／.env，已有字节与权限不改：

macOS：

```bash
python3.12 -X utf8 scripts/setup_skill.py --init
python3.12 -X utf8 scripts/setup_skill.py --install-deps
.venv/bin/python -X utf8 scripts/setup_skill.py --check
```

Windows PowerShell：

```powershell
py -3.12 -X utf8 scripts/setup_skill.py --init
py -3.12 -X utf8 scripts/setup_skill.py --install-deps
& .\.venv\Scripts\python.exe -X utf8 scripts/setup_skill.py --check
```

`--install-deps` 在本 Skill 创建 .venv 并按锁文件安装 Node 依赖，不使用全局 pip，不替换已有不兼容虚拟环境，不安装系统 Python／Node／Chrome／Poppler。缺少系统工具时，根据诊断先安装该工具再重试；不复制发送者的绝对路径。依赖安装会访问官方包仓库，不携带本 Skill 的后台或来源凭据。

填写自己的后台 Token 和第三方 Key。后台配置覆盖、环境变量优先级及来源选择见 [启动门禁](../INSTRUCTIONS.md#2-本地配置与凭据)。新配置留空时 `--check` 会报告 needs_setup，属于预期结果；ready_for_auth 只表示可继续鉴权，不代表鉴权已通过或 API 账号可用。

BOM／CRLF 在配置读取时兼容；文件写入使用 UTF-8。建议命令始终使用 `-X utf8`，避免旧 Windows 终端或重定向以本地代码页编码。Python 子进程和离线验收入口也明确使用 UTF-8；不要在命令行传入 Token 或 Key。

默认任务目录位于当前用户目录；显式 `create_task.py --output-dir` 和既有报告输出目录参数仍优先。旧任务不迁移。Chrome 路径可通过 `LC_IPR_CHROME` 或运行配置选择，Python 路径可通过 `LC_IPR_PYTHON` 指定本机解释器；路径值只选择程序，不改变鉴权或来源授权。

## 接收者检查

1. 执行 setup 的 --check，保留脱敏安装诊断。仅有 Key 不证明该来源获授权、免费额度足够或生产审批通过。
2. 用自己的 Token 执行 auth_gate.py；首次业务鉴权通过后创建任务，credentials 预检仍再次鉴权。
3. 以新目录做本机 Chrome/CDP、PDF 页渲染、中文空格路径及跨进程锁测试；Rosetta 结果不能当成 Intel 真机结果。
4. 依次执行 `scripts/verify_skill.py --mode fast --output-dir 新目录` 和 `--mode release --output-dir 另一个新目录`。release 不接受跳过布局检查；这些离线测试不代表真实来源查询已跑通。
5. 用接收者明确授权的来源做有限真实查询，保存脱敏回执。Serper 的余额使用授权需接收者重新确认；EUIPO 本轮暂停。

## 无密钥打包

使用包内 `scripts/package_skill.py --output-dir 新空目录`。它按 [明确文件清单](distribution-files.json) 读取所需文件，在独立暂存目录检查空模板、已知秘密值和机器路径，生成逐文件 SHA-256 清单并原子生成 ZIP。新增业务文件需经审阅后显式加入清单，不能通过递归“全目录打包”带入用户状态。

分发不含发送者真实 config.json、config.local.json、.env、任务、报告、日志、浏览器会话、虚拟环境、额度账本或账户证明。包内 `.env` 在暂存目录从已校验的空 `.env.example` 生成，权限记录为 0600，来源与文件哈希纳入清单；不复制本机现用 `.env`。历史文档中的发送者本机恢复路径只在暂存副本中脱敏；不会修改发送者原文，也不会提供不可用的接收者恢复命令。最终 ZIP 解压后应从空配置开始；不要附送个人凭据来“方便使用”。

交付验收记录必须区分：代码／离线测试、本机原生实测、独立账号真实查询、仍待验收的平台。未取得 Windows 或 Intel 真机结果时明确记待验收，不能用 mock 覆盖或 Rosetta 代替。
