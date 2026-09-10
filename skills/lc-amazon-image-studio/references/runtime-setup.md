# 运行环境准备

这是依赖准备入口，不是账户鉴权入口。实际产品分析、策略、生成、编辑、恢复及交付仍按 SKILL.md 原规则，从 skill 根目录执行 `python3 scripts/auth_gate.py`；本节不改变触发时机、凭据、校验或失败停止规则。

## 检查与授权

从 skill 根目录先运行 `python3 scripts/runtime_bootstrap.py inspect --json`。入口只用 Python 标准库，缺 Pillow 也能检查；不安装、不创建缓存或改配置。优先复用环境变量指定、已选择缓存、PATH、Codex bundled runtime 及 Playwright 浏览器缓存中真正满足版本约束的候选；不因第一个候选版本错误就停止搜索。

检查覆盖 `assets/layout-runtime.json` 中锁定的 Pillow、Playwright、Chromium，Node 最低主版本，以及全部内置字体的 SHA-256 和许可证。额外生产依赖 NumPy 在 bootstrap 的独立 `BOOTSTRAP_DEPENDENCIES` 规范中固定为现有冻结基线的 **2.3.5**，不修改原视觉运行时锁。该版本要求 Python ≥3.11；以 [NumPy 官方发布元数据](https://pypi.org/pypi/numpy/2.3.5/json) 为依据，不将 Python 3.10 误判为可安装。

`inspect` 只查版本与文件，完整环境返回 `ready:true` 仍仅表示依赖存在，**不是生产可用结论**。普通完整环境必须继续运行 `python3 scripts/runtime_bootstrap.py verify --json`，实际执行原有 `lc_layout.py --doctor`、Pillow／NumPy／`lc_typography` 导入及真实浏览器启动／页面截图探测；仅 `verified:true` 才进入生产。verify 不安装或写项目状态，浏览器只使用自动清理的临时 profile，截图留在内存。安装完成内部也执行同样验收。环境验证不签发视觉 QA，也不证明云端鉴权通过。

返回字段：

- `ready`：所有依赖满足锁定条件；verify／install 模式还要求运行探测通过。
- `verified`／`verification_required`：inspect 固定为 false／true；verify／install 全部真实探测成功才变为 true／false，禁止仅凭 inspect 的 ready 开工。
- `missing`：缺失、不匹配或损坏项与原因；`installable`：可在用户缓存自动补齐的项。
- `needs_confirmation`：检查发现缺失时提醒 Agent 评估权限；它不是对 Codex 当前权限的探测。Agent 必须以本轮真实权限上下文为准。
- `commands`：skill 工作目录、选定 Python、`LC_LAYOUT_NODE`／`LC_LAYOUT_NODE_MODULES`／`LC_LAYOUT_CHROMIUM`、doctor 完整参数及 pipeline 参数前缀。

当本轮用户已明确授予完全访问，且工具权限允许安装时，自动执行 `python3 scripts/runtime_bootstrap.py install --authorization full-access --json`。不因为全局偏好、以往会话或脚本返回值推断完全访问。

不是完全访问、权限不明确或无法自动安装时，先向用户说明缺失项并询问是否安装；用户明确同意且工具权限允许后，执行 `python3 scripts/runtime_bootstrap.py install --authorization user-confirmed --json`。不能通过确认标记申请或绕过工具越权。省略标记或使用 `unknown`／`restricted` 不安装。

## 隔离安装与失败边界

- macOS／Linux 安装只写 `~/.cache/lc-amazon-image-studio/runtime/<锁摘要>/`；Windows 使用 `%LOCALAPPDATA%\lc-amazon-image-studio\runtime\<锁摘要>\`，缺 LOCALAPPDATA 时使用当前用户的 `AppData\Local`。不改系统 Python、现有 Node、skill 配置或鉴权文件；不使用 sudo、`--break-system-packages` 或远程 shell 安装管道。
- Pillow 与 NumPy 在独立 Python venv 中从 PyPI 安装锁定版本且只接受二进制 wheel。缺可用 Python ≥3.11、venv／ensurepip 不可用或没有适配 wheel 时，停止并向用户确认外部环境准备；不偷偷改系统或源码编译依赖。
- 已有合格 Node 优先复用。确实缺失时，使用官方 Node **v24.21.0 LTS** 的当前平台归档，并从相同官方 HTTPS 发行目录读取 `SHASUMS256.txt`，逐字节核验 SHA-256 后才解压。只处理 macOS／Linux／Windows 的 x64、arm64；不支持的平台须确认其他安装方法。归档不落地符号链接，不接受路径逃逸。该 fallback 不修改原 `node_min_major`。[官方发行状态](https://nodejs.org/en/about/previous-releases)、[官方 v24.21.0 校验清单](https://nodejs.org/dist/v24.21.0/SHASUMS256.txt)（核对日期：2026-09-10）。
- 生产 Playwright 按原锁 **1.62.1** 装入独立 npm 目录，禁用 npm 生命周期脚本。其默认下载清单实际已指向 Chromium 151，不能用来直接补齐冻结的 149。若生产包的浏览器清单不匹配，另在 `browser-installer-*` 缓存安装官方 **playwright-core 1.61.0**，先验证其包版本及 chromium／headless-shell 两项均为 **149.0.7827.55 / revision 1228**，再执行该包内置 `install chromium`。此包仅是下载辅助，不参与生产模块选择；渲染仍为 Playwright 1.62.1 + Chromium 149，不改视觉锁。[官方 1.61.0 浏览器清单](https://github.com/microsoft/playwright/blob/v1.61.0/packages/playwright-core/browsers.json)。
- 安装后真实 Chromium 版本、原 doctor、Python 模块和浏览器运行检查仍须全部通过；未知版本组合或清单不符即停止，不能改清单骗过校验。Linux 缺系统动态库时不执行 `install-deps`／`--with-deps` 或系统包管理器，报告具体错误后征求确认。
- 字体缺失或 SHA-256 不匹配时要求恢复原 skill 资源及许可证，不下载“近似版本”或用系统字体替换；部分内置字体是固定生成产物，源仓库名称不足以证明替代文件字节等价。

安装失败会返回原始步骤的有界脱敏错误、仍缺失的清单和确认方向；不降级版本、质量、字体或验收。`installation_attempted` 表示是否已尝试安装，`installed` 只列成功完成步骤；失败但可能已写入的目录通过 `partial_cache` 给出。已下载的隔离临时文件保留在专用缓存用于诊断，不删除用户文件。只有 doctor、Python 模块和浏览器探测均成功才发布 `selection.json`（仅运行时路径，不存账户或 token）。后续检查重新验证选择，不把缓存当永久放行。

## 后续命令必须使用选定环境

所有后续 pipeline 命令及薄适配中的 Python 子命令，都用本次返回的 `commands.python` 与 `commands.env` 执行，并设置 `commands.cwd`。不要检查时找到 bundled Python、生产时又退回缺 Pillow 的系统 Python；也不要只安装 Chromium 而遗漏其环境路径。

建议由调用方传递 argv 数组和环境字典，不拼接未转义 shell 文本。`commands.doctor_argv` 可直接再次验收，`commands.pipeline_argv_prefix` 后追加 `plan --manifest … --json` 等已有命令。只覆盖返回的 `LC_LAYOUT_*`，不要打印或复制整个进程环境。原鉴权命令保持不变。

## macOS 与 Windows 能力边界

以下为本次明确覆盖的四种环境；模拟测试证明代码路径，不代表已在对应硬件／系统实测。所有平台仍须按真实产品执行原鉴权与逐图 QA，不能以环境通过代替质量审核。

- **macOS Intel x64**：整运行栈的官方 OS 范围为 **macOS 14+**；Node 使用 `darwin-x64` 归档，Python 需受支持的 64 位 Intel／universal2 解释器。归档、SHA 选择、npm 和浏览器路径已做无网络模拟；尚无 Intel 实机结果。
- **macOS Apple Silicon arm64**：同样要求 **macOS 14+**；Node 使用 `darwin-arm64`，优先原生 64 位 Python，避免无说明地混用 Rosetta 环境。本机 Apple Silicon 的版本查找、原 doctor、模块导入和浏览器运行已真实通过；下载／冷安装仍是模拟验证。
- **Windows 11 x64**：符合 Playwright 1.62.1 官方系统要求；Node 采用 `win-x64.zip` 根目录的 `node.exe`，npm 直接由 Node 执行 `node_modules/npm/bin/npm-cli.js`；venv 使用 `Scripts\python.exe`，不调用 `.sh`、shell 激活脚本或系统安装器。路径与命令链已模拟，尚无 Windows 实机结果。
- **Windows 10 x64**：保留相同版本的兼容执行路径，但 **不属于 Playwright 1.62.1 文档列出的官方支持系统**；inspect 会明确提示。Node 本身支持 Windows 10，Chrome 官方目前也仍列 Windows 10，但不能据此推导此 Playwright／Chromium 组合一定可用。只有目标机 `verify` 成功才能继续尝试原生产流程；失败应停下确认，不偷偷降级浏览器或降低 QA。尚无 Windows 10 实机结果，不能把模拟通过写成“已确保运行”。

原鉴权二进制不变，Windows 本次范围是 **x64（AMD64）**，不承诺 Windows ARM、32 位 Windows、WSL 或新平台的完整技能可用性。Mac Node 24.21.0 自身最低 macOS 13.5，但 Playwright 的 macOS 14 下限更高，因此不将 Node 能启动当作整套环境受支持。[锁定 Playwright 1.62.1 系统要求](https://github.com/microsoft/playwright/blob/v1.62.1/docs/src/intro-js.md)、[Node 24.21.0 平台清单](https://github.com/nodejs/node/blob/v24.21.0/BUILDING.md)、[Chrome 系统要求](https://support.google.com/chrome/a/answer/7100626?hl=en)（核对日期：2026-09-10）。

Windows 仅有 `py`／`python` 不等于 Python 不存在。可先 `py -0p` 查看已安装解释器，选其中 64 位 Python ≥3.11；例如已经安装 3.12 时，可用 `py -3.12 -B scripts/runtime_bootstrap.py inspect --json` 启动本节检查，再执行同入口的 `verify --json`。脚本只读解析 `py -0p`，不让 launcher 自动下载 Python；没有任何可用解释器才先请用户确认安装。[Python 官方 Windows 启动器说明](https://docs.python.org/3.12/using/windows.html#python-launcher-for-windows)。

上述 `py` 示例**只针对依赖入口**，不修改或替代原鉴权规则。生产仍必须能执行 SKILL.md 规定的 `python3 scripts/auth_gate.py` 标准入口；若 Windows 尚无 `python3` 命令，先明确报告并处理解释器命令可用性，不假装鉴权已执行、不直接运行二进制，也不擅自创建第二鉴权实现。

Windows 子进程以参数数组启动，`PATH` 使用分号并统一大小写键；Python pipeline／doctor 参数显式启用 UTF-8，避免中文用户目录或文案受系统代码页影响。自动发现同时接受新版 `chrome-headless-shell.exe`、旧 `headless_shell.exe`、全版 `chrome.exe`，Mac 则兼容旧 `Chromium.app` 与 `Google Chrome for Testing.app`。最终实际使用的路径始终以返回的环境为准。

复现无网络平台测试：从 `scripts/` 运行 `python3 -B -m unittest test_runtime_bootstrap -v`；Windows 用已经确认的 Python 启动同一个测试模块即可。下载、安装进程和平台映射使用合成 fixtures／mock；不要把此命令的成功当成 Windows 或 Intel 实机验收。
