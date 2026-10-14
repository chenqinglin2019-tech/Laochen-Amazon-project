# lc-amazon-data-crawl

Amazon 公开页面采集 Skill，包含关键词搜索、店铺、类目榜单和图片相似竞品流程。爬虫源码随 Skill 发布；安装脚本会在本机生成 runner，不需要下载其他人的 runner。

## 安装

准备 Python 3.10+、日常 Chrome、OpenCLI CLI 与 Browser Bridge 扩展、卖家精灵，以及你自己的云端授权令牌。克隆仓库后运行：

```bash
bash scripts/install_for_user.sh            # macOS / Linux
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_for_user.ps1   # Windows
```

脚本会隐藏令牌输入，写入本机的 `config.local.json`，通过云端鉴权后生成相邻的 `lc-amazon-data-crawl-runner`、安装依赖并运行 `doctor`。公开的 `config.json` 保持空令牌。已有授权配置和 runner 不会被覆盖；也可以把目标 runner 路径作为脚本第一个参数。

关键词、店铺和找同款均不需要测试浏览器。只有类目流程缺少专用浏览器时，在 runner 里执行一次 `./lc-amazon-data-crawl.sh install-browser`（Windows：`.\lc-amazon-data-crawl.cmd install-browser`）。

进入生成的 runner 后，可以先用自带的公开关键词样例试跑；此配置需要已登录的卖家精灵，不需要视觉模型。先选好日常 Chrome 工作标签，运行后可以切去其他应用，脚本固定操作原标签。执行对应的 `*-dry-run`，再执行 `*-run`：

```bash
cd ../lc-amazon-data-crawl-runner
./lc-amazon-data-crawl.sh amazon-front-dry-run --config config/amazon_front_public_quickstart.json
./lc-amazon-data-crawl.sh amazon-front-run --config config/amazon_front_public_quickstart.json
```

店铺默认每店铺最多 1008 条，关键词默认每词最多 2000 条；明确数量或 `"all"` 可覆盖。先多次加载，结束时原生导出；达到上限与插件结束分别报告。详见 [插件流程与迁移](references/plugin-collection.md)。

找同款默认每来源最多 48 个候选；启动前必须确认退出卖家精灵账号，插件保持启用。使用 ASIN／链接在固定日常 Chrome 标签后台搜索，不下载图片再上传。见 [找同款流程与迁移](references/image-background.md)。

正式任务建议在后台运行并把输出写入日志；每次运行结束后 `outputs/<job_id>/run_summary.json` 会写明结果状态和下一步该做什么（退出码含义见 SKILL.md）。

云端令牌只负责 Skill 使用授权。使用真实任务时，请替换 `inputs/` 的示例内容。卖家精灵字段需要使用者自己的插件及登录状态；图片视觉模型需要使用者自己的模型 API 密钥。两者都不会随仓库提供。Amazon 买家账号不需要登录。详细参数见 [SKILL.md](SKILL.md) 和 [配置说明](references/configuration.md)。

## 发布边界

发布包请用 `python3 scripts/package_skill.py` 生成（自动排除缓存、本地凭据、输出和浏览器 Profile，并拒绝打包带令牌的 `config.json`）。仓库保留空令牌的 `config.json` 和示例配置。不要提交 `config.local.json`、实际输入、runner 的 `outputs/`、浏览器 Profile、模型密钥或历史采集数据。`tools/bin` 中的鉴权程序属于运行依赖；公开分发前须确认其发布许可。
