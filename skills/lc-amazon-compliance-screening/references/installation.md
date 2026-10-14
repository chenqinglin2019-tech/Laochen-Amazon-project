# 安装与跨平台使用

本包适用于支持 Skill 和本地脚本执行的 AI 工具。AI 负责读取资料和语义分类，Python 负责规则计算；不是双击即可完成语义筛查的独立应用。网页读取使用宿主已有工具；业务调用需要用户自己的老陈访问 Token 和本技能权限，配置见 [INSTRUCTIONS.md](../INSTRUCTIONS.md)。

## 1. 解压与选择 Python

将 ZIP 中的整个 `lc-amazon-compliance-screening` 目录放到宿主支持的 Skill 安装位置，保留目录结构。不得只复制 SKILL.md。任务输入与输出放在另外的工作目录，升级时替换 Skill 目录即可。

优先使用宿主提供的 Python。否则探测可用命令：macOS 可检查 `python3`、`python`；Windows PowerShell 可检查 `py -3`、`python`。以命令实际返回的版本和 `sys.executable` 为准，不以命令存在为准。要求 Python 3.9+，推荐 3.12。无可用解释器时先从 Python 官方安装或使用宿主运行环境，不自动安装全局 Python。

macOS（zsh/bash），探测后把 Python 设置为输出的真实可执行文件路径：

```sh
python3 -c 'import sys; print(sys.version); print(sys.executable)'
PYTHON="/实际路径/python3"
SKILL="/实际路径/lc-amazon-compliance-screening"
"$PYTHON" "$SKILL/scripts/csc.py" doctor --require-excel
```

Windows（PowerShell），若 `py -3` 不可用，可用 `python` 执行同样探测：

```powershell
py -3 -c "import sys; print(sys.version); print(sys.executable)"
$Python = "C:\实际路径\python.exe"
$Skill = "C:\实际路径\lc-amazon-compliance-screening"
& $Python "$Skill\scripts\csc.py" doctor --require-excel
```

以上变量值需替换为实际路径，不能照抄“实际路径”。Windows 的 `&` 用于执行带引号的程序路径。无需切换到 Skill 目录。

## 2. 依赖与自检

单品、JSON 和 CSV/TSV 流程仅用标准库；`.xlsx` 必须安装 `openpyxl>=3.1,<4`。`doctor` 检查 Python、依赖、规则及文件摘要；不带 `--require-excel` 时，缺少 Excel 依赖仅警告，带此参数则返回失败。自检不安装任何软件，也不代表其他操作系统已验证。

确认要安装依赖后，使用同一解释器：

```sh
"$PYTHON" -m pip install -r "$SKILL/requirements.txt"
```

```powershell
& $Python -m pip install -r "$Skill\requirements.txt"
```

如果现有 Python 环境禁止安装或不希望改动它，先用该解释器的 `-m venv` 在用户工作目录建立虚拟环境，再把 Python 变量改为其中的 `bin/python`（macOS）或 `Scripts\python.exe`（Windows）；无需激活脚本。不要使用 `sudo pip` 或绕过环境保护。若没有 pip/venv，请更换完整 Python 安装或宿主支持的依赖环境。

## 3. 使用文件传递资料

处理业务资料前先运行 `<Python> <Skill目录>/scripts/auth_gate.py`，通过后再执行本节步骤。
后续每条 CLI 业务命令会再次查询权限，不扣积分；断网或授权失败时停止。

让 AI 使用文件工具写 UTF-8 JSON，避免 Shell 引号和重定向编码差异。以下文件都放在用户工作目录：

product.json：

```json
{"title":"造型发泥","url":"https://www.amazon.com/dp/EXAMPLE","bullets":["膏状造型产品"]}
```

category.json：

```json
{"families":["cosmetics"],"children":false,"battery":"none","wireless":false,"mains":false,"primary_form":"paste_gel","form_evidence":"卖点：膏状造型产品"}
```

链接仅为格式示例，实际使用必须替换或删除；分类必须根据实际资料重新判断。

