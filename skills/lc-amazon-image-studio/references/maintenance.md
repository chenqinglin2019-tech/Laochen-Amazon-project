# 维护手册（V8.1）

适用：修改、测试或打包 skill，以及替换鉴权二进制。维护不调用模型，不读真实凭据，不访问真实账户。

## 测试环境

- 运行时：`python3 scripts/runtime_bootstrap.py verify --json`。只需要 64 位 Python ≥3.11、Pillow 11–12、NumPy 1.26–2.x；已有兼容环境直接使用，缺少时在用户确认后执行 `install --authorization user-confirmed --json`（私有 venv，只装 Pillow 12.3.0 / NumPy 2.3.5 wheel，不用 sudo、不改系统 Python）。
  - `verify` 跑真实冒烟：导入全部 studio 模块，抠图→合成主图→在解码后的 JPEG 上校验 255，写入并回读 XMP。
  - 成功后在运行时缓存写 `selection.json` 和 `verified.json`（7 天有效；身份含解释器 stat、`VERIFIED_SOURCES` 源码哈希、平台和 `LC_STUDIO_PYTHON`）；缓存不可写时改写到用户临时目录；`--fresh` 强制重验。
  - 探测用 `-E -P -B`：忽略 PYTHONPATH、不把当前目录放进 sys.path，但保留用户 site-packages（与正常运行一致）。
  - `studio.py` 在当前解释器缺 Pillow/NumPy 时，会用 selection.json 里的 Python 重新启动一次。
- 运行测试：`cd scripts && P -X utf8 -m unittest discover -s . -p "test_*.py"`（约 1.5 分钟，约 150 个测试）。
- 测试隔离：用 `studio_test_support.isolated_env()`（设置 `LC_SKIP_AUTH_PASS_FOR_TESTS=1`、临时 `LC_TEMPLATE_LIBRARY_DIR`、`LC_AMAZON_STUDIO_CACHE`）。新测试必须用它或自行设置这些变量，否则会读写真实的用户库或鉴权记录。鉴权门禁测试用 `isolated_env(..., bypass_auth=False)`。

## 模块地图

| 模块 | 职责 |
|---|---|
| `studio.py` | CLI：init / add-photos / templates / plan / reserve / ingest-batch / deliver / status / reset；`plan`、`deliver` 先过 `check_pass` 再读项目 |
| `studio_project.py` | project.json 状态机与锁、图位、照片登记、预约/登记/失败/退回/重生/超时、预算；本套模特（`cast`：成员、定模特的图、epoch、预约时插入长相参考） |
| `studio_refs.py` | 色调光线板、产品照片遮挡副本、项目参考图（`refs/`）与其联系表 |
| `studio_catalog.py` | 内置＋用户模板的紧凑目录、联系表 |
| `studio_plan.py` | plan.json 校验与文案规则（替代旧的复核审查） |
| `studio_prompt.py` | 一次成图提示编译（内置模板、用户模板、custom、主图、重生） |
| `studio_main.py` | 主图：抠图、背景选择、纯白合成、JPEG 255 校验 |
| `studio_export.py` | 副图：按内容裁保留带、裁切风险、JPEG 4:4:4 导出、XMP 披露 |
| `lc_template_library.py` / `lc_template_intake.py` / `lc_template_schema.py` / `lc_style_plate.py` / `lc_design_templates.py` | 模板库、参考套图入库（含人物框、长相用词检查）、数据契约、风格底板/色调光线板/区域遮挡、内置模板 |
| `lc_frame_fit.py` | 画布 → 生图画幅与保留带 |
| `lc_jsonstore.py` / `lc_fsretry.py` | 加锁原子 JSON 写入 / Windows 文件占用重试 |
| `runtime_bootstrap.py` | 运行时检查与安装（仅标准库） |
| `build_release.py` | 打包 |

`test_import_graph.py` 保证发布模块只依赖发布模块、标准库、Pillow 和 NumPy。

## 主图纯白（阈值都在 `studio_main.py` 顶部）

