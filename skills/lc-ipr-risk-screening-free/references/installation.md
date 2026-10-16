# 安装、分发与平台验收

## 安装边界

解压到接收者可写的 Skill 目录，路径可以含中文和空格。不要覆盖已有凭据或旧任务。使用接收者本机 Python、Node、Google Chrome 和 PDF 工具，不复制发送者的虚拟环境、浏览器配置或系统程序。

macOS 使用 Finder 归档实用工具或系统 `ditto -x -k 包.zip 新目录` 解压，以保留 ZIP 中的文件权限。部分通用解压库会忽略权限，导致空 `.env` 也报 `PRIVATE_PERMISSIONS_REQUIRED`；此时在接收者自己的 Skill 目录执行 `chmod 600 config.json .env` 后重新检查。安装器不会为消除错误而自动修改已有凭据文件的权限，原凭据写入与鉴权规则不变。Windows 使用系统解压或 PowerShell `Expand-Archive`，权限继续按原 Windows 检查执行。

目标环境：macOS 14 及以上的 Intel x64／Apple Silicon ARM64；原生 x64 的 Windows 10 2004（build 19041）及以上、Windows 11 任意版本（此前仅按 Windows 10 22H2、11 24H2／25H2 判兼容；该构建判断只用于安装诊断，不是鉴权门禁，实机验证仍为 not_run）。npm 全局安装的 Codex 只暴露 `codex.cmd`：宿主会在其旁的 `node_modules/@openai/codex` 包内查找原生 `codex.exe`（脚本包装器本身不被接受），仍找不到时用 `--codex-binary` 或 `LC_IPR_CODEX_BINARY` 指定。安装器分别记录宿主架构、Python 进程架构及 Rosetta；Windows ARM、32 位进程、未知系统组合不标为兼容。版本识别成功只表示满足项目目标条件，原生端到端验收另记。

本次完整工作流支持 Python 3.9 及以上、Node 22 及以上，建议选择 Node 22 LTS，并保留实际版本。package.json 的 Node 20 下限仅描述 CDP 组件，不代表完整安装验收基线。Python PDF 依赖为 pypdf==6.10.0；Node 使用包内 package-lock.json 的 playwright-core。Chrome 用系统安装版本，不自动下载浏览器。PDF 页图需要本机 `pdftoppm`（Poppler）可在 PATH 找到，并实际运行成功；Windows 还须具备配套 DLL。（r9 起为可选：美国外观授权 PDF 用 pypdf＋Pillow 取图，`setup_skill.py --check` 不再因缺少 pdftoppm 判为 needs_setup；只有渲染用户自带的 PDF 页时才用它。）

Python 3.9/3.10 缺少内置 `tomllib`，安装器会安装锁定的 `tomli==2.5.0`（官方包元数据要求 Python >=3.8），由 `runtime_compat` 提供原 `tomllib` 导入接口。Python 3.11+ 使用内置解析器；新安装建议 Python 3.12。兼容入口保留已有纯 Python pypdf／tomllib 的限定来源回退，但新机器应在本 Skill 的 `.venv` 完整安装依赖，不能依赖发送者的 Codex 缓存。Pillow 必须安装在实际运行的解释器环境，不借用其他版本的原生扩展。

可先运行本机 Python 的 `scripts/setup_skill.py --check` 获取诊断；初始化和依赖安装完成后，业务与验收命令统一使用此 Skill 的 `.venv` 解释器，不混用系统 Python。`LC_IPR_DEPENDENCY_ROOT` 保留原有显式来源规则，不参与下载和安装。

Windows 10 是本项目需单独实测的兼容目标，不能因带有 Windows 二进制便宣称完整支持。Windows 上的最终双审使用 `report_review_host.py --isolation tool-free-process`（Windows 上 `auto` 即此后端；无内核级读边界，详见 [完整报告双审宿主](report-review-host.md)），需要原生 `codex.exe` 且已用 ChatGPT 登录；该后端已用伪 Codex 可执行文件离线验证，**尚未在 Windows 真机实测**，首次使用前先做一次冒烟：`codex.exe login status`、`codex.exe exec --sandbox read-only --json --ephemeral -` 是否被接受，以及输出事件中是否出现除 `report-review-host.md` 所列以外的启动提示。Playwright 的当前上游系统要求从 Windows 11 起；本 Skill 使用系统 Chrome 的 CDP 路线，Windows 10 仍须独立实际验证。

