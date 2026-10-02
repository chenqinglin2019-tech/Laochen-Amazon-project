# 维护手册（V7）

适用：修改、测试或打包 skill，以及替换鉴权二进制。维护不调用模型，不读真实凭据，不访问真实账户。

## 测试环境

- 运行时：先执行 `python3 scripts/runtime_bootstrap.py verify --json`。缺依赖时，在用户确认后执行 `install --authorization user-confirmed --json`（隔离缓存；Pillow/NumPy 只装锁定 wheel；不用 sudo、不改系统 Python）。
  - 没有 ensurepip 的 Linux：先建 `python3 -m venv --without-pip`，再用 get-pip。
  - Chromium 缺系统库且无 sudo：`apt-get download` + `dpkg -x` 解到用户目录，再经 `LD_LIBRARY_PATH` 使用。
- 运行测试：在 `scripts/` 下逐模块执行 `P -X utf8 -m unittest test_x`（可 `xargs -P 4` 并行），另加 `node --test test_orchestrate_imagegen.mjs`。浏览器测试需要 `LC_LAYOUT_NODE/NODE_MODULES/CHROMIUM`，也可以由 selection.json 自动补齐。
- 测试隔离：
  - `pipeline_test_support.py` 会设置 `LC_SKIP_AUTH_PASS_FOR_TESTS=1`，并把模板库指到临时目录（`LC_TEMPLATE_LIBRARY_DIR`）。
  - 新测试必须导入它或自行设置这两个变量，否则会读写真实的用户库或鉴权记录。
- 已知的环境性基线失败（原版代码同样失败）：
  - `test_lc_prompting`：6 个 PNG 字节哈希子测试，zlib 版本不同导致。
  - `test_lc_runtime_io`：文件系统 ctime 粒度太粗。
  - `test_lc_style_reference`：写死了 `/Users/laochen/...` 路径。

## 失效不变量（改代码前必读）

- **不改 `PIPELINE_VERSION`**（3.0.0）。生成指纹 = 版本 + 编译后的提示字节 + 参考文件哈希。旧 job 的提示字节一旦改变，就会**重生图**，花费模型调用。
  - 新行为只挂在新开关上：`prompt_profile`、policy version 2、`layout.renderer=style_v1`、`design_resolution.schema_version=2`。
- **布局指纹冻结文件（b1）**：`lc_layout.py`、`render_layout.mjs`、`assets/layout-runtime.json`、`lc_layout_v3.py`、`lc_project_contracts.py`、`lc_typography.py`、`lc_title_effects.py`，以及 `_font_records` 中的 Noto 字体。
  - 改动它们会让所有在途项目重新本地渲染并重审。
  - 这些文件的哈希也进入 `typography_dispatch_fingerprint`，未派发的图需要重新 plan。
- **style_v1 路由**：`lc_layout_style.install()`（由 `lc_image_pipeline` 导入时执行）包装 `lc_layout` 的 `render_batch`/`layout_fingerprint`/`validate_layout_v3`/`_discover_runtime`。
  - 非 style 作业原样调用原函数，因此指纹逐字节不变。
  - style 作业额外绑定 `lc_layout_style.py`、`render_layout_style.mjs`、`faces.json` 和实际用到的字重文件，并通过临时替换 `_prepare_job`/`_font_payload`/`subprocess`（加锁，finally 还原）复用原批处理。
  - 扩展渲染只改这两个 fork 文件。
- **审核规则摘要**（`lc_review_rules` scoped_v1）：
  - 全文件哈希覆盖 `lc_assets`/`lc_quality`/`lc_design`/`lc_project_contracts`/`lc_review_rules`。
  - `lc_image_pipeline`/`lc_workflow`/`lc_delivery`/`lc_dependencies` 按函数 AST 切片计入，排除 `_EXCLUDED` 列出的编排函数。
  - V7 接受一次“审核纪元”：`lc_quality.py`（decide_job 无图层时回退 reference_edit）以及 `lc_image_pipeline` 非排除函数的改动。在途项目已审图需本地复核，不重生。
  - 此后编排改动只放在排除函数或新模块里。
- **tripwire**：`test_invalidation_tripwire.py` 用 `fixtures/tripwire_golden.json` 比对 5 个旧作业变体的提示字节、生成/布局/导出指纹和排字派发绑定。像素按解码后哈希，代码和字体按字节哈希。
  - 它失败就说明改动会让旧项目失效。只有经用户同意、并在报告中写明失效类别，才可以有意重建 golden。

## 状态、诊断与计时契约

- `status` 只读：私有快照，不 prepare、不渲染、不写文件和锁、不恢复事务。报告计数、容量证据、在途 attempt、dispatch、审核队列、阻断、`next_actions` 和计时覆盖。
- 容量：`--tool-capacity/-source/-reason` 把证据与整数容量分开记录；缺证据时报告为缺失，不伪造。
- 失败诊断：
  - 失败记录绑定命令、job 范围、业务输入指纹和运行时身份。同命令同输入连续两次同样的错误时报 `diagnosis_required`。
  - 诊断锁 10 分钟后过期（`DIAGNOSIS_TTL_SECONDS=600`）；瞬时错误（浏览器超时、文件锁、网络）不计次。
  - 批量命令只锁出错的那张图。deliver/delivery-check/compact/finalize 的失败按项目级记录，不把点名的图逐张标为待诊断。
  - 一次真实成功就清零。诊断字段不进视觉依赖。
- 调度：
  - 瞬时预算为首发＋2 次重试，429 不计入；`--reset-transient` 开启新一轮并写入历史，质量预算不受影响。
  - `QUALITY_REPAIR_LIMIT_REACHED` 是终态，plan 不自动解封。
  - `generating` 超过 1800 秒未入库时，下次 plan 记一次瞬时失败并释放槽位。