- **白是构造出来的**：抠出产品后，透过遮罩贴到全 255 的画布上，遮罩外的像素从不写入；不画阴影。
- **抠图**：外圈拟合二次背景面（应对暗角），容差随噪声自适应，从边缘连通填充（行程编码并查集 `label()`，纯 NumPy，4000 px 照片约 2 秒）；带护栏的软阴影去除（去除量 ≤ 前景 30%、≥85% 在底部 45%、产品高度保留 ≥60%，否则保留产品）；贴附阴影残差、均匀底部阴影检测；去除封闭孔；去孤点；完整性（外接框缺口 >4%）；生成图的淡轮廓检查；边缘去色。
- **背景选择**（生成路线）：白 / #C8C8C8 / #8C8C8C 中按"分离度 p05 色差"和"产品颜色被误判为阴影的比例"打分，白色优先，其它背景风险低 0.10 以上才换；透明产品总用白色。
- **校验**：解码后不碰产品（遮罩外扩 1 px）的每个 8×8 块必须全为 255，四边全白，占比 0.85±0.012，居中 ±1%；q95 → q100 → PNG。
- **基准**：`P scripts/benchmark_main_white.py [--always-white] [--out x.json]`，10 种产品 × 8 种瑕疵（噪声、暗角、渐变、软/硬阴影、JPEG、偏白），记录首次通过、安全失败和"静默坏图"。V8 结果：首次通过 86.3%，3 次内通过 98.8%；唯一静默坏图是"玻璃＋透过玻璃可见的软阴影"（可见误差 1.06%）。
- 改阈值后必须重跑基准；静默坏图数不得增加。

## 不照抄参考（V8.1）

- **色调光线板**（`lc_style_plate.make_tone_board`）：
  - 算法：在长边 48 格的面积平均网格上，按每个通道拟合二次曲面；每轮只保留拟合最好的 60% 格子（`TONE_KEEP`），共重拟合 4 轮，再在 512 px 上求值。
  - 结果：局部的人物、产品、文字被当作离群点剔除，不会留下色块；旧底板（入库时没框人物）和未处理的 `--refs` 参考图同样安全。
  - `main_colours` 给出主色 hex，以文字进入提示。
  - `TONE_VERSION` 改算法时加 1，文件名随之变化（当前 `-t2`）。
  - 由库里的底板或项目参考图生成，存在项目的 `design/tones/`，从不写进共享模板库。
  - 测试保证：人物色块不留痕（区域偏色 <6 级），光线左右差保留 ≥50%，逐像素变化 ≤4 级，输出确定。
- **提示**（`studio_prompt.py`）：
  - 常量：`PRODUCT_ONLY`、`HIDDEN_NOTE`、`TONE_LINE`、`PERSON_LINE`、`IDENTITY_LINE`。
  - 用户模板只取 `USER_LOOK_KEYS`；`without_people` 按子句去掉人物描述。
  - 测试会检查所有内置模板 × 4 种画布的提示里都没有流程术语。
- **本套模特**（`studio_project.py`）：
  - 只有当前 epoch、以 `anchor` 身份预约的那次结果能定下模特；`clear_identity`/`recast`/`cast` 文本变更都会让 epoch 加 1。
  - 模特图丢失或被改动时自动清除并重新定。
  - 定模特的图失败时由下一位成员接替，结果会保存。
- **plan 校验**：`REFERENCE_WORDS`、`REAL_PERSON_WORDS` 在 `studio_plan.py` 顶部。改动时注意误报，例如 "dinner plates"、"scale reference" 必须通过。
- **共享库兼容**：V7.2 与 V8.1 共用模板库，库记录不得新增字段（schema 是封闭集合）。人物框只在入库包里，只影响底板像素。

## 副图保留带（`studio_export.py`）

- `CUT_RISK_LIMIT = 0.06`（带外强细节占比）、`EDGE_BUSY_FACTOR = 3.0`（裁切线内侧细节密度 / 中位数）。超过任一即 `FRAME_CONTENT_CUT`，自动重生 1 次。
- 带的位置按行/列强边缘能量滑动选择，裁切线附近 2% 的细节加权惩罚（保留边距）。
- 这些阈值需要用真实生图结果校准；改动后跑 `test_studio_cli` 的裁切用例。


## 鉴权通过记录与二进制

- `auth_gate.py` 验证成功后写 `<缓存>/auth-pass.json`（`lc_auth_pass`，schema `LC-AUTH-PASS/1`）。
  - 内容只有时间、主机指纹和 config.json 的加盐指纹，**不存 token**；有效期 12 小时。更换 token 或换机器后需要重新鉴权。
  - 主机指纹优先用稳定的机器 ID（macOS IOPlatformUUID、Windows MachineGuid、Linux machine-id），旧指纹存为 `host_alt`；缓存不可写时记录写到用户私有临时目录，`check_pass` 两处都查。
  - `plan`/`deliver` 调用 `check_pass`，失败返回 `AUTH_PASS_REQUIRED`，且不读、不写 project.json。测试用 `LC_SKIP_AUTH_PASS_FOR_TESTS=1` 绕过。
  - stdout 仍然只有 `{"ok":true,"message":"auth_passed"}`。