## r9 补充：分享给 Mac／Windows 使用者

- 只分享 `scripts/package_skill.py` 生成的干净包（`-package-` 包），不要分享含真实 key 的工作副本；不要用 Finder 重新压缩技能目录。
- Python 建议 3.10 及以上（3.12 最好）。Mac 自带的 3.9 能运行，但网络超时处理较弱，`--check` 会提示。
- Windows：
  - 先设一次用户环境变量 `setx PYTHONUTF8 1`，然后重开终端。鉴权入口和结束保护钩子在中文代码页下需要它。
  - 不要用 Microsoft Store 版 Python：它把临时文件写到私有位置，Codex 审阅读不到，`--check` 会提示。请装 python.org 的 Python。
  - 鉴权程序被 SmartScreen 或 Defender 拦下时，用 `Unblock-File tools\bin\*.exe` 解除。
  - 任务目录尽量短（例如 `C:\ipr\<ASIN>-US`）：最深的文件路径约 210 个字符，接近 Windows 260 字符的默认上限。
  - Windows 的睡眠时间会计入分析时长，跑任务请接电源。
- 国内安装依赖慢时，在运行 `--install-deps` 前设镜像：`PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`（PowerShell：`$env:PIP_INDEX_URL="..."`）。
- Codex：Mac 上用 npm 安装的 Codex 也能自动找到（到 `@openai/codex` 包里找原生程序）。终审固定使用 `references/review-host.json` 里的模型，ChatGPT 账号需要能用这个模型；不可用时流水线输出 `model_notice`。
- 网络：开代理的 TUN（增强）模式或“系统代理”都可以，fake-IP 已自动兼容。Codex 请求联网授权时，允许 `run_pipeline.py` 联网。`setup_skill.py --check-network` 会报告 DNS、正在用的代理，以及与 Google 专利网站的 TLS 握手是否成功。

## 初始化与依赖

进入解压后的 Skill 根目录，包内已预置各字段值为空的 `.env`，可以直接填写自己的第三方 API Key。Mac Finder 按 `⌘ + Shift + .` 显示隐藏文件；包内 `config.json` 的后台 token 也留空，不附带示例文件。初始化只补建缺失的空 config.json／.env，已有字节与权限不改：

macOS：

```bash
python3 -X utf8 scripts/setup_skill.py --init
python3 -X utf8 scripts/setup_skill.py --install-deps
.venv/bin/python -X utf8 scripts/setup_skill.py --check
```

Windows PowerShell：

```powershell
# 检查本机默认 Python；须为 3.9+，建议 3.12。
py -3 --version
py -3 -X utf8 scripts/setup_skill.py --init
py -3 -X utf8 scripts/setup_skill.py --install-deps
& .\.venv\Scripts\python.exe -X utf8 scripts/setup_skill.py --check
```

没有 `py` 启动器时可使用 `python --version` 检查已有解释器，并把上述两条 `py -3` 命令替换为 `python`；不要把 `py -3` 当成 `--python` 的程序路径。选择特定解释器时传 `--python "C:\完整路径\python.exe"`。虚拟环境创建后仍使用 `.venv\Scripts\python.exe`。

`--install-deps` 在本 Skill 创建 .venv 并按锁文件安装 Node 依赖，不使用全局 pip，不替换已有不兼容虚拟环境，不安装系统 Python／Node／Chrome／Poppler。缺少系统工具时，根据诊断先安装该工具再重试；不复制发送者的绝对路径。依赖安装会访问官方包仓库，不携带本 Skill 的后台或来源凭据。