- 计时：
  - 分项记录参考、规划、就绪等待、工具调用（含网络和排队，不等于推理时间）、交接（`tool_returned → ingested`）、锁等待、编码、字体、渲染、审核准备/等待、导出和交付。
  - 批级共享开销只挂在首个任务上，重叠区间取并集，不按图重复累加。缺失事件记为 null，不外推补值。
  - 目标（需要真实样本验证）：交接 p95 ≤30 秒，无阻断派发空档 p95 ≤10 秒，无变化时模型/渲染/审核素材重建次数为 0。小样本必须标注 n，夹具基准不能代表生产提速。

## 平台说明

- Windows：
  - 鉴权和管线都可以用 `py -3`，所有 CLI 输出强制 UTF-8，路径接受盘符和 UNC。可变项目放在本地卷上。
  - Chrome for Testing 的 `--version` 常常没有输出。bootstrap 的 `_chromium_matches` 会回退到 `<version>.manifest` 或 Playwright `browsers.json` 的 revision；渲染器的发现逻辑经 `lc_layout_style.discover_runtime` 用同一匹配器确认。
  - Windows 上文件哈希缓存仍关闭（`lc_assets`，`os.name == "nt"`），每次布局指纹都会重新哈希字体，这是已知的性能项。
- runtime_bootstrap：
  - `verify` 成功后在运行时缓存目录写 `selection.json`（node/modules/chromium/python 路径）和 `verified.json`。
  - `verified.json` 有效期 7 天，身份包括解释器/Node/Playwright/Chromium/字体的文件 stat、`VERIFIED_SOURCES` 源码哈希、平台和 `LC_LAYOUT_*`。
  - 身份不变时 `verify` 直接返回缓存（约 0.1 秒）；`--fresh` 强制完整验证；验证失败会删除 stamp。
  - `lc_runtime_env` 从 selection.json 补齐缺少的 `LC_LAYOUT_*`；解释器缺 Pillow 时，改用选定的 Python 重新启动一次。

## 鉴权通过记录与二进制

- `auth_gate.py` 验证成功后写 `<缓存>/auth-pass.json`（`lc_auth_pass`，schema `LC-AUTH-PASS/1`）。
  - 内容只有时间、主机指纹和 config.json 的加盐指纹，**不存 token**；有效期 12 小时。更换 token 或换机器后需要重新鉴权。
  - `plan`/`deliver` 调用 `check_pass`，失败返回 `AUTH_PASS_REQUIRED` 且不写 manifest。测试用 `LC_SKIP_AUTH_PASS_FOR_TESTS=1` 绕过。
  - stdout 仍然只有 `{"ok":true,"message":"auth_passed"}`。
- 替换鉴权二进制：
  1. 把新文件放入 `tools/bin/`，文件名不变。
  2. 计算 SHA-256，同步更新 `references/auth-binaries.json`。
  3. 用合成配置和 loopback 服务测试（`test_auth_gate`），不访问真实账户。
  4. 执行 `build_release.py`，它会复核哈希。
  - 支持范围：Windows 仅 x64；macOS 需 ≥14（Playwright 要求）。

## 字体

- Noto（Sans/Serif/CJK/Arabic）是锁定的基础字体，列在 `assets/fonts/manifest.json`（sha256 + 许可证），由 doctor 校验。
- `assets/fonts/faces.json` 登记 style_v1 显示字体（`extra/*.woff2`，Latin 子集，来自 @fontsource 5.3.0，SIL OFL 1.1）：montserrat、poppins、oswald、bebas_neue、nunito、libre_baskerville、pacifico。许可证文件为 `extra/OFL-*.txt`。非拉丁字符回退到 Noto。
- 排除 Playfair Display、Dancing Script、Lora：它们带 Reserved Font Name，按 OFL，子集化属于修改，改后不得沿用原名。新增字体前先检查 LICENSE 中是否声明 RFN。
- 新增字体后必须同步更新 `faces.json`、`manifest.json` 和 `template_taxonomy.json` 的 `font_faces`/`font_face_fallback`。

## 模板库数据契约（摘要）

- `user_templates.json`（`lc_template_schema`，schema 2）：
  - `sources[{id,filename,sha256,set_id?,observation?}]`。
  - `families[{id,revision,name,product_profile,tokens{palette,fonts,photography},review…}]`。
  - `templates[{id,revision,family_id,slot_role,observed_shape,recipe,layout,generation,assets{reference/plate/thumb_sha256},review}]`。
- id/revision 只追加；取最新版用 `latest()`；按语义哈希去重。
- 绑定使用 `binding_entry`（id、revision、语义哈希、快照），`COMPILER_VERSION=1`。改编译器必须升级版本号，否则已采用的项目会报 brief 变化。
- 品类和属性词表、slot 角色、配方、字体都在 `assets/layouts/template_taxonomy.json`。

## 打包

`python3 scripts/build_release.py [--out DIR] [--name N] [--with-tests] [--platform all|mac|win|linux]`：

- 输出干净的 zip：用固定后台地址生成 token 留空的 config.json（不复制本机 config.json），排除缓存、`__pycache__`/`__MACOSX`、事务目录和 skill 内的用户模板文件；默认不含测试。
- `--platform` 只带对应平台的鉴权二进制；打包前会核对 `auth-binaries.json`。
- 发布包：默认名 `lc-amazon-image-studio-v7.zip`。维护包：`--with-tests --name lc-amazon-image-studio-v7-dev`。
