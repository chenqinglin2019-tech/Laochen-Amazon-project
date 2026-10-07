# lc-amazon-data-crawl

Amazon 公开页面采集 Skill，包含关键词搜索、店铺、类目榜单和图片相似竞品流程。爬虫源码随 Skill 发布；安装脚本会在本机生成 runner，不需要下载其他人的 runner。

## 安装

准备 Python 3.10+、可用的 Chrome for Testing/Chromium，以及你自己的云端授权令牌。克隆仓库后运行：

```bash
bash scripts/install_for_user.sh            # macOS / Linux
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_for_user.ps1   # Windows
```

脚本会隐藏令牌输入，写入本机的 `config.local.json`，通过云端鉴权后生成相邻的 `lc-amazon-data-crawl-runner`、安装依赖并运行 `doctor`。公开的 `config.json` 保持空令牌。已有授权配置和 runner 不会被覆盖；也可以把目标 runner 路径作为脚本第一个参数。

如果 `doctor` 提示缺少 Chrome for Testing，在 runner 里执行一次 `./lc-amazon-data-crawl.sh install-browser`（Windows：`.\lc-amazon-data-crawl.cmd install-browser`）。

进入生成的 runner 后，可以先用自带的公开关键词样例试跑；此配置不要求卖家精灵或视觉模型。执行对应的 `*-dry-run`，再执行 `*-run`：

```bash
cd ../lc-amazon-data-crawl-runner
./lc-amazon-data-crawl.sh amazon-front-dry-run --config config/amazon_front_public_quickstart.json
./lc-amazon-data-crawl.sh amazon-front-run --config config/amazon_front_public_quickstart.json
```

店铺及关键词长任务使用 `amazon-front-supervise --config config/<job>.json`，在后台运行并把输出写入日志；它会按原冷却时间自动续采。最终监督结果见 `outputs/<job_id>/supervisor.json`，最后一次采集结果见 `run_summary.json`（退出码含义见 SKILL.md）。采集中用 `verify-output --job outputs/<job_id> --live` 核验已提交批次，结束后去掉 `--live` 核对JSONL及Excel。

云端令牌只负责 Skill 使用授权。使用真实任务时，请替换 `inputs/` 的示例内容。卖家精灵字段需要使用者自己的插件及登录状态；图片视觉模型需要使用者自己的模型 API 密钥。两者都不会随仓库提供。Amazon 买家账号不需要登录。详细参数见 [SKILL.md](SKILL.md) 和 [配置说明](references/configuration.md)。

## 发布边界

发布包请用 `python3 scripts/package_skill.py` 生成（自动排除缓存、本地凭据、输出和浏览器 Profile，并拒绝打包带令牌的 `config.json`）。仓库保留空令牌的 `config.json` 和示例配置。不要提交 `config.local.json`、实际输入、runner 的 `outputs/`、浏览器 Profile、模型密钥或历史采集数据。`tools/bin` 中的鉴权程序属于运行依赖；公开分发前须确认其发布许可。