- 鉴权文件和二进制由 `test_auth_invariants.py` 按 SHA-256 固定，SKILL.md 中的鉴权段落也按原文哈希固定；改动它们需要用户明确同意。
- 替换鉴权二进制：
  1. 把新文件放入 `tools/bin/`，文件名不变。
  2. 计算 SHA-256，同步更新 `references/auth-binaries.json` 和 `test_auth_invariants.py`。
  3. 用合成配置和 loopback 服务测试（`test_auth_gate`、`test_configure_auth`），不访问真实账户。
  4. 执行 `build_release.py`，它会复核哈希。
  - 支持范围：macOS arm64/x64、Windows x64、Linux x64。


### 接收者鉴权故障排查

- 在 Skill 根目录运行只读安装诊断：macOS/Linux 用 `python3 scripts/diagnose_auth.py --json`；Windows 用 `py -3 scripts\diagnose_auth.py --json`。它仅检查平台、组件哈希、执行权限和 macOS 隔离标记，不读 config.json/token、不联网、不改文件、不写通过记录；`installation_ok` 不能证明账户鉴权成功。
- 启动失败：入口先校验哈希；Unix 组件已有执行权限时不再 chmod，Windows 不修改 POSIX 模式。macOS 仍只处理已校验组件的 `com.apple.quarantine`，不清理整个目录、不关闭系统安全机制。缺执行权限、隔离标记读取失败、移除失败分别给出两行脱敏原因。目录受限时，把 Skill 正式安装到当前用户可写且宿主允许访问的技能目录。
- 连接或服务不可用：可能是宿主未授权本地进程访问 backend_url、DNS/TLS/代理问题，或后端故障；此结果不能判断 token 无效。核对实际宿主网络权限和后端状态，权限获批或连接恢复后按 SKILL.md 重跑原入口一次；不新增自动重试、不禁用 TLS、不修改鉴权协议。
- 支持的组件是 macOS arm64/x64、Windows x64、Linux x64；Windows/Linux arm64 暂无原生组件，不能把平台分支模拟测试视为原生验收。正式扩展架构必须提供可信来源的对应二进制、更新哈希清单并进行原生测试。

## 平台说明

- Windows：所有 CLI 输出强制 UTF-8，路径接受盘符和 UNC；`lc_fsretry` 处理杀毒软件或索引器短暂占用文件；项目路径接近 260 字符时报 `PATH_TOO_LONG`。可变项目放在本地卷上。
- macOS：python.org 版本装完运行一次 "Install Certificates.command"（只影响 `install` 下载 wheel）。
- 没有 Node、浏览器或字体依赖；联系表文字用 Pillow 内置字体。

## 模板库数据契约（摘要）

- `user_templates.json`（`lc_template_schema`，schema 2）：
  - `sources[{id,filename,sha256,set_id?,observation?}]`。
  - `families[{id,revision,name,product_profile,tokens{palette,palette_names,fonts,photography},avoid,review…}]`。
  - `templates[{id,revision,family_id,slot_role,observed_shape,recipe,layout,generation,assets{reference/plate/thumb_sha256},observation,review}]`。
- id/revision 只追加，取最新版用 `latest()`，按语义哈希去重。品类、属性词表、slot 角色、配方、字体名都在 `assets/layouts/template_taxonomy.json`。
- 内置模板 `assets/layouts/design_templates.json` 的文字会进入提示：只写画面和版式描述，不写流程术语（approved、evidence、container、later 等）；`test_studio_plan_prompt` 会把 27 个模板 × 4 种画布全部编译一遍检查。
- 用户模板的 background/props/surface 是别人的场景，不进提示，也不在 `templates --family` 里给 Agent。

## 打包

`python3 scripts/build_release.py [--out DIR] [--name N] [--with-tests] [--platform all|mac|win|linux]`：

- 输出干净的 zip：生成 token 留空的 config.json（不复制本机 config.json），排除缓存、`__pycache__`/`__MACOSX` 和 skill 内的用户模板文件；默认不含测试、基准和 `studio_test_support.py`。
- `--platform` 只带对应平台的鉴权二进制；打包前逐个核对存在、非符号链接、哈希匹配，缺一即拒绝。zip 使用 Unix 权限元数据（组件 0755、config.json 0600）。
- 发布包：默认名 `lc-amazon-image-studio-v8.1.zip`。维护包：`--with-tests --name lc-amazon-image-studio-v8.1-dev`。
- 发布前：全量测试通过；解压后在没有 Node 的 PATH 下跑 `init`/`templates`，确认 `plan` 无鉴权记录时被拒绝。