填写自己的后台 Token 和第三方 Key。后台配置覆盖、环境变量优先级及来源选择见 [启动门禁](../INSTRUCTIONS.md#2-本地配置与凭据)。新配置留空时 `--check` 会报告 needs_setup，属于预期结果；ready_for_auth 只表示可继续鉴权，不代表鉴权已通过或 API 账号可用。

## 原生模型运行环境

接收者需要 Codex 桌面版及其本机原生 CLI。发现顺序为：调用者 `--codex-binary`、环境变量 `LC_IPR_CODEX_BINARY`、已安装桌面应用内程序、PATH 中的原生程序。Mac 检查 `/Applications` 和当前用户 `~/Applications` 中的 ChatGPT／Codex 应用；Windows 只读查询当前用户 OpenAI 应用包位置，并检查当前用户常见安装目录。不会复制发送者的二进制或登录文件。自动候选逐个使用 `--version`、`exec --help`、`features list` 检查必要能力，选第一份兼容程序；显式路径无效或能力不符就报错，不自动回退。脚本包装器（包括 `codex.cmd`、PowerShell 和 JS 启动脚本）不能充当原生 CLI。

`setup_skill.py --check` 的 `native_review` 独立报告可执行文件、版本、必要参数和隔离特性。`cli_capable` 只表示这台机器的 CLI 接口满足静态能力检查；登录、模型账户可用性与图片输入仍未实测。检查只执行 `--version`、`exec --help`、`features list`，不执行登录、真实鉴权或模型请求，也不改变 `ready_for_auth` 的原有含义。缺少能力时显示明确待办，不自动降低隔离要求或更换默认模型。

本机模型执行仍须验证现有 ChatGPT 登录、授权模型与视觉输入；原有登录检查和双审隔离规则保持不变。安装检查不能代替原生完整工作流验收。

BOM／CRLF 在配置读取时兼容；Skill 自产 JSON、HTML、CSS 和原生日志明确以 UTF-8 读取，不依赖系统默认代码页。外部原件保留各自原有解码与损坏拒绝规则；文件写入使用 UTF-8。建议命令始终使用 `-X utf8`，避免旧 Windows 终端或重定向以本地代码页编码。Python 子进程和离线验收入口也明确使用 UTF-8；不要在命令行传入 Token 或 Key。

默认任务目录位于当前用户目录；显式 `create_task.py --output-dir` 和既有报告输出目录参数仍优先。旧任务不迁移。Chrome 路径可通过 `LC_IPR_CHROME` 或运行配置选择，Python 路径可通过 `LC_IPR_PYTHON` 指定本机解释器；路径值只选择程序，不改变鉴权或来源授权。

## 接收者检查

结束保护需另按[结束保护与断点恢复](continuation-guard.md)安装并由用户原生信任。Python 离线通过不等于桌面 Stop 钩子生效；未完成桌面冒烟时明确标“保护未启用”。

1. 执行 setup 的 --check，保留脱敏安装诊断。仅有 Key 不证明该来源获授权、账户容量足够或生产审批通过。
2. 用自己的 Token 执行 auth_gate.py；首次业务鉴权通过后创建任务，credentials 预检仍再次鉴权。
3. 以新目录做本机 Chrome/CDP、PDF 页渲染、中文空格路径及跨进程锁测试；Rosetta 结果不能当成 Intel 真机结果。
4. 依次执行 `scripts/verify_skill.py --mode fast --output-dir 新目录` 和 `--mode release --output-dir 另一个新目录`。release 必须同时生成历史样本和 `operator-report-v1` 实际交付样本，并在 390、580、768、900、1440 像素宽度验收；缺少样本、政策版本错误或版面不通过会整体失败，不接受跳过布局检查；这些离线测试不代表真实来源查询已跑通。
5. 用接收者明确授权的来源做有限真实查询，保存脱敏回执。Serper 的余额使用授权由接收者的新任务来源启用选择冻结，不继承发送者授权；EUIPO 本轮暂停。

## 联网权限与恢复

- 安装准备和实际鉴权前读取宿主提供的当前网络权限；已允许访问配置后端时直接执行原 auth_gate.py，不重复申请。网络明确关闭或目标主机受限时，使用宿主网络权限入口仅申请实际 backend_url 的主机（默认 mcp.yixunkuajing.com）。不读取、回显或通过命令参数传递 Token／Key 来判断网络权限，不新增独立业务／鉴权探测命令。网页、搜索、浏览器或 MCP 可用不证明 Python／Go 子进程可联网。
- 宿主禁止申请或管理员拒绝时，说明受限主机及恢复条件，保持鉴权门禁。不得自行修改全局权限、改代理、关闭 TLS 校验或更换鉴权接口。维护和离线测试不调用真实账户。
- 鉴权失败仍原样展示入口两行安全原因并停止业务。service_unavailable／超时可能来自网络权限、DNS/TLS/代理或服务故障，不能据此判定 Token 无效；invalid_token、permission_missing 等账户／Skill 拒绝仍按原原因处理，不公开原始响应或日志。网络权限获批或连接恢复后可重新执行原 auth_gate.py 一次，再失败就保留原因和恢复条件；脚本、20 秒超时、两次鉴权及冻结成功条件均不改变。
- 第三方 API 只对当前任务已授权且账户容量条件已满足的来源主机申请网络权限；历史免费任务继续核对免费额度与零支出。API key 已填入 .env 只证明本地配置存在，不等于网络、账号、来源授权或余额验收成功；不为测试联网调用未启用来源。
- 来源失败后的恢复沿用 [来源规则](providers.md#请求与重试安全)：先核对原请求、回执与提交状态。明确未提交且恢复条件变化的动作按原有界恢复规则执行；超时或提交未知不得盲目重提，额度、attempt_id 和任务上限不因网络授权而清零。保留未完成项，不把失败当作零结果或排除证据。
- 接收者需要分别验证本机网络访问及本人账户的真实鉴权／已授权来源调用。合成凭据、loopback 与沙箱恢复用例不代表接收者公网或真实召回已经验收。

## 无密钥打包

使用包内 `scripts/package_skill.py --output-dir 新空目录`。它按 [明确文件清单](distribution-files.json) 读取所需文件，在独立暂存目录检查空模板、已知秘密值和机器路径，生成逐文件 SHA-256 清单并原子生成 ZIP。包内及安装根目录的 `DISTRIBUTION-MANIFEST.json` 是发行文件基准，空凭据项仅表示发行模板，不能作为接收者当前配置验收或凭据哈希。安装升级同步该发行基准，保留接收者凭据原字节。新增业务文件需经审阅后显式加入清单，不能通过递归“全目录打包”带入用户状态。

分发不含发送者真实 config.json、config.local.json、.env、任务、报告、日志、浏览器会话、虚拟环境、额度账本或账户证明。包内 `config.json` 和 `.env` 由 scripts/credential_defaults.py 的固定空字段在暂存目录生成，权限记录为 0600，来源与文件哈希纳入清单；不复制本机现用 `.env`。历史文档中的发送者本机恢复路径只在暂存副本中脱敏；不会修改发送者原文，也不会提供不可用的接收者恢复命令。最终 ZIP 解压后应从空配置开始；不要附送个人凭据来“方便使用”。

修改 Skill 后先运行 `scripts/verify_skill.py --mode fast --output-dir <新目录>`，交付前运行 `--mode release`（release 还需要系统 Chrome 与浏览器版面验收）；在没有系统 Chrome 的环境里 `tools/cdp` 中依赖 Chrome 的用例会失败，属环境原因，须在有 Chrome 的机器上复核。改动 `codex_guard.py`／`completion_check.py` 后，需重新运行 `scripts/install_codex_guard.py` 并在 Codex `/hooks` 重新信任。

交付验收记录必须区分：代码／离线测试、本机原生实测、独立账号真实查询、仍待验收的平台。未取得 Windows 或 Intel 真机结果时明确记待验收，不能用 mock 覆盖或 Rosetta 代替。

图片解码依赖与 pypdf 一并由本地虚拟环境安装：Python 3.9 使用 Pillow 11.3.0，Python 3.10+ 使用 Pillow 12.3.0，保持原 Python 3.9 最低版本；setup_skill 和 verify_skill 检查实际运行环境。