macOS：

```sh
"$PYTHON" "$SKILL/scripts/csc.py" quick --input "/工作目录/product.json" --category "/工作目录/category.json" --sites US --out "/工作目录/单品报告"
"$PYTHON" "$SKILL/scripts/csc.py" table --input "/工作目录/商品表.xlsx" --categories "/工作目录/categories.json" --out "/工作目录/筛查结果.xlsx"
```

Windows PowerShell：

```powershell
& $Python "$Skill\scripts\csc.py" quick --input "C:\工作目录\product.json" --category "C:\工作目录\category.json" --sites US --out "C:\工作目录\单品报告"
& $Python "$Skill\scripts\csc.py" table --input "C:\工作目录\商品表.xlsx" --categories "C:\工作目录\categories.json" --out "C:\工作目录\筛查结果.xlsx"
```

完整工作步骤和逐行分类文件结构见 SKILL.md。已有内联 `--category` 用法仍兼容，推荐新任务使用文件。

## 4. 文件与错误处理

- JSON 支持 UTF-8、UTF-8 BOM、带 BOM 的 UTF-16；CSV/TSV 还兼容 GB18030。未知编码请另存为 UTF-8。程序文件输出和 CLI 输出为 UTF-8，宿主捕获管道输出时也应按 UTF-8 解码。
- `.xlsx` 结果保留普通工作表、公式、样式、超链接并追加三列。复杂绘图等对象不保证完全保真；保留原文件。`.xlsm` 和 `.xls` 会被拒绝，转为 `.xlsx` 会去除宏。
- CSV 默认输出 CSV；指定 `.tsv` 则输出制表符分隔文件。“通用义务”单独输出为 CSV。
- Excel 占用目标文件或目录不可写时，关闭文件或改用可写位置；输出不能与输入相同。表格先写临时文件，再替换目标，保存失败保留已有目标。
- 自检发现文件缺失或摘要不一致，重新解压原发行包，不要绕过校验或拼接不同版本的文件。

## 5. 维护者打包与测试

源码克隆后先运行同级 `lc-amazon-compliance-screening-auth-go/build.sh`，需要 Go 工具链和 Python。
脚本默认构建四个平台鉴权器并更新 tools/auth.json 的二进制摘要；自定义输出目录只用于暂存，不修改技能配置，发行时须使用默认输出重新构建。发行白名单和其余文件摘要在下一步刷新。
构建结果按仓库规则不进入 Git，但必须进入交付 ZIP。

刷新清单后，使用选定解释器运行 `-B -m unittest discover -s "<Skill目录>/tests" -v`，并在鉴权器源码目录执行 `go test -race ./...`。测试使用回环模拟服务与合成 Token，原业务单元测试通过测试内 mock 隔离鉴权；发行代码不提供测试跳过开关。测试可在任意工作目录运行；安装 Excel 依赖后才能执行全部 Excel 保留测试。没有依赖的跳过项不能当作完整验收通过。

维护者修改代码后运行 `"<Python路径>" "<Skill目录>/scripts/build_distribution.py" --refresh-manifest --out "<交付目录>/lc-amazon-compliance-screening.zip"`（PowerShell 在命令前加 `&`）。新增发行文件先显式加入清单，再刷新摘要；脚本不扫描收集工作目录。普通重新打包省略 `--refresh-manifest`，文件不一致会停止。

ZIP 使用发行清单白名单，只含 Skill 资源及清单，不含用户表格、分类、缓存、虚拟环境或作者本机路径。运行模块、业务文档和随包测试依赖缺失时拒绝打包；任何目录下的 `config.local.json`（不区分大小写）均禁止收录。

ZIP 保存 macOS/Linux 鉴权器的执行权限；解压工具若丢失执行位，运行时仅在需要时尝试补齐，已可执行的只读安装不需要修改权限。发行前应在 macOS 和 Windows 分别解压、自检、运行测试及一个单品/表格样例；没有真实 Windows 测试记录时只能标注“已做适配，待实机验证”。
